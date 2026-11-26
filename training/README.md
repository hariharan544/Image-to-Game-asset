# Training the AI supervisor on your RTX 4080 Super

The supervisor is a small open model (default **Qwen3-8B**, Apache-2.0). It learns what a senior
technical artist would do after each pipeline stage. It does **not** generate geometry. Tripo and
the Blender algorithms do that. It learns the judgement:
* which fix to try for a given problem on a given kind of asset;
* when to accept;
* when to ask you.

Later, a vision model learns *your* taste from your review notes.

## How the data is produced

1. **Bootstrap.** Run the pipeline with `supervisor: {backend: rules}` (the default). Every
   decision, the outcome of every retry, and every approve/reject note you give is logged to
   `datasets/supervisor/`.
2. **Label.**
   ```bat
   python training\build_dataset.py
   ```
   This keeps only decisions that proved right:
   * retries that fixed or reduced the issues;
   * accepts on assets you approved;
   * escalations.

   Assets are split train/validation by job, so validation contains assets the model has never
   seen.
3. **Volume.** Aim for 200+ examples before the first fine-tune and 1,000+ for a solid model. A
   typical asset produces 8–15 decisions, so that is about 25–100 assets. To get there faster, run
   batches of practice images in a sandbox Tripo project; every run is data.

## Fine-tune (QLoRA, about 10–13 GB VRAM)

1. Install the training dependencies, CUDA PyTorch first. Use WSL2 Ubuntu if a Windows wheel
   gives you trouble.
   ```bat
   pip install torch --index-url https://download.pytorch.org/whl/cu124
   ```
   ```bat
   pip install -r training\requirements-train.txt
   ```
2. Train. Roughly 20–60 minutes for 1,000 examples on a 4080 Super.
   ```bat
   python training\train_lora.py --base Qwen/Qwen3-8B --data training\data --out training\output\forge-supervisor
   ```
3. Merge and convert to GGUF with llama.cpp (`convert_lora_to_gguf.py`, or merge with PEFT then
   `convert_hf_to_gguf.py`, then quantise to Q5_K_M). Save it as
   `training\output\forge-supervisor.gguf`.
4. Serve with Ollama:
   ```bat
   ollama create forge-supervisor -f training\Modelfile
   ```

## Evaluate before you switch

Compare the fine-tuned model with the base model:

```bat
python training\eval_supervisor.py --model forge-supervisor
```
```bat
python training\eval_supervisor.py --model qwen3:8b
```

Switch the guide to `supervisor: {backend: llm}` only when the new model is at least as accurate
as the current one with near-zero invalid answers. Even then, the pipeline falls back to the rules
on any invalid or unsafe answer.

## Visual critique (vision model)

Set `FORGE_VLM_MODEL` (for example `qwen2.5vl:7b` in Ollama) to get an AI critique in every final
review.

`build_dataset.py` also writes `critique.jsonl`, which pairs the renders with your verdict and
notes. Once you have a few hundred reviewed assets, a vision LoRA on that file teaches the critic
your standards. That is roadmap phase 3, and the format is ready now.

## Retraining cycle

Produce assets → review with notes → `build_dataset` → `train_lora` → `eval_supervisor` →
promote if better. Repeat monthly or every ~200 new assets.
