"""The clean-mesh gate at the end of retopology: every face in its own place, nothing open.

UVgami puts its UVs back by matching positions and gives up on faces lying on each other;
the bake and the skinning go wrong there too. The gate finds and repairs them."""

import sys
from pathlib import Path

import pytest

bpy = pytest.importorskip("bpy")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "blender_scripts"))


def _ball(sub=3):
    import bmesh
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=sub, radius=1.0)
    return bm


def _cube(cuts=3):
    import bmesh
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=2.0)
    bmesh.ops.subdivide_edges(bm, edges=list(bm.edges), cuts=cuts, use_grid_fill=True)
    return bm


def _mesh(bm):
    me = bpy.data.meshes.new("t")
    bm.to_mesh(me)
    bm.free()
    return me


def _clean(me):
    from forge_bpy import rescue
    return (rescue.mesh_defects(me) == (0, 0, 0) and not rescue.stacked_faces(me).any()
            and not rescue.doubled_points(me).any())


def test_a_clean_mesh_is_left_alone():
    from forge_bpy import rescue
    me = _mesh(_cube())
    n = len(me.polygons)
    assert _clean(me)
    out = rescue.tidy(me)
    assert not any(out.values()) and len(me.polygons) == n


def test_duplicate_face_is_found_and_removed():
    from forge_bpy import rescue
    bm = _ball()
    bm.faces.ensure_lookup_table()
    f = bm.faces[10]
    vs = [bm.verts.new(v.co) for v in f.verts]          # a second face on the same spot
    bm.faces.new(vs)
    me = _mesh(bm)
    assert rescue.stacked_faces(me).sum() == 0 and rescue.doubled_points(me).sum() == 6   # both of each pair
    out = rescue.tidy(me)
    assert out["welded"] == 3 and _clean(me), (out, rescue.mesh_defects(me))


def test_triangle_over_half_a_quad_is_removed():
    from forge_bpy import rescue
    bm = _cube()
    bm.faces.ensure_lookup_table()
    q = next(f for f in bm.faces if len(f.verts) == 4)
    a, b, c, _d = q.verts
    bm.faces.new((a, b, c))
    me = _mesh(bm)
    assert rescue.stacked_faces(me).sum() == 2
    out = rescue.tidy(me)
    assert out["stacked"] == 1 and _clean(me), out
    assert all(len(p.vertices) == 4 for p in me.polygons)       # the quad stayed


def test_unwelded_seam_is_welded():
    import bmesh

    from forge_bpy import rescue
    bm = _cube()
    seam = [e for e in bm.edges if all(abs(v.co.x) < 1e-6 for v in e.verts)]
    bmesh.ops.split_edges(bm, edges=seam)
    me = _mesh(bm)
    assert rescue.mesh_defects(me)[0] > 0 and rescue.doubled_points(me).any()
    rescue.tidy(me)
    assert _clean(me)


def test_fin_and_pinched_hole_are_rebuilt_closed():
    import bmesh

    from forge_bpy import rescue
    bm = _ball(4)
    bm.edges.ensure_lookup_table()
    e = bm.edges[40]                                   # a fin on an edge: 3 faces there
    tip = bm.verts.new(e.verts[0].co * 1.3)
    bm.faces.new((e.verts[0], e.verts[1], tip))
    bm.verts.ensure_lookup_table()
    v = bm.verts[200]                                  # two holes touching at one point
    fs = list(v.link_faces)
    bmesh.ops.delete(bm, geom=[fs[0], fs[2]], context="FACES_ONLY")
    me = _mesh(bm)
    d = rescue.mesh_defects(me)
    assert d[0] > 0 and d[1] > 0, d
    rescue.tidy(me)
    assert _clean(me), rescue.mesh_defects(me)


def test_show_problem_edges_selects_exactly_the_faults():
    import importlib

    import bmesh
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "blender_addon"))
    importlib.import_module("forge_send")
    from forge_send import steps as S
    bm = _cube()
    bm.faces.ensure_lookup_table()
    q = next(f for f in bm.faces if len(f.verts) == 4)
    bmesh.ops.delete(bm, geom=[q], context="FACES_ONLY")          # one hole of 4 edges
    me = _mesh(bm)
    n = S.mark_defects(me)
    assert n == 4 and sum(e.select for e in me.edges) == 4
    assert sum(v.select for v in me.vertices) == 4
