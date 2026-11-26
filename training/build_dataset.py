"""Turn pipeline logs into fine-tuning data for the local AI supervisor.

    python training/build_dataset.py --data datasets/supervisor --out training/data

Reads   decisions.jsonl  (every supervisor decision + the outcome of the retry)
        reviews.jsonl    (every director verdict + notes)
Writes  decisions_train.jsonl / decisions_val.jsonl   chat format, text only
        critique.jsonl                                 vision examples (renders -> director notes)
        stats.json

Labeling policy - only decisions that turned out right become examples:
  retry action    kept if the next attempt resolved the blocking issues, or reduced them
  accept          kept unless the director later rejected that asset's final review
  escalate        kept when the director then had to decide (that is what escalation is for)
A director's rejection notes are also kept as critique examples - they teach the
vision model what you, specifically, care about.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from forge.dataset import DatasetRecorder  # noqa: E402
from forge.supervisor.base import Observation  # noqa: E402
from forge.supervisor.prompt import CRITIQUE_SYSTEM, SYSTEM, assistant_message, user_message  # noqa: E402


def _final_verdicts(reviews: list[dict]) -> dict[str, tuple[str, float]]:
    """job -> (status, time) of the latest final review."""
    out: dict[str, tuple[str, float]] = {}
    for r in reviews:
        if r.get("checkpoint") == "final":
            if r["job"] not in out or r["time"] >= out[r["job"]][1]:
                out[r["job"]] = (r["status"], r["time"])
    return out


def label(decisions: list[dict], reviews: list[dict], include_unreviewed: bool) -> list[dict]:
    outcomes = {r["outcome_for"]: r for r in decisions if "outcome_for" in r}
    verdicts = _final_verdicts(reviews)
    examples = []
    for d in decisions:
        if "observation" not in d:
            continue
        action = d["decision"]["action"]
        obs = d["observation"]
        n_err = sum(1 for i in obs["issues"] if i.get("severity", "error") == "error")
        verdict = verdicts.get(d["job"], (None, 0))
        decided_before_verdict = verdict[0] is None or d["time"] <= verdict[1]
        keep, why = False, ""
        if action == "accept":
            if verdict[0] == "rejected" and decided_before_verdict:
                why = "asset rejected by director"
            elif verdict[0] is None and not include_unreviewed:
                why = "asset not reviewed yet"
            else:
                keep, why = True, "accepted and asset approved"
        elif action == "escalate":
            keep, why = True, "escalation"
        else:
            out = outcomes.get(d["id"])
            if out is None:
                why = "no outcome recorded"
            elif out.get("resolved") or out.get("error_count", n_err) < n_err:
                keep, why = True, "retry fixed or reduced the issues"
            else:
                why = "retry did not help"
        if keep:
            examples.append({"id": d["id"], "job": d["job"], "why": why, "observation": obs,
                             "action": action, "reason": d["decision"].get("reason", "")})
    return examples


def to_chat(ex: dict) -> dict:
    obs = Observation(**ex["observation"])
    return {"id": ex["id"], "messages": [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": user_message(obs)},
        {"role": "assistant", "content": assistant_message(ex["action"], ex["reason"])},
    ]}


def critique_examples(reviews: list[dict]) -> list[dict]:
    out = []
    for r in reviews:
        if r.get("checkpoint") != "final" or not r.get("images"):
            continue
        verdict = "approve" if r["status"] == "approved" else "needs_work"
        obs = [s.strip() for s in (r.get("notes") or "").replace("\n", ";").split(";") if s.strip()]
        if verdict == "needs_work" and not obs:
            continue        # a rejection without notes teaches nothing
        out.append({"system": CRITIQUE_SYSTEM, "reference_images": r.get("reference_images", []),
                    "images": r["images"], "target": json.dumps({"verdict": verdict, "observations": obs})})
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--data", default="datasets/supervisor")
    p.add_argument("--out", default="training/data")
    p.add_argument("--val-fraction", type=float, default=0.1)
    p.add_argument("--include-unreviewed", action="store_true",
                   help="keep 'accept' decisions of assets the director has not reviewed yet")
    a = p.parse_args(argv)

    data, out = Path(a.data), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    decisions = DatasetRecorder.read_jsonl(data / "decisions.jsonl")
    reviews = DatasetRecorder.read_jsonl(data / "reviews.jsonl")
    examples = label(decisions, reviews, a.include_unreviewed)

    # split by job so the validation set contains assets the model never saw
    def bucket(job: str) -> float:
        return int(hashlib.sha1(job.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    train = [to_chat(e) for e in examples if bucket(e["job"]) >= a.val_fraction]
    val = [to_chat(e) for e in examples if bucket(e["job"]) < a.val_fraction]
    random.Random(0).shuffle(train)
    for name, rows in (("decisions_train.jsonl", train), ("decisions_val.jsonl", val),
                       ("critique.jsonl", critique_examples(reviews))):
        with open(out / name, "w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row) + "\n")
    by_action = defaultdict(int)
    for e in examples:
        by_action[e["action"]] += 1
    stats = {"decisions_logged": sum(1 for d in decisions if "observation" in d),
             "examples": len(examples), "train": len(train), "val": len(val),
             "by_action": dict(sorted(by_action.items()))}
    (out / "stats.json").write_text(json.dumps(stats, indent=2))
    print(json.dumps(stats, indent=2))
    if len(examples) < 200:
        print("note: fewer than 200 examples - keep producing assets with the rules supervisor "
              "before fine-tuning (see training/README.md)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
