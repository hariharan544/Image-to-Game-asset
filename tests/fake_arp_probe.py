"""A stand-in for Auto-Rig Pro, only for tests/test_arp_probe_run.py: just enough of ARP's
operators and module functions for every item of the WP0 probe (`forge arp-probe`) to run here.

The test copies this file to <tmp>/auto_rig_pro/src/auto_rig.py, next to a blender_manifest.toml,
and imports it in the probe's own Blender process (never in the pytest process), so nothing it
registers leaks into other tests. Behaviour follows ARP 3.77.33 where the probe looks:
  - append_arp: armature "rig" of *_ref bones in a "Reference" bone collection; root_ref.x keeps
    'spine_count'; head_ref.x keeps 'facial': 0 in the human preset and 1 in the dog and horse
    presets (as Auto-Rig Pro 3.79.17's, docs/research/arp_3_79_probe.json); rig_preset "bird"
    kills Blender (the crash the probe must survive)
  - show_limb_params (EXEC) writes the options onto the limb's reference bones; a tail moved
    to another side takes that side's next free name (tail_00_ref_dupli_001.x -> tail_00_ref.l);
    on an arm it also stores the finger IK colour on hand_ref as an ID-property array, as ARP's
    set_fingers does (the human preset already has one, like ARP's dog preset has toe colours);
    load_limb_settings(self) reads them back from the selected reference bone, so the colour
    arrives as an edit-bone ID-property array that dies when Edit Mode ends
  - add_limb names a second limb of a kind <bone>_ref_dupli_001<side>
  - match_to_rig adds deform bones (name without '_ref'), c_root_master.x, and IK poles named
    'c_leg_pole' / 'c_arms_pole' + the limb's side (c_arms_pole_dupli_001.l for a second arm)
  - bind_to_rig prints "set real chin pos" when rig.data has 'arp_chin_pos_vec'; without it, it
    reports a heat-weighting failure and turns scene.arp_bind_scale_fix on, as ARP does
  - arp_export_fbx_panel writes the selection with Blender's FBX exporter
  - id.set_humanoid_rig / id.set_mped_rig exist (ARP registers them under "id.")
With FAKE_ARP_POLL in the environment, show_limb_params' check (poll) says no ("poll() failed,
context is incorrect") the way the director's Auto-Rig Pro 3.79.17 did on a fresh rig:
  - before_add_limb: on a rig no limb was added to yet, whatever is shown (the cause is unknown)
  - hidden_refs: append_arp hides the "Reference" bone collection, and the check wants a selected
    bone that can be seen (add_limb shows the collection again, as Auto-Rig Pro does): the cause
    Forge guesses, which showing the reference bones first fixes
"""

from __future__ import annotations

import os

import bpy
from mathutils import Vector

POLL = os.environ.get("FAKE_ARP_POLL", "")

LIMBS = [("arm.l", "Arm (Left)", ""), ("arm.r", "Arm (Right)", ""), ("ears", "Ears", ""),
         ("head", "Head", ""), ("leg.l", "Leg (Left)", ""), ("leg.r", "Leg (Right)", ""),
         ("spine", "Spine", ""), ("tail", "Tail", ""), ("spline_ik", "Chain: Spline IK", ""),
         ("kilt", "Clothes: Kilt", "")]


def _human():
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
    return B


def _new_bones(ad, bones: dict, deform: bool = False) -> None:
    eb = ad.edit_bones
    coll = ad.collections.get("Reference") or ad.collections.new("Reference")
    for n, (h, t, _p) in bones.items():
        b = eb.get(n) or eb.new(n)
        b.head, b.tail, b.use_deform = Vector(h), Vector(t), deform
        if "_ref" in n:
            coll.assign(b)
    for n, (_h, _t, p) in bones.items():
        if p:
            eb[n].parent = eb[p]


def _side(name: str) -> str:
    return name[-12:] if "_dupli_" in name else name[-2:]


class Limb_Sides:
    def get_multi_limbs(self):
        rig = bpy.context.active_object
        for k in ("arm", "leg", "head", "ear", "tail", "spine"):
            setattr(self, k + "_sides", [])
        first = {"shoulder_ref": "arm", "thigh_ref": "leg", "head_ref": "head", "ear_01_ref": "ear",
                 "tail_00_ref": "tail", "root_ref": "spine"}
        for b in rig.data.bones:
            for stem, k in first.items():
                if b.name.startswith(stem + ".") or b.name.startswith(stem + "_dupli"):
                    getattr(self, k + "_sides").append(_side(b.name))


limb_sides = Limb_Sides()


def check_humanoid_limbs():
    rig = bpy.context.active_object
    limb_sides.get_multi_limbs()
    if bpy.context.scene.arp_export_rig_type != "HUMANOID":
        return True
    root = rig.data.bones.get("root_ref.x")
    spine = root["spine_count"] if root is not None and "spine_count" in root.keys() else 0
    return not (len(limb_sides.leg_sides) > 2 or len(limb_sides.ear_sides) > 2 or spine < 1
                or rig.data.bones.get("c_root_master.x") is None)


def load_limb_settings(self):
    rig = bpy.context.active_object
    b = rig.data.edit_bones.active
    self.side = _side(b.name)
    stem = b.name.split("_")[0]
    kind = {"arm": "arm", "shoulder": "arm", "thigh": "leg", "leg": "leg", "ear": "ear", "tail": "tail",
            "neck": "neck", "spine": "spine", "root": "spine", "head": "head"}.get(stem, "")
    self.limb_type = kind
    keys = {"arm": "hand_ref", "tail": "tail_00_ref", "neck": "neck_ref", "head": "head_ref", "ear": "ear_01_ref"}
    src = rig.data.edit_bones.get(keys.get(kind, "") + self.side)
    if src is not None:
        for k in src.keys():
            if hasattr(self, k):
                setattr(self, k, src[k])
    if kind == "tail":
        self.tail_side = self.side[-2:]


class FAKE_OT_append_arp(bpy.types.Operator):
    bl_idname = "arp.append_arp"
    bl_label = "append"
    rig_preset: bpy.props.StringProperty(default="")
    preset_description: bpy.props.StringProperty(default="")

    def execute(self, context):
        if self.rig_preset == "bird":
            print("Blender 5, loading Blender 4.4 bird armature...", flush=True)
            os._exit(3)                                     # what the real bird.blend did on Blender 5
        bones = _human() if self.rig_preset == "human" else \
            {k: v for k, v in _human().items() if not k.startswith(("shoulder", "arm_", "forearm", "hand"))}
        if self.rig_preset == "free":
            bones = {"root_ref.x": ((0, 0, 0), (0, 0, 0.2), None)}
        ad = bpy.data.armatures.new("rig")
        o = bpy.data.objects.new("rig", ad)
        col = bpy.data.collections.new("rig_collection")
        context.scene.collection.children.link(col)
        col.objects.link(o)
        context.view_layer.objects.active = o
        bpy.ops.object.mode_set(mode="EDIT")
        _new_bones(ad, bones)
        if "root_ref.x" in ad.edit_bones and self.rig_preset == "human":
            ad.edit_bones["root_ref.x"]["spine_count"] = 2
            for s in "lr":
                ad.edit_bones[f"hand_ref.{s}"]["fingers_ik_color"] = [0.8, 0.432, 0.0]
        if "head_ref.x" in ad.edit_bones:               # face bones: off in the human preset only
            ad.edit_bones["head_ref.x"]["facial"] = 0 if self.rig_preset == "human" else 1
        bpy.ops.object.mode_set(mode="OBJECT")
        if POLL == "hidden_refs":
            ad.collections["Reference"].is_visible = False
        o["arp_rig_type"] = self.rig_preset
        print(f"appended {self.rig_preset}")
        return {"FINISHED"}


class FAKE_OT_show_limb_params(bpy.types.Operator):
    bl_idname = "arp.show_limb_params"
    bl_label = "limb params"
    limb_type: bpy.props.StringProperty(default="")
    side: bpy.props.StringProperty(default="")
    load_settings_when_exec: bpy.props.BoolProperty(default=False)
    reset_to_default_settings: bpy.props.BoolProperty(default=True)
    arm_show_part: bpy.props.EnumProperty(items=(("MAIN", "Main", ""), ("FINGERS", "Fingers", "")))
    finger_thumb: bpy.props.BoolProperty(default=True)
    finger_index: bpy.props.BoolProperty(default=True)
    finger_middle: bpy.props.BoolProperty(default=True)
    finger_ring: bpy.props.BoolProperty(default=True)
    finger_pinky: bpy.props.BoolProperty(default=True)
    fingers_ik_color: bpy.props.FloatVectorProperty(subtype="COLOR_GAMMA", default=(0.8, 0.432, 0.0))
    toes_thumb: bpy.props.BoolProperty(default=True)
    three_bones_leg: bpy.props.BoolProperty(default=False)
    arm_wings: bpy.props.BoolProperty(default=False)
    spine_count: bpy.props.IntProperty(default=3, min=1, max=64)
    neck_count: bpy.props.IntProperty(default=1, min=1, max=16)
    ear_count: bpy.props.IntProperty(default=2, min=1, max=16)
    tail_count: bpy.props.IntProperty(default=4, min=1, max=64)
    tail_side: bpy.props.EnumProperty(items=((".x", "Middle", ""), (".l", "Left", ""), (".r", "Right", "")))
    tail_name: bpy.props.StringProperty(default="tail")
    facial: bpy.props.BoolProperty(default=True)
    facial_mouth: bpy.props.BoolProperty(default=True)

    @classmethod
    def poll(cls, context):
        rig = context.active_object
        if POLL == "before_add_limb":
            return rig is not None and bool(rig.get("fake_limb_added"))
        if POLL == "hidden_refs":
            return rig is not None and rig.mode == "EDIT" and any(
                b.select and not b.hide and all(c.is_visible for c in b.collections) for b in rig.data.edit_bones)
        return True

    def execute(self, context):
        rig = context.active_object
        eb = rig.data.edit_bones
        if self.load_settings_when_exec:
            load_limb_settings(self)
        owner = {"arm": "hand_ref", "tail": "tail_00_ref", "neck": "neck_ref", "head": "head_ref",
                 "ear": "ear_01_ref"}.get(self.limb_type)
        b = eb.get((owner or "") + self.side)
        if b is None:
            return {"CANCELLED"}
        if self.limb_type == "arm":
            for k in ("finger_thumb", "finger_index", "finger_middle", "finger_ring", "finger_pinky", "arm_wings"):
                b[k] = getattr(self, k)
            b["fingers_ik_color"] = self.fingers_ik_color      # an ID-property array, like set_fingers
        elif self.limb_type == "neck":
            b["neck_count"] = self.neck_count
        elif self.limb_type == "head":
            b["facial"] = self.facial
        elif self.limb_type == "tail":
            b["tail_count"] = self.tail_count
            if self.tail_side != self.side[-2:]:          # another side: the next free id there
                taken = any(t.name.startswith("tail_00_ref") and t.name.endswith(self.tail_side) for t in eb)
                new_side = ("_dupli_001" if taken else "") + self.tail_side
                for t in [t for t in eb if t.name.startswith("tail_") and t.name.endswith(self.side)]:
                    t.name = t.name[:-len(self.side)] + new_side
        return {"FINISHED"}


class FAKE_OT_add_limb(bpy.types.Operator):
    bl_idname = "arp.add_limb"
    bl_label = "add limb"
    limbs = LIMBS
    limbs_presets: bpy.props.StringProperty(default="")

    def execute(self, context):
        rig = context.active_object
        rig["fake_limb_added"] = True
        if "Reference" in rig.data.collections:          # Auto-Rig Pro shows the reference bones
            rig.data.collections["Reference"].is_visible = True
        bpy.ops.object.mode_set(mode="EDIT")
        ad = rig.data
        kind = self.limbs_presets
        stems = {"tail": "tail_00_ref", "ears": "ear_01_ref", "arm.l": "shoulder_ref", "spline_ik": "spline_01_ref",
                 "kilt": "kilt_01_ref"}
        exists = any(b.name.startswith(stems.get(kind, "?")) for b in ad.edit_bones)
        tag = "_dupli_001" if exists else ""
        if exists and any("_dupli_001" in b.name and b.name.startswith(stems[kind]) for b in ad.edit_bones):
            tag = "_dupli_002"
        if kind == "tail":
            bones = {f"tail_{i:02d}_ref{tag}.x": ((0, 0.1 + 0.1 * i, 0.9), (0, 0.2 + 0.1 * i, 0.9),
                                                  "root_ref.x" if i == 0 else f"tail_{i - 1:02d}_ref{tag}.x")
                     for i in range(4)}
        elif kind == "ears":
            bones = {f"ear_01_ref{tag}.{s}": ((0.1 * x, 0, 1.7), (0.2 * x, 0, 1.7), "head_ref.x")
                     for s, x in (("l", 1), ("r", -1))}
        elif kind == "arm.l":
            bones = {f"shoulder_ref{tag}.l": ((0.05, 0, 1.2), (0.15, 0, 1.2), "spine_02_ref.x"),
                     f"arm_ref{tag}.l": ((0.15, 0, 1.2), (0.45, 0, 1.2), f"shoulder_ref{tag}.l"),
                     f"hand_ref{tag}.l": ((0.45, 0, 1.2), (0.55, 0, 1.2), f"arm_ref{tag}.l")}
        elif kind == "spline_ik":
            bones = {f"spline_{i:02d}_ref{tag}.x": ((0, -0.1, 1.0 + 0.1 * i), (0, -0.1, 1.1 + 0.1 * i),
                                                    "root_ref.x" if i == 1 else f"spline_{i - 1:02d}_ref{tag}.x")
                     for i in range(1, 5)}
        elif kind == "kilt":
            bones = {f"kilt_01_ref{tag}.l": ((0.1, 0, 0.85), (0.1, 0, 0.6), "root_ref.x")}
        else:
            bones = {}
        _new_bones(ad, bones)
        return {"FINISHED"}


class FAKE_OT_disable_limb(bpy.types.Operator):
    """Removes the limb of the selected reference bone: same stem, same dupli tag, same side."""
    bl_idname = "arp.disable_limb"
    bl_label = "disable limb"

    def execute(self, context):
        rig = context.active_object
        bpy.ops.object.mode_set(mode="EDIT")
        eb = rig.data.edit_bones
        act = eb.active
        if act is None or "_ref" not in act.name:
            self.report({"ERROR"}, "select a reference bone")
            return {"CANCELLED"}
        stem = act.name.split("_ref")[0].rsplit("_", 1)[0]
        rest = act.name.split("_ref", 1)[1]
        for b in [b for b in eb if b.name.startswith(stem + "_") and "_ref" in b.name
                  and b.name.split("_ref", 1)[1] == rest]:
            eb.remove(b)
        return {"FINISHED"}


class FAKE_OT_match_to_rig(bpy.types.Operator):
    bl_idname = "arp.match_to_rig"
    bl_label = "match"

    def execute(self, context):
        rig = context.active_object
        bpy.ops.object.mode_set(mode="EDIT")
        eb = rig.data.edit_bones
        refs = [b for b in eb if "_ref" in b.name]
        out = {"c_root_master.x": ((0, 0, 0.9), (0, 0, 1.0), None)}
        for b in refs:
            n = b.name.replace("_ref", "")
            p = b.parent.name.replace("_ref", "") if b.parent is not None else "c_root_master.x"
            out[n] = (tuple(b.head), tuple(b.tail), p)
            if b.name.startswith("hand_ref") and b.get("arm_wings"):
                out["c_arm_feather_01" + _side(b.name)] = (tuple(b.head), tuple(b.tail), n)
        legs = [_side(b.name) for b in refs if b.name.startswith("thigh_ref")]
        arms = [_side(b.name) for b in refs if b.name.startswith("shoulder_ref")]
        for s in legs:
            x = -1 if s.endswith(".r") else 1
            out["c_leg_pole" + s] = ((0.1 * x, -0.5, 0.5), (0.1 * x, -0.6, 0.5), "c_root_master.x")
        for s in arms:
            x = -1 if s.endswith(".r") else 1
            out["c_arms_pole" + s] = ((0.45 * x, 0.5, 1.4), (0.45 * x, 0.6, 1.4), "c_root_master.x")
        for n, (h, t, p) in out.items():
            b = eb.get(n) or eb.new(n)
            b.head, b.tail = Vector(h), Vector(t)
            b.use_deform = not n.startswith("c_")
        for n, (_h, _t, p) in out.items():
            if p and p in eb:
                eb[n].parent = eb[p]
        bpy.ops.object.mode_set(mode="POSE")
        for owner, target, pole, sides in (("leg", "foot", "c_leg_pole", legs), ("forearm", "hand", "c_arms_pole", arms)):
            for s in sides:
                pb = rig.pose.bones.get(owner + s) or rig.pose.bones.get("arm" + s)
                if pb is not None:
                    c = pb.constraints.new("IK")
                    c.target, c.subtarget = rig, target + s
                    c.pole_target, c.pole_subtarget = rig, pole + s
        bpy.ops.object.mode_set(mode="OBJECT")
        return {"FINISHED"}


class FAKE_OT_bind_to_rig(bpy.types.Operator):
    bl_idname = "arp.bind_to_rig"
    bl_label = "bind"

    def execute(self, context):
        sc = context.scene
        rig = context.active_object
        meshes = [o for o in context.selected_objects if o.type == "MESH"]
        chin = "arp_chin_pos_vec" in rig.data.keys()
        print("  set real chin pos" if chin else "  set approximate chin pos")
        if not chin and sc.arp_bind_engine == "HEAT_MAP" and not sc.arp_bind_scale_fix:
            print("Warning: Bone Heat Weighting: failed to find solution for one or more bones")
            sc.arp_bind_scale_fix = True                    # ARP leaves it on and asks to bind again
        bpy.ops.object.parent_set(type="ARMATURE_AUTO")
        for o in meshes:
            m = next(m for m in o.modifiers if m.type == "ARMATURE" and m.object == rig)
            m.use_deform_preserve_volume = sc.arp_bind_preserve
            vg = o.vertex_groups.get("head.x")
            if chin and vg is not None:                     # the chin moves the jaw weights
                for v in o.data.vertices:
                    if v.co.z > 1.45:
                        vg.add([v.index], 1.0, "REPLACE")
        return {"FINISHED"}


class FAKE_OT_export_fbx_panel(bpy.types.Operator):
    bl_idname = "arp.arp_export_fbx_panel"
    bl_label = "export"
    filepath: bpy.props.StringProperty(default="untitled")

    def execute(self, context):
        if context.scene.arp_export_rig_type == "HUMANOID" and not check_humanoid_limbs():
            print("This is not a humanoid rig")
            return {"FINISHED"}
        bpy.ops.export_scene.fbx(filepath=self.filepath, use_selection=True, add_leaf_bones=False)
        return {"FINISHED"}


class FAKE_OT_set_humanoid_rig(bpy.types.Operator):
    bl_idname = "id.set_humanoid_rig"
    bl_label = "set_humanoid_rig"

    def execute(self, context):
        return {"FINISHED"}


class FAKE_OT_set_mped_rig(bpy.types.Operator):
    bl_idname = "id.set_mped_rig"
    bl_label = "set_mped_rig"

    def execute(self, context):
        return {"FINISHED"}


CLASSES = (FAKE_OT_append_arp, FAKE_OT_show_limb_params, FAKE_OT_add_limb, FAKE_OT_disable_limb, FAKE_OT_match_to_rig,
           FAKE_OT_bind_to_rig, FAKE_OT_export_fbx_panel, FAKE_OT_set_humanoid_rig, FAKE_OT_set_mped_rig)
ENUMS = {"arp_bind_engine": ("HEAT_MAP", "PSEUDO_VOXELS", "VHDS"),
         "arp_engine_type": ("UNITY", "UNREAL", "GODOT"),
         "arp_export_rig_type": ("HUMANOID", "UNIVERSAL")}
BOOLS = {"arp_bind_preserve": True, "arp_bind_scale_fix": False, "arp_bind_chin": True, "arp_rename_for_ue": False,
         "arp_mannequin_axes": False, "arp_ue4": False, "arp_ge_sel_only": False}


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)
    for k, items in ENUMS.items():
        setattr(bpy.types.Scene, k, bpy.props.EnumProperty(items=[(i, i, "") for i in items]))
    for k, v in BOOLS.items():
        setattr(bpy.types.Scene, k, bpy.props.BoolProperty(default=v))

