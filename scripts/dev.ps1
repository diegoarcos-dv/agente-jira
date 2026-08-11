$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "No existe .venv. Ejecuta primero .\scripts\setup.ps1"
}

$backend = Start-Process `
    -FilePath $Python `
    -ArgumentList "-m", "uvicorn", "app.main:app", "--reload", "--host", "127.0.0.1", "--port", "8000" `
    -WorkingDirectory (Join-Path $Root "backend") `
    -WindowStyle Hidden `
    -PassThru

try {
    Push-Location (Join-Path $Root "frontend")
    pnpm dev
}
finally {
    Pop-Location
    if (-not $backend.HasExited) {
        Stop-Process -Id $backend.Id
    }
}

