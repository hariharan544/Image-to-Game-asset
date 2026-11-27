"""A stand-in for Auto-Rig Pro's operators, enough for Forge's Step 8 to run end to end in
the tests (the real add-on needs a licence and a UI).

What it copies from Auto-Rig Pro (read in its 3.77.33 source):
  - append_arp: a reference armature 'rig' of *_ref bones (not deforming)
  - add_limb: tail_00_ref.x... hung from root_ref.x, ear_01_ref.l/.r from head_ref.x
  - match_to_rig: the final bones in the same object. A tail's first control hangs from what
    its reference hangs from, mapped like parent_retarget (spine_01_ref.x -> spine_01.x,
    root_ref.x -> root.x, others -> their c_ control); an ear on head_ref.x hangs from
    c_skull_02.x when it exists, else head.x
  - bind_to_rig: bone heat on the selected meshes; the Armature modifier's Preserve Volume is
    the scene's arp_bind_preserve (default True, as in Auto-Rig Pro)
IGNORE_TAIL_PARENT = True mimics a version that always hangs the tail from root.x."""

from __future__ import annotations

import bpy
from mathutils import Vector

IGNORE_TAIL_PARENT = False
SEEN: dict = {}


def _ref_layout():
    """Default reference bones (Forge moves them): name -> (head, tail, parent)."""
    B = {"root_ref.x": ((0, 0, 0.9), (0, 0, 1.0), None),
         "spine_01_ref.x": ((0, 0, 1.0), (0, 0, 1.2), "root_ref.x"),
         "spine_02_ref.x": ((0, 0, 1.2), (0, 0, 1.4), "spine_01_ref.x"),
         "neck_ref.x": ((0, 0, 1.4), (0, 0, 1.5), "spine_02_ref.x"),
         "head_ref.x": ((0, 0, 1.5), (0, 0, 1.8), "neck_ref.x")}
    for s, x in (("l", 1), ("r", -1)):
        B[f"shoulder_ref.{s}"] = ((0.05 * x, 0, 1.4), (0.15 * x, 0, 1.4), "spine_02_ref.x")
        B[f"arm_ref.{s}"] = ((0.15 * x, 0, 1.4), (0.45 * x, 0, 1.4), f"shoulder_ref.{s}")
        B[f"forearm_ref.{s}"] = ((0.45 * x, 0, 1.4), (0.7 * x, 0, 1.4), f"arm_ref.{s}")
        B[f"hand_ref.{s}"] = ((0.7 * x, 0, 1.4), (0.8 * x, 0, 1.4), f"forearm_ref.{s}")
        B[f"thigh_ref.{s}"] = ((0.1 * x, 0, 0.9), (0.1 * x, 0, 0.5), "root_ref.x")
        B[f"leg_ref.{s}"] = ((0.1 * x, 0, 0.5), (0.1 * x, 0, 0.1), f"thigh_ref.{s}")
        B[f"foot_ref.{s}"] = ((0.1 * x, 0, 0.1), (0.1 * x, -0.1, 0.03), f"leg_ref.{s}")
        B[f"toes_ref.{s}"] = ((0.1 * x, -0.1, 0.03), (0.1 * x, -0.17, 0.03), f"foot_ref.{s}")
    return B


def _new_bones(ad, bones: dict, deform: bool) -> None:
    eb = ad.edit_bones
    for n, (h, t, _p) in bones.items():
        b = eb.get(n) or eb.new(n)
        b.head, b.tail, b.use_deform = Vector(h), Vector(t), deform
    for n, (_h, _t, p) in bones.items():
        if p:
            eb[n].parent = eb[p]


class FAKE_OT_append_arp(bpy.types.Operator):
    bl_idname = "arp.append_arp"
    bl_label = "append"
    rig_preset: bpy.props.StringProperty(default="human")

    def execute(self, context):
        ad = bpy.data.armatures.new("rig")
        o = bpy.data.objects.new("rig", ad)
        context.scene.collection.objects.link(o)
        for x in context.view_layer.objects:
            x.select_set(False)
        context.view_layer.objects.active = o
        bpy.ops.object.mode_set(mode="EDIT")
        _new_bones(ad, _ref_layout(), False)
        bpy.ops.object.mode_set(mode="OBJECT")
        return {"FINISHED"}


class FAKE_OT_show_limb_params(bpy.types.Operator):
    bl_idname = "arp.show_limb_params"
    bl_label = "limb params"
    limb_type: bpy.props.StringProperty()
    side: bpy.props.StringProperty()
    facial: bpy.props.BoolProperty()
    tail_count: bpy.props.IntProperty()
    ear_count: bpy.props.IntProperty()

    def execute(self, context):
        return {"FINISHED"}


class FAKE_OT_add_limb(bpy.types.Operator):
    bl_idname = "arp.add_limb"
    bl_label = "add limb"
    limbs_presets: bpy.props.StringProperty()

    def execute(self, context):
        ad = context.active_object.data
        if self.limbs_presets == "tail":
            bones = {f"tail_{i:02d}_ref.x": ((0, 0.1 + 0.1 * i, 0.9), (0, 0.2 + 0.1 * i, 0.9),
                                             "root_ref.x" if i == 0 else f"tail_{i - 1:02d}_ref.x") for i in range(4)}
        else:
            bones = {}
            for s, x in (("l", 1), ("r", -1)):
                bones[f"ear_01_ref.{s}"] = ((0.1 * x, 0, 1.7), (0.2 * x, 0, 1.7), "head_ref.x")
                bones[f"ear_02_ref.{s}"] = ((0.2 * x, 0, 1.7), (0.3 * x, 0, 1.7), f"ear_01_ref.{s}")
        _new_bones(ad, bones, False)
        return {"FINISHED"}


def _retarget(ref_parent: str | None) -> str | None:
    """Auto-Rig Pro's parent_retarget for a reference parent."""
    if not ref_parent:
        return None
    side = ref_parent[-2:]
    c = "c_" + ref_parent.replace("_ref" + side, side)
    if c.startswith("c_root") or c.startswith("c_spine_"):
        c = c[2:]
    return c


class FAKE_OT_match_to_rig(bpy.types.Operator):
    bl_idname = "arp.match_to_rig"
    bl_label = "match"

    def execute(self, context):
        o = context.active_object
        eb = o.data.edit_bones

        def ref(n):
            b = eb[n]
            return (b.head.copy(), b.tail.copy())

        def half(ht, first):
            h, t = ht
            m = h.lerp(t, 0.5)
            return (h, m) if first else (m, t)
        B = {}

        def put(n, ht, parent, deform):
            B[n] = (ht[0], ht[1], parent, deform)
        put("c_root_master.x", ref("root_ref.x"), None, False)
        put("root.x", ref("root_ref.x"), "c_root_master.x", True)
        put("c_spine_01.x", ref("spine_01_ref.x"), "c_root_master.x", False)
        put("spine_01.x", ref("spine_01_ref.x"), "c_spine_01.x", True)
        put("c_spine_02.x", ref("spine_02_ref.x"), "c_spine_01.x", False)
        put("spine_02.x", ref("spine_02_ref.x"), "c_spine_02.x", True)
        put("c_neck.x", ref("neck_ref.x"), "spine_02.x", False)
        put("neck.x", ref("neck_ref.x"), "c_neck.x", True)
        put("c_head.x", ref("head_ref.x"), "c_neck.x", False)
        put("head.x", ref("head_ref.x"), "c_head.x", True)
        for s in "lr":
            x = "." + s
            put("c_shoulder" + x, ref("shoulder_ref" + x), "spine_02.x", False)
            put("shoulder" + x, ref("shoulder_ref" + x), "c_shoulder" + x, True)
            put("c_arm_fk" + x, ref("arm_ref" + x), "c_shoulder" + x, False)
            put("c_arm_twist_offset" + x, half(ref("arm_ref" + x), True), "c_shoulder" + x, True)
            put("arm_stretch" + x, half(ref("arm_ref" + x), False), "c_arm_fk" + x, True)
            put("c_forearm_fk" + x, ref("forearm_ref" + x), "c_arm_fk" + x, False)
            put("forearm_stretch" + x, ref("forearm_ref" + x), "c_forearm_fk" + x, True)
            put("c_hand_fk" + x, ref("hand_ref" + x), "c_forearm_fk" + x, False)
            put("hand" + x, ref("hand_ref" + x), "c_hand_fk" + x, True)
            put("c_thigh_fk" + x, ref("thigh_ref" + x), "c_root_master.x", False)
            put("thigh_stretch" + x, ref("thigh_ref" + x), "c_thigh_fk" + x, True)
            put("c_leg_fk" + x, ref("leg_ref" + x), "c_thigh_fk" + x, False)
            put("leg_stretch" + x, ref("leg_ref" + x), "c_leg_fk" + x, True)
            put("c_foot_fk" + x, ref("foot_ref" + x), "c_leg_fk" + x, False)
            put("foot" + x, ref("foot_ref" + x), "c_foot_fk" + x, True)
        if "tail_00_ref.x" in eb:
            p = "root.x" if IGNORE_TAIL_PARENT else _retarget(eb["tail_00_ref.x"].parent.name)
            i = 0
            while f"tail_{i:02d}_ref.x" in eb:
                put(f"c_tail_{i:02d}.x", ref(f"tail_{i:02d}_ref.x"), p if i == 0 else f"c_tail_{i - 1:02d}.x", True)
                i += 1
            put("c_tail_master.x", ref("tail_00_ref.x"), p, False)
        for s in "lr":
            if f"ear_01_ref.{s}" not in eb:
                continue
            rp = eb[f"ear_01_ref.{s}"].parent.name
            p = ("c_skull_02.x" if "c_skull_02.x" in B else "head.x") if "head_ref" in rp else _retarget(rp)
            put(f"c_ear_01.{s}", ref(f"ear_01_ref.{s}"), p, True)
            if f"ear_02_ref.{s}" in eb:
                put(f"c_ear_02.{s}", ref(f"ear_02_ref.{s}"), f"c_ear_01.{s}", True)
        _new_bones(o.data, {n: (h, t, p) for n, (h, t, p, _d) in B.items()}, False)
        for n, (_h, _t, _p, d) in B.items():
            eb[n].use_deform = d
        return {"FINISHED"}


class FAKE_OT_bind_to_rig(bpy.types.Operator):
    bl_idname = "arp.bind_to_rig"
    bl_label = "bind"

    def execute(self, context):
        sc = context.scene
        SEEN["arp_bind_preserve"] = bool(sc.arp_bind_preserve)
        rig = context.active_object
        meshes = [o for o in context.selected_objects if o.type == "MESH"]
        bpy.ops.object.parent_set(type="ARMATURE_AUTO")
        for o in meshes:
            m = next(m for m in o.modifiers if m.type == "ARMATURE" and m.object == rig)
            m.name = "rig"
            m.use_deform_preserve_volume = sc.arp_bind_preserve
        return {"FINISHED"}


CLASSES = (FAKE_OT_append_arp, FAKE_OT_show_limb_params, FAKE_OT_add_limb, FAKE_OT_match_to_rig,
           FAKE_OT_bind_to_rig)


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)
    bpy.types.Scene.arp_bind_preserve = bpy.props.BoolProperty(default=True)
    bpy.types.Scene.arp_bind_engine = bpy.props.StringProperty(default="HEAT_MAP")


def unregister():
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)
    del bpy.types.Scene.arp_bind_preserve
    del bpy.types.Scene.arp_bind_engine
