# Research: creatures

# Forge: animal and mythical creature features (rig, topology, texture, automation)

**Scope:** every creature feature in the brief, each with (a) why it matters, (b) topology, (c) rig, (d) texture/material, (e) how to detect or create it in Blender, (f) UE5 and Unity notes.

**Research limits:** this session could not open lucky3d.fr (the Auto-Rig Pro (ARP) docs), gumroad.com or superhivemarket.com. ARP facts below come from search-result extracts of those pages, cited by URL. Any exact ARP option label or bone name I could not see in an extract is marked UNVERIFIED. Check them in the ARP 3.79.17 UI, or allow lucky3d.fr in the session's network settings and re-check. Polygon budgets are working figures from practice unless a source is given.

**Repo context:** `/home/user/Image-to-Game-asset/blender_scripts/forge_bpy/appendages.py` already finds tails, ears and horns as vertex groups far from the humanoid skeleton, and lays joint chains along them. Most proposals in section 0 extend that module.

---

## 0. Pipeline pieces that serve every feature

### 0.1 Classify each appendage by shape (extends `appendages.py`)
For each group `appendages.py` finds, run PCA on its vertices to get eigenvalues λ1 ≥ λ2 ≥ λ3, plus a radius profile along the main axis.

| Shape signature | Class | Rig |
|---|---|---|
| Rod (λ2/λ1 < ~0.1), tapering, curved, low deformation, on head | horn, antler, tusk, spike | rigid: 100% to one bone, no chain |
| Rod, long, uniform or tapering, attached at the pelvis | tail | ARP tail limb, or Spline IK when it has more than ~8 segments |
| Rod, very long (more than 2 body lengths), many of them | tentacle | Spline IK limb |
| Rod, thin, on head | antenna, whisker | 2–4 bone chain plus engine-side jiggle |
| Rod, touches the ground plane (min Z within ε) | leg | ARP leg (2 or 3 bones); count legs by clustering ground contacts |
| Sheet (λ3/λ2 < ~0.15) attached along an arm-like rod | membrane wing, or feathered wing (see 1.3) | |
| Sheet on torso or tail, thin | fin, frill, sail | small fan chains |
| Sheet on neck, many parallel slits | gills | shape keys |
| A second head-sized blob, at a neck end | extra head | duplicate head and neck limbs |

Thresholds are starting values (UNVERIFIED). Tune them on test assets.

**Director's one click:** show each detected part with a coloured overlay and a label. The director gets "confirm / relabel / ignore" per part, plus "add part here" for parts the AI merged into the body. This gives one visual approval instead of manual rigging.

### 0.2 Separate meshes versus one skin
Tripo welds everything into one surface. Use this split rule:

- **Split into separate objects:**
  - rigid parts: horns, claws, hooves, beak sheaths, armour plates, exoskeleton segments
  - alpha-card parts: feathers, mane cards, fin rays when alpha is used
  - emissive inserts: crystals, runes
- **Keep in the main skin:** anything that bends with the flesh, such as membranes, fins, gills, tentacles and tails.

Rigid separated parts are weighted 100% to one bone. This is cheap on mobile and never bends unnaturally.

### 0.3 Skin weight budgets
- **Unity:** `SkinnedMeshRenderer.quality`, project-wide `QualitySettings.skinWeights`, and `ModelImporter.maxBonesPerVertex` cap influences per vertex. Unity warns of a cost above 4 bones per vertex, and its older manual calls 2 a common compromise ([Unity SkinnedMeshRenderer.quality](https://docs.unity3d.com/ScriptReference/SkinnedMeshRenderer-quality.html), [QualitySettings.skinWeights](https://docs.unity3d.com/ScriptReference/QualitySettings-skinWeights.html), [Unity 2018.3 SkinnedMeshRenderer manual](https://docs.unity3d.com/cn/2018.3/Manual/class-SkinnedMeshRenderer.html)).
- **Forge defaults:** 4 influences for AAA, 2–4 for mobile. Normalise and limit with `bpy.ops.object.vertex_group_limit_total(limit=4)` and `vertex_group_normalize_all`.

### 0.4 ARP export
Export only the deform skeleton. Bendy-bone chains do not export to FBX, and the ARP FAQ advises "Twist" mode for FBX ([ARP auto_rig doc](https://lucky3d.fr/auto-rig-pro/doc/auto_rig.html), [ARP FAQ](https://www.lucky3d.fr/auto-rig-pro/doc/_sources/faq.rst.txt)).

So in Blender, Spline IK, bendy bones and fold controllers are animation-time controls only. The engine receives plain bone chains, and procedural motion is rebuilt there:
- **UE5:** the Spline IK node, AnimDynamics and Control Rig.
- **Unity:** the Animation Rigging package.

### 0.5 Engine-side secondary motion (shared by tails, ears, antennae, manes, fins, tentacles)
- **UE5:**
  - **AnimDynamics:** a cheap AnimGraph solver with no collision, only constraint limits ([UE AnimDynamics](https://dev.epicgames.com/documentation/en-us/unreal-engine/animation-blueprint-animdynamics-in-unreal-engine)).
  - **Rigid Body node:** uses the Physics Asset, so it collides, at higher cost.
  - **Spline IK AnimGraph node:** "tails or other malleable character structures", with control points that can be driven at runtime ([UE Spline IK, 4.26 ref](https://docs.unrealengine.com/4.26/en-US/AnimatingObjects/SkeletalMeshAnimation/NodeReference/SkeletalControls/SplineIK)).
  - **Control Rig spline rigging** ([UE Control Rig Spline Rigging](https://dev.epicgames.com/documentation/unreal-engine/control-rig-spline-rigging-in-unreal-engine)).
  - **Full Body IK** for procedural creature locomotion ([UE blog: FBIK procedural dragon](https://www.unrealengine.com/en-US/blog/full-body-ik-procedural-dragon-animations)).
- **Unity (Animation Rigging package):**
  - **Chain IK Constraint:** FABRIK solver from a Root to a Tip ([Unity ChainIK](https://docs.unity3d.com/Packages/com.unity.animation.rigging@1.1/manual/constraints/ChainIKConstraint.html)).
  - **Damped Transform:** lagging, trailing motion ([Unity Learn Damped Transform](https://learn.unity.com/tutorial/using-animation-rigging-damped-transform)).
  - On mobile, prefer baked animation plus a few Damped Transforms.

### 0.6 Texture conventions used throughout
- **AAA (UE5):** BaseColor, Normal, ORM (Occlusion-Roughness-Metallic) as standard. Add masks only when needed:
  - **Tint mask:** RGBA, up to 4 recolour zones, for variants.
  - **Emissive mask.**
  - **SSS/thickness map:** for membranes, ears and fins.
  - **Detail normal:** a tiling texture for scales and chitin.
- **Unity URP Lit:** offers Detail Albedo and Detail Normal, gated by a Detail Mask that reads the alpha channel ([URP Lit/Complex Lit](https://docs.unity3d.com/Manual/urp/shader-complex-lit.html), [URP Lit](https://docs.unity3d.com/Manual/urp/lit-shader.html)). Pack mobile masks into one RGBA texture.
- **Thickness map:** bake inverted AO from inside the mesh (Cycles AO bake with normals flipped). It feeds UE5 Subsurface/Two-Sided Foliage shading models and a URP custom translucency term.

---

## 1. Feature by feature

### 1.1 Quadrupeds (dog/horse presets, digitigrade legs, hooves, paws, claws)

**(a) Why it matters**
- Locomotion is the whole read of a quadruped.
- A wrong joint count gives the "backwards knee" look.
- Foot sliding is the most visible bug in games.

**(b) Topology**
- Loops:
  - 3 loops at each joint: shoulder/scapula, elbow, carpus/wrist, hock, fetlock, stifle.
  - A fan of loops around the scapula, which slides under the skin.
  - Belly loops running front to back.
- Hooves: a separate rigid mesh, or a hard edge plus its own UV island.
- Paws: one loop per toe pad. Pads can stay as normal-map detail.
- Claws: separate rigid meshes, parented to the toe bone.
- Budgets (working figures): dog 15–40k tris AAA, 3–8k mobile; horse 25–60k AAA, 5–10k mobile.

**(c) Rig**
- **ARP presets:** dog and horse presets exist, described as "presets (human, dog, horse…)" ([BlendAtlas ARP](https://blendatlas.com/products/auto-rig-pro)). Non-humanoids are placed manually, without the Smart detection ([Superhive ARP](https://superhivemarket.com/products/auto-rig-pro)).
- **Digitigrade legs:** ARP has "3 bones IK for quadrupedal/digitigrade creatures" and "2 or 3 bones IK chains for legs" ([Superhive ARP](https://superhivemarket.com/products/auto-rig-pro)). The exact Limb Options label is UNVERIFIED; it is probably a leg type or bone-count setting.
  - Hind legs: 3 bones.
  - Forelegs: the horse uses 3 bones as well. For dog forelegs, test both 2 and 3.
- **Toes:** ARP leg toes cover dog paws; enable toes in the leg's limb options. Hooves need no toes: just the foot plus a "toes_01"-style tip bone (UNVERIFIED name).
- **Smart IK pole:** ARP 3.77 added one for legs (third-party changelog mirror, UNVERIFIED). Check the official log: [ARP updates log](https://lucky3d.fr/auto-rig-pro/doc/updates_log.html).
- **Paid add-on:** "Auto-Rig Pro: Rig Library" has 24–35 animal presets, from spider to dragon, including Dog/Horse with idle/trot/dig animations. These appear in the "Add Armature" dropdown ([BlenderNation](https://www.blendernation.com/2023/04/30/auto-rig-pro-rig-library-24-rig-presets-for-all-animals-big-and-small/), [Superhive Rig Library](https://superhivemarket.com/products/auto-rig-pro-rig-library)). It is worth buying for Forge: it gives proven reference bone layouts to snap to.
- **Automation:**
  1. Load the preset with `bpy.ops.arp.append_arp` or the equivalent preset op (UNVERIFIED op name).
  2. Move the `*_ref` bones to the joints `joints.py` estimates. Find leg joints from ground contacts and silhouette bend points: the sign change of curvature along the leg axis.
  3. Run Match to Rig.
- **Claws/hooves:** rigid 100% weight to `toes` or `foot`.

**(d) Texture**
- Hoof and claw: low roughness, a separate tint zone, and a keratin gradient (dark root to light tip, made from a UV-V ramp).
- Paw pads: rougher, darker, via a mask channel.
- Fur is out of scope here (done separately).

**(e) Detect / create**
- **Leg count:** connected components of vertices within ε of the ground plane.
- **Joint positions:** the cross-section radius minima along each leg's skeleton. Use a mesh-contraction skeleton, or `appendages.py`'s slice approach.
- **Hooves:** detected by a sharp colour change plus a radius step near the ground; split them off using the colour boundary.
- **Claws:** small tapered rods at toe tips, probably fused. If the AI fused toes into a mitten, generate claws from a claw primitive placed at each toe tip (a procedural asset library); the director confirms.

**(f) Engine**
- **UE5:** Leg IK / foot placement in the AnimBP; Motion Matching can be used if animations exist. Export one root bone at the origin for root motion.
- **Unity:** Humanoid avatar does not apply, so use the **Generic** rig type. Foot IK is custom (Two Bone IK Constraint plus raycast). A 3-bone leg needs Chain IK or a custom solver.

### 1.2 Wings in general: decide the type first
Classify into three types:
- **Feathered:** bird, angel, griffin.
- **Membrane:** bat, dragon, demon.
- **Insect:** flat, rigid, transparent.

Use colour/alpha cues plus the λ3 thinness of the wing sheet:
- Insect wings: thin and nearly transparent or iridescent.
- Membranes: thin between rods (the fingers).
- Feathered: thicker, layered silhouette with a serrated trailing edge.

### 1.3 Birds: feathered wings, feather cards, folding

**(a) Why it matters**
- Folding and unfolding is the signature move. A rigid wing slab looks broken.
- Primaries must spread feather by feather when spread, and stack flat when folded.

**(b) Topology**
- Arm skin: loops at shoulder, elbow and wrist.
- Flight feathers (primaries/secondaries) are separate cards: one quad strip of 2–4 quads per feather along its length, so it can bend.
- Coverts are painted into the base texture or made from very low-poly geometry ([Tripo blog: wings/membranes/feathers topology](https://www.tripo3d.ai/blog/explore/smart-mesh-topology-for-wings-membranes-and-feathers)).
- Examples: a game wing with individual primary/secondary cards was about 10k tris ([Sketchfab game-ready feathered wings](https://sketchfab.com/3d-models/game-ready-realistic-feathered-wings-1e0930b95cb948f29d4437db7c546897)). Bird assets overall run 3k–15k polys ([Coohom parrot guide](https://www.coohom.com/article/optimizing-a-3d-parrot-model-for-games-and-real-time-rendering)).
- Mobile: group feathers into 3–6 cards per wing, or bake them into one alpha-tested wing shape. Low-poly bird packs use grouped flight feathers at Low/Medium LOD and individual ones at High ([CGTrader low-poly birds](https://www.cgtrader.com/3d-models/animal/bird/low-poly-and-realistic-birds-animated)).

**(c) Rig (ARP)**
- The arm limb has a Wings/feathers option:
  - Per-bone feather counts for arm, forearm and hand.
  - "Feather Layers" (rows).
  - "Parent Feathers Layers": layers follow each other.
  - "Add Wings Fold Controller": scaling it folds arm plus feathers. The procedure is: select an arm bone, open Limb Options, enable it, then Match to Rig.
  - Source: [ARP doc via search extract](https://lucky3d.fr/auto-rig-pro/doc/auto_rig.html). Labels are paraphrased; exact casing is UNVERIFIED.
- Bird body:
  - The arm limb becomes the wing.
  - Legs: 3-bone leg (the tarsometatarsus is the third segment).
  - Toes: 4 per foot, with one reversed hallux.
  - Spine: short. Neck: long, possibly Spline IK neck (see 1.7).
  - Tail fan: feather chain bones, or a "tail" limb with a few bones plus feather cards weighted to it.
- A bird preset is mentioned only by a third-party directory ([CGDive ARP](https://addons.cgdive.com/tools/auto-rig-pro)), so treat it as UNVERIFIED. The Rig Library covers birds (UNVERIFIED which ones).
- Weights: each feather card 100% to its feather bone. The arm skin uses normal weights.

**(d) Texture**
- Feather atlas: about 8–16 feather variants in one texture, with alpha for the vane edge, plus normal and roughness.
- AAA: alpha-tested or dithered masked, two-sided, with backside translucency through a thin-surface/foliage model.
- Mobile: alpha-test only, no blending (overdraw); keep the cards few.
- Add a tint mask for plumage variants.

**(e) Detect / create**
- An AI wing is usually a solid slab with feather grooves sculpted in. Feathers cannot be extracted reliably (UNVERIFIED).
- Procedural recreation:
  1. Find the wing's leading-edge rod (shoulder, elbow, wrist) and the trailing-edge outline: the boundary of the wing sheet projected onto its PCA plane.
  2. Sample N points along the trailing edge.
  3. Instance feather cards with Geometry Nodes (Instance on Points along a curve from each bone to the outline point). Aim each card from its root on the arm to its trailing-edge point. Length is the distance; width comes from a profile curve.
  4. Bake the slab's colour onto the cards by projecting from the dense original (Selected to Active bake).
  5. Delete the slab, or shrink it to the covert layer.
- Create ARP feather bones with the same counts. Assign each card to the nearest feather bone by its root position.
- Director clicks once: "feathered: yes / no".

**(f) Engine**
- **UE5:** feathers stay as skinned mesh (fine on AAA). For AAA, a groom-based feather option exists, but cards are standard (UNVERIFIED for Groom feathers).
- **Unity mobile:** keep bones low by sharing feather bones (for example 1 bone per 2–3 feathers). Use alpha clip, and keep feather count small.

### 1.4 Bats and dragons: membrane wings with fingers

**(a) Why it matters**
- Membranes must stretch and fold between finger bones without tearing.
- Close-ups and backlight show veins and translucency.

**(b) Topology**
- Model the leading edge and finger rods first. Membrane loops radiate from them and follow tension lines ([Tripo creature wings guide](https://www.tripo3d.ai/blog/explore/hd-model-creature-membranes-wings-and-translucency-detail-guide)).
- A single-layer membrane avoids self-intersection. Durian (Sintel) hit trouble with a double-layered membrane in cloth sim, and used a shrunk shape key as the taut rest shape ([Blender Durian wing simulation](https://durian.blender.org/production/wing-simulation-or-gaaaaaah)).
- For games: a single-sided membrane plus a two-sided material, or a thin closed shell with a few loops between fingers.
  - Rows of loops between fingers: 6–12 AAA, 3–4 mobile.
  - Trailing edge: scallops in geometry for AAA; alpha for mobile and tattered edges (done separately).

**(c) Rig (ARP)**
- There is no dedicated membrane-wing limb that I could verify (UNVERIFIED).
- Recommended:
  - Use the arm limb for shoulder, elbow and wrist.
  - Add 3–5 extra finger chains:
    - Enable arm fingers, keep index/middle/ring/pinky, and lengthen them, or
    - duplicate bendy-bone/"bbones" chains, or small Spline IK limbs, parented to the hand.
  - ARP limb duplication works via "Duplicate" on a reference bone ([ARP doc](https://lucky3d.fr/auto-rig-pro/doc/auto_rig.html)).
- Membrane weighting: blend between neighbouring finger bones, using Blender's bone heat weights first, then smoothing.
- Add a membrane "stretch" corrective shape key driven by the finger spread angle (a driver on finger rotation) to avoid flat-shading pinches.
- Folding: a custom fold controller (a driver that scales spread across all fingers). The ARP Wings fold controller is built for feathers. Reusing it for fingers is UNVERIFIED.
- Dragon body:
  - Quadruped legs, 3-bone hind legs.
  - Long neck: Spline IK (1.7).
  - Tail: Spline IK or tail limb.
  - Wings: an additional arm pair (ARP limb duplication; centaur/spider-style multi-limb is supported, [Superhive ARP](https://superhivemarket.com/products/auto-rig-pro)).

**(d) Texture**
- Membrane: BaseColor with a vein network, plus a thickness map for translucency (thin = bright when backlit).
- AAA: UE5 Subsurface or Two-Sided Foliage shading model, using thickness as opacity/subsurface.
- Mobile: a fake rim/backlight term in a URP Shader Graph (dot(view, light) × thickness).
- Tattered holes: alpha (done separately).

**(e) Detect / create**
- Membrane = thin sheet (λ3 small) whose boundary includes 3–5 rods (fingers) radiating from a wrist point.
- Detect finger rods as ridge lines on the sheet: high curvature, thicker cross-section. Trace them with geodesic paths from the wrist to boundary tips that have locally maximal distance.
- Place finger bones along those paths.
- If the AI fused the wing to the body or made it too thick:
  1. Flatten it: solidify it to a single layer by taking one side's surface, using the normal-direction split on the sheet.
  2. Re-bake.
- Director clicks: confirm finger tips (one click each, at most 5 clicks per wing).

**(f) Engine**
- **UE5 AAA:** Chaos Cloth on the membrane is possible, with Animation Drive keeping it close to the skinned pose ([UE Clothing Tool](https://dev.epicgames.com/documentation/en-us/unreal-engine/clothing-tool-in-unreal-engine)). Expect wrist/shoulder penetration problems; Durian and DAZ users report the same. Recommend skinning plus corrective morphs as the default, and cloth only as an option.
- **Unity mobile:** skinned only, no cloth.

### 1.5 Fish / aquatic: fins, gills

**(a) Why it matters**
- Swimming is a sine wave down the spine. Fins flutter.
- Gills breathe in idle animations and close-ups.

**(b) Topology**
- Body: evenly spaced loops along the spine, so the sine wave bends smoothly (8–16 body segments).
- Fins: thin sheets with ray loops (one loop per fin ray, or per 2–3 rays).
- Gill slits: 2–3 loops around each slit, so a shape key can open them.
- Budget (working figures): fish 2–10k AAA, 0.5–2k mobile.

**(c) Rig**
- Spine: ARP spine with a high count, plus tail limb. Or the whole body as a Spline IK limb.
- Fins: small "bbones" or tail-type chains of 2–4 bones. Pectoral fins: an arm-like 2-bone chain, or a fan of 3 bones.
- Gills: shape keys `gill_open_L`/`gill_open_R` (a naming proposal), driven by a custom property. Export as morph targets. A cheaper alternative: one "gill" bone per slit, scaling.
- Engine-side sine swim: UE5 Control Rig / AnimGraph Spline IK driven by time; Unity: baked swim animation plus Damped Transform on fins.

**(d) Texture**
- Iridescent scales:
  - AAA: a view-angle (Fresnel) colour shift in the material, plus a tiling scale detail normal.
  - Mobile: a matcap-like ramp.
- Fins: alpha edge plus translucency (thickness).
- Wet look: lower roughness. Gill interior: red, SSS.

**(e) Detect / create**
- Fins = thin sheets on the body or tail (PCA). Gills = repeated parallel grooves behind the head; detect via curvature bands. They often cannot be detected reliably (UNVERIFIED), so the director marks them with one click and Forge cuts the slit loops with knife-project from a procedural curve.
- Rays: generate a fan of bones from the fin root edge to the fin outline.

**(f) Engine**
- UE5 and Unity both fine.
- For schools of fish on mobile, use vertex-shader animation (a sine in the vertex shader, driven by UV.x along the body) instead of skinning. It is cheap and standard (no source verified; UNVERIFIED).

### 1.6 Insects and arachnids: 6–8 legs, mandibles, antennae, exoskeleton plates

**(a) Why it matters**
- Leg gait is procedural in many games ([UE blog: Sumo Digital *Spyder*](https://www.unrealengine.com/tech-blog/sumo-digital-shares-how-it-created-spyder-s-sophisticated-animation-systems)).
- The exoskeleton must not bend like rubber.

**(b) Topology**
- Rigid plate segments as separate meshes or separate shells: head, thorax, abdomen segments, each leg segment.
- Overlapping plates rather than continuous skin. The joints are hidden by membrane rings, a few loops each.
- Mandibles: separate rigid parts.
- Antennae: thin tapered tubes, 4–6 sided, with 6–12 segments.
- Budget: spider 5–20k AAA, 1–4k mobile.

**(c) Rig (ARP)**
- Legs: "duplicate or remove limbs… spiders, centaurs" ([Superhive ARP](https://superhivemarket.com/products/auto-rig-pro)). Use leg limbs duplicated 3 or 4 times per side; 3-bone legs suit arachnids.
- ARP side naming: `.l`/`.r` plus a duplicate suffix such as `_dupli_001` (UNVERIFIED suffix format).
- Mandibles/chelicerae: 1–2 bone chains (bbones or tail-type limb, deform), mirrored.
- Antennae: 4–8 bone chains (tail-type limb or Spline IK).
- Weights: 100% rigid per plate. Do this automatically by assigning each separated shell to its nearest bone, with no blending.
- Abdomen: 1–3 bones for a breathing/pulse scale.

**(d) Texture**
- Chitin: low roughness, clear-coat look.
  - UE5 AAA: Clear Coat shading model.
  - Unity mobile: smoothness plus a specular boost.
- Iridescence: a thin-film ramp by view angle.
- Hairs/setae: tiny alpha cards on AAA, normal map on mobile.
- Tint mask for faction variants.

**(e) Detect / create**
- Legs: the ground-contact cluster count from 1.1. Joints: radius minima. Insect leg joints are pinched, so they are easy to find.
- Plates: segment the mesh by sharp concave creases (dihedral angle threshold in bmesh) into shells, then split. AI meshes often fuse plates; a crease-based split helps there.
- Antennae/mandibles: thin rods on the head (section 0.1).

**(f) Engine**
- **UE5:** Control Rig procedural leg placement plus FBIK ([UE FBIK dragon blog](https://www.unrealengine.com/en-US/blog/full-body-ik-procedural-dragon-animations)).
- **Unity:** Two Bone IK Constraint per leg with a raycast target (Animation Rigging). Mobile: baked cycles.
- Bone counts climb with 8 legs × 4 bones plus extras, so check mobile limits on target devices (no verified hard cap).

### 1.7 Serpents / nagas: long spines, Spline IK

**(a) Why it matters**
- S-curve slither. Coiling. Naga = human torso plus a snake lower body.

**(b) Topology**
- Even loops along the full length, about 1 loop per 0.5–1 body diameter.
- Belly scutes as a texture or as plate loops.
- Naga join: dense loops at the hip/tail transition.

**(c) Rig (ARP)**
- **Spline IK limb:**
  - "dedicated to rig ropes, tentacles…" ([ARP doc](https://lucky3d.fr/auto-rig-pro/doc/auto_rig.html)).
  - Settings: "IK Spline Count" (bone count), Deform toggle, optional FK chain.
  - IK-FK switch and snap, "Smoothness" parameter, Twist target ([ARP updates log](https://lucky3d.fr/auto-rig-pro/doc/updates_log.html)).
  - 3.72 added an "Advanced" mode with master/inter/individual controllers.
  - 3.73 added "Add Tail Bone" and "Preserve Shape" (third-party changelog mirror; check against the official log).
- **Long neck:** add a Head limb and a Spline IK limb. Enable "Add Tail Bone" (Limb Options > Advanced), then parent the neck ref bone to the spline tail ref bone ([ARP doc extract](https://lucky3d.fr/auto-rig-pro/doc/auto_rig.html)).
- **Naga:** keep the ARP human preset, disable the legs (ARP "Disable", not delete), and add a Spline IK limb from the pelvis.
- Bone count: 20–40 bones AAA, 8–16 mobile. Export the deform bones; in the engine, run Spline IK on them again.

**(d) Texture**
- Scales: a tiling detail normal plus a scale-pattern albedo. Belly/back tint mask.
- AAA: a scale-edge mask for iridescence or specular highlights.

**(e) Detect / create**
- A rod longer than 3× body width at the pelvis means a serpent tail. Its centreline comes from the slice centroids (already in `appendages.py`). Fit a curve and create Spline IK ref bones along it.

**(f) Engine**
- **UE5:** Spline IK node, or Control Rig "Spline From Points" / Fit Chain on Curve (UNVERIFIED node names). Slither via a path-following spline.
- **Unity:** no built-in spline IK. Use Chain IK, or a custom "follow the leader" script (each bone follows the previous one's history), or baked animation.

### 1.8 Tentacles (Spline IK, many segments)

**(a)–(b)**
- Reaching, curling, suckers in close-ups.
- Tapered tube, 8–12 sides AAA, 6 mobile. Loops spaced evenly or tightening toward the tip.
- Suckers: normal map, or geometry on AAA only.

**(c) Rig**
- ARP Spline IK limb per tentacle (Duplicate). The 3.78 release fixes "parenting to the tail of an IK Spline… with multiple IK Splines" (third-party mirror, UNVERIFIED).
- About 12–24 bones each AAA, 6–10 mobile.
- Curl shape keys are optional.

**(d) Texture**
- Wet SSS skin; sucker AO and normal; tint gradient root to tip (UV-V ramp).

**(e) Detect / create**
- Many similar rods from one region form a "radial cluster". Auto-create N Spline IK limbs via a loop over ARP's duplicate op, then fit each to its centreline.

**(f) Engine**
- **UE5:** Spline IK node plus AnimDynamics for idle sway ([AnimDynamics doc](https://dev.epicgames.com/documentation/en-us/unreal-engine/animation-blueprint-animdynamics-in-unreal-engine)).
- **Unity:** Chain IK toward a target plus a procedural tail script. Running IK before the damping logic matters ([Unity forum on Tail Animator ordering](https://discussions.unity.com/t/tail-animator-procedural-tail-animation-for-tentacles-simple-capes-squids-and-more/708463?page=7)).

### 1.9 Multiple heads and arms (centaur, hydra, multi-armed)

**(a)–(b)**
- Each head needs its own neck loops and its own facial set (eyes, eyelids, mouth). The mouth interior is in a separate report.
- Centaur: the human torso blends into the horse withers through a dense loop band.

**(c) Rig (ARP)**
- Duplicate head and neck limbs. A changelog fix mentions "more than 2 head limbs not aligning when Match to Rig", which suggests multiple heads are supported ([ARP updates log](https://lucky3d.fr/auto-rig-pro/doc/updates_log.html), via search extract).
- Hydra necks: each Head plus a Spline IK neck (see 1.7).
- Centaur: human spine, arms and head on a quadruped base. ARP marketing cites centaurs and links a tutorial ([Superhive ARP](https://superhivemarket.com/products/auto-rig-pro)).
- Extra arms: Duplicate on an arm ref bone.
- Facial rig on duplicated heads: UNVERIFIED that ARP's facial features duplicate per head. Plan for primary-head full face plus secondary heads with jaw plus eyelid bones only, or per-head shape-key sets with suffixes (`_h1`, `_h2`).

**(d) Texture**
- Shared atlas.
- Per-head emissive eyes in a mask channel, so heads can be lit individually (for example "active head" gameplay).

**(e) Detect / create**
- Head blobs: clusters with a near-spherical PCA, or face features from the image. `appendages.py` flags a second head as a big blob at a rod end.
- The director confirms "this is a head".

**(f) Engine**
- **UE5:** per-head LookAt / Aim nodes; morph target names must be unique per head.
- **Unity:** Multi-Aim Constraint per head.

### 1.10 Scales and plates
- **(a)** Close-up readability; armour feel.
- **(b)**
  - Small scales: texture only (normal plus detail normal).
  - Large plates (pangolin, armadillo, stegosaurus): separate rigid meshes, overlapping, 100% per bone.
  - Medium (dragon belly scutes): loops follow the plate boundaries.
- **(c)** Plates follow spine bones. Big dorsal plates get their own bone if they flare (shape key or bone).
- **(d)**
  - Tiling detail normal with mask (UE5: material detail-normal blend; URP: Detail Normal plus Detail Mask, [URP Lit](https://docs.unity3d.com/Manual/urp/lit-shader.html)).
  - Scale-edge mask for wear.
  - Tint mask.
- **(e)**
  - Detect sculpted scales by high-frequency curvature (bake curvature from the dense mesh). These go to normal map, not geometry. Sharp-crease segmentation finds big plates (see 1.6).
  - Procedural: a Geometry Nodes scale pattern (Voronoi-based) for the detail normal when the AI mesh is smooth.
- **(f)** Mobile: drop the detail normal at lower LODs.

### 1.11 Horns, antlers, tusks, spikes
- **(a)** Silhouette identity. They must not bend.
- **(b)**
  - Separate mesh, or a hard-boundary region.
  - Ring loops only at the base. 300–2k tris AAA, 100–400 mobile.
  - Antlers: branching tubes (Tripo fuses them; OK if rigid).
- **(c)** 100% weight to the `head` bone. A separate bone only if it breaks, detaches or animates (rams).
- **(d)**
  - Keratin/bone gradient root to tip (UV ramp), ridges in the normal map, low-to-mid roughness. Antlers: velvet variant through a tint mask.
- **(e)**
  - Already detected by `appendages.py` (top of head = horns).
  - Rigid test: weight-paint check. After auto-weights, any vertex in the horn group with a non-head weight is clamped to head = 1.0. This is a pure script.
- **(f)** Sockets in UE5 / child transforms in Unity allow swappable horns: export the horn as a separate static mesh plus a socket bone `horn_socket_l` (naming proposal).

### 1.12 Manes
- Fur and hair cards are covered separately. Specific to animals:
  - Mane cards weighted to the neck spline.
  - Plus 2–4 sway bones along the crest, driven by AnimDynamics (UE5) or Damped Transform (Unity).
  - Tint mask shared with the body.

### 1.13 Glowing / emissive features (eyes, runes, magic)
- **(a)** Readability in dark scenes, gameplay telegraphs (charging attack), close-ups.
- **(b)**
  - Eyes: separate eyeball meshes (the eye/eyelid report covers anatomy).
  - Runes: no geometry needed, mask only, unless they are raised (normal).
  - Crystals: separate meshes.
- **(c)**
  - Usually none. Animated intensity goes through a material parameter; a custom property in Blender exported as a curve is UNVERIFIED for FBX.
  - Better: drive emissive in the engine:
    - UE5: Material Parameter Collection or dynamic material instance.
    - Unity: `MaterialPropertyBlock` `_EmissionColor`.
- **(d)**
  - Emissive mask (one channel in a packed mask) times a tint colour times an intensity parameter.
  - AAA: scrolling or noise "pulse" in the material; bloom handles the glow.
  - Mobile: keep emission in the same shader (URP Lit Emission); avoid extra passes. Bloom is costly on low-end mobile (UNVERIFIED in general).
- **(e)**
  - Detect from the image or texture: pixels with high value and saturation that do not match the lighting.
  - In Blender: threshold the baked BaseColor in HSV (V > 0.9 and saturated, isolated islands) to build an emissive mask. The director confirms or paints with one stroke.
  - Runes can also be generated procedurally: a decal/texture stamp from a rune library on a UV island.
- **(f)** UE5 Lumen makes emissive surfaces contribute light on AAA (minor). Unity: emission does not light the scene in URP without baking.

### 1.14 Elemental effects (fire hair, smoke, magic auras): VFX versus mesh
- **(a)** These cannot be done well as static mesh. They are animated effects.
- **(b) Topology:**
  - Keep a low "base shape" mesh, a hair-shaped volume, using flow-mapped panning UVs. UV direction: root (V=0) to tip (V=1).
  - Spawn points for particles come from the mesh itself.
- **(c) Rig:** sockets or bones where effects attach (`fx_head`, `fx_hand_l`, ... a naming proposal). Export these as bones without weights (non-deform bones need to be exported; check ARP export settings, UNVERIFIED option).
- **(d) Texture:** the base mesh uses an animated material: panning noise times a gradient along V, emissive, additive or alpha-clip. Flipbook textures for flames.
- **(e) Detect / create:**
  - The AI mesh will have a solid sculpted flame blob.
  - Detect it by colour (fire hues plus brightness, as in 1.13) and shape (flame-like, upward spikes).
  - Replace: keep a simplified shell, set UVs along the up-axis, and assign the "Forge_Fire" shader template. Export a spawn-mask vertex colour for engine particles.
  - The director chooses "keep as stylised mesh" or "replace with effect".
- **(f) Engine:**
  - **UE5 Niagara:** the Skeletal Mesh data interface samples the mesh surface or named sampling regions ([UE Niagara SkelMesh DI](https://dev.epicgames.com/documentation/unreal-engine/API/Plugins/Niagara/UNiagaraDataInterfaceSkeletalMes-)). There is a community tutorial on fire and smoke from an animated character ([UE forum tutorial](https://forums.unrealengine.com/t/community-tutorial-niagara-fluids-tutorial-character-on-fire-simulation-skeletal-mesh-vfx-in-unreal-engine-5-3/1315552)). Pitfall: particles sampled only on spawn do not follow animation; update them or use sockets.
  - **Unity mobile:** use the built-in Particle System. VFX Graph needs compute shaders and supports only some high-end mobile devices ([VFX Graph system requirements](https://docs.unity3d.com/Packages/com.unity.visualeffectgraph@17.3/manual/System-Requirements.html)). Particle System Shape module = Skinned Mesh Renderer, for emission from the mesh.

### 1.15 Shape-shifting and morphing
- **(a)** Transform sequences (human to wolf), puffing up, inflating.
- **(b)** For morph targets, both shapes need identical vertex count and order. Forge produces this by:
  - retopologising form A, then
  - shrinkwrap-projecting a copy onto dense form B (Shrinkwrap modifier, or Surface Deform plus a manual correction pass), then
  - storing it as a shape key.
  - If A and B differ greatly (human vs wolf), use a mesh swap hidden by VFX instead. This is standard practice (UNVERIFIED).
- **(c)**
  - Two skeletons: blend through a shared superset skeleton, or swap actors at the VFX peak.
  - Shape keys: name them `morph_<target>` (a proposal). For faces, keep ARKit-52 names as in the facial report.
- **(d)** Two texture sets blended by a material parameter (dissolve or noise mask); emissive seam on the transition.
- **(e)**
  - Needs two AI generations from the same image pose (Tripo outputs A and B).
  - Automate: align B to A (ICP), project A's topology onto B, bake B's colour onto A's UVs as a second texture set.
  - Director confirms the alignment visually.
- **(f)**
  - **UE5:** morph targets via `SetMorphTarget` / curves.
  - **Unity:** `SkinnedMeshRenderer.SetBlendShapeWeight`.
  - Mobile: few blend shapes, and only on the visible LOD (cost guidance not verified).

---

## 2. Checklist of commonly missed creature parts (feed into the parts detector)
Eyelids and nictitating membrane (reptiles/birds, a shape key) · ear inner surface and ear twitch bones · nostrils (flare shape key) · whiskers · dewclaw · tongue and mouth bag (separate report) · beak (rigid upper, jaw-bone lower) · cheek pouches · throat sac/dewlap (inflate shape key) · gills · crest/frill (fan bones) · tail tip tuft · belly scutes · hoof frog and fetlock hair · claw sheaths · eye shine (emissive/tapetum, a material) · wing claw/thumb on bat and dragon wings · feather coverts · pupils (slit vs round, through a material parameter) · teeth · horn base skin ring · spikes along the spine (rigid, per spine bone) · sockets for gear and VFX (`fx_*`).

## 3. Automation summary

**Fully procedural:**
- Appendage classification (PCA plus radius)
- Ground-contact leg count
- Rigid weight clamp for horns, claws and plates
- Crease-based plate splitting
- Spline IK fitting to centrelines
- Feather card instancing with Geometry Nodes
- Thickness, curvature and AO bakes
- Emissive mask from colour
- UV-V gradients for horns, tentacles and flames

**Needs an AI-generated part or second generation:**
- Morph form B
- Separate feather or claw assets when AI fused them (or use a Forge procedural library)
- Clean membranes when the AI made thick slabs

**Needs one director click:**
- Feathered vs membrane vs insect wing
- Membrane finger tips
- Gill location
- "Is this a head"
- Fire: keep as mesh or replace with VFX
- Confirm each detected part's label

**Engine side, not exported from Blender:**
- Spline IK, AnimDynamics, cloth, Niagara/Particle System, Control Rig procedural legs
- Bendy bones and spline controllers do not survive FBX, so only the deform chains go out.

## 4. Items to verify in ARP 3.79.17 before coding
1. Exact Limb Options labels:
   - 3-bone leg option
   - Feather count fields
   - "Feather Layers"
   - "Parent Feathers Layers"
   - "Add Wings Fold Controller"
   - "IK Spline Count"
   - "Add Tail Bone"
   - "Preserve Shape"
2. bpy operator names for:
   - Add Armature preset
   - Duplicate limb
   - Disable limb
   - Match to Rig (`bpy.ops.arp.match_to_rig` is believed correct; UNVERIFIED)
3. Duplicated-limb bone naming suffix.
4. Whether the facial features (eyelids, lips, eyebrows) can be added to a duplicated head.
5. Whether a bird preset ships with ARP or only with the paid Rig Library.

To check these, allow lucky3d.fr in the session's network settings, or read the ARP Python source in the user's add-on folder (`auto_rig_pro/src/*.py` on the Windows machine).

## Sources
- ARP doc (auto_rig): https://lucky3d.fr/auto-rig-pro/doc/auto_rig.html
- ARP updates log: https://lucky3d.fr/auto-rig-pro/doc/updates_log.html
- ARP FAQ: https://www.lucky3d.fr/auto-rig-pro/doc/_sources/faq.rst.txt
- Superhive ARP: https://superhivemarket.com/products/auto-rig-pro
- BlendAtlas ARP: https://blendatlas.com/products/auto-rig-pro
- CGDive ARP: https://addons.cgdive.com/tools/auto-rig-pro
- ARP Rig Library: https://www.blendernation.com/2023/04/30/auto-rig-pro-rig-library-24-rig-presets-for-all-animals-big-and-small/
- ARP Rig Library on Superhive: https://superhivemarket.com/products/auto-rig-pro-rig-library
- Tripo wings/membranes/feathers topology: https://www.tripo3d.ai/blog/explore/smart-mesh-topology-for-wings-membranes-and-feathers
- Tripo creature wings guide: https://www.tripo3d.ai/blog/explore/hd-model-creature-membranes-wings-and-translucency-detail-guide
- Sketchfab feathered wings: https://sketchfab.com/3d-models/game-ready-realistic-feathered-wings-1e0930b95cb948f29d4437db7c546897
- CGTrader low-poly birds: https://www.cgtrader.com/3d-models/animal/bird/low-poly-and-realistic-birds-animated
- Coohom parrot optimisation: https://www.coohom.com/article/optimizing-a-3d-parrot-model-for-games-and-real-time-rendering
- Blender Durian wing simulation: https://durian.blender.org/production/wing-simulation-or-gaaaaaah
- UE Clothing Tool: https://dev.epicgames.com/documentation/en-us/unreal-engine/clothing-tool-in-unreal-engine
- UE AnimDynamics: https://dev.epicgames.com/documentation/en-us/unreal-engine/animation-blueprint-animdynamics-in-unreal-engine
- UE Spline IK (4.26 ref): https://docs.unrealengine.com/4.26/en-US/AnimatingObjects/SkeletalMeshAnimation/NodeReference/SkeletalControls/SplineIK
- UE Control Rig spline rigging: https://dev.epicgames.com/documentation/unreal-engine/control-rig-spline-rigging-in-unreal-engine
- UE FBIK dragon blog: https://www.unrealengine.com/en-US/blog/full-body-ik-procedural-dragon-animations
- UE Sumo Digital *Spyder* blog: https://www.unrealengine.com/tech-blog/sumo-digital-shares-how-it-created-spyder-s-sophisticated-animation-systems
- UE Niagara Skeletal Mesh data interface: https://dev.epicgames.com/documentation/unreal-engine/API/Plugins/Niagara/UNiagaraDataInterfaceSkeletalMes-
- UE forum, Niagara character fire tutorial: https://forums.unrealengine.com/t/community-tutorial-niagara-fluids-tutorial-character-on-fire-simulation-skeletal-mesh-vfx-in-unreal-engine-5-3/1315552
- Unity ChainIK: https://docs.unity3d.com/Packages/com.unity.animation.rigging@1.1/manual/constraints/ChainIKConstraint.html
- Unity Learn Damped Transform: https://learn.unity.com/tutorial/using-animation-rigging-damped-transform
- Unity forum, Tail Animator: https://discussions.unity.com/t/tail-animator-procedural-tail-animation-for-tentacles-simple-capes-squids-and-more/708463?page=7
- Unity VFX Graph system requirements: https://docs.unity3d.com/Packages/com.unity.visualeffectgraph@17.3/manual/System-Requirements.html
- Unity URP Lit: https://docs.unity3d.com/Manual/urp/lit-shader.html
- Unity URP Complex Lit: https://docs.unity3d.com/Manual/urp/shader-complex-lit.html
- Unity SkinnedMeshRenderer.quality: https://docs.unity3d.com/ScriptReference/SkinnedMeshRenderer-quality.html
- Unity QualitySettings.skinWeights: https://docs.unity3d.com/ScriptReference/QualitySettings-skinWeights.html
- Unity 2018.3 SkinnedMeshRenderer manual: https://docs.unity3d.com/cn/2018.3/Manual/class-SkinnedMeshRenderer.html
