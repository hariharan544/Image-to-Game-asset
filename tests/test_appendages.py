"""Extra body parts (tail, ears, horns) are found on a T-pose body and get a joint chain."""

import sys
from pathlib import Path

import pytest

bpy = pytest.importorskip("bpy")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "blender_scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))


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
    assert plan.get("tail", "").startswith("separate"), plan
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


@pytest.mark.parametrize("curl", [1.0, -1.0])
def test_curled_tail_is_cut_at_its_root_and_never_mirrored(curl):
    """A tail hanging on the centre line, then curling to one side: the cut is at the rump
    (where the surface turns into the body), not where the tail stops being symmetric. After
    the split, making the body symmetric from either side leaves no stub to mirror."""
    import numpy as np
    from mathutils import Vector

    import bodies
    from forge_bpy import density, parts, rescue
    body, P = bodies.curled_tail(curl)
    me = body.data
    co = bodies.coords(me)
    al = np.array([bodies.arc(P, c) for c in co])
    tail = (al[:, 0] < 0.06) & (al[:, 1] > 0.06)
    rep = []
    ids = parts.one_sided_parts(me, report=rep)
    assert ids.max() == 1, rep
    left = tail & (ids == 0)
    assert al[left, 1].max() < 0.17, al[left, 1].max()            # the rump surface is at ~0.12
    assert ((ids > 0) & (al[:, 0] > 0.06)).sum() == 0              # nothing away from the tail taken
    Pm = [Vector((-p.x, p.y, p.z)) for p in P]
    for side in ("left", "right"):
        m2 = me.copy()
        pieces = rescue.split_off(m2, ids)
        density.symmetrize(m2, side)
        c2 = bodies.coords(m2)
        for path in (P, Pm):
            a = np.array([bodies.arc(path, q) for q in c2])
            assert ((a[:, 0] < 0.04) & (a[:, 1] > 0.2)).sum() == 0, side    # no stub, no V
        assert bodies.open_edges(m2) == (0, 0)
        assert len(pieces) == 1 and bodies.open_edges(pieces[0][1]) == (0, 0)


def test_arms_in_different_poses_are_a_pair_not_parts():
    """An AI mesh's right hand 20 cm higher than the left: a pair in another pose. The chosen
    side wins for both arms; nothing is cut off the arm (that left slits on both arms)."""
    import numpy as np

    import bodies
    from forge_bpy import parts
    o = bodies.biped(arm_dz=0.2, tail=True)
    rep = []
    ids = parts.one_sided_parts(o.data, report=rep)
    co = bodies.coords(o.data)
    assert ((ids > 0) & (np.abs(co[:, 0]) > 0.45) & (co[:, 1] < 0.3)).sum() == 0, rep
    assert any(r[0] in ("pair", "kept") and abs(r[1][0]) > 0.45 for r in rep), rep   # seen, left alone
    tail = co[:, 1] > 0.45
    assert (ids[tail] > 0).all()                                   # the tail is still its own part


@pytest.mark.parametrize("tail_side", [0.30, 0.0])
def test_round_cartoon_bull_parts_found_whole(tail_side):
    """Fat belly, neckless head, horns going sideways then up, flat ears under them, thin tail
    with a tuft: every part is found whole (grown to its neck), horns are horns, ears are
    ears, the tail is thin and rooted at the rump."""
    import numpy as np

    import bodies
    from forge_bpy import appendages, joints
    ob = bodies.bull(tail_side=tail_side)
    J = joints.estimate(ob)
    found = {a["name"]: a for a in appendages.from_object(ob, J)}
    assert set(found) == {"tail", "horn_l", "horn_r", "ear_l", "ear_r"}, sorted(found)
    tail = found["tail"]
    assert tail["thin"] and tail["cut_ok"]
    assert np.linalg.norm(np.array(tail["chain"][0]) - (0, 0.24, 0.30)) < 0.05      # root at the rump
    for s in "lr":
        assert found[f"horn_{s}"]["kind"] == "horn" and found[f"ear_{s}"]["kind"] == "ear"
        assert found[f"horn_{s}"]["chain"][-1][2] > 0.95                              # tip at the top


def test_plan_lists_what_the_run_cuts():
    """The parts plan makes the split decision once; the run reads it. A curled tail with a
    side chosen: the plan lists it as separate and forge_split holds exactly that cut."""
    import importlib

    import numpy as np

    import bodies
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "blender_addon"))
    body, P = bodies.curled_tail(1.0)
    col = bpy.data.collections.new("Forge Parts")
    bpy.context.scene.collection.children.link(col)
    for c in list(body.users_collection):
        c.objects.unlink(body)
    col.objects.link(body)
    body["forge_kind"] = "body"
    S = importlib.import_module("forge_send.steps")
    from forge_bpy import density
    try:
        plan = S.plan_parts(recompute=True, side="left")
        assert any(v.startswith("separate") for v in plan.values()), plan
        ids = density.read_split(body.data)
        co = bodies.coords(body.data)
        al = np.array([bodies.arc(P, c) for c in co])
        tail = (al[:, 0] < 0.06) & (al[:, 1] > 0.17)
        assert ids is not None and (ids[tail] > 0).all() and ((ids > 0) & (al[:, 0] > 0.08)).sum() == 0
        assert body.data.get("forge_onesided_planned") and S.plan_rows()
    finally:
        bpy.ops.wm.read_homefile(use_empty=True)


def test_mirror_plane_is_measured_from_the_shape_not_the_box():
    """A body whose middle is 2.5 cm off x = 0 (one-sided curled tail included): the mirror
    plane comes from its own symmetry."""
    from mathutils import Matrix

    import bodies
    from forge_bpy import density
    ob = bodies.bull(tail_side=0.30)
    ob.data.transform(Matrix.Translation((0.025, 0.0, 0.0)))
    x0 = density.mirror_plane(ob.data)
    assert abs(x0 - 0.025) < 0.003, x0


LONG = [(0, 0.0, 0.97), (0, 0.12, 0.95), (0.0, 0.22, 0.80), (0.0, 0.27, 0.55), (0.0, 0.28, 0.30),
        (0.05, 0.28, 0.12), (0.25, 0.27, 0.08), (0.45, 0.25, 0.10)]


@pytest.mark.parametrize("kind", ["long", "thick", "big"])
def test_hard_one_sided_tails_are_still_cut_at_the_root(kind):
    """Review cases: a tail hanging far before it curls (its fragment is far from the rump),
    a thick tail next to legs about as thick, a tail with a big share of the vertices: each is
    cut at the rump, and mirroring from either side leaves no copy and loses nothing."""
    import numpy as np
    from mathutils import Vector

    import bodies
    from forge_bpy import density, parts, rescue
    path = LONG if kind == "long" else None
    r = {"long": 0.022, "thick": 0.035, "big": 0.03}[kind]
    if kind == "big":
        path = LONG + [(0.62, 0.30, 0.20), (0.75, 0.38, 0.35)]
    body, P = bodies.curled_tail(1.0, r=r, path=path)
    me = body.data
    co = bodies.coords(me)
    al = np.array([bodies.arc(P, c) for c in co])
    rep = []
    ids = parts.one_sided_parts(me, report=rep)
    assert ids.max() == 1, rep
    tail = (al[:, 0] < r + 0.03) & (al[:, 1] > 0.2)
    assert (ids[tail] > 0).mean() > 0.98, (ids[tail] > 0).mean()
    m2 = me.copy()
    assert len(rescue.split_off(m2, ids)) == 1
    density.symmetrize(m2, "left")
    c2 = bodies.coords(m2)
    Pm = [Vector((-p.x, p.y, p.z)) for p in P]
    a2 = np.array([bodies.arc(Pm, q) for q in c2])
    assert ((a2[:, 0] < r + 0.02) & (a2[:, 1] > 0.3) & (c2[:, 0] < -0.1)).sum() == 0     # no mirrored copy


def test_parts_do_not_depend_on_object_scale():
    from mathutils import Matrix

    import bodies
    from forge_bpy import appendages, joints
    ob = bodies.bull()
    ref = sorted((a["name"], a["kind"]) for a in appendages.from_object(ob, joints.estimate(ob)))
    ob.data.transform(Matrix.Scale(2.0, 4))
    ob.scale = (0.5, 0.5, 0.5)
    bpy.context.view_layer.update()
    got = sorted((a["name"], a["kind"]) for a in appendages.from_object(ob, joints.estimate(ob)))
    assert got == ref, (got, ref)


def test_mirror_plane_on_a_longer_arm():
    """Assemble centres the body by its box; one arm 6 cm longer moves the box, not the
    middle: the plane is found where the body is symmetric."""
    import bodies
    from forge_bpy import density
    o = bodies.biped()
    import bmesh
    from mathutils import Matrix
    bm = bmesh.new()
    bm.from_mesh(o.data)
    bmesh.ops.create_icosphere(bm, subdivisions=2, radius=0.09, matrix=Matrix.Translation((-1.02, 0, 1.10)))
    bm.to_mesh(o.data)
    bm.free()
    co = bodies.coords(o.data)
    box_mid = (co[:, 0].min() + co[:, 0].max()) / 2
    o.data.transform(Matrix.Translation((-box_mid, 0, 0)))     # centred by its box, like Assemble
    x0 = density.mirror_plane(o.data)
    assert abs(x0 - (-box_mid)) < 0.004, (x0, -box_mid)


def _as_forge_body(ob):
    import importlib
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "blender_addon"))
    col = bpy.data.collections.new("Forge Parts")
    bpy.context.scene.collection.children.link(col)
    for c in list(ob.users_collection):
        c.objects.unlink(ob)
    col.objects.link(ob)
    ob["forge_kind"] = "body"
    return importlib.import_module("forge_send.steps")


def test_plan_is_cached_measured_in_place_and_keeps_the_directors_paint(monkeypatch):
    import numpy as np

    import bodies
    from forge_bpy import appendages, density
    ob = bodies.bull()
    S = _as_forge_body(ob)
    try:
        S.prepare_maps(0.8, side="auto")
        plan = dict(ob["forge_plan"])
        assert plan.get("tail", "").startswith("separate") and plan.get("horn_l") == "rigid, fewer quads"
        # the director paints a horn tip red, then picks Left: the plan is made again for
        # mirroring, the paint stays
        me = ob.data
        co = bodies.coords(me)
        lv = np.array([l.vertex_index for l in me.loops])
        tip = np.linalg.norm(co[lv] - (0.26, -0.02, 0.98), axis=1) < 0.03
        c = np.empty(len(me.loops) * 4, np.float32)
        me.color_attributes["QR_Density"].data.foreach_get("color_srgb", c)
        c = c.reshape(-1, 4)
        c[tip] = (1, 0, 0, 1)
        me.color_attributes["QR_Density"].data.foreach_set("color_srgb", c.ravel())
        ob.location.x = 1.5                             # "Compare with original" moved it aside
        S.prepare_maps(0.8, side="left")
        assert ob.location.x == 1.5
        assert dict(ob["forge_plan"]).get("tail", "").startswith("separate")   # measured in place
        me.color_attributes["QR_Density"].data.foreach_get("color_srgb", c.ravel())
        assert c[tip, 1].mean() < 0.1                   # still red
        # an empty plan is a plan: not made again on every click
        calls = []
        real = appendages.from_object
        monkeypatch.setattr(appendages, "from_object", lambda *a, **k: calls.append(1) or real(*a, **k))
        ob["forge_plan"] = {}
        S.prepare_maps(0.8, side="left")
        S.prepare_maps(0.8, side="left")
        assert not calls and not S.plan_needed("left")
    finally:
        bpy.ops.wm.read_homefile(use_empty=True)


def test_raised_hand_is_still_an_arm():
    import numpy as np

    import bodies
    from forge_bpy import density, joints
    o = bodies.biped(arm_dz=0.2)
    J = joints.estimate(o)
    V = joints._verts(o)
    lab = density.region_labels(V, J)
    past = np.abs(V[:, 0]) > abs(J["upperarm_l"][0][0]) * 1.05
    assert (lab[past] == 1).sum() == 0                  # nothing past the shoulders is head


def test_a_cut_the_hole_fillers_refuse_is_closed_by_a_fan(monkeypatch):
    """On the director's mesh the tail-root opening was refused by Blender's fillers and the
    body was left unmirrored. Any simple opening now closes as a fan of triangles."""
    import bmesh

    import bodies
    from forge_bpy import parts, rescue
    body, _P = bodies.curled_tail(1.0)
    me = body.data
    ids = parts.one_sided_parts(me)
    monkeypatch.setattr(bmesh.ops, "holes_fill", lambda *a, **k: {"faces": []})
    monkeypatch.setattr(bmesh.ops, "edgeloop_fill", lambda *a, **k: {"faces": []})
    rep = []
    m2 = me.copy()
    pieces = rescue.split_off(m2, ids, rep)
    assert len(pieces) == 1 and not rep, rep
    assert rescue.mesh_defects(m2)[:2] == (0, 0)


def test_tail_curling_round_to_the_side_is_still_a_tail():
    import bodies
    from forge_bpy import appendages, joints
    ob = bodies.bull(tail_side=0.30)
    for v in ob.data.vertices:                     # the curl comes round beside the leg
        if v.co.y > 0.30 and v.co.z < 0.16:
            v.co.y -= 0.25 * (0.16 - v.co.z) / 0.16
    names = [a["name"] for a in appendages.from_object(ob, joints.estimate(ob))]
    assert "tail" in names, names


def test_ragged_cut_borders_are_closed_on_the_first_attempt():
    """On a dense AI-like mesh a ragged cut border has chords (a body edge between two rim
    vertices that are not neighbours on the loop); a hole filler then gives that edge a third
    face and the cut was refused - the body was then not mirrored and the mouth lost detail
    on one side. Closed with a fan first, every one is cut at the first attempt."""
    import numpy as np

    import bodies
    from forge_bpy import parts, rescue
    ob = bodies.bull(voxel=0.005)
    me = ob.data
    ids0 = parts.one_sided_parts(me)
    assert ids0.max() == 1
    calls = []
    real = rescue._rim_cut

    def counted(*a, **k):
        calls.append(1)
        return real(*a, **k)
    rescue._rim_cut = counted
    try:
        for seed in range(6):
            ids = bodies.ragged(me, ids0, 1, seed)
            calls.clear()
            m2 = me.copy()
            rep = []
            pieces = rescue.split_off(m2, ids, rep)
            assert len(pieces) == 1 and not rep, (seed, rep)
            assert len(calls) == 1, (seed, len(calls))          # no re-cut needed
            assert rescue.mesh_defects(m2)[:2] == (0, 0), seed
    finally:
        rescue._rim_cut = real
