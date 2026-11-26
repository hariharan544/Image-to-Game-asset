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


def find(V: np.ndarray, edges: np.ndarray, J: dict, segments: int = 5, min_share: float = 0.002,
         arr=None) -> list:
    """Appendages as [{"name", "kind", "chain": [(x,y,z)...], "verts": n}] sorted by size.

    With `arr` (parts.MeshArrays in the same space as V) every candidate is grown over the
    surface to its neck and measured on its whole shape by thickness: the distance to a
    guessed bone only says that something sticks out (on a round cartoon body it swallows
    most of a horn), never where the part ends or how thick it is."""
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
    cands = [v for v in sorted(groups.values(), key=len, reverse=True) if len(v) >= 12]
    if arr is not None:
        from .parts import grow_parts
        seeds = []
        for verts in cands:
            m = np.zeros(len(V), bool)
            m[verts] = True
            seeds.append(m)
        grown = []
        # the trunk's own thickness (spine and head capsules): what a part must be thinner than
        spine = np.array([segs[i][2].startswith(("pelvis", "spine", "chest", "neck", "head")) for i in range(len(segs))])
        on_spine = spine[which] & ~far
        trunk = 2.0 * float(np.median(local[on_spine])) if on_spine.any() else None
        for info in grow_parts(arr, seeds, body=~far, t_body=trunk):   # all together: touching parts stop at each other
            if info is not None:                # (None: as thick as the body around: not a part)
                grown.append((list(np.nonzero(info["mask"])[0]), info))
    else:
        grown = [(v, None) for v in cands]
    for verts, info in grown:
        if len(verts) < max(12, min_share * len(V)):
            continue
        P = V[verts]
        # root: the appendage vertex closest to the explained body; tip: farthest from the root
        root = P[np.argmin(d[verts])]
        i0 = verts[int(np.argmin(d[verts]))]
        if info is not None and info["ring"] is not None:
            root = np.array(info["ring"][0])          # the neck: where the part meets the body
        else:
            # start the chain on the body surface, not where the part begins to stick out
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
        thick = info["thickness"] if info is not None else width
        # elongated: longer than thick (PCA width of a curled tail is its curl, not its girth)
        if length < 1.6 * (thick if info is not None else width):
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
        if len(touch_v) > 2 and info is None:      # (a grown part's ring was checked instead)
            axis = (tip - root) / max(np.linalg.norm(tip - root), 1e-9)
            proj = (V[touch_v] - root) @ axis
            if float(proj.max() - proj.min()) > 0.5 * length:
                continue
        # flat (an ear is a thin sheet) or round (a horn is a cone): the cross-section shape
        # tells them apart better than the direction (rabbit ears point up, bull horns sideways)
        if info is not None:
            # a sheet is much thinner than a tube of the same area and length would be
            area = len(verts) * (arr.edge_len ** 2) * 0.87
            tube_d = area / (np.pi * max(length, 1e-9))
            flat = bool(thick < 0.45 * tube_d)
        else:
            flat = bool(ev_[2] < 0.25 * max(ev_[1], 1e-12))
        # pointed: a horn narrows to a tip, an ear stays blunt
        ax = (tip - root) / max(np.linalg.norm(tip - root), 1e-9)
        t = (P - root) @ ax
        rad = np.linalg.norm((P - root) - t[:, None] * ax, axis=1)
        lo, hi = np.percentile(t, 25), np.percentile(t, 85)
        base_r = np.percentile(rad[t <= lo], 75) if (t <= lo).any() else 0.0
        tip_r = np.percentile(rad[t >= hi], 75) if (t >= hi).any() else 0.0
        pointed = bool(base_r > 0 and tip_r < 0.35 * base_r)
        kind = _classify(c, root, tip, pelvis, head, head_top, head_r, front, H, flat, pointed)
        out.append({"kind": kind, "chain": [tuple(map(float, p)) for p in chain],
                    "verts": len(verts), "vert_idx": np.asarray(verts), "length": length,
                    "width": float(width), "thickness": float(thick),
                    "thin": bool(thick < 0.06 * H and kind != "horn"), "centre": tuple(map(float, c)),
                    "ring": info["ring"] if info is not None else None,
                    "cut_ok": bool(info["ok"]) if info is not None else False})
    out.sort(key=lambda a: -a["verts"])
    return _name(out)


def _seg_dist(p, a, b) -> float:
    ab = b - a
    t = np.clip(((p - a) @ ab) / max(float(ab @ ab), 1e-12), 0.0, 1.0)
    return float(np.linalg.norm(p - (a + t * ab)))


def _classify(c, root, tip, pelvis, head, head_top, head_r, front, H, flat=False, pointed=False) -> str:
    behind = (c[1] - pelvis[1]) * front < 0          # opposite side to the face
    way = (tip - root) / max(np.linalg.norm(tip - root), 1e-9)
    if _seg_dist(root, head, head_top) < 2.0 * head_r:
        if flat and abs(c[0] - head[0]) > 0.3 * head_r:
            return "ear"                             # a sheet on the side of the head, any angle
        if not flat and (way[2] > 0.5 or (way[2] > 0.1 and pointed)):   # a round cone: horn
            return "horn"
        if abs(c[0] - head[0]) > 0.8 * head_r:
            return "ear"
        return "snout" if not behind else "head_extra"
    # a tail grows from the lower back, near the centre line (the pelvis guess is unreliable on
    # a round cartoon body: compare with the middle of the trunk instead)
    if behind and abs(root[0]) < 0.1 * H and root[2] < max(pelvis[2] + 0.15 * H, 0.5 * (pelvis[2] + head[2])):
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


def from_object(obj, J: dict, segments: int = 5, grow: bool = True) -> list:
    from .parts import MeshArrays
    arr = MeshArrays(obj.data)
    m = np.array(obj.matrix_world)
    V = arr.co @ m[:3, :3].T + m[:3, 3]
    if grow:                                      # measure in the same (world) space
        arr.co = V
        nr = arr.nrm @ np.linalg.inv(m[:3, :3])
        arr.nrm = nr / np.maximum(np.linalg.norm(nr, axis=1, keepdims=True), 1e-12)
    return find(V, arr.ev, J, segments, arr=arr if grow else None)
