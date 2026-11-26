# Research gap: Crowds, VAT, impostors and skinned performance at scale

# Forge gap report: crowds, VAT, impostors and skinned performance at scale

**How this was researched.** Six web searches, then the shared search budget ran out. Direct fetches of dev.epicgames.com and docs.unity3d.com were blocked by the session network allowlist, so Epic and Unity pages are cited from search-result summaries and were not read in full. The OpenVAT GitHub README was read in full. Claims marked UNVERIFIED come from prior knowledge or inference. Check them in UE 5.7/5.8 and Unity 6.x before you hard-code them.

---

## 0. Executive summary: what Forge can produce automatically per asset

| Deliverable | Auto in Blender? | Director's part | Engine |
|---|---|---|---|
| Skinned LOD chain (LOD0–3) with a bone-removal plan and weights folded into parents | Yes (Decimate, then a vertex-group merge script) | Approve one LOD contact sheet | UE + Unity |
| Mech "rigid split": one mesh per bone plus a socket list, instead of a skinned mesh | Yes, if every vertex has a single 1.0 weight (detectable) | None | UE (Nanite static parts), Unity (no skinning cost) |
| Vertex-position VAT (EXR plus a mesh whose UV2 holds the vertex index) per clip | Yes (depsgraph loop, or the OpenVAT extension) | Watch an instanced playback clip | UE + Unity |
| Bone-animation texture ("BAT": matrices per frame, bone indices and weights in UVs) | Yes (numpy script) | None beyond playback check | Unity URP crowds; UE AnimToTexture-style |
| Octahedral impostor atlas (BaseColor+alpha, Normal+depth) for props, plus static-pose characters | Yes (scripted ortho cameras + Eevee + numpy atlas) | Approve turntable | Unity (custom shader); UE: use the built-in Impostor Baker or Forge's atlas |
| Platform validation report: bones per section, influences, morph count, vertex count vs VAT width, tris per LOD | Yes (pure bpy checks) | Read pass/fail | Both |
| Engine import-config scripts (Unity AssetPostprocessor; UE Python import + LOD/bone settings) | Yes (text generation) | None | Both |
| Nanite skeletal flag | Only as metadata; experimental | Opt-in per hero asset | UE AAA only |
| Animation Budget Allocator / URO / Animation Sharing setup | Project-level; Forge emits a per-asset significance profile and docs | None | UE |

---

## 1. Vertex animation textures (VAT): vertex-position and bone-matrix types

**(a) Why it matters.** Skinned meshes in Unity are not GPU-instanced, and in UE each one costs a component plus an animation tick. VAT turns an animated character into a static mesh whose vertex shader reads its pose from a texture. Hundreds or thousands of instances can then be drawn in a few instanced draw calls with no CPU animation. The costs: no runtime IK, no physics, and blending between clips is limited.

**(b) Topology.**
- **Vertex-position VAT.** Texture width = vertex count and height = frame count, or wrapped rows. Width limits apply: one UE forum report puts the UE5 vertex-animation material node at 8192, and the VFX Export Studio docs limit VAT to 16,384 vertices per object. That makes it suitable for crowd LODs (about 1–8k verts) but not LOD0 heroes.
- **Bone-matrix texture (BAT).** Texture size ≈ (bones × 3 or 4 texels) × frames, which is independent of vertex count. This is the better choice for creatures and mechs.
- **Seams.** Engines split vertices at UV seams and hard edges, so the Blender vertex index does not equal the engine vertex index. Write the lookup coordinate into a dedicated UV channel: u = (i + 0.5) / W per Blender vertex. Split copies inherit the same UV2, so the lookup survives the split. OpenVAT does exactly this and exports "a mesh with a VAT-compatible UV set".
- **Topology must stay constant across frames.** No topology-changing modifiers after the Armature modifier.

**(c) Rig.** The source rig is the Auto-Rig Pro (ARP) deform skeleton plus clips. BAT stores the skinning matrix per frame for each deform bone: `pose_bone.matrix @ bone.matrix_local.inverted()` (in object space), with up to 4 bone indices and weights per vertex in UV2/UV3 (the GPU ECS Animation Baker uses uv1–uv3 in the same way). Convert Blender Z-up metres to Unity (Y-up, left-handed, metres) or UE (Z-up, left-handed, cm) before writing.

**(d) Texture.**
- Format: EXR half or float, linear, no mips, point filtering, no compression.
- OpenVAT outputs PNG 8/16-bit or EXR16 (half, ZIP) or EXR32, plus a `-remap_info.json` with min/max per channel and clip ranges. Normals can be omitted, packed as extra rows, or written to a separate texture.
- The OpenVAT README says imported VATs should use RGB16 compression. VFX Export Studio docs show lower-precision compression causing visible position error.
- Tangent-space normal maps are unreliable on VAT meshes. The OpenVAT README recommends object-space normal maps, which need shader changes.

**(e) Automation in Blender.**
- **Option A: use OpenVAT.** Extension on extensions.blender.org, Blender 4.2+ including 5.x, version 1.1.2, core licence GPL-3.0, engine tools MIT. The README documents no headless or CLI mode. Driving its operators from bpy is UNVERIFIED, so test `bpy.ops` calls before relying on it.
- **Option B (recommended for control): Forge's own script.**
  1. For each frame: `scene.frame_set(f)`, `obj.evaluated_get(depsgraph).to_mesh()`, then `foreach_get('co')` into a numpy array.
  2. Subtract the rest pose to get offsets, normalise against the bounds, and store the bounds in JSON.
  3. Write the image with `bpy.data.images.new(..., float_buffer=True)` and save it as OPEN_EXR, colour depth 16.
  4. BAT variant: write `pose_bone` matrices per frame into an N×3 RGBA float texture.
  5. Clips come from the ARP pose-test library and are baked back-to-back with a clip table in JSON.
- Fully procedural. The director only watches a viewport playback of about 50 instances.

**(f) Engine notes.**
- **Unity URP.**
  - Shader Graph with a Custom Function that calls `SAMPLE_TEXTURE2D_LOD` in the vertex stage.
  - Draw with `Graphics.RenderMeshInstanced` or `RenderMeshIndirect`, with per-instance time offset and clip index in an instance buffer.
  - Alternatively, use GameObjects with MeshRenderers through the URP GPU Resident Drawer. It uses BatchRendererGroup, needs the SRP Batcher on, and needs shaders that support DOTS Instancing. It requires MeshRenderer, so skinned meshes fall back to non-instanced drawing, which is exactly why VAT is needed.
  - OpenVAT ships a Unity package with a Tools > OpenVAT menu for basic and PBR materials. Only the Unity importer reads the clip metadata.
  - Third-party alternatives: GPU Instancer Pro Crowd Animations (compute-skinned from pre-baked bone data) and GPU ECS Animation Baker.
- **UE5.**
  - Static mesh with World Position Offset, drawn through Instanced or Hierarchical Instanced Static Mesh components with per-instance custom data floats for clip and time.
  - OpenVAT's UE5 tools require forward rendering according to its README.
  - UE also ships an **AnimToTexture** plugin (Vertex and Bone modes, experimental; City Sample used VAT-style crowds with Mass) — UNVERIFIED in this session.
  - WPO on Nanite meshes works but is costly — UNVERIFIED.

---

## 2. Impostors and octahedral billboards (distant characters and props)

**(a) Why it matters.** At far distance a 2-triangle card that samples a pre-rendered view atlas replaces thousands of triangles and the skinning cost. Typical uses: crowds on stadium stands or battlefields, and forests of props.

**(b) Topology.** A single quad (billboard) or a low "impostor proxy" of 4–12 triangles. Characters render as a static idle pose. Animated impostors (frames × views) are possible but texture-heavy; SideFX Labs tooling supports "animated impostors".

**(c) Rig.** None. The impostor is the last LOD, swapped in by LODGroup or by HLOD/ISM distance.

**(d) Texture.**
- An atlas of N×N views on an octahedral or hemi-octahedral layout.
- Typical layout: 8×8 to 16×16 frames in 2k–4k. This is an industry norm, UNVERIFIED.
- Maps: BaseColor+opacity, plus world- or object-space Normal with depth in alpha (for parallax and depth-offset blending). Optionally ORM.
- Use a tint mask channel so crowds can vary colour.
- Shader: octahedral direction-to-frame mapping with a 3-frame blend.

**(e) Automation in Blender.**
- Fully procedural:
  1. Compute hemi-octahedral directions.
  2. For each direction, place an orthographic camera fitted to the bounding sphere.
  3. Render with Eevee using AOVs or passes (DiffCol, Normal, Z) on a transparent film.
  4. Pack the frames with numpy into an atlas.
  5. Emit the quad mesh and a JSON of frame count, layout and bounds radius.
- Director approval: a turntable GIF comparing the impostor with the real mesh at distance.

**(f) Engine notes.**
- **UE.** The built-in Impostor Baker plugin is found under Edit > Plugins > BUILT-IN > Mesh. Its types include full sphere, upper hemisphere and traditional billboards. From 5.5 it has a batch renderer that renders impostors for multiple meshes with a preset. The API index lists the module under an Experimental path. A forum bug reports impostors invisible when the camera aligns with -Z.
  - Recommendation for UE: let the engine bake from Forge's LOD0 via a UE Python batch call (exact API UNVERIFIED). Use Forge's own atlas only for parity with Unity.
- **Unity URP.** No built-in impostor system. Options: the Unity Industry Toolkit "BakeImpostor" action (Pixyz-based), Amplify Impostors from the Asset Store (UNVERIFIED for Unity 6 URP), or a Forge-supplied Shader Graph that reads Forge's atlas.

---

## 3. UE5 Nanite skeletal (skinned) meshes

**(a) Why it matters.**
- Per the official docs: one draw call per mesh, shadows through Virtual Shadow Maps, and no geometry LODs. Nanite skeletal meshes use animation LODs (bone reduction) instead.

**(b) Topology implications.**
- Forge could ship a much denser LOD0 for AAA heroes and mechs.

**(c) Limits (5.5 to 5.8, community reports, so partly UNVERIFIED).**
- Experimental in 5.5.
- Unsupported in 5.5: morph targets, Chaos cloth, grooms, translucency. Only opaque and masked materials.
- 5.8 has experimental Nanite translucency.
- Bone-dropping LODs were reportedly broken in 5.7 and working in 5.8.
- UE-228385: Nanite views are missing in the Skeletal Mesh Editor.
- No 5.6 or 5.7 release note found that declares the feature production-ready.

**(d)/(e) Forge policy.**
- **Default:** classic skeletal LODs.
- **Optional `nanite_skeletal=true` metadata:** only for opaque, morph-free AAA assets, which suits mechs and armoured creatures.
- **Better mech route:** rigid parts as Nanite static meshes attached to sockets. That is production-proven and needs no experimental skinning.
- **Never on mobile.**

---

## 4. UE Animation Budget Allocator, URO and related systems

**Animation Budget Allocator plugin** (per Epic docs):
- Set the character's mesh Component Class to `SkeletalMeshComponentBudgeted`.
- The budget is fixed game-thread time, `a.Budget.BudgetMs`, set per platform or scalability level (for example in DefaultScalability.ini).
- `a.Budget.Debug.Enabled` shows a debug overlay.
- API: `SetComponentSignificance`, `OnCalculateSignificance` (used when `bAutoCalculateSignificance`), `OnReduceWork`, `bAutoRegisterWithBudgetAllocator`.
- It throttles tick rate and interpolates the skipped frames.

**URO (Update Rate Optimizations)** — UNVERIFIED in this session, from prior knowledge:
- `bEnableUpdateRateOptimizations` on SkinnedMeshComponent, `AnimUpdateRateParams`, and debug via `bDisplayDebugUpdateRateOptimizations`.
- Use it together with `VisibilityBasedAnimTickOption` (OnlyTickPoseWhenRendered) and Leader Pose / Animation Sharing plugin for crowds.

**What Forge can emit.** These are project-level systems. Forge can ship per asset:
- A significance class (hero, NPC or crowd).
- Recommended LOD screen sizes.
- A per-LOD bone list for animation LODs.
- A small UE Python import script.

---

## 5. Unity GPU skinning and instancing limits

**Settings and behaviour:**
- **Quality > Skin Weights** (`QualitySettings.skinWeights`): One, Two, Four or Auto in 6.3; older versions had Unlimited.
- More than 4 influences needs compute-shader GPU skinning. Devices without compute fall back to CPU (per 2019-era docs; current wording not confirmed).
- Per-renderer override: `SkinnedMeshRenderer.quality`. Import-time weight count: `ModelImporter.maxBonesPerVertex`.
- SkinnedMeshRenderers are not GPU-instanced and are not handled by the GPU Resident Drawer (inferred from its MeshRenderer requirement).
- So for crowds, use VAT/BAT (section 1) or a compute-skinning asset.

**Mobile checklist (Forge Unity AssetPostprocessor):**
- `maxBonesPerVertex=4` (2 for crowd LODs).
- `optimizeGameObjects=true`, with exposed transforms only for sockets.
- Blend shapes off on LOD1+.
- Animator culling: Cull Update Transforms.
- `updateWhenOffscreen=false`.

**The "Bones count exceeds" warning.** This specific Unity message could not be researched (search budget ran out) — UNVERIFIED. The likely cause is constant-buffer-based skinning on old GLES or WebGL paths with high per-mesh bone counts. Mitigation is the same as the UE mobile 75-bone rule: split by material, or remove bones on mobile LODs.

---

## 6. Skinned LOD authoring for creatures and mechs

**Triangle ratios.** LOD0 100%, LOD1 about 50%, LOD2 about 25%, LOD3 about 10%, then an impostor. These are industry heuristics, UNVERIFIED as a standard.

**Bone removal per LOD:**
- **LOD1:** facial bones and morphs, finger and toe sub-joints, tongue.
- **LOD2:**
  - Tail chain halved (for example 8 → 4); see the bone-removal step below for which bones to drop.
  - Ears collapsed to one bone, wing secondaries removed, twist bones removed.
- **LOD3:** spine to 2 bones, no tail, no neck twist.

**Mechs:**
- Detect rigid binding automatically (every vertex has max weight 1.0, one bone per loose part).
- Export as per-bone rigid meshes, or skinning with a single influence.
- LODs delete greebles under a size threshold, merge parts per material, and add an impostor at the end.

**Blender automation:**
1. Duplicate the mesh.
2. Apply a Decimate (collapse) modifier, which keeps UVs and vertex groups. Quad Remesher is not suitable for LODs because it reflows UVs.
3. For each removed bone, add its vertex-group weights to the nearest retained ancestor, then normalise and limit total influences to 4 (or 2).
4. Name objects `<asset>_LOD0..3`. Unity's FBX importer builds a LODGroup from the `_LODn` suffix.
5. For UE, either import LOD0 and use built-in Skeletal Mesh Reduction plus "Bones to Remove" per LOD (UE reweights to the parent), or import LODs via a UE Python script (exact API UNVERIFIED).

**Director's part:** one contact sheet of LOD0–3 at their switch distances.

---

## 7. Per-platform bone and morph limits (validation rules Forge should enforce)

| Rule | Value | Source |
|---|---|---|
| UE max bones per section, default | 65536; clamped by `Compat.MAX_GPUSKIN_BONES`; 256 without 16-bit bone indices | Epic "Skeletal Mesh Rendering Paths" (search summary) |
| UE mobile bones per section | 75, the hard cap; work around by splitting material sections with fewer than 75 bones each | Epic docs; UE forums |
| Why 75 | Each bone takes 3 vec4 uniforms; GLES 3.0 guarantees at least 256 vertex uniform vectors, and 75×3 = 225 | Inference, UNVERIFIED |
| UE bone influences | 4 / 8 default modes; "Unlimited Bone Influence" in Project Settings > Rendering > Skinning, needs a restart | Epic docs |
| Unity influences | 1, 2, 4 or Auto; more than 4 needs compute | Unity ScriptReference |
| Morph targets on Nanite skeletal | Unsupported in 5.5 | Forums |
| Morph targets on mobile | Supported but costly. Forge rule: drop at LOD1+, mobile cap about 52 ARKit shapes only at LOD0 | UNVERIFIED heuristic |
| VAT width | At most 8192 (UE node, forum report) or 16,384 (VFX Export Studio docs) vertices | Forum / vendor docs |

**Forge validator.** For each LOD and material section, count unique deform bones with non-zero weight, check max influences per vertex, and count morphs. Fail the mobile target when any section has more than 75 bones or any vertex has more than 4 influences.

---

## Sources
- [Epic: Skeletal Mesh Rendering Paths](https://dev.epicgames.com/documentation/en-us/unreal-engine/skeletal-mesh-rendering-paths-in-unreal-engine)
- [Epic: Animation Budget Allocator](https://dev.epicgames.com/documentation/en-us/unreal-engine/animation-budget-allocator-in-unreal-engine)
- [USkeletalMeshComponentBudgeted API](https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Plugins/AnimationBudgetAllocator/USkeletalMeshComponentBudgeted)
- [Epic: Impostor Baker plugin](https://dev.epicgames.com/documentation/en-us/unreal-engine/impostor-baker-plugin-in-unreal-engine)
- [Impostor Baker -Z camera bug thread](https://forums.unrealengine.com/t/imposter-baker-1-0-imposters-invisible-when-camera-aligns-to-z-axis/2025249)
- [Epic: Nanite docs](https://dev.epicgames.com/documentation/en-US/unreal-engine/nanite-virtualized-geometry-in-unreal-engine)
- [Status of skinned meshes and Nanite](https://forums.unrealengine.com/t/status-of-skinned-meshes-and-metahuman-and-nanite-support/2835575)
- [Nanite skeletal meshes: morph targets and cloth](https://forums.unrealengine.com/t/nanite-skeletal-meshes-morph-targets-cloth/2062994)
- [UE-228385](https://issues.unrealengine.com/issue/UE-228385)
- [UE 5.6 announcement](https://www.unrealengine.com/en-US/news/unreal-engine-5-6-is-now-available)
- [CG Channel on UE 5.7](https://www.cgchannel.com/2025/11/unreal-engine-5-7-five-key-features-for-cg-artists/)
- [UE mobile 75-bone thread](https://forums.unrealengine.com/t/want-to-increase-bone-limit-on-mobile-more-than-75-bones/369409)
- [UE bone limit thread](https://forums.unrealengine.com/t/what-is-bone-limit-in-ue5/772743)
- [Unity QualitySettings.skinWeights](https://docs.unity3d.com/ScriptReference/QualitySettings-skinWeights.html)
- [Unity SkinnedMeshRenderer.quality](https://docs.unity3d.com/ScriptReference/SkinnedMeshRenderer-quality.html)
- [Unity URP GPU Resident Drawer](https://docs.unity3d.com/6000.3/Documentation/Manual/urp/gpu-resident-drawer.html)
- [Unity BRG sample blog](https://unity.com/blog/engine-platform/batchrenderergroup-sample-high-frame-rate-on-budget-devices)
- [Unity: rendering at scale](https://unity.com/blog/rendering-at-scale-efficient-strategies-for-massive-object-counts)
- [GPU Instancer Pro thread](https://discussions.unity.com/t/released-gpu-instancer-pro/1488733/314)
- [GPU ECS Animation Baker](https://marketplace.unity.com/packages/tools/animation/gpu-ecs-animation-baker-250425)
- [Unity Industry Toolkit BakeImpostor](https://docs.unity3d.com/Packages/com.unity.industry.toolkit@3.2/manual/Actions/Autogenerated/BakeImpostor.html)
- [OpenVAT GitHub](https://github.com/sharpen3d/openvat)
- [OpenVAT on Blender Extensions](https://extensions.blender.org/add-ons/openvat/)
- [OpenVAT UE5 forum thread](https://forums.unrealengine.com/t/openvat-an-open-source-vat-workflow-for-blender-to-ue5/2518621)
- [OpenVAT Unity thread](https://discussions.unity.com/t/vertex-animation-textures-an-elegant-solution-for-baked-simulations-and-advanced-deforming-animation-openvat/1680369)
- [VFX Export Studio docs](https://superhivemarket.com/products/vfx-export-studio-realtime-vfx-textures/docs)
- [SideFX impostor textures](https://www.sidefx.com/tutorials/game-tools-imposter-textures/)

**Not researched (search budget exhausted):** the Unity "Bones count exceeds" message text, UE AnimToTexture plugin docs, URO cvars, City Sample crowd specifics, and Unity 6 "GPU Skinning (Batched)". To read the Epic and Unity pages in full, dev.epicgames.com and docs.unity3d.com must be added to the session's allowed network hosts.
