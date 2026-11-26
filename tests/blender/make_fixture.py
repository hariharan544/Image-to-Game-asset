"""Build a fake 'AI-generated' asset like Tripo returns: dense triangulated meshes,
a baked texture, optionally a skeleton with weights. Exported as GLB.

    python make_fixture.py <out.glb> [--rigged]
"""

import sys

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


def main():
    out = sys.argv[1]
    rigged = "--rigged" in sys.argv
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


main()
