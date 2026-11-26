# Research gap: Translucent, refractive and volumetric creature materials

# Forge research: translucent, refractive and volumetric creature materials (ghost, slime and jelly, ice, crystal, glass golem, hologram, dissolve, iridescent and insect wings)

**I could not check sources live in this session.** The shared web-search budget for this turn was already used up, and dev.epicgames.com and docs.unity3d.com do not resolve from this sandbox. To check these claims, allow those two hosts in the session's network settings, or send a follow-up so the search budget resets.

Everything below comes from my own knowledge of the engines and the papers:
- Sources are listed at the end so a fact-check pass can verify them. None were re-fetched.
- Claims that depend on an exact property or console-variable name, or on a version, are marked **UNVERIFIED**.
- Repo facts were checked against `/home/user/Image-to-Game-asset/blender_scripts/forge_bpy/bake.py`. It bakes basecolor, normal, roughness, metallic (via EMIT) and AO, with a magenta sentinel and selected-to-active. The new bakes below follow that same pattern.

======================================================================
## 0. Core design decisions (read first)

1. **Translucency is a material class, not a texture.**
   - Tripo meshes come out opaque: one closed surface and PBR maps. I am not aware of Tripo writing a meaningful opacity channel (**UNVERIFIED**; check the GLB baseColor alpha on a sample).
   - So Forge must classify each part into a material class and generate the masks itself.
   - Classes: `OPAQUE`, `GHOST`, `GEL` (slime, jelly, jellyfish), `ICE`, `CRYSTAL`, `GLASS_SHELL` (a shell with an inner core), `HOLOGRAM`, `WING_THIN` (insect or fairy wing) and `EMISSIVE_ONLY`.
   - `DISSOLVE` is a state that any class can enter. It is a material feature, not a class.
2. **Prefer blend modes that do not depend on order.**
   - Additive and multiply blending are commutative, so they need no sorting.
   - Masked or dithered (stochastic) opacity writes depth, so it sorts correctly.
   - Use true alpha blending ("over") only where the look needs it, such as gel, glass or ice. Pair it with a depth prepass or a front/back split.
3. **Every class ships in three tiers:**
   - **AAA (UE5):** refraction and Substrate.
   - **Mobile-high (URP):** alpha blend with a depth prepass. No Opaque Texture unless the creature is a hero asset.
   - **Mobile-low (URP):** an opaque "fake" (fresnel rim, emissive, matcap). There is no transparency at all at this tier.

   The director approves the AAA and mobile-low looks. Mobile-high is interpolated between them.
4. **One packed "translucency mask" texture per translucent part, `T_<asset>_<part>_TM`, linear, not sRGB:**

   | Channel | Content |
   |---|---|
   | R | Thickness, 0 = thin, 1 = thick. Drives SSS and transmission. |
   | G | Interior depth or inner-geometry mask. Drives parallax and core visibility. |
   | B | Dissolve gradient (height or geodesic distance from a seed). |
   | A | Edge or curvature mask. Drives edge glow, crystal rims and dissolve rim bias. |

   On mobile, compress as ASTC 4x4 or 6x6. All four channels come from Blender bakes (section 10).

======================================================================
## 1. Detecting and classifying translucent parts automatically

- **(a) Why it matters.** A ghost or slime authored as opaque PBR reads wrong immediately. Transparency that is applied wrongly, such as a whole body including its eyes and teeth, causes sorting artefacts and overdraw.
- **(b) Topology.** Classification runs per part, after the "assemble parts" step. Any part that will be translucent must be its own mesh, or at least its own material slot. Opaque internals (eyes, teeth, a golem core, a jellyfish's gut) must be separate meshes.
- **(c) Rig.** None.
- **(d) Texture.** This step produces the class label and the preset parameters (tint, IOR, opacity, emissive colour).
- **(e) Automation in Blender:**
  1. **Label and prompt keywords.** Check the job YAML and prompt for: ghost, spectre, wraith, spirit, phantom, ethereal, slime, ooze, jelly, gelatinous, jellyfish, medusa, ice, frost, frozen, crystal, gem, quartz, glass, hologram, holographic, projection, dragonfly, fairy, insect wing, cicada. Each keyword maps to a class. This is procedural.
  2. **VLM pass on the concept image.** Ask "which named parts look see-through, glowing or glassy" and request JSON in the form part→class. If parts are already projected or segmented (for example with SAM masks), map each mask to its mesh part by majority vote over the projected faces. This needs an AI call.
  3. **Texture heuristics on the baked base colour and roughness** (numpy over the images, procedural; thresholds are UNVERIFIED and need tuning on samples):
     - Ice or crystal: low saturation, high value, cyan to blue hue, roughness < 0.25.
     - Gel: high-value saturated green, pink or purple, roughness < 0.3, very low normal-map variance.
     - Ghost: desaturated, value > 0.7, with a pale cyan or white bias.
     - These heuristics only propose a class. They never decide on their own.
  4. **Director confirmation.** Show one EEVEE turntable per proposed class with the preset applied, and let the director accept or swap it with a single click on a palette of presets. This is the "click once" step.
- **(f) Engine.** The class is written as a custom property on the mesh (`forge_mat_class`) and into the export manifest. The engine import script (UE Python or a Unity AssetPostprocessor) then creates a Material Instance of the matching master material.

======================================================================
## 2. Sorting translucent skinned meshes (shared infrastructure)

- **(a) Why it matters.** A skinned translucent mesh is a single draw call. With depth writes off, its triangles blend in index order, so the far arm draws over the near arm in some poses. Between objects, engines sort by bounds centre (or pivot) distance only, so a creature intersecting its own inner core flickers in order. Neither engine sorts per pixel by default.
- **(b) Topology tools Forge controls:**
  - **Nested shells:** inner parts first, outer last.
    - For nested layers (core, then flesh, then skin) or blobs around a centre, reorder faces so that inner faces have lower indices.
    - Operator: `bpy.ops.mesh.sort_elements(type='CURSOR_DISTANCE', elements={'FACE'})`, with the 3D cursor at the centroid or the core. Use `reverse=True` if needed, and check the result.
    - Graphics APIs blend primitives within one draw call in submission order, so this gives an order that is correct regardless of view for nested shells. It does not fix self-overlap of limbs.
  - **Inside the shell:** keep the shell a single closed manifold. Remove interpenetrating geometry (Tripo bakes eyes and mouth into the surface), because inside a translucent shell every internal face is visible.
  - **Opaque internals:** split them into separate meshes (eyes, core, bones).
  - **Poly budget.** A translucent shell shades both its front and back faces and every overlapping layer. Keep shells lean:
    - AAA: 15–40k tris for a hero creature shell.
    - Mobile: 2–6k tris.

    These are my recommendation, not engine limits (UNVERIFIED).
- **(c) Rig.** For the front/back split, both components must follow the same skeleton:
  - UE: `SetLeaderPoseComponent`, named MasterPoseComponent in older versions.
  - Unity: share the same bones array, or keep both as one SkinnedMeshRenderer with two submeshes.
- **(d) Material techniques, best first:**
  1. **Stochastic, dithered opacity (UE AAA default for ghosts and dissolves).**
     - Masked blend mode with Opacity Mask fed through `DitherTemporalAA`.
     - It writes depth, sorts perfectly, casts shadows, and works with Nanite, Lumen and skinned meshes. TSR or TAA resolve the noise.
     - It is not usable on mobile without TAA: the dither shows.
  2. **Depth prepass, then translucent ("front layer only").** Only the nearest surface is visible, like a ghost that is a uniformly faded solid. Self-sorting is solved.
     - **UE:** UE has no built-in multi-pass material. The standard trick:
       - Enable **Render CustomDepth Pass** on the component.
       - In the translucent material, set `opacity *= step(PixelDepth, SceneTexture:CustomDepth + bias)`, using the `CustomDepth` node or a SceneTexture lookup.
       - Bias about 1–2 units (UNVERIFIED value).
       - Translucent materials can read CustomDepth.
       - UE 5 materials also have **Output Depth and Velocity** under Translucency. It writes translucency depth and velocity for TSR and motion blur. Whether it can replace the custom-depth trick for self-occlusion is **UNVERIFIED**.
     - **URP:** use a two-pass hand-written shader. The first pass, tagged `LightMode=SRPDefaultUnlit`, uses `ZWrite On ColorMask 0`. The second pass, tagged `LightMode=UniversalForward`, is the transparent pass with `ZWrite Off ZTest LEqual`. URP runs both tags for one object in order.
       - Shader Graph cannot author two passes. Either use the HLSL template, or add a **Render Objects** renderer feature: a layer mask, the event "Before Rendering Transparents", and an override material that writes depth only.
       - In URP 14+ / Unity 2022+, Shader Graph transparent targets do expose a **Depth Write** setting (Auto, ForceEnabled, ForceDisabled). Single-pass ForceEnabled still depends on triangle order, so the prepass is preferred.
  3. **Back-then-front pass (gel, crystal, glass with visible inner walls).** Draw back faces (cull front), then front faces (cull back). This is correct for convex-ish volumes.
     - **URP:** a two-pass shader again (SRPDefaultUnlit with `Cull Front`, then UniversalForward with `Cull Back`).
     - **UE:** duplicate the shell in Blender, flip its normals, and export it as a second skinned component with a lower Translucency Sort Priority (for example −1 against 0) and the same leader pose. The UE component property is `TranslucencySortPriority`. UE 5.x also adds `TranslucencySortDistanceOffset` (UNVERIFIED name).
  4. **Order-independent transparency:**
     - **UE:** experimental sorted-pixels OIT. A project setting and `r.OIT.SortedPixels` (UNVERIFIED cvar name and platform requirement; it is believed to need D3D12 or SM6 raster-ordered views). Use it only for AAA PC and console, and only if tested.
     - **URP:** nothing built in. Weighted Blended OIT (McGuire & Bavoil 2013) is possible as a custom renderer feature, but it is not recommended for mobile (MRT bandwidth) or for refractive looks.
  5. **Additive.** Holograms and wispy ghosts need no sorting at all.
- **(e) Automation.** Forge writes the class and the chosen technique into the manifest:
  - Prepass and back/front components are produced in Blender (duplicate plus `bpy.ops.mesh.flip_normals()`, exported as a separate object bound to the same armature).
  - Face sorting is applied with `sort_elements`.
  - All of this is procedural.
- **(f) Engine notes:**
  - **UE:**
    - **Translucency Pass** (the material's Translucency Pass setting, formerly "Separate Translucency"): use Before DOF, or After DOF for soft glows.
    - **Lighting Mode:**
      - Surface ForwardShading: best quality, needed for Thin Translucent.
      - Surface TranslucencyVolume: cheaper.
      - Volumetric NonDirectional: cheapest, for ghosts.
    - Lumen lights translucency via **front layer translucency reflections** (5.1+, UNVERIFIED version).
  - **URP:**
    - Transparent objects sort back to front per renderer.
    - Materials can use `Sorting Priority` (render queue offset) to force a creature's shell after its internals.
    - Transparent objects are not in `_CameraOpaqueTexture` and do not write `_CameraDepthTexture`.

======================================================================
## 3. Ghost / spectre / wraith

- **(a) Why it matters.** Ghosts are seen in combat at mid range and need to stay readable: a silhouette rim plus a faint body. They often fade in and out (dissolve) and stack on top of each other, which costs overdraw.
- **(b) Topology.**
  - One closed shell, with no internal faces.
  - The tattered robe tail already has its own report: alpha cards, `tattered.md`.
  - Eyes and glow cores are separate opaque or additive meshes.
  - Budget: AAA 10–30k tris; mobile 1.5–4k tris (UNVERIFIED recommendation).
- **(c) Rig.**
  - The standard ARP biped or creature rig, plus an ARP **tail** limb for the wispy lower body (done in the ARP limbs report).
  - Hover bob: animation only. Optionally add a spring or jiggle chain (UE Control Rig spring or AnimDynamics; Unity spring bones such as Magica Cloth, third party).
  - Fade amount is driven by an animation curve:
    - UE: animation curves typed as **Material curves** drive the material parameter with the same name. Whether Blender FBX custom-property animation arrives as a UE curve is **UNVERIFIED**; ARP's exporter has options for custom props, which also need checking.
    - Unity: the Animator animates the material float property.
- **(d) Material:**
  - Unlit or lightly lit.
  - Opacity = fresnel (rim) × body opacity × noise scroll (panner on tiling noise).
  - Emissive tint, with a tint mask from the base colour luminance.
  - Optional depth fade (DepthFade node in UE; Scene Depth plus Depth Texture in URP) so the ghost softly intersects the floor.
  - UE AAA: Masked + DitherTemporalAA for a solid ghost, or Translucent + CustomDepth front-layer for a glassy ghost.
  - URP mobile-high: Additive (no sorting), or Alpha + prepass.
  - URP mobile-low: opaque with a strong fresnel emissive and dark body.
- **(e) Automation.**
  - Procedural: the classifier proposes GHOST. The baked base colour becomes the emissive tint, and luminance becomes the tint mask.
  - Rim width and opacity come from preset values, and the director picks between three opacity presets.
  - Thickness (R) is not needed. B (dissolve gradient) is baked as the height gradient.
- **(f) Engine.** In UE, translucent ghosts have no shadow unless you enable "Cast dynamic shadow as masked" (UNVERIFIED exact name) or use dither masked. In URP, an additive ghost casts no shadow; disable Cast Shadows on that renderer.

======================================================================
## 4. Slime / jelly / jellyfish (GEL)

- **(a) Why it matters.** The read depends on seeing inner walls and suspended things (bones, bubbles, swallowed items), plus wobble. These are often close-up hero blobs.
- **(b) Topology:**
  - A smooth, evenly spaced quad shell, because wobble needs even density.
  - Suspended internals are separate meshes (opaque), or are baked into the interior layer (section 9).
  - Jellyfish: bell shell (translucent) + oral arms and tentacles (alpha cards or thin tubes) + gonads (separate meshes, emissive).
  - Budget: AAA shell 8–25k tris; mobile 1–3k tris (UNVERIFIED).
- **(c) Rig.**
  - Blob: no skeleton, or a small rig (root plus 4–8 "jiggle" bones). The cheapest wobble is vertex-shader displacement driven by velocity:
    - UE: World Position Offset with a sine over object position, scaled by a velocity parameter.
    - Unity: a vertex offset in Shader Graph.
  - Jellyfish: bell pulse via a shape key (`Bell_Contract`, exported as a morph target / blendshape), or a ring of bones. Tentacles use ARP **Spline IK** or chain limbs (ARP limbs report) plus physics in engine.
- **(d) Material:**
  - Refraction, colour absorption by thickness (Beer–Lambert: `transmit = exp(-absorb_color * thickness)`, thickness from TM.R), SSS-like glow, specular with low roughness, fresnel.
  - **UE (Substrate):**
    - One **Slab BSDF**, with Diffuse Albedo kept low.
    - Use SSS MFP (mean free path) for the coloured scattering, F0 around 0.02, and roughness 0.05–0.2.
    - The blend mode is Translucent, with Refraction Method = Index of Refraction (IOR around 1.33–1.4) or Pixel Normal Offset.
    - Combine with the back-then-front components.
    - Substrate translucency has a coverage/transmittance model, and an exact node exists for converting transmittance colour to MFP (**UNVERIFIED node name**).
  - **UE (legacy):** Translucent, Surface ForwardShading, Refraction input; or Thin Translucent shading model for the bell.
  - **URP:**
    - Enable **Opaque Texture** in the URP asset.
    - Shader Graph Transparent: `Scene Color` node sampled at `ScreenPosition + normalTS.xy * strength * (1 - fresnel)` gives the refraction.
    - Tint by the exp absorption. Opaque Downsampling (2x Bilinear) saves bandwidth.
    - Mobile-low: opaque, with a fresnel brightened edge and a baked "fake interior" in the albedo.
- **(e) Automation.** Procedural:
  - TM.R thickness bake.
  - TM.G inner-object projection (section 9).
  - Absorb colour = 1 − normalised base colour.
  - IOR from a preset.
  - Bell pulse shape key, generated by scaling the bell rim ring with a radial falloff in bmesh and storing it as a shape key.
  - Director: approves a turntable with a wobble loop.
- **(f) Engine.** In UE, WPO on skinned meshes is fine. It needs "Evaluate World Position Offset" with Nanite, but translucent meshes are not Nanite. In URP, refraction cannot see other transparent objects (they are not in the Opaque Texture), so slime in front of a ghost won't refract the ghost. This is an accepted limitation.

======================================================================
## 5. Ice / crystal

- **(a) Why it matters.** Facets catch light, edges glow, and inner cracks give depth. Crystal growths on otherwise opaque creatures (crystal back spikes) are very common in mythical assets.
- **(b) Topology:**
  - **Faceted hard surface, not quad-remeshed.** Quad Remesher tends to round off sharp facets (UNVERIFIED for QR; it is generally true of curvature-adaptive remeshers). For CRYSTAL parts, Forge should route to planar decimation instead: `Decimate` modifier `decimate_type='DISSOLVE'` with `angle_limit` around 5°, then triangulate.
  - Mark sharp edges by angle and use split normals.
  - Crystal clusters on an opaque body: separate meshes, skinned rigidly (100% weight to one bone, normally the parent bone). A mechanical-style rigid parent, as in the mech report.
  - Budget: crystals are cheap, 50–500 tris per shard.
- **(c) Rig.** Rigid. One bone per crystal cluster, or parented to the nearest deform bone. Use no deformation, or facets shear.
- **(d) Material:**
  - Ice: Slab with roughness 0.1–0.3, refraction IOR 1.31, inner cracks via a parallax interior layer (section 9), frost in the roughness and normal maps, slight SSS (blue MFP).
  - Crystal: IOR 1.5–2.4, a fresnel-driven edge glow from TM.A, and an emissive core that fades with view depth.
  - Faceted refraction distortion uses the flat facet normals.
  - Cheap dispersion: sample Scene Color three times with slightly different offsets for R, G and B. AAA only.
  - URP mobile: a cubemap reflection probe plus fresnel plus a parallax inner layer, with **no** Opaque Texture. This often looks better than real refraction on mobile.
  - Opaque crystal fallback: Lit with metallic 0, smoothness 0.95, and emissive from TM.A.
- **(e) Automation:**
  - Procedural: edge mask via Geometry Nodes `Edge Angle`, captured as a point attribute and baked to TM.A through an emission bake. Alternatively, Cycles `Geometry > Pointiness` baked through emission (per-vertex resolution on the dense mesh, which is good enough).
  - Cracks: an AI-generated tileable crack texture, or a procedural Voronoi edge baked to G.
- **(f) Engine.** In UE, crystal parts on an opaque creature can stay **opaque** with a fake "inner" BumpOffset layer. That is often the best performance/look trade-off. Reserve true Translucent for hero ice golems.

======================================================================
## 6. Glass golem / shell with visible inner core (GLASS_SHELL)

- **(a) Why it matters.** The visible core (heart, skeleton, magma, clockwork) is the asset's identity, and it must stay visible in every pose.
- **(b) Topology:**
  - Two or more meshes:
    - The outer shell (translucent, thin-ish, closed).
    - The inner core (opaque or emissive, separate, possibly from a separate AI generation of "the core").
    - An optional back-face shell copy.
  - Tripo will fuse these into one surface, so Forge needs either:
    - an AI-generated core part from a second generation pass, prompted as "glowing crystal heart, isolated", or
    - a procedural core: shrink the shell with a negative `Solidify`/offset, keep the torso region only, and remesh.
- **(c) Rig.** The core is skinned to the same armature (it can share the torso bones), or rigidly parented to `spine_02`. Note: ARP spine bone names are `spine_01.x` / `spine_02.x` (UNVERIFIED for 3.79.17). Core pulse: a shape key or a scale bone.
- **(d) Material:**
  - Shell: thin translucent with refraction and low absorption.
  - Core: emissive, so it also reads in Lumen and bloom.
  - Ordering: the core draws first (opaque), then the shell (translucent), so the opaque core is naturally behind the shell.
  - Fake absorption uses TM.R thickness.
  - TM.G = inner-geometry mask: "is there core behind this texel?" Use it to boost transmission or brightness where the core shows through. This is also the mobile-low fallback: the core appearance is projected into the shell albedo.
- **(e) Automation.** Procedural, given the core mesh: the G mask bake (section 10), and the back-face copy. The director clicks once to approve the core position and size.
- **(f) Engine:**
  - UE: the shell and core are two components, or two material sections of one skeletal mesh. Translucent sections sort after opaque automatically.
  - URP: the same. The core is Opaque, so it lands in the Opaque Texture and is correctly refracted by the shell.

======================================================================
## 7. Hologram / projection body

- **(a) Why it matters.** Sci-fi creatures and summons. These must read as "not physical".
- **(b) Topology.** Any. Interior faces matter less, because the blend is additive. Budget as for an opaque mesh.
- **(c) Rig.** Normal. Optional glitch: vertex offset bands in the shader, so no bones.
- **(d) Material:**
  - **Additive, unlit.** This is order-independent, so there are no sorting problems.
  - Emissive = tint × (fresnel + scanlines + flicker).
  - Scanlines in world space, Z or screen space: `frac(worldZ * density + time)`.
  - Optional depth fade at intersections.
  - On mobile it is cheap, except for overdraw.
- **(e) Automation.** Procedural. The base colour is converted to luminance and used as the emissive mask. The director picks the tint.
- **(f) Engine.** Additive ignores scene lighting and fog unless handled. In UE, check "Apply Fogging" (UNVERIFIED property name in 5.x). No shadows.

======================================================================
## 8. Dissolve and edge glow (state on any class)

- **(a) Why it matters.** Death, spawn, teleport and summon all use it constantly. The edge glow sells it.
- **(b) Topology.** No requirement. Even triangle density only helps if the dissolve uses vertex-colour gradients. Use texture gradients (TM.B) instead, so topology does not matter.
- **(c) Rig.**
  - A material scalar `DissolveAmount` 0..1 is driven from gameplay or an animation curve.
  - UE: Custom Primitive Data (avoids creating a Material Instance Dynamic per actor), or a MID scalar, or an animation Material curve.
  - Unity: `Renderer.SetPropertyBlock` breaks SRP Batcher compatibility for that renderer. For a one-off death effect this is acceptable; alternatively, swap to a per-instance material while dissolving.
- **(d) Material:**
  - `mask = TM.B (directional gradient) * k + tiling_noise * (1-k)`.
  - `clip(mask - DissolveAmount)`.
  - `edge = 1 - saturate((mask - DissolveAmount) / EdgeWidth)`.
  - `emissive += edge * EdgeColor * EdgeIntensity` (HDR, so it blooms).
  - UE: Masked blend mode, so it keeps depth, shadows and Nanite masked support.
  - URP: Lit or Unlit with Alpha Clipping enabled.
  - **Mobile: alpha test (`clip`/discard) disables early-Z / hidden-surface removal** on tile-based GPUs (Arm Mali and Apple/PowerVR guidance). Use the dissolve variant only while dissolving, and switch back to the opaque material otherwise. Forge exports both `M_x` and `M_x_Dissolve`.
- **(e) Automation:**
  - B channel: either normalised object-space height (head-to-toe or toe-to-head) or a geodesic distance from a seed vertex (for "burns from the wound"). Compute the geodesic distance in bmesh with a Dijkstra over edge lengths on the low-poly mesh, write it as a colour attribute, and bake it via emission to TM.B. Procedural.
  - The noise texture is shared across all assets: one tileable Perlin-Worley in the engine library.
  - The director clicks once to choose the seed point (a head, the heart, or a mouse click on the mesh), or accepts the "top-down" default.
- **(f) Engine.** In UE, Nanite skeletal meshes (5.5+; UNVERIFIED for masked) need checking. Fallback: disable Nanite on dissolving creatures.

======================================================================
## 9. Fake interior volume (parallax / interior mapping / inner layer)

- **(a) Why it matters.** Slime with bones inside, ice with trapped objects, crystals with inner fractures, a ghost with a visible skeleton. Real volumetrics on skinned meshes are unaffordable, so the interior is faked.
- **(b) Topology.** The shell needs clean, non-overlapping UVs (UVPackmaster) and valid tangents, because parallax needs the tangent basis. Avoid UV seams over the "window" areas.
- **(c) Rig.** None. The interior is a texture, so it deforms with the skin for free.
- **(d) Material techniques, cheapest first:**
  1. **Single-layer parallax inner texture.**
     - `uv_inner = uv + ViewDirTS.xy / ViewDirTS.z * depth * TM.G`. Sample an "interior" colour texture at `uv_inner` and blend it under the surface by transmission. One extra sample, so it works on mobile.
     - UE: `BumpOffset` node, or a custom ViewDir maths node.
     - URP Shader Graph: `Parallax Mapping` node.
  2. **Parallax Occlusion Mapping** (UE `ParallaxOcclusionMapping` material function; URP Shader Graph `Parallax Occlusion Mapping` node). For cracks and frost depth. AAA, or mobile-high at a low step count.
  3. **Interior mapping** (van Dongen 2008): ray-box per texel. It suits rooms and boxy crystals, and suits creatures poorly. Skip it except for crystal golems.
  4. **Raymarched volume** (Custom node). AAA only, cinematics. UE Heterogeneous Volumes do not apply to skinned meshes (UNVERIFIED).
- **(e) Automation: the inner-geometry projection bake (Blender).**
  - Bake the **colour of the inner objects as seen straight inward from the shell**: selected-to-active, with the inner objects (bones, bubbles, core) selected as the source and the shell active.
  - `cage_extrusion` is small. `max_ray_distance` is about the shell's inner depth.
  - Rays start from the slightly extruded cage and travel inward, so they hit the inner object. Edge-case behaviour (back faces, nearest hit in both directions) is **UNVERIFIED** and needs a test fixture.
  - Bake DIFFUSE colour into `T_<part>_Interior`, and the hit distance into TM.G using the BVH method in section 10.
  - The interior objects can be:
    - an AI-generated "skeleton inside slime" part,
    - a procedurally generated bubble field (Geometry Nodes: `Distribute Points in Volume` → `Instance on Points` icospheres → `Realize Instances`), or
    - the creature's own retopologised core.
- **(f) Engine.** UE and URP both handle tangent-space parallax on skinned meshes, as long as tangents are exported. Use FBX export with tangent space on, and import using the file's normals and tangents in both engines (UE "Import Normals and Tangents", Unity "Tangents: Import").

======================================================================
## 10. Blender bakes feeding these shaders (implementation for `bake.py`)

`bake.py` already does selected-to-active with a sentinel and has an EMIT bake path. Add an `"attr"` map type that bakes a colour attribute through EMIT. All of the masks below are computed as per-vertex attributes on the **dense Tripo mesh**: millions of vertices give texel-level detail. Each is then baked EMIT, selected-to-active, into the low-poly UVs.

1. **Thickness → TM.R.**
   - Method A (fast, procedural): `mathutils.bvhtree.BVHTree.FromObject(high, depsgraph)`. For each vertex, cast a ray along −normal from `co - n*eps` and store `d` (with the miss = `None` check noted in `tattered.md`). Average 3–5 jittered cone rays.
   - Normalise by the 95th percentile and store as a colour attribute `forge_thickness`.
   - Use numpy plus a loop over `ray_cast`. Budget: about 2–5 M rays, roughly a minute on CPU (UNVERIFIED timing).
   - Method B: invert normals and bake Cycles AO with Only Local. Thickness ≈ AO of the inverted mesh. Uses the GPU, but it is noisier and needs a duplicate mesh.
   - Feeds: UE Substrate Slab thickness and SSS MFP scale, legacy Subsurface colour opacity, URP absorption, EEVEE preview.
2. **Inner-geometry mask and interior depth → TM.G.** The same BVH, built on the inner objects only. The ray goes inward from the shell. G = `1 - saturate(dist / maxDepth)` on a hit, and 0 on a miss. Plus the interior colour DIFFUSE bake from section 9.
3. **Dissolve gradient → TM.B.** Object-space Z normalised, or the bmesh geodesic distance from the seed. Bake it on the low-poly mesh directly (an EMIT of its own attribute, no selected-to-active).
4. **Edge, curvature and rim → TM.A.** Geometry Nodes `Edge Angle` / `Edge Neighbors` → `Capture Attribute` (point domain), or Cycles `Geometry.Pointiness` (Cycles only). Bake via emission, then clamp and level.
5. **Thin-film thickness map** (wings, optional). A noise-modulated constant, used in the Blender preview and in Substrate.
6. **Pack** R, G, B and A in numpy into one image and save it as Non-Color PNG.

**Director preview in Blender, EEVEE Next (4.2+, so 5.3 should have it):**
- Material property `surface_render_method` = `'BLENDED'` or `'DITHERED'`.
- Raytraced refraction on the material and in the scene (`use_raytrace_refraction` property; UNVERIFIED exact names in 5.3).
- The Material Output node has a **Thickness** socket (4.2+). Wire TM.R into it so the preview matches the engine.
- Principled BSDF `Transmission Weight`, `IOR`, `Subsurface Weight/Radius`, and **Thin Film Thickness / IOR** (4.2+) for iridescence previews.

======================================================================
## 11. Iridescent and insect wings (WING_THIN)

- **(a) Why it matters.** Dragonfly, fairy and moth wings are large, thin, see-through and backlit. They flap fast, so they are seen mostly in motion and in close-ups on idle.
- **(b) Topology:**
  - A single-sided plane, or a thin two-sided card, separate per wing.
  - Venation goes in texture, not geometry.
  - Leading-edge vein loops are needed for bending.
  - Tripo gives a thick slab: replace it by flattening to a card (as in `tattered.md`'s card rebuild), keeping the outline via alpha.
  - Budget: AAA 200–1,000 tris per wing; mobile 20–100 tris per wing.
- **(c) Rig.**
  - One root bone per wing, plus 1–3 bend bones. Add them as an ARP custom limb or a bone chain. The wing limb itself was covered in the ARP limbs report.
  - The flap is animation. A vertex-shader flutter is optional.
  - Insects with four wings: separate bones per wing.
- **(d) Material:**
  - Masked opacity for vein outlines plus translucent membrane, or fully Translucent with opacity about 0.2–0.5.
  - UE legacy: **Thin Translucent** shading model (requires Surface ForwardShading lighting, uses a Thin Translucent Material output with Transmittance colour). Or Two Sided Foliage on Masked for opaque-ish membranes.
  - UE Substrate: Slab with **thin-film** (Substrate supports thin-film iridescence; UNVERIFIED pin names "Thin Film Thickness"/"Thin Film IOR" or similar).
  - Cheap iridescence for URP and fallback: `ramp(frac(NdotV * k + thicknessMap))` sampled from a rainbow gradient texture.
  - Back-lighting: URP has no built-in transmission, so add `saturate(dot(-L, V))^p * transmissionColor` in a Shader Graph custom lighting function (main light via a Custom Function `GetMainLight`).
  - Sorting: wings overlap each other, so give each wing its own section or component. Use the Masked/dither path in UE AAA, and alpha blend with a per-wing sort priority on mobile.
- **(e) Automation:**
  - Procedural: detect wings in the appendages stage (`appendages.py` already finds appendages; add a flatness test where the PCA third eigenvalue is much smaller than the second, plus the label "wing"), then card-rebuild and bake.
  - Vein texture: an AI-generated texture from the concept image crop, or the baked base colour thresholded for veins.
  - The director clicks once to approve the opacity and iridescence preset.
- **(f) Engine.** Wings flapping in front of the body suffer translucency sorting against the body: the body is opaque, so this is fine. They also suffer sorting against other translucent effects. In UE, put wings in the After DOF translucency pass only if they are soft. Mobile: two wings means two translucent draws, which is acceptable.

======================================================================
## 12. Mobile overdraw and transparency limits

- Tile-based GPUs (Mali, Adreno, Apple) make blending itself cheap in on-chip memory, but **fill rate and overdraw** dominate. **Alpha test/discard defeats early-Z/HSR**, and **framebuffer fetch / Opaque Texture copies** cost bandwidth (Arm Mali best-practices guide; Apple GPU docs).
- Forge's rules for mobile (these are recommendations, UNVERIFIED as hard numbers):
  - At most 1–2 overlapping translucent layers per pixel for creature bodies.
  - No full-screen translucent creature. If a translucent creature can fill the screen, use mobile-low (opaque fake).
  - Opaque Texture is only on if a hero asset needs refraction. Use Opaque Downsampling 2x or 4x.
  - Prefer additive over alpha (no prepass needed). Prefer opaque + fresnel fakes over either.
  - Swap the dissolve material in only while dissolving.
  - Check with the Unity Frame Debugger, Rendering Debugger overdraw view, and Arm or Snapdragon profilers.
- UE AAA: check Shader Complexity and Quad Overdraw view modes, and prefer dithered Masked over Translucent for large bodies.

======================================================================
## 13. Engine import automation summary

- **UE Python** (`unreal.AssetToolsHelpers`, `MaterialInstanceConstantFactoryNew`, `unreal.MaterialEditingLibrary.set_material_instance_*_parameter_value`):
  - Master materials `M_Forge_Ghost`, `M_Forge_Gel`, `M_Forge_Ice`, `M_Forge_Crystal`, `M_Forge_GlassShell`, `M_Forge_Hologram`, `M_Forge_WingThin`, each with a static switch `bDissolve`.
  - Set component `translucency_sort_priority` and `render_custom_depth` on the Blueprint's skeletal mesh components where relevant.
- **Unity editor script:**
  - Shader Graphs `SG_Forge_*` plus one HLSL two-pass shader `Forge/TransparentPrepass`. The URP asset per tier toggles Opaque Texture.
  - Use `BaseShaderGUI.SetupMaterialBlendMode` for URP Lit-derived materials (see `tattered.md`).
  - Set `material.renderQueue` offsets for shell versus internals.

======================================================================
## Sources (not re-fetched this session; verify)

- [UE: Using transparency in materials / Blend modes / Translucency Lighting Modes](https://dev.epicgames.com/documentation/en-us/unreal-engine/using-transparency-in-unreal-engine-materials)
- [UE: Refraction (IOR, Pixel Normal Offset, 2D Offset)](https://dev.epicgames.com/documentation/en-us/unreal-engine/using-refraction-in-unreal-engine)
- [UE: Shading models (Thin Translucent, Two Sided Foliage)](https://dev.epicgames.com/documentation/en-us/unreal-engine/shading-models-in-unreal-engine)
- [UE: Substrate overview (Slab BSDF, thin film, translucency)](https://dev.epicgames.com/documentation/en-us/unreal-engine/overview-of-substrate-materials-in-unreal-engine)
- [UE: Custom Depth / Stencil](https://dev.epicgames.com/documentation/en-us/unreal-engine/post-process-materials-in-unreal-engine)
- [UE: Parallax Occlusion Mapping / BumpOffset material functions](https://dev.epicgames.com/documentation/en-us/unreal-engine/parallax-occlusion-mapping-in-unreal-engine)
- [Unity URP Asset (Opaque Texture, Opaque Downsampling, Depth Texture)](https://docs.unity3d.com/Packages/com.unity.render-pipelines.universal@17.0/manual/universalrp-asset.html)
- [Unity Shader Graph Scene Color node](https://docs.unity3d.com/Packages/com.unity.shadergraph@17.0/manual/Scene-Color-Node.html)
- [Unity URP Render Objects renderer feature](https://docs.unity3d.com/Packages/com.unity.render-pipelines.universal@17.0/manual/renderer-features/renderer-feature-render-objects.html)
- [Unity Shader Graph Parallax Mapping / Parallax Occlusion Mapping nodes](https://docs.unity3d.com/Packages/com.unity.shadergraph@17.0/manual/Parallax-Occlusion-Mapping-Node.html)
- [McGuire & Bavoil 2013, Weighted Blended Order-Independent Transparency, JCGT 2(2)](https://jcgt.org/published/0002/02/09/)
- [van Dongen 2008, Interior Mapping (CGI 2008)](https://www.proun-game.com/Oogst3D/CODING/InteriorMapping/InteriorMapping.pdf)
- [Arm Mali GPU Best Practices Guide (overdraw, discard, early-ZS)](https://developer.arm.com/documentation/101897/latest/)
- [Blender 4.2 release notes: EEVEE Next (render method, thickness output), Principled Thin Film](https://developer.blender.org/docs/release_notes/4.2/)
- [Blender manual: Baking (selected to active, cage, max ray distance)](https://docs.blender.org/manual/en/latest/render/cycles/baking.html)
- [Blender Python API: mathutils.bvhtree, bpy.ops.mesh.sort_elements](https://docs.blender.org/api/current/mathutils.bvhtree.html)
- Repo: `/home/user/Image-to-Game-asset/blender_scripts/forge_bpy/bake.py` (existing bake types: basecolor, normal, roughness, metallic via EMIT, AO); `/home/user/Image-to-Game-asset/docs/research/tattered.md` (BVH miss handling, URP blend-mode setup).

Highest-priority items for a fact-check pass:
- Substrate pin and node names (thin film, the transmittance-to-MFP conversion).
- Whether UE "Output Depth and Velocity" fixes self-sorting.
- The `r.OIT.SortedPixels` requirements.
- EEVEE Next Python property names in 5.3.
- Whether UE imports Blender FBX custom-property animation as Material curves.
- The selected-to-active inward-hit behaviour for the interior bake.
