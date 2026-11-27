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
    """The Step 6 rows: the share measured before the patch decides the colour, in plain words;
    places the new mesh is too coarse for point back to Step 4; 'cleanly' is claimed only when
    the check could judge every texel (not on open, paper-thin pieces of the original)."""
    import importlib
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "blender_addon"))
    L = importlib.import_module("forge_send.stages_late")
    rep = {"parts": {"Body": {"maps": dict.fromkeys(("basecolor", "normal", "roughness", "metallic", "ao"), "x"),
                              "invalid_texels": {"normal": 0.034, "basecolor": 0.012}, "invalid_texels_max": 0.034,
                              "bake_miss_ratio": 0.034, "cage": {"unenclosed": 5}},
                     "Sword": {"maps": {"basecolor": "x"}, "invalid_texels_max": 0.0, "bake_miss_ratio": 0.0},
                     "Cape": {"maps": {"basecolor": "x"}, "invalid_texels_max": 0.0, "bake_miss_ratio": 0.0,
                              "both_ways": 0.4}}}
    rows = L._bake_rows(rep)
    text = [t for _i, t in rows]
    assert (L.WARN, "Body: 5 maps") in rows
    assert "    3.4% of the texture could not be baked cleanly" in text and "    and was patched from nearby" in text
    joined = " ".join(text)
    assert "5 places where the new mesh is too coarse or folded" in joined and "Step 4" in joined
    assert (L.GOOD, "Sword: 1 map") in rows and "    the whole texture baked cleanly" in text
    cape = text[text.index("Cape: 1 map") + 1:]
    assert cape[0].startswith("    40.0% comes from open, paper-thin pieces") and "Weld into one solid" in " ".join(cape)
    assert text.count("    the whole texture baked cleanly") == 1          # not said for the cape
    for t in text:                                  # plain words: no bake jargon on the panel
        assert not any(w in t.lower() for w in ("texel", "cage", " hit", "ray"))


def _hand(gap=0.003, r=0.008):
    """Two 8 mm 'fingers' `gap` apart on a palm (red / blue / green), as ONE welded piece."""
    import bmesh
    from mathutils import Matrix
    pieces = []
    for name, x, rgb in (("A", r + gap / 2, (0.8, 0.05, 0.05)), ("B", -(r + gap / 2), (0.05, 0.05, 0.8))):
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
    return _join(pieces + [palm], "Hand")


def _coarse_low(src, name, voxel=0.0015, ratio=0.02):
    low = _voxel_copy(src, voxel)
    dec = low.modifiers.new("d", "DECIMATE")
    dec.ratio = ratio
    dg = bpy.context.evaluated_depsgraph_get()
    dg.update()
    low.data = bpy.data.meshes.new_from_object(low.evaluated_get(dg))
    low.modifiers.clear()
    low.data.materials.clear()
    low.name = name
    _unwrap(low)
    for p in low.data.polygons:
        p.use_smooth = True
    return low


def test_one_missing_face_keeps_the_crevice_check(tmp_path):
    """The welded hand with ONE face missing at the bottom of the palm, far from the fingers. A
    hole anywhere used to make the whole piece count both ways: the cage then reached into the
    other finger and the check passed the flipped normals as clean. Only the faces around the
    opening may count both ways."""
    import bmesh
    import numpy as np
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree

    from forge_bpy import bake
    bpy.ops.wm.read_homefile(use_empty=True)
    orig = _hand()
    solid = _voxel_copy(orig, 0.0008)
    bm = bmesh.new()
    bm.from_mesh(solid.data)
    bm.faces.ensure_lookup_table()
    bmesh.ops.delete(bm, geom=[min(bm.faces, key=lambda f: f.calc_center_median().z)], context="FACES")
    bm.to_mesh(solid.data)
    bm.free()
    two, _rec = bake._orientation(solid.data)
    assert 0 < two.sum() < 0.01 * len(two)                    # only the rim of the opening
    solid.name = "Hand_high"
    low = _coarse_low(orig, "Hand_low")
    _roles(low, solid, "Hand")
    orig.hide_render = True
    bake.clear_fit_cache()
    S = 256
    args = {**PANEL, "texture_size": S, "texture_dir": str(tmp_path), "solid_meshes": {solid.name: solid.data.name}}
    r1 = bake.run({**args, "maps": ["normal"]})["parts"]["Hand"]
    solid_me = solid.data
    solid.data = orig.data                                     # colour from the original, as run_bake
    r2 = bake.run({**args, "maps": ["basecolor"]})["parts"]["Hand"]
    solid.data = solid_me
    ys, xs, P = _texel_points(low, S)
    nz = _pixels(r1["maps"]["normal"], S)[ys, xs, 2]
    assert int((nz < 0.5).sum()) == 0, int((nz < 0.5).sum())      # (about 1,000 before)
    tree = BVHTree.FromObject(orig, bpy.context.evaluated_depsgraph_get())
    mi = np.array([p.material_index for p in orig.data.polygons])
    names = [m.name for m in orig.data.materials]
    truth = np.array([names[mi[tree.find_nearest(Vector(p))[2]]] for p in P])
    col = _pixels(r2["maps"]["basecolor"], S)[ys, xs, :3]
    finger = np.isin(truth, ["A", "B"])
    got = np.where(col[:, 0] > col[:, 2], "A", "B")
    wrong = finger & (np.abs(col[:, 0] - col[:, 2]) > 0.3) & (got != truth)
    assert finger.sum() > 2000 and wrong.sum() == 0, (int(finger.sum()), int(wrong.sum()))


def _ear_with_hole(hole: bool):
    """A ball and a thin ear-like box (60 x 40 x 4 mm): top red, bottom blue; optionally a 10 mm
    hole in the ear's top skin. The low: a cube on the ball (it makes the bake reach long, as
    horns do on a full body) and the ear box. Returns (original, low)."""
    import bmesh
    from mathutils import Matrix, Vector
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=48, v_segments=24, radius=0.03, matrix=Matrix.Translation((-0.1, 0, 0)))
    ball = _link("Ball", bm)
    ball.data.materials.append(_material("grey", (0.5, 0.5, 0.5)))
    bm = bmesh.new()
    box = Matrix.Translation((0.05, 0, 0)) @ Matrix.Diagonal((0.06, 0.04, 0.004, 1))
    bmesh.ops.create_cube(bm, size=1.0, matrix=box)
    bmesh.ops.subdivide_edges(bm, edges=bm.edges[:], cuts=15, use_grid_fill=True)
    if hole:
        dead = [f for f in bm.faces if f.calc_center_median().z > 0.0019
                and (f.calc_center_median().xy - Vector((0.05, 0))).length < 0.005]
        bmesh.ops.delete(bm, geom=dead, context="FACES")
    ear = _link("Ear", bm)
    ear.data.materials.append(_material("top", (0.8, 0.05, 0.05)))
    ear.data.materials.append(_material("bottom", (0.05, 0.05, 0.8)))
    for p in ear.data.polygons:
        p.material_index = 0 if p.center.z > -0.001 else 1
    orig = _join([ball, ear], "Body")
    _unwrap(orig)
    bm = bmesh.new()
    h = 0.03 / 3 ** 0.5
    bmesh.ops.create_cube(bm, size=2 * h, matrix=Matrix.Translation((-0.1, 0, 0)))
    bmesh.ops.create_cube(bm, size=1.0, matrix=box)
    bmesh.ops.subdivide_edges(bm, edges=[e for e in bm.edges if (e.verts[0].co - e.verts[1].co).length > 0.005
                                         and e.verts[0].co.x > -0.05], cuts=3, use_grid_fill=True)
    low = _link("Body_low", bm)
    _unwrap(low)
    for p in low.data.polygons:
        p.use_smooth = False
    _roles(low, orig, "Body")
    return orig, low


@pytest.mark.parametrize("welded", [True, False])
def test_colour_never_comes_through_a_hole_in_the_original(tmp_path, welded):
    """Step 3 keeps the raw original (with its holes) for the colour. Over a hole in the ear's
    top skin a ray passes through and meets the bottom skin from inside: blue on the top. With
    the welded solid known, the hit lies under the solid's surface; without it, it is the back
    of a face that has an inside. Either way it is marked and patched from the red around."""
    import numpy as np

    from forge_bpy import bake
    bpy.ops.wm.read_homefile(use_empty=True)
    solid_me = None
    if welded:                                     # the welded solid: made before the hole
        closed, closed_low = _ear_with_hole(False)
        solid = _voxel_copy(closed, 0.0008)
        solid_me = solid.data
        for o in (solid, closed, closed_low):
            bpy.data.objects.remove(o)
    orig, low = _ear_with_hole(True)
    S = 256
    args = {**PANEL, "texture_size": S, "texture_dir": str(tmp_path), "maps": ["basecolor"]}
    bake.clear_fit_cache()
    rep = bake.run({**args, "solid_meshes": {orig.name: solid_me.name}} if welded else args)
    r = rep["parts"]["Body"]
    ys, xs, P = _texel_points(low, S)
    px = _pixels(r["maps"]["basecolor"], S)[ys, xs, :3]
    over = (P[:, 2] > 0.0015) & (np.hypot(P[:, 0] - 0.05, P[:, 1]) < 0.005)
    assert over.sum() > 50
    assert int((px[over, 2] > px[over, 0]).sum()) == 0, int((px[over, 2] > px[over, 0]).sum())
    kind = "buried" if welded else "back_face"
    assert r["invalid_kinds"][kind] > 0.5 * over.sum() / len(ys), r["invalid_kinds"]


def test_gutter_is_regrown_from_repaired_texels(tmp_path, monkeypatch):
    """Blender's margin grows the gutter from the island's border texels BEFORE the check marks
    some of them bad. The slab case with the cage forced inside on one half, and a gutter round
    the island: after the repair no gutter texel next to the bad half may keep a flipped normal
    (mipmaps and filtering pull the gutter into the seams)."""
    import bmesh
    import numpy as np
    from mathutils import Matrix

    from forge_bpy import bake
    bpy.ops.wm.read_homefile(use_empty=True)
    low = _plane("Slab_low", 0.0, cuts=8)
    _unwrap(low)
    for d in low.data.uv_layers.active.data:            # leave room for a 16 px gutter
        d.uv = (0.15 + 0.7 * d.uv[0], 0.15 + 0.7 * d.uv[1])
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0, matrix=Matrix.Diagonal((2.2, 2.2, 0.02, 1)))
    high = _link("Slab", bm)
    _roles(low, high, "Slab")
    real = bake.fit_cage

    def forced(low_, *a, **k):
        fit = real(low_, *a, **k)
        xs = np.array([v.co.x for v in low_.data.vertices])
        fit["push"] = np.where(xs < -0.01, 0.002, fit["push"])
        return fit
    monkeypatch.setattr(bake, "fit_cage", forced)
    bake.clear_fit_cache()
    S = 128
    r = bake.run({**PANEL, "texture_size": S, "texture_dir": str(tmp_path), "maps": ["normal"]})["parts"]["Slab"]
    assert r["invalid_kinds"]["back_face"] > 0.2 and r.get("gutter_redone", {}).get("normal", 0) > 0, r
    nz = _pixels(r["maps"]["normal"], S)[..., 2]
    tri, _b, _i = bake._raster(low, S)
    cov = tri >= 0
    ring = bake._grow(cov, 16) & ~cov                  # the gutter Blender's margin fills
    assert ring.sum() > 1000
    assert int((nz[ring] < 0.5).sum()) == 0, int((nz[ring] < 0.5).sum())    # (2,960 before)


def test_island_rim_texels_are_checked_at_full_size():
    """At 2K and 4K the rays are checked on a 1024 grid. An island's rim at full size (texels
    whose centre is inside the island although the coarse texel's is not) must be repaired too
    when it lies next to a bad texel, not left as baked."""
    import numpy as np

    from forge_bpy import bake
    bpy.ops.wm.read_homefile(use_empty=True)
    n, k = 8, 2
    img = bpy.data.images.new("rim", n, n, alpha=False, float_buffer=True)
    covered = np.zeros((n // k, n // k), bool)
    covered[:3] = True                                 # coarse rows 0-2 inside the island
    invalid = np.zeros_like(covered)
    invalid[2, 1] = True                               # one bad coarse texel: full rows 4-5, cols 2-3
    island = np.full((n, n), -1, np.int32)
    island[:7] = 0                                     # full size: row 6 is the island's rim
    px = np.zeros((n, n, 4), np.float32)
    px[..., 2] = px[..., 3] = 1.0                      # blue: a clean bake
    for y, x in ((4, 2), (4, 3), (5, 2), (5, 3), (6, 2), (6, 3)):
        px[y, x] = (1, 0, 0, 1)                        # red: what the bad rays baked, rim included
    img.pixels.foreach_set(px.ravel())
    val = {"invalid": invalid, "covered": covered, "share": 1 / covered.sum()}
    out = bake._apply_validation(img, val, island, "basecolor", margin=2)
    res = np.empty(n * n * 4, np.float32)
    img.pixels.foreach_get(res)
    res = res.reshape(n, n, 4)
    red = res[..., 0] > res[..., 2]
    assert not red[island >= 0].any(), np.argwhere(red)
    assert not red.any() and out["filled"] >= 6, out
    bpy.data.images.remove(img)


def test_a_surface_facing_away_never_bakes(tmp_path):
    """Blender bakes a face's normal as it is, even when the ray meets it from behind: an open,
    paper-thin piece of the original seen from its back comes out as a flipped normal. Half the
    sheet above the new mesh faces down: those texels are marked and patched from the half that
    faces up; colour does not care which side it sees."""
    import bmesh
    from mathutils import Matrix

    from forge_bpy import bake
    bpy.ops.wm.read_homefile(use_empty=True)
    low = _plane("Sheet_low", 0.0)
    _unwrap(low)
    bm = bmesh.new()
    for x, flip in ((-0.5, True), (0.5, False)):     # two open halves, 1 mm apart
        res = bmesh.ops.create_grid(bm, x_segments=8, y_segments=16, size=0.5,
                                    matrix=Matrix.Translation((x * 1.002, 0, 0.008)) @ Matrix.Diagonal((0.999, 2.0, 1, 1)))
        if flip:
            bmesh.ops.reverse_faces(bm, faces=list({f for v in res["verts"] for f in v.link_faces}))
    high = _link("Sheet", bm)
    high.data.materials.append(_material("skin", (0.8, 0.1, 0.1)))
    _roles(low, high, "Sheet")
    bake.clear_fit_cache()
    S = 64
    rep = bake.run({**PANEL, "texture_size": S, "texture_dir": str(tmp_path), "maps": ["normal"]})
    r = rep["parts"]["Sheet"]
    assert r["invalid_kinds"]["faces_away"] > 0.3, r["invalid_kinds"]
    ys, xs, _P = _texel_points(low, S)
    nz = _pixels(r["maps"]["normal"], S)[ys, xs, 2]
    assert (nz >= 0.5).all(), int((nz < 0.5).sum())
    bake.clear_fit_cache()
    rep = bake.run({**PANEL, "texture_size": S, "texture_dir": str(tmp_path), "maps": ["basecolor"]})
    r = rep["parts"]["Sheet"]
    assert r["invalid_texels"]["basecolor"] < 0.01 and r["both_ways"] > 0.3, r   # seen, but not checkable


def test_buried_test_keeps_one_voxel_cells_on_a_big_solid():
    """The 'buried in the welded solid' test skips points next to the solid's surface with a
    grid of one-voxel cells. On a big or fine solid a dense grid had to be coarsened (a cap on
    its size), so points a few voxels deep were skipped as 'next to the surface'. The cells are
    now a sparse set: no cap."""
    import bmesh
    import numpy as np
    from mathutils import Matrix

    from forge_bpy import bake
    bpy.ops.wm.read_homefile(use_empty=True)
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=320, v_segments=160, radius=0.05)          # ~1 mm edges
    bmesh.ops.create_cube(bm, size=0.01, matrix=Matrix.Translation((3.0, 3.0, 3.0)))    # far away
    solid = _link("Solid", bm)
    co = np.array([v.co[:] for v in solid.data.vertices])
    surf = bake._surface_of(solid)
    S = bake._Surface(surf.tree, surf.two_sided, co)
    rng = np.random.default_rng(1)
    d = rng.normal(size=(200, 3))
    d /= np.linalg.norm(d, axis=1, keepdims=True)
    deep = d * (0.05 - 0.006)                       # 6 mm (6 voxels) under the surface
    shallow = d * (0.05 - 0.0005)                   # half a voxel under it
    out = bake._deep_mask(S, np.concatenate([deep, shallow]), depth=0.002, cell=0.001)
    assert out[:200].all() and not out[200:].any(), (int(out[:200].sum()), int(out[200:].sum()))


def test_caches_see_flipped_faces_and_new_corners():
    """The ray tree and the texel map are cached between the passes. Flipped faces with the same
    coordinates are a different surface (which way the faces point decides the check), and the
    same UVs on other corners are other islands."""
    import bmesh
    import numpy as np

    from forge_bpy import bake
    bpy.ops.wm.read_homefile(use_empty=True)
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=16, v_segments=8, radius=0.1)
    o = _link("S", bm)
    bake.clear_fit_cache()
    a = bake._surface_cached(o)
    assert bake._surface_cached(o) is a
    o.data.flip_normals()
    assert bake._surface_cached(o) is not a
    low = _plane("L", 0.0, cuts=4)
    _unwrap(low)
    r1 = bake._raster(low, 32)
    me = low.data
    lv = np.array([lp.vertex_index for lp in me.loops])
    uv = np.array([d.uv[:] for d in me.uv_layers.active.data])
    # the same corners' UVs, but one corner moved onto another vertex: other islands may follow
    me.loops[0].vertex_index = int(lv[1])
    me.uv_layers.active.data.foreach_set("uv", uv.ravel())
    assert bake._raster(low, 32) is not r1


def test_a_failed_or_stopped_bake_frees_the_ray_trees(tmp_path, monkeypatch):
    """The ray trees of multi-million-face originals are cached during a bake. When a pass fails
    or Stop closes the job, run_bake must still free them (and put the welded solids back)."""
    import importlib
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "blender_addon"))
    S = importlib.import_module("forge_send.steps")
    B = S._mod("bake")
    bpy.ops.wm.read_homefile(use_empty=True)
    monkeypatch.setattr(S, "work_dir", lambda: tmp_path)

    def detail_pass(args):
        B._SURF["tree"] = object()
        B._FIT["fit"] = {}
        B._RASTER["map"] = ()
        yield 0.1
        raise RuntimeError("detail pass failed")
    monkeypatch.setattr(B, "run_iter", detail_pass)
    gen = S.run_bake(64, samples=1, device="CPU")
    with pytest.raises(RuntimeError):
        for _ in gen:
            pass
    assert not B._SURF and not B._FIT and not B._RASTER
    gen = S.run_bake(64, samples=1, device="CPU")          # Stop during the detail pass
    next(gen)
    assert B._SURF
    gen.close()
    assert not B._SURF and not B._FIT and not B._RASTER


def test_a_flipped_normal_in_the_result_is_patched_whatever_the_check_said():
    """Where Blender's ray and the re-cast one part ways (long grazing rays at a coarse part), the
    check can pass a texel that comes out with its normal pointing INTO the new surface. That is
    never a correct bake (an engine rebuilds z as positive): the normal map is read back, those
    texels are patched and counted, and the same texels are patched in AO (same rays)."""
    import numpy as np

    from forge_bpy import bake
    bpy.ops.wm.read_homefile(use_empty=True)
    n = 8
    island = np.zeros((n, n), np.int32)
    val = {"invalid": np.zeros((n, n), bool), "covered": np.ones((n, n), bool), "share": 0.0}
    nm = bpy.data.images.new("nm", n, n, alpha=False, float_buffer=True)
    px = np.zeros((n, n, 4), np.float32)
    px[...] = (0.5, 0.5, 1.0, 1.0)                    # straight up
    px[3:5, 3:5] = (0.5, 0.9, 0.2, 1.0)               # pointing into the surface (z = -0.6)
    nm.pixels.foreach_set(px.ravel())
    out = bake._apply_validation(nm, val, island, "normal", margin=2)
    res = np.empty(n * n * 4, np.float32)
    nm.pixels.foreach_get(res)
    assert (res.reshape(n, n, 4)[..., 2] > 0.99).all()
    assert abs(out["share"] - 4 / 64) < 1e-6 and int(out["flipped"].sum()) == 4, out["share"]
    ao = bpy.data.images.new("ao", n, n, alpha=False, float_buffer=True)
    px[...] = (1.0, 1.0, 1.0, 1.0)
    px[3:5, 3:5] = (0.0, 0.0, 0.0, 1.0)              # the same bad rays: black
    ao.pixels.foreach_set(px.ravel())
    out = bake._apply_validation(ao, val, island, "ao", margin=2, extra=out["flipped"])
    ao.pixels.foreach_get(res)
    assert (res.reshape(n, n, 4)[..., 0] > 0.99).all() and abs(out["share"] - 4 / 64) < 1e-6
    bpy.data.images.remove(nm)
    bpy.data.images.remove(ao)
