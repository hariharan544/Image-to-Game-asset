"""Step 5 with UVgami cutting the seams: settings for a bakeable map, UVs onto Forge's own
meshes, a part UVgami cannot do falls back to Blender, no engine = Blender for everything."""

import sys
from pathlib import Path

import pytest

bpy = pytest.importorskip("bpy")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "blender_scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))


@pytest.fixture()
def uvg(monkeypatch):
    import fake_uvgami

    from forge_bpy import addon_trial
    bpy.ops.wm.read_homefile(use_empty=True)
    m = fake_uvgami.install()
    monkeypatch.setattr(addon_trial, "view3d_override", lambda: {"scene": bpy.context.scene})
    yield m
    fake_uvgami.uninstall()


def _low(name, kind, loc):
    import bmesh
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=3, radius=0.5)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    o.location = loc
    bpy.context.scene.collection.objects.link(o)
    o["forge_role"], o["forge_part"], o["forge_kind"] = "low", name, kind
    return o


def _drive(gen, on_wait):
    """Run the step's generator; on its first wait the engine does its work."""
    called = False
    try:
        while True:
            next(gen)
            if not called:
                called = True
                on_wait()
    except StopIteration as stop:
        return stop.value


def test_uvgami_cuts_the_seams_then_the_packer_packs(uvg):
    import fake_uvgami

    from forge_bpy import uv
    _low("Body", "body", (0, 0, 0))
    _low("Bell", "prop", (2, 0, 0))
    props = bpy.context.scene.uvgami
    rep = _drive(uv.run({"unwrapper": "uvgami", "packer": "blender", "texture_size": 1024}),
                 lambda: fake_uvgami.deliver())
    assert {r["seams"] for r in rep["parts"].values()} == {"uvgami"}, rep
    s = uvg.seen_settings
    assert s["transfer_uvs"] and not s["pack_after_unwrap"] and not s["symmetry"] and not s["stack_similar"]
    assert props.symmetry and props.pack_after_unwrap and not props.transfer_uvs   # the director's settings back
    for r in rep["parts"].values():
        assert r["has_uv"] and r["overlap_pct"] < 0.5


def test_a_part_uvgami_cannot_do_falls_back_to_blender(uvg):
    import fake_uvgami

    from forge_bpy import uv
    _low("Body", "body", (0, 0, 0))
    _low("Bell", "prop", (2, 0, 0))
    rep = _drive(uv.run({"unwrapper": "uvgami", "packer": "blender", "texture_size": 1024}),
                 lambda: fake_uvgami.deliver(fail=("Bell",)))
    assert rep["parts"]["Body"]["seams"] == "uvgami"
    assert rep["parts"]["Bell"]["seams"] == "blender" and rep["parts"]["Bell"]["seams_note"]
    assert rep["parts"]["Bell"]["has_uv"]


def test_no_engine_means_blender_for_everything(uvg):
    from forge_bpy import uv
    bpy.context.scene.uvgami.engine = "NONE"
    _low("Body", "body", (0, 0, 0))
    assert "Download Engine" in uv.uvgami_status()
    rep = uv.run({"unwrapper": "uvgami", "packer": "blender", "texture_size": 1024})
    assert not hasattr(rep, "__next__")
    assert rep["parts"]["Body"]["seams"] == "blender" and rep["parts"]["Body"]["has_uv"]


def test_the_face_is_kept_free_of_seams():
    """The front of the head is weighted in UVgami's seam-restriction group: seams go round
    the back of the head and under the chin."""
    import numpy as np

    import bodies
    from forge_bpy import joints, uv
    ob = bodies.bull()
    ob["forge_kind"] = "body"
    n = uv.face_seam_guard(ob)
    assert n > 50
    g = ob.vertex_groups[uv.UVGAMI_WEIGHTS]
    co = bodies.coords(ob.data)
    w = np.zeros(len(co), bool)
    for v in ob.data.vertices:
        if any(x.group == g.index for x in v.groups):
            w[v.index] = True
    J = joints.estimate(ob)
    head = np.array(J["head"][0][:])
    assert (co[w, 2] > J["neck"][0][2]).all()                  # on the head
    assert (co[w, 1] < head[1]).mean() > 0.95                  # its front (the bull faces -Y)


def test_a_failed_transfer_is_explained_and_leaves_nothing_behind(uvg):
    """UVgami cannot put its UVs back (faces on the same spot): it hides Forge's mesh and keeps
    its own copy. Forge shows its mesh again, removes the copy and says why in plain words."""
    import fake_uvgami

    from forge_bpy import uv
    body = _low("Body", "body", (0, 0, 0))
    rep = _drive(uv.run({"unwrapper": "uvgami", "packer": "blender", "texture_size": 1024}),
                 lambda: fake_uvgami.deliver(transfer_fail={"Body": "output face 12 matches multiple input faces"}))
    r = rep["parts"]["Body"]
    assert r["seams"] == "blender" and r["has_uv"] and "same spot" in r["seams_note"], r
    assert not body.hide_get()
    assert not [o for o in bpy.data.objects if o.name.endswith("_unwrapped")]
    assert "UVgami Unwrapped" not in bpy.data.collections


def test_faces_on_the_same_spot_are_fixed_before_uvgami_sees_the_mesh(uvg):
    import bmesh
    import fake_uvgami

    from forge_bpy import rescue, uv
    body = _low("Body", "body", (0, 0, 0))
    bm = bmesh.new()
    bm.from_mesh(body.data)
    bm.faces.ensure_lookup_table()
    f = bm.faces[5]
    bm.faces.new([bm.verts.new(v.co) for v in f.verts])     # a face on top of a face
    bm.to_mesh(body.data)
    bm.free()
    rep = _drive(uv.run({"unwrapper": "uvgami", "packer": "blender", "texture_size": 1024}),
                 lambda: fake_uvgami.deliver())
    seen = uvg.seen_meshes["Body"]
    assert not rescue.doubled_points(seen).any() and not rescue.stacked_faces(seen).any()
    assert rep["parts"]["Body"]["seams"] == "uvgami" and rep["parts"]["Body"]["cleaned"], rep


def test_uvgami_grid_never_replaces_the_parts_materials(uvg):
    import fake_uvgami

    from forge_bpy import uv
    body = _low("Body", "body", (0, 0, 0))
    skin = bpy.data.materials.new("Skin")
    body.data.materials.append(skin)
    bpy.context.scene.uvgami.auto_grid = True                 # the director's own setting
    _drive(uv.run({"unwrapper": "uvgami", "packer": "blender", "texture_size": 1024}),
           lambda: fake_uvgami.deliver(grid=True))
    assert not uvg.seen_settings["auto_grid"]                 # off while Forge unwraps
    assert bpy.context.scene.uvgami.auto_grid                 # and back afterwards
    assert [m.name for m in body.data.materials] == ["Skin"]
    assert {p.material_index for p in body.data.polygons} == {0}
