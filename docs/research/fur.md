# Research: fur (fact-checked)

FACT-CHECKED REPORT: FUR / HAIR CARDS (Forge, Blender 5.3)

How I checked: docs.blender.org, dev.epicgames.com and docs.unity3d.com do not resolve in this sandbox. To use them, they must be allowed in the session's network settings. To get around that, I read the Blender source directly from the GitHub mirror at raw.githubusercontent.com/blender/blender, branch **blender-v5.3-release**, which is primary evidence for 5.3. I also read the Unity URP source (Unity-Technologies/Graphics master), the UnityCsReference source, and the Auto-Rig Pro source in the scratchpad (version 3.77.33, not 3.79.17). Epic facts come from search snippets of the Epic docs.

Tags: CONFIRMED (checked in source or docs), CORRECTED (the original claim was wrong or out of date), UNVERIFIED (not checked).

======================================================================
A. CORRECTIONS THAT CHANGE THE CODE (read these first)
======================================================================
1. CORRECTED: on a Curves object, `bpy.data.meshes.new_from_object()` does NOT work. In 5.3, `BKE_mesh_new_from_object` only handles OB_FONT, OB_CURVES_LEGACY, OB_SURF, OB_MBALL and OB_MESH. For anything else it returns nullptr ("Object does not have geometry data"). Use one of these instead:
   (a) `bpy.ops.object.convert(target='MESH')` on the Curves object. CONFIRMED: `convert_curves_to_mesh` in object_add.cc takes the evaluated mesh from the geometry set (`geometry.get_mesh()`), keeps non-anonymous attributes, and calls `mesh_ensure_active_uv_map`. If the result is curves only, it gives a wire mesh.
   (b) Put the card GN modifier on a MESH carrier object that reads the curves through an Object Info node. Then `new_from_object(obj.evaluated_get(dg))` works.
   Do not rely on `modifier_apply` on a Curves object whose GN output is a mesh (UNVERIFIED; use (a)).
2. CORRECTED: several node "modes" in 5.x are now Menu input SOCKETS, not node properties. In 5.3 source:
   - Set Curve Normal has `inputs["Mode"]`, a Menu socket whose items are `rna_enum_curve_normal_mode_items` = 'MINIMUM_TWIST', 'Z_UP', 'FREE' (identifiers CONFIRMED in rna_curves.cc). The "Normal" input is used only when Mode is FREE.
   - Resample Curve has `inputs["Mode"]`, a Menu socket with "COUNT" and so on, plus inputs "Count" and "Length".
   So `node.mode = 'FREE'` is wrong. Use `node.inputs['Mode'].default_value = 'FREE'`. Whether `default_value` takes the identifier 'FREE' or the UI name 'Free' is UNVERIFIED, because menu items are resolved at runtime through `RNA_node_socket_menu_itemf`. Try the identifier first and fall back to the name inside a try/except.
   Still node properties (CONFIRMED): Distribute Points on Faces `distribute_method` ('POISSON'; inputs "Distance Min", "Density Max", "Density Factor", "Seed", "Selection"), and Store Named Attribute `data_type` / `domain`. Random Value has `data_type` plus inputs "ID" and "Seed" (CONFIRMED).
3. CONFIRMED, and a better result than the report claimed: in Set Curve Normal FREE mode the node writes the point attribute `custom_normal`. Curve to Mesh builds every profile ring from `evaluated_normals()`, and the source notes that "Normal and tangent may not be orthogonal in case of custom normals". So in 5.3 FREE normals DO drive Curve to Mesh orientation, and the tilt fallback is not needed.
4. CORRECTED: Curve to Mesh in 5.3 has the inputs Curve, Profile Curve, **Scale** (float field, default 1.0, "Scale of the profile at each point"), Fill Caps, and a "Miter Scale" panel (Miter Scale bool and Miter Scale Limit angle, default 135°). Point radius is not read. Drive width through **Scale** and drop the "Set Curve Radius" alternative. Curve to Mesh makes no UVs: CONFIRMED, there is no UV code in node_geo_curve_to_mesh.cc.
5. CORRECTED: Blender 5.x render output. `image_settings` now has `media_type` ('IMAGE' | 'MULTI_LAYER_IMAGE' | 'VIDEO'). Set `scene.render.image_settings.media_type = 'MULTI_LAYER_IMAGE'` BEFORE `file_format = 'OPEN_EXR_MULTILAYER'`, or the enum assignment can fail. CONFIRMED in rna_scene.cc 5.3.
6. CORRECTED and important for the Groom tier: in the **5.3** Alembic curves writer (abc_writer_curves.cc), generic Curves attributes are exported as arbGeomParams (`create_geom_param_for_attribute`). Names starting with '.', anonymous attributes and built-ins (position, radius, resolution, id, cyclic, curve_type, normal_mode, handles, knots_mode and others) are skipped. The 4.2, 4.5, 5.0, 5.1 and 5.2 release branches do NOT do this: I diffed all six branches. So in 5.3 you can write Curves attributes named `groom_width`, `groom_group_id`, `groom_root_uv` and `groom_guide` directly, and they should reach UE without the third-party exporter. How Blender maps CURVE domain to Alembic scope (UE wants constant or uniform for group id) is UNVERIFIED, so test one file in UE.
   Width: Blender writes the native Alembic widths as radius×2 (constant scope if all are equal, otherwise per vertex). CONFIRMED. UE falls back to 1 cm "if no groom_width attribute is specified, or one couldn't be converted from width values". So write an explicit `groom_width` in cm (Epic docs snippet).

======================================================================
B. SECTION-BY-SECTION VERDICTS
======================================================================
§0 Pipeline: sound. One addition: the GN card generator should live on a mesh carrier object or be converted with `object.convert` (see A1).

§1.1 Budgets: UNVERIFIED as standards. The figures are practitioner and marketplace numbers, which the report already says.

§1.2 GN cards
- `bpy.data.node_groups.new(name,'GeometryNodeTree')` and `ng.interface.new_socket(...)`: CONFIRMED (standard 4.x/5.x API).
- GeometryNodeResampleCurve: CORRECTED. Mode is a Menu socket (A2). Count is an input socket.
- Sample Nearest Surface / Sample UV Surface, then Capture Attribute (domain CURVE): plausible. Exact Capture Attribute property names were not checked in 5.3 (UNVERIFIED).
- Set Curve Normal FREE: CORRECTED/CONFIRMED (A2, A3).
- Curve to Mesh Scale: CONFIRMED (A4).
- UVs: store FLOAT2 on CORNER. The 'FLOAT2' and 'BYTE_COLOR' enum identifiers are CONFIRMED in rna_attribute.cc. In 5.x a UV map is a FLOAT2 CORNER attribute: CONFIRMED by practice and the cited forum. `convert` calls `mesh_ensure_active_uv_map`, so store 'UVMap' first so it becomes the active UV map. Order of 'UVMap' then 'UVRoot' in FBX: UNVERIFIED; check `mesh.uv_layers` after conversion.
- DataTransfer: CONFIRMED in rna_modifier.cc 5.3: `data_types_loops={'CUSTOM_NORMAL'}`, `loop_mapping='POLYINTERP_NEAREST'` (also 'POLYINTERP_LNORPROJ'), `data_types_verts={'VGROUP_WEIGHTS'}`, `vert_mapping='POLYINTERP_NEAREST'`, `layers_vgroup_select_src` / `_dst`. Set `use_loop_data=True` and `use_vert_data=True`.
- Hair Info shader node outputs: CONFIRMED (5.3): Is Strand, Intercept, Length, Thickness, Tangent Normal, Random.

§1.3 Skinning and chain bones: approach CONFIRMED as reasonable. ARP: `bpy.ops.arp.add_limb(limbs_presets=...)` takes 'tail', 'ears', 'spline_ik' ("Chain: Spline IK"), 'bbones' ("Chain: Bendy Bones"), 'kilt', 'breast', 'spine' and 'head', plus custom-limb presets with the suffix "_customlimb". This is CONFIRMED in the ARP 3.77.33 source (auto_rig.py, `ARP_OT_add_limb.limbs`). The required mode/context and whether 3.79.17 differs are UNVERIFIED. Use 'spline_ik' for manes and long tufts, 'tail' for tails, and 'ears' for ears. This links to the extra-body-part rigging request.

§1.4 Tatter/fin strips: an algorithm, not an API. `BMEdge.is_boundary` is CONFIRMED (standard bmesh).

§1.6 Colour through UVRoot: sound. `mesh.color_attributes.new(name,'BYTE_COLOR','POINT')`: CONFIRMED signature (name, type, domain).

§2 UE5 Groom
- `bpy.ops.wm.alembic_export` parameters in 5.3, CONFIRMED from io_alembic.cc: filepath (filesel), start, end, xsamples, gsamples, sh_open, sh_close, `selected` ("Selected Objects Only", default False), flatten, collection (hidden), uvs, packuv, normals, vcolors, orcos, subdiv_schema, apply_subdiv, curves_as_mesh, use_instancing, global_scale, triangulate, quad_method, ngon_method, export_hair, export_particles, export_custom_properties, as_background_job, evaluation_mode ('RENDER' | 'VIEWPORT'), init_scene_frame_range.
  `export_hair` applies to legacy hair particle systems only. New Curves objects export as curves unless `curves_as_mesh=True`, so keep that False. Pass `as_background_job=False` for deterministic scripting.
- Curve types: CONFIRMED in the writer. POLY maps to kLinear, CATMULL_ROM to kLinear with CatmullRom basis, BEZIER to kCubic with Bezier basis, and NURBS is handled too. Use POLY plus resampling before export so UE gets plain linear strands.
- groom_* schema: CONFIRMED from Epic snippets. groom_root_uv is optional (UE uses spherical mapping if it is missing). groom_group_id is int32 constant, with a limit of 15 per groom (MetaHuman exporter doc). The groom_width fallback is 1 cm, and an explicit groom_width is not overwritten. Properties must be lowercase with the `groom_` prefix. Only curves tagged groom_guide are used for simulation. The values groom_version_major/minor = 1/5 are UNVERIFIED (not found in snippets). Sources: https://dev.epicgames.com/documentation/en-us/unreal-engine/using-alembic-for-grooms-in-unreal-engine , https://dev.epicgames.com/documentation/en-us/metahuman/groom-exporter , https://dev.epicgames.com/documentation/en-us/unreal-engine/xgen-guidelines-for-hair-creation-in-unreal-engine
- Skin cache: CONFIRMED. Project Settings > Rendering > Optimizations > "Support Compute Skin Cache", then restart the editor. Binding to a skeletal mesh is greyed out without it. Source: https://dev.epicgames.com/documentation/unreal-engine/setting-up-a-project-for-grooms-in-unreal-engine . Forums say the groom must not be a child of the skeletal mesh (anecdotal).
- Platform: CONFIRMED. Groom Cards and Meshes work on all platforms. Strands do not run on mobile (Epic staff, UE 5.4). Skinned attachment and RBF global interpolation are unsupported on mobile. One LOD can contain both strands and cards so UE can switch between them. Source: https://dev.epicgames.com/documentation/en-us/unreal-engine/groom-platform-support-in-unreal-engine
- Hair Card Generator: CONFIRMED as experimental. The API option `bReduceCardsFromPreviousLOD` sits in FCardsGenerationAdvancedOptions (HairCardGeneratorEditor), and a Dataflow variant exists (FGroomAdvancedGenerationSettings). Driving it from Python is UNVERIFIED. Source: https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Plugins/HairCardGeneratorEditor/FCardsGenerationAdvancedOptions
- LOD "Geometry Type" Strands/Cards/Meshes: CONFIRMED.
- global_scale applied in one place only: still good advice. Whether `global_scale` also scales the Alembic widths is UNVERIFIED, so write groom_width in cm yourself.

§3 Shells and fins: the cited references are general (Arm best practices). No API claims needed checking.

§4 Blender hair curves API
- `bpy.data.hair_curves.new(name)`: CONFIRMED (rna_main "hair_curves"). Do NOT use `bpy.data.curves`, which holds legacy curves.
- Curves properties: CONFIRMED (5.3): surface, surface_uv_map, position_data, curve_offset_data, normals, points, curves, materials, use_mirror_x/y/z, selection_domain, use_sculpt_collision, surface_collision_distance.
- Curves functions: CONFIRMED in rna_curves_api.cc: `add_curves(sizes)`, `remove_curves(indices=)`, `resize_curves(sizes, indices=)`, `reorder_curves(new_indices)`, `set_types(type='CATMULL_ROM' default, indices=)`. The report did not mention reorder_curves.
- Operators: CONFIRMED. `object.curves_empty_hair_add`, `object.curves_random_add`, `curves.snap_curves_to_surface(attach_mode='NEAREST'|'DEFORM')` (DEFORM requires unchanged surface topology), `curves.surface_set`, `curves.convert_to_particle_system`, `curves.convert_from_particle_system`, plus curve_type_set, subdivide, switch_direction and others.
- Essentials hair asset file: the file name `procedural_hair_node_assets.blend` is CONFIRMED (blender-assets repo, publish/geometry_nodes/). The install path `<ver>/datafiles/assets/geometry_nodes/` is UNVERIFIED, so keep the glob, matching `*hair*`. Node-group and socket names: UNVERIFIED; enumerate `data_from.node_groups`.
- `cycles_curves.shape`: CONFIRMED (5.3 Cycles properties.py) as 'RIBBONS' (default), 'THICK' or 'THICK_LINEAR', plus `subdivisions`. For the flat ortho atlas, 'THICK' or 'RIBBONS' both work. RIBBONS is faster and camera-facing.
- AOVs: `ShaderNodeOutputAOV.aov_name` CONFIRMED, with inputs Color and Value. `film_transparent`: CONFIRMED. EXR: CORRECTED (A5).

§5 Mip coverage
- Unity: `TextureImporter.mipMapsPreserveCoverage` and `alphaTestReferenceValue` CONFIRMED (UnityCsReference TextureImporter.bindings.cs). `mipMapBias` also exists.
- UE: there is still no documented "preserve coverage" option. Community fixes are a negative mip bias in the sampler, hand-authored mips, or a higher clip value (forums: https://forums.unrealengine.com/t/hair-fading-out-with-distance/113832). Remains UNVERIFIED.

§6 Engine materials
- Unity URP Lit property names: CONFIRMED from Lit.shader: `_Surface` (0 = Opaque), `_AlphaClip`, `_Cutoff` (default 0.5), `_Cull` (default 2 = Back, so set 0 for Both), `_Blend`, keyword `_ALPHATEST_ON`. Render queue AlphaTest = 2450, with RenderType "TransparentCutout".
  When you set these from script, you must also set the keyword, the queue and `_AlphaToMask` yourself, because the ShaderGUI sets them only through the inspector (BaseShaderGUI.SetMaterialKeywords).
- CORRECTED: "Alpha-to-coverage needs a custom AlphaToMask pass; Shader Graph does not expose it" is out of date (it comes from a 2020 thread). Current URP Lit has `_AlphaToMask` and `AlphaToMask[_AlphaToMask]`. BaseShaderGUI sets it to 1 automatically for Opaque with Alpha Clipping on. Shader Graph UniversalTarget adds `AlphaToMask` to passes when Alpha Clipping is on. It only has an effect when MSAA is on, and URP warns about the extra cost with MSAA. The URP version that introduced this is UNVERIFIED, so check the user's URP package. Source: https://github.com/Unity-Technologies/Graphics/blob/master/Packages/com.unity.render-pipelines.universal/Editor/ShaderGUI/BaseShaderGUI.cs
- UE material: Masked, Two Sided, Hair or Default Lit, DitherTemporalAA, PDO. These are standard but not re-verified; the "Dither Opacity Mask" checkbox name is UNVERIFIED. Masked cards on mobile UE work (cards are supported on all platforms). One forum report says the hair material did not show on an Android device: https://forums.unrealengine.com/t/can-groom-hair-cards-be-used-on-mobile-devices/1324918 . For the Forge FBX path, use Default Lit Masked on mobile.

§7 Pitfalls: add these.
- `new_from_object` returns None for Curves objects (A1).
- Menu-socket modes in 5.x (A2).
- EXR media_type in 5.x (A5).
- Only Blender 5.3+ writes custom groom_* attributes to Alembic; on older versions use the Groom Exporter add-on (A6).
- UE reads UV and width only from groom_* names. Blender's own `surface_uv_coordinate` attribute is exported but UE ignores it, so copy it to `groom_root_uv`.
- The `custom_normal` attribute (FREE mode) appears in the converted mesh's attributes and would export as a generic attribute. Remove it after conversion (UNVERIFIED whether convert keeps it).
- "Curves objects export to FBX as nothing": still UNVERIFIED but likely. Keep the convert step either way.

UNVERIFIED (remaining):
- The format of a menu socket's `default_value` (identifier or name).
- How Alembic maps CURVE domain to scope.
- groom_version values.
- Whether global_scale affects widths.
- The Essentials install path and node-group/socket names.
- Capture Attribute property names in 5.3.
- ARP 3.79.17 differences from 3.77.33.
- The UE mip-coverage option and the Dither Opacity Mask name.
- Hair Card Generator Python automation.
- All budgets.
- The groove-direction method (novel).

Blender source files read (blender-v5.3-release): makesrna/intern/rna_curves.cc, rna_curves_api.cc, rna_scene.cc, rna_modifier.cc, rna_attribute.cc, rna_main.cc, rna_node_socket.cc; editors/io/io_alembic.cc; io/alembic/exporter/abc_writer_curves.cc; nodes/geometry/nodes/node_geo_set_curve_normal.cc, node_geo_curve_to_mesh.cc, node_geo_curve_resample.cc, node_geo_distribute_points_on_faces.cc; blenkernel/intern/mesh_convert.cc, curve_to_mesh_convert.cc; editors/object/object_add.cc; editors/curves/intern/curves_ops.cc; nodes/shader/nodes/node_shader_hair_info.cc, node_shader_output_aov.cc; intern/cycles/blender/addon/properties.py. All are under https://github.com/blender/blender/tree/blender-v5.3-release/

Asset-file source: https://projects.blender.org/blender/blender-assets/pulls/8/files . Local copies of the source files are in /tmp/claude-0/-home-user-Image-to-Game-asset/f1ff8269-309f-546b-b536-494e8126b836/scratchpad/fur_v/
