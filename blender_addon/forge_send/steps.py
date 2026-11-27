"""Steps 4-9 of the in-Blender workflow (no UI). Each run_* returns a result dict or a
generator (it yields seconds to wait while an add-on engine works, then returns the dict);
stages_ui drives generators from a timer.

The mesh work reuses the pipeline's tested stage code (forge_bpy): a copy is installed
inside this add-on by `forge install-blender-addon`; in the repository it is imported
from blender_scripts/.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import bpy
from mathutils import Vector

from . import geometry as G


STATUS = {"text": ""}          # progress text of add-on side jobs (export...)


def fb():
    """The forge_bpy package (installed copy first, then the repository)."""
    try:
        from . import forge_bpy                     # noqa: F401
        return sys.modules[__package__ + ".forge_bpy"]
    except ImportError:
        root = Path(__file__).resolve().parents[2] / "blender_scripts"
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        import forge_bpy
        return forge_bpy


def _mod(name: str):
    import importlib
    pkg = fb()
    return importlib.import_module(f"{pkg.__name__}.{name}")


def C():
    return _mod("common")


def has_addon_op(path: str) -> bool:
    return _mod("addon_trial").has_op(path)


# ----------------------------------------------------------------------------- files

def work_dir() -> Path:
    """<blend folder>/<blend name>_forge - textures, exports, Tripo round trips."""
    if not bpy.data.filepath:
        raise RuntimeError("Save the .blend file first (Ctrl+S): textures and exports go next to it")
    p = Path(bpy.data.filepath)
    d = p.parent / f"{p.stem}_forge"
    d.mkdir(parents=True, exist_ok=True)
    return d


def asset_name() -> str:
    name = Path(bpy.data.filepath).stem if bpy.data.filepath else "asset"
    return C().safe_name(name).lower()


# ----------------------------------------------------------------------------- objects

def parts():
    return G.mesh_parts(bpy.context.scene)


def lows():
    return C().meshes_with_role("low")


def body_low():
    return next((o for o in lows() if G.kind(o) == "body"), None)


def _clear(role: str) -> None:
    for o in list(C().objects_with_role(role)):
        me = o.data if o.type == "MESH" else None
        bpy.data.objects.remove(o)
        if me is not None and me.users == 0:      # (a low can be a multi-million copy)
            bpy.data.meshes.remove(me)


def clear_rig() -> None:
    c = C()
    for o in list(bpy.data.objects):
        if o.type == "ARMATURE" and (o.get(c.ROLE_PROP) == "rig" or o.get("forge_arp") or o.get("forge_arp_helper")
                                     or o.get("forge_ref_rig")):
            bpy.data.objects.remove(o)
    for o in lows():
        for m in [m for m in o.modifiers if m.type == "ARMATURE"]:
            o.modifiers.remove(m)
        mw = o.matrix_world.copy()
        o.parent = None
        o.matrix_world = mw
        o.vertex_groups.clear()


# ----------------------------------------------------------------------------- step 4: retopology

def prepare_retopo(only=None) -> list:
    """Approved parts become the hidden 'high' sources; fresh copies become the 'low' meshes.
    only: part names to redo; every other part keeps the new mesh it already has."""
    c = C()
    clear_rig()
    _clear("lod")
    if only:
        for o in list(lows()):
            if o.get(c.PART_PROP) in only:
                me = o.data
                bpy.data.objects.remove(o)
                if me.users == 0:
                    bpy.data.meshes.remove(me)
    else:
        _clear("low")
    try:
        _mod("retopo").cleanup_jobs()             # first: retires the jobs of removed results
    except Exception:                             # noqa: BLE001
        pass
    # leftovers of a run that stopped half-way (rescue pieces, Quad Remesher results)
    for o in list(bpy.data.objects):
        if o.get("forge_rescue") or "_rescue" in o.name or o.name.startswith("Retopo_") \
                or o.get("forge_cage") or o.get("forge_qr_proxy"):
            bpy.data.objects.remove(o)
    for mod in ("retopo", "bake"):
        try:
            _mod(mod).STATUS["text"] = ""
        except Exception:                             # noqa: BLE001
            pass
    STATUS["text"] = ""
    low_col = c.get_collection(c.LOW_COLLECTION)
    out = []
    ps = parts()
    for p in ps:
        p.location.x = 0.0                     # "Compare with original" may have moved it aside
    bpy.context.view_layer.update()            # matrix_world must see that before bounds are read
    for p in ps:
        part = c.safe_name(p.name)
        if only and part not in only:
            continue
        p[G.ROLE] = G.kind(p) or "prop"        # keep body/prop before forge_role becomes "high"
        p[c.PART_PROP] = part
        p[c.ROLE_PROP] = "high"
        low = c.duplicate(p, f"{part}_low")
        c.move_to_collection(low, low_col)
        low[c.ROLE_PROP] = "low"
        low[c.PART_PROP] = part
        low[G.ROLE] = p[G.ROLE]
        lo, hi = G.world_bounds(p)
        size = max(hi - lo)
        # mirror symmetry only for parts centred on the body's middle (body, bell, collar)
        # mirror symmetry only for parts centred on the body AND really symmetric: otherwise the
        # remesher copies one-sided details (a notch in one ear) to the other side
        centred = abs((lo.x + hi.x) / 2) < 0.02 * size
        asym = _mod("density").asymmetry(p.data) if centred else 1.0
        low["forge_asymmetry"] = round(asym, 4)
        # mostly symmetric (a notch in one ear, a scar): remesh symmetric for even topology,
        # then "fit to original" puts the one-sided details back
        low["forge_symmetry_x"] = centred and asym < 0.10
        p.hide_set(True)
        out.append(low)
    return out


def ensure_detail_maps(strength: float, recompute: bool = False) -> int:
    """Detail map on every original part (kept on it: the director may paint over it)."""
    dens = _mod("density")
    n = 0
    for p in parts():
        me = p.data
        if recompute or dens.QR_ATTR not in me.color_attributes:
            factor = None
            if G.kind(p) == "body" and strength > 0:
                # spend the budget where it matters: face, hands, joints more; belly, back less
                try:
                    J = _mod("joints").estimate(p)
                    V = _mod("joints")._verts(p)
                    factor, lab, _names = dens.region_factors(V, J)
                    factor = factor ** strength
                    # the shape check is stricter on the face (label 1 = head)
                    import numpy as np
                    dens.write_strict(me, np.where(lab == 1, 0.35, 1.0))
                except Exception as exc:              # noqa: BLE001
                    print(f"[forge] region weights skipped: {exc}")
            dens.write_qr_density(me, dens.detail_score(me), strength, make_active=False, factor=factor)
            n += 1
    return n


def plan_parts(recompute: bool = False, side: str = "", paint: bool = True) -> dict:
    """The parts plan, made ONCE and used by the run (what the director sees is what runs):
    - thin parts without a twin (tail, antenna, trunk) are cut at their neck and remeshed on
      their own, then attached;
    - when a side is chosen for mirroring, parts that mirroring would copy or delete (a tail
      curling to one side) are cut the same way; pairs in another pose are not parts;
    - thick rigid parts (horns) get fewer quads; ears stay with the body.
    Stored on the body mesh (forge_split + forge_plan); the panel lists it in Step 4."""
    import numpy as np
    dens = _mod("density")
    parts_mod = _mod("parts")
    out = {}
    for p in parts():
        if G.kind(p) != "body":
            continue
        me = p.data
        mirror = side in ("left", "right")
        if (not recompute and dens.SPLIT_ATTR in me.attributes and "forge_plan" in p
                and bool(me.get("forge_plan_mirror", False)) == mirror):
            return dict(p["forge_plan"])         # (an EMPTY plan is a plan too)
        first_plan = "forge_plan_mirror" not in me
        J = _mod("joints").estimate(p)
        apps = _mod("appendages").from_object(p, J)
        arr = parts_mod.MeshArrays(me)
        arr.to_world(np.array(p.matrix_world))   # the same space the parts were measured in
        ids = np.zeros(len(me.vertices), np.int32)
        k = 0
        regions = []
        blocked: list = []
        for a in apps:
            m = np.zeros(len(me.vertices), bool)
            m[a["vert_idx"]] = True
            regions.append((a, m))
            twin = parts_mod.has_twin(arr, m, a.get("thickness", a["width"]))
            # split only thin parts WITHOUT a twin; paired ears/horns stay with the mirrored
            # body, where they come out symmetric without extra seams near the face
            if a.get("thin") and not twin and a["kind"] not in ("ear", "horn") and not a.get("cut_ok", True):
                # one-sided and thin, but no clean cut (it rests against a leg...): mirroring
                # would copy or delete it, so this body must not be mirrored
                blocked.append((a["name"], m))
                out[a["name"]] = "with the body (no clean cut): body NOT mirrored"
            elif a.get("thin") and not twin and a["kind"] not in ("ear", "horn"):
                k += 1
                ids[m & (ids == 0)] = k
                out[a["name"]] = "separate (cut at its root)"
            elif a["kind"] == "horn":
                out[a["name"]] = "rigid, fewer quads"
            else:
                out[a["name"]] = "with the body"
        if mirror and dens.straddles_middle(me):
            rep: list = []
            extra = parts_mod.one_sided_parts(me, taken=ids, arr=arr, report=rep)
            for kk in [int(x) for x in np.unique(extra) if x > 0]:
                m = extra == kk
                name = next((a["name"] for a, am in regions if (am & m).sum() > 0.3 * m.sum()), f"part_{kk}")
                out[name] = "separate: one-sided, kept as it is when mirroring"
                ids[m & (ids == 0)] = kk
            for kind, c, why in rep:
                where = "left" if c[0] > 0 else "right"
                if kind == "pair":
                    out[f"{where} side differs"] = why
                elif kind == "kept":
                    # the director must know BEFORE the run: mirroring would copy/delete it
                    blocked.append((f"one-sided part on the {where}", None))
                    out[f"one-sided part on the {where}"] = f"not cut ({why}): body NOT mirrored"
            me["forge_onesided_planned"] = True
        elif "forge_onesided_planned" in me:
            del me["forge_onesided_planned"]
        me["forge_plan_mirror"] = mirror
        # a part the bone-based finder could not cut, but the one-sided cut took after all,
        # blocks nothing: it is cut (found twice - by the skeleton and by the mirror test)
        still = []
        for name, m in blocked:
            if m is not None and (ids[m] > 0).mean() > 0.6:
                if str(out.get(name, "")).startswith("with the body"):
                    out[name] = "separate: one-sided, kept as it is when mirroring"
                continue
            still.append(name)
        blocked = still
        if mirror and blocked:
            me["forge_mirror_blocked"] = ", ".join(blocked)[:120]
        elif "forge_mirror_blocked" in me:
            del me["forge_mirror_blocked"]
        dens.write_split(me, ids)
        # rigid horns: half the quads (they never deform, only their shape matters)
        horn = np.zeros(len(me.vertices), bool)
        app_all = np.zeros(len(me.vertices), bool)
        for a, m in regions:
            app_all |= m
            if a["kind"] == "horn":
                horn |= m
        if horn.any() and dens.QR_ATTR in me.color_attributes and (paint or first_plan):
            # rings=2 reaches the base too, which the head weighting would otherwise paint red.
            # Only on a fresh map: re-planning for another side must not wipe the director's paint
            dens.boost(me, horn, rings=2, edge_factor=0.7)      # edges 1.4x longer: half the quads
        # face creases are carved on the FACE only: ear, horn and tail roots are not creases
        sa = me.attributes.get(dens.STRICT_ATTR)
        if sa is not None and app_all.any() and (paint or first_plan):
            sv = np.empty(len(me.vertices), np.float32)
            sa.data.foreach_get("value", sv)
            sv[dens._dilate(app_all, me, 3)] = 1.0
            sa.data.foreach_set("value", sv)
        p["forge_plan"] = out
    return out


def show_side(p, side: str) -> None:
    """Preview: the part as if made from its left (+X) or right side, mirrored ('' = original)."""
    m = p.modifiers.get("FORGE_side")
    if not side:
        if m is not None:
            p.modifiers.remove(m)
        return
    if m is None:
        m = p.modifiers.new("FORGE_side", "MIRROR")
    m.use_axis = (True, False, False)
    m.use_bisect_axis = (True, False, False)
    m.use_bisect_flip_axis = (side == "right", False, False)
    m.use_mirror_merge = True


def show_detail_map(on: bool) -> None:
    """Show the originals coloured by the detail map: red = more quads, cyan = fewer, white = normal."""
    dens = _mod("density")
    for p in parts():
        me = p.data
        if dens.QR_ATTR not in me.color_attributes:
            continue
        if on:
            p["forge_prev_color"] = me.color_attributes.active_color_name or ""
            me.color_attributes.active_color_name = dens.QR_ATTR
        else:
            prev = p.get("forge_prev_color", "")
            if prev and prev in me.color_attributes:
                me.color_attributes.active_color_name = prev
    new = lows()
    for p in parts():                     # with new meshes present the map view swaps them
        p.hide_set(bool(new) and not on)
    for o in new:
        o.hide_set(on)


def prepare_maps(detail: float, recompute: bool = False, side: str = "") -> int:
    """Detail map AND parts plan together, so the map the director sees (Show / Paint) is the
    map Quad Remesher gets: the plan paints the horns lighter on top of the detail map."""
    n = ensure_detail_maps(detail, recompute=recompute) if detail > 0 else 0
    # measure the parts where they are: "Compare with original" may have moved them aside
    moved = [(p, p.location.x) for p in parts() if p.location.x]
    for p, _x in moved:
        p.location.x = 0.0
    if moved:
        bpy.context.view_layer.update()
    try:
        fresh = recompute or n > 0
        plan_parts(recompute=fresh, side=side, paint=fresh)   # a fresh map needs the plan again
    except Exception as exc:                          # noqa: BLE001 - remeshing still works without
        print(f"[forge] parts plan failed: {exc}")
        for p in parts():
            if G.kind(p) == "body":
                p["forge_plan"] = {"parts plan failed": str(exc)[:80]}
    finally:
        for p, x in moved:
            p.location.x = x
        if moved:
            bpy.context.view_layer.update()
    return n


def plan_needed(side: str) -> bool:
    """The parts plan has to be (re)made: no plan yet, or the mirroring choice changed."""
    for p in parts():
        if G.kind(p) == "body":
            me = p.data
            return not (_mod("density").SPLIT_ATTR in me.attributes and "forge_plan" in p
                        and bool(me.get("forge_plan_mirror", False)) == (side in ("left", "right")))
    return False


def prepare_maps_job(detail: float, recompute: bool = False, side: str = ""):
    """prepare_maps as a job: the panel shows what is going on (on a dense AI mesh finding
    the parts takes a minute or two) and Stop works between the steps."""
    STATUS["text"] = "detail map + finding the extra parts (tail, horns, ears...)"
    yield 0.1
    n = prepare_maps(detail, recompute=recompute, side=side)
    STATUS["text"] = ""
    return n


def plan_rows() -> list:
    """The parts plan as short panel lines (read-only: safe in draw)."""
    body = None
    for p in parts():
        if G.kind(p) == "body":
            body = p
    plan = dict(body.get("forge_plan", {})) if body is not None else {}
    groups: dict = {}
    for name, what in plan.items():
        groups.setdefault(str(what), []).append(str(name))
    return [f"{', '.join(sorted(v))}: {k}" for k, v in sorted(groups.items())]


MIN_TRIS_PER_PART = 300


def budget_split(budget: int, report_json: str) -> list:
    """How the Triangles budget divides between the parts: by surface area, like the run
    (props share the budget; they do not add to it). [(label, tris)], largest first; empty
    when the Step 3 report does not cover every part (read-only: safe in draw)."""
    import json
    try:
        rep = json.loads(report_json or "{}")
    except ValueError:
        return []
    ps = parts()
    areas = {p.name: rep.get(p.name, {}).get("area") for p in ps}
    if not ps or any(a is None for a in areas.values()):
        return []
    total = sum(areas.values()) or 1.0
    out = [("body" if G.kind(p) == "body" else p.name[:18],
            max(int(budget * areas[p.name] / total), MIN_TRIS_PER_PART)) for p in ps]
    return sorted(out, key=lambda x: -x[1])


def part_names(objs) -> list:
    """Forge part names of the given objects (new meshes or originals)."""
    c = C()
    out = []
    names = {c.safe_name(p.name): p for p in parts()}
    for o in objs:
        part = o.get(c.PART_PROP)
        if not part and o in names.values():
            part = c.safe_name(o.name)
        if part in names and part not in out:
            out.append(part)
    return out


def missing_lows() -> list:
    """Parts that have no new mesh yet (e.g. after redoing only some parts)."""
    c = C()
    have = {o.get(c.PART_PROP) for o in lows()}
    return [c.safe_name(p.name) for p in parts() if c.safe_name(p.name) not in have]


def run_retopo(budget: int, use_qr: bool = True, detail: float = 0.8, symmetry: str = "auto", only=None):
    if use_qr:
        prepare_maps(detail, side=symmetry)
    for p in parts():                                  # a side preview must not reach the remesher
        show_side(p, "")
    prepare_retopo(only)
    if not (use_qr and detail > 0):              # no map: QR spreads quads by curvature only
        dens = _mod("density")
        for o in lows():
            a = o.data.color_attributes.get(dens.QR_ATTR)
            if a is not None:
                o.data.color_attributes.remove(a)
    args = {"method": "quadremesher" if use_qr else "quadriflow", "target_tris": int(budget),
            "symmetry": symmetry, "only": list(only or []),
            "min_tris_per_part": MIN_TRIS_PER_PART, "qr_timeout": 900, "shape_retries": 1}
    return _mod("retopo").run(args)


def stop_cleanup(label: str = "") -> None:
    """After Stop: drop half-done pieces and results, show the original parts again."""
    if "retopo" in label:
        undo_retopo()                     # a half-done retopology is of no use: start clean
    try:
        _mod("retopo").cleanup_jobs()     # first: retires the jobs of removed results
    except Exception:                     # noqa: BLE001
        pass
    for o in list(bpy.data.objects):
        if o.get("forge_rescue") or "_rescue" in o.name or o.name.startswith("Retopo_") \
                or o.get("forge_qr_proxy"):
            bpy.data.objects.remove(o)
    try:
        retopo = _mod("retopo")
        retopo.cleanup_jobs()
        retopo.STATUS["text"] = ""
    except Exception:                                 # noqa: BLE001
        pass
    new = lows()
    for p in parts():                     # with new meshes present the originals stay hidden
        p.hide_set(bool(new))
    for o in new:
        o.hide_set(False)
    try:                                  # back to normal viewport colours
        for area in bpy.context.screen.areas:
            if area.type == "VIEW_3D":
                area.spaces.active.shading.color_type = "MATERIAL"
    except (AttributeError, TypeError):
        pass


def mark_defects(me) -> int:
    """Select exactly the faults of a mesh (object mode; edit mode shows them): open edges,
    edges of 3+ faces, wire edges, stray points, faces lying on each other, doubled points."""
    import numpy as np
    rescue = _mod("rescue")
    ne, nv, nf = len(me.edges), len(me.vertices), len(me.polygons)
    le = np.empty(len(me.loops), np.int64)
    me.loops.foreach_get("edge_index", le)
    per_edge = np.bincount(le, minlength=ne)
    lv = np.empty(len(me.loops), np.int64)
    me.loops.foreach_get("vertex_index", lv)
    ev = np.empty(ne * 2, np.int64)
    me.edges.foreach_get("vertices", ev)
    ev = ev.reshape(-1, 2)
    e_sel = per_edge != 2
    f_sel = rescue.stacked_faces(me)
    v_sel = rescue.doubled_points(me)
    used = np.zeros(nv, bool)
    used[lv] = True
    v_sel |= ~used
    v_sel[ev[e_sel].ravel()] = True
    if f_sel.any():
        fs = np.empty(nf, np.int64)
        me.polygons.foreach_get("loop_start", fs)
        ft = np.empty(nf, np.int64)
        me.polygons.foreach_get("loop_total", ft)
        for i in np.flatnonzero(f_sel):
            v_sel[lv[fs[i]:fs[i] + ft[i]]] = True
    e_sel |= v_sel[ev[:, 0]] & v_sel[ev[:, 1]]
    me.vertices.foreach_set("select", v_sel)
    me.edges.foreach_set("select", e_sel)
    me.polygons.foreach_set("select", f_sel)
    me.update()
    return int(e_sel.sum())


def clay_lows() -> None:
    """Plain grey on the new meshes until the bake (the original's material would show the
    density colours and confuse)."""
    mat = bpy.data.materials.get("FORGE_clay") or bpy.data.materials.new("FORGE_clay")
    mat.diffuse_color = (0.62, 0.62, 0.62, 1.0)
    for o in lows():
        o.data.materials.clear()
        o.data.materials.append(mat)
        a = o.data.color_attributes.get("QR_Density")
        if a is not None:
            o.data.color_attributes.remove(a)


def undo_retopo() -> None:
    clear_rig()
    _clear("lod")
    _clear("low")
    for p in parts():
        p.location.x = 0.0
        p.hide_set(False)
        for k in (C().ROLE_PROP,):
            if k in p:
                del p[k]


# ----------------------------------------------------------------------------- step 5: UVs

def run_uv(texture_size: int, use_uvpm: bool = True, use_uvgami: bool = True):
    args = {"packer": "uvpackmaster" if use_uvpm else "blender", "method": "angle_seams",
            "unwrapper": "uvgami" if use_uvgami else "blender",
            "texture_size": int(texture_size), "margin_px": 8, "uvpm_search_time": 3}
    rep = _mod("uv").run(args)
    if not hasattr(rep, "__next__"):
        rep["uvgami"] = uvgami_status()
        return rep

    def gen():
        out = yield from rep
        out["uvgami"] = uvgami_status()
        return out
    return gen()


def uvgami_status() -> str:
    try:
        return _mod("uv").uvgami_status()
    except Exception as exc:                          # noqa: BLE001
        return str(exc)


CHECKER = "FORGE_UV_CHECKER"


def toggle_checker() -> bool:
    """Show a UV grid on every low mesh (squares should look square and even). Returns state."""
    objs = lows()
    on = not any(o.get("forge_checker") for o in objs)
    if on:
        img = bpy.data.images.get(CHECKER) or bpy.data.images.new(CHECKER, 1024, 1024)
        img.generated_type = "COLOR_GRID"
        mat = bpy.data.materials.get(CHECKER) or bpy.data.materials.new(CHECKER)
        mat.use_nodes = True
        nt = mat.node_tree
        bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
        tex = nt.nodes.get("checker") or nt.nodes.new("ShaderNodeTexImage")
        tex.name = "checker"
        tex.image = img
        nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
        for o in objs:
            o["forge_checker"] = ",".join(m.name if m else "" for m in o.data.materials)
            o.data.materials.clear()
            o.data.materials.append(mat)
    else:
        for o in objs:
            names = o.get("forge_checker", "")
            o.data.materials.clear()
            for n in names.split(","):
                if n and n in bpy.data.materials:
                    o.data.materials.append(bpy.data.materials[n])
            if "forge_checker" in o:
                del o["forge_checker"]
    return on


def checker_off() -> None:
    if any(o.get("forge_checker") for o in lows()):
        toggle_checker()


# ----------------------------------------------------------------------------- step 6: bake

COLOUR_MAPS = ("basecolor", "roughness", "metallic")
DETAIL_MAPS = ("normal", "ao")


def run_bake(texture_size: int, samples: int = 16, device: str = "GPU"):
    """Normal + AO from the repaired mesh; colour / roughness / metal from the original
    texture (the pre-repair copy when a part was welded solid, since welding drops UVs)."""
    checker_off()
    c, bake = C(), _mod("bake")
    tex_dir = work_dir() / "textures"
    args = {"texture_size": int(texture_size), "texture_dir": str(tex_dir), "samples": samples,
            "device": device, "cage_extrusion_ratio": 0.01, "margin_px": 16, "fitted_cage": True}
    swapped = {}
    for h in c.meshes_with_role("high"):
        src = bpy.data.meshes.get(h.get(G.BACKUP, "")) if h.get(G.BACKUP) else None
        if src is not None and not h.data.uv_layers and src.uv_layers:
            swapped[h.name] = h.data
    rep1 = yield from bake.run_iter({**args, "maps": list(DETAIL_MAPS)})
    for name in swapped:                                  # colour from the original texture
        h = bpy.data.objects[name]
        h.data = bpy.data.meshes[h[G.BACKUP]]
    try:
        rep2 = yield from bake.run_iter({**args, "maps": list(COLOUR_MAPS)})
    finally:
        for name, mesh in swapped.items():
            bpy.data.objects[name].data = mesh
        hide_highs()
    return finish_bake(rep1, rep2)


def hide_highs() -> None:
    """Baking selects (and so un-hides) the originals; they would sit on top of the new model."""
    for h in C().meshes_with_role("high"):
        h.hide_set(True)


def finish_bake(*reports) -> dict:
    bake = _mod("bake")
    out = {}
    for rep in reports:
        for part, r in rep.get("parts", {}).items():
            e = out.setdefault(part, {"maps": {}, "bake_misses": {}})
            if "skipped" in r:
                e["skipped"] = r["skipped"]
                continue
            e["maps"].update(r.get("maps", {}))
            e["bake_misses"].update(r.get("bake_misses", {}))
            if "metallic_cleanup" in r:
                e["metallic_cleanup"] = r["metallic_cleanup"]
            for k, v in (r.get("specks_removed") or {}).items():
                e.setdefault("specks_removed", {})[k] = v
    for low in lows():
        part = low.get(C().PART_PROP)
        e = out.get(part)
        if not e or not e["maps"]:
            continue
        e["bake_miss_ratio"] = round(max(e["bake_misses"].values(), default=0.0), 4)
        imgs = {}
        for k, path in e["maps"].items():
            img = bpy.data.images.get(f"T_{part}_{k}")
            if img is None or img.filepath_raw != path:
                img = bpy.data.images.load(path, check_existing=True)
            imgs[k] = img
        old = list(low.data.materials)
        bake._final_material(low, imgs)
        for m in old:
            if m and m.users == 0:
                bpy.data.materials.remove(m)
    return {"parts": out}


# ----------------------------------------------------------------------------- step 7: colour

def export_for_retexture() -> Path:
    """Low meshes (with our UVs) as one GLB per part, for Tripo Studio's texture tool."""
    d = work_dir() / "retexture"
    d.mkdir(exist_ok=True)
    c = C()
    for o in lows():
        c.select_only(o)
        kw = dict(filepath=str(d / f"{o.get(c.PART_PROP)}.glb"), export_format="GLB", use_selection=True)
        try:
            bpy.ops.export_scene.gltf(**kw, export_animations=False)
        except TypeError:
            bpy.ops.export_scene.gltf(**kw)
    return d


def _fit_to(src, target) -> None:
    """Uniform scale + move `src` so its bounding box matches `target` (Tripo re-centres models)."""
    G.apply_transform(src)
    slo, shi = G.world_bounds(src)
    tlo, thi = G.world_bounds(target)
    s = max(thi - tlo) / max(max(shi - slo), 1e-9)
    from mathutils import Matrix
    src.data.transform(Matrix.Translation((tlo + thi) / 2) @ Matrix.Scale(s, 4) @ Matrix.Translation(-(slo + shi) / 2))
    src.data.update()


def import_retexture(path: str, part: str, texture_size: int, samples: int = 16, device: str = "GPU") -> dict:
    """Bake the colour of a re-textured model (same shape) onto our low mesh's UVs."""
    c, bake = C(), _mod("bake")
    low = next((o for o in lows() if o.get(c.PART_PROP) == part), None)
    if low is None:
        raise RuntimeError(f"no low mesh for part {part}")
    before = {o.name for o in bpy.data.objects}
    ext = os.path.splitext(path)[1].lower()
    if ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=path)
    elif ext in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=path)
    else:
        raise RuntimeError("pick a .glb, .gltf or .fbx file")
    new = [o for o in bpy.data.objects if o.name not in before]
    meshes = [o for o in new if o.type == "MESH"]
    if not meshes:
        raise RuntimeError("the file has no mesh")
    src = meshes[0]
    if len(meshes) > 1:
        c.select_only(*meshes, active=src)
        bpy.ops.object.join()
    for o in new:
        if o.name in bpy.data.objects and o != src and o.type != "MESH":
            bpy.data.objects.remove(o)
    _fit_to(src, low)
    # bake against the re-textured model instead of the original high
    old_high = c.high_for(low)
    if old_high is not None:
        old_high[c.ROLE_PROP] = "high_keep"
    src[c.ROLE_PROP] = "high"
    src[c.PART_PROP] = part
    others = [o for o in lows() if o != low]
    for o in others:
        o[c.ROLE_PROP] = "low_keep"
    try:
        rep = bake.run({"texture_size": int(texture_size), "texture_dir": str(work_dir() / "textures"),
                        "samples": samples, "device": device, "cage_extrusion_ratio": 0.01,
                        "margin_px": 16, "maps": list(COLOUR_MAPS)})
    finally:
        for o in others:
            o[c.ROLE_PROP] = "low"
        if old_high is not None:
            old_high[c.ROLE_PROP] = "high"
        bpy.data.objects.remove(src)
        hide_highs()
    # one material again with the new colour and the earlier normal / AO maps
    imgs = {k: bpy.data.images.get(f"T_{part}_{k}") for k in COLOUR_MAPS + DETAIL_MAPS}
    imgs = {k: v for k, v in imgs.items() if v is not None}
    old = list(low.data.materials)
    bake._final_material(low, imgs)
    for m in old:
        if m and m.users == 0:
            bpy.data.materials.remove(m)
    return rep


def paint_setup(obj) -> str:
    """Texture Paint on the part's base colour map."""
    c = C()
    part = obj.get(c.PART_PROP)
    img = bpy.data.images.get(f"T_{part}_basecolor")
    if img is None:
        raise RuntimeError("bake the textures first (step 6)")
    c.select_only(obj)
    bpy.ops.object.mode_set(mode="TEXTURE_PAINT")
    ip = bpy.context.scene.tool_settings.image_paint
    ip.mode = "IMAGE"
    ip.canvas = img
    pal = texture_palette(img)
    try:
        ip.palette = pal
    except (AttributeError, TypeError):
        pass
    if pal.colors:
        first = tuple(pal.colors[0].color)
        ups = bpy.context.scene.tool_settings.unified_paint_settings
        for target in (ups, getattr(ip, "brush", None)):
            try:
                target.color = first
            except (AttributeError, TypeError):
                pass
    return img.name


def palette_colours(px: "np.ndarray", k: int = 12, samples: int = 40000, seed: int = 0) -> list:
    """The texture's main colours (k-means on a sample of its texels), most used first."""
    import numpy as np
    rgb = px.reshape(-1, px.shape[-1])[:, :3]
    if len(rgb) == 0:
        return []
    rng = np.random.default_rng(seed)
    pts = rgb[rng.choice(len(rgb), min(samples, len(rgb)), replace=False)].astype(np.float64)
    cen = pts[rng.choice(len(pts), min(k, len(pts)), replace=False)]
    for _ in range(15):
        lab = np.argmin(((pts[:, None, :] - cen[None]) ** 2).sum(-1), axis=1)
        for i in range(len(cen)):
            sel = pts[lab == i]
            if len(sel):
                cen[i] = sel.mean(axis=0)
    counts = np.bincount(lab, minlength=len(cen))
    order = np.argsort(-counts)
    out = []
    for i in order:
        c = cen[i]
        if counts[i] == 0 or any(np.abs(c - np.array(o)).max() < 0.03 for o in out):
            continue                                  # skip near-duplicates
        out.append(tuple(float(x) for x in c))
    return out


def texture_palette(img, k: int = 12):
    """A swatch palette of the part's own colours: the eyedropper in paint mode samples the
    LIT screen (shadows make every pick darker); swatches are the true texture colours."""
    import numpy as np
    w, h = img.size
    px = np.empty(w * h * 4, np.float32)
    img.pixels.foreach_get(px)
    cols = palette_colours(px.reshape(h, w, 4), k)
    name = "Forge colours"
    pal = bpy.data.palettes.get(name) or bpy.data.palettes.new(name)
    while pal.colors:
        pal.colors.remove(pal.colors[0])
    for c in cols:
        pal.colors.new().color = c
    return pal


def save_painted() -> int:
    n = 0
    for img in bpy.data.images:
        if img.name.startswith("T_") and img.is_dirty and img.filepath_raw:
            img.save()
            n += 1
    return n


# ----------------------------------------------------------------------------- step 8: rig

def place_joints() -> dict:
    """Guess the joints from the body's T-pose and put Auto-Rig Pro's reference bones there."""
    if not has_addon_op("arp.append_arp"):
        raise RuntimeError("Auto-Rig Pro is not enabled (Edit > Preferences > Add-ons)")
    body = body_low()
    if body is None:
        raise RuntimeError("no body mesh: finish step 4 first")
    clear_rig()
    joints = _mod("joints").estimate(body)
    rig, report = _mod("arp_rig").place(joints, lows(), {"arp_preset": "human"})
    # tail, ears... found on the body become Auto-Rig Pro limbs; face bones stay off for now
    try:
        apps = _mod("appendages").from_object(body, joints)
    except Exception as exc:                          # noqa: BLE001
        apps = []
        report["extras_error"] = str(exc)
    report["extras"] = _mod("arp_rig").add_extras(rig, apps, {})
    rig["forge_ref_rig"] = True
    report["ref_rig"] = rig.name
    return report


def ref_rig():
    return next((o for o in bpy.data.objects if o.type == "ARMATURE" and o.get("forge_ref_rig")
                 and not o.get("forge_arp")), None)


def edit_joints() -> None:
    rig = ref_rig()
    if rig is None:
        raise RuntimeError("place the joints first")
    C().select_only(rig)
    rig.show_in_front = True
    bpy.ops.object.mode_set(mode="EDIT")
    rig.data.use_mirror_x = True             # move a left joint, the right one follows


def build_rig(max_influences: int = 8) -> dict:
    rig = ref_rig()
    if rig is None:
        raise RuntimeError("place the joints first")
    C().ensure_object_mode()
    body = [o for o in lows() if G.kind(o) == "body"]
    props = [o for o in lows() if G.kind(o) != "body"]
    rep = _mod("arp_rig").finish(rig, body, props, {"max_influences": max_influences})
    arm = bpy.data.objects.get(rep["rig"])
    if arm is not None and "forge_ref_rig" in arm:
        del arm["forge_ref_rig"]
    w = {}
    metrics = _mod("metrics")
    for o in body:
        w[o.get(C().PART_PROP)] = metrics.weight_metrics(o, max_influences)
    rep["weights"] = w
    bad = [p for p, m in w.items() if not m.get("weighted")]
    if bad:
        raise RuntimeError(f"Auto-Rig Pro did not skin {', '.join(bad)} - check the joints and build again")
    return rep


def final_rig():
    return next((o for o in bpy.data.objects if o.type == "ARMATURE" and o.get("forge_arp")), None)


# pose test: (control bone candidates, world axis, degrees) per key frame
POSES = {
    15: [(("c_arm_fk.l",), "Y", -60), (("c_arm_fk.r",), "Y", 60), (("c_head.x",), "Z", 30)],
    30: [(("c_arm_fk.l",), "Z", 50), (("c_arm_fk.r",), "Z", -50), (("c_forearm_fk.l",), "Z", 60),
         (("c_forearm_fk.r",), "Z", -60), (("c_spine_02.x", "c_spine_01.x"), "X", 20)],
    45: [(("c_thigh_fk.l",), "X", -45), (("c_leg_fk.l",), "X", 70), (("c_thigh_fk.r",), "X", 30),
         (("c_neck.x",), "X", -20)],
}
FK_SWITCHES = (("c_hand_ik.l", "c_hand_ik.r", "c_foot_ik.l", "c_foot_ik.r"), "ik_fk_switch")


def pose_test() -> dict:
    """Key a few extreme poses on the rig's FK controls and play them."""
    import math

    from mathutils import Quaternion
    arm = final_rig()
    if arm is None:
        raise RuntimeError("build the rig first")
    if "forge_pose_switches" in arm:            # pressed twice: restore first, then start again
        pose_test_stop()
    C().select_only(arm)
    bpy.ops.object.mode_set(mode="POSE")
    pb = arm.pose.bones
    names, prop = FK_SWITCHES
    saved = {}
    for n in names:
        if n in pb and prop in pb[n]:
            saved[n] = pb[n][prop]
            pb[n][prop] = 1.0                                 # FK so rotations drive the limbs
    arm["forge_pose_switches"] = saved
    if arm.animation_data is None:
        arm.animation_data_create()
    act = bpy.data.actions.new("FORGE_pose_test")
    arm.animation_data.action = act
    used = set()
    sc = bpy.context.scene

    def rest_all(frame):
        for b in pb:
            b.rotation_mode = "QUATERNION"
            b.rotation_quaternion = (1, 0, 0, 0)
        for n in used:
            pb[n].keyframe_insert("rotation_quaternion", frame=frame)

    for frame, moves in POSES.items():
        for cands, _axis, _deg in moves:
            n = next((c for c in cands if c in pb), None)
            if n:
                used.add(n)
    rest_all(1)
    for frame, moves in POSES.items():
        for b in pb:
            b.rotation_quaternion = (1, 0, 0, 0)
        for cands, axis, deg in moves:
            n = next((c for c in cands if c in pb), None)
            if not n:
                continue
            bone = arm.data.bones[n]
            rest = bone.matrix_local.to_3x3()
            world = Quaternion(Vector({"X": (1, 0, 0), "Y": (0, 1, 0), "Z": (0, 0, 1)}[axis]),
                               math.radians(deg))
            local = (rest.inverted() @ world.to_matrix() @ rest).to_quaternion()
            pb[n].rotation_mode = "QUATERNION"
            pb[n].rotation_quaternion = local
        for n in used:
            pb[n].keyframe_insert("rotation_quaternion", frame=frame)
    rest_all(60)
    sc.frame_start, sc.frame_end = 1, 60
    sc.frame_set(1)
    bpy.ops.object.mode_set(mode="OBJECT")
    return {"controls_moved": sorted(used)}


# ----------------------------------------------------------------------------- sample animations
# Test clips made in Python on the rig's own FK controls: no outside animation files, no
# licences. Each frame is a list of WORLD rotations per control (character faces -Y, its left
# is +X), applied in order and turned into the control's local rotation, so the same clip
# works on any Auto-Rig Pro rig. What each clip is for is in CLIPS (shown in the panel).
CLIPS = {
    "rom": ("Range of motion", "Every joint to its limit, one after another: look for tearing, "
            "collapsing elbows/knees/shoulders, twisting wrists, props leaving the body"),
    "walk": ("Walk cycle", "A plain walk on the spot: knees, hips, shoulders and the belly in motion; "
             "the tail and ears follow"),
    "idle": ("Idle (breathing)", "Slow breathing, a look around, a tail sway: what the player sees most"),
    "tail": ("Tail and ears", "A wave down the tail and ear flicks: links bend smoothly, no kinks"),
}
CLIP_LENGTH = {"rom": 195, "walk": 32, "idle": 120, "tail": 96}   # rom: 13 poses x 15 frames
ARM_DOWN = 65.0                                  # T-pose arms lowered to a relaxed A-pose


def _chain(pb, prefix: str, side: str = "") -> list:
    """Auto-Rig Pro chain controls in order (c_tail_00.x, c_tail_01.x... / c_ear_01.l...)."""
    import re
    out = []
    for n in pb.keys():
        m = re.match(rf"^{re.escape(prefix)}(\d+)(\.[xlr])$", n)
        if m and (not side or m.group(2) == side):
            out.append((int(m.group(1)), n))
    return [n for _i, n in sorted(out)]


def _clip_frame(clip: str, f: int, pb) -> dict:
    """{control: [(world axis, degrees), ...]} for this frame of the clip."""
    import math
    n = CLIP_LENGTH[clip]
    ph = 2 * math.pi * (f - 1) / n
    tail = _chain(pb, "c_tail_")
    ears = {s: _chain(pb, "c_ear_", "." + s) for s in "lr"}
    out: dict = {}

    def add(bone, axis, deg):
        if bone in pb and abs(deg) > 1e-6:
            out.setdefault(bone, []).append((axis, deg))

    def arms_down(swing_l=0.0, swing_r=0.0):
        add("c_arm_fk.l", "Y", ARM_DOWN)
        add("c_arm_fk.r", "Y", -ARM_DOWN)
        add("c_arm_fk.l", "X", swing_l)
        add("c_arm_fk.r", "X", swing_r)

    if clip == "walk":
        s, c = math.sin(ph), math.cos(ph)
        add("c_thigh_fk.l", "X", -25 * s)                     # forward = -X for a -Y facing body
        add("c_thigh_fk.r", "X", 25 * s)
        add("c_leg_fk.l", "X", 5 + 45 * max(0.0, c))         # knee bends while the leg swings
        add("c_leg_fk.r", "X", 5 + 45 * max(0.0, -c))
        arms_down(20 * s, -20 * s)                           # arms swing against the legs
        add("c_forearm_fk.l", "Y", 15)
        add("c_forearm_fk.r", "Y", -15)
        for b in ("c_spine_02.x", "c_spine_01.x"):
            add(b, "Z", 4 * s)
        add("c_neck.x", "Z", -3 * s)
        for i, b in enumerate(tail):
            add(b, "Z", 12 * math.sin(ph - 0.7 * i))
        for side, sign in (("l", 1), ("r", -1)):
            for b in ears[side]:
                add(b, "Y", sign * 6 * math.sin(2 * ph))
    elif clip == "idle":
        s = math.sin(ph)
        arms_down(2 * s, 2 * s)
        add("c_spine_02.x", "X", 2.5 * s)                    # breathing
        add("c_head.x", "Z", 12 * math.sin(ph / 1.0 + 0.5) * max(0.0, math.sin(ph / 2)))
        add("c_head.x", "X", -3 * s)
        for i, b in enumerate(tail):
            add(b, "Z", 7 * math.sin(ph - 0.5 * i))
        for side, sign in (("l", 1), ("r", -1)):
            for b in ears[side]:
                add(b, "Y", sign * 4 * max(0.0, math.sin(3 * ph)) ** 4 * 3)
    elif clip == "tail":
        for i, b in enumerate(tail):
            add(b, "Z", 25 * math.sin(ph - 0.7 * i))
            add(b, "X", 10 * math.sin(2 * ph - 0.7 * i))
        for side, sign in (("l", 1), ("r", -1)):
            for b in ears[side]:
                add(b, "Y", sign * 20 * math.sin(2 * ph))
    elif clip == "rom":
        # a pose every 15 frames, rest in between: each joint toward its limit
        poses = [
            [],
            [("c_arm_fk.l", "Y", -80), ("c_arm_fk.r", "Y", 80)],                 # arms up
            [("c_arm_fk.l", "Y", ARM_DOWN), ("c_arm_fk.r", "Y", -ARM_DOWN)],     # arms down
            [("c_arm_fk.l", "Z", 80), ("c_arm_fk.r", "Z", -80)],                 # arms forward
            [("c_arm_fk.l", "Z", -40), ("c_arm_fk.r", "Z", 40)],                 # arms back
            [("c_forearm_fk.l", "Z", 120), ("c_forearm_fk.r", "Z", -120)],       # elbows
            [("c_arm_fk.l", "X", 70), ("c_arm_fk.r", "X", -70)],                 # arm twist
            [("c_thigh_fk.l", "X", -80), ("c_leg_fk.l", "X", 100),
             ("c_thigh_fk.r", "X", 35)],                                         # leg forward / back
            [("c_thigh_fk.l", "Y", -40), ("c_thigh_fk.r", "Y", 40)],             # legs apart
            [("c_spine_01.x", "X", 25), ("c_spine_02.x", "X", 25)],              # bend forward
            [("c_spine_01.x", "Z", 30), ("c_spine_02.x", "Z", 30)],              # twist
            [("c_neck.x", "X", -30), ("c_head.x", "Z", 60)],                     # look round
        ] + [[(b, "Z", 40 * (1 if i % 2 == 0 else -1)) for i, b in enumerate(tail)]
             + [(b, "Y", 30) for b in ears["l"]] + [(b, "Y", -30) for b in ears["r"]]]
        k = (f - 1) / 15.0
        i0 = int(k) % len(poses)
        w = 0.5 - 0.5 * math.cos(math.pi * min(1.0, 2 * (k - int(k))))        # out and back
        for bone, axis, deg in poses[i0]:
            add(bone, axis, deg * w)
    return out


def sample_animation(clip: str = "rom") -> dict:
    """Key a test clip on the rig's FK controls and set the scene to play it in a loop."""
    import math

    from mathutils import Quaternion
    if clip not in CLIPS:
        raise ValueError(f"unknown clip {clip!r}")
    arm = final_rig()
    if arm is None:
        raise RuntimeError("build the rig first")
    if "forge_pose_switches" in arm:              # another clip is on: restore first
        pose_test_stop()
    C().select_only(arm)
    bpy.ops.object.mode_set(mode="POSE")
    pb = arm.pose.bones
    names, prop = FK_SWITCHES
    saved = {}
    for nm in names:
        if nm in pb and prop in pb[nm]:
            saved[nm] = pb[nm][prop]
            pb[nm][prop] = 1.0                    # FK so rotations drive the limbs
    arm["forge_pose_switches"] = saved
    if arm.animation_data is None:
        arm.animation_data_create()
    act = bpy.data.actions.new(f"FORGE_pose_{clip}")
    arm.animation_data.action = act
    length = CLIP_LENGTH[clip]
    axes = {"X": (1, 0, 0), "Y": (0, 1, 0), "Z": (0, 0, 1)}
    frames = list(range(1, length + 1, 2)) + [length + 1]
    poses = {f: _clip_frame(clip, f if f <= length else 1, pb) for f in frames}
    used = sorted({b for p in poses.values() for b in p})
    for f in frames:
        for b in used:
            q = Quaternion()
            for axis, deg in poses[f].get(b, []):
                q = Quaternion(Vector(axes[axis]), math.radians(deg)) @ q    # later = outer
            rest = arm.data.bones[b].matrix_local.to_3x3()
            local = (rest.inverted() @ q.to_matrix() @ rest).to_quaternion()
            pb[b].rotation_mode = "QUATERNION"
            pb[b].rotation_quaternion = local
            pb[b].keyframe_insert("rotation_quaternion", frame=f)
    sc = bpy.context.scene
    sc.frame_start, sc.frame_end = 1, length               # frame length+1 == frame 1: a clean loop
    sc.frame_set(1)
    bpy.ops.object.mode_set(mode="OBJECT")
    return {"clip": clip, "frames": length, "controls": used}


def animated_meshes(arm) -> list:
    """The new meshes the rig moves: skinned to it, or pinned to one of its bones."""
    return [o for o in lows() if o.parent is arm
            or any(m.type == "ARMATURE" and m.object is arm for m in o.modifiers)]


def check_animation_job(clip: str):
    """Generator: put the clip on (if it is not), measure about 48 of its frames, return the
    report (motion_check: joints, skin, faces passing through faces, weights)."""
    if clip not in CLIPS:
        raise ValueError(f"unknown clip {clip!r}")
    arm = final_rig()
    if arm is None:
        raise RuntimeError("build the rig first")
    act = arm.animation_data.action if arm.animation_data else None
    if act is None or act.name != f"FORGE_pose_{clip}":
        sample_animation(clip)
    scr = bpy.context.screen
    if scr is not None and scr.is_animation_playing:
        bpy.ops.screen.animation_cancel(restore_frame=False)
    objs = animated_meshes(arm)
    if not objs:
        raise RuntimeError("no mesh is skinned to the rig: build the rig again")
    length = CLIP_LENGTH[clip]
    frames = list(range(1, length + 1, max(1, length // 48)))
    gen = _mod("motion_check").check(arm, objs, frames)
    try:
        while True:
            share = next(gen)
            STATUS["text"] = f"checking {CLIPS[clip][0].lower()}: {int(100 * share)} %"
            yield 0.01
    except StopIteration as stop:
        rep = stop.value
    finally:
        STATUS["text"] = ""
    rep.pop("per_frame", None)
    rep["clip"] = clip
    return rep


def pose_test_stop() -> None:
    arm = final_rig()
    if arm is None:
        return
    if bpy.context.screen and bpy.context.screen.is_animation_playing:
        bpy.ops.screen.animation_cancel(restore_frame=False)
    if arm.animation_data and arm.animation_data.action and arm.animation_data.action.name.startswith("FORGE_pose"):
        act = arm.animation_data.action
        arm.animation_data.action = None
        bpy.data.actions.remove(act)
    for b in arm.pose.bones:
        b.rotation_quaternion = (1, 0, 0, 0)
        b.rotation_euler = (0, 0, 0)
        b.location = (0, 0, 0)
    for n, v in dict(arm.get("forge_pose_switches", {})).items():
        if n in arm.pose.bones:
            arm.pose.bones[n]["ik_fk_switch"] = v
    if "forge_pose_switches" in arm:
        del arm["forge_pose_switches"]
    bpy.context.scene.frame_set(1)


# ----------------------------------------------------------------------------- step 9: export

ENGINE_LODS = {"unreal": [1.0, 0.5, 0.25, 0.125], "unity": [1.0, 0.5, 0.25]}
ENGINE_INFLUENCES = {"unreal": 8, "unity": 4}


def _texture_maps(bake_report: dict) -> dict:
    return {part: r.get("maps", {}) for part, r in bake_report.get("parts", {}).items()}


def export_engine(engine: str, bake_report: dict, unity_budget: int = 0) -> dict:
    """LODs + engine FBX + packed textures. For Unity a lighter copy is made and removed again."""
    c, fin = C(), _mod("finalize")
    pose_test_stop()
    checker_off()
    c.ensure_object_mode()
    out_dir = work_dir() / "export" / engine
    originals = lows()
    temp = []
    try:
        if engine == "unity":
            # mobile: a lighter copy (the Unreal meshes and their 8-bone weights stay untouched)
            total = sum(c.tri_count(o) for o in originals)
            ratio = min(1.0, unity_budget / max(total, 1)) if unity_budget else 1.0
            for o in originals:
                d = c.duplicate(o, f"{o.name}_unity")
                temp.append(d)
                d[c.ROLE_PROP] = "low"
                o[c.ROLE_PROP] = "low_keep"
                if ratio < 0.98:
                    mod = d.modifiers.new("forge_mobile", "DECIMATE")
                    mod.ratio = ratio
                    mod.use_collapse_triangulate = True
                    c.select_only(d)
                    bpy.ops.object.modifier_move_to_index(modifier=mod.name, index=0)
                    bpy.ops.object.modifier_apply(modifier=mod.name)
        arm = c.find_armature()
        if arm is not None:
            deform = {b.name for b in arm.data.bones if b.use_deform}
            from importlib import import_module
            skin = import_module(f"{fb().__name__}.skin")
            for o in lows():
                if o.vertex_groups:
                    skin._cleanup_weights(o, ENGINE_INFLUENCES[engine], 0.01, deform)
        _clear("lod")
        lods = fin.lods({"lod_ratios": ENGINE_LODS[engine]})
        files = fin.export({"engine": engine, "asset_name": asset_name(), "export_dir": str(out_dir),
                            "texture_maps": _texture_maps(bake_report), "detachable_parts": [],
                            "unity_pipeline": "urp", "ao_into_basecolor": engine == "unity"})
        files["lods"] = lods.get("parts", {})
    finally:
        _clear("lod")
        for d in temp:
            bpy.data.objects.remove(d)
        for o in originals:
            o[c.ROLE_PROP] = "low"
            o.name = f"{o.get(c.PART_PROP)}_low"
    return files


def open_folder(path: Path) -> bool:
    import subprocess
    try:
        if sys.platform == "win32":
            os.startfile(str(path))            # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
        return True
    except OSError:
        print(f"[forge] folder: {path}")
        return False


def scene_ground_ok() -> bool:
    b = body_low()
    if b is None:
        return False
    lo, _ = G.world_bounds(b)
    return abs(lo.z) < 0.01 * max(b.dimensions)

