# Research: mechanical

# Forge research report: mechanical and hard-surface assets

Scope: robots and mechs, vehicles, weapons, tools, machinery, drones, plus hard-surface topology, baking, texturing and engine setup, and how to tell hard-surface from organic automatically.

Source access: dev.epicgames.com and exoside.com would not resolve from this session, so I could not open the Epic or Quad Remesher docs. Claims about them come from search-result summaries of those pages and from community threads. Those claims are cited as [S#], and anything I could not confirm is marked UNVERIFIED. To check them directly, both hosts have to be allowed in the session's network settings.

---

## 0. Key findings, and gaps in the current Forge code

I read these files: `/home/user/Image-to-Game-asset/blender_scripts/forge_bpy/retopo.py`, `uv.py`, `bake.py` and `/home/user/Image-to-Game-asset/blender_addon/forge_send/stages_late.py`.

1. **Rigid parts do not need quad topology.** A mechanical part that never deforms can be triangles or n-gons, so the quad flow Quad Remesher (QR) gives is wasted on it. Two better paths:
   - planar decimation plus hard edges, then a bake; or
   - "mid-poly": a bevel, then weighted normals, and no normal-map bake.

   Today Forge sends every part through QR in organic mode.
2. **Forge never turns on QR normal splitting.** `retopo.py` (`_qr_part`) always sets `s.use_normals = False`, `s.use_materials = False`, and turns `autodetect_hard_edges` on only when no density map was painted. Hard-surface parts need their own branch (section 2).
3. **`bake.py` has no explicit cage object.** `_bake()` uses `cage_extrusion` plus `max_ray_distance` and no `cage_object`. On a low poly with split normals (hard edges), the rays follow the split normals and can leave gaps or seams at hard edges. A hard-surface bake should use a smooth-shaded cage copy (section 3). The exact way Blender extrudes when no cage object is set is UNVERIFIED, so test it on one asset.
4. **The order of operations matters.** `uv.py` already marks seams on sharp edges and island borders, then calls `shade_smooth_by_angle` (40°) after unwrapping. For hard-surface parts, three things must match: the sharp edges (and any Weighted Normal result), the UV seams, and the normals used for the bake and the FBX export.
5. **Rigid binding is the core of every mechanical rig.** Each separate part gets 100% weight on one bone. That exports through Auto-Rig Pro (ARP) or FBX as one skeletal mesh. Pistons, turrets, wheels, gears and rotors are then bone transforms driven by constraints in Blender, by Animation Blueprint, Control Rig or Chaos in UE5, and by scripts or Animation Rigging in Unity.
6. **Segmentation decides most of the work.** Tripo offers part segmentation: v1 is geometric with no settings; v2 is semantic, with granularity and a reference-image option [S14][S15]. That is the best automatic source for wheels, doors, magazines and rotors. The director then confirms only pivots and axes with one click each.

---

## 1. Telling hard-surface from organic automatically, and switching settings

**(a) Why it matters.** The wrong mode gives soft blobs on machines (organic retopo) or faceted skin (hard-edge settings). Many assets are mixed, for example an armoured knight or a cyborg, so classify **per part**, not per asset.

**(e) Detection.** Use these signals, all computable with bpy/bmesh and numpy on a cleaned, lightly decimated copy. The raw Tripo surface is noisy and its edges are rounded, so dihedral angles on the dense mesh understate how sharp the part is.
- **Planarity ratio.** Region-grow faces whose normals are within about 5° of each other. Count the share of total area in regions larger than 0.5% of the part's area. Above roughly 0.45 suggests hard-surface (threshold UNVERIFIED; calibrate it on your own assets).
- **Feature-line ratio.** After `Decimate(decimate_type='DISSOLVE', angle_limit=radians(5))`, take the area-weighted share of edges with a dihedral angle above 30°.
- **Curvature histogram.** Organic shapes give a broad, unimodal mean-curvature spread. Hard-surface shapes are bimodal: near zero on flats plus spikes on edges. The repo already computes per-vertex curvature (`density.py`), so reuse it.
- **Primitive fit.** Fit cylinders or planes with PCA plus RANSAC. Good fits suggest a mechanical part, and a cylinder fit also flags wheel or rotor candidates.
- **Semantic hint.** Use the image or prompt label, for example a vision-model tag such as "robot", "car" or "gun", as a prior. Tripo v2 semantic segmentation part names also help [S14].
- **Director override.** Store a per-part flag `forge_surface = 'HARD' | 'ORGANIC'`. Show it as a coloured overlay and let the director toggle a part with one click.

**Settings by part type:**

| Step | Organic (current) | Hard-surface part |
|---|---|---|
| Retopo | QR with density map | Option A: QR with `autodetect_hard_edges=True`, `use_normals=True` (after marking sharp edges), `use_materials=True` if regions carry material IDs, `adaptive_size` about 20–40. Option B (often better for rigid parts): Decimate DISSOLVE (5–10°), then Decimate COLLAPSE to budget, then triangulate. |
| Normals | smooth by angle 40° | `shade_smooth_by_angle(angle=radians(30), keep_sharp_edges=True)`, then mark sharp edges, then Weighted Normal modifier |
| UV | angle seams | Seams on **every** sharp edge, straightened rectangular islands, uniform texel density |
| Bake | extrusion only | Explicit cage, larger margin, supersample (section 3) |
| Rig | ARP auto-skin | Rigid single-bone weights, no smoothing |

The QR property names above are the ones already measured in `retopo.py`. Community reports say "Detect Hard Edges by angle" can do badly on messy input, and that marking hard edges by hand with "Use Normals Splitting" works better [S1]. Rhino's QuadRemesh, a similar tool, uses a 30° break angle and advises turning detection off for disorganised meshes [S2]. Whether QR honours material borders as edge loops is UNVERIFIED (the QR doc PDF was unreachable [S3]).

---

## 2. Hard-surface topology: support loops, mid-poly with weighted normals, or Nanite

**(a) Why it matters.** Shading errors (gradients across large flat faces) are the most visible flaw on game hard-surface assets. Silhouette bevels matter in close-ups and first-person view.

**(b) The three approaches:**
1. **Low poly with hard edges plus a baked normal map.** This is the classic route and the best fit for Forge, because the dense Tripo mesh is a ready-made "high poly" with soft edges. Sharp edges must sit on UV splits [S4]. One practitioner recommends instead keeping the mesh "as watertight as budgets allow and bevel sharp edges" rather than splitting [S4].
2. **Mid-poly: real chamfers plus weighted or face-weighted normals, with little or no normal bake.** This is common in UE5 studio practice and relies on custom vertex normals [S5]. It suits Nanite (no baked normals needed [S6]). It also suits mobile, because the normal map can be dropped and a tiling detail normal used instead, at the cost of more triangles.
3. **Support loops** are only for subdivision modelling. They are irrelevant to game meshes and should not be generated.

**Bevels and Weighted Normal in bpy** (Blender 4.1 and later, valid in 5.x):

```python
bev = obj.modifiers.new("FG_Bevel", 'BEVEL')
bev.limit_method = 'ANGLE'; bev.angle_limit = radians(30)
bev.width = 0.004 * obj.dimensions.length   # relative to object size
bev.segments = 1  # 2 for hero assets
bev.harden_normals = True
bev.face_strength_mode = 'FSTR_ALL'          # feeds face weights to the next modifier
wn = obj.modifiers.new("FG_WN", 'WEIGHTED_NORMAL')
wn.mode = 'FACE_AREA'; wn.keep_sharp = True; wn.use_face_influence = True
```

The Weighted Normal options (Keep Sharp, Face Influence with face strength from Bevel's "Set Strength") are documented in the Blender manual [S7]. Since 4.1, Auto Smooth is gone; it is replaced by the "Smooth by Angle" modifier node group and `bpy.ops.object.shade_smooth_by_angle` [S8]. Older scripts that set `use_auto_smooth` break [S8].

**Budgets (rules of thumb, all UNVERIFIED; no authoritative source found):**

| Asset | AAA (UE5) | Mobile (Unity URP) |
|---|---|---|
| Hand weapon, first person | 15–60k tris | 2–8k |
| Hand weapon, third person | 5–15k | 1–3k |
| Car | 60–200k (Nanite: much more) | 5–20k |
| Mech or robot | 30–120k | 4–15k |
| Drone or prop | 2–15k | 300–3k |

Bevel only silhouette-defining edges on mobile. Every hard edge and every UV seam duplicates vertices [S4].

**(e) Automation.**
- Fully procedural: dissolve decimate, angle-based sharp marking (`bpy.ops.mesh.edges_select_sharp(sharpness=radians(30))` then `bpy.ops.mesh.mark_sharp()`), the Bevel and Weighted Normal stack, and triangulation.
- Needs a director click only when a crease is wrongly hard or soft. Offer a sharp-edge-angle slider with a live preview.

**(f) Engines.**
- Export custom normals with FBX `mesh_smooth_type='OFF'`, which writes normals only.
- In UE, import with "Import Normals and Tangents" (or "Import Normals"). In Unity, set Normals to Import.
- Nanite may re-split edges and ignore imported normals on some meshes [S6]. Test one asset per type.

---

## 3. Hard-surface baking

**(a) Why it matters.** Seams, waviness and edge gaps are what make a baked prop look "AI-made".

**(b), (d) Rules:**
- Every hard edge sits on a UV island border. A UV split does not require a hard edge [S4].
- Padding (margin) of at least 8 px at 1k and 16 px at 2k. Use `margin_type='EXTEND'`. Mip-mapping eats into the padding, so mobile (lower resolution) needs relatively more [S4]. These numbers are a common rule, UNVERIFIED.
- Bakers that "average normals" ignore the low poly's smoothing [S4]. In Blender, an explicit cage gives the averaged-projection behaviour.

**(e) In bpy:**

```python
cage = low.copy(); cage.data = low.data.copy()
# set every face to smooth on the cage, then add a Displace modifier along normals (strength = extrusion)
bpy.ops.object.bake(type='NORMAL', normal_space='TANGENT', use_selected_to_active=True,
                    use_cage=True, cage_object=cage.name, max_ray_distance=ext*4,
                    margin=16, margin_type='EXTEND')
```

- Blender's bake has no anti-aliasing (UNVERIFIED but widely reported). Bake at 2× resolution and downscale with a Lanczos filter in numpy or Pillow.
- Bake **curvature** for edge wear: put a Geometry Nodes edge-angle attribute (or Cycles "Pointiness") into an emission shader and bake EMIT.
- Bake a **material-ID** map: flat emission colour per material slot from the high poly.
- Bake **AO** for cavity dirt.

**(f) Engines.** Blender bakes OpenGL (+Y) normal maps. UE expects DirectX: set Flip Green Channel on the texture, or flip G at export. Unity uses OpenGL. Both engines use MikkTSpace, as Blender does.

---

## 4. Materials and textures: IDs, wear, trim sheets, decals, emissive

### 4.1 Material IDs and masks (painted metal, rust, wear)
- **(a)** Mechanical assets read as "real" through edge wear, cavity grime and rust streaks. Team or player colours need tint masks.
- **(b)** No topology needed, except separate material slots for glass or canopy (translucent) and for emissive parts if their shader differs.
- **(c)** None.
- **(d)** Maps to produce:
  - Base colour, normal, ORM (UE: R = AO, G = roughness, B = metallic).
  - URP MetallicSmoothness. The repo already does this in `finalize.py`.
  - An RGBA tint/ID mask: R = primary paint, G = secondary, B = trim or metal, A = emissive.
  - Edge wear derived from curvature × noise. Rust and dirt derived from AO cavity × noise × world-up gradient.
- **(e)** Procedural.
  - ID: cluster the baked Tripo colour into K = 3–6 colours with k-means.
  - Wear and rust: masks from curvature, AO and noise in numpy. Expose wear amount and rust amount sliders for the director.
  - AI-generated part: an optional "hero decal" image.
- **(f)** Engines.
  - UE: a master material with tint parameters per mask channel (Material Instance parameters). Brushed metal needs anisotropy, which requires the project setting for anisotropic materials or Substrate (UNVERIFIED for 5.x).
  - Unity URP Lit: use Detail Inputs (detail mask, detail albedo and normal) for tiling micro detail. URP Lit has no anisotropy (UNVERIFIED; HDRP does).

### 4.2 Trim sheets and tiling materials vs unique bakes
- **(a)** Big vehicles and mechs get blurry with one unique 2k–4k bake. Trim sheets and tiling materials keep texel density high and save memory.
- **(b)** Trim workflow: strips of faces UV-mapped to horizontal bands of a shared trim texture. Too many trims look banded ("over-trimming") [S9]. A two-UV setup is common: UV0 for trims or decals, UV1 for unique or tiling detail [S9].
- **(e)** Recommendation for Forge:
  - Keep the unique bake as the default (it carries the AI colour).
  - Add a tiling **detail normal plus roughness** layer from a small procedural library (scratches, brushed metal, cast iron), sampled on UV1 or triplanar. This is procedural.
  - Full trim-sheet remapping from AI meshes is research-grade, so don't automate it. Leave it as optional manual work.

### 4.3 Decals
- **(a)** Logos, warning stripes, panel lines and bolts add detail without unique texels.
- **(b)** Mesh decals are quads floating about 0.1–0.5 mm above the surface, each on its own decal material ID, a technique associated with Star Citizen [S9][S10].
- **(e)** Procedural: project an image (AI-generated or library) onto the surface with a GN raycast, build a conforming quad strip, offset it along the normal, and set an alpha-blended material. The director clicks once for the position.
- **(f)** Engines.
  - UE: Deferred Decal actors or mesh decals with the DBuffer decal material domain.
  - Unity URP: Decal Renderer Feature. On tile-based mobile GPUs, use the Screen Space technique and keep "Use Rendering Layers" off, because it forces a DepthNormal prepass. Projection decals don't work on transparent surfaces [S11].
  - For mobile, prefer baking decals into base colour.

### 4.4 Emissive lights (headlights, LEDs, visors, screens, thrusters)
- **(a)** Gameplay readability and night scenes. Damage states can switch emitters off.
- **(b)** Separate faces or islands, and a separate material if emitters need to animate.
- **(c)** Optional bone or material parameter for blinking. UE light components attach to sockets.
- **(d)** Emissive mask in the ID-mask alpha, or a separate emissive texture. HDR intensity is a material parameter.
- **(e)** Detect bright, saturated, high-value regions in the Tripo colour map: HSV value > 0.9 with a cluster smaller than 3% of the area. Propose them, then the director confirms with a click.
- **(f)** Engines.
  - UE: Emissive Color times a parameter; bloom does the glow; add Spot or Point Light components at sockets for real light.
  - Unity URP: Emission (HDR) on the Lit shader, with bloom in the Volume.

### 4.5 Glass, canopies and lenses
Use a separate material slot.
- UE: Translucent or Thin Translucent.
- Mobile: avoid translucency; use opaque glass with a fake reflection cubemap.
- Detect via Tripo segmentation or a director click.

---

## 5. Robots and mechs: rigid parts, pistons, hydraulics, cables

### 5.1 Rigid part binding
- **(a)** Mechanical parts must not stretch. Default auto-skinning deforms them like flesh. Paint so that "each rigid body part is only using one bone" [S12].
- **(b)** Parts stay as separate pieces: loose parts or Tripo segments. Close the hole at each joint so a part can rotate without showing gaps: add a ball or cylinder "joint cap" mesh (procedural sphere or cylinder at the pivot). Each part keeps its own island set.
- **(c)** Rig.
  - Use the ARP humanoid or quadruped (or a custom chain) for the skeleton.
  - Bind with a **rigid single-bone weight per loose part**: for each part, find the nearest bone segment to the part's centroid, then create one vertex group with weight 1.0.
  - Do this in Forge code instead of ARP auto-skinning. Weights are plain vertex groups, so ARP export still works.
  - ARP's own Bind offers heat maps, Voxelize and Adaptive Auto Skinning [S13]. A dedicated rigid-bind option is UNVERIFIED (none found).
  - Custom (non-ARP) bones must be marked as custom bones to be exported [S13]. The exact ARP mechanism, which I recall as a `cc_` name prefix, is UNVERIFIED.
- **(d)** Same as section 4.1. Joint caps reuse the part material.
- **(e)** Detect parts with `bpy.ops.mesh.separate(type='LOOSE')`. If Tripo fused everything, use Tripo segmentation [S14][S15], or cut at bone joints with a plane bisect plus a fill cap, which the director confirms. Procedural: bone assignment, joint caps, weights.
- **(f)** Engines.
  - UE: one Skeletal Mesh with rigid weights. One draw call per material, with physics asset bodies per part.
  - Unity: either a SkinnedMeshRenderer with 1-bone weights (Quality Settings › Skin Weights can be "1 Bone" on mobile) or a hierarchy of MeshRenderers.
  - Unity's manual recommends one SkinnedMeshRenderer per character [S16]. One practitioner measured a rigid multi-renderer robot about 25% cheaper [S16]. Benchmark before choosing.

### 5.2 Pistons and hydraulics
- **(a)** Pistons that stretch or detach are the classic broken-mech tell.
- **(b)** Two separate meshes, a cylinder and a rod, coaxial, with the rod overlapping inside the cylinder at maximum extension.
- **(c)** Two bones: `piston_cyl_L` is parented to part A and gets a **Damped Track** to `piston_rod_L`'s head. `piston_rod_L` is parented to part B and gets a Damped Track back to the cylinder. Neither bone deforms anything other than its own mesh. Alternative: a single Stretch To constraint only for an elastic sleeve or bellows mesh.
- **(e)** Detect by fitting coaxial cylinders of two radii (a thin one inside a thick one) between two different rigid parts. The constraint setup is procedural. The director confirms the axis.
- **(f)** Constraints don't export.
  - Bake the action at export (the ARP and FBX exporters bake animation).
  - For runtime procedural motion, recreate the constraint in engine. UE: AnimBP "Look At" nodes or a Control Rig Aim. Unity: Animation Rigging "Multi-Aim Constraint". These node names are well known but not verified from docs in this session.

### 5.3 Cables, hoses and wire bundles
- **(a)** Hoses that intersect or stretch break close-ups. Dangling cables add secondary motion.
- **(b)** A tube mesh with even rings along its length (about 6–8 sides AAA, 4 mobile) and enough length segments to bend.
- **(c)** A bone chain (ARP Spline IK limb, or a plain chain with Blender's Spline IK constraint).
  - UE: AnimDynamics or Rigid Body nodes for slack, or the Cable Component plugin for a separate procedural cable.
  - Unity: Damped Transform (Animation Rigging) or a physics bone-chain package.
- **(e)** Detect tubes: a long, thin skeletal shape found by curve-skeleton or PCA, with constant radius. Rebuild procedurally: extract the centreline, then GN Curve to Mesh, then UVs straight along the length (ideal for a tiling hose texture). The director picks the two endpoints if detection fails.

---

## 6. Vehicles

### 6.1 Wheels
- **(a)** Wheels must spin and steer, and in UE they must line up with Chaos wheel bones.
- **(b)** Each wheel is a separate mesh: tyre plus rim, with a brake caliper as a separate mesh that does not spin. Use 16–32 radial segments for AAA and 8–12 for mobile. The pivot sits exactly at the wheel centre.
- **(c)** Rig.
  - Bones: `root`, then the body, then wheel bones such as `wheel_fl`, `wheel_fr`, `wheel_rl`, `wheel_rr`. The names are a Forge choice; UE only needs them to match the Wheel Setups list [S17].
  - The vehicle faces +X in UE [S17].
  - Apply transforms. Clean bone orientation avoids wheels spinning on the wrong axis [S17].
  - Wheels as children of root rather than of the body is suggested by forum reports [S17] (UNVERIFIED).
  - Calipers get a steering-only bone: copy Z rotation from the wheel bone, with no spin.
- **(d)** Tyre rubber (high roughness, tiling tread detail normal), rim metal. A motion-blur disc is optional for high-speed vehicles.
- **(e)** Detect: loose parts or segments whose PCA shows two near-equal large axes and one short axis, sitting near the bottom of the bounding box, two or more of them, roughly symmetric. Find the axle axis from the short PCA axis. Fully procedural. The director confirms front and rear.
- **(f)** Engines.
  - UE5: a Skeletal Mesh, Create Physics Asset on import, Min Bone Size set so wheel bones get bodies [S17].
  - Then a Wheeled Vehicle Pawn with ChaosWheeledVehicleMovementComponent, ChaosVehicleWheel blueprints and an AnimBP with a Wheel Controller node. The node names are UNVERIFIED (the Epic page could not be opened).
  - Unity: a separate WheelCollider GameObject per wheel, apart from the visual wheel mesh [S18]. Raise colliders by half the Suspension Distance [S18]. Sync visuals each frame with `GetWorldPose`. Export wheels as separate objects or bones.

### 6.2 Suspension
- **(a)** Visual suspension arms or springs that don't follow the wheel look broken.
- **(b)** Separate meshes for arms, struts and springs.
- **(c)** Arms get a Damped Track to the wheel bone. Struts use the piston setup from section 5.2. A spring is a coil mesh with a Stretch To bone (it may scale on one axis). Engine-side, these must be AnimBP Look At nodes or Control Rig, since Chaos moves only the wheel bones.
- **(e)** Detection is hard. Suggest a director click on "this part connects wheel to body".

### 6.3 Doors, hatches, hoods, canopies
- **(a)** Interaction (enter, exit) and damage.
- **(b)** A separate mesh with closed backfaces or interior thickness, and the inside visible when open (an interior panel mesh). For a full cabin interior, an AI-generated interior part is needed.
- **(c)** One bone per door with its pivot on the hinge line. A Limit Rotation constraint sets the opening angle.
  - UE: animation, or a Physics Constraint on the door body for loose doors.
  - Unity: a HingeJoint, or an Animator.
- **(e)** Hinge axis: after segmentation, take the boundary edges shared with the body and fit the longest straight segment. That line is the axis candidate. The director clicks to confirm the hinge side.

### 6.4 Turrets
- **(a)** Aiming at runtime.
- **(b)** Separate meshes for the turret ring (yaw) and the gun mantlet and barrel (pitch). Close the gap with a ring skirt.
- **(c)** Bones `turret_yaw` (rotates Z), with child `gun_pitch` (rotates its local axis), plus a `muzzle` bone or socket at the barrel tip. Add limits.
  - UE: AnimBP Transform (Modify) Bone, or Control Rig, driven by the aim target.
  - Unity: a script rotating Transforms, or Multi-Aim.
- **(e)** Detect a cylinder or disc part on top with rotational symmetry. The barrel is a long thin cylinder found by PCA, and its tip gives the muzzle position. Fully procedural, then the director confirms.

### 6.5 Tracks and treads
- **(a)** Tanks and dozers.
- **(b), (c)** Three options [S19]:
  1. **A UV-panned track material** on a continuous belt mesh, with speed from Blueprint or script. Cheapest; best for mobile.
  2. **A skinned ribbon** whose bones sit at the road wheels, so the belt deforms over terrain, plus panning.
  3. **Instanced link meshes along a spline.** Heavy beyond about 100 links [S19].
- **(d)** A tiling tread texture strip; UVs must run straight along the belt.
- **(e)** Procedural: extract the belt centreline, rebuild it with GN Curve to Mesh, and unwrap it straight. The AI tread geometry becomes the baked texture of one link. For AAA hero vehicles, use an array-on-curve of a link mesh.

---

## 7. Weapons

### 7.1 Firearms (slide, bolt, trigger, magazine, hammer, ejection)
- **(a)** Reload and fire animations, and first-person close-ups (the highest texel density in a game).
- **(b)** Separate meshes for: slide or bolt, trigger, hammer, magazine (closed and watertight, because it is dropped), charging handle, selector, bolt catch.
  - The bullets visible in the magazine are a separate small mesh.
  - Scope lens and reticle use separate materials.
- **(c)** A skeletal mesh with bone names such as `root`, `slide`, `trigger`, `hammer`, `magazine`, `bolt`, `charging_handle`.
  - These are a Forge convention. No official cross-studio standard was found (UNVERIFIED).
  - Sockets or helper bones: `Muzzle`, `ShellEject`, `Grip_R`, `Grip_L` (support hand IK target), `Sight` (aim-down-sights camera alignment).
  - Each moving part has one translation or rotation axis with limits.
  - Muzzle sockets reused under the same name across weapons let one Blueprint serve all of them [S20].
- **(d)** Gunmetal or parkerised metal with edge wear from curvature, polymer with micro-texture detail, an emissive or reticle material for sights.
- **(e)** Tripo segmentation separates magazine, trigger and slide reasonably well (UNVERIFIED for small parts). The fallback is a director click to lasso a region, with automatic closing of the cut.
  - Axes: the slide moves along the barrel axis (from PCA of the whole gun). The trigger pivot is a director click.
  - Muzzle: the end of the bore. Detect the bore as a concave cylinder at the barrel end, or by director click.
- **(f)** Engines.
  - UE: a skeletal mesh when parts animate. A static mesh with `SOCKET_<MeshName>_##` empties and `UCX_<MeshName>_##` collision for non-animated weapons [S21].
  - There is a reported bug where a UCX_ object in the same FBX causes socket empties to be ignored [S21]. Export collision in a separate pass or add sockets in UE via Python.
  - Unity: empties export as child Transforms named `Muzzle` and the like.

### 7.2 Melee weapons
- **(a)** Trails, hit detection and hand placement.
- **(b)** Usually one rigid static mesh, with weighted normals or a bevel on the blade edge so it catches the light.
- **(c)** No bones. Sockets: `Grip`, `TrailStart`, `TrailEnd` (blade base and tip). The UE AnimNotifyState Trail takes two socket names (from memory; UNVERIFIED). Chains or flails get a bone chain plus physics.
- **(d)** Blade: low roughness with anisotropic streaks (UE) or a tiling brushed detail (Unity). The edge bevel is brighter in the wear mask.
- **(e)** The blade axis is the longest PCA axis. The grip is the narrow cylindrical section. The tip is the extreme point along the axis. All procedural.

### 7.3 Bows (with string)
- **(a)** The draw animation must bend the limbs and pull the string to the nock point.
- **(b)** Limbs need enough length segments to bend (about 8–12 for AAA). The string is a separate thin mesh, or is regenerated procedurally as a 3–4-sided tube.
- **(c)** Bones:
  - `bow_root` (grip).
  - `limb_upper_01..03` and `limb_lower_01..03`, rotating to bend.
  - `string_top` and `string_bottom` at the limb tips, as children of the last limb bones.
  - `string_nock`, which the hand drives.
  - String vertices are weighted to the nock and the tips, with linear falloff, so the string forms a V shape.
  - An `Arrow` socket sits at the nock.
  - Alternative: a single shape key "draw" for the limbs, driven 0–1 (UE morph target or Unity blendshape).
- **(e)** The bow axis comes from PCA. The string is detected as a thin, nearly straight element joining the two tips, then regenerated procedurally as a GN Curve to Mesh line between the tips. Fully procedural; the director previews the draw pose.

---

## 8. Tools, machinery and gears; drones and rotors

### 8.1 Gears and rotating machinery
- **(a)** Meshing gears that slip look wrong.
- **(b)** A separate mesh per gear, with its pivot on the gear axis.
- **(c)** One bone per gear, with a driver on its rotation: `rot_b = -rot_a * (teeth_a / teeth_b)`. In engine, bake the animation as a loop, or rotate by code (UE RotatingMovementComponent; Unity script).
- **(e)** Detect: a disc-like part (PCA) with high rotational symmetry. Count teeth by sampling the radial distance around the rim and taking the FFT peak. Meshing pairs: rims within a tolerance of touching. All procedural.

### 8.2 Drones and propeller or rotor props
- **(a)** Spinning rotors, plus a motion-blur look at speed.
- **(b)** A separate rotor mesh with its pivot at the hub. Add a procedural blurred-disc mesh (a disc with radial alpha) to swap in at high RPM, using alpha-test on mobile.
- **(c)** A bone `rotor_01..n`. UE: RotatingMovementComponent, or an AnimBP. Unity: a script. Optionally swap the disc via material parameter or mesh visibility.
- **(d)** The disc material: alpha-blended radial streaks (generated procedurally from the blade's baked colour).
- **(e)** Detect thin blade clusters with rotational symmetry above an axis. Hub centre equals the axis. Procedural.

### 8.3 Tools (wrenches, drills, chainsaws)
Static mesh plus sockets, as for melee in section 7.2. Moving bits (drill chuck, chainsaw chain) use the rotor or track-panning approaches above.

---

## 9. Engine export: static vs skeletal, sockets, collision

**UE5:**
- **Choosing the mesh type.** Non-animated props are a Static Mesh, optionally with Nanite. Anything with moving parts is a Skeletal Mesh with rigid weights.
- **Static mesh sockets.** Empties named `SOCKET_<RenderMeshName>_##` [S21].
- **Collision.** `UCX_<RenderMeshName>_##` convex pieces. The name must match exactly, including any `SM_` prefix [S21]. Watch for name changes with the 5.5 Interchange importer [S21].
- **Skeletal mesh sockets.** These are created in the skeleton editor. From Blender, export non-deforming helper bones (`muzzle`, and so on) instead.
- **Nanite.** For AAA vehicles and props, a mid-poly mesh with weighted normals can skip normal bakes [S6]. About 2M triangles is roughly the disk size of a 4k normal map [S6].

**Unity URP (mobile):**
- Rigid hierarchies can stay as separate MeshRenderers (batching or instancing) or a 1-bone SkinnedMeshRenderer [S16].
- Remove unused helper nodes [S16].
- Collision: generate simplified convex hulls in Blender, export them as separate objects, and assign MeshCollider (convex) in an import postprocessor.

**Shared:**
- Apply scale and rotation.
- UE expects +X forward for vehicles [S17].
- Keep pivots at hinges and axles.
- Export animation baked from constraints.

---

## 10. What is procedural, what needs an AI part, and what needs one director click

| Feature | Procedural (bpy, bmesh, GN, numpy) | AI-generated part | Director click |
|---|---|---|---|
| Hard vs organic per part | metrics in section 1 | – | toggle if wrong |
| Hard edges, bevel, weighted normals | yes | – | angle slider |
| Rigid weights and joint caps | yes | – | – |
| Part splitting | loose parts | Tripo segmentation | lasso a missed part |
| Pistons, hoses | rebuild via GN curves | – | confirm the endpoints |
| Wheels, gears, rotors, turrets | cylinder fits, FFT | – | confirm front/axis |
| Door hinges | edge-line fit | car interior (optional) | hinge side |
| Firearm parts and muzzle | axes, muzzle | segmentation helps | trigger pivot, muzzle if missed |
| Bow string | regenerate between tips | – | preview the draw |
| Tracks | belt rebuild, panning | link detail (bake source) | – |
| Wear, rust, ID, tint masks | curvature, AO, k-means | – | intensity sliders |
| Decals | projection plus quad strips | decal image | placement |
| Emissive | HSV detection | – | confirm the regions |
| Sockets, UCX collision | yes | – | – |

---

## Sources
- [S1] BlenderArtists, Quad Remesher thread (hard edges vs normals splitting): https://blenderartists.org/t/quad-remesher-auto-retopologizer/1170913?page=31
- [S2] Rhino QuadRemesh docs (30° hard-edge threshold): https://docs.mcneel.com/rhino/8/help/en-us/commands/quadremesh.htm
- [S3] QuadRemesher 1.3 user doc (unreachable here): https://www.exoside.com/quadremesherdata/QuadRemesher_1.3_UserDoc.pdf
- [S4] Polycount discussions (hard edges and UV splits, padding, averaged normals, vertex cost): https://polycount.com/discussion/comment/2767232/ , https://polycount.com/discussion/comment/1689464 , https://polycount.com/discussion/comment/2351926
- [S5] 80.lv, "Creating assets within the mid-poly workflow in UE5": https://80.lv/articles/creating-assets-within-the-mid-poly-workflow-in-ue5/
- [S6] UE forums, Nanite and normals: https://forums.unrealengine.com/t/uvs-and-nanite/231247/9 , https://forums.unrealengine.com/t/best-game-mesh-approach-for-fp-weapon-nanite-meshes/2723107 , https://forums.unrealengine.com/t/nanite-offline-displacementmaps-normal/2715782
- [S7] Blender manual, Weighted Normal modifier: https://docs.blender.org/manual/en/5.1/modeling/modifiers/normals/weighted_normal.html
- [S8] Blender 4.1 release notes, Modeling (Auto Smooth becomes a modifier): https://developer.blender.org/docs/release_notes/4.1/modeling/ ; Smooth by Angle: https://docs.blender.org/manual/en/4.2/modeling/modifiers/normals/smooth_by_angle.html
- [S9] Trim sheets and decals: https://www.patreon.com/posts/lets-talk-about-94999921 , https://polycount.com/discussion/155894/decal-technique-from-star-citizen
- [S10] 80.lv, sci-fi production guide (mesh decals): https://80.lv/articles/007gai-sci-fi-environment-production-guide/
- [S11] Unity URP Decal Renderer Feature reference: https://docs.unity3d.com/Manual/urp/renderer-feature-decal-reference.html
- [S12] UE forum, rigid skinning of a mechanical mesh: https://forums.unrealengine.com/t/rig-skin-of-mechanical-mesh/1417178/2
- [S13] Auto-Rig Pro product page and changelog: https://superhivemarket.com/products/auto-rig-pro/versions
- [S14] Scenario, Tripo Segmentation essentials: https://help.scenario.com/articles/9861107995-tripo-segmentation-the-essentials
- [S15] Tripo blog, splitting a model into parts: https://www.tripo3d.ai/blog/auto-split-model-into-parts
- [S16] Unity manual, optimized characters: https://docs.unity3d.com/2021.1/Documentation/Manual/ModelingOptimizedCharacters.html ; Unity discussion, rigid vs skinned: https://discussions.unity.com/t/performance-of-non-deforming-skinned-mesh-versus-multiple-mesh-renderers-like-robot-or-turret/246364
- [S17] UE vehicle art setup and Chaos conversion (summaries only): https://dev.epicgames.com/documentation/en-us/unreal-engine/vehicle-art-setup-in-unreal-engine , https://dev.epicgames.com/documentation/en-us/unreal-engine/how-to-convert-physx-vehicles-to-chaos-in-unreal-engine ; wheel axis thread: https://forums.unrealengine.com/t/chaos-vehicles-vehiclemovement-component-wheel-setup-problem/768602/2
- [S18] Unity WheelCollider tutorial and reference: https://docs.unity3d.com/Manual/WheelColliderTutorial.html , https://docs.unity3d.com/Manual/class-WheelCollider.html
- [S19] UE forums, tank tracks: https://forums.unrealengine.com/t/how-to-create-tank-treads/1137117 , https://forums.unrealengine.com/t/need-input-rigging-tank-tracks-with-bones/106629
- [S20] UE forum, muzzle socket: https://forums.unrealengine.com/t/how-can-i-spawn-a-bullet-at-the-tip-of-the-rifle/1716499
- [S21] UE FBX Static Mesh pipeline (SOCKET_ and UCX_): https://dev.epicgames.com/documentation/en-us/unreal-engine/fbx-static-mesh-pipeline-in-unreal-engine ; UCX/socket bug: https://forums.unrealengine.com/t/unreals-socket-import-for-fbx-files-is-broken-workaround/2303521 ; 5.5 Interchange UCX issue: https://forums.unrealengine.com/t/ucx-collisions-not-importing-with-lods-in-unreal-engine-5-5/2382620

