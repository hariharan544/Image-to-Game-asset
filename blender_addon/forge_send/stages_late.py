"""Steps 4-9 in the "Forge - step by step" panel: buttons, background runner, reports.

One operator (forge.step) runs every action; long ones (Quad Remesher, UVPackmaster)
are generators driven by a timer so Blender stays responsive while their engines work.
"""

from __future__ import annotations

import json
import traceback

import bpy
from bpy.props import StringProperty

from . import steps as S

ORDER = ["brief", "assemble", "repair", "retopo", "uv", "bake", "colour", "rig", "export"]
TITLES = {"retopo": (4, "Retopology"), "uv": (5, "UVs"), "bake": (6, "Detail bake"),
          "colour": (7, "Colour texture"), "rig": (8, "Rig + pose test"), "export": (9, "Export")}
ICON = {"todo": "COLORSET_13_VEC", "review": "COLORSET_04_VEC", "approved": "COLORSET_03_VEC"}
GOOD, WARN, BAD = "COLORSET_03_VEC", "COLORSET_09_VEC", "COLORSET_01_VEC"


def st_of(context):
    return context.scene.forge_stage


def reopen(st, stage: str) -> None:
    """Re-open `stage` for review; every later step has to be done again."""
    i = ORDER.index(stage)
    setattr(st, stage, "review")
    if stage == "brief":
        return                     # the brief guides later runs; it does not undo approved work
    for later in ORDER[i + 1:]:
        setattr(st, later, "todo")
    if i <= ORDER.index("rig"):
        st.rig_phase = ""
        st.anim_rep = "{}"


def _start_step(st, stage: str) -> None:
    i = ORDER.index(stage)
    for later in ORDER[i + 1:]:
        setattr(st, later, "todo")


# ----------------------------------------------------------------------------- background runner

_JOB: dict = {}     # the running job lives in memory only: never saved in the .blend


def job_running() -> bool:
    return "on_done" in _JOB


def job_label() -> str:
    return _JOB.get("label", "") if job_running() else ""


def _snapshot(st) -> tuple:
    return tuple(getattr(st, s) for s in ORDER) + (st.rig_phase,)


def _finish(result=None, error=None) -> None:
    st = bpy.context.scene.forge_stage
    done = _JOB.pop("on_done", None)
    snap = _JOB.pop("snapshot", None)
    _JOB.pop("label", None)
    if error or (done and snap is not None and snap != _snapshot(st)):
        for mod in ("retopo", "bake", "uv"):      # no stale progress text for the next job
            try:
                S._mod(mod).STATUS["text"] = ""
            except Exception:                     # noqa: BLE001
                pass
        S.STATUS["text"] = ""
    if error:
        st.error = error
    elif done and snap is not None and snap != _snapshot(st):
        st.error = "Result discarded: an earlier step was changed while this was running. Run it again."
    elif done:
        try:
            done(st, result)
            st.error = ""
        except Exception as exc:                          # noqa: BLE001 - shown in the panel
            st.error = f"{type(exc).__name__}: {exc}"
            traceback.print_exc()
    _redraw()


def _tick():
    gen = _JOB.get("gen")
    if gen is None:
        return None
    try:
        wait = next(gen)
        return float(wait or 0.5)
    except StopIteration as stop:
        _JOB.pop("gen", None)
        _finish(stop.value)
    except Exception as exc:                              # noqa: BLE001
        _JOB.pop("gen", None)
        traceback.print_exc()
        _finish(error=f"{type(exc).__name__}: {exc}")
    return None


def run(st, label: str, fn, on_done) -> None:
    """Run fn(); a generator result keeps running from a timer, then on_done(st, result)."""
    if job_running():
        raise RuntimeError(f"still working: {job_label()}")
    st.error = ""
    _JOB["label"] = label
    _JOB["started"] = __import__("time").time()
    _JOB["on_done"] = on_done
    _JOB["snapshot"] = _snapshot(st)
    try:
        res = fn()
    except Exception as exc:                              # noqa: BLE001
        traceback.print_exc()
        _JOB.clear()
        st.error = f"{type(exc).__name__}: {exc}"
        return
    if hasattr(res, "__next__"):
        _JOB["gen"] = res
        if bpy.app.background:                            # tests: no event loop, drive it here
            import time
            while "gen" in _JOB:
                w = _tick()
                if w:
                    time.sleep(min(w, 0.05))
        else:
            bpy.app.timers.register(_tick, first_interval=0.1)
    else:
        _finish(res)


def _redraw():
    try:
        for win in bpy.context.window_manager.windows:
            for area in win.screen.areas:
                if area.type == "VIEW_3D":
                    area.tag_redraw()
    except Exception:                                     # noqa: BLE001
        pass


# ----------------------------------------------------------------------------- actions

def _save_rep(st, field: str, rep) -> None:
    setattr(st, field, json.dumps(rep, default=str))


def _approve(st, stage: str, context, op) -> None:
    from .stages_ui import _log, _save
    setattr(st, stage, "approved")
    _log(context, stage, "approve", {"report": json.loads(getattr(st, f"{stage}_rep", "{}") or "{}")})
    _save(op)


def _shading(context, kind: str) -> None:
    for area in context.screen.areas:
        if area.type == "VIEW_3D":
            area.spaces.active.shading.type = kind


ACTIONS = {
    "retopo_run": "Rebuild every part as a clean quad mesh inside the triangle budget (Quad Remesher). "
                  "The originals are kept hidden for the detail bake",
    "retopo_undo": "Remove the new meshes and show the originals again",
    "retopo_run_selected": "Redo only the parts you selected in the viewport (a prop): every other new mesh "
                           "stays as it is; each part gets the same share of the budget as in a full run",
    "retopo_show_defects": "Select and frame the open or broken edges of the new meshes",
    "retopo_side_left": "Preview: the whole model built from its LEFT side (+X), mirrored. Uses it",
    "retopo_side_right": "Preview: the whole model built from its RIGHT side (-X), mirrored. Uses it",
    "retopo_side_off": "Back to the original model (no preview)",
    "retopo_side_auto": "Pick the side that keeps more detail and preview it",
    "retopo_map": "Show / hide the detail map on the originals: red = more quads, cyan = fewer, white = normal",
    "retopo_map_reset": "Make the detail map again from the shape (undoes your painting)",
    "retopo_map_paint": "Paint the detail map yourself on the selected part (Vertex Paint)",
    "retopo_compare": "Show / hide the original high-detail parts next to the new meshes",
    "uv_run": "Cut seams and unwrap every part, pack the pieces tightly (UVPackmaster)",
    "uv_checker": "Show a checker pattern: squares should look square and evenly sized everywhere",
    "uv_compare_clear": "Forget the comparison: Auto goes back to OptCuts",
    "bake_run": "Bake normal + AO detail from the originals and copy their colour onto the new UVs. "
                "Blender may not respond for a few minutes",
    "colour_show": "Show the textured model (Material Preview)",
    "colour_paint": "Paint fixes on the selected part's colour texture (Texture Paint mode)",
    "colour_save": "Save the painted textures",
    "colour_tripo": "Export each clean part for Tripo Studio's texture tool and open the folder",
    "rig_place": "Guess the joints from the T-pose and place Auto-Rig Pro's reference bones",
    "rig_edit": "Adjust the joints: move the bones (left side moves the right too). Tab when done",
    "rig_build": "Build the Auto-Rig Pro rig, skin the body, attach every prop 100% to its nearest bone",
    "rig_pose": "Play a pose test: arms down/forward, elbows, legs, head and spine. Look for tearing",
    "rig_pose_stop": "Stop the pose test and return to the rest pose",
    "rig_anim": "Play the chosen sample animation on the rig (made on the rig itself: no files)",
    "rig_check": "Step through the chosen animation and measure it: joints that collapse, skin that "
                 "stretches, the mesh passing through itself, weights the engines refuse",
    "rig_check_worst": "Go to the frame where the animation looks worst",
    "export_run": "Make LODs and export Unreal (AAA) and Unity (mobile) files + a GLB preview",
    "export_open": "Open the export folder",
}


def _clean_view(context) -> None:
    """Only the new meshes, in plain grey: the originals (coloured by the detail map) stay
    hidden, otherwise they show through the new surface as coloured streaks."""
    for o in S.parts():
        o.hide_set(True)
    for o in S.lows():
        o.hide_set(False)
    for area in (context.screen.areas if context.screen else []):
        if area.type == "VIEW_3D":
            area.spaces.active.shading.color_type = "MATERIAL"


class FORGE_OT_step(bpy.types.Operator):
    bl_idname = "forge.step"
    bl_label = "Forge step"
    bl_options = {"REGISTER"}
    action: StringProperty()

    @classmethod
    def description(cls, context, props):
        return ACTIONS.get(props.action, "")

    def execute(self, context):
        st = st_of(context)
        if job_running():
            self.report({"WARNING"}, f"Still working: {job_label()}")
            return {"CANCELLED"}
        a = self.action
        try:
            if context.mode != "OBJECT" and a not in ("rig_pose_stop", "colour_save", "retopo_map_paint"):
                bpy.ops.object.mode_set(mode="OBJECT")
            getattr(self, "do_" + a)(context, st)
        except Exception as exc:                          # noqa: BLE001
            traceback.print_exc()
            st.error = f"{type(exc).__name__}: {exc}"
            self.report({"ERROR"}, st.error)
            return {"CANCELLED"}
        return {"FINISHED"}

    # -- 4 retopology
    def do_retopo_run(self, context, st):
        if st.get("detail_view"):
            st["detail_view"] = False
            S.show_detail_map(False)
        _start_step(st, "retopo")
        # the old result is gone the moment the run starts: if this run fails, there must be
        # no old report and no Approve over half-built meshes
        st.retopo, st.retopo_rep = "todo", "{}"
        st.rig_phase = ""
        qr = S.has_addon_op("qremesher.remesh")
        if not qr:
            self.report({"WARNING"}, "Quad Remesher not found: Blender's own remesher is used")

        def done(st, rep):
            S._mod("retopo").STATUS["text"] = ""
            body = S.body_low()
            if body is not None:                      # where the triangles went, by body region
                try:
                    J = S._mod("joints").estimate(body)
                    rep["regions"] = S._mod("density").region_tris(body, J)
                except Exception as exc:              # noqa: BLE001
                    print(f"[forge] region report skipped: {exc}")
            for o in S.lows():                    # show whether mirror symmetry was used
                r = rep.get("parts", {}).get(o.get("forge_part"))
                if r is not None:
                    r["symmetry"] = bool(o.get("forge_symmetry_x"))
                    r["asymmetry_pct"] = round(100 * float(o.get("forge_asymmetry", 1.0)), 1)
            S.clay_lows()
            _clean_view(bpy.context)
            _save_rep(st, "retopo_rep", rep)
            st.retopo = "review"
        run(st, "retopology (Quad Remesher)" if qr else "retopology",
            lambda: S.run_retopo(st.budget, qr, st.detail, st.symmetry), done)

    def do_retopo_run_selected(self, context, st):
        """Redo only the selected parts (a prop), keep every other new mesh as it is. Each part
        gets the same share of the budget as in a full run."""
        only = S.part_names(context.selected_objects)
        if not only:
            self.report({"ERROR"}, "Select the parts to redo first (click them in the viewport)")
            return
        if st.get("detail_view"):
            st["detail_view"] = False
            S.show_detail_map(False)
        old = st.retopo_rep or "{}"
        st.retopo = "todo"
        qr = S.has_addon_op("qremesher.remesh")

        def done(st, rep):
            S._mod("retopo").STATUS["text"] = ""
            merged = json.loads(old)
            parts = merged.get("parts", {})
            for o in S.lows():
                r = rep.get("parts", {}).get(o.get("forge_part"))
                if r is not None:
                    r["symmetry"] = bool(o.get("forge_symmetry_x"))
                    r["asymmetry_pct"] = round(100 * float(o.get("forge_asymmetry", 1.0)), 1)
            parts.update(rep.get("parts", {}))
            have = {o.get("forge_part") for o in S.lows()}
            merged["parts"] = {k: v for k, v in parts.items() if k in have}
            merged["total_tris"] = sum(int(v.get("tris_after", 0)) for v in merged["parts"].values())
            merged["missing"] = S.missing_lows()
            S.clay_lows()
            _clean_view(bpy.context)
            _save_rep(st, "retopo_rep", merged)
            st.retopo = "review"
        run(st, f"retopology of {len(only)} part(s)", lambda: S.run_retopo(st.budget, qr, st.detail,
                                                                          st.symmetry, only=only), done)

    def do_retopo_show_defects(self, context, st):
        """Select and frame the open / broken edges of the new meshes that are not clean."""
        rep = json.loads(st.retopo_rep or "{}").get("parts", {})
        bad = [o for o in S.lows() if any(rep.get(o.get("forge_part"), {}).get(k) for k in
                                          ("open_edges", "bad_edges", "loose", "stacked"))]
        if not bad:
            self.report({"INFO"}, "No open or broken edges")
            return
        S.C().select_only(*bad)
        for o in bad:                    # exactly the faults: not every edge near a joint
            S.mark_defects(o.data)
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_mode(type="EDGE")
        for area in context.screen.areas:
            if area.type == "VIEW_3D":
                region = next((r for r in area.regions if r.type == "WINDOW"), None)
                with context.temp_override(area=area, region=region):
                    bpy.ops.view3d.view_selected()
                break
        self.report({"INFO"}, "The selected edges are the problem: Tab back to Object mode when done")

    def do_retopo_side_left(self, context, st):
        self._side(context, st, "left")

    def do_retopo_side_right(self, context, st):
        self._side(context, st, "right")

    def do_retopo_side_off(self, context, st):
        self._side(context, st, "")

    def do_retopo_side_auto(self, context, st):
        body = S.G.body_of(S.parts())
        side = S._mod("density").pick_side(body.data) if body else "left"
        st.symmetry = side
        self._side(context, st, side)
        self.report({"INFO"}, f"The {side} side keeps more detail: chosen")

    def _side(self, context, st, side):
        for p in S.parts():
            if S.G.kind(p) == "body":
                S.show_side(p, side)
                p.hide_set(False)
        if side:
            st.symmetry = side

    def do_retopo_map(self, context, st):
        on = not st.get("detail_view", False)

        def show(st, _n=None):
            st["detail_view"] = on
            S.show_detail_map(on)
            for area in bpy.context.screen.areas if bpy.context.screen else []:
                if area.type == "VIEW_3D":
                    sh = area.spaces.active.shading
                    sh.type = "SOLID"
                    sh.color_type = "VERTEX" if on else "MATERIAL"
        if on and (S.plan_needed(st.symmetry) or any(S._mod("density").QR_ATTR not in p.data.color_attributes
                                                     for p in S.parts())):
            run(st, "detail map + parts plan", lambda: S.prepare_maps_job(st.detail, side=st.symmetry, budget=st.budget), show)
        else:
            show(st)

    def do_retopo_map_reset(self, context, st):
        run(st, "detail map + parts plan (again)",
            lambda: S.prepare_maps_job(st.detail, recompute=True, side=st.symmetry, budget=st.budget),
            lambda st, n: None)

    def do_retopo_map_paint(self, context, st):
        o = context.active_object
        if o is None or o not in S.parts():
            o = S.G.body_of(S.parts())
        S.prepare_maps(st.detail, side=st.symmetry, budget=st.budget)
        S.show_detail_map(True)
        st["detail_view"] = True
        S.C().select_only(o)
        o.data.color_attributes.active_color_name = "QR_Density"
        bpy.ops.object.mode_set(mode="VERTEX_PAINT")
        self.report({"INFO"}, "Paint red where you want more quads, cyan for fewer, white = normal. "
                              "Tab when done")

    def do_retopo_undo(self, context, st):
        S.undo_retopo()
        st.retopo = "todo"
        st.retopo_rep = "{}"
        _start_step(st, "retopo")

    def do_retopo_compare(self, context, st):
        highs = S.parts()
        show = any(o.hide_get() for o in highs)
        off = 0.0
        if show:                    # the whole original moves aside as one group, props stay on it
            for o in highs:
                o.location.x = 0.0
            context.view_layer.update()
            bounds = [S.G.world_bounds(o) for o in highs]
            off = 1.2 * (max(b[1].x for b in bounds) - min(b[0].x for b in bounds))
        for o in highs:
            o.hide_set(not show)
            o.location.x = off

    def do_retopo_approve(self, context, st):
        missing = S.missing_lows()
        if missing:
            self.report({"ERROR"}, f"No new mesh yet for {', '.join(missing)}: select it and "
                                   "Run for selected parts")
            return
        for o in S.parts():
            o.location.x = 0.0
            o.hide_set(True)
        _approve(st, "retopo", context, self)

    # -- 5 UVs
    def do_uv_run(self, context, st):
        _start_step(st, "uv")
        uvpm = S.has_addon_op("uvpackmaster4.pack")

        def done(st, rep):
            _save_rep(st, "uv_rep", rep)
            st.uv = "review"
        run(st, S.UV_JOB, lambda: S.run_uv(int(st.tex_size), uvpm, engine=st.uv_engine,
                                           split=st.partuv_split, winner=uv_winner(st)), done)

    def do_uv_compare_clear(self, context, st):
        st.uv_compare_rep = "{}"

    def do_uv_checker(self, context, st):
        on = S.toggle_checker()
        _shading(context, "MATERIAL" if on else "SOLID")

    def do_uv_approve(self, context, st):
        S.checker_off()
        _approve(st, "uv", context, self)

    # -- 6 bake
    def do_bake_run(self, context, st):
        _start_step(st, "bake")
        S.work_dir()                                      # asks to save first

        def done(st, rep):
            _save_rep(st, "bake_rep", rep)
            st.bake = "review"
        run(st, "baking", lambda: S.run_bake(int(st.tex_size)), done)
        _shading(context, "MATERIAL")

    def do_bake_approve(self, context, st):
        _approve(st, "bake", context, self)

    # -- 7 colour
    def do_colour_show(self, context, st):
        _shading(context, "MATERIAL")
        if st.colour == "todo":
            st.colour = "review"

    def do_colour_paint(self, context, st):
        o = context.active_object
        if o is None or o not in S.lows():
            o = S.body_low()
        name = S.paint_setup(o)
        st.colour = "review"
        self.report({"INFO"}, f"Painting on {name}. Press Save paint when done")

    def do_colour_save(self, context, st):
        n = S.save_painted()
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        self.report({"INFO"}, f"Saved {n} texture(s)")

    def do_colour_tripo(self, context, st):
        d = S.export_for_retexture()
        st.colour = "review"
        S.open_folder(d)

    def do_colour_approve(self, context, st):
        S.save_painted()
        _approve(st, "colour", context, self)

    # -- 8 rig
    def do_rig_place(self, context, st):
        _start_step(st, "rig")
        rep = S.place_joints()
        _save_rep(st, "rig_rep", rep)
        st.rig = "review"
        st.rig_phase = "joints"
        _shading(context, "SOLID")

    def do_rig_edit(self, context, st):
        S.edit_joints()

    def do_rig_build(self, context, st):
        st.anim_rep = "{}"                        # (checks of the old skinning)
        try:                                      # what Place joints found stays listed
            placed = json.loads(st.rig_rep or "{}").get("extras")
        except ValueError:
            placed = None
        rep = S.build_rig(8)
        if placed and "extras" not in rep:
            rep["extras"] = placed
        _save_rep(st, "rig_rep", rep)
        st.rig_phase = "built"

    def do_rig_pose(self, context, st):
        S.pose_test()
        try:
            bpy.ops.screen.animation_play()
        except RuntimeError:
            pass

    def do_rig_anim(self, context, st):
        rep = S.sample_animation(st.anim_clip)
        self.report({"INFO"}, f"{S.CLIPS[st.anim_clip][0]}: {rep['frames']} frames on "
                              f"{len(rep['controls'])} controls")
        try:
            bpy.ops.screen.animation_play()
        except RuntimeError:
            pass

    def do_rig_check(self, context, st):
        def done(st, rep):
            _save_rep(st, "anim_rep", rep)
            if rep.get("worst_frame"):
                bpy.context.scene.frame_set(int(rep["worst_frame"]))
        run(st, f"checking {S.CLIPS[st.anim_clip][0].lower()}", lambda: S.check_animation_job(st.anim_clip), done)

    def do_rig_check_worst(self, context, st):
        rep = json.loads(st.anim_rep or "{}")
        if rep.get("worst_frame"):
            if context.screen and context.screen.is_animation_playing:
                bpy.ops.screen.animation_cancel(restore_frame=False)
            context.scene.frame_set(int(rep["worst_frame"]))

    def do_rig_pose_stop(self, context, st):
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        S.pose_test_stop()

    def do_rig_approve(self, context, st):
        S.pose_test_stop()
        _approve(st, "rig", context, self)

    # -- 9 export
    def do_export_run(self, context, st):
        _start_step(st, "export")
        bake = json.loads(st.bake_rep or "{}")
        budget_unity = st.budget_unity

        def job():
            files = {}
            for engine in ("unreal", "unity"):
                S.STATUS["text"] = f"exporting {engine} (LODs, FBX, textures)"
                yield 0.05
                files[engine] = S.export_engine(engine, bake, budget_unity if engine == "unity" else 0)
            S.STATUS["text"] = ""
            return files

        def done(st, files):
            _save_rep(st, "export_rep", files)
            st.export = "review"
        run(st, "export", job, done)

    def do_export_open(self, context, st):
        S.open_folder(S.work_dir() / "export")

    def do_export_approve(self, context, st):
        _approve(st, "export", context, self)


class FORGE_OT_import_retexture(bpy.types.Operator):
    bl_idname = "forge.import_retexture"
    bl_label = "Import re-textured part"
    bl_description = ("Pick the model Tripo Studio re-textured; its colour is baked onto the selected part "
                      "(same shape, our UVs)")
    filepath: StringProperty(subtype="FILE_PATH")
    filter_glob: StringProperty(default="*.glb;*.gltf;*.fbx", options={"HIDDEN"})

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        st = st_of(context)
        o = context.active_object
        lows = S.lows()
        if o not in lows:
            o = next((x for x in lows if x.select_get()), None) or S.body_low()
        part = o.get(S.C().PART_PROP)
        try:
            if context.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
            S.import_retexture(self.filepath, part, int(st.tex_size))
        except Exception as exc:                          # noqa: BLE001
            traceback.print_exc()
            st.error = f"{type(exc).__name__}: {exc}"
            self.report({"ERROR"}, st.error)
            return {"CANCELLED"}
        st.colour = "review"
        self.report({"INFO"}, f"New colour baked onto {part}")
        return {"FINISHED"}


# ----------------------------------------------------------------------------- panel

def _btn(layout, action: str, text: str, icon: str, scale: float = 1.0, alert: bool = False):
    row = layout.row(align=True)
    row.scale_y = scale
    row.alert = alert
    row.operator("forge.step", text=text, icon=icon).action = action


def _header(box, stage: str, status: str):
    n, title = TITLES[stage]
    row = box.row()
    row.label(text=f"Step {n} · {title}", icon=ICON[status])
    if status == "approved":
        op = row.operator("forge.stage_reopen", text="Change", icon="LOOP_BACK", emboss=False)
        op.stage = stage


def _rows(col, items):
    for icon, text in items:
        col.label(text=text, icon=icon)


JOINT_WHY = {        # why a cut-off part was not joined as one skin, in plain words
    "no plug": "its root ring was not recorded",
    "no overlap": "it does not reach into the body",
    "hole": "the body has an opening next to its root",
    "island": "joining would cut away more than the root",
    "inside": "it lies inside the body",
    "openings": "its root did not open as one clean ring",
    "bridge": "the two root rings could not be bridged",
    "open edges": "joining would have left holes",
    "thin faces": "joining would have made needle-thin faces",
    "flipped faces": "joining would have turned faces inside out",
    "crossing faces": "the joint faces would have crossed each other",
    "off the surface": "at this triangle count the joint would cut across the fold at its root",
    "error": "Blender refused the join",
}
# what to do, by reason: the hidden plug is inside the body for every reason but these
JOINT_TODO = {
    "no overlap": "it sits on the body as its own piece: check its root in the viewport",
    "no plug": "it sits on the body as its own piece: check its root in the viewport",
    "inside": "check in the viewport that it still shows",
    "off the surface": "its root is hidden inside the body: nothing to do (more triangles let it join as one skin)",
}


def _part_name(j: dict, only: bool) -> str:
    """A cut-off part by its name in the parts plan (the tail, the left antenna...)."""
    name = str(j.get("name") or "")
    if name and not name.startswith("part_"):
        return f"the {S.part_words(name)}"
    return "the cut-off part" if only else f"cut-off part {j.get('part', '')}".strip()


PANEL_WIDTH = 44                                 # characters a sidebar row shows (Steps 4-6)


def _row(icon, text):
    """One indented sentence as rows that fit the sidebar (Steps 4-6)."""
    return _wrapped(icon, text, first="    ", rest="     ", width=PANEL_WIDTH)


def _joint_rows(r):
    """How each cut-off part was joined back: one skin, or its own piece (why, what to do)."""
    joints = r.get("joints") or ([{"joint": r["joint"]}] if r.get("joint") else [])
    out = []
    for j in joints:
        name = _part_name(j, len(joints) == 1)
        res = str(j.get("joint", ""))
        if res == "welded":
            out += _row("BLANK1", f"{name}: joined into the body as one skin")
            if j.get("folds_near"):
                out += _row(WARN, f"{name}: {j['folds_near']} folded faces near its root (the part's own "
                                  "remesh). Look at it; if it shows, paint it denser and run again")
            continue
        why = res.split(":", 1)[1].strip() if ":" in res else ""
        out += _row("BLANK1", f"{name}: kept as its own piece")
        if why:
            out += _row("BLANK1", f"({JOINT_WHY.get(why, why)})")
        todo = JOINT_TODO.get(why, "its root is hidden inside the body: nothing to do")
        if j.get("plug_shows") and why not in ("no overlap", "no plug", "inside"):
            todo = "part of its root shows next to the body: check it in the viewport"
        out += _row("BLANK1", todo)
    return out


def _retopo_rows(rep):
    out = []
    for part, r in rep.get("parts", {}).items():
        m = str(r.get("method", ""))
        icon = GOOD if m.startswith("quadremesher") and "failed" not in m else (BAD if m.startswith("failed") else WARN)
        sh = r.get("shape")
        if sh and sh.get("lost_pct", 0) > 0.5:
            icon = WARN if sh.get("detail_only") else BAD
        out += _wrapped(icon, f"{part}: {r.get('tris_before', 0):,} > {r.get('tris_after', 0):,} tris", rest="    ")
        if icon != GOOD and not (sh and sh.get("lost_pct", 0) > 0.5):
            out += _row("BLANK1", f"method: {m}")
        cr = r.get("creases") or {}
        if "left_pct" in cr or "right_pct" in cr:
            low_side = min(cr.get("left_pct", 100), cr.get("right_pct", 100))
            out += _row("BLANK1" if low_side >= 80 else WARN,
                        f"face creases kept: left {cr.get('left_pct', '-')}%, "
                        f"right {cr.get('right_pct', '-')}%"
                        + (f" (+{cr.get('carved_tris', 0)} tris carved)" if cr.get("carved_tris") else ""))
        if "symmetry" in r:
            if r["symmetry"] and r.get("asymmetry_pct", 0) >= 1:
                out += _row("BLANK1", f"mirrored, then fitted ({r['asymmetry_pct']}% one-sided)")
            else:
                out += _row("BLANK1", "mirrored (symmetric)" if r["symmetry"]
                            else f"not mirrored ({r.get('asymmetry_pct', 0)}% one-sided detail)")
        if r.get("separate_parts"):
            out += _row("BLANK1", f"{r['separate_parts']} part(s) remeshed on their own, then joined")
            out += _joint_rows(r)
        if r.get("over_budget"):
            out += _row(WARN, f"{r['over_budget']:,} tris over the budget, left as is: reducing would "
                              "crumple the joint. To fit, lower Triangles a little and run again")
        for how in r.get("piece_fallbacks", []):
            out += _row(WARN, f"a part got no Quad Remesher result: {how} used")
        for why in r.get("split_kept", []):
            out += _row(WARN, why)
        if r.get("open_edges") or r.get("bad_edges") or r.get("loose"):
            out += _row(BAD, f"not clean: {r.get('open_edges', 0)} open, {r.get('bad_edges', 0)} broken, "
                             f"{r.get('loose', 0)} loose edges")
            out += _row("BLANK1", "Show the problem edges (button below)")
        if r.get("stacked"):
            out += _row(BAD, f"not clean: {r['stacked']} faces / points on top of each other")
            out += _row("BLANK1", "UVgami and the bake need each face in its own place")
        t = r.get("tidied") or {}
        if any(t.values()):
            bits = [f"{t['welded']} doubled points welded" if t.get("welded") else "",
                    f"{t['stacked']} stacked faces removed" if t.get("stacked") else "",
                    "openings rebuilt" if t.get("rebuilt") else ""]
            out += _row("BLANK1", "cleaned: " + ", ".join(b for b in bits if b))
        if sh:
            if sh.get("lost_pct", 0) > 0.5 and sh.get("detail_only"):
                out += _row("BLANK1", f"fine detail flattened: {sh['lost_pct']}% (curls, twists)")
                out += _row("BLANK1", "the bake keeps it as a normal map; for real geometry: "
                                      "raise Triangles or paint it red, run again")
            elif sh.get("lost_pct", 0) > 0.5:
                out += _row("BLANK1", f"shape lost: {sh['lost_pct']}% (gap {sh['max_gap_pct']}% of size)")
                out += _row("BLANK1", "paint the lost part red (Paint), run again")
            if sh.get("rescue_undone"):
                out += _row(WARN, "rebuilding a lost part was undone (it left openings)")
            else:
                fixed = f", fixed {sh['refined']}x" if sh.get("refined") else ""
                if "face-refined" in m:
                    fixed += ", face details refined"
                if sh.get("rescued"):
                    fixed += f", {sh['rescued']} thin part(s) rebuilt"
                out += _row("BLANK1", f"shape kept{fixed}")
    for name in rep.get("missing", []):
        out += _wrapped(WARN, f"{name}: no new mesh yet - select it, Run for selected parts", rest="    ")
    if rep.get("total_tris"):
        out.append(("INFO", f"total {rep['total_tris']:,} triangles"))
    reg = rep.get("regions") or {}
    if reg:
        tot = max(sum(reg.values()), 1)
        order = sorted(reg.items(), key=lambda kv: -kv[1])
        out += _row("BLANK1", ", ".join(f"{k} {100 * v // tot}%" for k, v in order))
    return out


def _wrapped(icon, text, first="", rest="    ", width=44):
    """A long plain sentence as panel rows that fit: the icon on the first row only."""
    import textwrap
    lines = textwrap.wrap(text, width, initial_indent=first, subsequent_indent=rest) or [first]
    return [(icon if i == 0 else "BLANK1", line) for i, line in enumerate(lines)]


GUARD_ROWS = {"island": "face kept in one piece: no seam across it",
              "seam_cost": "seams kept off the face"}


def _uv_run_rows(rep):
    """Which UVgami engine cut the seams, and how (one block for the whole model)."""
    out = []
    run = rep.get("uvgami_run") or {}
    by_uvgami = any(r.get("seams") == "uvgami" for r in rep.get("parts", {}).values())
    if run.get("engine") and by_uvgami:
        out.append((GOOD, f"Seams cut by UVgami ({run.get('label') or run['engine']})"))
    if run.get("note"):
        out += _wrapped(WARN, run["note"])
    if not by_uvgami:
        return out
    guard = run.get("face_guard", "")
    if guard in GUARD_ROWS:
        out.append(("BLANK1", "    " + GUARD_ROWS[guard]))
    elif guard == "ignored":
        out += _wrapped(WARN, f"{run.get('label') or run.get('engine')} ignores the face guard: "
                              "seams may cross the face", first="    ", rest="     ")
    if run.get("material_seams"):
        out.append(("BLANK1", "    seams follow the material borders"))
    return out


def _uv_rows(rep):
    out = []
    if rep.get("uvgami"):
        out.append((WARN, rep["uvgami"][:60]))
    out += _uv_run_rows(rep)
    for part, r in rep.get("parts", {}).items():
        if not r.get("has_uv"):
            out.append((BAD, f"{part}: no UVs"))
            continue
        over, cv = r.get("overlap_pct", 0), r.get("texel_density_cv") or 0
        packer = str(r.get("packer", ""))
        by_uvpm = packer == "uvpackmaster"                # exactly: "uvpackmaster-failed>..." is a fallback
        icon = BAD if over > 0.5 else (WARN if cv > 0.4 or not by_uvpm else GOOD)
        out.append((icon, f"{part}: {r.get('utilization', 0):.0%} used, stretch {cv:.2f}"))
        seams = r.get("seams")
        if seams == "uvgami":
            out.append(("BLANK1", "    seams by UVgami"))
        elif seams:
            note = str(r.get("seams_note") or "")
            out.append((WARN if note else "BLANK1", "    seams by Blender"))
            if note.startswith("UVgami: "):              # its own reason, on lines that fit
                out += _wrapped("BLANK1", note, first="    ", rest="     ")
            elif note:
                out.append(("BLANK1", f"    ({note})"))
        cl = r.get("cleaned") or {}
        if cl.get("welded") or cl.get("stacked") or cl.get("rebuilt"):
            out.append(("BLANK1", "    fixed first: faces on the same spot"))
        if cl.get("left"):
            out.append((WARN, f"    {cl['left']} faces still on the same spot"))
        if by_uvpm:
            out.append(("BLANK1", "    packed by UVPackmaster"))
        elif "failed" in packer:
            out.append(("BLANK1", "    Blender packer (UVPackmaster failed)"))
        else:
            out.append(("BLANK1", "    Blender packer (UVPackmaster not found)"))
        if over > 0.5:
            out.append(("BLANK1", f"    {over:.1f}% overlapping"))
    return out


def _bake_rows(rep):
    out = []
    for part, r in rep.get("parts", {}).items():
        if r.get("skipped"):
            out += _wrapped(BAD, f"{part}: {r['skipped']}", rest="    ")
            continue
        inv = r.get("invalid_texels_max")
        if inv is None:                         # a report from before the rays were checked
            miss = r.get("bake_miss_ratio", 0)
            icon = GOOD if miss <= 0.02 else (WARN if miss <= 0.10 else BAD)
            out += _wrapped(icon, f"{part}: {len(r.get('maps', {}))} maps, {miss:.1%} patched", rest="    ")
        else:
            # measured BEFORE the patch: spots where the bake found nothing, the inside of the
            # original, hidden texture, or a surface facing away from the new mesh
            icon = GOOD if inv <= 0.02 else (WARN if inv <= 0.10 else BAD)
            n = len(r.get("maps", {}))
            out.append((icon, f"{part}: {n} map{'' if n == 1 else 's'}"))
            # parts of the original that are open, paper-thin pieces have no inside: there the
            # check cannot tell whether the bake saw their front or their back
            both = float(r.get("both_ways", 0.0))
            if inv >= 0.0005:
                out += _row("BLANK1", f"{inv:.1%} of the texture could not be baked cleanly and was "
                                      "patched from nearby")
            elif both < 0.0005:
                out += _row("BLANK1", "the whole texture baked cleanly")
            if both >= 0.0005:
                out += _row("BLANK1", f"{both:.1%} comes from open, paper-thin pieces of the original: "
                                      "there the bake cannot be checked. To fix: Step 3, Weld into one "
                                      "solid; then Steps 4, 5 and 6 run again")
        spots = int((r.get("cage") or {}).get("unenclosed", 0))
        if spots:                               # a warning only when the patching is not small
            sev = "INFO" if inv is not None and inv <= 0.02 else WARN
            out += _row(sev, f"{spots:,} faces of the new mesh are too coarse or folded to bake "
                             "cleanly. To fix: raise Triangles in Step 4 (or paint the spot red); "
                             "then Steps 5 and 6 run again")
        hidden = int((r.get("cage") or {}).get("hidden", 0))
        if hidden:
            out += _row("BLANK1", f"{hidden:,} faces of a part's hidden root, inside the body: "
                                  "never seen, not checked")
        sp = sum((r.get("specks_removed") or {}).values())
        if sp:
            out += _row("BLANK1", f"{sp:,} specks cleaned")
    return out


def _rig_rows(rep):
    out = []
    ex = rep.get("extras") or {}
    for k, n in (ex.get("added") or {}).items():
        out.append((GOOD, f"{k}: {n} bones"))
    for k, why in (ex.get("skipped") or {}).items():
        out += _wrapped("INFO", f"{_app_words(k)}: {why}", first="", rest="  ", width=60)
    for k in ex.get("stray") or []:                # (Auto-Rig Pro adds ears in pairs)
        out += _wrapped("INFO", f"{_app_words(k)}: none on this body; Auto-Rig Pro adds it anyway, "
                                "its bones move no skin", first="", rest="  ", width=60)
    for e in (ex.get("errors") or [])[:3]:
        out.append((BAD, e[:60]))
    stray = set(ex.get("stray") or [])
    if not rep.get("chain_parents"):              # (placed, not built yet)
        for chain, h in (ex.get("parents") or {}).items():
            if isinstance(h, dict) and h.get("ref_parent") and chain not in stray:
                out.append(("BLANK1", f"  {_app_words(chain)} will hang from "
                                      f"{_bone_words(h['ref_parent'].replace('_ref', ''))}"))
    if rep.get("bones"):
        out.append((GOOD, f"{rep['bones']} bones ({rep.get('deform_bones', 0)} deform)"))
    for part, w in rep.get("weights", {}).items():
        if not w.get("weighted", True):
            out.append((BAD, f"{part}: not skinned"))
            continue
        un = w.get("unweighted_verts_pct", 0)
        out.append((GOOD if un < 0.5 else BAD, f"{part}: {un:.1f}% unweighted"))
    for part, bone in rep.get("props", {}).items():
        out.append(("BONE_DATA", f"{part} > {bone}"))
    out += _chain_rows(rep)
    return out


def _bone_words(name) -> str:
    """'spine_01.x' -> 'spine 01', 'c_ear_01.l' -> 'left ear 01' (for the panel)."""
    if not name:
        return "?"
    base, _, side = str(name).rpartition(".")
    if not base:
        base, side = str(name), ""
    if base.startswith("c_"):
        base = base[2:]
    return ({"l": "left ", "r": "right "}.get(side, "") + base.replace("_", " ")).strip()


def _app_words(app) -> str:
    """'ear_l' -> 'left ear', 'tail' -> 'tail', 'tail2' -> 'second tail'."""
    return S.part_words(app)


def _chain_rows(rep):
    """Tail / ears after the build: what they hang from, and whether that bone owns the skin
    round their root (if another bone does, the root tears when that bone moves)."""
    out = []
    if (rep.get("skinning") or {}).get("preserve_volume_found"):
        out.append(("INFO", "Preserve Volume turned off (engines blend"))
        out.append(("BLANK1", "  bones linearly: now the viewport matches)"))
    differs = set()
    stray = set((rep.get("extras") or {}).get("stray") or []) | set(rep.get("stray_chains") or {})
    for chain, cp in (rep.get("chain_parents") or {}).items():
        if isinstance(cp, dict) and cp.get("ok") is False and chain not in stray:
            differs.add(chain)
            out.append((WARN, f"{_app_words(chain)} hangs from {_bone_words(cp.get('parent'))},"))
            out.append(("BLANK1", f"  not {_bone_words(cp.get('wanted'))} (Auto-Rig Pro differs)."))
            out.append(("BLANK1", "  Its root may tear when the body bends: send"))
            out.append(("BLANK1", "  a screenshot of this box back to the Forge team"))
    for app, a in (rep.get("appendages") or {}).items():
        if not isinstance(a, dict):
            continue
        name = _app_words(app)
        if a.get("error") or a.get("skipped"):
            out.append(("INFO", f"{name}: root weights not checked"))
            out.append(("BLANK1", f"  ({str(a.get('error') or a.get('skipped'))[:40]})"))
            continue
        share, parent, owner = a.get("root_share", 0.0), a.get("parent"), a.get("root_owner")
        ok = a.get("root_ok", share >= 0.5)
        if ok is None:                               # no body skin round its root to read
            out.append(("INFO", f"{name} hangs from {_bone_words(parent)}"))
            out.append(("BLANK1", "  (no body skin round its root to check)"))
        elif ok:
            out.append((GOOD, f"{name} hangs from {_bone_words(parent)}"))
            out.append(("BLANK1", f"  which moves {share:.0%} of the skin round its root"))
        elif owner == parent:                        # the biggest share, though under half
            out.append(("INFO", f"{name} hangs from {_bone_words(parent)}"))
            out.append(("BLANK1", f"  which moves most ({share:.0%}) of the skin round"))
            out.append(("BLANK1", "  its root; bones near it move the rest"))
        else:
            out.append((WARN, f"{name}: the skin round its root moves"))
            out.append(("BLANK1", f"  with {_bone_words(owner)}, not {_bone_words(parent)}"))
            out.append(("BLANK1", f"  ({share:.0%}): it can tear when {_bone_words(owner)} moves."))
            if app not in differs:
                out.append(("BLANK1", "  Check the joints near it, build again"))
        if a.get("moved_points"):
            out.append(("BLANK1", f"  {a['moved_points']:,} body points it pulled"))
            out.append(("BLANK1", f"  now follow {_bone_words(parent)}"))
    return out


def _when(frame, pose) -> str:
    """'pose 'elbows' (frame 85)': which test pose a finding was in, then the frame."""
    if not pose or not pose.get("name"):
        return f"frame {frame}"
    part = "" if float(pose.get("weight", 1.0)) >= 0.9 else ", part way"
    return f"pose '{pose['name']}'{part} (frame {frame})"


ANIM_SHOWN = 6                                   # places listed in the panel (worst first)


def _wrap(icon, text, width=60, first="    ", rest="      ") -> list:
    """One finding as panel rows of at most `width` characters: the first with the icon."""
    out, line = [], first
    for word in text.split():
        if len(line) + len(word) + (0 if line.endswith(" ") else 1) > width and line.strip():
            out.append(line)
            line = rest
        line += ("" if line.endswith(" ") else " ") + word
    if line.strip():
        out.append(line)
    return [(icon if i == 0 else "BLANK1", t) for i, t in enumerate(out)]


def _when_bent(f) -> str:
    """"pose 'elbows' (bent 120°, frame 85)": the test pose, how far the joint turned, the frame."""
    frame, pose = f.get("frame"), f.get("pose")
    turn = []
    if f.get("bend_deg") is not None and (f.get("bend_deg") >= 10 or not f.get("twist_deg")):
        turn.append(f"bent {f['bend_deg']}°")
    if f.get("twist_deg") is not None and f["twist_deg"] >= 10:
        turn.append(f"twisted {f['twist_deg']}°")
    inside = ", ".join(turn + [f"frame {frame}"])
    if not pose or not pose.get("name"):
        return f"at {inside}"
    part = "" if float(pose.get("weight", 1.0)) >= 0.9 else " part way"
    return f"pose '{pose['name']}'{part} ({inside})"


ANIM_ADVICE = {
    "stretch": "Stretched skin: smooth the weights there over a wider band.",
    "pose": "The pose asks for that stretch: on this body no weights can spread the turn "
            "wider. Turn that part less in the animation.",
    "squash": "Squashed skin away from a bend's crease: a bone there shrinks, or the weights "
              "pull the points together - smooth them.",
    "folds": "Faces turning inside out or folding through: smooth the weights there.",
    "joint": "Thinner than game skinning makes it: smooth the weights across that joint.",
    "inner": "The inside of a bend caves in: the weights blend over too long a stretch there. "
             "Blend over a shorter one on the inside of the bend, or add a helper bone.",
    "deep": "Game skinning cannot hold a turn that deep: turn it less, or add a helper bone.",
    "touch": "Parts passing into each other: turn less in that pose, or move the part.",
    "hidden": "A part Step 4 kept as its own piece has its root hidden in the body; a far turn "
              "brings it out. Turn it less in that pose, or raise Triangles in Step 4 so it "
              "joins the body as one skin.",
    "unity": "Unity's limit: fewer bones per point there (smoother, wider weights) helps.",
}
STRETCH_FAIL = 2.0                               # (motion_check.LIMITS["stretch"][1])


def _pose_part(f) -> str:
    """'the head' for a finding whose stretch the pose itself asks for (motion_check names
    the part that turns); '' when unknown."""
    m = f.get("pose_mover")
    return f"the {m}" if m else ""


def _finding_text(where, f) -> tuple:
    """(one finding in plain words: where, in which pose, what happened; [the advice it needs])."""
    c = f.get("check")
    if c == "joints":
        twist = f.get("kind") == "twist" or (f.get("bend_deg") or 0) < 10
        what = f"{f.get('part') or 'thickness'} kept {f['value']:.0%}"
        turn = "twist" if twist else "bend"
        if f.get("normal") and f.get("grade") == "warn":
            return f"{where}, {_when_bent(f)}: {what} - normal for game skinning at this {turn}", []
        if f.get("normal"):
            return f"{where}, {_when_bent(f)}: {what} - game skinning collapses at a {turn} this deep", ["deep"]
        if f.get("part") == "inner side":
            # outside the crease the inner side thins when the blend reaches too far along the limb
            return f"{where}, {_when_bent(f)}: {what} - the inside of the bend caves in", ["inner"]
        return f"{where}, {_when_bent(f)}: {what} - more than game skinning loses", ["joint"]
    if c == "skin":
        parts, why = [], []
        if f.get("stretch_grade", f.get("grade")) not in (None, "pass"):
            floor = f.get("pose_floor")
            text = f"skin stretched {f['stretch']:.1f}x (the texture smears)"
            part = _pose_part(f)
            if floor is not None and floor > STRETCH_FAIL:
                # no weights can bring it under the limit: the pose asks for it on this body
                text += f"; the pose itself asks for at least {floor:.1f}x on this body"
                if part:
                    text += f": turn {part} less"
                why.append("pose")
            else:
                if floor is not None:        # weights can help, down to what the pose asks
                    text += f"; the pose itself asks for at least {floor:.1f}x here"
                    if part:
                        text += f" (turning {part} less helps too)"
                why.append("stretch")
            parts.append((f, text))
        if f.get("squash_grade") not in (None, "pass"):
            g = {"frame": f.get("squash_frame"), "pose": f.get("squash_pose")}
            parts.append((g, f"skin squashed to {f['squash']:.0%} (the texture bunches)"))
            why.append("squash")
        if f.get("folds") and f.get("folds_grade") not in (None, "pass"):
            g = {"frame": f.get("folds_frame"), "pose": f.get("folds_pose")}
            parts.append((g, f"{f['folds']} faces turn inside out"))
            why.append("folds")
        if not parts:
            return f"{where}: skin {f.get('grade')}", []
        (g0, t0), rest = parts[0], parts[1:]
        text = f"{where}, {_when_bent(g0)}: {t0}"
        for g, t in rest:
            same = g.get("frame") == g0.get("frame")
            text += f"; {t}" + ("" if same else f" in {_when_bent(g)}")
        return text, why
    if c == "crossing" and f.get("kind") == "touch":
        return f"{where}, {_when_bent(f)}: {f['faces']} faces pass into each other", ["touch"]
    if c == "crossing" and f.get("kind") == "hidden":
        return f"{where}, {_when_bent(f)}: {f['faces']} faces come out through the body", ["hidden"]
    if c == "crossing":
        return f"{where}, {_when_bent(f)}: {f['faces']} faces fold through each other", ["folds"]
    if c == "unity":
        text = (f"Unity, {where}, {_when_bent(f)}: its 4-bone limit moves the skin {f['shift_mm']:.0f} mm "
                f"(about {f['shift_edges']:.1f} times the typical edge length)")
        if float(f.get("added_stretch") or 1.0) >= 1.1 and f.get("added_where"):
            g = {"frame": f.get("added_frame"), "pose": f.get("added_pose")}
            text += (f"; it stretches the skin {f['added_stretch']:.1f}x more at {f['added_where']}, "
                     f"{_when_bent(g)}")
        return text, ["unity"]
    if c == "contact":
        return f"{where}, {_when_bent(f)}: inner side presses together - contact, expected", []
    return f"{where}: {f.get('grade')}", []


def _bad(f) -> bool:
    return f.get("grade") in ("warn", "fail")


def _anim_rows(rep):
    """The automatic checks of one clip, in plain words: the worst finding per place (a joint,
    a part, two parts touching), in which test pose, and what to do; contact is information.
    The places shown are the worst ones, and always the worst of each check (a collapsing joint
    is never hidden behind stretched skin)."""
    if "regions" not in rep:
        return _anim_rows_legacy(rep)
    icon = {"pass": GOOD, "warn": WARN, "fail": BAD, "info": "INFO"}
    c = rep.get("checks", {})
    out = [(icon.get(rep.get("grade"), WARN),
            {"pass": "Animation looks clean", "warn": "Animation: worth a look",
             "fail": "Animation: something breaks"}.get(rep.get("grade"), "Animation checked")
            + f" ({rep.get('frames', 0)} frames)")]
    if (rep.get("skinning") or {}).get("preserve_volume"):
        out.append((WARN, "    the rig blends with Preserve Volume on;"))
        out.append(("BLANK1", "      engines do not: build the rig again"))
    regions = rep.get("regions") or []
    bad = [r for r in regions if _bad(r)]
    sev = {"fail": 2, "warn": 1}
    shown = list(bad[:ANIM_SHOWN])
    must = {}                                    # region index -> the check it is shown for
    for chk in ("joints", "skin", "crossing"):
        cands = [(k, f) for k, r in enumerate(bad) for f in (r.get("findings") or [r["worst"]])
                 if f.get("check") == chk and _bad(f)]
        if not cands:
            continue
        k, _f = max(cands, key=lambda kf: (sev[kf[1]["grade"]], float(kf[1].get("over") or 0.0), -kf[0]))
        must.setdefault(k, chk)
        if all(r is not bad[k] for r in shown):
            shown.append(bad[k])
    shown.sort(key=lambda r: next(k for k, x in enumerate(bad) if x is r))
    advice = []
    for r in shown:
        k = next(k for k, x in enumerate(bad) if x is r)
        fs = [f for f in (r.get("findings") or [r["worst"]]) if _bad(f)]
        pick = fs[:2]
        chk = must.get(k)
        if chk and not any(f.get("check") == chk for f in pick):
            pick = pick[:1] + [next(f for f in fs if f.get("check") == chk)]
        for f in pick:
            text, why = _finding_text(r["where"], f)
            out += _wrap(icon.get(f["grade"], WARN), text)
            for w in why:
                if w not in advice:
                    advice.append(w)
        caves = any(f.get("check") == "joints" and f.get("part") == "inner side" for f in pick)
        if r.get("contact") and not caves:
            out.append(("BLANK1", "      (inner side presses there: contact, expected)"))
    rest = [r for r in bad if all(r is not x for x in shown)]
    if rest:
        out += _wrap("BLANK1", f"and {len(rest)} more places worth a look: "
                     + ", ".join(r["where"] for r in rest[:4])
                     + (", ..." if len(rest) > 4 else ""))
    touching = [r["where"] for r in regions if r.get("grade") == "info" and r.get("contact")]
    if touching:
        out += _wrap("INFO", "contact, expected at these bends: " + ", ".join(touching[:6]))
    for why in advice:
        out += _wrap("INFO", ANIM_ADVICE[why])
    j, k, x = c.get("joints", {}), c.get("skin", {}), c.get("crossing", {})
    if j and j.get("grade") == "pass":
        out.append((GOOD, "    joints keep their shape"))
    if k and k.get("grade") == "pass":
        out.append((GOOD, f"    skin stretch fine (up to {k.get('stretch', 1.0):.1f}x)"))
    if x and x.get("grade") == "pass":
        out.append((GOOD, "    nothing passes through the body" if not x.get("contact")
                    else "    nothing passes through (contact at bends only)"))
    w = c.get("weights", {})
    if w:
        if w.get("unweighted"):
            out.append((BAD, f"    {w['unweighted']} points no bone moves"))
        u = w.get("unity") or {}
        over = (w.get("over") or {}).get("Unity", 0)
        if over:
            out += _wrap("INFO", f"{over} points use more than 4 bones: Unity fades the weakest out")
        if u and u.get("grade") not in (None, "pass"):
            text, _why = _finding_text(u.get("where") or "the body", {**u, "check": "unity"})
            out += _wrap(icon.get(u["grade"], WARN), text)
            out += _wrap("BLANK1", ANIM_ADVICE["unity"], first="      ")
        if u and u.get("grade") == "pass" and over:
            out += _wrap(GOOD, f"that moves the skin {u.get('shift_mm', 0):.0f} mm at most (measured on the full "
                         "mesh): fine")
        if not w.get("unweighted") and w.get("grade") == "pass" and not over:
            out.append((GOOD, "    weights fine for Unreal and Unity"))
    for name, mods in ((rep.get("measured_as") or {}).get("without_modifiers") or {}).items():
        out += _wrap("INFO", f"{name}: measured without its {', '.join(mods)} (it adds points after the "
                     "bones move the mesh)")
    for name, why in (rep.get("skipped") or {}).items():
        out += _wrap(WARN, f"{name} not checked: {why}")
    return out


def _anim_rows_legacy(rep):
    """A report from before the checks were made per region (kept in older files)."""
    icon = {"pass": GOOD, "warn": WARN, "fail": BAD}
    c = rep.get("checks", {})
    out = [(icon.get(rep.get("grade"), WARN),
            {"pass": "Animation looks clean", "warn": "Animation: worth a look",
             "fail": "Animation: something breaks"}.get(rep.get("grade"), "Animation checked")
            + f" ({rep.get('frames', 0)} frames)")]
    if (rep.get("skinning") or {}).get("preserve_volume"):
        out.append((WARN, "    the rig blends with Preserve Volume on;"))
        out.append(("BLANK1", "      engines do not: build the rig again"))
    j = c.get("joints", {})
    if j:
        if j.get("frame") is None or j["grade"] == "pass":
            out.append((GOOD, "    joints keep their shape"))
        else:
            out.append((icon[j["grade"]], f"    {j['where'] or 'a joint'} thins to {j['value']:.0%}"))
            out.append(("BLANK1", f"      {_when(j['frame'], j.get('pose'))}"))
    k = c.get("skin", {})
    if k:
        if k["grade"] == "pass":
            out.append((GOOD, f"    skin stretch fine (up to {k['stretch']:.1f}x)"))
        else:
            if k["stretch"] > 1.5:
                out.append((icon[k["grade"]], f"    skin stretches {k['stretch']:.1f}x: {k['where']}"))
                out.append(("BLANK1", f"      {_when(k['frame'], k.get('pose'))}"))
                out.append(("BLANK1", "      (the texture smears there)"))
            if k["squash"] < 0.3:
                out.append((WARN, f"    skin squashes to {k['squash']:.0%}: {k['squash_where']}"))
                out.append(("BLANK1", f"      {_when(k['squash_frame'], k.get('squash_pose'))}"))
    x = c.get("crossing", {})
    if x:
        if not x.get("value"):
            out.append((GOOD, "    nothing passes through the body"))
        else:
            out.append((icon[x["grade"]], f"    {x['value']} faces pass through others"))
            out.append(("BLANK1", f"      worst in {_when(x['frame'], x.get('pose'))}"))
    w = c.get("weights", {})
    if w:
        if w.get("unweighted"):
            out.append((BAD, f"    {w['unweighted']} points no bone moves"))
        if (w.get("over") or {}).get("Unity"):
            out.append((WARN, f"    {w['over']['Unity']} points use more than 4 bones"))
            out.append(("BLANK1", "      (Unity takes 4: the weakest fade out; Unreal: fine)"))
        if not w.get("unweighted") and not (w.get("over") or {}).get("Unity"):
            out.append((GOOD, "    weights fine for Unreal and Unity"))
    return out


def draw_late(layout, context):
    st = st_of(context)
    busy = job_label()
    if busy:
        import time as _t
        box = layout.box()
        box.label(text=f"Working: {busy}...", icon="SORTTIME")
        secs = int(_t.time() - _JOB.get("started", _t.time()))
        now = ""
        for mod in ("retopo", "bake", "uv"):              # whichever step is running reports here
            try:
                now = now or S._mod(mod).STATUS.get("text", "")
            except Exception:                             # noqa: BLE001
                pass
        now = now or S.STATUS.get("text", "")
        if now:
            box.label(text=now[:60])
        box.label(text=f"{secs // 60} min {secs % 60:02d} s - leave Blender alone")
        row = box.row()
        row.alert = True
        row.operator("forge.stop_job", text="Stop", icon="CANCEL")
    if st.error:
        box = layout.box()
        col = box.column(align=True)
        col.alert = True
        import textwrap
        for i, line in enumerate(textwrap.wrap(st.error, 44)[:6]):
            col.label(text=line, icon="ERROR" if i == 0 else "BLANK1")

    prev_ok = st.repair == "approved"
    for stage in ("retopo", "uv", "bake", "colour", "rig", "export"):
        status = getattr(st, stage)
        box = layout.box()
        _header(box, stage, status)
        body = box.column()
        body.enabled = prev_ok and not busy
        if not prev_ok:
            body.label(text="Approve the step above first.")
        elif status != "approved":
            globals()["_draw_" + stage](body, st)
        prev_ok = status == "approved"


def _approve_btn(col, stage, text="Approve"):
    _btn(col, f"{stage}_approve", text, "CHECKMARK", 1.5)


def _draw_retopo(col, st):
    col.prop(st, "budget")
    split = S.budget_split(st.budget, st.report)
    if len(split) > 1:                       # props share the budget with the body
        c = col.column(align=True)
        c.label(text="Shared by the parts (by surface):", icon="INFO")
        for label, tris in split[:6]:
            c.label(text=f"   {label}: {tris:,} tris")
        if len(split) > 6:
            c.label(text=f"   + {len(split) - 6} more")
    col.prop(st, "detail", slider=True)
    c = col.column(align=True)
    c.prop(st, "symmetry")
    r = c.row(align=True)
    r.operator("forge.step", text="Left", icon="BACK").action = "retopo_side_left"
    r.operator("forge.step", text="Right", icon="FORWARD").action = "retopo_side_right"
    r.operator("forge.step", text="Best", icon="AUTO").action = "retopo_side_auto"
    r.operator("forge.step", text="", icon="X").action = "retopo_side_off"
    c = col.column(align=True)
    c.label(text="Detail map: red = more quads, cyan = fewer")
    r = c.row(align=True)
    r.operator("forge.step", text="Show / hide", icon="HIDE_OFF").action = "retopo_map"
    r.operator("forge.step", text="Paint", icon="BRUSH_DATA").action = "retopo_map_paint"
    r.operator("forge.step", text="Reset", icon="FILE_REFRESH").action = "retopo_map_reset"
    plan = S.plan_rows()
    if plan:
        c = col.column(align=True)
        c.label(text="Extra parts found:", icon="OUTLINER_OB_ARMATURE")
        for line in plan:
            c.label(text="   " + line)
        if S.plan_needed(st.symmetry):
            c.label(text="   (made for another symmetry choice: Show or Run updates it)", icon="INFO")
    _btn(col, "retopo_run", "Run retopology", "MOD_REMESH", 1.3)
    rep = json.loads(st.retopo_rep or "{}")
    if S.lows():
        col.operator("forge.step", text="Run for selected parts only", icon="RESTRICT_SELECT_OFF").action = \
            "retopo_run_selected"
    if st.retopo == "review" and rep:
        _rows(col.column(align=True), _retopo_rows(rep))
        if any(r.get("open_edges") or r.get("bad_edges") or r.get("loose") for r in rep.get("parts", {}).values()):
            col.operator("forge.step", text="Show the problem edges", icon="ZOOM_SELECTED").action = \
                "retopo_show_defects"
        row = col.row(align=True)
        row.operator("forge.step", text="Compare with original", icon="MOD_MIRROR").action = "retopo_compare"
        col.label(text="Press Z > Wireframe to see the quads.", icon="INFO")
        _approve_btn(col, "retopo")
        _btn(col, "retopo_undo", "Undo retopology", "CANCEL", alert=True)


COMPARE_HEAD = ("Engine", "Stretch", "Seams", "Islands", "Used", "Time")
COMPARE_LEGEND = ("Stretch: lower = the texture stays even (counts most)",
                  "Seams: total seam length, 1.0x = the shortest",
                  "Islands: separate pieces. Used: texture filled")


def _short_time(seconds) -> str:
    s = int(round(float(seconds or 0)))
    return f"{s} s" if s < 60 else f"{s // 60}:{s % 60:02d}"


def _compare_rows(rep):
    """Compare engines as a table: (header, [(icon, cells)], [(icon, note)])."""
    rows, notes = [], []
    winner = rep.get("winner", "")
    done = [r for r in rep.get("rows", []) if r.get("seams") is not None]
    shortest = min((float(r["seams"]) for r in done), default=0.0)
    for r in rep.get("rows", []):
        label = r.get("label") or r.get("engine", "")
        if r.get("engine") == "PARTUV" and r.get("split"):
            label += {"AI": " AI", "TREE": " tree", "GEOMETRIC": " geo"}.get(r["split"], "")
        if r.get("engine") == "XATLAS":
            label += " (fast)"
        if r.get("seams") is None:
            cells = (label, "-", "-", "-", "-", _short_time(r.get("seconds")))
        else:
            rel = float(r["seams"]) / shortest if shortest > 0 else 1.0
            cells = (label, f"{float(r.get('stretch', 0)):.2f}", f"{rel:.1f}x", str(r.get("islands", 0)),
                     f"{float(r.get('used', 0)):.0%}", _short_time(r.get("seconds")))
        icon = GOOD if r.get("engine") == winner else (WARN if not r.get("ok") else "BLANK1")
        rows.append((icon, cells))
        if not r.get("ok") and r.get("why"):
            name = r.get("label") or r.get("engine", "")
            notes += _wrapped(WARN, r["why"] if r["why"].startswith(name) else f"{name}: {r['why']}")
    if winner:
        lab = next((r.get("label") for r in rep.get("rows", []) if r.get("engine") == winner), winner)
        notes.insert(0, (GOOD, f"{lab} wins: {rep.get('why') or 'best result'}"))
        notes += _wrapped("INFO", f"Its UVs are on the model now. Auto uses {lab} for this model.")
    elif rep.get("rows"):
        notes += _wrapped(BAD, f"No winner: {rep.get('why') or 'no engine delivered every part'}. "
                               "The model is as it was.")
    elif rep.get("why"):
        notes += _wrapped(WARN, f"Not compared: {rep['why']}")
    return COMPARE_HEAD, rows, notes


def _draw_compare(col, rep, stale=False):
    head, rows, notes = _compare_rows(rep)
    box = col.box()
    if rows:
        grid = box.grid_flow(row_major=True, columns=len(head), even_columns=False, even_rows=False, align=True)
        for cell in head:
            grid.label(text=cell)
        for icon, cells in rows:
            for i, cell in enumerate(cells):
                grid.label(text=cell, icon=icon if i == 0 else "NONE")
    c = box.column(align=True)
    _rows(c, notes)
    if rows:
        for line in COMPARE_LEGEND:
            c.label(text=line)
    if stale:
        c.label(text="(made before the meshes changed: compare again)", icon="INFO")


def _auto_why(st, winner: str, used: str) -> str:
    """Why Auto uses this engine: the comparison's winner, or why not (the note below says what
    to do)."""
    if winner and used == winner:
        return "won Compare engines"
    try:
        cmp = json.loads(st.uv_compare_rep or "{}")
    except ValueError:
        cmp = {}
    if winner:
        label = next((r.get("label") for r in cmp.get("rows", []) if r.get("engine") == winner), winner)
        row = next((e for e in S.uv_engines() if e["id"] == winner), None)
        if row is None:
            return f"{label} won Compare engines, but your UVgami comes without it"
        if not row.get("available", True):
            return f"{label} won Compare engines, but doesn't run on this computer"
        return f"{label} won Compare engines, but isn't downloaded"
    if cmp.get("rows"):
        return "Compare engines found no winner"
    return "no comparison yet"


def _uv_engine_rows(st):
    """Which engine Unwrap + pack will use, in plain words."""
    out = []
    status = S.uvgami_status()
    if status:                                            # no UVgami (or no engine): Blender cuts
        return _wrapped(WARN, f"{status}: Blender's own unwrap cuts the seams"), {}
    winner = uv_winner(st)
    plan = S.uv_engine_plan(st.uv_engine, winner, st.partuv_split)
    if st.uv_engine == "AUTO" and plan.get("engine"):
        why = _auto_why(st, winner, plan["engine"])
        out += _wrapped("INFO", f"Auto uses {plan['label'].split(',')[0]} ({why})")
    if plan.get("note"):
        out += _wrapped(WARN, plan["note"])
    return out, plan


def _draw_uv(col, st):
    col.prop(st, "tex_size")
    col.prop(st, "uv_engine")
    rows, plan = _uv_engine_rows(st)
    if plan.get("engine") == "PARTUV" or st.uv_engine == "PARTUV":
        col.prop(st, "partuv_split")
    if rows:
        _rows(col.column(align=True), rows)
    _btn(col, "uv_run", "Unwrap + pack UVs", "UV", 1.3)
    have = [e for e in S.uv_engines() if e["installed"]]
    c = col.column(align=True)
    if len(have) >= 2:
        row = c.row(align=True)
        row.operator("forge.uv_compare", text="Compare engines", icon="SORTBYEXT")
        last = _last_unwrap_seconds(st)
        c.label(text=f"Unwraps {len(have)} times" + (f"; the last unwrap took {S._duration(last)}"
                                                       if last else ""), icon="INFO")
    elif have:                                # another engine this UVgami has, for this computer
        more = next((e for e in S.uv_engines() if not e["installed"] and e.get("available", True)), None)
        if more:
            c.label(text=f"Download {more['label']} in UVgami to compare engines", icon="INFO")
    cmp = json.loads(st.uv_compare_rep or "{}")
    if cmp.get("rows") or cmp.get("why"):
        _draw_compare(col, cmp, stale=bool(cmp.get("meshes")) and cmp.get("meshes") != S.uv_fingerprint())
        if cmp.get("winner"):
            _btn(col, "uv_compare_clear", "Forget the comparison", "X")
    rep = json.loads(st.uv_rep or "{}")
    if st.uv == "review" and rep:
        _rows(col.column(align=True), _uv_rows(rep))
        _btn(col, "uv_checker", "Checker on / off", "TEXTURE")
        _approve_btn(col, "uv")


def _draw_bake(col, st):
    col.label(text=f"Texture size: {int(st.tex_size) // 1024}K (set in step 5)")
    _btn(col, "bake_run", "Bake textures", "RENDER_STILL", 1.3)
    rep = json.loads(st.bake_rep or "{}")
    if st.bake == "review" and rep:
        _rows(col.column(align=True), _bake_rows(rep))
        col.label(text="Look for seams, stretched or blurry areas.", icon="INFO")
        _approve_btn(col, "bake")


def _draw_colour(col, st):
    _btn(col, "colour_show", "Show textured model", "SHADING_TEXTURE")
    c = col.column(align=True)
    c.label(text="Fix small spots (swatches = the texture's own colours):", icon="BRUSH_DATA")
    r = c.row(align=True)
    r.operator("forge.step", text="Paint selected part", icon="TPAINT_HLT").action = "colour_paint"
    r.operator("forge.step", text="Save paint", icon="FILE_TICK").action = "colour_save"
    c = col.column(align=True)
    c.label(text="Re-make the colour with AI (optional):", icon="SHADERFX")
    c.operator("forge.step", text="1. Export parts for Tripo", icon="EXPORT").action = "colour_tripo"
    c.operator("forge.import_retexture", text="2. Import re-textured part", icon="IMPORT")
    if st.colour == "review":
        _approve_btn(col, "colour", "Approve colour")
    else:
        _approve_btn(col, "colour", "Colour is fine - approve")


def _draw_rig(col, st):
    if st.rig_phase == "":
        col.label(text="Needs Auto-Rig Pro.", icon="INFO")
        _btn(col, "rig_place", "Place joints automatically", "BONE_DATA", 1.3)
        return
    rep = json.loads(st.rig_rep or "{}")
    if st.rig_phase == "joints":
        _rows(col.column(align=True), _rig_rows(rep))
        c = col.column(align=True)
        c.label(text="Check the joints (front + side view):", icon="INFO")
        c.label(text="  shoulders, elbows, wrists, hips,")
        c.label(text="  knees, ankles, neck, head, tail, ears.")
        _btn(col, "rig_edit", "Adjust joints", "EDITMODE_HLT")
        _btn(col, "rig_build", "Build rig + skin", "ARMATURE_DATA", 1.3)
        _btn(col, "rig_place", "Guess joints again", "FILE_REFRESH")
        return
    _rows(col.column(align=True), _rig_rows(rep))
    c = col.column(align=True)
    c.prop(st, "anim_clip", text="")
    row = c.row(align=True)
    row.scale_y = 1.3
    row.operator("forge.step", text="Play", icon="PLAY").action = "rig_anim"
    row.operator("forge.step", text="Stop", icon="PAUSE").action = "rig_pose_stop"
    col.label(text=S.CLIPS[st.anim_clip][1][:60], icon="INFO")
    if len(S.CLIPS[st.anim_clip][1]) > 60:
        col.label(text="  " + S.CLIPS[st.anim_clip][1][60:120])
    _btn(col, "rig_check", "Check it automatically", "VIEWZOOM")
    rep_a = json.loads(st.anim_rep or "{}")
    if rep_a.get("clip") == st.anim_clip:
        _rows(col.column(align=True), _anim_rows(rep_a))
        if rep_a.get("worst_frame"):
            col.operator("forge.step", text=f"Go to the worst frame ({rep_a['worst_frame']})",
                         icon="FRAME_NEXT").action = "rig_check_worst"
    else:
        col.label(text="Look for tearing, collapsing joints,", icon="INFO")
        col.label(text="props leaving the body.")
    _approve_btn(col, "rig")
    _btn(col, "rig_place", "Redo joints", "LOOP_BACK", alert=True)


def _draw_export(col, st):
    col.prop(st, "budget_unity")
    _btn(col, "export_run", "Export Unreal + Unity", "EXPORT", 1.3)
    rep = json.loads(st.export_rep or "{}")
    if st.export == "review" and rep:
        c = col.column(align=True)
        for engine, files in rep.items():
            n = len(files.get("meshes", {})) + sum(len(t) for t in files.get("textures", {}).values())
            c.label(text=f"{engine}: {n} files", icon=GOOD)
        _btn(col, "export_open", "Open export folder", "FILE_FOLDER")
        _approve_btn(col, "export", "Done")


@bpy.app.handlers.persistent
def _on_load(*_args):
    """A job cannot survive a file load (its timer is gone): forget it, clear old busy flags."""
    _JOB.clear()
    for sc in bpy.data.scenes:
        if hasattr(sc, "forge_stage") and sc.forge_stage.busy:
            sc.forge_stage.busy = ""


def register_handlers():
    if _on_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load)


def unregister_handlers():
    if _on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load)


def uv_winner(st) -> str:
    """The engine that won Compare engines for this model ('' before any comparison)."""
    try:
        return str(json.loads(st.uv_compare_rep or "{}").get("winner") or "")
    except ValueError:
        return ""


def _last_unwrap_seconds(st) -> float:
    try:
        return float(json.loads(st.uv_rep or "{}").get("seconds") or 0.0)
    except (ValueError, TypeError):
        return 0.0


class FORGE_OT_uv_compare(bpy.types.Operator):
    bl_idname = "forge.uv_compare"
    bl_label = "Compare engines"
    bl_options = {"REGISTER"}
    bl_description = ("Unwrap the model once with every UVgami engine you have downloaded, pack each "
                      "result the same way and show them side by side. The best one (least stretch, "
                      "then shortest seams, then fewest islands, then fastest) stays on the model and "
                      "becomes the Auto engine for it")

    @classmethod
    def poll(cls, context):
        return not job_running() and len([e for e in S.uv_engines() if e["installed"]]) >= 2

    def invoke(self, context, event):
        n, text = S.compare_warning(_last_unwrap_seconds(st_of(context)))
        return context.window_manager.invoke_confirm(self, event, title="Compare engines", message=text,
                                                     confirm_text=f"Unwrap {n} times", icon="QUESTION")

    def execute(self, context):
        st = st_of(context)
        if job_running():
            self.report({"WARNING"}, f"Still working: {job_label()}")
            return {"CANCELLED"}
        try:
            if context.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
        except RuntimeError as exc:
            st.error = f"RuntimeError: {exc}"
            return {"CANCELLED"}
        uvpm = S.has_addon_op("uvpackmaster4.pack")

        def done(st, res):
            res = dict(res or {})
            rep = res.pop("report", None) or {}
            _save_rep(st, "uv_compare_rep", res)
            if res.get("winner") and rep:          # the winner's UVs are on the model now
                _start_step(st, "uv")
                st.uv_engine = "AUTO"              # Auto = the winner, for this model
                _save_rep(st, "uv_rep", rep)
                st.uv = "review"
        run(st, S.UV_COMPARE_JOB, lambda: S.run_uv_compare(int(st.tex_size), uvpm, st.partuv_split), done)
        return {"FINISHED"}


class FORGE_OT_stop_job(bpy.types.Operator):
    bl_idname = "forge.stop_job"
    bl_label = "Stop"
    bl_description = ("Stop the running job (e.g. a Quad Remesher run that takes too long), remove its "
                      "half-done pieces and unlock the panel")

    def execute(self, context):
        gen = _JOB.get("gen")
        label = _JOB.get("label", "")
        _JOB.clear()                                  # the timer finds no job and stops
        if gen is not None:
            try:
                gen.close()
            except Exception:                         # noqa: BLE001
                pass
        S.stop_cleanup(label)
        st = st_of(context)
        if "retopo" in label:
            st.retopo = "todo"
            st.retopo_rep = "{}"
        st.error = "Stopped. Run the step again when ready (you can change the settings first)."
        _redraw()
        return {"FINISHED"}


CLASSES = (FORGE_OT_step, FORGE_OT_import_retexture, FORGE_OT_uv_compare, FORGE_OT_stop_job)
