"""Automatic checks while a sample clip plays on the rig (Step 8).

"Watch for tearing" becomes a pass / warn / fail for each part of the body, with the frame
where it is worst (the caller adds the test pose shown at that frame):

  joints    where two body segments share the skin (elbow, knee, shoulder, ear root, tail root)
            the skin keeps its distance from the bones. Each frame the child segment's turn
            against its parent is split into a bend and a twist, and each point is put on the
            inner side of the bend, on a side, or on the outer side. A limb of radius r bent by
            an angle presses into itself on the inner side up to r*tan(angle/2) from the joint
            (further where the other side is thicker: _Layout._reach): that is contact, expected,
            and shown as information. Thinning anywhere else is the skinning's: the sides, the
            outer side (linear blending's elbow loss), the inner side past the contact (a blend
            reaching too far along the limb) and a twist (the candy wrapper). Twist bones along
            one segment are judged as '<segment> twist', and the skin they share is named so.
            A frame where the two bones no longer meet at the joint (the lower back turning
            about the body's middle, against the thigh) is skin sliding: the skin check's.
  skin      each triangle's largest principal stretch against rest (the texture smears), its
            smallest where no joint bends it (squash: the texture bunches), and triangles turned
            inside out outside a contact zone (folds): the worst per region. Slivers are not
            read. Where the stretch is high, the part the pose itself asks for, whatever the
            weights, is proved and named (_pose_floors), so the panel never advises weights
            that cannot help
  crossing  faces newly passing through faces. Inside one joint's contact zone: contact. Inside
            one segment: a fold (a fault). Between parts: '<A> touches <B>' (a forearm into an
            ear). Faces that already cross at rest are not counted. Faces lying inside another
            shell at rest - the root of a part Step 4 kept as its own piece, plugged into the
            body - are its 'hidden root' when they come out (hidden_faces), never a touch
  weights   points no bone moves; and what Unity's 4-bone limit does to the skin (simulated
            with the same limit the export applies, on the full mesh before Unity's copy is
            reduced): how far it moves the skin and the stretch it adds

What is measured is what the engines play: linear blending (Preserve Volume is switched off
while measuring), Unreal with the weights as bound (8 bones at most), Unity cut to 4. A mesh
whose modifiers add points after the bones move it is measured without them. Every finding
names its region and how far past its limit it is ("over"); the worst finding per region is
listed (by_region), worst first on that one scale whatever the check.
"""

from __future__ import annotations

import math
import re

import numpy as np

import bpy

LIMITS = {
    "volume": (0.7, 0.5),          # (warn below, fail below) joint thickness kept, posed / rest
    "stretch": (1.5, 2.0),         # (warn above, fail above) a triangle's largest stretch: smear
    "squash": (0.3, 0.0),          # (warn below, never fails) a triangle's smallest stretch: bunching
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
SLIVER = 0.05                      # nor triangles lower than this share of their longest edge: a
                                   # sliver's stretch is a tiny move over its tiny height
ZONE_TOL = 0.25                    # a face is in a contact zone up to this share further out than
                                   # rigid limbs would meet (linear blending bulges the crease a little)
UNITY_SHIFT = 0.5                  # Unity's limit moving skin more than this many median edges: warn
LBS_MARGIN = 0.05                  # thinning within this of linear blending's own loss is the method's
SEPARATE = 0.25                    # the two bones of a joint this far apart at it (x its radius): shear
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
    (r"shoulder", "shoulder blade", ""),          # (Auto-Rig Pro's shoulder bone: its joints are
                                                  # the collarbone and the shoulder)
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
# joints and segments never share a name (a place is named once): the spine's lowest segment is
# "small of the back", the joint below it "lower back"; the neck segment is "neck", the joints
# at its ends "base of the neck" and "top of the neck"
JOINT_WORDS = {("upper arm", "forearm"): "elbow", ("forearm", "hand"): "wrist", ("thigh", "calf"): "knee",
               ("calf", "foot"): "ankle", ("foot", "toes"): "ball of the foot", ("neck", "head"): "top of the neck",
               ("head", "jaw"): "jaw", ("hips", "spine"): "lower back", ("spine", "spine"): "back",
               ("spine", "head"): "neck", ("spine", "neck"): "base of the neck"}

ALT_WORDS = {"neck": "base of the head"}      # (the chest against the head, when there is a neck too)


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


def hidden_faces(rest, tris) -> tuple:
    """(hidden, shell, plugged): which triangles lie, at rest, inside ANOTHER closed shell of
    the measured meshes, each triangle's shell, and the pairs of shells one of which is
    plugged into the other ({frozenset((a, b))}). A part Step 4 kept as its own piece has its
    root plugged into the body (and the body's lid under it lies inside the part): crossing
    nothing at rest, those faces come out when the part turns. That is the part's hidden root
    showing, not two parts touching. Read by shells, not by names: a tail, a wing, an antenna.
    Inside: ray parity against the other shell (rescue._parity_inside)."""
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    from .appendages import _components
    from .rescue import _parity_inside
    hid = np.zeros(len(tris), bool)
    plugged: set = set()
    if len(tris) < 2:
        return hid, np.zeros(len(tris), np.int64), plugged
    e = np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]])
    lab = _components(len(rest), e[:, 0], e[:, 1])
    tlab = lab[tris[:, 0]]
    shells = np.unique(tlab)
    if len(shells) < 2:
        return hid, tlab, plugged
    se, cnt = np.unique(np.sort(e, axis=1), axis=0, return_counts=True)
    open_shell = set(np.unique(lab[se[cnt != 2].ravel()]).tolist())     # (parity needs a closed one)
    cen = rest[tris].mean(axis=1)
    size = float(np.ptp(rest, axis=0).max()) if len(rest) else 1.0
    for s in shells.tolist():
        if s in open_shell:
            continue
        mine = tlab == s
        lo, hi = rest[tris[mine]].reshape(-1, 3).min(axis=0), rest[tris[mine]].reshape(-1, 3).max(axis=0)
        cand = np.flatnonzero(~mine & ~hid & np.all((cen >= lo) & (cen <= hi), axis=1))
        if not len(cand):
            continue
        tree = BVHTree.FromPolygons([Vector(p) for p in rest], tris[mine].tolist(), all_triangles=True)
        eps = 1e-6 * max(size, 1e-3)
        for t in cand.tolist():
            if _parity_inside(tree, Vector(cen[t]), eps):
                hid[t] = True
                plugged.add(frozenset((int(tlab[t]), int(s))))
    return hid, tlab, plugged


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
            sw = "back" if n == 1 else ("small of the back" if k == 0 else "chest" if k == n - 1
                                        else "middle of the back" + (f" {k}" if n > 3 else ""))
            key, seg = b, _Seg(b, "spine", sw, "", "", True, RANK["spine"] + 0.1 * k)
        elif word is not None:
            role = "finger" if word.endswith("finger") or word == "thumb" else \
                "shoulder" if word == "shoulder blade" else word
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
    if P.role == "spine" and C.role == "spine" and C.word != "chest":
        return f"back under the {C.word}"            # (three or more spine bones)
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
        self.own = own
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
        self.tri_c = rest[tris].mean(axis=1) if len(tris) else np.zeros((0, 3))
        # each point's two strongest segments
        top = np.argsort(-SW, axis=1, kind="stable")[:, :2] if len(segs) > 1 else np.zeros((n, 2), np.int64)
        rows = np.arange(n)
        self.s1 = top[:, 0]
        self.s2 = np.where(SW[rows, top[:, 1]] >= BLEND, top[:, 1], -1) if len(segs) > 1 else np.full(n, -1)
        self._names: dict = {}
        self.joints: list = []
        self._find_joints()
        self.pt_reg, self.reg_names = self._regions(self.s1, self.s2, None, self._in_twist(Wn, self.s1, self.s2))
        ts = SW[tris].mean(axis=1) if len(tris) else np.zeros((0, len(segs)))
        if len(tris) and len(segs) > 1:
            tt = np.argsort(-ts, axis=1, kind="stable")[:, :2]
            t1 = tt[:, 0]
            t2 = np.where(ts[np.arange(len(tris)), tt[:, 1]] >= BLEND, tt[:, 1], -1)
        else:
            t1, t2 = np.zeros(len(tris), np.int64), np.full(len(tris), -1)
        self.tri_seg = t1
        tw_n = Wn[tris].mean(axis=1) if len(tris) else np.zeros((0, len(bones)))
        self.tri_reg, _ = self._regions(t1, t2, self.reg_names, self._in_twist(tw_n, t1, t2))
        # each triangle's strongest bone (its rest normal turns with it)
        tw = W[tris].sum(axis=1) if len(tris) else np.zeros((0, len(bones)))
        self.tri_bone = np.argmax(tw, axis=1) if len(bones) else np.zeros(len(tris), np.int64)
        self.tri_free = tw.sum(axis=1) <= 1e-9 if len(tris) else np.zeros(0, bool)
        r0 = rest[tris[:, 0]] if len(tris) else np.zeros((0, 3))
        self.rest_n = np.cross(rest[tris[:, 1]] - r0, rest[tris[:, 2]] - r0) if len(tris) else np.zeros((0, 3))
        area = np.linalg.norm(self.rest_n, axis=1)
        longest = np.linalg.norm(rest[tris] - rest[np.roll(tris, 1, axis=1)], axis=2).max(axis=1) \
            if len(tris) else np.zeros(0)
        height = area / np.maximum(longest, 1e-30)             # (area here is twice the triangle's)
        self.tri_ok = (area >= MIN_AREA * (np.median(area) if len(area) else 0.0)) & (height >= SLIVER * longest)

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
        """The name of the region where segments i and j share skin ('left elbow'). A joint
        never takes a segment's name (or a twist's): that one gets a number. Two segment pairs
        with the same anatomical word are one place (the collarbone against either chest bone)."""
        key = (min(i, j), max(i, j))
        if key not in self._names:
            self._names[key] = self._unique(self._pair_word(i, j))
        return self._names[key]

    def _unique(self, name: str) -> str:
        taken = {s.name for s in self.segs} | {f"{s.name} twist" for s in self.segs if s.kind == "twist"}
        if name not in taken:
            return name
        if name in ALT_WORDS and ALT_WORDS[name] not in taken:
            return ALT_WORDS[name]
        k = 2
        while f"{name} {k}" in taken:
            k += 1
        return f"{name} {k}"

    def _pair_word(self, i: int, j: int) -> str:
        P, C = self.segs[i], self.segs[j]
        if not P.bones or not C.bones:
            return f"{P.name} and {C.name}"
        (pb, cb), _p, _c = self._order(P.bones, C.bones, P.rank, C.rank)
        if pb is C.bones:
            P, C = C, P
        w = _joint_word(P, C)
        side = C.side or P.side
        if w is not None:
            return f"{side} {w}".strip()
        if P.arp and C.arp:
            return f"{C.name} and {P.name}"
        child = self.bones[cb[0]] if len(cb) == 1 else C.name
        return f"{_nice(child)} joint"

    def _in_twist(self, Wb, s1, s2) -> np.ndarray:
        """Items (points or faces, weights Wb over bones) inside one segment that its twist bones
        share (the 2nd of them moves it BLEND or more): the '<segment> twist' place, where the
        twist joint is judged - its skin is named the same, one place under one name."""
        out = np.zeros(len(s1), bool)
        for k, seg in enumerate(self.segs):
            if seg.kind != "twist" or len(seg.bones) < 2:
                continue
            m = np.flatnonzero((s1 == k) & (s2 < 0))
            if not len(m):
                continue
            sub = Wb[np.ix_(m, seg.bones)]
            tot = np.maximum(sub.sum(axis=1), 1e-12)
            second = np.sort(sub, axis=1)[:, -2]
            out[m[second / tot >= BLEND]] = True
        return out

    def _regions(self, s1, s2, names=None, twist=None) -> tuple:
        names = [] if names is None else names
        at = {nm: k for k, nm in enumerate(names)}
        out = np.empty(len(s1), np.int64)
        cache: dict = {}
        tw = np.zeros(len(s1), bool) if twist is None else twist
        for k, (a, b, t) in enumerate(zip(s1.tolist(), s2.tolist(), tw.tolist())):
            key = ((a, b, t) if b < 0 else (min(a, b), max(a, b), False))
            r = cache.get(key)
            if r is None:
                nm = (f"{self.segs[a].name} twist" if t else self.segs[a].name) if b < 0 else self.pair_name(a, b)
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
        # the contact zone can hold any point (and face) of the two sides near the joint
        side_w = np.where(self.own, 0.0, self.Wn[:, J.union].sum(axis=1))    # (a prop is a part of its own)
        cand = np.flatnonzero(side_w >= 0.5)
        rdir, along, rd = self._radial(J, self.rest[cand])
        # each side's radius near the joint, where it is widest (90th percentile, within two
        # radii of it): a tapered limb's thick side meets the thin side further out
        crest = _dist_union(self.rest[cand], self.H, self.T, J.union)
        for nm, m in (("r_p", along < 0.0), ("r_c", along >= 0.0)):
            m = m & (np.abs(along) < 2.0 * J.r) & (crest >= 0.25 * J.r) & (crest < 3.0 * J.r)
            setattr(J, nm, float(np.percentile(crest[m], 90)) if m.sum() >= MIN_PART_POINTS else J.r)
        keep = rd < 2.0 * max(J.r, J.r_p, J.r_c, 1e-9)
        J.cidx, J.c_rdir, J.c_along, J.c_rd = cand[keep], rdir[keep], along[keep], rd[keep]
        tw = side_w[self.tris].mean(axis=1) if len(self.tris) else np.zeros(0)
        tc = np.flatnonzero(tw >= 0.5)
        rdir, along, rd = self._radial(J, self.tri_c[tc])
        keep = rd < 2.0 * max(J.r, J.r_p, J.r_c, 1e-9)
        J.tidx, J.t_rdir, J.t_along, J.t_rd = tc[keep], rdir[keep], along[keep], rd[keep]
        # faces whose three corners the two sides share: the joint's blend, where linear blending
        # folds the crease in a little further than rigid limbs would meet
        shared = np.zeros(n, bool)
        shared[idx] = True
        J.t_band = shared[self.tris[J.tidx]].all(axis=1) if len(J.tidx) else np.zeros(0, bool)
        return J

    @staticmethod
    def _reach(J, rho, along, theta):
        """How far from the joint, along the limb, the inner side of a bend presses into the
        other side. A point at distance a along its limb and rho from the axis, turned by theta
        against the other side (a limb of radius r ending at the joint), is inside it while
        a <= (r - rho cos theta) / sin theta (and, under 90 degrees, a <= rho tan theta: still
        behind the joint). Both as thick: r tan(theta/2). A thin limb turning against a thick
        one (an arm against the shoulder) presses in further; a thick side's far skin never
        meets a thin limb (0)."""
        t = math.radians(min(theta, 179.0))
        c, s = math.cos(t), math.sin(t)
        other = np.where(along >= 0.0, J.r_p, J.r_c)
        reach = (other - rho * c) / s
        if theta < 90.0:
            reach = np.minimum(reach, rho * math.tan(t))
        return np.maximum(reach, 0.0)

    @staticmethod
    def _radial(J, P) -> tuple:
        v = P - J.pivot
        along = v @ J.axis
        rad = v - along[:, None] * J.axis
        rd = np.linalg.norm(rad, axis=1)
        return rad / np.maximum(rd, 1e-12)[:, None], along, rd

    def measure(self, J, co, R, H, T, mats=None):
        """One joint at one frame: its bend, twist, the thickness kept on each side of the bend,
        and its contact zone (indices of points). None when it neither bends nor twists, or when
        its two bones no longer meet at the joint (mats given): a parent turning about a far
        point drags its side away (the lower back in a spine twist, against the thigh) - that
        is skin shearing, which the skin check judges, not a joint closing."""
        Rrel = R[J.p].T @ R[J.c]
        theta, tw, total, bdir = _swing_twist(Rrel, J.axis)
        if theta < MIN_TURN and abs(tw) < MIN_TURN:
            return None
        if mats is not None:
            at_p = mats[J.p, :3, :3] @ J.pivot + mats[J.p, :3, 3]
            at_c = mats[J.c, :3, :3] @ J.pivot + mats[J.c, :3, 3]
            if np.linalg.norm(at_p - at_c) > SEPARATE * max(J.r, 1e-9):
                return None
        ratio = _dist_union(co[J.idx], H, T, J.union) / np.maximum(J.rest, 1e-12)
        use = J.use
        if theta >= MIN_TURN:
            # the half of the limb the bend closes on presses into the other half (see _reach):
            # that is contact. Only the inner side is excused there; the sides and the outer
            # side are graded all the way to the joint.
            s = J.rdir @ bdir
            inner, outer = s > INNER, s < -INNER
            zone = (s > 0.0) & (np.abs(J.along) < self._reach(J, J.rd, J.along, theta))
            cs = J.c_rdir @ bdir
            czone = J.cidx[(cs > 0.0) & (np.abs(J.c_along) < self._reach(J, J.c_rd, J.c_along, theta))]
            # faces: near the joint by where they are (their centre), with a margin in proportion
            # to the reach - the same on a coarse game mesh as on a fine one - or when the two
            # sides share all their corners (the blend: linear blending folds the crease in
            # there; a point weighted to the wrong bone is not shared, so its folds still count).
            # Near the joint the inner side presses and the sides pinch under linear blending:
            # faces crossing or turning there are the bend's (contact), and so is squash all round
            ts = J.t_rdir @ bdir
            near = (np.abs(J.t_along) < self._reach(J, J.t_rd, J.t_along, theta) * (1.0 + ZONE_TOL)) | J.t_band
            tzone, tbend = J.tidx[(ts > -INNER) & near], J.tidx[near]
            parts = {"inner side": use & inner & ~zone, "sides": use & ~inner & ~outer,
                     "outer side": use & outer}
            cz = use & zone & inner
        else:
            zone = np.zeros(len(J.idx), bool)
            czone, tzone, tbend = J.cidx[:0], J.tidx[:0], J.tidx[:0]
            parts = {"all round": use}
            cz = zone
        vals = {k: float(np.percentile(ratio[m], 5)) for k, m in parts.items() if m.sum() >= MIN_PART_POINTS}
        part = min(vals, key=vals.get) if vals else None
        # each point's place this frame: 2 contact zone, 1 inner side, 0 a side (or a twist), -1 outer
        side = np.where(zone, 2, 0) if theta < MIN_TURN else \
            np.where(zone, 2, np.where(inner, 1, np.where(outer, -1, 0)))
        return {"bend": theta, "twist": tw, "turn": total, "part": part,
                "value": vals[part] if part else None, "parts": vals,
                "contact": float(np.percentile(ratio[cz], 5)) if cz.sum() >= MIN_PART_POINTS else None,
                "zone": czone, "tzone": tzone, "tbend": tbend, "side": side, "ratio": ratio}


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
    hidden: list = []                         # (modifier, was shown) switched off while measuring
    try:
        for m, _was in mods:
            m.use_deform_preserve_volume = False
        objs, without, skipped = _comparable(objs, hidden)
        rests, sizes = _rest_points(arm, objs)
        rep = yield from _run(arm, objs, frames, deform, rests, sizes)
    finally:
        sc.frame_set(keep_frame)
        for m, was in mods:
            m.use_deform_preserve_volume = was
        for m, was in hidden:
            m.show_viewport = was
        if hidden:
            bpy.context.view_layer.update()
    rep["measured_as"] = {"blend": "linear", "preserve_volume_was_on": any(w for _m, w in mods),
                          "unity": "full mesh, before Unity's copy is reduced"}
    if without:
        rep["measured_as"]["without_modifiers"] = without
    if skipped:
        rep["skipped"] = skipped
    return rep


def _comparable(objs, hidden: list) -> tuple:
    """(objects to measure, {object: modifiers left out}, {object: why not measured}). A modifier
    that adds or removes points (Subdivision, Decimate...) makes the moved mesh no longer match
    its rest points: measured as it was, the object would read frozen - skin turned inside out
    that never moved. Such an object is measured without those modifiers (the skinned cage, what
    the bones move); one that still does not match is left out and named."""
    dg = bpy.context.evaluated_depsgraph_get()
    keep, without, skipped = [], {}, {}
    for o in objs:
        if _count(o, dg) == len(o.data.vertices):
            keep.append(o)
            continue
        off = [m for m in o.modifiers if m.type != "ARMATURE" and m.show_viewport]
        for m in off:
            hidden.append((m, True))
            m.show_viewport = False
        bpy.context.view_layer.update()
        dg = bpy.context.evaluated_depsgraph_get()
        if off and _count(o, dg) == len(o.data.vertices):
            keep.append(o)
            without[o.name] = [m.name for m in off]
        else:
            for m in off:
                m.show_viewport = True
                hidden.remove((m, True))
            bpy.context.view_layer.update()
            dg = bpy.context.evaluated_depsgraph_get()
            skipped[o.name] = "its modifiers change its points, so its movement cannot be measured"
    return keep, without, skipped


def _count(obj, dg) -> int:
    ev = obj.evaluated_get(dg)
    me = ev.to_mesh()
    try:
        return len(me.vertices)
    finally:
        ev.to_mesh_clear()


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
    hidden, tshell, plugged = hidden_faces(rest, tris)
    hidden &= ~at_rest
    root_word: dict = {}

    def hidden_root(a: int, b: int) -> str:
        """'hidden root of the tail': named after the smaller shell of the two (the piece),
        by the segment carrying most of its faces."""
        sa, sb = int(tshell[a]), int(tshell[b])
        na, nb = int((tshell == sa).sum()), int((tshell == sb).sum())
        s = sa if na <= nb else sb
        if s not in root_word:
            seg = L.segs[int(np.bincount(L.tri_seg[tshell == s]).argmax())]
            root_word[s] = f"a part on the {seg.name}" if seg.role in CORE or seg.role is None \
                else f"the {seg.name}"
        return f"hidden root of {root_word[s]}"
    nreg = len(L.reg_names)
    # worst per region over the clip
    joints: dict = {}
    contact: dict = {}
    skin_s = np.ones(nreg)
    skin_f = np.full(nreg, -1)
    skin_t = np.full(nreg, -1)
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
        tri_zone = np.full(len(tris), -1, np.int64)     # a joint whose contact zone holds each face
        tri_bend = np.zeros(len(tris), bool)            # faces a bend squeezes (near a bending joint)
        zones = []                                      # (joint, its contact faces) this frame
        for ji, J in enumerate(L.joints):
            res = L.measure(J, co, R, H, T, mats)
            if res is None:
                continue
            tri_zone[res["tzone"]] = ji
            tri_bend[res["tbend"]] = True
            if len(res["tzone"]):
                zones.append((ji, res["tzone"]))
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
        if len(tris):
            s1, s2, nrm = principal_stretch(rest, co, tris)
            ok = L.tri_ok
            reg = L.tri_reg
            m1 = np.ones(nreg)
            np.maximum.at(m1, reg[ok], s1[ok])
            better = m1 > skin_s
            skin_s[better], skin_f[better] = m1[better], f
            for k in np.flatnonzero(better).tolist():          # (its worst face: for the pose's floor)
                at = np.flatnonzero(ok & (reg == k))
                skin_t[k] = int(at[np.argmax(s1[at])])
            # skin squashed together where no joint bends it (a bone scaled, points pulled together)
            sq_ok = ok & ~tri_bend
            m2 = np.ones(nreg)
            np.minimum.at(m2, reg[sq_ok], s2[sq_ok])
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
            # contact: both faces in one joint's zone (a face can be near two joints)
            pz = np.full(len(pairs), -1, np.int64)
            inz = np.zeros(len(tris), bool)
            for ji, tz in zones:
                inz[:] = False
                inz[tz] = True
                pz[(pz < 0) & inz[pairs[:, 0]] & inz[pairs[:, 1]]] = ji
            sa, sb = L.tri_seg[pairs[:, 0]], L.tri_seg[pairs[:, 1]]
            groups: dict = {}
            for (a, b), cz, x, y in zip(pairs.tolist(), pz.tolist(), sa.tolist(), sb.tolist()):
                if hidden[a] or hidden[b] or (x == y and tshell[a] != tshell[b]
                                              and frozenset((int(tshell[a]), int(tshell[b]))) in plugged):
                    # (or the piece and the body round its root, both carried by the part's bones)
                    key = ("hidden", hidden_root(a, b))
                elif cz >= 0:
                    key = ("contact", L.joints[cz].name)
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
    floors = _pose_floors(arm, L, rest, edges, med_edge, skin_s, skin_f, skin_t)
    return _report(L, frames, n_tris, med_edge, joints, contact, jzone_folds, skin_s, skin_f, sq_s, sq_f,
                   folds, folds_f, crossing, total_cross, at_rest, unity, u_s, objs, arm, deform, per_frame,
                   floors)


FIRM = 0.5                         # skin this close to its bone (x the distance to any bone moving
                                   # otherwise) follows that bone whatever the weights
FLOOR_REGIONS = 8                  # stretched regions whose pose floor is worked out (worst first)


def _geodesic(n, edges, el, src, src_d, rmax, rounds=300):
    """Distance over the surface (along edges) from the source points, up to rmax."""
    d = np.full(n, np.inf)
    d[src] = src_d
    for _ in range(rounds):
        old = d.copy()
        np.minimum.at(d, edges[:, 1], d[edges[:, 0]] + el)
        np.minimum.at(d, edges[:, 0], d[edges[:, 1]] + el)
        d[d > rmax] = np.inf
        if np.array_equal(old, d):
            break
    return d


def _pose_floors(arm, L, rest, edges, med_edge, skin_s, skin_f, skin_t) -> dict:
    """{region: {"floor", "mover"}}: the stretch the pose itself asks of the skin there, whatever
    the weights - so the panel does not advise smoothing weights where no weights can help.

    At the frame where a region stretches most, the bones fall into groups that move as one
    (the head with its ears, the still body...). Skin at most FIRM times as far from its own
    group's bones as from any other group's follows its group whatever the weights. From the
    region's worst face, the nearest such skin of two groups, a and b, are g_a + g_b apart over
    the surface; after the pose they are |a' - b'| apart (seen from b's group). Some skin on
    that way must stretch at least |a' - b'| / (g_a + g_b): a lower bound, not an estimate.
    "mover": the part that turns (the group's top bone), to name in the advice."""
    out: dict = {}
    if not len(L.bones) or not len(edges):
        return out
    todo = [k for k in np.argsort(-skin_s).tolist()
            if skin_s[k] > LIMITS["stretch"][0] and skin_t[k] >= 0 and skin_f[k] >= 0][:FLOOR_REGIONS]
    if not todo:
        return out
    sc = bpy.context.scene
    n = len(rest)
    el = np.linalg.norm(rest[edges[:, 0]] - rest[edges[:, 1]], axis=1)
    span = float(np.linalg.norm(rest.max(axis=0) - rest.min(axis=0))) if n else 1.0
    parent = {b: (arm.data.bones[b].parent.name if arm.data.bones[b].parent else None) for b in L.bones}
    by_frame: dict = {}
    for k in todo:
        by_frame.setdefault(int(skin_f[k]), []).append(k)
    for f, regs in sorted(by_frame.items()):
        sc.frame_set(f)
        mats = skin_matrices(arm, L.bones)
        # bones moving as one: the same skinning matrix (to a tenth of a millimetre over the body)
        group = np.full(len(L.bones), -1)
        reps: list = []
        for j in range(len(L.bones)):
            for gi, r in enumerate(reps):
                dm = np.abs(mats[j, :3, :3] - mats[r, :3, :3]).max() * span + np.abs(mats[j, :3, 3] - mats[r, :3, 3]).max()
                if dm < 1e-4:
                    group[j] = gi
                    break
            else:
                group[j] = len(reps)
                reps.append(j)
        G = len(reps)
        if G < 2:
            continue
        Dg = np.full((n, G), np.inf)
        for j in range(len(L.bones)):
            Dg[:, group[j]] = np.minimum(Dg[:, group[j]], _dist_to_bone(rest, L.H[j], L.T[j]))
        own = np.argmin(Dg, axis=1)
        srt = np.sort(Dg, axis=1)
        firm = (srt[:, 0] <= FIRM * srt[:, 1]) & ~L.free
        for k in regs:
            t = int(skin_t[k])
            vt = L.tris[t]
            xt = L.tri_c[t]
            g = _geodesic(n, edges, el, vt, np.linalg.norm(rest[vt] - xt, axis=1), 0.5 * span)
            near = {}
            for gi in range(G):
                m = firm & (own == gi) & np.isfinite(g)
                if m.any():
                    near[gi] = int(np.flatnonzero(m)[np.argmin(g[m])])
            best, pair = 1.0, None
            gs = sorted(near)
            for i in gs:
                for j in gs:
                    if j <= i:
                        continue
                    a, b = near[i], near[j]
                    rel = np.linalg.inv(mats[reps[j]]) @ mats[reps[i]]
                    pa = rel[:3, :3] @ rest[a] + rel[:3, 3]
                    ratio = float(np.linalg.norm(pa - rest[b]) / max(g[a] + g[b], 1e-12))
                    if ratio > best:
                        best, pair = ratio, (i, j)
            if pair is None:
                continue
            moves = {gi: float(np.linalg.norm(mats[reps[gi], :3, :3] @ xt + mats[reps[gi], :3, 3] - xt)) for gi in pair}
            mg = max(moves, key=moves.get)
            members = [L.bones[j] for j in range(len(L.bones)) if group[j] == mg]
            top = next((b for b in members if parent.get(b) not in members), members[0])
            out[L.reg_names[k]] = {"floor": best, "mover": L.segs[L.seg_of[L.bones.index(top)]].name}
    return out


def _lbs_floor(turn_deg: float) -> float:
    """The thickness linear blending keeps at a joint turned this far (50/50 blend): cos(turn/2)."""
    return math.cos(math.radians(min(abs(turn_deg), 180.0)) / 2.0)


def _over(value: float, warn: float, fail: float, below: bool) -> float:
    """How far past its limit a value is, on one scale for every check: the limit of the grade
    it reached against the value (1 at the limit, 1.5 = half as far again). Findings of
    different checks (a thickness, a stretch, a share of faces) rank by it."""
    if below:
        lim = fail if value < fail else warn
        return lim / max(value, 1e-6)
    lim = fail if value > fail else warn
    return value / lim if lim > 0 else 1.0 + value / max(fail, 1e-12)


def _report(L, frames, n_tris, med_edge, joints, contact, jzone_folds, skin_s, skin_f, sq_s, sq_f, folds,
            folds_f, crossing, total_cross, at_rest, unity, u_s, objs, arm, deform, per_frame,
            floors=None) -> dict:
    floors = floors or {}
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
             "lbs": round(floor, 2), "normal": bool(r["value"] >= floor - LBS_MARGIN),
             "over": round(_over(r["value"], *LIMITS["volume"], below=True), 3)}
        if name in contact:
            c = contact[name]
            e["contact"] = {"value": round(c["value"], 3), "frame": c["frame"], "bend_deg": int(round(c["bend"])),
                            "faces": c["faces"], "folds": jzone_folds.get(name, 0)}
        jr.append(e)
    for name, c in contact.items():
        if name not in joints:
            jr.append({"where": name, "grade": "pass", "value": None, "frame": None, "kind": "joint", "over": 0.0,
                       "contact": {"value": round(c["value"], 3), "frame": c["frame"],
                                   "bend_deg": int(round(c["bend"])), "faces": c["faces"],
                                   "folds": jzone_folds.get(name, 0)}})
    jr.sort(key=lambda e: (-ORDER.index(e["grade"]), -e["over"]))
    worst = next((e for e in jr if e["value"] is not None), None)
    out["checks"]["joints"] = {
        "grade": worst["grade"] if worst else "pass", "value": worst["value"] if worst else 1.0,
        "frame": worst["frame"] if worst else None, "where": worst["where"] if worst else "",
        "part": worst["part"] if worst else None, "bend_deg": worst["bend_deg"] if worst else None,
        "regions": jr}
    # ---- skin: worst stretch, folds and squash per region
    sr = []
    for k, name in enumerate(L.reg_names):
        st = float(skin_s[k])
        fd = int(folds[k])
        sq = float(sq_s[k])
        if st <= 1.0 + 1e-9 and fd == 0 and sq >= 1.0 - 1e-9:
            continue
        gs = _grade(st, *LIMITS["stretch"], below=False)
        gf = _grade(fd / n_tris, *LIMITS["folds"], below=False)
        gq = _grade(sq, *LIMITS["squash"], below=True)
        g = _worse(_worse(gs, gf), gq)
        overs = [(gs, _over(st, *LIMITS["stretch"], below=False)), (gf, _over(fd / n_tris, *LIMITS["folds"], below=False)),
                 (gq, _over(sq, *LIMITS["squash"], below=True))]
        e = {"where": name, "grade": g, "stretch": round(st, 2),
             "frame": int(skin_f[k]) if skin_f[k] >= 0 else None, "stretch_grade": gs, "folds": fd, "folds_grade": gf,
             "squash": round(sq, 2), "squash_grade": gq,
             "over": round(max((o for gg, o in overs if gg == g), default=0.0), 3)}
        if name in floors and gs != "pass" and floors[name]["floor"] >= LIMITS["stretch"][0]:
            e["pose_floor"] = round(floors[name]["floor"], 2)  # what the pose itself asks there
            e["pose_mover"] = floors[name]["mover"]
        if fd:
            e["folds_frame"] = int(folds_f[k])
        if sq_f[k] >= 0:
            e["squash_frame"] = int(sq_f[k])
        sr.append(e)
    sr.sort(key=lambda e: (-ORDER.index(e["grade"]), -e["over"]))
    ws = max(sr, key=lambda e: e["stretch"], default=None)
    wf = max(sr, key=lambda e: e["folds"], default=None)
    wq = min(sr, key=lambda e: e["squash"], default=None)
    out["checks"]["skin"] = {
        "grade": max((e["grade"] for e in sr), key=ORDER.index, default="pass"),
        "stretch": ws["stretch"] if ws else 1.0, "frame": ws["frame"] if ws else None,
        "where": ws["where"] if ws else "", "folds": wf["folds"] if wf else 0,
        "folds_where": wf["where"] if wf and wf["folds"] else "",
        "squash": wq["squash"] if wq else 1.0, "squash_where": wq["where"] if wq and wq["squash"] < 1.0 else "",
        "regions": sr}
    if wf and wf["folds"]:
        out["checks"]["skin"]["folds_frame"] = wf["folds_frame"]
    if wq and wq.get("squash_frame") is not None:
        out["checks"]["skin"]["squash_frame"] = wq["squash_frame"]
    # ---- crossings: contact (information), folds (faults), parts touching (warnings)
    cr = []
    for (kind, where), c in crossing.items():
        share = c["faces"] / n_tris
        if kind == "contact":
            g, ov = "info", 0.0
        elif kind == "fold":
            g, ov = _grade(share, *LIMITS["crossing"], below=False), _over(share, *LIMITS["crossing"], below=False)
        else:
            g, ov = "warn", _over(min(share, LIMITS["crossing"][1]), *LIMITS["crossing"], below=False)
        cr.append({"where": where, "kind": kind, "grade": g, "faces": c["faces"], "frame": c["frame"],
                   "over": round(ov, 3)})
    rank = {"fail": 0, "warn": 1, "info": 2}
    cr.sort(key=lambda e: (rank[e["grade"]], -e["faces"]))
    faults = [e for e in cr if e["kind"] != "contact"]
    cg = max((e["grade"] for e in faults), key=ORDER.index, default="pass")
    wx = faults[0] if faults else None                   # (its value and frame: the worst fault)
    out["checks"]["crossing"] = {
        "grade": cg, "value": wx["faces"] if wx else 0, "frame": wx["frame"] if wx else None,
        "where": wx["where"] if wx else "",
        "all_faces": int(total_cross[0]), "all_frame": total_cross[1], "at_rest": int(at_rest.sum()),
        "contact": sum(e["faces"] for e in cr if e["kind"] == "contact"),
        "folds": sum(e["faces"] for e in cr if e["kind"] == "fold"),
        "touches": sum(e["faces"] for e in cr if e["kind"] == "touch"),
        "hidden_roots": sum(e["faces"] for e in cr if e["kind"] == "hidden"), "regions": cr}
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
                  "limit_crossed": crossed[:5], "measured_on": "full mesh",
                  "over": round(max(shift_edges / UNITY_SHIFT, 1.0 if crossed else 0.0), 3)}
    wg = "fail" if w["unweighted"] else ug
    out["checks"]["weights"] = {"grade": wg, **w}
    out["grade"] = max((x["grade"] for x in out["checks"].values()), key=ORDER.index)
    bad = [x for x in out["checks"].values() if x.get("frame") is not None and x["grade"] != "pass"]
    if w["unity"]["grade"] != "pass" and w["unity"]["frame"] is not None:
        bad.append({"grade": w["unity"]["grade"], "frame": w["unity"]["frame"]})
    worst_check = max(bad, key=lambda x: ORDER.index(x["grade"]), default=None)
    out["worst_frame"] = worst_check["frame"] if worst_check else None
    out["regions"] = by_region(out["checks"])
    top = out["regions"][0]["worst"] if out["regions"] else None
    if top and top.get("frame") is not None and top["grade"] == (worst_check or {}).get("grade"):
        out["worst_frame"] = top["frame"]            # (the first place the panel lists)
    out["per_frame"] = per_frame
    return out


def by_region(checks: dict) -> list:
    """The findings per region (a joint, a segment, two parts touching), worst region first:
    [{"where", "grade", "worst": finding, "contact": finding or None, "findings": [worst first]}].
    A finding is a copy of a region entry of one check, with "check" naming it; contact is
    "info" (expected at a bend, never a fault). Regions where everything passes are left out.
    Within a grade, findings rank by how far past their limit they are ("over"): a joint kept
    at 33 % (limit 50 %) comes before skin stretched 2.3x (limit 2x)."""
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

    def key(f):
        return (-sev.get(f["grade"], 0), -float(f.get("over") or 0.0), _badness(f))
    out = []
    for where, fs in found.items():
        fs.sort(key=key)
        worst = fs[0]
        if sev.get(worst["grade"], 0) == 0:
            continue
        out.append({"where": where, "grade": worst["grade"], "worst": worst,
                    "contact": next((f for f in fs if f["check"] == "contact"), None),
                    "findings": [f for f in fs if f["grade"] != "pass"]})
    out.sort(key=lambda r: key(r["worst"]))
    return out


def _badness(f: dict) -> float:
    """Lower = worse: a tie-break within one check (and for reports from before "over")."""
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
