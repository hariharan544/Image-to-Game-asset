# Research gap: Damage states, destruction and dismemberment

# Forge gap report: damage states, destruction and dismemberment

Scope: what Forge must author in Blender (topology, bones, sockets, materials and metadata) so UE5 and Unity URP can run destruction, mech and vehicle damage states, creature dismemberment and progressive damage masks. Items marked UNVERIFIED are from memory or from a single forum report and were not confirmed against current docs.

---

## 0. Cross-cutting conventions (decide once, apply to every asset)

These make the rest of the report work.

1. **Damage manifest.** Forge writes one `forge_damage.json` per asset. It lists cut bones, cap slots, piece lists, sockets, zone IDs and state meshes. UE Python and Unity editor importers read it and build the Blueprints and prefabs. FBX cannot carry most of this:
   - Chaos cluster hierarchy is not an FBX attribute, so the importer ignores it ([SideFX forum](https://www.sidefx.com/forum/topic/88676/)).
   - UE skeletal sockets are made in the Skeleton editor, not imported from FBX.
2. **Two UV channels.**
   - UV0 is for the art. Mirroring and overlaps are allowed.
   - UV1 must be unique and non-overlapping. Runtime hit masks and wound render targets need a unique layout ([Tom Looman](https://tomlooman.com/unreal-engine-render-character-wounds/), [UDK HitMask](https://docs.unrealengine.com/udk/Three/HitMask.html)).
   - UVPackmaster: run a second pack into UV1 with overlaps and mirroring disabled.
3. **Reserved material slots.** These are the names the engine scripts look for:
   - `MI_<asset>_Interior`: fracture cut faces. Triplanar, so no UVs or bakes are needed.
   - `MI_<asset>_GoreCap`: flesh caps and stumps.
   - `MI_<asset>_MechInterior`: hidden panel cavities.
   - The dense Tripo source has no interior surfaces, so these faces must be **excluded from the normal/AO/colour bake**. Give them their own material and bake only the exterior slot.
4. **Damage mask packing.** One RGBA texture per asset at mobile resolution, generated in Blender:
   - R = blood/grime accumulation (cavity and AO based)
   - G = burn/char (convexity plus noise)
   - B = cracks/scratches (Voronoi edges masked by curvature)
   - A = zone ID (see §4)
   - The engine shader blends these with scalar params `Damage_Blood`, `Damage_Burn`, `Damage_Crack` (0–1) or per-zone arrays.
5. **Names.**
   - Collision: `UCX_<mesh>_NN`.
   - Static-mesh sockets: `SOCKET_<name>` empties. The UE FBX static-mesh importer turns these into sockets (UNVERIFIED for UE 5.5+ Interchange).
   - Pieces: `<asset>_chunk_NNN`.
   - State meshes: `<asset>_S0/S1/S2`.
   - Caps: `<asset>_cap_<bone>_parent` and `<asset>_cap_<bone>_child`.

---

## 1. Prop and structure destruction (UE Chaos Geometry Collection / Unity pre-fractured prefab swap)

**(a) Why it matters.** Destruction gives readable feedback and changes gameplay (cover, paths). AAA titles simulate the pieces physically. Mobile can only afford a mesh swap plus a few rigid bodies.

**(b) Topology**
- The intact mesh must be a closed manifold. Forge's repair step already guarantees this.
- **UE path (recommended): fracture in UE, not Blender.**
  - Ship the intact retopo mesh with an extra empty material slot `Interior`.
  - Chaos Fracture Mode does Voronoi, cluster, planar and slice fracture with multiple cluster levels ([Epic: Fracturing GC](https://dev.epicgames.com/documentation/en-us/unreal-engine/fracturing-geometry-collections-user-guide), [Cluster GC](https://dev.epicgames.com/documentation/unreal-engine/cluster-geometry-collections-user-guide-in-unreal-engine)).
  - Internal faces get a second material ID ([Epic GC guide](https://dev.epicgames.com/documentation/unreal-engine/geometry-collections-user-guide)).
  - Forum reports say automatic internal-slot creation changed around UE 5.3. There is now a Utilities tool that assigns materials to internal and external faces ([forum](https://forums.unrealengine.com/t/how-do-i-assign-materials-to-internal-surfaces/1941762)). Verify this per engine version.
- **Art-directed and Unity path: fracture in Blender.**
  - Export every piece as its own mesh in one FBX, with Combine Meshes off.
  - In UE, select all imported piece actors and click **Fracture Mode > Generate > New**. Each mesh becomes one GC piece ([forum workaround](https://www.sidefx.com/forum/topic/88676/), [Dataflow quickstart](https://dev.epicgames.com/documentation/unreal-engine/dataflow-for-destruction-quickstart?lang=en-US)).
  - Blender cluster hierarchy does **not** survive the import. Rebuild clusters in UE with Auto Cluster or Dataflow.
  - One UE 5.0.1 report says pieces vanished until they had UVs ([forum](https://forums.unrealengine.com/t/disappearing-mesh-with-fracture-mode/534591)). Always UV the interior faces too, even with a simple box projection.
- **Piece budgets** (heuristics, UNVERIFIED):
  - AAA hero prop: 50–300 leaf pieces in 2–3 cluster levels.
  - Mobile: 8–30 fragments, low poly, with the intact mesh shown until the break.
  - Unity convex MeshColliders are capped at 255 triangles. Generate simplified convex hulls with Decimate and Convex Hull and export them as `UCX_` objects.
- **Embedded geometry.** Rebar or wiring inside walls has no collision and is not simulated. Add it in UE with the Embed tool ([Epic cluster guide](https://dev.epicgames.com/documentation/unreal-engine/cluster-geometry-collections-user-guide-in-unreal-engine)). Forge can export it as a separate mesh named `<asset>_embed_*`.

**(c) Rig and engine components**
- No skeleton is needed.
- UE: GeometryCollectionComponent with these settings:
  - Damage Thresholds per cluster level. The size-specific threshold option overrides the level thresholds.
  - Anchored pieces (Fracture Mode > Set Anchored) for the parts that stay attached to the ground or wall.
  - Remove-On-Break timers (Utilities > Set removal-on-break, plus *Allow Removal on Break*). There is a known issue where removed pieces stop colliding but keep rendering ([UE-358545 / forum](https://forums.unrealengine.com/t/unable-to-interact-with-geometry-collection-after-use-removal-on-break-utilitie/2692833)).
  - Fields (Anchor, Strain) are the runtime triggers.
- Unity:
  - Intact prefab, plus a `_Fractured` prefab whose fragments each have a Rigidbody and a convex MeshCollider, all disabled by default.
  - A script swaps the two at a damage threshold and applies an explosion force ([Unity discussions](https://discussions.unity.com/t/exploding-models/1635879), [Unity manual: wreck prefabs](https://docs.unity3d.com/Manual/instantiating-prefabs-wrecks.html)).
  - Options: OpenFracture (open source, convex and non-convex) for runtime or editor fracture ([GitHub](https://github.com/unitycoder/OpenFracture)), RayFire (commercial), or a baked "Break" animation clip instead of physics on low-end devices.

**(d) Texture and material**
- Exterior: the existing baked PBR.
- Interior:
  - Triplanar procedural material: concrete, wood grain, metal or stone, chosen from the asset class tag.
  - Optional: a dark-to-bright edge gradient from vertex colour, written by Blender as distance to the original surface.
  - Emissive "hot core" for lava or energy props.
- Crack pre-damage before the break: the B channel of the mask, driven by `Damage_Crack`.

**(e) Blender automation**
- **Cell Fracture extension.** It shipped with Blender 4.1 and is now an extension for 4.2+ ([extensions.blender.org](https://extensions.blender.org/add-ons/cell-fracture/), [manual](https://docs.blender.org/manual/en/4.1/addons/object/cell_fracture.html)).
  - Operator: `bpy.ops.object.add_fracture_cell_objects(...)`. The bl_idname is UNVERIFIED; check the extension source.
  - Main parameters: `source={'PARTICLE_OWN'|'VERT_OWN'|'PENCIL'}`, `source_limit`, `source_noise`, `recursion`, `margin`, `material_index`, `use_interior_vgroup`.
  - A review reports that in 4.3.1 the interior material and the interior vertex group are **not assigned**. Do not rely on the extension's interior material assignment. Assign the material yourself, using the rule in the next item.
- **More robust: Forge's own Voronoi in bmesh.**
  - Scatter N seed points: volume-uniform, or biased toward an impact point the director clicks.
  - For each seed, copy the mesh and run `bmesh.ops.bisect_plane(..., clear_outer=True)` against the perpendicular-bisector plane of every neighbouring seed.
  - Fill each cut with `bmesh.ops.contextual_create` / `edgeloop_fill`.
  - Tag the new faces with the Interior material index. Every face created by a bisect fill is interior by construction.
  - Recursion (re-fracturing pieces) gives the cluster levels. Store the parent index in a custom property so the manifest can describe intended clusters.
- **Unity collision.** Per piece: Convex Hull, then decimate to ≤255 tris, exported as `UCX_`.
- **Geometry Nodes.** No built-in Voronoi fracture node is known to exist in 4.x/5.x (UNVERIFIED for 5.3). Use bmesh.
- **Director involvement.** One click for the density preset (low/med/high), plus an optional impact point. Everything else is procedural. An AI-generated part is only needed for distinctive interiors such as a hollow statue or a machine core.

**(f) Engine notes**
- UE: Nanite works with GCs in UE5, and the root proxy mesh can render the intact state cheaply (UNVERIFIED feature name).
- Unity mobile: pool the fracture prefabs, enable only the pieces near the hit, and fade and destroy them after a few seconds ([UE mobile fake-destruction thread with the same pattern](https://forums.unrealengine.com/t/faking-destructible-mesh-functionality-on-mobile/351142)).

---

## 2. Vehicle and mech damage states (state swaps, detachable parts, hidden cavities, dents)

**(a) Why it matters.** Damage is read silhouette-first: lost armour plates, a hanging door, a burnt husk. It tells the player which parts are weak and gives destroyed cars and mechs wreck geometry. Doom Eternal's "destructible demons" uses the same idea on creatures: armour and weak points stripped piece by piece, which changes AI behaviour ([PC Gamer](https://www.pcgamer.com/hugo-martin-doom-eternals-destructible-demon-system-makes-such-an-impact-2016s-doom-is-now-hard-to-play/), [PCGamesN](https://www.pcgamesn.com/doom-eternal/doom-eternal-destructible-demons)).

**(b) Topology**
- **Whole-asset state meshes.**
  - `S0` intact, `S1` damaged (silhouette breaks, missing panels, bent parts), `S2` destroyed husk (charred, collapsed, no glass).
  - S1 and S2 share the UV0 layout with S0 so the same textures and masks still apply. Forge makes S1/S2 from S0 by procedural edits, so this comes for free.
  - Mobile: S0 plus S2 only.
- **Detachable parts** (doors, wheels, armour plates, turrets, antennae, mech limbs):
  - Each part is a separate object with its origin at the hinge or attach pivot.
  - Each part has its own `UCX_` collision.
  - Each part is a closed mesh with a back face or thickness. The inside of a panel is visible once it flies off.
- **Hidden cavity under each part** (`MechInterior`):
  - A shallow recessed shell where the part was, showing wiring, frame and sockets.
  - In the intact state it must not z-fight. Either the cavity sits fully behind the part, or it is hidden and the engine shows it.
  - A procedural default: duplicate the footprint faces under the part, inset 5–10%, extrude inward, and add a greeble array.
- **Dents.**
  - Skeletal vehicles: per-zone shape keys `Dent_FrontL`, `Dent_FrontR`, `Dent_Roof` and so on, exported as morph targets.
  - Procedural generation: displace inward along the normal, weighted by a zone vertex group and noise.
  - These need a reasonably even quad density on the panels. Quad Remesher's default output is fine.
- **Budgets** (UNVERIFIED heuristics):
  - AAA: S1 about the same tri count as S0. S2 at roughly 60% of S0. Each detachable part 0.5–5k tris.
  - Mobile: 3–8 detachables at most.

**(c) Rig**
- **Static props and vehicles in UE (preferred for new UE5 work).**
  - Chaos Modular Vehicles: a tree of Geometry Collection components under a ClusterUnionVehicleComponent.
  - Parts can be detached by code or by physics collision ([Epic overview](https://dev.epicgames.com/documentation/unreal-engine/chaos-modular-vehicles-overview)).
  - Each Forge detachable then becomes its own GC asset.
  - Community reports say the animation and cluster-union callback on part loss is rough ([forum](https://forums.unrealengine.com/t/chaos-modular-vehicles-wheels-fall-off/2735416)). This is still experimental.
- **Skeletal mechs and vehicles (ARP).**
  - Every detachable gets its **own deform bone**: `part_door_l`, `part_plate_chest_01` and so on, parented to the carrying bone.
  - Weights are 100% rigid to that bone. Hard-surface parts need rigid skinning. The ARP mechanical approach was covered separately.
  - On detach:
    - UE: `HideBoneByName(bone, PBO_Term)`, then spawn the matching static mesh `SM_part_*` with simulated physics at the bone transform.
    - Unity: set the bone's `localScale = Vector3.zero` and instantiate the part prefab.
  - The physics asset gets one body per part bone, so hits can be attributed to parts.
- **Sockets.** Use non-deforming leaf bones or `SOCKET_` empties:
  - `fx_smoke_engine`, `fx_spark_<part>`, `fx_fire_<n>` for damage VFX.
  - `attach_<part>` for the pivot.
  - In ARP, add these as custom bones. Whether `cc_`-prefixed custom bones export as deforming or helper bones is UNVERIFIED for 3.79.x; check the "Export > Custom bones" behaviour.
- **Hidden cavity visibility.**
  - UE: put the cavity in its own material slot and toggle it with `SkinnedMeshComponent::ShowMaterialSection(MaterialID, SectionIndex, bShow, LOD)` (UNVERIFIED BP exposure for every version). The alternative is a separate component that is attached and hidden.
  - Unity: a separate child renderer, disabled by default.

**(d) Texture and material**
- All parts share the master material with these parameters:
  - `Damage_Burn`: a char albedo multiplier, roughness raised, plus an emissive ember mask from noise in the G channel. Decays over time.
  - `Damage_Crack`/scratch: exposes bare metal via the B mask, which lowers roughness and raises metallic.
  - Bullet holes: decals, or the render-target hit mask on UV1.
- S2 husk: bake a second albedo variant (char, soot, no paint), or drive `Damage_Burn = 1`.
- Glass: a separate slot, removed in S2, and shown as a crack-normal variant in S1.
- `MechInterior`: a trim sheet (cables, pipes, panels) shared across all mech assets, with no per-asset bake.

**(e) Blender automation**
- **Segmenting detachables from a Tripo single shell is the hard part.** The procedure:
  1. bmesh region growing on the original dense mesh, splitting where the dihedral angle exceeds about 40°, the colour changes, or there are panel-gap grooves (strong concave curvature lines).
  2. Propose candidate panel islands to the director, coloured.
  3. The director clicks to confirm or merge.
  4. Separate the panels, solidify them by thickness, and generate the cavity.
- **Alternative:** ask the AI generator for the parts separately, using part-aware generation or segmentation if Tripo offers it (UNVERIFIED for current Tripo features), and assemble them in the existing "assemble parts" step. This is the most reliable path for hero vehicles.
- **Done procedurally:**
  - S1: remove the detachables, add dents, chip the bevels with the Boolean noise cutter.
  - S2: remove glass, darken, collapse with Lattice or Simple Deform.
  - Dent shape keys, cavity shells, UCX hulls, sockets placed at part pivots.
- **Director clicks:** confirm the parts, and approve the S1/S2 look.

**(f) Engine notes**
- UE: state swaps can use `SetStaticMesh`/`SetSkeletalMeshAsset`. GC per part if using Chaos.
- Unity: prefab variants per state, with parts as child prefabs (Rigidbody isKinematic until released).
- Mobile: keep the swap and spawn at most 3 rigid bodies.

---

## 3. Creature and character dismemberment

**(a) Why it matters.** Dismemberment is core feedback in shooters and action games (Dead Space, L4D2, Fallout, Doom Eternal). It changes the silhouette and locomotion: crawlers, a headless death. Close-ups expose stumps, so the caps must hold up.

**(b) Topology (the critical rules)**
1. **Cut points sit at a child bone's head (a joint).**
   - `HideBoneByName` simply forces scale 0 on the bone and its children ([Epic Skinned Mesh docs / forum](https://forums.unrealengine.com/t/hide-unhide-a-specific-bone-by-name/481745)).
   - Vertices skinned to the hidden bone collapse to that bone's pivot ([UE-220481](https://issues.unrealengine.com/issue/UE-220481)).
   - So the cut ring must lie at that pivot, or the stump visibly pinches.
   - Standard cut list for humanoids (UE mannequin names after ARP's UE rename): `neck_01→head`, `upperarm_l/r`, `lowerarm_l/r`, `hand_l/r` (optional), `thigh_l/r`, `calf_l/r`. Creatures add `tail_01`, `wing_*`, `jaw` and similar.
2. **A clean edge loop exactly at each cut.**
   - Before Quad Remesher, split faces into a temporary material per body segment at the cut planes. Bisect along a plane perpendicular to the bone at its head.
   - Enable QR **"Use Materials"**. Material borders become edge loops (UNVERIFIED exact behaviour; test on one asset).
   - Then merge the materials back into one.
3. **Hard weight seam at the cut.**
   - Vertices on the parent side of the ring: 0% child-bone weight. Vertices on the child side: 100% child-chain weight.
   - Smooth weights that cross the cut cause the classic stretched neck ([forum](https://forums.unrealengine.com/t/break-skeletal-mesh-after-breaking-constraint/130030)).
   - Keep the smoothing to the loops either side of the ring. Joint deformation suffers a little, so add one extra supporting loop near the cut so the hard seam does not crease visibly when bent.
4. **Pre-modelled caps (two per cut):**
   - `cap_<bone>_parent`: the stump on the body, skinned 100% to the parent bone.
   - `cap_<bone>_child`: the end of the severed limb, skinned 100% to the child bone.
   - Both are hidden by default and slightly domed or sunken, with a bone cross-section ring.
   - Fallout 4's Creation Kit uses the same per-limb meat cap and partition approach. Its BodyPartData has Meat Cap TextureSet, Geometry Segment Index, and Cut Min/Max/Radius/Tessellation ([UESP CK BodyPartData](https://falloutck.uesp.net/wiki/BodyPartData)). Caps live in per-limb partitions (BSDismemberSkinInstance), and a missing partition makes caps show on the wrong zones ([Nexus](https://forums.nexusmods.com/topic/1675248-meatcap-not-rendering-on-certain-armors)).
5. **Severed-limb meshes.** Either separate skeletal meshes per cut (`SK_<asset>_limb_<bone>`: the child-chain vertices plus the child cap, same skeleton), or spawn a duplicate of the full mesh and hide the complementary bones. Separate limb meshes are cleaner and cheaper.
6. **Budgets** (UNVERIFIED heuristics):
   - Caps 200–800 tris each at AAA, 50–150 on mobile.
   - Mobile: limit cuts to head plus four limbs, or head only.
   - Caps must exist in **every LOD**, since hiding a bone hides it in all LODs.

**(c) Rig**
- ARP rig unchanged.
- Export the cut list as manifest entries `{bone, parent_cap_slot, child_cap_slot, limb_asset, fx_socket}`.
- Add a non-deforming `fx_cut_<bone>` leaf at each cut (blood spurt socket, oriented along the bone).
- UE runtime:
  - `HideBoneByName(bone, PBO_Term)` terminates the bodies below the bone ([forum](https://forums.unrealengine.com/t/hide-unhide-a-specific-bone-by-name/481745)).
  - Show the parent cap section (`ShowMaterialSection`), or a cap component using `SetLeaderPoseComponent` (the 5.1+ name for SetMasterPoseComponent).
  - Spawn the limb skeletal mesh copying the pose and simulate physics.
  - On ragdolls, `BreakConstraint(impulse, location, bone)` severs the physics joint ([forum](https://forums.unrealengine.com/t/break-skeletal-mesh-after-breaking-constraint/130030)).
  - Hidden bones still have collision unless the bodies are terminated ([forum](https://forums.unrealengine.com/t/bug-scalling-bone-wont-scale-collision/33297)).
  - Attached components are not hidden by HideBoneByName, so detach weapons and armour yourself ([forum](https://forums.unrealengine.com/t/hidebonebyname-does-not-affect-attached-components/2852162)).
- Unity runtime:
  - Scale the bone transform to zero on the SkinnedMeshRenderer's bone array.
  - Enable the cap SkinnedMeshRenderer, which shares the same `bones[]`.
  - Instantiate the limb prefab with a ragdoll (Rigidbody + CharacterJoint) and destroy the joint at the cut.
- Physics asset: one body per cut-chain bone, so hits map to limbs. Per-limb health lives in game code, keyed by the manifest bone names.
- Advanced alternative: runtime procedural slicing plugins avoid pre-cut meshes, but they cost CPU and are not for mobile ([80.lv](https://80.lv/articles/elevate-your-ue5-game-s-interactivity-with-real-time-slicing-dismemberment)).

**(d) Texture and material**
- `MI_GoreCap`:
  - Wet flesh with SSS (UE Subsurface profile; Unity URP has no native SSS, so use wrap lighting or a fake transmission).
  - Low roughness with a wet clearcoat (UE).
  - Albedo variant per creature type (red flesh, green alien, black ichor, machine-oil for cyborgs) via a tint parameter.
  - Bone ring masked by radial UV. Optional emissive for magical or robotic creatures.
- Caps UVs: a planar projection along the bone axis into a shared gore atlas, the same atlas for all assets.
- Body: wound mask on UV1 (§4), with bleed-out around the cut by `Damage_Blood` in that zone.
- Robots and constructs: use `MechInterior` caps instead of flesh. Same mechanism, different material.

**(e) Blender automation**
- **Cut-plane placement.** Fully automatic from ARP deform bones:
  - Plane origin = child bone head. Normal = bone direction.
  - Bisect the retopo mesh along it, restricted to vertices whose dominant weight is in the parent/child pair, so it does not slice the torso.
  - Director involvement: approve the cut overlay, or drag one plane.
- **Weight seam.** Automatic: vertex groups are partitioned by which side of the plane each vertex sits on, then normalised.
- **Cap generation.** Automatic:
  1. Take the boundary loop (`bmesh` boundary edges from a duplicate of the ring).
  2. `bmesh.ops.edgeloop_fill` or grid fill, inset twice.
  3. Push the centre in or out with noise displacement for torn flesh.
  4. Inner inset ring = bone cross-section (material index 1 or a vertex colour).
  5. Weight 100% to the parent or the child bone. Planar UV.
- **Torn edge variant.** Displace the ring with noise. Generate as a shape key or as alternate cap meshes; three variants avoids repetition.
- **Limb meshes.** Automatic: duplicate the body, delete the parent-side vertices, join the child cap, keep the armature modifier.
- **AI-generated parts:** not needed. Optionally an AI-sculpted "hero stump" for close-up cinematics.
- **Director clicks:** pick which cuts are enabled (a default per creature class), and approve the gore intensity preset. Also note region ratings: keep gore assets in separate packages so they can be stripped.

**(f) Engine notes**
- UE:
  - Each cap as a material section costs one draw call when visible. Many sections increase the base draw calls, so consider a single "all caps" section with per-cap vertex-colour IDs and a scalar mask array.
  - Keep `HideBoneByName` targets as joints with no other skinning issues.
- Unity:
  - Bone scale zero is fine with GPU skinning.
  - Caps as separate SkinnedMeshRenderers sharing bones; enable a renderer only after its cap has been revealed.
- Severed limbs (both engines): pool them and fade them out.

---

## 4. Progressive damage masks (blood, burn, cracks, wounds)

**(a) Why it matters.** Progressive masks show state continuously (health, fire exposure, fatigue) with no extra meshes. They are cheap on mobile when zone-based.

**(b) Topology**
- None beyond unique UV1.
- Optional zone vertex colours.
- Valve's L4D2 approach adds no geometry: wound ellipsoids in local space are evaluated in the shader. It allowed up to 54 wounds per model at about 15 extra VS instructions ([Vlachos GDC 2010 slides](https://es.slideshare.net/alexvlachos/gdc-2010-left4dead2-wounds), [VDC Infected shader](https://developer.valvesoftware.com/wiki/Infected_(shader))). It also used pre-modelled wound interior meshes.

**(c) Rig and engine side**
- **Zone-based (mobile and AAA baseline).**
  - The A channel (or vertex colour A) stores a zone ID derived from the dominant deform bone: head, torso, each arm, each leg, tail, and so on.
  - The material holds a per-zone damage array (UE: Custom Primitive Data, so there is no extra MID per instance; Unity: MaterialPropertyBlock float array).
  - Code raises zone damage on hit.
- **Hit-location (AAA).**
  - Convert the hit to pre-skinned local space, then to UV1.
  - Splat into a per-character render target, fading it over time ([Tom Looman](https://tomlooman.com/unreal-engine-render-character-wounds/), [UDK HitMask](https://docs.unrealengine.com/udk/Three/HitMask.html), [skeletal paint tutorial](https://forums.unrealengine.com/t/tutorial-simple-skeletal-mesh-paint-blueprint-only/255419)).
  - Costs 1–2 RTs per character and unique UVs.
  - Alternative: skinned decals (marketplace).
- **Wound ellipsoids (AAA, L4D2 style).**
  - A shader array of up to N ellipsoids in bone or local space. Pixels inside are discarded and show a "wound interior" mesh or a cap-style backface.
  - Advanced; forge only supplies the inner wound mesh: a shrunk, flipped duplicate of the body with the GoreCap material. This is UNVERIFIED as a universal convention.

**(d) Texture and material maps generated by Forge**
- **R blood/grime:** cavity plus AO from the existing bake, plus a gravity bias (world −Z gradient). Pools in crevices.
- **G burn:** noise thresholded by convexity. Drives char albedo, raises roughness, adds emissive embers (a separate threshold band on G gives glowing edges at partial burn).
- **B cracks:** Voronoi edge distance × curvature mask (Blender shader nodes: Voronoi *Distance to Edge*), baked. Stone and ceramic creatures get crack *normal* detail too: a second tiling detail normal, gated by B.
- **A zone ID:** baked from dominant bone weights. For the vertex-colour option, a bpy loop over the vertices sets colour by `argmax(weights)`, then bakes to texture with Emit.
- Blood **wetness:** lower roughness where R × `Damage_Blood` is high. Optional dried-blood darkening over time.
- Packing: one 512² (mobile) or 1–2K (AAA) RGBA, linear (not sRGB), UV0 for authored masks. Runtime hit RTs use UV1.

**(e) Blender automation**
- All four channels are procedural from the existing bakes and the rig. There is no director click except intensity previews: Forge renders 0/50/100% damage turntables for approval.

**(f) Engine notes**
- UE: the master material exposes `Damage_*` scalars plus a CPD zone array. Niagara blood VFX attach at `fx_cut_*` sockets and hit locations.
- Unity URP:
  - Shader Graph with the same parameters.
  - Use MaterialPropertyBlock (or SRP Batcher–compatible per-material instances; note MPBs break SRP Batcher batching).
  - Skip render-target hit masks on mobile.

---

## 5. Pipeline insertion points (where these go in Forge's existing step order)

1. **Assemble parts.** Tag the asset class (prop / vehicle / mech / creature / character) and gore level. Confirm the detachable parts with the director.
2. **Repair.** Ensure manifold so fracture and caps work.
3. **Retopology.** Pre-split at the cut planes and panel borders, then QR with Use Materials so loops land on the cuts.
4. **UVs.** UV0 art pack. UV1 unique pack. Caps go into the shared gore or mech-interior atlas.
5. **Bake.** Exterior slot only. Then generate the damage mask RGBA.
6. **Colour.** Generate the S2 char variant.
7. **Rig.** ARP. Add `fx_*` and `part_*` bones. Enforce the hard weight seam at cuts. Build the dent shape keys.
8. **Pose test.** Also run a dismember preview: in Blender, scale each cut bone to 0, show its caps, and render. Also a fracture preview (an exploded view of the pieces). The director approves both.
9. **Export.**
   - UE: intact mesh with an Interior slot, or the pieces FBX, plus `forge_damage.json`. A UE editor-Python script builds the GC, the cap sections and the limb assets.
   - Unity: the intact and fractured prefabs, state variants, and limb prefabs, built by an editor script from the same manifest.

## 6. Open gaps and items to verify (UNVERIFIED)

- The Cell Fracture bl_idname and its interior-material bug on Blender 5.3. Plan the custom bmesh Voronoi as the default.
- Whether Quad Remesher's "Use Materials" reliably produces closed loops on material borders.
- Whether ARP 3.79.17 exports custom `cc_` bones (needed for `fx_` and `part_` bones).
- Whether UE 5.5+ Interchange still honours `SOCKET_` and `UCX_` prefixes.
- Whether `ShowMaterialSection` is exposed to Blueprint in the target UE version.
- Whether a UE editor-Python API exists for Fracture Mode "New from selection". Fallback: `GeometryCollection` C++ / Dataflow graphs.
- No official guide was found on damage thresholds for Chaos Modular Vehicle part detachment.

## Sources
- [Epic: Geometry Collections user guide](https://dev.epicgames.com/documentation/unreal-engine/geometry-collections-user-guide), [Fracturing GC](https://dev.epicgames.com/documentation/en-us/unreal-engine/fracturing-geometry-collections-user-guide), [Cluster GC](https://dev.epicgames.com/documentation/unreal-engine/cluster-geometry-collections-user-guide-in-unreal-engine), [Dataflow for destruction](https://dev.epicgames.com/documentation/unreal-engine/dataflow-for-destruction-quickstart?lang=en-US), [Destruction quick start](https://dev.epicgames.com/documentation/unreal-engine/destruction-quick-start)
- [Epic: Chaos Modular Vehicles overview](https://dev.epicgames.com/documentation/unreal-engine/chaos-modular-vehicles-overview)
- [SideFX forum: GC export to UE5](https://www.sidefx.com/forum/topic/88676/); [UE forum: internal materials](https://forums.unrealengine.com/t/how-do-i-assign-materials-to-internal-surfaces/1941762); [Remove-on-break issue](https://forums.unrealengine.com/t/unable-to-interact-with-geometry-collection-after-use-removal-on-break-utilitie/2692833)
- [Blender Cell Fracture extension](https://extensions.blender.org/add-ons/cell-fracture/), [manual 4.1](https://docs.blender.org/manual/en/4.1/addons/object/cell_fracture.html)
- [UE forum: HideBoneByName](https://forums.unrealengine.com/t/hide-unhide-a-specific-bone-by-name/481745), [BreakConstraint/stretch](https://forums.unrealengine.com/t/break-skeletal-mesh-after-breaking-constraint/130030), [UE-220481](https://issues.unrealengine.com/issue/UE-220481), [attached components not hidden](https://forums.unrealengine.com/t/hidebonebyname-does-not-affect-attached-components/2852162), [gore mesh tutorial thread](https://forums.unrealengine.com/t/tutorial-preview-gore-mesh-dismemberment-tutorial/48172)
- [UESP Fallout 4 CK BodyPartData](https://falloutck.uesp.net/wiki/BodyPartData), [Nexus meat-cap partitions](https://forums.nexusmods.com/topic/1675248-meatcap-not-rendering-on-certain-armors)
- [Vlachos GDC 2010 L4D2 wounds](https://es.slideshare.net/alexvlachos/gdc-2010-left4dead2-wounds), [VDC Infected shader](https://developer.valvesoftware.com/wiki/Infected_(shader))
- [Tom Looman: rendering wounds](https://tomlooman.com/unreal-engine-render-character-wounds/), [UDK HitMask](https://docs.unrealengine.com/udk/Three/HitMask.html)
- [Unity discussions: pre-fractured swap](https://discussions.unity.com/t/exploding-models/1635879), [Unity manual: wreck prefabs](https://docs.unity3d.com/Manual/instantiating-prefabs-wrecks.html), [OpenFracture](https://github.com/unitycoder/OpenFracture), [UE mobile fake destruction](https://forums.unrealengine.com/t/faking-destructible-mesh-functionality-on-mobile/351142)
- [PC Gamer: Doom Eternal destructible demons](https://www.pcgamer.com/hugo-martin-doom-eternals-destructible-demon-system-makes-such-an-impact-2016s-doom-is-now-hard-to-play/), [PCGamesN](https://www.pcgamesn.com/doom-eternal/doom-eternal-destructible-demons)
- [80.lv: UE5 real-time slicing dismemberment](https://80.lv/articles/elevate-your-ue5-game-s-interactivity-with-real-time-slicing-dismemberment)
