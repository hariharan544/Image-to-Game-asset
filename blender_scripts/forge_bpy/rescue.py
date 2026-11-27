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
    grown = _dilate(region, src_me, grow_rings) if grow_rings else region
    bm = bmesh.new()
    sub = _submesh(src_me, grown)                 # only the region: no full pass of the body
    bm.from_mesh(sub)
    bpy.data.meshes.remove(sub)
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
        still = [e for e in bm.edges if e.is_boundary]
        if still:
            _fan_fill(bm, still)                  # a loop the filler refuses: a fan
    else:
        plug = None
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    if plug:
        me["forge_plug"] = [*plug[0], *plug[1], plug[2]]
    return me


def _submesh(me, keep: np.ndarray):
    """A new mesh of the faces whose vertices are all in `keep` (no loose vertices, no wire
    edges: only what faces use)."""
    nl = len(me.loops)
    ls = np.empty(len(me.polygons), np.int32)
    me.polygons.foreach_get("loop_start", ls)
    lt = np.empty(len(me.polygons), np.int32)
    me.polygons.foreach_get("loop_total", lt)
    lv = np.empty(nl, np.int32)
    me.loops.foreach_get("vertex_index", lv)
    allin = np.minimum.reduceat(keep[lv].astype(np.int8), ls) > 0 if len(ls) else np.zeros(0, bool)
    fsel = np.nonzero(allin)[0]
    cnt = lt[fsel].astype(np.int64)
    first = np.repeat(np.cumsum(cnt) - cnt, cnt)
    corners = np.repeat(ls[fsel].astype(np.int64), cnt) + (np.arange(int(cnt.sum())) - first)
    used = np.unique(lv[corners]) if len(corners) else np.zeros(0, np.int64)
    remap = np.full(len(me.vertices), -1, np.int64)
    remap[used] = np.arange(len(used))
    co = np.empty(len(me.vertices) * 3, np.float32)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)[used]
    out = bpy.data.meshes.new("forge_sub")
    out.vertices.add(len(used))
    out.vertices.foreach_set("co", co.ravel())
    out.loops.add(len(corners))
    out.loops.foreach_set("vertex_index", remap[lv[corners]].astype(np.int32))
    out.polygons.add(len(fsel))
    starts = np.concatenate([[0], np.cumsum(lt[fsel])[:-1]]).astype(np.int32) if len(fsel) else np.zeros(0, np.int32)
    out.polygons.foreach_set("loop_start", starts)
    out.update(calc_edges=True)
    out.validate(clean_customdata=False)
    return out


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


def tidy(me, max_hole: int = 64) -> None:
    """Small mesh faults a remesh or a join can leave: near-duplicate vertices on a seam,
    stray points and wire edges, small holes. Bigger openings are left for the report."""
    bm = bmesh.new()
    bm.from_mesh(me)
    if bm.verts:
        size = max((max(v.co[i] for v in bm.verts) - min(v.co[i] for v in bm.verts)) for i in range(3))
        bad = {v for e in bm.edges if e.is_boundary or len(e.link_faces) > 2 for v in e.verts}
        if bad:
            bmesh.ops.remove_doubles(bm, verts=list(bad), dist=size * 2e-5)
        wire = [e for e in bm.edges if not e.link_faces]
        if wire:
            bmesh.ops.delete(bm, geom=wire, context="EDGES")
        loose = [v for v in bm.verts if not v.link_faces]
        if loose:
            bmesh.ops.delete(bm, geom=loose, context="VERTS")
        open_e = [e for e in bm.edges if e.is_boundary]
        if open_e:
            res = bmesh.ops.holes_fill(bm, edges=open_e, sides=max_hole)
            ng = [f for f in res.get("faces", []) if len(f.verts) > 3]
            if ng:
                bmesh.ops.triangulate(bm, faces=ng)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        bm.to_mesh(me)
        me.update()
    bm.free()


def mesh_defects(me) -> tuple:
    """(open edges, edges shared by more than two faces, loose vertices + wire edges), counted
    from arrays (fast on millions of faces)."""
    ne = len(me.edges)
    le = np.empty(len(me.loops), np.int32)
    me.loops.foreach_get("edge_index", le)
    per_edge = np.bincount(le, minlength=ne)
    lv = np.empty(len(me.loops), np.int32)
    me.loops.foreach_get("vertex_index", lv)
    used = np.zeros(len(me.vertices), bool)
    used[lv] = True
    return (int((per_edge == 1).sum()), int((per_edge > 2).sum()),
            int((~used).sum()) + int((per_edge == 0).sum()))


def _rim_cut(me, remove: np.ndarray, owner: np.ndarray):
    """Cut the removed vertices out of the body and cap ONLY the openings the cut made (an
    unrelated opening elsewhere is left alone and never counted for or against a cut).
    Returns (bmesh, {part k: rim defects}), the rim vertices tagged with their part."""
    # rim = body vertices sharing a FACE with a removed vertex (on quads the diagonal corner
    # shares no edge with it, yet ends up on the opening)
    ls = np.empty(len(me.polygons), np.int32)
    me.polygons.foreach_get("loop_start", ls)
    lv = np.empty(len(me.loops), np.int32)
    me.loops.foreach_get("vertex_index", lv)
    fown = np.maximum.reduceat(owner[lv], ls) if len(ls) else np.zeros(0, np.int32)
    lt = np.diff(np.append(ls, len(lv)))
    lown = np.repeat(fown, lt)
    rim_k = np.zeros(len(me.vertices), np.int32)       # body vertex next to removed part k
    m = (lown > 0) & ~remove[lv]
    rim_k[lv[m]] = lown[m]
    bm = bmesh.new()
    bm.from_mesh(me)
    tag = bm.verts.layers.int.new("forge_rim")
    bm.verts.ensure_lookup_table()
    for i in np.nonzero(rim_k)[0]:
        bm.verts[int(i)][tag] = int(rim_k[i])
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if remove[v.index]], context="VERTS")
    loose = [v for v in bm.verts if not v.link_faces and v[tag]]
    if loose:
        bmesh.ops.delete(bm, geom=loose, context="VERTS")
    # scraps first (the inner end of a part that was a separate shell, INSIDE the body): no
    # filler may close them into little lenses. A shell outside (a horn base on the head) stays
    _drop_cut_scraps(bm, tag)
    # a fan first: it only adds edges to a new centre, so a body edge across the opening (a
    # chord) can never get a third face, which made the n-gon fillers refuse the cut
    opening = _cut_openings(bm, tag)
    if opening:
        _unpinch(bm, opening)                         # two loops meeting at one vertex: split it
        opening = _cut_openings(bm, tag)
        _fan_fill(bm, opening, tag)
    rim_open = _cut_openings(bm, tag)                 # what a fan could not take
    if rim_open:
        res = bmesh.ops.holes_fill(bm, edges=rim_open, sides=100000)
        ng = [f for f in res.get("faces", []) if len(f.verts) > 3]
        if ng:
            bmesh.ops.triangulate(bm, faces=ng)
    still = _cut_openings(bm, tag)
    if still:
        try:
            res = bmesh.ops.edgeloop_fill(bm, edges=still)
            ng = [f for f in res.get("faces", []) if len(f.verts) > 3]
            if ng:
                bmesh.ops.triangulate(bm, faces=ng)
        except (RuntimeError, ValueError):
            pass
    still = _cut_openings(bm, tag)
    if still:                                         # small loops the fillers left behind
        _unpinch(bm, still)
        _fan_fill(bm, _cut_openings(bm, tag), tag)
    stray = [v for v in bm.verts if not v.link_faces and (v[tag] or not v.link_edges)]
    if stray:                                         # (left by splitting a pinch)
        bmesh.ops.delete(bm, geom=stray, context="VERTS")
    wire = [e for e in bm.edges if not e.link_faces and (e.verts[0][tag] or e.verts[1][tag])]
    if wire:
        bmesh.ops.delete(bm, geom=wire, context="EDGES")
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bad: dict = {}
    why: dict = {}
    for e in bm.edges:
        k = e.verts[0][tag] or e.verts[1][tag]
        if not k:
            continue
        if e.is_boundary and e.verts[0][tag] and e.verts[1][tag]:
            bad[k] = bad.get(k, 0) + 1
            why.setdefault(k, [0, 0])[0] += 1
        elif len(e.link_faces) > 2:               # (an old fin at the rim too: one ring further)
            bad[k] = bad.get(k, 0) + 1
            why.setdefault(k, [0, 0])[1] += 1
    _rim_cut.last_why = why
    return bm, bad


_rim_cut.last_why = {}


def _unpinch(bm, edges) -> int:
    """A vertex where two openings touch (four open edges) is split into one vertex per fan of
    faces, so each opening becomes a simple loop (the copies stay at the same place)."""
    deg: dict = {}
    for e in edges:
        if e.is_valid:
            for v in e.verts:
                deg.setdefault(v, []).append(e)
    n = 0
    for v, es in deg.items():
        if len(es) > 2 and v.is_valid:
            try:
                bmesh.utils.vert_separate(v, [e for e in es if e.is_valid])
                n += 1
            except (ValueError, RuntimeError):
                pass
    return n


def _cut_openings(bm, tag) -> list:
    """Every opening the cut made, WHOLE: seeded by open edges with both ends on the rim,
    followed along open edges, so a small old hole the cut runs into is closed with it."""
    seed = [e for e in bm.edges if e.is_valid and e.is_boundary and e.verts[0][tag] and e.verts[1][tag]]
    out, stack = set(seed), list(seed)
    while stack:
        for v in stack.pop().verts:
            for e2 in v.link_edges:
                if e2.is_boundary and e2 not in out:
                    out.add(e2)
                    stack.append(e2)
    return list(out)


def _fan_fill(bm, edges, tag=None) -> int:
    """Close every simple boundary loop (each vertex on exactly two of its open edges) with a
    fan of triangles around a new centre vertex: works on loops that are not flat or not
    convex, which the hole fillers sometimes refuse. Pinched loops are left (the caller then
    moves the cut one ring further)."""
    from mathutils import Vector
    adj: dict = {}
    for e in edges:
        for v in e.verts:
            adj.setdefault(v, []).append(e)
    seen: set = set()
    made = 0
    for start, es in list(adj.items()):
        if start in seen or len(es) != 2:
            continue
        loop, v, e = [start], start, es[0]
        seen.add(start)
        while True:
            w = e.other_vert(v)
            if w is start:
                break
            if len(adj.get(w, [])) != 2 or w in seen:
                loop = None
                break
            loop.append(w)
            seen.add(w)
            e = adj[w][1] if adj[w][0] is e else adj[w][0]
            v = w
        if not loop or len(loop) < 3:
            continue
        c = bm.verts.new(sum((x.co for x in loop), Vector()) / len(loop))
        if tag is not None:
            c[tag] = start[tag]
        for i in range(len(loop)):
            try:
                bm.faces.new((loop[i], loop[(i + 1) % len(loop)], c))
                made += 1
            except ValueError:
                pass
    return made


def _inside(bm, faces: set, pts: list) -> bool:
    """Are these points inside the rest of the mesh? Ray parity in three directions (hits on
    the shell itself are skipped), majority vote."""
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    tree = BVHTree.FromBMesh(bm)
    bm.faces.ensure_lookup_table()
    own = {f.index for f in faces}
    votes = 0
    for d in (Vector((0.37, 0.53, 0.76)), Vector((-0.61, 0.29, -0.73)), Vector((0.12, -0.95, 0.28))):
        inside = 0
        for p in pts:
            o, n, far = Vector(p), 0, 0
            while far < 10_000:
                hit = tree.ray_cast(o, d)
                if hit[0] is None:
                    break
                if hit[2] not in own:
                    n += 1
                o = hit[0] + d * 1e-6
                far += 1
            inside += n % 2
        votes += inside * 2 > len(pts)
    return votes >= 2


def _drop_cut_scraps(bm, tag, _unused=None, max_share: float = 0.05) -> int:
    """A small shell left open AT THE CUT and lying INSIDE the body is a scrap of the removed
    part (the inner end of a part that was a separate shell overlapping the body): delete it.
    A shell outside (a horn base standing on the head), shells away from the cut, and big
    ones are never touched."""
    total = len(bm.faces)
    seen: set = set()
    dropped = 0
    cap = int(max_share * total) + 1
    for e in [e for e in bm.edges if e.is_boundary and (e.verts[0][tag] or e.verts[1][tag])]:
        if not e.is_valid or not e.link_faces or e.link_faces[0] in seen:
            continue
        shell, stack = set(), [e.link_faces[0]]
        while stack and len(shell) <= cap:            # (big shells are never scraps: stop early)
            f = stack.pop()
            if f in shell:
                continue
            shell.add(f)
            for ed in f.edges:
                stack.extend(g for g in ed.link_faces if g not in shell)
        seen |= shell
        if len(shell) > cap:
            continue
        verts = list({v for f in shell for v in f.verts})
        sample = [v.co.copy() for v in verts[:: max(1, len(verts) // 7)]][:7]
        if not _inside(bm, shell, sample):
            continue
        bmesh.ops.delete(bm, geom=list(shell), context="FACES")
        bmesh.ops.delete(bm, geom=[v for v in verts if v.is_valid and not v.link_faces], context="VERTS")
        dropped += 1
    return dropped


def split_off(me, ids: np.ndarray, report: list | None = None) -> list:
    """Planned split (before remeshing): every part marked k > 0 in `ids` is taken out of
    `me` (the hole is capped) and returned as its own closed piece with a plug that reaches
    back into the body. [(k, piece_mesh, plug)].

    Transactional: a part is only taken when its piece comes out closed and its own cut
    leaves the body closed at the cut; otherwise it stays with the body (the reason goes to
    `report` as (k, why)). One pass over the body for all parts; openings elsewhere on the
    body are not this function's business."""
    regions = {k: ids == k for k in sorted(set(int(i) for i in np.unique(ids)) - {0})}
    tries = {k: 0 for k in regions}
    pieces: dict = {}

    def refuse(k, why):
        if k in pieces:
            bpy.data.meshes.remove(pieces.pop(k)[0])
        regions.pop(k, None)
        if report is not None:
            report.append((k, why))

    def grow(k) -> bool:
        """A ragged cut: move it one ring further into the body (at most twice)."""
        if tries[k] >= 2:
            return False
        tries[k] += 1
        others = np.zeros(len(ids), bool)
        for j, r in regions.items():
            if j != k:
                others |= r
        regions[k] = _dilate(regions[k], me, 1) & ~others
        if k in pieces:
            bpy.data.meshes.remove(pieces.pop(k)[0])
        return True

    while regions:
        for k in [k for k in regions if k not in pieces]:
            piece = extract(me, regions[k], grow_rings=0, name=f"forge_part_{k}")   # exact cut
            d = mesh_defects(piece)
            if d[0] or d[1] or d[2] or len(piece.polygons) < 8:
                bpy.data.meshes.remove(piece)
                if not grow(k):
                    refuse(k, "the cut piece was not closed: kept with the body")
                continue
            plug = list(piece["forge_plug"]) if "forge_plug" in piece else None
            pieces[k] = (piece, plug)
        if not pieces:
            if regions:
                continue                          # (pieces being re-cut one ring further)
            break
        if any(k not in pieces for k in regions):
            continue                              # (one is being re-cut: cut all together)
        remove = np.zeros(len(ids), bool)
        owner = np.zeros(len(ids), np.int32)
        for k in pieces:
            remove |= regions[k]
            owner[regions[k]] = k
        bm, bad = _rim_cut(me, remove, owner)
        failed = [k for k in pieces if bad.get(k)]
        if not failed and all(k in pieces for k in regions):
            bm.to_mesh(me)
            bm.free()
            me.update()
            break
        bm.free()
        for k in failed:
            if not grow(k):
                o, b = _rim_cut.last_why.get(k, [0, 0])
                refuse(k, f"cutting it would leave the body open ({o} open, {b} broken edges at the cut): "
                          "kept with the body")
    return [(k, pieces[k][0], pieces[k][1]) for k in sorted(pieces)]


def attach(target, piece_obj) -> None:
    """Join a remeshed piece to the body as its own shell, root plugged inside the body:
    no boolean (booleans of overlapping organic shapes leave shards). The hidden plug is
    inside the body; skinning blends the root."""
    seal(piece_obj.data)
    _join(target, piece_obj)
