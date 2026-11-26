"""Supervisor contract shared by the rule engine and the AI (LLM) supervisor.

After every stage the supervisor sees an Observation (metrics, QA issues, the
attempt history, the director's notes) and must answer with a Decision whose
action comes from a fixed ACTION SPACE. A fixed action space keeps the AI safe
(it can only turn known knobs) and makes its decisions learnable: every
(observation -> action -> outcome) triple becomes training data.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Optional

# Each action: (stage it applies to, description shown to the AI, param transform)
Transform = Callable[[dict], dict]


def _set(**kv) -> Transform:
    return lambda p: {**p, **kv}


def _mul(key: str, factor: float, lo: float = 0.0, hi: float = 1e12, cast=float) -> Transform:
    return lambda p: {**p, key: cast(min(max(p.get(key, 1.0) * factor, lo), hi))}


def _add(key: str, delta: float, lo: float = -1e12, hi: float = 1e12, cast=float) -> Transform:
    return lambda p: {**p, key: cast(min(max(p.get(key, 0) + delta, lo), hi))}


ACTIONS: dict[str, tuple[str, str, Transform]] = {
    # retopology
    "retopo_voxel_first": ("retopo", "Voxel-remesh before QuadriFlow (fixes non-manifold AI meshes)", _set(method="voxel_quadriflow")),
    "retopo_decimate": ("retopo", "Use decimation instead of quad remesh (always succeeds, triangles)", _set(method="decimate")),
    "retopo_reduce_budget": ("retopo", "Lower the triangle budget by 10%", _mul("budget_scale", 0.9, 0.1, 2.0)),
    "retopo_new_seed": ("retopo", "Retry QuadriFlow with a different random seed", _add("seed", 1, cast=int)),
    "retopo_no_symmetry": ("retopo", "Disable X symmetry (asymmetric models)", _set(symmetry_x=False)),
    # UVs
    "uv_smart": ("uv", "Smart UV Project unwrap", _set(method="smart")),
    "uv_angle_seams": ("uv", "Seams on hard edges + angle-based unwrap", _set(method="angle_seams")),
    "uv_min_stretch": ("uv", "Seams + minimum-stretch unwrap (organic shapes)", _set(method="min_stretch")),
    "uv_lower_angle": ("uv", "Lower the island angle limit by 10 deg (less stretch, more islands)", _add("angle_limit_deg", -10, 20, 89)),
    "uv_raise_angle": ("uv", "Raise the island angle limit by 10 deg (fewer islands, better packing)", _add("angle_limit_deg", 10, 20, 89)),
    "uv_bigger_margin": ("uv", "Increase island margin by 50% (fixes bleeding)", _mul("margin_px", 1.5, 2, 64, int)),
    # baking
    "bake_more_extrusion": ("bake", "Double the bake cage extrusion (fixes black misses)", _mul("cage_extrusion_ratio", 2.0, 1e-4, 0.2)),
    "bake_less_extrusion": ("bake", "Halve the bake cage extrusion (fixes projection bleeding)", _mul("cage_extrusion_ratio", 0.5, 1e-4, 0.2)),
    "bake_more_samples": ("bake", "Double bake samples (noisy AO)", _mul("samples", 2.0, 1, 256, int)),
    # skinning
    "skin_lower_min_weight": ("skin", "Halve the minimum kept weight (fewer unweighted verts)", _mul("min_weight", 0.5, 1e-4, 0.2)),
}

GENERIC = {
    "accept": "Accept the stage as is (only warnings remain)",
    "escalate": "Stop and ask the creative director (cannot be fixed automatically)",
}


@dataclass
class Observation:
    asset: str
    stage: str
    attempt: int
    params: dict
    result: dict
    issues: list[dict]
    history: list[dict]            # previous attempts of this stage: params, issues, action
    notes: str = ""                # creative direction from the guide
    budget: dict = field(default_factory=dict)
    images: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Decision:
    action: str
    reason: str
    decided_by: str
    new_params: Optional[dict] = None

    def to_dict(self) -> dict:
        return asdict(self)


def actions_for(stage: str) -> dict[str, str]:
    out = {k: d for k, (s, d, _) in ACTIONS.items() if s == stage}
    out.update(GENERIC)
    return out


def apply_action(action: str, params: dict) -> dict:
    if action not in ACTIONS:
        return params
    return ACTIONS[action][2](dict(params))


class Supervisor:
    name = "base"

    def decide(self, obs: Observation) -> Decision:     # pragma: no cover - interface
        raise NotImplementedError

    def critique(self, images: list[str], reference_images: list[str], notes: str) -> Optional[dict]:
        """Optional visual review of finished previews. Returns {"verdict", "observations"} or None."""
        return None
