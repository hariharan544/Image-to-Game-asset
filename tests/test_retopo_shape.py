"""Retopology shape check: a thin part lost by the remesher is painted denser and re-run."""

import sys
from pathlib import Path

import pytest

bpy = pytest.importorskip("bpy")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "blender_scripts"))


def _body_with_tail(r1=0.04, r2=0.02):
    import bmesh
    bpy.ops.wm.read_homefile(use_empty=True)          # each test starts from an empty scene
    from mathutils import Matrix
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=6, radius=1.0)
    res = bmesh.ops.create_cone(bm, cap_ends=True, segments=10, radius1=r1, radius2=r2, depth=1.0,
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


def test_quad_remesher_refusal_is_remembered():
    """A refusal (licence / busy engine) is remembered: no 15-minute wait per part."""
    from forge_bpy import retopo
    bpy.ops.wm.read_homefile(use_empty=True)
    body = bpy.data.objects.new("Body_low", bpy.data.meshes.new("Body_low"))
    bpy.context.scene.collection.objects.link(body)
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


def test_mirrored_run_that_loses_a_one_sided_part_keeps_the_mirror_and_rebuilds_the_part(monkeypatch):
    """The bull's tail curves to one side: the mirrored remesh loses it. The mirrored result
    (good, symmetric face) is KEPT and only the tail is rebuilt - no unmirrored re-run, which
    re-rolls the whole head (the director saw the right mouth side washed out that way)."""
    import bmesh as bm_

    from forge_bpy import common, retopo
    o = _body_with_tail()
    o["forge_symmetry_x"] = True
    seen = []

    def qr(obj, quads, args, timeout):
        yield 0.0
        mirrored = bool(obj.get("forge_symmetry_x"))
        whole = any(v.co.x < 0.5 for v in obj.data.vertices)
        seen.append("mirrored-body" if (whole and mirrored) else ("body" if whole else "piece"))
        if whole and mirrored:              # a mirror cannot keep a one-sided tail
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
        elif not whole:
            assert retopo._quadriflow(obj, max(int(quads * 2), 400), {})
        return True

    monkeypatch.setattr(retopo, "_qr_part", qr)
    gen = retopo._run_qr({"target_tris": common.tri_count(o), "qr_timeout": 5, "conform": False,
                          "carve": False})
    try:
        while True:
            next(gen)
    except StopIteration as stop:
        rep = stop.value
    assert seen == ["mirrored-body", "piece"], seen          # no unmirrored whole-body re-run
    assert o.get("forge_symmetry_x")
    assert rep["parts"]["Body"]["method"] == "quadremesher(rescued)"
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


def test_planned_flow_split_tail_symmetric_body_attached(monkeypatch):
    """The principled flow: the thin one-sided tail is split off BEFORE remeshing, the body is
    made symmetric from the chosen side and remeshed mirrored, the tail is remeshed on its own
    and attached (no boolean). No rescue, no unmirrored re-roll."""
    import numpy as np

    from forge_bpy import common, density, retopo
    o = _body_with_tail()
    me = o.data
    co = np.array([v.co[:] for v in me.vertices])
    for v in me.vertices:                         # make the right side (-X) a little bumpy
        if v.co.x < -0.6 and abs(v.co.z) < 0.3:
            v.co *= 1.03
    density.write_split(me, (co[:, 0] > 1.02).astype(np.int32))      # the tail = part 1
    calls = []

    def qr(obj, quads, args, timeout):
        yield 0.0
        whole = any(v.co.x < 0.5 for v in obj.data.vertices)
        calls.append(("body" if whole else "piece", bool(obj.get("forge_symmetry_x"))))
        return retopo._quadriflow(obj, max(int(quads * 2), 600), {})

    monkeypatch.setattr(retopo, "_qr_part", qr)
    gen = retopo._run_qr({"target_tris": common.tri_count(o), "qr_timeout": 5,
                          "symmetry": "left", "carve": False})
    try:
        while True:
            next(gen)
    except StopIteration as stop:
        rep = stop.value
    r = rep["parts"]["Body"]
    assert calls[0] == ("body", True) and ("piece", False) in calls, calls
    assert "part(s) separate" in r["method"] and r["shape"]["rescued"] == 0, r
    v = np.array([x.co[:] for x in o.data.vertices])
    assert v[:, 0].max() > 1.9                                  # the tail is there
    # the body was built from the LEFT side: no bump on the right any more
    body = v[v[:, 0] < 0.98]
    assert abs(body[:, 0].min() + 1.0) < 0.02, body[:, 0].min()
    assert not [x for x in bpy.data.objects if x.get("forge_rescue")]


def test_side_choice_never_mirrors_a_prop_beside_the_body(monkeypatch):
    """Symmetry 'left' is for parts across the body's middle. A hair tuft laid out beside the
    body must come back as ONE tuft, not a second copy on the other side."""
    import bmesh
    import numpy as np

    from forge_bpy import common, density, retopo
    bpy.ops.wm.read_homefile(use_empty=True)
    bm = bmesh.new()
    from mathutils import Matrix
    bmesh.ops.create_icosphere(bm, subdivisions=4, radius=0.15, matrix=Matrix.Translation((1.5, 0, 1.0)))
    me = bpy.data.meshes.new("Hair")
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new("Hair_low", me)
    bpy.context.scene.collection.objects.link(o)
    o["forge_role"], o["forge_part"] = "low", "Hair"
    assert not density.straddles_middle(me)
    seen = []

    def qr(obj, quads, args, timeout):
        yield 0.0
        seen.append(bool(obj.get("forge_symmetry_x")))
        return True

    monkeypatch.setattr(retopo, "_qr_part", qr)
    gen = retopo._run_qr({"target_tris": 600, "qr_timeout": 5, "symmetry": "left", "carve": False,
                          "conform": False, "shape_check": False})
    try:
        while True:
            next(gen)
    except StopIteration:
        pass
    v = np.array([x.co[:] for x in o.data.vertices])
    assert v[:, 0].min() > 1.2, v[:, 0].min()          # still one tuft, at +X only
    assert seen and not any(seen)                       # and the remesher never mirrored it


def test_stop_frees_every_copy_of_the_part(monkeypatch):
    """Stop closes the job half-way: no part-sized mesh copy may stay behind in memory."""
    from forge_bpy import common, retopo
    o = _body_with_tail()
    meshes0 = {m.name for m in bpy.data.meshes}

    def qr(obj, quads, args, timeout):
        yield 0.5
        return True

    monkeypatch.setattr(retopo, "_qr_part", qr)
    gen = retopo._run_qr({"target_tris": common.tri_count(o), "qr_timeout": 5, "symmetry": "left"})
    for _ in range(3):
        next(gen)
    gen.close()
    left = [m.name for m in bpy.data.meshes if m.users == 0 and m.name not in meshes0]
    assert not left, left


def test_a_part_that_cannot_be_cut_is_never_mirrored(monkeypatch):
    """If the cut of a one-sided part is refused, mirroring would copy or delete it: the body
    is not mirrored, and the report says so."""
    import numpy as np

    from forge_bpy import common, density, rescue, retopo
    o = _body_with_tail()
    co = np.array([v.co[:] for v in o.data.vertices])
    density.write_split(o.data, (co[:, 0] > 1.02).astype(np.int32))

    def refuse(me, ids, report=None):
        if report is not None:
            report.append((1, "cutting it would leave an opening in the body: kept with the body"))
        return []

    def qr(obj, quads, args, timeout):
        yield 0.0
        return retopo._quadriflow(obj, max(int(quads * 2), 600), {})

    monkeypatch.setattr(rescue, "split_off", refuse)
    monkeypatch.setattr(retopo, "_qr_part", qr)
    gen = retopo._run_qr({"target_tris": common.tri_count(o), "qr_timeout": 5, "symmetry": "left",
                          "carve": False, "shape_check": False})
    try:
        while True:
            next(gen)
    except StopIteration as stop:
        rep = stop.value
    r = rep["parts"]["Body"]
    assert not o.get("forge_symmetry_x")
    assert any("not mirrored" in w for w in r.get("split_kept", [])), r
    v = np.array([x.co[:] for x in o.data.vertices])
    assert v[:, 0].max() > 1.8 and v[:, 0].min() > -1.1                     # one tail, not two


def test_cleanup_retires_jobs_and_late_results_are_removed_when_idle():
    from forge_bpy import retopo
    bpy.ops.wm.read_homefile(use_empty=True)
    retopo._QR_JOBS.clear()
    retopo._QR_JOBS["fq001_00001z"] = {"state": "abandoned", "t": __import__("time").time(), "limit": 900}
    late = bpy.data.objects.new("Retopo_fq001_00001z", bpy.data.meshes.new("late"))
    bpy.context.scene.collection.objects.link(late)
    assert retopo._poll_late() is None              # removed it, nothing left to watch
    assert "Retopo_fq001_00001z" not in bpy.data.objects and not retopo._QR_JOBS
    retopo._QR_JOBS["fq001_00002z"] = {"state": "abandoned", "t": __import__("time").time(), "limit": 900}
    stray = bpy.data.objects.new("Retopo_fq001_00002z.001", bpy.data.meshes.new("stray"))
    bpy.context.scene.collection.objects.link(stray)
    retopo.cleanup_jobs()
    assert not retopo._QR_JOBS and "Retopo_fq001_00002z.001" not in bpy.data.objects


def test_props_keep_fine_detail_for_the_bake_never_glued_pieces(monkeypatch):
    """A curly hair tuft or a twisted rope loses fine detail at a few thousand triangles: the
    bake keeps it. No rebuilt pieces are glued on (they left lumps and openings)."""
    from forge_bpy import common, retopo
    o = _body_with_tail()
    o["forge_kind"] = "prop"
    calls = []

    def collapsing_qr(obj, quads, args, timeout):
        yield 0.0
        calls.append(len(obj.data.vertices))
        for v in obj.data.vertices:                 # the thin part collapses every time
            if v.co.x > 1.0:
                v.co.x = 1.0 + 0.1 * (v.co.x - 1.0)
        return True

    monkeypatch.setattr(retopo, "_qr_part", collapsing_qr)
    gen = retopo._run_qr({"target_tris": common.tri_count(o), "qr_timeout": 5, "carve": False})
    try:
        while True:
            next(gen)
    except StopIteration as stop:
        rep = stop.value
    sh = rep["parts"]["Body"]["shape"]
    assert sh["rescued"] == 0
    assert len(calls) <= 3                          # no extra rebuild jobs
    assert rep["parts"]["Body"]["open_edges"] == 0


def test_a_part_the_plan_could_not_cut_blocks_the_mirror(monkeypatch):
    """The plan found a one-sided part it cannot cut cleanly (a tail resting against a leg):
    mirroring would copy or delete it, so the body is not mirrored and the panel says why."""
    import numpy as np

    from forge_bpy import common, retopo
    o = _body_with_tail()
    o.data["forge_mirror_blocked"] = "tail"

    def qr(obj, quads, args, timeout):
        yield 0.0
        return retopo._quadriflow(obj, max(int(quads * 2), 600), {})

    monkeypatch.setattr(retopo, "_qr_part", qr)
    gen = retopo._run_qr({"target_tris": common.tri_count(o), "qr_timeout": 5, "symmetry": "left",
                          "carve": False, "shape_check": False})
    try:
        while True:
            next(gen)
    except StopIteration as stop:
        rep = stop.value
    r = rep["parts"]["Body"]
    assert not o.get("forge_symmetry_x")
    assert any("not mirrored: tail" in w for w in r.get("split_kept", [])), r
    v = np.array([x.co[:] for x in o.data.vertices])
    assert v[:, 0].max() > 1.8 and v[:, 0].min() > -1.1


def test_cut_off_part_gets_the_body_quad_size(monkeypatch):
    """A part remeshed on its own (the tail) gets the quad size the body has where it sits,
    not a multiple of the average: no dense tail on a coarse body."""
    import numpy as np

    from forge_bpy import common, density, retopo
    o = _body_with_tail()
    co = np.array([v.co[:] for v in o.data.vertices])
    density.write_split(o.data, (co[:, 0] > 1.02).astype(np.int32))
    asked = {}

    def qr(obj, quads, args, timeout):
        yield 0.0
        whole = any(v.co.x < 0.5 for v in obj.data.vertices)
        asked.setdefault("body" if whole else "piece", []).append(quads)
        return retopo._quadriflow(obj, max(int(quads * 2), 200), {})

    monkeypatch.setattr(retopo, "_qr_part", qr)
    gen = retopo._run_qr({"target_tris": 6000, "qr_timeout": 5, "symmetry": "none", "carve": False,
                          "conform": False, "shape_check": False})
    try:
        while True:
            next(gen)
    except StopIteration:
        pass
    v = np.array([x.co[:] for x in o.data.vertices])
    ev = np.array([e.vertices[:] for e in o.data.edges])
    mid = (v[ev[:, 0]] + v[ev[:, 1]]) / 2
    length = np.linalg.norm(v[ev[:, 0]] - v[ev[:, 1]], axis=1)
    near_root = (mid[:, 0] > 0.8) & (mid[:, 0] < 0.97)
    tail = mid[:, 0] > 1.2
    body_e, tail_e = np.median(length[near_root]), np.median(length[tail])
    # a 0.04-wide tail keeps 8 edges around (2*pi*0.04/8 = 0.031) or the body's quad size
    want = min(body_e, 2 * np.pi * 0.035 / 8)
    assert 0.8 < tail_e / want < 1.25, (tail_e, body_e, asked)
    assert asked["piece"][0] < 0.1 * asked["body"][0], asked


def test_thick_cut_off_part_matches_the_body_not_a_multiple(monkeypatch):
    """A thick part (round edge no limit): its quads are the body's size where it attaches."""
    import numpy as np

    from forge_bpy import common, density, retopo
    o = _body_with_tail(0.16, 0.12)
    co = np.array([v.co[:] for v in o.data.vertices])
    density.write_split(o.data, (co[:, 0] > 1.02).astype(np.int32))
    seen = {}

    def qr(obj, quads, args, timeout):
        yield 0.0
        if obj is not o:
            v = np.array([x.co[:] for x in o.data.vertices])        # the body as it is now
            ev = np.array([e.vertices[:] for e in o.data.edges])
            mid = (v[ev[:, 0]] + v[ev[:, 1]]) / 2
            near = mid[:, 0] > 0.8
            body_e = float(np.median(np.linalg.norm(v[ev[near, 0]] - v[ev[near, 1]], axis=1)))
            from forge_bpy.rescue import area
            seen["want"] = area(obj.data) / min(body_e, 2 * np.pi * 0.16 / 8) ** 2
            seen["got"] = quads
        return retopo._quadriflow(obj, max(int(quads * 2), 200), {})

    monkeypatch.setattr(retopo, "_qr_part", qr)
    gen = retopo._run_qr({"target_tris": 6000, "qr_timeout": 5, "symmetry": "none", "carve": False,
                          "conform": False, "shape_check": False})
    try:
        while True:
            next(gen)
    except StopIteration:
        pass
    assert 0.75 < seen["got"] / seen["want"] < 1.3, seen


def _stand_in_qr(calls=None):
    """Quad Remesher stand-in: Blender's QuadriFlow (it refuses near-duplicate points)."""
    import bmesh

    from forge_bpy import retopo

    def qr(obj, quads, args, timeout):
        yield 0.0
        if calls is not None:
            calls.append((obj.name, int(quads)))
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=2.5e-4)
        bmesh.ops.dissolve_degenerate(bm, dist=2.5e-4, edges=bm.edges)
        bm.to_mesh(obj.data)
        bm.free()
        obj.data.update()
        return retopo._quadriflow(obj, max(int(quads * 2), 200), {"symmetry_x": False})
    return qr


def _run(args):
    from forge_bpy import retopo
    gen = retopo._run_qr(args)
    try:
        while True:
            next(gen)
    except StopIteration as stop:
        return stop.value


def _inside(tree, p, eps=1e-7):
    from mathutils import Vector
    votes = 0
    for d in ((0.37, 0.53, 0.76), (-0.61, 0.29, -0.73), (0.12, -0.95, 0.28)):
        d = Vector(d).normalized()
        o, n = Vector(p), 0
        for k in range(2000):
            hit = tree.ray_cast(o, d)
            if hit[0] is None:
                break
            n += k == 0 or hit[3] > 2 * eps            # (a re-hit where the last one was: one crossing)
            o = hit[0] + d * eps
        votes += n % 2
    return votes >= 2


def _root_faces(fin, orig, root, rad):
    """What shows at a part's root on the final mesh: the faces within 2.5 radii of the root
    that are not buried inside another shell -> (count, wrong-facing against the original,
    p95 distance to the original in radii, shells among them, crossing faces in one shell)."""
    import numpy as np
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree

    from forge_bpy.appendages import _components
    from forge_bpy.rescue import _submesh

    def tree(m):
        return BVHTree.FromPolygons([v.co.copy() for v in m.vertices], [tuple(p.vertices) for p in m.polygons])
    ev = np.array([e.vertices[:] for e in fin.edges], np.int64)
    lab = _components(len(fin.vertices), ev[:, 0], ev[:, 1])
    flab = np.array([lab[p.vertices[0]] for p in fin.polygons])
    cen = np.array([p.center[:] for p in fin.polygons])
    near = np.flatnonzero(np.linalg.norm(cen - np.array(root[:]), axis=1) < 2.5 * rad)
    shells = sorted(set(flab[near].tolist()))
    others = {s: tree(_submesh(fin, lab == s)) for s in shells} if len(shells) > 1 else {}
    vis = [i for i in near if not any(s != flab[i] and _inside(t, cen[i]) for s, t in others.items())]
    t_orig = tree(orig)
    wrong, dist = 0, []
    for i in vis:
        hit = t_orig.find_nearest(Vector(cen[i]))
        dist.append(hit[3] / rad)
        wrong += fin.polygons[i].normal.dot(hit[1]) < 0
    t_fin = tree(fin)
    polys = [set(p.vertices) for p in fin.polygons]
    nset = set(near.tolist())
    cross = {i for i, j in t_fin.overlap(t_fin) if i != j and flab[i] == flab[j] and not polys[i] & polys[j]
             and (i in nset or j in nset)}
    return len(vis), wrong, float(np.percentile(dist, 95)) if dist else 0.0, len(shells), len(cross)


@pytest.mark.parametrize("case,budget,defaults,fit", [("curl", 30000, False, 0.1), ("curl", 30000, True, 0.1),
                                                     ("bull", 12000, True, 0.15)])
def test_tail_root_is_one_skin_or_a_clean_attach(monkeypatch, case, budget, defaults, fit):
    """The director's bull: the curled tail's hidden plug showed outside the body as a
    crumpled, red collar. Now the tail is welded into the body as one skin, or - when the
    joint would not be clean - attached with its plug hidden. Either way the root is clean:
    closed, faces the right way, on the original surface, never decimated after joining.
    Run with fitting/carving and the shape check off, and with the defaults; and on the bull
    at a coarse budget, where a joint of a few big faces would cut across the sharp fold at
    the tail's root (measured before: 0.15-0.34 radius off; the tail itself is only about 12
    quads round there and stands up to 0.2 radius off on its own, hence the wider limit)."""
    from mathutils import Vector

    import bodies
    from forge_bpy import density, parts, rescue, retopo
    ob = bodies.curled_tail(1.0, r=0.035)[0] if case == "curl" else bodies.bull(tail_r=0.035)
    ob.name = "Body_low"
    ob["forge_role"], ob["forge_part"] = "low", "Body"
    me = ob.data
    density.write_split(me, parts.one_sided_parts(me))
    me["forge_onesided_planned"] = True
    orig = me.copy()
    shift = density.mirror_plane(orig)                     # (the run works in the mirror frame)
    plugs = []
    real_extract = rescue.extract

    def extract(*a, **k):
        out = real_extract(*a, **k)
        if "forge_plug" in out and out.name.startswith("forge_part"):
            plugs.append(list(out["forge_plug"]))
        return out
    monkeypatch.setattr(rescue, "extract", extract)
    monkeypatch.setattr(retopo, "_qr_part", _stand_in_qr())
    args = {"target_tris": budget, "qr_timeout": 5, "symmetry": "left"}
    if not defaults:
        args.update(carve=False, shape_check=False)
    r = _run(args)["parts"]["Body"]
    fin = ob.data
    assert rescue.mesh_defects(fin) == (0, 0, 0), r
    joint = r.get("joint", "")
    assert joint == "welded" or (joint.startswith("attached:") and "error" not in joint), r
    assert not r["method"].endswith("+decimate"), r            # never decimated after the joint
    root = Vector(plugs[-1][0:3]) + Vector((shift, 0.0, 0.0))
    rad = float(plugs[-1][6])
    n, wrong, p95, shells, cross = _root_faces(fin, orig, root, rad)
    assert n > 50 and wrong <= 2 and p95 < fit, (joint, n, wrong, p95)
    if joint == "welded":
        assert shells == 1 and cross <= 2, (shells, cross)          # one skin, nothing crossing


def test_weld_rolls_back_and_attaches_when_the_bridge_fails(monkeypatch):
    """The weld works on copies: when a step fails, the body is exactly as it was, the part
    is attached as its own shell, and the reason is reported."""
    import bmesh
    import numpy as np

    import bodies
    from forge_bpy import parts, rescue
    ob, _P = bodies.curled_tail(1.0, r=0.035)
    full = ob.data.copy()
    cap = ob.data.copy()
    (_k, src, _plug), = rescue.split_off(cap, parts.one_sided_parts(cap))
    target = bpy.data.objects.new("Body_low", cap.copy())
    piece = bpy.data.objects.new("Body_low_part1", src.copy())
    for o in (target, piece):
        bpy.context.scene.collection.objects.link(o)
    body0 = bodies.coords(target.data)

    def broken(*a, **k):
        raise RuntimeError("no loops")
    monkeypatch.setattr(bmesh.ops, "bridge_loops", broken)
    info: dict = {}
    assert rescue.weld(target, piece, src, cap, full, info) == "attached: bridge"
    assert info["joint"] == "attached: bridge" and min(info["loops"]) >= 3, info
    after = bodies.coords(target.data)
    assert len(after) == len(body0) + len(piece.data.vertices)          # body + the part's shell
    assert np.array_equal(after[:len(body0)], body0)                     # the body untouched
    assert rescue.mesh_defects(target.data) == (0, 0, 0)


def test_parts_reserve_is_not_spent_by_the_body_rerun(monkeypatch):
    """The body's triangle re-run aims at the body's OWN share (the budget minus what the
    cut-off parts reserved), and nothing is decimated once a part is joined to the body: a
    collapse there crumpled the tail root. A body the remesher overshoots is reduced alone,
    before the joint; what is still over is reported."""
    import numpy as np

    from forge_bpy import density, rescue, retopo
    real_dec, real_weld = retopo._decimate, rescue.weld
    for factor in (0.5, 1.6):                    # the remesher gives half / 1.6x the count asked
        o = _body_with_tail()
        co = np.array([v.co[:] for v in o.data.vertices])
        density.write_split(o.data, (co[:, 0] > 1.02).astype(np.int32))
        asked, decimated, joined = [], [], []

        def qr(obj, quads, args, timeout):
            yield 0.0
            whole = any(v.co.x < 0.5 for v in obj.data.vertices)
            if whole:
                asked.append(quads)
            return retopo._quadriflow(obj, max(int(quads * 2 * factor), 200), {})

        def dec(obj, target_tris):
            decimated.append(bool(joined))
            return real_dec(obj, target_tris)

        def weld(*a, **k):
            joined.append(1)
            return real_weld(*a, **k)
        monkeypatch.setattr(retopo, "_qr_part", qr)
        monkeypatch.setattr(retopo, "_decimate", dec)
        monkeypatch.setattr(rescue, "weld", weld)
        r = _run({"target_tris": 6000, "qr_timeout": 5, "symmetry": "none", "carve": False,
                  "conform": False, "shape_check": False})["parts"]["Body"]
        assert joined and not any(decimated), (factor, decimated)     # never after the joint
        share = 2 * asked[0] / 0.94                                   # the body's own triangles
        assert len(asked) == 2, asked                                  # one corrected re-run
        assert asked[1] * 2 * factor <= 1.1 * share, (factor, asked, share)
        assert r["tris_after"] <= 1.05 * 6000 or r.get("over_budget"), r


def test_a_mesh_with_joined_parts_is_never_decimated_its_overrun_is_reported():
    from forge_bpy import common, retopo
    o = _body_with_tail()
    tris = common.tri_count(o)
    report: dict = {}
    retopo._finish_part(o, tris // 2, "quadremesher", tris, report, True, joined=True)
    r = report["Body"]
    assert common.tri_count(o) == tris and "+decimate" not in r["method"]
    assert r["over_budget"] == tris - tris // 2
    retopo._finish_part(o, tris // 2, "quadremesher", tris, report, True)        # (no parts: reduced)
    assert common.tri_count(o) <= 1.05 * (tris // 2) and "+decimate" in report["Body"]["method"]


def test_weld_opening_is_one_loop_islands_and_old_holes_go_with_it():
    """The cut the weld makes must leave ONE simple opening on each side: kept faces it
    encloses go with it, an old hole it runs into is taken in, and a cut that would take
    off a big piece far from the joint is refused."""
    import math

    import bmesh
    from mathutils import Vector

    from forge_bpy import rescue
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=32, v_segments=24, radius=1.0)
    pole = Vector((0, 0, 1))

    def ang(f):
        return math.degrees(f.calc_center_median().normalized().angle(pole))
    ring = {f for f in bm.faces if 12 < ang(f) < 30}            # an annulus: encloses an island
    hole = min((f for f in bm.faces if 31 < ang(f) < 40), key=lambda f: f.calc_center_median().x)
    bmesh.ops.delete(bm, geom=[hole], context="FACES_ONLY")       # an old hole next to the cut
    island = {f for f in bm.faces if ang(f) <= 12}
    opening, why = rescue._open_cut(bm, ring, pole, 1.5)
    assert why is None and rescue._one_loop(opening), why
    assert not any(f.is_valid for f in island)                    # the island went with the cut
    assert not [e for e in bm.edges if e.is_boundary and e not in set(opening)]   # hole taken in
    bm.free()
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=32, v_segments=24, radius=1.0)
    band = {f for f in bm.faces if abs(f.calc_center_median().z) < 0.1}   # a belt round the middle
    assert rescue._open_cut(bm, band, Vector((1, 0, 0)), 0.5)[1] == "island"   # half a sphere: no
    bm.free()


def test_the_joint_ring_sits_on_the_fold_between_body_and_part():
    """A joint of a few big faces across the sharp fold where a tail meets the body cut the
    fold as chords (on the coarse bull: face centres 0.3 radius off). The ring across the
    middle of the joint is seated ON the fold - the point of the original deepest under the
    straight line between the body side and the part side - and stays put where the
    original is flat."""
    import bmesh
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree

    from forge_bpy import rescue
    # the original near the root: the body (y = 0) meets the part (x = 0) along the z axis
    pts = [(0, 0, -1), (2, 0, -1), (2, 0, 1), (0, 0, 1), (0, 2, -1), (0, 2, 1)]
    t_full = BVHTree.FromPolygons([Vector(p) for p in pts], [(0, 1, 2, 3), (0, 3, 5, 4)])
    bm = bmesh.new()
    a, m, b = (bm.verts.new(p) for p in ((1.0, 0.0, 0.2), (0.5, 0.5, 0.2), (0.0, 1.0, 0.2)))
    bm.edges.new((a, m))
    bm.edges.new((m, b))
    assert rescue._seat_on_fold([m], {a}, {b}, t_full) == 1
    assert (m.co - Vector((0, 0, 0.2))).length < 0.06, m.co          # on the fold
    flat = BVHTree.FromPolygons([Vector(p) for p in pts[:4]], [(0, 1, 2, 3)])
    m.co = Vector((0.5, 0.0, 0.2))
    a.co, b.co = Vector((1.0, 0.0, 0.2)), Vector((0.0, 0.0, 0.2))
    assert rescue._seat_on_fold([m], {a}, {b}, flat) == 0                # no fold: left alone
    bm.free()


def test_two_cut_off_parts_are_each_joined_and_named(monkeypatch):
    """Two parts cut off one body (a tail and a trunk): each is remeshed and joined back on
    its own, and the report names each one as the parts plan does."""
    import bmesh
    import numpy as np
    from mathutils import Matrix

    from forge_bpy import density, retopo
    bpy.ops.wm.read_homefile(use_empty=True)
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=6, radius=1.0)
    for rot, axis in ((1.5708, "Y"), (-1.5708, "X")):            # one along +X, one along +Y
        res = bmesh.ops.create_cone(bm, cap_ends=True, segments=10, radius1=0.04, radius2=0.02, depth=1.0,
                                    matrix=Matrix.Rotation(rot, 4, axis) @ Matrix.Translation((0, 0, 1.45)))
        vs = set(res["verts"])
        bmesh.ops.subdivide_edges(bm, edges=[e for e in bm.edges if e.verts[0] in vs and e.verts[1] in vs],
                                  cuts=10, use_grid_fill=True)
    me = bpy.data.meshes.new("Body")
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new("Body_low", me)
    bpy.context.scene.collection.objects.link(o)
    o["forge_role"], o["forge_part"] = "low", "Body"
    co = np.array([v.co[:] for v in me.vertices])
    density.write_split(me, np.where(co[:, 0] > 1.02, 1, np.where(co[:, 1] > 1.02, 2, 0)).astype(np.int32))
    me["forge_split_names"] = {"1": "tail", "2": "trunk"}
    monkeypatch.setattr(retopo, "_qr_part", _stand_in_qr())
    r = _run({"target_tris": 8000, "qr_timeout": 5, "symmetry": "none", "carve": False,
              "shape_check": False})["parts"]["Body"]
    assert r["separate_parts"] == 2, r
    assert [j["name"] for j in r["joints"]] == ["tail", "trunk"], r["joints"]
    assert all(j["joint"] == "welded" or j["joint"].startswith("attached:") for j in r["joints"]), r["joints"]
    from forge_bpy import rescue
    assert rescue.mesh_defects(o.data) == (0, 0, 0)
