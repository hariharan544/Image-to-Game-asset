"""forge - command line for the creative director.

  forge run      guides/my_game.yaml [--asset knight]     run / resume assets
  forge status   [--jobs jobs]                            where every asset is
  forge review   jobs/knight --checkpoint final --approve [--notes "..."]
  forge review   jobs/knight --checkpoint final --reject --notes "cape clips" --redo-from retopo
  forge review   jobs/knight --reject --notes "mobile textures too blurry" --redo-from bake@unity
  forge setup-blender [--blender PATH]                    find + verify Blender, GPU, add-ons, smoke test
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
from .pipeline import STAGE_NAMES, Pipeline, split_key, stage_order
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
        image = (guide.base_dir / spec.image).resolve() if spec.image else None
        model = (guide.base_dir / spec.model).resolve() if spec.model else None
        rig_model = (guide.base_dir / spec.rig_model).resolve() if spec.rig_model else None
        missing = [str(p) for p in (image, model, rig_model) if p is not None and not p.exists()]
        if missing:
            print(f"[{spec.name}] input file not found: {', '.join(missing)}", file=sys.stderr)
            rc = 1
            continue
        if model is not None:
            if model.suffix.lower() not in (".glb", ".gltf", ".fbx", ".obj"):
                print(f"[{spec.name}] model must be .glb, .gltf, .fbx or .obj: {model}", file=sys.stderr)
                rc = 1
                continue
            spec = spec.model_copy(update={"model": str(model),
                                           "rig_model": str(rig_model) if rig_model else None})
            print(f"[{spec.name}] starting from your model {model.name} (no Tripo API credits used)")
        job = Job.open(a.jobs, spec, image or model)
        status = Pipeline(job, rec).run()
        rc = rc or (0 if status in (DONE, AWAITING_REVIEW) else 1)
    return rc


def cmd_status(a) -> int:
    root = Path(a.jobs)
    for m in sorted(root.glob("*/manifest.json")):
        job = Job.load(m.parent)
        stages = job.m["stages"]
        cur = next((s for s in stage_order(job.spec.engines)
                    if stages.get(s, {}).get("status") not in ("done", "skipped")), "-")
        credits = sum(v or 0 for v in job.m.get("credits", {}).values())
        wait = f" waiting on '{job.m.get('waiting_on')}'" if job.m["status"] == AWAITING_REVIEW else ""
        print(f"{job.m['asset']:24} {job.m['status']:16} stage={cur:18} credits={credits:<6g}{wait}")
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
        order = stage_order(job.spec.engines)
        name, target = split_key(a.redo_from)
        if name not in STAGE_NAMES or (target and target not in job.spec.engines):
            print(f"--redo-from must be a stage ({', '.join(STAGE_NAMES)}), optionally @engine "
                  f"({', '.join(job.spec.engines)})", file=sys.stderr)
            return 2
        idx = next(i for i, k in enumerate(order)
                   if split_key(k)[0] == name and (target is None or split_key(k)[1] in (None, target)))
        if name in ("concept", "generate"):          # new cloud generation (spends credits)
            keys = ["generate", "segment", "complete", "texture", "rig_check", "rig"]
            if name == "concept":
                keys.append("multiview")
                job.m["artifacts"].pop("concept_views", None)
            for k in keys:
                job.m["tripo_tasks"].pop(k, None)
            job.m["artifacts"].pop("tripo", None)
        # with @engine only that target is rebuilt; shared later stages (final review) always reset
        reset = [k for k in order[idx:]
                 if not (target and split_key(k)[1] and split_key(k)[1] != target)]
        blends = job.m["artifacts"].get("blend", {})
        for k in reset:
            job.m["stages"].pop(k, None)
            blends.pop(k, None)
        for c in list(job.m["checkpoints"]):
            if c == "final" or c.startswith("escalation_") or (c == "concept" and name == "concept"):
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
    from .tripo_key import resolve
    key, region, source = resolve()
    good = bool(key) and key.startswith("tsk_")
    print(f"Tripo API key   : {('found via ' + source + ', region ' + region) if good else 'MISSING (run: tripo login --region ov, or set TRIPO_API_KEY in .env)'}")
    ok &= good
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


def cmd_setup_blender(a) -> int:
    from .setup_blender import run
    return run(a.blender, a.jobs, Path.cwd() / ".env", a.skip_smoke_test, addon_trial=a.addon_trial,
               addon_trial2=a.addon_trial2)


def cmd_report(a) -> int:
    """A short, paste-able text summary of a job (instead of sending files)."""
    job = Job.load(a.job)
    m = job.m
    out = [f"JOB {m['asset']}: {m['status']}" + (f" (waiting on {m.get('waiting_on')})" if m.get("waiting_on") else "")]
    tr = m["artifacts"].get("tripo", {})
    out.append(f"source: {tr.get('source', 'tripo api')}  rig file: {'yes' if tr.get('rig_source') else 'no'}")
    for key in stage_order(job.spec.engines):
        st = m["stages"].get(key)
        if not st:
            continue
        att = (st.get("attempts") or [{}])[-1]
        r = att.get("result") or {}
        name = key.split("@")[0]
        info = ""
        if name == "cleanup":
            info = (f"parts={r.get('parts')} rigged={r.get('rigged')} bones={r.get('bone_count')} "
                    f"height={round(r.get('height_m') or 0, 3)}m merged={len(r.get('merged_into_body') or [])}")
        elif name == "retopo":
            info = " ".join(f"{p}:{v.get('tris_after')}tris/{v.get('method')}" for p, v in r.get("parts", {}).items())
            if r.get("fused"):
                info += " fused=" + ",".join(f"{p}:{f['shells_before']}->{f['shells_after']}shells"
                                             for p, f in r["fused"].items())
        elif name == "uv":
            info = " ".join(f"{p}:util={v.get('utilization')} overlap={v.get('overlap_pct')} {v.get('packer')}"
                            for p, v in r.get("parts", {}).items())
        elif name == "bake":
            info = " ".join(f"{p}:misses={v.get('bake_miss_ratio')} metal={(v.get('metallic_cleanup') or {}).get('metal_pct')}%"
                            for p, v in r.get("parts", {}).items())
        elif name == "skin":
            a_ = r.get("arp") or {}
            info = f"{r.get('rig_system')} refs={a_.get('placed')} deform={a_.get('deform_bones')}"
            if r.get("arp_fallback_reason"):
                info += f" FALLBACK: {r['arp_fallback_reason'][:120]}"
        elif name == "metrics":
            for p, v in r.get("parts", {}).items():
                me, w = v.get("mesh", {}), v.get("weights", {})
                info += (f"{p}: tris={me.get('tris')} shells={me.get('shells')} holes(boundary)={me.get('boundary_edges')} "
                         f"ngons={me.get('ngons')} over_influence={w.get('verts_over_influence_limit')} ")
        issues = [f"{i['code']}({i['severity'][0]})" for i in att.get("issues", [])]
        dec = (att.get("decision") or {}).get("action", "")
        out.append(f"  {key:22} {st.get('status'):16} {info} {' '.join(issues)} {('-> ' + dec) if dec else ''}".rstrip())
        if att.get("error"):
            out.append(f"      ERROR: {att['error'].splitlines()[0][:200]}")
    for c, v in m.get("checkpoints", {}).items():
        out.append(f"review {c}: {v.get('status')} {v.get('notes', '')}")
    print("\n".join(out))
    return 0


def cmd_install_addon(a) -> int:
    """Install + enable the "Send to Forge" panel in the user's Blender."""
    from .blender import BlenderError, find_blender, run_stage
    root = Path(__file__).resolve().parent.parent
    blender = [a.blender] if a.blender else find_blender()
    if not blender:
        print("Blender not found (run `forge setup-blender` first)", file=sys.stderr)
        return 1
    venv = root / ".venv" / ("Scripts/forge.exe" if os.name == "nt" else "bin/forge")
    print("Close every Blender window first - an open Blender overwrites the preferences when it quits.")
    try:
        res = run_stage("install_addon", {"src": str(root / "blender_addon" / "forge_send"),
                                          "project": str(root), "forge_exe": str(venv) if venv.exists() else None},
                        Path(a.jobs) / "_setup" / "logs" / "install_addon.log",
                        blender=blender, factory_startup=False)
    except BlenderError as exc:
        print(f"[X] install failed: {exc}", file=sys.stderr)
        return 1
    if not res.get("enabled"):
        print(f"[X] installed to {res['installed_to']} but could not be enabled: {res.get('errors')}")
        return 1
    print(f"[OK] Forge panel installed and enabled ({res['installed_to']}).")
    print("     Open Blender > 3D Viewport > press N > 'Forge' tab.")
    return 0


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
    v.add_argument("--redo-from", help=f"restart from this stage ({', '.join(STAGE_NAMES)}); "
                                       "add @unreal or @unity to rebuild only that target")
    v.set_defaults(fn=cmd_review)

    b = sub.add_parser("setup-blender", help="find and verify Blender, GPU, add-ons; run a smoke test")
    b.add_argument("--blender", help="path to blender.exe (saved to .env as FORGE_BLENDER)")
    b.add_argument("--skip-smoke-test", action="store_true")
    b.add_argument("--addon-trial", action="store_true",
                   help="run Quad Remesher / Auto-Rig Pro / UVPackmaster for real in a windowed Blender")
    b.add_argument("--addon-trial2", action="store_true",
                   help="Auto-Rig Pro full flow (rig, bind, engine export) + a real UVPackmaster pack")
    b.set_defaults(fn=cmd_setup_blender)

    rp = sub.add_parser("report", help="short text summary of a job, to paste into a chat")
    rp.add_argument("job", help="job folder, e.g. jobs\\bull")
    rp.set_defaults(fn=cmd_report)

    ia = sub.add_parser("install-blender-addon", help="install the 'Send to Forge' panel into Blender")
    ia.add_argument("--blender", help="path to blender.exe (default: the one Forge uses)")
    ia.set_defaults(fn=cmd_install_addon)

    c = sub.add_parser("check", help="verify the environment")
    c.set_defaults(fn=cmd_check)

    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
