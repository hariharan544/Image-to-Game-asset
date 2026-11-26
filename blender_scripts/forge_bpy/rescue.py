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


def extract(src_me, region: np.ndarray, grow_rings: int = 2, name: str = "forge_rescue"):
    """A closed mesh of the region whose root continues as a tapered plug INTO the body.

    The cut is kept tight (a couple of rings past the lost area) and the open root is
    extruded inward, so the boolean union meets the body along a clean crossing line
    instead of two surfaces lying on top of each other (which leaves cracks and flaps)."""
    from mathutils import Vector
    grown = _dilate(region, src_me, grow_rings)
    bm = bmesh.new()
    bm.from_mesh(src_me)
    bm.verts.ensure_lookup_table()
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not grown[v.index]], context="VERTS")
    open_edges = [e for e in bm.edges if e.is_boundary]
    if open_edges and bm.verts:
        ring = {v for e in open_edges for v in e.verts}
        root = sum((v.co for v in ring), Vector()) / len(ring)
        centre = sum((v.co for v in bm.verts), Vector()) / len(bm.verts)
        # the plug follows the cut ring itself: its plane normal, pointing from the body into
        # the part (the farthest vertex of a curled tail points sideways, not into the body)
        rc = np.array([v.co[:] for v in ring]) - np.array(root[:])
        tip = max(bm.verts, key=lambda v: (v.co - root).length).co.copy()
        normal = tip - root if (tip - root).length > 1e-9 else centre - root
        if len(ring) >= 3:
            _u, sv, vt = np.linalg.svd(rc, full_matrices=False)
            if sv[2] < 0.25 * sv[1]:                 # one flat ring: its normal (else: tip)
                normal = Vector(vt[2])
        out = normal.normalized()
        if out.dot(centre - root) < 0:
            out = -out
        radius = max(float(np.median([(v.co - root).length for v in ring])), 1e-6)
        # plug: two rings going into the body, narrowing, then closed
        edges = open_edges
        for depth, shrink in ((0.6, 0.85), (1.2, 0.6)):
            res = bmesh.ops.extrude_edge_only(bm, edges=edges)
            new_v = [g for g in res["geom"] if isinstance(g, bmesh.types.BMVert)]
            for v in new_v:
                rel = v.co - root
                rel -= out * rel.dot(out)                    # radial part
                v.co = root - out * (radius * depth) + rel * shrink
            edges = [g for g in res["geom"] if isinstance(g, bmesh.types.BMEdge)
                     and all(x in new_v for x in g.verts)]
        plug = (root, out, radius)
        res = bmesh.ops.holes_fill(bm, edges=[e for e in bm.edges if e.is_boundary], sides=100000)
        ng = [f for f in res.get("faces", []) if len(f.verts) > 3]
        if ng:
            bmesh.ops.triangulate(bm, faces=ng)
    else:
        plug = None
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    if plug:
        me["forge_plug"] = [*plug[0], *plug[1], plug[2]]
    return me


def retract_stub(target, piece_obj, plug) -> int:
    """The remesher's collapsed stub (what is left of the tail on the body) lies around and
    partly outside the rebuilt part; fused as it is, it pokes through and leaves a crack or a
    flap. Pull every target vertex on or near the rebuilt part deep into its plug, where the
    union swallows it."""
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    root = Vector(plug[0:3])
    out = Vector(plug[3:6])
    radius = float(plug[6])
    deep = root - out * radius * 0.9
    pm = piece_obj.data
    tree = BVHTree.FromPolygons([v.co.copy() for v in pm.vertices], [tuple(p.vertices) for p in pm.polygons])
    n = 0
    for v in target.data.vertices:
        along = (v.co - root).dot(out)
        if along < -radius * 0.3:                      # body side of the cut: leave the body alone
            continue
        radial = ((v.co - root) - out * along).length
        if along < radius * 0.5 and radial > radius * 1.6:
            continue                                   # body surface around the root
        hit = tree.find_nearest(v.co)
        if hit[0] is None or hit[3] > radius * 1.2:
            continue                                   # far from the rebuilt part
        inside = (v.co - hit[0]).dot(hit[1]) < 0
        if inside or hit[3] < radius * 0.35:
            v.co = deep + (v.co - deep) * 0.25
            n += 1
    target.data.update()
    return n


def area(me) -> float:
    a = np.empty(len(me.polygons), np.float32)
    me.polygons.foreach_get("area", a)
    return float(a.sum())


def seal(me) -> int:
    """Close any hole in a remeshed piece (remeshers sometimes leave one at a thin end)."""
    bm = bmesh.new()
    bm.from_mesh(me)
    open_e = [e for e in bm.edges if e.is_boundary]
    n = 0
    if open_e:
        res = bmesh.ops.holes_fill(bm, edges=open_e, sides=100000)
        n = len(res.get("faces", []))
        ng = [f for f in res.get("faces", []) if len(f.verts) > 3]
        if ng:
            bmesh.ops.triangulate(bm, faces=ng)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        bm.to_mesh(me)
        me.update()
    bm.free()
    return n


def fuse(target, piece_obj, plug=None) -> str:
    """Boolean-union piece_obj into target's mesh (exact solver), one closed surface."""
    seal(piece_obj.data)                 # a leaky piece makes the union leak too
    before = target.data.copy()
    faces_before = len(before.polygons)
    if plug:
        retract_stub(target, piece_obj, plug)
    mod = target.modifiers.new("forge_rescue_union", "BOOLEAN")
    mod.operation = "UNION"
    mod.solver = "EXACT"
    mod.object = piece_obj
    for k, v in (("use_self", True), ("use_hole_tolerant", True)):   # the pulled-in stub crosses itself
        if hasattr(mod, k):
            setattr(mod, k, v)
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
    if len(new.polygons) < 0.8 * faces_before:
        # the union failed (it lost most of the body): keep the body as it was and attach the
        # rebuilt part as an overlapping piece instead - still skinnable, never destroyed
        bpy.data.meshes.remove(new)
        target.data = before
        if old.users == 0:
            bpy.data.meshes.remove(old)
        _join(target, piece_obj)
        return "joined"
    target.data = new
    if old.users == 0:
        bpy.data.meshes.remove(old)
    bpy.data.meshes.remove(before)
    clean_seam(target.data, piece_obj)
    return "fused"


def _join(target, piece_obj) -> None:
    bm = bmesh.new()
    bm.from_mesh(target.data)
    m = target.matrix_world.inverted() @ piece_obj.matrix_world
    tmp = piece_obj.data.copy()
    tmp.transform(m)
    bm.from_mesh(tmp)
    bpy.data.meshes.remove(tmp)
    bm.to_mesh(target.data)
    bm.free()
    target.data.update()


def clean_seam(me, piece_obj) -> None:
    """After the union: weld near-duplicates, drop slivers and loose bits, and relax the
    vertices along the new seam so the joint is smooth instead of cracked."""
    from mathutils.bvhtree import BVHTree
    bm = bmesh.new()
    bm.from_mesh(me)
    size = max((max(v.co[i] for v in bm.verts) - min(v.co[i] for v in bm.verts)) for i in range(3)) \
        if bm.verts else 1.0
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=size * 2e-4)
    bmesh.ops.dissolve_degenerate(bm, dist=size * 2e-4, edges=bm.edges)
    loose = [v for v in bm.verts if not v.link_faces]
    if loose:
        bmesh.ops.delete(bm, geom=loose, context="VERTS")
    # seam = vertices of the result lying on the piece's surface AND on the body's (the
    # crossing line): those close to the piece surface whose faces mix both origins
    pm = piece_obj.data
    tree = BVHTree.FromPolygons([v.co.copy() for v in pm.vertices], [tuple(p.vertices) for p in pm.polygons])
    near = set()
    tol = size * 0.004
    for v in bm.verts:
        hit = tree.find_nearest(v.co)
        if hit[0] is not None and hit[3] < tol:
            near.add(v)
    seam = [v for v in near if any(n not in near for n in (e.other_vert(v) for e in v.link_edges))]
    band = set(seam)
    for _ in range(2):                                   # a couple of rings around the crossing
        band |= {e.other_vert(v) for v in list(band) for e in v.link_edges}
    if band:
        for _ in range(3):
            bmesh.ops.smooth_vert(bm, verts=list(band), factor=0.5, use_axis_x=True, use_axis_y=True,
                                  use_axis_z=True)
    ng = [f for f in bm.faces if len(f.verts) > 4]
    if ng:
        bmesh.ops.triangulate(bm, faces=ng)
    # needle triangles along the crossing line shade badly: collapse their shortest edge
    import math
    for _ in range(3):
        bm.faces.ensure_lookup_table()
        short = set()
        for f in bm.faces:
            if len(f.verts) != 3 or not any(v in band for v in f.verts):
                continue
            angles = [l.calc_angle() for l in f.loops]
            if min(angles) < math.radians(4):
                short.add(min(f.edges, key=lambda e: e.calc_length()))
        if not short:
            break
        bmesh.ops.collapse(bm, edges=list(short), uvs=True)
        band = {v for v in band if v.is_valid}
    # holes or broken (3+ face) edges the union or the collapses can leave on the crossing
    # line: cut the faces around them out and fill the opening cleanly
    for _ in range(3):
        loose = [v for v in bm.verts if not v.link_faces]
        if loose:
            bmesh.ops.delete(bm, geom=loose, context="VERTS")
        bad = [e for e in bm.edges if len(e.link_faces) > 2]
        if bad:
            kill = {f for e in bad for v in e.verts for f in v.link_faces}
            bmesh.ops.delete(bm, geom=list(kill), context="FACES")
            loose = [v for v in bm.verts if not v.link_faces]
            if loose:
                bmesh.ops.delete(bm, geom=loose, context="VERTS")
        open_e = [e for e in bm.edges if e.is_boundary]
        if not open_e and not bad:
            break
        if open_e:
            res = bmesh.ops.holes_fill(bm, edges=open_e, sides=200)
            ng = [f for f in res.get("faces", []) if len(f.verts) > 3]
            if ng:
                bmesh.ops.triangulate(bm, faces=ng)
            still = [e for e in bm.edges if e.is_boundary]
            if still:                                   # a tangled little hole: weld its rim first
                rim = list({v for e in still for v in e.verts})
                bmesh.ops.remove_doubles(bm, verts=rim, dist=size * 3e-3)
                still = [e for e in bm.edges if e.is_valid and e.is_boundary]
                if still:
                    res = bmesh.ops.holes_fill(bm, edges=still, sides=0)
                    ng = [f for f in res.get("faces", []) if len(f.verts) > 3]
                    if ng:
                        bmesh.ops.triangulate(bm, faces=ng)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()
    me.update()


def _defects(bm) -> tuple:
    """(open edges, edges shared by more than two faces, loose vertices)."""
    return (sum(1 for e in bm.edges if e.is_boundary), sum(1 for e in bm.edges if len(e.link_faces) > 2),
            sum(1 for v in bm.verts if not v.link_faces))


def mesh_defects(me) -> tuple:
    bm = bmesh.new()
    bm.from_mesh(me)
    d = _defects(bm)
    bm.free()
    return d


def _cut_body(me, remove: np.ndarray):
    """The body without the removed vertices, every opening capped. Returns a bmesh."""
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.verts.ensure_lookup_table()
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if remove[v.index]], context="VERTS")
    loose = [v for v in bm.verts if not v.link_faces]
    if loose:
        bmesh.ops.delete(bm, geom=loose, context="VERTS")
    open_edges = [e for e in bm.edges if e.is_boundary]
    if open_edges:
        res = bmesh.ops.holes_fill(bm, edges=open_edges, sides=100000)
        ng = [f for f in res.get("faces", []) if len(f.verts) > 3]
        if ng:
            bmesh.ops.triangulate(bm, faces=ng)
    _drop_open_scraps(bm)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return bm


def _drop_open_scraps(bm, max_share: float = 0.05) -> int:
    """Small shells that are still open after capping are scraps of the removed part (the
    inner end of a part that was a separate shell overlapping the body): delete them."""
    total = len(bm.faces)
    seen: set = set()
    dropped = 0
    for e in [e for e in bm.edges if e.is_boundary]:
        if not e.is_valid or not e.link_faces or e.link_faces[0] in seen:
            continue
        shell, stack = set(), [e.link_faces[0]]
        while stack:
            f = stack.pop()
            if f in shell:
                continue
            shell.add(f)
            for ed in f.edges:
                stack.extend(g for g in ed.link_faces if g not in shell)
        seen |= shell
        if len(shell) < max_share * total:
            verts = {v for f in shell for v in f.verts}
            bmesh.ops.delete(bm, geom=list(shell), context="FACES")
            bmesh.ops.delete(bm, geom=[v for v in verts if v.is_valid and not v.link_faces], context="VERTS")
            dropped += 1
    return dropped


def split_off(me, ids: np.ndarray, report: list | None = None) -> list:
    """Planned split (before remeshing): every part marked k > 0 in `ids` is taken out of
    `me` (the hole is capped) and returned as its own closed piece with a plug that reaches
    back into the body. [(k, piece_mesh, plug)].

    Transactional: a piece is only taken when the piece comes out closed and the body is
    left without new openings or broken edges; otherwise it stays with the body (and the
    reason goes to `report`). The body is never handed on with a hole."""
    before = mesh_defects(me)
    pieces = []
    for k in sorted(set(int(i) for i in np.unique(ids)) - {0}):
        region = ids == k
        piece = extract(me, region, grow_rings=0, name=f"forge_part_{k}")   # exact cut: no overlap band
        d = mesh_defects(piece)
        if d[0] or d[1] or len(piece.polygons) < 8:
            bpy.data.meshes.remove(piece)
            if report is not None:
                report.append((k, "the cut piece was not closed: kept with the body"))
            continue
        plug = list(piece["forge_plug"]) if "forge_plug" in piece else None
        pieces.append((k, piece, plug))
    ok = []
    for k, piece, plug in pieces:           # each cut must leave the body as sound as before
        bm = _cut_body(me, ids == k)
        d = _defects(bm)
        bm.free()
        if d[0] > before[0] or d[1] > before[1]:
            bpy.data.meshes.remove(piece)
            if report is not None:
                report.append((k, "cutting it would leave an opening in the body: kept with the body"))
            continue
        ok.append((k, piece, plug))
    if ok:
        remove = np.isin(ids, [k for k, _p, _q in ok])
        bm = _cut_body(me, remove)
        bm.to_mesh(me)
        bm.free()
        me.update()
    return ok


def attach(target, piece_obj) -> None:
    """Join a remeshed piece to the body as its own shell, root plugged inside the body:
    no boolean (booleans of overlapping organic shapes leave shards). The hidden plug is
    inside the body; skinning blends the root."""
    seal(piece_obj.data)
    _join(target, piece_obj)
