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


# ----------------------------------------------------------------------------- the bake cage
#
# A bake ray starts on the cage and runs towards the new (low) surface; Cycles takes the FIRST
# surface it meets, from either side. So every ray must start OUTSIDE the original surface its
# texel stands for, and must not start beyond (or inside) a neighbouring surface. The cage is
# fitted per face, checked where Blender really starts the rays, and every texel's ray is
# checked again before the maps are trusted (_validate_hits).

CAGE_FLOOR_REL = 0.0015       # the cage's margin over the original: at most 0.15% of the part
CAGE_MAX_REL = 0.02           # how far above the new surface the fit looks for the original
VERIFY_ROUNDS = 3             # bounded repair of the cage where a check still starts inside
_FIT: dict = {}               # fit cache: key (coordinates of the low and of the surface) -> fit
_SURF: dict = {}              # the last surface built (its BVH serves the fit and the ray check)
_RASTER: dict = {}            # the last texel map of a low (both passes use the same one)
# skewed directions for inside/outside votes (axis-aligned rays graze voxel-remesh faces)
_DIRS = ((0.267, 0.535, 0.802), (-0.816, 0.408, -0.408), (0.371, -0.928, 0.0))


def clear_fit_cache() -> None:
    """Forget fits, surfaces and texel maps (call when the meshes may have changed, and after
    a bake to free the memory of the originals' trees)."""
    _FIT.clear()
    _SURF.clear()
    _RASTER.clear()


def _arr(coll, attr: str, n: int, dtype) -> np.ndarray:
    out = np.empty(n, dtype)
    if n:
        coll.foreach_get(attr, out)
    return out


def _components(n: int, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    from .appendages import _components as comp
    return comp(n, a, b)


class _Surface:
    """What the rays meet, as a BVH tree in the high object's local space, with per-face flags:
    two_sided - faces of open pieces (a boundary edge somewhere): no inside/outside to trust;
    partly_deep - faces with a corner buried in the welded solid (only the colour source)."""

    def __init__(self, tree, two_sided: np.ndarray, verts=None, partly_deep=None):
        self.tree, self.two_sided, self.verts, self.partly_deep = tree, two_sided, verts, partly_deep


def _orientation(me) -> tuple:
    """(two_sided per face, needs_recalc): faces of pieces with an open boundary are two-sided;
    a closed piece needs its normals recalculated when its winding is inconsistent or it is
    inside out (negative volume)."""
    nf, nv, ne, nl = len(me.polygons), len(me.vertices), len(me.edges), len(me.loops)
    if not nf:
        return np.zeros(0, bool), False
    lv = _arr(me.loops, "vertex_index", nl, np.int32)
    le = _arr(me.loops, "edge_index", nl, np.int32)
    ps = _arr(me.polygons, "loop_start", nf, np.int32)
    ev = _arr(me.edges, "vertices", ne * 2, np.int32).reshape(-1, 2)
    cnt = np.bincount(le, minlength=ne)
    lab = _components(nv, ev[:, 0], ev[:, 1])
    face_lab = lab[lv[ps]]
    open_lab = np.zeros(nv, bool)
    open_lab[lab[ev[cnt == 1, 0]]] = True
    two = open_lab[face_lab]
    if two.all():
        return two, False
    # consistent winding: the two corners on a shared edge start at its two different ends
    order = np.argsort(le, kind="stable")
    start = np.concatenate([[0], np.cumsum(cnt)[:-1]])
    m2 = np.nonzero(cnt == 2)[0]
    l1, l2 = order[start[m2]], order[start[m2] + 1]
    if ((lv[l1] == lv[l2]) & ~open_lab[lab[ev[m2, 0]]]).any():
        return two, True
    # outward: every closed piece encloses a positive volume
    me.calc_loop_triangles()
    nt = len(me.loop_triangles)
    tv = _arr(me.loop_triangles, "vertices", nt * 3, np.int32).reshape(-1, 3)
    tp = _arr(me.loop_triangles, "polygon_index", nt, np.int32)
    co = _arr(me.vertices, "co", nv * 3, np.float32).reshape(-1, 3).astype(np.float64)
    a, b, c = co[tv[:, 0]], co[tv[:, 1]], co[tv[:, 2]]
    vol = np.einsum("ij,ij->i", a, np.cross(b, c))
    per = np.bincount(face_lab[tp], weights=vol, minlength=nv)
    closed = np.unique(face_lab[~two])
    return two, bool((per[closed] < 0).any())


def _recalc_normals(me) -> None:
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()
    me.update()


def _tree(obj):
    from mathutils.bvhtree import BVHTree
    return BVHTree.FromObject(obj, bpy.context.evaluated_depsgraph_get())


def _tree_of_mesh(me):
    """BVH of a mesh datablock that is not on an object (a temporary object: much faster than
    BVHTree.FromPolygons on millions of faces). Local coordinates, like FromObject."""
    tmp = bpy.data.objects.new("FORGE_tmp_bvh", me)
    bpy.context.scene.collection.objects.link(tmp)
    try:
        return _tree(tmp)
    finally:
        bpy.data.objects.remove(tmp)


def _surface_of(mesh_or_obj) -> _Surface:
    """A consistently oriented surface: the mesh itself when every closed piece already points
    outward, else a temporary copy with recalculated normals (the original is not touched)."""
    if isinstance(mesh_or_obj, bpy.types.Object):
        obj = mesh_or_obj
        if len(obj.modifiers):
            ev = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
            me, own = bpy.data.meshes.new_from_object(ev), True
        else:
            me, own = obj.data, False
    else:
        obj, me, own = None, mesh_or_obj, False
    two, recalc = _orientation(me)
    if recalc and not own:
        me, own = me.copy(), True
    if recalc:
        _recalc_normals(me)
    try:
        tree = _tree(obj) if (obj is not None and not own) else _tree_of_mesh(me)
        return _Surface(tree, two)
    finally:
        if own:
            bpy.data.meshes.remove(me)


def _coords(me) -> np.ndarray:
    return _arr(me.vertices, "co", len(me.vertices) * 3, np.float32).reshape(-1, 3)


def _surface_cached(target, co=None) -> _Surface:
    """_surface_of, remembered for the last mesh (by its coordinates): the fit and the ray check
    of a pass meet the same surface, and a multi-million-face tree takes a while to build."""
    evaluated = isinstance(target, bpy.types.Object) and len(target.modifiers) > 0
    me = target.data if isinstance(target, bpy.types.Object) else target
    co = _coords(me) if co is None else co
    key = _hash(co, np.array([len(me.polygons), len(me.loops), evaluated]))
    surf = _SURF.get(key)
    if surf is None:
        _SURF.clear()
        surf = _SURF[key] = _surface_of(target)
    return surf


def _scale(mw) -> float:
    s = mw.to_scale()
    return max(float(abs(s[0]) + abs(s[1]) + abs(s[2])) / 3.0, 1e-12)


def _low_arrays(low):
    me = low.data
    me.calc_loop_triangles()
    nt, n = len(me.loop_triangles), len(me.vertices)
    tv = _arr(me.loop_triangles, "vertices", nt * 3, np.int32).reshape(-1, 3)
    tl = _arr(me.loop_triangles, "loops", nt * 3, np.int32).reshape(-1, 3)
    co = _arr(me.vertices, "co", n * 3, np.float32).reshape(-1, 3).astype(np.float64)
    vn = _arr(me.vertices, "normal", n * 3, np.float32).reshape(-1, 3).astype(np.float64)
    uv = None
    if me.uv_layers.active is not None:
        uv = _arr(me.uv_layers.active.data, "uv", len(me.loops) * 2, np.float32).reshape(-1, 2).astype(np.float64)
    return tv, tl, co, vn, uv


def _to_high(low, high_mw):
    """low-local -> high-local: (3x3, offset, high scale, low scale)."""
    m = np.array(high_mw.inverted() @ low.matrix_world)
    return m[:3, :3], m[:3, 3], _scale(high_mw), _scale(low.matrix_world)


def _bary_grid(m: int) -> np.ndarray:
    return np.array([(i / m, j / m, (m - i - j) / m) for i in range(m + 1) for j in range(m + 1 - i)])


def _samples(tv, tl, co, uv, size: int):
    """Sample points over every low triangle: a barycentric grid spaced about a quarter of the
    longest edge, or 4 texels at the bake size when that is finer (at least 15 points).
    Returns (face index per sample, barycentrics per sample)."""
    e3 = np.stack([np.linalg.norm(co[tv[:, i]] - co[tv[:, (i + 1) % 3]], axis=1) for i in range(3)], 1).max(1)
    m = np.full(len(tv), 4, np.int64)
    if uv is not None and len(tv):
        euv = np.stack([np.linalg.norm(uv[tl[:, i]] - uv[tl[:, (i + 1) % 3]], axis=1) for i in range(3)], 1).max(1)
        m = np.clip(np.ceil(euv * size / 4.0), 4, 32).astype(np.int64)
    m[e3 <= 0] = 1
    fidx, bary = [], []
    for k in np.unique(m):
        faces = np.nonzero(m == k)[0]
        g = _bary_grid(int(k))
        fidx.append(np.repeat(faces, len(g)))
        bary.append(np.tile(g, (len(faces), 1)))
    if not fidx:
        return np.zeros(0, np.int64), np.zeros((0, 3))
    return np.concatenate(fidx), np.concatenate(bary)


def _lerp(vals, tv, fidx, bary):
    return np.einsum("sk,skd->sd", bary, vals[tv[fidx]])


def fit_cage(low, surf: _Surface, high_mw, size: int = 1024, max_rel: float = CAGE_MAX_REL,
             min_rel: float = CAGE_FLOOR_REL, smooth: int = 4) -> dict:
    """Push per low vertex (along its normal) of a cage that ENCLOSES the original over every low
    face, without reaching into a neighbouring surface.

    - Measured at sample points across each face, not only at the vertices: between vertices a
      thin or curved original (ear rim, horn tip) bulges past a cage made from vertex pushes.
    - Only the surface a point stands for counts: going out along the normal, the first surface
      must be met from the INSIDE (an exit). A surface met from outside is another wall: it never
      pushes the cage, it limits it (room). Faces of open pieces count both ways.
    - The cage's margin is at most half the room to that other wall; enclosure keeps priority.
    - Then the ACTUAL cage is checked where Blender starts the rays (the interpolated cage point,
      running towards the low point) and repaired in at most VERIFY_ROUNDS bounded rounds.
    Returns {"push" (low-local, per vertex), "max_ray" (world), "unenclosed" (low faces whose
    cage still starts inside), "unenclosed_samples", "samples", ...}."""
    from mathutils import Vector
    tree, two = surf.tree, surf.two_sided
    rc, near = tree.ray_cast, tree.find_nearest
    R, T, s_h, s_l = _to_high(low, high_mw)
    tv, tl, co, vn, uv = _low_arrays(low)
    n = len(co)
    co_h = co @ R.T + T
    vn_h = vn @ R.T
    vn_h /= np.maximum(np.linalg.norm(vn_h, axis=1, keepdims=True), 1e-12)
    diag = max(low.dimensions.length, 1e-6) / s_h            # in high-local units
    lo, hi = diag * min_rel, diag * max_rel
    eps = diag * 1e-6
    fidx, bary = _samples(tv, tl, co, uv, size)
    S = len(fidx)
    P = _lerp(co_h, tv, fidx, bary)
    N = _lerp(vn_h, tv, fidx, bary)
    N /= np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-12)
    need = np.zeros(S)
    room = np.full(S, np.inf)
    gin = np.zeros(S)
    for s, (p, d) in enumerate(zip(P.tolist(), N.tolist())):
        dv = Vector(d)
        pv = Vector(p)
        h = rc(pv - dv * eps, dv)
        exit_ = h[0] is not None and not two[h[2]] and h[1].dot(dv) > 0
        if h[0] is not None and h[3] > hi and exit_:
            continue                           # deeper than the fit reaches: left to the check
        if h[0] is not None and h[3] <= hi and (exit_ or two[h[2]]):
            t, q = h[3], h[0]                  # under its own surface by t
            for _ in range(4):
                h2 = rc(q + dv * eps, dv, 2 * hi)
                if h2[0] is None:
                    break
                if two[h2[2]] or h2[1].dot(dv) < 0:
                    room[s] = h2[3]            # room: from that surface to the next wall
                    break
                if t + h2[3] > hi:
                    break
                t, q = t + h2[3], h2[0]        # out of an overlapping piece too
            need[s] = t
        else:
            if h[0] is not None:
                room[s] = h[3]                 # outside; a neighbouring wall above (or nothing)
            hb = rc(pv + dv * eps, -dv, hi)
            if hb[0] is not None:
                gin[s] = hb[3]                 # the own surface lies this far below
    need_f = np.zeros(len(tv))
    np.maximum.at(need_f, fidx, need)
    room_f = np.full(len(tv), np.inf)
    np.minimum.at(room_f, fidx, room)
    need_v = np.zeros(n)
    np.maximum.at(need_v, tv.ravel(), np.repeat(need_f, 3))
    room_v = np.full(n, np.inf)
    np.minimum.at(room_v, tv.ravel(), np.repeat(room_f, 3))
    cap = np.maximum(need_v, np.minimum(need_v + 0.5 * room_v, 1.25 * hi + lo))
    push = np.clip(1.15 * need_v + np.minimum(lo, 0.5 * room_v), need_v, cap)
    base = push.copy()
    ev = _arr(low.data.edges, "vertices", len(low.data.edges) * 2, np.int32)
    ea, eb = ev[0::2], ev[1::2]
    deg = np.maximum(np.bincount(ea, minlength=n) + np.bincount(eb, minlength=n), 1)
    for _ in range(smooth):          # even out (the cage must not fold): within [own need, room cap]
        avg = (np.bincount(ea, weights=push[eb], minlength=n) + np.bincount(eb, weights=push[ea], minlength=n)) / deg
        push = np.clip(0.5 * push + 0.5 * avg, base, cap)

    # check the ACTUAL cage: the ray starts at the interpolated cage point and runs to the low
    # point; its first hit must be met from outside (where vertex normals spread apart, on
    # coarse curved parts, the cage between vertices sits lower than the pushes suggest)
    L = P
    bad = np.zeros(S, np.int8)                  # 1 = still under its own surface, 2 = in a neighbour
    todo = np.arange(S)
    raised = lowered = 0
    for rnd in range(VERIFY_ROUNDS + 1):
        Cg = _lerp(co_h + vn_h * push[:, None], tv, fidx[todo], bary[todo])
        V = L[todo] - Cg
        dist = np.linalg.norm(V, axis=1)
        D = V / np.maximum(dist, 1e-12)[:, None]
        up = np.zeros(len(todo))
        down = np.zeros(len(todo))
        for k, (c, d, ds) in enumerate(zip(Cg.tolist(), D.tolist(), dist.tolist())):
            s = todo[k]
            bad[s] = 0
            if ds < eps:
                continue
            h = rc(c, d)                         # unbounded: inside a big part, the way out is far
            if h[0] is None or two[h[2]] or (h[1][0] * d[0] + h[1][1] * d[1] + h[1][2] * d[2]) <= 0:
                continue                         # met from outside (or nothing): fine
            if h[3] >= ds - eps:                 # leaves past the low point: still inside its own
                bad[s] = 1
                nh = near(c, 2 * hi)
                up[k] = max(1.5 * (nh[3] if nh[0] is not None else hi), 0.25 * lo)
            else:                                # leaves before the low point: inside a neighbour
                bad[s] = 2
                down[k] = 1.5 * h[3]
        if rnd == VERIFY_ROUNDS or not (up.any() or down.any()):
            break
        up_f = np.zeros(len(tv))
        np.maximum.at(up_f, fidx[todo], up)
        down_f = np.zeros(len(tv))
        np.maximum.at(down_f, fidx[todo], down)
        up_v = np.zeros(n)
        np.maximum.at(up_v, tv.ravel(), np.repeat(up_f, 3))
        down_v = np.zeros(n)
        np.maximum.at(down_v, tv.ravel(), np.repeat(down_f, 3))
        new = np.where(up_v > 0, push + up_v, push - down_v)
        new = np.clip(new, need_v, cap)          # never past the room cap, never under the own need
        changed = np.abs(new - push) > eps
        raised += int((changed & (new > push)).sum())
        lowered += int((changed & (new < push)).sum())
        if not changed.any():
            break
        push = new
        todo = np.nonzero(changed[tv[fidx]].any(axis=1))[0]
    Cg = _lerp(co_h + vn_h * push[:, None], tv, fidx, bary)
    seg = np.linalg.norm(Cg - L, axis=1)
    reach = 1.25 * float(np.max(seg + gin)) if S else 2 * lo
    reach = max(reach, 2 * lo)
    failing = bad > 0
    return {"push": push * s_h / s_l, "max_ray": reach * s_h,
            "need": need_v * s_h / s_l, "cap": cap * s_h / s_l, "failing_faces": np.unique(fidx[failing]),
            "unenclosed": len(np.unique(fidx[failing])),
            "unenclosed_samples": int(failing.sum()), "in_neighbour_samples": int((bad == 2).sum()),
            "samples": int(S), "raised": raised, "lowered": lowered,
            "push_mm": [round(float(x) * s_h * 1000, 2) for x in (np.percentile(push, 50), np.percentile(push, 99), push.max())] if n else [0, 0, 0]}


def _hash(*arrays) -> str:
    import hashlib
    h = hashlib.blake2b(digest_size=16)
    for a in arrays:
        h.update(np.ascontiguousarray(a).tobytes())
    return h.hexdigest()


def _fit_for(low, high, solid, size: int, max_rel: float, min_rel: float, smooth: int) -> dict:
    """The fit for this low against the visible shape: the welded solid when the part has one,
    else the high itself. Cached by the coordinates of both (a moved vertex is a new fit), so
    the colour pass reuses the detail pass's cage."""
    me = low.data
    co = _coords(me)
    target = solid if solid is not None else high.data
    tco = _coords(target)
    key = _hash(co, np.array(low.matrix_world), np.array(high.matrix_world), tco,
                np.array([len(me.polygons), len(target.polygons), size, max_rel, min_rel, smooth], np.float64))
    fit = _FIT.get(key)
    if fit is None:
        surf = _surface_cached(high if (solid is None or solid == high.data) else solid, tco)
        fit = fit_cage(low, surf, high.matrix_world, size, max_rel, min_rel, smooth)
        if len(_FIT) > 16:
            _FIT.clear()
        _FIT[key] = fit
    return fit


def build_cage(low, high, max_rel: float = CAGE_MAX_REL, min_rel: float = CAGE_FLOOR_REL, smooth: int = 4,
               size: int = 1024, solid=None):
    """A bake cage fitted to this part (see fit_cage): a copy of the low mesh, each vertex pushed
    out along its normal. Returns (cage object, max ray distance for the bake, world units)."""
    fit = _fit_for(low, high, solid, size, max_rel, min_rel, smooth)
    me = low.data
    n = len(me.vertices)
    cage_me = me.copy()
    co = _arr(me.vertices, "co", n * 3, np.float32).reshape(-1, 3)
    nr = _arr(me.vertices, "normal", n * 3, np.float32).reshape(-1, 3)
    co = co + nr * fit["push"][:, None]
    cage_me.vertices.foreach_set("co", co.astype(np.float32).ravel())
    cage_me.update()
    cage = bpy.data.objects.new(f"{low.name}_cage", cage_me)
    cage.matrix_world = low.matrix_world.copy()
    bpy.context.scene.collection.objects.link(cage)
    cage.hide_render = True
    cage["forge_cage"] = True
    for k in ("unenclosed", "unenclosed_samples", "samples", "raised", "lowered"):
        cage[f"forge_{k}"] = int(fit[k])
    cage["forge_max_ray"] = float(fit["max_ray"])
    return cage, float(fit["max_ray"])


# ----------------------------------------------------------------------------- checking the rays

def _bake_res(size: int) -> int:
    res = size
    while res > 1024 and res % 2 == 0:
        res //= 2
    return res


def _raster(low, res: int):
    """Which low triangle each texel centre of a res x res bake falls in (row 0 = v 0), where in
    it (barycentrics), and its UV island: (tri (-1 = none), bary, island (-1 = none))."""
    _tv, tl, _co, _vn, uv = _low_arrays(low)
    key = _hash(tl, uv if uv is not None else np.zeros(0), np.array([res]))
    if key in _RASTER:
        return _RASTER[key]
    out = _raster_build(low, res, tl, uv)
    _RASTER.clear()
    _RASTER[key] = out
    return out


def _raster_build(low, res: int, tl, uv):
    tri = np.full((res, res), -1, np.int32)
    bary = np.zeros((res, res, 3), np.float32)
    if uv is None or not len(tl):
        return tri, bary, np.full((res, res), -1, np.int32)
    me = low.data
    lv = _arr(me.loops, "vertex_index", len(me.loops), np.int32)
    key = np.stack([lv, np.round(uv[:, 0] * 2 ** 20), np.round(uv[:, 1] * 2 ** 20)], 1).astype(np.int64)
    _u, inv = np.unique(key, axis=0, return_inverse=True)
    inv = inv.ravel()
    a, b, c = inv[tl[:, 0]], inv[tl[:, 1]], inv[tl[:, 2]]
    lab = _components(int(inv.max()) + 1, np.concatenate([a, b]), np.concatenate([b, c]))
    tri_island = lab[a]
    U = uv[tl] * res
    for t in range(len(tl)):
        (ax, ay), (bx, by), (cx, cy) = U[t]
        x0, x1 = max(int(np.floor(min(ax, bx, cx))), 0), min(int(np.ceil(max(ax, bx, cx))), res - 1)
        y0, y1 = max(int(np.floor(min(ay, by, cy))), 0), min(int(np.ceil(max(ay, by, cy))), res - 1)
        if x1 < x0 or y1 < y0:
            continue
        d = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(d) < 1e-12:
            continue
        xs, ys = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
        w0 = ((by - cy) * (xs - cx) + (cx - bx) * (ys - cy)) / d
        w1 = ((cy - ay) * (xs - cx) + (ax - cx) * (ys - cy)) / d
        w2 = 1.0 - w0 - w1
        sub = tri[y0:y1 + 1, x0:x1 + 1]
        m = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6) & (sub < 0)
        if not m.any():
            continue
        sub[m] = t
        bsub = bary[y0:y1 + 1, x0:x1 + 1]
        bsub[m] = np.stack([w0[m], w1[m], w2[m]], 1)
    island = np.where(tri >= 0, tri_island[np.maximum(tri, 0)], -1).astype(np.int32)
    return tri, bary, island


def _inside(tree, p) -> bool:
    """p inside a closed, outward surface: the first hit is a back face for most directions."""
    votes = 0
    for d in _DIRS:
        h = tree.ray_cast(p, d)
        if h[0] is not None and h[1].dot(d) > 0:
            votes += 1
    return votes >= 2


def _deep_mask(solid: _Surface, pts: np.ndarray, depth: float, cell: float) -> np.ndarray:
    """True where a point lies inside the welded solid by more than `depth`. Points next to the
    solid's surface (a coarse grid around its vertices) are skipped; the rest are tested exactly."""
    out = np.zeros(len(pts), bool)
    if not len(pts) or solid.verts is None or not len(solid.verts):
        return out
    S = solid.verts
    g = max(cell, 1e-9)
    lo = S.min(axis=0) - 3 * g
    dims = np.ceil((S.max(axis=0) + 3 * g - lo) / g).astype(np.int64) + 1
    while int(np.prod(dims)) > 24_000_000:            # memory: a coarser grid only trims less
        g *= 1.26
        dims = np.ceil((S.max(axis=0) + 3 * g - lo) / g).astype(np.int64) + 1
    occ = np.zeros(tuple(dims), bool)
    ij = np.clip(((S - lo) / g).astype(np.int64), 0, dims - 1)
    occ[ij[:, 0], ij[:, 1], ij[:, 2]] = True
    for ax in range(3):                         # grow by one cell: "next to the surface"
        grown = occ.copy()
        sl_a = [slice(None)] * 3
        sl_b = [slice(None)] * 3
        sl_a[ax], sl_b[ax] = slice(1, None), slice(None, -1)
        grown[tuple(sl_a)] |= occ[tuple(sl_b)]
        grown[tuple(sl_b)] |= occ[tuple(sl_a)]
        occ = grown
    pij = ((pts - lo) / g).astype(np.int64)
    inb = ((pij >= 0) & (pij < dims)).all(axis=1)
    nearby = np.zeros(len(pts), bool)
    q = pij[inb]
    nearby[inb] = occ[q[:, 0], q[:, 1], q[:, 2]]
    tree = solid.tree
    for i in np.nonzero(~nearby)[0].tolist():
        p = pts[i].tolist()
        if tree.find_nearest(p, depth)[0] is None and _inside(tree, p):
            out[i] = True
    return out


def _voxel_size(me) -> float:
    """Edge length of a voxel remesh (its median edge)."""
    ne = len(me.edges)
    if not ne:
        return 0.0
    ev = _arr(me.edges, "vertices", ne * 2, np.int32).reshape(-1, 2)
    co = _arr(me.vertices, "co", len(me.vertices) * 3, np.float32).reshape(-1, 3)
    return float(np.median(np.linalg.norm(co[ev[:, 0]] - co[ev[:, 1]], axis=1)))


def _visible_colour_source(high, solid: _Surface, depth: float, cell: float):
    """A temporary copy of the colour original without its pieces buried in the welded solid
    (deeper than `depth`): buried AI texture can then never be fetched, whatever a ray does.
    Returns (object, its surface, faces removed). The caller deletes the object and its mesh."""
    import bmesh
    if len(high.modifiers):
        me = bpy.data.meshes.new_from_object(high.evaluated_get(bpy.context.evaluated_depsgraph_get()))
    else:
        me = high.data.copy()
    me.name = f"FORGE_colour_{high.name}"
    two, recalc = _orientation(me)
    if recalc:
        _recalc_normals(me)
    nv, nf, nl = len(me.vertices), len(me.polygons), len(me.loops)
    co = _arr(me.vertices, "co", nv * 3, np.float32).reshape(-1, 3).astype(np.float64)
    deep_v = _deep_mask(solid, co, depth, cell)
    lv = _arr(me.loops, "vertex_index", nl, np.int32)
    ps = _arr(me.polygons, "loop_start", nf, np.int32)
    dl = deep_v[lv].astype(np.int8)
    all_deep = np.minimum.reduceat(dl, ps).astype(bool) if nf else np.zeros(0, bool)
    any_deep = np.maximum.reduceat(dl, ps).astype(bool) if nf else np.zeros(0, bool)
    removed = int(all_deep.sum())
    if removed:
        for name, vals in (("forge_two_sided", two), ("forge_partly_deep", any_deep)):
            at = me.attributes.new(name, "INT", "FACE")
            at.data.foreach_set("value", vals.astype(np.int32))
        bm = bmesh.new()
        bm.from_mesh(me)
        bm.faces.ensure_lookup_table()
        bmesh.ops.delete(bm, geom=[bm.faces[i] for i in np.nonzero(all_deep)[0].tolist()], context="FACES")
        bm.to_mesh(me)
        bm.free()
        me.update()
        nf = len(me.polygons)
        two = _arr(me.attributes["forge_two_sided"].data, "value", nf, np.int32).astype(bool)
        any_deep = _arr(me.attributes["forge_partly_deep"].data, "value", nf, np.int32).astype(bool)
        for name in ("forge_two_sided", "forge_partly_deep"):
            me.attributes.remove(me.attributes[name])
    obj = bpy.data.objects.new(me.name, me)
    obj.matrix_world = high.matrix_world.copy()
    bpy.context.scene.collection.objects.link(obj)
    obj["forge_colour_source"] = True
    return obj, _Surface(_tree(obj), two, None, any_deep), removed


def _validate_hits(low, high_mw, cage, surf: _Surface, max_ray: float, raster, solid=None,
                   depth: float = 0.0) -> dict:
    """Re-cast every covered texel's ray as Cycles does (from the interpolated cage point towards
    the low point, first hit within max_ray, both sides of a face) and mark the ones that cannot
    be trusted: no hit, a hit on the BACK of a face (the ray started inside the original), or
    (colour from an original with buried pieces) a hit deeper than `depth` inside the welded
    solid. Cycles cannot skip back faces itself (Marmoset / Substance 'ignore backfaces')."""
    tri, bary, _island = raster
    ys, xs = np.nonzero(tri >= 0)
    invalid = np.zeros(tri.shape, bool)
    kinds = {"miss": 0, "back_face": 0, "buried": 0}
    if not len(ys):
        return {"invalid": invalid, "covered": tri >= 0, "kinds": kinds, "share": 0.0}
    R, T, s_h, _s_l = _to_high(low, high_mw)
    tv, _tl, co, _vn, _uv = _low_arrays(low)
    cme = cage.data
    cco = _arr(cme.vertices, "co", len(cme.vertices) * 3, np.float32).reshape(-1, 3).astype(np.float64)
    co_h, cg_h = co @ R.T + T, cco @ R.T + T
    f = tri[ys, xs]
    b = bary[ys, xs].astype(np.float64)
    Lp = _lerp(co_h, tv, f, b)
    Cp = _lerp(cg_h, tv, f, b)
    V = Lp - Cp
    dist = np.linalg.norm(V, axis=1)
    D = V / np.maximum(dist, 1e-12)[:, None]
    reach = max_ray / s_h
    rc, two, pdeep = surf.tree.ray_cast, surf.two_sided, surf.partly_deep
    bad = np.zeros(len(ys), np.int8)
    for k, (c, d) in enumerate(zip(Cp.tolist(), D.tolist())):
        h = rc(c, d, reach)
        if h[0] is None:
            bad[k] = 1
        elif not two[h[2]] and (h[1][0] * d[0] + h[1][1] * d[1] + h[1][2] * d[2]) > 0:
            bad[k] = 2
        elif solid is not None and pdeep is not None and pdeep[h[2]]:
            p = h[0]
            if solid.tree.find_nearest(p, depth)[0] is None and _inside(solid.tree, p):
                bad[k] = 3
    invalid[ys, xs] = bad > 0
    kinds = {"miss": int((bad == 1).sum()), "back_face": int((bad == 2).sum()), "buried": int((bad == 3).sum())}
    return {"invalid": invalid, "covered": tri >= 0, "kinds": kinds,
            "share": float((bad > 0).sum()) / len(ys)}


def _upsample(a: np.ndarray, k: int) -> np.ndarray:
    return np.kron(a, np.ones((k, k), a.dtype)) if k > 1 else a


def _inpaint(rgb: np.ndarray, holes: np.ndarray, sources: np.ndarray, island: np.ndarray,
             max_rounds: int = 1024) -> np.ndarray:
    """Fill hole texels ring by ring from their 4 neighbours that are valid AND in the same UV
    island (never across a seam). Works in place on rgb (h, w, 3). Returns the flat indices of
    holes that could not be reached (their whole island is invalid)."""
    h, w = holes.shape
    flat = rgb.reshape(-1, 3)
    ok = sources.ravel().copy()
    isl = island.ravel()
    left = np.flatnonzero(holes)
    for _ in range(max_rounds):
        if not len(left):
            break
        y, x = np.divmod(left, w)
        acc = np.zeros((len(left), 3), np.float64)
        cnt = np.zeros(len(left), np.int32)
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            yy, xx = y + dy, x + dx
            inb = (yy >= 0) & (yy < h) & (xx >= 0) & (xx < w)
            nb = np.where(inb, yy * w + xx, 0)
            good = inb & ok[nb] & (isl[nb] == isl[left])
            acc[good] += flat[nb[good]]
            cnt[good] += 1
        got = cnt > 0
        if not got.any():
            break
        flat[left[got]] = acc[got] / cnt[got][:, None]
        ok[left[got]] = True
        left = left[~got]
    return left


def _apply_validation(img, val: dict, raster, mtype: str) -> float:
    """After a map's bake (Blender's margin keeps the gutter): the texels whose ray was invalid
    become holes, filled from valid texels of the same UV island. Returns the share of the
    island texels that had no clean hit, measured BEFORE the fill."""
    w, h = img.size
    px = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    px = px.reshape(h, w, 4)
    res = val["invalid"].shape[0]
    k = h // res if (h % res == 0 and w == h) else 1
    cov = _upsample(val["covered"], k)
    bad = _upsample(val["invalid"], k)
    isl = _upsample(raster[2], k)
    if cov.shape != (h, w):                       # odd sizes: no texel-level check possible
        return _resolve_sentinel(img, np.ones((h, w), bool), mtype)
    if k > 1:                                     # the coarse check's edge texels too
        grow = bad.copy()
        grow[1:] |= bad[:-1]
        grow[:-1] |= bad[1:]
        grow[:, 1:] |= bad[:, :-1]
        grow[:, :-1] |= bad[:, 1:]
        bad = grow & cov
    sent = (px[..., 0] > 0.99) & (px[..., 1] < 0.01) & (px[..., 2] > 0.99)
    holes = (bad | sent) & cov
    extra = sent & cov & ~bad                    # rays Blender left unbaked that the check passed
    share = val["share"] + float(extra.sum()) / max(int(cov.sum()), 1)
    rgb = px[..., :3]
    if holes.any():
        left = _inpaint(rgb, holes, cov & ~holes, isl)
        if len(left):                            # a whole island without one clean texel
            miss = np.zeros(holes.shape, bool)
            miss.ravel()[left] = True
            rgb[miss] = _fill_colours(rgb, cov & ~miss, miss, 64)
    outside = sent & ~cov
    if outside.any():
        good = cov & ~holes
        neutral = NEUTRAL.get(mtype) or (rgb[good].mean(axis=0, dtype=np.float64) if good.any() else (0.5, 0.5, 0.5))
        rgb[outside] = neutral
    px[..., :3] = rgb
    px[..., 3] = 1.0
    img.pixels.foreach_set(px.ravel())
    return share


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


def _refill_misses(img, high, low, mat, mtype, size, non_color, extrusion, margin, cov, max_ray=None) -> int:
    """Second pass for texels the first bake missed (margin 0, no hit check): bake them again
    with the SAME cage (or the same extrusion) and twice the ray reach, and copy only those
    texels in. It never falls back to a plain fixed distance, which brings back the smear."""
    miss = _sentinel_mask(img) & (cov if cov.shape == (size, size) else True)
    n = int(miss.sum())
    if not n:
        return 0
    tmp = _new_image(f"{img.name}_refill", size, non_color, SENTINEL)
    _set_target(mat, tmp)
    C.select_only(high, low, active=low)
    reach = 2.0 * (max_ray if max_ray else extrusion * 4)
    if mtype == "metallic":
        with _ChannelAsEmission([high], "Metallic"):
            _bake(mtype, extrusion, reach, margin)
    else:
        _bake(mtype, extrusion, reach, margin)
    w, h = img.size
    a = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(a)
    a = a.reshape(h, w, 4)
    b = np.empty(w * h * 4, dtype=np.float32)
    tmp.pixels.foreach_get(b)
    b = b.reshape(h, w, 4)
    got = miss & ~((b[..., 0] > 0.99) & (b[..., 1] < 0.01) & (b[..., 2] > 0.99))
    a[got] = b[got]
    img.pixels.foreach_set(a.ravel())
    _set_target(mat, img)
    bpy.data.images.remove(tmp)
    return int(got.sum())


def run(args: dict) -> dict:
    """Plain call (headless pipeline): runs every step at once."""
    gen = run_iter(args)
    try:
        while True:
            next(gen)
    except StopIteration as stop:
        return stop.value


def run_iter(args: dict):
    """Generator: yields after each map so a UI stays responsive (progress, Stop).

    args (besides sizes and paths): fitted_cage (fit a cage per part), validate_hits (re-cast
    every texel's ray and repair the ones without a clean hit; on with the fitted cage),
    solid_meshes {high object name: welded solid mesh name} (the visible shape of parts welded
    solid; colour then comes from the original without its buried pieces), despeckle (off)."""
    size = int(args.get("texture_size", 2048))
    out_dir = os.path.abspath(args["texture_dir"])
    os.makedirs(out_dir, exist_ok=True)
    maps_wanted = [m for m in args.get("maps", MAP_TYPES) if m in MAP_TYPES]
    extrusion_ratio = float(args.get("cage_extrusion_ratio", 0.01))
    margin = int(args.get("margin_px", 8))
    fitted = bool(args.get("fitted_cage", False))
    validate = fitted and bool(args.get("validate_hits", True))
    solids = args.get("solid_meshes") or {}
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
        extrusion, max_ray = plain, plain * 4
        cage = None
        src = high                                         # what the rays meet
        temps = []
        val = raster = None
        entry = {}
        solid_me = bpy.data.meshes.get(solids.get(high.name, "")) if solids.get(high.name) else None
        mat = None
        baked = {}
        misses = {}
        refilled = {}
        try:
            if fitted:                                     # step-by-step panel turns it on
                STATUS["text"] = f"{part}: fitting the bake cage"
                yield 0.05
                cage, max_ray = build_cage(low, high, size=size, solid=solid_me)
                _CAGE["name"] = cage.name
                entry["cage"] = {"unenclosed": int(cage["forge_unenclosed"]),
                                 "unenclosed_samples": int(cage["forge_unenclosed_samples"]),
                                 "samples": int(cage["forge_samples"]),
                                 "max_ray_mm": round(max_ray * 1000, 2)}
            if validate:
                STATUS["text"] = f"{part}: checking every bake ray"
                yield 0.05
                solid = None
                depth = 0.0
                if solid_me is not None and solid_me != high.data:
                    # colour from the original: without the pieces buried in the welded solid
                    sco = _coords(solid_me)
                    base = _surface_cached(solid_me, sco)
                    solid = _Surface(base.tree, base.two_sided, sco.astype(np.float64))
                    voxel = _voxel_size(solid_me)
                    depth = 2.0 * voxel
                    src, surf, removed = _visible_colour_source(high, solid, depth, voxel)
                    temps.append(src)
                    entry["buried_faces_removed"] = removed
                else:
                    surf = _surface_cached(high)
                raster = _raster(low, _bake_res(size))
                val = _validate_hits(low, high.matrix_world, cage, surf, max_ray, raster, solid, depth)
                entry["invalid_kinds"] = {k: round(v / max(int(val["covered"].sum()), 1), 5)
                                          for k, v in val["kinds"].items()}
            mat = _bake_material(low)
            cov = _uv_coverage(low, size) if val is None else None
            for mi, mtype in enumerate(maps_wanted):
                STATUS["text"] = f"{part}: baking {mtype} ({mi + 1}/{len(maps_wanted)})"
                yield 0.05
                non_color = mtype != "basecolor"
                img = _new_image(f"T_{part}_{mtype}", size, non_color, SENTINEL)
                _set_target(mat, img)
                C.select_only(src, low, active=low)
                if mtype == "metallic":
                    with _ChannelAsEmission([src], "Metallic"):
                        _bake(mtype, extrusion, max_ray, margin)
                else:
                    _bake(mtype, extrusion, max_ray, margin)
                if val is not None:
                    # texels whose ray had no clean hit: filled from their own UV island
                    misses[mtype] = _apply_validation(img, val, raster, mtype)
                else:
                    if cage is not None:
                        refilled[mtype] = _refill_misses(img, src, low, mat, mtype, size, non_color,
                                                         extrusion, margin, cov, max_ray)
                    misses[mtype] = _resolve_sentinel(img, cov, mtype)
                if args.get("despeckle", False):
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
            for o in temps:
                me = o.data
                bpy.data.objects.remove(o)
                if me.users == 0:
                    bpy.data.meshes.remove(me)
        entry["maps"] = {k: os.path.join(out_dir, f"T_{part}_{k}.png") for k in baked}
        if part in cleaned:
            entry["metallic_cleanup"] = cleaned[part]
        if specks.get(part):
            entry["specks_removed"] = specks[part]
        if refilled:
            entry["cage_refilled"] = refilled
        if val is not None:
            # share of the island texels without a clean hit, counted BEFORE they were filled
            entry["invalid_texels"] = {k: round(v, 4) for k, v in misses.items()}
            entry["invalid_texels_max"] = round(max(misses.values(), default=0.0), 4)
        # share of texels inside the UV islands that had to be filled
        entry["bake_miss_ratio"] = round(max(misses.values(), default=0.0), 4)
        entry["bake_misses"] = {k: round(v, 4) for k, v in misses.items()}
        _final_material(low, baked)
        if mat is not None:
            bpy.data.materials.remove(mat)
        report[part] = entry

    c = bpy.data.collections.get(C.HIGH_COLLECTION)
    if c:
        c.hide_render = True
    STATUS["text"] = ""
    return {"parts": report}
