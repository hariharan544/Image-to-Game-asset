"""Stage: retopology - rebuild every low part to a clean mesh inside the triangle budget.

Methods (chosen by the guide, changed by the supervisor on retry):
  quadremesher      Exoside Quad Remesher (paid add-on; best edge flow). Needs a windowed
                    Blender with user add-ons; the orchestrator arranges that. Falls back
                    to QuadriFlow per part when the add-on is missing, fails or times out.
  quadriflow        Blender's built-in quad remesher (needs a manifold mesh)
  voxel_quadriflow  voxel remesh first to force a manifold, then QuadriFlow
  decimate          collapse decimation - always works, triangles not quads
The chain falls through to the next method when one fails.
"""

from __future__ import annotations

import time

import bmesh
import bpy

from . import common as C

CHAIN = {
    "quadremesher": ["quadriflow", "voxel_quadriflow", "decimate"],   # fallback after QR
    "quadriflow": ["quadriflow", "voxel_quadriflow", "decimate"],
    "voxel_quadriflow": ["voxel_quadriflow", "decimate"],
    "decimate": ["decimate"],
}


def _surface_area(obj) -> float:
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    area = sum(f.calc_area() for f in bm.faces)
    bm.free()
    return area


def _replace_mesh(obj, src_mesh) -> None:
    old = obj.data
    obj.data = src_mesh
    if old.users == 0:
        bpy.data.meshes.remove(old)


def _quadriflow(obj, target_tris: int, opts: dict) -> bool:
    C.select_only(obj)
    try:
        res = bpy.ops.object.quadriflow_remesh(
            mode="FACES",
            target_faces=max(int(target_tris / 2), 50),   # quads -> 2 tris each
            use_mesh_symmetry=bool(obj.get("forge_symmetry_x", opts.get("symmetry_x", False))),
            use_preserve_sharp=bool(opts.get("preserve_hard_edges", True)),
            use_preserve_boundary=True,
            preserve_attributes=False,
            smooth_normals=False,
            seed=int(opts.get("seed", 0)),
        )
    except RuntimeError:
        return False
    return "FINISHED" in res and len(obj.data.polygons) > 0


def _voxel(obj, target_tris: int) -> None:
    area = max(_surface_area(obj), 1e-9)
    # pick a voxel size giving ~4x the target face count before QuadriFlow reduces it
    voxel = (area / max(target_tris * 4, 100)) ** 0.5
    mod = obj.modifiers.new("forge_voxel", "REMESH")
    mod.mode = "VOXEL"
    mod.voxel_size = voxel
    mod.adaptivity = 0.0
    C.apply_modifier(obj, mod.name)


def _decimate(obj, target_tris: int) -> bool:
    current = C.tri_count(obj)
    if current <= target_tris:
        return True
    mod = obj.modifiers.new("forge_decimate", "DECIMATE")
    mod.decimate_type = "COLLAPSE"
    mod.ratio = max(target_tris / current, 0.001)
    mod.use_collapse_triangulate = True
    C.apply_modifier(obj, mod.name)
    return True


def _retopo_part(obj, target_tris: int, method: str, opts: dict) -> str:
    backup = obj.data.copy()
    for step in CHAIN.get(method, CHAIN["quadriflow"]):
        # each attempt starts from the cleaned AI mesh
        _replace_mesh(obj, backup.copy())
        try:
            if step == "quadriflow" and _quadriflow(obj, target_tris, opts):
                break
            if step == "voxel_quadriflow":
                _voxel(obj, target_tris)
                if _quadriflow(obj, target_tris, opts):
                    break
            if step == "decimate" and _decimate(obj, target_tris):
                break
        except RuntimeError:
            continue
    else:
        step = "failed"
    bpy.data.meshes.remove(backup)
    # remeshing drops vertex groups / UVs; stale modifiers stay (armature) on purpose
    obj.vertex_groups.clear()
    return step


def _targets(args: dict):
    """The new meshes to make now, and each one's triangle budget. Redoing only some parts
    gives each the SAME share of the whole budget it gets in a full run (shares from the
    original parts' areas), so redoing the props never takes triangles from the body."""
    lows = C.meshes_with_role("low")
    total = int(args["target_tris"])
    scale = float(args.get("budget_scale", 1.0))
    min_part = int(args.get("min_tris_per_part", 150))
    only = set(args.get("only") or [])
    if not only:
        return lows, _part_budgets(lows, total, scale, min_part)
    from .rescue import area
    highs = {o.get(C.PART_PROP): o for o in C.meshes_with_role("high")}
    areas = {k: area(h.data) for k, h in highs.items()}
    tot = sum(areas.values()) or 1.0
    todo = [o for o in lows if o.get(C.PART_PROP) in only]
    budgets = {o.name: max(int(total * scale * areas.get(o.get(C.PART_PROP), 0.0) / tot), min_part) for o in todo}
    return todo, budgets


def _part_budgets(lows, total_budget: int, budget_scale: float, min_part: int) -> dict:
    areas = {o.name: _surface_area(o) for o in lows}
    total_area = sum(areas.values()) or 1.0
    return {o.name: max(int(total_budget * budget_scale * areas[o.name] / total_area), min_part) for o in lows}


ROUND_EDGES = 8          # a round part needs at least this many edges around to stay round
MIN_PIECE_QUADS = 64


def _plug_radius(plug) -> float:
    return float(plug[6]) if plug and len(plug) >= 7 else 0.0


def _piece_edge(edge: float, plug) -> float:
    """The quad size for a cut-off part: the body's quad size where it attaches, never so
    coarse that the part's round root gets fewer than ROUND_EDGES edges around."""
    import math
    r = _plug_radius(plug)
    return min(edge, 2 * math.pi * r / ROUND_EDGES) if r > 0 else edge


def _quads_for(area: float, edge: float) -> int:
    return max(MIN_PIECE_QUADS, int(area / max(edge, 1e-9) ** 2))


def _local_edge(me, plug) -> float | None:
    """Median length of the body's edges around a part's root (where it will sit). Looks
    wider when the neighbourhood is too small to measure."""
    import numpy as np
    r = _plug_radius(plug)
    if r <= 0 or not len(me.edges):
        return None
    co = np.empty(len(me.vertices) * 3, np.float32)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    ev = np.empty(len(me.edges) * 2, np.int32)
    me.edges.foreach_get("vertices", ev)
    ev = ev.reshape(-1, 2)
    root = np.array(plug[:3], np.float32)
    d = np.linalg.norm((co[ev[:, 0]] + co[ev[:, 1]]) / 2 - root, axis=1)
    length = np.linalg.norm(co[ev[:, 0]] - co[ev[:, 1]], axis=1)
    for reach in (3.0, 6.0, 12.0):
        m = d < reach * r
        if m.sum() >= 12:
            return float(np.median(length[m]))
    return None


def _split_ngons(obj) -> int:
    """Engines want tris and quads only; remeshers occasionally leave a few n-gons."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    ngons = [f for f in bm.faces if len(f.verts) > 4]
    if ngons:
        bmesh.ops.triangulate(bm, faces=ngons, quad_method="BEAUTY", ngon_method="BEAUTY")
        bm.to_mesh(obj.data)
        obj.data.update()
    bm.free()
    return len(ngons)


def _finish_part(obj, part_budget: int, used: str, before: int, report: dict, quad_method: bool,
                 joined: bool = False) -> None:
    split = _split_ngons(obj)
    after = C.tri_count(obj)
    over = 0
    # never exceed budget: final safety decimate (QR re-runs smaller first, see _qr_part).
    # Not on a mesh that already holds parts remeshed on their own and joined to it: each
    # part was held to its own share, and a collapse here crumples the joints - reported
    if after > part_budget * 1.05:
        if joined:
            over = after - part_budget
        else:
            _decimate(obj, part_budget)
            after = C.tri_count(obj)
            used += "+decimate"
    for p in obj.data.polygons:
        p.use_smooth = True
    report[obj.get(C.PART_PROP)] = {"budget": part_budget, "tris_before": before,
                                    "tris_after": after, "method": used, "ngons_split": split}
    if over:
        report[obj.get(C.PART_PROP)]["over_budget"] = int(over)


def _opts(args: dict) -> dict:
    return {"symmetry_x": args.get("symmetry_x", False),
            "preserve_hard_edges": args.get("preserve_hard_edges", True),
            "seed": args.get("seed", 0)}


def _shell_count(obj) -> int:
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    seen, shells = set(), 0
    for v in bm.verts:
        if v.index in seen:
            continue
        shells += 1
        stack = [v]
        while stack:
            cur = stack.pop()
            if cur.index in seen:
                continue
            seen.add(cur.index)
            stack.extend(e.other_vert(cur) for e in cur.link_edges)
    bm.free()
    return shells


def _displace(obj, dist: float) -> None:
    mod = obj.modifiers.new("forge_offset", "DISPLACE")
    mod.direction = "NORMAL"
    mod.mid_level = 0.0
    mod.strength = dist
    C.select_only(obj)
    bpy.ops.object.modifier_move_to_index(modifier=mod.name, index=0)
    bpy.ops.object.modifier_apply(modifier=mod.name)


def _fuse(obj, voxel_rel: float, max_tris: int, close_rel: float = 0.006) -> dict:
    """Melt all shells of a part into ONE watertight surface (voxel remesh), like a sculptor's
    DynaMesh before ZRemesher. Closes the gaps between touching pieces, open paper-thin parts
    (hair spikes) and holes, and drops buried duplicate geometry. The original detail is not
    lost: it is baked back from the untouched high mesh."""
    shells_before = _shell_count(obj)
    size = max(obj.dimensions) or 1.0
    close = size * close_rel
    if close > 0:                     # morphological close: inflate so touching pieces overlap ...
        _displace(obj, close)
    mod = obj.modifiers.new("forge_fuse", "REMESH")
    mod.mode = "VOXEL"
    mod.voxel_size = max(size * voxel_rel, 1e-4)
    mod.adaptivity = 0.0
    mod.use_smooth_shade = True
    C.select_only(obj)
    bpy.ops.object.modifier_move_to_index(modifier=mod.name, index=0)
    bpy.ops.object.modifier_apply(modifier=mod.name)
    if close > 0:                     # ... and deflate back to the original size
        _displace(obj, -close)
    if C.tri_count(obj) > max_tris:                 # keep the remesher's input reasonable
        _decimate(obj, max_tris)
    return {"shells_before": shells_before, "shells_after": _shell_count(obj),
            "voxel_size_m": round(size * voxel_rel, 5), "gap_closed_m": round(close * 2, 5)}


def run(args: dict):
    """Returns the result dict, or a generator (Quad Remesher waits on its engine)."""
    fused = {}
    if args.get("fuse_shells"):
        skip = set(args.get("detachable_parts", []))      # props are often hard-surface: keep edges
        for obj in C.meshes_with_role("low"):
            if obj.get(C.PART_PROP) not in skip:
                fused[obj.get(C.PART_PROP)] = _fuse(obj, float(args.get("fuse_voxel_rel", 0.004)),
                                                    int(args.get("fuse_max_tris", 400000)),
                                                    float(args.get("fuse_close_rel", 0.006)))
    res = _dispatch(args)
    if not fused:
        return res
    if isinstance(res, dict):
        res["fused"] = fused
        return res

    def wrap():
        out = yield from res
        out["fused"] = fused
        return out
    return wrap()


def _dispatch(args: dict):
    method = args.get("method", "quadriflow")
    if method == "quadremesher":
        from .addon_trial import has_op
        if has_op("qremesher.remesh") and hasattr(bpy.context.scene, "qremesher"):
            return _run_qr(args)
    return _run_builtin(args)


def _bounds(me):
    import numpy as np
    co = np.empty(len(me.vertices) * 3, np.float32)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    return (co.min(axis=0), co.max(axis=0)) if len(co) else None


def _same_place(src_me, new_me, tol: float = 0.2) -> bool:
    """The remeshed part still covers the original's box (within 20% of its size)."""
    import numpy as np
    a, b = _bounds(src_me), _bounds(new_me)
    if a is None or b is None:
        return False
    size = float(np.linalg.norm(a[1] - a[0])) or 1.0
    return float(np.abs(a[0] - b[0]).max()) < tol * size and float(np.abs(a[1] - b[1]).max()) < tol * size


def _run_builtin(args: dict) -> dict:
    method = args.get("method", "quadriflow")
    lows, budgets = _targets(args)
    report: dict = {}
    for obj in lows:
        before = C.tri_count(obj)
        if before <= budgets[obj.name] and not args.get("always_remesh", False):
            used = "kept (already within budget)"       # e.g. a low-poly prop
        else:
            keep = obj.data.copy()
            used = _retopo_part(obj, budgets[obj.name], method, _opts(args))
            if not _same_place(keep, obj.data):
                # the built-in remesher sometimes collapses thin boxes (measured: a sword came
                # back elsewhere, 91% bake misses): reduce the original instead
                _replace_mesh(obj, keep.copy())
                _decimate(obj, budgets[obj.name])
                used += ">broken>decimate"
            bpy.data.meshes.remove(keep)
        if method == "quadremesher":
            used = "quadremesher-unavailable>" + used
        _finish_part(obj, budgets[obj.name], used, before, report, True)
    return {"parts": report, "total_tris": sum(r["tris_after"] for r in report.values())}


# ----------------------------------------------------------------------------- Quad Remesher

# Quad Remesher jobs. The engine runs outside Blender and imports its result later as a new
# object "Retopo_<input name>", hiding the input. Principles:
#   - never recognise the result by predicting a long derived name: every job remeshes a
#     temporary copy named with a short, unique, never reused token, so the result name is
#     short (no length cut by the engine) and cannot clash with anything;
#   - track jobs, not names: a job that timed out or was stopped stays "abandoned" until its
#     late result shows up and is removed - it can never be taken for the current job;
#   - a wait is sized to the work, says what it waits for, and leaves the scene clean.
_QR_JOBS: dict = {}            # token -> {"state": "running" | "abandoned", "t": start, "limit": s}
_QR_SEQ = [0]
STATUS = {"text": ""}          # what the running job is doing, for the panel


def _qr_token() -> str:
    import os
    _QR_SEQ[0] += 1
    return f"fq{os.getpid() % 1000:03d}_{_QR_SEQ[0]:05d}z"      # fixed width: no prefix clashes


def _result_base(name: str) -> str | None:
    """The input name a result object stands for ("Retopo_<input>", maybe ".001")."""
    if not name.startswith("Retopo_"):
        return None
    base = name[7:]
    head, dot, tail = base.rpartition(".")
    if dot and tail.isdigit():
        base = head
    return base


def _is_result_of(o, token: str) -> bool:
    return _result_base(o.name) == token


def _short(name: str) -> str:
    return name if len(name) <= 26 else f"{name[:16]}~{name[-7:]}"


def _activate_collection_of(obj) -> None:
    def find(lc, col):
        if lc.collection == col:
            return lc
        for ch in lc.children:
            hit = find(ch, col)
            if hit:
                return hit
        return None
    try:
        col = obj.users_collection[0]
        lc = find(bpy.context.view_layer.layer_collection, col)
        if lc is not None:
            bpy.context.view_layer.active_layer_collection = lc
    except (IndexError, AttributeError, RuntimeError):
        pass


def _remove_object(o) -> None:
    me = o.data if o.type == "MESH" else None
    bpy.data.objects.remove(o)
    if me is not None and me.users == 0:
        bpy.data.meshes.remove(me)


def _purge_late_results(max_age: float = 7200.0) -> int:
    """Remove late results of abandoned jobs (and forget jobs too old to still deliver)."""
    n = 0
    now = time.time()
    for token, job in list(_QR_JOBS.items()):
        if job["state"] != "abandoned":
            continue
        late = [o for o in bpy.data.objects if _is_result_of(o, token)]
        for o in late:
            _remove_object(o)
            n += 1
        if late or now - job["t"] > max_age:
            _QR_JOBS.pop(token, None)
    return n


def cleanup_jobs() -> None:
    """Stop / a new run: temporary copies and stray results never stay in the scene, and a
    job whose result is removed here is retired with it (nobody waits for it any more)."""
    _purge_late_results()
    for o in list(bpy.data.objects):
        if o.get("forge_qr_proxy") or (o.name.startswith("Retopo_") and o.type == "MESH"):
            base = _result_base(o.name)
            if base in _QR_JOBS:
                _QR_JOBS.pop(base, None)
            _remove_object(o)


def _poll_late() -> float | None:
    """Timer while abandoned jobs exist: a result the engine delivers while Blender is idle
    (after a timeout or Stop) is removed at once, not left on top of the review mesh."""
    try:
        _purge_late_results()
    except ReferenceError:
        pass
    return 2.0 if any(j["state"] == "abandoned" for j in _QR_JOBS.values()) else None


def _watch_late() -> None:
    try:
        if not bpy.app.timers.is_registered(_poll_late):
            bpy.app.timers.register(_poll_late, first_interval=2.0, persistent=False)
    except (AttributeError, ValueError):
        pass


def _wait_limit(obj, timeout: float) -> float:
    """Seconds to wait for this input: a tail piece is done in seconds, a 5-million-triangle
    body can take many minutes."""
    return float(min(timeout, max(120.0, 60.0 + len(obj.data.polygons) / 5000.0)))


def _qr_part(obj, quads: int, args: dict, timeout: float):
    """Generator: remesh `obj` with Quad Remesher, replace its mesh with the result.
    Returns True on success. The engine works on a temporary copy named with a job token."""
    from .addon_trial import view3d_override
    if args.get("_qr_refused"):
        return False                      # it refused once (licence / engine): don't wait again
    label = STATUS["text"] or f"{_short(obj.name)}: Quad Remesher"
    # an abandoned job may still be running in the engine: let it finish first (bounded)
    t_wait = time.time()
    while any(j["state"] == "abandoned" and time.time() - j["t"] < j.get("limit", 120) for j in _QR_JOBS.values()) \
            and time.time() - t_wait < 120:
        STATUS["text"] = f"waiting for the previous Quad Remesher run {int(time.time() - t_wait)} s"
        yield 0.5
        _purge_late_results()
    for j in _QR_JOBS.values():
        if j["state"] == "abandoned":
            j["limit"] = 0                # waited enough for it: never wait for it again
    _purge_late_results()
    STATUS["text"] = label
    s = bpy.context.scene.qremesher
    s.target_count = max(int(quads), 20)
    token = _qr_token()
    proxy = bpy.data.objects.new(token, obj.data.copy())
    proxy.matrix_world = obj.matrix_world.copy()
    (obj.users_collection[0] if obj.users_collection else bpy.context.scene.collection).objects.link(proxy)
    proxy["forge_qr_proxy"] = True
    from .density import only_qr_density
    painted = only_qr_density(proxy.data)          # detail map (red = more quads, cyan = fewer)
    s.adaptive_size = float(args.get("qr_adaptive_size", 75.0 if painted else 50.0))
    # with a density map, keep the total near the budget and let the map move quads around
    s.adapt_quad_count = not painted
    s.use_vertex_color = painted
    s.use_materials = False
    s.use_normals = False
    # organic shapes: the angle detector smooths away soft creases; the map handles them
    s.autodetect_hard_edges = bool(args.get("preserve_hard_edges", not painted))
    s.symmetry_x = bool(obj.get("forge_symmetry_x", args.get("symmetry_x", False)))
    s.symmetry_y = s.symmetry_z = False
    C.select_only(proxy)
    _activate_collection_of(proxy)        # Quad Remesher imports its result into the active one
    before = {o.as_pointer() for o in bpy.data.objects}
    limit = _wait_limit(obj, timeout)
    job = {"state": "running", "t": time.time(), "limit": limit}
    result = None
    try:
        ov = view3d_override()
        if not ov:
            return False
        try:
            with bpy.context.temp_override(**ov):
                res = bpy.ops.qremesher.remesh()
        except RuntimeError:
            return False
        if not ({"RUNNING_MODAL", "FINISHED"} & set(res)):
            args["_qr_refused"] = True
            return False
        _QR_JOBS[token] = job
        t0, last, stable = time.time(), None, 0
        while time.time() - t0 < limit:
            yield 0.5
            STATUS["text"] = f"{label} - {int(time.time() - t0)} s"
            _purge_late_results()
            new = [o for o in bpy.data.objects if o.as_pointer() not in before and o.type == "MESH"
                   and not o.get("forge_qr_proxy")]
            mine = [o for o in new if _is_result_of(o, token)]
            if not mine:
                # second line of defence: the engine named it differently. One new result
                # object, in the copy's place, while the copy got hidden: that is ours
                others = {t for t in _QR_JOBS if t != token}
                cands = [o for o in new if o.name.startswith("Retopo_") and _result_base(o.name) not in others]
                if len(cands) == 1 and proxy.hide_get() and _same_place(proxy.data, cands[0].data, 0.25):
                    print(f"[forge] Quad Remesher named its result {cands[0].name!r} (expected Retopo_{token})")
                    mine = cands
            if mine:
                faces = sum(len(o.data.polygons) for o in mine)
                stable = stable + 1 if faces == last else 0
                last = faces
                if stable >= 2:
                    result = max(mine, key=lambda o: len(o.data.polygons))
                    break
        if result is None:
            return False
        # bring the result into the low object (keeps its name, part tag, parent, modifiers)
        mesh = result.data.copy()
        mesh.transform(obj.matrix_world.inverted() @ result.matrix_world)
        _replace_mesh(obj, mesh)
        for o in [o for o in bpy.data.objects if o.as_pointer() not in before and o.type == "MESH"
                  and (_is_result_of(o, token) or o == result)]:
            _remove_object(o)
        obj.hide_set(False)
        obj.vertex_groups.clear()
        return True
    finally:
        # timed out, refused, or stopped (the generator was closed): the copy goes; a job the
        # engine may still finish stays registered so its late result is removed, never taken
        if result is None and token in _QR_JOBS:
            _QR_JOBS[token]["state"] = "abandoned"
            _watch_late()
        else:
            _QR_JOBS.pop(token, None)
        try:
            _remove_object(proxy)
        except ReferenceError:            # already removed (Stop cleaned the scene)
            pass
        STATUS["text"] = label


def _run_qr(args: dict):
    lows, budgets = _targets(args)
    timeout = float(args.get("qr_timeout", 300))
    report: dict = {}
    for obj in lows:
        yield from _qr_one(obj, budgets[obj.name], args, timeout, report)
    return {"parts": report, "total_tris": sum(r["tris_after"] for r in report.values())}


def _qr_one(obj, budget: int, args: dict, timeout: float, report: dict):
    """One part through Quad Remesher (generator). Every temporary mesh of the part is freed
    in the end, also when the director presses Stop half-way (each is a copy of a part that
    can have millions of vertices)."""
    temp: list = []

    def keep_tmp(me):
        temp.append(me.name)
        return me
    try:
        before = C.tri_count(obj)
        backup = keep_tmp(obj.data.copy())
        headroom = float(args.get("carve_headroom", 0.94))
        target = budget * headroom / 2              # quads; room left for carving
        # ---- plan before remeshing: split off thin one-sided parts (tail...), make the body
        # symmetric from the chosen side. The remesher then gets a clean symmetric body and
        # nothing has to be rescued afterwards.
        from . import density as _dens
        from . import rescue as _rescue
        full_backup = None
        split_pieces = []
        split_report: list = []
        side = str(args.get("symmetry", "auto"))
        # the director's side applies to parts that straddle the body's middle (body, collar,
        # bell on the chest). A part off to one side (a prop laid out beside the body, an
        # earring) has no mirror twin across X = 0: mirroring it would make a second copy
        mirror = side in ("left", "right") and _dens.straddles_middle(backup)
        # mirror across the body's own middle, measured from its symmetry (not its box):
        # work in a frame where that middle is x = 0, and move the result back at the end
        shift = _dens.mirror_plane(backup) if mirror else 0.0
        if abs(shift) > 1e-6:
            from mathutils import Matrix
            backup.transform(Matrix.Translation((-shift, 0.0, 0.0)))
            backup.update()
        ids = _dens.read_split(backup) if args.get("split_thin", True) else None
        if mirror and not backup.get("forge_onesided_planned"):
            # (normally the parts plan made this decision and the director saw it; this is
            # for a body that never had a plan) whatever mirroring would copy or delete is
            # split off too and keeps its own shape
            import numpy as np
            extra = _dens.one_sided_parts(backup, ids)
            if extra.any():
                ids = np.where(extra > 0, extra, ids if ids is not None else 0).astype(np.int32)
        if ids is not None or mirror:
            full_backup = backup
            backup = keep_tmp(full_backup.copy())
            if ids is not None:
                STATUS["text"] = f"{_short(obj.name)}: cutting off the parts (tail...)"
                yield 0.05
                split_pieces = _rescue.split_off(backup, ids, split_report)
                for _k, pme, _p in split_pieces:
                    keep_tmp(pme)
            blocked = backup.get("forge_mirror_blocked") or full_backup.get("forge_mirror_blocked")
            if mirror and (split_report or blocked):
                # a one-sided part that could not be cut would be copied or deleted by the
                # mirror: this body is NOT mirrored (the director is told why)
                mirror = False
                obj["forge_symmetry_x"] = False
                split_report.append((0, f"not mirrored: {blocked or 'a one-sided part'} could not be cut off"))
            if mirror:
                STATUS["text"] = f"{_short(obj.name)}: making it symmetric from the {side} side"
                yield 0.05
                _dens.symmetrize(backup, side)
                obj["forge_symmetry_x"] = True
            _replace_mesh(obj, backup.copy())
        if side == "none" or (side in ("left", "right") and not mirror):
            obj["forge_symmetry_x"] = False
        piece_quads: list = []
        if split_pieces:
            # a cut-off part gets the SAME quad size as the body (one quad size across the
            # joint), never too coarse to stay round. Its share comes out of the body's
            # budget: reserved now from the body's average quad size, settled after the
            # body is done from the quad size the body really has where the part sits
            import math
            e_avg = math.sqrt(max(_rescue.area(full_backup), 1e-12) / max(target, 1.0))
            piece_quads = [int(1.1 * _quads_for(_rescue.area(pm), _piece_edge(e_avg, p)))
                           for _k, pm, p in split_pieces]
            target = max(target - sum(piece_quads), target * 0.5)
        # the body's own share of the triangles: the whole budget minus what the cut-off parts
        # reserved (each part's share is enforced where it is set)
        share = 2 * target / headroom
        fit = {"tree": None, "fitted": False, "carve": {}}

        def _fit():
            """Fit to the original, then cut narrow face creases in (local, adds only)."""
            from .density import carve, conform, source_tree
            if args.get("conform", True):
                conform(obj.data, backup, relax=int(args.get("conform_relax", 2)))
            if args.get("carve", True):
                if fit["tree"] is None:
                    fit["tree"] = source_tree(backup)
                fit["carve"] = carve(obj.data, backup, fit["tree"])
            fit["fitted"] = True
        STATUS["text"] = f"{_short(obj.name)}: Quad Remesher"
        ok = yield from _qr_part(obj, target, args, timeout)
        used = "quadremesher"
        got = C.tri_count(obj) if ok else 0
        if ok and (got > share * 1.05 or got < share * 0.7):
            # QR's count is a target, not a cap (and a density map can make it undershoot):
            # one corrected re-run before any decimation - towards the body's OWN share
            target = target * (share / max(got, 1)) * (0.95 if got > share else 1.0)
            _replace_mesh(obj, backup.copy())
            STATUS["text"] = f"{_short(obj.name)}: Quad Remesher again (triangle count)"
            ok = yield from _qr_part(obj, target, args, timeout)
            used = "quadremesher(rerun)"
        if ok and args.get("conform", True):
            # fit to the original: after a symmetric remesh this restores one-sided details
            STATUS["text"] = f"{_short(obj.name)}: fitting to the original, carving face creases"
            yield 0.05
            _fit()
        shape = None
        if ok and args.get("shape_check", True):
            # did a thin part (tail, tuft, nail tip) collapse? paint it denser and run again
            from .density import boost, shape_loss
            tol = float(args.get("shape_tolerance", 0.008))
            max_lost = float(args.get("shape_max_lost", 0.002))
            face_max = float(args.get("face_max_lost", 0.004))   # share of the face area
            shape = shape_loss(backup, obj.data, tol)
            shape["refined"] = 0
            shape["rescued"] = 0
            for _ in range(int(args.get("shape_retries", 1))):
                face_only = shape["lost_ratio"] < max_lost and shape.get("face_lost", 0) >= face_max
                if shape["lost_ratio"] < max_lost and not face_only:
                    break
                if not face_only and obj.get("forge_symmetry_x"):
                    break      # a thin part lost while mirrored: rebuild just that part (below)
                boost(backup, shape["mask"])          # includes flattened face details
                keep = keep_tmp(obj.data.copy())
                _replace_mesh(obj, backup.copy())
                STATUS["text"] = (f"{_short(obj.name)}: face details flattened, Quad Remesher again denser there"
                                  if face_only else f"{_short(obj.name)}: shape lost, Quad Remesher again with more detail")
                ok2 = yield from _qr_part(obj, target, args, timeout)
                if not ok2:
                    _replace_mesh(obj, keep)
                    break
                bpy.data.meshes.remove(keep)
                fit["fitted"] = False
                if face_only:
                    # (with a thin part lost, fitting would pull the stub towards it before the
                    # rebuild; only face refinement is fitted here - the rest at the end)
                    _fit()
                refined = shape["refined"] + 1
                shape = shape_loss(backup, obj.data, tol)
                shape["refined"] = refined
                shape["rescued"] = 0
                used = "quadremesher(face-refined)" if face_only else "quadremesher(shape-fixed)"
            # the thin-part rebuild is for real thin parts only, never pieces of the face
            is_prop = obj.get("forge_kind") == "prop"
            if is_prop and shape["lost_ratio"] >= max_lost:
                # a prop's lost bits are fine surface detail (curls, rope twist): the bake keeps
                # them as a normal map. Gluing rebuilt pieces on only leaves lumps and openings.
                # A big gap (a spear tip gone) is a lost SHAPE: it stays red, paint and re-run
                shape["detail_only"] = shape.get("max_rel", 0.0) < 0.03
            if shape["lost_ratio"] >= max_lost and args.get("shape_rescue", True) and not is_prop:
                # still missing: retopologize each lost region on its own and fuse it back -
                # kept only if the mesh comes out at least as clean as it went in
                from . import rescue
                total_area = max(rescue.area(backup), 1e-9)
                rescued = 0
                before_rescue = keep_tmp(obj.data.copy())
                defects0 = rescue.mesh_defects(obj.data)
                for ri, region in enumerate(rescue.regions(backup, shape.get("mask_thin", shape["mask"]))[:4]):
                    piece_me = rescue.extract(backup, region)
                    plug = list(piece_me["forge_plug"]) if "forge_plug" in piece_me else None
                    quads = max(150, int(target * 3 * rescue.area(piece_me) / total_area))
                    piece = bpy.data.objects.new(f"{obj.name}_rescue{ri}", piece_me)
                    piece.matrix_world = obj.matrix_world.copy()   # its mesh is in obj's space
                    piece["forge_rescue"] = True
                    for col in obj.users_collection:
                        col.objects.link(piece)
                    STATUS["text"] = f"{_short(obj.name)}: rebuilding thin part {ri + 1} (tail, horn...)"
                    ok3 = yield from _qr_part(piece, quads, args, timeout)
                    if ok3:
                        rescue.fuse(obj, piece, plug)
                        rescued += 1
                    # the remesher swaps the piece's mesh (and frees the old one): look both up by name
                    mesh_names = {piece.data.name}
                    bpy.data.objects.remove(piece)
                    for name in mesh_names:
                        m = bpy.data.meshes.get(name)
                        if m is not None and m.users == 0:
                            bpy.data.meshes.remove(m)
                d1 = rescue.mesh_defects(obj.data)
                if rescued and (d1[0] > defects0[0] or d1[1] > defects0[1]):
                    _replace_mesh(obj, before_rescue.copy())   # it made openings: undo it
                    rescued = 0
                    shape["rescue_undone"] = True
                if rescued:
                    refined, shape = shape["refined"], shape_loss(backup, obj.data, tol)
                    shape["refined"], shape["rescued"] = refined, rescued
                    used = "quadremesher(rescued)"
            if (shape["lost_ratio"] >= max_lost and obj.get("forge_symmetry_x") and not shape.get("rescued")
                    and not mirror):                             # never override the director's side
                # last resort: the thin-part rebuild could not bring it back. A run WITHOUT
                # mirroring (it re-rolls the whole mesh: the mirrored face is usually better,
                # which is why this comes last)
                obj["forge_symmetry_x"] = False
                keep = keep_tmp(obj.data.copy())
                _replace_mesh(obj, backup.copy())
                STATUS["text"] = f"{_short(obj.name)}: shape lost while mirrored, Quad Remesher without mirror"
                ok2 = yield from _qr_part(obj, target, args, timeout)
                if ok2:
                    bpy.data.meshes.remove(keep)
                    _fit()
                    flags = {k2: shape.get(k2) for k2 in ("detail_only", "rescue_undone")}
                    shape = shape_loss(backup, obj.data, tol)
                    shape["refined"], shape["rescued"] = 1, 0
                    shape.update({k2: v2 for k2, v2 in flags.items() if v2})
                    used = "quadremesher(no-mirror)"
                else:
                    _replace_mesh(obj, keep)
        if not ok:
            _replace_mesh(obj, (full_backup or backup).copy())
            for _k, pme, _p in split_pieces:      # the fallback keeps the whole original
                if pme.users == 0:
                    bpy.data.meshes.remove(pme)
            split_pieces = []
            obj["forge_symmetry_x"] = False       # (the original is not the mirrored body)
            used = "quadremesher-failed>" + _retopo_part(obj, budget, "quadremesher", _opts(args))
        piece_fallbacks: list = []
        joints: list = []
        if ok and not fit["fitted"] and args.get("carve", True):
            from .density import carve, source_tree       # rescued / unfitted result: carve only
            fit["carve"] = carve(obj.data, backup, fit["tree"] or source_tree(backup))
        if ok and split_pieces and C.tri_count(obj) > share * 1.05:
            # the body alone is over its share: reduce the body alone, now. Once a part is
            # joined to it nothing is decimated (a collapse there crumples the joint)
            _split_ngons(obj)
            _decimate(obj, int(share))
            used += "+decimate"
        if ok and split_pieces:
            from .density import conform
            for (k, pme, plug), reserved in zip(split_pieces, piece_quads):
                edge = _local_edge(obj.data, plug)       # the body's quad size where it sits
                quads = (min(reserved, _quads_for(_rescue.area(pme), _piece_edge(edge, plug)))
                         if edge else reserved)
                src = pme.copy()
                piece = bpy.data.objects.new(f"{obj.name}_part{k}", pme)
                piece.matrix_world = obj.matrix_world.copy()
                piece["forge_rescue"] = True
                for col in obj.users_collection:
                    col.objects.link(piece)
                piece["forge_symmetry_x"] = False
                STATUS["text"] = f"{_short(obj.name)}: thin part {k} on its own (tail...)"
                okp = yield from _qr_part(piece, quads, args, timeout)
                if okp:
                    conform(piece.data, src, relax=1)
                else:
                    # no Quad Remesher result: Blender's own quad remesher, then a reduced copy
                    _replace_mesh(piece, src.copy())
                    how = _retopo_part(piece, quads * 2, "quadriflow", _opts(args))
                    if how != "decimate" and not _same_place(src, piece.data):
                        _replace_mesh(piece, src.copy())
                        _decimate(piece, quads * 2)
                        how = "decimate"
                    piece_fallbacks.append({"quadriflow": "QuadriFlow", "voxel_quadriflow": "voxel + QuadriFlow",
                                            "decimate": "a reduced copy"}.get(how, "the cut piece as it was"))
                for a in list(piece.data.color_attributes):   # no detail-map colours on the result
                    piece.data.color_attributes.remove(a)
                STATUS["text"] = f"{_short(obj.name)}: joining thin part {k} to the body"
                yield 0.05
                info: dict = {}
                _rescue.weld(obj, piece, src, backup, full_backup or backup, info)
                joints.append({"part": k, "joint": info.get("joint", "attached"), "loops": info.get("loops", [])})
                names = {piece.data.name, src.name}
                bpy.data.objects.remove(piece)
                for n in names:
                    m = bpy.data.meshes.get(n)
                    if m is not None and m.users == 0:
                        bpy.data.meshes.remove(m)
            used += f"+{len(split_pieces)} part(s) separate"
        crease = {}
        if ok and args.get("carve", True):
            from .density import crease_kept
            crease = crease_kept(backup, obj.data)
        bpy.data.meshes.remove(backup)
        if full_backup is not None:
            bpy.data.meshes.remove(full_backup)
        if abs(shift) > 1e-6:
            from mathutils import Matrix
            obj.data.transform(Matrix.Translation((shift, 0.0, 0.0)))
            obj.data.update()
        _finish_part(obj, budget, used, before, report, True, joined=bool(split_pieces))
        r = report[obj.get(C.PART_PROP)]
        if joints:
            r["joints"] = joints
            bad = [j["joint"] for j in joints if j["joint"] != "welded"]
            r["joint"] = bad[0] if bad else "welded"
            if len(joints) == 1:
                r["joint_loops"] = joints[0]["loops"]
        # final gate: a game mesh must be closed. Small leftovers (doubles on a seam, a stray
        # point, a little hole) are tidied; anything bigger is reported and can be shown
        # (faces lying on each other and doubled points count too: the bake, the skinning
        # and UVgami - which puts UVs back by position - all need every face in its own place)
        def stacked():
            return int(_rescue.stacked_faces(obj.data).sum()) + int(_rescue.doubled_points(obj.data).sum())
        d = _rescue.mesh_defects(obj.data)
        st = stacked()
        if any(d) or st:
            fixed = _rescue.tidy(obj.data)
            if any(fixed.values()):
                r["tidied"] = fixed
            d = _rescue.mesh_defects(obj.data)
            st = stacked()
        r["open_edges"], r["bad_edges"], r["loose"] = int(d[0]), int(d[1]), int(d[2])
        r["stacked"] = st
        r["separate_parts"] = len(split_pieces)
        if piece_fallbacks:
            r["piece_fallbacks"] = piece_fallbacks
        if split_report:
            r["split_kept"] = [why for _k, why in split_report]
        if crease or fit["carve"]:
            report[obj.get(C.PART_PROP)]["creases"] = {**crease, "carved_tris": fit["carve"].get("added", 0)}
        if shape is not None:
            report[obj.get(C.PART_PROP)]["shape"] = {
                "lost_pct": round(100 * shape["lost_ratio"], 2), "max_gap_pct": round(100 * shape["max_rel"], 2),
                "face_lost_pct": round(100 * shape.get("face_lost", 0.0), 2),
                "refined": shape["refined"], "rescued": shape.get("rescued", 0),
                "detail_only": bool(shape.get("detail_only")), "rescue_undone": bool(shape.get("rescue_undone"))}
    finally:
        for name in temp:
            m = bpy.data.meshes.get(name)
            if m is not None and m.users == 0:
                bpy.data.meshes.remove(m)


