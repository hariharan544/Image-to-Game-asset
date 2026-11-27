"""The test zoo (tests/bodies_zoo.py) builds what it claims: one closed fused surface like an
AI mesh, on the ground, facing -Y, with every named extra part where its info says it is, at
the coarse voxel (fast) and at the zoo's default voxel. Generator checks only: what the product
code does with these bodies is for the tests that use them (and tests/zoo_baseline.py, whose
scoring is held here to a stored record so its totals stay comparable)."""

import json
import sys
from pathlib import Path

import pytest

bpy = pytest.importorskip("bpy")
sys.path.insert(0, str(Path(__file__).resolve().parent))

VOXEL = 0.016          # coarse: thin sheets are thickened to 2.2 voxels, everything stays fused
NAMES = ["bat_wings", "bird_wings", "one_wing", "dorsal_fin", "shoulder_cannon", "two_tails", "trunk", "cape",
         "tentacles", "horns_asym", "quadruped", "weapon_in_hand", "forearm_shield", "sash_diagonal", "ponytail_side",
         "antlers", "hair_spikes", "back_spines", "skirt", "four_arms", "four_wings", "tail_spikes", "held_staff",
         "dragon", "loadout", "winged_tail", "naga", "chibi", "back_hair"]


def _near(co, p):
    import numpy as np
    return float(np.min(np.linalg.norm(co - np.asarray(p), axis=1)))


def _tol(e, voxel):
    """How far a measured point may be from its design: about 2 voxels, or half the root ring."""
    return max(2 * voxel, 0.5 * (e["ring"]["radius"] if e.get("ring") else 0.0))


def check_body(name, ob, info, voxel):
    """Everything info claims, checked against the mesh (used by the tests below)."""
    import numpy as np

    import bodies_zoo as Z
    me = ob.data
    co = Z.coords(me)
    # one closed fused surface (plus one per separate part), on the ground, a plausible size
    assert Z.open_edges(me) == (0, 0), name
    assert Z.shells(me) == 1 + len(info["separate"]) + len(info["shells"]), name
    assert abs(co[:, 2].min()) < 1e-5
    assert 1.0 * info["scale"] < info["height"] < 2.4 * info["scale"], info["height"]
    assert len(me.vertices) > 2000
    # ground truth on every vertex and face, every owner present
    lab = Z.truth(me)
    assert lab is not None and len(lab) == len(me.vertices) and (lab == info["truth"]).all()
    assert set(np.unique(lab)) == set(range(len(info["labels"])))
    assert len(info["face_truth"]) == len(me.polygons)
    bones, apps, limbs = info["bones"], info["appendages"], info["limbs"]
    # facing -Y: toes (biped) or the head (quadruped) stick out to -Y
    if info["kind"] == "quadruped":
        top = co[co[:, 2] > co[:, 2].max() - 0.1]
        assert top[:, 1].mean() < -0.3
    elif "leg_l" in limbs:
        feet = co[(co[:, 2] < 0.05) & np.isin(lab, [info["labels"].index(x) for x in ("leg_l", "leg_r")])]
        assert -feet[:, 1].min() > 1.5 * feet[:, 1].max()
    # T-pose: each hand is the far end of its arm along X, at shoulder height (an arm posed
    # otherwise: the far end along the arm, at its hand's height)
    for s in "lr":
        if f"arm_{s}" in limbs:
            e = limbs[f"arm_{s}"]
            arm = co[Z.part_mask(me, info, f"arm_{s}")]
            sgn = 1 if s == "l" else -1
            if e["symmetry"] == "pair":
                assert abs(e["tip"][0] * sgn - (arm[:, 0] * sgn).max()) <= voxel + 1e-6
                assert abs(e["tip"][2] - info["joints_hint"][f"shoulder_{s}"][2]) < 0.06
            else:
                j = info["joints_hint"]
                d = np.asarray(j[f"hand_{s}"]) - np.asarray(j[f"shoulder_{s}"])
                d /= np.linalg.norm(d)
                assert abs(np.asarray(e["tip"]) @ d - (arm @ d).max()) <= voxel + 1e-6
                assert abs(e["tip"][2] - j[f"hand_{s}"][2]) < 0.06
    assert apps or any(e["symmetry"] != "pair" for e in limbs.values()), name    # (or a body about its limbs)
    for a, e in list(apps.items()) + list(limbs.items()):
        m = Z.part_mask(me, info, a)
        P = co[m]
        assert m.sum() >= 30, (a, int(m.sum()))
        assert e["symmetry"] in Z.SYMMETRY and e["side"] in ("l", "r", "c"), a
        assert e["side"] == "c" or np.sign(P[:, 0].mean()) == (1 if e["side"] == "l" else -1), a
        assert e["parent"] in bones or e["parent"] in apps, (a, e["parent"])
        if a in apps:
            assert e["rig"] in Z.RIGS, (a, e["rig"])
        # the root: fused (a ring) or, for a part that is its own shell, none
        if e.get("separate"):
            assert e["ring"] is None and Z.shells(me) > 1, a
        else:
            assert e["ring"] is not None and e["ring"]["verts"] >= 4, a
            base = [o for o in e["root_on"] if o not in apps]
            on_part = [o for o in e["root_on"] if o in apps]
            assert base or on_part, (a, e["root_on"])          # (a dense cluster: rooted among its neighbours)
            shared = bool(on_part) and e["parent"] not in on_part       # its ring runs into a neighbour's
            if not shared:
                d = float(np.linalg.norm(np.asarray(e["root"]) - e["root_design"]))
                assert d <= _tol(e, voxel), (a, round(d, 4), round(_tol(e, voxel), 4))
            assert e["root_shape"] == e["ring"]["shape"]
        # the tip: a vertex of the part, where it was designed
        assert _near(P, e["tip"]) < 1e-6, a
        d = float(np.linalg.norm(np.asarray(e["tip"]) - e["tip_design"]))
        assert d <= _tol(e, voxel), (a, round(d, 4), round(_tol(e, voxel), 4))
        # (a part lying on the body stands out only its own height from its root)
        reach = 0.03 if not e.get("proud") else min(0.03, 0.8 * e["proud_design"])
        assert np.linalg.norm(np.asarray(e["tip"]) - e["root"]) > reach, a
        for p in e.get("root_line", []):
            assert _near(P, p) < 1e-6
        for b in e.get("branches", []):
            assert _near(P, b["tip"]) < 1e-6 and np.linalg.norm(np.asarray(b["tip"]) - b["tip_design"]) < 2.5 * voxel
        # what "symmetry" claims is what the surface does
        sym = e["symmetry"]
        if sym == "pair":
            t = (apps.get(e["twin"]) or limbs.get(e["twin"]))
            assert t is not None and t["twin"] == a and e["mirror_on_twin"] > 0.8, (a, e["mirror_on_twin"])
        elif sym == "centre":
            assert e["side"] == "c" and e["mirror_on_self"] > 0.85, (a, e["mirror_on_self"])
        elif sym == "centre_asym":
            assert e["side"] == "c" and e["mirror_on_self"] < 0.95, (a, e["mirror_on_self"])
            if e["ring"] is not None:                                # rooted on the mirror plane
                assert abs(e["root"][0]) < max(2 * voxel, 0.5 * e["ring"]["radius"]), (a, e["root"])
        elif sym == "one-sided":                                     # (a relief lower than the tolerance
            assert e["twin"] is None and (e.get("relief") or e["mirror_on_surface"] < 0.5), (    # mirrors onto skin)
                a, e["mirror_on_surface"])
        else:                                                        # pair_asym / pair_posed
            t = apps.get(e["twin"]) or limbs.get(e["twin"])
            assert t is not None and t["twin"] == a and t["symmetry"] == sym, a
            assert min(e["mirror_on_twin"], t["mirror_on_twin"]) < 0.9, (a, e["mirror_on_twin"], t["mirror_on_twin"])
    Z.info_json(info)                                    # serialisable for reports


@pytest.mark.parametrize("voxel", [VOXEL, 0.008])
@pytest.mark.parametrize("name", NAMES)
def test_zoo_body_is_one_closed_surface_with_its_parts_where_info_says(name, voxel):
    import bodies_zoo as Z
    assert set(NAMES) == set(Z.ZOO)
    ob, info = Z.ZOO[name](voxel=voxel)
    check_body(name, ob, info, voxel)


def test_what_each_new_case_is_about():
    """The point of each newer body, checked: a weapon moves the hand extent, a shield and a
    blade hang on a forearm, a skirt touches both legs, a sash and a ponytail are not their own
    mirror image, antlers branch, spikes cluster, parts sit on a part, big parts can be their own
    shell, the naga has no legs, the chibi's head is big."""
    import numpy as np

    import bodies_zoo as Z
    v = VOXEL
    ob, info = Z.weapon_in_hand(voxel=v)
    co = Z.coords(ob.data)
    sw = info["appendages"]["sword_r"]
    assert sw["parent"] == "hand_r" and sw["root_on"] == ["arm_r"] and sw["symmetry"] == "one-sided"
    assert -co[:, 0].min() > -info["limbs"]["arm_r"]["tip"][0] + 0.5          # the blade, not the hand, is the far end
    ob, info = Z.forearm_shield(voxel=v)
    sh = info["appendages"]["shield_l"]
    assert sh["parent"] == "forearm_l" and sh["root_on"] == ["arm_l"]
    ob, info = Z.loadout(voxel=v)
    a = info["appendages"]
    assert a["cannon_l"]["symmetry"] == a["blade_r"]["symmetry"] == "one-sided"
    assert a["blade_r"]["parent"] == "forearm_r"
    ob, info = Z.ZOO["skirt"](voxel=v)
    touched = {w for c in info["appendages"]["skirt"]["contacts"] for w in c["with"]}
    assert {"leg_l", "leg_r"} <= touched, info["appendages"]["skirt"]["contacts"]
    ob, info = Z.sash_diagonal(voxel=v)
    sa = info["appendages"]["sash"]
    assert sa["symmetry"] == "centre_asym" and sa["mirror_on_self"] < 0.5
    ob, info = Z.ponytail_side(voxel=v)
    pt = info["appendages"]["ponytail"]
    assert pt["symmetry"] == "centre_asym" and pt["contacts"] and pt["tip"][0] > 0.1
    ob, info = Z.antlers_body(voxel=v)
    assert all(len(info["appendages"][f"antler_{s}"]["branches"]) == 3 for s in "lr")
    ob, info = Z.hair_spikes(voxel=v, n=14)
    sp = [e for e in info["appendages"].values() if e["kind"] == "spike"]
    assert len(sp) == 14 and sum(e["symmetry"] == "pair" for e in sp) >= 10
    ob, info = Z.four_arms(voxel=v)
    assert [e["rig"] for e in info["appendages"].values()] == ["limb", "limb"]
    ob, info = Z.four_wings(voxel=v)
    assert sorted(info["appendages"]) == ["wing2_l", "wing2_r", "wing_l", "wing_r"]
    assert all(e["symmetry"] == "pair" for e in info["appendages"].values())
    ob, info = Z.tail_spikes(voxel=v)
    for n, e in info["appendages"].items():
        if e["kind"] == "spike":
            assert e["root_on"] == ["tail"] and e["parent"] == "tail", (n, e["root_on"])
    ob, info = Z.held_staff(voxel=v)
    assert sorted(info["separate"]) == ["halo", "staff_r"] and Z.shells(ob.data) == 3
    ob, info = Z.naga(voxel=v)
    assert not info["limbs"].keys() & {"leg_l", "leg_r"} and info["appendages"]["snake"]["symmetry"] == "centre_asym"
    ob, info = Z.chibi(voxel=v)
    j = info["joints_hint"]
    assert j["head_top"][2] - j["neck"][2] > 0.3 * info["height"]
    ob, info = Z.dragon(voxel=v)
    a = info["appendages"]
    assert info["kind"] == "quadruped" and len(info["limbs"]) == 4
    assert {a["wing_l"]["symmetry"], a["horn_l"]["symmetry"], a["tail"]["symmetry"]} == {"pair", "centre"}
    # the quadruped's tail sways to one side (not its own mirror image); straight, it is centred
    ob, info = Z.quadruped(voxel=v)
    assert info["appendages"]["tail"]["symmetry"] == "centre_asym"
    ob, info = Z.quadruped(voxel=v, sway=0.0)
    assert info["appendages"]["tail"]["symmetry"] == "centre"
    assert np.isfinite(info["appendages"]["tail"]["mirror_on_self"])


@pytest.mark.parametrize("voxel", [0.008, 0.014])
def test_designed_contacts_away_from_the_root_survive_the_remesh(voxel):
    """The folded wing rests on the thigh, the cape touches the rump and one calf, two
    tentacles touch each other: contacts that are not roots, at fine and coarse voxels."""
    import bodies_zoo as Z
    _ob, info = Z.bird_wings(voxel=voxel)
    for s in "lr":
        c = info["appendages"][f"wing_{s}"]["contacts"]
        assert any(f"leg_{s}" in x["with"] for x in c), (s, c)
    _ob, info = Z.ZOO["cape"](voxel=voxel)
    c = info["appendages"]["cape"]["contacts"]
    assert any("body" in x["with"] and abs(x["centre"][2] - 0.95) < 0.08 for x in c), c          # the rump
    calf = [x for x in c if x["centre"][2] < 0.6]
    assert len(calf) == 1 and calf[0]["with"] == ["leg_l"] and calf[0]["centre"][0] > 0.05, c    # one calf
    _ob, info = Z.ZOO["tentacles"](voxel=voxel)
    touching = [a for a, e in info["appendages"].items() if e["touching"]]
    assert len(touching) == 2
    a, b = touching
    assert any(b in x["with"] for x in info["appendages"][a]["contacts"] + [{"with": info["appendages"][a]["root_on"]}])
    _ob, info = Z.bird_wings(voxel=voxel, rest=False)                    # folded clear of the body
    assert not info["appendages"]["wing_l"]["contacts"]


def test_shells_scale_sides_and_determinism():
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
    for gen in ("quadruped", "tentacles"):                                 # every base can have them
        ob, info = Z.ZOO[gen](voxel=VOXEL, shells=2)
        assert Z.shells(ob.data) == 3, gen
    # half size: everything scales, the voxel stays absolute
    _ob, half = Z.bat_wings(voxel=VOXEL, scale=0.6)
    _ob, info = Z.bat_wings(voxel=VOXEL)
    assert abs(half["height"] / info["height"] - 0.6) < 0.03
    assert abs(half["appendages"]["wing_l"]["root"][2] / info["appendages"]["wing_l"]["root"][2] - 0.6) < 0.03
    # one-sided parts on the other side
    _ob, one = Z.one_wing(voxel=VOXEL, style="bat", side="r")
    assert list(one["appendages"]) == ["wing_r"] and one["appendages"]["wing_r"]["symmetry"] == "one-sided"
    for gen, kw, part in (("shoulder_cannon", {"kind": "pauldron", "side": "r"}, "pauldron_r"),
                          ("shoulder_cannon", {"side": "r"}, "cannon_r"), ("horns_asym", {"big_side": "r"}, "horn_r"),
                          ("weapon_in_hand", {"side": "l"}, "sword_l"), ("ponytail_side", {"side": "r"}, "ponytail")):
        ob, info = Z.ZOO[gen](voxel=VOXEL, **kw)
        co = Z.coords(ob.data)
        want = 1 if part == "sword_l" else -1                               # (the ponytail lies on the right)
        assert np.sign(np.mean(co[Z.part_mask(ob.data, info, part)][:, 0])) == want, (gen, part)
        check_body(gen, ob, info, VOXEL)
    _ob, q = Z.ZOO["dorsal_fin"](voxel=VOXEL, base="quadruped")
    assert q["kind"] == "quadruped" and q["appendages"]["fin"]["symmetry"] == "centre"
    assert len(q["limbs"]) == 4 and "shoulder_fl" in q["joints_hint"] and "hand_l" not in q["joints_hint"]
    # deterministic: the same parameters give the same mesh (noise included, with its seed)
    for kw in ({}, {"noise": 0.004, "seed": 3}):
        ob1, _i = Z.horns_asym(voxel=VOXEL, **kw)
        co1 = Z.coords(ob1.data)
        ob2, _i = Z.horns_asym(voxel=VOXEL, **kw)
        assert co1.shape == Z.coords(ob2.data).shape and np.allclose(co1, Z.coords(ob2.data))


def test_ai_like_options_blend_noise_triangles_colour():
    """blend rounds the seams (only near them, only outwards), noise moves everything a little
    but keeps pairs mirrored, tris gives a triangle mesh of about the asked size, colour gives
    every part its own flat colour (as a colour attribute, or UVs + an image) with a material."""
    import numpy as np

    import bodies_zoo as Z
    v = VOXEL
    ob0, plain = Z.horns_asym(voxel=v)
    co0 = Z.coords(ob0.data)
    ob1, bl = Z.horns_asym(voxel=v, blend=0.04)
    co1 = Z.coords(ob1.data)
    assert co0.shape == co1.shape and Z.open_edges(ob1.data) == (0, 0)
    moved = np.linalg.norm(co1 - co0, axis=1)
    assert moved.max() > 0.004 and (moved > 1e-6).mean() < 0.7              # the seams, not the rest
    check_body("horns_asym+blend", ob1, bl, v)
    co0 = Z.coords(Z.bat_wings(voxel=v)[0].data)
    ob2, nz = Z.bat_wings(voxel=v, noise=0.004, seed=1)
    co2 = Z.coords(ob2.data)
    assert co0.shape == co2.shape and np.median(np.linalg.norm(co2 - co0, axis=1)) > 0.001
    check_body("bat_wings+noise", ob2, nz, v)
    ob3, tr = Z.tentacles_body(voxel=v, tris=9000)
    me = ob3.data
    assert tr["triangles_only"] and abs(len(me.polygons) - 9000) < 900 and Z.open_edges(me) == (0, 0)
    check_body("tentacles+tris", ob3, tr, v)
    ob4, col = Z.cape_body(voxel=v, colour="texture")
    me = ob4.data
    assert me.uv_layers.get("UVMap") and me.materials and Z.COLOUR_ATTR in me.color_attributes
    img = [n.image for n in me.materials[0].node_tree.nodes if n.type == "TEX_IMAGE"][0]
    px = np.empty(img.size[0] * img.size[1] * 4, np.float32)
    img.pixels.foreach_get(px)
    px = px.reshape(img.size[1], img.size[0], 4)
    uv = np.empty(len(me.loops) * 2, np.float32)
    me.uv_layers["UVMap"].data.foreach_get("uv", uv)
    uv = uv.reshape(-1, 2)
    ls = np.empty(len(me.polygons), np.int32)
    me.polygons.foreach_get("loop_start", ls)
    ft = col["face_truth"]
    for f in (0, len(ft) // 2, len(ft) - 1):                               # each face reads its part's colour
        c = uv[ls[f]:ls[f] + 4].mean(axis=0)
        got = px[int(c[1] * img.size[1]), int(c[0] * img.size[0]), :3]
        want = col["colours"][col["labels"][ft[f]]]
        assert np.abs(got - want).max() < 0.02, (f, got, want)
    ob5, ai = Z.bat_wings(voxel=v, preset="ai")
    assert ai["options"]["blend"] and ai["options"]["noise"] and ai["options"]["colour"] == "texture"
    check_body("bat_wings ai", ob5, ai, v)


def test_compose_any_combination_on_any_base():
    """Parts are Kit-level functions on anchors: the same horn fits a humanoid and a
    quadruped; a pair is worked out from what is on the other side."""
    import bodies_zoo as Z
    ob, info = Z.compose("custom", "humanoid", [("bat_wing", {"side": "l"}), ("bat_wing", {"side": "r"}),
                                                ("tail", {"style": "hang"}), ("horn", {"side": "l"}),
                                                ("cannon", {"side": "r"})], voxel=VOXEL)
    a = info["appendages"]
    assert a["wing_l"]["symmetry"] == "pair" and a["tail"]["symmetry"] == "centre"
    assert a["horn_l"]["symmetry"] == a["cannon_r"]["symmetry"] == "one-sided"
    check_body("custom", ob, info, VOXEL)
    ob, info = Z.compose("horned_beast", "quadruped", [("horn", {"side": "l"}), ("horn", {"side": "r"}),
                                                       ("spikes", {"where": "back", "n": 5})], voxel=VOXEL)
    assert info["appendages"]["horn_l"]["parent"] == "head" and info["appendages"]["horn_l"]["symmetry"] == "pair"
    check_body("horned_beast", ob, info, VOXEL)


def test_zoo_v2_bodies_build_with_their_truth():
    """Zoo v2, at the zoo's default voxel (a 3 mm relief needs it): one raised arm is a posed pair
    of limbs whose joints turn with it; the pouch is a one-sided pad on the hip standing about its
    designed height out of the body; the scar is a one-sided relief of a few millimetres."""
    import bodies_zoo as Z
    v = 0.008
    assert set(Z.ZOO_V2) == {"humanoid_raised_arm", "pouch_small", "relief_scar"} and not set(Z.ZOO_V2) & set(Z.ZOO)
    ob, info = Z.humanoid_raised_arm(voxel=v)
    check_body("humanoid_raised_arm", ob, info, v)
    arms, j = info["limbs"], info["joints_hint"]
    assert arms["arm_l"]["symmetry"] == arms["arm_r"]["symmetry"] == "pair_posed"
    assert arms["arm_l"]["twin"] == "arm_r" and arms["arm_r"]["twin"] == "arm_l"
    assert abs(j["wrist_l"][2] - j["wrist_r"][2] - 0.2) < 1e-6 and abs(j["shoulder_l"][2] - j["shoulder_r"][2]) < 0.01
    assert arms["arm_l"]["tip"][2] - arms["arm_r"]["tip"][2] > 0.2               # the hand rises past the wrist
    ob, info = Z.pouch_small(voxel=v)
    check_body("pouch_small", ob, info, v)
    j = info["joints_hint"]
    p = info["appendages"]["pouch_l"]
    assert (p["kind"], p["side"], p["symmetry"], p["parent"]) == ("pouch", "l", "one-sided", "pelvis")
    # (a flat pad on the curved hip stands out more at its corners than at its middle)
    assert "body" in p["root_on"] and 0.5 * p["proud_design"] < p["proud"] < 1.6 * p["proud_design"], p["proud"]
    P = Z.coords(ob.data)[Z.part_mask(ob.data, info, "pouch_l")]
    assert P[:, 0].min() > 0 and P[:, 1].mean() < 0 and abs(P[:, 2].mean() - j["pelvis"][2]) < 0.1   # left hip, front
    ob, info = Z.relief_scar(voxel=v)
    check_body("relief_scar", ob, info, v)
    s = info["appendages"]["scar_l"]
    assert (s["kind"], s["symmetry"], s["rig"], s["relief"]) == ("scar", "one-sided", "skin", True)
    assert 0.25 * s["proud_design"] < s["proud"] < 2.0 * s["proud_design"], s["proud"]
    assert s["proud"] < info["voxel"]                                             # below even one voxel


def test_ain_warp_is_not_its_own_mirror_image():
    """The '+ai' warp is odd in x along x (a symmetric body stays symmetric); '+ain' adds a
    displacement along x that is even in x, a few millimetres, so a body built symmetric is no
    longer its own mirror image: its mirror gap (how far the mirror image of the surface lies
    from it) is well above the plain body's."""
    import numpy as np
    from mathutils.bvhtree import BVHTree

    import bodies_zoo as Z
    rng = np.random.default_rng(7)
    P = np.c_[rng.uniform(0.05, 0.8, 400), rng.uniform(-0.3, 0.3, 400), rng.uniform(0.0, 1.8, 400)]
    M = P * [-1, 1, 1]
    ai = Z.Kit("w", "humanoid", 0.016, opts={"noise": 0.004})._warp_fn()
    a, am = ai(P), ai(M)
    assert np.allclose(am[:, 0], -a[:, 0]) and np.allclose(am[:, 1:], a[:, 1:])          # odd: mirrored
    ain = Z.Kit("w", "humanoid", 0.016, opts={"noise": 0.004, "skew": Z.SKEW})._warp_fn()
    b, bm = ain(P), ain(M)
    even = (b[:, 0] + bm[:, 0]) / 2
    assert np.allclose(bm[:, 1:], b[:, 1:]) and np.abs(even).max() > 0.5 * Z.SKEW        # not odd in x
    assert np.abs(even).max() < 1.5 * Z.SKEW
    other = Z.Kit("w", "humanoid", 0.016, opts={"noise": 0.004, "skew": Z.SKEW, "seed": 1})._warp_fn()
    assert not np.allclose(other(P)[:, 0], b[:, 0])                                      # seeded
    # the same in every Blender process: the noise module's own seed (from the clock) is not used
    from mathutils import noise
    noise.seed_set(12345)
    assert np.array_equal(ain(P), b) and np.array_equal(ai(P), a)

    def gap(ob):
        me = ob.data
        co = Z.coords(me)
        lv, ls, lt = Z._faces(me)
        tree = BVHTree.FromPolygons(co.tolist(), [lv[ls[i]:ls[i] + lt[i]].tolist() for i in range(len(ls))])
        q = co[::7] * [-1, 1, 1]
        return float(np.median([tree.find_nearest(p)[3] for p in q.tolist()]))
    plain = gap(Z.four_arms(voxel=VOXEL)[0])
    skewed = gap(Z.four_arms(voxel=VOXEL, noise=0.004, blend=0.03, skew=Z.SKEW)[0])
    assert skewed > max(5 * plain, 0.1 * Z.SKEW), (plain, skewed)


def test_a_stored_baseline_record_rescores_to_its_stored_score():
    """The baseline harness's scoring holds still (shim parity): records stored with the scores
    they had - one from the first harness's reference run, the others from zoo v2 runs with the
    new columns - re-score to exactly those scores, problem lines included, through score() (the
    old total's lines) and score_new() (the new lines, kept apart). scored_fields() keeps all the
    scores read."""
    import zoo_baseline as zb
    for rec in STORED_RECORDS:
        want = rec["stored"]
        assert zb.score(rec) == (want["score"], want["problems"], want["score_by"]), rec["body"]
        assert zb.score(zb.scored_fields(rec)) == zb.score(rec), rec["body"]
        if "score_new" in want:
            assert zb.score_new(rec) == (want["score_new"], want["problems_new"], want["score_new_by"]), rec["body"]
            assert zb.score_new(zb.scored_fields(rec)) == zb.score_new(rec), rec["body"]


# zoo_baseline.scored_fields of stored records (shares of 0 left out: the scores read them as 0),
# each with the scores it was stored with ("stored"): weapon_in_hand from the first harness's
# reference run (fast, plain), quadruped_shells, humanoid_raised_arm and relief_scar from the zoo v2
# baseline (fast, plain)
STORED_RECORDS = json.loads(
    '[{"body":"weapon_in_hand","dry":{"auto":{"copied":{},"cut":[],"cut_share":{},"lost":{},"mirrored":false,"qr_symm'
    'etry":false,"refused":[],"why_not":""},"left":{"copied":{},"cut":["part_1"],"cut_share":{"arm_r":0.184,"sword_r"'
    ':1.0},"lost":{},"mirrored":true,"qr_symmetry":true,"refused":[],"why_not":""},"right":{"copied":{},"cut":["part_'
    '1"],"cut_share":{"arm_r":0.184,"sword_r":1.0},"lost":{"arm_l":0.151},"mirrored":true,"qr_symmetry":true,"refused'
    '":[],"why_not":""}},"errors":[],"found":[],"joint_errors":{"ankle_l":0.044,"ankle_r":0.044,"elbow_l":0.064,"elbo'
    'w_r":0.295,"hand_l":0.796,"hand_r":0.796,"head":0.038,"head_top":0.002,"hip_l":0.065,"hip_r":0.065,"knee_l":0.07'
    '7,"knee_r":0.077,"neck":0.069,"pelvis":0.085,"shoulder_l":0.008,"shoulder_r":0.008,"wrist_l":0.169,"wrist_r":0.6'
    '32},"mesh":{"height":1.809},"parts":{"arm_l":{"class":"-","detected":"missed","found_as":[],"fragments":0,"kind"'
    ':"arm","merged_with":[],"symmetry":"pair"},"arm_r":{"class":"-","detected":"missed","found_as":[],"fragments":0,'
    '"kind":"arm","merged_with":[],"symmetry":"pair"},"leg_l":{"class":"-","detected":"missed","found_as":[],"fragmen'
    'ts":0,"kind":"leg","merged_with":[],"symmetry":"pair"},"leg_r":{"class":"-","detected":"missed","found_as":[],"f'
    'ragments":0,"kind":"leg","merged_with":[],"symmetry":"pair"},"sword_r":{"class":"-","detected":"missed","found_a'
    's":[],"fragments":0,"kind":"weapon","merged_with":[],"symmetry":"one-sided"}},"phantoms":[],"plan":{"auto":{"blo'
    'cked":null},"left":{"blocked":null},"right":{"blocked":null}},"real":{},"stored":{"problems":["[rig +4] skeleton'
    ' guess off: hand_l by 0.80 m, hand_r by 0.80 m, wrist_r by 0.63 m, elbow_r by 0.29 m, wrist_l by 0.17 m","[step4'
    ' +5] [left] arm_r: a limb is cut off as a part (18%)","[step4 +5] [right] arm_l: limb lost 15%","[step4 +5] [rig'
    'ht] arm_r: a limb is cut off as a part (18%)","[detect +3] sword_r: not found at all"],"score":22.0,"score_by":{'
    '"detect":3.0,"rig":4.0,"step4":15.0}},"truth":{"sword_r":{"kind":"weapon","parent":"hand_r","rig":"prop","root_s'
    'hape":"round","side":"r","symmetry":"one-sided","twin":null,"verts":1778}}},{"body":"quadruped_shells","dry":{"a'
    'uto":{"copied":{},"cut":["snout"],"cut_share":{"body":0.001,"tail":0.989},"lost":{},"mirrored":false,"plan_drift'
    '":{"drift":false,"how":"the executor run twice on the same plan"},"qr_symmetry":false,"refused":[],"unplanned_ch'
    'ange":{"added":[],"added_cm2":0,"islands":0,"lost":[],"lost_cm2":0},"why_not":""},"left":{"copied":{"shell_loose'
    '_1":1.0},"cut":["snout"],"cut_share":{"body":0.001,"tail":0.989},"lost":{},"mirrored":true,"plan_drift":{"drift"'
    ':false,"how":"the executor run twice on the same plan"},"qr_symmetry":true,"refused":[],"unplanned_change":{"add'
    'ed":[{"area_cm2":46.7,"verts":42,"where":{"body":1.0}}],"added_cm2":46.7,"islands":1,"lost":[],"lost_cm2":0},"wh'
    'y_not":""},"right":{"copied":{},"cut":["snout"],"cut_share":{"body":0.001,"tail":0.989},"lost":{"shell_loose_1":'
    '1.0},"mirrored":true,"plan_drift":{"drift":false,"how":"the executor run twice on the same plan"},"qr_symmetry":'
    'true,"refused":[],"unplanned_change":{"added":[],"added_cm2":0,"islands":1,"lost":[{"area_cm2":46.7,"verts":42,"'
    'where":{"shell_loose_1":1.0}}],"lost_cm2":46.7},"why_not":""}},"errors":[],"errors_new":[],"found":[{"kind":"hor'
    'n","name":"horn_l","truth":{"body":0.938,"ear_l":0.031,"ear_r":0.031}},{"kind":"snout","name":"snout_r","truth":'
    '{"leg_br":0.999}},{"kind":"snout","name":"snout_l","truth":{"leg_bl":0.999}},{"kind":"snout","name":"snout","tru'
    'th":{"tail":1.0}}],"height":1.3466899394989014,"joint_errors":{},"joint_errors_quad":{"ankle_bl":0.338,"ankle_br'
    '":0.338,"elbow_fl":0.145,"elbow_fr":0.145,"head":1.208,"hip_bl":0.489,"hip_br":0.504,"knee_bl":0.345,"knee_br":0'
    '.345,"neck":0.756,"pelvis":0.481,"shoulder_fl":0.412,"shoulder_fr":0.412,"wrist_fl":0.531,"wrist_fr":0.444},"mes'
    'h":{"height":1.347},"parts":{"ear_l":{"class":"wrong (horn)","detected":"found","found_as":[["horn_l","horn",1.0'
    ']],"fragments":1,"kind":"ear","merged_with":["ear_r"],"side":"l","symmetry":"pair"},"ear_r":{"class":"wrong (hor'
    'n)","detected":"found","found_as":[["horn_l","horn",1.0]],"fragments":1,"kind":"ear","merged_with":["ear_l"],"si'
    'de":"r","symmetry":"pair"},"leg_bl":{"class":"wrong (snout)","detected":"found","found_as":[["snout_l","snout",0'
    '.911]],"fragments":1,"kind":"leg","merged_with":[],"side":"l","symmetry":"pair"},"leg_br":{"class":"wrong (snout'
    ')","detected":"found","found_as":[["snout_r","snout",0.911]],"fragments":1,"kind":"leg","merged_with":[],"side":'
    '"r","symmetry":"pair"},"leg_fl":{"class":"-","detected":"missed","found_as":[],"fragments":0,"kind":"leg","merge'
    'd_with":[],"side":"l","symmetry":"pair"},"leg_fr":{"class":"-","detected":"missed","found_as":[],"fragments":0,"'
    'kind":"leg","merged_with":[],"side":"r","symmetry":"pair"},"tail":{"class":"wrong (snout)","detected":"found","f'
    'ound_as":[["snout","snout",0.975]],"fragments":1,"kind":"tail","merged_with":[],"side":"c","symmetry":"centre_as'
    'ym"}},"phantoms":["horn_l","snout_r","snout_l"],"plan":{"auto":{"blocked":null,"regions":[{"action":"cut","body_'
    'share":0.0,"limb_share":{},"name":"snout","verts":2147},{"action":"rigid","body_share":0.344,"limb_share":{},"na'
    'me":"horn_l","verts":10441}]},"left":{"blocked":null,"regions":[{"action":"cut","body_share":0.0,"limb_share":{}'
    ',"name":"snout","verts":2147},{"action":"rigid","body_share":0.344,"limb_share":{},"name":"horn_l","verts":10441'
    '}]},"right":{"blocked":null,"regions":[{"action":"cut","body_share":0.0,"limb_share":{},"name":"snout","verts":2'
    '147},{"action":"rigid","body_share":0.344,"limb_share":{},"name":"horn_l","verts":10441}]}},"real":{},"stored":{'
    '"problems":["[detect +1.5] ear_l: found as one part with ear_r","[rig +1] ear_l (ear): classified wrong (horn)",'
    '"[detect +1.5] ear_r: found as one part with ear_l","[rig +1] ear_r (ear): classified wrong (horn)","[rig +1] ta'
    'il (tail): classified wrong (snout)","[rig +1.5] 3 phantom part(s) on body/limbs: horn_l=horn->body, snout_r=sno'
    'ut->leg_br, snout_l=snout->leg_bl"],"problems_new":["[unplanned change +8] [left] 1 island(s) changed that no pl'
    'an allowed: lost 0 cm2, added 46.7 cm2 (near body)","[loose piece copied or lost +4] [left] shell_loose_1: lost '
    '0%, copied over 100%","[unplanned change +8] [right] 1 island(s) changed that no plan allowed: lost 46.7 cm2, ad'
    'ded 0 cm2 (near shell_loose_1)","[loose piece copied or lost +4] [right] shell_loose_1: lost 100%, copied over 0'
    '%","[quadruped skeleton off +4] quadruped skeleton off: head by 1.21 m, neck by 0.76 m, wrist_fl by 0.53 m, hip_'
    'br by 0.50 m, hip_bl by 0.49 m"],"score":7.5,"score_by":{"detect":3.0,"rig":4.5,"step4":0.0},"score_new":28.0,"s'
    'core_new_by":{"loose piece copied or lost":8.0,"quadruped skeleton off":4.0,"unplanned change":16.0}},"truth":{"'
    'ear_l":{"kind":"ear","parent":"head","rig":"chain","root_shape":"oval","side":"l","symmetry":"pair","twin":"ear_'
    'r","verts":324},"ear_r":{"kind":"ear","parent":"head","rig":"chain","root_shape":"oval","side":"r","symmetry":"p'
    'air","twin":"ear_l","verts":324},"tail":{"kind":"tail","parent":"pelvis","rig":"chain","root_shape":"round","sid'
    'e":"c","symmetry":"centre_asym","twin":null,"verts":2202}}},{"body":"humanoid_raised_arm","dry":{"auto":{"copied'
    '":{},"cut":[],"cut_share":{},"lost":{},"mirrored":false,"plan_drift":{"drift":false,"how":"the executor run twic'
    'e on the same plan"},"qr_symmetry":false,"refused":[],"unplanned_change":{"added":[],"added_cm2":0,"islands":0,"'
    'lost":[],"lost_cm2":0},"why_not":""},"left":{"copied":{"arm_l":0.842},"cut":[],"cut_share":{},"lost":{"arm_r":0.'
    '841},"mirrored":true,"plan_drift":{"drift":false,"how":"the executor run twice on the same plan"},"qr_symmetry":'
    'true,"refused":[],"unplanned_change":{"added":[{"area_cm2":1345.9,"verts":3104,"where":{"arm_r":0.99,"body":0.01'
    '}},{"area_cm2":80.5,"verts":196,"where":{"arm_r":1.0}}],"added_cm2":1426.4,"islands":4,"lost":[{"area_cm2":1336.'
    '5,"verts":2838,"where":{"arm_r":1.0}},{"area_cm2":81.0,"verts":162,"where":{"arm_r":0.98,"body":0.02}}],"lost_cm'
    '2":1417.5},"why_not":""},"right":{"copied":{"arm_r":0.844},"cut":[],"cut_share":{},"lost":{"arm_l":0.84},"mirror'
    'ed":true,"plan_drift":{"drift":false,"how":"the executor run twice on the same plan"},"qr_symmetry":true,"refuse'
    'd":[],"unplanned_change":{"added":[{"area_cm2":1336.5,"verts":2838,"where":{"arm_l":1.0,"body":0.0}},{"area_cm2"'
    ':81.0,"verts":162,"where":{"arm_l":1.0}}],"added_cm2":1417.5,"islands":4,"lost":[{"area_cm2":1345.9,"verts":3104'
    ',"where":{"arm_l":1.0}},{"area_cm2":80.5,"verts":196,"where":{"arm_l":0.98,"body":0.02}}],"lost_cm2":1426.4},"wh'
    'y_not":""}},"errors":[],"errors_new":[],"found":[{"kind":"back_extra","name":"back_extra","truth":{"body":0.52,"'
    'leg_l":0.24,"leg_r":0.24}}],"height":1.8088617324829102,"joint_errors":{"ankle_l":0.104,"ankle_r":0.104,"elbow_l'
    '":0.199,"elbow_r":0.147,"hand_l":0.209,"hand_r":0.002,"head":0.027,"head_top":0.002,"hip_l":0.912,"hip_r":0.912,'
    '"knee_l":0.503,"knee_r":0.503,"neck":0.053,"pelvis":0.932,"shoulder_l":0.296,"shoulder_r":0.296,"wrist_l":0.13,"'
    'wrist_r":0.052},"mesh":{"height":1.809},"parts":{"arm_l":{"class":"-","detected":"missed","found_as":[],"fragmen'
    'ts":0,"kind":"arm","merged_with":[],"side":"l","symmetry":"pair_posed"},"arm_r":{"class":"-","detected":"missed"'
    ',"found_as":[],"fragments":0,"kind":"arm","merged_with":[],"side":"r","symmetry":"pair_posed"},"leg_l":{"class":'
    '"generic (back_extra)","detected":"partly","found_as":[["back_extra","back_extra",0.289]],"fragments":1,"kind":"'
    'leg","merged_with":["leg_r"],"side":"l","symmetry":"pair"},"leg_r":{"class":"generic (back_extra)","detected":"p'
    'artly","found_as":[["back_extra","back_extra",0.289]],"fragments":1,"kind":"leg","merged_with":["leg_l"],"side":'
    '"r","symmetry":"pair"}},"phantoms":["back_extra"],"plan":{"auto":{"blocked":null,"regions":[]},"left":{"blocked"'
    ':null,"regions":[]},"right":{"blocked":null,"regions":[]}},"real":{},"stored":{"problems":["[rig +4] skeleton gu'
    'ess off: pelvis by 0.93 m, hip_l by 0.91 m, hip_r by 0.91 m, knee_l by 0.50 m, knee_r by 0.50 m","[rig +0.5] 1 p'
    'hantom part(s) on body/limbs: back_extra=back_extra->body"],"problems_new":["[unplanned change +8] [left] 4 isla'
    'nd(s) changed that no plan allowed: lost 1417.5 cm2, added 1426.4 cm2 (near arm_r, body)","[unplanned change +8]'
    ' [right] 4 island(s) changed that no plan allowed: lost 1426.4 cm2, added 1417.5 cm2 (near arm_l, body)"],"score'
    '":4.5,"score_by":{"detect":0.0,"rig":4.5,"step4":0.0},"score_new":16.0,"score_new_by":{"unplanned change":16.0}}'
    ',"truth":{}},{"body":"relief_scar","dry":{"auto":{"copied":{},"cut":[],"cut_share":{},"lost":{},"mirrored":false'
    ',"plan_drift":{"drift":false,"how":"the executor run twice on the same plan"},"qr_symmetry":true,"refused":[],"u'
    'nplanned_change":{"added":[],"added_cm2":0,"islands":0,"lost":[],"lost_cm2":0},"why_not":""},"left":{"copied":{"'
    'scar_l":0.655},"cut":[],"cut_share":{},"lost":{},"mirrored":true,"plan_drift":{"drift":false,"how":"the executor'
    ' run twice on the same plan"},"qr_symmetry":true,"refused":[],"unplanned_change":{"added":[],"added_cm2":0,"isla'
    'nds":0,"lost":[],"lost_cm2":0},"why_not":""},"right":{"copied":{},"cut":[],"cut_share":{},"lost":{"scar_l":0.682'
    '},"mirrored":true,"plan_drift":{"drift":false,"how":"the executor run twice on the same plan"},"qr_symmetry":tru'
    'e,"refused":[],"unplanned_change":{"added":[],"added_cm2":0,"islands":0,"lost":[],"lost_cm2":0},"why_not":""}},"'
    'errors":[],"errors_new":[],"found":[],"height":1.8088617324829102,"joint_errors":{"ankle_l":0.044,"ankle_r":0.04'
    '4,"elbow_l":0.024,"elbow_r":0.024,"hand_l":0.002,"hand_r":0.002,"head":0.038,"head_top":0.002,"hip_l":0.065,"hip'
    '_r":0.065,"knee_l":0.077,"knee_r":0.077,"neck":0.069,"pelvis":0.085,"shoulder_l":0.008,"shoulder_r":0.008,"wrist'
    '_l":0.006,"wrist_r":0.006},"mesh":{"height":1.809},"parts":{"arm_l":{"class":"-","detected":"missed","found_as":'
    '[],"fragments":0,"kind":"arm","merged_with":[],"side":"l","symmetry":"pair"},"arm_r":{"class":"-","detected":"mi'
    'ssed","found_as":[],"fragments":0,"kind":"arm","merged_with":[],"side":"r","symmetry":"pair"},"leg_l":{"class":"'
    '-","detected":"missed","found_as":[],"fragments":0,"kind":"leg","merged_with":[],"side":"l","symmetry":"pair"},"'
    'leg_r":{"class":"-","detected":"missed","found_as":[],"fragments":0,"kind":"leg","merged_with":[],"side":"r","sy'
    'mmetry":"pair"},"scar_l":{"class":"-","detected":"missed","found_as":[],"fragments":0,"kind":"scar","merged_with'
    '":[],"side":"l","symmetry":"one-sided"}},"phantoms":[],"plan":{"auto":{"blocked":null,"regions":[]},"left":{"blo'
    'cked":null,"regions":[]},"right":{"blocked":null,"regions":[]}},"real":{},"stored":{"problems":["[step4 +8] [lef'
    't] scar_l (one-sided): damaged (lost 0%, copied over 66%)","[step4 +8] [right] scar_l (one-sided): damaged (lost'
    ' 68%, copied over 0%)"],"problems_new":[],"score":16.0,"score_by":{"detect":0.0,"rig":0.0,"step4":16.0},"score_n'
    'ew":0.0,"score_new_by":{}},"truth":{"scar_l":{"kind":"scar","parent":"chest","proud_mm":3.68,"relief":true,"rig"'
    ':"skin","root_shape":"slot","side":"l","symmetry":"one-sided","twin":null,"verts":110}}}]')
