"""Forge - step by step: each stage runs in the director's own Blender and waits for Approve.

3D Viewport > Sidebar (N) > Forge > "Forge - step by step"
  Step 2  Assemble         collect the generated parts, size them, place them, mirror
  Step 3  Geometry repair  automatic: cracks, holes, floating bits, normals; optional weld
  Steps 4-9 follow (retopology, UVs, detail bake, colour texture, rig, export).
Every Approve saves the .blend and logs the decision (training data for the local AI reviewer).
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import bpy
from bpy.props import EnumProperty, FloatProperty, IntProperty, PointerProperty, StringProperty

from . import geometry as G

STATUS = [("todo", "To do", ""), ("review", "Waiting for you", ""), ("approved", "Approved", "")]
ICON = {"todo": "COLORSET_13_VEC", "review": "COLORSET_04_VEC", "approved": "COLORSET_03_VEC"}
OK_ICON, BAD_ICON = "COLORSET_03_VEC", "COLORSET_01_VEC"


KINDS = [("biped", "Biped character", "Stands on two legs: human, cartoon animal, robot"),
         ("quadruped", "Four-legged animal", "Dog, horse, bull on four legs"),
         ("creature", "Creature", "Wings, tentacles, many legs, mythical"),
         ("prop", "Prop", "Object, weapon, accessory"),
         ("vehicle", "Vehicle / machine", "Wheels, hard surface, moving parts")]
STYLES = [("cartoon", "Cartoon / stylized", ""), ("realistic", "Realistic", "")]
SIDES = [("auto", "Auto", "Mirror when the model is symmetric enough, from the better side"),
         ("left", "Left side", "Build both sides from the character's LEFT side (+X)"),
         ("right", "Right side", "Build both sides from the character's RIGHT side (-X)"),
         ("none", "No mirror", "Keep both sides as they are (asymmetric design)")]


# Step 5's unwrap engines (UVgami's ids); the numbers are what the .blend stores: never reuse one
UV_ENGINES = [("AUTO", "Auto", "The engine that won Compare engines for this model; OptCuts until you "
                               "compare", 0),
              ("OPTCUTS", "OptCuts", "Least stretch for the seam length. Can be slow on dense meshes", 1),
              ("PARTUV", "PartUV", "Splits the model into parts first: fewer islands, can be faster", 2),
              ("XATLAS", "xatlas", "Fast, made for lightmaps: many small islands", 3)]
_UV_ENGINE_ITEMS: dict = {}        # Blender needs the strings of a dynamic enum kept alive: every
                                   # variant is kept (a handful: downloaded or not)


def _uv_engine_items(self, context):
    """The engines, each marked when UVgami cannot use it now (not in this UVgami, not for this
    computer, not downloaded)."""
    try:
        from . import steps as S
        have = {e["id"]: e for e in S.uv_engines()}
    except Exception:                                     # noqa: BLE001
        have = {}
    items = [UV_ENGINES[0]]
    for eid, label, desc, n in UV_ENGINES[1:]:
        if eid not in have:
            label = f"{label} (not in this UVgami)" if have else label
        elif not have[eid].get("available", True):
            label = f"{label} (not for this computer)"
        elif not have[eid]["installed"]:
            label = f"{label} (not downloaded)"
        items.append((eid, label, desc, n))
    return _UV_ENGINE_ITEMS.setdefault(tuple(items), items)


PARTUV_SPLITS = [("AUTO", "Auto", "AI when PartUV's AI part is downloaded, else Tree"),
                 ("TREE", "Tree", "Splits the model into parts by shape. Nothing extra to download"),
                 ("GEOMETRIC", "Geometric", "Groups faces by direction. Faster, more seams"),
                 ("AI", "AI", "AI finds the parts. Needs PartUV's AI download (5 GB) and an NVIDIA card")]


class ForgeStageState(bpy.types.PropertyGroup):
    brief: EnumProperty(items=STATUS, default="todo")
    concept: StringProperty(name="Concept image", subtype="FILE_PATH",
                            description="The image the model was generated from (shown next to the model)")
    asset_kind: EnumProperty(name="What is it", items=KINDS, default="biped")
    art_style: EnumProperty(name="Style", items=STYLES, default="cartoon")
    symmetry: EnumProperty(name="Symmetry", items=SIDES, default="auto")
    assemble: EnumProperty(items=STATUS, default="todo")
    repair: EnumProperty(items=STATUS, default="todo")
    height_m: FloatProperty(name="Body height (m)", default=0.0, min=0.0, soft_max=10.0,
                            description="Real-world height of the body; 0 = keep the generated size")
    solid_res: IntProperty(name="Weld detail", default=400, min=64, max=2000,
                           description="Detail of the welded shell (higher = finer, heavier)")
    report: StringProperty(default="{}")          # JSON: part -> analysis after repair
    fixed: StringProperty(default="{}")           # JSON: part -> what the repair did
    # steps 4-9 (stages_late.py)
    retopo: EnumProperty(items=STATUS, default="todo")
    uv: EnumProperty(items=STATUS, default="todo")
    bake: EnumProperty(items=STATUS, default="todo")
    colour: EnumProperty(items=STATUS, default="todo")
    rig: EnumProperty(items=STATUS, default="todo")
    export: EnumProperty(items=STATUS, default="todo")
    budget: IntProperty(name="Triangles (Unreal)", default=30000, min=500, max=500000,
                        description="Triangle budget for the whole character in Unreal (all parts together)")
    budget_unity: IntProperty(name="Triangles (Unity)", default=8000, min=300, max=200000,
                              description="Triangle budget for the Unity mobile version")
    detail: FloatProperty(name="Detail focus", default=0.8, min=0.0, max=1.0,
                          description="How strongly quads move from flat areas (belly, back) to detail "
                                      "(eyes, mouth, nostrils, nails, hoof tips). 0 = even quads")
    tex_size: EnumProperty(name="Texture size", default="2048",
                           items=[("1024", "1K", ""), ("2048", "2K", ""), ("4096", "4K", "")])
    uv_engine: EnumProperty(name="Unwrap engine", items=_uv_engine_items,
                            description="The UVgami engine that cuts the seams in Step 5")
    partuv_split: EnumProperty(name="PartUV split", items=PARTUV_SPLITS, default="AUTO",
                               description="How PartUV splits the model into parts before it unwraps")
    uv_compare_rep: StringProperty(default="{}")  # Compare engines: the table and the winner (Auto's engine)
    rig_phase: StringProperty(default="")         # "" | "joints" | "built"
    anim_clip: EnumProperty(name="Sample animation", default="rom",
                            items=[("rom", "Range of motion", "Every joint to its limit: look for tearing"),
                                   ("walk", "Walk cycle", "A plain walk on the spot"),
                                   ("idle", "Idle (breathing)", "Breathing, a look around, a tail sway"),
                                   ("tail", "Tail and ears", "A wave down the tail, ear flicks")])
    busy: StringProperty(default="")             # unused since 1.2.1 (kept so old files load)
    error: StringProperty(default="")
    retopo_rep: StringProperty(default="{}")
    uv_rep: StringProperty(default="{}")
    bake_rep: StringProperty(default="{}")
    rig_rep: StringProperty(default="{}")
    anim_rep: StringProperty(default="{}")        # Step 8 automatic checks of the last clip
    export_rep: StringProperty(default="{}")


# ----------------------------------------------------------------------------- helpers

def _st(context):
    return context.scene.forge_stage


def _log(context, stage: str, decision: str, data: dict) -> None:
    """Append the decision next to the .blend (and in the Forge project when set up)."""
    rec = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "stage": stage, "decision": decision,
           "file": bpy.data.filepath, "data": data}
    targets = []
    if bpy.data.filepath:
        targets.append(Path(bpy.data.filepath).with_suffix(".forge_log.jsonl"))
    try:
        from . import project_dir
        proj = project_dir()
        if str(proj) not in ("", ".") and (proj / "forge").is_dir():
            targets.append(proj / "training" / "stage_decisions.jsonl")
    except Exception:
        pass
    for t in targets:
        try:
            t.parent.mkdir(parents=True, exist_ok=True)
            with open(t, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec) + "\n")
        except OSError:
            pass


def _save(op) -> None:
    """Save after an approval. A save problem must never undo or block the approval: when
    Blender cannot write its .blend1 backup (OneDrive or antivirus holding the file), save
    without the backup copy; if even that fails, say so and carry on."""
    if bpy.data.filepath:
        try:
            bpy.ops.wm.save_mainfile()
            return
        except RuntimeError as exc:
            first = str(exc)
        paths = bpy.context.preferences.filepaths
        old = paths.save_version
        try:
            paths.save_version = 0                  # no .blend1 backup this time
            bpy.ops.wm.save_mainfile()
            op.report({"WARNING"}, "Saved without the .blend1 backup copy (Blender could not "
                                   "write it; files inside OneDrive often cause this)")
        except RuntimeError as exc:
            op.report({"WARNING"}, f"Approved, but the file could not be saved: {exc or first}. "
                                   "Save with Ctrl+S, or Save As to a folder outside OneDrive")
        finally:
            paths.save_version = old
    else:
        op.report({"WARNING"}, "Approved. Save the file (Ctrl+S) to keep your progress")


def _object_mode(context) -> None:
    if context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")


def _parts(context):
    return G.mesh_parts(context.scene)


def _reanalyse(context) -> dict:
    st = _st(context)
    rep = {o.name: G.analyse(o) for o in _parts(context)}
    st.report = json.dumps(rep)
    return rep


# ----------------------------------------------------------------------------- step 2 operators

def place_concept(ref, img, parts: list) -> None:
    """Stand the concept beside the whole layout (body, arms and props), never overlapping it:
    as tall as the body, its right edge a clear gap left of the leftmost part."""
    body = G.body_of(parts) if parts else None
    if parts:
        bounds = [G.world_bounds(o) for o in parts]
        lo_x = min(b[0].x for b in bounds)
        blo, bhi = G.world_bounds(body or parts[0])
        height = max(bhi.z - blo.z, 1e-3)
        mid_z, mid_y = (blo.z + bhi.z) / 2, (blo.y + bhi.y) / 2
    else:
        lo_x, height, mid_z, mid_y = -1.0, 2.0, 1.0, 0.0
    iw, ih = (img.size[0], img.size[1]) if img.size[0] and img.size[1] else (1, 1)
    size = height * max(iw, ih) / ih            # the empty's size is the image's LONGER side
    width = size * iw / max(iw, ih)
    gap = 0.25 * height
    ref.empty_display_size = size
    ref.empty_image_offset = (-0.5, -0.5)       # centred on its location
    ref.location = (lo_x - gap - width / 2, mid_y, mid_z)
    ref.rotation_euler = (1.5708, 0.0, 0.0)     # facing the front view


class FORGE_OT_concept(bpy.types.Operator):
    bl_idname = "forge.stage_concept"
    bl_label = "Show concept next to the model"
    bl_description = "Put the concept image in the viewport, beside the model, to compare while you work"

    def execute(self, context):
        st = _st(context)
        path = bpy.path.abspath(st.concept)
        if not st.concept or not Path(path).exists():
            self.report({"ERROR"}, "Pick the concept image first")
            return {"CANCELLED"}
        img = bpy.data.images.load(path, check_existing=True)
        ref = bpy.data.objects.get("Forge concept") or bpy.data.objects.new("Forge concept", None)
        if ref.name not in context.scene.collection.objects:
            context.scene.collection.objects.link(ref)
        ref.empty_display_type = "IMAGE"
        ref.data = img
        place_concept(ref, img, _parts(context))
        return {"FINISHED"}


class FORGE_OT_approve_brief(bpy.types.Operator):
    bl_idname = "forge.stage_approve_brief"
    bl_label = "Approve brief"
    bl_description = "This is what we are making. Unlocks Assemble"

    def execute(self, context):
        st = _st(context)
        st.brief = "approved"
        _log(context, "brief", "approve", {"kind": st.asset_kind, "style": st.art_style,
                                           "symmetry": st.symmetry, "concept": st.concept})
        _save(self)
        return {"FINISHED"}


class FORGE_OT_collect(bpy.types.Operator):
    bl_idname = "forge.stage_collect"
    bl_label = "Collect selected parts"
    bl_description = ("Put the selected generated parts in the 'Forge Parts' collection: the biggest becomes "
                      "the body (feet on the floor, centred), new props are sized and lined up beside it")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        _object_mode(context)
        try:
            info = G.collect(list(context.selected_objects), _st(context).height_m)
        except RuntimeError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        st = _st(context)
        st.assemble = "review"
        st.repair = "todo"
        self.report({"INFO"}, f"Body: {info['body']}, {len(info['parts'])} parts. "
                              f"Now place the props on the body, then Approve layout")
        return {"FINISHED"}


class FORGE_OT_set_body(bpy.types.Operator):
    bl_idname = "forge.stage_set_body"
    bl_label = "This is the body"
    bl_description = "Use this part as the body (the others become props)"
    bl_options = {"REGISTER", "UNDO"}
    name: StringProperty()

    def execute(self, context):
        for o in _parts(context):
            o[G.ROLE] = "body" if o.name == self.name else "prop"
        return {"FINISHED"}


class FORGE_OT_select_part(bpy.types.Operator):
    bl_idname = "forge.stage_select_part"
    bl_label = "Select"
    bl_description = "Select this part and frame it in the viewport"
    name: StringProperty()

    def execute(self, context):
        _object_mode(context)
        o = bpy.data.objects.get(self.name)
        if not o:
            return {"CANCELLED"}
        for x in context.view_layer.objects:
            x.select_set(False)
        o.hide_set(False)
        o.select_set(True)
        context.view_layer.objects.active = o
        try:
            bpy.ops.view3d.view_selected()
        except RuntimeError:
            pass
        return {"FINISHED"}


class FORGE_OT_to_cursor(bpy.types.Operator):
    bl_idname = "forge.stage_to_cursor"
    bl_label = "Move to 3D cursor"
    bl_description = ("Move the selected part to the 3D cursor. Tip: Shift + right-click on the body "
                      "puts the cursor on its surface")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.active_object is not None and context.active_object.type == "MESH"

    def execute(self, context):
        _object_mode(context)
        G.move_to(context.active_object, context.scene.cursor.location.copy())
        return {"FINISHED"}


class FORGE_OT_mirror(bpy.types.Operator):
    bl_idname = "forge.stage_mirror"
    bl_label = "Mirror to other side"
    bl_description = "Make a copy of the selected part on the other side of the body (e.g. second wrist band)"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        o = context.active_object
        return o is not None and o.type == "MESH" and G.kind(o) == "prop"

    def execute(self, context):
        _object_mode(context)
        dup = G.mirror(context.active_object)
        self.report({"INFO"}, f"Made {dup.name}")
        return {"FINISHED"}


class FORGE_OT_approve_layout(bpy.types.Operator):
    bl_idname = "forge.stage_approve_layout"
    bl_label = "Approve layout"
    bl_description = "The parts are where they belong. Locks the layout and unlocks Geometry repair"

    def execute(self, context):
        _object_mode(context)
        parts = _parts(context)
        if not parts or not G.body_of(parts):
            self.report({"ERROR"}, "Collect the parts first")
            return {"CANCELLED"}
        G.finalize_layout(parts)
        st = _st(context)
        st.assemble = "approved"
        _log(context, "assemble", "approve",
             {"parts": {o.name: G.kind(o) for o in parts}, "height_m": st.height_m})
        _save(self)
        return {"FINISHED"}


class FORGE_OT_reopen(bpy.types.Operator):
    bl_idname = "forge.stage_reopen"
    bl_label = "Change"
    bl_description = "Re-open this step (later steps have to be approved again)"
    stage: StringProperty()

    def execute(self, context):
        from .stages_late import reopen
        reopen(_st(context), self.stage)
        return {"FINISHED"}


# ----------------------------------------------------------------------------- step 3 operators

class FORGE_OT_repair(bpy.types.Operator):
    bl_idname = "forge.stage_repair"
    bl_label = "Run automatic repair"
    bl_description = ("Weld cracks, remove floating bits and loose points, close holes, point faces "
                      "outward - on every part. The original is kept: Undo repair brings it back")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        _object_mode(context)
        st = _st(context)
        parts = _parts(context)
        wm = context.window_manager
        wm.progress_begin(0, len(parts))
        fixed = {}
        for i, o in enumerate(parts):
            fixed[o.name] = G.repair(o)
            wm.progress_update(i + 1)
        wm.progress_end()
        st.fixed = json.dumps(fixed)
        rep = _reanalyse(context)
        st.repair = "review"
        bad = [n for n, r in rep.items() if not r["ok"] or r["needs_weld"]]
        if bad:
            self.report({"WARNING"}, f"Still needs a look: {', '.join(bad)} (see the panel)")
        else:
            self.report({"INFO"}, "All parts are clean. Check them in the viewport, then Approve")
        return {"FINISHED"}


class FORGE_OT_weld(bpy.types.Operator):
    bl_idname = "forge.stage_weld"
    bl_label = "Weld into one solid"
    bl_description = ("Rebuild this part as one watertight shell: fixes every remaining hole, broken edge and "
                      "overlapping piece. The colour texture is lost here - step 7 paints the clean model")
    bl_options = {"REGISTER", "UNDO"}
    name: StringProperty()

    def execute(self, context):
        _object_mode(context)
        o = bpy.data.objects.get(self.name)
        if not o:
            return {"CANCELLED"}
        res = G.make_solid(o, _st(context).solid_res)
        fixed = json.loads(_st(context).fixed or "{}")
        fixed.setdefault(o.name, {})["welded_solid"] = True
        _st(context).fixed = json.dumps(fixed)
        _reanalyse(context)
        self.report({"INFO"}, f"{o.name}: one solid shell, {res['tris']:,} triangles")
        return {"FINISHED"}


class FORGE_OT_show_problems(bpy.types.Operator):
    bl_idname = "forge.stage_show_problems"
    bl_label = "Show problems"
    bl_description = "Open the part in Edit Mode with the problem edges selected and zoom to them"
    name: StringProperty()

    def execute(self, context):
        o = bpy.data.objects.get(self.name)
        if not o:
            return {"CANCELLED"}
        _object_mode(context)
        for x in context.view_layer.objects:
            x.select_set(False)
        o.hide_set(False)
        o.select_set(True)
        context.view_layer.objects.active = o
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_mode(type="EDGE")
        bpy.ops.mesh.select_all(action="DESELECT")
        bpy.ops.mesh.select_non_manifold()
        try:
            bpy.ops.view3d.view_selected()
        except RuntimeError:
            pass
        self.report({"INFO"}, "Selected = problem edges. Tab returns to Object Mode")
        return {"FINISHED"}


class FORGE_OT_normals_view(bpy.types.Operator):
    bl_idname = "forge.stage_normals_view"
    bl_label = "Check inside / outside"
    bl_description = "Toggle the face colour check: blue = facing out (good), red = inside out"

    def execute(self, context):
        for area in context.screen.areas:
            if area.type == "VIEW_3D":
                ov = area.spaces.active.overlay
                ov.show_face_orientation = not ov.show_face_orientation
        return {"FINISHED"}


class FORGE_OT_undo_repair(bpy.types.Operator):
    bl_idname = "forge.stage_undo_repair"
    bl_label = "Undo repair"
    bl_description = "Bring back every part exactly as it was before the repair"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        _object_mode(context)
        n = sum(G.restore(o) for o in _parts(context))
        st = _st(context)
        _log(context, "repair", "reject", {"report": json.loads(st.report or "{}")})
        st.repair = "todo"
        st.report = "{}"
        st.fixed = "{}"
        self.report({"INFO"}, f"Restored {n} parts")
        return {"FINISHED"}


class FORGE_OT_approve_repair(bpy.types.Operator):
    bl_idname = "forge.stage_approve_repair"
    bl_label = "Approve geometry"
    bl_description = "The parts look right. Unlocks retopology"

    def execute(self, context):
        _object_mode(context)
        st = _st(context)
        _log(context, "repair", "approve",
             {"report": json.loads(st.report or "{}"), "fixed": json.loads(st.fixed or "{}")})
        st.repair = "approved"
        _save(self)
        return {"FINISHED"}


# ----------------------------------------------------------------------------- panel

def _header(box, number: int, title: str, status: str, stage: str):
    row = box.row()
    row.label(text=f"Step {number} · {title}", icon=ICON[status])
    if status == "approved":
        op = row.operator("forge.stage_reopen", text="Change", icon="LOOP_BACK", emboss=False)
        op.stage = stage


class FORGE_PT_stages(bpy.types.Panel):
    bl_label = "Forge - step by step"
    bl_idname = "FORGE_PT_stages"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Forge"
    bl_order = 0

    def draw(self, context):
        st = _st(context)
        layout = self.layout
        parts = _parts(context)

        # ---------------------------------------------------------------- step 1
        box = layout.box()
        _header(box, 1, "Brief", st.brief, "brief")
        if st.brief != "approved":
            c = box.column(align=True)
            c.label(text="What are we making?", icon="QUESTION")
            box.prop(st, "concept")
            box.prop(st, "asset_kind")
            box.prop(st, "art_style")
            box.prop(st, "symmetry")
            r = box.row(align=True)
            r.operator("forge.stage_concept", icon="IMAGE_REFERENCE")
            r = box.row()
            r.scale_y = 1.3
            r.operator("forge.stage_approve_brief", icon="CHECKMARK")
        else:
            box.label(text=f"{dict((k, n) for k, n, _d in KINDS)[st.asset_kind]}, "
                           f"{dict((k, n) for k, n, _d in STYLES)[st.art_style].lower()}, "
                           f"symmetry: {dict((k, n) for k, n, _d in SIDES)[st.symmetry].lower()}")

        # ---------------------------------------------------------------- step 2
        box = layout.box()
        _header(box, 2, "Assemble", st.assemble, "assemble")
        if st.assemble != "approved" and st.brief != "approved":
            box.label(text="Fill in the brief first.")
        elif st.assemble != "approved":
            col = box.column(align=True)
            col.label(text="Import the parts (Tripo Bridge or")
            col.label(text="File > Import), select them all, then:")
            box.prop(st, "height_m")
            row = box.row()
            row.scale_y = 1.3
            row.operator("forge.stage_collect", icon="IMPORT")
        if parts:
            col = box.column(align=True)
            for o in parts:
                row = col.row(align=True)
                is_body = G.kind(o) == "body"
                op = row.operator("forge.stage_select_part", text=o.name,
                                  icon="OUTLINER_OB_MESH" if is_body else "OBJECT_DATA", emboss=False)
                op.name = o.name
                row.label(text="body" if is_body else "prop")
                if not is_body and st.assemble != "approved":
                    op = row.operator("forge.stage_set_body", text="", icon="USER")
                    op.name = o.name
        if st.assemble == "review":
            col = box.column(align=True)
            col.label(text="Place each prop on the body:", icon="INFO")
            col.label(text="  click it, Shift + right-click the body,")
            col.label(text="  then Move to 3D cursor. Fine-tune")
            col.label(text="  with G (move) R (rotate) S (scale).")
            row = box.row(align=True)
            row.operator("forge.stage_to_cursor", icon="PIVOT_CURSOR")
            row.operator("forge.stage_mirror", icon="MOD_MIRROR")
            row = box.row()
            row.scale_y = 1.5
            row.operator("forge.stage_approve_layout", icon="CHECKMARK")

        # ---------------------------------------------------------------- step 3
        box = layout.box()
        _header(box, 3, "Geometry repair", st.repair, "repair")
        body = box.column()
        body.enabled = st.assemble == "approved"
        if st.assemble != "approved":
            body.label(text="Approve the layout first.")
        elif st.repair != "approved":
            row = body.row()
            row.scale_y = 1.3
            row.operator("forge.stage_repair", icon="TOOL_SETTINGS")
        rep = json.loads(st.report or "{}")
        fixed = json.loads(st.fixed or "{}")
        if rep and st.assemble == "approved":
            col = body.column(align=True)
            for name, r in rep.items():
                good = r["ok"] and not r["needs_weld"]
                row = col.row(align=True)
                row.alert = not good
                row.label(text=f"{name}: {r['tris']:,} tris", icon=OK_ICON if good else BAD_ICON)
                f = fixed.get(name, {})
                done = [t for t in (f"{f.get('holes_closed', 0)} holes closed" if f.get("holes_closed") else "",
                                    f"{f.get('removed_bits', 0)} bits removed" if f.get("removed_bits") else "",
                                    "cracks welded" if f.get("welded_points") else "",
                                    "welded solid" if f.get("welded_solid") else "") if t]
                if done:
                    col.label(text="    fixed: " + ", ".join(done))
                if not good:
                    sub = col.row(align=True)
                    sub.alert = True
                    sub.label(text="    left: " + G.problems_text(r))
                    if st.repair != "approved":
                        sub = col.row(align=True)
                        op = sub.operator("forge.stage_show_problems", icon="ZOOM_SELECTED")
                        op.name = name
                        op = sub.operator("forge.stage_weld", icon="MOD_REMESH")
                        op.name = name
            if st.repair == "review":
                body.prop(st, "solid_res")
                body.operator("forge.stage_normals_view", icon="NORMALS_FACE")
                col = body.column(align=True)
                col.label(text="Look all around each part. Red rows", icon="INFO")
                col.label(text="still have problems: Weld fixes them.")
                row = body.row(align=True)
                row.scale_y = 1.5
                row.operator("forge.stage_approve_repair", icon="CHECKMARK")
                row = body.row()
                row.alert = True
                row.operator("forge.stage_undo_repair", icon="CANCEL")

        # ---------------------------------------------------------------- steps 4-9
        from .stages_late import draw_late
        draw_late(layout, context)


CLASSES = (ForgeStageState, FORGE_OT_concept, FORGE_OT_approve_brief, FORGE_OT_collect, FORGE_OT_set_body, FORGE_OT_select_part, FORGE_OT_to_cursor,
           FORGE_OT_mirror, FORGE_OT_approve_layout, FORGE_OT_reopen, FORGE_OT_repair, FORGE_OT_weld,
           FORGE_OT_show_problems, FORGE_OT_normals_view, FORGE_OT_undo_repair, FORGE_OT_approve_repair,
           FORGE_PT_stages)


def _not_busy(cls, context):
    from .stages_late import job_running
    return not job_running()


def _guard(op_cls):
    """No Forge button may change the scene while a background job (Quad Remesher...) runs."""
    old = op_cls.__dict__.get("poll")
    if old is None:
        op_cls.poll = classmethod(_not_busy)
    else:
        fn = old.__func__
        op_cls.poll = classmethod(lambda cls, context: _not_busy(cls, context) and fn(cls, context))


def register():
    from . import stages_late
    for c in CLASSES:
        if c.__name__.startswith("FORGE_OT_"):
            _guard(c)
    for c in CLASSES + stages_late.CLASSES:
        bpy.utils.register_class(c)
    bpy.types.Scene.forge_stage = PointerProperty(type=ForgeStageState)
    stages_late.register_handlers()


def unregister():
    from . import stages_late
    stages_late.unregister_handlers()
    del bpy.types.Scene.forge_stage
    for c in reversed(CLASSES + stages_late.CLASSES):
        bpy.utils.unregister_class(c)
