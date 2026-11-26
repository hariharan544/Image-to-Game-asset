"""The Forge pipeline: one image -> game-ready, rigged, multi-part asset.

  concept      Tripo: 1 image -> 4 views            [checkpoint: director approves views]
  generate     Tripo: views -> 3D (+ parts, + rig)
  cleanup      Blender: import, scale, pivot, clean       \
  retopo       Blender: clean quads inside the budget      |  each stage is checked by
  uv           Blender: unwrap + pack, measured            |  the QA gate; the supervisor
  bake         Blender: AI detail -> PBR maps              |  accepts, retries with new
  skin         Blender: weights onto the new mesh, sockets |  parameters, or escalates
  lods         Blender: LOD chain                          |  to the director
  metrics      Blender: final measurements                /
  previews     Blender: turntable renders (+ AI critique)
  final_review                                     [checkpoint: director approves asset]
  export       Blender: FBX + packed textures for each engine
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

ORDER = ["concept", "generate", "cleanup", "retopo", "uv", "bake", "skin", "lods",
         "metrics", "previews", "final_review", "export"]
BLENDER_STAGES = ["cleanup", "retopo", "uv", "bake", "skin", "lods", "metrics", "previews"]
SUPERVISED = {"cleanup", "retopo", "uv", "bake", "skin", "metrics"}


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
               "smooth_angle_deg": u.smooth_angle_deg},
        "bake": {"cage_extrusion_ratio": x.cage_extrusion_ratio, "samples": x.samples},
        "skin": {"max_influences": spec.rig.max_influences, "min_weight": spec.rig.min_weight},
        "lods": {"lod_ratios": t.lod_ratios},
        "metrics": {},
        "previews": {"resolution": 768, "engine": "BLENDER_WORKBENCH"},
    }.get(stage, {})


def match_parts(wanted: list[str], parts: list[str]) -> list[str]:
    """Guide names ('sword') -> actual part names ('Sword_mesh_2'), case-insensitive substring."""
    out = []
    for w in wanted:
        wl = w.lower()
        out += [p for p in parts if wl in p.lower() and p not in out]
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
            for stage in ORDER:
                if job.stage_done(stage):
                    continue
                self.say(f"[{job.m['asset']}] {stage} ...")
                job.set_stage(stage, RUNNING, started=time.time())
                getattr(self, f"_stage_{stage}")()
                if job.stage(stage)["status"] == RUNNING:
                    job.set_stage(stage, DONE, finished=time.time())
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
        if not spec.generation.use_multiview or spec.extra_images:
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
        if not self.job.artifact("tripo"):
            self.job.set_artifact("tripo", self.tripo.run(self.tripo.generate(self.job)))

    def _stage_final_review(self) -> None:
        def packet() -> Path:
            d = self.job.path("review", "final", ".keep").parent
            imgs = self.job.artifact("previews") or []
            for p in imgs:
                shutil.copy(p, d / Path(p).name)
            refs = [self.job.m["source_image"]] + list((self.job.artifact("concept_views") or {}).values())
            critique = self.sup.critique(imgs, refs, self.spec.notes)
            self.job.set_artifact("ai_critique", critique)
            warnings = [i for s in self.job.m["stages"].values() for a in s.get("attempts", [])[-1:]
                        for i in a.get("issues", []) if i.get("severity") == "warn"]
            lines = [f"# Final review: {self.spec.name}", "",
                     f"Type **{self.spec.type}** / tier **{self.spec.tier}** / style **{self.spec.style}**  ",
                     f"Budget {self.spec.effective_tris} tris, textures {self.spec.texture.size}px", "",
                     "## Renders", *[f"![{Path(p).stem}]({Path(p).name})" for p in imgs], "",
                     "## Warnings (not blocking)", *([f"- {w['code']} ({w.get('part')}): {w['message']}"
                                                      for w in warnings] or ["- none"]), ""]
            if critique:
                lines += [f"## AI critique ({critique.get('model')}): {critique['verdict']}",
                          *[f"- {o}" for o in critique["observations"]], ""]
            metrics = (self.job.stage("metrics").get("attempts") or [{}])[-1].get("result")
            lines += ["## Metrics", "```json", json.dumps(metrics, indent=2), "```"]
            (d / "REVIEW.md").write_text("\n".join(lines), encoding="utf-8")
            return d
        self._checkpoint("final", self.spec.review.final_checkpoint, packet)

    # ------------------------------------------------------------------ blender stages
    def _input_blend(self, stage: str) -> Optional[str]:
        idx = BLENDER_STAGES.index(stage)
        blends = self.job.m["artifacts"].get("blend", {})
        for prev in reversed(BLENDER_STAGES[:idx]):
            if prev in blends:
                return blends[prev]
        return None

    def _fixed_args(self, stage: str, attempt: int) -> dict:
        job, spec = self.job, self.spec
        a: dict[str, Any] = {}
        if stage != "cleanup":
            a["load_blend"] = self._input_blend(stage)
        if stage not in ("metrics", "previews"):
            a["save_blend"] = str(job.path("blend", f"{BLENDER_STAGES.index(stage):02d}_{stage}_a{attempt}.blend"))
        if stage == "cleanup":
            a["source"] = job.artifact("tripo")["source_for_blender"]
        elif stage == "uv":
            a["texture_size"] = spec.texture.size
        elif stage == "bake":
            uv_res = job.stage("uv")["attempts"][-1]["result"]
            a.update(texture_size=spec.texture.size, texture_dir=str(job.path("textures", ".keep").parent),
                     maps=spec.texture.maps, margin_px=spec.uv.margin_px, device=spec.texture.device,
                     uv_utilization={p: r.get("utilization", 0.7) for p, r in uv_res.get("parts", {}).items()})
        elif stage == "skin":
            parts = job.stage("cleanup")["attempts"][-1]["result"].get("parts", [])
            a.update(sockets=spec.rig.sockets,
                     rigid_parts=[])      # detachable props keep Tripo's weights (usually 100% to the hand)
            a["_parts"] = parts
        elif stage == "metrics":
            a.update(texture_size=spec.texture.size, max_influences=spec.rig.max_influences)
        elif stage == "previews":
            a["preview_dir"] = str(job.path("previews", ".keep").parent)
        return a

    def _blender(self, stage: str, args: dict, attempt: int) -> dict:
        log_path = self.job.path("logs", f"{stage}_a{attempt}.log")
        return run_stage(stage, {k: v for k, v in args.items() if not k.startswith("_")}, log_path,
                         blender=self.blender)

    def _supervised_stage(self, stage: str) -> None:
        job, spec = self.job, self.spec
        st = job.stage(stage)
        params = dict(st.get("params") or tunables(stage, spec))
        history: list[dict] = []
        last_decision_id: Optional[str] = None
        max_tries = spec.supervisor.max_retries_per_stage + 1
        for attempt in range(1, max_tries + 1):
            args = {**params, **self._fixed_args(stage, attempt)}
            try:
                result = self._blender(stage, args, attempt)
            except BlenderError as exc:
                job.add_attempt(stage, {"attempt": attempt, "params": params, "error": str(exc)[:2000]})
                self._fail(stage, str(exc).splitlines()[0])
            issues = [i.to_dict() for i in qa.check(stage, result, spec)]
            if last_decision_id:
                errors = [i for i in issues if i["severity"] == "error"]
                self.rec.record_outcome(last_decision_id, {
                    "issue_codes": sorted({i["code"] for i in errors}),
                    "error_count": len(errors),
                    "resolved": not errors})
            obs = Observation(
                asset=spec.name, stage=stage, attempt=attempt, params=params, result=result, issues=issues,
                history=history, notes=spec.notes,
                budget={"tris": spec.effective_tris, "texture": spec.texture.size, "tier": spec.tier,
                        "type": spec.type, "texel_density": spec.uv.texel_density_px_per_m})
            decision: Decision = self.sup.decide(obs)
            last_decision_id = self.rec.record_decision(str(job.root), obs.to_dict(), decision.to_dict())
            job.add_attempt(stage, {"attempt": attempt, "params": params, "result": result,
                                    "issues": issues, "decision": decision.to_dict(),
                                    "blend": args.get("save_blend")})
            self.say(f"   attempt {attempt}: {len(issues)} issue(s) -> {decision.action} ({decision.decided_by}): "
                     f"{decision.reason}")
            if decision.action == "accept":
                if args.get("save_blend"):
                    job.m["artifacts"].setdefault("blend", {})[stage] = args["save_blend"]
                job.set_stage(stage, DONE, params=params, finished=time.time())
                return
            if decision.action == "escalate":
                job.set_stage(stage, AWAITING_REVIEW, params=params)
                self._pause(f"escalation_{stage}", decision.reason)
            history.append({"attempt": attempt, "action": decision.action,
                            "issue_codes": sorted({i["code"] for i in issues})})
            params = decision.new_params or params
        job.set_stage(stage, AWAITING_REVIEW, params=params)
        self._pause(f"escalation_{stage}", f"still failing after {max_tries} attempts")

    def _stage_cleanup(self): self._supervised_stage("cleanup")
    def _stage_retopo(self): self._supervised_stage("retopo")
    def _stage_uv(self): self._supervised_stage("uv")
    def _stage_bake(self): self._supervised_stage("bake")
    def _stage_metrics(self): self._supervised_stage("metrics")

    def _stage_skin(self):
        if not self.spec.rig.enabled:
            self.job.set_stage("skin", SKIPPED)
            return
        self._supervised_stage("skin")

    def _stage_lods(self):
        args = {**tunables("lods", self.spec), **self._fixed_args("lods", 1)}
        res = self._blender("lods", args, 1)
        self.job.m["artifacts"].setdefault("blend", {})["lods"] = args["save_blend"]
        self.job.add_attempt("lods", {"attempt": 1, "result": res})

    def _stage_previews(self):
        args = {**tunables("previews", self.spec), **self._fixed_args("previews", 1)}
        try:
            res = self._blender("previews", args, 1)
        except BlenderError:          # no GPU / OpenGL (servers, CI): fall back to Cycles on CPU
            args["engine"] = "CYCLES"
            res = self._blender("previews", args, 2)
        self.job.set_artifact("previews", res["images"])
        self.job.add_attempt("previews", {"attempt": 1, "result": res})

    def _stage_export(self):
        spec, job = self.spec, self.job
        bake = job.stage("bake")["attempts"][-1]["result"]
        tex_maps = {p: r["maps"] for p, r in bake.get("parts", {}).items() if "maps" in r}
        parts = job.stage("cleanup")["attempts"][-1]["result"].get("parts", [])
        detachable = match_parts(spec.detachable_parts, parts)
        exports = {}
        for engine in spec.engines:
            args = {"load_blend": self._input_blend("previews"), "engine": engine, "asset_name": spec.name,
                    "export_dir": str(job.path("export", engine, ".keep").parent),
                    "texture_maps": tex_maps, "detachable_parts": detachable,
                    "unity_pipeline": spec.export.unity_pipeline}
            exports[engine] = self._blender("export", args, 1)
        job.set_artifact("exports", exports)
        missing = sorted(set(spec.detachable_parts) - {w for w in spec.detachable_parts if match_parts([w], parts)})
        if missing:
            self.say(f"   note: detachable parts not found among generated parts {parts}: {missing}")
