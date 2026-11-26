# Research: detail-editing

# Adding or changing rig and topology details after the automated pass (Forge, Blender 5.3 + QR + UVPM4 + ARP 3.79)

## How far the sources go
- Three documentation sites were blocked in this session: **lucky3d.fr** (the official Auto-Rig Pro manual), **docs.blender.org** and **superhivemarket.com**. To check the exact Auto-Rig Pro labels, those hosts need to be allowed.
- Every Auto-Rig Pro operator, option or bone name below that is not confirmed by a cited source is marked UNVERIFIED. Your own repo already confirms `arp.append_arp`, `arp.match_to_rig`, `arp.bind_to_rig` and `arp_export_fbx_panel`, plus the Quad Remesher properties `use_materials`, `use_vertex_color`, `autodetect_hard_edges` and `adaptive_size` (see `blender_scripts/forge_bpy/arp_rig.py` and `retopo.py`).
- Blender `bpy` operator names come from the stable API as I know it. They are marked "API" and should be smoke-tested once in 5.3.

## Overall design: one rule
Never edit the final mesh by hand. Every change is stored as an **edit record**, written in bone or landmark space, and replayed by the stage scripts. That makes changes repeatable and keeps earlier approvals valid (see §10). Each feature below is one operator that adds or removes edit records, and then reruns only the affected stages.

---

## 1. Extra edge loops at joints (elbow, knee, wrist, fingers, neck, shoulder, hip)

**(a) Why it matters.** Skinned joints collapse ("candy-wrapper" twist, elbow pinch) unless there are loops on both sides of the joint pivot. This is the main thing that makes a pose test fail.

**(b) Topology.**
- Bending joints need 3 loops: one at the pivot and one on each side, about 1/4 of the limb radius away.
- Shoulder and hip need 4–5 loops, fanned toward the armpit or groin.
- Fingers: AAA uses 3 loops per knuckle, mobile uses 2.
- Twist zones (forearm, upper arm) need evenly spaced loops so twist bones can spread the rotation.
- Rough cost: AAA hero adds about +2–4k tris for all joints; mobile adds about +400–800. Take this out of the stage-4 budget rather than adding to it.

**(c) Rig.** Nothing new is needed. Auto-Rig Pro twist bones (`forearm_twist`, `thigh_twist`; UNVERIFIED names) need the evenly spaced loops. After the loops are added, rebind only that region (§5).

**(d) Texture.** None. Loops stay inside the UV islands. Rerun UVs and bake only if seams moved.

**(e) Automation.**
- **Preferred: guide the retopology instead of adding loops afterwards.**
  - Before running Quad Remesher, paint the high mesh with a "joint ring" material band. The band is the set of faces within ±r of a plane that passes through the joint and is perpendicular to the bone. Then set `scene.qremesher.use_materials = True`.
  - Quad Remesher places edge loops along material borders and the rest of the topology follows them (unofficial FAQ [1]; a forum user compares it to ZBrush "Keep Groups" [2]).
  - Joint positions come from `joints.py`. The density vertex colour you already use (`use_vertex_color`) still applies.
- **Fallback: insert loops after retopology with bmesh.**
  - For each joint, find faces crossing the plane through the bone head with the bone direction as its normal.
  - Collect the **edge ring**: edges roughly parallel to the bone (|dot| > 0.7) whose midpoints lie within ±r.
  - Run `bmesh.ops.subdivide_edgering(bm, edges=ring, cuts=2, interp_mode='SURFACE', smooth=1.0)` (API), then shrink-wrap the new vertices to the high mesh.
  - This runs without a viewport. `mesh.loopcut_slide` needs a viewport context, so avoid it.
- **Director.** No input needed. The pose test (§4) is the approval.

**(f) Engines.** UE5 defaults to linear skinning, and Unity has no dual quaternion skinning by default, so loops (not "preserve volume") must carry the deformation. Mobile: 4 influences, so loops count for more. UNVERIFIED that neither engine offers dual quaternion skinning out of the box in current versions.

---

## 2. Loops around the eyes and mouth (ring topology), including eyelids

**(a) Why it matters.**
- Blinks, squints, speech and close-ups need concentric rings. A Tripo mesh has the eye "painted" into one closed surface, so a blink would pull texture across the eyeball.

**(b) Topology.**
- **Eyelid:**
  - Upper lid: at least 3 rings (AAA uses 5–7). Lower lid: at least 2 (AAA uses 3–5).
  - A **lid-margin loop** gives the lid thickness and turns inward around the eyeball, sealing the socket so no hole shows when the lid closes.
  - The eyeball is a **separate mesh**: a UV sphere with a cornea bulge. The lid mesh must cover the eyeball by about 10–15% at rest.
  - Eyelashes are separate cards.
- **Mouth:**
  - 4–8 rings (mobile uses 3), plus the lip-roll loop into the mouth bag (mouth bag already researched).
  - Nasolabial fold loop and cheek/jaw loops.
- **Budget:**
  - AAA hero head: about 8–15k tris, with around 1/3 of that in the eyes and mouth.
  - Mobile head: about 1.5–3k tris. At least 2 lid rings and 3 mouth rings are non-negotiable even on mobile.

**(c) Rig.**
- **Auto-Rig Pro head limb, "Facial Features":** eyebrows, eyelids, lips, teeth, tongue, chin, skulls.
  - Recent releases support "removing all eyelids (amount set to zero)" and have "auto-eyelid settings per upper/lower eyelids" (release-note snippets via search [3]).
  - Bone names follow the `c_eyelid_top_01.l`, `c_eyelid_bot_01.l`, `c_lips_top.x`, `c_lips_smile.l`, `c_eyebrow_full.l`, `c_jawbone.x`, `c_eye.l` and `c_eye_target.x` pattern (UNVERIFIED).
- **Alternatively or additionally, ARKit shape keys** (`eyeBlinkLeft`, `eyeSquintLeft`, `eyeWideLeft`, …; §6).
- **Eye aim:** a damped-track or IK constraint to `c_eye_target.x`.

**(d) Texture / material.**
- **Eyeball:** separate material.
  - UE5: Substrate/Eye shading model with iris mask, refraction depth and limbus darkening. Unity URP mobile: unlit or lit sphere with a parallax iris.
- **Tear-line strip and eye "occlusion" shell:** AAA only, MetaHuman style (UNVERIFIED as a requirement; MetaHumans ship these meshes).
- **Lid-margin wetness:** a roughness mask.
- **Inner lid / caruncle:** the subsurface scattering (SSS) colour mask.
- **Paint-out:** the eye painted on the skin under the lid must be repainted as skin, otherwise a blink shows the iris on the lid. Do this by baking the base colour with the eye region masked, then inpainting with an image model or a procedural skin fill.

**(e) Automation.**
1. **Detect landmarks.**
   - Render the front view (orthographic) and run a 2D face-landmark model (MediaPipe Face Mesh or a similar 468/478-point model gives eye and lip contours).
   - Raycast the contour points onto the high mesh. This works for humans and many stylised creatures. For non-humanoid creatures, the director clicks two eye corners and two mouth corners once.
2. **Build the guide bands.** From the contour, build geodesic rings at distances d1…dn and paint alternating materials. Quad Remesher then puts loops on those borders (`use_materials`) [1].
3. **Cut the lid opening.**
   - Delete faces inside the eye contour on the low mesh.
   - Add `bmesh.ops.extrude_edge_only`, scale it inward toward the eye centre, and offset it along -normal. This builds the lid margin plus the socket wall.
   - Add a procedural eyeball sphere scaled to the contour's bounding circle.
4. **Fallback when retopology is already done.** Run `bmesh.ops.bevel(geom=contour_edges, offset=…, segments=2, affect='EDGES')` (API) or `bmesh.ops.inset_region` to add concentric loops to an existing ring.
5. **Rig the face.** Turn on the Auto-Rig Pro facial features, place the reference bones from the landmarks, run `match_to_rig`, then bind the head region only (§5).
6. **Blink shapes.** Generate them procedurally:
   - Rotate the lid ring vertices about the eyeball centre with a falloff per ring (ring 0 = 1.0, ring n = 0).
   - Store the result as `eyeBlinkLeft`/`eyeBlinkRight` shape keys.
   - Check that the lid edge stays outside the eyeball (closest-point test against the eyeball mesh, with an offset of at least the lid thickness).

**(f) Engines.**
- UE5: eyelids can be bones or morphs. MetaHuman-style curves (`CTRL_expressions_eyeBlinkL`, UNVERIFIED) or ARKit names map from Live Link Face.
- Unity: blend shapes cost memory per vertex per shape, so on mobile prefer bones for lids and keep at most about 10 shapes (UNVERIFIED budget).

---

## 3. Re-retopologising one region only (partial remesh plus bridge)

**(a) Why it matters.** It fixes one bad area (an ear, a hand, a face) without disturbing approved UVs, weights or bakes elsewhere.

**(b) Topology.** The patch boundary must keep the existing boundary vertex count, or be bridged with a single ring of transition quads. Quads only, no poles on the boundary.

**(c) Rig.** Move weights onto the new patch from the previous version (Data Transfer, `VGROUP_WEIGHTS`, nearest face interpolated). Smooth one ring across the seam.

**(d) Texture.**
- Re-unwrap only the patch faces.
- Pin the other islands: UVPackmaster 4 has a pack-into-existing / locked islands mode (UNVERIFIED option name).
- Rebake only the patch area: bake to a temporary image, then composite it through a UV-space mask of the patch.

**(e) Automation.**
1. **Region selection.** One of three sources:
   - a vertex group from a marker brush (§11);
   - a face set;
   - the faces within radius R of a clicked point, computed with a geodesic BFS.
2. **On the low mesh,** delete the region's faces and record the hole's boundary loop L (count N).
3. **On the high mesh,** cut the matching patch slightly larger (+1 ring). Use a KD-tree proximity from the low region, then `bmesh.ops.delete` the rest.
4. **Remesh the patch** with Quad Remesher at the regional target count (keep `use_materials` if face guides exist). Fall back to QuadriFlow (`object.quadriflow_remesh`).
5. **Join the patch to the body.**
   - Trim the patch back by one ring and get its boundary loop P.
   - Resample P to N vertices along arc length, merging or splitting the nearest vertices.
   - Run `bmesh.ops.bridge_loops(bm, edges=L+P, use_pairs=False)`, then `bmesh.ops.join_triangles`.
   - If N is even and the shape is simple, `bmesh.ops.grid_fill` on L alone is a no-remesh alternative.
6. **Finish.** Shrink-wrap the patch and bridge vertices to the high mesh, run a 2-iteration relax (`bmesh.ops.smooth_vert`), and keep the boundary vertices locked.
7. **Invalidate.** Mark UV/bake/weights as invalid only for the faces in that region (§10).
8. **Director.** One click to select the region; approval is a before/after view.

**(f) Engines.** None. LODs for that part must be regenerated (stage 8).

---

## 4. Corrective shape keys driven by bone angles

**(a) Why it matters.** Loops alone cannot fix volume loss at shoulders, elbows, knees, wrists and the hip/groin. Correctives are the AAA standard (MetaHumans use RBF pose drivers).

**(b) Topology.** Needs the joint loops from §1. One shape per joint per direction (for example `elbow_l_bend90`).

**(c) Rig.**
- **Blender:**
  - A driver on `key_blocks[name].value` with a `ROTATION_DIFF`, or a `TRANSFORMS` variable reading the bone's local Euler or swing angle (Local Space). Map it with a scripted expression such as `clamp((a - 0.2)/(1.4-0.2), 0, 1)`.
  - Standard manual method: right-click → Add Driver, with the forearm's local X rotation in Local Space [4].
  - Blender Studio's Pose Shape Keys add-on creates bone-driven corrective shapes [5]. The bundled "Corrective Shape Keys" extension (Create Duplicate for Editing; Apply Pose as Shape Key) converts a posed sculpt back into rest space [6][7].
- **Auto-Rig Pro:**
  - The forum suggests ARP makes driver creation easy but has no automatic corrective system; correctives are marked after animating [8].
  - Exact ARP button names: UNVERIFIED.

**(d) Texture.** For AAA, optionally add wrinkle maps (an extra normal map blended by the same curve: a UE material parameter or Unity shader property). Mobile: none.

**(e) Automation, with no sculpting by the director.**
1. For each joint, pose it to its extreme (for example elbow at 120°, knee at 130°, shoulder abducted 90°/raised 150°).
2. Build the "ideal" target by adding a **Corrective Smooth** modifier (rest source = bind pose, "Only Smooth" off, a smoothing vertex group limited to the joint region) and evaluating the depsgraph mesh.
   - Do not rely on Apply as Shape Key with Corrective Smooth: an old open bug makes it produce an empty key [9].
   - Instead, give the evaluated positions to Apply Pose as Shape Key, or run your own inverse-skinning solve: for each vertex, solve rest-space delta = inverse(Σ wᵢ·Mᵢ) · (target − skinned). This is exact for linear blend skinning.
3. Add the driver from the bone angle as in (c).
4. Add a QA metric: volume ratio of the joint region posed vs rest (flag below 0.9) and self-intersection count.
- Commercial precedent: JointForge bakes delta-mush corrections into bone-driven shape keys for Unity [10]. Corrective Smooth Baker bakes the effect into weights instead [11]. That second approach is cheaper on mobile and worth offering as the mobile path.

**(f) Engines.**
- **FBX does not carry drivers.**
  - UE5: import as morph targets ("Import Morph Targets" [12]), then add a **Pose Driver** node (RBF; drive output = curves/morph targets) in a Post-Process Anim Blueprint [13][14]. For UE 5.6+ MetaHuman pipelines Epic points to the Pose Editor (per a Fab listing; UNVERIFIED).
  - Unity: no built-in pose driver. Ship a small MonoBehaviour that reads `localRotation` relative to the bind pose and calls `SkinnedMeshRenderer.SetBlendShapeWeight`, exported from the same driver table as JSON. Set "Blend Shape Normals" to Import or Calculate to match Normals [15].
- **Mobile alternative:** bake the corrective weights into animation clips, or skip correctives and use extra helper bones (cheaper).

---

## 5. Automated weight-painting fixes

**(a) Why it matters.** Most "rig looks broken" reports are weight problems: bleed between legs, fingers sharing weights, jagged twist, orphan vertices.

**(b) Topology.** None.

**(c) Rig / operators (API, verify in 5.3).**
- `object.vertex_group_smooth(group_select_mode='BONE_DEFORM', factor=0.5, repeat=2, expand=0)`
- `object.vertex_group_clean(group_select_mode='ALL', limit=0.01, keep_single=True)`. The manual says Clean "will not create completely unreferenced vertices" [16].
- `object.vertex_group_limit_total(limit=8|4)`, which removes the lowest weights first [16].
- `object.vertex_group_normalize_all(lock_active=False)`
- `object.vertex_group_quantize(steps=…)` for mobile. Optional.

**(d) Texture.** None.

**(e) Automation.** A "fix this region" macro:
1. **Region mask:** a vertex group from the marker brush, or automatically the vertices whose posed edge-length strain is above a threshold in the pose test.
2. **Rebind with heat maps, region only.** Duplicate the region plus 2 rings, then run `object.parent_set(type='ARMATURE_AUTO')` on the duplicate.
   - Optionally use only the selected bones: `paint.weight_from_bones(type='AUTOMATIC')` in weight paint with vertex-mask selection. UNVERIFIED that it respects the mask in 5.3; test it.
   - Or rebind with Auto-Rig Pro: `arp.bind_to_rig` with the voxelised engine. ARP has heat-map and voxel bind engines, and your code sets `scene.arp_bind_engine`. A "bind selected vertices only" option is UNVERIFIED.
3. **Copy weights back.** Add a Data Transfer modifier: `VGROUP_WEIGHTS`, vertex mapping `POLYINTERP_NEAREST`, layers `ALL`→`NAME`, and its vertex-group influence = the region mask with a feathered falloff. Then apply it.
4. **Clean up.** Run smooth → clean → limit (8 for UE, 4 for Unity) → normalise.
5. **Symmetry.** Use `object.vertex_group_mirror(use_topology=False)` for left/right symmetric fixes.
6. **Leg/finger separation rule.** Zero the weight of bone B on vertices whose geodesic distance to B's segment is more than k × that of their nearest bone. This stops the classic bleed between legs.
7. **Director.** "Paint here = wrong" marker. Approval is the pose test.

**(f) Engines.** Unity Quality → Skin Weights must match the 4 used at export. UE allows up to 8+ (12 with unlimited bone influences; UNVERIFIED for 5.x).

---

## 6. Morph targets / blendshape sets: ARKit 52 and visemes

**(a) Why it matters.**
- Facial animation, lip sync and Live Link Face capture.
- ARKit names are the de-facto exchange set: 52 coefficients (Apple ARFaceAnchor.BlendShapeLocation [17][18]; Unity mirrors the enum [19]).

**(b) Topology.** Requires the §2 rings, a mouth bag, teeth/tongue separation and eyelids that can close.

**(c) Rig: exact names (Apple ARKit).**

| Group | Shape names |
|---|---|
| Eyes | `eyeBlinkLeft/Right`, `eyeLookDownLeft/Right`, `eyeLookInLeft/Right`, `eyeLookOutLeft/Right`, `eyeLookUpLeft/Right`, `eyeSquintLeft/Right`, `eyeWideLeft/Right` |
| Jaw | `jawForward`, `jawLeft`, `jawRight`, `jawOpen` |
| Mouth | `mouthClose`, `mouthFunnel`, `mouthPucker`, `mouthLeft`, `mouthRight`, `mouthSmileLeft/Right`, `mouthFrownLeft/Right`, `mouthDimpleLeft/Right`, `mouthStretchLeft/Right`, `mouthRollLower`, `mouthRollUpper`, `mouthShrugLower`, `mouthShrugUpper`, `mouthPressLeft/Right`, `mouthLowerDownLeft/Right`, `mouthUpperUpLeft/Right` |
| Brows | `browDownLeft/Right`, `browInnerUp`, `browOuterUpLeft/Right` |
| Cheeks / nose / tongue | `cheekPuff`, `cheekSquintLeft/Right`, `noseSneerLeft/Right`, `tongueOut` |

- **Visemes (Oculus/Meta OVR set, 15):** `sil, PP, FF, TH, DD, kk, CH, SS, nn, RR, aa, E, ih, oh, ou`. Visemes can be built as mixes of ARKit shapes.

**(d) Texture.** AAA: wrinkle-map masks for brow, eye and nasolabial areas driven by the same curves. Mobile: none.

**(e) Automation.**
1. **Bones first.** Build the Auto-Rig Pro face rig (§2), then pose it into each ARKit expression from a pose library and bake each pose to a shape key with `object.modifier_apply_as_shapekey(keep_modifier=True, modifier='Armature')` (API).
   - Only the 52 poses are hand-authored, once, as a library in bone space, and reused for every asset. They scale with the face landmarks.
   - This is the "procedural" path. Stylised or creature faces need per-asset scaling of the poses (factor from the landmark distances).
2. **Transfer from a template head that already has ARKit 52.**
   - Fit the template to the landmarks, then Surface Deform: bind the new head to the template, then for each key set template key = 1 and apply as shape key (keep the modifier).
   - The *target* (template) must be manifold, with no concave faces or doubles. Surface Deform ignores the *bound* mesh's own shape keys [20][21]. That is fine here because the keys live on the target.
   - Data Transfer cannot transfer shape keys. Use it for weights and normals only.
3. **Same topology** (re-versioned mesh with an unchanged vertex order): `object.shape_key_transfer` or "Join as Shapes".
4. **Optional third-party:** Faceit (works next to Auto-Rig Pro but cannot use the ARP face rig for its automatic expressions [22]).
5. **QA.** Per shape, the maximum vertex delta must exceed a minimum (no empty shapes) and there must be no lid-eyeball penetration.

**(f) Engines.**
- UE5:
  - Morph targets are named exactly like the Blender shape keys; enable "Import Morph Targets".
  - Reimporting morphs onto a skeleton that already has them overwrites the existing ones [12].
  - Live Link Face sends ARKit names directly. MetaHuman uses its own control rig with an ARKit mapping asset (UNVERIFIED name).
- Unity:
  - Enable "Import BlendShapes". Blend shape normals need smoothing groups in the FBX, and "Blend Shape Normals" should match Normals [15].
  - Mobile: limit the count (each shape costs vertex-delta memory). Ship the 15 visemes plus blinks and mix ARKit only on AAA.

---

## 7. Adding or removing bones on an existing Auto-Rig Pro rig

**(a) Why it matters.** It covers extra parts the auto rig missed (capes, pouches, antennae, mechanical pistons, jaw straps) and removes bones mobile does not need.

**(b) Topology.** Each new chain needs loops at every new joint (re-run §1 for those bones).

**(c) Rig.**
- **ARP limb.** `arp.add_limb` (UNVERIFIED operator id) for spine, arm, leg, head, ears, tail, breast, spline IK, bendy bones and kilt limbs. Duplicates get a `_dupli_NNN` suffix (UNVERIFIED). This needs `match_to_rig` again.
- **Custom bone.**
  - Add the bone in Edit Mode on the final rig and name it with the `cc_` prefix so the exporter includes it [23].
  - ARP 3.59+ has "buttons to quickly set/unset the selected bones as custom bones for export" [24].
  - One UE forum report says `cc_` bones caused UE5 export issues, with no confirmed fix [25]. Test it.
- **Removal.** Disable the limb in reference mode, or for mobile "Unity" export keep the bones and drop them with a deform-flag filter.
- **Persistence across re-match.** Store custom bones as edit records with their parent and their head/tail as fractions in the parent bone's space, and re-add them after every `match_to_rig`. Re-matching can regenerate the rig (UNVERIFIED whether ARP preserves `cc_` bones across re-match).

**(d) Texture.** None, unless the new part needs its own material slot.

**(e) Automation: "bone chain from A to B", two clicks.**
1. The director clicks A, then B, on the mesh (modal operator, raycast).
2. Build the centreline. Sample the A→B path along the surface geodesic. For each sample, raycast inward along -normal to the far wall and take the midpoint. Smooth the result with a 1D Laplacian.
3. Choose the number of bones: n = clamp(length / (2 × mean radius), 2, 8). Fewer on mobile.
4. Create `cc_<name>_01..n`, parent to the nearest deform bone at A (`nearest_bone` already exists in `arp_rig.py`), and set the roll from the mean surface normal.
5. Optional controls:
   - spline IK (bendy limb) for tentacles and tails;
   - Copy Rotation with influence falloff for secondary motion;
   - Damped Track / Stretch To for mechanical pistons (mechanical basics already researched).
6. Bind the region only (§5 step 2–4, with the bone filter = the new chain).
7. Run the auto pose test (rotate each new bone ±45°).
8. **Remove bone:** click the bone, then merge its weights into the parent (`vertex_group` add-merge, then delete the group and the bone).

**(f) Engines.** UE: new bones need the skeleton asset updated; reimport with the same skeleton adds them (UNVERIFIED for compatible-skeleton cases). Unity Humanoid ignores extra bones, but they still animate as generic transforms. Watch the 75-bone mobile warning.

---

## 8. Sockets / attachment points

**(a) Why it matters.** Weapons, props, VFX spawn points (muzzle, mouth fire), camera anchors, and hit or impact points.

**(b) Topology.** None.

**(c) Rig.**
- Skeletal assets: a leaf bone named `cc_socket_<name>`, non-deforming, zero weights. This works in both engines. Your pipeline already adds `socket_weapon_r`; add the `cc_` prefix if ARP export filters it out.
- UE5 alternative: skeleton or mesh sockets authored in the editor (skeleton sockets live on the skeleton asset; mesh sockets on the mesh only [26]). These can be scripted with Unreal Python (UNVERIFIED API).
- Static props: an empty named `SOCKET_<Mesh>_##`; UE strips the prefix [27].
  - Known pitfalls: sockets are ignored when there is a UCX_ collision in some versions, multi-mesh import needs "Combine Static Meshes", LOD export can drop sockets, and reimport can duplicate sockets.
  - Blender workaround from the forum: empty scale 0.01 (not applied) plus 90° X rotation [27].
- Unity: bones and empties import as Transforms; attach props by parenting under them.

**(d) Texture.** None.

**(e) Automation.**
- The asset-type preset lists the default sockets (hands, back, hip, head, muzzle).
- Place each from the joints: palm centre = the midpoint of the hand bone tail and the middle-finger base, offset by the palm normal.
- The director can drag a marker or click "socket here" on the mesh. The orientation comes from the surface normal plus the parent bone's axis.

**(f) Engines.** See (c). Export a `sockets.json` (name, parent, local transform) so both engines can be rebuilt by script if the FBX socket import fails.

---

## 9. Other details the pipeline should check (scope note)
For each of these, the same edit-record and region-rebind tools apply. They are listed briefly because they belong to other research areas.
- Finger and toe splitting: separate fused digits by cutting along the valley curvature line, then add per-digit loops.
- Tongue, teeth and mouth bag: already researched.
- Nails, claws and horns: rigid; weight them to a single bone.
- Clothing and armour layers: separate meshes with their own weights copied from the body, plus correctives for clipping.
- Twist bones.
- Breath/chest corrective.
- Neck and throat loops.

---

## 10. Versioning so later changes keep earlier approvals

**Store the asset as recipe plus layers, not as a final mesh.**
- `edits.json`: an ordered list of records, for example:
  - `{id, op:"joint_loops", bone:"forearm.l", t:0.5, cuts:2}`
  - `{op:"region_remesh", region:{landmark:"ear.l", radius:0.04}, target:800}`
  - `{op:"add_chain", A:[bone-space coordinates], B:[…], n:4}`
  - `{op:"weight_fix", region, method:"heat"}`
  - `{op:"corrective", bone, angle}`
  - `{op:"socket", …}`
- Every record is anchored in **bone space or landmark space**, never by vertex index, so it replays after retopology.
- Each stage `.blend` (already per stage) stores the hash of the edits it consumed.
- An **approval** = (stage, edit-hash, region-hash) plus a thumbnail. Each region gets a hash of the positions of its own vertices.
- When an edit changes region R, only approvals whose region intersects R are invalidated. Everything else is shown as "still approved".
- Before → after views come from comparing turntable renders between versions.

**Carry data forward instead of recomputing it.**
- Weights: Data Transfer from the previous version (§5).
- Shape keys: Surface Deform from the previous version (§6).
- UVs: Data Transfer UV (`LOOP` data type, `POLYINTERP_NEAREST`) outside the changed region.
- Bakes: composite the new bake through the region UV mask.

Keep the stage-per-process model. The supervisor's action space gets these edit ops as new knobs, so the recorder logs them as training data.

---

## 11. UI patterns for the step-by-step panel (non-modeler director)

1. **"Add detail here" brush.**
   - A modal operator with raycast clicks or a drag stroke writes into a `forge_detail` vertex colour/attribute on the high mesh. The colour intensity is the quad density for Quad Remesher (already supported).
   - Shift+drag = "make it simpler".
   - Shows a live estimate of the triangle cost against the budget.
2. **"Ring here".** Click on a limb, and a ghost loop preview (GPU overlay) appears perpendicular to the nearest bone. The scroll wheel sets 1–3 loops.
3. **"Fix this region"** (lasso or brush). A menu offers: Remesh region (§3) / Rebind weights (§5) / Smooth weights / Add corrective (auto).
4. **"Bone chain A→B".** Two clicks plus a slider for the number of bones, with an instant wiggle preview.
5. **"Socket here".** A click plus a preset dropdown (weapon_r, back, muzzle…).
6. **"Face points".** Shown only when automatic detection has low confidence: click 4 eye corners and 2 mouth corners, with a pictogram showing which point is next.
7. **Pose test strip.**
   - Fixed poses (T-pose, squat, arms up, fist, blink, jawOpen, smile), with an automatic "problem heat-map" overlay (strain, volume loss, intersections).
   - The director clicks the red spot and gets "Fix" suggestions in plain language: "Add loops", "Smooth weights", "Auto corrective".
8. **Every action shows a before/after slider and Approve/Undo.** Undo removes the edit record, not a mesh state.
- Implementation: Blender `WorkSpaceTool` for the brushes, a `gpu` module overlay for previews, and operators that only append edit records and call `run_stage.py` for the affected stages.

---

## Sources
1. BlenderNation, Quad Remesher unofficial FAQ (Use Materials → loops on material borders; Normals Splitting): https://www.blendernation.com/2019/10/18/quad-remesher-auto-retopologizer-for-blender-unofficial-faq/
2. Blender Artists, Quad Remesher thread: https://blenderartists.org/t/quad-remesher-auto-retopologizer/1170913
3. Auto-Rig Pro release notes (eyelid amount 0; auto-eyelid per upper/lower), seen as search snippets of https://superhivemarket.com/products/auto-rig-pro/versions (page not directly fetchable)
4. Packt, Blender 2.5 Character Animation Cookbook, "Using corrective shape keys": https://subscription.packtpub.com/book/game-development/9781849513203/1/ch01lvl1sec11/using-corrective-shape-keys
5. Blender Studio, Pose Shape Keys: https://studio.blender.org/pipeline/addons/pose_shape_keys
6. Blender manual, Corrective Shape Keys add-on: https://docs.blender.org/manual/en/4.1/addons/animation/corrective_shape_keys.html
7. Corrective Shape Keys extension: https://extensions.blender.org/add-ons/corrective-shape-keys/
8. Blender Artists, Auto-Rig Pro thread (corrective discussion): https://blenderartists.org/t/auto-rig-pro-3-62/672834?page=47
9. Blender bug T44663 (Corrective Smooth Apply as Shape Key produces an empty key): https://developer.blender.org/T44663
10. JointForge: https://superhivemarket.com/products/jointforge
11. Corrective Smooth Baker: https://blendermarket.com/products/corrective-smooth-baker
12. UE FBX Morph Target Pipeline: https://dev.epicgames.com/documentation/en-us/unreal-engine/fbx-morph-target-pipeline-in-unreal-engine
13. UE Pose Driver: https://dev.epicgames.com/documentation/en-us/unreal-engine/pose-driver-in-unreal-engine
14. UE 4.27 Pose Driver node (drive curves/morphs): https://docs.unrealengine.com/4.27/AnimatingObjects/SkeletalMeshAnimation/AnimPose/PoseDriverNode/
15. Unity Model import settings (Import BlendShapes, Blend Shape Normals): https://docs.unity3d.com/6000.4/Documentation/Manual/FBXImporter-Model.html
16. Blender manual, Object Clean Up (Limit Total, Clean): https://docs.blender.org/manual/en/4.1/scene_layout/object/editing/cleanup.html
17. Apple, ARFaceAnchor.BlendShapeLocation: https://developer.apple.com/documentation/arkit/arfaceanchor/blendshapelocation
18. 52 coefficients count (GitHub sample): https://github.com/DaoKeLegend/Creating-Face-Based-AR-Experiences
19. Unity ARKitBlendShapeLocation enum: https://docs.unity3d.com/Packages/com.unity.xr.arkit@6.1/api/UnityEngine.XR.ARKit.ARKitBlendShapeLocation.html
20. Blender manual, Surface Deform: https://www.blender.org/manual/en/modeling/modifiers/deform/surface_deform.html
21. Blender issue #93162 (Surface Deform ignores the bound mesh's shape keys): https://projects.blender.org/blender/blender/issues/93162
22. Faceit FAQ (ARP compatibility): https://faceit-doc.readthedocs.io/en/latest/FAQ/
23. Blender Artists, ARP 3.52 thread (`cc_` prefix): https://blenderartists.org/t/auto-rig-pro-3-52/672834?page=39
24. Blender Artists, ARP 3.59 thread (set/unset custom bones buttons): https://blenderartists.org/t/auto-rig-pro-3-59/672834?page=43
25. UE forum, ARP export issues with `cc_` bones: https://forums.unrealengine.com/t/in-desperate-need-of-help-getting-auto-rig-pro-to-export-characters-over-properly-please/1543155
26. UE Skeletal Mesh Sockets: https://dev.epicgames.com/documentation/en-us/unreal-engine/skeletal-mesh-sockets-in-unreal-engine
27. UE FBX Static Mesh Pipeline (`SOCKET_` prefix): https://dev.epicgames.com/documentation/en-us/unreal-engine/fbx-static-mesh-pipeline-in-unreal-engine; forum workaround: https://forums.unrealengine.com/t/unreals-socket-import-for-fbx-files-is-broken-workaround/2303521

**UNVERIFIED items to check first in Blender 5.3 with ARP 3.79.17 (the manual is unreachable from here):**
- the ARP add-limb operator id and limb enum names;
- ARP facial bone names (`c_eyelid_*`, `c_lips_*`);
- an ARP "bind selected vertices only" option;
- whether ARP keeps `cc_` bones across `match_to_rig`;
- whether `paint.weight_from_bones` respects the vertex mask;
- the UVPackmaster 4 locked-islands option name;
- the MetaHuman curve and mapping names;
- mobile blend-shape and bone budgets.
