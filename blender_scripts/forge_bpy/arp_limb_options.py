"""Change an Auto-Rig Pro limb's options without losing its other settings (spec 9.2).

Auto-Rig Pro's limb options button (arp.show_limb_params) applies every option of the limb at
once. An option left out of the call goes back to its default, so a call with only the wanted
option can quietly undo other settings (put five toes back on a hoof, reset a tail's controls).
The safe way, used by Step 8 (arp_rig.add_extras) and by the `forge arp-probe` check
(addon_trial), is `set_limb_options`:
  1. read the limb's current settings the way Auto-Rig Pro's own panel does: its
     load_limb_settings, run on a copy of the button's defaults, in Edit Mode;
  2. copy every value to plain Python before Edit Mode ends (some are live bone data that
     Blender frees when Edit Mode ends: they then read as garbage, or crash Blender);
  3. change only the wanted options and send every option back, with
     load_settings_when_exec=False (else Auto-Rig Pro reloads the old values over the new ones);
  4. if Auto-Rig Pro refuses that call, send only the options that differ from the defaults;
  5. read the settings again: the wanted ones must have changed and nothing else.
Forge never sends only the changed options: when the settings cannot be read first, nothing
is changed and the report says why.

Measured on the director's PC (Auto-Rig Pro 3.79.17, Blender 5.3, docs/research/
arp_3_79_probe.json): this changed fingers, neck count, tail count, tail side and wings with
nothing else changing. The same PC refused the face switch right after a fresh rig was added
("poll() failed, context is incorrect"), while every call after an added limb went through.
Auto-Rig Pro's check wants a selected reference bone that can be seen, and adding a limb shows
the reference bones, so the reference bone is made visible first (`show_ref`, what Auto-Rig
Pro's own Edit Reference Bones does). When Auto-Rig Pro still says no, the report carries what
its check saw (`poll_diagnostics`).

Nothing here raises from `set_limb_options` or `facial_off`: every problem comes back in the
report, in plain words.
"""

from __future__ import annotations

import contextlib
import inspect
import io
import math
import sys
from types import SimpleNamespace

import bpy

OP = "arp.show_limb_params"
# panel-only switches, never sent back as settings
UI_ONLY = {"arm_show_part", "leg_show_part", "facial_show_part", "kilt_ui_show",
           "reset_to_default_settings", "load_settings_when_exec"}
LIVE_VALUES_NOTE = (
    "load_limb_settings copies some values straight from EDIT bones as ID-property arrays (finger "
    "and toe colours: per_limb.*.edit_bone_values lists them). Blender frees those when Edit Mode "
    "ends, so they read empty or as garbage, or crash Blender. The spec 9.2 namespace protocol must "
    "copy every value to plain Python before leaving Edit Mode, as this probe does.")
# plain words for the report (short: Step 8 shows them after "right ear: 2 bones, not 12: " on
# one 60-character panel row)
WORDS = {"poll": "Auto-Rig Pro said no here",
         "no_reader": "its settings could not be read",
         "missing": "{ref} is missing",
         "not_a_limb": "no limb at {ref}",
         "not_kept": "Auto-Rig Pro did not keep it",
         "failed": "Auto-Rig Pro hit an error"}


def err(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"[:600]


def view3d() -> dict:
    """The 3D view to run Auto-Rig Pro's operators in ({} without a window)."""
    from .addon_trial import view3d_override
    try:
        return view3d_override()
    except Exception:                                       # noqa: BLE001
        return {}


def arp_module(attr: str):
    """Auto-Rig Pro's own module that defines `attr` (its path differs between installs and versions)."""
    for name, mod in list(sys.modules.items()):
        if mod is None or "auto_rig" not in name.lower():
            continue
        try:
            if callable(getattr(mod, attr, None)):
                return mod
        except Exception:                                   # noqa: BLE001
            continue
    return None


# ----------------------------------------------------------------------------- values

def js(v, depth: int = 0):
    """JSON-safe copy of a Blender / ARP value (ID properties, vectors, sets). Never raises: a
    value that cannot be read is recorded as such (one bad value must not end the probe)."""
    try:
        return _js_value(v, depth)
    except Exception as exc:                                # noqa: BLE001
        try:
            return f"<could not read {type(v).__name__}: {err(exc)}>"[:300]
        except Exception:                                   # noqa: BLE001
            return "<could not read this value>"


def _js_value(v, depth: int):
    if depth > 6:
        return str(v)[:200]
    if v is None or isinstance(v, (bool, int, str)):
        return v
    if isinstance(v, float):
        return round(v, 6) if math.isfinite(v) else str(v)
    if hasattr(v, "to_dict"):
        return js(v.to_dict(), depth + 1)
    if hasattr(v, "to_list"):
        return js(v.to_list(), depth + 1)
    if isinstance(v, dict):
        return {str(k): js(x, depth + 1) for k, x in list(v.items())[:2000]}
    if isinstance(v, (set, frozenset)):
        return sorted(str(x) for x in v)
    if hasattr(v, "bl_rna") and hasattr(v, "name"):
        return f"<{type(v).__name__} {v.name}>"
    try:
        return [js(x, depth + 1) for x in list(v)[:2000]]
    except TypeError:
        return str(v)[:200]


def plain(v, depth: int = 0):
    """A copy of an option value that no longer points into Blender data. ARP's
    load_limb_settings copies ID-property arrays straight from EDIT bones (the finger and toe
    colours); Blender frees those when Edit Mode ends, after which they read as empty or as
    garbage, or crash. So every value is copied while still in Edit Mode."""
    try:
        if v is None or isinstance(v, (bool, int, float, str)):
            return v
        if isinstance(v, (set, frozenset)):
            return set(v)                   # enum-flag options: the operator wants a set
        if depth > 6 or hasattr(v, "bl_rna"):
            return js(v)                    # a Blender struct is not an option value: its name
        if hasattr(v, "to_dict"):
            return {str(k): plain(x, depth + 1) for k, x in v.to_dict().items()}
        if hasattr(v, "to_list"):
            return [plain(x, depth + 1) for x in v.to_list()]
        if isinstance(v, dict):
            return {str(k): plain(x, depth + 1) for k, x in v.items()}
        return [plain(x, depth + 1) for x in v]
    except Exception:                                       # noqa: BLE001
        return js(v)


def norm(v):
    """For comparing: ID-property arrays, vectors and tuples as lists."""
    try:
        if hasattr(v, "to_list"):
            v = v.to_list()
        elif hasattr(v, "to_dict"):
            v = v.to_dict()
        if v is None or isinstance(v, (bool, int, float, str, bytes, dict, set, frozenset, list)):
            return v
        if hasattr(v, "bl_rna"):
            return v
        return list(v)
    except Exception:                                       # noqa: BLE001
        return v


def same(a, b) -> bool:
    a, b = norm(a), norm(b)
    if isinstance(a, float) or isinstance(b, float):
        try:
            return abs(float(a) - float(b)) < 1e-6
        except (TypeError, ValueError):
            return False
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    if isinstance(a, (set, frozenset, list)) and isinstance(b, (set, frozenset, list)):
        return sorted(map(str, a)) == sorted(map(str, b))   # an enum-flag value against a copy
    try:
        return bool(a == b)
    except Exception:                                       # noqa: BLE001
        return False


def prop_default(p):
    if getattr(p, "array_length", 0):
        return tuple(p.default_array)
    if p.type == "ENUM" and getattr(p, "is_enum_flag", False):
        return set(p.default_flag)
    return getattr(p, "default", None)


def op_defaults() -> dict:
    """Every option of the limb options button, at its default."""
    rna = bpy.ops.arp.show_limb_params.get_rna_type()
    return {p.identifier: prop_default(p) for p in rna.properties
            if p.identifier != "rna_type" and p.type not in ("POINTER", "COLLECTION")}


# ----------------------------------------------------------------------------- what ARP printed

class _Tee(io.TextIOBase):
    def __init__(self, buf: io.StringIO, out):
        self.buf, self.out = buf, out

    def write(self, s):
        self.buf.write(s)
        if self.out is not None:
            try:
                self.out.write(s)
                self.out.flush()                # the log must keep it if Blender then crashes
            except Exception:                               # noqa: BLE001
                pass
        return len(s)


@contextlib.contextmanager
def captured(buf: io.StringIO):
    """ARP explains itself with print(): keep what it prints while an operator runs (and still
    write it to the log, which is all that is left when Blender crashes)."""
    with contextlib.redirect_stdout(_Tee(buf, sys.stdout)):
        yield


def tail(text: str, n: int = 25) -> list:
    return [line[:300] for line in text.splitlines() if line.strip()][-n:]


# ----------------------------------------------------------------------------- the rig

def is_ref(b) -> bool:
    return "_ref" in b.name and not b.name.startswith("c_")


def edit_mode(rig) -> None:
    """`rig` the active, selected object, in Edit Mode (left as it is when it already is)."""
    vl = bpy.context.view_layer
    if vl.objects.active is rig and rig.mode == "EDIT":
        return
    act = vl.objects.active
    if act is not None and act.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for o in vl.objects:
        o.select_set(False)
    rig.select_set(True)
    vl.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")


def select_ref(rig, name: str) -> bool:
    """Edit Mode on `rig` with the bone `name` alone selected and active (False: no such bone)."""
    edit_mode(rig)
    eb = rig.data.edit_bones
    b = eb.get(name)
    if b is None:
        return False
    for x in eb:
        x.select = x.select_head = x.select_tail = False
    b.select = b.select_head = b.select_tail = True
    eb.active = b
    return True


def show_ref(rig, name: str) -> list:
    """Make the bone `name` and its bone collections visible (Edit Mode). Auto-Rig Pro changes a
    limb only through a selected bone that can be seen; this is what its own Edit Reference Bones
    button does. Returns what was hidden before."""
    shown: list = []
    b = rig.data.edit_bones.get(name)
    if b is None:
        return shown
    try:
        if b.hide:
            b.hide = False
            shown.append(f"{name} (hidden bone)")
    except Exception:                                       # noqa: BLE001
        pass
    for c in list(getattr(b, "collections", None) or []):
        while c is not None:
            try:
                if not c.is_visible:
                    c.is_visible = True
                    shown.append(c.name)
            except Exception:                               # noqa: BLE001
                pass
            c = getattr(c, "parent", None)
    return shown


def ref_parents(rig) -> dict:
    """Reference bone -> its parent's name (edit bones in Edit Mode, else the saved bones)."""
    bones = rig.data.edit_bones if rig.mode == "EDIT" else rig.data.bones
    return {b.name: (b.parent.name if b.parent else None) for b in bones if is_ref(b)}


def bone_key(rig, bone: str, key: str):
    """(bone found, the bone's stored value for `key` or None)."""
    bones = rig.data.edit_bones if rig.mode == "EDIT" else rig.data.bones
    b = bones.get(bone)
    if b is None:
        return False, None
    try:
        return True, plain(b.get(key))
    except Exception:                                       # noqa: BLE001
        return True, None


# ----------------------------------------------------------------------------- read, change, verify

def limb_state(rig, ref: str, defaults: dict):
    """Every current option of the limb `ref` belongs to, read the way ARP's panel reads it:
    load_limb_settings() on a namespace filled with the operator defaults (spec 9.2).
    Returns (values, other attributes ARP set, ARP's reports, names of values that were live
    edit-bone ID properties). Everything is copied to plain Python while still in Edit Mode.
    Raises LookupError when ARP's reader is not there and KeyError when `ref` is not."""
    mod = arp_module("load_limb_settings")
    if mod is None:
        raise LookupError("no Auto-Rig Pro module defines load_limb_settings")
    if not select_ref(rig, ref):
        raise KeyError(f"{ref} is not in the rig")
    ns = SimpleNamespace(**defaults)
    notes: list = []
    ns.report = lambda kind, msg: notes.append(str(msg))
    with bpy.context.temp_override(**view3d()):
        mod.load_limb_settings(ns)
    raw = {k: v for k, v in vars(ns).items() if k != "report"}
    live = sorted(k for k, v in raw.items() if hasattr(v, "to_list") or hasattr(v, "to_dict"))
    vals = {k: plain(raw.get(k)) for k in defaults}
    extra = {k: plain(v) for k, v in raw.items() if k not in defaults}
    return vals, extra, notes, live


def _poll_failed(exc: BaseException) -> bool:
    s = str(exc)
    return "poll() failed" in s or "context is incorrect" in s


def _call(kw: dict, buf: io.StringIO) -> None:
    with captured(buf), bpy.context.temp_override(**view3d()):
        bpy.ops.arp.show_limb_params("EXEC_DEFAULT", **kw)


def set_limb_options(rig, ref: str, changes: dict) -> dict:
    """Spec 9.2: read the limb's state, change only `changes`, verify the rest. Never raises.
    The report: ok, call_used ("all_keys", "non_default_keys" or "none" when already so),
    changed_ok, after, unexpected_changes; on a problem also error, stage, reason (plain words)
    and diagnostics (what Auto-Rig Pro's check saw). The rig is left in Edit Mode."""
    rep: dict = {"ref": ref, "changes": dict(changes), "ok": False}
    buf = io.StringIO()
    stage = "read"
    try:
        defaults = op_defaults()
        if not select_ref(rig, ref):
            rep.update(error=f"{ref} is not in the rig", stage=stage, reason=WORDS["missing"].format(ref=ref))
            return rep
        shown = show_ref(rig, ref)
        if shown:
            rep["shown"] = shown
        before, _, _, _ = limb_state(rig, ref, defaults)
        rep.update(limb_type=before.get("limb_type"), side=before.get("side"))
        if not before.get("limb_type"):
            rep.update(error=f"load_limb_settings found no limb at {ref}", stage=stage,
                       reason=WORDS["not_a_limb"].format(ref=ref))
            return rep
        if all(same(before.get(k), v) for k, v in changes.items()):
            rep.update(ok=True, call_used="none", changed_ok=True, after={k: before.get(k) for k in changes},
                       unexpected_changes={}, ref_after=ref)
            return rep
        pre = ref_parents(rig)
        kw = {k: v for k, v in before.items() if k not in UI_ONLY}
        kw.update(changes)
        kw.update(limb_type=before.get("limb_type"), side=before.get("side"), load_settings_when_exec=False)
        stage = "call"
        select_ref(rig, ref)
        try:
            _call(kw, buf)
            rep["call_used"] = "all_keys"
        except Exception as exc:                            # noqa: BLE001 - try the short form
            rep["all_keys_error"] = err(exc)
            if _poll_failed(exc):                           # the short form would meet the same check
                raise
            keep = set(changes) | {"limb_type", "side", "load_settings_when_exec"}
            select_ref(rig, ref)
            _call({k: v for k, v in kw.items() if k in keep or not same(v, defaults.get(k))}, buf)
            rep["call_used"] = "non_default_keys"
        stage = "verify"
        post = ref_parents(rig)
        ref_after = ref
        if ref not in post:                 # renamed (a new side): the root of what appeared
            new = {n: p for n, p in post.items() if n not in pre}
            roots = [n for n, p in new.items() if p not in new]
            stem = ref.split("_ref")[0]
            ref_after = next((n for n in roots if n.startswith(stem)), roots[0] if roots else ref)
            rep["renamed"] = {"gone": sorted(set(pre) - set(post))[:40], "new": sorted(new)[:40]}
        rep["ref_after"] = ref_after
        after, _, _, _ = limb_state(rig, ref_after, defaults)
        rep["changed_ok"] = all(same(after.get(k), v) for k, v in changes.items())
        rep["after"] = {k: after.get(k) for k in changes}
        rep["unexpected_changes"] = {k: [before.get(k), after.get(k)] for k in before
                                     if k not in changes and k not in UI_ONLY and k != "side"
                                     and not same(before.get(k), after.get(k))}
        rep["ok"] = bool(rep["changed_ok"])
        if not rep["ok"]:
            rep.update(stage=stage, reason=WORDS["not_kept"])
    except Exception as exc:                                # noqa: BLE001 - reported, never raised
        rep.update(ok=False, error=err(exc), stage=stage)
        rep["reason"] = (WORDS["poll"] if _poll_failed(exc) else WORDS["no_reader"] if isinstance(exc, LookupError)
                         else WORDS["missing"].format(ref=ref) if isinstance(exc, KeyError) else WORDS["failed"])
        rep["diagnostics"] = poll_diagnostics(rig, ref)
    finally:
        rep["log_tail"] = tail(buf.getvalue(), 10)
    return rep


def facial_off(rig) -> dict:
    """Face bones off on the head (Step 8 keeps them off until the face has a cut mouth and
    separate eyes). Auto-Rig Pro's human preset already has them off (its head_ref.x stores
    facial = 0), so nothing is sent then. Never raises. Returns {"facial": "already off" | "off"
    | "still on" | "no head", "reason" (when not off), "protocol" (the set_limb_options report)}."""
    out: dict = {}
    try:
        found, value = bone_key(rig, "head_ref.x", "facial")
    except Exception as exc:                                # noqa: BLE001 - then ask Auto-Rig Pro
        found, value = True, None
        out["read_error"] = err(exc)
    if not found:
        return {**out, "facial": "no head", "reason": WORDS["missing"].format(ref="head_ref.x")}
    if value is not None and not value:
        return {**out, "facial": "already off", "stored": value}
    r = set_limb_options(rig, "head_ref.x", {"facial": False})
    out["protocol"] = r
    if r.get("ok"):
        out["facial"] = "already off" if r.get("call_used") == "none" else "off"
    else:
        out.update(facial="still on", reason=r.get("reason") or WORDS["failed"])
    return out


# ----------------------------------------------------------------------------- why ARP says no

def operator_poll(idname: str) -> dict:
    """The Python class behind an operator and the source of its poll() (what it checks)."""
    out: dict = {}
    cls, seen = None, set()
    stack = list(bpy.types.Operator.__subclasses__())
    while stack:
        c = stack.pop()
        if c in seen:
            continue
        seen.add(c)
        stack.extend(c.__subclasses__())
        if getattr(c, "bl_idname", "") == idname:
            cls = c
            break
    if cls is None:
        return {"error": "operator class not found"}
    out["class"] = f"{cls.__module__}.{cls.__qualname__}"
    out["mro"] = [f"{k.__module__}.{k.__qualname__}" for k in cls.__mro__][:12]
    for k in cls.__mro__:
        if "poll" in k.__dict__:
            fn = k.__dict__["poll"]
            try:
                src = inspect.getsource(getattr(fn, "__func__", fn))[:3000]
                out.setdefault("poll_sources", []).append({"class": k.__qualname__, "source": src})
            except Exception as exc:                        # noqa: BLE001
                out.setdefault("poll_sources", []).append({"class": k.__qualname__, "error": err(exc)})
    return out


def _try(out: dict, key: str, fn) -> None:
    try:
        out[key] = fn()
    except Exception as exc:                                # noqa: BLE001
        out[key + "_error"] = err(exc)


def poll_diagnostics(rig=None, ref: str = "", idname: str = OP) -> dict:
    """What an operator's check (poll) sees, for the log when Auto-Rig Pro says 'context is
    incorrect': its poll source, the mode, the active object, the active and selected edit
    bones, what Blender counts as selected and editable, and whether a 3D view was found.
    Never raises."""
    out: dict = {"operator": idname}
    try:
        out.update(operator_poll(idname))
    except Exception as exc:                                # noqa: BLE001
        out["poll_error"] = err(exc)
    ov: dict = {}
    try:
        ov = view3d()
        out["override"] = {k: ov.get(k) is not None for k in ("window", "area", "region")}
    except Exception as exc:                                # noqa: BLE001
        out["override_error"] = err(exc)
    ctx = bpy.context
    _try(out, "mode", lambda: ctx.mode)
    ob = None
    try:
        ob = ctx.view_layer.objects.active
    except Exception as exc:                                # noqa: BLE001
        out["active_object_error"] = err(exc)
    out["active_object"] = ob.name if ob is not None else None
    if ob is None:
        return out
    _try(out, "active_type", lambda: ob.type)
    _try(out, "active_mode", lambda: ob.mode)
    if rig is not None:
        _try(out, "active_is_rig", lambda: ob is rig)
    if ob.type != "ARMATURE":
        return out
    # Auto-Rig Pro's own is-this-a-rig test looks for the c_pos bone
    _try(out, "has_c_pos", lambda: ob.pose is not None and ob.pose.bones.get("c_pos") is not None)
    if ob.mode != "EDIT":
        return out
    eb = ob.data.edit_bones
    _try(out, "active_edit_bone", lambda: eb.active.name if eb.active is not None else None)
    _try(out, "selected_edit_bones", lambda: sorted(b.name for b in eb if b.select)[:40])
    if ref:
        _try(out, "ref_hidden", lambda: eb[ref].hide if ref in eb else None)
        _try(out, "ref_collections", lambda: {c.name: c.is_visible for c in eb[ref].collections} if ref in eb else None)

    def editable():
        with ctx.temp_override(**ov):
            sel = bpy.context.selected_editable_bones
            return {"mode": bpy.context.mode,
                    "bones": None if sel is None else sorted(b.name for b in sel)[:40]}
    _try(out, "selected_editable_bones", editable)
    return out
