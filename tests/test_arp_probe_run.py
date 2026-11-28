"""`forge arp-probe` end to end in this container, where Auto-Rig Pro is not installed.

1. The 'ARP missing' path, through the real command line and the real stage runner: the file
   is still written, every check says "skipped", and the director is told in plain words.
2. Every probe item against tests/fake_arp_probe.py, run in the probe's own Blender processes
   (never in this one), including a Blender crash in the bird part.
3. A rerun of three parts (`--only`) where Auto-Rig Pro refuses the face switch on a fresh rig,
   as it did on the director's PC: every setup still runs to the end, the full result file is
   left alone, and since the human rig has the face off already (no call), the rerun asks the
   button on purpose on a fresh rig and records what its check saw (face_switch).
4. The same rerun where the cause is hidden reference bones: showing them makes the button say
   yes, and the dog rig's face switch goes through.
"""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

pytest.importorskip("bpy")              # the probe's Blender side runs on the bpy module here

from forge import arp_probe  # noqa: E402
from forge.blender import SCRIPT, BlenderError  # noqa: E402
from forge.cli import main as cli  # noqa: E402

HERE = Path(__file__).resolve().parent


def test_arp_missing_path(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "probe.json"
    rc = cli(["arp-probe", "--blender", sys.executable, "--out", str(out)])
    said = capsys.readouterr().out
    assert rc == 1
    rep = json.loads(out.read_text(encoding="utf-8"))
    assert arp_probe.validate(rep) == []
    assert rep["arp"]["loaded"] is False
    assert rep["blender"]["version"]
    assert rep["parts"]["basics"]["status"] == "ok"
    assert all(rep["parts"][k]["status"] == "skipped" for k in arp_probe.PART_KEYS if k != "basics")
    for name in arp_probe.SECTIONS:
        assert rep[name]["status"] == "skipped" and "Auto-Rig Pro" in rep[name]["reason"], name
    assert all(rep["presets"][p]["status"] == "skipped" for p in arp_probe.PRESETS)
    assert arp_probe.validate(rep, require_arp=True) == ["Auto-Rig Pro was not loaded when the probe ran"]
    # plain words: what is wrong, how to fix it, where the file is, what to send
    assert "Auto-Rig Pro is not turned on" in said and "Preferences > Add-ons" in said
    assert str(out) in said and "send that file back" in said
    assert "FORGE_BLENDER=" in (tmp_path / ".env").read_text()


# ----------------------------------------------------------------------------- fake ARP

def _fake_arp(root: Path) -> Path:
    pkg = root / "auto_rig_pro"
    (pkg / "src").mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "src" / "__init__.py").write_text("")
    shutil.copy(HERE / "fake_arp_probe.py", pkg / "src" / "auto_rig.py")
    (pkg / "blender_manifest.toml").write_text('schema_version = "1.0.0"\nid = "auto_rig_pro"\nversion = "3.79.17"\n')
    (pkg / "armature_presets").mkdir()
    for p in ("human", "dog", "horse", "bird", "bird_44", "free"):
        (pkg / "armature_presets" / f"{p}.blend").write_bytes(b"")
    wrapper = root / "run_with_fake_arp.py"
    wrapper.write_text(
        "import runpy, sys\n"
        f"sys.path.insert(0, {str(root)!r})\n"
        "import auto_rig_pro.src.auto_rig as fake\n"
        "fake.register()\n"
        f"runpy.run_path({str(SCRIPT)!r}, run_name='__main__')\n")
    return wrapper


def _runner(wrapper: Path, calls: list):
    """forge.blender.run_stage, but Blender starts with the fake ARP registered."""
    def run(stage, args, log_path, timeout=3600, blender=None, factory_startup=True, windowed=False):
        calls.append({"stage": stage, "args": args, "windowed": windowed, "factory_startup": factory_startup})
        with tempfile.TemporaryDirectory() as tmp:
            a, r = Path(tmp) / "args.json", Path(tmp) / "result.json"
            a.write_text(json.dumps(args))
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(log_path, "w") as log:
                proc = subprocess.run([sys.executable, str(wrapper), stage, str(a), str(r)],
                                      stdout=log, stderr=subprocess.STDOUT, timeout=timeout)
            if not r.exists():
                raise BlenderError(f"stage {stage} crashed (exit {proc.returncode}); see {log_path}")
            payload = json.loads(r.read_text())
        if not payload.get("ok"):
            raise BlenderError(f"stage {stage} failed: {payload.get('error')}\n{payload.get('traceback', '')}")
        return payload["result"]
    return run


@pytest.fixture(scope="module")
def probed(tmp_path_factory):
    root = tmp_path_factory.mktemp("arp_probe")
    calls: list = []
    said: list = []
    out = root / "out" / "arp_3_79_probe.json"
    rc = arp_probe.run([sys.executable], str(root / "jobs"), out, say=said.append,
                       runner=_runner(_fake_arp(root / "fake"), calls))
    return {"rc": rc, "rep": json.loads(out.read_text(encoding="utf-8")), "calls": calls, "said": said,
            "root": root}


def test_fake_probe_runs_every_part(probed):
    rep = probed["rep"]
    assert probed["rc"] == 0, "\n".join(probed["said"])
    assert arp_probe.validate(rep, require_arp=True) == []
    assert [c["args"]["part"] for c in probed["calls"]] == list(arp_probe.PART_KEYS)
    # the user's add-ons are needed (no factory startup) and ARP is loaded even if prefs are unsaved
    assert all(not c["factory_startup"] and "auto-rig pro" in c["args"]["ensure_addons"] for c in probed["calls"])
    assert [c["windowed"] for c in probed["calls"]] == [p[2] for p in arp_probe.PARTS]
    assert rep["arp"]["version"] == "3.79.17" and rep["arp"]["version_tuple"] == [3, 79, 17]
    assert "bird_44" in rep["arp"]["presets_available"]
    bad = {s: rep[s] for s in arp_probe.SECTIONS if rep[s]["status"] != "ok"}
    assert not bad, json.dumps(bad, indent=1)[:3000]


def test_fake_probe_bird_crash_is_recorded(probed):
    rep = probed["rep"]
    assert rep["parts"]["bird"]["status"] == "crashed"
    assert rep["parts"]["bird"]["stopped_at"] == "presets.bird"
    assert rep["presets"]["bird"]["status"] == "crashed"
    assert "Blender stopped" in rep["presets"]["bird"]["reason"]
    assert any("bird" in l for l in rep["parts"]["bird"]["log_tail"])
    assert any("Blender closed by itself" in l for l in probed["said"])
    assert rep["parts"]["limbs"]["status"] == "ok"          # the parts after it still ran


def test_fake_probe_presets_and_options(probed):
    rep = probed["rep"]
    h = rep["presets"]["human"]
    assert h["status"] == "ok" and h["ref_bones"]["hand_ref.r"]["parent"] == "forearm_ref.r"
    assert h["ref_bones"]["root_ref.x"]["keys"] == {"spine_count": 2}
    assert h["ref_bones"]["head_ref.x"]["collections"] == ["Reference"]
    assert rep["presets"]["free"]["ref_count"] == 1
    assert rep["spine_count"]["human"] == 2 and rep["spine_count"]["operator_default"] == 3
    lo = rep["limb_options"]
    assert lo["properties"]["tail_side"]["items"] == [".x", ".l", ".r"]
    assert lo["properties"]["fingers_ik_color"]["default"] == [0.8, 0.432, 0.0]
    assert "kilt_amount" in lo["missing_expected"] and lo["expected_present"]["finger_pinky"]
    assert rep["scale_fix"]["exists"] and rep["scale_fix"]["default"] is False
    assert rep["scene_props"]["props"]["arp_bind_engine"]["items"] == ["HEAT_MAP", "PSEUDO_VOXELS", "VHDS"]
    assert rep["operators"]["ops"]["arp.add_limb"]["exists"] and not rep["operators"]["ops"]["arp.dupli_limb"]["exists"]


def test_fake_probe_removes_one_ear_and_records_what_stayed(probed):
    """The stray-ear clean-up is only safe if disable_limb on one ear leaves the other one."""
    d = probed["rep"]["disable_limb"]
    assert d["status"] == "ok" and d["selected"] == "ear_01_ref.r"
    assert d["removed_ref_bones"] == ["ear_01_ref.r"]
    assert d["other_side_kept"] is True and "ear_01_ref.l" in d["ears_left"]
    assert "ear_01_ref_dupli_001.r" in d["ears_left"] and d["others_kept"] is True


def test_fake_probe_limb_settings_and_protocol(probed):
    rep = probed["rep"]
    per = rep["load_limb_settings"]["per_limb"]
    assert per["arm"]["limb_type"] == "arm" and per["arm"]["side"] == ".l"
    assert per["tail"]["status"] == "ok" and per["ear"]["status"] == "ok"
    assert rep["load_limb_settings"]["module"] == "auto_rig_pro.src.auto_rig"
    cases = rep["limb_protocol"]["cases"]
    assert cases["arm_pinky_off"]["changed_ok"] is True and cases["arm_pinky_off"]["unexpected_changes"] == {}
    # two arm calls in a row: the finger colour ARP reads from the EDIT bone (an ID-property array
    # that dies with Edit Mode) is copied in time, so nothing reads as reset and nothing crashes
    assert cases["arm_ring_off"]["changed_ok"] is True and cases["arm_ring_off"]["unexpected_changes"] == {}
    assert per["arm"]["edit_bone_values"] == ["fingers_ik_color"]
    assert per["arm"]["values"]["fingers_ik_color"] == [0.8, 0.432, 0.0]
    assert "Edit Mode" in rep["limb_protocol"]["note"]
    assert cases["neck_count_2"]["changed_ok"] is True
    assert cases["tail_count_6"]["after"] == {"tail_count": 6}
    assert "spine_count" in rep["ref_bone_keys"]["keys_seen"]


def test_source_keys_reads_arp_style_lookups(tmp_path, monkeypatch):
    """The key map of load_limb_settings is read from ARP's own source (spec 9.2 fallback)."""
    (tmp_path / "lls_mod.py").write_text(
        "def load_limb_settings(self):\n"
        "    b = get_edit_bone('ear_01_ref' + self.side)\n"
        "    if 'ears_amount' in b.keys():\n"
        "        self.ear_count = b['ears_amount']\n"
        "    if \"tail_count\" in tail_00_ref.keys():\n"
        "        self.tail_count = tail_00_ref[\"tail_count\"]\n"
        "    self.finger_thumb = hand_ref['thumb']\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.syspath_prepend(str(HERE.parent / "blender_scripts"))
    import lls_mod
    from forge_bpy import addon_trial
    got = addon_trial._source_keys(lls_mod.load_limb_settings)
    assert got["keys"] == ["ears_amount", "tail_count", "thumb"] and got["bones"] == ["ear_01_ref"]


def _addon_trial(monkeypatch):
    monkeypatch.syspath_prepend(str(HERE.parent / "blender_scripts"))
    from forge_bpy import addon_trial
    return addon_trial


def test_values_are_compared_and_recorded_safely(monkeypatch):
    """ID-property arrays compare by value, and a value that cannot be read is recorded as such."""
    import bpy
    at = _addon_trial(monkeypatch)
    ob = bpy.data.objects.new("probe_eq_test", None)
    try:
        ob["c"] = [0.8, 0.432, 0.0]
        arr = ob["c"]
        assert type(arr).__name__ == "IDPropertyArray"
        assert at._eq(arr, arr) and at._eq(arr, (0.8, 0.432, 0.0)) and not at._eq(arr, [0.0, 0.0, 0.0])
        assert at._plain(arr) == [0.8, 0.432, 0.0] and at._plain({"a"}) == {"a"}
        assert at._eq({"A", "B"}, ["B", "A"]) and at._eq((1, 2), [1, 2])
    finally:
        bpy.data.objects.remove(ob)

    class Broken:
        def __iter__(self):
            raise RuntimeError("freed")
    got = at._js({"ok": 1, "bad": Broken()})
    assert got["ok"] == 1 and got["bad"].startswith("<could not read Broken: RuntimeError: freed")


def test_an_item_that_cannot_be_recorded_is_an_error_not_the_end(monkeypatch):
    at = _addon_trial(monkeypatch)
    rec = at._Rec("limbs", None)
    real_put, calls = rec.put, []

    def put(key, value):
        calls.append(key)
        if len(calls) == 1:
            raise RuntimeError("bad type code")
        real_put(key, value)
    rec.put = put
    out = at._item(rec, "limb_protocol.cases.arm_pinky_off", lambda: {"x": 1})
    assert out["status"] == "error" and "could not record" in out["error"]
    assert rec.r["limb_protocol"]["cases"]["arm_pinky_off"]["status"] == "error"
    at._item(rec, "limb_protocol.cases.neck_count_2", lambda: {"x": 2})    # the next item still runs
    assert rec.r["limb_protocol"]["cases"]["neck_count_2"] == {"x": 2, "status": "ok",
                                                               "seconds": rec.r["limb_protocol"]["cases"]["neck_count_2"]["seconds"]}


def test_fake_probe_add_limb_names(probed):
    a = probed["rep"]["add_limb"]
    assert "spline_ik" in a["presets_items"]
    assert all(a["cases"][c]["status"] == "ok" for c in ("arm_dupli", "tail_dupli_left", "tail_dupli_right",
                                                          "spline_ik", "ears_second", "kilt")), a["cases"].keys()
    assert a["cases"]["arm_dupli"]["new_root"] == "shoulder_ref_dupli_001.l"
    left = a["cases"]["tail_dupli_left"]
    # ARP renames a tail moved to another side; the probe follows it and hangs it from the head
    assert left["new_root"] == "tail_00_ref_dupli_001.x"
    assert left["root_after_side"] == "tail_00_ref.l" and left["parent_now"] == "head_ref.x"
    assert left["side_change"]["changed_ok"] is True and left["side_change"]["ref_after"] == "tail_00_ref.l"
    assert a["cases"]["tail_dupli_right"]["root_after_side"] == "tail_00_ref.r"
    assert a["cases"]["ears_second"]["new_root"].startswith("ear_01_ref_dupli_001")
    assert a["after_match"]["chain_roots_parents"]["tail_00.l"][0] == "head.x"
    res = probed["rep"]["humanoid_check"]["results"]
    assert res["refs_with_second_ears"]["humanoid"] is False       # more than 2 ear sides
    assert res["human_after_match"]["humanoid"] is True


def test_fake_probe_build_bind_chin_poles_sockets(probed):
    rep = probed["rep"]
    assert rep["ik_poles"]["expected"] == {n: True for n in ("c_leg_pole.l", "c_leg_pole.r", "c_arms_pole.l",
                                                             "c_arms_pole.r")}
    assert rep["ik_poles"]["ik_constraints"]["leg.l"]["pole"] == "c_leg_pole.l"
    # a second arm's pole is named after its side (ARP: 'c_arms_pole' + side)
    after = probed["rep"]["add_limb"]["after_match"]["ik_poles"]
    assert after["dupli_poles"] == ["c_arms_pole_dupli_001.l"]
    multi = rep["multi_arm_export"]["ik_poles"]
    assert multi["dupli_poles"] == ["c_arms_pole_dupli_001.l"]
    assert multi["ik_constraints"]["arm_dupli_001.l"]["pole"] == "c_arms_pole_dupli_001.l"
    dog = rep["ik_poles"]["rigs"]["dog"]
    assert dog["status"] == "ok" and dog["preset"] == "dog" and "c_leg_pole.l" in dog["pole_bones"]
    ops = rep["operators"]["ops"]
    assert ops["id.set_humanoid_rig"]["exists"] and ops["id.set_mped_rig"]["exists"]
    assert rep["deform_names"]["owner_bones"]["hand.r"] is True
    chin = rep["chin"]
    assert chin["keys_read"] is True and chin["approximate_without_keys"] is True and chin["weights_changed"]
    # the fake's first bind fails heat weighting and turns Scale Fix on, like ARP: the second chin
    # bind still runs without it, and the chin says its weight comparison does not count
    assert chin["scale_fix_turned_on_by_arp"] == ["bind_without_keys"] and chin["weights_comparison_valid"] is False
    assert chin["bind_with_keys"]["scale_fix_used"] is False and "weights_comparison_note" in chin
    b = rep["bind"]
    assert b["engine_items"] == ["HEAT_MAP", "PSEUDO_VOXELS", "VHDS"] and b["preserve_volume_prop"] == "arp_bind_preserve"
    assert b["modifier_preserve_volume"] is True and b["pseudo_voxels"]["ok"] is True
    assert b["heat_map"]["unweighted_vertices"] == 0
    assert b["pseudo_voxels"]["scale_fix_used"] is False          # ARP's switch was put back
    for label in ("unity_humanoid", "unity_universal", "unreal_humanoid", "unreal_universal"):
        v = rep["socket_export"]["variants"][label]
        assert v["exported"] and v["socket"] == {"found": True, "name": "cc_socket_probe", "parent": "hand.r",
                                                  "all_matches": ["cc_socket_probe"]}, label
        assert v["prop_exported"], label
    m = rep["multi_arm_export"]
    assert m["humanoid_check"] is True and m["exported"] and "arm_dupli_001.l" in m["dupli_bones_exported"]
    assert rep["wings"]["arm_wings_set"] is True and rep["wings"]["feather_bones"] == ["c_arm_feather_01_dupli_001.l"]
    assert rep["wings"]["protocol"]["unexpected_changes"] == {}
    assert rep["headless"]["append_ok"] is True and rep["headless"]["match_ok"] is True
    assert (probed["root"] / "jobs" / "_setup" / "arp_probe" / "exports" / "probe_unity_humanoid.fbx").exists()


def test_fake_probe_face_switch_goes_through_the_shared_protocol(probed):
    """The human preset stores facial = 0 (as Auto-Rig Pro's does): the three setups send nothing.
    The fresh dog rig (facial = 1) has it turned off the 9.2 way and checked, as Step 8 would."""
    rep = probed["rep"]
    for face in (rep["multi_arm_export"]["facial"], rep["extra"]["limbs_setup"]["facial"],
                 rep["extra"]["build_setup"]["facial"]):
        assert face == {"facial": "already off", "stored": 0}, face
    fs = rep["extra"]["face_switch"]
    dog = fs["fresh_dog"]
    assert dog["status"] == "ok" and dog["stored_before"] == 1 and dog["stored_after"] is False, dog
    assert dog["before"]["poll"] is True and dog["facial"]["facial"] == "off"
    assert dog["facial"]["protocol"]["call_used"] == "all_keys" and dog["facial"]["protocol"]["unexpected_changes"] == {}
    human = fs["fresh_human"]
    assert human["status"] == "ok" and human["before"]["poll"] is True and human["shown"] == []
    assert human["answer"] == "Auto-Rig Pro said yes straight away"
    lines = arp_probe.summary_lines(rep)
    assert "Limb options button on a fresh rig: Auto-Rig Pro said yes straight away" in lines
    assert "Face-bones switch: already off (3 test rigs), off (1 test rig)" in lines


def test_bones_are_told_apart_by_name_words_not_letters(probed, monkeypatch):
    """'ear' is in 'forearm' as letters: the director's first file listed forearm bones as ear
    deform bones and forearm_stretch as an ear chain."""
    at = _addon_trial(monkeypatch)
    assert not at._named("forearm_stretch_dupli_001.l", "ear") and not at._named("forearm_twist.r", "ear")
    assert at._named("c_ear_01_dupli_001.l", "ear") and at._named("ear_02_ref.r", "ear")
    assert at._named("c_tail_master.x", "tail") and not at._named("c_detail.x", "tail")
    assert at._named("c_spline_curvy.x", "spline") and not at._named("c_spine_02.x", "spline")
    assert at._named("c_hand_feather_master_dupli_001.l", *at.WING_WORDS)
    after = probed["rep"]["add_limb"]["after_match"]
    assert after["ear_deform"] and all(at._named(n, "ear") for n in after["ear_deform"]), after["ear_deform"]
    assert not [n for n in after["chain_roots_parents"] if n.startswith("forearm")]


def test_rerun_where_the_face_switch_is_refused_still_runs_every_setup(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_ARP_POLL", "before_add_limb")      # the fake's button says no on a fresh rig
    work = tmp_path / "jobs" / "_setup" / "arp_probe"
    work.mkdir(parents=True)
    (work / arp_probe.RESULT_NAME).write_text("the full result\n", encoding="utf-8")
    calls: list = []
    said: list = []
    rc = arp_probe.run([sys.executable], str(tmp_path / "jobs"), None, say=said.append,
                       runner=_runner(_fake_arp(tmp_path / "fake"), calls), only="multi_arm,limbs,build")
    assert rc == 0, "\n".join(said)
    assert [c["args"]["part"] for c in calls] == ["multi_arm", "limbs", "build"]
    assert (work / arp_probe.RESULT_NAME).read_text(encoding="utf-8") == "the full result\n"
    rep = json.loads((work / arp_probe.RERUN_NAME).read_text(encoding="utf-8"))
    assert arp_probe.validate(rep, require_arp=True) == []
    assert rep["only"] == ["multi_arm", "limbs", "build"]
    assert rep["parts"]["basics"]["status"] == "not_run" and rep["presets"]["human"]["status"] == "not_run"
    # the human rig has the face off already: the setups send nothing and run to the end
    m = rep["multi_arm_export"]
    assert m["status"] == "ok" and m["exported"] and m["humanoid_check"] is True, m
    for face in (m["facial"], rep["extra"]["limbs_setup"]["facial"], rep["extra"]["build_setup"]["facial"]):
        assert face == {"facial": "already off", "stored": 0}, face
    assert rep["extra"]["limbs_setup"]["status"] == "ok" and rep["extra"]["build_setup"]["status"] == "ok"
    # so the rerun asks on purpose, on a fresh rig, and records what Auto-Rig Pro's check saw
    fs = rep["extra"]["face_switch"]
    human = fs["fresh_human"]
    assert human["status"] == "ok" and human["before"]["poll"] is False and human["after"]["poll"] is False
    assert human["shown"] == [] and human["before"]["reference_visible"] == {"Reference": {"visible": True, "seen": True}}
    for d in (human["before"]["diagnostics"], human["after"]["diagnostics"]):
        assert 'POLL == "before_add_limb"' in d["poll_sources"][0]["source"], d
        assert d["active_object"] == "rig" and d["active_edit_bone"] == "head_ref.x", d
        assert d["selected_edit_bones"] == ["head_ref.x"] and set(d["override"]) == {"window", "area", "region"}
        assert d["mode"] == "EDIT_ARMATURE" and d["active_type"] == "ARMATURE"
        assert d["selected_editable_bones"]["bones"] == ["head_ref.x"]
    assert human["answer"] == "Auto-Rig Pro said no, even with the reference bones shown"
    dog = fs["fresh_dog"]                               # Step 8's own face switch, on a dog rig
    assert dog["status"] == "ok" and dog["stored_before"] == 1 and dog["stored_after"] == 1, dog
    assert dog["before"]["poll"] is False and dog["facial"]["facial"] == "still on"
    assert dog["facial"]["reason"] == "Auto-Rig Pro said no here"
    assert "poll_sources" in dog["facial"]["protocol"]["diagnostics"]
    # after a limb was added the same button works (as on the director's PC)
    assert all(c["changed_ok"] for c in rep["limb_protocol"]["cases"].values())
    for name in ("disable_limb", "chin", "bind", "socket_export", "deform_names"):
        assert rep[name]["status"] == "ok", (name, rep[name])
    assert rep["add_limb"]["cases"]["kilt"]["status"] == "ok"
    lines = arp_probe.summary_lines(rep)
    assert lines[1] == "Rerun of: multi_arm, limbs, build (the full result file stays as it was)"
    assert lines[2] == "Checks that worked: 11 of 11"           # (1 multi_arm, 5 limbs, 5 build)
    assert lines[-2] == "Limb options button on a fresh rig: Auto-Rig Pro said no, even with the reference bones shown"
    assert lines[-1].startswith("Face-bones switch: Auto-Rig Pro said no on 1 of 4 test rigs")
    assert str(work / arp_probe.RERUN_NAME) in said[-4]
    # the rerun's logs and exports sit beside the full run's, not over them
    assert (work / "logs" / "rerun_limbs.log").exists() and not (work / "logs" / "limbs.log").exists()
    assert rep["parts"]["limbs"]["log"].startswith("_setup/arp_probe/logs/rerun_limbs.log")
    assert (work / "exports" / "rerun" / "probe_multi_arm_unity_humanoid.fbx").exists()
    assert not (work / "exports" / "probe_unity_humanoid.fbx").exists()


def test_rerun_where_hidden_reference_bones_are_the_cause_shows_them_and_goes_through(tmp_path, monkeypatch):
    """If the cause is the one Forge guesses (the fresh rig's reference bones cannot be seen),
    the rerun says so, and the face switch Step 8 makes on a dog rig goes through."""
    monkeypatch.setenv("FAKE_ARP_POLL", "hidden_refs")
    calls: list = []
    said: list = []
    rc = arp_probe.run([sys.executable], str(tmp_path / "jobs"), None, say=said.append,
                       runner=_runner(_fake_arp(tmp_path / "fake"), calls), only=["multi_arm", "limbs"])
    assert rc == 0, "\n".join(said)
    rep = json.loads((tmp_path / "jobs" / "_setup" / "arp_probe" / arp_probe.RERUN_NAME).read_text(encoding="utf-8"))
    fs = rep["extra"]["face_switch"]
    human = fs["fresh_human"]
    assert human["before"]["poll"] is False and human["shown"] == ["Reference"] and human["after"]["poll"] is True
    assert human["before"]["reference_visible"] == {"Reference": {"visible": False, "seen": False}}
    assert human["before"]["diagnostics"]["selected_editable_bones"]["bones"] == []
    assert human["answer"] == "Auto-Rig Pro said no until the reference bones were shown"
    dog = fs["fresh_dog"]
    assert dog["before"]["poll"] is False and dog["facial"]["facial"] == "off", dog
    assert dog["facial"]["protocol"]["shown"] == ["Reference"] and dog["stored_after"] is False
    assert all(c["changed_ok"] for c in rep["limb_protocol"]["cases"].values())
    lines = arp_probe.summary_lines(rep)
    assert "Limb options button on a fresh rig: Auto-Rig Pro said no until the reference bones were shown" in lines
    assert "Face-bones switch: already off (2 test rigs), off (1 test rig)" in lines
