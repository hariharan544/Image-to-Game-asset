r"""The Forge pipeline: one image -> game-ready, rigged, multi-part asset per target engine.

Shared (paid once):
  concept      Tripo: 1 image -> 4 views            [checkpoint: director approves views]
  generate     Tripo: views -> 3D (+ parts, + rig)
  cleanup      Blender: import, scale, pivot, clean
Per target (unreal = AAA, unity = mobile), each with its own budgets:
  retopo@T     Blender: clean quads inside the budget      \  each stage is checked by
  uv@T         Blender: unwrap + pack, measured             |  the QA gate; the supervisor
  bake@T       Blender: AI detail -> PBR maps               |  accepts, retries with new
  skin@T       Blender: weights onto the new mesh, sockets  |  parameters, or escalates
  lods@T       Blender: LOD chain                           |  to the director
  metrics@T    Blender: final measurements                 /
  previews@T   Blender: turntable renders
Then:
  final_review                                     [checkpoint: director approves all targets]
  export@T     Blender: FBX + packed textures in the engine's conventions
"""

from __future__ import annotations

import json
import logging
import shutil
import time
from pathlib import Path
from typing import Any, Callable, Optional

from . import qa, tripo_stage
from .blender import BlenderError, run_stage
from .dataset import DatasetRecorder
from .job import AWAITING_REVIEW, DONE, FAILED, PENDING, RUNNING, SKIPPED, Job
from .spec import AssetSpec
from .supervisor import Decision, Observation, Supervisor, make_supervisor

log = logging.getLogger("forge")

SHARED = ["concept", "generate", "cleanup"]
TARGET_STAGES = ["retopo", "uv", "bake", "skin", "lods", "metrics", "previews"]
STAGE_NAMES = SHARED + TARGET_STAGES + ["final_review", "export"]


def stage_order(engines: list[str]) -> list[str]:
    """Concrete stage keys, e.g. ['concept', ..., 'retopo@unreal', ..., 'retopo@unity', ..., 'export@unity']."""
    return (SHARED + [f"{s}@{e}" for e in engines for s in TARGET_STAGES]
            + ["final_review"] + [f"export@{e}" for e in engines])


def split_key(key: str) -> tuple[str, Optional[str]]:
    name, _, target = key.partition("@")
    return name, (target or None)


class Stop(Exception):
    """Pipeline paused (review needed) or failed; message says why."""


# ----------------------------------------------------------------------------- parameters

def tunables(stage: str, spec: AssetSpec) -> dict:
    """The knobs the supervisor may turn for a stage (initial values from the guide)."""
    t, u, x = spec.topology, spec.uv, spec.texture
    return {
        "cleanup": {"target_height_m": t.target_height_m, "merge_distance_ratio": 1e-5},
        "retopo": {"target_tris": t.target_tris, "budget_scale": t.budget_scale, "method": t.method,
                   "symmetry_x": t.symmetry_x, "preserve_hard_edges": t.preserve_hard_edges, "seed": 0},
        "uv": {"method": u.method, "angle_limit_deg": u.angle_limit_deg, "margin_px": u.margin_px,
               "smooth_angle_deg": u.smooth_angle_deg, "packer": u.packer,
               "uvpm_search_time": u.uvpm_search_time},
        "bake": {"cage_extrusion_ratio": x.cage_extrusion_ratio, "samples": x.samples},
        "skin": {"max_influences": spec.rig.max_influences, "min_weight": spec.rig.min_weight},
        "lods": {"lod_ratios": t.lod_ratios},
        "metrics": {},
        "previews": {"resolution": 768, "engine": "BLENDER_WORKBENCH"},
    }.get(stage, {})


def match_parts(wanted: list[str], parts: list[str]) -> list[str]:
    """Guide names -> actual part names. An exact (case-insensitive) name wins, so 'tripo_part_1'
    never also grabs 'tripo_part_10'; otherwise substring ('sword' -> 'Sword_mesh_2')."""
    out = []
    for w in wanted:
        wl = w.lower()
        exact = [p for p in parts if p.lower() == wl]
        out += [p for p in (exact or [p for p in parts if wl in p.lower()]) if p not in out]
    return out


class Pipeline:
    def __init__(self, job: Job, recorder: DatasetRecorder, supervisor: Optional[Supervisor] = None,
                 blender: Optional[list[str]] = None, tripo=tripo_stage,
                 on_event: Callable[[str], None] = print):
        self.job = job
        self.spec = job.spec
        self.rec = recorder
        self.sup = supervisor or make_supervisor(self.spec.supervisor.backend)
        self.blender = blender
        self.tripo = tripo
        self.say = on_event

    # ------------------------------------------------------------------ driver
    def run(self) -> str:
        job = self.job
        job.m["status"] = RUNNING
        job.save()
        try:
            for key in stage_order(self.spec.engines):
                if job.stage_done(key):
                    continue
                self.say(f"[{job.m['asset']}] {key} ...")
                job.set_stage(key, RUNNING, started=time.time())
                name, target = split_key(key)
                fn = getattr(self, f"_stage_{name}")
                fn(target) if target else fn()
                if job.stage(key)["status"] == RUNNING:
                    job.set_stage(key, DONE, finished=time.time())
        except Stop as s:
            self.say(f"[{job.m['asset']}] paused: {s}")
            return job.m["status"]
        job.m["status"] = DONE
        job.save()
        self.say(f"[{job.m['asset']}] DONE -> {job.root / 'export'}")
        return DONE

    def _pause(self, checkpoint: str, why: str) -> None:
        self.job.m["status"] = AWAITING_REVIEW
        self.job.m["waiting_on"] = checkpoint
        self.job.save()
        raise Stop(f"waiting for review '{checkpoint}': {why}. "
                   f"Approve with: forge review {self.job.root} --checkpoint {checkpoint} --approve")

    def _tspec(self, key: str) -> AssetSpec:
        _, target = split_key(key)
        return self.spec.for_target(target) if target else self.spec

    def _fail(self, stage: str, why: str) -> None:
        self.job.set_stage(stage, FAILED, error=why)
        self.job.m["status"] = FAILED
        self.job.save()
        raise Stop(f"{stage} failed: {why}")

    def _checkpoint(self, name: str, enabled: bool, packet: Callable[[], Path]) -> None:
        if not enabled or self.spec.review.auto_approve:
            return
        cp = self.job.checkpoint(name)
        if cp["status"] == "approved":
            return
        if cp["status"] != "rejected":
            path = packet()
            self._pause(name, f"review packet at {path}")
        self._pause(name, "rejected - rerun with --redo-from <stage> after adjusting the guide")

    # ------------------------------------------------------------------ cloud stages
    def _stage_concept(self) -> None:
        spec = self.spec
        if spec.model or not spec.generation.use_multiview or spec.extra_images:
            self.job.set_stage("concept", SKIPPED)
            return
        if not self.job.artifact("concept_views"):
            self.job.set_artifact("concept_views", self.tripo.run(self.tripo.concept_views(self.job)))

        def packet() -> Path:
            d = self.job.path("review", "concept", ".keep").parent
            views = self.job.artifact("concept_views")
            for k, v in views.items():
                shutil.copy(v, d / f"{k}{Path(v).suffix}")
            shutil.copy(self.job.m["source_image"], d / f"input{Path(self.job.m['source_image']).suffix}")
            (d / "REVIEW.md").write_text(
                f"# Concept views: {spec.name}\n\nCheck that the 4 views match the input image and "
                f"your intent before 3D generation spends credits.\n\nNotes from the guide: {spec.notes or '-'}\n",
                encoding="utf-8")
            return d
        self._checkpoint("concept", spec.review.concept_checkpoint, packet)

    def _stage_generate(self) -> None:
        if self.job.artifact("tripo"):
            return
        if self.spec.model:
            # user-supplied model (e.g. Tripo Studio download): keep a copy inside the job
            src = Path(self.spec.model)
            dst = self.job.path("source", src.name)
            if src.resolve() != dst.resolve():
                shutil.copy(src, dst)
            art = {"source": "user_model", "generated": str(dst), "source_for_blender": str(dst)}
            if self.spec.rig_model:
                rsrc = Path(self.spec.rig_model)
                rdst = self.job.path("source", "rig_" + rsrc.name)
                shutil.copy(rsrc, rdst)
                art["rig_source"] = str(rdst)
            self.job.set_artifact("tripo", art)
            return
        self.job.set_artifact("tripo", self.tripo.run(self.tripo.generate(self.job)))

    def _stage_final_review(self) -> None:
        def packet() -> Path:
            d = self.job.path("review", "final", ".keep").parent
            previews = self.job.artifact("previews") or {}
            refs = [r for r in [self.job.m["source_image"]] + list((self.job.artifact("concept_views") or {}).values())
                    if Path(r).suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")]
            primary = previews.get(self.spec.primary_engine, [])
            critique = self.sup.critique(primary, refs, self.spec.notes)
            self.job.set_artifact("ai_critique", critique)
            lines = [f"# Final review: {self.spec.name}", "",
                     f"Type **{self.spec.type}** / tier **{self.spec.tier}** / style **{self.spec.style}**", ""]
            if critique:
                lines += [f"## AI critique ({critique.get('model')}): {critique['verdict']}",
                          *[f"- {o}" for o in critique["observations"]], ""]
            for engine in self.spec.engines:
                t = self.spec.for_target(engine)
                sub = d / engine
                sub.mkdir(exist_ok=True)
                for p in previews.get(engine, []):
                    shutil.copy(p, sub / Path(p).name)
                warnings = [i for k, st in self.job.m["stages"].items() if k.endswith(f"@{engine}")
                            for a in st.get("attempts", [])[-1:] for i in a.get("issues", [])
                            if i.get("severity") == "warn"]
                metrics = (self.job.stage(f"metrics@{engine}").get("attempts") or [{}])[-1].get("result")
                lines += [f"## {engine} ({t.platform})",
                          f"Budget {t.effective_tris} tris, textures {t.texture.size}px, "
                          f"{t.rig.max_influences} bone influences", "",
                          *[f"![{engine} {Path(p).stem}]({engine}/{Path(p).name})" for p in previews.get(engine, [])],
                          "", "Warnings (not blocking):",
                          *([f"- {w['code']} ({w.get('part')}): {w['message']}" for w in warnings] or ["- none"]),
                          "", "<details><summary>metrics</summary>", "", "```json",
                          json.dumps(metrics, indent=2), "```", "</details>", ""]
            (d / "REVIEW.md").write_text("\n".join(lines), encoding="utf-8")
            return d
        self._checkpoint("final", self.spec.review.final_checkpoint, packet)

    # ------------------------------------------------------------------ blender stages
    def _input_blend(self, key: str) -> Optional[str]:
        name, target = split_key(key)
        blends = self.job.m["artifacts"].get("blend", {})
        if target:
            idx = TARGET_STAGES.index(name) if name in TARGET_STAGES else len(TARGET_STAGES)
            for prev in reversed(TARGET_STAGES[:idx]):
                if f"{prev}@{target}" in blends:
                    return blends[f"{prev}@{target}"]
        return blends.get("cleanup")

    def _fixed_args(self, key: str, attempt: int) -> dict:
        job = self.job
        name, target = split_key(key)
        spec = self._tspec(key)
        tdir = target or "shared"
        a: dict[str, Any] = {}
        if name != "cleanup":
            a["load_blend"] = self._input_blend(key)
        if name not in ("metrics", "previews"):
            a["save_blend"] = str(job.path("blend", tdir, f"{STAGE_NAMES.index(name):02d}_{name}_a{attempt}.blend"))
        if name == "cleanup":
            a["source"] = job.artifact("tripo")["source_for_blender"]
            if job.artifact("tripo").get("rig_source"):
                a["rig_source"] = job.artifact("tripo")["rig_source"]
            a["detachable_parts"] = list(spec.detachable_parts)
            a["merge_body_parts"] = spec.merge_body_parts
        elif name == "uv":
            a["texture_size"] = spec.texture.size
        elif name == "bake":
            uv_res = job.stage(f"uv@{target}")["attempts"][-1]["result"]
            a.update(texture_size=spec.texture.size, texture_dir=str(job.path("textures", tdir, ".keep").parent),
                     maps=spec.texture.maps, margin_px=spec.uv.margin_px, device=spec.texture.device,
                     metallic_floor=spec.texture.metallic_floor,
                     uv_utilization={p: r.get("utilization", 0.7) for p, r in uv_res.get("parts", {}).items()})
        elif name == "skin":
            parts = job.stage("cleanup")["attempts"][-1]["result"].get("parts", [])
            a.update(sockets=spec.rig.sockets, rigid_parts=[], rig_method=spec.rig.method,
                     bind_engine=spec.rig.bind_engine,
                     detachable_parts=match_parts(spec.detachable_parts, parts))
        elif name == "metrics":
            a.update(texture_size=spec.texture.size, max_influences=spec.rig.max_influences)
        elif name == "previews":
            a["preview_dir"] = str(job.path("previews", tdir, ".keep").parent)
        return a

    def _blender(self, key: str, args: dict, attempt: int) -> dict:
        name, _ = split_key(key)
        log_path = self.job.path("logs", f"{key.replace('@', '_')}_a{attempt}.log")
        # paid add-ons need the user's add-ons loaded and (for their engines/GPU) a window
        addons = []
        if name == "retopo" and args.get("method") == "quadremesher":
            addons.append("quad remesher")
        if name == "uv" and args.get("packer") == "uvpackmaster":
            addons.append("uvpackmaster")
        if name == "skin" and args.get("rig_method") == "auto_rig_pro":
            addons.append("auto-rig pro")
        if name == "export" and args.get("rig_system") == "auto_rig_pro":
            addons.append("auto-rig pro")
        needs_addons = bool(addons)
        if needs_addons:
            args = {**args, "ensure_addons": addons}
        result = run_stage(name, {k: v for k, v in args.items() if not k.startswith("_")}, log_path,
                           blender=self.blender, windowed=needs_addons, factory_startup=not needs_addons)
        if name == "skin" and result.get("rig_system") == "arp_failed":
            # Auto-Rig Pro failed and saved nothing: rebuild skinning with the AI skeleton
            reason = result.get("arp_fallback_reason")
            fb = {k: v for k, v in args.items() if k != "ensure_addons"}
            fb["rig_method"] = "transfer"
            result = run_stage(name, {k: v for k, v in fb.items() if not k.startswith("_")},
                               self.job.path("logs", f"{key.replace('@', '_')}_a{attempt}_transfer.log"),
                               blender=self.blender)
            result["arp_fallback_reason"] = reason
        return result

    def _supervised_stage(self, key: str) -> None:
        job = self.job
        name, target = split_key(key)
        spec = self._tspec(key)
        st = job.stage(key)
        params = dict(st.get("params") or tunables(name, spec))
        history: list[dict] = []
        last_decision_id: Optional[str] = None
        max_tries = spec.supervisor.max_retries_per_stage + 1
        for attempt in range(1, max_tries + 1):
            args = {**params, **self._fixed_args(key, attempt)}
            try:
                result = self._blender(key, args, attempt)
            except BlenderError as exc:
                job.add_attempt(key, {"attempt": attempt, "params": params, "error": str(exc)[:2000]})
                self._fail(key, str(exc).splitlines()[0])
            issues = [i.to_dict() for i in qa.check(name, result, spec)]
            if last_decision_id:
                errors = [i for i in issues if i["severity"] == "error"]
                self.rec.record_outcome(last_decision_id, {
                    "issue_codes": sorted({i["code"] for i in errors}),
                    "error_count": len(errors),
                    "resolved": not errors})
            obs = Observation(
                asset=spec.name, stage=name, attempt=attempt, params=params, result=result, issues=issues,
                history=history, notes=spec.notes,
                budget={"platform": spec.platform, "engine": target or "shared", "tris": spec.effective_tris,
                        "texture": spec.texture.size, "tier": spec.tier, "type": spec.type,
                        "texel_density": spec.uv.texel_density_px_per_m})
            decision: Decision = self.sup.decide(obs)
            last_decision_id = self.rec.record_decision(str(job.root), obs.to_dict(), decision.to_dict())
            job.add_attempt(key, {"attempt": attempt, "params": params, "result": result,
                                  "issues": issues, "decision": decision.to_dict(),
                                  "blend": args.get("save_blend")})
            self.say(f"   attempt {attempt}: {len(issues)} issue(s) -> {decision.action} ({decision.decided_by}): "
                     f"{decision.reason}")
            if decision.action == "accept":
                if args.get("save_blend"):
                    job.m["artifacts"].setdefault("blend", {})[key] = args["save_blend"]
                job.set_stage(key, DONE, params=params, finished=time.time())
                return
            if decision.action == "escalate":
                job.set_stage(key, AWAITING_REVIEW, params=params)
                self._pause(f"escalation_{key}", decision.reason)
            history.append({"attempt": attempt, "action": decision.action,
                            "issue_codes": sorted({i["code"] for i in issues})})
            params = decision.new_params or params
        job.set_stage(key, AWAITING_REVIEW, params=params)
        self._pause(f"escalation_{key}", f"still failing after {max_tries} attempts")

    def _stage_cleanup(self): self._supervised_stage("cleanup")
    def _stage_retopo(self, t): self._supervised_stage(f"retopo@{t}")
    def _stage_uv(self, t): self._supervised_stage(f"uv@{t}")
    def _stage_bake(self, t): self._supervised_stage(f"bake@{t}")
    def _stage_metrics(self, t): self._supervised_stage(f"metrics@{t}")

    def _stage_skin(self, t):
        if not self.spec.rig.enabled:
            self.job.set_stage(f"skin@{t}", SKIPPED)
            return
        self._supervised_stage(f"skin@{t}")

    def _stage_lods(self, t):
        key = f"lods@{t}"
        args = {**tunables("lods", self._tspec(key)), **self._fixed_args(key, 1)}
        res = self._blender(key, args, 1)
        self.job.m["artifacts"].setdefault("blend", {})[key] = args["save_blend"]
        self.job.add_attempt(key, {"attempt": 1, "result": res})

    def _stage_previews(self, t):
        key = f"previews@{t}"
        args = {**tunables("previews", self._tspec(key)), **self._fixed_args(key, 1)}
        try:
            res = self._blender(key, args, 1)
        except BlenderError:          # no GPU / OpenGL (servers, CI): fall back to Cycles on CPU
            args["engine"] = "CYCLES"
            res = self._blender(key, args, 2)
        previews = dict(self.job.artifact("previews") or {})
        previews[t] = res["images"]
        self.job.set_artifact("previews", previews)
        self.job.add_attempt(key, {"attempt": 1, "result": res})

    def _stage_export(self, t):
        job, spec = self.job, self.spec.for_target(t)
        bake = job.stage(f"bake@{t}")["attempts"][-1]["result"]
        tex_maps = {p: r["maps"] for p, r in bake.get("parts", {}).items() if "maps" in r}
        parts = job.stage("cleanup")["attempts"][-1]["result"].get("parts", [])
        detachable = match_parts(spec.detachable_parts, parts)
        args = {"load_blend": self._input_blend(f"previews@{t}"), "engine": t, "asset_name": spec.name,
                "export_dir": str(job.path("export", t, ".keep").parent),
                "texture_maps": tex_maps, "detachable_parts": detachable,
                "unity_pipeline": spec.export.unity_pipeline,
                "ao_into_basecolor": spec.export.ao_into_basecolor}
        skin_att = job.stage(f"skin@{t}").get("attempts") or []
        skin_res = skin_att[-1].get("result", {}) if skin_att else {}
        if skin_res.get("rig_system") == "auto_rig_pro":
            args["rig_system"] = "auto_rig_pro"
            args["prop_bones"] = skin_res.get("arp", {}).get("props", {})
        exports = dict(job.artifact("exports") or {})
        exports[t] = self._blender(f"export@{t}", args, 1)
        job.set_artifact("exports", exports)
        missing = [w for w in spec.detachable_parts if not match_parts([w], parts)]
        if missing:
            self.say(f"   note: detachable parts not found among generated parts {parts}: {missing}")
