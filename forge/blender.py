"""Run one Blender stage headless and return its result.

Blender is found via (first hit wins):
  1. FORGE_BLENDER env var (path to blender.exe)
  2. newest  C:/Program Files/Blender Foundation/Blender */blender.exe  (Windows)
  3. `blender` on PATH
  4. the `bpy` pip module in the current Python (dev / CI only)
"""

from __future__ import annotations

import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

SCRIPT = Path(__file__).resolve().parent.parent / "blender_scripts" / "run_stage.py"


class BlenderError(RuntimeError):
    pass


def _version_key(path: str) -> tuple:
    m = re.search(r"Blender (\d+)\.(\d+)", path)
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def find_blender() -> Optional[list[str]]:
    env = os.environ.get("FORGE_BLENDER")
    if env:
        return [env]
    candidates = glob.glob(r"C:/Program Files/Blender Foundation/Blender */blender.exe")
    if candidates:
        return [max(candidates, key=_version_key)]
    exe = shutil.which("blender")
    if exe:
        return [exe]
    try:
        import importlib.util
        if importlib.util.find_spec("bpy") is not None:
            return [sys.executable]
    except (ImportError, ValueError):
        pass
    return None


# where the Blender installer puts it on Windows (the version number follows the release)
USUAL_BLENDER = r"C:\Program Files\Blender Foundation\Blender 5.3\blender.exe"


def known_blender() -> Optional[str]:
    """The Blender Forge would use without --blender, if it is really there."""
    b = find_blender()
    return b[0] if b and Path(b[0]).exists() else None


def no_such_blender_lines(path: str, known: Optional[str]) -> list[str]:
    """What to say when --blender names a file that is not there. The director once typed the
    example from a message, C:\\path\\to\\blender.exe, word for word: say it was an example."""
    lines = [f"[X] There is no blender.exe at {path}"]
    if "path\\to\\" in str(path).replace("/", "\\").lower():
        lines.append("    (That path was only an example of how to write it.)")
    lines += ["    After --blender, give the real place of blender.exe on this PC. It is usually:",
              f"      \"{USUAL_BLENDER}\"",
              "      (the version number in the folder name may differ)."]
    if known:
        lines += ["    Or leave --blender out: Forge then uses the Blender it already knows:", f"      {known}"]
    else:
        lines.append("    Forge does not know a Blender on this PC yet: run `forge setup-blender` first.")
    return lines


def blender_not_found_lines(command: str) -> list[str]:
    """What to say when no Blender was given and none was found (the path shown is an example)."""
    return ["[X] Forge could not find Blender on this PC.",
            f"    Install it (see docs/SETUP_BLENDER.md), then run `{command}` again. If Blender is",
            "    installed somewhere unusual, add --blender with the real place of blender.exe,",
            f"    for example: --blender \"{USUAL_BLENDER}\"",
            "    (that is an example: use the folder Blender is in on your PC)."]


def run_stage(stage: str, args: dict, log_path: Path, timeout: float = 3600,
              blender: Optional[list[str]] = None, factory_startup: bool = True,
              windowed: bool = False) -> dict:
    """factory_startup=True ignores the user's Blender preferences/add-ons, so pipeline
    results are reproducible. sysinfo runs with False to see the real setup.
    windowed=True opens a small Blender window (needed by add-ons that require the GPU/UI,
    e.g. UVPackmaster, or that run an external engine, e.g. Quad Remesher); it closes itself."""
    cmd_base = blender or find_blender()
    if not cmd_base:
        raise BlenderError("Blender not found. Install Blender 4.2+ or set FORGE_BLENDER to blender.exe")
    with tempfile.TemporaryDirectory(prefix="forge_") as tmp:
        a = Path(tmp) / "args.json"
        r = Path(tmp) / "result.json"
        a.write_text(json.dumps(args), encoding="utf-8")
        if cmd_base[0] == sys.executable and "blender" not in Path(cmd_base[0]).name.lower():
            cmd = [*cmd_base, str(SCRIPT), stage, str(a), str(r)]
        else:
            mode = ["--window-geometry", "40", "40", "960", "600", "--no-window-focus"] if windowed else ["-b"]
            cmd = [*cmd_base, *mode, *(["--factory-startup"] if factory_startup else []),
                   "-P", str(SCRIPT), "--", stage, str(a), str(r)]
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "w", encoding="utf-8") as log:
            try:
                proc = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, timeout=timeout)
            except subprocess.TimeoutExpired as exc:
                raise BlenderError(f"stage {stage} timed out after {timeout}s") from exc
        if not r.exists():
            raise BlenderError(f"stage {stage} crashed (exit {proc.returncode}); see {log_path}")
        payload = json.loads(r.read_text(encoding="utf-8"))
    if not payload.get("ok"):
        raise BlenderError(f"stage {stage} failed: {payload.get('error')}\n{payload.get('traceback', '')}")
    return payload["result"]
