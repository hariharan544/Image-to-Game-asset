# Forge: one image → game-ready 3D asset

Forge turns a single concept image into a **game-ready, multi-part, rigged 3D asset** for
**Unreal Engine 5 and Unity**. A creative director only has to choose the image, write a few
plain lines in a *Creative Guide*, and approve at two checkpoints.

```
image ─► Tripo (cloud) ─────────► Blender (headless, automatic) ──────────────────► Unity / Unreal
         4 views, 3D model,       clean ▸ retopology ▸ UVs ▸ bake PBR ▸ skin weights   FBX + packed
         parts, skeleton          ▸ sockets ▸ LODs ▸ renders                            textures
                     ▲                          ▲ after every stage
              you approve views        QA gate + AI supervisor: accept / retry with
                                       new settings / ask you
```

* **Tripo** does the generation: 4 views from your image, the 3D model, part splitting, and the
  skeleton (Unity or Unreal spec). It is called through the official `tripo3d` SDK (apiv3).
* **Blender** rebuilds the AI model into a production asset: clean quad topology inside the
  polygon budget, proper UVs, the AI's detail and colour baked into PBR maps, the AI's skin
  weights transferred onto the new mesh and limited to the engine's influence count, weapon/prop
  sockets, LODs, and engine-correct export (Unreal: `SK_`/`SM_`, ORM, DirectX normals; Unity:
  HDRP Mask Map or URP, OpenGL normals).
* **QA gate + AI supervisor** measure every stage (triangles, UV overlap/stretch/texel density,
  bake misses, unweighted vertices...) and decide what to do. The supervisor is a **local open
  model you fine-tune on your RTX 4080** from the pipeline's own history and your reviews
  (see [training/README.md](training/README.md)). Until it is trained, a built-in rule
  supervisor does the job.

## Setup (Windows)

1. Install **Python 3.11+** and **Blender 4.2 LTS or newer** (developed against Blender 5.3).
2. In a terminal in this folder:
   ```bat
   py -m venv .venv
   .venv\Scripts\activate
   pip install -e .[dev]
   copy .env.example .env
   ```
3. Put your Tripo API key (`tsk_...`, from platform.tripo3d.ai) into `.env`.
4. Check everything is found:
   ```bat
   forge check
   ```

## Making assets (the director's workflow)

1. Put concept images in `inputs/`: one object per image, plain background.
2. Copy `guides/example_project.yaml` to `guides/my_game.yaml` and list your assets. For each one
   you pick a **type** (humanoid, creature, weapon, prop, vehicle, environment), a **tier** (hero,
   standard, background) and a **style** (realistic, stylized, lowpoly). Add **detachable parts**
   and **notes** in plain words. Budgets, texture sizes, rig spec and export settings follow from
   those choices (see `guides/profiles/`).
3. Run:
   ```bat
   forge run guides\my_game.yaml
   ```
4. **Checkpoint 1: concept.** Open `jobs\<asset>\review\concept\` and look at the 4 generated
   views. Then approve:
   ```bat
   forge review jobs\knight --approve
   ```
   Or reject with a note to regenerate the views:
   ```bat
   forge review jobs\knight --reject --notes "back view lost the cape" --redo-from concept
   ```
   Run `forge run` again to continue.
5. **Checkpoint 2: final.** `jobs\<asset>\review\final\REVIEW.md` shows turntable renders, the AI
   critique, warnings and metrics. Approve to export, or reject with notes and a restart stage:
   ```bat
   forge review jobs\knight --reject --notes "sword blade too thin" --redo-from retopo
   ```
6. The game-ready files are in `jobs\<asset>\export\unreal\` and `jobs\<asset>\export\unity\`.

`forge status` lists every asset, its stage and the Tripo credits it used. Runs are resumable.
Tripo task IDs are saved before waiting, so a crash or a rerun never pays for the same
generation twice.

**Your notes are training data.** Every approve/reject note teaches the AI supervisor what
you care about.

## Repository layout

| Path | What |
|---|---|
| `guides/` | Creative Guides + profiles (asset types, styles, engines) |
| `forge/` | Orchestrator: spec, pipeline, Tripo stage, QA gate, supervisor, dataset recorder, CLI |
| `blender_scripts/` | Headless Blender stages (`run_stage.py` + `forge_bpy/`) |
| `training/` | Build dataset → QLoRA fine-tune on the 4080 → evaluate → serve with Ollama |
| `docs/` | Architecture and roadmap |
| `tests/` | Unit tests + a full pipeline run with a fake Tripo (needs Blender or the `bpy` module) |

## Status

Phase 1 is done: the pipeline, the Blender stages, the QA gate, the supervisors, the training
environment, and the tests. The full pipeline runs end to end against a local test model
(`pytest`).

Not verified yet:
- The Tripo calls have not been run against the live API. They follow the official SDK
  (`tripo3d` 1.0, apiv3).
- The fine-tuning script has not been run on a GPU yet.

The paid add-ons (Quad Remesher, Auto-Rig Pro, UVPackmaster) are not wired in yet. Blender's
built-in equivalents are used for now. See [docs/ROADMAP.md](docs/ROADMAP.md).
