"""Extra parts of a body (tail, horn, ear, pouch...) found and cut by their SHAPE.

Principles (no model-specific numbers; every threshold is relative to the part itself):
  - A part is much thinner than what it grows out of. Thickness = shape diameter: how far a
    ray travels inward before it leaves the surface again (median of a small cone of rays).
  - A part is cut at its NECK: grown from a seed over the surface while it stays thin, it
    stops where the surface turns into the body (the inward rays suddenly go a long way).
    Asymmetry or a guessed bone only tell us that a part is there, never where it ends.
  - A cut must be one short closed ring. A patch with a long ragged border is not a part.
  - A part with a twin on the other side (an arm, an ear) is a pair, not a one-sided part:
    when the director picks a side, that side simply wins for both.
"""

from __future__ import annotations

import numpy as np


class MeshArrays:
    """The mesh as numpy arrays, read once (AI meshes have millions of vertices)."""

    def __init__(self, me):
        n = len(me.vertices)
        co = np.empty(n * 3, np.float32)
        me.vertices.foreach_get("co", co)
        self.co = co.reshape(-1, 3).astype(np.float64)
        nr = np.empty(n * 3, np.float32)
        me.vertices.foreach_get("normal", nr)
        self.nrm = nr.reshape(-1, 3).astype(np.float64)
        ev = np.empty(len(me.edges) * 2, np.int32)
        me.edges.foreach_get("vertices", ev)
        self.ev = ev.reshape(-1, 2).astype(np.int64)
        ls = np.empty(len(me.polygons), np.int32)
        me.polygons.foreach_get("loop_start", ls)
        lt = np.empty(len(me.polygons), np.int32)
        me.polygons.foreach_get("loop_total", lt)
        lv = np.empty(len(me.loops), np.int32)
        me.loops.foreach_get("vertex_index", lv)
        self.ls, self.lt, self.lv = ls.astype(np.int64), lt.astype(np.int64), lv.astype(np.int64)
        self.n = n
        self.size = float((self.co.max(axis=0) - self.co.min(axis=0)).max()) if n else 1.0
        w = np.linalg.norm(self.co[self.ev[:, 0]] - self.co[self.ev[:, 1]], axis=1) if len(self.ev) else np.ones(1)
        self.edge_len = float(np.median(w)) or 1e-6

    def local_tree(self, local: np.ndarray):
        """BVH of the faces whose vertices are all inside `local` (a neighbourhood)."""
        from mathutils import Vector
        from mathutils.bvhtree import BVHTree
        inl = local[self.lv]
        allin = np.minimum.reduceat(inl.astype(np.int8), self.ls) > 0 if len(self.ls) else np.zeros(0, bool)
        idx = np.nonzero(local)[0]
        remap = np.full(self.n, -1, np.int64)
        remap[idx] = np.arange(len(idx))
        verts = [Vector(p) for p in self.co[idx]]
        polys = []
        for f in np.nonzero(allin)[0]:
            s, t = self.ls[f], self.lt[f]
            polys.append(tuple(int(x) for x in remap[self.lv[s:s + t]]))
        return BVHTree.FromPolygons(verts, polys) if polys else None


def thickness(arr: MeshArrays, tree, idx: np.ndarray, limit: float) -> np.ndarray:
    """Shape diameter at the given vertices: median distance a cone of 5 inward rays travels
    before it meets the surface again (rays that meet nothing within `limit` count as limit)."""
    from mathutils import Vector
    out = np.full(len(idx), limit)
    if tree is None:
        return out
    eps = 1e-5 * arr.size
    for j, i in enumerate(idx):
        n = -arr.nrm[i]
        ln = np.linalg.norm(n)
        if ln < 1e-9:
            continue
        n = n / ln
        a = np.cross(n, (0.0, 0.0, 1.0) if abs(n[2]) < 0.9 else (1.0, 0.0, 0.0))
        a /= np.linalg.norm(a)
        b = np.cross(n, a)
        o = Vector(arr.co[i] + n * eps)
        ds = []
        for d in (n, n + 0.45 * a, n - 0.45 * a, n + 0.45 * b, n - 0.45 * b):
            h = tree.ray_cast(o, Vector(d / np.linalg.norm(d)), limit)
            ds.append(h[3] if h[0] is not None else limit)
        out[j] = float(np.median(ds))
    return out


def _sample(idx: np.ndarray, k: int) -> np.ndarray:
    return idx if len(idx) <= k else idx[:: len(idx) // k + 1]


def _components(n: int, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    from .appendages import _components as comp
    return comp(n, a, b)


def neck_region(arr: MeshArrays, seed: np.ndarray, max_share: float = 0.15, body=None) -> dict | None:
    """One part: see grow_parts."""
    return grow_parts(arr, [seed], max_share, body)[0]


def grow_parts(arr: MeshArrays, seeds: list, max_share: float = 0.15, body=None,
               t_body: float | None = None) -> list:
    """Grow every seed (vertices of a part, maybe only a fragment of it) over the surface while
    the surface stays thin, and stop at the neck where it turns into the thick body.

    Thin = shape diameter under 2.5 stems or the geometric mean of stem and body thickness,
    whichever is larger: a tapering horn keeps growing to its base, a tail stops where the
    rump begins, whatever their absolute size. All parts grow together, ring by
    ring, and a vertex belongs to the first part that reaches it: an ear and a horn whose
    roots touch stop at each other instead of one swallowing the other.
    Per seed: {"mask", "thickness", "body_thickness", "ring": (centre, normal_into_body,
    radius), "ok": one short ring, "why"} or None when there is no part."""
    n = arr.n
    label = np.zeros(n, np.int32)
    if body is None:                              # surely body: everything that is no seed
        body = np.ones(n, bool)
        for sd in seeds:
            body &= ~sd
    bidx = np.nonzero(body)[0]
    # an even sample of the body (by area, the same on a coarse or a dense mesh): "the body
    # nearest to a part" then covers the same patch whatever the resolution
    bsam = bidx[:: max(1, len(bidx) // 40_000)]
    states = []
    for k, seed in enumerate(seeds, start=1):
        sidx = np.nonzero(seed)[0]
        if len(sidx) < 8 or len(bidx) < 8:
            states.append(None)
            continue
        # the body around = the body surface nearest to the part (where it will meet it), even
        # when the visible fragment of the part is far from it (the tip of a long horn)
        c = arr.co[sidx].mean(axis=0)
        near = bsam[np.argsort(np.linalg.norm(arr.co[bsam] - c, axis=1))[:800]]
        slo, shi = arr.co[sidx].min(axis=0), arr.co[sidx].max(axis=0)
        sext = float((shi - slo).max())
        m1 = max(0.6 * sext, 0.06 * arr.size)        # room for the hidden rest of the part
        m2 = 0.03 * arr.size
        lo = np.minimum(slo - m1, arr.co[near].min(axis=0) - m2)
        hi = np.maximum(shi + m1, arr.co[near].max(axis=0) + m2)
        ext = float((hi - lo).max())
        margin = 0.0
        local = np.all((arr.co >= lo) & (arr.co <= hi), axis=1)
        tree = arr.local_tree(local)
        limit = 2.0 * (ext + margin)
        Ts = thickness(arr, tree, sidx, limit)
        t_stem = float(np.percentile(Ts, 30))     # the stem, not a tuft at the end
        if t_body is None:
            # upper quartile: some of the nearest "body" may still be the part's own hidden stem
            tb = float(np.percentile(thickness(arr, tree, _sample(near, 400), limit), 75))
        else:
            tb = float(t_body)                    # the trunk, measured by the caller
        if t_stem >= 0.6 * tb:
            states.append(None)                   # as thick as the body around: not a part
            continue
        # thin enough to belong: well under the body, and within a few stems (a tapering horn
        # doubles its girth to the base; the rump is ten times a tail)
        thr = float(max(2.5 * t_stem, np.sqrt(t_stem * tb)))
        T = {int(i): float(t) for i, t in zip(sidx, Ts)}
        start = sidx[(Ts < thr) & (label[sidx] == 0)]
        label[start] = k
        le = arr.ev[local[arr.ev[:, 0]] & local[arr.ev[:, 1]]]
        states.append({"k": k, "local": local, "tree": tree, "limit": limit, "thr": thr, "T": T,
                       "t_stem": t_stem, "t_body": tb, "le": le, "rejected": np.zeros(n, bool),
                       "active": True})
    cap = int(max_share * n)
    while any(st and st["active"] for st in states):
        for st in states:
            if not st or not st["active"]:
                continue
            le, k = st["le"], st["k"]
            a_in, b_in = label[le[:, 0]] == k, label[le[:, 1]] == k
            cand = np.unique(np.concatenate([le[a_in & ~b_in, 1], le[b_in & ~a_in, 0]]))
            cand = cand[(label[cand] == 0) & ~st["rejected"][cand]]
            if len(cand) == 0:
                st["active"] = False
                continue
            tc = thickness(arr, st["tree"], cand, st["limit"])
            for i, t in zip(cand, tc):
                st["T"][int(i)] = float(t)
            ok = tc < st["thr"]
            label[cand[ok]] = k
            st["rejected"][cand[~ok]] = True
            if (label == k).sum() > cap:
                st["active"] = False
                st["spread"] = True
    # two fragments of ONE part (a tail the bone test cut in two) meet halfway along it: a
    # part whose cut touches another part more than the body is that part
    ev = arr.ev
    for _ in range(len(states)):
        merged = False
        for st in states:
            if not st or st.get("spread") or not (label == st["k"]).any():
                continue
            k = st["k"]
            a_k, b_k = label[ev[:, 0]] == k, label[ev[:, 1]] == k
            other = np.concatenate([label[ev[a_k & ~b_k, 1]], label[ev[b_k & ~a_k, 0]]])
            if len(other) == 0:
                continue
            vals, cnt = np.unique(other, return_counts=True)
            j = int(vals[np.argmax(cnt)])
            if j > 0 and cnt.max() >= 0.5 * len(other):
                target = next(t for t in states if t and t["k"] == j)
                label[label == k] = j
                target["T"].update(st["T"])
                target["local"] = target["local"] | st["local"]
                target["le"] = arr.ev[target["local"][arr.ev[:, 0]] & target["local"][arr.ev[:, 1]]]
                st["merged_into"] = j
                merged = True
        if not merged:
            break
    out = []
    for st in states:
        if st is None or st.get("spread"):
            out.append(None)
            continue
        if st.get("merged_into"):
            j = st["merged_into"]
            while True:                               # follow merges to the final part
                t = next(x for x in states if x and x["k"] == j)
                if not t.get("merged_into"):
                    break
                j = t["merged_into"]
            out.append({"merged_into": j - 1})
            continue
        if not (label == st["k"]).any():
            out.append(None)
            continue
        out.append(_finish_part(arr, label, st))
    # callers get the finished part for every seed of it
    for i, r in enumerate(out):
        if r is not None and "merged_into" in r:
            out[i] = None
    return out


def _finish_part(arr: MeshArrays, label: np.ndarray, st: dict) -> dict:
    n, k, local, le = arr.n, st["k"], st["local"], st["le"]
    region = label == k
    # keep the biggest connected piece, then fill what it encloses (a tuft at the tail tip is
    # thicker than the tail but still part of it)
    e_in = region[le[:, 0]] & region[le[:, 1]]
    lab = _components(n, le[e_in, 0], le[e_in, 1])
    ids, cnt = np.unique(lab[region], return_counts=True)
    region = region & (lab == ids[np.argmax(cnt)])
    out_l = local & ~region
    e_out = out_l[le[:, 0]] & out_l[le[:, 1]]
    lab2 = _components(n, le[e_out, 0], le[e_out, 1])
    # an island is enclosed only if it does not reach the edge of the neighbourhood (a leg cut
    # by the box edge is connected to the body outside it), touches this part, and belongs to
    # no other part
    edge_v = np.zeros(n, bool)
    xb = local[arr.ev[:, 0]] != local[arr.ev[:, 1]]
    edge_v[arr.ev[xb].ravel()] = True
    open_ids = np.unique(lab2[out_l & (edge_v | (label > 0))])
    ids2, cnt2 = np.unique(lab2[out_l], return_counts=True)
    if len(ids2) > 1:
        body = ids2[np.argmax(cnt2)]
        touch = np.unique(np.concatenate([lab2[le[region[le[:, 0]] & out_l[le[:, 1]], 1]],
                                          lab2[le[region[le[:, 1]] & out_l[le[:, 0]], 0]]]))
        enclosed = out_l & (lab2 != body) & ~np.isin(lab2, open_ids) & np.isin(lab2, touch)
        region = region | enclosed
    Tv = np.array([t for i, t in st["T"].items() if region[i]])
    res = {"mask": region, "thickness": float(np.percentile(Tv, 30)) if len(Tv) else st["t_stem"],
           "body_thickness": st["t_body"], "ring": None, "ok": False, "why": ""}
    # the cut ring: part vertices next to the rest
    a_in, b_in = region[arr.ev[:, 0]], region[arr.ev[:, 1]]
    cross = a_in ^ b_in
    ring = np.unique(np.where(a_in[cross], arr.ev[cross, 0], arr.ev[cross, 1]))
    if len(ring) == 0:
        res["ok"], res["why"] = True, "a separate shell: taken whole, nothing to cut"
        return res
    if len(ring) < 3:
        res["why"] = "no cut ring"
        return res
    rc = arr.co[ring]
    centre = rc.mean(axis=0)
    _u, _s, vt = np.linalg.svd(rc - centre, full_matrices=False)
    normal = vt[2]
    pc = arr.co[region].mean(axis=0)
    if normal @ (pc - centre) > 0:
        normal = -normal                              # pointing away from the part: into the body
    radius = float(np.median(np.linalg.norm(rc - centre, axis=1)))
    res["ring"] = (centre, normal, radius)
    # one short ring: the ring is small against the part, and in one piece. Both ends of the
    # cut edges form a band two vertices wide around the cut: connected along the band for
    # triangles and quads alike
    pext = float((arr.co[region].max(axis=0) - arr.co[region].min(axis=0)).max())
    band = np.unique(arr.ev[cross].ravel())
    ring_m = np.zeros(n, bool)
    ring_m[band] = True
    re_ = arr.ev[ring_m[arr.ev[:, 0]] & ring_m[arr.ev[:, 1]]]
    rl = _components(n, re_[:, 0], re_[:, 1])
    _ri, rcnt = np.unique(rl[band], return_counts=True)
    main_share = rcnt.max() / len(band)
    if 2.0 * float(np.linalg.norm(rc - centre, axis=1).max()) > 0.8 * pext:
        res["why"] = "the cut runs along the part, not around it"
    elif main_share < 0.9:
        res["why"] = "the cut is in pieces"
    else:
        res["ok"] = True
    return res


def mirror_far(co: np.ndarray, cell: float) -> np.ndarray:
    """True where a vertex's mirror image (across X = 0) has no vertex of the mesh within about
    one cell: grid lookup, fast on millions of vertices."""
    def key(q):
        return (q[:, 0] * 2_000_003 + q[:, 1]) * 2_000_003 + q[:, 2]
    lo = co.min(axis=0) - 2 * cell
    q = np.floor((co - lo) / cell).astype(np.int64)
    occ = np.unique(key(q))
    m = co.copy()
    m[:, 0] = -m[:, 0]
    qm = np.floor((m - lo) / cell).astype(np.int64)
    found = np.zeros(len(co), bool)
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for dz in (-1, 0, 1):
                k = key(qm + np.array([dx, dy, dz]))
                i = np.clip(np.searchsorted(occ, k), 0, len(occ) - 1)
                found |= occ[i] == k
    return ~found


def mirror_found(co_all: np.ndarray, pts: np.ndarray, cell: float) -> np.ndarray:
    """For each point: is there a vertex of the mesh near its mirror image (within ~cell)?"""
    def key(q):
        return (q[:, 0] * 2_000_003 + q[:, 1]) * 2_000_003 + q[:, 2]
    lo = np.minimum(co_all.min(axis=0), (pts * [-1, 1, 1]).min(axis=0)) - 2 * cell
    occ = np.unique(key(np.floor((co_all - lo) / cell).astype(np.int64)))
    m = pts.copy()
    m[:, 0] = -m[:, 0]
    qm = np.floor((m - lo) / cell).astype(np.int64)
    found = np.zeros(len(pts), bool)
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for dz in (-1, 0, 1):
                k = key(qm + np.array([dx, dy, dz]))
                i = np.clip(np.searchsorted(occ, k), 0, len(occ) - 1)
                found |= occ[i] == k
    return found


def has_twin(arr: MeshArrays, mask: np.ndarray, part_thickness: float) -> bool:
    """The part's mirror image lies on the surface (within about the part's own thickness)
    for most of it: there is a twin on the other side - an arm in another pose, an ear at
    another angle. A tail curling to one side mirrors into empty air."""
    idx = _sample(np.nonzero(mask)[0], 4000)
    if len(idx) == 0 or mask.all():
        return False
    cell = max(part_thickness, 2.0 * arr.edge_len)
    # against the REST of the surface: a part on the centre line mirrors onto itself, which
    # makes it symmetric, not paired
    return float(mirror_found(arr.co[~mask], arr.co[idx], cell).mean()) > 0.5


def one_sided_parts(me, taken=None, high: float = 0.05, low: float = 0.012, min_extent: float = 0.08,
                    max_share: float = 0.15, arr: MeshArrays | None = None, report: list | None = None) -> np.ndarray:
    """Parts that mirroring would copy or delete because they have no twin: a tail curling to
    one side, a single horn, a pouch on one hip. Seeds: regions whose mirror image is far off
    (hysteresis like an edge detector). Pairs (an arm raised higher than the other) are
    skipped: the chosen side wins for both. Each part is cut at its neck (neck_region) and
    only taken when the cut is one short ring. Returns ids (0 = body) numbered after `taken`."""
    arr = arr or MeshArrays(me)
    n = arr.n
    ids = np.zeros(n, np.int32)
    if n == 0:
        return ids
    co, size = arr.co, arr.size
    far_hi = mirror_far(co, high * size)
    far_lo = mirror_far(co, low * size)
    if taken is not None:
        far_lo &= taken == 0
        far_hi &= taken == 0
    if not far_hi.any():
        return ids
    ev = arr.ev
    keep = far_lo[ev[:, 0]] & far_lo[ev[:, 1]]
    lab = _components(n, ev[keep, 0], ev[keep, 1])
    seeds = []
    for root in np.unique(lab[far_hi & far_lo]):
        sel = (lab == root) & far_lo
        if sel.sum() > max_share * n:
            continue
        p = co[sel]
        ext = float((p.max(axis=0) - p.min(axis=0)).max())
        if ext < min_extent * size:
            continue
        seeds.append((sel, p.mean(axis=0), ext))
    k = int(taken.max()) if taken is not None and len(taken) else 0
    for sel, c, _ext in seeds:
        if (ids[sel] > 0).mean() > 0.5:
            continue                                  # already inside a part found before
        nk = neck_region(arr, sel, max_share, body=~far_lo)
        if nk is None or not nk["ok"]:
            if report is not None:
                report.append(("kept", c, nk["why"] if nk else "not thinner than the body"))
            continue
        if has_twin(arr, nk["mask"], nk["thickness"]):
            if report is not None:
                report.append(("pair", c, "differs from its twin: the chosen side is used"))
            continue
        m = nk["mask"] & (ids == 0)
        if taken is not None:
            m &= taken == 0
        k += 1
        ids[m] = k
        if report is not None:
            report.append(("split", c, "one-sided, cut at its root"))
    return ids
