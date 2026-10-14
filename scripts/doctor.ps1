param([switch]$SkipPorts)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'preflight.ps1')
$root = Get-AgenteJiraRoot
$checks = [System.Collections.Generic.List[object]]::new()

function Add-Check([string]$Name, [bool]$Ok, [string]$Detail, [bool]$Blocking = $true) {
    $script:checks.Add([pscustomobject]@{ Name = $Name; Ok = $Ok; Detail = $Detail; Blocking = $Blocking })
}

Write-Host 'AGENTE JIRA — DIAGNÓSTICO LOCAL' -ForegroundColor Cyan
Write-Host ''

$resolvedPython = Resolve-Python
if ($resolvedPython) {
    $pythonProbe = Invoke-ResolvedPython $resolvedPython @('--version')
    Add-Check 'Python 3.12+' $true "$($pythonProbe.Output) [$resolvedPython]"
} else {
    Add-Check 'Python 3.12+' $false 'No encontrado o incompatible. Instala Python 3.12+ o configura AGENTE_JIRA_PYTHON.'
}

$venvPath = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPath)) {
    Add-Check 'Entorno virtual' $false 'No existe .venv. Ejecuta scripts\setup.cmd.'
    $venvProbe = $null
} else {
    $venvProbe = Invoke-Captured $venvPath @('-c', 'import sys; print(sys.executable)')
    if ($venvProbe.Ok) {
        $versionProbe = Invoke-Captured $venvPath @('--version')
        $valid = $versionProbe.Ok -and (Test-MinVersion $versionProbe.Output 3 12)
        Add-Check 'Entorno virtual' $valid $(if ($valid) { $versionProbe.Output } else { 'El entorno virtual existe pero no funciona.' })
    } else {
        Add-Check 'Entorno virtual' $false 'El entorno virtual existe pero no funciona. Ejecuta scripts\setup.cmd para reconstruirlo.'
    }
}

if ($venvProbe -and $venvProbe.Ok) {
    $imports = Invoke-Captured $venvPath @('-c', "import fastapi, uvicorn, openpyxl, jsonschema, httpx, mcp; print('backend imports OK')")
    Add-Check 'Dependencias backend' $imports.Ok $(if ($imports.Ok) { $imports.Output } else { 'Faltan dependencias. Ejecuta scripts\setup.cmd.' })
} else {
    Add-Check 'Dependencias backend' $false 'No se pueden comprobar hasta reparar .venv.'
}

$node = Get-Command node -ErrorAction SilentlyContinue
if ($node) {
    $probe = Invoke-Captured $node.Source @('--version')
    Add-Check 'Node.js 20+' ($probe.Ok -and (Test-MinVersion $probe.Output 20)) $(if ($probe.Ok) { $probe.Output } else { 'Node.js no responde.' })
} else { Add-Check 'Node.js 20+' $false 'No encontrado en PATH.' }

$compiledFrontend = Test-Path (Join-Path $root 'frontend\dist\index.html')
$pnpm = Get-Command pnpm -ErrorAction SilentlyContinue
if ($pnpm) {
    $probe = Invoke-Captured $pnpm.Source @('--version')
    Add-Check 'pnpm' $probe.Ok $(if ($probe.Ok) { $probe.Output } else { 'pnpm no responde.' })
} elseif ($compiledFrontend) {
    # A packaged/local production start serves the existing frontend build and
    # does not invoke pnpm.  Keep the missing development tool visible without
    # preventing a safe backend restart.
    Add-Check 'pnpm' $true 'No encontrado en PATH; se usará el frontend ya compilado.' $false
} else {
    Add-Check 'pnpm' $false 'No encontrado en PATH y no existe un frontend compilado. Ejecuta scripts\setup.cmd.'
}

$frontendMarkers = @('frontend\node_modules\vite\package.json','frontend\node_modules\vitest\vitest.mjs','frontend\node_modules\react\package.json')
$missingFrontend = @($frontendMarkers | Where-Object { -not (Test-Path (Join-Path $root $_)) })
Add-Check 'Dependencias frontend' ($missingFrontend.Count -eq 0) $(if ($missingFrontend.Count -eq 0) { 'node_modules completo' } else { 'node_modules incompleto. Ejecuta scripts\setup.cmd.' })

$localRecoveryEnabled = $env:AGENTE_JIRA_EMERGENCY_LOCAL_AUTH_ENABLED -match '^(?i:1|true|yes|on)$'
$localPasswordConfigured = -not [string]::IsNullOrWhiteSpace($env:AGENTE_JIRA_LOCAL_PASSWORD)
if ($localRecoveryEnabled) {
    Add-Check 'Recuperación local' $localPasswordConfigured $(if ($localPasswordConfigured) { 'Recuperación local de emergencia configurada.' } else { 'Falta AGENTE_JIRA_LOCAL_PASSWORD para la recuperación local de emergencia habilitada.' })
} else {
    Add-Check 'Recuperación local' $true 'Deshabilitada; el arranque normal usa autenticación federada Atlassian.' $false
}

foreach ($port in 8000, 5173) {
    if ($SkipPorts) { continue }
    if (Test-TcpPort $port) {
        $owner = Get-PortOwner $port
        $ownAgent = ($port -eq 8000 -and (Test-AgenteHealth))
        Add-Check "Puerto $port" $false $(if ($ownAgent) { "Ocupado por Agente Jira ($owner). Detén la instancia antes de iniciar otra." } else { "Ocupado por otro proceso ($owner). No se detendrá automáticamente." })
    } else { Add-Check "Puerto $port" $true 'Disponible' }
}

$db = Join-Path $root 'backend\data\agente_jira.db'
$sqliteOk = $false
if ($venvProbe -and $venvProbe.Ok) {
    $sqliteProbe = Invoke-Captured $venvPath @('-c', 'import sqlite3; print(sqlite3.sqlite_version)')
    $sqliteOk = $sqliteProbe.Ok
} 
Add-Check 'SQLite' $sqliteOk $(if ($sqliteOk) { 'Disponible' } else { 'No disponible en el Python del entorno.' })

$required = @('backend\app\config.py','backend\requirements.txt','frontend\package.json','frontend\pnpm-lock.yaml','config\jira_execution_policy_v1.json','docs\schemas\jira_execution_policy_v1.schema.json')
$missing = @($required | Where-Object { -not (Test-Path (Join-Path $root $_)) })
Add-Check 'Configuración local' ($missing.Count -eq 0) $(if ($missing.Count -eq 0) { 'Archivos requeridos presentes; .env.example no se trata como configuración activa.' } else { 'Faltan: ' + ($missing -join ', ') })

Write-Host ''
foreach ($check in $checks) {
    $mark = if ($check.Ok) { '✅' } else { '❌' }
    Write-Host ("{0,-24} {1} {2}" -f $check.Name, $mark, $check.Detail)
}
$failed = @($checks | Where-Object { -not $_.Ok -and $_.Blocking })
Write-Host ''
if ($failed.Count -eq 0) {
    Write-Host 'Resultado:' -ForegroundColor Green
    Write-Host 'Sistema listo para iniciar.' -ForegroundColor Green
    exit 0
}
Write-Host 'Resultado:' -ForegroundColor Red
Write-Host ("Sistema no listo: {0} comprobación(es) bloqueante(s)." -f $failed.Count) -ForegroundColor Red
exit 1
