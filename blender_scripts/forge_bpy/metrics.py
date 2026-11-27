"""Measurements the QA gate and the AI supervisor use to judge each stage."""

from __future__ import annotations

import bmesh
import bpy
import numpy as np

from . import common as C


def mesh_metrics(obj) -> dict:
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    non_manifold = sum(1 for e in bm.edges if not e.is_manifold and not e.is_boundary)
    boundary = sum(1 for e in bm.edges if e.is_boundary)
    ngons = sum(1 for f in bm.faces if len(f.verts) > 4)
    quads = sum(1 for f in bm.faces if len(f.verts) == 4)
    faces = len(bm.faces) or 1
    # loose shells
    seen, shells = set(), 0
    for v in bm.verts:
        if v.index in seen:
            continue
        shells += 1
        stack = [v]
        while stack:
            cur = stack.pop()
            if cur.index in seen:
                continue
            seen.add(cur.index)
            stack.extend(e.other_vert(cur) for e in cur.link_edges)
    bm.free()
    dims = obj.dimensions
    return {
        "tris": C.tri_count(obj),
        "verts": len(obj.data.vertices),
        "non_manifold_edges": non_manifold,
        "boundary_edges": boundary,
        "ngons": ngons,
        "quad_ratio": round(quads / faces, 3),
        "shells": shells,
        "dimensions_m": [round(d, 4) for d in dims],
    }


def _uv_tris(obj):
    me = obj.data
    me.calc_loop_triangles()
    uv = me.uv_layers.active
    if uv is None:
        return None, None
    n = len(me.loop_triangles)
    loops = np.empty(n * 3, dtype=np.int64)
    me.loop_triangles.foreach_get("loops", loops)
    uvs = np.empty(len(me.loops) * 2, dtype=np.float64)
    uv.data.foreach_get("uv", uvs)
    uvs = uvs.reshape(-1, 2)[loops].reshape(n, 3, 2)
    vidx = np.empty(n * 3, dtype=np.int64)
    me.loop_triangles.foreach_get("vertices", vidx)
    co = np.empty(len(me.vertices) * 3, dtype=np.float64)
    me.vertices.foreach_get("co", co)
    pos = co.reshape(-1, 3)[vidx].reshape(n, 3, 3)
    return uvs, pos


def _area2(t):
    a, b, c = t[:, 0], t[:, 1], t[:, 2]
    return 0.5 * np.abs((b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (c[:, 0] - a[:, 0]) * (b[:, 1] - a[:, 1]))


def _area3(t):
    return 0.5 * np.linalg.norm(np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]), axis=1)


def _coverage(uvs, res: int) -> np.ndarray:
    """Rasterise UV triangles; returns per-pixel coverage counts."""
    grid = np.zeros((res, res), dtype=np.uint16)
    px = uvs * res
    for tri in px:
        x0, y0 = np.floor(tri.min(axis=0)).astype(int)
        x1, y1 = np.ceil(tri.max(axis=0)).astype(int)
        x0, y0 = max(x0, 0), max(y0, 0)
        x1, y1 = min(x1, res), min(y1, res)
        if x1 <= x0 or y1 <= y0:
            continue
        xs, ys = np.meshgrid(np.arange(x0, x1) + 0.5, np.arange(y0, y1) + 0.5)
        a, b, c = tri
        d = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
        if abs(d) < 1e-12:
            continue
        l1 = ((b[1] - c[1]) * (xs - c[0]) + (c[0] - b[0]) * (ys - c[1])) / d
        l2 = ((c[1] - a[1]) * (xs - c[0]) + (a[0] - c[0]) * (ys - c[1])) / d
        l3 = 1 - l1 - l2
        eps = 1e-6
        inside = (l1 > eps) & (l2 > eps) & (l3 > eps)
        grid[y0:y1, x0:x1] += inside.astype(np.uint16)
    return grid


def uv_metrics(obj, texture_size: int, raster_res: int = 512) -> dict:
    uvs, pos = _uv_tris(obj)
    if uvs is None or len(uvs) == 0:
        return {"has_uv": False}
    a_uv = _area2(uvs)
    a_3d = _area3(pos)
    valid = (a_3d > 1e-12)
    density = np.sqrt(a_uv[valid] * texture_size ** 2 / a_3d[valid])   # pixels per metre
    w = a_3d[valid]
    mean = float(np.average(density, weights=w)) if w.sum() > 0 else 0.0
    std = float(np.sqrt(np.average((density - mean) ** 2, weights=w))) if w.sum() > 0 else 0.0
    out_of_bounds = float(np.mean((uvs < -1e-4) | (uvs > 1 + 1e-4)))
    grid = _coverage(np.clip(uvs, 0, 1), raster_res)
    covered = grid > 0
    overlap = grid > 1
    zero_area = int(np.sum(a_uv < 1e-12))
    return {
        "has_uv": True,
        "utilization": round(float(covered.mean()), 4),
        "overlap_pct": round(100.0 * float(overlap.sum()) / max(int(covered.sum()), 1), 3),
        "texel_density_px_per_m": round(mean, 2),
        "texel_density_cv": round(std / mean, 4) if mean > 0 else None,
        "out_of_bounds_ratio": round(out_of_bounds, 5),
        "zero_area_uv_tris": zero_area,
    }


def uv_layout(obj, eps: float = 1e-5) -> dict:
    """How the active UV map is cut: islands (separate pieces), seam length, surface area.
    An edge is a seam where the two faces beside it disagree on the UV of either end.
    seam_ratio = seam length / sqrt(surface area): the same cut on a model twice the size gives
    the same number, so engines (or models) compare on the shape of the cut, not the scale."""
    from .appendages import _components
    me = obj.data
    nl, nf = len(me.loops), len(me.polygons)
    if me.uv_layers.active is None or not nl or not nf:
        return {}
    uv = np.empty(nl * 2, np.float64)
    me.uv_layers.active.data.foreach_get("uv", uv)
    uv = uv.reshape(-1, 2)
    lv = np.empty(nl, np.int64)
    me.loops.foreach_get("vertex_index", lv)
    le = np.empty(nl, np.int64)
    me.loops.foreach_get("edge_index", le)
    ls = np.empty(nf, np.int64)
    me.polygons.foreach_get("loop_start", ls)
    lt = np.empty(nf, np.int64)
    me.polygons.foreach_get("loop_total", lt)
    face = np.repeat(np.arange(nf), lt)
    nxt = np.arange(1, nl + 1)
    nxt[ls + lt - 1] = ls                                 # the corner after the last is the first
    co = np.empty(len(me.vertices) * 3, np.float64)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    area_f = np.empty(nf, np.float64)
    me.polygons.foreach_get("area", area_f)
    area = float(area_f.sum())
    order = np.argsort(le, kind="stable")
    counts = np.bincount(le, minlength=len(me.edges))
    first = np.concatenate(([0], np.cumsum(counts)[:-1]))
    two = np.nonzero(counts == 2)[0]                      # edges between exactly two faces
    a, b = order[first[two]], order[first[two] + 1]
    same = lv[b] == lv[a]                                 # (faces wound the same way or not)
    b_start = np.where(same, b, nxt[b])                   # b's corner at a's start vertex
    b_end = np.where(same, nxt[b], b)
    seam = (np.abs(uv[a] - uv[b_start]).max(axis=1) > eps) | (np.abs(uv[nxt[a]] - uv[b_end]).max(axis=1) > eps)
    length = np.linalg.norm(co[lv[a]] - co[lv[nxt[a]]], axis=1)
    seam_len = float(length[seam].sum())
    joined = ~seam
    labels = _components(nf, face[a][joined], face[b][joined])
    return {"islands": int(len(np.unique(labels))), "seam_length_m": round(seam_len, 4),
            "seam_ratio": round(seam_len / max(area, 1e-12) ** 0.5, 3), "area_m2": round(area, 6)}


def weight_metrics(obj, max_influences: int) -> dict:
    if not obj.vertex_groups:
        return {"weighted": False}
    over, unweighted, not_normalized = 0, 0, 0
    for v in obj.data.vertices:
        ws = [g.weight for g in v.groups if g.weight > 1e-4]
        if not ws:
            unweighted += 1
            continue
        if len(ws) > max_influences:
            over += 1
        if abs(sum(ws) - 1.0) > 0.01:
            not_normalized += 1
    n = len(obj.data.vertices) or 1
    return {
        "weighted": True,
        "vertex_groups": len(obj.vertex_groups),
        "verts_over_influence_limit": over,
        "unweighted_verts_pct": round(100.0 * unweighted / n, 3),
        "not_normalized_pct": round(100.0 * not_normalized / n, 3),
    }


def collect(args: dict) -> dict:
    tex = int(args.get("texture_size", 2048))
    max_inf = int(args.get("max_influences", 4))
    out = {}
    for obj in C.meshes_with_role("low"):
        entry = {"mesh": mesh_metrics(obj), "uv": uv_metrics(obj, tex)}
        if C.find_armature() is not None:
            entry["weights"] = weight_metrics(obj, max_inf)
        out[obj.get(C.PART_PROP)] = entry
    return {"parts": out}
