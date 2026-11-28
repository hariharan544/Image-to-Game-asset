"""Cut-off parts for retopology.

Planned (split_off -> weld): a thin one-sided part (a tail) is cut off the original BEFORE
remeshing - the body and the piece share the cut - remeshed on its own, then welded back
into the body as one continuous skin (or, when that joint would not be clean, attached as
its own shell with its plug hidden inside the body).

Rescue (extract -> fuse): when a part of the original (a tail, a horn tip) is still missing
after density-guided re-runs, cut that region out of the original, retopologize it on its
own (quads sized for it, not for the whole body) and fuse it back into the new mesh with a
boolean union, so the result stays one closed surface for skinning.
"""

from __future__ import annotations

import bmesh
import bpy
import numpy as np

from .density import _dilate


def _in_order(bm, elems) -> list:
    """Bmesh elements of one kind (vertices, edges or faces) as a list in mesh order. A set
    (or dict) of bmesh elements runs in memory-address order, which changes from run to run
    and with whatever ran before in the process: anything summed over, sampled from, picked
    first from or handed to a bmesh op must come in a fixed order, or the same input gives a
    mesh a few last bits different - and a remesher makes another mesh of that."""
    elems = list(elems)
    if not elems:
        return elems
    seq = (bm.verts if isinstance(elems[0], bmesh.types.BMVert) else
           bm.edges if isinstance(elems[0], bmesh.types.BMEdge) else bm.faces)
    seq.index_update()
    return sorted(elems, key=lambda x: x.index)


def _extrude_edges(bm, edges) -> dict:
    """What bmesh.ops.extrude_edge_only does to open edges, built in the order of `edges`:
    the op makes its wall faces and side edges walking a table keyed by memory address, so
    their order and direction change from run to run. Each wall runs along its edge the
    other way than the face already there (wound like it). {"geom": new vertices, the new
    edges along the old ones, the walls}."""
    new_of: dict = {}
    verts, along, walls = [], [], []

    def copy(v):
        w = new_of.get(v)
        if w is None:
            w = new_of[v] = bm.verts.new(v.co, v)
            verts.append(w)
        return w
    for e in edges:
        a, b = e.verts
        if e.link_loops and e.link_loops[0].vert is a:
            a, b = b, a
        a2, b2 = copy(a), copy(b)
        f = e.link_loops[0].face if e.link_loops else None
        walls.append(bm.faces.new((a, b, b2, a2), f) if f is not None else bm.faces.new((a, b, b2, a2)))
        along.append(bm.edges.get((a2, b2)))
    return {"geom": verts + along + walls}


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


def extract(src_me, region: np.ndarray, grow_rings: int = 2, name: str = "forge_rescue",
            faces: np.ndarray | None = None, shape: tuple = (1.0, 1.0, None)):
    """A closed mesh of the region whose root continues as a tapered plug INTO the body.

    grow_rings == 0 is the planned cut (split_off): `faces` are exactly the faces the body
    loses to this part, so the piece's open edge IS the body's cut rim, and the plug continues
    the part straight into the solid along the ring's own normal, every ring vertex keeping
    its own place. grow_rings > 0 is the rescue of a lost part (fuse): the cut is kept tight
    (a couple of rings past the lost area) and the open root is extruded inward, so the
    boolean union meets the body along a clean crossing line. `shape` (depth, width, level)
    sets the planned plug (see _plug; tried in turn by _hide_plugs)."""
    from mathutils import Vector
    grown = _dilate(region, src_me, grow_rings) if grow_rings else region
    bm = bmesh.new()
    sub, on_body = _submesh(src_me, grown, faces, on_rest=True)   # only the region: no full pass
    bm.from_mesh(sub)
    bpy.data.meshes.remove(sub)
    open_edges = [e for e in bm.edges if e.is_boundary]
    plug = None
    first = len(bm.verts)
    if open_edges and bm.verts and grow_rings == 0:
        # the cut is where the piece meets the body; any other opening is an old hole of the
        # part (a tip the generator left open): closed first, it never becomes a plug
        cut = [e for e in open_edges if on_body[e.verts[0].index] and on_body[e.verts[1].index]]
        old = [e for e in open_edges if not (on_body[e.verts[0].index] and on_body[e.verts[1].index])]
        if cut and old:
            res = bmesh.ops.holes_fill(bm, edges=old, sides=100000)
            ng = [f for f in res.get("faces", []) if len(f.verts) > 3]
            if ng:
                bmesh.ops.triangulate(bm, faces=ng)
            left = [e for e in old if e.is_valid and e.is_boundary]
            if left:
                _fan_fill(bm, left)
        first = len(bm.verts)
        plug = _plug(bm, cut or open_edges, *shape)
    elif open_edges and bm.verts:
        ring = _in_order(bm, {v for e in open_edges for v in e.verts})     # (summed in mesh order)
        root = sum((v.co for v in ring), Vector()) / len(ring)
        centre = sum((v.co for v in bm.verts), Vector()) / len(bm.verts)
        # this cut crosses the lost part wherever the loss ended, often slanted across it: the
        # cut's own normal can lean far off the part (56 deg on a straight tail), so the plug
        # follows a flat ring's normal, else the part's direction (its farthest point)
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
            res = _extrude_edges(bm, edges)
            new_v = [g for g in res["geom"] if isinstance(g, bmesh.types.BMVert)]
            for v in new_v:
                rel = v.co - root
                rel -= out * rel.dot(out)                    # radial part
                v.co = root - out * (radius * depth) + rel * shrink
            is_new = set(new_v)
            edges = [g for g in res["geom"] if isinstance(g, bmesh.types.BMEdge)
                     and all(x in is_new for x in g.verts)]
        plug = (root, out, radius)
        res = bmesh.ops.holes_fill(bm, edges=[e for e in bm.edges if e.is_boundary], sides=100000)
        ng = [f for f in res.get("faces", []) if len(f.verts) > 3]
        if ng:
            bmesh.ops.triangulate(bm, faces=ng)
        still = [e for e in bm.edges if e.is_boundary]
        if still:
            _fan_fill(bm, still)                  # a loop the filler refuses: a fan
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    if plug:
        me["forge_plug"] = [*plug[0], *plug[1], plug[2]]
        me["forge_plug_first"] = int(first)          # vertices from here on are the plug's
    return me


DIRS = ((0.37, 0.53, 0.76), (-0.61, 0.29, -0.73), (0.12, -0.95, 0.28))


def _parity_inside(tree, p, eps: float = 1e-6) -> bool:
    """Is p inside the closed surface in `tree`? Ray parity in three directions, majority.
    A hit right where the last one was (the same face met again at a grazing angle, or the
    other face of the edge the ray went through) is the same crossing: counted once."""
    from mathutils import Vector
    votes = 0
    for d in DIRS:
        d = Vector(d).normalized()
        o, n, k = Vector(p), 0, 0
        while k < 2000:
            hit = tree.ray_cast(o, d)
            if hit[0] is None:
                break
            if k == 0 or hit[3] > 2 * eps:
                n += 1
            o = hit[0] + d * eps
            k += 1
        votes += n % 2
    return votes >= 2


def _ring_axis(bm, open_edges, root):
    """(axis, radius, wound outward) of a cut ring: the axis is the vector area of the open
    surface (half the sum of (a - root) x (b - root) along its boundary, in the faces' own order) - the
    normal of any closed loop, flat or not, and blind to where the part's tip went. It points
    from the cut into the part; a surface wound inward would point it the other way, so the
    side is checked on the part closed with a lid: a step along the axis must go into the part.
    Radius: median distance of the ring vertices from the axis. Wound outward: whether the
    faces' own normals point out of the solid (the vector area agrees with the axis)."""
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    ring = {v for e in open_edges for v in e.verts}
    va = Vector()
    for e in open_edges:
        lp = e.link_loops[0]
        va += (lp.vert.co - root).cross(lp.link_loop_next.vert.co - root)
    scale = max(float(np.median([(v.co - root).length for v in ring])), 1e-9)
    if va.length > 1e-6 * scale * scale:
        out = va.normalized()
    else:                                          # (a loop enclosing no area: the part's centre)
        centre = sum((v.co for v in bm.verts), Vector()) / len(bm.verts)
        out = (centre - root).normalized() if (centre - root).length > 1e-12 else Vector((0, 0, 1))
    radius = max(float(np.median([((v.co - root) - out * (v.co - root).dot(out)).length for v in ring])), 1e-6)
    tmp = bm.copy()
    try:
        _fan_fill(tmp, [e for e in tmp.edges if e.is_boundary])
        tree = BVHTree.FromBMesh(tmp)
        eps = 1e-6 * max(radius, 1e-3)
        a = _parity_inside(tree, root + out * 0.3 * radius, eps)
        b = _parity_inside(tree, root - out * 0.3 * radius, eps)
        if b and not a:
            out = -out
    finally:
        tmp.free()
    return out, radius, va.dot(out) >= 0.0        # (and: faces wound outward, normals point out)


PLUG_STEP = 0.6           # radii each plug ring goes deeper (at least)
PLUG_TAPER = (0.85, 0.6)  # each plug ring's width, against the one before
PLUG_INTO = 0.3           # a plug wall leaves the ring at least this steeply into the solid (sine)


def _first_step(start, es):
    """Of the two open edges at a loop's first vertex, the one to walk first: the one whose
    face runs into `start` (the walk then goes against the faces already there, so a fan
    over it is wound like them); else towards the lower-numbered neighbour. A fixed rule:
    the same loop is always walked the same way, in whatever order its edges came."""
    fwd = [e for e in es if e.link_loops and e.link_loops[0].vert is not start]
    return fwd[0] if len(fwd) == 1 else min(es, key=lambda e: e.other_vert(start).index)


def _loops_of(bm, edges) -> list:
    """The vertex loops (in order) of edges that form simple closed loops; [] for any part
    that is not one (a vertex on more than two of the edges). Each loop starts at its first
    vertex in mesh order and runs the way _first_step says."""
    adj: dict = {}
    for e in edges:
        for v in e.verts:
            adj.setdefault(v, []).append(e)
    if any(len(es) != 2 for es in adj.values()):
        return []
    loops, seen = [], set()
    for start in _in_order(bm, adj):
        if start in seen:
            continue
        loop, v, e = [start], start, _first_step(start, adj[start])
        seen.add(start)
        while True:
            w = e.other_vert(v)
            if w is start:
                break
            loop.append(w)
            seen.add(w)
            e = adj[w][1] if adj[w][0] is e else adj[w][0]
            v = w
        loops.append(loop)
    return loops


def _star_radial(loop, out, radial: dict, rounds: int = 400) -> dict | None:
    """The loop's offsets from the axis, smoothed along the loop until the loop goes round the
    axis once, always the same way (star-shaped: a fan from the axis then never folds).
    None when it never does (the loop does not go round the axis)."""
    import math
    if len(loop) < 3:
        return None
    e1 = out.orthogonal().normalized()
    e2 = out.cross(e1)
    r = np.array([[radial[v].dot(e1), radial[v].dot(e2)] for v in loop])

    def star(a) -> bool:
        th = np.arctan2(a[:, 1], a[:, 0])
        d = np.diff(np.append(th, th[0]))
        d = (d + math.pi) % (2 * math.pi) - math.pi
        return bool((np.all(d > 0) or np.all(d < 0)) and abs(abs(d.sum()) - 2 * math.pi) < 1e-3
                    and np.all(np.linalg.norm(a, axis=1) > 1e-12))
    for _ in range(rounds):
        if star(r):
            break
        r = 0.5 * r + 0.25 * (np.roll(r, 1, axis=0) + np.roll(r, -1, axis=0))
    else:
        return None
    return {v: e1 * float(x) + e2 * float(y) for v, (x, y) in zip(loop, r)}


def _plug(bm, open_edges, depth: float = 1.0, width: float = 1.0, level: float | None = None):
    """The plug of a planned cut: the part continued into the solid, `depth` x PLUG_STEP
    radius per ring, `width` x PLUG_TAPER as wide as the ring. Ring 1: each ring vertex keeps
    its own height along the axis (a ring that is not flat stays unfolded; with `level`, a
    vertex standing more than `level` radii above the ring's middle steps down to it first)
    and goes one step deeper, tapering towards the axis - and never leaves the ring less
    steeply into the solid than PLUG_INTO (a ring tilted against the part would otherwise
    step out through the stump below it). Ring 2: one level, a step under the deepest of
    ring 1, closed with a flat fan around the axis. Both outlines are smoothed along the ring
    until they go round the axis without turning back (a ragged cut zigzags in and out):
    every wall goes down, the lid cannot fold. A ring that never goes round the axis keeps
    its own outline and heights. Returns (root, axis from the body into the part, radius)."""
    from mathutils import Vector
    ring = _in_order(bm, {v for e in open_edges for v in e.verts})     # (summed in mesh order)
    root = sum((v.co for v in ring), Vector()) / len(ring)
    out, radius, wound_out = _ring_axis(bm, open_edges, root)
    step = PLUG_STEP * depth * radius
    mid = float(np.median([(v.co - root).dot(out) for v in ring]))
    on_ring = set(ring)

    def extrude(edges):
        res = _extrude_edges(bm, edges)
        vs = [g for g in res["geom"] if isinstance(g, bmesh.types.BMVert)]
        is_new = set(vs)
        es = [g for g in res["geom"] if isinstance(g, bmesh.types.BMEdge) and all(x in is_new for x in g.verts)]
        return vs, es

    def outline(vs, es, taper) -> tuple:
        """Each vertex's new offset from the axis, and the vertices whose loop goes round it."""
        radial = {v: (v.co - root) - out * (v.co - root).dot(out) for v in vs}
        round_ = set()
        for loop in _loops_of(bm, es):
            star = _star_radial(loop, out, radial)
            if star is None:
                continue
            have = max(float(np.median([star[v].length for v in loop])), 1e-12)
            want = float(np.median([radial[v].length for v in loop]))
            for v in loop:
                radial[v] = star[v] * (want / have)
            round_.update(loop)
        return {v: r * taper for v, r in radial.items()}, round_

    # each ring vertex's outward normal (on the part's own surface): a wall must leave the
    # ring INTO the solid
    bm.normal_update()
    sign = 1.0 if wound_out else -1.0
    normal = {v: v.normal * sign for v in ring}
    ring1, edges = extrude(open_edges)
    radial, _r = outline(ring1, edges, PLUG_TAPER[0] * width)
    for v in ring1:
        parent = next((e.other_vert(v) for e in v.link_edges if e.other_vert(v) in on_ring), None)
        along = (v.co - root).dot(out)
        top = along if level is None else min(along, mid + level * radius)
        to = root + out * (top - step) + radial[v]
        n = normal.get(parent)
        d = to - v.co
        if n is not None and n.length > 0.5 and d.length > 0 and d.dot(n) > -PLUG_INTO * d.length:
            d2 = d - n * (d.dot(n) + PLUG_INTO * d.length)
            to = v.co + d2 * (d.length / max(d2.length, 1e-12))
        v.co = to
    floor = min((v.co - root).dot(out) for v in ring1) - step
    ring2, edges = extrude(edges)
    radial, round_ = outline(ring2, edges, PLUG_TAPER[1])
    for v in ring2:
        along = (v.co - root).dot(out)
        v.co = root + out * (floor if v in round_ else along - step) + radial[v]
    before = set(bm.verts)
    _fan_fill(bm, edges)
    for c in [v for v in bm.verts if v not in before]:     # a level lid: its centre on the axis
        if all(e.other_vert(c) in round_ for e in c.link_edges):
            c.co = root + out * floor
    still = [e for e in bm.edges if e.is_boundary]
    if still:                                      # (a pinched ring: one loop per fan first)
        _unpinch(bm, still)
        _fan_fill(bm, [e for e in bm.edges if e.is_boundary])
    return (root, out, radius)


def _submesh(me, keep: np.ndarray, faces: np.ndarray | None = None, on_rest: bool = False):
    """A new mesh of the faces whose vertices are all in `keep`, or of exactly the faces
    marked in `faces` when given (no loose vertices, no wire edges: only what faces use).
    on_rest: also return, per vertex of the new mesh, whether a face left out uses it too
    (the vertices on the cut)."""
    nl = len(me.loops)
    ls = np.empty(len(me.polygons), np.int32)
    me.polygons.foreach_get("loop_start", ls)
    lt = np.empty(len(me.polygons), np.int32)
    me.polygons.foreach_get("loop_total", lt)
    lv = np.empty(nl, np.int32)
    me.loops.foreach_get("vertex_index", lv)
    if faces is not None:
        allin = np.asarray(faces, bool)
    else:
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
    if on_rest:
        rest = np.zeros(len(me.vertices), bool)
        rest[lv[~np.repeat(allin, lt)]] = True
        return out, rest[used]
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
    # the exact boolean works in threads: the same union comes in another vertex and face
    # order each run (measured: same points and faces, different order), and the weld
    # below keeps the first of two doubles - put it in order by position first
    from .common import canonical_order
    canonical_order(new, by_position=True)
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
    seam = [v for v in bm.verts if v in near and any(n not in near for n in (e.other_vert(v) for e in v.link_edges))]
    band = set(seam)
    for _ in range(2):                                   # a couple of rings around the crossing
        band |= {e.other_vert(v) for v in list(band) for e in v.link_edges}
    if band:
        for _ in range(3):
            bmesh.ops.smooth_vert(bm, verts=_in_order(bm, band), factor=0.5, use_axis_x=True, use_axis_y=True,
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
        bmesh.ops.collapse(bm, edges=_in_order(bm, short), uvs=True)
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
                # (in mesh order: of two doubles the first one listed stays)
                rim = _in_order(bm, {v for e in still for v in e.verts})
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


def same_spot_tolerance(me) -> float:
    """Two points closer than this are the same point - for us and for UVgami, which puts its
    UVs back by matching positions (its tolerance: 2e-6 of the largest coordinate, at least
    1e-5); ours is a little wider so nothing it would find ambiguous survives."""
    if not len(me.vertices):
        return 1e-5
    co = np.empty(len(me.vertices) * 3, np.float32)
    me.vertices.foreach_get("co", co)
    return max(float(np.abs(co).max()) * 3e-6, 1.5e-5)


def doubled_points(me, tol: float | None = None) -> np.ndarray:
    """Vertices that share their spot with another vertex (mask)."""
    from mathutils.kdtree import KDTree
    n = len(me.vertices)
    out = np.zeros(n, bool)
    if not n:
        return out
    tol = same_spot_tolerance(me) if tol is None else tol
    co = np.empty(n * 3, np.float32)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    # only vertices in a crowded grid cell can have a twin: few tree queries
    key = np.floor(co / (4 * tol)).astype(np.int64)
    _u, inv, cnt = np.unique(key, axis=0, return_inverse=True, return_counts=True)
    near = np.zeros(n, bool)
    for off in (0.0, 0.5):                       # (a twin across a cell border)
        k2 = np.floor(co / (4 * tol) + off).astype(np.int64)
        _u2, inv2, cnt2 = np.unique(k2, axis=0, return_inverse=True, return_counts=True)
        near |= cnt2[inv2.ravel()] > 1
    idx = np.flatnonzero(near)
    if not len(idx):
        return out
    kd = KDTree(len(idx))
    for i in idx:
        kd.insert(co[i], int(i))
    kd.balance()
    for i in idx:
        if len(kd.find_range(co[i], tol)) > 1:
            out[i] = True
    return out


def stacked_faces(me) -> np.ndarray:
    """Faces lying on top of another face: two faces sharing three corners (a duplicate, or a
    triangle over part of a quad). A closed, clean surface has none (mask)."""
    import itertools
    nf = len(me.polygons)
    out = np.zeros(nf, bool)
    if nf < 2:
        return out
    lv = np.empty(len(me.loops), np.int64)
    me.loops.foreach_get("vertex_index", lv)
    fs = np.empty(nf, np.int64)
    me.polygons.foreach_get("loop_start", fs)
    ft = np.empty(nf, np.int64)
    me.polygons.foreach_get("loop_total", ft)
    tris, fids = [], []
    for n in np.unique(ft):
        idx = np.flatnonzero(ft == n)
        corners = lv[fs[idx][:, None] + np.arange(n)]
        combos = (itertools.combinations(range(n), 3) if n <= 8
                  else [(i, (i + 1) % n, (i + 2) % n) for i in range(n)])
        for c in combos:
            tris.append(np.sort(corners[:, list(c)], axis=1))
            fids.append(idx)
    t = np.concatenate(tris)
    f = np.concatenate(fids)
    o = np.lexsort((t[:, 2], t[:, 1], t[:, 0]))
    t, f = t[o], f[o]
    same = np.all(t[1:] == t[:-1], axis=1) & (f[1:] != f[:-1])
    out[f[1:][same]] = True
    out[f[:-1][same]] = True
    return out


def _bm_stacked(bm) -> list:
    """bmesh twin of stacked_faces: [[faces sharing three corners], ...]."""
    import itertools
    groups: dict = {}
    for f in bm.faces:
        vs = sorted(v.index for v in f.verts)
        combos = (itertools.combinations(vs, 3) if len(vs) <= 8
                  else [tuple(sorted((vs[i], vs[(i + 1) % len(vs)], vs[(i + 2) % len(vs)])))
                        for i in range(len(vs))])
        for c in combos:
            groups.setdefault(c, []).append(f)
    seen, out = set(), []
    for fs in groups.values():
        fs = [f for f in dict.fromkeys(fs)]
        if len(fs) > 1 and not all(f in seen for f in fs):
            out.append(fs)
            seen.update(fs)
    return out


def _bm_defects(bm) -> int:
    """One number to compare repairs by: open + broken edges + stacked faces."""
    bm.verts.index_update()
    n = sum(1 for e in bm.edges if e.is_boundary or len(e.link_faces) > 2)
    return n + sum(len(g) for g in _bm_stacked(bm))


def _drop_stacked(bm) -> int:
    """Of every group of faces lying on each other keep the biggest (a quad over the triangle
    that covers half of it; one of two duplicates)."""
    bm.verts.index_update()
    kill = set()
    for fs in _bm_stacked(bm):
        keep = max(fs, key=lambda f: (len(f.verts), f.calc_area()))
        kill.update(f for f in fs if f is not keep)
    if kill:
        bmesh.ops.delete(bm, geom=list(kill), context="FACES_ONLY")
    return len(kill)


def _drop_loose(bm) -> None:
    wire = [e for e in bm.edges if not e.link_faces]
    if wire:
        bmesh.ops.delete(bm, geom=wire, context="EDGES")
    loose = [v for v in bm.verts if not v.link_faces]
    if loose:
        bmesh.ops.delete(bm, geom=loose, context="VERTS")


def _fill_openings(bm, max_hole: int = 0) -> None:
    open_e = [e for e in bm.edges if e.is_boundary]
    if not open_e:
        return
    res = bmesh.ops.holes_fill(bm, edges=open_e, sides=max_hole)
    ng = [f for f in res.get("faces", []) if len(f.verts) > 3]
    if ng:
        bmesh.ops.triangulate(bm, faces=ng, quad_method="BEAUTY", ngon_method="BEAUTY")
    if max_hole == 0:                       # (a local rebuild: every opening must close)
        still = [e for e in bm.edges if e.is_boundary]
        if still:
            _unpinch(bm, still)
            _fan_fill(bm, [e for e in bm.edges if e.is_boundary])


def _rebuild_defects(bm, rings: int) -> None:
    """Cut the faces around every leftover open / broken edge out (`rings` rings) and close
    the opening cleanly - the same idea as the parts cut: rebuild a small clean patch rather
    than patch a tangle."""
    bad = {v for e in bm.edges if e.is_boundary or len(e.link_faces) > 2 for v in e.verts}
    bm.verts.index_update()
    for fs in _bm_stacked(bm):
        bad.update(v for f in fs for v in f.verts)
    faces = {f for v in bad for f in v.link_faces}
    for _ in range(rings - 1):
        faces |= {g for f in faces for v in f.verts for g in v.link_faces}
    if not faces:
        return
    bmesh.ops.delete(bm, geom=list(faces), context="FACES_ONLY")
    _drop_loose(bm)
    _fill_openings(bm)


def tidy(me, max_hole: int = 64) -> dict:
    """The clean-mesh gate. Small faults a remesh or a join can leave: points on the same spot
    (welded), faces lying on each other (the smaller dropped), zero-area faces, stray points
    and wire edges, small holes (filled). What is left is rebuilt locally, one ring wider
    each try; a try is kept only if the mesh comes out with fewer faults. Returns counts."""
    out = {"welded": 0, "stacked": 0, "rebuilt": 0}
    bm = bmesh.new()
    bm.from_mesh(me)
    if not bm.verts:
        bm.free()
        return out
    tol = same_spot_tolerance(me)
    n0 = len(bm.verts)
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=tol)
    out["welded"] = n0 - len(bm.verts)
    bad = {v for e in bm.edges if e.is_boundary or len(e.link_faces) > 2 for v in e.verts}
    if bad:                                        # (a seam left unwelded by a join)
        size = max((max(v.co[i] for v in bm.verts) - min(v.co[i] for v in bm.verts)) for i in range(3))
        # (in mesh order: of two doubles the first one listed stays)
        bmesh.ops.remove_doubles(bm, verts=_in_order(bm, bad), dist=size * 2e-5)
    bmesh.ops.dissolve_degenerate(bm, dist=tol, edges=list(bm.edges))
    out["stacked"] = _drop_stacked(bm)
    _drop_loose(bm)
    _fill_openings(bm, max_hole)
    best = _bm_defects(bm)
    for rings in (1, 2, 3):
        if best == 0:
            break
        trial = bm.copy()
        _rebuild_defects(trial, rings)
        _drop_stacked(trial)
        d = _bm_defects(trial)
        if d < best:
            bm.free()
            bm, best = trial, d
            out["rebuilt"] = rings
        else:
            trial.free()
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me)
    me.update()
    bm.free()
    return out


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
    stale = bm.verts.layers.int.get("forge_rim")       # (from an earlier cut: this cut's only)
    if stale is not None:
        bm.verts.layers.int.remove(stale)
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
    bm.edges.index_update()
    return sorted(out, key=lambda e: e.index)        # (in mesh order: the same cut gives the same mesh)


def _fan_fill(bm, edges, tag=None) -> int:
    """Close every simple boundary loop (each vertex on exactly two of its open edges) with a
    fan of triangles around a new centre vertex: works on loops that are not flat or not
    convex, which the hole fillers sometimes refuse. Pinched loops are left (the caller then
    moves the cut one ring further). Each loop starts at its first vertex in mesh order and
    runs the way _first_step says: the same loop always gets the same fan (the centre summed
    in the same order), wound like the faces around it, in whatever order its edges came."""
    from mathutils import Vector
    adj: dict = {}
    for e in edges:
        for v in e.verts:
            adj.setdefault(v, []).append(e)
    seen: set = set()
    made = 0
    for start in _in_order(bm, adj):
        es = adj[start]
        if start in seen or len(es) != 2:
            continue
        loop, v, e = [start], start, _first_step(start, es)
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
        if tag is not None:                         # (the loop's part: an old hole on it has none)
            c[tag] = next((x[tag] for x in loop if x[tag]), 0)
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
        verts = _in_order(bm, {v for f in shell for v in f.verts})     # (the same sample every run)
        sample = [v.co.copy() for v in verts[:: max(1, len(verts) // 7)]][:7]
        if not _inside(bm, shell, sample):
            continue
        bmesh.ops.delete(bm, geom=_in_order(bm, shell), context="FACES")
        bmesh.ops.delete(bm, geom=[v for v in verts if v.is_valid and not v.link_faces], context="VERTS")
        dropped += 1
    return dropped


PLUG_SHOWS = 0.03          # share of a plug's area that may lie outside the body (along the cut ring itself)
PLUG_FOLDS_IN = 0.1        # a plug with more of its area inside the part it continues is folded back into it
# (depth, width, level) of the plugs tried in turn while one shows or folds (see _plug)
PLUG_SHAPES = ((1.0, 1.0, None), (1.0, 1.0, 0.25), (0.6, 0.75, None), (0.35, 0.55, None))


def _plug_faults(pme, tree, eps: float) -> tuple:
    """(folded, share of the plug's area outside the closed surface in `tree`) of a cut
    piece; the plug is every face using a vertex the plug added. Folded: a plug face crosses
    another face, or more than PLUG_FOLDS_IN of the plug lies inside the part's own solid (the
    part closed with a lid over the cut): walls hanging inside the part they continue pinch
    the piece, and the remesher makes a crumpled root of it."""
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    first = int(pme.get("forge_plug_first", len(pme.vertices)))
    plugf = [p.index for p in pme.polygons if max(p.vertices) >= first]
    if not plugf:
        return False, 0.0
    # (a plug face can only cross the faces around the root: the rest of a long part is left out)
    pl = list(pme["forge_plug"])
    root, reach = Vector(pl[0:3]), 6.0 * float(pl[6])
    inplug = set(plugf)
    near = [p for p in pme.polygons if p.index in inplug or (p.center - root).length < reach]
    polys = [set(p.vertices) for p in near]
    t = BVHTree.FromPolygons([v.co.copy() for v in pme.vertices], [tuple(p.vertices) for p in near])
    pset = {k for k, p in enumerate(near) if max(p.vertices) >= first}
    if any((i in pset or j in pset) and not polys[i] & polys[j] for i, j in t.overlap(t) if i < j):
        return True, 1.0
    own = bmesh.new()
    try:
        own.from_mesh(pme)
        own.verts.ensure_lookup_table()
        bmesh.ops.delete(own, geom=[v for v in own.verts if v.index >= first], context="VERTS")
        _fan_fill(own, [e for e in own.edges if e.is_boundary])
        t_own = BVHTree.FromBMesh(own)
    finally:
        own.free()
    area = outside = inner = 0.0
    for i in plugf:
        p = pme.polygons[i]
        area += p.area
        if not _parity_inside(tree, p.center, eps):
            outside += p.area
        if _parity_inside(t_own, p.center, eps):
            inner += p.area
    return inner > PLUG_FOLDS_IN * area, (outside / area if area > 0 else 0.0)


def _hide_plugs(me, bm, pieces: dict, regions: dict) -> list:
    """A plug must stay hidden in the body and never fold. A part leaving the body at a slant
    (or a ragged cut tilting the ring) can take a full-size plug out through the body's surface
    next to the root: such a piece is cut again with a shorter, narrower plug, and the one that
    does not fold and shows least is kept. Returns the parts whose every plug folds (a root
    running along the body: no plug fits under it).
    `bm` is the body with its cut capped; `me` still the uncut original."""
    from mathutils.bvhtree import BVHTree
    tree = None
    folded = []
    for k in sorted(pieces):                         # (by part id: the refusals in that order)
        piece, plug, mine = pieces[k]
        if plug is None:
            continue
        if tree is None:
            tree = BVHTree.FromBMesh(bm)
        eps = 1e-6 * max(float(plug[6]), 1e-3)
        best = (_plug_faults(piece, tree, eps), piece, plug)
        for shape in PLUG_SHAPES[1:]:
            if not best[0][0] and best[0][1] <= PLUG_SHOWS:
                break
            alt = extract(me, regions[k], grow_rings=0, name=f"forge_part_{k}", faces=mine, shape=shape)
            d = mesh_defects(alt)
            if d[0] or d[1] or d[2] or "forge_plug" not in alt:
                bpy.data.meshes.remove(alt)
                continue
            faults = _plug_faults(alt, tree, eps)
            if faults < best[0]:
                bpy.data.meshes.remove(best[1])
                best = (faults, alt, list(alt["forge_plug"]))
            else:
                bpy.data.meshes.remove(alt)
        pieces[k] = (best[1], best[2], mine)
        best[1]["forge_plug_shows"] = round(float(best[0][1]), 3)   # (kept when every shape shows)
        if best[0][0]:
            folded.append(k)
    return folded


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
    ls = np.empty(len(me.polygons), np.int32)
    me.polygons.foreach_get("loop_start", ls)
    lv = np.empty(len(me.loops), np.int32)
    me.loops.foreach_get("vertex_index", lv)

    def ownership() -> np.ndarray:
        """Which part takes each face: the one _rim_cut gives it (the highest part among its
        corners). Both sides of the cut are then bounded by the same curve, and a face that
        touches two parts belongs to exactly one of them."""
        owner = np.zeros(len(ids), np.int32)
        for k in sorted(regions):
            owner[regions[k]] = k
        return np.maximum.reduceat(owner[lv], ls) if len(ls) else np.zeros(0, np.int32)

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
        fown = ownership()
        for k in sorted(k for k in regions if k not in pieces):
            mine = fown == k
            piece = extract(me, regions[k], grow_rings=0, name=f"forge_part_{k}", faces=mine)   # exact cut
            d = mesh_defects(piece)
            if d[0] or d[1] or d[2] or len(piece.polygons) < 8:
                bpy.data.meshes.remove(piece)
                if not grow(k):
                    refuse(k, "the cut piece was not closed: kept with the body")
                continue
            plug = list(piece["forge_plug"]) if "forge_plug" in piece else None
            pieces[k] = (piece, plug, mine)
        if not pieces:
            if regions:
                continue                          # (pieces being re-cut one ring further)
            break
        if any(k not in pieces for k in regions):
            continue                              # (one is being re-cut: cut all together)
        fown = ownership()                        # a neighbour re-cut or refused since: take again
        stale = [k for k in sorted(pieces) if not np.array_equal(pieces[k][2], fown == k)]
        for k in stale:
            bpy.data.meshes.remove(pieces.pop(k)[0])
        if stale:
            continue
        remove = np.zeros(len(ids), bool)
        owner = np.zeros(len(ids), np.int32)
        for k in sorted(pieces):
            remove |= regions[k]
            owner[regions[k]] = k
        bm, bad = _rim_cut(me, remove, owner)
        # (parts by id, never in the order they happened to be cut - a part re-cut one ring
        # further comes back last: two neighbours grown one ring further in another order
        # would share the faces between them differently)
        failed = [k for k in sorted(pieces) if bad.get(k)]
        folded = [] if failed else _hide_plugs(me, bm, pieces, regions)
        if folded:
            bm.free()
            for k in folded:
                # (every plug crosses itself or folds back into the part: a root running along
                # the body, or a long thin slot - a fin, a sail, a wing root - that one cone-shaped
                # plug cannot fill. The part is remeshed with the body instead)
                refuse(k, "its root is too long and thin, or lies along the body, for a hidden plug: "
                          "kept with the body")
            continue
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
    tidy(piece_obj.data)                 # a clean piece: nothing stacked, nothing open
    _join(target, piece_obj)


# ------------------------------------------------------------------ one skin at a cut root

OPEN_LAYER = "forge_open"
JOINT_ROOM = 1                 # rings of faces each side gives up so the bridge has room
JOINT_CUTS = 1                 # rings put back across the bridge (tried first; then none)
# the joints tried in turn: (rings put back, the middle ring seated on the fold)
JOINT_TRIES = ((JOINT_CUTS, True), (JOINT_CUTS, False), (0, False))
JOINT_RELAX = (4, 8, 16)       # relax + lay-on-the-original rounds for the joint band (checked after each)
MIN_JOINT_ANGLE = 5.0          # degrees: a smaller corner is a needle that shades and skins badly
JOINT_FIT = 0.1                # joint faces may stand off the original by this much of the part's radius
JOINT_FIT_SLACK = 1.5          # ... or by half as much again as the remeshed faces around the joint do


def _tree_of(me, near=None, reach: float = 0.0):
    """A BVH tree of a mesh (through a bmesh: no Python list per vertex and face, which
    costs seconds and a gigabyte on a multi-million-face original), or of only its faces with
    a corner within `reach` of `near` (for nearest-point questions near a joint; ray parity
    needs the whole closed surface)."""
    from mathutils.bvhtree import BVHTree
    if near is None:
        bm = bmesh.new()
        try:
            bm.from_mesh(me)
            return BVHTree.FromBMesh(bm)
        finally:
            bm.free()
    nv = len(me.vertices)
    co = np.empty(nv * 3, np.float32)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    ls = np.empty(len(me.polygons), np.int64)
    me.polygons.foreach_get("loop_start", ls)
    lt = np.empty(len(me.polygons), np.int64)
    me.polygons.foreach_get("loop_total", lt)
    lv = np.empty(len(me.loops), np.int64)
    me.loops.foreach_get("vertex_index", lv)
    close = np.linalg.norm(co - np.array(near[:], np.float32), axis=1) < reach
    fsel = np.flatnonzero(np.maximum.reduceat(close[lv].astype(np.int8), ls) > 0) if len(ls) else ls
    used = np.unique(np.concatenate([lv[ls[f]:ls[f] + lt[f]] for f in fsel])) if len(fsel) else np.zeros(0, np.int64)
    remap = np.full(nv, -1, np.int64)
    remap[used] = np.arange(len(used))
    polys = [tuple(remap[lv[ls[f]:ls[f] + lt[f]]].tolist()) for f in fsel]
    return BVHTree.FromPolygons([tuple(c) for c in co[used].tolist()], polys)


def _folds_near(me, root, reach: float) -> int:
    """Faces within `reach` of the root that cross another face (faces sharing a corner
    aside): folds a 'welded' joint may still have around it (from the part's own remesh)."""
    from mathutils.bvhtree import BVHTree
    nv = len(me.vertices)
    co = np.empty(nv * 3, np.float32)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    cen = np.empty(len(me.polygons) * 3, np.float32)
    me.polygons.foreach_get("center", cen)
    near = np.flatnonzero(np.linalg.norm(cen.reshape(-1, 3) - np.array(root[:], np.float32), axis=1) < reach)
    if len(near) < 2:
        return 0
    polys = [tuple(me.polygons[int(i)].vertices) for i in near]
    t = BVHTree.FromPolygons([tuple(c) for c in co.tolist()], polys)
    sets = [set(p) for p in polys]
    return len({i for a, b in t.overlap(t) if a != b and not sets[a] & sets[b] for i in (a, b)})


def _bad_edges(bm) -> int:
    """Open edges + edges shared by more than two faces."""
    return sum(1 for e in bm.edges if e.is_boundary or len(e.link_faces) > 2)


def _inside_from(bm, tree, seed_pt, root, reach: float, eps: float) -> set:
    """The faces of `bm` lying inside the closed surface in `tree`, CONNECTED to the face
    nearest `seed_pt` and within `reach` of the root: a tail tuft resting against a leg is
    inside the body too, but it is not the joint."""
    from mathutils.bvhtree import BVHTree
    bm.faces.index_update()
    bm.faces.ensure_lookup_table()
    memo: dict = {}

    def inside(f) -> bool:
        r = memo.get(f)
        if r is None:
            c = f.calc_center_median()
            r = memo[f] = (c - root).length < reach and _parity_inside(tree, c, eps)
        return r
    near = BVHTree.FromBMesh(bm).find_nearest_range(seed_pt, max(reach * 0.25, 1e-9))
    near.sort(key=lambda h: h[3])
    seed = next((bm.faces[h[2]] for h in near[:24] if inside(bm.faces[h[2]])), None)
    if seed is None:
        return set()
    comp, stack = {seed}, [seed]
    while stack:
        f = stack.pop()
        for e in f.edges:
            for g in e.link_faces:
                if g not in comp and inside(g):
                    comp.add(g)
                    stack.append(g)
    return comp


def _cut_edges(bm, kill: set) -> list:
    """Edges between a face to delete and a face to keep: the opening the cut will make (in
    mesh order)."""
    return _in_order(bm, {e for f in kill for e in f.edges
                          if len(e.link_faces) == 2 and (e.link_faces[0] in kill) != (e.link_faces[1] in kill)})


def _open_cut(bm, kill: set, root, reach: float):
    """Delete `kill` so that this side keeps ONE piece with ONE simple opening. Kept faces
    the cut encloses (islands) go with it, but only small ones near the joint (a bigger piece
    means the cut went somewhere it should not); a vertex where the opening touches itself
    takes its faces with it; both repeated until nothing changes. Returns (opening edges,
    None) or ([], reason)."""
    kill = set(kill)
    for _round in range(8):
        rimv = {v for f in kill for v in f.verts}
        # an old hole the cut runs into goes with the cut (the faces along it): the opening
        # must be one loop, not a loop touching a hole
        holes = {e for v in rimv for e in v.link_edges if e.is_boundary and e.link_faces[0] not in kill}
        stack = list(holes)
        while stack:
            for v in stack.pop().verts:
                for e2 in v.link_edges:
                    if e2.is_boundary and e2 not in holes:
                        holes.add(e2)
                        stack.append(e2)
        if holes:
            if any((v.co - root).length > reach for e in holes for v in e.verts):
                return [], "hole"
            kill.update(e.link_faces[0] for e in holes)
            rimv = {v for f in kill for v in f.verts}
        seeds = _in_order(bm, {g for v in rimv for g in v.link_faces if g not in kill})
        comps, seen = [], set()
        for f0 in seeds:
            if f0 in seen:
                continue
            comp, stack = [f0], [f0]
            seen.add(f0)
            while stack:
                f = stack.pop()
                for e in f.edges:
                    for g in e.link_faces:
                        if g not in seen and g not in kill:
                            seen.add(g)
                            comp.append(g)
                            stack.append(g)
            comps.append(comp)
        if not comps:
            return [], "inside"
        # the biggest piece stays (of two the same size: the one first in mesh order - the
        # seeds come in mesh order, and max keeps the first)
        best = max(comps, key=len)
        islands = [c for c in comps if c is not best]
        for c in islands:
            if any((v.co - root).length > reach for f in c for v in f.verts):
                return [], "island"
            kill.update(c)
        deg: dict = {}
        for e in _cut_edges(bm, kill):
            for v in e.verts:
                deg[v] = deg.get(v, 0) + 1
        pinch = [v for v, n in deg.items() if n > 2]
        if not (pinch or holes or islands):
            break
        kill.update(f for v in pinch for f in v.link_faces)
    else:
        return [], "openings"
    opening = _cut_edges(bm, kill)
    bmesh.ops.delete(bm, geom=list(kill), context="FACES")
    return [e for e in opening if e.is_valid], None


def _one_loop(edges) -> bool:
    """Do these edges form exactly one simple closed loop?"""
    if len(edges) < 3:
        return False
    vs: dict = {}
    for e in edges:
        for v in e.verts:
            vs.setdefault(v, []).append(e)
    if any(len(es) != 2 for es in vs.values()):
        return False
    seen, stack = {edges[0]}, [edges[0]]
    while stack:
        e = stack.pop()
        for v in e.verts:
            for e2 in vs[v]:
                if e2 not in seen:
                    seen.add(e2)
                    stack.append(e2)
    return len(seen) == len(edges)


def _even_loops(bm, lay) -> set:
    """Give the shorter cut loop as many edges as the longer one (its longest edges split in
    half), so the bridge is one ring of quads instead of fans of needle triangles. Returns
    the faces that got an extra corner (triangulated once the joint is relaxed)."""
    loops = {m: [e for e in bm.edges if e[lay] == m] for m in (1, 2)}
    short = 1 if len(loops[1]) < len(loops[2]) else 2
    edges = loops[short]
    grown: set = set()
    for _ in range(abs(len(loops[1]) - len(loops[2]))):
        e = max(edges, key=lambda x: x.calc_length())
        grown.update(e.link_faces)
        ne, _nv = bmesh.utils.edge_split(e, e.verts[0], 0.5)
        ne[lay] = short
        edges.append(ne)
    return grown


def _seat_on_fold(mids, rim_b, rim_p, t_full) -> int:
    """Put the ring across the middle of the joint ON the fold of the original between the
    body and the part: for each middle vertex, the point of the original that lies deepest
    under the straight line from its body-side neighbour to its part-side neighbour (on a
    sharp crease the crease itself, on a round fillet its middle). A modeller's support loop:
    the quads then lie on one side of the fold each instead of cutting across it as chords
    (measured on a coarse bull: face centres 0.3 radius off the crease). Returns how many
    vertices moved."""
    moved = 0
    for m in mids:
        if not m.is_valid:
            continue
        nb = [e.other_vert(m) for e in m.link_edges]
        a = next((w for w in nb if w in rim_b), None)
        b = next((w for w in nb if w in rim_p), None)
        if a is None or b is None:
            continue
        ab = b.co - a.co
        length = ab.length
        if length < 1e-12:
            continue
        u = ab / length
        mid = (a.co + b.co) * 0.5
        hit = t_full.find_nearest(mid)
        if hit[0] is None:
            continue
        d = hit[0] - mid
        d -= u * d.dot(u)
        if d.length < 0.02 * length:            # the original runs along the line: no fold
            continue
        d.normalize()
        best, depth = None, 0.0
        for t in np.linspace(0.15, 0.85, 15):
            h = t_full.ray_cast(a.co + ab * float(t), d, length)
            if h[0] is not None and h[3] > depth:
                best, depth = h[0], h[3]
        if best is not None:
            m.co = best
            moved += 1
    return moved


def _joint_faults(bm, band: set, t_full, before: int, rad: float = 0.0):
    """Why the welded joint is not acceptable, or None: it added open or broken edges, a
    joint face has a needle corner, faces the other way than the original surface, crosses
    another face, or stands off the original farther than the faces around it do."""
    import math
    from mathutils.bvhtree import BVHTree
    bm.normal_update()
    if _bad_edges(bm) > before or any(e.is_boundary or len(e.link_faces) > 2 for v in band for e in v.link_edges):
        return "open edges"
    bfaces = {f for v in band for f in v.link_faces}
    small = math.radians(MIN_JOINT_ANGLE)
    for f in bfaces:
        if f.calc_area() <= 0.0 or min(lp.calc_angle() for lp in f.loops) < small:
            return "thin faces"

    def agree(f) -> float:
        hit = t_full.find_nearest(f.calc_center_median())
        return f.normal.dot(hit[1]) if hit[0] is not None else 0.0
    # the original's own winding is the reference (an inward-wound original flips every
    # answer): read it on the faces just outside the joint band
    ring = {g for f in bfaces for v in f.verts for g in v.link_faces} - bfaces
    votes = [agree(f) for f in ring]
    sign = 1.0 if sum(a >= 0 for a in votes) >= sum(a < 0 for a in votes) else -1.0
    if any(sign * agree(f) < 0 for f in bfaces):
        return "flipped faces"
    bm.verts.index_update()
    bm.faces.index_update()
    bm.faces.ensure_lookup_table()
    blist = sorted(bfaces, key=lambda f: f.index)
    tb = BVHTree.FromPolygons([v.co.copy() for v in bm.verts], [tuple(v.index for v in f.verts) for f in blist])
    tall = BVHTree.FromBMesh(bm)
    for i, j in tb.overlap(tall):
        f, g = blist[i], bm.faces[j]
        if f is g or set(f.verts) & set(g.verts):
            continue
        return "crossing faces"
    if rad > 0.0 and ring:
        # it follows the original as closely as the remeshed faces around the joint do (their
        # own chord error, half as much again; at least JOINT_FIT of the part's radius): nearly
        # every joint face (19 in 20) within that, and none farther than twice that
        def off(f) -> float:
            hit = t_full.find_nearest(f.calc_center_median())
            return hit[3] if hit[0] is not None else 0.0
        around = [off(f) for f in ring]
        joint = [off(f) for f in bfaces]
        typical = max(JOINT_FIT * rad, JOINT_FIT_SLACK * float(np.percentile(around, 95)))
        worst = max(2 * JOINT_FIT * rad, JOINT_FIT_SLACK * max(around))
        if float(np.percentile(joint, 95)) > typical or max(joint) > max(worst, 2 * typical):
            return "off the surface"
    return None


def _bridge(bm, t_full, before: int, cuts: int, rad: float = 0.0, seat: bool = True):
    """Bridge the two marked cut loops of `bm` (as many edges on both: a ring of quads), put
    `cuts` rings back across the bridge (the room given up for it: the joint keeps about the
    body's quad size and follows the fillet), relax the band and lay it on the ORIGINAL
    surface, which has the real fillet, the middle ring seated on the fold - relaxing further
    only while the one fault left is a needle corner or a face off the original. Returns why
    the joint is not acceptable, or None."""
    lay = bm.edges.layers.int.get(OPEN_LAYER)
    grown = _even_loops(bm, lay)
    rim = [e for e in bm.edges if e[lay]]
    mids: list = []
    try:
        res = bmesh.ops.bridge_loops(bm, edges=rim)
    except (RuntimeError, ValueError, TypeError):
        return "bridge"
    joint = [f for f in res.get("faces", []) if f.is_valid]
    if not joint:
        return "bridge"
    js = set(joint)
    cross = _in_order(bm, {e for f in joint for e in f.edges if not e[lay] and all(g in js for g in e.link_faces)})
    if cross and cuts:
        inner = set(bmesh.ops.subdivide_edges(bm, edges=cross, cuts=cuts, use_grid_fill=True)["geom_inner"])
        joint = [f for f in bm.faces if f in js or any(v in inner for v in f.verts)]
        if cuts == 1 and seat:
            mids = [v for v in bm.verts if v in inner]
    # (read after the subdivision: it invalidates vertex references, not the edge layer)
    rim_b = {v for e in bm.edges if e[lay] == 2 for v in e.verts}
    rim_p = {v for e in bm.edges if e[lay] == 1 for v in e.verts}
    band = {v for f in joint for v in f.verts}
    for _ in range(2):
        band |= {e.other_vert(v) for v in list(band) for e in v.link_edges}
    band_l = _in_order(bm, band)
    done, shell, why = 0, None, None
    for total in JOINT_RELAX:
        for _ in range(total - done):
            bmesh.ops.smooth_vert(bm, verts=band_l, factor=0.5, use_axis_x=True, use_axis_y=True,
                                  use_axis_z=True)
            for v in band_l:
                hit = t_full.find_nearest(v.co)
                if hit[0] is not None:
                    v.co = hit[0]
        done = total
        if mids:
            _seat_on_fold(mids, rim_b, rim_p, t_full)
        if shell is None:
            ng = _in_order(bm, [f for f in grown if f.is_valid and len(f.verts) > 4])
            if ng:
                res = bmesh.ops.triangulate(bm, faces=ng, quad_method="BEAUTY", ngon_method="BEAUTY")
                joint += [f for f in res.get("faces", []) if f.is_valid]
            shell, stack = set(joint), list(joint)
            while stack:
                f = stack.pop()
                for e in f.edges:
                    for g in e.link_faces:
                        if g not in shell:
                            shell.add(g)
                            stack.append(g)
            shell = _in_order(bm, shell)
        bmesh.ops.recalc_face_normals(bm, faces=shell)
        why = _joint_faults(bm, band, t_full, before, rad)
        if why not in ("thin faces", "off the surface"):
            break
    return why


def _weld(target, piece_obj, src_me, cap_me, full_me, trees: dict | None = None):
    """The weld itself, on bmesh copies: (reason or None, [body loop, part loop]). The target
    mesh is written only when the joint passed every check. `trees` keeps the capped body's
    tree for the next part (built once per body)."""
    from mathutils import Vector
    pl = list(src_me["forge_plug"]) if "forge_plug" in src_me else []
    if len(pl) < 7:
        return "no plug", []
    root, out, rad = Vector(pl[0:3]), Vector(pl[3:6]).normalized(), float(pl[6])
    reach = 4.0 * rad
    eps = 1e-6 * max(rad, 1e-3)
    bb, bp = bmesh.new(), bmesh.new()
    try:
        bb.from_mesh(target.data)
        tmp = piece_obj.data.copy()
        tmp.transform(target.matrix_world.inverted() @ piece_obj.matrix_world)
        bp.from_mesh(tmp)
        bpy.data.meshes.remove(tmp)
        for bm_ in (bb, bp):            # (before any cut: a new layer invalidates references)
            lay = bm_.edges.layers.int.get(OPEN_LAYER) or bm_.edges.layers.int.new(OPEN_LAYER)
            for e in bm_.edges:
                e[lay] = 0
        before = _bad_edges(bb) + _bad_edges(bp)
        # the body opens where the part's solid covers it, the part where it is plug (inside
        # the body), each flood-filled from the joint
        trees = {} if trees is None else trees
        if trees.get("cap_of") != cap_me.name:
            trees.update(cap=_tree_of(cap_me), cap_of=cap_me.name)
        kill_b = _inside_from(bb, _tree_of(src_me), root, root, reach, eps)
        kill_p = _inside_from(bp, trees["cap"], root - out * 1.2 * rad, root, reach, eps)
        if not kill_b or not kill_p:
            return "no overlap", [0, 0]
        for _ in range(JOINT_ROOM):     # room for the bridge: one more ring of faces on each side
            kill_b |= {g for f in kill_b for v in f.verts for g in v.link_faces}
            kill_p |= {g for f in kill_p for v in f.verts for g in v.link_faces}
        lb, why = _open_cut(bb, kill_b, root, 1.5 * reach)
        if why:
            return why, [0, 0]
        lp, why = _open_cut(bp, kill_p, root, 1.5 * reach)
        loops = [len(lb), len(lp)]
        if why:
            return why, loops
        if not _one_loop(lb) or not _one_loop(lp):
            return "openings", loops
        lay_b, lay_p = bb.edges.layers.int.get(OPEN_LAYER), bp.edges.layers.int.get(OPEN_LAYER)
        for e in lb:
            e[lay_b] = 2
        for e in lp:
            e[lay_p] = 1
        tmp = bpy.data.meshes.new("forge_weld_tmp")
        bp.to_mesh(tmp)
        bb.from_mesh(tmp)
        bpy.data.meshes.remove(tmp)
        lay = bb.edges.layers.int.get(OPEN_LAYER)
        rim = [e for e in bb.edges if e[lay]]        # ONLY the two cut loops (never an old hole)
        if sorted((sum(1 for e in rim if e[lay] == 2), sum(1 for e in rim if e[lay] == 1))) != sorted(loops):
            return "openings", loops
        t_full = _tree_of(full_me, root, 4.0 * reach)      # (the original near the joint)
        why = None
        for cuts, seat in JOINT_TRIES:                  # the finer joint first
            work = bb.copy()
            try:
                why = _bridge(work, t_full, before, cuts, rad, seat)
                if why is None:
                    work.edges.layers.int.remove(work.edges.layers.int.get(OPEN_LAYER))
                    work.to_mesh(target.data)
                    target.data.update()
                    return None, loops
            finally:
                work.free()
        return why, loops
    finally:
        bb.free()
        bp.free()


def weld(target, piece_obj, src_me, cap_me, full_me, info: dict | None = None, trees: dict | None = None) -> str:
    """Join a remeshed cut-off part to the body as ONE continuous skin: open the body where
    the part's solid covers it (src_me: the cut piece with its plug), open the part where it
    is plug (inside cap_me, the capped body), give the shorter opening as many edges as the
    longer, bridge the two openings - only those two loops - and lay the joint band on the
    uncut original (full_me), which has the real fillet. All on copies: the body is changed
    only when the joint adds no open or broken edge, no face crosses another or faces
    inward, and no joint corner is a needle; otherwise the part is attached as its own shell
    (its plug hidden in the body). Returns 'welded' or 'attached: <reason>'; `info` gets
    that and the two loop sizes, and for a weld the faces still folded near the root (the
    part's own remesh can fold there: 'welded' alone would not say the root is clean).
    `trees`: a dict kept across the parts of one body (its trees are built once)."""
    if info is None:
        info = {}
    seal(piece_obj.data)
    tidy(piece_obj.data)                 # a clean piece: nothing stacked, nothing open
    try:
        why, loops = _weld(target, piece_obj, src_me, cap_me, full_me, trees)
    except (RuntimeError, ValueError) as ex:            # (bmesh refused something: never half a weld)
        why, loops = "error", []
        info["error"] = str(ex)[:120]
    info["loops"] = loops
    if why is None:
        info["joint"] = "welded"
        pl = list(src_me["forge_plug"])
        from mathutils import Vector
        folds = _folds_near(target.data, Vector(pl[0:3]), 2.5 * float(pl[6]))
        if folds:
            info["folds_near"] = folds
        return "welded"
    attach(target, piece_obj)
    info["joint"] = f"attached: {why}"
    return info["joint"]
