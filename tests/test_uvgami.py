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
    import fake_uvgami

    from forge_bpy import uv
    fake_uvgami.set_installed(())                           # nothing downloaded: its enum reads NONE
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


def test_an_engine_that_stops_is_explained(uvg):
    """PartUV's AI split without a working NVIDIA card stops with its own message: the report
    passes it on instead of 'no result'."""
    from forge_bpy import uv
    _low("Body", "body", (0, 0, 0))

    def stops():
        uvg.error_messages = ["PartUV could not start (no CUDA device)"]
        uvg.is_active = False
    rep = _drive(uv.run(ARGS), stops)
    r = rep["parts"]["Body"]
    assert r["seams"] == "blender" and r["seams_note"] == "UVgami: its engine stopped: PartUV could not " \
        "start (no CUDA device)", r


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


# ----------------------------------------------------------------------------- engines

ARGS = {"unwrapper": "uvgami", "packer": "blender", "texture_size": 1024}


def _drive_all(gen):
    """Run a generator to the end; whenever UVgami is busy, the (fake) engine finishes."""
    import fake_uvgami
    if not hasattr(gen, "__next__"):
        return gen
    try:
        while True:
            next(gen)
            if fake_uvgami.manager().is_active:
                fake_uvgami.deliver()
    except StopIteration as stop:
        return stop.value


def _uvs(o):
    import numpy as np
    a = np.zeros(len(o.data.loops) * 2, np.float32)
    if o.data.uv_layers.active is not None:
        o.data.uv_layers.active.data.foreach_get("uv", a)
    return a


def _meshes():
    import fake_uvgami
    return len([m for m in bpy.data.meshes if not m.name.startswith(fake_uvgami.SEEN_PREFIX)])


def _late():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "blender_addon"))
    from forge_send import stages_late
    return stages_late


def test_the_chosen_engine_is_set_for_the_run_and_the_directors_settings_come_back(uvg):
    """UVgami's panel unwraps with whatever the director left there: Forge sets the engine and
    its own settings for every run, says what it really used, and puts the panel back."""
    import fake_uvgami

    from forge_bpy import uv
    fake_uvgami.set_installed(("OPTCUTS", "PARTUV"))
    _low("Body", "body", (0, 0, 0))
    p = bpy.context.scene.uvgami
    p.engine = "OPTCUTS"                                  # the director's own choices
    p.partuv.segmentation = "GEOMETRIC"
    p.optcuts.mode = "HARD"
    p.split_regions, p.import_uvs, p.keep_quads = False, True, False
    p.priority, p.proxy_mode, p.weight_value = "FEWER_SEAMS", "ON", 5    # shape every engine's cut
    raw, raw_split = p.get("engine"), p.partuv.get("segmentation")
    rep = _drive_all(uv.run({**ARGS, "uvgami_engine": "PARTUV"}))
    s = uvg.seen_settings
    assert s["engine"] == "PARTUV" and s["segmentation"] == "TREE"        # Auto split, no AI: tree
    assert s["split_regions"] and s["keep_quads"] and not s["import_uvs"]
    assert not s["symmetry"] and not s["stack_similar"] and not s["auto_grid"] and s["transfer_uvs"]
    assert (s["priority"], s["proxy_mode"], s["weight_value"]) == (uv.UVGAMI_PRIORITY, "AUTO", 3) == \
        ("BALANCED", uv.UVGAMI_PROXY, uv.UVGAMI_WEIGHT)
    assert p.engine == "OPTCUTS" and p.get("engine") == raw                  # all back as they were
    assert p.partuv.segmentation == "GEOMETRIC" and p.partuv.get("segmentation") == raw_split
    assert p.optcuts.mode == "HARD" and not p.split_regions and p.import_uvs and not p.keep_quads
    assert (p.priority, p.proxy_mode, p.weight_value) == ("FEWER_SEAMS", "ON", 5)
    run = rep["uvgami_run"]
    assert run["engine"] == "PARTUV" and run["split"] == "TREE" and not run["note"], run
    assert run["priority"] == "BALANCED" and run["proxy"] == "AUTO", run
    rows = [t for _, t in _late()._uv_rows(rep)]
    assert "Seams cut by UVgami (PartUV, tree split)" in rows, rows

    fake_uvgami.set_ai(True)                              # AI downloaded: Auto = AI
    rep = _drive_all(uv.run({**ARGS, "uvgami_engine": "PARTUV"}))
    assert uvg.seen_settings["segmentation"] == "AI" and rep["uvgami_run"]["split"] == "AI"
    rep = _drive_all(uv.run({**ARGS, "uvgami_engine": "OPTCUTS"}))
    assert uvg.seen_settings["engine"] == "OPTCUTS" and uvg.seen_settings["optcuts_mode"] == "AUTO"
    assert rep["uvgami_run"]["label"] == "OptCuts" and p.optcuts.mode == "HARD"
    assert uvg.seen_settings["priority"] == "BALANCED" and p.priority == "FEWER_SEAMS"


def test_the_ai_split_without_its_download_uses_the_tree_split_and_says_so(uvg):
    import fake_uvgami

    from forge_bpy import uv
    fake_uvgami.set_installed(("OPTCUTS", "PARTUV"))
    _low("Body", "body", (0, 0, 0))
    rep = _drive_all(uv.run({**ARGS, "uvgami_engine": "PARTUV", "partuv_split": "AI"}))
    assert uvg.seen_settings["segmentation"] == "TREE"
    assert "AI split isn't downloaded" in rep["uvgami_run"]["note"]


def test_an_engine_not_downloaded_falls_back_and_says_so_plainly(uvg):
    import fake_uvgami

    from forge_bpy import uv
    fake_uvgami.set_installed(("OPTCUTS",))
    _low("Body", "body", (0, 0, 0))
    rep = _drive_all(uv.run({**ARGS, "uvgami_engine": "PARTUV"}))
    assert uvg.seen_settings["engine"] == "OPTCUTS"
    note = rep["uvgami_run"]["note"]
    assert note.startswith("PartUV isn't downloaded yet") and "Download Engine under PartUV" in note
    assert note.endswith("Used OptCuts this time."), note
    assert rep["parts"]["Body"]["seams"] == "uvgami"
    text = " ".join(t for _, t in _late()._uv_rows(rep))
    assert "PartUV isn't downloaded yet" in text and "Seams cut by UVgami (OptCuts)" in text
    fake_uvgami.set_installed(("PARTUV",))                # Auto (OptCuts) missing: PartUV, said so
    rep = _drive_all(uv.run({**ARGS, "uvgami_engine": "AUTO"}))
    assert uvg.seen_settings["engine"] == "PARTUV" and "Used PartUV this time" in rep["uvgami_run"]["note"]


def test_auto_uses_the_engine_that_won_the_comparison(uvg):
    import fake_uvgami

    from forge_bpy import uv
    fake_uvgami.set_installed(("OPTCUTS", "PARTUV"))
    _low("Body", "body", (0, 0, 0))
    _drive_all(uv.run({**ARGS, "uvgami_engine": "AUTO", "uvgami_auto": "PARTUV"}))
    assert uvg.seen_settings["engine"] == "PARTUV"
    _drive_all(uv.run({**ARGS, "uvgami_engine": "AUTO", "uvgami_auto": ""}))
    assert uvg.seen_settings["engine"] == "OPTCUTS"                          # no comparison yet
    _drive_all(uv.run({**ARGS, "uvgami_engine": "OPTCUTS", "uvgami_auto": "PARTUV"}))
    assert uvg.seen_settings["engine"] == "OPTCUTS"                          # a chosen engine wins


def test_material_seams_only_when_the_mesh_has_more_than_one_material(uvg):
    from forge_bpy import uv
    body = _low("Body", "body", (0, 0, 0))
    skin, horn = bpy.data.materials.new("Skin"), bpy.data.materials.new("Horn")
    body.data.materials.append(skin)
    body.data.materials.append(horn)                      # two slots, every face on the first
    _drive_all(uv.run(ARGS))
    assert not uvg.seen_settings["material_seams"]
    body.data.polygons[0].material_index = 1              # now two materials meet: a part border
    rep = _drive_all(uv.run(ARGS))
    assert uvg.seen_settings["material_seams"] and rep["uvgami_run"]["material_seams"]
    assert "    seams follow the material borders" in [t for _, t in _late()._uv_rows(rep)]


def test_the_face_guard_means_no_seam_across_the_face_under_every_engine(uvg, monkeypatch):
    """UVgami 2.5.0 makes the painted face one island under every engine (the seam runs round
    its edge); an engine that would put fewer seams on it is just as good; an engine that does
    not read paint gets no paint and the report says seams may cross the face."""
    import fake_uvgami

    from forge_bpy import uv
    painted = []

    def guard(o):
        painted.append(o.name)
        g = o.vertex_groups.get(uv.UVGAMI_WEIGHTS) or o.vertex_groups.new(name=uv.UVGAMI_WEIGHTS)
        g.add(list(range(20)), 1.0, "REPLACE")
        return 20
    monkeypatch.setattr(uv, "face_seam_guard", guard)
    fake_uvgami.set_installed(("OPTCUTS", "PARTUV", "XATLAS"))
    _low("Body", "body", (0, 0, 0))
    for eid in ("OPTCUTS", "PARTUV", "XATLAS"):
        rep = _drive_all(uv.run({**ARGS, "uvgami_engine": eid}))
        assert uvg.seen_settings["engine"] == eid and uvg.seen_settings["use_weights"], eid
        assert rep["uvgami_run"]["face_guard"] == "island", rep["uvgami_run"]
    assert "    face kept in one piece: no seam across it" in [t for _, t in _late()._uv_rows(rep)]

    fake_uvgami.ENGINES["OPTCUTS"].supports_painted_islands = False         # guided cut only
    rep = _drive_all(uv.run({**ARGS, "uvgami_engine": "OPTCUTS"}))
    assert uvg.seen_settings["use_weights"] and rep["uvgami_run"]["face_guard"] == "seam_cost"

    fake_uvgami.ENGINES["XATLAS"].supports_painted_islands = False          # reads no paint
    painted.clear()
    rep = _drive_all(uv.run({**ARGS, "uvgami_engine": "XATLAS"}))
    assert not uvg.seen_settings["use_weights"] and not painted
    assert rep["uvgami_run"]["face_guard"] == "ignored"
    assert "ignores the face guard" in " ".join(t for _, t in _late()._uv_rows(rep))

    rep = _drive_all(uv.run({**ARGS, "uvgami_engine": "PARTUV", "guard_face": False}))
    assert not uvg.seen_settings["use_weights"] and rep["uvgami_run"]["face_guard"] == "off"


def test_without_its_engine_list_the_face_guard_follows_uvgami_250(uvg):
    import fake_uvgami

    from forge_bpy import uv
    sys.modules.pop(fake_uvgami.ENG)
    uv._MODS.clear()
    assert {uv.face_guard_mode(e) for e in uv.ENGINE_IDS} == {"island"}
    assert [e["id"] for e in uv.uvgami_engines() if e["installed"]] == ["OPTCUTS"]   # its panel's one


def test_the_winner_is_picked_by_the_documented_score():
    from forge_bpy import uv

    def row(eid, stretch, seams, islands, secs, ok=True):
        return {"engine": eid, "stretch": stretch, "seams": seams, "islands": islands, "seconds": secs, "ok": ok}
    # stretch first, even against far fewer seams and islands and a faster run
    assert uv.pick_winner([row("OPTCUTS", .10, 9, 40, 300), row("PARTUV", .20, 3, 5, 10)]) == \
        ("OPTCUTS", "least stretch")
    # the same stretch (within 0.02): shorter seams
    w, why = uv.pick_winner([row("OPTCUTS", .10, 9, 40, 300), row("PARTUV", .115, 6, 50, 600)])
    assert w == "PARTUV" and why.startswith("shortest seams"), why
    # the same stretch and seams (within 10 %): fewer islands
    w, why = uv.pick_winner([row("OPTCUTS", .10, 6, 40, 30), row("PARTUV", .11, 6.4, 20, 600)])
    assert w == "PARTUV" and why.startswith("fewest islands"), why
    # all about the same: the faster
    w, why = uv.pick_winner([row("OPTCUTS", .10, 6, 40, 300), row("PARTUV", .11, 6.2, 41, 60)])
    assert w == "PARTUV" and why.startswith("fastest")
    # an engine that left a part out (or overlapped) cannot win, however good its numbers
    assert uv.pick_winner([row("OPTCUTS", .05, 2, 2, 1, ok=False), row("PARTUV", .3, 9, 50, 99)])[0] == "PARTUV"
    assert uv.pick_winner([row("OPTCUTS", .05, 2, 2, 1, ok=False)])[0] == ""


def _two_lows_with_uvs():
    from forge_bpy import uv
    lows = [_low("Body", "body", (0, 0, 0)), _low("Bell", "prop", (2, 0, 0))]
    for o in lows:                                         # an earlier Step 5 result
        uv._unwrap(o, "smart", 66, 0.01)
    return lows


def test_compare_runs_every_engine_from_the_same_mesh_and_keeps_the_winner(uvg):
    import fake_uvgami
    import numpy as np

    from forge_bpy import uv
    fake_uvgami.set_installed(("OPTCUTS", "PARTUV", "XATLAS"))
    # OptCuts and PartUV stretch about the same, PartUV cuts shorter seams; xatlas stretches most
    fake_uvgami.STATE["results"] = {"OPTCUTS": ("smart", 66), "PARTUV": ("cube", 0), "XATLAS": ("sphere", 0)}
    lows = _two_lows_with_uvs()
    p = bpy.context.scene.uvgami
    p.engine = "XATLAS"                                   # the director's own choice
    before = {o.name: _uvs(o) for o in lows}
    names = {o.name: o.data.name for o in lows}
    meshes = _meshes()
    res = _drive_all(uv.compare(ARGS))
    starts = uvg.starts
    assert [s["engine"] for s in starts] == ["OPTCUTS", "PARTUV", "XATLAS"]
    for s in starts:                                      # every engine got the very same meshes
        for o in lows:
            assert np.allclose(s["uvs"][o.name], before[o.name]), s["engine"]
            assert s["faces"][o.name] == len(o.data.polygons) and s["groups"][o.name] == starts[0]["groups"][o.name]
    rows = {r["engine"]: r for r in res["rows"]}
    assert all(r["ok"] for r in rows.values()), rows
    assert rows["XATLAS"]["stretch"] > rows["OPTCUTS"]["stretch"] + uv.TIE_STRETCH
    assert rows["PARTUV"]["islands"] and rows["OPTCUTS"]["seams"] > rows["PARTUV"]["seams"]
    assert (res["winner"], res["why"]) == uv.pick_winner(res["rows"]) and res["winner"] == "PARTUV", res["rows"]
    assert res["why"].startswith("shortest seams")
    # the winner's UVs are on the model, nothing else is left behind
    assert _meshes() == meshes and {o.name: o.data.name for o in lows} == names
    assert not any(m.use_fake_user for m in bpy.data.meshes)
    assert all(not np.allclose(_uvs(o), before[o.name]) for o in lows)
    assert {r["seams"] for r in res["report"]["parts"].values()} == {"uvgami"}
    assert res["report"]["uvgami_run"]["engine"] == "PARTUV"
    assert "UVgami Unwrapped" not in bpy.data.collections and p.engine == "XATLAS"
    head, table, notes = _late()._compare_rows(res)
    assert head[:4] == ("Engine", "Stretch", "Seams", "Islands") and len(table) == 3
    assert table[1][0] == _late().GOOD and table[1][1][0].startswith("PartUV")
    assert table[2][1][0] == "xatlas (fast)" and table[2][1][2] == "1.0x"     # one piece: shortest seams
    assert notes[0][1].startswith("PartUV wins: shortest seams"), notes


def test_compare_survives_an_engine_failing(uvg, monkeypatch):
    import fake_uvgami

    from forge_bpy import uv
    fake_uvgami.set_installed(("OPTCUTS", "PARTUV", "XATLAS"))
    fake_uvgami.STATE["crash"] = {"PARTUV"}               # UVgami itself fails on PartUV
    score = uv._score

    def breaks_on_xatlas(rep):                            # and something breaks while xatlas is measured
        if rep.get("uvgami_run", {}).get("engine") == "XATLAS":
            raise RuntimeError("measuring went wrong")
        return score(rep)
    monkeypatch.setattr(uv, "_score", breaks_on_xatlas)
    lows = _two_lows_with_uvs()
    meshes = _meshes()
    res = _drive_all(uv.compare(ARGS))
    rows = {r["engine"]: r for r in res["rows"]}
    assert set(rows) == {"OPTCUTS", "PARTUV", "XATLAS"}
    assert not rows["PARTUV"]["ok"] and "would not start" in rows["PARTUV"]["why"], rows["PARTUV"]
    assert not rows["XATLAS"]["ok"] and "measuring went wrong" in rows["XATLAS"]["why"]
    assert rows["OPTCUTS"]["ok"] and res["winner"] == "OPTCUTS"
    assert _meshes() == meshes and all(o.data.uv_layers for o in lows)
    assert not any(m.use_fake_user for m in bpy.data.meshes)
    notes = " ".join(t for _, t in _late()._compare_rows(res)[2])
    assert "PartUV would not start" in notes and "xatlas: it failed" in notes, notes


def test_compare_with_no_winner_leaves_the_model_as_it_was(uvg):
    import fake_uvgami
    import numpy as np

    from forge_bpy import uv
    fake_uvgami.set_installed(("OPTCUTS", "PARTUV"))
    fake_uvgami.STATE["refuse"] = {"OPTCUTS"}             # OptCuts will not start,
    fake_uvgami.STATE["skip"] = {"PARTUV": {"Bell"}}      # PartUV gives nothing for the bell
    lows = _two_lows_with_uvs()
    before = {o.name: _uvs(o) for o in lows}
    meshes = _meshes()
    res = _drive_all(uv.compare(ARGS))
    assert res["winner"] == "" and not res["report"] and len(res["rows"]) == 2
    rows = {r["engine"]: r for r in res["rows"]}
    assert rows["PARTUV"]["why"].startswith("no result for 1 of 2 parts") and rows["PARTUV"]["delivered"] == 1
    assert rows["OPTCUTS"]["why"] == "OptCuts would not start"
    assert all(np.array_equal(_uvs(o), before[o.name]) for o in lows) and _meshes() == meshes
    assert "The model is as it was." in " ".join(t for _, t in _late()._compare_rows(res)[2])


def test_stop_during_compare_puts_everything_back(uvg):
    import fake_uvgami
    import numpy as np

    from forge_bpy import uv
    fake_uvgami.set_installed(("OPTCUTS", "PARTUV"))
    lows = _two_lows_with_uvs()
    p = bpy.context.scene.uvgami
    p.engine = "PARTUV"
    raw = p.get("engine")
    hidden = lows[1]
    hidden.hide_set(True)
    before = {o.name: _uvs(o) for o in lows}
    names = {o.name: o.data.name for o in lows}
    meshes = _meshes()
    gen = uv.compare(ARGS)
    next(gen)                                             # OptCuts is working...
    assert uvg.is_active
    gen.close()                                           # ...the director presses Stop
    assert uvg.cancelled == 1 and not uvg.is_active       # UVgami stopped: it writes nothing later
    assert {o.name: o.data.name for o in lows} == names and _meshes() == meshes
    assert all(np.array_equal(_uvs(o), before[o.name]) for o in lows)
    assert not any(m.use_fake_user for m in bpy.data.meshes)
    assert hidden.hide_get() and not lows[0].hide_get()
    assert p.get("engine") == raw and not p.transfer_uvs and p.symmetry
    assert uv.STATUS["text"] == ""


class _Layout:
    """Records what a panel draws (no UI in background mode)."""
    def __init__(self, log):
        self.__dict__["log"] = log

    def __getattr__(self, name):
        def call(*args, **kw):
            self.log.append((name, args, kw))
            return _Layout(self.log)
        return call

    def __setattr__(self, key, value):
        self.log.append(("set", key, value))


def test_compare_engines_from_the_panel(uvg):
    """The Step 5 action: warn first, run as a job, show the table, keep the winner as Auto's
    engine; Unwrap + pack on Auto then uses it."""
    import json

    import fake_uvgami
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "blender_addon"))
    import importlib
    F = importlib.import_module("forge_send")
    from forge_send import stages_late as L
    from forge_send import steps as S
    F.register()
    try:
        fake_uvgami.set_installed(("OPTCUTS", "PARTUV"))
        fake_uvgami.STATE["auto"] = True                  # the engine finishes as soon as it starts
        fake_uvgami.STATE["results"] = {"OPTCUTS": ("sphere", 0), "PARTUV": ("smart", 50)}
        _two_lows_with_uvs()
        st = bpy.context.scene.forge_stage
        st.repair, st.retopo, st.tex_size = "approved", "approved", "1024"
        st.uv_rep = json.dumps({"seconds": 95})
        n, text = S.compare_warning(95)
        assert n == 2 and "2 times (OptCuts, PartUV)" in text and "took 1 min 35 s: expect about 3 min 10 s" \
            in text, text
        assert bpy.ops.forge.uv_compare() == {"FINISHED"} and not st.error, st.error
        cmp = json.loads(st.uv_compare_rep)
        assert cmp["winner"] == "PARTUV" and "report" not in cmp and cmp["meshes"] == S.uv_fingerprint()
        assert st.uv == "review" and st.uv_engine == "AUTO" and L.uv_winner(st) == "PARTUV"
        assert json.loads(st.uv_rep)["uvgami_run"]["engine"] == "PARTUV"
        rows, plan = L._uv_engine_rows(st)
        assert plan["engine"] == "PARTUV" and rows[0][1] == "Auto uses PartUV (won Compare engines)"
        log = []
        L._draw_uv(_Layout(log), st)                      # the panel draws: table, button, rows
        texts = [k.get("text", "") for name, _a, k in log if name in ("label", "operator")]
        assert "Compare engines" in texts and "Engine" in texts and "PartUV tree" in texts, texts
        assert any(t.startswith("Unwraps 2 times; the last unwrap took") for t in texts), texts
        assert "Seams cut by UVgami (PartUV, tree split)" in texts and "PartUV wins: least stretch" in texts
        assert ("set", "action", "uv_compare_clear") in log
        assert bpy.ops.forge.step(action="uv_run") == {"FINISHED"} and not st.error, st.error
        assert uvg.starts[-1]["engine"] == "PARTUV"
        st.uv_engine = "OPTCUTS"                          # the director's own pick beats Auto
        assert bpy.ops.forge.step(action="uv_run") == {"FINISHED"} and uvg.starts[-1]["engine"] == "OPTCUTS"
        bpy.ops.forge.step(action="uv_compare_clear")
        st.uv_engine = "AUTO"
        assert L._uv_engine_rows(st)[0][0][1] == "Auto uses OptCuts (no comparison yet)"
    finally:
        F.unregister()


def test_islands_and_seam_length_are_measured():
    """A cube cut into its six sides: 6 islands, every edge a seam (12 x 1 m), on 6 m2 of surface."""
    import bmesh

    from forge_bpy import metrics, uv
    bpy.ops.wm.read_homefile(use_empty=True)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    me = bpy.data.meshes.new("cube")
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new("cube", me)
    bpy.context.scene.collection.objects.link(o)
    uv._unwrap(o, "smart", 66, 0.01)
    m = metrics.uv_layout(o)
    assert m["islands"] == 6 and abs(m["seam_length_m"] - 12) < 1e-6 and abs(m["area_m2"] - 6) < 1e-6
    assert abs(m["seam_ratio"] - 12 / 6 ** 0.5) < 1e-3
    o.scale = (1, 1, 1)
    me.transform(__import__("mathutils").Matrix.Scale(3.0, 4))     # the same cut, three times the size
    assert metrics.uv_layout(o)["seam_ratio"] == m["seam_ratio"]


def _text(rows):
    """Panel rows as one sentence (a long one is wrapped over several rows)."""
    return " ".join(t.strip() for _, t in rows)


def test_notes_only_point_to_downloads_this_uvgami_has(uvg, monkeypatch):
    """Some UVgami builds come without PartUV (or xatlas), the Superhive build without PartUV's AI
    split, and PartUV has no build for every computer: the notes say so instead of sending the
    director to a Download button that isn't there."""
    import fake_uvgami

    from forge_bpy import uv
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "blender_addon"))
    from forge_send import stages_ui
    fake_uvgami.set_installed(("OPTCUTS",))
    _low("Body", "body", (0, 0, 0))
    assert uv.resolve_engine("PARTUV")[1].startswith("PartUV isn't downloaded yet: in Edit > Preferences")

    eng = sys.modules[fake_uvgami.ENG]                    # a build without the PartUV folder
    eng.ENGINES = {k: v for k, v in eng.ENGINES.items() if k != "PARTUV"}
    assert [e["id"] for e in uv.uvgami_engines()] == ["OPTCUTS", "XATLAS"]
    assert uv.resolve_engine("PARTUV") == ("OPTCUTS", "Your UVgami comes without PartUV. Used OptCuts this time.")
    rep = _drive_all(uv.run({**ARGS, "uvgami_engine": "PARTUV"}))
    assert rep["uvgami_run"]["note"] == "Your UVgami comes without PartUV. Used OptCuts this time."
    assert "Download" not in _text(_late()._uv_rows(rep))
    labels = {i[0]: i[1] for i in stages_ui._uv_engine_items(None, None)}
    assert labels["PARTUV"] == "PartUV (not in this UVgami)" and labels["XATLAS"] == "xatlas (not downloaded)"

    eng.ENGINES = fake_uvgami.ENGINES                     # PartUV in the build, not for this computer
    fake_uvgami.STATE["unavailable"] = {"PARTUV"}
    assert uv.resolve_engine("PARTUV")[1] == "PartUV doesn't run on this computer. Used OptCuts this time."
    assert {i[0]: i[1] for i in stages_ui._uv_engine_items(None, None)}["PARTUV"] == \
        "PartUV (not for this computer)"
    fake_uvgami.STATE["unavailable"] = set()

    ai = "Download Engine under AI Segmentation"          # PartUV's AI split
    assert ai in uv.resolve_split("AI", ai_ready=False)[1]
    monkeypatch.setattr(uv, "_on_mac", lambda: True)
    assert uv.resolve_split("AI", ai_ready=False) == \
        ("TREE", "PartUV's AI split needs an NVIDIA card, which a Mac doesn't have. Used the tree split this time.")
    monkeypatch.setattr(uv, "_on_mac", lambda: False)
    sys.modules[fake_uvgami.PARTUV].partfield = None      # the Superhive build: no AI part at all
    assert uv.resolve_split("AI", ai_ready=False) == \
        ("TREE", "Your UVgami comes without PartUV's AI split. Used the tree split this time.")


def test_the_auto_row_says_why_auto_uses_its_engine(uvg):
    import json
    import types

    import fake_uvgami
    L = _late()
    fake_uvgami.set_installed(("OPTCUTS",))
    _low("Body", "body", (0, 0, 0))
    won = {"winner": "PARTUV", "why": "least stretch",
           "rows": [{"engine": "OPTCUTS", "label": "OptCuts", "ok": True},
                    {"engine": "PARTUV", "label": "PartUV", "ok": True}]}
    st = types.SimpleNamespace(uv_engine="AUTO", partuv_split="AUTO", uv_compare_rep=json.dumps(won))
    rows, plan = L._uv_engine_rows(st)                    # PartUV won, then was removed
    assert plan["engine"] == "OPTCUTS" and _text(rows).startswith(
        "Auto uses OptCuts (PartUV won Compare engines, but isn't downloaded) PartUV isn't downloaded yet"), rows
    assert all(len(t.strip()) <= 44 for _, t in rows)             # fits the panel
    eng = sys.modules[fake_uvgami.ENG]                    # ...or this UVgami has none
    eng.ENGINES = {k: v for k, v in eng.ENGINES.items() if k != "PARTUV"}
    assert _text(L._uv_engine_rows(st)[0]) == ("Auto uses OptCuts (PartUV won Compare engines, but your UVgami "
                                               "comes without it) Your UVgami comes without PartUV. Used "
                                               "OptCuts this time.")
    st.uv_compare_rep = json.dumps({"winner": "", "why": "no engine delivered every part",
                                    "rows": [{"engine": "OPTCUTS", "label": "OptCuts", "ok": False}]})
    assert _text(L._uv_engine_rows(st)[0]) == "Auto uses OptCuts (Compare engines found no winner)"
    st.uv_compare_rep = "{}"
    assert _text(L._uv_engine_rows(st)[0]) == "Auto uses OptCuts (no comparison yet)"


def _panel_ready():
    """The add-on registered, Steps 1-4 approved (the panel's actions can run)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "blender_addon"))
    import importlib
    F = importlib.import_module("forge_send")
    F.register()
    st = bpy.context.scene.forge_stage
    st.repair, st.retopo, st.tex_size = "approved", "approved", "1024"
    return F, st


def test_with_the_checker_on_unwrap_and_compare_still_see_the_material_borders(uvg):
    """'Checker on' puts one checker material on every mesh. Unwrap + pack and Compare engines take
    it off first (UVgami must see where Skin meets Horn), and put it back on afterwards."""
    import fake_uvgami
    import numpy as np
    F, st = _panel_ready()
    from forge_send import steps as S
    try:
        fake_uvgami.set_installed(("OPTCUTS", "PARTUV"))
        fake_uvgami.STATE["auto"] = True
        body, bell = _two_lows_with_uvs()
        for n in ("Skin", "Horn"):
            body.data.materials.append(bpy.data.materials.new(n))
        idx = np.zeros(len(body.data.polygons), np.int64)
        idx[:10] = 1                                      # a horn on the skin
        body.data.polygons.foreach_set("material_index", idx)

        def materials_back():                             # checker off: Skin and Horn where they were
            assert "forge_checker" in body and {m.name for m in body.data.materials} == {S.CHECKER}
            S.checker_off()
            now = np.zeros(len(body.data.polygons), np.int64)
            body.data.polygons.foreach_get("material_index", now)
            assert [m.name for m in body.data.materials] == ["Skin", "Horn"] and (now == idx).all()
            assert S.toggle_checker()

        assert S.toggle_checker()                          # the director looks at the checker
        materials_back()                                  # (on / off alone keeps the borders)

        assert bpy.ops.forge.step(action="uv_run") == {"FINISHED"} and not st.error, st.error
        assert uvg.seen_settings["material_seams"] and uvg.seen_materials["Body"] == ["Skin", "Horn"]
        materials_back()
        n = len(uvg.starts)
        assert bpy.ops.forge.uv_compare() == {"FINISHED"} and not st.error, st.error
        compared = uvg.starts[n:]
        assert [s["engine"] for s in compared] == ["OPTCUTS", "PARTUV"]
        assert all(s["settings"]["material_seams"] and s["materials"]["Body"] == ["Skin", "Horn"]
                   for s in compared), compared
        materials_back()
        S.checker_off()
    finally:
        F.unregister()


def test_stop_from_the_panel_during_compare_keeps_what_the_director_hid_hidden(uvg):
    """Stop (the panel's button) during Compare engines: the meshes come back as they were, a part
    the director hid stays hidden and an original they showed stays shown."""
    import fake_uvgami
    import numpy as np
    F, st = _panel_ready()
    from forge_send import geometry as G
    from forge_send import stages_late as L
    from forge_send import steps as S
    try:
        fake_uvgami.set_installed(("OPTCUTS", "PARTUV"))
        lows = _two_lows_with_uvs()
        original = bpy.data.objects.new("Body_original", bpy.data.meshes.new("Body_original"))
        col = bpy.data.collections.new(G.PARTS_COLLECTION)
        bpy.context.scene.collection.children.link(col)
        col.objects.link(original)                        # shown next to the new mesh by the director
        lows[1].hide_set(True)
        before = {o.name: _uvs(o) for o in lows}
        names = {o.name: o.data.name for o in lows}
        meshes = _meshes()
        gen = S.run_uv_compare(1024, False)
        next(gen)                                         # OptCuts is working...
        assert uvg.is_active
        L._JOB.update({"gen": gen, "on_done": lambda *a: None, "label": S.UV_COMPARE_JOB, "started": 0})
        assert bpy.ops.forge.stop_job() == {"FINISHED"} and "Stopped" in st.error
        assert uvg.cancelled == 1 and not uvg.is_active and not L.job_running()
        assert lows[1].hide_get() and not lows[0].hide_get() and not original.hide_get()
        assert all(np.array_equal(_uvs(o), before[o.name]) for o in lows)
        assert {o.name: o.data.name for o in lows} == names and _meshes() == meshes
        assert not any(m.use_fake_user for m in bpy.data.meshes)
        S.stop_cleanup("baking")                          # (other jobs: the new meshes are shown)
        assert not lows[1].hide_get() and original.hide_get()
    finally:
        F.unregister()
        # this test's own extras must not reach the next test file (it counts the scene's objects)
        for name in ("Body_original",):
            o = bpy.data.objects.get(name)
            if o is not None:
                me = o.data
                bpy.data.objects.remove(o)
                if me is not None and me.users == 0:
                    bpy.data.meshes.remove(me)
        c = bpy.data.collections.get(G.PARTS_COLLECTION)
        if c is not None and not c.objects:
            bpy.data.collections.remove(c)
