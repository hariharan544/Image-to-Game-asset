"""Stage: retopology - rebuild every low part to a clean mesh inside the triangle budget.

Methods (chosen by the guide, changed by the supervisor on retry):
  quadriflow        Blender's built-in quad remesher (needs a manifold mesh)
  voxel_quadriflow  voxel remesh first to force a manifold, then QuadriFlow
  decimate          collapse decimation - always works, triangles not quads
The chain falls through to the next method when one fails.
"""

from __future__ import annotations

import bmesh
import bpy

from . import common as C

CHAIN = {
    "quadriflow": ["quadriflow", "voxel_quadriflow", "decimate"],
    "voxel_quadriflow": ["voxel_quadriflow", "decimate"],
    "decimate": ["decimate"],
}


def _surface_area(obj) -> float:
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    area = sum(f.calc_area() for f in bm.faces)
    bm.free()
    return area


def _replace_mesh(obj, src_mesh) -> None:
    old = obj.data
    obj.data = src_mesh
    if old.users == 0:
        bpy.data.meshes.remove(old)


def _quadriflow(obj, target_tris: int, opts: dict) -> bool:
    C.select_only(obj)
    try:
        res = bpy.ops.object.quadriflow_remesh(
            mode="FACES",
            target_faces=max(int(target_tris / 2), 50),   # quads -> 2 tris each
            use_mesh_symmetry=bool(opts.get("symmetry_x", False)),
            use_preserve_sharp=bool(opts.get("preserve_hard_edges", True)),
            use_preserve_boundary=True,
            preserve_attributes=False,
            smooth_normals=False,
            seed=int(opts.get("seed", 0)),
        )
    except RuntimeError:
        return False
    return "FINISHED" in res and len(obj.data.polygons) > 0


def _voxel(obj, target_tris: int) -> None:
    area = max(_surface_area(obj), 1e-9)
    # pick a voxel size giving ~4x the target face count before QuadriFlow reduces it
    voxel = (area / max(target_tris * 4, 100)) ** 0.5
    mod = obj.modifiers.new("forge_voxel", "REMESH")
    mod.mode = "VOXEL"
    mod.voxel_size = voxel
    mod.adaptivity = 0.0
    C.apply_modifier(obj, mod.name)


def _decimate(obj, target_tris: int) -> bool:
    current = C.tri_count(obj)
    if current <= target_tris:
        return True
    mod = obj.modifiers.new("forge_decimate", "DECIMATE")
    mod.decimate_type = "COLLAPSE"
    mod.ratio = max(target_tris / current, 0.001)
    mod.use_collapse_triangulate = True
    C.apply_modifier(obj, mod.name)
    return True


def _retopo_part(obj, target_tris: int, method: str, opts: dict) -> str:
    backup = obj.data.copy()
    for step in CHAIN.get(method, CHAIN["quadriflow"]):
        # each attempt starts from the cleaned AI mesh
        _replace_mesh(obj, backup.copy())
        try:
            if step == "quadriflow" and _quadriflow(obj, target_tris, opts):
                break
            if step == "voxel_quadriflow":
                _voxel(obj, target_tris)
                if _quadriflow(obj, target_tris, opts):
                    break
            if step == "decimate" and _decimate(obj, target_tris):
                break
        except RuntimeError:
            continue
    else:
        step = "failed"
    bpy.data.meshes.remove(backup)
    # remeshing drops vertex groups / UVs; stale modifiers stay (armature) on purpose
    obj.vertex_groups.clear()
    return step


def run(args: dict) -> dict:
    total_budget = int(args["target_tris"])
    method = args.get("method", "quadriflow")
    budget_scale = float(args.get("budget_scale", 1.0))   # supervisor retry knob
    opts = {
        "symmetry_x": args.get("symmetry_x", False),
        "preserve_hard_edges": args.get("preserve_hard_edges", True),
        "seed": args.get("seed", 0),
    }
    lows = C.meshes_with_role("low")
    areas = {o.name: _surface_area(o) for o in lows}
    total_area = sum(areas.values()) or 1.0
    min_part = int(args.get("min_tris_per_part", 150))

    report = {}
    for obj in lows:
        part_budget = max(int(total_budget * budget_scale * areas[obj.name] / total_area), min_part)
        before = C.tri_count(obj)
        used = _retopo_part(obj, part_budget, method, opts)
        after = C.tri_count(obj)
        # never exceed budget: final safety decimate
        if after > part_budget * 1.05:
            _decimate(obj, part_budget)
            after = C.tri_count(obj)
            used += "+decimate"
        for p in obj.data.polygons:
            p.use_smooth = True
        report[obj.get(C.PART_PROP)] = {
            "budget": part_budget, "tris_before": before, "tris_after": after, "method": used,
        }
    return {"parts": report, "total_tris": sum(r["tris_after"] for r in report.values())}
