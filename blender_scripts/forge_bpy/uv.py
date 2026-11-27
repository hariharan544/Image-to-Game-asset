"""Stage: UV unwrap + pack every low part, then measure UV quality.

Methods:
  smart        Smart UV Project (robust on any topology)
  angle_seams  mark seams on sharp edges + island borders, then angle-based unwrap
               (fewer, larger islands; better for organic shapes)
  min_stretch  same seams, Minimum Stretch unwrap
Each part gets its own 0-1 UV space (one texture set per part), which is what
makes props swappable.
"""

from __future__ import annotations

import math
import sys

import bmesh
import bpy

from . import common as C
from . import metrics


def _unwrap(obj, method: str, angle_deg: float, margin: float) -> None:
    C.select_only(obj)
    me = obj.data
    while me.uv_layers:
        me.uv_layers.remove(me.uv_layers[0])
    me.uv_layers.new(name="UVMap")
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    if method == "smart":
        bpy.ops.uv.smart_project(angle_limit=math.radians(angle_deg), island_margin=margin,
                                 area_weight=0.0, correct_aspect=True, scale_to_bounds=False)
    else:
        bpy.ops.uv.smart_project(angle_limit=math.radians(angle_deg), island_margin=margin)
        bpy.ops.uv.seams_from_islands(mark_seams=True)
        bm = bmesh.from_edit_mesh(me)
        for e in bm.edges:
            if len(e.link_faces) == 2 and e.calc_face_angle(0.0) > math.radians(angle_deg):
                e.seam = True
        bmesh.update_edit_mesh(me)
        bpy.ops.uv.unwrap(method="MINIMUM_STRETCH" if method == "min_stretch" else "ANGLE_BASED",
                          margin=margin)
    bpy.ops.object.mode_set(mode="OBJECT")


def unflip_islands(obj) -> int:
    """Turn mirror-image UV islands the right way round (text and painted details read
    correctly, every island has the same tangent handedness for normal maps). Each flipped
    island is mirrored inside its own box, so the packing and margins stay exactly as they
    are. Returns how many islands were turned."""
    from bpy_extras.bmesh_utils import bmesh_linked_uv_islands
    me = obj.data
    if not me.uv_layers:
        return 0
    bm = bmesh.new()
    bm.from_mesh(me)
    uv = bm.loops.layers.uv.active
    n = 0
    for island in bmesh_linked_uv_islands(bm, uv):
        area = 0.0
        for f in island:
            pts = [l[uv].uv for l in f.loops]
            for i in range(len(pts)):
                a, b = pts[i], pts[(i + 1) % len(pts)]
                area += a.x * b.y - b.x * a.y
        if area >= 0:
            continue
        us = [l[uv].uv.x for f in island for l in f.loops]
        mid = (min(us) + max(us))
        for f in island:
            for l in f.loops:
                l[uv].uv.x = mid - l[uv].uv.x
        n += 1
    if n:
        bm.to_mesh(me)
        me.update()
    bm.free()
    return n


def _pack(obj, margin: float) -> None:
    C.select_only(obj)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.select_all(action="SELECT")
    bpy.ops.uv.average_islands_scale()
    bpy.ops.uv.pack_islands(rotate=True, margin=margin, shape_method="CONCAVE")
    bpy.ops.object.mode_set(mode="OBJECT")


# ----------------------------------------------------------------------------- UVgami (seams)
# UVgami cuts the seams and flattens the pieces; UVPackmaster then packs. Driven through its own
# operator and settings, read from the add-on's source (2.5.0, GPL): uvgami.start on the
# selected meshes, Scene.uvgami settings, a job manager whose is_active turns False when the
# session is over. transfer_uvs writes the UVs onto Forge's own meshes. Whatever UVgami does not
# deliver falls back to Blender's unwrap.
#
# UVgami has three engines (src/engines): OptCuts (least stretch for the seam length, slow),
# PartUV (splits the model into parts first: fewer islands, can be faster on dense meshes) and
# xatlas (fast, made for lightmaps). Its panel unwraps with whichever the director picked last,
# so every Forge run sets the engine (and the engine's own settings) itself, then puts the
# director's settings back.
UVGAMI_WEIGHTS = "UVgami_seam_restrictions"      # its vertex group: the painted area (see face_seam_guard)
ENGINE_IDS = ("OPTCUTS", "PARTUV", "XATLAS")     # UVgami's ids; also Forge's fallback order
ENGINE_LABELS = {"OPTCUTS": "OptCuts", "PARTUV": "PartUV", "XATLAS": "xatlas"}
SPLIT_LABELS = {"AI": "AI split", "TREE": "tree split", "GEOMETRIC": "geometric split"}
# What a UVgami 2.5.0 engine does with painted weights (Engine.paint_is_seam_cost and
# paints_islands with each engine's supports_* flags), for when its engine objects cannot be
# read: every engine has supports_painted_islands, so the paint becomes its own island.
ENGINE_FLAGS_250 = {e: {"supports_guided": e == "OPTCUTS", "supports_painted_islands": True}
                    for e in ENGINE_IDS}
DOWNLOAD_HOW = "in Edit > Preferences > Add-ons > UVgami, press Download Engine under {}"
# UVgami's Priority shapes every engine's own cut (PartUV's --threshold, xatlas' --max-cost,
# OptCuts' bound and seam-border angle), so Forge sets it for every run instead of taking whatever
# the director last left in UVgami's panel. Balanced is UVgami's own default ("low stretching with
# moderate seams"): Less Stretch is the slowest and cuts the most seams (each seam a line a bake
# can show), Fewer Seams leaves visible stretch. Forge measures the stretch itself, and Compare
# engines ranks it first.
UVGAMI_PRIORITY = "BALANCED"
UVGAMI_PROXY = "AUTO"       # UVgami's default: a low-poly stand-in only for very large parts
UVGAMI_WEIGHT = 3           # UVgami's default strength of painted weights (OptCuts' seam weight)
_MODS: dict = {}


def _uvgami_module(suffix: str):
    """A module of the UVgami add-on by its name's end ('src.engines'...), or None."""
    import sys
    name = _MODS.get(suffix)
    if name and name in sys.modules:
        return sys.modules[name]
    for name, mod in list(sys.modules.items()):
        if "uvgami" in name and name.endswith(suffix):
            _MODS[suffix] = name
            return mod
    return None


def _uvgami_manager():
    mod = _uvgami_module("src.unwrap.manager")
    return getattr(mod, "manager", None) if mod is not None else None


def uvgami_status() -> str:
    """'' when UVgami can unwrap now, else why not (for the panel)."""
    from .addon_trial import has_op
    if not has_op("uvgami.start") or not hasattr(bpy.context.scene, "uvgami"):
        return "UVgami not installed"
    props = bpy.context.scene.uvgami
    try:
        if props.engine in ("", "NONE"):
            return "UVgami has no engine yet: press Download Engine in its panel"
    except (AttributeError, TypeError):
        return "UVgami settings not found"
    if _uvgami_manager() is None:
        return "UVgami version not supported (no job manager)"
    return ""


def uvgami_engines() -> list:
    """The engines this UVgami build has, in Forge's order: [{'id', 'label', 'installed',
    'available'}]. 'installed' = downloaded and ready (UVgami's own installed_engines());
    'available' = UVgami offers it for this computer (Engine.is_available: PartUV has no build
    for Intel Macs). [] without UVgami."""
    if not hasattr(bpy.context.scene, "uvgami"):
        return []
    known, have, gone = list(ENGINE_IDS), set(), set()
    mod = _uvgami_module("src.engines")
    if mod is not None and hasattr(mod, "installed_engines"):
        try:
            builds = getattr(mod, "ENGINES", None) or {}
            known = [e for e in ENGINE_IDS if e in builds] or known
            have = {str(getattr(e, "id", "")) for e in mod.installed_engines()}
            for e in known:
                fn = getattr(builds.get(e), "is_available", None)
                if fn is not None and not fn():
                    gone.add(e)
        except Exception as exc:                          # noqa: BLE001 - an add-on of another version
            print(f"[forge] UVgami engines not readable: {exc}")
    else:                                                 # no engine list: only the one its panel shows
        try:
            have = {str(bpy.context.scene.uvgami.engine)}
        except (AttributeError, TypeError):
            pass
    return [{"id": e, "label": ENGINE_LABELS[e], "installed": e in have, "available": e not in gone}
            for e in known]


def _engine_object(eid: str):
    mod = _uvgami_module("src.engines")
    try:
        return (getattr(mod, "ENGINES", None) or {}).get(eid) if mod is not None else None
    except AttributeError:
        return None


def face_guard_mode(eid: str) -> str:
    """What UVgami does with Forge's face paint (UVGAMI_WEIGHTS + use_weights) under this engine.
    It differs per engine, so it is read from the engine itself (UVgami's Engine.paints_islands /
    paint_is_seam_cost: painted islands win when an engine has both):
      'island'     the painted faces are cut out along the paint's edge and flattened as ONE
                   piece: no seam crosses the face, the seam runs round its edge. UVgami 2.5.0
                   does this under every engine (OptCuts, PartUV and xatlas).
      'seam_cost'  the engine puts fewer seams on painted points (OptCuts' guided cut, as in
                   older UVgami builds): seams avoid the face.
      'ignored'    the engine does not read paint: seams may cross the face. Forge then paints
                   nothing (use_weights stays off), so no stale paint can change the unwrap.
    Both of the first two mean what Forge wants - no seam across the face - so the guard stays
    on for them; an engine that would read the paint some other way would land in 'ignored'."""
    eng = _engine_object(eid)
    if eng is None:
        flags = ENGINE_FLAGS_250.get(eid, {})
    else:
        flags = {k: bool(getattr(eng, k, False)) for k in ("supports_guided", "supports_painted_islands")}
    if flags.get("supports_painted_islands"):
        return "island"
    if flags.get("supports_guided"):
        return "seam_cost"
    return "ignored"


def partuv_ai_ready() -> bool:
    """PartUV's AI split is downloaded (PartField, an NVIDIA card's CUDA)."""
    mod = _uvgami_module("src.engines.partuv")
    fn = getattr(mod, "is_ai_segmentation_available", None) if mod is not None else None
    try:
        return bool(fn()) if fn is not None else False
    except Exception:                                     # noqa: BLE001
        return False


def engine_missing(eid: str, engines=None) -> str:
    """Why this engine cannot be used now, in plain words with what to do. Only an engine this
    UVgami has, for this computer, can be downloaded: UVgami 2.5.0 says some of its builds ship
    without the xatlas and PartUV folders."""
    if engines is None:
        engines = uvgami_engines()
    label = ENGINE_LABELS.get(eid, eid)
    row = next((e for e in engines if e["id"] == eid), None)
    if engines and row is None:
        return f"Your UVgami comes without {label}."
    if row is not None and not row.get("available", True):
        return f"{label} doesn't run on this computer."
    return f"{label} isn't downloaded yet: {DOWNLOAD_HOW.format(label)}."


def resolve_engine(choice: str = "AUTO", winner: str = "", installed=None, engines=None) -> tuple:
    """(engine id to use, plain note). choice: 'AUTO' or an engine id; Auto = the engine that won
    Compare engines for this model (winner), else OptCuts. An engine that cannot be used is
    replaced by the first downloaded one, and the note says why (engine_missing). ('', '') when
    none is downloaded."""
    if engines is None:
        engines = uvgami_engines()
    if installed is None:
        installed = [e["id"] for e in engines if e["installed"]]
    want = choice if choice in ENGINE_IDS else (winner if winner in ENGINE_IDS else "OPTCUTS")
    if want in installed:
        return want, ""
    use = next((e for e in ENGINE_IDS if e in installed), "")
    if not use:
        return "", ""
    return use, f"{engine_missing(want, engines)} Used {ENGINE_LABELS[use]} this time."


def _on_mac() -> bool:
    return sys.platform == "darwin"


def partuv_ai_missing() -> str:
    """Why PartUV's AI split cannot be used, in plain words with what to do. Only a UVgami that
    has the AI part (src.engines.partuv.partfield: the Superhive build comes without it) offers
    its download, and never on a Mac (it runs on an NVIDIA card's CUDA)."""
    mod = _uvgami_module("src.engines.partuv")
    if mod is not None and hasattr(mod, "partfield") and getattr(mod, "partfield") is None:
        return "Your UVgami comes without PartUV's AI split."
    if _on_mac():
        return "PartUV's AI split needs an NVIDIA card, which a Mac doesn't have."
    return ("PartUV's AI split isn't downloaded yet (in Edit > Preferences > Add-ons > UVgami, press "
            "Download Engine under AI Segmentation; it needs an NVIDIA card).")


def resolve_split(choice: str = "AUTO", ai_ready=None) -> tuple:
    """PartUV's split: (mode, plain note). Auto = AI when it is downloaded, else Tree (splits by
    shape, nothing extra to download). Geometric clusters faces (faster, more seams)."""
    ai = partuv_ai_ready() if ai_ready is None else bool(ai_ready)
    if choice in ("TREE", "GEOMETRIC"):
        return choice, ""
    if choice == "AI" and not ai:
        return "TREE", f"{partuv_ai_missing()} Used the tree split this time."
    return ("AI" if ai else "TREE"), ""


def engine_label(eid: str, split: str = "") -> str:
    """'PartUV, tree split' / 'OptCuts'."""
    label = ENGINE_LABELS.get(eid, eid)
    return f"{label}, {SPLIT_LABELS[split]}" if eid == "PARTUV" and split in SPLIT_LABELS else label


UVGAMI_COLLECTIONS = ("UVgami Unwrapped", "UVgami Not Unwrapped")
UVGAMI_GRID = ("UVgami_grid", "uvgami_material_indices")     # its grid material, its saved slots
LAST = {"why": "", "cleaned": {}, "run": {}}                  # the last UVgami run, for the report


def _uvgami_collections() -> list:
    """UVgami's own collections (it names a second one '<name>.001')."""
    return [c for c in bpy.data.collections
            if c.name in UVGAMI_COLLECTIONS or c.name.rpartition(".")[0] in UVGAMI_COLLECTIONS]


def _uvgami_leftovers() -> set:
    return {o.name for c in _uvgami_collections() for o in c.all_objects}


def _uvgami_why(manager) -> str:
    """UVgami's own reason, in plain words ('' when it reported none)."""
    if manager is None:
        return ""
    if not getattr(manager, "transfer_uv_failed", False):
        msgs = [str(m) for m in (getattr(manager, "error_messages", None) or []) if m]
        if msgs:                            # e.g. "PartUV could not start (no CUDA device)"
            return f"its engine stopped: {msgs[0][:70]}"
        code = getattr(manager, "error_code", 0)
        return f"its engine failed (error {code})" if code else ""
    detail = str(getattr(manager, "transfer_uv_fail_detail", "") or "")
    if "multiple input faces" in detail or "multiple vertices" in detail:
        return "it could not put its UVs back: faces of the mesh lie on the same spot"
    if "timed out" in detail:
        return "it took too long"
    if "no matching input vertex" in detail or "no input face" in detail or "face_count" in detail:
        return "it could not put its UVs back: the mesh changed while it worked"
    return f"it could not put its UVs back ({detail[:60] or 'no reason given'})"


def _strip_uvgami_grid(obj) -> None:
    """UVgami's 'Auto Grid' puts its grid material on the mesh (all faces): take it off and
    give the faces their own materials back."""
    me = obj.data
    for i, m in enumerate(me.materials):
        if m is not None and m.name.split(".")[0] == UVGAMI_GRID[0]:
            me.materials.pop(index=i)
            break
    saved = me.get(UVGAMI_GRID[1])
    if saved is not None:
        saved = [int(i) for i in saved]              # (a copy: the property goes next)
        del me[UVGAMI_GRID[1]]
        if len(saved) == len(me.polygons):
            me.polygons.foreach_set("material_index", saved)


def _uvgami_ready(obj) -> dict:
    """UVgami puts its UVs back by matching positions: every face must have its own place.
    Points on the same spot are welded and faces on each other dropped first (the same gate
    as the end of Step 4). {'fixed': counts, 'stacked': left}"""
    from . import rescue
    me = obj.data

    def count():
        return int(rescue.stacked_faces(me).sum()) + int(rescue.doubled_points(me).sum())
    n = count()
    if not n:
        return {"fixed": {}, "stacked": 0}
    fixed = rescue.tidy(me)
    return {"fixed": {k: v for k, v in fixed.items() if v}, "stacked": count()}


def face_seam_guard(obj) -> int:
    """Paint the FACE (front of the head) in UVgami's weight group, so no seam crosses it. What
    the engine makes of the paint is face_guard_mode(): in UVgami 2.5.0 the face becomes one
    piece of its own and the seam runs round its edge (over the crown, beside the cheeks, under
    the chin), never across the eyes, muzzle or mouth."""
    import numpy as np

    from . import density, joints
    if obj.get("forge_kind", "body") != "body":
        return 0
    try:
        J = joints.estimate(obj)
    except Exception:                                  # noqa: BLE001 - a prop or an odd shape
        return 0
    V = joints._verts(obj)
    lab = density.region_labels(V, J)
    head = np.array(J["head"][0][:])
    front = float(J.get("_front", -1.0))
    face = (lab == 1) & ((V[:, 1] - head[1]) * front > 0)
    if not face.any():
        return 0
    g = obj.vertex_groups.get(UVGAMI_WEIGHTS) or obj.vertex_groups.new(name=UVGAMI_WEIGHTS)
    g.add([int(i) for i in np.nonzero(face)[0]], 1.0, "REPLACE")
    return int(face.sum())


def _uv_ok(obj) -> bool:
    """A usable UV map: every corner has finite coordinates, nearly every face has UV area."""
    import numpy as np
    me = obj.data
    if not me.uv_layers or me.uv_layers.active is None or not len(me.loops):
        return False
    uv = np.empty(len(me.loops) * 2, np.float32)
    me.uv_layers.active.data.foreach_get("uv", uv)
    if not np.isfinite(uv).all():
        return False
    uv = uv.reshape(-1, 2)
    ls = np.empty(len(me.polygons), np.int32)
    me.polygons.foreach_get("loop_start", ls)
    a, b = uv[ls], uv[np.minimum(ls + 1, len(uv) - 1)]
    c = uv[np.minimum(ls + 2, len(uv) - 1)]
    area = np.abs((b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (c[:, 0] - a[:, 0]) * (b[:, 1] - a[:, 1]))
    return bool((area > 1e-12).mean() > 0.98 and np.ptp(uv[:, 0]) > 0)


def _material_count(obj) -> int:
    """How many different materials the faces of this mesh use."""
    import numpy as np
    me = obj.data
    if len(me.materials) < 2 or not len(me.polygons):
        return min(len(me.materials), 1)
    idx = np.empty(len(me.polygons), np.int64)
    me.polygons.foreach_get("material_index", idx)
    used = {me.materials[int(i)] for i in np.unique(idx) if 0 <= int(i) < len(me.materials)}
    return len({m for m in used if m is not None} or {None})


RAW_ENUMS = ("engine", "segmentation")     # UVgami enums with their own get/set: kept as stored


def _set_settings(settings: list) -> list:
    """[(group, key, value)] -> what to put back. A setting the group does not have, or refuses
    (an engine that is not downloaded), is left alone."""
    keep = []
    for group, key, value in settings:
        if group is None or not hasattr(group, key):
            continue
        old = ("raw", group.get(key)) if key in RAW_ENUMS else ("attr", getattr(group, key))
        try:
            setattr(group, key, value)
        except (TypeError, ValueError):
            continue
        keep.append((group, key, old))
    return keep


def _put_back(keep: list) -> None:
    """The director's own UVgami settings back. The engine and PartUV's split are restored as
    stored, so 'whichever is first downloaded' stays that way."""
    for group, key, (how, old) in reversed(keep):
        try:
            if how == "attr":
                setattr(group, key, old)
            elif old is None:
                if group.get(key) is not None:
                    del group[key]
            else:
                group[key] = old
        except (TypeError, ValueError, KeyError, ReferenceError):
            pass


def _uvgami_cancel(manager) -> None:
    if manager is not None and (manager.is_active or getattr(manager, "pieces_still_arriving", 0)):
        try:
            bpy.ops.uvgami.cancel_all("EXEC_DEFAULT")
        except (RuntimeError, AttributeError):
            pass


def _uvgami_unwrap(objs: list, args: dict):
    """Generator: UVgami seams + unwrap for these meshes in one batch. Returns {name: ok}.
    args: uvgami_engine ('AUTO' or an engine id), uvgami_auto (Auto's engine: the comparison's
    winner), partuv_split ('AUTO', 'TREE', 'GEOMETRIC', 'AI'), guard_face, uvgami_minutes."""
    import time

    from .addon_trial import view3d_override
    out = {o.name: False for o in objs}
    LAST["why"], LAST["cleaned"], LAST["run"] = "", {}, {}
    if not objs or uvgami_status():
        return out
    asked = str(args.get("uvgami_engine", "AUTO") or "AUTO")
    eid, note = resolve_engine(asked, str(args.get("uvgami_auto", "") or ""))
    if not eid:
        LAST["why"] = "no UVgami engine is downloaded"
        return out
    split, split_note = resolve_split(str(args.get("partuv_split", "AUTO") or "AUTO")) \
        if eid == "PARTUV" else ("", "")
    run = LAST["run"] = {"asked": asked, "engine": eid, "split": split, "label": engine_label(eid, split),
                         "note": " ".join(n for n in (note, split_note) if n)}
    ready = []
    for o in objs:
        r = _uvgami_ready(o)
        if r["fixed"]:
            LAST["cleaned"][o.name] = r["fixed"]
        if r["stacked"]:                    # still faces on each other: Blender unwraps this one
            LAST["cleaned"].setdefault(o.name, {})["left"] = r["stacked"]
        else:
            ready.append(o)
    objs = ready
    if not objs:
        LAST["why"] = "faces of the mesh lie on the same spot"
        return out
    props = bpy.context.scene.uvgami
    leftovers = _uvgami_leftovers()         # (the director's own earlier UVgami results stay)
    collections = {c.name for c in _uvgami_collections()}
    shown = {o.name for o in objs if not o.hide_get()}
    # The face guard means "no seam across the face" under every engine, or it is not used:
    # see face_guard_mode (UVgami 2.5.0: the painted face becomes one island of its own).
    guard = face_guard_mode(eid) if args.get("guard_face", True) else "off"
    weighted = 0
    for o in objs:
        if not o.data.uv_layers:
            o.data.uv_layers.new(name="UVMap")
        if guard in ("island", "seam_cost"):
            weighted += face_seam_guard(o)
    if guard in ("island", "seam_cost") and not weighted:
        guard = "none"                      # no face found (props only, or no head)
    elif guard == "ignored" and not any(o.get("forge_kind", "body") == "body" for o in objs):
        guard = "none"
    # materials mark the borders between parts: a seam there costs nothing (each material gets
    # its own texture region anyway). One material = no borders to follow.
    multi = any(_material_count(o) > 1 for o in objs)
    run.update(face_guard=guard, face_points=int(weighted), material_seams=multi)
    settings = [
        (props, "engine", eid),             # first: what UVgami does depends on it
        (props, "transfer_uvs", True),      # onto Forge's own meshes (same vertices, same object)
        (props, "pack_after_unwrap", False),  # UVPackmaster packs
        (props, "import_uvs", False),       # UVgami cuts its own seams, never re-uses old UVs
        (props, "split_regions", True),     # each part of a character unwrapped on its own
        (props, "material_seams", multi),
        (props, "symmetry", False),         # mirrored stacked UVs would bake one side onto both
        (props, "stack_similar", False),    # the bake needs every spot its own place
        (props, "auto_grid", False),        # its grid material would replace the part's own
        (props, "keep_quads", True),
        (props, "use_weights", weighted > 0),
        (props, "unwrap_timeout", int(max(1, args.get("uvgami_minutes", 20)))),
        (props, "priority", UVGAMI_PRIORITY),   # shapes every engine's cut: never the panel's leftover
        (props, "proxy_mode", UVGAMI_PROXY),
        (props, "weight_value", UVGAMI_WEIGHT),
    ]
    if eid == "PARTUV":
        settings.append((getattr(props, "partuv", None), "segmentation", split))
    elif eid == "OPTCUTS":                  # organic or hard surface: chosen per loose part
        settings.append((getattr(props, "optcuts", None), "mode", "AUTO"))
    keep = _set_settings(settings)
    run.update(priority=str(getattr(props, "priority", "") or ""),          # what UVgami really got
               proxy=str(getattr(props, "proxy_mode", "") or ""))
    manager = _uvgami_manager()
    before = {o.name: _uv_array(o) for o in objs}
    try:
        C.select_only(*objs)
        ov = view3d_override()
        STATUS["text"] = f"{STATUS['step']}UVgami ({ENGINE_LABELS[eid]}): cutting seams on {len(objs)} part(s)"
        try:
            if ov:
                with bpy.context.temp_override(**ov):
                    res = bpy.ops.uvgami.start()
            else:
                res = bpy.ops.uvgami.start()
        except RuntimeError as exc:
            print(f"[forge] UVgami refused: {exc}")
            LAST["why"] = f"{ENGINE_LABELS[eid]} would not start"
            return out
        if "FINISHED" not in res:
            LAST["why"] = f"{ENGINE_LABELS[eid]} would not start"
            return out
        used, seen = eid, ""                # what it really runs (from the session it started)
        if getattr(manager, "is_active", False):
            used = getattr(getattr(manager, "engine", None), "id", "") or eid
            seen = getattr(getattr(getattr(manager, "props", None), "partuv", None), "segmentation", "")
        if used == "PARTUV" and seen in SPLIT_LABELS:
            split = seen
        run.update(engine=used, split=split if used == "PARTUV" else "", label=engine_label(used, split))
        t0 = time.time()
        limit = 60.0 * float(args.get("uvgami_minutes", 20)) + 30
        try:
            while (manager.is_active or getattr(manager, "pieces_still_arriving", 0) or
                   getattr(manager, "preparing", [])) and time.time() - t0 < limit:
                yield 0.5
                STATUS["text"] = (f"{STATUS['step']}UVgami ({ENGINE_LABELS.get(used, used)}): cutting "
                                  f"seams on {len(objs)} part(s) - {int(time.time() - t0)} s")
        except GeneratorExit:               # Stop: UVgami must not write onto the meshes later
            _uvgami_cancel(manager)
            raise
        if manager.is_active:                       # took too long: stop it, Blender unwraps
            _uvgami_cancel(manager)
            LAST["why"] = "it took too long"
            return out
        LAST["why"] = _uvgami_why(manager)
    finally:
        _put_back(keep)
        _uvgami_cleanup(objs, shown, leftovers, collections)
        STATUS["text"] = ""
    import numpy as np
    for o in objs:
        try:
            now = _uv_array(o)
            changed = now.shape != before[o.name].shape or not np.allclose(now, before[o.name])
            out[o.name] = bool(changed and _uv_ok(o))        # UVgami really delivered this part
        except ReferenceError:
            out[o.name] = False
    return out


def _uvgami_cleanup(objs, shown: set, leftovers: set, collections: set) -> None:
    """After UVgami: Forge's meshes visible as they were (a failed transfer hides them), no grid
    material on them, and no copies left behind in UVgami's collections from this run."""
    for o in objs:
        try:
            if o.name in shown and o.hide_get():
                o.hide_set(False)
            _strip_uvgami_grid(o)
        except ReferenceError:
            pass
    for c in _uvgami_collections():
        for o in list(c.all_objects):
            if o.name in leftovers:
                continue
            me = o.data if o.type == "MESH" else None
            bpy.data.objects.remove(o, do_unlink=True)
            if me is not None and me.users == 0:
                bpy.data.meshes.remove(me)
    for c in _uvgami_collections():
        if c.name not in collections and not c.all_objects and not c.children:
            bpy.data.collections.remove(c)


def _uv_array(o):
    import numpy as np
    me = o.data
    if not me.uv_layers or me.uv_layers.active is None:
        return np.zeros(0, np.float32)
    a = np.empty(len(me.loops) * 2, np.float32)
    me.uv_layers.active.data.foreach_get("uv", a)
    return a


STATUS = {"text": "", "step": ""}       # step: 'engine 2 of 3: ' while Compare engines runs


def _uvpm_ready() -> bool:
    from .addon_trial import has_op
    return has_op("uvpackmaster4.pack") and hasattr(bpy.context.scene, "uvpm4_props")


def run(args: dict):
    """Returns the result dict, or a generator when UVgami / UVPackmaster run (async engines)."""
    use_uvgami = args.get("unwrapper") == "uvgami" and not uvgami_status()
    if args.get("packer") == "uvpackmaster" and _uvpm_ready():
        return _run(args, use_uvpm=True, use_uvgami=use_uvgami)
    if use_uvgami:
        return _run(args, use_uvpm=False, use_uvgami=True)
    gen = _run(args, use_uvpm=False)
    try:
        while True:
            next(gen)
    except StopIteration as stop:
        res = stop.value
    if args.get("packer") == "uvpackmaster":
        res["packer_fallback_reason"] = "UVPackmaster 4 (or its engine) not available"
    return res


def _run(args: dict, use_uvpm: bool, use_uvgami: bool = False):
    """args['uvgami_only']: a part UVgami does not deliver gets no Blender unwrap (Compare engines
    measures the engine's own work only)."""
    import time
    t0 = time.time()
    method = args.get("method", "smart")
    angle = float(args.get("angle_limit_deg", 66.0))
    tex = int(args.get("texture_size", 2048))
    margin_px = float(args.get("margin_px", 8))
    margin = margin_px / tex
    smooth_angle = float(args.get("smooth_angle_deg", 40.0))

    report = {}
    lows = C.meshes_with_role("low")
    by_uvgami = {}
    if use_uvgami:
        by_uvgami = yield from _uvgami_unwrap(lows, args)
    for obj in lows:
        seams = "uvgami" if by_uvgami.get(obj.name) else "blender"
        note = "" if seams == "uvgami" or not use_uvgami else \
            ("UVgami: " + LAST["why"] if LAST["why"] else "UVgami gave no result for this part")
        if seams == "blender" and args.get("uvgami_only"):
            report[obj.get(C.PART_PROP)] = {"has_uv": False, "seams": "none", "seams_note": note}
            continue
        if seams == "blender":
            _unwrap(obj, method, angle, margin)
        packer = "blender"
        if use_uvpm:
            ok = yield from _uvpm_pack(obj, tex, margin_px, float(args.get("uvpm_search_time", 3.0)),
                                       float(args.get("uvpm_timeout", 120.0)))
            packer = "uvpackmaster" if ok else "uvpackmaster-failed>blender"
            if not ok:
                _pack(obj, margin)
        else:
            _pack(obj, margin)
        turned = unflip_islands(obj)
        C.select_only(obj)
        bpy.ops.object.shade_smooth_by_angle(angle=math.radians(smooth_angle))
        report[obj.get(C.PART_PROP)] = {**metrics.uv_metrics(obj, tex), **metrics.uv_layout(obj),
                                        "packer": packer, "unflipped": turned, "seams": seams,
                                        "seams_note": note,
                                        **({"cleaned": LAST["cleaned"][obj.name]}
                                           if use_uvgami and obj.name in LAST["cleaned"] else {})}
    out = {"parts": report, "seconds": round(time.time() - t0, 1)}
    if use_uvgami and LAST["run"]:
        out["uvgami_run"] = dict(LAST["run"])
    return out


# ----------------------------------------------------------------------------- Compare engines
# The same model, unwrapped once with every downloaded UVgami engine, each result packed the way
# Step 5 packs, measured with the same numbers, side by side. The meshes go back to how they were
# before every run, so each engine starts from the same mesh. The best result stays on the model
# and becomes Auto's engine for it.
#
# The score (pick_winner), in the order a bake cares about:
#   1. least stretch: the texel density spread (texel_density_cv, Step 5's "stretch"). A bake
#      shows every stretched spot as blur or smear. Within 0.02 of the best counts as a draw.
#   2. then the shortest seams (seam length / sqrt(surface area)): every seam is a place a bake
#      or a paint stroke can show a line. Within 10 % of the best counts as a draw.
#   3. then the fewest islands (pieces): fewer pieces = less margin lost, easier to paint.
#      Within 10 % counts as a draw.
#   4. then the fastest.
# Only an engine that delivered every part with nothing overlapping can win.
TIE_STRETCH = 0.02
TIE_SHARE = 0.10


def pick_winner(rows: list) -> tuple:
    """(engine id, why in plain words) by the score above; ('', why) when no engine can win."""
    pool = [r for r in rows if r.get("ok")]
    if not pool:
        return "", "no engine delivered every part"
    steps = (("stretch", lambda best: best + TIE_STRETCH, "least stretch"),
             ("seams", lambda best: best * (1 + TIE_SHARE), "shortest seams"),
             ("islands", lambda best: best * (1 + TIE_SHARE), "fewest islands"))
    why, alike = "", []
    for key, limit, words in steps:
        if len(pool) == 1:
            break
        top = limit(min(float(r[key]) for r in pool))
        kept = [r for r in pool if float(r[key]) <= top + 1e-9]
        if len(kept) < len(pool):
            why = words if not alike else f"{words} (stretch{'' if len(alike) == 1 else ' and seams'} about the same)"
        alike.append(key)
        pool = kept
    best = min(pool, key=lambda r: float(r.get("seconds") or 0.0))
    if len(pool) > 1:
        why = "fastest (the results are about the same)"
    elif not why:
        why = "the only engine with a full result"
    return best["engine"], why


def _score(rep: dict) -> dict:
    """One engine's numbers over the whole model (parts weighted by their surface)."""
    parts = list(rep.get("parts", {}).values())
    done = [p for p in parts if p.get("has_uv") and p.get("seams") == "uvgami"]
    row = {"parts": len(parts), "delivered": len(done)}
    if done:
        w = [max(float(p.get("area_m2") or 0.0), 1e-9) for p in done]
        tw = sum(w)
        row["stretch"] = round(sum(float(p.get("texel_density_cv") or 0.0) * x for p, x in zip(done, w)) / tw, 4)
        row["used"] = round(sum(float(p.get("utilization") or 0.0) * x for p, x in zip(done, w)) / tw, 4)
        row["seams"] = round(sum(float(p.get("seam_length_m") or 0.0) for p in done) / tw ** 0.5, 3)
        row["islands"] = int(sum(int(p.get("islands") or 0) for p in done))
        row["overlap_pct"] = max(float(p.get("overlap_pct") or 0.0) for p in done)
    why = ""
    if len(done) < len(parts):
        notes = [str(p.get("seams_note") or "") for p in parts if p not in done]
        note = next((n[len("UVgami: "):] for n in notes if n.startswith("UVgami: ")), "")
        if not done:
            why = note or "no result"
        else:
            why = f"no result for {len(parts) - len(done)} of {len(parts)} parts" + (f": {note}" if note else "")
    elif row.get("overlap_pct", 0.0) > 0.5:
        why = f"pieces overlap ({row['overlap_pct']:.1f}%)"
    row["ok"] = bool(done) and not why
    row["why"] = why
    return row


def _hold(objs: list) -> dict:
    """Keep every mesh exactly as it is: the object works on a copy from now on."""
    held = {"active": getattr(bpy.context.view_layer.objects.active, "name", ""), "objs": {}}
    for o in objs:
        me = o.data
        held["objs"][o.name] = {"obj": o, "mesh": me, "fake": me.use_fake_user,
                                "hide": o.hide_get(), "select": o.select_get()}
        me.use_fake_user = True                # (never lost, even if the file is saved meanwhile)
    return held


def _fresh(held: dict, results: dict) -> None:
    """Every object gets a new copy of its held mesh; the last run's copy goes unless it is a
    result being kept."""
    kept = {m.as_pointer() for r in results.values() for m in r.values()}
    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for h in held["objs"].values():
        o = h["obj"]
        work = o.data
        o.data = h["mesh"].copy()
        o.data.use_fake_user = False
        if work.as_pointer() not in kept | {h["mesh"].as_pointer()} and work.users == 0:
            bpy.data.meshes.remove(work)


def _settle(held: dict, results: dict, winner: str) -> None:
    """End of a comparison: the winner's meshes stay (under the original mesh names), or, with no
    winner / a failure / Stop, the held meshes come back. Nothing else is left behind."""
    if bpy.context.mode != "OBJECT":
        try:
            bpy.ops.object.mode_set(mode="OBJECT")
        except RuntimeError:
            pass
    keep = results.get(winner, {}) if winner else {}
    for name, h in held["objs"].items():
        o, orig = h["obj"], h["mesh"]
        try:
            work = o.data
            spare = work.as_pointer() != orig.as_pointer()      # (orig may be removed below)
            new = keep.get(name)
            if new is not None:
                o.data = new
                label = orig.name
                orig.use_fake_user = False
                if orig.users == 0:
                    bpy.data.meshes.remove(orig)
                    new.name = label
                new.use_fake_user = h["fake"]
            else:
                o.data = orig
                orig.use_fake_user = h["fake"]
            if spare and work.as_pointer() != o.data.as_pointer() and work.users == 0:
                bpy.data.meshes.remove(work)
        except ReferenceError:
            pass
        try:
            o.hide_set(h["hide"])
            o.select_set(h["select"])
        except (ReferenceError, RuntimeError):
            pass
    winners = {m.as_pointer() for m in keep.values()}
    for r in results.values():                  # the losers' meshes
        for m in r.values():
            try:
                if m.as_pointer() in winners:
                    continue
                m.use_fake_user = False
                if m.users == 0:
                    bpy.data.meshes.remove(m)
            except ReferenceError:
                pass
    act = bpy.data.objects.get(held["active"]) if held["active"] else None
    if act is not None:
        try:
            bpy.context.view_layer.objects.active = act
        except (RuntimeError, ReferenceError):
            pass


def compare(args: dict):
    """Generator: Compare engines. Returns {'rows': [...], 'winner', 'why', 'report' (the winner's
    Step 5 report, its UVs left on the model), 'meshes' {part: faces}}."""
    import time
    import traceback
    engines = [e for e in uvgami_engines() if e["installed"]]
    lows = C.meshes_with_role("low")
    status = uvgami_status()
    out = {"rows": [], "winner": "", "why": "", "report": {},
           "meshes": {str(o.get(C.PART_PROP)): len(o.data.polygons) for o in lows}}
    if status or not engines or not lows:
        out["why"] = status or ("no UVgami engine is downloaded" if not engines else "no new meshes yet")
        return out
    use_uvpm = args.get("packer") == "uvpackmaster" and _uvpm_ready()
    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    held = _hold(lows)
    results, reports, winner = {}, {}, ""
    try:
        for i, e in enumerate(engines, 1):
            eid = e["id"]
            _fresh(held, results)
            row = {"engine": eid, "label": ENGINE_LABELS[eid]}
            t0 = time.time()
            try:
                STATUS["step"] = f"engine {i} of {len(engines)}: "
                STATUS["text"] = f"Comparing engines: {ENGINE_LABELS[eid]} ({i} of {len(engines)})"
                rep = yield from _run(dict(args, uvgami_engine=eid, uvgami_only=True),
                                      use_uvpm=use_uvpm, use_uvgami=True)
                run = rep.get("uvgami_run") or {}
                row.update(_score(rep), split=run.get("split", ""), engine_used=run.get("engine", eid))
                if run.get("engine", eid) != eid:          # UVgami ran another engine: not this one's
                    row.update(ok=False, why=f"UVgami ran {ENGINE_LABELS.get(run['engine'], run['engine'])}")
                if row["ok"]:
                    results[eid] = {h["obj"].name: h["obj"].data for h in held["objs"].values()}
                    for m in results[eid].values():
                        m.use_fake_user = True
                    reports[eid] = rep
            except Exception as exc:                   # noqa: BLE001 - one engine must not stop the rest
                traceback.print_exc()
                row.update(ok=False, why=f"it failed ({type(exc).__name__}: {str(exc)[:60]})")
            row["seconds"] = round(time.time() - t0, 1)
            out["rows"].append(row)
        winner, out["why"] = pick_winner(out["rows"])
        if winner:
            reports[winner]["seconds"] = next(r["seconds"] for r in out["rows"] if r["engine"] == winner)
            out["report"] = reports[winner]
    finally:
        _settle(held, results, winner)         # also on Stop (GeneratorExit) and on an error
        STATUS["text"], STATUS["step"] = "", ""
    out["winner"] = winner
    out["meshes"] = {str(o.get(C.PART_PROP)): len(o.data.polygons) for o in lows}   # as they are now
    return out


# ----------------------------------------------------------------------------- UVPackmaster 4

def _uv_snapshot(obj) -> list:
    return [tuple(l.uv) for l in obj.data.uv_layers.active.data]


def _uvpm_pack(obj, tex: int, margin_px: float, search_time: float, timeout: float):
    """Generator: pack one part's islands into its own 0-1 tile with UVPackmaster 4.
    Measured on the user's PC: pack(mode_id="pack.single_tile") from a UV Editor context
    returns PASS_THROUGH/FINISHED and the engine updates the UVs ~1-3 s later."""
    import time

    from .addon_trial import view3d_override
    m = bpy.context.scene.uvpm4_props.default_main_props
    m.pixel_margin_enable = True                 # margin in pixels of *this* part's texture
    m.pixel_margin = int(round(margin_px))
    m.pixel_margin_tex_size = int(tex)
    m.rotation_enable = True
    m.rotation_step = 90
    if hasattr(m, "flipping_enable"):
        m.flipping_enable = False                # islands stay the right way round
    m.normalize_scale = True                     # equal texel density across islands
    m.fully_inside = True
    m.heuristic_enable = search_time > 0         # spend a few seconds searching for a tighter pack
    if search_time > 0:
        m.heuristic_search_time = int(search_time)
    C.select_only(obj)
    bpy.ops.object.mode_set(mode="OBJECT")
    before = _uv_snapshot(obj)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    ov = view3d_override()
    area = ov.get("area")
    old_ui = area.ui_type if area else None
    t0 = time.time()
    try:
        if area:
            area.ui_type = "UV"
            ov["region"] = next((r for r in area.regions if r.type == "WINDOW"), None)
            ov["space_data"] = area.spaces.active
        bpy.context.scene.tool_settings.use_uv_select_sync = True
        with bpy.context.temp_override(**ov):
            bpy.ops.uvpackmaster4.pack(mode_id="pack.single_tile")
    except Exception:
        if area:
            area.ui_type = old_ui
        bpy.ops.object.mode_set(mode="OBJECT")
        return False
    last, stable, changed = None, 0, False
    try:
        while time.time() - t0 < timeout:
            yield 0.5
            bpy.ops.object.mode_set(mode="OBJECT")
            cur = _uv_snapshot(obj)
            bpy.ops.object.mode_set(mode="EDIT")
            if cur != before:
                changed = True
                stable = stable + 1 if cur == last else 0
                last = cur
                if stable >= 3 and time.time() - t0 > search_time:
                    break
    finally:                                     # always give the director's 3D view back
        if area:
            area.ui_type = old_ui
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
    return changed
