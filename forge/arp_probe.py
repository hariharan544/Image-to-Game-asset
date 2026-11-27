"""`forge arp-probe`: record how the director's own Auto-Rig Pro behaves (Step 8, WP0).

The new Step 8 (rig brief card + point-and-click joints) leans on Auto-Rig Pro facts that were
read from an older ARP (3.77.33). This command checks them in the director's Blender and ARP and
writes them to jobs/_setup/arp_probe/arp_3_79_probe.json (outside git, so the director's next
`git pull` is never blocked by it). The director sends that file back and it is committed as
docs/research/arp_3_79_probe.json, which the later work packages read instead of guessing. It
changes no Forge behaviour: every part runs in a fresh, throwaway Blender scene and nothing is
saved into any .blend file or into Blender's preferences.

Each part runs in its own Blender process, so one crash (ARP's bird preset is known to crash
some Blender 5 builds) does not lose the rest. A part writes what it has found after every
item; when its Blender dies, the item it was busy with is recorded as "crashed".

The Blender side is `blender_scripts/forge_bpy/addon_trial.py` (`run_rig_probe`).
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from .blender import find_blender, run_stage

ROOT = Path(__file__).resolve().parent.parent
RESULT_NAME = "arp_3_79_probe.json"         # written to <jobs>/_setup/arp_probe/ (gitignored)
COMMITTED = ROOT / "docs" / "research" / RESULT_NAME    # where it goes once the director sent it
SCHEMA_ID = "forge.arp_probe/1"

# (key, words for the director, needs a window, timeout in seconds)
PARTS = (
    ("basics", "Auto-Rig Pro version, options, and the human, dog, horse and free rigs", True, 600),
    ("bird", "The bird rig, in its own window in case it crashes Blender", True, 300),
    ("wings", "Wings on an extra arm, in its own window in case it crashes Blender", True, 600),
    ("multi_arm", "A second pair of arms (skin and export), and the dog rig's knee and elbow controls", True, 900),
    ("limbs", "Extra tails, ears, arms and chains", True, 900),
    ("build", "A test character: build, skin twice, export four ways", True, 1800),
    ("headless", "Auto-Rig Pro without a window", False, 300),
)
PART_KEYS = tuple(p[0] for p in PARTS)

PRESETS = ("human", "dog", "horse", "bird", "free")
PRESET_PART = {"human": "basics", "dog": "basics", "horse": "basics", "free": "basics", "bird": "bird"}
PRESET_KEYS = ("armature", "ref_bones", "ref_count")

# section -> (part that records it, keys later work packages read when status == "ok")
SECTIONS = {
    "operators": ("basics", ("ops", "arp_ops")),
    "scene_props": ("basics", ("props",)),
    "limb_options": ("basics", ("properties", "expected_present", "missing_expected")),
    "spine_count": ("basics", ("human",)),
    "scale_fix": ("basics", ("prop", "exists", "default")),
    "humanoid_check": ("basics", ("reachable", "results")),
    "multi_arm_export": ("multi_arm", ("humanoid_check", "exported", "dupli_bones_exported", "ik_poles")),
    "wings": ("wings", ("arm_wings_set", "match_ok", "feather_bones")),
    "load_limb_settings": ("limbs", ("module", "keys_in_source", "per_limb")),
    "ref_bone_keys": ("limbs", ("bones", "keys_seen")),
    "limb_protocol": ("limbs", ("cases",)),
    "add_limb": ("limbs", ("presets_items", "cases")),
    "deform_names": ("build", ("deform_bones", "owner_bones")),
    "ik_poles": ("build", ("pole_bones", "expected", "ik_constraints")),
    "chin": ("build", ("keys_read", "weights_changed", "arp_bind_chin")),
    "bind": ("build", ("engine_items", "preserve_volume_prop", "modifier_preserve_volume",
                       "scale_fix_prop", "heat_map", "pseudo_voxels")),
    "socket_export": ("build", ("variants",)),
    "headless": ("headless", ("append_ok", "match_ok")),
}
# dict-of-cases inside a section: (section, field, keys every "ok" case has)
NESTED = (
    ("add_limb", "cases", ("new_ref_bones",)),
    ("limb_protocol", "cases", ("changed_ok", "unexpected_changes")),
    ("load_limb_settings", "per_limb", ("ref", "limb_type", "values")),
    ("humanoid_check", "results", ("humanoid",)),
    ("socket_export", "variants", ("exported", "socket")),
    ("ik_poles", "rigs", ("pole_bones", "dupli_poles", "ik_constraints")),
)
# one named entry inside a section, checked when it is there: (section, field, keys when "ok")
SUBS = (
    ("add_limb", "after_match", ("deform_count", "ik_poles")),
)
STATUSES = {"ok", "error", "skipped", "crashed", "not_run", "timeout", "partial"}
PART_STATUSES = {"ok", "error", "crashed", "timeout", "skipped", "not_run"}
NO_ARP = "Auto-Rig Pro is not loaded in this Blender"

WORDS = {"ok": "worked", "error": "failed", "skipped": "skipped", "crashed": "Blender closed (crash)",
         "not_run": "not reached", "timeout": "took too long", "partial": "partly recorded"}


# ----------------------------------------------------------------------------- merging

def _deep_merge(dst: dict, src: dict) -> dict:
    for k, v in src.items():
        if k == "errors" and isinstance(v, list):
            dst.setdefault("errors", []).extend(v)
        elif isinstance(v, dict) and isinstance(dst.get(k), dict):
            _deep_merge(dst[k], v)
        else:
            dst[k] = v
    return dst


def _set_path(d: dict, path: str, value) -> None:
    keys = path.split(".")
    for k in keys[:-1]:
        if not isinstance(d.get(k), dict):
            d[k] = {}
        d = d[k]
    old = d.get(keys[-1])
    d[keys[-1]] = {**old, **value} if isinstance(old, dict) and isinstance(value, dict) else value


def _read_partial(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _log_tail(path: Path, n: int = 40) -> list[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
    except OSError:
        return []


def _missing(part: str, parts: dict, arp_loaded=None) -> dict:
    st = parts.get(part)
    if arp_loaded is False:
        return {"status": "skipped", "reason": NO_ARP}
    if st is None:
        return {"status": "not_run", "reason": f"the '{part}' part did not run"}
    if st["status"] == "skipped":
        return {"status": "skipped", "reason": st.get("reason", NO_ARP)}
    if st.get("arp_loaded") is False:
        return {"status": "skipped", "reason": f"Auto-Rig Pro did not load in the '{part}' part's Blender"}
    if st["status"] == "ok":
        return {"status": "not_run", "reason": f"the '{part}' part finished without recording this"}
    return {"status": "not_run",
            "reason": f"Blender stopped during the '{part}' part ({st['status']}) before this was reached"}


def assemble(merged: dict, parts: dict) -> dict:
    """The final report: fixed top-level keys, every section present with a status."""
    rep = {"schema": SCHEMA_ID,
           "written_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "blender": merged.get("blender", {}),
           "arp": merged.get("arp", {"loaded": None}),
           "parts": parts}
    loaded = rep["arp"].get("loaded")
    presets = dict(merged.get("presets", {}))
    for name in PRESETS:
        if not isinstance(presets.get(name), dict) or "status" not in presets[name]:
            presets[name] = {**(presets.get(name) or {}), **_missing(PRESET_PART[name], parts, loaded)}
    rep["presets"] = presets
    for name, (part, _keys) in SECTIONS.items():
        sec = merged.get(name)
        if not isinstance(sec, dict) or not sec:
            sec = _missing(part, parts, loaded)
        elif "status" not in sec:
            sec = {"status": "partial", "reason": f"the '{part}' part did not record this", **sec}
        rep[name] = sec
    known = set(rep) | {"part", "_current", "errors"}
    rep["extra"] = {k: v for k, v in merged.items() if k not in known}
    rep["errors"] = list(merged.get("errors", []))
    rep["notes"] = ("Each section and preset has a status: ok, error (with 'error'), skipped, crashed, "
                    "not_run or timeout (with 'reason'). A crash or an error is a result too. "
                    "Paths are shortened: <forge> is the Forge folder, ~ the user's home folder.")
    return rep


# ----------------------------------------------------------------------------- schema

def _check_entry(where: str, e, keys, problems: list) -> None:
    if not isinstance(e, dict):
        problems.append(f"{where}: missing")
        return
    st = e.get("status")
    if st not in STATUSES:
        problems.append(f"{where}: status {st!r} is not one of {sorted(STATUSES)}")
    elif st == "ok":
        problems += [f"{where}: '{k}' missing" for k in keys if k not in e]
    elif st == "error" and not isinstance(e.get("error"), str):
        problems.append(f"{where}: an error without its message")
    elif st not in ("ok", "error", "partial") and not isinstance(e.get("reason"), str):
        problems.append(f"{where}: status {st} without a reason")


def validate(rep: dict, require_arp: bool = False) -> list[str]:
    """Problems with a probe report (empty list = every key later work packages read is there)."""
    p: list[str] = []
    if rep.get("schema") != SCHEMA_ID:
        p.append(f"schema is {rep.get('schema')!r}, expected {SCHEMA_ID!r}")
    for k in ("written_at", "blender", "arp", "parts", "presets", "errors"):
        if k not in rep:
            p.append(f"'{k}' missing")
    if not (rep.get("blender") or {}).get("version"):
        p.append("blender.version missing")
    arp = rep.get("arp") or {}
    if "loaded" not in arp:
        p.append("arp.loaded missing")
    if require_arp and arp.get("loaded") is not True:
        p.append("Auto-Rig Pro was not loaded when the probe ran")
    if arp.get("loaded") and not arp.get("version"):
        p.append("arp.version missing")
    parts = rep.get("parts") or {}
    for k in PART_KEYS:
        if (parts.get(k) or {}).get("status") not in PART_STATUSES:
            p.append(f"parts.{k}: missing or unknown status")
    presets = rep.get("presets") or {}
    for name in PRESETS:
        _check_entry(f"presets.{name}", presets.get(name), PRESET_KEYS, p)
        e = presets.get(name) or {}
        if e.get("status") == "ok" and not isinstance(e.get("ref_bones"), dict):
            p.append(f"presets.{name}.ref_bones is not a dict")
    for name, (_part, keys) in SECTIONS.items():
        _check_entry(name, rep.get(name), keys, p)
    for sec, field, keys in NESTED:
        s = rep.get(sec) or {}
        if s.get("status") not in ("ok", "partial") or not isinstance(s.get(field), dict):
            continue
        for case, e in s[field].items():
            _check_entry(f"{sec}.{field}.{case}", e, keys, p)
    for sec, field, keys in SUBS:
        s = rep.get(sec) or {}
        if s.get("status") in ("ok", "partial") and field in s:
            _check_entry(f"{sec}.{field}", s[field], keys, p)
    if not isinstance(rep.get("errors", []), list):
        p.append("errors is not a list")
    return p


# ----------------------------------------------------------------------------- words

def dumps(o, ind: int = 0, width: int = 100) -> str:
    """JSON with one key per line, but short lists and dicts kept on one line (vectors, names)."""
    flat = json.dumps(o, ensure_ascii=True, default=str)       # ASCII: any odd character is escaped
    if not isinstance(o, (dict, list)) or len(flat) + ind <= width or not o:
        return flat
    pad = " " * (ind + 1)
    if isinstance(o, dict):
        body = ",\n".join(f"{pad}{json.dumps(str(k), ensure_ascii=True)}: {dumps(v, ind + 1, width)}"
                          for k, v in o.items())
        return "{\n" + body + "\n" + " " * ind + "}"
    return "[\n" + ",\n".join(pad + dumps(v, ind + 1, width) for v in o) + "\n" + " " * ind + "]"


def _scrub(text: str, roots: list) -> str:
    """Replace the Forge folder and the home folder with placeholders (the file is shared)."""
    for root, label in roots:
        variants = {str(root), str(root).replace("\\", "/"), str(root).replace("/", "\\")}
        for v in sorted(variants, key=len, reverse=True):
            if len(v) < 4:
                continue
            for form in (v, json.dumps(v)[1:-1]):
                text = re.sub(re.escape(form), lambda _m: label, text, flags=re.IGNORECASE)
    return text


def summary_lines(rep: dict) -> list[str]:
    a, b = rep.get("arp") or {}, rep.get("blender") or {}
    arp = f"Auto-Rig Pro {a.get('version') or '?'}" if a.get("loaded") else "Auto-Rig Pro: not loaded"
    out = [f"{arp}, Blender {b.get('version') or '?'}"]
    rigs = []
    for name in PRESETS:
        e = rep.get("presets", {}).get(name) or {}
        n = e.get("ref_count")
        rigs.append(f"{name} {n} reference bone{'' if n == 1 else 's'}" if e.get("status") == "ok"
                    else f"{name}: {WORDS.get(e.get('status'), e.get('status'))}")
    out.append("Rigs: " + ", ".join(rigs))
    good = [s for s in SECTIONS if (rep.get(s) or {}).get("status") == "ok"]
    out.append(f"Checks that worked: {len(good)} of {len(SECTIONS)}")
    bad = [f"{s} ({WORDS.get(rep[s].get('status'), rep[s].get('status'))})" for s in SECTIONS
           if (rep.get(s) or {}).get("status") != "ok"]
    if bad:
        out.append("Checks that did not work (that is useful to know too): " + ", ".join(bad))
    return out


# ----------------------------------------------------------------------------- command

def _safe_say(say: Callable[[str], None]) -> Callable[[str], None]:
    """A console that cannot print a character must not end the command (Windows code pages)."""
    def s(line: str) -> None:
        try:
            say(line)
        except UnicodeError:
            say(line.encode("ascii", "backslashreplace").decode("ascii"))
    return s


def _report_text(merged: dict, parts: dict) -> tuple[str, Optional[str]]:
    """The result file's text, and what went wrong making it (None when nothing did). Never
    raises: when the full report cannot be put together, a plainer one still keeps the data."""
    roots = [(ROOT, "<forge>"), (Path.home(), "~")]
    try:
        return _scrub(dumps(assemble(merged, parts)), roots), None
    except Exception as exc:                    # noqa: BLE001
        problem = f"{type(exc).__name__}: {exc}"[:300]
    try:
        raw = json.dumps({"schema": SCHEMA_ID, "write_error": problem, "parts": parts, "raw": merged},
                         ensure_ascii=True, default=repr, skipkeys=True, indent=1)
        return _scrub(raw, roots), problem
    except Exception as exc:                    # noqa: BLE001
        return json.dumps({"schema": SCHEMA_ID, "write_error": problem, "second_error": str(exc)[:300],
                           "parts": {k: str(v)[:2000] for k, v in parts.items()}}, ensure_ascii=True), problem


def _write(targets: list, text: str, say: Callable[[str], None]) -> Optional[Path]:
    """Write the file (through a temporary file, so it is never left empty). Returns where."""
    for target in dict.fromkeys(targets):
        tmp = target.with_name(target.name + ".tmp")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(text + "\n", encoding="utf-8", errors="backslashreplace")
            os.replace(tmp, target)
            return target
        except Exception as exc:                # noqa: BLE001
            say(f"[!] Could not write {target}: {exc}")
    return None


def run(blender: Optional[list[str]], jobs_dir: str, out_path: Optional[Path] = None,
        say: Callable[[str], None] = print, runner: Callable = run_stage) -> int:
    t_start = time.time()
    say = _safe_say(say)
    blender = blender or find_blender()
    if not blender:
        say("[X] Blender was not found. Run `forge setup-blender` first, or add --blender \"C:\\path\\to\\blender.exe\".")
        return 1
    work = (Path(jobs_dir) / "_setup" / "arp_probe").resolve()     # Blender must never see relative paths
    out = Path(out_path) if out_path else work / RESULT_NAME
    logs, exports = work / "logs", work / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    logs.mkdir(parents=True, exist_ok=True)
    say("Auto-Rig Pro check for the new Step 8.")
    say(f"Blender windows open and close by themselves {sum(1 for p in PARTS if p[2])} times "
        "(about 5 minutes, up to 15 on a slow PC).")
    say("Please don't close them or click in them. Your own Blender files and settings are not changed.")

    merged: dict = {}
    parts: dict = {}
    arp_missing = False
    for i, (key, label, windowed, timeout) in enumerate(PARTS, 1):
        if arp_missing:
            parts[key] = {"status": "skipped", "reason": NO_ARP}
            continue
        say(f"  [{i}/{len(PARTS)}] {label} ...")
        partial = work / f"{key}.partial.json"
        partial.unlink(missing_ok=True)
        log = logs / f"{key}.log"
        t0 = time.time()
        try:
            rep = runner("arp_probe", {"part": key, "partial": str(partial), "out_dir": str(exports),
                                       "ensure_addons": ["auto-rig pro", "auto_rig_pro"]},
                         log, blender=blender, factory_startup=False, windowed=windowed, timeout=timeout)
            st = {"status": "ok"}
        except Exception as exc:                # noqa: BLE001 - a failed part is a result, never the end
            rep = _read_partial(partial)
            first = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
            status = "timeout" if "timed out" in first else ("crashed" if "crashed" in first else "error")
            st = {"status": status, "message": first, "stopped_at": rep.get("_current"),
                  "log_tail": _log_tail(log)}
            if rep.get("_current"):
                _set_path(rep, rep["_current"], {
                    "status": "crashed" if status == "crashed" else "timeout" if status == "timeout" else "error",
                    "reason": f"Blender stopped while doing this ({first})", "error": first})
        head_arp = None
        try:
            rep = dict(rep or {})
            rep.pop("_current", None)
            rep.pop("part", None)
            head_arp, head_blender = rep.pop("arp", None), rep.pop("blender", None)
            if isinstance(head_arp, dict):      # the version facts come from the first part that has them
                st["arp_loaded"] = head_arp.get("loaded")
                if "arp" not in merged or key == "basics":
                    merged["arp"] = head_arp
            if isinstance(head_blender, dict) and ("blender" not in merged or key == "basics"):
                merged["blender"] = head_blender
            _deep_merge(merged, rep)
        except Exception as exc:                # noqa: BLE001 - what this part found could not be merged
            st = {**st, "status": "error" if st["status"] == "ok" else st["status"],
                  "message": st.get("message") or f"its result could not be read: {type(exc).__name__}: {exc}"[:300]}
        st["seconds"] = round(time.time() - t0, 1)
        st["log"] = f"_setup/arp_probe/logs/{key}.log (in the jobs folder)"
        parts[key] = st
        if st["status"] == "ok":
            say(f"        ok ({st['seconds']:.0f} s)")
        else:
            say(f"  [!] {'Blender closed by itself' if st['status'] == 'crashed' else 'This part stopped'}: "
                f"{st['message'][:160]}")
            say("      That is a result too - it is recorded in the file. Carrying on.")
        if key == "basics" and st.get("arp_loaded") is False:
            arp_missing = True
            a = head_arp or {}
            say(f"[X] Auto-Rig Pro is not turned on in this Blender ({blender[0]}).")
            if a.get("enable_error"):
                say(f"    Blender said: {str(a['enable_error'])[:200]}")
            say("    In Blender: Edit > Preferences > Add-ons, search for Auto-Rig Pro and tick it,")
            say("    then run this command again. (The file below is still written.)")

    # from here on nothing may stop the file being written or the plain-words summary being shown
    text, write_error = _report_text(merged, parts)
    written = _write([out, work / RESULT_NAME], text, say)
    try:
        report = json.loads(text)
        problems = validate(report)
        lines = summary_lines(report)
    except Exception as exc:                    # noqa: BLE001
        problems, lines = [f"the summary could not be read back ({type(exc).__name__})"], []
    say("")
    for line in lines:
        say("   " + line)
    if write_error:
        say(f"[!] Part of the result could not be laid out normally ({write_error[:160]}).")
        say("    The file still has everything that was found.")
    if problems:
        say(f"[!] The result file is missing {len(problems)} expected entries (first: {problems[0]}).")
    minutes, seconds = divmod(int(time.time() - t_start), 60)
    say("")
    if written is None:
        say(f"[X] Finished in {minutes} min {seconds} s, but the result file could not be saved (see above).")
        say("    Please copy every line of this window into your message instead.")
        return 1
    say(f"{'[X]' if arp_missing else '[OK]'} Finished in {minutes} min {seconds} s. The result file is:")
    say(f"     {written}")
    say("Please send that file back: attach it, or open it in Notepad, select all, copy and paste it.")
    say("If any line above starts with [X] or [!], copy those lines into your message too.")
    say("Nothing in your own Blender files or settings was changed.")
    return 1 if arp_missing else 0
