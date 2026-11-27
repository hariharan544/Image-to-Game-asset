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
        self.seen_meshes = {}
        self.transfer_uv_failed = False
        self.transfer_uv_fail_detail = ""


class _Props(bpy.types.PropertyGroup):
    engine: bpy.props.StringProperty(default="OPTCUTS")
    transfer_uvs: bpy.props.BoolProperty(default=False)
    pack_after_unwrap: bpy.props.BoolProperty(default=True)
    symmetry: bpy.props.BoolProperty(default=True)
    stack_similar: bpy.props.BoolProperty(default=False)
    keep_quads: bpy.props.BoolProperty(default=True)
    unwrap_timeout: bpy.props.IntProperty(default=60)
    use_weights: bpy.props.BoolProperty(default=False)
    auto_grid: bpy.props.BoolProperty(default=False)


class UVGAMI_OT_start(bpy.types.Operator):
    bl_idname = "uvgami.start"
    bl_label = "Unwrap"

    def execute(self, context):
        m = manager()
        p = context.scene.uvgami
        m.seen_settings = {k: getattr(p, k) for k in ("transfer_uvs", "pack_after_unwrap", "symmetry",
                                                     "stack_similar", "use_weights", "auto_grid")}
        m.jobs = [o.name for o in context.selected_objects if o.type == "MESH"]
        m.seen_meshes = {n: bpy.data.objects[n].data.copy() for n in m.jobs}
        m.transfer_uv_failed, m.transfer_uv_fail_detail = False, ""      # (a new session)
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


def _collection(name):
    c = bpy.data.collections.get(name)
    if c is None:
        c = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(c)
    return c


def deliver(fail=(), transfer_fail=None, grid=False):
    """The engine finishes: UVs onto the originals (transfer_uvs), except the failed ones.
    transfer_fail {name: detail}: like the real add-on when it cannot put the UVs back - the
    original is hidden and the unwrapped copy is kept in 'UVgami Unwrapped'. grid: its Auto
    Grid material lands on the originals."""
    m = manager()
    for name in m.jobs:
        o = bpy.data.objects.get(name)
        if o is None or name in fail:
            continue
        if transfer_fail and name in transfer_fail:
            copy = o.copy()
            copy.data = o.data.copy()
            copy.name = name + "_unwrapped"
            _collection("UVgami Unwrapped").objects.link(copy)
            o.hide_set(True)
            m.transfer_uv_failed, m.transfer_uv_fail_detail = True, transfer_fail[name]
            continue
        if grid:
            mat = bpy.data.materials.get("UVgami_grid") or bpy.data.materials.new("UVgami_grid")
            idx = [0] * len(o.data.polygons)
            o.data.polygons.foreach_get("material_index", idx)
            o.data["uvgami_material_indices"] = idx
            o.data.materials.append(mat)
            o.data.polygons.foreach_set("material_index", [len(o.data.materials) - 1] * len(idx))
        for x in bpy.context.view_layer.objects:
            x.select_set(False)
        o.select_set(True)
        bpy.context.view_layer.objects.active = o
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.uv.smart_project(angle_limit=1.15)
        bpy.ops.object.mode_set(mode="OBJECT")
    m.is_active = False
