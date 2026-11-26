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


def has_op(path: str) -> bool:
    """bpy.ops returns a namespace for *any* name, so hasattr() lies; ask for the RNA type."""
    ns, name = path.split(".")
    try:
        getattr(getattr(bpy.ops, ns), name).get_rna_type()
        return True
    except Exception:
        return False


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
    if not has_op("arp.append_arp"):
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
    if not has_op("qremesher.remesh") or not hasattr(bpy.context.scene, "qremesher"):
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


# ============================================================================ trial v2
# Run with {"only": ["arp", "uvpm"]}: the full Auto-Rig Pro flow and a real UVPackmaster pack.

import os
import re
import sys

from . import metrics


def _rna_dump(ptr, depth: int = 2) -> dict:
    out = {}
    for p in ptr.bl_rna.properties:
        if p.identifier == "rna_type":
            continue
        try:
            v = getattr(ptr, p.identifier)
        except Exception as exc:
            out[p.identifier] = {"error": _err(exc)}
            continue
        e = {"type": p.type}
        if p.type == "ENUM":
            e["items"] = [i.identifier for i in p.enum_items][:40]
            e["value"] = addon_probe._value(v)
        elif p.type == "POINTER" and v is not None and depth > 0 and hasattr(v, "bl_rna"):
            e["fields"] = _rna_dump(v, depth - 1)
        elif p.type == "COLLECTION":
            e["len"] = len(v)
        else:
            e["value"] = addon_probe._value(v)
        out[p.identifier] = e
    return out


def _module_dir(needle: str):
    for name, mod in list(sys.modules.items()):
        if needle in name.lower() and getattr(mod, "__file__", None) and name.count(".") <= 2:
            return os.path.dirname(mod.__file__)
    return None


def _scene_enums(prefix: str, names: tuple) -> dict:
    out = {}
    props = bpy.types.Scene.bl_rna.properties
    for n in names:
        if n in props and props[n].type == "ENUM":
            out[n] = {"items": [i.identifier for i in props[n].enum_items],
                      "value": getattr(bpy.context.scene, n, None)}
    return out


def _test_body(height: float):
    bpy.ops.mesh.primitive_cylinder_add(vertices=24, radius=height * 0.12, depth=height,
                                        location=(0, 0, height / 2))
    body = bpy.context.active_object
    body.name = "trial_body"
    m = body.modifiers.new("s", "SUBSURF")
    m.levels = 2
    bpy.ops.object.modifier_apply(modifier=m.name)
    return body


def _trial_arp_flow(report: dict):
    arp: dict = {}
    report["auto_rig_pro_flow"] = arp
    if not has_op("arp.append_arp"):
        arp["skipped"] = "Auto-Rig Pro not loaded"
        return
    d = _module_dir("auto_rig_pro")
    arp["module_dir"] = d
    presets = []
    if d:
        for root, _, files in os.walk(d):
            presets += [os.path.relpath(os.path.join(root, f), d) for f in files if f.endswith(".blend")]
    arp["preset_blends"] = sorted(presets)[:60]
    arp["enums"] = _scene_enums("arp_", ("arp_engine_type", "arp_export_rig_type", "arp_bind_engine",
                                         "arp_smart_type", "arp_mesh_smooth_type", "arp_ge_vcol_type"))
    try:
        arp["export_op_params"] = _op_params("arp_export_scene.fbx")
    except Exception as exc:
        arp["export_op_params"] = _err(exc)

    _empty_scene()
    before = {o.name for o in bpy.data.objects}
    names = [os.path.splitext(os.path.basename(p))[0] for p in presets]
    candidates = [n for n in ("human", "Human") if n in names] + ["human"]
    for preset in dict.fromkeys(candidates):
        try:
            with bpy.context.temp_override(**view3d_override()):
                bpy.ops.arp.append_arp(rig_preset=preset)
            arp["append_preset"] = preset
            break
        except Exception as exc:
            arp.setdefault("append_errors", {})[preset] = _err(exc)[-400:]
    yield 0.5
    rigs = [o for o in bpy.data.objects if o.name not in before and o.type == "ARMATURE"]
    arp["appended"] = {o.name: [b.name for b in o.data.bones][:400] for o in rigs}
    if not rigs:
        return
    rig = rigs[0]
    _select_only(rig)
    for mode in ("EDIT", "OBJECT"):
        try:
            bpy.ops.object.mode_set(mode=mode)
            with bpy.context.temp_override(**view3d_override()):
                arp["match_result"] = list(bpy.ops.arp.match_to_rig())
            arp["match_mode"] = mode
            break
        except Exception as exc:
            arp.setdefault("match_errors", {})[mode] = _err(exc)[-400:]
    yield 0.5
    try:
        bpy.ops.object.mode_set(mode="OBJECT")
    except Exception:
        pass
    arm = bpy.data.objects.get(rig.name)
    arp["final_rig"] = {"name": arm.name, "bones": len(arm.data.bones),
                        "deform": [b.name for b in arm.data.bones if b.use_deform][:300]} if arm else None
    height = max(arm.dimensions.z, 1.0) if arm else 1.8
    body = _test_body(height)
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    body.select_set(True)
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    try:
        with bpy.context.temp_override(**view3d_override()):
            arp["bind_result"] = list(bpy.ops.arp.bind_to_rig())
        arp["body_vertex_groups"] = len(body.vertex_groups)
    except Exception as exc:
        arp["bind_error"] = _err(exc)[-600:]
    yield 0.5
    out_dir = os.path.abspath(report.get("_out_dir", "."))
    exports = {}
    engines = arp["enums"].get("arp_engine_type", {}).get("items", [])
    for eng in engines:
        if eng not in ("UNITY", "UE", "UNREAL"):
            continue
        sc = bpy.context.scene
        path = os.path.join(out_dir, f"arp_trial_{eng}.fbx")
        entry: dict = {"path": path, "attempts": {}}
        sc.arp_engine_type = eng
        if eng == "UNITY" and "HUMANOID" in arp["enums"].get("arp_export_rig_type", {}).get("items", []):
            sc.arp_export_rig_type = "HUMANOID"        # Unity Mecanim humanoid
        else:
            sc.arp_export_rig_type = "UNIVERSAL"
        if eng == "UNREAL" and hasattr(sc, "arp_rename_for_ue"):
            sc.arp_rename_for_ue = True                # UE Mannequin bone names
        entry["settings"] = {"engine": eng, "rig_type": sc.arp_export_rig_type}
        # the Export button's operator prepares the data the internal FBX writer needs
        calls = (("arp.arp_export_fbx_panel", lambda: bpy.ops.arp.arp_export_fbx_panel(filepath=path)),
                 ("arp_export_scene.fbx", lambda: bpy.ops.arp_export_scene.fbx(
                     filepath=path, shape_keys_baked_data="{}", mesh_names_data="{}")))
        for name, call in calls:
            for o in bpy.context.view_layer.objects:
                o.select_set(False)
            body.select_set(True)
            arm.select_set(True)
            bpy.context.view_layer.objects.active = arm
            try:
                with bpy.context.temp_override(**view3d_override()):
                    entry["attempts"][name] = list(call())
            except Exception as exc:
                entry["attempts"][name] = _err(exc)[-700:]
            yield 1.0
            if os.path.exists(path):
                entry["used"] = name
                break
        entry["exists"] = os.path.exists(path)
        entry["size"] = os.path.getsize(path) if entry["exists"] else 0
        exports[eng] = entry
        yield 0.5
    arp["exports"] = exports
    # read the exported skeletons back
    for eng, e in exports.items():
        if not e.get("exists"):
            continue
        before = {o.name for o in bpy.data.objects}
        try:
            bpy.ops.import_scene.fbx(filepath=e["path"])
            arms = [o for o in bpy.data.objects if o.name not in before and o.type == "ARMATURE"]
            e["reimported_bones"] = {a.name: [b.name for b in a.data.bones][:300] for a in arms}
        except Exception as exc:
            e["reimport_error"] = _err(exc)
        for o in [o for o in bpy.data.objects if o.name not in before]:
            bpy.data.objects.remove(o)


def _trial_uvpm(report: dict):
    u: dict = {}
    report["uvpackmaster_flow"] = u
    if not has_op("uvpackmaster4.pack"):
        u["skipped"] = "UVPackmaster 4 not loaded"
        return
    sc = bpy.context.scene
    try:
        u["props"] = _rna_dump(sc.uvpm4_props, depth=2)
    except Exception as exc:
        u["props_error"] = _err(exc)
    d = _module_dir("uvpackmaster")
    u["module_dir"] = d
    modes = set()
    if d:
        for root, _, files in os.walk(d):
            for f in files:
                if f.endswith(".py"):
                    try:
                        text = open(os.path.join(root, f), encoding="utf-8", errors="ignore").read()
                    except OSError:
                        continue
                    modes |= set(re.findall(r"""['"](pack\.[a-z0-9_.]+)['"]""", text))
    u["mode_ids"] = sorted(modes)[:60]
    _empty_scene()
    bpy.ops.mesh.primitive_monkey_add()
    obj = bpy.context.active_object
    _select_only(obj)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(island_margin=0.0)
    bpy.ops.object.mode_set(mode="OBJECT")
    u["before"] = metrics.uv_metrics(obj, 1024)
    mode_id = next((m for m in ("pack.single_tile", "pack.default") if m in modes), sorted(modes)[0] if modes else "")
    u["mode_used"] = mode_id
    uv = obj.data.uv_layers.active
    snap = [tuple(l.uv) for l in uv.data]
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    t0 = time.time()
    # UVPackmaster's operators poll for a UV Editor: turn the 3D view into one for the call
    ov = view3d_override()
    area = ov.get("area")
    old_ui = area.ui_type if area else None
    u["attempts"] = {}
    try:
        if area:
            area.ui_type = "UV"
            ov["region"] = next((r for r in area.regions if r.type == "WINDOW"), None)
            ov["space_data"] = area.spaces.active
        bpy.context.scene.tool_settings.use_uv_select_sync = True
        for label, kw in (("uv_editor", ov), ("uv_editor_no_space", {k: v for k, v in ov.items() if k != "space_data"})):
            try:
                with bpy.context.temp_override(**kw):
                    u["attempts"][label] = list(bpy.ops.uvpackmaster4.pack(mode_id=mode_id))
                u["call_result"] = u["attempts"][label]
                break
            except Exception as exc:
                u["attempts"][label] = _err(exc)[-400:]
    finally:
        pass
    if "call_result" not in u:
        u["call_error"] = "pack could not run in any context"
        if area:
            area.ui_type = old_ui
        bpy.ops.object.mode_set(mode="OBJECT")
        return
    last, stable = None, 0
    while time.time() - t0 < 120:
        yield 0.5
        bpy.ops.object.mode_set(mode="OBJECT")
        cur = [tuple(l.uv) for l in obj.data.uv_layers.active.data]
        bpy.ops.object.mode_set(mode="EDIT")
        if cur != snap:
            stable = stable + 1 if cur == last else 0
            last = cur
            if stable >= 3:
                break
    bpy.ops.object.mode_set(mode="OBJECT")
    if area:
        area.ui_type = old_ui
    u["elapsed_s"] = round(time.time() - t0, 1)
    u["uv_changed"] = last is not None
    u["after"] = metrics.uv_metrics(obj, 1024)


def run_v2(args: dict):
    report: dict = {"windowed": not bpy.app.background, "blender": bpy.app.version_string,
                    "_out_dir": args.get("out_dir", ".")}
    yield 2.0
    try:
        addon_probe.run({})          # also loads add-ons that are ticked but not loaded
    except Exception as exc:
        report["probe_error"] = _err(exc)
    yield 0.5
    only = set(args.get("only", ["arp", "uvpm"]))
    if "arp" in only:
        try:
            yield from _trial_arp_flow(report) or ()
        except Exception as exc:
            report["auto_rig_pro_flow_error"] = _err(exc)
    if "uvpm" in only:
        try:
            yield from _trial_uvpm(report) or ()
        except Exception as exc:
            report["uvpackmaster_flow_error"] = _err(exc)
    report.pop("_out_dir", None)
    return report
