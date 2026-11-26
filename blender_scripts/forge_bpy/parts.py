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

    def to_world(self, m) -> None:
        """Measure in world space (object matrix m, 4x4 numpy): coordinates, normals, size."""
        m = np.asarray(m, float)
        self.co = self.co @ m[:3, :3].T + m[:3, 3]
        nr = self.nrm @ np.linalg.inv(m[:3, :3])
        self.nrm = nr / np.maximum(np.linalg.norm(nr, axis=1, keepdims=True), 1e-12)
        self.size = float((self.co.max(axis=0) - self.co.min(axis=0)).max()) if self.n else 1.0
        w = np.linalg.norm(self.co[self.ev[:, 0]] - self.co[self.ev[:, 1]], axis=1) if len(self.ev) else np.ones(1)
        self.edge_len = float(np.median(w)) or 1e-6

    def local_tree(self, local: np.ndarray):
        """BVH of the faces whose vertices are all inside `local` (a neighbourhood). Built from
        arrays (no Python loop per face: a box can hold a million faces of an AI mesh)."""
        from mathutils.bvhtree import BVHTree
        if not len(self.ls):
            return None
        inl = local[self.lv].astype(np.int8)
        allin = np.minimum.reduceat(inl, self.ls) > 0
        idx = np.nonzero(local)[0]
        remap = np.full(self.n, -1, np.int64)
        remap[idx] = np.arange(len(idx))
        polys = []
        for t in np.unique(self.lt[allin]):
            sel = np.nonzero(allin & (self.lt == t))[0]
            corners = self.ls[sel][:, None] + np.arange(t)[None, :]
            polys += remap[self.lv[corners]].tolist()
        if not polys:
            return None
        return BVHTree.FromPolygons(self.co[idx].tolist(), polys)


def thickness(arr: MeshArrays, tree, idx: np.ndarray, limit: float) -> np.ndarray:
    """Shape diameter at the given vertices: median distance a cone of 5 inward rays travels
    before it meets the surface again (rays that meet nothing within `limit` count as limit)."""
    from mathutils import Vector
    idx = np.asarray(idx, np.int64)
    out = np.full(len(idx), float(limit))
    if tree is None or len(idx) == 0:
        return out
    n = -arr.nrm[idx]
    ln = np.linalg.norm(n, axis=1)
    ok = ln > 1e-9
    n[ok] /= ln[ok, None]
    ref = np.where(np.abs(n[:, 2:3]) < 0.9, [[0.0, 0.0, 1.0]], [[1.0, 0.0, 0.0]])
    a = np.cross(n, ref)
    a /= np.maximum(np.linalg.norm(a, axis=1, keepdims=True), 1e-12)
    b = np.cross(n, a)
    dirs = np.stack([n, n + 0.45 * a, n - 0.45 * a, n + 0.45 * b, n - 0.45 * b], axis=1)
    dirs /= np.maximum(np.linalg.norm(dirs, axis=2, keepdims=True), 1e-12)
    orig = arr.co[idx] + n * (1e-5 * arr.size)
    d = np.full((len(idx), 5), float(limit))
    ray = tree.ray_cast
    for j in np.nonzero(ok)[0]:
        o = Vector(orig[j])
        for r in range(5):
            h = ray(o, Vector(dirs[j, r]), limit)
            if h[0] is not None:
                d[j, r] = h[3]
    out[ok] = np.median(d[ok], axis=1)
    return out


def trunk_thickness(arr: MeshArrays) -> float | None:
    """How thick the body's trunk is: the front-to-back depth along the centre line, slice by
    slice (no rays: cheap on any mesh). Upper quartile: legs and neck slices are thinner."""
    co = arr.co
    if arr.n < 50:
        return None
    x0 = float(np.median(co[:, 0]))
    band = np.abs(co[:, 0] - x0) < 0.03 * arr.size
    if band.sum() < 20:
        return None
    z = co[band, 2]
    y = co[band, 1]
    zb = np.floor((z - z.min()) / (0.03 * arr.size)).astype(np.int64)
    depths = []
    for b in np.unique(zb):
        yy = y[zb == b]
        if len(yy) >= 4:
            depths.append(float(yy.max() - yy.min()))
    return float(np.percentile(depths, 75)) if depths else None


def _sample(idx: np.ndarray, k: int) -> np.ndarray:
    return idx if len(idx) <= k else idx[:: len(idx) // k + 1]


def _components(n: int, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    from .appendages import _components as comp
    return comp(n, a, b)


def neck_region(arr: MeshArrays, seed: np.ndarray, max_share: float = 0.35, body=None,
                t_body: float | None = None) -> dict | None:
    """One part: see grow_parts."""
    return grow_parts(arr, [seed], max_share, body, t_body)[0]


def _box_state(arr: MeshArrays, st: dict, lo, hi) -> None:
    """(Re)build a part's search neighbourhood: vertices, faces (BVH), edges, its border."""
    local = np.all((arr.co >= lo) & (arr.co <= hi), axis=1)
    st["local"] = local
    st["tree"] = arr.local_tree(local)
    st["limit"] = 2.0 * float((hi - lo).max())
    st["le"] = arr.ev[local[arr.ev[:, 0]] & local[arr.ev[:, 1]]]
    xb = local[arr.ev[:, 0]] != local[arr.ev[:, 1]]
    edge_v = np.zeros(arr.n, bool)
    edge_v[arr.ev[xb].ravel()] = True
    st["edge_v"] = edge_v & local
    st["lo"], st["hi"] = lo, hi


def grow_parts(arr: MeshArrays, seeds: list, max_share: float = 0.35, body=None,
               t_body: float | None = None) -> list:
    """Grow every seed (vertices of a part, maybe only a fragment of it) over the surface while
    the surface stays thin, and stop at the neck where it turns into the thick body.

    Thin = shape diameter under 2.5 stems or the geometric mean of stem and trunk thickness,
    whichever is larger: a tapering horn keeps growing to its base, a tail stops where the
    rump begins, whatever their absolute size. The trunk is measured on the body itself
    (t_body from the caller, else trunk_thickness), never on whatever happens to be nearest
    a fragment (a leg, the part's own hidden stem).
    All parts grow together, ring by ring; a vertex belongs to the first part that reaches
    it, so an ear and a horn whose roots touch stop at each other. A part that reaches the
    edge of its search box gets a bigger box and grows on; max_share only guards against a
    growth leaking over the body.
    Per seed: {"mask", "thickness", "body_thickness", "ring": (centre, normal_into_body,
    radius), "ok": one short ring, "why"} or None when it is not thinner than the body."""
    n = arr.n
    label = np.zeros(n, np.int32)
    tb = float(t_body) if t_body else (trunk_thickness(arr) or arr.size)
    if body is None:                              # surely body: everything that is no seed
        body = np.ones(n, bool)
        for sd in seeds:
            body &= ~sd
    states = []
    for k, seed in enumerate(seeds, start=1):
        sidx = np.nonzero(seed)[0]
        if len(sidx) < 8:
            states.append(None)
            continue
        slo, shi = arr.co[sidx].min(axis=0), arr.co[sidx].max(axis=0)
        m1 = max(0.6 * float((shi - slo).max()), 0.06 * arr.size)
        st = {"k": k, "seed": seed, "grow": 0, "T": {}, "rejected": np.zeros(n, bool), "active": True,
              "m1": m1}
        _box_state(arr, st, slo - m1, shi + m1)
        Ts = thickness(arr, st["tree"], sidx, st["limit"])
        t_stem = float(np.percentile(Ts, 30))     # the stem, not a tuft at the end
        if t_stem >= 0.6 * tb:
            states.append(None)                   # as thick as the trunk: not a part
            continue
        st["t_stem"], st["t_body"] = t_stem, tb
        # thin enough to belong: well under the trunk, and within a few stems (a tapering horn
        # doubles its girth to the base; the rump is ten times a tail)
        st["thr"] = float(max(2.5 * t_stem, np.sqrt(t_stem * tb)))
        st["T"].update(zip(sidx.tolist(), Ts.tolist()))
        start = sidx[(Ts < st["thr"]) & (label[sidx] == 0)]
        label[start] = k
        states.append(st)
    cap = int(max(max_share, 0.05) * n)
    live = [st for st in states if st]
    while any(st["active"] for st in live):
        for st in live:
            if not st["active"]:
                continue
            le, k = st["le"], st["k"]
            a_in, b_in = label[le[:, 0]] == k, label[le[:, 1]] == k
            cand = np.unique(np.concatenate([le[a_in & ~b_in, 1], le[b_in & ~a_in, 0]]))
            cand = cand[(label[cand] == 0) & ~st["rejected"][cand]]
            if len(cand) == 0:
                region = label == k
                if (region & st["edge_v"]).any() and st["grow"] < 3:
                    # cut short by the box, not by the body: a bigger box, grow on
                    st["grow"] += 1
                    r = np.nonzero(region)[0]
                    m = st["m1"] * (1 + st["grow"])
                    _box_state(arr, st, arr.co[r].min(axis=0) - m, arr.co[r].max(axis=0) + m)
                    st["rejected"][:] = False             # (rays may have left the old box)
                    continue
                st["active"] = False
                st["at_edge"] = bool((region & st["edge_v"]).any())
                continue
            tc = thickness(arr, st["tree"], cand, st["limit"])
            st["T"].update(zip(cand.tolist(), tc.tolist()))
            ok = tc < st["thr"]
            label[cand[ok]] = k
            st["rejected"][cand[~ok]] = True
            if (label == k).sum() > cap:
                st["active"] = False
                st["spread"] = True
                label[label == k] = 0                     # it leaked: free what it took
    # two fragments of ONE part (a tail the bone test cut in two) meet halfway along it: a
    # fragment almost enclosed by another part is that part (a mere touch, like an ear root
    # against a horn root, is not)
    ev = arr.ev
    by_k = {st["k"]: st for st in live}
    for _ in range(len(live)):
        merged = False
        for st in live:
            if st.get("spread") or st.get("merged_into") or not (label == st["k"]).any():
                continue
            k = st["k"]
            a_k, b_k = label[ev[:, 0]] == k, label[ev[:, 1]] == k
            other = np.concatenate([label[ev[a_k & ~b_k, 1]], label[ev[b_k & ~a_k, 0]]])
            if len(other) == 0:
                continue
            vals, cnt = np.unique(other, return_counts=True)
            j = int(vals[np.argmax(cnt)])
            target = by_k.get(j)
            if j > 0 and target and not target.get("spread") and cnt.max() >= 0.9 * len(other):
                label[label == k] = j
                target["T"].update(st["T"])
                lo = np.minimum(target["lo"], st["lo"])
                hi = np.maximum(target["hi"], st["hi"])
                local = target["local"] | st["local"]
                target["local"], target["lo"], target["hi"] = local, lo, hi
                target["le"] = arr.ev[local[arr.ev[:, 0]] & local[arr.ev[:, 1]]]
                target["edge_v"] = (target["edge_v"] | st["edge_v"]) & ~(label == j)
                st["merged_into"] = j
                merged = True
        if not merged:
            break
    out = []
    for st in states:
        if st is None or st.get("merged_into"):
            out.append(None)
            continue
        if st.get("spread"):
            out.append({"mask": st["seed"], "thickness": st["t_stem"], "body_thickness": st["t_body"],
                        "ring": None, "ok": False, "why": "it grew over too much of the body"})
            continue
        if not (label == st["k"]).any():
            out.append(None)
            continue
        res = _finish_part(arr, label, st)
        if st.get("at_edge") and res["ok"]:
            res["ok"], res["why"] = False, "it reaches beyond the search area: no clear neck"
        out.append(res)
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
    open_ids = np.unique(lab2[out_l & (st["edge_v"] | (label > 0))])
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
    # the cut ring: part vertices next to the BODY (where it touches another part, like an
    # ear root against a horn root, is not its neck)
    a_in, b_in = region[arr.ev[:, 0]], region[arr.ev[:, 1]]
    cross = a_in ^ b_in
    other = np.where(a_in, arr.ev[:, 1], arr.ev[:, 0])
    cross &= (label[other] == 0) | (label[other] == k)
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
    trunk = trunk_thickness(arr)
    for sel, c, _ext in seeds:
        if (ids[sel] > 0).mean() > 0.5:
            continue                                  # already inside a part found before
        nk = neck_region(arr, sel, body=~far_lo, t_body=trunk)
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
