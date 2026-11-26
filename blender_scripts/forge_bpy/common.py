"""Shared helpers for Forge stages running inside Blender (or the `bpy` module).

Nothing in this package may import third-party modules other than numpy,
which ships with Blender.
"""

from __future__ import annotations

import bpy

HIGH_COLLECTION = "FORGE_HIGH"   # untouched AI meshes, used as bake / weight sources
LOW_COLLECTION = "FORGE_LOW"     # game meshes being built
LOD_COLLECTION = "FORGE_LOD"
RIG_COLLECTION = "FORGE_RIG"

PART_PROP = "forge_part"         # custom property: logical part name on every object
ROLE_PROP = "forge_role"         # "high" | "low" | "lod" | "rig"


def ensure_object_mode() -> None:
    if bpy.context.view_layer.objects.active and bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")


def get_collection(name: str, hide_render: bool = False) -> bpy.types.Collection:
    coll = bpy.data.collections.get(name)
    if coll is None:
        coll = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(coll)
    coll.hide_render = hide_render
    return coll


def move_to_collection(obj: bpy.types.Object, coll: bpy.types.Collection) -> None:
    for c in list(obj.users_collection):
        c.objects.unlink(obj)
    coll.objects.link(obj)


def select_only(*objs: bpy.types.Object, active: bpy.types.Object | None = None) -> None:
    ensure_object_mode()
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    for o in objs:
        o.hide_set(False)
        o.select_set(True)
    bpy.context.view_layer.objects.active = active or (objs[0] if objs else None)


def objects_with_role(role: str) -> list[bpy.types.Object]:
    return [o for o in bpy.data.objects if o.get(ROLE_PROP) == role]


def meshes_with_role(role: str) -> list[bpy.types.Object]:
    return [o for o in objects_with_role(role) if o.type == "MESH"]


def find_armature() -> bpy.types.Object | None:
    """The asset's skeleton: an Auto-Rig Pro rig if one was built, else the source rig.
    ARP helper armatures (e.g. rig_add) are never returned."""
    arms = [o for o in bpy.data.objects if o.type == "ARMATURE" and not o.get("forge_arp_helper")]
    for pick in (lambda o: o.get("forge_arp"), lambda o: o.get(ROLE_PROP) == "rig", lambda o: True):
        hit = next((o for o in arms if pick(o)), None)
        if hit is not None:
            return hit
    return None


def high_for(low: bpy.types.Object) -> bpy.types.Object | None:
    part = low.get(PART_PROP)
    for o in meshes_with_role("high"):
        if o.get(PART_PROP) == part:
            return o
    return None


def tri_count(obj: bpy.types.Object) -> int:
    me = obj.data
    me.calc_loop_triangles()
    return len(me.loop_triangles)


def apply_modifier(obj: bpy.types.Object, mod_name: str) -> None:
    select_only(obj)
    bpy.ops.object.modifier_apply(modifier=mod_name)


def duplicate(obj: bpy.types.Object, name: str) -> bpy.types.Object:
    new = obj.copy()
    new.data = obj.data.copy()
    new.name = name
    new.data.name = name
    for c in obj.users_collection:
        c.objects.link(new)
    return new


def safe_name(text: str) -> str:
    out = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in text)
    return out.strip("_") or "part"
