"""A stand-in for the Quad Remesher add-on that behaves like the real one on the director's
PC: the operator returns at once, the engine works outside Blender, and later its result is
imported as a NEW object "Retopo_<input name>" into the active collection while the input is
hidden. Tests drive the import between the generator's yields (`engine.deliver()`)."""

from __future__ import annotations

import bpy


class _Props(bpy.types.PropertyGroup):
    target_count: bpy.props.IntProperty(default=5000)
    adaptive_size: bpy.props.FloatProperty(default=50.0)
    adapt_quad_count: bpy.props.BoolProperty(default=True)
    use_vertex_color: bpy.props.BoolProperty(default=False)
    use_materials: bpy.props.BoolProperty(default=False)
    use_normals: bpy.props.BoolProperty(default=False)
    autodetect_hard_edges: bool = bpy.props.BoolProperty(default=True)
    symmetry_x: bpy.props.BoolProperty(default=False)
    symmetry_y: bpy.props.BoolProperty(default=False)
    symmetry_z: bpy.props.BoolProperty(default=False)


class Engine:
    jobs: list = []
    name_limit = None          # e.g. 63: an engine that cuts long result names


class QREMESHER_OT_remesh(bpy.types.Operator):
    bl_idname = "qremesher.remesh"
    bl_label = "fake Quad Remesher"

    def execute(self, context):
        o = context.view_layer.objects.active
        # the engine takes a snapshot of the input and works on it outside Blender
        Engine.jobs.append((o.name, o.data.copy(), o.matrix_world.copy()))
        return {"FINISHED"}


def install():
    if not hasattr(bpy.types.Scene, "qremesher"):
        bpy.utils.register_class(_Props)
        bpy.types.Scene.qremesher = bpy.props.PointerProperty(type=_Props)
        bpy.utils.register_class(QREMESHER_OT_remesh)
    Engine.jobs.clear()
    return Engine


def deliver(remesh=None):
    """The engine finishes the oldest job: import its result like the real add-on (into the
    active collection, named after the input, the input hidden if it still exists)."""
    name, me, mw = Engine.jobs.pop(0)
    if remesh is not None:
        remesh(me)
    rname = "Retopo_" + name
    if Engine.name_limit:
        rname = rname[:Engine.name_limit]
    res = bpy.data.objects.new(rname, me)
    res.matrix_world = mw
    bpy.context.view_layer.active_layer_collection.collection.objects.link(res)
    src = bpy.data.objects.get(name)
    if src is not None:
        src.hide_set(True)                   # hide_input
    return res
