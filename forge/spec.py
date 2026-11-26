"""Creative Guide -> fully resolved technical spec for each asset.

Layering (later wins):
  built-in defaults
  < asset_types/<type>.yaml  (+ its tier block)
  < styles/<style>.yaml
  < engines/<engine>.yaml    (each engine; strictest influence limit wins)
  < guide `defaults:` block
  < the asset's own `overrides:` block
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Literal, Optional

import yaml
from pydantic import BaseModel, Field, field_validator

PROFILE_DIR = Path(__file__).resolve().parent.parent / "guides" / "profiles"

AssetType = Literal["humanoid", "creature", "weapon", "prop", "vehicle", "environment"]
Tier = Literal["hero", "standard", "background"]
Engine = Literal["unity", "unreal"]


class GenerationSpec(BaseModel):
    model_version: Optional[str] = None          # None = Tripo SDK default; set the newest from Tripo docs
    use_multiview: bool = False                  # ask Tripo for front/left/back/right views first
    texture_quality: Literal["standard", "detailed"] = "detailed"
    geometry_quality: Literal["standard", "detailed"] = "detailed"
    generate_parts: bool = False                 # Tripo splits the model into parts
    segment: bool = False                        # run Tripo mesh segmentation + completion after generation
    face_limit: Optional[int] = None
    seed: Optional[int] = None


class TopologySpec(BaseModel):
    target_tris: int = 10000
    method: Literal["quadriflow", "voxel_quadriflow", "decimate"] = "quadriflow"
    budget_scale: float = 1.0
    symmetry_x: bool = False
    preserve_hard_edges: bool = True
    lod_ratios: list[float] = Field(default_factory=lambda: [1.0, 0.5, 0.25, 0.12])
    target_height_m: Optional[float] = None      # real-world height; None keeps AI scale


class UVSpec(BaseModel):
    method: Literal["smart", "angle_seams", "min_stretch"] = "smart"
    angle_limit_deg: float = 66.0
    margin_px: int = 8
    smooth_angle_deg: float = 40.0
    texel_density_px_per_m: float = 512.0


class TextureSpec(BaseModel):
    size: int = 2048
    maps: list[str] = Field(default_factory=lambda: ["basecolor", "normal", "roughness", "metallic", "ao"])
    cage_extrusion_ratio: float = 0.01
    samples: int = 16
    device: Literal["CPU", "GPU"] = "GPU"


class RigSpec(BaseModel):
    enabled: bool = False
    rig_type: str = "biped"
    spec: str = "tripo"
    model_version: Optional[str] = "v3.0-20260909"
    max_influences: int = 4
    min_weight: float = 0.01
    sockets: dict[str, str] = Field(default_factory=dict)   # socket bone -> parent key (hand_r, head...)


class ExportSpec(BaseModel):
    unity_pipeline: Literal["hdrp", "urp"] = "hdrp"


class QASpec(BaseModel):
    max_tris_over_budget_pct: float = 5.0
    max_uv_overlap_pct: float = 0.5
    min_uv_utilization: float = 0.55
    max_texel_density_cv: float = 0.35
    texel_density_tolerance: float = 0.5        # +-50% of the target density is acceptable
    max_non_manifold_edges: int = 0
    max_bake_miss_ratio: float = 0.02
    max_unweighted_verts_pct: float = 0.0
    max_ngons: int = 0


class ReviewSpec(BaseModel):
    concept_checkpoint: bool = True              # approve the generated views before spending on 3D
    final_checkpoint: bool = True                # approve the finished asset
    auto_approve: bool = False                   # skip both (batch runs once the supervisor is trusted)


class SupervisorSpec(BaseModel):
    backend: Literal["rules", "llm"] = "rules"
    max_retries_per_stage: int = 3


class AssetSpec(BaseModel):
    name: str
    image: str
    extra_images: dict[str, str] = Field(default_factory=dict)   # left/back/right reference views
    type: AssetType = "prop"
    tier: Tier = "standard"
    style: str = "realistic"
    engines: list[Engine] = Field(default_factory=lambda: ["unreal", "unity"])
    detachable_parts: list[str] = Field(default_factory=list)    # exported as separate swappable meshes
    notes: str = ""                                              # creative direction for the supervisor
    generation: GenerationSpec = Field(default_factory=GenerationSpec)
    topology: TopologySpec = Field(default_factory=TopologySpec)
    uv: UVSpec = Field(default_factory=UVSpec)
    texture: TextureSpec = Field(default_factory=TextureSpec)
    rig: RigSpec = Field(default_factory=RigSpec)
    export: ExportSpec = Field(default_factory=ExportSpec)
    qa: QASpec = Field(default_factory=QASpec)
    review: ReviewSpec = Field(default_factory=ReviewSpec)
    supervisor: SupervisorSpec = Field(default_factory=SupervisorSpec)

    @field_validator("engines")
    @classmethod
    def _engines_nonempty(cls, v):
        if not v:
            raise ValueError("at least one engine is required")
        return v

    @property
    def effective_tris(self) -> int:
        return int(self.topology.target_tris * self.topology.budget_scale)


class Guide(BaseModel):
    project: str
    assets: list[AssetSpec]
    base_dir: Path


# ----------------------------------------------------------------------------- merging


def deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def resolve_asset(raw: dict, project_defaults: dict, profile_dir: Path = PROFILE_DIR) -> AssetSpec:
    merged_top = deep_merge(project_defaults, {k: v for k, v in raw.items() if k != "overrides"})
    a_type = merged_top.get("type", "prop")
    tier = merged_top.get("tier", "standard")
    style = merged_top.get("style", "realistic")
    engines = merged_top.get("engines", ["unreal", "unity"])

    type_prof = _load_yaml(profile_dir / "asset_types" / f"{a_type}.yaml")
    tiers = type_prof.pop("tiers", {})
    if a_type and not type_prof and not tiers:
        raise ValueError(f"unknown asset type profile: {a_type}")
    layers = [type_prof, tiers.get(tier, {})]

    style_path = profile_dir / "styles" / f"{style}.yaml"
    if not style_path.exists():
        raise ValueError(f"unknown style profile: {style} (add guides/profiles/styles/{style}.yaml)")
    layers.append(_load_yaml(style_path))

    engine_layers = [_load_yaml(profile_dir / "engines" / f"{e}.yaml") for e in engines]
    merged: dict[str, Any] = {}
    for layer in layers:
        merged = deep_merge(merged, layer)
    # rig spec from the first engine, influence limit = strictest engine
    if engine_layers:
        merged = deep_merge(merged, engine_layers[0])
        infl = [l.get("rig", {}).get("max_influences") for l in engine_layers if l.get("rig")]
        infl = [i for i in infl if i]
        if infl:
            merged = deep_merge(merged, {"rig": {"max_influences": min(infl)}})
        for l in engine_layers[1:]:
            merged = deep_merge(merged, {"export": l.get("export", {})})

    proj_tech = {k: v for k, v in project_defaults.items() if isinstance(v, dict)}
    merged = deep_merge(merged, proj_tech)
    merged = deep_merge(merged, {k: v for k, v in merged_top.items() if not isinstance(v, dict) or k in ("extra_images",)})
    merged = deep_merge(merged, raw.get("overrides", {}))
    return AssetSpec(**merged)


def load_guide(path: str | Path, profile_dir: Path = PROFILE_DIR) -> Guide:
    path = Path(path)
    data = _load_yaml(path)
    defaults = dict(data.get("defaults", {}))
    for key in ("engines", "style", "tier"):
        if key in data:
            defaults.setdefault(key, data[key])
    assets = [resolve_asset(a, defaults, profile_dir) for a in data.get("assets", [])]
    names = [a.name for a in assets]
    dupes = {n for n in names if names.count(n) > 1}
    if dupes:
        raise ValueError(f"duplicate asset names in guide: {sorted(dupes)}")
    return Guide(project=data.get("project", path.stem), assets=assets, base_dir=path.parent)
