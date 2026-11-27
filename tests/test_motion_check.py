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


# ----------------------------------------------------------------------------- Auto-Rig Pro arms

ARP_ARM = ("shoulder", "c_arm_twist_offset", "arm_stretch", "forearm_stretch", "forearm_twist", "hand")


def _arp_arms(radius=0.4, length=1.0, blend=0.15, cuts=59, taper=1.0):
    """Two arms in a T (one tube along X) with Auto-Rig Pro's deform bones and names: shoulder,
    upper arm = c_arm_twist_offset + arm_stretch, forearm = forearm_stretch + forearm_twist, hand;
    left on +X, mirrored on -X. Each bone hangs from the one before; the weights blend linearly
    over +-blend*length round every bone boundary. taper < 1: from the elbow on the arm is that
    much thinner (it narrows over +-0.1 length round the elbow), like a real forearm.
    Returns (rig, tube, ends of the bones)."""
    import math

    import bmesh
    from mathutils import Matrix
    bpy.ops.wm.read_homefile(use_empty=True)
    L = length
    ends = [0.0, 0.3 * L, 0.8 * L, 1.3 * L, 1.8 * L, 2.3 * L, 2.7 * L]
    ad = bpy.data.armatures.new("A")
    arm = bpy.data.objects.new("Rig", ad)
    bpy.context.scene.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    for s, x in (("l", 1), ("r", -1)):
        prev = None
        for i, n in enumerate(ARP_ARM):
            b = ad.edit_bones.new(f"{n}.{s}")
            b.head, b.tail = (x * ends[i], 0, 0), (x * ends[i + 1], 0, 0)
            if prev is not None:
                b.parent, b.use_connect = prev, True
            prev = b
    bpy.ops.object.mode_set(mode="OBJECT")
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=24, radius1=radius, radius2=radius, depth=2 * ends[-1],
                          matrix=Matrix.Rotation(math.pi / 2, 4, "Y"))
    side = [e for e in bm.edges if abs(e.verts[0].co.x - e.verts[1].co.x) > ends[-1]]
    bmesh.ops.subdivide_edges(bm, edges=side, cuts=cuts, use_grid_fill=True)
    if taper != 1.0:
        for v in bm.verts:
            u = min(max((abs(v.co.x) - (ends[3] - 0.1 * L)) / (0.2 * L), 0.0), 1.0)
            k = 1.0 + (taper - 1.0) * u
            v.co.y *= k
            v.co.z *= k
    me = bpy.data.meshes.new("Arms")
    bm.to_mesh(me)
    bm.free()
    tube = bpy.data.objects.new("Body_low", me)
    bpy.context.scene.collection.objects.link(tube)
    groups = {f"{n}.{s}": tube.vertex_groups.new(name=f"{n}.{s}") for s in "lr" for n in ARP_ARM}
    h = blend * L

    def ramp(u):
        return min(max((u + h) / (2 * h), 0.0), 1.0)
    for v in me.vertices:
        x, s = abs(v.co.x), ("l" if v.co.x >= 0 else "r")
        for i, n in enumerate(ARP_ARM):
            lo = 1.0 if i == 0 else ramp(x - ends[i])
            hi = 0.0 if i == len(ARP_ARM) - 1 else ramp(x - ends[i + 1])
            if lo - hi > 1e-6:
                groups[f"{n}.{s}"].add([v.index], lo - hi, "REPLACE")
    mod = tube.modifiers.new("Armature", "ARMATURE")
    mod.object = arm
    arm.animation_data_create()
    arm.animation_data.action = bpy.data.actions.new("FORGE_pose_test")
    return arm, tube, ends


def _turn(arm, bone, axis, deg, frame=None):
    """Turn a bone about a WORLD axis (as Forge's test poses do) and key it at `frame`."""
    import math

    from mathutils import Quaternion, Vector
    rest = arm.data.bones[bone].matrix_local.to_3x3()
    q = Quaternion(Vector(axis), math.radians(deg))
    pb = arm.pose.bones[bone]
    pb.rotation_mode = "QUATERNION"
    pb.rotation_quaternion = (rest.inverted() @ q.to_matrix() @ rest).to_quaternion()
    if frame is not None:
        pb.keyframe_insert("rotation_quaternion", frame=frame)


def _key_rest(arm, bones, frame):
    for b in bones:
        pb = arm.pose.bones[b]
        pb.rotation_mode = "QUATERNION"
        pb.rotation_quaternion = (1, 0, 0, 0)
        pb.keyframe_insert("rotation_quaternion", frame=frame)


def _elbows(deg=120.0, **kw):
    """Both elbows bent from straight (frame 1) to `deg` (frame 12), forearms to the front (-Y)."""
    arm, tube, ends = _arp_arms(**kw)
    _key_rest(arm, ["forearm_stretch.l", "forearm_stretch.r"], 1)
    _turn(arm, "forearm_stretch.l", (0, 0, 1), -deg, 12)
    _turn(arm, "forearm_stretch.r", (0, 0, 1), deg, 12)
    return arm, tube


def test_a_fat_elbow_names_the_elbow_and_tells_contact_from_thinning():
    """r/L = 0.4 bent 120 degrees: the inner sides press together (contact, information), the
    outer side keeps about cos(60) = half its distance under linear blending (a warning, normal
    for game skinning), and the faces crossing in the crease are contact, not faults."""
    arm, tube = _elbows(120.0)
    rep = _run(arm, [tube], list(range(1, 13)))
    joints = {e["where"]: e for e in rep["checks"]["joints"]["regions"]}
    for side in ("left", "right"):
        e = joints[f"{side} elbow"]
        assert e["part"] == "outer side" and 0.5 <= e["value"] < 0.7 and e["grade"] == "warn", e
        assert e["normal"] and e["frame"] == 12 and 115 <= e["bend_deg"] <= 121, e
        assert e["contact"]["value"] < 0.5 and e["contact"]["faces"] > 0, e      # pressed, reported
    assert joints["left elbow"]["value"] == pytest.approx(joints["right elbow"]["value"], abs=0.02)
    cross = rep["checks"]["crossing"]["regions"]
    assert {x["where"] for x in cross} == {"left elbow", "right elbow"}, cross
    assert all(x["kind"] == "contact" and x["grade"] == "info" for x in cross), cross
    x = rep["checks"]["crossing"]                        # (its value and frame: the worst fault)
    assert x["grade"] == "pass" and x["value"] == 0 and x["frame"] is None, x
    assert x["all_faces"] > 0 and x["contact"] > 0 and x["all_frame"] == 12, x
    skin = {e["where"]: e for e in rep["checks"]["skin"]["regions"]}
    for side in ("left", "right"):                       # folds in the crease are not graded
        assert skin.get(f"{side} elbow", {}).get("folds", 0) == 0, skin.get(f"{side} elbow")
        # a blend of +-0.15 on a limb this fat stretches the outer skin 3x: that is the weights'
        assert skin[f"{side} elbow"]["stretch_grade"] == "fail" and skin[f"{side} elbow"]["stretch"] > 2.5
        assert skin[f"{side} elbow"]["squash_grade"] == "pass"
    assert rep["checks"]["joints"]["grade"] == "warn" and rep["checks"]["skin"]["grade"] == "fail"
    assert rep["grade"] == "fail"
    import json
    json.dumps(rep)                     # (stored in the scene as JSON: plain numbers only, no numpy)
    # the panel: one sentence per finding, contact as information, nothing longer than 60
    import importlib
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "blender_addon"))
    L = importlib.import_module("forge_send.stages_late")
    _fake_poses(rep, "elbows")
    rows = L._anim_rows(rep)
    text = " ".join(t.strip() for _i, t in rows)
    assert "left elbow, pose 'elbows' (bent 120°, frame 12): outer side kept" in text, text
    assert "normal for game skinning at this bend" in text and "contact, expected" in text, text
    assert "touches" not in text and "fold" not in text, text
    assert "skin stretched 3.0x" in text and "smooth the weights there over a wider band" in text, text
    assert max(len(t) for _i, t in rows) <= 60
    warn_rows = [t for i, t in rows if i == L.WARN]
    assert any("left elbow" in t for t in warn_rows), rows
    # and that advice works: the same elbow blended over +-0.5 no longer fails
    arm, tube = _elbows(120.0, blend=0.5)
    rep = _run(arm, [tube], list(range(1, 13)))
    assert rep["checks"]["skin"]["grade"] == "warn" and rep["checks"]["skin"]["stretch"] < 2.0, rep["checks"]["skin"]


def test_a_tapered_elbow_presses_its_crease_further_out():
    """A forearm thinner than the upper arm (as real arms are): bent 120 degrees, the thick side
    meets the thin side further out than the thin side's own radius says. The crease is contact,
    never 'forearm touches upper arm', and no fold is graded there."""
    arm, tube, _ends = _arp_arms(radius=0.16, taper=0.62)
    _key_rest(arm, ["forearm_stretch.l", "forearm_stretch.r"], 1)
    _turn(arm, "forearm_stretch.l", (0, 0, 1), -120.0, 12)
    _turn(arm, "forearm_stretch.r", (0, 0, 1), 120.0, 12)
    rep = _run(arm, [tube], list(range(1, 13)))
    cross = rep["checks"]["crossing"]
    assert cross["grade"] == "pass" and cross["contact"] > 0, cross["regions"]
    assert {x["kind"] for x in cross["regions"]} == {"contact"}, cross["regions"]
    skin = {e["where"]: e for e in rep["checks"]["skin"]["regions"]}
    assert all(e["folds"] == 0 for e in skin.values()), skin
    joints = {e["where"]: e for e in rep["checks"]["joints"]["regions"]}
    for side in ("left", "right"):
        e = joints[f"{side} elbow"]
        assert e["part"] == "outer side" and e["normal"] and e["contact"]["faces"] > 0, e


def test_a_coarse_mesh_keeps_its_contact_zone_where_the_limbs_meet():
    """Rings as far apart as the limb is thick (a game low): the contact zone is a distance along
    the limb, not a count of face rings, so a point weighted to the wrong bone two rings past
    where the limbs meet still turns its faces inside out - a fold, graded - while the crease
    itself stays contact."""
    from mathutils import Vector
    from forge_bpy import motion_check as M
    r = 0.15
    arm, tube, ends = _arp_arms(radius=r, cuts=35)                   # rings about r apart
    _key_rest(arm, ["forearm_stretch.l", "forearm_stretch.r"], 1)
    _turn(arm, "forearm_stretch.l", (0, 0, 1), -90.0, 12)
    _turn(arm, "forearm_stretch.r", (0, 0, 1), 90.0, 12)
    st = M.rest_layout(arm, [tube])
    lay = st["L"]
    J = next(j for j in lay.joints if j.name == "left elbow")
    bpy.context.scene.frame_set(12)
    co = M._posed(tube, bpy.context.evaluated_depsgraph_get(), len(tube.data.vertices))
    _m, R, H, T = M.pose_state(arm, lay)
    res = lay.measure(J, co, R, H, T, _m)
    bpy.context.scene.frame_set(1)
    reach = r * 1.0                                       # r tan(90/2): where rigid limbs meet
    along = abs((lay.tri_c[res["tzone"]] - J.pivot) @ J.axis)
    assert along.max() < 1.5 * reach, along.max()          # (two face rings reached 2.3x as far)
    # a point on the inner side, the second ring past where the limbs meet, left on the upper arm
    piv = ends[3]
    bad = min(tube.data.vertices, key=lambda p: (p.co - Vector((piv + 2 * r, -r, 0.0))).length)
    assert 1.6 * r < bad.co.x - piv < 2.4 * r, bad.co.x - piv
    for g in tube.vertex_groups:
        g.remove([bad.index])
    tube.vertex_groups["arm_stretch.l"].add([bad.index], 1.0, "REPLACE")
    rep = _run(arm, [tube], list(range(1, 13)))
    sk = rep["checks"]["skin"]
    assert sk["folds"] >= 1 and sk["grade"] == "fail", sk


def _fake_poses(node, name):
    """What steps._attach_poses adds: the test pose at every frame of a finding."""
    if isinstance(node, dict):
        for k in list(node):
            if (k == "frame" or k.endswith("_frame")) and isinstance(node[k], int):
                node["pose" if k == "frame" else k[:-5] + "pose"] = {"name": name, "weight": 1.0, "bend_deg": 120}
            elif isinstance(node[k], (dict, list)):
                _fake_poses(node[k], name)
    elif isinstance(node, list):
        for x in node:
            _fake_poses(x, name)


def test_b_a_twisted_upper_arm_fails_as_a_twist():
    """160 degrees between the twist bone and the stretch bone of one segment: linear blending
    wrings it to cos(80) (the candy wrapper), judged all round and named '<segment> twist'."""
    arm, tube, _ends = _arp_arms(radius=0.1)
    _key_rest(arm, ["arm_stretch.l"], 1)
    _turn(arm, "arm_stretch.l", (1, 0, 0), 160.0, 12)
    rep = _run(arm, [tube], list(range(1, 13)))
    joints = {e["where"]: e for e in rep["checks"]["joints"]["regions"]}
    e = joints["left upper arm twist"]
    assert e["grade"] == "fail" and e["part"] == "all round" and e["twist_deg"] >= 150 and e["bend_deg"] < 10, e
    assert e["value"] < 0.3 and e["normal"], e                      # what linear blending does at 160
    assert rep["checks"]["joints"]["where"] == "left upper arm twist"
    assert "left elbow" not in joints and "right upper arm twist" not in joints, joints   # nothing else turns
    # the skin the twist bones share is that same place: one place, one name
    skin = {x["where"]: x for x in rep["checks"]["skin"]["regions"]}
    assert "left upper arm twist" in skin and skin["left upper arm twist"]["stretch"] > 1.0, list(skin)
    assert [r["where"] for r in rep["regions"]].count("left upper arm twist") == 1


def test_d_the_bend_direction_is_taken_each_frame():
    """A shoulder raised and then swung forward: the top of the arm is the inner side of the
    first bend and a side of the second; the front the other way round."""
    from forge_bpy import motion_check as M
    arm, tube, _ends = _arp_arms(radius=0.3)
    _key_rest(arm, ["c_arm_twist_offset.l"], 1)
    _turn(arm, "c_arm_twist_offset.l", (0, 1, 0), -60.0, 10)                  # up (+Z)
    _turn(arm, "c_arm_twist_offset.l", (0, 0, 1), -60.0, 20)                  # forward (-Y)
    st = M.rest_layout(arm, [tube])
    lay = st["L"]
    J = next(j for j in lay.joints if j.name == "left shoulder")
    top, front, bottom = J.rdir[:, 2] > 0.9, J.rdir[:, 1] < -0.9, J.rdir[:, 2] < -0.9
    assert top.sum() > 5 and front.sum() > 5 and bottom.sum() > 5

    def sides(f):
        bpy.context.scene.frame_set(f)
        dg = bpy.context.evaluated_depsgraph_get()
        co = M._posed(tube, dg, len(tube.data.vertices))
        _m, R, H, T = M.pose_state(arm, lay)
        res = lay.measure(J, co, R, H, T)
        assert 55 < res["bend"] < 65, res["bend"]
        return res["side"]
    up, fw = sides(10), sides(20)
    # 1 inner side, 2 inner side within the contact zone, 0 a side, -1 outer side (a point on the
    # bend's own plane can lie in the zone: the zone is the half the bend closes on)
    assert set(up[top].tolist()) <= {1, 2} and set(up[bottom].tolist()) == {-1}, (up[top], up[bottom])
    assert set(up[front].tolist()) <= {0, 2} and (up[front] == 0).any(), up[front]
    assert set(fw[front].tolist()) <= {1, 2} and set(fw[top].tolist()) <= {0, 2}, (fw[front], fw[top])
    assert set(fw[bottom].tolist()) <= {0, 2} and (fw[top] == 0).any(), fw[bottom]
    assert (up[top] == 2).any() and (fw[front] == 2).any()               # contact near the pivot
    bpy.context.scene.frame_set(1)


def test_e_a_sliver_does_not_blow_up_the_stretch_and_a_fold_is_counted():
    """A rest edge of 1e-7 m (a remesher sliver) would read 10000x as an edge ratio; per
    triangle, slivers are left out and the skin reads what it is. A point weighted to the wrong
    bone is left behind when the forearm bends: its faces turn inside out (a fold, a fault)."""
    import numpy as np
    from mathutils import Vector
    arm, tube = _arm(25)
    me = tube.data
    v = min(me.vertices, key=lambda p: (p.co - Vector((1.02, 0, 0.15))).length)
    nb = [me.vertices[i] for e in me.edges if v.index in e.vertices for i in e.vertices if i != v.index]
    u = min(nb, key=lambda p: abs(p.co.y - v.co.y) + abs(p.co.z - v.co.z))     # its neighbour along the arm
    v.co = u.co + (v.co - u.co).normalized() * 1e-7       # (v keeps the weights of where it was)
    vi, ui = v.index, u.index
    rep = _run(arm, [tube], list(range(1, 13, 2)) + [12])
    assert rep["checks"]["skin"]["stretch"] < 3.0 and rep["checks"]["skin"]["grade"] == "pass", rep["checks"]["skin"]
    from forge_bpy import motion_check as M
    st = M.rest_layout(arm, [tube])
    bpy.context.scene.frame_set(12)
    co = M._posed(tube, bpy.context.evaluated_depsgraph_get(), len(me.vertices))
    rest = st["rest"]                                    # what the old edge ratio read there
    assert np.linalg.norm(co[ui] - co[vi]) / np.linalg.norm(rest[ui] - rest[vi]) > 100
    bpy.context.scene.frame_set(1)
    # a point of the forearm left on the upper arm
    arm, tube = _arm(60)
    bad = min(tube.data.vertices, key=lambda p: (p.co - Vector((1.6, 0, 0.15))).length)
    for g in tube.vertex_groups:
        g.remove([bad.index])
    tube.vertex_groups["upperarm.l"].add([bad.index], 1.0, "REPLACE")
    rep = _run(arm, [tube], list(range(1, 13)))
    sk = rep["checks"]["skin"]
    assert sk["folds"] >= 1 and sk["grade"] == "fail" and sk["folds_where"], sk
    assert any(r["where"] == sk["folds_where"] and r["grade"] == "fail" for r in rep["regions"])


def test_f_preserve_volume_does_not_change_what_is_measured():
    """The check measures linear blending (what the engines play) whatever the modifier says,
    puts the setting back, and numpy's linear blend is Blender's modifier to 1e-6 m."""
    import numpy as np
    from forge_bpy import motion_check as M
    arm, tube = _elbows(120.0, radius=0.3)
    mod = tube.modifiers["Armature"]
    frames = list(range(1, 13))
    mod.use_deform_preserve_volume = False
    a = _run(arm, [tube], frames)
    mod.use_deform_preserve_volume = True
    b = _run(arm, [tube], frames)
    assert mod.use_deform_preserve_volume                          # put back
    assert a["checks"] == b["checks"] and a["regions"] == b["regions"]
    assert b["measured_as"]["preserve_volume_was_on"] and not a["measured_as"]["preserve_volume_was_on"]
    mod.use_deform_preserve_volume = False
    st = M.rest_layout(arm, [tube])
    for f in (6, 12):
        bpy.context.scene.frame_set(f)
        co = M._posed(tube, bpy.context.evaluated_depsgraph_get(), len(tube.data.vertices))
        mats, _R, _H, _T = M.pose_state(arm, st["L"])
        assert np.abs(M.lbs(st["rest"], st["L"].Wn, mats) - co).max() < 1e-6
    bpy.context.scene.frame_set(1)


def _far_bone_tube(tail):
    """A tube on four bones that never move, and a band of points also weighted `tail` to a
    fifth bone off to the side, which turns 30 degrees (frames 1 to 5)."""
    import math

    import bmesh
    from mathutils import Matrix
    bpy.ops.wm.read_homefile(use_empty=True)
    ad = bpy.data.armatures.new("A")
    arm = bpy.data.objects.new("Rig", ad)
    bpy.context.scene.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    for i in range(4):
        b = ad.edit_bones.new(f"near_{i}")
        b.head, b.tail = (0.5 * i, 0, 0), (0.5 * i + 0.5, 0, 0)
    far = ad.edit_bones.new("far")
    far.head, far.tail = (1.0, 0.5, 0), (1.0, 0.8, 0)
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
    g = [tube.vertex_groups.new(name=f"near_{i}") for i in range(4)] + [tube.vertex_groups.new(name="far")]
    for v in me.vertices:
        band = 0.85 <= v.co.x <= 1.15
        t = tail if band else 0.0
        for i in range(4):
            g[i].add([v.index], (1.0 - t) / 4.0, "REPLACE")
        if band:
            g[4].add([v.index], t, "REPLACE")
    tube.modifiers.new("Armature", "ARMATURE").object = arm
    arm.animation_data_create()
    arm.animation_data.action = bpy.data.actions.new("FORGE_pose_test")
    _key_rest(arm, ["far"], 1)
    _turn(arm, "far", (0, 0, 1), 30.0, 5)
    return arm, tube


def test_g_unity_four_bone_limit_is_measured_not_counted():
    """Unity keeps 4 bones (the export's own continuous limit). A 12 % fifth bone that moves
    shifts the skin by more than half an edge: a warning with the frame and the place. A 5 %
    tail moves it less: still counted (information), but it passes."""
    import importlib
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "blender_addon"))
    S = importlib.import_module("forge_send.steps")
    out = {}
    for tail in (0.12, 0.05):
        arm, tube = _far_bone_tube(tail)
        rep = _run(arm, [tube], [1, 3, 5])
        out[tail] = rep
        w = rep["checks"]["weights"]
        assert w["over"]["Unity"] > 0 and w["over"]["Unreal"] == 0, w
        assert w["unity"]["measured_on"] == "full mesh"
    big, small = out[0.12]["checks"]["weights"], out[0.05]["checks"]["weights"]
    assert big["grade"] == "warn" and big["unity"]["grade"] == "warn", big
    assert big["unity"]["shift_edges"] > 0.5 and big["unity"]["frame"] == 5 and big["unity"]["where"], big
    assert big["unity"]["shift_mm"] == pytest.approx(small["unity"]["shift_mm"] * 0.12 / 0.05, rel=0.05)
    assert small["grade"] == "pass" and small["unity"]["shift_edges"] < 0.5, small
    S._attach_poses(out[0.12], "rom")                        # the frame gets its pose, as in Step 8
    assert out[0.12]["checks"]["weights"]["unity"]["pose"]["name"] == S.clip_pose("rom", 5)[1]
    L = importlib.import_module("forge_send.stages_late")
    text = " ".join(t.strip() for _i, t in L._anim_rows(out[0.12]))
    assert "Unity" in text and "4-bone limit moves the skin" in text and "points use more than 4 bones" in text, text
    assert "times the typical edge length" in text and "stretch up to" not in text, text
    text = " ".join(t.strip() for _i, t in L._anim_rows(out[0.05]))
    assert "4-bone limit moves the skin" not in text and "fine" in text, text


def test_a_prop_pinned_to_a_bone_is_a_part_of_its_own():
    """A box pinned whole to the forearm swings into the upper arm when the elbow folds: it is
    named by its part and reported as touching the arm (a warning), never as the elbow's contact
    or as a fold of the forearm."""
    import bmesh
    arm, tube = _arm(165)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=0.12)
    bmesh.ops.translate(bm, verts=bm.verts, vec=(1.55, 0.2, 0.0))
    me = bpy.data.meshes.new("Box")
    bm.to_mesh(me)
    bm.free()
    box = bpy.data.objects.new("Box_low", me)
    bpy.context.scene.collection.objects.link(box)
    box["forge_part"] = "Box"
    box.vertex_groups.new(name="forearm.l").add(list(range(len(me.vertices))), 1.0, "REPLACE")
    box.modifiers.new("Armature", "ARMATURE").object = arm
    rep = _run(arm, [tube, box], list(range(1, 13)))
    cross = rep["checks"]["crossing"]["regions"]
    box_x = [x for x in cross if "Box" in x["where"]]
    assert box_x and all(x["kind"] == "touch" and x["grade"] == "warn" for x in box_x), cross
    assert any(x["where"] == "Box touches left upperarm" for x in box_x), box_x
    assert not [x for x in cross if x["kind"] == "fold"], cross
    assert rep["checks"]["weights"]["points"] == len(tube.data.vertices) + len(me.vertices)


# ----------------------------------------------------------------------------- review fixes

def _late():
    import importlib
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "blender_addon"))
    return importlib.import_module("forge_send.stages_late")


def test_a_collapsing_joint_is_never_hidden_behind_stretched_skin():
    """Findings of different checks rank by how far past their limit they are: a twist kept at
    33 % (limit 50 %: 1.5x past it) comes before skin stretched 2.3x (limit 2x: 1.15x). And the
    panel always shows each check's worst place, even behind many worse ones."""
    from forge_bpy import motion_check as M
    joint = {"where": "left upper arm twist", "grade": "fail", "value": 0.334, "part": "all round", "frame": 97,
             "bend_deg": 0, "twist_deg": 150, "kind": "twist", "lbs": 0.26, "normal": True,
             "over": M._over(0.334, *M.LIMITS["volume"], below=True)}
    skins = [{"where": f"place {k}", "grade": "fail", "stretch": 2.3 - 0.01 * k, "frame": 83, "stretch_grade": "fail",
              "folds": 0, "folds_grade": "pass", "squash": 0.8, "squash_grade": "pass",
              "over": M._over(2.3 - 0.01 * k, *M.LIMITS["stretch"], below=False)} for k in range(9)]
    checks = {"joints": {"grade": "fail", "regions": [joint]}, "skin": {"grade": "fail", "regions": skins},
              "crossing": {"grade": "pass", "regions": []}}
    regions = M.by_region(checks)
    assert regions[0]["where"] == "left upper arm twist", [r["where"] for r in regions]
    # a joint that only warns still gets its row behind more than six failing places
    joint.update(grade="warn", value=0.62, over=M._over(0.62, *M.LIMITS["volume"], below=True), normal=False)
    rep = {"frames": 12, "grade": "fail", "checks": checks, "regions": M.by_region(checks)}
    assert rep["regions"][-1]["where"] == "left upper arm twist"
    text = " ".join(t.strip() for _i, t in _late()._anim_rows(rep))
    assert "left upper arm twist" in text and "all round kept 62%" in text, text
    assert "and 3 more places" in text, text


def test_inner_side_caving_in_is_told_to_blend_tighter_not_wider():
    """A slim elbow blended over +-0.5 and bent 120 degrees: the inner side caves in outside the
    crease - the blend reaches too far along the limb. The advice is a tighter blend on the inside
    of the bend (or a helper bone), never 'smooth the weights', and no 'contact, expected' note
    sits under that finding."""
    arm, tube = _elbows(120.0, radius=0.15, blend=0.5)
    rep = _run(arm, [tube], list(range(1, 13)))
    e = {x["where"]: x for x in rep["checks"]["joints"]["regions"]}["left elbow"]
    assert e["part"] == "inner side" and e["grade"] == "fail" and not e["normal"], e
    _fake_poses(rep, "elbows")
    rows = _late()._anim_rows(rep)
    text = " ".join(t.strip() for _i, t in rows)
    assert "inner side kept" in text and "the inside of the bend caves in" in text, text
    assert "Blend over a shorter one on the inside of the bend" in text, text
    assert "smooth the weights across that joint" not in text, text
    k = next(i for i, (_ic, t) in enumerate(rows) if "left elbow," in t)
    assert "inner side" in " ".join(t.strip() for _i, t in rows[k:k + 2]), rows[k:k + 2]
    assert "contact, expected" not in " ".join(t for _i, t in rows[k:k + 4]), rows[k:k + 4]


def test_skin_squashed_where_nothing_bends_is_graded():
    """A forearm bone shrunk to 45 % along its length (a squash control): nothing bends, the
    skin bunches up. The squash is graded (a warning) and said in plain words."""
    arm, tube = _arm(0.0)
    pb = arm.pose.bones["forearm.l"]
    pb.scale = (1, 1, 1)
    pb.keyframe_insert("scale", frame=1)
    pb.scale = (1.0, 0.45, 1.0)                                # bone Y: along the forearm
    pb.keyframe_insert("scale", frame=12)
    rep = _run(arm, [tube], list(range(1, 13)))
    sk = rep["checks"]["skin"]
    assert sk["grade"] == "warn" and sk["squash"] < 0.3 and sk["squash_where"], sk
    assert rep["grade"] != "pass"
    _fake_poses(rep, "rest")
    text = " ".join(t.strip() for _i, t in _late()._anim_rows(rep))
    assert "skin squashed to" in text and "Squashed skin where nothing bends" in text, text
    # bending the elbow 120 degrees squeezes the crease: that is the bend's, not graded as squash
    arm, tube = _elbows(120.0, radius=0.15)
    rep = _run(arm, [tube], list(range(1, 13)))
    assert all(e["squash_grade"] == "pass" for e in rep["checks"]["skin"]["regions"]), rep["checks"]["skin"]


def _web(spread_deg):
    """A flat web of skin between two parallel bones 0.2 apart (fingers webbed together), each
    side weighted to its bone, blended across the middle; bone b swings away from a."""
    import math

    import bmesh
    from mathutils import Matrix
    bpy.ops.wm.read_homefile(use_empty=True)
    ad = bpy.data.armatures.new("A")
    arm = bpy.data.objects.new("Rig", ad)
    bpy.context.scene.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    for n, y in (("a", -0.1), ("b", 0.1)):
        e = ad.edit_bones.new(n)
        e.head, e.tail = (0, y, 0), (1, y, 0)
    bpy.ops.object.mode_set(mode="OBJECT")
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0, matrix=Matrix.Translation((0.5, 0, 0)) @ Matrix.Diagonal((1.0, 0.3, 0.04, 1)))
    bmesh.ops.subdivide_edges(bm, edges=list(bm.edges), cuts=12, use_grid_fill=True)
    me = bpy.data.meshes.new("Web")
    bm.to_mesh(me)
    bm.free()
    web = bpy.data.objects.new("Web_low", me)
    bpy.context.scene.collection.objects.link(web)
    ga, gb = web.vertex_groups.new(name="a"), web.vertex_groups.new(name="b")
    for v in me.vertices:
        w = min(max((v.co.y + 0.03) / 0.06, 0.0), 1.0)
        if w < 1:
            ga.add([v.index], 1 - w, "REPLACE")
        if w > 0:
            gb.add([v.index], w, "REPLACE")
    web.modifiers.new("Armature", "ARMATURE").object = arm
    arm.animation_data_create()
    arm.animation_data.action = bpy.data.actions.new("FORGE_pose_test")
    _key_rest(arm, ["b"], 1)
    _turn(arm, "b", (0, 0, 1), spread_deg, 12)
    return arm, web


def test_stretch_the_pose_itself_asks_for_is_told_as_the_pose():
    """Spreading webbed fingers 60 degrees: the skin between the two bones must stretch whatever
    the weights (skin next to each bone follows it). The check proves the pose asks for more
    than the limit and says so - turn it less - instead of 'smooth the weights'. A fat elbow's
    stretch is the weights' (test a): no such floor there."""
    arm, web = _web(60.0)
    rep = _run(arm, [web], list(range(1, 13)))
    worst = max(rep["checks"]["skin"]["regions"], key=lambda e: e["stretch"])
    assert worst["stretch_grade"] == "fail" and worst["pose_floor"] > 2.0, worst
    assert worst["pose_floor"] <= worst["stretch"] + 1e-6 and worst["pose_mover"] == "b", worst
    _fake_poses(rep, "spread")
    text = " ".join(t.strip() for _i, t in _late()._anim_rows(rep))
    assert "the pose itself asks for at least" in text and "turn the b less" in text, text
    assert "The pose asks for that stretch" in text and "smooth the weights there over a wider band" not in text, text
    arm, tube = _elbows(120.0)
    rep = _run(arm, [tube], list(range(1, 13)))
    assert not any("pose_floor" in e for e in rep["checks"]["skin"]["regions"]), rep["checks"]["skin"]["regions"]


def test_a_modifier_that_adds_points_is_measured_without_it():
    """A Subdivision modifier after the armature changes the point count: the check measures the
    skinned cage (the same report as without it), says so, and switches the modifier back on.
    Measured frozen, it read 262 faces turned inside out that never moved."""
    arm, tube = _arm(120)
    a = _run(arm, [tube], list(range(1, 13)))
    tube.modifiers.new("Smooth", "SUBSURF").levels = 1
    b = _run(arm, [tube], list(range(1, 13)))
    assert a["checks"] == b["checks"], (a["checks"]["skin"], b["checks"]["skin"])
    assert b["measured_as"]["without_modifiers"] == {"Tube_low": ["Smooth"]} and not b.get("skipped")
    assert tube.modifiers["Smooth"].show_viewport
    text = " ".join(t.strip() for _i, t in _late()._anim_rows(b))
    assert "Tube_low: measured without its Smooth" in text, text
