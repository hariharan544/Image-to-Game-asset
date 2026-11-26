# Research: tattered (fact-checked)

FACT-CHECKED REPORT: Tattered cloth, capes, membranes and alpha-cutout cards (Forge: Blender 5.3 -> UE5 AAA / Unity URP mobile)

The original report is mostly sound. I found 6 errors that would break an implementation and fixed them.

Several sources could not be reached from this session: docs.unity3d.com, issues.unrealengine.com and bgolus.medium.com. Claims that depend only on those pages are confirmed through search-result summaries or mirrors, as noted.

Verification is strongest for:
- the repo,
- the Unity URP Lit.shader, BaseShaderGUI.cs and LitGUI.cs source (fetched from GitHub master),
- the Blender API and manual summaries,
- UE Python API summaries.

======================================================================
A. CORRECTIONS THAT CHANGE CODE (read first)
======================================================================
1. **Shrinkwrap has no `project_axis` property (CORRECTED).**
   - ShrinkwrapModifier projects only along the booleans `use_project_x`, `use_project_y` and `use_project_z` (all default False).
   - With all three off, PROJECT uses the vertex normals.
   - The other properties exist: `wrap_method` enum NEAREST_SURFACEPOINT / PROJECT / NEAREST_VERTEX / TARGET_PROJECT, `use_negative_direction` (default False) and `use_positive_direction` (default True in 3.1+/dev; older docs say False).
   - Fix: build the grid already oriented by the PCA frame and leave all axis flags off, so it projects along the grid normal. Better, use Option B (BVHTree front/back ray average), which is deterministic and needs no modifier.
2. **The BVHTree hit test in §1a is wrong (CORRECTED).**
   - `BVHTree.ray_cast` returns `(location, normal, index, distance)`, with every element `None` on a miss.
   - Test `loc is not None`, not the truthiness of a Vector.
   - Correct form: `loc, nrm, idx, d = bvh.ray_cast(origin, direction, max_d); t[i] = d+eps if loc is not None else 0.0`.
   - Rays are not back-face culled. That is what we want here, because the inward ray hits the opposite side's back face. (No-culling: CONFIRMED by API knowledge, UNVERIFIED in the 5.3 docs.)
3. **Data Transfer apply silently produces no weights unless the destination groups exist (CORRECTED/ADDED).**
   - The manual says the modifier "will not create destination data layers"; you have to press Generate Data Layers first.
   - Script: `bpy.ops.object.datalayout_transfer(modifier=mod.name)` with the card active, then `modifier_apply`. (Operator name from API knowledge; UNVERIFIED in 5.3 docs.)
   - Alternative: the one-shot `bpy.ops.object.data_transfer(use_reverse_transfer=False, data_type='VGROUP_WEIGHTS', vert_mapping='POLYINTERP_NEAREST', layers_select_src='ALL', layers_select_dst='NAME')` with source selected and card active. It creates the groups.
   - Modifier fields: `use_vert_data=True` must also be set, plus `data_types_verts={'VGROUP_WEIGHTS'}`, `vert_mapping='POLYINTERP_NEAREST'`, `layers_vgroup_select_src='ALL'`, `layers_vgroup_select_dst='NAME'` (CONFIRMED names, API knowledge).
   - Known pitfall: a mismatched group set makes the transfer fail for all groups (developer.blender.org/T53988).
4. **URP back faces and shadows: the renderer flag is redundant (CORRECTED).**
   - The URP Lit ShadowCaster pass uses `Cull[_Cull]` and `_ALPHATEST_ON` (CONFIRMED in Lit.shader).
   - With `_Cull=0` (Off) the shadow pass is already two-sided, so `MeshRenderer.shadowCastingMode=TwoSided` is redundant (harmless).
   - With the recommended duplicated back sheet plus `_Cull=2` (Back), shadows come from both sheets. No flag is needed.
5. **The URP script should not hand-set keywords only (IMPROVED).**
   - URP's own `BaseShaderGUI.SetupMaterialBlendMode(Material)` (public static, namespace UnityEditor) sets these together:
     - the `_ALPHATEST_ON` keyword,
     - queue `RenderQueue.AlphaTest` (2450),
     - tag `RenderType=TransparentCutout`,
     - ZWrite,
     - `_AlphaToMask=1` when alpha clip is on.
   - Set the floats, then call it. If you hand-roll instead, you miss `_AlphaToMask`.
   - That matters on mobile: with MSAA on, alpha-to-coverage is active, and that also costs early-Z on Mali. Decide deliberately; `_AlphaToMask=0` is a valid cheaper choice on mobile without MSAA.
6. **The UE override struct must be written back (CORRECTED).**
   - `base_property_overrides` is a struct copy. Edit it, then `mi.set_editor_property('base_property_overrides', ov)`, then `unreal.MaterialEditingLibrary.update_material_instance(mi)`.
   - Each value needs its `override_*` flag set True, or it is ignored (UE forum thread 672369).

======================================================================
0. REPO FINDINGS (CONFIRMED by reading the code)
======================================================================
- `bake._new_image()` line 44: `bpy.data.images.new(name, size, size, alpha=False, float_buffer=False)`. CONFIRMED.
- `SENTINEL = (1.0, 0.0, 1.0, 1.0)` at line 123. `_fill_colours(rgb, valid, miss, iterations, ...)` at line 139. `_resolve_sentinel(img, cov, mtype, iterations=64)` at line 169. CONFIRMED.
  - `_resolve_sentinel` also paints texels outside UV coverage with a neutral or mean colour (line 188–189) and then forces `px[...,3]=1.0` (line 190). CONFIRMED.
  - Card path: run `_fill_colours` with `miss = (mask==0)` across the whole island, and skip the neutral-outside fill.
- `_bake()` calls `bpy.ops.object.bake(..., margin=margin, use_clear=False)` (line 109). `_ChannelAsEmission` class at line 70. `C.select_only(high, low, active=low)` at line 283. CONFIRMED.
- `finalize._pack_textures(..., ao_into_basecolor=False)` writes `T_{stem}_BC.png` (line 189, via `copy_color`) and `{stem}_BaseMap.png` (line 198, with an `ao_into_basecolor` branch at 199). CONFIRMED.
  - The AO multiply must touch RGB only and keep A.
- `finalize._setup_preview_engine(engine, res)` exists (line 50). CONFIRMED. Check that it uses `'BLENDER_EEVEE'` (see §3f).
- `appendages._components(n, a, b)` (line 69) exists. Its classifier returns horn / ear / tail / back_extra. There is no thickness metric. CONFIRMED.
- The `steps.py` placement (`classify_cards()` after `prepare_retopo()`, card branch in `run_retopo` / `run_uv` / `run_bake` / `finalize`) is a sound proposal; this is design, not a fact to verify.

======================================================================
1. CLASSIFICATION
======================================================================
- §1a numpy + BVHTree approach: valid with fix A2.
  - `BVHTree.FromObject(obj, depsgraph)` returns object-space data built from the evaluated mesh. CONFIRMED (API knowledge).
  - Vertex indices match `ev.to_mesh()` only if no topology-changing modifiers differ. Build both from the same evaluated object, as the code does.
  - `MeshVertex.normal` is read-only and auto-computed in 4.1+/5.x. CONFIRMED (API knowledge).
  - Timing estimate: UNVERIFIED.
- §1b Geometry Nodes:
  - The Raycast node exists, with inputs Target Geometry, Attribute, Interpolation, Source Position, Ray Direction, Ray Length, and outputs Is Hit, Hit Position, Hit Normal, Hit Distance, Attribute. Node idname `GeometryNodeRaycast`; Store Named Attribute is `GeometryNodeStoreNamedAttribute`. CONFIRMED (API knowledge; docs.blender.org not fetched).
  - Read back from `obj.evaluated_get(dg).data.attributes["forge_thick"].data.foreach_get("value", buf)`. CONFIRMED pattern.
  - Pitfall (ADDED): raycasting a geometry against itself from points on its surface needs the ε offset, or it self-hits at distance ~0. The report includes it.
- §1c thresholds, PCA ratios, complexity metric, multi-hit fold test: heuristics, UNVERIFIED. Must be tuned on Tripo assets.

======================================================================
2. CARD BUILD
======================================================================
- `bmesh.ops.create_grid(bm, x_segments=, y_segments=, size=, matrix=, calc_uvs=)`. CONFIRMED (API knowledge).
  - `calc_uvs=True` needs an existing UV layer; it is simpler to write planar UVs yourself as proposed.
- `bmesh.ops.reverse_faces(bm, faces=...)`. CONFIRMED.
- Shrinkwrap: see A1. Option B (front/back BVH average) is recommended.
- "Hard splits give uneven cage normals" is in line with the Blender manual's baking note on cages; for a plane the manual also says the cage method "is a preferable method when baking into planes". CONFIRMED in spirit.
- Heat weighting error string "Bone Heat Weighting: failed to find solution for one or more bones". CONFIRMED (well known). ARP 3.79 behaviour on open sheets: UNVERIFIED.
- Data Transfer: see A3.
- Polycount savings: estimates, UNVERIFIED.

======================================================================
3. BAKING
======================================================================
- `bpy.ops.object.bake(type='EMIT', use_selected_to_active=True, use_cage=False, cage_extrusion=, max_ray_distance=, margin=, margin_type='EXTEND'|'ADJACENT_FACES', use_clear=False, target='IMAGE_TEXTURES')`. All parameter names and enum values CONFIRMED (API knowledge plus the manual summary).
- §3c ray semantics. CONFIRMED (manual 2.90–5.0 summaries, API BakeSettings):
  - Max Ray Distance applies only when Cage is off ("only available when not using Cage"; 0 = unlimited).
  - Extrusion is used both with and without a cage.
  - Without a cage, rays follow the low mesh normals.
  - ADDED: rays start at low + extrusion·normal and travel inward up to `max_ray_distance`. If extrusion is greater than h, the start point is outside the front surface and the first hit is the front surface. The 2·extrusion rule stays below the back surface of the same slab only while `2·ext < ext + h + 2h`, i.e. it can reach the far side of thick regions. Clamp `max_ray_distance ≤ ext + h` (front hit plus a margin) so a hole in the front layer cannot be "filled" by the back layer or a fold.
- Cycles bake anti-aliasing: commonly reported as point-sampled per texel (no AA), so 2× supersample then downsample is the right defensive choice. UNVERIFIED in the official docs.
- `scene.cycles.samples=1` for EMIT is fine (deterministic emission). Also set `scene.render.bake.use_selected_to_active`-equivalent args as above.
- `bpy.data.images.new(name, w, h, alpha=True)`, `img.alpha_mode='STRAIGHT'`, `img.pixels.foreach_set`, `img.file_format='PNG'`. CONFIRMED.
  - ADDED: set `img.filepath_raw` before `img.save()`, or use `img.save(filepath=...)` (4.x+; UNVERIFIED for 5.3). PNG is written RGBA when the image has an alpha plane.
- Straight alpha with dilated RGB under A=0, never premultiplied: CONFIRMED as standard practice. It matches Unity's alphaIsTransparency behaviour (dilate colour into transparent texels).
- `margin=0` for the coverage pass: correct.
- Bake transparency reports (T72085, #119610): cited as open. Status UNVERIFIED (projects.blender.org not fetched). The advice to bake coverage from geometry stands either way.

3f. Blender material
- `Material.surface_render_method` enum DITHERED / BLENDED, default DITHERED. CONFIRMED (5.1/dev API summary).
- `blend_method` still exists in 5.0 as Deprecated (OPAQUE/CLIP/HASHED/BLEND). CORRECTED: it is deprecated, not removed. Do not rely on it.
- `Material.shadow_method`: absent from 5.x API search results; removal UNVERIFIED (cited #130822 not fetched). Guard with `hasattr`.
- `use_backface_culling`: CONFIRMED.
- The engine id `'BLENDER_EEVEE_NEXT'` became `'BLENDER_EEVEE'` in 5.0, listed as a breaking change. CONFIRMED (5.0 EEVEE release notes).
- ADDED: `Material.use_nodes` is deprecated since 5.0 (removal planned 6.0). Don't toggle it in new code.
- Alpha Clip emulated with a Math Greater Than node into Alpha (4.2 migration). CONFIRMED by the migration-notes summary.
- FBX carries no blend mode, so set materials from the manifest: CONFIRMED practice. glTF alpha-mode detection in 5.3: UNVERIFIED.

======================================================================
4. UNREAL ENGINE 5
======================================================================
- Blend Mode Masked, Two Sided, Opacity Mask; default Opacity Mask Clip Value 0.3333. CONFIRMED (long-standing engine default).
- Python:
  - `unreal.BlendMode.BLEND_MASKED`. CONFIRMED.
  - `MaterialInstanceBasePropertyOverrides` fields `override_blend_mode`/`blend_mode`, `override_two_sided`/`two_sided`, `override_opacity_mask_clip_value`/`opacity_mask_clip_value`. CONFIRMED (Python API pages 4.26–5.1 + dev.epicgames.com).
  - 5.6+ spelling UNVERIFIED but unchanged in the latest listing found. Must be written back per A6.
- `unreal.MaterialInstanceConstantFactoryNew`, `MaterialEditingLibrary.set_material_instance_texture_parameter_value`. CONFIRMED (API knowledge).
- Two Sided flips back-face normals: CONFIRMED (engine behaviour).
- UE-269216 (TwoSidedSign inverted for Nanite opacity mask): CONFIRMED via search summary. 5.5 regression, affects 5.5.4, listed fixed with target 5.7.
- UE-307863 (Dither Opacity Mask on Nanite in 5.6): UNVERIFIED (tracker unreachable; ID appears in search results only).
- Nanite + masked forum bugs: CONFIRMED to exist in forum results. This includes "Nanite: unused VertexInterpolator node disables Opacity Mask" (forums 2734328). Keep cards non-Nanite (skeletal meshes are typically non-Nanite anyway).
- Texture compression: TC_Default picks DXT1/DXT5 (BC1/BC3) by alpha presence; TC_BC7 is available. CONFIRMED (engine knowledge).
  - ADDED: make sure "Compress Without Alpha" is off on card BC textures.
- Alpha sharpening `a' = (a − clip)/max(fwidth(a), 1e-4) + 0.5`: CONFIRMED via a secondary quote of Golus's Unity implementation (`col.a = (col.a - _Cutoff) / max(fwidth(col.a), 0.0001) + 0.5;`). The report's `saturate(...)` wrapper is fine. Original article not fetched.

======================================================================
5. UNITY URP (all CONFIRMED against Graphics repo master source unless noted)
======================================================================
Property names in Lit.shader:
- `_Cutoff` Range(0,1) = 0.5
- `_AlphaClip` [ToggleUI] = 0
- `_Cull` = 2 (Back; Off = 0)
- `_Surface` = 0 (Opaque)
- `_AlphaToMask` = 0
- `_SmoothnessTextureChannel` = 0
- `_WorkflowMode` = 1 (Metallic)
- `_BaseMap`, `_MetallicGlossMap`

Other confirmed behaviour:
- `_SmoothnessTextureChannel`: 0 = SpecularMetallicAlpha ("Metallic Alpha"), 1 = AlbedoAlpha.
  - `_SMOOTHNESS_TEXTURE_ALBEDO_CHANNEL_A` is enabled when the channel is AlbedoAlpha and the surface is Opaque. Alpha-clipped materials are Opaque, so the conflict is real. Use 0.
- Alpha clip on an opaque surface: queue AlphaTest, `RenderType=TransparentCutout`, `_ALPHATEST_ON`, and `AlphaToMask=1` (BaseShaderGUI).

Corrected script:
```csharp
m.shader = Shader.Find("Universal Render Pipeline/Lit");
m.SetFloat("_Surface", 0); m.SetFloat("_AlphaClip", 1); m.SetFloat("_Cutoff", 0.5f);
m.SetFloat("_Cull", 2);            // duplicated back sheet; use 0 for single-sheet "Both"
m.SetFloat("_SmoothnessTextureChannel", 0);
UnityEditor.BaseShaderGUI.SetupMaterialBlendMode(m);  // keywords, queue 2450, tag, _AlphaToMask
// optional mobile w/o MSAA: m.SetFloat("_AlphaToMask", 0);
```
- `SetupMaterialBlendMode` exists as a public static wrapper on master. Its availability in the installed URP version is UNVERIFIED (older URPs used `BaseShaderGUI.SetMaterialKeywords`).
- Back-face lighting with Render Face Both (normals not flipped): consistent with the Unity tutorial cited. UNVERIFIED directly (docs.unity3d.com unreachable). The duplicated, flipped back sheet recommendation stands.

TextureImporter:
- `alphaSource=FromInput`, `alphaIsTransparency` (dilates colour into transparent texels; not supported for HDR), `mipmapEnabled`, `mipMapsPreserveCoverage`, `alphaTestReferenceValue`, `sRGBTexture`. CONFIRMED to exist (docs.unity.com 6000.x TextureImporterSettings summaries).
- How coverage preservation uses the reference value: UNVERIFIED in docs. In practice set `alphaTestReferenceValue` equal to the material `_Cutoff`.
- Some settings must go through `TextureImporterSettings` + `SetTextureSettings`.
- ASTC 6x6 / 4x4 and the ETC2 fallback: standard practice; specific values UNVERIFIED.

Mobile cost (discard / alpha-to-coverage defeats early-Z/HSR on Mali; PowerVR "do not use discard"): CONFIRMED by the cited Arm/Imagination sources (titles and summaries; PDFs not re-fetched).

======================================================================
6. BUDGETS: all UNVERIFIED recommendations (unchanged). Keep the "≥4 texels across the thinnest strand" rule as a QA check.

======================================================================
7. ADDITIONS THE REPORT MISSED
======================================================================
- Clamp max_ray_distance (see §3c) so that holes in the front layer are not filled by the back or fold layers.
- Data Transfer needs layer generation (A3).
- URP `_AlphaToMask` is auto-enabled with alpha clip. Decide per platform.
- UE: turn off "Compress Without Alpha" on card BC textures, and write overrides back with `update_material_instance`.
- Blender 5.x: `blend_method` is deprecated (not gone) and `use_nodes` is deprecated. Guard `shadow_method` with `hasattr`.
- `_resolve_sentinel`'s outside-coverage neutral fill plus forced A=1 must be bypassed for card images, not just alpha=True at creation.

======================================================================
SOURCES
======================================================================
Fetched:
- Unity URP source (GitHub master):
  - https://raw.githubusercontent.com/Unity-Technologies/Graphics/master/Packages/com.unity.render-pipelines.universal/Shaders/Lit.shader
  - https://raw.githubusercontent.com/Unity-Technologies/Graphics/master/Packages/com.unity.render-pipelines.universal/Editor/ShaderGUI/BaseShaderGUI.cs
  - https://raw.githubusercontent.com/Unity-Technologies/Graphics/master/Packages/com.unity.render-pipelines.universal/Editor/ShaderGUI/ShadingModels/LitGUI.cs

From search-result summaries:
- Blender:
  - Shrinkwrap API: https://docs.blender.org/api/dev/bpy.types.ShrinkwrapModifier.html ; https://docs.blender.org/api/2.93/bpy.types.ShrinkwrapModifier.html
  - Material API 5.x: https://docs.blender.org/api/5.3/bpy.types.Material.html ; https://docs.blender.org/api/5.1/bpy.types.Material.html ; https://projects.blender.org/blender/blender/issues/113976
  - EEVEE id rename: https://developer.blender.org/docs/release_notes/5.0/eevee/
  - Baking manual: https://docs.blender.org/manual/en/4.2/render/cycles/baking.html ; https://docs.blender.org/manual/en/4.5/render/cycles/baking.html ; https://docs.blender.org/api/3.3/bpy.types.BakeSettings.html
  - Data Transfer: https://docs.blender.org/manual/en/4.1/modeling/modifiers/modify/data_transfer.html ; https://developer.blender.org/T53988
- Unreal:
  - UE Python overrides: https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/MaterialInstanceBasePropertyOverrides ; https://forums.unrealengine.com/t/how-to-set-materialinstanceconstant-blend-mode-in-python/672369
  - UE TwoSidedSign / Nanite: https://issues.unrealengine.com/issue/UE-269216 ; https://forums.unrealengine.com/t/nanite-twosidedsign-is-backwards/2500286 ; https://forums.unrealengine.com/t/nanite-unused-vertexinterpolator-node-disables-opacity-mask-material-renders-opaque/2734328
- Unity TextureImporterSettings: https://docs.unity.com/ja-jp/engine/6000.0/script-reference/unityeditor/textureimportersettings
- Alpha sharpening: https://bgolus.medium.com/anti-aliased-alpha-test-the-esoteric-alpha-to-coverage-8b177335ae4f (formula via a secondary quote, https://bugs.dolphin-emu.org/issues/11626)

All other sources from the original report are retained but were not re-fetched.

Network note: docs.unity3d.com, issues.unrealengine.com and bgolus.medium.com are not reachable from this session. They have to be allowed in the session's network settings before anyone can fetch them.

Repo files: /home/user/Image-to-Game-asset/blender_scripts/forge_bpy/bake.py, /home/user/Image-to-Game-asset/blender_scripts/forge_bpy/finalize.py, /home/user/Image-to-Game-asset/blender_scripts/forge_bpy/appendages.py, /home/user/Image-to-Game-asset/blender_addon/forge_send/steps.py
