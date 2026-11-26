"""Skeleton -> Auto-Rig Pro reference-bone mapping (pure geometry, no ARP needed)."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from forge.blender import find_blender, run_stage

ROOT = Path(__file__).resolve().parent.parent
pytestmark = pytest.mark.skipif(find_blender() is None or find_blender()[0] != sys.executable,
                                reason="needs the bpy module in this Python")

PROBE = r'''
import bpy, json, sys
sys.path.insert(0, sys.argv[1])
from forge_bpy import arp_rig, common as C
bpy.ops.wm.open_mainfile(filepath=sys.argv[2])
arm = C.find_armature()
j = arp_rig.find_joints(arm)
t = arp_rig.ref_targets(j, 0.0, 1.8)
print("RESULT" + json.dumps({"missing": arp_rig.missing_joints(j), "spine": len(j["_spine"]),
      "targets": sorted(t), "heel_r": list(t["foot_heel_ref.r"][0]), "foot_r": list(j["foot_r"][0]),
      "ball_r": list(j["ball_r"][0])}))
'''


@pytest.mark.parametrize("naming", ["ue", "mixamo"])
def test_all_65_reference_bones_placed(tmp_path, naming):
    glb, blend = tmp_path / "h.glb", tmp_path / "h.blend"
    run_stage("fixture", {"out": str(glb), "humanoid": True, "naming": naming}, tmp_path / "f.log")
    run_stage("cleanup", {"source": str(glb), "target_height_m": 1.8, "save_blend": str(blend)}, tmp_path / "c.log")
    out = subprocess.run([sys.executable, "-c", PROBE, str(ROOT / "blender_scripts"), str(blend)],
                         capture_output=True, text=True, check=True).stdout
    r = json.loads(out.split("RESULT", 1)[1])
    assert r["missing"] == [] and r["spine"] == 3
    assert len(r["targets"]) == 65                      # ARP's human preset has 65 *_ref bones
    assert {"root_ref.x", "head_ref.x", "thumb3_ref.l", "index1_base_ref.r", "foot_bank_02_ref.l"} <= set(r["targets"])
    # heel sits on the ground behind the ankle (character faces -Y)
    heel, foot, ball = r["heel_r"], r["foot_r"], r["ball_r"]
    assert abs(heel[2]) < 1e-6 and heel[1] > foot[1] > ball[1]
