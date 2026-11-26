# Research gap: Lightmap UVs, vertex colour channels and static lighting data

# Forge gap report: lightmap UVs, vertex-colour channels and static lighting data

**How this was researched.** I could not fetch dev.epicgames.com or docs.unity3d.com directly: the session's network does not allow those hosts. Facts below come from search-engine extracts of those official pages, plus Unreal forums, the Blender tracker and devtalk. Anything I could not confirm against a source is marked **UNVERIFIED**. API property names written from memory are also marked UNVERIFIED and should be checked by introspection at runtime (`dir()` in bpy, `unreal`, or the Unity C# API).

---

## 0. Summary: what Forge should decide per asset

| Asset class (Forge auto-classifies) | UV0 | UV1 (2nd channel) | UV2/UV3 | Vertex colour profile | UE5 import | Unity URP import |
|---|---|---|---|---|---|---|
| **Static prop / environment piece, non-Nanite** (mobile, or UE with baked lighting) | Material UVs; may overlap or mirror | **Authored, unique, non-overlapping lightmap UV** | free | `PROP` | Generate Lightmap UVs **OFF**, Light Map Coordinate Index = 1, Light Map Resolution computed by Forge | Generate Lightmap UVs **OFF** (authored uv2 is used), Contribute GI on, Receive GI = Lightmaps |
| **Static prop, Nanite** (UE AAA, Lumen) | same | Authored UV1 anyway: cheap, and needed if a project bakes lighting or for the fallback mesh | free (Nanite reportedly reads UV0–3 only) | `PROP` | Nanite on, LMCI = 1, low LM res; Lumen needs no lightmap | same as non-Nanite row (the Unity build is non-Nanite) |
| **Mechanical, with moving parts** | same | Static shell: authored UV1. Moving parts: no UV1 (they are lit by probes) | free | `PROP` (+ `A` = emissive mask option) | Split into a static shell plus moving static-mesh components or skeletal parts | Split into a lightmapped static shell plus moving parts that use Light Probes |
| **Skinned character or creature** | same | **No lightmap UV.** The channel is free for other data | Smoothed outline normals (if toon) | `CHAR` | Volumetric Lightmap or Lumen; capsule shadows optional | Receive GI = Light Probes, `probeAnchor` on a shared bone |
| **Swaying attachments** (banners, cables, plants on props) | same | UV1 only if the mesh is static and lightmapped | free | `SWAY` (Crysis-style) | WPO material reads the vertex colours | Shader Graph WPO reads the vertex colours |

Core rule: **Forge always authors UV1 for static exports and turns off engine-side lightmap UV generation.** The engine generators cannot honour Forge's knowledge of hard edges and island scale, and Unity's generator also changes the import result whenever its settings change.

---

## 1. Lightmap UVs (second UV channel)

**(a) Why it matters.** Baked lighting (Unity URP mobile, and UE projects using Lightmass/GPU Lightmass) stores per-texel light in a texture mapped by a second UV set. Every surface needs unique texels, so UV0 cannot be reused when it has mirrored, stacked or tiled islands, which mobile texture budgets encourage. Overlaps cause wrong or bleeding light. Too little padding causes seams and bleeding at mip and low resolutions.

**(b) Topology / UV requirements.**
- All charts must be inside [0,1], **non-overlapping**, and of **uniform world-space texel density**. Lighting resolution follows area, not detail importance, though a small importance bias is fine.
- Cut seams at hard shading edges. Unity's generator uses a "Hard Angle" of 88° by default, so Forge should match that threshold. One continuous chart across a 90° corner bleeds light around the corner.
- **Padding:** Unity says padding between charts must be "at least two full texels" in lightmap space. UE's "Min Lightmap Resolution" sets packing padding so that packing is "texel accurate down to" that resolution, and Epic advises a power of two equal to the lowest resolution the mesh will use. 64 is the commonly observed default (forum evidence; the official default value is UNVERIFIED).
- Cost: UV1 seams add vertex splits. My heuristic is +10–30 % vertices (UNVERIFIED). Each extra UV channel costs 4–8 bytes per vertex. Mobile budgets should count this.
- Mirroring and rotation inside UV1 are fine; overlap is not.

**(c) Rig requirements.** None for static meshes. Skinned meshes are never lightmapped in Unity (skinned meshes "cannot use baked lightmaps") or in UE (skeletal meshes are dynamic-lit). So Forge skips UV1 lightmap generation for anything with an Armature modifier.

**(d) Texture / material.** UV1 holds no authored textures. The engine generates lightmaps and shadowmasks:
- **UE:** HQ lightmaps on desktop, LQ on mobile.
- **Unity:** Lightmap Directional Mode (Non-Directional is cheaper on mobile), Lightmap compression and Max Lightmap Size are Lighting-window settings.

Do not use UV1 for detail maps on static meshes. Put detail and tiling maps on UV0 or UV2.

**(e) Creating it automatically in Blender (bpy). Fully procedural; no director click.**

1. **Create the layer.** `lm = me.uv_layers.new(name="UV1_Lightmap", do_init=True)` copies the active UV0. Guarantee the order: index 0 = `UV0_Main`, index 1 = `UV1_Lightmap`. FBX exports UV sets in layer order and both engines map them by index. If extra layers exist, rebuild them in order.
2. **Choose a chart source.**
   - If UV0 has no overlaps and no stacked or mirrored islands, reuse the UV0 islands. Additionally cut at edges with angle > 88°: mark seams from `bmesh` `edge.calc_face_angle() > radians(88)`, then `bpy.ops.uv.unwrap` only the affected islands.
   - Otherwise (mirrored or overlapping UV0), run `bpy.ops.uv.smart_project(angle_limit=radians(66), island_margin=0, area_weight=0, scale_to_bounds=False)` with `me.uv_layers.active = lm`.
   - `bpy.ops.uv.lightmap_pack(PREF_CONTEXT='ALL_FACES', PREF_PACK_IN_ONE=True, PREF_NEW_UVLAYER=False, PREF_BOX_DIV=12, PREF_MARGIN_DIV=0.1)` is a cheap fallback for hard-surface boxes. It makes one chart per face or quad group, so it creates many seams and wastes space. Its existence in Blender 5.x is unconfirmed (the 5.0 API page I saw did not show it), so **UNVERIFIED in 5.3**: test with `hasattr(bpy.ops.uv, "lightmap_pack")`.
3. **Equalise density.** Run `bpy.ops.uv.average_islands_scale()` on the lightmap layer.
4. **Pack.**
   - UVPackmaster 4 is preferred. Its packing logic is Python-scriptable since v3. Operator and property names are **UNVERIFIED**: discover them with `[o for o in dir(bpy.ops) if 'uvpm' in o.lower()]` and the scene property group. Set texture size = Min Lightmap Resolution (e.g. 64), pixel margin = 2 px, rotation on, heuristic search on for final quality (time-boxed).
   - Built-in fallback: `bpy.ops.uv.pack_islands(margin_method='FRACTION', margin=2/min_res, rotate=True, shape_method='CONCAVE')`.
5. **Validate.** Rasterise each island's triangles in numpy into a `min_res × min_res` grid, dilated by 1 texel, then fail if any texel holds two island IDs, if any UV falls outside [0,1], or if any face has zero area. Also report packing efficiency (used area / total).
6. **Recommend a lightmap resolution.** `res = clamp(pow2_ceil(sqrt(surface_area_m2 / efficiency) * texels_per_m), 32, 1024)`. Example densities: mobile 8–16 t/m, AAA 16–32 t/m. These are heuristics, **UNVERIFIED** as industry numbers. Write the value to a sidecar `asset.forge.json` (see §4) because FBX cannot carry it.

**(f) Engine notes.**

*UE5*
- Static Mesh Build Settings: **Generate Lightmap UVs**, **Source Lightmap Index**, **Destination Lightmap Index**, **Min Lightmap Resolution**.
- Mesh Details: **Light Map Coordinate Index** (should match the destination index; default 1) and **Light Map Resolution**.
- With authored UV1, set Generate Lightmap UVs = false, otherwise UE repacks into the destination index.
- Python names, **UNVERIFIED**: `unreal.MeshBuildSettings.generate_lightmap_u_vs / src_lightmap_index / dst_lightmap_index / min_lightmap_resolution`, applied via `StaticMeshEditorSubsystem.set_lod_build_settings`, and `StaticMesh.set_editor_property('light_map_coordinate_index', 1)` / `'light_map_resolution'`.
- Validate visually with the **Lightmap Density** view mode; this is the director check.
- **Nanite + baked lighting:** community reports describe black seams, "overlapping UV" errors when building lighting, and Volumetric Lightmap regressions in 5.4 (UE-218670). A workaround reported on the forums is to set the Nanite fallback to Relative Error = 0 before baking. Epic's official support status could not be confirmed (**UNVERIFIED**). Forge's AAA default should therefore be Nanite + Lumen (no lightmaps), while still shipping UV1.
- Lumen relies on Mesh Distance Fields, not UV1.

*Unity*
- Model Import → Model tab → Geometry → **Generate Lightmap UVs**. It writes to UV2 (the `TEXCOORD1` / `Mesh.uv2` channel). Settings: **Hard Angle** (88°), **Angle Error**, **Area Error**, **Margin Method** (Manual / Calculate since 2020.1), **Pack Margin**, and **Min Lightmap Resolution** / **Min Object Scale** (visible only when Margin Method = Calculate).
- With authored uv2, leave the option off.
- AssetPostprocessor, **UNVERIFIED names**: `ModelImporter.generateSecondaryUV=false`; `meshCompression = Off` for lightmapped meshes, because quantised UVs cause seams.
- Per renderer: Contribute Global Illumination static flag, `receiveGI = ReceiveGI.Lightmaps`, Scale In Lightmap set from Forge's resolution recommendation.
- Enlighten realtime GI may use uv3 (`TEXCOORD2`) when present (**UNVERIFIED**). Avoid putting data in uv3 on projects that use realtime GI.

---

## 2. Probe lighting for skinned and moving meshes

**(a) Why it matters.** Characters and moving mechanical parts must match the baked environment. Otherwise they look pasted-on, which matters most on mobile where everything else is baked.

**(b) Topology.** Split mechanical assets into a static shell and moving parts so the shell can be lightmapped. Keep each character as a few renderers that share one probe sample point.

**(c) Rig / engine components.**
- **Unity:**
  - `SkinnedMeshRenderer.lightProbeUsage = BlendProbes`.
  - **Anchor Override** (`probeAnchor`) should be a bone such as `spine_01` or the root. By default probes are sampled at the bounds centre. Unity's manual recommends one shared anchor when several meshes adjoin, to avoid a lighting discontinuity at the join. That applies to Forge's separate eyes, teeth, hair cards and body.
  - Light Probe Proxy Volume is for large dynamic objects, but LPPV is Built-in-pipeline only, not URP (**UNVERIFIED**).
  - **Adaptive Probe Volumes (Unity 6+ URP)** light **per pixel rather than per object** and place probes automatically. They need a Baking Set and URP-asset support. Renderers opt in with Receive GI = Light Probes. APV behaviour specifically on skinned meshes is not documented in what I found (**UNVERIFIED**). Recommend Light Probe Groups for low-end mobile and APV for mid/high tier.
- **UE:**
  - Skeletal and movable meshes get indirect light from the **Volumetric Lightmap** (baked lighting) or from Lumen.
  - For baked or mobile projects, add capsule indirect shadows via a **Shadow Physics Asset** on the skeletal mesh. Forge can generate it from ARP bones. Property name is **UNVERIFIED**.

**(d) Texture.** None. Optionally bake an AO or "probe darkening" term into vertex colour A or R (see §3) to fake contact occlusion that probes cannot provide.

**(e) Automation.** Detect skinned meshes from the Armature modifier. Write `probe_anchor_bone` to the sidecar (default: ARP `c_root_master`, deform `root.x` / spine). Choose a bone that does not translate wildly (avoid hands). Detect moving mechanical parts from the rig (bones with keyed transforms) or the earlier "retractable parts" step, then split them by bone weight: faces 100 % weighted to a non-root bone go to a separate part.

**(f) Engine notes.** See (c). The Unity postprocessor or prefab builder assigns `probeAnchor` to the same transform for every renderer of the asset.

---

## 3. Vertex-colour channel convention

**Constraints that drive the design:**
- **Exactly one RGBA colour set is reliably supported.** UE static and skeletal meshes carry one vertex-colour channel. Unity `Mesh.colors` is a single array. Blender's FBX exporter has had bugs exporting only the first attribute and now has `prioritize_active_color`. Extra scalars therefore go into UV2/UV3 as float2.
- Precision is 8 bits per channel in UE (`FColor`), so store masks, not precise data.
- Use the **POINT** domain (`me.color_attributes.new("FORGE_VC", 'FLOAT_COLOR', 'POINT')`) to avoid extra vertex splits. Use CORNER only when hard discontinuities are needed.

**Colour space. This is the trap.**
- Blender `FLOAT_COLOR` is stored linear. `BYTE_COLOR` is stored sRGB but exposed linear (`.color` vs `.color_srgb`).
- FBX exporter: `colors_type = 'SRGB' | 'LINEAR' | 'NONE'` (default SRGB). The FBX format does not specify a colour space.
- **UE's FBX importer treats vertex colours as sRGB and converts them to linear** (Epic forum). So export **`colors_type='SRGB'`** for UE; the shader then receives Blender's stored linear value. There is a reported bug where meshes built from MeshDescription brighten vertex colours.
- Unity is believed to pass vertex colours through raw with no conversion (**UNVERIFIED**). So export **`colors_type='LINEAR'`** for Unity builds; the shader then receives the same stored values.
- glTF `COLOR_0` is linear by spec.
- **Forge must ship a calibration asset** `Forge_VCTest`: a strip of vertices at 0 / 0.25 / 0.5 / 0.75 / 1 per channel. Run it through both export paths once per engine version and check the values with a debug material. Either confirm the rule above or flip the setting.

### Proposed profiles (written to the sidecar as `vc_profile`)

| Profile | R | G | B | A |
|---|---|---|---|---|
| `PROP` (static and mechanical) | Baked AO / cavity | Edge wear (convexity) | Dirt / grime (cavity + up-facing gradient) | Tint region ID, quantised in 1/8 steps (0 = untinted) |
| `MECH_EMISSIVE` (variant of `PROP`) | AO | Edge wear | Damage / burn mask | Emissive mask (lights, screens) |
| `SWAY` (Crysis convention) | Edge stiffness / flutter | Per-element phase | Overall bend stiffness | AO |
| `CHAR` (skinned, toon-capable) | AO / shadow-threshold offset | Damage / wetness / blood mask | Tint region ID | Outline width scale (1 = default, 0 = none) |

Notes on the profiles:
- `SWAY` follows Crysis: R = edge stiffness, G = per-leaf phase, B = overall stiffness, A = AO (GPU Gems 3 ch.16; channel assignment from memory, **UNVERIFIED** exact).
- `CHAR`: the Guilty Gear Xrd (GDC 2015) style also uses vertex colour for shadow-threshold and outline control. Exact channel mapping **UNVERIFIED**.
- Smoothed outline normals for toon go in UV2/UV3 (octahedral float2), not in colour.
- **Cloth weights:** UE Chaos Cloth and Unity Cloth paint their weights in-engine, not from vertex colour. Do not rely on vertex colour for cloth sim weights. Use `SWAY` (shader WPO) for cheap secondary motion and keep real cloth weights as a separate engine-side step (**UNVERIFIED** whether UE 5.x Dataflow cloth imports weight maps from FBX attributes).

**(a) Why it matters.** Per-vertex masks cost almost nothing on mobile, need no extra texture fetch, and survive texture LOD and atlasing. Wind and sway need per-vertex weights so that bases stay planted. Tint IDs let one asset produce many variants. Outline width avoids thick lines on fingers and thin parts.

**(b) Topology.** Masks need enough vertices to resolve them; tint boundaries need an edge loop at the boundary. Sway weights need vertical subdivisions (more than 4 segments along bending length). Forge's retopo step should insert loops where a mask gradient is steep. Detect this from per-face mask variance after transferring from the dense mesh.

**(c) Rig.** `SWAY` replaces bones for small secondary motion. `CHAR` A (outline) and G (damage) are shading-only. No extra bones.

**(d) Material.**
- UE: the VertexColor node drives the master material: AO multiply, wear/dirt lerp to detail layers, tint via the region-ID palette, WPO for sway (e.g. SimpleGrassWind's WindWeight input from vertex colour).
- Unity URP: the stock Lit shader ignores vertex colour, so Forge needs a custom Shader Graph using the **Vertex Color** node.

**(e) Generation in Blender. Procedural; at most one director click.**
- **AO:** `scene.render.bake.target='VERTEX_COLORS'` + `bpy.ops.object.bake(type='AO')` (Cycles) into the active colour attribute. Or transfer from the dense Tripo mesh's AO with a Data Transfer modifier / Geometry Nodes *Sample Nearest Surface*.
- **Wear / dirt:** `bpy.ops.paint.vertex_color_dirt(blur_strength, blur_iterations, clean_angle, dirt_angle, dirt_only, normalize)` gives a convexity/cavity map. Combine it with GN noise and normal·Z for grime.
- **Sway:** GN with normalised distance from the attach point, either `(pos.z - min.z)/h` or geodesic via *Shortest Edge Paths* (R/B). Phase comes from *Mesh Island* index → *Random Value* (G). Store with *Store Named Attribute* (FLOAT_COLOR, POINT), then apply the modifier.
- **Tint ID:** k-means (3–6 clusters) on the baked albedo per vertex. The **director clicks which clusters are tintable** once.
- **Outline width:** inward raycast thickness (GN *Raycast* along −normal), mapped so thin parts get small width.
- **Damage:** noise × wear, with one director slider for coverage.
- **Packing:** combine the masks into `FORGE_VC` and set it as active/render colour. Export with `colors_type` per engine and `prioritize_active_color=True`.

**(f) Engine import behaviour.**
- **UE:** FBX and Interchange option **Vertex Color Import Option** = Replace / Ignore / Override. Some versions default to *Ignore* on reimport (forum, UE 5.0.3), so Forge's import script must set **Replace** explicitly. Interchange's enum is `InterchangeVertexColorImportOption`. Nanite meshes keep vertex colours.
- **Unity:** colours import automatically into `Mesh.colors`. Mesh compression can quantise them. Gamma behaviour: see the calibration note above.

---

## 4. Engine-side glue (needed because FBX cannot carry the settings)

Forge writes a sidecar file `<asset>.forge.json` containing:
- `asset_class`
- `nanite: bool`
- `lightmap: {uv_index: 1, resolution, min_resolution}`
- `vc_profile`
- `vc_colorspace_exported`
- `probe_anchor_bone`
- `split_parts[]`

It is consumed by:
- **UE:** an Editor Python import hook (Interchange pipeline or `unreal.AssetImportTask` post-step). It sets Vertex Color Import Option = Replace, Generate Lightmap UVs = off, Light Map Coordinate Index = 1, Light Map Resolution, the Nanite flag and the Shadow Physics Asset.
- **Unity:** an `AssetPostprocessor` (`OnPreprocessModel` / `OnPostprocessModel`) that sets `generateSecondaryUV=false`, `meshCompression=Off`, static flags `ContributeGI`, `receiveGI`, Scale In Lightmap, and `lightProbeUsage` + `probeAnchor` for skinned renderers.

Director approval is visual only: the UE **Lightmap Density** view, a Blender overlay of the UV1 checker, and a vertex-colour channel preview per profile.

---

## Sources
- Epic, "Generating Lightmap UVs in Unreal Engine": https://dev.epicgames.com/documentation/en-us/unreal-engine/generating-lightmap-uvs-in-unreal-engine
- Epic, "Understanding Lightmapping": https://dev.epicgames.com/documentation/unreal-engine/understanding-lightmapping-in-unreal-engine?lang=en-US
- Min Lightmap Resolution default (forum): https://forums.unrealengine.com/t/min-lightmap-resolution-any-way-to-batch-edit/117405
- Nanite and baked lighting issues: https://forums.unrealengine.com/t/nanite-and-baked-lightmaps/235564 ; https://forums.unrealengine.com/t/enabling-nanite-is-causing-overlapping-uv-errors-when-building-static-lighting/644578 ; https://forums.unrealengine.com/t/is-gpu-lightmass-supposed-to-work-with-nanite/536988 ; https://issues.unrealengine.com/issue/UE-218670 ; https://forums.unrealengine.com/t/static-lighting-and-nanite-custom-fallback-settings-or-use-nanite/1616300
- Nanite UV0–3 limit (forum): https://forums.unrealengine.com/t/nanite-ignores-uv-channels-higher-than-3-bug-or-intended/1260470
- UE vertex-colour import: https://dev.epicgames.com/documentation/en-us/unreal-engine/fbx-import-options-reference-in-unreal-engine ; https://docs.unrealengine.com/5.0/en-US/PythonAPI/class/VertexColorImportOption.html ; https://docs.unrealengine.com/PythonAPI/class/InterchangeVertexColorImportOption.html ; https://forums.unrealengine.com/t/importing-vertex-colors-and-encoding/558856 ; https://forums.unrealengine.com/t/vertex-colors-are-interpreted-as-srgb-instead-of-linear-when-building-a-static-mesh-from-mesh-description/2729016 ; https://forums.unrealengine.com/t/fbx-not-importing-with-vertex-colours/458342
- Unity lightmap UVs: https://docs.unity3d.com/Manual/LightingGiUvs-Reference.html ; https://docs.unity3d.com/2020.2/Documentation/Manual/LightingGiUvs-GeneratingLightmappingUVs.html
- Unity probes / APV: https://docs.unity3d.com/ru/Manual/LightProbes-MeshRenderer.html ; https://docs.unity3d.com/Manual/urp/probevolumes-concept.html ; https://docs.unity3d.com/Manual/urp/probevolumes-use.html ; https://discussions.unity.com/t/urp-does-not-support-apv/1595290
- Unity linear workflow: https://docs.unity3d.com/Manual/linear-color-space.html
- Blender lightmap_pack / UV operators: https://docs.blender.org/api/4.2/bpy.ops.uv.html ; https://docs.blender.org/api/5.0/bpy.ops.uv.html
- Blender FBX colour export: https://projects.blender.org/blender/blender-addons/pulls/104435 ; https://devtalk.blender.org/t/srgb-linear-color-values-and-fbx-exports/10049 ; https://developer.blender.org/T98721 ; https://projects.blender.org/blender/blender-addons/issues/102905
- UVPackmaster 4: https://superhivemarket.com/products/uvpackmaster/ ; https://80.lv/articles/uvpackmaster-4-for-blender-released
- Crysis vegetation vertex colours (GPU Gems 3 ch.16, from memory): https://developer.nvidia.com/gpugems/gpugems3/part-iii-rendering/chapter-16-vegetation-procedural-animation-and-shading-crysis
