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


def run(args: dict) -> dict:
    method = args.get("method", "smart")
    angle = float(args.get("angle_limit_deg", 66.0))
    tex = int(args.get("texture_size", 2048))
    margin_px = float(args.get("margin_px", 8))
    margin = margin_px / tex
    smooth_angle = float(args.get("smooth_angle_deg", 40.0))

    report = {}
    for obj in C.meshes_with_role("low"):
        _unwrap(obj, method, angle, margin)
        _pack(obj, margin)
        C.select_only(obj)
        bpy.ops.object.shade_smooth_by_angle(angle=math.radians(smooth_angle))
        report[obj.get(C.PART_PROP)] = metrics.uv_metrics(obj, tex)
    return {"parts": report}
