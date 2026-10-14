from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BACKEND_DIR.parent
CURRENT_TEMPLATE_VERSION = "1.3"


@dataclass(frozen=True)
class Settings:
    database_path: Path
    schema_path: Path
    frontend_dist: Path
    frozen_template_path: Path
    local_user: str
    local_password: str
    emergency_local_auth_enabled: bool = False
    allow_all_corporate_users: bool = False
    app_session_ttl_seconds: int = 28800
    atlassian_mcp_url: str = "https://mcp.atlassian.com/v1/mcp/authv2"
    atlassian_site_url: str = "https://dpti.atlassian.net"
    atlassian_proxy_url: str | None = None
    atlassian_oauth_callback_url: str = (
        "http://localhost:8000/api/integrations/atlassian/callback"
    )
    atlassian_oauth_storage_dir: Path | None = None
    jira_execution_policy_path: Path = PROJECT_DIR / "config" / "jira_execution_policy_v1.json"
    jira_execution_policy_schema_path: Path = (
        PROJECT_DIR / "docs" / "schemas" / "jira_execution_policy_v1.schema.json"
    )
    jira_write_lock_ttl_seconds: int = 900
    jira_read_concurrency: int = 4
    voice_stt_enabled: bool = False
    voice_whisper_model: str = "small"
    voice_whisper_language: str = "es"
    voice_whisper_device: str = "cpu"
    voice_whisper_compute_type: str = "int8"
    voice_whisper_beam_size: int = 2
    voice_whisper_hotwords: str = (
        "Vic Jira genera nueva propuesta confirmación autenticación tarea Task Story Bug "
        "Epic Subtask Héctor Víctor prioridad responsable asígnala envíala"
    )
    voice_ai_enabled: bool = False
    voice_llm_provider: str = "ollama"
    voice_gemma_model: str = ""
    ollama_base_url: str = "http://127.0.0.1:11434"
    minutes_ai_enabled: bool = True
    minutes_llm_model: str = "qwen3.5:4b"
    minutes_prompt_version: str = "minutes_semantic_v1"
    minutes_enrichment_model: str = "qwen3.5:4b"
    minutes_enrichment_timeout_seconds: float = 30.0
    minutes_max_chars: int = 30000
    minutes_timeout_seconds: float = 120.0
    news_telegram_url: str | None = None
    voice_max_audio_bytes: int = 10 * 1024 * 1024
    voice_max_duration_seconds: float = 30.0
    voice_command_timeout_seconds: float = 60.0
    voice_min_confidence: float = 0.70
    voice_context_ttl_seconds: int = 1800
    voice_jira_confirmation_ttl_seconds: int = 600
    voice_tts_enabled: bool = False
    voice_tts_provider: str = "piper"
    voice_tts_voice: str = "es_MX-ald-medium"
    voice_tts_model_path: Path = (
        BACKEND_DIR / "data" / "voices" / "es_MX-ald-medium.onnx"
    )
    voice_tts_length_scale: float = 1.0
    voice_tts_rate: int = 0
    voice_tts_timeout_seconds: float = 10.0
    voice_tts_max_chars: int = 500


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _telegram_url(value: str | None) -> str | None:
    candidate = (value or "").strip()
    parsed = urlparse(candidate)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {"t.me", "www.t.me", "telegram.me", "www.telegram.me"}
        or not parsed.path.strip("/")
    ):
        return None
    return candidate


def get_settings() -> Settings:
    database_path = Path(
        os.getenv("AGENTE_JIRA_DB", str(BACKEND_DIR / "data" / "agente_jira.db"))
    )
    voice_tts_model_path = Path(
        os.getenv(
            "VOICE_TTS_MODEL_PATH",
            str(BACKEND_DIR / "data" / "voices" / "es_MX-ald-medium.onnx"),
        )
    )
    if not voice_tts_model_path.is_absolute():
        voice_tts_model_path = PROJECT_DIR / voice_tts_model_path
    public_base_url = os.getenv("AGENTE_JIRA_PUBLIC_BASE_URL", "").strip().rstrip("/")
    callback_default = (
        f"{public_base_url}/api/integrations/atlassian/callback"
        if public_base_url
        else "http://localhost:8000/api/integrations/atlassian/callback"
    )
    return Settings(
        database_path=database_path,
        schema_path=PROJECT_DIR / "docs" / "schemas" / "jira_proposal_v1_1.schema.json",
        frontend_dist=PROJECT_DIR / "frontend" / "dist",
        frozen_template_path=(
            PROJECT_DIR
            / "releases"
            / "plantilla_excel_v1_1"
            / "plantilla_plan_trabajo_jira_v1_1.xlsx"
        ),
        local_user=os.getenv("AGENTE_JIRA_LOCAL_USER", "admin@agentejira.local"),
        # There is intentionally no password fallback in runtime code.  A local
        # operator must opt in through the environment; an empty value keeps the
        # service fail-safe while allowing health/doctor diagnostics to run.
        local_password=os.getenv("AGENTE_JIRA_LOCAL_PASSWORD", "").strip(),
        emergency_local_auth_enabled=_env_bool("AGENTE_JIRA_EMERGENCY_LOCAL_AUTH_ENABLED", False),
        allow_all_corporate_users=_env_bool("AGENTE_JIRA_ALLOW_ALL_CORPORATE_USERS", False),
        app_session_ttl_seconds=max(900, min(86400, _env_int("AGENTE_JIRA_SESSION_TTL_SECONDS", 28800))),
        atlassian_mcp_url=os.getenv(
            "AGENTE_JIRA_ATLASSIAN_MCP_URL",
            # This client enumerates the complete Jira tool catalog during
            # connection.  The v2 endpoint exposes tools lazily through its
            # `discover` tool, whereas authv2 retains the compatible catalog.
            "https://mcp.atlassian.com/v1/mcp/authv2",
        ),
        atlassian_site_url=os.getenv(
            "AGENTE_JIRA_ATLASSIAN_SITE_URL",
            "https://dpti.atlassian.net",
        ),
        # Corporate Windows proxy/PAC settings are not consumed consistently by
        # Python HTTP clients.  Keep this explicit and scoped to Atlassian.
        atlassian_proxy_url=(
            os.getenv("AGENTE_JIRA_ATLASSIAN_PROXY_URL", "").strip() or None
        ),
        atlassian_oauth_callback_url=os.getenv(
            "AGENTE_JIRA_ATLASSIAN_CALLBACK_URL",
            callback_default,
        ),
        atlassian_oauth_storage_dir=Path(
            os.getenv(
                "AGENTE_JIRA_ATLASSIAN_OAUTH_DIR",
                str(BACKEND_DIR / "data" / "atlassian_oauth"),
            )
        ),
        jira_execution_policy_path=Path(
            os.getenv(
                "AGENTE_JIRA_EXECUTION_POLICY",
                str(PROJECT_DIR / "config" / "jira_execution_policy_v1.json"),
            )
        ),
        jira_execution_policy_schema_path=(
            PROJECT_DIR / "docs" / "schemas" / "jira_execution_policy_v1.schema.json"
        ),
        jira_write_lock_ttl_seconds=max(
            60,
            min(3600, _env_int("AGENTE_JIRA_WRITE_LOCK_TTL_SECONDS", 900)),
        ),
        jira_read_concurrency=max(
            1,
            min(8, _env_int("AGENTE_JIRA_READ_CONCURRENCY", 4)),
        ),
        voice_stt_enabled=_env_bool("VOICE_STT_ENABLED", False),
        voice_whisper_model=os.getenv("VOICE_WHISPER_MODEL", "small").strip() or "small",
        voice_whisper_language=(
            os.getenv("VOICE_WHISPER_LANGUAGE", "es").strip() or "es"
        ),
        voice_whisper_device=(
            os.getenv("VOICE_WHISPER_DEVICE", "cpu").strip() or "cpu"
        ),
        voice_whisper_compute_type=(
            os.getenv("VOICE_WHISPER_COMPUTE_TYPE", "int8").strip() or "int8"
        ),
        voice_whisper_beam_size=max(
            1,
            min(10, _env_int("VOICE_WHISPER_BEAM_SIZE", 2)),
        ),
        voice_whisper_hotwords=os.getenv(
            "VOICE_WHISPER_HOTWORDS",
            "Vic Jira genera nueva propuesta confirmación autenticación tarea Task Story Bug "
            "Epic Subtask Héctor Víctor prioridad responsable asígnala envíala",
        ).strip(),
        voice_ai_enabled=_env_bool("VOICE_AI_ENABLED", False),
        minutes_ai_enabled=_env_bool("MINUTES_AI_ENABLED", True),
        minutes_llm_model=(os.getenv("MINUTES_LLM_MODEL", "qwen3.5:4b").strip() or "qwen3.5:4b"),
        minutes_prompt_version=(os.getenv("MINUTES_PROMPT_VERSION", "minutes_semantic_v1").strip() or "minutes_semantic_v1"),
        minutes_enrichment_model=(os.getenv("MINUTES_ENRICHMENT_MODEL", "qwen3.5:4b").strip() or "qwen3.5:4b"),
        minutes_enrichment_timeout_seconds=max(5.0, min(90.0, _env_float("MINUTES_ENRICHMENT_TIMEOUT_SECONDS", 30.0))),
        minutes_max_chars=max(100, min(100000, _env_int("MINUTES_MAX_CHARS", 30000))),
        minutes_timeout_seconds=max(5.0, min(300.0, _env_float("MINUTES_TIMEOUT_SECONDS", 120.0))),
        news_telegram_url=_telegram_url(os.getenv("NEWS_TELEGRAM_URL")),
        voice_llm_provider=(
            os.getenv("VOICE_LLM_PROVIDER", "ollama").strip().lower() or "ollama"
        ),
        voice_gemma_model=os.getenv("VOICE_GEMMA_MODEL", "").strip(),
        ollama_base_url=(
            os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
        ),
        voice_max_audio_bytes=max(
            1,
            _env_int("VOICE_MAX_AUDIO_BYTES", 10 * 1024 * 1024),
        ),
        voice_max_duration_seconds=max(
            1.0,
            _env_float("VOICE_MAX_DURATION_SECONDS", 30.0),
        ),
        voice_command_timeout_seconds=max(
            1.0,
            _env_float("VOICE_COMMAND_TIMEOUT_SECONDS", 60.0),
        ),
        voice_min_confidence=min(
            1.0,
            max(0.0, _env_float("VOICE_MIN_CONFIDENCE", 0.70)),
        ),
        voice_context_ttl_seconds=max(
            60,
            _env_int("VOICE_CONTEXT_TTL_SECONDS", 1800),
        ),
        voice_jira_confirmation_ttl_seconds=max(
            30,
            _env_int("VOICE_JIRA_CONFIRMATION_TTL_SECONDS", 600),
        ),
        voice_tts_enabled=_env_bool("VOICE_TTS_ENABLED", False),
        voice_tts_provider=(
            os.getenv("VOICE_TTS_PROVIDER", "piper").strip().lower() or "piper"
        ),
        voice_tts_voice=(
            os.getenv("VOICE_TTS_VOICE", "es_MX-ald-medium").strip()
        ),
        voice_tts_model_path=voice_tts_model_path,
        voice_tts_length_scale=max(
            0.5,
            min(2.0, _env_float("VOICE_TTS_LENGTH_SCALE", 1.0)),
        ),
        voice_tts_rate=max(-10, min(10, _env_int("VOICE_TTS_RATE", 0))),
        voice_tts_timeout_seconds=max(
            1.0,
            _env_float("VOICE_TTS_TIMEOUT_SECONDS", 10.0),
        ),
        voice_tts_max_chars=max(
            40,
            min(2000, _env_int("VOICE_TTS_MAX_CHARS", 500)),
        ),
    )
