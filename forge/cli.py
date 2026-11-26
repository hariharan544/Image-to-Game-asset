"""forge - command line for the creative director.

  forge run      guides/my_game.yaml [--asset knight]     run / resume assets
  forge status   [--jobs jobs]                            where every asset is
  forge review   jobs/knight --checkpoint final --approve [--notes "..."]
  forge review   jobs/knight --checkpoint final --reject --notes "cape clips" --redo-from retopo
  forge check                                             verify Blender, Tripo key, AI supervisor
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .blender import find_blender
from .dataset import DatasetRecorder
from .job import AWAITING_REVIEW, DONE, PENDING, Job
from .pipeline import ORDER, Pipeline
from .spec import load_guide


def _load_dotenv() -> None:
    env = Path.cwd() / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def cmd_run(a) -> int:
    guide = load_guide(a.guide)
    rec = DatasetRecorder(a.data)
    assets = [x for x in guide.assets if not a.asset or x.name in a.asset]
    if not assets:
        print("no matching assets in guide", file=sys.stderr)
        return 2
    rc = 0
    for spec in assets:
        image = (guide.base_dir / spec.image).resolve()
        if not image.exists():
            print(f"[{spec.name}] input image not found: {image}", file=sys.stderr)
            rc = 1
            continue
        job = Job.open(a.jobs, spec, image)
        status = Pipeline(job, rec).run()
        rc = rc or (0 if status in (DONE, AWAITING_REVIEW) else 1)
    return rc


def cmd_status(a) -> int:
    root = Path(a.jobs)
    for m in sorted(root.glob("*/manifest.json")):
        job = Job.load(m.parent)
        stages = job.m["stages"]
        cur = next((s for s in ORDER if stages.get(s, {}).get("status") not in ("done", "skipped")), "-")
        credits = sum(v or 0 for v in job.m.get("credits", {}).values())
        wait = f" waiting on '{job.m.get('waiting_on')}'" if job.m["status"] == AWAITING_REVIEW else ""
        print(f"{job.m['asset']:24} {job.m['status']:16} stage={cur:12} credits={credits:<6g}{wait}")
    return 0


def cmd_review(a) -> int:
    job = Job.load(a.job)
    cp = a.checkpoint or job.m.get("waiting_on")
    if not cp:
        print("nothing is waiting for review", file=sys.stderr)
        return 2
    status = "approved" if a.approve else "rejected"
    job.set_checkpoint(cp, status, a.notes or "")
    if cp == "final":
        imgs = job.artifact("previews") or []
    else:
        imgs = list((job.artifact("concept_views") or {}).values())
    DatasetRecorder(a.data).record_review(str(job.root), cp, status, a.notes or "", imgs,
                                          [job.m["source_image"]], job.artifact("ai_critique"))

    if cp.startswith("escalation_") and a.approve:
        # director accepts the last attempt of an escalated stage as it is
        stage = cp.removeprefix("escalation_")
        last = (job.stage(stage).get("attempts") or [{}])[-1]
        if last.get("blend"):
            job.m["artifacts"].setdefault("blend", {})[stage] = last["blend"]
        job.set_stage(stage, "done", accepted_by="director")
    if a.redo_from:
        if a.redo_from not in ORDER:
            print(f"--redo-from must be one of {ORDER}", file=sys.stderr)
            return 2
        idx = ORDER.index(a.redo_from)
        if idx <= ORDER.index("generate"):       # new cloud generation (spends credits)
            keys = ["generate", "segment", "complete", "rig_check", "rig"]
            if a.redo_from == "concept":
                keys.append("multiview")
                job.m["artifacts"].pop("concept_views", None)
            for k in keys:
                job.m["tripo_tasks"].pop(k, None)
            job.m["artifacts"].pop("tripo", None)
        for s in ORDER[idx:]:
            job.m["stages"].pop(s, None)
        blends = job.m["artifacts"].get("blend", {})
        for s in ORDER[idx:]:
            blends.pop(s, None)
        for c in list(job.m["checkpoints"]):
            if c == "final" or c.startswith("escalation_") or (c == "concept" and idx == 0):
                job.m["checkpoints"].pop(c)
    job.m["status"] = PENDING
    job.m.pop("waiting_on", None)
    job.save()
    print(f"{job.m['asset']}: {cp} {status}. Continue with: forge run <guide> --asset {job.m['asset']}")
    return 0


def cmd_check(a) -> int:
    ok = True
    b = find_blender()
    print(f"Blender         : {b[0] if b else 'NOT FOUND (install Blender or set FORGE_BLENDER)'}")
    ok &= bool(b)
    key = os.environ.get("TRIPO_API_KEY", "")
    print(f"TRIPO_API_KEY   : {'set' if key.startswith('tsk_') else 'MISSING (put it in .env)'}")
    ok &= key.startswith("tsk_")
    try:
        import tripo3d
        print(f"tripo3d SDK     : {tripo3d.__version__}")
    except ImportError:
        print("tripo3d SDK     : NOT INSTALLED (pip install -e .)")
        ok = False
    from .supervisor import LLMSupervisor
    s = LLMSupervisor()
    print(f"AI supervisor   : {s.url} model={s.model} -> {'reachable' if s.available() else 'offline (rules will be used)'}")
    return 0 if ok else 1


def main(argv=None) -> int:
    _load_dotenv()
    p = argparse.ArgumentParser(prog="forge", description="Image -> game-ready 3D asset pipeline")
    p.add_argument("--jobs", default="jobs", help="job folder (default: jobs)")
    p.add_argument("--data", default="datasets/supervisor", help="training-data folder")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="run or resume assets from a creative guide")
    r.add_argument("guide")
    r.add_argument("--asset", action="append", help="only this asset (repeatable)")
    r.set_defaults(fn=cmd_run)

    s = sub.add_parser("status", help="show every job")
    s.set_defaults(fn=cmd_status)

    v = sub.add_parser("review", help="approve or reject a checkpoint")
    v.add_argument("job")
    v.add_argument("--checkpoint", help="concept | final | escalation_<stage> (default: what the job waits on)")
    g = v.add_mutually_exclusive_group(required=True)
    g.add_argument("--approve", action="store_true")
    g.add_argument("--reject", action="store_true")
    v.add_argument("--notes", help="what is wrong / right - this becomes AI training data")
    v.add_argument("--redo-from", help=f"restart from this stage: {', '.join(ORDER)}")
    v.set_defaults(fn=cmd_review)

    c = sub.add_parser("check", help="verify the environment")
    c.set_defaults(fn=cmd_check)

    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
