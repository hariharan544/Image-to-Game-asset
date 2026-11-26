"""Measure how well a supervisor model agrees with the labelled decisions.

    python training/eval_supervisor.py --data training/data/decisions_val.jsonl
    python training/eval_supervisor.py --model qwen3:8b       # compare with an un-tuned base model

Uses the same OpenAI-compatible endpoint as the pipeline (FORGE_LLM_URL /
FORGE_LLM_MODEL). Reports exact-action accuracy, invalid answers, and the rule
supervisor's accuracy on the same set as a baseline. Promote a new model to
production (FORGE_LLM_MODEL) only when it beats the current one here.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from forge.supervisor.llm import LLMSupervisor, _extract_json  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--data", default="training/data/decisions_val.jsonl")
    p.add_argument("--model", help="model name on the server (default FORGE_LLM_MODEL)")
    p.add_argument("--limit", type=int, default=0)
    a = p.parse_args()

    rows = [json.loads(l) for l in open(a.data, encoding="utf-8") if l.strip()]
    if a.limit:
        rows = rows[:a.limit]
    if not rows:
        print("no evaluation rows")
        return 1
    sup = LLMSupervisor(model=a.model)
    if not sup.available():
        print(f"model server {sup.url} is not reachable")
        return 1
    hits = invalid = 0
    confusion: Counter = Counter()
    for r in rows:
        want = json.loads(r["messages"][-1]["content"])["action"]
        allowed = [line.split(":")[0][2:] for line in r["messages"][1]["content"].split("ALLOWED ACTIONS:\n")[1].splitlines()]
        text = sup._chat(sup.model, r["messages"][:-1])
        got = (_extract_json(text) or {}).get("action")
        if got not in allowed:
            invalid += 1
            got = f"INVALID({got})"
        hits += got == want
        if got != want:
            confusion[(want, got)] += 1
    n = len(rows)
    print(f"model={sup.model}  n={n}  accuracy={hits / n:.1%}  invalid={invalid / n:.1%}")
    for (want, got), c in confusion.most_common(10):
        print(f"  expected {want:24} got {got:24} x{c}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
