# Forge - one-time setup on Windows 10/11.
#
# Run from the repository folder in PowerShell:
#     powershell -ExecutionPolicy Bypass -File setup\setup_windows.ps1
#
# What it does (it asks before installing anything):
#   1. Python 3.12      - installs with winget if no Python 3.10+ is found
#   2. Blender          - installs with winget if Blender is not found
#   3. .venv + Forge    - creates a virtual environment and installs Forge into it
#   4. .env             - creates it from .env.example (you add your Tripo key)
#   5. forge setup-blender - checks version, GPU (OptiX), add-ons, runs the smoke test

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

function Have($cmd) { [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }
function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [Environment]::GetEnvironmentVariable("Path", "User")
}
function Ask($question) {
    $a = Read-Host "$question [Y/n]"
    return ($a -eq "" -or $a -match "^[Yy]")
}
function Winget-Install($id, $what) {
    if (-not (Have "winget")) {
        Write-Host "[X] winget is not available. Install $what manually, then run this script again." -ForegroundColor Red
        exit 1
    }
    if (-not (Ask "Install $what with winget ($id)?")) { exit 1 }
    winget install --id $id -e --accept-source-agreements --accept-package-agreements
    Refresh-Path
}

Write-Host "== Forge setup ==" -ForegroundColor Cyan

# ---- 1. Python ---------------------------------------------------------------
# each candidate = executable + its leading arguments (splatted, so empty lists pass nothing)
$py = $null
foreach ($cand in @(@("py", "-3"), @("python"))) {
    $exe = $cand[0]; $pre = @($cand | Select-Object -Skip 1)
    if (Have $exe) {
        try {
            $ok = & $exe @pre -c "import sys; print(sys.version_info >= (3, 10))" 2>$null
            if ($ok -eq "True") { $py = $cand; break }
        } catch {}
    }
}
if (-not $py) {
    Write-Host "No Python 3.10+ found."
    Winget-Install "Python.Python.3.12" "Python 3.12"
    $py = @("py", "-3")
}
Write-Host "[OK] Python: $($py -join ' ')"

# ---- 2. Blender ---------------------------------------------------------------
$blender = $env:FORGE_BLENDER
if (-not $blender) {
    $found = Get-ChildItem "C:\Program Files\Blender Foundation\Blender*\blender.exe" -ErrorAction SilentlyContinue |
             Sort-Object { [version]($_.Directory.Name -replace "[^0-9.]", "") } -Descending
    if ($found) { $blender = $found[0].FullName }
}
if (-not $blender) {
    Write-Host "Blender not found."
    Winget-Install "BlenderFoundation.Blender" "Blender (latest)"
    $found = Get-ChildItem "C:\Program Files\Blender Foundation\Blender*\blender.exe" -ErrorAction SilentlyContinue
    if (-not $found) {
        Write-Host "[X] Blender still not found. Install from https://www.blender.org/download/ and rerun." -ForegroundColor Red
        exit 1
    }
    $blender = $found[0].FullName
}
Write-Host "[OK] Blender: $blender"

# ---- 3. virtual environment + Forge ------------------------------------------
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    $exe = $py[0]; $pre = @($py | Select-Object -Skip 1)
    & $exe @pre -m venv .venv
}
& .\.venv\Scripts\python.exe -m pip install --upgrade pip --quiet
& .\.venv\Scripts\python.exe -m pip install -e ".[dev]" --quiet
Write-Host "[OK] Forge installed in .venv"

# ---- 4. .env --------------------------------------------------------------------
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "[!] Created .env - open it and put your Tripo API key (tsk_...) in TRIPO_API_KEY" -ForegroundColor Yellow
}

# ---- 5. verify Blender + smoke test ------------------------------------------
& .\.venv\Scripts\forge.exe setup-blender --blender "$blender"
$rc = $LASTEXITCODE

Write-Host ""
if ($rc -eq 0) {
    Write-Host "== Setup complete ==" -ForegroundColor Green
    Write-Host "Next time, open PowerShell here and run:  .\.venv\Scripts\Activate.ps1"
    Write-Host "Then:  forge check   /   forge run guides\my_game.yaml"
} else {
    Write-Host "== Setup finished with problems - see the messages above ==" -ForegroundColor Red
}
exit $rc
