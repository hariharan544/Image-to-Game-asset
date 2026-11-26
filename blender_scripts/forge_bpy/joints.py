"""Guess skeleton joints from a T-pose body mesh (no source skeleton needed).

Assumes the Forge assemble convention: feet on Z=0, centred on X=0 (the character's
left is +X), arms straight out along X. Works on slices of the vertex cloud, so it
copes with cartoon proportions (big head, short legs, large hands). The result is a
first guess the director checks (and can move) before the rig is built.

Returns {joint_key: (head Vector, tail Vector)} with the keys arp_rig.ref_targets uses.
"""

from __future__ import annotations

import numpy as np
from mathutils import Vector

FINGERS = ("thumb", "index", "middle", "ring", "pinky")


def _verts(obj) -> np.ndarray:
    me = obj.data
    co = np.empty(len(me.vertices) * 3, np.float32)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3).astype(np.float64)
    m = np.array(obj.matrix_world)
    return co @ m[:3, :3].T + m[:3, 3]


def _centre(v: np.ndarray, fallback) -> np.ndarray:
    return v.mean(axis=0) if len(v) else np.asarray(fallback, float)


def estimate(obj) -> dict:
    return estimate_points(_verts(obj))


def estimate_points(V: np.ndarray) -> dict:
    g, top = V[:, 2].min(), V[:, 2].max()
    H = max(top - g, 1e-6)
    ax = np.abs(V[:, 0])
    max_x = ax.max()

    # ---- arms: the vertices far out on X are arm / hand
    arm_pts = V[ax > 0.6 * max_x]
    arm_z = float(np.median(arm_pts[:, 2]))
    arm_half = max(float(np.percentile(arm_pts[:, 2], 95) - np.percentile(arm_pts[:, 2], 5)) / 2, 0.01 * H)

    # ---- torso width just below the arms
    band = V[(V[:, 2] > arm_z - 0.12 * H) & (V[:, 2] < arm_z - 0.04 * H)]
    torso_w = float(np.percentile(np.abs(band[:, 0]), 98)) if len(band) else 0.3 * max_x
    torso_w = min(torso_w, 0.6 * max_x)
    torso_y = float(np.median(V[np.abs(V[:, 0]) < 0.5 * torso_w][:, 1]))

    # front: the side the toes stick out (the character normally faces -Y)
    feet = V[V[:, 2] < g + 0.04 * H]
    if len(feet):
        fy = feet[:, 1]
        front = -1.0 if (torso_y - fy.min()) >= (fy.max() - torso_y) else 1.0
    else:
        front = -1.0

    J: dict = {}
    for s, sign in (("l", 1.0), ("r", -1.0)):
        side = V[V[:, 0] * sign > 0]
        sx = np.abs(side[:, 0])
        near_arm = np.abs(side[:, 2] - arm_z) < max(1.5 * arm_half, 0.04 * H)

        def arm_centre(x, width):
            sel = side[near_arm & (np.abs(sx - x) < width)]
            c = _centre(sel, (x * sign, torso_y, arm_z))
            # inside the torso the slice is mostly chest: keep the arm's centre line height
            return Vector((x * sign, c[1], arm_z if x <= 1.05 * torso_w else c[2]))

        shoulder_x = 0.9 * torso_w
        L = max(max_x - shoulder_x, 1e-6)
        # wrist = thinnest point of the outer arm (where the hand starts); straight tube -> 80%
        bins = np.linspace(shoulder_x + 0.45 * L, max_x - 0.1 * L, 14)
        step = (bins[1] - bins[0]) if len(bins) > 1 else 0.05 * L
        thick = []
        for x in bins:
            sel = side[near_arm & (np.abs(sx - x) < step)]
            thick.append(np.ptp(sel[:, 2]) if len(sel) > 2 else np.inf)
        thick = np.array(thick)
        finite = thick[np.isfinite(thick)]
        if len(finite) and finite.min() < 0.85 * np.median(finite):
            wrist_x = float(bins[int(np.argmin(thick))])
        else:
            wrist_x = shoulder_x + 0.8 * L
        elbow_x = shoulder_x + 0.5 * (wrist_x - shoulder_x)
        w = 0.03 * L
        sh, el, wr = arm_centre(shoulder_x, w), arm_centre(elbow_x, w), arm_centre(wrist_x, w)
        tip = arm_centre(max_x - 0.02 * L, w)
        tip.x = max_x * sign
        clav = Vector((0.25 * torso_w * sign, sh.y, sh.z))
        J[f"clavicle_{s}"] = (clav, sh.copy())
        J[f"upperarm_{s}"] = (sh, el.copy())
        J[f"lowerarm_{s}"] = (el, wr.copy())
        J[f"hand_{s}"] = (wr, tip)

        # fingers: spread across the hand's depth, thumb towards the front
        hand = side[near_arm & (sx > wrist_x)]
        if len(hand) > 4:
            y0, y1 = hand[:, 1].min(), hand[:, 1].max()
            hz = float(np.median(hand[:, 2]))
        else:
            y0, y1, hz = wr.y - 0.05 * L, wr.y + 0.05 * L, wr.z
        hl = max(max_x - wrist_x, 1e-6)
        for i, f in enumerate(FINGERS):
            if f == "thumb":
                ty = (y0 if front < 0 else y1)
                base = Vector(((wrist_x + 0.25 * hl) * sign, wr.y + (ty - wr.y) * 0.6, hz))
                end = Vector(((wrist_x + 0.55 * hl) * sign, ty, hz))
            else:
                k = (i - 1) / 3.0                       # 0 .. 1 across the hand
                if front > 0:
                    k = 1.0 - k
                fy = y0 + (y1 - y0) * (0.25 + 0.65 * k)
                base = Vector(((wrist_x + 0.45 * hl) * sign, fy, hz))
                end = Vector((max_x * sign, fy, hz))
            seg = (end - base) / 3.0
            for n in (1, 2, 3):
                J[f"{f}{n}_{s}"] = (base + seg * (n - 1), base + seg * n)

    # ---- legs: crotch = lowest torso point on the centre line (front half: the tail hangs behind)
    centre_line = V[(np.abs(V[:, 0]) < 0.12 * torso_w) & ((V[:, 1] - torso_y) * front >= -0.02 * H)
                    & (V[:, 2] > g + 0.02 * H)]
    crotch = float(centre_line[:, 2].min()) if len(centre_line) else g + 0.45 * H
    crotch = min(crotch, arm_z - 0.1 * H)
    hip_z = crotch + 0.04 * (crotch - g)
    leg_band = V[(V[:, 2] > g + 0.2 * (crotch - g)) & (V[:, 2] < g + 0.6 * (crotch - g))]
    for s, sign in (("l", 1.0), ("r", -1.0)):
        leg = leg_band[leg_band[:, 0] * sign > 0.12 * torso_w]
        leg_x = float(np.median(np.abs(leg[:, 0]))) if len(leg) else 0.5 * torso_w
        side = V[(V[:, 0] * sign > 0) & (np.abs(np.abs(V[:, 0]) - leg_x) < 0.5 * leg_x + 1e-6)]

        def leg_point(z):
            sel = side[np.abs(side[:, 2] - z) < 0.03 * H]
            c = _centre(sel, (leg_x * sign, torso_y, z))
            return Vector((leg_x * sign, c[1], z))

        hip = leg_point(hip_z)
        knee = leg_point(g + 0.5 * (hip_z - g))
        ankle = leg_point(g + 0.1 * (hip_z - g))
        foot = side[side[:, 2] < ankle.z]
        toe_y = (foot[:, 1].min() if front < 0 else foot[:, 1].max()) if len(foot) else ankle.y + front * 0.1 * H
        ball = Vector((ankle.x, ankle.y + 0.6 * (toe_y - ankle.y), g + 0.03 * H))
        toe = Vector((ankle.x, toe_y, g + 0.03 * H))
        J[f"thigh_{s}"] = (hip, knee.copy())
        J[f"calf_{s}"] = (knee, ankle.copy())
        J[f"foot_{s}"] = (ankle, ball.copy())
        J[f"ball_{s}"] = (ball, toe)

    # ---- spine, neck, head (head top measured on the centre line: horns stick out sideways)
    def mid_y(z):
        sel = V[(np.abs(V[:, 2] - z) < 0.03 * H) & (np.abs(V[:, 0]) < 0.5 * torso_w)]
        return float(np.median(sel[:, 1])) if len(sel) else torso_y

    centre = V[np.abs(V[:, 0]) < 0.3 * torso_w]
    head_top = float(centre[:, 2].max()) if len(centre) else top
    zs = np.linspace(arm_z, arm_z + 0.5 * (head_top - arm_z), 12)
    widths = []
    for z in zs:
        sel = V[np.abs(V[:, 2] - z) < 0.02 * H]
        widths.append(np.percentile(np.abs(sel[:, 0]), 98) if len(sel) else np.inf)
    widths = np.array(widths)
    neck_z = float(zs[int(np.argmin(widths))]) if widths.min() < 0.8 * torso_w else arm_z + 0.2 * (head_top - arm_z)
    neck_z = max(neck_z, arm_z + 0.02 * H)
    head_z = neck_z + 0.3 * (head_top - neck_z)
    pelvis = Vector((0.0, mid_y(hip_z), hip_z))
    neck = Vector((0.0, mid_y(neck_z), neck_z))
    head = Vector((0.0, mid_y(head_z), head_z))
    J["pelvis"] = (pelvis, pelvis.lerp(neck, 0.15))
    J["neck"] = (neck, head.copy())
    J["head"] = (head, Vector((head.x, head.y, head_top)))
    J["_spine"] = []
    J["_front"] = front
    return J
