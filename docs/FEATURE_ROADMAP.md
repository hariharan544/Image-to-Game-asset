# Part A — Critique of the Forge Feature Roadmap

I checked the modules that exist today (`blender_scripts/forge_bpy/`: appendages, joints, density, metrics, rescue, retopo, uv, bake, skin, arp_rig, finalize, cleanup, fixture, addon_probe; `blender_addon/forge_send/`: steps, stages_ui, stages_late, geometry). The draft is detailed. Its main faults are in build order and in a missing early "ground truth" layer, not in the features it lists.

## A1. Vital features, anatomy and mechanics that are missing

**Ground truth (nothing later works without it)**
1. **Real-world scale, forward axis, ground plane and origin.** No step sets the asset's height (a bull is about 1.5 m at the shoulder), its forward axis (Blender −Y, UE +X, Unity +Z), feet on Z=0 or the pivot. Capsules, physics mass, texel density in px/m, animation retargeting and the "scale 1" QA badge all depend on this.
2. **Skeleton conventions per engine.** The draft has no rules for bone roll or orientation, no `root` bone at the origin, and no UE `ik_foot_root` / `ik_hand_root` / `ik_hand_gun` bones that Lyra and GASP expect. Nothing maps ARP `.l/.r` names to engine `_l/_r`. Without this, retargeting fails silently.
3. **VLM asset brief taken from the input image.** This would give species, body plan, limb count, foot type, materials and a list of expected parts. The classifiers currently guess blind. A brief would turn most "1C" confirmations into "A".
4. **Asymmetric assets.** Symmetry alignment is treated as always on. A one-clawed crab, asymmetric armour or a damaged mech needs a "no symmetry / partial symmetry" route, or QR X-symmetry and mirrored weights will damage it.
5. **A body-plan template library.** Biped, quadruped, hexapod (dragon: 4 legs + 2 wings), bird, serpent or limbless, fish, insect or arachnid (6 or 8 legs, segmented exoskeleton), octopus, flyer, wheeled, tracked and walker mech. This decides rig, stance, physics and animation. Today it is spread across separate features with no single selector.

**Anatomy**
6. **Neutral stance for non-bipeds.** "A-pose normalisation" has no meaning for a quadruped, snake or bird. Each body plan needs its own neutral stance: legs straight under the body, head forward, tail relaxed, wings folded or spread.
7. **Foot type.** The draft lists plantigrade, digitigrade and multi-leg legs but not unguligrade. The bull has **cloven hooves (two rigid digits plus dewclaws)**. Paw pads and claws are missing too, and so are foot-roll pivots (heel, ball, toe tip) for foot IK and the foot-slide badge.
8. **Spine, neck and tail segment counts** taken from body length. Horses and giraffes need long necks and serpents need many spine bones. ARP neck, spine and tail counts must be set automatically.
9. **Quadruped shoulder girdle.** Scapula slide and the chest "sling" are missing. Without them the front legs of every quadruped collapse at the shoulder.
10. **Breathing.** No chest or belly breathing bone or shape key, and no idle breathing loop. Every creature needs one.
11. **Hands.** Finger count is not always 5 (3-fingered creatures, mitts). There is no thumb opposition axis, no per-finger curl axis or bone roll for retargeting, and no nails or claws as rigid tips.
12. **Eyes.** Pupil shape (round, horizontal bar for bovines and goats, vertical slit), lateral eye placement with its own look-at limits, eye count (spiders, multi-eyed), lidless eyes (fish, snakes) and an eye pivot fitted to the eyeball centre.
13. **Jaw hinge location.** The temporomandibular pivot should be estimated from landmarks and the side silhouette. If it is wrong, every jaw-open shape breaks. Lip-less mouths (beaks, mandibles) need a different mouth-bag rule.
14. **Ear interior and ear base.** Ear rotation pivot plus thin-ear SSS. Only SSS is listed.
15. **Content and anatomy flags.** Genitals, udders and similar anatomy should be detected and flagged for the rating board, with an option to smooth them over. Tripo sometimes generates them.

**Mechanical**
16. **Vehicle data the engines require.** Wheel bones at the wheel centre with radius and width in the manifest (UE Chaos Vehicle, Unity WheelCollider), suspension travel, centre of mass, steering axis and the drive or steer flag per wheel.
17. **Mech walker legs.** Reverse-joint and multi-leg IK for machines, plus a gait test.
18. **Rotors and propellers.** A spin bone plus a blurred-disc card swap. Headlights and light sockets. Turret yaw and pitch limits with aim bones exposed to gameplay. Recoil and slide clips for weapons.
19. **Seats, riders and mounts.** Seat, saddle and rider sockets with a rider pose check (relevant to the bull as a mount).

**Pipeline and production**
20. **Mobile draw calls: material and texture atlas merge.** Mobile needs one material and one draw call per character where possible. The draft adds material slots, emissive slots, glass slots and interior slots, but nothing merges them back for mobile.
21. **Starter animation set.** A "real-animation test" exists, but no deliverable set does. A shipped game asset needs idle and breathing, locomotion (in-place and root motion) and hit or death clips. For quadrupeds there is almost no licence-safe library, so the procedural gait generator becomes a deliverable, not just a test.
22. **Versioning, provenance and resume.** Per-stage snapshots with rollback, crash-safe resume (Blender 5.3 with three heavy add-ons will crash), and stored prompt, seed and Tripo task ID plus licence record for each asset.
23. **Fixture set from day one.** Only the bull is tested until the scope gate. Body-plan bugs hide until late. The draft needs at least a humanoid, the bull, a flyer, a serpent and a mechanical prop or vehicle from M1.
24. **Time-per-asset target and progress UI.** No target is defined, such as "≤ 30 director-minutes per creature". Without one, approval sheets keep growing.

## A2. Wrong build-order dependencies

1. **Edit records are listed as a foundation but scheduled in M10+.** Section 1 says every change replays after retopology. Sockets, secondary bones, helper bones and partial re-retopology all "Need: Edit records", and they ship in M5–M9. Fix: core edit records go in M1. Replay for each tool is added as each tool ships.
2. **The face is built before the body is cleaned.** M2 cuts eyes and mouth, then M4 runs the fusion cut/cap, stance normalisation and hidden-surface work, which move and rebuild the same mesh. The roadmap's own top risk is "repair will close new cuts". Fix: body repair and stance first, face cuts after.
3. **The face rig comes before the body rig.** The M3 bull test needs "ear pin" and "creature jaw", but ear chains, the Universal rig and the creature jaw are in M4. ARP's facial module also needs the final base rig (and for a bull, the dog or horse preset). Fix: body and creature rig first, face rig after.
4. **Part segmentation is marked vital (step 2) but built in M8.** Rigid split, horns and hooves (M4), card classification (M6) and region detection (M7) all depend on it. Fix: move it to the body milestone.
5. **The hard/organic classifier is in M8, but M4 needs it** for horn and hoof rigid split and keratin. It is part of the part classifier. Fix: build it there.
6. **Finger and toe repair is in M10+,** yet target-aware ARP limb options (fingers, metacarpals) need it, and the humanoid fixture at the scope gate cannot pass without it. Mitten hands are Tripo's most common humanoid defect. Fix: body milestone.
7. **Hidden-surface regeneration is in M10+,** yet A-pose or stance normalisation (M4) opens armpits and the crotch, and the cloth weight transfer feature depends on it. Fix: ship the procedural and template tiers with cut/cap. The AI tier can come later.
8. **Thin-sheet classification runs after retopology.** Step 7 has a "card branch for thin sheets", but the thin-sheet classifier is step 8. A cape must be routed away from QR before QR runs. Fix: classify in Assemble (part kind "card"), rebuild in the retopology branch, and keep step 8 for generated cards only (fur, lashes, feathers).
9. **Eyelash and eyebrow cards ship in M3, but card alpha bake, preview materials and engine alpha-cutout are M6.** Fix: lashes go in the card milestone.
10. **Engine import is last (M9).** For eight milestones the director drops FBX files into the engines and sets them up by hand, which a non-modeler cannot do. Alpha-cutout material setup (M6) and the "UE normal flipped" bull test (M1) also cannot be checked without an import pipeline. Fix: a minimal headless UE and Unity import with validation V1–V5 in M1, extended by each milestone.
11. **The budget validator (M1) "Needs: Skinned LODs" (M9) for "one-click reduce".** This is circular. Fix: M1 reports only; reduce comes with LODs.
12. **Validation V1–V13 is in M9** while "failing assets stop before the director sees them" is a rule for every step. Fix: build validation incrementally from M1.
13. **Retractable parts need a geometry stage.** Claws, stingers and tongue extension need a sheath or pocket cut and cap before retopology (like the eye pocket). The draft only has a rig-stage feature for them. Fix: add pocket geometry to Repair.
14. **Shape keys are not protected against later geometry edits.** Partial re-retopology after expressions exist destroys morphs. Fix: shape-key transfer is required by partial re-retopology and the edit-record replay.
15. **Toon proxy normals (Bake/Colour step) need seam weld (Rig step).** That order is backwards. Fix: seam weld normals (geometry part) move to Retopology, and weight and shape-key falloff stay in Rig.
16. **Dismemberment cut loops (retopology, step 7) need the damage manifest, which ships in M10.** Fix: the cut list is a step-2 tag (already there). The manifest section goes in M1's manifest schema.
17. **Scale and orientation come after nothing.** They must happen before texel density, joint estimation thresholds and physics. They are missing entirely (see A1).

## A3. Steps that would need modelling, rigging or art skill

| Draft wording | Why a non-modeler can't do it | Corrected interaction |
|---|---|---|
| Segmentation "lasso or bisect fallback" | Drawing a lasso on a 3D surface and placing a bisect plane are modelling actions | Click a seed on the part; Forge grows the region; a single "cut height" slider; 3 candidate cuts as thumbnails |
| "Regenerate with a corrected image" | Fixing the image needs 2D art skill | Forge edits the image itself (pose/separation edit model or Tripo multiview); director picks 1 of 3 |
| Quadruped legs "ADJ (confirm joints)" | Placing joints in 3D is rigging | Side and front 2D silhouettes with snap-to-anatomy dots; drag in 2D only, mirrored automatically |
| Eye aperture "approve outline" with no option if wrong | Editing a curve on a mesh is modelling | 3 candidate outlines + "wider / narrower" slider |
| Hidden-surface regen "ADJ (> 5% of a part)" | Undefined; implies sculpting | Choose 1 of 3 (procedural, template, AI); never sculpt |
| Cloth sim masks (Max Distance) | Weight-painting skill | Automatic from distance to body + preset (tight / loose / flowing) |
| Partial region re-retopology "1C" | Choosing a region on the mesh needs a selection skill | Click a labelled part from the part overlay |
| Inverted-hull outline "erase brush" | Acceptable, but a brush on a mesh is close to texture painting | Keep, but default to automatic width from curvature; brush is last resort |
| ARP ref placement when landmarks fail | Moving ARP reference bones is rigging | 2D overlay dots on front and side renders, mirrored |
| Face pose sheet "redo" | Redo implies sculpting a shape key | Per-shape strength slider + "regenerate with stronger/weaker profile" |
| "Template ABPs are built by hand once", PhysicsAsset hand-tuned fallback | Engine editor work | Mark as **developer-only, once per engine version**; never shown to the director |
| Fur "AI (guide generation)" with no fallback | Combing guides is grooming | Fallback: direction field from colour-image flow + 3 presets (sleek / shaggy / curly) |

---

# Part B — Corrected roadmap

# Forge Feature Roadmap

*For the creative director and the developer. Repo: `/home/user/Image-to-Game-asset`. Target setup: Blender 5.3, Quad Remesher (QR), UVPackmaster 4 (UVPM), Auto-Rig Pro 3.79.17 (ARP), Tripo, Unreal 5 (AAA) and Unity URP (mobile).*

---

## 1. What is missing today, and the rule we follow

Forge already turns an image into a retopologised, UV'd, baked, rigged and exported asset. It already has an appendage finder (tail, ears, horns), a joint estimator, a detail density map, a shape-loss check and thin-part rescue. These are the gaps:

- **Ground truth.** Forge has no real-world scale, forward axis, ground plane or origin rule, and no per-engine skeleton conventions (bone roll, root bone, IK bones, `_l/_r` names). It has no body-plan template and no brief describing what the image shows. Retargeting, physics and texel density all rest on these.
- **Face.** Eyes and mouth come out sealed and painted on. There are no eyeballs, lids, mouth interior, teeth or tongue. Pupil shape, lateral eyes and the jaw hinge position are not modelled. Face bones are switched off, so nothing can blink, talk or snarl.
- **Creature body.** Tails and ears are detected, but no bones are added for them. There are no quadruped, hexapod, serpent or insect body plans. There is no neutral stance for non-bipeds, no scapula slide, no breathing, and no cloven hooves, paws or claws. Nothing retracts. Horns and hooves are skinned like flesh.
- **AI defects.** Tripo fuses arms to torsos, legs to each other and capes to backs. It fuses fingers into mittens, hides surfaces and bakes in lighting. Today Forge copies these faults into the final asset.
- **Thin things.** Fur, manes, lashes, membranes, capes and fins come out as thick slabs. There are no alpha cards.
- **Texture definition.** There are no curvature or thickness maps, tint masks, wear, region editing, correct per-engine packing, seam handling or mobile material atlas merge.
- **Mechanical parts.** Hard edges get softened. There are no pivots, hinges, wheels (with engine vehicle data), walker legs, rotors, seats, collision or sockets.
- **Animation.** There is no starter clip set: idle, breathing, locomotion, hit or death.
- **Engine side.** The FBX is dropped in and the rest is set up by hand. There are no physics bodies, materials, import settings, validation or in-engine preview.
- **Production safety.** There are no stage snapshots, crash-safe resume, provenance (prompt, seed, Tripo task, licence) or director-time budget.

**Rule for every feature, in order of preference:**
1. **Automatic.** Forge works it out from the brief, mesh, colour, landmarks and skeleton.
2. **One click.** Forge shows its guess as a coloured overlay or thumbnails; the director clicks Accept or picks from 2–3 options.
3. **AI part.** Forge asks Tripo, a VLM, an image-edit model or ComfyUI to generate or complete a missing piece, then aligns it automatically.
4. **You adjust.** Only when the first three fail: dots dragged on a **2D** front or side render, a slider, or a click on a labelled part. Every adjustment has before/after and Undo.

The director never edits topology, weights, bones in 3D, curves or nodes, and never paints masks. Work that must be done in an engine editor is marked **developer-only, once per engine version**. Every change is stored as an edit record, so it replays after retopology and only invalidates approvals for the region it touches. **Target: ≤ 30 director-minutes per creature, ≤ 15 per prop.** Each step shows its click count.

---

## 2. Updated step-by-step workflow

Steps marked **(NEW)** are new panel steps. Everything else extends an existing step. Order matters: nothing after step 4 may change the silhouette, because later steps cut into the mesh.

| # | Step | What happens (new capabilities in **bold**) |
|---|------|------|
| 1 | **Image, brief and generate** | **VLM asset brief**: species or object, **body plan** (biped / quadruped / hexapod / bird / serpent / fish / insect-arachnid / tentacled / flyer / wheeled / tracked / walker / prop), limb and finger count, foot type, eye type, materials, expected parts, real-world size guess. **Image cleanup** (background removal). **Tripo preflight**: stance prompt for each body plan, multi-view input, cape and held items generated separately. **Auto-corrected image**: an image-edit model separates arms and fingers and the director picks 1 of 3, then regenerates. **Provenance record** (prompt, seed, Tripo task ID, licence). |
| 2 | **Scale, orientation and symmetry** (NEW) | **Real-world height** from the brief (one slider to confirm). **Forward axis**, **ground plane (feet on Z=0)** and **origin**. **Symmetry plane align** with an **asymmetric / partial symmetry** option. |
| 3 | **Assemble parts** | Split loose parts, then **Tripo segmentation** with a **click-a-seed region grow and cut-height slider** fallback, plus **joint caps**. **Temporary skeleton from the body-plan template plus per-vertex part labels**. **Part kinds**: body / prop / retractable / card / mechanical / rigid (horn, hoof, beak, claw, nail) / cloth / armour / hair. **Part classifier**: shape (PCA plus radius profile), hard vs organic, material class (opaque, glass, gel, ghost, emissive). **Thin-sheet / card classifier** (capes, membranes and fins are routed to cards here, before QR). **Asset class**: static, mechanical, skinned or sway. **Part label review overlay**: confirm, relabel, ignore or add a part. **Split-mesh rule**: head, neck and body stay one skin. **Damage tags**: gore level and cut list. **Content flags** (anatomy for the rating board). |
| 4 | **Geometry repair and stance** | **Three-tier source** (SRC_v0_raw / SRC_v1_fixed / WRK). **Fusion detector** with **cut, cap and fair**. **Hidden-surface regeneration** (procedural, template, AI: pick 1 of 3). **Fused finger and toe repair** with **finger-count** from the brief. **Hoof, paw and claw repair** (cloven hooves, dewclaws, pads). **Stance normalisation per body plan** (A-pose for bipeds, neutral stance for quadrupeds and others). **Rigid part split** (keratin, plates, hooves, claws, mandibles). **Retract pockets and sheaths** (claw sheaths, stinger pocket). Every cut is tagged so later repair **never fills it**. |
| 5 | **Face landmarks** (NEW) | **Face profile** (human, bovine, equine, avian, reptile, fish, insect, toon and so on, plus multi-head), confirmed with one click. **MediaPipe landmarks** with a **2D click fallback**. **Jaw hinge estimate** from the side silhouette. **Eye type** (pupil shape, lateral or frontal, eye count, lidded or lidless). Approved on an overlay. |
| 6 | **Eyes** (NEW) | **Aperture cut with lid margin and pocket** (3 candidate outlines plus a width slider). **Procedural eyeballs with iris and pupil shape**, pivot at the fitted centre. AAA adds **tear line, caruncle and occlusion**. Lidless eyes get a spectacle shell. Toon/anime faces go the **flat_uv / decal** route instead. |
| 7 | **Mouth cut and interior** (NEW) | **Lip slit cut** (or **beak / mandible split**), tagged so it is never filled again. **Mouth bag** that is deep enough for tongue extension. **Teeth, gums and tongue templates**. **Nostril cut**. **Ear base pivot** marker. |
| 8 | **Retopology** | QR with **X-symmetry (skipped for asymmetric assets)**, **joint ring bands**, **eye and lip ring density**, **dismemberment cut loops** and **seam edge rings**. A **face topology check** reruns QR automatically if needed. A **hard-surface branch** (QR with sharps, or a planar decimate for crystals). A **card branch** rebuilds the sheets classified in step 3. **Bevel plus weighted-normal** shading on hard parts. **Seam weld normals** for head and body. **Partial region re-retopology** (click a labelled part) with **shape-key transfer**. |
| 9 | **Hair, fur and generated cards** (NEW) | **Eyelash and eyebrow cards**. **Fur and hair cards** (Geometry Nodes) from a **flow field plus 3 presets**, with a **strand atlas**. **Feather cards**. AAA adds a **UE groom tier**. |
| 10 | **UVs** | **Texel density per region**, taken from the real-world scale (face and hands at 2x). **Face UV uniqueness**. **Seam-cost-aware seams**. **Hard-surface seams on sharp edges**. **Lightmap UV1** for static assets, or **damage UV1** for skinned ones. Toon: a **FaceSDF** UV. **Mobile atlas layout** (all opaque parts in one set). |
| 11 | **Bake** | Bakes read **SRC_v1_fixed**. **Triangulate before baking**. **Cage bake** for hard parts. **Auxiliary maps** (curvature, thickness, local AO, edge, position, world normal, ID). **Card alpha bake**. **Translucency mask (TM)**. **Interior projection**. **Damage mask**. **Face and repair texture fill**. **Seam normal fade**. |
| 12 | **Colour / Texture Studio** | **Region detection**. **Tint masks and variants**. **Non-destructive layer stack**. **Smart materials** (wear, dirt, dust, wet). **Delight and concept colour match**. **Prompt re-texture by region**. **Decals, tattoos and scars**. **Emissive and glass**. **Detail normals**. **Style profile** (realistic, hand-painted or toon, with ramps, ILM and SDF face shadow). **Lighting review turntables**. **Mobile material merge** (one material where possible). Tripo re-texture round trip as today. |
| 13 | **Body rig** | **Engine skeleton conventions** (bone roll, `root`, IK bones, `_l/_r`). Base ARP rig from the **body-plan template** with **target options** (twist bones, fingers, toes, metacarpals) and **auto spine, neck and tail counts**. **Rig extras**: tail, ears, spline chains, quadruped/digitigrade/unguligrade legs with **foot-roll pivots**, **scapula slide**, wing finger chains, feathers, multi-head. **Breathing bone**. **Mechanical**: hinge, slider, piston, gear, wheel (with vehicle data), turret with aim limits, rotor, walker legs. **Retractable and deployable** parts. **Physics and secondary bones**: jiggle, dangle chains, helpers, sockets (including seat and rider), weak points, fx bones. **Rigid binding**, **weight cleanup**, **attachment follower**, **cloth and card weight transfer**, **seam weld weights**, **stylised deformation profile**. **Humanoid vs Universal** export type. |
| 14 | **Face rig and expressions** (NEW) | **ARP facial module** placed from landmarks and jaw hinge. **Teeth and tongue binding**. **Creature face bones**. **ARKit 52 and creature expression keys**, **visemes**, **face pose sheet** with gates. |
| 15 | **Deformation and animation test** | **Correctives**, **bulge and squash keys**, **wrinkle maps**. **ROM heat-map test**. **Shear check against the engines**. **Starter animation set**: idle with breathing, locomotion (procedural gait for each body plan, or a licensed retarget), hit and death, in-place and root motion. Foot-slide and penetration badges. |
| 16 | **Physics and damage** | **Physics bodies from cross-sections** with **mass from real-world scale**. **Joint limits**. **Hitbox zones and surfaces**. **Controller capsule and bounds**. **Vehicle centre of mass and wheel colliders**. **Cloth colliders**. **Convex hulls**. **Ragdoll drop test**. **Dismemberment caps and limbs**. **Prop fracture**. **Vehicle and mech damage states**. |
| 17 | **Export** | **forge_manifest.json** with sections for scale, axes, body plan, skeleton, face, physics, vehicle, damage, materials, sockets, animations, LODs, budgets and provenance. **Naming module**. **ARP export hardening** (multi-clip, no simplify, shape-key safe). **Per-engine normals and channel packing**. **Skinned LODs with bone removal**. **Budget validator with one-click reduce**. **Re-import QA badge**. Unreal and Unity mobile copies plus the GLB preview, as today. Optional **VAT/BAT** and **impostor**. |
| 18 | **Engine assembly** (NEW panel step, but built up from M1) | **UE headless import**: materials, sockets, IK Rig, physics asset plugin, Chaos Vehicle setup. **Unity batch import**: prefab, URP materials, avatar, ragdoll, LODGroup, WheelColliders. **Validation rules V1–V13** (V1–V5 from M1). **In-engine review sheet**. |

All steps write a **stage snapshot**, so the asset can be **resumed after a crash** and **rolled back** to any approved stage.

---

## 3. Feature table (merged, one row per feature)

**How:** A = automatic · 1C = one click · AI = AI part · ADJ = you adjust in 2D, with a slider or by clicking a labelled part (several letters mean the fallback chain). **DEV** = developer-only, once per engine version.
**Effort:** S < 1 week · M 1–2 weeks · L 2–4 weeks · XL > 4 weeks.
**Value:** vital / high / medium / nice. **MS** = milestone (section 4).

### 3.1 Pipeline foundations

| Feature | What it gives | How | Needs | Effort | Value | MS |
|---|---|---|---|---|---|---|
| ARP / QR / UVPM probe (`addon_probe.py` extension) | Real property and operator names on the director's install, so nothing is guessed | A | – | S | vital | M1 |
| Engine-neutral manifest `forge_manifest.json` (full schema up front) | One sidecar with scale, axes, body plan, skeleton, face, physics, vehicle, damage, sockets, animation, LOD, material, budget and provenance sections | A | – | M | vital | M1 |
| Naming module `naming.py` | Engine-safe names (SK_/SM_/T_/UCX_/SOCKET_/_LODn), `_l/_r` mapping, no '.' or spaces | A | – | S | high | M1 |
| Edit records and region-scoped approvals (core) | Later fixes replay after retopology; only approvals for the changed region reset. Each tool adds its replay when it ships | A | – | L | vital | M1 |
| Stage snapshots, crash-safe resume, rollback | A Blender crash or a bad step never costs approved work | A | Edit records | M | vital | M1 |
| Provenance and licence record | Prompt, seed, Tripo task ID, model versions and licence for each asset | A | Manifest | S | high | M1 |
| Real-world scale, forward axis, ground plane and origin | Correct size for physics, texel density and retargeting; feet on Z=0; per-engine axis conversion | A (brief), 1C (height slider) | VLM brief | S | vital | M1 |
| Engine skeleton conventions (bone roll, `root`, UE IK bones, side suffixes) | Library animations and retargeting work without silent twists | A | Probe | M | vital | M1 |
| Three-tier bake source (raw / fixed / work) | Bakes read the repaired mesh, so no black smears from fused bridges | A | – | S | vital | M1 |
| Symmetry plane detection and alignment, with asymmetric and partial options | Asset centred on X=0; QR symmetry, mirrored weights and UVs work; asymmetric assets are not forced symmetric | 1C | – | M | vital | M1 |
| Minimal engine import and validation V1–V5 (headless UE, Unity batch) | Every milestone is checked in both engines with no manual engine work | A | Manifest, naming | L | vital | M1 |
| Fixture set (humanoid, bull, flyer, serpent, vehicle prop) | Body-plan bugs show up early, not at the end | A | – | S | vital | M1 |
| Director time and click counter per step | Shows where the ≤ 30-minute target is lost | A | – | S | high | M1 |
| VLM asset brief | Species, body plan, limb, finger and eye types, foot type, materials, expected parts and size feed every classifier | A, 1C (confirm card) | – | M | vital | M2 |
| Body-plan template library | Biped / quadruped / hexapod / bird / serpent / fish / insect-arachnid / tentacled / flyer / wheeled / tracked / walker templates for skeleton, stance, rig, physics and gait | A, 1C override | VLM brief | L | vital | M2 |
| Asset class classifier (static / mechanical / skinned / sway) | Picks lightmaps, Nanite, vertex-colour profile, static or skeletal route | A, 1C override | VLM brief | M | high | M2 |
| Tripo preflight and auto-corrected image regenerate | Fewer fused arms and fingers before any repair; the director picks 1 of 3 corrected images and never edits pixels | 1C, AI | VLM brief | M | high | M2 |
| Lighting review turntables and A/B | One shared approval view: 3 light rigs, matcap seam crops, light sweep | 1C | – | M | high | M2 |
| Budget validator, report only (bones per section, influences, morphs, mobile bone count) | Mobile never silently breaks: 75 bones per section, 4 or 2 influences | A | Manifest | S | vital | M1 |
| Budget one-click reduce | Removes bones or influences to fit the budget | 1C | Skinned LODs, budget validator | S | high | M10 |
| VRAM and compression budget QA | Texture memory per profile, with automatic resize | A | Channel packing | S | medium | M8 |
| Export round-trip QA badge | Re-imports the FBX and checks scale, axes, bones, clips, takes, no live drivers, shape keys intact | A | ARP export settings | M | high | M1 |
| Content and anatomy flags | Anatomy that matters for the rating board is flagged, with a smooth-over option | A, 1C | Part classifier | S | medium | M2 |

### 3.2 Assemble, repair and body

| Feature | What it gives | How | Needs | Effort | Value | MS |
|---|---|---|---|---|---|---|
| Part segmentation and joint caps | Separate parts for rigid bind, pivots and doors; caps at rigid joints | A (Tripo seg), 1C (click seed + region grow + cut-height slider) | – | L | vital | M2 |
| Temporary skeleton and `forge_part` labels | Per-vertex bone labels from the body-plan template; turns fusion detection into a graph question | A, ADJ (2D front/side dots, mirrored) | Joint estimator, body plan | M | vital | M2 |
| Part classifier (shape, cloth/armour, hard/organic, material class) | Each part tagged as rod, tail, tentacle, leg, sheet, skin, cloth, armour, rigid accessory, hair, and HARD or ORGANIC | A, 1C | Segmentation, temp skeleton, VLM brief | L | vital | M2 |
| Thin-sheet / card classifier | Capes, membranes, fins, insect wings and thin ears are routed to cards **before** QR | A | Part classifier | M | vital | M2 |
| Part label review overlay | Colour overlay with confirm, relabel, ignore and "add part here"; also hosts wing type, gills and fire questions | 1C | Part classifier | M | vital | M2 |
| Fused-region detector | Red bands at armpits, crotch web, tail-leg, wing-body and cape-back; skirts are left alone | 1C | Temp skeleton | L | vital | M2 |
| Cut, cap and fair fused bridges, with cut tags | Clean surfaces for QR and the bake; tagged cuts are never filled again (regression test) | A | Fusion detector, 3-tier source | M | vital | M2 |
| Hidden-surface regeneration: procedural and template tiers | Armpits, back under cape and legs under skirt get real surface | A (< 5% of a part), 1C (pick 1 of 3) | Cut and cap | L | vital | M2 |
| Hidden-surface regeneration: AI completion tier | Larger hidden areas filled by AI | AI | Procedural tier | M | medium | M11 |
| Stance normalisation per body plan | Symmetric A-pose for bipeds; neutral stance for quadrupeds, birds and serpents; no baked asymmetric creases | 1C (100% / 50%) | Temp skeleton, cut and cap, hidden-surface regen | L | vital | M2 |
| Fused finger and toe repair with finger count | Separate fingers (regenerate, template hand or slab cut); count from the brief; barefoot/shoe flag | 1C, AI | Temp skeleton, VLM brief | L | vital | M2 |
| Hoof, paw and claw repair | Cloven hooves with dewclaws, paw pads, nails and claws as rigid tips | A, 1C | Rigid split, VLM brief | M | high | M2 |
| Rigid part split | Horns, hooves, claws, beaks, mandibles, plates and crystals as separate rigid parts | A, 1C (tip click) | Part classifier | M | vital | M2 |
| Retract pockets and sheaths | Cavity for claws, stingers and spikes so deploys never poke through skin | A | Rigid split, cut tags | M | high | M2 |
| Split-mesh rule and seam edge rings | Head, neck and body stay one skin; swappable parts split on an identical edge ring | 1C (seam height) | – | M | high | M2 |
| Inner core / internals separation | Opaque eyes, teeth and cores inside glass or gel shells | AI (Tripo core), A (shrunk shell) | Material class | L | medium | M11 |

### 3.3 Face (profile, landmarks, eyes, mouth)

| Feature | What it gives | How | Needs | Effort | Value | MS |
|---|---|---|---|---|---|---|
| Face profile and eye-mode classifier | human / bovine / equine / avian / reptile / insect / fish / toon / anime and the like, plus multi-head; drives every later face step | A (brief), 1C (dropdown with 3 thumbnails) | Appendage finder, VLM brief | M | vital | M4 |
| Face landmarks with 2D click fallback | Eye corners, lip lines, iris and brow arc projected onto the mesh | A (MediaPipe subprocess), 1C (4–6 clicks on a 2D render) | Face profile, stance normalised | L | vital | M4 |
| Jaw hinge estimate | Jaw pivot from the side silhouette and landmarks, so jaw-open does not tear the cheeks | A, ADJ (2D dot) | Landmarks | S | vital | M4 |
| Eye type: pupil shape, placement, count, lidded or lidless | Bar pupils for bovines and goats, slits for cats, lateral look-at limits, spider eyes, fish/snake spectacle | A (brief), 1C | Face profile | M | high | M4 |
| Eye aperture cut, lid margin and pocket | Eyes that can open and close; concentric lid loops before retopology | 1C (3 candidate outlines + width slider) | Landmarks | L | vital | M4 |
| Procedural eyeballs with iris and pupil material | Rotating Eye_L/Eye_R pivoted at the fitted centre; iris colour sampled from the image; AAA adds a cornea shell | A | Aperture cut, eye type | L | vital | M4 |
| Tear line, caruncle and eye occlusion (AAA) | Eyes stop looking pasted on; on mobile this is painted into the texture | A | Eyeballs, attachment follower | M | medium | M11 |
| Mouth slit cut (or beak / mandible split) | An openable mouth; repair is told to skip the slit | A | Landmarks, jaw hinge | M | vital | M4 |
| Mouth bag | Dark closed cavity behind the lips, deep enough for tongue extension | A | Slit cut | M | vital | M4 |
| Teeth, gums and tongue templates | Human, toon and creature fang sets fitted into the bag, set up for ARP | A | Mouth bag | M | high | M4 |
| Nostril cut and interior | Flare-able nostrils (important for bulls and horses); dent plus dark texture on mobile | A | Landmarks | S | medium | M4 |
| Ear base pivot marker | Ears rotate from the skull, not mid-ear | A | Appendage finder | S | high | M3 |
| Face topology check and auto-rerun | Enough eye and lip loops, symmetric topology, pass/fail badge | A | Slit cut, aperture cut | M | high | M4 |
| Stylised eyes and mouths (flat_uv, decal, flipbook) | Toon/anime eyes moved by UV offset, ^ ^ expressions, texture-swap mouths | 1C (approve atlas sheet) | Face profile | L | high | M11 |
| Multi-head replication | Each head of a Cerberus or hydra animates and lip-syncs on its own | 1C (confirm head count) | Expression keys | L | nice | M11 |

### 3.4 Retopology and geometry

| Feature | What it gives | How | Needs | Effort | Value | MS |
|---|---|---|---|---|---|---|
| Joint ring guide bands for QR | Loops on both sides of every joint, so no candy-wrapper or pinch (loop-insert fallback) | A | Joint estimator, temp skeleton | M | vital | M2 |
| Hard-surface retopology branch (incl. crystal / ice planar decimate) | Sharp edges and facets survive on horns, hooves, armour and machines | A | Hard/organic classifier | M | high | M2 |
| Bevel and weighted-normal mid-poly shading | Clean flat shading; can skip the normal bake (Nanite, mobile) | 1C (sharp-angle slider) | Hard-surface branch | S | high | M9 |
| Seam weld normals (geometry part) | Invisible head/body normal seam, available before bake and toon normals | A | Split-mesh rule | S | high | M2 |
| Hard-surface triangle budgets and mobile simplification | Correct triangle target per weapon, vehicle or drone; lighter mobile copy | A | Hard-surface branch, bevel | S | nice | M9 |
| Dismemberment cut loops and hard weight seams | Clean edge loops at cut bones so stumps do not pinch | 1C (pick cuts and gore preset) | Damage tags (step 3), manifest schema | L | high | M11 |
| Partial region re-retopology with shape-key transfer | Redo one ear, hand or face area without touching approved work or losing morphs | 1C (click a labelled part) | Edit records, shape-key transfer | L | medium | M11 |
| Cables, hoses and tracks rebuild | Clean tubes and belts with straight UVs and bend chains | 1C (endpoints if needed) | Segmentation | L | medium | M9 |

### 3.5 Cards, alpha, hair and fur

| Feature | What it gives | How | Needs | Effort | Value | MS |
|---|---|---|---|---|---|---|
| Alpha card rebuild for classified sheets (retopology card branch) | Single-layer double-sided card with an alpha outline; tatters come from alpha | A | Card classifier | L | vital | M6 |
| Card alpha / coverage bake | Straight-alpha RGBA with dilated colour; no forced A=1 | A | Card rebuild | M | vital | M6 |
| Blender preview materials for cards and translucency | Correct alpha-clip and translucency preview for approval (5.x-safe API) | A | – | S | high | M6 |
| Engine alpha-cutout material setup | Cards, feathers and fur correctly Masked / AlphaClip, two-sided, through the import pipeline | A | Minimal engine import | M | vital | M6 |
| Eyelash and eyebrow cards | Lashes from the lid margin, brows from the brow arc; follow every blink | A | Aperture cut, card alpha bake, attachment follower | M | high | M6 |
| Fur and hair card generator (Geometry Nodes) | Mane, tail tuft, fetlock and fur as game cards instead of a sculpted blob | AI (guide generation), A (flow field from the colour image), 1C (3 presets: sleek / shaggy / curly) | Card weight transfer | XL | high | M6 |
| Hair card texture atlas (strand ortho render) | Alpha, colour, normal and root-tip atlas matched to the creature colour | A | Fur cards | L | medium | M6 |
| Feathered wing: feather cards and ARP feather bones | Foldable feathered wings | 1C | Card bake, label overlay | XL | medium | M11 |
| UE groom export tier (Alembic) | Real strands on AAA Unreal, with cards as fallback | A | Fur cards | M | medium | M11 |

### 3.6 UVs and textures

| Feature | What it gives | How | Needs | Effort | Value | MS |
|---|---|---|---|---|---|---|
| Per-region texel density and per-material texture sets | Face and hands sharp (2x), consistent density from real scale, auto texture size; fixes the bull's 2504 vs 1024 px/m | A | Real-world scale | M | high | M8 |
| Face UV uniqueness check | No mirrored or stacked face islands, so L/R masks work | A | – | S | high | M4 |
| Seam fixing and seam-cost-aware seams | Seams hidden under arms and behind the head; colour blended across seams; QA ΔE < 3 | A | Layer stack | M | high | M8 |
| Hard-surface UVs and cage bake | No wavy edges or gaps on hard parts | A | Hard-surface branch | M | high | M9 |
| Lightmap UV1 with validation | Baked lighting for static props (Unity mobile, Lightmass); resolution recommended | A | Asset class | M | high | M9 |
| Per-engine normal convention (triangulate, DirectX flip for UE) | Bumps lit correctly in UE; bake matches exported triangles | A | – | S | vital | M1 |
| Channel packing and naming per engine | UE ORM, URP MetallicSmoothness, Forge mobile mask; correct colour space | A | – | S | vital | M1 |
| Mobile material merge and texture atlas | One material and one draw call per mobile character where possible; emissive and alpha kept only when needed | A | Channel packing, UV layout | M | vital | M8 |
| Auxiliary bakes (curvature, thickness, local AO, edge, position, world normal, ID) | Inputs for wear, dirt, SSS, toon and masks | A | – | M | vital | M8 |
| Repair and face texture fill | Colour for cut, filled, stretched and painted-eye areas; dark interiors; AO re-baked with openings | A, AI (masked re-texture) | Cut and cap, stance, eye and mouth cuts | M | high | M4 |
| Skin and face material maps | Thickness for SSS (ears, lids, nostrils), roughness zones (wet nose leather and lips), lip/cheek/brow tint masks, pore normal | A | Landmarks, aux bakes | M | medium | M8 |
| Tint region detection | Click-to-pick regions from segments, colour clusters or flood fill | A, 1C, AI (Tripo segment names) | Segmentation | M | vital | M8 |
| RGBA tint masks and variants | Team colours and skins at near-zero cost; defaults reproduce the original look | 1C | Regions, master materials | M | high | M8 |
| Non-destructive layer stack and Approve & Bake | Undoable recolour, wear and decals; nothing destructive until approved | 1C | Aux bakes | L | vital | M8 |
| Smart materials with auto material tagging | Edge wear, cavity dirt, top dust, rust and wet on sliders; region material tags from a VLM; 3 damage levels | AI, ADJ (sliders) | Layer stack, regions | M | high | M8 |
| Delighting, PBR albedo range and concept colour match | Removes baked-in shadows; colours match the concept | ADJ (2 sliders) | Regions, aux bakes | M | high | M8 |
| Regional prompt re-texture (ComfyUI) and base-colour upscale | "Make the horns bronze", higher resolution than Tripo | AI | Layer stack, regions | XL | medium | M11 |
| Decals, tattoos and scars | Click-to-place logo or tattoo; scar drawn as one stroke | 1C | Layer stack, re-texture | L | medium | M11 |
| Emissive and glass detection | Glowing eyes, runes, LEDs, headlights and visors as an emissive mask or slot; glass gets its own slot | 1C | Segmentation | S | medium | M9 |
| Mechanical masks (ID, tint, wear, rust) | Team-colour mask and procedural wear for machines | 1C | Hard-surface bake, tint masks | M | medium | M9 |
| Creature masks (zones, root-to-tip gradient on horns and claws, scale detail) | Standard creature variants; keratin gradients | A | Part classifier | M | nice | M8 |
| Detail normal library | Pores, weave, leather, scales and brushed metal up close for about 1 MB | 1C (3 thumbnails) | Regions, master materials | M | medium | M8 |
| Style profile (realistic / hand-painted / toon) | The director picks a look; hand-painted recipe with 5 sliders | ADJ (sliders) | Layer stack, aux bakes | M | medium | M11 |
| Toon ramp and ILM maps | Cel shading per material in both engines | 1C (3 ramp presets) | Regions, master materials | L | medium | M11 |
| Toon face-shadow proxy normals | Clean anime face shading | 1C | Seam weld normals, normal consistency | M | medium | M11 |
| SDF face-shadow map | Genshin-style nose and cheek shadow sweep | ADJ (one slider) | Toon proxy | L | medium | M11 |
| Translucent material class classifier | Ghost, slime, ice, crystal, hologram and thin wing detected per part | 1C (EEVEE turntable) | Preview materials | M | high | M11 |
| Translucency mask (TM) bake | Thickness, interior, dissolve gradient and edge in one RGBA | A | Material class | L | high | M11 |
| Interior colour projection | Fake volume: bones inside slime, objects inside ice | A | TM bake | M | medium | M11 |
| Damage mask RGBA and unique UV1 | Blood, burn and crack damage plus a zone ID; approved on a 0/50/100% turntable | 1C | Damage manifest | M | high | M11 |
| Vertex-colour profiles (PROP, MECH_EMISSIVE, SWAY, CHAR) and calibration strip | Cheap per-vertex AO, wear, tint ID and outline width, with correct colour space per engine | A | Asset class, regions | M | high | M11 |
| Forge Texture Studio panel | Every texture action above as clicks in step 12 | 1C | Layer stack, regions, review turntables | L | vital | M8 |

### 3.7 Body rig

| Feature | What it gives | How | Needs | Effort | Value | MS |
|---|---|---|---|---|---|---|
| Custom bone tagging and parenting (`cc_`) | Extra, mechanical and deploy bones survive ARP export | A | – | S | vital | M3 |
| Body-plan rig builder (ARP biped / dog / horse presets + Forge templates) | Correct base rig for each body plan, with spine, neck and tail counts from part length | A | Body-plan templates, temp skeleton | L | vital | M3 |
| Humanoid vs Universal export chooser | No refused exports for quadrupeds or multi-ear rigs; avoids name collisions | A | Body-plan rig builder | S | vital | M3 |
| Target-aware ARP limb options | Twist bones (2 for UE, 1 for Unity), fingers, metacarpals, toes, breast bones | A | Finger repair | M | high | M3 |
| ARP extras stage: tail, ears, chains (manes, fins, antennae, tentacles) | Bones for what the appendage finder already detects; chain length set from part length | A | Appendage classifier, ear base pivot | L | vital | M3 |
| Quadruped / digitigrade / unguligrade / multi-leg rig with foot-roll pivots | Correct leg count and 3-bone legs from ground contacts; heel/ball/tip pivots; no backwards hocks | A, ADJ (2D side-view dots, mirrored) | Body-plan rig builder | XL | vital | M3 |
| Scapula slide and chest sling (quadrupeds) | Front legs do not collapse at the shoulder | A | Quadruped rig | M | high | M3 |
| Serpent and spline-body rig | Snakes, worms, eels and tentacles bend smoothly along the body | A | Body-plan templates | L | high | M3 |
| Breathing bone and idle breathing | Every creature breathes in idle | A | Body-plan rig builder | S | high | M3 |
| Rigid part 100% weight clamp (incl. hooves, claws, mechanical parts and armour) | Horns, hooves, plates and machine parts never bend; plate interpenetration flagged in ROM poses | A, 1C (clearance or helper bone) | Rigid split, part classifier | M | vital | M3 |
| Weight cleanup and region rebind | Smooth, clean, limit and normalise weights; "fix this region" rebind by clicking a red spot | 1C | ROM test | M | vital | M3 |
| ROM pose test with heat map (engine-faithful LBS) | One approval image for all body deformation; click a red spot for a fix | 1C | – | M | vital | M3 |
| Clothing and card weight transfer, hidden-body removal, poke-through, hat hair | Cloth and cards follow the body; hidden triangles removed; no poke-through | A | Part classifier, hidden-surface regen | L | high | M6 |
| Seam weld weights and shape-key falloff | Invisible head/body seam in every pose and expression | A | Split-mesh rule, seam weld normals | M | high | M3 |
| Secondary bones: jiggle, dangle chains, two-click "bone chain A→B" | Belly, dewlap, earrings, ponytails, nose rings and straps move; physics hint list | 1C | Part classifier, edit records | L | high | M7 |
| Procedural helper bones (elbow, knee, armpit, glute, pauldron) | Volume kept on mobile without correctives | A | Edit records | M | medium | M11 |
| Membrane wing finger chains and fold driver | Bat and dragon wings stretch and fold; hexapods (4 legs + 2 wings) supported | ADJ (≤ 5 tip clicks on a 2D render) | Appendage classifier, chains | XL | medium | M11 |
| Mechanical part detectors (pivot and axis) | Wheels, gears, turrets, pistons, doors, rotors and muzzles found; gizmo to confirm or flip | 1C | Segmentation | L | high | M9 |
| Mechanical constraint rigs | Hinge, slider, piston, gear ratio, wheel roll, turret with aim limits, rotor spin | A | Mech detectors, cc_ tagging | L | high | M9 |
| Vehicle data (wheel radius and width, suspension travel, steer and drive flags, centre of mass) | Chaos Vehicle and WheelCollider setups work without manual tuning | A, 1C (confirm drive wheels) | Mech detectors, real-world scale | M | high | M9 |
| Mech walker legs (reverse-joint and multi-leg IK) | Walking machines with planted feet | A, ADJ (2D dots) | Mech rigs, body-plan templates | L | medium | M9 |
| Clip authoring and safe bake for driven rigs | Deploy_/Open_/Spin_ clips export once, with no double transforms (Blender 5 slotted actions) | A | cc_ tagging | M | high | M7 |
| Retractable and deployable parts | Claws, stingers, tongue and spikes hide in their pockets and deploy; hidden → deployed approval strip | 1C | Retract pockets, cc_ tagging, clip authoring | L | high | M7 |
| Sockets and attachment points (`sockets.json`) incl. seat and rider | Hand, back, hip, head, muzzle, fx, seat and saddle sockets in both engines; "socket here" click; rider pose check | 1C | Edit records | S | medium | M7 |
| Attachment follower | Lashes, brows, tear line and whisker cards follow every expression (weights plus shape keys) | A | Expression keys | M | high | M5 |
| Stylised deformation profile | Squash and stretch that survives export (twist-based, softlink) | 1C | Import presets | S | high | M11 |
| Inverted-hull toon outlines | Outline-ready smoothed normals in UV3 plus a width attribute from curvature; erase brush as last resort | A, ADJ | Normal consistency, style profile | L | medium | M11 |

### 3.8 Face rig, shapes and deformation tests

| Feature | What it gives | How | Needs | Effort | Value | MS |
|---|---|---|---|---|---|---|
| ARP facial rig and face-ref placement (jaw, lips, lids, teeth, tongue; creature mouth) | Jaw, lid and lip deformation; refs placed from landmarks and jaw hinge; bone names read at runtime | A, ADJ (2D dots) | Body rig, landmarks, face profile | L | vital | M5 |
| Mouth and eye binding with teeth weight fallback | Teeth, tongue and mouth bag bound correctly even with no eye bones; clean upper/lower lip split | A | Facial rig, teeth | M | high | M5 |
| Expression keys (ARKit 52, computed blinks, L/R split) and visemes | Live Link / Audio2Face-ready keys, 15 visemes; mobile gets blink, jaw and visemes only | A | Facial rig, face topology check | XL | vital | M5 |
| Face pose sheet and automatic gates | Lid-through-eyeball, leaky pocket and open-bag checks, then a contact sheet with approve or a strength slider per group | 1C, ADJ (strength slider) | Expression keys | M | vital | M5 |
| Creature face bones and expression sets | Snarl, ear pin, beak open, nictitating membrane, mandibles, gills, bovine lateral chew | 1C | Face profile, expression keys, ear chains | XL | high | M5 |
| Real-animation test and starter animation set (procedural gaits per body plan, licensed retarget, root motion) | Idle with breathing, walk, run, attack, hit and death as deliverable clips; foot-slide and penetration badges | 1C | ROM test, manifest, skeleton conventions | XL | vital | M10 |
| Auto corrective shape keys (inverse skinning) and driver table (AAA) | Shoulder, elbow, knee and hip keep volume | A | ROM test, joint rings | L | high | M11 |
| Expression wrinkle and blood-flow maps (AAA) | MetaHuman-style folds and colour on frowns and smiles | ADJ (strength sliders) | Expression keys, face UV check | XL | medium | M11 |
| Joint wrinkle maps | Folds on knuckles, elbows, knees and creature necks | A | Expression wrinkles | M | nice | M11 |
| Shape-key deployables and shape-key-safe export | Spikes, frills and swelling as morphs; keys survive retopology and decimation | A | Deployable parts | M | medium | M7 |
| Creature shape keys (gills, bell pulse, morph forms) | Breathing gills, jellyfish pulse, shape-shifter morph | AI (second Tripo form), 1C | Label overlay | L | nice | M11 |
| Shear detector and three-way engine check | What the director approves in Blender looks the same in UE and Unity; Fix button | 1C | Stylised profile, engine import | L | high | M11 |
| B-Bone to segment bones | Rubber-hose limbs, tails and tentacles exportable | 1C | cc_ tagging, shear check | L | medium | M11 |
| Volume-preserving bulge bones / squash keys | Squash and stretch keeps volume | A | Stylised profile | M | medium | M11 |
| Sway weights (vertex colour) | Cheap shader sway for banners, cables and small flaps | A | VC profiles | M | medium | M11 |

### 3.9 Physics and damage

| Feature | What it gives | How | Needs | Effort | Value | MS |
|---|---|---|---|---|---|---|
| Physics body fitting from cross-sections | Bone-accurate capsules, spheres and boxes with mass from real-world scale, for ragdoll, hitbox and cloth sets | A | Manifest, body rig, real-world scale | L | vital | M10 |
| Ragdoll joint limits | No forward knees or spinning heads; limits for each body plan; mech hinge and slider limits taken from the rig | A | Body fitting | M | vital | M10 |
| Ragdoll drop test and collider review sheet | Coloured colliders plus a 3 s drop video; "too fat / thin / floppy" buttons | 1C | Body fitting, limits | M | high | M10 |
| Hitbox zones, multipliers and surface types | Headshots, armour reduction, per-zone reactions, flesh/metal/chitin/keratin surfaces | A | Body fitting | M | high | M10 |
| Weak-point detection and placement | Shootable cores, eyes and tanks with a click-to-confirm sphere | 1C | Hitbox zones | M | medium | M11 |
| Controller capsule, pivot and animated bounds | Feet on the ground, correct navmesh, no culling pops; long-body capsules for quadrupeds | A | Body fitting | S | high | M10 |
| Cloth and hair collision capsules | Capes and skirts stay out of the legs | A | Body fitting | S | medium | M11 |
| Cloth simulation masks (Max Distance) | AAA skirt and cape simulation; sim / bone chain / rigid choice; mask computed automatically from distance to the body + preset | A, 1C (preset) | Cloth weight transfer | M | medium | M11 |
| Convex decomposition (CoACD) and UCX / collision export | Collision for props, mechs and pieces; static vs skeletal routing | A | Body fitting, naming | M | high | M9 |
| Mechanical articulation export | Stretch-free motor chains (Unity ArticulationBody, UE drives) | A | Limits, convex hulls | M | nice | M11 |
| Damage manifest and reserved material slots | Cut list, pieces, states and interior/gore slots | A | Manifest schema | S | high | M11 |
| Severed limbs, fx sockets and dismember preview | Flying limb, blood socket and a gore preview grid | 1C | Cut loops, body fitting | M | medium | M11 |
| Prop fracture (Voronoi) with interior faces | Pre-fractured pieces with hulls; exploded-view approval | 1C | Damage manifest, convex hulls | L | medium | M11 |
| Vehicle and mech damage states (S0/S1/S2) | Lost plates, hanging doors, dents, burnt husk | 1C | Damage manifest, convex hulls | XL | medium | M11 |
| Translucent sorting prep | Stable ordering for gel and glass shells | A | Material class | M | medium | M11 |
| Dissolve state export | Death/spawn dissolve, swapped in only while dissolving | 1C | TM bake | S | medium | M11 |

### 3.10 Export, LOD and engine

| Feature | What it gives | How | Needs | Effort | Value | MS |
|---|---|---|---|---|---|---|
| ARP export hardening (multi-clip, no simplify, shape-key keys, x100, presets, leaf bones) | No dropped clips, flattened claw motion or scale mismatch | A | Manifest | S | vital | M1 |
| Per-profile face export settings | Mobile folds face bones; 4 influences; jaw as c_jawbone; morphs per LOD | A | Facial rig | S | vital | M5 |
| Normal and tangent export/import consistency | Custom normals and seams survive engine import | A | Minimal engine import | S | vital | M1 |
| Skinned LODs with per-LOD bone removal and weight folding | LOD0–3 drop face, finger, twist and tail bones; contact sheet at switch distances | A | Weight cleanup, manifest | M | high | M10 |
| Rigid mech split export | Fully rigid mechs exported as per-bone static meshes (Nanite, no skinning) | A | Manifest | S | medium | M9 |
| Sockets, collision and static vs skeletal routing | Correct mesh type, SOCKET_/UCX_ export | A | Mech detectors | M | high | M9 |
| Automated UE5 import (headless Python), full | Skeleton, morphs, LODs, MIs, textures, sockets, IK Rig, Chaos Vehicle with zero clicks | A | Minimal engine import | XL | vital | M1 (minimal) → M10 (full) |
| Automated Unity import (batch mode), full | Prefab, avatar, URP material variants, LODGroup, colliders, WheelColliders, rigging constraints | A | Minimal engine import | L | vital | M1 (minimal) → M10 (full) |
| Engine master materials and Shader Graphs (opaque, tint, detail, skin, eye, toon) | Packed data actually renders; URP gets skin and eye fallbacks | A, DEV (masters authored once) | Packing, import hooks | L | high | M8 |
| Per-class translucency masters in 3 tiers | Ghost, gel, ice, crystal, glass, hologram and wing for AAA, mobile-high and mobile-low | A, DEV | Material class, TM | XL | high | M11 |
| Engine face drivers and importers | Eyelid follow, ARKit remap, wrinkle and toon drivers, chew and gill loops | A, DEV (template ABPs once) | Face manifest, face export | L | high | M5 |
| Engine secondary motion and procedural deploy templates | Spring tails, ears and cables; scale-snap deploy at runtime | A, DEV | Import presets, deployables, chains | L | medium | M7 |
| UE IK Rig / Retargeter and Unity Humanoid/Generic avatar | Library animations (Lyra, GASP, Starter Assets) run on the asset | A | Manifest, export hardening, skeleton conventions | XL | high | M10 |
| UE physics asset builder (C++ plugin) | Forge bodies become PHYS_<asset>; hand-tuned template as developer fallback | A, DEV | Body fitting, UE import | L | high | M10 |
| Unity ragdoll and ragdoll-swap prefab | Colliders, joints, hitboxes, pooled ragdoll for mobile | A | Body fitting, Unity import | M | high | M10 |
| Validation rules and `engine_report.json` | V1–V5 (scale, axes, skeleton, normals, packing) from M1; V6–V13 added with their features. Failing assets stop before the director sees them | A | Minimal engine import | M | vital | M1 → M10 |
| In-engine review contact sheet | Turntable, pose test, blink and LOD strip rendered in UE and Unity next to Blender | 1C | Engine import | L | high | M1 (turntable) → M10 |
| VAT/BAT baker and crowd shaders | Hundreds of instanced crowd animals in a few draw calls | A | Skinned LODs, import | L | medium | M11 |
| Octahedral impostor baker | 2-triangle distant LOD | A | Skinned LODs | M | nice | M11 |
| Crowd performance profile | Budget allocator, URO and culling set per significance class | A | Import | S | nice | M11 |

---

## 4. Build order (milestones)

Each milestone ships on its own and leaves Forge working. It ends with a **fixture test**: the bull plus the other fixtures the milestone touches (humanoid, flyer, serpent, vehicle prop). Every milestone is checked **in UE and Unity through the import pipeline**, not by hand. Vital items come first; within a milestone the order is the build order. Each tool adds its edit-record replay and its validation rules when it ships.

**Ordering principle:** ground truth → clean silhouette → body rig → face cuts → face rig → cards → deployables → textures → mechanical → physics/LOD/animation → extras. Nothing may change the silhouette after the face is cut, and no face bones are added before the body rig exists.

### M1 — Ground truth, safety net and engine smoke path (≈4–5 weeks)
Extend the probe (ARP 3.79.17, QR, UVPM, 5.3 API, ARP dog/horse presets, bone roll on export). Then the manifest (full schema) and naming module, core edit records, stage snapshots and resume, provenance record, fixture set, and real-world scale, axes, ground and origin. Then engine skeleton conventions (root, IK bones, roll, suffixes), symmetry alignment with the asymmetric option, three-tier bake source, ARP export hardening, per-engine normal convention, channel packing, budget validator (report only), export round-trip QA badge, minimal headless UE and Unity import with V1–V5, an in-engine turntable, and the director click/time counter.
**Fixture test:** the bull is re-exported at 1.5 m shoulder height, centred on X=0, feet on Z=0, facing +X in UE and +Z in Unity. The QA badge is green: one root, one pelvis, all clips, scale 1, UE normal map flipped, ORM packed. Both engines import headless and render a turntable. A crash mid-step resumes from the snapshot.

### M2 — Brief, assemble, repair and stance (≈8–10 weeks)
VLM asset brief, body-plan templates, asset class, Tripo preflight and auto-corrected image, part segmentation and joint caps, temporary skeleton and labels, part classifier (including hard/organic and material class), thin-sheet classifier, label review overlay, rigid split, fusion detector, cut/cap/fair with cut tags (regression test), hidden-surface regeneration (procedural and template tiers), finger and toe repair, hoof/paw/claw repair, stance normalisation, retract pockets, split-mesh rule and seam rings, joint ring bands, hard-surface retopology branch, seam weld normals, content flags and lighting review turntables.
**Fixture test:** bull with no leg web, separate cloven hooves with dewclaws, rigid horns, neutral quadruped stance. Humanoid with 5 separate fingers and clean armpits. Cape on a fixture classified as a card. Under 10 director clicks per asset.

### M3 — Body and creature rig (≈8–10 weeks)
cc_ tagging, body-plan rig builder, Humanoid/Universal chooser, target-aware limb options, ARP extras (tail, ears, chains), ear base pivot, quadruped/unguligrade legs with foot-roll pivots, scapula slide, serpent spline rig, breathing bone, rigid 100% clamp, seam weld weights, ROM heat-map test, weight cleanup and region rebind.
**Fixture test:** bull with 4 correct legs (no backwards hocks), scapula slide, tail chain, ear chains rotating from the skull, rigid horns and hooves, breathing. Serpent bends smoothly. Humanoid retargets one Lyra/Starter clip without twisted hands. ROM sheets are green. The Universal export re-imports with tail_/ear_ bones present.

### M4 — Face geometry: eyes, mouth, interior (≈6–8 weeks)
Face profile (bovine), landmarks with 2D click fallback, jaw hinge estimate, eye type (bar pupil, lateral), eye aperture with lid margin and pocket, eyeballs with iris and pupil, mouth slit (or beak split), mouth bag, teeth/gums/tongue templates, nostril cut, face topology check plus QR rerun, face UV uniqueness, face and repair texture fill.
**Fixture test:** the director clicks 4 eye points and 2 mouth corners at most. The bull has real eyeballs with horizontal bar pupils, an openable mouth with a dark interior and tongue, flared nostrils, and no painted eyes left in the texture. The topology badge is green. Repair re-run leaves all cuts open.

### M5 — Face rig and expressions (≈6–8 weeks)
ARP facial rig with ref placement (jaw first, both signs tested), mouth/eye binding with teeth fallback, expression keys (mobile set first: blink L/R, jaw, visemes; then ARKit 52), creature face bones and expression sets (ear pin, snarl, lateral chew), attachment follower, face pose sheet with gates, per-profile face export settings, viseme set plus face manifest, engine face drivers (developer builds the template ABP once).
**Fixture test:** blink, look L/R/U/D within lateral-eye limits, jaw open and chew, nostril flare, ear pin. The face contact sheet is approved. The Unity mobile copy has ≤ 4 influences. Blink plays in both engines.

### M6 — Cards, fur and alpha (≈6–8 weeks)
Alpha card rebuild (retopology card branch), card alpha bake, Blender preview materials, engine alpha-cutout setup through import, card/cloth weight transfer with hidden-body removal, eyelash and eyebrow cards, fur/hair card generator (flow field plus presets), strand atlas.
**Fixture test:** tail tuft, forelock, ear hair and lashes as cards that follow blinks. A fixture cape becomes a card. Alpha is correct in Blender, UE (Masked) and URP (AlphaClip). Mobile lash overdraw is within budget.

### M7 — Retractable, deployable and secondary motion (≈4–5 weeks)
Clip authoring with safe bake, retractable/deployable system (kinds A–D) using the M2 pockets, shape-key deployables with shape-key-safe export, sockets.json (including seat and rider), engine procedural deploy templates, secondary bones (dewlap jiggle, chain A→B), engine secondary motion.
**Fixture test:** a tongue extend/retract clip that stays inside the mouth bag, and a nose-ring chain added with two clicks. Hidden → deployed approval strip. Clips are present as FBX takes. A claw fixture covers the claw case. The bull gets a saddle socket that passes the rider pose check.

### M8 — Texture definition and mobile materials (≈8–10 weeks)
Auxiliary bakes, region detection, layer stack, Texture Studio panel, master materials and Shader Graphs (developer authors masters once), tint masks and variants, smart materials, delighting and concept match, per-region texel density from real scale, seam fixing, skin/face maps (wet nose leather, thin ear SSS), creature masks (horn root-to-tip gradient), detail normal library, mobile material merge and atlas, VRAM QA.
**Fixture test:** density near target (fixes 2504 vs 1024 px/m). Three coat-colour variants from one set. Horn gradient, dust on the back, no baked-in shadows. Mobile bull renders in one draw call (plus one for alpha cards). All approved in the turntable in Blender and both engines.

### M9 — Mechanical (≈8–10 weeks)
Bevel plus weighted normals, hard-surface UV and cage bake, mechanical detectors, constraint rigs (including turret aim limits and rotors), vehicle data, mech walker legs, mechanical masks, emissive and glass, convex decomposition plus UCX, sockets/collision routing, rigid mech split, cables/hoses/tracks, hard-surface budgets, lightmap UV1.
**Fixture test:** an armoured-bull variant (plates rigid, sharp edges kept) plus a cart fixture: wheels roll with the correct radius, the door hinges, collision hulls import, and the cart drives as a Chaos Vehicle in UE and with WheelColliders in Unity.

### M10 — Physics, LODs, animation and full engine assembly (≈10–12 weeks)
Full UE and Unity import, validation V6–V13, full in-engine review sheet, physics body fitting with mass, joint limits for each body plan, drop test, hitbox zones and surfaces, controller capsule, UE physics plugin, Unity ragdoll builder, skinned LODs with bone removal, budget one-click reduce, IK Rig and Humanoid/Generic avatar, starter animation set (procedural gaits for each body plan, licensed retargets, root motion) with real-animation test.
**Fixture test:** one click from Export to a UE and Unity contact sheet. The bull ragdoll drops without a spinning head, the head hitbox multiplier is set, LOD0–3 switch cleanly, and the procedural quadruped walk and idle-with-breathing pass the foot-slide badge. The humanoid runs a Lyra locomotion set.

### M11+ — AAA and specialist extras (pick per production need)
Correctives and helper bones, expression wrinkle and joint wrinkle maps, multi-head, stylised eyes/mouth and the toon pipeline (outlines, proxy normals, SDF, ramps, style profile), stylised deformation (shear check, B-bone conversion, bulge), translucency classes (TM, interior, masters, sorting, dissolve, inner core), wings (membrane, feathered, hexapod), AI tier of hidden-surface regeneration, tear line/caruncle/occlusion, cloth masks and colliders, damage (manifest, mask, dismemberment cut loops, fracture, vehicle states, weak points), crowds (VAT/BAT, impostors, crowd profile), UE groom, regional AI re-texture, decals and scars, vertex-colour profiles, sway, partial re-retopology with shape-key transfer, mechanical articulation export.

**Total before M11: about 70–90 weeks for one developer.** Re-plan after M3 with measured director time per asset.

---

## 5. Risks and what must be verified on the director's PC

### 5.1 Run the probe first (M1, blocks everything)
Run `addon_probe.py` inside the director's Blender 5.3 and save the output to the repo. Check:

**Auto-Rig Pro 3.79.17.** Most ARP facts were confirmed on 3.70–3.77 source only.
- `show_limb_params.get_rna_type().properties`: facial_* flags, lips_amount, jaw_rotation, tongue_amount, tail_count, tail_side, neck and spine counts, load_settings_when_exec.
- `add_limb` preset IDs (tail, ears, spline_ik, bbones) and the context they need. They touch `space_data` and crash headless without `temp_override`.
- `auto_rig.set_ears`, `bone_tag_add` / set_bone_tag parameters, `check_rig_export`, `fix_rig_export`, `ge_save_preset` / `ge_load_preset`.
- Generated facial bone names (jaw_ref.x, c_eyelid_*, c_teeth_*, tong_*, c_jawbone.x) and the parent of c_teeth_bot_master.x.
- Export properties: arp_full_facial, arp_bake_only_active(_slot), arp_simplify_fac, arp_ge_startend_keying_sk, enums of arp_bake_type / arp_frame_range_type, arp_export_rig_type, softlink storage, root bone and IK bone options, bone axis/roll options per engine.
- Whether Humanoid strips cc_ bones; whether cc_ bones survive re-match; dog/horse presets, the 3-bone leg option, foot-roll pivots for quadrupeds; wings/feather option names.
- Jaw-open axis and sign: test both.

**Quad Remesher.** Read `scene.qremesher` properties: the X-symmetry name, use_materials, use_vertex_color, use_normals, autodetect_hard_edges, adaptive_size. Then run three test remeshes on the bull: (a) material bands become loops (joint rings, eye/lip rings, cut loops); (b) the open mouth slit and eye apertures stay open borders with parallel rings; (c) hard edges are kept with pre-marked sharps. Add (d): an asymmetric fixture with symmetry off.

**UVPackmaster 4.** Operator and property names via `dir(bpy.ops)` for: locked islands, per-island scale and texel density, disabling stacking/mirroring per island, margin in texels, packing into a second UV channel, packing several objects into one atlas.

**Blender 5.3 API.** Smoke-test each:
- bmesh slots: split_edges, extrude_edge_only, grid_fill on odd loops, bridge_loops, subdivide_edgering.
- `modifier_apply_as_shapekey(keep_modifier=True)` under temp_override.
- `datalayout_transfer`, `normals_split_custom_set` / the custom_normal attribute.
- `bake.margin_type` values, `img.save` plus `filepath_raw`, `image_settings.media_type`.
- Slotted actions: action_slot assignment, `channelbag.fcurves`, `anim_utils.bake_action_objects`.
- `id_properties_ui`, the Kuwahara node, `uv.lightmap_pack`, AO node inside/only_local.
- Back-face behaviour of `BVHTree.ray_cast`, `shade_smooth_by_angle`.
- FBX exporter axis and `apply_unit_scale` behaviour in 5.3.

**External processes on the director's Windows PC (RTX 4080).** MediaPipe, CoACD and the VLM/image-edit clients must run in a separate Python subprocess, not Blender's. A local ComfyUI is needed for regional re-texture and the corrected-image tier. The X-Part / HoloPart light release is unverified on Windows. Headless UE and Unity must run from the same machine with pinned versions.

**Tripo.** Segmentation v2 parameters and small-part quality, whether re-texture accepts a mask, whether text and image prompts combine, whether the GLB alpha means anything, whether a pose parameter exists, and the licence and commercial terms for generated assets.

### 5.2 Engine side (verify once per engine version and pin it)
- **UE:** Interchange vs legacy FBX option names (`Interchange.FeatureFlags.Import.FBX`), how the .x suffix is handled, socket and UCX bugs (UE 5.5 rename drops UCX), Pose Asset curves no longer auto-added, IK Retargeter API changes in 5.6, PhysicsAsset is opaque to Python (so the C++ plugin is required), AnimGraph nodes cannot be made from Python (template ABPs are built by the developer once), Chaos Vehicle wheel bone requirements, headless MRQ, validator method names.
- **Unity:** URP `SetupMaterialBlendMode` availability, Blend Shape Normals option, blendshape weight range 0–100, MaterialPropertyBlock vs SRP Batcher, `Camera.Render` under URP in batch mode, 4-influence and bone count messages, Generic vs Humanoid avatar for quadrupeds, WheelCollider axis conventions.

### 5.3 Product risks
- **Unverified thresholds.** Every threshold (sphere-fit residual, PCA ratios, fusion 1.5%, loop counts, budgets, viseme mixes, limit tables) is a starting value. Tune on 10–20 real Tripo assets per body plan and expose the important ones as sliders.
- **Repair ordering.** Repair, weld or hole-fill will silently close new cuts (mouth slit, eye apertures, pockets, cut loops) unless they are tagged and skipped. The regression test ships in M2, before any face cut exists.
- **Silhouette changes after face work.** Any step that moves geometry after M4 (stance, hidden-surface regen, partial re-retopology) must replay face cuts and transfer shape keys through edit records, or the face is lost.
- **Unreliable detection.** Stylised and creature faces, fused AI parts, mitten hands, unusual body plans and mech pivots all need the 2D click fallback from day one, not added later.
- **Hidden modelling skill.** Any fallback that asks for 3D selection, curve editing, weight painting or bone placement breaks the non-modeler rule. Review every new ADJ against the section 1 rule before shipping.
- **Render time** for approval sheets (52+ face thumbnails, ROM, turntables). Use Workbench or low-resolution EEVEE and cache. Track director minutes per asset against the ≤ 30-minute target.
- **Mobile cost.** Alpha overdraw on tile GPUs (1 lash strip per eye), extra material slots mean draw calls (merge them), morph memory, 75 bones per section.
- **Animation sourcing.** There are almost no licence-safe quadruped clips. The procedural gait generator is on the critical path, not optional.
- **Licences.** SMPL is not free for commercial use; GASP/Starter Assets are engine-locked; Mixamo is manual and local only; intrinsic-decomposition, image-edit and paint models have unverified licences; Tripo output terms must be recorded per asset.
- **Stability.** Blender 5.3 with QR, UVPM and ARP plus subprocesses will crash. Snapshots and resume (M1) are a requirement, not a convenience.
- **Scope creep.** The face (M4–M5) and engine assembly (M10) are the largest blocks. Do not start M11 items until M1–M5 pass on the bull and on the humanoid, flyer, serpent and vehicle-prop fixtures.