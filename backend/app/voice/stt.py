from __future__ import annotations

import asyncio
import tempfile
import threading
from collections.abc import Awaitable
from pathlib import Path
from typing import Protocol

from ..config import Settings
from .errors import VoiceInputError, VoiceUnavailableError
from .models import TranscriptionResult


class VoiceTranscriber(Protocol):
    def transcribe(
        self,
        audio: bytes,
        content_type: str,
    ) -> Awaitable[TranscriptionResult]: ...


_AUDIO_SUFFIXES = {
    "audio/webm": ".webm",
    "audio/ogg": ".ogg",
    "audio/mp4": ".m4a",
    "audio/mpeg": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
}


class FasterWhisperTranscriber:
    """Lazy, reusable faster-whisper adapter with ephemeral audio files."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._model = None
        self._model_lock = threading.Lock()
        self._transcribe_lock = threading.Lock()

    def _get_model(self):
        if self._model is not None:
            return self._model
        with self._model_lock:
            if self._model is not None:
                return self._model
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise VoiceUnavailableError(
                    "El reconocimiento de voz local no está instalado. "
                    "Instala las dependencias del backend y reinicia la aplicación."
                ) from exc
            try:
                self._model = WhisperModel(
                    self.settings.voice_whisper_model,
                    device=self.settings.voice_whisper_device,
                    compute_type=self.settings.voice_whisper_compute_type,
                )
            except Exception as exc:
                raise VoiceUnavailableError(
                    "No fue posible cargar el modelo Whisper local configurado."
                ) from exc
        return self._model

    async def transcribe(
        self,
        audio: bytes,
        content_type: str,
    ) -> TranscriptionResult:
        return await asyncio.to_thread(self._transcribe_sync, audio, content_type)

    def _transcribe_sync(
        self,
        audio: bytes,
        content_type: str,
    ) -> TranscriptionResult:
        media_type = content_type.split(";", 1)[0].strip().lower()
        suffix = _AUDIO_SUFFIXES.get(media_type)
        if suffix is None:
            raise VoiceInputError("El formato de audio no es compatible.")

        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temporary:
                temporary.write(audio)
                temporary_path = Path(temporary.name)
            try:
                import av

                with av.open(str(temporary_path)) as container:
                    duration = (
                        float(container.duration / av.time_base)
                        if container.duration is not None
                        else 0.0
                    )
            except Exception as exc:
                raise VoiceInputError("El archivo de audio no se pudo leer.") from exc
            if duration > self.settings.voice_max_duration_seconds:
                raise VoiceInputError(
                    "El audio supera el límite de "
                    f"{int(self.settings.voice_max_duration_seconds)} segundos."
                )
            model = self._get_model()
            with self._transcribe_lock:
                segments, info = model.transcribe(
                    str(temporary_path),
                    language=self.settings.voice_whisper_language,
                    beam_size=self.settings.voice_whisper_beam_size,
                    best_of=self.settings.voice_whisper_beam_size,
                    condition_on_previous_text=False,
                    vad_filter=True,
                    hotwords=self.settings.voice_whisper_hotwords or None,
                )
                text = " ".join(segment.text.strip() for segment in segments).strip()
            if not text:
                raise VoiceInputError(
                    "No pude detectar una instrucción hablada. Inténtalo de nuevo."
                )
            return TranscriptionResult(
                text=text,
                duration_seconds=float(getattr(info, "duration", duration) or duration),
            )
        except (VoiceInputError, VoiceUnavailableError):
            raise
        except Exception as exc:
            raise VoiceInputError(
                "No fue posible transcribir el audio localmente."
            ) from exc
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
