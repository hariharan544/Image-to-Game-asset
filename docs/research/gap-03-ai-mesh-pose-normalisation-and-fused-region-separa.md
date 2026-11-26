# Research gap: AI-mesh pose normalisation and fused-region separation

# Forge gap report: normalising the pose of AI meshes and separating fused regions before retopology

Scope: automated detection and repair on Tripo meshes before Quad Remesher (QR). It covers arms glued to the torso, webbed legs, hair or capes fused to the back and shoulders, tails fused to legs, wings fused to the body, asymmetric or bent rest poses, finding and aligning the symmetry plane, Tripo inputs that give cleaner output, and the director's clicks.

Network note: www.lucky3d.fr (the Auto-Rig Pro docs) and docs.blender.org could not be reached from this session. So Auto-Rig Pro (ARP) operator identifiers and the exact behaviour of Blender's 5.3 apply-pose operators are marked UNVERIFIED unless a search result confirmed them. Engine and Blender API facts given without a citation come from my own knowledge and were not re-fetched here.

---

## 0. Ground rule: keep a separate bake source

- **(a) Why it matters:** Changing the pose and cutting fused regions both change the shape. The bake (normal, AO, colour) must come from a dense mesh that matches the final rest pose and the final separated parts. If you bake from the original fused mesh, the armpit bridge and leg web get baked into the normal and AO maps as dark smears.
- **(b) Topology:** Keep three objects:
  - `SRC_v0_raw`: the original Tripo mesh, read-only, archive only.
  - `SRC_v1_fixed`: the dense mesh after symmetry alignment, separation, capping and pose normalisation. This is the real bake source.
  - `WRK`: a decimated copy of `SRC_v1_fixed` (about 200–500k triangles) that goes to QR.
- **(c) Rig:** The temporary rig deforms `SRC_v1` and every separated dense part with the same Armature modifier and weights. This is a precondition of the whole approach: they must all move identically.
- **(d) Texture:** Tripo's UVs and base-colour texture survive deformation, because moving vertices keeps UV coordinates. So the colour stays valid after posing. Only stretched regions need a texture fix (section 9).
- **(e) Automation:**
  - Apply the armature with `bpy.ops.object.modifier_apply(modifier="Armature")` on each dense object. Tripo meshes have no shape keys, so this works. If shape keys ever exist, use the "Apply Modifiers with Shape Keys" extension ([extensions.blender.org](https://extensions.blender.org/add-ons/apply-modifiers-with-shape-keys/)).
  - Then delete the temporary rig. Build the final ARP rig fresh on the retopologised mesh. Do not try to carry the temporary rig forward.
  - Blender's own "Apply Pose as Rest Pose" only changes the rest pose of the armature. The skinned mesh then has to be re-skinned, according to the Blender manual excerpt in search results ([docs.blender.org apply](https://docs.blender.org/manual/en/5.3/animation/armatures/posing/editing/apply.html), page not fetched). That is why applying the modifier is the correct step here, not applying the pose.
- **(f) Engines:** Nothing engine-specific. Both engines only see the final rest pose.

---

## 1. Finding the symmetry plane and aligning it for QR symmetry

- **(a) Why it matters:** QR symmetry, ARP's mirrored markers, mirrored weights and symmetrical UV layout all assume the X=0 plane is the plane of symmetry. Tripo output is often rotated a few degrees and offset.
- **(b) Topology:** None needed beyond alignment. Optionally run `bpy.ops.mesh.symmetrize` on `WRK` only, so QR gets a perfectly mirrored input. Never symmetrise the bake source, because that destroys asymmetric costume detail.
- **(c) Rig:** ARP's mirroring and X-axis-mirror weight paint need the plane at X=0 with transforms applied.
- **(d) Texture:** Symmetry lets you mirror UV islands with UVPackmaster's similarity and stacking modes. Only do that on a model with a symmetrical texture. Check that the colour on the left and right differ by less than a set threshold.
- **(e) Automation:**
  1. **Before the pose is fixed** (a posed body is geometrically asymmetric), take the midplane from the torso or head only. Keep vertices within the central band of the bounding box (|x − cx| < 0.25 × width), or use the spine and head bones from the skeleton in section 2.
  2. **Starting estimate:** Use PCA of the vertices, weighted by area, to get 3 candidate planes. Score each one by mirror error: reflect the vertices and query a `mathutils.kdtree.KDTree` of the original, taking the median nearest distance. Keep the best.
  3. **Refine with ICP:** Reflect, find correspondences, re-fit the plane from the midpoints of pairs. The normal is the normalised mean of (p − p′) differences. Repeat 10–20 times.
     - PCA alone is sensitive to small geometric changes. ICP converges only from a close starting point. Podolak et al.'s Planar Reflective Symmetry Transform is the robust global alternative. ([Podolak 2006](https://gfx.cs.princeton.edu/pubs/Podolak_2006_APS/symmpaper.pdf), [arXiv 2109.09927](https://arxiv.org/html/2109.09927v2), [Mizoguchi & Kanai PCA+ICP](https://www.ist.hokudai.ac.jp/labo/dgp/publications/unofficialpapers/mizo_asme08%20.pdf))
  4. **Align:** Rotate and translate so the plane becomes world YZ, with the origin on the plane at floor height. Run `transform_apply`. Then local and world coordinates match. That matters because QR mirrors about the world axis for an off-centre object unless symmetry is set to Local. This is only a user report on a forum ([Nomad forum](https://forum.nomadsculpt.com/t/quad-remesher-is-duplicating-objects/16247)). The QR property names in bpy are UNVERIFIED, so read them from `bpy.context.scene` at run time.
  5. **Re-check after pose normalisation (section 4):** Re-run ICP on the whole body. If the 95th-percentile mirror error is under 1% of height, enable QR X-symmetry. Otherwise leave QR symmetry off and flag the asset as "asymmetric costume".
- **(f) Engines:** UE5 expects Z up and X forward. Unity expects Y up. Handle that with the export axis settings, not by rotating the mesh.

```python
import numpy as np, mathutils
def mirror_err(P, n, d, kd):            # plane n.x = d
    R = P - 2*((P@n - d)[:,None])*n
    return np.median([kd.find(mathutils.Vector(r))[2] for r in R[::7]])
```

---

## 2. Temporary skeleton: the basis for every detection step

- **(a) Why it matters:** Bone labels turn "is this a fused region?" into a graph question. When one connected surface patch is split between two body regions that are *not neighbours in the hierarchy* (upper arm vs ribcage, left thigh vs right thigh, tail vs thigh, hair or cape vs scapula), that patch is a fusion.
- **(b) Topology:** None at this stage.
- **(c) Rig: three sources, best first.**
  1. **ARP Smart.**
     - Markers: chin, neck, shoulders, wrists, spine root and ankles, then "Go!".
     - Smart scans the silhouette and bounding-box ratios, according to forum and third-party descriptions ([BlenderArtists](https://blenderartists.org/t/auto-rig-pro-3-69/672834?page=17), [Superhive](https://superhivemarket.com/products/auto-rig-pro)).
     - Marker placement can be scripted, or the director can click the markers.
     - The Python operator IDs (module `auto_rig_smart.py`) were seen only in a traceback, so they are UNVERIFIED. Read them from Blender's Info log after one manual run.
  2. **UniRig** ([GitHub](https://github.com/VAST-AI-Research/UniRig), SIGGRAPH 2025, by the Tripo/VAST team).
     - Predicts skeletons for humans, animals and fantasy characters, which covers tails and wings.
     - The README says the full skinning checkpoints are still pending, and it points to SkinTokens as the successor. So use it for the skeleton only, and run it locally on the 4080.
  3. **Tripo's own rig API.**
     - `rig_type` with `spec` set to mixamo, unreal, unity or another value, plus a rig check that recommends the rig type ([Alibaba Tripo rig docs](https://help.aliyun.com/en/model-studio/tripo-auto-rig-api-reference), [WaveSpeed](https://wavespeed.ai/docs/docs-api/tripo3d/rig)).
     - Returns a skinned GLB that could serve as the temporary rig. Its quality on fused meshes is UNVERIFIED.
- **(d) Texture:** Not applicable.
- **(e) Labels:**
  - For each vertex, compute the distance to each bone segment (a capsule distance), plus a geodesic tie-break so labels do not jump across a gap.
  - Smooth the labels with 2–3 rounds of majority vote on the 1-ring of neighbours.
  - Store the result as an integer attribute `forge_part` (a Geometry Nodes or bmesh int layer) so the director overlay can colour it.
- **(f) Engines:** This skeleton is thrown away after section 4.

---

## 3. Detecting fused regions

### 3.1 Armpit bridge (arm glued to the torso)

- **(a) Why it matters:** The shoulder cannot rotate down or forward without dragging the ribcage. The bake also gets a black AO wedge. The armpit is a close-up area in shoulder-heavy animation (melee, aiming).
- **(b) Topology:**
  - After separation, the arm and torso are still one mesh (the shoulder stays connected). Only the bridge below the shoulder is removed.
  - Retopology then needs proper armpit loops: 2–3 loops around the deltoid and an armpit "pole star". Those were covered in the earlier topology report.
- **(c) Rig:** The ARP standard arm limb. Twist bones (ARP "Twist Bones" count ≥ 1) and a deltoid or armpit corrective help, but only after the bridge is gone.
- **(d) Texture:** New surface on the inner arm and the side of the ribcage. See section 6 for colour fill. Mask it in an `M_repair` vertex-colour layer so the colour step can treat it specially.
- **(e) Automation, three tests that are AND/OR-ed:**
  1. **Label adjacency.** Faces whose vertices carry `upperarm_L` and `spine/chest` labels, *below* the shoulder joint height minus about 0.3 × upper-arm length. Shoulder-cap faces legitimately mix those labels. Faces below that line do not.
  2. **Shape diameter function (SDF), the "thin neck" test.**
     - Cast a ray inward along −normal with `mathutils.bvhtree.BVHTree.ray_cast` and record the thickness.
     - A bridge has a local SDF minimum in the arm-to-torso direction, while the surrounding surface is much thicker. Use a cone of 5–9 rays and take the median.
     - SDF stays stable across poses and is used for part partitioning ([Shapira et al. SDF](https://link.springer.com/doi/10.1007/s00371-007-0197-5), [Neural ShDF](https://arxiv.org/pdf/2306.11737.pdf)).
  3. **Self-proximity for near-contact.**
     - Use `BVHTree.find_nearest_range(co, r)` with r about 1.5% of height. A hit counts when the found point's label is non-adjacent and its normal faces back (n·n′ < −0.5).
     - This finds arms that are *almost* touching but not fused. Those do not need cutting, but they do need pose normalisation (section 4) to open the gap before the bake. Otherwise the cage ray-cast hits the wrong surface.
- **Cut:**
  - Select the bridge faces and dilate by 1 ring. Delete them with `bmesh.ops.delete(bm, geom=faces, context='FACES')`.
  - Cap each new boundary loop with `bmesh.ops.holes_fill(bm, edges=boundary, sides=0)`, or `bmesh.ops.triangle_fill` / `grid_fill` for clean loops.
  - Then fair the cap: 10–30 iterations of `bmesh.ops.smooth_laplacian_vert` on the cap plus 2 rings, with the boundary pinned.
  - Then a local voxel remesh of the part. This is optional and fine on the dense source.
- **(f) Engines:** None beyond normal skinning.

### 3.2 Crotch web (legs webbed together)

- **(a) Why it matters:** Walk and run cycles tear the web. Leg IK pulls the opposite thigh.
- **(b) Topology:** Separate the thighs below the crotch apex. The final retopo needs a crotch diamond or pole and 3+ loops at the hip.
- **(c) Rig:** ARP legs. A hip-flex corrective (shape key or helper bone) is optional.
- **(d) Texture:** Inner-thigh fill. In mobile this is rarely seen. In AAA it shows when the character falls or crouches.
- **(e) Automation:**
  - The crotch apex is the highest point where `thigh_L` and `thigh_R` labels meet near the pelvis bone head.
  - Faces that connect `thigh_L` to `thigh_R` and lie more than 0.1 × thigh length below the apex form the web. Cut and cap as in 3.1.
  - **A false positive that matters:** robes, skirts and long coats are a *legitimate* web.
    - Classify the region as cloth when its SDF is thin (under about 0.5% of height, sheet-like) *and* it spans both legs with its outward normals on both sides.
    - In that case do NOT cut. Mark the asset "skirt" so it gets a skirt bone chain or cloth (ARP extra limbs were covered earlier).
    - The director confirms with one click (section 11).
- **(f) Engines:** UE5 Chaos Cloth or the Unity Cloth component for long robes. Otherwise skirt bones.

### 3.3 Hair or cape fused to the shoulders and back

- **(a) Why it matters:** Hair and capes need their own secondary motion (spring bones or cloth). Fused, they make the torso rigid, and the body underneath is missing.
- **(b) Topology:** Separate into its own object (`HAIR_*`, `CAPE_*`). Keep a thin attachment strip if it is truly attached at the collar or neck. Body surface under it has to be regenerated (section 5).
- **(c) Rig:**
  - Capes: ARP extra limb "Spline IK" or "Bone chain", 3–5 chains across the width. Hair: ARP chains. Both were covered in the earlier report.
  - The attachment strip is weighted 100% to the neck or chest.
- **(d) Texture:** The cape's underside often has no colour from Tripo. Use a two-sided material or generate the inner colour. Mark it in `M_repair`.
- **(e) Automation:**
  - Detect a "sheet" region: SDF below the threshold over a large connected area that sits *outside* the body envelope. The envelope is the union of bone capsules with radii fitted from the median SDF per bone.
  - The attachment line is where the sheet meets thick body labels. Cut along that line, but keep the top 1–2 rings attached for collar capes.
  - Long hair lying on the shoulders: separate fully and keep the scalp attachment.
  - **The cut alone is not enough:** for regenerated body surface, a body template or AI part completion is needed. Procedural fill only works for small holes.
- **(f) Engines:** UE5: AnimDynamics, Kawaii Physics (third-party plugin) or Chaos Cloth. Unity: Magica Cloth or Dynamic Bone (third-party). Mobile: baked animation or 2–3 bone chains.

### 3.4 Tail fused to the legs

- **(a) Why it matters:** A tail that sways or drags must not pull the leg along with it.
- **(b) Topology:** Separate the tail from the leg along the contact strip. The tail root stays attached to the pelvis.
- **(c) Rig:** ARP tail limb, covered earlier.
- **(d) Texture:** Small fills on the back of the leg and the side of the tail.
- **(e) Automation:**
  - Faces labelled tail plus thigh or calf (non-adjacent) form the bridge. Cut and cap.
  - If the tail coils around the leg, the near-contact test (3.1.3) flags it. Before the bake, pose the tail away during pose normalisation (section 4).
- **(f) Engines:** Nothing special.

### 3.5 Wings fused to the body or arms

- **(a) Why it matters:** Wings fold and spread. If the membrane is fused to the ribcage or arm, every flap tears the torso.
- **(b) Topology:** The wing root at the scapula stays connected (a real attachment). Separate everything else that touches the torso, arm or legs. A membrane needs real thickness or a two-sided material.
- **(c) Rig:** ARP has no dedicated wing limb (UNVERIFIED). Typically you build arm-like chains plus membrane "finger" chains with ARP custom bones or extra limbs, and use UniRig's predicted bones as the layout guide.
- **(d) Texture:** Alpha-cut membrane edges are covered in the earlier tattered-edges report.
- **(e) Automation:**
  - Wing labels come from the UniRig skeleton. ARP Smart does not detect wings (UNVERIFIED but likely).
  - Bridge faces are wing faces in contact with chest or arm faces away from the root. Treat them as sheet regions as in 3.3.
  - If the skeleton has no wing bones, the director clicks the wing roots (section 11).
- **(f) Engines:** Nothing special. Two-sided materials cost more on mobile.

### 3.6 Mechanical objects

- Mechanical fusions are pistons welded to the housing, wheels fused to the fender, or turret joined to the hull.
- **Detect** with part segmentation rather than a skeleton: P3-SAM from Hunyuan3D-Part, or SDF and curvature segmentation. Cut along sharp concave creases, using dihedral angle over 60° and concave.
- **Fill** with planar caps, using `bmesh.ops.bisect_plane` plus `holes_fill`. Hard-surface caps are planar, so no fairing is needed.
- **No pose normalisation.** Only set joints to their rest or neutral position, for example a closed landing gear. That position is chosen by the director.

---

## 4. Normalising the pose to a symmetric A-pose

- **(a) Why it matters:**
  - Bent knees, asymmetric arms and a tilted head bake asymmetric creases into the normal map. They break mirroring and make retargeting harder.
  - The A-pose is the convention for UE5 Manny and Quinn and for MetaHuman. That is not a hard requirement, because the IK Retargeter has an editable retarget pose. Unity Humanoid accepts it via "Enforce T-Pose" in Configure Avatar. (Engine facts from my own knowledge, not re-fetched.)
- **(b) Topology:**
  - Normalise *before* retopo, so QR edge flow follows a neutral pose.
  - Target pose:
    - Upper arm about 45° below horizontal.
    - Elbow bent about 10–15° forward, palms facing down and in.
    - Legs straight with knee bend under 5°, feet hip-width, toes forward.
    - Spine and head neutral, eyes level.
  - Rotations over about 40° on dense meshes cause candy-wrapper twisting and volume loss. Flag them, and prefer re-generation (section 10) for very bent poses (crouch, sitting).
- **(c) Rig:**
  - Use the temporary skeleton from section 2.
  - Weights: ARP binding (heat or voxelised) or Blender automatic weights with `bpy.ops.object.parent_set(type='ARMATURE_AUTO')`. Bind on the *already separated* mesh. Otherwise the arm weights bleed into the torso through the bridge.
  - Turn on `use_deform_preserve_volume` (dual quaternion) on the Armature modifier for twist regions.
  - Then a Corrective Smooth modifier with rest source "Original Coordinates" and "Only Smooth" off, limited to a vertex group of the joint regions.
  - Apply both modifiers.
- **(d) Texture:** Joints that straighten (behind the knee, inside the elbow) expose crease areas that Tripo painted dark. Detect regions where face area grew by more than 30% (`area_after / area_before`), write them to `M_repair`, then fix them in section 9.
- **(e) Automation:**
  1. **Symmetric target per bone pair (L/R).** Mirror the right bone's direction across X, then average it with the left bone's to get d̄. Blend d̄ toward the canonical A-pose direction with weight w: 1.0 for arms and legs, 0.5 for the spine.
  2. Pose each bone with `pb.rotation_quaternion = (current_dir.rotation_difference(target_dir)) @ pb.rotation_quaternion` in local space. Process parents first.
  3. Twist: keep roll, and align the palm normal to the canonical one.
  4. Apply the armature on every dense object at once (section 0), then delete the temporary rig.
  5. **Validate:**
     - Self-intersection: test with `BVHTree.overlap(BVHTree)` between parts (arm vs torso). Any overlap means rejecting or reducing the rotation.
     - Volume change per part: under 5%. Use `bmesh.calc_volume()` on the closed parts.
     - Run the symmetry ICP (section 1) again.
  6. **Alternative for difficult poses:** regenerate with pose conditioning. Hunyuan3D-Omni accepts a skeleton condition (51 bones, 6 floats each, with an A-pose bone file in its demos) and generates a mesh in that pose ([arXiv 2509.21245](https://arxiv.org/html/2509.21245v1), [DeepWiki pose demo](https://deepwiki.com/Tencent-Hunyuan/Hunyuan3D-Omni/5.2-pose-control-demo)). PoseMaster is similar ([arXiv 2506.21076](https://arxiv.org/pdf/2506.21076)). After that, the textures have to be regenerated or reprojected.
- **(f) Engines:**
  - UE5: the IK Retargeter takes care of the remaining difference to Manny via the retarget pose.
  - Unity Humanoid: Configure Avatar and Enforce T-Pose. The bind pose stays A, and only the avatar definition is set.

---

## 5. Regenerating hidden surfaces (armpit, under a cape, between legs, behind hair)

- **(a) Why it matters:** Surfaces Tripo never generated become visible the moment the character moves.
- **(b) Topology:** The fill must be a closed, smooth surface that continues the curvature of its surroundings. Its density should match the surrounding dense mesh so the bake is consistent.
- **(c) Rig:** Nothing beyond the normal weights.
- **(d) Texture:** Every fill gets `M_repair = 1`, used for colour fill (section 9).
- **(e) Options, cheapest first:**
  1. **Procedural fill and fair (no AI).** Holes under about 5% of the part's surface: `holes_fill`, Laplacian or "minimal surface" fairing, optional local voxel remesh. Fine for armpits and the crotch.
  2. **Template fill.**
     - Fit a neutral body template to the skeleton: the MPFB / MakeHuman base mesh, or an SMPL-X-like body (check licence; SMPL is not free for commercial use).
     - Shrinkwrap or Surface Deform onto the visible body, then take the template's surface inside the hole region and boolean-union or bridge it in.
     - Good for the back under a cape or a torso hidden by hair. Template fitting quality is UNVERIFIED and should be tested per asset.
  3. **AI part completion.**
     - Hunyuan3D-Part has two stages: P3-SAM segments the mesh, and X-Part generates complete parts. It is built for AI meshes, and the public GitHub release is a "light" version ([HF Hunyuan3D-Part](https://huggingface.co/tencent/Hunyuan3D-Part), [X-Part arXiv 2509.08643](https://arxiv.org/pdf/2509.08643)).
     - HoloPart completes occluded part geometry from incomplete segment patches. Its quality depends on the masks ([arXiv 2504.07943](https://arxiv.org/abs/2504.07943)).
     - Use these for large hidden areas such as the whole back under a cape, or a wing joined to the arm. The output is a new part mesh, which you align (ICP) and blend into the original along a boundary band.
  4. **Regenerating the image.** Re-run Tripo with a fixed reference image (section 10). This is often cheaper than repairing an asset with more than 2 serious fusions.
- **Decision rule:**
  - Hole area under 5% of the part: option 1 automatically.
  - 5–20%: option 2 or 3, and the director approves.
  - Over 20%, or more than 2 major fusions: option 4.
- **(f) Engines:** None.

---

## 6–8. Engine-side and budget notes for these steps

- **Poly budget:** The dense working mesh is unconstrained, because the bake source has no budget. The final budgets come from the earlier retopo report and are not repeated here.
- **Caps on cut regions:** In the low-poly mesh they must not become flat n-gons. QR handles that, because it gets the faired dense surface as input.

---

## 9. Texture repair after cuts, fills and posing

- **(a) Why it matters:** New faces have no UV or colour. Stretched creases look smeared.
- **(b) Topology:** None.
- **(c) Rig:** None.
- **(d) Maps:** Base colour only. Normal and AO are baked anyway from the corrected `SRC_v1`.
- **(e) Automation:**
  1. Fill faces get UVs with a Smart UV Project of the fill only, then UVPackmaster into free space. Alternatively, bake the colour to the final low-poly mesh straight away, which avoids UV work on the dense mesh.
  2. **Colour:**
     - (a) Fast: a selected-to-active colour bake from `SRC_v1` to the low-poly mesh with a large margin and extend fill. Then a texture-space "push-pull" or diffusion fill inside `M_repair` from the neighbouring texels. Mean colour plus noise from the surrounding ring gives a good enough skin, cloth or fur match.
     - (b) AI: region-masked texture regeneration, such as Hunyuan3D-Paint, or Tripo's re-texture with a mask. Mask support is UNVERIFIED.
  3. Stretched areas (area ratio over 1.3) get the same diffusion fill with low strength, or a detail-map tiling overlay.
- **(f) Engines:** UE5 and Unity: no difference.

---

## 10. Inputs to Tripo that give cleaner, separated poses

- **(a) Why it matters:** Prevention is cheaper than repair. Arms fused to the body are the most common failure, and Scenario's comparison shows exactly that case ([Scenario multi-view](https://help.scenario.com/en/articles/use-multi-view-for-better-3d-models)).
- **(e) Rules to apply automatically before upload** (edit the image with an image model when the source art does not comply):
  - Full body, frontal, orthographic-looking, even and diffuse lighting with no baked shadows. Tripo recommends a "T-pose / neutral pose", "A-pose, arms slightly out, symmetrical posture, full body visible" ([Tripo 25 tips](https://www.tripo3d.ai/blog/25-image-to-3d-prompt-tips-for-cleaner-ai-3d-models)).
  - Arms clearly away from the torso and not crossing it. Legs and feet visible, with a gap between them. Remove held items, which become separate assets. Open, empty hands ([Artlist](https://help.artlist.io/hc/en-us/articles/29595196941213), [Scenario dwarf example](https://help.scenario.com/en/articles/use-multi-view-for-better-3d-models)).
  - Cape and long hair: request "cape hanging behind, not touching arms", or generate the character without the cape and the cape separately. That avoids section 3.3 entirely.
  - Tail: "tail extended straight back, not touching legs". Wings: "wings fully spread, membranes away from the body".
  - Use multi-view input (front, side and back). It reduces hidden-surface guessing.
  - Tripo Studio reportedly has a T-pose generation option ([Tripo T-pose blog](https://www.tripo3d.ai/blog/t-pose-vs-a-pose-in-3d-modeling)). No `pose` parameter is documented in the generation API (UNVERIFIED either way).
- **Suggested prompt suffix:**

  `full body, front view, A-pose, arms 45° away from torso, legs slightly apart, open empty hands, symmetrical, neutral expression, eyes open, even diffuse lighting, plain background, hair and cape not touching arms or shoulders`

- **(f) Engines:** None.

---

## 11. The director's minimal click set (visual approval only)

Each step shows a viewport overlay with Accept and Change.

1. **Symmetry plane:** a green plane over the model. Accept, or Flip if the wrong axis was picked. About 1 click.
2. **Skeleton and labels:** colour-coded `forge_part` regions plus bones.
   - Accept.
   - If wrong, place the ARP Smart markers: chin, neck, shoulders, wrists, spine root, ankles, with mirroring on. About 6 clicks.
   - Wings or tail missing: click the root and the tip, 2 clicks each.
3. **Fusions:** red bands for each detected bridge, with a label (armpit, crotch, cape, tail, wing).
   - Click a band to toggle it off (a false positive, such as a skirt).
   - Clicking a crotch band toggles skirt or legs. Typically 0–2 clicks.
4. **Hidden-surface method:** shown only for fills over 5%. Choose Procedural, Template or AI, or Regenerate the image. 1 click per region.
5. **Pose:** a before/after slider of the A-pose with collision areas highlighted. Accept, or reduce the strength from 100% to 50%. 1 click.
6. **Texture repair:** `M_repair` regions shown in magenta, then the filled colour. Accept, or switch to the AI fill. 1 click.

Typical clean asset: about 4 clicks. Badly fused asset: about 15 clicks, or one "Regenerate the image" click, which sends the corrected reference and the prompt from section 10 back to Tripo.

---

## Suggested order of operations (bpy module `forge_normalize.py`)

1. `freeze_source()`
2. `align_symmetry(coarse)`
3. `build_temp_skeleton()`: ARP Smart, then UniRig, then the Tripo rig API as fallbacks
4. `label_parts()`
5. `detect_fusions()`: label adjacency, SDF, BVH proximity, sheet test
6. director gate 1–3
7. `cut_and_cap()`
8. `fill_hidden()`
9. director gate 4
10. `bind_temp()` and `pose_to_A()`
11. `validate()`: overlap, volume, symmetry
12. `apply_and_drop_rig()`
13. `align_symmetry(fine)`
14. director gate 5
15. `mark_repair_regions()`
16. Hand `SRC_v1` and `WRK` on to QR and the bake
17. Texture repair during the colour step (gate 6)

## Still UNVERIFIED and to check locally

- ARP Python operator IDs for Smart and "Apply Pose as Rest". Run each step once by hand and read the Info log.
- Quad Remesher's bpy property names for symmetry.
- Whether Tripo's generation API has a pose or T-pose option.
- Quality of the light X-Part release and of the Tripo rig API on fused meshes.
- Accuracy of template fitting.
- The thresholds given above (1.5% / 5% / 20% / 1.3× / 40°). They are starting values to tune on 10–20 real Tripo assets.

## Sources

- [Hunyuan3D-Part (P3-SAM + X-Part)](https://huggingface.co/tencent/Hunyuan3D-Part)
- [X-Part arXiv 2509.08643](https://arxiv.org/pdf/2509.08643)
- [HoloPart arXiv 2504.07943](https://arxiv.org/abs/2504.07943)
- [Hunyuan3D-Omni arXiv 2509.21245](https://arxiv.org/html/2509.21245v1)
- [Hunyuan3D-Omni pose demo (DeepWiki)](https://deepwiki.com/Tencent-Hunyuan/Hunyuan3D-Omni/5.2-pose-control-demo)
- [PoseMaster arXiv 2506.21076](https://arxiv.org/pdf/2506.21076)
- [UniRig GitHub](https://github.com/VAST-AI-Research/UniRig)
- [Tripo auto-rig API (Alibaba)](https://help.aliyun.com/en/model-studio/tripo-auto-rig-api-reference)
- [Tripo rig API (WaveSpeed)](https://wavespeed.ai/docs/docs-api/tripo3d/rig)
- [Tripo image-to-3D tips](https://www.tripo3d.ai/blog/25-image-to-3d-prompt-tips-for-cleaner-ai-3d-models)
- [Tripo T-pose vs A-pose](https://www.tripo3d.ai/blog/t-pose-vs-a-pose-in-3d-modeling)
- [Scenario multi-view guide](https://help.scenario.com/en/articles/use-multi-view-for-better-3d-models)
- [Artlist pose advice](https://help.artlist.io/hc/en-us/articles/29595196941213)
- [Shape Diameter Function (Shapira et al.)](https://link.springer.com/doi/10.1007/s00371-007-0197-5)
- [Neural ShDF](https://arxiv.org/pdf/2306.11737.pdf)
- [Planar Reflective Symmetry Transform (Podolak 2006)](https://gfx.cs.princeton.edu/pubs/Podolak_2006_APS/symmpaper.pdf)
- [Reflection plane detection arXiv 2109.09927](https://arxiv.org/html/2109.09927v2)
- [Quad Remesher local-symmetry anecdote (Nomad forum)](https://forum.nomadsculpt.com/t/quad-remesher-is-duplicating-objects/16247)
- [ARP Smart forum notes](https://blenderartists.org/t/auto-rig-pro-3-69/672834?page=17)
- [Auto-Rig Pro (Superhive)](https://superhivemarket.com/products/auto-rig-pro)
- [Apply Modifiers with Shape Keys](https://extensions.blender.org/add-ons/apply-modifiers-with-shape-keys/)
- [Blender manual: apply pose](https://docs.blender.org/manual/en/5.3/animation/armatures/posing/editing/apply.html) (seen only in search results; not fetched)

