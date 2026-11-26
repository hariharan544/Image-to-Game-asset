# Research gap: Normals across split meshes and stylised/toon shading data

# FORGE gap report: normals across split meshes, and stylised/toon shading data

Scope: shading seams where split meshes meet (head/neck/body, clothing to skin, MetaHuman-style split head and body); normal transfer; tangent consistency; blendshape normals; anime/toon data (inverted-hull outlines with smoothed normals, face-shadow normal editing, SDF face-shadow maps, ramp and threshold masks); UE5 and Unity URP setups; mobile cost; bpy automation.

Network note: three hosts were blocked in this session, so those claims rely on search snippets and are marked: erichu33.github.io (Anime Shading Plus SDF guide), www.docswell.com (Arc System Works Guilty Gear toon-line talk) and dev.epicgames.com (Epic docs). Allow them in the environment's network settings to verify further.

---

## 0. Pipeline decision: avoid the seam where you can

The most reliable fix is to not have a split. MetaHuman splits head and body into separate meshes, so the two sides of the neck boundary are different vertices sitting on top of each other ("Two vertices sit on top of each other but they are not the same vertex"). That split is where its known neck seam comes from ([UE forum: MetaHuman seam after Maya export](https://forums.unrealengine.com/t/metahuman-seam-after-exporting-from-maya/1346076), [Custom MetaHumans world normals mismatch](https://forums.unrealengine.com/t/custom-metahumans-world-normals-mismatching-head-vs-body/2367243)).

Forge rule (recommended):
| Part | Split as | Why |
|---|---|---|
| Head + neck + body skin | **One mesh, several material slots** (Unity submeshes / UE sections). Split into separate objects only if the head must be swappable or needs its own LOD chain or blendshape budget. | Shared vertices give no normal seam and no gap under skinning. Mobile also gets one SkinnedMeshRenderer instead of two. |
| Eyes, teeth, tongue, mouth bag, eyelashes | Separate meshes | They have no shared border with skin, so no seam fix is needed. |
| Armour, hard attachments | Separate meshes, hard edges allowed | They overlap the body rather than continue it, so there is no normal continuity to keep. |
| Tight clothing that continues skin (bodysuit cuffs, collars blending into the neck) | Separate mesh. Transfer normals from the body in a falloff band. | This avoids faceting where the cloth meets skin. |
| Swappable head (MetaHuman-like) | Separate mesh with the **seam protocol in section 1** | |

---

## 1. Seam protocol for split skin meshes (head–neck–body, cloth-to-skin)

**(a) Why it matters.** At a split, each mesh computes its own vertex normals from one side only. You get a lighting crease, and a world-normal crease that SSAO, SSR and outlines also pick up. Under skinning, different weights on the two sides open a visible gap. Normal maps baked separately have different tangent frames, and mip filtering differs across the boundary, so even matched vertex normals can leave a texture seam. Community reports confirm a seam can remain after normal transfer when the meshes are also normal-mapped ([polycount thread](https://polycount.com/discussion/comment/2685710)).

**(b) Topology.**
- The boundary loops must have **identical vertex count and positions**. Have Quad Remesher retopologise the combined skin, then split along an edge loop. Do not retopologise each piece separately.
- Put the split on a clean edge ring in a low-deformation zone: the base of the neck, or under a collar or hairline.
- Give each side 1–2 support loops near the seam so normal interpolation is the same on both sides.
- Budget: no extra triangles. Boundary vertices are duplicated across the two meshes (about 30–60 vertices for a neck ring).

**(c) Rig.**
- Boundary vertices must have **bit-identical skin weights** on both meshes. After Auto-Rig Pro binds, copy the body weights onto the head boundary ring: a Data Transfer modifier using vertex groups, limited to the seam vertex group.
- Shape keys or morphs on the head must **fade to zero delta at the boundary ring**. Multiply each key by a falloff vertex group. Otherwise the ring tears away from the body when an expression plays.

**(d) Normals and tangents.**
1. **Symmetric average (preferred).** Match boundary vertices with a KD-tree. Average their normals (each side's corner normals, area/angle weighted). Write the same custom normal to both meshes.
2. **One-way transfer (simpler).** Use a Data Transfer modifier on the head mesh, source = body, Face Corner Data = Custom Normals, mapping *Nearest Corner and Best Matching Face Normal*, restricted to a seam vertex group. This is the community-standard fix ([BG3 modding: fixing neck seams](https://bg3.wiki/wiki/Modding:Fixing_neck_seams); [80.lv: data transfer to smooth seams between separate meshes](https://80.lv/articles/using-data-transfer-in-blender-to-smooth-seams-between-separate-meshes)). The MetaHuman community fix is the same idea: body to head, boundary edges only ([UE forum](https://forums.unrealengine.com/t/custom-metahumans-world-normals-mismatching-head-vs-body/2367243/7)). A 2–3-ring falloff in the vertex group (weights 1 at the boundary down to 0) blends the transfer into the interior.
3. **Normal-map fade.** Epic suggested fading the head's normal map to flat around the neck as a workaround ([UE forum](https://forums.unrealengine.com/t/custom-metahumans-world-normals-mismatching-head-vs-body/2367243)). In Forge, bake a seam-distance mask (Geometry Nodes *Geometry Proximity* to the boundary curve, stored as a colour attribute, baked to texture). Then lerp the baked tangent-space normal texels toward (0.5, 0.5, 1.0) with numpy over a band of about 8–16 px. Do this on both meshes.
4. **Tangent consistency.** Bake with MikkTSpace in Blender, which is the Cycles bake default. Import with MikkTSpace or imported tangents in the engines: Unity `ModelImporterTangents.CalculateMikk` is the default ([Unity ModelImporterTangents](https://docs.unity3d.com/ScriptReference/ModelImporterTangents.html)). Because custom normals change the tangent frame, either export tangents from Blender (FBX "Tangent Space") and import them, or always recompute from the *imported* custom normals. Never let the engine recompute normals.
5. **Colour and AO continuity.** Bake both meshes from the same dense Tripo source. Include the other mesh as an occluder in the AO bake. Keep texel density equal across the seam. Use ≥16 px dilation so mips do not bleed background.

**(e) Blender automation (Blender 4.1+ / 5.x).**
- Since 4.1, Auto Smooth is gone. Custom normals are always used when they exist, and `use_auto_smooth`, `auto_smooth_angle` and `free_normals_split` were removed in favour of `Mesh.corner_normals` ([Blender 4.1 modeling notes](https://developer.blender.org/docs/release_notes/4.1/modeling/), [PR #108014](https://projects.blender.org/blender/blender/pulls/108014)).
- `Mesh.normals_split_custom_set()` and `normals_split_custom_set_from_vertices()` are still the write path; add-on ports kept using them ([addons PR #104609](https://projects.blender.org/blender/blender-addons/pulls/104609/files)). UNVERIFIED for 5.3 specifically. Blender 4.5+ reportedly stores custom normals as a generic `custom_normal` attribute and adds a GN *Set Mesh Normal* node (UNVERIFIED version), which would make a Geometry Nodes path possible.
- Known bug class: a deform modifier placed *after* a Data Transfer custom-normals modifier may not update normals ([Blender #94838](https://projects.blender.org/blender/blender/issues/94838)). Forge should **apply** the transfer as the last step before export, after the rig preview. The armature is a deform modifier, so exported custom normals remain correct because FBX writes the rest pose.

Core bpy (symmetric seam weld, director never clicks):
```python
import bpy, bmesh, mathutils, numpy as np
def seam_weld(a, b, tol=1e-4):
    ma, mb = a.data, b.data
    kd = mathutils.kdtree.KDTree(len(mb.vertices))
    for v in mb.vertices: kd.insert(b.matrix_world @ v.co, v.index)
    kd.balance()
    na = np.array([n.vector for n in ma.corner_normals]).reshape(-1,3)  # 4.1+
    nb = np.array([n.vector for n in mb.corner_normals]).reshape(-1,3)
    va = np.array([l.vertex_index for l in ma.loops]); vb = np.array([l.vertex_index for l in mb.loops])
    pairs = {}
    for v in ma.vertices:
        co, j, d = kd.find(a.matrix_world @ v.co)
        if d < tol: pairs[v.index] = j
    for ia, ib in pairs.items():
        n = (na[va==ia].sum(0) + nb[vb==ib].sum(0)); n /= np.linalg.norm(n)
        na[va==ia] = n; nb[vb==ib] = n        # rotate to world first if transforms differ
    ma.normals_split_custom_set(na.tolist()); mb.normals_split_custom_set(nb.tolist())
    return pairs   # reuse pairs to copy skin weights b->a and to snap positions
```
Modifier alternative:
```python
dt = head.modifiers.new("SeamNrm", 'DATA_TRANSFER')
dt.object = body; dt.use_loop_data = True; dt.data_types_loops = {'CUSTOM_NORMAL'}
dt.loop_mapping = 'NEAREST_POLYNOR'; dt.vertex_group = "SEAM_FALLOFF"
bpy.ops.object.modifier_apply(modifier=dt.name)
```
Detection: in bmesh, `e.is_boundary` boundary loops on mesh A whose vertices KD-match mesh B within tolerance are the seam. Validation for the director: render a matcap or flat-grey EEVEE turntable at 3 light angles, cropped on the seam, and flag if the max angular normal delta across matched pairs exceeds 0.5°.

**Blendshape normals.** Blender shape keys store positions only. Custom normals are rest-pose data.
- **Unity.** Blend Shape Normals can be *Import* (FBX normals, "requires smoothing groups in the FBX file"), *Calculate*, or *Legacy* (smoothing angle). Blend-shape tangents exist only if Tangents = Calculate ([Unity FBX importer Model tab](https://docs.unity3d.com/Manual/FBXImporter-Model.html)).
- **Unreal.** FBX carries one normal set (the base mesh), so imported morph normals are effectively recomputed ([UE forum: morph targets, normals, FBX](https://forums.unrealengine.com/t/let-me-tell-you-about-morph-targets-normals-and-the-fbx-file-format/84085)). A UE 5.6+ report says morph normal/tangent deformation fails on LOD0 but works on LOD1/2 ([UE forum](https://forums.unrealengine.com/t/morph-target-normal-tangent-deformation-works-on-imported-lods-but-not-on-lod0/2688688)).
- **Consequence.** Recomputed morph normals on a split head only see head geometry, so the seam can reappear while a morph is active. The mitigation is the zero-delta falloff at the boundary from (c). With zero position delta near the seam, the normal delta there is about 0, so the base custom normal survives (UNVERIFIED reasoning; test per engine).
- **Anime faces.** Do not let morphs alter face normals at all: Unity Blend Shape Normals = None, which needs a check. UNVERIFIED that None keeps base normals exactly.

**(f) Engine notes.**
- **UE5.**
  - Import with Normal Import Method = *Import Normals and Tangents*, or Import Normals with MikkTSpace tangents. A forum report says reimport with "import normals and tangents" fixed UV-island seams ([UE forum](https://forums.unrealengine.com/t/metahuman-skeletal-mesh-seam-issue-maya-export/1239237)).
  - **Skin Cache "Recompute Tangents" per section** recomputes per mesh and can re-open the seam. One report: setting Skin Cache Usage = Enabled on the head produced a world-normal seam, while Auto did not ([UE forum](https://forums.unrealengine.com/t/normal-seam-between-head-and-body-after-skin-cache-usage-enabled/1815259)). Keep Recompute Tangents off for split skin sections, or use its vertex-mask channel to exclude the boundary ring (UNVERIFIED that the mask fully fixes it).
  - Interchange vs legacy FBX importer option names differ by version (UNVERIFIED which is default in your 5.x).
- **Unity URP.**
  - Normals = Import.
  - Tangents = Import, or Calculate Mikk.
  - Blend Shape Normals as above.
  - Use a Weld/Optimize mesh setting that does not merge the boundary (separate meshes are safe).
  - Export FBX from Blender with custom normals and tangent space. Smoothing groups are needed for blendshape-normal import (exact Blender option: `mesh_smooth_type='FACE'`; UNVERIFIED that Unity accepts it with custom normals).

---

## 2. Inverted-hull outlines with smoothed normals

**(a) Why.** Hull outlines are the standard anime/toon line, as in Genshin ([Genshin shader breakdown](https://bjayers.artstation.com/blog/category/5)) and Guilty Gear (ASW toon-line talk, blocked; UNVERIFIED details). Extruding along the *render* normals splits the hull at every hard edge and UV/normal split, which tears holes in the outline ([Kodeco UE4 toon outlines](https://www.kodeco.com/92-unreal-engine-4-toon-outlines-tutorial)). So the extrusion uses a separate **smoothed normal**: averaged per position, ignoring splits.

**(b) Topology.**
- **No extra geometry.** The hull is the same mesh drawn a second time, front-face culled and extruded in the vertex shader.
- Avoid very thin geometry: concave creases, nostrils and fingers self-intersect, so mask width there.
- **Per-vertex width control** (Forge colour attribute `toon_ctrl`, linear, byte):
  - R = outline width (0 on eyelashes, inner mouth, nose and fingertip creases)
  - G = outline Z/depth offset (pushes lines behind the face to hide inner lines)
  - B = shadow-threshold offset (see section 4)
  - A = outline colour or material index
- The Guilty Gear/ASW convention uses vertex colour for threshold offset, Z-offset and thickness (UNVERIFIED channel order; source blocked).
- **Mobile:** an optional decimated "outline proxy" mesh at ~30–50% triangles, skinned to the same armature (UNVERIFIED cost benefit).

**(c) Rig.**
- The smoothed normal must survive skinning, so store it in **tangent space** (TBN of the render mesh). The shader rebuilds the object/world normal from the skinned tangent frame. The Smooth Normal Generator doc notes tangent-space storage suits animated models ([zerychen smooth normal generator](https://zerychen.github.io/doc/smooth-normal-generator.pdf)).
- Shape keys do not update the stored smoothed normal. That is acceptable: outline width barely changes on expressions.
- If tangents differ between Blender and the engine, the decoded direction drifts. That is the second reason to export and import tangents.

**(d) Storage options.**
| Store | Precision | UE5 | Unity URP |
|---|---|---|---|
| UV2 (xy) + UV3.x (z), or octahedral-encoded in one UV | float | UV channels map to TexCoord[n] | delt06 URP toon writes smoothed normals to **UV2** and appends `SmoothedNormals` to the name for its post-processor ([delt06 outline wiki](https://github.com/Delt06/urp-toon-shader/wiki/Outline)) |
| Vertex colour RGB | 8-bit | VertexColor node (UNVERIFIED sRGB handling; prefer UVs in UE) | `COLOR` semantic; precision OK for outlines |
| Tangent attribute itself (overwrite tangent with smoothed normal) | float | – | Common Genshin-clone trick; breaks normal maps on that mesh |

Forge default: **octahedral-encode the tangent-space smoothed normal into UV channel 3** (`OutlineNrm`). This keeps vertex colour free for control masks and works in both engines. Mobile URP: one extra float2 stream.

**(e) bpy bake (fully procedural).**
```python
import bpy, numpy as np
from collections import defaultdict
def bake_outline_normals(obj, uv_src="UVMap", uv_dst="OutlineNrm"):
    me = obj.data
    me.calc_tangents(uvmap=uv_src)                  # MikkTSpace, per corner
    key = lambda co: tuple(np.round(co, 5))
    acc = defaultdict(lambda: np.zeros(3))
    for p in me.polygons:                           # angle-weighted face normals per *position*
        for li in p.loop_indices:
            v = me.loops[li].vertex_index
            acc[key(me.vertices[v].co)] += np.array(p.normal) * p.area
    uv = me.uv_layers.get(uv_dst) or me.uv_layers.new(name=uv_dst)
    for l in me.loops:
        n = acc[key(me.vertices[l.vertex_index].co)]; n /= np.linalg.norm(n)
        t = np.array(l.tangent); b = np.array(l.bitangent_sign*np.cross(l.normal, l.tangent))
        ts = np.array([t@n, b@n, np.array(l.normal)@n])   # tangent-space smoothed normal
        o = ts[:2] / np.abs(ts).sum()                     # octahedral encode
        if ts[2] < 0: o = (1-np.abs(o[::-1]))*np.sign(o)
        uv.data[l.index].uv = (o*0.5+0.5).tolist()
```
- Export: FBX must include tangents, and Unity must import tangents so the decode frame matches.
- **Director preview in Blender:** a Geometry Nodes hull (duplicate, offset along the decoded attribute × `toon_ctrl.R` × width, flip faces) with a black emission material, *Backface Culling* on. Alternatively use Solidify (negative thickness, Flip normals, material offset) as a cheap approximation that uses real normals.
- One click for the director: a width slider and an "erase outline here" paint, where vertex-colour R defaults to 1 with automatic zeros on eyelash, mouth-bag and eye meshes.

**(f) Engines.**
- **Unity URP.** URP renders only the first pass of a multi-pass shader in a material, so use either:
  1. A second material appended to the renderer's materials list. An extra material beyond the submesh count re-renders the *last* submesh, so with multiple submeshes use option 2 or a dedicated outline submesh (UNVERIFIED that this behaviour is unchanged in Unity 6).
  2. A **Render Objects** renderer feature with an override outline material on a dedicated layer. delt06's setup uses Clip Space width to cancel perspective, and Offset Factor/depth tweaks against see-through artefacts ([delt06 outline wiki](https://github.com/Delt06/urp-toon-shader/wiki/Outline)).
  - Other references: Unity Toon Shader outline options, including a baked-normal outline map ([Unity Toon Shader outline docs](https://docs.unity3d.com/Packages/com.unity.toonshader@0.15/manual/Outline.html)), [URP_Toon (ChiliMilk)](https://github.com/ChiliMilk/URP_Toon), [URPSimpleGenshinShaders](https://github.com/NoiRC256/URPSimpleGenshinShaders).
- **UE5.**
  1. The **Overlay Material** slot, added in UE 5.1, works on static and skeletal meshes and can be set per mesh or per material slot ([UE forum: where is overlay material](https://forums.unrealengine.com/t/where-is-overlay-material/764815), [community tutorial: simple outline overlay](https://forums.unrealengine.com/t/community-tutorial-how-to-create-an-overlay-material-in-unreal-engine-5-simple-outline/1829138)). The outline material uses World Position Offset = TransformVector(Tangent→World, decode(TexCoord[3])) × width × VertexColor.R. It is Unlit, Two-Sided off, and the culling is reversed (UNVERIFIED that overlay materials can flip cull mode; otherwise use option 2). Known issues: overlay missing on skeletal meshes with a Cloth asset in 5.5 ([forum](https://forums.unrealengine.com/t/overlay-material-is-not-working-on-skeletal-mesh-with-cloth/2653126)), and Mutable overlay bugs in 5.7.
  2. A second Skeletal Mesh component using the same mesh and a leader pose, with an outline material that inverts the hull via WPO ([Kodeco](https://www.kodeco.com/92-unreal-engine-4-toon-outlines-tutorial)).
  3. A post-process edge (custom depth/stencil). This costs more on mobile.

**Mobile cost.**
- The hull roughly **doubles skinned vertex shading and adds one draw call per outlined submesh**. Fill cost is small because the outline is thin.
- A screen-space edge pass needs depth (and normals), plus a full-screen pass. That is bandwidth-heavy on tile-based GPUs (UNVERIFIED general claim; profile on device).
- The SRP Batcher reduces state changes between draw calls but not their number. On low-end devices, unoptimised SRP-batched shaders can be slower than with the batcher off. Check in the Frame Debugger ([Unity SRP Batcher](https://docs.unity3d.com/6000.2/Documentation/Manual/SRPBatcher.html)).
- Forge mobile rules:
  - Outline only on LOD0 hero characters, off at LOD1+.
  - Width in clip space.
  - No outline on props.
  - Budget ≤1 outline draw per character (a single outline submesh).

---

## 3. Face-shadow normal editing (proxy normal transfer)

**(a) Why.** Real face normals (nose, cheeks, lips) produce blotchy cel-shadow islands. Anime faces shade as if they were a simple ellipsoid. Data Transfer of custom normals from a proxy shape is the standard Blender approach for this: "getting clean toon shading on stylized character faces… shade as if it were a different shape" ([Blender Artists: customizing normals series](https://blenderartists.org/t/customizing-normals-tutorial-series/1369038)). A sphere as the source is suggested in [UE forum: normal editing](https://forums.unrealengine.com/t/normal-editing-and-3d-modeling-discussion/150158).

**(b) Topology.** No change. The face must be part of the head mesh, so custom normals live on it. Keep the nose bridge and lips as part of the same continuous surface.

**(c) Rig.** Custom normals are rest-pose. Expressions do not change face shading, which is the intended anime look. Set blendshape normals to not recalculate (see section 1).

**(d) Material.** Use a toon face material with no normal map on the face, or only a detail normal map. Usually it is paired with an SDF face-shadow map (section 4); with SDF, the proxy normals matter mainly for rim and specular.

**(e) Automation.**
1. Fit an ellipsoid or capsule proxy to the head vertex group: bounds and PCA, or the ARP `head` bone axes. Optionally add a separate small capsule for the nose.
2. Paint the weight map procedurally: 1.0 on cheeks and forehead, 0.3–0.5 on nose and lips, 0 at the neck seam. Use the ARP facial reference positions (eyes, lips, nose) as landmarks.
3. Add the transfer:
   ```python
   dt = head.modifiers.new("FaceNrm", 'DATA_TRANSFER')
   dt.object = proxy; dt.use_loop_data = True; dt.data_types_loops = {'CUSTOM_NORMAL'}
   dt.loop_mapping = 'POLYINTERP_LNORPROJ'; dt.vertex_group = "FACE_NRM_W"
   ```
   The mapping is *Projected face interpolated* ([Blender manual: Data Transfer](https://docs.blender.org/manual/en/4.5/modeling/modifiers/modify/data_transfer.html)).
4. Re-run the neck-seam weld afterwards, so the face transfer weight falls to 0 before the seam.
5. Director approval uses an EEVEE *Shader to RGB* → Color Ramp (constant) preview with a light rotating 360° around the head.

**(f) Engines.** Import normals as-is (UE Import Normals; Unity Normals = Import). Never recalculate.

---

## 4. SDF face-shadow maps, toon ramps and threshold masks

**SDF / threshold face-shadow map.**
- **(a) Why.** It gives a clean, art-directed nose and cheek shadow that sweeps smoothly with light yaw: the Genshin/HSR look.
- **(b) Topology.** It needs a **left/right-symmetric face UV**: the shader mirrors the U coordinate when light comes from the other side. URP_Toon states its face shadow mask only works with symmetrical face UVs ([URP_Toon](https://github.com/ChiliMilk/URP_Toon)). Forge solution: a **dedicated UV channel `FaceSDF`**, a front planar projection that is symmetric by construction. The main UVPackmaster layout stays unconstrained.
- **(c) Rig and runtime.** The shader needs the head's forward and right vectors each frame:
  - Unity: a script reads the head bone and sets them on the face material instance. URP_Toon and URPSimpleGenshinShaders both require face forward/left direction inputs ([URPSimpleGenshinShaders](https://github.com/NoiRC256/URPSimpleGenshinShaders)). Avoid MaterialPropertyBlock, because it makes the renderer SRP-Batcher-incompatible ([Unity SRP Batcher](https://docs.unity3d.com/6000.2/Documentation/Manual/SRPBatcher.html)).
  - UE: use Custom Primitive Data or a Material Parameter Collection updated from the head socket transform in the character Blueprint.
  - The ARP bone `head.x` supplies the axes.
- **(d) Texture.** Single channel, 512² mobile / 1024² AAA, linear and not sRGB. The value is the light-yaw threshold at which a texel becomes lit. Shader:
  ```
  lit = step(threshold(uv or mirrored uv), remap(dot(L_xz, forward)))
  ```
  Use the sign of `dot(L, right)` to choose the mirror. The classic authoring workflow: paint shadow masks at several angles, convert each to an SDF, interpolate and merge (Anime Shading Plus workflow, [erichu33 ASPDocs](https://erichu33.github.io/ASPDocs/en/articles/face-shadow-map-creation-and-baking-workflow.html); host blocked, UNVERIFIED details). For lilToon conversion, see [lilToon SDF guide (JP)](https://scrapbox.io/onigiri-tiken/%E3%80%90Unity%E3%80%91%E3%82%B7%E3%82%A7%E3%83%BC%E3%83%80%E3%83%BC%EF%BC%9AlilToon%E3%81%A7SDF%E3%82%92%E4%BD%BF%E3%81%A3%E3%81%9F%E9%A1%94%E5%BD%B1).
- **(e) Automation (procedural, no painting).**
  1. Using the proxy-transferred normals from section 3, or a slightly smoothed copy of the face, bake into `FaceSDF` UV space a lit mask `N·L > 0` for N light yaws (for example 32 steps over 0–180°): EEVEE emission bake, or a numpy evaluation of corner normals per texel via a GN-baked position/normal image.
  2. In numpy, threshold(texel) = first yaw index where lit ÷ N.
  3. Enforce monotonicity: cumulative max, so each texel switches once.
  4. Blur lightly (an SDF-like smooth edge).
  5. Symmetrise by averaging with the mirrored copy.

  The director approves a 6-frame light sweep, plus an optional one-click "nose-shadow length" slider that biases the nose region.

**Toon ramp and threshold masks (body and clothing).**
- **(d) Maps.**
  - **Base colour.**
  - **"ILM/lightmap"** in the Genshin-style layout: R = specular intensity, G = shadow threshold/AO offset, B = specular shape mask, A = ramp row / material ID (community reverse-engineering, UNVERIFIED; [Genshin shader breakdown](https://bjayers.artstation.com/blog/category/5)).
  - **Ramp texture:** 256×(N materials × 2, day/night).
  - **Optional MatCap / rim mask.**
  - The Unity Toon Shader (UTS) equivalents are Base, 1st/2nd Shade Map, Shading Grade Map, High Color mask, Rim mask and Outline width/baked-normal maps ([Unity Toon Shader](https://docs.unity3d.com/Packages/com.unity.toonshader@0.12/manual/index.html)).
- **(e) Automation.**
  - G channel: Cycles AO bake from the dense Tripo mesh, remapped so crevices are pre-shadowed. Add per-vertex `toon_ctrl.B` for manual bias.
  - A channel: Forge part segmentation mapped to a ramp row ID.
  - Ramp rows: procedural from each part's median albedo. Shadow tone = hue shift toward cool or toward the skin's SSS red, saturation +10–20%, value −30–45%. Two-step or soft step from the director's choice of 3 presets.
  - R/B channels: specular from a metal/hair mask (hair cards, metal parts).
  - Blender preview: EEVEE Shader to RGB → Map Range by ILM.G → ramp image lookup with V = ILM.A.
- **(f) Engines.**
  - **Unity URP:** a custom lit shader (URPSimpleGenshinShaders as a teaching base) or UTS.
  - **UE5:** stock UE has no toon shading model. Options: (1) an Unlit material with custom lighting, where the directional light vector comes in through an MPC or Custom Primitive Data from a Blueprint; (2) post-process cel quantisation, which loses per-material ramps; (3) a custom engine shading model (community forks: [UE5 anime/toon shading model thread](https://forums.unrealengine.com/t/ue5-anime-toon-cel-shading-model-works-with-launcher-engine-versions/544226/18), [80.lv physically based cel shading in UE5](https://80.lv/articles/tutorial-physically-based-cel-shading-in-unreal-engine-5)). Forge default for UE: option 1. It is identical in logic to Unity, and the ILM, ramp and SDF textures can be shared.
  - Mobile: ramp lookup plus an SDF sample is about 2 texture fetches. Pack ILM into one RGBA at half the base resolution.

---

## 5. Forge step mapping (what runs where)

| Forge step | New sub-step | Auto / AI part / director click |
|---|---|---|
| Assemble | Decide one-mesh-multi-slot vs split (section 0 table) | Auto by part type |
| Retopo | Retopo combined skin, then split on an edge ring; record `SEAM_*` vertex groups | Auto; director confirms seam height (1 click) |
| UVs | Add `FaceSDF` symmetric UV for stylised faces | Auto |
| Bake | Cross-occluding AO; seam-band normal-map fade; ILM (AO→G, ID→A); SDF face map | Auto |
| Colour | Procedural ramp rows from part albedo | Auto; director picks 1 of 3 ramp presets |
| Rig | ARP bind, then copy boundary weights, shape-key seam falloff, seam weld (`normals_split_custom_set`), face proxy transfer, outline normal bake into UV3, `toon_ctrl` colour attribute | Auto; director paints outline erasures optionally |
| Export | FBX with custom normals and tangents, linear vertex colours, UV3 kept; UE: Import Normals & Tangents, Recompute Tangents off on split sections; Unity: Normals/Tangents Import, Blend Shape Normals as decided, outline via Render Objects | Auto |
| QA | Seam matcap crop (angular delta < 0.5°), light-sweep toon turntable, outline on/off | Visual approval |

UNVERIFIED items to test first in the user's Blender 5.3:
- `normals_split_custom_set` and the `custom_normal` attribute behaviour in 5.x.
- Unity Blend Shape Normals = None preserving custom base normals.
- The UE overlay-material cull-mode flip.
- UE vertex-colour sRGB handling.
- Guilty Gear vertex-colour channel order.

