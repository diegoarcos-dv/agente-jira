$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"

try {
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/health" -TimeoutSec 2
    if ($health.status -eq "ok" -and $health.template_version -eq "1.1") {
        Write-Host "La aplicación ya está ejecutándose en http://localhost:8000" -ForegroundColor Green
        exit 0
    }
}
catch {
    # El puerto está libre o no corresponde a una instancia saludable del Agente Jira.
}

if (-not (Test-Path (Join-Path $Root "frontend\dist\index.html"))) {
    Push-Location (Join-Path $Root "frontend")
    try {
        pnpm build
    }
    finally {
        Pop-Location
    }
}

Push-Location (Join-Path $Root "backend")
try {
    & $Python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
}
finally {
    Pop-Location
}
