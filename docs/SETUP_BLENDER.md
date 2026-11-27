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

## Paid add-ons: probe report

When Quad Remesher, UVPackmaster or Auto-Rig Pro are installed, `forge setup-blender` also writes
`jobs\_setup\addon_probe.json`. It lists each add-on's version, its operators and parameters, and
its settings, as they exist in *your* Blender. Forge's add-on adapters are written against this
file, so send it over after the first setup run.

## Auto-Rig Pro check for Step 8 (`forge arp-probe`)

The new Step 8 relies on how *your* Auto-Rig Pro behaves (its rig presets, limb options, IK
poles, binding and export). Run this once, in PowerShell in the Forge folder:

```powershell
.venv\Scripts\forge.exe arp-probe
```

Small Blender windows open and close by themselves for about 5 minutes; don't click in them or
close them. A window may close suddenly at the bird or the wings step: that is a result too, and
the check carries on. Nothing in your files or Blender settings is changed: every step uses an
empty throwaway scene and nothing is saved. The result is
`jobs\_setup\arp_probe\arp_3_79_probe.json` (the last lines show the full path): send that file
back, with any lines that start with `[X]` or `[!]`. Logs and test exports are in the same folder.

## UVPackmaster engine

UVPackmaster 4 packs with a separate **engine** program that ships with your purchase and is
installed on its own. Without it, the add-on loads but reports *"UVPackmaster engine 4.0.4 not
detected"*. To install it:
1. run the engine installer from your UVPackmaster download;
2. restart Blender;
3. check that UV Editor → N panel → UVPackmaster shows the engine as ready.

Until then, Forge packs UVs with Blender's built-in packer.

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
