"""Stage 2 (Assemble) and Stage 3 (Geometry repair) - the mesh work, no UI.

Runs inside the director's Blender. No bpy.ops here (works headless and from any
context); heavy counting is done with numpy on the mesh arrays so 1M-triangle
AI models stay fast.
"""

from __future__ import annotations

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector

PARTS_COLLECTION = "Forge Parts"
ROLE = "forge_kind"            # "body" | "prop"   (forge_role is the pipeline's high/low)
BACKUP = "forge_backup_mesh"   # mesh datablock name kept for "Undo repair"

# starting size of a newly generated prop, as a fraction of the body height (guessed by name)
SIZE_GUESS = [(("hair", "tuft", "fur", "mane"), 0.30), (("collar", "rope", "neck", "scarf"), 0.40),
              (("bell",), 0.12), (("band", "bracelet", "wrist", "cuff", "ring"), 0.15),
              (("horn",), 0.20), (("hat", "helmet", "crown"), 0.35),
              (("sword", "axe", "staff", "spear", "weapon"), 0.60)]


# ----------------------------------------------------------------------------- helpers

def mesh_parts(scene) -> list:
    col = bpy.data.collections.get(PARTS_COLLECTION)
    if not col:
        return []
    # never the remesher's temporary results or Forge's own helper pieces
    return [o for o in col.objects if o.type == "MESH" and not o.name.startswith("Retopo_")
            and not o.get("forge_rescue") and not o.get("forge_cage")]


def kind(o):
    """'body' / 'prop'. Read-only (the panel calls it while drawing, where writes are not
    allowed); files from add-on 1.1 stored the kind in forge_role."""
    k = o.get(ROLE)
    if k:
        return k
    legacy = o.get("forge_role")
    return legacy if legacy in ("body", "prop") else None


def body_of(parts: list):
    return next((o for o in parts if kind(o) == "body"), None)


def apply_transform(obj) -> None:
    """Bake location/rotation/scale into the mesh (the mesh is made single-user first)."""
    if obj.data.users > 1:
        obj.data = obj.data.copy()
    mw = obj.matrix_world.copy()
    obj.parent = None
    obj.data.transform(mw)
    if mw.determinant() < 0:            # a negative scale turns the mesh inside out
        obj.data.flip_normals()
    b = bpy.data.meshes.get(obj.get(BACKUP, ""))
    if b is not None and b != obj.data:  # the pre-repair copy moves with the part
        b.transform(mw)
        if mw.determinant() < 0:
            b.flip_normals()
        b.update()
    obj.matrix_world = Matrix.Identity(4)
    obj.data.update()


def world_bounds(obj):
    pts = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return lo, hi


def _size_guess(name: str) -> float:
    n = name.lower()
    for keys, frac in SIZE_GUESS:
        if any(k in n for k in keys):
            return frac
    return 0.20


# ----------------------------------------------------------------------------- stage 2: assemble

def collect(objs: list, target_height: float = 0.0) -> dict:
    """Gather the generated parts into one collection, pick the body, size and lay them out.

    Parts placed earlier (forge_placed) keep their position; new ones are scaled to a
    plausible size and lined up beside the body so the director can drag them on.
    """
    meshes = [o for o in objs if o.type == "MESH"]
    if not meshes:
        raise RuntimeError("Select the generated parts (meshes) first")
    col = bpy.data.collections.get(PARTS_COLLECTION)
    if col is None:
        col = bpy.data.collections.new(PARTS_COLLECTION)
        bpy.context.scene.collection.children.link(col)
    for o in meshes:
        for m in [m for m in o.modifiers if m.type == "ARMATURE"]:
            o.modifiers.remove(m)                 # the rig is made later (stage 8)
        apply_transform(o)
        for c in list(o.users_collection):
            if c != col:
                c.objects.unlink(o)
        if o.name not in col.objects:
            col.objects.link(o)

    parts = mesh_parts(bpy.context.scene)
    body = body_of(parts)
    if body is None:
        def vol(o):
            lo, hi = world_bounds(o)
            d = hi - lo
            return d.x * d.y * d.z
        body = max(parts, key=vol)
        body[ROLE] = "body"
    for o in parts:
        if o.name != body.name:
            o[ROLE] = "prop"
        else:
            o[ROLE] = "body"

    # body: feet on the floor, centred, requested height
    lo, hi = world_bounds(body)
    h = max(hi.z - lo.z, 1e-6)
    s = target_height / h if target_height > 0 else 1.0
    if not body.get("forge_placed") or target_height > 0:
        centre = Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z))
        m = Matrix.Scale(s, 4) @ Matrix.Translation(-centre)
        body.data.transform(m)
        body.data.update()
        body["forge_placed"] = True
        # parts already placed move and scale with the body
        if abs(s - 1.0) > 1e-6:
            for o in parts:
                if o.name != body.name and o.get("forge_placed"):
                    o.data.transform(m)
                    o.data.update()

    blo, bhi = world_bounds(body)
    bh = bhi.z - blo.z
    x = bhi.x + bh * 0.15
    new = []
    for o in sorted(parts, key=lambda p: p.name):
        if o.name == body.name or o.get("forge_placed"):
            continue
        lo, hi = world_bounds(o)
        size = max(hi - lo)
        want = _size_guess(o.name) * bh
        if size > 0:
            o.data.transform(Matrix.Scale(want / size, 4))
            o.data.update()
        lo, hi = world_bounds(o)
        c = (lo + hi) / 2
        o.data.transform(Matrix.Translation(Vector((x - lo.x, -c.y, bh * 0.5 - c.z))))
        o.data.update()
        x += (hi.x - lo.x) + bh * 0.1
        o["forge_placed"] = True
        new.append(o.name)
    return {"body": body.name, "parts": [o.name for o in parts], "new": new, "scale": s}


def move_to(obj, point: Vector) -> None:
    lo, hi = world_bounds(obj)
    obj.location += point - (lo + hi) / 2


def mirror(obj) -> object:
    """A copy of the part on the other side of the body (mirror across X = 0)."""
    apply_transform(obj)
    dup = obj.copy()
    dup.data = obj.data.copy()
    flip = Matrix.Scale(-1, 4, (1, 0, 0))
    dup.data.transform(flip)
    dup.data.flip_normals()
    dup.data.update()
    src_backup = bpy.data.meshes.get(obj.get(BACKUP, ""))
    if src_backup is not None:          # its own mirrored "before repair" copy
        b = src_backup.copy()
        b.transform(flip)
        b.flip_normals()
        b.use_fake_user = True
        dup[BACKUP] = b.name
    elif BACKUP in dup:
        del dup[BACKUP]
    swap = {"_L": "_R", "_R": "_L", ".L": ".R", ".R": ".L"}
    base, tail = obj.name[:-2], obj.name[-2:]
    if tail not in swap:
        # Blender convention: the character's left side is +X (it faces -Y)
        lo, hi = world_bounds(obj)
        tail = "_L" if (lo.x + hi.x) >= 0 else "_R"
        base = obj.name
        obj.name = base + tail
    dup.name = base + swap[tail]
    for c in obj.users_collection:
        c.objects.link(dup)
    dup[ROLE] = kind(obj) or "prop"
    dup["forge_placed"] = True
    return dup


def finalize_layout(parts: list) -> None:
    for o in parts:
        apply_transform(o)


# ----------------------------------------------------------------------------- stage 3: analysis

def _components(n: int, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Connected-component label per vertex (min-label propagation + pointer jumping)."""
    lab = np.arange(n)
    if len(a) == 0:
        return lab
    while True:
        la, lb = lab[a], lab[b]
        m = np.minimum(la, lb)
        new = lab.copy()
        np.minimum.at(new, la, m)
        np.minimum.at(new, lb, m)
        np.minimum.at(new, a, m)
        np.minimum.at(new, b, m)
        while True:
            jumped = new[new]
            if np.array_equal(jumped, new):
                break
            new = jumped
        if np.array_equal(new, lab):
            return lab
        lab = new


def _get(coll, attr, n, dtype):
    out = np.zeros(n, dtype)            # dtype must match Blender's storage (int32 / float32)
    coll.foreach_get(attr, out)
    return out.astype(np.int64 if dtype == np.int32 else np.float64)


def _arrays(me):
    nv, ne, nf, nl = len(me.vertices), len(me.edges), len(me.polygons), len(me.loops)
    ev = _get(me.edges, "vertices", ne * 2, np.int32).reshape(-1, 2)
    loop_edge = _get(me.loops, "edge_index", nl, np.int32)
    loop_vert = _get(me.loops, "vertex_index", nl, np.int32)
    fstart = _get(me.polygons, "loop_start", nf, np.int32)
    ftotal = _get(me.polygons, "loop_total", nf, np.int32)
    farea = _get(me.polygons, "area", nf, np.float32)
    return nv, ev, loop_edge, loop_vert, fstart, ftotal, farea


def analyse(obj) -> dict:
    """Counts the director can read: pieces, holes, broken edges, loose bits."""
    me = obj.data
    nv, ev, loop_edge, loop_vert, fstart, ftotal, farea = _arrays(me)
    faces_per_edge = np.bincount(loop_edge, minlength=len(ev))
    boundary = ev[faces_per_edge == 1]
    nonman = int((faces_per_edge > 2).sum())
    wire = int((faces_per_edge == 0).sum())
    face_vert = loop_vert[fstart] if len(fstart) else np.empty(0, np.int64)
    used = np.zeros(nv, bool)
    used[loop_vert] = True
    lab = _components(nv, ev[:, 0], ev[:, 1])
    island_area = np.bincount(lab[face_vert], weights=farea, minlength=nv) if len(face_vert) else np.zeros(nv)
    total_area = float(farea.sum()) or 1.0
    shells = int(len(np.unique(lab[face_vert]))) if len(face_vert) else 0
    big = int((island_area > 0.02 * total_area).sum())
    tiny = int(((island_area > 0) & (island_area < 5e-4 * total_area)).sum())
    holes = 0
    if len(boundary):
        bl = _components(nv, boundary[:, 0], boundary[:, 1])
        holes = int(len(np.unique(bl[np.unique(boundary)])))
    rep = {
        "tris": int((ftotal - 2).sum()),
        "verts": nv,
        "pieces": shells,
        "big_pieces": big,
        "tiny_bits": tiny,
        "holes": holes,
        "open_edges": int(len(boundary)),
        "bad_edges": nonman,
        "loose": int((~used).sum()) + wire,
    }
    rep["ok"] = rep["holes"] == 0 and rep["bad_edges"] == 0 and rep["loose"] == 0 and rep["tiny_bits"] == 0
    # several big overlapping pieces (e.g. horns pushed into the head) = not one welded solid
    rep["needs_weld"] = big > 1 and kind(obj) == "body"
    return rep


def problems_text(rep: dict) -> str:
    bits = []
    if rep.get("holes"):
        bits.append(f"{rep['holes']} holes")
    if rep.get("bad_edges"):
        bits.append(f"{rep['bad_edges']} broken edges")
    if rep.get("tiny_bits"):
        bits.append(f"{rep['tiny_bits']} floating bits")
    if rep.get("loose"):
        bits.append(f"{rep['loose']} loose points")
    if rep.get("needs_weld"):
        bits.append(f"{rep['big_pieces']} pieces not welded")
    return ", ".join(bits) or "clean"


# ----------------------------------------------------------------------------- stage 3: repair

def backup(obj) -> None:
    name = obj.get(BACKUP)
    if name and name in bpy.data.meshes:
        return                                    # keep the very first original
    copy = obj.data.copy()
    copy.name = f"FORGE_BACKUP_{obj.name}"
    copy.use_fake_user = True
    obj[BACKUP] = copy.name


def restore(obj) -> bool:
    name = obj.get(BACKUP)
    src = bpy.data.meshes.get(name) if name else None
    if src is None:
        return False
    old = obj.data
    obj.data = src.copy()
    obj.data.name = old.name
    if old.users == 0:
        bpy.data.meshes.remove(old)
    return True


def drop_backup(obj) -> None:
    name = obj.get(BACKUP)
    if name and name in bpy.data.meshes:
        bpy.data.meshes.remove(bpy.data.meshes[name])
    if BACKUP in obj:
        del obj[BACKUP]


def _remove_tiny_islands(obj, area_ratio: float) -> int:
    me = obj.data
    nv, ev, loop_edge, loop_vert, fstart, ftotal, farea = _arrays(me)
    if not len(fstart):
        return 0
    lab = _components(nv, ev[:, 0], ev[:, 1])
    face_vert = loop_vert[fstart]
    island_area = np.bincount(lab[face_vert], weights=farea, minlength=nv)
    total = float(farea.sum()) or 1.0
    tiny = (island_area > 0) & (island_area < area_ratio * total)
    n = int(tiny.sum())
    if not n:
        return 0
    kill = np.nonzero(tiny[lab])[0]
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.verts.ensure_lookup_table()
    bmesh.ops.delete(bm, geom=[bm.verts[i] for i in kill], context="VERTS")
    bm.to_mesh(me)
    bm.free()
    me.update()
    return n


def repair(obj, merge_rel: float = 1e-4, speck_rel: float = 5e-4, max_hole_sides: int = 1024) -> dict:
    """Automatic geometry repair. Keeps the shape and textures of every existing face.

    1. weld cracks (vertices closer than merge_rel x size)
    2. remove collapsed faces, loose points and stray edges
    3. remove tiny floating bits (smaller than speck_rel of the surface)
    4. close every hole (new faces are triangulated)
    5. point every face outward
    """
    backup(obj)
    me = obj.data
    size = max(obj.dimensions.length, 1e-6)
    before = len(me.vertices)

    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=size * merge_rel)
    welded = before - len(bm.verts)
    bmesh.ops.dissolve_degenerate(bm, dist=size * merge_rel * 0.1, edges=bm.edges)
    loose_e = [e for e in bm.edges if not e.link_faces]
    if loose_e:
        bmesh.ops.delete(bm, geom=loose_e, context="EDGES_FACES")
    loose_v = [v for v in bm.verts if not v.link_faces]
    if loose_v:
        bmesh.ops.delete(bm, geom=loose_v, context="VERTS")
    bm.to_mesh(me)
    bm.free()
    me.update()

    specks = _remove_tiny_islands(obj, speck_rel)

    bm = bmesh.new()
    bm.from_mesh(me)
    open_edges = [e for e in bm.edges if e.is_boundary]
    filled = 0
    if open_edges:
        res = bmesh.ops.holes_fill(bm, edges=open_edges, sides=max_hole_sides)
        new_faces = res.get("faces", [])
        filled = len(new_faces)
        tri = [f for f in new_faces if len(f.verts) > 3]
        if tri:
            bmesh.ops.triangulate(bm, faces=tri, quad_method="BEAUTY", ngon_method="BEAUTY")
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()
    me.update()
    return {"welded_points": welded, "removed_bits": specks, "holes_closed": filled}


def make_solid(obj, resolution: int = 400) -> dict:
    """Weld overlapping pieces into one watertight shell (voxel remesh).

    Removes every hole, inner face and crack in one go, at the cost of the colour
    texture - that is re-made on the clean model in stage 7 anyway.
    """
    backup(obj)
    size = max(obj.dimensions)
    mod = obj.modifiers.new("forge_solid", "REMESH")
    mod.mode = "VOXEL"
    mod.voxel_size = max(size / max(resolution, 16), 1e-5)
    mod.adaptivity = 0.0
    mod.use_smooth_shade = True
    others = [m for m in obj.modifiers if m.name != mod.name and m.show_viewport]
    for m in others:
        m.show_viewport = False
    dg = bpy.context.evaluated_depsgraph_get()
    dg.update()
    new = bpy.data.meshes.new_from_object(obj.evaluated_get(dg))
    obj.modifiers.remove(mod)
    for m in others:
        m.show_viewport = True
    old = obj.data
    new.name = old.name
    for mat in old.materials:
        new.materials.append(mat)
    obj.data = new
    if old.users == 0:
        bpy.data.meshes.remove(old)
    return {"tris": int(sum(len(p.vertices) - 2 for p in new.polygons))}
