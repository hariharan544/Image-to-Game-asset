"""Stage: document the scripting surface of the paid add-ons in *this* Blender.

Reports, for Quad Remesher, UVPackmaster and Auto-Rig Pro:
  - module name, display name, version, enabled state
  - every operator in their bpy.ops namespaces, with parameters for the
    operators Forge is likely to drive (remesh / pack / smart rig / export ...)
  - their settings PropertyGroups on Scene / WindowManager with current values
Forge's add-on adapters are written against this report.
Run without --factory-startup.
"""

from __future__ import annotations

import addon_utils
import bpy

ADDONS = {
    "quad_remesher": {"names": ("quad remesher", "quad_remesh", "quadremesh", "qremesh"),
                      "ops_ns": ("qremesh", "quadremesh", "quad_remesh"),
                      "props": ("qremesh", "quadremesh", "quad_remesh"),
                      "focus": ("remesh",)},
    "uvpackmaster": {"names": ("uvpackmaster", "uvpm"),
                     "ops_ns": ("uvpackmaster", "uvpm"),
                     "props": ("uvpm", "uvpackmaster"),
                     "focus": ("pack", "engine", "group", "align", "scale", "texel")},
    "smart_remesh": {"names": ("smart remesh", "smart_remesh", "smartremesh"),
                     "ops_ns": (),                 # unknown: found by the add-on's own module below
                     "props": ("smart_remesh", "smartremesh", "srm", "sremesh"),
                     "focus": ("",),               # every operator with its parameters
                     "by_module": True, "files": True},
    "auto_rig_pro": {"names": ("auto-rig pro", "auto_rig_pro", "autorigpro", "auto rig pro"),
                     "ops_ns": ("arp",),
                     "props": ("arp",),
                     "focus": ("smart", "match", "bind", "export", "guess", "auto_scale", "init",
                               "skin", "retarget", "remap", "add_marker", "go_detect")},
}
MAX_FIELDS = 200


def _value(v):
    if isinstance(v, (bool, int, float, str)) or v is None:
        return v
    try:
        return list(v)[:16]
    except TypeError:
        return str(v)[:80]


def _op_params(op) -> list[dict]:
    out = []
    try:
        rna = op.get_rna_type()
    except Exception as exc:  # some add-on ops fail introspection
        return [{"error": str(exc)[:200]}]
    for p in rna.properties:
        if p.identifier == "rna_type":
            continue
        entry = {"id": p.identifier, "type": p.type}
        if p.type == "ENUM":
            entry["items"] = [i.identifier for i in p.enum_items][:40]
        try:
            d = getattr(p, "default", None)
            entry["default"] = _value(d)
        except Exception:
            pass
        out.append(entry)
    return out


def _group_fields(owner, attr) -> dict:
    grp = getattr(owner, attr, None)
    if grp is None or not hasattr(grp, "bl_rna"):
        return {"value": _value(grp)}
    fields = {}
    for p in list(grp.bl_rna.properties)[:MAX_FIELDS]:
        if p.identifier == "rna_type":
            continue
        try:
            v = getattr(grp, p.identifier)
            if hasattr(v, "bl_rna") and not isinstance(v, (str, bytes)):
                v = f"<{type(v).__name__}>"
            fields[p.identifier] = {"type": p.type, "value": _value(v)}
        except Exception as exc:
            fields[p.identifier] = {"type": p.type, "error": str(exc)[:80]}
    return fields


def run(args: dict) -> dict:
    mods = list(addon_utils.modules())
    report = {"blender": bpy.app.version_string, "addons": {}}
    for key, spec in ADDONS.items():
        found = []
        for m in mods:
            info = addon_utils.module_bl_info(m)
            hay = (m.__name__ + " " + info.get("name", "")).lower()
            if not any(n in hay for n in spec["names"]):
                continue
            entry = {"module": m.__name__, "name": info.get("name"),
                     "version": _value(info.get("version")),
                     "enabled_in_saved_prefs": m.__name__ in bpy.context.preferences.addons.keys(),
                     "loaded": addon_utils.check(m.__name__)[1]}
            if not entry["loaded"]:
                # turn it on for this process only (not saved), so the probe works even when
                # the preferences were never saved; record why if it refuses to load headless
                errors = []
                try:
                    addon_utils.enable(m.__name__, default_set=False, persistent=False,
                                       handle_error=lambda ex: errors.append(f"{type(ex).__name__}: {ex}"))
                except Exception as exc:
                    errors.append(f"{type(exc).__name__}: {exc}")
                entry["loaded_by_probe"] = addon_utils.check(m.__name__)[1]
                if errors:
                    entry["enable_errors"] = [e[:500] for e in errors]
            found.append(entry)
        ops = {}
        for ns in dir(bpy.ops):
            if not any(n in ns.lower() for n in spec["ops_ns"]):
                continue
            group = getattr(bpy.ops, ns)
            for name in dir(group):
                if name.startswith("_"):
                    continue
                full = f"{ns}.{name}"
                op = getattr(group, name)
                if any(f in name.lower() for f in spec["focus"]):
                    ops[full] = {"params": _op_params(op)}
                    try:
                        ops[full]["description"] = op.get_rna_type().description[:200]
                    except Exception:
                        pass
                else:
                    ops[full] = None          # listed, parameters not needed yet
        props = {}
        for owner_name, owner_type, owner in (("Scene", bpy.types.Scene, bpy.context.scene),
                                              ("WindowManager", bpy.types.WindowManager, bpy.context.window_manager)):
            for attr in dir(owner_type):
                if any(n in attr.lower() for n in spec["props"]):
                    props[f"{owner_name}.{attr}"] = _group_fields(owner, attr)
        if spec.get("by_module") and found:
            _by_module(found, spec, ops, props)
        report["addons"][key] = {"found": found, "operators": ops, "settings": props}
    return report


def _subclasses(cls):
    out = []
    for c in cls.__subclasses__():
        out.append(c)
        out += _subclasses(c)
    return out


def _by_module(found: list, spec: dict, ops: dict, props: dict) -> None:
    """An add-on whose operator namespace is not known: every registered operator, panel and
    settings group defined in its own module (and, for adapters, its source files and
    manifest: version and the Blender versions it declares)."""
    import os
    import sys
    mods = tuple(f["module"] for f in found)
    for cls in _subclasses(bpy.types.Operator):
        if not getattr(cls, "__module__", "").startswith(mods):
            continue
        idname = getattr(cls, "bl_idname", "")
        if "." not in idname:
            continue
        ns, name = idname.split(".", 1)
        op = getattr(getattr(bpy.ops, ns), name)
        entry = {"params": _op_params(op), "class": cls.__name__, "label": getattr(cls, "bl_label", ""),
                 "module": cls.__module__, "modal": hasattr(cls, "modal"), "invoke": hasattr(cls, "invoke")}
        try:
            entry["description"] = op.get_rna_type().description[:300]
        except Exception:
            pass
        ops[idname] = entry
    panels = []
    for cls in _subclasses(bpy.types.Panel):
        if getattr(cls, "__module__", "").startswith(mods):
            panels.append({"class": cls.__name__, "label": getattr(cls, "bl_label", ""),
                           "category": getattr(cls, "bl_category", ""), "space": getattr(cls, "bl_space_type", "")})
    props["_panels"] = panels
    groups = {}
    for owner_name, owner_type, owner in (("Scene", bpy.types.Scene, bpy.context.scene),
                                          ("WindowManager", bpy.types.WindowManager, bpy.context.window_manager),
                                          ("Object", bpy.types.Object, bpy.context.object)):
        if owner is None:
            continue
        for attr in dir(owner_type):
            try:
                val = getattr(owner, attr)
            except Exception:
                continue
            if hasattr(val, "bl_rna") and type(val).__module__.startswith(mods):
                groups[f"{owner_name}.{attr}"] = _group_fields(owner, attr)
    props.update(groups)
    if spec.get("files"):
        for f in found:
            m = sys.modules.get(f["module"])
            root = os.path.dirname(getattr(m, "__file__", "") or "")
            files = []
            for dp, _dn, fn in os.walk(root):
                for n in fn:
                    pth = os.path.join(dp, n)
                    files.append({"path": os.path.relpath(pth, root), "bytes": os.path.getsize(pth)})
            f["files"] = sorted(files, key=lambda x: x["path"])[:400]
            man = os.path.join(root, "blender_manifest.toml")
            if os.path.exists(man):
                f["manifest"] = open(man, encoding="utf-8", errors="ignore").read()[:3000]
