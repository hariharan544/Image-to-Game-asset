"""Extra body parts (tail, ears, horns) are found on a T-pose body and get a joint chain."""

import sys
from pathlib import Path

import pytest

bpy = pytest.importorskip("bpy")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "blender_scripts"))


def _creature():
    import bmesh
    from mathutils import Matrix, Vector

    from forge_bpy import fixture
    fixture.humanoid({"out": "/tmp/_forge_creature.glb"})
    body = bpy.data.objects["Body"]
    bm = bmesh.new()
    bm.from_mesh(body.data)

    def tube(a, b, r):
        a, b = Vector(a), Vector(b)
        d = b - a
        m = Matrix.Translation((a + b) / 2) @ d.to_track_quat("Z", "Y").to_matrix().to_4x4()
        bmesh.ops.create_cone(bm, cap_ends=True, segments=12, radius1=r, radius2=r * 0.5, depth=d.length, matrix=m)
    tube((0, 0.12, 0.95), (0, 0.55, 0.55), 0.03)            # tail, behind (+Y), hanging down
    for x in (1, -1):
        tube((0.1 * x, 0, 1.68), (0.28 * x, 0, 1.72), 0.035)   # ears, sideways
        tube((0.06 * x, 0, 1.74), (0.16 * x, 0, 1.97), 0.025)  # horns, upwards
    bm.to_mesh(body.data)
    bm.free()
    # fuse into one evenly dense surface, like an AI-generated mesh
    m = body.modifiers.new("v", "REMESH")
    m.mode, m.voxel_size = "VOXEL", 0.012
    dg = bpy.context.evaluated_depsgraph_get()
    dg.update()
    body.data = bpy.data.meshes.new_from_object(body.evaluated_get(dg))
    body.modifiers.remove(m)
    return body


def test_tail_ears_horns_found_with_chains():
    from forge_bpy import appendages, joints
    body = _creature()
    J = joints.estimate(body)
    found = {a["name"]: a for a in appendages.from_object(body, J, segments=4)}
    assert set(found) == {"tail", "ear_l", "ear_r", "horn_l", "horn_r"}, sorted(found)
    tail = found["tail"]["chain"]
    assert len(tail) == 5
    assert abs(tail[0][1] - 0.12) < 0.05 and abs(tail[0][2] - 0.95) < 0.06     # root at the body
    assert abs(tail[-1][1] - 0.55) < 0.04 and abs(tail[-1][2] - 0.55) < 0.04   # tip at the end
    assert found["ear_l"]["chain"][-1][0] > 0.25 and found["ear_r"]["chain"][-1][0] < -0.25
    assert found["horn_l"]["chain"][-1][2] > 1.9


def test_parts_plan_splits_tail_lightens_horns():
    import importlib

    import numpy as np
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "blender_addon"))
    body = _creature()
    col = bpy.data.collections.new("Forge Parts")
    bpy.context.scene.collection.children.link(col)
    for c in list(body.users_collection):
        c.objects.unlink(body)
    col.objects.link(body)
    body["forge_kind"] = "body"
    S = importlib.import_module("forge_send.steps")
    try:
        _check_density(S, body)
    finally:                                  # leave no "Forge Parts" behind for other tests
        bpy.ops.wm.read_homefile(use_empty=True)


def _check_density(S, body):
    """The parts plan: tail thin and one-sided -> separate; horns thick and rigid -> fewer
    quads; ears -> with the body."""
    import numpy as np
    assert S.ensure_detail_maps(0.8) == 1
    plan = S.plan_parts(recompute=True)
    assert plan.get("tail") == "separate", plan
    assert plan.get("horn_l") == "rigid, fewer quads" and plan.get("ear_l") == "with the body", plan
    me = body.data
    ids = np.empty(len(me.vertices), np.int32)
    me.attributes["forge_split"].data.foreach_get("value", ids)
    co = np.array([v.co[:] for v in me.vertices])
    assert ids[np.linalg.norm(co - (0, 0.5, 0.6), axis=1) < 0.05].min() >= 1     # the tail tip is split
    assert ids[np.linalg.norm(co - (0, -0.16, 1.1), axis=1) < 0.05].max() == 0   # the belly is not
    c = np.empty(len(me.loops) * 4, np.float32)
    me.color_attributes["QR_Density"].data.foreach_get("color_srgb", c)
    c = c.reshape(-1, 4)
    lv = np.array([l.vertex_index for l in me.loops])
    horn_tip = np.linalg.norm(co[lv] - (0.16, 0, 1.95), axis=1) < 0.04
    assert horn_tip.any() and c[horn_tip, 0].mean() < 0.95                       # cyan-ish: fewer quads
    # Reset makes the map again: the horns must stay light (what the director sees = what QR gets)
    S.prepare_maps(0.8, recompute=True)
    me.color_attributes["QR_Density"].data.foreach_get("color_srgb", c.ravel())
    assert c[horn_tip, 0].mean() < 0.95
    assert any("horn" in line for line in S.plan_rows()), S.plan_rows()

def test_resample_chain_even_spacing():
    from forge_bpy.arp_rig import _resample
    pts = _resample([(0, 0, 0), (1, 0, 0), (1, 3, 0)], 4)
    assert len(pts) == 5 and pts[0].length == 0 and (pts[-1] - pts[0]).length > 3
    steps = [(pts[i + 1] - pts[i]).length for i in range(4)]
    assert max(steps) - min(steps) < 0.3            # about 1 unit each along the 4-unit path


def test_budget_goes_to_head_hands_and_joints():
    import numpy as np

    from forge_bpy import density, joints
    body = _creature()
    J = joints.estimate(body)
    V = joints._verts(body)
    f, _w, _n = density.region_factors(V, J)

    def at(p):
        return f[np.argmin(np.linalg.norm(V - np.array(p), axis=1))]
    head, belly = at((0, -0.12, 1.66)), at((0, -0.16, 1.1))
    hand, elbow = at((0.78, 0, 1.42)), at(tuple(J["lowerarm_l"][0]))
    assert head >= 1.5 and hand > 1.3 and elbow >= 1.3 and belly < 0.8, (head, hand, elbow, belly)
    reg = density.region_tris(body, J)
    assert {"head", "body", "arms", "legs"} <= set(reg) and sum(reg.values()) > 0


def test_flat_upright_ears_and_sideways_horns():
    """Shape decides, not direction: flat sheets pointing up are ears (rabbit), round cones
    going out and up are horns (bull)."""
    import bmesh
    from mathutils import Matrix, Vector

    from forge_bpy import appendages, fixture, joints
    fixture.humanoid({"out": "/tmp/_forge_creature2.glb"})
    body = bpy.data.objects["Body"]
    bm = bmesh.new()
    bm.from_mesh(body.data)
    for x in (1, -1):
        # rabbit ear: a flat slab standing up from the side of the head
        m = Matrix.Translation((0.07 * x, 0.0, 1.88)) @ Matrix.Diagonal((0.012, 0.05, 0.14, 1))
        bmesh.ops.create_cube(bm, size=2.0, matrix=m)
        # bull horn: a cone going out more than up
        a, b = Vector((0.1 * x, -0.03, 1.66)), Vector((0.3 * x, -0.03, 1.78))
        d = b - a
        m = Matrix.Translation((a + b) / 2) @ d.to_track_quat("Z", "Y").to_matrix().to_4x4()
        bmesh.ops.create_cone(bm, cap_ends=True, segments=12, radius1=0.035, radius2=0.004,
                              depth=d.length, matrix=m)
    bm.to_mesh(body.data)
    bm.free()
    m = body.modifiers.new("v", "REMESH")
    m.mode, m.voxel_size = "VOXEL", 0.008
    dg = bpy.context.evaluated_depsgraph_get()
    dg.update()
    body.data = bpy.data.meshes.new_from_object(body.evaluated_get(dg))
    body.modifiers.remove(m)
    J = joints.estimate(body)
    kinds = sorted(a["kind"] for a in appendages.from_object(body, J))
    assert kinds.count("ear") == 2 and kinds.count("horn") == 2, kinds


def test_one_sided_tail_is_split_before_mirroring():
    """A tail curling to one side: mirroring the body would make two tails (or none). It is
    found as a one-sided part, split off, and the symmetric body keeps a single tail."""
    import bmesh
    import numpy as np
    from mathutils import Matrix, Vector

    from forge_bpy import density, fixture, rescue
    fixture.humanoid({"out": "/tmp/_forge_creature3.glb"})
    body = bpy.data.objects["Body"]
    bm = bmesh.new()
    bm.from_mesh(body.data)
    pts = [Vector((0.0, 0.12, 0.95)), Vector((0.08, 0.35, 0.75)), Vector((0.3, 0.45, 0.55))]
    for a, b in zip(pts, pts[1:]):                 # a tail that bends to the character's left
        d = b - a
        m = Matrix.Translation((a + b) / 2) @ d.to_track_quat("Z", "Y").to_matrix().to_4x4()
        bmesh.ops.create_cone(bm, cap_ends=True, segments=12, radius1=0.03, radius2=0.025,
                              depth=d.length + 0.03, matrix=m)
    bm.to_mesh(body.data)
    bm.free()
    m = body.modifiers.new("v", "REMESH")
    m.mode, m.voxel_size = "VOXEL", 0.012
    dg = bpy.context.evaluated_depsgraph_get()
    dg.update()
    me = bpy.data.meshes.new_from_object(body.evaluated_get(dg))
    ids = density.one_sided_parts(me)
    co = np.array([v.co[:] for v in me.vertices])
    assert ids.max() == 1, ids.max()
    tip = np.linalg.norm(co - (0.3, 0.45, 0.55), axis=1) < 0.05
    belly = np.linalg.norm(co - (0, -0.16, 1.1), axis=1) < 0.08
    arm = np.abs(co[:, 0]) > 0.5
    assert ids[tip].min() == 1 and ids[belly].max() == 0 and ids[arm].max() == 0
    pieces = rescue.split_off(me, ids)
    density.symmetrize(me, "right")                # keep -X: would have deleted the tail
    co2 = np.array([v.co[:] for v in me.vertices])
    behind = co2[(co2[:, 1] > 0.3) & (co2[:, 2] < 0.85)]
    assert len(behind) == 0                        # no mirrored tail on the body
    assert len(pieces) == 1                        # the one tail travels on its own
