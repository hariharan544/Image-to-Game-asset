"""The "Send to Forge" Blender add-on: install, load from saved prefs, send, guide accepted by Forge."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from forge.blender import find_blender, run_stage
from forge.spec import load_guide

ROOT = Path(__file__).resolve().parent.parent
pytestmark = pytest.mark.skipif(find_blender() is None or find_blender()[0] != sys.executable,
                                reason="needs the bpy module in this Python")

SEND = r'''
import bpy, sys, json
bpy.ops.wm.read_userpref()
import addon_utils
print("ENABLED", addon_utils.check("forge_send")[1])
bpy.ops.wm.open_mainfile(filepath=sys.argv[1])
for o in bpy.context.view_layer.objects:
    o.select_set(o.type == "MESH" and o.name.startswith("Body"))
bpy.context.view_layer.objects.active = next(o for o in bpy.context.selected_objects)
s = bpy.context.scene.forge
s.asset_name = "studio knight!"
s.asset_type = "humanoid"; s.tier = "standard"; s.detachable = "Sword"; s.height_m = 1.8
s.notes = "test"; s.auto_run = False
print("RESULT", bpy.ops.forge.send())
'''


def test_install_then_send(tmp_path):
    env = {**os.environ, "BLENDER_USER_SCRIPTS": str(tmp_path / "scripts"),
           "BLENDER_USER_CONFIG": str(tmp_path / "config")}
    project = tmp_path / "project"
    for d in ("forge", "inputs", "guides"):
        (project / d).mkdir(parents=True)
    # 1. install (stage runs in a child process that inherits our env)
    os.environ.update({k: env[k] for k in ("BLENDER_USER_SCRIPTS", "BLENDER_USER_CONFIG")})
    try:
        res = run_stage("install_addon", {"src": str(ROOT / "blender_addon" / "forge_send"),
                                          "project": str(project), "forge_exe": None},
                        tmp_path / "install.log", factory_startup=False)
        assert res["enabled"], res
        assert (Path(res["installed_to"]) / "forge_project.json").exists()
        # 2. a rigged character scene to send
        glb, blend = tmp_path / "src.glb", tmp_path / "scene.blend"
        run_stage("fixture", {"out": str(glb), "humanoid": True}, tmp_path / "f.log")
        run_stage("cleanup", {"source": str(glb), "save_blend": str(blend)}, tmp_path / "c.log")
    finally:
        for k in ("BLENDER_USER_SCRIPTS", "BLENDER_USER_CONFIG"):
            os.environ.pop(k, None)
    # 3. fresh Blender: the add-on loads from saved prefs; press Send to Forge
    out = subprocess.run([sys.executable, "-c", SEND, str(blend)], env=env, capture_output=True, text=True)
    assert "ENABLED True" in out.stdout, out.stdout[-2000:] + out.stderr[-2000:]
    assert "RESULT {'FINISHED'}" in out.stdout, out.stdout[-2000:] + out.stderr[-2000:]
    model = project / "inputs" / "studio_knight.glb"
    assert model.exists() and model.stat().st_size > 1000
    # 4. Forge reads the guide the panel wrote
    g = load_guide(project / "guides" / "from_blender.yaml")
    a = g.assets[0]
    assert a.name == "studio_knight" and a.type == "humanoid" and a.tier == "standard"
    assert a.detachable_parts == ["Sword"] and a.topology.target_height_m == 1.8
    assert (g.base_dir / a.model).resolve() == model.resolve()
    assert a.review.concept_checkpoint is False
    # the armature travelled with the selected mesh
    assert b"Armature" in model.read_bytes() or b"pelvis" in model.read_bytes()
