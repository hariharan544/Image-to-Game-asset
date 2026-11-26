# Research gap: Automated engine-side assembly and validation

# Forge: building and checking assets inside Unreal 5 and Unity without anyone at the keyboard

**Research limits.**
- The shared web-search budget for this run was used up before my first query, so I searched no further.
- dev.epicgames.com and docs.unity3d.com do not resolve from this session, so I could not check the official API pages. To check them in a later run, someone has to allow both hosts in the session's network settings.
- Instead I checked API names against GitHub: public source code that calls these APIs, Unity's own C# reference source, and Haxe bindings generated from the UE 5.2 headers. GitHub code search and raw file fetches worked.
- A name confirmed in a real call site or a header is marked [V]. Anything else that is not common knowledge is marked UNVERIFIED.
- Repo context I read: `/home/user/Image-to-Game-asset/blender_scripts/forge_bpy/finalize.py` already writes these files:
  - Unreal: `SK_<asset>.fbx` or `SM_<asset>_<part>.fbx`, plus textures `T_<asset>_<part>_BC/_N/_ORM.png` with the normal map's green channel flipped for DirectX.
  - Unity: `<asset>_<part>_BaseMap/_Normal/_MetallicSmoothness/_Occlusion.png`.
  - Mesh objects named `<part>_LOD0…` and an ARP export (Mannequin bone names for Unreal, Humanoid for Unity).

  The engine-side setup below picks up from those files.

---

## 0. Overall design (applies to every feature below)

1. **Blender writes a sidecar file, `forge_manifest.json`, next to each FBX.** It is the single description of the asset for both engines. Contents:
   - asset name, archetype (humanoid / quadruped / mech / prop) and tier (AAA / mobile);
   - the list of meshes with their LODs and triangle counts;
   - material slots, each with a *material kind* (opaque, masked, skin, eye, cornea, hair, emissive, metal) and its texture paths;
   - tint-mask channel meanings;
   - sockets (name, bone, location and rotation);
   - collision hints (bone, capsule radius and length);
   - morph target names, and driver rules such as `{driver: "lowerarm_l", axis: "Y", from: 0, to: 90, target: "corr_elbow_l_90"}`;
   - eyelid follow ratios, look-at bones, and AnimDynamics chains (tail, ears, antennae, cables);
   - budgets, and the camera framing used for the Blender preview, so the engine shots can be compared like for like.

   Why a sidecar file and not only FBX custom properties: Unity *can* read FBX user properties (`OnPostprocessGameObjectWithUserProperties(GameObject, string[] propNames, object[] values)` [V, UnityCsReference IModelImporterBlock.cs; Unity's FPSSample SkeletonImporter.cs]). Unreal has no equally simple path (FBX metadata import is UNVERIFIED and the Interchange equivalent is unclear). Do both:
   - Blender: export with `use_custom_props=True`;
   - write the JSON file regardless;
   - the engine scripts read the JSON.

2. **One command per engine, run from Forge's `pipeline.py` after the Blender export step:**
   - **Unreal, import and setup, no rendering needed:**
     `UnrealEditor-Cmd.exe Forge.uproject -run=pythonscript -script="forge_ue_import.py --manifest <path>" -unattended -nop4 -nosplash -stdout`
     This mode runs without a GPU renderer (null RHI), so it cannot take screenshots.
   - **Unreal, screenshots and turntable, needs the GPU:** run the full editor with
     `UnrealEditor.exe Forge.uproject -ExecutePythonScript="forge_ue_review.py <manifest>" -unattended -nosplash`
     or render the turntable directly from the command line with Movie Render Queue (MRQ) (see U10).
   - **Alternative while the editor is open:** Python remote execution, the same mechanism as Epic's "Send to Unreal" Blender add-on. It uses `remote_execution.RemoteExecution()`, `.start()`, `.open_command_connection(node_id)` and `.run_command(code, unattended=…)`, with the default port 9998 [V, poly-hammer/BlenderTools send2ue `dependencies/unreal.py`]. Turn on Project Settings > Python > Enable Remote Execution. This lets the Blender add-on push a job into a running editor.
   - **Unity:**
     `Unity.exe -batchmode -projectPath <P> -executeMethod Forge.Editor.ForgeBuild.Run -forgeManifest <path> -logFile <log>`
     Leave out `-quit` and call `EditorApplication.Exit(code)` yourself, so a failed check returns a non-zero exit code. Leave out `-nographics` when screenshots are needed.

3. **Every step writes `engine_report.json`:** a pass/fail list of check results, plus paths to the screenshots. Forge shows these to the director next to the Blender preview.

---

## 1. Naming conventions

**(a) Why it matters.** Validation rules, material binding and LOD discovery all depend on names. Consistent prefixes also make the Content Browser and Project window filterable.

**(b)–(d) The conventions.** Allar's style guide, v2 (UE5) branch [V, github.com/Allar/ue5-style-guide/tree/v2]:

| Asset | Prefix |
|---|---|
| Skeletal mesh | `SK_` |
| Static mesh | `S_` (the guide notes "Many use SM_. We use S_.") |
| Skeleton | `SKEL_` |
| Physics asset | `PHYS_` |
| Material | `M_` |
| Material instance | `MI_` |
| Texture | `T_` |
| Animation blueprint | `ABP_` |
| Control Rig | `CR_` |
| Animation sequence | `A_` (UE4 table) |
| Blend space | `BS_` |
| Montage | `AM_` |
| Material function | `MF_` |

- Texture suffixes: `_D` (colour), `_N`, `_R`, `_A`, `_O`, `_B`, `_E`, `_S` and `_M`. The guide gives `_M` to both Mask and Metallic, so it conflicts with itself.
- Packed textures stack the letters, e.g. `_ERO`. The guide advises against four-channel packing, except opacity in the colour texture's alpha.
- Folders: put everything under `Content/<Project>/…`, use PascalCase, and avoid folders named `Meshes`, `Textures` or `Materials` [V, Allar].

**Recommended Forge convention.** Keep `SM_`, which Forge already uses and Epic's own sample content mostly uses; record it as a deliberate departure from Allar's `S_`.
- Folder: `/Game/Forge/Characters/<Asset>/`
- Meshes and rig: `SK_<Asset>`, `SKEL_Forge_<Archetype>` (shared), `PHYS_<Asset>`
- Materials: `MI_<Asset>_<Slot>`, child of the masters `M_Forge_{Opaque,Masked,Skin,Eye,Cornea,Hair,Emissive}`
- Textures: `T_<Asset>_<Slot>_{BC,N,ORM,TM(tint mask),EM(emissive mask),DN(detail normal)}`. Prefer the existing `_BC`/`_ORM` over Allar's `_D`, because ORM is the established Unreal channel order (Occlusion, Roughness, Metallic).
- Animation and rig: `ABP_Forge_<Archetype>`, `ABP_Forge_<Archetype>_PP`, `CR_Forge_<Archetype>_Face`, `IK_<Asset>`, `RTG_Manny_to_<Asset>`
- Review: `LS_Review_<Asset>`, `L_Forge_Review`

These IK, retargeter and review prefixes are not in Allar's guide; they follow the common community pattern (UNVERIFIED as a standard).
- **Unity:** the same names with no `SK_` prefix (Forge currently exports Unity files without a prefix; that is fine). Prefab `PF_<Asset>`, material `MAT_<Asset>_<Slot>` (prefix UNVERIFIED as a standard). Keep the `_LOD0.._LODn` suffixes; Unity relies on them.

**(e) Automation.** A shared `naming.py` produces every name, in both Blender and the engine scripts, from the manifest. Validation rule V1 (section 3) enforces it.

**(f) Engine notes.** Unreal turns `.` and spaces in names into `_`. Make Blender bone and shape-key names identifier-safe already (`[A-Za-z0-9_]`).

---

## 2. Unreal Engine 5 (AAA)

### U1. Importing the FBX (Interchange vs the legacy FBX importer)

**(a) Why.** The import settings decide which skeleton the mesh uses, whether morph targets come in, how normals are treated, and whether a physics asset is created. Most broken-looking imports come from here.

**(b)–(d) What the FBX must contain.**
- Smoothing/normals exported (Blender `mesh_smooth_type='FACE'` or tangent space).
- Shape keys present.
- Armature object not named "Armature". Forge already handles this: UE drops a top node named "Armature" instead of adding a root bone.

**(e) Script.** Check which importer is active: `unreal.SystemLibrary.get_console_variable_string_value('Interchange.FeatureFlags.Import.FBX')` [V, send2ue]. Then use one of two paths.

- **Interchange path** [V, OpenDCAI/GameFactory-3A `import_mesh.py`; xavier150 Blender-For-UnrealEngine]:
  ```python
  mgr = unreal.InterchangeManager.get_interchange_manager_scripted()
  src = unreal.InterchangeManager.create_source_data(fbx_path)
  params = unreal.ImportAssetParameters()
  params.set_editor_property("is_automated", True)
  pipe = unreal.InterchangeGenericAssetsPipeline()   # or duplicate /Interchange/Pipelines/DefaultAssetsPipeline
  # sub-pipelines: pipe.mesh_pipeline, plus animation/texture/material sub-pipelines
  params.set_editor_property("override_pipelines", [unreal.SoftObjectPath("/Game/Forge/Pipelines/PL_ForgeCharacter")])
  mgr.import_asset("/Game/Forge/Characters/Bull", src, params)
  ```
  - Store a Forge pipeline *asset* rather than building one in code. Copy DefaultAssetsPipeline once in the editor and set: skeletal meshes on, morph targets on, physics asset creation on, material import off (Forge builds the MIs itself), texture import off.
  - The individual sub-pipeline property names (`import_morph_targets`, `create_physics_asset`, `skeleton`) are UNVERIFIED for Python. Read them from `dir(pipe.mesh_pipeline)` in the user's UE version and cache them.
  - Interchange also supports **Python pipelines**: subclass `unreal.InterchangePythonPipelineBase` and override `scripted_execute_pipeline`. The class exists [V, UE header `InterchangePythonPipelineBase.h` on a GitHub mirror]; the override name is UNVERIFIED. This is the place to rename assets and assign the skeleton inside the import itself.
- **Legacy path** [V, send2ue]:
  - `task = unreal.AssetImportTask()` with `filename`, `destination_path`, `replace_existing`, `replace_existing_settings`, `automated=True`;
  - `opts = unreal.FbxImportUI()` with `automated_import_should_detect_type=False`, `import_mesh`, `import_as_skeletal`, `mesh_type_to_import=unreal.FBXImportType.FBXIT_SKELETAL_MESH`, `import_materials=False`, `import_textures=False`, `import_animations`;
  - `opts.skeleton = unreal.load_asset(SKEL path)`; `opts.create_physics_asset=True`, or `False` plus `opts.physics_asset = template`;
  - `opts.skeletal_mesh_import_data = unreal.FbxSkeletalMeshImportData()` (its `import_morph_targets` / `import_mesh_lo_ds` fields; `import_mesh_lo_ds` is [V]);
  - `unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])`.
- **Hook for anything else imported by hand:** `unreal.get_editor_subsystem(unreal.ImportSubsystem).on_asset_post_import.add_callable(fn)` [V, Ryan-DowlingSoka/UnrealImporterRules-Python; FXTD Unreal-PyToolkit]. This gives "importer rules", the Unreal counterpart of Unity's AssetPostprocessor.

**(f)** Pin the Unreal version in `forge.yaml`. Unreal's Python names drift between versions; one public repo notes `k2_*` override names for EditorValidatorBase "in 5.8". At startup, check that every API call the script uses exists (`hasattr`), and fail with a clear message if one is missing.

### U2. Skeleton strategy (shared skeleton per archetype)

**(a) Why.** A shared skeleton lets one AnimBP, one Control Rig and one animation library serve every generated creature.

**(b)/(c) Requirements.** ARP already exports Unreal Mannequin bone names for humanoids. Create `SKEL_Forge_Humanoid` once (from Manny, or from the first ARP export), then import every humanoid with `opts.skeleton = SKEL_Forge_Humanoid`.
- When a mesh brings extra bones (eyelids, jaw, tail, ears), Unreal **adds the missing bones to the shared skeleton** as long as the existing hierarchy matches. That is the documented behaviour of importing onto an existing skeleton (UNVERIFIED for Interchange).
- Different body proportions: set bone translation retargeting to `Skeleton` for root/pelvis and `AnimationScaled` / `Skeleton` elsewhere (UNVERIFIED that this is scriptable; the property lives on the Skeleton's bone tree).
- Quadrupeds and mechs: one `SKEL_Forge_<Archetype>` each.

**(e)** If an import fails because the hierarchy does not match, fall back to a separate skeleton for that asset and generate an IK Rig plus a retargeter from Manny (U8).

### U3. Physics asset (PHYS_)

**(a) Why.** Ragdoll, hit reactions, physical animation, AnimDynamics/RigidBody collision, and accurate per-bone hit detection.

**(b)** It needs proper bone volumes. AI meshes with fur or attached props produce oversized auto-generated capsules.

**(c) Two options.**
1. Create it on import (`create_physics_asset=True`). Unreal fits one capsule per bone above a minimum size.
2. **Template (recommended):** one `PHYS_Forge_Humanoid` tuned once by hand, assigned with `opts.physics_asset = template` and `create_physics_asset=False` [V, send2ue `set_physics_asset`]. Bones that don't match are ignored.

Python cannot reliably edit body shapes (the BodySetup aggregate geometry). Re-running "generate bodies" with custom settings has no public Python API (UNVERIFIED). If per-asset capsule fitting is required, the options are a small C++ editor function library (`ForgeEditorLib`) exposed to Python, or writing per-bone radii into the manifest and scaling the template's capsules in C++.

**(e)** Blender can compute a capsule per bone (radius = 80th percentile distance from the bone axis of vertices weighted above 0.5 to that bone) and store it in the manifest. Unity uses the same numbers directly (Y4).

**(f)** Mobile: give Unity colliders only on the root plus a few key bones; keep the full ragdoll for AAA.

### U4. LODs and LOD settings

**(a) Why.** Performance; mobile needs aggressive LODs and a minimum LOD per platform.

**(b)** Forge already exports `_LOD0..n` meshes from Blender.
- Import them with `import_mesh_lo_ds=True` [V field name].
- Or generate them in Unreal: `sub = unreal.get_editor_subsystem(unreal.SkeletalMeshEditorSubsystem)`, then `sub.regenerate_lod(mesh, new_lod_count=n)`, `sub.get_lod_count(mesh)`, `sub.get_lod_build_settings(mesh, i)` / `set_lod_build_settings(mesh, i, opts)` [all V, send2ue].
- Static meshes: `unreal.StaticMeshEditorSubsystem.set_lod_build_settings(mesh, i, unreal.MeshBuildSettings())` [V].

**(c)** Screen sizes and reduction per tier belong in a shared **`SkeletalMeshLODSettings` data asset** per tier (`LODS_Forge_AAA`, `LODS_Forge_Mobile`), assigned with `skeletal_mesh.lod_settings = data_asset` [V, send2ue].

**(d)** Heuristic screen sizes (not from a source):
- AAA: 1.0 / 0.5 / 0.25 / 0.12
- Mobile: 1.0 / 0.35 / 0.15

Set the per-platform minimum LOD for Android/iOS through the mesh's per-platform `min_lod` (property name UNVERIFIED). In Unreal 5 the bone influence limit is a per-platform project setting (UNVERIFIED in detail).

**(f)** Nanite on skeletal meshes is experimental in late UE 5.x (UNVERIFIED). Keep Nanite off for skinned characters on the AAA path unless the user's version is confirmed.

### U5. Materials: master materials plus instances (tint, masks, special shading)

**(a) Why.** Instances are cheap to recolour (variants and team colours), keep shader permutations low, and give the director sliders to adjust.

**(b)** One material slot per shading model. Blender names each slot with its kind, written in the manifest. Mobile: no more than 2–3 slots.

**(d) Master materials, each built once by hand:**
- `M_Forge_Opaque` parameters: `BaseColor`(T), `Normal`(T), `ORM`(T), `TintMask`(T, RGBA), `Tint_R/G/B/A`(vector), `TintStrength`, `DetailNormal`(T), `DetailTiling`, `EmissiveMask`(T), `EmissiveColor`, `EmissiveIntensity`; static switches `UseTint`, `UseDetail`, `UseEmissive`.
- `M_Forge_Masked`: tattered alpha edges and fur cards (fur cards use `M_Forge_Hair` with the Hair shading model on AAA).
- `M_Forge_Skin`: Subsurface Profile shading model, plus an `SSS_Forge_Default` profile.
- `M_Forge_Eye`: Eye shading model on AAA, with an iris mask and refraction depth, following MetaHuman's approach.
- `M_Forge_Cornea`: translucent, for a separate cornea mesh.
- `M_Forge_Metal_Aniso`: anisotropy input; Substrate in late 5.x is UNVERIFIED.

The shading model cannot be changed in an instance, hence one master per kind.

**(e) Script** (`MaterialEditingLibrary` function names are well known; not re-verified this session, network blocked):
```python
at = unreal.AssetToolsHelpers.get_asset_tools()
mi = at.create_asset(f"MI_{asset}_{slot}", path, unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
mel = unreal.MaterialEditingLibrary
mel.set_material_instance_parent(mi, unreal.load_asset("/Game/Forge/MaterialLibrary/M_Forge_Opaque"))
mel.set_material_instance_texture_parameter_value(mi, "BaseColor", tex_bc)
mel.set_material_instance_vector_parameter_value(mi, "Tint_R", unreal.LinearColor(1, .2, .2, 1))
mel.set_material_instance_scalar_parameter_value(mi, "EmissiveIntensity", 5.0)
mel.set_material_instance_static_switch_parameter_value(mi, "UseTint", True)   # UE5.x
mel.update_material_instance(mi)
```
- **Assigning to the mesh:** skeletal meshes have `mesh.materials` (an array of `SkeletalMaterial` with `material_interface` and `material_slot_name`); static meshes have `static_materials` [V, send2ue `get_material_index_by_name`]. Match by slot name, then `set_editor_property('materials', mats)`.
- **Texture import settings, per map kind:**
  - colour: sRGB on, `TC_DEFAULT`;
  - `_N`: `TC_NORMALMAP`;
  - `_ORM`, `_TM`, `_EM`: sRGB off, `TC_MASKS`;
  - characters: `lod_group = TEXTUREGROUP_CHARACTER`;
  - mobile: `max_texture_size` from the manifest.
- **Tint mask:** Blender bakes an RGBA tint mask from material IDs or colour clusters on the AI texture (procedural k-means on the baked colour). The director picks one colour per channel once. Unity reuses the same mask (Y5).

**(f)** Subsurface Profile and the Eye shading model do not run on mobile renderers. The Unreal mobile path falls back automatically to default lit (the exact fallback is UNVERIFIED); for Unity see Y5.

### U6. Sockets

**(a) Why.** Weapon and hand attach points, VFX spawn points (mouth, eyes, exhausts), camera and look targets, plus the mount points for mechanical retractable parts.

**(b)** They are positioned on bones; record them in the manifest.

**(e)**
- **Skeletal mesh** [V, GloriousEggroll/OpenUT2k4 `ImportUT2004.py`]:
  ```python
  sock = sk.find_socket(name) or unreal.SkeletalMeshSocket(sk)
  sk.add_socket(sock, False)   # False = mesh-level, not skeleton
  sk.rename_socket(sock.get_editor_property("socket_name"), name)
  ```
  That repo notes "SocketName/BoneName are read-only from Python: add, then rename and re-parent". Set `bone_name` (via an editor-property workaround or skeleton-level socket, UNVERIFIED), `relative_location` and `relative_rotation`.
- **Static mesh** [V, send2ue]: `s = unreal.StaticMeshSocket(sm)`; `s.set_editor_property('socket_name' / 'relative_location' / 'relative_rotation' / 'relative_scale', …)`; `sm.add_socket(s)`; remove an old one with `find_socket` / `remove_socket`.
- **Static mesh collision:** FBX objects named `UCX_<mesh>_##`, `UBX_` or `USP_` import as simple collision (standard Unreal convention). Check with `StaticMeshEditorSubsystem.get_simple_collision_count` / `get_convex_collision_count` [V].

**(f) Unity:** export sockets as empty GameObjects parented to bones, named `socket_<name>` (keep `EMPTY` in the FBX object types, which Forge already does).

### U7. AnimBP and post-process AnimBP: look-at, eyelid follow, Pose Driver correctives, AnimDynamics

**(a) Why.**
- **Post-process AnimBP:** runs on top of *any* animation: gameplay, Sequencer and montages. Secondary motion and correctives therefore always show up, including in cinematics. KawaiiPhysics explicitly recommends putting physics in the post-process ABP so it survives Sequencer's anim instance override [V, KawaiiPhysics `kawaii_physics_setup.py`].
- **Eyelid follow:** without it the eyes look dead in close-ups. The lids must track the eye's pitch.
- **Correctives:** stop elbows, knees and shoulders collapsing.

**(b)** Eyelid follow needs separate lid edge loops, plus lid bones or ARKit-style shape keys (covered in the earlier face research).

**(c) Concrete graph for `ABP_Forge_Humanoid_PP`:**
1. Input Pose
2. **Look At** (head 0.3 / neck 0.2 / eye_l and eye_r 1.0; target from a `LookTarget` variable set by gameplay)
3. **Control Rig node** running `CR_Forge_Face`:
   - Get eye_l rotation → pitch × `LidFollowTop` (≈0.6) → rotate lid_top_l; × `LidFollowBot` (≈0.25) → lid_bot_l;
   - or, for shape-key characters, set the curves `eyeLookDownLeft` / `eyeLookUpLeft` / `eyeLookInLeft` / `eyeLookOutLeft` (ARKit names), which drive morph targets of the same name.
4. **Pose Driver** nodes for correctives:
   - Source bone `lowerarm_l`; RBF on swing;
   - Drive Output = curves, so target names equal the morph target names, e.g. `corr_elbow_l_90`. That driving-curves-by-target-name behaviour is UNVERIFIED in detail.
5. **AnimDynamics** for tail, ear, antenna and cable chains (from the manifest chains; chain mode, box extents from bone length). Alternatively **RigidBody** using PHYS_ bodies on those bones only, or KawaiiPhysics (third-party).
6. Output.

**(e) Can Python create this?**
- Creating the asset: yes [V, KawaiiPhysics toolset]:
  ```python
  f = unreal.AnimBlueprintFactory()
  f.set_editor_property('target_skeleton', skel)
  f.set_editor_property('parent_class', unreal.AnimInstance.static_class())
  ```
  then `create_asset(...)`.
- Assigning it: `skeletal_mesh.set_editor_property('post_process_anim_blueprint', abp.generated_class())` [V].
- **Inserting AnimGraph nodes from stock Python is not possible.** KawaiiPhysics ships its own C++ `KawaiiPhysicsEditorLibrary.add_kawaii_physics_nodes(...)` and `compile_anim_blueprint_with_messages(...)` to do it [V].
- **Forge approach:** build `ABP_Forge_<Archetype>_PP` and `CR_Forge_<Archetype>_Face` **once by hand** against the shared skeleton. Expose tuning as variables or anim curves. Per asset, the script only assigns the ABP and writes per-asset numbers, either as AnimBP class defaults on a child ABP or as curve metadata (exact method UNVERIFIED).
- If the asset is on its own skeleton (the U2 fallback), duplicate the template and retarget it ("Replace Skeleton"; Python path UNVERIFIED). Or build a small C++ `ForgeEditorLib` that writes node bone references from the manifest; this is the only fully generic route.
- **Template Animation Blueprints** (skeleton-agnostic) exist in UE5, but which nodes accept bone references in them is UNVERIFIED.

**(f) Morph targets** keep their Blender shape-key names. For live face capture, name the 52 ARKit shapes exactly (`eyeBlinkLeft`, `jawOpen`, `mouthSmileLeft`, …) so Live Link Face curves drive them directly. MetaHuman uses its own `CTRL_expressions_*` curve layer plus an ARKit mapping pose asset; Forge does not need it unless it targets MetaHuman animation (UNVERIFIED detail).

### U8. Control Rig, IK Rig, retargeting

**(a) Why.** Animators need hand-key controls, and the shared Manny/UEFN animation library has to be retargeted onto creatures.

**(e)**
- **IK Rig:** `rig = create_asset(f'IK_{name}', path, unreal.IKRigDefinition, unreal.IKRigDefinitionFactory())`; `c = unreal.IKRigController.get_controller(rig)`; `c.set_skeletal_mesh(mesh)`; `c.apply_auto_generated_retarget_definition()`; `c.apply_auto_fbik()`; `set_retarget_root` / `set_pelvis` [V names: genex-games `retarget.py`; scenario-labs probe list; DazToUnreal `CreateIKRetargeter.py`].
- **Retargeter:** `unreal.IKRetargeterController` assigns source/target IK rigs and auto-maps chains. Names other than the controller itself are UNVERIFIED; DazToUnreal's script is a complete working reference.
- **Control Rig:**
  - Python can create a Control Rig blueprint and import bones. Graph editing goes through `RigVMController` (`add_unit_node_from_struct_path`), which is verbose but possible (UNVERIFIED in this session).
  - In 5.4+, **Modular Control Rig** auto-fits modules by bone name (UNVERIFIED Python API).
  - Recommended: a hand-built `CR_Forge_<Archetype>` per archetype on the shared skeleton. Assigning it to the mesh needs no graph edits.

### U9. Data Validation rules

**(a) Why.** The director should only see shots of assets that already pass the technical checks; a failing asset should stop the run automatically.

**(e)**
- **Validator:** in Python [V, FXTD-ODYSSEY Unreal-PyToolkit]:
  ```python
  @unreal.uclass()
  class ForgeValidator(unreal.EditorValidatorBase):
      @unreal.ufunction(override=True)
      def can_validate_asset(self, asset): ...
      # override the validate method too; Python name differs by version:
      # validate_loaded_asset vs k2_* per a public probe noting "k2_* overrides in 5.8"
  ```
- **Registration:** `unreal.get_editor_subsystem(unreal.EditorValidatorSubsystem).add_validator(v)`. `AddValidator`, `ValidateAssets`, `ValidateAssetsWithSettings` and `bAllowBlueprintValidators` exist [V, UE 5.2 generated header bindings].
- **Running it:**
  - inside the import script: `ValidateAssetsWithSettings` on the new assets;
  - in CI: the `DataValidation` commandlet (`-run=DataValidation`, UNVERIFIED flag syntax).
- Turn on `bValidateOnSave` so hand edits are checked too.
- Rules: see section 3.

### U10. Screenshots and turntable inside Unreal, for the director

**(a) Why.** Approval should cover what Unreal actually renders: Lumen GI, SSS, eye refraction, LOD switches, the post-process ABP running.

**(e)**
- **Level:** `L_Forge_Review`, built once: neutral HDRI sky, three-point lights, a grey floor, and a calibrated-colour chart. Python opens it, then spawns a `SkeletalMeshActor` with the new mesh and a `CineCameraActor` framed from the manifest's bounds (same field of view and elevation as the Blender preview).
- **Sequence:** `LS_Review_<Asset>` via `LevelSequenceFactoryNew`, containing:
  - a transform track rotating the actor 360° over 8 s;
  - frames 0–60 at T-pose;
  - an animation section playing a retargeted Manny "pose test" montage (idle, walk, jump, crouch);
  - a curve section playing a blink-and-look-around test, to exercise lids and look-at;
  - a camera cut to a close-up of the face.
- **Rendering:**
  - In-editor: `unreal.MoviePipelineQueueSubsystem` (class exists [V, MovieRenderPipeline header and Python stubs]): allocate a job (sequence, map, preset `MRQ_Forge_Review`: PNG, Lumen, 1280×720, anti-aliasing 8 temporal samples), then `render_queue_with_executor(unreal.MoviePipelinePIEExecutor)`. Wait on the executor's finished delegate before quitting.
  - Fully headless command line: `UnrealEditor.exe Forge.uproject /Game/Forge/Review/L_Forge_Review -game -LevelSequence="/Game/…/LS_Review_X" -MoviePipelineConfig="/Game/…/MRQ_Forge_Review" -windowed -ResX=1280 -ResY=720 -log -unattended`. This is MRQ's documented command-line mode; exact flags UNVERIFIED this session.
  - Quick stills: `unreal.AutomationLibrary.take_high_res_screenshot(w, h, filename, camera)`. It needs a rendering editor, not a commandlet (exact signature UNVERIFIED).
- **Extra shots:**
  - LOD strip: force LOD *i* on the component (`set_forced_lod`, UNVERIFIED Python name) for each LOD;
  - a wireframe shot;
  - the material-ID shot.
- Forge assembles a contact sheet (Pillow) and puts it next to Blender's render at the same camera for the director.

---

## 3. Shared validation rules (both engines; run in each, results to `engine_report.json`)

| ID | Rule | Threshold source |
|---|---|---|
| V1 | Name and prefix match `naming.py`; folder correct | Allar / Forge |
| V2 | Triangles per LOD within budget (AAA hero e.g. 60–100k LOD0; mobile 5–15k) | manifest (heuristic numbers) |
| V3 | LOD count and screen sizes match the tier's LOD settings asset or LODGroup | tier |
| V4 | Bone count; influences per vertex no more than 4 (mobile) / 8 (AAA); mobile per-section bone limit | tier |
| V5 | Material slots no more than tier max; every slot uses an MI_ (Unreal) or material variant (Unity) of an approved master | |
| V6 | Textures: power of two, size no more than tier max, sRGB off for masks, normal compression on `_N`, no missing references | |
| V7 | Morph targets: required names present (ARKit 52 if the face tier asks for them); no empty deltas | manifest |
| V8 | Required sockets present (hands, head, mouth, eyes) | manifest |
| V9 | Skeleton = shared archetype skeleton; root at origin; scale sane (bounds height within ±10% of the manifest's real-world height) | |
| V10 | Physics asset or colliders present; body count no more than tier max | |
| V11 | Post-process ABP / Animator controller and the face CR / rig constraints assigned | |
| V12 | Humanoid avatar valid (Unity `avatar.isValid && avatar.isHuman`) | |
| V13 | No negative scale, no non-uniform scale on bones; UV0 in 0–1 for the bake channel; lightmap UV for static props | |

---

## 4. Unity URP (mobile)

### Y1. AssetPostprocessor: importer settings

**(a) Why.** Settings are applied identically on every reimport, with no clicking.

**(e)** `class ForgeModelPostprocessor : AssetPostprocessor`, limited to `Assets/Forge/…`. Return a `GetVersion()` number so changing the rules forces a reimport.
- **`OnPreprocessModel`:** `var mi = (ModelImporter)assetImporter;` then set:
  - `mi.animationType = ModelImporterAnimationType.Human` (Generic for quadrupeds and mechs);
  - `mi.avatarSetup = ModelImporterAvatarSetup.CreateFromThisModel`;
  - `mi.importBlendShapes = true`; `mi.importBlendShapeNormals = ModelImporterNormals.Calculate`;
  - `mi.materialImportMode = ModelImporterMaterialImportMode.None`;
  - `mi.importCameras = mi.importLights = false`;
  - `mi.bakeAxisConversion = true`;
  - `mi.optimizeGameObjects = false` while the rig needs bone transforms (Animation Rigging, sockets); `true` on mobile builds that expose only sockets via `extraExposedTransformPaths`;
  - `mi.meshCompression = ModelImporterMeshCompression.Medium` (mobile);
  - `mi.isReadable = false`.
- **Explicit humanoid mapping:** set `mi.humanDescription` with `HumanBone[]` built from the manifest, so ARP's Unity names always map. Map the **LeftEye, RightEye and Jaw** humanoid bones so `Animator.SetLookAtPosition` / `SetLookAtWeight` drive the eyes in `OnAnimatorIK`.
- **`OnPostprocessGameObjectWithUserProperties`** [V]: read Blender custom properties (material kind, collider hint, socket).
- **`OnPostprocessModel(GameObject root)`:**
  - turn children named `UCX_*` into `MeshCollider{convex=true}` and remove their renderers;
  - mark `socket_*` empties.
- **`OnPreprocessTexture`:**
  - `TextureImporter.sRGBTexture=false` for mask maps;
  - `textureType=NormalMap` for `_Normal`;
  - `SetPlatformTextureSettings(new TextureImporterPlatformSettings{ name="Android", overridden=true, maxTextureSize=1024, format=TextureImporterFormat.ASTC_6x6 })`, same for iOS.

### Y2. Building the prefab (as a prefab variant of the model)

**(e)** A batch-mode `ForgeBuild.Run`:
1. `AssetDatabase.ImportAsset(fbx)`.
2. `var inst = (GameObject)PrefabUtility.InstantiatePrefab(model)`.
3. Add components (Y3–Y7).
4. `PrefabUtility.SaveAsPrefabAsset(inst, "Assets/Forge/<Asset>/PF_<Asset>.prefab")`. Saving an instance of the model prefab gives a **prefab variant**, so reimporting the FBX updates the mesh while added components survive.

Wrap bulk work in `AssetDatabase.StartAssetEditing()` / `StopAssetEditing()`. Do not create assets inside `OnPostprocessAllAssets`; run them afterwards with `EditorApplication.delayCall`, or in the batch-mode method.

### Y3. Animator and Avatar

- `animator.avatar` = the sub-asset from `AssetDatabase.LoadAllAssetsAtPath(fbx).OfType<Avatar>()`.
- `animator.runtimeAnimatorController` = an `AnimatorOverrideController` built from `AC_Forge_<Archetype>` (template controller made once), with clips overridden per asset.
- Validate the avatar (V12).
- Mobile: `animator.cullingMode = AnimatorCullingMode.CullUpdateTransforms`.

### Y4. Colliders

- **Gameplay:** a `CapsuleCollider` sized from bounds on the root, or a `CharacterController`.
- **Ragdoll (only if the tier asks for it):** for each manifest collider: `CapsuleCollider` (radius and height from Blender's per-bone fit, U3e), `Rigidbody{isKinematic=true}`, `CharacterJoint` linked to the parent body. Unity's own RagdollBuilder is an internal editor wizard, so write our own.
- **Props:** convex `MeshCollider` from `UCX_`, or `BoxCollider` from bounds.

### Y5. Materials (URP)

- **Master:** Shader Graph `SG_Forge_Character` with `_BaseMap`, `_BumpMap`, `_MaskMap` (Forge packs metal in RGB and smoothness in A; see `finalize.py`), `_OcclusionMap` or AO baked into the base map (Forge's `ao_into_basecolor`), `_TintMask`, `_TintR/G/B/A`, `_EmissionMask`, `_EmissionColor`, `_DetailNormal`.
- **Per asset:** `var m = new Material(master); m.parent = master;` making a Material Variant, Unity 2022.1+. `Material.isVariant` / `.parent` [V, UnityCsReference `MaterialEditor.cs`]. Then `SetTexture`/`SetColor`, and `AssetDatabase.CreateAsset`.
- **If plain URP/Lit is used instead:** set `_BaseMap`, `_BumpMap`, `_MetallicGlossMap`, `_OcclusionMap`, `_EmissionMap`, `_EmissionColor`, and **enable the keywords** `_NORMALMAP`, `_METALLICSPECGLOSSMAP`, `_EMISSION`, or the maps are ignored (standard URP behaviour; confirm in the user's URP version).
- **Special shading** (URP has none of the following built in):
  - Skin: no SSS → wrap lighting plus a red scatter tint in the Shader Graph.
  - Eyes: no eye shader → iris with a parallax offset node plus a separate cornea using smoothness 1, or a matcap highlight.
  - Anisotropic metal: custom Shader Graph.

### Y6. LODGroup

Unity builds a LODGroup automatically from `_LOD0.._LODn` names (Forge relies on this). Then re-set the thresholds:
```csharp
lg.SetLODs(new[]{ new LOD(0.35f, r0), new LOD(0.15f, r1), new LOD(0.03f, r2) });
lg.fadeMode = LODFadeMode.CrossFade;
```
These are heuristic mobile values. Every LOD's `SkinnedMeshRenderer` shares the same bones. Also set `QualitySettings.skinWeights = SkinWeights.TwoBones` / `FourBones` for the mobile quality tier.

### Y7. Animation Rigging constraints (`com.unity.animation.rigging`)

`RigBuilder` sits on the Animator object, with a child `Rig` and `rigBuilder.layers.Add(new RigLayer(rig, true))` [V, scenario-labs procedures; VRigUnity; the package source mirror].
- **Look-at:** `MultiAimConstraint` on head/neck (weight 0.3/0.2) and eyes (1.0). Set `data.constrainedObject`, `data.sourceObjects = new WeightedTransformArray(0){ new WeightedTransform(target,1f) }`, aim and up axes chosen from the bone's rest orientation [V pattern].
- **Eyelid follow:** `MultiRotationConstraint` [V class] on lid_top_l with source eye_l at weight ≈0.6 and maintain offset; lid_bot_l at ≈0.25.
- **Tails, ears, cables:** `DampedTransform` chains, or `ChainIKConstraint` for controlled tails.
- **Limbs:** `TwoBoneIKConstraint` (feet planting).
- Call `rigBuilder.Build()` when the shot needs constraints evaluated in edit or batch mode.

### Y8. Blendshape drivers (Unity has no Pose Driver)

A small runtime component, `ForgeBlendshapeDriver : MonoBehaviour`. `[DefaultExecutionOrder]` runs it late, so it applies after the Animator / Animation Rigging pass.
- Each rule: driver transform; a swing angle measured against the rest pose with `Quaternion.Angle` or swing-twist on an axis; an `AnimationCurve` remap; then `smr.SetBlendShapeWeight(smr.sharedMesh.GetBlendShapeIndex(name), w)`.
- Rules come from the manifest: correctives, eyelid follow via ARKit shapes (`eyeLookDownLeft`…), and an automatic blink.
- Unity blend-shape weights run 0–100 by default (a 0–1 project option exists in newer versions, UNVERIFIED).
- Mobile cost: drive only shapes on LOD0, and strip correctives from LOD1+ in Blender.

### Y9. Validation in Unity

Unity has no Data Validation framework. A `ForgeValidator` static class runs V1–V13, writes `engine_report.json`, and the run ends with `EditorApplication.Exit(failures>0 ? 1 : 0)`. Optionally add Unity's Project Auditor package for general checks.

### Y10. Screenshots and turntable in Unity

Batch mode **without `-nographics`** on the RTX machine renders:
- Open `Forge_Review.unity`: mobile URP asset, the same HDRI, lights and colour chart as Unreal.
- Instantiate the prefab. Set the camera from the manifest framing, `camera.targetTexture = rt; camera.Render();`, then `ReadPixels` + `EncodeToPNG`. `Camera.Render` with URP is UNVERIFIED for every version; the newer API is `RenderPipeline.SubmitRenderRequest`.
- **Pose test without Play mode:** build a `PlayableGraph` with an `AnimationClipPlayable` on the Animator, `graph.Evaluate(t)` per frame, and rebuild the RigBuilder so constraints apply (UNVERIFIED that Animation Rigging evaluates inside a manually evaluated graph). Fallback: enter Play mode from the batch-mode script and capture with Unity Recorder (`RecorderController`).
- **Output:** 12 turntable angles, 4 pose frames, a face close-up with blink/look, an LOD strip, and the mobile quality-level shot. Forge assembles the contact sheet.

---

## 5. What is automatic, what needs a one-time hand build, what needs one director click

- **Fully scripted per asset:**
  - import, skeleton assignment, PHYS template, LOD settings, material instances and variants, texture settings, sockets, prefab, Animator/Avatar, LODGroup, colliders, Animation Rigging constraints, blendshape driver rules, validation, review renders;
  - in Unreal, the IK Rig + retargeter.
- **Built once per archetype, by hand or with a C++ helper:**
  - masters `M_Forge_*` / `SG_Forge_Character`;
  - `ABP_Forge_<Arch>_PP` (Look At, Control Rig face, Pose Drivers, AnimDynamics), `CR_Forge_<Arch>_Face`, `AC_Forge_<Arch>`;
  - `PHYS_Forge_<Arch>`, `LODS_Forge_<tier>`;
  - review levels/scenes and the MRQ preset.

  Reason: Unreal AnimGraph nodes cannot be inserted with stock Python. KawaiiPhysics needed its own C++ library to do it [V].
- **Director clicks:** approve or reject the engine contact sheet per engine. Optionally choose the tint-mask colours, which feed MI parameters and variant colours.

## 6. Main risks

- Unreal Python names change between versions; probe them with `hasattr` at startup.
- Interchange sub-pipeline property names were not checked.
- Unreal cannot generate physics bodies from Python with custom settings.
- AnimGraph cannot be authored from Python.
- Animation Rigging in edit-mode capture is not confirmed.
- URP has no SSS or eye shader.

## Sources

- Allar style guide (UE4 table and v2/UE5 branch): https://github.com/Allar/ue5-style-guide , https://github.com/Allar/ue5-style-guide/tree/v2
- Send to Unreal (Unreal-side import, sockets, LOD, physics, remote execution): https://github.com/poly-hammer/BlenderTools/blob/main/src/addons/send2ue/dependencies/unreal.py
- Interchange scripted import: https://raw.githubusercontent.com/OpenDCAI/GameFactory-3A/main/engine_adapters/ue5/import_generated/import_mesh.py
- Interchange in a Blender exporter: https://github.com/xavier150/Blender-For-UnrealEngine-Addons (`bfu_import_module/`)
- AnimBP factory, post-process ABP assignment, C++ library for AnimGraph nodes: https://github.com/pafuhana1213/KawaiiPhysics (`Plugins/KawaiiPhysics/Content/Python/kawaii_physics_toolset/toolset.py`, `skills/kawaii_physics_setup.py`)
- Skeletal mesh socket workaround: https://github.com/GloriousEggroll/OpenUT2k4 (`Client/Tools/ImportUT2004.py`)
- EditorValidatorBase in Python: https://github.com/FXTD-ODYSSEY/Unreal-PyToolkit (`Content/PyToolkit/_hook/on_saved.py`)
- EditorValidatorSubsystem functions (UE 5.2 bindings): https://github.com/SomeRanDev/Haxe-UnrealEngine5 (`Externs/generated_5_2_0/EditorValidatorSubsystem.hx`)
- Import hook (importer rules): https://github.com/Ryan-DowlingSoka/UnrealImporterRules-Python
- IK Rig / retargeter Python: https://github.com/daz3d/DazToUnreal (`UnrealPlugin/DazToUnreal/Content/Python/CreateIKRetargeter.py`)
- MRQ subsystem and executor: MovieRenderPipeline `MoviePipelineQueueSubsystem.h` (UE source mirror on GitHub); https://github.com/city-super/MatrixCity (`MatrixCityPlugin/Content/Python/pipeline.py`)
- Unity FBX user-properties callback: https://github.com/Unity-Technologies/UnityCsReference (`Editor/Modules/AssetPipelineEditor/ImportBlocksEditor/Core/Interfaces/IModelImporterBlock.cs`); https://github.com/Unity-Technologies/FPSSample (`Assets/Scripts/EditorTools/Editor/SkeletonImporter.cs`)
- Unity material variants: UnityCsReference `Editor/Mono/Inspector/MaterialEditor.cs`
- Animation Rigging: https://github.com/needle-mirror/com.unity.animation.rigging (`MultiRotationConstraint.cs`); https://github.com/Kariaro/VRigUnity (`RigAnimator.cs`)
- Not reachable this session (confirm UNVERIFIED items there): dev.epicgames.com (Unreal Python API, Interchange, MRQ command line, Data Validation) and docs.unity3d.com (ModelImporter, LODGroup, URP Lit keywords, Recorder).
