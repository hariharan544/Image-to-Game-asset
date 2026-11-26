# Research gap: Squash-and-stretch, bone scale and cartoon deformation export

# Forge gap report: squash-and-stretch, bone scale and cartoon deformation export

## How this was researched, and its limits

**Checked against source code (CONFIRMED):**
- **Blender 5.3 bundled FBX exporter:** `io_scene_fbx/export_fbx_bin.py` and `fbx_utils.py` from the local bpy wheel at `/tmp/claude-0/bpyenv/lib/python3.13/site-packages/bpy/5.3/scripts/addons_core/io_scene_fbx/`.
- **Blender main constraint and armature code:** `source/blender/blenkernel/intern/constraint.cc` (`stretchto_evaluate`) and `source/blender/makesdna/DNA_armature_types.h`, downloaded from github.com/blender/blender to `/tmp/claude-0/-home-user-Image-to-Game-asset/f1ff8269-309f-546b-b536-494e8126b836/scratchpad/bsrc/`.
- **Auto-Rig Pro 3.77.33:** the mirror at https://github.com/jasongzy/auto_rig_pro, cloned locally at `/tmp/claude-0/-home-user-Image-to-Game-asset/f1ff8269-309f-546b-b536-494e8126b836/scratchpad/arp_src/src/`. Files used: `auto_rig_ge.py`, `auto_rig.py` and `lib/constraints.py`. Line numbers below refer to these files.
- **Forge's own code:** `blender_scripts/forge_bpy/finalize.py` and `blender_addon/forge_send/steps.py`.

**What I could not reach:**
- docs.unity3d.com, dev.epicgames.com and www.lucky3d.fr do not resolve in this session. They need to be added to the session's allowed network domains.
- The web-search budget for this turn was already used up.
- So every Unreal Engine and Unity behaviour below comes from prior knowledge and is marked UNVERIFIED. Re-check those claims once those hosts are allowed.
- ARP 3.79.17 behaviour that differs from 3.77.33 is UNVERIFIED.

---

## 0. Key finding: what survives the trip from Blender to each engine

1. **The Blender FBX exporter writes plain TRS with no shear.** CONFIRMED, `fbx_utils.py` lines 1694–1704 and 1818–1828.
   - For a posed bone it computes `local = parent_pose.matrix.inverted_safe() @ pose.matrix`, then `matrix.decompose()` into location, rotation and scale.
   - It always writes `InheritType = 1` ("RSrs"), at `export_fbx_bin.py` lines 1951 and 2010.
   - Consequences:
     - Blender's per-bone **Inherit Scale** mode (FULL / FIX_SHEAR / AVERAGE / NONE / NONE_LEGACY / ALIGNED, `DNA_armature_types.h` lines 182–192) is not exported as a flag. It is baked into each child's local TRS.
     - Maya's **Segment Scale Compensate** never appears in a Blender FBX. Its effect is baked in the same way.
     - Any **shear** in a child's local matrix is lost when the matrix is decomposed. Shear appears when a non-uniformly scaled parent has a rotated child with Inherit Scale FULL.
2. **Unreal Engine:** `FTransform` is translation + quaternion + scale. Composing two transforms multiplies the scales per component and cannot represent shear. UNVERIFIED (from UE source comments as I remember them). So a non-uniformly scaled parent with a rotated child resolves differently in UE than in Blender FULL inheritance.
3. **Unity:** a `Transform` builds `localToWorldMatrix` by full matrix multiplication, so a child of a non-uniformly scaled parent is skewed. This is the same as Blender FULL with no compensation. UNVERIFIED.
   - Result: the same FBX can look different in UE and Unity whenever a non-uniform scale passes through to a rotated child.
4. **Rule that makes all three match: no deform bone may inherit non-uniform scale from a parent.**
   - Non-uniform scale is allowed only on:
     - **leaf** deform bones, or
     - bones whose deform children are **not** their FBX children (the stretch bone and the joint bone are siblings), or
     - bones converted to **translation-only stretch**, which is ARP's "soft-link".
   - Uniform scale on a parent is safe everywhere.
5. **Unity Humanoid drops scale** (and translation unless Translation DoF is on) on humanoid bones. UNVERIFIED.
   - Generic rigs keep scale curves on every transform. UNVERIFIED but long-standing behaviour.
   - So cartoon assets that need squash/stretch must import into Unity as **Generic**, or the stretch must be moved into blend shapes.

---

## 1. Bone scale through FBX (inherit modes, segment scale compensation)

**(a) Why it matters.**
- Squash/stretch, cartoon "smears", bulging and hiding parts by scaling to near zero all rely on bone scale.
- If scale reaches the engine wrongly, limbs shear, children "swim", and silhouettes differ between Blender approval and the game.

**(b) Topology.** Unaffected by the export itself. See §6 and §7 for the loops that stretch needs.

**(c) Rig requirements.**
- **Rest pose scale must be 1** on every bone and the armature object must be unscaled. Apply scale before export.
  - ARP's export already applies object scale (`auto_rig_ge.py` around line 3466: `transform_apply(scale=True)`). CONFIRMED.
- **Inherit Scale policy, set by Forge before bake:**
  - Leaf and "end" deform bones (head, hands, feet, tail tip, props): FULL is fine.
  - A deform bone whose parent may scale non-uniformly: set the child to `inherit_scale='NONE'` or `'ALIGNED'` in the *control* rig.
    - Then make sure the **exported** deform child is either uniformly scaled itself, or its parent's scale is uniform.
    - The exporter bakes the compensation as an inverse local scale. That is exact only when the child's axes line up with the parent's.
  - Simplest safe pattern: keep the deform hierarchy free of non-uniform scale on non-leaf bones. Put stretch into translation (soft-link, §4) or into leaf "bulge" bones parented beside the joints.
- **The equivalent of Maya Segment Scale Compensate is `inherit_scale='NONE'`.** It is not needed for FBX, because the exporter bakes it, and it is risky for UE (see 0.2).

**(d) Texture/material.** No special maps. Strong non-uniform scale makes texels and normal-map detail stretch visibly (see §9).

**(e) Automation in Blender.**
- **Shear detector:** after baking the deform skeleton (`bpy_extras.anim_utils.bake_action_objects`, already used in `docs/research/mech.md`), sample every frame and every deform bone. For `M = pose_bone.matrix.to_3x3()`, measure `max |cos(angle between columns)|`. Anything above `1e-3` means the shear will not survive and UE will differ from Blender.
- **Fix candidates for the director (one click):**
  - Convert that bone's stretch to soft-link.
  - Or set its children to `inherit_scale='NONE'` and re-bake.
- **Validator** (pure Python, runs inside Blender):
  ```python
  def shear(m3):
      c = [m3.col[i].normalized() for i in range(3)]
      return max(abs(c[0].dot(c[1])), abs(c[1].dot(c[2])), abs(c[0].dot(c[2])))
  def local_trs(pb):                       # exactly what the FBX exporter writes (fbx_utils.py 1700-1703)
      par = pb.parent
      m = (par.matrix.inverted_safe() if par else Matrix()) @ pb.matrix
      return m.decompose()
  ```

**(f) Engine notes.**
- Use the same FBX for both engines, but recompose with the engine's own rule to predict the result (see §10).
- UE Interchange vs. legacy FBX import: no documented difference for scale handling. UNVERIFIED.

---

## 2. Unreal Engine 5: non-uniform bone scale and import gotchas (all UNVERIFIED, docs unreachable)

**(a) Why it matters.** AAA cartoon characters in UE (Fortnite-style) do animate bone scale. It works if the hierarchy rule in 0.4 is respected.

**(c) Rig and engine requirements.**
- **Scale tracks:**
  - The AnimSequence import keeps scale tracks.
  - Compression (ACL by default in UE5) compresses scale. Constant all-1 scale tracks are stripped, which is fine.
- **No shear (`FTransform`):**
  - Non-uniform parent scale with rotated children gives "approximately right" results that differ from Blender and Unity.
  - UE's own tools (Control Rig, Sequencer) behave the same way, so a UE-authored squash also avoids deep non-uniform chains.
- **Reference pose:**
  - Keep rest scale at 1.
  - Use T0 As Ref Pose is not needed. Never ship a bind pose with scaled bones.
- **Retargeting:**
  - The IK Retargeter and skeleton "Translation Retargeting" deal with rotation and translation.
  - Bone scale is not retargeted to a different skeleton.
  - So squash/stretch animation only plays correctly on the same skeleton or on a compatible-skeleton mesh.
- **Physics Asset:**
  - Bodies attached to scaled bones do not follow the scale at runtime.
  - Ragdoll or hit detection on stretched limbs will not match.
  - Keep stylised squash off physics-driven bones, or accept the mismatch.
- **Bounds:**
  - Big stretches go outside the skeletal mesh's ref-pose bounds and cause culling pops.
  - Set `Positive/Negative Bounds Extension` on the Skeletal Mesh asset.
  - Or set "Use Bounds From Leader Pose" or increase bounds scale on the component.
- **Scale toward zero (hiding parts):**
  - Use 0.001–0.01, not 0, to avoid degenerate normals and tangents.
  - Already in the mech report (`docs/research/mech.md`): staggered translation is preferred, and the "hide" key goes on the claw bone only.
- **Morph-target alternative:**
  - UE imports blend-shape animation from FBX as morph-target curves.
  - Curves can also drive material parameters (anim curve type "Material"), useful for stretch-wrinkle masks.

---

## 3. Unity: Humanoid avatar vs. Generic rig (UNVERIFIED, docs unreachable)

**(a) Why it matters.**
- Forge currently sets ARP `arp_export_rig_type='HUMANOID'` for Unity (`finalize.py`, `ARP_ENGINE`). That is an ARP skeleton *layout*.
- The engine behaviour depends on Unity's **Rig → Animation Type** at import.

**(c) Requirements.**
- **Humanoid (Avatar + muscle space):**
  - Clips store muscle values (rotations), root motion and IK goals.
  - **Bone scale is discarded on humanoid bones.**
  - Translation on humanoid bones is kept only with **Translation DoF** enabled, and only for some bones.
  - Extra (non-humanoid) transforms keep generic curves only when they are included in the clip's **Avatar Mask / Transform mask** at import.
- **Generic:**
  - Keeps translation, rotation and scale curves on every transform. There is no retargeting.
  - **Use Generic for any Forge asset tagged `stylised_deform`.**
- **Mobile skin weights:**
  - Project Settings → Quality → Skin Weights can be 1, 2, 4 or Unlimited.
  - URP mobile commonly uses 2 or 4. Bendy-limb approximations (§6) need ≥ 2 influences, and 4 is better.
- **Animation import compression:** Keyframe Reduction has separate Rotation / Position / **Scale Error** tolerances (default ≈0.5%). Small squash keys can be optimised away; lower Scale Error for cartoon clips.
- **Bounds:** set `SkinnedMeshRenderer.updateWhenOffscreen` or enlarge `localBounds` for big stretches.

**(e) Automation.**
- Forge writes a Unity `.meta` / `ModelImporter` preset next to the FBX:
  - `animationType = Generic` when the asset has the `stylised_deform` flag.
  - Otherwise Humanoid for retargetable characters.
- In practice, the Unity import is done by an editor script in batchmode that reads a Forge sidecar JSON. This is an UNVERIFIED design choice, not a Unity requirement.

---

## 4. ARP stretch: IK stretch, auto-stretch, soft-link, and the check/fix operators

**(a) Why it matters.**
- ARP limbs stretch through `c_stretch_arm/leg` controllers, the `auto_stretch` and `stretch_length` properties, and spine "Stretch and Squash".
- ARP itself treats these as export hazards.

**(c) Rig facts, CONFIRMED in 3.77.33:**
- **`arp.check_rig_export`** (`auto_rig_ge.py` line 860):
  - Flags non-zero `c_stretch_arm./c_stretch_leg./c_stretch_thigh_b` positions, `auto_stretch != 0` and `stretch_length != 1` (lines 4063–4103).
  - The warning text: "it can potentially lead to bones rotation issues" (line 929).
  - It also flags spline-IK `y_scale != 2` / `stretch_mode != 1` (line 4073).
- **`arp.fix_rig_export`** (line 847) "Disabled all possible arms and legs stretches" and "Disabled Preserve Volume on skinned meshes".
  - **Forge must not call `fix_rig_export` on cartoon assets:** it would delete the stylisation.
  - Forge currently calls neither operator (grep found none).
- **Soft-link** (`arp.set_bone_tag` with `tag='softlink'`, line 501):
  - Tooltip: "Set selected bones as soft-link, for stretchy deformations. Scale values are maintained to 1, while keeping the actual stretched bone position. Only for deforming bones."
  - What export does with it:
    - The tagged bone's copy constraints become Copy Location + Copy Rotation (`lib/constraints.py`, `add_copy_transf(no_scale=True)`).
    - `use_connect` is set to False (line 7285).
    - For `arm_stretch` / `thigh_stretch` it uses helper bones (lines 7618–7660).
  - Net effect: **stretch is exported as translation, scale stays 1.** This survives UE, Unity Generic and (with Translation DoF) partly Unity Humanoid.
  - It cannot show *thickness* change. Volume preservation must then come from bulge bones or blend shapes (§7).
  - The tag is stored as a custom property `bone["softlink"] = 1` (line 3845 / `_set_softlink_bones` line 3906), so Forge can set it directly:
    ```python
    for name in ("arm_stretch.l","forearm_stretch.l","thigh_stretch.l","leg_stretch.l", ...):
        rig.data.bones[name]["softlink"] = 1     # equivalent to arp.set_bone_tag(tag='softlink')
    ```
  - The `arp_retro_export_soft_fix` scene property (hidden) keeps the old positions. Leave it False.
- **Spine squash** (`spine_master_stretchy`, "Add automatic stretch and squash when moving the spine master", `auto_rig.py` line 1294):
  - It uses deforming `spine_str_cns_XX` bones.
  - Export retargets the humanoid spine copy constraints to `spine_str_cns_xx` when the base spine is non-deforming (lines 7434–7448). CONFIRMED that this path exists.
  - Whether its scale stays shear-free: run the §1 detector. UNVERIFIED.
- **Head squash:** ARP adds a "jawbone track bone to support head squash and stretch" (`auto_rig.py` line 14371).
  - The head is near-leaf, so uniform or non-uniform scale on `head` is OK if facial deform children are not rotated relative to it.
  - Otherwise use soft-link or `inherit_scale` handling.

**(e) Automation.**
- Forge adds a `stylised` rig profile:
  - Set `softlink` on limb stretch bones.
  - Set `rig.arp_secondary_type='TWIST_BASED'` (§5).
  - Skip `fix_rig_export`.
  - Run `check_rig_export` only for its report.
  - Run the §1 shear detector and the §10 engine simulation.
- Director action: none unless the detector fails. Then one click: "convert to soft-link / flatten scale".

---

## 5. Bendy bones and twist conversion for export (ARP)

**(a) Why it matters.** Rubber-hose arms and smooth curves need more than one deform segment per limb bone. B-Bones do this in Blender but **are not exportable**.

**(c) ARP facts, CONFIRMED:**
- **`Object.arp_secondary_type`** (`auto_rig.py` line 49519):
  - `'TWIST_BASED'`: "Twist (Exportable, best) … Best compatibility with Fbx Export. Works best with multiple twist bones."
  - `'BENDY_BONES'`: "Good for very stretchy/cartoony characters. Warning, the secondary controllers and twist bones will not be exportable to FBX."
  - `'ADDITIVE'`: Legacy, exportable.
  - `'NONE'`.
- **Export options** (`auto_rig_ge.py` lines 11884–11888):
  - `arp_export_twist` (default True): "If disabled… twist weights are transferred to the main weights."
  - `arp_twist_fac` (default 0.5): "Generally 0.5 gives better results since game engines do not support dual quaternions". This is forced to 1.0 when there is more than one twist bone (lines 1057, 1155).
  - `arp_keep_bend_bones` (UI "Advanced"): "Export secondary controllers ("_bend" bone). Useful for cartoons rigs… In Twist mode, arms and legs secondary controllers are always exported."
  - `arp_push_bend` ("Push Additive"): scales up the additive bend bones' animation to make up for the missing additive Armature modifier (`_push_bend_bones`, line 3398). It skips scale curves.
- **Bendy-Bones *limbs* (`arp_bbones`) block export**: "Bendy-Bones are not exportable to Fbx" (line 885).
  - ARP's own source has a TODO to convert bbones to real bones (line 9429). There is **no built-in bbone-to-bone conversion.**
- **For export:**
  - Use `TWIST_BASED` with **multiple twist bones** per arm/leg segment (the `twist_bones_amount` limb property).
  - Set `arp_keep_bend_bones=True` when bend controllers are animated.
  - Keep `arp_export_twist=True`.
  - Keep `tail_bendy_count=1` and `spline_bendy=0` (already in `docs/research/arp_limbs.md`).

**(d) Texture.** None.

**(f) Engines.**
- Twist and bend bones arrive as ordinary bones. UE and Unity Generic play them.
- Unity Humanoid ignores them unless they are masked in (§3).
- UE IK Retargeter will not drive them, so use Control Rig or post-process (UNVERIFIED).

---

## 6. Approximating bendy limbs with extra deform bones (for custom B-Bone chains)

**(a) Why it matters.** Tails, tentacles, rubber-hose limbs and noodle props look best as B-Bones. Engines need real bones.

**(b) Topology.**
- Even edge loops along the length, at least as many loops as segments, ideally two loops per segment.
- Indicative targets, not a standard: AAA 3–4 loops per segment with 4–8 segments per limb; mobile 2 loops per segment with 3–4 segments.
- Avoid poles inside the bending region.

**(c) Rig: "bake B-Bone segments to real bones" (Forge-generated).**
1. For a B-Bone `B` with N segments, create deform bones `B_seg_00` to `B_seg_{N-1}`, not parented under each other. Parent them to `B`'s parent.
   - Not chaining them avoids inherited non-uniform scale (rule 0.4).
2. On each, add `COPY_TRANSFORMS` with target the armature, subtarget `B`, `head_tail = i/N`, and `use_bbone_shape = True` ("Follow B-Bone").
   - Whether Follow B-Bone copies segment scale and ease exactly is UNVERIFIED. Measure it with the §10 vertex-error test.
3. Transfer weights: an LBS fit from B-Bone weights to segment weights is the simplest step.
   - Option 1: duplicate the mesh, set `B.bbone_segments=1`, and use Data Transfer from a version with segments separated.
   - Option 2 (more robust): sample the posed B-Bone deformation over a ROM clip and solve per-vertex non-negative least squares over the K nearest segment bones, capping at 4 influences (2 for mobile). This is a Forge-side numpy job.
4. Bake the action (`bake_action_objects`, `do_scale=True`, `do_bbone=False`), turn off `use_deform` on `B`, and export the segments.
   - Use ARP **custom bone** tagging (`cc`) or a separate non-ARP armature path. Humanoid ARP export puts custom bones under `root.x` (see the arp_limbs report).
- Twist along the chain: let `Copy Transforms` carry it. Mobile with 2 influences shows candy-wrapping beyond about 90° of twist; add segments rather than influences.

**(e) What is automatic vs. needs the director:**
- Detecting B-Bones: automatic (`bone.bbone_segments > 1`).
- Conversion and weight fit: automatic.
- The director approves a side-by-side ROM playback with the error heatmap from §10.

---

## 7. Volume-preserving scale curves

**(a) Why it matters.**
- Squash/stretch reads "alive" only if volume is kept: stretched means thinner, squashed means fatter.
- Uniform scale or Y-only scale looks like rubber-sheet distortion.

**Maths, from Blender's Stretch To constraint** (`constraint.cc`, `stretchto_evaluate`). CONFIRMED:
- `scale_y = dist / rest_length`
- `bulge = (rest_length / dist) ^ volume_variation`, then clamped:
  - `use_bulge_max` / `use_bulge_min` give a hard clamp.
  - `bulge_smooth` blends that hard clamp with a soft clamp `1 ± range·atan(...)/(π/2)`.
- `VOLUME_XZ`: `scale_x = scale_z = sqrt(bulge)`. `VOLUME_X` / `VOLUME_Z` apply `bulge` to one axis. `NO_VOLUME` sets both to 1.
- With `volume_variation = 1`, `x·y·z = 1`: exact volume preservation.
- Forge's curve for any stretch value `s`: `xz = s ** (-0.5 * k)`, with `k` ≈ 1 (realistic) to 1.5 (cartoon). Clamp to `[0.6, 1.6]`.
- Spline IK has `xz_scale_mode = 'VOLUME_PRESERVE'` (mech report).

**(c) Exporting it.**
- The resulting non-uniform scale is fine on **leaf / sibling bulge bones** only (rule 0.4).
- Pattern: for each stretch bone, add a non-chained deform "bulge" bone at mid-segment.
  - Copy Location / Rotation from the segment.
  - A driver sets its X/Z scale to `s**-0.5`.
  - Bake that, then skin the mid-segment loops to it.
- Alternative for Unity Humanoid or for mobile: a **corrective blend shape** `squash` / `stretch` per body part. Bake its weight from `s` into the action as shape-key animation.
  - FBX carries shape-key animation. UE gets morph-target curves; Unity gets blendshape curves (UNVERIFIED for import details).
  - This costs memory, not bones, and survives Humanoid.
- Preserve Volume (dual quaternion) on the Armature modifier must stay **off**. Engines skin with linear blend, and ARP's fix operator disables it for that reason (line 854).

**(d) Texture.**
- Optional "stretch" detail mask: wrinkle or compression normal blend driven by the same `s`.
  - UE: anim curve to material parameter (UNVERIFIED API).
  - Unity: MaterialPropertyBlock from a script.
- AAA only. Skip on mobile.

---

## 8. Whole-body, head and prop squash

- **Whole character squash** (landing / jump anticipation):
  - Scale a dedicated deform bone under `root` (e.g. `squash_root`) about the feet, **uniform or Y-only**, with every child set to `inherit_scale` ALIGNED or flattened by the detector.
  - **Never scale `root` / `c_traj`.** Root-motion extraction and UE capsule / Unity CharacterController do not follow root scale (UNVERIFIED).
- **Props** (springy chests, rubber hammers): one bone per squashable part, leaf scale only. This is safe in all engines.
- **Eyes and pupils:** the "pupil dilate" scale-on-leaf pattern is safe. Eyelid bones under a scaled head need the §1 check.

---

## 9. Skinning, normals and bounds side effects (UNVERIFIED)

- Engine skinning transforms normals and tangents with the bone matrix, not its inverse transpose. Under strong non-uniform scale, shading on squashed parts will differ slightly from Blender's evaluated normals. Check with a lit turntable in the pose test.
- Large stretches exceed the ref-pose bounds (§2 and §3).
- Texel density visibly drops on long stretch frames. If stretch is above 1.5×, author UVs with about 1.2× density on the limb (heuristic).

---

## 10. Validation in Forge's pose test: making stylised deformation look the same everywhere

The existing `pose_test()` (`blender_addon/forge_send/steps.py` line 525) keys rotations only. Proposed additions:

1. **Stylised ROM clip** `FORGE_stylised_test`, auto-keyed on top of the current poses:
   - Limb stretch 1.5× and squash 0.7× through the ARP IK stretch controllers.
   - Spine-master squash.
   - Head squash.
   - A deliberate "shear probe": non-uniform scale on a parent with a 45°-rotated child.
   - Bend/twist controller arcs.
   - One "hide" key at 0.01.
2. **Numeric checks in Blender, no engine needed:**
   - a. Bake the export skeleton (ARP builds it; or bake deform bones with `do_scale=True`).
   - b. For each frame and deform bone, take local TRS exactly as the FBX exporter does (`local_trs` in §1).
   - c. Recompose world matrices three ways:
     - **Blender**: the evaluated `pose_bone.matrix`.
     - **Unity-style**: `world = parent_world @ TRS(local)` with full matrices.
     - **UE-style**: an `FTransform` product.
       ```python
       # UE FTransform A*B (child A in parent B): rot = qB @ qA ; scale = sA * sB (component-wise);
       # trans = qB @ (sB * tA) + tB      -- no shear can arise (UNVERIFIED that this matches UE exactly)
       ```
   - d. Linear-blend skin the low-poly mesh with each set of matrices, using the **exported** weights capped at the engine influence count (UE 8, Unity mobile 2 or 4).
     - Compare with Blender's evaluated mesh, with Preserve Volume off.
   - e. **Fail** if max vertex deviation is above 0.5% of character height, or above 1 cm at UE scale. This threshold is a heuristic.
     - Show a red/green vertex-colour heatmap and name the bones that cause it (shear above 1e-3, or a scale key under the Humanoid flag).
   - f. Humanoid check: if the asset is flagged Unity Humanoid and any humanoid bone has a non-1 scale key, the asset must switch to Generic or to blend shapes.
3. **Round trip:** re-import the exported FBX into a fresh scene, sample the same frames, and compare bone world matrices with the Blender bake.
   - This catches ARP export renames, bones dropped by the Humanoid gate, and lost bend bones.
4. **Optional engine ground truth (AAA tier):**
   - **Unity**: in batchmode, `-executeMethod`, call `AnimationMode.SampleAnimationClip`, then `SkinnedMeshRenderer.BakeMesh`, and write OBJ per test frame.
   - **UE**: `UnrealEditor-Cmd -run=pythonscript` imports the FBX, then poses the mesh and dumps it via the Python editor API. The exact calls are UNVERIFIED. Simpler fallback: a `HighResShot` screenshot per frame.
   - Forge then diffs the vertices against Blender, or builds the contact sheet.
5. **Director view:**
   - One contact sheet per test frame with columns "Blender | UE-sim | Unity-sim" (plus engine shots when available) and the heatmap overlay.
   - A green badge appears when all frames pass.
   - The single click on a failure is "Fix" (soft-link or flatten scale on the named bones), followed by an automatic re-test.

---

## Recommended changes to Forge

- Add an asset flag `stylised_deform`. When it is set:
  - Set `arp_secondary_type='TWIST_BASED'`, multiple twist bones, `arp_keep_bend_bones=True`, `arp_export_twist=True`.
  - Set soft-link on limb stretch bones.
  - Never call `arp.fix_rig_export`.
  - Write a Unity Generic import preset. Keep the UE export as it is.
- Convert custom B-Bone chains to baked segment bones (§6) before export.
- Add volume bulge bones or squash/stretch blend shapes (§7). Use blend shapes for Unity Humanoid and mobile.
- Extend `pose_test()` with the stylised ROM clip and the three-way recomposition check (§10).
- Set bounds extension in UE and `updateWhenOffscreen` / bounds in Unity for stretchy assets.

## Sources

- **Blender 5.3 FBX exporter** (local): `.../addons_core/io_scene_fbx/fbx_utils.py` lines 1694–1704 and 1818–1828; `export_fbx_bin.py` lines 1951 and 2010.
- **Blender main source**, local copies under `/tmp/claude-0/-home-user-Image-to-Game-asset/f1ff8269-309f-546b-b536-494e8126b836/scratchpad/bsrc/`:
  - [constraint.cc](https://github.com/blender/blender/blob/main/source/blender/blenkernel/intern/constraint.cc) (`stretchto_evaluate`)
  - [DNA_armature_types.h](https://github.com/blender/blender/blob/main/source/blender/makesdna/DNA_armature_types.h) (`BONE_INHERIT_SCALE_*`, `BBONE_HANDLE_SCALE_*`)
- **Auto-Rig Pro 3.77.33 mirror:** [jasongzy/auto_rig_pro](https://github.com/jasongzy/auto_rig_pro), local copy at `/tmp/claude-0/-home-user-Image-to-Game-asset/f1ff8269-309f-546b-b536-494e8126b836/scratchpad/arp_src/src/`:
  - `auto_rig_ge.py`: lines 501, 847, 860, 885, 929, 1057, 3398, 3845, 4063–4103, 7285, 7434–7448, 7540–7660, 9429, 11884–11888.
  - `auto_rig.py`: lines 1294, 14371, 49519, 49589.
  - `lib/constraints.py`: line 53.
- **Forge repo:** `/home/user/Image-to-Game-asset/blender_scripts/forge_bpy/finalize.py` (FBX_ENGINE, ARP_ENGINE), `/home/user/Image-to-Game-asset/blender_addon/forge_send/steps.py` (pose_test), `/home/user/Image-to-Game-asset/docs/research/arp_limbs.md`, `/home/user/Image-to-Game-asset/docs/research/mech.md`.
- **UE5 and Unity behaviour:** UNVERIFIED throughout. dev.epicgames.com, docs.unity3d.com and lucky3d.fr are not reachable in this session and the search budget was used up. Allow those hosts and send a follow-up message to verify §2, §3 and the engine side of §10.
