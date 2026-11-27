"""What kinds of body Forge can rig, and how each kind is rigged (Step 8, spec 5.4 and Appendix A).

The director picks the body plan on the Step 8 card ("What it is"). Each plan is a template:
which Auto-Rig Pro rig it starts from, how the joints are found, which export it gets by
default, which points can become questions, the bone-length ratios a check accepts, and the
extra parts such a body usually has.

match(parts) scores every template against the parts Forge measured (Step 4's part map: every
piece that grows out of the trunk, arms and legs included, each with a shape descriptor whose
words DESC_KEYS defines). Two tube twins that reach the ground from the trunk's underside are a
pair of legs; two tube twins that leave its sides without reaching the ground are a pair of
arms; and so on. The best template pre-fills "What it is", sure in proportion to how clearly it
beats the next one. own_limbs(parts, plan) picks out of such a map the limbs the starting rig
already has (its legs, a two-legged body's arms at the shoulders), so the brief's extra parts
never hold them.

Plain Python: no Blender, no numpy. Every rule here is a count or a ratio, never a size.
"""

from __future__ import annotations

import math
import re

# lead's choice: Step 8 asks at most 6 questions; Step 4's questions count inside them
MAX_QUESTIONS = 6
STEP4_QUESTIONS = 2

# the card's order of "What it is" (spec 5.1)
ORDER = ("person", "upright_animal", "quadruped", "bird", "serpent", "multi_arm", "custom")
HUMANOID_TEMPLATES = ("person", "upright_animal", "multi_arm")

# ----------------------------------------------------------------------------- ratio ranges

# bone-length ratios the RATIO check accepts, per proportions class (spec 5.4)
RATIO_WORDS = {"upperarm_forearm": "upper arm / forearm", "thigh_shin": "thigh / shin",
               "head_H": "head height / height", "neck_head": "neck length / head height"}
BIPED_RATIOS = {
    "realistic": {"upperarm_forearm": (0.95, 1.35), "thigh_shin": (0.9, 1.3),
                  "head_H": (0.11, 0.16), "neck_head": (0.2, 0.7)},
    "cartoon": {"upperarm_forearm": (0.7, 1.6), "thigh_shin": (0.7, 1.6),
                "head_H": (0.15, 0.35), "neck_head": (0.0, 0.7)},
    "chibi": {"upperarm_forearm": (0.6, 1.8), "thigh_shin": (0.6, 1.8),
              "head_H": (0.3, 0.55), "neck_head": (0.0, 0.5)},
}

# ----------------------------------------------------------------------------- joints each plan needs

# the joints a two-legged body must have before it can be built (the same list as arp_rig.REQUIRED)
BIPED_REQUIRED = ("pelvis", "neck", "head", "upperarm_l", "lowerarm_l", "hand_l", "upperarm_r", "lowerarm_r",
                  "hand_r", "thigh_l", "calf_l", "foot_l", "thigh_r", "calf_r", "foot_r")
# Four legs: the back legs keep the two-legged names. The front legs are Auto-Rig Pro leg copies
# (thigh_ref_dupli_001.l), so their joints get a "front_" prefix. WP13/WP14 fill them.
QUADRUPED_REQUIRED = ("pelvis", "neck", "head",
                      "thigh_l", "calf_l", "foot_l", "thigh_r", "calf_r", "foot_r",
                      "front_thigh_l", "front_calf_l", "front_foot_l",
                      "front_thigh_r", "front_calf_r", "front_foot_r")

# ----------------------------------------------------------------------------- markers (Appendix A)


def _m(mid, words, view, depth, pair=None, along=(), sets=(), after=(), ask_if=()) -> dict:
    return {"id": mid, "words": words, "view": view, "pair": pair, "centre": pair is None, "depth": depth,
            "along": tuple(along), "sets": tuple(sets), "after": tuple(after), "ask_if": tuple(ask_if)}


# Points the director can be asked to click. A pair is asked once, on the character's LEFT; the
# right follows by mirroring. "depth" is how far into the body the point sits along the view,
# measured from the front entry (0 = on the front skin, 1 = on the back skin). "after" lists the
# points it is measured from, so they are asked first. "ask_if" names the reasons that ask it.
MARKERS = {
    "biped": (
        _m("chin", "the CHIN (bottom of the jaw)", "auto", 0.15, along=("neck_base", "head_top"),
           sets=("_chin", "chin keys", "head pivot"), ask_if=("SKULL_IS_NECK", "CHIN_RULE", "face = jaw", "RATIO")),
        _m("skull_base", "where the head turns on the neck (back of the head)", "side", 0.55,
           sets=("_skull_base",), after=("chin",), ask_if=("SKULL_IS_NECK",)),
        _m("neck_base", "where the neck meets the shoulders", "front", 0.55,
           sets=("neck head",), after=("chin", "skull_base"), ask_if=("NO_NECK",)),
        _m("head_top", "the top of the head (not the horns)", "front", 0.5,
           sets=("head tail", "top"), after=("neck_base",), ask_if=("a part on the centre line raises the head top",)),
        _m("shoulder_l", "the LEFT shoulder (where the arm turns)", "front", 0.6, pair="shoulder_r",
           along=("clavicle base", "elbow_l"), sets=("upper arm head", "clavicle tail"), after=("neck_base",),
           ask_if=("SHOULDER_NO_CREASE", "ONE_LOOP", "RATIO")),
        _m("wrist_l", "where the LEFT hand (or hoof) starts", "front", 0.5, pair="wrist_r",
           along=("elbow_l", "hand_tip_l"), sets=("forearm tail", "hand head"), after=("shoulder_l",),
           ask_if=("WRIST_FALLBACK",)),
        _m("elbow_l", "the LEFT elbow (the bend)", "front", 0.7, pair="elbow_r",
           along=("shoulder_l", "wrist_l"), sets=("upper arm tail", "forearm head"), after=("shoulder_l", "wrist_l"),
           ask_if=("ELBOW_RULE", "HINGE_BACKWARD", "motion check")),
        _m("hand_tip_l", "the tip of the LEFT hand", "front", 0.5, pair="hand_tip_r",
           sets=("hand tail", "finger tips"), after=("wrist_l",), ask_if=("a fused or held prop extends the hand",)),
        _m("wing_tip_l", "the tip of the LEFT wing", "front", 0.5, pair="wing_tip_r",
           sets=("hand tail",), after=("wrist_l",), ask_if=("bird",)),
        _m("groin", "the top of the legs, between them", "front", 0.5,
           sets=("hips", "pelvis", "thigh heads"), ask_if=("HIP_NO_CREASE", "NO_CROTCH", "CROTCH_CAPPED")),
        _m("hip_l", "where the LEFT leg joins the body", "front", 0.5, pair="hip_r",
           along=("groin", "knee_l"), sets=("thigh head",), after=("groin",), ask_if=("MIRROR", "CENTRED")),
        _m("ankle_l", "where the LEFT foot (or hoof) starts", "front", 0.5, pair="ankle_r",
           along=("knee_l", "toe_l"), sets=("shin tail", "foot head"), after=("hip_l",), ask_if=("ANKLE_RULE",)),
        _m("knee_l", "the LEFT knee", "side", 0.25, pair="knee_r",
           along=("hip_l", "ankle_l"), sets=("thigh tail", "shin head"), after=("hip_l", "ankle_l"),
           ask_if=("KNEE_RULE", "HINGE_BACKWARD", "motion check")),
        _m("hock_l", "the back knee of the LEFT leg (heel raised)", "side", 0.7, pair="hock_r",
           along=("knee_l", "ankle_l"), sets=("ankle at the hock, or the extra leg joint",), after=("knee_l",),
           ask_if=("feet = heel raised",)),
        _m("toe_l", "the tip of the LEFT foot", "side", 0.5, pair="toe_r",
           sets=("toe tip", "ball"), after=("ankle_l",), ask_if=("NO_FEET",)),
        _m("spine_bend", "the middle of the back", "side", 0.65, along=("pelvis", "neck"),
           sets=("_spine_pts",), after=("groin", "neck_base"), ask_if=("a hump or a sway-back",)),
        _m("tail_start", "where the tail starts", "side", "0.5 + push",
           sets=("part:tail",), ask_if=("PARTS_MATCH", "TAIL_ROOT")),
        _m("tail_end", "the end of the tail", "side", 0.5, sets=("part:tail",), after=("tail_start",)),
        _m("ear_root_l", "where the LEFT ear grows from the head", "front", 0.5, pair="ear_root_r",
           sets=("part:ear_l",), ask_if=("PARTS_MATCH", "LABEL_MARGIN")),
        _m("wing_root_l", "where the LEFT wing grows from the body", "auto", 0.5, pair="wing_root_r",
           sets=("part:wing_l",), ask_if=("PARTS_MATCH", "LABEL_MARGIN")),
        _m("part_start", "where this part starts", "auto", "entry",
           sets=("part:<id>",), ask_if=("PARTS_MATCH", "add a part Forge missed")),
        _m("part_end", "the end of this part", "auto", "entry", sets=("part:<id>",), after=("part_start",)),
        _m("grip", "where the hand holds it", "front", "prop section centre",
           sets=("socket head",), ask_if=("PROP_ROLE", "held prop")),
    ),
    # four legs, every point in the side view (WP13 guided mode)
    "quadruped": (
        _m("chin", "the CHIN (bottom of the jaw)", "side", 0.5, sets=("_chin", "chin keys", "head pivot"),
           ask_if=("SKULL_IS_NECK", "CHIN_RULE")),
        _m("skull_base", "where the head turns on the neck (back of the head)", "side", 0.55,
           sets=("_skull_base",), after=("chin",), ask_if=("SKULL_IS_NECK",)),
        _m("withers_l", "the top of the LEFT front leg, at the shoulder", "side", 0.5, pair="withers_r",
           sets=("front leg head",), after=("skull_base",), ask_if=("guided",)),
        _m("front_wrist_l", "the wrist of the LEFT front leg", "side", 0.5, pair="front_wrist_r",
           sets=("front foot head",), after=("withers_l",), ask_if=("guided", "WRIST_FALLBACK")),
        _m("front_elbow_l", "the elbow of the LEFT front leg", "side", 0.5, pair="front_elbow_r",
           along=("withers_l", "front_wrist_l"), sets=("front leg middle",), after=("withers_l", "front_wrist_l"),
           ask_if=("guided", "HINGE_BACKWARD")),
        _m("front_tip_l", "the tip of the LEFT front hoof or paw", "side", 0.5, pair="front_tip_r",
           sets=("front toe tip",), after=("front_wrist_l",), ask_if=("guided",)),
        _m("hip_l", "where the LEFT back leg joins the body", "side", 0.5, pair="hip_r",
           sets=("thigh head",), ask_if=("guided",)),
        _m("hock_l", "the back-pointing joint of the LEFT back leg", "side", 0.5, pair="hock_r",
           sets=("back foot head",), after=("hip_l",), ask_if=("guided", "ANKLE_RULE")),
        _m("stifle_l", "the knee of the LEFT back leg, near the belly", "side", 0.5, pair="stifle_r",
           along=("hip_l", "hock_l"), sets=("thigh tail",), after=("hip_l", "hock_l"),
           ask_if=("guided", "KNEE_RULE", "HINGE_BACKWARD")),
        _m("hind_tip_l", "the tip of the LEFT back hoof or paw", "side", 0.5, pair="hind_tip_r",
           sets=("back toe tip",), after=("hock_l",), ask_if=("guided",)),
        _m("tail_start", "where the tail starts", "side", "0.5 + push", sets=("part:tail",),
           ask_if=("PARTS_MATCH", "TAIL_ROOT")),
        _m("tail_end", "the end of the tail", "side", 0.5, sets=("part:tail",), after=("tail_start",)),
        _m("ear_root_l", "where the LEFT ear grows from the head", "side", 0.5, pair="ear_root_r",
           sets=("part:ear_l",), ask_if=("PARTS_MATCH", "LABEL_MARGIN")),
        _m("part_start", "where this part starts", "auto", "entry",
           sets=("part:<id>",), ask_if=("PARTS_MATCH", "add a part Forge missed")),
        _m("part_end", "the end of this part", "auto", "entry", sets=("part:<id>",), after=("part_start",)),
    ),
}

# Question order (spec 7.3): facing; chin, skull base, neck base; shoulders, wrists, elbows;
# groin, hips, ankles, knees and hocks; the back; extra parts; props.
QUESTION_ORDER = {
    "biped": ("facing", "chin", "skull_base", "neck_base", "head_top", "shoulder", "wrist", "elbow", "hand_tip",
              "wing_tip", "groin", "hip", "ankle", "knee", "hock", "toe", "spine_bend", "tail_start", "tail_end",
              "ear_root", "wing_root", "part_start", "part_end", "grip"),
    "quadruped": ("facing", "chin", "skull_base", "withers", "front_wrist", "front_elbow", "front_tip", "hip",
                  "hock", "stifle", "hind_tip", "tail_start", "tail_end", "ear_root", "part_start", "part_end"),
}

# Only these points can become click questions (spec 7.2). Everything else (clavicle, spine
# middles, finger middles, heel) shows as a dot only. A part is two clicks, its start and its end
# (spec 12), so the end points are asked too, always together with their start (ASKED_WITH).
CRITICAL = ("chin", "skull_base", "neck_base", "groin", "shoulder", "elbow", "wrist", "hip", "knee", "hock",
            "ankle", "tail_start", "tail_end", "ear_root", "wing_root", "part_start", "part_end", "grip",
            "withers", "front_elbow", "front_wrist", "stifle")
ASKED_WITH = {"tail_end": "tail_start", "part_end": "part_start"}
# a mark id can name what it belongs to: 'grip:<prop>' is that prop's grip point, 'part:<id>' that
# part's start and end (spec 4.3)
MARK_KINDS = {"grip": "grip", "part": "part_start"}
# only the arm points of the two-legged set come once per extra arm pair ('shoulder_l_2')
ARM_ROW_STEMS = ("shoulder", "elbow", "wrist", "hand_tip")

_ORDINALS = ("", "", "second", "third", "fourth", "fifth", "sixth")


def _split(marker_id: str) -> tuple:
    """(marker id without its arm row, arm row or None, what it belongs to or None).
    'shoulder_l_2' -> ('shoulder_l', 2, None); 'grip:sword_2' -> ('grip', None, 'sword_2'):
    nothing after a ':' is read as an arm row."""
    mid = str(marker_id)
    kind, colon, owner = mid.partition(":")
    if colon:
        return MARK_KINDS.get(kind, kind), None, owner
    head, _, tail = mid.rpartition("_")
    if head and tail.isdigit():                    # an extra arm row
        return head, int(tail), None
    return mid, None, None


def stem(marker_id: str) -> str:
    """The marker's name without its side or arm row: 'wrist_l' -> 'wrist', 'shoulder_r_2' -> 'shoulder',
    'grip:sword' -> 'grip', 'part:tail' -> 'part_start'."""
    s = _split(marker_id)[0]
    for side in ("_l", "_r"):
        if s.endswith(side):
            return s[: -len(side)]
    return s


def is_critical(marker_id: str) -> bool:
    return stem(marker_id) in CRITICAL


def marker(marker_id: str, markers: str = "biped") -> dict | None:
    """The marker's row. A right-side point is its left twin with the words turned round;
    'shoulder_l_2' is the shoulder of the second arm pair (more than two arms; arm points of the
    two-legged set only); 'grip:sword' is the grip row for that prop."""
    mid, row_n, owner = _split(marker_id)
    if row_n is not None and (markers != "biped" or stem(mid) not in ARM_ROW_STEMS):
        return None                                # no such point: only arms come in rows
    right = mid.endswith("_r")
    left_id = mid[:-2] + "_l" if right else mid
    row = next((dict(m) for m in MARKERS[markers] if m["id"] == left_id), None)
    if row is None:
        return None
    if right:
        row.update(id=mid, pair=left_id, words=row["words"].replace("LEFT", "RIGHT"),
                   along=tuple(a[:-2] + "_r" if a.endswith("_l") else a for a in row["along"]),
                   after=tuple(a[:-2] + "_r" if a.endswith("_l") else a for a in row["after"]))
    if row_n is not None:
        nth = _ORDINALS[row_n] if row_n < len(_ORDINALS) else f"no. {row_n}"
        row.update(id=f"{row['id']}_{row_n}", words=f"{row['words']}, on the {nth} pair of arms",
                   after=tuple(f"{a}_{row_n}" if a.endswith(("_l", "_r")) else a for a in row["after"]))
    if owner is not None:
        row.update(id=str(marker_id), owner=owner)
    return row


def order_key(marker_id: str, markers: str = "biped") -> tuple:
    """Sort key for the question list: the dependency order, then the arm row, then the name."""
    order = QUESTION_ORDER[markers]
    s = stem(marker_id)
    row_n = _split(marker_id)[1] or 1
    return (order.index(s) if s in order else len(order), row_n, str(marker_id))


# ----------------------------------------------------------------------------- templates

def _t(**kw) -> dict:
    return kw


_BIPED_IDS = ("chin", "skull_base", "neck_base", "head_top", "shoulder_l", "wrist_l", "elbow_l", "hand_tip_l",
              "groin", "hip_l", "ankle_l", "knee_l", "toe_l", "spine_bend", "tail_start", "tail_end",
              "part_start", "part_end", "grip")
_QUAD_IDS = tuple(m["id"] for m in MARKERS["quadruped"])

# what each template expects to see in match(): ("eq", n) exactly n, ("min", n) at least n;
# "cues" says how animal-like extras (a tail, horns, a muzzle, ears that stick out) count.
# rig_limbs: the pairs of arms and legs the starting rig has of its own (a bird's wings are its
# arms). extra_arms: the card's "Pairs of arms" adds arms beyond those (more than two arms; arms
# on a four-legged, snake or other body, whose rig has none).
TEMPLATES = {
    "person": _t(
        words="Person", short="Person",
        preset="human", estimator="biped_v2", export="HUMANOID",
        markers="biped", marker_ids=_BIPED_IDS, required=BIPED_REQUIRED,
        ratio_ranges=BIPED_RATIOS, rom="biped", expected_parts={},
        defaults={"arm_pairs": 1, "leg_pairs": 1, "hands": "fingers", "feet": "flat", "stance": "t",
                  "height_to": "head_top"},
        match={"leg_pairs": ("eq", 1), "arm_pairs": ("eq", 1), "cues": "few"},
        rig_limbs={"arm_pairs": 1, "leg_pairs": 1}, extra_arms=False,
        three_bone_legs=False, add_limbs=(), notes=""),
    "upright_animal": _t(
        words="Animal standing on two legs", short="Animal on two legs",
        preset="human", estimator="biped_v2", export="HUMANOID",
        markers="biped", marker_ids=_BIPED_IDS + ("hock_l", "ear_root_l"), required=BIPED_REQUIRED,
        ratio_ranges=BIPED_RATIOS, rom="biped", expected_parts={"ear": 2, "tail": 1},
        defaults={"arm_pairs": 1, "leg_pairs": 1, "hands": "fingers", "feet": "flat", "stance": "t",
                  "height_to": "head_top"},
        match={"leg_pairs": ("eq", 1), "arm_pairs": ("eq", 1), "cues": "some"},
        rig_limbs={"arm_pairs": 1, "leg_pairs": 1}, extra_arms=False,
        three_bone_legs=False, add_limbs=(),
        notes="Exports for ready-made human animations: the legs keep two bones, the ankle sits at the "
              "hock and the foot runs from the hock to the ball. Hands and feet are often hooves."),
    "quadruped": _t(
        words="Animal on four legs", short="Animal on four legs",
        preset="dog", estimator="guided", export="UNIVERSAL",
        markers="quadruped", marker_ids=_QUAD_IDS, required=QUADRUPED_REQUIRED,
        # no measured ranges for four legs yet: the RATIO check skips them (WP13-WP14 add theirs)
        ratio_ranges={}, rom="quadruped", expected_parts={"ear": 2, "tail": 1},
        defaults={"arm_pairs": 0, "leg_pairs": 2, "hands": "none", "feet": "paws", "stance": "four",
                  "height_to": "withers"},
        match={"leg_pairs": ("eq", 2), "arm_pairs": ("eq", 0)},
        rig_limbs={"arm_pairs": 0, "leg_pairs": 2}, extra_arms=True,
        three_bone_legs=True, add_limbs=(),
        notes="The horse rig for hooves or a long neck, else the dog rig. The front legs are leg copies "
              "with three bones; there are no arms."),
    "bird": _t(
        words="Bird (wings are its arms)", short="Bird",
        # Auto-Rig Pro swaps "bird" for its own Blender 4.4 file itself; Forge always asks for "bird"
        preset="bird", estimator="guided", export="UNIVERSAL",
        markers="biped",
        marker_ids=("chin", "skull_base", "neck_base", "shoulder_l", "wrist_l", "wing_tip_l", "wing_root_l", "groin",
                    "hip_l", "ankle_l", "knee_l", "toe_l", "tail_start", "tail_end", "part_start", "part_end"),
        required=BIPED_REQUIRED, ratio_ranges={}, rom="bird", expected_parts={"beak": 1, "tail": 1},
        defaults={"arm_pairs": 1, "leg_pairs": 1, "hands": "none", "feet": "toes", "stance": "other",
                  "height_to": "head_top"},
        match={"wing_pairs": ("min", 1), "arm_pairs": ("eq", 0), "leg_pairs": ("eq", 1)},
        rig_limbs={"arm_pairs": 1, "leg_pairs": 1}, extra_arms=False,     # its wings are its arms
        three_bone_legs=False, add_limbs=(),
        notes="Only where the probe showed the bird rig does not crash this Blender; else the human rig."),
    "serpent": _t(
        words="Snake or no legs", short="Snake",
        preset="free", estimator="medial_axis", export="UNIVERSAL",
        markers="biped", marker_ids=("chin", "skull_base", "tail_end", "part_start", "part_end"),
        required=("neck", "head"), ratio_ranges={}, rom="serpent", expected_parts={},
        defaults={"arm_pairs": 0, "leg_pairs": 0, "hands": "none", "feet": "none", "stance": "other",
                  "height_to": "head_top"},
        match={"leg_pairs": ("eq", 0), "long_body": ("min", 1)},
        rig_limbs={"arm_pairs": 0, "leg_pairs": 0}, extra_arms=True,
        three_bone_legs=False, add_limbs=("spine", "head"),
        notes="A spine along the body and a head with at least one neck bone; a long body or tail bends "
              "along a smooth curve."),
    "multi_arm": _t(
        words="More than two arms", short="More than two arms",
        preset="human", estimator="biped_v2", export="HUMANOID",
        markers="biped", marker_ids=_BIPED_IDS, required=BIPED_REQUIRED,
        ratio_ranges=BIPED_RATIOS, rom="biped", expected_parts={"arm": 2},
        defaults={"arm_pairs": 2, "leg_pairs": 1, "hands": "fingers", "feet": "flat", "stance": "t",
                  "height_to": "head_top"},
        match={"arm_pairs": ("min", 2), "leg_pairs": ("eq", 1)},
        rig_limbs={"arm_pairs": 1, "leg_pairs": 1}, extra_arms=True,
        three_bone_legs=False, add_limbs=(), per_extra_arm=("shoulder_l", "wrist_l"),
        notes="The human rig plus an arm copy per extra arm; each extra pair adds a shoulder and a wrist point."),
    "custom": _t(
        words="Something else (I'll point at the parts)", short="Something else",
        preset="free", estimator="guided", export="UNIVERSAL",
        markers="biped", marker_ids=("part_start", "part_end"), required=(),
        ratio_ranges={}, rom="custom", expected_parts={},
        defaults={"arm_pairs": 0, "leg_pairs": 0, "hands": "none", "feet": "none", "stance": "other",
                  "height_to": "head_top"},
        match={}, rig_limbs={"arm_pairs": 0, "leg_pairs": 0}, extra_arms=True,
        three_bone_legs=False, add_limbs=(),
        notes="One chain per part, from where it starts to its end."),
}
for _name in ORDER:
    _tm = TEMPLATES[_name]
    _tm["name"] = _name
    # guided mode asks every point of its set (spec 12: four legs, all 12 side-view points)
    _tm["critical"] = tuple(m for m in _tm["marker_ids"] if is_critical(m) or _tm["estimator"] == "guided")


# A ratio this close to a boundary counts as on it, so rounding in the sizes (a body built 100
# times as big) never moves a count across the boundary.
EPS = 1e-9
HORSE_NECK = 1.5          # a neck longer than this many times its thickness takes the horse rig


def choose_preset(name: str, hands: str = "", feet: str = "", neck_ratio=None, bird_ok=None) -> tuple:
    """(Auto-Rig Pro rig to start from, plain-words note). Four legs: the horse rig for hooves or a
    neck longer than 1.5 times its thickness, else the dog rig. A bird gets "bird" (never Auto-Rig
    Pro's own Blender 4.4 file name) only when the probe showed the bird rig working in this
    Blender (bird_ok True); when it crashed, or nobody has checked yet, the human rig instead."""
    if name == "quadruped":
        if "hooves" in (hands, feet):
            return "horse", "hooves: the horse rig"
        if neck_ratio is not None and neck_ratio > HORSE_NECK + EPS:
            return "horse", "a long neck: the horse rig"
        return "dog", "paws and a short neck: the dog rig"
    if name == "bird" and bird_ok is not True:
        if bird_ok is False:
            return "human", "the bird rig crashes this Blender: built on the human rig"
        return "human", "the bird rig is not checked on this Blender yet: built on the human rig"
    return TEMPLATES[name]["preset"], ""


# ----------------------------------------------------------------------------- the part descriptor

# Step 4's part map describes every piece that grows out of the trunk (U10-U12 measure it, WP3
# hands it to the brief as parts[].desc). This is the one place its words are defined. Every key
# is optional: a part without a descriptor counts for nothing in match(). Keys not listed here
# pass through untouched.
DESC_SHAPES = ("tube", "sheet", "blob", "shell")        # shell: a hollow sheet round the core (skirt, robe)
DESC_ATTACH = ("root", "slot", "along", "contact")      # root: grows out of its host; slot: a sheet set in a
#                                                          slit (fin, wing); along: lies on it with no root
#                                                          (pad, strap); contact: only touches it
DESC_SYM = ("matched", "add-on", "differs", "posed", "off-centre")   # how it compares with the other side
DESC_FACES = ("down", "side", "back", "up", "front")    # which way it leaves its host, in the body's frame
DESC_ZONES = ("high", "mid", "low")                     # which third of the core's height its root is in:
#                                                          high = the top third (shoulders), low = the bottom
DESC_SIDES = ("l", "r", "c", "x")                       # c and x both mean the centre line
DESC_KEYS = {
    "shape": DESC_SHAPES, "attach": DESC_ATTACH, "sym": DESC_SYM, "face": DESC_FACES, "zone": DESC_ZONES,
    "side": DESC_SIDES,
    "host": "'core', 'head', or the id of the part it grows from (spikes on a tail)",
    "ground": "True when it reaches the ground",
    "twin": "the id of its twin across the middle",
    "tips": "how many tips it has (an antler branches: 2 or more), at least 1",
    "taper": "tip radius over root radius; a cone is under 0.45",
    "reach": "how far its tip stands off its host, over the host's width",
}
CONE_TAPER = 0.45         # a tube that narrows below this share of its root radius is a cone (U12)
EAR_REACH = 0.25          # an ear that stands off the head by this share of the head's width sticks out


def clean_desc(desc) -> tuple:
    """(descriptor, [(key, value) left out]): the known keys checked against DESC_KEYS, other keys
    kept as they are. A value that is not one of a key's words, or not a sensible number, is left
    out, so a producer's mistake shows instead of quietly deciding a body plan."""
    if not isinstance(desc, dict):
        return {}, ([("desc", desc)] if desc is not None else [])
    out, bad = {}, []
    for k in sorted(desc, key=str):
        v = desc[k]
        words = DESC_KEYS.get(k)
        if isinstance(words, tuple):
            ok = v in words
        elif k == "host" or k == "twin":
            ok = isinstance(v, str) and bool(v)
        elif k == "ground":
            ok = isinstance(v, bool) or v in (0, 1)
            v = bool(v) if ok else v
        elif k == "tips":
            ok = isinstance(v, int) and not isinstance(v, bool) and v >= 1
        elif k in ("taper", "reach"):
            ok = isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v >= 0
        else:
            ok = True                              # not ours: kept as it is
        if ok:
            out[k] = v
        else:
            bad.append((k, v))
    return out, bad


# ----------------------------------------------------------------------------- match

TWIN_SYMS = ("matched", "posed", "differs")       # a part with a twin across the middle
MISS = 0.15                                       # score kept per count off by one
LONG_CORE = 6.0                                   # a trunk this many times longer than thick is a long body
CUES = ("tail", "horns", "muzzle", "ears")
# How much each animal-like extra leans a two-legged body towards 'animal'. A tail or a muzzle
# is rare on a person; horns less so (helmets, costumes); ears that stick out least (elves).
CUE_WEIGHTS = {"tail": 1.0, "muzzle": 1.0, "horns": 0.75, "ears": 0.5}


def _desc(p: dict) -> dict:
    d = p.get("desc")
    return d if isinstance(d, dict) else {}


def part_side(p: dict) -> str:
    """Which side a part is on: 'l', 'r' or 'x' (the middle). The part's own 'side' first, then
    its descriptor's ('c' and 'x' both mean the middle), then the end of its name ('horn_l',
    'ear_r2'); anything else is the middle. rig_brief reads sides with this too, so the card, the
    plan and match() always put a part on the same side."""
    for s in (p.get("side"), _desc(p).get("side")):
        if isinstance(s, str) and s in DESC_SIDES:
            return "x" if s == "c" else s
    m = re.search(r"_([lr])\d*$", str(p.get("id", "")))
    return m.group(1) if m else "x"


def _side(p: dict) -> str:
    s = part_side(p)
    return "c" if s == "x" else s


def role(p: dict) -> str:
    """What a measured part is from its descriptor alone: leg, arm, wing, tail, ground_body,
    hidden_legs (a hollow sheet reaching the ground, such as a robe), or head (any part on the
    head), or "" for anything else. A part that lies along its host or only touches it is never a
    limb."""
    d = _desc(p)
    shape, host, face = d.get("shape"), d.get("host", "core"), d.get("face")
    ground = bool(d.get("ground"))
    if d.get("attach") in ("along", "contact"):
        return ""                                 # a pad, a strap, a tail resting on the back
    if host == "head":
        return "head"
    if host not in ("core", None):
        return ""                                 # a part on a part (spikes on a tail)
    if shape == "shell" and ground:
        return "hidden_legs"
    if shape == "tube" and ground and face in ("down", None):
        return "ground_body" if _side(p) == "c" else "leg"
    if shape == "tube" and ground:                # a long body coming down behind and lying on the ground
        return "ground_body" if _side(p) == "c" else ""
    if shape == "tube" and (face == "side" or (face == "down" and d.get("zone") in ("high", "mid"))):
        return "arm"                              # out to the side, or hanging from the upper two thirds
    if shape == "sheet" and face in ("side", "back", "up") and d.get("zone", "high") == "high" \
            and d.get("sym") in TWIN_SYMS:
        return "wing"
    if shape == "tube" and face == "back":
        return "tail"
    return ""


# which root height a limb of each kind usually has, first: arms hang from the shoulders, legs
# stand on the ground
_ZONE_FIRST = {"arm": ("high", "mid", "low"), "leg": ("low", "mid", "high")}


def own_limbs(parts: list, name: str) -> list:
    """The parts that are limbs the starting rig already has, as [(id, role)] sorted by id: the
    template's legs, and on two-legged bodies with arms its first arm pair (a bird's arms are its
    wings, handled by the plan). Each side takes its parts by root height first (arms from the
    shoulders down, legs from the ground up), then by name, so 'which pair is extra' never depends
    on names alone.

    Only a whole part map holds such limbs. A map that holds the legs (or a robe reaching the
    ground, which hides them) is one; a list of extra parts never is, so nothing is taken from it.
    The caller passes only parts with no card kind: a part called "Extra arm" is never the rig's
    own arm."""
    roles = [role(p) for p in parts]
    if not any(r in ("leg", "hidden_legs") for r in roles):
        return []
    have = TEMPLATES[name]["rig_limbs"]
    out = []
    for want, n in (("leg", have["leg_pairs"]), ("arm", 0 if name == "bird" else have["arm_pairs"])):
        first = _ZONE_FIRST[want]

        def key(p):
            zone = _desc(p).get("zone")
            return (first.index(zone) if zone in first else len(first), str(p.get("id")))

        for side in ("l", "r"):
            mine = sorted((p for p, r in zip(parts, roles) if r == want and _side(p) == side), key=key)
            out += [(str(p.get("id")), want) for p in mine[:n]]
    return sorted(out)


def _pairs(items: list) -> float:
    """How many left-right pairs: explicit twins first, then lefts and rights matched in name
    order. An unmatched part on one side counts as half a pair."""
    by_id = {str(p.get("id", i)): p for i, p in enumerate(items)}
    used, pairs = set(), 0
    for pid in sorted(by_id):
        tw = by_id[pid].get("twin") or _desc(by_id[pid]).get("twin")
        if pid in used or tw is None or str(tw) not in by_id or str(tw) in used or str(tw) == pid:
            continue
        used |= {pid, str(tw)}
        pairs += 1
    rest = [pid for pid in sorted(by_id) if pid not in used]
    lefts = [pid for pid in rest if _side(by_id[pid]) == "l" and _desc(by_id[pid]).get("sym") in TWIN_SYMS]
    rights = [pid for pid in rest if _side(by_id[pid]) == "r" and _desc(by_id[pid]).get("sym") in TWIN_SYMS]
    k = min(len(lefts), len(rights))
    pairs += k
    singles = len([pid for pid in rest if _side(by_id[pid]) in ("l", "r")]) - 2 * k
    return pairs + 0.5 * singles


def _horn_like(head: list) -> bool:
    """Horns from descriptors: one or two cones on the head (taper under 0.45, or a branching
    antler), either a matched pair or one on the centre line with matched sides. Many cones are
    hair spikes; a lone cone off to one side is a ponytail or a lock of hair."""
    cones = [p for p in head if _desc(p).get("shape") == "tube"
             and (_desc(p).get("tips", 1) >= 2 or _desc(p).get("taper", 1.0) < CONE_TAPER)]
    if len(cones) == 2:
        return _pairs(cones) >= 1 and all(_desc(p).get("sym") in TWIN_SYMS for p in cones)
    if len(cones) == 1:
        return _side(cones[0]) == "c" and _desc(cones[0]).get("sym") == "matched"
    return False


def _ear_like(head: list) -> bool:
    """Ears from descriptors: a pair of sheets on the head that stand off it by at least a quarter
    of the head's width. Modelled human ears lie close to the head and do not count."""
    sheets = [p for p in head if _desc(p).get("shape") == "sheet" and _desc(p).get("reach", 0.0) >= EAR_REACH]
    return _pairs(sheets) >= 1


def features(parts: list, body: dict | None = None) -> dict:
    """Counts match() compares: leg, arm and wing pairs, long bodies, and the animal-like extras
    (a tail, horns, a muzzle, ears that stick out) with their summed weight. Parts the director
    called 'not a part' are left out. A robe or long skirt reaching the ground hides the legs: it
    counts as one pair when no legs are seen."""
    parts = [p for p in parts if p.get("motion") != "not_part"]
    by_role: dict = {}
    for p in parts:
        by_role.setdefault(role(p), []).append(p)
    kinds = [str(p.get("kind") or "") for p in parts]
    head = by_role.get("head", [])
    cues = {
        "tail": bool(by_role.get("tail")) or "tail" in kinds,
        "horns": any(k in ("horn", "antler") for k in kinds) or _horn_like(head),
        "muzzle": any(k in ("muzzle", "snout", "beak") for k in kinds)
        or any(_desc(p).get("shape") == "blob" and _desc(p).get("face") == "front" for p in head),
        "ears": "ear" in kinds or _ear_like(head),
    }
    long_core = 1 if (body or {}).get("core_aspect", 0.0) >= LONG_CORE else 0
    legs = _pairs(by_role.get("leg", []))
    if legs == 0 and by_role.get("hidden_legs"):
        legs = 1.0
    names = [c for c in CUES if cues[c]]
    return {"leg_pairs": legs, "arm_pairs": _pairs(by_role.get("arm", [])),
            "wing_pairs": _pairs(by_role.get("wing", [])),
            "long_body": len(by_role.get("ground_body", [])) + long_core,
            "cues": round(sum(CUE_WEIGHTS[c] for c in names), 6), "cue_names": names}


def _agree(rule: tuple, found: float) -> float:
    how, want = rule
    off = abs(found - want) if how == "eq" else max(0.0, want - found)
    return MISS ** off


_WHY = {"person": "two arms and two legs", "upright_animal": "two arms and two legs, with {cues}",
        "quadruped": "four feet on the ground", "bird": "wings and two legs",
        "serpent": "no legs and a long body", "multi_arm": "{arms} pairs of arms and two legs",
        "custom": "no body shape Forge knows"}


def match(parts: list, body: dict | None = None) -> list:
    """Every template scored 0..1 against the measured parts, best first:
    [{"plan", "score", "why"}].

    Each part is read from its descriptor (DESC_KEYS): shape, attach, host, face, zone, ground,
    sym, twin, and for head parts tips, taper and reach. Legs are tube twins on the core that
    reach the ground; arms are tube twins that leave its sides, or hang from its upper two thirds,
    without reaching the ground; wings are sheet twins high on the core; a tail is a tube leaving
    the back. A part attached 'along' or by 'contact' is never a limb. body: {"core_aspect": the
    trunk's length over its thickness} when known.

    A count off by one keeps MISS of the score. Animal-like extras lean a two-legged body towards
    'animal' by their weight (CUE_WEIGHTS): 'person' keeps 0.5 to the power of the summed
    weights. 'Something else' scores what the best other template leaves, halved, so it wins
    only when nothing fits. Ties keep the card's order."""
    f = features(parts, body)
    scores = {}
    for name in ORDER:
        if name == "custom":
            continue
        s = 1.0
        for feat, rule in TEMPLATES[name]["match"].items():
            if feat == "cues":
                s *= 0.5 ** f["cues"] if rule == "few" else 1.0 - 0.5 ** f["cues"]
            else:
                s *= _agree(rule, f[feat])
        scores[name] = s
    scores["custom"] = 0.5 * (1.0 - max(scores.values()))
    cue_words = _and([{"tail": "a tail", "horns": "horns", "muzzle": "a muzzle", "ears": "ears"}[c]
                      for c in f["cue_names"]]) or "nothing animal-like"
    out = [{"plan": n, "score": round(scores[n], 6),
            "why": _WHY[n].format(cues=cue_words, arms=_count_words(f["arm_pairs"]))} for n in ORDER]
    out.sort(key=lambda r: (-r["score"], ORDER.index(r["plan"])))
    return out


def pick(parts: list, body: dict | None = None) -> dict:
    """The best template as a measured card value: {"value", "sure", "why"}. Sure is how far the
    best score beats the next one, so two templates that fit equally well give sure 0."""
    ranked = match(parts, body)
    best, second = ranked[0], ranked[1]
    return {"value": best["plan"], "sure": round(max(0.0, best["score"] - second["score"]), 6),
            "why": best["why"]}


def _and(words: list) -> str:
    if len(words) <= 1:
        return "".join(words)
    return ", ".join(words[:-1]) + " and " + words[-1]


def _count_words(n: float) -> str:
    n = int(round(n))
    return {0: "no", 1: "one", 2: "two", 3: "three", 4: "four"}.get(n, str(n))
