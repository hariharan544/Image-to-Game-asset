# Auto-Rig Pro 3.79.17 on the director's PC: what the check showed

Source: `docs/research/arp_3_79_probe.json`, written by `forge arp-probe` on 2026-11-28. The
name in brackets is where the number sits in that file. After each fact: what it means for
Step 8.

## The setup

- Auto-Rig Pro 3.79.17 in Blender 5.3.0: all 7 parts ran in 58 s and Blender never closed by itself (`parts`). Step 8 can be built on these facts.
- 9 rig presets on disk: bird, bird_44, cs, dog, free, horse, horse_ik_spine, human, master (`arp.presets_available`).

## Rigs Auto-Rig Pro starts from

- The bird rig loads: 49 reference bones; Auto-Rig Pro says "Blender 5, loading Blender 4.4 bird armature" (`presets.bird`). Birds no longer need to wait for a crash fix.
- Human: 65 reference bones, 2 spine reference bones, and root_ref.x stores spine_count 3 (`presets.human`, `spine_count`). The count includes the root: read it from the bones, not from the number.
- Dog: 114 reference bones, spine_count 4 (3 spine bones), three-bone legs (thigh_b_ref) (`presets.dog`).
- Dog front legs are leg copies (`_dupli_001`) with poles c_leg_pole_dupli_001.l/.r and no arm poles (`ik_poles.rigs.dog`). Four-legged rigs look for leg poles on the front legs too.
- Horse: 116 reference bones, neck_count 4 with 3 subneck reference bones, three-bone legs (`presets.horse`).
- Face bones: off in the human and bird presets (facial 0), on in the dog and horse (facial 1) (`presets.*.ref_bones.head_ref.x.keys.facial`). Step 8 only needs the face switch on the dog and horse rigs.
- Free: 0 reference bones, 2 bones (`presets.free`).
- add_limb offers 12 limbs: arm.l, arm.r, breast, ears, head, leg.l, leg.r, spine, tail, spline_ik, bbones, kilt (`add_limb.presets_items`).

## Changing a limb's options

- The safe way (spec 9.2) works: 4 of 4 changes took (pinky off, ring finger off, neck 2 bones, tail 6 bones), each with every option sent in one call and nothing else changing (`limb_protocol`). Step 8 now changes tail and ear counts this way (`arp_limb_options.py`).
- The limb options button has 246 options; all 44 the spec names exist (`limb_options`).
- Auto-Rig Pro's own settings reader is reachable, in `auto_rig_pro.src.auto_rig` (`load_limb_settings.module`).

## Extra parts

- Wings on an added arm: set the safe way with nothing else changing, match_to_rig finished, no crash; 3 feather deform bones per wing at the defaults, 21 feather bones in all (`wings`). The spec 9.5 gate passes on this PC: extra wings may use arm_wings.
- disable_limb on the right ear removed only that ear's 4 bones; the left ear, the second ear pair and every other limb stayed (`disable_limb`). One-eared animals and stray ears: add the pair, then disable the missing side.
- A tail moved to .l or .r is renamed (tail_00_ref_dupli_001.x becomes tail_00_ref.l); hung from head_ref.x it builds with its control under c_head.x (`add_limb.cases.tail_dupli_left`, `add_limb.after_match.chain_roots_parents`). Hair strands, antennae and ponytails can be tails on the head.
- The kilt builds in Blender 5.3: 50 new bones in 1.1 s, no crash; it crashed Blender 4.4.0 (`add_limb.cases.kilt`). Skirts may use the kilt.
- A spline IK chain's root hangs from c_traj (spline_01_ref.x and c_spline_root.x) (`add_limb.after_match.chain_roots_parents`). Step 8 must re-parent a trunk or tentacle chain to the bone it grows from, or it will not follow the body.
- With all these limbs added: 483 bones, 109 of them deform bones (`add_limb.after_match`).

## Building without a window

- In background Blender (no window), append and match_to_rig both worked: 67 deform bones in 1.1 s (`headless`). Step 8 can build without a window. (The 3.77.33 source read in `arp_limbs.md` said append_arp crashed without one; 3.79.17 does not.)
- Human rig: 67 deform bones. hand, head, neck, spine_01, spine_02, root and foot deform; arm, forearm, thigh and leg do not (their stretch and twist bones do) (`deform_names`).
- IK poles: c_leg_pole.l/.r and c_arms_pole.l/.r; an added arm gets c_arms_pole_dupli_001.l (`ik_poles`, `add_limb.after_match.ik_poles`).

## Skinning

- Bind engines: HEAT_MAP (the default), PSEUDO_VOXELS, VHDS, AAS (`bind.engine_items`).
- On the 4,048-vertex test body: heat map 0.8 s, pseudo voxels 1.4 s, every vertex weighted both times (`bind`).
- Preserve Volume is on by default and on the Armature modifier after a bind; Scale Fix is off by default (`bind`, `scale_fix`). Step 8 keeps turning Preserve Volume off before the bind (engines blend bones linearly).
- Chin: with the chin keys set, Auto-Rig Pro reads them and 325 of 4,048 vertices change their head weight, by up to 0.29 (`chin`). Asking where the chin is changes the skin, so the chin question stays.

## Export

- A cc_ socket bone on hand.r, with a prop weighted 100% to it, came out in all four exports with the prop still on it; in Unreal humanoid its parent is hand_r (`socket_export`). Props can be sockets (spec 9.6).
- Bones exported, each count with the one socket bone: Unity humanoid 60, Unity universal 68, Unreal humanoid 75, Unreal universal 68 (`socket_export.variants.*.bone_count`).
- Unreal humanoid uses the mannequin names: pelvis, spine_01, clavicle_l, upperarm_l, lowerarm_l, hand_l, thigh_l, calf_l, and adds 7 ik bones (ik_foot_root, ik_hand_root, ik_hand_gun...) (`socket_export.variants.unreal_humanoid.bones`).
- Auto-Rig Pro's own humanoid check still says humanoid with an extra arm, a second ear pair (4 ear sides) and 3 tails (`humanoid_check.results`). Open: whether a HUMANOID export keeps the extra arm. The part that exports it (multi_arm) stopped early; the rerun answers it.

## The face switch, and the rerun

- The face switch was refused 3 times, each time as the first edit right after a fresh rig: "show_limb_params.poll() failed, context is incorrect"; it stopped multi_arm_export, limbs_setup and build_setup (`errors`). Every option change after an added limb went through.
- The human preset already has the face off, so that switch was never needed there.
- Most likely cause: the limb options button only works on a selected reference bone that can be seen, and adding a limb shows the reference bones (Auto-Rig Pro does this in add_limb).
- The fix, in the check and in Step 8 alike (one copy, `arp_limb_options.py`): skip the switch when head_ref.x already stores it off; otherwise show the reference bones and change it the safe way; when Auto-Rig Pro still says no, write down what its check saw and carry on.
- What this cost the file: multi_arm_export has no result, and the build part measured the human rig straight from the preset, without match_to_rig (deform_names, ik_poles, chin, bind, socket_export). The headless part, which did match, has the same 67 deform bones.
- Rerun, after `git pull`, in PowerShell in the Forge folder: `.venv\Scripts\forge.exe arp-probe --only multi_arm,limbs,build` (a few minutes). It writes `jobs\_setup\arp_probe\arp_3_79_probe_rerun.json` and leaves the first result alone. Send that file back.
