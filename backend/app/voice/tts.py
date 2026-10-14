from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import tempfile
import threading
from typing import Any, Protocol
import wave

from ..config import Settings
from .errors import VoiceTTSUnavailableError


@dataclass(frozen=True)
class VoiceAudio:
    content: bytes
    mime_type: str = "audio/wav"


class VoiceSynthesizer(Protocol):
    def synthesize(self, text: str) -> Awaitable[VoiceAudio]: ...


class PiperVoiceSynthesizer:
    """Cross-platform offline Piper adapter used by Linux deployments."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._voice: Any | None = None
        self._lock = threading.Lock()

    async def synthesize(self, text: str) -> VoiceAudio:
        return await asyncio.to_thread(self._synthesize_sync, text)

    def _load_voice(self):
        model_path = self.settings.voice_tts_model_path
        config_path = Path(f"{model_path}.json")
        if not model_path.is_file() or not config_path.is_file():
            raise VoiceTTSUnavailableError(
                "El modelo Piper local no está instalado. Ejecuta el instalador de voz."
            )
        try:
            from piper import PiperVoice

            return PiperVoice.load(str(model_path), use_cuda=False)
        except VoiceTTSUnavailableError:
            raise
        except Exception as exc:
            raise VoiceTTSUnavailableError(
                "Piper no pudo cargar el modelo de voz local."
            ) from exc

    def _synthesize_sync(self, text: str) -> VoiceAudio:
        if self.settings.voice_tts_provider != "piper":
            raise VoiceTTSUnavailableError("El proveedor Piper no está configurado.")
        spoken_text = text.strip()[: self.settings.voice_tts_max_chars]
        if not spoken_text:
            raise VoiceTTSUnavailableError("No hay texto para sintetizar.")
        try:
            with self._lock:
                if self._voice is None:
                    self._voice = self._load_voice()
                from piper import SynthesisConfig

                synthesis_config = SynthesisConfig(
                    length_scale=self.settings.voice_tts_length_scale,
                )
                buffer = BytesIO()
                with wave.open(buffer, "wb") as wav_file:
                    self._voice.synthesize_wav(
                        spoken_text,
                        wav_file,
                        syn_config=synthesis_config,
                    )
                content = buffer.getvalue()
        except VoiceTTSUnavailableError:
            raise
        except Exception as exc:
            raise VoiceTTSUnavailableError(
                "El motor Piper local no está disponible."
            ) from exc
        if len(content) <= 44 or not content.startswith(b"RIFF"):
            raise VoiceTTSUnavailableError("Piper no generó audio WAV utilizable.")
        return VoiceAudio(content=content)


class Sapi5VoiceSynthesizer:
    """Optional Windows-only SAPI5 adapter for local development."""

    def __init__(self, settings: Settings):
        self.settings = settings

    async def synthesize(self, text: str) -> VoiceAudio:
        return await asyncio.to_thread(self._synthesize_sync, text)

    def _synthesize_sync(self, text: str) -> VoiceAudio:
        if self.settings.voice_tts_provider != "sapi5":
            raise VoiceTTSUnavailableError("El proveedor SAPI5 no está configurado.")
        if not text.strip():
            raise VoiceTTSUnavailableError("No hay texto para sintetizar.")
        temporary_path: Path | None = None
        pythoncom = None
        stream = None
        try:
            import pythoncom as pythoncom_module
            import win32com.client

            pythoncom = pythoncom_module
            pythoncom.CoInitialize()
            voice = win32com.client.Dispatch("SAPI.SpVoice")
            configured_voice = self.settings.voice_tts_voice.casefold()
            if configured_voice:
                selected = next(
                    (
                        token
                        for token in voice.GetVoices()
                        if configured_voice in str(token.GetDescription()).casefold()
                    ),
                    None,
                )
                if selected is None:
                    raise VoiceTTSUnavailableError(
                        f"La voz SAPI5 '{self.settings.voice_tts_voice}' no está instalada."
                    )
                voice.Voice = selected
            voice.Rate = self.settings.voice_tts_rate
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temporary:
                temporary_path = Path(temporary.name)
            stream = win32com.client.Dispatch("SAPI.SpFileStream")
            stream.Format.Type = 16  # 24 kHz, 16-bit, mono.
            stream.Open(str(temporary_path), 3, False)
            voice.AudioOutputStream = stream
            voice.Speak(text[: self.settings.voice_tts_max_chars])
            stream.Close()
            stream = None
            content = temporary_path.read_bytes()
            if len(content) <= 44:
                raise VoiceTTSUnavailableError("SAPI5 no generó audio utilizable.")
            return VoiceAudio(content=content)
        except VoiceTTSUnavailableError:
            raise
        except Exception as exc:
            raise VoiceTTSUnavailableError(
                "El motor de voz local de Windows no está disponible."
            ) from exc
        finally:
            if stream is not None:
                try:
                    stream.Close()
                except Exception:
                    pass
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            if pythoncom is not None:
                pythoncom.CoUninitialize()


class UnavailableVoiceSynthesizer:
    def __init__(self, provider: str):
        self.provider = provider

    async def synthesize(self, _text: str) -> VoiceAudio:
        raise VoiceTTSUnavailableError(
            f"El proveedor TTS local '{self.provider}' no está soportado."
        )


def build_voice_synthesizer(settings: Settings) -> VoiceSynthesizer:
    if settings.voice_tts_provider == "piper":
        return PiperVoiceSynthesizer(settings)
    if settings.voice_tts_provider == "sapi5":
        return Sapi5VoiceSynthesizer(settings)
    return UnavailableVoiceSynthesizer(settings.voice_tts_provider)
