"""Step 4's fit to the original makes no dent the original does not have.

A mouth line narrower than the new mesh's quads, fading to nothing at its ends where it runs
into the concave join of lip and muzzle (tests/bodies.mouth_head: the cartoon bull with a lower
lip), remeshed at a game face's quad size by a stand-in that does not see the line, then fitted
by the product's own Step 4 (retopo._run_qr: conform, carve, the dent gate). Measured from the
original: the fit may leave no point of the smooth surface beside the line farther outside the
new mesh (the new mesh sunk below it) than the remesher's own mesh did, by more than the crease
tolerance carve works to. With the face marked as Step 4's plan marks it, the fit's own
projection pulled quad corners into the line and sank their faces into the lips beside it.
With the whole mouth in the face, carve still cuts the line, as a V that digs no deeper than
about the tolerance beside it. The same at 1/100 and 100 times the size, and the same mesh on
every run.
"""

import sys
from pathlib import Path

import pytest

bpy = pytest.importorskip("bpy")
HERE = Path(__file__).resolve().parent
for _p in (HERE, HERE.parent / "blender_scripts", HERE.parent / "blender_addon"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

QR_EDGE = 0.0095        # the face's quad edge for 30k triangles with the head ~35% of them (at x1)
TOL_REL = 0.0012        # carve's crease tolerance (share of the size)
_STAND_IN: dict = {}


def _stand_in(smooth):
    """Quad Remesher stand-in: Blender's QuadriFlow at the face's quad size on the bull without
    the mouth line (at this quad size a remesher does not follow a line a few mm wide). Made
    once at x1 and scaled with the model, as a remesher's result scales with it (QuadriFlow
    itself fails at x0.01). Returns (points, faces) at x1."""
    import bmesh

    from forge_bpy import retopo
    if "co" not in _STAND_IN:
        import bodies
        ob = bpy.data.objects.new("qr_in", smooth.copy())
        bpy.context.scene.collection.objects.link(ob)
        retopo._decimate(ob, 200_000)
        bm = bmesh.new()
        bm.from_mesh(ob.data)
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=2.5e-4)
        bm.to_mesh(ob.data)
        bm.free()
        area = sum(p.area for p in ob.data.polygons)
        assert retopo._quadriflow(ob, int(2 * area / QR_EDGE ** 2), {"symmetry_x": False, "preserve_hard_edges": False})
        _STAND_IN["co"] = bodies.coords(ob.data)
        _STAND_IN["faces"] = [tuple(p.vertices) for p in ob.data.polygons]
        bpy.data.objects.remove(ob)
    return _STAND_IN["co"], _STAND_IN["faces"]


def _fitted(scale: float, whole_face: bool = False) -> dict:
    """The bull through Step 4 with the stand-in as Quad Remesher, its face marked as Step 4's
    plan marks it (the head region, ears and horns left out; whole_face: the whole head, mouth
    and lip included - on this neckless head the region's neck runs through the mouth, so the
    plan's face leaves the mouth line out and carve never sees it). Returns the original (points,
    faces, groove depth per point), the stand-in, the new mesh (points, faces, exact hash) and
    Step 4's report for the part - as arrays: the next build clears the scene."""
    import bodies
    import numpy as np
    from mathutils import Matrix

    from forge_bpy import common, density, joints, retopo
    ob, smooth, off = bodies.mouth_head()
    qco, qfaces = _stand_in(smooth)
    qr = bpy.data.meshes.new("qr")
    qr.from_pydata((qco * scale).tolist(), [], qfaces)
    qr.update()
    ob.data.transform(Matrix.Scale(scale, 4))
    ob.data.update()
    co = bodies.coords(ob.data)
    head = density.region_labels(co, joints.estimate_points(co)) == 1
    if whole_face:
        head |= (co[:, 2] > 0.58 * scale) & (np.abs(co[:, 0]) < 0.17 * scale)
    face = head & (np.abs(co[:, 0]) < 0.17 * scale) & (co[:, 2] < 0.82 * scale)
    density.write_strict(ob.data, np.where(face, 0.35, 1.0))
    src_faces = [tuple(p.vertices) for p in ob.data.polygons]
    ob["forge_role"], ob["forge_part"] = "low", "Body"

    def fake(obj, quads, args, timeout):
        yield 0.0
        retopo._replace_mesh(obj, qr.copy())
        return True
    retopo._qr_part, keep = fake, retopo._qr_part
    try:
        tris = sum(len(p.vertices) - 2 for p in qr.polygons)
        gen = retopo._run_qr({"target_tris": int(tris / 0.94), "qr_timeout": 5, "shape_check": False})
        try:
            while True:
                next(gen)
        except StopIteration as stop:
            rep = stop.value
    finally:
        retopo._qr_part = keep
    assert common.tri_count(ob) > 0.9 * tris
    return {"co": co, "faces": src_faces, "off": off * scale, "qr": qco * scale, "qr_faces": qfaces,
            "low": bodies.coords(ob.data), "low_faces": [tuple(p.vertices) for p in ob.data.polygons],
            "hash": density.exact_hash(ob.data), "rep": rep["parts"]["Body"],
            "size": float(np.linalg.norm(co.max(axis=0) - co.min(axis=0)))}


def _tree(co, faces):
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    return BVHTree.FromPolygons([Vector(c) for c in co], faces)


def _sunk(co, sel, low, low_faces):
    """Per selected original point: how far it lies outside the mesh (the mesh sunk below it)."""
    import numpy as np
    from mathutils import Vector
    tree = _tree(low, low_faces)
    out = np.zeros(len(sel))
    for j, i in enumerate(sel):
        p, n, _i, d = tree.find_nearest(Vector(co[i]))
        if (Vector(co[i]) - p).dot(n) > 0:
            out[j] = d
    return out


def _dug_beside(r, scale):
    """How much deeper than the remesher's own mesh the fit left the new mesh below the original
    beside the mouth line (original points with no groove under them, round the mouth): the
    deepest dent the fit made, not the chord the remesher already cut."""
    import bodies
    import numpy as np
    co = r["co"]
    sel = np.nonzero((r["off"] <= 0) & (np.linalg.norm(co - np.array(bodies.MUZZLE) * scale, axis=1) < 0.12 * scale))[0]
    after = _sunk(co, sel, r["low"], r["low_faces"])
    before = _sunk(co, sel, r["qr"], r["qr_faces"])
    return float((after - before).max())


@pytest.fixture(scope="module")
def runs():
    """The fitted head at x1, x0.01 and x100 (each built once for the tests below)."""
    return {scale: _fitted(scale) for scale in (1.0, 0.01, 100.0)}


@pytest.mark.parametrize("scale", [1.0, 0.01, 100.0])
def test_no_dent_beside_the_fading_mouth_line(runs, scale):
    r = runs[scale]
    dug = _dug_beside(r, scale)
    assert dug <= TOL_REL * r["size"], (scale, dug / (TOL_REL * r["size"]))


def test_the_mouth_line_is_still_cut():
    """With the whole mouth in the face, carve still cuts the line: the face is still kept on
    both sides, and the new mesh reaches down past the crease tolerance on most of the line's
    deep part - while the V it cuts digs no deeper than about that tolerance beside the line."""
    import numpy as np
    from mathutils import Vector
    r = _fitted(1.0, whole_face=True)
    cr = r["rep"]["creases"]
    assert cr["left_pct"] >= 98 and cr["right_pct"] >= 98 and cr["carved_tris"] > 0, cr
    tol = TOL_REL * r["size"]
    tree = _tree(r["low"], r["low_faces"])
    deep = np.nonzero(r["off"] > 1.5 * tol)[0]
    reached = np.array([r["off"][i] - tree.find_nearest(Vector(r["co"][i]))[3] for i in deep])
    assert np.mean(reached > tol) > 0.7, np.mean(reached > tol)
    assert _dug_beside(r, 1.0) <= 1.25 * tol


def test_same_mesh_every_run(runs):
    """Step 4 with the fit gives the same mesh again, to the last bit."""
    assert _fitted(1.0)["hash"] == runs[1.0]["hash"]


def test_dent_rows_say_what_was_found_fixed_and_left():
    """Plain words in the Step 4 rows, the panel's region words for where, every row fits."""
    import importlib
    L = importlib.import_module("forge_send.stages_late")
    base = {"method": "quadremesher", "tris_before": 90000, "tris_after": 30000,
            "creases": {"left_pct": 100.0, "right_pct": 100.0, "carved_tris": 120}}

    def said(r):
        rows = L._retopo_rows({"parts": {"Body": r}})
        assert max(len(t) for _i, t in rows) <= L.PANEL_WIDTH, max(rows, key=lambda x: len(x[1]))
        return rows, " ".join(" ".join(t.split()) for _i, t in rows)
    _rows, text = said({**base, "dents": {"found": 2, "fixed": 2, "left": 0, "where": ["head"]}})
    assert "smoothed 2 small dents Forge had made on the head" in text and "none left" in text, text
    rows, text = said({**base, "dents": {"found": 3, "fixed": 2, "left": 1, "where": ["head", "arms"],
                                         "left_where": ["head"], "kinds": ["dent", "dent", "bump"]}})
    assert "dents and bumps Forge made on the head and arms: found 3, smoothed 2, 1 left" in text, text
    assert "look at the head" in text and "paint the spot red" in text, text
    assert any(i == L.WARN for i, _t in rows)
    _rows, text = said(base)
    assert "dent" not in text, text
