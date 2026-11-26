# Research: human-body

# Forge research report: human/humanoid BODY features for game-ready rigs

**Scope:** This covers the body only: hands, feet, joints, secondary motion, clothing, armour, accessories, hair and LOD. It does not repeat the areas you already researched: mouth interior, retractable parts, fur/hair cards, tattered alpha, ARP extra limbs and mechanical rigs. Sources are numbered [n] and listed at the end.

**Access limit:** the official Auto-Rig Pro documentation (lucky3d.fr) was not reachable from this session. The host has to be allowed in the session's network settings before it can be checked. Every ARP option or operator name below comes from memory, marketplace listings or forum threads, and is marked UNVERIFIED unless a source confirms it.

---

## 0. Cross-cutting rules (apply to every feature)

1. **Engines skin with linear blend skinning (LBS), so Blender must too during the pose test.**
   - Blender's Armature modifier "Preserve Volume" uses dual-quaternion skinning (DQS). That setting does not survive FBX export.
   - Unreal has no native DQS, according to forum reports and a third-party UE5 "DualSkin Toolkit" [18]. Treat the absence of DQS in Unity's built-in renderer as UNVERIFIED.
   - The Kavan DQS paper explains why LBS collapses at twisted and bent joints ("candy-wrapper") [19].
   - **Action:** run the director's pose-test renders with `armature_mod.use_deform_preserve_volume = False`. Otherwise the director approves deformation that the engine will not reproduce.
2. **Bones per vertex.** Unity limits skin influences per vertex through Quality settings (One, Two or Four Bones, or Auto) [9]. Unity calls four influences the performance-friendly maximum and advises keeping bone counts below about 30 for mobile [9].
   - In bpy, normalise and limit weights to 4 for UE and Unity URP: `bpy.ops.object.vertex_group_limit_total(limit=4)`, then `vertex_group_normalize_all()`.
   - Consider limiting to 2 influences for low mobile LODs.
3. **The deformation-quality chain** (cheapest first):
   - topology loops
   - weights
   - twist bones
   - helper/corrective bones
   - corrective morph targets
   - ML Deformer (UE only, AAA)

   Mobile should stop at helper bones. Morph targets cost memory and GPU on mobile and should be reserved for the face.
4. **Automated ROM pose test, run after every rig change:**
   - Generate a standard range-of-motion action: arms up/forward/back, elbow 140°, wrist ±70°, squat, knee 140°, hip flex 100°, fist.
   - Measure flipped faces, self-intersections (`mathutils.bvhtree.BVHTree.overlap` between body regions) and local volume loss (signed tetra volume per limb segment, rest vs posed).
   - Render a contact sheet with red heat-map overlays. The director approves that one image.

---

## 1. Hands: fingers, thumb, nails, finger loops

**(a) Why it matters.** Hands sit in first-person view and in every close-up (grip, weapon hold, gestures). Fused AI fingers make grips and hand-IK impossible. Bad knuckle loops collapse when the hand makes a fist.

**(b) Topology**
- **Per finger:** 3 phalanges, each with at least 3 loops per knuckle (one at the crease, one on each side) for AAA, and 2 for mobile.
- **Finger cross-section:** 8 sides for AAA, 6 for mobile, a 4-sided "mitten" for far LODs. These are common practice (UNVERIFIED as a standard).
- **Thumb:** starts at the carpometacarpal joint deep in the palm, not at the web. It needs its own loop fan into the palm plus a web loop between thumb and index finger.
- **Palm:** loops for the palm creases. The back of the hand needs loops that let the knuckles bulge.
- **Nails:** AAA uses a small inset/extruded nail plate (2-4 quads plus a cuticle loop). Mobile uses no geometry, only a texture mask.
- **Budget (UNVERIFIED ballpark):** about 2-4k triangles per hand for AAA hero LOD0, about 400-800 for mobile, and a mitten (fingers merged, 1 bone) at LOD2+.

**(c) Rig**
- **ARP:** arm limb "Fingers" with per-finger toggles (thumb, index, middle, ring, pinky). Bones are named like `c_thumb1/2/3`, `c_index1/2/3` plus `c_index1_base` metacarpals; there are finger IK and "fingers shapes"/fist sliders. All UNVERIFIED (docs unreachable).
- **UE5 Manny naming:** `thumb_01_l…03`, `index_metacarpal_l`, `index_01_l…03` (and similar for the other fingers). The `_metacarpal` bones are UNVERIFIED; check the Manny skeleton in-editor. Use ARP's game-engine export with UE renaming.
- **Unity:** Humanoid avatar maps Proximal/Intermediate/Distal per finger. Metacarpals are not mapped.
- **Mobile:** drop the distal bones, or merge fingers into one or two "curl" bones at low LOD (UE "Bones to Remove" per LOD [7]).
- **Correctives:** knuckle bulge via a small "knuckle" helper bone per MCP joint (AAA only) or a morph for a full fist.

**(d) Texture/material**
- SSS (subsurface) skin profile.
- Nail mask with its own roughness and specular (nails are glossy).
- Knuckle-wrinkle detail normal.
- Palm/back colour difference (the palm is lighter and less pigmented).
- Optional knuckle wrinkle map blended by finger-curl curve (AAA).
- Tint mask channel for gloves versus skin.

**(e) Automation in Blender**
- **Detect fused fingers.**
  1. From the ARP Smart wrist marker and the hand bounding box, slice the hand along its long axis using `bmesh.ops.bisect_plane` on a copy at 5-10 planes from the knuckles to the fingertips.
  2. Count closed cross-section loops per slice (connected edge islands).
  3. If the count is under 4 outside the thumb, the fingers are fused. Flag it.
- **Fix, in order of preference:**
  1. Regenerate at source: give Tripo a reference image in A-pose with "fingers spread, palms down".
  2. Swap in a procedural or template hand. Keep a clean, already-weighted hand asset in a library, fit it with lattice/shrinkwrap to the AI hand silhouette, then bridge the wrist loop (`bmesh.ops.bridge_loops`). Transfer colour by baking.
  3. Last resort: cut fingers by Boolean slabs between the knuckle markers. The director clicks 4 gap points.
- **Loop density:** paint vertex-colour density near knuckle markers. Quad Remesher can use vertex colour for adaptive density (property name in bpy UNVERIFIED, e.g. `use_vertex_color`).
- **Nail mask:** a procedural mask from fingertip-bone proximity, dorsal-facing normals and distal-phalanx length. Bake it to a mask channel. The director confirms it visually.

**(f) Engine**
- UE: IK Retargeter needs finger chains mapped. Remove finger bones at LOD2+ via Bones to Remove [7].
- Unity: Humanoid finger muscles, and Skin Weights Quality=Two on low-end [9].

---

## 2. Feet and toes

**(a)** Feet need clean ankle and ball-of-foot deformation for walk and IK foot-planting. Barefoot characters, and creatures with visible toes, need toe bones.

**(b) Topology**
- Ankle: 3 loops.
- Ball-of-foot crease: 2-3 loops.
- Heel and sole fairly flat. A planar sole helps foot IK and contact.
- Barefoot AAA: individual toes with 2 loops per toe joint.
- Shoes: no toes, only a ball-crease loop. Mobile: one toe block.

**(c) Rig**
- **ARP:** leg limb "Toes" option, with individual toe bones (`toes_thumb`, `toes_index` and so on) or a single `c_toes` (UNVERIFIED names). Foot roll and banking controls are built in.
- **UE Manny:** `foot_l` and `ball_l`. **Unity Humanoid:** Foot and Toes.
- Shoes: export only `ball`. Individual toes: export them as extra bones, which are not in Humanoid mapping, so they stay generic.

**(d) Material:** for barefoot, SSS, a nail mask and a sole-dirt mask (an AO plus world-down gradient mask). For shoes: leather/rubber, a tint mask, and a detail normal for the sole tread.

**(e) Automation**
- Classify barefoot versus shoe by segmentation label (Section 8), or by colour/material discontinuity at the ankle.
- For barefoot: run the same cross-section toe count as for fingers.
- Set ARP toe options accordingly through the ARP property on the reference-bone armature (UNVERIFIED property path). The director clicks once if it is ambiguous.

**(f) Engine:** UE foot IK (Control Rig / Leg IK) needs `ik_foot_*` virtual bones. ARP can export IK bones (UNVERIFIED option). In Unity Humanoid, Foot IK is automatic.

---

## 3. Joint deformation: shoulders, elbows, knees, hips, wrists

**(a)** Joints cause most visible "rig-broken" artifacts: collapse, candy-wrapper twist, armpit tearing and buttock flattening. These show in every animation, not only close-ups.

**(b) Topology** (sources: Polycount limb-topology discussions, ZRemesher joint guide [12])
- **Elbows and knees:** 2-3 tight loops on the crease side and broader rings on the stretch side. A single loop collapses, so use a double edge at the front of the elbow [12]. Add a "diamond" or extra loop at the kneecap and the point of the elbow.
- **Shoulder:** circular loops around the deltoid, continuing into the armpit and chest. The clavicle must exist and be weighted [12].
- **Hips:** a loop following the inguinal crease (groin) and one following the gluteal fold.
- **Wrists:** 3 loops. Forearm loops must be evenly spaced so twist distributes.
- **Neck:** 3+ loops (the face pipeline covers the head).
- **Budget:** an AAA joint with 6-10 loops per elbow/knee region; mobile 3-4.
- **Quad Remesher:** loops do not appear automatically in the right place. Feed density through vertex colour (high at joint markers) and, if the version supports it, guide curves/edges (UNVERIFIED in the bpy API).

**(c) Rig**
- **Twist bones.**
  - UE Manny has 2 twist bones per segment: `upperarm_twist_01_l/02_l`, `lowerarm_twist_01/02`, `thigh_twist_01/02`, `calf_twist_01/02` [3].
  - ARP arms and legs have a "Twist bones" count. One is enough inside Blender with Preserve Volume. At least one is needed for the Unity humanoid, and UE supports several [1]. Set it to 2 for UE and 1 for Unity mobile.
  - ARP's secondary controllers have deformation modes "Twist" (FBX-exportable), "Additive" (FBX-exportable) and "Bendy-Bones" (Blender only, not for games) [13]. Use Twist or Additive for export.
- **Unity twist driving:** Unity Humanoid avatar "Upper Arm / Fore Arm / Upper Leg / Leg Twist" muscle settings (UNVERIFIED names). Or use Animation Rigging "Twist Correction", which redistributes a share of the source rotation to twist nodes with weights from -1 to 1 [16].
- **UE twist driving:** baked into animation, or the post-process AnimBP / Control Rig drives twist and corrective bones. The Manny corrective hierarchy (e.g. `thigh_correctiveRoot_l`) is driven by the post-process ABP [3].
- **Corrective (helper) bones** are the mobile-friendly option. Add helper bones for elbow, knee and armpit/deltoid, buttock and wrist volume.
  - In Blender, a helper bone parented to the parent segment, with Copy Rotation at 0.5 influence from the child plus a translation driver.
  - On export these must be baked (ARP bakes constraints on export), or re-created in the UE post-process AnimBP / Unity Animation Rigging.
  - MetaHuman uses RBF solvers to drive corrective joints from driver-joint rotation [11].
- **Corrective shape keys / morph targets** (AAA):
  - Shape keys named, for example, `elbow_bend_90_L`, `knee_bend_120_L`, `shoulder_up_L`, `hip_flex_L`.
  - Driven in Blender by bone-rotation drivers.
  - In UE by the Pose Driver node (RBF; can drive Pose Assets or curves; marked experimental) [10] or Control Rig.
  - In Unity by a small script or Animation Rigging job writing `SetBlendShapeWeight`.
  - Note: ARP has a corrective shape-key helper (UNVERIFIED).
- **AAA alternative:** UE ML Deformer, trained from Alembic or Chaos-generated data [20]. Expensive to set up and not for mobile.

**(d) Texture:** wrinkle and stretch detail normals at elbow and knee creases (optional), and an AO bake that does not bake a crease shadow you would need to remove when straight. A neutral rest pose (A-pose) is best for the bake.

**(e) Automation**
- **Joint markers:** ARP "Smart" auto-detection gives elbow, knee, wrist, shoulder and hip positions.
- **Density field:** vertex colour = falloff from each joint (radius ≈ 0.6 × segment radius), used as Quad Remesher's adaptive-density input.
- **Weights:**
  - ARP bind (voxel/heat; ARP has a voxelized binding option for non-manifold AI meshes, UNVERIFIED name).
  - Smooth with `bpy.ops.object.vertex_group_smooth`, limit to 4, then normalise.
  - For difficult meshes, Robust Skin Weights Transfer (Epic Games; SIGGRAPH Asia 2023) from a clean template body. It does a two-stage closest-point match plus inpainting [4]. A Python/libigl implementation exists, and a separate Blender add-on is by Sent From Space [4][5].
- **Corrective shape key generation (scriptable):**
  1. Pose the joint and evaluate two meshes: the target with Preserve Volume / DQS on, plus Corrective Smooth for a smooth target, and the engine-like LBS result.
  2. The posed-space difference must be converted to rest space by inverse-skinning per vertex. That needs a small numpy routine: per-vertex blended matrix inverse.
  3. Store the result as a shape key and add a driver.
  4. Validate by re-running the ROM metrics.
- **Helper bones:** add them procedurally with `edit_bones.new` at joint markers and ARP custom-bone conventions (the `cc_` prefix for custom controllers is UNVERIFIED). Weight them by transferring a falloff around the crease.
- **Director's click:** only on the ROM contact sheet ("elbow OK / not OK").

**(f) Engine**
- **UE:** Pose Driver node is experimental [10]. Correctives on Manny are done through the post-process ABP [3]. Retarget rigs must include corrective bones [3].
- **Unity:** Twist Correction constraint [16]. Blend shapes cost per-frame GPU work, so avoid them on mobile.

---

## 4. Muscles and jiggle (breasts, belly, glutes, flab)

**(a)** Secondary motion sells weight and life. Its absence reads as "stiff". It is usually expected on stylised and realistic female characters, bellies and heavy characters.

**(b) Topology:** no special loops beyond even, dense-enough quads over the jiggle area. AAA 6-10 loops across a breast; mobile 3-4. Avoid triangles at the jiggle centre.

**(c) Rig**
- **ARP:** spine "Breast" option adds breast bones. A user reports 4 extra breast bones that are bendy-bones-based in Blender [13]. Export the deform bones only.
- **Belly/glute:** add custom bones parented to spine_01 or pelvis.
- **UE:** AnimDynamics node, a lightweight solver that simulates its own bodies, not the Physics Asset; it uses constraints rather than collision; there is one node per bone or chain [14]. Or Kawaii Physics (pafuhana1213's free plugin, UE 5.5 supported) [17]. Or Rigid Body nodes with the Physics Asset.
- **Unity:** spring-bone components. Magica Cloth "BoneSpring" mode is UNVERIFIED (not found in sources); a simple spring script also works. Use per-renderer distance culling on mobile.

**(d) Texture:** none special beyond skin SSS. Optional stretch-mark detail mask.

**(e) Automation**
- Decide from body measurements and director-entered character tags ("jiggle: chest/belly/glutes").
- Place bones at curvature maxima: the breast apex is found as the local maximum of distance from a fitted body proxy plane in the chest region.
- Weights: a radial falloff vertex group of radius r, blended with the parent spine weight.
- **Fully procedural.** The director only toggles tags.

**(f) Engine:** UE AnimDynamics respects the LOD threshold, so disable it at far LODs [14]. Unity: disable spring scripts beyond X metres.

---

## 5. Clothing layers (cloth versus body, hidden surfaces, simulation, weight transfer)

**(a)** AI meshes fuse clothes and body into one shell.
- Games need tight clothing to deform with the body without poke-through.
- Loose clothing (skirts, capes, coats, scarves) needs simulation or bone chains.
- Swappable outfits need a body underneath.
- Hidden body triangles waste triangles and cause z-fighting and poke-through.

**(b) Topology**
- **Tight clothing:** keep as part of the single "skin" mesh (simplest; most mobile NPCs do this). Loops must follow the body joints exactly as in Section 3.
- **Loose clothing:** a separate mesh or material section. Even quads for simulation (uniform edge length ≈ simulation resolution). Single-sided plus a backface material, or a thin inner shell. Cloth edges need a hem loop.
- **Swappable layering:** separate skinned meshes sharing one skeleton. The body under clothing is deleted per outfit or masked.
- **Budget:** a skirt or cape simulation mesh of about 500-2k vertices for AAA, about 100-300 for mobile, or use bone chains instead.

**(c) Rig and engine components**
- **UE:**
  - Chaos Cloth via the Clothing Tool on skeletal mesh sections. Paint Max Distance, the maximum distance a vertex may move from its skinned position; also Backstop [6].
  - Newer UE: Chaos Cloth Asset / Dataflow (Panel Cloth editor, experimental in 5.3) [20].
  - Modular outfits use Leader Pose (cheap on the game thread, not render) or Copy Pose From Mesh [15]. Cloth on followers needs "Bind Cloth to Leader Pose", which forces local-space simulation [15].
- **Unity:**
  - The Cloth component on a SkinnedMeshRenderer, with per-particle Max Distance constraints. Colliders are limited to sphere/capsule/conical capsule. Self-collision is expensive [8].
  - `Cloth.coefficients[i].maxDistance` is scriptable, so the editor import script can read a vertex colour exported from Blender and fill the coefficients automatically.
- **Mobile:** prefer bone chains (ARP Spline IK or tail-like chains, or a kilt-style limb) with spring motion, over mesh cloth.

**(d) Texture/material**
- Fabric uses UE's Cloth/"Sheen" shading model or Substrate fuzz. Unity URP Lit has no sheen, so use a custom fabric shader or Lit with fuzz detail.
- Detail normal for weave, a tint mask for recolour variants, and opacity/two-sided for single-layer cloth.
- Body hiding mask texture: MetaHuman-style body masks. Note a forum report that the mask is broken after assembly in UE 5.8 (verify per version) [21].

**(e) Automation**
1. **Classify** (Section 8) into SKIN, CLOTH_TIGHT, CLOTH_LOOSE.
2. **CLOTH_LOOSE extraction.** Segment-separate (`bpy.ops.mesh.separate(type='SELECTED')`), remove inner faces, and solidify or keep single-sided.
3. **Body under loose cloth.** The AI mesh has no body there. Options:
   - (i) Regenerate a "base body" in Tripo from an edited image of the same character in underwear or bodysuit.
   - (ii) Fit a parametric base body (MPFB/MakeHuman in Blender, or a stored template mesh) to the ARP markers, then shrinkwrap it to the inner clothing surface plus an offset. Licensing needs checking.
   - (iii) Fill only the needed part (legs under a skirt) from the template.
4. **Weight transfer to clothing.**
   - Data Transfer modifier from the body: Vertex Data → Vertex Groups, mapping "Nearest Face Interpolated" / "Projected Face Interpolated", then Generate Data Layers [22]. In bpy: `mod.data_types_verts={'VGROUP_WEIGHTS'}; mod.vert_mapping='POLYINTERP_NEAREST'`, then `bpy.ops.object.datalayout_transfer(modifier=mod.name)` and apply.
   - For loose cloth, Robust Skin Weights Transfer gives better results by inpainting regions that don't match [4]. Smooth along the skirt so the legs don't tear it.
5. **Hidden-surface removal** (deterministic and scriptable):
   1. For each body face, cast rays along its normal and in 4 jittered directions using `BVHTree.ray_cast` against the clothing BVH.
   2. If every ray hits clothing within d (e.g. 0.5-3 cm, or a scale-relative value), then do this in rest pose and the 4-6 ROM poses (evaluate depsgraph meshes).
   3. Hidden in every pose: delete the face (baked outfit), or write a vertex group/texture "hide mask" (swappable outfit).
   4. Keep a 1-loop margin.
6. **Poke-through check:** ROM poses, count body verts outside the cloth surface (sign of the closest-point normal dot). Push cloth outward via a Shrinkwrap "Outside Surface" offset on the affected verts only.
7. **Simulation weights:** procedurally compute Max Distance = f(distance below the waist / pelvis bone, distance from the attachment line). Store in vertex colour for Unity, or as a vertex group for UE painting/Dataflow import (automatic import path in UE UNVERIFIED; may require one paint step or an editor Python script).
8. **Director's clicks:** confirm the class colour map. For a skirt, optionally choose sim / bone-chain / rigid.

**(f) Engine notes**
- UE Clothing Tool Max Distance semantics [6].
- Mutable "Remove Unseen Mesh Parts" / "Clip Mesh With Mesh" for runtime outfit swaps; forum reports artifacts with morphs [21].
- Third-party UE occluders exist (Fab "Dynamic Mesh Occluder") [21].
- Unity: Cloth component costs [8].

---

## 6. Armour (rigid plates)

**(a)** Metal plates must not bend like skin. Overlapping plates (pauldrons, tassets, greaves) must slide without interpenetrating. This is obvious in close-ups and in combat poses.

**(b) Topology**
- Hard-surface: support loops or bevel plus weighted normals rather than many loops. Each plate is a separate island with real thickness.
- Pauldrons overlap the arm with clearance.
- Inner surfaces hidden by the body can be deleted.
- Budget: AAA 2-10k triangles per major plate set; mobile with the normal map carrying the detail.
- Separate material slot (metal).

**(c) Rig**
- **Rigid skinning:** each plate island is weighted 100% to one bone (no blending). This is what makes it "rigid on bones".
- **Pauldron:** its own helper bone between clavicle and upperarm (Copy Rotation 0.5, or "half-rotation" Damped Track), baked on export.
- **Tassets/faulds** (hip plates): one bone each, with a limit-rotation constraint or AnimDynamics hinge in-engine [14].
- **Helmet/visor:** rigid to head. A visor hinge bone if it opens.
- **Small rigid accessories:** as separate static meshes attached to sockets. UE: socket attachment / a `socket_` bone. Unity: a child transform. These are cheaper for swapping (exact UE socket-creation automation UNVERIFIED; can be done via editor Python).

**(d) Texture/material**
- PBR metal/roughness, AO, curvature-driven edge wear mask, and a dirt/grime mask (AO plus world-up).
- RGB tint mask for 3 recolour zones (faction colours).
- Detail normal for brushed metal. Optional anisotropic for brushed steel: UE Substrate/anisotropy input; URP Lit has none (custom shader).
- Emissive for runes.

**(e) Automation**
- **Detect armour segments:** semantic label (Section 8), plus low Gaussian curvature variance per island, plus high metallic/low roughness from the Tripo PBR textures sampled at the faces, plus an offset from the body proxy greater than cloth thickness.
- **Rigid weights:** for each island, sum the current skin weights per bone, then assign 100% to the argmax bone (a simple bmesh/numpy loop).
- **Pauldron helper bone:** created procedurally at the shoulder marker.
- **Interpenetration check** in ROM poses with `BVHTree.overlap` between the plate and its neighbour plates or body. Report it to the director as red highlights. The fix is director-assisted: the director chooses "add clearance" (scale plate up 3%) or "add helper bone".

**(f) Engine:** UE can use Leader Pose for modular armour sets [15], or static mesh components on sockets. Unity: child transforms or separate SkinnedMeshRenderers sharing bones.

---

## 7. Accessories (belts, pouches, jewelry, straps)

**(a)** They add silhouette, but they break if weighted like skin (belts stretching) or if fully rigid (belt snapping off the waist).

**(b) Topology:** belts as a ring band with 2-3 loops of height and quads around. Buckles and pouches are separate islands. Jewelry is low-poly with detail in the normal map. Mobile: merge into the body texture where they are small (rings, thin necklaces become texture-only).

**(c) Rig**
- **Belt band:** smooth weights from the pelvis/spine (Data Transfer from the body [22]) with weights smoothed vertically, so it moves as one band.
- **Buckle, pouch:** rigid to the pelvis or thigh, plus an optional jiggle bone driven by UE AnimDynamics [14] / Kawaii Physics [17], or a Unity spring.
- **Necklace/chain:** a 3-6 bone chain (AnimDynamics chain mode costs more [14]).
- **Earrings/pendants:** a single pendulum bone.
- **Rings:** rigid to the finger proximal bone. Removed at far LODs.

**(d) Material:** metal/leather. Tint masks. Gem emissive or a fake-refraction gem shader (UE: refraction/Substrate; Unity URP: cubemap-reflection gem). Alpha-test for chain links on mobile.

**(e) Automation**
- Segmentation label plus small-island size plus position relative to markers. Waist ring → belt; neck ring → necklace; finger → ring.
- Choose weighting automatically:
  - ring-shaped and around a limb → smooth transfer
  - small and compact → rigid
  - long and thin hanging → bone chain via ARP Spline IK or a procedural chain using `edit_bones.new` along the hanging curve skeleton
- Hanging-chain detection: a principal axis aligned with gravity plus a free end.
- The director confirms "dangling: yes/no".

**(f) Engine:** AnimDynamics/Kawaii in UE; spring bones in Unity. Disable at far LOD.

---

## 8. Deciding automatically what is body vs clothing vs armour vs hair vs accessory

Recommended decision pipeline, scriptable:

1. **Semantic segmentation from the generator.**
   - Tripo Segmentation v2 is semantic, splits the model into named parts with granularity levels, and is available via the API (Alibaba/fal/WaveSpeed/ComfyUI wrappers; fal returns part names) [23].
   - Map names with a keyword dictionary: skin/body/arm/leg; shirt/pants/skirt/cape/coat; armor/plate/pauldron/helmet/gauntlet; belt/pouch/necklace; hair/beard.
2. **Local fallback/refinement.**
   - Hunyuan3D-Part (P3-SAM segmentation of any mesh plus X-Part completion of hidden parts) is designed for AI-generated meshes [24]. Its "complete the occluded part" ability is useful for generating the body under clothing. The public release is a "light" X-Part.
   - PartField (NVIDIA): fast feed-forward class-agnostic segmentation [24].
   - Running these on the RTX 4080 16 GB under Windows: feasibility UNVERIFIED.
3. **Geometric and material features per segment, computed in bpy:**
   - Fitted body proxy: ARP Smart markers, then a parametric body or capsule skeleton. Measure each segment's signed distance from the proxy: near 0 → skin or tight cloth; above the threshold → loose cloth or armour.
   - Thickness: inward ray cast. Cloth is about 0.3-1 cm, armour plate about 0.3-1 cm but rigid and offset.
   - Curvature statistics: armour is piecewise smooth with sharp boundaries.
   - Material: metallic/roughness from the Tripo PBR maps, and a skin-tone hue range in albedo (HSV skin cluster).
   - Location relative to bones: below the waist and hanging → skirt/cape; on the head and covering the skull → hair/helmet.
4. **Rule-based classifier** to SKIN / CLOTH_TIGHT / CLOTH_LOOSE / ARMOUR_RIGID / ACC_RIGID / ACC_DANGLE / HAIR_SHELL. Output a confidence. Low confidence → director prompt.
5. **Director UI:** a colour-coded turntable render. One click on a mislabelled part cycles its class, implemented as a Blender modal operator or by clicking the material slot.
6. **Material IDs** per class become export sections in UE and submeshes in Unity, which enables hiding, LOD and material swaps.

---

## 9. Hair styles (helmet hair versus cards) and helmets

Fur/hair cards are already researched; body-related points only:

- **(a)** AI hair is a solid "helmet". It is fine for mobile and stylised work but looks fake in AAA close-ups. Hats and helmets require hair variants.
- **(b)** Keep the AI shell as the scalp/base cap (low-poly). Add cards on top for AAA. For mobile, the shell plus alpha-tested fringe cards.
- **(c) Rig:** long hair, ponytails and braids use bone chains (ARP Spline IK / tail-like limb), with physics through AnimDynamics/Kawaii (UE) or spring bones (Unity). Short hair stays rigid to the head.
- **(d) Material:** anisotropic hair shading. UE has the Hair shading model; URP needs a custom anisotropic or Kajiya-Kay shader (UNVERIFIED that URP lacks it built-in in the newest version). Alpha-test with dithered/TAA in UE. A root-to-tip gradient and ID/flow maps.
- **(e) Automation**
  - Detect hair segments: semantic label, plus a region on the skull above the ear-line markers, plus a high-frequency strand normal pattern.
  - For hats or helmets, generate a "hat-hair" variant via a shape key that shrinkwraps the hair under the helmet's inner surface. Name it e.g. `hair_compress_helmet`, exported as a UE morph target / Unity blend shape. Or delete the hidden hair faces as in Section 5.
  - UE can generate hair cards and per-LOD cards from grooms with the experimental Hair Card Generator. Each Generation Settings element maps to one LOD, and "Reduce Cards from Previous LOD" is available [25]. That only helps if a groom exists.

---

## 10. LOD and partial body hiding

**(a)** Performance (mobile especially), outfit swaps, first-person arms, and dismemberment.

**(b) Topology and budgets** (UNVERIFIED industry ballparks)
- AAA hero LOD0 about 60-150k triangles total (body plus clothes), LOD1 50%, LOD2 25%, LOD3 about 10%.
- Mobile LOD0 about 8-25k, LOD1 about 4-8k.
- Keep joint loops in LOD1, and drop finger and toe detail first.

**(c) Rig per LOD**
- UE: per-LOD "Bones to Remove", then regenerate that LOD [7]. Remove finger bones, twist_02, toes, jiggle and correctives at LOD2+.
- Unity: generated Mesh LOD ignores skin weights and blend shapes and does not reduce skinning cost. Unity recommends LOD Group with authored meshes for skinned meshes [26].
- So Forge should author skinned LODs in Blender:
  - Decimate (Collapse, with a vertex-group factor protecting joint loops) or Quad Remesher at lower counts.
  - Then Data Transfer the weights from LOD0 [22].
  - Then `vertex_group_limit_total(limit=2)` for the lowest mobile LODs.
  - Corrective morphs are excluded from LOD1+.

**(d) Texture:** a shared atlas across LODs. Lower LODs drop detail normals and SSS (mobile: pre-integrated or wrap lighting).

**(e) Automation:** fully scriptable LOD generation plus a ROM check per LOD, then a director contact sheet showing LOD0-3 side by side.

**(f) Partial hiding**
- **UE:**
  - `HideBoneByName` (scales the influence to zero; standard API, behaviour not checked here).
  - Material-slot opacity-mask parameters.
  - Body hiding masks (MetaHuman; reported broken after assembly in UE 5.8 [21]).
  - Mutable "Remove Unseen Mesh Parts" for runtime removal [21].
  - Leader Pose modular parts [15].
- **Unity:** separate SkinnedMeshRenderers per region (head/torso/arms/legs) toggled on/off. Mesh-section hiding by disabling submeshes needs a script.
- **Forge implication:** export the body split into region material slots (`M_Body_Torso`, `M_Body_Arms`, `M_Body_Legs`, `M_Body_Hands`, `M_Body_Feet`) or region vertex groups. The engine can then hide the regions covered by an outfit, and first-person views can show arms only.

---

## 11. Missed-feature checklist ("am I missing vital parts?") for the humanoid body

**Topology, rig and texture**
- Clavicle bones, and shoulder/armpit loops.
- Twist bones (2 for UE, 1 for Unity).
- Metacarpals (UE5) and finger chains.
- Thumb CMC loop fan, and a nail mask.
- Toes/ball bone, and a planar sole.
- Ankle, wrist, knee and elbow double loops.
- Gluteal and groin loops.
- Helper/corrective bones or corrective morphs (AAA).
- Jiggle bones: breast, belly, glute, pouches, earrings.
- Belt band weights, and rigid armour weights.
- Pauldron and tasset helper bones.
- Cloth sim masks (Max Distance).
- Hidden-body removal.
- Body region material slots for hiding.
- Hat-hair morph.
- 4-influence limit, and 2 for mobile low LODs.
- LODs authored with Bones to Remove.

**Materials**
- Skin SSS profile, and nail/palm/sole masks.
- Fabric sheen, metal edge-wear, and tint masks (RGB).
- Detail normals, and anisotropic hair/metal.

**Engine setup**
- UE: IK foot bones, retarget chains including correctives, Leader Pose / Bind Cloth.
- Unity: Humanoid avatar mapping, Twist Correction, Cloth coefficients from vertex colour.

**What needs what**

| Approach | Features |
|---|---|
| Procedural, no AI | density maps, weights, rigid armour, helper bones, jiggle bones, hidden-surface removal, LODs, masks, Max Distance, ROM tests |
| Needs a regenerated AI part | separated fingers (when fused), body under loose clothing (or template body / X-Part completion), clean hand replacement (or template library) |
| Needs one director click | class-map corrections, a fused-finger fallback cut, "dangling yes/no", skirt sim vs bone-chain, ROM sheet approval |

---

## Sources
1. ARP docs copy, twist bones (Unity needs at least 1; UE supports several; Preserve Volume in Blender). Low-quality mirror, wording garbled: https://blayowle1987.blogspot.com/2022/03/how-to-draw-oil-rig.html. Official docs (unreachable here): https://lucky3d.fr/auto-rig-pro/doc/
2. (unused)
3. UE Manny twist/corrective bones: https://www.reallusion.com/FeedBackTracker/Issue/Inconsistent-twist-bone-hierarchy-in-Unreal-Engine-skeletons ; https://forums.unrealengine.com/t/khornes-skm-manny-metahuman-logic-corrective-joints-skin-file-for-maya-2024/2693160 ; https://forums.unrealengine.com/t/how-to-retarget-ue5-manny-and-quinn-pose-assets-to-nearly-identical-skeleton/574222
4. Robust Skin Weights Transfer via Weight Inpainting (Abdrashitov et al., Epic, SIGGRAPH Asia 2023): https://www.dgp.toronto.edu/~rinat/projects/RobustSkinWeightsTransfer/index.html ; code: https://github.com/rin-23/RobustSkinWeightsTransferCode
5. Blender add-on coverage: https://digitalproduction.com/2025/04/23/weight-no-more-streamlining-blenders-weight-painting-with-robust-weight-transfer/ ; https://80.lv/articles/grab-this-one-click-blender-tool-for-effortless-weight-transfers
6. UE Clothing Tool (Max Distance, Backstop): https://dev.epicgames.com/documentation/en-us/unreal-engine/clothing-tool-in-unreal-engine
7. UE Skeletal Mesh LODs (Bones to Remove): https://dev.epicgames.com/documentation/en-us/unreal-engine/skeletal-mesh-lods-in-unreal-engine
8. Unity Cloth component: https://docs.unity3d.com/Manual/class-Cloth.html
9. Unity skin weights quality and mobile character optimisation: https://docs.unity3d.com/2021.1/Documentation/ScriptReference/QualitySettings-skinWeights.html ; https://docs.unity3d.com/2020.1/Documentation/Manual/ModelingOptimizedCharacters.html
10. UE Pose Driver (RBF correctives; experimental): https://dev.epicgames.com/documentation/en-us/unreal-engine/pose-driver-in-unreal-engine ; https://docs.unrealengine.com/4.27/AnimatingObjects/SkeletalMeshAnimation/AnimPose/PoseDriverNode/
11. MetaHuman RBF corrective joints: https://dev.epicgames.com/documentation/metahuman/metahuman-stylized-character-body-rig-editing
12. Joint topology: https://polycount.com/discussion/comment/1602516/ ; https://polycount.com/discussion/comment/902741/ ; https://novedge.com/blogs/design-news/zbrush-tip-deformation-ready-joint-topology-with-zremesher ; https://blenderartists.org/t/how-do-i-fix-this-knee-topology/1653202
13. ARP marketplace and forum (secondary controller modes Twist/Additive/Bendy-Bones; breast bones): https://superhivemarket.com/products/auto-rig-pro ; https://blenderartists.org/t/auto-rig-pro-3-69/672834?page=20
14. UE AnimDynamics: https://dev.epicgames.com/documentation/en-us/unreal-engine/animation-blueprint-animdynamics-in-unreal-engine
15. UE Modular characters / Leader Pose / Bind Cloth: https://dev.epicgames.com/documentation/en-us/unreal-engine/working-with-modular-characters-in-unreal-engine ; https://dev.epicgames.com/documentation/unreal-engine/BlueprintAPI/Clothing/BindClothtoLeaderPoseComponent
16. Unity Animation Rigging Twist Correction: https://docs.unity3d.com/Packages/com.unity.animation.rigging@1.2/manual/constraints/TwistCorrection.html
17. Kawaii Physics: https://github.com/pafuhana1213 ; https://80.lv/articles/kawaii-physics-plug-in-now-supports-unreal-engine-5-5
18. UE DQS (community): https://forums.unrealengine.com/t/dual-quaternion-skinning-method/158382 ; https://forums.unrealengine.com/t/nicolas-michel-dualskin-toolkit/2732323
19. Kavan et al., DQS: https://users.cs.utah.edu/~ladislav/kavan08geometric/kavan08geometric.pdf
20. UE ML Deformer / ML Cloth: https://dev.epicgames.com/documentation/en-us/unreal-engine/ml-deformer-framework-in-unreal-engine ; https://dev.epicgames.com/documentation/en-us/unreal-engine/machine-learning-cloth-simulation-overview ; https://forums.unrealengine.com/t/tutorial-ml-cloth-generation/1284843
21. Hiding the body under clothes: https://forums.unrealengine.com/t/tutorial-mutable-remove-unseen-mesh-parts/2135684 ; https://forums.unrealengine.com/t/metahumans-body-mesh-depeding-on-clothes/1661087 ; https://forums.unrealengine.com/t/fully-hidden-metahuman-body-becomes-visible-after-assembly/2833124 ; https://www.fab.com/listings/74734a8d-f8d3-4474-810b-f4577cdb769b ; https://forums.unrealengine.com/t/mutable-plugin-5-8-mesh-reshape-works-correctly-with-body-morphs-but-modifiers-clip-mesh-with-mesh-produce-geometry-artifacts-on-the-reshaped-mesh/2836644
22. Blender Data Transfer modifier: https://docs.blender.org/manual/en/4.5/modeling/modifiers/modify/data_transfer.html ; https://docs.blender.org/api/5.3/bpy.types.DataTransferModifier.html
23. Tripo Segmentation v2 / API: https://www.tripo3d.ai/blog/tripo-segmentation-v2 ; https://fal.ai/models/tripo3d/tripo/segment/llms.txt ; https://help.aliyun.com/en/model-studio/tripo-segmentation-api-reference
24. Part segmentation: https://huggingface.co/tencent/Hunyuan3D-Part/blob/main/README.md ; https://research.nvidia.com/labs/toronto-ai/partfield-release ; https://arxiv.org/html/2411.07184v1
25. UE Hair Card Generator / groom LOD: https://dev.epicgames.com/documentation/unreal-engine/creating-hair-cards-and-lods-using-hair-card-generator ; https://dev.epicgames.com/documentation/unreal-engine/setting-up-level-of-detail-for-grooms-in-unreal-engine
26. Unity Mesh LOD (ignores skin weights; no skinning saving): https://docs.unity3d.com/6000.2/Documentation/Manual/lod/mesh-lod-introduction.html ; https://discussions.unity.com/t/mesh-lod-2025/1620503

