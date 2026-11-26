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


def _merge_body(meshes: list, detachable: list) -> tuple[list, list]:
    """Join every mesh that is not a swappable part into one 'Body' (AI tools often split a
    character into many parts: one material and no seams at joints is what a game needs)."""
    names = [m.name.lower() for m in meshes]
    wl = [w.lower() for w in detachable]

    def keep(m):   # exact name match first, else substring (same rule as the orchestrator)
        n = m.name.lower()
        return any(n == w or (w not in names and w in n) for w in wl)

    kept = [m for m in meshes if keep(m)]          # decide before joining: joined objects vanish
    body = [m for m in meshes if m not in kept]
    if len(body) < 2:
        return meshes, []
    merged = [m.name for m in body]
    C.select_only(*body, active=body[0])
    bpy.ops.object.join()
    joined = bpy.context.view_layer.objects.active
    joined.name = "Body"
    joined.data.name = "Body"
    return [joined] + kept, merged


def _drop_import_helpers() -> None:
    """Bone display shapes / helper meshes the importers create are not asset parts."""
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


def _import_rig_source(path: str, main_meshes: list) -> dict:
    """Bring in the skeleton from a separate rigged file (e.g. Studio's retopologized + rigged
    copy, because Studio cannot rig the dense model). Its armature becomes the asset's skeleton;
    its meshes are kept hidden only as a skin-weight source. Aligned to the dense model by
    bounding box in case the two files differ in scale or placement."""
    before = set(bpy.data.objects)
    _import(path)
    _drop_import_helpers()
    new = [o for o in bpy.data.objects if o not in before]
    arms = [o for o in new if o.type == "ARMATURE"]
    if not arms:
        raise RuntimeError(f"rig model has no skeleton: {os.path.basename(path)}")
    for o in [o for o in bpy.data.objects if o.type == "ARMATURE" and o not in new]:
        bpy.data.objects.remove(o)                 # the rig file's skeleton wins
    rig_meshes = [o for o in new if o.type == "MESH"]
    mlo, mhi = _world_bbox(main_meshes)
    rlo, rhi = _world_bbox(rig_meshes or arms)
    s = (mhi.z - mlo.z) / max(rhi.z - rlo.z, 1e-9)
    mc, rc = (mlo + mhi) / 2, (rlo + rhi) / 2
    moved = abs(s - 1) > 0.02 or (mc - rc).length > 0.02 * (mhi.z - mlo.z)
    if moved:
        for r in [o for o in new if o.parent is None]:
            r.location = (r.location - rc) * s + mc
            r.scale = r.scale * s
        bpy.context.view_layer.update()
    coll = C.get_collection("FORGE_WEIGHTS", hide_render=True)
    for m in rig_meshes:
        m[C.ROLE_PROP] = "weights"
        C.move_to_collection(m, coll)
        m.hide_set(True)
    return {"file": os.path.basename(path), "bones": len(arms[0].data.bones),
            "aligned_scale": round(s, 4) if moved else 1.0, "weight_meshes": len(rig_meshes)}


def run(args: dict) -> dict:
    src = args["source"]
    target_height = args.get("target_height_m")       # None = keep AI scale
    merge_dist_ratio = float(args.get("merge_distance_ratio", 1e-5))

    _clear_scene()
    _import(src)
    C.ensure_object_mode()
    _drop_import_helpers()
    meshes = [o for o in bpy.data.objects if o.type == "MESH" and o.get(C.ROLE_PROP) != "weights"]
    if not meshes:
        raise RuntimeError("Imported file contains no meshes")
    rig_report = _import_rig_source(args["rig_source"], meshes) if args.get("rig_source") else None
    arm = C.find_armature()

    # --- normalise scale and pivot: bottom-centre at the origin -------------
    roots = [o for o in bpy.data.objects if o.parent is None]
    lo, hi = _world_bbox(meshes)
    size = hi - lo
    scale = 1.0
    unit_fix = None
    if target_height and size.z > 1e-9:
        scale = float(target_height) / size.z
    elif size.z > 30.0:
        # no target height and taller than 30 m: almost certainly exported in centimetres (FBX)
        scale = unit_fix = 0.01
    offset = Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z))
    for r in roots:
        r.location = (r.location - offset) * scale
        r.scale = r.scale * scale
    bpy.context.view_layer.update()
    C.select_only(*bpy.data.objects)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

    merged_from = []
    if args.get("merge_body_parts", True):
        meshes, merged_from = _merge_body(meshes, args.get("detachable_parts", []))

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
        "unit_fix": unit_fix,
        "merged_into_body": merged_from,
        "rig_source": rig_report,
        "height_m": size.z * scale,
        "cleanup": stats,
    }
