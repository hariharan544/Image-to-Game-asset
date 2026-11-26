"""Find the extra body parts a humanoid skeleton does not cover: tail, ears, horns, trunk,
antennae... and lay a joint chain along each (root at the body, tip at the end).

Works on the body's vertex cloud after joints.estimate(): every vertex is measured
against the humanoid bone segments; vertices far from all of them (relative to the local
body thickness) are "unexplained". Connected groups of those are appendages, named by
where they sit (behind the pelvis = tail, sides of the head = ears, top of the head = horns).
"""

from __future__ import annotations

import numpy as np

SEGMENTS = [("pelvis", "neck"), ("neck", "head")]
LIMB_CHAINS = [("clavicle", "upperarm"), ("upperarm", "lowerarm"), ("lowerarm", "hand"),
               ("thigh", "calf"), ("calf", "foot"), ("foot", "ball")]


def _segments(J: dict) -> list:
    """Bone segments (head, tail) from the joint dict as numpy pairs, plus a reach radius scale."""
    out = []
    for k, v in J.items():
        if k.startswith("_"):
            continue
        h, t = v
        if k.startswith("clavicle"):      # lies inside the chest: its skin belongs to the spine
            continue
        if "thumb" in k or "index" in k or "middle" in k or "ring" in k or "pinky" in k:
            continue
        out.append((np.array(h[:]), np.array(t[:]), k))
    return out


def _dist_to_segments(P: np.ndarray, segs: list) -> tuple:
    """Distance to the nearest bone segment, which segment, and where along it (0..1)."""
    best = np.full(len(P), np.inf)
    which = np.full(len(P), -1)
    where = np.zeros(len(P))
    for i, (a, b, _k) in enumerate(segs):
        ab = b - a
        L2 = float(ab @ ab) or 1e-12
        t = np.clip(((P - a) @ ab) / L2, 0.0, 1.0)
        d = np.linalg.norm(P - (a + t[:, None] * ab), axis=1)
        m = d < best
        best[m], which[m], where[m] = d[m], i, t[m]
    return best, which, where


BINS = 10


def _local_radius(d, which, where, nseg: int, H: float) -> np.ndarray:
    """Body thickness around each bone, slice by slice along it (a chest is wider than a
    waist). A low percentile per slice, so an appendage hanging off it does not count."""
    slot = which * BINS + np.minimum((where * BINS).astype(int), BINS - 1)
    r = np.full(nseg * BINS, np.nan)
    for s in np.unique(slot):
        sel = d[slot == s]
        if len(sel) >= 8:
            r[s] = np.percentile(sel, 35)
    # empty slices: the bone's own median slice value, else a fraction of the height
    for i in range(nseg):
        row = r[i * BINS:(i + 1) * BINS]
        fill = np.nanmedian(row) if np.isfinite(row).any() else 0.05 * H
        row[~np.isfinite(row)] = fill
    return r[slot]


def _components(n: int, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    lab = np.arange(n)
    if len(a) == 0:
        return lab
    while True:
        m = np.minimum(lab[a], lab[b])
        new = lab.copy()
        np.minimum.at(new, lab[a], m)
        np.minimum.at(new, lab[b], m)
        np.minimum.at(new, a, m)
        np.minimum.at(new, b, m)
        while True:
            j = new[new]
            if np.array_equal(j, new):
                break
            new = j
        if np.array_equal(new, lab):
            return lab
        lab = new


def find(V: np.ndarray, edges: np.ndarray, J: dict, segments: int = 5, min_share: float = 0.002) -> list:
    """Appendages as [{"name", "kind", "chain": [(x,y,z)...], "verts": n}] sorted by size."""
    g, top = V[:, 2].min(), V[:, 2].max()
    H = max(top - g, 1e-6)
    segs = _segments(J)
    d, which, where = _dist_to_segments(V, segs)
    local = _local_radius(d, which, where, len(segs), H)
    reach = local * 1.5 + 0.02 * H
    far = d > reach
    # wrists/ankles beyond the last joint are hands/feet, not appendages
    hands = [np.array(J[f"hand_{s}"][1][:]) for s in "lr" if f"hand_{s}" in J]
    for hp in hands:
        far &= np.linalg.norm(V - hp, axis=1) > 0.12 * H
    idx = np.nonzero(far)[0]
    if len(idx) == 0:
        return []
    keep = far[edges[:, 0]] & far[edges[:, 1]]
    lab = _components(len(V), edges[keep, 0], edges[keep, 1])
    groups = {}
    for v in idx:
        groups.setdefault(lab[v], []).append(v)
    pelvis = np.array(J["pelvis"][0][:])
    head = np.array(J["head"][0][:])
    neck = np.array(J["neck"][0][:])
    front = float(J.get("_front", -1.0))
    head_top = np.array(J["head"][1][:])
    head_r = max(np.linalg.norm(head - neck), 0.6 * np.linalg.norm(head_top - head), 0.05 * H)
    out = []
    for verts in groups.values():
        if len(verts) < max(12, min_share * len(V)):
            continue
        P = V[verts]
        # root: the appendage vertex closest to the explained body; tip: farthest from the root
        root = P[np.argmin(d[verts])]
        # start the chain on the body surface, not where the part begins to stick out
        i0 = verts[int(np.argmin(d[verts]))]
        a, b, _k = segs[which[i0]]
        on_bone = a + where[i0] * (b - a)
        out_dir = root - on_bone
        root = on_bone + out_dir / max(np.linalg.norm(out_dir), 1e-9) * local[i0]
        dist = np.linalg.norm(P - root, axis=1)
        tip = P[np.argmax(dist)]
        length = float(dist.max())
        if length < 0.04 * H:
            continue
        # appendages are elongated; a patch of torso surface flagged by mistake is a broad sheet
        ev_ = np.linalg.eigvalsh(np.cov((P - P.mean(axis=0)).T))[::-1]
        width = 2.0 * np.sqrt(max(ev_[1], 0.0))
        if length < 1.6 * width:
            continue
        # must stick out clearly (armpits and shoulder blends stick out a little, ears a lot)
        if float(np.max(d[verts] - local[verts])) < 0.06 * H:
            continue
        # chain: centroids of slices along root->tip distance
        edges_ = np.linspace(0, length, segments + 1)
        chain = [root]
        for i in range(1, segments + 1):
            sl = P[(dist >= edges_[i - 1]) & (dist <= edges_[i] + 1e-9)]
            chain.append(sl.mean(axis=0) if len(sl) else root + (tip - root) * i / segments)
        chain[-1] = tip
        c = P.mean(axis=0)
        # a real appendage meets the body only around its root; a strip of torso surface
        # flagged by mistake touches the body all along its length
        member = np.zeros(len(V), bool)
        member[verts] = True
        touch_e = (member[edges[:, 0]] & ~far[edges[:, 1]]) | (member[edges[:, 1]] & ~far[edges[:, 0]])
        touch_v = np.unique(np.where(member[edges[touch_e, 0]], edges[touch_e, 0], edges[touch_e, 1]))
        if len(touch_v) > 2:
            axis = (tip - root) / max(np.linalg.norm(tip - root), 1e-9)
            proj = (V[touch_v] - root) @ axis
            if float(proj.max() - proj.min()) > 0.5 * length:
                continue
        kind = _classify(c, root, tip, pelvis, head, head_top, head_r, front, H)
        out.append({"kind": kind, "chain": [tuple(map(float, p)) for p in chain],
                    "verts": len(verts), "length": length, "centre": tuple(map(float, c))})
    out.sort(key=lambda a: -a["verts"])
    return _name(out)


def _seg_dist(p, a, b) -> float:
    ab = b - a
    t = np.clip(((p - a) @ ab) / max(float(ab @ ab), 1e-12), 0.0, 1.0)
    return float(np.linalg.norm(p - (a + t * ab)))


def _classify(c, root, tip, pelvis, head, head_top, head_r, front, H) -> str:
    behind = (c[1] - pelvis[1]) * front < 0          # opposite side to the face
    way = (tip - root) / max(np.linalg.norm(tip - root), 1e-9)
    if _seg_dist(root, head, head_top) < 2.0 * head_r:
        if way[2] > 0.5:                             # pointing up: horn / antenna
            return "horn"
        if abs(c[0] - head[0]) > 0.8 * head_r:
            return "ear"
        return "snout" if not behind else "head_extra"
    if behind and root[2] < pelvis[2] + 0.15 * H and abs(root[0]) < 0.1 * H:
        return "tail"
    if behind:
        return "back_extra"
    return "extra"


def _name(items: list) -> list:
    counts: dict = {}
    for a in items:
        k = a["kind"]
        side = ""
        if k in ("ear", "horn") or abs(a["centre"][0]) > 0.02:
            side = "_l" if a["centre"][0] > 0 else "_r"
            if k == "tail":
                side = ""
        base = k + side
        counts[base] = counts.get(base, 0) + 1
        a["name"] = base if counts[base] == 1 else f"{base}{counts[base]}"
    return items


def from_object(obj, J: dict, segments: int = 5) -> list:
    me = obj.data
    n = len(me.vertices)
    co = np.empty(n * 3, np.float32)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3).astype(np.float64)
    m = np.array(obj.matrix_world)
    V = co @ m[:3, :3].T + m[:3, 3]
    ev = np.empty(len(me.edges) * 2, np.int32)
    me.edges.foreach_get("vertices", ev)
    return find(V, ev.reshape(-1, 2).astype(np.int64), J, segments)
