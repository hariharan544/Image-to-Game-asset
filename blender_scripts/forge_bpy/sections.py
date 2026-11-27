"""Slices and rays through a body mesh, in plain numpy (no Blender needed).

The joint guess, the cut rings and the held-prop cut ask the same few questions of a mesh:
what does a slice through it look like here, where does a limb widen into the body, where is
it narrowest, where does it bend, and is a point inside? This module answers them on plain
arrays, so every answer can be tested without Blender.

Principles:
  - Every threshold is a ratio of a measured size (a loop's radius, the body's size). The
    same body at x0.01 or x100 gives the same answer.
  - A vertex that lies exactly on a cutting plane counts as below it. A slice through a
    vertex then gives one clean loop, never a doubled one.
  - A slice is linked by the mesh edges it crosses, not by distances, so linking needs no
    tolerance. A loop that cannot close (an open mesh, a slice cut short) says so.
  - The ball that limits a slice keeps the slice's own segments that come near its centre.
    How big the faces are does not matter: a long face that passes close by still counts.
  - Loops nest. A loop is a hole only when it sits straight inside a solid loop and runs the
    other way. A limb inside a bracelet's hole is solid again.
  - A part taken away (mask_tris) leaves its root patched over, so the body's slices there
    still close and measure the body alone.
  - Nothing depends on how the mesh is turned: the default body size is measured from the
    surface's own centre, not from a box along the axes.
  - Ties go to the lowest index. No set or dict order decides a result.

Inputs are world-space arrays: V is (n, 3) float, T is (m, 3) int (tris(arr) builds it from
parts.MeshArrays). Where a direction matters, Forge's convention holds: Z is up, the
character faces -Y and its left is +X.
"""

from __future__ import annotations

import math

import numpy as np

JUMP = 1.8           # a limb meets the body where the slice area grows this many times at once
BALL_RADII = 3.0     # a slice looks this many local radii around its centre...
BALL_SIZE = 0.15     # ...or this share of the body's size, whichever is larger
PLATEAU = 0.03       # radii within 3% of the smallest count as one straight stretch
BEND_SHARE = 0.25    # each line bend_along fits holds at least a quarter of the points (and 3)
BEND_TIE = 0.02      # bend angles within 2% of the largest count as the same bend
CONTACT_BAND = 0.01  # a foot touches the ground within this share of the body's height
AUTO = "auto"        # profile_along: the ball follows the limb's own radius
_SLACK = 1e-9        # a ray along a shared edge hits both triangles; the two hits merge after
_MERGE = 1e-9        # hits closer than this share of the body's size are one hit
_RAYS = ((1.0, 0.0, 0.0), (-1.0, 0.0, 0.0), (0.0, 1.0, 0.0))


# ---------------------------------------------------------------------------------------
# small helpers

def _unit(v) -> np.ndarray:
    v = np.asarray(v, float)
    ln = float(np.linalg.norm(v))
    return v / ln if ln > 0 else np.zeros_like(v)


def _basis(n: np.ndarray):
    """Two unit vectors that span the plane with unit normal n, with u x v = n. The choice
    depends on n only, so the same plane always gets the same frame."""
    e = np.zeros(3)
    e[int(np.argmin(np.abs(n)))] = 1.0
    u = _unit(np.cross(n, e))
    return u, np.cross(n, u)


def _side(P: np.ndarray, p: np.ndarray, n: np.ndarray) -> np.ndarray:
    """Signed distance of points from the plane (p, n). Written out term by term, so a vertex
    gets the same value whichever triangle asks."""
    return (P[:, 0] - p[0]) * n[0] + (P[:, 1] - p[1]) * n[1] + (P[:, 2] - p[2]) * n[2]


def _dist2(P: np.ndarray, p: np.ndarray) -> np.ndarray:
    """Squared distance of points from p, one value per point."""
    return (P[:, 0] - p[0]) ** 2 + (P[:, 1] - p[1]) ** 2 + (P[:, 2] - p[2]) ** 2


def _corner_min_max(x: np.ndarray, T: np.ndarray):
    """Smallest and largest of a per-vertex value over each triangle's three corners
    (elementwise: much faster than a min over rows of three)."""
    a, b, c = x[T[:, 0]], x[T[:, 1]], x[T[:, 2]]
    return np.minimum(np.minimum(a, b), c), np.maximum(np.maximum(a, b), c)


def _in_polygon(x: np.ndarray, y: np.ndarray, px: np.ndarray, py: np.ndarray) -> np.ndarray:
    """Even-odd test: which of the points (px, py) lie inside the closed polygon (x, y)."""
    x1, y1 = np.roll(x, -1), np.roll(y, -1)
    Y = py[:, None]
    across = (y[None, :] > Y) != (y1[None, :] > Y)
    with np.errstate(divide="ignore", invalid="ignore"):
        xc = x[None, :] + (Y - y[None, :]) * ((x1 - x) / (y1 - y))[None, :]
    return ((across & (px[:, None] < xc)).sum(1) % 2) == 1


class _Slabs:
    """Each triangle's extent along a direction, measured once, so a run of parallel slices
    hands each slice only the triangles that reach its plane. The margin only widens this
    first pick; cut() decides exactly which triangles cross."""

    def __init__(self, V, T, a, n):
        self.T = T
        if len(T):
            self.lo, self.hi = _corner_min_max(_side(V, a, n), T)
            self.pad = 1e-7 * max(float(np.abs(self.lo).max()), float(np.abs(self.hi).max()))

    def near(self, s: float) -> np.ndarray:
        """The triangles that reach the plane at distance s along the direction."""
        if not len(self.T):
            return self.T
        pad = self.pad + 1e-7 * abs(s)
        return self.T[(self.lo <= s + pad) & (self.hi >= s - pad)]


def body_size(V, T=None) -> float:
    """A size of the mesh that stays the same when the mesh turns: twice the largest distance
    of a vertex T uses from the surface's area centroid. Without T (or with no area), all of
    V and their plain mean. For an upright body it comes out close to its height.

    A box along the axes would not do: the same mesh turned on its side has another box, so
    every ball and every result built on it would change with the turn."""
    V = np.asarray(V, float)
    c = None
    if T is not None and len(T):
        T = np.asarray(T, np.int64).reshape(-1, 3)
        A, B, C = V[T[:, 0]], V[T[:, 1]], V[T[:, 2]]
        w = 0.5 * np.linalg.norm(np.cross(B - A, C - A), axis=1)
        V = V[np.unique(T)]
        if w.sum() > 0:
            c = (w[:, None] * (A + B + C)).sum(axis=0) / (3.0 * w.sum())
    if not len(V):
        return 0.0
    if c is None:
        c = V.mean(axis=0)
    return 2.0 * float(np.sqrt(_dist2(V, c).max()))


def ball_radius(r_guess, H) -> float:
    """How far around its centre a slice looks: 3 local radii, or 0.15 of the body's size
    when that is more. Without a radius guess, 0.15 of the body's size."""
    return max(BALL_RADII * float(r_guess or 0.0), BALL_SIZE * float(H))


# ---------------------------------------------------------------------------------------
# triangles

def tris(arr, with_poly: bool = False):
    """Fan triangles of the polygons of a parts.MeshArrays (anything with ls, lt and lv).

    Polygon i with corners c0..ck gives (c0, cj, cj+1) for j = 1..k-1, in polygon order, so
    the faces keep their winding. With with_poly, also returns the polygon of each triangle."""
    ls = np.asarray(arr.ls, np.int64)
    lt = np.asarray(arr.lt, np.int64)
    lv = np.asarray(arr.lv, np.int64)
    k = np.maximum(lt - 2, 0)
    total = int(k.sum())
    poly = np.repeat(np.arange(len(lt), dtype=np.int64), k)
    j = np.arange(total, dtype=np.int64) - np.repeat(np.cumsum(k) - k, k)
    base = ls[poly]
    T = np.stack([lv[base], lv[base + j + 1], lv[base + j + 2]], axis=1) if total else \
        np.zeros((0, 3), np.int64)
    return (T, poly) if with_poly else T


def mask_tris(T, excluded, with_caps: bool = False) -> np.ndarray:
    """The triangles left when the excluded vertices are taken away (pass 2 of the joint
    guess), with the openings this leaves patched over.

    Every triangle with an excluded corner is dropped. A part that is its own shell just goes.
    A part that grows out of the body (an AI mesh is one fused surface) leaves an opening at
    its root; the opening is patched with triangles between its own border vertices, so a
    slice of the body there closes with a straight run across the root, as if the part had
    never been there. The patch needs no new vertices. Holes the mesh had before stay open.

    `excluded` is a bool mask over the vertices (a shorter mask counts the rest as kept), or a
    list of vertex ids. With with_caps, also returns a bool per triangle: True for a patch."""
    T = np.asarray(T, np.int64).reshape(-1, 3)
    ex = np.asarray(excluded)
    if not len(T):
        return (T, np.zeros(0, bool)) if with_caps else T
    size = int(T.max()) + 1
    m = np.zeros(size, bool)
    if ex.dtype == bool:
        ex = ex.ravel()[:size]
        m[:len(ex)] = ex
    else:
        ids = ex.astype(np.int64).ravel()
        m[ids[(ids >= 0) & (ids < size)]] = True
    drop = m[T[:, 0]] | m[T[:, 1]] | m[T[:, 2]]
    keep = T[~drop]
    caps = _patch_openings(keep, T[drop], size)
    out = np.vstack([keep, caps]) if len(caps) else keep
    if with_caps:
        return out, np.arange(len(out)) >= len(keep)
    return out


def _patch_openings(keep: np.ndarray, gone: np.ndarray, size: int) -> np.ndarray:
    """Triangles that close the openings left where `gone` met `keep`.

    An edge is on such an opening when one kept triangle and at least one dropped triangle
    share it. The patch runs each of those edges the other way, so it winds like the faces
    round it. Each opening is stitched like a zip, from both ends of its border toward the
    middle, which gives a flat patch across a flat ring. Walks start at the lowest vertex id."""
    empty = np.zeros((0, 3), np.int64)
    if not len(keep) or not len(gone):
        return empty

    def half_edges(T):
        return np.concatenate([T[:, [0, 1]], T[:, [1, 2]], T[:, [2, 0]]])

    hk, hg = half_edges(keep), half_edges(gone)
    code_k = np.minimum(hk[:, 0], hk[:, 1]) * size + np.maximum(hk[:, 0], hk[:, 1])
    code_g = np.minimum(hg[:, 0], hg[:, 1]) * size + np.maximum(hg[:, 0], hg[:, 1])
    _, inv, cnt = np.unique(code_k, return_inverse=True, return_counts=True)
    border = (cnt[inv.reshape(-1)] == 1) & np.isin(code_k, code_g)
    if not border.any():
        return empty
    # the patch's edges run against the kept faces' edges, sorted by (start, end)
    e = hk[border][:, ::-1]
    e = e[np.lexsort((e[:, 1], e[:, 0]))]
    starts = e[:, 0]
    used = np.zeros(len(e), bool)
    tris_out = []
    for k0 in range(len(e)):
        if used[k0]:
            continue
        ring, k = [int(e[k0, 0])], k0
        while True:
            used[k] = True
            v = int(e[k, 1])
            if v == ring[0]:
                break
            ring.append(v)
            lo = int(np.searchsorted(starts, v, "left"))
            hi = int(np.searchsorted(starts, v, "right"))
            free = [j for j in range(lo, hi) if not used[j]]
            if not free:
                ring = []            # the border does not come back round: leave it open
                break
            k = free[0]
        if len(ring) < 3:
            continue
        r = int(np.argmin(ring))
        ring = ring[r:] + ring[:r]
        i, j, step = 0, len(ring) - 1, 0
        while j - i > 1:
            if step % 2 == 0:
                tris_out.append((ring[i], ring[i + 1], ring[j]))
                i += 1
            else:
                tris_out.append((ring[i], ring[j - 1], ring[j]))
                j -= 1
            step += 1
    return np.array(tris_out, np.int64).reshape(-1, 3)


# ---------------------------------------------------------------------------------------
# slices

def cut(V, T, p, n, ball=None, with_tris: bool = False):
    """Where the plane through p with normal n crosses the triangles.

    Returns (segs, keys). segs is (k, 2, 3): one segment per crossed triangle. keys is
    (k, 2, 2): the mesh edge (low vertex id, high vertex id) that each end lies on. Two
    triangles that share an edge share its key and its point exactly; loops() links on that.

    With ball, only the segments that come within `ball` of p are kept (the nearest point of
    the segment counts, not the triangle's corners), so a slice that reaches further than the
    ball comes out open, however big or small the faces are. A vertex exactly on the plane
    counts as below it. When the faces wind outward, each segment runs counter-clockwise
    around solid material as seen from the side n points to. With with_tris, also returns the
    triangle of each segment."""
    V = np.asarray(V, float)
    T = np.asarray(T, np.int64).reshape(-1, 3)
    p = np.asarray(p, float)
    n = _unit(n)
    segs, keys, tid = _cut(V, T, _valid(T), p, n)
    if ball is not None and len(segs):
        keep = _seg_dist2(segs, p) <= float(ball) ** 2
        segs, keys, tid = segs[keep], keys[keep], tid[keep]
    return (segs, keys, tid) if with_tris else (segs, keys)


def _valid(T: np.ndarray) -> np.ndarray:
    """Ids of the triangles with three different corners."""
    return np.nonzero((T[:, 0] != T[:, 1]) & (T[:, 1] != T[:, 2]) & (T[:, 2] != T[:, 0]))[0]


def _seg_dist2(segs: np.ndarray, p: np.ndarray) -> np.ndarray:
    """Squared distance from p to the nearest point of each segment."""
    A, D = segs[:, 0], segs[:, 1] - segs[:, 0]
    L2 = (D * D).sum(axis=1)
    w = ((p - A) * D).sum(axis=1)
    t = np.clip(np.divide(w, L2, out=np.zeros_like(w), where=L2 > 0), 0.0, 1.0)
    return _dist2(A + t[:, None] * D, p)


def _vertex_values(V, Tt, f):
    """f(points) for the vertices the triangles Tt use, and a lookup by vertex id. A small
    piece of a big mesh only pays for its own vertices; a big piece skips the sort."""
    if 3 * len(Tt) >= len(V):
        vals = f(V)
        return lambda ids: vals[ids]
    vid = np.unique(Tt)
    vals = f(V[vid])
    return lambda ids: vals[np.searchsorted(vid, ids)]


def _cut(V, T, tid, p, n):
    empty = (np.zeros((0, 2, 3)), np.zeros((0, 2, 2), np.int64), np.zeros(0, np.int64))
    if not len(tid) or not n.any():
        return empty
    Tt = T[tid]
    get = _vertex_values(V, Tt, lambda P: _side(P, p, n))
    u0, u1, u2 = get(Tt[:, 0]) > 0, get(Tt[:, 1]) > 0, get(Tt[:, 2]) > 0
    cnt = u0.astype(np.int8) + u1 + u2
    hit = (cnt == 1) | (cnt == 2)
    if not hit.any():
        return empty
    Tt, tid = Tt[hit], tid[hit]
    up = np.stack([u0[hit], u1[hit], u2[hit]], axis=1)
    # The lone corner is the one on its own side. With corners (L, A, B) in winding order,
    # the slice leaves through edge L-A and comes back through edge B-L when L is above.
    lone_up = up.sum(axis=1) == 1
    lone = np.where(lone_up, np.argmax(up, axis=1), np.argmin(up, axis=1))
    r = np.arange(len(Tt))
    L, A, B = Tt[r, lone], Tt[r, (lone + 1) % 3], Tt[r, (lone + 2) % 3]
    e_la = np.sort(np.stack([L, A], axis=1), axis=1)
    e_bl = np.sort(np.stack([B, L], axis=1), axis=1)
    keys = np.stack([np.where(lone_up[:, None], e_la, e_bl),
                     np.where(lone_up[:, None], e_bl, e_la)], axis=1)
    # one crossing point per mesh edge, measured from its lower end, so a vertex on the
    # plane gives exactly its own position
    ek = keys.reshape(-1, 2)
    code = ek[:, 0] * len(V) + ek[:, 1]
    _, first, back = np.unique(code, return_index=True, return_inverse=True)
    ue = ek[first]
    dv = get(ue)
    a_up = dv[:, 0] > 0
    hi = np.where(a_up, ue[:, 0], ue[:, 1])
    lo = np.where(a_up, ue[:, 1], ue[:, 0])
    dh = np.where(a_up, dv[:, 0], dv[:, 1])
    dl = np.where(a_up, dv[:, 1], dv[:, 0])
    s = dl / (dl - dh)
    X = V[lo] + s[:, None] * (V[hi] - V[lo])
    return X[back.reshape(-1)].reshape(-1, 2, 3), keys, tid


def loops(segs, keys) -> list:
    """Links cut() segments that share an edge key into loops.

    Each loop is {"pts": (q, 3), "keys": (q, 2), "closed": bool}. A ring that comes back to
    its start through plain edges is closed. A chain that stops at an open edge, at the edge
    of a ball, or at a non-manifold edge (more than two triangles) is open. Repeated points
    (a slice through a vertex) are kept once. Loops run the way most of their segments run;
    a ring starts at its lowest edge key, and the loops come sorted by their lowest key."""
    segs = np.asarray(segs, float).reshape(-1, 2, 3)
    keys = np.asarray(keys, np.int64).reshape(-1, 2, 2)
    if not len(segs):
        return []
    flat = keys.reshape(-1, 2)
    base = int(flat.max()) + 1
    _, first, node = np.unique(flat[:, 0] * base + flat[:, 1], return_index=True, return_inverse=True)
    node = node.reshape(-1, 2)
    pts = segs.reshape(-1, 3)[first]
    nkey = flat[first]
    ends = node.tolist()
    inc: list = [[] for _ in range(len(first))]
    for s, (a, b) in enumerate(ends):
        if a != b:
            inc[a].append(s)
            inc[b].append(s)
    deg = [len(x) for x in inc]
    used = [a == b for a, b in ends]
    seglen = np.linalg.norm(segs[:, 1] - segs[:, 0], axis=1).tolist()

    def walk(u: int, s: int):
        start, nodes, vote = u, [u], 0.0
        while True:
            used[s] = True
            a, b = ends[s]
            v = b if a == u else a
            vote += seglen[s] if a == u else -seglen[s]
            if v == start:
                return nodes, vote, deg[start] == 2
            nodes.append(v)
            if deg[v] != 2:
                return nodes, vote, False
            nxt = [t for t in inc[v] if not used[t]]
            if not nxt:
                return nodes, vote, False
            u, s = v, nxt[0]

    chains = []
    for u in range(len(first)):          # chains from loose ends and branch points first
        if deg[u] != 2:
            for s in inc[u]:
                if not used[s]:
                    chains.append(walk(u, s))
    for s in range(len(ends)):           # what is left goes round in rings
        if not used[s]:
            chains.append(walk(ends[s][0], s))

    out = []
    for nodes, vote, closed in chains:
        if closed:
            k = int(np.argmin(nodes))
            nodes = nodes[k:] + nodes[:k]
            if vote < 0:
                nodes = nodes[:1] + nodes[:0:-1]
        elif vote < 0:
            nodes = nodes[::-1]
        idx = np.asarray(nodes, np.int64)
        P = pts[idx]
        keep = np.ones(len(P), bool)
        keep[1:] = (P[1:] != P[:-1]).any(axis=1)
        idx, P = idx[keep], P[keep]
        if closed and len(P) > 1 and (P[-1] == P[0]).all():
            idx, P = idx[:-1], P[:-1]
        if len(P) < (3 if closed else 2):
            continue
        out.append((int(idx.min()), {"pts": P, "keys": nkey[idx], "closed": bool(closed)}))
    out.sort(key=lambda x: x[0])
    return [lp for _, lp in out]


def loop_props(loop, n=None) -> dict:
    """What a loop measures.

    `loop` is a loops() dict or a (q, 3) array of points (taken as closed). n is the slice
    normal; without it the loop's own vector area gives the plane, which suits loops that
    are not flat (a crease-snapped cut ring). An open loop is measured as if its two ends
    were joined.

    Returns:
      vector_area  half the sum of p_i x p_i+1: its length is the area seen along it
      normal       the plane normal used (n, or the vector area direction)
      signed_area  area seen from the side the normal points to (negative when the loop
                   runs clockwise there)
      area, r      area, and r = sqrt(area / pi): the radius of a disc with that area
      centroid     the area centroid
      perimeter    length of the loop (without the closing gap of an open loop)
      roundness    4 pi area / perimeter^2: 1 for a circle, small for a slot or a ragged ring
      aspect       sqrt of the ratio of the area's two principal second moments: 1 for a
                   disc, a/b for an a-by-b ellipse (the area's PCA, not the points')
      major        the long direction of the area
      off_plane    rms distance of the points from the plane, as a share of r
      origin, u, v the 2D frame of the plane (u x v = normal)
      contains     contains(point) -> bool for a 3D point (projected) or a 2D point in the
                   (origin, u, v) frame; also takes (k, 3) or (k, 2) arrays"""
    if isinstance(loop, dict):
        P = np.asarray(loop["pts"], float)
        closed = bool(loop.get("closed", True))
    else:
        P = np.asarray(loop, float)
        closed = True
    c0 = P.mean(axis=0) if len(P) else np.zeros(3)
    Q = P - c0
    va = 0.5 * np.cross(Q, np.roll(Q, -1, axis=0)).sum(axis=0) if len(P) else np.zeros(3)
    if n is not None and np.any(n):
        nrm = _unit(n)
    else:
        nrm = _unit(va) if np.any(va) else np.array([0.0, 0.0, 1.0])
    u, v = _basis(nrm)
    x, y = Q @ u, Q @ v
    x1, y1 = np.roll(x, -1), np.roll(y, -1)
    cr = x * y1 - x1 * y
    a2 = float(cr.sum()) / 2.0
    area = abs(a2)
    if a2 != 0.0:
        cx = float(((x + x1) * cr).sum()) / (6.0 * a2)
        cy = float(((y + y1) * cr).sum()) / (6.0 * a2)
        sxx = float((cr * (x * x + x * x1 + x1 * x1)).sum()) / 12.0 / a2 - cx * cx
        syy = float((cr * (y * y + y * y1 + y1 * y1)).sum()) / 12.0 / a2 - cy * cy
        sxy = float((cr * (x * y1 + 2 * x * y + 2 * x1 * y1 + x1 * y)).sum()) / 24.0 / a2 - cx * cy
        lam, vec = np.linalg.eigh(np.array([[sxx, sxy], [sxy, syy]]))
        aspect = math.sqrt(lam[1] / lam[0]) if lam[0] > 0 else math.inf
        mj = vec[0, 1] * u + vec[1, 1] * v
        major = mj if mj[int(np.argmax(np.abs(mj)))] >= 0 else -mj
    else:
        cx = cy = 0.0
        aspect, major = math.inf, u.copy()
    r = math.sqrt(area / math.pi)
    steps = np.linalg.norm(np.roll(P, -1, axis=0) - P, axis=1) if len(P) else np.zeros(0)
    perimeter = float(steps.sum() if closed else steps[:-1].sum())
    off = float(np.sqrt(np.mean((Q @ nrm) ** 2))) if len(P) else 0.0

    def contains(pt):
        pt = np.asarray(pt, float)
        one = pt.ndim == 1
        pt = np.atleast_2d(pt)
        if pt.shape[1] == 3:
            w = pt - c0
            px, py = w @ u, w @ v
        else:
            px, py = pt[:, 0], pt[:, 1]
        res = _in_polygon(x, y, px, py) if len(P) >= 3 else np.zeros(len(pt), bool)
        return bool(res[0]) if one else res

    return {
        "vector_area": va, "normal": nrm, "signed_area": a2, "area": area, "r": r,
        "centroid": c0 + cx * u + cy * v, "perimeter": perimeter,
        "roundness": 4.0 * math.pi * area / perimeter ** 2 if perimeter > 0 else 0.0,
        "aspect": aspect, "major": major, "off_plane": off / r if r > 0 else 0.0,
        "origin": c0, "u": u, "v": v, "contains": contains,
    }


def section(V, T, p, n, ball=None) -> list:
    """Every loop of the slice through p with normal n, each loops() dict merged with its
    loop_props(), a "hole" flag and a "parent".

    Closed loops nest. A loop's parent is the smallest closed loop that holds it (most of its
    points lie inside), as an index into this list, or None. A loop is a hole when its parent
    is solid and it runs the other way: the inner wall of a hollow tube. Inside a hole a loop
    is solid again, so an arm through a bracelet stays an arm. Loops are settled from the
    biggest down, so a parent is always settled first; ties go to the lower index. Open loops
    take no part in the nesting."""
    out = [dict(lp, **loop_props(lp, n), hole=False, parent=None)
           for lp in loops(*cut(V, T, p, n, ball))]
    ring = [i for i, lp in enumerate(out) if lp["closed"] and lp["signed_area"] != 0.0]
    ring.sort(key=lambda i: (-out[i]["area"], i))
    # Boxes only skip loops that are far apart. Every point lies on the plane, so each box is
    # widened by a share of its own size: rounding along the normal must not decide.
    box = {}
    for i in ring:
        lo, hi = out[i]["pts"].min(axis=0), out[i]["pts"].max(axis=0)
        pad = 1e-6 * float((hi - lo).max())
        box[i] = (lo - pad, hi + pad)
    for k, i in enumerate(ring):
        P = out[i]["pts"]
        q = P[np.unique(np.linspace(0, len(P) - 1, min(len(P), 16)).astype(np.int64))]
        mid = 0.5 * (P.min(axis=0) + P.max(axis=0))
        for j in reversed(ring[:k]):                 # smallest first: the first that holds it
            if out[j]["area"] <= out[i]["area"]:
                continue
            if not ((box[j][0] <= mid).all() and (mid <= box[j][1]).all()):
                continue
            if 2 * int(np.count_nonzero(out[j]["contains"](q))) > len(q):
                out[i]["parent"] = j
                break
        j = out[i]["parent"]
        out[i]["hole"] = bool(j is not None and not out[j]["hole"]
                              and (out[i]["signed_area"] > 0) != (out[j]["signed_area"] > 0))
    return out


def loop_at(V, T, p, n, ball=None):
    """The loop of the slice through p (normal n) that p belongs to, and how many loops the
    slice has (holes not counted).

    The loop is the smallest closed loop around p; else the smallest open one around p
    (measured as if closed); else, when p is in none (a bent limb leaves a straight axis),
    the loop whose centroid is nearest, closed ones first. It is a section() dict plus
      inside     p is in it
      enclosing  the areas of the other loops whose material is round p, biggest first: a
                 body the limb runs into, or a sleeve over it. A loop with p in its hole (a
                 bracelet round the limb) does not count.
      n_inside   1 when p is in the loop, plus one per enclosing loop: more than one means
                 the limb runs inside another shell here.
    (None, 0) when the slice is empty."""
    sec = section(V, T, p, n, ball)
    solid = [k for k, lp in enumerate(sec) if not lp["hole"]]
    if not solid:
        return None, 0
    p = np.asarray(p, float)
    ins = [bool(sec[k]["contains"](p)) for k in solid]
    pick = [m for m in range(len(solid)) if ins[m]]
    if pick:
        m = min(pick, key=lambda m: (not sec[solid[m]]["closed"], sec[solid[m]]["area"], m))
    else:
        d = [float(np.linalg.norm(sec[k]["centroid"] - p)) for k in solid]
        m = min(range(len(solid)), key=lambda m: (not sec[solid[m]]["closed"], d[m], m))
    # a solid loop whose hole holds p has its material round the hole, not round p
    held = {lp["parent"] for lp in sec if lp["hole"] and lp["contains"](p)}
    enclosing = sorted((sec[solid[o]]["area"] for o in pick if o != m and solid[o] not in held),
                       reverse=True)
    lp = dict(sec[solid[m]], inside=ins[m], enclosing=enclosing,
              n_inside=int(ins[m]) + len(enclosing))
    return lp, len(solid)


# ---------------------------------------------------------------------------------------
# along an axis

def profile_along(V, T, a, b, steps: int = 24, ball=AUTO, H=None, r_guess=None) -> list:
    """Slices across the segment a -> b, at t = 0, 1/steps, ..., 1, each with normal (b - a).

    Each sample is {t, s (distance from a), p (the point on the axis), found, closed, inside,
    n_inside, enclosing, n_loops, end, r, area, centroid, loop, ball}; `loop` is the loop_at()
    dict. `end` is True when the plane misses the mesh altogether (past its end, or in a gap
    between shells), as against a slice that only runs out of the ball.

    ball: a number limits every slice to that radius; None does not limit; AUTO (the
    default) uses ball_radius(r_guess, H) on every slice, where r_guess follows the last
    closed loop around the axis; before any loop gives a radius that is 0.15 H. H is the
    body's size (its height when upright); it defaults to body_size(), which does not change
    when the mesh turns."""
    V = np.asarray(V, float)
    T = np.asarray(T, np.int64).reshape(-1, 3)
    a, b = np.asarray(a, float), np.asarray(b, float)
    ax = b - a
    length = float(np.linalg.norm(ax))
    if length == 0.0 or steps < 1:
        return []
    n = ax / length
    auto = isinstance(ball, str)
    if auto and H is None:
        H = body_size(V, T)
    slabs = _Slabs(V, T, a, n)
    out = []
    for i in range(steps + 1):
        t = i / steps
        p = a + t * ax
        bl = ball_radius(r_guess, H) if auto else ball
        near = slabs.near(t * length)
        lp, nl = loop_at(V, near, p, n, bl)
        end = lp is None and not len(_cut(V, near, _valid(near), p, n)[0])
        smp = {"t": t, "s": t * length, "p": p, "found": lp is not None, "closed": bool(lp and lp["closed"]),
               "inside": bool(lp and lp["inside"]), "n_inside": lp["n_inside"] if lp else 0,
               "enclosing": lp["enclosing"] if lp else [], "n_loops": nl, "end": bool(end),
               "r": lp["r"] if lp else 0.0, "area": lp["area"] if lp else 0.0,
               "centroid": lp["centroid"] if lp else None, "loop": lp, "ball": bl}
        if auto and smp["closed"] and smp["inside"] and smp["r"] > 0:
            r_guess = smp["r"]
        out.append(smp)
    return out


def profile_centroids(profile: list):
    """(t, centroids) of the samples that found a closed loop, in order: (k,) and (k, 3).
    Works on profile_along() and trunk_axis() samples alike."""
    good = [s for s in profile if s["found"] and s["closed"]]
    return (np.array([s["t"] for s in good], float),
            np.array([s["centroid"] for s in good], float).reshape(-1, 3))


def _in_bigger_shell(smp: dict, area: float, jump: float) -> float:
    """How many times the biggest loop round the sample's axis point outgrows `area`, when
    that is more than `jump` times; else 0. A sleeve over a limb is only a little bigger and
    does not count; a body the limb runs into is many times bigger."""
    big = max(smp.get("enclosing") or [0.0])
    if area > 0 and big > jump * area:
        return big / area
    return 0.0


def crease_along(profile: list, jump: float = JUMP, skip_tip: bool = True, reverse: bool = False):
    """Where a limb merges into the body: walking the profile from its first sample (build it
    from the limb's free end toward the body; reverse walks from the last), the first place
    where
      - the slice area grows more than `jump` times from one sample to the next ("jump"),
      - the loop stops being closed: it runs out of the ball ("open"),
      - or the axis runs inside another shell more than `jump` times the limb's area: an arm
        that is its own shell, pushed into the body ("split"). A shell only a little bigger
        (a sleeve, armour, cloth over the limb) does not count; the walk keeps to the limb.
    The 1.8 matches the measured armpit and groin jumps; it is a ratio, not a size.

    A slice that misses the mesh altogether (past the limb's end, or a gap between shells)
    is skipped, so a limb that just ends has no crease.

    The walk starts at the first closed loop. With skip_tip it also skips the samples
    closer to that first loop than their own radius: a rounded tip grows fast too.

    Works on profile_along() samples; trunk_axis() samples work too (z stands in for s).

    Returns {t, p, before, after, reason, ratio} or None. t (and p) lie halfway between the
    last limb sample (index `before`) and the first sample past the crease (`after`)."""
    order = range(len(profile) - 1, -1, -1) if reverse else range(len(profile))
    prev, tip = None, None
    for i in order:
        smp = profile[i]
        good = smp["found"] and smp["closed"]
        if smp.get("end"):
            continue
        if prev is None:
            if not good or _in_bigger_shell(smp, smp["area"], jump):
                continue
            if skip_tip:
                s = smp.get("s", smp.get("z", smp["t"]))
                if tip is None:
                    tip = s
                if abs(s - tip) < smp["r"]:
                    continue
            prev = i
            continue
        last = profile[prev]
        ratio = smp["area"] / last["area"] if last["area"] > 0 else math.inf
        shell = _in_bigger_shell(smp, last["area"], jump) if good else 0.0
        why = ("open" if not good else "split" if shell else "jump" if ratio > jump else None)
        if why:
            if why == "split":
                ratio = shell
            return {"t": 0.5 * (last["t"] + smp["t"]), "p": 0.5 * (last["p"] + smp["p"]),
                    "before": prev, "after": i, "reason": why, "ratio": ratio}
        prev = i
    return None


def find_crease(V, T, a, b, steps: int = 24, ball=AUTO, H=None, jump: float = JUMP, refine: int = 2):
    """crease_along() on profile_along(a, b), then narrowed down: each round slices the gap
    between the two samples around the crease 8 times finer. Returns the crease dict with
    the refined t and p, plus r and centroid of the last limb loop before the crease (where
    the limb itself is still measured, not the merged slice), or None without a crease."""
    if isinstance(ball, str) and H is None:
        H = body_size(V, T)
    prof = profile_along(V, T, a, b, steps, ball, H)
    c = crease_along(prof, jump)
    if c is None:
        return None
    a, b = np.asarray(a, float), np.asarray(b, float)
    t0, t1 = prof[c["before"]]["t"], prof[c["after"]]["t"]
    limb = prof[c["before"]]
    for _ in range(max(int(refine), 0)):
        sub = profile_along(V, T, a + t0 * (b - a), a + t1 * (b - a), 8, ball, H, r_guess=limb["r"])
        cs = crease_along(sub, jump, skip_tip=False)
        if cs is None:
            break
        t0, t1 = t0 + (t1 - t0) * sub[cs["before"]]["t"], t0 + (t1 - t0) * sub[cs["after"]]["t"]
        limb = sub[cs["before"]]
        c = dict(c, reason=cs["reason"], ratio=cs["ratio"])
    t = 0.5 * (t0 + t1)
    return dict(c, t=t, p=a + t * (b - a), r=limb["r"], centroid=limb["centroid"])


def area_jumps(profile: list, jump: float = JUMP) -> list:
    """Every pair of neighbouring samples (both closed) whose slice area changes more than
    `jump` times, either way: [{t, before, after, ratio}], ratio = later area / earlier area.
    A grip shows as a jump up where the hand starts and a jump down where it ends."""
    out = []
    for i in range(len(profile) - 1):
        s0, s1 = profile[i], profile[i + 1]
        if not (s0["found"] and s0["closed"] and s1["found"] and s1["closed"]):
            continue
        if s0["area"] <= 0 or s1["area"] <= 0:
            continue
        ratio = s1["area"] / s0["area"]
        if ratio > jump or ratio < 1.0 / jump:
            out.append({"t": 0.5 * (s0["t"] + s1["t"]), "before": i, "after": i + 1, "ratio": ratio})
    return out


def narrowest_along(profile: list, t0: float = 0.0, t1: float = 1.0):
    """(t_min, contrast): where the closed loops between t0 and t1 are thinnest, and
    contrast = r_min / median r over that stretch (small means a clear narrowing).

    When the thinnest part is a straight stretch (radii within 3% of the smallest), t_min is
    the end of it where the shape widens more: a wrist sits where the hand begins, not in
    the middle of the forearm. (None, 1.0) with fewer than 3 loops."""
    lo, hi = min(t0, t1), max(t0, t1)
    idx = [i for i, s in enumerate(profile)
           if s["found"] and s["closed"] and s["r"] > 0 and lo <= s["t"] <= hi]
    if len(idx) < 3:
        return None, 1.0
    r = np.array([profile[i]["r"] for i in idx])
    k = int(np.argmin(r))
    contrast = float(r[k] / np.median(r))
    near = r <= r[k] * (1.0 + PLATEAU)
    s, e = k, k
    while s > 0 and near[s - 1]:
        s -= 1
    while e < len(r) - 1 and near[e + 1]:
        e += 1
    if e > s:
        left = r[s - 1] if s > 0 else -math.inf
        right = r[e + 1] if e < len(r) - 1 else -math.inf
        k = e if right > left else s if left > right else (s + e) // 2
    return profile[idx[k]]["t"], contrast


def _direction(P: np.ndarray) -> np.ndarray:
    """Best-fit line direction of points, pointing from the first point toward the last."""
    _, _, vt = np.linalg.svd(P - P.mean(axis=0), full_matrices=False)
    d = vt[0]
    return d if (P[-1] - P[0]) @ d >= 0 else -d


def bend_along(centroids, with_point: bool = False):
    """(max_angle_deg, index, direction) of a polyline of loop centroids.

    For an inner point i, a line is fitted to the points before i and another to the points
    after it (i itself is left out: a slice right at a joint mixes both sides). Each line
    fits at least a quarter of the points, and at least 3, so a bulge or a little noise near
    an end cannot pass for a bend. The bend is the largest angle between such a pair of
    lines. On a clean corner several i give the same angle: the angles within 2% of the
    largest that run on from it count as one bend, and the middle one of that run is used.

    The corner is where the two lines of that pair meet, brought to the nearest point of the
    polyline (a smooth bend's lines meet outside it); index is the centroid nearest that
    corner. So the answer comes from the shape, not from which samples happen to exist.
    direction is the unit vector the corner points to, away from the straight line between
    the ends. With with_point, the corner point is returned fourth.

    (0.0, None, zero vector) with fewer than 7 points or a straight line."""
    P = np.asarray(centroids, float).reshape(-1, 3)
    none = (0.0, None, np.zeros(3)) + ((None,) if with_point else ())
    m = max(3, math.ceil(BEND_SHARE * len(P)))
    cand = list(range(m, len(P) - m))
    if not cand:
        return none
    fits = []
    for i in cand:
        da, db = _direction(P[:i]), _direction(P[i + 1:])
        fits.append((math.degrees(math.acos(float(np.clip(da @ db, -1.0, 1.0)))), da, db))
    ang = np.array([f[0] for f in fits])
    k = int(np.argmax(ang))
    if ang[k] <= 0.0:
        return none
    near = ang >= ang[k] * (1.0 - BEND_TIE)
    lo, hi = k, k
    while lo > 0 and near[lo - 1]:
        lo -= 1
    while hi < len(ang) - 1 and near[hi + 1]:
        hi += 1
    k = (lo + hi) // 2
    i, (_, da, db) = cand[k], fits[k]
    corner = _nearest_on_polyline(P, _lines_meet(P[:i].mean(axis=0), da, P[i + 1:].mean(axis=0), db))
    index = int(np.argmin(_dist2(P, corner)))
    out = (float(ang.max()), index, _unit(da - db))
    return out + ((corner,) if with_point else ())


def _lines_meet(c1, d1, c2, d2) -> np.ndarray:
    """The point halfway between the closest points of two lines (c, unit d)."""
    w = c1 - c2
    b, d, e = float(d1 @ d2), float(d1 @ w), float(d2 @ w)
    den = 1.0 - b * b
    if den <= 0.0:
        return 0.5 * (c1 + c2)
    s, u = (b * e - d) / den, (e - b * d) / den
    return 0.5 * (c1 + s * d1 + c2 + u * d2)


def _nearest_on_polyline(P: np.ndarray, q: np.ndarray) -> np.ndarray:
    """The point of the polyline P nearest q (ties go to the first segment)."""
    if len(P) == 1:
        return P[0].copy()
    seg = np.stack([P[:-1], P[1:]], axis=1)
    k = int(np.argmin(_seg_dist2(seg, q)))
    A, D = seg[k, 0], seg[k, 1] - seg[k, 0]
    L2 = float(D @ D)
    t = min(max(float((q - A) @ D) / L2, 0.0), 1.0) if L2 > 0 else 0.0
    return A + t * D


# ---------------------------------------------------------------------------------------
# rays

def _ray_prep(V, T):
    V = np.asarray(V, float)
    T = np.asarray(T, np.int64).reshape(-1, 3)
    size = float((V.max(axis=0) - V.min(axis=0)).max()) if len(V) else 0.0
    return V, T, size


def _hits(prep, o, d):
    V, T, size = prep
    o, d = np.asarray(o, float), _unit(d)
    if not len(T) or not d.any():
        return np.zeros(0), np.zeros((0, 3)), np.zeros(0, np.int64)
    # Only triangles whose box, seen along the ray, covers the ray (and that reach past its
    # start) can be hit: test those few in full.
    u_ax, v_ax = _basis(d)
    pad = 1e-8 * size
    u0, u1 = _corner_min_max(_side(V, o, u_ax), T)
    w0, w1 = _corner_min_max(_side(V, o, v_ax), T)
    _, d1 = _corner_min_max(_side(V, o, d), T)
    cand = np.nonzero((u0 <= pad) & (u1 >= -pad) & (w0 <= pad) & (w1 >= -pad) & (d1 > -pad))[0]
    A = V[T[cand, 0]]
    e1, e2 = V[T[cand, 1]] - A, V[T[cand, 2]] - A
    scale = np.linalg.norm(e1, axis=1) * np.linalg.norm(e2, axis=1)
    pv = np.cross(d, e2)
    det = (e1 * pv).sum(axis=1)
    ok = np.abs(det) > 1e-12 * scale          # edge-on or degenerate triangles never count
    inv = np.zeros_like(det)
    inv[ok] = 1.0 / det[ok]
    s = o - A
    u = (s * pv).sum(axis=1) * inv
    q = np.cross(s, e1)
    v = (q @ d) * inv
    t = (q * e2).sum(axis=1) * inv
    hit = ok & (u >= -_SLACK) & (v >= -_SLACK) & (u + v <= 1.0 + _SLACK) & (t > 0)
    loc = np.nonzero(hit)[0]
    th, idx = t[loc], cand[loc]
    order = np.lexsort((idx, th))
    loc, idx, th = loc[order], idx[order], th[order]
    nr = np.cross(e1[loc], e2[loc])
    nr /= np.linalg.norm(nr, axis=1, keepdims=True)    # never zero: flat triangles were dropped
    sg = nr @ d
    # A ray through a shared edge or vertex meets every triangle there at the same t: keep
    # one entry and one exit per spot, ordered so they alternate with what came before.
    keep, depth, i = [], 0, 0
    tol = _MERGE * size
    while i < len(th):
        j = i
        while j + 1 < len(th) and th[j + 1] - th[i] <= tol:
            j += 1
        ent = [g for g in range(i, j + 1) if sg[g] < 0]
        ext = [g for g in range(i, j + 1) if sg[g] > 0]
        pick = ([ent[0], ext[0]] if depth <= 0 else [ext[0], ent[0]]) if ent and ext else \
            ent[:1] or ext[:1]
        for g in pick:
            depth += 1 if sg[g] < 0 else -1
        keep += pick
        i = j + 1
    keep = np.asarray(keep, np.int64)
    return th[keep], nr[keep], idx[keep]


def ray_hits(V, T, o, d, with_tris: bool = False):
    """Every place the ray from o along d meets the surface (vectorised Moller-Trumbore over
    all triangles; the plain-numpy stand-in for repeated BVH casts).

    Returns (t, normals) sorted by t: t is the distance along the unit direction (t > 0),
    normals the unit face normals from the winding. A ray through a shared edge or vertex
    gives one hit there, not one per triangle. With with_tris, also the triangle ids."""
    t, nr, idx = _hits(_ray_prep(V, T), o, d)
    return (t, nr, idx) if with_tris else (t, nr)


def ray_spans(ts, normals, d):
    """Pairs ray hits into the stretches where the ray is inside solid material.

    A hit whose normal faces the ray (n . d < 0) is an entry, otherwise an exit. A nesting
    count keeps overlapping shells as one span (entry, entry, exit, exit). When the normals
    do not add up (an exit while outside, still inside at the end, an edge-on hit), the hits
    are paired in order instead: (1st, 2nd), (3rd, 4th), ...

    Returns (spans, by_normals): spans is a list of (t_in, t_out) in order along the ray;
    by_normals is False when the in-order pairing was used. The ray must start outside."""
    ts = np.asarray(ts, float).ravel()
    sg = np.asarray(normals, float).reshape(-1, 3) @ _unit(d)
    spans, depth, start, ok = [], 0, 0.0, True
    for t, s in zip(ts.tolist(), sg.tolist()):
        if s < 0:
            if depth == 0:
                start = t
            depth += 1
        elif s > 0 and depth > 0:
            depth -= 1
            if depth == 0:
                spans.append((start, t))
        else:
            ok = False
            break
    if ok and depth == 0:
        return spans, True
    return [(float(ts[k]), float(ts[k + 1])) for k in range(0, len(ts) - 1, 2)], False


def inside(V, T, p) -> bool:
    """Whether p is inside the mesh: each of three rays (+X, -X, +Y) votes inside when it
    meets the surface an odd number of times; 2 of 3 votes win. One ray that slips through
    a hole in an open mesh is outvoted."""
    prep = _ray_prep(V, T)
    votes = sum(len(_hits(prep, p, d)[0]) % 2 for d in _RAYS)
    return votes >= 2


# ---------------------------------------------------------------------------------------
# trunk and feet

def _line_crossings(P: np.ndarray, x0: float) -> list:
    """Sorted y where the closed polygon P (x, y columns) crosses the line x = x0."""
    x, y = P[:, 0], P[:, 1]
    x1, y1 = np.roll(x, -1), np.roll(y, -1)
    m = (x > x0) != (x1 > x0)
    return sorted((y[m] + (x0 - x[m]) * (y1[m] - y[m]) / (x1[m] - x[m])).tolist())


def trunk_axis(V, T, z0: float, z1: float, x0: float, steps: int = 12, ball=None) -> list:
    """Horizontal slices from z0 to z1 (steps + 1 of them) that follow the trunk.

    At each height, the centre line x = x0 runs through some loops. The biggest of them is
    the trunk (a tail or a hand in the same slice is smaller); y_mid is the middle of the
    longest stretch of the centre line inside it. The sample's loop is the smallest closed
    loop around (x0, y_mid, z), so a shell over the trunk (armour, a coat) does not count.

    Each sample is {t, z, p, found, closed, r, area, centroid, width (x extent), depth (y
    extent), loop}. The centroids are the trunk's medial axis; profile_centroids() gives
    them as an array."""
    V = np.asarray(V, float)
    T = np.asarray(T, np.int64).reshape(-1, 3)
    up = np.array([0.0, 0.0, 1.0])
    yc = float(np.median(V[np.unique(T), 1])) if len(T) else 0.0
    slabs = _Slabs(V, T, np.zeros(3), up)
    out = []
    for i in range(steps + 1):
        t = i / max(steps, 1)
        z = z0 + t * (z1 - z0)
        lps = [lp for lp in section(V, slabs.near(z), (x0, yc, z), up, ball)
               if lp["closed"] and not lp["hole"]]
        best = None
        for k, lp in enumerate(lps):
            ys = _line_crossings(lp["pts"], x0)
            for j in range(0, len(ys) - 1, 2):
                key = (lp["area"], ys[j + 1] - ys[j], -k)
                if best is None or key > best[0]:
                    best = (key, 0.5 * (ys[j] + ys[j + 1]))
        smp = {"t": t, "z": z, "p": None, "found": False, "closed": False, "r": 0.0, "area": 0.0,
               "centroid": None, "width": 0.0, "depth": 0.0, "loop": None}
        if best is not None:
            p = np.array([x0, best[1], z])
            around = [k for k, lp in enumerate(lps) if lp["contains"](p)]
            smp["p"] = p
            if around:
                lp = lps[min(around, key=lambda k: (lps[k]["area"], k))]
                ext = lp["pts"].max(axis=0) - lp["pts"].min(axis=0)
                smp.update(found=True, closed=True, r=lp["r"], area=lp["area"], centroid=lp["centroid"],
                           width=float(ext[0]), depth=float(ext[1]), loop=lp)
        out.append(smp)
    return out


def contact_patch(V, ground: float, side_mask=None, H=None, front=(0.0, -1.0, 0.0),
                  band: float = CONTACT_BAND):
    """The vertices of one foot that touch the ground: within band * H (0.01 H) above
    `ground`, among the vertices in side_mask (all without it). H defaults to the mesh's
    height.

    Returns {toe, heel, left, right, centre, idx, n} or None when nothing touches. toe and
    heel are the points furthest to the front and back along `front`; left and right are
    the side-most points, left being the character's left (up x front)."""
    V = np.asarray(V, float)
    if H is None:
        H = float(V[:, 2].max() - V[:, 2].min()) if len(V) else 0.0
    sel = (V[:, 2] - float(ground)) <= band * float(H)
    if side_mask is not None:
        sel &= np.asarray(side_mask, bool)
    idx = np.nonzero(sel)[0]
    if not len(idx):
        return None
    P = V[idx]
    f = np.asarray(front, float).copy()
    f[2] = 0.0
    f = _unit(f)
    lat = np.cross([0.0, 0.0, 1.0], f)
    pf, pl = P @ f, P @ lat
    return {"toe": P[int(np.argmax(pf))], "heel": P[int(np.argmin(pf))],
            "left": P[int(np.argmax(pl))], "right": P[int(np.argmin(pl))],
            "centre": P.mean(axis=0), "idx": idx, "n": len(idx)}
