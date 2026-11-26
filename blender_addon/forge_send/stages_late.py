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

ORDER = ["assemble", "repair", "retopo", "uv", "bake", "colour", "rig", "export"]
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
    for later in ORDER[i + 1:]:
        setattr(st, later, "todo")
    if i <= ORDER.index("rig"):
        st.rig_phase = ""


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
    "export_run": "Make LODs and export Unreal (AAA) and Unity (mobile) files + a GLB preview",
    "export_open": "Open the export folder",
}


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
            _save_rep(st, "retopo_rep", rep)
            st.retopo = "review"
        run(st, "retopology (Quad Remesher)" if qr else "retopology",
            lambda: S.run_retopo(st.budget, qr, st.detail), done)

    def do_retopo_map(self, context, st):
        S.ensure_detail_maps(st.detail)
        on = not st.get("detail_view", False)
        st["detail_view"] = on
        S.show_detail_map(on)
        for area in context.screen.areas:
            if area.type == "VIEW_3D":
                sh = area.spaces.active.shading
                sh.type = "SOLID"
                sh.color_type = "VERTEX" if on else "MATERIAL"

    def do_retopo_map_reset(self, context, st):
        n = S.ensure_detail_maps(st.detail, recompute=True)
        self.report({"INFO"}, f"Detail map made again for {n} part(s)")

    def do_retopo_map_paint(self, context, st):
        o = context.active_object
        if o is None or o not in S.parts():
            o = S.G.body_of(S.parts())
        S.ensure_detail_maps(st.detail)
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
        rep = S.build_rig(8)
        _save_rep(st, "rig_rep", rep)
        st.rig_phase = "built"

    def do_rig_pose(self, context, st):
        S.pose_test()
        try:
            bpy.ops.screen.animation_play()
        except RuntimeError:
            pass

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
            icon = BAD
        out.append((icon, f"{part}: {r.get('tris_before', 0):,} > {r.get('tris_after', 0):,} tris"))
        if icon != GOOD and not (sh and sh.get("lost_pct", 0) > 0.5):
            out.append(("BLANK1", f"    method: {m}"))
        if "symmetry" in r:
            if r["symmetry"] and r.get("asymmetry_pct", 0) >= 1:
                out.append(("BLANK1", f"    mirrored, then fitted ({r['asymmetry_pct']}% one-sided)"))
            else:
                out.append(("BLANK1", "    mirrored (symmetric)" if r["symmetry"]
                            else f"    not mirrored ({r.get('asymmetry_pct', 0)}% one-sided detail)"))
        if sh:
            if sh.get("lost_pct", 0) > 0.5:
                out.append(("BLANK1", f"    shape lost: {sh['lost_pct']}% (gap {sh['max_gap_pct']}% of size)"))
                out.append(("BLANK1", "    paint the lost part red (Paint), run again"))
            else:
                fixed = f", fixed {sh['refined']}x" if sh.get("refined") else ""
                if sh.get("rescued"):
                    fixed += f", {sh['rescued']} thin part(s) rebuilt"
                out.append(("BLANK1", f"    shape kept{fixed}"))
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
    for part, r in rep.get("parts", {}).items():
        if not r.get("has_uv"):
            out.append((BAD, f"{part}: no UVs"))
            continue
        over, cv = r.get("overlap_pct", 0), r.get("texel_density_cv") or 0
        icon = BAD if over > 0.5 else (WARN if cv > 0.4 or "uvpackmaster" not in str(r.get("packer")) else GOOD)
        out.append((icon, f"{part}: {r.get('utilization', 0):.0%} used, stretch {cv:.2f}"))
        if over > 0.5:
            out.append(("BLANK1", f"    {over:.1f}% overlapping"))
    return out


def _bake_rows(rep):
    out = []
    for part, r in rep.get("parts", {}).items():
        if r.get("skipped"):
            out.append((BAD, f"{part}: {r['skipped']}"))
            continue
        miss = r.get("bake_miss_ratio", 0)
        icon = GOOD if miss <= 0.02 else (WARN if miss <= 0.10 else BAD)
        out.append((icon, f"{part}: {len(r.get('maps', {}))} maps, {miss:.1%} filled"))
        sp = sum((r.get("specks_removed") or {}).values())
        if sp:
            out.append(("BLANK1", f"    {sp:,} speck texels cleaned"))
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


def draw_late(layout, context):
    st = st_of(context)
    busy = job_label()
    if busy:
        import time as _t
        box = layout.box()
        box.label(text=f"Working: {busy}...", icon="SORTTIME")
        secs = int(_t.time() - _JOB.get("started", _t.time()))
        now = ""
        for mod in ("retopo", "bake"):                    # whichever step is running reports here
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
    col.prop(st, "detail", slider=True)
    c = col.column(align=True)
    c.label(text="Detail map: red = more quads, cyan = fewer")
    r = c.row(align=True)
    r.operator("forge.step", text="Show / hide", icon="HIDE_OFF").action = "retopo_map"
    r.operator("forge.step", text="Paint", icon="BRUSH_DATA").action = "retopo_map_paint"
    r.operator("forge.step", text="Reset", icon="FILE_REFRESH").action = "retopo_map_reset"
    _btn(col, "retopo_run", "Run retopology", "MOD_REMESH", 1.3)
    rep = json.loads(st.retopo_rep or "{}")
    if st.retopo == "review" and rep:
        _rows(col.column(align=True), _retopo_rows(rep))
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
    row = col.row(align=True)
    row.scale_y = 1.3
    row.operator("forge.step", text="Pose test", icon="PLAY").action = "rig_pose"
    row.operator("forge.step", text="Stop", icon="PAUSE").action = "rig_pose_stop"
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
