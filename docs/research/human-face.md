# Research: human-face

# Forge research: the humanoid face (eyes, lids, lashes, brows, nose, ears, lips, cheeks, jaw, face rig, skin) in an automated Tripo → Blender → UE5/Unity URP pipeline

**Access limits during this research:** The official Auto-Rig Pro docs (www.lucky3d.fr) and docs.unity3d.com could not be fetched from this session because those hosts are not on the session's network allowlist. Web search still worked, and I used the snippets it returned. So exact ARP option and bone names below are marked UNVERIFIED. Forge should not hard-code them: it should read the bone list from the ARP rig at runtime (see §0.3). The repo has no existing face, eyelid, blink, ARKit or viseme code (grep of /home/user/Image-to-Game-asset found none), so all of this is new work.

---

## 0. Pipeline changes that every face feature needs

**0.1 Find the face landmarks (the step that makes everything else automatic)**
- Render an orthographic front view of the head. Do it twice: once with the baked colour, once with Workbench matcap and cavity shading.
- Run a 2D face-landmark detector on the renders. MediaPipe Face Landmarker gives 478 points, including iris points 468–477. dlib's 68-point model is the fallback.
- Run the detector in a separate Python process, not inside Blender's bundled Python. That avoids numpy and ABI conflicts. (UNVERIFIED that mediapipe installs cleanly into Blender 5.3's Python.)
- Map each 2D landmark back onto the mesh by ray-casting from the ortho camera: `mathutils.bvhtree.BVHTree.FromObject(...).ray_cast(origin, dir)`.
- Output: inner and outer eye corners, upper and lower lid apex, iris centre and radius, brow arc, nose wings and tip, mouth corners, upper and lower lip line, chin, jaw angle, ear root.
- If confidence is low (stylised, anime, creature, mask, beard), fall back to **one director click per landmark group** on the front render. Minimum set: eye centre ×2 and mouth corner ×2, then drag-handles on the proposed aperture curves.
- Extra cue: AI meshes often paint an iris onto a bulge. `cv2.HoughCircles` on the colour render finds it and gives eye centre and iris radius directly.

**0.2 Cut the openings before retopology**
- Cut the eye apertures (and the mouth, which was researched separately) on the dense mesh first, then run Quad Remesher.
- Boundary edges make QR produce rings that run parallel to the hole. That is the concentric eyelid and lip loop topology faces need. This is a strong heuristic, UNVERIFIED for QR specifically.
- Combine it with the existing detail-map density guide (commit d999cfa already adds density around eyes and mouth) and with **QR's X-symmetry**. Symmetric topology is required so Left shapes can be mirrored to Right (`bpy.ops.object.shape_key_mirror(use_topology=True)`).

**0.3 Do not hard-code ARP bone names**
- After `arp.match_to_rig`, list the bone names and classify them by pattern (`eyelid_top`, `eyelid_bot`, `eye`, `eye_offset`, `jaw`, `lips`, `eyebrow`, `tong`, `teeth`, `cheek`, `nose`, `chin`).
- Names often seen in ARP rigs (UNVERIFIED for 3.79.17): `c_eye.l`, `c_eye_offset.l`, `c_eye_target.x`, `c_eyelid_top.l`, `c_eyelid_bot.l`, `c_eyebrow_full.l`, `c_lips_top.x`, `c_lips_smile.l`, `c_jawbone.x`, `c_tong_01.x`, `c_teeth_top.x`, `c_teeth_bot.x`, `c_nose_01.x`, `c_chin_01.x`, `c_cheek_smile.l`.
- Deform bones exported for UE/Unity are usually the same names without the `c_` prefix. The ARP changelog mentions remap presets moving to names "without the c_ prefix" ([ARP versions](https://superhivemarket.com/products/auto-rig-pro/versions)).
- The same changelog confirms recent ARP versions added **auto-eyelid (eyelid-follow) settings per upper and lower lid**, support for **removing all eyelids**, and nose root/tip bones.

**0.4 One shared "attachment follower" helper (it solves lashes, brows, tear line, occlusion and caruncle at once)**
1. Copy skin weights: Data Transfer modifier from the head (`use_vert_data`, `data_types_verts={'VGROUP_WEIGHTS'}`, nearest face interpolated).
2. Make the attachment follow every head shape key: Surface Deform bound to the head; for each head shape key, set value 1, then `bpy.ops.object.modifier_apply_as_shapekey(keep_modifier=True, modifier="SurfaceDeform")` and rename the result to the same name.
3. Remove the Surface Deform modifier.

Modifiers do not export to engines, so everything must end up as weights plus shape keys ([UE forum on modifiers not carrying over](https://forums.unrealengine.com/t/face-rigging-question-blender-to-unreal/2686598)).

**0.5 Visual checks for the director to approve, each rendered automatically**
1. Front and three-quarter view with the aperture curves overlaid (before cutting).
2. Blink turntable.
3. Eyes looking left, right, up and down, with the lids following.
4. ARKit-52 contact sheet (52 thumbnails).
5. Viseme strip of 15.
6. Close-up eye beauty shot.

Automatic gates to run before showing anything:
- Lid–eyeball intersection at blink 0, 0.25, 0.5, 0.75 and 1.0 (BVH overlap).
- The eyeball must be fully hidden at blink = 1 (rays from the camera through the aperture must hit the lid).
- No sclera gap at the corners in neutral.
- Lashes must not cross the eyeball surface.

---

## 1. Eyeballs: separate spheres with cornea, iris and pupil

**(a) Why it matters.** Eyes are where players look first. Eye rotation (look-at, saccades) is the cheapest way to make a character feel alive. A painted eye on a closed surface cannot rotate, blink or take a look-at.

**(b) Topology**
- Each eye is a separate mesh. Use a UV sphere with poles on the front–back axis, so the iris sits in clean circular rings.
- Two-mesh layout (AAA):
  - inner eyeball: sclera plus a concave or flat iris disc, slightly recessed;
  - outer cornea and sclera shell: a sphere with a bulged cornea cap.
- One-mesh layout (mobile): a single sphere, with parallax doing the job of the cornea.
- Human reference sizes (anatomy textbook averages, approximate): eyeball diameter ≈ 24 mm, cornea radius of curvature ≈ 7.8 mm, visible iris diameter ≈ 11.5–12 mm.
- Size the eyeball from the landmarks: r ≈ 0.19 × inter-pupil distance (human IPD ≈ 63 mm), or r ≈ 0.4 × aperture width. Stylised characters: fit the sphere to the aperture curve instead.
- Budget per eye (practitioner heuristic, UNVERIFIED): AAA 500–1,500 tris (plus a 300–800 tri cornea shell); mobile 80–200 tris.

**(c) Rig**
- One bone per eye, pivoting at the sphere centre (ARP eye bones with an eye target), weight 1.0, nothing else.
- Engine-side look-at:
  - UE: AnimBP Look At / Control Rig aim on the eye bones.
  - Unity: Animation Rigging **Multi-Aim Constraint**.
- Engine-side auto-blink and saccades: a small script or AnimBP drives the `eyeBlinkLeft` / `eyeBlinkRight` curves.

**(d) Texture and material**
- UV: planar front projection with the iris centred at UV (0.5, 0.5). That lets one parametric material serve every character, with parameters IrisRadius, PupilScale (dilation), LimbusWidth/Darkness, IrisColour, ScleraTint and VeinAmount.
- Maps: sclera albedo (vein noise, pinkish corners), iris albedo (radial fibres), iris height (for parallax/refraction), and optionally a normal map.
- Iris colour: sample the source image inside the MediaPipe iris landmarks.
- Wetness: cornea roughness ≈ 0.02–0.08 with a strong specular highlight (catchlight). The sclera is slightly rougher.
- Fantasy variants are material parameters, not new meshes: slit or goat pupils (pupil shape mask), an emissive iris mask for glowing eyes, solid-black eyes.

**(e) Automation in Blender**
1. Create the sphere at the landmark eye centre. Push it back along −view by about 0.35·r–0.5·r so the cornea apex sits about 1 mm behind the lid surface. Then refine: binary-search the depth until the sphere stays inside the lid shell and the aperture shows 90–100 % iris height.
2. Build the iris and limbus procedurally in Blender (polar coordinates + noise) and bake it to 1024² (AAA) or 256² (mobile).
3. Parent to the eye bone, set the vertex group to 1.0, and name the objects `Eye_L` / `Eye_R`.

All of this is procedural. The director only needs to step in if the auto-fit size looks wrong.

**(f) Engines**
- **UE5:**
  - The *Eye* shading model has inputs Iris Mask and Iris Distance (plus AO and Pixel Depth Offset).
  - Epic warns it has "very strong dependencies between the shader code, the Material, the shape of the geometry, and its UV layout" and recommends reusing the Digital Humans / MetaHuman eye geometry ([UE shading models](https://dev.epicgames.com/documentation/en-us/unreal-engine/shading-models-in-unreal-engine)).
  - Substrate has an Eye BSDF with IrisMask, IrisNormal, IrisPlaneNormal and CorneaNormal ([Substrate Eye BSDF API](https://dev.epicgames.com/documentation/unreal-engine/API/Runtime/Engine/UMaterialExpressionSubstrateEyeB-)).
  - Recommendation: either match the MetaHuman eye mesh and UV convention exactly and use the Eye model, or use the two-mesh approach (Default Lit eyeball plus a translucent or thin-translucent cornea shell). The second is more robust for procedural eyes.
- **Unity:**
  - HDRP has an Eye shader and Eye Master Stack (cornea refraction, caustics, pupil dilation, limbal ring, SSS). It is HDRP-only, depends on the sample eye mesh, and the Sclera Iris Blend node is not supported in URP ([HDRP eye shader](https://docs.unity3d.com/Packages/com.unity.render-pipelines.high-definition@15.0/manual/eye-shader.html), [Sclera Iris Blend node](https://docs.unity3d.com/Packages/com.unity.shadergraph@13.1/manual/Sclera-Iris-Blend-Node.html)).
  - For URP mobile, build a custom Shader Graph: Parallax Mapping on the iris using the iris height map, a fake refraction offset, a fixed matcap or sphere specular, and limbus darkening. One draw per eye.

---

## 2. Eye wetness, tear line, caruncle and eye occlusion (the parts most often missed)

**(a) Why it matters.** Without these, eyes look "pasted on". There is a hard white edge where the lid meets the eyeball, no contact shadow and no wet meniscus. MetaHuman ships all three: eyeshell, lacrimal fluid (tear line) and eye occlusion ([UE forum: MetaHuman materials and slots](https://forums.unrealengine.com/t/ue5-6-preview-metahuman-creator-assembled-metahuman-has-wrong-materials-assigned/2532947)).

**(b) Topology**
- **Tear line:** a thin strip (about 0.3–1 mm wide, 1–2 quads across) running along the lower and upper lid margin where the lid touches the eyeball, plus a small wedge at the inner corner.
- **Caruncle (lacrimal caruncle):** a small pink fleshy lump in the inner corner. Model it as 2–3 extra loops on the head mesh, or as a small separate wedge.
- **Eye occlusion:** a shell slightly in front of the eyeball covering only the aperture, with the vertex ring snapped to the lid margin.
- Budgets (heuristic): AAA 100–300 tris each per eye; mobile: skip the meshes and bake the effect (see (f)).

**(c) Rig.** Use the attachment follower (§0.4): lid weights plus every lid shape key. They must follow blink, squint and wide.

**(d) Material**
- Tear line: translucent or masked, almost no albedo, very low roughness, gradient opacity, thin-surface refraction.
- Occlusion: translucent multiply (darken), strongest under the upper lid and at the corners, plus a soft blur gradient ([Reallusion eye-occlusion shader description](https://manual.reallusion.com/Character-Creator-5/Content/ENU/5.0/15_Digital_Human_Shader/Eyes/Digital-Human-Eye-Occlusion-Shader.htm), [Reallusion tear-line shader](https://manual.reallusion.com/Character-Creator-5/Content/ENU/5.0/15_Digital_Human_Shader/Eyes/Digital-Human-Tearline-Shader.htm)).
- Caruncle: skin material with a pink tint mask and low roughness (wet).

**(e) Automation.** Everything here is fully procedural.
- Generate the tear line and occlusion with bmesh from the **lid-margin edge loop**, which comes from the aperture cut (§3).
- Tear line: duplicate the loop, offset it by r + 0.1 mm on the eyeball sphere, and bridge.
- Occlusion: project the loop onto a sphere of radius r + 0.3–0.5 mm and fill it with a grid-fill cap.
- Caruncle: insert a small wedge at the inner-corner landmark.

**(f) Engines**
- UE:
  - Separate material slots. Known pitfalls: lacrimal-fluid glow with Lumen GI plus a skylight (lowering opacity fixed it), and slot mix-ups at LOD3/4 ([forum](https://forums.unrealengine.com/t/lumen-gi-skylight-glowing-lacrimal-fluid/239224), [forum](https://forums.unrealengine.com/t/missing-eye-on-lod3/258052)).
  - Drop these meshes at lower LODs.
- Unity URP mobile: do not ship these meshes. Bake the occlusion into the sclera albedo/AO (upper-lid darkening) and fake wetness with a higher specular on the sclera edge.

---

## 3. Eyelids: upper and lower, blink, loops, follow-eye

**(a) Why it matters.** Blinks happen every few seconds on every visible character. Lids must slide over the eyeball and never intersect it. They must also *follow the eye* (upper lid rises when looking up, drops when looking down), or the gaze reads as dead or wrong.

**(b) Topology**
- Concentric loops around the aperture: AAA 6–8 loops with 24–32 verts on the lid margin; mobile 3–4 loops with 12–16 verts (heuristic, UNVERIFIED).
- **Lid margin thickness:** a 1–2 face strip that turns *inward* (about 1.5–2 mm) and then wraps back over the eyeball as a hidden pocket. That way the closed lids meet edge-to-edge, and no socket hole shows when the eye rotates.
- **Upper and lower margins need matching vertex counts** with one shared corner vertex each side, so a blink can close them seam-to-seam.
- One **crease loop** (supratarsal fold) on the upper lid, and one loop below the lower lid (lid–cheek junction).

**(c) Rig.** Both approaches are valid, and a hybrid is best.
- **Bones (ARP):** eyelid top and bottom controllers plus several lid tweak bones, pivoting at the eye centre, so a lid rotation slides over the sphere. ARP has per-upper/lower-lid auto-eyelid (follow) settings ([ARP versions](https://superhivemarket.com/products/auto-rig-pro/versions)).
- **Shape keys:** `eyeBlinkLeft/Right`, `eyeSquintLeft/Right`, `eyeWideLeft/Right` (ARKit), plus the half-blink correctives `eyeBlink_50_L` (Forge's own naming).
  - A linear blendshape blink cuts through the eyeball halfway. The cures are an in-between or corrective shape, or spherical bone rotation ([BA thread on non-linear eyelid shape keys](https://blenderartists.org/t/found-a-facial-rig-solution-in-blender-eyelids-blink-with-non-linear-shape-keys/1369811)).
- **Eyelid follow at runtime (important):** Blender constraints (ARP follow) are not exported. When the engine drives the eyes with look-at, the lids will not follow unless the engine does it:
  - UE: AnimBP "Transform (Modify) Bone" / Control Rig. Copy about 30–50 % of eye pitch to the upper lid bones and about 20–30 % to the lower, or drive the corrective curves `eyeLookUpLeft`, etc.
  - Unity: Animation Rigging **Multi-Rotation Constraint** (eye → lid, weight 0.3–0.5) or a script that sets blendshape weights.

**(d) Texture**
- Lid margin: slightly pink and wet (lower roughness).
- Inner pocket: dark red/black, so any leak looks like shadow.
- Lash line: dark band in the albedo (needed on mobile even when lash cards exist).
- Cavity and AO in the crease.

**(e) Automation for an AI mesh with sealed or painted eyes.** This is the core recipe.
1. **Classify the eye state** from a depth profile through the eye centre plus curvature:
   - painted-open on a bulge;
   - sculpted closed (lash line ridge, convex lid);
   - real cavity (rare).
2. **Aperture curve:** a closed spline through the inner corner, upper apex and outer corner (upper arc) and the lower apex (lower arc), from landmarks. For closed-eye inputs, the aperture height comes from the human ratio (opening height ≈ 0.33–0.4 × width) or from the source image if it shows open eyes. The director approves the overlay.
3. **Cut (dense mesh, before QR):** knife-project or boolean the curve. Delete faces inside it. Snap the boundary onto a sphere of radius r + 0.3 mm. Extrude the boundary inward 1.5–2 mm (margin), then extrude again and shrinkwrap onto r + 0.4 mm going backwards (the pocket).
4. **QR retopology** with symmetry. Verify the loop count around the aperture (walk edge rings from the boundary with bmesh). If it is too low, raise the local density in the detail map and rerun.
5. **Blink shape key, computed (no sculpting):** for each upper-lid vertex within N rings of the margin, convert it to spherical coordinates around the eye centre. Rotate it about the eye's local X axis by θ·falloff(ring), where θ closes the upper margin down to the meeting line (about 70 % of the way to the lower margin). Rotate the lower lid up by the remaining amount. Then clamp to radius ≥ r + 0.3 mm. Store the result as `eyeBlinkLeft`. Repeat for squint (partial, with the cheek raised) and wide (upper lid rotated up, about −10°). Mirror via topology.
   - Generating a 50 % in-between the same way stops the linear-blend cut-through. Use the corrective method in Blender, then bake.
6. **ARP lid bones:** after `match_to_rig`, set the lid bone pivots to the eyeball centre.
7. **Texture fix-up:** the baked colour still contains the painted eye or closed lid.
   - Rasterise a UV mask of the faces within 2 rings of the aperture.
   - Inpaint them: median skin colour plus noise, or OpenCV Telea; an AI inpaint is optional.
   - Paint the margin pink and the pocket dark.
   - **Re-bake AO after inserting the eyeballs.** AO baked from the sealed original is wrong around the eyes.
   - For closed-eye sources, the original closed-lid texture is a good reference for the blink-state upper lid.

**(f) Engines**
- Morph targets: UE "Import Morph Targets"; Unity "Import BlendShapes", with Blend Shape Normals set to *Calculate* to avoid lighting seams during blinks.
- Mobile: bone-driven blink avoids morph cost. Keep the blink morph only if it is not already in the viseme set.

---

## 4. Eyelashes and eyebrows (cards with alpha)

**(a) Why they matter.** Without lashes the face reads as unfinished, and they frame the eye at close-up. Brows carry most of the emotion (surprise, anger).

**(b) Topology**
- **Lashes:**
  - AAA: 2–3 layered card strips per upper lid, 1 per lower lid, 8–20 segments, curled. About 1–3k tris for both eyes (heuristic).
  - Mobile: one strip per upper lid (about 30–60 tris) or texture only.
- **Brows:**
  - AAA: hair cards (a groom converted to cards; Forge's hair-card research applies), about 100–400 cards.
  - Mobile: painted into the albedo, optionally with a slight sculpted ridge.

**(c) Rig.** Attachment follower (§0.4): lash weights come from the nearest lid margin vertices, and lashes must receive the blink, squint and wide shape keys. Brows follow `browInnerUp`, `browDownLeft/Right` and `browOuterUpLeft/Right`, or ARP eyebrow bones. Note: one ARP user reports eyebrow bones moving the whole forehead, so check the weights ([ARP ratings](https://superhivemarket.com/products/auto-rig-pro/ratings?page=3)).

**(d) Texture**
- Alpha atlas with lash or brow strand clumps, a root-to-tip colour gradient, and a depth/ID map for per-card variation. Use alpha test, not blend.
- Brow tint mask in the skin texture as a fallback.

**(e) Automation**
- **Lashes, fully procedural:**
  1. Take the lid-margin edge loop (front edge).
  2. Extrude cards along normal and up, with a curl curve (bmesh or GN curve-to-mesh), and taper at the corners.
  3. Generate the atlas procedurally: draw tapered curves in numpy/PIL or GN and render.
- **Brows:**
  1. Brow arc from landmarks (MediaPipe brow points), or detect it as dark pixels in the albedo above the eye.
  2. Scatter curves over the brow region with growth direction rules (medial strands point up, lateral strands sweep outward).
  3. Convert to cards and transfer.
  4. Inpaint the painted brow lightly, so card and paint don't double up.

The director only approves density and colour.

**(f) Engines**
- UE: Masked material with dithered opacity (TSR/TAA) or the Hair shading model on cards, two-sided. Turn off Cast Shadow on lashes for performance.
- Unity URP: Alpha Clip with two-sided rendering. On mobile tile-based GPUs, alpha-test overdraw is expensive, so keep at most one lash strip per eye.

---

## 5. Nose and nostrils

**(a)** Nostrils show in up-shots and close-ups. A flat, shallow dent reads as a mask. Nostril flare and sneer add emotion (disgust, anger, effort).

**(b) Topology**
- A loop around each nostril opening, plus the ala (nose-wing) crease loop.
- The **nasolabial loop** from the nose wing down past the mouth corner is required for smiles (shared with §7).
- A short internal nostril tube, 1–2 loops deep, capped.
- Mobile: no tube, just a dent plus dark texture.

**(c) Rig**
- `noseSneerLeft/Right` (ARKit), plus an optional nostril flare shape.
- ARP has nose bones (root and tip are mentioned in the changelog); nose tip bones are mostly for stylised characters.

**(d) Texture**
- Darkened nostril interior (AO plus vertex colour).
- High SSS and a red tint at the nose tip and wings in the thickness/SSS mask.
- Roughness: oilier at the nose tip.

**(e) Automation**
- Nostril landmarks (MediaPipe nose points) plus a concave-curvature check.
- If depth < threshold, cut a small ellipse and extrude 3–5 mm inward with taper, before QR.
- Vertex-paint the inside black for the bake.

All procedural.

**(f) Engines:** no special notes. The nostril interior should not cast shadows; drop the tube at mobile LODs.

---

## 6. Ears

**(a)** Ears are visible from side and back cameras. They are the main place where SSS shows (backlit red rim). Fantasy ears (elf or animal) may be animated; ARP extra limbs are covered in the separate research.

**(b) Topology**
- Simplified helix, antihelix, concha and tragus. A shallow ear-canal plug with no tunnel.
- Separate the ear from hair: AI meshes often fuse hair into the back of the ear.
- Budget (heuristic): AAA 600–1,500 tris per ear; mobile 100–300.

**(c) Rig.** Human: none, ears are fully weighted to the head. Elf or animal: a 2–3 bone chain (ARP ears limb, already researched).

**(d) Texture.** This is where the **thickness map** matters most: bake inverted AO with flipped normals, from the dense mesh. Strong SSS, red tint.

**(e) Automation**
- Ear-root landmarks: side render plus MediaPipe failure fallback, or the existing appendage finder (commit 5b79a2d), which already detects ears.
- Check that the hair/ear separation is clean.
- The thickness bake is procedural.

**(f) Engines:** UE uses the thickness/opacity input with Subsurface Profile; URP uses the thickness map in a custom wrap-SSS term.

---

## 7. Lips, mouth corners, cheeks, jaw

The mouth interior (teeth, tongue, mouth bag) was researched separately; this section is about the outer mouth.

**(a)** Dialogue, smiles and face capture all depend on this region. It is the most-watched moving part of a speaking face.

**(b) Topology**
- Concentric **orbicularis loops**: AAA 6–8 loops with 32–40 verts around the lip line; mobile 3–4 loops with 16–20 verts (heuristic).
- A dedicated **vermilion-border loop**: a crisp lip-colour edge that also lets the lips roll.
- A **lip-seam loop** where upper and lower lip meet, cut open for the mouth bag.
- **Mouth corners:** a clean pole-free corner with 2–3 loops turning, so `mouthSmile` and `mouthStretch` don't pinch.
- The **nasolabial fold loop** and a cheek loop running toward the eye (the cheek raise in a smile comes from these).
- **Jaw line:** loops along the jaw border so `jawOpen` deforms only below it.

**(c) Rig**
- **Jaw:** a jaw bone pivoting at about the ear/condyle position (ARP jaw controller), with a weight gradient from chin to cheek.
- **Lips:** ARP lip bones (top, bottom, corners, plus a lips-amount option; "sticky lips" exists according to third-party notes, UNVERIFIED).
- **Cheeks:** `cheekPuff`, `cheekSquintLeft/Right`; ARP cheek bones (UNVERIFIED names).
- ARKit mouth set (23 shapes):

  | Group | Shapes |
  |---|---|
  | Whole mouth | `mouthClose`, `mouthFunnel`, `mouthPucker`, `mouthLeft`, `mouthRight` |
  | Corners (each L/R) | `mouthSmile`, `mouthFrown`, `mouthDimple`, `mouthStretch` |
  | Roll and shrug | `mouthRollLower`, `mouthRollUpper`, `mouthShrugLower`, `mouthShrugUpper` |
  | Press and lift (each L/R) | `mouthPress`, `mouthLowerDown`, `mouthUpperUp` |

  Plus jaw: `jawOpen`, `jawForward`, `jawLeft`, `jawRight`.
- `mouthClose` is meant to be used *together with* `jawOpen` (lips closed with the jaw open). Author it as a corrective on top of `jawOpen`.

**(d) Texture**
- Lip tint mask (RGBA tint-mask channel), lower lip roughness (wet), and a lip-line detail normal.
- Cheek redness mask. Stubble or beard mask (male).

**(e) Automation**
- Mouth corners and lip lines from landmarks. Cut the seam before QR (mouth research).
- Jaw pivot = (ear landmark + mouth corner) heuristic, placed at about the tragus height. Director drag-fix if needed.
- Shapes come from the face-rig generation (§8).

**(f) Engines:** see §8.

---

## 8. Face-rig approaches and expression sets

**8.1 The options**

| Approach | Pros | Cons | Use for |
|---|---|---|---|
| Bone-based (ARP facial) | Cheap, works on mobile, one rig for body and face | Coarser lips and cheeks; face capture needs a pose mapping | Mobile, stylised, creatures |
| Blendshapes (ARKit 52) | Industry standard for face capture: iPhone ARKit / Live Link Face, Unity Live Capture, NVIDIA Audio2Face, Meta Movement SDK | Memory per shape; all 52 must be made | AAA dialogue and cinematics |
| **Hybrid (recommended)** | Bones for eyes, jaw, tongue and lid pivots; shape keys for lips, brows, cheeks, nose and correctives | Two systems to maintain | Default for Forge humanoids |

Faceit's FAQ says it works alongside ARP but cannot use ARP's face rig for its automatic expressions ([Faceit FAQ](https://faceit-doc.readthedocs.io/en/latest/FAQ/)). ARP facial bones can drive lids instead of shape keys ([80.lv ARP stylised face](https://80.lv/articles/stylized-3d-facial-rig-made-in-blender-with-auto-rig-pro)).

**8.2 The ARKit 52 names** (Apple `ARFaceAnchor.BlendShapeLocation`; Unity mirrors them in PascalCase as `ARKitBlendShapeLocation`. Sources: [Apple](https://developer.apple.com/documentation/arkit/arfaceanchor/blendshapelocation), [Unity](https://docs.unity3d.com/Packages/com.unity.xr.arkit@6.1/api/UnityEngine.XR.ARKit.ARKitBlendShapeLocation.html). The full list below is from memory, cross-checked against the partial lists in search results; count = 52.)

| Region | Count | Shapes |
|---|---|---|
| Eyes | 14 | `eyeBlink`, `eyeLookDown`, `eyeLookIn`, `eyeLookOut`, `eyeLookUp`, `eyeSquint`, `eyeWide` — each Left/Right |
| Jaw | 4 | `jawForward`, `jawLeft`, `jawRight`, `jawOpen` |
| Mouth | 23 | listed in §7(c) |
| Brows | 5 | `browDownLeft`, `browDownRight`, `browInnerUp`, `browOuterUpLeft`, `browOuterUpRight` |
| Cheeks | 3 | `cheekPuff`, `cheekSquintLeft`, `cheekSquintRight` |
| Nose | 2 | `noseSneerLeft`, `noseSneerRight` |
| Tongue | 1 | `tongueOut` |

Notes:
- Name shape keys exactly in Apple camelCase and map case-insensitively in the engines.
- Which side "Left" means (character's left vs viewer's left) has to be checked with a test capture. UNVERIFIED.

**8.3 Visemes for dialogue.** Meta/Oculus 15: `sil, PP, FF, TH, DD, kk, CH, SS, nn, RR, aa, E, ih, oh, ou` ([Meta viseme reference](https://developers.meta.com/horizon/documentation/unity/audio-ovrlipsync-viseme-reference/)). The OVRLipSync plugin is end-of-life; the Meta Movement SDK delivers the same 15 visemes via the `XR_META_face_tracking_visemes` OpenXR extension.
- Forge can generate visemes as **mixes of ARKit shapes**. For example, PP = mouthClose + mouthPress; FF = mouthRollLower + mouthUpperUp; aa = jawOpen 0.6. The exact weights are UNVERIFIED and should be tuned once, then reused for every character.
- Name them `viseme_sil` … `viseme_ou`.
- Mobile can ship only these 15 plus blink L/R and jaw, instead of all 52.

**8.4 Making the 52 shapes automatically.** Three routes, best first for Forge.
1. **From ARP facial bone poses (fully scripted, works on any topology).** Store 52 pose presets as controller transforms normalised by head size. For each preset: apply the pose, run `bpy.ops.object.modifier_apply_as_shapekey(keep_modifier=True, modifier="Armature")` on the face mesh, rename the result to the ARKit name, then reset the pose. Add the computed lid shapes from §3 (more accurate than bones). Quality is medium; the director approves the contact sheet.
2. **Template transfer (AAA quality).** Keep one canonical head with perfect loops and hand-authored ARKit 52 shapes. Wrap it onto the AI head: landmark-based RBF/Laplacian deform, then shrinkwrap and relax. Bake the AI head's detail onto the wrapped template. Shapes then transfer as deltas, because the vertex order is identical. Topology and shapes stay consistent across every character, so this is the route to scale up to. Building the template is a one-time manual or authoring job.
3. **Third-party add-ons** (Faceit, FaceKeys) generate ARKit shapes from landmarks. Headless scripting of their operators is UNVERIFIED.

**8.5 MetaHuman conventions (UE AAA)**
- MetaHuman faces run on RigLogic/DNA with curves like `CTRL_expressions_eyeBlinkL` and joints like `FACIAL_C_Jaw` and `FACIAL_L_Eye` (names UNVERIFIED from memory).
- Live Link Face ARKit data reaches MetaHumans through the `mh_arkit_mapping_pose` pose asset inside Face_AnimBP ([NVIDIA ACE UE doc](https://docs.nvidia.com/ace/ace-unreal-plugin/2.5/ace-unreal-plugin-animation.html), [forum](https://forums.unrealengine.com/t/retargeting-face-data-stream-from-live-link-face-app/2503215)).
- For a Forge character in UE:
  - With ARKit shape keys, Live Link Face drives the morph targets directly (curve name = morph name).
  - With bone-only faces, build a **Pose Asset** from an animation whose frames are the 52 poses with matching curve names. That is Epic's documented approach in the Face AR Sample ([UE Face AR sample](https://dev.epicgames.com/documentation/unreal-engine/face-ar-sample-in-unreal-engine)). ARP can bake those 52 frames.
- "Mesh to MetaHuman" is an alternative route for realistic humans only. It is known to misalign the occlusion and lacrimal meshes on custom heads ([forum](https://forums.unrealengine.com/t/mesh-to-metahuman-causes-misalignment-around-the-eyes/689206)). Whether it works on closed-eye AI heads, and current MetaHuman licensing for non-UE engines, are both UNVERIFIED.

**8.6 Runtime drivers**
- NVIDIA Audio2Face outputs ARKit-style weights (ACE doc above).
- Unity Live Capture has an ARKit FaceBlendShape mapper.
- Unity lip-sync: uLipSync, an open-source MFCC-based plugin that drives blendshapes (UNVERIFIED current status).
- MetaHuman Animator audio-to-face: MetaHumans only (UNVERIFIED for custom meshes).

---

## 9. Skin shading

**(a)** Skin without SSS looks like plastic or wax. The specular breakup (pores, oily T-zone) is what reads as "skin" at close range.

**(d) Maps Forge should produce**
- Albedo with lighting removed (AI textures often contain baked lighting; delight it).
- Normal (from the dense mesh) plus a **tiling detail/pore normal** (2–8× tiling, mask-blended; generated procedurally as a noise-cells pore map).
- **Cavity** (curvature/pointiness bake, multiplied into specular).
- Roughness/specular mask (T-zone oilier, lips wet, cheeks drier).
- **Thickness/SSS mask** (ears, nostrils, lids high).
- **Tint masks** in RGBA: lips, cheeks/blush, brows/beard, eye-shadow. These allow runtime customisation.
- AAA option: **wrinkle maps.** These are animated normal maps blended by expression curves (brow raise, squint, smile), as in MetaHuman. They are hard to auto-generate: one idea is baking the shape-key-posed mesh with procedural crease displacement, UNVERIFIED. Treat as phase 2.

**(e) Bake.** In Cycles, bake cavity, AO and thickness from the dense original *after* the eyeballs, lid pockets and nostril cuts are in place. Generate the masks from landmarks as UV-space soft regions.

**(f) Engines**
- **UE5:**
  - *Subsurface Profile* shading model: screen-space, more physically accurate. It needs TAA/TSR, Metallic is unavailable, and the default profile approximates Caucasian skin ([UE Subsurface Profile](https://dev.epicgames.com/documentation/en-us/unreal-engine/subsurface-profile-shading-model-in-unreal-engine)). Create one profile per skin tone. The dual-lobe specular lives in the profile asset (UNVERIFIED wording).
  - Mobile UE: *Preintegrated Skin* is cheaper.
- **Unity URP:** no built-in SSS. Use a Shader Graph with wrap lighting plus a pre-integrated skin LUT (curvature × N·L), a thickness-based back-light term for ears, detail normal and cavity. Mobile: a wrap-diffuse red terminator only.

---

## 10. Commonly missed face items (checklist for Forge to gate on)

1. Eyeballs as separate rotating meshes, with lid pockets.
2. Lid-margin thickness, with even upper and lower vertex counts.
3. Eyelid follow **implemented engine-side** (constraints do not export).
4. Tear line, caruncle and occlusion (AAA), or baked equivalents (mobile).
5. Lashes and brows that receive the same shape keys as the face (attachment follower).
6. AO and cavity re-baked after the eyes and mouth are opened.
7. Texture inpaint of painted eyes and lids.
8. Symmetric topology (QR symmetry) so shapes mirror.
9. Nasolabial, vermilion, crease and jaw-line loops.
10. Neutral pose = eyes open, mouth closed, relaxed (face capture assumes this).
11. Blend-shape normals: Unity *Calculate*; UE recomputes morph tangents.
12. Morph targets on **each LOD**: Unity LOD meshes each need their own blendshapes; UE morphs per LOD.
13. Bones per vertex: Unity mobile Skin Weights = 4 (UE supports more).
14. Mobile budget, heuristic, UNVERIFIED:

    | Part | Mobile | AAA |
    |---|---|---|
    | Head | 1.5–5k tris | 8–30k tris |
    | Blendshapes | blink L/R + 15 visemes + jaw | full ARKit 52 + correctives + wrinkle maps |

15. Stylised/chibi alternative: **texture-swap eyes and mouth** (UV-offset flipbook driven by a bone scale or material parameter). Very cheap for mobile, and it avoids lid topology entirely.
16. Mythical variants:
    - Extra eyes: custom bones with Damped Track to the shared eye target, extra `eyeBlink_C` keys. ARP's support for more than 2 eyes is UNVERIFIED.
    - Tusks and horns: rigid to the jaw or head bone.
    - Slit, glowing or solid pupils: material parameters.
    - Long ears: bone chain.

---

## Sources
- [Auto-Rig Pro version history (auto-eyelid per lid, remove eyelids, remap names, nose bones)](https://superhivemarket.com/products/auto-rig-pro/versions)
- [ARP user review (eyebrow bones, facial options)](https://superhivemarket.com/products/auto-rig-pro/ratings?page=3)
- [80.lv: stylised facial rig with ARP](https://80.lv/articles/stylized-3d-facial-rig-made-in-blender-with-auto-rig-pro)
- [Faceit FAQ (ARP compatibility)](https://faceit-doc.readthedocs.io/en/latest/FAQ/)
- [Apple ARKit BlendShapeLocation](https://developer.apple.com/documentation/arkit/arfaceanchor/blendshapelocation)
- [Unity ARKitBlendShapeLocation](https://docs.unity3d.com/Packages/com.unity.xr.arkit@6.1/api/UnityEngine.XR.ARKit.ARKitBlendShapeLocation.html)
- [Unity Live Capture FaceBlendShape](https://docs.unity3d.com/Packages/com.unity.live-capture@1.1/api/Unity.LiveCapture.ARKitFaceCapture.FaceBlendShape.html)
- [Meta OVRLipSync viseme reference](https://developers.meta.com/horizon/documentation/unity/audio-ovrlipsync-viseme-reference/)
- [UE shading models (Eye model)](https://dev.epicgames.com/documentation/en-us/unreal-engine/shading-models-in-unreal-engine)
- [UE Substrate Eye BSDF](https://dev.epicgames.com/documentation/unreal-engine/API/Runtime/Engine/UMaterialExpressionSubstrateEyeB-)
- [UE Subsurface Profile](https://dev.epicgames.com/documentation/en-us/unreal-engine/subsurface-profile-shading-model-in-unreal-engine)
- [UE Face AR Sample](https://dev.epicgames.com/documentation/unreal-engine/face-ar-sample-in-unreal-engine)
- [NVIDIA ACE UE animation (mh_arkit_mapping_pose)](https://docs.nvidia.com/ace/ace-unreal-plugin/2.5/ace-unreal-plugin-animation.html)
- [UE forum: retargeting Live Link Face](https://forums.unrealengine.com/t/retargeting-face-data-stream-from-live-link-face-app/2503215)
- [UE forum: Lumen lacrimal glow](https://forums.unrealengine.com/t/lumen-gi-skylight-glowing-lacrimal-fluid/239224)
- [UE forum: eye LOD material slots](https://forums.unrealengine.com/t/missing-eye-on-lod3/258052)
- [UE forum: MetaHuman 5.6 wrong materials](https://forums.unrealengine.com/t/ue5-6-preview-metahuman-creator-assembled-metahuman-has-wrong-materials-assigned/2532947)
- [UE forum: Mesh to MetaHuman eye misalignment](https://forums.unrealengine.com/t/mesh-to-metahuman-causes-misalignment-around-the-eyes/689206)
- [UE forum: modifiers don't export](https://forums.unrealengine.com/t/face-rigging-question-blender-to-unreal/2686598)
- [Unity HDRP Eye shader](https://docs.unity3d.com/Packages/com.unity.render-pipelines.high-definition@15.0/manual/eye-shader.html)
- [Unity Sclera Iris Blend node (HDRP only)](https://docs.unity3d.com/Packages/com.unity.shadergraph@13.1/manual/Sclera-Iris-Blend-Node.html)
- [Reallusion eye occlusion shader](https://manual.reallusion.com/Character-Creator-5/Content/ENU/5.0/15_Digital_Human_Shader/Eyes/Digital-Human-Eye-Occlusion-Shader.htm)
- [Reallusion tear line shader](https://manual.reallusion.com/Character-Creator-5/Content/ENU/5.0/15_Digital_Human_Shader/Eyes/Digital-Human-Tearline-Shader.htm)
- [Blender Shrinkwrap constraint](https://docs.blender.org/manual/en/dev/animation/constraints/relationship/shrinkwrap.html)
- [Blender Studio facial rigging: eyes chapter](https://studio.blender.org/training/facial-rigging/chapter/eyes/)
- [BlenderArtists: non-linear eyelid shape keys](https://blenderartists.org/t/found-a-facial-rig-solution-in-blender-eyelids-blink-with-non-linear-shape-keys/1369811)

**Unreachable:** lucky3d.fr (official ARP docs) and docs.unity3d.com (direct fetch) are blocked by the session network allowlist. Allow them to verify the exact ARP facial option and bone names.
