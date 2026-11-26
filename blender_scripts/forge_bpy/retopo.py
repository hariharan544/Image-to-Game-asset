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


def _part_budgets(lows, total_budget: int, budget_scale: float, min_part: int) -> dict:
    areas = {o.name: _surface_area(o) for o in lows}
    total_area = sum(areas.values()) or 1.0
    return {o.name: max(int(total_budget * budget_scale * areas[o.name] / total_area), min_part) for o in lows}


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


def _finish_part(obj, part_budget: int, used: str, before: int, report: dict, quad_method: bool) -> None:
    split = _split_ngons(obj)
    after = C.tri_count(obj)
    # never exceed budget: final safety decimate (QR re-runs smaller first, see _qr_part)
    if after > part_budget * 1.05:
        _decimate(obj, part_budget)
        after = C.tri_count(obj)
        used += "+decimate"
    for p in obj.data.polygons:
        p.use_smooth = True
    report[obj.get(C.PART_PROP)] = {"budget": part_budget, "tris_before": before,
                                    "tris_after": after, "method": used, "ngons_split": split}


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
    lows = C.meshes_with_role("low")
    budgets = _part_budgets(lows, int(args["target_tris"]), float(args.get("budget_scale", 1.0)),
                            int(args.get("min_tris_per_part", 150)))
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

# Quad Remesher jobs that timed out keep running in their engine and import their result
# later: input name -> True. Their late "Retopo_<name>" objects are removed, never taken.
_QR_PENDING: dict = {}
STATUS = {"text": ""}          # what the running job is doing, for the panel


def _is_result_of(o, name: str) -> bool:
    r = "Retopo_" + name
    return o.name == r or (o.name.startswith(r + ".") and o.name[len(r) + 1:].isdigit())


def _purge_late_results() -> None:
    for name in list(_QR_PENDING):
        late = [o for o in bpy.data.objects if _is_result_of(o, name)]
        for o in late:
            bpy.data.objects.remove(o)
        src = bpy.data.objects.get(name)
        if src is not None:
            src.hide_set(False)           # the late import hid it again (hide_input)
        if late:
            _QR_PENDING.pop(name, None)


def _qr_part(obj, quads: int, args: dict, timeout: float):
    """Generator: remesh `obj` with Quad Remesher, replace its mesh with the result.
    Returns True on success. Measured on the user's PC: the operator returns
    RUNNING_MODAL at once; the result appears as a new object 'Retopo_<name>' and the
    source gets hidden."""
    from .addon_trial import view3d_override
    if args.get("_qr_refused"):
        return False                      # it refused once (licence / engine): don't wait again
    s = bpy.context.scene.qremesher
    s.target_count = max(int(quads), 20)
    from .density import only_qr_density
    painted = only_qr_density(obj.data)            # detail map (red = more quads, cyan = fewer)
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
    _purge_late_results()
    C.select_only(obj)
    before = {o.name for o in bpy.data.objects}
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
    t0, last, stable = time.time(), None, 0
    result = None
    while time.time() - t0 < timeout:
        yield 0.5
        _purge_late_results()
        # only this input's result: a late import of an earlier part must never be taken
        new = [o for o in bpy.data.objects
               if o.name not in before and o.type == "MESH" and _is_result_of(o, obj.name)]
        if new:
            faces = sum(len(o.data.polygons) for o in new)
            stable = stable + 1 if faces == last else 0
            last = faces
            if stable >= 2:
                result = max(new, key=lambda o: len(o.data.polygons))
                break
    if result is None:
        _QR_PENDING[obj.name] = True      # its result may still arrive: remove it then
        obj.hide_set(False)
        return False
    # bring the result into the low object (keeps its name, part tag, parent, modifiers)
    mesh = result.data.copy()
    mesh.transform(obj.matrix_world.inverted() @ result.matrix_world)
    _replace_mesh(obj, mesh)
    for o in [o for o in bpy.data.objects if o.name not in before and _is_result_of(o, obj.name)]:
        bpy.data.objects.remove(o)
    obj.hide_set(False)
    obj.vertex_groups.clear()
    return True


def _run_qr(args: dict):
    lows = C.meshes_with_role("low")
    budgets = _part_budgets(lows, int(args["target_tris"]), float(args.get("budget_scale", 1.0)),
                            int(args.get("min_tris_per_part", 150)))
    timeout = float(args.get("qr_timeout", 300))
    report: dict = {}
    for obj in lows:
        budget = budgets[obj.name]
        before = C.tri_count(obj)
        backup = obj.data.copy()
        target = budget * float(args.get("carve_headroom", 0.94)) / 2   # quads; room left for carving
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
        STATUS["text"] = f"{obj.name}: Quad Remesher"
        ok = yield from _qr_part(obj, target, args, timeout)
        used = "quadremesher"
        got = C.tri_count(obj) if ok else 0
        if ok and (got > budget * 1.05 or got < budget * 0.7):
            # QR's count is a target, not a cap (and a density map can make it undershoot):
            # one corrected re-run before any decimation
            target = target * (budget / max(got, 1)) * (0.95 if got > budget else 1.0)
            _replace_mesh(obj, backup.copy())
            STATUS["text"] = f"{obj.name}: Quad Remesher again (triangle count)"
            ok = yield from _qr_part(obj, target, args, timeout)
            used = "quadremesher(rerun)"
        if ok and args.get("conform", True):
            # fit to the original: after a symmetric remesh this restores one-sided details
            STATUS["text"] = f"{obj.name}: fitting to the original, carving face creases"
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
            if shape["lost_ratio"] >= max_lost and obj.get("forge_symmetry_x"):
                # mirrored and something got lost: a one-sided part (a tail curving to one side)
                # cannot survive a mirror. One run WITHOUT mirroring, fitted again
                obj["forge_symmetry_x"] = False
                keep = obj.data.copy()
                _replace_mesh(obj, backup.copy())
                STATUS["text"] = f"{obj.name}: shape lost while mirrored, Quad Remesher without mirror"
                ok2 = yield from _qr_part(obj, target, args, timeout)
                if ok2:
                    bpy.data.meshes.remove(keep)
                    _fit()
                    shape = shape_loss(backup, obj.data, tol)
                    shape["refined"], shape["rescued"] = 1, 0
                    used = "quadremesher(no-mirror)"
                else:
                    _replace_mesh(obj, keep)
            for _ in range(int(args.get("shape_retries", 1))):
                face_only = shape["lost_ratio"] < max_lost and shape.get("face_lost", 0) >= face_max
                if shape["lost_ratio"] < max_lost and not face_only:
                    break
                boost(backup, shape["mask"])          # includes flattened face details
                keep = obj.data.copy()
                _replace_mesh(obj, backup.copy())
                STATUS["text"] = (f"{obj.name}: face details flattened, Quad Remesher again denser there"
                                  if face_only else f"{obj.name}: shape lost, Quad Remesher again with more detail")
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
            if shape["lost_ratio"] >= max_lost and args.get("shape_rescue", True):
                # still missing: retopologize each lost region on its own and fuse it back
                from . import rescue
                total_area = max(rescue.area(backup), 1e-9)
                rescued = 0
                for ri, region in enumerate(rescue.regions(backup, shape.get("mask_thin", shape["mask"]))[:4]):
                    piece_me = rescue.extract(backup, region)
                    plug = list(piece_me["forge_plug"]) if "forge_plug" in piece_me else None
                    quads = max(150, int(target * 3 * rescue.area(piece_me) / total_area))
                    piece = bpy.data.objects.new(f"{obj.name}_rescue{ri}", piece_me)
                    piece.matrix_world = obj.matrix_world.copy()   # its mesh is in obj's space
                    piece["forge_rescue"] = True
                    for col in obj.users_collection:
                        col.objects.link(piece)
                    STATUS["text"] = f"{obj.name}: rebuilding thin part {ri + 1} (tail, horn...)"
                    ok3 = yield from _qr_part(piece, quads, args, timeout)
                    if ok3:
                        rescue.fuse(obj, piece, plug)
                        rescued += 1
                    # the remesher swaps the piece's mesh (and frees the old one): look both up by name
                    mesh_names = {piece.data.name}
                    if not ok3 and piece.name in _QR_PENDING:
                        piece.hide_set(True)      # QR may still import for it: removed later
                        continue
                    bpy.data.objects.remove(piece)
                    for name in mesh_names:
                        m = bpy.data.meshes.get(name)
                        if m is not None and m.users == 0:
                            bpy.data.meshes.remove(m)
                if rescued:
                    refined, shape = shape["refined"], shape_loss(backup, obj.data, tol)
                    shape["refined"], shape["rescued"] = refined, rescued
                    used = "quadremesher(rescued)"
        if not ok:
            _replace_mesh(obj, backup.copy())
            used = "quadremesher-failed>" + _retopo_part(obj, budget, "quadremesher", _opts(args))
        if ok and not fit["fitted"] and args.get("carve", True):
            from .density import carve, source_tree       # rescued / unfitted result: carve only
            fit["carve"] = carve(obj.data, backup, fit["tree"] or source_tree(backup))
        crease = {}
        if ok and args.get("carve", True):
            from .density import crease_kept
            crease = crease_kept(backup, obj.data)
        bpy.data.meshes.remove(backup)
        _finish_part(obj, budget, used, before, report, True)
        if crease or fit["carve"]:
            report[obj.get(C.PART_PROP)]["creases"] = {**crease, "carved_tris": fit["carve"].get("added", 0)}
        if shape is not None:
            report[obj.get(C.PART_PROP)]["shape"] = {
                "lost_pct": round(100 * shape["lost_ratio"], 2), "max_gap_pct": round(100 * shape["max_rel"], 2),
                "face_lost_pct": round(100 * shape.get("face_lost", 0.0), 2),
                "refined": shape["refined"], "rescued": shape.get("rescued", 0)}
    return {"parts": report, "total_tris": sum(r["tris_after"] for r in report.values())}
