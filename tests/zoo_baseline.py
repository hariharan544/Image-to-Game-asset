"""Baseline: what the product does with every body of the test zoo (tests/bodies_zoo.py),
measured against the zoo's ground truth. A before/after tool for fix branches:

    python tests/zoo_baseline.py --repo <checkout> --out <dir> [--side left,right] [--mode fast|real|both]
                                 [--ai off|on|both] [--voxel 0.008] [--budget 40000] [--render] [body ...]

The zoo always comes from this file's folder; the product (blender_scripts, blender_addon) from
--repo (default: this checkout), so the same bodies can be run against any version.

Per body:
  - joints.estimate against the zoo's joints_hint (humanoid bodies)
  - appendages.from_object: which zoo parts are found, in how many pieces, under which kind
  - parts.one_sided_parts and the mirror numbers (straddles_middle, mirror_plane, asymmetry)
  - the Step 4 parts plan for Symmetry "auto" (steps.prepare_maps, the default path) and for each
    side asked (steps.plan_parts)
  - mode "fast": a dry run of each plan with the product's own functions (rescue.split_off, then
    density.symmetrize for a side; for auto no mirror, and the Quad Remesher X-symmetry flag
    prepare_retopo would set). Cut, lost, copied and torn shares come from what split_off
    actually returned, never from the plan.
  - mode "real": steps.run_retopo itself (prepare_maps, prepare_retopo, retopo._run_qr with its
    split_off, mirror, piece remesh and weld) with tests/fake_qr.py as Quad Remesher (it returns
    the input reduced to the asked size; fitting, carving and the shape check are off), and the
    final mesh measured against the original.
Scores (higher = worse) and plain-language problems per body; baseline.json in --out.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
import tempfile
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent

BODIES = [(n, n, {}) for n in (
    "bat_wings", "bird_wings", "one_wing", "dorsal_fin", "shoulder_cannon", "two_tails", "trunk", "cape", "tentacles",
    "horns_asym", "quadruped", "weapon_in_hand", "forearm_shield", "sash_diagonal", "ponytail_side", "antlers",
    "hair_spikes", "back_spines", "skirt", "four_arms", "four_wings", "tail_spikes", "held_staff", "dragon", "loadout",
    "winged_tail", "naga", "chibi", "back_hair")] + [
    ("one_wing_bat", "one_wing", {"style": "bat"}),
    ("dorsal_fin_quadruped", "dorsal_fin", {"base": "quadruped"}),
    ("shoulder_pauldron", "shoulder_cannon", {"kind": "pauldron"}),
    ("weapon_up", "weapon_in_hand", {"point": "up"}),
    ("bat_wings_shells", "bat_wings", {"shells": 2}),           # extra shells on each base
    ("quadruped_shells", "quadruped", {"shells": 2}),
    ("tentacles_shells", "tentacles", {"shells": 2}),
    ("naga_shells", "naga", {"shells": 2}),
]
AI = {"blend": 0.03, "noise": 0.004}                               # the AI-like surface (Step 4 needs no colour)

# what the product's appendage kinds can say about each zoo kind
PRODUCT_KIND_OK = {"tail": {"tail"}, "ear": {"ear"}, "horn": {"horn"}, "trunk": {"snout", "trunk"}, "antler": {"horn"}}
GENERIC = {"extra", "back_extra", "head_extra"}
ONE_SIDED = ("one-sided", "pair_asym", "centre_asym")             # what a mirror copies or deletes
# product joint (key, index) for each zoo joints_hint name
JOINT_MAP = {"pelvis": ("pelvis", 0), "neck": ("neck", 0), "head": ("head", 0), "head_top": ("head", 1)}
for _s in "lr":
    JOINT_MAP.update({f"shoulder_{_s}": (f"upperarm_{_s}", 0), f"elbow_{_s}": (f"lowerarm_{_s}", 0),
                      f"wrist_{_s}": (f"hand_{_s}", 0), f"hand_{_s}": (f"hand_{_s}", 1),
                      f"hip_{_s}": (f"thigh_{_s}", 0),
                      f"knee_{_s}": (f"calf_{_s}", 0), f"ankle_{_s}": (f"foot_{_s}", 0)})


def _setup(repo: Path):
    for p in (repo / "blender_addon", repo / "blender_scripts", HERE):
        sys.path.insert(0, str(p))


def comp(mask, lab, labels) -> dict:
    """Which ground-truth owners a vertex set is made of (shares, largest first)."""
    import numpy as np
    if not mask.any():
        return {}
    vals, cnt = np.unique(lab[mask], return_counts=True)
    o = np.argsort(-cnt)
    return {labels[int(vals[i])]: round(float(cnt[i] / mask.sum()), 3) for i in o if cnt[i] / mask.sum() >= 0.01}


def as_forge_body(ob):
    import bpy
    col = bpy.data.collections.get("Forge Parts") or bpy.data.collections.new("Forge Parts")
    if col.name not in bpy.context.scene.collection.children:
        bpy.context.scene.collection.children.link(col)
    for c in list(ob.users_collection):
        c.objects.unlink(ob)
    col.objects.link(ob)
    ob["forge_kind"] = "body"
    return importlib.import_module("forge_send.steps")


def _kd(co):
    from mathutils.kdtree import KDTree
    kd = KDTree(len(co))
    for i, p in enumerate(co):
        kd.insert(p, i)
    kd.balance()
    return kd


def _tree(me):
    from mathutils.bvhtree import BVHTree
    import bodies_zoo as Z
    lv, ls, lt = Z._faces(me)
    return BVHTree.FromPolygons(Z.coords(me).tolist(), [lv[ls[i]:ls[i] + lt[i]].tolist() for i in range(len(ls))])


def cut_shares(co0, lab, labels, pieces, shift: float = 0.0) -> dict:
    """Share of each ground-truth part that split_off really took (its vertices found again,
    unmoved, in a returned piece; the pieces may be in the mirror frame, `shift` along x)."""
    import numpy as np
    if not pieces:
        return {}
    taken = np.zeros(len(co0), bool)
    kd = _kd(co0)
    for P in pieces:
        for p in P.tolist():
            for q in (p, (p[0] + shift, p[1], p[2])):
                _c, j, d = kd.find(q)
                if d < 1e-5:
                    taken[j] = True
                    break
    out = {}
    for k, name in enumerate(labels):
        m = lab == k
        if m.any() and taken[m].any():
            out[name] = round(float(taken[m].mean()), 3)
    return out


def lost_copied(co0, lab, labels, result_co, result_tree, tol: float, plane: float = 0.0) -> tuple:
    """(share of each part no longer on the result surface, share of each part copied by a mirror
    onto new surface): new = result vertices far from the original whose mirror image is near an
    original vertex of that part."""
    import numpy as np
    from mathutils import Vector
    lost = np.array([result_tree.find_nearest(Vector(p))[3] > tol for p in co0.tolist()])
    kd0 = _kd(co0)
    copied = np.zeros(len(labels))
    for p in result_co.tolist():
        if kd0.find(p)[2] <= tol:
            continue
        _c, j, d = kd0.find((2 * plane - p[0], p[1], p[2]))
        if d <= tol:
            copied[lab[j]] += 1
    lo, co = {}, {}
    for k, name in enumerate(labels):
        m = lab == k
        if m.any():
            lo[name] = round(float(lost[m].mean()), 3)
            if copied[k]:
                co[name] = round(float(copied[k] / m.sum()), 3)
    return lo, co


def _plan_names(me) -> dict:
    return {int(k): str(v) for k, v in dict(me.get("forge_split_names") or {}).items()}


def dry_run(me, ids, side, lab, labels, voxel, qr_sym_auto) -> dict:
    """Step 4 before remeshing, with the product's functions: split_off the planned parts in the
    mirror frame, then (for a side) mirror the body unless a cut failed or the plan blocked it."""
    import bodies_zoo as Z
    from mathutils import Matrix
    from forge_bpy import density, rescue
    co0 = Z.coords(me)
    m2 = me.copy()
    mirror = side in ("left", "right") and density.straddles_middle(me)
    shift = density.mirror_plane(m2) if mirror else 0.0
    if abs(shift) > 1e-6:
        m2.transform(Matrix.Translation((-shift, 0, 0)))
    rep: list = []
    pieces = rescue.split_off(m2, ids, rep) if ids is not None else []
    blocked = me.get("forge_mirror_blocked")
    why = ""
    if mirror and (rep or blocked):
        mirror = False
        why = f"not mirrored: {blocked or 'a cut failed'}"
    if mirror:
        density.symmetrize(m2, side)
    if abs(shift) > 1e-6:
        m2.transform(Matrix.Translation((shift, 0, 0)))
        for _k, pm, _p in pieces:
            pm.transform(Matrix.Translation((shift, 0, 0)))
    planned = sorted(set(int(i) for i in (ids if ids is not None else [])) - {0})
    names = _plan_names(me)
    got = [int(k) for k, _pm, _p in pieces]
    out = {"mirrored": bool(mirror), "why_not": why, "plane": round(float(shift), 4),
           "planned": [names.get(k, str(k)) for k in planned], "cut": [names.get(k, str(k)) for k in got],
           "refused": [(names.get(int(k), str(k)), w) for k, w in rep],
           "qr_symmetry": bool(mirror) if side in ("left", "right") else bool(qr_sym_auto)}
    out["cut_share"] = cut_shares(co0, lab, labels, [Z.coords(pm) for _k, pm, _p in pieces])
    import numpy as np
    res = np.concatenate([Z.coords(m2)] + [Z.coords(pm) for _k, pm, _p in pieces]) if pieces else Z.coords(m2)
    tmp = m2.copy()
    if pieces:
        import bmesh
        bm = bmesh.new()
        bm.from_mesh(tmp)
        for _k, pm, _p in pieces:
            bm.from_mesh(pm)
        bm.to_mesh(tmp)
        bm.free()
    out["lost"], out["copied"] = lost_copied(co0, lab, labels, res, _tree(tmp), 2.5 * voxel, shift)
    for m in [m2, tmp] + [pm for _k, pm, _p in pieces]:
        bpy_remove(m)
    return out


def bpy_remove(me):
    import bpy
    if me is not None and me.name in bpy.data.meshes and me.users == 0:
        bpy.data.meshes.remove(me)


def _decimate_to(tris: int):
    """The stand-in Quad Remesher's work: the input reduced to about `tris` triangles."""
    def run(me):
        import bmesh
        import bpy
        n = sum(len(p.vertices) - 2 for p in me.polygons)
        if n <= tris:
            return
        ob = bpy.data.objects.new("_zoo_qr", me)
        bpy.context.scene.collection.objects.link(ob)
        mod = ob.modifiers.new("d", "DECIMATE")
        mod.ratio = max(tris / n, 0.01)
        dg = bpy.context.evaluated_depsgraph_get()
        dg.update()
        bm = bmesh.new()
        bm.from_object(ob, dg)
        ob.modifiers.clear()
        bm.to_mesh(me)
        bm.free()
        bpy.data.objects.remove(ob)
    return run


def real_run(gen, kw, side, budget, voxel) -> dict:
    """steps.run_retopo for one side, Quad Remesher played by tests/fake_qr.py."""
    import bpy
    import numpy as np

    import bodies_zoo as Z
    import fake_qr
    from forge_bpy import addon_trial, density, rescue, retopo
    ob, info = Z.ZOO[gen](**kw)
    lab, labels = info["truth"], info["labels"]
    co0 = Z.coords(ob.data)
    S = as_forge_body(ob)
    eng = fake_qr.install()
    saved = (addon_trial.view3d_override, retopo._wait_limit, rescue.split_off, retopo.run)
    cuts, jobs = [], []

    def split_off(me, ids, report=None):
        rep = report if report is not None else []
        n0 = len(rep)
        out = saved[2](me, ids, rep)
        cuts.append({"planned": sorted(set(int(i) for i in np.unique(ids)) - {0}), "cut": [int(k) for k, _m, _p in out],
                     "refused": [(int(k), w) for k, w in rep[n0:]], "pieces": [Z.coords(pm) for _k, pm, _p in out]})
        return out

    def run(args):
        args.update({"conform": False, "carve": False, "shape_check": False, "qr_timeout": 60})
        return saved[3](args)
    addon_trial.view3d_override = lambda: {"scene": bpy.context.scene}
    retopo._wait_limit = lambda obj, timeout: 60.0
    rescue.split_off = split_off
    retopo.run = run
    retopo._QR_JOBS.clear()
    out = {"side": side}
    try:
        res = S.run_retopo(budget, use_qr=True, detail=0.8, symmetry=side)
        report = None
        if hasattr(res, "__next__"):
            t0 = time.time()
            while time.time() - t0 < 600:
                try:
                    next(res)
                except StopIteration as st:
                    report = st.value
                    break
                if eng.jobs:
                    q = bpy.context.scene.qremesher
                    jobs.append({"what": retopo.STATUS.get("text", "")[:60], "verts": len(eng.jobs[0][1].vertices),
                                 "symmetry_x": bool(q.symmetry_x), "quads": int(q.target_count)})
                    fake_qr.deliver(_decimate_to(2 * int(q.target_count)))
        else:
            report = res
        body = S.body_low()
        r = (report or {}).get("parts", {}).get(body.get("forge_part") if body else "", {}) if report else {}
        names = _plan_names(ob.data)
        plan = dict(ob.get("forge_plan", {}))
        out.update({"plan": plan, "blocked": ob.data.get("forge_mirror_blocked"), "jobs": jobs,
                    "method": r.get("method"), "split_kept": r.get("split_kept", []),
                    "separate_parts": r.get("separate_parts", 0), "joints": r.get("joints", []),
                    "open_edges": r.get("open_edges"), "mirrored": bool(body.get("forge_symmetry_x")) if body else None,
                    "why_not": next((w for w in r.get("split_kept", []) if w.startswith("not mirrored")), "")})
        c = cuts[0] if cuts else {"planned": [], "cut": [], "refused": [], "pieces": []}
        out["planned"] = [names.get(k, str(k)) for k in c["planned"]]
        out["cut"] = [names.get(k, str(k)) for k in c["cut"]]
        out["refused"] = [(names.get(k, str(k)), w) for k, w in c["refused"]]
        mirrors = side in ("left", "right") and density.straddles_middle(ob.data)
        plane = density.mirror_plane(ob.data) if mirrors else 0.0
        out["plane"] = round(float(plane), 4)
        out["cut_share"] = cut_shares(co0, lab, labels, c["pieces"], plane)
        out["qr_symmetry"] = bool(jobs[0]["symmetry_x"]) if jobs else None
        if body is not None:
            fin = Z.coords(body.data) @ np.array(body.matrix_world)[:3, :3].T + np.array(body.matrix_world)[:3, 3]
            out["lost"], out["copied"] = lost_copied(co0, lab, labels, fin, _tree(body.data), max(2.5 * voxel, 0.02),
                                                     plane)
            out["final_tris"] = sum(len(p.vertices) - 2 for p in body.data.polygons)
    finally:
        addon_trial.view3d_override, retopo._wait_limit, rescue.split_off, retopo.run = saved
        fake_qr.uninstall()
        retopo._QR_JOBS.clear()
        bpy.ops.wm.read_homefile(use_empty=True)
    return out


def run_body(key, gen, kw, args) -> dict:
    import bpy
    import numpy as np

    import bodies_zoo as Z
    from forge_bpy import appendages, density, joints, parts
    rec = {"body": key, "generator": gen, "params": kw, "errors": [], "timing": {}}
    t0 = time.time()
    ob, info = Z.ZOO[gen](**kw)
    rec["timing"]["build"] = round(time.time() - t0, 2)
    me = ob.data
    lab, labels, voxel = info["truth"], info["labels"], info["voxel"]
    rec["mesh"] = {"verts": len(me.vertices), "faces": len(me.polygons), "shells": Z.shells(me),
                   "height": round(info["height"], 3)}
    rec["truth"] = {n: {k: e[k] for k in ("kind", "side", "symmetry", "twin", "root_shape", "parent", "rig", "verts")}
                    for n, e in info["appendages"].items()}
    extras, limbs = list(info["appendages"]), list(info["limbs"])

    def step(name, fn):
        t = time.time()
        try:
            return fn()
        except Exception as exc:                                     # noqa: BLE001
            rec["errors"].append({"step": name, "error": f"{type(exc).__name__}: {exc}",
                                  "trace": traceback.format_exc(limit=4)[-1200:]})
            return None
        finally:
            rec["timing"][name] = round(time.time() - t, 2)
    # ---- joints
    J = step("joints.estimate", lambda: joints.estimate(ob))
    rec["joint_errors"] = {}
    if J is not None and info["kind"] == "humanoid":
        for j, q in info["joints_hint"].items():
            if j in JOINT_MAP and JOINT_MAP[j][0] in J:
                k, i = JOINT_MAP[j]
                rec["joint_errors"][j] = round(float(np.linalg.norm(np.array(J[k][i][:]) - np.array(q))), 3)
    # ---- appendages
    found = step("appendages.from_object", lambda: appendages.from_object(ob, J)) if J is not None else None
    rec["found"], fmasks = [], []
    for a in found or []:
        m = np.zeros(len(lab), bool)
        m[a["vert_idx"]] = True
        fmasks.append((a, m))
        rec["found"].append({"name": a["name"], "kind": a["kind"], "verts": int(a["verts"]), "thin": a["thin"],
                             "cut_ok": a.get("cut_ok"), "truth": comp(m, lab, labels)})
    # ---- one-sided cut on its own
    rep: list = []
    ids1 = step("parts.one_sided_parts", lambda: parts.one_sided_parts(me, report=rep))
    rec["one_sided"] = {"parts": [], "report": []}
    if ids1 is not None:
        for k in [int(x) for x in np.unique(ids1) if x > 0]:
            rec["one_sided"]["parts"].append({"id": k, "truth": comp(ids1 == k, lab, labels)})
        co = Z.coords(me)
        for kind, c, why in rep:
            j = int(np.argmin(np.linalg.norm(co - np.asarray(c), axis=1)))
            rec["one_sided"]["report"].append({"verdict": kind, "at": labels[lab[j]], "why": why})
    rec["symmetry"] = {}
    step("density.symmetry", lambda: rec["symmetry"].update(
        straddles_middle=bool(density.straddles_middle(me)), mirror_plane=round(float(density.mirror_plane(me)), 4),
        asymmetry=round(float(density.asymmetry(me)), 4)))
    co_ = Z.coords(me)
    lo_, hi_ = co_.min(axis=0), co_.max(axis=0)
    centred = abs((lo_[0] + hi_[0]) / 2) < 0.02 * float((hi_ - lo_).max())
    # (steps.prepare_retopo: Symmetry "auto" turns Quad Remesher's X symmetry on for a centred body
    # under 10 % asymmetry; the real mode reads it from the run instead)
    qr_auto = bool(centred and rec["symmetry"].get("asymmetry", 1.0) < 0.10)
    rec["symmetry"]["qr_symmetry_auto"] = qr_auto
    # ---- the Step 4 plans and their dry runs
    S = as_forge_body(ob)
    rec["plan"], rec["dry"] = {}, {}
    for side in ["auto"] + args.sides:
        if side == "auto":
            def prep():
                S.prepare_maps(0.8, recompute=True, side="auto")
                return dict(ob.get("forge_plan", {}))
            plan = step("prepare_maps[auto]", prep)
        else:
            plan = step(f"plan_parts[{side}]", lambda: S.plan_parts(recompute=True, side=side))
        ids = density.read_split(me)
        rec["plan"][side] = {"plan": plan, "blocked": me.get("forge_mirror_blocked"),
                             "planned_share": {} if ids is None else {
                                 labels[k]: round(float((ids[lab == k] > 0).mean()), 3)
                                 for k in range(len(labels)) if (ids[lab == k] > 0).any()}}
        if args.mode in ("fast", "both"):
            d = step(f"dry_run[{side}]", lambda: dry_run(me, ids, side, lab, labels, voxel, qr_auto))
            if d is not None:
                rec["dry"][side] = d
    # ---- the real run (one fresh build per side)
    rec["real"] = {}
    if args.mode in ("real", "both"):
        for side in ["auto"] + args.sides:
            r = step(f"real[{side}]", lambda: real_run(gen, kw, side, args.budget, voxel))
            if r is not None:
                rec["real"][side] = r
    # ---- verdicts per ground-truth part
    rec["parts"] = {}
    for n in extras + limbs:
        k = labels.index(n)
        tm = lab == k
        e = info["appendages"].get(n) or info["limbs"][n]
        v = {"kind": e["kind"], "symmetry": e["symmetry"]}
        cov = sorted(((a["name"], a["kind"], round(float((m & tm).sum() / max(tm.sum(), 1)), 3))
                      for a, m in fmasks if (m & tm).sum() >= 0.1 * tm.sum()), key=lambda x: -x[2])
        v["found_as"], v["fragments"] = cov, len(cov)
        best = cov[0][2] if cov else 0.0
        v["detected"] = "found" if best >= 0.5 else "partly" if best >= 0.15 else "missed"
        ok = PRODUCT_KIND_OK.get(e["kind"])
        v["class"] = ("-" if not cov else "ok" if ok and cov[0][1] in ok else
                      f"generic ({cov[0][1]})" if cov[0][1] in GENERIC else f"wrong ({cov[0][1]})")
        merged = set()
        for _a, m in fmasks:
            if (m & tm).sum() >= 0.25 * tm.sum():
                for n2 in extras + limbs:
                    t2 = lab == labels.index(n2)
                    if n2 != n and (m & t2).sum() >= 0.25 * t2.sum():
                        merged.add(n2)
        v["merged_with"] = sorted(merged)
        rec["parts"][n] = v
    rec["phantoms"] = [f["name"] for f in rec["found"] if sum(x for n, x in f["truth"].items() if n in extras) < 0.3]
    rec["height"] = info["height"]
    rec["score"], rec["problems"], rec["score_by"] = score(rec)
    if args.render:
        try:
            render_sheet(key, ob, info, fmasks, rec, Path(args.out))
        except Exception as exc:                                     # noqa: BLE001
            rec["errors"].append({"step": "render", "error": f"{type(exc).__name__}: {exc}"})
    bpy.ops.wm.read_homefile(use_empty=True)
    return rec


def score(rec) -> tuple:
    """How badly the product handles the body (higher = worse) and why: damage in Step 4 first
    (cut limbs, torn parts, one-sided parts mirrored away, plan != run), then what Step 8 would
    rig wrongly, then detection and naming. Real-run results take the place of the dry run.
    Reads the record only (--rescore recomputes a finished baseline.json)."""
    cat = {"step4": 0.0, "rig": 0.0, "detect": 0.0}
    why = []

    def add(c, v, text):
        cat[c] += v
        why.append(f"[{c} +{v:g}] {text}")
    for e in rec["errors"]:
        add("step4", 10, f"ERROR in {e['step']}: {e['error'][:120]}")
    apps = rec["truth"]
    limbs = {n for n in rec["parts"] if n not in apps}
    H = rec.get("height") or rec["mesh"]["height"]
    bad = {j: e for j, e in rec["joint_errors"].items() if e > 0.08 * H}
    if bad:
        add("rig", 4, "skeleton guess off: " + ", ".join(
            f"{j} by {e:.2f} m" for j, e in sorted(bad.items(), key=lambda x: -x[1])[:5]))
    runs = {s: (rec["real"].get(s) or rec["dry"].get(s)) for s in set(rec["dry"]) | set(rec["real"])}
    for side, r in sorted(runs.items()):
        tag = f"[{side}{' real' if side in rec['real'] else ''}]"
        cut, lost, cop = r.get("cut_share", {}), r.get("lost", {}), r.get("copied", {})
        for n in list(apps) + sorted(limbs):
            sym = rec["parts"][n]["symmetry"]
            c, lo, cp = cut.get(n, 0.0), lost.get(n, 0.0), cop.get(n, 0.0)
            if n in limbs:
                if c > 0.05:
                    add("step4", 5, f"{tag} {n}: a limb is cut off as a part ({c:.0%})")
                if lo > 0.05:                       # (a hand is about a sixth of an arm)
                    add("step4", 5, f"{tag} {n}: limb lost {lo:.0%}")
                continue
            if sym in ONE_SIDED and (lo > 0.05 or cp > 0.05):      # (a fold or a crossing is a small share)
                add("step4", 8, f"{tag} {n} ({sym}): damaged (lost {lo:.0%}, copied over {cp:.0%})")
            elif sym in ("pair", "pair_posed", "centre") and lo > 0.2:
                add("step4", 5, f"{tag} {n} ({sym}): lost {lo:.0%}")
            if 0.05 < c < 0.9:
                add("step4", 4, f"{tag} {n}: torn - only {c:.0%} of it is cut off, the rest stays on the body")
        bc = cut.get("body", 0.0)
        if bc > 0.02:
            add("step4", 4, f"{tag} the cut takes {bc:.0%} of the body itself ({', '.join(r.get('cut', []))})")
        for name, w in r.get("refused", []):
            add("step4", 3, f"{tag} plan != run: the plan cuts {name}, split_off refuses: {w[:90]}")
        if side in ("left", "right") and (r.get("why_not") or (r.get("mirrored") is False and r.get("refused"))):
            add("step4", 1, f"{tag} Symmetry {side.title()} asked, body NOT mirrored "
                            f"({(r.get('why_not') or 'a cut failed')[:60]})")
        if side == "auto" and r.get("qr_symmetry"):
            left_on = [n for n, e in apps.items() if e["symmetry"] in ONE_SIDED and cut.get(n, 0.0) < 0.5]
            if left_on:
                add("step4", 2, f"{tag} Quad Remesher X symmetry ON with not-symmetric parts left on the body: "
                                f"{', '.join(left_on)[:80]}")
    for side in ("left", "right"):
        blk = rec["plan"].get(side, {}).get("blocked")
        if not blk:
            continue
        needless = []
        for name in [b.strip() for b in str(blk).split(",")]:
            f = next((f for f in rec["found"] if f["name"] == name), None)
            top = list(f["truth"])[0] if f and f["truth"] else None
            t = apps.get(top) if top else None
            if (t and t["symmetry"] in ("pair", "centre")) or top in ["body"] + list(limbs):
                needless.append(f"{name}={top}")
        if needless:
            add("step4", min(2 * len(needless), 4), f"[{side}] Symmetry blocked needlessly by {', '.join(needless)}")
    generic = []
    kinds: dict = {}
    for n, v in rec["parts"].items():
        if n not in limbs:
            kinds.setdefault(v["kind"], []).append(n)
    for kind, names in kinds.items():          # a cluster (many spikes): one line per kind, capped
        if len(names) < 4:
            continue
        miss = [n for n in names if rec["parts"][n]["detected"] == "missed"]
        part = [n for n in names if rec["parts"][n]["detected"] == "partly"]
        if miss:
            add("detect", min(1.5 + 0.5 * len(miss), 6.0),
                f"{len(miss)} of {len(names)} {kind} parts not found at all")
        if part:
            add("detect", min(1.0 + 0.25 * len(part), 3.0),
                f"{len(part)} of {len(names)} {kind} parts only partly found")
    for n, v in rec["parts"].items():
        if n in limbs:
            continue
        cluster = len(kinds.get(v["kind"], [])) >= 4
        if v["detected"] == "missed" and not cluster:
            add("detect", 3, f"{n}: not found at all")
        elif v["detected"] == "partly" and not cluster:
            add("detect", 1.5, f"{n}: only partly found ({v['found_as'][0][2]:.0%} as {v['found_as'][0][0]})")
        if v["fragments"] > 1:
            add("detect", 1, f"{n}: found in {v['fragments']} pieces")
        if v["merged_with"]:
            add("detect", 1.5, f"{n}: found as one part with {', '.join(v['merged_with'])}")
        if v["class"].startswith("wrong"):
            add("rig", 1, f"{n} ({v['kind']}): classified {v['class']}")
        elif v["class"].startswith("generic"):
            generic.append(f"{n}={v['class'][9:-1]}")
    if generic:
        add("rig", min(0.25 * len(generic), 1.0), "no class for: " + ", ".join(generic)[:160])
    if rec["phantoms"]:
        ph = ", ".join(f"{f['name']}={f['kind']}->{next(iter(f['truth']), '?')}" for f in rec["found"]
                       if f["name"] in rec["phantoms"])
        add("rig", min(0.5 * len(rec["phantoms"]), 2),
            f"{len(rec['phantoms'])} phantom part(s) on body/limbs: {ph[:200]}")
    return round(sum(cat.values()), 2), why, {k: round(v, 2) for k, v in cat.items()}


def render_sheet(key, ob, info, fmasks, rec, out: Path) -> None:
    """A small picture per body: ground truth (front, back) and what was found (back)."""
    import bpy
    import numpy as np
    me = ob.data
    sc = bpy.context.scene
    sc.render.engine = "BLENDER_WORKBENCH"
    sc.display.shading.light, sc.display.shading.color_type = "STUDIO", "VERTEX"
    sc.render.resolution_x = sc.render.resolution_y = 320
    cam = bpy.data.objects.new("zoo_cam", bpy.data.cameras.new("zoo_cam"))
    sc.collection.objects.link(cam)
    sc.camera = cam
    cam.data.type = "ORTHO"
    import bodies_zoo as Z
    co = Z.coords(me)
    lo, hi = co.min(axis=0), co.max(axis=0)
    c = (lo + hi) / 2
    cam.data.ortho_scale = float(max(hi[0] - lo[0], hi[2] - lo[2])) * 1.1
    files = []
    for tag, lab in (("truth", info["truth"]), ("found", None)):
        if lab is None:
            lab = np.zeros(len(co), np.int32)
            for i, (_a, m) in enumerate(fmasks, start=1):
                lab[m & (lab == 0)] = i
        pal = np.array([(0.72, 0.72, 0.72)] + [__import__("colorsys").hsv_to_rgb((i * 0.618) % 1, 0.75, 0.95)
                                               for i in range(1, int(lab.max()) + 2)], np.float32)
        if "zoo_view" in me.color_attributes:
            me.color_attributes.remove(me.color_attributes["zoo_view"])
        a = me.color_attributes.new("zoo_view", "FLOAT_COLOR", "POINT")
        a.data.foreach_set("color", np.concatenate([pal[lab], np.ones((len(lab), 1), np.float32)], 1).ravel())
        me.color_attributes.active_color = a
        for view, loc, rot in (("front", (c[0], lo[1] - 5, c[2]), (1.5708, 0, 0)),
                               ("back", (c[0], hi[1] + 5, c[2]), (1.5708, 0, 3.14159))):
            if tag == "found" and view == "front":
                continue
            cam.location, cam.rotation_euler = loc, rot
            sc.render.filepath = str(out / f"_{key}_{tag}_{view}.png")
            bpy.ops.render.render(write_still=True)
            files.append(sc.render.filepath)
    try:
        from PIL import Image
        ims = [Image.open(f) for f in files]
        sheet = Image.new("RGB", (sum(i.width for i in ims), ims[0].height), "white")
        x = 0
        for im in ims:
            sheet.paste(im, (x, 0))
            x += im.width
        sheet.save(out / f"{key}.png")
        for f in files:
            Path(f).unlink(missing_ok=True)
    except ImportError:
        pass


def summary(rec) -> str:
    lines = [f"[{rec['body']}] score {rec['score']} {rec.get('score_by', '')}"]
    lines += [f"    - {p}" for p in rec["problems"]]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--repo", default=str(HERE.parent), help="checkout whose product code is measured")
    ap.add_argument("--out", default=str(Path(tempfile.gettempdir()) / "zoo_baseline"))
    ap.add_argument("--side", default="left,right", help="mirror sides to plan and run (auto always runs)")
    ap.add_argument("--mode", default="fast", choices=("fast", "real", "both"))
    ap.add_argument("--ai", default="off", choices=("off", "on", "both"), help="AI-like surface (blend + noise)")
    ap.add_argument("--voxel", type=float, default=0.008)
    ap.add_argument("--budget", type=int, default=40000, help="triangles for the real run")
    ap.add_argument("--render", action="store_true")
    ap.add_argument("--rescore", action="store_true", help="only recompute the scores of the baseline.json in --out")
    ap.add_argument("bodies", nargs="*")
    args = ap.parse_args(argv)
    args.sides = [s for s in args.side.split(",") if s in ("left", "right")]
    _setup(Path(args.repo).resolve())
    out = Path(args.out)
    if args.rescore:
        doc = json.loads((out / "baseline.json").read_text())
        for rec in doc["bodies"].values():
            if "parts" in rec:
                rec["score"], rec["problems"], rec["score_by"] = score(rec)
                print(summary(rec))
        doc["ranking"] = sorted(((k, r["score"]) for k, r in doc["bodies"].items()), key=lambda x: -x[1])
        (out / "baseline.json").write_text(json.dumps(doc, indent=1, default=str))
        print("ranking:", doc["ranking"])
        return
    out.mkdir(parents=True, exist_ok=True)
    todo = [b for b in BODIES if not args.bodies or b[0] in args.bodies]
    variants = {"off": [("", {})], "on": [("+ai", AI)], "both": [("", {}), ("+ai", AI)]}[args.ai]
    path = out / "baseline.json"
    old = json.loads(path.read_text()) if path.exists() and args.bodies else {}
    results = dict(old.get("bodies", {}))
    import bodies_zoo as Z
    for key, gen, kw in todo:
        for suffix, opts in variants:
            name = key + suffix
            t = time.time()
            try:
                rec = run_body(name, gen, {"voxel": args.voxel, **kw, **opts}, args)
            except Exception as exc:                                 # noqa: BLE001
                rec = {"body": name, "errors": [{"step": "build", "error": f"{type(exc).__name__}: {exc}",
                                                 "trace": traceback.format_exc(limit=6)}], "score": 99,
                       "problems": [f"build failed: {exc}"]}
            rec["timing_total"] = round(time.time() - t, 1)
            results[name] = rec
            print(summary(rec) + f"  ({rec['timing_total']} s)")
            sys.stdout.flush()
    ranking = sorted(results, key=lambda k: -results[k]["score"])
    version = None
    try:
        version = importlib.import_module("forge_send").bl_info.get("version")
    except Exception:                                                # noqa: BLE001
        pass
    doc = {"what": __doc__.split("\n\n")[0], "repo": str(Path(args.repo).resolve()), "addon_version": version,
           "args": {k: v for k, v in vars(args).items() if k != "bodies"},
           "ranking": [(k, results[k]["score"]) for k in ranking], "bodies": results}
    path.write_text(json.dumps(Z.info_json(doc), indent=1, default=str))
    print("ranking:", doc["ranking"])
    print("written:", path)


if __name__ == "__main__":
    main()
