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
FIT_CHECK = 0.05     # a vertex that moved this share of its edge more than its neighbours did (on
                     # average) bends its faces: it goes only as far as brings them closest to the
                     # original (_keep_closer); one that moved with its neighbours only carries
                     # its faces along, onto the surface each corner was projected to
FIT_GRID = 3         # the gap between faces and original is measured at FIT_GRID^2 points per triangle
FIT_STEPS = (1.0, 0.75, 0.5, 0.25)   # shares of a bending move tried (and none), longest first
FIT_JUDGED = 3       # a vertex is judged again when a neighbour is held back, at most this many times


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


def _grid(k: int) -> list:
    """The middles of the k x k small triangles a triangle splits into, as (s, t) shares of its
    two sides from the first corner: every one stands for the same share of its area."""
    up = [((i + 1 / 3) / k, (j + 1 / 3) / k) for i in range(k) for j in range(k - i)]
    down = [((i + 2 / 3) / k, (j + 2 / 3) / k) for i in range(k - 1) for j in range(k - 1 - i)]
    return up + down


_FIT_SAMPLES = _grid(FIT_GRID)


def _sag(co: np.ndarray, v: int, f, start: np.ndarray, nrm: np.ndarray) -> tuple:
    """How far face f may lie off a smooth surface through its corners (its chord error), as
    (inside, outside). With the surface's normal turning by angle a over a distance L between
    two of its corners, it bends by about a / L; a flat face D across (its longest side or
    diagonal, with v where it is and where it was) sags about (a / L) * D^2 / 8 off it - inside
    where the surface bulges out between the corners (their normals spread apart), outside
    where it hollows in (they close in: a fold or a join the face spans). The bend is the
    remesher's own surface's (start, nrm: its points and normals), between the corners other
    than v: at its quad size it is the smooth surface the faces stand for - the original's own
    normals next to a narrow groove are its walls', a bend the faces were never meant to
    follow."""
    pts = [w for w in f if w != v]
    bulge = hollow = 0.0
    for i, p in enumerate(pts):
        for q in pts[i + 1:]:
            d = start[q] - start[p]
            dist = float(np.linalg.norm(d))
            if dist <= 0.0:
                continue
            bend = math.acos(float(np.clip(np.dot(nrm[p], nrm[q]), -1.0, 1.0))) / dist
            if float(np.dot(d, nrm[q] - nrm[p])) >= 0.0:
                bulge = max(bulge, bend)
            else:
                hollow = max(hollow, bend)
    corners = [co[w] for w in pts] + [co[v], start[v]]
    span = max(float(np.linalg.norm(x - y)) for i, x in enumerate(corners) for y in corners[i + 1:])
    return bulge * span * span / 8.0, hollow * span * span / 8.0


def _gap(tree, co: np.ndarray, v: int, faces: list, sags: list, reach: float) -> tuple:
    """How far the faces round point v lie off the original beyond each face's own chord error
    (sags: inside, outside), as (volume, deepest): at points spread evenly over each face (fanned
    into triangles from v), the distance along the face's normal, out or in, to the original
    surface - the nearest one met that faces the same way (from inside, the surface above; never
    the far side of a thin part) - less the face's chord error on that side; the volume sums it
    times the area each point stands for. Measured across the face, not to the nearest surface
    point: a face sunk into a lip beside a narrow groove is close to the groove's wall but far
    below the lip the eye sees. The chord error is left out because a flat face cannot follow a
    curved surface closer than that: a remesher's point raised off a coarse sphere does narrow
    the gap of its sagging faces - by a bump. A point with no such surface within reach (pushed
    through a thin part) counts as reach."""
    from mathutils import Vector
    total = deepest = 0.0
    share = 1.0 / len(_FIT_SAMPLES)
    for f, (sag_in, sag_out) in zip(faces, sags):
        i = f.index(v)
        P = [Vector(co[w]) for w in f[i:] + f[:i]]
        for B, C in zip(P[1:-1], P[2:]):
            ab, ac = B - P[0], C - P[0]
            nv = ab.cross(ac)
            area = nv.length / 2.0
            if area <= 0.0:
                continue
            nv /= 2.0 * area
            for s, t in _FIT_SAMPLES:
                p = P[0] + ab * s + ac * t
                best, inside = None, False
                for d, up in ((nv, True), (-nv, False)):
                    h = tree.ray_cast(p, d, reach)
                    if h[0] is not None and h[1].dot(nv) > 0.0 and (best is None or h[3] < best):
                        best, inside = h[3], up             # (met going up: the face is dug in under it)
                if best is None:
                    h = tree.find_nearest(p, reach)
                    if h[0] is not None and h[1].dot(nv) > 0.0:
                        best, inside = h[3], (p - h[0]).dot(h[1]) < 0.0
                    else:
                        best = reach
                off = max(0.0, best - (sag_in if inside else sag_out))
                total += off * area * share
                deepest = max(deepest, off)
    return total, deepest


def _keep_closer(tree, start: np.ndarray, nrm: np.ndarray, target: np.ndarray, polys: list, vf: list,
                 ev: np.ndarray, edge: np.ndarray, reach: np.ndarray, tol: float, check: float = FIT_CHECK) -> tuple:
    """Each vertex whose move bends its faces (it moves more than `check` of its edge farther
    than its neighbours do, on average) goes only as far along its move, from where the
    remesher left it (start) to where the fit put it (target), as brings its faces closest to
    the original: all the way if they then lie on it within their chord error and tol
    everywhere (_gap's deepest); else to whichever of FIT_STEPS of the way leaves the least
    volume between faces and original beyond their chord error (_gap) - the shorter of two as
    close, and none of the way unless some share is closer than none. One test for every case:
    a vertex pulled into a notch at least about as wide as its faces takes them into the notch
    (closer: a one-sided notch comes back after a mirrored run); one pulled off a ghost bump or
    remesher noise onto the surface lands on it; one pulled into a groove narrower than its
    faces would drag them into the material on both sides of it - more volume dug out beside
    the groove than the groove holds: it goes only as deep as that pays, often not at all (the
    whole way is the notch the original does not have; the same for a ridge narrower than the
    faces, which would lift them off the skin beside it). One vertex at a time, lowest number
    first, each judged among its neighbours as they are by then; when one is held back its
    neighbours are judged again (at most FIT_JUDGED times each), as their faces changed.
    Returns (coordinates, how many were held back)."""
    import heapq
    n = len(target)
    out = target.copy()
    a, b = ev[:, 0], ev[:, 1]
    deg = np.maximum(np.bincount(a, minlength=n) + np.bincount(b, minlength=n), 1)[:, None]
    nbrs: list = [[] for _ in range(n)]
    for x, y in ev:
        nbrs[x].append(int(y))
        nbrs[y].append(int(x))
    move = target - start
    rest = np.stack([np.bincount(a, weights=move[b, k], minlength=n) + np.bincount(b, weights=move[a, k], minlength=n)
                     for k in range(3)], axis=1) / deg
    todo = [int(v) for v in np.nonzero(np.linalg.norm(move - rest, axis=1) > check * edge)[0]]
    heapq.heapify(todo)
    queued = set(todo)
    judged = np.zeros(n, np.int64)
    while todo:
        v = heapq.heappop(todo)
        queued.discard(v)
        if not vf[v] or not nbrs[v] or judged[v] >= FIT_JUDGED or not np.any(move[v]):
            continue
        was = out[v].copy()
        out[v] = target[v]                               # (judged in place: only v's faces are read)
        best = 1.0
        if float(np.linalg.norm(move[v] - (out[nbrs[v]] - start[nbrs[v]]).mean(axis=0))) > check * edge[v]:
            judged[v] += 1                               # (else it moves with its neighbours: faces carried along)
            faces = [polys[f] for f in vf[v]]
            sags = [_sag(out, v, f, start, nrm) for f in faces]
            lim = float(reach[v])
            vol, deepest = _gap(tree, out, v, faces, sags, lim)
            if deepest > tol:
                for share in FIT_STEPS[1:] + (0.0,):     # the shorter of two as close
                    out[v] = start[v] + share * move[v]
                    got = _gap(tree, out, v, faces, sags, lim)[0]
                    if got <= vol:
                        vol, best = got, share
        out[v] = target[v] if best == 1.0 else start[v] + best * move[v]
        if np.any(out[v] != was):
            for w in nbrs[v]:
                if w not in queued:
                    heapq.heappush(todo, w)
                    queued.add(w)
    return out, int(np.count_nonzero(np.any(out != target, axis=1)))


def conform(low_me, src_me, max_rel: float = 0.04, relax: int = 2, tree=None, tol_rel: float = 0.0012) -> dict:
    """Move every vertex of the new mesh onto the original surface. After a SYMMETRIC remesh
    this puts one-sided details back (a notch in one ear) and pulls the mesh into grooves at
    least about as wide as its quads. Projection along the vertex normal (both ways) keeps the
    quads even; where that finds nothing (the notch: there is no surface along the normal) the
    nearest surface point is used. A light relax keeps the quads from bunching, then they are
    projected again. Last, a vertex whose move bent its faces goes only as far along it as
    brings them closest to the original (_keep_closer): all the way where they then lie on it
    (within their chord error and tol_rel of the size); a vertex pulled into a groove narrower
    than its faces would sink them into the lips on both sides - a notch the original does not
    have - so it goes only as deep as that leaves its faces closer than where the remesher put
    it, often not at all (carve cuts such a crease in along new edges)."""
    from mathutils import Vector
    tree = tree or source_tree(src_me)
    n = len(low_me.vertices)
    if n == 0:
        return {"moved": 0, "held_back": 0}
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
            if best is None:
                near = tree.find_nearest(p, lim)
                if near[0] is not None and near[1].dot(d) > 0.0:
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

    start, nrm0 = co.copy(), normals(co)
    co, moved = project(co, nrm0)
    for _ in range(relax):
        avg = (np.stack([np.bincount(a, weights=co[b, k], minlength=n) + np.bincount(b, weights=co[a, k], minlength=n)
                         for k in range(3)], axis=1)) / deg
        nrm = normals(co)
        delta = avg - co
        delta -= nrm * (delta * nrm).sum(axis=1, keepdims=True)   # slide along the surface only
        co = co + 0.5 * delta
        co, _m = project(co, normals(co))
    polys = _polys(low_me)
    co, back = _keep_closer(tree, start, nrm0, co, polys, _vertex_faces(polys, n), ev, edge,
                            np.where(reach > 0, reach, limit), tol_rel * size)
    low_me.vertices.foreach_set("co", co.astype(np.float32).ravel())
    low_me.update()
    return {"moved": int(moved), "held_back": int(back)}


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
    vertices. Capped at max_add (share of the triangles)."""
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
            if h[0] is not None and h[1].dot(n) > 0.0 and (best is None or h[3] < best[3]):
                best = h
        return best

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
                    best = (h[3], t, Vector(h[0]))
            if best is not None:
                marks.append((best[0], e, best[1], best[2]))
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
        flat_at = {}
        for _gap, e, t, hit in marks:
            if not e.is_valid:
                continue
            _ne, nv = bmesh.utils.edge_split(e, e.verts[0], t)
            flat_at[nv] = nv.co.copy()                   # where it sat on the bridging edge
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
        added = sum(len(f.verts) - 2 for f in bm.faces) - tris0
        if added >= allowance:
            break
    bm.normal_update()
    bm.to_mesh(low_me)
    bm.free()
    low_me.update()
    return {"added": int(added), "splits": int(splits)}


CREASE_RING = 6      # points round a face point, half a quad of the new mesh away, that say how deep it lies


def _crease_depth(tree, p, n, r: float) -> "float | None":
    """How far original point p (normal n) lies below the surface round it, r away: the
    original is found along n (out or in, within 4 r) at CREASE_RING points round p on its
    tangent plane; along each line through p (two opposite points) the valley is as deep as
    its lower side, and p's depth is that of its deepest valley. A groove floor lies below both
    its lips across the groove; the foot of a step or the skin on a bulge does not (None:
    too few points found)."""
    from mathutils import Vector
    axis = min(((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)), key=lambda ax: abs(n.dot(Vector(ax))))
    u = n.cross(Vector(axis)).normalized()
    w = n.cross(u)
    heights = []
    for k in range(CREASE_RING):
        a = 2.0 * math.pi * k / CREASE_RING
        q = p + (u * math.cos(a) + w * math.sin(a)) * r
        best = None
        for d in (n, -n):
            h = tree.ray_cast(q, d, 4.0 * r)
            if h[0] is not None and h[1].dot(n) > 0.0 and (best is None or h[3] < best[3]):
                best = h
        heights.append(None if best is None else (best[0] - p).dot(n))
    half = CREASE_RING // 2
    lines = [min(heights[k], heights[k + half]) for k in range(half)
             if heights[k] is not None and heights[k + half] is not None]
    return max(lines) if lines else None


def crease_kept(src_me, low_me, tol_rel: float = 0.0012, max_samples: int = 40_000) -> dict:
    """How much of the face's creases the new mesh keeps, left (+X) and right (-X): the share of
    the crease-floor points that the new mesh comes within tol_rel of the size of. A crease-floor
    point is a point of the original's face (strict region) lying deeper than tol_rel below the
    surface round it half a quad away (_crease_depth; the face's typical quad of the new mesh,
    the median at those points): a valley narrower than the quads, which a remesher bridges
    unless an edge happens to run along it. A broad hollow any mesh follows is not one, nor is
    the smooth skin round a crease - nearly all of a face, which any mesh keeps: a share of all
    of it reads about 99% even for a mesh that lost the mouth line. Also how many crease points
    each side has ("left_n", "right_n"); a side with none has no share, a face with none
    returns {}."""
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    a = src_me.attributes.get(STRICT_ATTR)
    if a is None or not len(low_me.polygons):
        return {}
    n = len(src_me.vertices)
    sv = np.empty(n, np.float32)
    a.data.foreach_get("value", sv)
    co = np.empty(n * 3, np.float32)
    src_me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3).astype(np.float64)
    nrm = np.empty(n * 3, np.float32)
    src_me.vertices.foreach_get("normal", nrm)
    nrm = nrm.reshape(-1, 3).astype(np.float64)
    size = float(np.linalg.norm(co.max(axis=0) - co.min(axis=0))) or 1.0
    tol = tol_rel * size
    idx = np.nonzero(sv < 0.999)[0]
    if len(idx) == 0:
        return {}
    idx = idx[:: max(1, len(idx) // max_samples)]
    polys = _polys(low_me)
    lco = np.empty(len(low_me.vertices) * 3, np.float32)
    low_me.vertices.foreach_get("co", lco)
    lco = lco.reshape(-1, 3).astype(np.float64)
    quad = np.array([np.mean([np.linalg.norm(lco[f[j]] - lco[f[j - 1]]) for j in range(len(f))]) for f in polys])
    low = BVHTree.FromPolygons([Vector(c) for c in lco], polys)
    src = source_tree(src_me)
    near = [low.find_nearest(Vector(co[i])) for i in idx]
    found = [(i, h) for i, h in zip(idx, near) if h[0] is not None and np.linalg.norm(nrm[i]) > 0.5]
    if not found:
        return {}
    r = 0.5 * float(np.median([quad[h[2]] for _i, h in found]))
    left, kept = [], []
    for i, h in found:
        depth = _crease_depth(src, Vector(co[i]), Vector(nrm[i]), r)
        if depth is None or depth <= tol:
            continue
        left.append(co[i, 0] > 0)
        kept.append(h[3] <= tol)
    left, kept = np.array(left, bool), np.array(kept, bool)
    out: dict = {}
    for side, sel in (("left", left), ("right", ~left)):
        if sel.any():
            out[f"{side}_pct"] = round(100.0 * float(kept[sel].mean()), 1)
            out[f"{side}_n"] = int(sel.sum())
    return out



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
