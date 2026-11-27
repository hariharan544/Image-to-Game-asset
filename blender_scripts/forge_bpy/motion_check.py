"""Automatic checks while a sample clip plays on the rig (Step 8).

"Watch for tearing" becomes a pass / warn / fail with the worst frame named:

  joints     where two bones share the skin (elbow, knee, shoulder, wrist) the skin keeps
             its distance from the bones; a collapsing joint pulls it in towards them (the
             linear-blend "candy wrapper" and the pinched inner elbow). Worst 5 % of each
             joint's points, posed distance / rest distance
  skin       how far an edge stretches or squashes against its rest length (texture smear)
  crossing   faces passing through other faces that did not touch at rest (a knee into the
             belly, a prop into the chest); parts that already overlap at rest - a tail root
             plugged into the body - are not counted
  weights    points no bone moves, and points more bones move than the engines take
             (Unity 4, Unreal 8)

Everything is measured on the evaluated (posed) meshes, frame by frame, in world space.
"""

from __future__ import annotations

import numpy as np

import bpy

LIMITS = {
    "volume": (0.7, 0.5),          # (warn below, fail below) joint thickness, posed / rest
    "stretch": (1.5, 2.0),         # (warn above, fail above) edge length / rest: texture smear
    "squash": (0.3, -1.0),         # (warn below, never fails) inner bends squash in real skin too
    "crossing": (0.0, 0.01),       # (warn above, fail above) share of faces newly crossing
}
ENGINE_INFLUENCES = {"Unity": 4, "Unreal": 8}
MIN_JOINT_POINTS = 8               # fewer shared points than this: not a joint to judge
BLEND = 0.1                        # a point is in a joint when its 2nd bone moves it this much


def _world_co(me, mw) -> np.ndarray:
    co = np.empty(len(me.vertices) * 3, np.float64)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    m = np.array(mw, np.float64)
    return co @ m[:3, :3].T + m[:3, 3]


def _tris(me) -> np.ndarray:
    me.calc_loop_triangles()
    t = np.empty(len(me.loop_triangles) * 3, np.int64)
    me.loop_triangles.foreach_get("vertices", t)
    return t.reshape(-1, 3)


def _edges(me) -> np.ndarray:
    e = np.empty(len(me.edges) * 2, np.int64)
    me.edges.foreach_get("vertices", e)
    return e.reshape(-1, 2)


def _top_two(obj, deform: set):
    """The two bones that move each point most: (bone names, index of 1st, index of 2nd,
    weight of 2nd); index -1 = none."""
    names = {g.index: g.name for g in obj.vertex_groups}
    bones: list = []
    at: dict = {}
    n = len(obj.data.vertices)
    b1 = np.full(n, -1, np.int64)
    b2 = np.full(n, -1, np.int64)
    w2 = np.zeros(n)
    for v in obj.data.vertices:
        ws = sorted(((g.weight, names.get(g.group)) for g in v.groups
                     if g.weight > 1e-4 and names.get(g.group) in deform), reverse=True)
        for slot, (w, name) in enumerate(ws[:2]):
            if name not in at:
                at[name] = len(bones)
                bones.append(name)
            if slot == 0:
                b1[v.index] = at[name]
            else:
                b2[v.index], w2[v.index] = at[name], w
    return bones, b1, b2, w2


def _segments(arm, bones: list, posed: bool):
    mw = arm.matrix_world
    h = np.empty((len(bones), 3))
    t = np.empty((len(bones), 3))
    for i, name in enumerate(bones):
        if posed:
            pb = arm.pose.bones[name]
            h[i], t[i] = (mw @ pb.head)[:], (mw @ pb.tail)[:]
        else:
            b = arm.data.bones[name]
            h[i], t[i] = (mw @ b.head_local)[:], (mw @ b.tail_local)[:]
    return h, t


def _to_segment(p, a, b) -> np.ndarray:
    ab = b - a
    t = np.clip(np.einsum("ij,ij->i", p - a, ab) / np.maximum(np.einsum("ij,ij->i", ab, ab), 1e-12), 0, 1)
    return np.linalg.norm(p - (a + ab * t[:, None]), axis=1)


def _bone_distance(co, idx1, idx2, h, t) -> np.ndarray:
    return np.minimum(_to_segment(co, h[idx1], t[idx1]), _to_segment(co, h[idx2], t[idx2]))


def crossing_faces(co, tris, shrink: float = 0.98) -> set:
    """Triangles passing through another triangle. Each triangle is shrunk a little towards
    its centre first, so neighbours sharing an edge or a corner no longer touch: whatever
    still overlaps really crosses."""
    from mathutils.bvhtree import BVHTree
    if not len(tris):
        return set()
    c = co[tris].mean(axis=1, keepdims=True)
    pts = (c + (co[tris] - c) * shrink).reshape(-1, 3)
    polys = np.arange(len(pts)).reshape(-1, 3)
    tree = BVHTree.FromPolygons(pts.tolist(), polys.tolist(), all_triangles=True)
    pairs = tree.overlap(tree)
    out = set()
    for i, j in pairs:
        if i != j:
            out.add(i)
            out.add(j)
    return out


class _Mesh:
    """One skinned mesh: its rest state and what to compare each frame against."""

    def __init__(self, obj, arm, deform: set, offset: int, dg=None):
        self.obj, self.offset = obj, offset
        me = obj.data
        rest = self.posed(dg) if dg is not None else None      # (the rig in its rest pose)
        self.rest = rest if rest is not None else _world_co(me, obj.matrix_world)
        self.tris = _tris(me)
        self.edges = _edges(me)
        self.rest_len = np.linalg.norm(self.rest[self.edges[:, 0]] - self.rest[self.edges[:, 1]], axis=1)
        bones, b1, b2, w2 = _top_two(obj, deform)
        self.bones = [b for b in bones if b in arm.data.bones]
        known = {b: i for i, b in enumerate(self.bones)}
        remap = np.array([known.get(b, -1) for b in bones] + [-1], np.int64)
        b1, b2 = remap[b1], remap[b2]
        self.region = b1                                   # (the bone that moves it most)
        # the joints: points shared by two bones, grouped by the pair
        shared = (b1 >= 0) & (b2 >= 0) & (w2 >= BLEND)
        idx = np.flatnonzero(shared)
        pair = np.sort(np.stack([b1[idx], b2[idx]], axis=1), axis=1)
        keys, joint = np.unique(pair, axis=0, return_inverse=True) if len(idx) else (np.zeros((0, 2)), idx)
        self.j_idx, self.j_b1, self.j_b2 = idx, b1[idx], b2[idx]
        self.joint = joint.ravel()
        self.j_name = []
        for a, b in keys.astype(int):
            na, nb = self.bones[a], self.bones[b]
            pa = arm.data.bones[na].parent
            self.j_name.append(na if pa is not None and pa.name == nb else nb)   # named by the child
        h, t = _segments(arm, self.bones, False) if self.bones else (np.zeros((0, 3)),) * 2
        self.j_rest = (_bone_distance(self.rest[idx], self.j_b1, self.j_b2, h, t)
                       if len(idx) else np.zeros(0))
        # a point lying on its bone (a thin flap) only adds noise to a ratio
        self.j_use = np.zeros(len(idx), bool)
        for j in range(len(self.j_name)):
            m = self.joint == j
            if m.sum() >= MIN_JOINT_POINTS:
                self.j_use[m] = self.j_rest[m] >= 0.25 * np.median(self.j_rest[m])

    def joint_thickness(self, co, arm) -> dict:
        """{joint name: 5th percentile of posed / rest distance from the bones}."""
        if not len(self.j_idx):
            return {}
        h, t = _segments(arm, self.bones, True)
        now = _bone_distance(co[self.j_idx], self.j_b1, self.j_b2, h, t)
        ratio = now / np.maximum(self.j_rest, 1e-9)
        out = {}
        for j, name in enumerate(self.j_name):
            m = (self.joint == j) & self.j_use
            if m.sum() >= MIN_JOINT_POINTS:
                out[name] = min(out.get(name, 9.0), float(np.percentile(ratio[m], 5)))
        return out

    def posed(self, dg) -> np.ndarray | None:
        ev = self.obj.evaluated_get(dg)
        me = ev.to_mesh()
        try:
            if len(me.vertices) != len(self.obj.data.vertices):
                return None                       # (a modifier changed the mesh: not comparable)
            return _world_co(me, ev.matrix_world)
        finally:
            ev.to_mesh_clear()


def weights(objs, deform: set) -> dict:
    """Points no bone moves, and points moved by more bones than each engine takes."""
    n = unweighted = 0
    over = {k: 0 for k in ENGINE_INFLUENCES}
    for o in objs:
        names = {g.index: g.name for g in o.vertex_groups}
        for v in o.data.vertices:
            k = sum(1 for g in v.groups if g.weight > 1e-4 and names.get(g.group) in deform)
            n += 1
            if k == 0:
                unweighted += 1
            for eng, lim in ENGINE_INFLUENCES.items():
                if k > lim:
                    over[eng] += 1
    return {"points": n, "unweighted": unweighted, "over": over}


def _grade(value: float, warn: float, fail: float, below: bool) -> str:
    if (value < fail) if below else (value > fail):
        return "fail"
    if (value < warn) if below else (value > warn):
        return "warn"
    return "pass"


def _nice(bone: str) -> str:
    """'forearm_stretch.l' -> 'left forearm' (for the panel)."""
    side = {"l": "left ", "r": "right ", "x": ""}
    base, _, s = bone.rpartition(".")
    if not base:
        base, s = bone, ""
    for junk in ("c_", "_stretch", "_twist", "_ref", "_def", "DEF-", "_fk", "_ik"):
        base = base.replace(junk, "")
    return (side.get(s.lower(), "") + base.replace("_", " ")).strip()


def check(arm, objs, frames: list):
    """Generator: step through `frames` of the armature's current action, measure, and return
    the report. Yields the share done (0..1) between frames."""
    sc = bpy.context.scene
    deform = {b.name for b in arm.data.bones if b.use_deform}
    meshes, off = [], 0
    pose_position = arm.data.pose_position
    arm.data.pose_position = "REST"                  # rest = the rig in its rest pose (props
    bpy.context.view_layer.update()                  # pinned to a bone included)
    try:
        dg = bpy.context.evaluated_depsgraph_get()
        for o in objs:
            m = _Mesh(o, arm, deform, off, dg)
            meshes.append(m)
            off += len(m.rest)
    finally:
        arm.data.pose_position = pose_position
        bpy.context.view_layer.update()
    all_tris = np.concatenate([m.tris + m.offset for m in meshes]) if meshes else np.zeros((0, 3), np.int64)
    rest_all = np.concatenate([m.rest for m in meshes]) if meshes else np.zeros((0, 3))
    at_rest = crossing_faces(rest_all, all_tris)
    keep_frame = sc.frame_current
    worst = {"volume": (1.0, None, ""), "stretch": (1.0, None, ""), "squash": (1.0, None, ""),
             "crossing": (0, None, "")}
    per_frame = []
    try:
        for i, f in enumerate(frames):
            sc.frame_set(f)
            dg = bpy.context.evaluated_depsgraph_get()
            posed_all = []
            row = {"frame": f}
            for m in meshes:
                co = m.posed(dg)
                if co is None:
                    co = m.rest
                posed_all.append(co)
                for name, ratio in m.joint_thickness(co, arm).items():
                    if ratio < worst["volume"][0]:
                        worst["volume"] = (ratio, f, name)
                    row["volume"] = min(row.get("volume", 1.0), ratio)
                ln = np.linalg.norm(co[m.edges[:, 0]] - co[m.edges[:, 1]], axis=1)
                ok = m.rest_len > 1e-9
                ratio = ln[ok] / m.rest_len[ok]
                if len(ratio):
                    hi, lo = int(np.argmax(ratio)), int(np.argmin(ratio))
                    e_ok = m.edges[ok]
                    if ratio[hi] > worst["stretch"][0]:
                        g = m.region[e_ok[hi, 0]]
                        worst["stretch"] = (float(ratio[hi]), f, m.bones[g] if g >= 0 else "")
                    if ratio[lo] < worst["squash"][0]:
                        g = m.region[e_ok[lo, 0]]
                        worst["squash"] = (float(ratio[lo]), f, m.bones[g] if g >= 0 else "")
                    row["stretch"] = max(row.get("stretch", 1.0), float(ratio[hi]))
            now = crossing_faces(np.concatenate(posed_all), all_tris) if posed_all else set()
            new = len(now - at_rest)
            row["crossing"] = new
            if new > worst["crossing"][0]:
                worst["crossing"] = (new, f, "")
            per_frame.append(row)
            yield (i + 1) / max(len(frames), 1)
    finally:
        sc.frame_set(keep_frame)
    n_tris = max(len(all_tris), 1)
    out = {"frames": len(frames), "checks": {}}
    v, vf, vb = worst["volume"]
    out["checks"]["joints"] = {"grade": _grade(v, *LIMITS["volume"], below=True), "value": round(v, 3),
                               "frame": vf, "where": _nice(vb)}
    s, sf, sb = worst["stretch"]
    q, qf, qb = worst["squash"]
    g1, g2 = _grade(s, *LIMITS["stretch"], below=False), _grade(q, *LIMITS["squash"], below=True)
    order = ("pass", "warn", "fail")
    out["checks"]["skin"] = {"grade": max(g1, g2, key=order.index), "stretch": round(s, 2), "frame": sf,
                             "where": _nice(sb), "squash": round(q, 2), "squash_frame": qf,
                             "squash_where": _nice(qb)}
    c, cf, _ = worst["crossing"]
    out["checks"]["crossing"] = {"grade": _grade(c / n_tris, *LIMITS["crossing"], below=False),
                                 "value": int(c), "frame": cf, "at_rest": len(at_rest)}
    skinned = [o for o in objs if any(md.type == "ARMATURE" and md.object is arm for md in o.modifiers)]
    w = weights(skinned, deform)                     # (a prop pinned to a bone has no weights)
    wg = "fail" if w["unweighted"] else ("warn" if w["over"]["Unity"] else "pass")
    out["checks"]["weights"] = {"grade": wg, **w}
    out["grade"] = max((x["grade"] for x in out["checks"].values()), key=order.index)
    bad = [x for x in out["checks"].values() if x.get("frame") is not None and x["grade"] != "pass"]
    worst_check = max(bad, key=lambda x: order.index(x["grade"]), default=None)
    out["worst_frame"] = worst_check["frame"] if worst_check else None
    out["per_frame"] = per_frame
    return out
