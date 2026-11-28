"""Test bodies shaped like the director's AI meshes (voxel-fused, one closed surface)."""

from __future__ import annotations

import bpy
import numpy as np

CURL = [(0, 0.0, 0.97), (0, 0.12, 0.95), (0.0, 0.22, 0.80), (0.02, 0.27, 0.62), (0.10, 0.28, 0.45),
        (0.28, 0.27, 0.36), (0.42, 0.25, 0.36)]


def curled_tail(curl: float = 1.0, r: float = 0.022, voxel: float = 0.008, path=None):
    """The humanoid fixture with a tail rooted inside the rump on the centre line, hanging
    straight down for a while, then curling to the side (+X for curl=1, -X for -1), with a
    tuft. Returns (body object, tail polyline)."""
    import bmesh
    from mathutils import Matrix, Vector

    from forge_bpy import fixture
    bpy.ops.wm.read_homefile(use_empty=True)
    fixture.humanoid({"out": "/tmp/_forge_curl.glb"})
    body = bpy.data.objects["Body"]
    bm = bmesh.new()
    bm.from_mesh(body.data)
    pts = [Vector((p[0] * curl, p[1], p[2])) for p in (path or CURL)]
    for a, b in zip(pts, pts[1:]):
        d = b - a
        m = Matrix.Translation((a + b) / 2) @ d.to_track_quat("Z", "Y").to_matrix().to_4x4()
        bmesh.ops.create_cone(bm, cap_ends=True, segments=12, radius1=r, radius2=r, depth=d.length + r, matrix=m)
    bmesh.ops.create_uvsphere(bm, u_segments=12, v_segments=8, radius=r * 2.2, matrix=Matrix.Translation(pts[-1]))
    bm.to_mesh(body.data)
    bm.free()
    mod = body.modifiers.new("v", "REMESH")
    mod.mode, mod.voxel_size = "VOXEL", voxel
    dg = bpy.context.evaluated_depsgraph_get()
    dg.update()
    me = bpy.data.meshes.new_from_object(body.evaluated_get(dg))
    body.modifiers.remove(mod)
    body.data = me
    return body, pts


def arc(pts, p):
    """(distance to the polyline, arc length at the nearest point)."""
    from mathutils import Vector
    best, acc = (1e9, 0.0), 0.0
    p = Vector(p)
    for a, b in zip(pts, pts[1:]):
        ab = b - a
        t = max(0.0, min(1.0, (p - a).dot(ab) / ab.length_squared))
        d = (p - (a + ab * t)).length
        if d < best[0]:
            best = (d, acc + t * ab.length)
        acc += ab.length
    return best


def biped(arm_dz: float = 0.0, tail: bool = False, res: float = 0.025):
    """A round cartoon biped (metaballs, T-pose). The right arm's hand is arm_dz higher than
    the left one: the pose asymmetry AI meshes have."""
    import bmesh
    from mathutils import Vector
    bpy.ops.wm.read_homefile(use_empty=True)
    mb = bpy.data.metaballs.new("mb")
    mb.resolution, mb.threshold = res, 0.6
    ob = bpy.data.objects.new("mb", mb)
    bpy.context.scene.collection.objects.link(ob)

    def ball(p, r, s=(1, 1, 1)):
        e = mb.elements.new(type="ELLIPSOID")
        e.co, e.radius = p, 1.0
        e.size_x, e.size_y, e.size_z = r * s[0], r * s[1], r * s[2]
        e.stiffness = 2.0

    def chain(a, b, r0, r1, n=14):
        a, b = Vector(a), Vector(b)
        for i in range(n + 1):
            t = i / n
            ball(a.lerp(b, t), (r0 * (1 - t) + r1 * t) * 2.0)
    ball((0, 0, 0.75), 0.75, (1, 0.9, 1.15))
    ball((0, 0, 1.45), 0.5)
    chain((0.3, 0, 1.05), (0.95, 0, 1.10), 0.13, 0.10)
    chain((-0.3, 0, 1.05), (-0.95, 0, 1.10 + arm_dz), 0.13, 0.10)
    for x in (1, -1):
        chain((0.2 * x, 0, 0.5), (0.22 * x, 0, 0.05), 0.16, 0.14, 8)
    if tail:
        chain((0, 0.35, 0.45), (0.25, 0.75, 0.25), 0.04, 0.03, 20)
        ball((0.28, 0.80, 0.24), 0.14)
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(ob.evaluated_get(dg))
    bpy.data.objects.remove(ob)
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    bmesh.ops.triangulate(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new("Body_low", me)
    bpy.context.scene.collection.objects.link(o)
    o["forge_role"], o["forge_part"] = "low", "Body"
    return o


def open_edges(me) -> tuple:
    """(boundary edges, edges with more than two faces)."""
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(me)
    b = sum(1 for e in bm.edges if e.is_boundary)
    nm = sum(1 for e in bm.edges if len(e.link_faces) > 2)
    bm.free()
    return b, nm


def coords(me) -> np.ndarray:
    co = np.empty(len(me.vertices) * 3, np.float32)
    me.vertices.foreach_get("co", co)
    return co.reshape(-1, 3).astype(np.float64)


def bull(voxel: float = 0.008, tail_side: float = 0.30, leg_x: float = 0.15, leg_r: float = 0.075,
         ear_z: float = 0.76, tail_r: float = 0.022):
    """A round cartoon bull (fat belly, big neckless head with a muzzle, short legs, T-pose arms
    with hand balls, horns going sideways then up, flat ears under them, thin tail with a tuft
    curling to +X by tail_side; tail_r: the tail's radius at its root)."""
    import bmesh
    from mathutils import Matrix, Vector
    bpy.ops.wm.read_homefile(use_empty=True)
    bm = bmesh.new()

    def ball(c, r, s=(1, 1, 1)):
        m = Matrix.Translation(c) @ Matrix.Diagonal((r * s[0], r * s[1], r * s[2], 1))
        bmesh.ops.create_uvsphere(bm, u_segments=24, v_segments=16, radius=1.0, matrix=m)

    def tube(a, b, r1, r2=None):
        a, b = Vector(a), Vector(b)
        d = b - a
        m = Matrix.Translation((a + b) / 2) @ d.to_track_quat("Z", "Y").to_matrix().to_4x4()
        bmesh.ops.create_cone(bm, cap_ends=True, segments=16, radius1=r1, radius2=r1 if r2 is None else r2,
                              depth=d.length, matrix=m)

    def path(pts, radii):
        for (a, b), (r1, r2) in zip(zip(pts, pts[1:]), zip(radii, radii[1:])):
            tube(a, b, r1, r2)
            ball(b, r2)
    ball((0, 0, 0.42), 0.27, (1.0, 0.95, 1.05))
    ball((0, -0.02, 0.74), 0.17, (1.05, 1.0, 0.95))
    ball((0, -0.17, 0.70), 0.09, (1.1, 0.8, 0.7))
    for x in (1, -1):
        tube((0.15 * x, 0, 0.56), (0.50 * x, 0, 0.56), 0.065, 0.05)
        ball((0.55 * x, 0, 0.56), 0.07, (1.2, 0.9, 0.7))
        tube((leg_x * x, 0, 0.22), (leg_x * x, 0, 0.03), leg_r, leg_r)
        ball((leg_x * x, -0.03, 0.035), leg_r, (1.0, 1.4, 0.46))
        path([(0.11 * x, -0.02, 0.84), (0.22 * x, -0.02, 0.87), (0.27 * x, -0.02, 0.93), (0.26 * x, -0.02, 1.0)],
             [0.04, 0.035, 0.025, 0.006])
        m = Matrix.Translation((0.24 * x, 0.0, ear_z)) @ Matrix.Rotation(-0.25 * x, 4, "Y") @ \
            Matrix.Diagonal((0.09, 0.012, 0.04, 1))
        bmesh.ops.create_uvsphere(bm, u_segments=16, v_segments=12, radius=1.0, matrix=m)
    s = tail_side
    k = tail_r / 0.022
    path([(0, 0.24, 0.30), (0.02, 0.33, 0.20), (s * 0.4, 0.37, 0.11), (s, 0.36, 0.09)],
         [0.022 * k, 0.018 * k, 0.016 * k, 0.016 * k])
    ball((s + 0.05, 0.36, 0.11), 0.05, (1.3, 0.8, 0.9))
    me = bpy.data.meshes.new("b")
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new("Body", me)
    bpy.context.scene.collection.objects.link(ob)
    mod = ob.modifiers.new("v", "REMESH")
    mod.mode, mod.voxel_size = "VOXEL", voxel
    dg = bpy.context.evaluated_depsgraph_get()
    dg.update()
    ob.data = bpy.data.meshes.new_from_object(ob.evaluated_get(dg))
    ob.modifiers.remove(mod)
    zmin = min(v.co.z for v in ob.data.vertices)
    for v in ob.data.vertices:
        v.co.z -= zmin
    return ob


def narrow_rump(tail_r: float = 0.06, body_r: float = 0.075, voxel: float = 0.006):
    """A thick tail leaving a narrow body sideways near its rounded end (lizard-like: the
    body there is only about 1.25 tail radii wide). Returns (object, split ids: the tail = 1)."""
    import bmesh
    from mathutils import Matrix, Vector
    bpy.ops.wm.read_homefile(use_empty=True)
    bm = bmesh.new()

    def tube(a, b, r):
        a, b = Vector(a), Vector(b)
        d = b - a
        m = Matrix.Translation((a + b) / 2) @ d.to_track_quat("Z", "Y").to_matrix().to_4x4()
        bmesh.ops.create_cone(bm, cap_ends=True, segments=16, radius1=r, radius2=r, depth=d.length, matrix=m)
    tube((0, -0.4, 0.3), (0, 0.10, 0.3), body_r)
    bmesh.ops.create_uvsphere(bm, u_segments=24, v_segments=16, radius=body_r,
                              matrix=Matrix.Translation((0, 0.10, 0.3)))
    tube((0.0, 0.05, 0.3), (0.25, 0.10, 0.3), tail_r)
    tube((0.25, 0.10, 0.3), (0.40, 0.30, 0.3), tail_r * 0.8)
    me = bpy.data.meshes.new("b")
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new("Body", me)
    bpy.context.scene.collection.objects.link(ob)
    mod = ob.modifiers.new("v", "REMESH")
    mod.mode, mod.voxel_size = "VOXEL", voxel
    dg = bpy.context.evaluated_depsgraph_get()
    dg.update()
    ob.data = bpy.data.meshes.new_from_object(ob.evaluated_get(dg))
    ob.modifiers.remove(mod)
    co = coords(ob.data)
    return ob, (co[:, 0] > body_r * 1.25).astype(np.int32)


def ragged(me, ids, k, seed, p=0.35, rings=6):
    """A part border made ragged the way thickness noise at a fillet makes it: border
    vertices flip in or out at random, then the biggest piece is kept and what it encloses
    filled (as parts._finish_part does)."""
    from forge_bpy.appendages import _components
    from forge_bpy.density import _dilate
    rng = np.random.default_rng(seed)
    R = ids == k
    inner = ~_dilate(~R, me, rings)
    band = _dilate(R, me, rings) & ~inner & ((ids == 0) | R)
    R2 = R ^ (band & (rng.random(len(R)) < p))
    ev = np.empty(len(me.edges) * 2, np.int32)
    me.edges.foreach_get("vertices", ev)
    ev = ev.reshape(-1, 2).astype(np.int64)
    e_in = R2[ev[:, 0]] & R2[ev[:, 1]]
    lab = _components(len(R2), ev[e_in, 0], ev[e_in, 1])
    u, c = np.unique(lab[R2], return_counts=True)
    R2 &= lab == u[np.argmax(c)]
    e_out = ~R2[ev[:, 0]] & ~R2[ev[:, 1]]
    lab2 = _components(len(R2), ev[e_out, 0], ev[e_out, 1])
    u2, c2 = np.unique(lab2[~R2], return_counts=True)
    R2 |= ~R2 & (lab2 != u2[np.argmax(c2)])
    out = ids.copy()
    out[R] = 0
    out[R2] = k
    return out


MUZZLE = (0.0, -0.17, 0.70)                  # bull()'s muzzle ball: centre and radii
MUZZLE_R = (0.099, 0.072, 0.063)


def _taubin(me, passes: int, lam: float = 0.5, mu: float = -0.53) -> None:
    """Smoothing that does not shrink: rounds the sharp creases where voxel-fused balls meet
    into the soft fillets an AI mesh has there."""
    co = coords(me)
    ev = np.empty(len(me.edges) * 2, np.int32)
    me.edges.foreach_get("vertices", ev)
    ev = ev.reshape(-1, 2).astype(np.int64)
    n = len(co)
    deg = np.maximum(np.bincount(ev[:, 0], minlength=n) + np.bincount(ev[:, 1], minlength=n), 1)[:, None]
    for _ in range(passes):
        for f in (lam, mu):
            s = np.zeros_like(co)
            for k in range(3):
                s[:, k] = np.bincount(ev[:, 0], weights=co[ev[:, 1], k], minlength=n) + \
                    np.bincount(ev[:, 1], weights=co[ev[:, 0], k], minlength=n)
            co = co + f * (s / deg - co)
    me.vertices.foreach_set("co", co.astype(np.float32).ravel())
    me.update()


def mouth_head(depth: float = 0.005, width: float = 0.003, voxel: float = 0.004, refine: int = 2,
               phi=(12.0, 112.0), elev=(-62.0, -32.0), fade: float = 0.25, narrow: float = 0.4,
               profile: str = "v"):
    """bull() (belly, neckless head, muzzle, horns, ears, arms, legs, tail) with a lower lip
    under the muzzle, fused, its joins softened to fillets and the mouth made finer (an AI mesh
    is dense everywhere). A mouth line on each side: a V groove `depth` deep and `width` wide each
    side of its line, running round the muzzle from `phi[0]` (deg from the front) to `phi[1]`
    and from `elev[0]` (deg below the muzzle's middle: its front end runs into the concave join
    of lip and muzzle, under the nostril) to `elev[1]` (its back end rises to the mouth corner).
    It fades to nothing over the last `fade` of its length at both ends, narrowing to `narrow`
    of its width. `profile`: the groove's cross-section - "v" (straight walls to a sharp floor),
    "u" (a flat floor between steep walls) or "over" (the upper lip's side steep, almost an
    overhang, the lower side a long slope). Returns (object, the same mesh without the mouth
    line, groove depth per vertex)."""
    import math

    import bmesh
    from mathutils import Matrix, Vector
    from mathutils.bvhtree import BVHTree
    from mathutils.kdtree import KDTree
    bpy.ops.wm.read_homefile(use_empty=True)
    bm = bmesh.new()

    def ball(c, s, u=24, v=16):
        m = Matrix.Translation(c) @ Matrix.Diagonal((s[0], s[1], s[2], 1))
        bmesh.ops.create_uvsphere(bm, u_segments=u, v_segments=v, radius=1.0, matrix=m)

    def tube(a, b, r1, r2):
        a, b = Vector(a), Vector(b)
        d = b - a
        m = Matrix.Translation((a + b) / 2) @ d.to_track_quat("Z", "Y").to_matrix().to_4x4()
        bmesh.ops.create_cone(bm, cap_ends=True, segments=16, radius1=r1, radius2=r2, depth=d.length, matrix=m)

    def path(pts, radii):
        for (a, b), (r1, r2) in zip(zip(pts, pts[1:]), zip(radii, radii[1:])):
            tube(a, b, r1, r2)
            ball(b, (r2, r2, r2))
    ball((0, 0, 0.42), (0.27, 0.2565, 0.2835))
    ball((0, -0.02, 0.74), (0.1785, 0.17, 0.1615), 64, 48)
    ball(MUZZLE, MUZZLE_R, 64, 48)
    ball((0, -0.15, 0.645), (0.08, 0.06, 0.03), 64, 48)          # the lower lip
    for x in (1, -1):
        tube((0.15 * x, 0, 0.56), (0.50 * x, 0, 0.56), 0.065, 0.05)
        ball((0.55 * x, 0, 0.56), (0.084, 0.063, 0.049))
        tube((0.15 * x, 0, 0.22), (0.15 * x, 0, 0.03), 0.075, 0.075)
        ball((0.15 * x, -0.03, 0.035), (0.075, 0.105, 0.0345))
        path([(0.11 * x, -0.02, 0.84), (0.22 * x, -0.02, 0.87), (0.27 * x, -0.02, 0.93), (0.26 * x, -0.02, 1.0)],
             [0.04, 0.035, 0.025, 0.006])
        m = Matrix.Translation((0.24 * x, 0.0, 0.76)) @ Matrix.Rotation(-0.25 * x, 4, "Y") @ \
            Matrix.Diagonal((0.09, 0.012, 0.04, 1))
        bmesh.ops.create_uvsphere(bm, u_segments=16, v_segments=12, radius=1.0, matrix=m)
    path([(0, 0.24, 0.30), (0.02, 0.33, 0.20), (0.12, 0.37, 0.11), (0.30, 0.36, 0.09)], [0.022, 0.018, 0.016, 0.016])
    ball((0.35, 0.36, 0.11), (0.065, 0.04, 0.045))
    me = bpy.data.meshes.new("head")
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new("Head", me)
    bpy.context.scene.collection.objects.link(ob)
    mod = ob.modifiers.new("v", "REMESH")
    mod.mode, mod.voxel_size = "VOXEL", voxel
    dg = bpy.context.evaluated_depsgraph_get()
    dg.update()
    ob.data = bpy.data.meshes.new_from_object(ob.evaluated_get(dg))
    ob.modifiers.remove(mod)
    me = ob.data
    _taubin(me, 20)
    mc = np.array(MUZZLE)
    if refine:
        bm = bmesh.new()
        bm.from_mesh(me)
        es = [e for e in bm.edges if (e.verts[0].co - Vector(mc)).length < 0.15]
        bmesh.ops.subdivide_edges(bm, edges=es, cuts=refine, use_grid_fill=True)
        bmesh.ops.triangulate(bm, faces=[f for f in bm.faces if len(f.verts) > 4])
        bm.to_mesh(me)
        bm.free()
        me.update()
        _taubin(me, 3)
    smooth = me.copy()
    co = coords(me)
    nr = np.empty(len(co) * 3, np.float32)
    me.vertices.foreach_get("normal", nr)
    nr = nr.reshape(-1, 3).astype(np.float64)
    tree = BVHTree.FromPolygons([Vector(c) for c in co], [tuple(p.vertices) for p in me.polygons])
    rad = np.array(MUZZLE_R)
    dense, dense_u = [], []
    for side in (1, -1):
        pts = []
        for t in np.linspace(0.0, 1.0, 361):
            p = math.radians(side * (phi[0] + (phi[1] - phi[0]) * t))
            e = math.radians(elev[0] + (elev[1] - elev[0]) * t)
            d = np.array([rad[0] * math.sin(p) * math.cos(e), -rad[1] * math.cos(p) * math.cos(e),
                          rad[2] * math.sin(e)])
            d /= np.linalg.norm(d)
            h = tree.ray_cast(Vector(mc + d * 0.001), Vector(d), 1.0)
            pts.append(np.array(h[0][:]))
        pts = np.array(pts)
        s = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))])
        for i in range(len(pts) - 1):
            k = max(1, int((s[i + 1] - s[i]) / (width * 0.1)))
            for j in range(k):
                dense.append(pts[i] + (pts[i + 1] - pts[i]) * j / k)
                dense_u.append((s[i] + (s[i + 1] - s[i]) * j / k) / s[-1])
    kd = KDTree(len(dense))
    for i, p in enumerate(dense):
        kd.insert(Vector(p), i)
    kd.balance()
    off = np.zeros(len(co))
    for i in np.nonzero(np.linalg.norm(co - mc, axis=1) < 0.2)[0]:
        q, j, d = kd.find(Vector(co[i]))
        u = dense_u[j]
        taper = float(np.clip(min(u, 1.0 - u) / fade, 0.0, 1.0))
        taper = taper * taper * (3 - 2 * taper)
        w = width * (narrow + (1.0 - narrow) * taper)
        if profile == "u":
            x = (d / w) ** 4
        elif profile == "over":
            x = d / (0.35 * w) if co[i][2] > q[2] else d / (2.0 * w)
        else:
            x = d / w
        if x < 1.0:
            off[i] = depth * taper * (1.0 - x)
    me.vertices.foreach_set("co", (co - nr * off[:, None]).astype(np.float32).ravel())
    me.update()
    return ob, smooth, off
