"""Auto-Rig Pro rigging: rebuild the AI (Tripo) skeleton as a production ARP rig.

Measured on the user's PC (Blender 5.3, ARP 3.79.17):
  arp.append_arp(rig_preset="human")   -> armature "rig" with 65 *_ref bones
  arp.match_to_rig()  (rig active, EDIT mode) -> final rig, 67 deform bones
  arp.bind_to_rig()   (meshes selected, rig active) -> skinned
  arp.arp_export_fbx_panel(filepath)   -> engine FBX; Unreal HUMANOID + mannequin axes
                                          gives UE5 Mannequin names, Unity HUMANOID 59 bones

Flow here:
  1. find the source joints (UE Mannequin, Mixamo or generic names) on the Tripo armature
  2. append ARP's human preset, move every reference bone onto those joints
  3. match_to_rig, bind the body parts, weld detachable props rigidly to their socket bone
  4. remove the source armature
Pure-geometry helpers (joint finding, reference targets) are separate so they are testable
without Auto-Rig Pro.
"""

from __future__ import annotations

import re

import bpy
from mathutils import Vector

from . import arp_limb_options as LO
from . import common as C

SIDES = {"l": ("l", "left"), "r": ("r", "right")}

# base names per joint: UE Mannequin / Mixamo / common DCC names (compared normalised)
LIMBS = {
    "clavicle": ("clavicle", "shoulder", "collar"),
    "upperarm": ("upperarm", "arm", "uparm"),
    "lowerarm": ("lowerarm", "forearm", "elbow"),
    "hand": ("hand", "wrist"),
    "thigh": ("thigh", "upleg", "upperleg"),
    "calf": ("calf", "leg", "lowerleg", "shin", "knee"),
    "foot": ("foot", "ankle"),
    "ball": ("ball", "toebase", "toe", "toes"),
}
FINGERS = ("thumb", "index", "middle", "ring", "pinky")
CENTER = {
    "pelvis": ("pelvis", "hips", "hip"),
    "neck": ("neck01", "neck", "neck1"),
    "head": ("head",),
}
ARP_SOCKET_BONES = {"hand_r": "hand.r", "hand_l": "hand.l", "head": "head.x",
                    "spine": "spine_02.x", "pelvis": "root.x"}


def norm(name: str) -> str:
    n = name.lower().replace("mixamorig", "")
    if "|" in n:
        n = n.split("|")[-1]
    if ":" in n:
        n = n.split(":")[-1]
    return re.sub(r"[^a-z0-9]", "", n)


def _side_aliases(base: str, s: str) -> list[str]:
    short, full = SIDES[s]
    return [f"{base}{short}", f"{short}{base}", f"{full}{base}", f"{base}{full}"]


def find_joints(arm) -> dict:
    """Return {joint_key: (head Vector, tail Vector)} in world space for the joints found."""
    mw = arm.matrix_world
    bones = {norm(b.name): b for b in arm.data.bones}
    out: dict = {}

    def put(key, bone):
        out[key] = (mw @ bone.head_local, mw @ bone.tail_local)

    for key, aliases in CENTER.items():
        for a in aliases:
            if a in bones:
                put(key, bones[a])
                break
    for s in SIDES:
        for key, bases in LIMBS.items():
            for base in bases:
                hit = next((bones[a] for a in _side_aliases(base, s) if a in bones), None)
                if hit:
                    put(f"{key}_{s}", hit)
                    break
        short, full = SIDES[s]
        for f in FINGERS:
            for i in (1, 2, 3):
                cands = [f"{f}0{i}{short}", f"{f}{i}{short}", f"{full}hand{f}{i}", f"{short}{f}{i}",
                         f"{f}0{i}{full}"]
                hit = next((bones[a] for a in cands if a in bones), None)
                if hit:
                    put(f"{f}{i}_{s}", hit)
            meta = next((bones[a] for a in (f"{f}metacarpal{short}", f"{f}metacarpal{full}")
                         if a in bones), None)
            if meta:
                put(f"{f}0_{s}", meta)
    # spine chain: bones between pelvis and neck along the parent chain
    neck = next((bones[a] for a in CENTER["neck"] if a in bones), None)
    pelvis = next((bones[a] for a in CENTER["pelvis"] if a in bones), None)
    chain = []
    b = neck.parent if neck else None
    while b is not None and b != pelvis:
        chain.append(b)
        b = b.parent
    chain.reverse()
    out["_spine"] = [(mw @ x.head_local, mw @ x.tail_local) for x in chain]
    return out


REQUIRED = ["pelvis", "neck", "head", "upperarm_l", "lowerarm_l", "hand_l", "upperarm_r", "lowerarm_r",
            "hand_r", "thigh_l", "calf_l", "foot_l", "thigh_r", "calf_r", "foot_r"]


def missing_joints(j: dict) -> list[str]:
    return [k for k in REQUIRED if k not in j]


def ref_targets(j: dict, ground_z: float, top_z: float) -> dict:
    """{arp_ref_bone: (head, tail)} from source joints. Only bones we can place are returned;
    ARP keeps its default placement (scaled) for the rest."""
    t: dict = {}
    H = lambda k: j[k][0].copy()      # noqa: E731
    T = lambda k: j[k][1].copy()      # noqa: E731
    pelvis, neck, head = H("pelvis"), H("neck"), H("head")
    spine = j.get("_spine") or []
    spine_start = spine[0][0] if spine else pelvis + (neck - pelvis) * 0.15
    mid = spine[len(spine) // 2][0] if len(spine) >= 2 else spine_start.lerp(neck, 0.5)
    t["root_ref.x"] = (pelvis, spine_start if (spine_start - pelvis).length > 1e-4 else pelvis.lerp(neck, 0.1))
    t["spine_01_ref.x"] = (t["root_ref.x"][1], mid)
    t["spine_02_ref.x"] = (mid, neck)
    t["neck_ref.x"] = (neck, head)
    t["head_ref.x"] = (head, Vector((head.x, head.y, max(top_z, head.z + (head - neck).length))))
    if j.get("_skull_base") is not None:
        # the head pivots at the base of the skull, not inside it: the head bone starts there and
        # the neck bone runs below it; root, spine_01 and the spine's middle stay where they are
        skull = Vector(j["_skull_base"])
        sh_z = 0.5 * (j["upperarm_l"][0].z + j["upperarm_r"][0].z) if "upperarm_l" in j and "upperarm_r" in j \
            else neck.z
        n0 = Vector((skull.x, skull.y, max(0.5 * (sh_z + skull.z), mid.z + 0.02 * (top_z - ground_z))))
        if n0.z < skull.z - 1e-4:
            t["spine_02_ref.x"] = (mid, n0)
            t["neck_ref.x"] = (n0, skull)
            t["head_ref.x"] = (skull, Vector((skull.x, skull.y, max(top_z, skull.z + (skull - n0).length))))
    for s in ("l", "r"):
        x = f".{s}"
        if f"clavicle_{s}" in j:
            t["shoulder_ref" + x] = (H(f"clavicle_{s}"), H(f"upperarm_{s}"))
        t["arm_ref" + x] = (H(f"upperarm_{s}"), H(f"lowerarm_{s}"))
        t["forearm_ref" + x] = (H(f"lowerarm_{s}"), H(f"hand_{s}"))
        hand_tail = H(f"middle1_{s}") if f"middle1_{s}" in j else T(f"hand_{s}")
        t["hand_ref" + x] = (H(f"hand_{s}"), hand_tail)
        t["thigh_ref" + x] = (H(f"thigh_{s}"), H(f"calf_{s}"))
        t["leg_ref" + x] = (H(f"calf_{s}"), H(f"foot_{s}"))
        foot = H(f"foot_{s}")
        ball = H(f"ball_{s}") if f"ball_{s}" in j else T(f"foot_{s}")
        toe_tip = T(f"ball_{s}") if f"ball_{s}" in j else ball + (ball - foot) * 0.5
        t["foot_ref" + x] = (foot, ball)
        t["toes_ref" + x] = (ball, toe_tip)
        fwd = Vector((ball.x - foot.x, ball.y - foot.y, 0.0))
        flen = max(fwd.length, 0.05)
        fwd = fwd.normalized() if fwd.length > 1e-6 else Vector((0, -1, 0))
        side = fwd.cross(Vector((0, 0, 1))).normalized()
        g = lambda v: Vector((v.x, v.y, ground_z))   # noqa: E731
        heel = g(foot) - fwd * flen * 0.35
        t["foot_heel_ref" + x] = (heel, heel + fwd * flen * 0.15)
        w = flen * 0.35
        t["foot_bank_01_ref" + x] = (g(ball) + side * w, g(ball) + side * w + fwd * flen * 0.1)
        t["foot_bank_02_ref" + x] = (g(ball) - side * w, g(ball) - side * w + fwd * flen * 0.1)
        for f in FINGERS:
            keys = [f"{f}{i}_{s}" for i in (1, 2, 3)]
            if not all(k in j for k in keys):
                continue
            t[f"{f}1_ref{x}"] = (H(keys[0]), H(keys[1]))
            t[f"{f}2_ref{x}"] = (H(keys[1]), H(keys[2]))
            t[f"{f}3_ref{x}"] = (H(keys[2]), T(keys[2]))
            if f != "thumb":
                base = H(f"{f}0_{s}") if f"{f}0_{s}" in j else H(f"hand_{s}").lerp(H(keys[0]), 0.35)
                t[f"{f}1_base_ref{x}"] = (base, H(keys[0]))
    return t


# ----------------------------------------------------------------------------- ARP calls

def _ov():
    from .addon_trial import view3d_override
    return view3d_override()


def _place_refs(rig, targets: dict) -> dict:
    """Move ARP reference bones (EDIT mode). Bones are set parents-first; connected children
    follow their parent's tail, so each bone gets head and tail explicitly."""
    C.select_only(rig)
    bpy.ops.object.mode_set(mode="EDIT")
    eb = rig.data.edit_bones
    inv = rig.matrix_world.inverted()
    placed, skipped = [], []
    order = sorted(targets, key=lambda n: len(eb[n].parent_recursive) if n in eb else 0)
    connected = {n: eb[n].use_connect for n in order if n in eb}
    for name in order:
        b = eb.get(name)
        if b is None:
            skipped.append(name)
            continue
        head, tail = targets[name]
        if (tail - head).length < 1e-4:
            tail = head + Vector((0, 0, 0.01))
        b.use_connect = False
        b.head = inv @ head
        b.tail = inv @ tail
        placed.append(name)
    # re-join ARP's chains (elbow = one point): ref_targets puts each child's head on its
    # parent's tail, so this moves nothing - but dragging a joint now moves both bones
    for name, was in connected.items():
        if was and eb[name].parent is not None:
            eb[name].use_connect = True
    return {"placed": len(placed), "missing_in_arp": skipped}


def place(joints: dict, lows: list, args: dict):
    """Append Auto-Rig Pro's reference rig and move its bones onto `joints`.
    Returns (ref_rig, report). The director may adjust the reference bones afterwards."""
    miss = missing_joints(joints)
    if miss:
        raise RuntimeError(f"joints missing: {miss}")
    ground = min((o.matrix_world @ Vector(c)).z for o in lows for c in o.bound_box)
    top = max((o.matrix_world @ Vector(c)).z for o in lows for c in o.bound_box)
    targets = ref_targets(joints, ground, top)
    C.ensure_object_mode()
    before = {o.name for o in bpy.data.objects}
    bpy.context.scene.cursor.location = (0, 0, 0)
    with bpy.context.temp_override(**_ov()):
        bpy.ops.arp.append_arp(rig_preset=args.get("arp_preset", "human"))
    new_arms = [o for o in bpy.data.objects if o.name not in before and o.type == "ARMATURE"]
    rig = next((o for o in new_arms if any(b.name.endswith("_ref.x") for b in o.data.bones)), None)
    if rig is None:
        raise RuntimeError(f"ARP append produced no reference rig ({[o.name for o in new_arms]})")
    rig.location = (0, 0, 0)
    for o in bpy.data.objects:
        if o.name not in before and o != rig:
            o["forge_arp_helper"] = True
    report = {"source_joints": sorted(k for k in joints if not k.startswith("_")),
              "spine_bones": len(joints.get("_spine", []))}
    report.update(_place_refs(rig, targets))
    bpy.ops.object.mode_set(mode="OBJECT")
    return rig, report


def nearest_bone(rig, point: Vector, deform_only: bool = True) -> str:
    """Name of the (deform) bone whose segment is closest to `point` (world space)."""
    from mathutils.geometry import intersect_point_line
    inv = rig.matrix_world.inverted()
    p = inv @ point
    best, best_d = None, float("inf")
    for b in rig.data.bones:
        if deform_only and not b.use_deform:
            continue
        q, t = intersect_point_line(p, b.head_local, b.tail_local)
        q = b.head_local if t < 0 else (b.tail_local if t > 1 else q)
        d = (p - q).length
        if d < best_d:
            best, best_d = b.name, d
    return best


def finish(rig, body: list, props: list, args: dict) -> dict:
    """match_to_rig, bind the body (heat map), weld each prop 100% to one bone."""
    report: dict = {}
    C.select_only(rig)
    bpy.ops.object.mode_set(mode="EDIT")
    try:                                # the joints may have moved since they were placed
        hung = hang_chains(rig)
    except Exception as exc:            # noqa: BLE001
        hung = {"error": str(exc)}
    with bpy.context.temp_override(**_ov()):
        bpy.ops.arp.match_to_rig()
    bpy.ops.object.mode_set(mode="OBJECT")
    rig = bpy.data.objects.get(rig.name)
    rig[C.ROLE_PROP] = "rig"
    rig["forge_arp"] = True
    try:
        report["chain_parents"] = chain_parents(rig, hung)
    except Exception as exc:            # noqa: BLE001
        report["chain_parents"] = {"error": str(exc)}
    for o in body + props:              # drop any older binding
        for m in [m for m in o.modifiers if m.type == "ARMATURE"]:
            o.modifiers.remove(m)
        mw = o.matrix_world.copy()
        o.parent = None
        o.matrix_world = mw
        o.vertex_groups.clear()
    sc = bpy.context.scene
    engine = args.get("bind_engine", "HEAT_MAP")
    if hasattr(sc, "arp_bind_engine"):
        sc.arp_bind_engine = engine
    if hasattr(sc, "arp_bind_preserve"):  # ARP's default is on; engines blend linearly
        sc.arp_bind_preserve = False
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    for o in body:
        o.hide_set(False)
        o.select_set(True)
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    with bpy.context.temp_override(**_ov()):
        bpy.ops.arp.bind_to_rig()
    report["bind_engine"] = engine
    report["skinning"] = linear_blend(rig, body)
    # appendage bones leak weight onto the body under bone heat: hand it to their parent bone
    report["appendages"] = {}
    for o in body:
        try:
            report["appendages"].update(settle_appendages(o, rig))
        except Exception as exc:        # noqa: BLE001
            report["appendages"][str(o.get(C.PART_PROP))] = {"error": str(exc)}
        stray = [c for c in str(o.get(STRAY_PROP, "") or "").split(",") if c]
        if stray:                       # a chain no part was found for moves no skin
            try:
                report.setdefault("stray_chains", {}).update(still_chains(o, rig, stray))
            except Exception as exc:    # noqa: BLE001
                report.setdefault("stray_chains", {})["error"] = str(exc)
    # ARP's binding does not respect the engine's influence limit nor normalise: do it here
    from .skin import _cleanup_weights
    deform = {b.name for b in rig.data.bones if b.use_deform}
    max_inf = int(args.get("max_influences", 4))
    min_w = float(args.get("min_weight", 0.01))
    report["weight_cleanup"] = {o.get(C.PART_PROP): _cleanup_weights(o, max_inf, min_w, deform, continuous=True)
                                for o in body}
    report["body_vertex_groups"] = {o.get(C.PART_PROP): len(o.vertex_groups) for o in body}

    # props: 100% to one bone - the named socket bone, else the nearest deform bone
    sockets = args.get("sockets", {})
    report["props"] = {}
    for p in props:
        part = p.get(C.PART_PROP)
        key = next((v for k, v in sockets.items() if part.lower() in k.lower()), None)
        bone = ARP_SOCKET_BONES.get(key) if key else None
        if not bone or bone not in rig.data.bones:
            lo = p.matrix_world @ Vector(p.bound_box[0])
            hi = p.matrix_world @ Vector(p.bound_box[6])
            bone = nearest_bone(rig, (lo + hi) / 2) or "hand.r"
        vg = p.vertex_groups.new(name=bone)
        vg.add(list(range(len(p.data.vertices))), 1.0, "REPLACE")
        m = p.modifiers.new("Armature", "ARMATURE")
        m.object = rig
        m.use_deform_preserve_volume = False
        p.parent = rig
        p.matrix_parent_inverse = rig.matrix_world.inverted()
        report["props"][part] = bone
    report["sockets"] = {k: ARP_SOCKET_BONES.get(v, v) for k, v in sockets.items()}
    report["rig"] = rig.name
    report["bones"] = len(rig.data.bones)
    report["deform_bones"] = sum(1 for b in rig.data.bones if b.use_deform)
    return report


def linear_blend(rig, objs: list) -> dict:
    """Engines blend bones linearly (LBS); Blender's Preserve Volume (dual quaternions) bends
    differently, so the viewport and the checks would not show what ships. Turn it off on every
    Armature modifier the rig drives and report what Auto-Rig Pro's bind had set."""
    found = []
    for o in objs:
        for m in o.modifiers:
            if m.type == "ARMATURE" and m.object == rig:
                if m.use_deform_preserve_volume:
                    found.append(o.name)
                m.use_deform_preserve_volume = False
    return {"preserve_volume_found": bool(found), "preserve_volume_on": found, "now": "linear blend"}


# ----------------------------------------------------------------------------- extra chains

# the body's reference bones a chain (tail, ears) can hang from, and each chain's first ref bone
BODY_REFS = ("root_ref.x", "spine_01_ref.x", "spine_02_ref.x", "spine_03_ref.x", "neck_ref.x", "head_ref.x")
CHAIN_ROOTS = {"tail": "tail_00_ref.x", "ear_l": "ear_01_ref.l", "ear_r": "ear_01_ref.r"}
CHAIN_CONTROLS = {"tail": ("c_tail_", ".x"), "ear_l": ("c_ear_", ".l"), "ear_r": ("c_ear_", ".r")}
APP_ATTR = "forge_app_"            # boolean point attribute on the body: the appendage's surface
FREE_ATTR = "forge_free_"          # ... of a part found but not rigged (no chain): left as bound
ROOT_RINGS = 3                     # edge rings round an appendage's root (weight hand-off, ownership)
ROOT_FADE = 2.0                    # the hand-off fades over this x the root's radius (its
                                   # thickness), along the skin
ROOT_SHARE_WARN = 0.5              # the chain's parent should move at least this much of its root skin
RIGID = "rigid (follows its parent bone)"
STRAY_PROP = "forge_stray_chains"  # (body object) chains placed by no part, comma-separated
NOT_RIGGED = "not rigged yet, so it will not bend on its own"


def appendage_parent(ref_segments: dict, root_point):
    """The body bone a chain (tail, ear...) should hang from: the one whose segment the chain's
    root projects onto (0 <= t <= 1) at the smallest perpendicular distance - that bone owns
    the skin the chain grows out of. If the root projects onto none, the nearest one.
    ref_segments: {name: (head, tail)} with any 3-vectors. Returns a name (None if empty)."""
    import numpy as np
    p = np.asarray(root_point, float)
    best, best_key = None, None
    for name, (h, t) in ref_segments.items():
        h, t = np.asarray(h, float), np.asarray(t, float)
        ab = t - h
        L2 = float(ab @ ab)
        if L2 < 1e-12:
            continue
        u = float((p - h) @ ab) / L2
        d = float(np.linalg.norm(p - (h + min(max(u, 0.0), 1.0) * ab)))
        key = (0 if 0.0 <= u <= 1.0 else 1, d)
        if best_key is None or key < best_key:
            best, best_key = name, key
    return best


def hang_chains(rig) -> dict:
    """(EDIT mode, reference rig) Hang each extra chain's first reference bone from the body
    reference bone its root projects onto (appendage_parent). Auto-Rig Pro builds the real
    chain's parent from it at match_to_rig. Returns {chain: {"ref_parent", "was"}}."""
    eb = rig.data.edit_bones
    mw = rig.matrix_world
    segs = {n: (mw @ eb[n].head, mw @ eb[n].tail) for n in BODY_REFS if n in eb}
    out = {}
    for chain, first in CHAIN_ROOTS.items():
        b = eb.get(first)
        if b is None or not segs:
            continue
        want = appendage_parent(segs, mw @ b.head)
        was = b.parent.name if b.parent else None
        if want and want != was:
            b.use_connect = False
            b.parent = eb[want]
        out[chain] = {"ref_parent": want or was, "was": was}
    return out


def _bones_named(rig, prefix: str, side: str) -> list:
    out = []
    for b in rig.data.bones:
        m = re.match(rf"^{re.escape(prefix)}(\d+){re.escape(side)}$", b.name)
        if m:
            out.append((int(m.group(1)), b.name))
    return [n for _i, n in sorted(out)]


def chain_bones(rig, chain: str) -> list:
    """The chain's control bones in order (c_tail_00.x..., c_ear_01.l...)."""
    prefix, side = CHAIN_CONTROLS.get(chain, (None, None))
    return _bones_named(rig, prefix, side) if prefix else []


def _body_bone(rig, bone: str, weighted=None):
    """The deform bone a chain bone hangs from: walk up its parents, taking a deform parent or
    the deform bone a control drives (c_neck.x -> neck.x). With `weighted`, the first one that
    actually moves some skin (a skull control the bind left empty is passed over); if none
    does, the first deform one."""
    bones = rig.data.bones
    b = bones.get(bone)
    first = None
    p = b.parent if b is not None else None
    while p is not None:
        for cand in (p.name, p.name[2:] if p.name.startswith("c_") else None):
            if cand and cand in bones and bones[cand].use_deform:
                if weighted is None or cand in weighted:
                    return cand
                first = first or cand
        p = p.parent
    return first


def chain_parents(rig, hung: dict) -> dict:
    """After match_to_rig: which bone each extra chain really hangs from, against the body bone
    chosen for it. Auto-Rig Pro versions differ: a mismatch is reported, never raised."""
    out = {}
    for chain in CHAIN_ROOTS:
        bones = chain_bones(rig, chain)
        if not bones:
            continue
        first = rig.data.bones[bones[0]]
        ref = (hung.get(chain) or {}).get("ref_parent") if isinstance(hung, dict) else None
        want = ref.replace("_ref", "") if ref else None
        ancestors = [a.name for a in first.parent_recursive]
        ok = want is None or want in ancestors or ("c_" + want) in ancestors
        out[chain] = {"bone": first.name, "parent": first.parent.name if first.parent else None,
                      "body_bone": _body_bone(rig, first.name), "wanted": want, "ok": bool(ok)}
    master = rig.data.bones.get("c_tail_master.x")
    if master is not None and "tail" in out:
        out["tail"]["master_parent"] = master.parent.name if master.parent else None
    return out


def store_regions(obj, appendages: list, names) -> list:
    """Remember each rigged appendage's surface on the body (a boolean point attribute
    forge_app_<name>): after the bind, its chain's weight outside it goes to the parent bone.
    An attribute survives the bind, the weight clean-up and the engine exports.
    A part found but given no chain (a second tail, a wing: not rigged yet) is stored as
    forge_free_<name>: no other chain's hand-off may move its skin. A rigid part (a horn)
    is not: it follows its parent bone, so leaked chain weight on it goes to that bone."""
    import numpy as np
    me = obj.data
    for a in [a for a in me.attributes if a.name.startswith((APP_ATTR, FREE_ATTR))]:
        me.attributes.remove(a)
    stored = []
    for a in appendages:
        if a.get("vert_idx") is None or not a.get("name"):
            continue
        rigged = a["name"] in names
        if not rigged and a.get("kind") in (None, "horn"):
            continue
        mask = np.zeros(len(me.vertices), bool)
        idx = np.asarray(a["vert_idx"], np.int64)
        mask[idx[(idx >= 0) & (idx < len(mask))]] = True
        attr = me.attributes.new((APP_ATTR if rigged else FREE_ATTR) + a["name"], "BOOLEAN", "POINT")
        attr.data.foreach_set("value", mask)
        if rigged:
            stored.append(a["name"])
    return stored


def ring_distance(n: int, edges, region, rings: int):
    """Edge rings from a region: 0 inside it, 1..rings outside, inf further away."""
    import numpy as np
    dist = np.full(n, np.inf)
    dist[region] = 0.0
    front = np.asarray(region, bool).copy()
    for k in range(1, rings + 1):
        nb = front.copy()
        nb[edges[front[edges[:, 0]], 1]] = True
        nb[edges[front[edges[:, 1]], 0]] = True
        dist[nb & ~np.isfinite(dist)] = k
        front = nb
    return dist


def surface_distance(co, edges, region, rmax: float, rounds: int = 400):
    """Distance over the surface (along edges) from a region: 0 inside it, inf past rmax."""
    import numpy as np
    el = np.linalg.norm(co[edges[:, 0]] - co[edges[:, 1]], axis=1)
    d = np.where(np.asarray(region, bool), 0.0, np.inf)
    for _ in range(rounds):
        old = d.copy()
        np.minimum.at(d, edges[:, 1], d[edges[:, 0]] + el)
        np.minimum.at(d, edges[:, 0], d[edges[:, 1]] + el)
        d[d > rmax] = np.inf
        if np.array_equal(old, d):
            break
    return d


def root_radius(co, edges, region) -> float:
    """An appendage's root radius: its points next to the body, from their middle."""
    import numpy as np
    reg = np.asarray(region, bool)
    a, b = edges[:, 0], edges[:, 1]
    edge = np.unique(np.concatenate([a[reg[a] & ~reg[b]], b[reg[b] & ~reg[a]]]))
    if len(edge) < 3:
        return 0.0
    p = co[edge]
    return float(np.median(np.linalg.norm(p - p.mean(axis=0), axis=1)))


def own_piece(edges, region, n: int):
    """The points of the separate shell(s) an appendage is, or None when it shares its skin
    with the body. Step 4 keeps a part as its own piece (its root plugged into the body) when
    it cannot join it as one skin: then no edge leads from the part to the body, and anything
    measured along the skin from it never reaches the body. Read by connectivity, not by name
    (a tail, a wing, an antenna). The body is the shell holding most of the points outside the
    region; the region is its own piece when none of its shells is that one."""
    import numpy as np
    from .appendages import _components
    reg = np.asarray(region, bool)
    if not reg.any() or reg.all() or not len(edges):
        return None
    lab = _components(n, edges[:, 0], edges[:, 1])
    rest = np.bincount(lab[~reg], minlength=n)
    body = int(np.argmax(rest))
    mine = np.unique(lab[reg])
    if body in mine:
        return None
    return np.isin(lab, mine)


def piece_root(co, edges, piece, faces) -> tuple:
    """Where a part kept as its own piece enters the body, measured in space: (the root points
    - the piece's points within one of its edges of the body's surface, in the biggest connected
    group of its points near or inside the body - and the root's radius). `faces`: the body's triangles
    (point indices). (empty, 0.0) when the piece is nowhere near the body."""
    import numpy as np
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    from .appendages import _components
    pts = np.flatnonzero(piece)
    if not len(pts) or not len(faces):
        return np.zeros(0, np.int64), 0.0
    pe = edges[piece[edges[:, 0]] & piece[edges[:, 1]]]
    el = np.linalg.norm(co[pe[:, 0]] - co[pe[:, 1]], axis=1) if len(pe) else np.zeros(0)
    h = float(np.median(el)) if len(el) else 0.0
    tree = BVHTree.FromPolygons([Vector(c) for c in co], [tuple(map(int, t)) for t in faces])
    depth = np.full(len(pts), np.inf)              # signed: below 0 inside the body
    for k, i in enumerate(pts.tolist()):
        hit = tree.find_nearest(Vector(co[i]))
        if hit[0] is not None:
            side = float((Vector(co[i]) - hit[0]).dot(hit[1]))
            depth[k] = -hit[3] if side < 0 else hit[3]
    if not np.isfinite(depth).any():
        return np.zeros(0, np.int64), 0.0
    near = depth <= max(h, 1.5 * float(np.min(np.abs(depth[np.isfinite(depth)]))))
    sel = np.zeros(len(co), bool)
    sel[pts[near]] = True
    se = pe[sel[pe[:, 0]] & sel[pe[:, 1]]]
    lab = _components(len(co), se[:, 0], se[:, 1]) if len(se) else np.arange(len(co))
    groups, sizes = np.unique(lab[sel], return_counts=True)
    dmap = np.full(len(co), np.inf)
    dmap[pts] = depth
    # the root: the biggest connected group (the plug and its ring), the deeper one on a tie (a
    # tail tip dipping into a leg is a small group of its own)
    root_g = max(zip(groups.tolist(), sizes.tolist()), key=lambda gs: (gs[1], -float(dmap[lab == gs[0]].min())))[0]
    grp = sel & (lab == root_g)
    ring = grp.copy()
    ring[pts[np.abs(depth) > max(h, 1e-9)]] = False   # (the deep plug is not the root's ring)
    use = np.flatnonzero(ring if ring.sum() >= 3 else grp)
    p = co[use]
    rad = float(np.median(np.linalg.norm(p - p.mean(axis=0), axis=1))) if len(use) >= 3 else h
    return use, rad


def _space_distance(co, src, dst, rmax: float):
    """Distance in space from the points `src` to each point of `dst` (bool), inf past rmax."""
    import numpy as np
    d = np.full(len(co), np.inf)
    if not len(src) or rmax <= 0:
        return d
    s = co[src]
    lo, hi = s.min(axis=0) - rmax, s.max(axis=0) + rmax
    cand = np.flatnonzero(np.asarray(dst, bool) & np.all((co >= lo) & (co <= hi), axis=1))
    for i in range(0, len(cand), 2048):
        c = cand[i:i + 2048]
        m = np.sqrt(((co[c, None, :] - s[None, :, :]) ** 2).sum(axis=2)).min(axis=1)
        d[c] = np.where(m <= rmax, m, np.inf)
    return d


def settle_appendages(obj, rig, rings: int = ROOT_RINGS) -> dict:
    """After the bind, for each rigged appendage stored on the body:
    - root ownership: of the skin in a band round its root (chain bones left out), the share
      its parent bone moves. If another bone owns that skin, the root tears when that bone
      moves (a tail hung from the hips while the lower back owns its root).
    - weight hand-off: bone heat lets appendage bones move body skin (an ear flap dragging the
      neck). Chain weight outside the appendage goes to the parent bone, fading out over a
      distance along the skin of ROOT_FADE x the root's radius (keep 1 - d / that), so there is
      no seam on any mesh: the same width on a coarse game mesh as on a fine one. The point's
      total is unchanged. The band is that wide too (`rings` edge rings when the root's radius
      cannot be read).
    A part Step 4 kept as its own piece (no edge to the body: own_piece) is measured in space
    from where it enters the body (piece_root) instead of along the skin, the whole piece
    keeping its chain's weight. The surface of a part no chain moves (FREE_ATTR: found, not
    rigged yet) is never touched: another chain's hand-off must not pin it to the parent bone.
    Returns {appendage: {...}}."""
    import numpy as np
    from .skin import set_weights, weight_matrix
    me = obj.data
    regions = [a.name for a in me.attributes if a.name.startswith(APP_ATTR) and a.domain == "POINT"]
    if not regions:
        return {}
    deform = {b.name for b in rig.data.bones if b.use_deform}
    names, W = weight_matrix(obj, deform)
    n = len(me.vertices)
    weighted = {nm for j, nm in enumerate(names) if W[:, j].max() > 1e-4}
    E = np.empty(len(me.edges) * 2, np.int64)
    me.edges.foreach_get("vertices", E)
    E = E.reshape(-1, 2)
    free = np.zeros(n, bool)                     # parts with no chain of their own: left alone
    for a in [a for a in me.attributes if a.name.startswith(FREE_ATTR) and a.domain == "POINT"]:
        m = np.zeros(n, bool)
        a.data.foreach_get("value", m)
        free |= m
    co = np.empty(n * 3)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    tris = None
    out, changed = {}, set()
    for attr_name in regions:
        app = attr_name[len(APP_ATTR):]
        reg = np.zeros(n, bool)
        me.attributes[attr_name].data.foreach_get("value", reg)
        chain = [b for b in chain_bones(rig, app) if b in names]
        if not chain or not reg.any():
            out[app] = {"skipped": "no chain bones carry weight" if reg.any() else "no surface stored"}
            continue
        parent = _body_bone(rig, chain[0], weighted)
        if parent is None:
            out[app] = {"skipped": "it hangs from no deforming bone"}
            continue
        if parent not in names:                         # a bone the bind gave no skin yet
            names.append(parent)
            W = np.hstack([W, np.zeros((n, 1))])
        cols = [names.index(b) for b in chain]
        pj = names.index(parent)
        piece = own_piece(E, reg, n)
        if piece is not None:                          # its own shell: measured in space
            if tris is None:
                me.calc_loop_triangles()
                tris = np.empty(len(me.loop_triangles) * 3, np.int64)
                me.loop_triangles.foreach_get("vertices", tris)
                tris = tris.reshape(-1, 3)
            body_f = tris[~piece[tris].any(axis=1)]
            src, rad = piece_root(co, E, piece, body_f)
            width = ROOT_FADE * rad
            dist = _space_distance(co, src, ~piece, width) / max(width, 1e-12)
            dist[piece] = 0.0
            body = ~piece
            band = body & (dist <= 1.0)
            if not band.any() and len(src):            # (a root finer than the body's points)
                d2 = _space_distance(co, src, body, np.inf)
                if np.isfinite(d2[body]).any():
                    band = body & (d2 <= 2.0 * float(np.min(d2[body])) + 1e-9)
            keep = np.clip(1.0 - dist, 0.0, 1.0)
        else:
            width = ROOT_FADE * root_radius(co, E, reg)
            if width > 0:
                dist = surface_distance(co, E, reg, width) / width        # (in widths: 1 = faded out)
                band = (dist > 0) & (dist <= 1.0)
                keep = np.clip(1.0 - dist, 0.0, 1.0)
            else:
                dist = ring_distance(n, E, reg, rings)
                band = (dist >= 1) & (dist <= rings)
                keep = np.clip(1.0 - dist / (rings + 1), 0.0, 1.0)
        keep[free & ~reg] = 1.0
        band &= ~free
        rest = W[band].copy()
        rest[:, cols] = 0.0
        tot = rest.sum(axis=0)
        share = float(tot[pj] / tot.sum()) if tot.sum() > 0 else 0.0
        owner = names[int(np.argmax(tot))] if tot.sum() > 0 else parent
        moved = W[:, cols] * (1.0 - keep)[:, None]
        total = np.maximum(W.sum(axis=1), 1e-12)
        drag = moved.sum(axis=1) / total            # share of each point the chain was moving
        W[:, cols] -= moved
        W[:, pj] += moved.sum(axis=1)
        changed |= set(cols) | {pj}
        out[app] = {"chain": chain, "parent": parent, "root_share": round(share, 2), "root_owner": owner,
                    "fade_mm": round(width * 1000.0, 1),
                    "root_ok": share >= ROOT_SHARE_WARN, "moved_points": int((drag > 0.01).sum()),
                    "moved_max": round(float(drag.max()), 2)}
        if piece is not None:
            out[app]["own_piece"] = True
        if tot.sum() <= 0:                          # no body skin round the root to read
            out[app]["root_ok"] = None
    if changed:
        set_weights(obj, names, W, sorted(changed))
    return out


def still_chains(obj, rig, chains) -> dict:
    """Chains Auto-Rig Pro added that no appendage was found for (it adds both ears; a
    one-eared creature, or an ear the finder missed, leaves one at its default spot by the
    head): all their weight goes to the bone they hang from, so they move no skin and the
    range-of-motion clip turning them drags nothing. {chain: {"parent", "points"}}."""
    import numpy as np
    from .skin import set_weights, weight_matrix
    deform = {b.name for b in rig.data.bones if b.use_deform}
    names, W = weight_matrix(obj, deform)
    n = len(obj.data.vertices)
    weighted = {nm for j, nm in enumerate(names) if W[:, j].max() > 1e-4}
    out, changed = {}, set()
    for chain in chains:
        bones = [b for b in chain_bones(rig, chain) if b in names]
        if not bones:
            continue
        parent = _body_bone(rig, bones[0], weighted)
        if parent is None:
            continue
        if parent not in names:
            names.append(parent)
            W = np.hstack([W, np.zeros((n, 1))])
        cols = [names.index(b) for b in bones]
        pj = names.index(parent)
        moved = W[:, cols].sum(axis=1)
        W[:, cols] = 0.0
        W[:, pj] += moved
        changed |= set(cols) | {pj}
        out[chain] = {"parent": parent, "points": int((moved > 0.01).sum())}
    if changed:
        set_weights(obj, names, W, sorted(changed))
    return out


def build(args: dict) -> dict:
    """Full-auto pipeline: rebuild the AI (Tripo) skeleton as an ARP rig.
    Returns a report; raises on failure (caller falls back)."""
    src = next((o for o in bpy.data.objects if o.type == "ARMATURE" and o.get(C.ROLE_PROP) == "rig"
                and not o.get("forge_arp")), None)
    if src is None:
        raise RuntimeError("no source armature to rebuild")
    joints = find_joints(src)
    miss = missing_joints(joints)
    if miss:
        raise RuntimeError(f"source skeleton lacks joints ARP needs: {miss}")
    lows = C.meshes_with_role("low")
    rig, report = place(joints, lows, args)
    detachable = set(args.get("detachable_parts", []))
    body = [o for o in lows if o.get(C.PART_PROP) not in detachable]
    props = [o for o in lows if o.get(C.PART_PROP) in detachable]
    report.update(finish(rig, body, props, args))
    # the AI skeleton is no longer needed (high meshes keep theirs only as bake sources)
    for o in list(bpy.data.objects):
        if o.type == "MESH" and o.get(C.ROLE_PROP) == "high":
            for m in [m for m in o.modifiers if m.type == "ARMATURE"]:
                o.modifiers.remove(m)
            o.parent = None
    bpy.data.objects.remove(src)
    for o in C.meshes_with_role("weights"):       # rig-file meshes were only a weight source
        bpy.data.objects.remove(o)
    return report


# ----------------------------------------------------------------------------- extra limbs

def _resample(chain: list, n: int) -> list:
    """n+1 points evenly along a polyline (n bones)."""
    pts = [Vector(p) for p in chain]
    seg = [(pts[i + 1] - pts[i]).length for i in range(len(pts) - 1)]
    total = sum(seg) or 1e-9
    out, acc, i = [pts[0]], 0.0, 0
    for k in range(1, n):
        want = total * k / n
        while i < len(seg) - 1 and acc + seg[i] < want:
            acc += seg[i]
            i += 1
        t = (want - acc) / max(seg[i], 1e-9)
        out.append(pts[i].lerp(pts[i + 1], min(max(t, 0.0), 1.0)))
    out.append(pts[-1])
    return out


def _chain_refs(rig, stem: str, side: str, first: int) -> list:
    """A chain's reference bones in order, as many as Auto-Rig Pro made (Edit Mode):
    tail_00_ref.x, tail_01_ref.x ... or ear_01_ref.l, ear_02_ref.l ..."""
    eb = rig.data.edit_bones
    out, i = [], first
    while eb.get(f"{stem}_{i:02d}_ref{side}") is not None:
        out.append(f"{stem}_{i:02d}_ref{side}")
        i += 1
    return out


def _place_chain(rig, names: list, pts: list) -> int:
    eb = rig.data.edit_bones
    inv = rig.matrix_world.inverted()
    n = 0
    for i, name in enumerate(names):
        b = eb.get(name)
        if b is None or i + 1 >= len(pts):
            continue
        b.head, b.tail = inv @ pts[i], inv @ pts[i + 1]
        n += 1
    return n


def add_extras(rig, appendages: list, args: dict) -> dict:
    """Tail and ears from the detected appendages (Auto-Rig Pro limbs), facial bones off
    until the face has a cut mouth and separate eyes. Never raises: problems are reported.

    Limb options change through the safe protocol (arp_limb_options, spec 9.2): the face switch
    is skipped when the head already has it off (Auto-Rig Pro's human preset does), and a bone
    count is changed with every other setting of that limb sent back as it was. When Auto-Rig
    Pro refuses, the panel gets a plain reason, the report keeps what its check saw
    (limb_options, for the log), and the tail and ears are still added with the bones it made."""
    rep: dict = {"added": {}, "skipped": {}, "errors": [], "limb_options": {}}
    C.select_only(rig)
    bpy.ops.object.mode_set(mode="EDIT")
    ov = _ov()

    def call(fn, **kw):
        LO.edit_mode(rig)
        with bpy.context.temp_override(**ov):
            res = fn("EXEC_DEFAULT", **kw)
        LO.edit_mode(rig)                                 # (the chain's bones are read in Edit Mode)
        return res

    def count(ref: str, key: str, n: int, label: str, words) -> None:
        """Auto-Rig Pro's bone count for a chain; when it says no, its own count stays."""
        r = LO.set_limb_options(rig, ref, {key: n})
        rep["limb_options"][label] = r
        if not r.get("ok"):
            rep["errors"].append(words(r.get("reason") or LO.WORDS["failed"]))
        LO.edit_mode(rig)

    if not args.get("facial", False):
        try:
            f = LO.facial_off(rig)
            rep["facial"] = f["facial"]
            if f.get("protocol"):
                rep["limb_options"]["facial"] = f["protocol"]
            if f["facial"] == "still on":
                rep["errors"].append(f"face bones stay on: {f.get('reason')}")
            LO.edit_mode(rig)
        except Exception as exc:                          # noqa: BLE001
            rep["errors"].append(f"face bones: {exc}")
    by_kind = {}
    for a in appendages:
        by_kind.setdefault(a["kind"], []).append(a)

    tail = (by_kind.get("tail") or [None])[0]
    if tail is not None:
        n = int(args.get("tail_bones", 4))
        try:
            call(bpy.ops.arp.add_limb, limbs_presets="tail")
            names = _chain_refs(rig, "tail", ".x", 0)
            if names and len(names) != n:
                have = len(names)
                count("tail_00_ref.x", "tail_count", n, "tail_count",
                      lambda why: f"tail: {have} bones, not {n}: {why}")
                names = _chain_refs(rig, "tail", ".x", 0)
            rep["added"]["tail"] = _place_chain(rig, names, _resample(tail["chain"], len(names))) if names else 0
        except Exception as exc:                          # noqa: BLE001
            rep["errors"].append(f"tail: {exc}")

    ears = {a["name"][-1]: a for a in by_kind.get("ear", []) if a["name"] in ("ear_l", "ear_r")}
    if ears:
        n = int(args.get("ear_bones", 2))
        try:
            call(bpy.ops.arp.add_limb, limbs_presets="ears")
            placed = 0
            for s, a in ears.items():                   # Auto-Rig Pro counts each side's ear on its own
                names = _chain_refs(rig, "ear", "." + s, 1)
                if names and len(names) != n:
                    have, side = len(names), {"l": "left", "r": "right"}[s]
                    count(f"ear_01_ref.{s}", "ear_count", n, f"ear_count_{s}",
                          lambda why, h=have, w=side: f"{w} ear: {h} bones, not {n}: {why}")
                    names = _chain_refs(rig, "ear", "." + s, 1)
                if names:
                    placed += _place_chain(rig, names, _resample(a["chain"], len(names)))
            rep["added"]["ears"] = placed
        except Exception as exc:                          # noqa: BLE001
            rep["errors"].append(f"ears: {exc}")

    # which appendage became which chain (their surfaces are stored for the bind)
    rep["chains"] = ([tail["name"]] if tail is not None and "tail" in rep["added"] else []) \
        + ([a["name"] for a in ears.values()] if "ears" in rep["added"] else [])
    # every other part found is listed (a second tail, a third ear, wings...): none goes
    # unmentioned. A part with no chain only follows the body; its skin is kept as bound
    for a in appendages:
        if a["name"] not in rep["chains"]:
            rep["skipped"][a["name"]] = RIGID if a["kind"] == "horn" else NOT_RIGGED
    # Auto-Rig Pro adds both ears: a side no ear was found for keeps its default spot by the
    # head. Its bones must move no skin (finish() hands their weight to the parent bone)
    if "ears" in rep["added"]:
        rep["stray"] = [f"ear_{s}" for s in "lr" if s not in ears]
    try:                         # each chain hangs from the body bone its root grows out of
        LO.edit_mode(rig)
        rep["parents"] = hang_chains(rig)
    except Exception as exc:                              # noqa: BLE001
        rep["errors"].append(f"chain parents: {exc}")
    bpy.ops.object.mode_set(mode="OBJECT")
    return rep
