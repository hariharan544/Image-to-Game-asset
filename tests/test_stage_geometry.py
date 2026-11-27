"""Stage 2 (Assemble) + Stage 3 (Geometry repair) on deliberately broken meshes."""

import sys
from pathlib import Path

import pytest

bpy = pytest.importorskip("bpy")
import bmesh  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "blender_addon"))
from forge_send import geometry as G  # noqa: E402


def _obj(name, bm):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(o)
    return o


def broken_body(name="Body"):
    """A sphere torn along a crack (duplicate seam vertices), with two holes, floating specks
    and loose points - the kind of damage AI segmentation leaves."""
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=48, v_segments=24, radius=1.0)
    # crack: split the mesh along a ring of edges -> duplicate vertices on the seam
    ring = [e for e in bm.edges if all(abs(v.co.z) < 1e-6 for v in e.verts)]
    bmesh.ops.split_edges(bm, edges=ring)
    # two holes (picked by position: Blender's face order is not stable between runs)
    from mathutils import Vector
    holes = [f for f in bm.faces
             if (f.calc_center_median() - Vector((0, -0.85, 0.5))).length < 0.12
             or (f.calc_center_median() - Vector((0.85, 0, -0.5))).length < 0.12]
    assert len(holes) >= 2
    bmesh.ops.delete(bm, geom=holes, context="FACES")
    # specks + loose points
    for i in range(3):
        bmesh.ops.create_cube(bm, size=0.004, matrix=__import__("mathutils").Matrix.Translation((2 + i * 0.1, 0, 0)))
    for i in range(4):
        bm.verts.new((0, 3 + i, 0))
    o = _obj(name, bm)
    o.location = (5, 2, 1)
    o.scale = (2, 2, 2)
    return o


def test_analyse_finds_damage_and_repair_fixes_it():
    o = broken_body()
    G.apply_transform(o)
    rep = G.analyse(o)
    assert rep["holes"] >= 2 and rep["tiny_bits"] == 3 and rep["loose"] == 4 and not rep["ok"]
    res = G.repair(o)
    assert res["welded_points"] > 0 and res["removed_bits"] == 3 and res["holes_closed"] >= 2
    after = G.analyse(o)
    assert after["ok"], after
    assert after["pieces"] == 1 and after["open_edges"] == 0
    # undo brings the damaged original back
    assert G.restore(o)
    assert G.analyse(o)["holes"] >= 2
    G.drop_backup(o)
    assert not any(m.name.startswith("FORGE_BACKUP_Body") for m in bpy.data.meshes)


def test_make_solid_welds_overlapping_pieces():
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=32, v_segments=16, radius=1.0)
    from mathutils import Matrix
    bmesh.ops.create_cone(bm, cap_ends=True, segments=16, radius1=0.3, radius2=0.0, depth=1.0,
                          matrix=Matrix.Translation((0.6, 0, 1.0)))      # a horn pushed into the head
    o = _obj("BullBody", bm)
    o["forge_kind"] = "body"
    rep = G.analyse(o)
    assert rep["big_pieces"] == 2 and rep["needs_weld"]
    G.make_solid(o, resolution=64)
    after = G.analyse(o)
    assert after["pieces"] == 1 and after["ok"] and not after["needs_weld"], after


def test_collect_sizes_and_lays_out_parts_then_mirror():
    # an empty scene first: Collect picks the body among every part in the scene, and a body
    # an earlier test left there (the suite run in another order) would be taken instead
    bpy.ops.wm.read_homefile(use_empty=True)
    body = broken_body("BullBody2")
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bell = _obj("bell", bm)               # generated at "unit" size, as Tripo does
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=24, radius1=0.5, radius2=0.5, depth=0.3)
    band = _obj("wrist band", bm)
    info = G.collect([body, bell, band], target_height=1.8)
    assert body.get("forge_kind") == "body" and bell.get("forge_kind") == "prop"
    assert info["body"] == "BullBody2" and set(info["new"]) == {"bell", "wrist band"}
    lo, hi = G.world_bounds(body)
    assert abs((hi.z - lo.z) - 1.8) < 1e-3 and abs(lo.z) < 1e-4 and abs(lo.x + hi.x) < 1e-3
    blo, bhi = G.world_bounds(bell)
    assert abs(max(bhi - blo) - 0.12 * 1.8) < 1e-3          # bell sized from its name
    assert blo.x > hi.x                                      # laid out beside the body
    # the director drags the band onto the right wrist, then mirrors it
    G.move_to(band, __import__("mathutils").Vector((0.7, 0, 1.0)))
    dup = G.mirror(band)
    assert band.name == "wrist band_L" and dup.name == "wrist band_R"
    a, b = G.world_bounds(band), G.world_bounds(dup)
    assert abs(a[0].x + b[1].x) < 1e-4 and abs(a[1].x + b[0].x) < 1e-4
    # mirrored copy still points outward
    G.repair(dup)
    assert G.analyse(dup)["ok"]
    # each side keeps its own "before repair" copy, mirrored to its side
    G.repair(band)
    dup2 = G.mirror(band)
    b1, b2 = bpy.data.meshes[band[G.BACKUP]], bpy.data.meshes[dup2[G.BACKUP]]
    assert b1 != b2
    x1 = sum(v.co.x for v in b1.vertices) / len(b1.vertices)
    x2 = sum(v.co.x for v in b2.vertices) / len(b2.vertices)
    assert abs(x1 + x2) < 1e-4 and x1 > 0
    # moving a repaired part moves its backup too (colour bake source of welded parts)
    band.location.z += 0.5
    G.apply_transform(band)
    assert abs(max(v.co.z for v in bpy.data.meshes[band[G.BACKUP]].vertices)
               - max(v.co.z for v in band.data.vertices)) < 0.05
    # running Collect again keeps the director's placement
    before = G.world_bounds(band)
    G.collect([band], target_height=0)
    assert (G.world_bounds(band)[0] - before[0]).length < 1e-6


def test_panel_buttons_in_order():
    """The director's clicks: Collect -> Approve layout -> Run repair -> Weld -> Approve geometry."""
    import importlib
    import re
    from unittest import mock

    F = importlib.import_module("forge_send")
    F.register()
    try:
        bpy.ops.wm.read_homefile(use_empty=True)
        body = broken_body("TripoBody")
        bm = bmesh.new()
        bmesh.ops.create_cube(bm, size=1.0)
        bell = _obj("Bell", bm)
        bpy.context.view_layer.update()
        for o in bpy.context.view_layer.objects:
            o.select_set(o.name in ("TripoBody", "Bell"))
        st = bpy.context.scene.forge_stage
        st.height_m = 2.0
        assert bpy.ops.forge.stage_collect() == {"FINISHED"} and st.assemble == "review"
        bpy.context.view_layer.objects.active = bell
        assert bpy.ops.forge.stage_mirror() == {"FINISHED"}
        assert bpy.ops.forge.stage_approve_layout() == {"FINISHED"} and st.assemble == "approved"
        assert bpy.ops.forge.stage_repair() == {"FINISHED"} and st.repair == "review"
        import json
        rep = json.loads(st.report)
        assert set(rep) == {"TripoBody", "Bell_L", "Bell_R"} and all(r["ok"] for r in rep.values()), rep
        assert bpy.ops.forge.stage_show_problems(name="TripoBody") == {"FINISHED"}
        bpy.ops.object.mode_set(mode="OBJECT")
        assert bpy.ops.forge.stage_weld(name="TripoBody") == {"FINISHED"}
        assert json.loads(st.fixed)["TripoBody"]["welded_solid"]
        assert bpy.ops.forge.stage_approve_repair() == {"FINISHED"} and st.repair == "approved"
        assert bpy.ops.forge.stage_reopen(stage="repair") == {"FINISHED"}
        assert bpy.ops.forge.stage_undo_repair() == {"FINISHED"} and st.repair == "todo"
        assert G.analyse(bpy.data.objects["TripoBody"])["holes"] >= 2     # original is back

        # draw the panel in every state with a recording layout; every icon must exist in Blender
        valid = {i.identifier for i in bpy.types.UILayout.bl_rna.functions["label"].parameters["icon"].enum_items}
        src = "".join(p.read_text() for p in Path(F.__file__).parent.glob("*.py"))
        icons = set(re.findall(r'icon="([A-Z0-9_]+)"', src)) | set(re.findall(r'"(COLORSET_\d+_VEC)"', src))
        assert icons <= valid, icons - valid
        for a, r in (("todo", "todo"), ("review", "todo"), ("approved", "review"), ("approved", "approved")):
            st.assemble, st.repair = a, r
            fake = mock.MagicMock()
            F.stages_ui.FORGE_PT_stages.draw(fake, bpy.context)
        for stage in ("retopo", "uv", "bake", "colour", "rig", "export"):
            for status in ("todo", "review", "approved"):
                st.repair = "approved"
                setattr(st, stage, status)
                for phase in ("", "joints", "built"):
                    st.rig_phase = phase
                    F.stages_ui.FORGE_PT_stages.draw(mock.MagicMock(), bpy.context)

        # a part collected by add-on 1.1 (kind stored in forge_role): drawing must not write
        # to it - Blender forbids ID writes while drawing and the whole panel goes blank
        legacy = bpy.data.objects["TripoBody"]
        legacy["forge_role"] = "body"
        if "forge_kind" in legacy:
            del legacy["forge_kind"]
        F.stages_ui.FORGE_PT_stages.draw(mock.MagicMock(), bpy.context)
        assert "forge_kind" not in legacy and legacy["forge_role"] == "body"
        assert G.kind(legacy) == "body" and G.body_of(G.mesh_parts(bpy.context.scene)) == legacy
    finally:
        F.unregister()


def test_concept_image_stands_clear_of_all_parts():
    """The concept card is as tall as the body and never overlaps an arm or a prop."""
    from forge_send import stages_ui
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    body = _obj("ConceptBody", bm)
    body.scale = (3.0, 0.6, 1.8)                   # T-pose: wider than tall
    body.location = (0.4, 0, 0.9)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=0.3)
    prop = _obj("ConceptProp", bm)
    prop.location = (-3.0, 0, 0.5)                 # a prop parked far left
    body["forge_kind"], prop["forge_kind"] = "body", "prop"
    img = bpy.data.images.new("concept", 1024, 2048)       # portrait sheet
    ref = bpy.data.objects.new("Forge concept test", None)
    ref.empty_display_type = "IMAGE"
    ref.data = img
    bpy.context.view_layer.update()
    stages_ui.place_concept(ref, img, [body, prop])
    width = ref.empty_display_size * 1024 / 2048
    height = ref.empty_display_size
    assert abs(height - 1.8) < 1e-4
    assert ref.location.x + width / 2 < G.world_bounds(prop)[0].x - 0.1      # clear of everything
    assert abs(ref.location.z - 0.9) < 1e-4


def test_save_survives_a_blocked_backup(tmp_path):
    """Blender cannot write the .blend1 backup (OneDrive holds it): the approval still saves."""
    from forge_send import stages_ui
    f = tmp_path / "bull.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(f))
    bpy.ops.wm.save_mainfile()                      # a .blend exists, the next save backs it up
    blocker = tmp_path / "bull.blend1"
    if blocker.exists():
        blocker.unlink()
    blocker.mkdir()
    (blocker / "keep").write_text("x")              # a folder where the backup should go
    msgs = []

    class Op:
        def report(self, kind, text):
            msgs.append(text)
    before = f.stat().st_mtime_ns
    import time
    time.sleep(0.05)
    stages_ui._save(Op())
    assert f.stat().st_mtime_ns > before, msgs
    assert bpy.context.preferences.filepaths.save_version >= 1
