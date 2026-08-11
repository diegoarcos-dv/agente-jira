$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$PytestTemp = Join-Path $Root ("backend\.pytest-tmp-" + [Guid]::NewGuid().ToString("N"))

if (-not (Test-Path $Python)) {
    throw "No existe .venv. Ejecuta primero .\scripts\setup.ps1"
}

Push-Location (Join-Path $Root "backend")
try {
    & $Python -m pytest --basetemp $PytestTemp -p no:cacheprovider
    if ($LASTEXITCODE -ne 0) {
        throw "Las pruebas del backend fallaron."
    }
}
finally {
    Pop-Location
}

Push-Location (Join-Path $Root "frontend")
try {
    pnpm test
    if ($LASTEXITCODE -ne 0) {
        throw "Las pruebas del frontend fallaron."
    }
    pnpm build
    if ($LASTEXITCODE -ne 0) {
        throw "La compilación del frontend falló."
    }
}
finally {
    Pop-Location
}

Write-Host "Verificación completa." -ForegroundColor Green
