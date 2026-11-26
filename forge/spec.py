"""Creative Guide -> fully resolved technical spec for each asset.

Every engine is a *target* with its own platform and budgets:
  unreal -> platform "aaa"     (asset type `tiers:` table)
  unity  -> platform "mobile"  (asset type `mobile:` table)
One Tripo generation is shared; Blender builds one game asset per target.

Layering per target (later wins):
  built-in defaults
  < asset_types/<type>.yaml  (+ the tier block of the target's platform)
  < styles/<style>.yaml
  < engines/<engine>.yaml
  < guide `defaults:`               < guide `defaults: targets: <engine>:`
  < the asset's `overrides:`        < the asset's `overrides: targets: <engine>:`
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
Platform = Literal["aaa", "mobile"]
TECH_SECTIONS = ("topology", "uv", "texture", "rig", "export", "qa")


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
    # quadremesher = Exoside Quad Remesher add-on (falls back to quadriflow when unavailable)
    method: Literal["quadremesher", "quadriflow", "voxel_quadriflow", "decimate"] = "quadremesher"
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
    # uvpackmaster = UVPackmaster 4 (tighter packing; needs its engine), falls back to blender
    packer: Literal["uvpackmaster", "blender"] = "uvpackmaster"
    uvpm_search_time: float = 3.0                # seconds of heuristic search per part (more = tighter)


class TextureSpec(BaseModel):
    size: int = 2048
    maps: list[str] = Field(default_factory=lambda: ["basecolor", "normal", "roughness", "metallic", "ao"])
    cage_extrusion_ratio: float = 0.01
    samples: int = 16
    device: Literal["CPU", "GPU"] = "GPU"


class RigSpec(BaseModel):
    enabled: bool = False
    # transfer     = keep Tripo's skeleton, copy its weights onto the new mesh
    # auto_rig_pro = rebuild as an Auto-Rig Pro rig (humanoids; UE5 Mannequin / Unity Humanoid export),
    #                falls back to transfer when ARP is missing or fails
    method: Literal["transfer", "auto_rig_pro"] = "transfer"
    bind_engine: Literal["HEAT_MAP", "PSEUDO_VOXELS", "VHDS"] = "HEAT_MAP"
    rig_type: str = "biped"
    spec: str = "tripo"
    model_version: Optional[str] = "v3.0-20260909"
    max_influences: int = 4
    max_bones: Optional[int] = None              # warn above this (mobile)
    min_weight: float = 0.01
    sockets: dict[str, str] = Field(default_factory=dict)   # socket bone -> parent key (hand_r, head...)


class ExportSpec(BaseModel):
    unity_pipeline: Literal["hdrp", "urp"] = "urp"
    ao_into_basecolor: bool = False              # mobile: bake AO into the base map, one texture less


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


class TargetSpec(BaseModel):
    """The technical sections resolved for one engine/platform."""
    engine: Engine
    platform: Platform
    topology: TopologySpec
    uv: UVSpec
    texture: TextureSpec
    rig: RigSpec
    export: ExportSpec
    qa: QASpec


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
    platform: Platform = "aaa"
    targets: dict[str, TargetSpec] = Field(default_factory=dict)

    @property
    def primary_engine(self) -> str:
        """The AAA engine when there is one: its skeleton spec is what Tripo rigs to."""
        return "unreal" if "unreal" in self.engines else self.engines[0]

    def for_target(self, engine: str) -> "AssetSpec":
        """A copy whose technical sections are the given engine's (used by every per-target stage)."""
        if engine not in self.targets:
            raise KeyError(f"{self.name} has no target {engine!r} (engines: {self.engines})")
        t = self.targets[engine]
        upd = {k: getattr(t, k) for k in TECH_SECTIONS}
        return self.model_copy(update={**upd, "engines": [engine], "platform": t.platform, "targets": {}})

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
    scalars = {k: v for k, v in project_defaults.items() if not isinstance(v, dict)}
    merged_top = deep_merge(scalars, {k: v for k, v in raw.items() if k != "overrides"})
    a_type = merged_top.get("type", "prop")
    tier = merged_top.get("tier", "standard")
    style = merged_top.get("style", "realistic")
    engines = merged_top.get("engines", ["unreal", "unity"])

    type_prof = _load_yaml(profile_dir / "asset_types" / f"{a_type}.yaml")
    if not type_prof:
        raise ValueError(f"unknown asset type profile: {a_type}")
    tier_tables = {"aaa": type_prof.pop("tiers", {}), "mobile": type_prof.pop("mobile", {})}

    style_path = profile_dir / "styles" / f"{style}.yaml"
    if not style_path.exists():
        raise ValueError(f"unknown style profile: {style} (add guides/profiles/styles/{style}.yaml)")
    style_prof = _load_yaml(style_path)

    proj_tech = {k: v for k, v in project_defaults.items() if isinstance(v, dict) and k != "targets"}
    proj_targets = project_defaults.get("targets", {}) or {}
    overrides = dict(raw.get("overrides", {}) or {})
    ov_targets = overrides.pop("targets", {}) or {}
    top = {k: v for k, v in merged_top.items() if not isinstance(v, dict) or k == "extra_images"}

    per_target: dict[str, AssetSpec] = {}
    platforms: dict[str, str] = {}
    for e in engines:
        eprof = _load_yaml(profile_dir / "engines" / f"{e}.yaml")
        platform = eprof.pop("platform", "aaa")
        table = tier_tables.get(platform) or tier_tables["aaa"]
        merged: dict[str, Any] = {}
        for layer in (type_prof, table.get(tier, {}), style_prof, eprof, proj_tech,
                      proj_targets.get(e, {}), top, overrides, ov_targets.get(e, {})):
            merged = deep_merge(merged, layer)
        per_target[e] = AssetSpec(**merged, platform=platform)
        platforms[e] = platform

    primary = "unreal" if "unreal" in engines else engines[0]
    spec = per_target[primary]
    spec.targets = {e: TargetSpec(engine=e, platform=platforms[e],
                                  **{k: getattr(s, k) for k in TECH_SECTIONS})
                    for e, s in per_target.items()}
    return spec


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
