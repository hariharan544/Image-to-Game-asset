"""Steps 4-9 of the in-Blender workflow, clicked through on a test character.

Quad Remesher / UVPackmaster / Auto-Rig Pro are not installed here: the steps must fall
back (Blender remesher / packer) or stop with a clear message (rig), never crash.
"""

import importlib
import json
import sys
from pathlib import Path

import pytest

bpy = pytest.importorskip("bpy")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "blender_addon"))
sys.path.insert(0, str(ROOT / "blender_scripts"))


def test_steps_4_to_9(tmp_path):
    from forge_bpy import fixture

    F = importlib.import_module("forge_send")
    F.register()
    try:
        fixture.humanoid({"out": str(tmp_path / "h.glb")})      # body + sword + skeleton
        for o in list(bpy.data.objects):
            if o.type == "ARMATURE":
                bpy.data.objects.remove(o)
        body, sword = bpy.data.objects["Body"], bpy.data.objects["Sword"]
        for o in (body, sword):
            o.parent = None
            o.vertex_groups.clear()
            for m in list(o.modifiers):
                o.modifiers.remove(m)
        bpy.context.view_layer.update()
        for o in bpy.context.view_layer.objects:
            o.select_set(o.name in ("Body", "Sword"))
        bpy.ops.wm.save_as_mainfile(filepath=str(tmp_path / "hero.blend"))
        st = bpy.context.scene.forge_stage
        st.height_m = 1.8
        assert bpy.ops.forge.stage_collect() == {"FINISHED"}
        assert bpy.ops.forge.stage_approve_layout() == {"FINISHED"}
        assert bpy.ops.forge.stage_repair() == {"FINISHED"}
        assert bpy.ops.forge.stage_approve_repair() == {"FINISHED"}

        # 4 retopology (no Quad Remesher here -> Blender's remesher, reported as a fallback)
        st.budget = 4000
        assert bpy.ops.forge.step(action="retopo_map") == {"FINISHED"}, st.error
        assert "QR_Density" in bpy.data.objects["Body"].data.color_attributes
        assert bpy.data.objects["Body"].data.color_attributes.active_color_name == "QR_Density"
        assert bpy.ops.forge.step(action="retopo_map") == {"FINISHED"}            # hide again
        assert not bpy.data.objects["Body"].hide_get()          # no new mesh yet: the bull stays visible
        assert bpy.ops.forge.step(action="retopo_run") == {"FINISHED"}, st.error
        assert st.retopo == "review", st.error
        rep = json.loads(st.retopo_rep)
        assert set(rep["parts"]) == {"Body", "Sword"} and rep["total_tris"] <= 4000 * 1.1
        lows = [o for o in bpy.data.objects if o.get("forge_role") == "low"]
        assert len(lows) == 2 and all(o.name.endswith("_low") for o in lows)
        assert bpy.data.objects["Body_low"]["forge_symmetry_x"] and not bpy.data.objects["Sword_low"]["forge_symmetry_x"]
        assert bpy.data.objects["Body"].hide_get()                   # original kept, hidden
        bpy.ops.forge.step(action="retopo_compare")
        assert not bpy.data.objects["Body"].hide_get() and bpy.data.objects["Body"].location.x > 0
        # the original moves aside as one group (props stay on it)
        assert bpy.data.objects["Body"].location.x == bpy.data.objects["Sword"].location.x
        # running again while compared: symmetry must come from the real (centred) position
        assert bpy.ops.forge.step(action="retopo_run") == {"FINISHED"}, st.error
        assert bpy.data.objects["Body_low"]["forge_symmetry_x"]
        assert bpy.data.objects["Body"].location.x == 0
        bpy.ops.forge.step(action="retopo_compare")
        assert bpy.ops.forge.step(action="retopo_approve") == {"FINISHED"}
        assert bpy.data.objects["Body"].location.x == 0 and st.retopo == "approved"

        # 5 UVs
        lows = [o for o in bpy.data.objects if o.get("forge_role") == "low"]    # rebuilt by the 2nd run
        st.tex_size = "1024"
        assert bpy.ops.forge.step(action="uv_run") == {"FINISHED"} and st.uv == "review", st.error
        uv = json.loads(st.uv_rep)["parts"]
        assert all(r["has_uv"] and r["overlap_pct"] < 1.0 for r in uv.values()), uv
        bpy.ops.forge.step(action="uv_checker")
        assert all(o.data.materials[0].name == "FORGE_UV_CHECKER" for o in lows)
        assert bpy.ops.forge.step(action="uv_approve") == {"FINISHED"}
        assert all(o.data.materials[0].name != "FORGE_UV_CHECKER" for o in lows)

        # 6 bake (CPU here)
        assert bpy.ops.forge.step(action="bake_run") == {"FINISHED"} and st.bake == "review", st.error
        assert bpy.data.objects["Body"].hide_get() and bpy.data.objects["Sword"].hide_get()  # originals hidden
        bake = json.loads(st.bake_rep)["parts"]
        assert set(bake["Body"]["maps"]) == {"basecolor", "normal", "roughness", "metallic", "ao"}
        assert all(Path(p).exists() for p in bake["Body"]["maps"].values())
        assert bake["Body"]["bake_miss_ratio"] < 0.1
        mat = bpy.data.objects["Body_low"].data.materials[0]
        imgs = {n.image.name for n in mat.node_tree.nodes if n.type == "TEX_IMAGE"}
        assert {"T_Body_basecolor", "T_Body_normal"} <= imgs
        assert bpy.ops.forge.step(action="bake_approve") == {"FINISHED"}

        # 7 colour: Tripo round trip with the exported part (same shape) re-imported
        assert bpy.ops.forge.step(action="colour_tripo") == {"FINISHED"}
        glb = tmp_path / "hero_forge" / "retexture" / "Sword.glb"
        assert glb.exists()
        bpy.context.view_layer.objects.active = bpy.data.objects["Sword_low"]
        assert bpy.ops.forge.import_retexture(filepath=str(glb)) == {"FINISHED"}, st.error
        m = bpy.data.objects["Sword_low"].data.materials
        assert len(m) == 1 and {"T_Sword_basecolor", "T_Sword_normal"} <= {
            n.image.name for n in m[0].node_tree.nodes if n.type == "TEX_IMAGE"}
        assert len([o for o in bpy.data.objects if o.type == "MESH"]) == 4   # import cleaned up
        assert bpy.ops.forge.step(action="colour_approve") == {"FINISHED"}

        # 8 rig: Auto-Rig Pro missing -> clear message, nothing broken
        try:
            bpy.ops.forge.step(action="rig_place")
        except RuntimeError:
            pass
        assert "Auto-Rig Pro" in st.error and st.rig == "todo"

        # 9 export without a rig (static meshes) - Unreal + Unity
        S = importlib.import_module("forge_send.steps")
        bake_rep = json.loads(st.bake_rep)
        un = S.export_engine("unreal", bake_rep)
        ui = S.export_engine("unity", bake_rep, unity_budget=1500)
        assert Path(un["meshes"]["body"]).exists() and Path(ui["meshes"]["body"]).exists()
        assert any(p.endswith("_ORM.png") for p in un["textures"]["Body"].values())
        assert Path(un["preview"]).exists()
        names = sorted(o.name for o in bpy.data.objects if o.type == "MESH")
        assert names == ["Body", "Body_low", "Sword", "Sword_low"], names     # temp copies gone
    finally:
        F.unregister()


def test_joint_guess_on_t_pose():
    from forge_bpy import fixture, joints
    from mathutils import Vector

    fixture.humanoid({"out": "/tmp/_forge_h.glb"})
    J = joints.estimate(bpy.data.objects["Body"])
    ref = {n: Vector(h) for n, p, h, t in fixture.UE_SKELETON}
    pairs = {"pelvis": "pelvis", "neck": "neck_01", "head": "head"}
    for s in "lr":
        for k in ("clavicle", "upperarm", "lowerarm", "hand", "thigh", "calf", "foot", "ball"):
            pairs[f"{k}_{s}"] = f"{k}_{s}"
    worst = max((J[k][0] - ref[v]).length for k, v in pairs.items())
    assert worst < 0.08 * 1.8, worst                       # within 8% of the body height
    assert J["hand_l"][0].x > 0 and J["hand_r"][0].x < 0 and J["_front"] == -1.0
    from forge_bpy.arp_rig import missing_joints, ref_targets
    assert not missing_joints(J)
    t = ref_targets(J, 0.0, 1.8)
    assert {"thumb1_ref.l", "index1_base_ref.l", "foot_heel_ref.r", "head_ref.x"} <= set(t)


def test_job_lock_lives_in_memory_and_stale_results_are_discarded():
    F = importlib.import_module("forge_send")
    F.register()
    try:
        L = importlib.import_module("forge_send.stages_late")
        st = bpy.context.scene.forge_stage
        st.repair = "approved"
        hits = []

        def slow():
            yield 0.01
            st.repair = "review"                      # the director re-opened step 3 meanwhile
            yield 0.01
            return {"ok": 1}
        L.run(st, "test job", slow, lambda st, r: hits.append(r))
        assert hits == [] and "discarded" in st.error and not L.job_running()
        L.run(st, "test job", lambda: {"ok": 2}, lambda st, r: hits.append(r))
        assert hits == [{"ok": 2}] and st.error == ""
        # a busy flag saved by add-on 1.2.0 is cleared when a file loads
        st.busy = "retopology"
        L._JOB["on_done"] = lambda *a: None
        L._on_load()
        assert st.busy == "" and not L.job_running()
        # while a job runs, step 2/3 buttons are disabled
        L._JOB["on_done"] = lambda *a: None
        assert not bpy.types.FORGE_OT_stage_reopen.poll(bpy.context)
        L._JOB.clear()
        assert bpy.types.FORGE_OT_stage_reopen.poll(bpy.context)
        # a long job: the panel shows it, Stop ends it and unlocks everything
        from unittest import mock

        def endless():
            while True:
                yield 1.0
        L._JOB.update({"gen": endless(), "on_done": lambda *a: None, "label": "retopology", "started": 0})
        L.S._mod("retopo").STATUS["text"] = "Body_low: rebuilding thin part 1"
        F.stages_ui.FORGE_PT_stages.draw(mock.MagicMock(), bpy.context)
        leftover = bpy.data.objects.new("Body_low_rescue0", bpy.data.meshes.new("r"))
        bpy.context.scene.collection.objects.link(leftover)
        assert bpy.ops.forge.stop_job() == {"FINISHED"}
        assert not L.job_running() and "Stopped" in st.error
        assert "Body_low_rescue0" not in bpy.data.objects and L.S._mod("retopo").STATUS["text"] == ""
        assert bpy.types.FORGE_OT_stage_reopen.poll(bpy.context)
    finally:
        F.unregister()


def test_detail_map_for_quad_remesher():
    import bmesh
    import numpy as np
    from forge_bpy import density as D

    # colour code = Quad Remesher's own density brush
    c = D.qr_colours(np.array([1.0, 4.0, 0.25, 2.0, 0.5]))
    assert np.allclose(c[0, :3], 1) and np.allclose(c[1, :3], (1, 0, 0)) and np.allclose(c[2, :3], (0, 1, 1))
    assert np.allclose(c[3, :3], (1, 2 / 3, 2 / 3)) and np.allclose(c[4, :3], (2 / 3, 1, 1))
    assert D.qr_density(np.array([0.0, 0.5, 1.0]), 0.0).tolist() == [1.0, 1.0, 1.0]   # strength 0: even

    # a box: corners and edges are detail, the middle of the faces is flat
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=2.0)
    bmesh.ops.subdivide_edges(bm, edges=bm.edges[:], cuts=40, use_grid_fill=True)
    me = bpy.data.meshes.new("box")
    bm.to_mesh(me)
    keep = me.color_attributes.new("Col", "BYTE_COLOR", "CORNER")       # the model's own colours
    me.color_attributes.active_color = keep
    s = D.detail_score(me)
    D.write_qr_density(me, s, 0.8, make_active=False)
    assert me.color_attributes.active_color_name == "Col"                 # model colours untouched
    co = np.array([v.co[:] for v in me.vertices])
    lv = np.array([l.vertex_index for l in me.loops])
    col = np.array([d.color_srgb[:] for d in me.color_attributes["QR_Density"].data])
    edge = ((np.abs(co) > 0.97).sum(1) >= 2)[lv]
    flat = ((np.abs(co) < 0.5).sum(1) >= 2)[lv]
    assert col[edge, 1].mean() < 0.85 and col[edge, 0].mean() > 0.95     # reddish: more quads
    assert col[flat, 0].mean() < 0.85 and col[flat, 2].mean() > 0.95     # cyan-ish: fewer quads
    # before remeshing it must be the only colour layer
    assert D.only_qr_density(me) and [a.name for a in me.color_attributes] == ["QR_Density"]


def test_palette_has_the_texture_colours_not_darker_ones():
    import numpy as np
    sys.path.insert(0, str(ROOT / "blender_addon"))
    S = importlib.import_module("forge_send.steps")
    px = np.zeros((64, 64, 4), np.float32)
    px[..., :3] = (0.70, 0.40, 0.25)            # fur
    px[:20, :, :3] = (0.85, 0.65, 0.50)         # belly
    px[50:, 50:, :3] = (0.35, 0.18, 0.10)       # a dark spot
    cols = S.palette_colours(px, k=6)
    assert np.allclose(cols[0], (0.70, 0.40, 0.25), atol=0.02)      # most used first
    for want in ((0.85, 0.65, 0.50), (0.35, 0.18, 0.10)):
        assert any(np.allclose(c, want, atol=0.03) for c in cols), cols
    img = bpy.data.images.new("T_x_basecolor", 64, 64)
    img.pixels.foreach_set(px.ravel())
    pal = S.texture_palette(img)
    assert pal.name == "Forge colours" and 3 <= len(pal.colors) <= 12


def test_mirror_image_uv_islands_are_turned_round():
    """A mirrored half unwraps as a mirror-image island: checker text reads backwards and the
    normal-map tangents flip. Every island ends up the right way round, in the same box."""
    import bmesh
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "blender_scripts"))
    from forge_bpy import uv as U
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=4, y_segments=4, size=1.0)
    me = bpy.data.meshes.new("flipuv")
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new("flipuv", me)
    bpy.context.scene.collection.objects.link(o)
    layer = me.uv_layers.new(name="UVMap")
    for l in me.loops:                              # mirror-image UVs: u = 1 - x
        x, y, _z = me.vertices[l.vertex_index].co
        layer.data[l.index].uv = (0.5 - x * 0.25, 0.5 + y * 0.25)
    before = [tuple(d.uv) for d in layer.data]
    assert U.unflip_islands(o) == 1
    after = [tuple(d.uv) for d in me.uv_layers.active.data]
    assert min(u for u, _v in after) == pytest.approx(min(u for u, _v in before))
    assert max(u for u, _v in after) == pytest.approx(max(u for u, _v in before))
    assert U.unflip_islands(o) == 0                 # now the right way round


def test_redo_only_the_selected_parts_keeps_the_others():
    """'Run for selected parts only': the prop is remeshed again, the body's new mesh is not
    touched, and the prop gets the same budget share as in a full run."""
    import bmesh
    S = importlib.import_module("forge_send.steps")
    G = importlib.import_module("forge_send.geometry")
    bpy.ops.wm.read_homefile(use_empty=True)
    col = bpy.data.collections.new("Forge Parts")
    bpy.context.scene.collection.children.link(col)

    def part(name, kind, r, loc):
        bm = bmesh.new()
        bmesh.ops.create_icosphere(bm, subdivisions=5, radius=r)
        me = bpy.data.meshes.new(name)
        bm.to_mesh(me)
        bm.free()
        o = bpy.data.objects.new(name, me)
        o.location = loc
        col.objects.link(o)
        o[G.ROLE] = kind
        return o
    part("Body", "body", 1.0, (0, 0, 1))
    part("Bell", "prop", 0.3, (2, 0, 1))
    bpy.context.view_layer.update()
    rep = S.run_retopo(4000, use_qr=False, detail=0.0)
    full = {k: v["budget"] for k, v in rep["parts"].items()}
    body_low = next(o for o in S.lows() if o.get("forge_part") == "Body")
    body_mesh, body_faces = body_low.data.name, len(body_low.data.polygons)
    rep2 = S.run_retopo(4000, use_qr=False, detail=0.0, only=["Bell"])
    assert set(rep2["parts"]) == {"Bell"}
    assert rep2["parts"]["Bell"]["budget"] == full["Bell"]           # same share as a full run
    body_low = next(o for o in S.lows() if o.get("forge_part") == "Body")
    assert body_low.data.name == body_mesh and len(body_low.data.polygons) == body_faces
    assert len(S.lows()) == 2 and not S.missing_lows()
    assert S.part_names([body_low]) == ["Body"]
