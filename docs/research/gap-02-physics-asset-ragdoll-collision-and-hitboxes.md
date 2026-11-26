# Research gap: Physics asset, ragdoll, collision and hitboxes

# Forge gap report: physics assets, ragdolls, collision and hitboxes

Scope: how Forge can generate collision and physics data for skinned characters, creatures and mechanical rigs, and turn it into a UE5 Physics Asset or Unity ragdoll and colliders, with no manual modelling. The only manual work is visual approval, plus at most one click to place a weak point.

Repo context: the Blender stages live in `/home/user/Image-to-Game-asset/blender_scripts/forge_bpy/` (`arp_rig.py`, `skin.py`, `joints.py`, `appendages.py`, …). The stage list is in `/home/user/Image-to-Game-asset/forge/pipeline.py`, as `TARGET_STAGES = ["retopo","uv","bake","skin","lods","metrics","previews"]`.

**Proposal:** add a `physics@{engine}` stage between `skin` and `lods`, implemented in a new `forge_bpy/physics.py`. It writes `<asset>.physics.json`, plus `UCX_` meshes for static props. Engine-side importers build the physics assets from that file.

Network note: `dev.epicgames.com` could not be fetched from this session. Epic doc pages are cited from search-result summaries. Any engine default I could not confirm in a source is marked UNVERIFIED.

---

## 0. Core design decision: compute in Blender, use one JSON file, and rebuild in each engine

The UE automatic generator is not good enough on its own:
- It fits by bone length and vertex weights, and skips bones shorter than **Min Bone Size** ([Epic: Tools & Profiles](https://dev.epicgames.com/documentation/unreal-engine/physics-asset-editor-in-unreal-engine---tools-and-profiles?lang=en-US)).
- It often fails with "bone size too small" on badly scaled meshes ([forum](https://forums.unrealengine.com/t/bone-size-too-small-cannot-create-physics-asset-error/288157)).
- The FBX-import `create_physics_asset` setting was reported to have no effect in UE 5.6 ([forum](https://forums.unrealengine.com/t/5-6-bug-fbximportui-settings-physics-asset-configuration-appears-to-have-no-effect/2678237)).

Unity has no automatic generator beyond the 11-body Ragdoll Wizard (humanoids only).

Forge should therefore own the data. Blender measures the mesh, writes an engine-neutral `physics.json`, and the UE and Unity importers build assets from it deterministically. The same JSON also drives a Blender rigid-body drop test, so the director can approve the ragdoll before any engine runs.

### Axis and scale calibration (removes coordinate-convention bugs)

`physics.json` stores every collider in **rest-pose model space** (Blender metres, Z-up). It also stores the **rest-pose head position of every exported bone**.

Each engine importer then:
1. Reads its own imported reference-pose bone positions.
2. Solves a similarity transform (Umeyama/Kabsch: scale, rotation, translation) between the JSON bone heads and the engine bone heads.
3. Applies that transform to all collider points.
4. Converts the result to bone-local space through the inverse of the reference pose.

This absorbs the cm/m difference, Y-up vs Z-up, the handedness flip and ARP export-orientation options automatically. If the residual error is above 1% of character height, the import fails loudly. This calibration method is my own design recommendation; I found no engine document describing it.

---

## 1. Per-feature specification

### 1.1 Ragdoll and hit-reaction bodies (skinned characters and creatures)

**(a) Why it matters.** Death ragdolls, partial hit reactions ("physical animation"), secondary motion on tails and ears, and bone-accurate hit detection all depend on these bodies. In UE the physics asset is "a set of rigid bodies and constraints that make up a single ragdoll" ([Python API: PhysicsAsset](https://docs.unrealengine.com/5.0/en-US/PythonAPI/class/PhysicsAsset.html)).

**(b) Topology requirements.**
- No extra edge loops are needed. Colliders are separate primitives, not mesh.
- Skin weights must be clean, with one dominant bone per vertex region. The fitting below uses dominant weights.
- Joints need the deformation loops already specified in the retopo research. Otherwise collider fit at elbows and knees reflects bad shapes.

**(c) Rig requirements.** One body per *major* deform bone. Constraint count = body count − 1 (a tree). Bones that never get bodies, and are merged into their parent:
- twist bones
- fingers and toes (except on AAA hero characters)
- face bones: eyelids, lips, tongue, jaw (jaw is optional on AAA)
- IK, pole and helper bones
- ARP `c_` controller bones, which are not exported anyway

Small chains (tail, ears, antennae, hair strands) get their own bodies. They are kinematic in the main ragdoll, or simulated only in the UE AnimBP RigidBody node or an equivalent. Bone-name mapping is in §3.

**(d) Texture/material requirements.**
- There are no texture maps. Each body gets a **physical material** or **surface type** that drives damage, impact VFX, decals and footstep sounds.
- The surface tag can be derived from the colour/material ID that Forge already has (metal, flesh, cloth, chitin).

**(e) Automation (Blender).** Implemented in `physics.py`, described in §2.
- **Procedural:** capsule, tapered-capsule, sphere and box fitting; joint limits; masses; collision-disable pairs.
- **From the rig:** if the rig carries `Limit Rotation` constraints (ARP or mechanical rigs), those min/max values become the joint limits directly.
- **Director:** approves one sheet of overlay renders plus a drop-test video.

**(f) Engine notes.**
- **UE:** use a USkeletalMesh with a PhysicsAsset. Blend ragdoll in with `SetAllBodiesBelowSimulatePhysics` and `SetAllBodiesBelowPhysicsBlendWeight`, driven every tick ([Epic: physics-driven animation](https://dev.epicgames.com/documentation/unreal-engine/physics-driven-animation-in-unreal-engine?lang=en-US)).
  - Known issue: blend weight blends the visible pose but leaves the collision bodies at their fully simulated positions ([UE-72912](https://issues.unrealengine.com/issue/UE-72912)). Gameplay traces during a partial blend can therefore hit "ghost" bodies; prefer tuning Physical Animation strength instead.
  - Physical Animation Component accumulating kinematic-target error and preventing sleep ([forum](https://forums.unrealengine.com/t/chaos-ragdoll-rigid-bodies-not-falling-asleep-properly/2525665?page=2)).
  - Physics Blend Weight works together with Physics Control Component since 5.3 ([forum](https://forums.unrealengine.com/t/physics-control-component-how-to-lerp-from-simulated-to-kinematic/1397218)).
- **Unity:** each bone gets Rigidbody, Collider and CharacterJoint. CharacterJoint requires a Rigidbody. Twist has a low/high pair; swing limits are symmetric ([Unity CharacterJoint manual](https://docs.unity.com/en-us/engine/6000.0/manual/physics-section/physics-overview/joints-section/class-character-joint)). The API members are `lowTwistLimit`, `highTwistLimit`, `swing1Limit`, `swing2Limit`, `swingLimitSpring`, `twistLimitSpring`, `swingAxis` and `axis` ([ScriptReference](https://docs.unity3d.com/cn/current/ScriptReference/CharacterJoint.html)).
  - Alive: all bodies are `isKinematic=true` and the Animator is on.
  - Death: the Animator is off and bodies are non-kinematic.
  - Mobile: use the **ragdoll-swap** pattern. The live enemy has only trigger hitboxes and no per-bone Rigidbodies. On death, spawn a pooled ragdoll prefab and copy the pose into it. This is a widely used pattern; it is not documented by Unity.

### 1.2 Joint constraints and limits

**(a) Why it matters.** Wrong limits give the classic broken-ragdoll problems: knees bending forward, heads spinning 360°, and jitter from overlapping bodies.

**(b) Topology requirements.** None.

**(c) Rig requirements.** Each constraint connects child to parent, with its frame on the child bone head.
- **UE.** `FConstraintInstance` has Swing1, Swing2 and Twist set to Free, Limited or Locked. Linear axes stay Locked. UE angular limits are **symmetric (±)**. An asymmetric human joint (elbow 0..145°) must therefore be expressed by rotating the constraint reference frame by the mid-angle and using limit = half-range. The Forge importer does this.
- **Unity.** CharacterJoint twist is asymmetric (low and high), which maps the elbow directly. Swing1 and swing2 are symmetric. The Ragdoll Wizard aligns the twist axis with the limb's largest swing axis ([Unity manual](https://docs.unity.com/en-us/engine/6000.0/manual/physics-section/physics-overview/joints-section/class-character-joint)).
- **Default limit table** (heuristic starting values, UNVERIFIED as "standard"; tune once from the drop-test video), in degrees:

| joint | type | swing1 | swing2 | twist |
|---|---|---|---|---|
| spine and chest | cone | ±25 | ±20 | ±15 |
| neck/head | cone | ±35 | ±30 | ±40 |
| clavicle | cone | ±15 | ±15 | locked |
| upper arm (shoulder) | cone | ±80 | ±60 | ±45 |
| forearm (elbow) | hinge | 0..145 (frame-rotated) | locked | ±10 |
| hand | cone | ±60 | ±30 | ±20 |
| thigh (hip) | cone | ±70 | ±35 | ±30 |
| calf (knee) | hinge | 0..140 back only | locked | ±5 |
| foot | cone | ±35 | ±20 | ±10 |
| tail/ear chain link | cone | ±25 | ±25 | ±10 |
| mech hinge | hinge | from `Limit Rotation` | locked | locked |
| mech piston | prismatic | linear limit from `Limit Location` | — | — |

**(d) Texture/material requirements.** None.

**(e) Automation.**
- **Hinge-axis detection:** take the PCA of the bone's animated rotation over the pose-test frames. If the rig has `Limit Rotation` or locked rotation axes, read those instead.
- **Hinge direction:** the knee/elbow bend side comes from the IK pole-target side in ARP.
- **Collision disable pairs:** parent–child pairs, plus any pair whose capsules overlap by more than 10% at rest pose or in any pose-test frame. These go into `disable_collision`.

**(f) Engine notes.**
- UE: set "Disable Collision" between those pairs (C++ `UPhysicsAsset::DisableCollision(i,j)`).
- Unity: CharacterJoint `enableCollision=false` disables parent–child collision. Disable other pairs with `Physics.IgnoreCollision`. Turn on `enableProjection=true` to stop limbs stretching.

### 1.3 Gameplay hitboxes and damage zones (humans, creatures, mechs)

**(a) Why it matters.** Headshots, weak points (glowing cores, eyes, fuel tanks, exposed joints), armour that reduces damage, and per-zone hit reactions.

**(b) Topology requirements.**
- Weak points that must be shot out or destroyed should be **separate meshes or material slots** (assembly step), so they can hide, swap or emissive-flash.
- Armour plates on mechs are already separate rigid parts.

**(c) Rig requirements.**
- Hitboxes are the ragdoll bodies plus extra *kinematic/query-only* bodies for weak points.
- On UE a weak point is a body on its own bone, for example a `weakpoint_01` bone parented to `spine_03`. ARP can add it as an extra single bone (custom bone) or via the extra-limb tooling already researched.
- Each body has a zone enum: `HEAD, NECK, TORSO_UPPER, TORSO_LOWER, ARM, HAND, LEG, FOOT, TAIL, WING, WEAKPOINT, ARMOR, MECH_JOINT`.
- Default multipliers (design defaults, UNVERIFIED as industry standard): head ×2.5, neck ×1.5, torso ×1.0, limbs ×0.75, hands/feet ×0.5, weak point ×3.0, armour ×0.25.

**(d) Texture/material requirements.**
- An optional **weak-point mask** (R channel of a mask texture) drives an emissive pulse or hit-flash.
- Detecting the weak point from the emissive map produced by the colour step is the automation hook (see e).

**(e) Automation.**
- Zones are assigned by bone-name mapping (§3).
- **Weak-point candidates** are proposed automatically from three sources:
  - emissive or high-saturation texel clusters in the baked colour map, projected back to vertices;
  - assembly part labels such as `core`, `eye`, `tank`, `reactor`, `cockpit`;
  - for creatures, the eyes found by the eyelid/eye research.
- The director gets **one click per weak point.** A Blender operator ray-casts from the viewport click onto the mesh, and the weak point is fitted as a sphere at the click.
- Otherwise the candidate list is approved or rejected in the review sheet.

**(f) Engine notes.**
- **UE.**
  - Hit results against physics-asset bodies return `BoneName` ([UDN collision guide](https://udn.epicgames.com/Three/CollisionTechnicalGuide.html)).
  - Per-poly skeletal collision does **not** return a bone name, and per-poly traces were reported failing from 5.3 onward ([forum](https://forums.unrealengine.com/t/hitresult-bone-is-none-when-perpoly-collision-on/355397), [forum 5.3+](https://forums.unrealengine.com/t/linetracecomponent-doesnt-work-on-per-poly-skeletal-meshes-from-5-3-and-up/2736130)).
  - Skeletal-mesh traces only return the Physical Material from material slot 0 ([UE-189837](https://issues.unrealengine.com/issue/UE-189837)).
  - Therefore put a **Physical Material on each body** (`BodySetup->PhysMaterial`), map it to a Physical Surface (`SurfaceType_Head` …), and read `Hit.PhysMaterial->SurfaceType` with `bReturnPhysicalMaterial=true`.
  - UE allows up to 62 custom surface types (UNVERIFIED).
- **Unity.** Each body's collider sits on a `Hitbox` layer. A `ForgeHitbox : MonoBehaviour {Zone zone; float multiplier;}` goes on the same GameObject. Raycasts read `hit.collider.GetComponent<ForgeHitbox>()`. On mobile, use 4–6 merged trigger capsules (head, torso, arms, legs) on kinematic bodies.

### 1.4 Character controller capsule, pivot and bounds

**(a) Why it matters.** The movement capsule blocks movement. With CharacterMovement, the capsule is the only collision that blocks movement ([forum](https://forums.unrealengine.com/t/character-nav-agent-radius-and-height/292009)). A wrong size causes floating feet, clipping through doors and navmesh mismatches. Wrong render bounds cause culling pops when animation leaves the reference bounds.

**(b) Topology requirements.** The pivot is at the feet, centred between them, at Z=0 in Blender. Forge's finalize step should enforce this.

**(c) Rig requirements.** The root bone is at the origin.

**(d) Texture/material requirements.** None.

**(e) Automation.**
- **Height H:** the rest-pose top of the head (or top of mesh) minus the ground. Exclude the raised-arm and weapon extents.
- **Radius R:** the 90th percentile of horizontal distance from the vertical axis through the pelvis. Use only vertices dominated by torso and leg bones, so arms in A-pose don't inflate it. Clamp to `0.18·H ≤ R ≤ 0.3·H` for bipeds. These are heuristic constants.
- **Quadrupeds and large creatures:** UE CharacterMovement capsules are always vertical. Use R = half the body *width*, H = shoulder height. Add a body "extra collision" from the physics asset for the long axis; otherwise a custom movement or Mover component is needed (UNVERIFIED as best practice).
- **Mechs:** the same fit, using the cockpit/torso part.
- **Bounds:** evaluate every pose-test and animation frame, take the union of the vertex AABBs, and add a 5% margin. Write them to JSON.

**(f) Engine notes.**
- **UE:**
  - `CapsuleHalfHeight = H/2`, `CapsuleRadius = R`. The half-height cannot be less than the radius ([UCapsuleComponent API](https://dev.epicgames.com/documentation/unreal-engine/API/Runtime/Engine/UCapsuleComponent)).
  - Mesh relative location Z = −HalfHeight. Yaw is usually −90 for Blender −Y-forward exports.
  - The ACharacter defaults of radius 34 / half-height 88 are UNVERIFIED (from engine source memory).
  - Nav agent radius ≥ capsule radius and agent height ≥ 2×half-height (Epic guidance quoted in the same [forum thread](https://forums.unrealengine.com/t/character-nav-agent-radius-and-height/292009)).
  - Bodies flagged **"Consider for Bounds"** in the physics asset define the skeletal mesh's runtime bounds. Set it on pelvis, spine, head, hands and feet, plus outermost tail and wing tips (UNVERIFIED flag name; it exists in UE4/5 BodySetup as `bConsiderForBounds`).
- **Unity:**
  - `CharacterController.height=H`, `radius=R`, `center=(0,H/2,0)`.
  - `skinWidth≈0.1·R`; Unity's docs recommend about 10% of the radius (UNVERIFIED citation).
  - `stepOffset ≤ 0.3·H`.
  - `SkinnedMeshRenderer.localBounds` comes from the JSON bounds, so `updateWhenOffscreen` can stay off.

### 1.5 Cloth and hair collision capsules

**(a) Why it matters.** Capes, skirts, long hair and hair cards must not pass through legs and torso. Cloth solvers handle only simple shapes well, and they cost per collider.

**(b) Topology requirements.**
- Cloth needs its own mesh section with a weight/mask paint for simulated vs pinned areas. This is covered by the fur/hair-cards research.
- Collision colliders are separate primitives.

**(c) Rig requirements.**
- A **separate, smaller cloth-collision set**: tapered capsules on thigh, calf, pelvis, spine, upper arm and head, inflated by 0.5–1 cm. Use about 6–12 colliders.
- Cloth collision is not the ragdoll set; never feed it 20+ bodies (heuristic).

**(d) Texture/material requirements.** Cloth max-distance and backstop weight masks (vertex paint in Blender, exported as vertex colour or engine paint).

**(e) Automation.**
- The colliders reuse the §2 fit with `inflate=+0.01 m`.
- The set is chosen as the bones whose capsules lie within cloth reach: the cloth mesh's bounding box expanded by 10%.

**(f) Engine notes.**
- **UE:**
  - Clothing data references a physics asset. Spheres and capsules, including tapered capsules, are the reliable shapes ([forum](https://forums.unrealengine.com/t/capsule-borders-dont-collide-with-cloth/464065/5)).
  - Convex and box shapes are listed as "simple colliders" in the Dataflow collision node ([Epic docs](https://dev.epicgames.com/documentation/unreal-engine/node-reference/Dataflow/SimulationCollisionConfig)), but forum reports show issues ([forum](https://forums.unrealengine.com/t/chaos-cloth-issues-with-convex-collision-transformation-and-ccd-logic-ue-5-6-1/2705862)).
  - There are reported caps on the number of capsules read ([forum](https://forums.unrealengine.com/t/tappered-capsule-doesnt-collide-with-cloth-asset/463764/2)) and a capsule-orientation bug ([forum](https://forums.unrealengine.com/t/chaos-cloth-world-capsule-collision-problem/2698269)).
  - Recommendation: a dedicated `PA_<asset>_Cloth` physics asset with only spheres and tapered capsules.
  - Groom (strand hair) also takes a physics asset for collision (UNVERIFIED detail).
- **Unity:**
  - `Cloth.capsuleColliders` takes `ClothSphereColliderPair`. Two SphereColliders form a *conic (tapered) capsule*, which is "useful for modelling limbs". Cloth only collides with colliders explicitly assigned, and only one way ([Unity ClothSphereColliderPair](https://docs.unity3d.com/ScriptReference/ClothSphereColliderPair.html)).
  - A maximum of 32 spheres is documented for Unity 5.2 and may have changed since ([legacy doc](https://docs.unity3d.com/520/Documentation/ScriptReference/Cloth-sphereColliders.html)).
  - Forge's tapered capsule (r0, r1, endpoints) maps **exactly** onto a sphere pair.
  - Unity Cloth works only on skinned meshes.

### 1.6 Convex decomposition for mechanical parts and static props

**(a) Why it matters.**
- Mechs and vehicles are made of rigid concave parts: claws, turrets, armour shells. Capsules fit them badly.
- Destructible or detachable parts need convex hulls, because dynamic bodies cannot use triangle-mesh collision. In Unity, a non-convex MeshCollider cannot sit on a Rigidbody ([Unity MeshCollider](https://docs.unity3d.com/2021.1/Documentation/Manual/class-MeshCollider.html)).

**(b) Topology requirements.**
- Rigid parts should be separate mesh islands, each skinned 100% to one bone (mechanical-rig research).
- Decompose the **retopo/low-poly** mesh, not the Tripo dense mesh. Triangulate first; CoACD needs triangles ([CoACD README](https://raw.githubusercontent.com/SarahWeiii/CoACD/main/README.md)).

**(c) Rig requirements.** One body per rigid bone, with the hulls listed under that bone. Hinge and piston constraints come from the mech rig's limit constraints (§1.2).

**(d) Texture/material requirements.** A per-part surface type (metal, glass, rubber) from the material ID.

**(e) Automation.**
- **Rigid detection:** for each bone's vertex set, if max weight ≥ 0.99 on more than 95% of its vertices, the part is rigid.
- **Shape choice:** if the convex hull's volume is no more than 1.15× the mesh volume (it is almost convex), use one hull. Otherwise run **CoACD** (`pip install coacd`; `coacd.run_coacd(mesh, threshold=…, max_convex_hull=N, preprocess_mode="auto")`).
  - `threshold` is a concavity cutoff, default 0.05, range 0.01–1. Lower gives more pieces.
  - `max_convex_hull` works only with merge enabled.
  - A 2026 `real_metric=True` mode takes the threshold in metres ([CoACD README](https://raw.githubusercontent.com/SarahWeiii/CoACD/main/README.md); paper: Wei et al., "Approximate Convex Decomposition for 3D Meshes with Collision-Aware Concavity and Tree Search", ACM TOG 41(4), SIGGRAPH 2022, arXiv 2205.02961).
  - A reference wrapper retries with `preprocess_mode="on"` on failure ([EmbodiedGen](https://huggingface.co/spaces/HorizonRobotics/EmbodiedGen-Image-to-3D/blob/a0173e91b4bf0c0aff96532e371b05b91027f9f9/embodied_gen/data/convex_decomposer.py)).
- **Running it:** run CoACD in a **subprocess with a separate Python**, not inside Blender's Python. Wheels for Blender 5.3's bundled Python version are UNVERIFIED.
- **Post-processing:** decimate each hull to at most N vertices with `bmesh.ops.convex_hull` and then vertex clustering. Mobile: replace hulls with fitted OBBs (PCA box) when the box volume is no more than 1.3× the hull volume.
- **V-HACD fallback:** UE's built-in Auto Convex uses V-HACD ([Epic how-to](https://dev.epicgames.com/documentation/unreal-engine/add-a-collision-hull-to-a-static-mesh-using-the-auto-convex-collision-tool-in-unreal-engine)). The Python/Blueprint `BulkSetConvexDecompositionCollisions` exists, and it removes existing collision ([API](https://dev.epicgames.com/documentation/unreal-engine/API/Editor/StaticMeshEditor/UStaticMeshEditorSubsystem/BulkSetConvexDec-)). It can be used engine-side for static props if CoACD is not available.

**(f) Engine notes.**
- **UE static props:** export hulls as `UCX_<RenderMeshName>_##` (boxes `UBX_`, spheres `USP_`) in the same FBX. The name must match the render mesh exactly ([Epic FBX static mesh pipeline](https://dev.epicgames.com/documentation/unreal-engine/fbx-static-mesh-pipeline-in-unreal-engine)).
  - Pitfalls: only the first mesh's collision is imported when several meshes are in one file; "Generate collision" on import overwrites custom collision ([forum](https://forums.unrealengine.com/t/custom-collsion-is-not-imported-with-the-mesh/6872)); a 5.5 Interchange renaming bug drops collision ([UE-248981](https://issues.unrealengine.com/issue/UE-248981)).
  - Recommendation: one FBX per static mesh, with auto-generate collision off.
- **UE skeletal mechs:** UCX is **not** read for skeletal meshes. Hulls go into JSON and become `FKConvexElem` in each bone's `USkeletalBodySetup` (§4).
  - Epic's Auto Convex example uses Hull Count 32, Max Hull Verts 16 and Hull Precision 50,000 ([Epic how-to](https://dev.epicgames.com/documentation/unreal-engine/add-a-collision-hull-to-a-static-mesh-using-the-auto-convex-collision-tool-in-unreal-engine)).
- **Unity:** each hull becomes a child GameObject of the bone with `MeshCollider{convex=true}`. The convex limit is 255 triangles ([Unity MeshCollider](https://docs.unity3d.com/2021.1/Documentation/Manual/class-MeshCollider.html)).
  - Export hull meshes in the FBX with names `HULL_<bone>_##` and `Export Deform Only` off. The postprocessor strips their renderers and turns them into colliders.

### 1.7 Mechanical articulations: Unity ArticulationBody vs Rigidbody joints, and UE equivalents

**(a) Why it matters.**
- Motor-driven mechs, robot arms, cranes and walker legs need stiff, stretch-free joint chains.
- Ordinary joint chains stretch and jitter under heavy mass ratios.
- ArticulationBody uses a Featherstone reduced-coordinate solver, so there is "no unwanted stretch" ([Unity ArticulationBody](https://docs.unity.com/en-us/engine/6000.5/script-reference/unityengine/articulationbody)).

**(b) Topology requirements.** Rigid parts as in 1.6.

**(c) Rig requirements.**
- Joint type per link:
  - `Fixed`
  - `Revolute`: hinge, with limits from `Limit Rotation`
  - `Prismatic`: piston, with limits from `Limit Location`
  - `Spherical`
- Plus a drive (stiffness, damping, forceLimit).
- **Limit:** 64 articulation links. Unity's manual states a maximum hierarchy depth of 64, and the issue tracker reports a 64-body cap and crashes beyond it ([Unity manual](https://docs.unity.com/en-us/engine/current/manual/physics-section/physics-overview/articulations-section/physics-articulations), [issue](https://issuetracker.unity.com/issues/22636/crash-on-physxdyfeatherstonearticulationsetupinternalconstraintsforlink-when-the-total-articulationbodies-count-exceeds-128)).
- For longer chains, connect several articulations with regular joints.

**(d) Texture/material requirements.** None.

**(e) Automation.**
- The JSON `joint.kind` comes from the mech rig's locked axes.
- Drives get stiffness = k·mass(child) with damping ratio about 1 (heuristic).
- Use ArticulationBody only when the asset is tagged `driven_mech`. A plain "mech death collapse" uses Rigidbody plus ConfigurableJoint/HingeJoint.

**(f) Engine notes.**
- **Unity:** ArticulationBody and Rigidbody must not be mixed in the same hierarchy chain (UNVERIFIED wording, generally true).
- **UE:** the same physics asset. Hinge = two angular axes Locked; piston = Linear X Limited. Motorised joints use constraint angular drives or Physics Control Component.
- Mech breakage or destruction is better handled by Chaos Geometry Collections (out of scope).

---

## 2. Blender algorithm: bone-aligned capsules from mesh cross-sections

The new module is `forge_bpy/physics.py`. The inputs are the low-poly skinned mesh, the exported deform armature, and the dense Tripo mesh (optional, for a tighter fit).

**Step 1. Pick the bodies.**
- Walk the deform hierarchy.
- Drop or merge bones matching the exclusion list in §1.1c.
- Drop or merge bones whose length is below `max(0.03 m, 0.035·H)`. This is Forge's own "Min Bone Size", in metres and independent of scale. Merged bones add their vertices to the parent body.

**Step 2. Gather vertices per body.** A vertex belongs to the body of its *dominant* weight, the argmax over the body set after merging. This mirrors UE's "dominant weight" vertex-weighting option (UNVERIFIED option name; UE offers dominant/any weight in body creation).

**Step 3. Work in bone space.** Transform the vertices into the bone's rest-pose matrix (`bone.matrix_local.inverted()`), where +Y runs along the bone.

**Step 4. Take cross-section slices.** For k = 8 slices along y ∈ [y_min, y_max] of that vertex set:
- **Option A (fast):** radial distance `r = sqrt(x²+z²)` of the vertices in each slice band, taking the 85–90th percentile. This ignores spikes such as horns and fur clumps.
- **Option B (exact cross-section):** `bmesh.ops.bisect_plane` on a bmesh copy, with plane normal = bone Y. Keep only the **connected loop nearest the bone axis**, so the torso is not counted when slicing the upper arm. Measure the loop's 2D centroid and its equivalent radius `sqrt(area/π)`, or its max inscribed radius for a tighter fit.
- **Option C (robust when weights are still poor):** `mathutils.bvhtree.BVHTree.ray_cast` from the bone axis outward in 12 directions per slice. The hit distances give the radius profile, and a centroid offset follows from the hit points.

**Step 5. Fit the shape.**
- From the slice profile `r(y)` and centroid `c(y)`, fit a line to `r(y)` to get the tapered capsule: r0 at the proximal end, r1 at the distal end.
- Capsule axis: a line through the slice centroids, which allows an off-axis belly or chest.
- Endpoints: A = c(y_min+r0), B = c(y_max−r1). Clamp the length to ≥ 0.
- Shape choice from the PCA eigenvalues λ1 ≥ λ2 ≥ λ3 of the vertex set:
  - λ1/λ2 > 1.8 and the main axis within 25° of the bone → capsule (tapered if |r0−r1|/max > 0.2)
  - λ1/λ3 < 1.5 → sphere (head, fists, eyeballs, weak points)
  - λ3/λ2 < 0.35 → box, an oriented bounding box from PCA (pelvis, chest on armoured or flat creatures, feet, hands, wings)
  - rigid mech part → convex (§1.6)
- These thresholds are heuristic and are tuning knobs in `pipeline.tunables`.

**Step 6. Shrink-to-avoid.** Iteratively shrink the radius where a body overlaps non-adjacent bodies at rest pose. Keep the overlap with the parent, because the joint covers it.

**Step 7. Validate on pose-test frames.**
- Report % of skin vertices within 1.5 cm of some collider surface. Target ≥ 90% AAA, ≥ 80% mobile (heuristic).
- Report the worst-overlap pairs, which go into `disable_collision`.

**Step 8. Mass.** Volume × density (1000 kg/m³ flesh, 7800 metal scaled by a fill factor of about 0.15 for hollow mech shells), normalised to a target total mass from the asset spec, for example 80 kg for a humanoid. Clamp the child/parent mass ratio to ≤ 1:8 for solver stability (heuristic).

**Step 9. Approval preview.**
- Draw colliders as wireframe objects coloured by zone (head red, weak point yellow, armour grey) and render turntable stills.
- **Drop test:** build a Blender rigid-body world from the same JSON. Each body is a rigid body with a capsule/convex shape. Each constraint is a `GENERIC` rigid-body constraint with `use_limit_ang_x/y/z` and the limit angles. Bones follow via `Child Of`/`Copy Transforms`. Drop from 1 m, render 3 s, and show it to the director.
- Blender's Bullet is not Chaos or PhysX, so this is approximate. It is still enough to catch inverted knees and spinning heads.

Fitting sketch (Option A):
```python
def fit_bone(mesh_obj, arm_obj, bone, vidx):
    Mb = (arm_obj.matrix_world @ bone.matrix_local).inverted() @ mesh_obj.matrix_world
    P = np.array([Mb @ mesh_obj.data.vertices[i].co for i in vidx])  # y = along bone
    y0, y1 = np.percentile(P[:,1], [2, 98]); edges = np.linspace(y0, y1, 9)
    prof = []
    for a, b in zip(edges[:-1], edges[1:]):
        S = P[(P[:,1] >= a) & (P[:,1] < b)]
        if len(S) < 6: continue
        c = np.median(S[:, [0,2]], axis=0)
        r = np.percentile(np.linalg.norm(S[:, [0,2]] - c, axis=1), 88)
        prof.append(((a+b)/2, c, r))
    ys, cs, rs = map(np.array, zip(*prof)); k, m = np.polyfit(ys, rs, 1)
    r0, r1 = max(k*y0+m, .005), max(k*y1+m, .005)
    cA, cB = cs[0], cs[-1]
    A = (cA[0], y0 + r0, cA[1]); B = (cB[0], y1 - r1, cB[1])   # bone space
    return A, B, r0, r1   # convert to model space with (arm.matrix_world @ bone.matrix_local)
```

### `physics.json` schema (v1)
```json
{"schema":"forge.physics/1","units":"m","up":"Z","forward":"-Y",
 "calib":{"bone_heads":{"pelvis":[0,0,0.98],"spine_01":[0,0.01,1.05]}},
 "controller":{"height":1.82,"radius":0.32,"pivot":"feet","bounds_min":[-0.9,-0.7,0],"bounds_max":[0.9,0.7,2.1]},
 "bodies":[
  {"bone":"thigh_l","shape":"tapered_capsule","a":[0.1,0,0.95],"b":[0.12,0,0.55],"r0":0.085,"r1":0.06,
   "mass":9.8,"zone":"LEG","surface":"Flesh","physics_type":"default","bounds":true,"sets":["ragdoll","hitbox","cloth"]},
  {"bone":"weakpoint_01","shape":"sphere","c":[0,0.12,1.3],"r":0.07,"zone":"WEAKPOINT","surface":"Core","physics_type":"kinematic","sets":["hitbox"]},
  {"bone":"turret","shape":"convex","hulls":[[[x,y,z],"..."]],"zone":"ARMOR","surface":"Metal","sets":["ragdoll","hitbox"]}],
 "constraints":[{"child":"calf_l","parent":"thigh_l","kind":"hinge","frame_axis":[1,0,0],
   "twist":[-5,5],"swing1":[0,140],"swing2":[0,0],"drive":null}],
 "disable_collision":[["thigh_l","thigh_r"]],
 "zones":{"HEAD":2.5,"WEAKPOINT":3.0,"ARMOR":0.25}}
```
Limits are stored as asymmetric `[min,max]`; the UE importer re-centres them (§1.2).

---

## 3. Bone-name mapping

Feeding the ARP export with UE-compatible names, using the UE mannequin skeleton, makes the zone table and the UE/MetaHuman retargeting consistent. The canonical names Forge should key on:
- `pelvis`
- `spine_01..05`
- `neck_01`
- `head`
- `clavicle_l`
- `upperarm_l`
- `lowerarm_l`
- `hand_l`
- `thigh_l`
- `calf_l`
- `foot_l`
- `ball_l`

Mirror every `_l` name for `_r`.

ARP's own names are `spine_01.x`, `thigh_stretch.l`, `leg_stretch.l`, `arm_stretch.l`, `forearm_stretch.l` and so on, with twist bones `*_twist.*`. The exact ARP deform names are UNVERIFIED; read them from `arp_rig.py` output.

Exclusion regexes: `twist|_ref|^c_|ik|pole|eyelid|lip|tongue|teeth|brow|cheek|nose|finger|thumb|index|middle|ring|pinky|toes_(?!01)`.

Creature chains: `tail_##`, `ear_##`, `wing_##`, `tentacle_##`, which the appendage finder already emits.

---

## 4. Engine-side importers

### UE5 (editor Python, plus a small C++ editor plugin)

1. Import the FBX with *Create Physics Asset* **off**.
2. Create an empty asset or a default one with `unreal.SkeletalMeshEditorSubsystem.create_physics_asset(mesh, set_to_mesh, lod)`. That subsystem function replaces the deprecated EditorSkeletalMeshLibrary one ([API](https://dev.epicgames.com/documentation/unreal-engine/API/Editor/SkeletalMeshEditor/USkeletalMeshEditorSubsystem/CreatePhysicsAsset)). `unreal.PhysicsAssetFactory` is also exposed ([Python API](https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/PhysicsAssetFactory)). The exact Python method signature is UNVERIFIED.
3. Rebuild the bodies. Editing bodies and constraints from Python is poorly exposed; users report `unreal.PhysicsAsset` being nearly opaque ([forum](https://forums.unrealengine.com/t/editing-physics-assets-via-python/142027)). The practical route is a **~300-line C++ editor plugin, `ForgePhysicsImporter`**, with one `UFUNCTION(BlueprintCallable)` `BuildFromJson(USkeletalMesh*, FString JsonPath, FString Set)` that Python calls. It:
   - clears the bodies;
   - for each body, creates a `USkeletalBodySetup` (`BoneName`, `PhysicsType`, `PhysMaterial`, `bConsiderForBounds`) and fills `AggGeom` with:
     - `FKSphylElem` (`Center`, `Rotation`, `Radius`, `Length` = cylinder length excluding the caps, local Z axis, cm), or
     - `FKTaperedCapsuleElem` (`Radius0`, `Radius1`, `Length`), or
     - `FKSphereElem`, `FKBoxElem`, or
     - `FKConvexElem` (`VertexData` then `UpdateElemBox()`);
   - calls `BodySetup->CreatePhysicsMeshes()`;
   - for constraints, creates a `UPhysicsConstraintTemplate`, sets `DefaultInstance.ConstraintBone1=child` and `ConstraintBone2=parent`, sets the frames from the ref pose with the mid-angle rotation, and calls `SetAngularSwing1Limit(ACM_Limited, half)` etc., with linear axes Locked;
   - calls `DisableCollision(i,j)`;
   - calls `UpdateBodySetupIndexMap()`, `UpdateBoundsBodiesArray()`, `RefreshPhysicsAssetChange()`.

   The C++ member names are from engine-source familiarity and are UNVERIFIED against 5.x headers. Body/constraint indices and the `FPhysAssetCreateParams` options (Create Body for All Bones, Disable Collisions by Default, Create Joints) are documented in the [API](https://dev.epicgames.com/documentation/unreal-engine/API/Developer/PhysicsUtilities/FPhysAssetCreateParams).
4. Build three assets from the `sets` field: `PA_<asset>` (ragdoll + hitbox), `PA_<asset>_Cloth`, and optionally a shadow physics asset of spheres and capsules for capsule shadows. Assign the first to the mesh and the cloth one to the clothing data.
5. Create the Physical Materials and surface types from `zones` and write a `DT_<asset>_DamageZones` DataTable (zone → multiplier).

### Unity (AssetPostprocessor)

The `OnPostprocessModel` step reads the sidecar `<model>.physics.json`, calibrates (§0), and per body:
- adds `Rigidbody{mass, isKinematic=true, interpolation=Interpolate}`;
- adds the collider:
  - CapsuleCollider with `direction` = the bone-local axis closest to A→B, `radius = (r0+r1)/2`, `height = |AB| + 2r`, `center = midpoint`. Unity capsules cannot taper; on AAA, split a strongly tapered capsule into two;
  - SphereCollider or BoxCollider;
  - convex MeshCollider children for hulls;
- adds `CharacterJoint{connectedBody=parent, axis=twist axis, swingAxis, low/highTwistLimit, swing1/2Limit, enableProjection=true, enableCollision=false}`, or ArticulationBody for `driven_mech`;
- adds `ForgeHitbox{zone, multiplier}`;
- sets the layer to `Ragdoll`/`Hitbox`;
- sets up the CharacterController from `controller`;
- builds Cloth `capsuleColliders` from `sets:["cloth"]` as sphere pairs.

Also save a prefab variant `<asset>_Ragdoll` for the mobile ragdoll-swap pattern.

---

## 5. AAA vs mobile limits

These are recommended Forge budgets: heuristic industry practice unless a source is shown, and UNVERIFIED as hard engine limits.

| item | AAA (UE5 PC/console) | Mobile (Unity URP) |
|---|---|---|
| Humanoid ragdoll bodies | 16–22 (adds clavicles, spine ×3, hands, feet, optional jaw) | 10–11. Unity's Ragdoll Wizard layout: pelvis, 2 hips, 2 knees, 2 arms, 2 elbows, middle spine, head (from memory, UNVERIFIED count) |
| Constraints | bodies − 1 | bodies − 1 |
| Creature / quadruped bodies | 20–40, tail ≤ 6 links, ears 1–2 each | 8–15, tail ≤ 3, ears merged into head |
| Hitbox zones | all ragdoll bodies + ≤ 4 weak-point bodies | 4–6 trigger capsules + ≤ 2 weak points |
| Mech: hulls per rigid part / verts per hull | ≤ 8 hulls, ≤ 32 verts (Epic example uses 16 verts, 32 hulls per mesh) | 1–2 hulls or a box per part, ≤ 16 verts; Unity convex ≤ 255 triangles (hard limit) |
| Mech total collision shapes | ≤ 64 | ≤ 20 |
| ArticulationBody links | ≤ 64 (Unity/PhysX hard limit) | ≤ 16 (budget) |
| Cloth colliders per cloth | 8–16 spheres/capsules | 4–6; legacy Unity hard cap 32 spheres |
| Simultaneous full ragdolls | 10–30 | 2–4, then switch to baked death animations |
| Solver iterations (Unity) | 10–12 for ragdolls | default (6) |

---

## 6. Director touch points
1. **One approval sheet.** Collider overlay renders coloured by zone, the drop-test video, the controller capsule shown next to a 1.8 m reference human, and the coverage metric.
2. **Optional clicks.** Place a weak point, or reject or accept auto-detected weak points.
3. **Rejection knobs.** On "too fat / too thin", the supervisor adjusts `radius_percentile` (88 → 80/95), `inflate` and the limit scale (×0.8 / ×1.2) through `pipeline.tunables`, and the stage reruns. No modelling is required.

---

## Sources
- Epic: [Physics Asset Editor Tools & Profiles](https://dev.epicgames.com/documentation/unreal-engine/physics-asset-editor-in-unreal-engine---tools-and-profiles?lang=en-US) · [FPhysAssetCreateParams](https://dev.epicgames.com/documentation/unreal-engine/API/Developer/PhysicsUtilities/FPhysAssetCreateParams) · [SkeletalMeshEditorSubsystem.CreatePhysicsAsset](https://dev.epicgames.com/documentation/unreal-engine/API/Editor/SkeletalMeshEditor/USkeletalMeshEditorSubsystem/CreatePhysicsAsset) · [PhysicsAssetFactory (Python)](https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/PhysicsAssetFactory) · [PhysicsAsset (Python)](https://docs.unrealengine.com/5.0/en-US/PythonAPI/class/PhysicsAsset.html) · [Physics-driven animation](https://dev.epicgames.com/documentation/unreal-engine/physics-driven-animation-in-unreal-engine?lang=en-US) · [FBX static mesh pipeline](https://dev.epicgames.com/documentation/unreal-engine/fbx-static-mesh-pipeline-in-unreal-engine) · [Auto Convex Collision](https://dev.epicgames.com/documentation/unreal-engine/add-a-collision-hull-to-a-static-mesh-using-the-auto-convex-collision-tool-in-unreal-engine) · [BulkSetConvexDecompositionCollisions](https://dev.epicgames.com/documentation/unreal-engine/API/Editor/StaticMeshEditor/UStaticMeshEditorSubsystem/BulkSetConvexDec-) · [UCapsuleComponent](https://dev.epicgames.com/documentation/unreal-engine/API/Runtime/Engine/UCapsuleComponent) · [Dataflow SimulationCollisionConfig](https://dev.epicgames.com/documentation/unreal-engine/node-reference/Dataflow/SimulationCollisionConfig) · [UDN Collision guide](https://udn.epicgames.com/Three/CollisionTechnicalGuide.html)
- Epic issues and forums: [UE-72912](https://issues.unrealengine.com/issue/UE-72912) · [UE-189837](https://issues.unrealengine.com/issue/UE-189837) · [UE-248981](https://issues.unrealengine.com/issue/UE-248981) · [per-poly no BoneName](https://forums.unrealengine.com/t/hitresult-bone-is-none-when-perpoly-collision-on/355397) · [per-poly 5.3+](https://forums.unrealengine.com/t/linetracecomponent-doesnt-work-on-per-poly-skeletal-meshes-from-5-3-and-up/2736130) · [Python physics asset editing](https://forums.unrealengine.com/t/editing-physics-assets-via-python/142027) · [5.6 FbxImportUI physics asset bug](https://forums.unrealengine.com/t/5-6-bug-fbximportui-settings-physics-asset-configuration-appears-to-have-no-effect/2678237) · [bone size too small](https://forums.unrealengine.com/t/bone-size-too-small-cannot-create-physics-asset-error/288157) · [nav agent vs capsule](https://forums.unrealengine.com/t/character-nav-agent-radius-and-height/292009) · [Chaos ragdoll sleep](https://forums.unrealengine.com/t/chaos-ragdoll-rigid-bodies-not-falling-asleep-properly/2525665?page=2) · [cloth tapered capsules](https://forums.unrealengine.com/t/capsule-borders-dont-collide-with-cloth/464065/5) · [cloth capsule cap](https://forums.unrealengine.com/t/tappered-capsule-doesnt-collide-with-cloth-asset/463764/2) · [cloth capsule orientation](https://forums.unrealengine.com/t/chaos-cloth-world-capsule-collision-problem/2698269) · [cloth convex CCD issues](https://forums.unrealengine.com/t/chaos-cloth-issues-with-convex-collision-transformation-and-ccd-logic-ue-5-6-1/2705862) · [UCX custom collision import](https://forums.unrealengine.com/t/custom-collsion-is-not-imported-with-the-mesh/6872)
- Unity: [CharacterJoint manual](https://docs.unity.com/en-us/engine/6000.0/manual/physics-section/physics-overview/joints-section/class-character-joint) · [CharacterJoint API](https://docs.unity3d.com/cn/current/ScriptReference/CharacterJoint.html) · [ArticulationBody](https://docs.unity.com/en-us/engine/6000.5/script-reference/unityengine/articulationbody) · [Articulations manual](https://docs.unity.com/en-us/engine/current/manual/physics-section/physics-overview/articulations-section/physics-articulations) · [Articulation 64-body issue](https://issuetracker.unity.com/issues/22636/crash-on-physxdyfeatherstonearticulationsetupinternalconstraintsforlink-when-the-total-articulationbodies-count-exceeds-128) · [MeshCollider (255-tri convex)](https://docs.unity3d.com/2021.1/Documentation/Manual/class-MeshCollider.html) · [ClothSphereColliderPair](https://docs.unity3d.com/ScriptReference/ClothSphereColliderPair.html) · [Cloth.sphereColliders 5.2](https://docs.unity3d.com/520/Documentation/ScriptReference/Cloth-sphereColliders.html)
- CoACD: [README](https://raw.githubusercontent.com/SarahWeiii/CoACD/main/README.md) · [GitHub](https://github.com/sarahweiii/CoACD) · [EmbodiedGen wrapper](https://huggingface.co/spaces/HorizonRobotics/EmbodiedGen-Image-to-3D/blob/a0173e91b4bf0c0aff96532e371b05b91027f9f9/embodied_gen/data/convex_decomposer.py)

**Main UNVERIFIED items:**
- UE body-creation enum names (Primitive Type list, Dominant/Any Weight) and the Min Bone Size default
- the C++ member names in §4
- the exact Python signature of `create_physics_asset`
- the ACharacter 34/88 capsule default
- the 62 surface-type limit
- the Unity Ragdoll Wizard body count
- the Unity skinWidth guidance
- CoACD wheel availability for Blender 5.3's Python
- all joint-limit defaults, budget numbers and fitting thresholds, which are design heuristics
