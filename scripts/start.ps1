param(
    # Use this when publishing the local service through HTTPS (for example,
    # https://agente.bioxor.net).  OAuth must return to the same public URL.
    [string]$PublicBaseUrl
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$CurrentTemplateVersion = '1.3'
$Python = Join-Path $Root ".venv\Scripts\python.exe"

# The local .env is intentionally not a general-purpose secret loader.  Load
# only the public Radar Telegram deep link needed by the local application.
$radarEnvFile = Join-Path $Root ".env"
if (Test-Path $radarEnvFile) {
    $radarTelegramLine = Get-Content $radarEnvFile | Where-Object { $_ -match '^NEWS_TELEGRAM_URL=' } | Select-Object -Last 1
    if ($null -ne $radarTelegramLine) {
        $env:NEWS_TELEGRAM_URL = $radarTelegramLine.Substring('NEWS_TELEGRAM_URL='.Length).Trim()
    }
}

if ($PublicBaseUrl) {
    try {
        $publicUri = [Uri]$PublicBaseUrl
    }
    catch {
        throw "PublicBaseUrl debe ser una URL HTTPS válida."
    }
    if ($publicUri.Scheme -ne "https" -or -not $publicUri.Host) {
        throw "PublicBaseUrl debe ser una URL HTTPS válida."
    }
    $env:AGENTE_JIRA_PUBLIC_BASE_URL = $PublicBaseUrl.TrimEnd('/')
}

# The local app keeps writes globally locked at startup. This policy enables
# every supported Jira work type in AT, after the user explicitly unlocks the
# interface and confirms the reviewed batch.
if (-not $env:AGENTE_JIRA_EXECUTION_POLICY) {
    $env:AGENTE_JIRA_EXECUTION_POLICY = Join-Path $Root "config\jira_execution_policy_4e.json"
}

if (-not $env:AGENTE_JIRA_ALLOW_ALL_CORPORATE_USERS) {
    $env:AGENTE_JIRA_ALLOW_ALL_CORPORATE_USERS = "true"
}

try {
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/health" -TimeoutSec 2
    if ($health.status -eq "ok" -and $health.template_version -eq $CurrentTemplateVersion) {
        Write-Host "La aplicación ya está ejecutándose en http://localhost:8000" -ForegroundColor Green
        exit 0
    }
    if ($health.status -eq "ok") {
        Write-Host "Ya hay una instancia con plantilla v$($health.template_version) en http://localhost:8000. Ciérrala y vuelve a iniciar para cargar v$CurrentTemplateVersion; no se reinició para conservar tu sesión local." -ForegroundColor Yellow
        exit 1
    }
}
catch {
    # El puerto está libre o no corresponde a una instancia saludable del Agente Jira.
}

& (Join-Path $PSScriptRoot 'doctor.ps1')
if ($LASTEXITCODE -ne 0) { throw "No se pudo iniciar Agente Jira. Corrige el diagnóstico anterior." }

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
