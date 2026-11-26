"""Full pipeline run with Tripo replaced by a local fixture model.

Needs Blender: either the `bpy` pip module in this Python, or FORGE_BLENDER /
blender on PATH. Skipped otherwise.
"""

from pathlib import Path

import pytest

from forge.blender import find_blender, run_stage
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
    d = tmp_path_factory.mktemp("fx")
    out = d / "src.glb"
    run_stage("fixture", {"out": str(out), "rigged": True}, d / "fixture.log")
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
            "targets": {"unity": {"topology": {"target_tris": 800}, "texture": {"size": 128}}},
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
    # unity = mobile: URP maps, AO folded into the base map (no separate occlusion texture)
    assert (un / "knight.fbx").exists() and (un / "Textures" / "knight_Body_MetallicSmoothness.png").exists()
    assert not (un / "Textures" / "knight_Body_Occlusion.png").exists()

    # two separate builds from one generation: AAA budget vs mobile budget
    aaa = job.stage("retopo@unreal")["attempts"][-1]["result"]["total_tris"]
    mob = job.stage("retopo@unity")["attempts"][-1]["result"]["total_tris"]
    assert aaa <= 3000 * 1.05 and mob <= 800 * 1.05 and mob < aaa
    assert (job.root / "textures" / "unity" / "T_Body_basecolor.png").exists()
    for engine in ("unreal", "unity"):
        m = job.stage(f"metrics@{engine}")["attempts"][-1]["result"]["parts"]["Body"]
        assert m["weights"]["unweighted_verts_pct"] == 0 and m["uv"]["overlap_pct"] < 0.5
    assert (job.root / "review" / "final" / "unity" / "front.png").exists()

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
    assert job.m["waiting_on"] == "escalation_uv@unity"
    attempts = job.stage("uv@unity")["attempts"]
    actions = [a["decision"]["action"] for a in attempts]
    assert actions == ["uv_lower_angle", "uv_min_stretch", "uv_angle_seams", "escalate"]
    # each retry really ran with the changed parameters
    assert attempts[1]["params"]["angle_limit_deg"] == spec.targets["unity"].uv.angle_limit_deg - 10
    assert attempts[2]["params"]["method"] == "min_stretch"
    # outcomes of retries are recorded for training
    # (other stages may also retry - e.g. QuadriFlow output varies run to run on the tiny
    #  mobile budget - so only the UV retries are checked here)
    uv_ids = {d["id"] for d in rec.read_jsonl(rec.decisions)
              if d.get("observation", {}).get("stage") == "uv"
              and d["observation"]["params"].get("method") is not None
              and d["decision"]["action"].startswith("uv_")}
    outcomes = [r for r in rec.read_jsonl(rec.decisions) if r.get("outcome_for") in uv_ids]
    assert len(outcomes) >= 3 and all(o["resolved"] is False for o in outcomes)

    assert cli(["--jobs", str(jobs), "--data", str(data), "review", str(job.root),
                "--approve", "--notes", "stretch acceptable on a background prop"]) == 0
    job = Job.load(job.root)
    assert Pipeline(job, rec, tripo=FakeTripo(fixture_glb)).run() == "done"
    assert (job.root / "export" / "unity" / "tiny.fbx").exists()


def test_user_model_mode_uses_no_tripo_api(tmp_path, fixture_glb, monkeypatch):
    """Option B: start from a model downloaded from Tripo Studio. The Tripo API must not be
    touched; the rest of the pipeline runs as usual."""
    from forge import tripo_stage

    def no_api(*a, **k):
        raise AssertionError("Tripo API must not be called in model mode")
    monkeypatch.setattr(tripo_stage, "_client", no_api)

    guide = tmp_path / "guide.yaml"
    model = tmp_path / "inputs" / "studio_knight.glb"
    model.parent.mkdir()
    model.write_bytes(fixture_glb.read_bytes())
    guide.write_text(f"""
project: T
engines: [unity]
defaults:
  review: {{auto_approve: true}}
assets:
  - name: knight
    model: inputs/studio_knight.glb
    type: humanoid
    tier: background
    detachable_parts: [sword]
    overrides:
      texture: {{size: 128, samples: 1, device: CPU}}
      qa: {{min_uv_utilization: 0.0, max_texel_density_cv: 5, max_bake_miss_ratio: 1}}
""")
    jobs = tmp_path / "jobs"
    assert cli(["--jobs", str(jobs), "--data", str(tmp_path / "d"), "run", str(guide)]) == 0
    job = Job.load(jobs / "knight")
    assert job.m["status"] == "done"
    assert job.stage("concept")["status"] == "skipped"
    assert job.artifact("tripo")["source"] == "user_model"
    assert (job.root / "source" / "studio_knight.glb").exists()
    assert (jobs / "knight" / "export" / "unity" / "knight.fbx").exists()


def test_asset_needs_image_or_model():
    from forge.spec import resolve_asset
    with pytest.raises(Exception):
        resolve_asset({"name": "x", "type": "prop"}, {})


SPLIT_RIG = r'''
import bpy, sys
src, dense_out, rig_out = sys.argv[1:4]
# dense model: same character, skeleton removed, denser mesh
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=src)
for o in [o for o in bpy.data.objects if o.type == "ARMATURE"]:
    bpy.data.objects.remove(o)
for o in [o for o in bpy.data.objects if o.type == "MESH"]:
    o.parent = None
    o.modifiers.clear()
    o.vertex_groups.clear()
    m = o.modifiers.new("s", "SUBSURF"); m.levels = 1
    bpy.context.view_layer.objects.active = o
    bpy.ops.object.modifier_apply(modifier="s")
bpy.ops.export_scene.gltf(filepath=dense_out, export_format="GLB")
# rig model: the rigged copy, but 100x bigger and moved (like a centimetre FBX)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=src)
for o in [o for o in bpy.data.objects if o.parent is None]:
    o.scale = (100, 100, 100); o.location = (50, -20, 0)
bpy.ops.export_scene.gltf(filepath=rig_out, export_format="GLB")
'''


def test_dense_model_plus_separate_rig_model(tmp_path):
    """Studio can't rig a 950k-triangle model: the user gives the dense textured model plus the
    rigged retopologized copy. Shape/texture from the first, skeleton from the second."""
    import subprocess
    import sys as _sys
    src = tmp_path / "h.glb"
    run_stage("fixture", {"out": str(src), "humanoid": True}, tmp_path / "f.log")
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    subprocess.run([_sys.executable, "-c", SPLIT_RIG, str(src), str(inputs / "bull.glb"),
                    str(inputs / "bull_rig.glb")], check=True, capture_output=True)
    guide = tmp_path / "guide.yaml"
    guide.write_text("""
project: T
engines: [unity]
defaults: {review: {auto_approve: true}}
assets:
  - name: bull
    model: inputs/bull.glb
    rig_model: inputs/bull_rig.glb
    type: humanoid
    tier: background
    detachable_parts: [Sword]
    overrides:
      texture: {size: 128, samples: 1, device: CPU}
      qa: {min_uv_utilization: 0.0, max_texel_density_cv: 5, max_bake_miss_ratio: 1,
           max_tris_over_budget_pct: 50, max_ngons: 1000}
""")
    jobs = tmp_path / "jobs"
    assert cli(["--jobs", str(jobs), "--data", str(tmp_path / "d"), "run", str(guide)]) == 0
    job = Job.load(jobs / "bull")
    assert job.m["status"] == "done", (job.m.get("waiting_on"),
                                       {k: v.get("status") for k, v in job.m["stages"].items()})
    clean = job.stage("cleanup")["attempts"][-1]["result"]
    assert clean["rigged"] and clean["rig_source"]["bones"] == 52
    assert abs(clean["rig_source"]["aligned_scale"] - 0.01) < 1e-3      # 100x copy scaled back
    assert sorted(clean["parts"]) == ["Body", "Sword"]
    m = job.stage("metrics@unity")["attempts"][-1]["result"]["parts"]["Body"]["weights"]
    assert m["weighted"] and m["unweighted_verts_pct"] == 0 and m["vertex_groups"] >= 3
    assert (jobs / "bull" / "export" / "unity" / "bull.fbx").exists()
