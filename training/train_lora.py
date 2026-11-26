"""QLoRA fine-tune of the AI supervisor on an RTX 4080 Super (16 GB).

    python training/train_lora.py --base Qwen/Qwen3-8B --data training/data --out training/output/forge-supervisor

4-bit base weights + LoRA adapters keep an 8B model at roughly 10-13 GB of VRAM
with the default settings (batch 1, grad-accum 16, 2048 tokens). Only the
assistant's answer is trained on (the prompt tokens are masked out).

Requires: pip install -r training/requirements-train.txt   (CUDA build of PyTorch)
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="Qwen/Qwen3-8B", help="any chat model on Hugging Face (Apache-2.0 recommended)")
    p.add_argument("--data", default="training/data")
    p.add_argument("--out", default="training/output/forge-supervisor")
    p.add_argument("--epochs", type=float, default=3)
    p.add_argument("--lr", type=float, default=2e-4)
    p.add_argument("--rank", type=int, default=16)
    p.add_argument("--max-len", type=int, default=2048)
    p.add_argument("--grad-accum", type=int, default=16)
    a = p.parse_args()

    import torch
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import (AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, Trainer,
                              TrainingArguments)

    tok = AutoTokenizer.from_pretrained(a.base)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token

    def template(messages, add_generation_prompt):
        kw = dict(tokenize=False, add_generation_prompt=add_generation_prompt)
        try:
            return tok.apply_chat_template(messages, enable_thinking=False, **kw)   # Qwen3: no <think>
        except TypeError:
            return tok.apply_chat_template(messages, **kw)

    def encode(row):
        msgs = row["messages"]
        prompt = template(msgs[:-1], add_generation_prompt=True)
        answer = msgs[-1]["content"] + (tok.eos_token or "")
        p_ids = tok(prompt, add_special_tokens=False)["input_ids"]
        a_ids = tok(answer, add_special_tokens=False)["input_ids"]
        p_ids = p_ids[-(a.max_len - len(a_ids)):]           # keep the end of long prompts
        return {"input_ids": p_ids + a_ids, "labels": [-100] * len(p_ids) + a_ids}

    data = Path(a.data)
    train = [encode(r) for r in load_rows(data / "decisions_train.jsonl")]
    val = [encode(r) for r in load_rows(data / "decisions_val.jsonl")]
    if not train:
        raise SystemExit(f"no training rows in {data}; run training/build_dataset.py first")
    print(f"train={len(train)} val={len(val)}")

    def collate(batch):
        n = max(len(b["input_ids"]) for b in batch)
        ids = torch.full((len(batch), n), tok.pad_token_id, dtype=torch.long)
        lab = torch.full((len(batch), n), -100, dtype=torch.long)
        att = torch.zeros((len(batch), n), dtype=torch.long)
        for i, b in enumerate(batch):
            L = len(b["input_ids"])
            ids[i, :L] = torch.tensor(b["input_ids"])
            lab[i, :L] = torch.tensor(b["labels"])
            att[i, :L] = 1
        return {"input_ids": ids, "labels": lab, "attention_mask": att}

    model = AutoModelForCausalLM.from_pretrained(
        a.base, device_map="auto", torch_dtype=torch.bfloat16,
        quantization_config=BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                               bnb_4bit_compute_dtype=torch.bfloat16,
                                               bnb_4bit_use_double_quant=True))
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
    model = get_peft_model(model, LoraConfig(
        r=a.rank, lora_alpha=a.rank * 2, lora_dropout=0.05, task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]))
    model.print_trainable_parameters()

    args = TrainingArguments(
        output_dir=a.out, num_train_epochs=a.epochs, learning_rate=a.lr,
        per_device_train_batch_size=1, per_device_eval_batch_size=1,
        gradient_accumulation_steps=a.grad_accum, lr_scheduler_type="cosine", warmup_ratio=0.05,
        bf16=True, logging_steps=10, save_strategy="epoch",
        eval_strategy="epoch" if val else "no", report_to="none",
        gradient_checkpointing=True, optim="paged_adamw_8bit", remove_unused_columns=False)
    Trainer(model=model, args=args, train_dataset=train, eval_dataset=val or None,
            data_collator=collate).train()
    model.save_pretrained(Path(a.out) / "adapter")
    tok.save_pretrained(Path(a.out) / "adapter")
    print(f"adapter saved to {Path(a.out) / 'adapter'} - next: training/README.md 'Serve the model'")


if __name__ == "__main__":
    main()
