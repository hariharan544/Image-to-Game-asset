"""Stage (windowed): try the paid add-ons for real and report how they behave.

  1. probe again with the UI up (UVPackmaster only loads with a GPU context)
  2. Auto-Rig Pro: smart-detection operators, append the reference rig, list its bones
  3. Quad Remesher: remesh a dense test sphere, wait for the result, measure it

Generator stage: yields seconds to wait so Quad Remesher's engine and timers can run.
The report is what Forge's add-on adapters are built from.
"""

from __future__ import annotations

import time

import bpy

from . import addon_probe


def view3d_override() -> dict:
    wm = bpy.context.window_manager
    for win in wm.windows:
        for area in win.screen.areas:
            if area.type == "VIEW_3D":
                region = next((r for r in area.regions if r.type == "WINDOW"), None)
                return {"window": win, "screen": win.screen, "area": area, "region": region}
    return {}


def _op_params(path: str):
    ns, name = path.split(".")
    op = getattr(getattr(bpy.ops, ns), name)
    return addon_probe._op_params(op)


def _err(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"[:600]


def _empty_scene() -> None:
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)


def _select_only(obj) -> None:
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def _trial_arp(report: dict) -> None:
    arp: dict = {}
    report["auto_rig_pro"] = arp
    if not hasattr(bpy.ops, "arp"):
        arp["skipped"] = "Auto-Rig Pro not loaded"
        return
    arp["ai_installed"] = getattr(bpy.context.scene, "arp_smart_AI_is_installed", None)
    # Smart (auto-detection) operators live outside the `arp` namespace in some versions
    smart = {}
    for ns in ("id", "arp"):
        group = getattr(bpy.ops, ns)
        for name in dir(group):
            if any(k in name.lower() for k in ("detect", "marker", "smart", "append")):
                try:
                    smart[f"{ns}.{name}"] = _op_params(f"{ns}.{name}")
                except Exception as exc:
                    smart[f"{ns}.{name}"] = _err(exc)
    arp["smart_and_append_ops"] = smart
    _empty_scene()
    before = {o.name for o in bpy.data.objects}
    try:
        with bpy.context.temp_override(**view3d_override()):
            arp["append_result"] = list(bpy.ops.arp.append_arp())
    except Exception as exc:
        arp["append_error"] = _err(exc)
    rigs = {}
    for o in bpy.data.objects:
        if o.name in before or o.type != "ARMATURE":
            continue
        rigs[o.name] = {"bones": len(o.data.bones), "names": [b.name for b in o.data.bones][:400]}
    arp["appended_armatures"] = rigs
    arp["appended_objects"] = sorted(o.name for o in bpy.data.objects if o.name not in before)[:100]


def _trial_qr(report: dict, timeout: float):
    qr: dict = {}
    report["quad_remesher"] = qr
    if not hasattr(bpy.ops, "qremesher") or not hasattr(bpy.context.scene, "qremesher"):
        qr["skipped"] = "Quad Remesher not loaded"
        return
    _empty_scene()
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=5, radius=1.0)
    src = bpy.context.active_object
    src.name = "qr_trial_src"
    src.scale = (1.0, 0.7, 1.4)
    qr["source_faces"] = len(src.data.polygons)
    s = bpy.context.scene.qremesher
    s.target_count = 800
    s.adaptive_size = 50.0
    s.autodetect_hard_edges = True
    _select_only(src)
    before = {o.name for o in bpy.data.objects}
    t0 = time.time()
    try:
        with bpy.context.temp_override(**view3d_override()):
            qr["call_result"] = list(bpy.ops.qremesher.remesh())
    except Exception as exc:
        qr["call_error"] = _err(exc)
        return
    qr["returned_after_s"] = round(time.time() - t0, 2)
    stable, last_faces, progress = 0, None, []
    while time.time() - t0 < timeout:
        yield 1.0
        progress.append(round(float(getattr(s, "progress_value", 0.0)), 3))
        new = [o for o in bpy.data.objects if o.name not in before and o.type == "MESH"]
        if new:
            faces = sum(len(o.data.polygons) for o in new)
            stable = stable + 1 if faces == last_faces else 0
            last_faces = faces
            if stable >= 2:
                break
    qr["progress_samples"] = progress[-20:]
    new = [o for o in bpy.data.objects if o.name not in before and o.type == "MESH"]
    qr["elapsed_s"] = round(time.time() - t0, 1)
    qr["timed_out"] = not new
    qr["results"] = []
    for o in new:
        quads = sum(1 for p in o.data.polygons if len(p.vertices) == 4)
        qr["results"].append({"name": o.name, "faces": len(o.data.polygons),
                              "quad_ratio": round(quads / max(len(o.data.polygons), 1), 3),
                              "collections": [c.name for c in o.users_collection],
                              "hidden": o.hide_get()})
    qr["source_after"] = {"exists": src.name in bpy.data.objects,
                          "hidden": src.hide_get() if src.name in bpy.data.objects else None}


def run(args: dict):
    report: dict = {"windowed": not bpy.app.background, "blender": bpy.app.version_string}
    yield 2.0                                   # let add-ons finish registering with the UI up
    try:
        report["probe"] = addon_probe.run({})
    except Exception as exc:
        report["probe_error"] = _err(exc)
    yield 0.5
    try:
        _trial_arp(report)
    except Exception as exc:
        report["auto_rig_pro_error"] = _err(exc)
    yield 0.5
    try:
        gen = _trial_qr(report, float(args.get("qr_timeout", 300)))
        if gen is not None:
            yield from gen
    except Exception as exc:
        report["quad_remesher_error"] = _err(exc)
    return report
