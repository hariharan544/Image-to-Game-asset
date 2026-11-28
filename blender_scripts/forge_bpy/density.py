"""Detail map: where a retopology needs more quads (and where it can save them).

Per vertex of the dense AI mesh, a 0..1 "detail" score from how sharply the surface bends
at the scale of a few quads: eye sockets, the mouth line, nostrils, ear rims, nail and hoof
tips score high; a belly or a back scores low. Pure numpy on the mesh arrays (a 5M-triangle
mesh takes a few seconds).

The score is written as a colour attribute for Quad Remesher's density painting
(see to_qr_colours) and can be shown to the director as a heat map.
"""

from __future__ import annotations

import math

import numpy as np


def _arrays(me):
    nv, ne = len(me.vertices), len(me.edges)
    co = np.empty(nv * 3, np.float32)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3).astype(np.float64)
    nrm = np.empty(nv * 3, np.float32)
    me.vertices.foreach_get("normal", nrm)
    nrm = nrm.reshape(-1, 3).astype(np.float64)
    ev = np.empty(ne * 2, np.int32)
    me.edges.foreach_get("vertices", ev)
    return co, nrm, ev.reshape(-1, 2).astype(np.int64)


def _smooth(values: np.ndarray, ev: np.ndarray, n: int, iterations: int) -> np.ndarray:
    """Average each vertex with its edge neighbours `iterations` times (graph Laplacian)."""
    a, b = ev[:, 0], ev[:, 1]
    deg = np.bincount(a, minlength=n) + np.bincount(b, minlength=n)
    deg = np.maximum(deg, 1).astype(np.float64)
    v = values.astype(np.float64)
    for _ in range(iterations):
        acc = np.bincount(a, weights=v[b], minlength=n) + np.bincount(b, weights=v[a], minlength=n)
        v = 0.5 * v + 0.5 * acc / deg
    return v


def detail_score(me, scales=(6, 30), feature_iterations: int = 3) -> np.ndarray:
    """Detail at two sizes, combined: small sharp features (eyes, mouth, nails) and broad
    forms (chest and belly muscles, shoulder blades) both pull quads towards them."""
    out = None
    for s in scales:
        part = _detail_one(me, s, feature_iterations + s // 6)
        out = part if out is None else np.maximum(out, part)
    return out if out is not None else np.zeros(len(me.vertices))


def _detail_one(me, scale_iterations: int, feature_iterations: int) -> np.ndarray:
    """0..1 per vertex. Curvature is measured on a slightly smoothed copy of the normals
    (so sculpt noise and fur strokes do not count), then spread a little so a feature gets
    a band of density around it, not a single vertex row."""
    co, nrm, ev = _arrays(me)
    n = len(co)
    if n == 0 or len(ev) == 0:
        return np.zeros(n)
    # smooth the normals a little: curvature at the scale of the future quads
    sn = np.stack([_smooth(nrm[:, k], ev, n, scale_iterations) for k in range(3)], axis=1)
    sn /= np.maximum(np.linalg.norm(sn, axis=1, keepdims=True), 1e-12)
    a, b = ev[:, 0], ev[:, 1]
    d = co[b] - co[a]
    length = np.maximum(np.linalg.norm(d, axis=1), 1e-12)
    # bend per unit length: change of normal across the edge / edge length (absolute curvature)
    bend = np.linalg.norm(sn[b] - sn[a], axis=1) / length
    curv = (np.bincount(a, weights=bend, minlength=n) + np.bincount(b, weights=bend, minlength=n))
    cnt = np.maximum(np.bincount(a, minlength=n) + np.bincount(b, minlength=n), 1)
    curv = curv / cnt
    # scale-free: express it relative to the object size, then robustly normalise
    size = float(np.linalg.norm(co.max(axis=0) - co.min(axis=0))) or 1.0
    curv *= size
    curv = _smooth(curv, ev, n, feature_iterations)
    lo, hi = np.percentile(curv, 50), np.percentile(curv, 98)
    return np.clip((curv - lo) / max(hi - lo, 1e-12), 0.0, 1.0)


def write_attribute(me, score: np.ndarray, name: str, colours: np.ndarray) -> None:
    """Store per-vertex RGBA colours as a point colour attribute and make it active."""
    attr = me.color_attributes.get(name)
    if attr is not None:
        me.color_attributes.remove(attr)
    attr = me.color_attributes.new(name=name, type="FLOAT_COLOR", domain="POINT")
    attr.data.foreach_set("color", colours.astype(np.float32).ravel())
    me.color_attributes.active_color = attr
    try:
        me.color_attributes.render_color_index = me.color_attributes.find(name)
    except (AttributeError, TypeError):
        pass


def heat_colours(score: np.ndarray) -> np.ndarray:
    """Blue (flat, few quads) -> red (detail, many quads), for showing the director."""
    s = score[:, None]
    blue = np.array([0.05, 0.2, 1.0, 1.0])
    red = np.array([1.0, 0.1, 0.05, 1.0])
    return (1 - s) * blue + s * red


# ----------------------------------------------------------------------------- Quad Remesher

QR_ATTR = "QR_Density"


def qr_density(score: np.ndarray, strength: float = 0.8) -> np.ndarray:
    """Detail score 0..1 -> Quad Remesher density multiplier: flat areas fewer quads,
    detailed areas more (strength 0 = uniform, 1 = about 0.3x .. 3x)."""
    k = 1.75 * float(np.clip(strength, 0.0, 1.0))
    return np.clip(2.0 ** ((score * 2.0 - 1.0) * k), 0.25, 4.0)


def qr_colours(density: np.ndarray) -> np.ndarray:
    """Quad Remesher's own colour code (from its density brush): white = 1x,
    red (1,0,0) = 4x denser, cyan (0,1,1) = 4x sparser, linear in between."""
    out = np.ones((len(density), 4))
    up = density >= 1.0
    n = (density[up] - 1.0) / 3.0
    out[up, 1] = 1.0 - n
    out[up, 2] = 1.0 - n
    n = ((1.0 / density[~up]) - 1.0) / 3.0
    out[~up, 0] = 1.0 - n
    return np.clip(out, 0.0, 1.0)


def write_qr_density(me, score: np.ndarray, strength: float = 0.8, make_active: bool = True,
                     factor=None) -> None:
    """Corner-domain byte colours in sRGB, as Quad Remesher's density brush paints them.
    factor: optional per-vertex multiplier (importance of the body region)."""
    dens = qr_density(score, strength)
    if factor is not None:
        dens = np.clip(dens * factor, 0.25, 4.0)
    # Quad Remesher reads the colour as an EDGE-length factor (measured on the director's
    # bull: the head took 66% when densities were written directly), so a density d needs
    # edges sqrt(d) shorter
    point = qr_colours(np.sqrt(dens))
    nl = len(me.loops)
    lv = np.empty(nl, np.int32)
    me.loops.foreach_get("vertex_index", lv)
    attr = me.color_attributes.get(QR_ATTR)
    if attr is not None:
        me.color_attributes.remove(attr)
    keep_active = me.color_attributes.active_color_name
    keep_render = me.color_attributes.render_color_index
    attr = me.color_attributes.new(name=QR_ATTR, type="BYTE_COLOR", domain="CORNER")
    attr.data.foreach_set("color_srgb", point[lv].astype(np.float32).ravel())
    if not make_active and keep_active:   # leave the model's own colour layer in charge
        me.color_attributes.active_color_name = keep_active
        me.color_attributes.render_color_index = keep_render
        return
    me.color_attributes.active_color = attr
    try:
        me.color_attributes.render_color_index = me.color_attributes.find(QR_ATTR)
    except (AttributeError, TypeError):
        pass


def only_qr_density(me) -> bool:
    """Before remeshing: QR's density map must be the only (first, active) colour layer."""
    if QR_ATTR not in me.color_attributes:
        return False
    for a in [a for a in me.color_attributes if a.name != QR_ATTR]:
        me.color_attributes.remove(a)
    attr = me.color_attributes[QR_ATTR]
    me.color_attributes.active_color = attr
    try:
        me.color_attributes.render_color_index = 0
    except (AttributeError, TypeError):
        pass
    return True


# ----------------------------------------------------------------------------- shape check

STRICT_ATTR = "forge_strict"     # per-vertex tolerance factor (< 1 = stricter), e.g. the face


def write_strict(me, factor: np.ndarray) -> None:
    a = me.attributes.get(STRICT_ATTR)
    if a is not None:
        me.attributes.remove(a)
    a = me.attributes.new(STRICT_ATTR, "FLOAT", "POINT")
    a.data.foreach_set("value", factor.astype(np.float32))


def shape_loss(src_me, low_me, tol_rel: float = 0.008, max_samples: int = 300_000) -> dict:
    """How much of the original surface the new mesh lost (a thin tail collapsed, a tuft or
    a nail tip cut off): distance from every original vertex to the new surface.
    Returns {"mask": bool per original vertex, "lost_ratio", "max_rel"}."""
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    n = len(src_me.vertices)
    co = np.empty(n * 3, np.float32)
    src_me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    size = float(np.linalg.norm(co.max(axis=0) - co.min(axis=0))) or 1.0
    lv = [v.co.copy() for v in low_me.vertices]
    tree = BVHTree.FromPolygons(lv, [tuple(p.vertices) for p in low_me.polygons])
    # a dense AI mesh has millions of points: test an even sample, then grow the hits back
    stride = max(1, n // max_samples)
    idx = np.arange(0, n, stride)
    dist = np.empty(len(idx))
    for j, i in enumerate(idx):
        hit = tree.find_nearest(Vector(co[i]))
        dist[j] = hit[3] if hit[0] is not None else size
    rel = dist / size
    # stricter where it matters (the face: a flattened mouth corner or lid crease counts)
    scale = np.ones(len(idx))
    strict_region = np.zeros(len(idx), bool)
    a = src_me.attributes.get(STRICT_ATTR)
    if a is not None and a.domain == "POINT" and len(a.data) == n:
        sv = np.empty(n, np.float32)
        a.data.foreach_get("value", sv)
        scale = sv[idx].astype(np.float64)
        strict_region = scale < 0.999
    thin = rel > tol_rel
    strict = rel > tol_rel * scale
    grow = int(2 * stride ** 0.5) + 1

    def full(sel):
        m = np.zeros(n, bool)
        m[idx[sel]] = True
        if stride > 1 and m.any():
            m = _dilate(m, src_me, grow)
        return m
    face_n = int(strict_region.sum())
    return {"mask": full(strict), "mask_thin": full(thin),
            "lost_ratio": float(thin.mean()) if len(rel) else 0.0,
            "face_lost": float((strict & strict_region).sum()) / face_n if face_n else 0.0,
            "max_rel": float(rel.max()) if len(rel) else 0.0}


def _dilate(mask: np.ndarray, me, rings: int) -> np.ndarray:
    ev = np.empty(len(me.edges) * 2, np.int32)
    me.edges.foreach_get("vertices", ev)
    ev = ev.reshape(-1, 2)
    m = mask.copy()
    for _ in range(rings):
        grow = m[ev[:, 0]] | m[ev[:, 1]]
        m[ev[grow, 0]] = True
        m[ev[grow, 1]] = True
    return m


def qr_factors(col: np.ndarray) -> np.ndarray:
    """Inverse of qr_colours: Quad Remesher's edge factor from its colour code (rows r, g, b, ...)."""
    col = np.asarray(col, np.float64)
    out = np.ones(len(col))
    up = (col[:, 0] >= 0.999) & ((col[:, 1] < 0.999) | (col[:, 2] < 0.999))
    out[up] = 1.0 + 3.0 * (1.0 - np.minimum(col[up, 1], col[up, 2]))
    down = col[:, 0] < 0.999
    out[down] = 1.0 / (1.0 + 3.0 * (1.0 - col[down, 0]))
    return out


def vertex_factors(me) -> np.ndarray:
    """Per-vertex edge factor of the detail map (the densest corner), 1 where there is none."""
    n, nl = len(me.vertices), len(me.loops)
    attr = me.color_attributes.get(QR_ATTR)
    out = np.ones(n)
    if attr is None or not nl:
        return out
    col = np.empty(nl * 4, np.float32)
    attr.data.foreach_get("color_srgb", col)
    lv = np.empty(nl, np.int32)
    me.loops.foreach_get("vertex_index", lv)
    out[:] = 0.0
    np.maximum.at(out, lv, qr_factors(col.reshape(-1, 4)))
    out[out <= 0] = 1.0
    return out


def boost(me, mask: np.ndarray, rings: int = 3, edge_factor=4.0) -> int:
    """Paint the masked area (grown by a few rings) denser. edge_factor is Quad Remesher's own
    scale (edges that many times shorter): 4 = full red = 16x the quads, 2 = 4x the quads.
    A per-vertex array paints each vertex with its own factor."""
    mask = _dilate(mask, me, rings)
    attr = me.color_attributes.get(QR_ATTR)
    nl = len(me.loops)
    if attr is None:
        attr = me.color_attributes.new(name=QR_ATTR, type="BYTE_COLOR", domain="CORNER")
        attr.data.foreach_set("color_srgb", np.ones(nl * 4, np.float32))
    col = np.empty(nl * 4, np.float32)
    attr.data.foreach_get("color_srgb", col)
    col = col.reshape(-1, 4)
    lv = np.empty(nl, np.int32)
    me.loops.foreach_get("vertex_index", lv)
    hit = mask[lv]
    if np.ndim(edge_factor):
        col[hit] = qr_colours(np.asarray(edge_factor, np.float64)[lv[hit]])
    else:
        col[hit] = qr_colours(np.array([float(edge_factor)]))[0]
    attr.data.foreach_set("color_srgb", col.ravel())
    return int(mask.sum())



def asymmetry(me, tol_rel: float = 0.006, max_samples: int = 60_000) -> float:
    """Share of the surface that has no mirror twin across X = 0 (a notch in one ear, a scar,
    a prop on one side). Mirror symmetry in the remesher would copy such details to the
    other side, so it is only used when this is close to 0."""
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    n = len(me.vertices)
    if n == 0:
        return 0.0
    co = np.empty(n * 3, np.float32)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    size = float(np.linalg.norm(co.max(axis=0) - co.min(axis=0))) or 1.0
    tree = BVHTree.FromPolygons([v.co.copy() for v in me.vertices], [tuple(p.vertices) for p in me.polygons])
    idx = np.arange(0, n, max(1, n // max_samples))
    off = 0
    for i in idx:
        x, y, z = co[i]
        hit = tree.find_nearest(Vector((-x, y, z)))
        if hit[0] is None or hit[3] > tol_rel * size:
            off += 1
    return off / len(idx)



# ----------------------------------------------------------------------------- budget by region

# how much each body region deserves, relative to its surface (games: faces are seen close
# up and animate; hands gesture; joints bend; a belly or a back is a big smooth area)
REGION_WEIGHT = {"head": 1.5, "neck": 1.15, "hand": 1.5, "foot": 1.15, "ball": 1.15,
                 "pelvis": 0.7, "upperarm": 0.85, "lowerarm": 0.9, "thigh": 0.8, "calf": 0.9}
JOINT_WEIGHT = 1.35
JOINTS = ("lowerarm", "calf", "upperarm", "thigh", "hand", "foot", "neck")   # bone heads = bends


def region_of(key: str) -> str:
    base = key.rsplit("_", 1)[0] if key.endswith(("_l", "_r")) else key
    return base


REGION_NAMES = ["body", "head", "arms", "hands", "legs", "feet"]
REGION_W = {"body": 0.7, "head": 1.5, "arms": 0.9, "hands": 1.5, "legs": 0.85, "feet": 1.15}


def region_labels(V: np.ndarray, J: dict) -> np.ndarray:
    """Body region per point from the body layout (not the nearest bone: on a round cartoon
    torso the chest is nearest to the neck bone and would count as head).
    head: above the neck (inside the shoulders); arms/hands: out past the shoulders;
    legs/feet: below the hips and out to the side of the centre line; body: the rest."""
    def p(k, i=0):
        return np.array(J[k][i][:])
    neck_z = p("neck")[2]
    sh_x = abs(p("upperarm_l")[0])
    wr_x = abs(p("hand_l")[0])
    hip_z = p("thigh_l")[2]
    ank_z = p("foot_l")[2]
    leg_x = abs(p("thigh_l")[0])
    ax = np.abs(V[:, 0])
    lab = np.zeros(len(V), np.int8)                                   # body
    H = float(V[:, 2].max() - V[:, 2].min()) or 1.0
    # arms are out past the shoulders AND at arm height: ears, horns and hair beside a wide
    # head stay head (a straight |x| cut sliced through their roots)
    arm = (ax > sh_x * 1.05) & (V[:, 2] < neck_z + 0.03 * H)
    # a hand raised above the neck is still an arm: past the shoulders and nearer an arm bone
    # than the head
    cand = (ax > sh_x * 1.05) & ~arm
    if cand.any():
        def seg_d(P, a, b):
            ab = b - a
            t = np.clip(((P - a) @ ab) / max(float(ab @ ab), 1e-12), 0.0, 1.0)
            return np.linalg.norm(P - (a + t[:, None] * ab), axis=1)
        P = V[cand]
        d_arm = np.full(len(P), np.inf)
        for k in ("upperarm_l", "lowerarm_l", "hand_l", "upperarm_r", "lowerarm_r", "hand_r"):
            if k in J:
                d_arm = np.minimum(d_arm, seg_d(P, p(k, 0), p(k, 1)))
        d_head = seg_d(P, p("head", 0), p("head", 1)) if "head" in J else np.full(len(P), np.inf)
        idx = np.nonzero(cand)[0]
        arm[idx[d_arm < d_head]] = True
    lab[(V[:, 2] > neck_z) & ~arm] = 1                                # head
    lab[arm] = 2
    lab[arm & (ax > wr_x)] = 3                                        # hands
    leg = (V[:, 2] < hip_z) & (ax > 0.35 * leg_x) & ~arm
    lab[leg] = 4
    lab[leg & (V[:, 2] < ank_z + 0.02 * (V[:, 2].max() - V[:, 2].min()))] = 5   # feet
    return lab


def region_factors(V: np.ndarray, J: dict):
    """Per-vertex importance multiplier and region label, from the guessed joints."""
    lab = region_labels(V, J)
    f = np.array([REGION_W[n] for n in REGION_NAMES])[lab]
    # rings of extra quads where joints bend
    H = float(V[:, 2].max() - V[:, 2].min()) or 1.0
    for k in ("upperarm_l", "upperarm_r", "lowerarm_l", "lowerarm_r", "hand_l", "hand_r",
              "thigh_l", "thigh_r", "calf_l", "calf_r", "foot_l", "foot_r", "neck"):
        if k in J:
            near = np.linalg.norm(V - np.array(J[k][0][:]), axis=1) < 0.06 * H
            f[near] = np.maximum(f[near], JOINT_WEIGHT)
    return f, lab, REGION_NAMES


def region_tris(low_obj, J: dict) -> dict:
    """Triangles per body region of the new mesh (for the director's budget view)."""
    me = low_obj.data
    me.calc_loop_triangles()
    n = len(me.loop_triangles)
    if n == 0:
        return {}
    tv = np.empty(n * 3, np.int32)
    me.loop_triangles.foreach_get("vertices", tv)
    co = np.empty(len(me.vertices) * 3, np.float32)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3).astype(np.float64)
    cen = co[tv.reshape(-1, 3)].mean(axis=1)
    m = np.array(low_obj.matrix_world)
    P = cen @ m[:3, :3].T + m[:3, 3]
    lab = region_labels(P, J)
    out: dict = {}
    for i, name in enumerate(REGION_NAMES):
        n_i = int((lab == i).sum())
        if n_i:
            out[name] = n_i
    return out


# ----------------------------------------------------------------------------- fit to original

FACING = 0.2         # a hit on the original counts only if its face turns at most ~78 deg from the vertex
STAND_FOR = 1.5      # a ray hit this many times farther than the nearest surface point is not the
                     # surface the vertex stands for: the ray ran on down a groove narrower than the
                     # quads, or onto a wall that faces across it
FIT_SLACK = 0.05     # ... beyond that, a hit may lie this share of the vertex's edge farther (chord size)
FIT_CHECK = 0.05     # a move longer than this share of the vertex's edge (beyond a face's chord error)
                     # is checked: it must bring the faces round the vertex closer to the original,
                     # or it is put back


def _polys(me) -> list:
    """Every face of a mesh as a tuple of its vertex indices."""
    nf, nl = len(me.polygons), len(me.loops)
    ls = np.empty(nf, np.int64)
    me.polygons.foreach_get("loop_start", ls)
    lt = np.empty(nf, np.int64)
    me.polygons.foreach_get("loop_total", lt)
    lv = np.empty(nl, np.int64)
    me.loops.foreach_get("vertex_index", lv)
    return [tuple(int(x) for x in lv[s0:s0 + t]) for s0, t in zip(ls, lt)]


def _vertex_faces(polys: list, n: int) -> list:
    out: list = [[] for _ in range(n)]
    for fi, f in enumerate(polys):
        for v in f:
            out[v].append(fi)
    return out


def _mean_edge(co: np.ndarray, ev: np.ndarray) -> np.ndarray:
    """Per vertex: the mean length of its edges."""
    n = len(co)
    a, b = ev[:, 0], ev[:, 1]
    deg = np.maximum(np.bincount(a, minlength=n) + np.bincount(b, minlength=n), 1)
    el = np.linalg.norm(co[a] - co[b], axis=1)
    return (np.bincount(a, weights=el, minlength=n) + np.bincount(b, weights=el, minlength=n)) / deg


def _face(co: np.ndarray, f) -> tuple:
    """One face (its corner indices in order) as (corners, unit normal, sample points: its middle
    and the middle of each side, its longest side), in mathutils vectors (small and fast)."""
    from mathutils import Vector
    P = [Vector(co[v]) for v in f]
    n = Vector((0.0, 0.0, 0.0))
    for a, b in zip(P, P[1:] + P[:1]):
        n += a.cross(b)
    if n.length > 0:
        n.normalize()
    mid = sum(P, Vector((0.0, 0.0, 0.0))) / len(P)
    sides = [(a, b) for a, b in zip(P, P[1:] + P[:1])]
    return P, n, [mid] + [(a + b) * 0.5 for a, b in sides], max((a - b).length for a, b in sides) or 1e-9


def _patch_out(tree, co: np.ndarray, faces: list) -> tuple:
    """From samples on the faces to the original: the distance to the nearest original point, and
    the original point under each sample (along the face's normal, out or in, within the face's
    size; else the nearest point). A face that bridges a groove has the groove floor under it."""
    out, under = [], []
    for f in faces:
        _P, nv, samples, reach = _face(co, f)
        for pv in samples:
            near = tree.find_nearest(pv)
            if near[0] is None:
                continue
            out.append(near[3])
            best = None
            for s in (1.0, -1.0):
                h = tree.ray_cast(pv, nv * s, reach)
                if h[0] is not None and h[1].dot(nv) > 0.0 and (best is None or h[3] < best[3]):
                    best = h
            under.append(tuple((best or near)[0]))
    return out, under


def _patch_back(co: np.ndarray, faces: list, pts: list) -> list:
    """From original points back to the faces: the distance to the nearest of the faces."""
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    ids: dict = {}
    tris = []
    for f in faces:
        k = [ids.setdefault(int(v), len(ids)) for v in f]
        tris += [(k[0], k[j], k[j + 1]) for j in range(1, len(k) - 1)]
    if not tris or not pts:
        return []
    local = BVHTree.FromPolygons([Vector(co[v]) for v in ids], tris)
    return [local.find_nearest(Vector(p))[3] for p in pts]


def _rms(gaps) -> float:
    return float(np.sqrt(np.mean(np.square(gaps))))


def _closer(tree, before: np.ndarray, after: np.ndarray, faces: list) -> bool:
    """True when the faces lie closer to the original in the `after` shape than `before`,
    measured both ways at face samples (from the faces to the original, and from the original
    under the faces back to them) on the same original points in both shapes. Both ways: a
    face that bridges a groove is far from the groove floor under it, a face sunk into a lip is
    far from the lip above it - a move that trades one for a bigger other is not closer. Each
    way is the root-mean-square gap: every sample counts, a big gap (a dent is one place) more
    than many small ones."""
    oa, ua = _patch_out(tree, before, faces)
    ob, ub = _patch_out(tree, after, faces)
    pts = ua + ub
    if not oa or not ob or not pts:
        return False
    ea = _rms(oa) + _rms(_patch_back(before, faces, pts))
    eb = _rms(ob) + _rms(_patch_back(after, faces, pts))
    return eb < ea


def _dug(tree, local, p, up, lim: float) -> float:
    """How far the sample p of new faces lies dug into the original, measured both ways: its
    distance to the original surface nearest to it when it lies behind that (and that faces
    the way `up` does: not the far side of a thin part), and how far the original surface above
    it (along `up`: from inside, the first surface met faces the way the ray goes) lies from
    the new faces (`local`, a tree of them). In a narrow groove or a tight join the nearest
    surface can be a wall right beside the sample while the lip above lies well off the faces:
    the eye sees the lip."""
    worst = 0.0
    h = tree.find_nearest(p, lim)
    if h[0] is not None and h[1].dot(up) > 0.0 and (p - h[0]).dot(h[1]) < 0.0:
        worst = h[3]
    r = tree.ray_cast(p, up, lim)
    if r[0] is not None and r[1].dot(up) > 0.0:
        back = local.find_nearest(r[0])
        if back[0] is not None:
            worst = max(worst, back[3])
    return worst


def _local_tree(corner_lists) -> "object | None":
    """A tree of a few faces given as lists of corner points (to measure back to them)."""
    from mathutils.bvhtree import BVHTree
    pts, tris = [], []
    for cs in corner_lists:
        k0 = len(pts)
        pts += [c.copy() for c in cs]
        tris += [(k0, k0 + j, k0 + j + 1) for j in range(1, len(cs) - 1)]
    return BVHTree.FromPolygons(pts, tris) if tris else None


SPOKE = (0.15, 0.3, 0.45, 0.6, 0.75, 0.9)   # samples along each line from a moved point to its faces' other corners


def _dig(tree, co: np.ndarray, v: int, faces: list) -> float:
    """How deep the faces round point v dig into the original: the deepest of samples on them
    (each face's middle, and points along each line from v to the face's other corners - where
    a face sunk into a groove meets the groove's rim), measured both ways (_dug)."""
    from mathutils import Vector
    parts = [_face(co, f) for f in faces]
    local = _local_tree([P for P, _n, _s, _r in parts])
    if local is None:
        return 0.0
    pv = Vector(co[v])
    worst = 0.0
    for f, (P, nv, samples, reach) in zip(faces, parts):
        pts = [samples[0]] + [pv.lerp(c, t) for c, w in zip(P, f) if w != v for t in SPOKE]
        for p in pts:
            worst = max(worst, _dug(tree, local, p, nv, reach))
    return worst


def _keep_closer(tree, start: np.ndarray, co: np.ndarray, polys: list, vf: list, edge: np.ndarray,
                 tol: float, check: float = FIT_CHECK) -> tuple:
    """Every vertex that moved by more than `check` of its edge from `start` keeps its move
    only if its faces end up closer to the original (both ways) than with the vertex put back,
    and dig no deeper into it than tol (nor deeper than they did): a vertex pulled into a groove
    narrower than its faces takes them down into the lips on both sides - that is a notch,
    however much nearer the groove floor gets. Otherwise it is put back. One vertex at a time,
    in vertex order, each judged among its neighbours as they are by then. Returns
    (coordinates, how many were put back)."""
    out = co.copy()
    back = 0
    far = np.nonzero(np.linalg.norm(co - start, axis=1) > check * edge)[0]
    for v in far:
        faces = [polys[f] for f in vf[v]]
        if not faces:
            continue
        was = out.copy()
        was[v] = start[v]
        if _dig(tree, out, v, faces) > max(tol, _dig(tree, was, v, faces)) or not _closer(tree, was, out, faces):
            out[v] = start[v]
            back += 1
    return out, back


def conform(low_me, src_me, max_rel: float = 0.04, relax: int = 2, tree=None, tol_rel: float = 0.0012) -> dict:
    """Move every vertex of the new mesh onto the original surface. After a SYMMETRIC remesh
    this puts one-sided details back (a notch in one ear) and pulls the mesh into grooves at
    least as wide as its quads. Projection along the vertex normal (both ways) keeps the quads
    even; where that finds nothing (the notch: there is no surface along the normal), or only a
    surface much farther than the nearest one, the nearest surface point is used. A light relax
    keeps the quads from bunching, then they are projected again. Last, every move longer than
    a chord must have brought the faces round the vertex closer to the original, measured both
    ways, without digging them more than tol_rel of the size into it (a vertex pulled into a
    groove narrower than its faces sinks them into the lips on both sides: put back - carve
    cuts such a crease along the edges instead, as a line that tapers where the groove fades)."""
    from mathutils import Vector
    tree = tree or source_tree(src_me)
    n = len(low_me.vertices)
    if n == 0:
        return {"moved": 0, "put_back": 0}
    co = np.empty(n * 3, np.float32)
    low_me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3).astype(np.float64)
    size = float(np.linalg.norm(co.max(axis=0) - co.min(axis=0))) or 1.0
    limit = max_rel * size
    ev = np.empty(len(low_me.edges) * 2, np.int32)
    low_me.edges.foreach_get("vertices", ev)
    ev = ev.reshape(-1, 2).astype(np.int64)
    a, b = ev[:, 0], ev[:, 1]
    deg = np.maximum(np.bincount(a, minlength=n) + np.bincount(b, minlength=n), 1)[:, None]

    # each vertex may only move onto the original surface it stands for: one that faces the
    # same way, and not farther than a few of its own edges (next to a thin ear or in the gap
    # at a horn root, the nearest hit can be the far side of the sheet or another wall)
    edge = _mean_edge(co, ev)
    reach = np.minimum(4.0 * edge, limit)
    slack = FIT_SLACK * edge

    def project(pts, nrm):
        out = pts.copy()
        moved = 0
        for i in range(n):
            p = Vector(pts[i])
            d = Vector(nrm[i])
            lim = float(reach[i]) or limit
            best = None
            for s in (1.0, -1.0):
                hit = tree.ray_cast(p, d * s, lim)
                if hit[0] is not None and hit[1].dot(d) > FACING and (best is None or hit[3] < best[1]):
                    best = (hit[0], hit[3])
            near = tree.find_nearest(p, lim)
            if best is not None and near[0] is not None and best[1] > STAND_FOR * near[3] + slack[i]:
                best = None             # down a narrow groove or onto its far wall: not this vertex's surface
            if best is None and near[0] is not None and near[1].dot(d) > 0.0:
                best = (near[0], near[3])
            if best is not None:
                out[i] = best[0][:]
                moved += best[1] > 1e-6 * size
        return out, moved

    def normals(pts):
        low_me.vertices.foreach_set("co", pts.astype(np.float32).ravel())
        low_me.update()
        nr = np.empty(n * 3, np.float32)
        low_me.vertices.foreach_get("normal", nr)
        return nr.reshape(-1, 3).astype(np.float64)

    start = co.copy()
    co, moved = project(co, normals(co))
    for _ in range(relax):
        avg = (np.stack([np.bincount(a, weights=co[b, k], minlength=n) + np.bincount(b, weights=co[a, k], minlength=n)
                         for k in range(3)], axis=1)) / deg
        nrm = normals(co)
        delta = avg - co
        delta -= nrm * (delta * nrm).sum(axis=1, keepdims=True)   # slide along the surface only
        co = co + 0.5 * delta
        co, _m = project(co, normals(co))
    polys = _polys(low_me)
    co, back = _keep_closer(tree, start, co, polys, _vertex_faces(polys, n), edge, tol_rel * size)
    low_me.vertices.foreach_set("co", co.astype(np.float32).ravel())
    low_me.update()
    return {"moved": int(moved), "put_back": int(back)}


# ----------------------------------------------------------------------------- carve creases

def source_tree(src_me):
    from mathutils.bvhtree import BVHTree
    return BVHTree.FromPolygons([v.co.copy() for v in src_me.vertices],
                                [tuple(p.vertices) for p in src_me.polygons])


def _poly_strict(src_me) -> "np.ndarray | None":
    """Strict factor per source polygon (from its first vertex), or None without the attribute."""
    a = src_me.attributes.get(STRICT_ATTR)
    if a is None or a.domain != "POINT":
        return None
    sv = np.empty(len(src_me.vertices), np.float32)
    a.data.foreach_get("value", sv)
    ls = np.empty(len(src_me.polygons), np.int32)
    src_me.polygons.foreach_get("loop_start", ls)
    lv = np.empty(len(src_me.loops), np.int32)
    src_me.loops.foreach_get("vertex_index", lv)
    return sv[lv[ls]]


def _cut_beside(tree, v, up, lim: float) -> float:
    """How deep the faces round a carved point cut into the original beside the groove: the
    deepest of samples on them (each face's middle and points along each line from the point to
    the face's other corners - where the V meets the groove's rim), measured both ways (_dug)
    along the bridging edge's normal."""
    local = _local_tree([[x.co for x in f.verts] for f in v.link_faces])
    if local is None:
        return 0.0
    worst = 0.0
    for f in v.link_faces:
        others = [x.co for x in f.verts if x is not v]
        if not others:
            continue
        mid = (v.co + sum(others, v.co * 0.0)) / (len(others) + 1)
        for p in [mid] + [v.co.lerp(c, t) for c in others for t in SPOKE]:
            worst = max(worst, _dug(tree, local, p, up, lim))
    return worst


def _groove_pair(f, is_new, tree):
    """The two crossing points of face f to join (None: fewer than two not joined yet): of every
    pair not already joined by an edge, the one whose line runs deepest in the groove - its
    middle nearest the original surface; a line across the face to a crossing point of another
    groove runs above the floor. Of two as near, the pair that comes first by place. Chosen by
    where the points are, never by where the face's corners happen to start."""
    from mathutils import Vector
    pts = [v for v in f.verts if v in is_new]
    best = None
    for i, a in enumerate(pts):
        for b in pts[i + 1:]:
            if any(e.other_vert(a) is b for e in a.link_edges):
                continue                                 # already joined
            mid = Vector((a.co + b.co) * 0.5)
            near = tree.find_nearest(mid)
            gap = near[3] if near[0] is not None else math.inf
            key = (gap, sorted((tuple(a.co), tuple(b.co))))
            if best is None or key < best[0]:
                best = (key, a, b)
    return None if best is None else best[1:]


def carve(low_me, src_me, tree=None, tol_rel: float = 0.0012, passes: int = 2, samples: int = 5,
          max_add: float = 0.06, min_edge_rel: float = 0.0015, reach_rel: float = 0.02) -> dict:
    """Cut narrow creases (mouth line, lid crease, corner pocket) into the new mesh.

    A remesher keeps a groove narrower than one quad only if an edge happens to run along it;
    otherwise quads bridge it and the groove is gone. Here every edge of the new mesh in the
    strict (face) region is compared with the original at a few points; where it bridges a
    groove by more than tol_rel of the size, the edge is split at the groove floor and the new
    points are joined face by face, so the valley becomes a continuous edge line - on both
    sides, whatever direction the remesher chose. Only adds detail; never moves existing
    vertices. Capped at max_add (share of the triangles).

    The cut follows the original and nothing else: the floor must face the way the edge does
    (a wall facing across the groove is not its floor); a crossing point with no partner among
    its faces' crossing points is not a groove at all - it is put back on its edge; and the line
    tapers where the groove fades: an end point sinks only as deep as its faces can go without
    digging into the original beside the groove deeper than the groove is going to be one
    crossing further on (never less than tol): else the V, as wide as the quads, would stop at
    full depth where the groove fades to nothing - a notch the original does not have."""
    import bmesh
    from mathutils import Vector
    pstrict = _poly_strict(src_me)
    if pstrict is None:
        return {"added": 0, "splits": 0, "skipped": "no strict region"}
    tree = tree or source_tree(src_me)
    bm = bmesh.new()
    bm.from_mesh(low_me)
    if not bm.verts:
        bm.free()
        return {"added": 0, "splits": 0}
    co = np.array([v.co[:] for v in bm.verts])
    size = float(np.linalg.norm(co.max(axis=0) - co.min(axis=0))) or 1.0
    tol, reach, min_edge = tol_rel * size, reach_rel * size, min_edge_rel * size
    tris0 = sum(len(f.verts) - 2 for f in bm.faces)
    allowance = int(max_add * tris0)
    added = splits = 0

    def hit_at(p, n, lim):
        """The groove floor under p: not facing away from the surface (not the far side of a
        sheet or the underside of an ear), within reach."""
        best = None
        for s in (1.0, -1.0):
            h = tree.ray_cast(p, n * s, lim)
            if h[0] is not None and h[1].dot(n) > FACING and (best is None or h[3] < best[3]):
                best = h
        return best

    put_back = 0
    cut_all: set = set()                                 # crossing points still cut, every pass
    flat_at: dict = {}                                   # where each sat on its bridging edge
    up_at: dict = {}

    def taper(nv, before: float) -> bool:
        """Raise the end point of a cut line from the floor towards its edge until its faces dig
        into the original beside the groove no deeper than the groove would be one crossing
        further on, going by how it changes from the point before (`before`, that point's
        depth) to this one - never less than tol. A line broken off in a groove that goes on
        at full depth keeps its end; where the groove fades, the end fades with it. True if it
        is still cut."""
        up, lim, gap = up_at[nv]
        allow = max(tol, 2.0 * gap - before)
        deep = nv.co.copy()
        if _cut_beside(tree, nv, up, lim) <= allow:
            return True
        lo, hi = 0.0, 1.0                                # share of the way from the edge to the floor
        for _step in range(8):
            nv.co = flat_at[nv].lerp(deep, (lo + hi) / 2)
            if _cut_beside(tree, nv, up, lim) <= allow:
                lo = (lo + hi) / 2
            else:
                hi = (lo + hi) / 2
        nv.co = flat_at[nv].lerp(deep, lo)
        return lo > 0.0

    for _ in range(passes):
        bm.normal_update()
        marks = []
        for e in bm.edges:
            a, b = e.verts
            elen = (b.co - a.co).length
            if elen < min_edge:
                continue
            best = None
            # a groove narrower than one quad is not much deeper than the quad is wide:
            # much deeper hits are another surface, not this groove
            lim = min(reach, 1.5 * elen)
            for k in range(1, samples + 1):
                t = k / (samples + 1)
                p = a.co.lerp(b.co, t)
                n = a.normal.lerp(b.normal, t)
                if n.length < 1e-9:
                    continue
                h = hit_at(p, n.normalized(), lim)
                if h is None or pstrict[h[2]] >= 0.999 or h[3] <= tol:
                    continue
                if best is None or h[3] > best[0]:
                    best = (h[3], t, Vector(h[0]), n.normalized(), lim)
            if best is not None:
                marks.append((best[0], e, best[1], best[2], best[3], best[4]))
        if not marks:
            break
        # deepest first; of two as deep, the one whose ends come first by place (never by the
        # order the edges happen to be in: the room below can take one and not the other)
        marks.sort(key=lambda m: (-m[0], sorted((tuple(m[1].verts[0].co), tuple(m[1].verts[1].co)))))
        room = max(0, allowance - added) // 3          # an edge split + face splits ~ 3 triangles
        marks = marks[:room]
        if not marks:
            break
        # (lists, not sets: a set of bmesh elements runs in memory-address order, which
        # changes from run to run - the faces would be split, and the folds put back, in
        # another order each time)
        new_verts = []
        for gap, e, t, hit, up, lim in marks:
            if not e.is_valid:
                continue
            _ne, nv = bmesh.utils.edge_split(e, e.verts[0], t)
            flat_at[nv] = nv.co.copy()                   # where it sat on the bridging edge
            up_at[nv] = (up, lim, gap)
            nv.co = hit
            new_verts.append(nv)
            splits += 1
        is_new = set(new_verts)
        # join the crossing points face by face: the groove becomes an edge chain
        for f in list(dict.fromkeys(f for v in new_verts for f in v.link_faces)):
            if not f.is_valid:
                continue
            pair = _groove_pair(f, is_new, tree)
            if pair is None:
                continue
            try:
                bmesh.utils.face_split(f, *pair)
            except (ValueError, RuntimeError):
                pass
        ng = [f for f in bm.faces if len(f.verts) > 4]
        if ng:
            bmesh.ops.triangulate(bm, faces=ng)
        # a cut that folds the surface (in the narrow gap at an ear or horn root the floor
        # can be another wall) is put back flat: a crease may deepen a valley, never fold it
        bm.normal_update()
        for nv in new_verts:
            if nv.is_valid and any(len(e.link_faces) == 2 and e.calc_face_angle(0.0) > math.radians(100)
                                   for e in nv.link_edges):
                nv.co = flat_at[nv]
        # a crossing point with no partner (no line to another crossing point that is still
        # cut) is not a groove: a lone pit where the original's groove fades. Put back, until
        # every point left has a partner
        cut = {nv for nv in new_verts if nv.is_valid and (nv.co - flat_at[nv]).length > 1e-12 * size}

        def partners(nv):
            return sum(1 for e in nv.link_edges if e.other_vert(nv) in cut or e.other_vert(nv) in cut_all)
        tapered: set = set()
        while True:
            lone = [nv for nv in new_verts if nv in cut and not partners(nv)]
            for nv in lone:
                nv.co = flat_at[nv]
                cut.discard(nv)
            # the line tapers where the original's groove fades (or where the face ends): along
            # the line a groove narrower than the quads is cut as a V as wide as the quads - that
            # is the crease kept - but at its end the V would stop at full depth, a notch the
            # original does not have. Each end point sinks only as far as its faces can go
            # without digging into the original beside it deeper than the groove is going to be
            # one crossing on (from the point before it to this one: a line broken off in a
            # groove that goes on keeps its end, one where the groove fades keeps a tol-deep end);
            # one that cannot sink at all goes back on its edge, and the point before is the end
            ends = [nv for nv in new_verts if nv in cut and nv not in tapered and partners(nv) == 1]
            for nv in ends:
                tapered.add(nv)
                prev = next(e.other_vert(nv) for e in nv.link_edges
                            if e.other_vert(nv) in cut or e.other_vert(nv) in cut_all)
                if not taper(nv, up_at[prev][2] if prev in up_at else up_at[nv][2]):
                    nv.co = flat_at[nv]
                    cut.discard(nv)
            if not lone and not ends:
                break
        put_back += sum(1 for nv in new_verts if nv.is_valid and nv not in cut)
        cut_all |= cut
        added = sum(len(f.verts) - 2 for f in bm.faces) - tris0
        if added >= allowance:
            break
    bm.normal_update()
    bm.to_mesh(low_me)
    bm.free()
    low_me.update()
    return {"added": int(added), "splits": int(splits), "put_back": int(put_back)}


def crease_kept(src_me, low_me, tol_rel: float = 0.0012, max_samples: int = 200_000) -> dict:
    """Share of the face (strict region) kept within tol_rel of size, left (+X) and right (-X)."""
    from mathutils import Vector
    a = src_me.attributes.get(STRICT_ATTR)
    if a is None:
        return {}
    n = len(src_me.vertices)
    sv = np.empty(n, np.float32)
    a.data.foreach_get("value", sv)
    co = np.empty(n * 3, np.float32)
    src_me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    size = float(np.linalg.norm(co.max(axis=0) - co.min(axis=0))) or 1.0
    idx = np.nonzero(sv < 0.999)[0]
    if len(idx) == 0:
        return {}
    idx = idx[:: max(1, len(idx) // max_samples)]
    tree = source_tree(low_me)
    ok = np.zeros(len(idx), bool)
    for j, i in enumerate(idx):
        h = tree.find_nearest(Vector(co[i]))
        ok[j] = h[0] is not None and h[3] <= tol_rel * size
    left = co[idx, 0] > 0
    out = {}
    if left.any():
        out["left_pct"] = round(100.0 * ok[left].mean(), 1)
    if (~left).any():
        out["right_pct"] = round(100.0 * ok[~left].mean(), 1)
    return out



# ----------------------------------------------------------------------------- dent gate

DENT_RATIO = 3.0     # a face may lie this many times its expected chord error off the original


def _face_gaps(tree, co: np.ndarray, polys: list, fids, size: float, tol: float) -> dict:
    """The faces (of fids) that lie off the original by more than they can explain: face ->
    its worst signed gap at its samples (- inside: a dent, + outside: a bump). A flat face of
    edge e on a surface whose normal turns by angle a under it lies about e * a / 8 off it (its
    chord error); a face more than DENT_RATIO times that (and more than tol) off the original
    is off where the original is not. Only where the original is smooth under the face: the
    original under the face's samples (straight under them, along the face's normal) must lie
    on one smooth sheet - within half the face's gap of a plane. A face over a groove or a
    crease it bridges has the groove floor under some samples and the rim under others: that is
    detail the face does not follow, not a dent or a bump it made. A sample whose nearest
    original point faces away from the face (the other side of a thin ear) is not judged."""
    out = {}
    for fi in fids:
        P, nv, samples, reach = _face(co, polys[fi])
        ns, under, worst = [], [], 0.0
        for k, pv in enumerate(P + samples):
            h = tree.find_nearest(pv)
            if h[0] is None or h[1].dot(nv) <= 0.0:
                continue
            ns.append(h[1][:])
            if k < len(P):                       # (the corners lend their normals: they lie on it)
                under.append(h[0][:])
                continue
            gap = (pv - h[0]).dot(h[1])
            if abs(gap) > abs(worst):
                worst = gap
            best = None
            for s_ in (1.0, -1.0):
                r = tree.ray_cast(pv, nv * s_, reach)
                if r[0] is not None and r[1].dot(nv) > 0.0 and (best is None or r[3] < best[3]):
                    best = r
            under.append((best or h)[0][:])
        if len(ns) < 2 or not worst:
            continue
        N = np.array(ns)
        turn = math.acos(float(np.clip((N @ N.T).min(), -1.0, 1.0)))
        e = sum((a - b).length for a, b in zip(P, P[1:] + P[:1])) / len(P)
        if abs(worst) <= max(DENT_RATIO * e * turn / 8.0, tol):
            continue
        U = np.array(under) - np.mean(under, axis=0)
        sheet = np.linalg.svd(U, full_matrices=False)[2][-1]            # the plane they lie nearest
        if float(np.abs(U @ sheet).max()) * 2.0 <= abs(worst):
            out[fi] = worst
    return out


def _islands(polys: list, fids) -> list:
    """Faces that share a corner, grouped (each group sorted, groups by their first face)."""
    parent = {f: f for f in fids}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    by_vert: dict = {}
    for f in sorted(fids):
        for v in polys[f]:
            if v in by_vert:
                a, b = find(by_vert[v]), find(f)
                if a != b:
                    parent[max(a, b)] = min(a, b)
            else:
                by_vert[v] = f
    groups: dict = {}
    for f in sorted(fids):
        groups.setdefault(find(f), []).append(f)
    return [groups[k] for k in sorted(groups)]


def smooth_dents(low_me, src_me, tree=None, tol_rel: float = 0.0012, before=None) -> dict:
    """The dent gate at the end of the fit: islands of faces that lie farther inside (a dent) or
    outside (a bump) the original than their chord error explains, where the original is
    smooth, are repaired where they are: each of their points is relaxed towards its neighbours
    and put back on the nearest original surface, and keeps that only if its faces then lie
    closer to the original (both ways); an island that still shows is left and reported.
    before: the points as the remesher gave them (before the fit): then only faces the fit
    moved are judged - a face with a point moved by more than a chord (FIT_CHECK of its edge).
    What the remesher made itself is the shape check's business, and a face round a crossing
    point carve added is a crease cut on purpose (carve keeps its own cut to the original).
    Returns {"found", "fixed", "left", "at": [island middle, ...], "left_at": [...], "kinds":
    ["dent" (sunk) or "bump" (raised), one per island]}."""
    tree = tree or source_tree(src_me)
    n = len(low_me.vertices)
    if n == 0 or not len(low_me.polygons):
        return {"found": 0, "fixed": 0, "left": 0, "at": [], "left_at": [], "kinds": []}
    co = np.empty(n * 3, np.float32)
    low_me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3).astype(np.float64)
    size = float(np.linalg.norm(co.max(axis=0) - co.min(axis=0))) or 1.0
    tol = tol_rel * size
    polys = _polys(low_me)
    vf = _vertex_faces(polys, n)
    ev = np.empty(len(low_me.edges) * 2, np.int32)
    low_me.edges.foreach_get("vertices", ev)
    ev = ev.reshape(-1, 2).astype(np.int64)
    nbrs: list = [[] for _ in range(n)]
    for a, b in ev:
        nbrs[a].append(int(b))
        nbrs[b].append(int(a))
    judged = range(len(polys))
    if before is not None:
        b = np.asarray(before, np.float64).reshape(-1, 3)
        n0 = min(len(b), n)
        moved = np.zeros(n, bool)
        moved[:n0] = np.linalg.norm(co[:n0] - b[:n0], axis=1) > FIT_CHECK * _mean_edge(co, ev)[:n0]
        judged = [fi for fi, f in enumerate(polys) if any(moved[v] for v in f) and max(f) < n0]
    bad = _face_gaps(tree, co, polys, judged, size, tol)
    islands = _islands(polys, list(bad))
    from mathutils import Vector
    fixed, at, left_at, kinds = 0, [], [], []
    for isl in islands:
        verts = sorted({v for f in isl for v in polys[f]})
        middle = co[verts].mean(axis=0)
        kinds.append("dent" if min(bad[f] for f in isl) < -max(bad[f] for f in isl) else "bump")
        for v in verts:
            if not nbrs[v]:
                continue
            trial = co.copy()
            near = tree.find_nearest(Vector(co[nbrs[v]].mean(axis=0)))      # relax, then onto the original
            if near[0] is None:
                continue
            trial[v] = near[0][:]
            faces = [polys[f] for f in vf[v]]
            if _closer(tree, co, trial, faces):
                co = trial
        near_faces = sorted({f for v in verts for f in vf[v]})
        if _face_gaps(tree, co, polys, near_faces, size, tol):
            left_at.append([round(float(x), 6) for x in middle])
        else:
            fixed += 1
        at.append([round(float(x), 6) for x in middle])
    low_me.vertices.foreach_set("co", co.astype(np.float32).ravel())
    low_me.update()
    return {"found": len(islands), "fixed": fixed, "left": len(islands) - fixed, "at": at, "left_at": left_at,
            "kinds": kinds}


# ----------------------------------------------------------------------------- symmetry and parts plan

SPLIT_ATTR = "forge_split"       # per vertex: 0 = body, k = thin part k (retopologized separately)


def straddles_middle(me, cell: float = 0.02, min_share: float = 0.5) -> bool:
    """The part is its own mirror image across X = 0 for most of its surface (a body, a
    collar, a bell on the chest): it can be made symmetric from one side. A part off to one
    side (a prop beside the body, a hair tuft, an earring) has no twin there: mirroring it
    would make a second copy. Measured on the surface, not the box (a curled tail or one
    raised arm moves the box, not the middle)."""
    n = len(me.vertices)
    if n == 0:
        return False
    co = np.empty(n * 3, np.float32)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3).astype(np.float64)
    if n > 300_000:                             # the share is a statistic: a sample is enough
        co = co[:: n // 300_000 + 1]
    size = float((co.max(axis=0) - co.min(axis=0)).max()) or 1.0
    return float(np.mean(~_mirror_far(co, cell * size))) >= min_share


def mirror_plane(me, max_shift: float = 0.03, samples: int = 60_000) -> float:
    """Where the body's mirror plane really is (x = x0), measured from its own symmetry, not
    from its box (a longer arm or a curled tail moves the box centre): the x0 whose mirror
    image lies closest to the surface (median distance of a sample), found coarse to fine
    within max_shift of the size. One-sided parts are a minority and do not move a median."""
    from mathutils.kdtree import KDTree
    n = len(me.vertices)
    if n == 0:
        return 0.0
    co = np.empty(n * 3, np.float32)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3).astype(np.float64)
    if n > samples:
        co = co[:: n // samples + 1]
    size = float((co.max(axis=0) - co.min(axis=0)).max()) or 1.0
    kd = KDTree(len(co))
    for i, p in enumerate(co):
        kd.insert(p, i)
    kd.balance()
    q = co[:: max(1, len(co) // 4000)]

    def cost(x0):
        return float(np.median([kd.find((2 * x0 - p[0], p[1], p[2]))[2] for p in q]))
    span = max_shift * size
    xs = np.linspace(-span, span, 13)
    best = min(xs, key=cost)
    step = xs[1] - xs[0]
    while step > 1e-4 * size:
        step *= 0.5
        best = min((best - step, best, best + step), key=cost)
    return float(best)


def symmetrize(me, side: str) -> None:
    """Make the mesh symmetric from one side: 'left' keeps the character's left (+X) and
    mirrors it over, 'right' keeps -X. One-sided parts must be split off first."""
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(me)
    size = max((max(v.co[i] for v in bm.verts) - min(v.co[i] for v in bm.verts)) for i in range(3)) \
        if bm.verts else 1.0
    bmesh.ops.symmetrize(bm, input=bm.verts[:] + bm.edges[:] + bm.faces[:],
                         direction="X" if side == "left" else "-X", dist=size * 1e-5)
    # vertices that sat a hair off the plane leave doubles and zero-length edges on the seam
    mid = [v for v in bm.verts if abs(v.co.x) < size * 1e-4]
    if mid:
        bmesh.ops.remove_doubles(bm, verts=mid, dist=size * 1e-5)
        bmesh.ops.dissolve_degenerate(bm, dist=size * 1e-6, edges=bm.edges[:])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()
    me.update()


def _mirror_far(co: np.ndarray, cell: float) -> np.ndarray:
    from .parts import mirror_far
    return mirror_far(co, cell)


def one_sided_parts(me, taken=None, **kw) -> np.ndarray:
    """Parts mirroring would copy or delete (no twin), cut at their neck: see parts.py."""
    from .parts import one_sided_parts as osp
    return osp(me, taken, **kw)


def write_split(me, ids: np.ndarray) -> None:
    a = me.attributes.get(SPLIT_ATTR)
    if a is not None:
        me.attributes.remove(a)
    a = me.attributes.new(SPLIT_ATTR, "INT", "POINT")
    a.data.foreach_set("value", ids.astype(np.int32))


def read_split(me):
    a = me.attributes.get(SPLIT_ATTR)
    if a is None or a.domain != "POINT":
        return None
    ids = np.empty(len(me.vertices), np.int32)
    a.data.foreach_get("value", ids)
    return ids if ids.any() else None


FINGERPRINT_STEP = 1e-6          # coordinates are compared on a grid this fine against the mesh's size
FINGERPRINT_RINGS = 16           # points on one spot are told apart by their neighbours this many rings out


def _mesh_arrays(me) -> tuple:
    """The mesh as it is stored, in its own order: coordinates (float32), edges, and each face's
    corner count and corners (the vertex of every loop, a face's corners one after another)."""
    nv, ne, nf, nl = len(me.vertices), len(me.edges), len(me.polygons), len(me.loops)
    co = np.empty(nv * 3, np.float32)
    me.vertices.foreach_get("co", co)
    ev = np.empty(ne * 2, np.int32)
    me.edges.foreach_get("vertices", ev)
    lt = np.empty(nf, np.int32)
    me.polygons.foreach_get("loop_total", lt)
    lv = np.empty(nl, np.int32)
    me.loops.foreach_get("vertex_index", lv)
    return co.reshape(-1, 3), ev.reshape(-1, 2), lt, lv


def exact_hash(me) -> str:
    """sha1 of the mesh exactly as it is stored, in its own order: every bit of every
    coordinate, the edges and the faces. Two meshes with the same exact hash are the same mesh
    to the last bit; one coordinate a single float step off gives another hash. fingerprint is
    the comparison on a grid; this one shows drift in the last bits too, which a remesher can
    turn into a different mesh."""
    import hashlib
    h = hashlib.sha1()
    for a in _mesh_arrays(me):
        h.update(np.int64(len(a)).tobytes())         # (each array's length: no two meshes read alike)
        h.update(np.ascontiguousarray(a).tobytes())
    return h.hexdigest()


def _scramble(x: np.ndarray) -> np.ndarray:
    """A fixed, well-mixed 64-bit number for each non-negative integer (splitmix64): a sum of
    them says which numbers were summed, in any order."""
    z = x.astype(np.uint64) + np.uint64(0x9E3779B97F4A7C15)
    z = (z ^ (z >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)
    z = (z ^ (z >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)
    return z ^ (z >> np.uint64(31))


def _vertex_names(q: np.ndarray, ev: np.ndarray) -> np.ndarray:
    """One number per vertex that does not depend on the order of the vertices: the rank of its
    place on the grid. Points on the same place (an unwelded seam, a loose copy, the two sides
    of an exact boolean's cut) are told apart by the names of their neighbours, then of their
    neighbours' neighbours, up to FINGERPRINT_RINGS rings out. Two still alike are joined alike
    that far (copies of each other: a doubled sheet)."""
    _u, name = np.unique(q, axis=0, return_inverse=True)
    name = name.reshape(-1).astype(np.int64)
    n = len(name)
    count = int(name.max()) + 1 if n else 0
    if count == n or not len(ev):
        return name
    a = np.concatenate([ev[:, 0], ev[:, 1]]).astype(np.int64)
    b = np.concatenate([ev[:, 1], ev[:, 0]]).astype(np.int64)
    for _ in range(FINGERPRINT_RINGS):
        around = np.zeros(n, np.uint64)              # the neighbours' names, in any order
        np.add.at(around, a, _scramble(name[b]))
        # the name first: a new name only splits an old one, the places stay in their order
        _u, new = np.unique(np.stack([name.astype(np.uint64), around], axis=1), axis=0, return_inverse=True)
        new = new.reshape(-1).astype(np.int64)
        grown = int(new.max()) + 1
        name = new
        if grown == count or grown == n:
            break
        count = grown
    return name


def _lowest_rotation(rows: np.ndarray) -> np.ndarray:
    """Each row (a face's corners) read from the corner on where it reads lowest, in its own
    winding: from its lowest corner, unless a degenerate face has that corner twice."""
    t = rows.shape[1]
    every = np.arange(len(rows))
    best = rows.copy()
    for i in range(1, t):
        alt = np.roll(rows, -i, axis=1)
        diff = alt != best
        first = np.argmax(diff, axis=1)
        lower = diff.any(axis=1) & (alt[every, first] < best[every, first])
        best[lower] = alt[lower]
    return best


def fingerprint(me, ordered: bool = True) -> tuple:
    """(vertices, faces, sha1 of where the vertices are, sha1 of the faces and edges) of a mesh:
    two meshes with the same fingerprint are the same mesh in the same place, the same points
    joined the same way. Used to prove that two runs did the same thing (the plan's dry run and
    the real run, or one run and the next).

    Coordinates count on a grid, so the last bits of a float do not count - unless a value sits
    right on the middle between two grid points (exact_hash compares every bit). The grid step
    is the power of two at or just under FINGERPRINT_STEP x the mesh's size (its largest
    extent), and it is hashed with the points: the same mesh moved, or scaled by any factor,
    gives another fingerprint, at any scale.

    By default the mesh is hashed in its own order: vertices, faces (each from its own first
    corner) and edges as they are numbered. The same surface in another order gives another
    fingerprint (a remesher makes a different mesh of it).

    With ordered=False the fingerprint does not depend on the order of the elements: each
    vertex is known by its place (and where points share a place, by its neighbours: see
    _vertex_names), each face by those names from its lowest corner on in its own winding, each
    edge by its two names; all of them sorted."""
    import hashlib
    co, ev, lt, lv = _mesh_arrays(me)
    nv, nf = len(co), len(lt)
    co = co.astype(np.float64)
    size = float((co.max(axis=0) - co.min(axis=0)).max()) if nv else 0.0
    size = size or (float(np.abs(co).max()) if nv else 0.0) or 1.0     # (all on one spot)
    # a power of two: every coordinate divides by it exactly, and the grid points are the same
    # numbers on every machine
    level = math.frexp(FINGERPRINT_STEP * size)[1] - 1
    q = np.rint(co / math.ldexp(1.0, level)).astype(np.int64)
    hv, hf = hashlib.sha1(np.int64(level).tobytes()), hashlib.sha1()
    if ordered:                                      # (a face's corners follow each other in the loops)
        hv.update(q.tobytes())
        for a in (lt, lv, ev):
            hf.update(np.int64(len(a)).tobytes())
            hf.update(a.astype(np.int64).tobytes())
        return nv, nf, hv.hexdigest(), hf.hexdigest()
    hv.update(q[np.lexsort(q.T[::-1])].tobytes())
    name = _vertex_names(q, ev)
    ls = np.concatenate([[0], np.cumsum(lt)[:-1]]).astype(np.int64) if nf else np.zeros(0, np.int64)
    for t in np.unique(lt).tolist():                 # faces with the same number of corners together
        sel = np.nonzero(lt == t)[0]
        rows = _lowest_rotation(name[lv[ls[sel][:, None] + np.arange(t)[None, :]]])
        hf.update(np.int64(t).tobytes())
        hf.update(rows[np.lexsort(rows.T[::-1])].tobytes())
    pairs = np.sort(name[ev.astype(np.int64)], axis=1) if len(ev) else np.zeros((0, 2), np.int64)
    hf.update(b"edges")
    hf.update(pairs[np.lexsort(pairs.T[::-1])].tobytes())
    return nv, nf, hv.hexdigest(), hf.hexdigest()


def pick_side(me) -> str:
    """'left' or 'right': the side with more surface detail (the better kept one)."""
    s = detail_score(me, scales=(6,))
    co = np.empty(len(me.vertices) * 3, np.float32)
    me.vertices.foreach_get("co", co)
    x = co.reshape(-1, 3)[:, 0]
    return "left" if s[x > 0].sum() >= s[x < 0].sum() else "right"
