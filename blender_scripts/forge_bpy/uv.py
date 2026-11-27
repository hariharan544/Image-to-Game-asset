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
# UVgami cuts the seams and flattens the pieces (OptCuts: least stretch for the seam length);
# UVPackmaster then packs. Driven through its own operator and settings, read from the
# add-on's source (GPL): uvgami.start on the selected meshes, Scene.uvgami settings, a job
# manager whose is_active turns False when the session is over. transfer_uvs writes the UVs
# onto Forge's own meshes. Whatever UVgami does not deliver falls back to Blender's unwrap.
UVGAMI_WEIGHTS = "UVgami_seam_restrictions"      # its vertex group: weighted areas get no seams


def _uvgami_manager():
    import sys
    for name, mod in list(sys.modules.items()):
        if "uvgami" in name and name.endswith("src.unwrap.manager"):
            return getattr(mod, "manager", None)
    return None


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


UVGAMI_COLLECTIONS = ("UVgami Unwrapped", "UVgami Not Unwrapped")
UVGAMI_GRID = ("UVgami_grid", "uvgami_material_indices")     # its grid material, its saved slots
LAST = {"why": "", "cleaned": {}}                             # the last UVgami run, for the report


def _uvgami_collections() -> list:
    """UVgami's own collections (it names a second one '<name>.001')."""
    return [c for c in bpy.data.collections
            if c.name in UVGAMI_COLLECTIONS or c.name.rpartition(".")[0] in UVGAMI_COLLECTIONS]


def _uvgami_leftovers() -> set:
    return {o.name for c in _uvgami_collections() for o in c.all_objects}


def _uvgami_why(manager) -> str:
    """UVgami's own reason, in plain words ('' when it reported none)."""
    if manager is None or not getattr(manager, "transfer_uv_failed", False):
        return ""
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
    """Weight the FACE (front of the head) in UVgami's seam-restriction group, so the seams go
    round the back of the head and under the chin, where nobody looks."""
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


def _uvgami_unwrap(objs: list, args: dict):
    """Generator: UVgami seams + unwrap for these meshes in one batch. Returns {name: ok}."""
    import time

    from .addon_trial import view3d_override
    out = {o.name: False for o in objs}
    LAST["why"], LAST["cleaned"] = "", {}
    if not objs or uvgami_status():
        return out
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
    keep = {}
    want = {"transfer_uvs": True,           # onto Forge's own meshes (same vertices, same object)
            "pack_after_unwrap": False,     # UVPackmaster packs
            "symmetry": False,              # mirrored stacked UVs would bake one side onto both
            "stack_similar": False,         # the bake needs every spot its own place
            "auto_grid": False,             # its grid material would replace the part's own
            "keep_quads": True,
            "unwrap_timeout": int(max(1, args.get("uvgami_minutes", 20)))}
    leftovers = _uvgami_leftovers()         # (the director's own earlier UVgami results stay)
    collections = {c.name for c in _uvgami_collections()}
    shown = {o.name for o in objs if not o.hide_get()}
    weighted = 0
    for o in objs:
        if not o.data.uv_layers:
            o.data.uv_layers.new(name="UVMap")
        if args.get("guard_face", True):
            weighted += face_seam_guard(o)
    want["use_weights"] = weighted > 0
    for k, v in want.items():
        if hasattr(props, k):
            keep[k] = getattr(props, k)
            try:
                setattr(props, k, v)
            except (TypeError, ValueError):
                keep.pop(k, None)
    manager = _uvgami_manager()
    before = {o.name: _uv_array(o) for o in objs}
    try:
        C.select_only(*objs)
        ov = view3d_override()
        STATUS["text"] = f"UVgami: cutting seams on {len(objs)} part(s)"
        try:
            if ov:
                with bpy.context.temp_override(**ov):
                    res = bpy.ops.uvgami.start()
            else:
                res = bpy.ops.uvgami.start()
        except RuntimeError as exc:
            print(f"[forge] UVgami refused: {exc}")
            return out
        if "FINISHED" not in res:
            return out
        t0 = time.time()
        limit = 60.0 * float(args.get("uvgami_minutes", 20)) + 30
        while (manager.is_active or getattr(manager, "pieces_still_arriving", 0) or
               getattr(manager, "preparing", [])) and time.time() - t0 < limit:
            yield 0.5
            STATUS["text"] = f"UVgami: cutting seams on {len(objs)} part(s) - {int(time.time() - t0)} s"
        if manager.is_active:                       # took too long: stop it, Blender unwraps
            try:
                bpy.ops.uvgami.cancel_all("EXEC_DEFAULT")
            except RuntimeError:
                pass
            LAST["why"] = "it took too long"
            return out
        LAST["why"] = _uvgami_why(manager)
    finally:
        for k, v in keep.items():
            try:
                setattr(props, k, v)
            except (TypeError, ValueError):
                pass
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


STATUS = {"text": ""}


def run(args: dict):
    """Returns the result dict, or a generator when UVgami / UVPackmaster run (async engines)."""
    use_uvgami = args.get("unwrapper") == "uvgami" and not uvgami_status()
    if args.get("packer") == "uvpackmaster":
        from .addon_trial import has_op
        if has_op("uvpackmaster4.pack") and hasattr(bpy.context.scene, "uvpm4_props"):
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
        report[obj.get(C.PART_PROP)] = {**metrics.uv_metrics(obj, tex), "packer": packer,
                                        "unflipped": turned, "seams": seams,
                                        "seams_note": "" if seams == "uvgami" or not use_uvgami else
                                        ("UVgami: " + LAST["why"] if LAST["why"] else
                                         "UVgami gave no result for this part"),
                                        **({"cleaned": LAST["cleaned"][obj.name]}
                                           if use_uvgami and obj.name in LAST["cleaned"] else {})}
    return {"parts": report}


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
