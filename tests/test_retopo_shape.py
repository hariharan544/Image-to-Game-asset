"""Retopology shape check: a thin part lost by the remesher is painted denser and re-run."""

import sys
from pathlib import Path

import pytest

bpy = pytest.importorskip("bpy")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "blender_scripts"))


def _body_with_tail():
    import bmesh
    bpy.ops.wm.read_homefile(use_empty=True)          # each test starts from an empty scene
    from mathutils import Matrix
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=6, radius=1.0)
    res = bmesh.ops.create_cone(bm, cap_ends=True, segments=10, radius1=0.04, radius2=0.02, depth=1.0,
                                matrix=Matrix.Translation((1.45, 0, 0)) @ Matrix.Rotation(1.5708, 4, "Y"))
    vs = set(res["verts"])
    bmesh.ops.subdivide_edges(bm, edges=[e for e in bm.edges if e.verts[0] in vs and e.verts[1] in vs],
                              cuts=10, use_grid_fill=True)
    me = bpy.data.meshes.new("Body")
    bm.to_mesh(me)
    o = bpy.data.objects.new("Body_low", me)
    bpy.context.scene.collection.objects.link(o)
    o["forge_role"], o["forge_part"] = "low", "Body"
    return o


def test_lost_tail_is_detected_painted_and_remeshed(monkeypatch):
    import numpy as np

    from forge_bpy import density, retopo
    o = _body_with_tail()
    calls = []

    def fake_qr(obj, quads, args, timeout):
        """Stand-in for Quad Remesher: keeps the tail only where the density map is red."""
        yield 0.0
        me = obj.data
        attr = me.color_attributes.get(density.QR_ATTR)
        red = np.zeros(len(me.vertices), bool)
        if attr is not None:
            col = np.empty(len(me.loops) * 4, np.float32)
            attr.data.foreach_get("color_srgb", col)
            lv = np.array([l.vertex_index for l in me.loops])
            red[lv[(col.reshape(-1, 4)[:, 1] < 0.1)]] = True
        import bmesh
        bm = bmesh.new()
        bm.from_mesh(me)
        bm.verts.ensure_lookup_table()
        tail = [v for v in bm.verts if v.co.x > 1.05]
        kept_tail = all(red[v.index] for v in tail[:20])
        if not kept_tail:
            bmesh.ops.delete(bm, geom=tail, context="VERTS")
        bm.to_mesh(me)
        bm.free()
        calls.append(kept_tail)
        return True

    monkeypatch.setattr(retopo, "_qr_part", fake_qr)
    from forge_bpy import common
    gen = retopo._run_qr({"target_tris": common.tri_count(o), "qr_timeout": 5})
    try:
        while True:
            next(gen)
    except StopIteration as stop:
        rep = stop.value
    shape = rep["parts"]["Body"]["shape"]
    assert calls == [False, True], calls                      # lost once, kept after painting
    assert shape["refined"] == 1 and shape["lost_pct"] < 0.2, shape
    assert max(v.co.x for v in o.data.vertices) > 1.9            # the tail is back
    assert rep["parts"]["Body"]["method"] == "quadremesher(shape-fixed)"


def test_thin_part_rescued_when_remesher_keeps_losing_it(monkeypatch):
    import bmesh as bm_

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "blender_addon"))
    from forge_bpy import common, retopo
    from forge_send import geometry as G
    o = _body_with_tail()
    faces0 = len(o.data.polygons)
    calls = []

    def stubborn_qr(obj, quads, args, timeout):
        """Like the director's run: the body comes back with the tail collapsed into an
        off-centre stub; a part remeshed on its own comes back as a clean quad mesh."""
        yield 0.0
        bm = bm_.new()
        bm.from_mesh(obj.data)
        has_body = any(v.co.x < 0.5 for v in bm.verts)
        if has_body:
            for v in bm.verts:
                if v.co.x > 1.0:
                    v.co.x = 1.0 + 0.15 * (v.co.x - 1.0)
                    v.co.y = v.co.y * 0.7 + 0.03
                    v.co.z *= 0.7
            new = bpy.data.meshes.new(obj.data.name + "_qr")
            bm.to_mesh(new)
            bm.free()
            retopo._replace_mesh(obj, new)
        else:
            bm.free()
            assert retopo._quadriflow(obj, max(int(quads * 2), 400), {})
        calls.append("body" if has_body else "piece")
        return True

    monkeypatch.setattr(retopo, "_qr_part", stubborn_qr)
    gen = retopo._run_qr({"target_tris": common.tri_count(o), "qr_timeout": 5})
    try:
        while True:
            next(gen)
    except StopIteration as stop:
        rep = stop.value
    shape = rep["parts"]["Body"]["shape"]
    assert calls == ["body", "body", "piece"], calls     # 1 density retry, then the rescue
    assert shape["rescued"] == 1 and shape["lost_pct"] < 0.5 and shape["max_gap_pct"] < 1.5, shape
    assert max(v.co.x for v in o.data.vertices) > 1.9              # the tail is back
    assert len(o.data.polygons) > 0.8 * faces0 * 0.9               # the body was never destroyed
    assert G.analyse(o)["holes"] == 0
    assert rep["parts"]["Body"]["method"] == "quadremesher(rescued)"
    assert not [x for x in bpy.data.objects if "_rescue" in x.name]


def test_late_quad_remesher_results_are_never_taken():
    from forge_bpy import retopo
    bpy.ops.wm.read_homefile(use_empty=True)

    def obj(name):
        o = bpy.data.objects.new(name, bpy.data.meshes.new(name))
        bpy.context.scene.collection.objects.link(o)
        return o
    body = obj("Body_low")
    for n in ("Retopo_Body_low", "Retopo_Body_low.001", "Retopo_Body_low_rescue0", "Retopo_Body_lowX"):
        obj(n)
    match = sorted(o.name for o in bpy.data.objects if retopo._is_result_of(o, "Body_low"))
    assert match == ["Retopo_Body_low", "Retopo_Body_low.001"]
    # a timed-out part: its late import is removed and the part shown again
    body.hide_set(True)
    retopo._QR_PENDING["Body_low"] = True
    retopo._purge_late_results()
    assert "Body_low" not in retopo._QR_PENDING and not body.hide_get()
    assert sorted(o.name for o in bpy.data.objects) == ["Body_low", "Retopo_Body_lowX", "Retopo_Body_low_rescue0"]
    # a refusal (licence / busy engine) is remembered: no 15-minute wait per part
    args = {"_qr_refused": True}
    gen = retopo._qr_part(body, 100, args, 900)
    try:
        next(gen)
        raise AssertionError("should not wait")
    except StopIteration as stop:
        assert stop.value is False


def test_one_sided_detail_turns_mirror_symmetry_off():
    import bmesh as bm_

    from forge_bpy import density
    bm = bm_.new()
    bm_.ops.create_icosphere(bm, subdivisions=5, radius=1.0)
    me = bpy.data.meshes.new("sym")
    bm.to_mesh(me)
    assert density.asymmetry(me) < 0.01                  # a sphere is symmetric
    # a notch on the +X side only (like the cut in the bull's left ear)
    for v in bm.verts:
        if v.co.x > 0.6 and abs(v.co.z) < 0.4:
            v.co *= 0.9
    bm.to_mesh(me)
    bm.free()
    assert density.asymmetry(me) > 0.02


def test_despeckle_removes_dots_keeps_edges():
    import numpy as np

    from forge_bpy.bake import despeckle_array
    px = np.zeros((64, 64, 4), np.float32)
    px[..., :3] = (0.6, 0.35, 0.2)                 # brown skin
    px[:, 40:, :3] = (0.3, 0.15, 0.1)              # a darker fur patch: a real edge
    px[20, 10, :3] = (0.95, 0.9, 0.85)             # light speck
    px[30:32, 20:22, :3] = (0.9, 0.85, 0.8)        # 2x2 speck
    px[50, 10, :3] = (0.05, 0.02, 0.01)            # dark speck
    edge_before = px[:, 38:42].copy()
    n = despeckle_array(px, radius=3, threshold=0.12)
    assert n > 0
    for y, x in ((20, 10), (30, 20), (31, 21), (50, 10)):
        assert np.allclose(px[y, x, :3], (0.6, 0.35, 0.2), atol=0.05), (y, x, px[y, x])
    assert np.allclose(px[:, 38:42], edge_before)   # the patch border is untouched


def _plane(name, z, size=2.0, cuts=8):
    import bmesh as bm_
    from mathutils import Matrix
    bm = bm_.new()
    bm_.ops.create_grid(bm, x_segments=cuts, y_segments=cuts, size=size / 2, matrix=Matrix.Translation((0, 0, z)))
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(o)
    return o


def _flat_material(name, rgb):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    bsdf = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    bsdf.inputs["Base Color"].default_value = (*rgb, 1)
    return m


@pytest.mark.parametrize("fitted", [False, True])
def test_fitted_cage_does_not_pick_up_a_neighbouring_surface(tmp_path, fitted):
    """Like the inside of the bull's ear: the right surface is just above the new one, a
    NEIGHBOURING surface (the ear's back) a little further. A fixed bake distance starts the
    rays beyond the neighbour and fetches its colour (the smear); the fitted cage does not."""
    import numpy as np

    from forge_bpy import bake
    bpy.ops.wm.read_homefile(use_empty=True)
    low = _plane("Ear_low", 0.0)
    bpy.context.view_layer.objects.active = low
    low.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project()
    bpy.ops.object.mode_set(mode="OBJECT")
    right = _plane("Ear", 0.004)
    right.data.materials.append(_flat_material("skin", (0.8, 0.1, 0.1)))      # red: correct
    back = _plane("Back", 0.018)
    back.data.materials.append(_flat_material("back", (0.1, 0.1, 0.8)))       # blue: neighbour
    # one "high" object with both surfaces (as in a real mesh)
    bpy.ops.object.select_all(action="DESELECT")
    right.select_set(True)
    back.select_set(True)
    bpy.context.view_layer.objects.active = right
    bpy.ops.object.join()
    for o, role in ((low, "low"), (right, "high")):
        o["forge_role"], o["forge_part"] = role, "Ear"
    rep = bake.run({"texture_size": 64, "texture_dir": str(tmp_path), "maps": ["basecolor"], "samples": 1,
                    "device": "CPU", "cage_extrusion_ratio": 0.01, "fitted_cage": fitted, "despeckle": False})
    img = bpy.data.images.load(rep["parts"]["Ear"]["maps"]["basecolor"])
    px = np.array(img.pixels[:]).reshape(64, 64, 4)[16:48, 16:48, :3].reshape(-1, 3)
    red = float(np.mean(px[:, 0] > px[:, 2]))
    if fitted:
        assert red > 0.95, red              # the right colour everywhere
    else:
        assert red < 0.5, red               # the old fixed distance shows the smear
    assert not [o for o in bpy.data.objects if o.get("forge_cage")]


def test_texels_the_cage_misses_are_baked_again_no_pink(tmp_path):
    import numpy as np

    from forge_bpy import bake
    bpy.ops.wm.read_homefile(use_empty=True)
    low = _plane("Skin_low", 0.0)
    bpy.context.view_layer.objects.active = low
    low.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project()
    bpy.ops.object.mode_set(mode="OBJECT")
    high = _plane("Skin", 0.004)
    high.data.materials.append(_flat_material("skin", (0.8, 0.1, 0.1)))
    mat = bake._bake_material(low)
    img = bake._new_image("T_Skin_basecolor", 64, False, bake.SENTINEL)   # all "missed" (pink)
    bake._setup_cycles(1, "CPU")
    cov = np.ones((64, 64), bool)
    n = bake._refill_misses(img, high, low, mat, "basecolor", 64, False, 0.03, 4, cov)
    assert n > 0
    assert bake._sentinel_mask(img)[16:48, 16:48].sum() == 0      # no pink left inside
    px = np.array(img.pixels[:]).reshape(64, 64, 4)[16:48, 16:48, :3]
    assert (px[..., 0] > px[..., 2]).mean() > 0.95                 # the right (red) colour


def test_fit_to_original_restores_one_sided_notch():
    """Symmetric remesh copies the right ear to the left; fitting to the original puts the
    left ear's notch back."""
    import bmesh as bm_
    import numpy as np

    from forge_bpy import density
    bm = bm_.new()
    bm_.ops.create_icosphere(bm, subdivisions=6, radius=1.0)
    for v in bm.verts:                                  # the original: a dent on +X only
        if v.co.x > 0.7 and abs(v.co.z) < 0.35 and abs(v.co.y) < 0.35:
            v.co *= 0.9
    src = bpy.data.meshes.new("orig")
    bm.to_mesh(src)
    bm.free()
    bm = bm_.new()
    bm_.ops.create_icosphere(bm, subdivisions=4, radius=1.0)   # the symmetric remesh
    low = bpy.data.meshes.new("low")
    bm.to_mesh(low)
    bm.free()

    def dent_depth(me):
        co = np.array([v.co[:] for v in me.vertices])
        sel = (co[:, 0] > 0.5) & (np.abs(co[:, 1]) < 0.15) & (np.abs(co[:, 2]) < 0.15)
        return 1.0 - np.linalg.norm(co[sel], axis=1).min()
    assert dent_depth(low) < 0.02
    density.conform(low, src)
    assert dent_depth(low) > 0.07                         # the notch is back
    co = np.array([v.co[:] for v in low.vertices])
    other = co[co[:, 0] < -0.7]
    assert np.allclose(np.linalg.norm(other, axis=1), 1.0, atol=0.02)   # the other side unchanged


def test_mirrored_run_that_loses_a_one_sided_part_reruns_without_mirror(monkeypatch):
    """The bull's tail curves to one side: a mirrored remesh loses it. The next run must be
    WITHOUT mirror (not denser and still mirrored)."""
    import bmesh as bm_

    from forge_bpy import common, retopo
    o = _body_with_tail()
    o["forge_symmetry_x"] = True
    seen = []

    def qr(obj, quads, args, timeout):
        yield 0.0
        mirrored = bool(obj.get("forge_symmetry_x"))
        seen.append(mirrored)
        if mirrored:                       # a mirror cannot keep a one-sided tail
            bm = bm_.new()
            bm.from_mesh(obj.data)
            bm_.ops.delete(bm, geom=[v for v in bm.verts if v.co.x > 1.05], context="VERTS")
            holes = [e for e in bm.edges if e.is_boundary]
            if holes:
                bm_.ops.holes_fill(bm, edges=holes)
            new = bpy.data.meshes.new("m")
            bm.to_mesh(new)
            bm.free()
            retopo._replace_mesh(obj, new)
        return True

    monkeypatch.setattr(retopo, "_qr_part", qr)
    gen = retopo._run_qr({"target_tris": common.tri_count(o), "qr_timeout": 5, "conform": False})
    try:
        while True:
            next(gen)
    except StopIteration as stop:
        rep = stop.value
    assert seen == [True, False], seen                          # one mirrored run, then one without
    assert rep["parts"]["Body"]["method"] == "quadremesher(no-mirror)"
    assert rep["parts"]["Body"]["shape"]["lost_pct"] < 0.2
    assert max(v.co.x for v in o.data.vertices) > 1.9


def test_flattened_face_detail_is_refined_not_rebuilt(monkeypatch):
    """A shallow mouth-corner pocket: too small for the normal shape check, caught by the
    stricter face check -> one denser run (never the thin-part rebuild)."""
    import bmesh as bm_
    import numpy as np

    from forge_bpy import common, density, retopo
    bpy.ops.wm.read_homefile(use_empty=True)
    bm = bm_.new()
    bm_.ops.create_icosphere(bm, subdivisions=6, radius=1.0)
    for v in bm.verts:                         # a shallow pocket (the mouth corner)
        if (v.co - __import__("mathutils").Vector((0.0, -1.0, 0.0))).length < 0.2:
            v.co *= 0.98
    me = bpy.data.meshes.new("Body")
    bm.to_mesh(me)
    bm.free()
    co = np.array([v.co[:] for v in me.vertices])
    density.write_strict(me, np.where(co[:, 2] > -0.5, 0.35, 1.0))     # "face" = upper part
    o = bpy.data.objects.new("Body_low", me)
    bpy.context.scene.collection.objects.link(o)
    o["forge_role"], o["forge_part"] = "low", "Body"
    calls = []

    def qr(obj, quads, args, timeout):
        """Flattens the pocket unless the density map marks it red."""
        yield 0.0
        m = obj.data
        a = m.color_attributes.get(density.QR_ATTR)
        red = set()
        if a is not None:
            col = np.empty(len(m.loops) * 4, np.float32)
            a.data.foreach_get("color_srgb", col)
            lv = np.array([l.vertex_index for l in m.loops])
            red = set(lv[col.reshape(-1, 4)[:, 1] < 0.1].tolist())
        pocket = [v for v in m.vertices if (v.co - __import__("mathutils").Vector((0, -0.99, 0))).length < 0.2]
        kept = bool(pocket) and all(v.index in red for v in pocket[:10])
        if not kept:
            for v in pocket:
                v.co = v.co.normalized()
        calls.append(kept)
        return True

    monkeypatch.setattr(retopo, "_qr_part", qr)
    gen = retopo._run_qr({"target_tris": common.tri_count(o), "qr_timeout": 5, "conform": False})
    try:
        while True:
            next(gen)
    except StopIteration as stop:
        rep = stop.value
    r = rep["parts"]["Body"]
    assert calls == [False, True], calls
    assert r["method"] == "quadremesher(face-refined)" and r["shape"]["rescued"] == 0, r
    assert r["shape"]["face_lost_pct"] < 0.4


def _grooved_head(depth_rel=0.003, w=0.02):
    """Icosphere with a smile-shaped groove on BOTH sides of the front; front marked strict."""
    import math

    import bmesh as bm_
    import numpy as np

    from forge_bpy import density
    bpy.ops.wm.read_homefile(use_empty=True)
    bm = bm_.new()
    bm_.ops.create_icosphere(bm, subdivisions=7, radius=1.0)
    size = 2 * math.sqrt(3)
    depth = depth_rel * size
    floor = []
    for v in bm.verts:
        x, y, z = v.co
        ax = abs(x)
        if 0.15 < ax < 0.6 and y < 0:
            z0 = -0.25 + 0.6 * (ax - 0.15) ** 2          # the smile curve
            d = abs(z - z0)
            if d < w:
                v.co *= (1.0 - depth * (1 - (d / w) ** 2))
                if d < 0.25 * w:
                    floor.append(v.index)
    me = bpy.data.meshes.new("Head")
    bm.to_mesh(me)
    bm.free()
    co = np.array([v.co[:] for v in me.vertices])
    density.write_strict(me, np.where(co[:, 1] < 0, 0.35, 1.0))
    return me, np.array(floor), size


def _rotated_quad_sphere(edge):
    """A coarse quad sphere rotated 25 deg about Y: its rows cross the groove diagonally."""
    import math

    import bmesh as bm_
    from mathutils import Matrix
    bm = bm_.new()
    segs = max(8, int(round(2 * math.pi / edge)))
    bm_.ops.create_uvsphere(bm, u_segments=segs, v_segments=segs // 2, radius=1.0,
                            matrix=Matrix.Rotation(math.radians(25), 4, "Y"))
    me = bpy.data.meshes.new("qr")
    bm.to_mesh(me)
    bm.free()
    return me


@pytest.mark.parametrize("carve", [False, True])
def test_narrow_groove_survives_on_both_sides(monkeypatch, carve):
    import numpy as np
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree

    from forge_bpy import common, retopo
    src, floor, size = _grooved_head()
    o = bpy.data.objects.new("Head_low", src.copy())
    bpy.context.scene.collection.objects.link(o)
    o["forge_role"], o["forge_part"] = "low", "Head"
    counts = []

    def qr(obj, quads, args, timeout):
        """Ignores the density map entirely (worst case): a coarse rotated quad sphere."""
        yield 0.0
        new = _rotated_quad_sphere(4 * 0.02)
        retopo._replace_mesh(obj, new)
        counts.append(common.tri_count(obj))
        return True

    monkeypatch.setattr(retopo, "_qr_part", qr)
    gen = retopo._run_qr({"target_tris": 100000, "qr_timeout": 5, "carve": carve, "shape_check": False})
    try:
        while True:
            next(gen)
    except StopIteration as stop:
        rep = stop.value
    me = o.data
    tree = BVHTree.FromPolygons([v.co.copy() for v in me.vertices], [tuple(p.vertices) for p in me.polygons])
    co = np.array([v.co[:] for v in src.vertices])

    def kept(sel):
        pts = co[floor[sel]]
        return np.mean([tree.find_nearest(Vector(p))[3] <= 0.001 * size for p in pts])
    left, right = kept(co[floor, 0] > 0), kept(co[floor, 0] < 0)
    if carve:
        assert left >= 0.9 and right >= 0.9, (left, right)
        assert common.tri_count(o) <= 1.07 * counts[-1]
        assert max(len(p.vertices) for p in me.polygons) <= 4
        assert "decimate" not in rep["parts"]["Head"]["method"]
        cr = rep["parts"]["Head"]["creases"]
        assert cr["left_pct"] > 0 and cr["right_pct"] > 0 and cr["carved_tris"] > 0
    else:
        assert min(left, right) < 0.5, (left, right)     # control: without carving it is lost
