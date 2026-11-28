"""Step 4's fit to the original makes no dent the original does not have, and keeps what it has.

The fit (density.conform) puts every point of the new mesh on the original; a point whose move
bends its faces goes only as far as brings them closer to the original. A point pulled into a
groove narrower than its faces would drag them into the skin on both sides of it: the notch the
director saw at the bull's mouth corner, where the original is smooth.

- The cartoon bull's head with a lower lip (tests/bodies.mouth_head): a mouth line narrower than
  the new mesh's quads, fading to nothing where it runs into the concave join of lip and muzzle,
  in three cross-sections (a V, a U, the upper lip's side almost an overhang) and set higher on
  the muzzle. Remeshed at a game face's quad size by a stand-in that does not see the line, then
  fitted by the product's own Step 4 (retopo._run_qr: conform, carve). Measured from the
  original: the fit may leave no point of the smooth skin beside the line farther outside the
  new mesh (sunk below it) than the remesher's own mesh did, by more than the crease tolerance
  (where carve cuts the line, its V may dig about that much beside it). The same at 1/100 and
  100 times the size, and the same mesh on every run. With the whole mouth
  in the face, carve still cuts the line, and Step 4's crease report - measured on the creases'
  floors - says so (the stand-in's own share is far lower); with the fit off (carve alone, as a
  rebuilt mesh gets it) Step 4 still finishes.
- Icospheres, remeshed symmetric (a coarser icosphere) or by QuadriFlow with its points pushed
  off the surface: a one-sided notch two to four quads wide comes back, a ghost bump the mirror
  copied is flattened, and a remesher's noise is put on the surface.
- The same fit, with carve, in a fresh process with another hash seed: the same mesh.
"""

import os
import subprocess
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
MARK = "FITHASH "
_STAND_IN: dict = {}
LINES = {               # mouth lines: bodies.mouth_head's arguments
    "v": {},
    "u": {"profile": "u", "depth": 0.003, "width": 0.005},
    "over": {"profile": "over", "depth": 0.005, "width": 0.004},
    "high": {"elev": (-45.0, -20.0)},
}


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


def _fitted(scale: float, line: str = "v", whole_face: bool = False, **args) -> dict:
    """The bull through Step 4 with the stand-in as Quad Remesher, its face marked as Step 4's
    plan marks it (the head region, ears and horns left out; whole_face: the whole head, mouth
    and lip included - on this neckless head the region's neck runs through the mouth, so the
    plan's face leaves most of the mouth line out and carve never sees it). args: Step 4's own
    (conform=False: carve alone). Returns the original (points, faces, groove depth per point),
    the stand-in and its crease report, the new mesh (points, faces, exact hash) and Step 4's
    report for the part - as arrays: the next build clears the scene."""
    import bodies
    import numpy as np
    from mathutils import Matrix

    from forge_bpy import common, density, joints, retopo
    ob, smooth, off = bodies.mouth_head(**LINES[line])
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
    before = density.crease_kept(ob.data, qr) if whole_face else {}

    def fake(obj, quads, args, timeout):
        yield 0.0
        retopo._replace_mesh(obj, qr.copy())
        return True
    retopo._qr_part, keep = fake, retopo._qr_part
    try:
        tris = sum(len(p.vertices) - 2 for p in qr.polygons)
        gen = retopo._run_qr({"target_tris": int(tris / 0.94), "qr_timeout": 5, "shape_check": False, **args})
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
            "hash": density.exact_hash(ob.data), "rep": rep["parts"]["Body"], "standin_creases": before,
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
    """The fitted head (V line) at x1, x0.01 and x100 (each built once for the tests below)."""
    return {scale: _fitted(scale) for scale in (1.0, 0.01, 100.0)}


@pytest.mark.parametrize("scale", [1.0, 0.01, 100.0])
def test_no_dent_beside_the_fading_mouth_line(runs, scale):
    r = runs[scale]
    dug = _dug_beside(r, scale)
    assert dug <= TOL_REL * r["size"], (scale, dug / (TOL_REL * r["size"]))


@pytest.mark.parametrize("line,carve,limit", [("u", True, 1.0), ("over", True, 1.0), ("high", False, 1.0),
                                              ("high", True, 1.25)])
def test_no_dent_beside_other_mouth_lines(line, carve, limit):
    """A U (flat floor, steep walls), an upper lip almost overhanging the line (steep above, a
    long slope below), and the line set higher on the muzzle: the fit makes no dent beside any
    of them. The higher line runs partly into the plan's face, where carve cuts it: carve's V,
    a crease cut as wide as the quads, digs no deeper than about the tolerance beside it."""
    r = _fitted(1.0, line, carve=carve)
    dug = _dug_beside(r, 1.0)
    assert dug <= limit * TOL_REL * r["size"], (line, carve, dug / (TOL_REL * r["size"]))


def test_the_mouth_line_is_still_cut():
    """With the whole mouth in the face, carve still cuts the line: Step 4's crease report -
    on the creases' floors - says most of it is kept on both sides (far more than the remesher's
    own mesh, which bridges it), the new mesh reaches down past the crease tolerance on most of
    the line's deep part, and the V it cuts digs no deeper than about that tolerance beside it."""
    import numpy as np
    from mathutils import Vector
    r = _fitted(1.0, whole_face=True)
    cr, was = r["rep"]["creases"], r["standin_creases"]
    assert cr["left_pct"] >= 85 and cr["right_pct"] >= 80 and cr["carved_tris"] > 0, cr
    assert cr["left_n"] >= 50 and cr["right_n"] >= 50, cr                   # (the line's floor, measured)
    assert min(cr["left_pct"] - was["left_pct"], cr["right_pct"] - was["right_pct"]) >= 20, (cr, was)
    tol = TOL_REL * r["size"]
    tree = _tree(r["low"], r["low_faces"])
    deep = np.nonzero(r["off"] > 1.5 * tol)[0]
    reached = np.array([r["off"][i] - tree.find_nearest(Vector(r["co"][i]))[3] for i in deep])
    assert np.mean(reached > tol) > 0.7, np.mean(reached > tol)
    assert _dug_beside(r, 1.0) <= 1.25 * tol


def test_carve_alone_on_a_marked_face_finishes():
    """Step 4 with the fit off (carve alone on the remesher's mesh, as a rebuilt mesh gets it)
    on the face-marked head runs to the end and cuts the line."""
    r = _fitted(1.0, whole_face=True, conform=False)
    assert r["rep"]["creases"]["carved_tris"] > 0, r["rep"]


def test_same_mesh_every_run(runs):
    """Step 4 with the fit gives the same mesh again, to the last bit."""
    assert _fitted(1.0)["hash"] == runs[1.0]["hash"]


# ----------------------------------------------------------------------------- icospheres

def _ico(sub: int, scale: float = 1.0, shape=None):
    """An icosphere of radius `scale`, each point moved by shape(x, y, z) -> radius factor."""
    import bmesh
    from mathutils import Matrix
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=sub, radius=1.0)
    if shape is not None:
        for v in bm.verts:
            v.co *= shape(*v.co)
    me = bpy.data.meshes.new("ico")
    bm.to_mesh(me)
    bm.free()
    me.transform(Matrix.Scale(scale, 4))
    me.update()
    return me


def _coords(me):
    import numpy as np
    co = np.empty(len(me.vertices) * 3, np.float32)
    me.vertices.foreach_get("co", co)
    return co.reshape(-1, 3).astype(np.float64)


@pytest.mark.parametrize("scale", [1.0, 100.0])
def test_one_sided_notch_two_to_four_quads_wide_comes_back(scale):
    """A mirrored run copied the smooth side over a notch (box notches 0.24 and 0.14 wide, a
    round dimple 0.4 wide, the new mesh's edge ~0.07): the fit takes the new mesh most of the
    way down each; a wide one comes back over most of its floor."""
    import math

    import numpy as np
    from mathutils import Vector

    from forge_bpy import density
    depth = 0.1
    cases = {"box 0.12": lambda x, y, z: 1 - depth * (x > 0.7 and abs(y) < 0.12 and abs(z) < 0.12),
             "box 0.07": lambda x, y, z: 1 - depth * (x > 0.7 and abs(y) < 0.07 and abs(z) < 0.07),
             "dimple 0.2": lambda x, y, z: 1 - 0.6 * depth * (x > 0.5) * max(0.0, 1 - (math.hypot(y, z) / 0.2) ** 2),
             "box 0.35": lambda x, y, z: 1 - depth * (x > 0.7 and abs(y) < 0.35 and abs(z) < 0.35)}
    for name, shape in cases.items():
        bpy.ops.wm.read_homefile(use_empty=True)
        src, low = _ico(7, scale, shape), _ico(4, scale)
        density.conform(low, src)
        lco = _coords(low)
        reach = float((scale - np.linalg.norm(lco[lco[:, 0] > 0.3 * scale], axis=1)).max())
        want = (0.6 if name.startswith("dimple") else 1.0) * depth * scale
        assert reach >= 0.7 * want, (name, reach / want)
        if name == "box 0.35":                                    # most of a wide notch's floor
            co = _coords(src)
            floor = co[(np.linalg.norm(co, axis=1) < 0.95 * scale)]
            tree = density.source_tree(low)
            tol = TOL_REL * float(np.linalg.norm(co.max(axis=0) - co.min(axis=0)))
            kept = np.mean([tree.find_nearest(Vector(p))[3] <= tol for p in floor])
            assert kept >= 0.6, kept


@pytest.mark.parametrize("scale", [1.0, 100.0])
def test_ghost_bump_of_a_mirrored_run_is_flattened(scale):
    """The original has a dome on -X only; the mirror copied it to +X. The fit flattens the
    ghost onto the smooth original and keeps the real dome."""
    import math

    import numpy as np
    from mathutils import Vector

    from forge_bpy import density

    def dome(both):
        return lambda x, y, z: 1 + 0.05 * max(0.0, 1 - (math.hypot(y, z) / 0.3) ** 2) ** 2 * (x < -0.5 or (both and x > 0.5))
    bpy.ops.wm.read_homefile(use_empty=True)
    src, low = _ico(7, scale, dome(False)), _ico(4, scale, dome(True))
    density.conform(low, src)
    tree = density.source_tree(src)
    co = _coords(src)
    tol = TOL_REL * float(np.linalg.norm(co.max(axis=0) - co.min(axis=0)))
    lco = _coords(low)
    off = np.array([tree.find_nearest(Vector(p))[3] for p in lco])
    assert off[lco[:, 0] > 0.5 * scale].max() <= tol, off[lco[:, 0] > 0.5 * scale].max() / tol
    assert off[lco[:, 0] < -0.5 * scale].max() <= tol


@pytest.mark.parametrize("quads", [150, 750])
def test_remesher_noise_is_put_on_the_surface(quads):
    """QuadriFlow's coarse sphere with its points pushed in and out by 15% of an edge: the fit
    puts every point on the original (on a coarse sphere a raised point does narrow its sagging
    faces' gap - by a bump; that is not closer)."""
    import numpy as np
    from mathutils import Vector

    from forge_bpy import density, retopo
    bpy.ops.wm.read_homefile(use_empty=True)
    src = _ico(6, 0.5)
    ob = bpy.data.objects.new("q", src.copy())
    bpy.context.scene.collection.objects.link(ob)
    assert retopo._quadriflow(ob, 2 * quads, {"symmetry_x": False, "preserve_hard_edges": False})
    low = ob.data
    co = _coords(low)
    ev = np.array([e.vertices[:] for e in low.edges])
    edge = np.linalg.norm(co[ev[:, 0]] - co[ev[:, 1]], axis=1).mean()
    nr = np.array([v.normal[:] for v in low.vertices])
    co = co + nr * (np.random.default_rng(0).uniform(-1, 1, len(co)) * 0.15 * edge)[:, None]
    low.vertices.foreach_set("co", co.astype(np.float32).ravel())
    low.update()
    res = density.conform(low, src)
    tree = density.source_tree(src)
    off = np.array([tree.find_nearest(Vector(p))[3] for p in _coords(low)])
    sco = _coords(src)
    tol = TOL_REL * float(np.linalg.norm(sco.max(axis=0) - sco.min(axis=0)))
    assert off.max() <= tol, (off.max() / tol, res)


# ----------------------------------------------------------------------------- the same in a fresh process

def _fit_hash() -> str:
    """conform and carve on a sphere with a one-sided notch and a smile groove on its marked
    front, remeshed as a coarse quad sphere turned across the groove: the result's exact hash."""
    import math

    import numpy as np
    from mathutils import Matrix

    from forge_bpy import density
    bpy.ops.wm.read_homefile(use_empty=True)

    def shape(x, y, z):
        f = 1.0 - 0.1 * (x > 0.7 and abs(y) < 0.2 and abs(z) < 0.2)
        if 0.15 < abs(x) < 0.6 and y < 0:
            d = abs(z - (-0.25 + 0.6 * (abs(x) - 0.15) ** 2))
            f -= 0.01 * max(0.0, 1 - (d / 0.02) ** 2)
        return f
    src = _ico(6, 1.0, shape)
    co = _coords(src)
    density.write_strict(src, np.where(co[:, 1] < 0, 0.35, 1.0))
    # (a latitude-longitude quad sphere from its own numbers: bmesh's uv sphere is not the same
    # mesh to the last bit from one call to the next)
    rows, cols = 20, 40
    pts = [(0.0, 0.0, 1.0)] + [(math.sin(math.pi * i / rows) * math.cos(2 * math.pi * j / cols),
                                math.sin(math.pi * i / rows) * math.sin(2 * math.pi * j / cols),
                                math.cos(math.pi * i / rows)) for i in range(1, rows) for j in range(cols)] + [(0.0, 0.0, -1.0)]
    ring = [[1 + (i - 1) * cols + j for j in range(cols)] for i in range(1, rows)]
    faces = [(0, ring[0][j], ring[0][(j + 1) % cols]) for j in range(cols)]
    faces += [(ring[i][j], ring[i + 1][j], ring[i + 1][(j + 1) % cols], ring[i][(j + 1) % cols])
              for i in range(rows - 2) for j in range(cols)]
    faces += [(len(pts) - 1, ring[-1][(j + 1) % cols], ring[-1][j]) for j in range(cols)]
    low = bpy.data.meshes.new("low")
    low.from_pydata(pts, [], faces)
    low.transform(Matrix.Rotation(math.radians(25), 4, "Y"))
    low.update()
    tree = density.source_tree(src)
    fit = density.conform(low, src, tree=tree)
    cut = density.carve(low, src, tree)
    assert fit["held_back"] > 0 and cut["added"] > 0, (fit, cut)      # (both at work here)
    return density.exact_hash(low)


def test_fit_is_the_same_in_a_fresh_process():
    """The fit and carve, twice here (other allocations between) and once in a fresh process
    with another hash seed: the same mesh to the last bit."""
    import gc
    first = _fit_hash()
    junk = [bpy.data.meshes.new(f"junk{i}") for i in range(50)] + [object() for _ in range(20000)]
    gc.collect()
    assert _fit_hash() == first
    del junk
    child = subprocess.run([sys.executable, str(Path(__file__).resolve())], capture_output=True, text=True,
                           env={**os.environ, "PYTHONHASHSEED": "12345"}, timeout=600)
    line = next((ln for ln in child.stdout.splitlines() if ln.startswith(MARK)), None)
    assert line is not None, child.stdout[-2000:] + child.stderr[-2000:]
    assert line[len(MARK):].strip() == first


def test_crease_rows_say_what_was_measured():
    """The crease row names only the sides measured; a low share says what to do; every row
    fits the panel."""
    import importlib
    L = importlib.import_module("forge_send.stages_late")
    base = {"method": "quadremesher", "tris_before": 90000, "tris_after": 30000}

    def said(r):
        rows = L._retopo_rows({"parts": {"Body": r}})
        assert max(len(t) for _i, t in rows) <= L.PANEL_WIDTH, max(rows, key=lambda x: len(x[1]))
        return rows, " ".join(" ".join(t.split()) for _i, t in rows)
    rows, text = said({**base, "creases": {"left_pct": 96.0, "right_pct": 88.6, "left_n": 124, "right_n": 140,
                                           "carved_tris": 290}})
    assert "face creases kept: left 96.0%, right 88.6% (+290 tris carved)" in text, text
    assert "paint" not in text and not any(i == L.WARN for i, _t in rows), text
    rows, text = said({**base, "creases": {"left_pct": 62.0, "left_n": 40, "carved_tris": 0}})
    assert "face creases kept: left 62.0%" in text and "right" not in text, text
    assert "narrower than the quads" in text and "paint them red (Paint)" in text, text
    assert any(i == L.WARN for i, _t in rows)
    _rows, text = said({**base, "creases": {"carved_tris": 12}})
    assert "crease" not in text, text


if __name__ == "__main__":                      # the fresh process of test_fit_is_the_same_in_a_fresh_process
    print(MARK + _fit_hash(), flush=True)
