"""A stand-in for UVgami that behaves like the real add-on (2.5.0, read from its GPL source):
uvgami.start takes the selected meshes and returns at once; a job manager in
<module>.src.unwrap.manager has is_active True until the session ends; with transfer_uvs the
UVs land on the original objects. Tests finish the job with deliver()."""

from __future__ import annotations

import sys
import types

import bpy

MOD = "fake_uvgami.src.unwrap.manager"


class _Manager:
    def __init__(self):
        self.is_active = False
        self.pieces_still_arriving = 0
        self.preparing = []
        self.jobs = []
        self.seen_settings = {}


class _Props(bpy.types.PropertyGroup):
    engine: bpy.props.StringProperty(default="OPTCUTS")
    transfer_uvs: bpy.props.BoolProperty(default=False)
    pack_after_unwrap: bpy.props.BoolProperty(default=True)
    symmetry: bpy.props.BoolProperty(default=True)
    stack_similar: bpy.props.BoolProperty(default=False)
    keep_quads: bpy.props.BoolProperty(default=True)
    unwrap_timeout: bpy.props.IntProperty(default=60)
    use_weights: bpy.props.BoolProperty(default=False)


class UVGAMI_OT_start(bpy.types.Operator):
    bl_idname = "uvgami.start"
    bl_label = "Unwrap"

    def execute(self, context):
        m = manager()
        p = context.scene.uvgami
        m.seen_settings = {k: getattr(p, k) for k in ("transfer_uvs", "pack_after_unwrap", "symmetry",
                                                     "stack_similar", "use_weights")}
        m.jobs = [o.name for o in context.selected_objects if o.type == "MESH"]
        m.is_active = True
        return {"FINISHED"}


class UVGAMI_OT_cancel_all(bpy.types.Operator):
    bl_idname = "uvgami.cancel_all"
    bl_label = "Cancel All"

    def execute(self, context):
        manager().is_active = False
        return {"FINISHED"}


def manager():
    return sys.modules[MOD].manager


def install():
    if MOD not in sys.modules:
        mod = types.ModuleType(MOD)
        mod.manager = _Manager()
        sys.modules[MOD] = mod
    sys.modules[MOD].manager = _Manager()
    if not hasattr(bpy.types.Scene, "uvgami"):
        bpy.utils.register_class(_Props)
        bpy.types.Scene.uvgami = bpy.props.PointerProperty(type=_Props)
        bpy.utils.register_class(UVGAMI_OT_start)
        bpy.utils.register_class(UVGAMI_OT_cancel_all)
    return manager()


def uninstall():
    if hasattr(bpy.types.Scene, "uvgami"):
        del bpy.types.Scene.uvgami
        bpy.utils.unregister_class(UVGAMI_OT_start)
        bpy.utils.unregister_class(UVGAMI_OT_cancel_all)
        bpy.utils.unregister_class(_Props)
    sys.modules.pop(MOD, None)


def deliver(fail=()):
    """The engine finishes: UVs onto the originals (transfer_uvs), except the failed ones."""
    m = manager()
    for name in m.jobs:
        o = bpy.data.objects.get(name)
        if o is None or name in fail:
            continue
        for x in bpy.context.view_layer.objects:
            x.select_set(False)
        o.select_set(True)
        bpy.context.view_layer.objects.active = o
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.uv.smart_project(angle_limit=1.15)
        bpy.ops.object.mode_set(mode="OBJECT")
    m.is_active = False
