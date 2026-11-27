"""Step 8 rig: what the skin follows.

- the engines' bone limit fades the weakest bones out (no seam where two bones swap places)
- a chain (tail, ears) hangs from the body bone its root grows out of
- appendage bones do not drag the body skin around them, and the parent bone owns the root
- the head pivots at the base of the skull, the spine below stays where it was
- the skinning is the engines' (linear blend), never Preserve Volume
"""

import importlib
import sys
from pathlib import Path

import pytest

bpy = pytest.importorskip("bpy")
np = pytest.importorskip("numpy")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "blender_scripts"))
sys.path.insert(0, str(ROOT / "blender_addon"))
sys.path.insert(0, str(ROOT / "tests"))


# ----------------------------------------------------------------------------- bone limit

def test_bone_limit_is_continuous_where_the_weakest_bones_swap():
    from forge_bpy.skin import engine_limit, limit_influences
    # two neighbouring points: the 4th and 5th strongest bones swap places between them
    eps = np.array([0.02, 0.002, 0.0002])
    for e in eps:
        a = np.array([[0.40, 0.20, 0.15, 0.12 + e, 0.12]])
        b = np.array([[0.40, 0.20, 0.15, 0.12, 0.12 + e]])
        soft = np.abs(limit_influences(a, 4) - limit_influences(b, 4)).max()
        hard = np.abs(limit_influences(a, 4, continuous=False) - limit_influences(b, 4, continuous=False)).max()
        assert soft < 10 * e + 1e-12, (e, soft)          # shrinks with the difference
        assert hard > 0.12, hard                         # the hard cut jumps by a whole bone
    w = limit_influences(np.array([[0.4, 0.3, 0.2, 0.06, 0.04]]), 4)
    assert (w > 0).sum() <= 4 and abs(w.sum() - 1) < 1e-12
    assert np.allclose(w[0, :3] / w[0, :3].sum(), np.array([0.36, 0.26, 0.16]) / 0.78)
    # a row with no more bones than the limit is only normalised
    assert np.allclose(limit_influences(np.array([[0.5, 0.25, 0.25, 0.0, 0.0]]), 4), [[0.5, 0.25, 0.25, 0, 0]])
    # nothing left after the subtraction (all equal): the hard cut, never an empty point
    w = limit_influences(np.full((1, 6), 0.2), 4)
    assert (w > 0).sum() == 4 and abs(w.sum() - 1) < 1e-12
    assert limit_influences(np.zeros((2, 5)), 4).sum() == 0
    # the engine limit drops tiny weights first, as the export does
    w = engine_limit(np.array([[0.6, 0.395, 0.005]]), 4)
    assert w[0, 2] == 0 and abs(w.sum() - 1) < 1e-12


def test_cleanup_uses_the_same_limit_as_the_engines():
    """skin._cleanup_weights (bind and export) gives exactly engine_limit on the mesh."""
    import bmesh
    from forge_bpy.skin import _cleanup_weights, engine_limit, weight_matrix
    bpy.ops.wm.read_homefile(use_empty=True)
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=6, y_segments=6, size=1.0)
    me = bpy.data.meshes.new("g")
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new("g", me)
    bpy.context.scene.collection.objects.link(o)
    rng = np.random.default_rng(3)
    names = [f"b{i}" for i in range(7)]
    W = rng.random((len(me.vertices), 7)) ** 3
    for j, n in enumerate(names):
        g = o.vertex_groups.new(name=n)
        for i in range(len(me.vertices)):
            g.add([i], float(W[i, j]), "REPLACE")
    _cleanup_weights(o, 4, 0.01, set(names))
    got_names, got = weight_matrix(o, set(names))
    want = engine_limit(W, 4)
    full = np.zeros_like(want)
    for j, n in enumerate(got_names):
        full[:, names.index(n)] = got[:, j]
    assert np.abs(full - want).max() < 1e-6
    assert ((full > 0).sum(axis=1) <= 4).all()


# ----------------------------------------------------------------------------- chain parents

def _spine_segments():
    V = lambda *a: np.array(a, float)      # noqa: E731
    return {"root_ref.x": (V(0, 0.0, 0.14), V(0, 0.0, 0.22)), "spine_01_ref.x": (V(0, 0.0, 0.22), V(0, 0.0, 0.44)),
            "spine_02_ref.x": (V(0, 0.0, 0.44), V(0, 0.0, 0.61)), "neck_ref.x": (V(0, 0.0, 0.61), V(0, 0.0, 0.67)),
            "head_ref.x": (V(0, 0.0, 0.67), V(0, 0.0, 1.0))}


def test_a_chain_hangs_from_the_bone_its_root_grows_out_of():
    from forge_bpy.arp_rig import appendage_parent
    segs = _spine_segments()
    assert appendage_parent(segs, (0, 0.24, 0.30)) == "spine_01_ref.x"      # the bull's tail root
    assert appendage_parent(segs, (0.19, 0.0, 0.745)) == "head_ref.x"       # its ear roots
    assert appendage_parent(segs, (0, 0.2, 0.10)) == "root_ref.x"           # below everything: nearest
    assert appendage_parent(segs, (0, 0.1, 0.64)) == "neck_ref.x"
    assert appendage_parent({}, (0, 0, 0)) is None


def test_bull_chain_roots_project_onto_spine_and_head():
    """On the bull as Forge places it: the tail root is in spine_01's span (not the hips'), the
    ears' roots in the head's."""
    import bodies
    from forge_bpy import appendages, arp_rig, joints
    body = bodies.bull()
    J = joints.estimate(body)
    T = arp_rig.ref_targets(J, 0.0, 1.0)
    segs = {k: T[k] for k in ("root_ref.x", "spine_01_ref.x", "spine_02_ref.x", "neck_ref.x", "head_ref.x")}
    found = {a["name"]: a for a in appendages.from_object(body, J)}
    assert arp_rig.appendage_parent(segs, found["tail"]["chain"][0]) == "spine_01_ref.x"
    for s in "lr":
        assert arp_rig.appendage_parent(segs, found[f"ear_{s}"]["chain"][0]) == "head_ref.x"


def _armature(bones: dict, name="rig"):
    """bones: {name: (head, tail, parent, deform)}"""
    ad = bpy.data.armatures.new(name)
    arm = bpy.data.objects.new(name, ad)
    bpy.context.scene.collection.objects.link(arm)
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    for n, (h, t, _p, d) in bones.items():
        b = ad.edit_bones.new(n)
        b.head, b.tail, b.use_deform = h, t, d
    for n, (_h, _t, p, _d) in bones.items():
        if p:
            ad.edit_bones[n].parent = ad.edit_bones[p]
    bpy.ops.object.mode_set(mode="OBJECT")
    return arm


def test_reference_chains_are_rehung_and_the_real_parents_checked():
    from forge_bpy import arp_rig
    bpy.ops.wm.read_homefile(use_empty=True)
    segs = _spine_segments()
    bones = {k: (tuple(h), tuple(t), None, False) for k, (h, t) in segs.items()}
    bones["tail_00_ref.x"] = ((0, 0.24, 0.30), (0, 0.33, 0.20), "root_ref.x", False)    # ARP's default
    bones["ear_01_ref.l"] = ((0.19, 0, 0.745), (0.3, 0, 0.74), "head_ref.x", False)
    ref = _armature(bones, "ref")
    bpy.ops.object.mode_set(mode="EDIT")
    hung = arp_rig.hang_chains(ref)
    assert ref.data.edit_bones["tail_00_ref.x"].parent.name == "spine_01_ref.x"
    bpy.ops.object.mode_set(mode="OBJECT")
    assert hung["tail"] == {"ref_parent": "spine_01_ref.x", "was": "root_ref.x"}
    assert hung["ear_l"] == {"ref_parent": "head_ref.x", "was": "head_ref.x"}          # ARP's own kept
    # after match_to_rig: the real chain must hang from spine_01 (else: reported, not raised)
    final = {"root.x": ((0, 0, .14), (0, 0, .22), None, True), "spine_01.x": ((0, 0, .22), (0, 0, .44), "root.x", True),
             "c_head.x": ((0, 0, .67), (0, 0, 1), "spine_01.x", False), "head.x": ((0, 0, .67), (0, 0, 1), "c_head.x", True),
             "c_skull_02.x": ((0, 0, .8), (0, 0, .9), "head.x", False),
             "c_tail_00.x": ((0, .24, .3), (0, .33, .2), "spine_01.x", True),
             "c_tail_01.x": ((0, .33, .2), (0, .4, .1), "c_tail_00.x", True),
             "c_ear_01.l": ((.19, 0, .745), (.3, 0, .74), "c_skull_02.x", True)}
    rig = _armature(final)
    cp = arp_rig.chain_parents(rig, hung)
    assert cp["tail"]["ok"] and cp["tail"]["parent"] == "spine_01.x" and cp["tail"]["body_bone"] == "spine_01.x"
    assert cp["ear_l"]["ok"] and cp["ear_l"]["body_bone"] == "head.x"     # through the skull control
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    rig.data.edit_bones["c_tail_00.x"].parent = rig.data.edit_bones["root.x"]
    bpy.ops.object.mode_set(mode="OBJECT")
    cp = arp_rig.chain_parents(rig, hung)
    assert cp["tail"]["ok"] is False and cp["tail"]["wanted"] == "spine_01.x" and cp["tail"]["parent"] == "root.x"


# ----------------------------------------------------------------------------- weights round the root

def _strip(n=10):
    """Points 0..n-1 in a line (edges between neighbours): 0-2 are the tail, the rest body."""
    bpy.ops.wm.read_homefile(use_empty=True)
    me = bpy.data.meshes.new("strip")
    me.from_pydata([(0, 0.4 - 0.05 * i, 0.3) for i in range(n)], [(i, i + 1) for i in range(n - 1)], [])
    o = bpy.data.objects.new("Body_low", me)
    bpy.context.scene.collection.objects.link(o)
    return o


def _weights(o, rows: dict):
    for name, col in rows.items():
        g = o.vertex_groups.get(name) or o.vertex_groups.new(name=name)
        for i, w in enumerate(col):
            if w > 0:
                g.add([i], float(w), "REPLACE")


@pytest.mark.parametrize("parent", ["spine_01.x", "root.x"])
def test_appendage_weight_outside_it_goes_to_its_parent_with_a_falloff(parent):
    from forge_bpy import arp_rig
    from forge_bpy.skin import weight_matrix
    body = _strip()
    rig = _armature({"root.x": ((0, 0, .14), (0, 0, .22), None, True),
                     "spine_01.x": ((0, 0, .22), (0, 0, .44), "root.x", True),
                     "c_tail_00.x": ((0, .24, .3), (0, .33, .2), parent, True),
                     "c_tail_01.x": ((0, .33, .2), (0, .4, .1), "c_tail_00.x", True)})
    n = 10
    tail = [1.0, 1.0, 1.0] + [0.4] * (n - 3)            # bone heat: the tail moves body skin too
    spine = [0.0, 0.0, 0.0] + [0.6] * (n - 3)
    _weights(body, {"c_tail_00.x": tail, "spine_01.x": spine})
    body.vertex_groups.new(name="root.x")              # (the bind makes a group per deform bone)
    stored = arp_rig.store_regions(body, [{"name": "tail", "vert_idx": np.array([0, 1, 2])},
                                          {"name": "horn_l", "vert_idx": np.array([5])}], ["tail"])
    assert stored == ["tail"] and "forge_app_tail" in body.data.attributes
    rep = arp_rig.settle_appendages(body, rig)["tail"]
    names, W = weight_matrix(body, {"c_tail_00.x", "spine_01.x", "root.x"})
    t = W[:, names.index("c_tail_00.x")]
    p = W[:, names.index(parent)]
    assert np.allclose(t[:3], 1.0)                                       # the tail keeps its own skin
    assert np.allclose(t[3:7], [0.3, 0.2, 0.1, 0.0])                     # 3 rings of fade, then none
    assert np.allclose(W.sum(axis=1), 1.0)                               # nothing renormalised away
    assert np.allclose(p[3:6], 1.0 - t[3:6] - (spine[3:6] if parent == "root.x" else 0.0))
    assert rep["parent"] == parent and rep["moved_points"] == n - 3
    if parent == "spine_01.x":                  # the parent moves all the skin round the root
        assert rep["root_share"] == 1.0 and rep["root_ok"]
    else:                                       # hung from the hips while the spine owns the root
        assert rep["root_share"] == 0.0 and not rep["root_ok"] and rep["root_owner"] == "spine_01.x"
    # the panel says so in plain words
    L = importlib.import_module("forge_send.stages_late")
    rows = L._chain_rows({"appendages": {"tail": rep}})
    text = " ".join(r for _i, r in rows)
    if parent == "spine_01.x":
        assert "tail hangs from spine 01" in text and "100%" in text, text
    else:
        assert "moves" in text and "spine 01" in text and "can tear" in text and rows[0][0] == L.WARN, text
    assert max(len(r) for _i, r in rows) <= 60


def test_preserve_volume_is_turned_off_and_reported():
    from forge_bpy import arp_rig
    body = _strip()
    rig = _armature({"root.x": ((0, 0, 0), (0, 0, 1), None, True)})
    m = body.modifiers.new("rig", "ARMATURE")
    m.object, m.use_deform_preserve_volume = rig, True
    other = body.modifiers.new("other", "ARMATURE")
    other.use_deform_preserve_volume = True                               # not driven by this rig
    rep = arp_rig.linear_blend(rig, [body])
    assert rep["preserve_volume_found"] and rep["preserve_volume_on"] == ["Body_low"]
    assert not m.use_deform_preserve_volume and other.use_deform_preserve_volume
    assert arp_rig.linear_blend(rig, [body])["preserve_volume_found"] is False


# ----------------------------------------------------------------------------- head pivot

def _necked(neck_len):
    import bmesh
    from mathutils import Matrix, Vector
    bpy.ops.wm.read_homefile(use_empty=True)
    bm = bmesh.new()

    def ball(c, r, s=(1, 1, 1)):
        bmesh.ops.create_uvsphere(bm, u_segments=24, v_segments=16, radius=1.0,
                                  matrix=Matrix.Translation(c) @ Matrix.Diagonal((r * s[0], r * s[1], r * s[2], 1)))

    def tube(a, b, r):
        a, b = Vector(a), Vector(b)
        m = Matrix.Translation((a + b) / 2) @ (b - a).to_track_quat("Z", "Y").to_matrix().to_4x4()
        bmesh.ops.create_cone(bm, cap_ends=True, segments=16, radius1=r, radius2=r, depth=(b - a).length, matrix=m)
    ball((0, 0, 0.9), 0.3, (1, 0.8, 1.3))
    top = 0.9 + 0.39
    tube((0, 0, top - 0.05), (0, 0, top + neck_len), 0.06)
    ball((0, 0, top + neck_len + 0.11), 0.13)
    for x in (1, -1):
        tube((0.2 * x, 0, 1.1), (0.8 * x, 0, 1.1), 0.06)
        tube((0.12 * x, 0, 0.6), (0.12 * x, 0, 0.02), 0.08)
    me = bpy.data.meshes.new("n")
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new("Body", me)
    bpy.context.scene.collection.objects.link(ob)
    mod = ob.modifiers.new("v", "REMESH")
    mod.mode, mod.voxel_size = "VOXEL", 0.01
    dg = bpy.context.evaluated_depsgraph_get()
    dg.update()
    ob.data = bpy.data.meshes.new_from_object(ob.evaluated_get(dg))
    ob.modifiers.remove(mod)
    return ob, top + neck_len - 0.02                       # (where the head ball starts)


def _bodies():
    import bodies
    from forge_bpy import fixture
    yield "bull", bodies.bull(), None
    yield "biped", bodies.biped(), None
    fixture.humanoid({"out": "/tmp/_forge_skull_h.glb"})
    yield "humanoid", bpy.data.objects["Body"], None
    for length in (0.2, 0.3):
        ob, head_bottom = _necked(length)
        yield f"neck {length}", ob, head_bottom


def test_the_head_pivots_at_the_skull_base_and_the_spine_stays():
    """Neckless bodies (bull, round biped, the humanoid's head on its shoulders): the skull base
    is the narrowest section. A neck tube: the top of the tube, where the head starts. The
    head bone starts there; root, spine_01 and the spine's middle do not move; the joints the
    rest of Forge reads (neck, head) are unchanged."""
    from forge_bpy import arp_rig, joints
    for name, ob, head_bottom in _bodies():
        V = joints._verts(ob)
        H = V[:, 2].max() - V[:, 2].min()
        J = joints.estimate(ob)
        sb, neck, head = J["_skull_base"], J["neck"][0], J["head"][0]
        if head_bottom is None:
            assert abs(sb.z - neck.z) <= 0.01 * H, (name, sb.z, neck.z)
        else:
            assert abs(sb.z - head_bottom) <= 0.025 * H and sb.z > neck.z + 0.05 * H, (name, sb.z, head_bottom)
        assert sb.z < J["head"][1].z
        T = arp_rig.ref_targets(J, V[:, 2].min(), V[:, 2].max())
        J0 = dict(J)
        del J0["_skull_base"]
        T0 = arp_rig.ref_targets(J0, V[:, 2].min(), V[:, 2].max())        # what it was before
        for k in ("root_ref.x", "spine_01_ref.x"):
            assert all((a - b).length < 1e-9 for a, b in zip(T[k], T0[k])), (name, k)
        assert (T["spine_02_ref.x"][0] - T0["spine_02_ref.x"][0]).length < 1e-9
        assert (T["head_ref.x"][0] - sb).length < 1e-9 and (T["neck_ref.x"][1] - sb).length < 1e-9
        n0 = T["neck_ref.x"][0]
        assert (T["spine_02_ref.x"][1] - n0).length < 1e-9
        assert T["spine_02_ref.x"][0].z + 0.019 * H <= n0.z < sb.z, (name, n0.z)
        assert T["head_ref.x"][1].z >= J["head"][1].z - 1e-6
        assert len(T) == len(T0)
        # neck and head (appendages, density, UVs read them) are what they were
        assert J0["neck"][0] == neck and J0["head"][0] == head


# ----------------------------------------------------------------------------- the whole rig

@pytest.fixture(scope="module")
def bull_rigged():
    import arp_like
    import bodies
    S = importlib.import_module("forge_send.steps")
    from forge_bpy import motion_check as M
    body = bodies.bull(voxel=0.012)
    body["forge_role"], body["forge_part"], body["forge_kind"] = "low", "Body", "body"
    arm, J, apps, rep = arp_like.build(body)
    S.sample_animation("rom")
    sc = bpy.context.scene

    def posed(f=None):
        if f is not None:
            sc.frame_set(f)
        dg = bpy.context.evaluated_depsgraph_get()
        ev = body.evaluated_get(dg)
        me = ev.to_mesh()
        co = M._world_co(me, ev.matrix_world)
        ev.to_mesh_clear()
        return co
    arm.data.pose_position = "REST"
    bpy.context.view_layer.update()
    rest = posed()
    arm.data.pose_position = "POSE"
    bpy.context.view_layer.update()
    E = M._edges(body.data)
    rl = np.linalg.norm(rest[E[:, 0]] - rest[E[:, 1]], axis=1)
    ok = rl > 0.25 * np.median(rl)                       # (voxel remesh leaves sub-micron edges)
    frames = sorted(set(range(1, S.CLIP_LENGTH["rom"] + 1, 4)) | {f for f, _ in S.clip_peaks("rom")})
    ratio = {f: np.linalg.norm((c := posed(f))[E[:, 0]] - c[E[:, 1]], axis=1) / np.maximum(rl, 1e-12) for f in frames}
    out = {"body": body, "arm": arm, "apps": apps, "rep": rep, "E": E, "ok": ok, "ratio": ratio,
           "posed": posed, "S": S}
    yield out
    S.pose_test_stop()


def test_bull_rig_chains_hang_right_and_keep_the_body_still(bull_rigged):
    """Measured before this change on the same bull: tail hung from the hips owning 0 % of its
    root, ear flaps dragging body skin 35 mm (4772 points over 5 mm)."""
    rep, body, apps = bull_rigged["rep"], bull_rigged["body"], bull_rigged["apps"]
    assert rep["parents"] == {"tail": "spine_01.x", "ear_l": "head.x", "ear_r": "head.x"}
    assert set(rep["regions"]) == {"tail", "ear_l", "ear_r"}
    for app, a in rep["appendages"].items():
        assert a["root_ok"] and a["root_share"] >= (0.8 if app == "tail" else 0.6), (app, a)
        assert a["moved_points"] > 100
    S = bull_rigged["S"]
    peak = {n: f for f, n in S.clip_peaks("rom")}
    app_pts = np.zeros(len(body.data.vertices), bool)
    for a in apps:
        if a["name"] in rep["regions"]:
            app_pts[a["vert_idx"]] = True
    drag = np.linalg.norm(bull_rigged["posed"](peak["tail and ears"]) - bull_rigged["posed"](1), axis=1)[~app_pts]
    assert drag.max() < 0.02 and (drag > 0.005).sum() < 500, (drag.max(), (drag > 0.005).sum())


def test_bull_tail_root_and_head_turn_hold_over_the_range_of_motion(bull_rigged):
    """Before: the tail root stretched 2.72x bending forward, the ears 2.84x looking round. With
    the tail on spine_01 and the head pivot at the skull base: under 2x, and about the 2.1x a
    60-degree head turn on a neckless body asks for (that floor is the pose, not the skin)."""
    S, ratio, ok, body = bull_rigged["S"], bull_rigged["ratio"], bull_rigged["ok"], bull_rigged["body"]
    E = bull_rigged["E"]
    from forge_bpy.skin import weight_matrix
    deform = {b.name for b in bull_rigged["arm"].data.bones if b.use_deform}
    names, W = weight_matrix(body, deform)
    on_tail = W[:, [names.index(b) for b in names if b.startswith("c_tail_")]].sum(axis=1) > 0.5
    tail_e = ok & (on_tail[E[:, 0]] | on_tail[E[:, 1]])
    tail_worst = max(r[tail_e].max() for r in ratio.values())
    look = [f for f in ratio if S.clip_pose("rom", f)[1] == "look round"]
    look_worst = max(ratio[f][ok].max() for f in look)
    whole = max(r[ok].max() for r in ratio.values())
    assert tail_worst < 2.0, tail_worst
    assert look_worst < 2.3, look_worst
    assert whole < 2.45, whole


# ----------------------------------------------------------------------------- Step 8, end to end

@pytest.fixture
def fake_arp():
    import fake_arp as A
    A.register()
    A.IGNORE_TAIL_PARENT = False
    A.SEEN.clear()
    try:
        yield A
    finally:
        A.IGNORE_TAIL_PARENT = False
        A.unregister()


@pytest.mark.parametrize("arp_differs", [False, True])
def test_place_and_build_hang_the_chains_and_bind_like_the_engines(fake_arp, arp_differs):
    """Place the joints, build: the tail hangs from spine_01 (its root grows out of it), the ears
    from the head; Auto-Rig Pro binds without Preserve Volume; the tail and ear bones no longer
    move the body round them, and the panel says what each chain hangs from. An Auto-Rig Pro
    that hangs the tail elsewhere is reported in plain words, nothing crashes."""
    import bodies
    S = importlib.import_module("forge_send.steps")
    L = importlib.import_module("forge_send.stages_late")
    body = bodies.bull()                                       # (ears are found as ears at this size)
    body["forge_role"], body["forge_part"], body["forge_kind"] = "low", "Body", "body"
    body.name = "Body_low"
    fake_arp.IGNORE_TAIL_PARENT = arp_differs
    placed = S.place_joints()
    ex = placed["extras"]
    assert not ex["errors"] and ex["added"] == {"tail": 4, "ears": 4}, ex
    assert set(ex["regions"]) == {"tail", "ear_l", "ear_r"}
    assert ex["parents"]["tail"] == {"ref_parent": "spine_01_ref.x", "was": "root_ref.x"}
    assert ex["parents"]["ear_l"]["ref_parent"] == "head_ref.x"
    ref = S.ref_rig()
    assert ref.data.bones["tail_00_ref.x"].parent.name == "spine_01_ref.x"
    rep = S.build_rig(8)
    assert fake_arp.SEEN["arp_bind_preserve"] is False                  # asked before the bind
    assert rep["skinning"] == {"preserve_volume_found": False, "preserve_volume_on": [], "now": "linear blend"}
    arm = S.final_rig()
    mods = [m for m in body.modifiers if m.type == "ARMATURE"]
    assert mods and not any(m.use_deform_preserve_volume for m in mods)
    cp = rep["chain_parents"]
    assert cp["ear_l"]["ok"] and cp["ear_l"]["body_bone"] == "head.x"
    assert all(k in body.data.attributes for k in ("forge_app_tail", "forge_app_ear_l", "forge_app_ear_r"))
    text = "\n".join(t for _i, t in L._rig_rows(rep))
    if arp_differs:
        assert cp["tail"]["ok"] is False and cp["tail"]["parent"] == "root.x"
        assert "tail hangs from root," in text and "not spine 01" in text, text
        assert not rep["appendages"]["tail"]["root_ok"]                  # and the root warns
        assert "can tear" in text
    else:
        assert cp["tail"] == {"bone": "c_tail_00.x", "parent": "spine_01.x", "body_bone": "spine_01.x",
                              "wanted": "spine_01.x", "ok": True, "master_parent": "spine_01.x"}
        assert arm.data.bones["c_tail_00.x"].parent.name == "spine_01.x"
        for app in ("tail", "ear_l", "ear_r"):
            a = rep["appendages"][app]
            assert a["root_ok"] and a["moved_points"] > 0, (app, a)
        assert "tail hangs from spine 01" in text and "left ear hangs from head" in text, text
    assert max(len(t) for _i, t in L._rig_rows(rep)) <= 60
    # the weights obey the 8-bone limit and nothing is left unweighted
    assert all(w["weighted"] for w in rep["weights"].values())
