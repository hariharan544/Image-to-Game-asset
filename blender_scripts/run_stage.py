"""Headless entry point for one Forge stage.

Run inside Blender:
    blender -b [input.blend] -P run_stage.py -- <stage> <args.json> <result.json>
or with the `bpy` Python module (used by the tests):
    python run_stage.py <stage> <args.json> <result.json>

args.json may contain "load_blend" (start from this file) and "save_blend"
(write the scene here after the stage). The stage result (metrics) is written
to result.json as {"ok": true, "result": {...}} or {"ok": false, "error": "..."}.
"""

from __future__ import annotations

import json
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bpy  # noqa: E402

from forge_bpy import addon_probe, bake, cleanup, finalize, fixture, metrics, retopo, skin, sysinfo, uv  # noqa: E402

STAGES = {
    "cleanup": cleanup.run,
    "retopo": retopo.run,
    "uv": uv.run,
    "bake": bake.run,
    "skin": skin.run,
    "lods": finalize.lods,
    "metrics": metrics.collect,
    "previews": finalize.previews,
    "export": finalize.export,
    "sysinfo": sysinfo.run,
    "fixture": fixture.run,
    "addon_probe": addon_probe.run,
}


def _argv() -> list[str]:
    if "--" in sys.argv:
        return sys.argv[sys.argv.index("--") + 1:]
    return sys.argv[1:]


def main() -> int:
    stage, args_path, result_path = _argv()[:3]
    with open(args_path, encoding="utf-8") as f:
        args = json.load(f)
    try:
        if args.get("load_blend"):
            bpy.ops.wm.open_mainfile(filepath=args["load_blend"])
        result = STAGES[stage](args)
        if args.get("save_blend"):
            os.makedirs(os.path.dirname(os.path.abspath(args["save_blend"])), exist_ok=True)
            bpy.ops.wm.save_as_mainfile(filepath=args["save_blend"], compress=True)
        payload = {"ok": True, "stage": stage, "result": result}
        code = 0
    except Exception as exc:  # report every failure to the orchestrator
        payload = {"ok": False, "stage": stage, "error": f"{type(exc).__name__}: {exc}",
                   "traceback": traceback.format_exc()}
        code = 1
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    return code


if __name__ == "__main__":
    rc = main()
    if bpy.app.background:
        sys.exit(rc)
