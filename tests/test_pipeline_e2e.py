"""Full pipeline run with Tripo replaced by a local fixture model.

Needs Blender: either the `bpy` pip module in this Python, or FORGE_BLENDER /
blender on PATH. Skipped otherwise.
"""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

from forge.blender import find_blender
from forge.cli import main as cli
from forge.dataset import DatasetRecorder
from forge.job import Job
from forge.pipeline import Pipeline
from forge.spec import resolve_asset

ROOT = Path(__file__).resolve().parent.parent
pytestmark = pytest.mark.skipif(find_blender() is None, reason="Blender / bpy not available")


class FakeTripo:
    """Stands in for forge.tripo_stage: returns the fixture instead of calling the cloud."""

    def __init__(self, model: Path):
        self.model = model
        self.calls = 0

    @staticmethod
    def run(value):
        return value

    def concept_views(self, job):
        raise AssertionError("concept stage should be skipped in this test")

    def generate(self, job):
        self.calls += 1
        return {"generated": str(self.model), "rigged": str(self.model), "source_for_blender": str(self.model)}


@pytest.fixture(scope="module")
def fixture_glb(tmp_path_factory):
    out = tmp_path_factory.mktemp("fx") / "src.glb"
    blender = find_blender()
    script = ROOT / "tests" / "blender" / "make_fixture.py"
    if blender[0] == sys.executable:
        cmd = [sys.executable, str(script), str(out), "--rigged"]
    else:
        cmd = [*blender, "-b", "--factory-startup", "-P", str(script), "--", str(out), "--rigged"]
    subprocess.run(cmd, check=True, capture_output=True)
    return out


def test_full_pipeline_with_review(tmp_path, fixture_glb):
    img = tmp_path / "knight.png"
    img.write_bytes(b"\x89PNG fake")
    spec = resolve_asset({
        "name": "knight", "image": str(img), "type": "humanoid", "tier": "background",
        "detachable_parts": ["sword"], "notes": "test knight",
        "overrides": {
            "generation": {"use_multiview": False},
            "texture": {"size": 256, "samples": 2, "device": "CPU"},
            "topology": {"target_tris": 3000, "target_height_m": 1.8},
            "uv": {"texel_density_px_per_m": 128},
            "rig": {"sockets": {"socket_weapon_r": "hand_r"}},
            "qa": {"min_uv_utilization": 0.1},
        },
    }, {"engines": ["unreal", "unity"]})
    jobs = tmp_path / "jobs"
    rec = DatasetRecorder(tmp_path / "data")
    fake = FakeTripo(fixture_glb)
    job = Job.open(jobs, spec, img)

    status = Pipeline(job, rec, tripo=fake).run()
    assert status == "awaiting_review", job.m
    assert job.m["waiting_on"] == "final"
    review_md = job.root / "review" / "final" / "REVIEW.md"
    assert review_md.exists() and "front.png" in review_md.read_text()

    # director approves -> export
    assert cli(["--jobs", str(jobs), "--data", str(tmp_path / "data"), "review", str(job.root),
                "--approve", "--notes", "looks good"]) == 0
    job = Job.load(job.root)
    assert Pipeline(job, rec, tripo=fake).run() == "done"
    assert fake.calls == 1                                  # resume never re-generates

    ue = job.root / "export" / "unreal"
    un = job.root / "export" / "unity"
    assert (ue / "SK_knight.fbx").exists() and (ue / "SK_knight_Sword.fbx").exists()
    assert (ue / "Textures" / "T_knight_Body_ORM.png").exists()
    assert (un / "knight.fbx").exists() and (un / "Textures" / "knight_Body_MaskMap.png").exists()

    retopo = job.stage("retopo")["attempts"][-1]["result"]
    assert retopo["total_tris"] <= 3000 * 1.05
    metrics = job.stage("metrics")["attempts"][-1]["result"]["parts"]["Body"]
    assert metrics["weights"]["unweighted_verts_pct"] == 0
    assert metrics["uv"]["overlap_pct"] < 0.5

    decisions = rec.read_jsonl(rec.decisions)
    assert {d["observation"]["stage"] for d in decisions if "observation" in d} >= {"cleanup", "retopo", "uv", "bake", "skin"}
    assert rec.read_jsonl(rec.reviews)[0]["status"] == "approved"


def test_supervisor_retries_then_escalates_then_director_accepts(tmp_path, fixture_glb):
    """An impossible UV-stretch limit forces UV_STRETCH: the supervisor walks its playbook,
    escalates to the director, the director accepts the last attempt, the run finishes."""
    img = tmp_path / "p.png"
    img.write_bytes(b"x")
    spec = resolve_asset({
        "name": "tiny", "image": str(img), "type": "prop", "tier": "background",
        "overrides": {"review": {"auto_approve": True},
                      "texture": {"size": 128, "samples": 1, "device": "CPU"},
                      "qa": {"min_uv_utilization": 0.0, "max_texel_density_cv": 0.0001,
                             "max_bake_miss_ratio": 1}},
    }, {"engines": ["unity"]})
    jobs, data = tmp_path / "jobs", tmp_path / "data"
    rec = DatasetRecorder(data)
    job = Job.open(jobs, spec, img)
    assert Pipeline(job, rec, tripo=FakeTripo(fixture_glb)).run() == "awaiting_review"
    assert job.m["waiting_on"] == "escalation_uv"
    attempts = job.stage("uv")["attempts"]
    actions = [a["decision"]["action"] for a in attempts]
    assert actions == ["uv_lower_angle", "uv_min_stretch", "uv_angle_seams", "escalate"]
    # each retry really ran with the changed parameters
    assert attempts[1]["params"]["angle_limit_deg"] == spec.uv.angle_limit_deg - 10
    assert attempts[2]["params"]["method"] == "min_stretch"
    # outcomes of retries are recorded for training
    outcomes = [r for r in rec.read_jsonl(rec.decisions) if "outcome_for" in r]
    assert len(outcomes) == 3 and all(o["resolved"] is False for o in outcomes)

    assert cli(["--jobs", str(jobs), "--data", str(data), "review", str(job.root),
                "--approve", "--notes", "stretch acceptable on a background prop"]) == 0
    job = Job.load(job.root)
    assert Pipeline(job, rec, tripo=FakeTripo(fixture_glb)).run() == "done"
    assert (job.root / "export" / "unity" / "tiny.fbx").exists()
