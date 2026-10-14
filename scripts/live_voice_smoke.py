"""Prueba reproducible y sin escritura del Gate Voz 3 contra el servidor local.

Genera las frases con Piper en memoria, por lo que recorre el endpoint, Whisper, el contexto,
el router, la compuerta y el TTS de salida sin persistir audio. Deliberadamente no envía una
confirmación Jira: una conexión disponible puede dejar una operación preparada, nunca creada.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
from dataclasses import replace
from io import BytesIO
import json
import os
from pathlib import Path
import sys
import time
import wave

import httpx
from piper import PiperVoice


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
DEFAULT_MODEL = ROOT / "backend" / "data" / "voices" / "es_MX-ald-medium.onnx"


def synthesize_piper(voice: PiperVoice, text: str) -> bytes:
    buffer = BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        voice.synthesize_wav(text, wav_file)
    return buffer.getvalue()


def synthesize_sapi5(text: str) -> bytes:
    from app.config import get_settings
    from app.voice.tts import Sapi5VoiceSynthesizer

    settings = replace(
        get_settings(),
        voice_tts_provider="sapi5",
        voice_tts_voice="Microsoft Helena Desktop",
    )
    return asyncio.run(Sapi5VoiceSynthesizer(settings).synthesize(text)).content


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--input-provider", choices=("piper", "sapi5"), default="piper")
    args = parser.parse_args()

    username = os.getenv("AGENTE_JIRA_LOCAL_USER", "admin@agentejira.local")
    password = os.getenv("AGENTE_JIRA_LOCAL_PASSWORD", "").strip()
    if not password:
        parser.error("Configura AGENTE_JIRA_LOCAL_PASSWORD para ejecutar la prueba local de voz.")
    voice = (
        PiperVoice.load(str(args.model), use_cuda=False)
        if args.input_provider == "piper"
        else None
    )
    conversation = [
        (
            "Prepara una tarea para probar la autenticación.",
            "prepare_local_task",
            {"completed"},
        ),
        (
            "Crea una tarea para probar autenticación, asígnala a Héctor y pon prioridad alta.",
            "request_jira_create",
            {"awaiting_confirmation", "needs_clarification", "validation_error"},
        ),
        (
            "Genera una nueva propuesta, tienes mi confirmación.",
            "create_proposal",
            {"blocked"},
        ),
    ]

    with httpx.Client(base_url=args.base_url, timeout=90) as client:
        login = client.post(
            "/api/auth/login",
            json={"username": username, "password": password},
        )
        login.raise_for_status()
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        client.delete("/api/voice/context", headers=headers).raise_for_status()
        failures: list[str] = []
        for phrase, expected_intent, expected_statuses in conversation:
            input_audio = (
                synthesize_piper(voice, phrase)
                if voice is not None
                else synthesize_sapi5(phrase)
            )
            started = time.perf_counter()
            response = client.post(
                "/api/voice/command",
                headers=headers,
                data={"spoken_response": "true"},
                files={"audio": ("command.wav", input_audio, "audio/wav")},
            )
            elapsed = time.perf_counter() - started
            payload = response.json()
            if response.status_code != 200:
                failures.append(f"{phrase}: HTTP {response.status_code} {payload}")
                continue
            audio_bytes = (
                len(base64.b64decode(payload["audio_base64"]))
                if payload.get("audio_available") and payload.get("audio_base64")
                else 0
            )
            print(
                json.dumps(
                    {
                        "phrase": phrase,
                        "transcript": payload.get("transcript"),
                        "intent": payload.get("intent"),
                        "status": payload.get("status"),
                        "risk": payload.get("risk"),
                        "seconds": round(elapsed, 3),
                        "tts_wav_bytes": audio_bytes,
                        "draft": payload.get("draft"),
                        "jira_operation": payload.get("jira_operation"),
                    },
                    ensure_ascii=False,
                )
            )
            if payload.get("intent") != expected_intent:
                failures.append(
                    f"{phrase}: intent {payload.get('intent')} != {expected_intent}"
                )
            if payload.get("status") not in expected_statuses:
                failures.append(
                    f"{phrase}: status {payload.get('status')} no está en "
                    f"{sorted(expected_statuses)}"
                )
            operation = payload.get("jira_operation") or {}
            if operation.get("issue_key"):
                failures.append(
                    f"{phrase}: la prueba sin confirmación no debía crear un issue"
                )

    if failures:
        print(json.dumps({"result": "FAILED", "failures": failures}, ensure_ascii=False))
        return 1
    print(
        json.dumps(
            {"result": "PASS", "jira_write_performed": False},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
