"""Step 4 gives the same result for the same input, whatever ran before in the process.

The parts plan and the planned cut (steps.prepare_maps / steps.plan_parts, then rescue.split_off
and density.symmetrize for a side, as tests/zoo_baseline.py's fast mode runs them) on zoo bodies
with one-sided parts, cuts that weld or fail, and pieces next to each other: twice in this
process (with other allocations between, so memory addresses differ) and once in a fresh
process with another hash seed and the bodies in the other order. The stored plan, the split,
and the fingerprint and exact hash (every bit) of every piece and of the body must be exactly
the same each time: a set of Blender elements runs in memory-address order, and a result that
depended on it would differ from run to run (and a remesher makes another mesh of a few last
bits). One body has the AI-like surface, whose noise must not come from the clock; the zoo's
ground truth of every body is compared too.
"""

import gc
import hashlib
import json
import os
import random
import subprocess
import sys
from pathlib import Path

import pytest

bpy = pytest.importorskip("bpy")
HERE = Path(__file__).resolve().parent
for _p in (HERE, HERE.parent / "blender_scripts", HERE.parent / "blender_addon"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# bodies with a one-sided part, spikes on a part, a wing or fin root that cannot be plugged,
# two cut parts and a part that welds back; and one with the AI-like surface (+ai)
NAMES = ["tail_spikes", "weapon_up", "one_wing", "one_wing_bat", "dorsal_fin_quadruped", "two_tails", "trunk",
         "tail_spikes+ai"]
SIDES = ("auto", "left", "right")
VOXEL = 0.012          # coarser than the zoo's 0.008: the same parts and cuts in a third of the time
MARK = "DETERMINISM "


def _fingerprints(me) -> list:
    """The mesh on the grid in any order, on the grid in its own order, and to the last bit."""
    from forge_bpy import density
    return [list(density.fingerprint(me, ordered=False)), list(density.fingerprint(me)), density.exact_hash(me)]


def _cut(me, ids, side) -> dict:
    """The planned cut and mirror on a copy of the body (zoo_baseline.dry_run's steps)."""
    from mathutils import Matrix

    from forge_bpy import density, rescue
    m2 = me.copy()
    mirror = side in ("left", "right") and density.straddles_middle(me)
    shift = density.mirror_plane(m2) if mirror else 0.0
    if abs(shift) > 1e-6:
        m2.transform(Matrix.Translation((-shift, 0, 0)))
    rep: list = []
    pieces = rescue.split_off(m2, ids, rep) if ids is not None else []
    if mirror and (rep or me.get("forge_mirror_blocked")):
        mirror = False
    if mirror:
        density.symmetrize(m2, side)
    out = {"mirrored": mirror, "plane": repr(float(shift)), "refused": [[int(k), str(w)] for k, w in rep],
           "body": _fingerprints(m2),
           "pieces": [[int(k), _fingerprints(pm), [repr(float(x)) for x in (p or [])]] for k, pm, p in pieces]}
    for m in [m2] + [pm for _k, pm, _p in pieces]:
        bpy.data.meshes.remove(m)
    return out


def _record(name: str) -> dict:
    """Plan and cut of one body for every Symmetry choice."""
    import bodies_zoo as Z
    import numpy as np
    import zoo_baseline as ZB
    from forge_bpy import density
    key, ai = name.split("+")[0], name.endswith("+ai")
    _key, gen, kw = next(b for b in ZB.BODIES if b[0] == key)
    ob, info = Z.ZOO[gen](**{"voxel": VOXEL, **kw, **(ZB.AI if ai else {})})
    me = ob.data
    rec = {"input": _fingerprints(me),
           "truth": hashlib.sha1(np.asarray(info["truth"], np.int32).tobytes()).hexdigest()}
    S = ZB.as_forge_body(ob)
    for side in SIDES:
        if side == "auto":
            S.prepare_maps(0.8, recompute=True, side="auto")
        else:
            S.plan_parts(recompute=True, side=side)
        ids = density.read_split(me)
        plan = ob.get("forge_plan")
        names = me.get("forge_split_names")
        rec[side] = {"plan": list((plan.to_dict() if plan is not None else {}).items()),
                     "split": None if ids is None else hashlib.sha1(np.asarray(ids, np.int32).tobytes()).hexdigest(),
                     "parts": None if ids is None else np.unique(ids, return_counts=True)[1].tolist(),
                     "names": list((names.to_dict() if names is not None else {}).items()),
                     "blocked": me.get("forge_mirror_blocked"), **_cut(me, ids, side)}
    bpy.ops.wm.read_homefile(use_empty=True)
    return json.loads(json.dumps(rec))               # (tuples as lists: comparable with the child's)


def _junk(seed: int) -> None:
    """Allocate and free Blender and Python objects: memory addresses differ from the run before."""
    import bmesh
    rnd = random.Random(seed)
    for i in range(3):
        bm = bmesh.new()
        bmesh.ops.create_icosphere(bm, subdivisions=rnd.randint(3, 5), radius=1.0)
        held = set(bm.verts) | set(bm.faces)
        me = bpy.data.meshes.new(f"junk{i}")
        bm.to_mesh(me)
        bm.free()
        del held
    _junk.alive.append([object() for _ in range(rnd.randint(1000, 40000))])
    gc.collect()


_junk.alive = []


@pytest.fixture(scope="module")
def runs():
    first = {n: _record(n) for n in NAMES}
    _junk(1)
    second = {n: _record(n) for n in NAMES}
    env = {**os.environ, "PYTHONHASHSEED": "4242"}
    child = subprocess.run([sys.executable, str(Path(__file__).resolve()), *NAMES[::-1]], env=env,
                           capture_output=True, text=True, timeout=900)
    line = next((ln for ln in child.stdout.splitlines() if ln.startswith(MARK)), None)
    assert line is not None, child.stdout[-2000:] + child.stderr[-2000:]
    return first, second, json.loads(line[len(MARK):])


def _first_difference(a, b, path="") -> str:
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if a.get(k) != b.get(k):
                return _first_difference(a.get(k), b.get(k), f"{path}.{k}")
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for i, (x, y) in enumerate(zip(a, b)):
            if x != y:
                return _first_difference(x, y, f"{path}[{i}]")
    return f"{path}: {str(a)[:200]} != {str(b)[:200]}"


@pytest.mark.parametrize("name", NAMES)
def test_plan_and_cut_are_the_same_in_every_run(runs, name):
    first, second, child = runs
    assert first[name] == second[name], "again in this process: " + _first_difference(first[name], second[name])
    assert first[name] == child[name], "in a fresh process: " + _first_difference(first[name], child[name])


def test_the_runs_cut_and_mirror_something(runs):
    """(The comparison means something: parts are planned and cut, a body is mirrored.)"""
    first = runs[0]
    assert any(first[n][s]["pieces"] for n in NAMES for s in SIDES)
    assert any(first[n][s]["mirrored"] for n in NAMES for s in SIDES)
    assert any(first[n][s]["refused"] for n in NAMES for s in SIDES)


def _mesh(verts, faces, name="fp"):
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.update()
    return me


def _parts(me):
    verts = [tuple(v.co) for v in me.vertices]
    faces = [tuple(p.vertices) for p in me.polygons]
    return verts, faces


def _uv_sphere():
    import bmesh
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=12, v_segments=8, radius=1.0)
    me = bpy.data.meshes.new("s")
    bm.to_mesh(me)
    bm.free()
    return me


CUBE_FACES = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]


def _cube(k=1.0):
    """A cube of size 2k around the middle (for k a power of two its corners sit on the grid)."""
    return [(x, y, z) for x in (-k, k) for y in (-k, k) for z in (-k, k)]


def test_fingerprint_is_the_surface_not_the_order():
    from forge_bpy import density
    from forge_bpy.common import canonical_order
    bpy.ops.wm.read_homefile(use_empty=True)
    me = _uv_sphere()
    fp, fo = density.fingerprint(me, ordered=False), density.fingerprint(me)
    assert fp[:2] == (len(me.vertices), len(me.polygons))
    assert density.fingerprint(me.copy()) == fo
    assert density.exact_hash(me.copy()) == density.exact_hash(me)
    # the same surface in another order: canonical_order, or every vertex and face listed backwards
    again = me.copy()
    canonical_order(again, by_position=True)
    assert density.fingerprint(again, ordered=False) == fp
    assert density.fingerprint(again) != fo                       # (by default the order counts)
    verts, faces = _parts(me)
    n = len(verts)
    back = _mesh(verts[::-1], [tuple(n - 1 - i for i in f) for f in faces[::-1]], "back")
    assert density.fingerprint(back, ordered=False) == fp
    # put in canonical order, both come out exactly the same
    canonical_order(back, by_position=True)
    assert density.fingerprint(back) == density.fingerprint(again)
    assert density.exact_hash(back) == density.exact_hash(again)
    # one point moved by a thousandth of the size: another surface
    size = 2.0
    moved = me.copy()
    moved.vertices[5].co.x += 1e-3 * size
    assert density.fingerprint(moved, ordered=False) != fp
    # a face turned the other way: another surface
    flipped = _mesh(verts, [f[::-1] if i == 0 else f for i, f in enumerate(faces)], "flip")
    assert density.fingerprint(flipped, ordered=False) != fp


def test_fingerprint_sees_where_the_mesh_is_and_its_size():
    """The same mesh moved by half its size, or scaled by two, by a half or by a hundred, is not
    the same mesh (a mirror run without its shift undone, a body moved between plan and run)."""
    from forge_bpy import density
    bpy.ops.wm.read_homefile(use_empty=True)
    me = _uv_sphere()
    verts, faces = _parts(me)
    for ordered in (True, False):
        fp = density.fingerprint(me, ordered=ordered)
        moved = _mesh([(x + 1.0, y, z) for x, y, z in verts], faces, "moved")
        assert density.fingerprint(moved, ordered=ordered) != fp, ordered
        for k in (2.0, 0.5, 100.0):
            scaled = _mesh([(x * k, y * k, z * k) for x, y, z in verts], faces, "scaled")
            assert density.fingerprint(scaled, ordered=ordered) != fp, (ordered, k)


def test_fingerprint_sees_which_copy_a_face_uses_and_loose_edges():
    """Without the order: a welded edge with two loose copies of its ends is not an open seam
    (the second face on the copies), though both have the same points and faces at the same
    places; an extra loose edge is seen too."""
    from forge_bpy import density
    bpy.ops.wm.read_homefile(use_empty=True)
    a = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.5, 1.0, 0.0), (0.5, -1.0, 0.0)]
    welded = _mesh(a + [a[0], a[1]], [(0, 1, 2), (1, 0, 3)], "welded")
    seam = _mesh(a + [a[0], a[1]], [(0, 1, 2), (5, 4, 3)], "seam")
    assert density.fingerprint(welded, ordered=False)[:2] == density.fingerprint(seam, ordered=False)[:2]
    assert density.fingerprint(welded, ordered=False) != density.fingerprint(seam, ordered=False)
    # the same open seam with its two copies listed the other way round: the same mesh
    seam2 = _mesh([a[1], a[0], a[2], a[3], a[1], a[0]], [(5, 4, 2), (0, 1, 3)], "seam2")
    assert density.fingerprint(seam2, ordered=False) == density.fingerprint(seam, ordered=False)
    me = _uv_sphere()
    verts, faces = _parts(me)
    wire = bpy.data.meshes.new("wire")
    wire.from_pydata(verts, [(0, len(verts) - 1)], faces)
    wire.update()
    for ordered in (True, False):
        assert density.fingerprint(wire, ordered=ordered) != density.fingerprint(me, ordered=ordered)


def test_fingerprint_ignores_the_last_bits_and_the_exact_hash_does_not():
    """Coordinates count on a grid of at most a millionth of the size: a cube of size 2 has its
    corners on that grid, and a corner moved by far less than a grid step (inward: the size
    stays) gives the same fingerprint; a corner moved a thousandth of the size does not. The
    same holds at x1/128 and x128. The exact hash sees a single float step."""
    import numpy as np

    from forge_bpy import density
    bpy.ops.wm.read_homefile(use_empty=True)
    for k in (1.0, 1.0 / 128, 128.0):
        verts = _cube(k)
        a = _mesh(verts, CUBE_FACES, "a")
        near = list(verts)
        near[7] = (k * (1.0 - 2e-7), k, k)
        far = list(verts)
        far[7] = (k * (1.0 - 2e-3), k, k)
        assert density.fingerprint(_mesh(near, CUBE_FACES, "near")) == density.fingerprint(a), k
        assert density.fingerprint(_mesh(far, CUBE_FACES, "far")) != density.fingerprint(a), k
    verts = _cube()
    a = _mesh(verts, CUBE_FACES, "a")
    ulp = list(verts)
    ulp[7] = (float(np.nextafter(np.float32(1.0), np.float32(0.0))), 1.0, 1.0)
    b = _mesh(ulp, CUBE_FACES, "ulp")
    assert b.vertices[7].co.x != a.vertices[7].co.x
    assert density.fingerprint(b) == density.fingerprint(a)
    assert density.exact_hash(b) != density.exact_hash(a)


def test_points_on_one_spot_are_ordered_by_their_neighbours_not_by_input():
    """canonical_order(by_position): two points on the very same spot (an unwelded seam, a
    result built in threads) come out in the same order whichever came first - also two back
    to back faces whose third corners share a spot and differ only in the winding."""
    from forge_bpy import density
    from forge_bpy.common import canonical_order
    bpy.ops.wm.read_homefile(use_empty=True)
    tri_a = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
    tri_b = [(0.0, 0.0, 0.0), (-1.0, 0.0, 0.0), (0.0, -1.0, 0.0)]
    one = _mesh(tri_a + tri_b, [(0, 1, 2), (3, 4, 5)], "one")
    two = _mesh(tri_b + tri_a, [(0, 1, 2), (3, 4, 5)], "two")
    assert density.fingerprint(one) != density.fingerprint(two)
    canonical_order(one, by_position=True)
    canonical_order(two, by_position=True)
    assert _parts(one) == _parts(two)
    p = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 0.0)]
    one = _mesh(p, [(0, 1, 2), (3, 2, 1)], "bb1")
    two = _mesh([p[3], p[1], p[2], p[0]], [(3, 1, 2), (0, 2, 1)], "bb2")     # the two on one spot swapped
    assert density.fingerprint(one, ordered=False) == density.fingerprint(two, ordered=False)
    canonical_order(one, by_position=True)
    canonical_order(two, by_position=True)
    assert _parts(one) == _parts(two)


def _grid(n, half):
    """A flat grid of n x n quads, 2 x half wide, around the middle."""
    step = 2 * half / n
    verts = [(-half + i * step, -half + j * step, 0.0) for j in range(n + 1) for i in range(n + 1)]
    faces = [(j * (n + 1) + i, j * (n + 1) + i + 1, (j + 1) * (n + 1) + i + 1, (j + 1) * (n + 1) + i)
             for j in range(n) for i in range(n)]
    return verts, faces


def test_carve_joins_the_same_crossing_points_whatever_the_corner_order():
    """density.carve on a coarse grid over two grooves that both cross the middle quad (three
    crossing points on that face, so it has to choose which two to join): the same mesh comes
    out whichever corner each face starts at and whatever order the faces are in. (Joining the
    first two crossing points in the face's own corner order gave 5 different meshes for these
    6 orders.)"""
    import numpy as np

    from forge_bpy import density
    bpy.ops.wm.read_homefile(use_empty=True)
    half, depth, width = 1.5, 0.04, 0.15                 # (the middle quad is 1 wide)
    verts, faces = _grid(150, half)
    co = np.array(verts)
    for c in (-0.6, 0.6):                                # two grooves along x + y = c
        r = np.abs(co[:, 0] + co[:, 1] - c) / np.sqrt(2)
        co[:, 2] -= np.where(r < width, depth * (1 - (r / width) ** 2), 0.0)
    src = _mesh(co.tolist(), faces, "src")
    density.write_strict(src, np.full(len(co), 0.35))
    tree = density.source_tree(src)
    gv, gf = _grid(3, half)
    results = set()
    for turn, backwards in [(None, False), (1, False), (2, False), (3, False), (1, True), (2, True)]:
        fs = [list(f) for f in gf] if turn is None else [
            list(f[r:] + f[:r]) for i, f in enumerate(gf) for r in [(turn + 3 * i) % 4]]
        low = _mesh(gv, fs[::-1] if backwards else fs, "low")
        added = density.carve(low, src, tree, max_add=1.0)
        assert added["splits"] >= 4, added
        results.add(density.fingerprint(low, ordered=False))
    assert len(results) == 1


if __name__ == "__main__":                      # the fresh process of test_plan_and_cut_are_the_same_in_every_run
    out = {n: _record(n) for n in (sys.argv[1:] or NAMES)}
    print(MARK + json.dumps(out), flush=True)
