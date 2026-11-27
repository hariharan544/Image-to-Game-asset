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
    assert R.merge({"step1": step1, "measured": weak})["fields"]["body_plan"]["state"] == "ok"
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
    p = R.plan(b, [], {"neck": ((0, 0, 1.0), (0, 0, 1.3)), "_conf": {"neck": {"r": 0.05}}})
    assert p.preset == "bird" and p.preset != "bird_44"
    assert p.counts["neck"] == 3 and p.export_type == "UNIVERSAL"
    assert not p.chains                                # the wings are the bird's arms
    # where the probe saw the bird rig crash this Blender: the human rig, still no bird_44
    p = R.plan(b, [], None, probe={"bird_ok": False})
    assert p.preset == "human" and not p.chains and p.export_type == "UNIVERSAL" and p.counts["neck"] >= 1
    assert any("crashes" in n for n in p.notes)


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
    assert p.bind_engine == "HEAT_MAP"                         # heavy, but fingers would blur under voxels
    assert p.rigid_pieces


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
        assert set(t["critical"]) <= set(t["marker_ids"]) and all(BP.is_critical(m) for m in t["critical"])
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
    words += [w for _k, w, _p, _m in R.PART_KINDS] + [p for _k, _w, p, _m in R.PART_KINDS]
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
