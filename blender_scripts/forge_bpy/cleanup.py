"""Stage: import the AI-generated model and clean it up.

Result in the .blend:
  FORGE_HIGH  one cleaned copy of every part (bake + weight source, never exported)
  FORGE_LOW   one working copy of every part (replaced by retopology next)
  FORGE_RIG   the armature, if the source was rigged
"""

from __future__ import annotations

import os

import bmesh
import bpy
from mathutils import Vector

from . import common as C


def _clear_scene() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def _import(path: str) -> None:
    ext = os.path.splitext(path)[1].lower()
    if ext in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=path)
    elif ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=path)
    elif ext == ".obj":
        bpy.ops.wm.obj_import(filepath=path)
    else:
        raise ValueError(f"Unsupported model format: {ext}")


def _world_bbox(objs) -> tuple[Vector, Vector]:
    lo = Vector((1e18, 1e18, 1e18))
    hi = Vector((-1e18, -1e18, -1e18))
    for o in objs:
        for corner in o.bound_box:
            w = o.matrix_world @ Vector(corner)
            lo = Vector(map(min, lo, w))
            hi = Vector(map(max, hi, w))
    return lo, hi


def _clean_mesh(obj: bpy.types.Object, merge_dist: float) -> dict:
    me = obj.data
    bm = bmesh.new()
    bm.from_mesh(me)
    v0 = len(bm.verts)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=merge_dist)
    bmesh.ops.dissolve_degenerate(bm, edges=bm.edges, dist=merge_dist * 0.1)
    loose_v = [v for v in bm.verts if not v.link_faces]
    bmesh.ops.delete(bm, geom=loose_v, context="VERTS")
    loose_e = [e for e in bm.edges if not e.link_faces]
    bmesh.ops.delete(bm, geom=loose_e, context="EDGES")
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    merged = v0 - len(bm.verts)
    bm.to_mesh(me)
    bm.free()
    me.update()
    return {"verts_removed": merged}


def run(args: dict) -> dict:
    src = args["source"]
    target_height = args.get("target_height_m")       # None = keep AI scale
    merge_dist_ratio = float(args.get("merge_distance_ratio", 1e-5))

    _clear_scene()
    _import(src)
    C.ensure_object_mode()

    arm = C.find_armature()
    # bone display shapes / helper meshes the importer creates are not asset parts
    shape_meshes = set()
    for a in (o for o in bpy.data.objects if o.type == "ARMATURE"):
        for pb in a.pose.bones:
            if pb.custom_shape is not None:
                shape_meshes.add(pb.custom_shape.name)
                pb.custom_shape = None
    for o in list(bpy.data.objects):
        in_helper = any(c.name.startswith("glTF_not_exported") for c in o.users_collection)
        if o.type == "MESH" and (o.name in shape_meshes or in_helper):
            bpy.data.objects.remove(o)
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    if not meshes:
        raise RuntimeError("Imported file contains no meshes")

    # --- normalise scale and pivot: bottom-centre at the origin -------------
    roots = [o for o in bpy.data.objects if o.parent is None]
    lo, hi = _world_bbox(meshes)
    size = hi - lo
    scale = 1.0
    if target_height and size.z > 1e-9:
        scale = float(target_height) / size.z
    offset = Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z))
    for r in roots:
        r.location = (r.location - offset) * scale
        r.scale = r.scale * scale
    bpy.context.view_layer.update()
    C.select_only(*bpy.data.objects)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

    diag = (size * scale).length
    merge_dist = max(diag * merge_dist_ratio, 1e-7)

    high_coll = C.get_collection(C.HIGH_COLLECTION, hide_render=True)
    low_coll = C.get_collection(C.LOW_COLLECTION)
    parts = []
    stats = {}
    used_names: set[str] = set()
    for i, obj in enumerate(meshes):
        part = C.safe_name(obj.name)
        while part in used_names:
            part = f"{part}_{i}"
        used_names.add(part)
        stats[part] = _clean_mesh(obj, merge_dist)
        obj.name = f"{part}_high"
        obj[C.PART_PROP] = part
        obj[C.ROLE_PROP] = "high"
        low = C.duplicate(obj, f"{part}_low")
        low[C.ROLE_PROP] = "low"
        C.move_to_collection(obj, high_coll)
        C.move_to_collection(low, low_coll)
        parts.append(part)

    if arm is not None:
        arm[C.ROLE_PROP] = "rig"
        C.move_to_collection(arm, C.get_collection(C.RIG_COLLECTION))

    # empties left over from glTF hierarchy are noise
    for o in list(bpy.data.objects):
        if o.type == "EMPTY" and not o.children:
            bpy.data.objects.remove(o)

    return {
        "parts": parts,
        "rigged": arm is not None,
        "bone_count": len(arm.data.bones) if arm else 0,
        "scale_applied": scale,
        "height_m": size.z * scale,
        "cleanup": stats,
    }
