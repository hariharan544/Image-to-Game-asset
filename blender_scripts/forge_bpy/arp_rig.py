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
    with bpy.context.temp_override(**_ov()):
        bpy.ops.arp.match_to_rig()
    bpy.ops.object.mode_set(mode="OBJECT")
    rig = bpy.data.objects.get(rig.name)
    rig[C.ROLE_PROP] = "rig"
    rig["forge_arp"] = True
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
    # ARP's binding does not respect the engine's influence limit nor normalise: do it here
    from .skin import _cleanup_weights
    deform = {b.name for b in rig.data.bones if b.use_deform}
    max_inf = int(args.get("max_influences", 4))
    min_w = float(args.get("min_weight", 0.01))
    report["weight_cleanup"] = {o.get(C.PART_PROP): _cleanup_weights(o, max_inf, min_w, deform) for o in body}
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
        p.parent = rig
        p.matrix_parent_inverse = rig.matrix_world.inverted()
        report["props"][part] = bone
    report["sockets"] = {k: ARP_SOCKET_BONES.get(v, v) for k, v in sockets.items()}
    report["rig"] = rig.name
    report["bones"] = len(rig.data.bones)
    report["deform_bones"] = sum(1 for b in rig.data.bones if b.use_deform)
    return report


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


def _select_ref(rig, name: str) -> bool:
    eb = rig.data.edit_bones
    b = eb.get(name)
    if b is None:
        return False
    for x in eb:
        x.select = x.select_head = x.select_tail = False
    b.select = b.select_head = b.select_tail = True
    eb.active = b
    return True


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
    until the face has a cut mouth and separate eyes. Never raises: problems are reported."""
    rep: dict = {"added": {}, "skipped": {}, "errors": []}
    C.select_only(rig)
    bpy.ops.object.mode_set(mode="EDIT")
    ov = _ov()

    def call(fn, **kw):
        with bpy.context.temp_override(**ov):
            return fn("EXEC_DEFAULT", **kw)

    if not args.get("facial", False) and _select_ref(rig, "head_ref.x"):
        try:
            call(bpy.ops.arp.show_limb_params, limb_type="head", side=".x", facial=False)
            rep["facial"] = "off"
        except Exception as exc:                          # noqa: BLE001
            rep["errors"].append(f"facial off: {exc}")
    by_kind = {}
    for a in appendages:
        by_kind.setdefault(a["kind"], []).append(a)

    tail = (by_kind.get("tail") or [None])[0]
    if tail is not None:
        n = int(args.get("tail_bones", 4))
        try:
            call(bpy.ops.arp.add_limb, limbs_presets="tail")
            if _select_ref(rig, "tail_00_ref.x") and n != 4:
                call(bpy.ops.arp.show_limb_params, limb_type="tail", side=".x", tail_count=n)
            placed = _place_chain(rig, [f"tail_{i:02d}_ref.x" for i in range(n)], _resample(tail["chain"], n))
            rep["added"]["tail"] = placed
        except Exception as exc:                          # noqa: BLE001
            rep["errors"].append(f"tail: {exc}")

    ears = {a["name"][-1]: a for a in by_kind.get("ear", []) if a["name"] in ("ear_l", "ear_r")}
    if ears:
        n = int(args.get("ear_bones", 2))
        try:
            call(bpy.ops.arp.add_limb, limbs_presets="ears")
            if _select_ref(rig, "ear_01_ref.l") and n != 2:
                call(bpy.ops.arp.show_limb_params, limb_type="ear", side=".l", ear_count=n)
            placed = 0
            for s, a in ears.items():
                placed += _place_chain(rig, [f"ear_{i:02d}_ref.{s}" for i in range(1, n + 1)],
                                       _resample(a["chain"], n))
            rep["added"]["ears"] = placed
        except Exception as exc:                          # noqa: BLE001
            rep["errors"].append(f"ears: {exc}")

    for kind, items in by_kind.items():
        if kind not in ("tail", "ear"):
            for a in items:
                rep["skipped"][a["name"]] = "rigid (follows its parent bone)" if kind == "horn" \
                    else "found, not rigged yet"
    bpy.ops.object.mode_set(mode="OBJECT")
    return rep
