# Forge: one image → game-ready 3D asset

Forge turns a single concept image into a **game-ready, multi-part, rigged 3D asset** for two
targets at once: **Unreal Engine 5 (AAA / high-end)** and **Unity (mobile)**. Tripo generates the
model once. Blender then builds two separate versions from it, each with its own polygon budget,
texture sizes, bone limits and export conventions. A creative director only has to choose the image, write a few
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
* **Blender** rebuilds the AI model into a production asset, once per target: clean quad topology inside the
  polygon budget, proper UVs, the AI's detail and colour baked into PBR maps, the AI's skin
  weights transferred onto the new mesh and limited to the engine's influence count, weapon/prop
  sockets, LODs, and engine-correct export.
  * **Unreal AAA:** `SK_`/`SM_` names, ORM, DirectX normals, up to 8 influences, 4 LODs.
  * **Unity mobile:** URP, AO folded into the base map, OpenGL normals, 4 influences, a bone-count
    warning, 3 LODs, and budgets around 5× smaller.
* **QA gate + AI supervisor** measure every stage (triangles, UV overlap/stretch/texel density,
  bake misses, unweighted vertices...) and decide what to do. The supervisor is a **local open
  model you fine-tune on your RTX 4080** from the pipeline's own history and your reviews
  (see [training/README.md](training/README.md)). Until it is trained, a built-in rule
  supervisor does the job.

## Setup (Windows)

Open PowerShell in this folder and run:

```powershell
powershell -ExecutionPolicy Bypass -File setup\setup_windows.ps1
```

The script installs Python and Blender if they are missing (it asks first), installs Forge and
creates `.env`. It then runs **`forge setup-blender`**, which checks:
* the Blender version;
* that your RTX GPU is available for baking;
* which paid add-ons are installed.

It finishes with a smoke test of every Blender stage inside your Blender.

Then put your Tripo API key (`tsk_...`, from platform.tripo3d.ai) into `.env` and run
`forge check`. Details and manual steps: [docs/SETUP_BLENDER.md](docs/SETUP_BLENDER.md).

## Two ways to start an asset

| | `image:` (API) | `model:` (your own file) |
|---|---|---|
| Who makes the 3D model | Tripo API, automatically (4 views → model → parts → texture → rig) | you, in **Tripo Studio** with your web plan, or any tool |
| Credits | Tripo **API** credits (separate from the web plan) | your **web plan** credits; no API credits |
| Creative control | the concept checkpoint | full: pick the generation you like, edit in Studio |
| What to put in `inputs\` | the concept image | the downloaded model (**GLB with textures**; for characters the **auto-rigged** version) + optionally the image |

Everything after the 3D model is the same for both: Quad Remesher, UVPackmaster, baking,
Auto-Rig Pro, LODs, and the Unreal/Unity exports. You can mix both in one guide.

Tips for Studio downloads:
* **Use GLB.** It carries its textures. FBX textures are often separate files that get lost.
* **Characters must be auto-rigged in Studio first.** Auto-Rig Pro builds its rig from that
  skeleton. Without one, the run stops and asks you to download the rigged version.
* **Set `topology: {target_height_m: ...}`** to fix the real-world size. A model that comes in
  centimetres is detected and scaled automatically.

## The Blender panel: Tripo Studio → Bridge → Blender → Forge

The easiest way to work with option B is the **Send to Forge** panel inside Blender. Install it
once, with every Blender window closed:

```bat
.venv\Scripts\forge.exe install-blender-addon
```

Daily workflow:
1. In **Tripo Studio**, generate and auto-rig the character. Click **Export → Send to Blender**
   (Tripo DCC Bridge).
2. In Blender, select the model, press **N** and open the **Forge** tab.
3. Set the **name**, **type**, **tier**, **swappable parts** (select parts → ➕), **height**,
   **notes** and, optionally, the **concept image**.
4. Click **Send to Forge**. The panel:
   * exports a GLB to `inputs\`;
   * adds the asset to `guides\from_blender.yaml`;
   * starts the pipeline in a console window.
5. The panel shows the status. When it says *Waiting for you*, click **Open review**, then
   **Approve**, or **Reject** with notes and a stage to rebuild from (e.g. `bake@unity`).

The pipeline's own Blender windows switch the Tripo Bridge off inside themselves, so the
Bridge always stays connected to *your* Blender.

## Making assets (the director's workflow)

1. Put concept images in `inputs/`: one object per image, plain background.
2. Copy `guides/example_project.yaml` to `guides/my_game.yaml` and list your assets. For each one
   you pick a **type** (humanoid, creature, weapon, prop, vehicle, environment), a **tier** (hero,
   standard, background) and a **style** (realistic, stylized, lowpoly). The tier picks the
   budget in *both* tables: the AAA table for Unreal and the mobile table for Unity. Add **detachable parts**
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
   To rebuild only one version, add the engine to the stage name:
   ```bat
   forge review jobs\knight --reject --notes "mobile texture too blurry" --redo-from bake@unity
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
