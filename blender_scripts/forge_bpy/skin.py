"""Stage: transfer skin weights from the rigged AI mesh onto the clean low mesh,
enforce the engine's influence limit, and add prop sockets.

The skeleton comes from Tripo's rigging (spec unity / unreal). Because retopology
throws the original weights away, we copy them from the high mesh (which still
carries them) using nearest-face interpolation, then clean them up.
"""

from __future__ import annotations

import bpy
import numpy as np

from . import common as C

# bone-name fragments used to find socket parents on any common skeleton
SOCKET_PARENTS = {
    "hand_r": ["hand_r", "righthand", "hand.r", "r_hand", "right_hand"],
    "hand_l": ["hand_l", "lefthand", "hand.l", "l_hand", "left_hand"],
    "head": ["head"],
    "spine": ["spine_03", "spine2", "chest", "spine"],
    "pelvis": ["pelvis", "hips", "hip"],
}


def _find_bone(arm, key: str):
    names = {b.name.lower().replace(" ", "_"): b.name for b in arm.data.bones}
    for frag in SOCKET_PARENTS.get(key, [key]):
        for low, real in names.items():
            if low.endswith(frag) or low == frag:
                return real
    return None


def _transfer(low, high) -> None:
    for vg in high.vertex_groups:
        if vg.name not in low.vertex_groups:
            low.vertex_groups.new(name=vg.name)
    mod = low.modifiers.new("forge_wt", "DATA_TRANSFER")
    mod.object = high
    mod.use_vert_data = True
    mod.data_types_verts = {"VGROUP_WEIGHTS"}
    mod.vert_mapping = "POLYINTERP_NEAREST"
    mod.layers_vgroup_select_src = "ALL"
    mod.layers_vgroup_select_dst = "NAME"
    # data transfer must run before the armature deform
    C.select_only(low)
    bpy.ops.object.modifier_move_to_index(modifier=mod.name, index=0)
    bpy.ops.object.modifier_apply(modifier=mod.name)


def limit_influences(W, k: int, continuous: bool = True) -> np.ndarray:
    """At most k bones per point, each row summing to 1 (rows of W: one point's weights >= 0).

    continuous (the default): first subtract each row's (k+1)-th largest weight from all its
    weights and clamp at 0, then keep the k strongest. A hard cut (keep the k strongest) jumps
    wherever the k-th and (k+1)-th bones swap places between neighbouring points - one point
    keeps a 12 % bone, the next loses it - and the skin tears there when that bone moves;
    subtracting the (k+1)-th weight fades the weakest bones out smoothly instead. A row whose
    k strongest all equal the (k+1)-th (nothing would be left) falls back to the hard cut.
    Rows without any weight stay 0. The columns can be bones or just slots: zeros are ignored.
    This is the limit export_engine applies, so a check can measure exactly what ships."""
    W = np.asarray(W, np.float64)
    n, m = W.shape
    kept = np.zeros_like(W)
    if n == 0 or m == 0:
        return kept
    order = np.argsort(-W, axis=1, kind="stable")
    rows = np.arange(n)[:, None]
    top = order[:, :min(k, m)]
    kept[rows, top] = W[rows, top]
    if continuous and m > k:
        cut = W[np.arange(n), order[:, k]]
        soft = np.zeros_like(W)
        soft[rows, top] = np.maximum(W[rows, top] - cut[:, None], 0.0)
        ok = soft.sum(axis=1) > 1e-6 * np.maximum(kept.sum(axis=1), 1e-12)
        kept[ok] = soft[ok]
    s = kept.sum(axis=1, keepdims=True)
    return np.where(s > 0, kept / np.where(s > 0, s, 1.0), 0.0)


def engine_limit(W, k: int, min_weight: float = 0.01, continuous: bool = True) -> np.ndarray:
    """What an engine build does to weights (points x bones): tiny weights go, then
    limit_influences(k). export_engine and the bind use exactly this.

    continuous (the default): weights under min_weight go, and those up to twice it fade in
    (2 x (w - min_weight)); stronger ones are kept as they are. A hard cut keeps a 1.3 % bone on
    one point and drops a 0.9 % one on its neighbour: when that far bone moves (a thigh in a
    leg pose), the first point follows it a few millimetres and the skin between tears. Faded,
    they keep 0.6 % and 0. A row with nothing left keeps its weights (renormalised)."""
    W = np.asarray(W, np.float64)
    if not continuous:
        return limit_influences(np.where(W >= min_weight, W, 0.0), k, False)
    soft = np.where(W >= 2.0 * min_weight, W, np.maximum(2.0 * (W - min_weight), 0.0))
    gone = (soft.sum(axis=1) <= 1e-12) & (W.sum(axis=1) > 0)
    soft[gone] = W[gone]
    return limit_influences(soft, k, True)


def _cleanup_weights(low, max_influences: int, min_weight: float, deform_bones: set,
                     continuous: bool = True) -> int:
    """Per vertex: drop tiny + non-deform weights, keep at most N bones (engine_limit:
    continuous by default), normalise. Returns the number of vertices left without any
    weight (fixed by nearest neighbour)."""
    groups = {vg.index: vg for vg in low.vertex_groups}
    rows: list[list[tuple[int, float]]] = []
    for v in low.data.vertices:                  # (continuous: engine_limit fades the tiny ones)
        rows.append([(g.group, g.weight) for g in v.groups
                     if g.weight >= (1e-6 if continuous else min_weight) and groups[g.group].name in deform_bones])
    width = max((len(r) for r in rows), default=0)
    gi = np.full((len(rows), max(width, 1)), -1, np.int64)
    wt = np.zeros((len(rows), max(width, 1)))
    for i, r in enumerate(rows):
        for j, (g, w) in enumerate(r):
            gi[i, j], wt[i, j] = g, w
    wt = engine_limit(wt, max_influences, min_weight, continuous)
    new_weights: list[list[tuple[int, float]]] = [
        [(int(gi[i, j]), float(wt[i, j])) for j in np.flatnonzero(wt[i] > 0)] for i in range(len(rows))]

    # vertices that lost every weight copy their nearest weighted neighbour (by edge)
    adj: dict[int, list[int]] = {}
    for e in low.data.edges:
        a, b = e.vertices
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, []).append(a)
    missing = [i for i, ws in enumerate(new_weights) if not ws]
    for _ in range(64):
        if not missing:
            break
        still = []
        for i in missing:
            donor = next((n for n in adj.get(i, []) if new_weights[n]), None)
            if donor is None:
                still.append(i)
            else:
                new_weights[i] = list(new_weights[donor])
        if len(still) == len(missing):
            break
        missing = still

    for vg in low.vertex_groups:
        vg.remove(range(len(low.data.vertices)))
    for i, ws in enumerate(new_weights):
        for g, w in ws:
            groups[g].add([i], w, "REPLACE")
    used = {g for ws in new_weights for g, _ in ws}
    for g, vg in list(groups.items()):
        if g not in used:
            low.vertex_groups.remove(vg)
    return len(missing)


def weight_matrix(obj, names) -> tuple:
    """(bone names, W points x bones): the object's weights of the vertex groups in `names`."""
    cols = [vg for vg in obj.vertex_groups if vg.name in names]
    at = {vg.index: j for j, vg in enumerate(cols)}
    W = np.zeros((len(obj.data.vertices), len(cols)))
    for v in obj.data.vertices:
        for g in v.groups:
            j = at.get(g.group)
            if j is not None:
                W[v.index, j] = g.weight
    return [vg.name for vg in cols], W


def set_weights(obj, names: list, W, columns=None) -> None:
    """Write W (points x len(names)) back into the vertex groups `names` (created if missing).
    Only the given columns are rewritten (all by default)."""
    n = len(obj.data.vertices)
    for j in (range(len(names)) if columns is None else columns):
        vg = obj.vertex_groups.get(names[j]) or obj.vertex_groups.new(name=names[j])
        vg.remove(range(n))
        col = W[:, j]
        for i in np.flatnonzero(col > 1e-6):
            vg.add([int(i)], float(col[i]), "REPLACE")


def _ensure_armature_mod(low, arm) -> None:
    mod = next((m for m in low.modifiers if m.type == "ARMATURE"), None)
    if mod is None:
        mod = low.modifiers.new("Armature", "ARMATURE")
    mod.object = arm
    low.parent = arm
    low.matrix_parent_inverse = arm.matrix_world.inverted()


def _add_sockets(arm, sockets: dict) -> dict:
    """sockets: {"socket_name": "hand_r", ...} -> bone added under the matching bone."""
    added = {}
    if not sockets:
        return added
    C.select_only(arm)
    bpy.ops.object.mode_set(mode="EDIT")
    eb = arm.data.edit_bones
    for sock, parent_key in sockets.items():
        parent = _find_bone(arm, parent_key)
        if not parent or sock in eb:
            continue
        p = eb[parent]
        b = eb.new(sock)
        b.head = p.tail.copy()
        b.tail = p.tail + (p.tail - p.head).normalized() * max(p.length * 0.25, 0.01)
        b.roll = p.roll
        b.parent = p
        b.use_deform = False
        added[sock] = parent
    bpy.ops.object.mode_set(mode="OBJECT")
    return added


def run(args: dict) -> dict:
    """rig_method "auto_rig_pro": rebuild the skeleton with Auto-Rig Pro (humanoids); on any
    failure the scene is reloaded and the weight-transfer method below is used instead."""
    if args.get("rig_method") == "auto_rig_pro":
        from . import arp_rig
        from .addon_trial import has_op
        why = None
        if not has_op("arp.append_arp"):
            why = "Auto-Rig Pro not loaded"
        else:
            try:
                rep = arp_rig.build(args)
                return {"rig_system": "auto_rig_pro", "arp": rep, "parts": _weight_report(),
                        "sockets": rep.get("sockets", {}), "bones": rep["bones"]}
            except Exception as exc:
                import traceback
                print("[forge] Auto-Rig Pro path failed:")
                traceback.print_exc()
                why = f"{type(exc).__name__}: {exc}"[:400]
        # Do not save the half-built scene: the orchestrator reruns this stage with
        # rig_method "transfer" in a fresh Blender (reloading in-process is unsafe when windowed).
        args["save_blend"] = None
        return {"rig_system": "arp_failed", "arp_fallback_reason": why}
    res = _run_transfer(args)
    res["rig_system"] = "transfer"
    return res


def _weight_report() -> dict:
    out = {}
    for low in C.meshes_with_role("low"):
        unweighted = sum(1 for v in low.data.vertices if not any(g.weight > 1e-4 for g in v.groups))
        out[low.get(C.PART_PROP)] = {"vertex_groups": len(low.vertex_groups), "unweighted_verts": unweighted}
    return out


def _weights_source():
    """The rig file's meshes (role 'weights'), joined into one weight source."""
    ws = C.meshes_with_role("weights")
    if not ws:
        return None
    if len(ws) > 1:
        C.select_only(*ws, active=ws[0])
        bpy.ops.object.join()
    src = C.meshes_with_role("weights")[0]
    src.hide_set(False)
    return src


def _run_transfer(args: dict) -> dict:
    arm = C.find_armature()
    if arm is None:
        return {"skipped": "no armature in source model"}
    weights_src = _weights_source()
    max_inf = int(args.get("max_influences", 4))
    min_w = float(args.get("min_weight", 0.01))
    rigid_parts = set(args.get("rigid_parts", []))   # props: weld 100% to one bone instead

    report = {}
    for low in C.meshes_with_role("low"):
        part = low.get(C.PART_PROP)
        high = C.high_for(low)
        if (high is None or not high.vertex_groups) and weights_src is not None:
            high = weights_src            # skeleton came from a separate rigged file
        if part in rigid_parts:
            report[part] = {"rigid": True}
            continue
        if high is None or not high.vertex_groups:
            report[part] = {"skipped": "high mesh has no weights"}
            continue
        _transfer(low, high)
        deform = {b.name for b in arm.data.bones if b.use_deform}
        orphans = _cleanup_weights(low, max_inf, min_w, deform)
        _ensure_armature_mod(low, arm)
        report[part] = {"vertex_groups": len(low.vertex_groups), "unweighted_verts": orphans}

    sockets = _add_sockets(arm, args.get("sockets", {}))
    return {"parts": report, "sockets": sockets, "bones": len(arm.data.bones)}
