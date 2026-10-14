#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$ROOT/.venv/bin/python"
POLICY="$ROOT/config/jira_execution_policy_4e.json"
VOICE_NAME="${VOICE_TTS_VOICE:-es_MX-ald-medium}"
VOICE_MODEL="${VOICE_TTS_MODEL_PATH:-$ROOT/backend/data/voices/$VOICE_NAME.onnx}"

if [[ ! -x "$PYTHON" ]]; then
  echo "No existe $PYTHON. Crea el entorno virtual e instala backend/requirements.txt." >&2
  exit 1
fi

export AGENTE_JIRA_EXECUTION_POLICY="$POLICY"
export VOICE_STT_ENABLED="${VOICE_STT_ENABLED:-true}"
export VOICE_WHISPER_MODEL="${VOICE_WHISPER_MODEL:-small}"
export VOICE_WHISPER_LANGUAGE="${VOICE_WHISPER_LANGUAGE:-es}"
export VOICE_WHISPER_DEVICE="${VOICE_WHISPER_DEVICE:-cpu}"
export VOICE_WHISPER_COMPUTE_TYPE="${VOICE_WHISPER_COMPUTE_TYPE:-int8}"
export VOICE_WHISPER_BEAM_SIZE="${VOICE_WHISPER_BEAM_SIZE:-2}"
export VOICE_WHISPER_HOTWORDS="${VOICE_WHISPER_HOTWORDS:-Vic Jira genera nueva propuesta confirmación autenticación tarea Task Story Bug Epic Subtask Héctor Víctor prioridad responsable asígnala envíala}"
export VOICE_AI_ENABLED="${VOICE_AI_ENABLED:-true}"
export VOICE_LLM_PROVIDER="${VOICE_LLM_PROVIDER:-ollama}"
export VOICE_GEMMA_MODEL="${VOICE_GEMMA_MODEL:-gemma3:1b}"
export OLLAMA_BASE_URL="${OLLAMA_BASE_URL:-http://127.0.0.1:11434}"
export VOICE_COMMAND_TIMEOUT_SECONDS="${VOICE_COMMAND_TIMEOUT_SECONDS:-60}"
export VOICE_CONTEXT_TTL_SECONDS="${VOICE_CONTEXT_TTL_SECONDS:-1800}"
export VOICE_JIRA_CONFIRMATION_TTL_SECONDS="${VOICE_JIRA_CONFIRMATION_TTL_SECONDS:-600}"
export VOICE_TTS_ENABLED="${VOICE_TTS_ENABLED:-true}"
export VOICE_TTS_PROVIDER="${VOICE_TTS_PROVIDER:-piper}"
export VOICE_TTS_VOICE="$VOICE_NAME"
export VOICE_TTS_MODEL_PATH="$VOICE_MODEL"
export VOICE_TTS_LENGTH_SCALE="${VOICE_TTS_LENGTH_SCALE:-1.0}"
export VOICE_TTS_TIMEOUT_SECONDS="${VOICE_TTS_TIMEOUT_SECONDS:-10}"

if [[ "$VOICE_TTS_ENABLED" == "true" && ! -f "$VOICE_MODEL" ]]; then
  echo "Aviso: falta $VOICE_MODEL. Vic seguirá respondiendo por texto." >&2
  echo "Instala la voz con: bash scripts/setup-piper-voice.sh" >&2
fi

echo "Objetivo 4E habilitado en Linux: Whisper $VOICE_WHISPER_MODEL ($VOICE_WHISPER_DEVICE/$VOICE_WHISPER_COMPUTE_TYPE) + $VOICE_GEMMA_MODEL + Piper."
echo "Task Jira por voz requiere confirmación controlada."

cd "$ROOT/backend"
exec "$PYTHON" -m uvicorn app.main:app --host "${AGENTE_JIRA_HOST:-127.0.0.1}" --port "${AGENTE_JIRA_PORT:-8000}"
