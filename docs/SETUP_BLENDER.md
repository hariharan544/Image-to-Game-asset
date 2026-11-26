# Setting up Blender for Forge (Windows)

## Fastest way: one script

Open PowerShell in the repository folder and run:

```powershell
powershell -ExecutionPolicy Bypass -File setup\setup_windows.ps1
```

The script asks before it installs anything. It:
1. installs Python and Blender with winget if they are missing;
2. installs Forge;
3. creates `.env`;
4. runs `forge setup-blender`.

It ends with **"Setup complete"** when everything works.

## What `forge setup-blender` checks

```
[OK] Blender: C:\Program Files\Blender Foundation\Blender 5.x\blender.exe
[OK] Version 5.x
[OK] GPU baking: OPTIX -> NVIDIA GeForce RTX 4080 SUPER
[--] Quad Remesher: not installed
[--] Auto-Rig Pro: not installed
[--] UVPackmaster: not installed
Running the pipeline smoke test inside your Blender ...
   fixture ok, cleanup ok, retopo ok, uv ok, bake ok, skin ok, lods ok, previews ok, export ok x2
[OK] Smoke test passed. Exports: jobs\_setup\smoke\export
```

The smoke test builds a small rigged test character with a sword. It runs every Blender stage on
it in your Blender and exports it for Unreal and Unity. Open
`jobs\_setup\smoke\export\unreal\SK_SetupTest.fbx` in Unreal, or the Unity one, to see the output
format. The full report is in `jobs\_setup\blender_report.json`.

## Manual steps (if you prefer)

1. **Blender.** Install the latest release from blender.org, or run
   `winget install --id BlenderFoundation.Blender -e`. Forge needs 4.2 or newer and is developed
   on 5.3. The default install folder is found automatically. For any other folder, run this once:
   ```bat
   forge setup-blender --blender "D:\Apps\Blender\blender.exe"
   ```
   That saves the path to `.env`.
2. **GPU for baking.** In Blender go to Edit → Preferences → System → Cycles Render Devices, choose
   **OptiX** and tick the RTX 4080 Super. If no GPU shows up, update the NVIDIA Studio or Game
   Ready driver. Forge selects OptiX by itself when it bakes, but the driver must expose the card.
3. **Paid add-ons** (Quad Remesher, Auto-Rig Pro, UVPackmaster). In Blender go to Edit →
   Preferences → Add-ons → Install from Disk, pick each add-on's `.zip`, and tick its checkbox.
   `forge setup-blender` then reports them as enabled. They aren't used by the pipeline yet; they
   come in roadmap phase 3. Installing them now lets the setup check confirm they're ready.

## Notes

* Pipeline stages run Blender with `--factory-startup`, which ignores your personal Blender
  preferences and add-ons. That keeps every run identical. The add-on adapters in phase 3 will
  load their add-on explicitly.
* Close nothing: Blender runs in the background (no window opens) and exits after each stage.
* Bake speed: 1024 px textures take about 20 s per stage on a CPU and a few seconds on the 4080.
  Hero assets at 4K take longer.
