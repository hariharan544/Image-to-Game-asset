# Roadmap

## Phase 1: Foundation ✅ (this commit)
- Creative Guide + profiles (6 asset types × 3 tiers, 3 styles, Unity/Unreal)
- Tripo apiv3 stage (multiview, generation, parts, segmentation/completion, rig check + rig)
- Blender stages: cleanup, retopology, UVs, PBR bake, skin transfer + sockets, LODs, metrics,
  previews, engine export
- QA gate, rule supervisor, LLM supervisor with a safe action space, recorder, review checkpoints
- Training environment: dataset builder, QLoRA trainer, evaluator, Ollama serving
- Tests: full pipeline run with a fake Tripo

## Phase 1b: AAA + mobile targets ✅
- Unreal = AAA and Unity = mobile, built as two versions from one Tripo generation, each with its
  own budgets, textures, influences, LODs and export.

## Phase 2: First live run on your PC
- `forge check`, then one prop and one humanoid through the live Tripo API. Fix any field-name
  surprises in the Tripo responses.
- Pin the newest Tripo model versions in the guide (`generation.model_version`, `rig.model_version`).
- Tune the profile budgets with you after looking at real results.

## Phase 3: Paid add-ons + quality
- ✅ **Quad Remesher** is the default retopology method. It runs in a short-lived windowed
  Blender (verified on the user's PC: about 3 s per part, 100% quads). If it fails, it falls back
  to QuadriFlow for that part.
- ✅ **Auto-Rig Pro** rigs humanoids (`rig.method: auto_rig_pro`):
  1. Tripo's skeleton (UE Mannequin, Mixamo or generic names) → all 65 ARP reference bones;
  2. match_to_rig → bind;
  3. props welded to their socket bone;
  4. export through ARP: UE5 Mannequin skeleton for Unreal, Humanoid for Unity.

  Each ARP call was verified on the user's PC. The full chain runs in the setup smoke test. If ARP
  fails, the stage falls back to transferring Tripo's weights.
- ⏳ **UVPackmaster**: the add-on loads, but its packing engine (installed separately) is not
  detected. The adapter is built once the engine is installed. Blender's packer is used until then.
- Bake: optional cage mesh, anti-aliased bakes, texture de-lighting and seam fixing.
- Mobile: strip non-essential bones (fingers, twist bones) when the bone count is over budget.
  Optionally bake an atlas so all parts share one material, for fewer draw calls.
- Vision model labels parts from renders, so "sword", "helmet" and "cape" are recognised whatever
  Tripo calls them.

## Phase 4: AI supervisor v1
- Collect ≥ 200 labelled decisions, fine-tune Qwen3-8B on the 4080, evaluate, switch to
  `backend: llm`.
- Vision critic LoRA from your review notes.

## Phase 5: Animation (next stage after rigging)
- Tripo `animations/retarget` presets (idle, walk, run, jump, slash, shoot, hurt, fall, turn...)
  as a starter set per asset type.
- Blender: retarget to the final skeleton, root motion vs in-place per engine, clean curves,
  export animation FBX per clip.
- Engine setup scripts: UE5 IK Retargeter / Animation Blueprint stub; Unity Humanoid avatar +
  Animator Controller stub.
- Supervisor checks for animation: foot sliding, mesh intersection, joint limits.

## Phase 6: Scale
- Batch mode with a credit budget per run; parallel Blender workers.
- Engine import scripts that create materials automatically (UE Python, Unity Editor script).
