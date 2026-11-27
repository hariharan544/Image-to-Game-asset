"""Automatic checks while a sample clip plays on the rig (Step 8).

"Watch for tearing" becomes a pass / warn / fail for each part of the body, with the frame
where it is worst (the caller adds the test pose shown at that frame):

  joints    where two body segments share the skin (elbow, knee, shoulder, ear root, tail root)
            the skin keeps its distance from the bones. Each frame the child segment's turn
            against its parent is split into a bend and a twist, and each point is put on the
            inner side of the bend, on a side, or on the outer side. A limb of radius r bent by
            an angle presses into itself on the inner side up to r*tan(angle/2) from the joint:
            that is contact, expected, and shown as information. Thinning anywhere else is the
            skinning's: the sides, the outer side (linear blending's elbow loss) and a twist
            (the candy wrapper). Twist bones along one segment are judged as '<segment> twist'.
  skin      each triangle's largest principal stretch against rest (the texture smears), and
            triangles turned inside out outside a contact zone (folds): the worst per region
  crossing  faces newly passing through faces. Inside one joint's contact zone: contact. Inside
            one segment: a fold (a fault). Between parts: '<A> touches <B>' (a forearm into an
            ear). Parts that already overlap at rest - a tail root plugged into the body - are
            not counted
  weights   points no bone moves; and what Unity's 4-bone limit does to the skin (simulated
            with the same limit the export applies, on the full mesh before Unity's copy is
            reduced): how far it moves the skin and the stretch it adds

What is measured is what the engines play: linear blending (Preserve Volume is switched off
while measuring), Unreal with the weights as bound (8 bones at most), Unity cut to 4. Every
finding names its region; the worst finding per region is listed (by_region).
"""

from __future__ import annotations

import math
import re

import numpy as np

import bpy

LIMITS = {
    "volume": (0.7, 0.5),          # (warn below, fail below) joint thickness kept, posed / rest
    "stretch": (1.5, 2.0),         # (warn above, fail above) a triangle's largest stretch: smear
    "folds": (0.0, 0.01),          # (warn above, fail above) share of triangles turned inside out
    "crossing": (0.0, 0.01),       # (warn above, fail above) share of faces folding through others
}
ENGINE_INFLUENCES = {"Unity": 4, "Unreal": 8}
ENGINE_MIN_WEIGHT = 0.01           # the export drops weights under this first (skin.engine_limit)
MIN_JOINT_POINTS = 8               # fewer shared points than this: not a joint to judge
MIN_PART_POINTS = 4                # fewer points on one side of a bend: that side is not judged
BLEND = 0.1                        # a point is in a joint when its 2nd segment moves it this much
MIN_TURN = 10.0                    # degrees: a joint bending and twisting less is not judged
INNER = 0.5                        # cos to the bend direction: inner side above, outer below -INNER
MIN_AREA = 0.01                    # triangles under this share of the median rest area: not measured
UNITY_SHIFT = 0.5                  # Unity's limit moving skin more than this many median edges: warn
LBS_MARGIN = 0.05                  # thinning within this of linear blending's own loss is the method's
ORDER = ("pass", "warn", "fail")

# Auto-Rig Pro's deform bones by role (its arm and leg bone tables, ear and tail chains): the
# bones of one limb segment carry its skin together, so their weights are summed. Each entry:
# (name pattern without the side, segment word, kind). "twist": bones along one segment that
# share out its twist; "chain": links of a chain that bend (tail, ear, neck, toes).
ARP_SEGMENTS = (
    (r"c_arm_twist_offset\d*|c_arm_twist(_\d+)?|arm_twist(_\d+)?|arm_stretch", "upper arm", "twist"),
    (r"forearm_stretch|c_forearm_twist(_\d+)?|forearm_twist(_\d+)?", "forearm", "twist"),
    (r"c_thigh_twist(_\d+)?|thigh_twist(_\d+)?|thigh_stretch", "thigh", "twist"),
    (r"leg_stretch|c_leg_twist(_\d+)?|leg_twist(_\d+)?", "calf", "twist"),
    (r"c_ear_\d+", "ear", "chain"),
    (r"c_tail_\d+", "tail", "chain"),
    (r"shoulder", "shoulder", ""),
    (r"hand", "hand", ""),
    (r"foot", "foot", ""),
    (r"toes_\d+", "toes", "chain"),
    (r"root", "hips", ""),
    (r"spine_\d+", "spine", ""),
    (r"neck(_\d+)?|subneck_\d+", "neck", "chain"),
    (r"head|c_skull_\d+", "head", ""),
    (r"c?_?jawbone", "jaw", ""),
)
FINGER = r"c_(thumb|index|middle|ring|pinky)\d(_base)?"
CORE = ("hips", "spine", "neck", "head")
# which segment is the child of a joint: further from the body's core
RANK = {"hips": 0.0, "spine": 1.0, "neck": 3.0, "head": 4.0, "jaw": 5.0, "ear": 6.0, "tail": 6.0,
        "shoulder": 10.0, "upper arm": 11.0, "forearm": 12.0, "hand": 13.0, "finger": 14.0,
        "thigh": 11.0, "calf": 12.0, "foot": 13.0, "toes": 14.0}
JOINT_WORDS = {("upper arm", "forearm"): "elbow", ("forearm", "hand"): "wrist", ("thigh", "calf"): "knee",
               ("calf", "foot"): "ankle", ("foot", "toes"): "toes", ("neck", "head"): "neck",
               ("head", "jaw"): "jaw", ("hips", "spine"): "lower back", ("spine", "spine"): "back",
               ("spine", "head"): "neck", ("spine", "neck"): "base of the neck"}


# ----------------------------------------------------------------------------- mesh data

def _world_co(me, mw) -> np.ndarray:
    co = np.empty(len(me.vertices) * 3, np.float64)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    m = np.array(mw, np.float64)
    return co @ m[:3, :3].T + m[:3, 3]


def _tris(me) -> np.ndarray:
    me.calc_loop_triangles()
    t = np.empty(len(me.loop_triangles) * 3, np.int64)
    me.loop_triangles.foreach_get("vertices", t)
    return t.reshape(-1, 3)


def _edges(me) -> np.ndarray:
    e = np.empty(len(me.edges) * 2, np.int64)
    me.edges.foreach_get("vertices", e)
    return e.reshape(-1, 2)


def _weight_rows(obj, bones: list) -> np.ndarray:
    """Points x bones: the object's weights of those bones' vertex groups."""
    at = {b: j for j, b in enumerate(bones)}
    col = {g.index: at[g.name] for g in obj.vertex_groups if g.name in at}
    W = np.zeros((len(obj.data.vertices), len(bones)))
    for v in obj.data.vertices:
        for g in v.groups:
            j = col.get(g.group)
            if j is not None and g.weight > 0:
                W[v.index, j] = g.weight
    return W


# ----------------------------------------------------------------------------- names

def _split_side(name: str) -> tuple:
    """('forearm_stretch', 'left') from 'forearm_stretch.l'; side '' for the middle (.x)."""
    m = re.match(r"^(.*?)(?:[._])([lrLR]|x)$", name)
    if not m:
        return name, ""
    return m.group(1), {"l": "left", "r": "right"}.get(m.group(2).lower(), "")


def _word(base: str) -> str:
    for junk in ("c_", "_stretch", "_twist", "_ref", "_def", "DEF-", "_fk", "_ik"):
        base = base.replace(junk, "")
    return base.replace("_", " ").strip()


def _nice(bone: str) -> str:
    """'forearm_stretch.l' -> 'left forearm' (for the panel)."""
    base, side = _split_side(bone)
    return f"{side} {_word(base)}".strip()


def _grade(value: float, warn: float, fail: float, below: bool) -> str:
    if (value < fail) if below else (value > fail):
        return "fail"
    if (value < warn) if below else (value > warn):
        return "warn"
    return "pass"


def _worse(a: str, b: str) -> str:
    return max(a, b, key=lambda g: ORDER.index(g) if g in ORDER else 0)


# ----------------------------------------------------------------------------- geometry

def _dist_to_bone(p, a, b) -> np.ndarray:
    ab = b - a
    t = np.clip((p - a) @ ab / max(float(ab @ ab), 1e-12), 0.0, 1.0)
    return np.linalg.norm(p - (a + t[:, None] * ab), axis=1)


def _dist_union(p, H, T, bones) -> np.ndarray:
    """Distance from each point to the nearest of the bones (segments head-tail)."""
    out = np.full(len(p), np.inf)
    for b in bones:
        out = np.minimum(out, _dist_to_bone(p, H[b], T[b]))
    return out


def _bone_gap(h1, t1, h2, t2) -> float:
    pts = np.array([h1, t1])
    d1 = _dist_to_bone(pts, h2, t2).min()
    d2 = _dist_to_bone(np.array([h2, t2]), h1, t1).min()
    return float(min(d1, d2))


def skin_matrices(arm, bones: list) -> np.ndarray:
    """(bones, 4, 4) world skinning matrices of the current pose: what moves a rest point of
    each bone's skin, mw @ pose.matrix @ matrix_local^-1 @ mw^-1."""
    mw = np.array(arm.matrix_world, np.float64)
    imw = np.linalg.inv(mw)
    out = np.empty((len(bones), 4, 4))
    for i, n in enumerate(bones):
        pb = arm.pose.bones[n]
        out[i] = mw @ np.array(pb.matrix, np.float64) @ np.linalg.inv(np.array(pb.bone.matrix_local, np.float64)) @ imw
    return out


def lbs(rest, W, mats) -> np.ndarray:
    """Linear blend skinning as the engines (and Blender without Preserve Volume) do it: each
    point is the weighted sum of its bones' matrices applied to its rest position. W: points x
    bones, rows summing to 1 (rows of 0 stay at the origin)."""
    out = np.zeros_like(rest)
    for j in np.flatnonzero((W > 0).any(axis=0)):
        m = W[:, j] > 0
        out[m] += W[m, j, None] * (rest[m] @ mats[j, :3, :3].T + mats[j, :3, 3])
    return out


def _rotations(mats) -> np.ndarray:
    """The rotation in each matrix (a stretch bone's scale taken out)."""
    U, _s, Vt = np.linalg.svd(mats[:, :3, :3])
    R = U @ Vt
    bad = np.linalg.det(R) < 0
    if bad.any():
        U[bad, :, -1] *= -1
        R[bad] = U[bad] @ Vt[bad]
    return R


def _swing_twist(Rrel, axis) -> tuple:
    """(swing degrees, twist degrees, total turn degrees, bend direction) of a rotation
    against the child's rest axis. The bend direction is where the child swings to."""
    from mathutils import Matrix
    a2 = Rrel @ axis
    c = float(np.clip(axis @ a2, -1.0, 1.0))
    theta = math.degrees(math.acos(c))
    q = Matrix(Rrel.tolist()).to_quaternion()
    w, v = q.w, np.array((q.x, q.y, q.z))
    if w < 0:
        w, v = -w, -v
    tw = math.degrees(2.0 * math.atan2(float(v @ axis), w))
    if tw > 180.0:
        tw -= 360.0
    total = math.degrees(2.0 * math.acos(min(1.0, w)))
    b = a2 - c * axis
    nb = float(np.linalg.norm(b))
    return theta, tw, total, (b / nb if nb > 1e-9 else np.zeros(3))


def principal_stretch(rest, co, tris) -> tuple:
    """Per triangle the largest and smallest stretch of the skin (singular values of the 2D
    deformation gradient from rest to now) and its posed normal (unnormalised)."""
    r0 = rest[tris[:, 0]]
    e1, e2 = rest[tris[:, 1]] - r0, rest[tris[:, 2]] - r0
    l1 = np.maximum(np.linalg.norm(e1, axis=1), 1e-30)
    u = e1 / l1[:, None]
    n = np.cross(e1, e2)
    v = np.cross(n, u)
    v /= np.maximum(np.linalg.norm(v, axis=1), 1e-30)[:, None]
    x2, y2 = np.einsum("ij,ij->i", e2, u), np.maximum(np.einsum("ij,ij->i", e2, v), 1e-30)
    p0 = co[tris[:, 0]]
    f1, f2 = co[tris[:, 1]] - p0, co[tris[:, 2]] - p0
    # F = [f1 f2] @ inverse([[l1, x2], [0, y2]])
    g1 = f1 / l1[:, None]
    g2 = (f2 - g1 * x2[:, None]) / y2[:, None]
    a, b, c = np.einsum("ij,ij->i", g1, g1), np.einsum("ij,ij->i", g1, g2), np.einsum("ij,ij->i", g2, g2)
    m, d = 0.5 * (a + c), np.sqrt(np.maximum(0.25 * (a - c) ** 2 + b * b, 0.0))
    return np.sqrt(m + d), np.sqrt(np.maximum(m - d, 0.0)), np.cross(f1, f2)


def crossing_pairs(co, tris, shrink: float = 0.98) -> np.ndarray:
    """(k, 2) triangles passing through another triangle, i < j. Each triangle is shrunk a little
    towards its centre first, so neighbours sharing an edge or a corner no longer touch:
    whatever still overlaps really crosses."""
    from mathutils.bvhtree import BVHTree
    if not len(tris):
        return np.zeros((0, 2), np.int64)
    c = co[tris].mean(axis=1, keepdims=True)
    pts = (c + (co[tris] - c) * shrink).reshape(-1, 3)
    polys = np.arange(len(pts)).reshape(-1, 3)
    tree = BVHTree.FromPolygons(pts.tolist(), polys.tolist(), all_triangles=True)
    pairs = np.array(tree.overlap(tree), np.int64).reshape(-1, 2)
    pairs = pairs[pairs[:, 0] != pairs[:, 1]]
    return np.unique(np.sort(pairs, axis=1), axis=0) if len(pairs) else pairs


def crossing_faces(co, tris, shrink: float = 0.98) -> set:
    """Triangles passing through another triangle (see crossing_pairs)."""
    return set(crossing_pairs(co, tris, shrink).ravel().tolist())


# ----------------------------------------------------------------------------- segments, joints

class _Seg:
    """A body segment: the bones that carry one part's skin together (upper arm, tail...)."""

    def __init__(self, key, role, word, side, kind="", arp=False, rank=None):
        self.key, self.role, self.word, self.side = key, role, word, side
        self.kind, self.arp, self.rank, self.bones = kind, arp, rank, []

    @property
    def name(self) -> str:
        return f"{self.side} {self.word}".strip()


def _arp_role(base: str):
    for pat, word, kind in ARP_SEGMENTS:
        if re.fullmatch(pat, base):
            return word, kind
    m = re.fullmatch(FINGER, base)
    if m:
        return ("thumb" if m.group(1) == "thumb" else f"{m.group(1)} finger"), "chain"
    return None, None


def build_segments(bones: list) -> tuple:
    """(segments, segment index of each bone). Auto-Rig Pro's bones are grouped by role; any
    other bone is a segment of its own."""
    segs: list = []
    by_key: dict = {}
    of = np.empty(len(bones), np.int64)
    spines = sorted((b for b in bones if _arp_role(_split_side(b)[0])[0] == "spine"),
                    key=lambda b: _split_side(b)[0])
    for i, b in enumerate(bones):
        base, side = _split_side(b)
        word, kind = _arp_role(base)
        if word == "spine":
            k = spines.index(b)
            n = len(spines)
            sw = "back" if n == 1 else ("lower back" if k == 0 else "chest" if k == n - 1
                                        else "middle of the back" + (f" {k}" if n > 3 else ""))
            key, seg = b, _Seg(b, "spine", sw, "", "", True, RANK["spine"] + 0.1 * k)
        elif word is not None:
            role = "finger" if word.endswith("finger") or word == "thumb" else word
            key, seg = (word, side), _Seg((word, side), role, word, side, kind, True, RANK.get(role))
        else:
            key, seg = b, _Seg(b, None, _word(base) or b, side)
        if key not in by_key:
            by_key[key] = len(segs)
            segs.append(seg)
        of[i] = by_key[key]
        segs[by_key[key]].bones.append(i)
    return segs, of


def _joint_word(P: _Seg, C: _Seg):
    """The anatomical name of the joint between a parent and a child segment (None: none)."""
    if not (P.arp and C.arp):
        return None
    if C.role == "tail" or P.role == "tail":
        return "tail root"
    if C.role == "ear" or P.role == "ear":
        return "ear root"
    w = JOINT_WORDS.get((P.role, C.role))
    if w:
        return w
    if C.role == "upper arm" and P.role in ("hips", "spine", "shoulder"):
        return "shoulder"
    if C.role == "shoulder" and P.role in ("hips", "spine"):
        return "collarbone"
    if C.role == "shoulder" and P.role in ("neck", "head"):
        return "side of the neck"              # (a neckless body: the head sits on the shoulders)
    if C.role == "thigh" and P.role in ("hips", "spine"):
        return "hip"
    if C.role == "finger" and P.role == "hand":
        return f"{C.word} root"
    return None


class _Joint:
    """Two segments (or two bones of one segment) sharing skin, and how to judge it."""


class _Layout:
    """Which skin moves with which bones: segments, joints and regions, from the rest state."""

    def __init__(self, arm, bones: list, W, rest, tris, labels, rigid=None):
        self.bones, self.W, self.rest, self.tris = bones, W, rest, tris
        n = len(rest)
        segs, of = build_segments(bones)
        # a part of its own: an object pinned whole to one bone (a prop), and points no bone moves
        tot = W.sum(axis=1)
        self.free = tot <= 1e-9
        own = self.free | (np.zeros(n, bool) if rigid is None else rigid)
        extra = {}
        for lab in np.unique(labels[own]) if own.any() else []:
            extra[lab] = len(segs)
            segs.append(_Seg(("object", lab), None, str(lab), ""))
        self.segs, self.seg_of = segs, of
        S = np.zeros((len(bones), len(segs)))
        S[np.arange(len(bones)), of] = 1.0
        Wn = W / np.where(tot > 0, tot, 1.0)[:, None]
        self.Wn = Wn
        SW = Wn @ S
        for lab, si in extra.items():
            m = own & (labels == lab)
            SW[m] = 0.0
            SW[m, si] = 1.0
        self.SW = SW
        mw = np.array(arm.matrix_world, np.float64)
        ab = arm.data.bones
        self.H = np.array([(mw @ np.append(np.array(ab[b].head_local), 1.0))[:3] for b in bones]).reshape(-1, 3)
        self.T = np.array([(mw @ np.append(np.array(ab[b].tail_local), 1.0))[:3] for b in bones]).reshape(-1, 3)
        self.anc = {b: {a.name for a in ab[b].parent_recursive} for b in bones}
        # each point's two strongest segments
        top = np.argsort(-SW, axis=1, kind="stable")[:, :2] if len(segs) > 1 else np.zeros((n, 2), np.int64)
        rows = np.arange(n)
        self.s1 = top[:, 0]
        self.s2 = np.where(SW[rows, top[:, 1]] >= BLEND, top[:, 1], -1) if len(segs) > 1 else np.full(n, -1)
        self._names: dict = {}
        self.joints: list = []
        self._find_joints()
        self.pt_reg, self.reg_names = self._regions(self.s1, self.s2)
        ts = SW[tris].mean(axis=1) if len(tris) else np.zeros((0, len(segs)))
        if len(tris) and len(segs) > 1:
            tt = np.argsort(-ts, axis=1, kind="stable")[:, :2]
            t1 = tt[:, 0]
            t2 = np.where(ts[np.arange(len(tris)), tt[:, 1]] >= BLEND, tt[:, 1], -1)
        else:
            t1, t2 = np.zeros(len(tris), np.int64), np.full(len(tris), -1)
        self.tri_seg = t1
        self.tri_reg, _ = self._regions(t1, t2, self.reg_names)
        # each triangle's strongest bone (its rest normal turns with it)
        tw = W[tris].sum(axis=1) if len(tris) else np.zeros((0, len(bones)))
        self.tri_bone = np.argmax(tw, axis=1) if len(bones) else np.zeros(len(tris), np.int64)
        self.tri_free = tw.sum(axis=1) <= 1e-9 if len(tris) else np.zeros(0, bool)
        r0 = rest[tris[:, 0]] if len(tris) else np.zeros((0, 3))
        self.rest_n = np.cross(rest[tris[:, 1]] - r0, rest[tris[:, 2]] - r0) if len(tris) else np.zeros((0, 3))
        area = np.linalg.norm(self.rest_n, axis=1)
        self.tri_ok = area >= MIN_AREA * (np.median(area) if len(area) else 0.0)

    # ---- parent / child and names
    def _order(self, A: list, B: list, rank_a=None, rank_b=None) -> tuple:
        """((parent bones, child bones), parent bone, child bone): which side is further out,
        and the two bones where they meet."""
        best = None
        for a in A:
            for b in B:
                g = _bone_gap(self.H[a], self.T[a], self.H[b], self.T[b])
                if best is None or g < best[0]:
                    best = (g, a, b)
        _g, a, b = best
        if rank_a is not None and rank_b is not None and rank_a != rank_b:
            child_b = rank_b > rank_a
        elif any(self.bones[y] in self.anc[self.bones[x]] for x in A for y in B):
            child_b = False                                  # A hangs below B
        elif any(self.bones[x] in self.anc[self.bones[y]] for x in A for y in B):
            child_b = True
        else:                                                # the child starts where the parent is
            da = float(_dist_to_bone(self.H[a][None], self.H[b], self.T[b])[0])
            db = float(_dist_to_bone(self.H[b][None], self.H[a], self.T[a])[0])
            child_b = db <= da
        return ((A, B), a, b) if child_b else ((B, A), b, a)

    def pair_name(self, i: int, j: int) -> str:
        """The name of the region where segments i and j share skin ('left elbow')."""
        key = (min(i, j), max(i, j))
        if key not in self._names:
            P, C = self.segs[i], self.segs[j]
            if not P.bones or not C.bones:
                name = f"{P.name} and {C.name}"
            else:
                (pb, cb), _p, _c = self._order(P.bones, C.bones, P.rank, C.rank)
                if pb is C.bones:
                    P, C = C, P
                w = _joint_word(P, C)
                side = C.side or P.side
                if w is not None:
                    name = f"{side} {w}".strip()
                elif P.arp and C.arp:
                    name = f"{C.name} and {P.name}"
                else:
                    child = self.bones[cb[0]] if len(cb) == 1 else C.name
                    name = f"{_nice(child)} joint"
            self._names[key] = name
        return self._names[key]

    def _regions(self, s1, s2, names=None) -> tuple:
        names = [] if names is None else names
        at = {nm: k for k, nm in enumerate(names)}
        out = np.empty(len(s1), np.int64)
        cache: dict = {}
        for k, (a, b) in enumerate(zip(s1.tolist(), s2.tolist())):
            key = (a, b) if b < 0 else (min(a, b), max(a, b))
            r = cache.get(key)
            if r is None:
                nm = self.segs[a].name if b < 0 else self.pair_name(a, b)
                if nm not in at:
                    at[nm] = len(names)
                    names.append(nm)
                r = cache[key] = at[nm]
            out[k] = r
        return out, names

    # ---- joints
    def _find_joints(self) -> None:
        n = len(self.rest)
        groups: dict = {}
        shared = np.flatnonzero(self.s2 >= 0)
        for v, a, b in zip(shared.tolist(), self.s1[shared].tolist(), self.s2[shared].tolist()):
            groups.setdefault(("seg", min(a, b), max(a, b)), []).append(v)
        # twist bones / chain links inside one segment
        multi = [k for k, s in enumerate(self.segs) if len(s.bones) > 1]
        for k in multi:
            cols = np.array(self.segs[k].bones)
            pts = np.flatnonzero(self.s1 == k)
            if not len(pts):
                continue
            sub = self.Wn[np.ix_(pts, cols)]
            o = np.argsort(-sub, axis=1, kind="stable")[:, :2]
            w2 = sub[np.arange(len(pts)), o[:, 1]]
            ok = w2 >= BLEND
            for v, x, y in zip(pts[ok].tolist(), cols[o[ok, 0]].tolist(), cols[o[ok, 1]].tolist()):
                groups.setdefault(("bone", min(x, y), max(x, y)), []).append(v)
        for (kind, a, b), idx in groups.items():
            if len(idx) < MIN_JOINT_POINTS:
                continue
            idx = np.array(idx, np.int64)
            if kind == "seg":
                A, B = self.segs[a], self.segs[b]
                if not A.bones or not B.bones:
                    continue
                (pb, cb), p, c = self._order(A.bones, B.bones, A.rank, B.rank)
                name = self.pair_name(a, b)
                jk = "joint"
            else:
                seg = self.segs[self.seg_of[a]]
                (pb, cb), p, c = self._order([a], [b])
                jk = "twist" if seg.kind == "twist" else "bend"
                name = f"{seg.name} {jk}"
            self.joints.append(self._joint(name, jk, list(pb), list(cb), p, c, idx, n))

    def _joint(self, name, kind, pb, cb, p, c, idx, n) -> _Joint:
        J = _Joint()
        J.name, J.kind, J.p, J.c = name, kind, p, c
        J.union = sorted(set(pb) | set(cb))
        J.pivot = self.H[c].copy()
        ax = self.T[c] - self.H[c]
        J.axis = ax / max(float(np.linalg.norm(ax)), 1e-12)
        J.idx = idx
        J.rest = _dist_union(self.rest[idx], self.H, self.T, J.union)
        med = float(np.median(J.rest)) if len(J.rest) else 0.0
        J.use = J.rest >= 0.25 * med                     # (a point lying on its bone: noise)
        J.r = float(np.median(J.rest[J.use])) if J.use.any() else med
        J.rdir, J.along, J.rd = self._radial(J, self.rest[idx])
        # the contact zone can hold any point of the two sides near the joint, not just shared ones
        side_w = self.Wn[:, J.union].sum(axis=1)
        cand = np.flatnonzero(side_w >= 0.5)
        rdir, along, rd = self._radial(J, self.rest[cand])
        keep = rd < 2.0 * max(J.r, 1e-9)
        J.cidx, J.c_rdir, J.c_along, J.c_rd = cand[keep], rdir[keep], along[keep], rd[keep]
        return J

    @staticmethod
    def _radial(J, P) -> tuple:
        v = P - J.pivot
        along = v @ J.axis
        rad = v - along[:, None] * J.axis
        rd = np.linalg.norm(rad, axis=1)
        return rad / np.maximum(rd, 1e-12)[:, None], along, rd

    def measure(self, J, co, R, H, T):
        """One joint at one frame: its bend, twist, the thickness kept on each side of the bend,
        and its contact zone (indices of points). None when it neither bends nor twists."""
        Rrel = R[J.p].T @ R[J.c]
        theta, tw, total, bdir = _swing_twist(Rrel, J.axis)
        if theta < MIN_TURN and abs(tw) < MIN_TURN:
            return None
        ratio = _dist_union(co[J.idx], H, T, J.union) / np.maximum(J.rest, 1e-12)
        use = J.use
        if theta >= MIN_TURN:
            # the half of the limb the bend closes on presses into the other half: a surface at
            # distance rho from the axis meets the opposite one rho*tan(bend/2) from the joint
            s = J.rdir @ bdir
            inner, outer = s > INNER, s < -INNER
            tn = math.tan(math.radians(min(theta, 179.0)) / 2.0)
            zone = (s > 0.0) & (np.abs(J.along) < J.rd * tn)
            cs = J.c_rdir @ bdir
            czone = J.cidx[(cs > 0.0) & (np.abs(J.c_along) < J.c_rd * tn)]
            parts = {"inner side": use & inner & ~zone, "sides": use & ~inner & ~outer & ~zone,
                     "outer side": use & outer}
        else:
            zone = np.zeros(len(J.idx), bool)
            czone = J.cidx[:0]
            parts = {"all round": use}
        vals = {k: float(np.percentile(ratio[m], 5)) for k, m in parts.items() if m.sum() >= MIN_PART_POINTS}
        part = min(vals, key=vals.get) if vals else None
        cz = use & zone
        # each point's place this frame: 2 contact zone, 1 inner side, 0 a side (or a twist), -1 outer
        side = np.where(zone, 2, 0) if theta < MIN_TURN else \
            np.where(zone, 2, np.where(inner, 1, np.where(outer, -1, 0)))
        return {"bend": theta, "twist": tw, "turn": total, "part": part,
                "value": vals[part] if part else None, "parts": vals,
                "contact": float(np.percentile(ratio[cz], 5)) if cz.sum() >= MIN_PART_POINTS else None,
                "zone": czone, "side": side, "ratio": ratio}


# ----------------------------------------------------------------------------- weights

def weights(objs, deform: set) -> dict:
    """Points no bone moves, and points moved by more bones than each engine takes."""
    n = unweighted = 0
    over = {k: 0 for k in ENGINE_INFLUENCES}
    for o in objs:
        names = {g.index: g.name for g in o.vertex_groups}
        for v in o.data.vertices:
            k = sum(1 for g in v.groups if g.weight > 1e-4 and names.get(g.group) in deform)
            n += 1
            if k == 0:
                unweighted += 1
            for eng, lim in ENGINE_INFLUENCES.items():
                if k > lim:
                    over[eng] += 1
    return {"points": n, "unweighted": unweighted, "over": over}


def unity_weights(W) -> np.ndarray:
    """The weights Unity plays: the export's own 4-bone limit (skin.engine_limit)."""
    from .skin import engine_limit
    return engine_limit(W, ENGINE_INFLUENCES["Unity"], ENGINE_MIN_WEIGHT, continuous=True)


# ----------------------------------------------------------------------------- the check

def _posed(obj, dg, n: int):
    ev = obj.evaluated_get(dg)
    me = ev.to_mesh()
    try:
        if len(me.vertices) != n:
            return None                           # (a modifier changed the mesh: not comparable)
        return _world_co(me, ev.matrix_world)
    finally:
        ev.to_mesh_clear()


def check(arm, objs, frames: list):
    """Generator: step through `frames` of the armature's current action, measure, and return
    the report. Yields the share done (0..1) between frames."""
    sc = bpy.context.scene
    deform = {b.name for b in arm.data.bones if b.use_deform}
    # engines blend linearly: measure that, whatever the modifier is set to
    mods = [(m, m.use_deform_preserve_volume) for o in objs for m in o.modifiers
            if m.type == "ARMATURE" and m.object is arm]
    keep_frame = sc.frame_current
    try:
        for m, _was in mods:
            m.use_deform_preserve_volume = False
        rests, sizes = _rest_points(arm, objs)
        rep = yield from _run(arm, objs, frames, deform, rests, sizes)
    finally:
        sc.frame_set(keep_frame)
        for m, was in mods:
            m.use_deform_preserve_volume = was
    rep["measured_as"] = {"blend": "linear", "preserve_volume_was_on": any(w for _m, w in mods),
                          "unity": "full mesh, before Unity's copy is reduced"}
    return rep


def _setup(arm, objs, deform, rests, sizes) -> dict:
    """Everything measured against: the rest points of all meshes in one array, their faces,
    edges and weights, and the layout of segments, joints and regions."""
    offs = np.cumsum([0] + sizes)
    rest = np.concatenate(rests) if rests else np.zeros((0, 3))
    tris = np.concatenate([_tris(o.data) + offs[k] for k, o in enumerate(objs)]) if objs \
        else np.zeros((0, 3), np.int64)
    edges = np.concatenate([_edges(o.data) + offs[k] for k, o in enumerate(objs)]) if objs \
        else np.zeros((0, 2), np.int64)
    used = sorted({g.name for o in objs for g in o.vertex_groups if g.name in deform and g.name in arm.pose.bones})
    W = np.concatenate([_weight_rows(o, used) for o in objs]) if objs else np.zeros((0, len(used)))
    labels = np.concatenate([np.full(sizes[k], str(o.get("forge_part") or o.name), object)
                             for k, o in enumerate(objs)]) if objs else np.zeros(0, object)
    rigid = np.zeros(len(rest), bool)               # an object pinned whole to one bone: a prop
    for k in range(len(objs)):
        Wk = W[offs[k]:offs[k + 1]]
        tk = Wk.sum(axis=1)
        if len(Wk) and (tk > 0).all() and (Wk.max(axis=1) >= 0.999 * tk).all() \
                and len(np.unique(Wk.argmax(axis=1))) == 1:
            rigid[offs[k]:offs[k + 1]] = True
    L = _Layout(arm, used, W, rest, tris, labels, rigid)
    return {"offs": offs, "rest": rest, "tris": tris, "edges": edges, "used": used, "W": W, "L": L}


def _rest_points(arm, objs) -> tuple:
    """(rest points per object, point counts): the meshes with the rig in its rest pose (shape
    keys and props pinned to a bone included)."""
    pose_position = arm.data.pose_position
    try:
        arm.data.pose_position = "REST"
        bpy.context.view_layer.update()
        dg = bpy.context.evaluated_depsgraph_get()
        rests, sizes = [], []
        for o in objs:
            n = len(o.data.vertices)
            r = _posed(o, dg, n)
            rests.append(r if r is not None else _world_co(o.data, o.matrix_world))
            sizes.append(n)
        return rests, sizes
    finally:
        arm.data.pose_position = pose_position
        bpy.context.view_layer.update()


def rest_layout(arm, objs) -> dict:
    """The layout the check measures against (for tests and diagnostics): see _setup."""
    deform = {b.name for b in arm.data.bones if b.use_deform}
    return _setup(arm, objs, deform, *_rest_points(arm, objs))


def pose_state(arm, L) -> tuple:
    """(skinning matrices, rotations, posed bone heads, posed bone tails) of the current frame."""
    mats = skin_matrices(arm, L.bones) if L.bones else np.zeros((0, 4, 4))
    R = _rotations(mats) if L.bones else np.zeros((0, 3, 3))
    H = np.einsum("kij,kj->ki", mats[:, :3, :3], L.H) + mats[:, :3, 3]
    T = np.einsum("kij,kj->ki", mats[:, :3, :3], L.T) + mats[:, :3, 3]
    return mats, R, H, T


def _run(arm, objs, frames, deform, rests, sizes):
    sc = bpy.context.scene
    st = _setup(arm, objs, deform, rests, sizes)
    offs, rest, tris, edges, used, W, L = (st[k] for k in ("offs", "rest", "tris", "edges", "used", "W", "L"))
    n_tris = max(len(tris), 1)
    el = np.linalg.norm(rest[edges[:, 0]] - rest[edges[:, 1]], axis=1) if len(edges) else np.zeros(0)
    med_edge = float(np.median(el[el > 0])) if (el > 0).any() else 1.0
    # Unity: the export's 4-bone limit against the weights as bound (Blender normalises them)
    W8 = L.Wn
    skinned = np.zeros(len(rest), bool)
    for k, o in enumerate(objs):
        if any(md.type == "ARMATURE" and md.object is arm for md in o.modifiers):
            skinned[offs[k]:offs[k + 1]] = True
    W4 = unity_weights(W) if len(used) else W8
    D = np.where(skinned[:, None], W4 - W8, 0.0)
    u_rows = np.flatnonzero(np.abs(D).max(axis=1) > 1e-9) if D.size else np.zeros(0, np.int64)
    at_rest_pairs = crossing_pairs(rest, tris)
    at_rest = np.zeros(len(tris), bool)
    at_rest[at_rest_pairs.ravel()] = True
    nreg = len(L.reg_names)
    # worst per region over the clip
    joints: dict = {}
    contact: dict = {}
    skin_s = np.ones(nreg)
    skin_f = np.full(nreg, -1)
    sq_s = np.ones(nreg)
    sq_f = np.full(nreg, -1)
    folds = np.zeros(nreg, np.int64)
    folds_f = np.full(nreg, -1)
    u_s = np.ones(nreg)
    crossing: dict = {}
    total_cross = (0, None)
    unity = {"shift": 0.0, "frame": None, "where": "", "added": 1.0, "added_frame": None, "added_where": ""}
    per_frame = []
    jzone_folds: dict = {}
    for i, f in enumerate(frames):
        sc.frame_set(f)
        dg = bpy.context.evaluated_depsgraph_get()
        parts = []
        for k, o in enumerate(objs):
            p = _posed(o, dg, sizes[k])
            parts.append(p if p is not None else rests[k])
        co = np.concatenate(parts) if parts else rest
        mats, R, H, T = pose_state(arm, L)
        row = {"frame": f}
        # ---- joints
        zone_of = np.full(len(rest), -1, np.int64)
        for ji, J in enumerate(L.joints):
            res = L.measure(J, co, R, H, T)
            if res is None:
                continue
            zone_of[res["zone"]] = ji
            if res["value"] is not None:
                rec = joints.get(J.name)
                if rec is None or res["value"] < rec["value"]:
                    joints[J.name] = {"value": res["value"], "part": res["part"], "frame": f,
                                      "bend": res["bend"], "twist": res["twist"], "turn": res["turn"],
                                      "kind": J.kind}
                row["volume"] = min(row.get("volume", 1.0), res["value"])
            if res["contact"] is not None:
                c = contact.get(J.name)
                if c is None or res["bend"] > c["bend"]:
                    contact[J.name] = {"value": res["contact"], "frame": f, "bend": res["bend"], "faces": 0,
                                       "folds": 0}
        # ---- skin
        tri_zone = zone_of[tris].max(axis=1) if len(tris) else np.zeros(0, np.int64)
        if (tri_zone >= 0).any():                    # a face touching the zone is in it (one ring)
            ring = zone_of.copy()
            hit = np.flatnonzero(tri_zone >= 0)
            free = ring[tris[hit]] < 0
            ring[tris[hit][free]] = np.repeat(tri_zone[hit], 3).reshape(-1, 3)[free]
            tri_zone = ring[tris].max(axis=1)
        if len(tris):
            s1, s2, nrm = principal_stretch(rest, co, tris)
            ok = L.tri_ok
            reg = L.tri_reg
            m1 = np.ones(nreg)
            np.maximum.at(m1, reg[ok], s1[ok])
            better = m1 > skin_s
            skin_s[better], skin_f[better] = m1[better], f
            m2 = np.ones(nreg)
            np.minimum.at(m2, reg[ok], s2[ok])
            better = m2 < sq_s
            sq_s[better], sq_f[better] = m2[better], f
            Rt = R[L.tri_bone] if len(used) else np.broadcast_to(np.eye(3), (len(tris), 3, 3))
            expect = np.einsum("kij,kj->ki", Rt, L.rest_n)
            inv = ok & ~L.tri_free & (np.einsum("ij,ij->i", expect, nrm) < 0)
            fold = inv & (tri_zone < 0)
            fc = np.bincount(reg[fold], minlength=nreg)
            better = fc > folds
            folds[better], folds_f[better] = fc[better], f
            for ji in np.unique(tri_zone[inv & (tri_zone >= 0)]).tolist():
                nm = L.joints[ji].name
                jzone_folds[nm] = max(jzone_folds.get(nm, 0), int((inv & (tri_zone == ji)).sum()))
            row["stretch"] = float(s1[ok].max()) if ok.any() else 1.0
        # ---- crossings
        pairs = crossing_pairs(co, tris)
        if len(pairs):
            pairs = pairs[~(at_rest[pairs[:, 0]] | at_rest[pairs[:, 1]])]
        row["crossing"] = int(len(np.unique(pairs))) if len(pairs) else 0
        if row["crossing"] > total_cross[0]:
            total_cross = (row["crossing"], f)
        if len(pairs):
            za, zb = tri_zone[pairs[:, 0]], tri_zone[pairs[:, 1]]
            sa, sb = L.tri_seg[pairs[:, 0]], L.tri_seg[pairs[:, 1]]
            is_contact = (za >= 0) & (za == zb)
            groups: dict = {}
            for (a, b), cz, x, y in zip(pairs.tolist(), is_contact.tolist(), sa.tolist(), sb.tolist()):
                if cz:
                    key = ("contact", L.joints[int(tri_zone[a])].name)
                elif x == y:
                    key = ("fold", L.segs[x].name)
                else:
                    na, nb = sorted((L.segs[x].name, L.segs[y].name))
                    key = ("touch", f"{na} touches {nb}")
                groups.setdefault(key, set()).update((a, b))
            for key, faces in groups.items():
                c = crossing.get(key)
                if c is None or len(faces) > c["faces"]:
                    crossing[key] = {"faces": len(faces), "frame": f}
                if key[0] == "contact" and key[1] in contact:
                    contact[key[1]]["faces"] = max(contact[key[1]]["faces"], len(faces))
        # ---- Unity: the same pose with its 4-bone weights
        if len(u_rows):
            rr = rest[u_rows]
            delta = np.zeros((len(u_rows), 3))
            Du = D[u_rows]
            for j in np.flatnonzero(np.abs(Du).max(axis=0) > 1e-12):
                delta += Du[:, j, None] * (rr @ mats[j, :3, :3].T + mats[j, :3, 3])
            sh = np.linalg.norm(delta, axis=1)
            k = int(np.argmax(sh))
            if sh[k] > unity["shift"]:
                unity.update(shift=float(sh[k]), frame=f, where=L.reg_names[L.pt_reg[u_rows[k]]])
            cu = co.copy()
            cu[u_rows] += delta
            if len(tris):
                us1, _us2, _n = principal_stretch(rest, cu, tris)
                m1u = np.ones(nreg)
                np.maximum.at(m1u, L.tri_reg[L.tri_ok], us1[L.tri_ok])
                u_s = np.maximum(u_s, m1u)
                add = np.where(L.tri_ok, us1 / np.maximum(s1, 1e-12), 1.0)
                k = int(np.argmax(add))
                if add[k] > unity["added"]:
                    unity.update(added=float(add[k]), added_frame=f, added_where=L.reg_names[L.tri_reg[k]])
        per_frame.append(row)
        yield (i + 1) / max(len(frames), 1)
    return _report(L, frames, n_tris, med_edge, joints, contact, jzone_folds, skin_s, skin_f, sq_s, sq_f,
                   folds, folds_f, crossing, total_cross, at_rest, unity, u_s, objs, arm, deform, per_frame)


def _lbs_floor(turn_deg: float) -> float:
    """The thickness linear blending keeps at a joint turned this far (50/50 blend): cos(turn/2)."""
    return math.cos(math.radians(min(abs(turn_deg), 180.0)) / 2.0)


def _report(L, frames, n_tris, med_edge, joints, contact, jzone_folds, skin_s, skin_f, sq_s, sq_f, folds,
            folds_f, crossing, total_cross, at_rest, unity, u_s, objs, arm, deform, per_frame) -> dict:
    out = {"frames": len(frames), "checks": {}}
    # ---- joints: worst per joint, contact as information
    jr = []
    contact = {k: c for k, c in contact.items()
               if c["value"] < LIMITS["volume"][0] or c["faces"] or jzone_folds.get(k, 0)}
    for name, r in joints.items():
        floor = _lbs_floor(r["turn"])
        g = _grade(r["value"], *LIMITS["volume"], below=True)
        e = {"where": name, "grade": g, "value": round(r["value"], 3), "part": r["part"], "frame": r["frame"],
             "bend_deg": int(round(r["bend"])), "twist_deg": int(round(abs(r["twist"]))), "kind": r["kind"],
             "lbs": round(floor, 2), "normal": bool(r["value"] >= floor - LBS_MARGIN)}
        if name in contact:
            c = contact[name]
            e["contact"] = {"value": round(c["value"], 3), "frame": c["frame"], "bend_deg": int(round(c["bend"])),
                            "faces": c["faces"], "folds": jzone_folds.get(name, 0)}
        jr.append(e)
    for name, c in contact.items():
        if name not in joints:
            jr.append({"where": name, "grade": "pass", "value": None, "frame": None, "kind": "joint",
                       "contact": {"value": round(c["value"], 3), "frame": c["frame"],
                                   "bend_deg": int(round(c["bend"])), "faces": c["faces"],
                                   "folds": jzone_folds.get(name, 0)}})
    jr.sort(key=lambda e: (-ORDER.index(e["grade"]), e["value"] if e["value"] is not None else 9.0))
    worst = next((e for e in jr if e["value"] is not None), None)
    out["checks"]["joints"] = {
        "grade": worst["grade"] if worst else "pass", "value": worst["value"] if worst else 1.0,
        "frame": worst["frame"] if worst else None, "where": worst["where"] if worst else "",
        "part": worst["part"] if worst else None, "bend_deg": worst["bend_deg"] if worst else None,
        "regions": jr}
    # ---- skin: worst stretch and folds per region
    sr = []
    for k, name in enumerate(L.reg_names):
        st = float(skin_s[k])
        fd = int(folds[k])
        if st <= 1.0 + 1e-9 and fd == 0:
            continue
        gs = _grade(st, *LIMITS["stretch"], below=False)
        gf = _grade(fd / n_tris, *LIMITS["folds"], below=False)
        e = {"where": name, "grade": _worse(gs, gf), "stretch": round(st, 2),
             "frame": int(skin_f[k]) if skin_f[k] >= 0 else None, "stretch_grade": gs, "folds": fd, "folds_grade": gf,
             "squash": round(float(sq_s[k]), 2)}
        if fd:
            e["folds_frame"] = int(folds_f[k])
        if sq_f[k] >= 0:
            e["squash_frame"] = int(sq_f[k])
        sr.append(e)
    sr.sort(key=lambda e: (-ORDER.index(e["grade"]), -e["stretch"]))
    ws = max(sr, key=lambda e: e["stretch"], default=None)
    wf = max(sr, key=lambda e: e["folds"], default=None)
    out["checks"]["skin"] = {
        "grade": max((e["grade"] for e in sr), key=ORDER.index, default="pass"),
        "stretch": ws["stretch"] if ws else 1.0, "frame": ws["frame"] if ws else None,
        "where": ws["where"] if ws else "", "folds": wf["folds"] if wf else 0,
        "folds_where": wf["where"] if wf and wf["folds"] else "", "regions": sr}
    if wf and wf["folds"]:
        out["checks"]["skin"]["folds_frame"] = wf["folds_frame"]
    # ---- crossings: contact (information), folds (faults), parts touching (warnings)
    cr = []
    for (kind, where), c in crossing.items():
        if kind == "contact":
            g = "info"
        elif kind == "fold":
            g = _grade(c["faces"] / n_tris, *LIMITS["crossing"], below=False)
        else:
            g = "warn"
        cr.append({"where": where, "kind": kind, "grade": g, "faces": c["faces"], "frame": c["frame"]})
    rank = {"fail": 0, "warn": 1, "info": 2}
    cr.sort(key=lambda e: (rank[e["grade"]], -e["faces"]))
    faults = [e for e in cr if e["kind"] != "contact"]
    cg = max((e["grade"] for e in faults), key=ORDER.index, default="pass")
    out["checks"]["crossing"] = {
        "grade": cg, "value": int(total_cross[0]), "frame": total_cross[1], "at_rest": int(at_rest.sum()),
        "contact": sum(e["faces"] for e in cr if e["kind"] == "contact"),
        "folds": sum(e["faces"] for e in cr if e["kind"] == "fold"),
        "touches": sum(e["faces"] for e in cr if e["kind"] == "touch"), "regions": cr}
    # ---- weights: unweighted points, and what Unity's limit does
    skinned = [o for o in objs if any(md.type == "ARMATURE" and md.object is arm for md in o.modifiers)]
    w = weights(skinned, deform)                     # (a prop pinned to a bone has no weights)
    crossed = []
    for k, name in enumerate(L.reg_names):
        if ORDER.index(_grade(float(u_s[k]), *LIMITS["stretch"], below=False)) > \
                ORDER.index(_grade(float(skin_s[k]), *LIMITS["stretch"], below=False)):
            crossed.append(name)
    shift_edges = unity["shift"] / max(med_edge, 1e-12)
    ug = "warn" if (shift_edges > UNITY_SHIFT or crossed) else "pass"
    w["unity"] = {"grade": ug, "shift_mm": round(unity["shift"] * 1000.0, 1), "shift_edges": round(shift_edges, 2),
                  "frame": unity["frame"], "where": unity["where"], "added_stretch": round(unity["added"], 2),
                  "added_frame": unity["added_frame"], "added_where": unity["added_where"],
                  "stretch": round(float(u_s.max()) if len(u_s) else 1.0, 2), "limit_crossed": crossed[:5],
                  "measured_on": "full mesh"}
    wg = "fail" if w["unweighted"] else ug
    out["checks"]["weights"] = {"grade": wg, **w}
    out["grade"] = max((x["grade"] for x in out["checks"].values()), key=ORDER.index)
    bad = [x for x in out["checks"].values() if x.get("frame") is not None and x["grade"] != "pass"]
    if w["unity"]["grade"] != "pass" and w["unity"]["frame"] is not None:
        bad.append({"grade": w["unity"]["grade"], "frame": w["unity"]["frame"]})
    worst_check = max(bad, key=lambda x: ORDER.index(x["grade"]), default=None)
    out["worst_frame"] = worst_check["frame"] if worst_check else None
    out["regions"] = by_region(out["checks"])
    out["per_frame"] = per_frame
    return out


def by_region(checks: dict) -> list:
    """The findings per region (a joint, a segment, two parts touching), worst region first:
    [{"where", "grade", "worst": finding, "contact": finding or None, "findings": [worst first]}].
    A finding is a copy of a region entry of one check, with "check" naming it; contact is
    "info" (expected at a bend, never a fault). Regions where everything passes are left out."""
    found: dict = {}

    def add(f):
        found.setdefault(f["where"], []).append(f)

    for e in (checks.get("joints") or {}).get("regions", []):
        if e.get("value") is not None:
            add({**{k: v for k, v in e.items() if k != "contact"}, "check": "joints"})
        if e.get("contact"):
            add({**e["contact"], "where": e["where"], "grade": "info", "check": "contact"})
    for e in (checks.get("skin") or {}).get("regions", []):
        add({**e, "check": "skin"})
    for e in (checks.get("crossing") or {}).get("regions", []):
        if e["kind"] == "contact":
            continue                                  # (counted with the joint's contact)
        add({**e, "check": "crossing"})
    sev = {"fail": 3, "warn": 2, "info": 1, "pass": 0}
    out = []
    for where, fs in found.items():
        fs.sort(key=lambda f: (-sev.get(f["grade"], 0), _badness(f)))
        worst = fs[0]
        if sev.get(worst["grade"], 0) == 0:
            continue
        out.append({"where": where, "grade": worst["grade"], "worst": worst,
                    "contact": next((f for f in fs if f["check"] == "contact"), None),
                    "findings": [f for f in fs if f["grade"] != "pass"]})
    out.sort(key=lambda r: (-sev.get(r["grade"], 0), _badness(r["worst"])))
    return out


def _badness(f: dict) -> float:
    """Lower = worse, to order findings of one grade."""
    c = f.get("check")
    if c == "joints":
        return float(f.get("value") or 1.0) - 2.0
    if c == "skin":
        return -float(f.get("stretch") or 1.0) - 0.01 * float(f.get("folds") or 0)
    if c in ("crossing", "contact"):
        return -float(f.get("faces") or 0) / 1e4
    if c == "unity":
        return -float(f.get("shift_edges") or 0.0)
    return 0.0
