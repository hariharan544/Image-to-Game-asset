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


def build_cage(low, high, max_rel: float = 0.02, min_rel: float = 0.0015, smooth: int = 4):
    """A bake cage fitted to this part: a copy of the low mesh pushed out at each vertex only
    as far as the original surface lies outside it there (plus a margin), smoothed.

    With one fixed extrusion for the whole model, rays in deep, narrow places (eye socket,
    inside an ear, horn base, mouth corner) start beyond a NEIGHBOURING surface and fetch its
    colour: smears. Fitted per vertex, every ray starts just outside the right surface."""
    import numpy as np
    from mathutils.bvhtree import BVHTree
    dg = bpy.context.evaluated_depsgraph_get()
    tree = BVHTree.FromObject(high, dg)
    inv_h = high.matrix_world.inverted()
    mw = low.matrix_world
    me = low.data
    diag = max(low.dimensions.length, 1e-6)
    lo_d, hi_d = diag * min_rel, diag * max_rel
    n = len(me.vertices)
    push = np.full(n, lo_d)
    for i, v in enumerate(me.vertices):
        p = inv_h @ (mw @ v.co)
        nrm = (inv_h.to_3x3() @ (mw.to_3x3() @ v.normal)).normalized()
        hit = tree.ray_cast(p, nrm, hi_d)                 # original surface outside this point?
        if hit[0] is not None:
            push[i] = max(lo_d, hit[3] * 1.25 + lo_d)
        else:
            near = tree.find_nearest(p, hi_d)
            if near[0] is not None:
                push[i] = max(lo_d, min(near[3] * 1.25 + lo_d, hi_d))
    # smooth the push between neighbours so the cage does not fold
    ev = np.empty(len(me.edges) * 2, np.int32)
    me.edges.foreach_get("vertices", ev)
    a, b = ev[0::2], ev[1::2]
    deg = np.maximum(np.bincount(a, minlength=n) + np.bincount(b, minlength=n), 1)
    for _ in range(smooth):
        avg = (np.bincount(a, weights=push[b], minlength=n) + np.bincount(b, weights=push[a], minlength=n)) / deg
        push = np.maximum(push, 0.5 * push + 0.5 * avg)   # never below what the vertex needs
    cage_me = me.copy()
    co = np.empty(n * 3, np.float32)
    me.vertices.foreach_get("co", co)
    nr = np.empty(n * 3, np.float32)
    me.vertices.foreach_get("normal", nr)
    co = co.reshape(-1, 3) + nr.reshape(-1, 3) * (push[:, None] / max(mw.to_scale()[0], 1e-9))
    cage_me.vertices.foreach_set("co", co.astype(np.float32).ravel())
    cage_me.update()
    cage = bpy.data.objects.new(f"{low.name}_cage", cage_me)
    cage.matrix_world = mw.copy()
    bpy.context.scene.collection.objects.link(cage)
    cage.hide_render = True
    cage["forge_cage"] = True
    return cage, float(push.max())


_CAGE: dict = {"name": None}


def _bake(map_type: str, extrusion: float, max_ray: float, margin: int) -> None:
    kw = dict(use_selected_to_active=True, cage_extrusion=extrusion, max_ray_distance=max_ray,
              margin=margin, use_clear=False)       # keep the sentinel where rays miss
    if _CAGE["name"]:
        kw.update(use_cage=True, cage_object=_CAGE["name"], cage_extrusion=0.0)
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


# a colour no bake produces: magenta. Pre-filled, left untouched where rays miss.
SENTINEL = (1.0, 0.0, 1.0, 1.0)
NEUTRAL = {"normal": (0.5, 0.5, 1.0), "metallic": (0.0, 0.0, 0.0), "ao": (1.0, 1.0, 1.0)}


def _uv_coverage(low, size: int) -> np.ndarray:
    """Boolean mask (size x size, row 0 = v 0) of texels inside the low mesh's UV islands."""
    from . import metrics
    uvs, _ = metrics._uv_tris(low)
    res = min(size, 1024)
    if uvs is None or not len(uvs):
        return np.ones((size, size), bool)
    small = metrics._coverage(np.clip(uvs, 0, 1), res) > 0
    k = size // res
    return np.kron(small, np.ones((k, k), bool)) if k > 1 else small


def _fill_colours(rgb: np.ndarray, valid: np.ndarray, miss: np.ndarray, iterations: int,
                  work_res: int = 1024) -> np.ndarray:
    """Colours for the missed texels, grown from the valid ones. Done on a block-averaged copy
    of at most work_res^2 texels (4K maps would otherwise take minutes), then sampled back."""
    h, w = valid.shape
    k = max(1, h // work_res)
    hs, ws = h // k, w // k
    v = valid[:hs * k, :ws * k].reshape(hs, k, ws, k)
    c = rgb[:hs * k, :ws * k].reshape(hs, k, ws, k, 3)
    cnt = v.sum(axis=(1, 3)).astype(np.float32)
    small = (c * v[..., None]).sum(axis=(1, 3)) / np.maximum(cnt, 1)[..., None]
    ok = cnt > 0
    for _ in range(iterations):                  # grow valid colours into the holes
        if ok.all():
            break
        acc = np.zeros_like(small)
        n = np.zeros(ok.shape, np.float32)
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            o = np.roll(ok, (dy, dx), axis=(0, 1))
            acc += np.roll(small, (dy, dx), axis=(0, 1)) * o[..., None]
            n += o
        grow = (~ok) & (n > 0)
        small[grow] = acc[grow] / n[grow][:, None]
        ok = ok | grow
    if not ok.all():                             # very large holes: the part's average colour
        small[~ok] = small[ok].mean(axis=0, dtype=np.float64) if ok.any() else 0.5
    ys, xs = np.nonzero(miss)
    return small[np.minimum(ys // k, hs - 1), np.minimum(xs // k, ws - 1)]


def _resolve_sentinel(img, cov: np.ndarray, mtype: str, iterations: int = 64) -> float:
    """Count bake misses (sentinel texels inside UV islands) and fill them from neighbouring
    texels; texels outside the islands get a neutral value. Returns the miss ratio."""
    w, h = img.size
    px = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    px = px.reshape(h, w, 4)
    sent = (px[..., 0] > 0.99) & (px[..., 1] < 0.01) & (px[..., 2] > 0.99)
    if cov.shape != sent.shape:
        cov = np.ones_like(sent)
    miss = sent & cov
    ratio = float(miss.sum()) / max(int(cov.sum()), 1)
    if miss.any():
        rgb = px[..., :3]
        rgb[miss] = _fill_colours(rgb, ~sent, miss, iterations)
        px[..., :3] = rgb
    outside = sent & ~cov
    if outside.any():
        good = (~sent) & cov
        neutral = NEUTRAL.get(mtype) or (px[..., :3][good].mean(axis=0, dtype=np.float64) if good.any() else (0.5, 0.5, 0.5))
        px[..., :3][outside] = neutral
    px[..., 3] = 1.0
    img.pixels.foreach_set(px.ravel())
    return ratio


def _clean_metallic(img, floor: float) -> dict:
    """AI-generated PBR textures put low 'metallic' noise (~0.1-0.25) on non-metal surfaces
    (measured on the first real asset: the whole fur at ~0.2). Values below `floor` become 0;
    real metal above it is rescaled to the full 0..1 range."""
    px = np.empty(img.size[0] * img.size[1] * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    px = px.reshape(-1, 4)
    m = px[:, 0]
    covered = m > 1e-3
    noise = covered & (m < floor)
    out = np.where(m < floor, 0.0, (m - floor) / max(1.0 - floor, 1e-6)).astype(np.float32)
    px[:, 0] = px[:, 1] = px[:, 2] = out
    img.pixels.foreach_set(px.ravel())
    n = max(int(covered.sum()), 1)
    return {"floor": floor, "zeroed_pct": round(float(100.0 * noise.sum() / n), 2),
            "metal_pct": round(float(100.0 * (covered & (m >= floor)).sum() / n), 2)}


def despeckle_array(px: np.ndarray, radius: int = 3, threshold: float = 0.12) -> int:
    """Remove isolated specks in place: a texel brighter (or darker) than ALL 8 texels at
    `radius` around it by more than `threshold` (colour distance) is replaced by their mean.
    Real edges (a pupil, a fur-patch border) have similar colour on at least one side and stay.
    px: (h, w, >=3) float array. Returns the number of texels fixed."""
    rgb = px[..., :3]
    lum = rgb.mean(axis=2)
    lo = np.full(lum.shape, np.inf, np.float32)          # min over directions of (centre - ring)
    hi = np.full(lum.shape, -np.inf, np.float32)         # max over directions of (centre - ring)
    acc = np.zeros_like(rgb)
    dirs = [(radius, 0), (-radius, 0), (0, radius), (0, -radius),
            (radius, radius), (radius, -radius), (-radius, radius), (-radius, -radius)]
    for dy, dx in dirs:
        ring = np.roll(lum, (dy, dx), axis=(0, 1))
        d = lum - ring
        np.minimum(lo, d, out=lo)
        np.maximum(hi, d, out=hi)
        acc += np.roll(rgb, (dy, dx), axis=(0, 1))
    speck = (lo > threshold) | (hi < -threshold)
    # grow by one texel: a speck's soft rim goes too
    grow = speck.copy()
    for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        grow |= np.roll(speck, (dy, dx), axis=(0, 1))
    n = int(grow.sum())
    if n:
        rgb[grow] = (acc / len(dirs))[grow]
    return n


def _despeckle(img, mtype: str) -> int:
    if mtype not in ("basecolor", "normal", "roughness"):
        return 0
    w, h = img.size
    px = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    px = px.reshape(h, w, 4)
    r = max(2, int(round(3 * w / 4096)) + 1)             # about the same physical size at 2K and 4K
    n = despeckle_array(px, radius=r, threshold=0.12 if mtype != "normal" else 0.18)
    if n:
        img.pixels.foreach_set(px.ravel())
    return n


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


STATUS = {"text": ""}          # what the bake is doing, for the panel


def _sentinel_mask(img) -> np.ndarray:
    w, h = img.size
    px = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    px = px.reshape(h, w, 4)
    return (px[..., 0] > 0.99) & (px[..., 1] < 0.01) & (px[..., 2] > 0.99)


def _refill_misses(img, high, low, mat, mtype, size, non_color, extrusion, margin, cov) -> int:
    """Second pass for texels the fitted cage missed: bake them the plain way (fixed distance)
    and copy only those texels in. The cage can then never leave a hole."""
    miss = _sentinel_mask(img) & (cov if cov.shape == (size, size) else True)
    n = int(miss.sum())
    if not n:
        return 0
    tmp = _new_image(f"{img.name}_refill", size, non_color, SENTINEL)
    _set_target(mat, tmp)
    C.select_only(high, low, active=low)
    cage, _CAGE["name"] = _CAGE["name"], None
    try:
        if mtype == "metallic":
            with _ChannelAsEmission([high], "Metallic"):
                _bake(mtype, extrusion, extrusion * 4, margin)
        else:
            _bake(mtype, extrusion, extrusion * 4, margin)
    finally:
        _CAGE["name"] = cage
    w, h = img.size
    a = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(a)
    a = a.reshape(h, w, 4)
    b = np.empty(w * h * 4, dtype=np.float32)
    tmp.pixels.foreach_get(b)
    b = b.reshape(h, w, 4)
    a[miss] = b[miss]
    img.pixels.foreach_set(a.ravel())
    _set_target(mat, img)
    bpy.data.images.remove(tmp)
    return n


def run(args: dict) -> dict:
    """Plain call (headless pipeline): runs every step at once."""
    gen = run_iter(args)
    try:
        while True:
            next(gen)
    except StopIteration as stop:
        return stop.value


def run_iter(args: dict):
    """Generator: yields after each map so a UI stays responsive (progress, Stop)."""
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
    cleaned: dict = {}
    specks: dict = {}
    lows = C.meshes_with_role("low")
    for li, low in enumerate(lows):
        high = C.high_for(low)
        part = low.get(C.PART_PROP)
        if high is None:
            report[part] = {"skipped": "no high mesh"}
            continue
        diag = max(low.dimensions.length, 1e-6)
        plain = diag * extrusion_ratio                     # the old fixed distance
        extrusion = plain
        cage = None
        if args.get("fitted_cage", False):           # step-by-step panel turns it on
            STATUS["text"] = f"{part}: fitting the bake cage"
            yield 0.05
            cage, reach = build_cage(low, high)
            _CAGE["name"] = cage.name
            extrusion = max(reach, diag * 0.002)          # max ray reach beyond the cage
        mat = _bake_material(low)
        baked = {}
        cov = _uv_coverage(low, size)
        misses = {}
        refilled = {}
        try:
            for mi, mtype in enumerate(maps_wanted):
                STATUS["text"] = f"{part}: baking {mtype} ({mi + 1}/{len(maps_wanted)})"
                yield 0.05
                non_color = mtype != "basecolor"
                img = _new_image(f"T_{part}_{mtype}", size, non_color, SENTINEL)
                _set_target(mat, img)
                C.select_only(high, low, active=low)
                if mtype == "metallic":
                    with _ChannelAsEmission([high], "Metallic"):
                        _bake(mtype, extrusion, extrusion * 4, margin)
                else:
                    _bake(mtype, extrusion, extrusion * 4, margin)
                if cage is not None:
                    refilled[mtype] = _refill_misses(img, high, low, mat, mtype, size, non_color,
                                                     plain, margin, cov)
                misses[mtype] = _resolve_sentinel(img, cov, mtype)
                if args.get("despeckle", True):
                    specks.setdefault(part, {})[mtype] = _despeckle(img, mtype)
                if mtype == "metallic":
                    cleaned[part] = _clean_metallic(img, float(args.get("metallic_floor", 0.35)))
                path = os.path.join(out_dir, f"T_{part}_{mtype}.png")
                img.filepath_raw = path
                img.file_format = "PNG"
                img.save()
                baked[mtype] = img
        finally:
            if cage is not None:
                _CAGE["name"] = None
                bpy.data.objects.remove(cage)
        entry = {"maps": {k: os.path.join(out_dir, f"T_{part}_{k}.png") for k in baked}}
        if part in cleaned:
            entry["metallic_cleanup"] = cleaned[part]
        if specks.get(part):
            entry["specks_removed"] = specks[part]
        if refilled:
            entry["cage_refilled"] = refilled
        # share of texels inside the UV islands where the bake rays found nothing (now filled)
        entry["bake_miss_ratio"] = round(max(misses.values(), default=0.0), 4)
        entry["bake_misses"] = {k: round(v, 4) for k, v in misses.items()}
        _final_material(low, baked)
        bpy.data.materials.remove(mat)
        report[part] = entry

    c = bpy.data.collections.get(C.HIGH_COLLECTION)
    if c:
        c.hide_render = True
    STATUS["text"] = ""
    return {"parts": report}
