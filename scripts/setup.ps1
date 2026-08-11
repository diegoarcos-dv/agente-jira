$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Venv = Join-Path $Root ".venv"
$Python = Join-Path $Venv "Scripts\python.exe"

if (-not (Test-Path $Python)) {
    python -m venv $Venv
}

& $Python -m pip install --disable-pip-version-check -r (Join-Path $Root "backend\requirements.txt")
Push-Location (Join-Path $Root "frontend")
try {
    pnpm install
}
finally {
    Pop-Location
}

Write-Host ""
Write-Host "Entorno listo. Ejecuta .\scripts\dev.ps1" -ForegroundColor Green

