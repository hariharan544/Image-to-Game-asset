"""QA gate: turn stage metrics into a list of concrete issues using the spec's thresholds.

Each issue has a stable `code` - the supervisor's action space is keyed on these,
and the training data learns which fix resolves which code.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Optional

from .spec import AssetSpec


@dataclass
class Issue:
    code: str
    stage: str
    part: Optional[str]
    message: str
    value: Any = None
    limit: Any = None
    severity: str = "error"     # error = blocks the stage; warn = logged, sent to review

    def to_dict(self) -> dict:
        return asdict(self)


def _parts(result: dict) -> dict:
    return (result or {}).get("parts", {}) or {}


def check(stage: str, result: dict, spec: AssetSpec) -> list[Issue]:
    q = spec.qa
    issues: list[Issue] = []
    add = issues.append

    if stage == "cleanup":
        if not result.get("parts"):
            add(Issue("NO_PARTS", stage, None, "Imported model has no mesh parts"))
        if spec.rig.enabled and not result.get("rigged"):
            hint = (" - in Tripo Studio, auto-rig the model (retopologize first if it asks) and give the "
                    "rigged copy as rig_model / Rig source" if spec.model else "")
            add(Issue("NOT_RIGGED", stage, None, "Rig expected but the source model has no armature" + hint))
        if result.get("unit_fix"):
            add(Issue("UNITS_CONVERTED", stage, None,
                      f"model looked like centimetres; scaled by {result['unit_fix']}", severity="warn"))

    elif stage == "retopo":
        budget = spec.effective_tris
        total = result.get("total_tris", 0)
        limit = budget * (1 + q.max_tris_over_budget_pct / 100)
        if total > limit:
            add(Issue("OVER_BUDGET", stage, None, f"{total} tris > budget {budget}", total, budget))
        for part, r in _parts(result).items():
            if str(r.get("method", "")).startswith("failed"):
                add(Issue("RETOPO_FAILED", stage, part, "every retopology method failed"))
            elif str(r.get("method", "")).startswith("quadremesher-"):
                add(Issue("QUADREMESHER_FALLBACK", stage, part,
                          "Quad Remesher unavailable or failed; built-in remesher used",
                          r.get("method"), severity="warn"))
            elif "decimate" in str(r.get("method")) and spec.topology.method != "decimate":
                add(Issue("RETOPO_FALLBACK", stage, part,
                          "quad remesh failed, decimation was used (triangles, worse deformation)",
                          r.get("method"), severity="warn"))

    elif stage == "uv":
        target = spec.uv.texel_density_px_per_m
        tol = q.texel_density_tolerance
        for part, r in _parts(result).items():
            if not r.get("has_uv"):
                add(Issue("NO_UV", stage, part, "no UV map"))
                continue
            if str(r.get("packer", "")).startswith("uvpackmaster-") or (
                    spec.uv.packer == "uvpackmaster" and result.get("packer_fallback_reason")):
                add(Issue("UVPACKMASTER_FALLBACK", stage, part,
                          "UVPackmaster unavailable or failed; Blender's packer used",
                          r.get("packer") or result.get("packer_fallback_reason"), severity="warn"))
            if r["overlap_pct"] > q.max_uv_overlap_pct:
                add(Issue("UV_OVERLAP", stage, part, "overlapping UV islands", r["overlap_pct"], q.max_uv_overlap_pct))
            if r["utilization"] < q.min_uv_utilization:
                add(Issue("UV_LOW_UTILIZATION", stage, part, "too much empty texture space",
                          r["utilization"], q.min_uv_utilization, severity="warn"))
            cv = r.get("texel_density_cv")
            if cv is not None and cv > q.max_texel_density_cv:
                add(Issue("UV_STRETCH", stage, part, "uneven texel density (stretching)", cv, q.max_texel_density_cv))
            d = r.get("texel_density_px_per_m", 0)
            if target and not (target * (1 - tol) <= d <= target * (1 + tol)):
                add(Issue("TEXEL_DENSITY_OFF_TARGET", stage, part,
                          f"texel density {d:.0f} px/m vs target {target:.0f}", d, target, severity="warn"))
            if r.get("out_of_bounds_ratio", 0) > 0:
                add(Issue("UV_OUT_OF_BOUNDS", stage, part, "UVs outside 0-1", r["out_of_bounds_ratio"], 0))

    elif stage == "bake":
        for part, r in _parts(result).items():
            if "skipped" in r:
                add(Issue("BAKE_SKIPPED", stage, part, r["skipped"]))
                continue
            miss = r.get("bake_miss_ratio")
            if miss is not None and miss > q.max_bake_miss_ratio:
                add(Issue("BAKE_MISSES", stage, part, "rays missed the high mesh (black areas)", miss, q.max_bake_miss_ratio))

    elif stage == "skin":
        if "skipped" in (result or {}):
            if spec.rig.enabled:
                add(Issue("NO_ARMATURE", stage, None, result["skipped"]))
            return issues
        for part, r in _parts(result).items():
            if "skipped" in r and part not in spec.detachable_parts:
                add(Issue("NO_WEIGHTS", stage, part, r["skipped"]))
            if r.get("unweighted_verts", 0) > 0:
                add(Issue("UNWEIGHTED_VERTS", stage, part, "vertices without skin weights", r["unweighted_verts"], 0))
        if spec.rig.method == "auto_rig_pro" and (result or {}).get("rig_system") != "auto_rig_pro":
            add(Issue("ARP_FALLBACK", stage, None,
                      f"Auto-Rig Pro not used, Tripo skeleton kept: {result.get('arp_fallback_reason')}",
                      severity="warn"))
        bones = (result or {}).get("bones", 0)
        if spec.rig.max_bones and bones > spec.rig.max_bones:
            add(Issue("SKELETON_TOO_HEAVY", stage, None,
                      f"{bones} bones > {spec.rig.max_bones} recommended for {spec.platform}",
                      bones, spec.rig.max_bones, severity="warn"))
        missing = set(spec.rig.sockets) - set((result or {}).get("sockets", {}))
        for s in sorted(missing):
            add(Issue("SOCKET_MISSING", stage, None, f"socket {s} could not find its parent bone", severity="warn"))

    elif stage == "metrics":
        for part, r in _parts(result).items():
            m = r.get("mesh", {})
            if m.get("non_manifold_edges", 0) > q.max_non_manifold_edges:
                add(Issue("NON_MANIFOLD", stage, part, "non-manifold edges", m["non_manifold_edges"], q.max_non_manifold_edges))
            if m.get("ngons", 0) > q.max_ngons:
                add(Issue("NGONS", stage, part, "faces with more than 4 sides", m["ngons"], q.max_ngons))
            w = r.get("weights", {})
            if w.get("weighted") and w.get("unweighted_verts_pct", 0) > q.max_unweighted_verts_pct:
                add(Issue("UNWEIGHTED_VERTS", stage, part, "unweighted vertices", w["unweighted_verts_pct"], q.max_unweighted_verts_pct))
            if w.get("verts_over_influence_limit", 0) > 0:
                add(Issue("TOO_MANY_INFLUENCES", stage, part, "vertices over the bone influence limit",
                          w["verts_over_influence_limit"], spec.rig.max_influences))
    return issues


def blocking(issues: list[Issue]) -> list[Issue]:
    return [i for i in issues if i.severity == "error"]
