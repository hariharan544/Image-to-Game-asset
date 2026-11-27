"""The Auto-Rig Pro probe file that Step 8's later work packages read instead of guessing from
the 3.77.33 source mirror. `forge arp-probe` writes it to jobs/_setup/arp_probe/ on the
director's PC (outside git); once sent back it is committed as docs/research/arp_3_79_probe.json.

- The committed file, once the director has sent it back, has every key they read
  (skipped while the file is absent).
- `forge.arp_probe.validate` really catches missing keys, and the command's merging turns a
  Blender crash or a timeout into recorded results instead of losing the rest. Pure Python.
"""

import json
from pathlib import Path

import pytest

from forge import arp_probe
from forge.blender import BlenderError

PROBE_FILE = arp_probe.COMMITTED       # docs/research/arp_3_79_probe.json


def test_committed_probe_file_has_every_key_later_work_reads():
    if not PROBE_FILE.exists():
        pytest.skip("docs/research/arp_3_79_probe.json not sent back yet (run `forge arp-probe` on the director's PC)")
    rep = json.loads(PROBE_FILE.read_text(encoding="utf-8"))
    assert arp_probe.validate(rep, require_arp=True) == []
    # the facts the spec marks [probe] each have an answer, even if that answer is "it crashed"
    for name in arp_probe.SECTIONS:
        assert rep[name]["status"] in arp_probe.STATUSES
    assert rep["arp"]["version_tuple"][:1] == [3]


def _all_ok() -> dict:
    merged = {"blender": {"version": "5.3.0"}, "arp": {"loaded": True, "version": "3.79.17"},
              "presets": {p: {"status": "ok", "armature": "rig", "ref_bones": {}, "ref_count": 0}
                          for p in arp_probe.PRESETS}}
    for name, (_part, keys) in arp_probe.SECTIONS.items():
        merged[name] = {"status": "ok", **{k: {} for k in keys}}
    return arp_probe.assemble(merged, {k: {"status": "ok"} for k in arp_probe.PART_KEYS})


def test_validate_accepts_a_complete_report():
    assert arp_probe.validate(_all_ok(), require_arp=True) == []


def test_validate_names_what_is_missing():
    rep = _all_ok()
    del rep["chin"]["keys_read"]
    rep["presets"]["dog"] = {"status": "ok", "armature": "rig", "ref_count": 3}
    rep["bind"] = {"status": "error"}
    rep["socket_export"]["variants"] = {"unity_humanoid": {"status": "ok", "exported": True}}
    rep["wings"] = {"status": "crashed"}
    rep["parts"].pop("build")
    rep["arp"]["version"] = None
    p = arp_probe.validate(rep)
    for want in ("chin: 'keys_read' missing", "presets.dog: 'ref_bones' missing", "bind: an error without its message",
                 "socket_export.variants.unity_humanoid: 'socket' missing", "wings: status crashed without a reason",
                 "parts.build: missing or unknown status", "arp.version missing"):
        assert want in p, (want, p)


def test_a_crash_or_a_timeout_is_recorded_and_the_rest_kept(tmp_path):
    """Fake Blender runs: the bird part dies on the bird preset, the limbs part times out on the
    kilt; both had written their partial file. Everything found before is kept."""
    said: list = []

    def runner(stage, args, log_path, **kw):
        part = args["part"]
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(f"log of {part}\nlast line {part}\n")
        partial = Path(args["partial"])
        if part == "basics":
            return {"part": "basics", "_current": None, "blender": {"version": "5.3.0"},
                    "arp": {"loaded": True, "version": "3.79.17"},
                    "presets": {"human": {"status": "ok", "armature": "rig", "ref_bones": {"root_ref.x": {}},
                                          "ref_count": 1}}, "errors": ["presets.dog: KeyError"]}
        if part == "bird":
            partial.write_text(json.dumps({"_current": "presets.bird", "blender": {"version": "5.3.0"}}))
            raise BlenderError(f"stage {stage} crashed (exit 3221225477); see {log_path}")
        if part == "limbs":
            partial.write_text(json.dumps({
                "_current": "add_limb.cases.kilt", "errors": ["x: y"],
                "add_limb": {"status": "ok", "presets_items": ["tail"],
                             "cases": {"tail_first": {"status": "ok", "new_ref_bones": {"tail_00_ref.x": "root_ref.x"}}}}}))
            raise BlenderError(f"stage {stage} timed out after 900s")
        if part == "headless":                  # ARP does not load without a window: a finding
            return {"part": part, "arp": {"loaded": False}, "blender": {"version": "5.3.0"},
                    "headless": {"status": "ok", "arp_loaded": False, "append_ok": False, "match_ok": None}}
        if part in ("wings", "multi_arm"):
            return {"part": part, "arp": {"loaded": False}}
        if part == "build":
            raise OSError("Blender could not start")       # not even a Blender error: still recorded
        return {"part": part, "_current": None}

    out = tmp_path / "probe.json"
    assert arp_probe.run(["blender"], str(tmp_path / "jobs"), out, say=said.append, runner=runner) == 0
    rep = json.loads(out.read_text(encoding="utf-8"))
    assert arp_probe.validate(rep) == []
    assert rep["parts"]["bird"]["status"] == "crashed" and rep["parts"]["bird"]["stopped_at"] == "presets.bird"
    assert rep["parts"]["bird"]["log_tail"][-1] == "last line bird"
    assert rep["presets"]["bird"]["status"] == "crashed"
    assert rep["parts"]["limbs"]["status"] == "timeout"
    assert rep["add_limb"]["cases"]["tail_first"]["status"] == "ok"
    assert rep["add_limb"]["cases"]["kilt"]["status"] == "timeout"
    assert rep["load_limb_settings"]["status"] == "not_run" and "timeout" in rep["load_limb_settings"]["reason"]
    assert rep["parts"]["build"]["status"] == "error" and "could not start" in rep["parts"]["build"]["message"]
    assert rep["chin"]["status"] == "not_run" and "error" in rep["chin"]["reason"]
    assert rep["presets"]["human"]["status"] == "ok" and rep["presets"]["dog"]["status"] == "not_run"
    assert rep["errors"] == ["presets.dog: KeyError", "x: y"]
    # a later part whose Blender did not load ARP does not overwrite what the first part found
    assert rep["arp"] == {"loaded": True, "version": "3.79.17"}
    assert rep["headless"]["append_ok"] is False and rep["parts"]["headless"]["arp_loaded"] is False
    assert rep["wings"] == {"status": "skipped", "reason": "Auto-Rig Pro did not load in the 'wings' part's Blender"}
    assert rep["multi_arm_export"] == {"status": "skipped",
                                       "reason": "Auto-Rig Pro did not load in the 'multi_arm' part's Blender"}
    assert any("Blender closed by itself" in s for s in said)
    assert str(out) in said[-4] and "send that file back" in said[-3]


def _basics_only(merged_extra: dict):
    """A runner whose basics part returns `merged_extra` on top of a normal head; the rest is empty."""
    def runner(stage, args, log_path, **kw):
        if args["part"] != "basics":
            return {"part": args["part"], "_current": None}
        return {"part": "basics", "_current": None, "blender": {"version": "5.3.0"},
                "arp": {"loaded": True, "version": "3.79.17"}, **merged_extra}
    return runner


def test_result_goes_to_the_jobs_folder_not_into_git(tmp_path, monkeypatch):
    """Inside the git checkout an untracked result file would block the director's next
    `git pull` once the file is committed; the jobs folder is gitignored."""
    monkeypatch.chdir(tmp_path)
    said: list = []
    assert arp_probe.run(["blender"], "jobs", None, say=said.append, runner=_basics_only({})) == 0
    out = (tmp_path / "jobs" / "_setup" / "arp_probe" / "arp_3_79_probe.json").resolve()
    assert json.loads(out.read_text(encoding="utf-8"))["schema"] == arp_probe.SCHEMA_ID
    assert any(str(out) in s for s in said)
    assert not list(tmp_path.glob("**/*.tmp"))
    gitignore = (Path(arp_probe.ROOT) / ".gitignore").read_text()
    assert "jobs/" in gitignore.splitlines()


def test_an_odd_character_never_costs_the_file_or_the_summary(tmp_path):
    """A lone surrogate (what Blender gives for bytes that are not UTF-8) once ended the command
    with a traceback and left a 0-byte file."""
    said: list = []
    odd = "bone_\udcff.l"
    runner = _basics_only({"presets": {"human": {"status": "ok", "armature": odd, "ref_bones": {odd: {}},
                                                 "ref_count": 1}},
                           "errors": [f"presets.dog: KeyError: {odd}"]})
    out = tmp_path / "probe.json"
    assert arp_probe.run(["blender"], str(tmp_path / "jobs"), out, say=said.append, runner=runner) == 0
    rep = json.loads(out.read_text(encoding="utf-8"))
    assert rep["presets"]["human"]["armature"] == odd and odd in rep["presets"]["human"]["ref_bones"]
    assert any(s.strip().startswith("Auto-Rig Pro 3.79.17") for s in said)
    assert str(out) in said[-4]


def test_the_file_is_written_even_when_the_report_cannot_be_laid_out(tmp_path, monkeypatch):
    def broken(merged, parts):
        raise ValueError("cannot lay this out")
    monkeypatch.setattr(arp_probe, "assemble", broken)
    said: list = []
    out = tmp_path / "probe.json"
    arp_probe.run(["blender"], str(tmp_path / "jobs"), out, say=said.append,
                  runner=_basics_only({"presets": {"human": {"status": "ok"}}}))
    rep = json.loads(out.read_text(encoding="utf-8"))
    assert "cannot lay this out" in rep["write_error"]
    assert rep["raw"]["presets"]["human"]["status"] == "ok" and rep["parts"]["basics"]["status"] == "ok"
    assert any("could not be laid out normally" in s for s in said) and str(out) in said[-4]


def test_a_console_that_cannot_print_a_character_does_not_end_the_command(tmp_path):
    said: list = []

    def cp1252_console(line):
        line.encode("cp1252")
        said.append(line)

    runner = _basics_only({"errors": ["x: \u0142\udcff"]})
    out = tmp_path / "\u0142probe.json"
    assert arp_probe.run(["blender"], str(tmp_path / "jobs"), out, say=cp1252_console, runner=runner) == 0
    assert out.exists() and any("send that file back" in s for s in said)


def test_paths_are_shortened_before_the_file_is_shared(tmp_path):
    home, forge = Path("C:\\Users\\Someone"), Path("C:\\Users\\Someone\\Forge")
    text = json.dumps({"a": "C:\\Users\\Someone\\Forge\\jobs\\x.log", "b": "c:/users/someone/AppData/arp",
                       "c": "Blender at C:\\Program Files\\Blender"})
    out = json.loads(arp_probe._scrub(text, [(forge, "<forge>"), (home, "~")]))
    assert out == {"a": "<forge>\\jobs\\x.log", "b": "~/AppData/arp", "c": "Blender at C:\\Program Files\\Blender"}


def test_file_layout_is_compact_and_lossless():
    rep = {"a": {"head": [0.1, -0.2, 1.5], "keys": {}}, "names": [f"bone_{i:03d}.l" for i in range(30)], "n": None}
    text = arp_probe.dumps(rep)
    assert json.loads(text) == rep
    assert '"head": [0.1, -0.2, 1.5]' in text and '\n  "bone_029.l"\n' in text


def test_summary_is_plain_words():
    rep = _all_ok()
    rep["presets"]["bird"] = {"status": "crashed", "reason": "x"}
    lines = arp_probe.summary_lines(rep)
    assert lines[0] == "Auto-Rig Pro 3.79.17, Blender 5.3.0"
    assert "bird: Blender closed (crash)" in lines[1]
    assert lines[2] == f"Checks that worked: {len(arp_probe.SECTIONS)} of {len(arp_probe.SECTIONS)}"
