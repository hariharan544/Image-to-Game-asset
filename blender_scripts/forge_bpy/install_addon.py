"""Stage: install + enable the Forge "Send to Forge" add-on in the user's Blender.

Copies blender_addon/forge_send into the user's scripts/addons folder, writes
forge_project.json (project folder + forge executable) next to it, enables the add-on
and saves the preferences. Run WITHOUT --factory-startup and with Blender closed
(an open Blender would overwrite the saved preferences when it quits).
"""

from __future__ import annotations

import json
import os
import shutil
import sys

import addon_utils
import bpy


def run(args: dict) -> dict:
    src = os.path.abspath(args["src"])
    name = os.path.basename(src.rstrip("/\\"))
    root = bpy.utils.user_resource("SCRIPTS", path="addons", create=True)
    dst = os.path.join(root, name)
    if addon_utils.check(name)[1]:
        addon_utils.disable(name, default_set=True)
    shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    # the step-by-step panel runs the pipeline's stage code inside Blender: ship a copy
    shutil.copytree(os.path.dirname(os.path.abspath(__file__)), os.path.join(dst, "forge_bpy"),
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    with open(os.path.join(dst, "forge_project.json"), "w", encoding="utf-8") as f:
        json.dump({"project": args["project"], "forge": args.get("forge_exe")}, f, indent=2)
    # a scripts/addons folder created just now is not on Blender's import path yet
    if root not in sys.path:
        sys.path.append(root)
    addon_utils.modules_refresh()
    errors = []
    addon_utils.enable(name, default_set=True, persistent=True, handle_error=lambda e: errors.append(str(e)))
    enabled = addon_utils.check(name)[1]
    if enabled:
        bpy.ops.wm.save_userpref()
    return {"installed_to": dst, "enabled": enabled, "errors": errors[:3]}
