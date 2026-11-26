"""Retopology shape check: a thin part lost by the remesher is painted denser and re-run."""

import sys
from pathlib import Path

import pytest

bpy = pytest.importorskip("bpy")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "blender_scripts"))


def _body_with_tail():
    import bmesh
    from mathutils import Matrix
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=4, radius=1.0)
    res = bmesh.ops.create_cone(bm, cap_ends=True, segments=10, radius1=0.04, radius2=0.02, depth=1.0,
                                matrix=Matrix.Translation((1.45, 0, 0)) @ Matrix.Rotation(1.5708, 4, "Y"))
    vs = set(res["verts"])
    bmesh.ops.subdivide_edges(bm, edges=[e for e in bm.edges if e.verts[0] in vs and e.verts[1] in vs],
                              cuts=10, use_grid_fill=True)
    me = bpy.data.meshes.new("Body")
    bm.to_mesh(me)
    o = bpy.data.objects.new("Body_low", me)
    bpy.context.scene.collection.objects.link(o)
    o["forge_role"], o["forge_part"] = "low", "Body"
    return o


def test_lost_tail_is_detected_painted_and_remeshed(monkeypatch):
    import numpy as np

    from forge_bpy import density, retopo
    o = _body_with_tail()
    calls = []

    def fake_qr(obj, quads, args, timeout):
        """Stand-in for Quad Remesher: keeps the tail only where the density map is red."""
        yield 0.0
        me = obj.data
        attr = me.color_attributes.get(density.QR_ATTR)
        red = np.zeros(len(me.vertices), bool)
        if attr is not None:
            col = np.empty(len(me.loops) * 4, np.float32)
            attr.data.foreach_get("color_srgb", col)
            lv = np.array([l.vertex_index for l in me.loops])
            red[lv[(col.reshape(-1, 4)[:, 1] < 0.1)]] = True
        import bmesh
        bm = bmesh.new()
        bm.from_mesh(me)
        bm.verts.ensure_lookup_table()
        tail = [v for v in bm.verts if v.co.x > 1.05]
        kept_tail = all(red[v.index] for v in tail[:20])
        if not kept_tail:
            bmesh.ops.delete(bm, geom=tail, context="VERTS")
        bm.to_mesh(me)
        bm.free()
        calls.append(kept_tail)
        return True

    monkeypatch.setattr(retopo, "_qr_part", fake_qr)
    gen = retopo._run_qr({"target_tris": 100000, "qr_timeout": 5})
    try:
        while True:
            next(gen)
    except StopIteration as stop:
        rep = stop.value
    shape = rep["parts"]["Body"]["shape"]
    assert calls == [False, True], calls                      # lost once, kept after painting
    assert shape["refined"] == 1 and shape["lost_pct"] < 0.2, shape
    assert max(v.co.x for v in o.data.vertices) > 1.9            # the tail is back
    assert rep["parts"]["Body"]["method"] == "quadremesher(shape-fixed)"
