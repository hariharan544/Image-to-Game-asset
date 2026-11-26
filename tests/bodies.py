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
         ear_z: float = 0.76):
    """A round cartoon bull (fat belly, big neckless head with a muzzle, short legs, T-pose arms
    with hand balls, horns going sideways then up, flat ears under them, thin tail with a tuft
    curling to +X by tail_side)."""
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
    path([(0, 0.24, 0.30), (0.02, 0.33, 0.20), (s * 0.4, 0.37, 0.11), (s, 0.36, 0.09)], [0.022, 0.018, 0.016, 0.016])
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
