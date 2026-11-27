"""Slices and rays through a mesh (sections.py): pure numpy, on meshes built here from arrays."""

import math
import sys
from itertools import pairwise
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "blender_scripts"))

from forge_bpy import sections as S  # noqa: E402

K = 32  # points round each ring; a multiple of 4, so the rings hold the box corners and the poles


# ---------------------------------------------------------------------------------------
# mesh builders (faces wind outward)

class _Arr:
    """The polygon arrays of parts.MeshArrays, built from a face list."""

    def __init__(self, co, faces):
        self.co = np.asarray(co, float)
        self.lt = np.array([len(f) for f in faces], np.int64)
        self.ls = np.concatenate([[0], np.cumsum(self.lt)[:-1]]).astype(np.int64)
        self.lv = np.array([i for f in faces for i in f], np.int64)


def _mesh(co, faces):
    arr = _Arr(co, faces)
    return arr.co, S.tris(arr)


def _join(*meshes):
    """Several meshes as one (separate shells)."""
    V, T, off = [], [], 0
    for v, t in meshes:
        V.append(v)
        T.append(t + off)
        off += len(v)
    return np.vstack(V), np.vstack(T)


def _loft(rings, cap_start=True, cap_end=True):
    """A tube through rings of K points each (a single point is a pole). The rings go round
    their axis counter-clockwise seen from where the tube runs to; quads join them, and a fan
    round a centre point closes an end ring."""
    co, faces, ids = [], [], []
    for r in rings:
        r = np.atleast_2d(np.asarray(r, float))
        ids.append(list(range(len(co), len(co) + len(r))))
        co.extend(r.tolist())
    for a, b in pairwise(ids):
        if len(a) == 1:
            faces += [[a[0], b[(j + 1) % K], b[j]] for j in range(K)]
        elif len(b) == 1:
            faces += [[a[j], a[(j + 1) % K], b[0]] for j in range(K)]
        else:
            faces += [[a[j], a[(j + 1) % K], b[(j + 1) % K], b[j]] for j in range(K)]
    for end, ring, flip in ((cap_start, ids[0], True), (cap_end, ids[-1], False)):
        if end and len(ring) > 1:
            c = len(co)
            co.append(np.mean([co[i] for i in ring], axis=0).tolist())
            faces += [[c, ring[(j + 1) % K], ring[j]] if flip else [c, ring[j], ring[(j + 1) % K]]
                      for j in range(K)]
    return _mesh(co, faces)


def _ring(c, e1, e2, a, b=None):
    """K points c + a cos(phi) e1 + b sin(phi) e2 (needs e1 x e2 = the tube's direction)."""
    phi = 2 * np.pi * np.arange(K) / K
    b = a if b is None else b
    return (np.asarray(c, float) + a * np.cos(phi)[:, None] * np.asarray(e1, float)
            + b * np.sin(phi)[:, None] * np.asarray(e2, float))


def _revolve(xs, rs, axis="x", centre=(0.0, 0.0), cap_start=True, cap_end=True):
    """A body of revolution: radius rs[i] at height xs[i] along the axis (0 makes a pole)."""
    if axis == "x":
        D, e1, e2 = np.eye(3)[0], np.eye(3)[1], np.eye(3)[2]
        c0 = np.array([0.0, centre[0], centre[1]])
    elif axis == "y":
        D, e1, e2 = np.eye(3)[1], np.eye(3)[2], np.eye(3)[0]
        c0 = np.array([centre[0], 0.0, centre[1]])
    else:
        D, e1, e2 = np.eye(3)[2], np.eye(3)[0], np.eye(3)[1]
        c0 = np.array([centre[0], centre[1], 0.0])
    rings = [c0 + x * D if r == 0 else _ring(c0 + x * D, e1, e2, r) for x, r in zip(xs, rs)]
    return _loft(rings, cap_start, cap_end)


def _cylinder(r, z0, z1, centre=(0.0, 0.0), axis="z", n=6, caps=True):
    return _revolve(np.linspace(z0, z1, n), [r] * n, axis, centre, caps, caps)


def _box(lo, hi, n=4):
    """A closed box, each side an n x n grid of quads."""
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    co, faces = [], []
    g = np.linspace(0, 1, n + 1)
    for ax in range(3):
        for side in (0, 1):
            o = lo.copy()
            o[ax] = (lo if side == 0 else hi)[ax]
            a, b = (ax + 1) % 3, (ax + 2) % 3
            U, W = np.zeros(3), np.zeros(3)
            U[a], W[b] = hi[a] - lo[a], hi[b] - lo[b]
            if side == 0:              # U x W must point out of the box
                U, W = W, U
                o = o.copy()
            base = len(co)
            for i in g:
                for j in g:
                    co.append(o + i * U + j * W)
            for i in range(n):
                for j in range(n):
                    v = base + i * (n + 1) + j
                    faces.append([v, v + n + 1, v + n + 2, v + 1])
    co = np.array(co)
    _, first, inv = np.unique(np.round(co, 9), axis=0, return_index=True, return_inverse=True)
    inv = inv.reshape(-1)
    order = np.argsort(first)              # keep vertices in build order
    remap = np.empty_like(order)
    remap[order] = np.arange(len(order))
    co = co[first[order]]
    faces = [[int(remap[inv[v]]) for v in f] for f in faces]
    return _mesh(co, faces)


def _box_arm(w=1.0, h=0.6, r=0.3, arm=2.4, arm_rings=10):
    """A box (x from -w to w, y and z from -h to h) with an arm of radius r fused into its +X
    side: one closed surface. The arm ends at x = w + arm; arm_rings=2 gives faces that run
    its whole length."""
    phi = 2 * np.pi * np.arange(K) / K
    dirs = np.stack([np.cos(phi), np.sin(phi)], 1)
    rect = dirs / np.abs(dirs).max(axis=1, keepdims=True) * h
    rings = []
    for x in np.linspace(-w, w, 6):
        rings.append(np.column_stack([np.full(K, x), rect]))
    for x in np.linspace(w, w + arm, arm_rings):
        rings.append(np.column_stack([np.full(K, x), r * dirs]))
    return _loft(rings)


def _ring_shell(x0, x1, ri, ro):
    """A hollow ring round the X axis (a bracelet, a belt) from x0 to x1: an outer wall of
    radius ro and an inner wall of radius ri, joined by flat ends, all faces winding out of
    the ring's material."""
    e1, e2 = np.array([0.0, 1.0, 0.0]), np.array([0.0, 0.0, 1.0])
    rings = [_ring((x, 0, 0), e1, e2, rad) for x, rad in ((x0, ro), (x1, ro), (x1, ri), (x0, ri))]
    ids = [list(range(i * K, (i + 1) * K)) for i in range(4)]
    faces = []
    for a, b in zip(ids, ids[1:] + ids[:1]):
        faces += [[a[j], a[(j + 1) % K], b[(j + 1) % K], b[j]] for j in range(K)]
    return _mesh(np.vstack(rings), faces)


def _rot(seed):
    """A fixed random rotation (no mirror)."""
    q, _ = np.linalg.qr(np.random.default_rng(seed).normal(size=(3, 3)))
    if np.linalg.det(q) < 0:
        q[:, 0] *= -1
    return q


def _bent_tube(r=0.2, length=3.0, bend=30.0, n=8):
    """Two straight tubes of equal length meeting at a mitre, turning by `bend` degrees in
    the XY plane. The line from end to end is the X axis; the corner points to +Y."""
    h = math.radians(bend) / 2
    c, s = math.cos(h), math.sin(h)
    d1, d2 = np.array([c, s, 0.0]), np.array([c, -s, 0.0])
    z = np.array([0.0, 0.0, 1.0])
    e1a, e1b = np.cross(z, d1), np.cross(z, d2)
    knee = length * d1
    rings = [_ring(t * d1, e1a, z, r) for t in np.linspace(0, length, n, endpoint=False)]
    rings.append(_ring(knee, np.cross(z, [1.0, 0, 0]), z, r / c, r))
    rings += [_ring(knee + t * d2, e1b, z, r) for t in np.linspace(0, length, n + 1)[1:]]
    return _loft(rings), d1, d2, knee


def _icosphere(sub=2, radius=1.0):
    t = (1 + 5 ** 0.5) / 2
    co = [(-1, t, 0), (1, t, 0), (-1, -t, 0), (1, -t, 0), (0, -1, t), (0, 1, t), (0, -1, -t),
          (0, 1, -t), (t, 0, -1), (t, 0, 1), (-t, 0, -1), (-t, 0, 1)]
    co = [np.array(p, float) / np.linalg.norm(p) for p in co]
    faces = [(0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11), (1, 5, 9), (5, 11, 4),
             (11, 10, 2), (10, 7, 6), (7, 1, 8), (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8),
             (3, 8, 9), (4, 9, 5), (2, 4, 11), (6, 2, 10), (8, 6, 7), (9, 8, 1)]

    def mid(a, b, made):
        k = (min(a, b), max(a, b))
        if k not in made:
            p = co[a] + co[b]
            made[k] = len(co)
            co.append(p / np.linalg.norm(p))
        return made[k]

    for _ in range(sub):
        made, nf = {}, []
        for a, b, c in faces:
            ab, bc, ca = mid(a, b, made), mid(b, c, made), mid(c, a, made)
            nf += [(a, ab, ca), (b, bc, ab), (c, ca, bc), (ab, bc, ca)]
        faces = nf
    return np.array(co) * radius, np.array(faces, np.int64)


def _area_polygon_ring(r):
    return 0.5 * K * r * r * math.sin(2 * math.pi / K)


# ---------------------------------------------------------------------------------------
# triangles

def test_tris_fans_polygons_and_keeps_winding():
    co = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (2, 0, 0), (3, 0, 0), (3.5, 1, 0), (2.5, 2, 0),
          (1.5, 1, 0)]
    arr = _Arr(co, [[0, 1, 2, 3], [4, 5, 6, 7, 8], [0, 1, 2]])
    T, poly = S.tris(arr, with_poly=True)
    assert T.tolist() == [[0, 1, 2], [0, 2, 3], [4, 5, 6], [4, 6, 7], [4, 7, 8], [0, 1, 2]]
    assert poly.tolist() == [0, 0, 1, 1, 1, 2]
    V = np.asarray(co, float)
    nz = np.cross(V[T[:, 1]] - V[T[:, 0]], V[T[:, 2]] - V[T[:, 0]])[:, 2]
    assert (nz > 0).all()                       # same winding as the polygons


def test_mask_tris_drops_every_triangle_with_an_excluded_corner():
    T = np.array([[0, 1, 2], [2, 3, 4], [3, 4, 5]])
    assert S.mask_tris(T, [3, 4, 5]).tolist() == [[0, 1, 2]]
    ex = np.zeros(6, bool)
    ex[[3]] = True
    assert S.mask_tris(T, ex).tolist() == [[0, 1, 2]]
    # a bool mask over fewer vertices than the mesh has counts the rest as kept
    assert S.mask_tris(T, np.zeros(2, bool)).tolist() == T.tolist()
    assert S.mask_tris(T, []).tolist() == T.tolist()


def _edge_faces(T):
    """For each directed edge, how many triangles run along it."""
    he = np.concatenate([T[:, [0, 1]], T[:, [1, 2]], T[:, [2, 0]]])
    keys, cnt = np.unique(he, axis=0, return_counts=True)
    return {tuple(k): int(c) for k, c in zip(keys.tolist(), cnt.tolist())}


def test_mask_tris_closes_the_root_of_a_fused_part():
    """An arm that grows out of the body (one surface) is masked: the body's slices through
    its root still close, measure the body alone, and the trunk axis finds every sample."""
    w, h = 1.0, 0.6
    V, T = _box_arm(w=w, h=h)
    arm = V[:, 0] > w + 1e-9
    Tm, cap = S.mask_tris(T, arm, with_caps=True)
    assert cap.any() and not cap[:len(Tm) - int(cap.sum())].any()
    assert not np.isin(Tm, np.nonzero(arm)[0]).any()
    # closed and wound alike: every edge has one face each way
    ef = _edge_faces(Tm)
    assert all(c == 1 and ef.get((b, a)) == 1 for (a, b), c in ef.items())
    for z in (0.0, 0.1, 0.25):
        sec = S.section(V, Tm, (0, 0, z), (0, 0, 1))
        assert len(sec) == 1 and sec[0]["closed"] and sec[0]["signed_area"] > 0
        assert sec[0]["area"] == pytest.approx(2 * w * 2 * h, rel=1e-9)
    axis = S.trunk_axis(V, Tm, -0.5, 0.5, 0.0, steps=10)
    assert all(s["found"] and s["closed"] for s in axis)
    assert S.inside(V, Tm, (0.9, 0.05, 0.03)) and not S.inside(V, Tm, (1.5, 0.05, 0.03))
    # a hole the mask makes is patched; the holes the mesh had (an open tube's ends) stay open
    Vc, Tc = _cylinder(0.5, 0.0, 2.0, caps=False)
    Tcm = S.mask_tris(Tc, [2 * K])               # one vertex halfway up the side
    ef = _edge_faces(Tcm)
    open_edges = [e for e in ef if (e[1], e[0]) not in ef]
    assert len(open_edges) == 2 * K
    assert all(abs(Vc[a, 2] - Vc[b, 2]) < 1e-12 and Vc[a, 2] in (0.0, 2.0) for a, b in open_edges)


def test_mask_tris_removes_an_excluded_part_from_slices():
    body = _cylinder(0.5, 0.0, 2.0)
    tail = _cylinder(0.1, 0.5, 1.5, centre=(1.5, 0.0))
    V, T = _join(body, tail)
    tail_ids = np.arange(len(body[0]), len(V))
    before = S.section(V, T, (0, 0, 1.0), (0, 0, 1))
    after = S.section(V, S.mask_tris(T, tail_ids), (0, 0, 1.0), (0, 0, 1))
    assert len(before) == 2 and len(after) == 1
    assert after[0]["r"] == pytest.approx(before[0]["r"])


# ---------------------------------------------------------------------------------------
# slices

def test_cut_cylinder():
    r = 0.5
    V, T = _cylinder(r, 0.0, 2.0, centre=(0.3, -0.2))
    lps = S.loops(*S.cut(V, T, (0.0, 0.0, 0.77), (0, 0, 1)))
    assert len(lps) == 1 and lps[0]["closed"]
    pr = S.loop_props(lps[0], (0, 0, 1))
    assert np.linalg.norm(pr["centroid"][:2] - [0.3, -0.2]) < 0.02 * r
    assert abs(pr["centroid"][2] - 0.77) < 1e-9
    assert abs(pr["r"] - r) < 0.02 * r
    assert pr["signed_area"] > 0                # counter-clockwise round solid, seen from +Z
    assert pr["aspect"] == pytest.approx(1.0, abs=1e-6)
    assert pr["roundness"] > 0.99


def test_cut_tilted_plane_measures_an_ellipse():
    r, tilt = 0.5, math.radians(40)
    V, T = _cylinder(r, -2.0, 2.0)
    n = (math.sin(tilt), 0.0, math.cos(tilt))
    lps = S.loops(*S.cut(V, T, (0, 0, 0.1), n))
    assert len(lps) == 1 and lps[0]["closed"]
    pr = S.loop_props(lps[0], n)
    assert pr["area"] == pytest.approx(_area_polygon_ring(r) / math.cos(tilt), rel=1e-6)
    assert pr["aspect"] == pytest.approx(1 / math.cos(tilt), rel=0.02)
    assert abs(abs(pr["major"] @ _unit((math.cos(tilt), 0, -math.sin(tilt)))) - 1) < 1e-3


def _unit(v):
    v = np.asarray(v, float)
    return v / np.linalg.norm(v)


def test_loop_props_uses_the_vector_area_without_a_normal():
    n = _unit((1.0, 2.0, 2.0))
    u = _unit(np.cross(n, (0, 0, 1)))
    v = np.cross(n, u)
    pts = _ring((5.0, -3.0, 2.0), u, v, 0.7)
    pr = S.loop_props(pts)
    assert pr["area"] == pytest.approx(_area_polygon_ring(0.7))
    assert abs(pr["normal"] @ n) == pytest.approx(1.0)
    assert np.allclose(pr["centroid"], (5.0, -3.0, 2.0))
    assert pr["off_plane"] < 1e-9
    assert pr["contains"]((5.0, -3.0, 2.0)) and not pr["contains"]((5.0, -3.0, 2.0) + 0.8 * u)
    # a loop that is not flat (a cut ring snapped to a crease) still gets an area and a plane
    wavy = pts + 0.05 * np.cos(2 * 2 * np.pi * np.arange(K) / K)[:, None] * n
    pw = S.loop_props(wavy)
    assert pw["area"] == pytest.approx(_area_polygon_ring(0.7), rel=1e-6)
    assert 0 < pw["off_plane"] < 0.1


def test_loop_contains_picks_right_loop():
    big = _cylinder(1.0, 0.0, 2.0, centre=(0.0, 0.0))
    small = _cylinder(0.2, 0.0, 2.0, centre=(1.4, 0.0))
    V, T = _join(big, small)
    p = np.array([0.95, 0.0, 1.0])              # inside the big one, nearer the small one's centre
    lp, n_loops = S.loop_at(V, T, p, (0, 0, 1))
    assert n_loops == 2
    assert lp["inside"] and lp["n_inside"] == 1
    assert lp["r"] == pytest.approx(1.0, rel=0.02)
    lp, _ = S.loop_at(V, T, (1.45, 0.05, 1.0), (0, 0, 1))
    assert lp["r"] == pytest.approx(0.2, rel=0.02)
    # outside both: the nearest centroid wins
    lp, _ = S.loop_at(V, T, (1.4, 0.5, 1.0), (0, 0, 1))
    assert not lp["inside"] and lp["r"] == pytest.approx(0.2, rel=0.02)


def test_hollow_tube_inner_wall_is_a_hole():
    outer = _cylinder(1.0, 0.0, 2.0, caps=False)
    inner = _cylinder(0.6, 0.0, 2.0, caps=False)
    inner = (inner[0], inner[1][:, ::-1])       # its faces look into the hollow
    V, T = _join(outer, inner)
    sec = S.section(V, T, (0, 0, 1.0), (0, 0, 1))
    assert sorted(lp["hole"] for lp in sec) == [False, True]
    lp, n_loops = S.loop_at(V, T, (0, 0, 1.0), (0, 0, 1))
    assert n_loops == 1 and lp["r"] == pytest.approx(1.0, rel=0.02)


def test_limb_through_a_bracelet_stays_solid():
    """Inside a hollow ring a loop is solid again: an arm through a bracelet is not a hole, so
    the profile keeps the arm's radius and the armpit stays at the armpit."""
    w, r = 1.0, 0.3
    arm = _box_arm(w=w, r=r)
    for ro in (0.4, 0.45, 0.6):
        V, T = _join(arm, _ring_shell(2.6, 2.8, 0.31, ro))
        sec = S.section(V, T, (2.7, 0, 0), (-1, 0, 0))
        by_r = sorted(sec, key=lambda lp: lp["r"])
        limb, inner, outer = by_r
        assert not limb["hole"] and inner["hole"] and not outer["hole"]
        assert sec[limb["parent"]] is inner and sec[inner["parent"]] is outer
        assert outer["parent"] is None
        lp, n_loops = S.loop_at(V, T, (2.7, 0, 0), (-1, 0, 0))
        assert n_loops == 2 and lp["r"] == pytest.approx(r, rel=0.02)
        assert lp["n_inside"] == 1 and lp["enclosing"] == []
        a, b = np.array([w + 2.4, 0, 0]), np.zeros(3)
        prof = S.profile_along(V, T, a, b)
        assert max(s["r"] for s in prof if s["p"][0] > w + 0.2) == pytest.approx(r, rel=0.02)
        c = S.crease_along(prof)
        assert abs(c["p"][0] - w) < 0.3 * r
        fine = S.find_crease(V, T, a, b)
        assert abs(fine["p"][0] - w) < 0.05 * r


def test_nesting_three_deep():
    """A hollow rod through a hollow ring: wall, hole, solid, hole, from the outside in. The
    same when turned: every point lies on the plane, and rounding along it must not decide."""
    ring = _ring_shell(-0.5, 0.5, 0.6, 1.0)
    rod = _ring_shell(-2.0, 2.0, 0.2, 0.4)
    V, T = _join(ring, rod)
    for seed in (None, 0, 1, 2):
        R = np.eye(3) if seed is None else _rot(seed)
        sec = S.section(V @ R.T, T, np.array([0.1, 0, 0]) @ R.T, np.array([1.0, 0, 0]) @ R.T)
        order = sorted(range(len(sec)), key=lambda i: -sec[i]["r"])
        assert [sec[i]["hole"] for i in order] == [False, True, False, True]
        assert [round(sec[i]["r"], 1) for i in order] == [1.0, 0.6, 0.4, 0.2]
        assert [sec[i]["parent"] for i in order] == [None] + order[:3]


def test_ball_limit_opens_a_slice_that_reaches_further():
    assert S.ball_radius(0.1, 2.0) == pytest.approx(0.3)      # 0.15 H wins
    assert S.ball_radius(0.2, 2.0) == pytest.approx(0.6)      # 3 r wins
    assert S.ball_radius(None, 2.0) == pytest.approx(0.3)
    V, T = _box((-1, -1, -1), (1, 1, 1), n=8)
    lps = S.loops(*S.cut(V, T, (0, -1.0, 0), (0, 0, 1), ball=0.6))
    assert lps and not any(lp["closed"] for lp in lps)
    lps = S.loops(*S.cut(V, T, (0, -1.0, 0), (0, 0, 1)))
    assert len(lps) == 1 and lps[0]["closed"]


def test_ball_keeps_long_faces_that_pass_close_by():
    """The ball measures the slice, not the triangle corners: a limb whose faces run its whole
    length still closes in every slice, and its armpit is found where it is."""
    for rings in (2, 3, 4):
        V, T = _cylinder(0.2, 0.0, 4.0, axis="x", n=rings)
        prof = S.profile_along(V, T, (4.0, 0, 0), (0.0, 0, 0))
        assert all(s["closed"] for s in prof[:-1])
        assert S.crease_along(prof) is None
        segs, _ = S.cut(V, T, (2.0, 0, 0), (1, 0, 0), ball=0.3)
        assert len(S.loops(segs, _)) == 1
    w, r = 1.0, 0.3
    for rings in (2, 3):
        V, T = _box_arm(w=w, r=r, arm_rings=rings)
        a, b = np.array([w + 2.4, 0, 0]), np.zeros(3)
        prof = S.profile_along(V, T, a, b)
        assert all(s["closed"] for s in prof)
        c = S.crease_along(prof)
        assert abs(c["p"][0] - w) < 0.3 * r
        assert abs(S.find_crease(V, T, a, b)["p"][0] - w) < 0.05 * r


# ---------------------------------------------------------------------------------------
# degenerate input

def test_empty_cut():
    V, T = _cylinder(0.5, 0.0, 2.0)
    segs, keys = S.cut(V, T, (0, 0, 5.0), (0, 0, 1))
    assert segs.shape == (0, 2, 3) and keys.shape == (0, 2, 2)
    assert S.loops(segs, keys) == []
    assert S.loop_at(V, T, (0, 0, 5.0), (0, 0, 1)) == (None, 0)
    assert S.cut(V, T[:0], (0, 0, 1.0), (0, 0, 1))[0].shape == (0, 2, 3)
    assert S.cut(V, T, (0, 0, 1.0), (0, 0, 0))[0].shape == (0, 2, 3)   # no normal: no slice
    prof = S.profile_along(V, T, (0, 0, 3.0), (0, 0, 4.0), steps=4)
    assert len(prof) == 5 and not any(s["found"] for s in prof)
    assert S.crease_along(prof) is None
    assert S.narrowest_along(prof) == (None, 1.0)
    assert S.bend_along(np.zeros((3, 3)))[1] is None
    assert S.profile_along(V, T, (0, 0, 1.0), (0, 0, 1.0)) == []


def test_plane_through_vertices_exactly():
    r = 0.5
    V, T = _cylinder(r, 0.0, 2.0, n=5)          # rings at z = 0, 0.5, 1, 1.5, 2
    lps = S.loops(*S.cut(V, T, (0, 0, 1.0), (0, 0, 1)))
    assert len(lps) == 1 and lps[0]["closed"]
    assert len(lps[0]["pts"]) == K               # each ring vertex once, not twice
    pr = S.loop_props(lps[0], (0, 0, 1))
    assert pr["area"] == pytest.approx(_area_polygon_ring(r), rel=1e-12)
    assert pr["perimeter"] == pytest.approx(2 * K * r * math.sin(math.pi / K), rel=1e-12)
    # the plane of the top cap touches only: a vertex on the plane counts as below it
    assert S.loops(*S.cut(V, T, (0, 0, 2.0), (0, 0, 1))) == []
    # the bottom cap's plane gives the bottom ring
    lps = S.loops(*S.cut(V, T, (0, 0, 0.0), (0, 0, 1)))
    assert len(lps) == 1 and len(lps[0]["pts"]) == K
    # a sphere cut through one vertex, and touched at a vertex
    V, F = _icosphere(2)
    top = int(np.argmax(V[:, 2]))
    assert S.loops(*S.cut(V, F, V[top], (0, 0, 1))) == []
    assert S.loops(*S.cut(V, F, V[top], (0, 0, -1))) == []
    lps = S.loops(*S.cut(V, F, V[0], _unit((0.3, 0.1, 1.0))))
    assert len(lps) == 1 and lps[0]["closed"]
    pts = lps[0]["pts"]
    assert len(np.unique(pts, axis=0)) == len(pts)


def test_open_mesh_gives_open_chains():
    V, T = _cylinder(0.5, 0.0, 2.0, caps=False)
    lps = S.loops(*S.cut(V, T, (0, 0, 1.0), (0, 0, 1)))
    assert len(lps) == 1 and lps[0]["closed"]    # round an open tube: still a ring
    lps = S.loops(*S.cut(V, T, (0, 0.01, 1.0), (0, 1, 0)))
    assert len(lps) == 2 and not any(lp["closed"] for lp in lps)
    V, F = _icosphere(2)
    holed = F[V[F].mean(axis=1)[:, 0] < 0.85]
    lps = S.loops(*S.cut(V, holed, (0, 0, 0.01), (0, 0, 1)))
    assert len(lps) == 1 and not lps[0]["closed"]


def test_non_manifold_edge_gives_open_chains():
    co = [(0, 0, -1), (0, 0, 1), (1, 0, 0), (-1, 0.1, 0), (-1, -0.1, 0)]
    T = np.array([[0, 1, 2], [1, 0, 3], [0, 1, 4]])      # three faces on edge 0-1
    lps = S.loops(*S.cut(np.array(co, float), T, (0, 0, 0), (0, 0, 1)))
    assert lps and not any(lp["closed"] for lp in lps)


# ---------------------------------------------------------------------------------------
# along an axis

def test_crease_arm_into_box():
    w, r, arm = 1.0, 0.3, 2.4
    found = []
    for scale in (0.01, 1.0, 100.0):
        V, T = _box_arm(w=w, r=r, arm=arm)
        V = V * scale
        a, b = np.array([w + arm, 0, 0]) * scale, np.zeros(3)
        prof = S.profile_along(V, T, a, b)
        c = S.crease_along(prof)
        assert c is not None
        assert abs(c["p"][0] - w * scale) < 0.3 * r * scale
        found.append((c["t"], c["reason"], prof[c["before"]]["r"] / scale))
        fine = S.find_crease(V, T, a, b)
        assert abs(fine["p"][0] - w * scale) < 0.05 * r * scale
        assert fine["r"] == pytest.approx(r * scale, rel=0.02)
        assert fine["centroid"][0] > w * scale
    assert found[0][:2] == found[1][:2] == found[2][:2]       # the same crease at every scale
    assert found[0][2] == pytest.approx(found[2][2], rel=1e-9)


def test_crease_arm_into_box_turned():
    """The same body turned any way gives the same crease: no size or ball depends on the
    axes."""
    w, r, arm = 1.0, 0.3, 2.4
    V, T = _box_arm(w=w, r=r, arm=arm)
    a, b = np.array([w + arm, 0, 0]), np.zeros(3)
    ref = S.crease_along(S.profile_along(V, T, a, b))
    for seed in range(4):
        R = _rot(seed)
        assert S.body_size(V @ R.T, T) == pytest.approx(S.body_size(V, T), rel=1e-9)
        c = S.crease_along(S.profile_along(V @ R.T, T, a @ R.T, b @ R.T))
        assert (c["t"], c["reason"], c["before"]) == (ref["t"], ref["reason"], ref["before"])
        fine = S.find_crease(V @ R.T, T, a @ R.T, b @ R.T)
        assert abs((fine["p"] @ R)[0] - w) < 0.05 * r


def test_crease_ignores_a_sleeve():
    """A loose sleeve over the upper arm (a closed shell, or a single-sided cloth tube) is only a
    little bigger than the arm: the walk keeps to the arm and finds the armpit, not the cuff."""
    w, r = 1.0, 0.3
    arm = _box_arm(w=w, r=r)
    for caps in (True, False):
        V, T = _join(arm, _cylinder(1.2 * r, 0.95, 2.2, axis="x", n=8, caps=caps))
        a, b = np.array([w + 2.4, 0, 0]), np.zeros(3)
        prof = S.profile_along(V, T, a, b)
        in_sleeve = [s for s in prof if w + 0.1 < s["p"][0] < 2.1]
        assert in_sleeve and all(s["n_inside"] == 2 for s in in_sleeve)
        assert all(s["r"] == pytest.approx(r, rel=0.02) for s in in_sleeve)
        c = S.crease_along(prof)
        assert abs(c["p"][0] - w) < 0.3 * r
        assert abs(S.find_crease(V, T, a, b)["p"][0] - w) < 0.05 * r


def test_crease_of_an_arm_that_is_a_separate_shell():
    """An arm pushed into the body as its own shell keeps its size inside: the crease is where
    the axis is first inside two loops."""
    w, r = 0.6, 0.3
    body = _box((-0.6, -0.6, -0.6), (0.6, 0.6, 0.6), n=12)
    arm = _cylinder(r, 0.2, 3.0, axis="x", n=12)
    V, T = _join(body, arm)
    c = S.crease_along(S.profile_along(V, T, (3.0, 0, 0), (0, 0, 0)))
    assert c["reason"] == "split" and c["ratio"] > S.JUMP
    assert abs(c["p"][0] - w) < 0.3 * r


def test_a_limb_that_just_ends_has_no_crease():
    """The last slice of a profile that runs to the mesh's end face is empty: that is the end
    of the mesh, not a crease."""
    V, T = _cylinder(0.2, 0.0, 4.0, axis="x", n=12)
    prof = S.profile_along(V, T, (4.0, 0, 0), (0.0, 0, 0))
    assert prof[-1]["end"] and not prof[-1]["found"]
    assert S.crease_along(prof) is None and S.find_crease(V, T, (4.0, 0, 0), (0.0, 0, 0)) is None
    # every slice is limited, the first one too: 0.15 H before any radius is known
    assert prof[0]["ball"] == pytest.approx(S.BALL_SIZE * S.body_size(V, T))
    # trunk_axis samples walk too
    axis = S.trunk_axis(*_cylinder(0.5, 0.0, 2.0), 0.2, 1.8, 0.0, steps=6)
    assert S.crease_along(axis) is None


def test_crease_skips_a_rounded_tip():
    """Near a round tip the slice area also grows fast; fine slices would read it as a crease."""
    r = 0.3
    ang = np.linspace(0.15, np.pi / 2, 12)
    xs = [0.0] + list(r - r * np.cos(ang)) + list(np.linspace(0.6, 3.0, 8))
    rs = [0.0] + list(r * np.sin(ang)) + [r] * 8
    V, T = _revolve(xs, rs)
    prof = S.profile_along(V, T, (0, 0, 0), (2.9, 0, 0), steps=96)
    assert S.crease_along(prof, skip_tip=False)["p"][0] < r       # what the skip prevents
    assert S.crease_along(prof) is None


def test_narrowest_wrist_ball():
    r, R, x_s = 0.5, 1.0, 3.0
    xc = x_s + math.sqrt(R * R - r * r)
    ang = np.linspace(math.asin(r / R), math.pi, 14)  # from where the ball meets the arm to its far pole
    xs = list(np.linspace(0, x_s, 8)) + list(xc - R * np.cos(ang[1:]))
    rs = [r] * 8 + list(R * np.sin(ang[1:]))
    rs[-1] = 0.0
    V, T = _revolve(xs, rs)
    tip = np.array([xc + R, 0, 0])
    prof = S.profile_along(V, T, (0, 0, 0), tip, steps=32)
    t, contrast = S.narrowest_along(prof, 0.45, 0.95)
    assert abs(t * tip[0] - x_s) < 0.5 * r
    assert contrast < 0.85
    # the same window without the ball's widening shows no clear narrowing
    _, contrast2 = S.narrowest_along(prof, 0.05, 0.5)
    assert contrast2 > 0.97


def test_bend_along():
    V, T = _bent_tube(r=0.2, length=3.0, bend=30.0)[0]
    s0 = 0.5
    h = math.radians(15)
    a = np.array([s0 * math.cos(h), s0 * math.sin(h), 0])
    b = np.array([2 * 3.0 * math.cos(h) - s0 * math.cos(h), s0 * math.sin(h), 0])
    prof = S.profile_along(V, T, a, b, steps=24)
    _, cen = S.profile_centroids(prof)
    assert len(cen) == 25
    ang, i, direction = S.bend_along(cen)
    assert abs(ang - 30.0) < 0.5
    assert abs(cen[i][0] - 3.0 * math.cos(h)) < 0.3    # at the corner
    assert direction[1] > 0.99                          # the corner points to +Y
    # a straight tube does not bend
    V, T = _cylinder(0.2, 0.0, 4.0, axis="x", n=9)
    _, cen = S.profile_centroids(S.profile_along(V, T, (0.3, 0, 0), (3.7, 0, 0)))
    assert S.bend_along(cen)[0] < 1e-6


def _bend_case():
    (V, T), _, _, knee = _bent_tube(r=0.2, length=3.0, bend=30.0)
    h = math.radians(15)
    a = np.array([0.5 * math.cos(h), 0.5 * math.sin(h), 0])
    b = np.array([6.0 * math.cos(h) - 0.5 * math.cos(h), 0.5 * math.sin(h), 0])
    return V, T, a, b, knee


def test_bend_along_corner_is_the_shape_not_the_samples():
    """On a clean corner several line pairs give the same angle. The corner comes from where
    the lines meet, so turning the mesh, renumbering it or losing samples does not move it."""
    V, T, a, b, knee = _bend_case()
    r = 0.2
    ang, i, _, corner = S.bend_along(S.profile_centroids(S.profile_along(V, T, a, b))[1],
                                             with_point=True)
    assert abs(ang - 30.0) < 0.5 and i == 12
    assert np.linalg.norm(corner - knee) < 0.05 * r
    for seed in range(6):
        R = _rot(seed)
        perm = np.random.default_rng(seed).permutation(len(V))
        inv = np.empty_like(perm)
        inv[perm] = np.arange(len(V))
        Vs, Ts = (V @ R.T)[perm], inv[T]
        prof = S.profile_along(Vs, Ts, a @ R.T, b @ R.T)
        _, cen = S.profile_centroids(prof)
        assert len(cen) == 25
        ang2, i2, dir2, corner2 = S.bend_along(cen, with_point=True)
        assert abs(ang2 - 30.0) < 0.5 and i2 == i
        assert np.linalg.norm(corner2 @ R - knee) < 0.05 * r
        assert (dir2 @ R)[1] > 0.99
    # samples lost round the corner (open slices) leave a gap; the corner stays put along the limb
    _, cen = S.profile_centroids(S.profile_along(V, T, a, b))
    gap = np.delete(cen, range(9, 16), axis=0)
    ang3, _, _, corner3 = S.bend_along(gap, with_point=True)
    assert abs(ang3 - 30.0) < 0.5
    assert abs(corner3[0] - knee[0]) < 0.5 * r


def test_bend_along_ignores_end_bulges_and_noise():
    """A one-sided bulge near the end (a wrist bone) or a little surface noise must not read as
    a bend past the 3.6 deg elbow rule."""
    r, L = 0.3, 2.4
    e1, e2 = np.array([0, 1.0, 0]), np.array([0, 0, 1.0])
    phi = 2 * np.pi * np.arange(K) / K
    rings = []
    for x in np.linspace(0, L, 25):
        c = np.array([x, 0, 0.0])
        rad = r * (1 + 2 * 0.08 * np.clip(np.cos(phi), 0, None)) if x > L - 0.25 else np.full(K, r)
        rings.append(c + rad[:, None] * (np.cos(phi)[:, None] * e1 + np.sin(phi)[:, None] * e2))
    V, T = _loft(rings)
    _, cen = S.profile_centroids(S.profile_along(V, T, (0.02, 0, 0), (L - 0.02, 0, 0)))
    assert S.bend_along(cen)[0] < 3.6
    for seed in range(5):
        V, T = _cylinder(0.25, 0.0, 4.0, axis="x", n=41)
        V = V + np.random.default_rng(seed).normal(scale=0.05 * 0.25, size=V.shape)
        _, cen = S.profile_centroids(S.profile_along(V, T, (0.3, 0, 0), (3.7, 0, 0)))
        assert S.bend_along(cen)[0] < 3.6


def test_area_jumps_both_ways():
    """A thin rod through a fat sleeve (a grip): one jump up, one jump down."""
    V, T = _revolve([0, 1, 2, 2, 3, 4, 4, 5, 6], [0.1, 0.1, 0.1, 0.3, 0.3, 0.3, 0.1, 0.1, 0.1])
    prof = S.profile_along(V, T, (0.05, 0, 0), (5.95, 0, 0), steps=24, ball=None)
    jumps = S.area_jumps(prof)
    assert [j["ratio"] > 1 for j in jumps] == [True, False]
    assert abs(jumps[0]["t"] * 5.9 + 0.05 - 2.0) < 0.15
    assert abs(jumps[1]["t"] * 5.9 + 0.05 - 4.0) < 0.15


def test_profile_is_deterministic_and_order_free():
    V, T = _box_arm()
    a, b = (3.4, 0, 0), (0, 0, 0)
    p1 = S.profile_along(V, T, a, b)
    rng = np.random.default_rng(7)
    T2 = T[rng.permutation(len(T))]
    T2 = np.roll(T2, 1, axis=1)                 # same winding, other first corner
    p2 = S.profile_along(V, T2, a, b)
    assert [s["r"] for s in p1] == [s["r"] for s in p2]
    for s1, s2 in zip(p1, p2):
        if s1["found"]:
            assert np.array_equal(s1["loop"]["pts"], s2["loop"]["pts"])
            assert np.array_equal(s1["loop"]["keys"], s2["loop"]["keys"])
    c1, c2 = S.crease_along(p1), S.crease_along(p2)
    assert (c1["t"], c1["reason"], c1["before"]) == (c2["t"], c2["reason"], c2["before"])


# ---------------------------------------------------------------------------------------
# rays

def test_ray_spans():
    d = (0, 1, 0)
    # alternating normals pair up
    ts = [1.0, 2.0, 3.0, 4.5]
    nr = [(0, -1, 0), (0, 1, 0), (0, -1, 0), (0, 1, 0)]
    assert S.ray_spans(ts, nr, d) == ([(1.0, 2.0), (3.0, 4.5)], True)
    # overlapping shells nest: entry, entry, exit, exit is one span
    nr = [(0, -1, 0), (0, -1, 0), (0, 1, 0), (0, 1, 0)]
    assert S.ray_spans(ts, nr, d) == ([(1.0, 4.5)], True)
    # normals that do not alternate (a flipped face) fall back to pairs in order
    ts = [1.0, 2.0, 3.0, 4.5, 6.0]
    nr = [(0, -1, 0), (0, 1, 0), (0, 1, 0), (0, -1, 0), (0, 1, 0)]
    assert S.ray_spans(ts, nr, d) == ([(1.0, 2.0), (3.0, 4.5)], False)
    assert S.ray_spans(ts, [(0, 1, 0)] * 5, d)[1] is False
    assert S.ray_spans([], np.zeros((0, 3)), d) == ([], True)
    # a ray from the front through a leg with a tail behind it: the FIRST span is the leg
    leg = _cylinder(0.3, 0.0, 2.0)
    tail = _cylinder(0.15, 0.5, 2.0, axis="y", centre=(0.0, 1.0))
    V, T = _join(leg, tail)
    o, d = np.array([0.0, -5.0, 1.0]), np.array([0.0, 1.0, 0.0])
    ts, nr = S.ray_hits(V, T, o, d)
    assert len(ts) == 4                          # each crossing once, though it runs along edges
    spans, by_normals = S.ray_spans(ts, nr, d)
    assert by_normals and len(spans) == 2
    assert spans[0] == pytest.approx((4.7, 5.3))
    assert spans[1] == pytest.approx((5.5, 7.0))


def test_inside_parity():
    H = 2.0
    V, T = _box((-1, -1, -1), (1, 1, 1))
    assert S.inside(V, T, (1 - 0.01 * H, 0.13, 0.07))
    assert not S.inside(V, T, (1 + 0.01 * H, 0.13, 0.07))
    assert S.inside(V, T, (0, 0, 0))             # every ray runs through a grid vertex
    assert not S.inside(V, T, (0, 0, 1 + 0.01 * H))
    # a sphere with a hole round +X: that ray slips out, the other two outvote it
    V, F = _icosphere(2)
    holed = F[V[F].mean(axis=1)[:, 0] < 0.85]
    assert len(S.ray_hits(V, holed, (0.1, 0.05, 0.02), (1, 0, 0))[0]) % 2 == 0
    assert S.inside(V, holed, (0.1, 0.05, 0.02))
    assert not S.inside(V, holed, (0.1, 0.05, 1.05))


def test_ray_hits_are_the_same_at_any_scale():
    V, T = _box((-1, -1, -1), (1, 1, 1))
    o, d = np.array([0.0, 0.0, -3.0]), np.array([0.0, 0.0, 1.0])
    for scale in (0.01, 100.0):
        ts, _ = S.ray_hits(V * scale, T, o * scale, d)
        assert ts / scale == pytest.approx([2.0, 4.0])


# ---------------------------------------------------------------------------------------
# trunk and feet

def test_trunk_axis_follows_the_trunk_not_the_tail():
    torso = _box((-0.5, -0.3, 1.0), (0.5, 0.3, 2.0), n=6)
    tail = _cylinder(0.1, 0.2, 1.6, axis="y", centre=(0.0, 1.5))
    V, T = _join(torso, tail)
    axis = S.trunk_axis(V, T, 1.1, 1.9, 0.0, steps=8)
    assert len(axis) == 9 and all(s["found"] for s in axis)
    cen = np.array([s["centroid"] for s in axis])
    assert np.abs(cen[:, :2]).max() < 1e-9
    assert all(s["width"] == pytest.approx(1.0) and s["depth"] == pytest.approx(0.6) for s in axis)


def test_contact_patch():
    foot = _box((0.1, -0.4, 0.0), (0.3, 0.1, 0.1), n=4)
    leg = _box((0.15, -0.05, 0.1), (0.25, 0.05, 1.0), n=4)
    V, _ = _join(foot, leg)
    side = V[:, 0] > 0
    cp = S.contact_patch(V, 0.0, side, 1.0)
    assert cp["toe"][1] == pytest.approx(-0.4) and cp["heel"][1] == pytest.approx(0.1)
    assert cp["left"][0] == pytest.approx(0.3) and cp["right"][0] == pytest.approx(0.1)
    assert (V[cp["idx"], 2] <= 0.01).all()
    assert S.contact_patch(V, 0.0, ~side, 1.0) is None
    # facing +Y swaps toe and heel
    cp = S.contact_patch(V, 0.0, side, 1.0, front=(0, 1, 0))
    assert cp["toe"][1] == pytest.approx(0.1)
