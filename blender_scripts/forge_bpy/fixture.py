"""Stage: build a fake 'AI-generated' asset like Tripo returns - dense triangulated
meshes, a texture, optionally a skeleton with weights - exported as GLB.

Used by `forge setup-blender` (smoke test on the user's Blender) and by the tests.
args: {"out": "<path.glb>", "rigged": true}
"""

import bpy


def textured_material(name, color_a, color_b):
    img = bpy.data.images.new(name + "_tex", 128, 128)
    px = []
    for y in range(128):
        for x in range(128):
            c = color_a if ((x // 16 + y // 16) % 2) else color_b
            px.extend((*c, 1.0))
    img.pixels = px
    img.pack()
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = img
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.6
    bsdf.inputs["Metallic"].default_value = 0.2
    return mat


def dense(obj, levels=2):
    m = obj.modifiers.new("sub", "SUBSURF")
    m.levels = levels
    t = obj.modifiers.new("tri", "TRIANGULATE")
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.modifier_apply(modifier=m.name)
    bpy.ops.object.modifier_apply(modifier=t.name)


def run(args: dict) -> dict:
    if args.get("humanoid"):
        return humanoid(args)
    out = args["out"]
    rigged = bool(args.get("rigged", True))
    bpy.ops.wm.read_factory_settings(use_empty=True)

    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.3, location=(0, 0, 1.3), segments=32, ring_count=16)
    head = bpy.context.object
    bpy.ops.mesh.primitive_cylinder_add(radius=0.25, depth=1.0, location=(0, 0, 0.6), vertices=32)
    body = bpy.context.object
    bpy.ops.object.select_all(action="DESELECT")
    head.select_set(True); body.select_set(True)
    bpy.context.view_layer.objects.active = body
    bpy.ops.object.join()
    body.name = "Body"
    bpy.ops.object.mode_set(mode="EDIT"); bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(); bpy.ops.object.mode_set(mode="OBJECT")
    dense(body)
    body.data.materials.append(textured_material("BodyMat", (0.8, 0.2, 0.2), (0.9, 0.8, 0.3)))

    bpy.ops.mesh.primitive_cube_add(size=1, location=(0.45, 0, 0.8))
    sword = bpy.context.object
    sword.scale = (0.04, 0.08, 0.7)
    bpy.ops.object.transform_apply(scale=True)
    sword.name = "Sword"
    bpy.ops.object.mode_set(mode="EDIT"); bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(); bpy.ops.object.mode_set(mode="OBJECT")
    dense(sword, 1)
    sword.data.materials.append(textured_material("SwordMat", (0.6, 0.6, 0.7), (0.3, 0.3, 0.35)))

    if rigged:
        bpy.ops.object.armature_add(location=(0, 0, 0.1))
        arm = bpy.context.object
        bpy.ops.object.mode_set(mode="EDIT")
        eb = arm.data.edit_bones
        root = eb[0]; root.name = "pelvis"; root.head = (0, 0, 0); root.tail = (0, 0, 0.5)
        spine = eb.new("spine_01"); spine.head = (0, 0, 0.5); spine.tail = (0, 0, 1.0); spine.parent = root
        head_b = eb.new("head"); head_b.head = (0, 0, 1.0); head_b.tail = (0, 0, 1.6); head_b.parent = spine
        hand = eb.new("hand_r"); hand.head = (0.3, 0, 0.9); hand.tail = (0.45, 0, 0.9); hand.parent = spine
        bpy.ops.object.mode_set(mode="OBJECT")
        for ob, bones in ((body, None), (sword, "hand_r")):
            bpy.ops.object.select_all(action="DESELECT")
            ob.select_set(True); arm.select_set(True)
            bpy.context.view_layer.objects.active = arm
            if bones:
                bpy.ops.object.parent_set(type="ARMATURE_NAME")
                vg = ob.vertex_groups[bones]
                vg.add(list(range(len(ob.data.vertices))), 1.0, "REPLACE")
            else:
                bpy.ops.object.parent_set(type="ARMATURE_AUTO")

    bpy.ops.export_scene.gltf(filepath=out, export_format="GLB")
    return {"out": out, "rigged": rigged}


# ----------------------------------------------------------------------------- humanoid
# A T-pose test character with a UE5-Mannequin-like skeleton (or Mixamo names), facing -Y,
# like Tripo's biped output. Used to test the Auto-Rig Pro path.

UE_SKELETON = [  # name, parent, head, tail   (left = +X)
    ("pelvis", None, (0, 0, 0.95), (0, 0, 1.05)),
    ("spine_01", "pelvis", (0, 0, 1.05), (0, 0, 1.18)),
    ("spine_02", "spine_01", (0, 0, 1.18), (0, 0, 1.30)),
    ("spine_03", "spine_02", (0, 0, 1.30), (0, 0, 1.45)),
    ("neck_01", "spine_03", (0, 0, 1.45), (0, 0, 1.55)),
    ("head", "neck_01", (0, 0, 1.55), (0, 0, 1.80)),
]
for s, x in (("l", 1), ("r", -1)):
    UE_SKELETON += [
        (f"clavicle_{s}", "spine_03", (0.04 * x, 0, 1.42), (0.16 * x, 0, 1.42)),
        (f"upperarm_{s}", f"clavicle_{s}", (0.16 * x, 0, 1.42), (0.44 * x, 0, 1.42)),
        (f"lowerarm_{s}", f"upperarm_{s}", (0.44 * x, 0, 1.42), (0.70 * x, 0, 1.42)),
        (f"hand_{s}", f"lowerarm_{s}", (0.70 * x, 0, 1.42), (0.80 * x, 0, 1.42)),
        (f"thigh_{s}", "pelvis", (0.10 * x, 0, 0.92), (0.10 * x, 0, 0.50)),
        (f"calf_{s}", f"thigh_{s}", (0.10 * x, 0, 0.50), (0.10 * x, 0.02, 0.09)),
        (f"foot_{s}", f"calf_{s}", (0.10 * x, 0.02, 0.09), (0.10 * x, -0.10, 0.03)),
        (f"ball_{s}", f"foot_{s}", (0.10 * x, -0.10, 0.03), (0.10 * x, -0.17, 0.03)),
    ]
    for i, f in enumerate(("thumb", "index", "middle", "ring", "pinky")):
        y = (-0.03 + 0.015 * i)
        base = (0.80 * x, y, 1.42)
        for k in (1, 2, 3):
            h = (0.80 * x + 0.025 * (k - 1) * x, y, 1.42)
            t = (0.80 * x + 0.025 * k * x, y, 1.42)
            parent = f"hand_{s}" if k == 1 else f"{f}_0{k - 1}_{s}"
            UE_SKELETON.append((f"{f}_0{k}_{s}", parent, h, t))

MIXAMO = {"pelvis": "Hips", "spine_01": "Spine", "spine_02": "Spine1", "spine_03": "Spine2",
          "neck_01": "Neck", "head": "Head"}
for s, side in (("l", "Left"), ("r", "Right")):
    MIXAMO.update({f"clavicle_{s}": f"{side}Shoulder", f"upperarm_{s}": f"{side}Arm",
                   f"lowerarm_{s}": f"{side}ForeArm", f"hand_{s}": f"{side}Hand",
                   f"thigh_{s}": f"{side}UpLeg", f"calf_{s}": f"{side}Leg",
                   f"foot_{s}": f"{side}Foot", f"ball_{s}": f"{side}ToeBase"})
    for f in ("thumb", "index", "middle", "ring", "pinky"):
        for k in (1, 2, 3):
            MIXAMO[f"{f}_0{k}_{s}"] = f"{side}Hand{f.capitalize()}{k}"


def _limb(a, b, r):
    import mathutils
    a, b = mathutils.Vector(a), mathutils.Vector(b)
    bpy.ops.mesh.primitive_cylinder_add(vertices=12, radius=r, depth=(b - a).length, location=(a + b) / 2)
    o = bpy.context.active_object
    o.rotation_euler = (b - a).to_track_quat("Z", "Y").to_euler()
    return o


def humanoid(args: dict) -> dict:
    out = args["out"]
    naming = args.get("naming", "ue")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    parts = [_limb((0, 0, 0.9), (0, 0, 1.48), 0.16)]
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.12, location=(0, 0, 1.66))
    parts.append(bpy.context.active_object)
    for x in (1, -1):
        parts.append(_limb((0.12 * x, 0, 1.42), (0.80 * x, 0, 1.42), 0.045))
        parts.append(_limb((0.10 * x, 0, 0.95), (0.10 * x, 0.02, 0.06), 0.065))
        bpy.ops.mesh.primitive_cube_add(size=1, location=(0.10 * x, -0.06, 0.04))
        foot = bpy.context.active_object
        foot.scale = (0.08, 0.22, 0.07)
        parts.append(foot)
    for o in parts:
        o.select_set(True)
    bpy.context.view_layer.objects.active = parts[0]
    bpy.ops.object.join()
    body = bpy.context.active_object
    body.name = "Body"
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    bpy.ops.object.mode_set(mode="EDIT"); bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.remove_doubles(threshold=0.0001)
    bpy.ops.uv.smart_project(); bpy.ops.object.mode_set(mode="OBJECT")
    dense(body, 1)
    body.data.materials.append(textured_material("BodyMat", (0.3, 0.4, 0.8), (0.8, 0.7, 0.6)))

    bpy.ops.mesh.primitive_cube_add(size=1, location=(0.82, -0.05, 1.42))
    sword = bpy.context.active_object
    sword.scale = (0.03, 0.6, 0.06)
    bpy.ops.object.transform_apply(scale=True)
    sword.name = "Sword"
    bpy.ops.object.mode_set(mode="EDIT"); bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(); bpy.ops.object.mode_set(mode="OBJECT")
    sword.data.materials.append(textured_material("SwordMat", (0.6, 0.6, 0.7), (0.3, 0.3, 0.35)))

    bpy.ops.object.armature_add(location=(0, 0, 0))
    arm = bpy.context.active_object
    arm.name = "Armature"
    bpy.ops.object.mode_set(mode="EDIT")
    eb = arm.data.edit_bones
    eb.remove(eb[0])
    rename = (lambda n: "mixamorig:" + MIXAMO[n]) if naming == "mixamo" else (lambda n: n)
    for name, parent, h, t in UE_SKELETON:
        b = eb.new(rename(name))
        b.head, b.tail = h, t
        if parent:
            b.parent = eb[rename(parent)]
    bpy.ops.object.mode_set(mode="OBJECT")
    for ob, bone in ((body, None), (sword, rename("hand_r"))):
        bpy.ops.object.select_all(action="DESELECT")
        ob.select_set(True); arm.select_set(True)
        bpy.context.view_layer.objects.active = arm
        if bone:
            bpy.ops.object.parent_set(type="ARMATURE_NAME")
            ob.vertex_groups[bone].add(list(range(len(ob.data.vertices))), 1.0, "REPLACE")
        else:
            bpy.ops.object.parent_set(type="ARMATURE_AUTO")
    bpy.ops.export_scene.gltf(filepath=out, export_format="GLB")
    return {"out": out, "bones": len(arm.data.bones), "naming": naming}
