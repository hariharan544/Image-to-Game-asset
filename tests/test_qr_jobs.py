"""Quad Remesher jobs: the result is always found, a late or stopped job never pollutes the
next one, the wait is sized to the work and says what it waits for."""

import sys
from pathlib import Path

import pytest

bpy = pytest.importorskip("bpy")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "blender_scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

LONG = "tripo_node_71f6acba-89be-4f91-a4de-9d5a0bbcfd98_low"


@pytest.fixture()
def engine(monkeypatch):
    import fake_qr

    from forge_bpy import addon_trial, retopo
    bpy.ops.wm.read_homefile(use_empty=True)
    eng = fake_qr.install()
    eng.name_limit = None
    monkeypatch.setattr(addon_trial, "view3d_override", lambda: {"scene": bpy.context.scene})
    monkeypatch.setattr(retopo, "_wait_limit", lambda obj, timeout: timeout)
    retopo._QR_JOBS.clear()
    retopo.STATUS["text"] = ""
    yield eng
    retopo._QR_JOBS.clear()
    fake_qr.uninstall()


def _low(name, size=1.0):
    import bmesh
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=3, radius=size)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    col = bpy.data.collections.get("FORGE_LOW") or bpy.data.collections.new("FORGE_LOW")
    if col.name not in bpy.context.scene.collection.children:
        bpy.context.scene.collection.children.link(col)
    o = bpy.data.objects.new(name, me)
    col.objects.link(o)
    return o


def _start(gen, jobs: int = 1):
    """Run the generator until the engine holds `jobs` jobs (it may first wait for an older one)."""
    import fake_qr
    import time
    t0 = time.time()
    next(gen)
    while len(fake_qr.Engine.jobs) < jobs and time.time() - t0 < 10:
        next(gen)
    return gen


def _finish(gen):
    try:
        while True:
            next(gen)
    except StopIteration as stop:
        return stop.value


def _quads(me):
    """What the remesher returns: a visibly different mesh (a coarser sphere)."""
    import bmesh
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=1, radius=1.0)
    bm.to_mesh(me)
    bm.free()


@pytest.mark.parametrize("limit", [None, 63, 15])
def test_result_is_taken_for_long_names_whatever_the_engine_calls_it(engine, limit):
    import fake_qr

    from forge_bpy import retopo
    engine.name_limit = limit                    # 15: the engine cuts even the short job name
    for name in (LONG, LONG + "_part1", LONG + "_rescue0"):
        o = _low(name)
        gen = _start(retopo._qr_part(o, 100, {}, 5.0))
        fake_qr.deliver(_quads)
        assert _finish(gen) is True, name
        assert len(o.data.polygons) == 20 and o.name == name and not o.hide_get()
    assert not [x for x in bpy.data.objects if x.name.startswith("Retopo_") or x.get("forge_qr_proxy")]
    assert not retopo._QR_JOBS


def test_a_timed_out_job_never_eats_the_next_result(engine):
    import fake_qr

    from forge_bpy import retopo
    o = _low("Body_low")
    assert _finish(_start(retopo._qr_part(o, 100, {}, 0.6))) is False     # the engine is slow
    assert [j["state"] for j in retopo._QR_JOBS.values()] == ["abandoned"]
    assert not [x for x in bpy.data.objects if x.get("forge_qr_proxy")]   # the copy is gone
    gen = retopo._qr_part(o, 100, {}, 5.0)
    next(gen)                                     # it waits for the old job first...
    late_name = fake_qr.deliver().name            # ...which arrives late: the original mesh
    _start(gen, 1)                                # then the new job is launched
    fake_qr.deliver(_quads)                       # then the new one
    assert _finish(gen) is True
    assert len(o.data.polygons) == 20             # the new result, not the late one
    assert late_name not in bpy.data.objects      # the late result was removed
    assert not retopo._QR_JOBS


def test_stop_then_run_again_takes_only_the_new_result(engine):
    import fake_qr

    from forge_bpy import retopo
    o = _low("Body_low")
    gen = _start(retopo._qr_part(o, 100, {}, 5.0))
    gen.close()                                   # the director pressed Stop
    assert [j["state"] for j in retopo._QR_JOBS.values()] == ["abandoned"]
    assert not [x for x in bpy.data.objects if x.get("forge_qr_proxy")]
    gen = retopo._qr_part(o, 100, {}, 5.0)
    next(gen)
    fake_qr.deliver()                             # the stopped job finishes in the engine
    _start(gen, 1)
    fake_qr.deliver(_quads)
    assert _finish(gen) is True and len(o.data.polygons) == 20
    assert not [x for x in bpy.data.objects if x.name.startswith("Retopo_")]


def test_the_wait_says_what_it_waits_for(engine):
    import fake_qr

    from forge_bpy import retopo
    o = _low(LONG + "_part1")
    retopo.STATUS["text"] = f"{retopo._short(o.name)}: thin part 1 on its own (tail...)"
    gen = _start(retopo._qr_part(o, 100, {}, 5.0))
    import time
    time.sleep(1.1)
    next(gen)
    txt = retopo.STATUS["text"]
    assert "thin part 1" in txt[:60] and txt.rstrip().endswith("s"), txt
    fake_qr.deliver(_quads)
    assert _finish(gen) is True


def test_wait_limit_is_sized_to_the_part():
    from forge_bpy import retopo

    class O:
        class data:
            polygons = range(20_000)
    assert retopo._wait_limit(O, 900) == 120               # a tail piece: two minutes
    O.data.polygons = range(4_900_000)
    assert retopo._wait_limit(O, 900) == 900               # the whole body: the full allowance
