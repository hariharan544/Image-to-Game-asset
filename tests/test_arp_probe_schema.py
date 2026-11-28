"""The Auto-Rig Pro probe file that Step 8's later work packages read instead of guessing from
the 3.77.33 source mirror. `forge arp-probe` writes it to jobs/_setup/arp_probe/ on the
director's PC (outside git); once sent back it is committed as docs/research/arp_3_79_probe.json.

- The committed file (the director's run of 2026-11-28) has every key they read, and no
  personal folder in any form.
- `forge.arp_probe.validate` really catches missing keys, and the command's merging turns a
  Blender crash or a timeout into recorded results instead of losing the rest.
- Paths are shortened however they are written (Python-printed paths come doubled-escaped).
- `--only` reruns some parts into their own file; no file holding a full result is ever
  overwritten, and the full run's logs stay as they were.
- A --blender path that is not there is explained in plain words, with commands written the way
  the director types them; a Blender folder is taken as the blender.exe in it. Pure Python.
"""

import json
import re
from pathlib import Path, PureWindowsPath

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


def test_committed_probe_file_is_the_directors_run_with_no_personal_folder():
    text = PROBE_FILE.read_text(encoding="utf-8")
    rep = json.loads(text)
    assert (rep["arp"]["version"], rep["blender"]["version"]) == ("3.79.17", "5.3.0")
    assert all(rep["parts"][k]["status"] == "ok" for k in arp_probe.PART_KEYS)
    assert not re.search(r"[A-Za-z]:[\\/]+Users[\\/]", text, re.IGNORECASE)    # in no written form
    assert rep["arp"]["module_dir"].startswith("~") and "<forge>" in text
    # facts Step 8 is built on (docs/research/arp_3_79_findings.md)
    assert rep["presets"]["human"]["ref_bones"]["head_ref.x"]["keys"]["facial"] == 0
    assert all(c["changed_ok"] and c["unexpected_changes"] == {} for c in rep["limb_protocol"]["cases"].values())
    assert "show_limb_params.poll() failed" in rep["multi_arm_export"]["error"]


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
    def broken(merged, parts, only=None):
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


def test_paths_are_shortened_in_every_written_form():
    """Blender and Auto-Rig Pro print some paths as Python strings, which JSON escapes again:
    the director's first file kept the home folder in four FBX export lines that way."""
    home, forge = PureWindowsPath(r"C:\Users\Someone"), PureWindowsPath(r"C:\Users\Someone\Image-to-Game-asset")
    fbx = r"C:\Users\Someone\Image-to-Game-asset\jobs\exports\probe.fbx"
    rep = {"plain": fbx, "printed": f"FBX export starting... {fbx!r}", "slashes": fbx.replace("\\", "/"),
           "home": r"c:\users\someone\AppData\arp", "printed_home": repr(r"C:\Users\Someone\AppData"),
           "longer_name": r"C:\Users\Someone2\x", "other_drive": r"D:\Users\Someone\x"}
    text = arp_probe._scrub(arp_probe.dumps(rep), [(forge, "<forge>"), (home, "~")])
    assert json.loads(text) == {
        "plain": r"<forge>\jobs\exports\probe.fbx",
        "printed": r"FBX export starting... '<forge>\\jobs\\exports\\probe.fbx'",
        "slashes": "<forge>/jobs/exports/probe.fbx", "home": r"~\AppData\arp", "printed_home": r"'~\\AppData'",
        "longer_name": r"C:\Users\Someone2\x", "other_drive": r"D:\Users\Someone\x"}


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


# ----------------------------------------------------------------------------- rerun (--only)

def _parts_runner(seen: list, extra: dict):
    """A runner that records which parts ran and returns `extra[part]` on top of a normal head."""
    def runner(stage, args, log_path, **kw):
        seen.append(args["part"])
        return {"part": args["part"], "_current": None, "blender": {"version": "5.3.0"},
                "arp": {"loaded": True, "version": "3.79.17"}, **extra.get(args["part"], {})}
    return runner


def test_a_rerun_runs_only_the_parts_asked_and_never_replaces_the_full_result(tmp_path):
    work = tmp_path / "jobs" / "_setup" / "arp_probe"
    work.mkdir(parents=True)
    full = work / arp_probe.RESULT_NAME
    full.write_text("the full result", encoding="utf-8")
    seen, said = [], []
    extra = {"multi_arm": {"multi_arm_export": {"status": "ok", "facial": {"facial": "still on"}, "humanoid_check": True,
                                                "exported": True, "dupli_bones_exported": [], "ik_poles": {}}},
             "build": {"build_setup": {"status": "ok", "facial": {"facial": "already off"}}}}
    rc = arp_probe.run(["blender"], str(tmp_path / "jobs"), None, say=said.append,
                       runner=_parts_runner(seen, extra), only=" build, multi_arm")
    assert rc == 0 and seen == ["multi_arm", "build"]                   # in the probe's own order
    assert full.read_text(encoding="utf-8") == "the full result"
    rep = json.loads((work / arp_probe.RERUN_NAME).read_text(encoding="utf-8"))
    assert rep["only"] == ["multi_arm", "build"] and arp_probe.validate(rep) == []
    assert rep["parts"]["basics"] == {"status": "not_run", "reason": arp_probe.NOT_IN_RERUN}
    assert rep["presets"]["human"] == {"status": "not_run", "reason": arp_probe.NOT_IN_RERUN}
    assert rep["chin"]["status"] == "not_run" and "build" in rep["chin"]["reason"]   # ran, recorded nothing
    lines = arp_probe.summary_lines(rep)
    assert lines[1] == "Rerun of: multi_arm, build (the full result file stays as it was)"
    assert not [x for x in lines if x.startswith("Rigs:")]               # no rig part in this rerun
    assert lines[2] == "Checks that worked: 1 of 6"
    assert lines[-1] == ("Face-bones switch: Auto-Rig Pro said no on 1 of 2 test rigs "
                         "(what it saw is in the file)")
    assert any("Rerun of: multi_arm, build" in x for x in said) and str(work / arp_probe.RERUN_NAME) in said[-4]
    # even when told to write over the full result, a rerun writes its own file
    arp_probe.run(["blender"], str(tmp_path / "jobs"), full, say=said.append, runner=_parts_runner([], {}),
                  only=["headless"])
    assert full.read_text(encoding="utf-8") == "the full result"
    assert json.loads((work / arp_probe.RERUN_NAME).read_text(encoding="utf-8"))["only"] == ["headless"]


def test_a_rerun_never_writes_over_any_full_result(tmp_path):
    """--out may name the committed copy (docs/research/arp_3_79_probe.json) or a full result
    saved under another name: the rerun goes next to it."""
    research = tmp_path / "docs" / "research" / arp_probe.RESULT_NAME
    research.parent.mkdir(parents=True)
    research.write_text("the committed full result", encoding="utf-8")
    said: list = []
    assert arp_probe.run(["blender"], str(tmp_path / "jobs"), research, say=said.append,
                         runner=_parts_runner([], {}), only="build") == 0
    assert research.read_text(encoding="utf-8") == "the committed full result"
    assert json.loads((research.parent / arp_probe.RERUN_NAME).read_text(encoding="utf-8"))["only"] == ["build"]
    assert f"A rerun does not write over {arp_probe.RESULT_NAME}" in said[0]
    mine = tmp_path / "mine.json"                           # a full result under another name
    full = arp_probe.assemble(_all_ok(), {k: {"status": "ok"} for k in arp_probe.PART_KEYS})
    mine.write_text(json.dumps(full), encoding="utf-8")
    assert arp_probe.run(["blender"], str(tmp_path / "jobs"), mine, say=said.append,
                         runner=_parts_runner([], {}), only="build") == 0
    assert json.loads(mine.read_text(encoding="utf-8")) == full
    assert json.loads((tmp_path / arp_probe.RERUN_NAME).read_text(encoding="utf-8"))["only"] == ["build"]
    # a rerun file named by --out is simply written
    other = tmp_path / "rerun_again.json"
    assert arp_probe.run(["blender"], str(tmp_path / "jobs"), other, say=said.append,
                         runner=_parts_runner([], {}), only="build") == 0
    assert json.loads(other.read_text(encoding="utf-8"))["only"] == ["build"]
    # the full run's logs stay: a rerun logs to rerun_<part>.log
    logs = tmp_path / "jobs" / "_setup" / "arp_probe" / "logs"
    assert not (logs / "build.log").exists()


def test_only_takes_the_part_names_however_the_console_splits_them():
    assert arp_probe.parse_only("multi_arm,limbs,build") == ["multi_arm", "limbs", "build"]
    assert arp_probe.parse_only(" multi_arm, limbs ,build ") == ["multi_arm", "limbs", "build"]
    assert arp_probe.parse_only(["multi_arm", "limbs", "build"]) == ["multi_arm", "limbs", "build"]
    assert arp_probe.parse_only(["multi_arm,limbs", "build"]) == ["multi_arm", "limbs", "build"]
    assert arp_probe.parse_only(None) == [] and arp_probe.parse_only("") == []


def test_only_on_the_command_line_with_commas_or_spaces(tmp_path, monkeypatch):
    from forge import cli
    got: list = []
    monkeypatch.setattr(arp_probe, "run", lambda blender, jobs, out, only=None: got.append(only) or 0)
    monkeypatch.chdir(tmp_path)
    assert cli.main(["arp-probe", "--only", "multi_arm,limbs,build"]) == 0
    assert cli.main(["arp-probe", "--only", "multi_arm", "limbs", "build"]) == 0
    assert [arp_probe.parse_only(o) for o in got] == [["multi_arm", "limbs", "build"]] * 2


def test_a_rerun_with_a_wrong_part_name_says_which_names_work(tmp_path):
    seen, said = [], []
    assert arp_probe.run(["blender"], str(tmp_path / "jobs"), None, say=said.append,
                         runner=_parts_runner(seen, {}), only="multi_arms,build") == 1
    assert not seen and "multi_arms" in said[0] and "basics,bird,wings,multi_arm,limbs,build,headless" in said[0]
    rep = _all_ok()
    rep["only"] = ["limbs", "tails"]
    assert any(p.startswith("only is") for p in arp_probe.validate(rep))


# ----------------------------------------------------------------------------- Blender path messages

def test_a_blender_path_that_is_not_there_is_explained(tmp_path, monkeypatch, capsys):
    """The director typed the example from a message, C:\\path\\to\\blender.exe, word for word."""
    from forge.cli import main as cli
    monkeypatch.chdir(tmp_path)
    known = tmp_path / "Blender 5.3" / "blender.exe"
    known.parent.mkdir()
    known.write_bytes(b"")
    monkeypatch.setenv("FORGE_BLENDER", str(known))
    assert cli(["arp-probe", "--blender", r"C:\path\to\blender.exe"]) == 1
    said = capsys.readouterr().out
    assert r"There is no blender.exe at C:\path\to\blender.exe" in said
    assert "only an example" in said and "real place of blender.exe" in said
    assert r"C:\Program Files\Blender Foundation\Blender 5.3\blender.exe" in said
    assert "leave --blender out" in said and str(known) in said
    assert not (tmp_path / ".env").exists()                     # a wrong path is not remembered
    # no Blender known either: say how to get one, the way the director types it
    monkeypatch.setattr("forge.blender.find_blender", lambda: None)
    assert cli(["arp-probe", "--blender", r"D:\Apps\blender.exe"]) == 1
    said = capsys.readouterr().out
    assert "only an example" not in said and r"run `.venv\Scripts\forge.exe setup-blender` first" in said


def test_setup_blender_with_a_wrong_path_does_not_send_the_director_round_in_a_circle(tmp_path, monkeypatch, capsys):
    from forge.cli import main as cli
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("forge.blender.find_blender", lambda: None)
    assert cli(["setup-blender", "--blender", r"D:\Apps\Blender\blender.exe"]) == 1
    said = capsys.readouterr().out
    assert "run `forge setup-blender` first" not in said and "setup-blender` first" not in said
    assert "install Blender first (see docs/SETUP_BLENDER.md), then run this again without" in said
    assert not (tmp_path / ".env").exists()


def test_a_blender_folder_is_taken_as_the_blender_exe_in_it(tmp_path, monkeypatch, capsys):
    """The likely next slip after the example path: pasting the folder Blender is in."""
    from forge import blender as B
    from forge.cli import main as cli
    monkeypatch.chdir(tmp_path)
    got: list = []
    monkeypatch.setattr(arp_probe, "run", lambda blender, jobs, out, only=None: got.append(blender) or 0)
    folder = tmp_path / "Blender 5.3"
    folder.mkdir()
    # a folder without blender.exe in it is not a Blender: said, and not saved
    assert cli(["arp-probe", "--blender", "Blender 5.3"]) == 1
    said = capsys.readouterr().out
    assert "There is no blender.exe at Blender 5.3" in said and "That is a folder, and blender.exe is not in it" in said
    assert not got and not (tmp_path / ".env").exists()
    # with blender.exe in it: that file is used and saved, and the director is told
    (folder / "blender.exe").write_bytes(b"")
    assert cli(["arp-probe", "--blender", "Blender 5.3"]) == 0
    exe = str(folder / "blender.exe")
    assert got == [[exe]] and f"using the blender.exe in it, {exe}" in capsys.readouterr().out
    assert (tmp_path / ".env").read_text(encoding="utf-8").strip() == f"FORGE_BLENDER={exe}"
    assert cli(["arp-probe", "--blender", exe]) == 0                  # the file itself: no note
    assert got[-1] == [exe] and "That is the Blender folder" not in capsys.readouterr().out
    # a folder saved by an older Forge is read as the blender.exe in it, and a folder is never "known"
    monkeypatch.setenv("FORGE_BLENDER", str(folder))
    assert B.find_blender() == [exe] and B.known_blender() == exe
    (folder / "blender.exe").unlink()
    assert B.known_blender() is None
    assert B.blender_file(tmp_path / "nothing here") is None


def test_blender_not_found_says_the_path_shown_is_an_example(tmp_path, monkeypatch):
    monkeypatch.setattr(arp_probe, "find_blender", lambda: None)
    said: list = []
    assert arp_probe.run(None, str(tmp_path / "jobs"), say=said.append) == 1
    text = "\n".join(said)
    assert "could not find Blender" in text and "that is an example" in text
    assert '--blender "C:\\Program Files\\Blender Foundation\\Blender 5.3\\blender.exe"' in text
    assert "path\\to" not in text
