"""Deterministic supervisor: issue code -> ordered list of fixes to try.

Always available, and the fallback whenever the AI supervisor is offline or
answers with something invalid. Its decisions also seed the training data.
"""

from __future__ import annotations

from .base import Decision, Observation, Supervisor, apply_action

PLAYBOOK: dict[str, list[str]] = {
    "OVER_BUDGET": ["retopo_reduce_budget", "retopo_reduce_budget", "retopo_decimate"],
    "RETOPO_FAILED": ["retopo_voxel_first", "retopo_decimate"],
    "UV_OVERLAP": ["uv_bigger_margin", "uv_smart", "uv_lower_angle"],
    "UV_STRETCH": ["uv_lower_angle", "uv_min_stretch", "uv_angle_seams"],
    "UV_OUT_OF_BOUNDS": ["uv_smart"],
    "NO_UV": ["uv_smart"],
    "BAKE_MISSES": ["bake_more_extrusion", "bake_more_extrusion", "bake_less_extrusion"],
    "UNWEIGHTED_VERTS": ["skin_lower_min_weight"],
}


class RuleSupervisor(Supervisor):
    name = "rules"

    def decide(self, obs: Observation) -> Decision:
        errors = [i for i in obs.issues if i.get("severity", "error") == "error"]
        if not errors:
            why = "no blocking issues" + (f"; {len(obs.issues)} warning(s) sent to review" if obs.issues else "")
            return Decision("accept", why, self.name)
        tried = {h.get("action") for h in obs.history}
        for issue in errors:
            for action in PLAYBOOK.get(issue["code"], []):
                count_tried = sum(1 for h in obs.history if h.get("action") == action)
                allowed = PLAYBOOK[issue["code"]].count(action)
                if count_tried < allowed:
                    return Decision(action, f"{issue['code']}: {issue['message']}", self.name,
                                    apply_action(action, obs.params))
        codes = sorted({i["code"] for i in errors})
        return Decision("escalate", f"no automatic fix left for {codes} (tried {sorted(t for t in tried if t)})", self.name)

    def critique(self, images, reference_images, notes):
        return None

