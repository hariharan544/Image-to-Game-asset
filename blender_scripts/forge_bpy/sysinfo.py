"""Stage: report what this Blender install can do (version, GPU for Cycles, add-ons).

Run WITHOUT --factory-startup so the user's preferences (enabled add-ons,
GPU settings) are visible.
"""

from __future__ import annotations

import sys

import addon_utils
import bpy

# substrings of add-on module names -> the tools Forge will drive in later phases
KNOWN_ADDONS = {   # matched against "module name + display name", lower-case
    "quad_remesher": ("quad remesher", "quad_remesh", "quadremesh", "qremesh"),
    "auto_rig_pro": ("auto-rig pro", "auto_rig_pro", "auto-rig-pro", "autorigpro"),
    "uvpackmaster": ("uvpackmaster", "uvpm"),
    "smart_remesh": ("smart remesh", "smart_remesh", "smartremesh"),
    "uvgami": ("uvgami",),
}


def _cycles_devices() -> dict:
    out = {}
    try:
        prefs = bpy.context.preferences.addons["cycles"].preferences
    except KeyError:
        return {"error": "cycles add-on not available"}
    for backend in ("OPTIX", "CUDA", "HIP", "ONEAPI", "METAL"):
        try:
            prefs.compute_device_type = backend
        except TypeError:
            continue
        prefs.get_devices()
        names = [d.name for d in prefs.devices if d.type == backend]
        if names:
            out[backend] = names
    return out


def run(args: dict) -> dict:
    mods = list(addon_utils.modules())
    label = {m.__name__: (m.__name__ + " " + addon_utils.module_bl_info(m).get("name", "")).lower() for m in mods}
    prefs_on = set(bpy.context.preferences.addons.keys())     # ticked in the *saved* preferences
    enabled = sorted(n for n in label if addon_utils.check(n)[1] or n in prefs_on)
    installed = sorted(label)
    detected = {}
    for key, needles in KNOWN_ADDONS.items():
        hit_enabled = [n for n in enabled if any(s in label[n] for s in needles)]
        hit_installed = [n for n in installed if any(s in label[n] for s in needles)]
        detected[key] = {"enabled": bool(hit_enabled), "installed": bool(hit_installed),
                         "module": (hit_enabled or hit_installed or [None])[0]}
    devices = _cycles_devices()
    return {
        "blender_version": bpy.app.version_string,
        "version_tuple": list(bpy.app.version),
        "python": sys.version.split()[0],
        "background": bpy.app.background,
        "cycles_devices": devices,
        "best_gpu_backend": next((b for b in ("OPTIX", "CUDA", "HIP", "ONEAPI", "METAL") if b in devices), None),
        "addons": detected,
        "enabled_addon_count": len(enabled),
    }
