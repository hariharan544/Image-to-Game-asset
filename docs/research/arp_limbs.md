# Research: arp_limbs (fact-checked)

## Auto-Rig Pro: scripting extra limbs and facial parts, and how they export (fact-checked)

**How this was checked.** I re-read the ARP 3.77.33 source mirror (https://github.com/jasongzy/auto_rig_pro; local clone at `/tmp/claude-0/-home-user-Image-to-Game-asset/f1ff8269-309f-546b-b536-494e8126b836/scratchpad/arp_src`). I also scanned bone names in `armature_presets/dog.blend` and `horse.blend`, fetched the third-party scripts (all 3 URLs returned HTTP 200), and read the repo's `blender_scripts/forge_bpy/arp_rig.py`.

**What I could not reach:**
- lucky3d.fr docs, the Superhive changelog and docs.unity3d.com are blocked by this session's network settings (403).
- The user runs 3.79.17, so anything that changed between 3.77.33 and 3.79.17 is UNVERIFIED.
- Before passing keywords, check them at runtime with `bpy.ops.arp.show_limb_params.get_rna_type().properties.keys()`.

Line references below are `src/auto_rig.py` (AR) or `src/auto_rig_ge.py` (GE) in 3.77.33.

### 1. Adding limbs with `bpy.ops.arp.add_limb(limbs_presets=...)`

**Enum values** — CONFIRMED (AR:6091):
- `'arm.l'`, `'arm.r'`, `'breast'`, `'ears'`, `'head'`, `'leg.l'`, `'leg.r'`, `'spine'`, `'tail'`, `'spline_ik'`, `'bbones'`, `'kilt'`.
- Plus `'<file>_customlimb'` for each `.py` file in `prefs.custom_limb_path`, which `update_limbs_presets` appends to the list.
- The `'____'` separator is a no-op.

**Wings and custom bones are not limbs** — CONFIRMED. Wings are an arm option; custom bones are covered in section 4.

**Code paths** — CONFIRMED (AR:9855–9905):
- Generated in code: `ears` → `set_ears(2, side_arg='.l')`, `tail` → `set_tail(4, side_arg='.x')`, `breast` → `set_breast(True)`, `spline_ik` → `set_spline_ik(4, side_arg='.x')`, `bbones` → `set_bendy_bones(4, side_arg='.x')`, `kilt` → `set_kilt('.x')`.
- Duplicates use `side_arg='_dupli_NNN.x'`.
- `arm`, `leg`, `head` and `spine` are appended from `limb_presets/modules.blend` and joined into the rig.

**Headless crash** — CORRECTED (it is broader than stated). `bpy.context.space_data.overlay.show_relationship_lines = False` appears in two places:
- `_add_limb` (AR:10015)
- `_append_arp` (AR:12322)

So `arp.append_arp` crashes in `--background` too, not only appended limbs. The thruthesky script patches out both lines (its comments cite them). Run both inside `bpy.context.temp_override(**view3d_override())`; the repo's `arp_rig._ov()` → `addon_trial.view3d_override()` already exists.

**`breast` can only be added once** — CONFIRMED.

**Duplicate naming and offset** — CONFIRMED:
- Names follow `_dupli_NNN` + side, e.g. `tail_00_ref_dupli_001.x`.
- Appended duplicates are offset by `rig_module.matrix_world @ Vector((dupli_id*0.5, 0, 0))`. That is X in the module's local space, not strictly world X.

**`arp.dupli_limb` and `arp.dupli_limb_mirror`** — CONFIRMED. Poll requires `EDIT_ARMATURE` and `selected_editable_bones[0]` carrying the key `arp_duplicate`.

**`arp.disable_limb`** — not re-checked; UNVERIFIED.

**Template for a creature with no preset** — CONFIRMED in thruthesky's script: `append_arp(rig_preset='free')` → `add_limb('spine')` → N × `leg.l` / `leg.r` → `match_to_rig` → `bind_to_rig`.

**Preset files** — CONFIRMED: `bird`, `bird_44`, `dog`, `free`, `horse`, `horse_ik_spine`, `human`, `master` (plus `cs.blend`, which holds custom shapes, not a preset).

**Dog and horse preset contents** — CONFIRMED by scanning the .blend files:
- `tail_00..03_ref.x`
- `ear_01/02_ref.l` and `.r`
- `jaw_ref.x`, `tong_01..03_ref.x`, `c_muzzle.x`
- `thigh_ref.l/.r` and `thigh_b_ref.l/.r`
- Front legs are leg limbs, not arms: `thigh_ref_dupli_001.l/.r` and `thigh_b_ref_dupli_001.l/.r`. All four legs are 3-bone legs.
- Added from the 3.77.33 changelog: dog and horse presets have the muzzle controller on by default and a lower jaw rotation speed.

### Reference and controller bone names

| Limb | Ref bones | Bones after Match to Rig | Status |
|---|---|---|---|
| Tail | `tail_00_ref.x`… (0-based); with `tail_name` → `<name>_00_ref.x` | `c_<name>_NN.x` (deform) | CONFIRMED (the export builds `'c_'+tail_name+'_'+idx+side`, GE:8148) |
| Ears | `ear_01_ref.l`… (1-based, up to 16) | `c_ear_NN.l/.r` | CONFIRMED |
| Spline IK | `<name>_01_ref.x`… | `<name>_NN.x` and `c_<name>_*` controls; bones carry key `arp_spline` | ref names CONFIRMED (AR set_spline_ik); controller names UNVERIFIED |
| Bendy bones | `<bbones_name>_01_ref.x`… | not exportable | CONFIRMED (3.77.33 changelog warning) |
| Kilt | key `arp_kilt` | — | CONFIRMED |
| Jaw | `jaw_ref.x` | `c_jawbone.x` (control), `jawbone.x` (deform), `jawbone_track.x` | CONFIRMED (auto_rig_datas.py:346–352) |
| Tongue | `tong_01..03_ref.x` | `c_tong_0N.x` (control, non-deform), `tong_0N.x` (deform) | CONFIRMED (datas:563–573) |
| Teeth | `teeth_top_ref.x`, `teeth_bot_ref.x`, `teeth_top_ref.l/.r`, `teeth_bot_ref.l/.r` | `c_teeth_top.x` / `c_teeth_bot.x` (deform), `.l/.r` variants (deform), `c_teeth_top_master.x` / `c_teeth_bot_master.x` (control) | CONFIRMED (datas:519–531) |
| Eyes | `eye_offset_ref`, `eyelid_top_ref`, `eyelid_twk_top_ref`, `eyelid_corner_01_ref`… | `c_eye`, `c_eye_offset`, `eyelid_top/bot`, `c_eye_target.x` | CONFIRMED |
| Lips, muzzle | `lips_roll_top_ref.x`, `muzzle_ref.x` | `c_lips_*`, `c_nose_0N.x`, `c_chin_0N.x`, `c_cheek_*` | CONFIRMED |

### 2. `bpy.ops.arp.show_limb_params` (Limb Options)

**Poll** — CONFIRMED (AR:1421): `is_object_arp(active)`, mode `EDIT_ARMATURE`, and `'_ref'` in `selected_editable_bones[0].name`.

**`load_settings_when_exec`** — CONFIRMED:
- Default False.
- If True, `execute` calls `load_limb_settings(self)`, which overwrites the keywords you passed with the values saved on the ref bones.

**`invoke` is skipped with `'EXEC_DEFAULT'`** — CONFIRMED:
- The reset-to-defaults block lives in `invoke` behind `reset_to_default_settings` (BoolProperty, default True). That property also exists.
- `execute` sets `reset_to_default_settings = True` at its end.
- Blender reusing last-used values of non-SKIP_SAVE operator properties is UNVERIFIED. Pass every option explicitly.

**`side`** — CONFIRMED. It is a `StringProperty(default="")`, filled only by `load_limb_settings` (from `get_bone_side`). `execute` passes `self.side` as `side_arg` or `side` to: `set_arm_twist`, `set_arm_feathers`, `set_arm_half_bones`, `set_leg_twist`, `set_leg_half_bones`, `set_leg_auto_ik_roll`, `set_spline_ik(side_arg=...)`, `set_bendy_bones(side_arg=...)` and `set_kilt(self.side, ...)`. Always pass `side=`.

**Tail call** — CORRECTED and important:
- `execute` calls `set_tail(count, master_at_root, new_side=self.tail_side, ...)` without `side_arg`. The side is read from the selected bone.
- `tail_side` is an enum whose first item is `'.x'`, so it defaults to `'.x'`. A `.l` or `.r` tail (or tentacle) is moved to `.x` unless you pass `tail_side` explicitly.
- Always pass `tail_side` equal to the current side.

**Ears call** — CORRECTED:
- `execute` calls `set_ears(ear_count, preserve_shape=...)` with no side, so only the selected ear ref's side is rebuilt (`sides=[b_name[-2:]]`).
- With nothing selected, both `.l` and `.r` are rebuilt.
- Simplest: `set_ears(n, side_arg='.l')`. Despite the name, this rebuilds both `.l` and `.r` (it does `side_arg[:-2]+'.l'/'.r'`). Smart itself uses this call (auto_rig_smart.py:4298).

**Keyword defaults and ranges** — CONFIRMED, with these corrections:

| Keyword | Value in 3.77.33 | Status |
|---|---|---|
| `tail_count` | 4, range 1–32 | CONFIRMED |
| `tail_bendy_count` | 1 (tooltip: keep 1 for game engines) | CONFIRMED |
| `tail_parent_fallback` | `'c_traj'` | CONFIRMED |
| `tail_name` | `'tail'` | CONFIRMED |
| `ear_count` | 2, range 1–16 | CONFIRMED |
| `neck_count` | 1, range 1–16 | CONFIRMED |
| `neck_bendy` | IntProperty 1–256, default 1 | CORRECTED (not a bool) |
| `neck_parent_fallback` | exists | added |
| `spine_count` | 3, range 1–64 | CONFIRMED |
| `spline_count` | 4, range 2–1024 | CONFIRMED |
| `spline_bendy` | 0 (tooltip: keep 0 for export) | CONFIRMED |
| `spline_smoothness` | operator default 4, range 2–6; `set_spline_ik` function default is 3 | CORRECTED |
| `spline_side` | enum | CONFIRMED |
| `spline_name` | `'spline'`, with `update_limb_name` | CONFIRMED |
| `bbones_count` | 4 | CONFIRMED |
| `bbones_segments` | 5 | CONFIRMED |
| `kilt_amount` | 6, range 3–128 | CONFIRMED |
| `kilt_type_side` | exists | CONFIRMED |
| `arm_twist_bones` | 1–32 | CONFIRMED |
| `arm_wings`, `arm_feathers`, `forearm_feathers`, `hand_feathers`, `feathers_layers`, `feathers_subdiv`, `feathers_fold_controller` | exist | CONFIRMED |
| `feathers_fold_controller` | needs an action named `*rig_wings_fold*` (rest pose at frame 0, folded at frame 10) | added |
| `three_bones_leg`, `three_bones_leg_ctrl`, `leg_ikpole_smart`, `foot_roll_break`, `leg_half_bones`, `leg_twist_bones` | exist | CONFIRMED |
| `tongue_amount` | 3, range 1–32 | CONFIRMED |
| `eyelids_amount` | 3, range 1–32 | CONFIRMED |
| `lips_amount` | 2, range 0–32 | CONFIRMED |
| `eyeb_amount` | 4 | CONFIRMED |

**Module function signatures** — CORRECTED (`side_arg` defaults to None, not `'.x'` / `'.l'`):

```python
set_tail(tail_count, master_at_root=True, side_arg=None, new_side=None, preserve_shape=True, bb_count=1, parent_fallback='c_traj', new_name='tail')
set_ears(ears_amount, side_arg=None, offset_arg=None, preserve_shape=True)
set_spline_ik(amount, type='1', cont_freq=2, interpolation='SMOOTH', bbones_count=0, side_arg=None, ..., new_name='spline', new_side=None, smoothness=3, deform=True, preserve_shape=True, fk=False, fk_masters_freq=2, ..., spline_add_tail=False)
set_bendy_bones(amount, bbones_segment_args=5, scale=1.0, side_arg=None, new_side=None, new_name='bbones', parent_fallback='c_traj', preserve_shape=True)
set_neck(neck_count, twist=False, bendy_segments=1, parent_fallback='c_traj')
set_spine(count=3, bottom=False, ..., spine_master_enabled=False, spine_reverse=False, parent_fallback='c_traj')
```

- With `side_arg=None`, `set_tail` falls back to the selected bone's side, then to `'.x'`.
- Smart calls these functions as `auto_rig.set_ears` / `auto_rig.set_facial`, which confirms they can be called from other modules.
- Module path: find it by matching the suffix `auto_rig_pro.src.auto_rig` in `sys.modules`. The exact `bl_ext.*` prefix for 3.79.17 is UNVERIFIED.

**Kilt Pose-mode workaround** — CONFIRMED. It is gated on `(4,4,0) <= bpy.app.version < (4,4,1)`, so it never runs on 5.x.

**X-Mirror** — CONFIRMED. `execute` turns `use_mirror_x` off and restores it.

### 3. Facial parts on the head

**Operator path** — CONFIRMED:
- Select `head_ref.x` and call `show_limb_params(limb_type='head', ...)` with the keywords as written in the original report. All of them exist: `facial`, `facial_mouth`, `facial_teeth`, `facial_tongue`, `tongue_amount`, `facial_eye_l/_r`, `eyelids_amount`, `facial_eyebrow_l/_r`, `facial_chins`, `facial_noses`, `facial_cheeks`, `skull_bones`, `jaw_trans_to_rot`, `jaw_speed`, `unlock_jaw_y`, `lips_amount`, `auto_lips`, `muzzle`, `muzzle_nose` (default True).
- After `set_facial`, if `facial` is on: `set_jaw_rotation_location(jaw_trans_to_rot, auto_lips_visual)` runs only when `facial_mouth` is also on, and `set_eyetargets_distance(eye_target_dist)` runs whenever `facial` is on.

**Mouth options worth adding to the report:**
- `lips_floor` / `lips_floor_offset`: upper lips collide with lower lips.
- `lips_roll` (default True) and `lips_roll_cns`.
- `lips_offset`.
- `enable_eyelids_tweak`.
- `eye_target_dist`.

**`set_facial` keyword names** — CONFIRMED (AR:44738): `enable`, `mouth_enabled`, `teeth_enabled`, `tongue_enabled`, `tongue_amount`, `eye_l_enabled`, `eye_r_enabled`, `eyelids_amount`, `skull_bones`, `chins_enabled`, `noses_enabled`, `cheeks_enabled`, `eyebrow_l_enabled`, `eyebrow_r_enabled`, `lips_amount`, `auto_lips`, `muzzle`, `muzzle_nose`, `jaw_speed`, `unlock_jaw_y`. Smart uses `set_facial(enable=False)` to switch the face off (smart:4647).

**Smart** — CONFIRMED:
- Operators: `id.go_detect`, `arp.guess_markers`, `arp.guess_facial`, plus `id.facial_setup` and `id.validate_facial_setup`.
- Scene props: `arp_smart_ears`, `_eyes`, `_mouth`, `_teeth`, `_tongue`, `_nose`, `_chin`, `_cheeks`, `_eyebrows`. Spine, neck and twist counts are `arp_smart_spine_count`, `arp_smart_neck_count`, `arp_smart_twist_count`.
- No scene props for tail, spline or wing detection exist — CONFIRMED.
- Headless safety: UNVERIFIED (third-party claim only).

**Mouth placement guidance** — UNVERIFIED as ARP documentation, but sound practice. Key point: the jaw only opens cleanly if the mesh has a cut mouth and separate teeth and tongue.

### 4. Hidden or retractable parts: custom bones

**Tagging rule** — CONFIRMED (lib/bone_data.py): name starts with `cc_`, or the bone has key `cc` or `custom_bone`. The list is collected from `arm.data.bones`.

**Tag operators** — CORRECTED and expanded:
- `bpy.ops.arp.set_bone_tag(tag='cc')` and `arp.unset_bone_tag(tag=...)`. `tag` is a StringProperty (`'cc'`, `'softlink'`, `'const_interp'`, `'exclude'`), not an enum.
- Poll: `POSE` or `EDIT_ARMATURE`. They act on selected bones.
- For headless use, prefer `bpy.ops.arp.bone_tag_add(name='cc_claw.l', tag='cc')` or `list="['a','b']"`. These tag by name with no selection needed (GE:497–547).
- Scene lists `arp_custom_bones_list` and `arp_softlink_bones_list` exist — CONFIRMED.

**Export of custom bones** — CONFIRMED with detail:
- Humanoid forces `'deform': True` on custom bones and carries their exportable custom properties (GE:6580).
- If a custom bone duplicates a base-rig bone, it is skipped.
- Custom bones are excluded from both `rename_for_ue` and `rename_for_godot` — CONFIRMED.
- Parent resolution uses substrings of the parent's name (`find_matching_parent`, GE:6983): `'head'` → `head.x`, `'neck'` → `neck.x`, `'arm'` → `arm_stretch`, `'forearm'` → `forearm_stretch`, `c_root*` → `root.x`, and so on.

**Changelog 3.77.33** — CONFIRMED. It contains both "Support custom properties on humanoid skeletons, custom bones only" and "Custom bones parented to the first finger phalange were unparented when exporting" (fixed).

**Claw recipe** — sound, but these points are UNVERIFIED:
- Whether scale ~0.01 or translate is better per engine.
- `arp_bake_anim` defaults to True — CONFIRMED (GE:11896). Constraint-driven custom bones are then baked.

**Frog tongue or tentacle via `spline_ik`** — options CONFIRMED (`spline_fk`, `spline_bendy=0`, `spline_add_tail`). A built-in "shoot" / stretch control is UNVERIFIED.

**Alternative: extend the facial tongue.** `tongue_amount` goes up to 32, but see the Humanoid limitation in section 5.

### 5. Export

**Operators** — CONFIRMED: `arp.arp_export_fbx_panel` (GE:11756) and `arp.arp_export_gltf_panel` (GE:11793), each with `filepath` (StringProperty, default `'untitled'`).

**Scene properties and defaults** — CONFIRMED (GE:11869–12073):

| Property | Default |
|---|---|
| `arp_engine_type` (`UNITY` / `UNREAL` / `GODOT` / `OTHERS`) | `UNITY`; has an update callback |
| `arp_export_rig_type` (`HUMANOID` / `UNIVERSAL`) | `UNIVERSAL` |
| `arp_rename_for_ue` | True |
| `arp_mannequin_axes` | True; tooltip says 4 spine bones recommended |
| `arp_ue_ik` | True |
| `arp_ue_root_motion` | False |
| `arp_full_facial` | False |
| `arp_keep_bend_bones` | False |
| `arp_export_twist` | True |
| `arp_twist_fac` | 0.5 |
| `arp_units_x100` | True |
| `arp_bake_anim` | True |
| `arp_global_scale` | 1.0 |
| `arp_ge_sel_only` | False |
| `arp_export_triangulate` | False |
| `arp_ge_master_traj` | False; renamed `root` under UE rename |
| `arp_ge_export_metacarp` | False |

Others that exist: `arp_ue_ik_anim`, `arp_ge_sel_bones_only`, `arp_ge_add_dummy_mesh`, `arp_fix_fbx_rot`, `arp_init_fbx_rot`, `arp_ge_gltf_*`.

**Humanoid gate (`check_humanoid_limbs`, GE:2889)** — CONFIRMED. Export is refused if any of these is true:
- spine limbs > 1
- leg sides > 2
- heads > 1
- ear sides > 2
- `c_root_master.x` is missing
- `spine_count` < 1
- any `thigh_b_ref*` exists

Consequence: the dog and horse presets always need UNIVERSAL.

**Extra arms in Humanoid** — CORRECTED from UNVERIFIED. They are supported: arm sides beyond the first two are added through `arms_export_to_dict` (GE:6838).

**Extras that survive Humanoid** — CONFIRMED:
- Ears are collected explicitly (`c_ear_00..16`).
- Spline IK, tails, kilts, wings, subnecks, toes (when deforming), breasts and custom bones are also kept.
- `is_bone_extra_limb` (GE:4351) matches `c_tail_*`, `c_breast_*`, `c_ear_*`, key `arp_spline`, `arp_kilt` or `arp_feather`, and joint fans.

**New pitfall: renamed tails.**
- `is_bone_extra_limb` only recognises tails by the `c_tail_` prefix.
- Humanoid export tags tail bones with the literal key `"tail_name"`, not `arp_tail` (looks like a bug).
- So a tail with a custom `tail_name` is not classed as an extra limb and may get Mannequin-axes treatment (effect UNVERIFIED).
- Keep the default `tail_name='tail'`. For second chains use `_dupli` tails or spline_ik.

**UE renaming (`rename_for_ue`, GE:10378)** — CORRECTED detail:
- Skipped: bend bones, custom bones and `arp_ge_helper` bones only. Extra limbs are not skipped.
- Whole-name assignments that cause collisions:
  - `'head' in name` → `'head'`
  - `'root' in name` → `'pelvis'`
  - `'neck' in name` (other than `c_neck_01.x` and subnecks) → `neck_01` / `neck_NN`
- The others are substring replacements that rename without colliding: `thigh_stretch` → `thigh`, `leg_stretch` → `calf`, `toes_01` → `ball`, `shoulder` → `clavicle`, `arm_stretch` → `upperarm`, `forearm_stretch` → `lowerarm`, `c_index1` → `index_01`, and so on.
- Sides: `.l` / `.r` become `_l` / `_r`. `.x` is not stripped in this function — CONFIRMED. Whether the UE FBX importer later rewrites the `.` is UNVERIFIED.
- Rule: never use head, root or neck in tail, spline or kilt names. Avoid shoulder, arm_stretch, leg_stretch and thigh_stretch.

**Facial in Humanoid** — CONFIRMED with corrections:
- `default_facial_bones` (GE:28) is always exported when the face is on: `c_eyebrow_full`, `c_eyebrow_01_end`, `c_eyebrow_01..03`, `c_eye`, `c_eye_offset`, `eyelid_bot`, `eyelid_top`, `jawbone.x`, `c_lips_smile`, `c_eye_target`.
- **The jaw exports as `c_jawbone.x`** — CORRECTED. The humanoid bone `c_jawbone.x` copies the transforms of `jawbone.x`, and the mesh vertex group `jawbone.x` is renamed to `c_jawbone.x` (GE:6363, 7821).
- `additional_facial_bones` (GE:30) is exported only if `arp_full_facial=True`. It contains `c_teeth_bot/top`, `c_lips_bot/_01`, `c_lips_top/_01`, `c_lips_corner_mini`, `c_chin_01/02`, `c_cheek_smile`, `c_cheek_inflate`, `c_nose_01..03`, `c_eye_ref_track`, `tong_01..03`, `c_skull_01..03`, `c_eyelid_top/bot_01..03`, `c_eyelid_corner_01/02` and `c_eyelid_twk_top/bot`.
- Matching is `edit_bone.name[:-2] in additional_facial_bones`, so `tong_04+`, `c_lips_*_02+` and `c_eyelid_*_04+` are not exported in Humanoid. Confirmed by code; how their weights are handled is UNVERIFIED.
- Without Full Facial, weights move to `head.x` (`facial_transfer_head`) or to the jaw (`facial_transfer_jaw` = lips_bot, teeth_bot, chin, tong_01..03).
- Without Full Facial, eyelids are forced to deform.

**Universal (`_set_mped_rig`, GE:8562)** — CONFIRMED by reading. Facial export uses `ard.get_tongues(...)`, `get_variable_lips` and `get_variable_eyelids`, so variable tongue, lip and eyelid counts export. Use Universal when `tongue_amount > 3`, for quadrupeds, 3-bone legs, multiple heads, or more than one ear pair. Not run end-to-end.

**Unity and UE5 retarget behaviour** — UNVERIFIED. These are general engine claims and the Unity docs could not be fetched. Keep the guidance: Humanoid Avatar ignores extras, so use a Generic rig, procedural animation (spring / LateUpdate) or AnimDynamics / Control Rig.

### 6. Forge changes in `blender_scripts/forge_bpy/arp_rig.py`

The functions `place()`, `_place_refs`, `finish()` and `_ov()` exist — CONFIRMED. A sibling `appendages.py` also exists; check it for overlap.

1. Wrap `append_arp` **and** `add_limb` in `with bpy.context.temp_override(**_ov())`.
2. Add an `extras` stage after `place()`:
   - `add_limb`
   - select the ref bone
   - `show_limb_params('EXEC_DEFAULT', limb_type=..., side=..., load_settings_when_exec=False, reset_to_default_settings=False, ...)`
   - for tails always pass `tail_side`
   - for ears, prefer the module call `set_ears(n, side_arg='.l')`
3. Re-place the new refs: `tail_NN_ref`, `ear_NN_ref`, `<spline>_NN_ref`, `jaw_ref.x`, `tong_0N_ref.x`, `teeth_*_ref`.
4. Tag claws and other mechanical parts by name with `arp.bone_tag_add(name=..., tag='cc')`, or name them `cc_*`.
5. Choose the export mode:
   - Humanoid only if 1 spine, ≤ 2 leg sides, 1 head, ≤ 2 ear sides, no `thigh_b_ref`, and `tongue_amount ≤ 3`, `lips_amount ≤ 1`, `eyelids_amount ≤ 3`.
   - Otherwise `arp_export_rig_type='UNIVERSAL'`.
   - Set `arp_full_facial=True` whenever the mouth must open with teeth and tongue.
   - Keep `tail_bendy_count=1`, `spline_bendy=0`, no bbones limbs, and the default `tail_name`.
6. QA after export:
   - Assert the tail, ear, `tong_*`, `c_teeth_*`, `c_jawbone.x` and `cc_*` bones are present.
   - Assert there is exactly one `head` and one `pelvis`.
7. Weights: for tails and ears use `scn.arp_bind_engine = 'PSEUDO_VOXELS'` (Voxelized). Options are `'HEAT_MAP'` / `'PSEUDO_VOXELS'` / `'VHDS'` — CORRECTED from `'VOXELIZE'`, which does not exist. Note the 3.77.33 changelog fixed "binding multiple objects in Voxelized mode was broken", so stay at ≥ 3.77.33.

**Budgets** (mobile ~60–90 bones with 4 influences; UE5 ~150–250 bones with 8 influences) — UNVERIFIED heuristics. No source was reachable.

### Pitfalls summary

| Pitfall | Status |
|---|---|
| Headless: both `_add_limb` and `_append_arp` touch `space_data.overlay` | CORRECTED (broader than stated) |
| A `.l` / `.r` tail is reset to `.x` by `show_limb_params` if `tail_side` is not passed | NEW |
| Renamed tails are not classed as extra limbs in Humanoid export | NEW, effect UNVERIFIED |
| Humanoid drops tongue, lip and eyelid bones beyond the hard-coded counts | NEW |
| The Humanoid jaw is named `c_jawbone.x` | CORRECTED |
| Look up rig and edit bones again after `add_limb` / `join` / `match_to_rig` | CONFIRMED pattern |
| Kilt Pose-mode workaround applies only to 4.4.0 | CONFIRMED |

### Sources
- ARP source mirror: https://github.com/jasongzy/auto_rig_pro (3.77.33; `00_LOG.txt` is the changelog)
- https://raw.githubusercontent.com/thruthesky/model/HEAD/scripts/rig_animal_arp.py (patches both `space_data` lines)
- https://raw.githubusercontent.com/tipoLi5890/game-studio/HEAD/plugins/game-assets/skills/blender-retarget/scripts/brt_arp.py
- https://raw.githubusercontent.com/debakarr/mori-the-little-spirit/HEAD/tools/blender/arp_weights_mori.py
- Not reachable: lucky3d.fr, superhivemarket.com, docs.unity3d.com and the Unity discussions thread. Claims that rest on them are UNVERIFIED.
