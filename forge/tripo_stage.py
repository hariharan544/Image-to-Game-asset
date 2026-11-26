"""Tripo cloud stages (official `tripo3d` SDK >= 1.0, apiv3).

Every task id is written to the job manifest *before* waiting, so a crash or a
rerun reuses the existing task instead of paying for a new one.

Needs TRIPO_API_KEY (starts with tsk_) in the environment or .env.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from .job import Job

POLL_TIMEOUT_S = 1800


class TripoError(RuntimeError):
    pass


def _client():
    from tripo3d import TripoClient   # imported lazily so the rest of Forge works without it
    return TripoClient()


async def _run(job: Job, client, key: str, submit: Callable[[], Awaitable[str]], out_sub: str) -> tuple[Any, dict]:
    from tripo3d import TaskStatus
    task_id = job.tripo_task(key)
    if not task_id:
        task_id = await submit()
        job.set_tripo_task(key, task_id)
    task = await client.wait_for_task(task_id, timeout=POLL_TIMEOUT_S)
    if task.status != TaskStatus.SUCCESS:
        # a failed task must not be reused on the next run
        job.m["tripo_tasks"].pop(key, None)
        job.save()
        raise TripoError(f"Tripo task {key} ({task_id}) ended {task.status.value}: {task.error_message}")
    out_dir = job.path("tripo", out_sub, ".keep").parent
    files = await client.download_task_models(task, str(out_dir))
    credits = job.m.setdefault("credits", {})
    credits[key] = task.credits_consumed
    job.save()
    return task, {k: v for k, v in files.items() if v}


def _gen_kwargs(job: Job) -> dict:
    g = job.spec.generation
    kw: dict[str, Any] = dict(texture=True, pbr=True, texture_quality=g.texture_quality,
                              geometry_quality=g.geometry_quality, generate_parts=g.generate_parts)
    if g.model_version:
        kw["model_version"] = g.model_version
    if g.face_limit:
        kw["face_limit"] = g.face_limit
    if g.seed is not None:
        kw["model_seed"] = g.seed
    return kw


async def concept_views(job: Job) -> dict:
    """One image -> front/left/back/right views (Tripo image-to-multiview)."""
    async with _client() as client:
        _, files = await _run(job, client, "multiview",
                              lambda: client.image_to_multiview(job.m["source_image"]), "multiview")
    views = {k.replace("_view", ""): v for k, v in files.items() if k.endswith("_view")}
    if "front" not in views:
        raise TripoError(f"multiview task returned no front view: {sorted(files)}")
    return views


async def generate(job: Job) -> dict:
    """Image(s) -> textured 3D model, optional segmentation, optional rig."""
    spec = job.spec
    out: dict[str, Any] = {}
    async with _client() as client:
        kw = _gen_kwargs(job)
        if spec.generation.use_multiview and job.tripo_task("multiview"):
            mv_task = job.tripo_task("multiview")
            submit = lambda: client.multiview_to_model(mv_task, **kw)      # noqa: E731
        elif spec.extra_images:
            base = Path(job.m["source_image"]).parent
            views = [job.m["source_image"]] + [
                str(base / spec.extra_images[v]) if v in spec.extra_images else None
                for v in ("left", "back", "right")]
            submit = lambda: client.multiview_to_model(views, **kw)        # noqa: E731
        else:
            submit = lambda: client.image_to_model(job.m["source_image"], **kw)  # noqa: E731
        gen_task, files = await _run(job, client, "generate", submit, "generate")
        model_task_id = gen_task.task_id
        out["generated"] = files.get("pbr_model") or files.get("model")

        if spec.generation.segment:
            seg_task, _ = await _run(job, client, "segment",
                                     lambda: client.mesh_segment(model_task_id), "segment")
            done, files = await _run(job, client, "complete",
                                     lambda: client.mesh_complete(seg_task.task_id, completion_mode="ai_completion"),
                                     "complete")
            model_task_id = done.task_id
            out["generated"] = files.get("model") or out["generated"]

        if spec.rig.enabled:
            check, _ = await _run(job, client, "rig_check", lambda: client.rig_check(model_task_id), "rig_check")
            if check.output.riggable is False:
                raise TripoError("Tripo reports the model is not riggable (check pose / proportions)")
            detected = getattr(check.output.rig_type, "value", check.output.rig_type)
            rig_type = spec.rig.rig_type or detected or "biped"
            _, files = await _run(job, client, "rig", lambda: client.rig(
                model_task_id, model=spec.rig.model_version, rig_type=rig_type,
                spec=spec.rig.spec, out_format="glb"), "rig")
            out["rigged"] = files.get("model")
            out["rig_type"] = rig_type
    out["source_for_blender"] = out.get("rigged") or out["generated"]
    if not out["source_for_blender"]:
        raise TripoError("Tripo returned no model file")
    return out


def run(coro):
    return asyncio.run(coro)
