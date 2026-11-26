from pathlib import Path

import pytest

from forge import qa
from forge.spec import load_guide, resolve_asset
from forge.supervisor import Observation, RuleSupervisor, actions_for, apply_action
from forge.supervisor.llm import _extract_json
from forge.supervisor.prompt import user_message

ROOT = Path(__file__).resolve().parent.parent


def test_example_guide_resolves_aaa_and_mobile_targets():
    g = load_guide(ROOT / "guides" / "example_project.yaml")
    knight, chest, sword = g.assets
    assert knight.rig.enabled and knight.rig.rig_type == "biped"
    assert knight.rig.spec == "unreal"                         # Tripo rigs to the AAA skeleton
    ue, un = knight.targets["unreal"], knight.targets["unity"]
    assert (ue.platform, ue.topology.target_tris, ue.texture.size, ue.rig.max_influences) == ("aaa", 80000, 4096, 8)
    assert (un.platform, un.topology.target_tris, un.texture.size, un.rig.max_influences) == ("mobile", 15000, 2048, 4)
    assert un.export.unity_pipeline == "urp" and un.export.ao_into_basecolor and un.rig.max_bones == 75
    assert ue.topology.target_height_m == un.topology.target_height_m == 1.85   # general override -> both
    assert un.rig.sockets["socket_weapon_r"] == "hand_r"
    view = knight.for_target("unity")
    assert view.effective_tris == 15000 and view.platform == "mobile" and view.engines == ["unity"]
    assert not chest.rig.enabled and chest.targets["unreal"].topology.target_tris == 4000
    assert chest.targets["unity"].topology.target_tris == 800
    assert sword.style == "stylized" and "metallic" not in sword.targets["unity"].texture.maps


def test_per_target_overrides():
    spec = resolve_asset({"name": "x", "image": "a.png", "type": "prop",
                          "overrides": {"texture": {"size": 777},
                                        "targets": {"unity": {"texture": {"size": 128}}}}},
                         {"engines": ["unreal", "unity"], "targets": {"unreal": {"topology": {"target_tris": 999}}}})
    assert spec.targets["unreal"].texture.size == 777 and spec.targets["unity"].texture.size == 128
    assert spec.targets["unreal"].topology.target_tris == 999


def test_unknown_style_rejected():
    with pytest.raises(ValueError):
        resolve_asset({"name": "x", "image": "a.png", "style": "nope"}, {})


def _spec(**kw):
    return resolve_asset({"name": "t", "image": "a.png", "type": "prop", "tier": "standard", **kw}, {})


def test_qa_budget_and_uv():
    spec = _spec()
    issues = qa.check("retopo", {"total_tris": 9000, "parts": {}}, spec)
    assert [i.code for i in issues] == ["OVER_BUDGET"]
    uv = {"parts": {"a": {"has_uv": True, "utilization": 0.7, "overlap_pct": 3.0,
                          "texel_density_px_per_m": 500, "texel_density_cv": 0.1, "out_of_bounds_ratio": 0}}}
    assert [i.code for i in qa.check("uv", uv, spec)] == ["UV_OVERLAP"]


def _obs(issues, history=(), stage="retopo", params=None):
    return Observation(asset="t", stage=stage, attempt=len(history) + 1,
                       params=params or {"budget_scale": 1.0, "method": "quadriflow", "seed": 0},
                       result={}, issues=issues, history=list(history))


def test_rules_accept_retry_escalate():
    sup = RuleSupervisor()
    assert sup.decide(_obs([])).action == "accept"
    assert sup.decide(_obs([{"code": "X", "severity": "warn", "message": ""}])).action == "accept"
    over = [{"code": "OVER_BUDGET", "severity": "error", "message": "too many"}]
    d1 = sup.decide(_obs(over))
    assert d1.action == "retopo_reduce_budget" and d1.new_params["budget_scale"] == pytest.approx(0.9)
    hist = [{"action": "retopo_reduce_budget"}, {"action": "retopo_reduce_budget"}]
    assert sup.decide(_obs(over, hist)).action == "retopo_decimate"
    hist.append({"action": "retopo_decimate"})
    assert sup.decide(_obs(over, hist)).action == "escalate"


def test_action_space_is_stage_scoped_and_clamped():
    assert "uv_smart" in actions_for("uv") and "uv_smart" not in actions_for("retopo")
    assert apply_action("uv_lower_angle", {"angle_limit_deg": 25})["angle_limit_deg"] == 20
    assert apply_action("bake_more_extrusion", {"cage_extrusion_ratio": 0.15})["cage_extrusion_ratio"] == 0.2


def test_prompt_lists_allowed_actions_and_json_parsing():
    msg = user_message(_obs([{"code": "UV_OVERLAP", "severity": "error", "message": "m"}], stage="uv"))
    assert "uv_bigger_margin" in msg and "retopo_decimate" not in msg
    assert _extract_json('<think>hmm</think> sure: {"action": "accept", "reason": "ok"}')["action"] == "accept"
    assert _extract_json("no json") is None


def test_dataset_labels_only_helpful_decisions(tmp_path):
    import sys
    sys.path.insert(0, str(ROOT / "training"))
    from build_dataset import label

    def dec(i, action, n_err, job="j"):
        issues = [{"code": "UV_STRETCH", "severity": "error", "message": ""}] * n_err
        return {"id": i, "job": job, "time": 1.0, "decision": {"action": action, "reason": ""},
                "observation": {"asset": "a", "stage": "uv", "attempt": 1, "params": {}, "result": {},
                                "issues": issues, "history": []}}
    decisions = [
        dec("a", "uv_lower_angle", 2), {"outcome_for": "a", "error_count": 2, "resolved": False},
        dec("b", "uv_min_stretch", 2), {"outcome_for": "b", "error_count": 1, "resolved": False},
        dec("c", "uv_smart", 1), {"outcome_for": "c", "error_count": 0, "resolved": True},
        dec("d", "accept", 0), dec("e", "escalate", 1),
        dec("f", "accept", 0, job="rejected_job"),
    ]
    reviews = [{"job": "j", "checkpoint": "final", "status": "approved", "time": 2.0},
               {"job": "rejected_job", "checkpoint": "final", "status": "rejected", "time": 2.0}]
    kept = {e["id"] for e in label(decisions, reviews, include_unreviewed=False)}
    assert kept == {"b", "c", "d", "e"}


def test_redo_from_one_target_keeps_the_other(tmp_path):
    from forge.cli import main as cli
    from forge.job import Job
    from forge.pipeline import stage_order

    img = tmp_path / "a.png"
    img.write_bytes(b"x")
    spec = resolve_asset({"name": "k", "image": str(img), "type": "prop"}, {"engines": ["unreal", "unity"]})
    job = Job.open(tmp_path / "jobs", spec, img)
    for k in stage_order(spec.engines):
        job.set_stage(k, "done")
    job.set_tripo_task("generate", "t1")
    job.set_checkpoint("final", "approved")
    assert cli(["--jobs", str(tmp_path / "jobs"), "--data", str(tmp_path / "d"), "review", str(job.root),
                "--checkpoint", "final", "--reject", "--notes", "blurry", "--redo-from", "bake@unity"]) == 0
    job = Job.load(job.root)
    left = set(job.m["stages"])
    assert {"bake@unreal", "export@unreal", "uv@unity", "generate"} <= left
    assert not {"bake@unity", "previews@unity", "export@unity", "final_review"} & left
    assert job.tripo_task("generate") == "t1"                   # no new cloud generation
