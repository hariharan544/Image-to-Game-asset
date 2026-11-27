# Forge animation workflow: checking a rigged character before export

Research date: 27 November 2026. Target: Blender 5.3 on Windows, Auto-Rig Pro 3.79, export to Unreal 5 and Unity URP.

## The short version

- **No purchase is needed.** Forge generates its own test clips in Python on the Auto-Rig Pro (ARP) controls. That avoids licence exposure and works for quadrupeds, tails and ears, which downloadable clip libraries do not cover.
- **External clips are optional.** If you supply one (for example from Mixamo), it goes through ARP's Remap tool. Remap has no documented script commands, so that part may stay a guided six-click step.
- **Export uses ARP's documented script commands**, for both engines.
- **This document is a specification to build from.** Nothing here has been run. The joint angles, motion formulas and spring settings are working technical-artist practice, not vendor-verified numbers, and should be tuned on the first real character.

## What is confirmed and what is not

| Item | Status |
|---|---|
| ARP export script commands | Confirmed in the ARP documentation |
| ARP Remap workflow (the clicks) | Confirmed in the ARP documentation |
| ARP Remap script commands | **Not documented.** Forge must look them up inside Blender (`dir(bpy.ops.arp)`) |
| ARP on Blender 5.3 | The store listing says up to 5.2, but November 2026 release notes include 5.3 fixes. Those notes concern glTF export; FBX on 5.3 has no explicit statement |
| Tail and ear control names | **Unverified.** Forge must discover them on the actual rig by name prefix |
| Main control names (`c_traj`, `c_root_master.x`, `c_foot_ik`, `c_hand_ik`, `c_head.x`, `c_spine_*`) | Taken from ARP documentation by the researcher; not independently re-checked. Confirm on the rig |
| ROM angles, walk formulas, spring constants | Practice, not vendor-sourced |

---

## The workflow after rigging

| # | Step | What Forge does | What you see | What you approve |
|---|---|---|---|---|
| 1 | Bind check | Counts unweighted vertices and vertices with more than 4 bone influences (the mobile/Unity limit). Turns Preserve Volume off, because engines use plain linear skinning. | A pass/fail line and a count | Nothing unless it fails |
| 2 | ROM clip | Builds a range-of-motion clip: every joint moved to its limit and back, one axis at a time, on a fixed frame table | The character going through the moves; a contact sheet with one picture per joint; warning marks on frames where the mesh collapses or pokes through itself | "Deformation OK", or mark the bad joints to send back to weights |
| 3 | Sample clips | Builds idle, walk, turn, and for creatures a tail and ear sway, from formulas | Looping playback with the real texture or a checker pattern | "Motion reads correctly" |
| 4 | Follow-through | Runs a spring pass over tail and ear chains and bakes it to keyframes | Tail and ear tips lagging the body | "No clipping, lag looks natural" |
| 5 | External clip (optional) | Retargets a clip you supply through ARP Remap | The clip on your character next to the source | "Feet do not slide, proportions hold" |
| 6 | LOD check | Replays steps 2 and 3 on the 30k and 8k meshes | Side-by-side LODs at the worst frames | "Mobile LOD acceptable" |
| 7 | Export | Writes the animation FBX files for Unreal and Unity through ARP | A list of files written and their settings | Final sign-off |

---

## Step 2 in detail: the ROM clip

**Purpose:** move every deforming joint to its limit and back so each defect shows up at a known frame. The same frame always shows the same joint, so Forge can make contact sheets and compare LODs.

**Timing:** 30 frames per second. Each move takes 24 frames: 10 out, 4 hold, 10 back. The character returns to rest between moves.

### ROM_Biped frame table (frames 0 - 1171, about 39 seconds)

| Frames | Region | Moves (degrees) | What to look for |
|---|---|---|---|
| 0 - 9 | Rest pose hold | - | Reference |
| 10 - 153 | Spine and chest | Forward 45, back 30, side 30 left and right, twist 45 left and right | Belly or back collapse, ribs shearing |
| 154 - 297 | Neck and head | Nod down 40 and up 40, tilt 30 each way, turn 70 each way | Neck pinching, jaw dragging the collar |
| 298 - 393 | Clavicles | Shrug up 30, down 10, forward 20, back 20 | Shoulder line breaking |
| 394 - 537 | Shoulders | Arm forward 90, on up to 170, side 90, side 170, back 40, across chest | Deltoid caving in, armpit crossing, volume loss overhead |
| 538 - 633 | Arm twist | Upper arm +90 and -90, forearm +90 and -90 | "Candy wrapper": mesh pinching to a point at wrist or shoulder |
| 634 - 657 | Elbow | Flex 140 | Volume loss inside, sharp crease outside |
| 658 - 753 | Wrist | Flex 70, extend 70, side 30 each way | Wrist collapse |
| 754 - 825 | Fingers | Fist, splay, thumb oppose | Knuckle collapse, fingers crossing |
| 826 - 945 | Hips | Leg forward 110, back 30, side 60, thigh twist +45 and -45 | Buttock collapse, groin crossing |
| 946 - 969 | Knee | Flex 140 | Kneecap volume, back of knee intersecting |
| 970 - 1017 | Ankle | Up 40, down 50 | Heel and shin crease |
| 1018 - 1041 | Toes | Bend 45 | Toe crease |
| 1042 - 1161 | Combined poses | Deep squat, overhead reach, toe touch, arms crossed, run extreme | Faults that only appear when shoulder and spine move together |
| 1162 - 1171 | Rest pose hold | - | Confirms return to rest |

This is longer than the usual 600 - 900 frame guide because fingers and combined poses are included. A "Quick ROM" option should skip fingers, toes and clavicles.

### ROM_Creature add-on clip (frames 0 - 307)

| Frames | Region | Moves |
|---|---|---|
| 0 - 9 | Rest | - |
| 10 - 129 | Tail | Curl up, down, left, right as a wave from root to tip; twist |
| 130 - 201 | Ears | Forward, back, flop |
| 202 - 225 | Jaw | Open |
| 226 - 249 | Shoulder blades (quadruped) | Slide |
| 250 - 297 | Spine (quadruped) | Arch, hollow |
| 298 - 307 | Rest | - |

### Automatic checks Forge runs on every ROM frame

- **Volume:** flag any joint region that loses more than about 15 - 20 percent of its rest volume.
- **Stretch:** flag the worst edge-stretch ratio per frame.
- **Self-intersection:** count faces poking through other faces.
- **Influences:** unweighted vertices, and vertices with more than 4 bone influences.

All four run on LOD0 and on the 30k and 8k meshes. Fewer edge loops at elbow and knee means worse bending at 8k.

---

## Step 3 in detail: procedural sample clips

**Method.** Forge sets each control's rotation or position per frame and inserts a keyframe on the pose bone. It does not edit animation curves directly, because that part of Blender changed in 4.4 and 5.x and ARP's changelog lists several related breakages. Each clip is its own Action. Forge switches limbs to the mode being keyed: IK feet for walking, FK arms for the ROM.

In the formulas below, `p` is the loop phase: it goes once around a full circle over the length of the clip, so every loop closes exactly.

| Clip | Length at 30 fps | What is keyed |
|---|---|---|
| Idle_Breathe | 120 frames (0 - 120; frame 120 equals frame 0) | Chest pitch 1.5 - 2.5 degrees with the breath; shoulders lift 0.3 degrees slightly late; pelvis drops 0.3 percent of height; head counter-rotates half the chest; a slow side-to-side weight shift of 1 percent of hip width |
| Walk_InPlace | 32 frames (0 - 32) | IK feet on a stance-and-swing path; pelvis bounce, sway, yaw and roll; spine counter-twist; FK arm swing; head stabilised |
| Walk_RootMotion | 32 frames | The same walk, plus the root control `c_traj` moving forward at constant speed |
| Turn_90 | 36 frames (not a loop) | `c_traj` turns 90 degrees over 24 frames; head leads by 4 - 6 frames, chest by 2 - 3; two small steps |
| Quad_Walk / Quad_Trot | 32 frames | The same foot path on four legs. Walk order: left hind 0, left fore 0.25, right hind 0.5, right fore 0.75 of the cycle. Trot: diagonal pairs at 0 and 0.5. Spine side-bend 3 - 5 degrees |
| Tail_Ear_Sway | Layered onto the walk | A travelling wave down the tail; ear bounce at twice the step rate |

**Walk numbers.** Stride length about 0.8 of leg length. Step height 0.1 - 0.15 of leg length. Stance takes 50 - 60 percent of the cycle.
- During stance the foot moves straight back at constant speed. This is what prevents foot sliding.
- During swing it eases forward and lifts in an arc, pitching from +20 degrees at toe-off to -15 at heel strike.
- Pelvis: drops 3 percent of leg length at each contact (two bounces per cycle), sways 2 percent of hip width toward the standing leg, yaws 5 degrees, rolls 3 degrees.
- Spine counter-yaws 0.6 of the pelvis. Arms swing 25 degrees opposite the same-side leg, with the elbow adding 10 degrees slightly late.

**Root-motion speed.** For the feet to stay planted, forward speed must equal stride length divided by (stance fraction times cycle time). I derived this from the stance rule above; the research note's own wording of the formula was unclear.

**Tail wave.** For bone `i` of `n`: yaw = A × (i/n)^0.7 × sin(p − i × 0.4 to 0.6), with A between 10 and 25 degrees. Add a pitch at twice the rate and a quarter of the size.

**Ears.** Pitch 3 - 6 degrees at twice the step rate, delayed along the chain, plus an occasional quick flick.

**Variation.** A light noise layer may be added to the idle only. Never on a loop that must match its first and last frame.

---

## Step 4 in detail: follow-through on tails and ears

There are two routes. Forge should offer the built-in one by default.

1. **Built in (no add-on).** For each chain bone, Forge runs a damped spring that chases the parent's rotation. Stiffness is about 80 - 150, damping about 0.8 × the square root of stiffness. It runs one extra cycle first so the loop closes, then keys the result.
2. **Add-on (free).** Wiggle Bones (`wiggle.bake`) or Jiggle Physics (`armature.jiggle_bake`). Both bake commands were read in the add-ons' source code and are ordinary blocking commands, so Forge can call them. Neither states Blender 5.3 support, and neither has been run. Try both on one tailed character and keep one.

**What to check:** play the walk and the turn. Chain tips must lag the root by a few frames and must never pass through the body.

---

## Step 5 in detail: retargeting an external clip with ARP Remap

The documented steps (ARP Remap documentation):

1. Zero the armature object's location and rotation.
2. Import the FBX with "Automatic Bones Orientations" ticked.
3. Set the Source and Target armatures and press Auto-Scale. Use "In Place" to keep a looping clip on the spot.
4. Press "Build Bones List", then load a preset. The docs say: "if the Source armature is from Mixamo, select the Mixamo preset". Presets cover Mixamo, Rokoko and XSens.
5. Mark the root bone as Root so both movement and rotation transfer. Use IK on feet and hands; the docs contrast "IK feet, no sliding / FK feet, noticeable sliding".
6. If the rest poses differ (A-pose against T-pose), use "Redefine Rest Pose", then "Copy Selected Bones Rotation", then Apply.
7. Press "Re-Target". "Multiple Source Anim" handles several clips at once.

**Scripting.** The Remap page documents no script commands. Forge should look for them at start-up. If they are missing or have changed, the panel shows you the steps above as a checklist instead.

**Free fallback.** The "Retarget" extension (Blender 5.0 and newer, updated August 2026) has an Auto Rig Pro preset. Its commands are also undocumented.

**Limit.** Mixamo and the other libraries are humanoid only. For quadrupeds and creatures, the procedural clips are the practical answer.

---

## Step 7 in detail: export

**Common to both engines** (ARP export documentation):
- "Bones animations are baked when exporting, one keyframe per frame".
- "By default, only the active action is exported", so Forge must switch that off to export all test clips.

**Confirmed script recipe.** Settings sit on the scene, then one command writes the file:
- `scn.arp_engine_type = 'UNREAL'`
- `scn.arp_export_rig_type = 'HUMANOID'` or `'UNIVERSAL'`
- `scn.arp_units_x100`, `scn.arp_bake_actions`, `scn.arp_ue_root_motion`, `scn.arp_export_twist`, `scn.arp_ge_sel_only`
- `bpy.ops.arp.arp_export_fbx_panel(filepath=...)`

The setting names for "Rename for UE", "Mannequin Axes" and "Add IK Bones" are not in the documentation examples. Forge must read them from the scene.

### Unreal 5

| Setting | Value | Why |
|---|---|---|
| Rig type | Humanoid for bipeds, Universal for quadrupeds and creatures | Humanoid is "required for animation retargeting, root motion in game engines" |
| Units x100 | On | "Allows retargeting in Unreal" |
| Rename for UE, Mannequin Axes | On for bipeds | Lets the skeleton import as the Mannequin skeleton |
| Add IK Bones | On | Adds `ik_foot_root`, `ik_foot_l` and the rest |
| Root Motion | On for the root-motion walk | Moves the `c_traj` animation to the FBX root; then tick EnableRootMotion in Unreal |
| Export Twist | On | Prevents candy-wrapper forearms |

- Since ARP 3.79.17 (6 November 2026), Humanoid mode also supports "multiple leg and ear limbs".
- The research note also lists these ARP guidelines, which were not individually re-checked: 6 spine bones and 2 neck bones to match the UE5 Mannequin, character height about 1.80 m, rig named "root".

### Unity (URP, mobile)

- **Humanoid bipeds:** "root motion is automatically computed when importing Humanoid skeletons ... No extra export step required".
- **Twist:** the ARP docs say "Unity internally handles the hand twist by twisting the forearm bone without using a dedicated twist bone, unless an additional script/plugin is used". Check the forearm twist frames (538 - 633) on the 8k LOD specifically.
- **Creatures, tails, ears:** import as Generic, with "Avatar Definition: Create From This Model" and "Root Node: root". Tail and ear chains only animate as Generic or as extra bones outside the Humanoid avatar.
- **"Bake Axis Conversion"** is a Unity-only export option that matches Unity's import setting.

### One Blender 5.3 caution

ARP's 26 November 2026 release note says the glTF exporter "may crash in 5.3.0" with animated properties. Use FBX for the engine exports.

---

## Licence notes for every animation source

| Source | Can it be used in a commercial game? | Can Forge bundle or redistribute the files? | Status of this information |
|---|---|---|---|
| **Forge's own procedural clips** | Yes, they are yours | Yes | No third party involved |
| **Auto-Rig Pro rigs** | Yes: "a rig generated with Auto-Rig Pro by the end-user ... is the sole property of the end-user" | The add-on itself "cannot be freely distributed as is" | Confirmed on the vendor licence page |
| **Mixamo (Adobe)** | Yes: "available for free, with no licensing or royalty fees, for unlimited commercial or non commercial use", described as a "limited duration technology preview". No credit required. | **No.** Not allowed: "Any type of free distribution of character or animation raw files"; "You may not distribute the files to customers or non-team members". Not for training machine-learning models. | From an Adobe Community forum post (2022), not the legal terms. Adobe's official FAQ could not be opened. |
| **Quaternius Universal Animation Library 1 and 2** | Yes | **Treat as no.** The pack pages say "CC0 License", but the site licence page (updated 28 August 2026) says "You just can't resell or redistribute the assets themselves as assets". The two pages conflict. | Both pages confirmed. Only part of each kit is free. Check the licence file inside the download. |
| **Kenney** | Yes: "public domain licensed (CC0). You're free to use them, even in commercial projects." | Yes | Confirmed. The animation content is small and stylised. |
| **Rokoko free mocap (263 clips)** | Yes: "including for commercial use" | Not stated; **assume no** | Use confirmed; redistribution is an assumption. Download needs an email form. |
| **Unreal / Epic sample animations** | Treat as Unreal target only; never use for the Unity build | Assume no | **Unverified.** Epic's licence page could not be read. Open https://www.unrealengine.com/en-US/eula/content in a browser before using any. |
| **Unity sample animations** | Depends on each pack's own terms | Assume no | **Unverified.** Unity's store terms say some "Restricted Assets" carry their own licence. |
| **CMU motion capture** | Unknown | Unknown | **Could not be checked at all** (site unreachable). Do not rely on it. |

**Rule for Forge:** only the procedural clips ship with Forge. Any downloaded clip is fetched by you, under your own account, into a local folder that Forge reads. It is never committed to the Forge repository or installer. Shipping such animation baked into a finished game is the normal permitted use.

---

## Specification: the "Sample animations" panel in Forge Step 8

### Layout

1. **Rig summary line.** Biped or creature (auto-detected, with an override), number of tail and ear chains found, frame rate (default 30).
2. **Clip list.** One row per clip with: Build, Play, a status light (grey not built, green pass, amber warnings, red fail), and a "View worst frame" button.
3. **Check results.** The four automatic checks, each with a number and the frame where it was worst.
4. **LOD switch.** LOD0, 30k (Unreal) or 8k (Unity). Play and checks apply to the chosen mesh.
5. **Contact sheet button.** Renders one image per ROM region.
6. **External clip slot.** Folder picker, preset choice (Mixamo, Rokoko), "Retarget" button, or the six-step checklist if Remap cannot be scripted.
7. **Approve button.** Records which clips passed and unlocks Step 9.

### Clips, frame ranges and controls

| Clip | Frames | Shown for | ARP controls keyed | Limb mode |
|---|---|---|---|---|
| ROM_Biped | 0 - 1171 | Bipeds | Spine (`c_spine_*`), head (`c_head.x`), neck, shoulder, arm, forearm, hand and finger FK controls, thigh, leg, foot and toe FK controls | FK arms and legs |
| ROM_Creature | 0 - 307 | Creatures, and bipeds with tail or ears | Tail chain, ear chains, jaw, shoulder-blade and spine controls | FK |
| Idle_Breathe | 0 - 120 | All | `c_root_master.x` (pelvis), `c_spine_*`, shoulders, `c_head.x` | IK feet planted |
| Walk_InPlace | 0 - 32 | Bipeds | `c_foot_ik` left and right, `c_root_master.x`, `c_spine_*`, arm FK controls, `c_head.x` | IK feet, FK arms |
| Walk_RootMotion | 0 - 32 | Bipeds | As above, plus `c_traj` | IK feet, FK arms |
| Turn_90 | 0 - 36 | All | `c_traj`, `c_head.x`, `c_spine_*`, `c_foot_ik` | IK feet |
| Quad_Walk, Quad_Trot | 0 - 32 | Quadrupeds | Four foot IK controls, `c_root_master.x`, `c_spine_*`, `c_head.x` | IK feet |
| Tail_Ear_Sway | Matches the walk | Rigs with tail or ear chains | Every bone in each tail and ear chain | FK, then the spring bake |
| External clip | From the file | Bipeds | Set by ARP Remap | IK feet and hands |

**Control names.** Forge finds controls by name prefix on the actual rig and lists any it cannot find, instead of assuming names. Tail and ear names in particular are unverified.

**Loop clips.** They export without their duplicate last frame (for example 0 - 31 for a 32-frame walk).

### What is checked, and the pass rule

| Check | Clips | Pass rule (starting values, to tune) |
|---|---|---|
| Volume loss per joint region | ROM clips | Under 15 percent passes; 15 - 20 amber; over 20 red |
| Edge stretch | ROM clips | Report the worst ratio and frame; thresholds to be set on the first character |
| Self-intersection count | All clips | Zero outside the combined poses; any tail or ear touching the body is red |
| Bone influences | Once per mesh | No unweighted vertices; at most 4 influences per vertex for the Unity build |
| Foot slide | Walk and trot clips | Standing foot moves less than a small fraction of foot length during stance |
| Loop closure | Idle, walks, sway | First and last pose match |
| Follow-through | Tail_Ear_Sway, Turn_90 | Chain tip lags the root; no clipping |
| LOD comparison | All | The same checks on the 30k and 8k meshes; forearm twist checked on 8k for Unity |

### What you approve

- **After the ROM:** "Deformation OK", or tick the bad regions. Forge sends those back to the weight step (Voxel Heat Diffuse Skinning or EasyWeight, if adopted).
- **After the sample clips:** "Motion reads correctly".
- **After the LOD pass:** "Mobile LOD acceptable".
- **Final:** Approve for export. Forge then writes the Unreal and Unity animation files.

### Build order

1. ROM_Biped and the automatic checks. This catches most skinning faults and needs no gait logic.
2. Idle_Breathe and Walk_InPlace.
3. ROM_Creature and Tail_Ear_Sway with the built-in spring.
4. Walk_RootMotion and Turn_90, then export through ARP.
5. The external clip slot last, because it depends on finding Remap's undocumented commands.

---

## Sources

- ARP Remap: https://www.lucky3d.fr/auto-rig-pro/doc/remap_doc.html
- ARP game export: https://www.lucky3d.fr/auto-rig-pro/doc/ge_export_doc.html
- ARP versions: https://superhivemarket.com/products/auto-rig-pro/versions
- ARP licence: https://www.lucky3d.fr/auto-rig-pro/doc/license.html
- Wiggle Bones: https://extensions.blender.org/add-ons/wiggle-bones/
- Jiggle Physics: https://extensions.blender.org/add-ons/jiggle-physics/
- Retarget: https://extensions.blender.org/add-ons/retarget/
- Mixamo forum FAQ: https://community.adobe.com/t5/mixamo-discussions/mixamo-faq-licensing-royalties-ownership-eula-and-tos/td-p/13234775
- Quaternius: https://quaternius.com/packs/universalanimationlibrary.html and https://quaternius.com/license.html
- Kenney: https://kenney.nl/support
- Rokoko: https://www.rokoko.com/mocap/free-mocap-assets
- Epic content licence (not readable in the research session): https://www.unrealengine.com/en-US/eula/content
