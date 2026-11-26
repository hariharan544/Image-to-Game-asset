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
