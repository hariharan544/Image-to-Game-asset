"""Step 8 automatic checks: a sample clip is stepped through and the joints, the skin, faces
passing through faces and the weights are measured. A gentle bend passes; folding a tube
until the elbow collapses fails, with the frame named."""

import sys
from pathlib import Path

import pytest

bpy = pytest.importorskip("bpy")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "blender_scripts"))


def _arm(bend_deg, frames=12):
    """A tube on a 2-bone chain (upper arm, forearm), linearly blended over the elbow, and an
    action bending the elbow from 0 to bend_deg."""
    import math

    import bmesh
    from mathutils import Matrix, Quaternion, Vector
    bpy.ops.wm.read_homefile(use_empty=True)
    ad = bpy.data.armatures.new("A")
    arm = bpy.data.objects.new("Rig", ad)
    bpy.context.scene.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    up = ad.edit_bones.new("upperarm.l")
    up.head, up.tail = (0, 0, 0), (1, 0, 0)
    fo = ad.edit_bones.new("forearm.l")
    fo.head, fo.tail = (1, 0, 0), (2, 0, 0)
    fo.parent, fo.use_connect = up, True
    bpy.ops.object.mode_set(mode="OBJECT")
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=16, radius1=0.15, radius2=0.15, depth=2.0,
                          matrix=Matrix.Translation((1, 0, 0)) @ Matrix.Rotation(math.pi / 2, 4, "Y"))
    side = [e for e in bm.edges if abs(e.verts[0].co.x - e.verts[1].co.x) > 1.0]
    bmesh.ops.subdivide_edges(bm, edges=side, cuts=39, use_grid_fill=True)
    me = bpy.data.meshes.new("Tube")
    bm.to_mesh(me)
    bm.free()
    tube = bpy.data.objects.new("Tube_low", me)
    bpy.context.scene.collection.objects.link(tube)
    gu, gf = tube.vertex_groups.new(name="upperarm.l"), tube.vertex_groups.new(name="forearm.l")
    for v in me.vertices:
        w = min(max((v.co.x - 0.8) / 0.4, 0.0), 1.0)
        if w < 1:
            gu.add([v.index], 1 - w, "REPLACE")
        if w > 0:
            gf.add([v.index], w, "REPLACE")
    mod = tube.modifiers.new("Armature", "ARMATURE")
    mod.object = arm
    arm.animation_data_create()
    arm.animation_data.action = bpy.data.actions.new("FORGE_pose_test")
    pb = arm.pose.bones["forearm.l"]
    pb.rotation_mode = "QUATERNION"
    for f, deg in ((1, 0.0), (frames, bend_deg)):
        pb.rotation_quaternion = Quaternion(Vector((0, 0, 1)), math.radians(deg))
        pb.keyframe_insert("rotation_quaternion", frame=f)
    return arm, tube


def _run(arm, objs, frames):
    from forge_bpy import motion_check
    gen = motion_check.check(arm, objs, frames)
    try:
        while True:
            next(gen)
    except StopIteration as stop:
        return stop.value


def test_a_gentle_bend_passes():
    arm, tube = _arm(25)
    rep = _run(arm, [tube], list(range(1, 13, 2)) + [12])
    c = rep["checks"]
    assert c["joints"]["grade"] == "pass", c["joints"]
    assert c["crossing"]["value"] == 0 and c["weights"]["grade"] == "pass", c
    assert bpy.context.scene.frame_current == 1                     # the frame is put back


def test_a_collapsing_elbow_fails_and_names_the_frame():
    arm, tube = _arm(165)
    rep = _run(arm, [tube], list(range(1, 13)))
    c = rep["checks"]
    assert c["joints"]["grade"] == "fail" and c["joints"]["frame"] >= 9, c["joints"]
    assert "arm" in c["joints"]["where"], c["joints"]
    assert c["crossing"]["value"] > 0 and c["crossing"]["frame"] >= 9, c["crossing"]
    assert rep["grade"] == "fail" and rep["worst_frame"] >= 9


def test_unweighted_points_and_too_many_bones_are_counted():
    from forge_bpy import motion_check
    arm, tube = _arm(10)
    for i in range(8):                                    # 8 extra bones on point 0
        g = tube.vertex_groups.new(name=f"extra_{i}")
        g.add([0], 0.1, "REPLACE")
    deform = {"upperarm.l", "forearm.l"} | {f"extra_{i}" for i in range(8)}
    for v in tube.data.vertices[1:4]:                     # 3 points nothing moves
        for g in list(v.groups):
            tube.vertex_groups[g.group].remove([v.index])
    w = motion_check.weights([tube], deform)
    assert w["unweighted"] == 3 and w["over"]["Unity"] == 1 and w["over"]["Unreal"] == 1
