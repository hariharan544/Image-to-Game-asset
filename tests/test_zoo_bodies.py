"""The test zoo (tests/bodies_zoo.py) builds what it claims: one closed fused surface like an
AI mesh, on the ground, facing -Y, with every named extra part where its info says it is, at
the coarse voxel (fast) and at the zoo's default voxel. Generator checks only: what the product
code does with these bodies is for the tests that use them (and tests/zoo_baseline.py)."""

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
    # T-pose: each hand is the far end of its arm along X, at shoulder height
    for s in "lr":
        if f"arm_{s}" in limbs:
            e = limbs[f"arm_{s}"]
            arm = co[Z.part_mask(me, info, f"arm_{s}")]
            sgn = 1 if s == "l" else -1
            assert abs(e["tip"][0] * sgn - (arm[:, 0] * sgn).max()) <= voxel + 1e-6
            assert abs(e["tip"][2] - info["joints_hint"][f"shoulder_{s}"][2]) < 0.06
    assert apps, name
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
        assert np.linalg.norm(np.asarray(e["tip"]) - e["root"]) > 0.03, a
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
        elif sym == "one-sided":
            assert e["twin"] is None and e["mirror_on_surface"] < 0.5, (a, e["mirror_on_surface"])
        else:                                                        # pair_asym / pair_posed
            t = apps.get(e["twin"])
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
