"""Stage: bake the AI high-poly detail + textures onto the clean low-poly UVs.

Per part, bakes (selected-to-active, Cycles):
  basecolor, normal (tangent, OpenGL), roughness, metallic, ao
Then rebuilds a clean PBR material on the low mesh from the baked maps.
Engine-specific channel packing happens at export.
"""

from __future__ import annotations

import os

import bpy
import numpy as np

from . import common as C

MAP_TYPES = ("basecolor", "normal", "roughness", "metallic", "ao")


def _setup_cycles(samples: int, device: str) -> None:
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.samples = samples
    sc.cycles.use_denoising = False
    sc.cycles.device = "GPU" if device.upper() == "GPU" else "CPU"
    if sc.cycles.device == "GPU":
        prefs = bpy.context.preferences.addons["cycles"].preferences
        for backend in ("OPTIX", "CUDA"):
            try:
                prefs.compute_device_type = backend
                prefs.get_devices()
                for d in prefs.devices:
                    d.use = True
                break
            except TypeError:
                continue


def _new_image(name: str, size: int, non_color: bool, fill) -> bpy.types.Image:
    old = bpy.data.images.get(name)
    if old:
        bpy.data.images.remove(old)
    img = bpy.data.images.new(name, size, size, alpha=False, float_buffer=False)
    img.generated_color = fill
    if non_color:
        img.colorspace_settings.name = "Non-Color"
    return img


def _bake_material(low) -> bpy.types.Material:
    mat = bpy.data.materials.new(f"M_{low.get(C.PART_PROP)}_bake")
    mat.use_nodes = True
    low.data.materials.clear()
    low.data.materials.append(mat)
    return mat


def _set_target(mat, img) -> None:
    nodes = mat.node_tree.nodes
    node = nodes.get("forge_target") or nodes.new("ShaderNodeTexImage")
    node.name = "forge_target"
    node.image = img
    for n in nodes:
        n.select = False
    node.select = True
    nodes.active = node


class _ChannelAsEmission:
    """Temporarily route a Principled input (e.g. Metallic) into the material output as emission."""

    def __init__(self, objs, input_name: str):
        self.objs, self.input_name, self.saved = objs, input_name, []

    def __enter__(self):
        for o in self.objs:
            for slot in o.material_slots:
                mat = slot.material
                if not mat or not mat.use_nodes:
                    continue
                nt = mat.node_tree
                out = next((n for n in nt.nodes if n.type == "OUTPUT_MATERIAL" and n.is_active_output), None)
                bsdf = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
                if not out or not bsdf:
                    continue
                prev = out.inputs["Surface"].links[0].from_socket if out.inputs["Surface"].links else None
                emit = nt.nodes.new("ShaderNodeEmission")
                src = bsdf.inputs[self.input_name]
                if src.links:
                    from_sock = src.links[0].from_socket
                    nt.links.new(from_sock, emit.inputs["Color"])
                else:
                    v = float(src.default_value)
                    emit.inputs["Color"].default_value = (v, v, v, 1.0)
                nt.links.new(emit.outputs["Emission"], out.inputs["Surface"])
                self.saved.append((nt, out, prev, emit))
        return self

    def __exit__(self, *exc):
        for nt, out, prev, emit in self.saved:
            nt.nodes.remove(emit)
            if prev is not None:
                nt.links.new(prev, out.inputs["Surface"])


def _bake(map_type: str, extrusion: float, max_ray: float, margin: int) -> None:
    kw = dict(use_selected_to_active=True, cage_extrusion=extrusion, max_ray_distance=max_ray,
              margin=margin, use_clear=True)
    if map_type == "basecolor":
        bpy.ops.object.bake(type="DIFFUSE", pass_filter={"COLOR"}, **kw)
    elif map_type == "normal":
        bpy.ops.object.bake(type="NORMAL", normal_space="TANGENT", **kw)
    elif map_type == "roughness":
        bpy.ops.object.bake(type="ROUGHNESS", **kw)
    elif map_type in ("metallic",):
        bpy.ops.object.bake(type="EMIT", **kw)
    elif map_type == "ao":
        bpy.ops.object.bake(type="AO", **kw)


def _miss_ratio(img, covered_hint: float) -> float:
    """Fraction of pure-black texels in a base colour bake (rays that hit nothing)."""
    px = np.empty(img.size[0] * img.size[1] * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    rgb = px.reshape(-1, 4)[:, :3]
    black = float(np.mean(rgb.max(axis=1) < 1e-3))
    # texels outside UV islands are also black (cleared to 0) - remove that share
    return max(0.0, black - (1.0 - covered_hint))


def _final_material(low, maps: dict) -> None:
    part = low.get(C.PART_PROP)
    mat = bpy.data.materials.new(f"M_{part}")
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")

    def tex(key, non_color):
        n = nt.nodes.new("ShaderNodeTexImage")
        n.image = maps[key]
        if non_color:
            n.image.colorspace_settings.name = "Non-Color"
        return n

    if "basecolor" in maps:
        nt.links.new(tex("basecolor", False).outputs["Color"], bsdf.inputs["Base Color"])
    if "roughness" in maps:
        nt.links.new(tex("roughness", True).outputs["Color"], bsdf.inputs["Roughness"])
    if "metallic" in maps:
        nt.links.new(tex("metallic", True).outputs["Color"], bsdf.inputs["Metallic"])
    if "normal" in maps:
        nm = nt.nodes.new("ShaderNodeNormalMap")
        nt.links.new(tex("normal", True).outputs["Color"], nm.inputs["Color"])
        nt.links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])
    low.data.materials.clear()
    low.data.materials.append(mat)


def run(args: dict) -> dict:
    size = int(args.get("texture_size", 2048))
    out_dir = os.path.abspath(args["texture_dir"])
    os.makedirs(out_dir, exist_ok=True)
    maps_wanted = [m for m in args.get("maps", MAP_TYPES) if m in MAP_TYPES]
    extrusion_ratio = float(args.get("cage_extrusion_ratio", 0.01))
    margin = int(args.get("margin_px", 8))
    _setup_cycles(int(args.get("samples", 16)), args.get("device", "CPU"))

    for coll in (C.HIGH_COLLECTION,):
        c = bpy.data.collections.get(coll)
        if c:
            c.hide_render = False

    report = {}
    for low in C.meshes_with_role("low"):
        high = C.high_for(low)
        part = low.get(C.PART_PROP)
        if high is None:
            report[part] = {"skipped": "no high mesh"}
            continue
        diag = max(low.dimensions.length, 1e-6)
        extrusion = diag * extrusion_ratio
        mat = _bake_material(low)
        baked = {}
        for mtype in maps_wanted:
            non_color = mtype != "basecolor"
            fill = (0.5, 0.5, 1.0, 1.0) if mtype == "normal" else (0, 0, 0, 1)
            img = _new_image(f"T_{part}_{mtype}", size, non_color, fill)
            _set_target(mat, img)
            C.select_only(high, low, active=low)
            if mtype == "metallic":
                with _ChannelAsEmission([high], "Metallic"):
                    _bake(mtype, extrusion, extrusion * 4, margin)
            else:
                _bake(mtype, extrusion, extrusion * 4, margin)
            path = os.path.join(out_dir, f"T_{part}_{mtype}.png")
            img.filepath_raw = path
            img.file_format = "PNG"
            img.save()
            baked[mtype] = img
        entry = {"maps": {k: os.path.join(out_dir, f"T_{part}_{k}.png") for k in baked}}
        if "basecolor" in baked:
            util = float(args.get("uv_utilization", {}).get(part, 0.7))
            entry["bake_miss_ratio"] = round(_miss_ratio(baked["basecolor"], util), 4)
        _final_material(low, baked)
        bpy.data.materials.remove(mat)
        report[part] = entry

    c = bpy.data.collections.get(C.HIGH_COLLECTION)
    if c:
        c.hide_render = True
    return {"parts": report}
