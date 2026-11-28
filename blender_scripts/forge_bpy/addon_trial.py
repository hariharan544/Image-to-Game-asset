"""Stage (windowed): try the paid add-ons for real and report how they behave.

  1. probe again with the UI up (UVPackmaster only loads with a GPU context)
  2. Auto-Rig Pro: smart-detection operators, append the reference rig, list its bones
  3. Quad Remesher: remesh a dense test sphere, wait for the result, measure it

Generator stage: yields seconds to wait so Quad Remesher's engine and timers can run.
The report is what Forge's add-on adapters are built from.

Also here: `run_rig_probe`, the Step 8 Auto-Rig Pro probe behind `forge arp-probe` (WP0, the
spec's `_trial_rig_brief`), at the end of this file.
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
    variants = []          # (label, engine, rig_type, extra scene settings)
    if "UNITY" in engines:
        variants.append(("UNITY", "UNITY", "HUMANOID", {}))
    if "UNREAL" in engines:
        variants.append(("UNREAL", "UNREAL", "UNIVERSAL", {"arp_rename_for_ue": True}))
        variants.append(("UNREAL_HUMANOID", "UNREAL", "HUMANOID",
                         {"arp_rename_for_ue": True, "arp_mannequin_axes": True}))
        variants.append(("UNREAL_HUMANOID_UE4", "UNREAL", "HUMANOID",
                         {"arp_rename_for_ue": True, "arp_ue4": True}))
    for label, eng, rig_type, extra in variants:
        sc = bpy.context.scene
        path = os.path.join(out_dir, f"arp_trial_{label}.fbx")
        entry: dict = {"path": path, "attempts": {}}
        sc.arp_engine_type = eng
        sc.arp_export_rig_type = rig_type
        for k, v in extra.items():
            if hasattr(sc, k):
                setattr(sc, k, v)
        entry["settings"] = {"engine": eng, "rig_type": rig_type, **extra}
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
        exports[label] = entry
        for k in extra:                       # reset for the next variant
            if hasattr(sc, k) and k != "arp_rename_for_ue":
                setattr(sc, k, False)
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
        u["poll_diagnosis"] = _uvpm_diagnose()
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


def _uvpm_diagnose() -> dict:
    """Why does uvpackmaster4.pack.poll() fail? Read the poll source and the add-on state."""
    out: dict = {"mode": bpy.context.mode}
    out.update(LO.operator_poll("uvpackmaster4.pack"))
    if "class" not in out:
        return out
    # add-on preferences (engine path / status live here in UVPM)
    for name, addon in bpy.context.preferences.addons.items():
        if "uvpackmaster" in name.lower():
            try:
                out["prefs"] = _rna_dump(addon.preferences, depth=1)
            except Exception as exc:
                out["prefs_error"] = _err(exc)
    return out


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


# ============================================================================ rig brief probe (WP0)
# `forge arp-probe` (forge/arp_probe.py) runs `run_rig_probe` once per part, each part in its own
# Blender, and merges the parts into one result file, which is committed as
# docs/research/arp_3_79_probe.json once the director sends it back. Step 8's later work reads that
# file instead of guessing from the 3.77.33 source mirror. Rules:
#   * every item runs in its own try/except and records {"status": "error", "error": ...};
#   * after every item the part's report is written to args["partial"], and "_current" names the
#     item in progress, so a Blender crash still leaves everything found before it;
#   * scenes are throwaway (nothing is saved), the user's preferences are never written.

import inspect
import io
import json
import traceback

from . import arp_limb_options as LO

PROBE_PRESETS = ("human", "dog", "horse", "free")
EXPECTED_LIMB_OPTIONS = (
    "limb_type", "side", "load_settings_when_exec",
    "finger_thumb", "finger_index", "finger_middle", "finger_ring", "finger_pinky",
    "toes_thumb", "toes_index", "toes_middle", "toes_ring", "toes_pinky", "three_bones_leg",
    "spine_count", "neck_count", "ear_count", "tail_count", "tail_side", "tail_name",
    "arm_wings", "arm_feathers", "forearm_feathers", "hand_feathers",
    "spline_count", "spline_bendy", "spline_name", "spline_side", "spline_deform",
    "kilt_amount", "kilt_name", "facial", "facial_mouth", "facial_teeth", "facial_tongue",
    "facial_eye_l", "facial_eye_r", "facial_eyebrow_l", "facial_eyebrow_r", "facial_chins",
    "facial_noses", "facial_cheeks", "skull_bones", "muzzle")
OPTION_GROUPS = ("finger_", "fingers_", "toes_", "three_bones_leg", "spine_", "neck_", "ear_", "tail_",
                 "arm_wings", "feathers_", "spline_", "bbones_", "kilt_", "facial", "lips_", "eye")
PROBE_OPS = ("arp.append_arp", "arp.show_limb_params", "arp.add_limb", "arp.dupli_limb", "arp.disable_limb",
             "arp.match_to_rig", "arp.bind_to_rig", "arp.unbind_to_rig", "arp.arp_export_fbx_panel",
             "arp_export_scene.fbx", "id.set_humanoid_rig", "id.set_mped_rig")     # ARP names these two id.*
OWNER_BONES = ("hand.r", "hand.l", "head.x", "neck.x", "spine_01.x", "spine_02.x", "spine_03.x", "root.x",
               "forearm.r", "forearm.l", "arm.r", "arm.l", "thigh.r", "thigh.l", "leg.r", "leg.l",
               "foot.r", "foot.l")
POLE_NAMES = ("c_leg_pole.l", "c_leg_pole.r", "c_arms_pole.l", "c_arms_pole.r")
LIMB_REFS = {"arm": ("arm_ref.l", "shoulder_ref.l"), "leg": ("thigh_ref.l", "leg_ref.l"),
             "ear": ("ear_01_ref.l",), "tail": ("tail_00_ref.x",), "neck": ("neck_ref.x",),
             "spine": ("spine_01_ref.x", "root_ref.x"), "head": ("head_ref.x",)}
UI_ONLY = LO.UI_ONLY
SOCKET = "cc_socket_probe"
EXPORTS = (("unity_humanoid", "UNITY", "HUMANOID", {}),
           ("unity_universal", "UNITY", "UNIVERSAL", {}),
           ("unreal_humanoid", "UNREAL", "HUMANOID",
            {"arp_rename_for_ue": True, "arp_mannequin_axes": True, "arp_ue4": False}),
           ("unreal_universal", "UNREAL", "UNIVERSAL", {"arp_rename_for_ue": True}))


# the value helpers are shared with Step 8 (arp_limb_options): one copy of the 9.2 protocol
_js, _plain, _norm, _eq = LO.js, LO.plain, LO.norm, LO.same
_prop_default, _op_defaults = LO.prop_default, LO.op_defaults
_captured, _tail, _is_ref, _arp_module = LO.captured, LO.tail, LO.is_ref, LO.arp_module
_limb_state, LIVE_VALUES_NOTE = LO.limb_state, LO.LIVE_VALUES_NOTE


def _v3(v) -> list:
    return [round(float(x), 5) for x in v]


def _set_key(d: dict, path: str, value) -> None:
    keys = path.split(".")
    for k in keys[:-1]:
        if not isinstance(d.get(k), dict):
            d[k] = {}
        d = d[k]
    d[keys[-1]] = value


class _Rec:
    """The part's report, written to disk after every item (survives a Blender crash)."""

    def __init__(self, part: str, path):
        self.r: dict = {"part": part, "_current": None, "errors": []}
        self.path = path

    def flush(self) -> None:
        if not self.path:
            return
        try:
            tmp = f"{self.path}.tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.r, f, default=str)
            os.replace(tmp, self.path)
        except Exception:                                   # noqa: BLE001 - never stop the probe
            pass

    def start(self, key: str) -> None:
        self.r["_current"] = key
        self.flush()

    def put(self, key: str, value) -> None:
        _set_key(self.r, key, _js(value))
        self.r["_current"] = None
        self.flush()


def _item(rec: _Rec, key: str, fn, *a, **kw) -> dict:
    rec.start(key)
    t0 = time.time()
    try:
        out = dict(fn(*a, **kw) or {})
        out.setdefault("status", "ok")
        if out["status"] == "error":                        # an error found and reported, not raised
            rec.r["errors"].append(f"{key}: {out.get('error')}"[:600])
    except Exception as exc:                                # noqa: BLE001 - recorded, never raised
        out = {"status": "error", "error": _err(exc), "trace": traceback.format_exc()[-2000:]}
        rec.r["errors"].append(f"{key}: {_err(exc)}")
        _to_object_mode()
    out["seconds"] = round(time.time() - t0, 2)
    try:
        rec.put(key, out)
    except Exception as exc:                                # noqa: BLE001 - recording must not end the part
        out = {"status": "error", "error": f"could not record: {_err(exc)}", "seconds": out["seconds"]}
        rec.r["errors"].append(f"{key}: could not record: {_err(exc)}")
        try:
            rec.put(key, out)
        except Exception:                                   # noqa: BLE001
            rec.r["_current"] = None
    return out


def _to_object_mode() -> None:
    try:
        ob = bpy.context.view_layer.objects.active
        if ob is not None and ob.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
    except Exception:                                       # noqa: BLE001
        pass


def _arp_info() -> dict:
    import addon_utils
    info: dict = {"loaded": has_op("arp.append_arp")}
    mods = []
    for m in addon_utils.modules():
        bi = addon_utils.module_bl_info(m)
        hay = (m.__name__ + " " + str(bi.get("name", ""))).lower()
        if "auto_rig" in hay or "auto-rig" in hay:
            mods.append({"module": m.__name__, "name": bi.get("name"), "version": _js(bi.get("version")),
                         "enabled": bool(addon_utils.check(m.__name__)[1])})
    info["addon_modules"] = mods
    if not info["loaded"] and mods:
        errs: list = []                         # say why it does not turn on (for the director)
        try:
            addon_utils.enable(mods[0]["module"], default_set=False, persistent=False,
                               handle_error=lambda exc: errs.append(_err(exc)))
        except Exception as exc:                            # noqa: BLE001
            errs.append(_err(exc))
        if errs:
            info["enable_error"] = errs[0]
        info["loaded"] = has_op("arp.append_arp")
    src = _arp_module("load_limb_settings")
    d = os.path.dirname(os.path.dirname(src.__file__)) if src is not None and getattr(src, "__file__", None) \
        else _module_dir("auto_rig")
    info["module"] = src.__name__ if src is not None else None
    info["module_dir"] = d
    version, where = None, None
    if d and os.path.exists(os.path.join(d, "blender_manifest.toml")):
        try:
            txt = open(os.path.join(d, "blender_manifest.toml"), encoding="utf-8").read()
            m = re.search(r'(?m)^\s*version\s*=\s*"([^"]+)"', txt)
            version, where = (m.group(1), "blender_manifest.toml") if m else (None, None)
        except OSError:
            pass
    if version is None:
        for m in mods:
            if m.get("version"):
                version, where = ".".join(str(x) for x in m["version"]), "bl_info"
                break
    info["version"] = version
    info["version_source"] = where
    nums = re.findall(r"\d+", version or "")
    info["version_tuple"] = [int(x) for x in nums[:3]]
    presets = []
    if d and os.path.isdir(os.path.join(d, "armature_presets")):
        presets = sorted(os.path.splitext(f)[0] for f in os.listdir(os.path.join(d, "armature_presets"))
                         if f.endswith(".blend"))
    info["presets_available"] = presets
    return info


def _blender_info() -> dict:
    h = bpy.app.build_hash
    return {"version": bpy.app.version_string, "version_tuple": list(bpy.app.version),
            "windowed": not bpy.app.background,
            "build_hash": h.decode(errors="ignore") if isinstance(h, bytes) else str(h)}


# ----------------------------------------------------------------------------- scene helpers

def _clear_scene() -> None:
    _to_object_mode()
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    for c in list(bpy.data.collections):
        bpy.data.collections.remove(c)
    try:
        bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)
    except Exception:                                       # noqa: BLE001
        pass
    bpy.context.scene.cursor.location = (0, 0, 0)


def _ref_rig(objs):
    arms = [o for o in objs if o.type == "ARMATURE"]
    return next((o for o in arms if any(_is_ref(b) for b in o.data.bones)), arms[0] if arms else None)


def _append(preset: str):
    """Fresh scene + ARP preset. Returns (reference rig, new objects, what ARP printed)."""
    _clear_scene()
    before = {o.name for o in bpy.data.objects}
    buf = io.StringIO()
    with _captured(buf), bpy.context.temp_override(**view3d_override()):
        bpy.ops.arp.append_arp(rig_preset=preset)
    _to_object_mode()
    new = [o for o in bpy.data.objects if o.name not in before]
    rig = _ref_rig(new)
    if rig is None:
        raise RuntimeError(f"append_arp('{preset}') added no armature ({[o.name for o in new][:20]})")
    return rig, new, buf.getvalue()


def _limb_sides(rig) -> dict:
    """ARP's own count of limbs (what check_humanoid_limbs reads)."""
    for name, mod in list(sys.modules.items()):
        ls = getattr(mod, "limb_sides", None) if mod is not None and "auto_rig" in name.lower() else None
        if ls is not None and hasattr(ls, "get_multi_limbs"):
            _select_only(rig)
            ls.get_multi_limbs()
            return {k: _js(getattr(ls, k)) for k in dir(ls) if k.endswith("_sides")}
    return {"error": "limb_sides not found"}


def _ref_bones(rig) -> dict:
    _to_object_mode()
    out = {}
    for b in rig.data.bones:
        if not _is_ref(b):
            continue
        out[b.name] = {"parent": b.parent.name if b.parent else None, "head": _v3(b.head_local),
                       "tail": _v3(b.tail_local), "connect": b.use_connect, "deform": b.use_deform,
                       "collections": [c.name for c in getattr(b, "collections", [])][:6],
                       "keys": {k: _js(b[k]) for k in b.keys()}}
    return out


def _ref_parents(rig) -> dict:
    _to_object_mode()
    return {b.name: (b.parent.name if b.parent else None) for b in rig.data.bones if _is_ref(b)}


def _rig(st: dict):
    rig = bpy.data.objects.get(st.get("rig", ""))
    if rig is None:
        raise RuntimeError("no rig (an earlier step failed)")
    return rig


_select_ref = LO.select_ref


def _facial_off(rig) -> dict:
    """Forge's own head call (arp_rig.add_extras, through arp_limb_options.facial_off): face
    bones off, skipped when head_ref.x already stores them off (the human preset does). Never
    stops a part: when Auto-Rig Pro refuses, what its check saw is recorded and the part goes on
    (on the director's PC the refused call once ended multi_arm_export, limbs_setup and
    build_setup before they had done anything)."""
    try:
        out = LO.facial_off(rig)
    except Exception as exc:                                # noqa: BLE001 - recorded, never raised
        out = {"facial": "not changed", "error": _err(exc)}
    _to_object_mode()
    return out


def _match(rig):
    name = rig.name
    _select_only(rig)
    bpy.ops.object.mode_set(mode="EDIT")
    buf = io.StringIO()
    with _captured(buf), bpy.context.temp_override(**view3d_override()):
        res = bpy.ops.arp.match_to_rig()
    _to_object_mode()
    rig = bpy.data.objects.get(name)
    if rig is None:
        raise RuntimeError(f"the rig '{name}' is gone after match_to_rig")
    return rig, list(res), buf.getvalue()


def _name_words(name: str) -> set:
    """'forearm_stretch_dupli_001.l' -> {'forearm', 'stretch', 'dupli', '001'}. Bones are told
    apart by whole words: 'ear' is in 'forearm' as letters, not as a word (the director's first
    probe listed forearm bones as ear bones)."""
    return set(re.split(r"[_.]+", re.sub(r"\.[lrx]$", "", name.lower()))) - {""}


def _named(name: str, *words: str) -> bool:
    return not _name_words(name).isdisjoint(words)


CHAIN_WORDS = ("tail", "ear", "spline")
WING_WORDS = ("feather", "feathers", "wing", "wings")


def _parent_chain(rig, name: str, n: int = 10) -> list:
    b = rig.data.bones.get(name)
    out = []
    while b is not None and b.parent is not None and len(out) < n:
        b = b.parent
        out.append(b.name)
    return out


# ----------------------------------------------------------------------------- limb options

def _rna_props(rna) -> dict:
    out = {}
    for p in rna.properties:
        if p.identifier == "rna_type":
            continue
        e = {"type": p.type}
        try:
            e["default"] = _js(_prop_default(p))
        except Exception as exc:                            # noqa: BLE001
            e["default_error"] = _err(exc)
        if p.type == "ENUM":
            e["items"] = [i.identifier for i in p.enum_items][:60]
        if p.type in ("INT", "FLOAT"):
            e["min"], e["max"] = _js(p.hard_min), _js(p.hard_max)
        out[p.identifier] = e
    return out


def _set_limb_options(rig, ref: str, changes: dict) -> dict:
    """Spec 9.2 protocol (the one Step 8 uses, arp_limb_options.set_limb_options): read the
    limb's state, change only `changes`, verify the rest. A refusal is recorded as an error with
    what Auto-Rig Pro's check saw."""
    rep = LO.set_limb_options(rig, ref, changes)
    _to_object_mode()
    if rep.get("error"):
        rep["status"] = "error"
    return rep


def _source_keys(fn) -> dict:
    src = inspect.getsource(fn)
    keys = set(re.findall(r"""\[\s*['"]([A-Za-z0-9_]+)['"]\s*\]""", src))
    keys |= set(re.findall(r"""['"]([A-Za-z0-9_]+)['"]\s+in\s+[\w.\[\]'"]+\.keys\(\)""", src))
    bones = set(re.findall(r"""get_edit_bone\(\s*['"]([A-Za-z0-9_.]+)['"]""", src))
    return {"keys": sorted(keys), "bones": sorted(bones), "lines": src.count("\n")}


# ----------------------------------------------------------------------------- probe items

def _probe_operators() -> dict:
    ops = {}
    for path in PROBE_OPS:
        if not has_op(path):
            ops[path] = {"exists": False}
            continue
        try:
            ns, name = path.split(".")
            ops[path] = {"exists": True, "params": _rna_props(getattr(getattr(bpy.ops, ns), name).get_rna_type())}
        except Exception as exc:                            # noqa: BLE001
            ops[path] = {"exists": True, "error": _err(exc)}
    return {"ops": ops, "arp_ops": sorted(dir(bpy.ops.arp))[:600]}


def _scene_arp_props() -> dict:
    return {p.identifier: p for p in bpy.types.Scene.bl_rna.properties if p.identifier.startswith("arp_")}


def _probe_scene_props() -> dict:
    sc = bpy.context.scene
    out = {}
    for k, p in _scene_arp_props().items():
        e = {"type": p.type}
        try:
            e["default"] = _js(_prop_default(p))
            e["value"] = _js(getattr(sc, k))
        except Exception as exc:                            # noqa: BLE001
            e["error"] = _err(exc)
        if p.type == "ENUM":
            e["items"] = [i.identifier for i in p.enum_items][:60]
        out[k] = e
    return {"props": out}


def _probe_limb_options() -> dict:
    props = _rna_props(bpy.ops.arp.show_limb_params.get_rna_type())
    present = {n: n in props for n in EXPECTED_LIMB_OPTIONS}
    groups = {g: sorted(k for k in props if k.startswith(g)) for g in OPTION_GROUPS}
    return {"properties": props, "count": len(props), "expected_present": present,
            "missing_expected": sorted(n for n, ok in present.items() if not ok), "groups": groups}


def _probe_scale_fix() -> dict:
    props = _scene_arp_props()
    p = props.get("arp_bind_scale_fix")
    return {"prop": "arp_bind_scale_fix", "exists": p is not None,
            "default": _js(_prop_default(p)) if p is not None else None,
            "related": sorted(k for k in props if "scale" in k),
            "bind_props": sorted(k for k in props if k.startswith("arp_bind"))}


def _humanoid_section(rec: _Rec) -> None:
    if isinstance(rec.r.get("humanoid_check"), dict):
        return
    mod = _arp_module("check_humanoid_limbs")
    rec.put("humanoid_check", {"status": "ok", "reachable": mod is not None,
                               "module": mod.__name__ if mod else None, "results": {}})


def _humanoid(rig) -> dict:
    """ARP's own HUMANOID export test on this rig (spec 9.9)."""
    mod = _arp_module("check_humanoid_limbs")
    if mod is None:
        raise RuntimeError("check_humanoid_limbs is not reachable")
    _to_object_mode()
    _select_only(rig)
    sc = bpy.context.scene
    old = sc.arp_export_rig_type
    try:
        sc.arp_export_rig_type = "HUMANOID"
        ok = bool(mod.check_humanoid_limbs())
    finally:
        sc.arp_export_rig_type = old
    return {"humanoid": ok, "rig": rig.name, "limb_sides": _limb_sides(rig),
            "has_c_root_master": "c_root_master.x" in rig.data.bones,
            "three_bone_legs": sorted(b.name for b in rig.data.bones if b.name.startswith("thigh_b_ref"))}


def _probe_preset(preset: str) -> dict:
    rig, new, log = _append(preset)
    refs = _ref_bones(rig)
    out = {"armature": rig.name, "ref_count": len(refs), "ref_bones": refs,
           "bone_count": len(rig.data.bones), "deform_count": sum(1 for b in rig.data.bones if b.use_deform),
           "appended_objects": sorted(o.name for o in new)[:80],
           "armatures": {o.name: len(o.data.bones) for o in new if o.type == "ARMATURE"},
           "roots": sorted(n for n, e in refs.items() if e["parent"] is None or e["parent"] not in refs),
           "dupli_refs": sorted(n for n in refs if "_dupli_" in n),
           "rig_props": {k: _js(rig[k]) for k in rig.keys()},
           "data_props": {k: _js(rig.data[k]) for k in rig.data.keys()},
           "rig_spine_count": _js(getattr(rig, "rig_spine_count", None)),
           "log_tail": _tail(log)}
    root = refs.get("root_ref.x") or {}
    out["spine_count_key"] = root.get("keys", {}).get("spine_count")
    out["spine_refs"] = sorted(n for n in refs if n.startswith("spine_"))
    try:
        out["limb_sides"] = _limb_sides(rig)
    except Exception as exc:                                # noqa: BLE001
        out["limb_sides"] = {"error": _err(exc)}
    return out


def _probe_spine_count(rec: _Rec) -> dict:
    h = (rec.r.get("presets") or {}).get("human") or {}
    if h.get("status") != "ok":
        raise RuntimeError("the human preset could not be read")
    n = h.get("spine_count_key")
    if n is None:
        n = h.get("rig_spine_count")
    if n is None:
        n = len([s for s in h.get("spine_refs", []) if re.match(r"spine_\d+_ref\.x$", s)])
    return {"human": n, "root_ref_key": h.get("spine_count_key"), "rig_spine_count": h.get("rig_spine_count"),
            "spine_refs": h.get("spine_refs"),
            "operator_default": (rec.r.get("limb_options") or {}).get("properties", {}).get("spine_count", {}).get("default")}


# ----------------------------------------------------------------------------- limbs part

def _add_case(st: dict, preset: str) -> dict:
    rig = _rig(st)
    before = _ref_parents(rig)
    all_before = {b.name for b in rig.data.bones}
    _select_only(rig)
    buf = io.StringIO()
    with _captured(buf), bpy.context.temp_override(**view3d_override()):
        res = bpy.ops.arp.add_limb(limbs_presets=preset)
    rig = _rig(st)
    after = _ref_parents(rig)
    new = {n: after[n] for n in sorted(set(after) - set(before))}
    new_all = sorted({b.name for b in rig.data.bones} - all_before)
    st.setdefault("before_add", {})[preset] = before
    return {"preset": preset, "call": list(res), "new_ref_bones": new,
            "new_root": next((n for n, p in new.items() if p not in new), None),
            "new_bone_count": len(new_all), "new_bones": new_all[:150], "log_tail": _tail(buf.getvalue(), 12)}


def _tail_dupli(st: dict, side: str) -> dict:
    """An extra tail hung from the head (spec 9.5: extra ears as tail duplicates)."""
    out = _add_case(st, "tail")
    rig = _rig(st)
    before = st["before_add"]["tail"]
    root = out["new_root"]
    if not root:
        raise RuntimeError("the new tail has no reference bones")
    try:
        out["side_change"] = _set_limb_options(rig, root, {"tail_side": side})
    except Exception as exc:                                # noqa: BLE001
        out["side_change"] = {"status": "error", "error": _err(exc)}
    now = _ref_parents(rig)
    grp = {n: now[n] for n in sorted(set(now) - set(before))}
    out["refs_after_side"] = grp
    new_root = next((n for n, p in grp.items() if p not in grp), None)
    out["root_after_side"] = new_root
    if new_root and _select_ref(rig, new_root):
        eb = rig.data.edit_bones
        if eb.get("head_ref.x") is not None:
            eb[new_root].use_connect = False
            eb[new_root].parent = eb["head_ref.x"]
            out["parent_set_to"] = "head_ref.x"
        _to_object_mode()
        out["parent_now"] = _ref_parents(rig).get(new_root)
    return out


def _disable_ear(st: dict) -> dict:
    """What arp.disable_limb removes when one side's ear is selected: Forge would use it to drop the
    ear Auto-Rig Pro adds on a body with one ear, but only if it leaves the other ear in place."""
    rig = _rig(st)
    before = _ref_parents(rig)
    all_before = {b.name for b in rig.data.bones}
    ears = sorted(n for n in before if _named(n, "ear") and n.endswith(".r"))
    if not ears:
        raise RuntimeError("no right ear reference bones to remove")
    target = next((n for n in ears if "dupli" not in n), ears[0])
    if not _select_ref(rig, target):
        _to_object_mode()
        raise RuntimeError(f"could not select {target}")
    buf = io.StringIO()
    with _captured(buf), bpy.context.temp_override(**view3d_override()):
        res = bpy.ops.arp.disable_limb()
    _to_object_mode()
    rig = _rig(st)
    after = _ref_parents(rig)
    stem, rest = target.split("_ref")[0].rsplit("_", 1)[0] + "_", target.split("_ref", 1)[1]
    own = [n for n in ears if n.startswith(stem) and n.split("_ref", 1)[1] == rest]   # that ear's own chain
    gone_all = sorted(all_before - {b.name for b in rig.data.bones})
    ears_left = sorted(n for n in after if _named(n, "ear"))
    return {"selected": target, "call": list(res), "removed_ref_bones": sorted(set(before) - set(after)),
            "removed_bone_count": len(gone_all), "removed_bones": gone_all[:150], "ears_left": ears_left,
            "other_side_kept": any(n.endswith(".l") for n in ears_left),
            "others_kept": sorted(set(before) - set(after)) == own,
            "log_tail": _tail(buf.getvalue(), 12)}


def _probe_load_settings(st: dict) -> dict:
    rig = _rig(st)
    mod = _arp_module("load_limb_settings")
    if mod is None:
        raise RuntimeError("no Auto-Rig Pro module defines load_limb_settings")
    defaults = _op_defaults()
    names = {b.name for b in rig.data.bones}
    per = {}
    for limb, refs in LIMB_REFS.items():
        ref = next((r for r in refs if r in names), None)
        if ref is None:
            per[limb] = {"status": "error", "error": f"none of {list(refs)} in the rig"}
            continue
        try:
            vals, extra, notes, live = _limb_state(rig, ref, defaults)
            per[limb] = {"status": "ok", "ref": ref, "limb_type": vals.get("limb_type"), "side": vals.get("side"),
                         "changed": {k: v for k, v in vals.items() if not _eq(v, defaults.get(k))},
                         "values": vals, "extra": extra, "notes": notes, "edit_bone_values": live}
        except Exception as exc:                            # noqa: BLE001
            per[limb] = {"status": "error", "error": _err(exc)}
        _to_object_mode()
    try:
        src = _source_keys(mod.load_limb_settings)
    except Exception as exc:                                # noqa: BLE001
        src = {"keys": [], "error": _err(exc)}
    return {"module": mod.__name__, "keys_in_source": src.get("keys", []),
            "edit_bones_in_source": src.get("bones", []), "source": {k: v for k, v in src.items() if k not in ("keys", "bones")},
            "per_limb": per, "edit_bone_values_note": LIVE_VALUES_NOTE}


def _probe_ref_keys(st: dict) -> dict:
    refs = _ref_bones(_rig(st))
    bones = {n: e["keys"] for n, e in refs.items() if e["keys"]}
    seen = sorted({k for keys in bones.values() for k in keys})
    return {"bones": bones, "keys_seen": seen, "ref_count": len(refs)}


def _after_match(st: dict) -> dict:
    rig, res, log = _match(_rig(st))
    names = [b.name for b in rig.data.bones]
    deform = [b.name for b in rig.data.bones if b.use_deform]
    chains = {}
    for b in rig.data.bones:
        if _named(b.name, *CHAIN_WORDS) and (b.parent is None or not _named(b.parent.name, *CHAIN_WORDS)):
            chains[b.name] = _parent_chain(rig, b.name)
    return {"match": res, "bones": len(names), "deform_count": len(deform), "ik_poles": _poles_or_error(st),
            "dupli_deform": sorted(n for n in deform if _named(n, "dupli")),
            "tail_deform": sorted(n for n in deform if _named(n, "tail")),
            "ear_deform": sorted(n for n in deform if _named(n, "ear")),
            "spline_bones": sorted(n for n in names if _named(n, "spline"))[:80],
            "spline_deform": sorted(n for n in deform if _named(n, "spline")),
            "chain_roots_parents": chains, "log_tail": _tail(log, 12)}


# ----------------------------------------------------------------------------- build part

def _body_from_bones(rig, name: str = "probe_body"):
    """A closed test body around the rig's deform bones (tubes, voxel-remeshed into one skin)."""
    import bmesh
    from mathutils import Matrix
    _to_object_mode()
    H = max(rig.dimensions.z, 0.1)
    bm = bmesh.new()
    for b in rig.data.bones:
        if not b.use_deform:
            continue
        h, t = rig.matrix_world @ b.head_local, rig.matrix_world @ b.tail_local
        L = (t - h).length
        if L < 1e-4:
            continue
        r = max(min(0.3 * L, 0.06 * H), 0.012 * H)
        rot = (t - h).normalized().to_track_quat("Z", "Y").to_matrix().to_4x4()
        bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=12, radius1=r, radius2=r,
                              depth=L + r, matrix=Matrix.Translation((h + t) / 2) @ rot)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(obj)
    mod = obj.modifiers.new("vox", "REMESH")
    mod.mode = "VOXEL"
    mod.voxel_size = H / 80
    dg = bpy.context.evaluated_depsgraph_get()
    me2 = bpy.data.meshes.new_from_object(obj.evaluated_get(dg))
    obj.modifiers.clear()
    obj.data = me2
    bpy.data.meshes.remove(me)
    return obj


def _unbind(obj) -> None:
    for m in [m for m in obj.modifiers if m.type == "ARMATURE"]:
        obj.modifiers.remove(m)
    mw = obj.matrix_world.copy()
    obj.parent = None
    obj.matrix_world = mw
    obj.vertex_groups.clear()


def _group_weights(obj, group: str):
    vg = obj.vertex_groups.get(group)
    if vg is None:
        return None
    w = [0.0] * len(obj.data.vertices)
    for v in obj.data.vertices:
        for g in v.groups:
            if g.group == vg.index:
                w[v.index] = g.weight
    return w


def _bind_once(st: dict, engine: str, scale_fix=None):
    """bind_to_rig on the test body. Returns (facts, what ARP printed).

    After 'Bone Heat Weighting: failed', ARP turns scene.arp_bind_scale_fix on for good and asks
    'Bind again with Scale Fix enabled?' in a dialog. The probe records that, then puts the
    setting back, so the next bind runs like this one did. `scale_fix` forces the setting."""
    rig, body = _rig(st), bpy.data.objects[st["body"]]
    _unbind(body)
    sc = bpy.context.scene
    old = getattr(sc, "arp_bind_engine", None)
    has_fix = hasattr(sc, "arp_bind_scale_fix")
    old_fix = bool(sc.arp_bind_scale_fix) if has_fix else None
    fix_used = old_fix if scale_fix is None or not has_fix else bool(scale_fix)
    fix_after = None
    _to_object_mode()
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    body.hide_set(False)
    body.select_set(True)
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    buf = io.StringIO()
    t0 = time.time()
    try:
        sc.arp_bind_engine = engine
        if has_fix:
            sc.arp_bind_scale_fix = fix_used
        with _captured(buf), bpy.context.temp_override(**view3d_override()):
            res = list(bpy.ops.arp.bind_to_rig())
    finally:
        if has_fix:
            fix_after = bool(sc.arp_bind_scale_fix)
            sc.arp_bind_scale_fix = old_fix
        if old is not None:
            sc.arp_bind_engine = old
    _to_object_mode()
    mods = [m for m in body.modifiers if m.type == "ARMATURE"]
    deform = {b.name for b in rig.data.bones if b.use_deform}
    idx = {g.index for g in body.vertex_groups if g.name in deform}
    unweighted = sum(1 for v in body.data.vertices if not any(g.group in idx and g.weight > 0 for g in v.groups))
    facts = {"engine": engine, "result": res, "seconds": round(time.time() - t0, 1),
             "vertices": len(body.data.vertices), "vertex_groups": len(body.vertex_groups),
             "unweighted_vertices": unweighted, "armature_modifiers": len(mods),
             "modifier_preserve_volume": mods[0].use_deform_preserve_volume if mods else None,
             "scene_arp_bind_preserve": _js(getattr(sc, "arp_bind_preserve", None)),
             "scale_fix_used": fix_used, "scene_arp_bind_scale_fix_after": fix_after,
             "scale_fix_turned_on_by_arp": bool(has_fix and fix_after and not fix_used),
             "log_tail": _tail(buf.getvalue(), 20)}
    return facts, buf.getvalue()


def _probe_chin(st: dict) -> dict:
    """Do arp_chin_loc / arp_chin_pos_vec change the head weights at bind? (spec 9.4)"""
    from mathutils import Vector
    rig = _rig(st)
    body = bpy.data.objects[st["body"]]
    head = rig.data.bones.get("head.x")
    if head is None:
        raise RuntimeError("no head.x bone after match_to_rig")
    for k in ("arp_chin_loc", "arp_chin_pos_vec"):
        if k in rig.data.keys():
            del rig.data[k]
    fix = bool(getattr(bpy.context.scene, "arp_bind_scale_fix", False))   # the same for both binds
    a, log_a = _bind_once(st, "HEAT_MAP", scale_fix=fix)
    st["bind_heat"] = a
    wa = _group_weights(body, "head.x")
    hh, ht = head.head_local, head.tail_local
    L = (ht - hh).length
    chin = rig.matrix_world @ (hh + Vector((0.0, -0.6 * L, -0.35 * L)))
    rig.data["arp_chin_loc"] = chin.z
    rig.data["arp_chin_pos_vec"] = list(chin)
    b, log_b = _bind_once(st, "HEAT_MAP", scale_fix=fix)
    flipped = [n for n, f in (("bind_without_keys", a), ("bind_with_keys", b)) if f.get("scale_fix_turned_on_by_arp")]
    wb = _group_weights(body, "head.x")
    if wa is not None and wb is not None and len(wa) == len(wb):
        deltas = [abs(x - y) for x, y in zip(wa, wb)]
        delta, changed = max(deltas or [0.0]), sum(1 for d in deltas if d > 1e-3)
    else:
        delta = abs(sum(wa or []) - sum(wb or []))
        changed = None
    approx = rig.matrix_world @ (hh + head.z_axis.normalized() * L * 0.5)
    out = {"arp_bind_chin": _js(getattr(bpy.context.scene, "arp_bind_chin", None)),
           "keys_read": "set real chin pos" in log_b,
           "approximate_without_keys": "set approximate chin pos" in log_a,
           "weights_changed": delta > 1e-3, "max_head_weight_delta": round(delta, 5),
           "changed_vertices": changed, "chin_set": _v3(chin), "approx_chin_arp": _v3(approx),
           "head_group_found": wa is not None, "scale_fix_both_binds": fix,
           "scale_fix_turned_on_by_arp": flipped, "weights_comparison_valid": not flipped,
           "bind_without_keys": a, "bind_with_keys": b}
    if flipped:
        out["weights_comparison_note"] = (
            "Heat weighting failed for some bones in " + " and ".join(flipped) + " (ARP then turned Scale "
            "Fix on and asked to bind again). weights_changed and max_head_weight_delta do not measure "
            "the chin here; keys_read still does.")
    return out


def _import_fbx(path: str) -> dict:
    """Read an exported FBX back: armature bones with parents, meshes with vertex groups."""
    before = {o.name for o in bpy.data.objects}
    try:
        bpy.ops.import_scene.fbx(filepath=path)
    except Exception:                                       # noqa: BLE001 - Blender's newer importer
        bpy.ops.wm.fbx_import(filepath=path)
    new = [o for o in bpy.data.objects if o.name not in before]
    out = {"armatures": {}, "meshes": {}}
    for o in new:
        if o.type == "ARMATURE":
            out["armatures"][o.name] = {"bones": {b.name: (b.parent.name if b.parent else None)
                                                  for b in o.data.bones}}
        elif o.type == "MESH":
            out["meshes"][o.name] = {"vertices": len(o.data.vertices),
                                     "vertex_groups": [g.name for g in o.vertex_groups][:400]}
    for o in new:
        bpy.data.objects.remove(o, do_unlink=True)
    try:
        bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)
    except Exception:                                       # noqa: BLE001
        pass
    return out


def _socket_in(read: dict, socket: str = SOCKET) -> dict:
    """Where the socket bone ended up in a re-imported FBX (any name containing 'socket')."""
    for arm in read.get("armatures", {}).values():
        hits = [n for n in arm["bones"] if "socket" in n.lower()]
        if hits:
            name = socket if socket in hits else hits[0]
            return {"found": True, "name": name, "parent": arm["bones"][name], "all_matches": hits}
    return {"found": False}


def _add_socket(st: dict) -> dict:
    """cc_socket_* deform bone under hand.r, plus a small prop skinned 100% to it (spec 9.6)."""
    rig = _rig(st)
    H = max(rig.dimensions.z, 0.1)
    _select_only(rig)
    bpy.ops.object.mode_set(mode="EDIT")
    eb = rig.data.edit_bones
    hand = eb.get("hand.r") or next((b for b in eb if b.name.startswith("hand") and b.name.endswith(".r")), None)
    if hand is None:
        _to_object_mode()
        raise RuntimeError("no hand.r bone")
    s = eb.new(SOCKET)
    s.head = hand.tail.copy()
    s.tail = s.head + (hand.tail - hand.head).normalized() * 0.1 * H
    s.parent = hand
    s.use_connect = False
    s.use_deform = True
    owner = hand.name
    _to_object_mode()
    bpy.ops.mesh.primitive_cube_add(size=0.03 * H, location=rig.matrix_world @ rig.data.bones[SOCKET].head_local)
    prop = bpy.context.active_object
    prop.name = "probe_prop"
    vg = prop.vertex_groups.new(name=SOCKET)
    vg.add(list(range(len(prop.data.vertices))), 1.0, "REPLACE")
    m = prop.modifiers.new("Armature", "ARMATURE")
    m.object = rig
    m.use_deform_preserve_volume = False
    prop.parent = rig
    prop.matrix_parent_inverse = rig.matrix_world.inverted()
    st["prop"] = prop.name
    return {"socket": SOCKET, "owner": owner, "deform": rig.data.bones[SOCKET].use_deform}


def _export_variant(st: dict, label: str, engine: str, rig_type: str, extra: dict) -> dict:
    rig, body = _rig(st), bpy.data.objects[st["body"]]
    prop = bpy.data.objects.get(st.get("prop", ""))
    sc = bpy.context.scene
    path = os.path.join(st["out_dir"], f"probe_{label}.fbx")
    if os.path.exists(path):
        os.remove(path)
    settings = {"arp_engine_type": engine, "arp_export_rig_type": rig_type, "arp_ge_sel_only": True, **extra}
    old = {k: getattr(sc, k) for k in settings if hasattr(sc, k)}
    out: dict = {"settings": settings, "missing_settings": sorted(k for k in settings if not hasattr(sc, k))}
    buf = io.StringIO()
    try:
        for k, v in settings.items():
            if hasattr(sc, k):
                setattr(sc, k, v)
        _to_object_mode()
        for o in bpy.context.view_layer.objects:
            o.select_set(False)
        for o in (body, prop, rig):
            if o is not None:
                o.hide_set(False)
                o.select_set(True)
        bpy.context.view_layer.objects.active = rig
        with _captured(buf), bpy.context.temp_override(**view3d_override()):
            out["call"] = list(bpy.ops.arp.arp_export_fbx_panel(filepath=path))
    finally:
        for k, v in old.items():
            setattr(sc, k, v)
        out["log_tail"] = _tail(buf.getvalue(), 15)
    out["exported"] = os.path.exists(path)
    out["file"] = os.path.basename(path)
    if not out["exported"]:
        out["socket"] = {"found": False, "reason": "no file written"}
        return out
    out["size"] = os.path.getsize(path)
    read = _import_fbx(path)
    out["socket"] = _socket_in(read)
    arms = list(read["armatures"].values())
    out["bone_count"] = sum(len(a["bones"]) for a in arms)
    out["bones"] = sorted(n for a in arms for n in a["bones"])[:400]
    out["meshes"] = {n: {"vertices": m["vertices"],
                         "socket_groups": [g for g in m["vertex_groups"] if "socket" in g.lower()],
                         "groups": len(m["vertex_groups"])} for n, m in read["meshes"].items()}
    out["prop_exported"] = any(m["socket_groups"] for m in out["meshes"].values())
    return out


def _probe_deform_names(st: dict) -> dict:
    rig = _rig(st)
    deform = sorted(b.name for b in rig.data.bones if b.use_deform)
    return {"deform_bones": deform, "deform_count": len(deform),
            "owner_bones": {n: n in rig.data.bones and rig.data.bones[n].use_deform for n in OWNER_BONES},
            "twist_bones": [n for n in deform if _named(n, "twist")][:40]}


def _probe_poles(st: dict) -> dict:
    """IK pole controls and IK constraints. ARP names a pole 'c_leg_pole' / 'c_arms_pole' + the
    limb's side, so a duplicated limb's pole is e.g. c_arms_pole_dupli_001.l."""
    rig = _rig(st)
    poles = sorted(b.name for b in rig.data.bones if "pole" in b.name.lower())
    iks = {}
    for pb in rig.pose.bones:
        for c in pb.constraints:
            if c.type == "IK":
                iks[pb.name] = {"target": getattr(c, "subtarget", ""), "pole": getattr(c, "pole_subtarget", ""),
                                "pole_angle": round(float(getattr(c, "pole_angle", 0.0)), 5),
                                "chain_count": getattr(c, "chain_count", None)}
    heads = {n: _v3(rig.data.bones[n].head_local) for n in poles[:24]}
    joints = {b.name: _v3(b.head_local) for b in rig.data.bones
              if re.match(r"(leg|forearm)(_dupli_\d+)?\.[lr]$", b.name)}
    return {"pole_bones": poles, "expected": {n: n in rig.data.bones for n in POLE_NAMES},
            "dupli_poles": [n for n in poles if "_dupli_" in n],
            "ik_constraints": iks, "pole_heads": heads, "knee_elbow_heads": joints}


def _poles_or_error(st: dict) -> dict:
    try:
        return {"status": "ok", **_probe_poles(st)}
    except Exception as exc:                                # noqa: BLE001
        return {"status": "error", "error": _err(exc)}


def _probe_rig_poles(st: dict, preset: str) -> dict:
    """IK pole names on another preset after match_to_rig (the dog's front legs, spec WP13)."""
    rig, _, _ = _append(preset)
    st["rig"] = rig.name
    rig, res, log = _match(rig)
    return {"preset": preset, "match": res, "log_tail": _tail(log, 8), **_probe_poles(st)}


def _bind_section(st: dict) -> dict:
    props = _scene_arp_props()
    eng = props.get("arp_bind_engine")
    pv = props.get("arp_bind_preserve")
    out = {"engine_items": [i.identifier for i in eng.enum_items] if eng is not None else None,
           "engine_default": _js(_prop_default(eng)) if eng is not None else None,
           "preserve_volume_prop": "arp_bind_preserve" if pv is not None else None,
           "preserve_volume_default": _js(_prop_default(pv)) if pv is not None else None,
           "scale_fix_prop": "arp_bind_scale_fix" if "arp_bind_scale_fix" in props else None}
    heat = st.get("bind_heat")
    if heat is None:
        try:
            heat, _ = _bind_once(st, "HEAT_MAP")
        except Exception as exc:                            # noqa: BLE001
            heat = {"error": _err(exc)}
    out["heat_map"] = heat
    out["modifier_preserve_volume"] = heat.get("modifier_preserve_volume")
    try:
        vox, _ = _bind_once(st, "PSEUDO_VOXELS")
        out["pseudo_voxels"] = {"ok": vox["vertex_groups"] > 0, **vox}
    except Exception as exc:                                # noqa: BLE001
        out["pseudo_voxels"] = {"ok": False, "error": _err(exc)}
    return out


# ----------------------------------------------------------------------------- parts

def _part_basics(rec: _Rec, args: dict):
    _item(rec, "operators", _probe_operators)
    yield 0.1
    _item(rec, "scene_props", _probe_scene_props)
    _item(rec, "limb_options", _probe_limb_options)
    _item(rec, "scale_fix", _probe_scale_fix)
    _humanoid_section(rec)
    yield 0.1
    for p in PROBE_PRESETS:
        _item(rec, f"presets.{p}", _probe_preset, p)
        yield 0.3
    _item(rec, "spine_count", _probe_spine_count, rec)
    _clear_scene()


def _part_bird(rec: _Rec, args: dict):
    # ARP 3.77.33 loads bird_44.blend on Blender >= 4.4 because bird.blend crashed Blender 5
    _item(rec, "presets.bird", _probe_preset, "bird")
    yield 0.3
    _clear_scene()


def _probe_multi_arm(st: dict) -> dict:
    """A second arm pair: does HUMANOID still pass, and are the extra arm bones exported? (spec 5.4)"""
    rig, _, _ = _append("human")
    st["rig"] = rig.name
    facial = _facial_off(rig)
    case = _add_case(st, "arm.l")
    rig, res, _ = _match(_rig(st))
    out = {"facial": facial, "arm_dupli_refs": case["new_ref_bones"], "match": res,
           "humanoid_check": _humanoid(rig)["humanoid"], "ik_poles": _poles_or_error(st)}
    body = _body_from_bones(rig)
    st["body"] = body.name
    bind, _ = _bind_once(st, "HEAT_MAP")
    out["bind"] = {k: bind.get(k) for k in ("result", "vertex_groups", "unweighted_vertices")}
    exp = _export_variant(st, "multi_arm_unity_humanoid", "UNITY", "HUMANOID", {})
    out.update(exported=exp["exported"], export=exp,
               dupli_bones_exported=sorted(n for n in exp.get("bones", []) if "dupli" in n))
    return out


def _part_multi_arm(rec: _Rec, args: dict):
    st: dict = {"out_dir": os.path.abspath(args.get("out_dir") or ".")}
    os.makedirs(st["out_dir"], exist_ok=True)
    _humanoid_section(rec)
    _item(rec, "multi_arm_export", _probe_multi_arm, st)
    yield 0.3
    _item(rec, "ik_poles.rigs.dog", _probe_rig_poles, st, "dog")
    yield 0.1
    _clear_scene()


def _part_wings(rec: _Rec, args: dict):
    """Only wings in this Blender: spec 9.5 allows arm_wings only if this does not crash."""
    st: dict = {}

    def wings():
        rig, _, _ = _append("human")
        st["rig"] = rig.name
        case = _add_case(st, "arm.l")
        root = next((n for n in case["new_ref_bones"] if n.startswith("arm_ref")), None) or case["new_root"]
        if root is None:
            raise RuntimeError("add_limb arm.l added no reference bones")
        prot = _set_limb_options(_rig(st), root, {"arm_wings": True})
        out = {"arm_dupli_refs": case["new_ref_bones"], "ref": root, "protocol": prot,
               "arm_wings_set": prot.get("changed_ok")}
        if prot.get("error"):                   # no wings: matching would test nothing
            return {**out, "status": "error", "error": f"arm_wings not set: {prot['error']}"}
        # if match_to_rig crashes Blender, what is known so far stays in the partial file
        rec.put("wings", {"status": "partial", "reason": "match_to_rig not done yet", **out})
        rec.start("wings")
        rig, res, log = _match(_rig(st))
        names = [b.name for b in rig.data.bones]
        out.update(match_ok=True, match=res, log_tail=_tail(log, 12),
                   feather_bones=sorted(n for n in names if _named(n, *WING_WORDS))[:200],
                   feather_deform=sorted(b.name for b in rig.data.bones
                                         if b.use_deform and _named(b.name, *WING_WORDS))[:200])
        return out

    _item(rec, "wings", wings)
    yield 0.3
    _clear_scene()


def _part_limbs(rec: _Rec, args: dict):
    st: dict = {}
    _humanoid_section(rec)

    def setup():
        rig, _, _ = _append("human")
        st["rig"] = rig.name
        return {"rig": rig.name, "facial": _facial_off(rig)}

    _item(rec, "limbs_setup", setup)
    items: list = []
    try:
        items = [i[0] for i in bpy.types.ARP_OT_add_limb.limbs]
    except Exception:                                       # noqa: BLE001
        try:
            items = [i.identifier for i in
                     bpy.ops.arp.add_limb.get_rna_type().properties["limbs_presets"].enum_items]
        except Exception as exc:                            # noqa: BLE001
            rec.r["errors"].append(f"add_limb.presets_items: {_err(exc)}")
    rec.put("add_limb", {"status": "ok", "presets_items": items, "cases": {}})
    yield 0.1
    _item(rec, "add_limb.cases.tail_first", _add_case, st, "tail")
    _item(rec, "add_limb.cases.ears_first", _add_case, st, "ears")
    yield 0.1
    _item(rec, "load_limb_settings", _probe_load_settings, st)
    _item(rec, "ref_bone_keys", _probe_ref_keys, st)
    rec.put("limb_protocol", {"status": "ok", "cases": {}, "note": LIVE_VALUES_NOTE})
    for case, ref, changes in (("arm_pinky_off", "arm_ref.l", {"finger_pinky": False}),
                               ("arm_ring_off", "arm_ref.l", {"finger_ring": False}),
                               ("neck_count_2", "neck_ref.x", {"neck_count": 2}),
                               ("tail_count_6", "tail_00_ref.x", {"tail_count": 6})):
        _item(rec, f"limb_protocol.cases.{case}", lambda r=ref, c=changes: _set_limb_options(_rig(st), r, c))
        yield 0.1
    _item(rec, "add_limb.cases.arm_dupli", _add_case, st, "arm.l")
    _item(rec, "humanoid_check.results.refs_with_arm_dupli", lambda: _humanoid(_rig(st)))
    yield 0.1
    _item(rec, "add_limb.cases.tail_dupli_left", _tail_dupli, st, ".l")
    _item(rec, "add_limb.cases.tail_dupli_right", _tail_dupli, st, ".r")
    _item(rec, "add_limb.cases.spline_ik", _add_case, st, "spline_ik")
    yield 0.1
    _item(rec, "add_limb.cases.ears_second", _add_case, st, "ears")
    _item(rec, "humanoid_check.results.refs_with_second_ears", lambda: _humanoid(_rig(st)))
    yield 0.1
    _item(rec, "disable_limb", _disable_ear, st)       # the right ear only: does the left one stay?
    yield 0.1
    _item(rec, "add_limb.after_match", _after_match, st)
    _item(rec, "humanoid_check.results.limbs_rig_after_match", lambda: _humanoid(_rig(st)))
    yield 0.1
    _item(rec, "add_limb.cases.kilt", _add_case, st, "kilt")      # last: kilt crashed Blender 4.4.0
    yield 0.1
    _clear_scene()


def _part_build(rec: _Rec, args: dict):
    st: dict = {"out_dir": os.path.abspath(args.get("out_dir") or ".")}
    os.makedirs(st["out_dir"], exist_ok=True)
    _humanoid_section(rec)

    def setup():
        rig, _, _ = _append("human")
        st["rig"] = rig.name
        facial = _facial_off(rig)
        rig, res, log = _match(rig)
        return {"rig": rig.name, "facial": facial, "match": res, "bones": len(rig.data.bones),
                "height": round(rig.dimensions.z, 4), "log_tail": _tail(log, 12)}

    _item(rec, "build_setup", setup)
    yield 0.2
    _item(rec, "deform_names", _probe_deform_names, st)
    _item(rec, "ik_poles", _probe_poles, st)
    _item(rec, "humanoid_check.results.human_after_match", lambda: _humanoid(_rig(st)))
    yield 0.1

    def body():
        b = _body_from_bones(_rig(st))
        st["body"] = b.name
        return {"body": b.name, "vertices": len(b.data.vertices)}

    _item(rec, "build_body", body)
    yield 0.1
    _item(rec, "chin", _probe_chin, st)
    yield 0.2
    _item(rec, "socket_setup", _add_socket, st)
    rec.put("socket_export", {"status": "ok", "variants": {}})
    for label, engine, rig_type, extra in EXPORTS:
        _item(rec, f"socket_export.variants.{label}", _export_variant, st, label, engine, rig_type, extra)
        yield 0.3
    _item(rec, "bind", _bind_section, st)
    yield 0.1
    _clear_scene()


def _part_headless(rec: _Rec, args: dict):
    def go():
        out: dict = {"background": bpy.app.background, "arp_loaded": True}
        try:
            rig, _, log = _append("human")
            out.update(append_ok=True, append_log=_tail(log, 8))
        except Exception as exc:                            # noqa: BLE001
            out.update(append_ok=False, append_error=_err(exc), match_ok=None)
            return out
        try:
            rig, res, log = _match(rig)
            out.update(match_ok=True, match=res, deform=sum(1 for b in rig.data.bones if b.use_deform))
        except Exception as exc:                            # noqa: BLE001
            out.update(match_ok=False, match_error=_err(exc))
        return out

    _item(rec, "headless", go)
    yield 0.1
    _clear_scene()


PROBE_PARTS = {"basics": _part_basics, "bird": _part_bird, "wings": _part_wings, "multi_arm": _part_multi_arm,
               "limbs": _part_limbs, "build": _part_build, "headless": _part_headless}


def run_rig_probe(args: dict):
    """Stage "arp_probe": one part of the Step 8 Auto-Rig Pro probe (see forge/arp_probe.py)."""
    part = args.get("part", "basics")
    rec = _Rec(part, args.get("partial"))
    rec.r["blender"] = _blender_info()
    rec.flush()
    if not bpy.app.background:
        yield 1.0                                   # let add-ons finish registering with the UI up
    rec.start("arp")
    try:
        rec.r["arp"] = _js(_arp_info())
    except Exception as exc:                                # noqa: BLE001
        rec.r["arp"] = {"loaded": has_op("arp.append_arp"), "error": _err(exc)}
    rec.r["_current"] = None
    rec.flush()
    if not rec.r["arp"].get("loaded"):
        if part == "headless":                      # that is the answer for this part
            rec.put("headless", {"status": "ok", "arp_loaded": False, "append_ok": False, "match_ok": None,
                                 "background": bpy.app.background,
                                 "note": "Auto-Rig Pro does not load in a Blender without a window"})
        return rec.r                                # forge/arp_probe.py marks the other sections skipped
    if part not in PROBE_PARTS:
        raise ValueError(f"unknown probe part {part!r}")
    yield from PROBE_PARTS[part](rec, args)
    rec.r["_current"] = None
    return rec.r
