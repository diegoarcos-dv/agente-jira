$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Policy = Join-Path $Root "config\jira_execution_policy_4e.json"

& (Join-Path $PSScriptRoot 'doctor.ps1')
if ($LASTEXITCODE -ne 0) { throw "No se pudo iniciar Agente Jira 4E. Corrige el diagnóstico anterior." }

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
$env:VOICE_STT_ENABLED = "true"
$env:VOICE_WHISPER_MODEL = if ($env:VOICE_WHISPER_MODEL) { $env:VOICE_WHISPER_MODEL } else { "small" }
$env:VOICE_WHISPER_LANGUAGE = if ($env:VOICE_WHISPER_LANGUAGE) { $env:VOICE_WHISPER_LANGUAGE } else { "es" }
$env:VOICE_WHISPER_DEVICE = if ($env:VOICE_WHISPER_DEVICE) { $env:VOICE_WHISPER_DEVICE } else { "cpu" }
$env:VOICE_WHISPER_COMPUTE_TYPE = if ($env:VOICE_WHISPER_COMPUTE_TYPE) { $env:VOICE_WHISPER_COMPUTE_TYPE } else { "int8" }
$env:VOICE_WHISPER_BEAM_SIZE = if ($env:VOICE_WHISPER_BEAM_SIZE) { $env:VOICE_WHISPER_BEAM_SIZE } else { "2" }
$env:VOICE_WHISPER_HOTWORDS = if ($env:VOICE_WHISPER_HOTWORDS) { $env:VOICE_WHISPER_HOTWORDS } else { "Vic Jira genera nueva propuesta confirmación autenticación tarea Task Story Bug Epic Subtask Héctor Víctor prioridad responsable asígnala envíala" }
$env:VOICE_AI_ENABLED = "true"
$env:VOICE_LLM_PROVIDER = "ollama"
$env:VOICE_GEMMA_MODEL = if ($env:VOICE_GEMMA_MODEL) { $env:VOICE_GEMMA_MODEL } else { "gemma3:1b" }
$env:OLLAMA_BASE_URL = if ($env:OLLAMA_BASE_URL) { $env:OLLAMA_BASE_URL } else { "http://127.0.0.1:11434" }
$env:VOICE_COMMAND_TIMEOUT_SECONDS = if ($env:VOICE_COMMAND_TIMEOUT_SECONDS) { $env:VOICE_COMMAND_TIMEOUT_SECONDS } else { "60" }
$env:VOICE_CONTEXT_TTL_SECONDS = if ($env:VOICE_CONTEXT_TTL_SECONDS) { $env:VOICE_CONTEXT_TTL_SECONDS } else { "1800" }
$env:VOICE_JIRA_CONFIRMATION_TTL_SECONDS = if ($env:VOICE_JIRA_CONFIRMATION_TTL_SECONDS) { $env:VOICE_JIRA_CONFIRMATION_TTL_SECONDS } else { "600" }
$env:VOICE_TTS_ENABLED = if ($env:VOICE_TTS_ENABLED) { $env:VOICE_TTS_ENABLED } else { "true" }
$env:VOICE_TTS_PROVIDER = if ($env:VOICE_TTS_PROVIDER) { $env:VOICE_TTS_PROVIDER } else { "piper" }
$env:VOICE_TTS_VOICE = if ($env:VOICE_TTS_VOICE) { $env:VOICE_TTS_VOICE } else { "es_MX-ald-medium" }
$env:VOICE_TTS_MODEL_PATH = if ($env:VOICE_TTS_MODEL_PATH) {
    $env:VOICE_TTS_MODEL_PATH
} else {
    Join-Path $Root "backend\data\voices\es_MX-ald-medium.onnx"
}
$env:VOICE_TTS_LENGTH_SCALE = if ($env:VOICE_TTS_LENGTH_SCALE) { $env:VOICE_TTS_LENGTH_SCALE } else { "1.0" }
$env:VOICE_TTS_RATE = if ($env:VOICE_TTS_RATE) { $env:VOICE_TTS_RATE } else { "0" }
$env:VOICE_TTS_TIMEOUT_SECONDS = if ($env:VOICE_TTS_TIMEOUT_SECONDS) { $env:VOICE_TTS_TIMEOUT_SECONDS } else { "10" }
Push-Location (Join-Path $Root "backend")
try {
    Write-Host "Objetivo 4E habilitado: Epic, Subtask y relaciones padre-hijo controladas en AT." -ForegroundColor Yellow
    Write-Host "Voz local: Whisper $env:VOICE_WHISPER_MODEL ($env:VOICE_WHISPER_DEVICE/$env:VOICE_WHISPER_COMPUTE_TYPE) + $env:VOICE_GEMMA_MODEL + TTS $env:VOICE_TTS_PROVIDER. Task Jira por voz requiere confirmacion controlada." -ForegroundColor Cyan
    & $Python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
}
finally {
    Pop-Location
}
