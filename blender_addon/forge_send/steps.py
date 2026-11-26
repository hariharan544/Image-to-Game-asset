"""Steps 4-9 of the in-Blender workflow (no UI). Each run_* returns a result dict or a
generator (it yields seconds to wait while an add-on engine works, then returns the dict);
stages_ui drives generators from a timer.

The mesh work reuses the pipeline's tested stage code (forge_bpy): a copy is installed
inside this add-on by `forge install-blender-addon`; in the repository it is imported
from blender_scripts/.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import bpy
from mathutils import Vector

from . import geometry as G


def fb():
    """The forge_bpy package (installed copy first, then the repository)."""
    try:
        from . import forge_bpy                     # noqa: F401
        return sys.modules[__package__ + ".forge_bpy"]
    except ImportError:
        root = Path(__file__).resolve().parents[2] / "blender_scripts"
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        import forge_bpy
        return forge_bpy


def _mod(name: str):
    import importlib
    pkg = fb()
    return importlib.import_module(f"{pkg.__name__}.{name}")


def C():
    return _mod("common")


def has_addon_op(path: str) -> bool:
    return _mod("addon_trial").has_op(path)


# ----------------------------------------------------------------------------- files

def work_dir() -> Path:
    """<blend folder>/<blend name>_forge - textures, exports, Tripo round trips."""
    if not bpy.data.filepath:
        raise RuntimeError("Save the .blend file first (Ctrl+S): textures and exports go next to it")
    p = Path(bpy.data.filepath)
    d = p.parent / f"{p.stem}_forge"
    d.mkdir(parents=True, exist_ok=True)
    return d


def asset_name() -> str:
    name = Path(bpy.data.filepath).stem if bpy.data.filepath else "asset"
    return C().safe_name(name).lower()


# ----------------------------------------------------------------------------- objects

def parts():
    return G.mesh_parts(bpy.context.scene)


def lows():
    return C().meshes_with_role("low")


def body_low():
    return next((o for o in lows() if G.kind(o) == "body"), None)


def _clear(role: str) -> None:
    for o in list(C().objects_with_role(role)):
        bpy.data.objects.remove(o)


def clear_rig() -> None:
    c = C()
    for o in list(bpy.data.objects):
        if o.type == "ARMATURE" and (o.get(c.ROLE_PROP) == "rig" or o.get("forge_arp") or o.get("forge_arp_helper")
                                     or o.get("forge_ref_rig")):
            bpy.data.objects.remove(o)
    for o in lows():
        for m in [m for m in o.modifiers if m.type == "ARMATURE"]:
            o.modifiers.remove(m)
        mw = o.matrix_world.copy()
        o.parent = None
        o.matrix_world = mw
        o.vertex_groups.clear()


# ----------------------------------------------------------------------------- step 4: retopology

def prepare_retopo() -> list:
    """Approved parts become the hidden 'high' sources; fresh copies become the 'low' meshes."""
    c = C()
    clear_rig()
    _clear("lod")
    _clear("low")
    # leftovers of a run that stopped half-way (rescue pieces, Quad Remesher results)
    for o in list(bpy.data.objects):
        if o.get("forge_rescue") or "_rescue" in o.name or o.name.startswith("Retopo_"):
            bpy.data.objects.remove(o)
    low_col = c.get_collection(c.LOW_COLLECTION)
    out = []
    ps = parts()
    for p in ps:
        p.location.x = 0.0                     # "Compare with original" may have moved it aside
    bpy.context.view_layer.update()            # matrix_world must see that before bounds are read
    for p in ps:
        part = c.safe_name(p.name)
        p[G.ROLE] = G.kind(p) or "prop"        # keep body/prop before forge_role becomes "high"
        p[c.PART_PROP] = part
        p[c.ROLE_PROP] = "high"
        low = c.duplicate(p, f"{part}_low")
        c.move_to_collection(low, low_col)
        low[c.ROLE_PROP] = "low"
        low[c.PART_PROP] = part
        low[G.ROLE] = p[G.ROLE]
        lo, hi = G.world_bounds(p)
        size = max(hi - lo)
        # mirror symmetry only for parts centred on the body's middle (body, bell, collar)
        # mirror symmetry only for parts centred on the body AND really symmetric: otherwise the
        # remesher copies one-sided details (a notch in one ear) to the other side
        centred = abs((lo.x + hi.x) / 2) < 0.02 * size
        asym = _mod("density").asymmetry(p.data) if centred else 1.0
        low["forge_asymmetry"] = round(asym, 4)
        low["forge_symmetry_x"] = centred and asym < 0.01
        p.hide_set(True)
        out.append(low)
    return out


def ensure_detail_maps(strength: float, recompute: bool = False) -> int:
    """Detail map on every original part (kept on it: the director may paint over it)."""
    dens = _mod("density")
    n = 0
    for p in parts():
        me = p.data
        if recompute or dens.QR_ATTR not in me.color_attributes:
            dens.write_qr_density(me, dens.detail_score(me), strength, make_active=False)
            if G.kind(p) == "body" and strength > 0:
                # thin extra parts (tail, ears, horns) collapse in a retopology: 4x density
                try:
                    import numpy as np
                    J = _mod("joints").estimate(p)
                    mask = np.zeros(len(me.vertices), bool)
                    for a in _mod("appendages").from_object(p, J):
                        mask[a["vert_idx"]] = True
                    if mask.any():
                        dens.boost(me, mask, rings=2)
                except Exception as exc:              # noqa: BLE001 - the map still works without
                    print(f"[forge] appendage search skipped: {exc}")
            n += 1
    return n


def show_detail_map(on: bool) -> None:
    """Show the originals coloured by the detail map: red = more quads, cyan = fewer, white = normal."""
    dens = _mod("density")
    for p in parts():
        me = p.data
        if dens.QR_ATTR not in me.color_attributes:
            continue
        if on:
            p["forge_prev_color"] = me.color_attributes.active_color_name or ""
            me.color_attributes.active_color_name = dens.QR_ATTR
        else:
            prev = p.get("forge_prev_color", "")
            if prev and prev in me.color_attributes:
                me.color_attributes.active_color_name = prev
    new = lows()
    for p in parts():                     # with new meshes present the map view swaps them
        p.hide_set(bool(new) and not on)
    for o in new:
        o.hide_set(on)


def run_retopo(budget: int, use_qr: bool = True, detail: float = 0.8):
    if use_qr and detail > 0:
        ensure_detail_maps(detail)
    prepare_retopo()
    if not (use_qr and detail > 0):              # no map: QR spreads quads by curvature only
        dens = _mod("density")
        for o in lows():
            a = o.data.color_attributes.get(dens.QR_ATTR)
            if a is not None:
                o.data.color_attributes.remove(a)
    args = {"method": "quadremesher" if use_qr else "quadriflow", "target_tris": int(budget),
            "min_tris_per_part": 300, "qr_timeout": 900}
    return _mod("retopo").run(args)


def stop_cleanup() -> None:
    """After Stop: drop half-done pieces and results, show the original parts again."""
    for o in list(bpy.data.objects):
        if o.get("forge_rescue") or "_rescue" in o.name or o.name.startswith("Retopo_"):
            bpy.data.objects.remove(o)
    try:
        retopo = _mod("retopo")
        retopo.STATUS["text"] = ""
    except Exception:                                 # noqa: BLE001
        pass
    for p in parts():
        p.hide_set(False)
    for o in lows():
        o.hide_set(False)


def clay_lows() -> None:
    """Plain grey on the new meshes until the bake (the original's material would show the
    density colours and confuse)."""
    mat = bpy.data.materials.get("FORGE_clay") or bpy.data.materials.new("FORGE_clay")
    mat.diffuse_color = (0.62, 0.62, 0.62, 1.0)
    for o in lows():
        o.data.materials.clear()
        o.data.materials.append(mat)
        a = o.data.color_attributes.get("QR_Density")
        if a is not None:
            o.data.color_attributes.remove(a)


def undo_retopo() -> None:
    clear_rig()
    _clear("lod")
    _clear("low")
    for p in parts():
        p.location.x = 0.0
        p.hide_set(False)
        for k in (C().ROLE_PROP,):
            if k in p:
                del p[k]


# ----------------------------------------------------------------------------- step 5: UVs

def run_uv(texture_size: int, use_uvpm: bool = True):
    args = {"packer": "uvpackmaster" if use_uvpm else "blender", "method": "angle_seams",
            "texture_size": int(texture_size), "margin_px": 8, "uvpm_search_time": 3}
    return _mod("uv").run(args)


CHECKER = "FORGE_UV_CHECKER"


def toggle_checker() -> bool:
    """Show a UV grid on every low mesh (squares should look square and even). Returns state."""
    objs = lows()
    on = not any(o.get("forge_checker") for o in objs)
    if on:
        img = bpy.data.images.get(CHECKER) or bpy.data.images.new(CHECKER, 1024, 1024)
        img.generated_type = "COLOR_GRID"
        mat = bpy.data.materials.get(CHECKER) or bpy.data.materials.new(CHECKER)
        mat.use_nodes = True
        nt = mat.node_tree
        bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
        tex = nt.nodes.get("checker") or nt.nodes.new("ShaderNodeTexImage")
        tex.name = "checker"
        tex.image = img
        nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
        for o in objs:
            o["forge_checker"] = ",".join(m.name if m else "" for m in o.data.materials)
            o.data.materials.clear()
            o.data.materials.append(mat)
    else:
        for o in objs:
            names = o.get("forge_checker", "")
            o.data.materials.clear()
            for n in names.split(","):
                if n and n in bpy.data.materials:
                    o.data.materials.append(bpy.data.materials[n])
            if "forge_checker" in o:
                del o["forge_checker"]
    return on


def checker_off() -> None:
    if any(o.get("forge_checker") for o in lows()):
        toggle_checker()


# ----------------------------------------------------------------------------- step 6: bake

COLOUR_MAPS = ("basecolor", "roughness", "metallic")
DETAIL_MAPS = ("normal", "ao")


def run_bake(texture_size: int, samples: int = 16, device: str = "GPU") -> dict:
    """Normal + AO from the repaired mesh; colour / roughness / metal from the original
    texture (the pre-repair copy when a part was welded solid, since welding drops UVs)."""
    checker_off()
    c, bake = C(), _mod("bake")
    tex_dir = work_dir() / "textures"
    args = {"texture_size": int(texture_size), "texture_dir": str(tex_dir), "samples": samples,
            "device": device, "cage_extrusion_ratio": 0.01, "margin_px": 16}
    swapped = {}
    for h in c.meshes_with_role("high"):
        src = bpy.data.meshes.get(h.get(G.BACKUP, "")) if h.get(G.BACKUP) else None
        if src is not None and not h.data.uv_layers and src.uv_layers:
            swapped[h.name] = h.data
    rep1 = bake.run({**args, "maps": list(DETAIL_MAPS)})
    for name in swapped:                                  # colour from the original texture
        h = bpy.data.objects[name]
        h.data = bpy.data.meshes[h[G.BACKUP]]
    try:
        rep2 = bake.run({**args, "maps": list(COLOUR_MAPS)})
    finally:
        for name, mesh in swapped.items():
            bpy.data.objects[name].data = mesh
        hide_highs()
    return finish_bake(rep1, rep2)


def hide_highs() -> None:
    """Baking selects (and so un-hides) the originals; they would sit on top of the new model."""
    for h in C().meshes_with_role("high"):
        h.hide_set(True)


def finish_bake(*reports) -> dict:
    bake = _mod("bake")
    out = {}
    for rep in reports:
        for part, r in rep.get("parts", {}).items():
            e = out.setdefault(part, {"maps": {}, "bake_misses": {}})
            if "skipped" in r:
                e["skipped"] = r["skipped"]
                continue
            e["maps"].update(r.get("maps", {}))
            e["bake_misses"].update(r.get("bake_misses", {}))
            if "metallic_cleanup" in r:
                e["metallic_cleanup"] = r["metallic_cleanup"]
    for low in lows():
        part = low.get(C().PART_PROP)
        e = out.get(part)
        if not e or not e["maps"]:
            continue
        e["bake_miss_ratio"] = round(max(e["bake_misses"].values(), default=0.0), 4)
        imgs = {}
        for k, path in e["maps"].items():
            img = bpy.data.images.get(f"T_{part}_{k}")
            if img is None or img.filepath_raw != path:
                img = bpy.data.images.load(path, check_existing=True)
            imgs[k] = img
        old = list(low.data.materials)
        bake._final_material(low, imgs)
        for m in old:
            if m and m.users == 0:
                bpy.data.materials.remove(m)
    return {"parts": out}


# ----------------------------------------------------------------------------- step 7: colour

def export_for_retexture() -> Path:
    """Low meshes (with our UVs) as one GLB per part, for Tripo Studio's texture tool."""
    d = work_dir() / "retexture"
    d.mkdir(exist_ok=True)
    c = C()
    for o in lows():
        c.select_only(o)
        kw = dict(filepath=str(d / f"{o.get(c.PART_PROP)}.glb"), export_format="GLB", use_selection=True)
        try:
            bpy.ops.export_scene.gltf(**kw, export_animations=False)
        except TypeError:
            bpy.ops.export_scene.gltf(**kw)
    return d


def _fit_to(src, target) -> None:
    """Uniform scale + move `src` so its bounding box matches `target` (Tripo re-centres models)."""
    G.apply_transform(src)
    slo, shi = G.world_bounds(src)
    tlo, thi = G.world_bounds(target)
    s = max(thi - tlo) / max(max(shi - slo), 1e-9)
    from mathutils import Matrix
    src.data.transform(Matrix.Translation((tlo + thi) / 2) @ Matrix.Scale(s, 4) @ Matrix.Translation(-(slo + shi) / 2))
    src.data.update()


def import_retexture(path: str, part: str, texture_size: int, samples: int = 16, device: str = "GPU") -> dict:
    """Bake the colour of a re-textured model (same shape) onto our low mesh's UVs."""
    c, bake = C(), _mod("bake")
    low = next((o for o in lows() if o.get(c.PART_PROP) == part), None)
    if low is None:
        raise RuntimeError(f"no low mesh for part {part}")
    before = {o.name for o in bpy.data.objects}
    ext = os.path.splitext(path)[1].lower()
    if ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=path)
    elif ext in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=path)
    else:
        raise RuntimeError("pick a .glb, .gltf or .fbx file")
    new = [o for o in bpy.data.objects if o.name not in before]
    meshes = [o for o in new if o.type == "MESH"]
    if not meshes:
        raise RuntimeError("the file has no mesh")
    src = meshes[0]
    if len(meshes) > 1:
        c.select_only(*meshes, active=src)
        bpy.ops.object.join()
    for o in new:
        if o.name in bpy.data.objects and o != src and o.type != "MESH":
            bpy.data.objects.remove(o)
    _fit_to(src, low)
    # bake against the re-textured model instead of the original high
    old_high = c.high_for(low)
    if old_high is not None:
        old_high[c.ROLE_PROP] = "high_keep"
    src[c.ROLE_PROP] = "high"
    src[c.PART_PROP] = part
    others = [o for o in lows() if o != low]
    for o in others:
        o[c.ROLE_PROP] = "low_keep"
    try:
        rep = bake.run({"texture_size": int(texture_size), "texture_dir": str(work_dir() / "textures"),
                        "samples": samples, "device": device, "cage_extrusion_ratio": 0.01,
                        "margin_px": 16, "maps": list(COLOUR_MAPS)})
    finally:
        for o in others:
            o[c.ROLE_PROP] = "low"
        if old_high is not None:
            old_high[c.ROLE_PROP] = "high"
        bpy.data.objects.remove(src)
        hide_highs()
    # one material again with the new colour and the earlier normal / AO maps
    imgs = {k: bpy.data.images.get(f"T_{part}_{k}") for k in COLOUR_MAPS + DETAIL_MAPS}
    imgs = {k: v for k, v in imgs.items() if v is not None}
    old = list(low.data.materials)
    bake._final_material(low, imgs)
    for m in old:
        if m and m.users == 0:
            bpy.data.materials.remove(m)
    return rep


def paint_setup(obj) -> str:
    """Texture Paint on the part's base colour map."""
    c = C()
    part = obj.get(c.PART_PROP)
    img = bpy.data.images.get(f"T_{part}_basecolor")
    if img is None:
        raise RuntimeError("bake the textures first (step 6)")
    c.select_only(obj)
    bpy.ops.object.mode_set(mode="TEXTURE_PAINT")
    ip = bpy.context.scene.tool_settings.image_paint
    ip.mode = "IMAGE"
    ip.canvas = img
    return img.name


def save_painted() -> int:
    n = 0
    for img in bpy.data.images:
        if img.name.startswith("T_") and img.is_dirty and img.filepath_raw:
            img.save()
            n += 1
    return n


# ----------------------------------------------------------------------------- step 8: rig

def place_joints() -> dict:
    """Guess the joints from the body's T-pose and put Auto-Rig Pro's reference bones there."""
    if not has_addon_op("arp.append_arp"):
        raise RuntimeError("Auto-Rig Pro is not enabled (Edit > Preferences > Add-ons)")
    body = body_low()
    if body is None:
        raise RuntimeError("no body mesh: finish step 4 first")
    clear_rig()
    joints = _mod("joints").estimate(body)
    rig, report = _mod("arp_rig").place(joints, lows(), {"arp_preset": "human"})
    # tail, ears... found on the body become Auto-Rig Pro limbs; face bones stay off for now
    try:
        apps = _mod("appendages").from_object(body, joints)
    except Exception as exc:                          # noqa: BLE001
        apps = []
        report["extras_error"] = str(exc)
    report["extras"] = _mod("arp_rig").add_extras(rig, apps, {})
    rig["forge_ref_rig"] = True
    report["ref_rig"] = rig.name
    return report


def ref_rig():
    return next((o for o in bpy.data.objects if o.type == "ARMATURE" and o.get("forge_ref_rig")
                 and not o.get("forge_arp")), None)


def edit_joints() -> None:
    rig = ref_rig()
    if rig is None:
        raise RuntimeError("place the joints first")
    C().select_only(rig)
    rig.show_in_front = True
    bpy.ops.object.mode_set(mode="EDIT")
    rig.data.use_mirror_x = True             # move a left joint, the right one follows


def build_rig(max_influences: int = 8) -> dict:
    rig = ref_rig()
    if rig is None:
        raise RuntimeError("place the joints first")
    C().ensure_object_mode()
    body = [o for o in lows() if G.kind(o) == "body"]
    props = [o for o in lows() if G.kind(o) != "body"]
    rep = _mod("arp_rig").finish(rig, body, props, {"max_influences": max_influences})
    arm = bpy.data.objects.get(rep["rig"])
    if arm is not None and "forge_ref_rig" in arm:
        del arm["forge_ref_rig"]
    w = {}
    metrics = _mod("metrics")
    for o in body:
        w[o.get(C().PART_PROP)] = metrics.weight_metrics(o, max_influences)
    rep["weights"] = w
    bad = [p for p, m in w.items() if not m.get("weighted")]
    if bad:
        raise RuntimeError(f"Auto-Rig Pro did not skin {', '.join(bad)} - check the joints and build again")
    return rep


def final_rig():
    return next((o for o in bpy.data.objects if o.type == "ARMATURE" and o.get("forge_arp")), None)


# pose test: (control bone candidates, world axis, degrees) per key frame
POSES = {
    15: [(("c_arm_fk.l",), "Y", -60), (("c_arm_fk.r",), "Y", 60), (("c_head.x",), "Z", 30)],
    30: [(("c_arm_fk.l",), "Z", 50), (("c_arm_fk.r",), "Z", -50), (("c_forearm_fk.l",), "Z", 60),
         (("c_forearm_fk.r",), "Z", -60), (("c_spine_02.x", "c_spine_01.x"), "X", 20)],
    45: [(("c_thigh_fk.l",), "X", -45), (("c_leg_fk.l",), "X", 70), (("c_thigh_fk.r",), "X", 30),
         (("c_neck.x",), "X", -20)],
}
FK_SWITCHES = (("c_hand_ik.l", "c_hand_ik.r", "c_foot_ik.l", "c_foot_ik.r"), "ik_fk_switch")


def pose_test() -> dict:
    """Key a few extreme poses on the rig's FK controls and play them."""
    import math

    from mathutils import Quaternion
    arm = final_rig()
    if arm is None:
        raise RuntimeError("build the rig first")
    if "forge_pose_switches" in arm:            # pressed twice: restore first, then start again
        pose_test_stop()
    C().select_only(arm)
    bpy.ops.object.mode_set(mode="POSE")
    pb = arm.pose.bones
    names, prop = FK_SWITCHES
    saved = {}
    for n in names:
        if n in pb and prop in pb[n]:
            saved[n] = pb[n][prop]
            pb[n][prop] = 1.0                                 # FK so rotations drive the limbs
    arm["forge_pose_switches"] = saved
    if arm.animation_data is None:
        arm.animation_data_create()
    act = bpy.data.actions.new("FORGE_pose_test")
    arm.animation_data.action = act
    used = set()
    sc = bpy.context.scene

    def rest_all(frame):
        for b in pb:
            b.rotation_mode = "QUATERNION"
            b.rotation_quaternion = (1, 0, 0, 0)
        for n in used:
            pb[n].keyframe_insert("rotation_quaternion", frame=frame)

    for frame, moves in POSES.items():
        for cands, _axis, _deg in moves:
            n = next((c for c in cands if c in pb), None)
            if n:
                used.add(n)
    rest_all(1)
    for frame, moves in POSES.items():
        for b in pb:
            b.rotation_quaternion = (1, 0, 0, 0)
        for cands, axis, deg in moves:
            n = next((c for c in cands if c in pb), None)
            if not n:
                continue
            bone = arm.data.bones[n]
            rest = bone.matrix_local.to_3x3()
            world = Quaternion(Vector({"X": (1, 0, 0), "Y": (0, 1, 0), "Z": (0, 0, 1)}[axis]),
                               math.radians(deg))
            local = (rest.inverted() @ world.to_matrix() @ rest).to_quaternion()
            pb[n].rotation_mode = "QUATERNION"
            pb[n].rotation_quaternion = local
        for n in used:
            pb[n].keyframe_insert("rotation_quaternion", frame=frame)
    rest_all(60)
    sc.frame_start, sc.frame_end = 1, 60
    sc.frame_set(1)
    bpy.ops.object.mode_set(mode="OBJECT")
    return {"controls_moved": sorted(used)}


def pose_test_stop() -> None:
    arm = final_rig()
    if arm is None:
        return
    if bpy.context.screen and bpy.context.screen.is_animation_playing:
        bpy.ops.screen.animation_cancel(restore_frame=False)
    if arm.animation_data and arm.animation_data.action and arm.animation_data.action.name.startswith("FORGE_pose"):
        act = arm.animation_data.action
        arm.animation_data.action = None
        bpy.data.actions.remove(act)
    for b in arm.pose.bones:
        b.rotation_quaternion = (1, 0, 0, 0)
        b.rotation_euler = (0, 0, 0)
        b.location = (0, 0, 0)
    for n, v in dict(arm.get("forge_pose_switches", {})).items():
        if n in arm.pose.bones:
            arm.pose.bones[n]["ik_fk_switch"] = v
    if "forge_pose_switches" in arm:
        del arm["forge_pose_switches"]
    bpy.context.scene.frame_set(1)


# ----------------------------------------------------------------------------- step 9: export

ENGINE_LODS = {"unreal": [1.0, 0.5, 0.25, 0.125], "unity": [1.0, 0.5, 0.25]}
ENGINE_INFLUENCES = {"unreal": 8, "unity": 4}


def _texture_maps(bake_report: dict) -> dict:
    return {part: r.get("maps", {}) for part, r in bake_report.get("parts", {}).items()}


def export_engine(engine: str, bake_report: dict, unity_budget: int = 0) -> dict:
    """LODs + engine FBX + packed textures. For Unity a lighter copy is made and removed again."""
    c, fin = C(), _mod("finalize")
    pose_test_stop()
    checker_off()
    c.ensure_object_mode()
    out_dir = work_dir() / "export" / engine
    originals = lows()
    temp = []
    try:
        if engine == "unity":
            # mobile: a lighter copy (the Unreal meshes and their 8-bone weights stay untouched)
            total = sum(c.tri_count(o) for o in originals)
            ratio = min(1.0, unity_budget / max(total, 1)) if unity_budget else 1.0
            for o in originals:
                d = c.duplicate(o, f"{o.name}_unity")
                temp.append(d)
                d[c.ROLE_PROP] = "low"
                o[c.ROLE_PROP] = "low_keep"
                if ratio < 0.98:
                    mod = d.modifiers.new("forge_mobile", "DECIMATE")
                    mod.ratio = ratio
                    mod.use_collapse_triangulate = True
                    c.select_only(d)
                    bpy.ops.object.modifier_move_to_index(modifier=mod.name, index=0)
                    bpy.ops.object.modifier_apply(modifier=mod.name)
        arm = c.find_armature()
        if arm is not None:
            deform = {b.name for b in arm.data.bones if b.use_deform}
            from importlib import import_module
            skin = import_module(f"{fb().__name__}.skin")
            for o in lows():
                if o.vertex_groups:
                    skin._cleanup_weights(o, ENGINE_INFLUENCES[engine], 0.01, deform)
        _clear("lod")
        lods = fin.lods({"lod_ratios": ENGINE_LODS[engine]})
        files = fin.export({"engine": engine, "asset_name": asset_name(), "export_dir": str(out_dir),
                            "texture_maps": _texture_maps(bake_report), "detachable_parts": [],
                            "unity_pipeline": "urp", "ao_into_basecolor": engine == "unity"})
        files["lods"] = lods.get("parts", {})
    finally:
        _clear("lod")
        for d in temp:
            bpy.data.objects.remove(d)
        for o in originals:
            o[c.ROLE_PROP] = "low"
            o.name = f"{o.get(c.PART_PROP)}_low"
    return files


def open_folder(path: Path) -> bool:
    import subprocess
    try:
        if sys.platform == "win32":
            os.startfile(str(path))            # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
        return True
    except OSError:
        print(f"[forge] folder: {path}")
        return False


def scene_ground_ok() -> bool:
    b = body_low()
    if b is None:
        return False
    lo, _ = G.world_bounds(b)
    return abs(lo.z) < 0.01 * max(b.dimensions)

