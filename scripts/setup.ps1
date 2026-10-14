$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot 'preflight.ps1')
$Root = Get-AgenteJiraRoot
$Venv = Join-Path $Root ".venv"
$Python = Join-Path $Venv "Scripts\python.exe"

function Fail([string]$Message) { throw "No se pudo preparar Agente Jira.`n`n$Message" }

$venvValid = $false
if (Test-Path -LiteralPath $Python) {
    $probe = Invoke-Captured $Python @('-c', 'import sys; print(sys.executable)')
    $version = Invoke-Captured $Python @('--version')
    $venvValid = $probe.Ok -and $version.Ok -and (Test-MinVersion $version.Output 3 12)
    if (-not $venvValid) {
        $answer = Read-Host '.venv existe pero está dañado. ¿Reconstruirlo? (S/N)'
        if ($answer -notmatch '^(s|si|y|yes)$') { Fail 'Reconstrucción cancelada. El entorno virtual existente no funciona.' }
        $backup = "$Venv.broken-$(Get-Date -Format yyyyMMdd-HHmmss)"
        Move-Item -LiteralPath $Venv -Destination $backup
        Write-Host "Entorno anterior conservado en $backup" -ForegroundColor Yellow
    }
}

if (-not $venvValid) {
    $systemPython = Resolve-Python
    if (-not $systemPython -or $systemPython -eq $Python) {
        Fail 'No se encontró un Python 3.12+ funcional para crear .venv. Instala Python 3.12+ o configura AGENTE_JIRA_PYTHON.'
    }
    Write-Host "Python seleccionado: $systemPython" -ForegroundColor Cyan
    if ($systemPython -like '*|*') {
        $parts = $systemPython -split '\|', 2
        $create = Invoke-Captured $parts[0] (@($parts[1], '-m', 'venv', $Venv))
    } else {
        $create = Invoke-Captured $systemPython @('-m', 'venv', $Venv)
    }
    if (-not $create.Ok) { Fail "No se pudo crear .venv: $($create.Output)" }
}

if (-not (Test-Path -LiteralPath $Python)) { Fail 'La creación terminó sin .venv\Scripts\python.exe.' }
$verify = Invoke-Captured $Python @('-c', 'import sys; print(sys.executable)')
if (-not $verify.Ok) { Fail 'El entorno virtual se creó, pero no puede ejecutarse.' }
Write-Host "Entorno virtual: $($verify.Output)" -ForegroundColor Green

& $Python -m pip install --disable-pip-version-check -r (Join-Path $Root "backend\requirements.txt")
if ($LASTEXITCODE -ne 0) { Fail 'La instalación de dependencias backend falló.' }

$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node) { Fail 'Node.js 20+ no está en PATH.' }
$nodeProbe = Invoke-Captured $node.Source @('--version')
if (-not $nodeProbe.Ok -or -not (Test-MinVersion $nodeProbe.Output 20)) { Fail "Node.js incompatible: $($nodeProbe.Output)" }
$pnpm = Get-Command pnpm -ErrorAction SilentlyContinue
if (-not $pnpm) { Fail 'pnpm no está en PATH.' }
$pnpmProbe = Invoke-Captured $pnpm.Source @('--version')
if (-not $pnpmProbe.Ok) { Fail 'pnpm no responde.' }
Write-Host "Node.js: $($nodeProbe.Output) | pnpm: $($pnpmProbe.Output)" -ForegroundColor Green

Push-Location (Join-Path $Root "frontend")
try {
    & $pnpm.Source install --force --frozen-lockfile --virtual-store-dir=node_modules/.pnpm
    if ($LASTEXITCODE -ne 0) { Fail 'La instalación de dependencias frontend falló.' }
    $frontendMarkers = @('node_modules\vite\package.json','node_modules\vitest\vitest.mjs','node_modules\react\package.json')
    $missingFrontend = @($frontendMarkers | Where-Object { -not (Test-Path $_) })
    if ($missingFrontend.Count -gt 0) { Fail ('La instalación frontend terminó incompleta. Faltan: ' + ($missingFrontend -join ', ')) }
} finally { Pop-Location }

Write-Host ""
Write-Host "Entorno listo. Ejecuta .\scripts\doctor.ps1 y después .\scripts\dev.ps1" -ForegroundColor Green
