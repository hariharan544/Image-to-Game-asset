"""The rig brief: what the character is, as the Step 8 card "About your character" shows it
(spec 4.1 and 5.1-5.5).

Forge fills the card from several sources: the director's own answers, Step 1, Step 2's props,
the job, measurements of the mesh, Tripo, an optional AI read of the concept image, and the
body plan's defaults. merge() picks one value per row, by a fixed precedence, and marks the rows
the director should look at: yellow when Forge is unsure, red when two sources disagree.

plan() turns a brief into a RigPlan: which Auto-Rig Pro rig to start from, which limb options
change (fingers, toes, neck, spine), which chains the extra parts get, which parts stay stiff,
where props attach, how the skin is bound and how the rig is exported. Every count in it comes
from ratios (a tail's length to its thickness, a neck's length to its thickness), so the same
character gives the same plan at any scale.

Plain Python: no Blender. (Part names are read with appendages.plain_name, so the card and
the panel word them the same way.)
"""

from __future__ import annotations

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

MOTIONS = (("stiff", "Stiff"), ("bends", "Bends"), ("swings", "Swings"), ("not_part", "Not a part"))
# kind, card words, plural, how it moves by default (spec 5.5). In body order, from the head
# down: the card lists the parts and the one-line summary counts them in this order.
PART_KINDS = (
    ("horn", "Horn", "horns", "stiff"),
    ("antler", "Antler", "antlers", "stiff"),
    ("ear", "Ear", "ears", "bends"),
    ("muzzle", "Muzzle", "muzzles", "stiff"),         # part of the head: no bones of its own
    ("beak", "Beak", "beaks", "stiff"),
    ("hair", "Hair tuft", "hair tufts", "stiff"),
    ("mane", "Mane", "manes", "stiff"),
    ("trunk", "Trunk", "trunks", "bends"),
    ("arm", "Extra arm", "extra arms", "bends"),
    ("wing", "Wing", "wings", "bends"),
    ("fin", "Fin", "fins", "swings"),
    ("spike", "Spike", "spikes", "stiff"),
    ("plate", "Armour plate", "armour plates", "stiff"),
    ("hanging", "Hanging piece (bell, pouch, earring)", "hanging pieces", "swings"),
    ("tail", "Tail", "tails", "bends"),
    ("tentacle", "Tentacle", "tentacles", "bends"),
    ("other", "Other", "other parts", "stiff"),
)
KIND_WORDS = {k: w for k, w, _p, _m in PART_KINDS}
KIND_PLURAL = {k: p for k, _w, p, _m in PART_KINDS}
KIND_MOTION = {k: m for k, _w, _p, m in PART_KINDS}
KIND_RANK = {k: i for i, (k, _w, _p, _m) in enumerate(PART_KINDS)}
# the kinds appendages.find gives today, and other names, as card kinds
KIND_ALIASES = {"snout": "muzzle", "head_extra": "other", "back_extra": "other", "extra": "other",
                "tuft": "hair", "antlers": "antler", "spikes": "spike", "pauldron": "plate", "armour": "plate"}
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


def _side_of(pid: str) -> str:
    """'l', 'r' or 'x' from a part name ('horn_l', 'ear_r2', 'extra_l3'; anything else is the middle)."""
    m = re.search(r"_([lr])\d*$", str(pid))
    return m.group(1) if m else "x"


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


def _clean(name: str, value):
    """The value as the field's type, or None when it is not a valid answer for that field."""
    spec = FIELDS[name]
    if value is None:
        return None
    try:
        if spec["type"] == "enum":
            return value if value in dict(spec["options"]) else None
        if spec["type"] == "bool":
            return bool(value) if isinstance(value, bool) or value in (0, 1) else None
        v = int(value) if spec["type"] == "int" else float(value)
    except (TypeError, ValueError):
        return None
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
    is not from you or Step 1 and sure < 0.8, "red" when two sources at least 0.5 sure disagree
    (with "options": the two answers [value, words], and a one-line "reason"), else "ok".
    Answers that are not valid for their field are left out and listed in "ignored"."""
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
    parts = _merge_list(layers, "parts", "id", _fill_part)
    rigid_extra = sorted({str(r) for src in SOURCES for r in (layers.get(src) or {}).get("rigid", [])})
    stiff = [p["id"] for p in parts if p["motion"] == "stiff"]
    rigid = stiff + [r for r in rigid_extra if r not in stiff]
    notes = next((str((layers.get(s) or {}).get("notes")) for s in SOURCES if (layers.get(s) or {}).get("notes")), "")
    return {"v": 1, "confirmed": bool(confirmed), "sig": list(sig) if sig is not None else None,
            "fields": fields, "parts": parts,
            "props": _merge_list(layers, "props", "part", _fill_prop),
            "cloth": _merge_list(layers, "cloth", "part", _fill_cloth),
            "rigid": rigid, "notes": notes,
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
    if win["any_of"]:
        # a lower source picks inside what the winner allows (Step 1 "Biped" + the shape's "animal")
        allowed = win["any_of"]
        refined = next((c for c in order[1:] if c["src"] != "default" and c["sure"] >= DISAGREE
                        and c["value"] in allowed), None)
        if refined is not None:
            row = {"value": refined["value"], "src": refined["src"], "sure": refined["sure"],
                   "why": _join_why(refined["why"], win["why"])}
        elif row["value"] not in allowed:
            row["value"] = allowed[0]
    state = "ok"
    if win["src"] != "you" and win["sure"] >= DISAGREE:
        other = next((c for c in order if c is not win and c is not refined and c["src"] != "default"
                      and c["sure"] >= DISAGREE and not any(_same(name, c["value"], a) for a in allowed)), None)
        if other is not None:
            words_a = win["words"] or (" or ".join(_words(name, a) for a in allowed) if win["any_of"]
                                       else _words(name, row["value"]))
            words_b = other["words"] or _words(name, other["value"])
            reason = f"{SAYS[win['src']]} {words_a}; {SAYS[other['src']]} {words_b}"
            if other["why"]:
                reason += f" ({other['why']})"
            row.update(options=[[row["value"], words_a], [other["value"], words_b]],
                       reason=reason[:1].upper() + reason[1:])
            state = "red"
    if state == "ok" and row["src"] not in ("you", "step1") and row["sure"] < STRONG:
        state = "yellow"
    if state == "ok" and FIELDS[name]["unset"] is not None and row["value"] == FIELDS[name]["unset"]:
        state = "yellow"
        row["why"] = row["why"] or "not set"
    row["state"] = state
    return row


def _merge_list(layers: dict, key: str, id_key: str, fill) -> list:
    """Entries of one list (parts, props, cloth) merged by their id: the highest source's keys
    win, keys only a lower source has are kept (Step 4's descriptor, the found part's name)."""
    by_id: dict = {}
    for src in SOURCES:
        for raw in (layers.get(src) or {}).get(key, []) or []:
            if not isinstance(raw, dict) or raw.get(id_key) is None:
                continue
            sure = _sure(src, raw.get("sure"))
            by_id.setdefault(str(raw[id_key]), []).append((_rank(src, sure), SOURCES.index(src), src, sure, raw))
    out = []
    for pid in sorted(by_id):
        entries = sorted(by_id[pid], key=lambda e: (e[0], e[1]))
        merged: dict = {}
        for entry in reversed(entries):
            merged.update({k: v for k, v in entry[4].items() if v is not None})
        src, sure, top = entries[0][2:]
        merged.update({id_key: pid, "src": src, "sure": sure, "why": str(top.get("why") or "")})
        merged["found"] = any(bool(e[4].get("found")) or bool(e[4].get("app")) for e in entries)
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
        out.sort(key=lambda p: (KIND_RANK.get(p["kind"], len(KIND_RANK)), p["id"]))
    return out


def _fill_part(p: dict) -> dict:
    p["kind"] = _norm_kind(p.get("kind"))
    if p.get("motion") not in dict(MOTIONS):
        p["motion"] = KIND_MOTION.get(p["kind"], "stiff")
    p["bones"] = max(0, int(p.get("bones") or 0))         # 0 = auto
    p["side"] = p.get("side") if p.get("side") in ("l", "r", "x") else _side_of(p["id"])
    p["words"] = p.get("words") or part_words(p["id"], p["kind"])
    if p.get("desc") is not None:
        p["desc"] = dict(p["desc"])
    if p.get("step4") is not None:
        p["step4"] = {"row": p["step4"].get("row"), "disposition": p["step4"].get("disposition")}
    return p


def _fill_prop(p: dict) -> dict:
    if p.get("role") not in dict(PROP_ROLES):
        p["role"] = "bends"                       # no role known: the skin follows the body, no socket
    if p.get("detachable") is None:
        p["detachable"] = p["role"] in HELD
    p["words"] = p.get("words") or str(p["part"]).replace("_", " ")
    p.setdefault("grip", None)
    return p


def _fill_cloth(c: dict) -> dict:
    if c.get("motion") not in dict(CLOTH_MOTIONS):
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
    """A field's value, or its default (the body plan's default where it has one)."""
    row = (brief.get("fields") or {}).get(name)
    if isinstance(row, dict) and row.get("value") is not None:
        return row["value"]
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


def summary_words(brief: dict) -> str:
    """The card in one line once it is confirmed, for example
    'Animal on two legs · hooves · 2 horns · 2 ears · tail · no props'."""
    bits = [BP.TEMPLATES[value(brief, "body_plan")]["short"]]
    hands, feet = value(brief, "hands"), value(brief, "feet")
    n = int(value(brief, "fingers"))
    hand_w = {"fingers": f"{n} finger{'s' if n != 1 else ''}", "mitten": "mittens", "hooves": "hooves",
              "paws": "paws", "claws": "claws"}.get(hands)
    feet_w = {"toes": "toes", "paws": "paws", "hooves": "hooves", "heel_raised": "walks on its toes"}.get(feet)
    bits += [w for w in (hand_w, feet_w if feet_w != hand_w else None) if w]
    counts: dict = {}
    for p in brief.get("parts", []):
        if p.get("motion") != "not_part":
            k = _norm_kind(p.get("kind"))
            counts[k] = counts.get(k, 0) + 1
    for k in sorted(counts, key=lambda k: KIND_RANK.get(k, len(KIND_RANK))):
        if k in CLOTH_KINDS:
            continue
        c = counts[k]
        bits.append(KIND_WORDS[k].lower() if c == 1 else f"{c} {KIND_PLURAL[k]}")
    props = len(brief.get("props", []))
    bits.append("no props" if props == 0 else f"{props} prop{'s' if props != 1 else ''}")
    return " · ".join(bits)


# ----------------------------------------------------------------------------- chain bones

BONE_LEN = 2.5        # one chain bone is about 2.5 times the chain's mean radius long
MIN_BONES, BASE_MAX, BEND_MAX = 2, 8, 10
MAX_TURN = 35.0       # a bone may turn at most this much (degrees) from the one before it


def chain_bones(arc_len: float, mean_radius: float, cap=None, bend=None) -> int:
    """Bones for a bending chain (tail, trunk, tentacle): clamp(round(L / 2.5 r), 2, 8).

    With `bend`, the chain's centre line at rest (a polyline of points, root to tip), the count
    is raised while any bone would turn more than 35 degrees from the one before it, up to 10.
    `cap` (the bone budget) has the last word. Only ratios of the sizes count, so the result is
    the same at any scale."""
    if mean_radius and mean_radius > 0 and arc_len and arc_len > 0:
        n = int(math.floor(arc_len / (BONE_LEN * mean_radius) + 0.5 + 1e-9))
    else:
        n = MIN_BONES
    n = min(max(n, MIN_BONES), BASE_MAX)
    if bend is not None and len(bend) >= 3:
        while n < BEND_MAX and max_turn(bend, n) > MAX_TURN:
            n += 1
    if cap is not None:
        n = min(n, max(1, int(cap)))
    return n


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
    """The largest turn (degrees) between neighbouring bones when n bones follow the polyline."""
    pts = [tuple(float(c) for c in p) for p in poly]
    q = _resample(pts, n)
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


def _size(part: dict, app: dict | None) -> tuple:
    """(arc length, mean radius, centre polyline) of a part, from its found item when there is one.
    Any of them is None when unknown."""
    src = app or {}
    poly = src.get("chain") or src.get("path") or part.get("chain")
    arc = src.get("arc_len") or part.get("arc_len")
    if arc is None and poly is not None and len(poly) >= 2:
        arc = _poly_len(poly)
    if arc is None:
        arc = src.get("length") or part.get("length")
    r = src.get("radius") or part.get("radius")
    if r is None:
        thick = src.get("thickness") or src.get("width")
        r = 0.5 * float(thick) if thick else None
    return (float(arc) if arc else None, float(r) if r else None, poly)


def ear_bones(part: dict, app: dict | None) -> int:
    """2 bones; 3 when the ear is longer than 4 times its root width; 1 (it turns as one piece)
    when it is shorter than twice its root thickness (spec 5.5)."""
    src = app or {}
    length = src.get("length") or part.get("length")
    if length is None and src.get("chain"):
        length = _poly_len(src["chain"])
    ring = src.get("ring")
    width = 2.0 * float(ring[2]) if ring is not None and len(ring) > 2 and ring[2] else src.get("width")
    thick = src.get("thickness")
    if length and thick and length < 2.0 * float(thick):
        return 1
    if length and width and length > 4.0 * float(width):
        return 3
    return 2


# ----------------------------------------------------------------------------- the plan (spec 5.5)

@dataclass
class RigPlan:
    """How Step 8 builds the rig. limb_options: [(ref_bone, limb_type, side, changes)] for Auto-Rig
    Pro's limb settings (spec 9.2 changes them safely); chains: one entry per extra part chain;
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
    ankle_at_hock: bool = False                        # heel-raised legs kept two-bone for human animations
    rigid_pieces: bool = False                         # a machine: each loose piece follows one bone, no heat
    cloth_masks: list = field(default_factory=list)    # cloth left for game physics (a mask in the export)
    required: list = field(default_factory=list)       # joints that must exist before the build
    notes: list = field(default_factory=list)          # what the plan chose, in plain words

    def to_json(self) -> dict:
        d = asdict(self)
        d["limb_options"] = [list(o) for o in self.limb_options]
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


def neck_count(length, thickness) -> int:
    """1 bone when the neck is shorter than its thickness, 2 when shorter than twice it, else 3;
    never below 1 (spec 9.3)."""
    if not thickness or thickness <= 0 or length is None:
        return 1
    ratio = float(length) / float(thickness)
    return 1 if ratio < 1.0 else (2 if ratio < 2.0 else 3)


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
    (those break its own bone lookups)."""
    name = re.sub(r"[^A-Za-z0-9_]", "_", str(pid)) or "part"
    for bad in ("head", "root", "neck"):
        name = name.replace(bad, "part")
    return name


def _owner_hint(p: dict) -> str | None:
    host = (p.get("desc") or {}).get("host")
    if host and host not in ("core", "head"):
        return str(host)                          # a part on a part follows that part
    if host == "head" or p["kind"] in HEAD_KINDS:
        return "head"
    if p["kind"] == "mane":
        return "neck"
    return None                                   # the body bone its root grows from (found at build)


def _side_suffix(side: str) -> str:
    return {"l": ".l", "r": ".r"}.get(side, ".x")


def plan(brief: dict, apps=None, J=None, targets=None, probe=None) -> RigPlan:
    """The rig plan for a brief (spec 5.5). apps: appendages.find items (their chains and
    thicknesses size the chains); J: the joint dict (neck and trunk sizes). targets: {"engines":
    ["unity", "unreal"], "chain_cap": n} from the Step 9 budgets. probe: {"bird_ok", "wings_ok"}
    from the WP0 Auto-Rig Pro probe (unknown = allowed for the bird rig, not for wings)."""
    targets, probe = targets or {}, probe or {}
    tname = value(brief, "body_plan")
    t = BP.TEMPLATES[tname]
    hands, feet = value(brief, "hands"), value(brief, "feet")
    apps_by = {str(a["name"]): a for a in (apps or []) if a.get("name") is not None}
    neck_len, neck_thick = _neck_size(brief, J)
    neck_ratio = neck_len / neck_thick if neck_len is not None and neck_thick else None
    preset, why = BP.choose_preset(tname, hands, feet, neck_ratio, probe.get("bird_ok"))
    if preset == "bird_44":                       # Auto-Rig Pro picks that file itself; Forge never names it
        preset = "bird"
    p = RigPlan(template=tname, preset=preset, add_limbs=list(t["add_limbs"]), required=list(t["required"]))
    if why:
        p.notes.append(why)
    cap = targets.get("chain_cap")

    # ---- extra parts: chains and stiff parts
    rigid_ids = set(str(r) for r in brief.get("rigid", []))
    parts = [q for q in brief.get("parts", []) if q.get("motion") != "not_part"]
    cloth = {str(c["part"]): c for c in brief.get("cloth", [])}
    wing_arms = _wing_arms(parts) if tname == "bird" else set()
    # the dog and horse rigs already have a tail and a pair of ears: those are set, not added
    own_limbs = ("tail", "ears") if preset in ("dog", "horse") else ()
    ears, tails = [], []
    for q in parts:
        stiff = q["motion"] == "stiff" or q["id"] in rigid_ids
        if not stiff and q["kind"] == "ear" and q["motion"] == "bends":
            ears.append(q)
        elif not stiff and q["kind"] == "tail" and q["motion"] == "bends":
            tails.append(q)
    pair = _ear_pair(ears)
    first_tail = tails[0]["id"] if tails and tname != "serpent" else None
    fingers = finger_changes(hands, value(brief, "fingers"), value(brief, "thumb"))
    for q in parts:
        kind, motion, app = q["kind"], q["motion"], apps_by.get(str(q.get("app") or q["id"]))
        base = {"part": q["id"], "kind": kind, "side": q.get("side", "x"), "found": bool(q.get("found")),
                "options": {}}
        if kind in CLOTH_KINDS:
            cloth.setdefault(q["id"], {"part": q["id"], "kind": kind, "app": q.get("app"),
                                       "motion": "swings" if motion == "swings" else "with_body"})
            continue
        if q["id"] in wing_arms:
            continue                              # a bird's wings are its arms
        if motion == "stiff" or q["id"] in rigid_ids:
            p.rigid.append({"part": q["id"], "owner_hint": _owner_hint(q)})
            continue
        arc, r, poly = _size(q, app)
        if kind == "ear" and motion == "bends":
            n = q["bones"] or ear_bones(q, app)
            if q["id"] in pair:
                p.chains.append({**base, "limb": "ears", "add": None if "ears" in own_limbs else "ears",
                                 "bones": n, "parent_hint": "head",
                                 "options": {"ear_count": n}})
            else:                                 # more ears than one pair: tail copies hung from the head
                p.chains.append({**base, "limb": "tail_dupli", "add": "tail", "bones": n, "parent_hint": "head",
                                 "options": {"tail_count": n, "tail_side": _side_suffix(q.get("side"))}})
            continue
        if kind == "arm" or (kind == "wing" and probe.get("wings_ok")):
            opts = dict(fingers)
            if kind == "wing":
                opts["arm_wings"] = True
            side = q.get("side") if q.get("side") in ("l", "r") else "l"
            p.chains.append({**base, "limb": "arm_dupli", "add": f"arm.{side}", "bones": 3,
                             "parent_hint": "spine_02", "options": opts})
            continue
        if kind == "wing":                        # wings on an arm copy only where the probe allows it
            p.chains.append({**base, "limb": "tail_dupli", "add": "tail", "bones": q["bones"] or 3,
                             "parent_hint": "spine_02", "options": {"tail_count": q["bones"] or 3,
                                                                    "tail_side": _side_suffix(q.get("side"))}})
            continue
        if motion == "swings":
            n = q["bones"] or (2 if kind in ("mane", "hair") or not (arc and r)
                               else min(max(int(math.floor(arc / (BONE_LEN * r) + 0.5 + 1e-9)), 1), 2))
            p.chains.append({**base, "limb": "tail_dupli", "add": "tail", "bones": n,
                             "parent_hint": _owner_hint(q), "options": {"tail_count": n, "tail_side": ".x"}})
            continue
        n = q["bones"] or (chain_bones(arc, r, cap, bend=poly) if arc and r else 4)
        if cap is not None:
            n = min(n, max(1, int(cap)))
        if kind in ("trunk", "tentacle") or (kind == "tail" and tname == "serpent"):
            p.chains.append({**base, "limb": "spline_ik", "add": "spline_ik", "bones": max(n, 2),
                             "parent_hint": _owner_hint(q) or ("pelvis" if kind == "tail" else None),
                             "options": {"spline_count": max(n, 2), "spline_bendy": 0, "spline_deform": True,
                                         "spline_name": _limb_name(q["id"]),
                                         "spline_side": _side_suffix(q.get("side"))}})
        elif kind == "tail" and q["id"] == first_tail:
            p.chains.append({**base, "limb": "tail", "add": None if "tail" in own_limbs else "tail", "bones": n,
                             "parent_hint": "pelvis",
                             "options": {"tail_count": n, "tail_name": "tail"}})
        else:
            p.chains.append({**base, "limb": "tail_dupli", "add": "tail", "bones": n,
                             "parent_hint": _owner_hint(q) or ("pelvis" if kind == "tail" else None),
                             "options": {"tail_count": n, "tail_side": _side_suffix(q.get("side"))}})
    known = {q["id"] for q in brief.get("parts", [])}
    for rid in sorted(rigid_ids - known):          # clicked regions ("Click a part that must not bend")
        p.rigid.append({"part": rid, "owner_hint": None})

    # ---- cloth and hair (lead's choice: they move with the body unless told otherwise)
    for _pid, c in sorted(cloth.items()):
        if c.get("motion") == "physics_later":
            p.cloth_masks.append(c["part"])
        elif c.get("motion") == "swings":
            p.chains += _cloth_chains(c, apps_by.get(str(c.get("app") or c["part"])), cap)

    # ---- counts and limb options
    ear_n = max((c["bones"] for c in p.chains if c["limb"] == "ears"), default=None)
    tail_n = next((c["bones"] for c in p.chains if c["limb"] == "tail"), None)
    trunk_len, trunk_thick = _trunk_size(brief, J)
    has_head = preset != "free" or "head" in p.add_limbs
    has_spine = preset != "free" or "spine" in p.add_limbs
    spine_n = None
    if tname == "serpent" and trunk_len and trunk_thick:
        spine_n = chain_bones(trunk_len, 0.5 * trunk_thick, cap)
    elif trunk_len and trunk_thick and trunk_len / trunk_thick > 2.5:
        spine_n = 3
    p.counts = {"spine": spine_n if has_spine else None,
                "neck": neck_count(neck_len, neck_thick) if has_head else None,
                "tail": tail_n, "ear": ear_n}

    # ---- props: sockets, swinging chains, or skin that follows the body
    for pr in sorted(brief.get("props", []), key=lambda pr: str(pr["part"])):
        role = pr.get("role", "bends")
        if role == "bends":
            p.skinned_props.append(pr["part"])
        elif role == "swings":
            p.chains.append({"part": pr["part"], "kind": "prop", "side": "x", "found": True, "limb": "tail_dupli",
                             "add": "tail", "bones": 2, "parent_hint": None,
                             "options": {"tail_count": 2, "tail_side": ".x"}})
        else:
            p.sockets.append(_socket(pr, role, p.counts.get("spine")))

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
    p.bind_engine = "PSEUDO_VOXELS" if build in ("heavy", "round") and hands not in DIGIT_HANDS else "HEAT_MAP"
    p.rigid_pieces = value(brief, "moves_like") == "machine"
    engines = targets.get("engines") or ([targets["engine"]] if targets.get("engine") else [])
    known_engines = [ENGINE_INFLUENCES[e.lower()] for e in engines if str(e).lower() in ENGINE_INFLUENCES]
    p.max_influences = min(known_engines) if known_engines else 4
    return p


def _wing_arms(parts: list) -> set:
    """A bird's wings that are its arms: the first left and first right wing by name."""
    wings = [q for q in parts if q["kind"] == "wing"]
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


def _cloth_chains(c: dict, app: dict | None, cap) -> list:
    """Swinging cloth (spec 9.7): a skirt becomes Auto-Rig Pro's kilt; a cape or long hair gets
    1-3 chains across its width (count = clamp(round(3 x width / length), 1, 3)), each a smooth
    curve whose bones come from chain_bones on its length and half its strip's width."""
    if c.get("kind") == "skirt":
        return [{"part": c["part"], "kind": "skirt", "side": "x", "found": True, "limb": "kilt", "add": "kilt",
                 "bones": 0, "parent_hint": "pelvis", "options": {}}]
    src = app or {}
    width, length = c.get("width") or src.get("width"), c.get("length") or src.get("length")
    k = min(max(int(math.floor(3.0 * width / length + 0.5 + 1e-9)), 1), 3) if width and length else 1
    sides = {1: ("x",), 2: ("l", "r"), 3: ("l", "x", "r")}[k]
    n = chain_bones(length, 0.25 * width / k, cap) if width and length else 4
    return [{"part": c["part"], "kind": c.get("kind", "other"), "side": s, "found": True, "limb": "spline_ik",
             "add": "spline_ik", "bones": max(n, 2), "parent_hint": "spine_02", "strip": i, "of": k,
             "options": {"spline_count": max(n, 2), "spline_bendy": 0, "spline_deform": True,
                         "spline_name": _limb_name(f"{c['part']}_{i + 1}"), "spline_side": _side_suffix(s)}}
            for i, s in enumerate(sides)]


def _socket(pr: dict, role: str, spine_n=None) -> dict:
    if role == "both_hands":
        lead = "hand_l" if pr.get("lead") in ("l", "hand_l") else "hand_r"
        owner, other = OWNER_BONES[lead], OWNER_BONES["hand_l" if lead == "hand_r" else "hand_r"]
    elif role == "chest":                         # the top spine bone (the human rig has spine_01-02)
        owner, other = f"spine_{int(spine_n or 2):02d}.x", None
    else:
        owner, other = OWNER_BONES[role], None
    out = {"prop": pr["part"], "role": role, "owner": owner, "detachable": bool(pr.get("detachable")),
           "socket": "cc_socket_" + re.sub(r"[^A-Za-z0-9_]", "_", str(pr["part"]))}
    if other:
        out["other_hand"] = other
    return out


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
