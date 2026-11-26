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


def detail_score(me, scale_iterations: int = 6, feature_iterations: int = 3) -> np.ndarray:
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


def write_qr_density(me, score: np.ndarray, strength: float = 0.8, make_active: bool = True) -> None:
    """Corner-domain byte colours in sRGB, as Quad Remesher's density brush paints them."""
    point = qr_colours(qr_density(score, strength))
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
