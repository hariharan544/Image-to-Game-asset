"""The test zoo (tests/bodies_zoo.py) builds what it claims: one closed fused surface like an
AI mesh, on the ground, facing -Y, with every named extra part where its info says it is.
Generator checks only (coarse voxels, fast): what the product code does with these bodies is
for the tests that use them."""

import sys
from pathlib import Path

import pytest

bpy = pytest.importorskip("bpy")
sys.path.insert(0, str(Path(__file__).resolve().parent))

VOXEL = 0.016          # coarse: thin sheets are thickened to 2.2 voxels, everything stays fused


def _near(co, p, r):
    import numpy as np
    return np.linalg.norm(co - np.asarray(p), axis=1) < r


@pytest.mark.parametrize("name", ["bat_wings", "bird_wings", "one_wing", "dorsal_fin", "shoulder_cannon",
                                  "two_tails", "trunk", "cape", "tentacles", "horns_asym", "quadruped"])
def test_zoo_body_is_one_closed_surface_with_its_parts_where_info_says(name):
    import numpy as np

    import bodies_zoo as Z
    ob, info = Z.ZOO[name](voxel=VOXEL)
    me = ob.data
    co = Z.coords(me)
    # one closed fused surface, on the ground, a plausible size
    assert Z.open_edges(me) == (0, 0), name
    assert Z.shells(me) == 1, name
    assert abs(co[:, 2].min()) < 1e-5
    assert 1.0 < info["height"] < 2.2, info["height"]
    assert len(me.vertices) > 2000
    # ground truth on every vertex, every owner present
    lab = Z.truth(me)
    assert lab is not None and len(lab) == len(me.vertices) and (lab == info["truth"]).all()
    assert set(np.unique(lab)) == set(range(len(info["labels"])))
    # facing -Y: toes (biped) or the head (quadruped) stick out to -Y
    if info["kind"] == "quadruped":
        top = co[co[:, 2] > co[:, 2].max() - 0.1]
        assert top[:, 1].mean() < -0.3
    elif "leg_l" in info["limbs"]:
        feet = co[co[:, 2] < 0.05]
        assert -feet[:, 1].min() > 1.5 * feet[:, 1].max()
    # T-pose: the hands are the far ends along X, at shoulder height
    if "arm_l" in info["limbs"]:
        for s in "lr":
            hand = np.asarray(info["limbs"][f"arm_{s}"]["tip"])
            assert abs(abs(hand[0]) - np.abs(co[:, 0]).max()) < 0.02
            assert abs(hand[2] - co[np.argmax(co[:, 0] * (1 if s == "l" else -1)), 2]) < 0.06
    assert info["appendages"], name
    for a, e in info["appendages"].items():
        m = Z.part_mask(me, info, a)
        assert m.sum() >= 50, (a, int(m.sum()))
        assert e["symmetry"] in Z.SYMMETRY and e["side"] in ("l", "r", "c")
        assert e["side"] == "c" or (np.sign(co[m, 0].mean()) == (1 if e["side"] == "l" else -1)), a
        # fused to the body at its root (not a loose piece), the root ring near the designed root
        assert e["ring"] is not None and e["ring"]["verts"] >= 4, a
        assert np.linalg.norm(np.asarray(e["ring"]["centre"]) - e["root"]) < 0.12, (a, e["ring"]["centre"], e["root"])
        assert e["root_on"] and any(o not in info["appendages"] for o in e["root_on"]), (a, e["root_on"])
        # the tip is on the part, and the part reaches out from its root
        assert _near(co[m], e["tip"], 0.06 + VOXEL).any(), a
        assert np.linalg.norm(np.asarray(e["tip"]) - e["root"]) > 0.03, a
        # what "symmetry" claims is what the surface does
        if e["symmetry"] == "pair":
            assert e["twin"] in info["appendages"] and e["mirror_on_twin"] > 0.8, (a, e["mirror_on_twin"])
        elif e["symmetry"] == "centre":
            assert e["mirror_on_surface"] > 0.8, (a, e["mirror_on_surface"])
        elif e["symmetry"] == "one-sided":
            assert e["twin"] is None and e["mirror_on_surface"] < 0.5, (a, e["mirror_on_surface"])
        elif e["symmetry"] in ("pair_asym", "pair_posed"):            # a twin, but not a mirror image
            t = info["appendages"].get(e["twin"])
            assert t is not None and t["twin"] == a and t["symmetry"] == e["symmetry"], a
            assert min(e["mirror_on_twin"], t["mirror_on_twin"]) < 0.9, (a, e["mirror_on_twin"], t["mirror_on_twin"])
    Z.info_json(info)                                    # serialisable for reports


@pytest.mark.parametrize("voxel", [0.008, 0.014])
def test_designed_contacts_away_from_the_root_survive_the_remesh(voxel):
    """The folded wing rests on the thigh, the cape touches the rump and one calf, two
    tentacles touch each other: contacts that are not roots, at fine and coarse voxels."""
    import bodies_zoo as Z
    _ob, info = Z.bird_wings(voxel=voxel)
    for s in "lr":
        c = info["appendages"][f"wing_{s}"]["contacts"]
        assert any(f"leg_{s}" in x["with"] for x in c), (s, c)
    _ob, info = Z.cape(voxel=voxel)
    c = info["appendages"]["cape"]["contacts"]
    assert any("body" in x["with"] and abs(x["centre"][2] - 0.95) < 0.08 for x in c), c          # the rump
    calf = [x for x in c if x["centre"][2] < 0.6]
    assert len(calf) == 1 and calf[0]["with"] == ["leg_l"] and calf[0]["centre"][0] > 0.05, c    # one calf
    _ob, info = Z.tentacles(voxel=voxel)
    touching = [a for a, e in info["appendages"].items() if e["touching"]]
    assert len(touching) == 2
    a, b = touching
    assert any(b in x["with"] for x in info["appendages"][a]["contacts"] + [{"with": info["appendages"][a]["root_on"]}])
    _ob, info = Z.bird_wings(voxel=voxel, rest=False)                    # folded clear of the body
    assert not info["appendages"]["wing_l"]["contacts"]


def test_shells_scale_and_variants():
    import numpy as np

    import bodies_zoo as Z
    ob, info = Z.bat_wings(voxel=VOXEL, shells=2)
    me = ob.data
    assert Z.shells(me) == 3 and Z.open_edges(me) == (0, 0)
    co = Z.coords(me)
    buried = Z.part_mask(me, info, "shell_buried_1")
    loose = Z.part_mask(me, info, "shell_loose_1")
    assert buried.sum() > 20 and loose.sum() > 20
    body = ~(buried | loose)
    lo, hi = co[body].min(axis=0), co[body].max(axis=0)
    assert (co[buried] > lo).all() and (co[buried] < hi).all()            # inside the trunk
    # half size: everything scales, the voxel stays absolute
    _ob, half = Z.bat_wings(voxel=VOXEL, scale=0.6)
    assert abs(half["height"] / info["height"] - 0.6) < 0.03
    assert abs(half["appendages"]["wing_l"]["root"][2] / info["appendages"]["wing_l"]["root"][2] - 0.6) < 0.03
    # the asymmetric variants
    _ob, one = Z.one_wing(voxel=VOXEL, style="bat", side="r")
    assert list(one["appendages"]) == ["wing_r"] and one["appendages"]["wing_r"]["symmetry"] == "one-sided"
    _ob, pd = Z.shoulder_cannon(voxel=VOXEL, kind="pauldron", side="r")
    assert pd["appendages"]["pauldron_r"]["thin"] is False and pd["appendages"]["pauldron_r"]["side"] == "r"
    _ob, q = Z.dorsal_fin(voxel=VOXEL, base="quadruped")
    assert q["kind"] == "quadruped" and q["appendages"]["fin"]["symmetry"] == "centre"
    assert len(q["limbs"]) == 4 and not q["joints_hint"]
    # deterministic: the same parameters give the same mesh
    ob1, _i = Z.horns_asym(voxel=VOXEL)
    co1 = Z.coords(ob1.data)
    ob2, _i = Z.horns_asym(voxel=VOXEL)
    co2 = Z.coords(ob2.data)
    assert co1.shape == co2.shape and np.allclose(co1, co2)
