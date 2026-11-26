"""Detail map: where a retopology needs more quads (and where it can save them).

Per vertex of the dense AI mesh, a 0..1 "detail" score from how sharply the surface bends
at the scale of a few quads: eye sockets, the mouth line, nostrils, ear rims, nail and hoof
tips score high; a belly or a back scores low. Pure numpy on the mesh arrays (a 5M-triangle
mesh takes a few seconds).

The score is written as a colour attribute for Quad Remesher's density painting
(see to_qr_colours) and can be shown to the director as a heat map.
"""

from __future__ import annotations

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
    mask = np.zeros(n, bool)
    mask[idx[rel > tol_rel]] = True
    if stride > 1 and mask.any():
        mask = _dilate(mask, src_me, int(2 * stride ** 0.5) + 1)
    return {"mask": mask, "lost_ratio": float((rel > tol_rel).mean()) if len(rel) else 0.0,
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


def boost(me, mask: np.ndarray, rings: int = 3) -> int:
    """Paint the masked area (grown by a few rings) full red = 4x denser quads."""
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
    col[hit] = (1.0, 0.0, 0.0, 1.0)
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


def region_factors(V: np.ndarray, J: dict):
    """Per-vertex importance multiplier and region name index, from the guessed joints."""
    from .appendages import _dist_to_segments, _segments
    segs = _segments(J)
    d, which, where = _dist_to_segments(V, segs)
    names = [region_of(k) for _a, _b, k in segs]
    f = np.array([REGION_WEIGHT.get(n, 1.0) for n in names])[which]
    # rings of extra quads where joints bend: near the head (t~0) of the joint's bone
    H = float(V[:, 2].max() - V[:, 2].min()) or 1.0
    for i, (a, _b, k) in enumerate(segs):
        if region_of(k) in JOINTS:
            near = np.linalg.norm(V - a, axis=1) < 0.06 * H
            f[near] = np.maximum(f[near], JOINT_WEIGHT)
    return f, which, names


def region_tris(low_obj, J: dict) -> dict:
    """Triangles per body region of the new mesh (for the director's budget view)."""
    from .appendages import _dist_to_segments, _segments
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
    segs = _segments(J)
    _d, which, _w = _dist_to_segments(P, segs)
    out: dict = {}
    for i, (_a, _b, k) in enumerate(segs):
        r = region_of(k)
        r = {"lowerarm": "arms", "upperarm": "arms", "thigh": "legs", "calf": "legs", "foot": "feet",
             "ball": "feet", "hand": "hands", "pelvis": "body", "neck": "head", "head": "head"}.get(r, r)
        out[r] = out.get(r, 0) + int((which == i).sum())
    return out
