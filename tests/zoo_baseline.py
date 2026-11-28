"""Baseline: what the product does with every body of the test zoo (tests/bodies_zoo.py),
measured against the zoo's ground truth. A before/after tool for fix branches:

    python tests/zoo_baseline.py --repo <checkout> --out <dir> [--side left,right] [--mode fast|real|both]
                                 [--ai off|on|ain|both|all] [--zoo v1|v2|all] [--voxel 0.008]
                                 [--budget 40000] [--render] [--rescore] [--summary] [body ...]

The zoo always comes from this file's folder; the product (blender_scripts, blender_addon) from
--repo (default: this checkout), so the same bodies can be run against any version.

Per body:
  - joints.estimate against the zoo's joints_hint (humanoid bodies; a quadruped's on a line of
    its own)
  - appendages.from_object: which zoo parts are found, in how many pieces, under which kind; a
    part the product's plan gives a row of its own (one row covering >= 60 % of it) is found too
  - parts.one_sided_parts and the mirror numbers (straddles_middle, mirror_plane, asymmetry, and
    the mirror gap: how far the mirror image of each vertex lies from the surface)
  - the Step 4 parts plan for Symmetry "auto" (steps.prepare_maps, the default path) and for each
    side asked (steps.plan_parts), with every region the plan cuts, protects, paints or makes
    rigid and how much of each limb that region holds
  - mode "fast": a dry run of each plan with the product's own executor: ledger.prepare on the
    ledger the plan stored, once the product has one (forge_bpy.ledger); until then today's
    rescue.split_off, then density.symmetrize for a side unless a cut failed or the plan blocked
    it (what the plan says). Cut, lost, copied and torn shares come from what the executor
    actually returned, never from the plan. Auto's Quad Remesher X-symmetry flag is read from the product (the ledger's
    qr_symmetry, else the forge_symmetry_x steps.prepare_retopo writes on the new mesh).
  - mode "real": steps.run_retopo itself (prepare_maps, prepare_retopo, retopo._run_qr with its
    split_off, mirror, piece remesh and weld) with tests/fake_qr.py as Quad Remesher (it returns
    the input reduced to the asked size; fitting, carving and the shape check are off), and the
    final mesh measured against the original.
  - per run, label-free: the unplanned change (surface lost or added between the original and
    the result, beyond the harness's tolerance - the body's noise floor, never under a quarter of
    the coarser mesh's edge - in islands, outside what the product allowed), plan drift (the
    executor's fingerprints at plan time against the run's: in fast mode a second run that
    decides the mirror as retopo._qr_one does, in real mode the real run) and the mirror residual
    on the matched core.
Scores (higher = worse) and plain-language problems per body; baseline.json and summary.txt in
--out. Three totals, kept apart:
  - old total: the first zoo (BODIES) plain and +ai, scored by score(). Its lines never change,
    so the number stays comparable from branch to branch;
  - new lines: score_new() on the same records (unplanned change, plan fingerprint != run, an
    action region that takes a limb, a loose piece copied or lost, the quadruped skeleton off).
    They would move the old total, so they are a column of their own;
  - zoo v2: the bodies the first zoo could not test (BODIES_V2, every variant asked) and every
    body's +ain variant (an AI-like surface that is not its own mirror image), old and new
    lines together.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import math
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
BODIES_V2 = [(n, n, {}) for n in ("humanoid_raised_arm", "pouch_small", "relief_scar")]
AI = {"blend": 0.03, "noise": 0.004}                               # the AI-like surface (Step 4 needs no colour)
AIN = {**AI, "skew": 0.003}                                        # ... and not its own mirror image (bodies_zoo.SKEW)
VARIANTS = {"off": [("", {})], "on": [("+ai", AI)], "ain": [("+ain", AIN)], "both": [("", {}), ("+ai", AI)],
            "all": [("", {}), ("+ai", AI), ("+ain", AIN)]}
MIRROR_MODES = ("exact", "keep-around")                            # the product's modes that mirror the body

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
# a quadruped's joints_hint names on the product's joints: front legs on the arm chain, hind legs on
# the leg chain (what a skeleton made for it must put there; a joint the product has no key for
# is not placed)
QUAD_JOINT_MAP = {"pelvis": ("pelvis", 0), "neck": ("neck", 0), "head": ("head", 0)}
for _s in "lr":
    QUAD_JOINT_MAP.update({f"shoulder_f{_s}": (f"upperarm_{_s}", 0), f"elbow_f{_s}": (f"lowerarm_{_s}", 0),
                           f"wrist_f{_s}": (f"hand_{_s}", 0), f"hip_b{_s}": (f"thigh_{_s}", 0),
                           f"knee_b{_s}": (f"calf_{_s}", 0), f"ankle_b{_s}": (f"foot_{_s}", 0)})


def _setup(repo: Path):
    for p in (repo / "blender_addon", repo / "blender_scripts", HERE):
        sys.path.insert(0, str(p))


def generator(name: str):
    """The zoo generator of that name (the first zoo or zoo v2)."""
    import bodies_zoo as Z
    return {**Z.ZOO, **Z.ZOO_V2}[name]


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


def taken_by(co0, pieces, shift: float = 0.0, kd=None):
    """Which original vertices the cut pieces took (found again, unmoved, in a returned piece;
    the pieces may be in the mirror frame, `shift` along x)."""
    import numpy as np
    taken = np.zeros(len(co0), bool)
    if not pieces:
        return taken
    kd = kd or _kd(co0)
    for P in pieces:
        for p in P.tolist():
            for q in (p, (p[0] + shift, p[1], p[2])):
                _c, j, d = kd.find(q)
                if d < 1e-5:
                    taken[j] = True
                    break
    return taken


def cut_shares(co0, lab, labels, pieces, shift: float = 0.0) -> dict:
    """Share of each ground-truth part that split_off really took (taken_by)."""
    if not pieces:
        return {}
    taken = taken_by(co0, pieces, shift)
    out = {}
    for k, name in enumerate(labels):
        m = lab == k
        if m.any() and taken[m].any():
            out[name] = round(float(taken[m].mean()), 3)
    return out


def lost_copied(co0, lab, labels, result_co, result_tree, tol: float, plane: float = 0.0, d0=None) -> tuple:
    """(share of each part no longer on the result surface, share of each part copied by a mirror
    onto new surface): new = result vertices far from the original whose mirror image is near an
    original vertex of that part. d0: the original vertices' distances to the result surface, when
    already measured."""
    import numpy as np
    if d0 is None:
        d0 = surface_distances(co0, result_tree)
    lost = d0 > tol
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


def surface_distances(P, tree):
    """Distance from each point to the surface of a BVH tree."""
    import numpy as np
    from mathutils import Vector
    out = np.empty(len(P))
    fn = tree.find_nearest
    for i, p in enumerate(P.tolist()):
        h = fn(Vector(p))
        out[i] = h[3] if h[0] is not None else np.inf
    return out


def mirror_gaps(co, tree, plane: float, idx=None):
    """How far the mirror image (across x = plane) of each vertex (or of the chosen ones) lies
    from the surface: 0 where the surface is its own mirror image."""
    import numpy as np
    P = co if idx is None else co[idx]
    M = P.copy()
    M[:, 0] = 2 * plane - M[:, 0]
    return surface_distances(M, tree) if len(M) else np.zeros(0)


def vertex_area(me):
    """Surface area per vertex (each face's area shared out among its corners)."""
    import numpy as np

    import bodies_zoo as Z
    lv, ls, lt = Z._faces(me)
    fa = np.empty(len(me.polygons), np.float32)
    me.polygons.foreach_get("area", fa)
    return np.bincount(lv, weights=np.repeat(fa.astype(np.float64) / np.maximum(lt, 1), lt), minlength=len(me.vertices))


def islands(mask, ev, area, min_area: float) -> list:
    """Connected pieces of a vertex set along the mesh edges, each as a sorted index array, those
    of at least `min_area`, largest first (ties: lowest first vertex)."""
    import numpy as np

    import bodies_zoo as Z
    idx = np.nonzero(mask)[0]
    if not len(idx):
        return []
    remap = np.full(len(mask), -1)
    remap[idx] = np.arange(len(idx))
    e = ev[mask[ev[:, 0]] & mask[ev[:, 1]]]
    comp = Z._components(len(idx), remap[e[:, 0]], remap[e[:, 1]])
    out = [idx[comp == c] for c in np.unique(comp)]
    out = [g for g in out if float(area[g].sum()) >= min_area]
    return sorted(out, key=lambda g: (-float(area[g].sum()), int(g[0])))


def dilate(mask, ev, rings: int):
    """The vertex set grown by `rings` rings of edges."""
    m = mask.copy()
    for _ in range(rings):
        g = m.copy()
        g[ev[m[ev[:, 0]], 1]] = True
        g[ev[m[ev[:, 1]], 0]] = True
        m = g
    return m


def _polys(me) -> list:
    """A mesh's faces as lists of vertex indices."""
    import bodies_zoo as Z
    lv, ls, lt = Z._faces(me)
    return [lv[ls[i]:ls[i] + lt[i]].tolist() for i in range(len(ls))]


def on_pieces(P, pieces, faces, shift: float = 0.0):
    """How far each point lies from the cut-off pieces as split_off returned them (their surface,
    the plug that reaches back into the body included); the pieces may be in the mirror frame,
    `shift` along x. Infinite without pieces."""
    import numpy as np
    from mathutils.bvhtree import BVHTree
    if not pieces:
        return np.full(len(P), np.inf)
    V, F = [], []
    for co, fs in zip(pieces, faces):
        off = len(V)
        V += (np.asarray(co, float) + [shift, 0.0, 0.0]).tolist()
        F += [[i + off for i in f] for f in fs]
    return surface_distances(P, BVHTree.FromPolygons(V, F))


def cut_piece_shells(me, from_cut):
    """The result vertices of every shell (connected piece) of `me` made mostly, by area, of
    surface the cut took (from_cut: per result vertex, its nearest original vertex was cut off):
    a cut piece the run keeps as a shell of its own inside a mesh, its plug included (the hidden
    part that reaches back into the body, far from any cut-off surface). All of it is planned."""
    import numpy as np

    import bodies_zoo as Z
    ev = Z.edges(me)
    comp = Z._components(len(me.vertices), ev[:, 0], ev[:, 1])
    area = vertex_area(me)
    out = np.zeros(len(me.vertices), bool)
    for c in np.unique(comp).tolist():
        g = comp == c
        if float(area[g & from_cut].sum()) >= 0.5 * float(area[g].sum()):
            out |= g
    return out


def fingerprint(me) -> str:
    """The product's fingerprint of a mesh (density.fingerprint) when it has one, else this
    harness's own: a hash of the vertex and face counts and of the positions in sorted order, so
    the same surface gives the same print whatever order its vertices are in."""
    import numpy as np
    from forge_bpy import density
    fp = getattr(density, "fingerprint", None)
    if fp is not None:
        return str(fp(me))
    co = np.empty(len(me.vertices) * 3, np.float32)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    order = np.lexsort((co[:, 2], co[:, 1], co[:, 0]))
    h = hashlib.sha1(np.array([len(me.vertices), len(me.polygons)], np.int64).tobytes())
    h.update(np.ascontiguousarray(co[order]).tobytes())
    return h.hexdigest()[:16]


def joined(meshes):
    """One mesh holding copies of all the given meshes (the faithful result: body and pieces)."""
    import bmesh
    import bpy
    out = bpy.data.meshes.new("_zoo_result")
    bm = bmesh.new()
    for m in meshes:
        bm.from_mesh(m)
    bm.to_mesh(out)
    bm.free()
    return out


class Original:
    """The body as built, measured once for every comparison of a result with it: positions,
    edges, area per vertex, a surface tree and a vertex tree, the sizes every tolerance is a ratio
    of, and how far the mirror image of each vertex lies from the surface (across the product's
    own mirror plane, density.mirror_plane)."""

    def __init__(self, me, lab, labels, flab, apps: dict):
        import numpy as np

        import bodies_zoo as Z
        from forge_bpy import density
        self.co, self.ev = Z.coords(me), Z.edges(me)
        self.lab, self.labels, self.flab, self.apps = lab, labels, np.asarray(flab), apps
        self.area = vertex_area(me)
        self.tree, self.kd = _tree(me), _kd(self.co)
        # the mesh's own edge; the smallest island that counts is (2 e_ref)^2, e_ref the quad
        # edge of the finest export target (Unreal 30k triangles over this area), as in the plan
        self.edge = float(np.median(np.linalg.norm(self.co[self.ev[:, 0]] - self.co[self.ev[:, 1]], axis=1)))
        self.e_ref = math.sqrt(float(self.area.sum()) / 15000.0)
        self.min_area = (2 * self.e_ref) ** 2
        self.plane = float(density.mirror_plane(me))
        self.gaps = mirror_gaps(self.co, self.tree, self.plane)
        # the noise floor (the plan's principle 7): 3 x the body's own median mirror gap. Below
        # it a difference cannot be told from the surface's own asymmetry
        self.noise = 3.0 * float(np.median(self.gaps[np.isfinite(self.gaps)]))
        self.tau = self.change_tau(self.edge)

    def change_tau(self, res_edge: float) -> float:
        """The tolerance of the label-free change against a result whose median edge is
        `res_edge`: the noise floor, never under a quarter of the coarser mesh's edge (two
        samplings of the same smooth surface stay within a quarter edge of each other wherever
        it curves less sharply than half an edge, so a smaller difference cannot be told from
        the resampling)."""
        return max(self.noise, 0.25 * max(self.edge, float(res_edge)))

    def gap_summary(self) -> dict:
        import numpy as np
        g = self.gaps[np.isfinite(self.gaps)]
        return {"median_mm": round(1000 * float(np.median(g)), 3),
                "p90_mm": round(1000 * float(np.percentile(g, 90)), 3),
                "plane": round(self.plane, 5)}


def median_edge(me) -> float:
    """A mesh's median edge length (0 for a mesh without edges)."""
    import numpy as np

    import bodies_zoo as Z
    co, ev = Z.coords(me), Z.edges(me)
    return float(np.median(np.linalg.norm(co[ev[:, 0]] - co[ev[:, 1]], axis=1))) if len(ev) else 0.0


def compare(O, res_me, res_co, res_tree, d0, allow0, tau_product=None, allowance: str = "", allow1=None,
            near=None) -> dict:
    """The label-free change between the original and a result: original vertices farther than
    tau from the result (lost) and result vertices farther than tau from the original (added),
    as islands of at least O.min_area, outside what the product allowed to change (allow0: a mask
    on the original; a result vertex is allowed where its nearest original vertex is, or where
    allow1, a mask on the result, says so). tau is O.change_tau of the result's own edge: the
    body's noise floor, never under a quarter of the coarser mesh's edge; a smaller change is
    not measured. Also the mirror residual on the matched core (result vertices whose nearest
    original vertex has its mirror image on the surface within tau): how far their own mirror
    image lies from the result. Truth labels only name where an island is. near: each result
    vertex's nearest original vertex, when already looked up."""
    import numpy as np

    import bodies_zoo as Z
    from mathutils import Vector
    d1 = surface_distances(res_co, O.tree)
    if near is None:
        near = np.array([O.kd.find(p)[1] for p in res_co.tolist()], np.int64)
    res_edge = median_edge(res_me)
    tau = O.change_tau(res_edge)
    lost = d0 > tau
    added = d1 > tau
    if allow0 is not None:
        lost &= ~allow0
        added &= ~allow0[near]
    if allow1 is not None:
        added &= ~allow1
    ev1, area1 = Z.edges(res_me), vertex_area(res_me)
    li = islands(lost, O.ev, O.area, O.min_area)
    ai = islands(added, ev1, area1, O.min_area)

    def where(lab_of) -> dict:
        vals, cnt = np.unique(lab_of, return_counts=True)
        o = np.lexsort((vals, -cnt))
        return {O.labels[int(vals[i])]: round(float(cnt[i] / cnt.sum()), 2) for i in o[:3]}
    out = {"tau_mm": round(1000 * tau, 2), "noise_floor_mm": round(1000 * O.noise, 2),
           "resolution_mm": round(250 * max(O.edge, res_edge), 2),
           "tau_product_mm": "n/a" if tau_product is None else round(1000 * tau_product, 2),
           "min_area_cm2": round(1e4 * O.min_area, 2), "allowance": allowance or "none",
           "lost": [{"area_cm2": round(1e4 * float(O.area[g].sum()), 1), "verts": int(len(g)), "where": where(O.lab[g])}
                    for g in li],
           "added": [{"area_cm2": round(1e4 * float(area1[g].sum()), 1), "verts": int(len(g)),
                      "where": where(O.lab[near[g]])} for g in ai]}
    out["islands"] = len(out["lost"]) + len(out["added"])
    out["lost_cm2"] = round(sum(x["area_cm2"] for x in out["lost"]), 1)
    out["added_cm2"] = round(sum(x["area_cm2"] for x in out["added"]), 1)
    # the mirror residual on the matched core (a sample: at most about 20k result vertices)
    sel = np.arange(0, len(res_co), max(1, len(res_co) // 20000))
    sel = sel[O.gaps[near[sel]] <= tau]
    M = res_co[sel].copy()
    M[:, 0] = 2 * O.plane - M[:, 0]
    r = np.array([res_tree.find_nearest(Vector(p))[3] for p in M.tolist()]) if len(M) else np.zeros(0)
    resid = {"median_mm": round(1000 * float(np.median(r)), 3) if len(r) else None,
             "p95_mm": round(1000 * float(np.percentile(r, 95)), 3) if len(r) else None, "verts": int(len(sel))}
    return {"unplanned_change": out, "mirror_residual": resid, "d1": d1, "near": near}


def part_scale_lost_copied(O, d0, d1, res_co, tol: float) -> tuple:
    """Lost and copied shares for parts that lie on the body (truth `proud`: a pad, a relief),
    judged at their own scale: tolerance min(tol, half the part's measured height), never under
    3 x the body's own mirror gap (its noise floor: below it a difference cannot be told from the
    surface's own asymmetry). A copy is a result vertex off the original whose mirror image lands
    on the part's own faces."""
    from mathutils import Vector
    lo, co, tols = {}, {}, {}
    noise = O.noise
    for name in sorted(O.apps):
        e = O.apps[name]
        if not e.get("proud") or name not in O.labels:
            continue
        k = O.labels.index(name)
        m = O.lab == k
        t = max(min(tol, 0.5 * float(e["proud"])), noise)
        tols[name] = round(1000 * t, 2)
        lo[name] = round(float((d0[m] > t).mean()), 3)
        n = 0
        for p in res_co[d1 > t].tolist():
            hit = O.tree.find_nearest(Vector((2 * O.plane - p[0], p[1], p[2])))
            if hit[0] is not None and hit[3] <= t and int(O.flab[hit[2]]) == k:
                n += 1
        if n:
            co[name] = round(n / int(m.sum()), 3)
    return lo, co, tols


def _plan_names(me) -> dict:
    return {int(k): str(v) for k, v in dict(me.get("forge_split_names") or {}).items()}


def _ledger_module():
    """The product's Step 4 ledger (forge_bpy.ledger: decide, prepare), or None while the product
    has none."""
    try:
        return importlib.import_module("forge_bpy.ledger")
    except ImportError:
        return None


def stored_ledger(ob, me):
    """The ledger the product's plan stored on the body (forge_ledger, JSON), or None."""
    raw = me.get("forge_ledger") if me is not None else None
    if raw is None and ob is not None:
        raw = ob.get("forge_ledger")
    if raw is None:
        return None
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except ValueError:
            return None
    return raw.to_dict() if hasattr(raw, "to_dict") else dict(raw)


def _ledger_qr(ledger):
    q = (ledger or {}).get("qr_symmetry")
    return q.get("on") if isinstance(q, dict) else q


def execute(me, ids, side, ledger=None, as_run: bool = False) -> dict:
    """Step 4's executor once, on a copy of `me`. With the product's ledger (forge_bpy.ledger
    and a ledger its plan stored): ledger.prepare(copy, ledger), which this harness expects to
    return {'fit_target', 'qr_input', 'pieces': [(k, mesh, plug)], 'refused': [(k, why)], 'mode',
    'qr_symmetry', 'fps', 'allow'} in the copy's own frame (anything missing reads as not
    reported); the plan and the run then share it. Until then today's executor: split_off the
    planned parts in the mirror frame, then (for a side) mirror the body unless a cut failed or
    the plan blocked it - what the plan says. as_run: decide the mirror again the way
    retopo._qr_one does at run time, with its own helpers when the product has them (a refused
    part that is its own mirror image does not stop the mirror, retopo._symmetric_part; a cut
    whose lid would be copied onto bare skin does, retopo._lids_mirror_onto_skin). Fingerprints
    are taken in the frame the executor works in. 'executor' says which one ran."""
    import numpy as np
    from mathutils import Matrix
    from forge_bpy import density, rescue
    L = _ledger_module()
    if ledger is not None and L is not None and callable(getattr(L, "prepare", None)):
        m2 = me.copy()
        res = L.prepare(m2, ledger) or {}
        body = res.get("fit_target") or m2
        mode = res.get("mode") or (ledger.get("mirror") or {}).get("mode")
        qr = res.get("qr_symmetry")
        qr = qr.get("on") if isinstance(qr, dict) else qr
        qr = _ledger_qr(ledger) if qr is None else qr
        allow = res.get("allow")
        allow = np.asarray(allow, bool) if allow is not None and len(allow) == len(me.vertices) else None
        mirrored = mode in MIRROR_MODES
        why = "" if mirrored or side not in ("left", "right") else \
            f"not mirrored: {(ledger.get('mirror') or {}).get('why') or mode}"
        return {"body": body, "qr_input": res.get("qr_input"),
                "pieces": [(int(p[0]), p[1]) for p in res.get("pieces", [])],
                "refused": [(int(k), str(w)) for k, w in res.get("refused", [])], "mirrored": mirrored, "mode": mode,
                "why_not": why, "shift": 0.0, "fps": res.get("fps") or {}, "allow": allow,
                "qr_symmetry": None if qr is None else bool(qr), "tau": (ledger.get("frame") or {}).get("tau_keep"),
                "spare": [m for m in (m2,) if m is not body], "executor": "ledger"}
    m2 = me.copy()
    mirror = side in ("left", "right") and density.straddles_middle(me)
    shift = density.mirror_plane(m2) if mirror else 0.0
    if abs(shift) > 1e-6:
        m2.transform(Matrix.Translation((-shift, 0, 0)))
    full = m2.copy() if as_run else None           # (the whole body before the cut, as the run keeps it)
    rep: list = []
    pieces = rescue.split_off(m2, ids, rep) if ids is not None else []
    blocked = me.get("forge_mirror_blocked")
    why = note = ""
    if as_run:
        from forge_bpy import retopo
        symmetric = getattr(retopo, "_symmetric_part", None)
        lids = getattr(retopo, "_lids_mirror_onto_skin", None)
        lopsided = [k for k, _w in rep if k and not (symmetric is not None and symmetric(full, ids, k))]
        if mirror and (lopsided or blocked):
            mirror = False
            why = f"not mirrored: {blocked or 'a one-sided part could not be cut off'}"
        elif mirror and rep:
            note = "still mirrored: the part kept with the body is its own mirror image"
        uneven = lids(m2, side) if mirror and pieces and lids is not None else []
        if uneven:
            mirror = False
            why = f"not mirrored: the cut for part(s) {uneven} sits to one side of the middle"
        bpy_remove(full)
    elif mirror and (rep or blocked):
        mirror = False
        why = f"not mirrored: {blocked or 'a cut failed'}"
    if mirror:
        density.symmetrize(m2, side)
    fps = {"body": fingerprint(m2), "pieces": {str(int(k)): fingerprint(pm) for k, pm, _p in pieces}}
    if abs(shift) > 1e-6:
        m2.transform(Matrix.Translation((shift, 0, 0)))
        for _k, pm, _p in pieces:
            pm.transform(Matrix.Translation((shift, 0, 0)))
    return {"body": m2, "qr_input": None, "pieces": [(int(k), pm) for k, pm, _p in pieces],
            "refused": [(int(k), w) for k, w in rep], "mirrored": bool(mirror), "mode": None, "why_not": why,
            "shift": float(shift), "fps": fps, "allow": None, "qr_symmetry": None, "tau": None, "spare": [],
            "executor": "shim, deciding as the run" if as_run else "shim", "note": note}


def _free(ex) -> None:
    for m in [ex["body"], ex.get("qr_input")] + [pm for _k, pm in ex["pieces"]] + list(ex.get("spare", [])):
        if m is not None:
            bpy_remove(m)


def plan_prints(me, ids, side, ledger=None) -> dict:
    """The executor's fingerprints for this plan, as the plan would see them: the ledger's own
    (its dry run) when the product has one, else one run of the plan's executor on a copy."""
    if ledger is not None and (ledger.get("dry") or {}).get("fps"):
        return dict(ledger["dry"]["fps"])
    ex = execute(me, ids, side, ledger)
    fps = ex["fps"]
    _free(ex)
    return fps


def dry_run(me, ids, side, lab, labels, voxel, qr_sym_auto, O=None, ledger=None) -> dict:
    """Step 4 before remeshing, with the product's executor (execute), measured against the
    original: what was cut, refused, lost and copied (the old columns), then the label-free
    unplanned change, the mirror residual on the matched core, pads and reliefs at their own
    scale, and plan drift: the plan's fingerprints against a second, independent run that
    decides as the product's run does (the ledger's own prints once it has one). A second run
    also shows an executor that does not repeat itself (hidden non-determinism is drift too)."""
    import numpy as np

    import bodies_zoo as Z
    co0 = Z.coords(me)
    ex = execute(me, ids, side, ledger)
    pieces, m2, shift = ex["pieces"], ex["body"], ex["shift"]
    planned = sorted(set(int(i) for i in (ids if ids is not None else [])) - {0})
    names = _plan_names(me)
    got = [int(k) for k, _pm in pieces]
    out = {"executor": ex["executor"], "mirrored": bool(ex["mirrored"]), "why_not": ex["why_not"],
           "plane": round(float(shift), 4),
           "planned": [names.get(k, str(k)) for k in planned], "cut": [names.get(k, str(k)) for k in got],
           "refused": [(names.get(int(k), str(k)), w) for k, w in ex["refused"]],
           "qr_symmetry": (bool(ex["qr_symmetry"]) if ex["qr_symmetry"] is not None else
                           bool(ex["mirrored"]) if side in ("left", "right") else bool(qr_sym_auto))}
    if ex["mode"] is not None:
        out["mode"] = ex["mode"]
    out["cut_share"] = cut_shares(co0, lab, labels, [Z.coords(pm) for _k, pm in pieces])
    res = np.concatenate([Z.coords(m2)] + [Z.coords(pm) for _k, pm in pieces]) if pieces else Z.coords(m2)
    tmp = joined([m2] + [pm for _k, pm in pieces])
    tree = _tree(tmp)
    d0 = surface_distances(co0, tree)
    out["lost"], out["copied"] = lost_copied(co0, lab, labels, res, tree, 2.5 * voxel, shift, d0=d0)
    if O is not None:
        try:
            allow1 = None
            if ex["allow"] is not None:
                allow, how = ex["allow"], "product"
            elif pieces:                        # (today: what was cut - every cut-off piece with the
                # plug that reaches back into the body - and the lid split_off closes the body with,
                # tagged forge_rim, as planned change)
                taken = taken_by(co0, [Z.coords(pm) for _k, pm in pieces], 0.0, O.kd)
                allow, how = dilate(taken, O.ev, 2), "harness: cut pieces and their lids"
                rim = _int_attr(m2, "forge_rim")
                allow1 = np.concatenate([rim > 0 if rim is not None else np.zeros(len(m2.vertices), bool)]
                                        + [np.ones(len(pm.vertices), bool) for _k, pm in pieces])
            else:
                allow, how = None, "none"
            c = compare(O, tmp, Z.coords(tmp), tree, d0, allow, ex["tau"], how, allow1)
            out["unplanned_change"], out["mirror_residual"] = c["unplanned_change"], c["mirror_residual"]
            lo, co, tols = part_scale_lost_copied(O, d0, c["d1"], Z.coords(tmp), 2.5 * voxel)
            if tols:
                out["lost"].update(lo)
                out["copied"].update(co)
                out["part_scale_mm"] = tols
            out["fps"] = ex["fps"]
            if ledger is not None and (ledger.get("dry") or {}).get("fps"):
                pd = {"plan": dict(ledger["dry"]["fps"]), "run": ex["fps"],
                      "how": "the product's plan prints against this run"}
            else:
                # the plan's executor (what the plan says) against a second run that decides
                # the mirror again as retopo._qr_one does
                run = execute(me, ids, side, None, as_run=True)
                pd = {"plan": ex["fps"], "run": run["fps"],
                      "how": "the plan's executor against a second run deciding as the product's run does"}
                if bool(run["mirrored"]) != bool(ex["mirrored"]):
                    pd["why"] = (f"the run {'mirrors' if run['mirrored'] else 'does not mirror'}: "
                                 f"{run['why_not'] or run.get('note') or 'its own mirror decision'}")[:120]
                elif run["fps"] != ex["fps"]:
                    pd["why"] = "the same decisions made another mesh (the executor does not repeat itself)"
                _free(run)
            out["plan_drift"] = {"drift": pd["plan"] != pd["run"], **pd}
        except Exception as exc:                                     # noqa: BLE001
            out["new_errors"] = [f"{type(exc).__name__}: {exc}"[:300]]
    _free(ex)
    bpy_remove(tmp)
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


def real_run(gen, kw, side, budget, voxel, plan_fps=None) -> dict:
    """steps.run_retopo for one side, Quad Remesher played by tests/fake_qr.py. plan_fps: the
    executor's fingerprints at plan time, to compare with what this run's executor made."""
    import bpy
    import numpy as np

    import bodies_zoo as Z
    import fake_qr
    from forge_bpy import addon_trial, density, rescue, retopo
    ob, info = generator(gen)(**kw)
    lab, labels = info["truth"], info["labels"]
    co0 = Z.coords(ob.data)
    S = as_forge_body(ob)
    eng = fake_qr.install()
    saved = (addon_trial.view3d_override, retopo._wait_limit, rescue.split_off, retopo.run, density.symmetrize)
    cuts, jobs, mirrored_fp = [], [], []

    def split_off(me, ids, report=None):
        rep = report if report is not None else []
        n0 = len(rep)
        out = saved[2](me, ids, rep)
        cuts.append({"planned": sorted(set(int(i) for i in np.unique(ids)) - {0}), "cut": [int(k) for k, _m, _p in out],
                     "refused": [(int(k), w) for k, w in rep[n0:]], "pieces": [Z.coords(pm) for _k, pm, _p in out],
                     "piece_faces": [_polys(pm) for _k, pm, _p in out],
                     "fps": {"body": fingerprint(me), "pieces": {str(int(k)): fingerprint(pm) for k, pm, _p in out}}})
        return out

    def symmetrize(me, side_):
        saved[4](me, side_)
        mirrored_fp.append(fingerprint(me))

    def run(args):
        args.update({"conform": False, "carve": False, "shape_check": False, "qr_timeout": 60})
        return saved[3](args)
    addon_trial.view3d_override = lambda: {"scene": bpy.context.scene}
    retopo._wait_limit = lambda obj, timeout: 60.0
    rescue.split_off = split_off
    retopo.run = run
    density.symmetrize = symmetrize
    retopo._QR_JOBS.clear()
    out = {"side": side}
    try:
        mirrors = side in ("left", "right") and density.straddles_middle(ob.data)
        plane = density.mirror_plane(ob.data) if mirrors else 0.0
        O = Original(ob.data, lab, labels, info["face_truth"], info["appendages"])
        m_in = ob.data.copy()                      # the run's input in the frame its executor works in
        if abs(plane) > 1e-6:
            from mathutils import Matrix
            m_in.transform(Matrix.Translation((-plane, 0, 0)))
        fp_in = fingerprint(m_in)
        bpy.data.meshes.remove(m_in)
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
        mode = (r.get("mirror") or {}).get("mode") if isinstance(r.get("mirror"), dict) else None
        out.update({"executor": "the product's run", "plan": plan, "blocked": ob.data.get("forge_mirror_blocked"),
                    "jobs": jobs,
                    "method": r.get("method"), "split_kept": r.get("split_kept", []),
                    "separate_parts": r.get("separate_parts", 0), "joints": r.get("joints", []),
                    "open_edges": r.get("open_edges"),
                    # (the product's mode when it reports one, else whether its symmetrize ran:
                    # forge_symmetry_x is Quad Remesher's flag, on in Auto for a body never mirrored)
                    "mirrored": (mode in MIRROR_MODES if mode else bool(mirrored_fp)) if body else None,
                    "why_not": next((w for w in r.get("split_kept", []) if w.startswith("not mirrored")), "")})
        if mode:
            out["mode"] = mode
        c = cuts[0] if cuts else {"planned": [], "cut": [], "refused": [], "pieces": [], "piece_faces": [], "fps": None}
        out["planned"] = [names.get(k, str(k)) for k in c["planned"]]
        out["cut"] = [names.get(k, str(k)) for k in c["cut"]]
        out["refused"] = [(names.get(k, str(k)), w) for k, w in c["refused"]]
        out["plane"] = round(float(plane), 4)
        out["cut_share"] = cut_shares(co0, lab, labels, c["pieces"], plane)
        out["qr_symmetry"] = bool(jobs[0]["symmetry_x"]) if jobs else None
        if body is not None:
            fin = Z.coords(body.data) @ np.array(body.matrix_world)[:3, :3].T + np.array(body.matrix_world)[:3, 3]
            tree = _tree(body.data)
            tol = max(2.5 * voxel, 0.02)
            out["lost"], out["copied"] = lost_copied(co0, lab, labels, fin, tree, tol, plane)
            out["final_tris"] = sum(len(p.vertices) - 2 for p in body.data.polygons)
        try:
            # ---- the new columns: the whole result (every new mesh, cut-off pieces kept apart
            # included) against the original (compare: its tolerance from both meshes' edges)
            lows = [o for o in S.lows() if o.type == "MESH"]
            if lows:
                parts_w = []
                for o in sorted(lows, key=lambda o: o.name):
                    m = o.data.copy()
                    m.transform(o.matrix_world)
                    parts_w.append(m)
                whole = joined(parts_w)
                for m in parts_w:
                    bpy.data.meshes.remove(m)
                wco = Z.coords(whole)
                wtree = _tree(whole)
                w_edge = median_edge(whole)
                d0w = surface_distances(co0, wtree)
                taken = taken_by(co0, c["pieces"], plane, O.kd)
                near = np.array([O.kd.find(p)[1] for p in wco.tolist()], np.int64)
                allow, how = ((dilate(taken, O.ev, 2), "harness: cut pieces and their lids") if taken.any()
                              else (None, "none"))
                # (a cut-off piece the run did not weld back stays a new mesh of its own: planned)
                allow1 = np.concatenate([np.full(len(o.data.vertices), o != body and taken.any())
                                         for o in sorted(lows, key=lambda o: o.name)])
                if taken.any():
                    allow1 |= cut_piece_shells(whole, taken[near])
                    # (and wherever the result lies on a piece as it was cut, plug included, also
                    # when the run attaches it to the body: the plug stays hidden inside)
                    allow1 |= on_pieces(wco, c["pieces"], c["piece_faces"], plane) <= O.change_tau(w_edge)
                cmp_ = compare(O, whole, wco, wtree, d0w, allow, None, how, allow1, near=near)
                out["unplanned_change"], out["mirror_residual"] = cmp_["unplanned_change"], cmp_["mirror_residual"]
                lo, co, tols = part_scale_lost_copied(O, d0w, cmp_["d1"], wco, 2.5 * max(O.edge, w_edge))
                if tols:
                    out.setdefault("lost", {}).update(lo)
                    out.setdefault("copied", {}).update(co)
                    out["part_scale_mm"] = tols
                bpy.data.meshes.remove(whole)
            # plan drift: the product's own prints when its run reports them, else what this run's
            # executor made (cut pieces, then the mirrored body) against the plan's prints
            pd = r.get("plan_drift")
            if isinstance(pd, dict):
                out["plan_drift"] = {"how": "the product's own prints", **pd,
                                     "drift": bool(pd.get("drift", pd.get("plan") != pd.get("run")))}
            elif plan_fps is not None:
                run_fps = {"body": mirrored_fp[-1] if mirrored_fp else (c["fps"] or {}).get("body", fp_in),
                           "pieces": (c["fps"] or {}).get("pieces", {})}
                out["plan_drift"] = {"drift": run_fps != plan_fps, "how": "the plan's executor against the real run's",
                                     "plan": plan_fps, "run": run_fps}
        except Exception as exc:                                     # noqa: BLE001
            out["new_errors"] = [f"{type(exc).__name__}: {exc}"[:300]]
    finally:
        addon_trial.view3d_override, retopo._wait_limit, rescue.split_off, retopo.run, density.symmetrize = saved
        fake_qr.uninstall()
        retopo._QR_JOBS.clear()
        bpy.ops.wm.read_homefile(use_empty=True)
    return out


def _int_attr(me, name):
    """A per-vertex int attribute as an array, or None."""
    import numpy as np
    a = me.attributes.get(name)
    if a is None or a.domain != "POINT" or a.data_type not in ("INT", "INT8", "BOOLEAN"):
        return None
    v = np.empty(len(me.vertices), np.int32 if a.data_type != "BOOLEAN" else bool)
    a.data.foreach_get("value", v)
    return v.astype(np.int32)


def product_rows(me, ledger) -> list:
    """The rows of the product's plan with their vertices (forge_ledger_row: per vertex the row
    id, 0 = none) as [(row, mask)], sorted by id; [] while the product keeps no rows."""
    import numpy as np
    v = _int_attr(me, "forge_ledger_row")
    if v is None:
        return []
    rows = {int(r.get("id", -1)): r for r in (ledger or {}).get("rows", []) if isinstance(r, dict)}
    return [(rows.get(int(k), {"id": int(k)}), v == k) for k in np.unique(v).tolist() if k > 0]


def product_protected(me, rows):
    """What the product's plan keeps as modelled while the rest is mirrored: forge_keep (per
    vertex), else the rows whose disposition keeps or protects; None while it reports neither."""
    import numpy as np
    keep = _int_attr(me, "forge_keep")
    if keep is not None:
        return keep > 0
    prot = [m for r, m in rows if any(w in str(r.get("disposition", "")) for w in ("keep", "protect"))]
    return np.any(prot, axis=0) if prot else None


def action_regions(me, rows, lab, labels, limbs) -> list:
    """Every region the product's plan acts on: each part it cuts (forge_split), each part it
    makes rigid and paints lighter (forge_horn_plan), each region it protects or gives a row
    (the ledger's rows), and each island it keeps as modelled (forge_keep, also without rows),
    with the share of each limb and of the body that lies inside it."""
    import numpy as np

    import bodies_zoo as Z
    from forge_bpy import density
    regions = []
    keep = _int_attr(me, "forge_keep")
    if keep is not None and (keep > 0).any():
        for i, g in enumerate(sorted(islands(keep > 0, Z.edges(me), np.ones(len(me.vertices)), 0.0),
                                     key=lambda g: int(g[0])), start=1):
            m = np.zeros(len(me.vertices), bool)
            m[g] = True
            regions.append(("protect", f"kept island {i}", m))
    ids = density.read_split(me)
    names = _plan_names(me)
    if ids is not None:
        for k in sorted(set(np.unique(ids).tolist()) - {0}):
            regions.append(("cut", names.get(int(k), str(k)), ids == k))
    hp = me.get("forge_horn_plan")
    if hp is not None and int(hp.get("nv", -1)) == len(me.vertices) and len(hp.get("idx", [])):
        idx, hid = np.asarray(hp["idx"], np.int64), np.asarray(hp["hid"], np.int64)
        for i, name in enumerate(list(hp["names"])):
            m = np.zeros(len(me.vertices), bool)
            m[idx[hid == i]] = True
            regions.append(("rigid", str(name), m))
    for r, m in rows:
        regions.append((str(r.get("disposition") or "row"), str(r.get("words") or r.get("id")), m))
    out = []
    for action, name, m in regions:
        share = {}
        for n in sorted(limbs):
            t = lab == labels.index(n)
            s = float((m & t).sum() / max(int(t.sum()), 1))
            if s >= 0.01:
                share[n] = round(s, 3)
        b = lab == labels.index("body")
        out.append({"action": action, "name": name, "verts": int(m.sum()), "limb_share": share,
                    "body_share": round(float((m & b).sum() / max(int(b.sum()), 1)), 3)})
    return out


def protection(O, prot, info) -> dict:
    """Island recall on the parts a mirror copies or deletes (one-sided, pair_asym, centre_asym):
    the share of each one's mirror-off vertices (mirror image farther than the harness's
    tolerance from the surface) the product protects; and false protection: the share of each
    pair / centre part it protects, and the protected area where the surface does match its
    mirror image. 'n/a' while the product reports no protection."""
    if prot is None:
        return {"recall": "n/a", "false": "n/a", "false_area": "n/a"}
    off = O.gaps > O.tau
    rec_, fal = {}, {}
    for n in sorted(info["appendages"]):
        e = info["appendages"][n]
        m = O.lab == O.labels.index(n)
        if e["symmetry"] in ONE_SIDED and (m & off).any():
            rec_[n] = round(float((prot & off & m).sum() / (m & off).sum()), 3)
        elif e["symmetry"] in ("pair", "centre"):
            fal[n] = round(float((prot & m).sum() / max(int(m.sum()), 1)), 3)
    return {"recall": rec_, "false": fal,
            "false_area": round(float(O.area[prot & ~off].sum() / max(float(O.area.sum()), 1e-12)), 4)}


def product_qr_auto(S, auto_ledger):
    """Auto's Quad Remesher X-symmetry flag as the product sets it: the ledger's qr_symmetry when
    the product has one, else what steps.prepare_retopo writes on the body's new mesh
    (forge_symmetry_x). Called after the plans: it makes the new meshes."""
    q = _ledger_qr(auto_ledger)
    if q is not None:
        return bool(q), "ledger qr_symmetry"
    S.prepare_retopo()
    low = S.body_low()
    if low is None or low.get("forge_symmetry_x") is None:
        raise RuntimeError("prepare_retopo made no new body mesh with forge_symmetry_x")
    return bool(low["forge_symmetry_x"]), f"prepare_retopo forge_symmetry_x (asymmetry {low.get('forge_asymmetry')})"


def run_body(key, gen, kw, args) -> dict:
    import bpy
    import numpy as np

    import bodies_zoo as Z
    from forge_bpy import appendages, density, joints, parts
    rec = {"body": key, "generator": gen, "params": kw, "errors": [], "errors_new": [], "timing": {},
           "zoo": "v2" if gen in Z.ZOO_V2 or key.endswith("+ain") else "v1"}
    t0 = time.time()
    ob, info = generator(gen)(**kw)
    rec["timing"]["build"] = round(time.time() - t0, 2)
    me = ob.data
    lab, labels, voxel = info["truth"], info["labels"], info["voxel"]
    rec["mesh"] = {"verts": len(me.vertices), "faces": len(me.polygons), "shells": Z.shells(me),
                   "height": round(info["height"], 3)}
    rec["truth"] = {n: {k: e[k] for k in ("kind", "side", "symmetry", "twin", "root_shape", "parent", "rig", "verts")}
                    for n, e in info["appendages"].items()}
    for n, e in info["appendages"].items():
        if e.get("proud"):
            rec["truth"][n]["proud_mm"] = round(1000 * float(e["proud"]), 2)
        if e.get("relief"):
            rec["truth"][n]["relief"] = True
    extras, limbs = list(info["appendages"]), list(info["limbs"])

    def step(name, fn, errors="errors"):
        t = time.time()
        try:
            return fn()
        except Exception as exc:                                     # noqa: BLE001
            rec[errors].append({"step": name, "error": f"{type(exc).__name__}: {exc}",
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
    if J is not None and info["kind"] == "quadruped":
        rec["joint_errors_quad"] = {}
        for j in sorted(info["joints_hint"]):
            if j in QUAD_JOINT_MAP:
                k, i = QUAD_JOINT_MAP[j]
                rec["joint_errors_quad"][j] = round(float(np.linalg.norm(
                    np.array(J[k][i][:]) - np.array(info["joints_hint"][j]))), 3) if k in J else None
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
    # the original measured once for the new columns (sizes, trees, the mirror gap of every vertex)
    O = step("measure the original", lambda: Original(me, lab, labels, info["face_truth"], info["appendages"]),
             errors="errors_new")
    if O is not None:
        rec["symmetry"]["mirror_gap"] = O.gap_summary()
        rec["tolerances"] = {"tau_mm": round(1000 * O.tau, 2), "noise_floor_mm": round(1000 * O.noise, 2),
                             "edge_mm": round(1000 * O.edge, 2), "min_island_cm2": round(1e4 * O.min_area, 2)}
    # ---- the Step 4 plans and their dry runs
    S = as_forge_body(ob)
    rec["plan"], rec["dry"] = {}, {}
    row_masks, ledgers = [], {}
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
        led = stored_ledger(ob, me)
        ledgers[side] = led
        pr = rec["plan"][side]
        if led is None and _ledger_module() is not None:
            # (the product has a ledger but this plan stored none: the dry run falls back to the
            # old executor, which must not pass unnoticed)
            rec["errors_new"].append({"step": f"plan[{side}]", "error": "forge_bpy.ledger exists but the plan "
                                      "stored no forge_ledger: the dry run used the old executor"})

        def plan_columns():
            rows = product_rows(me, led)
            row_masks.extend(m for _r, m in rows)
            pr["rows"] = [{"id": r.get("id"), "words": r.get("words"), "disposition": r.get("disposition"),
                           "truth": comp(m, lab, labels)} for r, m in rows] if rows else "n/a"
            if led is not None:
                pr["ledger"] = {"mirror": led.get("mirror"), "qr_symmetry": led.get("qr_symmetry"),
                                "frame": led.get("frame")}
            pr["regions"] = action_regions(me, rows, lab, labels, limbs)
            if O is not None:
                pr["protection"] = protection(O, product_protected(me, rows), info)
            if args.mode == "real":                  # (fast: the dry run's first run is the plan's)
                pr["fps"] = plan_prints(me, ids, side, led)
        step(f"plan columns[{side}]", plan_columns, errors="errors_new")
        if args.mode in ("fast", "both"):
            d = step(f"dry_run[{side}]", lambda: dry_run(me, ids, side, lab, labels, voxel, None, O, led))
            if d is not None:
                rec["dry"][side] = d
                if (d.get("plan_drift") or {}).get("plan") is not None:
                    pr["fps"] = d["plan_drift"]["plan"]
                for e in d.pop("new_errors", []):
                    rec["errors_new"].append({"step": f"dry_run[{side}] new columns", "error": e})
    # Auto's Quad Remesher symmetry, read from the product (never recomputed here)
    qr = step("product QR flag[auto]", lambda: product_qr_auto(S, ledgers.get("auto")), errors="errors_new")
    rec["symmetry"]["qr_symmetry_auto"] = qr[0] if qr else None
    rec["symmetry"]["qr_symmetry_auto_from"] = qr[1] if qr else "not read (see errors_new)"
    if "auto" in rec["dry"]:
        q = rec["dry"]["auto"]
        if q.get("mode") is None:                    # (the ledger's executor reports its own)
            q["qr_symmetry"] = bool(qr[0]) if qr else False
    # ---- the real run (one fresh build per side)
    rec["real"] = {}
    if args.mode in ("real", "both"):
        for side in ["auto"] + args.sides:
            r = step(f"real[{side}]", lambda: real_run(gen, kw, side, args.budget, voxel,
                                                       rec["plan"].get(side, {}).get("fps")))
            if r is not None:
                rec["real"][side] = r
                for e in r.pop("new_errors", []):
                    rec["errors_new"].append({"step": f"real[{side}] new columns", "error": e})
    # ---- verdicts per ground-truth part
    rec["parts"] = {}
    for n in extras + limbs:
        k = labels.index(n)
        tm = lab == k
        e = info["appendages"].get(n) or info["limbs"][n]
        v = {"kind": e["kind"], "symmetry": e["symmetry"], "side": e["side"]}
        cov = sorted(((a["name"], a["kind"], round(float((m & tm).sum() / max(tm.sum(), 1)), 3))
                      for a, m in fmasks if (m & tm).sum() >= 0.1 * tm.sum()), key=lambda x: -x[2])
        v["found_as"], v["fragments"] = cov, len(cov)
        best = cov[0][2] if cov else 0.0
        v["detected"] = "found" if best >= 0.5 else "partly" if best >= 0.15 else "missed"
        if row_masks:                                # one of the plan's rows covering it counts as found
            v["row_cover"] = round(max(float((m & tm).sum() / max(tm.sum(), 1)) for m in row_masks), 3)
            if v["row_cover"] >= 0.6:
                v["detected"] = "found"
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
    rec["score_new"], rec["problems_new"], rec["score_new_by"] = score_new(rec)
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
                # a limb posed unlike its twin (one raised arm) may take its twin's pose when the
                # body is mirrored from the other side: the chosen side wins, nothing is lost
                won = (rec["parts"][n]["symmetry"] == "pair_posed" and r.get("mirrored")
                       and rec["parts"][n].get("side") == {"left": "r", "right": "l"}.get(side))
                if lo > 0.05 and not won:           # (a hand is about a sixth of an arm)
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
            # (a relief is one of the small differences the fit puts back: it may stay on)
            left_on = [n for n, e in apps.items() if e["symmetry"] in ONE_SIDED and cut.get(n, 0.0) < 0.5
                       and not e.get("relief")]
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
    relief = {n for n, e in apps.items() if e.get("relief")}       # small differences, not parts (zoo v2)
    for n, v in rec["parts"].items():
        if n not in limbs and n not in relief:
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
        if n in relief:                              # (it belongs with the grouped small differences)
            if v["detected"] == "found":
                add("detect", 3, f"{n} ({v['kind']}): a small difference found as a part of its own")
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


NEW_LINES = ("unplanned change", "plan fingerprint != run", "action region takes a limb",
             "loose piece copied or lost", "quadruped skeleton off", "error in a new measurement")


def score_new(rec) -> tuple:
    """The lines the first harness did not have, scored apart from score() so the old total stays
    comparable (higher = worse): 'unplanned change' +8 per run with an island of change outside
    what the product allowed; 'plan fingerprint != run' +3 per run whose executor made something
    else than the plan's; 'action region takes a limb' +5 per region and plan that holds >= 5 % of
    a limb; 'loose piece copied or lost' +4 per loose shell and run (scored like a one-sided part);
    'quadruped skeleton off' +4 (a quadruped joint farther than 0.08 H from joints_hint, or not
    placed); an error in a new measurement +10. Reads the record only."""
    by = {k: 0.0 for k in NEW_LINES}
    why = []

    def add(line, v, text):
        by[line] += v
        why.append(f"[{line} +{v:g}] {text}")
    for e in rec.get("errors_new", []):
        add("error in a new measurement", 10, f"ERROR in {e['step']}: {e['error'][:120]}")
    dry, real = rec.get("dry", {}), rec.get("real", {})
    for side in sorted(set(dry) | set(real)):
        r = real.get(side) or dry.get(side)
        tag = f"[{side}{' real' if side in real else ''}]"
        u = r.get("unplanned_change") or {}
        if u.get("islands"):
            near = {}
            for g in u.get("lost", []) + u.get("added", []):
                for n, x in g["where"].items():
                    near[n] = max(near.get(n, 0.0), x)
            add("unplanned change", 8, f"{tag} {u['islands']} island(s) changed that no plan allowed: lost "
                                       f"{u['lost_cm2']:g} cm2, added {u['added_cm2']:g} cm2 (near "
                                       f"{', '.join(sorted(near, key=lambda n: (-near[n], n))[:3])})")
        pd = r.get("plan_drift") or {}
        if pd.get("drift"):
            add("plan fingerprint != run", 3, f"{tag} the run's executor made another mesh than the plan's "
                                              f"({pd.get('how', '')}" + (f": {pd['why']}" if pd.get("why") else "")
                + ")")
        lost, cop = r.get("lost", {}), r.get("copied", {})
        for n in sorted(set(lost) | set(cop)):
            if n.startswith("shell_loose_") and (lost.get(n, 0.0) > 0.05 or cop.get(n, 0.0) > 0.05):
                add("loose piece copied or lost", 4, f"{tag} {n}: lost {lost.get(n, 0.0):.0%}, "
                                                     f"copied over {cop.get(n, 0.0):.0%}")
    for side in sorted(rec.get("plan", {})):
        for g in rec["plan"][side].get("regions", []):
            big = {n: x for n, x in g["limb_share"].items() if x >= 0.05}
            if big:
                add("action region takes a limb", 5, f"[{side}] the {g['action']} region {g['name']} holds "
                    + ", ".join(f"{n} {x:.0%}" for n, x in sorted(big.items(), key=lambda t: (-t[1], t[0]))))
    H = rec.get("height") or rec.get("mesh", {}).get("height") or 0.0
    jq = rec.get("joint_errors_quad")
    if jq:
        bad = {j: e for j, e in jq.items() if e is None or e > 0.08 * H}
        if bad:
            add("quadruped skeleton off", 4, "quadruped skeleton off: " + ", ".join(
                f"{j} {'not placed' if e is None else f'by {e:.2f} m'}"
                for j, e in sorted(bad.items(), key=lambda t: (-(t[1] if t[1] is not None else 99), t[0]))[:5]))
    return round(sum(by.values()), 2), why, {k: round(v, 2) for k, v in by.items() if v}


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


RUN_FIELDS = ("cut", "refused", "why_not", "mirrored", "qr_symmetry", "cut_share", "lost", "copied")


def scored_fields(rec) -> dict:
    """The part of a record that score() and score_new() read, and nothing else: a stored record
    re-scores from this alone (tests keep one so the scoring cannot drift unnoticed)."""
    out = {k: rec[k] for k in ("errors", "errors_new", "truth", "parts", "height", "joint_errors",
                               "joint_errors_quad", "phantoms") if k in rec}
    out["mesh"] = {"height": rec["mesh"]["height"]}
    out["found"] = [{k: f[k] for k in ("name", "kind", "truth")} for f in rec.get("found", [])]
    for kind in ("dry", "real"):
        out[kind] = {}
        for side, r in rec.get(kind, {}).items():
            q = {k: r[k] for k in RUN_FIELDS if k in r}
            if r.get("unplanned_change"):
                u = r["unplanned_change"]
                q["unplanned_change"] = {k: u[k] for k in ("islands", "lost", "added", "lost_cm2", "added_cm2")}
            if r.get("plan_drift"):
                q["plan_drift"] = {k: r["plan_drift"][k] for k in ("drift", "how", "why") if k in r["plan_drift"]}
            out[kind][side] = q
    out["plan"] = {side: {k: p[k] for k in ("blocked", "regions") if k in p} for side, p in rec.get("plan", {}).items()}
    return out


def summary(rec) -> str:
    lines = [f"[{rec['body']}] score {rec['score']} {rec.get('score_by', '')}"
             + (f" | new lines {rec['score_new']} {rec.get('score_new_by', '')}" if "score_new" in rec else "")]
    lines += [f"    - {p}" for p in rec["problems"]]
    lines += [f"    * {p}" for p in rec.get("problems_new", [])]
    return "\n".join(lines)


def totals(bodies: dict) -> dict:
    """The three totals (see the module's doc): old total and new lines over the first zoo's
    records, zoo v2 (old and new lines) over the rest; with the categories and the line counts."""
    out = {}
    for group in ("v1", "v2"):
        recs = [r for k, r in sorted(bodies.items()) if r.get("zoo", "v1") == group]
        cat, new = {"step4": 0.0, "rig": 0.0, "detect": 0.0}, {}
        for r in recs:
            for c, v in r.get("score_by", {}).items():
                cat[c] = cat.get(c, 0.0) + v
            for c, v in r.get("score_new_by", {}).items():
                new[c] = new.get(c, 0.0) + v
        old = round(sum(r["score"] for r in recs), 2)
        nl = round(sum(r.get("score_new", 0.0) for r in recs), 2)
        out[group] = {"records": len(recs), "old_lines": old, "by": {c: round(v, 2) for c, v in cat.items()},
                      "new_lines": nl, "new_by": {c: round(v, 2) for c, v in sorted(new.items())}}
    out["old_total"] = out["v1"]["old_lines"]
    out["new_lines_total"] = out["v1"]["new_lines"]
    out["zoo_v2_total"] = round(out["v2"]["old_lines"] + out["v2"]["new_lines"], 2)
    # the plan's acceptance 'on +ain every symmetric body shows asymmetry > 0', read two ways:
    # the product's own measure (density.asymmetry) and this harness's mirror gap
    ain = [r for k, r in sorted(bodies.items()) if k.endswith("+ain") and r.get("parts")
           and all(v.get("symmetry") in ("pair", "centre") for v in r["parts"].values())]
    gaps = [float((r.get("symmetry", {}).get("mirror_gap") or {}).get("median_mm") or 0.0) for r in ain]
    out["ain_symmetric"] = {
        "bodies": len(ain),
        "asymmetry_above_0": sum(1 for r in ain if float(r.get("symmetry", {}).get("asymmetry") or 0.0) > 0),
        "mirror_gap_above_0": sum(1 for g in gaps if g > 0),
        "mirror_gap_median_mm": [round(min(gaps), 3), round(max(gaps), 3)] if gaps else None}
    return out


def _fmt_runs(rec, kind: str) -> list:
    out = []
    for side in sorted(rec.get(kind, {})):
        r = rec[kind][side]
        u, m, pd = r.get("unplanned_change") or {}, r.get("mirror_residual") or {}, r.get("plan_drift") or {}
        loose = {n: (r.get("lost", {}).get(n, 0.0), r.get("copied", {}).get(n, 0.0))
                 for n in sorted(set(r.get("lost", {})) | set(r.get("copied", {}))) if n.startswith("shell_loose_")}
        out.append(f"   {kind:4s} {side:5s} mirrored={r.get('mirrored')} qr={r.get('qr_symmetry')} cut={r.get('cut')} "
                   f"refused={[x[0] for x in r.get('refused', [])]} | unplanned: {u.get('islands', '-')} island(s) "
                   f"lost {u.get('lost_cm2', '-')} / added {u.get('added_cm2', '-')} cm2 "
                   f"(tau {u.get('tau_mm', '-')} mm: noise floor {u.get('noise_floor_mm', '-')}, resolution "
                   f"{u.get('resolution_mm', '-')}; product's {u.get('tau_product_mm', '-')}) | drift "
                   f"{pd.get('drift', '-')}{(' (' + pd['why'] + ')') if pd.get('why') else ''} | residual "
                   f"{m.get('median_mm', '-')} / p95 {m.get('p95_mm', '-')} mm"
                   + (f" | loose {loose}" if loose else "") + (f" | part scale {r['part_scale_mm']} mm" if r.get(
                       "part_scale_mm") else ""))
    return out


def write_summary(doc: dict, path: Path) -> str:
    """summary.txt: the totals, then per body its scores, the new columns per run and plan, and
    the problems (- old lines, * new lines)."""
    b = doc["bodies"]
    t = totals(b)
    v1, v2 = t["v1"], t["v2"]
    L = ["TOTALS",
         f"  old total (first zoo, {v1['records']} records): {v1['old_lines']:g} "
         f"(step4 {v1['by']['step4']:g} / rig {v1['by']['rig']:g} / detect {v1['by']['detect']:g})",
         f"  new lines on the same records (a column of their own, not in the old total): {v1['new_lines']:g} "
         f"{v1['new_by']}",
         f"  zoo v2 ({v2['records']} records: the new bodies and every +ain variant): {t['zoo_v2_total']:g} = "
         f"old lines {v2['old_lines']:g} (step4 {v2['by']['step4']:g} / rig {v2['by']['rig']:g} / detect "
         f"{v2['by']['detect']:g}) + new lines {v2['new_lines']:g} {v2['new_by']}"]
    a = t.get("ain_symmetric") or {}
    if a.get("bodies"):
        L.append(f"  +ain, {a['bodies']} bodies built symmetric: the product's asymmetry() > 0 on "
                 f"{a['asymmetry_above_0']} (acceptance 'asymmetry > 0' "
                 f"{'met' if a['asymmetry_above_0'] == a['bodies'] else 'NOT met'} for the product's measure), "
                 f"the harness's mirror gap > 0 on {a['mirror_gap_above_0']} (median {a['mirror_gap_median_mm']} mm)")
    L += ["",
          "HOW TO READ",
          "  unplanned change: label-free, original against result; tau = the body's noise floor (3 x its median "
          "mirror gap), never under a quarter of the coarser mesh's edge (logged per run). A change smaller than "
          "tau, or an island smaller than the smallest island, is not measured.",
          "  plan drift (fast): the plan's executor against a second run that decides the mirror as the product's "
          "run does (retopo's own helpers); an executor that does not repeat itself drifts too. Real: the plan's "
          "executor against what the real run made.", ""]
    for k in sorted(b, key=lambda k: (b[k].get("zoo", "v1"), b[k].get("generator", k), k)):
        r = b[k]
        sym = r.get("symmetry", {})
        L.append(f"== {k} [{r.get('zoo', 'v1')}]: {r['score']} {r.get('score_by', '')} | new {r.get('score_new', '-')} "
                 f"{r.get('score_new_by', '')} | asymmetry {sym.get('asymmetry')} mirror gap {sym.get('mirror_gap')} "
                 f"| QR auto {sym.get('qr_symmetry_auto')} ({sym.get('qr_symmetry_auto_from', '-')})")
        for side in sorted(r.get("plan", {})):
            p = r["plan"][side]
            regs = [f"{g['action']} {g['name']}: {g['limb_share'] or '-'} body {g['body_share']:.0%}"
                    for g in p.get("regions", [])]
            prot = p.get("protection", {})
            rows = p.get("rows", "-")
            L.append(f"   plan {side:5s} regions {regs or '-'} | rows {rows if isinstance(rows, str) else len(rows)}"
                     f" | recall {prot.get('recall', '-')} | false protection {prot.get('false', '-')} "
                     f"area {prot.get('false_area', '-')}")
        L += _fmt_runs(r, "dry") + _fmt_runs(r, "real")
        if r.get("joint_errors_quad"):
            L.append(f"   quadruped joints {r['joint_errors_quad']}")
        L += [f"     - {p}" for p in r.get("problems", [])]
        L += [f"     * {p}" for p in r.get("problems_new", [])]
    text = "\n".join(L) + "\n"
    path.write_text(text)
    return text


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--repo", default=str(HERE.parent), help="checkout whose product code is measured")
    ap.add_argument("--out", default=str(Path(tempfile.gettempdir()) / "zoo_baseline"))
    ap.add_argument("--side", default="left,right", help="mirror sides to plan and run (auto always runs)")
    ap.add_argument("--mode", default="fast", choices=("fast", "real", "both"))
    ap.add_argument("--ai", default="off", choices=tuple(VARIANTS),
                    help="surface variants: off (plain), on (+ai), ain (+ain: not its own mirror image), "
                         "both (plain and +ai), all (plain, +ai and +ain)")
    ap.add_argument("--zoo", default="v1", choices=("v1", "v2", "all"),
                    help="bodies: the first zoo (BODIES), the new ones (BODIES_V2) or both")
    ap.add_argument("--voxel", type=float, default=0.008)
    ap.add_argument("--budget", type=int, default=40000, help="triangles for the real run")
    ap.add_argument("--render", action="store_true")
    ap.add_argument("--rescore", action="store_true", help="only recompute the scores of the baseline.json in --out")
    ap.add_argument("--summary", action="store_true", help="only rewrite summary.txt from the baseline.json in --out")
    ap.add_argument("bodies", nargs="*")
    args = ap.parse_args(argv)
    args.sides = [s for s in args.side.split(",") if s in ("left", "right")]
    _setup(Path(args.repo).resolve())
    out = Path(args.out)
    if args.rescore or args.summary:
        doc = json.loads((out / "baseline.json").read_text())
        if args.rescore:
            for rec in doc["bodies"].values():
                if "parts" in rec:
                    rec["score"], rec["problems"], rec["score_by"] = score(rec)
                    rec["score_new"], rec["problems_new"], rec["score_new_by"] = score_new(rec)
                    print(summary(rec))
            doc["ranking"] = sorted(((k, r["score"]) for k, r in doc["bodies"].items()), key=lambda x: -x[1])
            doc["totals"] = totals(doc["bodies"])
            (out / "baseline.json").write_text(json.dumps(doc, indent=1, default=str))
            print("ranking:", doc["ranking"])
        print(write_summary(doc, out / "summary.txt").split("\n\n")[0])
        return
    out.mkdir(parents=True, exist_ok=True)
    pool = {"v1": BODIES, "v2": BODIES_V2, "all": BODIES + BODIES_V2}[args.zoo]
    todo = [b for b in pool if not args.bodies or b[0] in args.bodies]
    variants = VARIANTS[args.ai]
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
                rec = {"body": name, "zoo": "v2" if gen in Z.ZOO_V2 or suffix == "+ain" else "v1",
                       "errors": [{"step": "build", "error": f"{type(exc).__name__}: {exc}",
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
           "ranking": [(k, results[k]["score"]) for k in ranking], "totals": totals(results), "bodies": results}
    path.write_text(json.dumps(Z.info_json(doc), indent=1, default=str))
    print("ranking:", doc["ranking"])
    print(write_summary(doc, out / "summary.txt").split("\n\n")[0])
    print("written:", path, out / "summary.txt")


if __name__ == "__main__":
    main()
