from __future__ import annotations

import asyncio
import base64
import importlib.util
import os
from collections import OrderedDict
from pathlib import Path

import httpx

from ..auth import AuthenticatedUser
from ..config import Settings
from .commands import VoiceCommandRouter
from .context import VoiceContextStore
from .errors import (
    VoiceInputError,
    VoiceTimeoutError,
    VoiceTTSUnavailableError,
    VoiceUnavailableError,
)
from .gemma import (
    OllamaGemmaInterpreter,
    VoiceIntentInterpreter,
    _deterministic_intent,
    is_explicit_help_request,
)
from .models import (
    VoiceCommandResponse,
    VoiceComponentStatus,
    VoiceContextView,
    VoiceStatusResponse,
)
from .stt import FasterWhisperTranscriber, VoiceTranscriber
from .tts import VoiceSynthesizer, build_voice_synthesizer


class VoiceCommandService:
    def __init__(
        self,
        settings: Settings,
        router: VoiceCommandRouter,
        transcriber: VoiceTranscriber | None = None,
        interpreter: VoiceIntentInterpreter | None = None,
        synthesizer: VoiceSynthesizer | None = None,
        context_store: VoiceContextStore | None = None,
    ):
        self.settings = settings
        self.router = router
        self.transcriber = transcriber or FasterWhisperTranscriber(settings)
        self.interpreter = interpreter or OllamaGemmaInterpreter(settings)
        self.synthesizer = synthesizer or build_voice_synthesizer(settings)
        self.context_store = context_store or router.context_store
        self._session_locks: OrderedDict[str, asyncio.Lock] = OrderedDict()
        self._session_locks_guard = asyncio.Lock()
        self._status_lock = asyncio.Lock()
        self._activated = False
        self._status = self._initial_status()

    def _initial_status(self) -> VoiceStatusResponse:
        stt_enabled = self.settings.voice_stt_enabled
        llm_enabled = self.settings.voice_ai_enabled
        tts_enabled = self.settings.voice_tts_enabled
        return VoiceStatusResponse(
            state=(
                "DISABLED"
                if not any((stt_enabled, llm_enabled, tts_enabled))
                else "NOT_STARTED"
            ),
            activated=False,
            message=(
                "Las funciones de voz están desactivadas en esta instalación."
                if not any((stt_enabled, llm_enabled, tts_enabled))
                else "La voz todavía no ha sido activada."
            ),
            stt=VoiceComponentStatus(
                name="STT",
                state="NOT_LOADED" if stt_enabled else "DISABLED",
                enabled=stt_enabled,
                configuration="enabled" if stt_enabled else "disabled",
                detail=(
                    "Whisper se cargará al primer uso."
                    if stt_enabled
                    else "VOICE_STT_ENABLED está deshabilitado."
                ),
                provider="faster-whisper",
                model=self.settings.voice_whisper_model,
            ),
            llm=VoiceComponentStatus(
                name="LLM",
                state="NOT_LOADED" if llm_enabled else "DISABLED",
                enabled=llm_enabled,
                configuration="enabled" if llm_enabled else "disabled",
                detail=(
                    "Ollama y Gemma se comprobarán al activar voz."
                    if llm_enabled
                    else "VOICE_AI_ENABLED está deshabilitado."
                ),
                provider=self.settings.voice_llm_provider,
                model=self.settings.voice_gemma_model or None,
            ),
            tts=VoiceComponentStatus(
                name="TTS",
                state="NOT_LOADED" if tts_enabled else "DISABLED",
                enabled=tts_enabled,
                configuration="enabled" if tts_enabled else "disabled",
                detail=(
                    "El proveedor TTS se cargará al sintetizar."
                    if tts_enabled
                    else "VOICE_TTS_ENABLED está deshabilitado."
                ),
                provider=self.settings.voice_tts_provider,
                model=self.settings.voice_tts_voice,
            ),
        )

    def get_status(self) -> VoiceStatusResponse:
        return self._status.model_copy(deep=True)

    def _set_component(self, name: str, **changes: object) -> None:
        current = getattr(self._status, name)
        updated = current.model_copy(update=changes)
        self._status = self._status.model_copy(update={name: updated})

    def _derive_overall_state(self) -> str:
        enabled = [component for component in (self._status.stt, self._status.llm, self._status.tts) if component.enabled]
        if not enabled:
            return "DISABLED"
        errors = [component for component in enabled if component.state == "ERROR"]
        if errors and len(errors) == len(enabled):
            return "ERROR"
        if errors:
            return "PARTIAL"
        return "READY"

    def _refresh_loaded_states(self) -> None:
        if self.settings.voice_stt_enabled and getattr(self.transcriber, "_model", None) is not None:
            self._set_component("stt", state="READY", available=True, detail="Whisper está cargado y listo.")
        if self.settings.voice_tts_enabled and getattr(self.synthesizer, "_voice", None) is not None:
            self._set_component("tts", state="READY", available=True, detail="El proveedor TTS está cargado y listo.")

    async def activate(self) -> VoiceStatusResponse:
        """Run only lightweight checks; never load a model or open a microphone."""
        async with self._status_lock:
            self._activated = True
            self._status = self._status.model_copy(
                update={
                    "state": "LOADING",
                    "activated": True,
                    "message": "Comprobando componentes de voz...",
                }
            )
            await asyncio.sleep(0)
            for component in ("stt", "llm", "tts"):
                current = getattr(self._status, component)
                if current.enabled:
                    self._set_component(component, state="LOADING", available=None)

            self._check_stt()
            await self._check_llm()
            self._check_tts()
            self._refresh_loaded_states()
            overall = self._derive_overall_state()
            self._status = self._status.model_copy(
                update={
                    "state": overall,
                    "message": (
                        "Voz parcialmente disponible. Revisa los componentes con error."
                        if overall == "PARTIAL"
                        else "No hay componentes de voz disponibles."
                        if overall == "ERROR"
                        else "Voz preparada. Los modelos se cargarán al primer uso."
                    ),
                }
            )
            return self.get_status()

    def _check_stt(self) -> None:
        if not self.settings.voice_stt_enabled:
            return
        missing = [
            package
            for package in ("faster_whisper", "av")
            if importlib.util.find_spec(package) is None
        ]
        if missing:
            self._set_component(
                "stt",
                state="ERROR",
                available=False,
                detail=(
                    "Falta dependencia local de reconocimiento: "
                    + ", ".join(missing)
                    + ". Instala las dependencias de voz."
                ),
            )
            return
        local_model = self._whisper_model_is_local()
        model_detail = (
            f"Whisper '{self.settings.voice_whisper_model}' está disponible localmente y "
            "se cargará al primer uso."
            if local_model
            else (
                f"El modelo Whisper '{self.settings.voice_whisper_model}' no está disponible localmente. "
                "El primer uso puede requerir obtenerlo; esta comprobación no descarga modelos."
            )
        )
        self._set_component(
            "stt",
            state="NOT_LOADED",
            available=local_model,
            detail=model_detail,
        )

    def _whisper_model_is_local(self) -> bool:
        configured = Path(self.settings.voice_whisper_model).expanduser()
        if configured.is_dir():
            return True
        model = self.settings.voice_whisper_model.strip()
        if not model:
            return False
        cache_roots: list[Path] = []
        for variable in ("HF_HOME", "HUGGINGFACE_HUB_CACHE", "TRANSFORMERS_CACHE"):
            value = os.getenv(variable)
            if value:
                root = Path(value).expanduser()
                cache_roots.append(root / "hub" if variable == "HF_HOME" else root)
        cache_roots.append(Path.home() / ".cache" / "huggingface" / "hub")
        cache_name = f"models--Systran--faster-whisper-{model.replace('/', '--')}"
        return any((root / cache_name).is_dir() for root in cache_roots)

    async def _check_llm(self) -> None:
        if not self.settings.voice_ai_enabled:
            return
        if self.settings.voice_llm_provider != "ollama":
            self._set_component(
                "llm",
                state="ERROR",
                available=False,
                detail="El proveedor de IA de voz configurado no está permitido. Usa Ollama local.",
            )
            return
        model = self.settings.voice_gemma_model
        if not model:
            self._set_component(
                "llm",
                state="ERROR",
                available=False,
                detail="Configura VOICE_GEMMA_MODEL, por ejemplo gemma3:1b.",
            )
            return
        try:
            async with httpx.AsyncClient(
                base_url=self.settings.ollama_base_url,
                timeout=2.0,
            ) as client:
                response = await client.get("/api/tags")
                response.raise_for_status()
                models = response.json().get("models", [])
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            self._set_component(
                "llm",
                state="ERROR",
                available=False,
                detail="Ollama no está disponible. Inicia Ollama localmente y vuelve a activar voz.",
            )
            return
        names = {entry.get("name") for entry in models if isinstance(entry, dict)}
        if model not in names:
            self._set_component(
                "llm",
                state="ERROR",
                available=False,
                detail=f"Ollama está disponible, pero no se encontró el modelo {model}.",
            )
            return
        self._set_component(
            "llm",
            state="READY",
            available=True,
            detail=(
                f"Ollama responde y el modelo {model} está disponible. "
                "Gemma se ejecuta fuera del backend."
            ),
        )

    def _check_tts(self) -> None:
        if not self.settings.voice_tts_enabled:
            return
        provider = self.settings.voice_tts_provider
        if provider == "piper":
            model_path = self.settings.voice_tts_model_path
            if not model_path.is_file() or not (model_path.parent / f"{model_path.name}.json").is_file():
                self._set_component(
                    "tts",
                    state="ERROR",
                    available=False,
                    detail="El modelo Piper configurado no existe. Ejecuta el instalador de voz.",
                )
                return
            if importlib.util.find_spec("piper") is None:
                self._set_component(
                    "tts",
                    state="ERROR",
                    available=False,
                    detail="Piper no está instalado. Instala las dependencias de voz.",
                )
                return
        elif provider == "sapi5":
            if importlib.util.find_spec("win32com") is None:
                self._set_component(
                    "tts",
                    state="ERROR",
                    available=False,
                    detail="SAPI5 no está disponible en este entorno de Windows.",
                )
                return
        else:
            self._set_component(
                "tts",
                state="ERROR",
                available=False,
                detail=f"El proveedor TTS local '{provider}' no está soportado.",
            )
            return
        self._set_component(
            "tts",
            state="NOT_LOADED",
            available=True,
            detail=f"{provider} está configurado y se cargará al primer uso.",
        )

    def _mark_error(self, component: str, detail: str) -> None:
        self._set_component(component, state="ERROR", available=False, detail=detail)
        self._status = self._status.model_copy(
            update={
                "state": self._derive_overall_state(),
                "message": "Voz parcialmente disponible. Revisa los componentes con error.",
            }
        )

    def _mark_ready(self, component: str, detail: str) -> None:
        self._set_component(component, state="READY", available=True, detail=detail)
        self._status = self._status.model_copy(
            update={"state": self._derive_overall_state(), "message": "Voz preparada."}
        )

    async def _session_lock(self, session_id: str) -> asyncio.Lock:
        async with self._session_locks_guard:
            lock = self._session_locks.get(session_id)
            if lock is None:
                lock = asyncio.Lock()
                self._session_locks[session_id] = lock
            else:
                self._session_locks.move_to_end(session_id)
            if len(self._session_locks) > 256:
                for key, candidate in list(self._session_locks.items()):
                    if key != session_id and not candidate.locked():
                        self._session_locks.pop(key, None)
                    if len(self._session_locks) <= 192:
                        break
            return lock

    async def process(
        self,
        audio: bytes,
        content_type: str,
        user: AuthenticatedUser,
        current_proposal_id: str | None = None,
        spoken_response: bool = False,
    ) -> VoiceCommandResponse:
        if not self.settings.voice_stt_enabled:
            raise VoiceUnavailableError(
                "El reconocimiento de voz está deshabilitado. Activa VOICE_STT_ENABLED."
            )
        try:
            return await asyncio.wait_for(
                self._process(
                    audio,
                    content_type,
                    user,
                    current_proposal_id,
                    spoken_response,
                ),
                timeout=self.settings.voice_command_timeout_seconds,
            )
        except TimeoutError as exc:
            raise VoiceTimeoutError(
                "El comando de voz superó el tiempo máximo de procesamiento."
            ) from exc

    async def _process(
        self,
        audio: bytes,
        content_type: str,
        user: AuthenticatedUser,
        current_proposal_id: str | None,
        spoken_response: bool,
    ) -> VoiceCommandResponse:
        try:
            transcription = await self.transcriber.transcribe(audio, content_type)
        except VoiceUnavailableError as exc:
            self._mark_error("stt", str(exc))
            raise
        else:
            self._mark_ready("stt", "Whisper está cargado y listo.")
        if transcription.duration_seconds > self.settings.voice_max_duration_seconds:
            raise VoiceInputError(
                f"El audio supera el límite de {int(self.settings.voice_max_duration_seconds)} segundos."
            )
        context = self.context_store.get(user)
        lock = await self._session_lock(context.session_id)
        async with lock:
            context = self.context_store.get(user)
            if current_proposal_id:
                context.active_proposal_id = current_proposal_id
            if self.settings.voice_ai_enabled:
                try:
                    intent = await self.interpreter.interpret(transcription.text, context)
                except VoiceUnavailableError as exc:
                    self._mark_error("llm", str(exc))
                    raise
                else:
                    self._mark_ready(
                        "llm",
                        "Ollama y el modelo configurado respondieron correctamente.",
                    )
            else:
                intent = _deterministic_intent(transcription.text, context)
                if intent is None:
                    raise VoiceUnavailableError(
                        "La IA de voz está deshabilitada; sólo están disponibles comandos deterministas. "
                        "Activa VOICE_AI_ENABLED para usar Gemma."
                    )
            unexpected_help = intent.intent == "help" and not is_explicit_help_request(
                transcription.text
            )
            if unexpected_help:
                intent = intent.model_copy(update={"confidence": 0.0})
            if intent.confidence < self.settings.voice_min_confidence:
                response = VoiceCommandResponse(
                    transcript=transcription.text,
                    intent=intent.intent,
                    status="needs_clarification",
                    message=(
                        "No pude relacionar lo que entendí con una función disponible. "
                        "Repítelo con una frase breve, por favor."
                        if unexpected_help
                        else "No entendí con suficiente certeza. ¿Puedes repetirlo?"
                    ),
                    draft=(
                        context.draft
                        if context.draft and context.draft.status == "draft"
                        else None
                    ),
                    context=VoiceContextView.from_context(context),
                )
            else:
                outcome = await self.router.execute(
                    intent,
                    user,
                    current_proposal_id,
                    context,
                )
                response = VoiceCommandResponse(
                    transcript=transcription.text,
                    intent=intent.intent,
                    status=outcome.status,
                    message=outcome.message,
                    requires_confirmation=outcome.requires_confirmation,
                    risk=outcome.risk.value,
                    draft=outcome.draft,
                    context=VoiceContextView.from_context(outcome.context),
                    jira_operation=outcome.jira_operation,
                )
        return await self._attach_audio(response, spoken_response)

    async def confirm_jira(
        self,
        user: AuthenticatedUser,
        confirmation_id: str,
        payload_hash: str,
        spoken_response: bool = False,
    ) -> VoiceCommandResponse:
        context = self.context_store.get(user)
        lock = await self._session_lock(context.session_id)
        async with lock:
            context = self.context_store.get(user)
            outcome = await self.router.confirm_jira(
                user,
                context,
                confirmation_id,
                payload_hash,
            )
            if outcome.persist_context:
                self.context_store.save(outcome.context)
            response = VoiceCommandResponse(
                transcript="",
                intent="confirm_jira_create",
                status=outcome.status,
                message=outcome.message,
                requires_confirmation=False,
                risk=outcome.risk.value,
                draft=outcome.draft,
                context=VoiceContextView.from_context(outcome.context),
                jira_operation=outcome.jira_operation,
            )
        return await self._attach_audio(response, spoken_response)

    async def cancel_jira(
        self,
        user: AuthenticatedUser,
        confirmation_id: str,
        payload_hash: str,
        spoken_response: bool = False,
    ) -> VoiceCommandResponse:
        context = self.context_store.get(user)
        lock = await self._session_lock(context.session_id)
        async with lock:
            context = self.context_store.get(user)
            outcome = self.router.cancel_jira(
                user,
                context,
                confirmation_id,
                payload_hash,
            )
            if outcome.persist_context:
                self.context_store.save(outcome.context)
            response = VoiceCommandResponse(
                transcript="",
                intent="reject_pending_action",
                status=outcome.status,
                message=outcome.message,
                requires_confirmation=False,
                risk=outcome.risk.value,
                draft=outcome.draft,
                context=VoiceContextView.from_context(outcome.context),
                jira_operation=outcome.jira_operation,
            )
        return await self._attach_audio(response, spoken_response)

    async def _attach_audio(
        self,
        response: VoiceCommandResponse,
        spoken_response: bool,
    ) -> VoiceCommandResponse:
        if not spoken_response or not self.settings.voice_tts_enabled:
            return response
        try:
            audio = await asyncio.wait_for(
                self.synthesizer.synthesize(response.message),
                timeout=self.settings.voice_tts_timeout_seconds,
            )
        except (VoiceTTSUnavailableError, TimeoutError) as exc:
            detail = (
                str(exc)
                if isinstance(exc, VoiceTTSUnavailableError)
                else "La síntesis de voz agotó el tiempo de espera."
            )
            self._mark_error("tts", detail)
            return response.model_copy(
                update={
                    "audio_error": (
                        "No fue posible reproducir la respuesta por voz. "
                        "La respuesta escrita sigue disponible. "
                        + detail
                    )
                }
            )
        else:
            self._mark_ready("tts", "El proveedor TTS está cargado y listo.")
        return response.model_copy(
            update={
                "audio_available": True,
                "audio_base64": base64.b64encode(audio.content).decode("ascii"),
                "audio_mime_type": "audio/wav",
            }
        )

    def get_context(self, user: AuthenticatedUser) -> VoiceContextView:
        return VoiceContextView.from_context(self.context_store.get(user))

    def clear_context(self, user: AuthenticatedUser) -> VoiceContextView:
        self.context_store.clear(user)
        return VoiceContextView.from_context(self.context_store.get(user))
