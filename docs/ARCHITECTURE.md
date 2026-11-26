# Architecture

## Stages

| # | Stage | Where | What it does | Measured by the QA gate |
|---|---|---|---|---|
| 1 | concept | Tripo `image-to-multiview` | 1 image → front/left/back/right views. **Checkpoint: director.** | (human) |
| 2 | generate | Tripo `multiview-to-model` / `image-to-model`, optional `mesh/segment` + `mesh/complete`, `animations/rig-check` + `animations/rig` | textured PBR model, parts, skeleton (spec `unreal`/`unity`) | Tripo task status |
| 3 | cleanup | Blender | import, drop helper meshes, scale to real height, pivot bottom-centre, merge doubles, remove degenerate/loose geometry, fix normals; keeps a *high* copy of each part | parts found, rig present |
| 4 | retopo | Blender | per-part triangle budget (by surface area), QuadriFlow → voxel+QuadriFlow → decimate chain, hard budget cap | budget, failed / fallback parts |
| 5 | uv | Blender | smart / seams+angle-based / seams+min-stretch unwrap, pack, smoothing by angle | overlap %, utilisation, texel density vs target, density variation (stretch), out-of-bounds |
| 6 | bake | Blender Cycles | high → low: base colour, tangent normal, roughness, metallic, AO; rebuilds a clean PBR material | ray misses |
| 7 | skin | Blender | transfer the AI's weights to the new mesh (nearest-face interpolation), keep deform bones only, strongest N influences, normalise, fill orphan vertices, add sockets (`socket_weapon_r` under `hand_r`, ...) | unweighted verts, missing sockets |
| 8 | lods | Blender | LOD chain `_LOD0.._LODn` by ratio | - |
| 9 | metrics | Blender | final measurements of the whole asset | non-manifold, ngons, weights, influences |
| 10 | previews | Blender | 5 turntable renders + clay render (Workbench; Cycles CPU fallback) | AI visual critique (optional) |
| 11 | final_review | - | review packet `REVIEW.md`. **Checkpoint: director.** | (human) |
| 12 | export | Blender | per engine: FBX (body + each detachable part), engine naming, texture packing | - |

Each Blender stage is a separate headless process (`blender -b -P blender_scripts/run_stage.py -- <stage> args.json result.json`)
that loads the previous stage's `.blend` and saves its own. That makes every stage repeatable
on its own, so a retry with new parameters only reruns that stage.

## Supervisor loop

```
run stage(params) ─► metrics ─► QA gate ─► issues ─► supervisor.decide(observation)
       ▲                                                    │
       └────── new params (from the fixed action space) ◄───┤ retry
                                                            ├─ accept   → next stage
                                                            └─ escalate → director
```

* **Action space** (`forge/supervisor/base.py`): every knob the AI may turn, scoped per stage and
  clamped to safe ranges. Examples: `retopo_voxel_first`, `uv_min_stretch`, `bake_more_extrusion`,
  `skin_lower_min_weight`. The AI cannot invent operations or accept over a blocking error.
* **Rule supervisor** (`rules.py`): an issue → fixes playbook. It is always available, is the
  fallback for any AI error, and produces the first training data.
* **LLM supervisor** (`llm.py`): a local open model through any OpenAI-compatible server
  (Ollama / LM Studio / llama.cpp). An optional vision model writes the visual critique in the
  final review.
* **Recorder** (`forge/dataset.py`): logs every observation, decision and retry outcome, plus every
  director verdict and note. `training/` turns this into fine-tuning data.

## Engine conventions

| | Unreal Engine 5 | Unity (HDRP default, URP optional) |
|---|---|---|
| Mesh names | `SK_<asset>.fbx` (rigged) / `SM_` (static), parts `..._<part>.fbx` | `<asset>.fbx`, `<asset>_<part>.fbx` |
| LODs | `<part>_LOD0..n` in the FBX | `<part>_LOD0..n` → automatic LODGroup |
| Normal map | DirectX (green flipped) `T_*_N` | OpenGL `*_Normal` |
| Packed map | `T_*_ORM` (R AO, G roughness, B metallic) | HDRP `*_MaskMap` (R metal, G AO, B detail, A smoothness) / URP `*_MetallicSmoothness` + `*_Occlusion` |
| FBX | scale 1.0, armature object named `Armature` (UE drops it, no extra root bone) | apply unit scale, bake space transform |
| Skin influences | the guide's limit (default 4, valid in both engines) | 4 |

## Multi-part assets

Parts come from Tripo (`generate_parts` or `mesh/segment` + `mesh/complete`). Every part gets its
own topology budget, its own 0–1 UV space and texture set, and its own weights. Parts listed in
`detachable_parts` are exported as separate FBX files so they can be swapped in the engine.
Sockets on the skeleton say where they attach. Guide names are matched to Tripo's part names by
case-insensitive substring. The roadmap adds AI labelling of parts from renders.
