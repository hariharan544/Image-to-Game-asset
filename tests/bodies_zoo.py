"""A zoo of test bodies whose extra parts are not (only) a tail: wings, fins, a shoulder cannon,
two tails, a trunk, a cape, tentacles, horns, antlers, hair, a sash, a skirt, a weapon in the
hand, a shield on the forearm, extra arms, a second wing pair, spikes on a tail, a naga, a chibi,
a dragon...

The pipeline must not be tuned to the one model it was first tried on ("the tail is for this
model - what if it has wings in another one, or some other non-symmetrical object?"). These
bodies are built like the director's AI meshes (Tripo): simple primitives fused by a voxel
remesh into ONE closed surface (optionally with loose or buried extra shells, and parts that are
their own closed shell such as a held staff or a halo), Z up, facing -Y, feet on the ground,
about 1-2 m tall, T-pose where there are arms.

How a body is made: a base (BASES: humanoid, chibi, creature, naga, quadruped) gives the trunk,
the limbs, a skeleton (bones) and anchors (head, back, rump, shoulders, hands...). Parts (PARTS:
one Kit-level function each, part(k, side=..., **shape)) attach to the anchors, so the same part
fits every base that has the anchor (horns on a humanoid or a dragon). compose(name, base,
parts=[...]) builds any combination; the ZOO generators are named compositions.

AI-like surface (generator options, all off by default; preset="ai" turns on a typical set):
  blend:  smooth-union radius (m) at every junction: the seam between parts is rounded off
          (volume-keeping smoothing of a band around the junction after the remesh)
  noise:  low-frequency displacement (m, a smooth mirror-symmetric warp: lumps, nothing
          perfectly round) plus a small random jitter of the vertices
  tris:   triangulate; with a count, decimate to about that many triangles (irregular, dense)
  colour: "vertex" (a colour attribute) or "texture" (UVs + an image): one flat colour per
          ground-truth part, with a material, so a Step 6 bake can measure colour bleeding
          across junctions (info["colours"])
  seed:   noise seed (everything else is deterministic)

Every generator returns (object, info):
  info["appendages"][name] = {
      "kind":      wing, fin, cannon, pauldron, tail, trunk, cape, tentacle, horn, ear, antler,
                   spike, hair, sash, skirt, arm, weapon, shield, blade, staff, halo
      "side":      "l" (+X), "r" (-X) or "c" (its root on the centre line)
      "symmetry":  one of SYMMETRY; "twin": its mirror partner (pairs only)
      "root":      the root ring's centre MEASURED on the fused mesh (where it leaves what it grows
                   from); "root_design" the designed middle of the root (where its centre line
                   leaves the base). A loose part (own shell) has no ring: root = root_design
      "tip":       the part's vertex farthest along its centre line (MEASURED); "tip_design"
      "root_line": for a long root (fin, cape): points ON the measured root ring nearest the
                   designed ends ("root_line_design"), so they are the visible ends
      "ring":      the measured root ring: centre, radius, major, minor, aspect, shape (round /
                   oval / slot by aspect), ends (the two ring points farthest apart), verts
      "root_shape": the measured ring's shape; "root_shape_design" / "root_size" are the
                   designed intent ("line" and "arc" say what the root is meant to be)
      "contacts":  places where it touches the body or another part AWAY from its root
      "root_on":   owners at the root ring (body, a limb, or another part for a part on a part)
      "parent":    the bone (info["bones"]) a rig hangs it on: head, chest, pelvis, hand_r... or
                   the name of the part it grows from (spikes on a tail -> "tail")
      "thin", "thickness":  a sheet / thin tube (designed), typical thickness in metres
      "rig":       chain, wing, cloth, rigid, limb (an extra arm), prop (own bone), skin (no bone)
      "path":      a centre polyline from root to tip
      "mirror_on_surface", "mirror_on_self", "mirror_on_twin": share of its vertices whose mirror
                   image (x -> -x) lies on the rest of the surface / on itself / on its twin,
                   within max(1.5 voxels, a quarter of the local radius)
      "separate":  True for a part that is its own closed shell (held staff, halo) }
  info["limbs"]: the same for arms and legs (covered by a humanoid / quadruped skeleton).
  info["bones"]: the base's skeleton {name: (head, tail)}; info["joints_hint"]: where the main
  joints belong (pelvis, spine, chest, neck, head, shoulders, elbows, wrists, hands, hips, knees,
  ankles; a quadruped's use its own names: shoulder_fl, hip_bl...).
  info["labels"]: owner names; the per-vertex ground truth (index into labels) is info["truth"]
  and the int point attribute TRUTH_ATTR (per face: FACE_TRUTH_ATTR), so it follows the mesh
  through copies and cuts.

Every generator takes voxel (remesh size), scale (overall size), shells (extra shells: buried
inside the trunk / loose beside the body, alternating), the options above and its own shape
parameters. Thin features never go under 2.2 voxels (they would break apart): info["clamped"]
lists any that were thickened for the chosen voxel.
"""

from __future__ import annotations

import colorsys
import math

import bpy
import numpy as np

TRUTH_ATTR = "zoo_truth"
FACE_TRUTH_ATTR = "zoo_truth_face"
COLOUR_ATTR = "zoo_colour"
SYMMETRY = {
    "pair": "a mirrored twin of the same shape and pose",
    "pair_posed": "a twin of the same shape in another pose (most of it still mirrors onto the twin)",
    "pair_asym": "a twin at the mirrored root but of another shape or size (broken horn, other tail)",
    "one-sided": "no twin: mirroring would copy or delete it",
    "centre": "on the mirror plane, its own mirror image",
    "centre_asym": "its root on the mirror plane, but not its own mirror image (a tail swaying to one side, a cape "
                   "fold on one calf, a side-swept ponytail, a diagonal sash): mirroring changes its shape",
}
RIGS = ("chain", "wing", "cloth", "rigid", "limb", "prop", "skin")
AI_LIKE = {"blend": 0.03, "noise": 0.004, "tris": 0, "colour": "texture"}


# ----------------------------------------------------------------------------- small helpers

def _unit(v) -> np.ndarray:
    v = np.asarray(v, float)
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-12 else v


def _resample(pts, m: int) -> np.ndarray:
    """m points evenly spaced along a polyline."""
    P = np.asarray(pts, float)
    seg = np.linalg.norm(np.diff(P, axis=0), axis=1)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    t = np.linspace(0.0, s[-1], m)
    return np.stack([np.interp(t, s, P[:, i]) for i in range(3)], axis=1)


def _arc_params(pts) -> np.ndarray:
    P = np.asarray(pts, float)
    s = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))])
    return s / max(s[-1], 1e-12)


def _lerp_ctrl(ctrl, t) -> np.ndarray:
    """Values given at evenly spaced control points (0..1), linearly interpolated at t."""
    C = np.asarray(ctrl, float)
    u = np.linspace(0.0, 1.0, len(C))
    if C.ndim == 1:
        return np.interp(t, u, C)
    return np.stack([np.interp(t, u, C[:, i]) for i in range(C.shape[1])], axis=1)


def _spline(pts, radii, per: int = 4) -> tuple:
    """A smooth curve through the control points (Catmull-Rom, `per` points per span) and the
    radii along it: organic parts bend, they do not kink."""
    P = np.asarray(pts, float)
    R = np.asarray(radii, float)
    Q = np.concatenate([[2 * P[0] - P[1]], P, [2 * P[-1] - P[-2]]])
    out, rad = [], []
    for i in range(len(P) - 1):
        p0, p1, p2, p3 = Q[i], Q[i + 1], Q[i + 2], Q[i + 3]
        for t in np.linspace(0, 1, per, endpoint=False):
            out.append(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t
                              + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3))
            rad.append(R[i] + (R[i + 1] - R[i]) * t)
    out.append(P[-1])
    rad.append(R[-1])
    return np.array(out), rad


def _rot(axis: str, a: float) -> np.ndarray:
    c, s = math.cos(a), math.sin(a)
    if axis == "x":
        return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])
    if axis == "y":
        return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def _seg_project(P, path, beyond: float = 0.08) -> tuple:
    """For points P (n, 3): (distance to the polyline, arc length of the nearest point on it).
    The last segment is extended `beyond` metres past the end: a point just beyond the tip gets
    more than the length."""
    A = np.asarray(path, float)
    P = np.asarray(P, float).reshape(-1, 3)
    best_d = np.full(len(P), np.inf)
    best_s = np.zeros(len(P))
    acc = 0.0
    nseg = len(A) - 1
    for j in range(nseg):
        a, d = A[j], A[j + 1] - A[j]
        L2 = float(d @ d)
        if L2 < 1e-18:
            continue
        t = ((P - a) @ d) / L2
        t = np.clip(t, 0.0, 1.0 + beyond / math.sqrt(L2) if j == nseg - 1 else 1.0)
        dist = np.linalg.norm(P - (a + t[:, None] * d), axis=1)
        better = dist < best_d
        best_d[better] = dist[better]
        best_s[better] = acc + t[better] * math.sqrt(L2)
        acc += math.sqrt(L2)
    return best_d, best_s


def _from_root(pts, root, most: int = 16) -> list:
    """The centre line from the root on: the root, then the points beyond it (at most `most`)."""
    P = np.asarray(pts, float)
    s = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))])
    _d, sr = _seg_project(np.asarray(root, float)[None], P, beyond=0.0)
    keep = P[s > sr[0] + 1e-6]
    if len(keep) > most:
        keep = keep[np.unique(np.round(np.linspace(0, len(keep) - 1, most)).astype(int))]
    return [tuple(map(float, root))] + [tuple(map(float, p)) for p in keep]


def _snap_tip(P, path, voxel: float, max_off: float = math.inf):
    """The vertex of P farthest along the centre line (the far end, past the designed tip):
    of those within a voxel of the farthest, the one nearest the line (a blunt or wide end
    gives its middle, not a corner)."""
    if not len(P):
        return None
    d, s = _seg_project(P, path)
    on = d <= max_off                       # (a branch: only the vertices on it)
    if not on.any():
        return None
    s = np.where(on, s, -np.inf)
    cand = np.nonzero(s >= s.max() - voxel)[0]
    return P[cand[np.argmin(d[cand])]]


def _ear_clip(Q) -> list:
    """Triangles of a simple 2D polygon (ear clipping): plates get inner edges, so where a plate
    crosses the body can be found along them (see Kit.junction)."""
    Q = np.asarray(Q, float)
    idx = list(range(len(Q)))
    sgn = 1.0 if 0.5 * np.sum(Q[:, 0] * np.roll(Q[:, 1], -1) - np.roll(Q[:, 0], -1) * Q[:, 1]) > 0 else -1.0
    tris = []
    while len(idx) > 3:
        m = len(idx)
        I = np.array(idx)
        A, B, Cc = Q[np.roll(I, 1)], Q[I], Q[np.roll(I, -1)]
        cross = sgn * ((B[:, 0] - A[:, 0]) * (Cc[:, 1] - B[:, 1]) - (B[:, 1] - A[:, 1]) * (Cc[:, 0] - B[:, 0]))
        ear = None
        for kk in np.argsort(-cross):
            if cross[kk] <= 1e-15:
                break
            a, b, c = A[kk], B[kk], Cc[kk]
            others = np.delete(I, [(kk - 1) % m, kk, (kk + 1) % m])
            P = Q[others]

            def side(p0, p1):
                return sgn * ((p1[0] - p0[0]) * (P[:, 1] - p0[1]) - (p1[1] - p0[1]) * (P[:, 0] - p0[0]))
            if not np.any((side(a, b) > -1e-15) & (side(b, c) > -1e-15) & (side(c, a) > -1e-15)):
                ear = kk
                break
        if ear is None:                               # (degenerate: a fan for the rest)
            tris += [(idx[0], idx[i], idx[i + 1]) for i in range(1, len(idx) - 1)]
            return tris
        tris.append((idx[(ear - 1) % m], idx[ear], idx[(ear + 1) % m]))
        idx.pop(ear)
    tris.append(tuple(idx))
    return tris


def coords(me) -> np.ndarray:
    co = np.empty(len(me.vertices) * 3, np.float32)
    me.vertices.foreach_get("co", co)
    return co.reshape(-1, 3).astype(np.float64)


def edges(me) -> np.ndarray:
    ev = np.empty(len(me.edges) * 2, np.int32)
    me.edges.foreach_get("vertices", ev)
    return ev.reshape(-1, 2).astype(np.int64)


def _faces(me) -> tuple:
    """(loop vertex indices, loop start per face, corners per face)."""
    lv = np.empty(len(me.loops), np.int32)
    me.loops.foreach_get("vertex_index", lv)
    ls = np.empty(len(me.polygons), np.int32)
    me.polygons.foreach_get("loop_start", ls)
    lt = np.empty(len(me.polygons), np.int32)
    me.polygons.foreach_get("loop_total", lt)
    return lv, ls, lt


def _components(n: int, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Connected component label per vertex (union-find over the given edges)."""
    parent = np.arange(n)

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for i, j in zip(a.tolist(), b.tolist()):
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[max(ri, rj)] = min(ri, rj)
    return np.array([find(i) for i in range(n)])


def shells(me) -> int:
    """Number of separate pieces (connected surfaces) of the mesh."""
    ev = edges(me)
    lab = _components(len(me.vertices), ev[:, 0], ev[:, 1])
    return len(np.unique(lab))


def open_edges(me) -> tuple:
    """(boundary edges, edges with more than two faces): (0, 0) for a closed surface."""
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(me)
    b = sum(1 for e in bm.edges if e.is_boundary)
    nm = sum(1 for e in bm.edges if len(e.link_faces) > 2)
    bm.free()
    return b, nm


def truth(me) -> np.ndarray | None:
    """The ground-truth owner index per vertex (see info["labels"]), or None."""
    a = me.attributes.get(TRUTH_ATTR)
    if a is None or a.domain != "POINT":
        return None
    v = np.empty(len(me.vertices), np.int32)
    a.data.foreach_get("value", v)
    return v


def part_mask(me, info: dict, name: str) -> np.ndarray:
    """Vertices whose ground truth is the named part (appendage, limb, "body", shell)."""
    lab = truth(me)
    if lab is None:
        lab = info["truth"]
    return lab == info["labels"].index(name)


def info_json(info: dict) -> dict:
    """The info without numpy arrays (for json.dump)."""
    def clean(x):
        if isinstance(x, dict):
            return {k: clean(v) for k, v in x.items()
                    if not (k in ("truth", "face_truth") and isinstance(v, np.ndarray))}
        if isinstance(x, (list, tuple)):
            return [clean(v) for v in x]
        if isinstance(x, np.ndarray):
            return clean(x.tolist())
        if isinstance(x, (np.floating,)):
            return float(x)
        if isinstance(x, (np.integer,)):
            return int(x)
        if isinstance(x, (np.bool_,)):
            return bool(x)
        return x
    return clean(info)


def _kdtree(co):
    from mathutils.kdtree import KDTree
    kd = KDTree(len(co))
    for i, p in enumerate(co):
        kd.insert(p, i)
    kd.balance()
    return kd


# ----------------------------------------------------------------------------- the kit

class Kit:
    """Primitives collected per owner ("body", "arm_l", "wing_l"...), fused at the end by a
    voxel remesh. Coordinates are design units (metres at scale 1). The base sets the anchors
    the parts attach to (self.anchor), the trunk's ellipsoids (self.ells: surface queries) and
    the skeleton (self.bones)."""

    def __init__(self, name: str, kind: str, voxel: float, scale: float = 1.0, opts: dict | None = None):
        self.name, self.kind = name, kind
        self.voxel, self.scale = float(voxel), float(scale)
        self.tmin = 2.2 * self.voxel / self.scale        # thinnest feature that survives the remesh
        self.geo: dict = {}                              # owner -> ([verts], [faces])
        self.fprim: dict = {}                            # owner -> primitive id per face
        self.nprim = 0
        self.prims: dict = {}                            # owner -> analytic primitives (inside tests)
        self.loose: list = []                            # owners kept as their own closed shell
        self.app: dict = {}                              # appendage name -> design info
        self.limbs: dict = {}
        self.clamped: list = []
        self.core = (0.0, 0.0, 1.2)                      # deep inside the trunk (buried shells)
        self.beside = (0.32, -0.04, 0.85)                # empty space next to the body (loose shells)
        self.joints: dict = {}                           # where the skeleton's main joints belong
        self.bones: dict = {}                            # bone -> (head, tail): what parts hang on
        self.anchor: dict = {}
        self.ells: list = []                             # the trunk's ellipsoids [(centre, radii)]
        self.base = ""
        self.notes = ""
        self.opts = {"blend": 0.0, "noise": 0.0, "tris": 0, "colour": None, "seed": 0}
        self.opts.update({k: v for k, v in (opts or {}).items() if v is not None})

    # -- primitives
    def _add(self, owner: str, V, F) -> None:
        gv, gf = self.geo.setdefault(owner, ([], []))
        off = len(gv)
        gv.extend(tuple(map(float, v)) for v in V)
        gf.extend([off + int(i) for i in f] for f in F)
        self.fprim.setdefault(owner, []).extend([self.nprim] * len(F))     # which primitive each face is of
        self.nprim += 1

    def _add_bm(self, owner: str, bm) -> None:
        self._add(owner, [v.co[:] for v in bm.verts], [[v.index for v in f.verts] for f in bm.faces])

    def _thin(self, t, what: str):
        t = np.asarray(t, float)
        if (t < self.tmin - 1e-12).any():
            self.clamped.append(what)
        return np.maximum(t, self.tmin)

    def ball(self, owner, c, r, s=(1, 1, 1), rot=None, seg: int = 24) -> None:
        """An ellipsoid: centre c, radius r times the axis scales s, optional rotation (3x3)."""
        import bmesh
        from mathutils import Matrix
        bm = bmesh.new()
        sx, sy, sz = (max(r * x, self.tmin / 2) for x in s)
        m = Matrix.Translation(c)
        if rot is not None:
            m = m @ Matrix(np.asarray(rot, float).tolist()).to_4x4()
        m = m @ Matrix.Diagonal((sx, sy, sz, 1))
        bmesh.ops.create_uvsphere(bm, u_segments=seg, v_segments=max(8, seg * 2 // 3), radius=1.0, matrix=m)
        self._add_bm(owner, bm)
        bm.free()
        self.prims.setdefault(owner, []).append(("ell", np.asarray(c, float), np.array([sx, sy, sz]),
                                                 None if rot is None else np.asarray(rot, float)))

    def tube(self, owner, a, b, r1, r2=None, seg: int = 16) -> None:
        """A capped cone from a (radius r1) to b (radius r2)."""
        import bmesh
        from mathutils import Matrix, Vector
        a, b = Vector(a), Vector(b)
        d = b - a
        if d.length < 1e-9:
            return
        r2 = r1 if r2 is None else r2
        r1, r2 = max(r1, self.tmin / 2), max(r2, self.tmin / 2)     # (a tapering tip: silently)
        bm = bmesh.new()
        m = Matrix.Translation((a + b) / 2) @ d.to_track_quat("Z", "Y").to_matrix().to_4x4()
        bmesh.ops.create_cone(bm, cap_ends=True, segments=seg, radius1=r1, radius2=r2, depth=d.length, matrix=m)
        self._add_bm(owner, bm)
        bm.free()
        self.prims.setdefault(owner, []).append(("cap", np.array(a[:]), np.array(b[:]), r1, r2))

    def path(self, owner, pts, radii, seg: int = 16, end_ball: bool = True, smooth: bool = False):
        """Tubes along a polyline with a ball at every joint (a bent tube); smooth: along a
        spline through the points instead. Returns the centre line it followed."""
        if smooth and len(pts) > 2:
            pts, radii = _spline(pts, radii)
        pts = [tuple(map(float, p)) for p in pts]
        for i, (a, b) in enumerate(zip(pts, pts[1:])):
            self.tube(owner, a, b, radii[i], radii[i + 1], seg)
            if i + 2 < len(pts) or end_ball:
                self.ball(owner, b, max(radii[i + 1], self.tmin / 2), seg=seg)
        return np.array(pts)

    def plate(self, owner, outline, thick, origin, u, v) -> None:
        """A flat solid: a 2D outline (in the plane origin + x*u + y*v) given a thickness
        (one value, or one per outline point: a tapered wedge)."""
        o, u, v = np.asarray(origin, float), _unit(u), _unit(v)
        nrm = _unit(np.cross(u, v))
        Q0 = np.asarray(outline, float)
        t0 = np.broadcast_to(self._thin(thick, f"{owner} plate"), (len(Q0),))
        # no outline edge longer than ~1.5 cm (the inner triangles then sample where it crosses)
        step = 0.015 / self.scale
        Q, t = [], []
        for i in range(len(Q0)):
            a, b = Q0[i], Q0[(i + 1) % len(Q0)]
            m = max(1, int(math.ceil(np.linalg.norm(b - a) / step)))
            for j in range(m):
                Q.append(a + (b - a) * j / m)
                t.append(t0[i] + (t0[(i + 1) % len(Q0)] - t0[i]) * j / m)
        Q, t = np.array(Q), np.array(t)
        n = len(Q)
        P = o + Q[:, :1] * u + Q[:, 1:2] * v
        top = P + nrm * (t[:, None] / 2)
        bot = P - nrm * (t[:, None] / 2)
        V = np.concatenate([top, bot])
        tri = _ear_clip(Q)
        F = [list(t) for t in tri] + [[n + t[2], n + t[1], n + t[0]] for t in tri]
        F += [[i, n + i, n + (i + 1) % n, (i + 1) % n] for i in range(n)]
        self._add(owner, V, F)

    def sheet(self, owner, P, t, closed: bool = False) -> None:
        """A curved solid sheet: grid points P (m, c, 3) on its middle surface, thickness t (m, c).
        closed: the columns wrap round (a tube of cloth: a skirt, a sash round the torso)."""
        P = np.asarray(P, float)
        m, c = P.shape[:2]
        t = self._thin(np.broadcast_to(np.asarray(t, float), (m, c)), f"{owner} sheet")
        di = np.gradient(P, axis=0)
        if closed:
            dk = (np.roll(P, -1, axis=1) - np.roll(P, 1, axis=1)) / 2
        else:
            dk = np.gradient(P, axis=1)
        N = np.cross(di, dk)
        N /= np.maximum(np.linalg.norm(N, axis=2, keepdims=True), 1e-12)
        top = (P + N * (t[..., None] / 2)).reshape(-1, 3)
        bot = (P - N * (t[..., None] / 2)).reshape(-1, 3)
        V = np.concatenate([top, bot])
        o = m * c

        def T(i, k):
            return i * c + (k % c)
        F = []
        cols = c if closed else c - 1
        for i in range(m - 1):
            for k in range(cols):
                F.append([T(i, k), T(i, k + 1), T(i + 1, k + 1), T(i + 1, k)])
                F.append([o + T(i, k), o + T(i + 1, k), o + T(i + 1, k + 1), o + T(i, k + 1)])
        if not closed:
            for i in range(m - 1):
                F.append([T(i, 0), T(i + 1, 0), o + T(i + 1, 0), o + T(i, 0)])
                F.append([T(i + 1, c - 1), T(i, c - 1), o + T(i, c - 1), o + T(i + 1, c - 1)])
        for k in range(cols):
            F.append([T(0, k + 1), T(0, k), o + T(0, k), o + T(0, k + 1)])
            F.append([T(m - 1, k), T(m - 1, k + 1), o + T(m - 1, k + 1), o + T(m - 1, k)])
        self._add(owner, V, F)

    # -- the base's geometry, for placing parts
    def surface(self, axis: int, sign: float, a: float, b: float, normal: bool = False):
        """The trunk's outermost surface coordinate along `axis` (sign +1 / -1) at the other two
        coordinates (a, b), in axis order (the union of the trunk ellipsoids): the humanoid's
        back y = surface(1, +1, x, z); the quadruped's top z = surface(2, +1, x, y). With normal:
        (coordinate, outward normal). nan where no ellipsoid covers (a, b)."""
        o = [i for i in range(3) if i != axis]
        best, nrm = -math.inf, None
        for c, r in self.ells:
            q = 1 - ((a - c[o[0]]) / r[o[0]]) ** 2 - ((b - c[o[1]]) / r[o[1]]) ** 2
            if q >= 0:
                v = c[axis] * sign + r[axis] * math.sqrt(q)
                if v > best:
                    best = v
                    p = np.zeros(3)
                    p[o[0]], p[o[1]], p[axis] = a, b, v * sign
                    nrm = _unit((p - np.asarray(c)) / np.asarray(r, float) ** 2)
        val = best * sign if best > -math.inf else math.nan
        return (val, nrm) if normal else val

    def back_point(self, x: float, f: float) -> tuple:
        """(point, outward normal) on the trunk's back at side offset x, fraction f along it
        (0 = low back / rump end, 1 = shoulders / withers)."""
        bk = self.anchor["back"]
        t = bk["t"][0] + f * (bk["t"][1] - bk["t"][0])
        p = np.zeros(3)
        p[0] = x
        p[bk["along_axis"]] = t * bk["along_sign"]
        ni = bk["axis"]
        o = [i for i in range(3) if i != ni]
        p[ni], n = self.surface(ni, 1.0, p[o[0]], p[o[1]], normal=True)
        return p, n

    def inside_many(self, P, owners=None) -> np.ndarray:
        """Which points are inside the given owners' primitives (default: body and limbs)."""
        P = np.asarray(P, float).reshape(-1, 3)
        owners = owners if owners is not None else ["body"] + list(self.limbs)
        out = np.zeros(len(P), bool)
        for ow in owners:
            for pr in self.prims.get(ow, []):
                if pr[0] == "ell":
                    _k, c, r, R = pr
                    v = P - c
                    if R is not None:
                        v = v @ R
                    out |= np.sum((v / r) ** 2, axis=1) <= 1.0
                else:
                    _k, a, b, r1, r2 = pr
                    d = b - a
                    t = np.clip(((P - a) @ d) / max(float(d @ d), 1e-18), 0.0, 1.0)
                    out |= np.linalg.norm(P - (a + t[:, None] * d), axis=1) <= r1 + t * (r2 - r1)
        return out

    def inside(self, p, owners=None) -> bool:
        return bool(self.inside_many([p], owners)[0])

    def _bisect(self, lo, hi, owners, n: int = 14) -> np.ndarray:
        """Points between lo (inside) and hi (outside) on the owners' surface."""
        lo, hi = np.array(lo, float).reshape(-1, 3), np.array(hi, float).reshape(-1, 3)
        for _ in range(n):
            m = (lo + hi) / 2
            im = self.inside_many(m, owners)
            lo = np.where(im[:, None], m, lo)
            hi = np.where(im[:, None], hi, m)
        return (lo + hi) / 2

    def exit_point(self, path, owners=None) -> np.ndarray:
        """Where a centre line first leaves the owners' primitives (default: body and limbs)."""
        P = _resample(path, 240)
        ins = self.inside_many(P, owners)
        if not ins[0]:
            return P[0]
        out = np.nonzero(~ins)[0]
        if not len(out):
            return P[-1]
        i = int(out[0])
        return self._bisect(P[i - 1], P[i], owners)[0]

    def junction(self, owner: str, base=None, hint=None):
        """The designed middle of a part's root: where the part's primitive surface crosses the
        base's (default: body and limbs). The crossings are joined into curves along the part's
        faces (and curves of its primitives that touch are one root); the curve nearest `hint`
        is the root, any other is a contact away from it. None if it never crosses."""
        V = np.asarray(self.geo[owner][0], float)
        faces = self.geo[owner][1]
        eid: dict = {}
        fedges = []
        for f in faces:
            ids = []
            for a, b in zip(f, list(f[1:]) + [f[0]]):
                key = (min(a, b), max(a, b))
                ids.append(eid.setdefault(key, len(eid)))
            fedges.append(ids)
        E = np.array(list(eid), np.int64)
        ins = self.inside_many(V, base)
        crossing = ins[E[:, 0]] != ins[E[:, 1]]
        cr = np.nonzero(crossing)[0]
        if not len(cr):
            return None
        A, B = V[E[cr, 0]], V[E[cr, 1]]
        ia = ins[E[cr, 0]][:, None]
        X = self._bisect(np.where(ia, A, B), np.where(ia, B, A), base)
        pos = np.full(len(E), -1)
        pos[cr] = np.arange(len(cr))
        a_, b_ = [], []
        for ids in fedges:                         # crossings on one face: the same curve
            c = [pos[i] for i in ids if pos[i] >= 0]
            a_ += c[:-1]
            b_ += c[1:]
        fa, fb = np.array(a_, np.int64), np.array(b_, np.int64)
        kd = _kdtree(X)                            # curves of primitives that touch: one root
        near = max(3.0 * self.voxel / self.scale, 0.05)       # (both faces of a sheet, a tube on it)
        for i, p in enumerate(X):
            for _c, j, _d in kd.find_range(p, near):
                if j > i:
                    a_.append(i)
                    b_.append(j)
        lab = _components(len(X), np.array(a_, np.int64), np.array(b_, np.int64))
        groups = [np.nonzero(lab == g)[0] for g in np.unique(lab)]
        if hint is not None:
            h = np.asarray(hint, float)
            g = min(groups, key=lambda g: float(np.min(np.linalg.norm(X[g] - h, axis=1))))
        else:
            g = max(groups, key=len)
        # the centre of the root curves by length (crossings bunch where many edges meet; each
        # stretch of the root counts by its length, like the vertices of the fused mesh's ring)
        w = np.zeros(len(X))
        L = np.linalg.norm(X[fa] - X[fb], axis=1) / 2
        np.add.at(w, fa, L)
        np.add.at(w, fb, L)
        wg = w[g]
        return (X[g] * wg[:, None]).sum(axis=0) / wg.sum() if wg.sum() > 1e-12 else X[g].mean(axis=0)

    def root_of(self, owner: str, path, base=None, hint=None) -> np.ndarray:
        """junction() near the start of the centre line, or where the line leaves the base."""
        j = self.junction(owner, base, hint if hint is not None else path[0])
        return j if j is not None else self.exit_point(path, base)

    def ray_out(self, c, d, owners, far: float = 0.8) -> float:
        """Distance from c along d to where the owners' primitives end (outermost crossing)."""
        c, d = np.asarray(c, float), _unit(d)
        steps = np.linspace(far, 0.0, 161)
        ins = self.inside_many(c + steps[:, None] * d, owners)
        if not ins.any():
            return 0.0
        i = int(np.argmax(ins))
        if i == 0:
            return far
        p = self._bisect(c + steps[i] * d, c + steps[i - 1] * d, owners)[0]
        return float((p - c) @ d)

    # -- what the parts are
    def appendage(self, name, kind, side, root, tip, root_shape, root_size, thin, thickness, rig, path=None,
                  symmetry=None, twin=None, group=None, shape=None, parent=None, **extra) -> None:
        """Register a part. symmetry None: worked out from the parts on the other side (same
        group: a twin; same shape: "pair", else "pair_asym"; none: "one-sided")."""
        assert symmetry is None or symmetry in SYMMETRY, symmetry
        assert rig in RIGS, rig
        self.app[name] = {"kind": kind, "side": side, "symmetry": symmetry, "twin": twin, "group": group or kind,
                          "shape_key": repr(shape), "root_design": tuple(map(float, root)),
                          "tip_design": tuple(map(float, tip)), "root_shape_design": root_shape,
                          "root_size": root_size, "thin": bool(thin), "thickness": float(thickness), "rig": rig,
                          "parent": parent,
                          "path": [tuple(map(float, p)) for p in (path if path is not None else (root, tip))],
                          **extra}

    def limb(self, name, kind, side, tip, path, parent=None) -> None:
        tw = {"l": "r", "r": "l"}
        twin = name[:-1] + tw[name[-1]]
        root = self.root_of(name, path, ["body"])
        self.limbs[name] = {"kind": kind, "side": side, "symmetry": "pair", "twin": twin,
                            "root_design": tuple(map(float, root)), "tip_design": tuple(map(float, tip)),
                            "path": [tuple(map(float, p)) for p in path], "parent": parent, "thickness": 0.0}

    def _resolve_symmetry(self) -> None:
        for name, e in self.app.items():
            if e["symmetry"] is not None:
                continue
            if e["side"] == "c":
                e["symmetry"] = "centre"
                continue
            other = {"l": "r", "r": "l"}[e["side"]]
            cand = [n for n, f in self.app.items() if n != name and f["group"] == e["group"] and f["side"] == other]
            if not cand:
                e["symmetry"], e["twin"] = "one-sided", None
                continue
            t = self.app[cand[0]]
            e["twin"] = cand[0]
            same = t["shape_key"] == e["shape_key"]
            posed = bool(e.get("posed") or t.get("posed"))
            e["symmetry"] = "pair" if same and not posed else "pair_posed" if same else "pair_asym"

    # -- fuse
    def _remesh(self, owners: list, name: str):
        s = self.scale
        allV, allF = [], []
        for o in owners:
            V, F = self.geo[o]
            off = len(allV)
            allV += V
            allF += [[i + off for i in f] for f in F]
        src = bpy.data.meshes.new(name + "_src")
        src.from_pydata((np.asarray(allV) * s).tolist(), [], allF)
        src.update()
        ob = bpy.data.objects.new(name + "_tmp", src)
        bpy.context.scene.collection.objects.link(ob)
        mod = ob.modifiers.new("zoo_voxel", "REMESH")
        mod.mode, mod.voxel_size = "VOXEL", self.voxel
        dg = bpy.context.evaluated_depsgraph_get()
        dg.update()
        me = bpy.data.meshes.new_from_object(ob.evaluated_get(dg))
        bpy.data.objects.remove(ob)
        bpy.data.meshes.remove(src)
        return me

    def _label(self, co, owners: list) -> tuple:
        """Ground truth: the owner whose primitives' surface is nearest each vertex, and which
        primitive (ball, tube, plate...) of it that is."""
        from mathutils.bvhtree import BVHTree
        s = self.scale
        dist = np.full((len(owners), len(co)), np.inf)
        prim = np.full((len(owners), len(co)), -1, np.int64)
        pad = 3 * self.voxel
        for j, o in enumerate(owners):
            Vo = np.asarray(self.geo[o][0]) * s
            tree = BVHTree.FromPolygons(Vo.tolist(), self.geo[o][1])
            fp = self.fprim[o]
            lo, hi = Vo.min(axis=0) - pad, Vo.max(axis=0) + pad
            sel = np.nonzero(np.all((co >= lo) & (co <= hi), axis=1))[0]
            fn = tree.find_nearest
            dj, pj = dist[j], prim[j]
            for i in sel.tolist():
                h = fn(co[i])
                if h[0] is not None:
                    dj[i] = h[3]
                    pj[i] = fp[h[2]]
        lab = np.argmin(dist, axis=0)
        return lab.astype(np.int32), prim[lab, np.arange(len(co))]

    def _warp_fn(self):
        """The low-frequency displacement (None when noise is off): a smooth vector field,
        mirror-symmetric in x (AI meshes are nearly symmetric), so thin sheets bend but keep
        their thickness. Works on world coordinates before grounding."""
        A = float(self.opts.get("noise") or 0.0)
        if A <= 0:
            return None
        from mathutils import Vector, noise
        seed = int(self.opts.get("seed", 0))
        f1, f2 = 1 / 0.22, 1 / 0.07
        o1 = np.array([11.3, 5.1, 7.7]) + 3.1 * seed
        o2 = np.array([3.7, 1.9, 9.2]) + 1.7 * seed

        def warp(P):
            P = np.asarray(P, float).reshape(-1, 3)
            out = np.empty_like(P)
            nv = noise.noise_vector
            for i, (x, y, z) in enumerate(P.tolist()):
                ax = abs(x)
                v1 = nv(Vector((ax * f1 + o1[0], y * f1 + o1[1], z * f1 + o1[2])))
                v2 = nv(Vector((ax * f2 + o2[0], y * f2 + o2[1], z * f2 + o2[2])))
                out[i] = (A * v1[0] + 0.35 * A * v2[0], A * v1[1] + 0.35 * A * v2[1],
                          A * v1[2] + 0.35 * A * v2[2])
                out[i, 0] *= math.tanh(x / 0.02)          # odd in x: the warp keeps the mirror symmetry
            return out
        return warp

    def build(self, shells: int = 0, params: dict | None = None):
        """Voxel-remesh everything into one closed surface (loose owners each into their own),
        label every vertex with the owner it came from, apply the AI-like options, put it on the
        ground, measure the roots. Returns (object, info)."""
        self._resolve_symmetry()
        s, o = self.scale, self.opts
        fused = [ow for ow in self.geo if ow not in self.loose]
        owners = fused + [ow for ow in self.loose if ow in self.geo]
        me = self._remesh(fused, self.name)
        lab, prim = self._label(coords(me), fused)
        if len(owners) > len(fused):
            parts = [(me, lab)]
            prims = [prim]
            for j, ow in enumerate(owners[len(fused):]):
                m2 = self._remesh([ow], f"{self.name}_{ow}")
                parts.append((m2, np.full(len(m2.vertices), len(fused) + j, np.int32)))
                prims.append(self._label(coords(m2), [ow])[1])
            me, lab = _join(parts, self.name)
            prim = np.concatenate(prims)
        labels = list(owners)
        co = coords(me)
        ev = edges(me)
        if float(o.get("blend") or 0.0) > 0:
            co = _blend(co, ev, prim, _faces(me), float(o["blend"]), self.voxel)
        warp = self._warp_fn()
        if warp is not None:
            co = co + warp(co)
            co = _jitter(co, me, 0.15 * self.voxel, int(o.get("seed", 0)))
        me.vertices.foreach_set("co", co.astype(np.float32).ravel())
        me.update()

        def W0(p):                                  # design point -> world before grounding
            p = np.asarray(p, float) * s
            return p + (warp(p)[0] if warp is not None else 0.0)

        # extra shells, like AI meshes have: buried inside the trunk / loose beside the body
        shell_info = []
        if shells:
            import bmesh
            from mathutils import Matrix
            bm = bmesh.new()
            bm.from_mesh(me)
            for i in range(shells):
                buried = i % 2 == 0
                k = i // 2
                if buried:
                    c = np.asarray(self.core, float) + [0.0, 0.0, 0.05 * k]
                    r = 0.035
                else:
                    c = np.asarray(self.beside, float) + [0.0, 0.0, 0.08 * k]
                    r = 0.02
                before = len(bm.verts)
                bmesh.ops.create_icosphere(bm, subdivisions=2, radius=r * s,
                                           matrix=Matrix.Translation(tuple(W0(c))))
                name = f"shell_{'buried' if buried else 'loose'}_{k + 1}"
                labels.append(name)
                shell_info.append({"name": name, "buried": buried, "centre": W0(c), "radius": r * s,
                                   "verts": len(bm.verts) - before})
            bm.to_mesh(me)
            bm.free()
            me.update()
            extra = []
            for j, sh in enumerate(shell_info):
                extra += [len(owners) + j] * sh["verts"]
            lab = np.concatenate([lab, np.asarray(extra, np.int32)])
        assert len(lab) == len(me.vertices)
        if o.get("tris"):
            me, lab = _triangulate(me, lab, int(o["tris"]) if not isinstance(o["tris"], bool) else 0)
        co = coords(me)
        dz = -float(co[:, 2].min())
        co[:, 2] += dz
        me.vertices.foreach_set("co", co.astype(np.float32).ravel())
        me.update()
        for sh in shell_info:
            sh["centre"] = tuple(map(float, np.asarray(sh["centre"]) + [0, 0, dz]))

        def W(p):                                   # design point -> world (scaled, warped, on the ground)
            q = W0(p)
            return (float(q[0]), float(q[1]), float(q[2] + dz))

        ob = bpy.data.objects.new(self.name, me)
        bpy.context.scene.collection.objects.link(ob)
        me.name = self.name
        a = me.attributes.new(TRUTH_ATTR, "INT", "POINT")
        a.data.foreach_set("value", lab)
        lv, ls, lt = _faces(me)
        flab = _face_labels(lab, lv, ls, lt)
        fa = me.attributes.new(FACE_TRUTH_ATTR, "INT", "FACE")
        fa.data.foreach_set("value", flab)
        colours = None
        if o.get("colour"):
            colours = _palette(labels)
            _colourize(me, flab, colours, labels, str(o["colour"]), self.name)

        # ---- measure on the final mesh
        co = coords(me)
        ev = edges(me)
        from mathutils.bvhtree import BVHTree
        tree = BVHTree.FromPolygons(co.tolist(), [lv[ls[i]:ls[i] + lt[i]].tolist() for i in range(len(ls))])
        app = {}
        for name, d in self.app.items():
            e = {k: v for k, v in d.items() if k not in ("group", "shape_key")}
            for key in ("root_design", "tip_design"):
                e[key] = W(d[key])
            e["path"] = [W(p) for p in d["path"]]
            e["root_size"] = tuple(float(x) * s for x in d["root_size"])
            e["thickness"] = d["thickness"] * s
            for key in ("contact_design", "root_line_design"):
                if key in e:
                    e[key] = [W(p) for p in e[key]]
            if "branches" in e:
                e["branches"] = [{"root": W(b["root"]), "tip_design": W(b["tip"]), "radius": b["radius"]}
                                 for b in e["branches"]]
            app[name] = e
        limbs = {}
        for name, d in self.limbs.items():
            e = dict(d)
            e["root_design"], e["tip_design"] = W(d["root_design"]), W(d["tip_design"])
            e["path"] = [W(p) for p in d["path"]]
            limbs[name] = e
        bones = {b: (W(h), W(t)) for b, (h, t) in self.bones.items()}
        extras = set(app)
        for name, e in list(app.items()) + list(limbs.items()):
            k = labels.index(name)
            m = lab == k
            e["verts"] = int(m.sum())
            P = co[m]
            if name in self.loose:
                e["ring"], e["contacts"], e["root_on"], rv = None, [], [], None
                e["separate"] = True
            else:
                e["ring"], e["contacts"], e["root_on"], rv = _rings(co, ev, lab, labels, k,
                                                                    np.asarray(e["root_design"]), extras)
            e["root"] = e["ring"]["centre"] if e["ring"] else e["root_design"]
            e["root_shape"] = e["ring"]["shape"] if e["ring"] else e.get("root_shape_design")
            tip = _snap_tip(P, e["path"], self.voxel)
            e["tip"] = tuple(map(float, tip)) if tip is not None else e["tip_design"]
            if "root_line_design" in e and rv is not None and len(rv):
                e["root_line"] = [tuple(map(float, co[rv[np.argmin(np.linalg.norm(co[rv] - np.asarray(p), axis=1))]]))
                                  for p in e["root_line_design"]]
            if "branches" in e:
                for b in e["branches"]:
                    near = P[np.linalg.norm(P - np.asarray(b["root"]), axis=1)
                             < 1.3 * np.linalg.norm(np.asarray(b["tip_design"]) - b["root"])]
                    t = _snap_tip(near, [b["root"], b["tip_design"]], self.voxel,
                                  max_off=b["radius"] + 1.5 * self.voxel)
                    b["tip"] = tuple(map(float, t)) if t is not None else b["tip_design"]
            if not e.get("parent"):
                e["parent"] = _parent_of(e, bones, extras)
            e["mirror_on_surface"], e["mirror_on_self"], e["mirror_on_twin"] = _mirror_share(
                tree, flab, co, lab, labels, k, e, self.voxel)
        H = float(co[:, 2].max() - co[:, 2].min())
        info = {"name": self.name, "kind": self.kind, "base": self.base, "height": H, "voxel": self.voxel,
                "scale": s, "front": "-Y", "up": "+Z", "verts": len(co), "faces": len(me.polygons),
                "triangles_only": bool((lt == 3).all()), "labels": labels, "truth": lab, "face_truth": flab,
                "appendages": app, "limbs": limbs, "shells": shell_info, "separate": [x for x in self.loose],
                "bones": bones, "joints_hint": {j: W(p) for j, p in self.joints.items()},
                "clamped": sorted(set(self.clamped)), "params": dict(params or {}), "notes": self.notes,
                "options": {k: o.get(k) for k in ("blend", "noise", "tris", "colour", "seed")},
                "colours": colours}
        ob["zoo_body"] = self.name
        return ob, info


def _join(parts: list, name: str) -> tuple:
    """One mesh from several (each its own shell), labels concatenated."""
    V, F, labs = [], [], []
    for me, lab in parts:
        off = len(V)
        V += coords(me).tolist()
        lv, ls, lt = _faces(me)
        F += [(lv[ls[i]:ls[i] + lt[i]] + off).tolist() for i in range(len(ls))]
        labs.append(lab)
        bpy.data.meshes.remove(me)
    out = bpy.data.meshes.new(name)
    out.from_pydata(V, [], F)
    out.update()
    return out, np.concatenate(labs).astype(np.int32)


def _neighbour_mean(co, ev, deg):
    S = np.stack([np.bincount(ev[:, 0], weights=co[ev[:, 1], i], minlength=len(co))
                  + np.bincount(ev[:, 1], weights=co[ev[:, 0], i], minlength=len(co)) for i in range(3)], axis=1)
    return S / np.maximum(deg, 1)[:, None]


def _vertex_normals(co, faces) -> np.ndarray:
    lv, ls, lt = faces
    n = np.zeros_like(co)
    for k in np.unique(lt):
        f = np.nonzero(lt == k)[0]
        C = [co[lv[ls[f] + j]] for j in range(k)]
        fn = np.cross(C[2] - C[0], C[-1] - C[1]) if k >= 4 else np.cross(C[1] - C[0], C[2] - C[0])
        for j in range(k):
            np.add.at(n, lv[ls[f] + j], fn)
    return n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)


def _blend(co, ev, prim, faces, radius: float, voxel: float) -> np.ndarray:
    """Round off every junction like a smooth union: near a seam between two primitives (two
    parts, or a ridge on a dome) the surface only ever moves OUT, along its normal, by the
    Laplacian's outward part: concave creases fill into a fillet about `radius` wide, convex
    shapes (a thin root, a rim) never shrink. Then a light relaxation along the surface."""
    cross = prim[ev[:, 0]] != prim[ev[:, 1]]
    jv = np.unique(ev[cross].ravel())
    if not len(jv):
        return co
    kd = _kdtree(co[jv])
    d = np.array([kd.find(p)[2] for p in co])
    w = np.clip(1.0 - d / (1.5 * radius), 0.0, 1.0)
    w = w * w * (3 - 2 * w)
    act = np.nonzero(w > 0)[0]
    if not len(act):
        return co
    deg = np.bincount(ev.ravel(), minlength=len(co)).astype(float)
    co = co.copy()
    wa = w[act][:, None]
    n = _vertex_normals(co, faces)
    for it in range(int(round(3.0 * (radius / voxel) ** 2))):
        if it % 3 == 0:
            n = _vertex_normals(co, faces)
        L = _neighbour_mean(co, ev, deg)[act] - co[act]
        out = np.maximum((L * n[act]).sum(axis=1, keepdims=True), 0.0)
        co[act] += 0.5 * wa * out * n[act]
    for _ in range(4):
        n = _vertex_normals(co, faces)
        L = _neighbour_mean(co, ev, deg)[act] - co[act]
        co[act] += 0.5 * wa * (L - (L * n[act]).sum(axis=1, keepdims=True) * n[act])
    return co


def _jitter(co, me, amp: float, seed: int) -> np.ndarray:
    """A small random move of every vertex along the surface (the grid stops being regular)."""
    me.vertices.foreach_set("co", co.astype(np.float32).ravel())
    me.update()
    n = np.empty(len(me.vertices) * 3, np.float32)
    me.vertex_normals.foreach_get("vector", n)
    n = n.reshape(-1, 3).astype(np.float64)
    r = np.random.default_rng(1000 + seed).normal(0.0, amp, (len(co), 3))
    r -= (r * n).sum(axis=1, keepdims=True) * n
    return co + r


def _triangulate(me, lab, target: int) -> tuple:
    """Triangles only; with a target, decimated (collapse, X-symmetric) to about that many
    triangles. The ground truth is carried over from the nearest vertex before."""
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.triangulate(bm, faces=bm.faces[:], quad_method="BEAUTY", ngon_method="BEAUTY")
    bm.to_mesh(me)
    bm.free()
    me.update()
    n = len(me.polygons)
    if not target or target >= n:
        return me, lab
    co0 = coords(me)
    ob = bpy.data.objects.new("zoo_decimate", me)
    bpy.context.scene.collection.objects.link(ob)
    mod = ob.modifiers.new("zoo_decimate", "DECIMATE")
    mod.ratio = target / n
    mod.use_collapse_triangulate = True
    mod.use_symmetry, mod.symmetry_axis = True, "X"
    dg = bpy.context.evaluated_depsgraph_get()
    dg.update()
    me2 = bpy.data.meshes.new_from_object(ob.evaluated_get(dg))
    bpy.data.objects.remove(ob)
    bpy.data.meshes.remove(me)
    kd = _kdtree(co0)
    lab2 = np.array([lab[kd.find(p)[1]] for p in coords(me2)], np.int32)
    return me2, lab2


def _face_labels(lab, lv, ls, lt) -> np.ndarray:
    """Per face: the label most of its corners have (the first corner's on a tie)."""
    L = lab[lv]
    out = np.empty(len(ls), np.int32)
    for k in np.unique(lt):
        f = np.nonzero(lt == k)[0]
        C = np.stack([L[ls[f] + j] for j in range(k)], axis=1)
        cnt = np.stack([(C == C[:, [j]]).sum(axis=1) for j in range(k)], axis=1)
        out[f] = C[np.arange(len(f)), np.argmax(cnt, axis=1)]
    return out


def _palette(labels) -> dict:
    out = {}
    for i, n in enumerate(labels):
        if n == "body":
            out[n] = (0.80, 0.70, 0.58)
        else:
            out[n] = tuple(round(c, 4) for c in colorsys.hsv_to_rgb((0.11 + i * 0.61803) % 1.0, 0.7, 0.9))
    return out


def _colourize(me, flab, colours: dict, labels: list, mode: str, name: str) -> None:
    """One flat colour per ground-truth part: a corner colour attribute, and with "texture"
    UVs (every face its own cell of an atlas, inset so a lookup never reads a neighbour cell)
    and an image; a material that shows it."""
    lv, ls, lt = _faces(me)
    rgb = np.array([colours[labels[i]] for i in range(len(labels))], np.float32)[flab]
    corner = np.repeat(rgb, lt, axis=0)
    ca = me.color_attributes.new(COLOUR_ATTR, "BYTE_COLOR", "CORNER")
    ca.data.foreach_set("color", np.concatenate([corner, np.ones((len(corner), 1), np.float32)], 1).ravel())
    me.color_attributes.active_color = ca
    img = None
    if mode == "texture":
        nf = len(ls)
        G = int(math.ceil(math.sqrt(nf)))
        size = 1024
        while size < G * 6 and size < 4096:
            size *= 2
        c = max(1, size // G)
        uvl = me.uv_layers.new(name="UVMap")
        f = np.arange(nf)
        gi, gj = f % G, f // G
        inset = min(1.5, c / 3) / size
        u0, u1 = gi * c / size + inset, (gi + 1) * c / size - inset
        v0, v1 = gj * c / size + inset, (gj + 1) * c / size - inset
        kloop = np.arange(len(lv)) - np.repeat(ls, lt)
        fl = np.repeat(f, lt)
        cu = np.array([0, 1, 1, 0, 0, 0, 0, 0])[np.minimum(kloop, 7)]
        cv = np.array([0, 0, 1, 1, 1, 1, 1, 1])[np.minimum(kloop, 7)]
        uv = np.stack([np.where(cu, u1[fl], u0[fl]), np.where(cv, v1[fl], v0[fl])], axis=1)
        uvl.data.foreach_set("uv", uv.astype(np.float32).ravel())
        img = bpy.data.images.new(f"{name}_zoo_tex", size, size, alpha=False)
        px = np.zeros((size, size, 4), np.float32)
        px[..., :3] = 0.5
        px[..., 3] = 1.0
        cells = np.zeros((G, G, 3), np.float32)
        cells[gj, gi] = rgb
        px[:G * c, :G * c, :3] = np.repeat(np.repeat(cells, c, axis=0), c, axis=1)[:size, :size]
        img.pixels.foreach_set(px.ravel())
        img.pack()
    mat = bpy.data.materials.new(f"{name}_zoo")
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    if img is not None:
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = img
        tex.interpolation = "Closest"
        nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    else:
        node = nt.nodes.new("ShaderNodeVertexColor")
        node.layer_name = COLOUR_ATTR
        nt.links.new(node.outputs["Color"], bsdf.inputs["Base Color"])
    me.materials.append(mat)


def _rings(co, ev, lab, labels, k, root_design, extras) -> tuple:
    """The root ring (where the part meets what it grows from, nearest its designed root), the
    other contacts (touching the body or another part away from the root), the owners at the
    root, and the part-side vertices of the root ring."""
    inA = lab == k
    cross = inA[ev[:, 0]] != inA[ev[:, 1]]
    if not cross.any():
        return None, [], [], None
    a_side = np.where(inA[ev[cross, 0]], ev[cross, 0], ev[cross, 1])
    b_side = np.where(inA[ev[cross, 0]], ev[cross, 1], ev[cross, 0])
    band = np.zeros(len(co), bool)
    band[a_side] = True
    band[b_side] = True
    e_in = band[ev[:, 0]] & band[ev[:, 1]]
    sub = np.nonzero(band)[0]
    remap = np.full(len(co), -1)
    remap[sub] = np.arange(len(sub))
    comp = _components(len(sub), remap[ev[e_in, 0]], remap[ev[e_in, 1]])
    groups = []
    for cid in np.unique(comp[remap[a_side]]):
        m = comp[remap[a_side]] == cid
        av = np.unique(a_side[m])
        others = lab[b_side[m]]
        vals, cnt = np.unique(others, return_counts=True)
        with_ = [labels[int(x)] for x in vals[np.argsort(-cnt)]]
        groups.append((av, with_))

    def is_base(names):
        return any(n not in extras for n in names)
    cands = [g for g in groups if is_base(g[1])] or groups
    root = min(cands, key=lambda g: float(np.min(np.linalg.norm(co[g[0]] - root_design, axis=1))))
    rc = co[root[0]]
    centre = rc.mean(axis=0)
    ends = [tuple(map(float, centre))] * 2
    if len(rc) >= 3:
        _u, _sv, vt = np.linalg.svd(rc - centre, full_matrices=False)
        proj = (rc - centre) @ vt[:2].T
        major = float(proj[:, 0].max() - proj[:, 0].min()) / 2
        minor = float(proj[:, 1].max() - proj[:, 1].min()) / 2
        ends = [tuple(map(float, rc[np.argmin(proj[:, 0])])), tuple(map(float, rc[np.argmax(proj[:, 0])]))]
    else:
        major = minor = 0.0
    radius = float(np.median(np.linalg.norm(rc - centre, axis=1))) if len(rc) else 0.0
    aspect = minor / major if major > 1e-9 else 1.0
    shape = "round" if aspect >= 0.55 else "oval" if aspect >= 0.25 else "slot"
    ring = {"centre": tuple(map(float, centre)), "radius": radius, "major": major, "minor": minor,
            "aspect": float(aspect), "shape": shape, "ends": ends, "verts": int(len(rc))}
    contacts = []
    for av, with_ in groups:
        if av is root[0]:
            continue
        contacts.append({"with": with_, "centre": tuple(map(float, co[av].mean(axis=0))), "verts": int(len(av))})
    contacts.sort(key=lambda c: -c["verts"])
    return ring, contacts, root[1], root[0]


def _parent_of(e, bones, extras) -> str:
    """A part on another part hangs on that part; otherwise on the bone nearest its root."""
    on = [n for n in e.get("root_on") or [] if n in extras]
    if on and not [n for n in e["root_on"] if n not in extras]:
        return on[0]
    if not bones:
        return "body"
    p = np.asarray(e["root"], float)

    def dist(b):
        h, t = (np.asarray(x, float) for x in bones[b])
        d = t - h
        u = min(1.0, max(0.0, float((p - h) @ d) / max(float(d @ d), 1e-12)))
        return float(np.linalg.norm(p - (h + u * d)))
    return min(bones, key=dist)


def _mirror_share(tree, flab, co, lab, labels, k, e, voxel) -> tuple:
    """Shares of the part's vertices whose mirror image (x -> -x) lies on the surface within
    max(1.5 voxels, a quarter of the local radius): on any other owner (any owner at all for a
    part on the centre line), on itself, on its twin."""
    from mathutils import Vector
    idx = np.nonzero(lab == k)[0]
    if len(idx) == 0:
        return 0.0, 0.0, None
    idx = idx[:: max(1, len(idx) // 2500)]
    P = co[idx]
    r_loc, _s = _seg_project(P, e["path"])
    cap = 0.5 * float(e.get("thickness") or 0.0) or 0.08
    tol = np.maximum(1.5 * voxel, 0.25 * np.minimum(r_loc, cap))
    twin = labels.index(e["twin"]) if e.get("twin") in labels else None
    centre = str(e.get("symmetry", "")).startswith("centre")
    on_s = on_self = on_t = 0
    for p, t in zip(P.tolist(), tol.tolist()):
        hits = tree.find_nearest_range(Vector((-p[0], p[1], p[2])), t)
        ls = {int(flab[h[2]]) for h in hits}
        if (ls - ({k} if not centre else set())) or (centre and k in ls):
            on_s += 1
        on_self += k in ls
        on_t += twin is not None and twin in ls
    n = len(P)
    return on_s / n, on_self / n, (on_t / n if twin is not None else None)


# ----------------------------------------------------------------------------- bases

def _start(name, kind, voxel, scale, reset, opts=None):
    if reset:
        bpy.ops.wm.read_homefile(use_empty=True)
    o = dict(opts or {})
    if o.pop("preset", None) == "ai":
        o = {**AI_LIKE, **{k: v for k, v in o.items() if v is not None}}
    return Kit(name, kind, voxel, scale, o)


ADULT = {"pelvis": ((0, 0, 0.97), (0.165, 0.12, 0.1125)), "torso": ((0, 0, 1.22), (0.19, 0.125, 0.29)),
         "sh_z": 1.41, "sh_x": 0.15, "sh_r": 0.07, "sh_tube": 0.075, "neck": (1.44, 1.60, 0.05),
         "head_c": (0.0, -0.01, 1.69), "head": (0.10, 0.11, 0.12),
         "arm_x": (0.14, 0.46, 0.71), "arm_r": (0.055, 0.044, 0.035), "hand_x": 0.775, "hand": (0.065, 0.03, 0.045),
         "leg_x": (0.095, 0.10, 0.10), "leg_z": (1.0, 0.52, 0.09), "leg_r": (0.08, 0.06, 0.042),
         "foot": ((0.10, -0.05, 0.045), (0.05, 0.12, 0.045))}
# chibi: a big head on a small body (about 1.2 m, the head a third of the height)
CHIBI = {"pelvis": ((0, 0, 0.47), (0.14, 0.11, 0.09)), "torso": ((0, 0, 0.62), (0.15, 0.11, 0.17)),
         "sh_z": 0.74, "sh_x": 0.11, "sh_r": 0.055, "sh_tube": 0.06, "neck": (0.76, 0.84, 0.045),
         "head_c": (0.0, -0.01, 1.0), "head": (0.24, 0.22, 0.22),
         "arm_x": (0.10, 0.27, 0.42), "arm_r": (0.045, 0.038, 0.032), "hand_x": 0.47, "hand": (0.05, 0.03, 0.04),
         "leg_x": (0.07, 0.075, 0.075), "leg_z": (0.48, 0.26, 0.07), "leg_r": (0.065, 0.052, 0.042),
         "foot": ((0.075, -0.04, 0.038), (0.045, 0.09, 0.038))}


def humanoid_base(k: Kit, P: dict | None = None, head=None, head_c=None, legs: bool = True) -> None:
    """A plain T-pose humanoid (ADULT: 1.8 m; CHIBI: a big head): trunk + head in "body", arms
    and legs as limbs; anchors for the parts and a skeleton."""
    P = dict(P or ADULT)
    if head is not None:
        P["head"] = head
    if head_c is not None:
        P["head_c"] = head_c
    B = "body"
    k.base = k.base or "humanoid"
    pc, pr = P["pelvis"]
    tc, tr = P["torso"]
    sz, sx = P["sh_z"], P["sh_x"]
    k.ball(B, pc, 1.0, pr)
    k.ball(B, tc, 1.0, tr)
    k.tube(B, (-sx, 0, sz), (sx, 0, sz), P["sh_tube"])
    for x in (1, -1):
        k.ball(B, (sx * x, 0, sz), P["sh_r"])
    n0, n1, nr = P["neck"]
    k.tube(B, (0, 0, n0), (0, 0, n1), nr)
    hc, hr = P["head_c"], P["head"]
    k.ball(B, hc, 1.0, hr)
    k.ells = [(pc, pr), (tc, tr)]
    ax, ar, hx, hd = P["arm_x"], P["arm_r"], P["hand_x"], P["hand"]
    hand_tip = hx + hd[0]
    k.anchor.update({"head": (np.asarray(hc, float), np.asarray(hr, float)), "front": np.array([0, -1.0, 0]),
                     "back": {"axis": 1, "sign": 1.0, "n": np.array([0, 1.0, 0]), "a": np.array([0, 0, 1.0]),
                              "along_axis": 2, "along_sign": 1.0, "t": (pc[2] + 0.03, sz + 0.07)},
                     "tail_frame": (np.array([0, 1.0, 0]), np.array([0, 0, -1.0])),
                     "rump": lambda x, z=pc[2] + 0.01: np.array([x, k.surface(1, 1.0, x, z), z]),
                     "shoulder": {}, "arm": {}, "hand": {}, "leg": {}, "P": P})
    for x, s in ((1, "l"), (-1, "r")):
        arm = [(ax[0] * x, 0, sz), (ax[1] * x, 0, sz), (ax[2] * x, 0, sz)]
        k.path(f"arm_{s}", arm, list(ar))
        hcen = (hx * x, -0.005, sz)
        k.ball(f"arm_{s}", hcen, 1.0, hd)
        k.limb(f"arm_{s}", "arm", s, (hand_tip * x, -0.005, sz), arm + [(hand_tip * x, -0.005, sz)],
               parent=f"clavicle_{s}")
        k.anchor["shoulder"][s] = (np.array([sx * x, 0, sz]), P["sh_r"])
        k.anchor["arm"][s] = ([np.asarray(p, float) for p in arm], list(ar))
        k.anchor["hand"][s] = (np.asarray(hcen, float), np.asarray(hd, float), np.array([hand_tip * x, -0.005, sz]))
        if legs:
            lx, lz, lr = P["leg_x"], P["leg_z"], P["leg_r"]
            fc, fr = P["foot"]
            leg = [(lx[0] * x, 0, lz[0]), (lx[1] * x, 0, lz[1]), (lx[2] * x, 0.01, lz[2])]
            k.path(f"leg_{s}", leg, list(lr))
            k.ball(f"leg_{s}", (fc[0] * x, fc[1], fc[2]), 1.0, fr)
            toe = (fc[0] * x, fc[1] - fr[1], fc[2])
            k.limb(f"leg_{s}", "leg", s, toe, leg + [toe], parent="pelvis")
            k.anchor["leg"][s] = ([np.asarray(p, float) for p in leg], list(lr))
    k.core = (0.0, 0.0, tc[2] - 0.02)
    k.beside = (sx + 0.17, -0.04, pc[2] - 0.12)
    hb = hc[2] - 0.9 * hr[2]
    k.joints = {"pelvis": pc, "spine": (0, 0, (pc[2] + tc[2]) / 2), "chest": (0, 0, tc[2] + 0.08),
                "neck": (0, 0, n0 + 0.03), "head": (0, hc[1], hb), "head_top": (0, hc[1], hc[2] + hr[2])}
    for x, s in ((1, "l"), (-1, "r")):
        k.joints.update({f"shoulder_{s}": ((ax[0] + 0.02) * x, 0, sz), f"elbow_{s}": (ax[1] * x, 0, sz),
                         f"wrist_{s}": (ax[2] * x, 0, sz), f"hand_{s}": (hand_tip * x, -0.005, sz)})
        if legs:
            lx, lz = P["leg_x"], P["leg_z"]
            k.joints.update({f"hip_{s}": (lx[0] * x, 0, lz[0] - 0.05), f"knee_{s}": (lx[1] * x, 0, lz[1]),
                             f"ankle_{s}": (lx[2] * x, 0.01, lz[2])})
    if not legs:
        del k.joints["pelvis"]                       # no legs: where a pelvis goes is a rig choice
    sp0 = pc[2] + 0.05
    k.bones = {"pelvis": ((0, 0, pc[2] - 0.05), (0, 0, sp0)), "spine": ((0, 0, sp0), (0, 0, tc[2])),
               "chest": ((0, 0, tc[2]), (0, 0, n0)), "neck": ((0, 0, n0), (0, 0, hb)),
               "head": ((0, hc[1], hb), (0, hc[1], hc[2] + hr[2]))}
    for x, s in ((1, "l"), (-1, "r")):
        k.bones.update({f"clavicle_{s}": ((0.02 * x, 0, sz + 0.01), (sx * x, 0, sz)),
                        f"upperarm_{s}": ((sx * x, 0, sz), (ax[1] * x, 0, sz)),
                        f"forearm_{s}": ((ax[1] * x, 0, sz), (ax[2] * x, 0, sz)),
                        f"hand_{s}": ((ax[2] * x, 0, sz), (hand_tip * x, -0.005, sz))})
        if legs:
            lx, lz = P["leg_x"], P["leg_z"]
            fc, fr = P["foot"]
            k.bones.update({f"thigh_{s}": ((lx[0] * x, 0, lz[0] - 0.05), (lx[1] * x, 0, lz[1])),
                            f"calf_{s}": ((lx[1] * x, 0, lz[1]), (lx[2] * x, 0.01, lz[2])),
                            f"foot_{s}": ((lx[2] * x, 0.01, lz[2]), (fc[0] * x, fc[1] - fr[1], fc[2]))})


def chibi_base(k: Kit) -> None:
    """Chibi proportions: the head about a third of the height, short limbs (1.2 m)."""
    k.base = "chibi"
    humanoid_base(k, CHIBI)


def creature_base(k: Kit) -> None:
    """A humanoid upper body on a round mantle, no legs (for tentacles)."""
    k.base = "creature"
    humanoid_base(k, legs=False)
    k.ball("body", (0, 0, 0.86), 1.0, (0.21, 0.19, 0.18))
    k.ells.append(((0, 0, 0.86), (0.21, 0.19, 0.18)))
    k.bones["pelvis"] = ((0, 0, 0.80), (0, 0, 1.02))
    k.beside = (0.36, -0.30, 0.55)


def naga_base(k: Kit, r: float = 0.11, turns: float = 1.4, coil_side: str = "l") -> None:
    """A humanoid upper body on a snake's lower body that comes down behind and coils on the
    ground to one side: the snake body is one long chain (kind tail) with its root at the
    pelvis, on the centre line but not its own mirror image."""
    k.base = "naga"
    humanoid_base(k, legs=False)
    x = 1 if coil_side == "l" else -1
    down = [(0, 0, 0.93), (0, 0.02, 0.78), (0, 0.07, 0.56), (0, 0.13, 0.32)]
    C = np.array([0.20 * x, 0.30, 0.0])
    n = 36
    ph = np.linspace(math.pi * 1.25, math.pi * 1.25 + turns * 2 * math.pi, n)
    rho = np.linspace(0.34, 0.08, n)
    rad = np.linspace(0.085, 0.03, n)
    coil = [(C[0] + x * rho[i] * math.cos(ph[i]), C[1] + rho[i] * math.sin(ph[i]), rad[i]) for i in range(n)]
    pts = down + coil
    radii = [r, r * 0.95, r * 0.85, r * 0.75] + list(rad)
    pts = list(k.path("snake", pts, radii, seg=20, smooth=True))
    root = k.root_of("snake", pts, ["body"])
    k.appendage("snake", "tail", "c", root, pts[-1], "round", (2 * r, 2 * r), False, 2 * r * 0.8, "chain",
                path=_from_root(pts, root), symmetry="centre_asym", parent="pelvis", lower_body=True)
    k.beside = (-0.45 * x, -0.25, 0.5)


def quadruped_base(k: Kit, leg_r: float = 0.06) -> None:
    """A four-legged animal (1.25 m to the top of the head), body along Y, head forward (-Y)."""
    B = "body"
    k.base = "quadruped"
    body = [((0, 0, 0.75), (0.16, 0.45, 0.18)), ((0, -0.32, 0.78), (0.17, 0.20, 0.20)),
            ((0, 0.33, 0.78), (0.16, 0.18, 0.18))]
    for c, r in body:
        k.ball(B, c, 1.0, r)
    k.ells = list(body)
    k.path(B, [(0, -0.40, 0.84), (0, -0.55, 1.02), (0, -0.63, 1.13)], [0.10, 0.08, 0.07])   # neck
    hc, hr = (0, -0.70, 1.17), (0.09, 0.13, 0.09)
    k.ball(B, hc, 1.0, hr)                                           # head
    k.ball(B, (0, -0.83, 1.13), 1.0, (0.06, 0.08, 0.06))             # muzzle
    k.anchor.update({"head": (np.asarray(hc, float), np.asarray(hr, float)), "front": np.array([0, -1.0, 0]),
                     "back": {"axis": 2, "sign": 1.0, "n": np.array([0, 0, 1.0]), "a": np.array([0, -1.0, 0]),
                              "along_axis": 1, "along_sign": -1.0, "t": (-0.40, 0.45)},
                     "tail_frame": (np.array([0, 1.0, 0]), np.array([0, 0, -1.0])),
                     "rump": lambda x, z=0.86: np.array([x, k.surface(1, 1.0, x, z), z])})
    k.bones = {"pelvis": ((0, 0.42, 0.80), (0, 0.15, 0.80)), "spine": ((0, 0.15, 0.80), (0, -0.15, 0.80)),
               "chest": ((0, -0.15, 0.80), (0, -0.40, 0.84)), "neck": ((0, -0.40, 0.84), (0, -0.63, 1.13)),
               "head": ((0, -0.63, 1.13), (0, -0.90, 1.13))}
    k.joints = {"pelvis": (0, 0.33, 0.80), "chest": (0, -0.32, 0.80), "neck": (0, -0.55, 1.02),
                "head": (0, -0.66, 1.15)}
    for x, s in ((1, "l"), (-1, "r")):
        for y, fb in ((-0.30, "f"), (0.32, "b")):
            name = f"leg_{fb}{s}"
            pts = [(0.10 * x, y, 0.72), (0.105 * x, y + (0.02 if fb == "f" else -0.04), 0.38), (0.10 * x, y, 0.06)]
            k.path(name, pts, [leg_r * 1.25, leg_r, leg_r * 0.75])
            k.ball(name, (0.10 * x, y - 0.02, 0.035), 1.0, (0.055, 0.07, 0.035))
            bottom = (0.10 * x, y - 0.02, 0.0)
            up, lo, ft = ("upperarm", "forearm", "hand") if fb == "f" else ("thigh", "calf", "foot")
            k.limb(name, "leg", s, bottom, pts + [bottom], parent="chest" if fb == "f" else "pelvis")
            k.bones.update({f"{up}_{s}": (pts[0], pts[1]), f"{lo}_{s}": (pts[1], pts[2]),
                            f"{ft}_{s}": (pts[2], bottom)})
            j0, j1, j2 = ("shoulder", "elbow", "wrist") if fb == "f" else ("hip", "knee", "ankle")
            k.joints.update({f"{j0}_{fb}{s}": pts[0], f"{j1}_{fb}{s}": pts[1], f"{j2}_{fb}{s}": pts[2]})
    k.core = (0.0, 0.0, 0.75)
    k.beside = (0.32, 0.0, 0.45)


BASES = {"humanoid": humanoid_base, "chibi": chibi_base, "creature": creature_base, "naga": naga_base,
         "quadruped": quadruped_base}
BASE_KIND = {"humanoid": "humanoid", "chibi": "humanoid", "creature": "creature", "naga": "creature",
             "quadruped": "quadruped"}


# ----------------------------------------------------------------------------- parts: back

def bat_wing(k: Kit, side: str = "l", thick: float = 0.024, span: float = 1.0, fingers: int = 3,
             scallop: float = 0.22, bones: bool = True, at: float = 0.583, spread=(0.75, 0.15),
             root_len: float = 0.24, x0: float = 0.07, name: str = "wing") -> None:
    """A membrane wing from the back: a flat plate a few voxels thick, a long slot-shaped root
    (root_len long, x0 from the middle), finger bones fanning from the wrist, a scalloped
    trailing edge. at: how far up the back (0 low back, 1 shoulders); spread: (out from the
    back, along it) of the span direction."""
    x = 1 if side == "l" else -1
    nm = f"{name}_{side}"
    bk = k.anchor["back"]
    R, _n = k.back_point(x0 * x, at)
    u = _unit(x * np.array([1.0, 0, 0]) + spread[0] * bk["n"] + spread[1] * bk["a"])
    v = _unit(bk["a"] - (bk["a"] @ u) * u)
    hr, bury = root_len / 2, 0.06
    W2 = np.array([0.30, 0.30]) * span
    angs = np.radians(np.linspace(15, -70, fingers))
    lens = np.linspace(0.62, 0.42, fingers) * span
    tips = [W2 + L * np.array([math.cos(a), math.sin(a)]) for a, L in zip(angs, lens)]
    cen = np.mean([W2] + tips + [np.array([0.0, -hr])], axis=0)

    def scal(P, Q, n=8):
        P, Q = np.asarray(P), np.asarray(Q)
        mid = (P + Q) / 2
        d = Q - P
        nrm = np.array([-d[1], d[0]])
        nrm = nrm / max(np.linalg.norm(nrm), 1e-12)
        if nrm @ (cen - mid) < 0:
            nrm = -nrm
        C = mid + nrm * scallop * np.linalg.norm(d)
        t = np.linspace(0, 1, n + 2)[1:-1, None]
        return list((1 - t) ** 2 * P + 2 * (1 - t) * t * C + t ** 2 * Q)
    out = [np.array([-bury, hr]), np.array([0.0, hr]), W2, tips[0]]
    for a, b in zip(tips, tips[1:]):
        out += scal(a, b) + [b]
    out += scal(tips[-1], np.array([0.03, -hr])) + [np.array([0.03, -hr]), np.array([-bury, -hr])]
    k.plate(nm, out, thick, R, u, v)

    def to3(q):
        return R + q[0] * u + q[1] * v
    if bones:
        br = 0.8 * max(thick, k.tmin)
        k.tube(nm, to3(np.array([-bury, 0.0])), to3(W2), br * 1.3, br * 1.1)
        k.ball(nm, to3(W2), br * 1.3)
        for t in tips:
            k.tube(nm, to3(W2), to3(t), br, br * 0.5)
    far = max(tips, key=lambda t: np.linalg.norm(t))
    root = k.root_of(nm, [R, to3(W2)], hint=R)
    k.appendage(nm, "wing", side, root, to3(far), "slot", (2 * hr, thick), True, thick, "wing",
                path=[R, to3(W2), to3(far)], group=name,
                shape=(thick, span, fingers, scallop, bones, at, spread, root_len, x0), fingers=fingers)


def bird_wing(k: Kit, side: str = "l", t_root: float = 0.07, t_tip: float = 0.036, span: float = 1.0,
              fold: float = 1.0, feathers: int = 6, rest: bool = True, name: str = "wing") -> None:
    """A thick feathered wing (adult humanoid): a tapered wedge (thick leading edge, thin
    trailing edge) going out to the wrist, then folded down along the back; with rest its lower
    trailing edge rests against the back of the thigh (a contact AWAY from the root)."""
    x = 1 if side == "l" else -1
    nm = f"{name}_{side}"
    X = np.array([x, 1, 1], float)
    sp = span
    inner = np.array([(0.03, 0.07, 1.36), (0.12, 0.15, 1.42), (0.12 + 0.14 * sp, 0.15 + 0.11 * sp, 1.50),
                      (0.12 + 0.26 * sp, 0.15 + 0.17 * sp, 1.49)]) * X
    wrist = inner[-1]
    lo = 1.49 - (1.49 - 0.84) * fold
    outer = np.array([wrist + np.array([0.02 * x, 0.0, 0.03]),
                      (wrist[0] + 0.01 * x, wrist[1], 1.49 - (1.49 - lo) * 0.3),
                      (wrist[0] - 0.05 * x, wrist[1] - 0.04, 1.49 - (1.49 - lo) * 0.68),
                      (wrist[0] - 0.13 * x, wrist[1] - 0.12, lo)])
    m = 28
    L = _resample(inner, m)
    t = _arc_params(L)
    chord = _lerp_ctrl([(0, 0.02, -0.15), (0, 0.03, -0.17), (0, 0.04, -0.17), (0, 0.04, -0.15)], t)
    tl = _lerp_ctrl([t_root, 0.85 * t_root, 0.7 * t_root, 0.6 * t_root], t)
    c = 7
    kk = np.linspace(0, 1, c)
    serr = 1.0 + 0.18 * ((np.arange(m) * feathers / m) % 1.0) * (t > 0.25)
    P = L[:, None, :] + chord[:, None, :] * (kk[None, :, None] * serr[:, None, None])
    T = tl[:, None] * (1.0 - 0.5 * kk[None, :])
    k.sheet(nm, P, T)
    m2 = 40
    L2 = _resample(outer, m2)
    t2 = _arc_params(L2)
    rest = rest and fold >= 0.8          # (only a wing folded down far enough reaches the thigh)
    if rest:          # the inner (trailing) edge comes in to rest on the back of the thigh
        ctrl = [(-0.16 * x, -0.02, 0), (-0.17 * x, -0.06, 0), (-0.18 * x, -0.10, 0), (-0.15 * x, -0.14, 0)]
    else:             # folded, but held clear of the body
        ctrl = [(-0.16 * x, -0.02, 0), (-0.15 * x, -0.04, 0), (-0.13 * x, -0.04, 0), (-0.10 * x, -0.03, 0)]
    chord2 = _lerp_ctrl(ctrl, t2)
    tl2 = _lerp_ctrl([0.6 * t_root, 0.5 * t_root, 0.4 * t_root, t_tip], t2)
    serr2 = 1.0 + 0.3 * ((np.arange(m2) * feathers / m2) % 1.0)
    P2 = L2[:, None, :] + chord2[:, None, :] * (kk[None, :, None] * serr2[:, None, None])
    T2 = tl2[:, None] * (1.0 - 0.5 * kk[None, :])
    k.sheet(nm, P2, T2)
    k.ball(nm, wrist, 0.45 * t_root)
    # the middle of the root: where the wing's surface crosses the back, near where its
    # mid-chord line leaves it
    R = k.root_of(nm, L + chord * 0.5, hint=k.exit_point(L + chord * 0.5))
    tip = L2[-1] + chord2[-1] * 0.5               # the middle of the folded tip's lower edge
    mid = L2[m2 // 2] + 0.5 * chord2[m2 // 2]
    corner = L2[-1] + chord2[-1] * serr2[-1]
    contact = [k.exit_point([corner, L2[-1]], [f"leg_{side}"])] if rest else []
    path = [R, wrist, mid, tip + np.array([0, 0, min(0.12, 0.5 * (mid[2] - tip[2]))]), tip]
    if fold < 0.8:            # folded only a little: the inner wing's trailing edge hangs lowest
        tip = _snap_tip(np.asarray(k.geo[nm][0]), path, k.voxel / k.scale)
    k.appendage(nm, "wing", side, R, tip, "oval", (0.16, t_root), False, t_root, "wing", path=path, group=name,
                shape=(t_root, t_tip, span, fold, feathers, rest), contact_design=contact, feathers=feathers)


def _fin_outline(back, outward, height, spikes: int, bury: float):
    """2D outline of a crest standing on a curve: back (n,2) points, outward (n,2) normals.
    Returns (outline, n, heights)."""
    n = len(back)
    t = np.linspace(0, 1, n)
    env = np.sin(np.pi * t) ** 0.6
    tri = 1.0 - np.abs(((t * spikes) % 1.0) * 2.0 - 1.0)      # 0 at the valleys, 1 at the spikes
    h = height * env * (0.45 + 0.55 * tri) if spikes else height * env
    root = back - bury * outward
    top = back + (h[:, None] + 0.004) * outward
    return np.concatenate([root, top[::-1]]), n, h


def dorsal_fin(k: Kit, height: float = 0.16, thick_root: float = 0.04, thick_edge: float = 0.018, spikes: int = 6,
               span=None, name: str = "fin") -> None:
    """A fin / crest along the back ON the centre line (any base with a back): its root is a long
    line on the mirror plane, following the trunk's surface (over the chest and hip bumps)."""
    bk = k.anchor["back"]
    f0, f1 = span or ((0.0, 1.0) if bk["axis"] == 1 else (0.1176, 0.8235))
    fs = np.linspace(f0, f1, 60)
    pn = [k.back_point(0.0, f) for f in fs]
    back = np.array([p[1:] for p, _n in pn])
    outward = np.array([n[1:] for _p, n in pn])
    ker = np.ones(9) / 9                                        # (smoothed: the union has creases)
    outward = np.stack([np.convolve(np.pad(outward[:, i], 4, mode="edge"), ker, "valid") for i in range(2)], 1)
    outward /= np.linalg.norm(outward, axis=1, keepdims=True)
    outline, n, h = _fin_outline(back, outward, height, spikes, 0.035)
    G = np.zeros((n, 2, 3))
    G[:, 0, 1:], G[:, 1, 1:] = outline[:n], outline[n:][::-1]
    k.sheet(name, G, np.stack([np.full(n, thick_root), np.full(n, thick_edge)], axis=1))
    j = int(np.argmax(h))                                       # the tallest spike
    tip = (0.0, *(back[j] + (h[j] + 0.004) * outward[j]))
    L = float(np.sum(np.linalg.norm(np.diff(back, axis=0), axis=1)))
    root = k.root_of(name, [(0.0, *back[n // 2]), tip], hint=(0.0, *back[n // 2]))
    k.appendage(name, "fin", "c", root, tip, "line", (L, thick_root), True, thick_edge, "rigid",
                path=[(0.0, *back[j]), tip], symmetry="centre", spikes=spikes,
                root_line_design=[(0.0, *back[0]), (0.0, *back[-1])])


def cape(k: Kit, thick: float = 0.024, gap: float = 0.03, touch_rump: bool = True, touch_leg: str = "l",
         length: float = 1.0, name: str = "cape") -> None:
    """A thin cape sheet (adult humanoid) hanging from the shoulders: fused along the shoulders
    (a long arc root), hanging `gap` behind the back (never less than the remesh keeps open),
    touching the rump and (touch_leg "l"/"r"/"") the back of one calf. With a calf fold it is
    not its own mirror image (centre_asym)."""
    t = max(thick, k.tmin)
    g = max(gap, 2.5 * k.voxel / k.scale)
    m, c = 56, 37
    z_top, z_bot = 1.47, 1.47 - 1.17 * length
    zs = np.linspace(z_top, z_bot, m)
    th = np.radians(np.linspace(-80, 80, c))
    P = np.zeros((m, c, 3))
    into = 0.012                                    # how far a touching cape dents into the body
    for i, z in enumerate(zs):
        f = (z_top - z) / (z_top - z_bot)                      # 0 at the shoulders, 1 at the hem
        w = 0.17 + 0.12 * min(1.0, f * 1.6)
        hang = 0.125 + g + t / 2 + 0.03 * f                    # behind the deepest point of the back
        hug = min(0.10 + 0.4 * (1.47 - min(z, 1.47)), hang)    # over the shoulders: on the upper back
        q = min(1.0, max(0.0, (1.36 - z) / 0.10))
        yc = -0.02 * (1 - q)
        d = hug * (1 - q) + hang * q
        if touch_rump:                                         # the middle comes in onto the rump
            target = 0.118 - into + t / 2
            d -= max(0.0, yc + d - target) * math.exp(-((z - 0.95) / 0.08) ** 2)
        ripple = 0.012 * np.cos(5 * th) * f                    # (even: the cape alone mirrors onto itself)
        x = w * np.sin(th)
        y = yc + d * np.cos(th) + ripple
        if touch_leg in ("l", "r"):                            # a fold falls onto one calf
            sx = 0.10 if touch_leg == "l" else -0.10
            ts = math.asin(max(-1.0, min(1.0, sx / w)))
            at = yc + d * math.cos(ts) + 0.012 * math.cos(5 * ts) * f
            pull = max(0.0, at - (0.058 - into + t / 2))
            y = y - pull * np.exp(-((x - sx) / 0.06) ** 2) * math.exp(-((z - 0.42) / 0.10) ** 2)
        P[i, :, 0], P[i, :, 1], P[i, :, 2] = x, y, z
    k.sheet(name, P, thick)
    contacts = []
    if touch_rump:
        contacts.append((0.0, 0.11, 0.95))
    if touch_leg in ("l", "r"):
        contacts.append((0.10 if touch_leg == "l" else -0.10, 0.06, 0.42))
    top = P[0]
    root = k.root_of(name, [top[c // 2], P[-1, c // 2]], hint=top[c // 2])
    k.appendage(name, "cape", "c", root, tuple(P[-1, c // 2]), "arc", (0.45, thick), True, thick,
                "cloth", path=[tuple(P[i, c // 2]) for i in range(0, m, 8)] + [tuple(P[-1, c // 2])],
                symmetry="centre_asym" if touch_leg in ("l", "r") else "centre", parent="chest",
                contact_design=contacts, root_line_design=[tuple(top[0]), tuple(top[c // 2]), tuple(top[-1])])


def spikes(k: Kit, where: str = "head", n: int = 14, length: float = 0.08, r: float = 0.016, on: str = "tail",
           name: str = "spike") -> None:
    """A dense cluster of spikes, each its own part: "head" (hair spikes on the top and back of
    the head, mirrored pairs plus centre ones), "back" (spines down the centre line of the back)
    or "tail" (on top of the part `on`: a part on a part)."""
    made = []
    if where == "head":
        hc, hr = k.anchor["head"]
        back = k.anchor["tail_frame"][0]
        up = np.array([0, 0, 1.0])
        X = np.array([1.0, 0, 0])

        def spot(th, ph):            # polar angle from up, azimuth from the back towards +X
            d = math.cos(th) * up + math.sin(th) * (math.cos(ph) * back + math.sin(ph) * X)
            return hc + hr * d, _unit(d / hr)
        cands = []
        for i in range(600):         # a golden spiral over the top and back of the head
            th = math.acos(1 - (i + 0.5) / 600 * (1 - math.cos(math.radians(80))))
            ph = math.radians((i * 137.508) % 180.0)
            cands.append((th, min(ph, math.pi - ph) if ph > math.pi / 2 else ph))
        dmin = 2 * r + 3 * k.voxel / k.scale + 0.012
        for _try in range(12):
            acc = []
            for th, ph in cands:
                p, _n = spot(th, ph)
                if p[0] < 0.35 * dmin:
                    p, _n = spot(th, 0.0)
                    ps, kind = [p], "c"
                else:
                    ps, kind = [p, p * np.array([-1, 1, 1])], "pair"
                    if 2 * p[0] < dmin:
                        continue
                if sum(2 if a[0] == "pair" else 1 for a in acc) + len(ps) > n:
                    continue
                if all(np.linalg.norm(q - b) >= dmin for q in ps for a in acc for b in a[1]):
                    acc.append((kind, ps, th, ph))
            if sum(2 if a[0] == "pair" else 1 for a in acc) >= n:
                break
            dmin *= 0.9
        i = 0
        for j, (kind, _ps, th, ph) in enumerate(acc):
            for x, s in (((0, "c"),) if kind == "c" else ((1, "l"), (-1, "r"))):
                p, nrm = spot(th, 0.0 if kind == "c" else ph)
                if x < 0:
                    p, nrm = p * np.array([-1, 1, 1]), nrm * np.array([-1, 1, 1])
                axis = _unit(nrm + 0.45 * back)
                i += 1
                nm = f"{name}_{i}"
                a, b = p - 0.6 * r * nrm, p + length * axis
                k.tube(nm, a, b, r, 0.0, seg=10)
                made.append((nm, s, a, b, ("pair", j) if kind == "pair" else None))
    elif where == "back":
        for i in range(n):
            f = 0.12 + 0.78 * (i + 0.5) / n
            p, nrm = k.back_point(0.0, f)
            axis = _unit(nrm - 0.35 * k.anchor["back"]["a"])
            a, b = p - 0.6 * r * nrm, p + length * (1.0 - 0.3 * abs(2 * (i + 0.5) / n - 1)) * axis
            nm = f"{name}_{i + 1}"
            k.tube(nm, a, b, r, 0.0, seg=10)
            made.append((nm, "c", a, b, None))
    else:
        host = k.app[on]
        P = np.asarray(host["path"], float)
        Ps = _resample(P, 60)
        rs = host["thickness"] / 2 * np.linspace(1.0, 0.45, 60)
        up = np.array([0, 0, 1.0])
        for i in range(n):
            j = int(round((0.22 + 0.62 * i / max(n - 1, 1)) * 59))
            tng = _unit(Ps[min(j + 1, 59)] - Ps[max(j - 1, 0)])
            perp = up - (up @ tng) * tng
            if np.linalg.norm(perp) < 0.3:
                perp = k.anchor["tail_frame"][0] - (k.anchor["tail_frame"][0] @ tng) * tng
            perp = _unit(perp)
            a = Ps[j] + perp * rs[j] * 0.3
            b = Ps[j] + perp * (rs[j] + length * (1.0 - 0.4 * i / max(n, 1)))
            nm = f"{name}_{i + 1}"
            k.tube(nm, a, b, min(r, 0.8 * rs[j]), 0.0, seg=10)
            made.append((nm, "c", a, b, None))
    host_sym = k.app[on]["symmetry"] if where == "tail" else None
    for nm, s, a, b, pair in made:
        owners = [on] if where == "tail" else None
        root = k.root_of(nm, [a, b], owners)
        sym = None if s != "c" else (host_sym if host_sym in ("centre", "centre_asym") else "centre")
        k.appendage(nm, "spike", s, root, b, "round", (2 * r, 2 * r), True, 2 * r, "rigid", path=[root, b],
                    symmetry=sym, group=f"{name}_pair{pair[1]}" if pair else None, shape=(length, r),
                    parent=on if where == "tail" else ("head" if where == "head" else None))


def back_hair(k: Kit, length: float = 0.55, width: float = 0.17, thick: float = 0.03, name: str = "hair") -> None:
    """Long hair lying along the back (humanoid): a slab from the back of the head down the
    upper back, resting on it all the way (its root and its contact are one long seam)."""
    hc, hr = k.anchor["head"]
    t = max(thick, k.tmin)
    z_top = hc[2] + 0.35 * hr[2]
    z_bot = z_top - length
    zs = np.linspace(z_top, z_bot, 44)
    xs_u = np.linspace(-1, 1, 15)
    y_head_back = hc[1] + hr[1] * math.sqrt(max(0.0, 1 - ((z_top - hc[2]) / hr[2]) ** 2))
    sh_top = k.anchor["P"]["sh_z"] + 0.04
    y_sh = k.surface(1, 1.0, 0.0, sh_top)
    P = np.zeros((len(zs), len(xs_u), 3))
    for i, z in enumerate(zs):
        f = (z_top - z) / length
        w = width * (0.75 + 0.35 * f)
        for j, uu in enumerate(xs_u):
            x = uu * w / 2
            ys = [y_head_back + (y_sh - y_head_back) * min(1.0, max(0.0, (z_top - z) / (z_top - sh_top)))]
            q = 1 - (x / hr[0]) ** 2 - ((z - hc[2]) / hr[2]) ** 2
            if q > 0:
                ys.append(hc[1] + hr[1] * math.sqrt(q))
            yb = k.surface(1, 1.0, x, z)
            if not math.isnan(yb):
                ys.append(yb)
            P[i, j] = (x, max(ys) + t / 2 - 0.006, z)
    k.sheet(name, P, t)
    root = k.root_of(name, [P[0, 7], P[-1, 7]], hint=P[0, 7])
    k.appendage(name, "hair", "c", root, tuple(P[-1, 7]), "slot", (width, t), True, t, "cloth",
                path=[tuple(P[i, 7]) for i in range(0, len(zs), 6)] + [tuple(P[-1, 7])], symmetry="centre",
                parent="head", lies_on="back")


def sash(k: Kit, from_side: str = "l", width: float = 0.075, thick: float = 0.02, name: str = "sash") -> None:
    """A band round the torso from one shoulder across the chest and back to the other hip
    (humanoid): fused along all its length, crossing the mirror plane, not its own mirror image."""
    x = 1 if from_side == "l" else -1
    P_ = k.anchor["P"]
    sh = np.array([0.11 * x, 0.0, P_["sh_z"] + 0.03])
    hip = np.array([-0.15 * x, 0.0, P_["pelvis"][0][2] + 0.05])
    c = (sh + hip) / 2
    e1 = _unit(sh - hip)
    e2 = np.array([0, 1.0, 0])
    nP = _unit(np.cross(e1, e2))
    t = max(thick, k.tmin)
    phis = np.linspace(0, 2 * math.pi, 72, endpoint=False)
    owners = ["body"]
    rows = []
    for ph in phis:
        d = math.cos(ph) * e1 + math.sin(ph) * e2
        rho = k.ray_out(c, d, owners)
        rows.append(c + d * (rho + t / 2 - 0.006))
    ring = np.array(rows)
    ws = np.linspace(-width / 2, width / 2, 7)
    G = ring[None, :, :] + ws[:, None, None] * nP[None, None, :]
    k.sheet(name, G, t, closed=True)
    front = [ring[i] for i in range(36, 72)] + [ring[0]]          # (phi from pi to 2pi: the front, -Y)
    path = front[::-1]                                            # the shoulder ... the hip, over the chest
    root = k.root_of(name, path, ["body"], hint=ring[0])
    k.appendage(name, "sash", "c", root, path[-1], "line", (2 * np.linalg.norm(sh - hip), t), True, t, "skin",
                path=path[::4] + [path[-1]], symmetry="centre_asym", parent="chest", lies_on="torso")


def skirt(k: Kit, length: float = 0.42, flare: float = 1.0, thick: float = 0.022, name: str = "skirt") -> None:
    """A skirt (humanoid with legs): a ring of cloth fused round the waist, flaring over the hips
    and resting on the outside of both thighs (contacts on both legs, across the crotch)."""
    P_ = k.anchor["P"]
    pc, pr = P_["pelvis"]
    t = max(thick, k.tmin)
    z_top = pc[2] + 0.05
    z_bot = z_top - length
    zs = np.linspace(z_top, z_bot, 40)
    th = np.linspace(0, 2 * math.pi, 64, endpoint=False)
    lx, lz, lr = P_["leg_x"], P_["leg_z"], P_["leg_r"]

    def thigh_out(z):                         # outer x of the thigh at height z
        f = min(1.0, max(0.0, (lz[0] - z) / (lz[0] - lz[1])))
        return lx[0] + f * (lx[1] - lx[0]) + lr[0] + f * (lr[1] - lr[0])
    G = np.zeros((len(zs), len(th), 3))
    ay_top = k.ray_out((0, 0, z_top), (0, 1, 0), ["body"], far=0.5) + t / 2 - 0.006
    for i, z in enumerate(zs):
        f = (z_top - z) / length
        c = np.array([0.0, 0.0, z])
        rbx = k.ray_out(c, (1, 0, 0), ["body"], far=0.5)
        rby = k.ray_out(c, (0, 1, 0), ["body"], far=0.5)
        ax = max(rbx + t / 2 + 0.008, thigh_out(z) + t / 2 - 0.005 if z < lz[0] - 0.06 else 0.0)
        ay = max(ay_top + 0.05 * flare * f, rby + t / 2 + 0.008)
        for j, a in enumerate(th):
            d = np.array([math.cos(a), math.sin(a), 0.0])
            rb = k.ray_out(c, d, ["body"], far=0.5)
            if i < 3:
                rho = rb + t / 2 - 0.006                       # the waistband: fused
            else:
                ell = 1.0 / math.sqrt((math.cos(a) / ax) ** 2 + (math.sin(a) / ay) ** 2)
                rho = max(ell, rb + t / 2 + 0.008) if rb > 0 else ell
            G[i, j] = c + d * rho
    k.sheet(name, G, t, closed=True)
    hem = G[-1, int(np.argmin(np.abs(th - 1.5 * math.pi)))]          # the front of the hem (-Y)
    waist = np.array([0.0, 0.0, z_top - 0.01])
    root = k.root_of(name, [waist, hem], ["body"], hint=G[0, 0])
    k.appendage(name, "skirt", "c", root, hem, "round", (2 * pr[0], 2 * pr[1]),
                True, t, "cloth", path=[waist, hem], symmetry="centre", parent="pelvis")


# ----------------------------------------------------------------------------- parts: shoulders and arms

def cannon(k: Kit, side: str = "l", barrel_r: float = 0.05, name: str = "cannon") -> None:
    """A thick one-sided arm cannon fused on the shoulder (humanoid): housing, a barrel pointing
    forward, a drum behind. NOT thin."""
    x = 1 if side == "l" else -1
    nm = f"{name}_{side}"
    sc, _sr = k.anchor["shoulder"][side]
    o = sc + np.array([0, 0, 0])
    k.ball(nm, o + (0.05 * x, 0.03, 0.09), 1.0, (0.09, 0.10, 0.07))                     # housing
    k.tube(nm, o + (0.07 * x, 0.02, 0.135), o + (0.07 * x, -0.38, 0.135), barrel_r)      # barrel
    k.tube(nm, o + (0.07 * x, -0.33, 0.135), o + (0.07 * x, -0.41, 0.135), barrel_r * 1.3)  # muzzle
    k.tube(nm, o + (0.02 * x, 0.14, 0.09), o + (0.12 * x, 0.14, 0.09), 0.06)             # drum
    root = k.root_of(nm, [o + (0.05 * x, 0.03, 0.0), o + (0.05 * x, 0.03, 0.20)])
    tip = o + (0.07 * x, -0.41, 0.135)
    k.appendage(nm, "cannon", side, root, tip, "oval", (0.18, 0.12), False, 2 * barrel_r, "rigid",
                path=[root, o + (0.07 * x, 0.0, 0.135), tip], group=name, shape=(barrel_r,))


def pauldron(k: Kit, side: str = "l", name: str = "pauldron") -> None:
    """A thick dome of armour over one shoulder (humanoid), fused on it."""
    x = 1 if side == "l" else -1
    nm = f"{name}_{side}"
    sc, _sr = k.anchor["shoulder"][side]
    rot = _rot("y", 0.35 * x)
    c = sc + (0.04 * x, 0.0, 0.06)
    k.ball(nm, c, 1.0, (0.12, 0.12, 0.07), rot=rot)                          # dome
    k.ball(nm, sc + (0.06 * x, 0.0, 0.125), 1.0, (0.05, 0.09, 0.035), rot=rot)   # ridge
    down = rot @ np.array([0, 0, -1.0])
    root = k.root_of(nm, [c + 0.12 * down, c - 0.12 * down])
    out = rot @ np.array([x * 1.0, 0, 0])
    tip = c + 0.10 * out - 0.35 * 0.07 * down        # the dome's outer edge, above the arm
    k.appendage(nm, "pauldron", side, root, tip, "oval", (0.24, 0.24), False, 0.07, "rigid",
                path=[root, c, tip], group=name, shape=())


def extra_arms(k: Kit, drop: float = 0.17, reach: float = 0.92, name: str = "arm2") -> None:
    """A second pair of arms below the first (humanoid), also in T-pose: limbs a humanoid
    skeleton does not have."""
    P_ = k.anchor["P"]
    z = P_["sh_z"] - drop
    tc, tr = P_["torso"]
    for x, s in ((1, "l"), (-1, "r")):
        nm = f"{name}_{s}"
        arm = [(0.10 * x, 0, z), (0.42 * reach * x, 0, z), (0.66 * reach * x, 0, z)]
        k.path(nm, arm, [0.05, 0.04, 0.032])
        hc = (0.72 * reach * x, -0.005, z)
        k.ball(nm, hc, 1.0, (0.06, 0.028, 0.042))
        tip = ((0.72 * reach + 0.06) * x, -0.005, z)
        root = k.root_of(nm, arm + [tip])
        k.appendage(nm, "arm", s, root, tip, "round", (0.10, 0.10), False, 0.09, "limb",
                    path=[tuple(root)] + arm[1:] + [tip], group=name, shape=(drop, reach))


def weapon(k: Kit, side: str = "r", point: str = "out", length: float = 0.75, name: str = "sword") -> None:
    """A sword fused into the hand (humanoid): grip through the fist, guard, blade. point "out"
    (along the arm: it moves the T-pose hand extent), "up", "down" or "forward"."""
    x = 1 if side == "l" else -1
    nm = f"{name}_{side}"
    hc, hd, _tip = k.anchor["hand"][side]
    d = {"out": np.array([x, 0, 0.0]), "up": np.array([0, 0, 1.0]), "down": np.array([0, 0, -1.0]),
         "forward": np.array([0, -1.0, 0])}[point]
    w = np.array([0, 0, 1.0]) if point in ("out", "forward") else np.array([0, -1.0, 0])
    nrm = _unit(np.cross(d, w))
    k.tube(nm, hc, hc + d * 0.10, 0.017)                                 # grip (out of the fist on one side)
    k.ball(nm, hc + d * 0.11, 1.0, (0.085, 0.013, 0.018), rot=np.stack([w, d, nrm], axis=1))   # guard
    s0, s1 = 0.12, 0.12 + length
    outline = [(s0, -0.026), (s1 - 0.07, -0.024), (s1, 0.0), (s1 - 0.07, 0.024), (s0, 0.026)]
    k.plate(nm, outline, 0.012, hc, d, w)
    root = k.root_of(nm, [hc, hc + d * s1], hint=hc + d * hd[{"out": 0, "up": 2, "down": 2, "forward": 1}[point]])
    k.appendage(nm, "weapon", side, root, hc + d * s1, "round", (0.05, 0.035), True, 0.012, "prop",
                path=[root, hc + d * s0, hc + d * s1], group=name, shape=(point, length), held_in=f"arm_{side}")


def shield(k: Kit, side: str = "l", radius: float = 0.22, thick: float = 0.03, name: str = "shield") -> None:
    """A round shield strapped to the front of the forearm (humanoid): a big one-sided disc
    rooted on a limb."""
    nm = f"{name}_{side}"
    arm, ar = k.anchor["arm"][side]
    mid = (arm[1] + arm[2]) / 2
    r_arm = (ar[1] + ar[2]) / 2
    back = mid[1] - r_arm + 0.008                     # its back face 8 mm into the forearm
    a = np.array([mid[0], back, mid[2]])
    b = np.array([mid[0], back - thick, mid[2]])
    k.tube(nm, a, b, radius, radius * 0.97, seg=40)
    k.ball(nm, b, 1.0, (0.05, 0.025, 0.05))           # boss
    root = k.root_of(nm, [a, b], hint=np.array([mid[0], mid[1] - r_arm, mid[2]]))
    k.appendage(nm, "shield", side, root, b + np.array([0, -0.025, 0]), "round", (0.2, 0.08), True, thick, "prop",
                path=[root, b + np.array([0, -0.025, 0])], group=name, shape=(radius, thick), parent=f"forearm_{side}")


def arm_blade(k: Kit, side: str = "r", length: float = 0.32, name: str = "blade") -> None:
    """A blade fused along the top of the forearm, pointing out past the hand (humanoid)."""
    x = 1 if side == "l" else -1
    nm = f"{name}_{side}"
    arm, ar = k.anchor["arm"][side]
    z0 = arm[1][2]
    x0, x1 = arm[1][0] * 0.95, arm[2][0]
    top = ar[1]
    xt = x1 + length * x
    outline = [(x0, z0 + top - 0.02), (x1, z0 + top - 0.02), (xt, z0 + top + 0.05), (x1, z0 + top + 0.07),
               (x0 + 0.06 * x, z0 + top + 0.035)]
    k.plate(nm, outline, 0.014, (0, 0, 0), (1, 0, 0), (0, 0, 1))
    root = k.root_of(nm, [np.array([(x0 + x1) / 2, 0.0, z0]), np.array([(x0 + x1) / 2, 0.0, z0 + top + 0.05])])
    tip = np.array([xt, 0.0, z0 + top + 0.05])
    k.appendage(nm, "blade", side, root, tip, "line", (abs(x1 - x0), 0.014), True, 0.014, "rigid",
                path=[root, np.array([x1, 0, z0 + top + 0.03]), tip], group=name, shape=(length,),
                parent=f"forearm_{side}")


def held_weapon(k: Kit, side: str = "r", length: float = 1.3, r: float = 0.022, name: str = "staff") -> None:
    """A staff held upright in the fist but its OWN closed shell (not fused), passing through the
    hand: a large separate part, as AI meshes have them."""
    nm = f"{name}_{side}"
    hc, _hd, _tip = k.anchor["hand"][side]
    a = hc + np.array([0, -0.005, -0.5 * length])
    b = hc + np.array([0, -0.005, 0.5 * length])
    k.tube(nm, a, b, r, r, seg=16)
    k.ball(nm, b, 0.05)
    k.loose.append(nm)
    k.appendage(nm, "staff", side, hc, b + np.array([0, 0, 0.05]), "round", (2 * r, 2 * r), True, 2 * r, "prop",
                path=[hc, b], group=name, shape=(length, r), parent=f"hand_{side}", held_in=f"arm_{side}")


def halo(k: Kit, r: float = 0.15, tube: float = 0.013, lift: float = 0.10, name: str = "halo") -> None:
    """A ring floating above the head: its own closed shell, touching nothing."""
    hc, hr = k.anchor["head"]
    c = hc + np.array([0, 0.02, hr[2] + lift])
    pts = [c + r * np.array([math.cos(a), math.sin(a), 0]) for a in np.linspace(0, 2 * math.pi, 33)]
    k.path(name, pts, [tube] * len(pts), seg=10)
    k.loose.append(name)
    k.appendage(name, "halo", "c", c, pts[0], "round", (2 * r, 2 * r), True, 2 * tube, "rigid",
                path=[c, pts[0]], symmetry="centre", parent="head")


# ----------------------------------------------------------------------------- parts: head

HORN_PATHS = {   # offsets from the head centre in head radii; radii along it at r = 0.038
    "side_up": [(0.4, 0.09, 0.5), (1.0, 0.09, 0.83), (1.8, 0.09, 1.25), (2.3, 0.0, 2.0), (2.2, -0.18, 2.83)],
    "back": [(0.4, 0.2, 0.5), (0.9, 0.5, 0.8), (1.3, 1.2, 1.1), (1.5, 2.0, 1.4), (1.4, 2.7, 1.9)],
}
HORN_RADII = [1.0, 0.895, 0.684, 0.395, 0.105]


def horn(k: Kit, side: str = "l", style: str = "side_up", length: float = 1.0, r: float = 0.038, stub=None,
         name: str = "horn") -> None:
    """A horn on the head (any base with a head): style "side_up" (sideways then up, pointed) or
    "back" (swept back); stub: a broken short horn of that share of the full length (blunt)."""
    x = 1 if side == "l" else -1
    nm = f"{name}_{side}"
    hc, hr = k.anchor["head"]
    off = np.array(HORN_PATHS[style]) * hr
    off[:, 0] *= x
    off[1:] = off[0] + (off[1:] - off[0]) * length
    pts = hc + off
    if stub is None:
        pts = k.path(nm, pts, [r * f for f in HORN_RADII], smooth=True)
        root = k.root_of(nm, pts)
        tip = pts[-1]
        path = _from_root(pts, root)
    else:
        L = float(np.sum(np.linalg.norm(np.diff(pts, axis=0), axis=1)))
        start = pts[0]
        end = start + _unit(pts[1] - pts[0]) * max(stub * L, 0.03)
        k.tube(nm, start, end, r, r * 0.84)
        root = k.root_of(nm, [start, end])
        tip = end
        path = [root, end]
    k.appendage(nm, "horn", side, root, tip, "round", (2 * r, 2 * r), False, 1.6 * r, "rigid", path=path,
                group=name, shape=(style, length, r, stub), parent="head", broken=stub is not None)


def antlers(k: Kit, sides: str = "lr", tines: int = 3, length: float = 1.0, r: float = 0.022,
            name: str = "antler") -> None:
    """Branching antlers on the head: a beam going up, out and back, with tines branching off it
    (info "branches": each tine's root on the beam and its tip)."""
    hc, hr = k.anchor["head"]
    hs = float(np.mean(hr)) / 0.11
    for x, s in ((1, "l"), (-1, "r")):
        if s not in sides:
            continue
        nm = f"{name}_{s}"
        beam = [(0.04, 0.01, 0.10), (0.10, 0.03, 0.17), (0.16, 0.07, 0.25), (0.21, 0.11, 0.33), (0.24, 0.15, 0.40)]
        B = np.array([hc + hs * np.array([p[0] * x, p[1], p[2]]) for p in beam])
        B[1:] = B[0] + (B[1:] - B[0]) * length
        radii = list(np.linspace(r, 0.45 * r, len(B)))
        k.path(nm, B, radii)
        Bs = _resample(B, 50)
        rs = np.interp(np.linspace(0, 1, 50), _arc_params(B), radii)
        branches = []
        for i in range(tines):
            j = int(round((0.3 + 0.55 * i / max(tines - 1, 1)) * 49))
            d = _unit(np.array([0.35 * x, -0.65, 0.68]))
            Lt = hs * length * (0.13 - 0.02 * i)
            a = Bs[j]
            b = a + d * Lt
            k.tube(nm, a, b, 0.75 * rs[j], 0.3 * rs[j], seg=10)
            k.ball(nm, b, 0.3 * rs[j], seg=10)
            branches.append({"root": a, "tip": b, "radius": float(max(0.75 * rs[j], k.tmin / 2) * k.scale)})
        root = k.root_of(nm, B)
        k.appendage(nm, "antler", s, root, B[-1], "round", (2 * r, 2 * r), False, 2 * r, "rigid",
                    path=_from_root(B, root), group=name, shape=(tines, length, r), parent="head", branches=branches)


def ears(k: Kit, style: str = "pointed", sides: str = "lr", name: str = "ear") -> None:
    """A pair of ears on the head: "elephant" (big flat slabs on the sides) or "pointed" (on
    top, like a dog's or a cat's)."""
    hc, hr = k.anchor["head"]
    for x, s in ((1, "l"), (-1, "r")):
        if s not in sides:
            continue
        nm = f"{name}_{s}"
        if style == "elephant":
            c = hc + np.array([1.29 * hr[0] * x, 0.31 * hr[1], 0.0])
            rot = _rot("z", -0.5 * x)
            radii = (0.012, 0.10 * hr[1] / 0.13, 0.12 * hr[2] / 0.13)
            k.ball(nm, c, 1.0, radii, rot=rot)
            tip = c + rot @ np.array([0, radii[1], 0])
            thick = 0.024
            rs = (0.2, 0.024)
        else:
            c = hc + np.array([0.78 * hr[0] * x, 0.31 * hr[1], 1.22 * hr[2]])
            rot = _rot("y", 0.3 * x)
            sc = float(np.mean(hr)) / 0.103
            radii = (0.032 * sc, 0.013 * sc, 0.075 * sc)
            k.ball(nm, c, 1.0, radii, rot=rot)
            tip = c + rot @ np.array([0, 0, radii[2]])
            thick = 2 * radii[1]
            rs = (2 * radii[0], thick)
        root = k.root_of(nm, [hc, c, tip], hint=k.exit_point([hc, c, tip]))
        k.appendage(nm, "ear", s, root, tip, "slot", rs, True, max(thick, k.tmin), "chain", path=[root, c, tip],
                    group=name, shape=(style,), parent="head")


def trunk(k: Kit, length: float = 1.0, name: str = "trunk") -> None:
    """A long trunk from the front of the face (humanoid head), hanging down in front of the
    chest, the tip curling forward: a chain on the centre line."""
    hc, _hr = k.anchor["head"]
    rel = np.array([(0, -0.07, -0.03), (0, -0.14, -0.06), (0, -0.20, -0.14), (0, -0.22, -0.26), (0, -0.21, -0.38),
                    (0, -0.20, -0.48), (0, -0.23, -0.56), (0, -0.28, -0.58)])
    P = hc + rel
    P[1:] = P[1] + (P[1:] - P[1]) * length
    radii = [0.05, 0.047, 0.042, 0.036, 0.031, 0.026, 0.021, 0.016]
    P = k.path(name, P, radii, smooth=True)
    root = k.root_of(name, P)
    k.appendage(name, "trunk", "c", root, P[-1], "round", (0.094, 0.094), True, 0.06, "chain",
                path=_from_root(P, root), symmetry="centre", parent="head")


def ponytail(k: Kit, side: str = "l", r: float = 0.038, name: str = "ponytail") -> None:
    """A ponytail from the back of the head, swept to one side and lying on that shoulder
    (humanoid): its root on the centre line, its shape on one side (centre_asym)."""
    x = 1 if side == "l" else -1
    hc, hr = k.anchor["head"]
    sz = k.anchor["P"]["sh_z"]
    pts = [hc + (0, 0.5 * hr[1], 0.33 * hr[2]), hc + (0, 1.18 * hr[1], 0.17 * hr[2]),
           (0.02 * x, hc[1] + 0.17, hc[2] - 0.05), (0.06 * x, 0.13, sz + 0.15), (0.10 * x, 0.07, sz + 0.10),
           (0.15 * x, 0.02, sz + 0.085), (0.21 * x, -0.01, sz + 0.07)]
    radii = [r, r, 0.92 * r, 0.8 * r, 0.7 * r, 0.6 * r, 0.42 * r]
    pts = list(k.path(name, pts, radii, smooth=True))
    root = k.root_of(name, pts)
    k.appendage(name, "hair", "c", root, pts[-1], "round", (2 * r, 2 * r), True, 2 * r, "chain",
                path=_from_root(pts, root), symmetry="centre_asym", parent="head",
                swept=side)


# ----------------------------------------------------------------------------- parts: tails and tentacles

TAIL_PATHS = {   # (out from the middle, back, down) from a point inside the rump, metres at length 1
    "hang": [(0, 0, 0), (0, 0.14, 0.02), (0, 0.24, 0.16), (0, 0.28, 0.38), (0, 0.29, 0.50)],
    "out": [(0, 0, 0), (0.01, 0.10, 0.05), (0.06, 0.24, 0.18), (0.13, 0.36, 0.38), (0.18, 0.44, 0.60),
            (0.21, 0.48, 0.76)],
    "long": [(0, 0, 0), (0, 0.25, 0.02), (0, 0.50, 0.16), (0, 0.75, 0.36), (0, 1.0, 0.52), (0, 1.2, 0.60)],
}


def tail(k: Kit, side: str = "c", style: str = "hang", r: float = 0.035, length: float = 1.0, sway: float = 0.0,
         turns: float = 1.25, name: str = "tail") -> None:
    """A tail from the rump (any base with a rump): style "hang" (out behind then down), "out"
    (out to its side and down), "long" (a dragon's), "curl" (a helix spiral to its side). side
    "c" on the centre line (sway: how far its tip drifts to +X: then not its own mirror image),
    "l"/"r" beside the middle (two tails)."""
    sgn = -1.0 if side == "r" else 1.0
    x0 = 0.0 if side == "c" else 0.05 * sgn
    B, D = k.anchor["tail_frame"]
    X = np.array([1.0, 0, 0])
    Rr = k.anchor["rump"](x0)
    Rin = Rr - 0.06 * B
    if style == "curl":
        n = 40
        ph = np.linspace(math.pi, math.pi + turns * 2 * math.pi, n)
        rho = np.linspace(0.15, 0.05, n)
        drift = np.linspace(0.0, 0.06 * turns, n)
        rel = [(0, 0, 0), (0.02, 0.10, 0.0)] + [(0.11 + drift[i], 0.36 + rho[i] * math.cos(ph[i]),
                                                -0.08 - rho[i] * math.sin(ph[i])) for i in range(n)]
    else:
        rel = TAIL_PATHS[style]
    rel = np.array(rel, float) * length
    pts = np.array([Rin + o * sgn * X + b * B + d * D for o, b, d in rel])
    if sway:
        f = _arc_params(pts) ** 2
        pts[:, 0] += sway * f
    radii = list(np.linspace(1.05, 0.42 if style != "hang" else 0.46, len(pts)) * r)
    pts = k.path(name, pts, radii, seg=12 if style == "curl" else 16, smooth=style != "curl")
    root = k.root_of(name, pts, hint=k.exit_point(pts))
    sym = None if side != "c" else ("centre_asym" if abs(sway) > 1e-9 else "centre")
    k.appendage(name, "tail", side, root, pts[-1], "round", (2 * r, 2 * r), True, 2 * r, "chain",
                path=_from_root(pts, root, 24),
                symmetry=sym, group="tail", shape=(style, r, length, sway, turns), parent="pelvis",
                curled=style == "curl")


def tentacles(k: Kit, n: int = 6, touch: bool = True, r: float = 0.055, name: str = "tentacle") -> None:
    """n (4-6) tentacles from the lower body (creature base), radiating out and down to the
    ground, tips curling; two neighbours on the +X side bend together and touch."""
    angs = [-180 + 360 * (j + 0.5) / n for j in range(n)]
    pos = sorted([a for a in angs if 0 < a < 180])
    pair = pos[:2] if touch and len(pos) >= 2 else []
    bend_by = 0.0
    if pair:
        gap = 2.0 * math.degrees(math.asin(min(1.0, 1.5 * 0.8 * r / (2 * 0.34))))
        bend_by = max(0.0, (pair[1] - pair[0] - gap) / 2)

    def d(ang):
        t = math.radians(ang)
        return np.array([math.sin(t), -math.cos(t), 0.0])
    z = np.array([0, 0, 1.0])
    for j, a in enumerate(angs):
        bend = (bend_by if a == pair[0] else -bend_by) if a in pair else 0.0
        curl = -25.0 * (1 if a > 1e-6 else -1 if a < -1e-6 else 0)
        pts = [0.08 * d(a) + 0.78 * z, 0.20 * d(a + bend * 0.25) + 0.62 * z, 0.34 * d(a + bend) + 0.38 * z,
               0.48 * d(a + bend * 0.3) + 0.12 * z, 0.60 * d(a) + 0.05 * z, 0.66 * d(a + curl) + 0.11 * z]
        radii = [r * f for f in (1.0, 1.0, 0.8, 0.6, 0.43, 0.27)]
        nm = f"{name}_{j + 1}"
        pts = list(k.path(nm, pts, radii, smooth=True))
        side = "l" if a > 1e-6 else "r" if a < -1e-6 else "c"
        root = k.root_of(nm, pts)
        twin = None if side == "c" else f"{name}_{angs.index(min(angs, key=lambda q: abs(q + a))) + 1}"
        posed = a in pair or (-a) in pair
        sym = "centre" if side == "c" else ("pair_posed" if posed else "pair")
        k.appendage(nm, "tentacle", side, root, pts[-1], "round", (2 * r, 2 * r), False, 2 * r, "chain",
                    path=_from_root(pts, root), symmetry=sym, twin=twin, angle=a,
                    touching=bool(a in pair), parent="pelvis")


PARTS = {"bat_wing": bat_wing, "bird_wing": bird_wing, "dorsal_fin": dorsal_fin, "cape": cape, "spikes": spikes,
         "back_hair": back_hair, "sash": sash, "skirt": skirt, "cannon": cannon, "pauldron": pauldron,
         "extra_arms": extra_arms, "weapon": weapon, "shield": shield, "arm_blade": arm_blade,
         "held_weapon": held_weapon, "halo": halo, "horn": horn, "antlers": antlers, "ears": ears, "trunk": trunk,
         "ponytail": ponytail, "tail": tail, "tentacles": tentacles}


def compose(name: str = "composed", base: str = "humanoid", parts=(), voxel: float = 0.008, scale: float = 1.0,
            shells: int = 0, reset: bool = True, base_kw: dict | None = None, notes: str = "", **opts):
    """Any combination: a base (BASES) and parts, each a PARTS name or (name, {keyword: value}).
    opts: blend, noise, tris, colour, seed, preset ("ai"). Returns (object, info)."""
    k = _start(name, BASE_KIND[base], voxel, scale, reset, opts)
    BASES[base](k, **(base_kw or {}))
    done = []
    for item in parts:
        pname, kw = (item, {}) if isinstance(item, str) else (item[0], dict(item[1]))
        PARTS[pname](k, **kw)
        done.append([pname, kw])
    k.notes = notes
    return k.build(shells, {"base": base, "parts": done, **(base_kw or {})})


# ----------------------------------------------------------------------------- the zoo

def bat_wings(voxel: float = 0.008, scale: float = 1.0, shells: int = 0, thick: float = 0.024, span: float = 1.0,
              fingers: int = 3, scallop: float = 0.22, bones: bool = True, sides: str = "lr", reset: bool = True,
              **opts):
    """1. A humanoid with a mirrored PAIR of thin membrane wings from the upper back (flat
    plates a few voxels thick, long slot-shaped root, scalloped edge). sides "l" or "r": one."""
    w = dict(thick=thick, span=span, fingers=fingers, scallop=scallop, bones=bones)
    return compose("bat_wings" if sides == "lr" else f"bat_wing_{sides}", "humanoid",
                   [("bat_wing", {"side": s, **w}) for s in "lr" if s in sides], voxel, scale, shells, reset,
                   notes="Thin membrane pair: wings, not ears or tails; rooted on the back as a slot.", **opts)


def bird_wings(voxel: float = 0.008, scale: float = 1.0, shells: int = 0, t_root: float = 0.07,
               t_tip: float = 0.036, span: float = 1.0, fold: float = 1.0, feathers: int = 6, sides: str = "lr",
               rest: bool = True, reset: bool = True, **opts):
    """2. A mirrored pair of thick feathered wings (tapered wedges) folded against the body: the
    folded tip rests against the back of the thigh (contact away from the root). rest=False holds
    it clear; fold (0..1) is how far down the folded part hangs."""
    w = dict(t_root=t_root, t_tip=t_tip, span=span, fold=fold, feathers=feathers, rest=rest)
    return compose("bird_wings" if sides == "lr" else f"bird_wing_{sides}", "humanoid",
                   [("bird_wing", {"side": s, **w}) for s in "lr" if s in sides], voxel, scale, shells, reset,
                   notes="Thick wedge wings folded down the back; the tip touches the thigh: a contact, not a root.",
                   **opts)


def one_wing(voxel: float = 0.008, scale: float = 1.0, shells: int = 0, style: str = "bird", side: str = "l",
             reset: bool = True, **kw):
    """3. The winged creature with ONE wing only: the asymmetric case. style "bird" or "bat"."""
    gen = bird_wings if style == "bird" else bat_wings
    ob, info = gen(voxel=voxel, scale=scale, shells=shells, sides=side, reset=reset, **kw)
    info["name"] = ob.name = f"one_wing_{style}_{side}"
    info["params"].update(style=style)
    info["notes"] = "One wing, no twin: mirroring must neither copy it to the other side nor delete it."
    return ob, info


def dorsal_fin_body(voxel: float = 0.008, scale: float = 1.0, shells: int = 0, height: float = 0.16,
                    thick_root: float = 0.04, thick_edge: float = 0.018, spikes: int = 6, base: str = "humanoid",
                    reset: bool = True, **opts):
    """4. A fin / crest along the back ON the centre line: its root is a long line on the mirror
    plane. base "humanoid" (down the back) or "quadruped" (along the top of the back; its tail
    hangs straight here)."""
    parts = [("dorsal_fin", dict(height=height, thick_root=thick_root, thick_edge=thick_edge, spikes=spikes))]
    if base == "quadruped":
        parts = [("ears", {}), ("tail", {"style": "hang"})] + parts
    return compose("dorsal_fin" if base == "humanoid" else f"dorsal_fin_{base}", base, parts, voxel, scale, shells,
                   reset, notes="A centre-line crest: its own mirror image; the root a long line on the mirror plane.",
                   **opts)


def shoulder_cannon(voxel: float = 0.008, scale: float = 1.0, shells: int = 0, kind: str = "cannon", side: str = "l",
                    barrel_r: float = 0.05, reset: bool = True, **opts):
    """5. A thick one-sided object fused on one shoulder: an arm cannon or (kind "pauldron") a
    dome of armour. One-sided but NOT thin."""
    part = ("cannon", {"side": side, "barrel_r": barrel_r}) if kind == "cannon" else ("pauldron", {"side": side})
    return compose(f"shoulder_{kind}", "humanoid", [part], voxel, scale, shells, reset,
                   notes="Thick and one-sided: it must stay with (or be cut from) the body, never mirrored.", **opts)


def two_tails(voxel: float = 0.008, scale: float = 1.0, shells: int = 0, r: float = 0.03, turns: float = 1.25,
              reset: bool = True, **opts):
    """6. Two tails from the rump: one out to +X, one curled (a helix) on the -X side. The roots
    mirror each other, the shapes do not."""
    return compose("two_tails", "humanoid", [("tail", {"side": "l", "style": "out", "r": r, "name": "tail_l"}),
                                             ("tail", {"side": "r", "style": "curl", "r": r, "turns": turns,
                                                       "name": "tail_r"})],
                   voxel, scale, shells, reset,
                   notes="Two tails, roots side by side: two chains; their roots must not merge.", **opts)


def trunk_body(voxel: float = 0.008, scale: float = 1.0, shells: int = 0, length: float = 1.0, ears: bool = True,
               reset: bool = True, **opts):
    """7. An elephant-like head (on a humanoid) with a long trunk hanging in front of the chest,
    the tip curling forward; big flat ears."""
    parts = [("trunk", {"length": length})] + ([("ears", {"style": "elephant"})] if ears else [])
    return compose("trunk", "humanoid", parts, voxel, scale, shells, reset,
                   base_kw={"head": (0.12, 0.13, 0.13), "head_c": (0.0, -0.01, 1.70)},
                   notes="A trunk on the face front pointing down: a chain on the centre line, not a snout.", **opts)


def cape_body(voxel: float = 0.008, scale: float = 1.0, shells: int = 0, thick: float = 0.024, gap: float = 0.03,
              touch_rump: bool = True, touch_leg: str = "l", length: float = 1.0, reset: bool = True, **opts):
    """8. A thin cape hanging from the shoulders, touching the rump and the back of one calf."""
    return compose("cape", "humanoid", [("cape", dict(thick=thick, gap=gap, touch_rump=touch_rump,
                                                      touch_leg=touch_leg, length=length))],
                   voxel, scale, shells, reset,
                   notes="A thin sheet close to the back and legs, touching them: cloth, not a tail. Root: an arc over "
                         "the shoulders; the rump and calf contacts are not roots.", **opts)


def tentacles_body(voxel: float = 0.008, scale: float = 1.0, shells: int = 0, n: int = 6, touch: bool = True,
                   r: float = 0.055, reset: bool = True, **opts):
    """9. n (4-6) tentacles from the lower body instead of legs; two neighbours touch."""
    return compose("tentacles", "creature", [("tentacles", dict(n=n, touch=touch, r=r))], voxel, scale, shells, reset,
                   notes="Tentacles instead of legs: no feet; neighbours touch. Each a chain.", **opts)


def horns_asym(voxel: float = 0.008, scale: float = 1.0, shells: int = 0, stub: float = 0.35, big_side: str = "l",
               reset: bool = True, **opts):
    """10. ONE large horn (sideways then up) and a broken stub on the other side."""
    ss = "r" if big_side == "l" else "l"
    return compose("horns_asym", "humanoid", [("horn", {"side": big_side}), ("horn", {"side": ss, "stub": stub})],
                   voxel, scale, shells, reset,
                   notes="An asymmetric pair: mirroring would copy the big horn over the stub (or the stub over it).",
                   **opts)


def quadruped(voxel: float = 0.008, scale: float = 1.0, shells: int = 0, tail: bool = True, ears: bool = True,
              leg_r: float = 0.06, sway: float = 0.05, reset: bool = True, **opts):
    """11. A quadruped on all fours: four legs, neck forward, a tail swaying a little to +X
    (sway 0: straight), small ears. No arms, no T-pose."""
    parts = ([("ears", {})] if ears else []) + ([("tail", {"style": "hang", "sway": sway})] if tail else [])
    return compose("quadruped", "quadruped", parts, voxel, scale, shells, reset, base_kw={"leg_r": leg_r},
                   notes="Four legs, head forward: limbs are legs (4), the tail the only chain behind.", **opts)


def weapon_in_hand(voxel: float = 0.008, scale: float = 1.0, shells: int = 0, side: str = "r", point: str = "out",
                   length: float = 0.75, reset: bool = True, **opts):
    """12. A sword fused into one hand; pointing out it moves the T-pose hand extent."""
    return compose("weapon_in_hand", "humanoid", [("weapon", dict(side=side, point=point, length=length))],
                   voxel, scale, shells, reset, notes="A weapon fused to a hand: a prop on the hand bone.", **opts)


def forearm_shield(voxel: float = 0.008, scale: float = 1.0, shells: int = 0, side: str = "l", radius: float = 0.22,
                   reset: bool = True, **opts):
    """13. A big round shield fused to the front of one forearm: a part rooted on a limb."""
    return compose("forearm_shield", "humanoid", [("shield", dict(side=side, radius=radius))], voxel, scale, shells,
                   reset, notes="A one-sided disc on a limb: it hangs on the forearm, not the body.", **opts)


def sash_diagonal(voxel: float = 0.008, scale: float = 1.0, shells: int = 0, from_side: str = "l",
                  reset: bool = True, **opts):
    """14. A sash from one shoulder across the chest and back to the other hip."""
    return compose("sash_diagonal", "humanoid", [("sash", {"from_side": from_side})], voxel, scale, shells, reset,
                   notes="Straddles the mirror plane, not its own mirror image: mirroring makes an X of it.", **opts)


def ponytail_side(voxel: float = 0.008, scale: float = 1.0, shells: int = 0, side: str = "l", reset: bool = True,
                  **opts):
    """15. A ponytail from the back of the head swept onto one shoulder."""
    return compose("ponytail_side", "humanoid", [("ponytail", {"side": side})], voxel, scale, shells, reset,
                   notes="Root on the centre line, lying on one shoulder: mirroring copies it to the other.", **opts)


def antlers_body(voxel: float = 0.008, scale: float = 1.0, shells: int = 0, tines: int = 3, reset: bool = True,
                 **opts):
    """16. Branching antlers: a beam with tines."""
    return compose("antlers", "humanoid", [("antlers", {"tines": tines})], voxel, scale, shells, reset,
                   notes="Branching parts: one part per antler, its tines are branches, not parts.", **opts)


def hair_spikes(voxel: float = 0.008, scale: float = 1.0, shells: int = 0, n: int = 14, reset: bool = True, **opts):
    """17. A dense cluster of 10-20 hair spikes on the head."""
    return compose("hair_spikes", "humanoid", [("spikes", {"where": "head", "n": n})], voxel, scale, shells, reset,
                   notes="Many small parts close together: a cluster, mostly mirrored pairs.", **opts)


def back_spines(voxel: float = 0.008, scale: float = 1.0, shells: int = 0, n: int = 7, base: str = "humanoid",
                reset: bool = True, **opts):
    """18. A row of spines down the centre line of the back."""
    return compose("back_spines", base, [("spikes", {"where": "back", "n": n, "length": 0.09, "r": 0.02})],
                   voxel, scale, shells, reset, notes="Spines on the mirror plane: each its own mirror image.", **opts)


def skirt_body(voxel: float = 0.008, scale: float = 1.0, shells: int = 0, length: float = 0.42, reset: bool = True,
               **opts):
    """19. A skirt: a ring root round the waist, resting on both thighs (across the crotch)."""
    return compose("skirt", "humanoid", [("skirt", {"length": length})], voxel, scale, shells, reset,
                   notes="A ring root fused round the waist and touching both legs: the crotch is hidden.", **opts)


def four_arms(voxel: float = 0.008, scale: float = 1.0, shells: int = 0, reset: bool = True, **opts):
    """20. Four arms: a second pair below the first, all in T-pose."""
    return compose("four_arms", "humanoid", [("extra_arms", {})], voxel, scale, shells, reset,
                   notes="Two arm pairs: the second pair is limbs a humanoid skeleton does not have.", **opts)


def four_wings(voxel: float = 0.008, scale: float = 1.0, shells: int = 0, reset: bool = True, **opts):
    """21. Two pairs of bat wings: a big upper pair and a smaller lower pair."""
    return compose("four_wings", "humanoid",
                   [("bat_wing", {"side": s}) for s in "lr"]
                   + [("bat_wing", {"side": s, "at": 0.12, "span": 0.65, "spread": (0.75, -0.45), "fingers": 2,
                                    "root_len": 0.12, "name": "wing2"}) for s in "lr"],
                   voxel, scale, shells, reset, notes="Two wing pairs on one back: four slots close together.", **opts)


def tail_spikes(voxel: float = 0.008, scale: float = 1.0, shells: int = 0, n: int = 5, reset: bool = True, **opts):
    """22. A long hanging tail with spikes on top: parts on a part."""
    return compose("tail_spikes", "humanoid", [("tail", {"style": "hang", "r": 0.04, "length": 1.3}),
                                               ("spikes", {"where": "tail", "n": n, "length": 0.07, "r": 0.018})],
                   voxel, scale, shells, reset, notes="Spikes rooted on the tail, not the body: their parent is it.",
                   **opts)


def held_staff(voxel: float = 0.008, scale: float = 1.0, shells: int = 0, side: str = "r", halo: bool = True,
               reset: bool = True, **opts):
    """23. A staff held upright in one fist as its OWN shell (through the hand), and a halo
    floating above the head (another separate shell)."""
    parts = [("held_weapon", {"side": side})] + ([("halo", {})] if halo else [])
    return compose("held_staff", "humanoid", parts, voxel, scale, shells, reset,
                   notes="Large separate shells that are real parts: never thrown away as AI debris.", **opts)


def dragon(voxel: float = 0.008, scale: float = 1.0, shells: int = 0, reset: bool = True, **opts):
    """24. A dragon: quadruped + a pair of membrane wings + a long tail + swept-back horns."""
    return compose("dragon", "quadruped",
                   [("bat_wing", {"side": s, "at": 0.75, "spread": (0.55, -0.1), "span": 1.0, "x0": 0.11})
                    for s in "lr"]
                   + [("tail", {"style": "long", "r": 0.045}), ("horn", {"side": "l", "style": "back", "r": 0.03}),
                      ("horn", {"side": "r", "style": "back", "r": 0.03})],
                   voxel, scale, shells, reset, notes="Wings AND a tail AND horns on four legs.", **opts)


def loadout(voxel: float = 0.008, scale: float = 1.0, shells: int = 0, reset: bool = True, **opts):
    """25. An asymmetric loadout: a cannon on the left shoulder, a blade on the right forearm."""
    return compose("loadout", "humanoid", [("cannon", {"side": "l"}), ("arm_blade", {"side": "r"})], voxel, scale,
                   shells, reset, notes="Different one-sided parts on each side: neither side can be mirrored.",
                   **opts)


def winged_tail(voxel: float = 0.008, scale: float = 1.0, shells: int = 0, reset: bool = True, **opts):
    """26. A humanoid with bat wings AND a tail (the wings move the pelvis guess the tail
    detection relies on)."""
    return compose("winged_tail", "humanoid", [("bat_wing", {"side": "l"}), ("bat_wing", {"side": "r"}),
                                               ("tail", {"style": "hang"})],
                   voxel, scale, shells, reset, notes="Wings and a tail on one body.", **opts)


def naga(voxel: float = 0.008, scale: float = 1.0, shells: int = 0, coil_side: str = "l", reset: bool = True,
         **opts):
    """27. A naga: a humanoid upper body on a snake's lower body coiled on the ground."""
    return compose("naga", "naga", [], voxel, scale, shells, reset, base_kw={"coil_side": coil_side},
                   notes="No legs: the lower body is one big chain coiled to one side.", **opts)


def chibi(voxel: float = 0.008, scale: float = 1.0, shells: int = 0, reset: bool = True, **opts):
    """28. Chibi proportions (a big head) with pointed ears."""
    return compose("chibi", "chibi", [("ears", {"style": "pointed"})], voxel, scale, shells, reset,
                   notes="The head a third of the height: proportions a joint guess must not assume.", **opts)


def back_hair_body(voxel: float = 0.008, scale: float = 1.0, shells: int = 0, length: float = 0.55,
                   reset: bool = True, **opts):
    """29. Long hair lying along the back (fused to it all the way down)."""
    return compose("back_hair", "humanoid", [("back_hair", {"length": length})], voxel, scale, shells, reset,
                   notes="Hair resting on the back: root and contact are one long seam.", **opts)


# (names kept from the first zoo: dorsal_fin, trunk, cape, tentacles are also part functions)
ZOO = {
    "bat_wings": bat_wings,
    "bird_wings": bird_wings,
    "one_wing": one_wing,
    "dorsal_fin": dorsal_fin_body,
    "shoulder_cannon": shoulder_cannon,
    "two_tails": two_tails,
    "trunk": trunk_body,
    "cape": cape_body,
    "tentacles": tentacles_body,
    "horns_asym": horns_asym,
    "quadruped": quadruped,
    "weapon_in_hand": weapon_in_hand,
    "forearm_shield": forearm_shield,
    "sash_diagonal": sash_diagonal,
    "ponytail_side": ponytail_side,
    "antlers": antlers_body,
    "hair_spikes": hair_spikes,
    "back_spines": back_spines,
    "skirt": skirt_body,
    "four_arms": four_arms,
    "four_wings": four_wings,
    "tail_spikes": tail_spikes,
    "held_staff": held_staff,
    "dragon": dragon,
    "loadout": loadout,
    "winged_tail": winged_tail,
    "naga": naga,
    "chibi": chibi,
    "back_hair": back_hair_body,
}
