"""`forge setup-blender`: find Blender, check it, and prove the pipeline runs in it.

1. locate Blender (or use --blender PATH and remember it in .env)
2. version check (4.2 minimum, newest recommended)
3. system info: GPU backend for Cycles baking (OptiX on RTX cards), paid add-ons
4. smoke test: build a test model, then cleanup -> retopo -> uv -> bake -> skin
   -> lods -> previews -> export (Unreal + Unity) inside *your* Blender
5. write a report to jobs/_setup/blender_report.json
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

from .blender import BlenderError, find_blender, run_stage

MIN_VERSION = (4, 2)
WINGET = "winget install --id BlenderFoundation.Blender -e"
DOWNLOAD = "https://www.blender.org/download/"


def _remember_blender(path: str, env_file: Path) -> None:
    lines = env_file.read_text(encoding="utf-8").splitlines() if env_file.exists() else []
    lines = [l for l in lines if not l.strip().startswith("FORGE_BLENDER=")]
    lines.append(f"FORGE_BLENDER={path}")
    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _smoke(blender: list[str], work: Path, gpu: bool, say, use_qr: bool = False, use_arp: bool = False) -> dict:
    """Run every Blender stage once on a generated test asset. Returns per-stage timings."""
    t: dict = {}
    logs = work / "logs"

    def stage(name, args, **kw):
        t0 = time.time()
        res = run_stage(name, args, logs / f"{name}.log", blender=blender, **kw)
        t[name] = round(time.time() - t0, 1)
        say(f"   {name:9} ok  ({t[name]}s)")
        return res

    src = work / "test_model.glb"
    # with Auto-Rig Pro: a T-pose humanoid with a UE-style skeleton, to test the ARP rig path
    stage("fixture", {"out": str(src), "rigged": True, "humanoid": use_arp})
    b = lambda n: str(work / f"{n}.blend")    # noqa: E731
    stage("cleanup", {"source": str(src), "target_height_m": 1.8, "save_blend": b("1")})
    if use_qr:
        res = stage("retopo", {"load_blend": b("1"), "target_tris": 4000, "save_blend": b("2"),
                               "method": "quadremesher", "ensure_addons": ["quad remesher"]},
                    windowed=True, factory_startup=False)
        methods = sorted({r["method"] for r in res["parts"].values()})
        say(f"             retopo method: {methods}, total tris {res['total_tris']}")
        t["retopo_methods"] = methods
    else:
        stage("retopo", {"load_blend": b("1"), "target_tris": 4000, "save_blend": b("2")})
    uv = stage("uv", {"load_blend": b("2"), "texture_size": 1024, "save_blend": b("3")})
    bake = stage("bake", {"load_blend": b("3"), "texture_size": 1024, "texture_dir": str(work / "textures"),
                          "samples": 16, "device": "GPU" if gpu else "CPU", "save_blend": b("4"),
                          "uv_utilization": {p: r["utilization"] for p, r in uv["parts"].items()}})
    skin_args = {"load_blend": b("4"), "max_influences": 4, "sockets": {"socket_weapon_r": "hand_r"},
                 "save_blend": b("5")}
    if use_arp:
        skin_args.update(rig_method="auto_rig_pro", detachable_parts=["Sword"], ensure_addons=["auto-rig pro"])
        skin = stage("skin", skin_args, windowed=True, factory_startup=False)
        a = skin.get("arp", {})
        say(f"             rig: {skin.get('rig_system')} "
            f"{('- ' + str(a.get('deform_bones')) + ' deform bones, refs placed ' + str(a.get('placed'))) if a else ''}"
            f"{' - fallback: ' + str(skin.get('arp_fallback_reason')) if skin.get('arp_fallback_reason') else ''}")
        t["rig_system"] = skin.get("rig_system")
    else:
        skin = stage("skin", skin_args)
    stage("lods", {"load_blend": b("5"), "lod_ratios": [1, 0.5, 0.25], "save_blend": b("6")})
    try:
        stage("previews", {"load_blend": b("6"), "preview_dir": str(work / "previews"),
                           "engine": "BLENDER_WORKBENCH"})
        t["preview_engine"] = "BLENDER_WORKBENCH"
    except BlenderError:
        say("   previews: Workbench (GPU viewport renderer) failed, trying Cycles CPU ...")
        stage("previews", {"load_blend": b("6"), "preview_dir": str(work / "previews"), "engine": "CYCLES"})
        t["preview_engine"] = "CYCLES"
    maps = {p: r["maps"] for p, r in bake["parts"].items() if "maps" in r}
    for engine in ("unreal", "unity"):
        ex = {"load_blend": b("6"), "engine": engine, "asset_name": "SetupTest",
              "export_dir": str(work / "export" / engine), "texture_maps": maps,
              "detachable_parts": ["Sword"], "unity_pipeline": "urp",
              "ao_into_basecolor": engine == "unity"}
        if skin.get("rig_system") == "auto_rig_pro":
            ex.update(rig_system="auto_rig_pro", prop_bones=skin.get("arp", {}).get("props", {}),
                      ensure_addons=["auto-rig pro"])
            res = stage("export", ex, windowed=True, factory_startup=False)
            say(f"             {engine}: {sorted(Path(p).name for p in res['meshes'].values())}")
        else:
            stage("export", ex)
    return t


def _addon_trial(blender: list[str], work: Path, say) -> None:
    say("Add-on trial: a Blender window opens for a few minutes and closes by itself - do not close it.")
    try:
        rep = run_stage("addon_trial", {"qr_timeout": 300}, work / "logs" / "addon_trial.log",
                        blender=blender, factory_startup=False, windowed=True, timeout=900)
    except BlenderError as exc:
        say(f"[X] Add-on trial failed: {str(exc).splitlines()[0]}")
        return
    (work / "addon_trial.json").write_text(json.dumps(rep, indent=2), encoding="utf-8")
    probe = rep.get("probe", {}).get("addons", {})
    uvpm = probe.get("uvpackmaster", {})
    say(f"   UVPackmaster (windowed): {len(uvpm.get('operators', {}))} operators, "
        f"{len(uvpm.get('settings', {}))} settings groups")
    arp = rep.get("auto_rig_pro", {})
    rigs = arp.get("appended_armatures", {})
    say(f"   Auto-Rig Pro: append {'ok' if rigs else 'FAILED ' + str(arp.get('append_error', ''))[:120]}"
        f"; armatures {[(k, v['bones']) for k, v in rigs.items()]}")
    qr = rep.get("quad_remesher", {})
    if qr.get("results"):
        r = qr["results"][0]
        say(f"   Quad Remesher: {r['faces']} faces, {int(r['quad_ratio'] * 100)}% quads in {qr['elapsed_s']}s")
    else:
        say(f"   Quad Remesher: no result ({qr.get('call_error') or qr.get('skipped') or 'timed out'})")
    say(f"[OK] Add-on trial report -> {work / 'addon_trial.json'}")


def _addon_trial2(blender: list[str], work: Path, say) -> None:
    say("Add-on trial 2 (Auto-Rig Pro full flow + UVPackmaster pack): a Blender window opens and "
        "closes by itself - do not close it.")
    out = work / "trial2"
    out.mkdir(parents=True, exist_ok=True)
    try:
        rep = run_stage("addon_trial2", {"out_dir": str(out)}, work / "logs" / "addon_trial2.log",
                        blender=blender, factory_startup=False, windowed=True, timeout=900)
    except BlenderError as exc:
        say(f"[X] Add-on trial 2 failed: {str(exc).splitlines()[0]}")
        return
    (work / "addon_trial2.json").write_text(json.dumps(rep, indent=2), encoding="utf-8")
    a = rep.get("auto_rig_pro_flow", {})
    say(f"   Auto-Rig Pro: preset={a.get('append_preset')} match={a.get('match_result')} "
        f"bind={a.get('bind_result') or a.get('bind_error', '')[:80]} "
        f"exports={ {k: v.get('exists', False) for k, v in a.get('exports', {}).items()} }")
    u = rep.get("uvpackmaster_flow", {})
    if u.get("after"):
        say(f"   UVPackmaster: mode={u.get('mode_used')} utilization "
            f"{u['before'].get('utilization')} -> {u['after'].get('utilization')} in {u.get('elapsed_s')}s")
    else:
        say(f"   UVPackmaster: {u.get('call_error') or u.get('skipped') or 'no result'}"[:200])
    say(f"[OK] Add-on trial 2 report -> {work / 'addon_trial2.json'}")


def run(blender_path: Optional[str], jobs_dir: str, env_file: Path, skip_smoke: bool, say=print,
        addon_trial: bool = False, addon_trial2: bool = False) -> int:
    report: dict = {"time": time.time()}
    if blender_path:
        p = Path(blender_path)
        if not p.exists():
            say(f"[X] {p} does not exist")
            return 1
        blender = [str(p)]
        _remember_blender(str(p), env_file)
        say(f"[OK] saved FORGE_BLENDER={p} to {env_file}")
    else:
        blender = find_blender()
    if not blender:
        say("[X] Blender not found.\n  Install it with:\n"
            f"      {WINGET}\n  or download it from {DOWNLOAD}\n"
            "  Then run `forge setup-blender` again (or pass --blender \"C:\\path\\to\\blender.exe\").")
        return 1
    report["blender"] = blender[0]
    say(f"[OK] Blender: {blender[0]}")

    work = (Path(jobs_dir) / "_setup").resolve()      # Blender must never see relative paths
    work.mkdir(parents=True, exist_ok=True)
    try:
        info = run_stage("sysinfo", {}, work / "logs" / "sysinfo.log", blender=blender, factory_startup=False)
    except BlenderError as exc:
        say(f"[X] Blender did not start correctly: {exc}")
        return 1
    report["sysinfo"] = info
    ver = tuple(info["version_tuple"][:2])
    ok = True
    if ver < MIN_VERSION:
        say(f"[X] Blender {info['blender_version']} is too old - Forge needs {MIN_VERSION[0]}.{MIN_VERSION[1]} or newer")
        ok = False
    else:
        say(f"[OK] Version {info['blender_version']} (Python {info['python']})")

    gpu = info.get("best_gpu_backend")
    if gpu:
        devs = ", ".join(info["cycles_devices"][gpu])
        say(f"[OK] GPU baking: {gpu} -> {devs}")
    else:
        say("[!] No GPU found for Cycles - baking will run on the CPU (slower). Update the NVIDIA driver,\n"
            "  then in Blender: Edit > Preferences > System > Cycles Render Devices > OptiX.")
    for name, label in (("quad_remesher", "Quad Remesher"), ("auto_rig_pro", "Auto-Rig Pro"),
                        ("uvpackmaster", "UVPackmaster")):
        a = info["addons"][name]
        state = "enabled" if a["enabled"] else ("installed, NOT enabled" if a["installed"] else "not installed")
        say(f"{'[OK]' if a['enabled'] else '[--]'} {label}: {state}")

    if any(info["addons"][k]["installed"] for k in info["addons"]):
        try:
            probe = run_stage("addon_probe", {}, work / "logs" / "addon_probe.log", blender=blender,
                              factory_startup=False)
            (work / "addon_probe.json").write_text(json.dumps(probe, indent=2), encoding="utf-8")
            say(f"Add-on probe -> {work / 'addon_probe.json'}")
            for key, a in probe["addons"].items():
                for f in a["found"]:
                    ops = len(a["operators"])
                    if f.get("enable_errors"):
                        say(f"   [X] {f['name']}: does not load in background Blender: {f['enable_errors'][0][:160]}")
                    elif f["loaded"] or f.get("loaded_by_probe"):
                        note = "" if f["enabled_in_saved_prefs"] else \
                            "  (ticked but preferences not saved: Blender menu > Save Preferences)"
                        say(f"   [OK] {f['name']} {f['version']}: {ops} operators{note}")
                    else:
                        say(f"   [!] {f['name']}: could not be loaded (see logs\\addon_probe.log)")
        except BlenderError as exc:
            say(f"[!] Add-on probe failed: {str(exc).splitlines()[0]}")

    if addon_trial:
        _addon_trial(blender, work, say)
    if addon_trial2:
        _addon_trial2(blender, work, say)

    if not skip_smoke and ok:
        say("Running the pipeline smoke test inside your Blender ...")
        try:
            report["smoke"] = _smoke(blender, work / "smoke", bool(gpu), say,
                                     use_qr=info["addons"]["quad_remesher"]["installed"],
                                     use_arp=info["addons"]["auto_rig_pro"]["installed"])
            say(f"[OK] Smoke test passed. Exports: {work / 'smoke' / 'export'}")
        except BlenderError as exc:
            say(f"[X] Smoke test failed: {str(exc).splitlines()[0]}\n  Logs: {work / 'smoke' / 'logs'}")
            report["smoke_error"] = str(exc)
            ok = False
    (work / "blender_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    say(f"Report: {work / 'blender_report.json'}")
    return 0 if ok else 1
