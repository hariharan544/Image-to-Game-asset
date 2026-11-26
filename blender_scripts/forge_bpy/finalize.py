"""Stages: LODs, preview renders, and engine export (Unity / Unreal)."""

from __future__ import annotations

import math
import os
import shutil

import bpy
import numpy as np
from mathutils import Vector

from . import common as C

# ----------------------------------------------------------------------------- LODs


def lods(args: dict) -> dict:
    ratios = [float(r) for r in args.get("lod_ratios", [1.0, 0.5, 0.25])]
    coll = C.get_collection(C.LOD_COLLECTION)
    for o in C.objects_with_role("lod"):
        bpy.data.objects.remove(o)
    report = {}
    for low in C.meshes_with_role("low"):
        part = low.get(C.PART_PROP)
        tris = [C.tri_count(low)]
        for i, r in enumerate(ratios[1:], start=1):
            lod = C.duplicate(low, f"{part}_LOD{i}")
            lod[C.ROLE_PROP] = "lod"
            lod["forge_lod"] = i
            C.move_to_collection(lod, coll)
            mod = lod.modifiers.new("forge_lod", "DECIMATE")
            mod.ratio = r
            mod.use_collapse_triangulate = True
            C.select_only(lod)
            bpy.ops.object.modifier_move_to_index(modifier=mod.name, index=0)
            bpy.ops.object.modifier_apply(modifier=mod.name)
            tris.append(C.tri_count(lod))
        report[part] = tris
    return {"parts": report}

# ----------------------------------------------------------------------------- previews


def _look_at(cam, target: Vector) -> None:
    direction = target - cam.location
    cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def _setup_preview_engine(engine: str, res: int) -> None:
    sc = bpy.context.scene
    sc.render.resolution_x = sc.render.resolution_y = res
    sc.render.film_transparent = False
    if engine == "CYCLES":                      # CPU fallback when no GPU/OpenGL is available
        sc.render.engine = "CYCLES"
        sc.cycles.device = "CPU"
        sc.cycles.samples = 8
        sc.cycles.use_denoising = False
        world = sc.world or bpy.data.worlds.new("forge_world")
        sc.world = world
        world.use_nodes = True
        bg = world.node_tree.nodes.get("Background")
        bg.inputs["Color"].default_value = (0.8, 0.8, 0.8, 1.0)
        bg.inputs["Strength"].default_value = 0.4
        if "forge_key" not in bpy.data.objects:
            sun = bpy.data.objects.new("forge_key", bpy.data.lights.new("forge_key", "SUN"))
            sun.data.energy = 3.0
            sun.rotation_euler = (math.radians(50), 0, math.radians(30))
            sc.collection.objects.link(sun)
    else:
        sc.render.engine = "BLENDER_WORKBENCH"
        sc.display.shading.light = "STUDIO"
        sc.display.shading.color_type = "TEXTURE"
        sc.display.shading.show_cavity = True


def _clay(engine: str, on: bool) -> None:
    sc = bpy.context.scene
    if engine == "CYCLES":
        mat = bpy.data.materials.get("forge_clay") or bpy.data.materials.new("forge_clay")
        bpy.context.view_layer.material_override = mat if on else None
    else:
        sc.display.shading.color_type = "SINGLE" if on else "TEXTURE"
        sc.display.shading.show_object_outline = on


def previews(args: dict) -> dict:
    out_dir = args["preview_dir"]
    os.makedirs(out_dir, exist_ok=True)
    res = int(args.get("resolution", 512))
    engine = args.get("engine", "BLENDER_WORKBENCH")
    _setup_preview_engine(engine, res)
    sc = bpy.context.scene
    for name in (C.HIGH_COLLECTION, C.LOD_COLLECTION):
        c = bpy.data.collections.get(name)
        if c:
            c.hide_render = True

    lows = C.meshes_with_role("low")
    lo = Vector((1e9, 1e9, 1e9))
    hi = -lo
    for o in lows:
        for corner in o.bound_box:
            w = o.matrix_world @ Vector(corner)
            lo = Vector(map(min, lo, w))
            hi = Vector(map(max, hi, w))
    center = (lo + hi) / 2
    radius = max((hi - lo).length, 1e-3)

    cam_data = bpy.data.cameras.get("forge_cam") or bpy.data.cameras.new("forge_cam")
    cam = bpy.data.objects.get("forge_cam") or bpy.data.objects.new("forge_cam", cam_data)
    if cam.name not in sc.collection.objects:
        sc.collection.objects.link(cam)
    cam_data.lens = 50
    sc.camera = cam

    def shoot(yaw_deg: float, path: str) -> None:
        a = math.radians(yaw_deg)
        dist = radius * 1.6
        cam.location = center + Vector((math.sin(a) * dist, -math.cos(a) * dist, radius * 0.35))
        _look_at(cam, center)
        sc.render.filepath = path
        bpy.ops.render.render(write_still=True)

    files = []
    views = args.get("views", {"front": 0, "right": 90, "back": 180, "left": 270, "three_quarter": 35})
    for label, yaw in views.items():
        path = os.path.join(out_dir, f"{label}.png")
        shoot(yaw, path)
        files.append(path)
    _clay(engine, True)                      # untextured shot to judge the shape / shading
    path = os.path.join(out_dir, "clay.png")
    shoot(views.get("three_quarter", 35), path)
    _clay(engine, False)
    files.append(path)
    return {"images": files, "engine": engine}


# ----------------------------------------------------------------------------- export


def _load_pixels(path: str):
    img = bpy.data.images.load(path, check_existing=False)
    img.colorspace_settings.name = "Non-Color"
    w, h = img.size
    px = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    bpy.data.images.remove(img)
    return px.reshape(h, w, 4), (w, h)


def _save_pixels(arr, size, path: str) -> None:
    w, h = size
    img = bpy.data.images.new(os.path.basename(path), w, h, alpha=True)
    img.colorspace_settings.name = "Non-Color"
    img.pixels.foreach_set(arr.astype(np.float32).ravel())
    img.filepath_raw = path
    img.file_format = "PNG"
    img.save()
    bpy.data.images.remove(img)


def _channel(maps, key, default, shape):
    if key in maps and os.path.exists(maps[key]):
        px, _ = _load_pixels(maps[key])
        return px[..., 0]
    return np.full(shape, default, dtype=np.float32)


def _pack_textures(part_name: str, maps: dict, engine: str, out_dir: str, asset: str, unity_pipeline: str,
                   ao_into_basecolor: bool = False) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    out = {}
    ref = maps.get("basecolor") or maps.get("normal")
    if not ref:
        return out
    base_px, size = _load_pixels(ref)
    shape = base_px.shape[:2]
    ao = _channel(maps, "ao", 1.0, shape)
    rough = _channel(maps, "roughness", 0.5, shape)
    metal = _channel(maps, "metallic", 0.0, shape)
    stem = f"{asset}_{part_name}"

    def copy_color(src, dst):
        shutil.copyfile(src, dst)

    if engine == "unreal":
        if "basecolor" in maps:
            dst = os.path.join(out_dir, f"T_{stem}_BC.png"); copy_color(maps["basecolor"], dst); out["basecolor"] = dst
        if "normal" in maps:
            n, _ = _load_pixels(maps["normal"])
            n[..., 1] = 1.0 - n[..., 1]                       # OpenGL -> DirectX
            dst = os.path.join(out_dir, f"T_{stem}_N.png"); _save_pixels(n, size, dst); out["normal"] = dst
        orm = np.stack([ao, rough, metal, np.ones(shape, np.float32)], axis=-1)
        dst = os.path.join(out_dir, f"T_{stem}_ORM.png"); _save_pixels(orm, size, dst); out["orm"] = dst
    else:  # unity
        if "basecolor" in maps:
            dst = os.path.join(out_dir, f"{stem}_BaseMap.png")
            if ao_into_basecolor and "ao" in maps:
                # mobile: darken the base colour by AO (sRGB pixels; AO is linear 0-1) - saves a texture
                img = bpy.data.images.load(maps["basecolor"], check_existing=False)
                w, h = img.size
                px = np.empty(w * h * 4, dtype=np.float32)
                img.pixels.foreach_get(px)
                bpy.data.images.remove(img)
                px = px.reshape(h, w, 4)
                px[..., :3] *= ao[..., None]
                bc = bpy.data.images.new(os.path.basename(dst), w, h, alpha=True)
                bc.pixels.foreach_set(px.ravel())
                bc.filepath_raw = dst
                bc.file_format = "PNG"
                bc.save()
                bpy.data.images.remove(bc)
            else:
                copy_color(maps["basecolor"], dst)
            out["basecolor"] = dst
        if "normal" in maps:
            n, _ = _load_pixels(maps["normal"])                # Unity is OpenGL already
            dst = os.path.join(out_dir, f"{stem}_Normal.png"); _save_pixels(n, size, dst); out["normal"] = dst
        smooth = 1.0 - rough
        if unity_pipeline == "hdrp":   # HDRP Mask Map: R metal, G AO, B detail mask, A smoothness
            mask = np.stack([metal, ao, np.zeros(shape, np.float32), smooth], axis=-1)
            dst = os.path.join(out_dir, f"{stem}_MaskMap.png")
        else:                          # URP/Built-in: R metal, A smoothness (+ separate AO)
            mask = np.stack([metal, metal, metal, smooth], axis=-1)
            dst = os.path.join(out_dir, f"{stem}_MetallicSmoothness.png")
            if not ao_into_basecolor:
                aom = np.stack([ao, ao, ao, np.ones(shape, np.float32)], axis=-1)
                ao_dst = os.path.join(out_dir, f"{stem}_Occlusion.png"); _save_pixels(aom, size, ao_dst); out["ao"] = ao_dst
        _save_pixels(mask, size, dst); out["mask"] = dst
    return out


FBX_COMMON = dict(
    use_selection=True, object_types={"MESH", "ARMATURE", "EMPTY"}, use_mesh_modifiers=True,
    mesh_smooth_type="FACE", use_tspace=True, add_leaf_bones=False, bake_anim=False,
    path_mode="STRIP", axis_forward="-Z", axis_up="Y",
)
FBX_ENGINE = {
    "unity": dict(apply_unit_scale=True, apply_scale_options="FBX_SCALE_ALL", bake_space_transform=True,
                  primary_bone_axis="Y", secondary_bone_axis="X"),
    "unreal": dict(apply_unit_scale=True, apply_scale_options="FBX_SCALE_NONE", bake_space_transform=False,
                   primary_bone_axis="Y", secondary_bone_axis="X"),
}


def _export_fbx(objs, path: str, engine: str) -> None:
    C.select_only(*objs)
    bpy.ops.export_scene.fbx(filepath=path, **FBX_COMMON, **FBX_ENGINE[engine])


def export(args: dict) -> dict:
    engine = args["engine"]
    asset = C.safe_name(args["asset_name"])
    out_dir = args["export_dir"]
    tex_maps = args.get("texture_maps", {})          # part -> {map: path}
    detachable = set(args.get("detachable_parts", []))
    unity_pipeline = args.get("unity_pipeline", "urp")
    ao_into_basecolor = bool(args.get("ao_into_basecolor", False))
    os.makedirs(out_dir, exist_ok=True)

    arm = C.find_armature()
    if arm is not None and engine == "unreal":
        arm.name = "Armature"   # UE drops a top node named "Armature" instead of adding a root bone
    skeletal = arm is not None
    prefix = "" if engine == "unity" else ("SK_" if skeletal else "SM_")

    lows = C.meshes_with_role("low")
    lod_objs = C.objects_with_role("lod")
    body = [o for o in lows if o.get(C.PART_PROP) not in detachable]
    files = {"meshes": {}, "textures": {}}

    def with_lods(objs):
        parts = {o.get(C.PART_PROP) for o in objs}
        extra = [l for l in lod_objs if l.get(C.PART_PROP) in parts]
        return objs + extra

    # LOD0 naming for Unity's automatic LODGroup
    for o in lows:
        o.name = f"{o.get(C.PART_PROP)}_LOD0"

    if body:
        objs = with_lods(body) + ([arm] if arm else [])
        path = os.path.join(out_dir, f"{prefix}{asset}.fbx")
        _export_fbx(objs, path, engine)
        files["meshes"]["body"] = path
    for o in lows:
        part = o.get(C.PART_PROP)
        if part in detachable:
            objs = with_lods([o]) + ([arm] if (arm and o.parent == arm) else [])
            path = os.path.join(out_dir, f"{'SM_' if engine == 'unreal' and o.parent != arm else prefix}{asset}_{part}.fbx")
            _export_fbx(objs, path, engine)
            files["meshes"][part] = path
        if part in tex_maps:
            files["textures"][part] = _pack_textures(part, tex_maps[part], engine,
                                                     os.path.join(out_dir, "Textures"), asset, unity_pipeline,
                                                     ao_into_basecolor)
    for o in lows:
        o.name = f"{o.get(C.PART_PROP)}_low"
    return files
