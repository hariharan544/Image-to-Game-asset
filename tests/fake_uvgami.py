"""A stand-in for UVgami that behaves like the real add-on (2.5.0, read from its GPL source):
uvgami.start takes the selected meshes and returns at once; a job manager in
<module>.src.unwrap.manager has is_active True until the session ends; with transfer_uvs the
UVs land on the original objects. Tests finish the job with deliver().

Engines as in <module>.src.engines: OPTCUTS / PARTUV / XATLAS with their enum values and
supports_* flags, installed_engines() over the downloaded ones (set_installed), and the
Scene.uvgami.engine enum lists only those, with UVgami's own get/set (a stored value that is
not downloaded reads as the first downloaded one). PartUV's split (props.partuv.segmentation)
offers AI only when the AI part is downloaded (set_ai). Each engine flattens differently
(RESULTS), so the engines give measurably different UVs. Nothing here downloads or runs a real
engine."""

from __future__ import annotations

import math
import sys
import types

import bpy

MOD = "fake_uvgami.src.unwrap.manager"
ENG = "fake_uvgami.src.engines"
PARTUV = "fake_uvgami.src.engines.partuv"

# what each fake engine does to the mesh: (Blender projection, smart-project angle)
# OptCuts: more pieces, little stretch; PartUV: one piece per part, more stretch; xatlas: many
# small pieces, least stretch, long seams
DEFAULT_RESULTS = {"OPTCUTS": ("smart", 50), "PARTUV": ("sphere", 0), "XATLAS": ("smart", 30)}
STATE = {"installed": {"OPTCUTS"}, "ai": False, "auto": False, "results": dict(DEFAULT_RESULTS),
         "refuse": set(), "crash": set(), "skip": {}}     # skip: {engine: {object names it gives nothing}}


class _Engine:
    def __init__(self, eid, label, value, **flags):
        self.id, self.label, self.enum_value = eid, label, value
        self.description = label
        self.supports_guided = False
        self.supports_painted_islands = False
        self.supports_regions = True
        self.supports_material_seams = True
        self.supports_keep_quads = True
        for k, v in flags.items():
            setattr(self, k, v)

    def paint_is_seam_cost(self, props):
        return props.use_weights and self.supports_guided and not self.supports_painted_islands

    def paints_islands(self, props):
        return props.use_weights and self.supports_painted_islands


def _engines():
    # the flags of UVgami 2.5.0: every engine paints islands, OptCuts is also "guided"
    return {"OPTCUTS": _Engine("OPTCUTS", "Optcuts", 0, supports_guided=True, supports_painted_islands=True),
            "PARTUV": _Engine("PARTUV", "PartUV", 1, supports_painted_islands=True),
            "XATLAS": _Engine("XATLAS", "xatlas", 2, supports_painted_islands=True)}


ENGINES = _engines()


def installed_engines():
    return [e for e in ENGINES.values() if e.id in STATE["installed"]]


def active_engine(engine_id):
    e = ENGINES.get(engine_id)
    return e if e is not None and e in installed_engines() else None


def is_ai_segmentation_available():
    return bool(STATE["ai"])


# Blender needs dynamic enum strings kept alive
_ENGINE_ITEMS = {e.id: (e.id, e.label, e.description, e.enum_value) for e in ENGINES.values()}
_NO_ENGINE = ("NONE", "No engine installed", "", 0)
_GEOMETRIC = ("GEOMETRIC", "Geometric", "", "", 0)
_AI = ("AI", "AI", "", "", 1)
_TREE = ("TREE", "Tree", "", "", 2)


def _engine_items(self, context):
    inst = installed_engines()
    return [_ENGINE_ITEMS[e.id] for e in inst] if inst else [_NO_ENGINE]


def _engine_get(self):
    stored = self.get("engine", -1)
    inst = installed_engines()
    if any(e.enum_value == stored for e in inst):
        return stored
    return inst[0].enum_value if inst else 0


def _engine_set(self, value):
    self["engine"] = value


def _split_items(self, context):
    return [_GEOMETRIC, _TREE, _AI] if STATE["ai"] else [_GEOMETRIC, _TREE]


def _split_get(self):
    stored = self.get("segmentation", 1)
    return 2 if stored == 1 and not STATE["ai"] else stored


def _split_set(self, value):
    self["segmentation"] = value


class _PartUV(bpy.types.PropertyGroup):
    segmentation: bpy.props.EnumProperty(items=_split_items, get=_split_get, set=_split_set)


class _OptCuts(bpy.types.PropertyGroup):
    mode: bpy.props.EnumProperty(items=(("AUTO", "Auto", ""), ("ORGANIC", "Organic", ""),
                                        ("HARD", "Hard Surface", "")), default="AUTO")


class _Props(bpy.types.PropertyGroup):
    engine: bpy.props.EnumProperty(items=_engine_items, get=_engine_get, set=_engine_set)
    priority: bpy.props.EnumProperty(items=(("LESS_STRETCH", "Less Stretch", ""), ("BALANCED", "Balanced", ""),
                                            ("FEWER_SEAMS", "Fewer Seams", "")), default="BALANCED")
    split_regions: bpy.props.BoolProperty(default=True)
    import_uvs: bpy.props.BoolProperty(default=False)
    material_seams: bpy.props.BoolProperty(default=False)
    transfer_uvs: bpy.props.BoolProperty(default=False)
    pack_after_unwrap: bpy.props.BoolProperty(default=True)
    symmetry: bpy.props.BoolProperty(default=True)
    stack_similar: bpy.props.BoolProperty(default=False)
    keep_quads: bpy.props.BoolProperty(default=True)
    unwrap_timeout: bpy.props.IntProperty(default=60)
    use_weights: bpy.props.BoolProperty(default=False)
    auto_grid: bpy.props.BoolProperty(default=False)
    partuv: bpy.props.PointerProperty(type=_PartUV)
    optcuts: bpy.props.PointerProperty(type=_OptCuts)


class _Snapshot:
    """What the real manager keeps: a copy of the settings at start (SettingsCopy)."""
    def __init__(self, p):
        for k in ("engine", "split_regions", "material_seams", "use_weights", "keep_quads", "import_uvs"):
            setattr(self, k, getattr(p, k))
        self.partuv = types.SimpleNamespace(segmentation=p.partuv.segmentation)


class _Manager:
    def __init__(self):
        self.is_active = False
        self.pieces_still_arriving = 0
        self.preparing = []
        self.jobs = []
        self.engine = None
        self.props = None
        self.seen_settings = {}
        self.seen_meshes = {}
        self.starts = []           # every session: engine, settings and each mesh as it was given
        self.cancelled = 0
        self.transfer_uv_failed = False
        self.transfer_uv_fail_detail = ""
        self.error_messages = []   # an engine's own stop message ("PartUV could not start (...)")
        self.error_code = 0


SEEN_PREFIX = "fake_seen_"      # the copies of what UVgami was given (not Forge's)
SEEN = ("transfer_uvs", "pack_after_unwrap", "symmetry", "stack_similar", "use_weights", "auto_grid",
        "split_regions", "material_seams", "import_uvs", "keep_quads")


class UVGAMI_OT_start(bpy.types.Operator):
    bl_idname = "uvgami.start"
    bl_label = "Unwrap"

    def execute(self, context):
        import numpy as np
        m = manager()
        p = context.scene.uvgami
        engine = active_engine(p.engine)
        if engine is None:
            self.report({"ERROR"}, "The selected engine is not installed")
            return {"CANCELLED"}
        if engine.id in STATE["crash"]:
            raise RuntimeError(f"{engine.label} crashed")
        if engine.id in STATE["refuse"]:
            self.report({"ERROR"}, f"{engine.label} could not start")
            return {"CANCELLED"}
        m.seen_settings = {k: getattr(p, k) for k in SEEN}
        m.seen_settings.update(engine=p.engine, segmentation=p.partuv.segmentation, optcuts_mode=p.optcuts.mode)
        m.engine, m.props = engine, _Snapshot(p)
        m.jobs = [o.name for o in context.selected_objects if o.type == "MESH"]
        for me in m.seen_meshes.values():                 # (only the last session's copies are kept)
            if me.name in bpy.data.meshes and me.users == 0:
                bpy.data.meshes.remove(me)
        m.seen_meshes = {n: bpy.data.objects[n].data.copy() for n in m.jobs}
        for n, me in m.seen_meshes.items():
            me.name = SEEN_PREFIX + n
        uvs = {}
        for n in m.jobs:
            me = bpy.data.objects[n].data
            a = np.zeros(len(me.loops) * 2, np.float32)
            if me.uv_layers.active is not None:
                me.uv_layers.active.data.foreach_get("uv", a)
            uvs[n] = a
        m.starts.append({"engine": engine.id, "settings": dict(m.seen_settings), "uvs": uvs,
                         "meshes": {n: bpy.data.objects[n].data.name for n in m.jobs},
                         "groups": {n: [g.name for g in bpy.data.objects[n].vertex_groups] for n in m.jobs},
                         "faces": {n: len(bpy.data.objects[n].data.polygons) for n in m.jobs}})
        m.transfer_uv_failed, m.transfer_uv_fail_detail = False, ""      # (a new session)
        m.error_messages, m.error_code = [], 0
        m.is_active = True
        if STATE["auto"]:
            deliver()
        return {"FINISHED"}


class UVGAMI_OT_cancel_all(bpy.types.Operator):
    bl_idname = "uvgami.cancel_all"
    bl_label = "Cancel All"

    def execute(self, context):
        manager().is_active = False
        manager().cancelled += 1
        return {"FINISHED"}


def manager():
    return sys.modules[MOD].manager


def set_installed(ids=("OPTCUTS",)):
    STATE["installed"] = set(ids)


def set_ai(on: bool):
    STATE["ai"] = bool(on)


def install(installed=("OPTCUTS",), ai=False, auto=False):
    STATE.update(installed=set(installed), ai=bool(ai), auto=bool(auto), results=dict(DEFAULT_RESULTS),
                 refuse=set(), crash=set(), skip={})
    global ENGINES
    ENGINES = _engines()
    mod = sys.modules.get(MOD) or types.ModuleType(MOD)
    mod.manager = _Manager()
    sys.modules[MOD] = mod
    eng = types.ModuleType(ENG)
    eng.ENGINES = ENGINES
    eng.installed_engines = installed_engines
    eng.active_engine = active_engine
    sys.modules[ENG] = eng
    part = types.ModuleType(PARTUV)
    part.is_ai_segmentation_available = is_ai_segmentation_available
    sys.modules[PARTUV] = part
    if not hasattr(bpy.types.Scene, "uvgami"):
        for c in (_PartUV, _OptCuts, _Props, UVGAMI_OT_start, UVGAMI_OT_cancel_all):
            bpy.utils.register_class(c)
        bpy.types.Scene.uvgami = bpy.props.PointerProperty(type=_Props)
    return manager()


def uninstall():
    if hasattr(bpy.types.Scene, "uvgami"):
        del bpy.types.Scene.uvgami
        for c in (UVGAMI_OT_cancel_all, UVGAMI_OT_start, _Props, _OptCuts, _PartUV):
            bpy.utils.unregister_class(c)
    for name in (MOD, ENG, PARTUV):
        sys.modules.pop(name, None)


def _collection(name):
    c = bpy.data.collections.get(name)
    if c is None:
        c = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(c)
    return c


def _flatten(o, how):
    kind, angle = how
    for x in bpy.context.view_layer.objects:
        x.select_set(False)
    o.select_set(True)
    bpy.context.view_layer.objects.active = o
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    if kind == "sphere":
        bpy.ops.uv.sphere_project()
    elif kind == "cube":
        bpy.ops.uv.cube_project()
    else:
        bpy.ops.uv.smart_project(angle_limit=math.radians(angle))
    bpy.ops.object.mode_set(mode="OBJECT")


def deliver(fail=(), transfer_fail=None, grid=False):
    """The engine finishes: UVs onto the originals (transfer_uvs), except the failed ones.
    transfer_fail {name: detail}: like the real add-on when it cannot put the UVs back - the
    original is hidden and the unwrapped copy is kept in 'UVgami Unwrapped'. grid: its Auto
    Grid material lands on the originals."""
    m = manager()
    eid = getattr(m.engine, "id", "OPTCUTS")
    how = STATE["results"].get(eid, ("smart", 66))
    fail = set(fail) | set(STATE["skip"].get(eid, ()))
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
        _flatten(o, how)
    m.is_active = False
