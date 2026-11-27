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
        run(st, "UV unwrap + pack", lambda: S.run_uv(int(st.tex_size), uvpm), done)

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
        rep = S.build_rig(8)
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


def _retopo_rows(rep):
    out = []
    for part, r in rep.get("parts", {}).items():
        m = str(r.get("method", ""))
        icon = GOOD if m.startswith("quadremesher") and "failed" not in m else (BAD if m.startswith("failed") else WARN)
        sh = r.get("shape")
        if sh and sh.get("lost_pct", 0) > 0.5:
            icon = WARN if sh.get("detail_only") else BAD
        out.append((icon, f"{part}: {r.get('tris_before', 0):,} > {r.get('tris_after', 0):,} tris"))
        if icon != GOOD and not (sh and sh.get("lost_pct", 0) > 0.5):
            out.append(("BLANK1", f"    method: {m}"))
        cr = r.get("creases") or {}
        if "left_pct" in cr or "right_pct" in cr:
            low_side = min(cr.get("left_pct", 100), cr.get("right_pct", 100))
            out.append(("BLANK1" if low_side >= 80 else WARN,
                        f"    face creases kept: left {cr.get('left_pct', '-')}%, "
                        f"right {cr.get('right_pct', '-')}%"
                        + (f" (+{cr.get('carved_tris', 0)} tris carved)" if cr.get("carved_tris") else "")))
        if "symmetry" in r:
            if r["symmetry"] and r.get("asymmetry_pct", 0) >= 1:
                out.append(("BLANK1", f"    mirrored, then fitted ({r['asymmetry_pct']}% one-sided)"))
            else:
                out.append(("BLANK1", "    mirrored (symmetric)" if r["symmetry"]
                            else f"    not mirrored ({r.get('asymmetry_pct', 0)}% one-sided detail)"))
        if r.get("separate_parts"):
            out.append(("BLANK1", f"    {r['separate_parts']} part(s) remeshed on their own, then attached"))
        for how in r.get("piece_fallbacks", []):
            out.append((WARN, f"    a part got no Quad Remesher result: {how} used"))
        for why in r.get("split_kept", []):
            out.append((WARN, f"    {why}"))
        if r.get("open_edges") or r.get("bad_edges") or r.get("loose"):
            out.append((BAD, f"    not clean: {r.get('open_edges', 0)} open, {r.get('bad_edges', 0)} broken, "
                             f"{r.get('loose', 0)} loose edges"))
            out.append(("BLANK1", "    Show the problem edges (button below)"))
        if r.get("stacked"):
            out.append((BAD, f"    not clean: {r['stacked']} faces / points on top of each other"))
            out.append(("BLANK1", "    UVgami and the bake need each face in its own place"))
        t = r.get("tidied") or {}
        if any(t.values()):
            bits = [f"{t['welded']} doubled points welded" if t.get("welded") else "",
                    f"{t['stacked']} stacked faces removed" if t.get("stacked") else "",
                    "openings rebuilt" if t.get("rebuilt") else ""]
            out.append(("BLANK1", "    cleaned: " + ", ".join(b for b in bits if b)))
        if sh:
            if sh.get("lost_pct", 0) > 0.5 and sh.get("detail_only"):
                out.append(("BLANK1", f"    fine detail flattened: {sh['lost_pct']}% (curls, twists)"))
                out.append(("BLANK1", "    the bake keeps it as a normal map; for real geometry:"))
                out.append(("BLANK1", "    raise Triangles or paint it red, run again"))
            elif sh.get("lost_pct", 0) > 0.5:
                out.append(("BLANK1", f"    shape lost: {sh['lost_pct']}% (gap {sh['max_gap_pct']}% of size)"))
                out.append(("BLANK1", "    paint the lost part red (Paint), run again"))
            if sh.get("rescue_undone"):
                out.append((WARN, "    rebuilding a lost part was undone (it left openings)"))
            else:
                fixed = f", fixed {sh['refined']}x" if sh.get("refined") else ""
                if "face-refined" in m:
                    fixed += ", face details refined"
                if sh.get("rescued"):
                    fixed += f", {sh['rescued']} thin part(s) rebuilt"
                out.append(("BLANK1", f"    shape kept{fixed}"))
    for name in rep.get("missing", []):
        out.append((WARN, f"{name}: no new mesh yet - select it, Run for selected parts"))
    if rep.get("total_tris"):
        out.append(("INFO", f"total {rep['total_tris']:,} triangles"))
    reg = rep.get("regions") or {}
    if reg:
        tot = max(sum(reg.values()), 1)
        order = sorted(reg.items(), key=lambda kv: -kv[1])
        line = ", ".join(f"{k} {100 * v // tot}%" for k, v in order[:4])
        out.append(("BLANK1", f"    {line}"))
        if len(order) > 4:
            out.append(("BLANK1", "    " + ", ".join(f"{k} {100 * v // tot}%" for k, v in order[4:])))
    return out


def _uv_rows(rep):
    out = []
    if rep.get("uvgami"):
        out.append((WARN, rep["uvgami"][:60]))
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
                words, line = note[len("UVgami: "):].split(), "    UVgami:"
                for w in words:
                    if len(line) + len(w) > 44:
                        out.append(("BLANK1", line))
                        line = "     "
                    line += " " + w
                out.append(("BLANK1", line))
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
            out.append((BAD, f"{part}: {r['skipped']}"))
            continue
        inv = r.get("invalid_texels_max")
        if inv is None:                         # a report from before the rays were checked
            miss = r.get("bake_miss_ratio", 0)
            icon = GOOD if miss <= 0.02 else (WARN if miss <= 0.10 else BAD)
            out.append((icon, f"{part}: {len(r.get('maps', {}))} maps, {miss:.1%} patched"))
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
                out.append(("BLANK1", f"    {inv:.1%} of the texture could not be baked cleanly"))
                out.append(("BLANK1", "    and was patched from nearby"))
            elif both < 0.0005:
                out.append(("BLANK1", "    the whole texture baked cleanly"))
            if both >= 0.0005:
                out.append(("BLANK1", f"    {both:.1%} comes from open, paper-thin pieces of the original:"))
                out.append(("BLANK1", "    there the bake cannot be checked (Step 3: Weld into one solid,"))
                out.append(("BLANK1", "    then bake again)"))
        spots = int((r.get("cage") or {}).get("unenclosed", 0))
        if spots:                               # a warning only when the patching is not small
            sev = "INFO" if inv is not None and inv <= 0.02 else WARN
            out.append((sev, f"    {spots:,} places where the new mesh is too coarse or folded"))
            out.append(("BLANK1", "    to bake cleanly (Step 4: more triangles there, then bake again)"))
        sp = sum((r.get("specks_removed") or {}).values())
        if sp:
            out.append(("BLANK1", f"    {sp:,} specks cleaned"))
    return out


def _rig_rows(rep):
    out = []
    ex = rep.get("extras") or {}
    for k, n in (ex.get("added") or {}).items():
        out.append((GOOD, f"{k}: {n} bones"))
    for k, why in (ex.get("skipped") or {}).items():
        out.append(("INFO", f"{k}: {why}"))
    for e in (ex.get("errors") or [])[:3]:
        out.append((BAD, e[:60]))
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
    return out


def _anim_rows(rep):
    """The automatic checks of one clip, in plain words."""
    icon = {"pass": GOOD, "warn": WARN, "fail": BAD}
    c = rep.get("checks", {})
    out = [(icon.get(rep.get("grade"), WARN),
            {"pass": "Animation looks clean", "warn": "Animation: worth a look",
             "fail": "Animation: something breaks"}.get(rep.get("grade"), "Animation checked")
            + f" ({rep.get('frames', 0)} frames)")]
    j = c.get("joints", {})
    if j:
        if j.get("frame") is None or j["grade"] == "pass":
            out.append((GOOD, "    joints keep their shape"))
        else:
            out.append((icon[j["grade"]], f"    {j['where'] or 'a joint'} thins to {j['value']:.0%}"))
            out.append(("BLANK1", f"      at frame {j['frame']} (collapsing joint)"))
    k = c.get("skin", {})
    if k:
        if k["grade"] == "pass":
            out.append((GOOD, f"    skin stretch fine (up to {k['stretch']:.1f}x)"))
        else:
            if k["stretch"] > 1.5:
                out.append((icon[k["grade"]], f"    skin stretches {k['stretch']:.1f}x: {k['where']}"))
                out.append(("BLANK1", f"      at frame {k['frame']} (texture smears there)"))
            if k["squash"] < 0.3:
                out.append((WARN, f"    skin squashes to {k['squash']:.0%}: {k['squash_where']}"))
                out.append(("BLANK1", f"      at frame {k['squash_frame']}"))
    x = c.get("crossing", {})
    if x:
        if not x.get("value"):
            out.append((GOOD, "    nothing passes through the body"))
        else:
            out.append((icon[x["grade"]], f"    {x['value']} faces pass through others"))
            out.append(("BLANK1", f"      worst at frame {x['frame']}"))
    w = c.get("weights", {})
    if w:
        if w.get("unweighted"):
            out.append((BAD, f"    {w['unweighted']} points no bone moves"))
        if (w.get("over") or {}).get("Unity"):
            out.append((WARN, f"    {w['over']['Unity']} points use more than 4 bones"))
            out.append(("BLANK1", "      (Unity keeps the 4 strongest; Unreal: fine)"))
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


def _draw_uv(col, st):
    col.prop(st, "tex_size")
    _btn(col, "uv_run", "Unwrap + pack UVs", "UV", 1.3)
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


CLASSES = (FORGE_OT_step, FORGE_OT_import_retexture, FORGE_OT_stop_job)
