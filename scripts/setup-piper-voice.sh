#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$ROOT/.venv/bin/python"
VOICE_NAME="${VOICE_TTS_VOICE:-es_MX-ald-medium}"
VOICE_DIR="${VOICE_TTS_DATA_DIR:-$ROOT/backend/data/voices}"

if [[ ! -x "$PYTHON" ]]; then
  echo "No existe $PYTHON. Crea el entorno virtual e instala backend/requirements.txt." >&2
  exit 1
fi

mkdir -p "$VOICE_DIR"
"$PYTHON" -m piper.download_voices --data-dir "$VOICE_DIR" "$VOICE_NAME"

echo "Voz Piper instalada en $VOICE_DIR/$VOICE_NAME.onnx"
echo "La descarga sólo ocurre durante esta instalación; la síntesis posterior es offline."
