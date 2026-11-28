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


# (field, values per element, numpy type) to read and write each kind of attribute
_ATTR_FIELDS = {"FLOAT": ("value", 1, "f4"), "INT": ("value", 1, "i4"), "INT8": ("value", 1, "i4"),
                "BOOLEAN": ("value", 1, "?"), "FLOAT_VECTOR": ("vector", 3, "f4"),
                "FLOAT2": ("vector", 2, "f4"), "INT32_2D": ("value", 2, "i4"),
                "FLOAT_COLOR": ("color", 4, "f4"), "BYTE_COLOR": ("color_srgb", 4, "f4"),
                "QUATERNION": ("value", 4, "f4")}


def _tied_by_neighbours(me, co, order):
    """`order` (vertices sorted by place) with every run of points on the very same spot put
    in the order of their neighbours' places, then of the faces around them (each face as the
    places of its corners, from its lowest on, in its own winding): two points on one spot are
    then told apart by the surface around them, not by the order they came in (a result built
    in threads can give them in either order). Two that still tie have their neighbours on the
    same spots and the same faces around them, wound the same way - copies of each other, a
    doubled sheet - and keep the order they came in."""
    import numpy as np
    s = co[order]
    same = np.all(s[1:] == s[:-1], axis=1)
    if not same.any():
        return order
    place = np.empty(len(co), np.int64)
    place[order] = np.cumsum(np.concatenate([[0], ~same]))      # one number per spot
    tied = np.zeros(len(co), bool)
    tied[order[1:][same]] = True
    tied[order[:-1][same]] = True
    ev = np.empty(len(me.edges) * 2, np.int64)
    me.edges.foreach_get("vertices", ev)
    ev = ev.reshape(-1, 2)
    ev = ev[tied[ev[:, 0]] | tied[ev[:, 1]]]
    around: dict = {}
    for a, b in ev.tolist():
        around.setdefault(a, []).append(int(place[b]))
        around.setdefault(b, []).append(int(place[a]))
    # the faces with a tied corner (two back-to-back faces on the same corners differ only in
    # their winding)
    nf = len(me.polygons)
    lt = np.empty(nf, np.int64)
    me.polygons.foreach_get("loop_total", lt)
    ls = np.empty(nf, np.int64)
    me.polygons.foreach_get("loop_start", ls)
    lv = np.empty(len(me.loops), np.int64)
    me.loops.foreach_get("vertex_index", lv)
    faces: dict = {}
    for f in np.unique(np.repeat(np.arange(nf), lt)[tied[lv]]).tolist():
        corners = lv[ls[f]:ls[f] + lt[f]].tolist()
        pl = [int(place[v]) for v in corners]
        key = min(tuple(pl[i:] + pl[:i]) for i in range(len(pl)))
        for v in corners:
            if tied[v]:
                faces.setdefault(v, []).append(key)
    out = order.copy()
    starts = np.nonzero(np.concatenate([[True], ~same]))[0].tolist() + [len(order)]
    for i, j in zip(starts, starts[1:]):
        if j - i > 1:
            run = order[i:j].tolist()
            out[i:j] = sorted(run, key=lambda v: (sorted(around.get(v, [])), sorted(faces.get(v, []))))
    return out


def canonical_order(me, by_position: bool = False) -> bool:
    """Rewrite a mesh with its faces in one fixed order: each face starting at its lowest
    vertex, the faces sorted by their corners; every attribute goes with its element. Some
    Blender operators (the UV sphere, spin, extrude) make faces and edges in memory-address
    order, which changes from run to run: the same surface then comes in another order, and
    a subdivision or a remesher makes a different mesh of it. The vertices keep their order,
    or with `by_position` are sorted by where they are (x, then y, then z: for a result whose
    vertex order itself changes from run to run - the exact boolean works in threads). Points
    on the very same spot are told apart by their neighbours and faces, never by the order
    they came in (see _tied_by_neighbours). False (left as it is) for a mesh with shape keys,
    vertex weights or an attribute of a kind it cannot carry across (custom split normals,
    matrices, text): rather unordered than missing data."""
    import numpy as np
    nf, nl, nv = len(me.polygons), len(me.loops), len(me.vertices)
    if not nf or me.shape_keys or any(v.groups for v in me.vertices):
        return False
    if any(not a.is_internal and a.name != "position" and a.data_type not in _ATTR_FIELDS for a in me.attributes):
        return False
    co = np.empty(nv * 3, np.float32)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    vperm = np.lexsort((co[:, 2], co[:, 1], co[:, 0])) if by_position else np.arange(nv)
    if by_position:
        vperm = _tied_by_neighbours(me, co, vperm)
    vnew = np.empty(nv, np.int64)
    vnew[vperm] = np.arange(nv)                     # old vertex -> its new number
    lv = np.empty(nl, np.int64)
    me.loops.foreach_get("vertex_index", lv)
    lv = vnew[lv]
    ls = np.empty(nf, np.int64)
    me.polygons.foreach_get("loop_start", ls)
    lt = np.empty(nf, np.int64)
    me.polygons.foreach_get("loop_total", lt)
    lvl = lv.tolist()
    key, rot = [], []
    for s, t in zip(ls.tolist(), lt.tolist()):
        f = lvl[s:s + t]
        i = f.index(min(f))
        key.append(f[i:] + f[:i])
        rot.append(list(range(s + i, s + t)) + list(range(s, s + i)))
    order = sorted(range(nf), key=key.__getitem__)
    fperm = np.array(order, np.int64)
    cperm = np.array([c for k in order for c in rot[k]], np.int64)
    ev = np.empty(len(me.edges) * 2, np.int64)
    me.edges.foreach_get("vertices", ev)
    ev = vnew[ev].reshape(-1, 2)
    old_edge = {tuple(sorted(p)): i for i, p in enumerate(ev.tolist())}
    le = np.empty(nl, np.int64)
    me.loops.foreach_get("edge_index", le)
    used = np.zeros(len(ev), bool)
    used[le] = True
    loose = sorted(tuple(sorted(p)) for p in ev[~used].tolist())     # (edges no face uses: kept too)
    saved = []
    for a in me.attributes:
        if a.is_internal or a.name == "position" or a.data_type not in _ATTR_FIELDS:
            continue
        field, w, dt = _ATTR_FIELDS[a.data_type]
        buf = np.empty(len(a.data) * w, dt)
        a.data.foreach_get(field, buf)
        saved.append((a.name, a.domain, a.data_type, field, buf.reshape(len(a.data), w)))
    uv_active = me.uv_layers.active.name if me.uv_layers.active else None
    col_active = me.color_attributes.active_color_name
    me.clear_geometry()
    me.vertices.add(nv)
    me.vertices.foreach_set("co", co[vperm].ravel())
    me.loops.add(nl)
    me.loops.foreach_set("vertex_index", lv[cperm].astype(np.int32))
    me.polygons.add(nf)
    me.polygons.foreach_set("loop_start", (np.cumsum(lt[fperm]) - lt[fperm]).astype(np.int32))
    me.update(calc_edges=True)
    ev = np.empty(len(me.edges) * 2, np.int64)
    me.edges.foreach_get("vertices", ev)
    if loose:
        ev = np.concatenate([ev, np.array(loose, np.int64).ravel()])
        me.edges.add(len(loose))
        me.edges.foreach_set("vertices", ev.astype(np.int32))
    eperm = np.array([old_edge.get(tuple(sorted(p)), -1) for p in ev.reshape(-1, 2).tolist()], np.int64)
    for name, domain, data_type, field, buf in saved:
        if domain == "POINT":
            buf = buf[vperm]
        elif domain == "FACE":
            buf = buf[fperm]
        elif domain == "CORNER":
            buf = buf[cperm]
        elif domain == "EDGE":
            buf = np.where((eperm >= 0)[:, None], buf[np.maximum(eperm, 0)], np.zeros_like(buf[:1]))
        a = me.attributes.get(name)
        if a is None:
            a = me.attributes.new(name, data_type, domain)
        a.data.foreach_set(field, buf.ravel())
    if uv_active and uv_active in me.uv_layers:
        me.uv_layers.active = me.uv_layers[uv_active]
    if col_active and col_active in me.color_attributes:
        me.color_attributes.active_color_name = col_active
    me.update()
    return True
