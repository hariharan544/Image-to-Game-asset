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
    tolerance. A loop that cannot close (an open mesh, a slice cut short) says so. Where a
    sheet is fused onto a surface (a fin on one edge line), the surface's own ring still
    closes and the sheet is left as an open chain.
  - The ball that limits a slice keeps the slice's own segments that come near its centre.
    How big the faces are does not matter: a long face that passes close by still counts.
    The ball follows how far the limb's loop reaches, so a flat part (a fin, a membrane)
    keeps its slices whole.
  - Loops nest. A loop is a hole only when it sits straight inside a solid loop and runs the
    other way. A limb inside a bracelet's hole is solid again.
  - A limb lying against the body (an arm resting on the ribs, thighs that touch) merges
    with it in the slice through a narrow neck between two hollows. The walk to a limb's
    root follows the limb's own lobe past such a neck; only a slice with no neck is the root.
  - A single-sided surface (a cape, a skirt made of one sheet) holds no volume: rays and
    inside() look through it.
  - A part taken away (mask_tris) leaves its root patched over, so the body's slices there
    still close and measure the body alone.
  - Nothing depends on how the mesh is turned: the default body size is measured from the
    surface's own centre, not from a box along the axes.
  - Ties go to the lowest index. No set or dict order decides a result.

Inputs are world-space arrays: V is (n, 3) float, T is (m, 3) int (tris(arr) builds it from
parts.MeshArrays). Slices link triangles through shared vertex ids, so a seam with doubled
vertices (a glTF import, a part joined back) breaks every slice across it: run weld(V, T)
once first. Where a direction matters, Forge's convention holds: Z is up, the character faces
-Y and its left is +X.
"""

from __future__ import annotations

import hashlib
import math

import numpy as np

JUMP = 1.8           # a limb meets the body where the slice area grows this many times at once
BALL_RADII = 3.0     # a slice looks this many times the limb's reach around its centre...
BALL_SIZE = 0.15     # ...or this share of the body's size, whichever is larger
PLATEAU = 0.03       # radii within 3% of the smallest count as one straight stretch
BEND_SHARE = 0.25    # each line bend_along fits holds at least a quarter of the points (and 3)
BEND_TIE = 0.02      # bend angles within 2% of the largest count as the same bend
CONTACT_BAND = 0.01  # a foot touches the ground within this share of the body's height
POCKET = 0.1         # a neck's two ends sit in hollows at least this share of its width deep
NECK_ARC = 2.0       # ...and the outline on each side of it is at least this many widths long
NECK_PTS = 256       # necks are looked for on at most this many points of a loop, then refined
PINCH_TIE = 0.9      # necks pinching within this share of the most pinched count as one neck
CONTACT_SPAN = 2.0   # a limb lying along the body touches it over more than this many radii
SHEET = 0.25         # a surface whose openings would need patches over this share of its area
TINY = 1e-6          # a closed loop under this share of the slice's largest loop is rounding
REFINE_TO = 0.1      # find_crease narrows the crease down to this share of the limb's radius
AUTO = "auto"        # profile_along: the ball follows the limb's own reach
_SLACK = 1e-9        # a ray along a shared edge hits both triangles; the two hits merge after
_MERGE = 1e-9        # hits closer than this share of the body's size are one hit
_RAYS = ((1.0, 0.0, 0.0), (-1.0, 0.0, 0.0), (0.0, 1.0, 0.0))
_SHEET_CACHE: dict = {}


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
    Y = np.asarray(py, float)[:, None]
    across = (y[None, :] > Y) != (y1[None, :] > Y)
    with np.errstate(divide="ignore", invalid="ignore"):
        xc = x[None, :] + (Y - y[None, :]) * ((x1 - x) / (y1 - y))[None, :]
    return ((across & (np.asarray(px, float)[:, None] < xc)).sum(1) % 2) == 1


def _shoelace(x: np.ndarray, y: np.ndarray) -> float:
    """Signed area of the closed polygon (x, y): positive when it runs counter-clockwise."""
    return 0.5 * float((x * np.roll(y, -1) - np.roll(x, -1) * y).sum())


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
    """How far around its centre a slice looks: 3 times the limb's reach (how far its loop
    reaches from the axis; for a round limb, its radius), or 0.15 of the body's size when that
    is more. Without a guess, 0.15 of the body's size."""
    return max(BALL_RADII * float(r_guess or 0.0), BALL_SIZE * float(H))


# ---------------------------------------------------------------------------------------
# mesh topology

def weld(V, T) -> np.ndarray:
    """T with every vertex replaced by the lowest-numbered vertex at exactly the same position.

    Slices and sheet_tris() link triangles through shared vertex ids, so a seam with doubled
    vertices (a glTF import, a part joined back) would read as an opening. Equal coordinates
    are matched exactly, with no tolerance; positions do not change, so V stays as it is."""
    V = np.asarray(V, float)
    T = np.asarray(T, np.int64).reshape(-1, 3)
    if not len(V) or not len(T):
        return T.copy()
    o = np.lexsort((V[:, 2], V[:, 1], V[:, 0]))      # stable: equal rows keep id order
    Vs = V[o]
    new = np.ones(len(V), bool)
    new[1:] = (Vs[1:] != Vs[:-1]).any(axis=1)
    grp = np.cumsum(new) - 1
    first = o[np.nonzero(new)[0]]
    canon = np.empty(len(V), np.int64)
    canon[o] = first[grp]
    return canon[T]


def _components(n: int, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Connected components of n items joined by the pairs (a, b): each item's label is the
    lowest item of its component."""
    lab = np.arange(n)
    if not len(a):
        return lab
    while True:
        la, lb = lab[a], lab[b]
        new = lab.copy()
        np.minimum.at(new, np.maximum(la, lb), np.minimum(la, lb))
        while True:
            nn = new[new]
            if np.array_equal(nn, new):
                break
            new = nn
        if np.array_equal(new, lab):
            return lab
        lab = new


def _mesh_key(V, T) -> tuple:
    """A content fingerprint of a mesh, so work measured once per mesh can be reused safely
    even when the same arrays are changed in place."""
    h = hashlib.blake2b(digest_size=16)
    for x in (V, T):
        x = np.ascontiguousarray(x)
        h.update(str((x.shape, x.dtype.str)).encode())
        h.update(x.tobytes())
    return h.hexdigest()


def sheet_tris(V, T) -> np.ndarray:
    """True for the triangles of single-sided surfaces: a cape, a skirt or a fin made of one
    sheet. They hold no volume, so rays and inside() look through them.

    Triangles are grouped into surfaces through edges that exactly two triangles share; an
    edge with one triangle (an opening) or with three or more (a sheet fused onto a body
    along a line) bounds a surface. A surface is a sheet when patching its openings flat
    would cover more than SHEET (a quarter) of its own area: a cape is mostly opening, while
    a body with a few holes is still a body. Vertices at exactly the same position count as
    one (weld). The answer is kept per mesh content, so asking again is cheap."""
    V = np.asarray(V, float)
    T = np.asarray(T, np.int64).reshape(-1, 3)
    key = _mesh_key(V, T)
    hit = _SHEET_CACHE.get(key)
    if hit is not None:
        return hit.copy()
    out = _sheet_tris(V, T)
    _SHEET_CACHE.clear()
    _SHEET_CACHE[key] = out
    return out.copy()


def _sheet_tris(V, T) -> np.ndarray:
    m = len(T)
    if not m:
        return np.zeros(0, bool)
    Tw = weld(V, T)
    e = np.sort(np.concatenate([Tw[:, [0, 1]], Tw[:, [1, 2]], Tw[:, [2, 0]]]), axis=1)
    code = e[:, 0] * (int(Tw.max()) + 1) + e[:, 1]
    _, inv, cnt = np.unique(code, return_inverse=True, return_counts=True)
    inv = inv.reshape(-1)
    per = cnt[inv]
    if (per == 2).all():
        return np.zeros(m, bool)
    tri = np.arange(3 * m) % m
    hm = np.nonzero(per == 2)[0]
    hm = hm[np.argsort(inv[hm], kind="stable")]
    lab = _components(m, tri[hm[0::2]], tri[hm[1::2]])
    A, B, C = V[Tw[:, 0]], V[Tw[:, 1]], V[Tw[:, 2]]
    area = np.bincount(lab, weights=0.5 * np.linalg.norm(np.cross(B - A, C - A), axis=1), minlength=m)
    hb = np.nonzero(per != 2)[0]
    owner = lab[tri[hb]]
    sheets = []
    for c in np.unique(owner).tolist():
        if _opening_area(V, e[hb[owner == c]]) > SHEET * area[c]:
            sheets.append(c)
    return np.isin(lab, sheets)


def _opening_area(V, edges: np.ndarray) -> float:
    """The area flat patches over the openings bounded by these edges would cover: each
    opening is walked edge by edge, and the length of its vector area is added."""
    adj: dict = {}
    for k, (a, b) in enumerate(edges.tolist()):
        adj.setdefault(a, []).append((b, k))
        adj.setdefault(b, []).append((a, k))
    used = np.zeros(len(edges), bool)
    total = 0.0
    for k0 in range(len(edges)):
        if used[k0]:
            continue
        used[k0] = True
        start, v = (int(x) for x in edges[k0])
        walk = [start, v]
        while v != start:
            nxt = [(w, k) for w, k in adj[v] if not used[k]]
            if not nxt:
                break
            w, k = nxt[0]
            used[k] = True
            walk.append(w)
            v = w
        P = V[np.asarray(walk, np.int64)]
        P = P - P.mean(axis=0)
        total += float(np.linalg.norm(0.5 * np.cross(P, np.roll(P, -1, axis=0)).sum(axis=0)))
    return total


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


def mask_tris(T, excluded, with_caps: bool = False, V=None) -> np.ndarray:
    """The triangles left when the excluded vertices are taken away (pass 2 of the joint
    guess), with the openings this leaves patched over.

    Every triangle with an excluded corner is dropped. A part that is its own shell just goes.
    A part that grows out of the body (an AI mesh is one fused surface) leaves an opening at
    its root; the opening is patched with triangles between its own border vertices, so a
    slice of the body there closes with a straight run across the root, as if the part had
    never been there. The patch needs no new vertices. Holes the mesh had before stay open.

    A ragged border can pass the same vertex twice: it is split there into simple rings. Each
    ring is filled by clipping ears, never adding an edge the mesh already has, so no edge
    ever ends up with more than two faces. With V (the vertex positions), each ear is a
    convex corner with no other border vertex inside, shortest first, in the ring's own
    plane, so the patch does not fold; without V, ears go from both ends of the ring toward
    the middle, like a zip.

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
    caps = _patch_openings(keep, T[drop], size, None if V is None else np.asarray(V, float))
    out = np.vstack([keep, caps]) if len(caps) else keep
    if with_caps:
        return out, np.arange(len(out)) >= len(keep)
    return out


def _patch_openings(keep: np.ndarray, gone: np.ndarray, size: int, V=None) -> np.ndarray:
    """Triangles that close the openings left where `gone` met `keep`.

    An edge is on such an opening when one kept triangle and at least one dropped triangle
    share it. The patch runs each of those edges the other way, so it winds like the faces
    round it. Walks start at the lowest vertex id."""
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
    # the mesh edges between border vertices: a patch must never add one of these again
    on = np.zeros(size, bool)
    on[e.ravel()] = True
    near = on[hk[:, 0]] & on[hk[:, 1]]
    edges = set(code_k[near].tolist())
    tris_out = []
    for ring in _border_rings(e):
        tris_out += _fill_ring(ring, edges, size, V)
    return np.array(tris_out, np.int64).reshape(-1, 3)


def _border_rings(e: np.ndarray) -> list:
    """The simple rings of directed border edges (sorted by start): a walk that comes back to
    a vertex it has already passed closes a ring there and goes on from that vertex. A border
    that does not come back round is left open. Each ring starts at its lowest vertex."""
    starts = e[:, 0]
    used = np.zeros(len(e), bool)
    rings = []
    for k0 in range(len(e)):
        if used[k0]:
            continue
        walk, k = [int(e[k0, 0])], k0
        pos = {walk[0]: 0}
        while True:
            used[k] = True
            v = int(e[k, 1])
            if v in pos:
                c = pos[v]
                if len(walk) - c >= 3:
                    rings.append(walk[c:])
                for u in walk[c + 1:]:
                    del pos[u]
                del walk[c + 1:]
            else:
                pos[v] = len(walk)
                walk.append(v)
            lo = int(np.searchsorted(starts, v, "left"))
            hi = int(np.searchsorted(starts, v, "right"))
            free = [j for j in range(lo, hi) if not used[j]]
            if not free:
                break
            k = free[0]
    out = []
    for ring in rings:
        r = int(np.argmin(ring))
        out.append(ring[r:] + ring[:r])
    return out


def _fill_ring(ring: list, edges: set, size: int, V=None) -> list:
    """Triangles that fill one simple ring of border vertices, by clipping ears. An ear whose
    new edge the mesh already has is never clipped. A ring that cannot be finished that way
    keeps its last part open."""
    cur = list(ring)
    out = []
    N = None
    if V is not None:
        R = V[np.asarray(cur, np.int64)]
        R = R - R.mean(axis=0)
        N = 0.5 * np.cross(R, np.roll(R, -1, axis=0)).sum(axis=0)
        N = N if np.any(N) else None
    step = 0
    while len(cur) > 3:
        q = len(cur)
        prv, nxt = np.roll(np.arange(q), 1), np.roll(np.arange(q), -1)
        if N is not None:
            P = V[np.asarray(cur, np.int64)]
            turn = np.cross(P - P[prv], P[nxt] - P) @ N
            diag = np.linalg.norm(P[nxt] - P[prv], axis=1)
            order = np.lexsort((np.arange(q), diag, turn <= 0)).tolist()
        else:
            first = 0 if step % 2 == 0 else q - 1
            order = [first] + [c for c in ([q - 1, 0] if first == 0 else [0, q - 1]) if c != first] + \
                list(range(1, q - 1))
        pick = None
        for strict in ((True, False) if N is not None else (False,)):
            for c in order:
                a, b = cur[prv[c]], cur[nxt[c]]
                if min(a, b) * size + max(a, b) in edges:
                    continue
                if strict and not _ear_ok(P, prv[c], c, nxt[c], turn[c], N):
                    continue
                pick = c
                break
            if pick is not None:
                break
        if pick is None:
            return out
        a, v, b = cur[prv[pick]], cur[pick], cur[nxt[pick]]
        out.append((a, v, b))
        edges.add(min(a, b) * size + max(a, b))
        del cur[pick]
        step += 1
    if len(cur) == 3:
        out.append(tuple(cur))
    return out


def _ear_ok(P, i, c, j, turn, N) -> bool:
    """Whether the corner c (between i and j) of a ring is an ear: it turns the ring's way
    about N and no other ring point lies inside the triangle (i, c, j)."""
    if turn <= 0:
        return False
    A, B, C = P[i], P[c], P[j]
    rest = np.ones(len(P), bool)
    rest[[i, c, j]] = False
    Q = P[rest]
    if not len(Q):
        return True
    s1 = np.cross(B - A, Q - A) @ N
    s2 = np.cross(C - B, Q - B) @ N
    s3 = np.cross(A - C, Q - C) @ N
    return not ((s1 > 0) & (s2 > 0) & (s3 > 0)).any()


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


def loops(segs, keys, n=None) -> list:
    """Links cut() segments that share an edge key into loops.

    Each loop is {"pts": (q, 3), "keys": (q, 2), "closed": bool}. A ring that comes back to
    its start through plain edges is closed. A chain that stops at an open edge or at the
    edge of a ball is open. Repeated points (a slice through a vertex) are kept once. Loops
    run the way most of their segments run; a ring starts at its lowest edge key, and the
    loops come sorted by their lowest key.

    Where more than two segments meet (a non-manifold edge: a fin or a sheet fused onto a
    surface along a line), the chains stop there and come out open, unless the slice normal
    n is given. With n, each segment that arrives there goes on along the one that leaves
    with the sharpest turn toward the material side: the surface going on round its own
    material, so the surface's ring closes and the sheet is left as an open chain. Segments
    run round material counter-clockwise about n when the faces wind outward and clockwise
    when they wind inward; the sign of the slice's total signed area says which."""
    segs = np.asarray(segs, float).reshape(-1, 2, 3)
    keys = np.asarray(keys, np.int64).reshape(-1, 2, 2)
    if not len(segs):
        return []
    flat = keys.reshape(-1, 2)
    base = int(flat.max()) + 1
    _, first, node = np.unique(flat[:, 0] * base + flat[:, 1], return_index=True, return_inverse=True)
    node = node.reshape(-1, 2).copy()
    pts = segs.reshape(-1, 3)[first]
    nkey = flat[first]
    orig = np.arange(len(first))
    if n is not None and np.any(n):
        # Segments run round material counter-clockwise about n when the faces wind outward,
        # clockwise when they wind inward: the slice's total signed area tells which.
        c = pts.mean(axis=0)
        sense = float((np.cross(segs[:, 0] - c, segs[:, 1] - c) @ _unit(n)).sum())
        side = _unit(n) if sense >= 0 else -_unit(n)
        node, pts, nkey, orig = _pair_branches(segs, node, pts, nkey, side)
    ends = node.tolist()
    inc: list = [[] for _ in range(len(pts))]
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
    for u in range(len(pts)):            # chains from loose ends and branch points first
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
            k = int(np.argmin(orig[np.asarray(nodes, np.int64)]))
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
        out.append((int(orig[idx].min()), {"pts": P, "keys": nkey[idx], "closed": bool(closed)}))
    out.sort(key=lambda x: x[0])
    return [lp for _, lp in out]


def _pair_branches(segs, node, pts, nkey, n):
    """Splits each slice point where more than two segments meet into one point per pair of
    an arriving and a leaving segment, paired by the most counter-clockwise turn about n
    first, and one point per segment left over (a loose end). A segment's direction is taken
    to the nearest point along its chain that is not the branch point itself, so a slice
    exactly through a vertex (segments of no length) still turns the right way. Returns the
    new node table, points, keys, and the original point of each new one."""
    nn = len(pts)
    real = node[:, 0] != node[:, 1]
    deg = np.bincount(node[real].ravel(), minlength=nn)
    branch = np.nonzero(deg > 2)[0]
    if not len(branch):
        return node, pts, nkey, np.arange(nn)
    inc: list = [[] for _ in range(nn)]
    for s_, (a_, b_) in enumerate(node.tolist()):
        if a_ != b_:
            inc[a_].append(s_)
            inc[b_].append(s_)

    def reach(s_, back):
        """The direction from the branch end of segment s_ to the first point along its chain
        that lies elsewhere (back: walking against the segments, from an arriving one)."""
        v = int(node[s_, 1] if back else node[s_, 0])
        here = pts[v]
        for _ in range(len(node)):
            u = int(node[s_, 0] if back else node[s_, 1])
            if (pts[u] != here).any():
                return (here - pts[u]) if back else (pts[u] - here)
            nxt = [t for t in inc[u] if t != s_ and int(node[t, 1 if back else 0]) == u]
            if len(nxt) != 1 or deg[u] != 2:
                break
            s_ = nxt[0]
        return np.zeros(3)

    plan = []
    for v in branch.tolist():
        arr = np.nonzero(real & (node[:, 1] == v))[0].tolist()
        dep = np.nonzero(real & (node[:, 0] == v))[0].tolist()
        da = {a: reach(a, True) for a in arr}
        db = {b: reach(b, False) for b in dep}
        cand = []
        for a in arr:
            for b in dep:
                turn = math.atan2(float(np.cross(da[a], db[b]) @ n), float(da[a] @ db[b]))
                cand.append((-turn, a, b))
        cand.sort()
        plan.append((v, arr, dep, cand))
    extra = []
    for v, arr, dep, cand in plan:
        done_a, done_b = set(), set()
        for _, a, b in cand:
            if a in done_a or b in done_b:
                continue
            done_a.add(a)
            done_b.add(b)
            node[a, 1] = node[b, 0] = nn + len(extra)
            extra.append(v)
        for a in arr:
            if a not in done_a:
                node[a, 1] = nn + len(extra)
                extra.append(v)
        for b in dep:
            if b not in done_b:
                node[b, 0] = nn + len(extra)
                extra.append(v)
    ex = np.asarray(extra, np.int64)
    return (node, np.vstack([pts, pts[ex]]), np.vstack([nkey, nkey[ex]]),
            np.concatenate([np.arange(nn), ex]))


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
      aspect_pts   sqrt(smaller / larger) of the points' own spread (their PCA): 1 for a
                   circle, b/a for an a-by-b ellipse. This is ring_check.py's "aspect", the
                   other way up from `aspect`; on a concave ring (a crescent) it differs
                   from 1 / aspect, because the points are not the area
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
    return _props(P, closed, n)


def _props(P: np.ndarray, closed: bool, n=None, frame=None) -> dict:
    """loop_props() of the points P; frame is (normal, u, v) when the caller already has the
    plane's frame (every loop of one slice shares it)."""
    k = len(P)
    c0 = P.mean(axis=0) if k else np.zeros(3)
    Q = P - c0
    Q1 = np.concatenate([Q[1:], Q[:1]]) if k else Q
    va = 0.5 * np.array([(Q[:, 1] * Q1[:, 2] - Q[:, 2] * Q1[:, 1]).sum(),
                         (Q[:, 2] * Q1[:, 0] - Q[:, 0] * Q1[:, 2]).sum(),
                         (Q[:, 0] * Q1[:, 1] - Q[:, 1] * Q1[:, 0]).sum()]) if k else np.zeros(3)
    if frame is not None:
        nrm, u, v = frame
    else:
        if n is not None and np.any(n):
            nrm = _unit(n)
        else:
            nrm = _unit(va) if np.any(va) else np.array([0.0, 0.0, 1.0])
        u, v = _basis(nrm)
    x, y = Q @ u, Q @ v
    x1, y1 = Q1 @ u, Q1 @ v
    cr = x * y1 - x1 * y
    a2 = float(cr.sum()) / 2.0
    area = abs(a2)
    if a2 != 0.0:
        cx = float(((x + x1) * cr).sum()) / (6.0 * a2)
        cy = float(((y + y1) * cr).sum()) / (6.0 * a2)
        sxx = float((cr * (x * x + x * x1 + x1 * x1)).sum()) / 12.0 / a2 - cx * cx
        syy = float((cr * (y * y + y * y1 + y1 * y1)).sum()) / 12.0 / a2 - cy * cy
        sxy = float((cr * (x * y1 + 2 * x * y + 2 * x1 * y1 + x1 * y)).sum()) / 24.0 / a2 - cx * cy
        lo, hi, (ex, ey) = _eig2(sxx, sxy, syy)
        aspect = math.sqrt(hi / lo) if lo > 0 else math.inf
        mj = ex * u + ey * v
        major = mj if mj[int(np.argmax(np.abs(mj)))] >= 0 else -mj
    else:
        cx = cy = 0.0
        aspect, major = math.inf, u.copy()
    if k >= 2:
        xm, ym = x - x.mean(), y - y.mean()
        lo, hi, _ = _eig2(float(xm @ xm), float(xm @ ym), float(ym @ ym))
        aspect_pts = math.sqrt(max(lo, 0.0) / hi) if hi > 0 else 1.0
    else:
        aspect_pts = 1.0
    r = math.sqrt(area / math.pi)
    steps = np.sqrt(((Q1 - Q) ** 2).sum(axis=1))
    perimeter = float(steps.sum() if closed else steps[:-1].sum())
    off = float(np.sqrt(np.mean((Q @ nrm) ** 2))) if k else 0.0

    def contains(pt):
        pt = np.asarray(pt, float)
        one = pt.ndim == 1
        pt = np.atleast_2d(pt)
        if pt.shape[1] == 3:
            w = pt - c0
            px, py = w @ u, w @ v
        else:
            px, py = pt[:, 0], pt[:, 1]
        res = _in_polygon(x, y, px, py) if k >= 3 else np.zeros(len(pt), bool)
        return bool(res[0]) if one else res

    return {
        "vector_area": va, "normal": nrm, "signed_area": a2, "area": area, "r": r,
        "centroid": c0 + cx * u + cy * v, "perimeter": perimeter,
        "roundness": 4.0 * math.pi * area / perimeter ** 2 if perimeter > 0 else 0.0,
        "aspect": aspect, "aspect_pts": aspect_pts, "major": major,
        "off_plane": off / r if r > 0 else 0.0,
        "origin": c0, "u": u, "v": v, "contains": contains,
    }


def _eig2(a: float, b: float, c: float):
    """Eigenvalues (smaller, larger) of the symmetric 2x2 matrix [[a, b], [b, c]], and the
    unit eigenvector of the larger one."""
    m, d = 0.5 * (a + c), math.hypot(0.5 * (a - c), b)
    lo, hi = m - d, m + d
    if b != 0.0:
        e = (hi - c, b)
    else:
        e = (1.0, 0.0) if a >= c else (0.0, 1.0)
    ln = math.hypot(*e)
    return lo, hi, (e[0] / ln, e[1] / ln)


def section(V, T, p, n, ball=None) -> list:
    """Every loop of the slice through p with normal n, each loops() dict merged with its
    loop_props(), a "hole" flag and a "parent".

    Closed loops nest. A loop's parent is the smallest closed loop that holds it (most of its
    points lie inside), as an index into this list, or None. A loop is a hole when its parent
    is solid and it runs the other way: the inner wall of a hollow tube. Inside a hole a loop
    is solid again, so an arm through a bracelet stays an arm. Loops are settled from the
    biggest down, so a parent is always settled first; ties go to the lower index. Open loops
    take no part in the nesting. A closed loop under TINY (a millionth) of the slice's
    largest loop is a speck left by rounding near a vertex, and is dropped."""
    n = _unit(n)
    return _section(*cut(V, T, p, n, ball), n)


def _section(segs, keys, n, lps=None) -> list:
    frame = (n,) + _basis(n)
    lps = loops(segs, keys, n) if lps is None else lps
    out = [dict(lp, **_props(lp["pts"], lp["closed"], frame=frame), hole=False, parent=None)
           for lp in lps]
    big = max((lp["area"] for lp in out if lp["closed"]), default=0.0)
    out = [lp for lp in out if not (lp["closed"] and lp["area"] <= TINY * big)]
    _nest(out)
    return out


def _nest(out: list) -> None:
    """Sets "parent" and "hole" on a list of section loops (see section())."""
    ring = [i for i, lp in enumerate(out) if lp["closed"] and lp["signed_area"] != 0.0]
    ring.sort(key=lambda i: (-out[i]["area"], i))
    if not ring:
        return
    # Boxes only skip loops that are far apart. Every point lies on the plane, so each box is
    # widened by a share of its own size: rounding along the normal must not decide.
    lo = np.array([out[i]["pts"].min(axis=0) for i in ring])
    hi = np.array([out[i]["pts"].max(axis=0) for i in ring])
    pad = 1e-6 * (hi - lo).max(axis=1, keepdims=True)
    lo, hi = lo - pad, hi + pad
    mid = 0.5 * (lo + hi)
    area = np.array([out[i]["area"] for i in ring])
    for k, i in enumerate(ring):
        P = out[i]["pts"]
        q = P[np.unique(np.linspace(0, len(P) - 1, min(len(P), 16)).astype(np.int64))]
        box = np.nonzero((area[:k] > area[k]) & (lo[:k] <= mid[k]).all(axis=1)
                         & (mid[k] <= hi[:k]).all(axis=1))[0]
        for jj in box[::-1].tolist():                  # smallest first: the first that holds it
            j = ring[jj]
            if 2 * int(np.count_nonzero(out[j]["contains"](q))) > len(q):
                out[i]["parent"] = j
                break
        j = out[i]["parent"]
        out[i]["hole"] = bool(j is not None and not out[j]["hole"]
                              and (out[i]["signed_area"] > 0) != (out[j]["signed_area"] > 0))


class _Slice:
    """One slice through p, cut once with no ball; its loops inside a ball, over the whole
    plane, and the whole plane's loops round p are worked out when first asked for."""

    def __init__(self, segs, keys, p, n):
        self.segs, self.keys, self.p, self.n = segs, keys, p, n
        self.d2 = _seg_dist2(segs, p) if len(segs) else np.zeros(0)
        self.base = int(keys.max()) + 1 if len(keys) else 1
        self._whole = None
        self._around = None
        self._loops = None

    def loops(self) -> list:
        if self._loops is None:
            self._loops = loops(self.segs, self.keys, self.n)
        return self._loops

    def whole(self) -> list:
        if self._whole is None:
            self._whole = _section(self.segs, self.keys, self.n, self.loops())
        return self._whole

    def within(self, ball) -> list:
        if ball is None:
            return self.whole()
        inb = self.d2 <= float(ball) ** 2
        if inb.all():
            return self.whole()
        return _section(self.segs[inb], self.keys[inb], self.n)

    def around(self) -> list:
        """The closed loops of the whole slice that hold p, nested as in section() among
        themselves, without measuring every other loop (a speck is judged against the
        biggest of them)."""
        if self._around is None:
            if self._whole is not None:
                keep = [k for k, w in enumerate(self._whole) if w["closed"] and w["contains"](self.p)]
                at = {k: m for m, k in enumerate(keep)}
                self._around = [dict(self._whole[k], parent=at.get(self._whole[k]["parent"]))
                                for k in keep]
            else:
                self._around = self._held_loops()
        return self._around

    def _held_loops(self) -> list:
        lps = [lp for lp in self.loops() if lp["closed"]]
        if not lps:
            return []
        frame = (self.n,) + _basis(self.n)
        p = self.p
        cand = []
        for lp in lps:
            P = lp["pts"]
            lo, hi = P.min(axis=0), P.max(axis=0)
            pad = 1e-6 * float((hi - lo).max())
            if (lo - pad <= p).all() and (p <= hi + pad).all():
                d = dict(lp, **_props(P, True, frame=frame), hole=False, parent=None)
                if d["contains"](p):
                    cand.append(d)
        big = max((d["area"] for d in cand), default=0.0)
        out = [d for d in cand if d["area"] > TINY * big]
        _nest(out)
        return out

    def codes(self, keys) -> np.ndarray:
        return keys[:, 0] * self.base + keys[:, 1]

    def alone(self, own: np.ndarray) -> bool:
        """Whether no loop of the whole slice but the surface with these edge codes can hold
        p: a closed loop round p crosses every ray from p in the plane, so one of four rays
        that meets nothing else settles it without linking the whole slice."""
        if not len(self.segs):
            return True
        u, v = _basis(self.n)
        A, B = self.segs[:, 0] - self.p, self.segs[:, 1] - self.p
        mine = np.isin(self.codes(self.keys[:, 0]), own) | np.isin(self.codes(self.keys[:, 1]), own)
        for e1, e2 in ((u, v), (-u, v), (v, u), (-v, u)):
            a1, a2, b1, b2 = A @ e1, A @ e2, B @ e1, B @ e2
            across = (a2 > 0) != (b2 > 0)
            with np.errstate(divide="ignore", invalid="ignore"):
                at = a1 + (0.0 - a2) * (b1 - a1) / (b2 - a2)
            if not (across & (at > 0) & ~mine).any():
                return True
        return False


def loop_at(V, T, p, n, ball=None):
    """The loop of the slice through p (normal n) that p belongs to, and how many loops the
    slice has inside the ball (holes not counted).

    The loop is the smallest closed loop around p; else the smallest open one around p
    (measured as if closed); else, when p is in none (a bent limb leaves a straight axis),
    the loop whose centroid is nearest, closed ones first. It is a section() dict plus
      inside     p is in it
      enclosing  the areas of the other shells whose material is round p, biggest first: a
                 body the limb runs into, or a sleeve over it. These are judged on the whole
                 slice, not only inside the ball, so a big body round a thin limb still
                 counts; the limb's own surface, however far it runs, does not. A loop with
                 p in its hole (a bracelet round the limb, a cloth shell with thickness)
                 does not count.
      shells     those enclosing loops themselves (section() dicts), biggest first
      n_inside   1 when p is in the loop, plus one per enclosing loop: more than one means
                 the limb runs inside another shell here.
      siblings   centroids of the other closed loops in the ball within JUMP of its area:
                 parts of about its size side by side (fingers, a twin leg).
    (None, 0) when the slice is empty."""
    V = np.asarray(V, float)
    T = np.asarray(T, np.int64).reshape(-1, 3)
    p = np.asarray(p, float)
    n = _unit(n)
    segs, keys, _ = _cut(V, T, _valid(T), p, n)
    return _pick(_Slice(segs, keys, p, n), ball)


def _pick(sl: _Slice, ball, jump: float = JUMP):
    sec = sl.within(ball)
    solid = [k for k, lp in enumerate(sec) if not lp["hole"]]
    if not solid:
        return None, 0
    p = sl.p
    ins = [bool(sec[k]["contains"](p)) for k in solid]
    pick = [m for m in range(len(solid)) if ins[m]]
    if pick:
        m = min(pick, key=lambda m: (not sec[solid[m]]["closed"], sec[solid[m]]["area"], m))
    else:
        d = [float(np.linalg.norm(sec[k]["centroid"] - p)) for k in solid]
        m = min(range(len(solid)), key=lambda m: (not sec[solid[m]]["closed"], d[m], m))
    lp = sec[solid[m]]
    shells = _enclosing(sl, lp)
    enclosing = [w["area"] for w in shells]
    sib = [sec[k]["centroid"] for k in solid
           if k != solid[m] and sec[k]["closed"] and lp["area"] > 0
           and lp["area"] / jump <= sec[k]["area"] <= lp["area"] * jump]
    return dict(lp, inside=ins[m], enclosing=enclosing, shells=shells,
                n_inside=int(ins[m]) + len(enclosing), siblings=sib), len(solid)


def _enclosing(sl: _Slice, lp: dict) -> list:
    """The closed solid loops of the whole slice round p, other than the surface lp itself is
    part of (any loop sharing a crossing edge with it), biggest first. A solid loop whose hole
    holds p has its material round the hole, not round p."""
    own = sl.codes(lp["keys"])
    if sl.alone(own):
        return []
    held = sl.around()
    inner = {id(held[w["parent"]]) for w in held if w["hole"] and w["parent"] is not None}
    out = []
    for w in held:
        if w["hole"] or id(w) in inner:
            continue
        if np.isin(sl.codes(w["keys"]), own).any():
            continue
        out.append(w)
    return sorted(out, key=lambda w: -w["area"])


# ---------------------------------------------------------------------------------------
# necks: where a loop pinches between two hollows

def _hull_depth(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """How far each point of a 2D polygon lies inside the convex hull of its points (0 on
    the hull): the depth of the hollows of its outline."""
    order = np.lexsort((y, x)).tolist()

    def chain(idx):
        h = []
        for i in idx:
            while len(h) >= 2:
                a, b = h[-2], h[-1]
                if (x[b] - x[a]) * (y[i] - y[a]) - (y[b] - y[a]) * (x[i] - x[a]) <= 0:
                    h.pop()
                else:
                    break
            h.append(i)
        return h

    lower, upper = chain(order), chain(order[::-1])
    hull = np.asarray(lower[:-1] + upper[:-1], np.int64)
    if len(hull) < 3:
        return np.zeros(len(x))
    hx, hy = x[hull], y[hull]
    ex, ey = np.roll(hx, -1) - hx, np.roll(hy, -1) - hy
    ln = np.hypot(ex, ey)
    ok = ln > 0
    hx, hy, ex, ey, ln = hx[ok], hy[ok], ex[ok], ey[ok], ln[ok]
    d = (ex[None, :] * (y[:, None] - hy[None, :])
         - ey[None, :] * (x[:, None] - hx[None, :])) / ln[None, :]
    return np.maximum(d.min(axis=1), 0.0)


def _necks(x: np.ndarray, y: np.ndarray):
    """Chords of a closed 2D polygon that could be necks, narrowest first: (i, j, w) with
    i < j and w the chord's length. Both ends sit in hollows of the outline at least POCKET
    times w deep, and the outline on each side of the chord is at least NECK_ARC times w
    long. A convex outline has no hollows, so it has no necks, however long and thin it is."""
    k = len(x)
    none = (np.zeros(0, np.int64),) * 2 + (np.zeros(0),)
    if k < 6:
        return none
    depth = _hull_depth(x, y)
    step = np.hypot(np.roll(x, -1) - x, np.roll(y, -1) - y)
    s = np.concatenate([[0.0], np.cumsum(step)[:-1]])
    L = float(step.sum())
    deep = np.nonzero(depth > 0)[0]
    if len(deep) < 2:
        return none
    a, b = np.triu_indices(len(deep), 1)
    I, J = deep[a], deep[b]
    w = np.hypot(x[J] - x[I], y[J] - y[I])
    arc = s[J] - s[I]
    ok = (w > 0) & (np.minimum(arc, L - arc) >= NECK_ARC * w) & \
        (np.minimum(depth[I], depth[J]) >= POCKET * w)
    I, J, w = I[ok], J[ok], w[ok]
    o = np.lexsort((J, I, w))
    return I[o], J[o], w[o]


def _refine_chord(x, y, i: int, j: int, step: int):
    """The shortest chord between points within `step` of i and of j (all points, where the
    neck was found on every step-th point)."""
    if step <= 1:
        return i, j
    k = len(x)
    ii = np.arange(i - step + 1, i + step) % k
    jj = np.arange(j - step + 1, j + step) % k
    D = (x[ii][:, None] - x[jj][None, :]) ** 2 + (y[ii][:, None] - y[jj][None, :]) ** 2
    a, b = np.unravel_index(int(np.argmin(D)), D.shape)
    return int(ii[a]), int(jj[b])


def _halves(k: int, i: int, j: int):
    """The two parts of a closed polygon of k points split by the chord (i, j), i < j: the
    points from i to j, and from j round to i. Both keep the chord's ends."""
    return np.arange(i, j + 1), np.concatenate([np.arange(j, k), np.arange(0, i + 1)])


def _chord_parts(x, y, I, J, q):
    """For chords (I < J) of a polygon: the signed area of the part from I to J (closed by
    the chord), and whether the 2D point q lies in it (counted along a ray toward +x)."""
    x1, y1 = np.roll(x, -1), np.roll(y, -1)
    S = np.concatenate([[0.0], np.cumsum(x * y1 - x1 * y)])
    a1 = 0.5 * (S[J] - S[I] + x[J] * y[I] - x[I] * y[J])

    def crosses(xa, ya, xb, yb):
        with np.errstate(divide="ignore", invalid="ignore"):
            xc = xa + (q[1] - ya) * (xb - xa) / (yb - ya)
        return ((ya > q[1]) != (yb > q[1])) & (q[0] < xc)

    C = np.concatenate([[0], np.cumsum(crosses(x, y, x1, y1))])
    cc = crosses(x[J], y[J], x[I], y[I])
    return a1, ((C[J] - C[I] + cc) % 2) == 1


def _chord_inside(x, y, i: int, j: int) -> bool:
    """Whether the chord (i, j) runs through the polygon's material, not across a gap."""
    t = np.array([0.25, 0.5, 0.75])
    px = x[i] + t * (x[j] - x[i])
    py = y[i] + t * (y[j] - y[i])
    return bool(_in_polygon(x, y, px, py).all())


def _round_lobe(lp: dict, p, ref_area: float, jump: float):
    """The lobe of a merged loop that holds p and is a limb's own section: the part beyond a
    neck between two hollows, with an area within `jump` of ref_area, and wider across than
    the neck (the neck is narrower than the limb's own diameter). Returns (lobe indices, rest
    indices, neck width) or None. The narrowest such neck wins."""
    P = lp["pts"]
    k = len(P)
    if k < 6 or ref_area <= 0:
        return None
    o, u, v = lp["origin"], lp["u"], lp["v"]
    x, y = (P - o) @ u, (P - o) @ v
    q = np.array([float((p - o) @ u), float((p - o) @ v)])
    step = max(1, -(-k // NECK_PTS))
    ci = np.arange(0, k, step)
    xc, yc = x[ci], y[ci]
    I, J, _ = _necks(xc, yc)
    if not len(I):
        return None
    a1, in1 = _chord_parts(xc, yc, I, J, q)
    a2 = _shoelace(xc, yc) - a1
    in2 = ~in1 & _in_polygon(xc, yc, q[:1], q[1:])[0]
    area = np.where(in1, np.abs(a1), np.abs(a2))
    ok = (in1 | in2) & (area > ref_area / jump) & (area < ref_area * jump)
    for c in np.nonzero(ok)[0][:8].tolist():
        i, j = _refine_chord(x, y, int(ci[I[c]]), int(ci[J[c]]), step)
        i, j = min(i, j), max(i, j)
        width = math.hypot(x[j] - x[i], y[j] - y[i])
        if i == j or not _chord_inside(x, y, i, j):
            continue
        h1, h2 = _halves(k, i, j)
        along = np.array([x[j] - x[i], y[j] - y[i]]) / width
        for part, rest in ((h1, h2), (h2, h1)):
            if not _in_polygon(x[part], y[part], q[:1], q[1:])[0]:
                continue
            ar = abs(_shoelace(x[part], y[part]))
            span = x[part] * along[0] + y[part] * along[1]
            if ref_area / jump < ar < ref_area * jump and float(span.max() - span.min()) > width:
                return part, rest, width
    return None


def _range_ext(x: np.ndarray):
    """Tables of the largest and smallest x over every index range i..j (i <= j) of a polygon."""
    k = len(x)
    A = np.tile(x, (k, 1))
    A[np.tril_indices(k, -1)] = -np.inf
    hi = np.maximum.accumulate(A, axis=1)
    A[np.tril_indices(k, -1)] = np.inf
    lo = np.minimum.accumulate(A, axis=1)
    return lo, hi


def _trim_sides(P: np.ndarray, c, x0: float, max_w: float):
    """A horizontal trunk loop with every side part cut off: a part beyond a neck narrower
    than max_w, wholly on one side of the centre line x = x0, that reaches further out on
    that side than the rest of the loop does. An arm resting on the body, or held out at the
    shoulders' height, is such a part; a bulge within the trunk's own width (a breast, a
    belly) is not. Each round looks at the necks that cut off at least 1/JUMP of the most any
    neck cuts off (the whole arm, not its hand), keeps those that pinch about as much as the
    most pinched one (their ends deepest in their hollows for their width; within PINCH_TIE),
    and cuts at the one of them nearest the trunk: the root, neither out along an arm whose
    sides run parallel nor biting into the trunk past a round lobe. c is a point (x, y) of the
    centre-line stretch, which stays. Returns the indices of the points left and how many
    parts were cut off."""
    keep = np.arange(len(P))
    cut_off = 0
    while cut_off < 8 and len(P) >= 6:
        x, y = P[:, 0], P[:, 1]
        k = len(P)
        step = max(1, -(-k // NECK_PTS))
        ci = np.arange(0, k, step)
        xc, yc = x[ci], y[ci]
        if not _in_polygon(xc, yc, c[:1], c[1:])[0]:
            break
        I, J, w = _necks(xc, yc)
        sel = w < max_w
        I, J = I[sel], J[sel]
        if not len(I):
            break
        a1, in1 = _chord_parts(xc, yc, I, J, c)
        a2 = _shoelace(xc, yc) - a1
        lo, hi = _range_ext(xc - x0)
        kc = len(xc)
        lo1, hi1 = lo[I, J], hi[I, J]                       # the part from I to J
        lo2 = np.minimum(lo[J, kc - 1], lo[0, I])           # the part from J round to I
        hi2 = np.maximum(hi[J, kc - 1], hi[0, I])
        olo, ohi = np.where(in1, lo2, lo1), np.where(in1, hi2, hi1)
        slo, shi = np.where(in1, lo1, lo2), np.where(in1, hi1, hi2)
        right, left = ohi < 0, olo > 0
        ok = (right & (olo < slo)) | (left & (ohi > shi))
        if not ok.any():
            break
        cand = np.nonzero(ok)[0]
        off_area = np.abs(np.where(in1, a2, a1))[cand]
        big = off_area >= off_area.max() / JUMP               # the biggest side part, not a wrist
        cand, off_area = cand[big], off_area[big]
        dep = _hull_depth(xc, yc)
        pinch = np.minimum(dep[I[cand]], dep[J[cand]]) / w[sel][cand]
        tie = pinch >= PINCH_TIE * pinch.max()                # ...where it pinches most,
        cand, off_area = cand[tie], off_area[tie]
        cand = cand[np.lexsort((cand, -off_area))]            # ...nearest the trunk
        found = False
        for s in cand[:8].tolist():
            i, j = _refine_chord(x, y, int(ci[I[s]]), int(ci[J[s]]), step)
            i, j = min(i, j), max(i, j)
            if i == j or math.hypot(x[j] - x[i], y[j] - y[i]) >= max_w or not _chord_inside(x, y, i, j):
                continue
            h1, h2 = _halves(k, i, j)
            if _in_polygon(x[h1], y[h1], c[:1], c[1:])[0]:
                stay, off = h1, h2
            elif _in_polygon(x[h2], y[h2], c[:1], c[1:])[0]:
                stay, off = h2, h1
            else:
                continue
            dx, ds = x[off] - x0, x[stay] - x0
            if not ((dx < 0).all() and dx.min() < ds.min() or (dx > 0).all() and dx.max() > ds.max()):
                continue
            P, keep = P[stay], keep[stay]
            cut_off += 1
            found = True
            break
        if not found:
            break
    return keep, cut_off


# ---------------------------------------------------------------------------------------
# along an axis

def profile_along(V, T, a, b, steps: int = 24, ball=AUTO, H=None, r_guess=None, ref_area=None,
                  contact: bool = True, jump: float = JUMP) -> list:
    """Slices across the segment a -> b, at t = 0, 1/steps, ..., 1, each with normal (b - a).

    Each sample is {t, s (distance from a), p (the point on the axis), found, closed, inside,
    n_inside, enclosing, siblings, n_loops, end, r, area, reach, centroid, loop, ball,
    contact, neck, merged, slice_area, slice_closed}; `loop` is the loop_at() dict. `end` is
    True when the plane misses the mesh altogether (past its end, or in a gap between
    shells), as against a slice that only runs out of the ball. `reach` is the largest
    distance of the loop from p.

    ball: a number limits every slice to that radius; None does not limit; AUTO (the
    default) uses ball_radius(reach, H) on every slice, where reach follows the last closed
    loop round the axis, so a wide flat part keeps a ball as wide as itself. Before any loop
    gives a reach, the ball is 0.15 H; a first slice that runs out of it is taken whole. H is
    the body's size (its height when upright); it defaults to body_size(), which does not
    change when the mesh turns. r_guess and ref_area give the reach and the area of the limb
    just before a, when the profile starts part way along it.

    Contact (when `contact` is set): once a limb loop has been measured, a slice that runs
    out of the ball or grows more than `jump` times is looked at whole. If the loop round p
    pinches at a neck between two hollows, and the lobe beyond it holds p, is wider across
    than the neck (the neck is narrower than the limb) and has an area within `jump` of the
    last limb loop, the limb is lying against something here: the sample is that lobe
    (closed), with contact True, the neck's width, and the whole slice's area and closed
    flag in slice_area and slice_closed. The other side of the neck counts as a sibling when
    it is about the lobe's size. Wherever the whole slice was looked at, `merged` is its
    smallest solid loop round p."""
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
    reach, ref = r_guess, ref_area
    out = []
    for i in range(steps + 1):
        t = i / steps
        p = a + t * ax
        near = slabs.near(t * length)
        segs, keys, _ = _cut(V, near, _valid(near), p, n)
        sl = _Slice(segs, keys, p, n)
        bl = ball_radius(reach, H) if auto else ball
        lp, nl = _pick(sl, bl, jump)
        if auto and reach is None and len(segs) and not (lp and lp["closed"]):
            whole, nw = _pick(sl, None, jump)
            if whole is not None and whole["closed"] and whole["inside"]:
                lp, nl, bl = whole, nw, None
        smp = {"t": t, "s": t * length, "p": p, "end": not len(segs), "n_loops": nl, "ball": bl,
               "contact": False, "neck": None, "merged": None, "slice_area": lp["area"] if lp else 0.0,
               "slice_closed": bool(lp and lp["closed"])}
        if contact and ref and len(segs) and (lp is None or not lp["closed"] or lp["area"] > jump * ref):
            lobe, smp["merged"] = _contact_lobe(sl, ref, jump)
            if lobe is not None:
                lp = lobe
                smp.update(contact=True, neck=lobe["neck"])
        smp.update(found=lp is not None, closed=bool(lp and lp["closed"]),
                   inside=bool(lp and lp["inside"]),
                   n_inside=lp["n_inside"] if lp else 0, enclosing=lp["enclosing"] if lp else [],
                   siblings=lp["siblings"] if lp else [], r=lp["r"] if lp else 0.0,
                   area=lp["area"] if lp else 0.0, centroid=lp["centroid"] if lp else None, loop=lp,
                   reach=float(np.sqrt(_dist2(lp["pts"], p).max())) if lp else 0.0)
        if smp["closed"] and smp["inside"] and smp["r"] > 0:
            reach, ref = smp["reach"], smp["area"]
        out.append(smp)
    return out


def _contact_lobe(sl: _Slice, ref: float, jump: float):
    """(lobe, merged): the whole slice's smallest solid loop round p (or None), and the
    limb's own lobe of it when the limb lies against something here (see profile_along), as
    a loop_at() style dict, else None."""
    held = [w for w in sl.around() if not w["hole"]]
    if not held:
        return None, None
    p = sl.p
    w = held[min(range(len(held)), key=lambda k: (held[k]["area"], k))]
    if w["area"] <= jump * ref:
        return None, w
    res = _round_lobe(w, p, ref, jump)
    if res is None:
        return None, w
    part, rest, width = res
    lobe = {"pts": w["pts"][part], "keys": w["keys"][part], "closed": True}
    props = loop_props(lobe, sl.n)
    other = loop_props(w["pts"][rest], sl.n)
    sib = [other["centroid"]] if props["area"] / jump <= other["area"] <= props["area"] * jump else []
    shells = _enclosing(sl, w)
    return dict(lobe, **props, hole=False, parent=None, inside=True,
                enclosing=[x["area"] for x in shells], shells=shells, n_inside=1 + len(shells),
                siblings=sib, neck=width), w


def _limb_idx(profile: list, jump: float = JUMP) -> list:
    """Indices of the samples whose loop is the limb's: closed, and round the axis point, or
    (where the straight axis leaves a bent limb) at least 1/jump of the median area of the
    loops round it. A small loop beside the axis (a finger the axis runs between, the speck
    at a tip) is not the limb."""
    good = [i for i, s in enumerate(profile) if s["found"] and s["closed"] and s["area"] > 0]
    held = [i for i in good if profile[i].get("inside", True)]
    if not good:
        return []
    ref = float(np.median([profile[i]["area"] for i in (held or good)]))
    return [i for i in good if profile[i].get("inside", True) or profile[i]["area"] >= ref / jump]


def profile_centroids(profile: list, jump: float = JUMP):
    """(t, centroids) of the limb's own stretch of the profile, in order: (k,) and (k, 3).

    A sample counts when its loop is closed and holds the axis point, or, where the straight
    axis has left a bent limb, when its loop is at least 1/jump of the median area of those;
    a finger the axis runs between, or the speck at a tip, does not. Of those, the longest
    run whose area changes less than `jump` times from one to the next is kept (the first
    such run on a tie): a slice across the body at an end of the profile (one that starts at
    a shoulder point inside the torso) is not the limb, and would bend its line.
    Works on profile_along() and trunk_axis() samples alike."""
    idx = _limb_idx(profile, jump)
    runs, cur = [], []
    for i in idx:
        if cur:
            r = profile[i]["area"] / profile[cur[-1]]["area"]
            if r > jump or r < 1.0 / jump:
                runs.append(cur)
                cur = []
        cur.append(i)
    if cur:
        runs.append(cur)
    good = [profile[i] for i in max(runs, key=len)] if runs else []
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


def crease_along(profile: list, jump: float = JUMP, skip_tip: bool = True, reverse: bool = False,
                 start=None, contact_span: float = CONTACT_SPAN):
    """Where a limb merges into the body: walking the profile from its first sample (build it
    from the limb's free end toward the body; reverse walks from the last), the first place
    where
      - the slice area grows more than `jump` times from one sample to the next ("jump"),
      - the loop stops being closed: it runs out of the ball ("open"),
      - the axis runs inside another shell more than `jump` times the limb's area: an arm
        that is its own shell, pushed into the body ("split"). A shell only a little bigger
        (a sleeve, armour, cloth over the limb) does not count; the walk keeps to the limb,
      - or the axis has left the limb: the nearest loop does not hold it and is under
        1/jump^2 of the limb's area, as where an arm lying along the body ends at the
        shoulder and the axis runs on past it ("gone").
    The 1.8 matches the measured armpit and groin jumps; it is a ratio, not a size.

    The walk starts at the first closed loop that holds the axis point (a finger the axis
    runs between is not the limb), at or past `start` when given. With skip_tip it also
    skips the samples closer to that first loop than their own radius: a rounded tip grows
    fast too. A slice that misses the mesh altogether (past the limb's end, a gap between
    shells, a height trunk_axis found nothing at) is skipped, so a limb that just ends has
    no crease.

    Contact samples (profile_along: the limb lying against the body, followed past a neck)
    are part of the limb, so an arm resting on the ribs or thighs that touch walk on to the
    real root. A contact shorter than contact_span limb radii is a limb going into the body
    at a slant, not lying along it: the crease is then put where it first merged.

    A walk that starts inside one of several parts side by side (the axis through one
    finger) stops where they join, as a leg stops at the pelvis: areas alone cannot tell the
    two apart. `joined` says how many other loops of about the limb's size in the last limb
    slice lie inside the merged one: 0 for a limb meeting the body, 1 for a leg meeting its
    twin, more for fingers meeting the palm (for "split", inside the shell run into). Walk
    again with start past a crease the caller does not want.

    Works on profile_along() samples; trunk_axis() samples work too (z stands in for s).

    Returns {t, p, before, after, reason, ratio, contact, joined} or None. t (and p) lie
    halfway between the last limb sample (index `before`) and the first sample past the
    crease (`after`); contact lists the (first t, last t) of every contact stretch walked."""
    return _crease(profile, jump, skip_tip, reverse, start, contact_span, True)


def _crease(profile, jump, skip_tip, reverse, start, contact_span, held):
    """crease_along(); with held False the first limb loop need not hold the axis point (a
    finer pass between two samples already known to be the limb's)."""
    order = range(len(profile) - 1, -1, -1) if reverse else range(len(profile))
    prev, tip, base = None, None, None
    spans, run = [], []

    def pos(smp):
        return smp.get("s", smp.get("z", smp["t"]))

    for i in order:
        smp = profile[i]
        if smp.get("end") or smp.get("p") is None:
            continue
        if start is not None and (smp["t"] > start if reverse else smp["t"] < start):
            continue
        good = smp["found"] and smp["closed"]
        if prev is None:
            if not good or (held and not smp.get("inside", True)) \
                    or _in_bigger_shell(smp, smp["area"], jump):
                continue
            if skip_tip:
                if tip is None:
                    tip = pos(smp)
                if abs(pos(smp) - tip) < smp["r"]:
                    continue
            prev = base = i
            continue
        last = profile[prev]
        ratio = smp["area"] / last["area"] if last["area"] > 0 else math.inf
        shell = _in_bigger_shell(smp, last["area"], jump) if good else 0.0
        gone = good and not smp.get("inside", True) and ratio < 1.0 / (jump * jump)
        why = ("open" if not good else "split" if shell else "jump" if ratio > jump else
               "gone" if gone else None)
        if why:
            if why == "split":
                ratio = shell
            b0, a0 = prev, i
            if run:
                first = profile[run[0]]
                if abs(pos(smp) - pos(first)) < contact_span * profile[base]["r"]:
                    b0, a0 = base, run[0]
                    why = "jump" if first.get("slice_closed") else "open"
                    ratio = first.get("slice_area", 0.0) / profile[base]["area"] \
                        if profile[base]["area"] > 0 else math.inf
                    run = []
            if run:
                spans.append((profile[run[0]]["t"], profile[run[-1]]["t"]))
            bs, af = profile[b0], profile[a0]
            merged = None
            if why == "split" and af.get("loop") and af["loop"].get("shells"):
                merged = af["loop"]["shells"][0]
            elif af.get("closed") and af.get("loop") is not None:
                merged = af["loop"]
            elif af.get("merged") is not None:
                merged = af["merged"]
            joined = sum(bool(merged["contains"](c)) for c in bs.get("siblings") or []) if merged else 0
            return {"t": 0.5 * (bs["t"] + af["t"]), "p": 0.5 * (bs["p"] + af["p"]),
                    "before": b0, "after": a0, "reason": why, "ratio": ratio,
                    "contact": spans, "joined": joined}
        if smp.get("contact"):
            run.append(i)
        else:
            if run:
                spans.append((profile[run[0]]["t"], profile[run[-1]]["t"]))
            run, base = [], i
        prev = i
    return None


def find_crease(V, T, a, b, steps: int = 24, ball=AUTO, H=None, jump: float = JUMP, refine: int = 2,
                start=None):
    """crease_along() on profile_along(a, b), then narrowed down: each round (at most
    `refine`) slices the gap between the two samples around the crease 8 times finer, until
    the gap is under a tenth of the limb's radius. Returns the crease dict with
    the refined t and p, plus r and centroid of the last limb loop before the crease (where
    the limb itself is still measured, not the merged slice), or None without a crease.
    The finer rounds follow a contact lobe only when the crease came at the end of one."""
    if isinstance(ball, str) and H is None:
        H = body_size(V, T)
    prof = profile_along(V, T, a, b, steps, ball, H, jump=jump)
    c = crease_along(prof, jump, start=start)
    if c is None:
        return None
    a, b = np.asarray(a, float), np.asarray(b, float)
    t0, t1 = prof[c["before"]]["t"], prof[c["after"]]["t"]
    limb = prof[c["before"]]
    follow = bool(limb.get("contact"))
    length = float(np.linalg.norm(b - a))
    for _ in range(max(int(refine), 0)):
        if (t1 - t0) * length < REFINE_TO * limb["r"]:
            break
        sub = profile_along(V, T, a + t0 * (b - a), a + t1 * (b - a), 8, ball, H, r_guess=limb["reach"],
                            ref_area=limb["area"], contact=follow, jump=jump)
        cs = _crease(sub, jump, False, False, None, 0.0, False)
        if cs is None:
            break
        t0, t1 = t0 + (t1 - t0) * sub[cs["before"]]["t"], t0 + (t1 - t0) * sub[cs["after"]]["t"]
        limb = sub[cs["before"]]
        c = dict(c, reason=cs["reason"], ratio=cs["ratio"])
    t = 0.5 * (t0 + t1)
    return dict(c, t=t, p=a + t * (b - a), r=limb["r"], centroid=limb["centroid"])


def area_jumps(profile: list, jump: float = JUMP) -> list:
    """Every pair of neighbouring limb samples (see profile_centroids) whose material round
    the axis changes more than `jump` times, either way: [{t, before, after, ratio}], ratio =
    later / earlier. The material round the axis is the sample's own loop, or the biggest
    shell round it when there is one, so a grip shows as a jump up where the hand starts and
    a jump down where it ends, whether the prop and the hand are one surface or two."""
    ok = set(_limb_idx(profile, jump))
    out = []
    for i in range(len(profile) - 1):
        if i not in ok or i + 1 not in ok:
            continue
        s0, s1 = profile[i], profile[i + 1]
        m0 = max([s0["area"]] + list(s0.get("enclosing") or []))
        m1 = max([s1["area"]] + list(s1.get("enclosing") or []))
        ratio = m1 / m0
        if ratio > jump or ratio < 1.0 / jump:
            out.append({"t": 0.5 * (s0["t"] + s1["t"]), "before": i, "after": i + 1, "ratio": ratio})
    return out


def narrowest_along(profile: list, t0: float = 0.0, t1: float = 1.0):
    """(t_min, contrast): where the limb's loops (see profile_centroids) between t0 and t1
    are thinnest, and contrast = r_min / median r over that stretch (small means a clear
    narrowing).

    When the thinnest part is a straight stretch (radii within 3% of the smallest), t_min is
    the end of it where the shape widens more: a wrist sits where the hand begins, not in
    the middle of the forearm. (None, 1.0) with fewer than 3 loops."""
    lo, hi = min(t0, t1), max(t0, t1)
    idx = [i for i in _limb_idx(profile) if profile[i]["r"] > 0 and lo <= profile[i]["t"] <= hi]
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

def _ray_prep(V, T, sheets=AUTO):
    V = np.asarray(V, float)
    T = np.asarray(T, np.int64).reshape(-1, 3)
    ids = np.arange(len(T))
    if isinstance(sheets, str):
        sheets = sheet_tris(V, T)
    if sheets is not None:
        solid = ~np.asarray(sheets, bool).ravel()[:len(T)]
        if not solid.all():
            T, ids = T[solid], ids[solid]
    size = float((V.max(axis=0) - V.min(axis=0)).max()) if len(V) else 0.0
    return V, T, size, ids


def _hits(prep, o, d):
    V, T, size, ids = prep
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
    return th[keep], nr[keep], ids[idx[keep]]


def ray_hits(V, T, o, d, with_tris: bool = False, sheets=AUTO):
    """Every place the ray from o along d meets the surface (vectorised Moller-Trumbore over
    all triangles; the plain-numpy stand-in for repeated BVH casts).

    Returns (t, normals) sorted by t: t is the distance along the unit direction (t > 0),
    normals the unit face normals from the winding. A ray through a shared edge or vertex
    gives one hit there, not one per triangle. With with_tris, also the triangle ids.

    sheets: the triangles to look through. AUTO (the default) uses sheet_tris(): a single-
    sided cape or skirt holds no volume, and a hit on it would have nothing to pair with in
    ray_spans() or inside(). A bool mask per triangle gives them directly (worked out once
    for many rays); None keeps every hit."""
    t, nr, idx = _hits(_ray_prep(V, T, sheets), o, d)
    return (t, nr, idx) if with_tris else (t, nr)


def ray_spans(ts, normals, d):
    """Pairs ray hits into the stretches where the ray is inside solid material.

    A hit whose normal faces the ray (n . d < 0) is an entry, otherwise an exit. A nesting
    count keeps overlapping shells as one span (entry, entry, exit, exit). When the normals
    do not add up (an exit while outside, still inside at the end, an edge-on hit), the hits
    are paired in order instead: (1st, 2nd), (3rd, 4th), ...

    Returns (spans, by_normals): spans is a list of (t_in, t_out) in order along the ray;
    by_normals is False when the in-order pairing was used. The ray must start outside.
    Give it the hits of ray_hits(), which leaves out single-sided sheets (a cape)."""
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


def inside(V, T, p, sheets=AUTO) -> bool:
    """Whether p is inside the mesh: each of three rays (+X, -X, +Y) votes inside when it
    meets the surface an odd number of times; 2 of 3 votes win. One ray that slips through
    a hole in an open mesh is outvoted. Single-sided sheets (a cape) are looked through, as
    in ray_hits(); `sheets` works the same way."""
    prep = _ray_prep(V, T, sheets)
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


def trunk_axis(V, T, z0: float, z1: float, x0: float, steps: int = 12, ball=None,
               trim: bool = True) -> list:
    """Horizontal slices from z0 to z1 (steps + 1 of them) that follow the trunk.

    At each height, the centre line x = x0 runs through some loops. The biggest of them is
    the trunk (a tail or a hand in the same slice is smaller); y_mid is the middle of the
    longest stretch of the centre line inside it. The sample's loop is the smallest closed
    loop around (x0, y_mid, z), so a shell over the trunk (armour, a coat) does not count.

    With trim, every part of that loop that hangs beyond a neck (between two hollows,
    narrower than the trunk is deep on the centre line) and lies wholly on one side of the
    centre line is cut off: an arm resting on the body, or held out at the shoulders' height,
    is not trunk. `trimmed` counts the parts cut off.

    Each sample is {t, z, p, found, closed, inside, end, r, area, centroid, width (x extent),
    depth (y extent), loop, trimmed}. `end` is True when the height misses the mesh
    altogether (above the head, below the feet). The centroids are the trunk's medial axis;
    profile_centroids() gives them as an array."""
    V = np.asarray(V, float)
    T = np.asarray(T, np.int64).reshape(-1, 3)
    up = np.array([0.0, 0.0, 1.0])
    yc = float(np.median(V[np.unique(T), 1])) if len(T) else 0.0
    slabs = _Slabs(V, T, np.zeros(3), up)
    out = []
    for i in range(steps + 1):
        t = i / max(steps, 1)
        z = z0 + t * (z1 - z0)
        near = slabs.near(z)
        q = np.array([x0, yc, z])
        segs, keys, _ = _cut(V, near, _valid(near), q, up)
        sl = _Slice(segs, keys, q, up)
        lps = [lp for lp in sl.within(ball) if lp["closed"] and not lp["hole"]]
        best = None
        for k, lp in enumerate(lps):
            ys = _line_crossings(lp["pts"], x0)
            for j in range(0, len(ys) - 1, 2):
                key = (lp["area"], ys[j + 1] - ys[j], -k)
                if best is None or key > best[0]:
                    best = (key, 0.5 * (ys[j] + ys[j + 1]), ys[j + 1] - ys[j])
        smp = {"t": t, "z": z, "p": None, "found": False, "closed": False, "inside": False,
               "end": not len(segs), "r": 0.0, "area": 0.0, "centroid": None, "width": 0.0,
               "depth": 0.0, "loop": None, "trimmed": 0}
        if best is not None:
            p = np.array([x0, best[1], z])
            around = [k for k, lp in enumerate(lps) if lp["contains"](p)]
            smp["p"] = p
            if around:
                lp = lps[min(around, key=lambda k: (lps[k]["area"], k))]
                cut_off = 0
                if trim:
                    kept, cut_off = _trim_sides(lp["pts"], np.array([x0, best[1]]), x0, best[2])
                    if cut_off:
                        lp = {"pts": lp["pts"][kept], "keys": lp["keys"][kept], "closed": True}
                        lp = dict(lp, **loop_props(lp, up), hole=False, parent=None)
                ext = lp["pts"].max(axis=0) - lp["pts"].min(axis=0)
                smp.update(found=True, closed=True, inside=True, r=lp["r"], area=lp["area"],
                           centroid=lp["centroid"], width=float(ext[0]), depth=float(ext[1]),
                           loop=lp, trimmed=cut_off)
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
