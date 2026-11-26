"""Thin-part rescue for retopology: when a part of the original (a tail, a horn tip) is still
missing after density-guided re-runs, cut that region out of the original, retopologize it
on its own (quads sized for it, not for the whole body) and fuse it back into the new mesh
with a boolean union, so the result stays one closed surface for skinning.
"""

from __future__ import annotations

import bmesh
import bpy
import numpy as np

from .density import _dilate


def _edges(me) -> np.ndarray:
    ev = np.empty(len(me.edges) * 2, np.int32)
    me.edges.foreach_get("vertices", ev)
    return ev.reshape(-1, 2).astype(np.int64)


def regions(src_me, mask: np.ndarray, min_verts: int = 40) -> list:
    """Connected groups of lost vertices (each a boolean mask), biggest first."""
    from .appendages import _components
    ev = _edges(src_me)
    keep = mask[ev[:, 0]] & mask[ev[:, 1]]
    lab = _components(len(mask), ev[keep, 0], ev[keep, 1])
    out = []
    for lbl in np.unique(lab[mask]):
        m = mask & (lab == lbl)
        if m.sum() >= max(min_verts, int(0.0003 * len(mask))):
            out.append(m)
    out.sort(key=lambda m: -int(m.sum()))
    return out


def extract(src_me, region: np.ndarray, grow_rings: int = 6, name: str = "forge_rescue"):
    """A closed mesh of the region, grown into the body so its root sits inside it."""
    grown = _dilate(region, src_me, grow_rings)
    bm = bmesh.new()
    bm.from_mesh(src_me)
    bm.verts.ensure_lookup_table()
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not grown[v.index]], context="VERTS")
    open_edges = [e for e in bm.edges if e.is_boundary]
    if open_edges:
        res = bmesh.ops.holes_fill(bm, edges=open_edges, sides=100000)
        ng = [f for f in res.get("faces", []) if len(f.verts) > 3]
        if ng:
            bmesh.ops.triangulate(bm, faces=ng)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    return me


def area(me) -> float:
    a = np.empty(len(me.polygons), np.float32)
    me.polygons.foreach_get("area", a)
    return float(a.sum())


def fuse(target, piece_obj) -> None:
    """Boolean-union piece_obj into target's mesh (exact solver), one closed surface."""
    mod = target.modifiers.new("forge_rescue_union", "BOOLEAN")
    mod.operation = "UNION"
    mod.solver = "EXACT"
    mod.object = piece_obj
    others = [m for m in target.modifiers if m.name != mod.name and m.show_viewport]
    for m in others:
        m.show_viewport = False
    piece_obj.hide_set(False)
    dg = bpy.context.evaluated_depsgraph_get()
    dg.update()
    new = bpy.data.meshes.new_from_object(target.evaluated_get(dg))
    target.modifiers.remove(mod)
    for m in others:
        m.show_viewport = True
    old = target.data
    new.name = old.name
    target.data = new
    if old.users == 0:
        bpy.data.meshes.remove(old)
