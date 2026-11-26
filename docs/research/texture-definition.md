# Research: texture-definition

# Forge: research on texture definition, alteration and director-added detail

**Scope.** This covers texture definition and alteration for the Tripo → Blender 5.3 → UE5 (AAA) / Unity URP (mobile) pipeline.

**What the repo does now.**
- `blender_scripts/forge_bpy/bake.py` bakes these maps with Cycles selected-to-active: basecolor (DIFFUSE colour), normal (tangent space, **OpenGL**), roughness, metallic (through EMIT) and ao.
- `forge/tripo_stage.py` already asks Tripo for `pbr: True, delight: True, texture_alignment: "original_image"`.
- `forge/spec.py` and `forge/qa.py` hold a texel-density target (512 px/m by default) and a coefficient-of-variation stretch check.

This report lists what is missing and how to script it.

**Tags.**
- **[UNVERIFIED]**: I did not check the claim against a source in this session. It may come from memory, or the source was a forum or third party.
- **[S#]**: a numbered source at the end.

---

## 0. Gaps that matter most (priority order)
1. **Normal-map green channel per engine.** UE uses DirectX (-Y) normals. Unity and Blender use OpenGL (+Y). The current bake is OpenGL only. At UE export, flip G, or set `flip_green_channel=True` on the UE texture asset. Also triangulate the low-poly mesh *before* baking and export that same triangulation, so the MikkTSpace tangents match. **[UNVERIFIED: standard practice, not re-checked]**
2. **No channel packing or compression metadata per engine.** Add ORM packing for UE and a MetallicSmoothness/mask map for URP. Set sRGB off on data maps, and BC5 / ASTC settings at import (sections 1 and 11).
3. **No tint masks (material ID / RGB masks).** Without them the director cannot get team colours, skins or variants. This is the cheapest high-value addition (section 4).
4. **No auxiliary bakes.** Curvature, thickness, position, ID and world-normal bakes are missing. Every smart material (wear, dirt, dust, edge highlights) and every hand-painted stylisation depends on them (section 5).
5. **No layered, non-destructive texture editing for the director.** That means: region pick → recolour / re-texture by prompt / add wear / add decal → approve → bake (sections 8, 10 and 13).
6. **Separate texture sets per region with different texel density.** Face, eyes, teeth and hands need more pixels than the torso. Use multiple materials, each on its own 0–1 tile, rather than UDIMs for games (section 12).

---

## 1. PBR channel set per engine

**(a) Why it matters.** A wrong colour space or channel convention is the most common silent failure. Packed masks in sRGB give wrong roughness. A wrong green channel inverts the lighting on every bump.

**(b) Topology.** None, apart from triangulating before baking (gap 1).

**(c) Rig.** None.

**(d) Maps per engine.**

UE5 (AAA), Default Lit master material:

| Texture | Channels | Compression setting | sRGB |
|---|---|---|---|
| `T_<Asset>_<Part>_BC` | RGB base colour, A opacity or tint mask (optional) | Default (BC1, or BC3 with alpha) or BC7 | on |
| `T_..._N` | RG normal, B reconstructed | `TC_Normalmap` (BC5), DirectX green | off |
| `T_..._ORM` | R=AO, G=Roughness, B=Metallic | `TC_Masks` (sRGB off) | off |
| `T_..._M` | Tint / ID mask RGBA | `TC_Masks`, or BC7 if channels bleed | off |
| `T_..._E` | Emissive | Default or HDR | on |
| Skin only | SSS mask / thickness, cavity | Masks | off |

Notes on these UE settings:
- Masks compression is ordinary compression with sRGB disabled [S1][S2].
- `TC_Normalmap` is BC5 and stores only R and G [S3][S4].
- Packed masks can show cross-channel compression artefacts. Users report BC7 as the fix, and also report BC7 bleeding into alpha. Test both. **[UNVERIFIED: forum reports]** [S1]
- Set the LOD group to `TEXTUREGROUP_Character` for colour and masks and `TEXTUREGROUP_CharacterNormalMap` for normals [S5][S6].

Unity URP (mobile), Lit shader:
- `_BaseMap`: RGB albedo, A alpha.
- `_MetallicGlossMap`: R metallic, **A smoothness**, which is 1 − roughness. Smoothness can also come from albedo alpha [S7].
- `_BumpMap`: import as Normal map, OpenGL.
- `_OcclusionMap`: URP reads the G channel. **[UNVERIFIED]**
- `_EmissionMap`.
- Detail inputs: `_DetailMask` (alpha), `_DetailAlbedoMap`, `_DetailNormalMap`. Tiling has no effect on the mask [S7].

URP Lit cannot read one fully packed mask. For mobile, ship a **custom Shader Graph** that uses HDRP's mask-map convention, so one texture fetch covers four channels:
- R = metallic
- G = AO
- B = detail or tint mask
- A = smoothness [S8]

Ship one more RGBA tint mask, or put the tint mask in base-colour alpha when there is no transparency.

**(e) Automation in Blender.**
- Add `pack_channels(maps, layout)` in numpy (`img.pixels.foreach_get` / `foreach_set`), with layouts `UE_ORM`, `URP_MetallicSmoothness` and `FORGE_MOBILE_MASK`.
- Write PNG 8-bit for colour and masks, and 16-bit PNG for normals before compression.
- Convert roughness to smoothness with `1 - r`. Flip G for UE normals.
- Mark data images `colorspace_settings.name = "Non-Color"` (already done).
- Everything here is procedural. The director never sees this step.

**(f) Engine import scripts.**
- UE Python: `unreal.Texture2D` set `compression_settings = unreal.TextureCompressionSettings.TC_NORMALMAP / TC_MASKS`, `srgb=False`, `lod_group`, `flip_green_channel`.
- Unity: an `AssetPostprocessor.OnPreprocessTexture` that keys on the suffix (`_N` → `TextureImporterType.NormalMap`; `_M` / `_ORM` → `sRGBTexture=false`) and sets `TextureImporterPlatformSettings` for Android/iOS (section 11). Forge can drop this `.cs` into the Unity export folder once.

---

## 2. Texel density targets

**(a) Why it matters.** Mixed density across a character (sharp shoulder, blurry face) looks wrong at close range. Density also drives VRAM.

**(b) Numbers and UV rules.** Common conventions, not standards [S9][S10][S11]:

| Use | Density |
|---|---|
| First-person / hero | 10.24 px/cm (1024 px/m) |
| Third-person | 5.12 px/cm (512 px/m) |
| Top-down | 2.56 px/cm (256 px/m) |
| Mobile / VR | 256–512 px/m |

Recommended Forge profile targets:
- **AAA third-person character body:** 1024 px/m, with **face, hands, eyes and other close-up regions at 2× (2048 px/m)**.
- **Mobile:** 256–512 px/m, with the face at 2× body.
- In the bull job, QA reported 2504 px/m against a 1024 target and 1266 against 512. Either the target needs per-profile tuning, or the atlas should shrink (QA already flags this, which is good).

UV rules:
- Islands of one material share one density.
- Per-region multipliers are done by scaling the islands *before* UVPackmaster packs them. UVPM 4 can pack with per-island scale locks. **[UNVERIFIED: exact UVPM option name; it has "Lock Overlapping" and per-island "Scale Limit" / "Texel Density" tools in v3+]**

**(c) Rig.** None.

**(d) Textures.** Size each texture as: needed px = density × sqrt(UV-area-equivalent surface m²) / packing efficiency (about 0.7–0.8). Round up to a power of two.

**(e) Automation.**
- QA already computes density.
- Add a region density multiplier from vertex groups (`Forge_Face`, `Forge_Hands`, eyes from the eyelid research). Use the detail map from commit `65d1b6f` (curvature score) to propose them automatically.
- The director approves a colour overlay (`checker` + density heatmap via colour attribute).

**(f) Engine notes.**
- UE: Mip / texel density view mode (Required Texture Resolution).
- Unity: Scene view "Mipmaps" draw mode. **[UNVERIFIED: name in Unity 6]**

---

## 3. Detail normal / tiling detail maps

**(a) Why it matters.** A 2K atlas cannot show skin pores, fabric weave or metal brushing at close range. A tiling detail map adds that frequency for about 1 MB.

**(b) Topology.** A second UV channel is optional. Usually the same UV0 is used with a tiling scale.

**(c) Rig.** None.

**(d) Textures.**
- Small tiling (256–512) detail normals: pores, cloth weave, scales, leather grain, brushed metal.
- Each comes with a **detail mask** that says where it applies. It can sit in a spare mask channel.
- UE: blend with `BlendAngleCorrectedNormals` **[UNVERIFIED: node name from memory]**.
- URP Lit: Detail Inputs (mask in alpha) [S7].
- HDRP detail-map packing (R desat albedo, G normal Y, B smoothness, A normal X) is a good single-texture convention to copy into a custom mobile Shader Graph [S8].

**(e) Automation.**
- Keep a curated library `forge/assets/detail/` (skin_pores, cloth_weave, leather, scales, metal_brushed, stone).
- Pick per tint region by a simple classifier: material label from the Tripo segment name, or ask a VLM on a render.
- Generate the detail mask from the region ID mask × (1 − curvature-edge) where appropriate.
- New detail tiles can be generated seamless by SD with tiling enabled, then turned into a normal by height → normal in numpy (Sobel). That is procedural.
- The director picks from 3 thumbnails (one click).

**(f) Engine notes.**
- Mobile: detail maps cost an extra 1–2 samples. Enable them only on the hero LOD, or skip them.
- UE: scale the detail tiling by a material parameter so the director can tune it in Material Instances.

---

## 4. Material ID / RGB tint masks (team colours, skins, variants)

**(a) Why it matters.** It gives dozens of variants from one texture set at runtime, near zero cost. It is essential for team colours, rarity skins and NPC variety.

**(b) Topology.**
- No mesh change is needed.
- Separate material slots only for genuinely different shading models: skin (SSS), eye (refraction), hair/fur (anisotropic / alpha), emissive glass.
- Keep draw calls low: AAA ≤ 4–6 materials per character, mobile 1–2. **[UNVERIFIED: common budget, not sourced]**

**(c) Rig.** None. At runtime, a UE Material Instance Dynamic, or a Unity `MaterialPropertyBlock` / material variant.

**(d) Textures.**
- Mask RGBA = 4 tintable regions, plus implicit "untinted" where the sum is 0. Use a second mask for more than 4 regions.
- In tint regions, base colour should be **near-neutral luminance** (desaturated, mid-grey detail). The shader then does `lerp(base, base_luma * tintColor * 2, mask)` (overlay-style) so the shading detail survives.
- Store a "tint strength" so the default parameters reproduce the original colour exactly. Compute the default tint as the region's mean colour.
- Compress with `TC_Masks`. Use BC7 if the channels bleed.

**(e) Automation. Sources of region IDs, best first:**
1. **Tripo part segmentation.** `mesh_segment` is already in the pipeline. Its part names map onto low-poly faces by nearest-surface transfer (Data Transfer modifier, face-corner or face data) → face attribute `forge_region`.
2. **Colour clustering.** Run k-means in CIELAB on the baked basecolor within UV coverage (numpy/sklearn, k = 4–8). Clean up with a connected-components area threshold and a morphological open. Convert pixel labels to per-face majority labels, so the masks follow geometry edges.
3. **Director click.** Raycast from the viewport click → face → flood-fill neighbours whose colour ΔE < tolerance and whose dihedral angle < threshold (bmesh). A slider adjusts the tolerance live.

Bake the ID map as an EMIT bake of a colour attribute (face-domain colour → Attribute node → Emission). Then split it into RGBA mask channels with antialiased edges: bake at 2× and downsample.

Also derive "neutralised base colour + default tint" per region:
- base' = base / regionMean × regionMeanLuma
- tint = regionMean

The director sees no change until they move a colour picker.

**(f) Engine notes.**
- UE: master material with `TintR..TintA` vector parameters; variants become Material Instance assets. Export these from Forge as a small JSON that a UE Python script turns into MI assets.
- Unity: Shader Graph properties `_TintR.._TintA`; variants as material assets. Use `MaterialPropertyBlock` for crowds (SRP Batcher caveat: per-instance properties break batching unless you use DOTS instancing). **[UNVERIFIED]**

---

## 5. Auxiliary bakes for smart materials: curvature, thickness, position, ID, world normal

**(a) Why it matters.** Procedural wear, dirt, dust, edge highlights, SSS thickness and stylised shading all key off these. Substance Painter bakes exactly this set. In Substance's convention, black is concave [S12][S13].

**(b) Topology.** Bake from the **dense Tripo mesh** (high) to the low-poly mesh, as now.

**(c) Rig.** None.

**(d) Maps and how to make them in Blender 5.x.**
- **Curvature**, best quality first:
  1. From the baked tangent normal map in numpy: curvature ≈ divergence of the normal XY (d nx/du + d ny/dv), Gaussian-smoothed, remapped around 0.5. Fast, matches the normal detail, no extra bake.
  2. Geometry Nodes on the high mesh: `Edge Angle` / face-normal differences → `Map Range` → store as a point attribute → EMIT bake high → low. This captures geometry only [S14].
  3. Shader `Geometry > Pointiness`. Cycles only and quick, but lowest quality [S14].
  4. Third-party CurvBake Pro (GPU) [S15].
- **Cavity / AO:** already baked.
  - Add a "local" AO: AO shader node with `only_local=True`, short distance.
  - Add an edge mask from the **Bevel node**: `dot(bevelNormal, trueNormal)` → 1 − value.
  - Both through EMIT bakes. **[UNVERIFIED: these exact node settings in 5.3, but the nodes exist since 2.8x]**
- **Thickness:** AO node with `inside=True` (Cycles), inverted, bake EMIT on the high mesh → low. Used for SSS (ears, nostrils, fingers, membranes, wings). **[UNVERIFIED: option still called "Inside" in 5.3]**
- **Position:** the 5.1 manual lists a Position bake that writes world-space XYZ into RGB [S16]. For gradients, prefer the *object-bbox-normalised* position: `Texture Coordinate > Generated` → EMIT → bake. Z gives the "dirt from the ground up" gradient.
- **World-space normal:** `bake(type="NORMAL", normal_space="OBJECT")`. Z gives "dust / snow on upward faces".
- **ID:** see section 4.
- Optionally use the third-party "Attribute Baker" extension (Blender 5.0+) to bake any Geometry Nodes attribute to an image through UV [S17].

Blender bake targets are the active Image Texture node or a colour attribute [S16]. Bake one pass at a time, using EMIT for arbitrary data. Set margin type to "Adjacent Faces" for cleaner seams **[UNVERIFIED: option name `bake.margin_type='ADJACENT_FACES'`, available since Blender 3.1]**.

**(e) Automation.** Fully procedural. Add `aux_maps = ("curvature","thickness","cavity","edge","position","wsnormal","id")` to `bake.py`. Store them at half resolution (they are masks).

**(f) Engine notes.**
- Usually these are *not* shipped. They are inputs to Blender-side smart materials, then baked into the final maps.
- Ship only what runtime effects need: thickness for UE Subsurface Profile (sits in Opacity for SSS) **[UNVERIFIED]**; curvature/cavity if runtime wear or dirt sliders are wanted.

---

## 6. Hand-painted vs realistic styles

**(a) Why it matters.** Mobile and stylised games often want lighting painted into the albedo with little or no normal map. AAA wants physically plausible PBR.

**(b) Topology.** The stylised look tolerates lower polys. A silhouette-driven budget is fine.

**(c) Rig.** None.

**(d) Textures.**
- **Realistic:** full PBR. Albedo within physically plausible range, roughly sRGB 30–240, with no baked shadow **[UNVERIFIED: commonly quoted range]**.
- **Hand-painted:** base colour carries gradients and AO; roughness is constant or omitted; often Unlit or Simple Lit (URP) shaders.

**(e) Automation. Procedural "paint-over" recipe in Blender shader nodes, then bake:**
- albedo × lerp(0.6, 1, AO)
- \+ top-light gradient from world normal Z and position Z
- \+ edge highlight from curvature > 0.6 (lighter, warmer)
- − cavity darkening (cooler hue)
- posterise or a slight hue shift on shadows
- a painterly filter with the Compositor **Kuwahara** node (Blender 4.0+) **[UNVERIFIED: present in 5.3 compositor]**

Bake the result to `_BC`. Expose 5 sliders (light direction, edge highlight, cavity, saturation, brush softness) to the director. One approval.

**(f) Engine notes.**
- Unity: URP Simple Lit or Unlit for hand-painted mobile.
- UE: Unlit or a custom toon material.
- Keep the normal map optional per profile.

---

## 7. Substance-Painter-like smart materials in Blender

**(a) Why it matters.** AI textures are "average". Readable game assets need edge wear on metal, grime in crevices, dust on top surfaces, and colour variation.

**(b) Topology.** None.

**(c) Rig.** None.

**(d) Layer recipes.** Each recipe outputs BC / roughness / metal / normal-height deltas plus a mask.
- **Edge wear (metal / paint chips):** mask = smoothstep(curvature, t, t+w) × noise(object coord, scale) × regionMask. Reveals bare metal: metallic=1, roughness 0.3, lighter colour.
- **Dirt / grime:** mask = (1 − AO_local) × (1 − positionZ)^k × noise. Darker, rougher.
- **Dust:** mask = saturate(wsNormalZ) × noise. Desaturated light colour, rough.
- **Rust / moss / blood / wetness:** the same masks with different colour and roughness, plus a wetness roughness drop.
- **Colour variation (realism breakup):** low-frequency noise hue / value ±3–5 %.

**(e) Implementation.**
- Store a **layer stack** as data: JSON in the job folder, mirrored as a custom property on the material. Each layer has type, params, mask source(s), blend mode and opacity.
- A Python builder regenerates a node tree: one node group per layer, `Mix` chains per channel, and aux maps (section 5) as image inputs.
- Preview in EEVEE (fast). On approval, bake each channel by temporarily routing it to Emission and calling `bake(type="EMIT")` on the low mesh, *not* selected-to-active, because everything is now in the low UV space.
- Existing free option for a layer UI: the "Ucupaint" add-on (layer-based texture painting and baking inside Blender) **[UNVERIFIED: 5.3 compatibility]**. A custom builder is simpler to control from bpy and from the director UI.
- Procedural vs AI vs director:
  - The masks are procedural.
  - The *recipe choice* can be automatic: a VLM tags parts as metal / cloth / skin / leather / stone, then defaults are applied, e.g. metal → edge wear 0.3, dirt 0.2.
  - The director only adjusts "amount" sliders.

**(f) Engine notes.**
- Bake everything for mobile.
- For AAA, optionally keep 1–2 runtime sliders (dirt amount, wetness) driven by the cavity/position masks packed into the mask texture. This enables gameplay states such as getting muddy or wet.

---

## 8. AI texture generation, regional re-texture and upscaling

**(a) Why it matters.**
- Tripo gives the base texture.
- The director needs "change *this* to *that*" without a modeller. Examples: "make the armour bronze", "add a sigil on the shield", "make the eyes glow".
- Resolution often has to go above Tripo's native output.

**(b) Topology.** None, but projections need a UV'd low mesh, which Forge has after the UV stage.

**(c) Rig.** None.

**(d) Textures.** Generated output feeds base colour first. Derive roughness / metal from a material label, not from the AI. Derive normal from the high mesh bake plus optional height-from-luma detail at low strength.

**(e) Options.**
1. **Tripo re-texture (whole model).** The pipeline already calls `texture_model` with `texture_prompt.image`, `pbr`, `delight`, `texture_quality` (standard / detailed / extreme up to 8K / fast) and `texture_alignment` (`original_image` / `geometry`) [S18][S19][S20].
   - Use `texture_alignment="geometry"` when the concept image and the mesh disagree in pose.
   - A text `texture_prompt` variant gives "skins". Feed a director-edited concept image for colourways. **[UNVERIFIED: whether text and image prompts can be combined]**
   - Re-texture the *dense* model and re-bake to the low UVs. This keeps everything downstream intact.
2. **Regional prompt-based re-texture (local, RTX 4080).** This is the StableProjectorz / Dream Textures method: depth-ControlNet + inpaint mask, projected from views [S21][S22][S23].
   - Director selects a region: click / flood fill (section 4), lasso, or a paint stroke on the mask image.
   - Script places 2–6 cameras that see the region: average the region normal, place cameras ±35° around it. For each camera, render colour (current texture), depth, normal, the region mask, and a facing-ratio map.
   - Send these to a local **ComfyUI** server via its HTTP API, with an SDXL/FLUX inpaint model plus depth (and canny) ControlNet, the prompt, and seed-locked multi-view consistency. Reference-image conditioning (IP-Adapter) uses the concept art.
   - Back-project each result into UV space. Use a temporary UV from `bpy.ops.uv.project_from_view` per camera, or a "projector" material with Camera-space `Texture Coordinate > Window`. Then EMIT-bake into the main UV.
   - Weight per texel = facing² × visibility (depth test) × mask. Normalise across views and feather the mask edge 8–16 px.
   - Blend into a new layer (section 7), so it can be undone.
   - Hunyuan3D-2 "Paint" (open-source multi-view texture generation) or MV-Adapter can replace step 3 for whole-object multi-view consistency. **[UNVERIFIED: licences and current versions]**
3. **Upscaling.** Real-ESRGAN / 4x-UltraSharp-class models (chaiNNer or ComfyUI) on base colour only. **[UNVERIFIED: model names current]**
   - Dilate islands first (push-pull fill, as `bake.py::_fill_colours` already does), so the GAN does not see black gaps. Then re-mask to UV coverage.
   - **Never GAN-upscale normal maps.** Re-bake them from the high mesh at the higher resolution.
   - Better still: upscale the per-view images *before* projection, or ask Tripo for `extreme` quality.

**(f) Engine notes.** None specific. The final output is ordinary textures.

---

## 9. Seam fixing

**(a) Why it matters.** Visible seams on faces and arms are the classic AI-texture tell. Mips widen seams at distance.

**(b) Topology.**
- Put UV seams in hidden places: under the arms, inside the legs, back of the head, under the hairline.
- Seam placement is done in the UV stage. Make it seam-cost aware: avoid the face front, chest centre and logos.

**(c) Rig.** None.

**(d) Textures.**
- Margin/padding ≥ 8 px at 1K and 16 px at 2K. Mips halve the margin each level; a bake of ~2^(mips-to-keep) px is ideal.
- Use "extend" or "adjacent faces" margin types.

**(e) Automation.**
- Baking from the 3D high mesh is continuous across low-poly seams by construction. Seams appear only from (i) projection (section 8) or (ii) painted/AI-edited layers.
- Fix 1: after any 2D edit, **re-project through 3D**. Bake the edited texture from a duplicate of the low mesh with the old UV onto itself (EMIT, selected-to-active, tiny cage). This re-samples both sides of the seam from the same 3D point.
- Fix 2: seam-aware blending in numpy. Use the seam edge list from bmesh (`edge.seam` or UV split detection). For each seam edge, sample texels along both UV sides at matching parameter t and average them in a feathered band (4–8 px).
- QA check: per seam edge, the mean ΔE across sides should be < 3. Flag the worst seams on a render for the director.

**(f) Engine notes.**
- BC / ASTC block compression makes seams worse when islands abut. Keep ≥ 4 px (one block) gaps between islands.
- UVPM: set margin in texels. **[UNVERIFIED]**

---

## 10. Delighting AI textures and colour matching to concept art

**(a) Why it matters.** Shadows or speculars baked into albedo double-shade in the engine. Cavities look painted black. The character looks wrong under any light other than the generator's.

**(b) Topology.** None.

**(c) Rig.** None.

**(d) Delighting.**
- Tripo `delight: True` is already on [S18][S19].
- Residual fixes, scripted in numpy per tint region (section 4):
  1. **AO division:** albedo' = albedo / lerp(1, AO, k), k ≈ 0.5–0.8, clamped. This removes painted cavity darkening.
  2. **Low-frequency luminance flattening:** L' = L − (blur_large(L) − regionMean(L)) × s. Use object-space blur via 3D rather than UV-space, if possible. Hue is kept, so intentional colour design stays.
  3. **Specular removal:** clamp pixels whose L is above the region's 98th percentile with low saturation to the region median.
  4. **PBR range validation:** clamp albedo to roughly sRGB 30–240. Metal albedo is brighter (sRGB ~180–255) **[UNVERIFIED: common charts]**.
- Optional AI decomposition per projected view: intrinsic image decomposition models such as Marigold-IID, Adobe RGB↔X or IntrinsicAnything, then back-project the albedo. Research-grade; DANTE-W (2026) targets exactly "lighting baked into mesh textures" [S24]. **[UNVERIFIED: maturity and licences]**
- Agisoft Texture De-Lighter (free, needs AO / cavity input) as a manual fallback. **[UNVERIFIED: still available]**

**Colour matching to concept.**
- Segment the concept image into parts (SAM / VLM labels matching the tint-region labels).
- Do Reinhard-style transfer in CIELAB per region: match mean and std of L, a, b, with L-std transfer at 50 % to keep shading detail.
- For a hand-painted style, also match saturation.
- The director gets a before/after slider and a per-region "match strength".

**(e) Automation.**
- All procedural, plus one director approval with sliders: delight strength, colour match strength.
- QA metric: the correlation between the albedo luminance and the AO / curvature maps. High correlation means shading is still baked in.

**(f) Engine notes.** UE has a Base Color validation view mode **[UNVERIFIED: name in UE 5.x]**. Unity Built-in had "Validate Albedo"; in URP use the Rendering Debugger **[UNVERIFIED]**.

---

## 11. Texture compression and mobile budgets

**(a) Why it matters.** Memory and bandwidth. Wrong formats can silently decompress to RGBA32 on unsupported devices [S25].

**(b) Topology.** None.

**(c) Rig.** None.

**(d) Formats.**
- **UE desktop:**
  - BC1 (4 bpp) or BC7 (8 bpp) for colour.
  - BC5 (8 bpp) for normals [S3][S4].
  - Masks: BC1, or BC7 if channels bleed [S1].
  - Oodle Texture is on by default and can use RDO for smaller packages [S26].
- **Unity mobile:**
  - ASTC is recommended on iOS A8+ and modern Android. ETC2 is the fallback. Unsupported ASTC is decompressed to RGBA32 [S25].
  - ASTC always uses 128-bit blocks: 4×4 = 8 bpp, 5×5 = 5.12, 6×6 = 3.56, 8×8 = 2 bpp [S27].
  - Arm says 6×6 is the most common mobile choice and is usable for normals with `-thorough` [S27][S28].
  - Suggested defaults: BaseColor 6×6; Normal 5×5 (hero) or 6×6; Mask 6×6–8×8; UI or tint masks with hard edges 4×4.

**Memory math** (base level; +33 % for mips):

| Format | 1024² | 2048² | 4096² |
|---|---|---|---|
| BC1 (4 bpp) | 0.5 MB | 2 MB | 8 MB |
| BC5 / BC7 (8 bpp) | 1 MB | 4 MB | 16 MB |
| ASTC 6×6 | 0.47 MB | 1.87 MB | – |
| ASTC 8×8 | 0.26 MB | 1.05 MB | – |

**Suggested budgets** **[UNVERIFIED: these are recommendations, not a published standard]**:
- **AAA hero character:** about 40–90 MB. Head 4K set (BC7 + BC5 + ORM ≈ 48 MB with mips at 4K, or 12 MB at 2K), body 4K set, eyes 1K, teeth/mouth 512–1K, hair 2K.
- **Mobile character:** ≤ 4–8 MB total. One 1K–2K atlas set: BaseColor ASTC6×6 + Normal 6×6 + Mask 8×8 at 2K ≈ 5.3 MB with mips. Eyes and mouth go *into the same atlas*.

**(e) Automation.** Forge writes PNGs. Engine import scripts (section 1f) set the formats:
- UE: `compression_settings`, `lod_group`, `max_texture_size`.
- Unity: `TextureImporterPlatformSettings{name="Android", format=TextureImporterFormat.ASTC_6x6, maxTextureSize=...}`.

Add a QA check for estimated VRAM per profile, using the table above.

**(f) Engine notes.**
- UE mobile also uses ASTC. Set it per platform in the Device Profile / Texture LOD settings. **[UNVERIFIED]**
- Unity: use Google Play texture compression targeting (Android App Bundle) when ETC2 fallbacks are needed [S25].

---

## 12. UDIMs vs single tile for games

**(a) Why it matters.** UDIMs give film-grade resolution. Engines handle them poorly.

**(b) Topology / UVs.** For games: **one 0–1 tile per material**. Split materials by region (head, body, eyes, mouth, hair, gear) when more pixels are needed.

**(c) Rig.** None.

**(d) Engine support.**
- UE supports UDIM *only through Streaming Virtual Texturing*:
  - Name tiles `BaseName.1001.png`.
  - Tiles are flipped vertically on import.
  - Requires VT enabled in project settings and Virtual samplers.
  - Allows per-tile resolution [S29][S30].
  - Users report limits with opacity / displacement. **[UNVERIFIED: forum]** [S31]
- Unity has no built-in UDIM support. **[UNVERIFIED]**

**(e) Automation.**
- Blender can bake to UDIM tiled images for an internal "master" set if wanted.
- Export rule:
  - UE AAA: either separate materials (default) or an optional SVT-UDIM path.
  - Unity: always atlas into 0–1 per material.
- UVPackmaster 4 can pack per-material 0–1 tiles directly.

**(f) Engine notes.**
- MetaHuman-style split: head and body are separate materials and texture sets. That gives a natural per-region density. **[UNVERIFIED: the exact MetaHuman texture-set layout]**

---

## 13. Adding new details: decals, wear, dirt, scars, tattoos

**(a) Why it matters.** This is the director's most common ask ("add a scar over the left eye", "clan tattoo on the arm", "battle damage"). It also enables runtime customisation.

**(b) Topology.**
- Baked decals: none.
- Runtime mesh decals: floating geometry slightly offset, skinned with the body, using the same weights through Data Transfer.
- Projected runtime decals: none.

**(c) Rig.**
- Mesh decals must copy the body vertex weights (Data Transfer modifier, `VGROUP_WEIGHTS`, nearest face interpolated). ARP export then includes them.
- Shape-key-driven scars (e.g. a scar crossing an eyelid) need the decal mesh to also receive the body's shape keys (Surface Deform, then apply-as-shape per key) **[UNVERIFIED: workflow, standard technique]**. A baked texture avoids this, which is why baking is preferred.

**(d) Textures. Three tiers.**
1. **Baked into the main maps (default, both engines).** BaseColor + normal/height + roughness deltas as a layer (section 7). Free at runtime.
2. **Tattoo / decal layer for customisation.** A separate RGBA decal atlas sampled with UV0 + per-decal transforms, or a second UV set (UV1) laid out for decal regions, blended in the shader by alpha. Allows player-chosen tattoos and team logos.
3. **Engine decals.**
   - UE: DBuffer decals are default in UE5. They work on skeletal meshes but can "slip" under strong deformation **[UNVERIFIED: forum]**. Actors control decal receipt. **Mesh decals** wrap geometry and are meant for characters [S32][S33].
   - Unity URP: Decal Projector + Decal Renderer Feature. **[UNVERIFIED: skinned-mesh behaviour]** Use for transient blood / damage, not identity features.

**(e) Creation from director input.**
- **Image or prompt decal:**
  - Director types "celtic knot tattoo" → SD generates it on transparent (or with a rembg-style background removal).
  - Director clicks the surface point → script places a projector (camera along the surface normal, size slider, rotation gizmo) → back-project with the section 8 method into a decal layer.
  - Tattoo blend: multiply into BC, roughness slightly up, no normal change.
- **Scar from a stroke:**
  - Director draws a Grease Pencil stroke on the surface (surface placement mode).
  - Script converts it to curve points, projects them onto the mesh, maps them to UV per point via `closest_point_on_mesh` + barycentric UV, and rasterises a **signed distance field** in UV space (numpy). Seam-crossing strokes are split per island.
  - Height = profile(SDF) (raised keloid or sunken cut) → normal via Sobel.
  - Colour = pinkish lerp by SDF.
  - Roughness: smoother in the scar.
  - Add procedural noise for an organic edge.
- **Wear / dirt / damage:** sliders from section 7. A "brush" mode lets the director paint the layer mask in Texture Paint mode (Blender native; one active image = the layer mask).
- **Damage stages for gameplay:** bake 2–3 wear levels into one mask channel as thresholds (0.33 / 0.66 / 1.0). The engine reveals them with a scalar parameter.

**(f) Engine notes.**
- UE: Material Instance params for tattoo atlas index and colour.
- Unity: Shader Graph with decal atlas + `_DecalST` vectors.
- Mobile: bake everything except team logos, which go in the tint-mask approach.

---

## 14. How the director adds or alters texture details with minimal work (UI design)

A **"Forge Texture Studio" N-panel**, driven by the layer stack in section 7. Every action creates a named, toggleable, re-orderable layer. Nothing is destructive until "Approve & Bake".

Workflow:
1. **Pick region.** One click on the model selects a tint region or island (flood fill by colour + angle, tolerance slider). Alternatives: lasso, or "paint mask". Text select through a VLM ("the belt") is optional **[UNVERIFIED: reliability]**.
2. **Choose an action:**
   - Recolour: colour picker plus hue / sat / value. Drives tint parameters, so it also works live in the engine.
   - Re-texture with prompt (section 8.2).
   - Change material (metal / leather / cloth / skin preset: roughness, metal, detail normal).
   - Add wear / dirt / dust / wet: amount slider.
   - Add decal from image or prompt, or tattoo (click to place, gizmo to scale or rotate).
   - Draw scar (Grease Pencil stroke).
   - Make glow: emissive layer, colour and intensity.
   - Match concept colours (section 10).
3. **Preview** in EEVEE, with turntable + three light rigs (studio, outdoor, dark) so baked-in lighting problems show up.
4. **Compare** A/B with the previous approved version.
5. **Approve & Bake.** Bakes all layers to the engine maps (sections 1 and 11), runs QA (seams, albedo range, VRAM, density), and exports variants: each recolour can be saved as a Material Instance preset rather than a new texture.

Persistence:
- Store the layer stack JSON in `jobs/<asset>/textures/layers.json`. Every AI generation records its seed, prompt and model, so it can be reproduced.
- Undo = remove a layer.

---

## 15. Concrete code additions (suggested module layout)

All under `blender_scripts/forge_bpy/`:
- `bake.py`: add aux bakes (section 5), the green-channel flip and packing (section 1), triangulate-before-bake (gap 1), and `margin_type`.
- `tex_regions.py`: Tripo segment transfer, LAB k-means, click flood fill, ID → RGBA masks, neutralise + default tints.
- `tex_layers.py`: layer-stack JSON ↔ node-tree builder; smart-material recipes (edge wear, dirt, dust, wet, colour variation, hand-painted).
- `tex_project.py`: camera placement, ComfyUI client, back-projection with facing / visibility weights, seam re-projection.
- `tex_fix.py`: delight (AO divide, LF flatten, spec clamp), concept colour match, seam blend, albedo range clamp, GAN upscale wrapper.
- `tex_decal.py`: prompt / image decals, Grease Pencil scar → SDF → height / normal.
- `export`: per-engine packing plus the UE Python and Unity `AssetPostprocessor` import scripts.
- `qa.py` additions: VRAM estimate, seam ΔE, albedo range, AO-albedo correlation, per-region texel density.

---

## Sources
- [S1] UE forum, RGB mask compression artifacts: https://forums.unrealengine.com/t/rgb-texture-mask-compression-artifacts/136275 ; https://forums.unrealengine.com/t/masks-texture-compression-considerably-degrading-textures/106490 ; https://forums.unrealengine.com/t/bc7-rgb-channels-bleed-into-alpha-channel/2689122
- [S2] UE 4.27 Texture Compression Settings: https://docs.unrealengine.com/4.27/RenderingAndGraphics/Textures/TextureCompressionSettings ; UE Python TextureCompressionSettings: https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/TextureCompressionSettings
- [S3] UE texture format support and settings: https://dev.epicgames.com/documentation/en-us/unreal-engine/texture-format-support-and-settings-in-unreal-engine
- [S4] Unreal tech-art textures guide (community): https://adamkomarowski.github.io/unrealtechart/book/unrealengine/textures/
- [S5] UE TextureGroup API: https://dev.epicgames.com/documentation/unreal-engine/API/Runtime/Engine/TextureGroup
- [S6] UE Texture Asset Editor: https://dev.epicgames.com/documentation/en-us/unreal-engine/texture-asset-editor-in-unreal-engine
- [S7] Unity URP Lit shader: https://docs.unity3d.com/Manual/urp/lit-shader.html
- [S8] Unity HDRP Mask Map and Detail Map: https://docs.unity3d.com/Packages/com.unity.render-pipelines.high-definition@17.0/manual/Mask-Map-and-Detail-Map.html
- [S9] Maxon C4D texel density: https://help.maxon.net/c4d/en-us/Content/html/Texel_Density.html
- [S10] Rebusfarm texel density basics: https://rebusfarm.net/blog/texel-density-basics-every-artist-should-know
- [S11] Texture resolution guide: https://www.strayspark.studio/blog/texture-resolution-guide-games-512-1k-2k-4k ; UE forum texel density: https://forums.unrealengine.com/t/texel-density-standards-for-aaa-first-person-shooter-games/1646118
- [S12] Substance Curvature baker: https://helpx.adobe.com/substance-3d-bake/bakers-settings/curvature.html
- [S13] Substance Curvature from Mesh: https://helpx.adobe.com/substance-3d-bake/bakers-settings/curvature-from-mesh.html
- [S14] Curvature maps in Blender: https://www.strayspark.studio/blog/curvature-maps-blender-substance-painter-alternative
- [S15] CurvBake Pro: https://blenderartists.org/t/release-curvbake-pro-high-quality-curvature-map-baker-gpu-optix-c/1649540
- [S16] Blender manual, Render Baking (5.0 / 5.1): https://docs.blender.org/manual/en/5.1/render/cycles/baking.html
- [S17] Attribute Baker extension: https://extensions.blender.org/add-ons/attribute-baker/
- [S18] Tripo texture parameters (WaveSpeed): https://wavespeed.ai/docs/docs-api/tripo3d/texture
- [S19] Scenario Tripo docs: https://docs.scenario.com/docs/3d-model-generation-tripo-ai
- [S20] ComfyUI TripoTextureNode: https://docs.comfy.org/built-in-nodes/TripoTextureNode.md ; Alibaba Tripo texture API: https://help.aliyun.com/en/model-studio/tripo-texture-api-reference
- [S21] StableProjectorz: https://forums.unrealengine.com/t/free-tool-for-texturing-2d-and-3d-assets-using-ai-stableprojectorz/1612620
- [S22] Dream Textures projection/inpaint PR: https://www.github.com/carson-katri/dream-textures/pull/616
- [S23] SD + ControlNet texture projection with Blender: https://medium.com/@mattzq/stable-diffusion-controlnet-texture-projection-workflow-with-blender-8dac4b7154c2
- [S24] DANTE-W, diffuse albedo neural texturing: https://huggingface.co/papers/2606.30677.md ; https://gamedev.net/news/4215-dante-w-diffuse-albedo-neural-texturing-in-the-wild/
- [S25] Unity texture formats by platform: https://docs.unity3d.com/Manual/texture-choose-format-by-platform.html ; https://docs.unity3d.com/2023.2/Documentation/Manual/texture-compression-formats.html
- [S26] Oodle Texture in UE: https://dev.epicgames.com/documentation/unreal-engine/oodle-texture-in-unreal-engine?lang=en-US
- [S27] ASTC format overview (Arm astc-encoder): https://chromium.googlesource.com/external/github.com/ARM-software/astc-encoder/+/a1abaae60e75b3a69a089a8d7d708d8d78fc3e8e/Docs/FormatOverview.md
- [S28] Arm "Yet more ASTC compression": https://developer.arm.com/community/arm-community-blogs/b/mobile-graphics-and-gaming-blog/posts/yet-more-astc-compression ; NVIDIA ASTC for game assets: https://developer.nvidia.com/astc-texture-compression-for-game-assets
- [S29] UE Streaming Virtual Texturing (UDIM): https://dev.epicgames.com/documentation/en-us/unreal-engine/streaming-virtual-texturing-in-unreal-engine
- [S30] UE Virtual Texturing: https://dev.epicgames.com/documentation/en-us/unreal-engine/virtual-texturing-in-unreal-engine
- [S31] UE forum, VT/UDIM opacity and displacement limits: https://forums.unrealengine.com/t/feature-request-virtual-texture-with-opacity-map-and-displacement-udims-problem/599955
- [S32] UE decal materials: https://dev.epicgames.com/documentation/en-us/unreal-engine/decal-materials-in-unreal-engine
- [S33] UE mesh decals: https://dev.epicgames.com/documentation/en-us/unreal-engine/using-mesh-decals-in-unreal-engine

**Repo files referenced:**
- /home/user/Image-to-Game-asset/blender_scripts/forge_bpy/bake.py
- /home/user/Image-to-Game-asset/forge/tripo_stage.py
- /home/user/Image-to-Game-asset/forge/spec.py
- /home/user/Image-to-Game-asset/forge/qa.py
- /home/user/Image-to-Game-asset/jobs/bull/review/final/REVIEW.md
