# Research: mech (fact-checked)

## Fact-checked and corrected report: mechanical rigs and secondary motion (tails, ears, tongue, claws, hinges, pistons, gears, chains) for Forge

**How this was checked.** docs.blender.org, lucky3d.fr (the ARP docs), superhivemarket.com, dev.epicgames.com, docs.unity3d.com, the Unity and Unreal forums, blenderartists.org and magicasoft.jp do not resolve from this session, so all of them would need allowing in the network settings. I checked against these instead:
- **Blender source** at https://github.com/blender/blender (main branch, `BLENDER_VERSION 504`, which is 5.4 alpha). The user runs 5.3, so anything marked "CONFIRMED (main)" should be re-checked on 5.3 with the repo's probe.
- **The ARP probe results already captured on the user's PC** (Blender 5.3, ARP 3.79.17): `jobs/_setup/addon_probe.json`, `addon_trial.json`, `addon_trial2.json`.
- **GitHub clones** of KawaiiPhysics, the Unity Animation Rigging package mirror and UniVRM.

Engine-side claims I could not re-fetch are marked UNVERIFIED (not re-fetched). They match prior knowledge but were not checked this pass.

### Biggest corrections (read first)
1. **Blender's FBX exporter already bakes constraints and drivers.** `fbx_animations_do` calls `scene.frame_set()` on every frame and writes the evaluated pose (export_fbx_bin.py around lines 2253–2380). Explicit `nla.bake` is therefore optional for the Blender FBX path. What matters is that each clip's action animates the *driving* property, such as `arm["open"]`.
   - ARP's exporter also bakes: `Scene.arp_bake_anim=True` and `Scene.arp_ge_bake_sample=1.0` in the probe.
   - The report's "must bake before export" is **CORRECTED**: baking is a safety step, not a requirement.
2. **Pitfall the report missed: after `nla.bake`, the drivers and constraints still run.**
   - In Blender's evaluation order, drivers overwrite F-curve values on the same channel. So a baked `rotation_euler` key is replaced by the driver reading a now-static `arm["open"]`.
   - Constraints are applied on top of the baked visual keys (`clear_constraints=False`). For Damped Track and Copy Rotation that means the transform is applied twice.
   - If you bake, then before export either mute them (`fc.mute=True` for each driver in `arm.animation_data.drivers`, `con.mute=True` for each constraint) or export from a copy of the armature with `clear_constraints=True` that has its drivers removed.
3. **Animated custom properties are not exported. CONFIRMED.**
   - The Blender FBX exporter writes curves only for object and bone transforms, shape keys, camera focal length and focus distance (export_fbx_bin.py lines 2285–2311).
   - `use_custom_props` (default False) writes **static** custom properties, and for bones it reads them from the data `Bone` (`bo_obj.bdata`), not the `PoseBone`. Any tag meant to reach the FBX must go in `arm.data.bones[n]["forge_mech"]`.
   - Neither engine is known to turn FBX bone user-properties into physics setup, so the sidecar JSON remains the transport.
   - ARP's changelog says animated custom-bone properties export only through "specific patched exporters".
4. **Gear ±180° wrap: CORRECTED.**
   - Blender's FBX exporter writes Euler XYZ rotation that is made continuous with the previous frame (`fbx_object_tx(..., rot_euler_compat=p_rot)` then `rot.to_euler('XYZ', compat)` in fbx_utils.py line 1827).
   - `anim_utils` bakes also make quaternions continuous (`quat.make_compatible`, anim_utils.py lines 570–576).
   - So a continuously spinning gear does not snap in the FBX. The remaining risk is aliasing when a gear turns more than 180° per sampled frame.
   - Engine-side spinning is still the better choice for looping or speed-driven gears.
5. **The ARP custom-bone flag in 3.79.17 is a "bone tag" system. CORRECTED (was UNVERIFIED).**
   - The probe lists operators `arp.set_bone_tag`, `arp.unset_bone_tag`, `arp.bone_tag_add`, `arp.bone_tag_remove`, `arp.bones_tag_manager`.
   - Probe settings: `Scene.arp_bone_tag_show='cc'`, `Scene.arp_custom_bones_list`, `Scene.arp_custom_bones_idx`, `Scene.arp_const_bones_list`.
   - The parameters of `set_bone_tag` were not recorded (UNVERIFIED). Read them on the PC with `[p.identifier for p in bpy.ops.arp.set_bone_tag.get_rna_type().properties]`, and use `arp.check_rig_export` (no params; "Check the rig to find possible export related errors") as a validation step.
   - The `cc_` name prefix is the legacy convention. Per the search excerpt of the ARP docs it still works ("To include custom bones in the Fbx export, make sure their names start with 'cc_'"). Use both the prefix and the tag.
6. **The ARP add-limb operator exists. CORRECTED (was UNVERIFIED).**
   - The probe shows `arp.add_limb`, `arp.dupli_limb`, `arp.dupli_limb_mirror`, `arp.disable_limb`, `arp.show_limb_params`, `arp.save_limb`, `arp.align_wings`, `arp.add_corrective_bone`.
   - Its parameters (limb-type enum values such as tail, ears or spline_ik) were not captured (UNVERIFIED). Probe with `get_rna_type()` before use.
   - Facial and tongue settings exist: `Scene.arp_full_facial` (False), `Scene.arp_smart_tongue` (True), `Scene.arp_tongue_name`, `Scene.arp_retro_jaw_rot`, `arp.guess_facial`, preset `misc_presets\facial_setup.blend`.
7. **ARP deform bone names are known from the user's trial. CORRECTED.**
   - The deform set includes `root.x`, `spine_01.x`, `spine_02.x`, `neck.x`, `head.x`, `hand.l/.r`, `c_index1_base.l`, `index1.l`, `c_index2.l`, `c_index3.l` (likewise for middle, ring and pinky), `foot.l`, `toes_01.l`.
   - `c_root_bend.x` is **not** deform. Parent tail bones to `root.x` (or to `c_root_bend.x` only if they are controllers). Parent ears and horns to `head.x`, and claws to `c_<finger>3.<side>`.
8. **The repo's export path is different from what the report said. CORRECTED.**
   - The repo calls `bpy.ops.arp.arp_export_fbx_panel(filepath=...)` (finalize.py `_export_arp`). Before that it sets `sc.arp_engine_type` ('UNREAL'/'UNITY'), `sc.arp_export_rig_type='HUMANOID'`, `arp_mannequin_axes`, `arp_rename_for_ue`, `arp_ue4` and `arp_ge_sel_only`.
   - `arp_export_rig_type` items are `['HUMANOID','UNIVERSAL']` and `arp_engine_type` items are `['UNITY','UNREAL','GODOT','OTHERS']` (addon_trial2.json).
   - The plain Blender path uses `bpy.ops.export_scene.fbx` with per-engine dicts (`FBX_ENGINE` in finalize.py): Unreal `apply_scale_options="FBX_SCALE_NONE"`, Unity `"FBX_SCALE_ALL"`, both `primary_bone_axis="Y"`, `secondary_bone_axis="X"`.
   - Whether HUMANOID mode exports tagged `cc` tail or ear bones is **UNVERIFIED**. A changelog excerpt (3.52) says custom bones in Humanoid export parent to `root.x`. Test it by extending `addon_trial.py` with one tagged tail bone, exporting both HUMANOID and UNIVERSAL, and listing the bones in the FBX.

---

### 0. Gap analysis (repo): CONFIRMED with small fixes
- `appendages.from_object(obj, J, segments=5)` returns dicts with `kind`, `chain` (a list of points from root to tip, `segments+1` long), `verts` (a **count**), `vert_idx` (a numpy array), `length`, `centre` and `name`. There are no separate root and tip keys; use `chain[0]` and `chain[-1]`. **CORRECTED**
- It is used only in `steps.py:ensure_detail_maps()` (line 147). **CONFIRMED**
- `arp_rig.finish()` (line 255) runs `arp.match_to_rig` and `arp.bind_to_rig`, and welds props through `ARP_SOCKET_BONES = {"hand_r":"hand.r","hand_l":"hand.l","head":"head.x","spine":"spine_02.x","pelvis":"root.x"}`. No appendage bones are added. **CONFIRMED**
- There is no `weapon_r` mapping in the repo, so the report's "`weapon_r` in ARP" is **UNVERIFIED** and should be removed.
- The signature is `skin._cleanup_weights(obj, max_influences, min_weight, deform_bones:set)`, with 4 arguments. The report omitted `deform_bones`. **CORRECTED**

### 1. Export rules
- `bpy.ops.nla.bake` parameters, all **CONFIRMED (main)** (scripts/startup/bl_operators/anim.py `NLA_OT_bake`):
  - `frame_start=1`, `frame_end=250`, `step=1`
  - `only_selected=True` (the default is **True**, so the report's `False` differs; True needs the bones selected)
  - `visual_keying=False`, `clear_constraints=False`, `clear_parents=False`, `use_current_action=False`
  - `clean_curves=False` (the default is False; the report wrote True as if it were the default)
  - `bake_types` is ENUM_FLAG {'POSE','OBJECT'}
  - `channel_types` is ENUM_FLAG {'LOCATION','ROTATION','SCALE','BBONE','PROPS'} (now **CONFIRMED**). `PROPS` bakes *pose-bone* custom properties.
- How the bake creates its action (**CONFIRMED**, anim_utils.py lines 456–499):
  - With `use_current_action=False`, it evaluates every frame first, then creates `bpy.data.actions.new("Action")`, assigns it and creates and assigns a slot itself (`action.slots.new(obj.id_type, name)`, then `atd.action_slot = slot`). You do not need to pre-create the action.
  - For scripting without an operator context, call `bpy_extras.anim_utils.bake_action_objects([(obj, None)], frames=range(a, b+1), bake_options=anim_utils.BakeOptions(only_selected=False, do_pose=True, do_object=False, do_visual_keying=True, do_constraint_clear=False, do_parents_clear=False, do_clean=False, do_location=True, do_rotation=True, do_scale=True, do_bbone=False, do_custom_props=False))`.
- Selection in 5.x (**CONFIRMED (main)**):
  - `PoseBone.select` exists ("Bone is selected in Pose Mode").
  - `Bone` (data) no longer defines `select`; only `EditBone.select`, `select_head` and `select_tail` exist.
  - Use `pb.select = True` for `only_selected` bakes.
- Slotted actions (all **CONFIRMED (main)**, rna_action.cc):
  - `Action` has `slots`, `layers`, `is_action_legacy`, `is_action_layered` and **no `fcurves`**. The legacy shim is gone, so don't rely on `action.fcurves`.
  - Use `action.layers[0].strips[0].channelbag(slot, ensure=True).fcurves`, or the helpers `anim_utils.action_ensure_channelbag_for_slot(action, slot)` and `anim_utils.animdata_get_channelbag_for_assigned_slot(adt)`.
  - `AnimData.action_slot`, `action_slot_handle`, `action_suitable_slots` and `last_slot_identifier` exist.
  - `action.slots.new(id_type, name)` takes `id_type` as a required parameter.
  - The FBX exporter's all-actions loop sets `ob.animation_data.action_slot` for each action (export_fbx_bin.py lines 2522–2614).
- FBX parameters (**CONFIRMED (main)**, io_scene_fbx `__init__.py`):

  | Parameter | Default | Note |
  |---|---|---|
  | `add_leaf_bones` | | exists |
  | `primary_bone_axis` / `secondary_bone_axis` | | exist |
  | `armature_nodetype` | `'NULL'` | other options `'ROOT'`, `'LIMBNODE'` |
  | `bake_anim` | True | |
  | `bake_anim_use_all_bones` | True | |
  | `bake_anim_use_nla_strips` | True | |
  | `bake_anim_use_all_actions` | True | |
  | `bake_anim_force_startend_keying` | True | |
  | `bake_anim_step` | 1.0 | |
  | `bake_anim_simplify_factor` | **1.0** | set it to 0.0 explicitly for mechanical clips |
  | `use_armature_deform_only` | False | **must be True** to drop the non-deform helper and target bones; the report assumed they are dropped automatically |
  | `use_custom_props` | False | |
  | `apply_scale_options` | | `'FBX_SCALE_NONE'`, `'FBX_SCALE_UNITS'`, … |
  | `use_mesh_modifiers` | | exists |

  - `use_armature_deform_only` still keeps a non-deform bone that has deform children.
- Mesh attributes: FBX writes only UV, Color, Normal, Tangent, Binormal, Smoothing, EdgeCrease and Material layers (**CONFIRMED**). A generic float attribute such as `root_u` (section 5) **will not export**. Pack it into a UV map (e.g. `UVMap_hair.x`) or a color-attribute channel. **CORRECTED**

### 2. Recipes (API names checked against rna_constraint.cc and rna_fcurve.cc)
- **2.1 Hinge**
  - **CONFIRMED (main)**: `LIMIT_ROTATION` with `use_limit_x/y/z`, `min_x..max_z` (angles), `use_transform_limit`, `euler_order` and `owner_space`.
  - Add: a new property, `use_legacy_behavior`, exists (default off, which gives the newer clamping that handles wrap-around). Leave it off.
  - Default `PoseBone.rotation_mode` is `'QUATERNION'`, so setting `'XYZ'` before `driver_add("rotation_euler", 0)` is required.
  - Expose the slider range with `arm.id_properties_ui("open").update(min=0.0, max=1.0)`. UNVERIFIED on 5.3 but long-standing API.
  - Keep expressions "simple" (e.g. `o*1.92`) so Blender's simple-expression evaluator runs them without Python and without needing "Auto Run Python Scripts". That evaluator is long-standing behaviour; not re-fetched.
  - "Drivers run before constraints": **CONFIRMED** behaviour. See correction 2 for the bake interaction.
- **2.2 Slider**: `LIMIT_LOCATION` with `use_min_y`, `use_max_y`, `min_y`, `max_y`, `use_transform_limit`. **CONFIRMED (main)**
- **2.3 Piston**: `DAMPED_TRACK` `track_axis` values include `'TRACK_Y'` and `'TRACK_NEGATIVE_Y'`. **CONFIRMED (main)**
- **2.4 Gears**
  - **CONFIRMED (main)**: driver variable type `'TRANSFORMS'`; target fields `bone_target`, `transform_type` (`'ROT_Y'`), `rotation_mode` (`'SWING_TWIST_Y'`, plus `'AUTO'`, `'QUATERNION'`, …), `transform_space` (`'LOCAL_SPACE'`).
  - The ±180° claim is CORRECTED (see correction 4).
  - The wheel formula `angle = distance/radius` is correct.
- **2.5 Spline IK**
  - **CONFIRMED (main)** properties: `chain_count`, `use_even_divisions`, `use_curve_radius`, `y_scale_mode` ∈ {`NONE`, `FIT_CURVE` (default), `BONE_ORIGINAL`}, `xz_scale_mode` ∈ {`NONE`, `BONE_ORIGINAL`, `INVERSE_PRESERVE`, `VOLUME_PRESERVE`}, `use_original_scale`, and `use_bulge_min/max`.
  - Hook modifier: **CONFIRMED** fields `object`, `subtarget`, `center`, `matrix_inverse`, `strength`, `falloff_type`, `vertex_group`, and function `vertex_indices_set([...])`.
  - For a Bezier curve each control point is 3 hook vertices (left handle, point, right handle), so point *i* uses indices `[3i, 3i+1, 3i+2]`. UNVERIFIED index order; test it.
  - Set `matrix_inverse = (arm.matrix_world @ pb.matrix).inverted()` at bind time, or the curve jumps. UNVERIFIED exact form; standard practice.
  - Staggered translation instead of scale: sound advice. The bone-scale-breaks-physics part is UNVERIFIED.
- **2.6 Retractable parts**: the design is sound and unchanged.
  - Add: put the "hide" scale key on the claw bone only. With an ARP Humanoid export, check that `cc` bones keep scale keys. UNVERIFIED.
  - UE needs **Import Morph Targets** on and Unity needs **Import BlendShapes** on for the `sheath_closed` shape key. UNVERIFIED (not re-fetched).
  - In the repo, `export_engine` applies a DECIMATE modifier to the Unity copy. That `modifier_apply` **fails on meshes with shape keys**, so add a shape-key-safe path (apply per shape key, or skip decimation for meshes with keys). Code fact, CONFIRMED by reading steps.py lines 615–626.
- **2.7 Weapons**: the approach stands. Remove `weapon_r`; the repo's socket for hand props is `hand.r`.
- **2.8 Jaw, teeth, tongue**
  - ARP facial exists (`Scene.arp_full_facial`, `arp.guess_facial`, `facial_setup.blend`; probe CONFIRMED).
  - The exact ARP facial bone names (e.g. `jawbone.x`, `c_tong_*`, `c_teeth_*`) are UNVERIFIED. After enabling facial, read them from `rig.data.bones` at runtime.
  - Teeth-to-bone mapping and a 4–6 bone tongue are reasonable choices, not checked against a source.

### 3. Extra body parts on ARP
- The robust path stands with corrections:
  - Parent tails to `root.x` (deform), ears and horns to `head.x`, side attachments to `spine_01.x`/`spine_02.x`.
  - Name the bones `cc_tail_01` and so on, and tag them with `arp.set_bone_tag` (parameters UNVERIFIED).
  - Validate with `arp.check_rig_export`.
- `arp.add_limb` exists; its parameters are UNVERIFIED.
- Budget table: the budgets are rules of thumb, UNVERIFIED.
- 3.2 Unity Humanoid needs an Avatar Mask for keys on extra bones, otherwise use Generic: UNVERIFIED (not re-fetched), consistent with known Unity behaviour.

### 4. Engine side
- **Sidecar and `dyn_` naming**: a Forge-owned convention, fine.
  - Name clash: ARP renames or prefixes custom bones, so decide whether the `dyn_` name is applied *after* the `cc_` prefix is stripped. ARP strips `cc_` on export? UNVERIFIED; test it.
- **UE AnimDynamics, RigidBody (`LOD Threshold`), Physics Asset Min Bone Size / Min Weld Size, Control Rig `SpringInterpV2`**: all UNVERIFIED (not re-fetched; dev.epicgames.com blocked). The descriptions match prior knowledge.
- **KawaiiPhysics**: CONFIRMED from the repo clone.
  - MIT licence (© 2019–2026). README badge "Unreal Engine 5.3–5.8". Plugin VersionName 1.21.0. Also sold on FAB.
  - Node fields (`AnimNode_KawaiiPhysics.h`): `RootBone`, `ExcludeBones`, `AdditionalRootBones`, `DummyBoneLength`, `BoneForwardAxis`, `PhysicsSettings` (Damping, Stiffness, WorldDampingLocation, WorldDampingRotation, Radius, LimitAngle), `SphericalLimits`, `CapsuleLimits`, `TaperedCapsuleLimits`, `BoxLimits`, `PlanarLimits`, `LimitsDataAsset`, `PhysicsAssetForLimits`, `BoneConstraints`, `bEnableWind`, `bAllowWorldCollision`, `IgnoreBoneNamePrefix`, `TargetFramerate`, `SimulationSpace`.
  - Sidecar `stiffness` and `damping` map directly to `PhysicsSettings.Stiffness` and `.Damping`.
  - Correction: colliders are sphere, capsule, tapered capsule, box and plane, not just sphere, capsule and plane.
  - New: the sample project bundles a `KawaiiPhysicsToolset` for UE 5.8's experimental Unreal MCP (node authoring and audits). That is a possible automation route; untested.
- **Template AnimBP approach** (pre-placed node, script sets RootBone): reasonable. UE Python AnimGraph node creation remains UNVERIFIED.
- **Unity Animation Rigging DampedTransform**: CONFIRMED (package 1.4.1 mirror).
  - API names: `DampedTransformData.constrainedObject`, `sourceObject`, `dampPosition`, `dampRotation` (clamped 0..1), `maintainAim`.
  - Semantics: 0 means follow with no damping, 1 means fully damped.
  - Needs `RigBuilder` on the Animator object plus a `Rig` child (standard package setup).
  - Update the doc URL to `com.unity.animation.rigging@1.4`.
  - Chaining one constraint per bone is UNVERIFIED as official guidance.
- **Magica Cloth 2**: UNVERIFIED (not re-fetched).
- **UniVRM**: MIT CONFIRMED. The latest version supports Unity 2022.3 LTS+ (from v0.128.0). Its SpringBone is transform-based, so it is independent of the render pipeline. The URP claim is moot.
- **Mobile budgets**: UNVERIFIED.

### 5. Hair cards
- Skinning cards to `dyn_hair_*` chains, or rigid to the head with shader wind: fine.
- CORRECTED: `root_u` must be stored in a UV map or color attribute to survive FBX (see section 1).

### 6. Scripted flow: amended steps
- Step 3: after adding bones, run `_cleanup_weights(o, max_inf, min_w, deform_set)` with all 4 arguments.
- Step 5 (bake), simplified:
  - Preferred: don't bake. Key `arm["open"]` / `arm["claws_out"]` in one action per clip. The FBX exporter (`bake_anim_use_all_actions=True`, `bake_anim_simplify_factor=0.0`) or ARP's exporter samples the evaluated pose.
  - If baking for cleanup: call `anim_utils.bake_action_objects` with `do_visual_keying=True`, then **mute drivers and constraints on the baked bones** before export, then unmute.
  - Optionally push clips to NLA. The FBX exporter's `bake_anim_use_nla_strips=True` exports non-muted strips as separate stacks; avoid getting duplicate stacks from strips and all-actions.
- Step 7 validation, added checks:
  - `arp.check_rig_export` passes
  - every tagged `cc_` bone is present in the exported FBX (re-import and list the bones)
  - `use_armature_deform_only=True` on the Blender path
  - no driver or constraint still active on bones that have baked keys
  - shape-key meshes are not decimated by `modifier_apply`

### 7. Pitfalls: corrected list
- Constraints and drivers do not travel as data, but both exporters bake their *result*. After a manual bake, mute them or they double-apply or override the keys.
- `FIT_CURVE` (the Spline IK default) and Stretch To produce scale. Use staggered translation.
- Gear flip at ±180° is not an issue in Blender FBX output (Euler-compat). Watch for spins of more than 180° per frame.
- Only `Bone`-level custom properties reach the FBX, and only static ones with `use_custom_props=True`.
- `Bone.select` is gone in 5.x main; use `PoseBone.select`.
- The `nla.bake` `only_selected` default is True.
- `bake_anim_simplify_factor` defaults to 1.0; set 0.0.
- Shape keys block `modifier_apply`, and the repo's Unity decimation path does exactly that.
- UE Physics Asset small-bone skipping, the AnimDynamics/RBAN scaling reports and Unity Humanoid masks: UNVERIFIED (not re-fetched).

### Still UNVERIFIED
- Parameters of `arp.add_limb` and `arp.set_bone_tag`.
- Whether ARP HUMANOID export keeps tagged tail and ear bones, and whether it strips `cc_`.
- ARP facial bone names.
- Everything UE-documented (AnimDynamics, RBAN, Physics Asset defaults, Control Rig units, Python AnimGraph).
- Unity Humanoid mask behaviour; Magica Cloth details.
- Hook vertex-index order for Bezier points.
- Budgets.
- Whether all "CONFIRMED (main)" items hold identically on 5.3. They were checked on main (5.4 alpha); verify on 5.3 with `addon_probe`.

### Sources
- Blender `nla.bake`: https://github.com/blender/blender/blob/main/scripts/startup/bl_operators/anim.py
- Bake internals and channelbag helpers: https://github.com/blender/blender/blob/main/scripts/modules/bpy_extras/anim_utils.py
- Action, slot and channelbag RNA: https://github.com/blender/blender/blob/main/source/blender/makesrna/intern/rna_action.cc
- AnimData `action_slot`: https://github.com/blender/blender/blob/main/source/blender/makesrna/intern/rna_animation.cc
- Constraints (Limit*, Damped Track, Spline IK): https://github.com/blender/blender/blob/main/source/blender/makesrna/intern/rna_constraint.cc
- Driver targets: https://github.com/blender/blender/blob/main/source/blender/makesrna/intern/rna_fcurve.cc
- `PoseBone.select`: https://github.com/blender/blender/blob/main/source/blender/makesrna/intern/rna_pose.cc
- `Bone` / `EditBone`: https://github.com/blender/blender/blob/main/source/blender/makesrna/intern/rna_armature.cc
- Hook modifier: https://github.com/blender/blender/blob/main/source/blender/makesrna/intern/rna_modifier.cc
- FBX exporter options: https://github.com/blender/blender/blob/main/scripts/addons_core/io_scene_fbx/__init__.py
- FBX exporter internals: https://github.com/blender/blender/blob/main/scripts/addons_core/io_scene_fbx/export_fbx_bin.py and https://github.com/blender/blender/blob/main/scripts/addons_core/io_scene_fbx/fbx_utils.py
- KawaiiPhysics: https://github.com/pafuhana1213/KawaiiPhysics (README.md, LICENSE, `Plugins/KawaiiPhysics/Source/KawaiiPhysics/Public/AnimNode_KawaiiPhysics.h`, `KawaiiPhysicsTypes.h`)
- Unity Animation Rigging 1.4.1 mirror: https://github.com/needle-mirror/com.unity.animation.rigging (`Runtime/.../DampedTransform.cs`, `Documentation~/constraints/DampedTransform.md`)
- UniVRM: https://github.com/vrm-c/UniVRM (LICENSE.txt, README.md)
- ARP changelog via search excerpts (pages not fetchable): https://superhivemarket.com/products/auto-rig-pro/versions and https://blenderartists.org/t/auto-rig-pro-3-59/672834?page=43
- ARP probe on the user's PC: `/home/user/Image-to-Game-asset/jobs/_setup/addon_probe.json`, `/home/user/Image-to-Game-asset/jobs/_setup/addon_trial.json`, `/home/user/Image-to-Game-asset/jobs/_setup/addon_trial2.json`

### Files
- `/home/user/Image-to-Game-asset/blender_scripts/forge_bpy/appendages.py`: `from_object` at line 206; output keys `kind`, `chain`, `verts`, `vert_idx`, `length`, `centre`, `name`.
- `/home/user/Image-to-Game-asset/blender_scripts/forge_bpy/arp_rig.py`: `ARP_SOCKET_BONES` at line 47, `nearest_bone` at line 238, `finish` at line 255, `build` at line 320.
- `/home/user/Image-to-Game-asset/blender_scripts/forge_bpy/finalize.py`: `_export_fbx` at line 247, `ARP_ENGINE` and `_export_arp` (via `arp.arp_export_fbx_panel`) at lines 252–276.
- `/home/user/Image-to-Game-asset/blender_scripts/forge_bpy/skin.py`: `_cleanup_weights(low, max_influences, min_weight, deform_bones)` at line 51.
- `/home/user/Image-to-Game-asset/blender_addon/forge_send/steps.py`: `has_addon_op` at line 45, `ensure_detail_maps` at line 133, `build_rig` at line 464, `pose_test` at line 501, `export_engine` at line 596 (the Unity DECIMATE apply is at lines 615–626).
