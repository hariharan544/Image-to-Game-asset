"""Tripo stage against a fake client: request shapes, the parts->texture chain, resume, key lookup."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

tripo3d = pytest.importorskip("tripo3d")
from tripo3d import TaskStatus  # noqa: E402

from forge import tripo_key, tripo_stage  # noqa: E402
from forge.job import Job  # noqa: E402
from forge.spec import resolve_asset  # noqa: E402


class FakeClient:
    def __init__(self, tmp: Path):
        self.tmp, self.calls, self.n = tmp, [], 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return None

    def _id(self, kind):
        self.n += 1
        return f"task_{kind}_{self.n}"

    async def image_to_model(self, image, **kw):
        self.calls.append(("image_to_model", kw))
        return self._id("gen")

    async def multiview_to_model(self, images, **kw):
        self.calls.append(("multiview_to_model", {"images": images, **kw}))
        return self._id("gen")

    async def upload_file(self, path):
        self.calls.append(("upload_file", {"path": str(path)}))
        return {"file_token": "file_ref"}

    async def create_task(self, data):
        self.calls.append(("create_task", data))
        return self._id(data["type"])

    async def rig_check(self, task_id):
        self.calls.append(("rig_check", {"input": task_id}))
        return self._id("rigcheck")

    async def rig(self, task_id, **kw):
        self.calls.append(("rig", {"input": task_id, **kw}))
        return self._id("rig")

    async def wait_for_task(self, task_id, timeout=None):
        out = SimpleNamespace(riggable=True, rig_type="biped")
        return SimpleNamespace(task_id=task_id, status=TaskStatus.SUCCESS, output=out,
                               error_message=None, credits_consumed=10)

    async def download_task_models(self, task, out_dir):
        p = Path(out_dir) / f"{task.task_id}.glb"
        p.write_bytes(b"glb")
        return {"model": str(p)}


def _job(tmp_path, **over):
    img = tmp_path / "hero.png"
    img.write_bytes(b"png")
    spec = resolve_asset({"name": "hero", "image": str(img), "type": "humanoid", "overrides": over}, {})
    return Job.open(tmp_path / "jobs", spec, img)


def test_parts_are_generated_untextured_then_textured_then_rigged(tmp_path, monkeypatch):
    fake = FakeClient(tmp_path)
    monkeypatch.setattr(tripo_stage, "_client", lambda: fake)
    job = _job(tmp_path, generation={"use_multiview": False})
    out = asyncio.run(tripo_stage.generate(job))
    kinds = [c[0] for c in fake.calls]
    assert kinds == ["image_to_model", "upload_file", "create_task", "rig_check", "rig"]
    gen = fake.calls[0][1]
    assert gen["model_version"] == "v3.1-20260211" and gen["generate_parts"] is True
    assert gen["texture"] is False and gen["pbr"] is False            # API rejects parts+texture
    tex = fake.calls[2][1]
    assert tex["type"] == "texture_model" and tex["input"].startswith("task_gen")
    assert tex["model"] == "v3.5-20260815" and tex["pbr"] and tex["delight"]
    assert tex["texture_prompt"] == {"image": "file_ref"}
    rig = fake.calls[4][1]
    assert rig["input"].startswith("task_texture") and rig["spec"] == "unreal"
    assert rig["model"] == "v3.0-20260909" and rig["out_format"] == "glb"
    assert out["source_for_blender"].endswith(".glb") and "rig" in Path(out["source_for_blender"]).name

    # resume: every task id was saved, so a rerun submits nothing new
    fake2 = FakeClient(tmp_path)
    monkeypatch.setattr(tripo_stage, "_client", lambda: fake2)
    asyncio.run(tripo_stage.generate(Job.load(job.root)))
    assert [c[0] for c in fake2.calls] == []


def test_without_parts_generation_is_textured_directly(tmp_path, monkeypatch):
    fake = FakeClient(tmp_path)
    monkeypatch.setattr(tripo_stage, "_client", lambda: fake)
    job = _job(tmp_path, generation={"use_multiview": False, "generate_parts": False}, rig={"enabled": False})
    asyncio.run(tripo_stage.generate(job))
    assert [c[0] for c in fake.calls] == ["image_to_model"]
    assert fake.calls[0][1]["texture"] is True and fake.calls[0][1]["generate_parts"] is False


def test_key_from_tripo_cli_login(tmp_path, monkeypatch):
    monkeypatch.delenv("TRIPO_API_KEY", raising=False)
    monkeypatch.delenv("TRIPO_PROFILE", raising=False)
    monkeypatch.setenv("TRIPO_HOME", str(tmp_path))
    assert tripo_key.resolve()[0] is None
    (tmp_path / "config.json").write_text(json.dumps({
        "active_profile": "work", "profiles": {"default": {"api_key": "tsk_a"},
                                               "work": {"api_key": "tsk_b", "region": "ov"}}}))
    key, region, source = tripo_key.resolve()
    assert key == "tsk_b" and region == "ov" and "work" in source
    monkeypatch.setenv("TRIPO_API_KEY", "tsk_env")
    assert tripo_key.resolve()[0] == "tsk_env"
