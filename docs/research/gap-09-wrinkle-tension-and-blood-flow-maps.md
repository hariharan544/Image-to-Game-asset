# Research gap: Wrinkle, tension and blood-flow maps

# Wrinkle, tension and blood-flow maps for Forge: implementation report

## How this was checked
- **WebSearch was not available.** The turn's shared limit of 200 searches was already used up, so I ran no searches. dev.epicgames.com, docs.unity3d.com and docs.blender.org do not resolve in this session. To check the claims that depend on them, those hosts must be allowed in the session's network settings. Everything that rests only on those sites is marked **UNVERIFIED**.
- **MetaHuman, CONFIRMED from Epic's public repo** `github.com/EpicGames/MetaHuman-DNA-Calibration` (main branch, shallow clone at `/tmp/claude-0/-home-user-Image-to-Game-asset/f1ff8269-309f-546b-b536-494e8126b836/scratchpad/wr/mhdna`). Files read:
  - `examples/dna_viewer_build_rig_with_textures.py`
  - `data/masks/*`, `data/maps/*` (file names and sizes)
  - `docs/dna.md`
  - `dnacalib/DNACalib/include/dna/layers/BehaviorReader.h`, `DefinitionReader.h`
  - `dna_viewer/dnalib/behavior.py`
  - `data/mh4/additional_assemble_script.py`
- **Blender, CONFIRMED in the `blender-v5.3-release` source** on raw.githubusercontent.com:
  - `rna_object.cc:3541`: `Object.add_rest_position_attribute`, described as "Add a "rest_position" attribute that is a copy of the position attribute before shape keys and modifiers are evaluated".
  - `rna_scene.cc`: `use_selected_to_active`, `use_cage`, `cage_object`, `normal_space`, and the bake `target` enum `IMAGE_TEXTURES` / `VERTEX_COLORS`.
  - These geometry-node sources exist: `node_geo_input_mesh_edge_vertices` (outputs Vertex Index 1/2 and Position 1/2), `node_geo_evaluate_on_domain`, `node_geo_blur_attribute`, `node_geo_input_mesh_edge_angle`, `node_geo_store_named_attribute`.
- **Auto-Rig Pro, CONFIRMED in the 3.77.33 source mirror** (scratchpad `arp_src`; the user runs 3.79.17, so re-probe these):
  - `arp.add_corrective_driver`: "Add the driver for the selected shape key", using a `ROTATION_DIFF` driver variable (`auto_rig.py:8351, 8385`).
  - `arp.add_corrective_bone`, `arp.mirror_shape_keys`.
  - Export options `arp_ge_startend_keying_sk`, `arp_ge_gltf_sk_normals`, `arp_ge_gltf_sk_tangents`.
- **Repo context.**
  - `blender_scripts/forge_bpy/bake.py` already has `_ChannelAsEmission` and the `selected_to_active` cage bake. The new module can reuse both.
  - The latest commit turned ARP face bones off. So today no asset has expression deformation yet. Wrinkles depend on the face-expression (shape key) work landing first.

---

## 1. What MetaHuman actually does (reference layout, CONFIRMED)

**Maps.** Each map comes as a 3-channel texture of the same size as the base map (1024² RGB TGA in the sample; the shipping resolution is **UNVERIFIED**):
- `head_normal`, plus three wrinkle normals: `head_wm1_normal`, `head_wm2_normal`, `head_wm3_normal`.
- `head_color`, plus three blood-flow colour maps: `head_cm1_color`, `head_cm2_color`, `head_cm3_color`.
- `cmN` is always paired with `wmN`.

**Masks.** There are 37 single-channel masks, each 256×256 8-bit (65,580-byte TGA) in the sample, named `head_wm<N>_<region>_<side>_msk`:

| Map | Masks |
|---|---|
| **wm1** (6 regions + lips) | blink_L/R, browsRaiseInner_L/R, browsRaiseOuter_L/R, chinRaise_L/R, jawOpen, purse_UL/UR/DL/DR, squintInner_L/R |
| **wm2** | browsDown_L/R, browsLateral_L/R, mouthStretch_L/R, neckStretch_L/R, noseWrinkler_L/R |
| **wm3** | cheekRaiseInner/Outer/Upper_L/R, smile_L/R |
| **wm13** | lips_UL/UR/DL/DR, shared by wm1 and wm3 (each used 4×) |

**Weights.** There are 82 scalar weights `FRM_WMmultipliers.head_<cmN_color|wmN_normal>_head_<mask>`. Each drives `shader_head_shader.maskWeight_00..81`. So every (mask, map) pair has its own weight, separately for colour and for normal.

**What computes those weights.** The DNA Behavior layer has an "animated maps" conditional table:
- `AnimatedMapInputIndices`, `OutputIndices`, `From`, `To`, `Slope` and `Cut` values.
- Rows are grouped per LOD by `AnimatedMapLODs`.
- Each row reads one raw control. When the input is within [from, to], it adds `slope*x + cut` to one output map weight. The filter semantics are CONFIRMED by the header comments. "Adds" versus "assigns" when several rows share an output is **UNVERIFIED**.
- The raw controls are `CTRL_expressions.*`, for example `noseWrinkleL` and `noseWrinkleUpperL` (from `additional_assemble_script.py`).

**Why there are 3 maps.** This is my inference, **UNVERIFIED**. Each map can only hold one wrinkle state per texel. The forehead needs a "brows raised" state (horizontal lines, wm1) and a "brows down" state (vertical glabella lines, wm2). Those two cannot live in the same map. Forge should use the same rule: **put contradictory states for the same region in different maps.**

**Forge adoption.** Use the MetaHuman names for maps and masks, but pack the masks into RGBA textures. The per-mask weights come from ARKit-named shape keys. The proposed mapping is my inference:

| MetaHuman mask | ARKit driver(s) |
|---|---|
| wm1_blink | eyeBlinkL/R |
| wm1_browsRaiseInner | browInnerUp (split L/R by mask) |
| wm1_browsRaiseOuter | browOuterUpLeft/Right |
| wm1_squintInner | eyeSquintL/R |
| wm1_chinRaise | mouthShrugLower |
| wm1_jawOpen | jawOpen |
| wm1_purse_* / wm13_lips_* | mouthPucker, mouthFunnel |
| wm2_browsDown + browsLateral | browDownLeft/Right |
| wm2_noseWrinkler | noseSneerLeft/Right (creature muzzle snarl as well, plus mouthUpperUpL/R) |
| wm2_mouthStretch | mouthStretchL/R |
| wm2_neckStretch | no ARKit equivalent. Drive from the neck/head bone pitch, or from jawOpen × mouthStretch |
| wm3_cheekRaise* (crow's feet) | cheekSquintLeft/Right |
| wm3_smile (nasolabial) | mouthSmileLeft/Right |

ARKit names are from Apple's ARFaceAnchor list. I did not re-fetch it, so treat them as **UNVERIFIED** spelling.

---

## 2. Feature: expression wrinkle normal maps (face: brow, crow's feet, nasolabial, nose/muzzle, chin, lips)

**(a) Why it matters.**
- Blendshapes move vertices, but a game mesh is too coarse (AAA head about 20–50k tris, mobile 3–8k) to fold into 1–3 mm creases.
- Without wrinkle maps, a frown or smile looks like a rubber mask in close-ups and cinematics.
- At gameplay distance they are barely visible. This is why mobile can drop them.

**(b) Topology.**
- **No extra loops are needed for the map itself.** Large folds (nasolabial bulge, muzzle snarl rolls, eyelid crease) still need real loops and blendshapes. Those are covered in the existing face section.
- **UVs must not be mirrored on the face.** L/R masks live in UV space, so overlapping L/R islands make `_L/_R` masks impossible. The Forge UV stage must keep the head/face islands unique. Add a check: fail if the face island's UVs overlap after packing.
- Give the face its own texel density: a 2K–4K head on AAA, 1K on mobile.
- Tangents must match between bake and engine (MikkTSpace). Export the tangents/binormals from Blender and import normals plus tangents in UE.
- Poly budget is unchanged.

**(c) Rig.**
- Needs expression shape keys named with the ARKit 52 names (or ARP facial bone poses baked into shape keys).
- The shader is driven by those same morph/blendshape weights. No extra bones.
- Forge exports a sidecar `wrinkle_drivers.json`: mask channel → list of (shape key, from, to, slope, cut). This copies the DNA conditional-table idea, so engine scripts and materials are generated from one source.

**(d) Texture/material.**
- **AAA:** 2–3 wrinkle normal maps (compress set A, compress set B, stretch) plus the matching cm colour maps.
- **Mask textures:** packed RGBA, 4 masks per texture, 256–512², uncompressed or BC7/ASTC 4x4. MetaHuman's masks are 256² (CONFIRMED in the sample).
- **Blend:** `w_map = saturate(Σ mask_i(uv) * weight_i)`, then `N = normalize(lerp(N_base, N_wmK, w_mapK))` for each map. `wmN` is a full normal map of the expressed state, including base detail; that wm maps are full rather than delta maps is **UNVERIFIED** for MetaHuman, but it is what lets the engine use a plain lerp.
- **Colour:** `albedo = lerp(base, cmK, w)`.
- With SSS (UE Subsurface Profile / MetaHuman skin), the blood-flow colour also tints the subsurface colour.

**(e) Automatic creation in Blender.** Proposed module `forge_bpy/wrinkle.py`.

1. **Rest reference.**
   - Set `low.add_rest_position_attribute = True` (CONFIRMED API). For numpy, read `key_blocks["Basis"].data` with `foreach_get("co")`.
2. **Pose each expression.**
   - For each ARKit key present (or an ARP face pose), set the value to 1.0 and evaluate the depsgraph: `obj.evaluated_get(dg).data.vertices.foreach_get("co")`.
3. **UV-space strain tensor per face.** This is the core. It is fully procedural, exact and fast in numpy.
   - Per triangle: rest edge matrix `Dr = [p1-p0, p2-p0]` (3×2), posed `Dp`, UV matrix `Du = [uv1-uv0, uv2-uv0]` (2×2).
   - Jacobians: `Jr = Dr·Du⁻¹`, `Jp = Dp·Du⁻¹`.
   - Solve the generalized 2×2 eigenproblem `(JpᵀJp) v = λ (JrᵀJr) v`.
   - `s = √λ` are the principal stretch ratios. `v_min` is the **compression direction in UV space**.
   - `compression = max(0, 1 - s_min)`, `stretch = max(0, s_max - 1)`.
   - Wrinkles run **perpendicular** to `v_min`.
   - Because the direction is already in UV space, no tangent-frame conversion is needed to make texture patterns.
4. **Tension attribute, Geometry Nodes variant** (live viewport preview for the director).
   - Edge domain: `Edge Vertices` → `Position 1/2` (posed). Rest positions come from `Evaluate at Index(Named Attribute "rest_position", Vertex Index 1/2)`.
   - `ratio = len_posed/len_rest - 1`.
   - `Evaluate on Domain` (Point, mean), then `Blur Attribute`, then `Store Named Attribute "tension"` (FLOAT, POINT).
   - The GN modifier must come after the Armature modifier.
   - Edge tension is direction-less. Use it for masks and the preview; use the step 3 tensor for crease direction.
   - Node sources are CONFIRMED in 5.3. Socket names other than those of Edge Vertices are **UNVERIFIED**.
5. **Resolution.**
   - Strain at low-poly resolution is too coarse for creases, but fine for masks, which are low-frequency anyway.
   - For crease placement, put the deformation on the dense Tripo mesh:
     - Surface Deform: `bpy.ops.object.surfacedeform_bind`, with the high mesh bound to the low.
     - Or a subdivided proxy of the low.
   - Then run step 3 on that mesh.
6. **Region masks.**
   - Per expression: `mask_E = smoothstep(t0, t1, compression_E)`. Use `stretch_E` for neckStretch and mouthStretch.
   - Dilate and blur, then split L/R by the sign of the rest X position (a per-vertex attribute before rasterising).
   - Rasterise to UV:
     - either write face-corner colour attributes and bake EMIT with the existing `_ChannelAsEmission` pattern (bake `target='IMAGE_TEXTURES'`),
     - or rasterise triangles directly in numpy (faster, no Cycles).
   - Pack 4 masks per RGBA texture in MetaHuman name order.
7. **Wrinkle height.** Two generators; pick per region.
   - **Amplify existing:** `h = cavity_base * gain * compression`. AI meshes usually already carry faint sculpted forehead and crow's-feet lines, so this keeps the asset's own style. Cavity/curvature come from the existing bake.
   - **Synthesize oriented:** line-integral convolution (LIC), or oriented Gabor noise, of band-limited noise along the wrinkle direction (⊥ `v_min`), with amplitude ∝ compression.
     - Wavelength per region is a config value: forehead larger, crow's feet fine, nasolabial a single fold.
     - Real anthropometric spacings are **UNVERIFIED**, so expose sliders.
   - **Stretch maps** (neck, mouthStretch): flatten the base detail instead, `N = lerp(N_base, flat, stretch*k)`. Stretched skin loses pores and fine lines.
8. **Height to normal.**
   - Sobel, then combine with the base normal using Reoriented Normal Mapping, so each `wmK` is a complete normal map.
   - Save as OpenGL (Y+) for Unity. For UE, either flip green or tick the texture's Flip Green Channel (**UNVERIFIED** option name).
9. **Alternative: bake from a posed, sculpted high mesh.** This is the classic studio method.
   - Pose both high and low to the expression and displace the high with step 7 (GN Set Position along normal × height sampled by UV).
   - Then bake `NORMAL` selected-to-active with the existing cage settings.
   - This gives silhouette-correct results but is slower. Use it for hero AAA assets only.
10. **Blood flow (cm maps).**
    - `cm = base * lerp(1, tint_compress, compression_mask)` with a slight red/darkening in folds. Smile and cheek-raise flush the cheeks.
    - `* lerp(1, tint_blanch, stretch_mask)` for pale stretched skin.
    - Tints are per-species config. A creature can use a hide-dependent tint or skip this.
11. **Director approval.**
    - A Blender preview material drives the node Mix factors from shape-key values: `driver_add('default_value')`, with a `SINGLE_PROP` variable on `key_blocks["browDownLeft"].value`.
    - Render a contact sheet: neutral plus 8 key expressions under raking light.
    - The director's only clicks: accept, or nudge one "wrinkle strength" and one "crease size" slider per region.
    - A director click is only needed if the face has no expression shape keys (then: "skip wrinkles").

**What is procedural, what needs an AI part, what needs a click.**
- Masks and stretch maps: fully procedural.
- Oriented wrinkles: procedural.
- An AI image model painting wrinkles onto the baked normal is possible but **UNVERIFIED** and inconsistent across L/R. Not recommended as the default.

**(f) Engine.**

**UE5.**
1. Import the morph targets. Animation curves carry the morph names.
2. Mark the driver curves as **Material** curves in the Skeleton/Skeletal Mesh curve metadata. The engine then pushes the curve value into a material scalar parameter of the same name. The exact UI and the 5.x relocation to "Curve Metadata" are **UNVERIFIED**.
3. Or compute the mask weights in the AnimBP or Control Rig (Modify Curve node, or `GetMorphTarget`), then call `SetScalarParameterValue` on a Dynamic Material Instance.
4. Material: per mask texture, `dot(maskRGBA, float4(w0..w3))` → saturate → lerp normals/colour.
   - Use a shared Wrap sampler to stay under the 16-sampler limit.
5. MetaHuman-compatible naming makes later retargeting onto MetaHuman materials easier. The UE parameter and curve names of the MetaHuman head material are **UNVERIFIED**. Only the Maya `maskWeight_NN` / `FRM_WMmultipliers` names are confirmed.

**Unity URP.**
- Shader Graph cannot read blendshape weights. A script is required.

```csharp
[ExecuteAlways] public class WrinkleDriver : MonoBehaviour {
  public SkinnedMeshRenderer smr; public Renderer target;
  [System.Serializable] public struct Row { public string shape; public int vec, comp; public float from, to, slope, cut; } // from wrinkle_drivers.json
  public Row[] rows; int[] idx; static readonly int[] ids = { Shader.PropertyToID("_WrinkleW0"), Shader.PropertyToID("_WrinkleW1"), Shader.PropertyToID("_WrinkleW2") };
  Vector4[] w = new Vector4[3]; MaterialPropertyBlock mpb;
  void OnEnable(){ mpb = new MaterialPropertyBlock(); idx = System.Array.ConvertAll(rows, r => smr.sharedMesh.GetBlendShapeIndex(r.shape)); }
  void LateUpdate(){ // after Animator
    for (int i=0;i<3;i++) w[i]=Vector4.zero;
    for (int i=0;i<rows.Length;i++){ if (idx[i]<0) continue; float x = smr.GetBlendShapeWeight(idx[i])/100f; // Unity weights are 0..100
      if (x>=rows[i].from && x<=rows[i].to) w[rows[i].vec][rows[i].comp] += rows[i].slope*x + rows[i].cut; }
    target.GetPropertyBlock(mpb); for (int i=0;i<3;i++) mpb.SetVector(ids[i], w[i]); target.SetPropertyBlock(mpb); } }
```

- The 0–100 weight range and the `MaterialPropertyBlock` behaviour (it takes that renderer out of SRP Batcher batching) are from memory, **UNVERIFIED** against current docs. Skinned meshes are not batched anyway.
- Shader Graph:
  - Sample Texture 2D (mask, Linear) → Dot Product with `_WrinkleW0` → Saturate → Lerp(base normal, wm normal) → Normalize → Normal (Tangent Space).
  - Same weight drives Lerp(base albedo, cm).
- Import the model with Blend Shape Normals = Import, so large folds still shade on mobile. The option name is **UNVERIFIED**.

---

## 3. Feature: joint wrinkles (knuckles, elbows, knees, armpit, creature neck/wing folds)

**(a) Why it matters.**
- Bent fingers and elbows look plastic without folds.
- Most visible in first-person hands and close-up hands. Low priority elsewhere.

**(b) Topology.**
- The usual 3-loop joint (covered earlier).
- No extra loops for the map. UV islands for hands must not overlap between knuckles.

**(c) Rig.**
- Driven by bone angle, not by shape keys.
- In Blender, preview with a driver using a `ROTATION_DIFF` variable (the same mechanism as ARP's `arp.add_corrective_driver`, CONFIRMED in the ARP source).
- Write the bone, angle range and mask channel into `wrinkle_drivers.json`.
- Do not rely on FBX exporting custom-property curves. That is **UNVERIFIED** and most likely not exported. Compute the value in the engine instead.

**(d) Texture.**
- One "body compress" wrinkle normal plus an RGBA mask: knuckles L/R, elbow L/R (second mask: knees, armpits).
- Colour flush is usually skipped. Knuckle whitening on a fist is an optional cm.

**(e) Blender.**
- Same steps 3–8, with the expression replaced by a test pose:
  - fingers curled 90°,
  - elbow and knee 120°,
  - arm raised for the armpit (stretch),
  - creature neck bent.
- Pose through ARP controls, or `pose_bone.rotation_euler` on the deform bones, then evaluate.
- Fully procedural. The director approves one pose sheet.

**(f) Engine.**
- **UE:** an AnimBP or Control Rig computes the angle, sets a Material-type curve, and the material reads the parameter. Pose Driver is an alternative.
- **Unity:** a script reads the Transform `localRotation` angle (`Quaternion.Angle(rest, current)`), remaps it from→to, and writes the weight into the same `WrinkleDriver` vectors.

---

## 4. Feature: mesh-tension maps (generic, automatic)

**(a) Why it matters.**
- They fill the gap for areas nobody authored masks for: stylised creatures and arbitrary AI anatomy.
- Tension drives wrinkles everywhere, without a per-region setup.

**(b) Topology.** Needs a vertex density good enough to resolve strain. On mobile meshes, compute offline only.

**(c) Rig.** None.

**(d) Texture.**
- **Offline use:** tension is how the masks above are generated (§2 steps 3–6). This is the recommended path.
- **Runtime tension in the engine:** this needs posed-versus-rest edge lengths per frame. UE skin cache / compute-shader or Unity compute approaches exist, but there is no built-in node. **UNVERIFIED** as an off-the-shelf feature. Not recommended for Forge, which needs scripted, predictable output.

**(e) Blender.** The GN graph in §2 step 4 (preview) and the numpy tensor (production).

**(f) Engine.** Bake to masks offline. Skip runtime tension.

---

## 5. Memory budgets

Block-compressed sizes. Mip chain is about +33%. BC5/BC7 = 1 B/px, BC1 = 0.5 B/px, ASTC 4x4 = 8 bpp, 6x6 ≈ 3.56 bpp, 8x8 = 2 bpp.

| Tier | Contents | Approx. memory |
|---|---|---|
| MetaHuman-like (reference) | 3 wm normals + 3 cm colours at 4K (resolution **UNVERIFIED**) | about 6 × 21.3 MiB ≈ 128 MiB, plus masks |
| **Forge AAA hero** | 2 wm (compress A/B) + 1 stretch wm at 2K BC5 (3 × 5.3 MiB); 2 cm at 2K BC7 (2 × 5.3 MiB); 3 RGBA masks at 512² (about 1 MiB each uncompressed, 0.35 MiB with BC7) | **≈ 28 MiB per head** |
| Forge AAA non-hero / body joints | 1 body wm at 2K BC5 + 1 RGBA mask | ≈ 6 MiB |
| **Mobile high** | 1 combined compress wm at 1K ASTC 6x6 (≈ 0.6 MiB with mips); 1 RGBA mask at 256² (brow, eyes/crow's feet, nasolabial+nose/muzzle, chin/neck); no cm map — colour = `albedo *= lerp(1, flushTint, w)` with a shader constant | **≈ 0.7 MiB**, +2 samplers |
| Mobile low | No wrinkle textures. Blendshape normals only (large folds shade), or a fixed detail-normal stripe masked by the same RGBA mask | 0 |

- Samplers: keep the mobile material at 8 or fewer samplers in total.
- The ES3.1 16-sampler figure and UE's shared-sampler behaviour are from memory, **UNVERIFIED**.

---

## 6. Recommended Forge integration

New stage `wrinkle`, after the bake and the face shape keys, before export.

**Pipeline order.** retopo → UV (check: face UVs not mirrored) → bake → face shape keys (ARKit) → **wrinkle** → rig/pose test → export.

**Outputs:**
- `T_<part>_wm1_normal.png`, `T_<part>_wm2_normal.png`, `T_<part>_wm3_normal.png` (wm3 = stretch, optional)
- `T_<part>_cm1_color.png`, `T_<part>_cm2_color.png`
- `T_<part>_wmmask_01..03.png` (RGBA, MetaHuman mask names recorded in the JSON)
- `wrinkle_drivers.json`
- Engine side: a generated UE material-function parameter list, plus the Unity `WrinkleDriver` prefab component.

**Config per profile:** `aaa` / `mobile_high` / `mobile_low`, plus per-species tints and crease sizes.

**Approval.** One contact sheet of expressions and joint poses, base versus wrinkled side by side.

---

## Sources
- Epic MetaHuman DNA Calibration (CONFIRMED items above): https://github.com/EpicGames/MetaHuman-DNA-Calibration
  - `examples/dna_viewer_build_rig_with_textures.py`
  - `data/masks/`, `data/maps/`
  - `docs/dna.md`
  - `dnacalib/DNACalib/include/dna/layers/BehaviorReader.h`
  - `data/mh4/additional_assemble_script.py`
- Blender 5.3 source:
  - https://github.com/blender/blender/blob/blender-v5.3-release/source/blender/makesrna/intern/rna_object.cc (L3541)
  - https://github.com/blender/blender/blob/blender-v5.3-release/source/blender/makesrna/intern/rna_scene.cc
  - https://github.com/blender/blender/tree/blender-v5.3-release/source/blender/nodes/geometry/nodes (edge_vertices, evaluate_on_domain, blur_attribute, store_named_attribute)
- Auto-Rig Pro 3.77.33 mirror: https://github.com/jasongzy/auto_rig_pro (`src/auto_rig.py` L485–613, L8351; `src/auto_rig_ge.py` L11912, L11989–11990)
- Unreachable this session, so everything resting only on them is UNVERIFIED: dev.epicgames.com (UE curve metadata, MetaHuman UE material), docs.unity3d.com (blendshape weight range, MaterialPropertyBlock and SRP Batcher, import options), docs.blender.org, developer.apple.com (ARKit names). WebSearch was exhausted, so no web searches were run.
