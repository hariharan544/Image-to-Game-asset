# Research gap: Non-human and stylised facial rigs (animal, beak, insect, cartoon)

# Forge: research report on non-human and stylised facial rigs

Scope: the expression set, rig, topology and texture Forge should generate for faces where ARKit 52 does not fit. This covers dog and cat, horse and cow, bird, reptile, insect, fish, cartoon and anime, and multi-head characters. It also covers how faces with no ARKit mapping are driven in UE5 and Unity.

On sources: the official Auto-Rig Pro docs (lucky3d.fr) and Epic docs (dev.epicgames.com) could not be fetched from this session because the network blocked them. Claims about ARP and UE come from search snippets of those pages, the Superhive changelog and the Blender Artists ARP thread. Anything I could not confirm against a primary page is marked **UNVERIFIED**. Every polygon, bone and shape-key count below is a **Forge recommendation**, not a sourced figure.

---

## 0. Key decisions for Forge

1. **Add a `face_profile` per asset** that picks the shape set, bone layout and material features. Proposed values: `human`, `muzzle_long` (dog, wolf, fox), `muzzle_short` (cat, bear, rabbit, tiger), `equine`, `bovine`, `avian`, `squamate` (lizard, snake), `crocodilian`, `amphibian`, `insect`, `fish`, `toon`, `anime`, plus a `multi_head` modifier. The muzzle_long / muzzle_short split is the same one OmniFaceRig (2026) uses for its non-human face templates [S1].
2. **Keep ARKit names wherever the meaning carries over** (`jawOpen`, `eyeBlinkLeft`, `mouthClose`, `noseSneerLeft` and so on). Add creature shapes as extensions in the same camelCase-plus-`Left`/`Right` style, and record each one in a `face_manifest.json`. That way ARKit capture (Live Link Face, Audio2Face) still drives the overlapping part, and the manifest says how to remap the rest.
3. **Base creature expressions on the animal FACS systems** (DogFACS, CatFACS, EquiFACS), not human FACS. DNEG built its production dog face controls on DogFACS: a growl is upper-lip raiser + nose wrinkler + lip pucker [S2][S3]. These systems use AUs, ADs and a separate set of Ear Action Descriptors (EADs) [S3][S4].
4. **Generate shapes from bones, then bake them.** Forge places bones (ARP plus custom `cc_` bones), poses them with a script, and saves each pose with `bpy.ops.object.modifier_apply_as_shapekey(keep_modifier=True, modifier="Armature")` into shape keys. Corrections come from Geometry Nodes or masked displacement. The director approves a contact sheet of the shapes.
5. **Drive stylised eyes and mouths through the material,** using UV offset and atlas or flipbook index, not geometry. UE uses Material-type animation curves [S5]. Unity uses a script that sets MaterialPropertyBlock values. VRM 1.0 formalises the same idea with `textureTransformBinds` and `materialColorBinds` on expressions (**UNVERIFIED**: from memory of the VRM spec, not fetched).

---

## 1. Shared infrastructure (every profile)

### 1.1 Shape-key / morph-target naming convention

- **Format:** `<region><Action>[Left|Right]` in camelCase, the same as ARKit. Bilateral shapes are always split into Left and Right. A centre shape has no suffix.
- **Regions:** `jaw`, `mouth`, `lip`, `muzzle`, `nose`, `nostril`, `cheek`, `brow`, `eye`, `nictitate`, `ear`, `whisker`, `beak`, `throat`, `gill`, `mandible`, `palp`, `antenna`, `pupil`, `crest`.
- **Prefixes for non-mesh channels** (these become engine curves with no morph target):
  - `mat_` for material scalars, such as `mat_wrinkleMuzzle`, `mat_eyeFrame`, `mat_mouthFrame`, `mat_pupilOffsetX_Left`.
  - `ctl_` for procedural or physics toggles, such as `ctl_earJiggle`.
- **Multi-head:** suffix `_h1`, `_h2`, `_h3`, for example `jawOpen_h2`. The first head (`h1`) has no suffix, so it stays compatible with ARKit and MetaHuman tooling.
- **Correctives:** `corr_<shapeA>__<shapeB>`, for example `corr_jawOpen__snarlLeft`. These are applied by a driver or curve, never keyed by animators. CGMA reports that Unreal did not read the correctives from a Maya blendshape rig, so the correctives were added as attributes on the controllers. In Forge, correctives should be explicit curves computed in the AnimBP or Control Rig, or by a Unity script [S6].
- **Manifest** (`face_manifest.json`, exported next to the FBX), with one entry per channel:

```json
{"name":"snarlLeft","type":"morph","region":"lip","side":"L",
 "facs":"DogFACS AU110+AU109 (UNVERIFIED codes)",
 "arkit_fallback":{"mouthUpperUpLeft":1.0,"noseSneerLeft":0.8},
 "viseme_use":null,"mobile":true,"head":1}
```

The engine importers (section 5) read `arkit_fallback` to build UE Pose Asset or remap tables and Unity ScriptableObject maps automatically.

### 1.2 How Forge generates shapes (applies to every feature below)

| Method | Use for | bpy |
|---|---|---|
| Bone pose → shape key | Jaw, beak, ears, mandibles, gills, lids, lip curls | Pose with ARP or custom bones, then `modifier_apply_as_shapekey(keep_modifier=True)`, then reset the pose |
| Masked procedural displace | Nostril flare, throat sac, cheek puff, muzzle bunching | A vertex-group mask built from geodesic distance to a seed vertex (bmesh BFS over edges). Displace along the normal or toward a pivot. Bake with `shape_key_add(from_mix=False)` and write coordinates |
| L/R split | Every bilateral shape | Duplicate the shape, multiply its delta by a smooth X-side falloff (sigmoid over ~1 cm across the midline) |
| Tension (compression) attribute | Driving wrinkle-map masks | In Geometry Nodes, compare edge length between Basis and the shape, store as a colour attribute, then bake to a texture mask |
| AI-generated part | Gums, nictitating membrane shell, anime eye or mouth atlas, wrinkle normal detail | Image or 3D generation, then fit |
| Director click | Mouth corners on a closed Tripo surface, beak hinge point, ear base, eye centre when sphere fitting fails | A single click in a modal operator; Forge snaps to the nearest vertex |

Detection heuristics for Tripo meshes:
- **Eyes:** RANSAC sphere fit on head-region vertices. A low residual means a spherical eye. A high residual with an ellipsoid fit means a flattened (cartoon) eye.
- **Beak or keratin:** a sharp dihedral-angle crease loop combined with a hue or roughness break in the baked albedo.
- **Ears:** protrusions found by geodesic extremities above the skull.
- **Mouth line:** concavity plus a dark albedo line. If confidence is under a threshold, Forge asks for the two-corner click.

Then `bpy.ops.mesh.shortest_path_select` between the corners, edge split, and the mouth bag from the earlier research.

### 1.3 ARP on non-human heads

- The ARP product page says non-humanoid characters (horse, dog) are rigged manually without Smart detection [S7].
- Recent changelog entries add removing all eyelids (amount set to 0) and separate auto-eyelid settings for upper and lower lids [S7]. Use amount 0 for insects, fish and snakes.
- The developer's guidance on reference placement (Blender Artists thread, v3.72): eyelid bone tails sit on the eyelid geometry, lip bone heads sit on or slightly ahead of the lips, skull bones run along the head height, and eyebrows are designed for shape keys, with an option for the bones to deform instead [S8].
- Faceit works alongside ARP, but its automatic expressions cannot use the ARP face rig [S9].
- **UNVERIFIED** (from memory of ARP 3.7x, not checked against the docs):
  - Facial feature toggles: eyebrows, eyelids, lips, teeth, tongue, chin, nose, cheeks.
  - Control bone names: `c_jawbone.x`, `c_lips_top.x`, `c_lips_bot.x`, `c_lips_smile.l/.r`, `c_eyelid_top.l`, `c_eyelid_bot.l`, `c_eye.l`, `c_eye_target.x`, `c_eye_offset.l`, `c_nose_01.x`, `c_chin_01.x`, `c_tong_01.x`.
  - Ears as a separate limb with a configurable bone count (`c_ear_01.l`…).
  - Custom bones prefixed `cc_` are kept by the Game Engine export.
  - Forge must read the real names from the generated armature at runtime, not hard-code them.
- **Practical rule:** for long-muzzle heads, align the lip-line references along the muzzle. An unstraightened animal lip line deforms badly (a Blender Studio facial-rigging thread reports this on a wolf head) [S10].

---

## 2. Per-feature specifications

### 2.1 Dog and cat (muzzle_long / muzzle_short): snarl, lip curl, muzzle wrinkle, ear pin and swivel, nostril flare, whiskers

**(a) Why it matters:** this is the main threat and emotion read for quadrupeds, shown at gameplay distance by ears and body and in close-up by snarl and wrinkle. Ears give the read even on mobile LODs.

**(b) Topology**
- Concentric loops around the upper lip (the dog's flews) and around the lower lip.
- Three to four vertical loops running from the nose pad to the brow, for the wrinkle bunching.
- Two loops around each nostril.
- One loop ring at the ear base, so the ear can rotate without shearing the skull.
- The gum line must be separate geometry, or a part of the mouth bag, visible when the lip lifts. Re-use the mouth-interior research.
- Whiskers: alpha cards or a separate strand-card mesh.
- Budget, AAA hero: 2–4k triangles for the head region. Mobile: 600–1.2k.

**(c) Rig**
- **Bones:**
  - jaw;
  - 3–5 upper-lip bones per side, following the flews;
  - 2 lower-lip bones per side;
  - nose tip;
  - ears: a 2–3 bone chain each (cat 2, floppy dog ear 3–4);
  - whisker pad bone per side.
- **Ear motion:**
  - Ear pin: rotate the ear base about the lateral axis, about −60° to −90°.
  - Ear swivel: rotate about the ear's local up axis, ±90°. Cats need it; horses even more.
  - Floppy ears: engine-side secondary motion (UE AnimDynamics or Spring Controller; Unity spring bones or Magica Cloth). These are general engine features; the node names are **UNVERIFIED** in this session.
- **Morphs (AAA):**
  - `snarlLeft/Right` (upper-lip raiser plus nose wrinkler);
  - `lipCurlUpperLeft/Right`;
  - `lipCurlLowerLeft/Right`;
  - `muzzleWrinkle` (nose wrinkler);
  - `nostrilFlareLeft/Right`;
  - `lipCornerPullLeft/Right` (pant or "smile");
  - `lipPucker`;
  - `cheekPuffLeft/Right`;
  - `browInnerUp` (puppy eyes; DogFACS AU101 [S2]);
  - `tongueOut`;
  - `pantLoop` (AD for panting, **UNVERIFIED** code);
  - `whiskerForward/Back` (cat);
  - `earPinLeft/Right` and `earSwivelLeft/Right` as bones, with optional corrective morphs at the ear base.
- **Mobile:** jaw bone + `snarl` (merged L/R) + `earPin` as bone + `blink`.
- **ARKit fallback:**
  - `snarl` ← `mouthUpperUp` + `noseSneer`
  - `lipCornerPull` ← `mouthSmile`
  - `nostrilFlare` ← `noseSneer` × 0.5
  - `browInnerUp` is identical.

**(d) Texture and material**
- A muzzle wrinkle normal map blended in by a mask, driven by `mat_wrinkleMuzzle` (the same principle as MetaHuman animated wrinkle maps).
- A gum and lip-lining colour region with a wet roughness mask.
- Nose leather: roughness and normal detail.
- Fur on the muzzle uses the fur-card research. Lift-off cards on the upper lip must be skinned to the lip bones.
- SSS on the ears (thin, back-lit) using a thickness map baked from the dense mesh (inverted AO or thickness bake).

**(e) Automation**
1. Find the ear base with the extremity heuristic. The director confirms with one click.
2. Find the nose tip as the frontmost point on the head's forward axis.
3. Place the lip line from the mouth-corner clicks.
4. Generate the lip bones along that line, evenly spaced, as `cc_lipUp_01.L`… if ARP lips cannot follow the flews (**UNVERIFIED** whether ARP lips handle long flews).
5. Create the shapes by bone pose and apply-as-shapekey. The muzzle wrinkle is a masked displace: compress along the forward axis inside the geodesic mask from the nose bridge, plus the tension attribute for `mat_wrinkleMuzzle`.
6. The wrinkle normal can be procedural (ridge noise oriented across the bridge) or AI-generated from the albedo crop.

Research shortcut: OmniFaceRig generates up to 155 blendshapes, inner mouth included, on long and short muzzles [S1]. Code availability and licence are **UNVERIFIED**, so treat it as a future replacement, not a dependency.

**(f) Engine**
- **UE:** morphs drive curves by name. Enable the Morph Target curve type, and set the Material curve type for the `mat_` curves [S5][S11]. Ear physics in the AnimBP.
- **Unity:** `SetBlendShapeWeight` (0–100). Material scalars set from blendshape weights in a `LateUpdate` script. Ear physics with a spring-bone package.
- **Mobile:** bake the wrinkle effect into a single mask-lerp, and cap at 4 skin influences.

### 2.2 Horse and bovine lips

**(a) Why it matters:** the horse's upper lip is prehensile (grazing, flehmen curl, nuzzling). Cattle chew with a sideways (lateral) jaw motion. Horse ear and nostril reads are the main emotion signal (EquiFACS has ear-specific EADs [S4]).

**(b) Topology**
- A dense, separately looped upper lip (4–5 loops) that can roll up and back.
- Nostril rings deep enough to dilate (horses flare a lot).
- Cow: a thick dewlap (neck skin fold) gets 2–3 loops if it will be animated.

**(c) Rig**
- **Horse morphs:** `lipUpperCurl` (flehmen; EquiFACS upper-lip curl, code **UNVERIFIED**), `lipUpperExtend` (prehensile reach), `lipUpperGraspLeft/Right`, `lipLowerDroop` (relaxed), `nostrilFlareLeft/Right` (EquiFACS nostril dilator, cited as AD38, **UNVERIFIED**), `chinRaise`, `eyeWhiteShow` (EquiFACS AD1 "eye white increase", **UNVERIFIED**), `blinkHalf`.
- **Horse ears:** bone chains for `earForward`, `earBack` (pinned) and `earRotate`, matching EquiFACS EAD101/103/104 (codes **UNVERIFIED**).
- **Bovine:** the jaw needs lateral rotation (yaw) plus a small forward-back translation for the chewing loop. Make this an AnimBP procedural loop, not a morph. Morphs: `tongueWrapLeft/Right` (prehensile tongue) and `noseLick`.

**(d) Texture:** nose and lip skin with low-fur regions (a fur-card exclusion mask), a whisker or bristle alpha, wet roughness inside the nostril, and a dark nostril interior (an AO-weighted colour, or a small inset mesh).

**(e) Automation:** same pipeline as 2.1. The `equine` profile adds the lip-curl bone (a hinge at the upper lip, rotating up and back). The bovine profile adds a `cc_jaw_lateral` controller or a constraint on the ARP jaw.

**(f) Engine:** the chewing and grazing loop is better as an engine-procedural layer (UE Control Rig sine on the jaw yaw; Unity script), so it can run alongside locomotion.

### 2.3 Bird: beak open, beak bone setup, nictitating membrane

**(a) Why it matters:** the beak is rigid keratin, so it must never bend like lips. A bird's expression comes from the crest, the eye and the nictitating membrane. The membrane is a strong close-up "creature" detail. Biology: the membrane is translucent, sweeps horizontally from front to back (nasal to temporal), can be partly drawn, and the bird keeps some vision through it; in owls it is opaque [S12][S13].

**(b) Topology**
- The beak is a separate rigid shell, or at least split along the gape line (tomium).
- Rhamphotheca vertices are rigid-weighted (1.0 to a single bone).
- One soft transition loop at the cere and gape corner (rictus), where skin meets beak.
- Eyes: spherical, with upper and lower lids. Birds close mainly with the lower lid; that is a general biology claim, not fetched.
- **Nictitating membrane:** a separate thin hemispherical shell (radius ~1.01× the eye), sitting between cornea and lids, about 40–80 triangles.
- Budget: AAA head 1.5–3k triangles. Mobile: 400–800.

**(c) Rig**
- `beak_lower` (jaw) hinges at the quadrate.
- `beak_upper` hinge at the craniofacial (frontonasal) joint. Parrots and many birds lift the upper beak (cranial kinesis; general biology, **UNVERIFIED** here).
- In ARP: map the lower beak to `c_jawbone.x` (**UNVERIFIED** name), and add `cc_beak_upper` as a custom bone.
- Tongue: the ARP tongue limb from the earlier research, 3 bones.
- Nictitating membrane per eye:
  - Bone `cc_nictitate.L` at the front (nasal) eye corner, rotating about the eye's vertical axis to sweep across. Alternatively a morph `nictitateLeft`, which is cheaper on mobile.
  - The membrane mesh is parented to the eye socket, not the eyeball (it must not follow gaze).
- Crest or feathers: a bone chain per crest group, morph `crestRaise`.
- Morphs: `beakOpen` (bone-generated, reference only), `throatPouchInflate` (pelicans, frigatebirds), `featherFluff` (a scale on feather cards from the head bone).
- **ARKit fallback:** `jawOpen` → lower beak; `eyeBlink` → lid plus partial nictitate. Lip-sync for talking birds is jaw only: map viseme open-ness to `jawOpen` and `beak_upper` × 0.3.

**(d) Texture and material**
- Beak: a separate material slot or masked region, glossy keratin (low roughness, slight clearcoat), optional anisotropic streak along the beak length.
- Membrane:
  - UE translucent material, opacity 0.3–0.5, slight milky tint, Fresnel rim.
  - Unity URP Transparent material, or a dithered opaque version for mobile (avoids sorting issues).
  - Owl variant: opaque, feather-coloured.
- Eye: refraction or parallax iris (the human-eye research applies).
- Cere and orbital skin: a tint mask for colour variants.

**(e) Automation**
1. Detect the beak with the crease-loop plus albedo-hue heuristic, then auto-split it to a separate rigid part or vertex group.
2. The hinge points come from the beak base loop: the director confirms one click for the upper hinge if confidence is low.
3. The membrane shell is generated procedurally: a UV sphere around the fitted eye sphere, the front hemisphere kept, then trimmed by the lid opening.
4. Forge auto-creates the eyelid rig with ARP eyelids if lids exist on the mesh. Tripo usually closes them, so lids may need to be built: an inset ring from the eye boundary, extruded as lids.

**(f) Engine:** the membrane needs depth-sort care (UE "Translucency Sort Priority"; Unity render queue Transparent+1), both **UNVERIFIED** for this specific case. On mobile, prefer the dithered opaque version.

### 2.4 Reptile and amphibian: jaw, throat sac, dewlap

**(a) Why it matters:** squamates and crocodilians have essentially no lip musculature. Their expression is jaw gape, the eye (lids and membrane on crocodiles and many lizards; snakes have no lids, only a fixed spectacle) and the throat display (anole dewlap, frog vocal sac, lizard gular pumping for breathing). These are general biology claims, not fetched.

**(b) Topology**
- A clean lip-scale line: rigid labial scales weighted to the jaw or skull.
- Throat sac or dewlap: an extra fan of 3–5 radial and concentric loops, so it can inflate 2–5× without collapsing. On the frog vocal sac, quads must stay even.
- Snake: a jaw split at the front of the lower jaw (mandibular symphysis), so the two lower-jaw halves can spread (open and widen for swallowing).

**(c) Rig**
- **Bones:**
  - jaw;
  - snakes: `cc_jaw_L` and `cc_jaw_R` (two lower-jaw halves) plus a quadrate swing;
  - `cc_hyoid` (drives the dewlap and throat);
  - tongue chain: snakes and monitor lizards need a forked tongue with 4–5 bones plus a fork split; re-use the ARP tongue limb;
  - eyelids where the species has them (amount 0 for snakes).
- **Morphs:** `throatSacInflate`, `dewlapExtend`, `gularPump` (a small breathing loop), `nostrilClose` (crocodile), `nictitateLeft/Right` (crocodile).
- **Mobile:** jaw + `throatSacInflate`.

**(d) Texture and material**
- Throat sac: a stretch mask (from the tension attribute) to lighten colour and raise translucency when inflated, with SSS (frog: a thin membrane). Driven by `mat_throatStretch`.
- Scales: a tileable scale normal detail map in UV2, or a triplanar detail.
- Snake spectacle: an eye with a clearcoat layer, no lids.

**(e) Automation**
- Detect the throat region as the ventral area between jaw and neck.
- The inflate morph is generated procedurally: displace along the normal inside a geodesic mask with a smooth falloff, plus a Laplacian smooth pass.
- The dewlap is often not modelled by Tripo. Either generate a fin-like extrusion procedurally from a director-clicked midline, or have the AI generate the part.

**(f) Engine:** the breathing `gularPump` loop is procedural (sine curve in AnimBP or Control Rig; Unity script) so it layers over any animation.

### 2.5 Insect: mandibles, palps, antennae, compound eyes (no lids)

**(a) Why it matters:** insects have rigid exoskeletons with no soft-tissue face. Expression is purely mechanical: mandible open, close and clack; palps fidget; antenna sweep. The eye cannot blink, so "aliveness" comes from shader effects (the moving pseudopupil, iridescence).

**(b) Topology**
- Mandibles, maxillae, palps and antenna segments are **separate rigid meshes**, or rigid-weighted parts. Treat them like the mechanical-rig research: each part is 100% weighted to one bone.
- Compound eye: a low-poly smooth dome, about 100–300 triangles. The facets come from the normal or detail map, not geometry.

**(c) Rig**
- **Bones:**
  - `cc_mandible_L` / `cc_mandible_R`: yaw rotation about the head's vertical axis (they open sideways, not down);
  - `cc_maxilla_L/R`;
  - palps: 2–3 bone chains;
  - antennae: 4–8 bone chains (the ARP tail or spline-IK limb from the earlier research);
  - labium (lower lip plate).
- **No morphs** are required. Bone-only, which suits mobile well.
- Engine-side: procedural antenna sway (spring or jiggle).
- `eye*` ARKit channels map to nothing. Set ARP eyelids to 0 [S7].
- Lip-sync for talking insects: map viseme open-ness to `mandibleOpen` (driving both mandible bones) plus a palp flutter. This is a stylistic choice.

**(d) Texture and material**
- Compound eye:
  - a hex ommatidia normal or detail map, tileable, in UV2 or triplanar;
  - **pseudopupil**: a dark spot where the view vector aligns with the facet normal. In the shader, `pow(saturate(dot(N, V)), k)` darkens the albedo, so the eye seems to "look at" the camera;
  - thin-film iridescence through a Fresnel-driven hue ramp.
- Exoskeleton: clearcoat, anisotropic on beetle elytra, and an emissive mask for bioluminescent species.
- **Mobile:** matcap or a simple Fresnel ramp instead of thin-film.

**(e) Automation**
- Mandible detection: two mirrored protrusions in front of the head.
- Forge segments them from the Tripo mesh. Tripo often fuses them, so the director clicks each mandible tip once, Forge grows the region by curvature and auto-separates it (`bpy.ops.mesh.separate(type='SELECTED')`).
- Pivot = the centroid of the boundary loop; Forge adds the bone and rigid weights.
- Compound eye = a large convex region with a low-residual sphere fit and an albedo that is dark or high in hex frequency. Forge assigns the `M_CompoundEye` material and generates a hex normal map procedurally (a Voronoi or hex pattern in a Blender shader, baked).

**(f) Engine:** the pseudopupil is pure shader (no curves). UE: a Material Function. Unity: Shader Graph with a View Direction node.

### 2.6 Fish: mouth, gill (operculum), barbels

**(a) Why it matters:** the idle "breathing" loop of mouth and gill pumping is what sells a living fish. Some fish protrude their jaws when feeding (premaxilla protrusion).

**(b) Topology**
- Operculum (gill cover): a separate flap or split edge so it can hinge outward, with gill-slit geometry or a dark interior behind it (a mini "gill bag", like the mouth bag).
- Lips: a ring of 2–3 loops for an O-shaped open.
- Barbels: bone chains, or plain alpha cards on mobile.

**(c) Rig**
- **Bones:** jaw; `cc_premaxilla` (protrusion translate); `cc_gill_L/R` (hinge at the front edge); barbel chains.
- **Morphs:** `mouthProtrude`, `mouthO`, `gillFlareLeft/Right`, `cheekPuff`.
- **Engine:** a procedural breathing loop in which mouth open is phase-offset from gill flare.
- **Mobile:** do the whole thing as vertex animation in the shader (a sine on a vertex-colour mask) with no bones. That is common practice for background fish; **UNVERIFIED** as a specific source.

**(d) Texture:** iridescent scales, an anisotropic or thin-film Fresnel ramp, a red gill interior with an emissive-free, high-SSS colour, and a wet clearcoat.

**(e) Automation:** detect the gill slit as a crease arc behind the eye. If it is missing, the director draws it with two clicks and Forge cuts it with a shortest path. The protrusion and gill shapes come from bone pose and apply-as-shapekey.

**(f) Engine:** UE: Control Rig or AnimBP sine on the curves. Unity: a script, or a VAT/vertex shader for schools of fish.

### 2.7 Cartoon and anime eyes and mouths (non-spherical)

**(a) Why it matters:** stylised characters have flattened or oval eyes that cannot rotate as spheres without poking through the skull. Expressions are often graphic: ^ ^ happy eyes, sparkle, sweat, X eyes. Mouths may be 2D shapes.

**(b) Topology: three supported eye types, recorded in the manifest as `eye_mode`**
1. **`scaled_sphere`**: a sphere eye with non-uniform scale on the eye bone. The geometry stays a sphere internally, so rotation still works. Lids are shaped around the scaled eye.
   - Requires scale-inherit settings that survive FBX. UE supports non-uniform bone scale, but scale on parent bones propagates (**UNVERIFIED** for the ARP export path).
   - Safer: scale only a leaf "eye_scale" bone that has no children.
2. **`flat_uv`**: the eye is a flattened lens shape conforming to the face. The iris and pupil are texture layers whose UVs are offset from bone rotation (the Godot community pattern: a pupil mask layered and moved by UV offset [S14]).
   - Topology: a single grid patch, 50–150 triangles, with lid geometry over it or lid morphs.
3. **`decal_plane`**: separate pupil or eye-shape planes in front of the eye white, with alpha, moved by bones. Extra eye shapes can be hidden inside the head and swapped in [S14].
   - Cheap and mobile-friendly. Prefer alpha-clip over blend to avoid sorting problems.

**Mouths:**
- a 3D mouth with the mouth bag (a toon variant of the human research), or
- a **texture-swap mouth**: a flipbook atlas of 8–16 shapes on a mouth patch, chosen by a `mat_mouthFrame` index.
- Many anime games mix both (3D jaw plus a texture interior). Hybrids are **UNVERIFIED** as a specific citation. The Guilty Gear Xrd material shows close-up toon characters relying heavily on vertex and UV data rather than textures [S15], but I could not confirm their exact eye and mouth mechanism.

**(c) Rig**
- **flat_uv:** keep ARP `c_eye.l` / `c_eye_target.x` (**UNVERIFIED** names) as the controls. A non-deforming "eye_look" bone feeds the engine, which converts its local rotation to `mat_pupilOffsetX/Y_Left/Right`.
- **Anime expression set** (VRM 1.0 presets, adopted as Forge toon names; **UNVERIFIED**, from memory of the VRM spec):
  - emotions: `happy`, `angry`, `sad`, `relaxed`, `surprised`;
  - visemes: `aa`, `ih`, `ou`, `ee`, `oh`;
  - blinks: `blink`, `blinkLeft`, `blinkRight`;
  - gaze: `lookUp`, `lookDown`, `lookLeft`, `lookRight`;
  - `neutral`.
- **Extras:** `eyeHappyArcLeft/Right` (^ shape, a morph or a `mat_eyeFrame` swap), `eyeSparkle` (emissive layer toggle), `pupilDilate`, `pupilShrink`, `eyeSquashLeft/Right` (non-uniform scale on the eye bone), `browAngry`, `browSad`, `cheekBlush` (`mat_blush`), `sweatDrop` (a hidden card mesh bone-scaled from 0 to 1).

**(d) Texture and material**
- **Eye material** parameters:
  - `PupilOffset` (vector2);
  - `PupilScale`;
  - `IrisTex`;
  - `EyeFrame` (atlas index);
  - `HighlightOffset`, a specular highlight that is **not** moved with the pupil so it stays fixed relative to the light or camera.
- Clamp the pupil offset inside an elliptical mask so it never leaves the white.
- Mouth material: `MouthFrame` atlas index, with the atlas sized as a power of two (4×4 of 256 px each on mobile).
- Blush, sparkle and tears: emissive or overlay masks in one RGBA mask texture.
- The Blender anime eye generators expose pupil size, colour and position and can bake to textures for games [S14 cluster].

**(e) Automation**
- **Eye-mode choice:** the sphere-fit residual decides. A low residual gives `scaled_sphere`. A high residual on a lens shape gives `flat_uv`, and a decal plane is added when the style is very graphic (the director picks from 3 thumbnails).
- **flat_uv build:**
  1. Project the UVs of the eye patch planar along the eye's forward axis, normalised to 0–1.
  2. Generate the iris and pupil as procedural textures (circle masks), or AI-generate them in the character's style.
  3. Author the atlas (eye frames, mouth frames) by AI image generation in a fixed grid template. The director approves the sheet once.
- **Engine conversion:** the `eye_look` bone rotation becomes a UV offset through a simple linear mapping (yaw/max_yaw → offset_x × max_offset). Forge writes the constants to the manifest.

**(f) Engine**
- **UE:**
  - Material curves: curves named exactly after material parameters drive them during playback [S5][S11]. Use this for `mat_mouthFrame` keyed by lip-sync and for `mat_eyeFrame`.
  - The pupil offset from bone rotation needs an AnimBP or Blueprint step: read the bone rotation and set it on a Dynamic Material Instance, or bake it into a curve with an Animation Modifier at import (**UNVERIFIED** that Animation Modifiers suit this, but the API is generic).
- **Unity:**
  - A `ToonFaceDriver` MonoBehaviour that reads the eye bone's `localRotation` in `LateUpdate` and sets `_PupilOffset` through `MaterialPropertyBlock`. Do the same for `_MouthFrame` from lip-sync.
  - If the project uses UniVRM, its expression system can bind UV-offset and colour to expressions natively (**UNVERIFIED**, from memory).

### 2.8 Multi-head characters (cerberus, hydra, two-headed ogre)

**(a) Why it matters:** each head should animate and lip-sync on its own (desynchronised heads look alive). This is a common boss trope.

**(b) Topology:** treat each head as a full face copy with its own loops, mouth bag and eyes. On mobile, the secondary heads can drop to jaw plus blink only.

**(c) Rig**
- The first head uses ARP's head and face.
- The extra heads use ARP spline-IK or neck chains, with duplicated facial bones as custom `cc_` bones. Whether ARP's Head limb can be duplicated with full facial features is **UNVERIFIED**; Forge must test it. Fallback: build the face for head 1, then copy its bone group with `_h2` renames and re-target the constraints.
- Shape keys get the `_h2`, `_h3` suffixes. Copy shapes between heads after alignment with a mirror or transform match, plus a Surface Deform or Data Transfer modifier, then apply-as-shapekey.

**(d) Texture:** a shared material, with a per-head tint mask channel for variation.

**(e) Automation:**
1. Count the heads by detecting head-like blobs: the skeleton extraction finds multiple neck terminals.
2. The director confirms the head count once.
3. Forge runs the face pipeline per head and suffixes all names.

**(f) Engine**
- UE: one Pose Asset per head, or a single one with suffixed curves. In the AnimBP, a Live Link or audio lip-sync source per head goes through a per-head remap (section 5).
- Unity: one `FaceDriver` component per head, with a `headSuffix` field.

---

## 3. Recommended shape budgets (Forge recommendations, not sourced)

| Profile | AAA morphs | AAA face bones | Mobile morphs | Mobile bones |
|---|---|---|---|---|
| muzzle_long/short | 35–60 | 25–40 | 6–10 | 8–12 |
| equine/bovine | 25–40 | 20–30 | 4–8 | 6–10 |
| avian | 10–20 | 12–20 | 2–4 | 5–8 |
| squamate/crocodilian | 8–15 | 10–20 | 2–3 | 4–8 |
| insect | 0–4 | 10–30 (rigid) | 0 | 6–15 |
| fish | 6–10 | 6–12 | 0 (vertex shader) | 0–4 |
| toon/anime | 25–50 (VRM set + extras) | 15–30 | 10–16 (VRM core) | 8–12 |

Skin influences:
- A faces-with-many-lip-bones guideline: more than 12 lip bones likely needs 8 influences [S6].
- Mobile target is 4 (Forge recommendation).

---

## 4. Lip-sync without ARKit

- **Viseme reduction per profile:**
  - Full Oculus/Meta set of 15: `sil PP FF TH DD kk CH SS nn RR aa E ih oh ou`. These names are the VRChat and Meta convention [S16].
  - Toon/anime: the 5 vowels `aa ih ou ee oh` (VRM).
  - Muzzle and equine: three channels, `jawOpen` + `lipCornerPull` + `lipPucker`.
  - Avian and insect: `jawOpen` (or `mandibleOpen`) only.
  - Texture mouths: viseme → `mat_mouthFrame` index table in the manifest.
- **Unity:**
  - uLipSync analyses audio. Its `uLipSyncBlendShape` component lets you register any blendshape against each phoneme in the profile, so custom creature names work without renaming [S17].
  - Convai's Lip Sync Map shows the same pattern: a map asset from source channels to arbitrary SkinnedMeshRenderer names, with a snake_case example [S18].
  - Forge should generate a ScriptableObject `FaceMap` from the manifest (`arkit_fallback` plus visemes).
- **UE:**
  - Pose Asset route: export the creature shapes as an animation sequence with one pose per frame, then create a Pose Asset from it. Curve-driven animation (FACS or viseme curves) plays through a Pose Asset node in the AnimBP, and other characters can share it via relative deltas [S19][S20].
  - Forum reports since about 5.3 say Pose Asset curves are not automatically added to the skeleton, so Control Rig cannot drive them directly [S21]. Forge should register the curves on the skeleton at import (Python editor script) and verify in-engine.
  - Live Link (ARKit capture to creature): a Live Link remap (Blueprint remap asset) renames and combines ARKit curves using the manifest's `arkit_fallback` weights. The remap asset class name is **UNVERIFIED**.
  - MetaHuman Animator and audio-to-face target MetaHuman rigs and do not map to creatures (**UNVERIFIED** as of UE 5.6/5.7). Treat them as ARKit-like sources and remap.

---

## 5. Implementation snippets (Blender 5.x bpy; API names verified for 2.9x–4.x, assumed stable)

```python
# Bone pose -> shape key (Forge core)
def pose_to_shape(obj, arm, pose_fn, name):
    pose_fn(arm)                                   # set bone transforms
    bpy.context.view_layer.update()
    mod = next(m for m in obj.modifiers if m.type == 'ARMATURE')
    with bpy.context.temp_override(object=obj, active_object=obj):
        bpy.ops.object.modifier_apply_as_shapekey(keep_modifier=True, modifier=mod.name)
    obj.data.shape_keys.key_blocks[-1].name = name
    for pb in arm.pose.bones: pb.matrix_basis.identity()

# L/R split
def split_lr(obj, src, blend_w=0.01):
    kb = obj.data.shape_keys.key_blocks; basis = kb[0].data; s = kb[src].data
    for side, sgn in (("Left", 1), ("Right", -1)):
        k = obj.shape_key_add(name=src + side, from_mix=False)
        for i, v in enumerate(obj.data.vertices):
            x = v.co.x * sgn                       # +X = character left in Blender
            w = 1 / (1 + math.exp(-x / blend_w))
            k.data[i].co = basis[i].co.lerp(s[i].co, w)
```

**UE import step** (Python, editor):
1. Read `face_manifest.json`.
2. For `type == "morph"`, set the curve metadata morph flag. For `mat_*`, set the material flag [S11].
3. Build the Pose Asset from the exported `*_poses` sequence.
4. Write a remap DataTable.

**Unity import step:** an AssetPostprocessor reads the manifest, creates the `FaceMap` ScriptableObject, and sets the mesh import "Blend Shape Normals" option (None for mobile toon). The import option exists; whether None is right for mobile toon is **UNVERIFIED**.

---

## 6. Open items Forge must verify in the user's install

1. ARP 3.79.17: the exact facial bone names, whether the Head limb can be duplicated for multi-head, whether ARP lips can follow long flews, and the ears-limb settings. Allow lucky3d.fr in the network settings to fetch the docs.
2. UE5 skeleton curve registration for Pose Assets after 5.3 [S21]. Also confirm that the Material curve flag lives in curve metadata now that `AACF_DriveMaterial` is marked deprecated [S11].
3. Non-uniform eye-bone scale surviving ARP's Game Engine export into UE and into Unity's Generic rig.
4. The exact DogFACS, CatFACS and EquiFACS codes. Fetch the manuals from animalfacs.com [S4] and the EquiFACS paper (Wathan 2015, PLoS ONE) [S3] before writing the codes into manifests.

---

## Sources

- [S1] OmniFaceRig, arXiv 2606.08043 and project page: https://arxiv.org/html/2606.08043v1 , https://omnifacerig.github.io/
- [S2] befores & afters, "Yep, there's FACS for dogs" (DNEG dogFACS): https://beforesandafters.com/2020/05/04/yep-theres-facs-for-dogs/
- [S3] EquiFACS (Wathan et al. 2015), PMC: https://pmc.ncbi.nlm.nih.gov/articles/PMC4526551 ; DogFACS variables table: https://pmc.ncbi.nlm.nih.gov/articles/PMC9803655/table/Tab1
- [S4] AnimalFACS (DogFACS/CatFACS/EquiFACS manuals): https://animalfacs.com/home ; PeerJ horse ethogram 2025: https://peerj.com/articles/19309
- [S5] UE Animation Curves: https://dev.epicgames.com/documentation/unreal-engine/animation-curves-in-unreal-engine ; UE 4.26 Curves: https://docs.unrealengine.com/4.26/AnimatingObjects/SkeletalMeshAnimation/Sequences/Curves
- [S6] 80.lv facial rigging guidelines for game developers: https://80.lv/articles/animating-speech-mastering-facial-rigging-guidelines-for-game-developers ; 80.lv CGMA student facial rigging: https://80.lv/articles/005cg-cgma-student-project-facial-rigging
- [S7] Auto-Rig Pro on Superhive (features and changelog): https://superhivemarket.com/products/auto-rig-pro , https://superhivemarket.com/products/auto-rig-pro/versions
- [S8] Blender Artists, Auto-Rig Pro 3.72 thread: https://blenderartists.org/t/auto-rig-pro-3-72/672834?page=2
- [S9] Faceit FAQ: https://faceit-doc.readthedocs.io/en/latest/FAQ/
- [S10] Blender Studio facial rigging course: https://studio.blender.org/training/facial-rigging/
- [S11] UE API: IInterface_AnimCurveMetaData / EAnimAssetCurveFlags: https://dev.epicgames.com/documentation/unreal-engine/API/Runtime/Engine/IInterface_AnimCurveMetaData , https://dev.epicgames.com/documentation/unreal-engine/API/Runtime/Engine/EAnimAssetCurveFlags
- [S12] Wikipedia, Nictitating membrane: https://en.wikipedia.org/wiki/Nictitating_membrane
- [S13] All About Birds, owl third eyelid: https://www.allaboutbirds.org/cams/athena-the-great-horned-owl-shows-off-her-third-eyelid/ ; 10000 Birds: https://www.10000birds.com/what-is-a-nictitating-membrane.htm
- [S14] Godot forum, 3D facial expressions from Blender (UV-offset pupils, swap shapes): https://forum.godotengine.org/t/managing-3d-characters-facial-expressions-from-blender-to-godot/130242 ; Kouji's eyes (Unity projector pupils): https://medium.com/@Spooklight_Apps/a-deep-look-into-koujis-eyes-ba22f00e426d ; UE forum, atlas-based 2D eye rig: https://forums.unrealengine.com/t/2d-eye-rig-atlas-based-help-needed/74355 ; Polycount anime eye rig: https://polycount.com/discussion/226547/anime-eye-rig-difficulties ; ArtStation anime eye generator: https://www.artstation.com/marketplace/p/3Ozb/stylized-anime-eye-generator-for-blender
- [S15] Motomura, Guilty Gear Xrd GDC slides: https://www.ggxrd.com/Motomura_Junya_GuiltyGearXrd.pdf
- [S16] VRChat wiki, Visemes: https://wiki.vrchat.com/wiki/Visemes ; Meta OVRLipSync Unity: https://developers.meta.com/vr/documentation/unity/audio-ovrlipsync-unity/
- [S17] uLipSync: https://github.com/hecomi/uLipSync
- [S18] Convai custom blendshape map: https://docs.convai.com/api-docs/plugins-and-integrations/convai-unity-sdk/getting-started/add-lip-sync/create-a-custom-blendshape-map
- [S19] UE Facial Animation Sharing: https://dev.epicgames.com/documentation/unreal-engine/facial-animation-sharing-in-unreal-engine
- [S20] UE Creating a Pose Asset: https://dev.epicgames.com/documentation/unreal-engine/creating-a-pose-asset-in-unreal-engine ; UE 4.27 AnimPose: https://docs.unrealengine.com/4.27/AnimatingObjects/SkeletalMeshAnimation/AnimPose
- [S21] UE forum, Pose Asset curve with Control Rig: https://forums.unrealengine.com/t/pose-asset-curve-with-control-rig/2050344 ; Set Curve Value for Pose: https://forums.unrealengine.com/t/control-rig-set-curve-value-for-morph-target-what-about-set-curve-value-for-pose-from-pose-asset/2414837
- From memory, not fetched (**UNVERIFIED**): VRM 1.0 expression presets and texture-transform binds (https://github.com/vrm-c/vrm-specification), the exact ARP bone names, and the specific AnimalFACS codes.
