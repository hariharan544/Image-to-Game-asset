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


def boost(me, mask: np.ndarray, rings: int = 3, edge_factor: float = 4.0) -> int:
    """Paint the masked area (grown by a few rings) denser. edge_factor is Quad Remesher's own
    scale (edges that many times shorter): 4 = full red = 16x the quads, 2 = 4x the quads."""
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
    lab[(V[:, 2] > neck_z) & (ax < sh_x)] = 1                         # head
    arm = ax > sh_x * 1.05
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

def conform(low_me, src_me, max_rel: float = 0.04, relax: int = 2) -> dict:
    """Move every vertex of the new mesh onto the original surface. After a SYMMETRIC remesh
    this puts one-sided details back (a notch in one ear) and pulls the mesh into grooves
    (mouth line). Projection along the vertex normal (both ways) keeps the quads even; where
    that finds nothing (the notch: there is no surface along the normal) the nearest surface
    point is used. A light relax keeps the quads from bunching, then they are projected again."""
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    tree = BVHTree.FromPolygons([v.co.copy() for v in src_me.vertices],
                                [tuple(p.vertices) for p in src_me.polygons])
    n = len(low_me.vertices)
    if n == 0:
        return {"moved": 0}
    co = np.empty(n * 3, np.float32)
    low_me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3).astype(np.float64)
    size = float(np.linalg.norm(co.max(axis=0) - co.min(axis=0))) or 1.0
    limit = max_rel * size
    ev = np.empty(len(low_me.edges) * 2, np.int32)
    low_me.edges.foreach_get("vertices", ev)
    a, b = ev[0::2].astype(np.int64), ev[1::2].astype(np.int64)
    deg = np.maximum(np.bincount(a, minlength=n) + np.bincount(b, minlength=n), 1)[:, None]

    def project(pts, nrm):
        out = pts.copy()
        moved = 0
        for i in range(n):
            p = Vector(pts[i])
            d = Vector(nrm[i])
            best = None
            for s in (1.0, -1.0):
                hit = tree.ray_cast(p, d * s, limit)
                if hit[0] is not None and (best is None or hit[3] < best[1]):
                    best = (hit[0], hit[3])
            if best is None:
                near = tree.find_nearest(p, limit)
                if near[0] is not None:
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

    co, moved = project(co, normals(co))
    for _ in range(relax):
        avg = (np.stack([np.bincount(a, weights=co[b, k], minlength=n) + np.bincount(b, weights=co[a, k], minlength=n)
                         for k in range(3)], axis=1)) / deg
        nrm = normals(co)
        delta = avg - co
        delta -= nrm * (delta * nrm).sum(axis=1, keepdims=True)   # slide along the surface only
        co = co + 0.5 * delta
        co, _m = project(co, normals(co))
    low_me.vertices.foreach_set("co", co.astype(np.float32).ravel())
    low_me.update()
    return {"moved": int(moved)}


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

    def hit_at(p, n):
        best = None
        for s in (1.0, -1.0):
            h = tree.ray_cast(p, n * s, reach)
            if h[0] is not None and (best is None or h[3] < best[3]):
                best = h
        return best

    for _ in range(passes):
        bm.normal_update()
        marks = []
        for e in bm.edges:
            a, b = e.verts
            if (b.co - a.co).length < min_edge:
                continue
            best = None
            for k in range(1, samples + 1):
                t = k / (samples + 1)
                p = a.co.lerp(b.co, t)
                n = a.normal.lerp(b.normal, t)
                if n.length < 1e-9:
                    continue
                h = hit_at(p, n.normalized())
                if h is None or pstrict[h[2]] >= 0.999 or h[3] <= tol:
                    continue
                if best is None or h[3] > best[0]:
                    best = (h[3], t, Vector(h[0]))
            if best is not None:
                marks.append((best[0], e, best[1], best[2]))
        if not marks:
            break
        marks.sort(key=lambda m: -m[0])
        room = max(0, allowance - added) // 3          # an edge split + face splits ~ 3 triangles
        marks = marks[:room]
        if not marks:
            break
        new_verts = set()
        for _gap, e, t, hit in marks:
            if not e.is_valid:
                continue
            _ne, nv = bmesh.utils.edge_split(e, e.verts[0], t)
            nv.co = hit
            new_verts.add(nv)
            splits += 1
        # join the crossing points face by face: the groove becomes an edge chain
        for f in list({f for v in new_verts for f in v.link_faces}):
            if not f.is_valid:
                continue
            nvs = [v for v in f.verts if v in new_verts]
            if len(nvs) < 2:
                continue
            a, b = nvs[0], nvs[1]
            if any(b in (e.other_vert(a),) for e in a.link_edges):
                continue                                 # already adjacent
            try:
                bmesh.utils.face_split(f, a, b)
            except (ValueError, RuntimeError):
                pass
        ng = [f for f in bm.faces if len(f.verts) > 4]
        if ng:
            bmesh.ops.triangulate(bm, faces=ng)
        added = sum(len(f.verts) - 2 for f in bm.faces) - tris0
        if added >= allowance:
            break
    bm.normal_update()
    bm.to_mesh(low_me)
    bm.free()
    low_me.update()
    return {"added": int(added), "splits": int(splits)}


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
