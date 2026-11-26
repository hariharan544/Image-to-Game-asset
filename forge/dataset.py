"""Training-data recorder.

Every supervisor decision is appended to <data_dir>/decisions.jsonl together
with what happened next (did the retry fix the issues?). Every director review
is appended to <data_dir>/reviews.jsonl. training/build_dataset.py turns these
into fine-tuning examples:

  decision examples  observation -> action, kept when the action led to an
                     accepted stage AND the director approved the final asset
  critique examples  renders + concept -> director's notes (for the vision model)
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Optional


class DatasetRecorder:
    def __init__(self, data_dir: str | Path):
        self.dir = Path(data_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.decisions = self.dir / "decisions.jsonl"
        self.reviews = self.dir / "reviews.jsonl"

    def _append(self, path: Path, rec: dict) -> None:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, default=str) + "\n")

    def record_decision(self, job: str, observation: dict, decision: dict) -> str:
        rid = uuid.uuid4().hex
        self._append(self.decisions, {
            "id": rid, "time": time.time(), "job": job,
            "observation": observation, "decision": decision,
        })
        return rid

    def record_outcome(self, decision_id: str, outcome: dict[str, Any]) -> None:
        """Outcome of the attempt that followed a decision (issues after the retry)."""
        self._append(self.decisions, {"outcome_for": decision_id, "time": time.time(), **outcome})

    def record_review(self, job: str, checkpoint: str, status: str, notes: str,
                      images: list[str], reference_images: list[str], ai_critique: Optional[dict]) -> None:
        self._append(self.reviews, {
            "time": time.time(), "job": job, "checkpoint": checkpoint, "status": status,
            "notes": notes, "images": images, "reference_images": reference_images,
            "ai_critique": ai_critique,
        })

    # ------------------------------------------------------------------ reading
    @staticmethod
    def read_jsonl(path: Path) -> list[dict]:
        if not path.exists():
            return []
        with open(path, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]
