"""Step 8 rig brief (WP2): what the character is, one value per card row, and the rig plan.

- merge: you > Step 1 > Step 2 > job > a sure measurement > Tripo > the AI read > a weak
  measurement > the default; the AI read is never surer than 0.6
- yellow rows when Forge is unsure, red rows when two sure sources disagree
- the plan: which Auto-Rig Pro rig, finger and toe options, chains for the extra parts, stiff
  parts, sockets for props, the bind and the export type
- chain bone counts come from ratios, so a body gives the same plan at any scale
- body_plans.match picks the body plan from the measured parts' shape descriptors
"""

import json
import math
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "blender_scripts"))

from forge_bpy import body_plans as BP          # noqa: E402
from forge_bpy import rig_brief as R            # noqa: E402

# ----------------------------------------------------------------------------- fixtures


def _pts(pts, s):
    return [tuple(c * s for c in p) for p in pts]


def scale_apps(apps, s):
    """The found parts of the same body built s times as big."""
    return [dict(a, chain=_pts(a["chain"], s), length=a["length"] * s, thickness=a["thickness"] * s,
                 width=a["width"] * s, ring=(_pts([a["ring"][0]], s)[0], a["ring"][1], a["ring"][2] * s))
            for a in apps]


def scale_joints(J, s):
    return {"pelvis": tuple(_pts(J["pelvis"], s)), "neck": tuple(_pts(J["neck"], s)),
            "_skull_base": _pts([J["_skull_base"]], s)[0],
            "_conf": {k: {"r": v["r"] * s} for k, v in J["_conf"].items()}}


def bull_apps():
    """What appendages.find gives on an upright cartoon bull (sizes as tests/bodies.bull builds it):
    two horns, two flat ears, a curled tail with a tuft."""
    horn = lambda x: {"name": f"horn_{'l' if x > 0 else 'r'}", "kind": "horn",          # noqa: E731
                      "chain": [(0.11 * x, -0.02, 0.84), (0.22 * x, -0.02, 0.87), (0.27 * x, -0.02, 0.93),
                                (0.26 * x, -0.02, 1.0)], "length": 0.22, "thickness": 0.05, "width": 0.07,
                      "ring": ((0.11 * x, -0.02, 0.84), (-x, 0.0, 0.0), 0.04)}
    ear = lambda x: {"name": f"ear_{'l' if x > 0 else 'r'}", "kind": "ear",            # noqa: E731
                     "chain": [(0.17 * x, 0.0, 0.77), (0.24 * x, 0.0, 0.76), (0.32 * x, 0.0, 0.74)],
                     "length": 0.17, "thickness": 0.024, "width": 0.08,
                     "ring": ((0.17 * x, 0.0, 0.77), (-x, 0.0, 0.0), 0.03)}
    tail = {"name": "tail", "kind": "tail",
            "chain": [(0.0, 0.24, 0.30), (0.02, 0.33, 0.20), (0.12, 0.37, 0.11), (0.30, 0.36, 0.09),
                      (0.35, 0.36, 0.11)], "length": 0.40, "thickness": 0.036, "width": 0.09,
            "ring": ((0.0, 0.24, 0.30), (0.0, -1.0, 0.0), 0.022)}
    return [horn(1), horn(-1), ear(1), ear(-1), tail]


def bull_joints():
    """A neckless head: the skull base sits on the neck base."""
    return {"pelvis": ((0, 0, 0.30), (0, 0, 0.36)), "neck": ((0, -0.02, 0.62), (0, -0.02, 0.74)),
            "_skull_base": (0, -0.02, 0.62), "_conf": {"neck": {"r": 0.12}, "spine": {"r": 0.25}}}


def bull_brief(**you):
    apps = bull_apps()
    layer = {"body_plan": "upright_animal", "hands": "hooves", "feet": "hooves", "build": "heavy"}
    layer.update(you)
    return R.merge({"you": layer, "measured": {"parts": R.parts_from_apps(apps)}}), apps


def _changes(plan, limb_type):
    return [o for o in plan.limb_options if o[1] == limb_type]


# ----------------------------------------------------------------------------- merge


ORDERED = [("you", 1.0), ("step1", 1.0), ("step2", 1.0), ("job", 0.9), ("measured", 0.9), ("tripo", 0.7),
           ("ai", 0.6), ("measured", 0.4)]


def test_merge_precedence():
    # every higher source beats every lower one, one pair at a time
    for i, (hi, s_hi) in enumerate(ORDERED):
        for lo, s_lo in ORDERED[i + 1:]:
            if hi == lo:
                continue
            b = R.merge({hi: {"build": {"value": "slim", "sure": s_hi, "why": "high"}},
                         lo: {"build": {"value": "heavy", "sure": s_lo, "why": "low"}}})
            row = b["fields"]["build"]
            assert (row["value"], row["src"]) == ("slim", hi), (hi, lo, row)
    # nothing said: the default, unsure, so it shows yellow
    b = R.merge({})
    assert b["fields"]["build"]["src"] == "default" and b["fields"]["build"]["state"] == "yellow"
    # every field carries value, src, sure, why and state
    for name in R.FIELD_ORDER:
        assert {"value", "src", "sure", "why", "state"} <= set(b["fields"][name]), name
    # a sure measurement beats Tripo; a weak one loses to Tripo and to the AI read
    b = R.merge({"measured": {"build": {"value": "slim", "sure": 0.85}}, "tripo": {"build": "heavy"}})
    assert b["fields"]["build"]["src"] == "measured"
    b = R.merge({"measured": {"build": {"value": "slim", "sure": 0.75}}, "tripo": {"build": "heavy"}})
    assert b["fields"]["build"]["src"] == "tripo"
    b = R.merge({"measured": {"build": {"value": "slim", "sure": 0.75}}, "ai": {"build": "heavy"}})
    assert b["fields"]["build"]["src"] == "ai"
    # the AI read is never surer than 0.6: always yellow until confirmed
    b = R.merge({"ai": {"build": {"value": "heavy", "sure": 0.99, "why": "looks heavy"}}})
    row = b["fields"]["build"]
    assert row["sure"] == pytest.approx(0.6) and row["state"] == "yellow" and row["why"] == "looks heavy"
    b = R.merge({"ai": {"parts": [{"id": "tail", "kind": "tail", "sure": 0.95}]}})
    assert b["parts"][0]["sure"] == pytest.approx(0.6) and b["parts"][0]["state"] == "yellow"
    # you and Step 1 never show yellow; an answer that is not a card option is left out
    b = R.merge({"you": {"build": "heavy"}, "step1": {"stance": "a"}, "ai": {"hands": "wings"}})
    assert b["fields"]["build"]["state"] == b["fields"]["stance"]["state"] == "ok"
    assert b["fields"]["hands"]["src"] == "default"
    assert b["ignored"] == [{"src": "ai", "field": "hands", "value": "wings", "why": "not a valid answer"}]
    with pytest.raises(ValueError):
        R.merge({"guess": {}})


def test_merge_is_deterministic_and_keeps_step4_facts():
    apps = bull_apps()
    desc = {"shape": "tube", "attach": "root", "sym": "off-centre", "host": "core", "face": "back"}
    measured = {"parts": R.parts_from_apps(apps), "build": {"value": "heavy", "sure": 0.9}}
    measured["parts"][-1]["desc"] = desc
    measured["parts"][-1]["step4"] = {"row": "r3", "disposition": "cut", "extra": 1}
    you = {"parts": [{"id": "tail", "kind": "tail", "motion": "swings"}], "body_plan": "upright_animal"}
    a = R.merge({"you": you, "measured": measured})
    shuffled = {"parts": list(reversed(measured["parts"])), "build": measured["build"]}
    b = R.merge(dict(reversed(list({"you": you, "measured": shuffled}.items()))))
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    tail = next(p for p in a["parts"] if p["id"] == "tail")
    # your answer wins, Step 4's descriptor and row stay with the part
    assert (tail["motion"], tail["src"], tail["found"]) == ("swings", "you", True)
    assert tail["desc"] == desc and tail["step4"] == {"row": "r3", "disposition": "cut"}
    # card order: from the head down, then by name; plain words, no internal names
    assert [p["id"] for p in a["parts"]] == ["horn_l", "horn_r", "ear_l", "ear_r", "tail"]
    assert [p["words"] for p in a["parts"]] == ["Left horn", "Right horn", "Left ear", "Right ear", "Tail"]
    assert a["rigid"] == ["horn_l", "horn_r"]


def test_contradiction_red():
    step1 = R.step1_layer(kind="biped", style="cartoon")
    four = {"body_plan": {"value": "quadruped", "sure": 0.9, "why": "four feet on the ground"}}
    b = R.merge({"step1": step1, "measured": four})
    row = b["fields"]["body_plan"]
    assert row["state"] == "red" and row["src"] == "step1" and row["value"] in ("person", "upright_animal")
    assert [o[0] for o in row["options"]] == [row["value"], "quadruped"]
    assert row["options"][0][1] == "Two legs" and row["options"][1][1] == "Animal on four legs"
    assert "Step 1" in row["reason"] and "four feet on the ground" in row["reason"]
    assert R.alerts(b)["red"] == ["body_plan"]
    # an animal on two legs is inside what "Biped" allows: the shape picks it, shown yellow
    two = {"body_plan": {"value": "upright_animal", "sure": 0.6, "why": "horns, ears and a tail found"}}
    row = R.merge({"step1": step1, "measured": two})["fields"]["body_plan"]
    assert (row["value"], row["src"], row["state"]) == ("upright_animal", "measured", "yellow")
    assert row["why"] == "horns, ears and a tail found; Step 1 said Biped"
    # the director's own answer is not argued with; an unsure source does not make a row red
    row = R.merge({"you": {"body_plan": "person"}, "measured": four})["fields"]["body_plan"]
    assert row["state"] == "ok"
    weak = {"body_plan": {"value": "quadruped", "sure": 0.4}}
    row = R.merge({"step1": step1, "measured": weak})["fields"]["body_plan"]
    assert row["state"] == "yellow"            # not red; yellow because "Biped" still allows either
    # parts: two sure sources naming different kinds
    b = R.merge({"step2": {"parts": [{"id": "horn_l", "kind": "horn"}]},
                 "measured": {"parts": [{"id": "horn_l", "kind": "ear", "sure": 0.7, "found": True}]}})
    assert b["parts"][0]["state"] == "red" and [o[0] for o in b["parts"][0]["options"]] == ["horn", "ear"]


def test_reopen_only_on_a_new_red_row_or_a_changed_body():
    step1 = R.step1_layer(kind="biped")
    old = R.merge({"step1": step1}, sig=[100, 1.0, 0.0], confirmed=True)
    same = R.merge({"step1": step1}, sig=[100, 1.0, 0.0])
    assert not R.reopen(old, same)
    assert R.reopen(old, R.merge({"step1": step1}, sig=[120, 1.0, 0.0]))
    red = R.merge({"step1": step1, "measured": {"body_plan": {"value": "quadruped", "sure": 0.9}}},
                  sig=[100, 1.0, 0.0])
    assert R.reopen(old, red)
    assert R.reopen(None, same)


def test_summary_words():
    b, _ = bull_brief()
    assert R.summary_words(b) == "Animal on two legs · hooves · 2 horns · 2 ears · tail · no props"
    b = R.merge({"you": {"body_plan": "person", "fingers": 4, "feet": "heel_raised",
                         "parts": [{"id": "tail", "kind": "tail", "motion": "not_part"}],
                         "props": [{"part": "sword", "role": "hand_r"}]}})
    assert R.summary_words(b) == "Person · 4 fingers · walks on its toes · 1 prop"


# ----------------------------------------------------------------------------- plan


def test_plan_bull():
    brief, apps = bull_brief()
    p = R.plan(brief, apps, bull_joints(), targets={"engines": ["unity", "unreal"]})
    assert (p.template, p.preset) == ("upright_animal", "human")
    arms = _changes(p, "arm")
    assert [o[0] for o in arms] == ["arm_ref.l", "arm_ref.r"]
    for o in arms:
        assert set(o[3]) == set(R.FINGER_KEYS) and not any(o[3].values())
    legs = _changes(p, "leg")
    assert [o[0] for o in legs] == ["thigh_ref.l", "thigh_ref.r"]
    for o in legs:
        assert set(o[3]) == set(R.TOE_KEYS) and not any(o[3].values())
    assert not any("three_bones_leg" in o[3] for o in p.limb_options) and not p.ankle_at_hock
    tail = next(a for a in apps if a["name"] == "tail")
    arc = sum(math.dist(a, b) for a, b in zip(tail["chain"], tail["chain"][1:]))
    want = R.chain_bones(arc, 0.5 * tail["thickness"], bend=tail["chain"])
    assert p.counts["tail"] == want and 2 <= want <= 10
    assert [c["limb"] for c in p.chains if c["part"] == "tail"] == ["tail"]
    assert p.counts["ear"] == 2
    assert sorted((c["part"], c["side"]) for c in p.chains if c["limb"] == "ears") == [("ear_l", "l"), ("ear_r", "r")]
    assert [r["part"] for r in p.rigid] == ["horn_l", "horn_r"]
    assert all(r["owner_hint"] == "head" for r in p.rigid)
    assert p.face == "head_one" and ("head_ref.x", "head", ".x", {"facial": False}) in p.limb_options
    assert p.export_type == "HUMANOID"
    assert p.counts["neck"] == 1 and ("neck_ref.x", "neck", ".x", {"neck_count": 1}) in p.limb_options
    assert p.bind_engine == "PSEUDO_VOXELS"          # heavy, and hooves have no fingers to blur
    assert p.max_influences == 4                      # Unity's limit when both engines are exported
    assert p.required[:3] == ["pelvis", "neck", "head"]
    json.dumps(p.to_json())                           # stored on the rig as forge_plan


def test_plan_quadruped():
    def quad(feet, neck_len, neck_r=0.08):
        J = {"neck": ((0, -0.40, 0.84), (0, -0.40, 0.84 + neck_len)), "_conf": {"neck": {"r": neck_r}},
             "pelvis": ((0, 0.42, 0.80), (0, 0.15, 0.80))}
        b = R.merge({"you": {"body_plan": "quadruped", "feet": feet}})
        return R.plan(b, [], J)

    assert quad("hooves", 0.10).preset == "horse"
    assert quad("paws", 0.37).preset == "horse"       # a neck 2.3 times as long as it is thick
    p = quad("paws", 0.12)
    assert p.preset == "dog"
    for q in (quad("hooves", 0.10), quad("paws", 0.37), p):
        assert q.export_type == "UNIVERSAL" and not _changes(q, "arm")
        legs = _changes(q, "leg")
        assert [o[0] for o in legs] == ["thigh_ref.l", "thigh_ref.r", "thigh_ref_dupli_001.l", "thigh_ref_dupli_001.r"]
        assert all(not any(o[3].values()) and "three_bones_leg" not in o[3] for o in legs)
    # the creature skeleton even when the card says human animations: four legs cannot be humanoid
    b = R.merge({"you": {"body_plan": "quadruped", "export": "humanoid"}})
    assert R.plan(b).export_type == "UNIVERSAL"
    # the dog and horse rigs have their own tail and ears: set, not added
    b = R.merge({"you": {"body_plan": "quadruped", "feet": "hooves",
                         "parts": [{"id": "tail", "kind": "tail"}, {"id": "ear_l", "kind": "ear"},
                                   {"id": "ear_r", "kind": "ear"}]}})
    assert {c["limb"]: c["add"] for c in R.plan(b).chains} == {"tail": None, "ears": None}


def test_plan_snake_bird():
    tail = {"name": "tail", "kind": "tail", "chain": [(0, 0.1, 0.5), (0, 0.4, 0.2), (0.3, 0.6, 0.05),
                                                      (0.0, 0.9, 0.04)], "thickness": 0.12}
    b = R.merge({"you": {"body_plan": "serpent"}, "measured": {"parts": R.parts_from_apps([tail])}})
    p = R.plan(b, [tail], None)
    assert p.preset == "free" and p.add_limbs == ["spine", "head"]
    assert [c["limb"] for c in p.chains] == ["spline_ik"]
    c = p.chains[0]
    assert c["options"]["spline_bendy"] == 0 and c["options"]["spline_count"] == c["bones"] >= 2
    assert not re.search("head|root|neck", c["options"]["spline_name"])
    assert p.counts["neck"] >= 1 and any(o[1] == "neck" and o[3]["neck_count"] >= 1 for o in p.limb_options)
    assert p.export_type == "UNIVERSAL" and p.required == ["neck", "head"]
    # a snake measured along its body: the spine follows it with ratio-based bones
    b2 = dict(b, measured={"trunk_len": 3.0, "trunk_thick": 0.12})
    assert R.plan(b2).counts["spine"] == R.chain_bones(3.0, 0.06)

    wings = [{"id": "wing_l", "kind": "wing"}, {"id": "wing_r", "kind": "wing"}]
    b = R.merge({"you": {"body_plan": "bird", "parts": wings}})
    p = R.plan(b, [], {"neck": ((0, 0, 1.0), (0, 0, 1.3)), "_conf": {"neck": {"r": 0.05}}}, probe={"bird_ok": True})
    assert p.preset == "bird" and p.preset != "bird_44"
    assert p.counts["neck"] == 3 and p.export_type == "UNIVERSAL"
    assert not p.chains                                # the wings are the bird's arms
    # where the probe saw the bird rig crash this Blender: the human rig, still no bird_44
    p = R.plan(b, [], None, probe={"bird_ok": False})
    assert p.preset == "human" and not p.chains and p.export_type == "UNIVERSAL" and p.counts["neck"] >= 1
    assert any("crashes" in n for n in p.notes)
    # nobody has run the probe yet: the human rig too (spec 5.4: the bird is behind the probe)
    for probe in (None, {}, {"bird_ok": None}):
        p = R.plan(b, [], None, probe=probe)
        assert p.preset == "human" and not p.chains and any("not checked" in n for n in p.notes), probe


def test_plan_heel_raised():
    b = R.merge({"you": {"body_plan": "upright_animal", "feet": "heel_raised"}})
    p = R.plan(b)
    assert p.export_type == "HUMANOID" and p.ankle_at_hock
    assert not any("three_bones_leg" in o[3] for o in p.limb_options)
    assert "thigh_b_l" not in p.required
    b = R.merge({"you": {"body_plan": "upright_animal", "feet": "heel_raised", "export": "creature"}})
    p = R.plan(b)
    assert p.export_type == "UNIVERSAL" and not p.ankle_at_hock
    legs = _changes(p, "leg")
    assert [(o[0], o[3]) for o in legs] == [("thigh_ref.l", {"three_bones_leg": True}),
                                            ("thigh_ref.r", {"three_bones_leg": True})]
    assert {"thigh_b_l", "thigh_b_r"} <= set(p.required)
    assert R.export_rig_type(p, "humanoid") == "UNIVERSAL"      # three-bone legs never export humanoid


def test_extra_ears():
    apps = bull_apps()
    more = [dict(a, name=a["name"] + "2", chain=[(x, y, z + 0.1) for x, y, z in a["chain"]])
            for a in apps if a["kind"] == "ear"]
    apps = apps + more
    b = R.merge({"you": {"body_plan": "upright_animal", "hands": "hooves"},
                 "measured": {"parts": R.parts_from_apps(apps)}})
    p = R.plan(b, apps, bull_joints())
    ears = [c for c in p.chains if c["limb"] == "ears"]
    assert sorted(c["part"] for c in ears) == ["ear_l", "ear_r"]
    assert len({c["side"] for c in ears}) <= 2 and {c["add"] for c in ears} == {"ears"}   # one ears limb
    extra = [c for c in p.chains if c["kind"] == "ear" and c["limb"] != "ears"]
    assert [(c["part"], c["limb"], c["parent_hint"], c["options"]["tail_side"]) for c in extra] == \
        [("ear_l2", "tail_dupli", "head", ".l"), ("ear_r2", "tail_dupli", "head", ".r")]
    assert p.export_type == "HUMANOID" and p.counts["ear"] == 2


def test_chain_bones_scale_free():
    long_thin, stubby = R.chain_bones(1.0, 0.02), R.chain_bones(0.1, 0.03)
    assert long_thin > stubby
    assert (long_thin, stubby) == (8, 2)                     # clamped to 2..8 without bends
    assert R.chain_bones(0.5, 0.05) == 4
    curl = [(math.cos(a) * 0.2, math.sin(a) * 0.2, 0.0) for a in [i * math.pi / 12 for i in range(19)]]
    arc = math.pi * 0.2
    plain = R.chain_bones(arc, arc / 7.5)                     # 3 bones would turn 60 degrees each
    bent = R.chain_bones(arc, arc / 7.5, bend=curl)
    assert plain == 3 and 3 < bent <= 10 and R.max_turn(curl, bent) <= R.MAX_TURN
    assert R.chain_bones(arc, arc / 7.5, cap=3, bend=curl) == 3
    for s in (0.01, 100.0):
        assert R.chain_bones(1.0 * s, 0.02 * s) == long_thin
        assert R.chain_bones(0.1 * s, 0.03 * s) == stubby
        assert R.chain_bones(arc * s, arc / 7.5 * s, bend=[tuple(c * s for c in p) for p in curl]) == bent
    # the whole plan is the same at any scale
    brief, apps = bull_brief()
    ref = R.plan(brief, apps, bull_joints()).to_json()
    for s in (0.01, 100.0):
        assert R.plan(brief, scale_apps(apps, s), scale_joints(bull_joints(), s)).to_json() == ref


def test_fingers_toes_and_neck():
    f = R.finger_changes
    assert list(f("fingers", 5, True).values()) == [True] * 5
    assert list(f("fingers", 4, True).values()) == [True, True, True, True, False]     # drops the pinky
    assert list(f("fingers", 3, True).values()) == [True, True, True, False, False]    # and the ring finger
    assert list(f("fingers", 4, False).values()) == [False, True, True, True, True]
    assert list(f("mitten").values()) == [True, True, False, False, False]
    for h in ("hooves", "paws", "none"):
        assert not any(f(h).values())
    assert R.toe_changes("flat") == {} and R.toe_changes("heel_raised") == {}
    assert list(R.toe_changes("toes", 3).values()) == [True, True, True, False, False]
    assert [R.neck_count(n, 1.0) for n in (0.0, 0.9, 1.5, 2.5)] == [1, 1, 2, 3]
    assert R.neck_count(None, None) == 1
    for s in (0.01, 100.0):
        assert R.neck_count(1.5 * s, 1.0 * s) == 2


def test_props_cloth_and_the_bind():
    b = R.merge({"you": {"body_plan": "person", "build": "heavy", "moves_like": "machine",
                         "props": [{"part": "sword", "role": "hand_r"}, {"part": "hat", "role": "head"},
                                   {"part": "staff", "role": "both_hands", "lead": "l"},
                                   {"part": "bag", "role": "chest"}, {"part": "bell", "role": "swings"},
                                   {"part": "sash", "role": "bends"}],
                         "cloth": [{"part": "skirt", "kind": "skirt", "motion": "swings"},
                                   {"part": "cape", "kind": "cape", "motion": "swings", "width": 0.9, "length": 0.8},
                                   {"part": "scarf", "kind": "cape", "motion": "swings", "width": 0.1, "length": 0.8},
                                   {"part": "hair", "kind": "hair", "motion": "physics_later"},
                                   {"part": "robe", "kind": "cape"}]}})
    p = R.plan(b)
    sockets = {s["prop"]: s for s in p.sockets}
    # lead's choice: held props come off in the game with a socket on the hand; worn ones stay on
    assert (sockets["sword"]["owner"], sockets["sword"]["detachable"]) == ("hand.r", True)
    assert (sockets["hat"]["owner"], sockets["hat"]["detachable"]) == ("head.x", False)
    assert (sockets["staff"]["owner"], sockets["staff"]["other_hand"]) == ("hand.l", "hand.r")
    assert sockets["bag"]["owner"] == "spine_02.x" and sockets["sword"]["socket"] == "cc_socket_sword"
    assert p.skinned_props == ["sash"]
    assert [c["bones"] for c in p.chains if c["part"] == "bell"] == [2]
    assert [c["limb"] for c in p.chains if c["part"] == "skirt"] == ["kilt"]
    cape = [c for c in p.chains if c["part"] == "cape"]
    # chains across the width: clamp(round(3 x width / length), 1, 3)
    assert [c["side"] for c in cape] == ["l", "x", "r"] and {c["limb"] for c in cape} == {"spline_ik"}
    assert [c["side"] for c in p.chains if c["part"] == "scarf"] == ["x"]
    assert p.cloth_masks == ["hair"]
    assert not [c for c in p.chains if c["part"] == "robe"]  # lead's choice: cloth moves with the body
    # a machine: each loose piece follows one bone, and nothing heat-binds it (spec 9.8)
    assert p.bind_engine == "RIGID" and p.rigid_pieces
    living = R.plan(R.merge({"you": {"body_plan": "person", "build": "heavy"}}))
    assert living.bind_engine == "HEAT_MAP" and not living.rigid_pieces   # heavy, but voxels blur fingers


# ----------------------------------------------------------------------------- body plan match

def _d(shape, sym="matched", host="core", face=None, zone=None, ground=False, attach="root", **kw):
    d = {"shape": shape, "attach": attach, "sym": sym, "host": host, "ground": ground}
    if face:
        d["face"] = face
    if zone:
        d["zone"] = zone
    d.update(kw)
    return d


def _limb_pair(name, face, zone, ground=False):
    return [{"id": f"{name}_{s}", "side": s, "desc": _d("tube", face=face, zone=zone, ground=ground,
                                                       twin=f"{name}_{'r' if s == 'l' else 'l'}")}
            for s in ("l", "r")]


def zoo_quadruped():
    """bodies_zoo.quadruped as the part map sees it: four legs from the underside of a long trunk
    to the ground (hoof balls at their ends), small pointed ears on the head, a muzzle, and a tail
    hanging from the rump and swaying a little to one side."""
    return (_limb_pair("leg_f", "down", "low", True) + _limb_pair("leg_b", "down", "low", True)
            + [{"id": "ear_l", "side": "l", "desc": _d("sheet", host="head", face="up")},
               {"id": "ear_r", "side": "r", "desc": _d("sheet", host="head", face="up")},
               {"id": "muzzle", "side": "c", "desc": _d("blob", host="head", face="front")},
               {"id": "tail", "side": "c", "desc": _d("tube", sym="off-centre", face="back", zone="mid")}])


def zoo_four_arms():
    """bodies_zoo.four_arms: a T-pose humanoid with a second arm pair 0.17 m below the first; the
    hands are part of the arms; the legs reach the ground."""
    return (_limb_pair("arm", "side", "high") + _limb_pair("arm2", "side", "mid")
            + _limb_pair("leg", "down", "low", True))


def zoo_person():
    return _limb_pair("arm", "side", "high") + _limb_pair("leg", "down", "low", True)


def test_match_body_plans_from_descriptors():
    for parts, want in ((zoo_quadruped(), "quadruped"), (zoo_four_arms(), "multi_arm"), (zoo_person(), "person")):
        ranked = BP.match(parts)
        assert ranked[0]["plan"] == want, (want, ranked[:3])
        assert BP.pick(parts)["value"] == want and BP.pick(parts)["sure"] >= 0.8, BP.pick(parts)
        # no set or input order decides anything
        assert BP.match(list(reversed(parts))) == ranked
        assert sorted(r["plan"] for r in ranked) == sorted(BP.ORDER)
    assert BP.pick(zoo_quadruped())["why"] == "four feet on the ground"
    # a person with wings on the back is still a person; with horns, a tail and a muzzle an animal
    winged = zoo_person() + [{"id": f"wing_{s}", "side": s, "desc": _d("sheet", face="back", zone="high")}
                             for s in ("l", "r")]
    assert BP.pick(winged)["value"] == "person"
    animal = zoo_person() + [{"id": "tail", "side": "c", "desc": _d("tube", sym="off-centre", face="back")},
                             {"id": "horn_l", "kind": "horn", "side": "l", "desc": _d("tube", host="head", face="up")},
                             {"id": "horn_r", "kind": "horn", "side": "r", "desc": _d("tube", host="head", face="up")},
                             {"id": "muzzle", "side": "c", "desc": _d("blob", host="head", face="front")}]
    assert BP.pick(animal)["value"] == "upright_animal"
    # wings for arms and two legs; an upper body on a snake's tail lying on the ground
    bird = _limb_pair("leg", "down", "low", True) + [{"id": f"wing_{s}", "side": s,
                                                      "desc": _d("sheet", face="side", zone="high")} for s in "lr"]
    assert BP.pick(bird)["value"] == "bird"
    naga = _limb_pair("arm", "side", "high") + [{"id": "snake", "side": "c",
                                                 "desc": _d("tube", sym="off-centre", face="down", ground=True)}]
    assert BP.pick(naga)["value"] == "serpent"
    assert BP.pick([])["value"] == "custom" or BP.pick([])["sure"] < 0.8
    # the measured pick goes into the brief as a measurement, shown yellow when it is not sure
    m = BP.pick(zoo_four_arms())
    b = R.merge({"step1": R.step1_layer("creature"), "measured": {"body_plan": m}})
    assert (b["fields"]["body_plan"]["value"], b["fields"]["body_plan"]["state"]) == ("multi_arm", "ok")


# ----------------------------------------------------------------------------- templates and markers

def test_templates_and_markers():
    for name in BP.ORDER:
        t = BP.TEMPLATES[name]
        assert t["preset"] != "bird_44"
        ids = {m["id"] for m in BP.MARKERS[t["markers"]]}
        assert set(t["marker_ids"]) <= ids, name
        assert set(t["critical"]) <= set(t["marker_ids"])
        # guided mode asks every point of its set; the others only the critical ones (spec 7.2)
        assert all(BP.is_critical(m) or t["estimator"] == "guided" for m in t["critical"])
        for cls, ranges in t["ratio_ranges"].items():
            assert cls in dict(R.FIELDS["proportions"]["options"])
            assert all(lo <= hi for lo, hi in ranges.values())
    for set_name, rows in BP.MARKERS.items():
        ids = {m["id"] for m in rows}
        for m in rows:
            assert set(m["after"]) <= ids, (set_name, m["id"])           # measured from points in the same set
            assert (m["pair"] is None) == m["centre"]
            if m["pair"]:
                assert "LEFT" in m["words"] and "RIGHT" in BP.marker(m["pair"], set_name)["words"]
            for a in m["after"]:                                         # asked after what it depends on
                assert BP.order_key(a, set_name) < BP.order_key(m["id"], set_name), (m["id"], a)
    keys = sorted(["elbow_l", "chin", "knee_l", "shoulder_l", "groin", "wrist_l", "skull_base", "hip_l", "ankle_l"],
                  key=BP.order_key)
    assert keys == ["chin", "skull_base", "shoulder_l", "wrist_l", "elbow_l", "groin", "hip_l", "ankle_l", "knee_l"]
    row2 = BP.marker("wrist_r_2")
    assert row2["id"] == "wrist_r_2" and "RIGHT" in row2["words"] and "second pair of arms" in row2["words"]
    assert BP.stem("shoulder_l_2") == "shoulder" and BP.is_critical("front_wrist_r")
    assert BP.MAX_QUESTIONS == 6 and BP.STEP4_QUESTIONS <= BP.MAX_QUESTIONS
    # lead's choices: height to the top of the head, to the shoulder on four legs
    assert R.value(R.merge({}), "height_to") == "head_top"
    assert R.value(R.merge({"you": {"body_plan": "quadruped"}}), "height_to") == "withers"
    assert R.value(R.merge({}), "face") == "head_one"


def test_two_legged_templates_need_the_joints_auto_rig_pro_needs():
    pytest.importorskip("bpy")
    from forge_bpy import arp_rig
    for name in BP.HUMANOID_TEMPLATES:
        assert list(BP.TEMPLATES[name]["required"]) == arp_rig.REQUIRED


JARGON = re.compile(r"\b(ref|reference bone|ik|fk|deform|vertex group|bone roll|preset|pole)\b", re.I)


def test_director_words_are_plain():
    words = [s["label"] for s in R.FIELDS.values()] + [s["note"] for s in R.FIELDS.values()]
    words += [w for s in R.FIELDS.values() for _v, w in s["options"]]
    words += [w for k in R.KIND_WORDS for w in (R.KIND_WORDS[k], R.KIND_ONE[k], R.KIND_PLURAL[k])]
    words += [w for _k, w in R.MOTIONS + R.CLOTH_MOTIONS + R.PROP_ROLES]
    words += [BP.TEMPLATES[n]["words"] for n in BP.ORDER] + [BP.TEMPLATES[n]["short"] for n in BP.ORDER]
    words += [m["words"] for rows in BP.MARKERS.values() for m in rows]
    b, _ = bull_brief()
    words += [R.summary_words(b)] + [p["words"] for p in b["parts"]]
    red = R.merge({"step1": R.step1_layer("biped"), "measured": {"body_plan": {"value": "quadruped", "sure": 0.9}}})
    words += [red["fields"]["body_plan"]["reason"]] + [w for _v, w in red["fields"]["body_plan"]["options"]]
    words += [r["why"] for parts in (zoo_quadruped(), zoo_four_arms(), zoo_person()) for r in BP.match(parts)]
    for w in words:
        assert not JARGON.search(w), w
        assert "_" not in w, w


# ----------------------------------------------------------------------------- review fixes


def _arc(deg, pts, radius=1.0, rise=0.0):
    """pts points along a circle arc turning `deg` degrees (a helix when it rises)."""
    return [(radius * math.cos(math.radians(deg) * i / (pts - 1)), radius * math.sin(math.radians(deg) * i / (pts - 1)),
             rise * i / (pts - 1)) for i in range(pts)]


def _extras(*specs):
    """Found parts the way appendages.find names them today: ('extra_l', x, z) and so on."""
    return [{"name": n, "kind": n.rstrip("0123456789").rsplit("_", 1)[0] if "_" in n else n,
             "chain": [(x, 0.0, z), (x + (0.3 if x > 0 else -0.3 if x < 0 else 0.0), 0.05, z - 0.05)],
             "length": 0.3, "thickness": 0.06, "width": 0.07} for n, x, z in specs]


def test_multi_arm_plans_an_arm_copy_per_extra_arm():
    # nothing found yet: the card's pairs of arms still give the arm copies, waiting for their points
    p = R.plan(R.merge({"you": {"body_plan": "multi_arm", "arm_pairs": 2}}))
    arms = [(c["part"], c["add"], c["row"], c["found"]) for c in p.chains if c["limb"] == "arm_dupli"]
    assert arms == [("arm_l2", "arm.l", 2, False), ("arm_r2", "arm.r", 2, False)]
    assert p.export_type == "HUMANOID" and p.preset == "human"
    # the finder calls extra arms 'extra': on the body's sides they become the arm copies, not stiff
    apps = _extras(("extra_l", 0.2, 1.1), ("extra_r", -0.2, 1.1))
    b = R.merge({"you": {"body_plan": "multi_arm", "arm_pairs": 2}, "measured": {"parts": R.parts_from_apps(apps)}})
    assert [(q["id"], q["kind"], q["motion"], q["state"]) for q in b["parts"]] == \
        [("extra_l", "arm", "bends", "yellow"), ("extra_r", "arm", "bends", "yellow")]
    assert b["rigid"] == [] and "2 extra arms" in R.summary_words(b)
    p = R.plan(b, apps)
    assert [(c["part"], c["limb"], c["add"], c["row"], c["found"]) for c in p.chains] == \
        [("extra_l", "arm_dupli", "arm.l", 2, True), ("extra_r", "arm_dupli", "arm.r", 2, True)]
    assert p.rigid == []
    # a stiff choice is kept: that arm copy waits for its points, the part stays stiff
    you = {"body_plan": "multi_arm", "arm_pairs": 2, "parts": [{"id": "extra_l", "motion": "stiff"}]}
    p = R.plan(R.merge({"you": you, "measured": {"parts": R.parts_from_apps(apps)}}), apps)
    assert [(c["part"], c["found"]) for c in p.chains] == [("arm_l2", False), ("extra_r", True)]
    assert [r["part"] for r in p.rigid] == ["extra_l"]
    # a part on the head is never an arm
    head = [{"id": "head_extra_l", "kind": "head_extra", "found": True}, {"id": "head_extra_r", "kind": "head_extra"}]
    p = R.plan(R.merge({"you": {"body_plan": "multi_arm"}, "measured": {"parts": head}}))
    assert {c["part"] for c in p.chains if c["limb"] == "arm_dupli"} == {"arm_l2", "arm_r2"}
    assert all(r["owner_hint"] == "head" for r in p.rigid)
    # descriptors: the four-armed zoo body's whole part map. The rig's own arms (the pair at the
    # shoulders) and legs are not extra parts; the second pair reads as arms
    four = [dict(q, found=True) for q in zoo_four_arms()]
    b = R.merge({"you": {"body_plan": "multi_arm"}, "measured": {"parts": four}})
    assert [q["id"] for q in b["parts"]] == ["arm2_l", "arm2_r"] and b["rigid"] == []
    assert b["limbs"] == [{"id": "arm_l", "role": "arm"}, {"id": "arm_r", "role": "arm"},
                          {"id": "leg_l", "role": "leg"}, {"id": "leg_r", "role": "leg"}]
    p = R.plan(b)
    assert [c["part"] for c in p.chains if c["limb"] == "arm_dupli"] == ["arm2_l", "arm2_r"]
    # nobody set the number of pairs: the parts found set it; two found pairs make rows 2 and 3
    apps4 = apps + _extras(("extra_l2", 0.2, 0.9), ("extra_r2", -0.2, 0.9))
    b = R.merge({"you": {"body_plan": "multi_arm"}, "measured": {"parts": R.parts_from_apps(apps4)}})
    assert (b["fields"]["arm_pairs"]["value"], b["fields"]["arm_pairs"]["src"]) == (3, "measured")
    p = R.plan(b, apps4)
    assert [(c["part"], c["row"]) for c in p.chains] == \
        [("extra_l", 2), ("extra_r", 2), ("extra_l2", 3), ("extra_r2", 3)]
    # the same parts in any order give the same plan
    assert R.plan(dict(b, parts=list(reversed(b["parts"]))), list(reversed(apps4))).to_json() == p.to_json()


def test_something_else_gives_every_part_a_chain():
    apps = _extras(("extra_l", 0.2, 0.5), ("extra_r", -0.2, 0.5), ("back_extra", 0.0, 0.5))
    b = R.merge({"you": {"body_plan": "custom"}, "measured": {"parts": R.parts_from_apps(apps)}})
    assert {q["motion"] for q in b["parts"]} == {"bends"} and b["rigid"] == []
    p = R.plan(b, apps)
    assert p.preset == "free" and p.rigid == []
    chains = [(c["part"], c["limb"], c["parent_hint"]) for c in p.chains]
    assert chains == [("back_extra", "tail_dupli", "root"), ("extra_l", "tail_dupli", "root"),
                      ("extra_r", "tail_dupli", "root")]
    for c, a in zip(p.chains, sorted(apps, key=lambda a: a["name"])):
        assert c["bones"] == R.chain_bones(math.dist(*a["chain"]), 0.5 * a["thickness"])
    # only what the director makes stiff is stiff; a trunk bends on a smooth curve
    you = {"body_plan": "custom", "parts": [{"id": "extra_l", "motion": "stiff"}, {"id": "nose", "kind": "trunk"}]}
    p = R.plan(R.merge({"you": you, "measured": {"parts": R.parts_from_apps(apps)}}), apps)
    assert p.rigid == [{"part": "extra_l", "owner_hint": "root"}]
    assert [c["limb"] for c in p.chains if c["part"] == "nose"] == ["spline_ik"]
    # 'Something else' is what match() falls back to: from there the parts still get chains
    m = BP.pick([])
    b = R.merge({"measured": {"body_plan": m, "parts": R.parts_from_apps(apps)}})
    assert R.value(b, "body_plan") == "custom" and len(R.plan(b, apps).chains) == 3


def test_coarse_curled_chain_gets_the_bones_of_the_real_curve():
    # appendages.find gives 6 points; a 240 degree curl on them needs what the smooth curl needs
    for deg, want in ((180, 6), (200, 6), (240, 7)):
        L = math.radians(deg)
        r = L / (2.5 * 4)                             # 4 bones before any bend
        dense = R.chain_bones(L, r, bend=_arc(deg, 400))
        assert dense == want
        assert R.chain_bones(L, r, bend=_arc(deg, 6)) == want, deg
    # the bend rule is exactly 35 degrees: 4 bones on a 139 degree arc turn 34.75 each, on 141 35.25
    L = math.radians(139.0)
    assert R.chain_bones(L, L / 5.0, bend=_arc(139.0, 61)) == 4
    L = math.radians(141.0)
    assert R.chain_bones(L, L / 5.0, bend=_arc(141.0, 61)) == 5
    assert R.max_turn(_arc(141.0, 61), 5) <= 35.0 < R.max_turn(_arc(141.0, 61), 4)
    # 340 degrees needs exactly 10; more turn than 10 bones can follow still stops at 10
    L = math.radians(340.0)
    assert R.chain_bones(L, L / 5.0, bend=_arc(340.0, 81)) == 10
    L = math.radians(380.0)
    assert R.chain_bones(L, L / 5.0, bend=_arc(380.0, 81, rise=0.2)) == 10
    # a coarse curl is the same at any scale
    for s in (0.01, 100.0):
        pts = [tuple(c * s for c in p) for p in _arc(240, 6)]
        assert R.chain_bones(math.radians(240) * s, math.radians(240) / 10 * s, bend=pts) == 7


def test_descriptor_schema_is_declared_and_checked():
    assert BP.DESC_SHAPES == ("tube", "sheet", "blob", "shell")
    assert BP.DESC_ATTACH == ("root", "slot", "along", "contact")
    assert BP.DESC_SYM == ("matched", "add-on", "differs", "posed", "off-centre")
    assert set(BP.DESC_KEYS) >= {"shape", "attach", "sym", "host", "face", "zone", "ground", "twin", "tips", "taper"}
    desc, bad = BP.clean_desc({"shape": "cylinder", "attach": "root", "zone": "top", "taper": float("nan"),
                               "tips": 0, "ground": 1, "girth": [0.1, 0.2]})
    assert desc == {"attach": "root", "ground": True, "girth": [0.1, 0.2]}
    assert sorted(k for k, _v in bad) == ["shape", "taper", "tips", "zone"]
    tail = {"id": "tail", "kind": "tail", "desc": {"shape": "cylinder", "face": "back"}}
    b = R.merge({"measured": {"parts": [tail]}})
    assert b["parts"][0]["desc"] == {"face": "back"}
    assert [(i["part"], i["desc"]) for i in b["ignored"]] == [("tail", "shape")]
    # a part lying along the body, or only touching it, is never a limb
    for attach in ("along", "contact"):
        legs = [dict(q, desc=dict(q["desc"], attach=attach)) if q["id"].startswith("leg_f") else q
                for q in zoo_quadruped()]
        assert BP.features(legs)["leg_pairs"] == 1, attach
    # a robe reaching the ground hides two legs
    robe = {"id": "robe", "side": "c", "desc": _d("shell", face="down", zone="low", ground=True)}
    assert BP.pick(_limb_pair("arm", "side", "high") + [robe])["value"] == "person"
    # arms hanging from the upper two thirds are arms
    assert BP.pick(_limb_pair("arm", "down", "mid") + _limb_pair("leg", "down", "low", True))["value"] == "person"


def test_animal_cues_need_real_horns_and_ears():
    person = zoo_person()
    spikes = [{"id": f"spike{i}", "side": "c", "desc": _d("tube", sym="off-centre", host="head", face="up", taper=0.3)}
              for i in range(14)]
    flat_ears = [{"id": f"ear_{s}", "side": s, "desc": _d("sheet", host="head", face="side", reach=0.1)} for s in "lr"]
    pony = [{"id": "ponytail", "side": "c", "desc": _d("tube", sym="off-centre", host="head", face="back", taper=0.4)}]
    for extra in (spikes, flat_ears, spikes + flat_ears, pony + flat_ears):
        m = BP.pick(person + extra)
        assert m["value"] == "person" and m["sure"] >= 0.8, m
        row = R.merge({"step1": R.step1_layer("biped"), "measured": {"body_plan": m}})["fields"]["body_plan"]
        assert row["value"] == "person"
    # a pair of cones and ears that stick out lean towards an animal, but not surely enough to
    # settle Step 1's "Biped" on their own; a tail and a muzzle do
    horns = [{"id": f"horn_{s}", "side": s, "desc": _d("tube", host="head", face="up", taper=0.3, twin=f"horn_{t}")}
             for s, t in (("l", "r"), ("r", "l"))]
    ears = [{"id": f"ear_{s}", "side": s, "desc": _d("sheet", host="head", face="up", reach=0.5)} for s in "lr"]
    m = BP.pick(person + horns + ears)
    assert m["value"] == "upright_animal" and m["sure"] < R.DISAGREE
    assert BP.features(person + horns + ears)["cue_names"] == ["horns", "ears"]
    unicorn = [{"id": "horn", "side": "c", "desc": _d("tube", host="head", face="up", taper=0.2)}]
    assert BP.features(person + unicorn)["cue_names"] == ["horns"]
    tail = [{"id": "tail", "side": "c", "desc": _d("tube", sym="off-centre", face="back")}]
    muzzle = [{"id": "muzzle", "side": "c", "desc": _d("blob", host="head", face="front")}]
    m = BP.pick(person + horns + ears + tail + muzzle)
    assert m["value"] == "upright_animal" and m["sure"] >= R.DISAGREE


def test_step1_biped_alone_is_not_a_sure_person():
    step1 = R.step1_layer(kind="biped")
    for measured in (None, {"value": "person", "sure": 0.0}):
        layers = {"step1": step1, **({"measured": {"body_plan": measured}} if measured else {})}
        row = R.merge(layers)["fields"]["body_plan"]
        assert row["value"] == "person" and row["state"] == "yellow" and row["sure"] < R.STRONG, row
    row = R.merge({"step1": step1})["fields"]["body_plan"]
    assert row["src"] == "step1" and "either Person or Animal standing on two legs" in row["why"]
    # an unsure reading inside what Step 1 allows is the best guess, still yellow
    row = R.merge({"step1": step1, "measured": {"body_plan": {"value": "upright_animal", "sure": 0.3}}})["fields"]
    assert (row["body_plan"]["value"], row["body_plan"]["state"]) == ("upright_animal", "yellow")
    # Step 1's "Four-legged animal" leaves no choice: it stays sure
    row = R.merge({"step1": R.step1_layer("quadruped")})["fields"]["body_plan"]
    assert (row["value"], row["state"], row["sure"]) == ("quadruped", "ok", 1.0)


def test_cloth_parts_move_with_the_body():
    b = R.merge({"measured": {"parts": [{"id": "cape", "kind": "cape", "found": True, "sure": 0.9},
                                        {"id": "skirt", "kind": "skirt", "found": True, "sure": 0.9},
                                        {"id": "tail", "kind": "tail", "found": True, "sure": 0.9}]}})
    assert [q["id"] for q in b["parts"]] == ["tail"] and b["rigid"] == []
    assert [(c["part"], c["kind"], c["motion"]) for c in b["cloth"]] == [("cape", "cape", "with_body"),
                                                                         ("skirt", "skirt", "with_body")]
    p = R.plan(b)
    assert p.rigid == [] and not [c for c in p.chains if c["part"] in ("cape", "skirt")]
    # the director's swinging cape gets its chains; a cape made stiff on purpose stays stiff
    b = R.merge({"you": {"parts": [{"id": "cape", "motion": "swings"}]},
                 "measured": {"parts": [{"id": "cape", "kind": "cape", "found": True, "width": 0.6, "length": 0.8}]}})
    assert [c["limb"] for c in R.plan(b).chains] == ["spline_ik", "spline_ik"]
    b = R.merge({"you": {"parts": [{"id": "cape", "kind": "cape", "motion": "stiff"}]}})
    assert b["rigid"] == ["cape"] and b["cloth"] == []


def test_plan_does_not_depend_on_list_order():
    apps = bull_apps()
    apps = apps + [dict(a, name="tail2", chain=[(x * 0.5, y, z) for x, y, z in a["chain"]]) for a in apps
                   if a["kind"] == "tail"]
    b = R.merge({"you": {"body_plan": "upright_animal"}, "measured": {"parts": R.parts_from_apps(apps)}})
    ref = R.plan(b, apps, bull_joints()).to_json()
    assert [(c["part"], c["limb"]) for c in ref["chains"] if c["kind"] == "tail"] == [("tail", "tail"),
                                                                                    ("tail2", "tail_dupli")]
    assert R.plan(dict(b, parts=list(reversed(b["parts"]))), list(reversed(apps)), bull_joints()).to_json() == ref
    wings = [{"id": "wing_l2", "kind": "wing", "side": "l"}, {"id": "wing_l", "kind": "wing", "side": "l"},
             {"id": "wing_r", "kind": "wing", "side": "r"}, {"id": "wing_r2", "kind": "wing", "side": "r"}]
    b = R.merge({"you": {"body_plan": "bird", "parts": wings}})
    for order in (b["parts"], list(reversed(b["parts"]))):
        p = R.plan(dict(b, parts=order), probe={"bird_ok": True})
        assert [c["part"] for c in p.chains] == ["wing_l2", "wing_r2"]     # wing_l and wing_r are its arms
    # one source naming the same part twice: the surer entry, whatever the order, and it is reported
    two = [{"id": "tail", "kind": "tail", "sure": 0.9}, {"id": "tail", "kind": "tentacle", "sure": 0.7}]
    for order in (two, list(reversed(two))):
        b = R.merge({"measured": {"parts": order}})
        assert b["parts"][0]["kind"] == "tail" and b["ignored"][0]["why"].startswith("listed twice")


def test_rig_limbs_the_body_lacks_are_removed():
    def quad(parts):
        return R.plan(R.merge({"you": {"body_plan": "quadruped", "feet": "hooves", "parts": parts}}))

    full = quad([{"id": "tail", "kind": "tail"}, {"id": "ear_l", "kind": "ear"}, {"id": "ear_r", "kind": "ear"}])
    assert full.remove_limbs == [] and {c["limb"]: c["add"] for c in full.chains} == {"tail": None, "ears": None}
    p = quad([{"id": "tail", "kind": "tail", "motion": "not_part"}, {"id": "ear_l", "kind": "ear"},
              {"id": "ear_r", "kind": "ear"}])
    assert p.remove_limbs == [("tail_00_ref.x", "tail", ".x")]
    p = quad([{"id": "tail", "kind": "tail"}, {"id": "ear_l", "kind": "ear"}])
    assert p.remove_limbs == [("ear_01_ref.r", "ear", ".r")]
    p = quad([{"id": "tail", "kind": "tail", "motion": "stiff"}])
    assert p.remove_limbs == [("tail_00_ref.x", "tail", ".x"), ("ear_01_ref.l", "ear", ".l"),
                              ("ear_01_ref.r", "ear", ".r")]
    assert [r["part"] for r in p.rigid] == ["tail"]
    json.dumps(p.to_json())
    # the ears limb comes as a pair on any rig: one ear drops the other side
    p = R.plan(R.merge({"you": {"body_plan": "person", "parts": [{"id": "ear_l", "kind": "ear"}]}}))
    assert p.remove_limbs == [("ear_01_ref.r", "ear", ".r")] and [c["add"] for c in p.chains] == ["ears"]
    assert R.plan(R.merge({"you": {"body_plan": "person"}})).remove_limbs == []


def test_spec_thresholds_at_their_edges():
    assert (R.STRONG, R.DISAGREE, R.AI_CAP) == (0.8, 0.5, 0.6)
    assert (R.BONE_LEN, R.MIN_BONES, R.BASE_MAX, R.BEND_MAX, R.MAX_TURN) == (2.5, 2, 8, 10, 35.0)
    # a measurement 0.8 sure beats Tripo and shows as sure; 0.79 loses to it and shows yellow
    b = R.merge({"measured": {"build": {"value": "slim", "sure": 0.8}}, "tripo": {"build": "heavy"}})
    assert b["fields"]["build"]["src"] == "measured"
    b = R.merge({"measured": {"build": {"value": "slim", "sure": 0.79}}, "tripo": {"build": "heavy"}})
    assert b["fields"]["build"]["src"] == "tripo"
    assert R.merge({"measured": {"build": {"value": "slim", "sure": 0.8}}})["fields"]["build"]["state"] == "ok"
    assert R.merge({"measured": {"build": {"value": "slim", "sure": 0.79}}})["fields"]["build"]["state"] == "yellow"
    # two sources exactly 0.5 sure that differ make a red row; 0.49 does not
    def build(src, value, sure):
        return {src: {"build": {"value": value, "sure": sure}}}

    assert R.merge(build("ai", "heavy", 0.5) | build("measured", "slim", 0.5))["fields"]["build"]["state"] == "red"
    assert R.merge(build("ai", "heavy", 0.5) | build("measured", "slim", 0.49))["fields"]["build"]["state"] == "yellow"
    # spec 5.2: any two sure sources that disagree, even under an unsure winner
    b = R.merge(build("step2", "heavy", 0.4) | build("measured", "slim", 0.9) | build("tripo", "round", 0.7))
    row = b["fields"]["build"]
    assert (row["value"], row["state"]) == ("heavy", "red") and [o[0] for o in row["options"]] == ["slim", "round"]
    # ears: 3 bones just past 4 times the root width, 1 just under twice the thickness
    assert R.ear_bones({}, {"length": 4.01, "width": 1.0, "thickness": 0.1}) == 3
    assert R.ear_bones({}, {"length": 3.99, "width": 1.0, "thickness": 0.1}) == 2
    assert R.ear_bones({}, {"length": 0.199, "width": 1.0, "thickness": 0.1}) == 1
    assert R.ear_bones({}, {"length": 0.201, "width": 1.0, "thickness": 0.1}) == 2
    # neck: 1 bone under 1.0 times its thickness, 2 under 2.0, else 3; the same at any scale
    assert [R.neck_count(x, 1.0) for x in (0.99, 1.0, 1.99, 2.0)] == [1, 2, 2, 3]
    for k in (1.0, 2.0):
        for s in (0.01, 0.0137, 7.3, 100.0):
            r = 0.137 * s
            base = (0.31 * s, -0.2 * s, 1.1 * s)
            J = {"neck": (base, (base[0], base[1], base[2] + k * 2 * r)), "_conf": {"neck": {"r": r}}}
            assert R.plan(R.merge({}), [], J).counts["neck"] == int(k) + 1, (k, s)
    # spine: 3 bones when the trunk is more than 2.5 times as long as thick
    for ratio, want in ((2.6, 3), (2.5, None), (2.4, None)):
        assert R.plan(R.merge({}) | {"measured": {"trunk_len": ratio, "trunk_thick": 1.0}}).counts["spine"] == want
    # four legs: the horse rig for a neck more than 1.5 times as long as thick
    assert [BP.choose_preset("quadruped", "", "paws", r)[0] for r in (1.49, 1.5, 1.51)] == ["dog", "dog", "horse"]
    # cape chains: clamp(round(3 x width / length), 1, 3)
    strips = [len(R._cloth_chains({"part": "cape", "kind": "cape", "width": w, "length": 1.0}, None, None))
              for w in (0.49, 0.51, 0.83, 0.84)]
    assert strips == [1, 2, 2, 3]
    # a tail end loop more than 1.5 times the tail's radius is a tuft, stiff on the last bone
    tail = {"name": "tail", "kind": "tail", "chain": [(0, 0.2, 0.5), (0, 0.5, 0.4), (0, 0.8, 0.3)], "thickness": 0.06}
    for end, tuft in ((0.0451, True), (0.0449, False)):
        b = R.merge({"you": {"body_plan": "upright_animal"},
                     "measured": {"parts": R.parts_from_apps([dict(tail, end_radius=end)])}})
        regions = R.plan(b, [dict(tail, end_radius=end)]).rigid_regions
        assert (regions == [{"region": "tuft", "part": "tail", "bone": "last", "owner_hint": "tail"}]) == tuft


def test_mark_ids_name_what_they_belong_to():
    assert BP.stem("grip:tripo_part_5") == "grip" and BP.is_critical("grip:tripo_part_5")
    assert BP.order_key("grip:tripo_part_5")[1] == 1                  # never read as an arm row
    row = BP.marker("grip:sword")
    assert row["id"] == "grip:sword" and row["owner"] == "sword" and row["words"] == "where the hand holds it"
    assert BP.stem("part:tail") == "part_start" and BP.is_critical("part:tail") and BP.marker("part:tail")
    # spec 7.2: ear and wing roots are critical points of their own
    for mid in ("ear_root_l", "ear_root_r", "wing_root_l"):
        assert BP.is_critical(mid) and BP.marker(mid) is not None
    assert "ear_root_l" in BP.TEMPLATES["upright_animal"]["critical"]
    assert "wing_root_l" in BP.TEMPLATES["bird"]["critical"]
    # only arm points come once per extra arm pair, and only in the two-legged set
    assert "second pair of arms" in BP.marker("shoulder_l_2")["words"]
    assert BP.marker("front_elbow_r_2", "quadruped") is None and BP.marker("knee_l_2") is None
    assert BP.marker("front_elbow_r", "quadruped")["words"] == "the elbow of the RIGHT front leg"


def test_small_review_fixes():
    # numbers that are not numbers are no answer
    for bad in (float("nan"), float("inf")):
        row = R.merge({"measured": {"height_m": {"value": bad, "sure": 0.9}}})["fields"]["height_m"]
        assert row["src"] == "default" and row["state"] == "yellow"
    # swinging pairs keep their sides; spline names are unique and never hold head, root or neck
    b = R.merge({"you": {"parts": [{"id": "fin_l", "kind": "fin"}, {"id": "fin_r", "kind": "fin"},
                                   {"id": "head_tentacle", "kind": "tentacle"},
                                   {"id": "root_tentacle", "kind": "tentacle"},
                                   {"id": "Neck_Trunk", "kind": "trunk"}]}})
    p = R.plan(b)
    assert [(c["part"], c["options"]["tail_side"]) for c in p.chains if c["kind"] == "fin"] == [("fin_l", ".l"),
                                                                                                ("fin_r", ".r")]
    names = [c["options"]["spline_name"] for c in p.chains if c["limb"] == "spline_ik"]
    assert len(set(names)) == len(names) == 3 and not any(re.search("head|root|neck", n, re.I) for n in names)
    # hooves are on the stiff list and stiffen the hand and foot they sit on
    b, apps = bull_brief()
    assert b["rigid"] == ["horn_l", "horn_r", "hooves"]
    assert R.plan(b, apps, bull_joints()).rigid_regions == [{"region": "hooves", "where": ["hand", "foot"],
                                                             "owner_hint": None}]
    claws = R.merge({"you": {"hands": "claws", "feet": "paws"}})
    assert claws["rigid"] == ["claws"] and R.plan(claws).rigid_regions[0]["where"] == ["hand"]
    # a brief from elsewhere with a bad body plan or bare parts still plans
    p = R.plan({"fields": {"body_plan": {"value": "dragon"}}, "parts": [{"id": "tail"}]})
    assert p.template == "person" and [r["part"] for r in p.rigid] == ["tail"]


# ----------------------------------------------------------------------------- one answer per piece

def _chains(p, *keys):
    return [tuple(c.get(k) for k in keys) for c in p.chains]


def test_a_lower_stiff_list_never_overrides_how_you_said_a_part_moves():
    # you said the tail bends; the shape's stiff list (and the image's) says stiff: you win, and
    # the card row and the plan agree
    for low in ("measured", "ai", "tripo"):
        b = R.merge({"you": {"parts": [{"id": "tail", "kind": "tail", "motion": "bends"}]},
                     low: {"parts": [{"id": "tail", "kind": "tail", "found": True}], "rigid": ["tail"]}})
        assert [(q["id"], q["motion"]) for q in b["parts"]] == [("tail", "bends")] and b["rigid"] == [], low
        assert [i for i in b["ignored"] if i.get("list") == "rigid"] == \
            [{"src": low, "list": "rigid", "id": "tail", "why": "you said: bends"}]
        p = R.plan(b)
        assert _chains(p, "part", "limb") == [("tail", "tail")] and p.rigid == []
    # a stored brief given back as your answers: its own part row says more than its stiff list
    old = R.merge({"measured": {"parts": [{"id": "tail", "kind": "tail", "motion": "stiff", "sure": 0.9}]}})
    assert old["rigid"] == ["tail"]
    new = R.merge({"you": {"parts": [{"id": "tail", "kind": "tail", "motion": "bends"}], "rigid": old["rigid"]}})
    assert new["parts"][0]["motion"] == "bends" and new["rigid"] == [] and R.plan(new).rigid == []
    # your "must not bend" click beats a lower source's Bends, and the card row says so
    b = R.merge({"you": {"rigid": ["tail"]},
                 "measured": {"parts": [{"id": "tail", "kind": "tail", "motion": "bends", "sure": 0.9}]}})
    row = b["parts"][0]
    assert row["motion"] == "stiff" and "you said it must not bend" in row["why"] and b["rigid"] == ["tail"]
    assert R.plan(b).rigid == [{"part": "tail", "owner_hint": None}] and not R.plan(b).chains
    # nobody chose how the tail moves: any stiff list does
    b = R.merge({"measured": {"parts": [{"id": "tail", "kind": "tail"}]}, "ai": {"rigid": ["tail"]}})
    assert b["parts"][0]["motion"] == "stiff"
    # an id that is no part is a clicked region; the plan stiffens only regions from the list
    b = R.merge({"you": {"rigid": ["patch"], "parts": [{"id": "ear_l", "kind": "ear"}]}})
    assert b["rigid"] == ["patch"]
    p = R.plan(dict(b, rigid=b["rigid"] + ["ear_l"]))           # a stale list naming a part
    assert p.rigid == [{"part": "patch", "owner_hint": None}] and _chains(p, "part") == [("ear_l",)]


def test_cloth_made_stiff_stays_stiff_in_the_plan():
    # a cape you made stiff: one stiff part, on the brief's stiff list and the plan's
    b = R.merge({"you": {"parts": [{"id": "cape", "kind": "cape", "motion": "stiff"}]}})
    assert b["rigid"] == ["cape"] and b["cloth"] == []
    p = R.plan(b)
    assert p.rigid == [{"part": "cape", "owner_hint": None}] and not p.chains and not p.cloth_masks
    # your stiff list beats the shape's swinging cloth row: stiff, and no chains
    cape = {"part": "cape", "kind": "cape", "motion": "swings", "width": 0.9, "length": 0.8}
    b = R.merge({"you": {"rigid": ["cape"]}, "measured": {"cloth": [dict(cape, sure=0.9)]}})
    assert [(q["id"], q["kind"], q["motion"]) for q in b["parts"]] == [("cape", "cape", "stiff")]
    assert b["cloth"] == [] and b["rigid"] == ["cape"]
    p = R.plan(b)
    assert [r["part"] for r in p.rigid] == ["cape"] and not p.chains
    # within one source the cloth row says more than the stiff list: it swings, nothing stiff
    b = R.merge({"you": {"rigid": ["cape"], "cloth": [cape]}})
    p = R.plan(b)
    assert b["rigid"] == [] and p.rigid == [] and {c["limb"] for c in p.chains} == {"spline_ik"}
    # a brief from elsewhere with both a stiff cape part and a swinging cape row: stiff only
    p = R.plan({"parts": [{"id": "cape", "kind": "cape", "motion": "stiff"}], "cloth": [cape]})
    assert [r["part"] for r in p.rigid] == ["cape"] and not p.chains


def test_a_part_sits_on_the_side_its_descriptor_says():
    # Step 4's part map names parts with no side in the name: the descriptor's side counts
    ears = [{"id": f"part_{i}", "kind": "ear", "sure": 0.9,
             "desc": _d("sheet", host="head", side=s, reach=0.5)} for i, s in ((3, "l"), (4, "r"))]
    b = R.merge({"you": {"body_plan": "upright_animal"}, "measured": {"parts": ears}})
    assert [(q["id"], q["side"]) for q in b["parts"]] == [("part_3", "l"), ("part_4", "r")]
    p = R.plan(b)
    assert _chains(p, "part", "limb", "side") == [("part_3", "ears", "l"), ("part_4", "ears", "r")]
    assert p.remove_limbs == []
    # one side reader for both modules: its own side, then its descriptor's, then its name; c = x
    for q, want in (({"id": "extra_l", "side": "c"}, "x"), ({"id": "extra_l", "desc": {"side": "c"}}, "x"),
                    ({"id": "t", "desc": {"side": "r"}}, "r"), ({"id": "horn_l2"}, "l"), ({"id": "tail"}, "x"),
                    ({"id": "fin_r", "side": "left"}, "r")):
        assert BP.part_side(q) == want and R.merge({"you": {"parts": [q]}})["parts"][0]["side"] == want, q
        assert BP._side(q) == ("c" if want == "x" else want)


def test_a_part_listed_twice_by_one_source_takes_nothing_from_the_dropped_entry():
    two = [{"id": "tail", "kind": "tail", "sure": 0.9}, {"id": "tail", "kind": "tentacle", "sure": 0.7,
                                                         "motion": "stiff", "app": "x"}]
    for order in (two, list(reversed(two))):
        b = R.merge({"measured": {"parts": order}})
        q = b["parts"][0]
        assert (q["kind"], q["motion"], q["found"], q.get("app")) == ("tail", "bends", False, None)
        assert R.plan(b).rigid == []


def test_every_kind_spec_5_5_names_is_a_card_kind():
    for raw, kind, motion in (("bell", "hanging", "swings"), ("pouch", "hanging", "swings"),
                              ("earring", "hanging", "swings"), ("hoof", "hoof", "stiff"), ("claw", "claw", "stiff"),
                              ("armour_plate", "plate", "stiff"), ("extra_arm", "arm", "bends"),
                              ("hair_tuft", "hair", "stiff"), ("snout", "muzzle", "head")):
        q = R.merge({"measured": {"parts": [{"id": "p", "kind": raw, "sure": 0.9}]}})["parts"][0]
        assert (q["kind"], q["motion"]) == (kind, motion), raw
        assert R.KIND_WORDS[kind] != "Other"
    # a swinging piece gets 1-2 bones from its length over its thickness
    for length, want in ((0.05, 1), (0.1, 2)):
        p = R.plan(R.merge({"you": {"parts": [{"id": "bell", "kind": "bell", "length": length, "thickness": 0.05}]}}))
        assert _chains(p, "part", "limb", "bones") == [("bell", "tail_dupli", want)]


def test_a_muzzle_is_part_of_the_head():
    apps = bull_apps() + [{"name": "snout", "kind": "snout", "chain": [(0, -0.2, 0.8), (0, -0.3, 0.78)],
                           "length": 0.1, "thickness": 0.12, "width": 0.14}]
    b = R.merge({"you": {"body_plan": "upright_animal", "hands": "hooves", "feet": "hooves", "face": "jaw"},
                 "measured": {"parts": R.parts_from_apps(apps), "measured": {"mouth_open": True}}})
    snout = next(q for q in b["parts"] if q["id"] == "snout")
    assert (snout["kind"], snout["motion"]) == ("muzzle", "head")
    assert b["rigid"] == ["horn_l", "horn_r", "hooves"]                       # as spec 4.1's bull
    assert R.summary_words(b) == "Animal on two legs · hooves · 2 horns · 2 ears · tail · no props"
    p = R.plan(b, apps, bull_joints())
    assert p.face == "jaw" and "snout" not in [r["part"] for r in p.rigid] + [c["part"] for c in p.chains]
    # you can still make it stiff; "part of the head" is offered only for parts on the head
    b = R.merge({"you": {"parts": [{"id": "snout", "kind": "muzzle", "motion": "stiff"}]}})
    assert b["rigid"] == ["snout"] and R.plan(b).rigid == [{"part": "snout", "owner_hint": "head"}]
    assert "head" in dict(R.motions_for({"kind": "muzzle"})) and "head" not in dict(R.motions_for({"kind": "tail"}))
    b = R.merge({"you": {"parts": [{"id": "tail", "kind": "tail", "motion": "head"}]}})
    assert b["parts"][0]["motion"] == "bends"


def test_a_part_on_one_side_never_adds_a_pair_of_arms():
    apps = _extras(("extra_l", 0.2, 1.1), ("extra_r", -0.2, 1.1), ("extra_l2", 0.25, 1.3))     # + a shoulder cannon
    b = R.merge({"you": {"body_plan": "multi_arm"}, "measured": {"parts": R.parts_from_apps(apps)}})
    assert b["fields"]["arm_pairs"]["value"] == 2
    cannon = next(q for q in b["parts"] if q["id"] == "extra_l2")
    assert (cannon["kind"], cannon["motion"], cannon["state"]) == ("other", "stiff", "yellow")
    assert "no twin on the other side" in cannon["why"]
    p = R.plan(b, apps)
    assert [(c["part"], c["row"], c["found"]) for c in p.chains if c["kind"] == "arm"] == \
        [("extra_l", 2, True), ("extra_r", 2, True)]
    assert [r["part"] for r in p.rigid] == ["extra_l2"]


def test_the_rigs_own_limbs_are_not_extra_parts():
    # the whole part map of a four-armed body: the pair at the shoulders is the rig's own whatever
    # it is called, the lower pair the extra one, and the legs are never stiff parts
    names = {"high": "arm_l2", "mid": "arm_l"}                # names that sort the wrong way round
    full = ([{"id": names[z].replace("_l", f"_{s}"), "side": s, "found": True, "desc": _d("tube", face="side", zone=z)}
             for z in ("high", "mid") for s in "lr"]
            + [{"id": f"leg_{s}", "side": s, "found": True, "desc": _d("tube", face="down", zone="low", ground=True)}
               for s in "lr"])
    b = R.merge({"measured": {"body_plan": BP.pick(full), "parts": full}})
    assert R.value(b, "body_plan") == "multi_arm" and R.value(b, "arm_pairs") == 2
    assert [q["id"] for q in b["parts"]] == ["arm_l", "arm_r"] and b["rigid"] == []
    assert [x["id"] for x in b["limbs"]] == ["arm_l2", "arm_r2", "leg_l", "leg_r"]
    p = R.plan(b)
    assert [(c["part"], c["row"]) for c in p.chains] == [("arm_l", 2), ("arm_r", 2)] and p.rigid == []
    # the same map in any order gives the same brief
    assert R.merge({"measured": {"body_plan": BP.pick(full), "parts": list(reversed(full))}}) == b
    # a list of extra parts (no legs in it) keeps every part; a part called an extra arm is never one
    extras = [q for q in full if q["id"].startswith("arm_l") or q["id"].startswith("arm_r")]
    b = R.merge({"you": {"body_plan": "multi_arm", "arm_pairs": 3}, "measured": {"parts": extras}})
    assert b["limbs"] == [] and len(b["parts"]) == 4
    named = [dict(q, kind="arm") for q in full if "arm" in q["id"]] + full[4:]
    assert [x["role"] for x in R.merge({"measured": {"parts": named}})["limbs"]] == ["leg", "leg"]


def test_arms_on_a_rig_that_has_none_are_added_not_copied():
    arms = [{"id": "arm_l", "kind": "arm"}, {"id": "arm_r", "kind": "arm"}]
    for plan_name, parent in (("serpent", "spine_02"), ("quadruped", "spine_02"), ("custom", "root")):
        p = R.plan(R.merge({"you": {"body_plan": plan_name, "parts": arms}}))
        assert _chains(p, "part", "limb", "add", "parent_hint") == \
            [("arm_l", "arm", "arm.l", parent), ("arm_r", "arm", "arm.r", parent)], plan_name
        assert any("rig has none" in n for n in p.notes)
    # a second arm on the same side copies the one just added; on the human rig every one is a copy
    p = R.plan(R.merge({"you": {"body_plan": "quadruped", "parts": arms + [{"id": "arm_l2", "kind": "arm"}]}}))
    assert _chains(p, "part", "limb") == [("arm_l", "arm"), ("arm_r", "arm"), ("arm_l2", "arm_dupli")]
    p = R.plan(R.merge({"you": {"body_plan": "person", "parts": [{"id": "arm_l2", "kind": "arm"}]}}))
    assert _chains(p, "limb") == [("arm_dupli",)]
    # a naga's arms from its part map: serpent counts them, and they hang from the top spine bone
    naga = _limb_pair("arm", "side", "high") + [{"id": "snake", "side": "c",
                                                 "desc": _d("tube", sym="off-centre", face="down", ground=True)}]
    b = R.merge({"measured": {"body_plan": BP.pick(naga), "parts": naga,
                              "measured": {"trunk_len": 3.0, "trunk_thick": 0.2}}})
    assert R.value(b, "body_plan") == "serpent" and R.value(b, "arm_pairs") == 1
    p = R.plan(b)
    top = f"spine_{p.counts['spine']:02d}"
    assert [(c["part"], c["limb"], c["parent_hint"]) for c in p.chains if c["kind"] == "arm"] == \
        [("arm_l", "arm", top), ("arm_r", "arm", top)]
    # wings may be arm copies only where the rig has an arm to copy
    wings = [{"id": "wing_l", "kind": "wing"}, {"id": "wing_r", "kind": "wing"}]
    p = R.plan(R.merge({"you": {"body_plan": "quadruped", "parts": wings}}), probe={"wings_ok": True})
    assert {c["limb"] for c in p.chains if c["kind"] == "wing"} == {"tail_dupli"}
    assert any("no arms to copy" in n for n in p.notes)
    p = R.plan(R.merge({"you": {"body_plan": "person", "parts": wings}}), probe={"wings_ok": True})
    assert {c["limb"] for c in p.chains} == {"arm_dupli"} and all(c["options"]["arm_wings"] for c in p.chains)


def test_props_go_on_bones_the_rig_has():
    props = [{"part": "sword", "role": "hand_r"}, {"part": "band", "role": "wrist_l"}, {"part": "hat", "role": "head"},
             {"part": "anklet", "role": "ankle_r"}]
    owners = {}
    for plan_name in ("person", "quadruped", "serpent", "custom"):
        b = R.merge({"you": {"body_plan": plan_name, "props": props}})
        p = R.plan(b)
        owners[plan_name] = {s["prop"]: s["owner"] for s in p.sockets}
        yellow = sorted(pr["part"] for pr in b["props"] if pr["state"] == "yellow")
        noted = sorted(n.split(":")[0] for n in p.notes if n.split(":")[0] in {"sword", "band", "hat", "anklet"})
        assert yellow == noted, plan_name                 # the card row and the plan say the same
    assert owners["person"] == {"sword": "hand.r", "band": "forearm.l", "hat": "head.x", "anklet": "leg.r"}
    assert owners["quadruped"] == {"sword": "foot_dupli_001.r", "band": "leg_dupli_001.l", "hat": "head.x",
                                   "anklet": "leg.r"}
    assert owners["serpent"] == {"sword": "spine_02.x", "band": "spine_02.x", "hat": "head.x", "anklet": "spine_02.x"}
    assert owners["custom"] == {"sword": "root", "band": "root", "hat": "root", "anklet": "root"}
    b = R.merge({"you": {"body_plan": "custom", "props": props[:1]}})
    assert "no right hand on this body: it follows the whole body" in b["props"][0]["why"]
    # a naga with arms holds its sword in its hand
    b = R.merge({"you": {"body_plan": "serpent", "props": props[:1],
                         "parts": [{"id": "arm_l", "kind": "arm"}, {"id": "arm_r", "kind": "arm"}]}})
    assert b["props"][0]["state"] == "ok" and R.plan(b).sockets[0]["owner"] == "hand.r"


def test_swinging_tails_and_ears_keep_the_rigs_own_limbs():
    for plan_name, add in (("quadruped", None), ("person", "tail")):
        b = R.merge({"you": {"body_plan": plan_name, "parts": [{"id": "tail", "kind": "tail", "motion": "swings"},
                                                               {"id": "ear_l", "kind": "ear"},
                                                               {"id": "ear_r", "kind": "ear"}]}})
        p = R.plan(b)
        tail = [c for c in p.chains if c["kind"] == "tail"]
        assert [(c["limb"], c["add"], c["options"]["tail_name"]) for c in tail] == [("tail", add, "tail")]
        assert 1 <= tail[0]["bones"] <= 2 and p.counts["tail"] == tail[0]["bones"] and p.remove_limbs == []
    b = R.merge({"you": {"body_plan": "quadruped", "parts": [{"id": "tail", "kind": "tail"},
                                                             {"id": "ear_l", "kind": "ear", "motion": "swings"},
                                                             {"id": "ear_r", "kind": "ear", "motion": "swings"}]}})
    p = R.plan(b)
    ears = [c for c in p.chains if c["kind"] == "ear"]
    assert [(c["limb"], c["add"]) for c in ears] == [("ears", None), ("ears", None)] and p.remove_limbs == []
    assert 1 <= p.counts["ear"] <= 2 and {c["options"]["ear_count"] for c in ears} == {p.counts["ear"]}
    # a bending tail takes the tail limb before a swinging one
    b = R.merge({"you": {"parts": [{"id": "tail", "kind": "tail", "motion": "swings"},
                                   {"id": "tail2", "kind": "tail"}]}})
    assert _chains(R.plan(b), "part", "limb") == [("tail", "tail_dupli"), ("tail2", "tail")]


def test_pairs_of_arms_and_legs_rows_mean_something():
    b = R.merge({"you": {"body_plan": "person", "arm_pairs": 2}})
    row = b["fields"]["arm_pairs"]
    assert row["state"] == "yellow" and "pick More than two arms" in row["why"]
    p = R.plan(b)
    assert not p.chains and any("Person has one pair of arms" in n for n in p.notes)
    for n in (0, 1):
        b = R.merge({"you": {"body_plan": "multi_arm", "arm_pairs": n}})
        assert b["fields"]["arm_pairs"]["state"] == "yellow"
        p = R.plan(b)
        assert [c["part"] for c in p.chains] == ["arm_l2", "arm_r2"] and any("one extra pair" in x for x in p.notes)
    b = R.merge({"you": {"body_plan": "quadruped", "leg_pairs": 1}})
    assert b["fields"]["leg_pairs"]["state"] == "yellow" and "two pairs of legs" in b["fields"]["leg_pairs"]["why"]
    # the defaults always fit; 'Something else' takes any number of legs; four legs take arms
    for plan_name in BP.ORDER:
        f = R.merge({"you": {"body_plan": plan_name}})["fields"]
        assert R.limb_row_problems(plan_name, f["arm_pairs"]["value"], f["leg_pairs"]["value"]) == {}
        assert "has" not in f["arm_pairs"]["why"] + f["leg_pairs"]["why"]
    assert R.merge({"you": {"body_plan": "custom", "leg_pairs": 3}})["fields"]["leg_pairs"]["state"] == "ok"
    p = R.plan(R.merge({"you": {"body_plan": "quadruped", "arm_pairs": 1}}))
    assert _chains(p, "part", "limb", "found") == [("arm_l", "arm", False), ("arm_r", "arm", False)]


def test_round_two_small_fixes():
    # one ears limb, one bone count: the larger of the pair; sizes on the brief part count too
    apps = [{"name": "ear_l", "kind": "ear", "length": 0.41, "width": 0.1, "thickness": 0.02},
            {"name": "ear_r", "kind": "ear", "length": 0.39, "width": 0.1, "thickness": 0.02}]
    p = R.plan(R.merge({"you": {"body_plan": "upright_animal"}, "measured": {"parts": R.parts_from_apps(apps)}}), apps)
    assert [c["options"]["ear_count"] for c in p.chains] == [3, 3] and p.counts["ear"] == 3
    ear = {"id": "ear_l", "kind": "ear", "length": 0.5, "width": 0.1, "thickness": 0.02}
    assert [c["bones"] for c in R.plan(R.merge({"you": {"parts": [ear]}})).chains] == [3]
    tail = {"id": "tail", "kind": "tail", "length": 1.0, "thickness": 0.04}
    assert R.plan(R.merge({"you": {"parts": [tail]}})).counts["tail"] == R.chain_bones(1.0, 0.02)
    # a part's end is asked with its start: a snake's tail tip, 2 clicks per part elsewhere
    assert "tail_end" in BP.TEMPLATES["serpent"]["critical"] and BP.ASKED_WITH["part_end"] == "part_start"
    assert BP.TEMPLATES["custom"]["critical"] == ("part_start", "part_end")
    assert set(BP.TEMPLATES["quadruped"]["critical"]) == set(BP.TEMPLATES["quadruped"]["marker_ids"])
    # the one-line summary: short words, cloth, and never longer than a few kinds
    b = R.merge({"you": {"parts": [{"id": "bell", "kind": "hanging"}, {"id": "thing", "kind": "other"}],
                         "cloth": [{"part": "cape", "kind": "cape"}]}})
    assert R.summary_words(b) == "Person · 5 fingers · hanging piece · other part · cape · no props"
    many = [{"id": f"{k}_{i}", "kind": k} for k in R.KIND_RANK for i in range(2)]
    s = R.summary_words(R.merge({"you": {"parts": many}}))
    assert len(s) < 100 and s.endswith("more · no props")
    assert "hoof" not in R.summary_words(R.merge({"you": {"hands": "hooves", "parts": [{"id": "h", "kind": "hoof"}]}}))
    # answers of the wrong type are listed, never a crash; counts are whole numbers
    b = R.merge({"you": {"parts": [{"id": "tail", "kind": "tail", "motion": ["bends"]}],
                         "props": [{"part": "s", "role": ["hand_r"]}], "rigid": "tail"}})
    assert b["parts"][0]["motion"] == "bends" and b["props"][0]["role"] == "bends" and b["rigid"] == []
    assert sorted(k for i in b["ignored"] for k in i if k in ("motion", "role")) == ["motion", "role"]
    for bad in (4.9, True, "4.5"):
        assert R.merge({"you": {"fingers": bad}})["fields"]["fingers"]["src"] == "default", bad
    assert R.merge({"you": {"fingers": 4.0}})["fields"]["fingers"]["value"] == 4
    # 'Both': loose pieces with no skin contact follow one bone; the body binds as usual
    p = R.plan(R.merge({"you": {"moves_like": "both"}}))
    assert p.loose_rigid and not p.rigid_pieces and p.bind_engine == "HEAT_MAP"
