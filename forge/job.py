"""A job = one asset going through the pipeline. Everything is persisted in
<jobs_dir>/<asset>/manifest.json so a run can stop (crash, review checkpoint)
and resume without redoing finished stages or paying Tripo twice."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Optional

from .spec import AssetSpec

PENDING, RUNNING, DONE, FAILED, AWAITING_REVIEW, SKIPPED = (
    "pending", "running", "done", "failed", "awaiting_review", "skipped")


class Job:
    def __init__(self, root: Path, manifest: dict):
        self.root = root
        self.m = manifest

    # --------------------------------------------------------------- create / load
    @classmethod
    def open(cls, jobs_dir: str | Path, spec: AssetSpec, source_image: Path) -> "Job":
        root = (Path(jobs_dir) / spec.name).resolve()
        path = root / "manifest.json"
        if path.exists():
            job = cls(root, json.loads(path.read_text(encoding="utf-8")))
            job.m["spec"] = spec.model_dump()          # guide edits apply to stages not yet done
            job.save()
            return job
        root.mkdir(parents=True, exist_ok=True)
        m = {
            "asset": spec.name,
            "created": time.time(),
            "source_image": str(source_image),
            "spec": spec.model_dump(),
            "stages": {},
            "tripo_tasks": {},
            "checkpoints": {},
            "artifacts": {},
            "status": PENDING,
        }
        job = cls(root, m)
        job.save()
        return job

    @classmethod
    def load(cls, job_dir: str | Path) -> "Job":
        root = Path(job_dir).resolve()
        return cls(root, json.loads((root / "manifest.json").read_text(encoding="utf-8")))

    def save(self) -> None:
        tmp = self.root / "manifest.json.tmp"
        tmp.write_text(json.dumps(self.m, indent=2, default=str), encoding="utf-8")
        os.replace(tmp, self.root / "manifest.json")

    # --------------------------------------------------------------- helpers
    @property
    def spec(self) -> AssetSpec:
        return AssetSpec(**self.m["spec"])

    def path(self, *parts: str) -> Path:
        p = self.root.joinpath(*parts)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def stage(self, name: str) -> dict:
        return self.m["stages"].setdefault(name, {"status": PENDING, "attempts": []})

    def stage_done(self, name: str) -> bool:
        return self.stage(name)["status"] in (DONE, SKIPPED)

    def set_stage(self, name: str, status: str, **extra: Any) -> None:
        st = self.stage(name)
        st["status"] = status
        st.update(extra)
        self.save()

    def add_attempt(self, name: str, attempt: dict) -> None:
        self.stage(name)["attempts"].append(attempt)
        self.save()

    def tripo_task(self, key: str) -> Optional[str]:
        return self.m["tripo_tasks"].get(key)

    def set_tripo_task(self, key: str, task_id: str) -> None:
        self.m["tripo_tasks"][key] = task_id
        self.save()

    def artifact(self, key: str) -> Optional[str]:
        return self.m["artifacts"].get(key)

    def set_artifact(self, key: str, value: Any) -> None:
        self.m["artifacts"][key] = value
        self.save()

    # --------------------------------------------------------------- review checkpoints
    def checkpoint(self, name: str) -> dict:
        return self.m["checkpoints"].get(name, {"status": PENDING})

    def set_checkpoint(self, name: str, status: str, notes: str = "", reviewer: str = "director") -> None:
        self.m["checkpoints"][name] = {"status": status, "notes": notes, "reviewer": reviewer, "time": time.time()}
        self.save()

    def reset_from(self, stage_order: list[str], first: str) -> None:
        """Mark `first` and every later stage pending (used after a rejection)."""
        hit = False
        for s in stage_order:
            hit = hit or s == first
            if hit and s in self.m["stages"]:
                self.m["stages"][s]["status"] = PENDING
        self.save()
