"""Step 8 changes Auto-Rig Pro limb options the safe way (spec 9.2, forge_bpy/arp_limb_options),
the same code the `forge arp-probe` check uses. Against tests/fake_arp.py, whose limb options
button re-applies every option of the limb, so an option left out of a call goes back to its
default (as Auto-Rig Pro's does).

- the human preset already has face bones off: nothing is sent
- every option is sent back, with load_settings_when_exec off; only the asked ones change
- a call with only the new count loses another setting; the protocol keeps it
- Auto-Rig Pro refusing the face switch (as it did on the director's PC) is reported in plain
  words with what its check saw, and the tail and ears are still added
- reference bones hidden after a fresh rig are shown first (the likely cause on that PC), and
  poll_check (what the probe rerun asks on purpose) sees the button say no, then yes
- an option Auto-Rig Pro changes without being asked is named on the panel
- the poll diagnostics never raise, even when the active object cannot be read
- without Auto-Rig Pro's settings reader nothing is changed blind
"""

import importlib
import sys
from pathlib import Path

import pytest

bpy = pytest.importorskip("bpy")
from mathutils import Vector  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "blender_scripts"))
sys.path.insert(0, str(ROOT / "blender_addon"))
sys.path.insert(0, str(ROOT / "tests"))

TAIL = {"kind": "tail", "name": "tail", "chain": [(0, 0.1, 0.9), (0, 0.5, 0.8), (0, 0.9, 0.5)]}
EARS = [{"kind": "ear", "name": f"ear_{s}", "chain": [(0.1 * x, 0, 1.7), (0.3 * x, 0, 1.85)]}
        for s, x in (("l", 1), ("r", -1))]
SAID_NO = "Auto-Rig Pro said no here"


@pytest.fixture
def arp():
    import fake_arp as A
    bpy.ops.wm.read_homefile(use_empty=True)
    A.register()
    A.HIDE_REFS = A.POLL_SAYS_NO = A.IGNORE_TAIL_PARENT = False
    A.SEEN.clear()
    A.ALSO_RESET.clear()
    try:
        yield A
    finally:
        A.HIDE_REFS = A.POLL_SAYS_NO = False
        A.ALSO_RESET.clear()
        A.unregister()


def _rig(face_on: bool = False):
    """A fresh human reference rig (object mode). face_on: as Auto-Rig Pro's dog and horse presets."""
    bpy.ops.arp.append_arp()
    rig = bpy.data.objects["rig"]
    if face_on:
        rig.data.bones["head_ref.x"]["facial"] = 1
    return rig


def _tip(rig, bone: str) -> float:
    return (rig.data.bones[bone].tail_local - Vector(TAIL["chain"][-1])).length


def test_face_bones_already_off_in_the_preset_send_nothing(arp):
    from forge_bpy import arp_rig
    rep = arp_rig.add_extras(_rig(), [TAIL] + EARS, {})
    assert rep["facial"] == "already off" and not rep["errors"], rep
    assert "limb_calls" not in arp.SEEN                 # default counts too: not one call
    assert rep["added"] == {"tail": 4, "ears": 4}


def test_every_option_is_sent_back_and_only_the_asked_ones_change(arp):
    from forge_bpy import arp_limb_options as LO
    from forge_bpy import arp_rig
    rig = _rig(face_on=True)
    rig.data.bones["head_ref.x"]["skull_bones"] = True       # a setting of the head that is not the default
    rep = arp_rig.add_extras(rig, [TAIL] + EARS, {"tail_bones": 6, "ear_bones": 3})
    assert not rep["errors"], rep["errors"]
    assert rep["facial"] == "off" and rep["added"] == {"tail": 6, "ears": 6}
    calls = arp.SEEN["limb_calls"]
    # Auto-Rig Pro counts each side's ear on its own: one call per side
    assert [(c["limb_type"], c["side"]) for c in calls] == [("head", ".x"), ("tail", ".x"), ("ear", ".l"), ("ear", ".r")]
    every = (set(LO.op_defaults()) - LO.UI_ONLY) | {"load_settings_when_exec"}
    for c in calls:
        assert set(c) == every and c["load_settings_when_exec"] is False, c
    assert calls[0]["facial"] is False and calls[0]["skull_bones"] is True     # kept as it was
    for what, r in rep["limb_options"].items():
        assert r["ok"] and r["call_used"] == "all_keys" and r["unexpected_changes"] == {}, (what, r)
    head = rig.data.bones["head_ref.x"]
    assert head["skull_bones"] is True and head["facial"] is False
    assert [f"tail_{i:02d}_ref.x" in rig.data.bones for i in range(7)] == [True] * 6 + [False]
    assert _tip(rig, "tail_05_ref.x") < 1e-4                  # the six bones run along the whole tail
    assert all(f"ear_03_ref.{s}" in rig.data.bones for s in "lr")


def test_a_call_with_only_the_new_count_resets_another_setting_the_protocol_keeps_it(arp):
    from forge_bpy import arp_limb_options as LO
    rig = _rig()
    LO.edit_mode(rig)
    bpy.ops.arp.add_limb(limbs_presets="tail")
    eb = rig.data.edit_bones
    eb["tail_00_ref.x"]["tail_master_at_root"] = False         # set earlier (by the rig plan, say)
    LO.select_ref(rig, "tail_00_ref.x")
    with bpy.context.temp_override(**LO.view3d()):
        bpy.ops.arp.show_limb_params("EXEC_DEFAULT", limb_type="tail", side=".x", tail_count=6)
    assert eb["tail_00_ref.x"]["tail_master_at_root"] is True    # lost: back to the default

    eb["tail_00_ref.x"]["tail_master_at_root"] = False
    before, _, _, _ = LO.limb_state(rig, "tail_00_ref.x", LO.op_defaults())
    r = LO.set_limb_options(rig, "tail_00_ref.x", {"tail_count": 5})
    sent = arp.SEEN["limb_calls"][-1]
    assert r["ok"] and r["unexpected_changes"] == {} and r["after"] == {"tail_count": 5}, r
    assert {k for k, v in sent.items() if not LO.same(v, before.get(k))} == {"tail_count"}
    eb = rig.data.edit_bones
    assert eb["tail_00_ref.x"]["tail_master_at_root"] is False   # kept
    assert "tail_04_ref.x" in eb and "tail_05_ref.x" not in eb
    # asking for what is already so sends nothing
    n = len(arp.SEEN["limb_calls"])
    assert LO.set_limb_options(rig, "tail_00_ref.x", {"tail_count": 5})["call_used"] == "none"
    assert len(arp.SEEN["limb_calls"]) == n


def test_a_refused_face_switch_is_reported_and_the_tail_and_ears_are_still_added(arp):
    from forge_bpy import arp_rig
    L = importlib.import_module("forge_send.stages_late")
    rig = _rig(face_on=True)
    arp.POLL_SAYS_NO = True
    rep = arp_rig.add_extras(rig, [TAIL] + EARS, {"tail_bones": 6})
    assert rep["facial"] == "still on"
    assert rep["errors"] == [f"face bones stay on: {SAID_NO}", f"tail: 4 bones, not 6: {SAID_NO}"]
    assert rep["added"] == {"tail": 4, "ears": 4} and rep["chains"] == ["tail", "ear_l", "ear_r"]
    assert _tip(rig, "tail_03_ref.x") < 1e-4                  # Auto-Rig Pro's four bones span the tail
    # for the log: what Auto-Rig Pro's check saw
    face = rep["limb_options"]["facial"]
    assert face["stage"] == "call" and "context is incorrect" in face["error"]
    d = face["diagnostics"]
    assert "POLL_SAYS_NO" in d["poll_sources"][0]["source"] and d["class"].endswith("FAKE_OT_show_limb_params")
    assert d["mode"] == "EDIT_ARMATURE" and d["active_object"] == "rig" and d["active_type"] == "ARMATURE"
    assert d["active_edit_bone"] == "head_ref.x" and d["selected_edit_bones"] == ["head_ref.x"]
    assert set(d["override"]) == {"window", "area", "region"}
    assert d["selected_editable_bones"]["bones"] == ["head_ref.x"]
    rows = [t for _i, t in L._rig_rows({"extras": rep})]
    assert f"face bones stay on: {SAID_NO}" in rows and max(map(len, rows)) <= 60, rows


def test_hidden_reference_bones_are_shown_before_auto_rig_pro_is_asked(arp):
    """The director's Auto-Rig Pro refused the face switch right after a fresh rig and never
    after an added limb; adding a limb shows the reference bones, and the button wants a
    selected bone that can be seen. The protocol shows the reference bones first."""
    from forge_bpy import arp_limb_options as LO
    arp.HIDE_REFS = True
    rig = _rig(face_on=True)
    LO.select_ref(rig, "head_ref.x")
    with pytest.raises(RuntimeError, match="context is incorrect"):
        with bpy.context.temp_override(**LO.view3d()):
            bpy.ops.arp.show_limb_params("EXEC_DEFAULT", limb_type="head", side=".x", facial=False)
    out = LO.facial_off(rig)
    assert out["facial"] == "off" and out["protocol"]["shown"] == ["Reference"], out


def test_poll_check_sees_the_button_say_no_then_yes_once_the_reference_bones_show(arp):
    """What the probe rerun asks on purpose on a fresh rig (addon_trial._fresh_rig_check)."""
    from forge_bpy import arp_limb_options as LO
    arp.HIDE_REFS = True
    rig = _rig()
    before = LO.poll_check(rig, "head_ref.x")
    assert before["poll"] is False, before
    assert before["reference_visible"] == {"Reference": {"visible": False, "seen": False}}
    d = before["diagnostics"]
    assert d["selected_edit_bones"] == ["head_ref.x"] and d["selected_editable_bones"]["bones"] == []
    assert d["ref_collections"] == {"Reference": False} and "poll_sources" in d
    assert LO.show_ref(rig, "head_ref.x") == ["Reference"]
    after = LO.poll_check(rig, "head_ref.x")
    assert after["poll"] is True and after["reference_visible"]["Reference"]["seen"] is True, after
    assert after["diagnostics"]["selected_editable_bones"]["bones"] == ["head_ref.x"]
    assert rig.data.bones["head_ref.x"]["facial"] == 0 and "limb_calls" not in arp.SEEN   # nothing changed
    assert LO.poll_check(rig, "no_such_ref.x") == {"ref": "no_such_ref.x", "error": "no_such_ref.x is not in the rig"}


def test_an_option_auto_rig_pro_changes_unasked_is_named_on_the_panel(arp):
    """The protocol sends every option back, yet Auto-Rig Pro may still reset one: Step 8 must
    not lose that setting without a word."""
    from forge_bpy import arp_rig
    L = importlib.import_module("forge_send.stages_late")
    arp.ALSO_RESET.update(head={"skull_bones": False}, tail={"tail_master_at_root": False})
    rig = _rig(face_on=True)
    rig.data.bones["head_ref.x"]["skull_bones"] = True
    rep = arp_rig.add_extras(rig, [TAIL], {"tail_bones": 6})
    assert rep["facial"] == "off" and rep["added"] == {"tail": 6}
    assert rep["limb_options"]["facial"]["unexpected_changes"] == {"skull_bones": [True, False]}
    assert rep["errors"] == ["face bones: Auto-Rig Pro also changed skull bones",
                             "tail: Auto-Rig Pro also changed tail master at root"], rep["errors"]
    rows = [t for _i, t in L._rig_rows({"extras": rep})]
    assert "face bones: Auto-Rig Pro also changed skull bones" in rows


def test_poll_diagnostics_never_raise_when_the_active_object_cannot_be_read(monkeypatch):
    from types import SimpleNamespace

    from forge_bpy import arp_limb_options as LO

    class Gone:                                     # what a removed object does when read
        def __getattr__(self, name):
            raise ReferenceError("StructRNA of type Object has been removed")

    ctx = SimpleNamespace(mode="EDIT_ARMATURE", view_layer=SimpleNamespace(objects=SimpleNamespace(active=Gone())))
    monkeypatch.setattr(LO, "bpy", SimpleNamespace(context=ctx, types=bpy.types, ops=bpy.ops))
    d = LO.poll_diagnostics(None, "head_ref.x")
    assert d["mode"] == "EDIT_ARMATURE" and "has been removed" in d["active_object_error"], d
    assert "active_type" not in d and "has been removed" in d["active_type_error"]
    monkeypatch.setattr(LO, "_what_poll_sees", lambda *a: 1 / 0)
    assert "ZeroDivisionError" in LO.poll_diagnostics(None, "head_ref.x")["diagnostics_error"]


def test_without_auto_rig_pros_settings_reader_nothing_is_changed_blind(arp):
    from forge_bpy import arp_rig
    sys.modules.pop("fake_auto_rig")                          # (the fixture puts nothing back)
    rig = _rig(face_on=True)
    rep = arp_rig.add_extras(rig, [TAIL], {"tail_bones": 6})
    assert "limb_calls" not in arp.SEEN
    assert rep["facial"] == "still on" and rep["added"] == {"tail": 4}
    assert rep["errors"] == ["face bones stay on: its settings could not be read",
                             "tail: 4 bones, not 6: its settings could not be read"]


def test_every_reason_fits_on_one_panel_row():
    from forge_bpy import arp_limb_options as LO
    for why in LO.WORDS.values():
        assert len(f"right ear: 2 bones, not 12: {why.format(ref='ear_01_ref.r')}") <= 60, why
        assert len(f"face bones stay on: {why.format(ref='head_ref.x')}") <= 60, why
    ears = {"unexpected_changes": {"ear_twist": [False, True], "ear_count": [3, 2]}}
    assert LO.also_changed(ears, "right ear") == "right ear: Auto-Rig Pro also changed ear count and 1 more"
    two = {"unexpected_changes": {"tail_master_at_root": [True, False], "tail_side": [".x", ".l"]}}
    assert LO.also_changed(two, "tail") == "tail: Auto-Rig Pro also changed 2 other options"   # (too long)
    long = {"unexpected_changes": {"a_very_long_option_name_from_auto_rig_pro": [1, 2]}}
    assert LO.also_changed(long, "right ear") == "right ear: Auto-Rig Pro also changed 1 other option"
    assert LO.also_changed({"unexpected_changes": {}}, "tail") == ""
    assert LO.also_changed(None, "tail") == "" and LO.also_changed("not a report", "tail") == ""
