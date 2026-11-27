"""Step 6 bake: the cage encloses the original everywhere Blender starts a ray, never reaches into a
neighbouring surface, every texel's ray is checked, and the panel's number is measured before the
fill. Small scenes, 64-256 px bakes, so the suite stays fast."""

import sys
from pathlib import Path

import pytest

bpy = pytest.importorskip("bpy")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "blender_scripts"))

# the arguments the Step 6 panel bakes with (steps.run_bake), without the solid swap
PANEL = {"samples": 1, "device": "CPU", "cage_extrusion_ratio": 0.01, "margin_px": 16,
         "fitted_cage": True, "validate_hits": True}


def _link(name, bm):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(o)
    return o


def _plane(name, z, size=2.0, cuts=8, hole=0.0):
    import bmesh
    from mathutils import Matrix
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=cuts, y_segments=cuts, size=size / 2, matrix=Matrix.Translation((0, 0, z)))
    if hole:
        dead = [f for f in bm.faces if max(abs(f.calc_center_median().x), abs(f.calc_center_median().y)) < hole]
        bmesh.ops.delete(bm, geom=dead, context="FACES")
    return _link(name, bm)


def _material(name, rgb):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    bsdf = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    bsdf.inputs["Base Color"].default_value = (*rgb, 1)
    return m


def _unwrap(o, smart=True):
    bpy.context.view_layer.objects.active = o
    bpy.ops.object.select_all(action="DESELECT")
    o.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    if smart:
        bpy.ops.uv.smart_project(angle_limit=1.15, island_margin=0.01)
    else:
        bpy.ops.uv.unwrap(margin=0.05)
    bpy.ops.object.mode_set(mode="OBJECT")


def _join(objs, name):
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.object.join()
    o = bpy.context.view_layer.objects.active
    o.name = name
    return o


def _roles(low, high, part):
    low["forge_role"], low["forge_part"] = "low", part
    high["forge_role"], high["forge_part"] = "high", part


def _voxel_copy(src, voxel):
    o = bpy.data.objects.new(src.name + "_v", src.data.copy())
    bpy.context.scene.collection.objects.link(o)
    mod = o.modifiers.new("v", "REMESH")
    mod.mode, mod.voxel_size, mod.adaptivity = "VOXEL", voxel, 0.0
    dg = bpy.context.evaluated_depsgraph_get()
    dg.update()
    me = bpy.data.meshes.new_from_object(o.evaluated_get(dg))
    o.modifiers.remove(mod)
    o.data = me
    return o


def _pixels(path, size):
    import numpy as np
    img = bpy.data.images.load(path)
    px = np.array(img.pixels[:]).reshape(size, size, 4)
    bpy.data.images.remove(img)
    return px


def _texel_points(low, size):
    """Covered texels of the low's UVs: (ys, xs, 3D point on the low)."""
    import numpy as np

    from forge_bpy import bake
    tri, bary, _isl = bake._raster(low, size)
    tv, _tl, co, _vn, _uv = bake._low_arrays(low)
    ys, xs = np.nonzero(tri >= 0)
    P = bake._lerp(co, tv, tri[ys, xs], bary[ys, xs].astype(np.float64))
    return ys, xs, P


def _inside(tree, p) -> bool:
    """5-direction parity: the first hit is a back face for most directions."""
    from mathutils import Vector
    votes = 0
    for d in ((0, 0, 1), (0, 0, -1), (1, 0, 0), (-1, 0, 0), (0, 1, 0)):
        d = Vector(d)
        h = tree.ray_cast(p + d * 1e-6, d)
        if h[0] is not None and h[1].dot(d) > 0:
            votes += 1
    return votes >= 3


def test_cage_encloses_coarse_parts():
    """A thin ear (90 x 12 x 40 mm) and a tapered horn pushed into a head; the new mesh is much
    coarser than the ear is thick (edges 15-25 mm) and lies on the surface. Between its vertices
    the original bulges past a cage made from vertex pushes; the fitted cage must still start
    every ray OUTSIDE the original, wherever Blender interpolates it."""
    import bmesh
    import numpy as np
    from mathutils import Matrix, Vector

    from forge_bpy import bake, density
    bpy.ops.wm.read_homefile(use_empty=True)
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=64, v_segments=40, radius=0.17)
    bmesh.ops.create_uvsphere(bm, u_segments=48, v_segments=24, radius=1.0,
                              matrix=Matrix.Translation((0.19, 0.0, -0.02)) @ Matrix.Diagonal((0.045, 0.006, 0.02, 1)))
    a, b = Vector((0.08, 0.0, 0.14)), Vector((0.2, 0.0, 0.3))
    d = b - a
    bmesh.ops.create_cone(bm, cap_ends=True, segments=32, radius1=0.035, radius2=0.006, depth=d.length,
                          matrix=Matrix.Translation((a + b) / 2) @ d.to_track_quat("Z", "Y").to_matrix().to_4x4())
    orig = _link("Head", bm)
    high = _voxel_copy(orig, 0.0025)                       # the welded solid
    low = _voxel_copy(orig, 0.006)
    dec = low.modifiers.new("d", "DECIMATE")
    dec.ratio = 0.06
    dg = bpy.context.evaluated_depsgraph_get()
    dg.update()
    low.data = bpy.data.meshes.new_from_object(low.evaluated_get(dg))
    low.modifiers.clear()
    density.conform(low.data, high.data, relax=2)
    low.data.update()
    me = low.data
    ev = np.array([e.vertices[:] for e in me.edges])
    co = np.array([v.co[:] for v in me.vertices])
    edge = np.linalg.norm(co[ev[:, 0]] - co[ev[:, 1]], axis=1)
    assert 0.012 < np.median(edge) < 0.03, np.median(edge)     # much coarser than the ear is thick
    surf = bake._surface_of(high)
    fit = bake.fit_cage(low, surf, high.matrix_world, size=512)
    assert fit["unenclosed_samples"] <= 0.001 * fit["samples"], fit
    # an independent check on a finer grid than the fit's own: interpolated cage points
    tv, _tl, co, vn, _uv = bake._low_arrays(low)
    cage = co + vn * fit["push"][:, None]
    g = bake._bary_grid(7)
    fidx = np.repeat(np.arange(len(tv)), len(g))
    bary = np.tile(g, (len(tv), 1))
    C = bake._lerp(cage, tv, fidx, bary)
    inside = sum(_inside(surf.tree, Vector(c)) for c in C)
    assert inside <= 0.001 * len(C), (inside, len(C))
    # and the cage does not run away: pushes stay within the fit's search range
    assert fit["push"].max() < 0.03 * low.dimensions.length, fit["push"].max()


def _ear_scene(flip_right: bool, z_right: float):
    bpy.ops.wm.read_homefile(use_empty=True)
    low = _plane("Ear_low", 0.0)
    _unwrap(low)
    right = _plane("Ear", z_right)
    right.data.materials.append(_material("skin", (0.8, 0.1, 0.1)))      # red: correct
    if flip_right:
        right.data.flip_normals()                                      # inconsistent winding
    back = _plane("Back", 0.018)
    back.data.materials.append(_material("back", (0.1, 0.1, 0.8)))     # blue: the neighbour
    high = _join([right, back], "Ear")
    _roles(low, high, "Ear")


@pytest.mark.parametrize("flip", [False, True])
def test_fit_respects_flipped_normals(tmp_path, flip):
    """The ear case with the right surface 8 mm up and its normals pointing DOWN (raw AI meshes
    have such pieces): an open piece has no inside/outside to trust, so it counts both ways and
    the cage still stops between it and the neighbour."""
    import numpy as np

    from forge_bpy import bake
    _ear_scene(flip, 0.008)
    bake.clear_fit_cache()
    rep = bake.run({**PANEL, "texture_size": 64, "texture_dir": str(tmp_path), "maps": ["basecolor"]})
    px = _pixels(rep["parts"]["Ear"]["maps"]["basecolor"], 64)[16:48, 16:48, :3].reshape(-1, 3)
    red = float(np.mean(px[:, 0] > px[:, 2]))
    assert red > 0.95, red
    assert not [o for o in bpy.data.objects if o.get("forge_cage") or o.get("forge_colour_source")]


def _capsule(bm, x, r, length):
    from mathutils import Matrix
    bmesh = __import__("bmesh")
    bmesh.ops.create_cone(bm, cap_ends=True, segments=32, radius1=r, radius2=r, depth=length,
                          matrix=Matrix.Translation((x, 0, length / 2)))
    for z in (0.0, length):
        bmesh.ops.create_uvsphere(bm, u_segments=32, v_segments=16, radius=r, matrix=Matrix.Translation((x, 0, z)))


def test_body_scale_crevice(tmp_path):
    """Two 8 mm fingers 3 mm apart on a part as big as a body (a 0.45 m ball in the same part):
    a margin of a fixed share of the part's size is wider than the gap. No texel may take the
    OTHER finger's colour, and no normal may come out flipped."""
    import bmesh
    import numpy as np
    from mathutils import Matrix, Vector
    from mathutils.bvhtree import BVHTree

    from forge_bpy import bake
    bpy.ops.wm.read_homefile(use_empty=True)
    r, gap = 0.008, 0.003
    xa = r + gap / 2
    pieces = []
    for name, x, rgb in (("A", xa, (0.8, 0.05, 0.05)), ("B", -xa, (0.05, 0.05, 0.8))):
        bm = bmesh.new()
        _capsule(bm, x, r, 0.09)
        o = _link(name, bm)
        o.data.materials.append(_material(name, rgb))
        pieces.append(o)
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=48, v_segments=24, radius=1.0,
                              matrix=Matrix.Translation((0, 0, -0.01)) @ Matrix.Diagonal((0.045, 0.02, 0.03, 1)))
    palm = _link("P", bm)
    palm.data.materials.append(_material("P", (0.05, 0.6, 0.05)))
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=32, v_segments=16, radius=0.45, matrix=Matrix.Translation((0, 0, -1.0)))
    ball = _link("Ball", bm)
    ball.data.materials.append(_material("Ball", (0.5, 0.5, 0.5)))
    hand = _join(pieces + [palm], "Hand_src")
    low = _voxel_copy(hand, 0.0015)
    dec = low.modifiers.new("d", "DECIMATE")
    dec.ratio = 0.02
    dg = bpy.context.evaluated_depsgraph_get()
    dg.update()
    low.data = bpy.data.meshes.new_from_object(low.evaluated_get(dg))
    low.modifiers.clear()
    low.data.materials.clear()
    low.name = "Hand_low"
    _unwrap(low)                                   # the texture goes to the hand
    bm = bmesh.new()
    bm.from_mesh(low.data)
    uvl = bm.loops.layers.uv.active
    for f in bm.faces:
        for lp in f.loops:
            lp[uvl].uv = lp[uvl].uv * 0.85
    res = bmesh.ops.create_uvsphere(bm, u_segments=16, v_segments=8, radius=0.45,
                                    matrix=Matrix.Translation((0, 0, -1.0)))
    ball_v = set(res["verts"])
    for f in bm.faces:                             # the ball's UVs: a small corner
        if f.verts[0] in ball_v:
            for lp in f.loops:
                co = lp.vert.co
                lp[uvl].uv = (0.88 + 0.11 * (co.x + 0.45) / 0.9, 0.88 + 0.11 * (co.y + 0.45) / 0.9)
    bm.to_mesh(low.data)
    bm.free()
    for p in low.data.polygons:
        p.use_smooth = True
    high = _join([hand, ball], "Hand")
    _roles(low, high, "Hand")
    bake.clear_fit_cache()
    S = 256
    rep = bake.run({**PANEL, "texture_size": S, "texture_dir": str(tmp_path), "maps": ["basecolor", "normal"]})
    part = rep["parts"]["Hand"]
    ys, xs, P = _texel_points(low, S)
    tree = BVHTree.FromObject(high, bpy.context.evaluated_depsgraph_get())
    mi = np.array([p.material_index for p in high.data.polygons])
    names = [m.name for m in high.data.materials]
    truth = np.array([names[mi[tree.find_nearest(Vector(p))[2]]] for p in P])
    col = _pixels(part["maps"]["basecolor"], S)[ys, xs, :3]
    finger = np.isin(truth, ["A", "B"])
    got = np.where(col[:, 0] > col[:, 2], "A", "B")
    sure = np.abs(col[:, 0] - col[:, 2]) > 0.3                # a clear red or blue
    wrong = finger & sure & (got != truth)
    assert finger.sum() > 500 and wrong.sum() == 0, (int(finger.sum()), int(wrong.sum()))
    nz = _pixels(part["maps"]["normal"], S)[ys, xs, 2]
    assert int((nz < 0.5).sum()) == 0, int((nz < 0.5).sum())   # no flipped normals


def test_honest_miss_share(tmp_path):
    """A hole in the original (no surface under part of the new mesh): Blender's 16 px margin
    fills the missed texels from their neighbours, so the old report said 0.0%. The share is
    now measured before any fill, and no magenta is left in the map."""
    import numpy as np

    from forge_bpy import bake
    bpy.ops.wm.read_homefile(use_empty=True)
    low = _plane("P_low", 0.0, cuts=16)
    _unwrap(low, smart=False)
    high = _plane("P", 0.01, cuts=16, hole=0.3)
    high.data.materials.append(_material("r", (0.8, 0.1, 0.1)))
    _roles(low, high, "P")
    bake.clear_fit_cache()
    rep = bake.run({**PANEL, "texture_size": 128, "texture_dir": str(tmp_path), "maps": ["basecolor"]})
    r = rep["parts"]["P"]
    # the hole is 9% of the plane's area: about that share has no clean hit (old report: 0.0)
    assert 0.04 < r["invalid_texels"]["basecolor"] < 0.16, r["invalid_texels"]
    assert r["invalid_kinds"]["miss"] > 0.04, r["invalid_kinds"]
    px = _pixels(r["maps"]["basecolor"], 128)[..., :3]
    magenta = (px[..., 0] > 0.99) & (px[..., 1] < 0.01) & (px[..., 2] > 0.99)
    assert not magenta.any()
    ys, xs, _P = _texel_points(low, 128)
    assert (px[ys, xs, 0] > px[ys, xs, 2]).mean() > 0.99        # the hole is filled with red


def test_validation_marks_backface_hits(tmp_path, monkeypatch):
    """A new mesh inside a thin slab, with the cage forced INSIDE the slab on one half: there
    the rays meet the slab's far side from within (back faces: Cycles would bake a flipped
    normal). The check marks them and fills them from the good half."""
    import bmesh
    import numpy as np
    from mathutils import Matrix

    from forge_bpy import bake
    bpy.ops.wm.read_homefile(use_empty=True)
    low = _plane("Slab_low", 0.0, cuts=8)
    _unwrap(low)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0, matrix=Matrix.Diagonal((2.2, 2.2, 0.02, 1)))
    high = _link("Slab", bm)
    _roles(low, high, "Slab")
    real = bake.fit_cage

    def forced(low_, *a, **k):
        fit = real(low_, *a, **k)
        xs = np.array([v.co.x for v in low_.data.vertices])
        fit["push"] = np.where(xs < -0.01, 0.002, fit["push"])   # 2 mm: still inside the 10 mm half-slab
        return fit
    monkeypatch.setattr(bake, "fit_cage", forced)
    bake.clear_fit_cache()
    rep = bake.run({**PANEL, "texture_size": 64, "texture_dir": str(tmp_path), "maps": ["normal"]})
    r = rep["parts"]["Slab"]
    assert r["invalid_kinds"]["back_face"] > 0.2, r["invalid_kinds"]
    assert r["invalid_texels"]["normal"] > 0.2, r["invalid_texels"]
    ys, xs, _P = _texel_points(low, 64)
    nz = _pixels(r["maps"]["normal"], 64)[ys, xs, 2]
    assert (nz >= 0.5).all(), int((nz < 0.5).sum())                  # no flipped normal left


MARK = (0.484375, 0.015625)       # the centre of one 3 cm face of the original: about 2 texels


def test_despeckle_is_off_by_default_detail_survives(tmp_path):
    """The panel's bake must not 'clean' real detail: a small dark mark (a pupil, a scar) and a
    two-colour border across two UV islands stay exactly as baked."""
    import bmesh
    import numpy as np
    from mathutils import Matrix

    from forge_bpy import bake
    bpy.ops.wm.read_homefile(use_empty=True)
    bm = bmesh.new()
    for x in (-0.51, 0.51):                       # two pieces of new mesh: two UV islands
        bmesh.ops.create_grid(bm, x_segments=4, y_segments=8, size=0.5,
                              matrix=Matrix.Translation((x, 0, 0)) @ Matrix.Diagonal((1.0, 2.0, 1.0, 1)))
    low = _link("Skin_low", bm)
    _unwrap(low)
    high = _plane("Skin", 0.004, cuts=64)
    for name, rgb in (("left", (0.8, 0.1, 0.1)), ("right", (0.1, 0.1, 0.8)), ("mark", (0.02, 0.02, 0.02))):
        high.data.materials.append(_material(name, rgb))
    for p in high.data.polygons:
        c = p.center
        p.material_index = 2 if (abs(c.x - MARK[0]) < 0.01 and abs(c.y - MARK[1]) < 0.01) else (0 if c.x < 0 else 1)
    _roles(low, high, "Skin")
    bake.clear_fit_cache()
    S = 128
    rep = bake.run({**PANEL, "texture_size": S, "texture_dir": str(tmp_path), "maps": ["basecolor"]})
    r = rep["parts"]["Skin"]
    assert "specks_removed" not in r
    ys, xs, P = _texel_points(low, S)
    col = _pixels(r["maps"]["basecolor"], S)[ys, xs, :3]
    at = int(np.argmin(np.linalg.norm(P[:, :2] - np.array(MARK), axis=1)))
    assert col[at].max() < 0.3, col[at]                                # the dark mark is still there
    # every texel is one of the three colours, never a blend across the border
    pal = np.array([[0.8, 0.1, 0.1], [0.1, 0.1, 0.8], [0.02, 0.02, 0.02]]) ** (1 / 2.2)
    dist = np.linalg.norm(col[:, None, :] - pal[None], axis=2).min(axis=1)
    assert (dist < 0.12).mean() > 0.995, float((dist < 0.12).mean())


def test_colour_never_comes_from_buried_pieces(tmp_path, monkeypatch):
    """An AI original often keeps pieces buried inside the visible shape (here a green ball 3 cm
    under the skin of a red head). With rays forced to start inside the head, the plain colour
    source shows the buried green; with the welded solid known, the colour comes from a copy of
    the original without its buried pieces and the bad rays are marked and filled: no green."""
    import bmesh
    import numpy as np
    from mathutils import Matrix

    from forge_bpy import bake
    bpy.ops.wm.read_homefile(use_empty=True)
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=48, v_segments=24, radius=0.2)
    head = _link("Head_src", bm)
    head.data.materials.append(_material("skin", (0.8, 0.1, 0.1)))
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=24, v_segments=12, radius=0.05, matrix=Matrix.Translation((0, 0, 0.12)))
    ball = _link("Buried", bm)
    ball.data.materials.append(_material("buried", (0.05, 0.8, 0.05)))
    orig = _join([head, ball], "Head")
    solid = _voxel_copy(orig, 0.004)
    solid_me = solid.data
    bpy.data.objects.remove(solid)
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=2, radius=0.2)
    low = _link("Head_low", bm)
    _unwrap(low)
    for p in low.data.polygons:
        p.use_smooth = True
    _roles(low, orig, "Head")
    real = bake.fit_cage

    def inside(low_, *a, **k):                 # the cage barely above the new mesh: between its
        fit = real(low_, *a, **k)              # vertices the rays start inside the head
        fit["push"] = np.full(len(fit["push"]), 0.001)
        fit["max_ray"] = 0.5
        return fit
    monkeypatch.setattr(bake, "fit_cage", inside)

    def green(rep):
        ys, xs, _P = _texel_points(low, 64)
        px = _pixels(rep["parts"]["Head"]["maps"]["basecolor"], 64)[ys, xs, :3]
        return int(((px[:, 1] > px[:, 0] + 0.2) & (px[:, 1] > px[:, 2] + 0.2)).sum())
    args = {**PANEL, "texture_size": 64, "texture_dir": str(tmp_path), "maps": ["basecolor"]}
    bake.clear_fit_cache()
    plain = bake.run({**args, "validate_hits": False, "margin_px": 0})
    assert green(plain) > 0                         # the buried colour is reachable
    bake.clear_fit_cache()
    rep = bake.run({**args, "solid_meshes": {orig.name: solid_me.name}})
    r = rep["parts"]["Head"]
    assert r["buried_faces_removed"] > 0 and r["invalid_texels"]["basecolor"] > 0, r
    assert green(rep) == 0
    assert not [o for o in bpy.data.objects if o.get("forge_colour_source")]


def test_panel_says_how_much_had_no_clean_hit():
    """The Step 6 rows: the share measured before the fill decides the colour, in plain words;
    spots the cage could not wrap point back to Step 4."""
    import importlib
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "blender_addon"))
    L = importlib.import_module("forge_send.stages_late")
    rep = {"parts": {"Body": {"maps": dict.fromkeys(("basecolor", "normal", "roughness", "metallic", "ao"), "x"),
                              "invalid_texels": {"normal": 0.034, "basecolor": 0.012}, "invalid_texels_max": 0.034,
                              "bake_miss_ratio": 0.034, "cage": {"unenclosed": 5}},
                     "Sword": {"maps": {"basecolor": "x"}, "invalid_texels_max": 0.0, "bake_miss_ratio": 0.0}}}
    rows = L._bake_rows(rep)
    text = [t for _i, t in rows]
    assert (L.WARN, "Body: 5 maps") in rows
    assert "    3.4% of the texture had no clean hit (filled from neighbours)" in text
    joined = " ".join(text)
    assert "could not wrap 5 spots" in joined and "Step 4" in joined
    assert (L.GOOD, "Sword: 1 map") in rows and "    every texel found its surface cleanly" in text
