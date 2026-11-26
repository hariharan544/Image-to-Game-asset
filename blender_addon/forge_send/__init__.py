"""Forge - Send to Forge (Blender add-on).

The creative director's front end for the Forge pipeline, inside Blender:
  Tripo Studio --DCC Bridge--> Blender --[Send to Forge]--> game-ready Unreal + Unity assets

3D Viewport > Sidebar (N) > Forge:
  1. select the model (its armature is included automatically)
  2. name, type, tier, swappable parts, notes
  3. Send to Forge: exports a GLB to <project>/inputs, adds the asset to
     <project>/guides/from_blender.yaml and starts `forge run` in a console window
  4. status / Open review / Approve / Reject - no command line needed

Installed by `forge install-blender-addon`, which also writes forge_project.json next to
this file (the project folder). The guide is written as JSON, which is valid YAML.
"""

bl_info = {
    "name": "Forge - Send to Forge",
    "author": "Forge pipeline",
    "version": (1, 0, 0),
    "blender": (4, 2, 0),
    "location": "3D Viewport > Sidebar > Forge",
    "description": "Send a model (e.g. from the Tripo DCC Bridge) through the Forge game-asset pipeline",
    "category": "Import-Export",
}

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, PointerProperty, StringProperty

ADDON_ID = __name__
GUIDE_NAME = "from_blender.yaml"

TYPES = [(t, t.capitalize(), "") for t in ("humanoid", "creature", "weapon", "prop", "vehicle", "environment")]
TIERS = [("hero", "Hero", "Close-up, highest budget"), ("standard", "Standard", "Normal gameplay distance"),
         ("background", "Background", "Far away / crowds")]
STYLES = [(s, s.capitalize(), "") for s in ("realistic", "stylized", "lowpoly")]
REDO = [("", "Nothing (just reject)", "")] + [
    (s, s, f"Rebuild from the {s} stage") for s in ("retopo", "uv", "bake", "skin", "lods", "export")] + [
    (f"{s}@{e}", f"{s} - {e} only", f"Rebuild only the {e} version from {s}")
    for s in ("retopo", "uv", "bake", "skin") for e in ("unreal", "unity")]


# ----------------------------------------------------------------------------- helpers

def _defaults() -> dict:
    try:
        return json.loads((Path(__file__).parent / "forge_project.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _prefs():
    addon = bpy.context.preferences.addons.get(ADDON_ID)
    return addon.preferences if addon else None


def project_dir() -> Path:
    p = _prefs()
    path = (p.project_dir if p and p.project_dir else _defaults().get("project", ""))
    return Path(bpy.path.abspath(path)) if path else Path()


def forge_cmd(project: Path) -> list:
    exe = _defaults().get("forge")
    if exe and Path(exe).exists():
        return [exe]
    for cand in (project / ".venv" / "Scripts" / "forge.exe", project / ".venv" / "bin" / "forge"):
        if cand.exists():
            return [str(cand)]
    return ["forge"]


def safe_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", text).strip("_") or "asset"


def guide_path(project: Path) -> Path:
    return project / "guides" / GUIDE_NAME


def load_guide(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"project": "From Blender", "engines": ["unreal", "unity"], "style": "realistic",
            "defaults": {"review": {"concept_checkpoint": False, "final_checkpoint": True}},
            "assets": []}


def upsert_asset(guide: dict, entry: dict) -> dict:
    assets = [a for a in guide.get("assets", []) if a.get("name") != entry["name"]]
    assets.append(entry)
    guide["assets"] = assets
    return guide


def export_selection(context, glb_path: Path) -> list:
    """Export the selected meshes plus the armatures they are bound to. Returns object names."""
    objs = set(o for o in context.selected_objects if o.type in ("MESH", "ARMATURE"))
    for o in list(objs):
        if o.type == "MESH":
            if o.parent and o.parent.type == "ARMATURE":
                objs.add(o.parent)
            for m in o.modifiers:
                if m.type == "ARMATURE" and m.object:
                    objs.add(m.object)
        if o.type == "ARMATURE":          # an armature alone selected -> take its meshes too
            objs.update(c for c in o.children if c.type == "MESH")
    if not any(o.type == "MESH" for o in objs):
        raise RuntimeError("Select the model (at least one mesh) first")
    if context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for o in context.view_layer.objects:
        o.select_set(False)
    for o in objs:
        o.hide_set(False)
        o.select_set(True)
    context.view_layer.objects.active = next(iter(objs))
    glb_path.parent.mkdir(parents=True, exist_ok=True)
    kw = dict(filepath=str(glb_path), export_format="GLB", use_selection=True)
    try:
        bpy.ops.export_scene.gltf(**kw, export_animations=False)
    except TypeError:                     # older/newer exporter option names
        bpy.ops.export_scene.gltf(**kw)
    return sorted(o.name for o in objs)


def build_entry(s, model_rel: str, image_rel) -> dict:
    entry = {"name": s.asset_name, "model": model_rel, "type": s.asset_type, "tier": s.tier, "style": s.style}
    if image_rel:
        entry["image"] = image_rel
    parts = [p.strip() for p in s.detachable.split(",") if p.strip()]
    if parts:
        entry["detachable_parts"] = parts
    if s.notes.strip():
        entry["notes"] = s.notes.strip()
    if s.height_m > 0:
        entry["overrides"] = {"topology": {"target_height_m": round(s.height_m, 3)}}
    return entry


def open_console(cmd: list, cwd: Path) -> None:
    """Run forge in its own console window so the director sees progress."""
    if sys.platform == "win32":
        subprocess.Popen(cmd, cwd=str(cwd), creationflags=subprocess.CREATE_NEW_CONSOLE)
    else:
        subprocess.Popen(cmd, cwd=str(cwd))


def job_manifest(project: Path, name: str):
    p = project / "jobs" / name / "manifest.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def open_folder(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(str(path))            # noqa: S606 - opens Explorer
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


# ----------------------------------------------------------------------------- data

class ForgePrefs(bpy.types.AddonPreferences):
    bl_idname = ADDON_ID
    project_dir: StringProperty(name="Forge project folder", subtype="DIR_PATH",
                                default=_defaults().get("project", ""))

    def draw(self, context):
        self.layout.prop(self, "project_dir")


class ForgeSettings(bpy.types.PropertyGroup):
    asset_name: StringProperty(name="Name", description="Asset name (file and job name)")
    asset_type: EnumProperty(name="Type", items=TYPES, default="humanoid")
    tier: EnumProperty(name="Tier", items=TIERS, default="hero")
    style: EnumProperty(name="Style", items=STYLES, default="realistic")
    detachable: StringProperty(name="Swappable parts",
                               description="Comma separated part names exported as separate meshes "
                                           "(e.g. sword, shield, helmet)")
    height_m: FloatProperty(name="Height (m)", default=0.0, min=0.0, soft_max=10.0,
                            description="Real-world height; 0 = keep the model's size")
    notes: StringProperty(name="Notes", description="Creative direction for the reviewers / AI supervisor")
    image: StringProperty(name="Concept image", subtype="FILE_PATH",
                          description="Optional: the concept image, shown in the review")
    rig_object: PointerProperty(
        name="Rig source", type=bpy.types.Object, poll=lambda self, o: o.type == "ARMATURE",
        description="Optional: the skeleton of a separate rigged copy (Tripo Studio rigs only after "
                    "retopologizing). The selected dense model gives shape + texture, this gives the skeleton")
    auto_run: BoolProperty(name="Start the pipeline", default=True)
    reject_notes: StringProperty(name="What is wrong")
    redo_from: EnumProperty(name="Rebuild from", items=REDO)


# ----------------------------------------------------------------------------- operators

class FORGE_OT_use_selection_name(bpy.types.Operator):
    bl_idname = "forge.use_selection_name"
    bl_label = "Name from selection"
    bl_description = "Use the active object's name as the asset name"

    def execute(self, context):
        if context.active_object:
            context.scene.forge.asset_name = safe_name(context.active_object.name).lower()
        return {"FINISHED"}


class FORGE_OT_mark_detachable(bpy.types.Operator):
    bl_idname = "forge.mark_detachable"
    bl_label = "Add selected as swappable"
    bl_description = "Add the selected meshes' names to the swappable parts list"

    def execute(self, context):
        s = context.scene.forge
        cur = [p.strip() for p in s.detachable.split(",") if p.strip()]
        for o in context.selected_objects:
            if o.type == "MESH" and o.name not in cur:
                cur.append(o.name)
        s.detachable = ", ".join(cur)
        return {"FINISHED"}


class FORGE_OT_send(bpy.types.Operator):
    bl_idname = "forge.send"
    bl_label = "Send to Forge"
    bl_description = "Export the selection to the Forge project, add it to the guide and start the pipeline"

    def execute(self, context):
        s = context.scene.forge
        project = project_dir()
        if not (project / "forge").is_dir():
            self.report({"ERROR"}, f"Forge project folder not found: '{project}'. Set it in the add-on preferences.")
            return {"CANCELLED"}
        if not s.asset_name.strip():
            s.asset_name = safe_name(context.active_object.name if context.active_object else "asset").lower()
        s.asset_name = safe_name(s.asset_name)
        glb = project / "inputs" / f"{s.asset_name}.glb"
        rig = s.rig_object
        rig_rel = None
        try:
            sel = [o for o in context.selected_objects
                   if not (rig and (o == rig or o.parent == rig))]      # keep the rig copy out
            for o in context.view_layer.objects:
                o.select_set(o in sel)
            names = export_selection(context, glb)
            if rig:
                for o in context.view_layer.objects:
                    o.select_set(o == rig)
                rig_glb = project / "inputs" / f"{s.asset_name}_rig.glb"
                export_selection(context, rig_glb)
                rig_rel = f"../inputs/{rig_glb.name}"
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        if s.asset_type in ("humanoid", "creature") and not rig and not any(
                bpy.data.objects[n].type == "ARMATURE" for n in names):
            self.report({"WARNING"}, "No armature found: characters need the auto-rigged model "
                                     "(auto-rig in Tripo Studio, then send again)")
        image_rel = None
        if s.image:
            src = Path(bpy.path.abspath(s.image))
            if src.exists():
                dst = project / "inputs" / f"{s.asset_name}{src.suffix.lower()}"
                if src.resolve() != dst.resolve():
                    shutil.copy(src, dst)
                image_rel = f"../inputs/{dst.name}"
        gpath = guide_path(project)
        gpath.parent.mkdir(parents=True, exist_ok=True)
        entry = build_entry(s, f"../inputs/{glb.name}", image_rel)
        if rig_rel:
            entry["rig_model"] = rig_rel
        guide = upsert_asset(load_guide(gpath), entry)
        gpath.write_text(json.dumps(guide, indent=2), encoding="utf-8")
        msg = f"Sent '{s.asset_name}' ({len(names)} objects) -> {glb.name}"
        if s.auto_run:
            open_console(forge_cmd(project) + ["run", str(gpath), "--asset", s.asset_name], project)
            msg += " - pipeline started in a console window"
        self.report({"INFO"}, msg)
        return {"FINISHED"}


class FORGE_OT_run(bpy.types.Operator):
    bl_idname = "forge.run"
    bl_label = "Run / continue"
    bl_description = "Run or resume the pipeline for this asset"

    def execute(self, context):
        project = project_dir()
        open_console(forge_cmd(project) + ["run", str(guide_path(project)), "--asset",
                                           context.scene.forge.asset_name], project)
        return {"FINISHED"}


class FORGE_OT_open_review(bpy.types.Operator):
    bl_idname = "forge.open_review"
    bl_label = "Open review"
    bl_description = "Open the review folder (renders + REVIEW.md) or the export folder when done"

    def execute(self, context):
        root = project_dir() / "jobs" / context.scene.forge.asset_name
        for sub in ("review/final", "review/concept", "export", ""):
            p = root / sub
            if p.exists():
                open_folder(p)
                return {"FINISHED"}
        self.report({"WARNING"}, "Nothing to open yet")
        return {"CANCELLED"}


class FORGE_OT_review(bpy.types.Operator):
    bl_idname = "forge.review"
    bl_label = "Review"
    approve: BoolProperty()

    def execute(self, context):
        s = context.scene.forge
        project = project_dir()
        job = project / "jobs" / s.asset_name
        cmd = forge_cmd(project) + ["review", str(job), "--approve" if self.approve else "--reject"]
        notes = s.reject_notes.strip() if not self.approve else "approved in Blender"
        if notes:
            cmd += ["--notes", notes]
        if not self.approve and s.redo_from:
            cmd += ["--redo-from", s.redo_from]
        res = subprocess.run(cmd, cwd=str(project), capture_output=True, text=True)
        if res.returncode != 0:
            self.report({"ERROR"}, (res.stderr or res.stdout).strip()[-300:])
            return {"CANCELLED"}
        if self.approve or s.redo_from:      # continue straight away
            open_console(forge_cmd(project) + ["run", str(guide_path(project)), "--asset", s.asset_name], project)
        self.report({"INFO"}, res.stdout.strip()[-200:] or "Recorded")
        return {"FINISHED"}


# ----------------------------------------------------------------------------- UI

class FORGE_PT_panel(bpy.types.Panel):
    bl_label = "Send to Forge"
    bl_idname = "FORGE_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Forge"

    def draw(self, context):
        s = context.scene.forge
        col = self.layout.column(align=False)
        row = col.row(align=True)
        row.prop(s, "asset_name")
        row.operator("forge.use_selection_name", text="", icon="EYEDROPPER")
        col.prop(s, "asset_type")
        col.prop(s, "tier")
        col.prop(s, "style")
        row = col.row(align=True)
        row.prop(s, "detachable")
        row.operator("forge.mark_detachable", text="", icon="ADD")
        col.prop(s, "rig_object")
        col.prop(s, "height_m")
        col.prop(s, "notes")
        col.prop(s, "image")
        col.prop(s, "auto_run")
        col.operator("forge.send", icon="EXPORT")

        if not s.asset_name:
            return
        m = job_manifest(project_dir(), s.asset_name)
        box = self.layout.box()
        if m is None:
            box.label(text="Not sent yet", icon="INFO")
            return
        status = m.get("status", "?")
        box.label(text=f"Status: {status}", icon="CHECKMARK" if status == "done" else "TIME")
        if m.get("waiting_on"):
            box.label(text=f"Waiting for you: {m['waiting_on']}", icon="ERROR")
        row = box.row(align=True)
        row.operator("forge.open_review", icon="FILE_FOLDER")
        row.operator("forge.run", icon="PLAY")
        if status == "awaiting_review":
            op = box.operator("forge.review", text="Approve", icon="CHECKMARK")
            op.approve = True
            box.prop(s, "reject_notes")
            box.prop(s, "redo_from")
            op = box.operator("forge.review", text="Reject", icon="CANCEL")
            op.approve = False


CLASSES = (ForgePrefs, ForgeSettings, FORGE_OT_use_selection_name, FORGE_OT_mark_detachable, FORGE_OT_send,
           FORGE_OT_run, FORGE_OT_open_review, FORGE_OT_review, FORGE_PT_panel)


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)
    bpy.types.Scene.forge = PointerProperty(type=ForgeSettings)


def unregister():
    del bpy.types.Scene.forge
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)
