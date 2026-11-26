# Research gap: Skeleton standard, retargeting and real-animation test

# Forge research: standard skeletons, retargeting, and tests with real animations

**Scope and method.** I checked the repo first: `blender_scripts/forge_bpy/arp_rig.py`, `blender_scripts/forge_bpy/finalize.py` (`ARP_ENGINE`, `FBX_ENGINE`, `_export_arp`), the measured ARP 3.79.17 probes in `jobs/_setup/addon_probe.json`, `addon_trial.json` and `addon_trial2.json`, and Phase 5 of `docs/ROADMAP.md`. I then ran web searches.

**Network limits.** WebFetch could not reach these hosts: www.lucky3d.fr (the ARP docs), dev.epicgames.com, api.unrealengine.com and huggingface.co. Each needs to be allowed in the session's network settings before it can be read in full. Because of this, the citations are search-result pages, and anything I could only infer is marked UNVERIFIED. Every ARP property and operator name below marked "measured" comes from the user's own probe JSON, so it is reliable for 3.79.17.

---

## 0. Core recommendation: a skeleton manifest drives everything

Do not rely on auto-mapping in either engine. Blender already knows every joint, because `find_joints` and the ARP reference bones locate them. Have Blender write a sidecar file, `<asset>.forge_skeleton.json`, next to every FBX. The UE Python script and the Unity editor script then build their retarget definitions from that file deterministically. Auto-mapping is used only as a cross-check.

```json
{ "archetype": "biped|quadruped|bird|serpent|generic",
  "units": "cm", "up": "Z", "forward": "-Y", "rest_pose": "A|T", "arm_angle_deg": 45,
  "root": "root", "pelvis": "pelvis", "height_cm": 182.0,
  "chains": [ {"name":"Spine","start":"spine_01","end":"spine_03","goal":null},
              {"name":"LeftArm","start":"upperarm_l","end":"hand_l","goal":"hand_l_goal"},
              {"name":"Tail","start":"tail_01","end":"tail_08","goal":null} ],
  "unity_human": {"Hips":"pelvis","Spine":"spine_01","Chest":"spine_02","UpperChest":"spine_03", "...":"..."},
  "excluded_from_chains": ["*twist*","ik_*"],
  "export": {"tool":"ARP","engine":"UNREAL","rig_type":"HUMANOID","units_x100":true} }
```

This one file solves the problem for bipeds, quadrupeds and generic creatures alike.

---

## F1. Bone naming and ARP game-engine export presets

**(a) Why it matters.** Library animations bind by bone name and hierarchy. UE5's Manny and Quinn share a skeleton, and the Game Animation Sample, Lyra and Marketplace content target it. Unity Humanoid works from muscle space, so names matter less there, but its auto-mapper still uses them.

**(b) Topology.** Not applicable. Keep the counts fixed per archetype instead:
- ARP's human preset gives 67 deform bones (measured).
- ARP Humanoid export to Unity gives 59 bones (measured, `arp_rig.py` docstring).

**(c) Rig.** All of these are measured Scene properties in ARP 3.79.17:
- `arp_engine_type`: UNITY, UNREAL, GODOT or OTHERS.
- `arp_export_rig_type`: HUMANOID or UNIVERSAL.
- Unreal-related: `arp_rename_for_ue`, `arp_mannequin_axes`, `arp_ue4`, `arp_ue_ik` (default True; adds the IK bones), `arp_ue_ik_anim`, `arp_ue_root_motion` (default False).
- Units: `arp_units_x100` (default True) and `arp_units_meters`.
- Axes: `arp_bone_axis_primary_export` = Y and `arp_bone_axis_secondary_export` = X (defaults).
- Rig name and parenting: `arp_export_rig_name` = "root" (default), `arp_export_noparent`.
- Twist and bend bones: `arp_export_twist` (default True), `arp_keep_bend_bones`.
- `arp_ge_export_metacarp`, `arp_ge_force_rest_pose_export` (default True), `arp_ge_master_traj`, `arp_fix_fbx_matrix` (default True), `arp_fix_fbx_rot`, `arp_init_fbx_rot`.
- Action export: `arp_export_use_actlist`, `arp_export_separate_fbx` with `FILE_PER_ACTION`, `arp_export_start_frame`/`end_frame`, `arp_export_slot_separator`.
- Operators: `arp.arp_export_fbx_panel(filepath, quick_export)`, `arp.check_rig_export`, `arp.fix_rig_export`, `arp.ge_save_preset`/`ge_load_preset`.

Forge already uses:
- Unreal: HUMANOID + `rename_for_ue` + `mannequin_axes`, with `arp_ue4=False`. This produced UE5 Mannequin names in the user's measurement.
- Unity: HUMANOID.

**Recommended presets:**

| Case | `arp_export_rig_type` | Other settings |
|---|---|---|
| Biped | HUMANOID | |
| Creature with tail, wings or extra limbs | UNIVERSAL | Exports custom limbs. One user reported HUMANOID drops non-human bones (UNVERIFIED in docs). |
| Unreal, any rig | | `arp_ue_ik=True` (`ik_foot_root`/`ik_hand_root` bones, as on Manny) |
| Animation export | | `arp_ue_root_motion` per clip type (see F9) |

**(d) Texture.** Not applicable.

**(e) Automation.** Fully scripted, and partly done in `finalize._export_arp`. Two additions:
1. Run `bpy.ops.arp.check_rig_export()` and then `arp.fix_rig_export()` before every export, and log what they report.
2. Save a Forge preset with `arp.ge_save_preset` so the settings cannot drift between ARP versions.

**(f) Engines.**
- One forum report says ARP renamed the root to `root_aprbaseobject` when the armature object was named "Armature". Never name the rig object "Armature" ([UE forum](https://forums.unrealengine.com/t/solved-skeleton-root-bone-problem-blender-auto-rig-pro-export/232170)).
- ARP's developer says on the UE forum that Humanoid "will export only the basic human bones" ([UE forum](https://forums.unrealengine.com/t/auto-rig-pro-for-blender-unreal-export/86715/5)).
- The ARP changelog records a fix for "long-standing bind pose issues" with Unreal ([Superhive versions](https://superhivemarket.com/products/auto-rig-pro/versions)). Invalid bind pose errors are still reported ([UE forum](https://forums.unrealengine.com/t/blender-auto-rig-pro-skinned-model-with-animation-fbx-invalid-bind-pose-error-gltf-root-bone-renamed-to-root-proxytruerootjoint/2384238)).

## F2. FBX scale (0.01 / 100), unit scale and leaf bones

**(a) Why it matters.** This is the most common Blender-to-UE breakage. A ×100 mismatch puts root scale at 100, makes animations 100× too small, or multiplies hip translation by 100 in the IK Retargeter. That ruins root motion and the retarget pelvis height ([UE forum: hips ×100](https://forums.unrealengine.com/t/issue-with-ik-retargeter-hips-translation-values-multiplied-by-100-unit-scale-mismatch/2677299), [root scaled ×100](https://forums.unrealengine.com/t/root-bone-is-scaled-by-x100/484622), [Blender T51704](https://projects.blender.org/blender/blender-addons/issues/51704)).

**(b) Topology.** Apply object scale and rotation on the mesh and the armature before binding.

**(c) Rig.**
- **ARP path (recommended):** keep `arp_units_x100=True` (measured default). This writes centimetres with a unit-scale root.
- **Plain Blender exporter fallback (`finalize.FBX_ENGINE`):**
  - Unreal: `apply_unit_scale=True`, `apply_scale_options='FBX_SCALE_NONE'`.
  - Unity: `'FBX_SCALE_ALL'` plus `bake_space_transform=True`.
  - Always pass `add_leaf_bones=False`, `primary_bone_axis='Y'`, `secondary_bone_axis='X'` and `armature_nodetype='NULL'`.

  Leaf `_end` bones add useless joints in UE and clutter in Unity's mapping. Guides consistently say to disable them ([Ready Player Me guide](https://docs.readyplayer.me/ready-player-me/integration-guides/unreal-sdk/blender-to-unreal-export)).
- **Mixamo FBX into Blender:** the armature arrives with object scale 0.01 because the file is in centimetres. Apply scale on the source before retargeting. ARP's `arp.auto_scale` ("Automatic scale of the source armature to fit the target armature height", measured description) covers the height match.

**(d) Texture.** Not applicable.

**(e) Automation.** Fully scriptable. Add a post-export validator that re-imports the FBX into an empty Blender scene and asserts:
- the armature's object scale is 1 (or 0.01 when consistent);
- the root bone's local scale is 1;
- the pelvis height in cm is within ±2% of the manifest's `height_cm × pelvis ratio`;
- no bone name ends in `_end`.

**(f) Engines.**
- UE: import with Import Uniform Scale 1. If the root bone shows scale 100, fail the run rather than patching it in UE.
- Unity: check `ModelImporter.globalScale` and `useFileScale`. After import, the model's world height should be about the manifest's `height_cm / 100` metres.

## F3. Bone axes and roll orientation

**(a) Why it matters.** Additive animations, Control Rig, AnimBP bone modifications, and Unity Humanoid muscle extraction all assume consistent local axes. Inconsistent roll shows up as twisted thumbs and wrists, backwards feet, and sideways finger curls ([Unity: feet backwards](https://discussions.unity.com/t/feet-backwards-in-t-pose-imported-from-blender/767112), [fingers sideways](https://discussions.unity.com/t/fingers-bending-sideways/119929), [Unity issue: twisted thumbs](https://issuetracker.unity3d.com/issues/3ds-max-model-thumbs-become-twisted-when-animation-type-is-set-as-humanoid)).

**(b) Topology.** Not applicable.

**(c) Rig.**
- Unreal: `arp_mannequin_axes=True` reorients exported bones to Manny's convention. That convention is X along the bone (UNVERIFIED; implied by the option's name and its use).
- Unity: muscle space tolerates roll differences, but finger and thumb roll must give a consistent curl axis.
- Generic and quadruped rigs: ARP's default Y-primary/X-secondary is fine, because test clips are baked onto this exact skeleton in Blender.

**(d) Texture.** Not applicable.

**(e) Automation.** Write a bpy check after `match_to_rig`, before binding. For each finger chain:
1. Compute the bend axis as the cross product of consecutive bone directions in a curled test pose.
2. Assert the same local axis (for example +X) is used on both sides, mirrored.

The ARP tools for repair are `arp.guess_fingers`, `arp.switch_all_fingers` and `arp.copy_bone_rest` (all measured). If the check fails, the director sees the "finger curl" ROM frame flagged red. They are not asked to fix roll by hand.

**(f) Engines.** In Unity, Configure Avatar → Pose → Enforce T-Pose is a UI-only partial fix. The thumb issue is "Won't Fix" ([issue tracker](https://issuetracker.unity3d.com/issues/3ds-max-model-thumbs-become-twisted-when-animation-type-is-set-as-humanoid)). Fix roll in Blender.

## F4. Rest pose: A vs T, Manny/Quinn proportions, retarget pose

**(a) Why it matters.** The source and target rest poses must line up. The pose difference mainly skews the arms. "The closer you can line up the 2 rig poses the better" ([UE forum: A-pose↔T-pose](https://forums.unrealengine.com/t/is-there-a-quick-way-to-perfectly-match-t-pose-skeleton-to-ue5s-standard-a-pose-when-retargeting/569850), [Mixamo X Bot → Manny upper-body issues](https://forums.unrealengine.com/t/ik-retarget-issues-with-upper-body-mixamo-x-bot-ue5-manny/655488), [uhiyama-lab guide](https://uhiyama-lab.com/en/notes/ue/animation-retargeting-complete-guide/)).
- Manny and Quinn are A-pose.
- Mixamo is T-pose.
- Unity Humanoid wants a T-pose for its avatar.

**(b) Topology.** Model and bind in A-pose (arms about 45° down). Shoulders deform better, and the pose matches Manny. Ask Tripo for A-pose where it offers the option (UNVERIFIED that Tripo exposes it).

**(c) Rig.** Store the bind pose in the manifest (`rest_pose`, `arm_angle_deg`, measured from the `upperarm` vector). Never rebind to match a library; fix the difference in the retarget pose:
- UE: `IKRetargeterController.auto_align_all_bones(unreal.RetargetSourceOrTarget.TARGET)` writes an aligned retarget pose ([search summary of the Epic Python guide](https://dev.epicgames.com/documentation/unreal-engine/using-python-to-create-and-edit-ik-retargeter-assets-in-unreal-engine)). Root offset: `set_root_offset_in_retarget_pose`.
- Blender with ARP Remap: run `arp.redefine_rest_pose` and `arp.save_pose_rest` (measured) to match the source's T-pose to the target. A Blender Artists thread says retargets break if the rest pose is not fixed first ([BA thread](https://blenderartists.org/t/issues-with-retargeting-animations-in-auto-rig-pro/1604289)).
- Unity: give the avatar T-pose `SkeletonBone` rotations through `HumanDescription.skeleton`. Compute them in Blender by posing the arms to horizontal and dumping the local rotations into the manifest. This is UNVERIFIED as a complete fix, but it is the documented mechanism.

**Proportions.** Retargeters scale pelvis translation by the height ratio (UE: the Pelvis Motion op, formerly "Root Phase"; [op stack doc](https://dev.epicgames.com/documentation/unreal-engine/retargeting-operation-stack-in-unreal-engine?lang=en-US)). Stylized proportions (chibi, big belly, big head) cause hand-body penetration and foot sliding. Those must be measured (F12), not assumed fine. Manny's exact height is UNVERIFIED, about 180 cm; read it at runtime from the source skeletal mesh bounds.

**(d) Texture.** Not applicable.

**(e) Automation.**
- Blender: rest-pose detection is pure geometry (angle between `upperarm` and the horizontal).
- UE: the retarget pose is fully scripted.
- Director: one click only if the auto-aligned shoulders look wrong in the test video. Then expose a single slider, "arm angle offset", and re-run.

**(f) Engines.** UE 5.4 added auto retargeting and auto align ([5.4 features talk](https://forums.unrealengine.com/t/talks-and-demos-ik-retargeting-5-4-features-at-a-glance/1817329)). Unity has no retarget-pose concept; the avatar T-pose is everything.

## F5. UE5 IK Rig chains, generated from ARP and the manifest

**(a) Why it matters.** IK Rig chains are the retarget contract in UE5, and the IK Retargeter maps chain to chain.

**(b) Topology.** Not applicable.

**(c) Rig.** Python API ([Epic IK Rig Python guide, via search](https://dev.epicgames.com/documentation/unreal-engine/using-python-to-create-and-edit-ik-rigs-in-unreal-engine)):

```python
ikr = asset_tools.create_asset(name, path, unreal.IKRigDefinition, unreal.IKRigDefinitionFactory())
c = unreal.IKRigController.get_controller(ikr)
c.set_skeletal_mesh(skm)
if manifest["archetype"] == "biped":
    c.apply_auto_generated_retarget_definition()   # template-based, bipeds only
    c.apply_auto_fbik()
else:
    for ch in manifest["chains"]:
        c.add_retarget_chain(ch["name"], ch["start"], ch["end"], ch["goal"] or "")
    c.set_retarget_root(manifest["pelvis"])        # UNVERIFIED Python name; editor: Hierarchy > Set Retarget Root
```

**Chain names.** For bipeds, use exactly the chain names of the engine's own `IK_Mannequin`. Read them at runtime with the IK Rig controller's chain getter (UNVERIFIED method name, roughly `get_retarget_chains()`) rather than hard-coding. Then `auto_map_chains(unreal.AutoMapChainType.EXACT, True)` matches them reliably.

**Typical Manny-style chains** (UNVERIFIED exact names):
- Root, Spine (spine_01→spine_0N), Neck, Head
- Left/RightClavicle
- Left/RightArm (upperarm→hand)
- Left/RightLeg (thigh→ball or foot)
- Left/Right Thumb/Index/Middle/Ring/Pinky
- Retarget root: pelvis

Different spine counts are fine. ARP's default spine is shorter than Manny's spine_01..05, and chain retargeting resamples along the chain.

**Creature chains, built from the manifest:**
- Tail
- WingL/WingR (humerus→hand→finger tip)
- FrontLegL/R and BackLegL/R (for quadrupeds; IK goals on paws)
- Neck, Head, Jaw
- ExtraArm_N

**Exclusions.** Keep twist bones and `ik_*` bones out of all chains.

**(d) Texture.** Not applicable.

**(e) Automation.**
- Fully scripted in UE Python from the manifest.
- `apply_auto_generated_retarget_definition` uses biped templates only. No quadruped template turned up, so quadrupeds always use manifest chains ([auto retargeting doc](https://dev.epicgames.com/documentation/unreal-engine/auto-retargeting-in-unreal-engine)). Use Auto Retarget Chains only as a cross-check: diff its chains against the manifest's and log the difference.

**(f) Engines.** In 5.6, the solver stack and API changed. `op_stack` is deprecated in favour of `RetargetOps`, and solvers and ops are structs. Pin the UE version in Forge and gate the code by `unreal.SystemLibrary.get_engine_version()`.

## F6. UE5 IK Retargeter and headless batch retargeting

**(a) Why it matters.** This is how real UE animations from GASP, Lyra or the Third Person template land on the asset.

**(b) Topology.** Not applicable.

**(c) Rig.**

```python
rtg = asset_tools.create_asset("RTG_Manny_to_X", path, unreal.IKRetargeter, unreal.IKRetargetFactory())
r = unreal.IKRetargeterController.get_controller(rtg)
r.set_ik_rig(unreal.RetargetSourceOrTarget.SOURCE, ik_mannequin)
r.set_ik_rig(unreal.RetargetSourceOrTarget.TARGET, ikr)
r.auto_map_chains(unreal.AutoMapChainType.EXACT, True)        # FUZZY as fallback
r.auto_align_all_bones(unreal.RetargetSourceOrTarget.TARGET)  # 5.4+
# 5.6+: r.add_default_ops() / r.add_retarget_op(...)  - Pelvis Motion, FK Chains, IK Chains, Root Motion ops
new = unreal.IKRetargetBatchOperation.duplicate_and_retarget(
    anims, src_mesh, tgt_mesh, rtg, "", "", "", "_X", True)
```

Sources:
- `duplicate_and_retarget` and `auto_align_all_bones` ([search summary of Epic docs](https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/IKRetargetBatchOperation)).
- `add_retarget_op` returns the stack index ([search summary](https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/IKRetargeterController)).
- Argument order and count differ by version. One forum user hit a signature error ([UE forum](https://forums.unrealengine.com/t/using-python-to-retarget-animations-to-a-folder/2838372)), so the argument list is UNVERIFIED for the user's UE version.
- The 5.2 docs describe `auto_map_chains` as fuzzy-only, and the enum descriptions on one API page appear swapped. Test this.

**(d) Texture.** Not applicable.

**(e) Automation.** Fully scripted in a UE commandlet, for example `UnrealEditor-Cmd.exe Project.uproject -run=pythonscript -script=forge_retarget.py`.

**Proof render.** Script a Level Sequence with the retargeted clip on the asset, and render it with Movie Render Queue through Python (`MoviePipelineQueueSubsystem`). Running MRQ headless with `-RenderOffscreen` is UNVERIFIED; worst case it needs a windowed editor, which the user has.

**(f) Engines.** IK bones (`ik_foot_l`/`ik_hand_gun`…) are not filled by chain retargeting. That matters if the game uses them, and GASP/Lyra-style setups do. Handle it with a retarget op or a post-process. UNVERIFIED which 5.6 op covers this.

## F7. Unity Humanoid avatar: auto-mapping and "Avatar is not valid"

**(a) Why it matters.** Humanoid is Unity's only cross-skeleton retargeting. Mixamo, Starter Assets and Asset Store clips all run on any valid Humanoid.

**(b) Topology.** Not applicable.

**(c) Rig.**
- **Required bones** (Unity manual: "at least the required bones"; [Configuring the Avatar](https://docs.unity3d.com/Manual/ConfiguringtheAvatar.html)): Hips, Spine, Head, Left/Right UpperLeg, LowerLeg, Foot, UpperArm, LowerArm, Hand. That is 15 bones; the exact list is from memory, so UNVERIFIED against the 6.x page.
- **Optional bones:** Chest, UpperChest, Neck, Shoulders, Toes, Eyes, Jaw, and 15 finger bones per hand.

**Editor script:**

```csharp
class ForgeAvatar : AssetPostprocessor {
  void OnPreprocessModel() {
    if (!assetPath.Contains("/Forge/")) return;
    var m = (ModelImporter)assetImporter; var man = LoadManifest(assetPath);
    if (man.archetype == "biped") {
      m.animationType = ModelImporterAnimationType.Human;
      m.avatarSetup  = ModelImporterAvatarSetup.CreateFromThisModel;
      m.humanDescription = BuildFromManifest(man);   // HumanBone[] from unity_human + FULL SkeletonBone[] list
    } else { m.animationType = ModelImporterAnimationType.Generic; m.motionNodeName = man.root; }
  }
  void OnPostprocessModel(GameObject g) { /* load Avatar sub-asset; assert avatar.isValid && avatar.isHuman; write JSON report */ }
}
```

`ModelImporter.animationType`, `avatarSetup`, `humanDescription` and `autoGenerateAvatarMappingIfUnspecified` are documented ([ModelImporter.avatarSetup](https://docs.unity3d.com/ScriptReference/ModelImporter-avatarSetup.html), [humanDescription](https://docs.unity3d.com/ScriptReference/ModelImporter-humanDescription.html)). Check `Avatar.isValid` before use ([AvatarBuilder.BuildHumanAvatar](https://docs.unity3d.com/6000.1/Documentation/ScriptReference/AvatarBuilder.BuildHumanAvatar.html)).

**Failure cases:**

| Cause | Typical error or symptom | Source |
|---|---|---|
| Required bone missing or misnamed | "Required human bone 'Hips' not found" | [issue tracker](https://issuetracker.unity3d.com/issues/anim-applying-humanoid-to-this-fbx-generates-unexpected-error) |
| `HumanDescription.skeleton` lists only some transforms (it must list every transform from the model root down) | "Transform 'X' not found in HumanDescription" | [forum](https://discussions.unity.com/t/modelimporter-how-to-import-as-humanoid/673885) |
| CopyFromOther avatar on a different hierarchy | "Copied Avatar Rig Configuration mis-match… Transform 'Hips' not found" | [Unity forum](https://forum.unity.com/threads/unity-avatar-creation-failed.1107353/) |
| Transforms inserted between the Animator and the skeleton root after the avatar was built | avatar no longer valid | [issue](https://issuetracker.unity3d.com/issues/inserting-transforms-between-the-gameobject-having-the-animator-component-and-the-root-of-the-skeleton-causes-resolve-errors) |
| Model swapped, but the Animator still holds the old avatar | wrong or missing bones | — |
| Rig left on Generic by mistake | no Humanoid retargeting | — |
| Forearm mapped to a twist or roll bone | distorted hands | [forum](https://discussions.unity.com/t/fbx-from-maya-importing-with-wrong-joint-rotation/675447) |
| Twist bones ignored by Humanoid | twisting artifacts | [Reallusion tracker](https://www.reallusion.com/FeedBackTracker/Issue/The-twist-bones-in-exported-rigs-are-ignored-by-Unity-s-humanoid-rig-causing-severe-joint-distortions) |
| Not in T-pose, or bad roll | warnings about bone roll | [forum](https://discussions.unity.com/t/importing-fbx-from-blender-root-motion-warps-animation/1486947) |

Twist bones need helper constraints or must be left out of the mapping.

**(d) Texture.** Not applicable.

**(e) Automation.** Fully scripted, including batch mode with `-executeMethod`. Blender writes the `unity_human` map, so Unity never guesses.

**(f) Engines.** Unity.

**Proof render in batch mode.** Load a Starter Assets or Quaternius clip and call `AnimationMode.SampleAnimationClip` per frame. Then `Camera.Render()` into a RenderTexture and write PNGs. Do not use `-nographics`. The Recorder package needs Play mode, so it is a worse fit. Starter Assets includes Humanoid idle, walk, run, jump and land clips ([Unity blog](https://unity.com/blog/games/say-hello-to-the-new-starter-asset-packages)).

## F8. Generic and quadruped skeletons

**(a) Why it matters.** Unity Generic clips bind by transform path and cannot retarget between different skeletons. Unity's Generic root motion also expects all rigs to share "the same topology and same proportion" ([Unity forum thread](https://discussions.unity.com/t/bake-into-pose-missing-in-unity-5-6-0b9/660825)). UE retargets quadrupeds only through manually defined chains.

**(b) Topology.** For each chain, store a "role" in the manifest (front_leg, back_leg, tail, wing, neck, jaw, spine). Roles must match across creatures of the same archetype, so one creature's library can be reused on another.

**(c) Rig.**
- ARP: UNIVERSAL export for these rigs. The extra limbs are already covered by the earlier ARP-limbs research.
- UE: IK Rig chains from the manifest, with IK goals on paws/feet so retargeted stride stays planted.
- Unity: Generic with `motionNodeName=root`.
- All non-human clips are retargeted in Blender onto the exact exported skeleton before export.

**(d) Texture.** Not applicable.

**(e) Automation.** Licensed quadruped libraries are scarce and inconsistent:
- Truebones Free Zoo: free-promo status and license unclear ([Truebones](https://truebones.gumroad.com/p/free-zoo-from-truebones-reminder-of-terms-of-use)). UNVERIFIED for commercial use.
- Mixamo: no quadrupeds.

Forge should therefore generate procedural test clips in bpy, which are license-free and deterministic:
- **Gaits:** walk with footfall order LH-LF-RH-RF at 25% phase offsets; trot with diagonal pairs.
- **How:** drive the ARP foot IK controllers along arcs, add a pelvis bob, then bake with `bpy.ops.nla.bake(visual_keying=True)`.
- **Other clips:** tail sine wave with per-bone phase lag; wing flap; jaw open/close; head look-around.

These clips prove deformation and chain direction, which is what the director needs to approve, even though they are not hero animation.

**(f) Engines.** UE: use the manifest chains for any later real quadruped library. Unity: Generic only.

## F9. Root bone and root motion

**(a) Why it matters.** Locomotion sets ship as in-place and as root-motion versions.
- UE: needs the motion on the `root` bone, with Enable Root Motion set per AnimSequence.
- Unity Humanoid: derives root motion from the body centre of mass. Bake Into Pose and the Root Transform options apply.
- Unity Generic: uses the Root Node ([Unity Root Motion manual](https://docs.unity3d.com/Manual/RootMotion.html)).

**(b) Topology.** Not applicable.

**(c) Rig.** Use one ground-level `root` bone at the origin, Z up, facing −Y in Blender. That maps to +X forward in UE once `mannequin_axes` and axis conversion are applied; verify with a test clip.

Mixamo has no root bone; the translation sits on `mixamorig:Hips`. Extract it with ARP:
- `arp.retarget(extract_root_motion=True, loc_x=True, loc_y=True, loc_z=False, loc_z_offset=True, rotation=True, forward_axis='Z', interpolation_type='LINEAR')`. All parameter names are measured.
- Or `arp.extract_root_motion` / `arp.clear_root_motion` separately.
- `arp_retarget_in_place` is the In Place toggle.

Export with `arp_ue_root_motion=True` for root-motion clips.

**(d) Texture.** Not applicable.

**(e) Automation.** Fully scripted.
- Keep two variants per locomotion clip: `_RM` and `_IP`.
- Validate root motion: root path length per cycle ≈ stride length, and pelvis XY relative to root stays under about 5 cm drift.
- UE: `seq.set_editor_property("enable_root_motion", True)`.
- Unity: per-clip `ModelImporterClipAnimation` settings — `lockRootRotation`, `lockRootHeightY`, `lockRootPositionXZ`, `keepOriginalOrientation`/`keepOriginalPositionY`/`XZ`, `loopTime`.

**(f) Engines.** Retargeting with mismatched units multiplies root and hip motion by 100 (F2). One UE forum thread reports retargeted root-motion scaling not working ([forum](https://forums.unrealengine.com/t/retargeting-root-motion-scale-is-not-working/1899296)). Measure it rather than trust it.

## F10. Headless Blender retargeting and director test clips

**(a) Why it matters.** Range-of-motion poses do not catch foot sliding, arm-body penetration, popping, shoulder collapse or tail flipping. Walk, run and attack clips do.

**(b) Topology.** Not applicable. Penetration problems found here go back to the topology step.

**(c) Rig.** Two retarget engines:
1. **ARP Remap** (measured operators): `arp.auto_scale`, `arp.build_bones_list`, `arp.import_config` (.bmap mapping), `arp.export_config`, `arp.redefine_rest_pose`/`arp.cancel_redefine`, `arp.save_pose_rest`, `arp.retarget(frame_start, frame_end, …)`, `arp.retarget_bind_only` (quick preview), `arp.batch_retarget`, `arp.remap_enable_all_actions`, `arp.toggle_action_remap(action_name)`.
   - Scene flags: `arp_remap_allow_root_update`, `arp_retarget_in_place`, `arp_remap_only_containing`.
   - The source/target property names are not in the `arp_*` dump. One community script sets them on the scene (UNVERIFIED names). Probe with `[p for p in bpy.types.Scene.bl_rna.properties.keys() if 'rig' in p]` on the user's machine.
   - Generate the .bmap from Forge's own name normaliser (`arp_rig.norm`, which already strips `mixamorig`) instead of relying on ARP's bundled presets.
2. **Pure-bpy fallback with no UI dependency.** For each mapped bone, add a world-space Copy Rotation constraint, plus Copy Location on the pelvis scaled by the height ratio, with rest-pose offsets compensated. Then `bpy.ops.nla.bake(visual_keying=True, clear_constraints=True)`. Use this for quadrupeds and creatures, and as a cross-check.

**Blender 4.4+ slotted actions.** Scripts must assign `anim_data.action` and `anim_data.action_slot`, or retargeted clips play nothing. ARP 3.79 has slot-aware export (`arp_export_slot_separator`, measured), so the API exists there. This is an inferred, high-risk breakage point for Blender 5.3.

**(d) Texture.** Use a test-render material override. Body: matcap or clay. Penetration: a red mask, from a per-frame BVH-tree overlap of hand and arm vertices against the torso. No new textures needed.

**(e) Automation.** Fully scripted:
- Per asset, 4 clips (idle, walk, run, attack) from 3 cameras (front, side, ¾), rendered in Workbench or EEVEE to MP4 with `bpy.ops.render.render(animation=True)` and FFMPEG.
- Plus one contact sheet with metric badges.
- The director only approves or rejects.

**(f) Engines.** The Blender clips are the universal proof. The UE (F6) and Unity (F7) renders are confirmation that the export contract holds.

## F11. Animation libraries: what can be used where

| Set | License | Rig | Where Forge may use it |
|---|---|---|---|
| **Quaternius Universal Animation Library 1 & 2** (120+/130 clips) | CC0 | One universal humanoid, FBX/GLB; the .blend source is a paid tier | **Best default** for headless Blender test clips; can be redistributed with Forge ([quaternius.com](https://quaternius.com/packs/universalanimationlibrary.html), [OGA](https://opengameart.org/content/universal-animation-library), [UE community tutorial, 5.6](https://forums.unrealengine.com/t/community-tutorial-getting-started-with-free-character-animations-from-quaternius/2636072)) |
| **Mixamo** | Free; commercial use OK when embedded in a product; no redistributing raw files; no attribution needed ([Adobe community FAQ](https://community.adobe.com/t5/mixamo-discussions/mixamo-faq-licensing-royalties-ownership-eula-and-tos/td-p/13234775); official helpx FAQ not fetched, so UNVERIFIED) | `mixamorig:` T-pose, cm | User downloads a fixed local test pack "without skin" once. Do not automate downloads: the community scripts use undocumented endpoints that break ([gist](https://gist.github.com/gnuton/ec2c3c2097f7aeaea8bb7d1256e4b212)) and may conflict with the ToS (UNVERIFIED). |
| **UE Game Animation Sample** (500+ clips) | Epic content; use it with or without its Blueprints and retarget it to your characters ([Epic blog](https://www.unrealengine.com/en-US/blog/game-animation-sample)). Export to Blender/Unity is likely not allowed by Epic's terms (UNVERIFIED) | Manny/Quinn (A-pose) | **Inside UE only** (F6 test + MRQ render) |
| **Unity Starter Assets – Third Person** | Unity Companion License on some listings, "Non standard EULA" on another (inconsistent; read `Assets/StarterAssets/license.txt`) | Humanoid | **Inside Unity only** (F7 test) |
| **CMU mocap (BVH)** | Widely described as free for any use (UNVERIFIED in this session) | Varies; needs cleanup | Optional extra test motions |
| **Tripo `animations/retarget` presets** | Tripo terms | Tripo rig | Already planned in ROADMAP Phase 5; a useful source, since they come with the asset |
| **Quadrupeds** | Truebones free zoo (status and license unclear); otherwise none found | — | Use procedural gaits (F8) |

## F12. Automated QA metrics shown next to the video

All computed in bpy on the baked target action:
- **Foot slide:** world XY speed of `foot_l/r` while foot Z < contact height + 2 cm, in cm per contact. Fail above about 3 cm (UNVERIFIED threshold; tune it).
- **Penetration:** BVH overlap volume or vertex count of hands and forearms against torso, and thigh against thigh, per frame.
- **Joint flips:** quaternion sign or axis jumps above 90° between frames; elbow and knee pole flips.
- **Stretch:** deformed edge length versus rest above 1.5× (candy-wrapper twist at forearm or upper arm).
- **Root health:** root path consistent and pelvis offset bounded (F9).
- **Unit sanity:** pelvis height versus manifest (F2).

Results go to `qa.py`/supervisor as JSON. Badges are green/amber/red.

## F13. What can be fully scripted

- **Blender, fully:** ARP export presets, checks and fixes, re-import validation, manifest, Remap retarget or constraint bake, procedural creature clips, renders, metrics.
- **UE Python, fully** (pinned version): FBX import, IK Rig from the manifest or auto-generated, IK Retargeter (map, align, ops), batch duplicate-and-retarget, root-motion flags, Level Sequence, MRQ render. MRQ may need a windowed editor.
- **Unity editor script, fully:** AssetPostprocessor with Human or Generic setup, a HumanDescription built from the manifest, avatar validity report, Animator Controller stub, frame capture with `AnimationMode` and `Camera.Render`.
- **Needs a human:**
  - the one-time Mixamo pack download;
  - the director's single "arm-angle offset" override when auto-align shoulders look wrong;
  - license sign-off for GASP and Starter Assets use.

## F14. What breaks most often, ranked, with the Forge guard

1. **Rest-pose mismatch (A vs T)** → arms, shoulders and hands off. Guard: manifest `rest_pose`, auto-align, Unity T-pose `SkeletonBone`s.
2. **×100 scale** (root scale 100, hips ×100, Mixamo 0.01 objects) → flying or tiny characters, broken root motion. Guard: F2 re-import validator.
3. **Wrong chains** (twist or IK bones inside chains, wrong start/end, fuzzy auto-map mistakes) → twisted forearms, frozen limbs. Guard: manifest chains with exclusions; auto-map EXACT, then diff.
4. **Bone roll and axis inconsistency** → thumbs, feet, fingers. Guard: F3 curl-axis check plus `arp_mannequin_axes`.
5. **Root motion convention** (Mixamo hips-only translation, missing extraction, Humanoid Bake Into Pose settings) → sliding or drifting. Guard: `_RM`/`_IP` variants plus the root health metric.
6. **Unity "Avatar is not valid"** (missing required bone, partial skeleton list, copied avatar, hierarchy changed afterwards). Guard: manifest-driven `HumanDescription` plus a post-import `isValid` assert.
7. **Extra roots and leaves** (object named "Armature", `_end` leaf bones, `root_aprbaseobject`). Guard: name rules and `add_leaf_bones=False`.
8. **Version drift:**
   - Blender 4.4+ slotted actions;
   - UE 5.6 op-stack API change (`op_stack` deprecated) and `duplicate_and_retarget` signature changes;
   - ARP Remap fixes per release.

   Guard: pin versions and keep a probe script like `addon_probe.py` per engine.
9. **Stylized proportions** → penetration and foot slide even with a correct setup. Guard: metrics and IK-goal ops (UE IK Chains op, foot goals). Report these; don't hide them.
10. **IK helper bones not animated** (`ik_foot_*`, `ik_hand_*`) after retargeting. Guard: post-process copy, or an op where available (UNVERIFIED).

---

**Repo files consulted:**
- /home/user/Image-to-Game-asset/blender_scripts/forge_bpy/arp_rig.py
- /home/user/Image-to-Game-asset/blender_scripts/forge_bpy/finalize.py
- /home/user/Image-to-Game-asset/jobs/_setup/addon_probe.json
- /home/user/Image-to-Game-asset/jobs/_setup/addon_trial.json
- /home/user/Image-to-Game-asset/jobs/_setup/addon_trial2.json
- /home/user/Image-to-Game-asset/docs/ROADMAP.md (Phase 5)

**Hosts to allow for full verification:** www.lucky3d.fr (ARP docs: export and Remap pages), dev.epicgames.com and api.unrealengine.com (exact Python signatures for 5.6+, the IK_Mannequin chain list, auto-retarget templates), huggingface.co (the ARP retarget community script).
