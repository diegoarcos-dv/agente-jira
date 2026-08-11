$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Policy = Join-Path $Root "config\jira_execution_policy_4e.json"

try {
    Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/health" -TimeoutSec 2 | Out-Null
    throw "El puerto 8000 ya esta ocupado. Deten la instancia actual con Ctrl+C antes de iniciar el modo 4E."
}
catch {
    if ($_.Exception.Message -like "El puerto 8000 ya esta ocupado*") { throw }
}

if (-not (Test-Path $Python)) {
    throw "No existe .venv. Ejecuta primero .\scripts\setup.ps1"
}

$env:AGENTE_JIRA_EXECUTION_POLICY = $Policy
Push-Location (Join-Path $Root "backend")
try {
    Write-Host "Objetivo 4E habilitado: Epic, Subtask y relaciones padre-hijo controladas en AT." -ForegroundColor Yellow
    & $Python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
}
finally {
    Pop-Location
}
