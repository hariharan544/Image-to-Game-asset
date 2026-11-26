"""Stage: UV unwrap + pack every low part, then measure UV quality.

Methods:
  smart        Smart UV Project (robust on any topology)
  angle_seams  mark seams on sharp edges + island borders, then angle-based unwrap
               (fewer, larger islands; better for organic shapes)
  min_stretch  same seams, Minimum Stretch unwrap
Each part gets its own 0-1 UV space (one texture set per part), which is what
makes props swappable.
"""

from __future__ import annotations

import math

import bmesh
import bpy

from . import common as C
from . import metrics


def _unwrap(obj, method: str, angle_deg: float, margin: float) -> None:
    C.select_only(obj)
    me = obj.data
    while me.uv_layers:
        me.uv_layers.remove(me.uv_layers[0])
    me.uv_layers.new(name="UVMap")
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    if method == "smart":
        bpy.ops.uv.smart_project(angle_limit=math.radians(angle_deg), island_margin=margin,
                                 area_weight=0.0, correct_aspect=True, scale_to_bounds=False)
    else:
        bpy.ops.uv.smart_project(angle_limit=math.radians(angle_deg), island_margin=margin)
        bpy.ops.uv.seams_from_islands(mark_seams=True)
        bm = bmesh.from_edit_mesh(me)
        for e in bm.edges:
            if len(e.link_faces) == 2 and e.calc_face_angle(0.0) > math.radians(angle_deg):
                e.seam = True
        bmesh.update_edit_mesh(me)
        bpy.ops.uv.unwrap(method="MINIMUM_STRETCH" if method == "min_stretch" else "ANGLE_BASED",
                          margin=margin)
    bpy.ops.object.mode_set(mode="OBJECT")


def _pack(obj, margin: float) -> None:
    C.select_only(obj)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.select_all(action="SELECT")
    bpy.ops.uv.average_islands_scale()
    bpy.ops.uv.pack_islands(rotate=True, margin=margin, shape_method="CONCAVE")
    bpy.ops.object.mode_set(mode="OBJECT")


def run(args: dict):
    """Returns the result dict, or a generator when UVPackmaster packs (its engine is async)."""
    if args.get("packer") == "uvpackmaster":
        from .addon_trial import has_op
        if has_op("uvpackmaster4.pack") and hasattr(bpy.context.scene, "uvpm4_props"):
            return _run(args, use_uvpm=True)
    gen = _run(args, use_uvpm=False)
    try:
        while True:
            next(gen)
    except StopIteration as stop:
        res = stop.value
    if args.get("packer") == "uvpackmaster":
        res["packer_fallback_reason"] = "UVPackmaster 4 (or its engine) not available"
    return res


def _run(args: dict, use_uvpm: bool):
    method = args.get("method", "smart")
    angle = float(args.get("angle_limit_deg", 66.0))
    tex = int(args.get("texture_size", 2048))
    margin_px = float(args.get("margin_px", 8))
    margin = margin_px / tex
    smooth_angle = float(args.get("smooth_angle_deg", 40.0))

    report = {}
    for obj in C.meshes_with_role("low"):
        _unwrap(obj, method, angle, margin)
        packer = "blender"
        if use_uvpm:
            ok = yield from _uvpm_pack(obj, tex, margin_px, float(args.get("uvpm_search_time", 3.0)),
                                       float(args.get("uvpm_timeout", 120.0)))
            packer = "uvpackmaster" if ok else "uvpackmaster-failed>blender"
            if not ok:
                _pack(obj, margin)
        else:
            _pack(obj, margin)
        C.select_only(obj)
        bpy.ops.object.shade_smooth_by_angle(angle=math.radians(smooth_angle))
        report[obj.get(C.PART_PROP)] = {**metrics.uv_metrics(obj, tex), "packer": packer}
    return {"parts": report}


# ----------------------------------------------------------------------------- UVPackmaster 4

def _uv_snapshot(obj) -> list:
    return [tuple(l.uv) for l in obj.data.uv_layers.active.data]


def _uvpm_pack(obj, tex: int, margin_px: float, search_time: float, timeout: float):
    """Generator: pack one part's islands into its own 0-1 tile with UVPackmaster 4.
    Measured on the user's PC: pack(mode_id="pack.single_tile") from a UV Editor context
    returns PASS_THROUGH/FINISHED and the engine updates the UVs ~1-3 s later."""
    import time

    from .addon_trial import view3d_override
    m = bpy.context.scene.uvpm4_props.default_main_props
    m.pixel_margin_enable = True                 # margin in pixels of *this* part's texture
    m.pixel_margin = int(round(margin_px))
    m.pixel_margin_tex_size = int(tex)
    m.rotation_enable = True
    m.rotation_step = 90
    m.normalize_scale = True                     # equal texel density across islands
    m.fully_inside = True
    m.heuristic_enable = search_time > 0         # spend a few seconds searching for a tighter pack
    if search_time > 0:
        m.heuristic_search_time = int(search_time)
    C.select_only(obj)
    bpy.ops.object.mode_set(mode="OBJECT")
    before = _uv_snapshot(obj)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    ov = view3d_override()
    area = ov.get("area")
    old_ui = area.ui_type if area else None
    t0 = time.time()
    try:
        if area:
            area.ui_type = "UV"
            ov["region"] = next((r for r in area.regions if r.type == "WINDOW"), None)
            ov["space_data"] = area.spaces.active
        bpy.context.scene.tool_settings.use_uv_select_sync = True
        with bpy.context.temp_override(**ov):
            bpy.ops.uvpackmaster4.pack(mode_id="pack.single_tile")
    except Exception:
        if area:
            area.ui_type = old_ui
        bpy.ops.object.mode_set(mode="OBJECT")
        return False
    last, stable, changed = None, 0, False
    try:
        while time.time() - t0 < timeout:
            yield 0.5
            bpy.ops.object.mode_set(mode="OBJECT")
            cur = _uv_snapshot(obj)
            bpy.ops.object.mode_set(mode="EDIT")
            if cur != before:
                changed = True
                stable = stable + 1 if cur == last else 0
                last = cur
                if stable >= 3 and time.time() - t0 > search_time:
                    break
    finally:                                     # always give the director's 3D view back
        if area:
            area.ui_type = old_ui
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
    return changed
