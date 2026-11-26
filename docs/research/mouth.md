# Research: mouth (fact-checked)

## Mouth interiors for Forge: fact-checked report

### What I could check
- **Auto-Rig Pro source.** I downloaded the vendored **ARP 3.70.38** (`__init__.py` says `"version": (3, 70, 38)`) from `raw.githubusercontent.com/V-Sekai/V-Sekai.blender-game-tools/main/addons/auto_rig_pro-master/src/` and read `auto_rig.py`, `auto_rig_datas.py`, `auto_rig_ge.py` and `auto_rig_smart.py`. Line numbers below refer to that version. The user runs 3.79.17, so re-check every name with `blender_scripts/forge_bpy/addon_probe.py` or `hasattr` before relying on it.
- **bmesh operators.** I checked them against Blender `main` source (`BLENDER_VERSION 504`, i.e. 5.4): `source/blender/bmesh/intern/bmesh_opdefines.cc`, `bmesh/tools/bmesh_edgesplit.cc` and `bmesh/operators/bmo_utils.cc`. These slot signatures have been stable for years, so they almost certainly hold for 5.3, though I did not check a 5.3 tag specifically.
- **MediaPipe.** I checked the landmark indices against `mediapipe/python/solutions/face_mesh_connections.py` (`FACEMESH_LIPS`).
- **Unreachable sources.** This session's proxy blocked lucky3d.fr, docs.blender.org, 80.lv, cgtrader, gamedev.net, dev.epicgames.com, docs.unity3d.com, create.roblox.com, wiki.reallusion.com and studio.blender.org. Every claim that rests only on those sites is marked UNVERIFIED.

---

### 1. How studios build the mouth interior
- The parts list (bag, two arches with gums, tongue; upper arch on the head, lower arch, tongue and lower bag on the jaw) is standard practice. **UNVERIFIED** (sources unreachable). It does match how ARP itself splits weights at export: see §5, where `facial_transfer_jaw` = lower lips, `c_teeth_bot`, chins, `tong_01..03`. That part is **CONFIRMED** in `auto_rig_ge.py:45`.
- Triangle counts (3851/2578/1318; 474/440/276): **UNVERIFIED**. The 80.lv and cgtrader pages were unreachable. Treat them as anecdotes.
- Modelling the neutral pose closed, so the cut only separates the lips: a design choice, fine.
- Lip topology (concentric orbicularis loops, poles kept out of the corners, equal vertex counts on upper and lower lip): standard practice. **UNVERIFIED** against the Roblox and Reallusion pages, which were unreachable.

### 2. Scripted mouth cut (proposed `forge_bpy/mouth.py`)

**Where it goes in the pipeline. CORRECTED and extended.**
- There are **two** weld passes before retopology, not one:
  - `blender_addon/forge_send/geometry.py:375`, `repair()`: `remove_doubles(dist=size*merge_rel)` with `merge_rel=1e-4` × the object's diagonal. That is about **0.2 mm on a 2 m character**.
  - `blender_scripts/forge_bpy/cleanup.py:52`: `merge_dist = diag * 1e-5` (`cleanup.py:140,176`). That is about 0.02 mm.
- `repair()` also "closes every hole" with `max_hole_sides=1024` (`geometry.py:359-366`). **It will cap the mouth slit** if it runs after the cut.
- So the cut must run **after both `geometry.repair` and `cleanup`**. Alternatively, `repair` must skip boundary loops that `mouth.py` has tagged, for example with a boolean edge attribute `forge_mouth_slit`.
- A 0.3-0.5 mm gap is only just above repair's weld distance, so ordering is the real fix.

**Step 1: find the mouth corners. CONFIRMED (indices).**
- In `FACEMESH_LIPS`:
  - The outer lip loop runs 61…291, so 61 and 291 are the outer corners.
  - The inner loop runs 78…308, so 78 and 308 are the inner corners.
  - 13 is the inner upper-lip midpoint, on the inner top chain `82,13,312`.
  - 14 is the inner lower-lip midpoint, on `87,14,317`.
- The Face Landmarker Tasks API uses the same 468/478 mesh topology.
- Detection on stylised or creature faces: **UNVERIFIED**. Keep the "director clicks two vertices" fallback.
- `obj.ray_cast` and `mathutils.bvhtree.BVHTree.FromBMesh(bm).ray_cast(origin, direction)` are standard API and stable since 2.8. Not re-checked against the 5.3 docs.

**Step 2: find the lip line.**
- Dijkstra over `bm.edges` with `edge.calc_length()` is fine.
- `density.py` really does score "the mouth line" high (module docstring, line 4). **CONFIRMED.**

**Step 3: open the slit.**
- `bmesh.ops.split_edges(bm, edges=..., verts=..., use_verts=False)`. The output slot is `edges.out`, so in Python it is `ret['edges']` (this holds the input edges plus the new ones). **CONFIRMED.**
- "Only interior path vertices are duplicated; the end vertices stay shared." **CONFIRMED** by the implementation:
  - `BM_mesh_edgesplit` calls `BM_vert_separate_hflag` on each vertex of a tagged edge.
  - An end vertex has only one tagged edge, so its face fan stays connected and the vertex is not duplicated.
  - The result is one closed boundary loop.

**Step 4: build the bag. Signatures CONFIRMED against Blender main source.**
- `extrude_edge_only(edges, use_normal_flip, use_select_history)` → `ret['geom']` (verts, edges and faces). Filtering `BMVert` out of it is correct.
- `translate(vec, space, verts, use_shapekey)`.
- `scale(vec, space, verts, use_shapekey)`. **CONFIRMED** semantics: `bmo_transform_exec` computes `mat = inv(space) @ M @ space`, so `space=Matrix.Translation(-center)` scales about `center`.
- `holes_fill(edges, sides)` → `faces`. `sides=0` fills all holes.
- `edgeloop_fill(edges, mat_nr, use_smooth)` → `faces`.
- `grid_fill(edges, mat_nr, use_smooth, use_interp_simple)` → `faces`. Needs a loop it can divide into a grid: an even edge count, ideally ≥ 4 quads a side. **UNVERIFIED** for odd-count loops; fall back to `holes_fill`.
- `bridge_loops(edges, use_pairs, use_cyclic, use_merge, merge_factor, twist_offset)` → `faces`, `edges`. The equal-edge-count requirement is **UNVERIFIED**: Blender's bridge can handle unequal loops in some cases. Resampling the template loop is still the safe choice.
- `inset_region(faces, faces_exclude, use_boundary, use_even_offset, use_interpolate, use_relative_offset, use_edge_rail, thickness, depth, use_outset)`. **CORRECTED**: the report left out `faces_exclude`, `use_interpolate` and `use_relative_offset`.
- `connect_vert_pair(verts, verts_exclude, faces_exclude)`.
- `subdivide_edgering(edges, interp_mode, smooth, cuts, profile_shape, profile_shape_factor)`.
- `bisect_edges(edges, cuts, edge_percents)`.
- `remove_doubles(verts, use_connected, dist)`.
- `recalc_face_normals(faces)`.
- `reverse_faces(faces, flip_multires)`. Use this to flip the bag faces that test as wrong.
- `material_index` per face: standard (`BMFace.material_index`).

**Step 5: get lip loops out of Quad Remesher.**
- `retopo.py:269-270` sets `s.use_materials = False` and `s.use_normals = False`, where `s = bpy.context.scene.qremesher` (`retopo.py:262`). **CONFIRMED.** These property names already work on the user's PC.
- Note that `s.use_vertex_color` is already in use as the density driver (`retopo.py:267`).
- That QR preserves open borders as edge loops is **UNVERIFIED**. Expected, but confirm with one test run.

**Step 6: baking.** Excluding the bag, teeth and tongue from the dense→low bake and giving them flat colour plus a vertex-colour or AO gradient is a design choice. Sound.

### 3. Teeth, tongue and gums: templates versus AI
- Template plus lattice/bbox fit: a design recommendation. The fit ratios are **UNVERIFIED** heuristics.
- Tripo for interior parts: the prompt's effectiveness is **UNVERIFIED**.
- **CORRECTED.** "One object per arch, which ARP's binding expects" is only half right. ARP accepts **either** `scene.arp_teeth_type='SINGLE'` (one object for both arches, `arp_teeth_name`) **or** `'SEPARATE'` (`arp_teeth_name` is the upper arch, `arp_teeth_lower_name` the lower), per `auto_rig.py:39920-39922`. Use `SEPARATE`, because then upper binds only to `top` bones and lower only to `bot` bones.

### 4. Budgets: all UNVERIFIED (rules of thumb)
- The table can stay as an internal guideline, but no reachable source backs the numbers.
- **CORRECTED (Unity).** "Extra jaw and tongue bones count against Quality → Skin Weights" is wrong. The Unity Quality setting *Skin Weights* (`QualitySettings.skinWeights`: One/Two/Four/Unlimited) caps **influences per vertex**, not bone count.
  - Extra bones cost skinning and matrix-palette work, not "skin weights".
  - Keep 4 influences per vertex for mobile.
  - Forge's `steps.build_rig(max_influences=8)` must clamp to 4 for the Unity/mobile profile.
  - Setting names are from memory: docs.unity3d.com was unreachable.
- **UE5.**
  - FBX import option "Normal Import Method = Import Normals and Tangents": from memory, **UNVERIFIED**. UE 5.5+ defaults to the Interchange importer, whose option names differ.
  - `MI_Teeth_Baked`: **UNVERIFIED** (Epic docs unreachable).
  - Opaque, Default Lit for the mouth: fine.

### 5. Rigging in Auto-Rig Pro (re-verified in the 3.70.38 source)

**The operator.**
- `ARP_OT_show_limb_params`: `bl_idname="arp.show_limb_params"`, `bl_label="Limb Options"` (`auto_rig.py:873-877`). **CONFIRMED.**
- These properties exist (`auto_rig.py:920-978, 1136-1137`). **CONFIRMED.**

  | Property | Type | Default |
  |---|---|---|
  | `limb_type` | Str | |
  | `side` | Str | |
  | `load_settings_when_exec` | | False |
  | `reset_to_default_settings` | | True |
  | `facial` | | True |
  | `facial_mouth` | | True |
  | `facial_teeth` | | True |
  | `facial_tongue` | | True |
  | `facial_chins` | | True |
  | `facial_noses` | | True |
  | `facial_cheeks` | | True |
  | `facial_eye_l` / `facial_eye_r` | | True |
  | `facial_eyebrow_l` / `facial_eyebrow_r` | | True |
  | `skull_bones` | | False |
  | `lips_amount` | Int | 2 (1-32) |
  | `auto_lips` | | True |
  | `jaw_rotation` | | **False** |
  | `unlock_jaw_y` | | |
  | `lips_floor` | | |
  | `lips_roll_cns` | | |
  | `jaw_separate_location` | | |

- `execute()` with `limb_type=='head'` calls `set_facial(...)`. Only when `facial` is True does it then call `set_jaw_rotation_location(jaw_rotation, auto_lips_visual, jaw_separate_location)` and `set_eyetargets_distance` (`auto_rig.py:1788-1875`). **CONFIRMED.**

**CORRECTED and added pitfalls:**
- Every `facial_*` sub-module defaults to **True**. Any sub-module you don't pass explicitly as False gets enabled at its default, scaled ref position. Pass False for every module you don't place.
- Even with `load_settings_when_exec=False`, the **ARP armature must be the active object in EDIT mode with `head_ref.x` selected**.
  - `set_facial` reads `context.active_object` and `get_selected_edit_bones()` to work out the side.
  - `set_jaw_rotation_location` falls back to `side=""` when nothing is selected. It then looks for `"head_ref"`, which does not exist (`auto_rig.py:36039-36060, 36169-36200`).
  - If `head_ref.x` is missing, `set_facial` prints "does not exist" and **returns silently**. Assert afterwards that `rig.data.bones.get('jaw_ref.x')` exists.

**Custom properties stored on `head_ref.x`. CONFIRMED, with the list extended:**
- `facial`, `mouth_enabled`, `teeth_enabled`, `tongue_enabled`
- `chins_enabled`, `noses_enabled`, `cheeks_enabled`
- `eye_l_enabled`, `eye_r_enabled`, `eyebrow_l_enabled`, `eyebrow_r_enabled`
- `skull_bones`, `lips_amount`, `auto_lips`, `lips_roll_cns`, `unlock_jaw_y`, `jaw_speed`
- `arp_jaw_rotation`, `arp_jaw_location`

The export code decides whether the face is enabled with `head_ref['facial']==1` (`auto_rig_ge.py:2545`).

**Skulls. CONFIRMED.**
- Names: `c_skull_01.x`, `c_skull_02.x`, `c_skull_03.x` (`auto_rig_datas.py:296-300`).
- Which areas they cover (mouth / eyes / head top) is from the property description, `"deform the mouth, eyes and head top areas"`.
- In code, `c_lips_roll_top` and `c_teeth_top_master` are parented to skull_01 (otherwise head), and the cheeks to skull_02 (`auto_rig.py:36525-36536`).

**Reference bones. CONFIRMED** in `auto_rig_datas.py:318-331, 465-466, 491-494, 534-537`.
- Jaw: `jaw_ref.x`.
- Chin: `chin_01_ref.x`, `chin_02_ref.x`.
- Lips:
  - `lips_top_ref.x`, `lips_bot_ref.x`
  - `lips_top_ref.l/.r`, `lips_bot_ref.l/.r`
  - `lips_top_01_ref.l/.r`, `lips_bot_01_ref.l/.r`
  - `lips_smile_ref.l/.r`, `lips_corner_mini_ref.l/.r`
  - `lips_roll_top_ref.x`, `lips_roll_bot_ref.x`
  - **Missed by the report:** `lips_offset_ref.x`. It drives the `c_lips_offset.x` control, which is copied from it at `auto_rig.py:23815-23819`.
  - Extra lips from `lips_amount` follow `lips_{top_|bot_}NN_ref.l/.r` (`get_variable_lips`).
- Teeth: `teeth_top_ref.x/.l/.r`, `teeth_bot_ref.x/.l/.r`.
- Tongue: `tong_01_ref.x`, `tong_02_ref.x`, `tong_03_ref.x`.
- Cheeks: `cheek_smile_ref.l/.r`, `cheek_inflate_ref.l/.r`.
- Eyes:
  - `eye_offset_ref.l/.r`
  - `eyelid_top_ref`, `eyelid_bot_ref`, `eyelid_twk_top_ref`, `eyelid_twk_bot_ref`
  - `eyelid_top_01_ref` / `eyelid_bot_01_ref`, `eyelid_corner_01_ref` / `eyelid_corner_02_ref`
  - plus `eyelid_*_02/03_ref`
- Eyebrows: `eyebrow_full_ref`, `eyebrow_01_end_ref`, `eyebrow_01_ref`, `eyebrow_02_ref`, `eyebrow_03_ref`.
- Nose: `nose_01_ref.x` … `nose_03_ref.x`.

**Jaw formula in ARP Smart. CONFIRMED verbatim** (`auto_rig_smart.py:2344-2348`):
- `jaw.head = head_ref.head + (head_ref.tail-head_ref.head)*0.2 + (chin_02_ref.head-head_ref.head)*0.2`
- `jaw.tail = chin_02_ref.head`

Placing the tongue refs depends on `teeth_top_ref.x`, `lips_top` and `nose_01`, so place teeth and lips before the tongue. The Smart operators `id.facial_setup` and `id.validate_facial_setup` exist (`auto_rig_smart.py:33,80`). **CONFIRMED.**

**Bones the rig produces. CONFIRMED** (`auto_rig_datas.py:333-361, 497-502, 540-546`):

| Bone | Deform | Control |
|---|---|---|
| `c_jawbone.x` | no | yes |
| `jawbone.x` | yes | |
| `jawbone_track.x` | helper | |
| `c_teeth_top_master.x`, `c_teeth_bot_master.x` | no | |
| `c_teeth_top.x/.l/.r`, `c_teeth_bot.x/.l/.r` | yes | yes |
| `c_tong_01..03.x` | no | yes |
| `tong_01..03.x` | yes | |
| `c_lips_top(.x/.l/.r)`, `c_lips_top_01.l/.r`, `c_lips_bot…`, `c_lips_smile.l/.r`, `c_lips_corner_mini.l/.r` | yes | |
| `c_lips_roll_top.x`, `c_lips_roll_bot.x`, `c_lips_offset.x` | no | |
| `c_chin_01.x`, `c_chin_02.x` | yes | |

- The parent of `c_teeth_bot_master.x` comes from ARP's template armature, not from code. Still **UNVERIFIED**; keep the `parent_recursive` assert.
- The masters are placed at `ref.head + (ref.head - ref.tail)/2` (`auto_rig.py:23855-23866`).

**Binding. CONFIRMED.**
- Scene properties: `arp_tongue_name`, `arp_teeth_name`, `arp_teeth_type` (`'SINGLE'`/`'SEPARATE'`), `arp_teeth_lower_name`, `arp_eyeball_type`, `arp_eyeball_name`, `arp_eyeball_name_right` (`auto_rig.py:39916-39922`).
- `arp_bind_split` exists, **default True** (`auto_rig.py:39871`).
- Operator: `arp.bind_to_rig`, which expects the meshes selected first and then the armature (`auto_rig.py:4417-4421`).

Conditions that turn auto-skinning off (`auto_rig.py:17339-17360`). **CONFIRMED**, with more conditions than the report listed:
- `auto_tongue` is off if the face is disabled **or** `get_object(scn.arp_tongue_name)` is None.
- `auto_teeth` is off if `c_eye.l` or `c_eye.r` is missing, **or** the teeth object, or the lower-teeth object in SEPARATE mode, is not found.
- **Practical consequence:** a creature rigged with `facial_eye_l/r=False` gets **no automatic teeth skinning**. Forge must then weight the teeth 100% itself.

Per-object skinning:
- The tongue object binds with only the `tong_0X.x` deform bones enabled.
- The teeth objects bind with only `top`/`bot` teeth bones (`auto_rig.py:18035-18055`).
- Those bones are disabled for every other mesh (`auto_rig.py:17598-17609`). **CONFIRMED.**

The fallback of weighting props 100% to one bone, and fixing lower-lip and upper-lip weights after the heat-map bind, are design recommendations. Sound.

**Pose test.**
- With `jaw_rotation=False` (the default), `c_jawbone.x` opens the jaw by **location**.
- With True, by rotation. The setting is stored as `head_ref['arp_jaw_rotation']`.
- The exact axis and sign are **UNVERIFIED**. Read `head_ref['arp_jaw_rotation']` and test both signs, measuring the chin's displacement.

**Export (`auto_rig_ge.py`). CORRECTED.**
- `default_facial_bones` (`auto_rig_ge.py:36`) = `c_eyebrow_full`, `c_eyebrow_01_end`, `c_eyebrow_01..03`, `c_eye`, `c_eye_offset`, `eyelid_bot`, `eyelid_top`, `jawbone.x`, `c_lips_smile`, `c_eye_target`. **CONFIRMED.**
- `additional_facial_bones` (`:38-43`) holds teeth, lips, chins, cheeks, noses, `c_eye_ref_track`, `tong_01..03`, the skulls and the secondary eyelids. They are added to the export skeleton only when `scene.arp_full_facial and is_facial_enabled(rig)` (`:5207-5211`). `arp_full_facial` is registered as "Full Facial", default False (`:9657`). **CONFIRMED.**
- **Previously UNVERIFIED, now CONFIRMED:** when Full Facial is off, ARP **moves the weights itself** (`auto_rig_ge.py:6252-6262`):
  - Skulls → `head.x`.
  - `facial_transfer_head` (all the upper facial bones) → `head.x`.
  - `facial_transfer_jaw` = `c_lips_bot_01`, `c_lips_bot`, `c_teeth_bot`, `c_chin_01/02`, `tong_01..03`, plus any extra `bot_` lips → the jaw bone.
  - So **no manual re-weighting is needed for mobile**: just leave Full Facial off.
- **Added:** in the humanoid export the jaw deform bone is written as **`c_jawbone.x`**, built from `jawbone.x`. Meshes' `jawbone.x` vertex group is renamed to `c_jawbone.x` (`auto_rig_ge.py:5292-5299, 6217-6223`). Engine-side code (UE AnimBP / Unity) must look for `c_jawbone`, not `jawbone`.
- With Full Facial on, `jawbone` is parented to `c_skull_01.x` if it exists, otherwise `head.x` (`:5644-5649`).
- **Rename for UE** (`rename_for_ue`, `:8592-8750`):
  - `.l`/`.r` become `_l`/`_r`.
  - **Any bone whose name contains `head` is renamed to `head`.** Pitfall: never give a custom or extra-part bone a name containing "head".
  - No facial-specific renames appear.
  - Handling of the `.x` suffix is **UNVERIFIED**. Confirm by reading the bone names in the exported FBX.
- Forge's `finalize.py:253-255` uses `arp_export_rig_type='HUMANOID'` and `arp_rename_for_ue=True` for Unreal, so all of the above applies. `arp_ge_sel_only` exists in 3.70.38.

### 6. Pitfalls checklist (corrected and extended)
1. `geometry.repair` welds at about 1e-4 × the diagonal and **fills holes of up to 1024 sides**. `cleanup` welds at 1e-5 × the diagonal. Cut the slit after both, or teach `repair` to skip tagged slit loops.
2. Exclude the bag, teeth and tongue from the dense→low raycast bake. Give them their own material.
3. Split both lips from one path so upper and lower get equal vertex counts (`split_edges` behaviour confirmed).
4. Cap the bag (`holes_fill` / `grid_fill`) and fix its normals with `reverse_faces`.
5. ARP: pass `False` for every `facial_*` sub-module you don't place; all default to True.
6. ARP: the rig must be active, in EDIT mode, with `head_ref.x` selected when calling `arp.show_limb_params`. Assert `jaw_ref.x` exists afterwards.
7. ARP: `auto_teeth` needs both `c_eye.l` and `c_eye.r` to exist. With the eyes disabled, weight the teeth manually.
8. Mobile: leave `arp_full_facial=False`. ARP folds teeth, tongue and lip weights into head and jaw automatically. Clamp to 4 influences per vertex for Unity.
9. The exported jaw bone is `c_jawbone(.x)`, not `jawbone`.
10. Rename for UE: any bone containing "head" becomes `head`.

### Sources (reached and read)
- ARP 3.70.38 source: https://github.com/V-Sekai/V-Sekai.blender-game-tools/tree/main/addons/auto_rig_pro-master/src (`auto_rig.py`, `auto_rig_datas.py`, `auto_rig_ge.py`, `auto_rig_smart.py`)
- Blender bmesh op definitions: https://github.com/blender/blender/blob/main/source/blender/bmesh/intern/bmesh_opdefines.cc ; `bmesh/tools/bmesh_edgesplit.cc` ; `bmesh/operators/bmo_utils.cc`
- MediaPipe lip landmarks: https://github.com/google-ai-edge/mediapipe/blob/master/mediapipe/python/solutions/face_mesh_connections.py

**Cited but unreachable, so their claims are UNVERIFIED:**
- lucky3d.fr ARP docs
- docs.blender.org
- 80.lv
- cgtrader
- gamedev.net (OmniFaceRig)
- Epic MetaHuman docs
- Roblox
- Reallusion wiki
- Unity docs
- studio.blender.org
- blenderartists.org
- thita.cc

### Repo files (verified)
- `/home/user/Image-to-Game-asset/blender_addon/forge_send/geometry.py:359-377`: `repair()` weld plus hole fill. **New, missed by the original report.**
- `/home/user/Image-to-Game-asset/blender_scripts/forge_bpy/cleanup.py:52` (`remove_doubles`) and `:140,176` (`merge_dist` = diag × 1e-5).
- `/home/user/Image-to-Game-asset/blender_scripts/forge_bpy/retopo.py:262-270`: `scene.qremesher`; `use_materials`/`use_normals` are hard-coded False.
- `/home/user/Image-to-Game-asset/blender_scripts/forge_bpy/arp_rig.py:119` (`ref_targets`), `:179` (`_place_refs`), `:209` (`place`): no face refs, only `head_ref.x` at `:133`.
- `/home/user/Image-to-Game-asset/blender_scripts/forge_bpy/finalize.py:253-275`: ARP export settings; it needs `arp_full_facial` per profile.
- `/home/user/Image-to-Game-asset/blender_scripts/forge_bpy/density.py:4`: the mouth-line score.
- `/home/user/Image-to-Game-asset/blender_addon/forge_send/steps.py:464` (`build_rig(max_influences=8)`, needs 4 for mobile) and `:501` (`pose_test`, needs a jaw-open pose).
