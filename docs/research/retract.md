# Research: retract (fact-checked)

FACT-CHECKED REPORT: hidden, retractable and deployable parts (claws, tongue, stinger, folding wings, growing spikes, glowing parts) in Forge

Verification basis:
- The most reliable source was the repo's own probe of the installed add-ons (Auto-Rig Pro 3.79.17 in Blender 5.3): /home/user/Image-to-Game-asset/jobs/_setup/addon_probe.json.
- Web search snippets were used for the rest.
- These hosts were not reachable from this session (DNS blocked), so their pages could not be opened directly: docs.blender.org, dev.epicgames.com, docs.unity3d.com and www.lucky3d.fr. Claims that depend on them are confirmed from search excerpts or marked UNVERIFIED. They must be allowed in the network settings to check further.

Labels used below:
- CONFIRMED: the claim was checked against a source.
- CORRECTED: the original claim was wrong or incomplete and has been fixed.
- UNVERIFIED: no reachable source confirmed it.
- KNOWN-API: matches the stable public API, but the docs host was blocked.

## 0. Corrections that change the implementation (read first)

1. **Forge exports through ARP, not the native FBX operator.** finalize.py calls `bpy.ops.arp.arp_export_fbx_panel`. The `bake_anim_*` flags of `export_scene.fbx` therefore do not apply. Use these ARP Scene props, taken from addon_probe.json with their installed defaults:
   - `arp_bake_anim` (True)
   - `arp_bake_type` ("ACTIONS")
   - `arp_bake_only_active` (**True by default**: only the active action is exported. Set it to False to export all Deploy_* clips.)
   - `arp_bake_only_active_slot` (True)
   - `arp_export_use_actlist` (False) and `arp_export_actlist`: an explicit per-export action list. Operators include `arp.actions_list_add`, `arp.actions_list_add_action`, `arp.actions_list_add_batch_actions` and `arp.ge_select_allactions`.
   - `arp_simplify_fac` (**0.01 by default**: set it to 0.0 so small claw travel is not lost)
   - `arp_ge_startend_keying` (True)
   - `arp_ge_startend_keying_sk` (**False by default**: set it to True for shape-key clips)
   - `arp_ge_bake_sample` (1.0)
   - `arp_frame_range_type` ("FULL"), `arp_export_start_frame` and `arp_export_end_frame`
   - `arp_export_separate_fbx`
   - `arp_ge_sel_bones_only`
   - `arp_keep_bend_bones`
   - Status: CONFIRMED (names and defaults from the probe). The enum items of `arp_bake_type` and `arp_frame_range_type` are UNVERIFIED; dump them with `_scene_enums("arp_", ...)`.

2. **How ARP flags custom bones: it uses a bone tag, not only the name prefix.**
   - The probe shows `Scene.arp_bone_tag_show = "cc"`. It also lists the operators `arp.set_bone_tag`, `arp.unset_bone_tag`, `arp.bone_tag_add`, `arp.bone_tag_remove` and `arp.bones_tag_manager`, plus `arp_custom_bones_list`.
   - The ARP docs, as quoted on Blender Artists, say: "make sure their names start with 'cc_' ... This prefix is the key to notify the exporter". The 3.59 changelog added set/unset buttons "avoiding the tedious work of renaming bones or adding custom properties".
   - Status: CONFIRMED that the "cc_" prefix works and that a "cc" tag mechanism exists.
   - UNVERIFIED: the parameters of `arp.set_bone_tag` (the probe returned null) and where the tag is stored (believed to be a bone custom property "cc").
   - Safest approach: use the `cc_` name prefix **and** call `arp.set_bone_tag` on the selected bones, wrapped in try/except. Then confirm with `arp.check_rig_export` or by re-importing the FBX.
   - Sources: https://blenderartists.org/t/auto-rig-pro-3-59/672834?page=43 and https://superhivemarket.com/products/auto-rig-pro/versions

3. **Unity citation for scale-curve cost: CORRECTED.**
   - The quote "Animating scale curves is more expensive than animating translation and rotation curves" is on the Mecanim Performance and Optimization page, not ModelingOptimizedCharacters.
   - Source: https://docs.unity3d.com/Manual/MecanimPeformanceandOptimization.html (also on the 6000.3 manual).
   - Status: the claim is CONFIRMED.

4. **Unreal attribute import options: CORRECTED names.**
   - Legacy FBX importer option: "Import Custom Attribute".
   - Interchange option (the default FBX path in 5.5+): "Import Attributes as Curves or Animation Attributes".
   - Project Settings > Engine > Animation > Custom Attributes has "Bone Custom Attribute Names" and "Bone Names with Custom Attributes". The report's "Bone Animation Attributes Names" is wrong.
   - Interchange has known regressions: attributes come in as curves only (UE 5.8.2 report), and curves failed to import in 5.3 to 5.5. The fallback is the console variable `Interchange.FeatureFlags.Import.FBX false`, which switches back to the legacy importer.
   - Sources:
     - https://dev.epicgames.com/documentation/unreal-engine/fbx-attributes-in-unreal-engine
     - https://forums.unrealengine.com/t/importing-fbx-animation-attributes-does-not-seem-to-work-with-interchange-5-8-2/2843197
     - https://forums.unrealengine.com/t/5-5-not-able-to-import-animation-curves-since-5-3-5-5/2267442

5. **The keyframe code example is internally inconsistent: CORRECTED.**
   - It sets every key to LINEAR, which contradicts the "CONSTANT snap on scale" rule, and it never adds the frame-1 scale key.
   - Interpolation modes do not survive FBX anyway. Both exporters sample the action every frame, so the engines only see per-frame samples.
   - Fix: key scale = 0.001 at frame 0 and scale = 1 at frame 1. Engines will lerp scale over that one frame, which is acceptable. If an instant snap is required, drive the scale in game code instead (see section 1A, procedural option).

6. **The inside-body test is wrong as written: CORRECTED.**
   - `mathutils.bvhtree.BVHTree.ray_cast` returns only the first hit, so it cannot do an odd/even count in one call.
   - Option 1: loop the ray_cast calls, restarting each one from hit + epsilon along the ray, and count the hits.
   - Option 2 (simpler): call `BVHTree.find_nearest(p)`, which returns `(loc, normal, index, dist)`. The point is inside when `(p - loc).dot(normal) < 0`. This needs a closed mesh with consistent normals. Run Forge's repair step first.

## 1. Four ways to hide a part (rule: choose per part)

### A. Bone translation into the body plus near-zero scale (default for claws and stingers)

- **The 0.001 rule:** CONFIRMED by the Unity forum thread "Blender Armature Animation - Scaling from zero doesn't work" (2017). Meshes whose bone starts at scale 0 never appear, and meshes that shrink to 0 mid-clip flicker. https://forum.unity.com/threads/blender-armature-animation-scaling-from-zero-doesnt-work.457076/
- **UE HideBoneByName:** CONFIRMED.
  - The docs say it "only enforces a scale of 0 for the hidden bones". Children are hidden too.
  - Its PhysBodyOption parameter is accepted but ignored in the implementation, according to forum source reading.
  - Components attached to the bone stay visible (forum thread 2852162).
  - UE-220481 is CONFIRMED: the hidden bone and its children are translated to the parent's location, which breaks skinned vertices. A fix was proposed behind a console variable; its status is UNVERIFIED.
  - Sources: https://issues.unrealengine.com/issue/UE-220481 and https://forums.unrealengine.com/t/hidebonebyname-does-not-affect-attached-components/2852162
- **Leaf bones, no physics bodies, kinematic-only colliders:** sound practice, not checked against a source.
- **ADDED, procedural alternative (recommended as the first path):** for kind A, deploy needs no exported clip at all.
  - UE: AnimBP "Transform (Modify) Bone" node, translation mode "Add to Existing", on `cc_*` bones. Translation = axis × (1 − Deploy) × −travel. Scale is driven the same way. KNOWN-API.
  - Unity: a LateUpdate script sets `localPosition` and `localScale` on the claw transforms. With "Optimize Game Objects" on, those transforms must be exposed.
  - This avoids every FBX animation export problem and gives a true snap on scale. The Forge manifest already carries the axis and travel needed.

### B. Bone chain stretched by translation (tongue, tentacle, whip tail)

- Use unconnected bones (`use_connect=False`) and translate them along their local axis. Avoid non-uniform scale, because children inherit it and the mesh shears. Sound practice.
- Spline IK, other constraints and drivers do not export. Bake them to FK (see section 4b). CONFIRMED in principle.
- ARP has built-in tail, spline IK and B-bone limbs (`arp.add_limb` is in the probe), with export bugs listed in the changelog. Whether its spline IK limb exports through the Humanoid rig type is UNVERIFIED.
- Runtime aiming: the UE AnimGraph "Spline IK" and "FABRIK" nodes exist (KNOWN-API), and so does Unity Animation Rigging `ChainIKConstraint` (KNOWN-API, package com.unity.animation.rigging). Per-version details in UE 5.x and Unity 6 remain UNVERIFIED.

### C. Morph target / shape key (spikes, gills, frills, swelling)

- Create the keys after Quad Remesher, because retopo destroys shape keys. CONFIRMED by the mechanism: vertex count changes.
- Transfer with the Surface Deform modifier (bind, then "Apply as Shape Key") or with Data Transfer. KNOWN-API.
- UE: curve name = morph name. The original report's link list is kept. Known 5.5 import issue: https://forums.unrealengine.com/t/importing-meshes-in-5-5-does-not-add-morph-targets-to-curves-on-skeleton/2247798
- ADDED: turn **off** the UE animation import option "Do not import curves with only 0 value". It exists on the legacy importer; the Interchange equivalent is UNVERIFIED. If it stays on, a hidden-only clip loses its morph curve.
- Unity: "Legacy Blend Shape Normals" is CONFIRMED to exist in the Model tab (6.2 and 6.3 docs). With it disabled, a "Blend Shape Normals" dropdown appears with Import / Calculate / None. Recommendation: Legacy off, Blend Shape Normals = Import. Importing blend-shape normals needs smoothing groups in the FBX, so export with `mesh_smooth_type="FACE"`, which Forge already uses. Source: https://docs.unity3d.com/Manual/FBXImporter-Model.html

### D. Material mask or separate mesh

- The UE Masked / Opacity Mask approach and the Unity URP `_AlphaClip` / `_Cutoff` approach are standard. KNOWN-API.
- The UE anim curve "Material" type exists (KNOWN-API). The docs page was not reachable.
- Mobile: alpha-test defeats early-Z / hidden-surface removal on tile-based GPUs, so put deployables on a separate slot. Sound practice.
- Separate mesh:
  - UE `SetLeaderPoseComponent`: KNOWN-API, UE 5.1+; it replaced `SetMasterPoseComponent`.
  - Socket attach and Unity child transform: standard.
- Reuse `_prop_to_static()` from finalize.py, as the report says.

The per-type recommendation table stands.

## 2. Bind-pose decision

- **Bind in the deployed state and make "hidden" the runtime default.** Sound. Unkeyed bones fall back to the reference pose in both engines.
- **UE override layer:** Layered Blend per Bone plus a Sequence Evaluator with Explicit Time. KNOWN-API. Alternatively use the procedural Modify Bone approach from section 1A.
- **Unity layer:** Override layer with weight 1 and an AvatarMask. The state's normalized time can be bound to a float parameter (`AnimatorState.timeParameterActive` / `timeParameter`). CONFIRMED: the Inspector label was renamed "Motion Time" in 2019.3. Note that `AnimatorStateInfo.normalizedTime` read from script will differ from the motion time; Unity says this is expected. https://issuetracker.unity3d.com/issues/animatorstateinfo-dot-normalizedtime-returns-the-total-play-time-of-animation-state-when-normalized-value-is-set-to-parameter
- **Binding in the hidden state:** ARP has `arp.copy_bone_rest` and `arp.bake_rot_from_scale` in the probe, but no confirmed "apply pose as rest including meshes" operator. Remains UNVERIFIED, and not recommended.
- **Clip convention** (frame 0 = hidden, last frame = deployed, linear): fine.

## 3. Per-part JSON

- Storing it on `rig.data.bones[name]["forge_deploy"]` (an IDProperty) works. Tidy-up: store it under a non-"cc" key so it does not collide with the ARP "cc" tag.
- The parent name `hand.l` is UNVERIFIED for every ARP rig type. ARP's deform hand bone is typically `hand.l` before export renaming, and becomes `hand_l` with `arp_rename_for_ue`. Resolve it at runtime from the rig instead of hard-coding it.
- Fix the inside-body check as described in section 0, item 6.

## 4. Building it in bpy (Blender 5.x)

### a) Bones
- `edit_bones.new`, then set head/tail, parent, `use_connect` and `use_deform`. KNOWN-API.
- Flag the bones as in section 0, item 2.
- Weights: a rigid 1.0 vertex group plus an Armature modifier, and remove body-bone weights from those vertices. Fine.

### b) Deploy action
- **Removal of `Action.fcurves`, `.groups` and `.id_root` in 5.0:** CONFIRMED. https://docs.blender.org/api/5.0/change_log.html
- **Channelbags:** `ActionChannelbag.fcurves` / `.groups` and `ActionChannelbagFCurves.ensure(data_path, index=0, group_name='')`: CONFIRMED in the 5.0 docs.
- **`bpy_extras.anim_utils.action_get_channelbag_for_slot(action, slot)`:** CONFIRMED in the 5.3 docs. `action_ensure_channelbag_for_slot` also exists.
- **Slot assignment:** `pb.keyframe_insert` on an action with no slot creates and assigns a slot (KNOWN-API behaviour). Read `ad.action_slot` *after* the first key, not before.
- **Scale interpolation:** see section 0, item 5. Add an explicit scale key at frame 1.
- **Baking the tongue:** `bpy.ops.nla.bake(frame_start, frame_end, step=1, only_selected=True, visual_keying=True, clear_constraints=False, clear_parents=False, use_current_action=True, clean_curves=False, bake_types={'POSE'}, channel_types={...})` is KNOWN-API (the docs host was blocked). Keep `clean_curves=False` so constant channels survive.
- **Shape-key action:** key `key_blocks[...].value` on the Key ID, which gets its own action and slot. Do not share one slotted action between the Object and the Key for FBX export: the exporter's support for that is UNVERIFIED.
- **Animated custom props through FBX:** CONFIRMED as unreliable. ARP's changelog says animated props on custom bones work "only with specific patched exporters (the builtin FBX and GLTF exporters don't support that yet)". The proxy-bone approach, or the engine-side curve approach, remains correct.
- **UE Python:** `unreal.AnimationLibrary.add_curve(anim_seq, curve_name, curve_type=FLOAT, ...)` and `unreal.AnimationLibrary.add_float_curve_keys(anim_seq, curve_name, times, values)` are CONFIRMED. A forum thread reports it is slow when run over many curves in UE5.0. https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/AnimationLibrary and https://forums.unrealengine.com/t/ue5-0-python-api-add-any-keys-to-float-curves-of-anim-sequence-is-very-slowly/638740
- **Unity `AssetPostprocessor.OnPostprocessGameObjectWithAnimatedUserProperties`:** the API is real. Whether Blender FBX carries animated user properties remains UNVERIFIED, and is likely not, given the item above.

### c) Approval preview strip
Fine.

## 5. Export

- **Native `export_scene.fbx` flag names:** `bake_anim`, `bake_anim_use_all_bones`, `bake_anim_use_all_actions`, `bake_anim_use_nla_strips`, `bake_anim_force_startend_keying`, `bake_anim_simplify_factor`, `add_leaf_bones`, `use_armature_deform_only`. KNOWN-API.
  - `simplify_factor = 0` is CONFIRMED by Blender developers as the way to disable simplification. https://projects.blender.org/blender/blender/issues/64446
  - Force start/end keying is CONFIRMED as "the way to get keys at start/end".
  - ADDED: also set `bake_anim_use_all_bones=True` (Key All Bones). That flag, not start/end keying, keys channels that were never animated. https://projects.blender.org/blender/blender-addons/issues/105226
- **Blender 5.x status:** the Python FBX add-on is now labelled "FBX (Legacy)" in the manual. A new C++ importer exists (`bpy.ops.wm.fbx_import`, since 4.5). No C++ exporter was found, so `export_scene.fbx` and ARP's patched exporter remain the export path. UNVERIFIED for 5.3. https://developer.blender.org/docs/release_notes/4.5/pipeline_assets_io/
- **For Forge, use the ARP props in section 0, item 1:**
  - `arp_bake_only_active=False`, or `arp_export_use_actlist=True` with a filled `arp_export_actlist`
  - `arp_simplify_fac=0`
  - `arp_ge_startend_keying_sk=True` for morph clips
  - `arp_export_separate_fbx` for per-clip files
- **Shape-key animation lost with all-actions / NLA:** the original citations (issues 105425 and 104759) are kept. They were not re-opened because the projects.blender.org pages were not fetched. The mitigation stands: one FBX per morph clip, with only that action active.
- **Slotted actions and all-actions / ARP bake:** UNVERIFIED. ARP 3.79 exposes `arp_bake_only_active_slot`, which shows it is slot-aware. Test with a minimal file.
- **UE import:** use the corrected option names from section 0, item 4. Also:
  - Import Morph Targets on.
  - "Do not import curves with only 0 value" off.
  - Sockets on claw-tip bones.
  - Translation Retargeting "Animation" on deploy bones.
- **Unity import:**
  - Humanoid clips need deploy transforms added in the clip's Mask → Transform list. KNOWN-API.
  - Compression: Off / Keyframe Reduction / Optimal, with Position / Rotation / Scale error settings. KNOWN-API.
  - When "Optimize Game Objects" is on, add the claw-tip transforms to "Extra Transforms to Expose". KNOWN-API.
  - Blend shapes: see section 1C.
- **Manifest and engine template scripts:** recommendation stands.

## 6. Budgets (rules of thumb, not hard limits)

- Unity's own legacy guidance for optimised characters suggests roughly 15 to 60 bones. That is tighter than the report's "≤75 on mobile". Suggested Forge targets: mobile body ≤ 60 to 75 including deployables, using one bone per claw group. UNVERIFIED as a hard limit; the page was not reachable.
- Unity URP skin weights: Project/Quality "Skin Weights" setting (1, 2, 4 or Unlimited bones). Use 2 to 4 on mobile. KNOWN-API.
- The other rows (morph count, claw triangle counts) are UNVERIFIED heuristics. Keep them, labelled as such.

## 7. Pitfalls (corrected list)

The original list stands, plus:
- ARP defaults `arp_bake_only_active=True` and `arp_simplify_fac=0.01` will silently drop Deploy clips or flatten small motion.
- `arp_ge_startend_keying_sk` defaults to False.
- Interchange (UE 5.5+) may import attributes as curves, or fail to import them. Keep the legacy-importer CVar fallback documented.
- In Unity, scripts that read `AnimatorStateInfo.normalizedTime` will not match the parameter-driven Motion Time.
- HideBoneByName collapses the bone and its children to the parent's location (UE-220481) and ignores its physics option.
- A single ray_cast cannot do an inside test. Use the find_nearest normal test.

## Next probe to add (addon_trial.py)

- Inspect `bpy.ops.arp.set_bone_tag.get_rna_type().properties`.
- Dump the enum items of `arp_bake_type` and `arp_frame_range_type`.
- Export a 2-bone `cc_` test with 2 actions and `arp_bake_only_active=False`, re-import it, and assert that both takes exist and the `cc_` bone is present.

## Sources

- https://blenderartists.org/t/auto-rig-pro-3-59/672834?page=43
- https://superhivemarket.com/products/auto-rig-pro/versions
- https://docs.blender.org/api/5.0/change_log.html
- https://docs.blender.org/api/5.3/bpy_extras.anim_utils.html
- https://docs.blender.org/api/5.0/bpy.types.ActionChannelbag.html
- https://developer.blender.org/docs/release_notes/4.5/pipeline_assets_io/
- https://projects.blender.org/blender/blender/issues/64446
- https://projects.blender.org/blender/blender-addons/issues/105226
- https://docs.unity3d.com/Manual/MecanimPeformanceandOptimization.html
- https://docs.unity3d.com/Manual/FBXImporter-Model.html
- https://issuetracker.unity3d.com/issues/animatorstateinfo-dot-normalizedtime-returns-the-total-play-time-of-animation-state-when-normalized-value-is-set-to-parameter
- https://forum.unity.com/threads/blender-armature-animation-scaling-from-zero-doesnt-work.457076/
- https://dev.epicgames.com/documentation/unreal-engine/API/Runtime/Engine/USkinnedMeshComponent/HideBoneByName
- https://issues.unrealengine.com/issue/UE-220481
- https://forums.unrealengine.com/t/hidebonebyname-does-not-affect-attached-components/2852162
- https://dev.epicgames.com/documentation/unreal-engine/fbx-attributes-in-unreal-engine
- https://forums.unrealengine.com/t/importing-fbx-animation-attributes-does-not-seem-to-work-with-interchange-5-8-2/2843197
- https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/AnimationLibrary
- https://forums.unrealengine.com/t/ue5-0-python-api-add-any-keys-to-float-curves-of-anim-sequence-is-very-slowly/638740
- Local file: /home/user/Image-to-Game-asset/jobs/_setup/addon_probe.json (ARP 3.79.17 props and operators)
