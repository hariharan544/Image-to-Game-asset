"""The rig brief: what the character is, as the Step 8 card "About your character" shows it
(spec 4.1 and 5.1-5.5).

Forge fills the card from several sources: the director's own answers, Step 1, Step 2's props,
the job, measurements of the mesh, Tripo, an optional AI read of the concept image, and the
body plan's defaults. merge() picks one value per row, by a fixed precedence, and marks the rows
the director should look at: yellow when Forge is unsure, red when two sources disagree.

plan() turns a brief into a RigPlan: which Auto-Rig Pro rig to start from, which limb options
change (fingers, toes, neck, spine), which limbs it adds or removes, which chains the extra parts
get, which parts stay stiff, where props attach, how the skin is bound and how the rig is
exported. Every count in it comes from ratios (a tail's length to its thickness, a neck's length
to its thickness), so the same character gives the same plan at any scale, and parts are taken
in card order, so the order of the brief's lists never changes it.

Plain Python: no Blender. (Part names are read with appendages.plain_name, so the card and
the panel word them the same way.)
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass, field

from . import body_plans as BP

# ----------------------------------------------------------------------------- sources

SOURCES = ("you", "step1", "step2", "job", "measured", "tripo", "ai", "default")
# precedence: a measurement Forge is sure of beats Tripo and the AI read; a weak one does not
RANKS = ("you", "step1", "step2", "job", "measured_strong", "tripo", "ai", "measured_weak", "default")
STRONG = 0.8          # a measurement this sure ranks above Tripo; below it a row shows yellow
AI_CAP = 0.6          # the AI read is never surer than this, so it always shows yellow until confirmed
DISAGREE = 0.5        # two sources at least this sure that differ make a red row
# how sure a bare value is when a source gives no number
BARE_SURE = {"you": 1.0, "step1": 1.0, "step2": 1.0, "job": 0.9, "measured": 0.5, "tripo": 0.7, "ai": AI_CAP,
             "default": 0.5}
# "<who> <what>" in a red row's reason
SAYS = {"you": "you said", "step1": "Step 1 says", "step2": "Step 2 says", "job": "the job says",
        "measured": "the shape says", "tripo": "Tripo says", "ai": "the image says",
        "default": "the usual choice is"}

# ----------------------------------------------------------------------------- fields (spec 5.1)


def _f(label, kind, default, sure, options=(), first=False, lo=None, hi=None, unset=None, note="") -> dict:
    return {"label": label, "type": kind, "default": default, "sure": sure, "options": tuple(options),
            "first": first, "lo": lo, "hi": hi, "unset": unset, "note": note}


FIELD_ORDER = ("body_plan", "stance", "height_m", "height_to", "hands", "fingers", "thumb", "feet", "toes",
               "arm_pairs", "leg_pairs", "build", "mass_kg", "proportions", "face", "moves_like", "symmetry",
               "export")

# Each field: card label, type, default, how sure the default is, and the options in plain words.
# "first" rows show on the card's first view; the rest sit under "More". A default the lead
# decided (height to the top of the head, the head moving as one, ...) is sure 1.0; a guess is
# sure 0.5, so it shows yellow until something better fills it.
FIELDS = {
    "body_plan": _f("What it is", "enum", "person", 0.5,
                    [(n, BP.TEMPLATES[n]["words"]) for n in BP.ORDER], first=True),
    "stance": _f("Pose now", "enum", "t", 0.5,
                 [("t", "Arms straight out (T)"), ("a", "Arms angled down (A)"), ("down", "Arms at the sides"),
                  ("four", "Standing on four legs"), ("other", "Other (sitting, crouching)")], first=True),
    "height_m": _f("Height", "float", 0.0, 1.0, first=True, lo=0.0, unset=0.0, note="m"),
    "height_to": _f("Height to", "enum", "head_top", 1.0,
                    [("head_top", "to the top of the head (not horns or ears)"), ("highest", "to the highest point"),
                     ("withers", "to the shoulder (four legs)")], first=True),
    "hands": _f("Hands", "enum", "fingers", 0.5,
                [("fingers", "Fingers"), ("mitten", "Mitten"), ("hooves", "Hooves"), ("paws", "Paws"),
                 ("claws", "Claws"), ("none", "None")], first=True),
    "fingers": _f("Fingers", "int", 5, 0.5, first=True, lo=1, hi=5),
    "thumb": _f("Thumb", "bool", True, 0.5, first=True),
    "feet": _f("Feet", "enum", "flat", 0.5,
               [("flat", "Shoes or flat feet"), ("toes", "Toes"), ("paws", "Paws"), ("hooves", "Hooves"),
                ("heel_raised", "Walks on its toes (heel raised)"), ("none", "None")], first=True),
    "toes": _f("Toes", "int", 5, 0.5, lo=1, hi=5),
    "arm_pairs": _f("Pairs of arms", "int", 1, 0.5, lo=0, hi=4),
    "leg_pairs": _f("Pairs of legs", "int", 1, 0.5, lo=0, hi=4),
    "build": _f("Build", "enum", "average", 0.5,
                [("slim", "Slim"), ("average", "Average"), ("heavy", "Heavy"), ("round", "Round")]),
    "mass_kg": _f("Weight for game physics", "float", 0.0, 1.0, lo=0.0,
                  note="(game physics only, does not move joints)"),
    # cartoon ranges are the wider ones: a guess there asks fewer needless questions
    "proportions": _f("Proportions", "enum", "cartoon", 0.5,
                      [("realistic", "Realistic"), ("cartoon", "Cartoon (big head, short legs)"),
                       ("chibi", "Chibi (head about as big as the body)")]),
    "face": _f("Face", "enum", "head_one", 1.0,
               [("head_one", "Head moves as one"), ("jaw", "Jaw opens"), ("full", "Full face")]),
    "moves_like": _f("Moves like", "enum", "living", 1.0,
                     [("living", "Living body"), ("machine", "Machine"), ("both", "Both")]),
    "symmetry": _f("Symmetric", "enum", "auto", 1.0,
                   [("auto", "Auto"), ("left", "Left side"), ("right", "Right side"), ("none", "No mirror")]),
    # lead's choice: upright animals export so ready-made human animations play on them
    "export": _f("Animations", "enum", "humanoid", 1.0,
                 [("humanoid", "Plays ready-made human animations (when the body allows)"),
                  ("creature", "Creature skeleton (plays only animations made for it)")]),
}

# ----------------------------------------------------------------------------- parts, props, cloth

# "Part of the head" (no bones of its own: the head's skin, so a jaw can still open in it) is
# offered only for parts on the head (motions_for).
MOTIONS = (("stiff", "Stiff"), ("bends", "Bends"), ("swings", "Swings"), ("not_part", "Not a part"),
           ("head", "Part of the head"))
# kind, card words, the word in the one-line summary (one, more), how it moves by default (spec
# 5.5). In body order, from the head down: the card lists the parts and the one-line summary
# counts them in this order.
PART_KINDS = (
    ("horn", "Horn", "horn", "horns", "stiff"),
    ("antler", "Antler", "antler", "antlers", "stiff"),
    ("ear", "Ear", "ear", "ears", "bends"),
    ("muzzle", "Muzzle", "muzzle", "muzzles", "head"),
    ("beak", "Beak", "beak", "beaks", "stiff"),
    ("hair", "Hair tuft", "hair tuft", "hair tufts", "stiff"),
    ("mane", "Mane", "mane", "manes", "stiff"),
    ("trunk", "Trunk", "trunk", "trunks", "bends"),
    ("arm", "Extra arm", "extra arm", "extra arms", "bends"),
    ("wing", "Wing", "wing", "wings", "bends"),
    ("claw", "Claw", "claw", "claws", "stiff"),
    ("fin", "Fin", "fin", "fins", "swings"),
    ("spike", "Spike", "spike", "spikes", "stiff"),
    ("plate", "Armour plate", "armour plate", "armour plates", "stiff"),
    ("hanging", "Hanging piece (bell, pouch, earring)", "hanging piece", "hanging pieces", "swings"),
    ("tail", "Tail", "tail", "tails", "bends"),
    ("tentacle", "Tentacle", "tentacle", "tentacles", "bends"),
    ("hoof", "Hoof", "hoof", "hooves", "stiff"),
    ("other", "Other", "other part", "other parts", "stiff"),
)
KIND_WORDS = {k: w for k, w, _o, _p, _m in PART_KINDS}
KIND_ONE = {k: o for k, _w, o, _p, _m in PART_KINDS}
KIND_PLURAL = {k: p for k, _w, _o, p, _m in PART_KINDS}
KIND_MOTION = {k: m for k, _w, _o, _p, m in PART_KINDS}
KIND_RANK = {k: i for i, (k, _w, _o, _p, _m) in enumerate(PART_KINDS)}
# the kinds appendages.find gives today, the names spec 5.5 and U12 use, and other names, as card kinds
KIND_ALIASES = {"snout": "muzzle", "head_extra": "other", "back_extra": "other", "extra": "other",
                "tuft": "hair", "hair_tuft": "hair", "antlers": "antler", "spikes": "spike",
                "pauldron": "plate", "armour": "plate", "armour_plate": "plate", "armor_plate": "plate",
                "extra_arm": "arm", "bell": "hanging", "pouch": "hanging", "earring": "hanging",
                "hooves": "hoof", "claws": "claw"}
HEAD_KINDS = ("ear", "horn", "antler", "muzzle", "beak", "hair", "trunk")
CLOTH_KINDS = ("cape", "skirt", "sash", "cloth")
CLOTH_MOTIONS = (("with_body", "Moves with the body"), ("swings", "Swings"), ("physics_later", "Game physics later"))

PROP_ROLES = (("hand_r", "Held in right hand"), ("hand_l", "Held in left hand"),
              ("both_hands", "Held in both hands"), ("head", "Worn on the head"), ("neck", "On the neck"),
              ("chest", "On the chest or back"), ("hips", "On the hips (belt)"), ("wrist_l", "On the left wrist"),
              ("wrist_r", "On the right wrist"), ("ankle_l", "On the left ankle"), ("ankle_r", "On the right ankle"),
              ("swings", "Hangs and swings"), ("bends", "Bends with the body"))
# lead's choice: a held prop comes off in the game (it gets a socket on the hand); a worn one does not
HELD = ("hand_r", "hand_l", "both_hands")
# Auto-Rig Pro's bone names (the ones arp_rig.ARP_SOCKET_BONES and the WP0 probe use)
OWNER_BONES = {"hand_r": "hand.r", "hand_l": "hand.l", "head": "head.x", "neck": "neck.x", "hips": "root.x",
               "wrist_l": "forearm.l", "wrist_r": "forearm.r", "ankle_l": "leg.l", "ankle_r": "leg.r"}
ENGINE_INFLUENCES = {"unity": 4, "unreal": 8}       # bones per vertex each engine takes (as motion_check)

# ----------------------------------------------------------------------------- small helpers


def _norm_kind(kind) -> str:
    k = str(kind or "other").lower()
    k = KIND_ALIASES.get(k, k)
    return k if k in KIND_RANK or k in CLOTH_KINDS else "other"


def part_words(pid: str, kind: str = "") -> str:
    """A part's name in plain words for the card: 'horn_l' -> 'Left horn', 'tail2' -> 'Second tail'."""
    from .appendages import plain_name
    w = plain_name(pid)
    k = _norm_kind(kind)
    if k in KIND_WORDS and k != "other" and KIND_WORDS[k].lower() not in w:
        w = f"{w} ({KIND_WORDS[k].lower()})"
    return w[:1].upper() + w[1:]


def _words(name: str, value) -> str:
    spec = FIELDS[name]
    if spec["type"] == "enum":
        return dict(spec["options"]).get(value, str(value))
    if spec["type"] == "bool":
        return "Yes" if value else "No"
    if spec["type"] == "float":
        return f"{float(value):.2f}"
    return str(value)


def _is_option(value, options) -> bool:
    """True when value is one of the (key, words) options' keys (only text can be one)."""
    return isinstance(value, str) and value in dict(options)


def _clean(name: str, value):
    """The value as the field's type, or None when it is not a valid answer for that field. A
    count must be a whole number (4.9 fingers is no answer), and yes/no is never a number."""
    spec = FIELDS[name]
    if value is None:
        return None
    try:
        if spec["type"] == "enum":
            return value if _is_option(value, spec["options"]) else None
        if spec["type"] == "bool":
            return bool(value) if isinstance(value, (bool, int, float)) and value in (0, 1) else None
        if isinstance(value, bool):
            return None                           # True is not a count or a size
        v = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(v):
        return None                               # not a number, or endless: no answer
    if spec["type"] == "int":
        if not v.is_integer():
            return None
        v = int(v)
    if (spec["lo"] is not None and v < spec["lo"]) or (spec["hi"] is not None and v > spec["hi"]):
        return None
    if spec["unset"] is not None and v == spec["unset"]:
        return None                               # "not set" is no answer
    return v


def _same(name: str, a, b) -> bool:
    if FIELDS[name]["type"] == "float":
        return abs(float(a) - float(b)) <= 0.03 * max(abs(float(a)), abs(float(b)), 1e-12)
    return a == b


def _rank(src: str, sure: float) -> int:
    if src == "measured":
        return RANKS.index("measured_strong" if sure >= STRONG else "measured_weak")
    return RANKS.index(src)


def _sure(src: str, sure) -> float:
    """How sure a source is, 0..1: its own number, else the source's usual one; the AI read is
    capped at AI_CAP."""
    try:
        s = BARE_SURE[src] if sure is None else float(sure)
    except (TypeError, ValueError):
        s = BARE_SURE[src]
    s = min(max(s, 0.0), 1.0) if s == s else BARE_SURE[src]       # (s != s: not a number)
    return min(s, AI_CAP) if src == "ai" else s


def _entry(src: str, raw) -> dict:
    """One source's answer as {value, sure, why, any_of, words}."""
    e = dict(raw) if isinstance(raw, dict) and "value" in raw else {"value": raw}
    sure = _sure(src, e.get("sure"))
    return {"src": src, "value": e.get("value"), "sure": sure, "why": str(e.get("why") or ""),
            "any_of": tuple(e["any_of"]) if e.get("any_of") else None, "words": e.get("words"),
            "rank": _rank(src, sure)}


def _layer_fields(layer: dict) -> dict:
    out = dict(layer.get("fields") or {})
    out.update({k: layer[k] for k in FIELD_ORDER if k in layer})
    return out


def _join_why(*whys) -> str:
    return "; ".join(w for w in whys if w)


# ----------------------------------------------------------------------------- merge (spec 5.2)

def merge(layers: dict, sig=None, confirmed: bool = False) -> dict:
    """The brief (JSON v1, spec 4.1) from source layers {src: layer}.

    A layer holds field answers (a bare value, or {"value", "sure", "why"}; "any_of" lets a
    source accept several values, as Step 1's "Biped" accepts a person or an animal on two legs)
    and lists: parts, props, cloth, rigid, notes, measured. Precedence for every field:
    you > step1 > step2 > job > measured (sure >= 0.8) > tripo > ai > measured (weak) > default.

    Every field comes back as {value, src, sure, why, state}. state is "yellow" when the value
    is not from you or Step 1 and sure < 0.8, or when the winner allows several values and
    nothing picks one; "red" when two sources at least 0.5 sure disagree (with "options": the two
    answers [value, words], and a one-line "reason"); else "ok". Lead's choice: a row you
    answered is never red, whatever the other sources say. Pairs of arms and pairs of legs that
    the body plan cannot have (two pairs of arms on a Person) show yellow, saying why.
    Answers that are not valid for their field (and descriptor values that are not in
    body_plans.DESC_KEYS) are left out and listed in "ignored".

    How a piece moves has one answer: a part row, a cloth row and a stiff list ("Click a part
    that must not bend") can all name it, and the highest source that chose wins (_settle), so
    the card row and the plan never disagree. Cloth kinds (cape, skirt, sash) move to the cloth
    list unless they are stiff. A whole part map (one that holds the legs) also holds the limbs
    the starting rig already has: those are taken out of the parts and listed in "limbs".

    The body plan sets some part defaults: under 'Something else' every part bends unless a
    source made it stiff; under 'More than two arms' (and on bodies whose rig has no arms) parts
    on the body's sides that read as arms become the extra arms. Hooves and claws are always on
    the stiff list. A prop worn where the body plan has no such bone shows yellow."""
    bad = sorted(set(layers) - set(SOURCES))
    if bad:
        raise ValueError(f"unknown brief sources: {bad}")
    ignored: list = []
    cands: dict = {name: [] for name in FIELD_ORDER}
    for src in SOURCES:
        layer = layers.get(src) or {}
        for name, raw in sorted(_layer_fields(layer).items()):
            if name not in FIELDS:
                ignored.append({"src": src, "field": name, "why": "not a card row"})
                continue
            e = _entry(src, raw)
            v = _clean(name, e["value"])
            if v is None:
                unset = FIELDS[name]["unset"]
                if e["value"] is not None and not (unset is not None and e["value"] == unset):
                    ignored.append({"src": src, "field": name, "value": e["value"], "why": "not a valid answer"})
                continue
            e["value"] = v
            if e["any_of"]:
                e["any_of"] = tuple(a for a in e["any_of"] if _clean(name, a) is not None) or (v,)
            cands[name].append(e)
    fields = {"body_plan": _resolve("body_plan", cands["body_plan"], _default("body_plan", None))}
    template = BP.TEMPLATES[fields["body_plan"]["value"]]
    for name in FIELD_ORDER[1:]:
        fields[name] = _resolve(name, cands[name], _default(name, template))
    parts = _merge_list(layers, "parts", "id", lambda m: _fill_part(m, ignored), ignored, ("motion", MOTIONS))
    cloth = _merge_list(layers, "cloth", "part", _fill_cloth, ignored, ("motion", CLOTH_MOTIONS))
    rigid_by = _stiff_lists(layers, ignored)
    parts, cloth, chosen = _settle(parts, cloth, rigid_by, ignored)
    known = {q["id"] for q in parts} | {c["part"] for c in cloth}
    parts, limbs = _own_limbs_out(parts, fields["body_plan"]["value"])
    _template_parts(fields, parts, chosen)
    _limb_rows(fields)
    parts.sort(key=_part_key)                     # a part the body plan named moves to its kind's place
    stiff = [q["id"] for q in parts if q["motion"] == "stiff"]
    # ids on a stiff list that are no part or cloth piece: clicked regions; hooves and claws come
    # from the hands and feet rows only
    regions = [r for r in sorted(rigid_by) if r not in known and r not in BODY_RIGID]
    rigid = list(dict.fromkeys(stiff + body_rigid(fields["hands"]["value"], fields["feet"]["value"]) + regions))
    props = _merge_list(layers, "props", "part", _fill_prop, ignored, ("role", PROP_ROLES))
    _prop_owners(props, fields, parts)
    for row in parts + cloth + props:
        row.pop("_chosen", None)
    notes = next((str((layers.get(s) or {}).get("notes")) for s in SOURCES if (layers.get(s) or {}).get("notes")), "")
    return {"v": 1, "confirmed": bool(confirmed), "sig": list(sig) if sig is not None else None,
            "fields": fields, "parts": parts, "props": props, "cloth": cloth,
            "rigid": rigid, "limbs": limbs, "notes": notes,
            "measured": dict((layers.get("measured") or {}).get("measured") or {}),
            "ignored": ignored}


def _default(name: str, template: dict | None) -> dict:
    spec = FIELDS[name]
    value, sure = spec["default"], spec["sure"]
    if template is not None and name in template["defaults"]:
        value = template["defaults"][name]
    return {"src": "default", "value": value, "sure": sure, "why": "", "any_of": None, "words": None,
            "rank": RANKS.index("default")}


def _resolve(name: str, cands: list, default: dict) -> dict:
    order = sorted(cands, key=lambda c: (c["rank"], SOURCES.index(c["src"])))
    order.append(default)
    win = order[0]
    row = {"value": win["value"], "src": win["src"], "sure": win["sure"], "why": win["why"]}
    allowed = (win["value"],)
    refined = None
    open_choice = False
    if win["any_of"] and len(win["any_of"]) > 1:
        # A lower source picks inside what the winner allows (Step 1 "Biped" + the shape's
        # "animal"): the first one at least 0.5 sure, else the surest weaker one, which still
        # shows yellow. When nothing picks, the row keeps the winner's value but is not sure.
        allowed = win["any_of"]
        inside = [c for c in order[1:] if c["src"] != "default" and c["value"] in allowed]
        refined = next((c for c in inside if c["sure"] >= DISAGREE), None)
        if refined is None and inside:
            refined = max(inside, key=lambda c: c["sure"])        # (max keeps the first of equals)
        if refined is not None:
            row = {"value": refined["value"], "src": refined["src"], "sure": refined["sure"],
                   "why": _join_why(refined["why"], win["why"])}
        else:
            open_choice = True
            row["value"] = row["value"] if row["value"] in allowed else allowed[0]
            row["sure"] = BARE_SURE["default"]
            row["why"] = _join_why(win["why"], "either " + " or ".join(_words(name, a) for a in allowed)
                                   + ": please pick")
    state = "ok"
    pair = None if win["src"] == "you" else _disagreement(name, order, win, allowed)
    if pair is not None:
        a, b = pair
        if a is win:
            value_a = row["value"]
            words_a = win["words"] or (" or ".join(_words(name, x) for x in allowed) if len(allowed) > 1
                                       else _words(name, row["value"]))
        else:
            value_a, words_a = a["value"], a["words"] or _words(name, a["value"])
        words_b = b["words"] or _words(name, b["value"])
        reason = f"{SAYS[a['src']]} {words_a}; {SAYS[b['src']]} {words_b}"
        if b["why"]:
            reason += f" ({b['why']})"
        row.update(options=[[value_a, words_a], [b["value"], words_b]], reason=reason[:1].upper() + reason[1:])
        state = "red"
    if state == "ok" and (open_choice or (row["src"] not in ("you", "step1") and row["sure"] < STRONG)):
        state = "yellow"
    if state == "ok" and FIELDS[name]["unset"] is not None and row["value"] == FIELDS[name]["unset"]:
        state = "yellow"
        row["why"] = row["why"] or "not set"
    row["state"] = state
    return row


def _disagreement(name: str, order: list, win: dict, allowed: tuple):
    """The first two sources, in precedence order, that are both at least 0.5 sure and give
    answers with nothing in common (the winner's answer is everything it allows), or None."""
    sure = [c for c in order if c["src"] != "default" and c["sure"] >= DISAGREE]

    def answers(c):
        return allowed if c is win else (c["any_of"] or (c["value"],))

    for i, a in enumerate(sure):
        for b in sure[i + 1:]:
            if not any(_same(name, x, y) for x in answers(a) for y in answers(b)):
                return a, b
    return None


def _list_of(layer: dict, key: str) -> list:
    v = layer.get(key)
    return list(v) if isinstance(v, (list, tuple)) else []


def _merge_list(layers: dict, key: str, id_key: str, fill, ignored: list, choice=None) -> list:
    """Entries of one list (parts, props, cloth) merged by their id: the highest source's keys
    win, keys only a lower source has are kept (Step 4's descriptor, the found part's name).

    One source listing the same id twice: only the surer entry is used (then the one that sorts
    first), whatever the list order; the other is listed in `ignored` and adds nothing.
    choice = (key, options): the answer a source picks for the entry (a part's motion, a prop's
    role). A value that is not one of the options is left out and listed in `ignored`; the row's
    "_chosen" is (rank, source index, source) of the entry whose answer won, or None when no
    source picked one."""
    by_id: dict = {}
    for src in SOURCES:
        best: dict = {}
        for raw in _list_of(layers.get(src) or {}, key):
            if not isinstance(raw, dict) or raw.get(id_key) is None:
                continue
            pid = str(raw[id_key])
            raw = dict(raw)
            if choice is not None and raw.get(choice[0]) is not None and not _is_option(raw[choice[0]], choice[1]):
                ignored.append({"src": src, "list": key, "id": pid, choice[0]: raw.pop(choice[0]),
                                "why": "not a valid answer"})
            sure = _sure(src, raw.get("sure"))
            e = (_rank(src, sure), SOURCES.index(src), src, sure, raw)
            if pid in best:
                ignored.append({"src": src, "list": key, "id": pid,
                                "why": "listed twice by one source: the surer entry is used"})
                e = min(e, best[pid], key=lambda x: (-x[3], json.dumps(x[4], sort_keys=True, default=str)))
            best[pid] = e
        for pid, e in best.items():
            by_id.setdefault(pid, []).append(e)
    out = []
    for pid in sorted(by_id):
        entries = sorted(by_id[pid], key=lambda e: (e[0], e[1]))      # one entry per source
        merged: dict = {}
        for entry in reversed(entries):
            merged.update({k: v for k, v in entry[4].items() if v is not None})
        src, sure, top = entries[0][2:]
        merged.update({id_key: pid, "src": src, "sure": sure, "why": str(top.get("why") or "")})
        merged["found"] = any(bool(e[4].get("found")) or bool(e[4].get("app")) for e in entries)
        if choice is not None:
            win = next((e for e in entries if e[4].get(choice[0]) is not None), None)
            merged["_chosen"] = win[:3] if win is not None else None
        merged = fill(merged)
        state = "ok"
        if src != "you" and sure >= DISAGREE and key == "parts":
            other = next((e for e in entries[1:] if e[3] >= DISAGREE and e[2] != "default"
                          and e[4].get("kind") is not None and _norm_kind(e[4]["kind"]) != merged["kind"]), None)
            if other is not None:
                k2 = _norm_kind(other[4]["kind"])
                merged["options"] = [[merged["kind"], KIND_WORDS.get(merged["kind"], merged["kind"])],
                                     [k2, KIND_WORDS.get(k2, k2)]]
                reason = (f"{SAYS[src]} {KIND_WORDS.get(merged['kind'], merged['kind']).lower()}; "
                          f"{SAYS[other[2]]} {KIND_WORDS.get(k2, k2).lower()}")
                merged["reason"] = reason[:1].upper() + reason[1:]
                state = "red"
        if state == "ok" and src not in ("you", "step1") and sure < STRONG:
            state = "yellow"
        merged["state"] = state
        out.append(merged)
    if key == "parts":
        out.sort(key=_part_key)
    return out


def _fill_part(p: dict, ignored: list | None = None) -> dict:
    raw = str(p.get("kind") or "other").lower()
    p["kind"] = _norm_kind(raw)
    if p["kind"] == "other" and raw != "other":
        p["found_kind"] = raw                     # the finder's own word ('extra', 'head_extra'): where it sits
    if p.get("desc") is not None:
        p["desc"], bad = BP.clean_desc(p["desc"])
        for k, v in bad:
            if ignored is not None:
                ignored.append({"src": p.get("src"), "part": p["id"], "desc": k, "value": v,
                                "why": "not a descriptor value"})
    if not _is_option(p.get("motion"), motions_for(p)):
        p["motion"] = KIND_MOTION.get(p["kind"], "stiff")
        if p["motion"] not in dict(motions_for(p)):
            p["motion"] = "stiff"
    try:
        p["bones"] = max(0, int(p.get("bones") or 0))     # 0 = auto
    except (TypeError, ValueError, OverflowError):
        p["bones"] = 0
    p["side"] = BP.part_side(p)                   # its own side, else its descriptor's, else its name's
    p["words"] = p.get("words") or part_words(p["id"], p["kind"])
    if isinstance(p.get("step4"), dict):
        p["step4"] = {"row": p["step4"].get("row"), "disposition": p["step4"].get("disposition")}
    return p


def motions_for(part: dict) -> tuple:
    """The motions the card offers a part: Stiff, Bends, Swings, Not a part, and Part of the head
    for a part on the head."""
    return MOTIONS if _on_head(part) else tuple(m for m in MOTIONS if m[0] != "head")


def _stiff_lists(layers: dict, ignored: list) -> dict:
    """{id: (rank, source index, source)}: the highest source that put each id on its stiff list.
    Entries that are not a name are listed in `ignored`."""
    out: dict = {}
    for src in SOURCES:
        for r in _list_of(layers.get(src) or {}, "rigid"):
            if isinstance(r, bool) or not isinstance(r, (str, int)) or str(r) == "":
                ignored.append({"src": src, "list": "rigid", "value": r, "why": "not a part name"})
                continue
            e = (_rank(src, BARE_SURE[src]), SOURCES.index(src), src)
            out[str(r)] = min(out.get(str(r), e), e)
    return out


def _settle(parts: list, cloth: list, rigid_by: dict, ignored: list) -> tuple:
    """One answer per piece for how it moves: (parts, cloth, ids whose motion a source chose).

    A piece can be named by a part row, a cloth row and a stiff list. The highest source that
    chose how it moves wins; within one source its cloth row, then its part row, then its stiff
    list (a row says more than a list). So a lower source's stiff list never stiffens a part you
    said bends, and the card row always says what the plan does.
    - Stiff or Not a part: a part row (a cape made stiff on purpose stays a stiff part);
    - Bends or Swings: a part row; for a cloth kind (cape, skirt, sash) a cloth row that swings
      (Swings) or moves with the body (Bends);
    - a cloth row's own answer: that cloth row;
    - nobody chose: the cloth row when there is one; a cloth-kind part moves to the cloth list
      and moves with the body (lead's choice); any other part keeps its kind's default.
    A stiff-list entry that loses is listed in `ignored`."""
    part_by = {q["id"]: q for q in parts}
    cloth_by = {c["part"]: c for c in cloth}
    words = dict(MOTIONS + CLOTH_MOTIONS)
    out_p, out_c, chosen = [], [], set()
    for pid in sorted(set(part_by) | set(cloth_by)):
        q, c = part_by.get(pid), cloth_by.get(pid)
        cands = []
        if c is not None and c.get("_chosen"):
            cands.append((c["_chosen"][:2], 0, c["_chosen"][2], "cloth", c["motion"]))
        if q is not None and q.get("_chosen"):
            cands.append((q["_chosen"][:2], 1, q["_chosen"][2], "part", q["motion"]))
        if pid in rigid_by:
            cands.append((rigid_by[pid][:2], 2, rigid_by[pid][2], "rigid", "stiff"))
        cands.sort(key=lambda e: (e[0], e[1]))
        win = cands[0] if cands else None
        if win is not None:
            chosen.add(pid)
            for e in cands[1:]:
                if e[3] == "rigid" and win[4] != "stiff":
                    ignored.append({"src": e[2], "list": "rigid", "id": pid,
                                    "why": f"{SAYS[win[2]]}: {words[win[4]].lower()}"})
        origin, motion = (win[3], win[4]) if win is not None else (None, None)
        if motion in ("stiff", "not_part"):
            if origin == "rigid" and (q is None or q["motion"] != "stiff"):
                q = q if q is not None else _part_from_cloth(c)
                q["why"] = _join_why(q["why"], f"{SAYS[win[2]]} it must not bend")
            q = q if q is not None else _part_from_cloth(c)
            q["motion"] = motion
            out_p.append(q)
        elif origin == "part":                    # bends, swings, part of the head
            if q["kind"] in CLOTH_KINDS and motion in ("bends", "swings"):
                c = c if c is not None else _cloth_from_part(q)
                c["motion"] = "swings" if motion == "swings" else "with_body"
                out_c.append(c)
            else:
                out_p.append(q)
        elif c is not None:                       # the cloth row's own answer, or nobody chose
            out_c.append(c)
        elif q["kind"] in CLOTH_KINDS:
            out_c.append(_cloth_from_part(q))
        else:
            out_p.append(q)
    out_c.sort(key=lambda c: c["part"])
    return out_p, out_c, chosen


def _cloth_from_part(q: dict) -> dict:
    """A cloth-kind part as a cloth row (its sizes, found name and Step 4 facts come along)."""
    c = {k: v for k, v in q.items() if k not in ("id", "kind", "motion", "bones", "side", "found_kind")}
    c.update(part=q["id"], kind=q["kind"])
    return _fill_cloth(c)


def _part_from_cloth(c: dict) -> dict:
    """A cloth row as a part row, for a cloth piece a source made stiff or called not a part."""
    q = {k: v for k, v in c.items() if k not in ("part", "motion", "words")}
    q["id"] = c["part"]
    return _fill_part(q)


def _own_limbs_out(parts: list, tname: str) -> tuple:
    """(parts without the limbs the starting rig already has, those limbs as [{id, role}]).
    Only parts with no card kind can be such a limb (body_plans.own_limbs)."""
    own = BP.own_limbs([q for q in parts if q["kind"] == "other"], tname)
    drop = {i for i, _r in own}
    return [q for q in parts if q["id"] not in drop], [{"id": i, "role": r} for i, r in own]


def body_rigid(hands: str, feet: str) -> list:
    """Body regions that are always stiff (spec 5.1): hooves, and claws on the hands."""
    out = ["hooves"] if "hooves" in (hands, feet) else []
    return out + (["claws"] if hands == "claws" else [])


def _on_head(q: dict) -> bool:
    return ((q.get("desc") or {}).get("host") == "head" or q["kind"] in HEAD_KINDS
            or q.get("found_kind") == "head_extra")


def _arm_rank(q: dict, auto_motion: bool = False):
    """How clearly a part is an extra arm: 0 when it is named an arm, 1 when its descriptor reads
    as an arm, 2 when it is an unnamed part on one side of the body, off the head, with no
    descriptor; None when it is not one. A stiff part is never one, unless stiff is only its
    kind's default (auto_motion)."""
    if q.get("motion") in ("not_part", "head") or (q.get("motion") == "stiff" and not auto_motion):
        return None
    if q["kind"] == "arm":
        return 0
    if q["kind"] != "other" or q.get("side") not in ("l", "r") or _on_head(q):
        return None
    host = (q.get("desc") or {}).get("host")
    if host not in (None, "core"):
        return None                               # a part on a part
    if q.get("desc"):
        return 1 if BP.role(q) == "arm" else None
    return 2


def _arm_slots(ranked: list, n: int) -> list:
    """n extra arm pairs as [(left part or None, right part or None)] from [(rank, part)]: the
    clearest candidates first, then by name, so the same parts give the same pairs in any order."""
    def side(s):
        return [q for _r, q in sorted(((r, q) for r, q in ranked if q.get("side") == s),
                                      key=lambda rq: (rq[0], rq[1]["id"]))]

    lefts, rights = side("l"), side("r")
    return [(lefts[i] if i < len(lefts) else None, rights[i] if i < len(rights) else None) for i in range(n)]


def extra_arm_pairs(tname: str, arm_pairs) -> int:
    """The arm pairs a plan adds to the starting rig: the card's pairs of arms beyond the rig's
    own, on the body plans that take arms from that row (body_plans 'extra_arms'); at least one
    on 'More than two arms'. Other body plans keep their rig's arms (0)."""
    t = BP.TEMPLATES[tname]
    if not t["extra_arms"]:
        return 0
    try:
        n = int(arm_pairs)
    except (TypeError, ValueError):
        n = 0
    return max(n - t["rig_limbs"]["arm_pairs"], 1 if tname == "multi_arm" else 0)


def _arm_candidates(parts: list, tname: str, chosen: set | None = None) -> list:
    """[(rank, part)] for the parts that can be extra arms on this body plan (_arm_rank). An
    unnamed part on the body's side (rank 2) counts only under 'More than two arms'."""
    top = 2 if tname == "multi_arm" else 1
    out = []
    for q in parts:
        r = _arm_rank(q, chosen is not None and q["id"] not in chosen)
        if r is not None and r <= top:
            out.append((r, q))
    return out


def _template_parts(fields: dict, parts: list, chosen: set) -> None:
    """Part defaults that come from the body plan (in place).

    Extra arms (on 'More than two arms', and on four-legged, snake and other bodies, whose rig
    has no arms): the extra arm pairs take the parts named arms first, then parts on the body's
    sides that read as arms, then (more than two arms only) unnamed parts on its sides. Nobody
    having set the number of arm pairs, the matched pairs found set it: a left part counts only
    with a right one, so a lone part on one side (a shoulder cannon) never adds a pair. A part
    that could be an arm but is left over stays as it is, shown yellow with the reason.
    'Something else': every part bends (one chain each) unless a source made it stiff."""
    tname = fields["body_plan"]["value"]
    t = BP.TEMPLATES[tname]
    if t["extra_arms"]:
        ranked = _arm_candidates(parts, tname, chosen)
        row = fields["arm_pairs"]
        found = min(sum(1 for _r, q in ranked if q["side"] == s) for s in ("l", "r"))
        own = t["rig_limbs"]["arm_pairs"]
        if row["src"] == "default" and found and own + found > int(row["value"]):
            n = min(own + found, FIELDS["arm_pairs"]["hi"])
            sure = min(q["sure"] for _r, q in ranked)
            fields["arm_pairs"] = {"value": n, "src": "measured", "sure": sure,
                                   "why": f"{n} pairs of arms counted from the parts found",
                                   "state": "ok" if sure >= STRONG else "yellow"}
        extra = extra_arm_pairs(tname, fields["arm_pairs"]["value"])
        taken = set()
        for left, right in _arm_slots(ranked, extra):
            for q in (left, right):
                if q is None:
                    continue
                taken.add(q["id"])
                if q["kind"] == "arm":
                    continue
                q["kind"], q["words"] = "arm", part_words(q["id"], "arm")
                q.pop("found_kind", None)
                if q["id"] not in chosen:
                    q["motion"] = "bends"
                q["why"] = _join_why(q["why"], f"{t['short']}: a part on the body's side")
                if q["state"] == "ok":
                    q["state"] = "yellow"
        for _r, q in ranked:
            if q["id"] in taken or q["kind"] == "arm":
                continue
            mine = sum(1 for _r2, q2 in ranked if q2["side"] == q["side"])
            no_twin = mine > sum(1 for _r2, q2 in ranked if q2["side"] != q["side"])
            q["why"] = _join_why(q["why"], "could be an arm, but has no twin on the other side" if no_twin
                                 else "could be an arm, but the pairs of arms are already full")
            if q["state"] == "ok":
                q["state"] = "yellow"
    if tname == "custom":
        for q in parts:
            if q["motion"] == "stiff" and q["id"] not in chosen:
                q["motion"] = "bends"
                q["why"] = _join_why(q["why"], "Something else: every part bends unless you make it stiff")


def _pairs_words(n: int) -> str:
    return {0: "no", 1: "one pair of", 2: "two pairs of"}.get(n, f"{n} pairs of")


def limb_row_problems(tname: str, arm_pairs, leg_pairs) -> dict:
    """{field: why} for the pairs-of-arms and pairs-of-legs rows a body plan cannot have: a
    Person or an animal on two legs has one pair of arms (more is 'More than two arms'), which
    needs at least two; every body plan but 'Something else' has its rig's pairs of legs. A
    bird's pairs of arms are its wings, so that row is not checked for it."""
    t = BP.TEMPLATES[tname]
    have = t["rig_limbs"]
    out = {}
    try:
        arms, legs = int(arm_pairs), int(leg_pairs)
    except (TypeError, ValueError):
        return out
    if tname == "multi_arm" and arms < 2:
        out["arm_pairs"] = "More than two arms needs at least two pairs of arms"
    elif not t["extra_arms"] and tname != "bird" and arms != have["arm_pairs"]:
        out["arm_pairs"] = (f"{t['short']} has {_pairs_words(have['arm_pairs'])} arms"
                            + ("; for more, pick More than two arms" if arms > have["arm_pairs"] else ""))
    if tname != "custom" and legs != have["leg_pairs"]:
        out["leg_pairs"] = f"{t['short']} has {_pairs_words(have['leg_pairs'])} legs"
    return out


def _limb_rows(fields: dict) -> None:
    """Pairs-of-arms and pairs-of-legs rows that the body plan cannot have turn yellow, saying
    why (limb_row_problems). They are never red: the rows are not two sources disagreeing."""
    probs = limb_row_problems(fields["body_plan"]["value"], fields["arm_pairs"]["value"],
                              fields["leg_pairs"]["value"])
    for name in ("arm_pairs", "leg_pairs"):
        if name in probs:
            row = fields[name]
            row["why"] = _join_why(row["why"], probs[name])
            if row["state"] == "ok":
                row["state"] = "yellow"


def _prop_owners(props: list, fields: dict, parts: list) -> None:
    """A prop row turns yellow when the body plan has no bone for its role (a hand on a snake):
    its 'why' says where it goes instead (the same rule as the plan's sockets, _owner_bone)."""
    tname = fields["body_plan"]["value"]
    t = BP.TEMPLATES[tname]
    arms = {q["side"] for q in parts if q["kind"] == "arm" and q["motion"] in ("bends", "swings")
            and q["side"] in ("l", "r")}
    if extra_arm_pairs(tname, fields["arm_pairs"]["value"]):
        arms |= {"l", "r"}
    rig = _rig_bones(t["preset"], t["add_limbs"], arms)
    for pr in props:
        if pr["role"] in ("bends", "swings"):
            continue
        _owner, _other, note = _owner_bones(pr, pr["role"], rig)
        if note:
            pr["why"] = _join_why(pr["why"], note)
            if pr["state"] == "ok":
                pr["state"] = "yellow"


def _fill_prop(p: dict) -> dict:
    if not _is_option(p.get("role"), PROP_ROLES):
        p["role"] = "bends"                       # no role known: the skin follows the body, no socket
    if p.get("detachable") is None:
        p["detachable"] = p["role"] in HELD
    p["words"] = p.get("words") or str(p["part"]).replace("_", " ")
    p.setdefault("grip", None)
    return p


def _fill_cloth(c: dict) -> dict:
    if not _is_option(c.get("motion"), CLOTH_MOTIONS):
        c["motion"] = "with_body"                 # lead's choice: cloth and hair move with the body
    c["kind"] = str(c.get("kind") or "other")
    c["words"] = c.get("words") or str(c["part"]).replace("_", " ")
    return c


def step1_layer(kind=None, style=None, height_m=None, height_to=None, symmetry=None, notes=None) -> dict:
    """Step 1's brief as a merge layer. "Biped" accepts a person or an animal on two legs (the
    shape decides between them); "Four-legged animal" is four legs; "Creature" leaves it to the
    shape; "Vehicle / machine" moves like a machine. The art style allows its own proportions."""
    out: dict = {}
    if kind == "biped":
        out["body_plan"] = {"value": "person", "any_of": ["person", "upright_animal"], "words": "Two legs",
                            "why": "Step 1 said Biped"}
    elif kind == "quadruped":
        out["body_plan"] = {"value": "quadruped", "words": "Four legs", "why": "Step 1 said Four-legged animal"}
    elif kind == "vehicle":
        out["moves_like"] = {"value": "machine", "why": "Step 1 said Vehicle / machine"}
    if style == "cartoon":
        out["proportions"] = {"value": "cartoon", "any_of": ["cartoon", "chibi"], "why": "Step 1 said Cartoon"}
    elif style == "realistic":
        out["proportions"] = {"value": "realistic", "why": "Step 1 said Realistic"}
    if height_m:
        out["height_m"] = float(height_m)
    if height_to:
        out["height_to"] = height_to
    if symmetry:
        out["symmetry"] = symmetry
    if notes:
        out["notes"] = str(notes)
    return out


def parts_from_apps(apps: list) -> list:
    """The parts appendages.find measured, as a 'measured' layer's parts: kind, the found name,
    how sure (from the label margin when the finder gives one) and Step 4's descriptor when the
    item carries one."""
    out = []
    for a in sorted(apps or [], key=lambda a: str(a.get("name"))):
        if a.get("name") is None:
            continue
        sure = a.get("sure")
        if sure is None:
            sure = min(1.0, 0.5 + float(a["margin"])) if a.get("margin") is not None else 0.6
        p = {"id": str(a["name"]), "kind": a.get("kind"), "app": str(a["name"]), "found": True,
             "sure": round(float(sure), 6), "margin": a.get("margin"), "why": a.get("why") or ""}
        if a.get("desc") is not None:
            p["desc"] = dict(a["desc"])
        if a.get("step4") is not None:
            p["step4"] = dict(a["step4"])
        out.append(p)
    return out


# ----------------------------------------------------------------------------- reading a brief

def value(brief: dict, name: str):
    """A field's value, or its default (the body plan's default where it has one) when the row is
    missing or holds no valid answer."""
    row = (brief.get("fields") or {}).get(name)
    if isinstance(row, dict) and row.get("value") is not None:
        v = _clean(name, row["value"])
        if v is not None:
            return v
    if name != "body_plan":
        t = BP.TEMPLATES.get(value(brief, "body_plan"))
        if t is not None and name in t["defaults"]:
            return t["defaults"][name]
    return FIELDS[name]["default"]


def alerts(brief: dict) -> dict:
    """The rows to look at: {"red": [...], "yellow": [...]}, fields in card order then parts."""
    out = {"red": [], "yellow": []}
    for name in FIELD_ORDER:
        st = ((brief.get("fields") or {}).get(name) or {}).get("state")
        if st in out:
            out[st].append(name)
    for p in brief.get("parts", []):
        if p.get("state") in out:
            out[p["state"]].append(f"part:{p['id']}")
    return out


def reopen(old: dict | None, new: dict) -> bool:
    """A confirmed card opens again only when the body changed (its signature) or a new red row
    appeared (spec 5.2)."""
    if not old or not old.get("confirmed"):
        return True
    if old.get("sig") != new.get("sig"):
        return True
    return bool(set(alerts(new)["red"]) - set(alerts(old)["red"]))


CLOTH_WORDS = {"cape": ("cape", "capes"), "skirt": ("skirt", "skirts"), "sash": ("sash", "sashes")}
SUMMARY_PIECES = 5    # at most this many kinds of extra parts and cloth in the one line; the rest as "+n more"


def summary_words(brief: dict) -> str:
    """The card in one line once it is confirmed, for example
    'Animal on two legs · hooves · 2 horns · 2 ears · tail · no props'.

    Parts that are not a part, or part of the head (a muzzle), are not counted; cloth is, after
    the parts. Past SUMMARY_PIECES kinds the rest show as '+n more', so the line stays short."""
    bits = [BP.TEMPLATES[value(brief, "body_plan")]["short"]]
    hands, feet = value(brief, "hands"), value(brief, "feet")
    n = int(value(brief, "fingers"))
    hand_w = {"fingers": f"{n} finger{'s' if n != 1 else ''}", "mitten": "mittens", "hooves": "hooves",
              "paws": "paws", "claws": "claws"}.get(hands)
    feet_w = {"toes": "toes", "paws": "paws", "hooves": "hooves", "heel_raised": "walks on its toes"}.get(feet)
    bits += [w for w in (hand_w, feet_w if feet_w != hand_w else None) if w]
    counts: dict = {}
    for p in brief.get("parts", []):
        if isinstance(p, dict) and p.get("motion") not in ("not_part", "head"):
            k = _norm_kind(p.get("kind"))
            if k not in CLOTH_KINDS:
                counts[k] = counts.get(k, 0) + 1
    pieces = []
    for k in sorted(counts, key=lambda k: KIND_RANK.get(k, len(KIND_RANK))):
        if KIND_PLURAL[k] in bits:
            continue                              # hooves or claws already said by the hands or feet
        pieces.append(KIND_ONE[k] if counts[k] == 1 else f"{counts[k]} {KIND_PLURAL[k]}")
    cloth: dict = {}
    for c in brief.get("cloth", []):
        if isinstance(c, dict):
            w = CLOTH_WORDS.get(str(c.get("kind")), ("cloth piece", "cloth pieces"))
            cloth[w] = cloth.get(w, 0) + 1
    pieces += [one if k == 1 else f"{k} {more}" for (one, more), k in sorted(cloth.items())]
    if len(pieces) > SUMMARY_PIECES:
        pieces = pieces[:SUMMARY_PIECES - 1] + [f"+{len(pieces) - SUMMARY_PIECES + 1} more"]
    bits += pieces
    props = len(brief.get("props", []))
    bits.append("no props" if props == 0 else f"{props} prop{'s' if props != 1 else ''}")
    return " · ".join(bits)


# ----------------------------------------------------------------------------- chain bones

BONE_LEN = 2.5        # one chain bone is about 2.5 times the chain's mean radius long
MIN_BONES, BASE_MAX, BEND_MAX = 2, 8, 10
MAX_TURN = 35.0       # a bone may turn at most this much (degrees) from the one before it
SMOOTH_STEPS = 16     # points per span of the smoothed centre line
EPS = BP.EPS          # a ratio this close to a boundary counts as on it (the same at any scale)


def chain_bones(arc_len: float, mean_radius: float, cap=None, bend=None) -> int:
    """Bones for a bending chain (tail, trunk, tentacle): clamp(round(L / 2.5 r), 2, 8).

    With `bend`, the chain's centre line at rest (a polyline of points, root to tip), the count
    is the smallest from there up to 10 at which no bone turns more than 35 degrees from the one
    before it, measured on a smooth line through the points (10 when none is). `cap` (the bone
    budget) has the last word. Only ratios of the sizes count, so the result is the same at any
    scale."""
    if mean_radius and mean_radius > 0 and arc_len and arc_len > 0:
        n = int(math.floor(arc_len / (BONE_LEN * mean_radius) + 0.5 + 1e-9))
    else:
        n = MIN_BONES
    n = min(max(n, MIN_BONES), BASE_MAX)
    if bend is not None and len(bend) >= 3:
        line = smooth_line(bend)
        n = next((m for m in range(n, BEND_MAX + 1) if _turn(line, m) <= MAX_TURN), max(n, BEND_MAX))
    if cap is not None:
        n = min(n, max(1, int(cap)))
    return n


def _mix(a, b, u: float) -> tuple:
    return tuple(x + (y - x) * u for x, y in zip(a, b))


def smooth_line(poly, steps: int = SMOOTH_STEPS) -> list:
    """A smooth centre line through a polyline's points, sampled `steps` times per span.

    The finder gives a chain as a handful of points. Bones laid on that coarse line turn at its
    corners however many there are, so the turn is measured on this line instead: a centripetal
    Catmull-Rom spline (it never loops or overshoots at a sharp corner), running straight on
    past both ends. Its shape depends only on the points, so it is the same at any scale."""
    pts: list = []
    for q in poly:
        q = tuple(float(c) for c in q)
        if not pts or math.dist(q, pts[-1]) > 0:
            pts.append(q)
    if len(pts) < 3:
        return pts
    ext = [_mix(pts[0], pts[1], -1.0)] + pts + [_mix(pts[-1], pts[-2], -1.0)]
    out = [pts[0]]
    for i in range(1, len(ext) - 2):
        p0, p1, p2, p3 = ext[i - 1], ext[i], ext[i + 1], ext[i + 2]
        t1 = math.dist(p0, p1) ** 0.5
        t2 = t1 + math.dist(p1, p2) ** 0.5
        t3 = t2 + math.dist(p2, p3) ** 0.5
        for k in range(1, steps + 1):
            t = t1 + (t2 - t1) * k / steps
            a1, a2, a3 = _mix(p0, p1, t / t1), _mix(p1, p2, (t - t1) / (t2 - t1)), _mix(p2, p3, (t - t2) / (t3 - t2))
            b1, b2 = _mix(a1, a2, t / t2), _mix(a2, a3, (t - t1) / (t3 - t1))
            out.append(_mix(b1, b2, (t - t1) / (t2 - t1)))
    return out


def _resample(pts: list, n: int) -> list:
    """n+1 points evenly along a polyline by arc length (the same rule as arp_rig._resample)."""
    seg = [math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
    total = sum(seg) or 1e-12
    out, acc, i = [tuple(pts[0])], 0.0, 0
    for k in range(1, n):
        want = total * k / n
        while i < len(seg) - 1 and acc + seg[i] < want:
            acc += seg[i]
            i += 1
        t = min(max((want - acc) / max(seg[i], 1e-300), 0.0), 1.0)
        out.append(tuple(a + (b - a) * t for a, b in zip(pts[i], pts[i + 1])))
    out.append(tuple(pts[-1]))
    return out


def max_turn(poly, n: int) -> float:
    """The largest turn (degrees) between neighbouring bones when n bones follow the smooth line
    through the polyline's points (smooth_line)."""
    return _turn(smooth_line(poly), n)


def _turn(line: list, n: int) -> float:
    q = _resample(line, n)
    worst = 0.0
    for a, b, c in zip(q, q[1:], q[2:]):
        u = [y - x for x, y in zip(a, b)]
        v = [y - x for x, y in zip(b, c)]
        nu, nv = math.hypot(*u), math.hypot(*v)
        if nu <= 0 or nv <= 0:
            continue
        cos = sum(x * y for x, y in zip(u, v)) / (nu * nv)
        worst = max(worst, math.degrees(math.acos(min(1.0, max(-1.0, cos)))))
    return worst


def _poly_len(poly) -> float:
    pts = [tuple(float(c) for c in p) for p in poly]
    return sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))


def _first(key: str, *where):
    """The first set value of key in the dicts given (the found item first, then the brief part)."""
    return next((d[key] for d in where if d.get(key)), None)


def _size(part: dict, app: dict | None) -> tuple:
    """(arc length, mean radius, centre polyline) of a part: each size from its found item when
    it has one, else from the brief part. Any of them is None when unknown."""
    where = (app or {}, part)
    poly = _first("chain", *where) or _first("path", *where)
    arc = _first("arc_len", *where)
    if arc is None and poly is not None and len(poly) >= 2:
        arc = _poly_len(poly) or None
    if arc is None:
        arc = _first("length", *where)
    r = _first("radius", *where)
    if r is None:
        thick = _first("thickness", *where) or _first("width", *where)
        r = 0.5 * float(thick) if thick else None
    return (float(arc) if arc else None, float(r) if r else None, poly)


EAR_LONG, EAR_SHORT = 4.0, 2.0       # ear length over its root width / over its thickness


def ear_bones(part: dict, app: dict | None) -> int:
    """2 bones; 3 when the ear is longer than 4 times its root width; 1 (it turns as one piece)
    when it is shorter than twice its root thickness (spec 5.5). Each size comes from the found
    item when it has one, else from the brief part."""
    where = (app or {}, part)
    length = _first("length", *where)
    chain = _first("chain", *where)
    if length is None and chain:
        length = _poly_len(chain)
    ring = _first("ring", *where)
    width = 2.0 * float(ring[2]) if ring is not None and len(ring) > 2 and ring[2] else _first("width", *where)
    thick = _first("thickness", *where)
    if length and thick and float(length) / float(thick) < EAR_SHORT - EPS:
        return 1
    if length and width and float(length) / float(width) > EAR_LONG + EPS:
        return 3
    return 2


# ----------------------------------------------------------------------------- the plan (spec 5.5)

@dataclass
class RigPlan:
    """How Step 8 builds the rig. limb_options: [(ref_bone, limb_type, side, changes)] for Auto-Rig
    Pro's limb settings (spec 9.2 changes them safely); chains: one entry per extra part chain,
    whose limb is tail, ears, tail_dupli, spline_ik, kilt, arm_dupli (a copy of an arm the rig
    has) or arm (the first arm on a side of a rig with none: four legs, a snake, other bodies);
    counts: {spine, neck, tail, ear} bone counts (None = the rig's own)."""
    template: str
    preset: str
    limb_options: list = field(default_factory=list)
    counts: dict = field(default_factory=dict)
    chains: list = field(default_factory=list)
    rigid: list = field(default_factory=list)
    sockets: list = field(default_factory=list)
    skinned_props: list = field(default_factory=list)
    face: str = "head_one"
    bind_engine: str = "HEAT_MAP"
    export_type: str = "UNIVERSAL"
    max_influences: int = 4
    add_limbs: list = field(default_factory=list)      # limbs the starting rig lacks (Auto-Rig Pro add_limb)
    remove_limbs: list = field(default_factory=list)   # [(ref_bone, limb_type, side)] the starting rig has
    #                                                    and this body lacks (Auto-Rig Pro disable_limb)
    rigid_regions: list = field(default_factory=list)  # stiff body regions that are not parts: hooves,
    #                                                    claws, a tail tuft
    ankle_at_hock: bool = False                        # heel-raised legs kept two-bone for human animations
    rigid_pieces: bool = False                         # a machine: each loose piece follows one bone, no heat
    loose_rigid: bool = False                          # both: loose pieces that do not touch the skin follow
    #                                                    one bone each; the body binds as usual
    cloth_masks: list = field(default_factory=list)    # cloth left for game physics (a mask in the export)
    required: list = field(default_factory=list)       # joints that must exist before the build
    notes: list = field(default_factory=list)          # what the plan chose, in plain words

    def to_json(self) -> dict:
        d = asdict(self)
        d["limb_options"] = [list(o) for o in self.limb_options]
        d["remove_limbs"] = [list(o) for o in self.remove_limbs]
        return d


# Auto-Rig Pro's own option, limb and bone names, as the WP0 probe lists them
# (addon_trial.EXPECTED_LIMB_OPTIONS, LIMB_REFS, OWNER_BONES). arp_rig uses only tail_count,
# ear_count and facial today; the finger, toe, three_bones_leg, neck_count, spine_count, tail_side,
# spline_*, arm_wings and facial_* options are the spec's names (9.2-9.5), used from WP6 and WP8 on.
FINGER_KEYS = ("finger_thumb", "finger_index", "finger_middle", "finger_ring", "finger_pinky")
TOE_KEYS = ("toes_thumb", "toes_index", "toes_middle", "toes_ring", "toes_pinky")
DIGIT_HANDS = ("fingers", "claws", "mitten")        # hands with finger bones (voxel binding blurs them)


def finger_changes(hands: str, fingers: int = 5, thumb: bool = True) -> dict:
    """Auto-Rig Pro arm options for the hands (spec 9.3). Fingers or claws: the count includes
    the thumb when there is one, and drops from the little finger (4 with a thumb drops the
    pinky; 3 drops ring and pinky). Mitten: thumb and index. Hooves, paws, none: all off."""
    if hands in ("fingers", "claws"):
        rest = max(0, min(4, int(fingers) - (1 if thumb else 0)))
        on = (bool(thumb),) + tuple(i < rest for i in range(4))
    elif hands == "mitten":
        on = (True, True, False, False, False)
    else:
        on = (False,) * 5
    return dict(zip(FINGER_KEYS, on))


def toe_changes(feet: str, toes: int = 5) -> dict:
    """Auto-Rig Pro leg options for the feet: Toes per count (dropping from the little toe);
    hooves, paws, none: all off. Flat feet and heel-raised feet keep the rig's own toes ({})."""
    if feet == "toes":
        n = max(0, min(5, int(toes)))
        return dict(zip(TOE_KEYS, tuple(i < n for i in range(5))))
    if feet in ("hooves", "paws", "none"):
        return dict.fromkeys(TOE_KEYS, False)
    return {}


SPINE_LONG = 2.5      # a trunk longer than this many times its thickness gets 3 spine bones


def neck_count(length, thickness) -> int:
    """1 bone when the neck is shorter than its thickness, 2 when shorter than twice it, else 3;
    never below 1 (spec 9.3)."""
    if not thickness or thickness <= 0 or length is None:
        return 1
    ratio = float(length) / float(thickness)
    return 1 if ratio < 1.0 - EPS else (2 if ratio < 2.0 - EPS else 3)


def _pt(p) -> tuple:
    return tuple(float(c) for c in p)


def _conf_r(J: dict, *keys):
    conf = J.get("_conf") or {}
    for k in keys:
        r = (conf.get(k) or {}).get("r")
        if r:
            return float(r)
    return None


def _neck_size(brief: dict, J: dict | None) -> tuple:
    """(neck length, neck thickness) from the measurements, else from the joints; None when unknown."""
    m = brief.get("measured") or {}
    if m.get("neck_len") is not None and m.get("neck_thick"):
        return float(m["neck_len"]), float(m["neck_thick"])
    if not J or "neck" not in J:
        return None, None
    base = _pt(J["neck"][0])
    top = _pt(J["_skull_base"]) if J.get("_skull_base") is not None else _pt(J["neck"][1])
    r = _conf_r(J, "neck")
    return math.dist(base, top), (2.0 * r if r else None)


def _trunk_size(brief: dict, J: dict | None) -> tuple:
    """(trunk length, trunk thickness): pelvis to neck base along the spine points when there are
    some; None when unknown."""
    m = brief.get("measured") or {}
    if m.get("trunk_len") is not None and m.get("trunk_thick"):
        return float(m["trunk_len"]), float(m["trunk_thick"])
    if not J or "pelvis" not in J or "neck" not in J:
        return None, None
    pts = [_pt(J["pelvis"][0])] + [_pt(p) for p in (J.get("_spine_pts") or [])] + [_pt(J["neck"][0])]
    r = _conf_r(J, "spine", "pelvis")
    return _poly_len(pts), (2.0 * r if r else None)


def _limb_name(pid: str) -> str:
    """A chain name Auto-Rig Pro accepts: letters, digits and '_', never 'head', 'root' or 'neck'
    in any case (those break its own bone lookups)."""
    name = re.sub(r"[^A-Za-z0-9_]", "_", str(pid)) or "part"
    return re.sub(r"(?i)head|root|neck", "part", name)


def _unique_names(chains: list) -> None:
    """Two spline chains on the same side never share a name: a later one gets '_2', '_3'
    (the chains are already in a fixed order)."""
    used: set = set()
    for c in chains:
        opts = c.get("options") or {}
        if "spline_name" not in opts:
            continue
        base, side, k = opts["spline_name"], opts.get("spline_side"), 1
        name = base
        while (name.lower(), side) in used:
            k += 1
            name = f"{base}_{k}"
        used.add((name.lower(), side))
        opts["spline_name"] = name


def _owner_hint(p: dict) -> str | None:
    host = (p.get("desc") or {}).get("host")
    if host and host not in ("core", "head"):
        return str(host)                          # a part on a part follows that part
    if _on_head(p):
        return "head"
    if p["kind"] == "mane":
        return "neck"
    return None                                   # the body bone its root grows from (found at build)


def _part_key(q: dict) -> tuple:
    """Card order: kind from the head down, then name. Every list the plan builds follows it."""
    return (KIND_RANK.get(q["kind"], len(KIND_RANK)), str(q["id"]))


def _side_suffix(side: str) -> str:
    return {"l": ".l", "r": ".r"}.get(side, ".x")


def plan(brief: dict, apps=None, J=None, targets=None, probe=None) -> RigPlan:
    """The rig plan for a brief (spec 5.5). apps: appendages.find items (their chains and
    thicknesses size the chains); J: the joint dict (neck and trunk sizes). targets: {"engines":
    ["unity", "unreal"], "chain_cap": n} from the Step 9 budgets. probe: {"bird_ok", "wings_ok"}
    from the WP0 Auto-Rig Pro probe; until the probe says True, neither the bird rig nor wings on
    arm copies are used. Parts are taken in card order (kind, then name), so the order of the
    brief's lists never changes the plan.

    The brief is merge()'s: how each part moves is its row's motion (the stiff list only adds
    regions that are no part, such as a clicked patch, hooves or claws), and its parts never hold
    the limbs the starting rig already has (merge lists those under "limbs")."""
    targets, probe = targets or {}, probe or {}
    tname = value(brief, "body_plan")
    t = BP.TEMPLATES[tname]
    hands, feet = value(brief, "hands"), value(brief, "feet")
    apps_by = {str(a["name"]): a for a in (apps or []) if isinstance(a, dict) and a.get("name") is not None}
    neck_len, neck_thick = _neck_size(brief, J)
    neck_ratio = neck_len / neck_thick if neck_len is not None and neck_thick else None
    preset, why = BP.choose_preset(tname, hands, feet, neck_ratio, probe.get("bird_ok"))
    if preset == "bird_44":                       # Auto-Rig Pro picks that file itself; Forge never names it
        preset = "bird"
    p = RigPlan(template=tname, preset=preset, add_limbs=list(t["add_limbs"]), required=list(t["required"]))
    if why:
        p.notes.append(why)
    cap = targets.get("chain_cap")

    # ---- the trunk first: the top spine bone is where arms and wings hang from
    trunk_len, trunk_thick = _trunk_size(brief, J)
    has_head = preset != "free" or "head" in p.add_limbs
    has_spine = preset != "free" or "spine" in p.add_limbs
    spine_n = None
    if has_spine and tname == "serpent" and trunk_len and trunk_thick:
        spine_n = chain_bones(trunk_len, 0.5 * trunk_thick, cap)
    elif has_spine and trunk_len and trunk_thick and trunk_len / trunk_thick > SPINE_LONG + EPS:
        spine_n = 3
    chest = f"spine_{int(spine_n or 2):02d}"

    # ---- extra parts: chains and stiff parts
    regions = {str(r) for r in brief.get("rigid", []) or []
               if isinstance(r, (str, int)) and not isinstance(r, bool)}
    every = sorted((_fill_part(dict(q)) for q in brief.get("parts", []) or []
                    if isinstance(q, dict) and q.get("id") is not None), key=_part_key)
    parts = [q for q in every if q["motion"] != "not_part"]
    cloth = {str(c["part"]): c for c in brief.get("cloth", []) or []
             if isinstance(c, dict) and c.get("part") is not None}
    known = {q["id"] for q in every} | set(cloth)
    for q in every:                               # one answer per piece: only a moving cloth part keeps a cloth row
        if q["kind"] not in CLOTH_KINDS or q["motion"] not in ("bends", "swings"):
            cloth.pop(q["id"], None)
    wing_arms = _wing_arms(parts) if tname == "bird" else set()
    # the dog and horse rigs already have a tail and a pair of ears: those are set, not added
    own_limbs = ("tail", "ears") if preset in ("dog", "horse") else ()
    arm_sides = {"l", "r"} if preset in ARM_PRESETS else set()     # sides that have an arm to copy

    def parent(q, usual=None):
        hint = _owner_hint(q) if q is not None else None
        if tname == "custom" and hint in (None, "head", "neck"):
            return "root"                         # 'Something else' has no body bones: the rig's root
        return hint or usual

    def app_of(q):
        return apps_by.get(str(q.get("app") or q["id"]))

    moving = [q for q in parts if q["motion"] in ("bends", "swings")]
    ears = [q for q in moving if q["kind"] == "ear"]
    pair = _ear_pair(ears)
    # Auto-Rig Pro's one ears limb has one bone count for both sides: the larger of the two
    pair_n = max((_ear_n(q, app_of(q)) for q in ears if q["id"] in pair), default=None)
    # the first tail takes the rig's tail limb (named "tail"), a bending one before a swinging one
    tails = sorted((q for q in moving if q["kind"] == "tail"), key=lambda q: (q["motion"] != "bends", q["id"]))
    first_tail = tails[0]["id"] if tails and tname != "serpent" else None
    fingers = finger_changes(hands, value(brief, "fingers"), value(brief, "thumb"))

    # ---- extra arms from the card's pairs of arms, on the parts found when there are some
    taken: set = set()
    extra = extra_arm_pairs(tname, value(brief, "arm_pairs"))
    if extra:
        ranked = _arm_candidates(parts, tname)
        row0 = t["rig_limbs"]["arm_pairs"]
        for i, slot in enumerate(_arm_slots(ranked, extra)):
            row = row0 + i + 1
            for s, q in zip(("l", "r"), slot):
                if q is not None:
                    taken.add(q["id"])
                pid = q["id"] if q is not None else (f"arm_{s}{row}" if row > 1 else f"arm_{s}")
                p.chains.append(_arm_chain(pid, "arm", s, bool(q is not None and q.get("found")), row, arm_sides,
                                           fingers, parent(q, chest)))
        p.notes.append(f"more than two arms: {2 * extra} arm copies, one per extra arm" if tname == "multi_arm"
                       else f"{2 * extra} arms added: this body plan's rig has none of its own")
    for name, why in sorted(limb_row_problems(tname, value(brief, "arm_pairs"), value(brief, "leg_pairs")).items()):
        p.notes.append(f"{why}: one extra pair is planned" if name == "arm_pairs" and tname == "multi_arm"
                       else f"{why} (the card's number is not used)")

    for q in parts:
        kind, motion, app = q["kind"], q["motion"], app_of(q)
        base = {"part": q["id"], "kind": kind, "side": q.get("side", "x"), "found": bool(q.get("found")),
                "options": {}}
        if q["id"] in taken or q["id"] in wing_arms:
            continue                              # an extra arm above, or a bird's wing that is its arm
        if motion == "head":
            continue                              # part of the head: the head's skin, no bones of its own
        if motion == "stiff":
            p.rigid.append({"part": q["id"], "owner_hint": parent(q)})
            continue
        if kind in CLOTH_KINDS:
            cloth.setdefault(q["id"], {"part": q["id"], "kind": kind, "app": q.get("app"),
                                       "motion": "swings" if motion == "swings" else "with_body"})
            continue
        arc, r, poly = _size(q, app)
        if kind == "ear":
            if q["id"] in pair:
                p.chains.append({**base, "limb": "ears", "add": None if "ears" in own_limbs else "ears",
                                 "bones": pair_n, "parent_hint": parent(q, "head"),
                                 "options": {"ear_count": pair_n}})
            else:                                 # more ears than one pair: tail copies hung from the head
                n = _ear_n(q, app)
                p.chains.append({**base, "limb": "tail_dupli", "add": "tail", "bones": n,
                                 "parent_hint": parent(q, "head"),
                                 "options": {"tail_count": n, "tail_side": _side_suffix(q.get("side"))}})
            continue
        if kind == "arm" or (kind == "wing" and probe.get("wings_ok") is True and preset in ARM_PRESETS):
            opts = dict(fingers)
            if kind == "wing":
                opts["arm_wings"] = True
            side = q.get("side") if q.get("side") in ("l", "r") else "l"
            p.chains.append(_arm_chain(q["id"], kind, side, bool(q.get("found")), None, arm_sides, opts,
                                       parent(q, chest)))
            continue
        if kind == "wing":                        # wings on an arm copy only where the probe allows it and
            n = q["bones"] or 3                   # the rig has an arm to copy: else a 3-bone chain
            p.chains.append({**base, "limb": "tail_dupli", "add": "tail", "bones": n,
                             "parent_hint": parent(q, chest),
                             "options": {"tail_count": n, "tail_side": _side_suffix(q.get("side"))}})
            continue
        if motion == "swings":
            n = q["bones"] or _swing_bones(kind, arc, r)
        else:
            n = q["bones"] or (chain_bones(arc, r, cap, bend=poly) if arc and r else 4)
            if cap is not None:
                n = min(n, max(1, int(cap)))
        if q["id"] == first_tail:
            p.chains.append({**base, "limb": "tail", "add": None if "tail" in own_limbs else "tail", "bones": n,
                             "parent_hint": parent(q, "pelvis"),
                             "options": {"tail_count": n, "tail_name": "tail"}})
        elif motion == "swings":
            p.chains.append({**base, "limb": "tail_dupli", "add": "tail", "bones": n,
                             "parent_hint": parent(q), "options": {"tail_count": n,
                                                                   "tail_side": _side_suffix(q.get("side"))}})
            continue
        elif kind in ("trunk", "tentacle") or (kind == "tail" and tname == "serpent"):
            p.chains.append({**base, "limb": "spline_ik", "add": "spline_ik", "bones": max(n, 2),
                             "parent_hint": parent(q, "pelvis" if kind == "tail" else None),
                             "options": {"spline_count": max(n, 2), "spline_bendy": 0, "spline_deform": True,
                                         "spline_name": _limb_name(q["id"]),
                                         "spline_side": _side_suffix(q.get("side"))}})
        else:
            p.chains.append({**base, "limb": "tail_dupli", "add": "tail", "bones": n,
                             "parent_hint": parent(q, "pelvis" if kind == "tail" else None),
                             "options": {"tail_count": n, "tail_side": _side_suffix(q.get("side"))}})
        if kind == "tail" and _tuft(q, app):
            p.rigid_regions.append({"region": "tuft", "part": q["id"], "bone": "last", "owner_hint": q["id"]})
    if probe.get("wings_ok") is True and preset not in ARM_PRESETS and any(c["kind"] == "wing" for c in p.chains):
        p.notes.append("this rig has no arms to copy for the wings: each wing gets a 3-bone chain")
    for rid in sorted(regions - known):            # clicked regions ("Click a part that must not bend")
        if rid in BODY_RIGID:
            continue
        p.rigid.append({"part": rid, "owner_hint": "root" if tname == "custom" else None})
    # hooves and claws: stiff on the hand or foot bone they sit on (spec 5.1)
    for region, where in (("hooves", [w for w, v in (("hand", hands), ("foot", feet)) if v == "hooves"]),
                          ("claws", ["hand"] if hands == "claws" else [])):
        if region in regions and where:
            p.rigid_regions.append({"region": region, "where": where, "owner_hint": None})

    # ---- cloth and hair (lead's choice: they move with the body unless told otherwise)
    for _pid, c in sorted(cloth.items()):
        if c.get("motion") == "physics_later":
            p.cloth_masks.append(c["part"])
        elif c.get("motion") == "swings":
            p.chains += _cloth_chains(c, apps_by.get(str(c.get("app") or c["part"])), cap)

    # ---- limbs the starting rig has and this body lacks
    p.remove_limbs = _remove_limbs(p.chains, own_limbs)
    for _ref, limb, side in p.remove_limbs:
        p.notes.append("no tail that moves: the rig's own tail is removed" if limb == "tail" else
                       f"no {'left' if side == '.l' else 'right'} ear: that ear of the rig is removed")

    # ---- counts and limb options
    ear_n = max((c["bones"] for c in p.chains if c["limb"] == "ears"), default=None)
    tail_n = next((c["bones"] for c in p.chains if c["limb"] == "tail"), None)
    p.counts = {"spine": spine_n, "neck": neck_count(neck_len, neck_thick) if has_head else None,
                "tail": tail_n, "ear": ear_n}

    # ---- props: sockets, swinging chains, or skin that follows the body
    rig = _rig_bones(preset, p.add_limbs, arm_sides, spine_n)
    for pr in sorted((pr for pr in brief.get("props", []) or [] if isinstance(pr, dict) and pr.get("part") is not None),
                     key=lambda pr: str(pr["part"])):
        role = pr.get("role", "bends")
        if not _is_option(role, PROP_ROLES):
            role = "bends"
        if role == "bends":
            p.skinned_props.append(pr["part"])
        elif role == "swings":
            p.chains.append({"part": pr["part"], "kind": "prop", "side": "x", "found": True, "limb": "tail_dupli",
                             "add": "tail", "bones": 2, "parent_hint": None,
                             "options": {"tail_count": 2, "tail_side": ".x"}})
        else:
            sock, note = _socket(pr, role, rig)
            p.sockets.append(sock)
            if note:
                p.notes.append(f"{pr.get('words') or pr['part']}: {note}")
    _unique_names(p.chains)

    p.export_type = export_rig_type(p, value(brief, "export"))
    if preset == "human" and feet == "heel_raised":
        if p.export_type == "HUMANOID":
            p.ankle_at_hock = True
            p.notes.append("heel raised: two-bone legs with the ankle at the hock, for human animations")
        else:
            p.required += ["thigh_b_l", "thigh_b_r"]
    p.limb_options = _limb_options(p, t, hands, feet, fingers, toe_changes(feet, value(brief, "toes")))
    p.face, head_changes, face_note = _face(brief)
    if face_note:
        p.notes.append(face_note)
    if has_head:
        p.limb_options.append(("head_ref.x", "head", ".x", head_changes))

    # ---- binding and export
    build = value(brief, "build")
    moves = value(brief, "moves_like")
    p.rigid_pieces = moves == "machine"
    if p.rigid_pieces:
        p.bind_engine = "RIGID"                   # each loose piece follows one bone, no heat (spec 9.8)
    elif build in ("heavy", "round") and hands not in DIGIT_HANDS:
        # Spec 9.8 names Fingers only. Claws and mittens get finger bones too (finger_changes),
        # which voxels blur the same way, so they keep the heat bind as well.
        p.bind_engine = "PSEUDO_VOXELS"
    else:
        p.bind_engine = "HEAT_MAP"
    if moves == "both":
        p.loose_rigid = True
        p.notes.append("a living body with machine parts: each loose piece that does not touch the skin "
                       "follows one bone; the body binds as usual")
    engines = targets.get("engines") or ([targets["engine"]] if targets.get("engine") else [])
    known_engines = [ENGINE_INFLUENCES[str(e).lower()] for e in engines if str(e).lower() in ENGINE_INFLUENCES]
    p.max_influences = min(known_engines) if known_engines else 4
    return p


ARM_PRESETS = ("human", "bird")       # the rigs with arms of their own (a bird's wings are its arms)


def _arm_chain(pid, kind: str, side: str, found: bool, row, arm_sides: set, options: dict, parent_hint) -> dict:
    """An arm for a part (or a placeholder waiting for its points): a copy of the rig's arm on that
    side when there is one, else Auto-Rig Pro's first arm on that side (four legs, a snake, other
    bodies). Either way it is added with add_limb 'arm.l' / 'arm.r'."""
    limb = "arm_dupli" if side in arm_sides else "arm"
    arm_sides.add(side)
    return {"part": pid, "kind": kind, "side": side, "found": found, "limb": limb, "add": f"arm.{side}",
            "bones": 3, "parent_hint": parent_hint, "row": row, "options": dict(options)}


def _swing_bones(kind: str, arc, r) -> int:
    """Bones for a swinging part (spec 5.5): 1-2 from its length over its thickness; a mane or a
    hair tuft, or a part of unknown size, 2."""
    if kind in ("mane", "hair") or not (arc and r):
        return 2
    return min(max(int(math.floor(arc / (BONE_LEN * r) + 0.5 + 1e-9)), 1), 2)


def _ear_n(q: dict, app: dict | None) -> int:
    """An ear's bones: the director's count, else ear_bones for a bending ear, 1-2 for a swinging one."""
    if q.get("bones"):
        return int(q["bones"])
    if q.get("motion") == "swings":
        arc, r, _poly = _size(q, app)
        return _swing_bones("ear", arc, r)
    return ear_bones(q, app)


def _rig_bones(preset: str, add_limbs, arm_sides, spine_n=None) -> dict:
    """Which owner bones a rig has: arms on a side (its own, or added), legs, front legs (four
    legs), a head and neck, a spine (hips and chest), and the chest bone's name."""
    spine = preset != "free" or "spine" in add_limbs
    return {"arms": ({"l", "r"} if preset in ARM_PRESETS else set()) | set(arm_sides),
            "legs": preset in ("human", "bird", "dog", "horse"), "front_legs": preset in ("dog", "horse"),
            "head": preset != "free" or "head" in add_limbs, "spine": spine,
            "chest": f"spine_{int(spine_n or 2):02d}.x"}


SIDE_WORDS = {"l": "left", "r": "right"}


def _owner_bone(role: str, rig: dict) -> tuple:
    """(owner bone, note) for a prop role on this rig (spec 9.6). A role whose bone the rig lacks
    goes to the nearest bone it has: on four legs a hand is the front foot and a wrist the front
    leg; otherwise the chest, or the root on a rig with no spine. The note says so in plain words
    ('' when the role's own bone is there)."""
    side = role[-1] if role[-2:] in ("_l", "_r") else None
    if role in ("hand_l", "hand_r"):
        if side in rig["arms"]:
            return f"hand.{side}", ""
        if rig["front_legs"]:
            return f"foot_dupli_001.{side}", f"no {SIDE_WORDS[side]} hand: it goes on the {SIDE_WORDS[side]} front foot"
        want = f"{SIDE_WORDS[side]} hand"
    elif role in ("wrist_l", "wrist_r"):
        if side in rig["arms"]:
            return f"forearm.{side}", ""
        if rig["front_legs"]:
            return f"leg_dupli_001.{side}", f"no {SIDE_WORDS[side]} wrist: it goes on the {SIDE_WORDS[side]} front leg"
        want = f"{SIDE_WORDS[side]} wrist"
    elif role in ("ankle_l", "ankle_r"):
        if rig["legs"]:
            return f"leg.{side}", ""
        want = f"{SIDE_WORDS[side]} ankle"
    elif role in ("head", "neck"):
        if rig["head"]:
            return OWNER_BONES[role], ""
        want = role
    elif role == "hips":
        if rig["spine"]:
            return OWNER_BONES["hips"], ""
        want = "hips"
    else:                                         # chest or back: the top spine bone
        if rig["spine"]:
            return rig["chest"], ""
        want = "chest"
    if rig["spine"]:
        return rig["chest"], f"no {want} on this body: it follows the chest"
    return "root", f"no {want} on this body: it follows the whole body"


def _owner_bones(pr: dict, role: str, rig: dict) -> tuple:
    """(owner, other hand or None, note) for a prop: held in both hands, the leading hand owns it
    (asked once) and the other is noted for the manifest."""
    if role != "both_hands":
        owner, note = _owner_bone(role, rig)
        return owner, None, note
    lead = "hand_l" if pr.get("lead") in ("l", "hand_l") else "hand_r"
    owner, note = _owner_bone(lead, rig)
    other, note2 = _owner_bone("hand_l" if lead == "hand_r" else "hand_r", rig)
    return owner, other, note or note2


BODY_RIGID = ("hooves", "claws")
TUFT = 1.5            # a tail end loop wider than this many times the tail's radius is a tuft


def _tuft(part: dict, app: dict | None) -> bool:
    """A tail tuft: the end loop wider than 1.5 times the tail's mean radius (spec 5.5). It stays
    stiff on the last tail bone. Needs the end loop's radius ('end_radius') from the finder."""
    end = (app or {}).get("end_radius") or part.get("end_radius")
    _arc, r, _poly = _size(part, app)
    return bool(end and r and float(end) / r > TUFT + EPS)


def _remove_limbs(chains: list, own_limbs: tuple) -> list:
    """[(ref_bone, limb_type, side)] for limbs the starting rig would have that nothing bends in:
    the dog or horse rig's own tail with no tail chain, and an ear side with no ear (Auto-Rig
    Pro's ears limb always comes as a pair, so one ear drops the other side)."""
    out = []
    if "tail" in own_limbs and not any(c["limb"] == "tail" for c in chains):
        out.append(("tail_00_ref.x", "tail", ".x"))
    sides = {c["side"] for c in chains if c["limb"] == "ears"}
    if sides or "ears" in own_limbs:
        keep = (sides & {"l", "r"}) or ({"l"} if sides else set())    # a lone ear on the middle uses the left one
        out += [(f"ear_01_ref.{s}", "ear", f".{s}") for s in ("l", "r") if s not in keep]
    return out


def _wing_arms(parts: list) -> set:
    """A bird's wings that are its arms: the first left and first right wing by name."""
    wings = sorted((q for q in parts if q["kind"] == "wing"), key=lambda q: str(q["id"]))
    out = set()
    for side in ("l", "r"):
        w = next((q for q in wings if q.get("side") == side), None)
        if w is not None:
            out.add(w["id"])
    return out


def _ear_pair(ears: list) -> set:
    """The ears Auto-Rig Pro's one ears limb takes: the first left and first right by name (a
    lone ear still uses the limb). Every other ear becomes a tail copy hung from the head,
    because human-animation export refuses more than two ear sides."""
    out = set()
    for side in ("l", "r"):
        e = next((q for q in sorted(ears, key=lambda q: q["id"]) if q.get("side") == side), None)
        if e is not None:
            out.add(e["id"])
    if not out and ears:
        out.add(sorted(ears, key=lambda q: q["id"])[0]["id"])
    return out


CLOTH_STRIPS = 3.0    # cape chains = clamp(round(3 x width / length), 1, 3)
CLOTH_RADIUS = 0.25   # a strip's radius for chain_bones: a quarter of its width


def _cloth_chains(c: dict, app: dict | None, cap) -> list:
    """Swinging cloth (spec 9.7): a skirt becomes Auto-Rig Pro's kilt; a cape or long hair gets
    1-3 chains across its width (count = clamp(round(3 x width / length), 1, 3)), each a smooth
    curve whose bones come from chain_bones on its length, with a quarter of its strip's width
    as the radius: a sheet bends more easily than a tube as wide, so it gets twice the bones."""
    if c.get("kind") == "skirt":
        return [{"part": c["part"], "kind": "skirt", "side": "x", "found": True, "limb": "kilt", "add": "kilt",
                 "bones": 0, "parent_hint": "pelvis", "options": {}}]
    src = app or {}
    width, length = c.get("width") or src.get("width"), c.get("length") or src.get("length")
    k = min(max(int(math.floor(CLOTH_STRIPS * width / length + 0.5 + 1e-9)), 1), 3) if width and length else 1
    sides = {1: ("x",), 2: ("l", "r"), 3: ("l", "x", "r")}[k]
    n = chain_bones(length, CLOTH_RADIUS * width / k, cap) if width and length else 4
    return [{"part": c["part"], "kind": c.get("kind", "other"), "side": s, "found": True, "limb": "spline_ik",
             "add": "spline_ik", "bones": max(n, 2), "parent_hint": "spine_02", "strip": i, "of": k,
             "options": {"spline_count": max(n, 2), "spline_bendy": 0, "spline_deform": True,
                         "spline_name": _limb_name(f"{c['part']}_{i + 1}"), "spline_side": _side_suffix(s)}}
            for i, s in enumerate(sides)]


def _socket(pr: dict, role: str, rig: dict) -> tuple:
    """(socket, note): the prop's socket on the bone its role names on this rig (_owner_bones),
    and a plain note when the rig has no such bone and a nearer one is used."""
    owner, other, note = _owner_bones(pr, role, rig)
    out = {"prop": pr["part"], "role": role, "owner": owner, "detachable": bool(pr.get("detachable")),
           "socket": "cc_socket_" + re.sub(r"[^A-Za-z0-9_]", "_", str(pr["part"]))}
    if other:
        out["other_hand"] = other
    return out, note


def _limb_options(p: RigPlan, t: dict, hands: str, feet: str, fingers: dict, toes: dict) -> list:
    """[(ref_bone, limb_type, side, changes)] in a fixed order: arms, legs, spine, neck. Names are
    Auto-Rig Pro's defaults for its rigs; for the other rigs WP6 finds them on the appended
    armature."""
    out = []
    if p.preset == "human":
        for s in ("l", "r"):
            out.append((f"arm_ref.{s}", "arm", f".{s}", dict(fingers)))
    legs = []
    if p.preset in ("human", "bird"):
        legs = [("thigh_ref", "")]
    elif p.preset in ("dog", "horse"):
        legs = [("thigh_ref", ""), ("thigh_ref", "_dupli_001")]       # back legs, then the front leg copies
    three = p.preset == "human" and feet == "heel_raised" and p.export_type == "UNIVERSAL"
    for ref, dup in legs:
        for s in ("l", "r"):
            ch = dict(toes)
            if three:
                ch["three_bones_leg"] = True
            if ch:
                out.append((f"{ref}{dup}.{s}", "leg", f"{dup}.{s}", ch))
    if p.counts.get("spine") is not None:
        out.append(("root_ref.x", "spine", ".x", {"spine_count": int(p.counts["spine"])}))
    if p.counts.get("neck") is not None:
        out.append(("neck_ref.x", "neck", ".x", {"neck_count": max(1, int(p.counts["neck"]))}))
    return out


def _face(brief: dict) -> tuple:
    """(face mode, head limb changes, note). Head moves as one: no face bones. Jaw: only the
    mouth (teeth and tongue when they are separate parts). Full face only when the eyes are
    separate parts and the mouth is cut; otherwise the jaw (mouth cut) or the head as one."""
    face = value(brief, "face")
    m = brief.get("measured") or {}
    mouth, eyes = bool(m.get("mouth_open")), bool(m.get("eyes_separate"))
    note = ""
    if face == "full" and not (mouth and eyes):
        face = "jaw" if mouth else "head_one"
        note = ("full face needs separate eyes and a cut mouth: " +
                ("the jaw opens instead" if mouth else "the head moves as one instead"))
    if face == "head_one":
        return face, {"facial": False}, note
    if face == "jaw":
        # facial option names from the Auto-Rig Pro probe (EXPECTED_LIMB_OPTIONS); WP0 confirms them
        return face, {"facial": True, "facial_mouth": True, "facial_eye_l": False, "facial_eye_r": False,
                      "facial_eyebrow_l": False, "facial_eyebrow_r": False, "facial_noses": False,
                      "facial_cheeks": False, "facial_chins": False,
                      "facial_teeth": bool(m.get("teeth_separate")),
                      "facial_tongue": bool(m.get("tongue_separate"))}, note
    return face, {"facial": True}, note


def export_rig_type(plan_: RigPlan, director_choice: str | None = None) -> str:
    """HUMANOID only when all of these hold (Auto-Rig Pro's own humanoid check, spec 9.9): a person,
    an animal on two legs or more than two arms; the director did not choose the creature
    skeleton; no three-bone legs; at most one ears limb (two ear sides); one head and one spine
    with at least one spine bone. (The human rig has one pair of legs and Forge adds no leg
    copies to it, so Auto-Rig Pro's "at most two leg sides" holds.) Otherwise UNIVERSAL."""
    t = BP.TEMPLATES[plan_.template]
    if plan_.template not in BP.HUMANOID_TEMPLATES or director_choice == "creature":
        return "UNIVERSAL"
    if t["three_bone_legs"] or plan_.preset != "human":
        return "UNIVERSAL"
    if any(o[3].get("three_bones_leg") for o in plan_.limb_options):
        return "UNIVERSAL"
    ear_sides = sorted({c["side"] for c in plan_.chains if c["limb"] == "ears"})
    if len(ear_sides) > 2:
        return "UNIVERSAL"
    if plan_.add_limbs.count("head") + 1 > 1 or plan_.add_limbs.count("spine") + 1 > 1:
        return "UNIVERSAL"
    if plan_.counts.get("spine") is not None and int(plan_.counts["spine"]) < 1:
        return "UNIVERSAL"
    return "HUMANOID"
