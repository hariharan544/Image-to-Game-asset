"""Entry point for one Forge stage, headless or windowed.

Headless (normal):
    blender -b [--factory-startup] -P run_stage.py -- <stage> <args.json> <result.json>
Windowed (add-ons that need the GPU/UI or run an external engine asynchronously,
e.g. UVPackmaster, Quad Remesher):
    blender [--factory-startup] --window-geometry ... -P run_stage.py -- <stage> <args.json> <result.json>
    The stage runs from a timer once the UI is up; Blender quits by itself afterwards.
With the `bpy` Python module (tests):
    python run_stage.py <stage> <args.json> <result.json>

args.json may contain "load_blend" (start from this file) and "save_blend" (write the
scene here after the stage). The result goes to result.json as
{"ok": true, "result": {...}} or {"ok": false, "error": "..."}.

A stage function may return a plain dict, or be a *generator*: it yields the number of
seconds to wait (letting Blender's event loop run, so add-on engines and timers work)
and finally returns its result dict.
"""

from __future__ import annotations

import inspect
import json
import os
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bpy  # noqa: E402

from forge_bpy import (addon_probe, addon_trial, bake, cleanup, finalize, fixture,  # noqa: E402
                       metrics, retopo, skin, sysinfo, uv)

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
    "addon_trial": addon_trial.run,
}


def _argv() -> list[str]:
    if "--" in sys.argv:
        return sys.argv[sys.argv.index("--") + 1:]
    return sys.argv[1:]


def _write(result_path: str, payload: dict) -> None:
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)


def _finish(args: dict, stage: str, result_path: str, result: dict) -> int:
    if args.get("save_blend"):
        os.makedirs(os.path.dirname(os.path.abspath(args["save_blend"])), exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=args["save_blend"], compress=True)
    _write(result_path, {"ok": True, "stage": stage, "result": result})
    return 0


def _error(stage: str, result_path: str, exc: BaseException) -> int:
    _write(result_path, {"ok": False, "stage": stage, "error": f"{type(exc).__name__}: {exc}",
                         "traceback": traceback.format_exc()})
    return 1


def _start(stage: str, args: dict):
    if args.get("load_blend"):
        bpy.ops.wm.open_mainfile(filepath=args["load_blend"])
    return STAGES[stage](args)


def run_background(stage: str, args: dict, result_path: str) -> int:
    try:
        out = _start(stage, args)
        if inspect.isgenerator(out):          # no event loop here: just wait between steps
            try:
                while True:
                    time.sleep(float(next(out) or 0.1))
            except StopIteration as stop:
                out = stop.value or {}
        return _finish(args, stage, result_path, out)
    except Exception as exc:  # report every failure to the orchestrator
        return _error(stage, result_path, exc)


def run_windowed(stage: str, args: dict, result_path: str) -> None:
    """Drive the stage from a persistent timer so Blender's UI/event loop keeps running."""
    state: dict = {"gen": None}

    def quit_now(code: int) -> None:
        sys.stdout.flush()
        os._exit(code)          # hard exit: no "save changes?" prompt, preferences untouched

    def tick():
        try:
            if state["gen"] is None:
                out = _start(stage, args)
                if not inspect.isgenerator(out):
                    quit_now(_finish(args, stage, result_path, out))
                state["gen"] = out
            return float(next(state["gen"]) or 0.1)
        except StopIteration as stop:
            quit_now(_finish(args, stage, result_path, stop.value or {}))
        except Exception as exc:
            quit_now(_error(stage, result_path, exc))
        return None

    bpy.app.timers.register(tick, first_interval=1.0, persistent=True)


def main() -> None:
    stage, args_path, result_path = _argv()[:3]
    with open(args_path, encoding="utf-8") as f:
        args = json.load(f)
    if bpy.app.background:
        sys.exit(run_background(stage, args, result_path))
    run_windowed(stage, args, result_path)   # returns; Blender's UI loop drives the timer


if __name__ == "__main__":
    main()
