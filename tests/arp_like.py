"""An Auto-Rig Pro-like final rig on a test body, built with Forge's own rules (Auto-Rig Pro
itself needs a UI, so it cannot run in the tests).

Deform bones, names and hierarchy follow ARP's human preset (checked in its human.blend and
dog.blend): upper arm = c_arm_twist_offset + arm_stretch, forearm = forearm_stretch +
forearm_twist, thigh = thigh_twist + thigh_stretch, leg = leg_stretch + leg_twist; the FK
controls drive the deform bones as their children, which is what ARP's constraints amount to
in FK; c_arm_fk copies only c_shoulder's location. What Forge decides is used as Forge does:
arp_rig.ref_targets (head pivot at the skull base), appendage_parent (each chain hangs from
the body bone its root grows out of), store_regions + settle_appendages after the bind,
linear blending and the continuous 8-bone limit. The bind is Blender's bone heat, which is
what ARP's HEAT_MAP engine runs."""

from __future__ import annotations

import bpy
from mathutils import Vector

from forge_bpy import appendages, arp_rig, joints, skin

# body reference bone -> the deform bone Auto-Rig Pro makes from it (parent_retarget)
BODY = {"root_ref.x": "root.x", "spine_01_ref.x": "spine_01.x", "spine_02_ref.x": "spine_02.x",
        "neck_ref.x": "neck.x", "head_ref.x": "head.x"}


def _half(h, t, first):
    m = h.lerp(t, 0.5)
    return (h, m) if first else (m, t)


def build(body, tail_parent: str | None = None, settle: bool = True, skull_base: bool = True,
          preserve_volume: bool = False, max_inf: int = 8):
    """Rig and skin `body`. Returns (rig, J, apps, report). tail_parent forces the tail's
    parent bone (None: Forge's appendage_parent). The bull's ears come out as 'extra' at
    coarse resolutions; side parts at head height are rigged as ears here."""
    J = joints.estimate(body)
    if not skull_base:
        J.pop("_skull_base", None)
    apps = appendages.from_object(body, J)
    for a in apps:
        if a["kind"] == "extra" and a["name"] in ("extra_l", "extra_r") and a["chain"][0][2] > J["neck"][0].z:
            a["kind"], a["name"] = "ear", "ear_" + a["name"][-1]
    lo = min((body.matrix_world @ Vector(c)).z for c in body.bound_box)
    hi = max((body.matrix_world @ Vector(c)).z for c in body.bound_box)
    T = arp_rig.ref_targets(J, lo, hi)
    B: dict = {}

    def put(n, ht, parent, deform, inherit_rot=True):
        B[n] = (Vector(ht[0]), Vector(ht[1]), parent, deform, inherit_rot)

    put("c_root_master.x", T["root_ref.x"], None, False)
    put("root.x", T["root_ref.x"], "c_root_master.x", True)
    put("c_spine_01.x", T["spine_01_ref.x"], "c_root_master.x", False)
    put("spine_01.x", T["spine_01_ref.x"], "c_spine_01.x", True)
    put("c_spine_02.x", T["spine_02_ref.x"], "c_spine_01.x", False)
    put("spine_02.x", T["spine_02_ref.x"], "c_spine_02.x", True)
    put("c_neck.x", T["neck_ref.x"], "spine_02.x", False)
    put("neck.x", T["neck_ref.x"], "c_neck.x", True)
    put("c_head.x", T["head_ref.x"], "c_neck.x", False)
    put("head.x", T["head_ref.x"], "c_head.x", True)
    for s in "lr":
        x = "." + s
        put("c_shoulder" + x, T["shoulder_ref" + x], "spine_02.x", False)
        put("shoulder" + x, T["shoulder_ref" + x], "c_shoulder" + x, True)
        a, f = T["arm_ref" + x], T["forearm_ref" + x]
        put("c_arm_fk" + x, a, "c_shoulder" + x, False, inherit_rot=False)
        put("arm_twist" + x, _half(*a, True), "c_shoulder" + x, False)
        put("c_arm_twist_offset" + x, _half(*a, True), "arm_twist" + x, True)
        put("arm_stretch" + x, _half(*a, False), "c_arm_fk" + x, True)
        put("c_forearm_fk" + x, f, "c_arm_fk" + x, False)
        put("forearm_stretch" + x, _half(*f, True), "c_forearm_fk" + x, True)
        put("forearm_twist" + x, _half(*f, False), "forearm_stretch" + x, True)
        put("c_hand_fk" + x, T["hand_ref" + x], "c_forearm_fk" + x, False)
        put("hand" + x, T["hand_ref" + x], "c_hand_fk" + x, True)
        th, lg = T["thigh_ref" + x], T["leg_ref" + x]
        put("c_thigh_fk" + x, th, "c_root_master.x", False)
        put("thigh_twist" + x, _half(*th, True), "c_thigh_fk" + x, True)
        put("thigh_stretch" + x, _half(*th, False), "c_thigh_fk" + x, True)
        put("c_leg_fk" + x, lg, "c_thigh_fk" + x, False)
        put("leg_stretch" + x, _half(*lg, True), "c_leg_fk" + x, True)
        put("leg_twist" + x, _half(*lg, False), "c_leg_fk" + x, True)
        put("c_foot_fk" + x, T["foot_ref" + x], "c_leg_fk" + x, False)
        put("foot" + x, T["foot_ref" + x], "c_foot_fk" + x, True)
        put("toes_01" + x, T["toes_ref" + x], "foot" + x, True)

    segs = {k: T[k] for k in BODY}
    parents, chains = {}, []
    tail = next((a for a in apps if a["kind"] == "tail"), None)
    if tail:
        pts = arp_rig._resample(tail["chain"], 4)
        tp = tail_parent or BODY[arp_rig.appendage_parent(segs, pts[0])]
        parents["tail"] = tp
        chains.append(tail["name"])
        for i in range(4):
            put(f"c_tail_{i:02d}.x", (pts[i], pts[i + 1]), tp if i == 0 else f"c_tail_{i - 1:02d}.x", True)
    for s in "lr":
        ear = next((a for a in apps if a["kind"] == "ear" and a["name"] == "ear_" + s), None)
        if ear:
            pts = arp_rig._resample(ear["chain"], 2)
            ep = BODY[arp_rig.appendage_parent(segs, pts[0])]
            parents["ear_" + s] = ep
            chains.append(ear["name"])
            for i in range(2):
                put(f"c_ear_{i + 1:02d}.{s}", (pts[i], pts[i + 1]), ep if i == 0 else f"c_ear_{i:02d}.{s}", True)

    ad = bpy.data.armatures.new("rig")
    arm = bpy.data.objects.new("rig", ad)
    bpy.context.scene.collection.objects.link(arm)
    arm["forge_arp"] = True
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    for n, (h, t, _p, d, ir) in B.items():
        eb = ad.edit_bones.new(n)
        eb.head, eb.tail, eb.use_deform, eb.use_inherit_rotation = h, t, d, ir
    for n, (_h, _t, p, _d, _ir) in B.items():
        if p:
            ad.edit_bones[n].parent = ad.edit_bones[p]
    bpy.ops.object.mode_set(mode="OBJECT")
    for s in "lr":
        c = arm.pose.bones["arm_twist." + s].constraints.new("DAMPED_TRACK")
        c.target, c.subtarget, c.head_tail = arm, "c_forearm_fk." + s, 0.0

    report = {"parents": parents, "regions": arp_rig.store_regions(body, apps, chains)}
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    body.select_set(True)
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.parent_set(type="ARMATURE_AUTO")
    mod = next(m for m in body.modifiers if m.type == "ARMATURE")
    mod.use_deform_preserve_volume = preserve_volume
    if not preserve_volume:
        report["skinning"] = arp_rig.linear_blend(arm, [body])
    report["appendages"] = arp_rig.settle_appendages(body, arm) if settle else {}
    deform = {n for n, v in B.items() if v[3]}
    skin._cleanup_weights(body, max_inf, 0.01, deform, continuous=True)
    return arm, J, apps, report
