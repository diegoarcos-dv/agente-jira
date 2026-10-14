from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import Any, Protocol
from urllib.parse import parse_qs, urlparse

import httpx
from mcp import ClientSession
from mcp.client.auth import OAuthClientProvider, TokenStorage
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import (
    OAuthClientInformationFull,
    OAuthClientMetadata,
    OAuthToken,
)

from .config import Settings
from .connection_diagnostics import ConnectionDiagnostics, ConnectionFailure, failure_report
from .oauth_storage import EncryptedFileOAuthStorage, WindowsDpapiProtector
from .jira_write_lock import GlobalJiraWriteLock, GlobalJiraWriteLockError
from .performance import current_trace

logger = logging.getLogger(__name__)

TARGET_SPACES = ("AT", "ASIT", "MTTI")
VISIBLE_PROJECTS_MAX_RESULTS = 50
FIELD_METADATA_MAX_RESULTS = 50
FIELD_METADATA_MAX_PAGES = 20
OAUTH_CONSENT_TIMEOUT_SECONDS = 300
ASSIGNEE_LOOKUP_CACHE_TTL_SECONDS = 45

# This is the only tool surface the application is allowed to invoke in Objective 3A.
# The guard is enforced before the MCP transport is reached and is covered by tests.
READ_ONLY_TOOL_ALLOWLIST = frozenset(
    {
        "atlassianUserInfo",
        "getAccessibleAtlassianResources",
        "getVisibleJiraProjects",
        "getJiraProjectIssueTypesMetadata",
        "getJiraIssueTypeMetaWithFields",
        "lookupJiraAccountId",
        "findAssignableUsers",
        "getJiraIssue",
        "searchJiraIssuesUsingJql",
    }
)


class AtlassianIntegrationError(RuntimeError):
    pass


class WriteToolBlocked(AtlassianIntegrationError):
    pass


class ControlledJiraWriteError(AtlassianIntegrationError):
    def __init__(
        self,
        message: str,
        *,
        outcome_uncertain: bool,
        real_mcp_calls: int,
    ) -> None:
        super().__init__(message)
        self.outcome_uncertain = outcome_uncertain
        self.real_mcp_calls = real_mcp_calls


def _is_explicit_jira_create_rejection(error: BaseException) -> bool:
    """Distinguish a Jira 4xx/tool rejection from an ambiguous transport failure."""

    message = str(error).casefold()
    rejection_markers = (
        "failed to create issue: bad request",
        "failed to create issue: unauthorized",
        "failed to create issue: forbidden",
        "failed to create issue: not found",
        "failed to create issue: conflict",
        "failed to create issue: unprocessable",
        "jira rechazo la creacion",
    )
    return any(marker in message for marker in rejection_markers)


class InMemoryOAuthStorage(TokenStorage):
    """OAuth state that intentionally disappears when the process stops."""

    def __init__(self) -> None:
        self.tokens: OAuthToken | None = None
        self.client_info: OAuthClientInformationFull | None = None

    async def get_tokens(self) -> OAuthToken | None:
        return self.tokens

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self.tokens = tokens

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        return self.client_info

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self.client_info = client_info

    def clear(self) -> None:
        self.tokens = None
        self.client_info = None

    @property
    def has_credentials(self) -> bool:
        return self.tokens is not None and self.client_info is not None


class McpSessionLike(Protocol):
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any: ...


def ensure_read_only_tool(name: str) -> None:
    if name not in READ_ONLY_TOOL_ALLOWLIST:
        raise WriteToolBlocked(
            f"La herramienta MCP '{name}' está bloqueada por la política de solo lectura del Objetivo 3A."
        )


async def call_read_only_tool(
    session: McpSessionLike,
    name: str,
    arguments: dict[str, Any] | None = None,
) -> Any:
    ensure_read_only_tool(name)
    return await session.call_tool(name, arguments or {})


def _tool_payload(result: Any) -> Any:
    structured = getattr(result, "structuredContent", None)
    if structured is not None:
        return structured
    content = getattr(result, "content", None) or []
    texts = [getattr(block, "text", "") for block in content if getattr(block, "text", "")]
    if not texts:
        return None
    combined = "\n".join(texts)
    try:
        return json.loads(combined)
    except json.JSONDecodeError:
        return combined


def _records(payload: Any, preferred: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in (*preferred, "values", "results", "items", "data", "projects", "issueTypes", "users"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            nested = _records(value, preferred)
            if nested:
                return nested
    return [payload]


def _field_records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict) and isinstance(payload.get("fields"), dict):
        return [
            {"fieldId": field_id, **value}
            for field_id, value in payload["fields"].items()
            if isinstance(value, dict)
        ]
    return _records(payload, ("fields",))


def _schema_arguments(
    tool: Any,
    values: dict[str, Any],
) -> dict[str, Any]:
    schema = getattr(tool, "inputSchema", None) or {}
    properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
    required = set(schema.get("required", ())) if isinstance(schema, dict) else set()
    arguments: dict[str, Any] = {}
    consumed_canonical: set[str] = set()
    aliases = {
        "cloudId": ("cloudId", "cloud_id"),
        # Atlassian currently publishes both projectKey and projectIdOrKey for
        # some read tools while server-side validation requires the latter.
        # Write tools that only expose projectKey still map to projectKey.
        "projectKey": ("projectIdOrKey", "projectKey", "projectId", "project"),
        "issueTypeId": ("issueTypeId", "issueType", "issuetypeId"),
        "query": ("query", "searchString", "searchTerm", "text", "username"),
        "jql": ("jql",),
        "maxResults": ("maxResults", "limit"),
        "startAt": ("startAt", "offset"),
        "requiredFieldsOnly": ("requiredFieldsOnly",),
        "nextPageToken": ("nextPageToken", "pageToken"),
        "issueIdOrKey": ("issueIdOrKey", "issueKey", "issueId"),
        "fields": ("fields",),
        "fieldsByKeys": ("fieldsByKeys",),
        "responseContentFormat": ("responseContentFormat",),
    }
    for canonical, candidates in aliases.items():
        if canonical not in values:
            continue
        # Some Atlassian MCP schemas expose legacy and current aliases at the
        # same time, but require only one of them. Prefer the required alias so
        # the payload follows the contract actually validated by the server.
        ordered_candidates = (*[item for item in candidates if item in required],
                              *[item for item in candidates if item not in required])
        for candidate in ordered_candidates:
            if candidate in properties:
                arguments[candidate] = values[canonical]
                consumed_canonical.add(canonical)
                break
    # Callers may already have schema-native arguments (for example after a
    # first mapping pass in the dashboard service). Keep those values instead
    # of dropping them when this guard maps the request again.
    for key, value in values.items():
        if key in properties and key not in arguments and key not in consumed_canonical:
            arguments[key] = value
    return arguments


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _extract_issue_key(payload: Any) -> str | None:
    if isinstance(payload, dict):
        for key in ("key", "issueKey", "issue_key"):
            value = payload.get(key)
            if value and re.fullmatch(r"[A-Z][A-Z0-9]+-[0-9]+", str(value).upper()):
                return str(value).upper()
        for value in payload.values():
            found = _extract_issue_key(value)
            if found:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = _extract_issue_key(value)
            if found:
                return found
    elif isinstance(payload, str):
        match = re.search(r"\b[A-Z][A-Z0-9]+-[0-9]+\b", payload.upper())
        if match:
            return match.group(0)
    return None


def _sprints_from_value(value: Any, fallback_state: str) -> list[dict[str, Any]]:
    """Normalize Sprint values returned by modern and legacy Jira issue payloads."""

    if isinstance(value, list):
        result: list[dict[str, Any]] = []
        for candidate in value:
            result.extend(_sprints_from_value(candidate, fallback_state))
        return result
    if isinstance(value, dict):
        sprint_id = value.get("id") or value.get("sprintId")
        name = value.get("name") or value.get("value")
        if sprint_id is None or name is None:
            result = []
            for nested in value.values():
                result.extend(_sprints_from_value(nested, fallback_state))
            return result
        return [{
            "id": str(sprint_id),
            "name": str(name),
            "state": str(value.get("state") or fallback_state).casefold(),
            "board_id": value.get("boardId") or value.get("rapidViewId") or value.get("board_id"),
            "source": "ROVO_MCP_JQL",
        }]
    if not isinstance(value, str):
        return []
    # Legacy Jira serialized Sprint: [id=321,rapidViewId=45,state=ACTIVE,name=SPT-01,...]
    result = []
    for raw in re.findall(r"\[([^\]]*\bid=\d+[^\]]*)\]", value):
        sprint_id = re.search(r"(?:^|,)id=(\d+)", raw)
        name = re.search(r"(?:^|,)name=([^,]+)", raw)
        state = re.search(r"(?:^|,)state=([^,]+)", raw)
        board_id = re.search(r"(?:^|,)(?:rapidViewId|boardId)=(\d+)", raw)
        if sprint_id and name:
            result.append({
                "id": sprint_id.group(1),
                "name": name.group(1).strip(),
                "state": (state.group(1) if state else fallback_state).strip().casefold(),
                "board_id": board_id.group(1) if board_id else None,
                "source": "ROVO_MCP_JQL",
            })
    return result


def _extract_sprints(payload: Any, field_ids: set[str], fallback_state: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for issue in _records(payload, ("issues",)):
        fields = issue.get("fields")
        if not isinstance(fields, dict):
            continue
        for field_id, value in fields.items():
            if field_id in field_ids or _normalize_identity(field_id) == "sprint":
                result.extend(_sprints_from_value(value, fallback_state))
    return result


def _next_page_token(payload: Any) -> str | None:
    if isinstance(payload, dict):
        for key in ("nextPageToken", "next_page_token", "pageToken"):
            value = payload.get(key)
            if value:
                return str(value)
        for value in payload.values():
            token = _next_page_token(value)
            if token:
                return token
    elif isinstance(payload, list):
        for value in payload:
            token = _next_page_token(value)
            if token:
                return token
    return None


def _normalize_identity(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(character for character in text if not unicodedata.combining(character))
    return " ".join(text.casefold().split())


def work_type_matches(requested: Any, candidate: dict[str, Any] | None) -> bool:
    """Match Jira work types by semantic identity, including localized subtasks."""
    if not isinstance(candidate, dict):
        return False
    requested_key = _normalize_identity(requested)
    actual_key = _normalize_identity(candidate.get("name"))
    if requested_key in {"subtask", "sub-task", "sub tarea", "subtarea"}:
        return bool(candidate.get("subtask")) or actual_key in {
            "subtask",
            "sub-task",
            "sub tarea",
            "subtarea",
        }
    aliases = {
        "task": {"task", "tarea"},
        "story": {"story", "historia"},
        "bug": {"bug", "defecto", "incidencia"},
        "epic": {"epic"},
    }
    return actual_key in aliases.get(requested_key, {requested_key})


BUSINESS_FIELD_ALIASES = {
    "iniciativa": {"iniciativa", "initiative"},
    "linea_trabajo": {"linea de trabajo", "linea trabajo", "workstream"},
    "sprint": {"sprint"},
    "tipo_seguimiento": {"tipo de seguimiento", "tipo seguimiento"},
    "semaforo": {"semaforo", "traffic light"},
}


def _business_field_key(field: dict[str, Any]) -> str | None:
    normalized = _normalize_identity(field.get("name"))
    for key, aliases in BUSINESS_FIELD_ALIASES.items():
        if normalized in {_normalize_identity(alias) for alias in aliases}:
            return key
    return None


def _business_field_options(field: dict[str, Any]) -> list[dict[str, str]]:
    """Expose only compact business options, never raw Jira metadata or accounts."""

    if _business_field_key(field) is None:
        return []
    allowed_values = field.get("allowedValues")
    if not isinstance(allowed_values, list):
        return []
    options: list[dict[str, str]] = []
    seen: set[str] = set()
    for candidate in allowed_values:
        if isinstance(candidate, dict):
            label = (
                candidate.get("value")
                or candidate.get("name")
                or candidate.get("displayName")
                or candidate.get("label")
            )
            jira_id = candidate.get("id")
        else:
            label = candidate
            jira_id = None
        if label is None:
            continue
        label_text = str(label).strip()
        normalized = _normalize_identity(label_text)
        if not label_text or normalized in seen:
            continue
        seen.add(normalized)
        option = {"value": label_text, "label": label_text}
        if jira_id is not None:
            option["jira_id"] = str(jira_id)
        options.append(option)
    return options


@dataclass
class OAuthAttempt:
    username: str
    storage: InMemoryOAuthStorage | EncryptedFileOAuthStorage = field(
        default_factory=InMemoryOAuthStorage
    )
    authorization_url: str | None = None
    oauth_state: str | None = None
    redirect_ready: asyncio.Event = field(default_factory=asyncio.Event)
    callback_queue: asyncio.Queue[tuple[str, str | None]] = field(default_factory=asyncio.Queue)
    task: asyncio.Task[None] | None = None
    provider: OAuthClientProvider | None = None
    available_tools: dict[str, Any] = field(default_factory=dict)
    assignee_allowed_accounts: dict[str, set[str]] = field(default_factory=dict)
    assignee_lookup_cache: dict[str, tuple[datetime, list[dict[str, Any]]]] = field(default_factory=dict)
    snapshot: dict[str, Any] | None = None
    error: str | None = None
    connected: bool = False
    stage: str = "IDLE"
    sprint_cache: dict[str, tuple[datetime, list[dict[str, Any]]]] = field(default_factory=dict)
    diagnostic_failure: dict[str, Any] | None = None


class AtlassianIntegrationManager:
    """Per-user OAuth + read-only Rovo MCP integration for the local MVP."""

    def __init__(self, settings: Settings, write_lock: GlobalJiraWriteLock | None = None):
        self.settings = settings
        self.write_lock = write_lock
        self._attempts: dict[str, OAuthAttempt] = {}
        self._states: dict[str, OAuthAttempt] = {}
        self._restore_locks: dict[str, asyncio.Lock] = {}
        self._refresh_locks: dict[str, asyncio.Lock] = {}
        self.diagnostics = ConnectionDiagnostics(self)
        try:
            self._protector = WindowsDpapiProtector()
            self._oauth_storage_kind = "OS_ENCRYPTED"
        except RuntimeError:
            self._protector = None
            self._oauth_storage_kind = "MEMORY_ONLY"

    def new_atlassian_http_client(self, **kwargs: Any) -> httpx.AsyncClient:
        """Create an Atlassian-only HTTP client, honoring an explicit corporate proxy."""

        if self.settings.atlassian_proxy_url:
            kwargs["proxy"] = self.settings.atlassian_proxy_url
        return httpx.AsyncClient(**kwargs)

    def status(self, username: str) -> dict[str, Any]:
        attempt = self._attempts.get(username)
        base = {
            "connected": False,
            "phase": "DISCONNECTED",
            "mcp_endpoint": self.settings.atlassian_mcp_url,
            "target_site": self.settings.atlassian_site_url,
            "target_spaces": list(TARGET_SPACES),
            "oauth_storage": self._oauth_storage_kind,
            "jira_write_enabled": False,
            "write_tools_blocked": True,
            "error": None,
            "snapshot": None,
            "stage": "IDLE",
            "diagnostic": self.diagnostics.status(username),
        }
        if attempt is None:
            return base
        if attempt.error:
            base.update({"phase": "ERROR", "error": attempt.error})
        elif attempt.connected:
            base.update({"connected": True, "phase": "CONNECTED"})
        elif attempt.authorization_url:
            base["phase"] = "AWAITING_USER_CONSENT"
        else:
            base["phase"] = "CONNECTING"
        base["snapshot"] = attempt.snapshot
        base["stage"] = attempt.stage
        if base['diagnostic']['state'] not in ('JIRA_READY',):
            base['connected'] = False
        return base

    def objective_4_tool_readiness(self, username: str) -> dict[str, Any]:
        """Inspect advertised tool schemas without invoking any MCP tool."""

        attempt = self._attempts.get(username)
        available = attempt.available_tools if attempt and attempt.connected else {}

        def describe(name: str) -> dict[str, Any]:
            tool = available.get(name)
            schema = None
            if tool is not None:
                schema = getattr(tool, "inputSchema", None)
                if schema is None:
                    schema = getattr(tool, "input_schema", None)
                if hasattr(schema, "model_dump"):
                    schema = schema.model_dump(mode="json")
            normalized_schema = schema if isinstance(schema, dict) else None
            schema_hash = None
            if normalized_schema is not None:
                encoded = json.dumps(
                    normalized_schema,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
                schema_hash = hashlib.sha256(encoded).hexdigest()
            return {
                "name": name,
                "exposed": tool is not None,
                "input_schema": normalized_schema,
                "schema_sha256": schema_hash,
                "required_inputs": (
                    normalized_schema.get("required", []) if normalized_schema else []
                ),
            }

        return {
            "connected": bool(attempt and attempt.connected),
            "inspection_only": True,
            "tools_invoked": 0,
            "create": describe("createJiraIssue"),
            "readback": describe("getJiraIssue"),
        }

    async def begin_connect(self, username: str) -> dict[str, str]:
        await self.disconnect(username)
        attempt = OAuthAttempt(username=username, storage=self._storage(username))
        self._attempts[username] = attempt
        attempt.task = asyncio.create_task(self._authorize_and_discover(attempt))
        try:
            await asyncio.wait_for(attempt.redirect_ready.wait(), timeout=30)
        except TimeoutError as exc:
            if attempt.task.done():
                await self._surface_task_failure(attempt)
            attempt.task.cancel()
            attempt.diagnostic_failure = failure_report(ConnectionFailure('MCP_TIMEOUT'), attempt.stage)
            raise AtlassianIntegrationError(
                "Atlassian no entregó la URL de autorización dentro del tiempo esperado."
            ) from exc
        if attempt.error:
            raise AtlassianIntegrationError(attempt.error)
        if not attempt.authorization_url:
            raise AtlassianIntegrationError("No se recibió la URL de autorización de Atlassian.")
        return {"authorization_url": attempt.authorization_url, "phase": "AWAITING_USER_CONSENT"}

    async def finish_callback(self, code: str, state: str) -> dict[str, Any]:
        attempt = self._states.pop(state, None)
        if attempt is None:
            raise AtlassianIntegrationError("OAUTH_STATE_INVALID")
        if not code:
            attempt.diagnostic_failure = failure_report(ConnectionFailure('OAUTH_CALLBACK_INVALID'), 'OAUTH_CALLBACK')
            raise AtlassianIntegrationError('OAUTH_CALLBACK_INVALID')
        await attempt.callback_queue.put((code, state))
        if attempt.task is None:
            raise AtlassianIntegrationError("La autorización OAuth no tiene una tarea activa.")
        try:
            await asyncio.wait_for(asyncio.shield(attempt.task), timeout=90)
        except TimeoutError as exc:
            attempt.diagnostic_failure = failure_report(ConnectionFailure('MCP_TIMEOUT'), attempt.stage)
            attempt.task.cancel()
            raise AtlassianIntegrationError(
                "Atlassian autorizó el acceso, pero la consulta MCP no terminó a tiempo."
            ) from exc
        await self._surface_task_failure(attempt)
        self._states.pop(state, None)
        return self.status(attempt.username)

    async def deny_callback(self, state: str | None) -> None:
        if not state:
            return
        attempt = self._states.pop(state, None)
        if attempt is not None:
            if attempt.task and not attempt.task.done():
                attempt.task.cancel()
                try:
                    await attempt.task
                except asyncio.CancelledError:
                    pass
            attempt.diagnostic_failure = failure_report(ConnectionFailure('OAUTH_CANCELLED'), 'OAUTH_CALLBACK')
            attempt.error = 'La autorización de Atlassian fue cancelada.'

    async def disconnect(self, username: str) -> None:
        self.diagnostics.results.pop(username, None)
        attempt = self._attempts.pop(username, None)
        if attempt is not None:
            if attempt.oauth_state:
                self._states.pop(attempt.oauth_state, None)
            if attempt.task and not attempt.task.done():
                attempt.task.cancel()
                try:
                    await attempt.task
                except (asyncio.CancelledError, Exception):
                    pass
            try:
                attempt.storage.clear()
            except RuntimeError:
                # A DPAPI blob can become unreadable after a Windows/session change.
                # An explicit reconnect must still be able to discard that stale
                # credential before starting a fresh OAuth flow.
                pass
        try:
            self._storage(username).clear()
        except RuntimeError:
            # The persisted file itself cannot be decrypted, so clear only that
            # user's unreadable OAuth blob as part of the explicit reconnect.
            directory = (
                self.settings.atlassian_oauth_storage_dir
                or self.settings.database_path.parent / "atlassian_oauth"
            )
            EncryptedFileOAuthStorage.clear_persisted(directory, username)

    async def rebind_user(self, source_username: str, destination_username: str) -> None:
        """Attach a completed OAuth attempt to its authorized local user."""

        if not source_username or not destination_username or source_username == destination_username:
            return
        attempt = self._attempts.pop(source_username, None)
        if attempt is not None:
            if attempt.oauth_state:
                self._states[attempt.oauth_state] = attempt
            attempt.username = destination_username
            self._attempts[destination_username] = attempt
        directory = (
            self.settings.atlassian_oauth_storage_dir
            or self.settings.database_path.parent / "atlassian_oauth"
        )
        if self._protector is not None:
            EncryptedFileOAuthStorage.move_persisted(directory, source_username, destination_username)
        if source_username in self._restore_locks:
            self._restore_locks[destination_username] = self._restore_locks.pop(source_username)
        if source_username in self._refresh_locks:
            self._refresh_locks[destination_username] = self._refresh_locks.pop(source_username)

    def credential_metadata(self, username: str) -> dict[str, Any]:
        attempt = self._attempts.get(username)
        token = attempt.storage.tokens if attempt else None
        snapshot = attempt.snapshot if attempt else None
        scopes = getattr(token, "scope", None) if token else None
        return {
            "expires_at": str(getattr(token, "expires_at", None) or "") or None,
            "scopes": " ".join(scopes) if isinstance(scopes, (list, tuple, set)) else str(scopes or "") or None,
            "cloud_id": (snapshot or {}).get("cloud_id"),
            "site_url": (snapshot or {}).get("site_url"),
        }

    def has_persisted_credentials(self, username: str) -> bool:
        """Check only for a user's encrypted credential file, never its contents."""

        if self._protector is None:
            return False
        directory = (
            self.settings.atlassian_oauth_storage_dir
            or self.settings.database_path.parent / "atlassian_oauth"
        )
        return EncryptedFileOAuthStorage.path_for(directory, username).is_file()

    async def ensure_restored(self, username: str) -> dict[str, Any]:
        """Recover a previously authorized session without asking for consent again."""

        if username in self._attempts:
            return self.status(username)
        lock = self._restore_locks.setdefault(username, asyncio.Lock())
        async with lock:
            if username in self._attempts:
                return self.status(username)
            try:
                storage = self._storage(username)
            except RuntimeError as exc:
                attempt = OAuthAttempt(username=username)
                attempt.error = 'La autorización Atlassian guardada no se puede recuperar.'
                attempt.diagnostic_failure = failure_report(exc, 'RESTORE_SAVED_OAUTH')
                self._attempts[username] = attempt
                return self.status(username)
            if not storage.has_credentials:
                return self.status(username)
            attempt = OAuthAttempt(username=username, storage=storage)
            self._attempts[username] = attempt

            async def unexpected_redirect(_url: str) -> None:
                raise AtlassianIntegrationError(
                    "La autorización Atlassian guardada venció. Vuelve a conectar la cuenta."
                )

            async def unexpected_callback() -> tuple[str, str | None]:
                raise AtlassianIntegrationError(
                    "La autorización Atlassian guardada requiere consentimiento de nuevo."
                )

            attempt.provider = self._provider(
                attempt,
                redirect_handler=unexpected_redirect,
                callback_handler=unexpected_callback,
            )
            attempt.stage = "RESTORE_SAVED_OAUTH"
            try:
                attempt.snapshot = await asyncio.wait_for(self._discover(attempt), 90)
                attempt.connected = True
                attempt.stage = "COMPLETE"
            except Exception as exc:
                attempt.diagnostic_failure = failure_report(exc, attempt.stage)
                attempt.error = attempt.diagnostic_failure['message']
            return self.status(username)

    async def refresh(self, username: str) -> dict[str, Any]:
        lock = self._refresh_locks.setdefault(username, asyncio.Lock())
        async with lock:
            await self.ensure_restored(username)
            attempt = self._attempts.get(username)
            if (
                attempt is None
                or attempt.provider is None
                or attempt.storage.tokens is None
            ):
                raise AtlassianIntegrationError("Primero conecta tu cuenta Atlassian.")
            attempt.error = None
            attempt.diagnostic_failure = None
            self.diagnostics.results.pop(username, None)
            attempt.connected = False
            try:
                attempt.snapshot = await asyncio.wait_for(self._discover(attempt), 90)
                attempt.connected = True
                attempt.stage = "COMPLETE"
            except Exception as exc:
                attempt.diagnostic_failure = failure_report(exc, attempt.stage)
                attempt.error = attempt.diagnostic_failure['message']
                raise AtlassianIntegrationError(attempt.error) from exc
            return self.status(username)

    async def find_assignees(
        self,
        username: str,
        space: str,
        query: str,
    ) -> list[dict[str, Any]]:
        await self.ensure_restored(username)
        if space not in TARGET_SPACES:
            raise AtlassianIntegrationError("Space no permitido para el piloto.")
        if len(query.strip()) < 2:
            raise AtlassianIntegrationError("Escribe al menos dos caracteres para buscar.")
        attempt = self._connected_attempt(username)
        cache_key = f"{space}:{_normalize_identity(query)}"
        cached = attempt.assignee_lookup_cache.get(cache_key)
        now = datetime.now(UTC)
        if cached and now - cached[0] < timedelta(seconds=ASSIGNEE_LOOKUP_CACHE_TTL_SECONDS):
            return copy.deepcopy(cached[1])
        tool_name = next(
            (
                name
                for name in ("findAssignableUsers", "lookupJiraAccountId")
                if name in attempt.available_tools
            ),
            None,
        )
        if tool_name is None:
            raise AtlassianIntegrationError(
                "El servidor MCP no expuso una herramienta de consulta de responsables."
            )
        project = next(
            (
                item
                for item in (attempt.snapshot or {}).get("spaces", [])
                if item.get("key") == space
            ),
            None,
        )
        values = {
            "cloudId": (attempt.snapshot or {}).get("cloud_id"),
            "projectKey": (project or {}).get("id") or space,
            "query": query.strip(),
            "maxResults": 20,
        }
        payload = await self._invoke(attempt, tool_name, values)
        users = []
        for item in _records(payload, ("users", "accounts")):
            users.append(
                {
                    "account_id": item.get("accountId") or item.get("account_id") or item.get("id"),
                    "display_name": item.get("displayName") or item.get("display_name") or item.get("name"),
                    "email": item.get("emailAddress") or item.get("email"),
                    "active": item.get("active", True),
                    "capability": tool_name,
                }
            )
        unique: dict[str, dict[str, Any]] = {}
        for user in users:
            if not user["account_id"] and not user["display_name"]:
                continue
            identity = str(user["account_id"] or _normalize_identity(user["display_name"]))
            unique.setdefault(identity, user)
        active_users = [user for user in unique.values() if user.get("active", True)]
        normalized_query = _normalize_identity(query)
        exact = [
            user
            for user in active_users
            if _normalize_identity(user.get("display_name")) == normalized_query
            or _normalize_identity(user.get("email")) == normalized_query
        ]
        result = exact or active_users
        attempt.assignee_lookup_cache[cache_key] = (now, copy.deepcopy(result))
        return result

    async def list_sprints(
        self,
        username: str,
        space: str,
        *,
        force_refresh: bool = False,
    ) -> list[dict[str, Any]]:
        """Discover active/future Sprints through Rovo JQL without exposing IDs to users."""

        await self.ensure_restored(username)
        if space not in TARGET_SPACES:
            raise AtlassianIntegrationError("Space no permitido para el piloto.")
        attempt = self._connected_attempt(username)
        cached = attempt.sprint_cache.get(space)
        now = datetime.now(UTC)
        if cached and not force_refresh and now - cached[0] < timedelta(minutes=5):
            return copy.deepcopy(cached[1])
        if "searchJiraIssuesUsingJql" not in attempt.available_tools:
            raise AtlassianIntegrationError(
                "Rovo MCP no expuso la busqueda JQL necesaria para recuperar Sprints."
            )
        snapshot = attempt.snapshot or {}
        project = next(
            (item for item in snapshot.get("spaces", []) if item.get("key") == space),
            None,
        )
        sprint_field_ids = {
            str(field.get("id"))
            for work_type in (project or {}).get("work_types", [])
            for field in work_type.get("fields", [])
            if field.get("business_key") == "sprint" and field.get("id")
        }
        if not sprint_field_ids:
            raise AtlassianIntegrationError(
                f"Jira no publico el campo Sprint para los Work Types visibles de {space}."
            )
        values: list[dict[str, Any]] = []
        for state, function in (("active", "openSprints()"), ("future", "futureSprints()")):
            next_page_token = None
            for page_number in range(20):
                arguments = {
                    "cloudId": snapshot.get("cloud_id"),
                    "jql": f'project = "{space}" AND sprint in {function} ORDER BY updated DESC',
                    "fields": sorted(sprint_field_ids),
                    "maxResults": 50,
                }
                if next_page_token:
                    arguments["nextPageToken"] = next_page_token
                payload = await self._invoke(
                    attempt,
                    "searchJiraIssuesUsingJql",
                    arguments,
                )
                values.extend(_extract_sprints(payload, sprint_field_ids, state))
                next_page_token = _next_page_token(payload)
                if not next_page_token:
                    break
            else:
                raise AtlassianIntegrationError(
                    f"El catalogo de Sprints de {space} excedio el limite seguro de paginacion; no se elegira un Sprint automaticamente."
                )
        from .sprints import normalize_sprint_catalog

        catalog = normalize_sprint_catalog(values)
        attempt.sprint_cache[space] = (now, catalog)
        return copy.deepcopy(catalog)

    async def validate_priority(
        self,
        username: str,
        space: str,
        priority: str,
    ) -> dict[str, str]:
        """Validate a priority name through read-only JQL before it enters a create payload."""

        await self.ensure_restored(username)
        if space not in TARGET_SPACES:
            raise AtlassianIntegrationError("Space no permitido para el piloto.")
        if priority not in {"Highest", "High", "Medium", "Low", "Lowest"}:
            raise AtlassianIntegrationError("Prioridad no permitida por el modelo de voz.")
        attempt = self._connected_attempt(username)
        if "searchJiraIssuesUsingJql" not in attempt.available_tools:
            raise AtlassianIntegrationError(
                "Rovo MCP no expuso la búsqueda JQL necesaria para validar Prioridad."
            )
        await self._invoke(
            attempt,
            "searchJiraIssuesUsingJql",
            {
                "cloudId": (attempt.snapshot or {}).get("cloud_id"),
                "jql": f'project = "{space}" AND priority = "{priority}" ORDER BY updated DESC',
                "fields": ["priority"],
                "maxResults": 1,
            },
        )
        return {"name": priority}

    async def create_single_task_and_readback(
        self,
        username: str,
        create_arguments: dict[str, Any],
        readback_fields: list[str],
        timeout_seconds: int,
    ) -> dict[str, Any]:
        """Invoke exactly one allowed create call followed by one read-only verification."""

        await self.ensure_restored(username)
        attempt = self._connected_attempt(username)
        if attempt.provider is None:
            raise ControlledJiraWriteError(
                "No existe un proveedor OAuth activo.",
                outcome_uncertain=False,
                real_mcp_calls=0,
            )
        create_started = False
        call_count = 0

        async def operation() -> dict[str, Any]:
            nonlocal create_started, call_count
            async with self.new_atlassian_http_client(
                auth=attempt.provider,
                follow_redirects=True,
                timeout=timeout_seconds,
            ) as client:
                async with streamable_http_client(
                    self.settings.atlassian_mcp_url,
                    http_client=client,
                ) as (read_stream, write_stream, _):
                    async with ClientSession(read_stream, write_stream) as session:
                        await session.initialize()
                        tools_result = await session.list_tools()
                        tools = {tool.name: tool for tool in tools_result.tools}
                        create_tool = tools.get("createJiraIssue")
                        read_tool = tools.get("getJiraIssue")
                        if create_tool is None or read_tool is None:
                            raise ControlledJiraWriteError(
                                "Rovo no expuso createJiraIssue y getJiraIssue en esta sesion.",
                                outcome_uncertain=False,
                                real_mcp_calls=0,
                            )
                        schema = getattr(create_tool, "inputSchema", None) or {}
                        properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
                        unexpected = sorted(set(create_arguments) - set(properties))
                        if unexpected:
                            raise ControlledJiraWriteError(
                                "El payload contiene parametros fuera del contrato: " + ", ".join(unexpected),
                                outcome_uncertain=False,
                                real_mcp_calls=0,
                            )
                        try:
                            # Final backend-authoritative check. Functional policy,
                            # preflight and confirmation remain separate gates.
                            if self.write_lock is not None:
                                self.write_lock.assert_can_write(username, "createJiraIssue")
                            # Mark the transport as started only after the lock
                            # succeeds; a rejected lock is not an uncertain Jira
                            # outcome because no MCP write was attempted.
                            create_started = True
                            call_count = 1
                            create_started_at = perf_counter()
                            create_result = await session.call_tool(
                                "createJiraIssue",
                                copy.deepcopy(create_arguments),
                            )
                        except Exception as exc:
                            if _is_explicit_jira_create_rejection(exc):
                                raise ControlledJiraWriteError(
                                    "Jira rechazo la creacion: "
                                    + self._redact_sensitive(str(exc)),
                                    outcome_uncertain=False,
                                    real_mcp_calls=1,
                                ) from exc
                            raise
                        create_elapsed_ms = round((perf_counter() - create_started_at) * 1000, 1)
                        create_payload = _tool_payload(create_result)
                        if getattr(create_result, "isError", False):
                            raise ControlledJiraWriteError(
                                "Jira rechazo la creacion: " + self._redact_sensitive(str(create_payload)),
                                outcome_uncertain=False,
                                real_mcp_calls=1,
                            )
                        issue_key = _extract_issue_key(create_payload)
                        if not issue_key:
                            raise ControlledJiraWriteError(
                                "Rovo respondio a la creacion sin una clave Jira verificable.",
                                outcome_uncertain=True,
                                real_mcp_calls=1,
                            )
                        call_count = 2
                        readback_started_at = perf_counter()
                        try:
                            read_result = await call_read_only_tool(
                                session,
                                "getJiraIssue",
                                _schema_arguments(
                                    read_tool,
                                    {
                                        "cloudId": create_arguments["cloudId"],
                                        "issueIdOrKey": issue_key,
                                        "fields": readback_fields,
                                        "fieldsByKeys": True,
                                        "responseContentFormat": "adf",
                                    },
                                ),
                            )
                            read_payload = _tool_payload(read_result)
                            if getattr(read_result, "isError", False):
                                return {
                                    "issue_key": issue_key,
                                    "create_response": create_payload,
                                    "readback": None,
                                    "readback_error": self._redact_sensitive(str(read_payload)),
                                    "real_mcp_calls": 2,
                                    "create_elapsed_ms": create_elapsed_ms,
                                    "readback_elapsed_ms": round((perf_counter() - readback_started_at) * 1000, 1),
                                }
                        except Exception as exc:
                            return {
                                "issue_key": issue_key,
                                "create_response": create_payload,
                                "readback": None,
                                "readback_error": self._safe_error(exc, "READBACK_CREATED_TASK"),
                                "real_mcp_calls": 2,
                                "create_elapsed_ms": create_elapsed_ms,
                                "readback_elapsed_ms": round((perf_counter() - readback_started_at) * 1000, 1),
                            }
                        return {
                            "issue_key": issue_key,
                            "create_response": create_payload,
                            "readback": read_payload,
                            "readback_error": None,
                            "real_mcp_calls": 2,
                            "create_elapsed_ms": create_elapsed_ms,
                            "readback_elapsed_ms": round((perf_counter() - readback_started_at) * 1000, 1),
                        }

        try:
            return await asyncio.wait_for(operation(), timeout=timeout_seconds)
        except GlobalJiraWriteLockError:
            raise
        except ControlledJiraWriteError:
            raise
        except TimeoutError as exc:
            raise ControlledJiraWriteError(
                "La operacion excedio el tiempo limite. No se permite reintentar automaticamente.",
                outcome_uncertain=create_started,
                real_mcp_calls=call_count,
            ) from exc
        except Exception as exc:
            raise ControlledJiraWriteError(
                self._safe_error(exc, "CONTROLLED_CREATE_TASK"),
                outcome_uncertain=create_started,
                real_mcp_calls=call_count,
            ) from exc

    def connected_snapshot(self, username: str) -> dict[str, Any]:
        """Return a defensive copy without exposing OAuth material."""

        attempt = self._connected_attempt(username)
        if attempt.snapshot is None:
            raise AtlassianIntegrationError("El diagnóstico Jira todavía no está disponible.")
        snapshot = copy.deepcopy(attempt.snapshot)
        snapshot["_assignee_allowed_accounts"] = {
            key: sorted(values)
            for key, values in attempt.assignee_allowed_accounts.items()
        }
        return snapshot

    def jira_field_catalog(
        self,
        username: str,
        space: str,
        work_type: str,
        field_id: str,
    ) -> dict[str, Any]:
        """Return the verified option catalog from the existing Jira snapshot."""
        snapshot = self.connected_snapshot(username)
        for project in snapshot.get("spaces", []):
            if str(project.get("key")) != space:
                continue
            for issue_type in project.get("work_types", []):
                if not work_type_matches(work_type, issue_type):
                    continue
                for field in issue_type.get("fields", []):
                    if str(field.get("id")) == field_id:
                        return {
                            "space": space,
                            "work_type": work_type,
                            "field_id": field_id,
                            "field_name": field.get("name"),
                            "options": list(field.get("options") or []),
                            "fetched_at": snapshot.get("verified_at"),
                            "status": "verified",
                        }
        raise AtlassianIntegrationError(
            f"No se encontró el campo {field_id} para {space} / {work_type} en el catálogo Jira."
        )

    async def _authorize_and_discover(self, attempt: OAuthAttempt) -> None:
        async def redirect_handler(url: str) -> None:
            attempt.authorization_url = url
            states = parse_qs(urlparse(url).query).get("state", [])
            if not states:
                attempt.error = "La URL OAuth de Atlassian no incluyó el parámetro state."
            else:
                attempt.oauth_state = states[0]
                self._states[states[0]] = attempt
            attempt.redirect_ready.set()

        async def callback_handler() -> tuple[str, str | None]:
            attempt.stage = 'OAUTH_CALLBACK'
            try:
                return await asyncio.wait_for(attempt.callback_queue.get(), OAUTH_CONSENT_TIMEOUT_SECONDS)
            except TimeoutError as exc:
                raise ConnectionFailure('OAUTH_TIMEOUT') from exc

        provider = self._provider(
            attempt,
            redirect_handler=redirect_handler,
            callback_handler=callback_handler,
        )
        attempt.provider = provider
        attempt.stage = "OAUTH_AND_MCP_CONNECT"
        try:
            async with self.new_atlassian_http_client(auth=provider, follow_redirects=True, timeout=60) as client:
                async with streamable_http_client(
                    self.settings.atlassian_mcp_url,
                    http_client=client,
                ) as (read_stream, write_stream, _):
                    async with ClientSession(read_stream, write_stream) as session:
                        attempt.stage = "MCP_INITIALIZE"
                        await session.initialize()
                        attempt.stage = "MCP_LIST_TOOLS"
                        tools_result = await session.list_tools()
                        attempt.available_tools = {tool.name: tool for tool in tools_result.tools}
                        attempt.snapshot = await self._discover_with_session(attempt, session)
                        attempt.connected = True
                        attempt.stage = "COMPLETE"
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover - real network errors vary
            attempt.diagnostic_failure = failure_report(exc, attempt.stage)
            logger.warning('Atlassian connection failed phase=%s category=%s request_id=%s', attempt.stage, attempt.diagnostic_failure['error_code'], attempt.diagnostic_failure['request_id'])
            attempt.error = attempt.diagnostic_failure['message']
            attempt.redirect_ready.set()
        finally:
            if attempt.oauth_state:
                self._states.pop(attempt.oauth_state, None)

    def diagnostic_attempt(self, username: str) -> OAuthAttempt:
        """Read encrypted credentials without clearing or initiating consent."""
        try:
            storage = self._storage(username)
        except RuntimeError as exc:
            raise ConnectionFailure('OAUTH_INVALID') from exc
        return OAuthAttempt(username=username, storage=storage)

    async def diagnostic_read(self, attempt: OAuthAttempt, result: dict) -> None:
        permission_denied = False

        async def observe_response(response):
            nonlocal permission_denied
            if response.status_code == 403:
                permission_denied = True

        async def no_redirect(_url):
            raise ConnectionFailure('JIRA_PERMISSION_DENIED' if permission_denied else 'OAUTH_EXPIRED')

        async def no_callback():
            raise ConnectionFailure('OAUTH_EXPIRED')

        provider = self._provider(attempt, redirect_handler=no_redirect, callback_handler=no_callback)
        result['phase'] = 'MCP_INITIALIZE'
        async with self.new_atlassian_http_client(auth=provider, follow_redirects=True, timeout=httpx.Timeout(10, connect=5), event_hooks={'response': [observe_response]}) as client:
            async with streamable_http_client(self.settings.atlassian_mcp_url, http_client=client) as (reader, writer, _):
                async with ClientSession(reader, writer) as session:
                    await session.initialize()
                    result['checks'].update(network='OK', mcp='OK', oauth='OK')
                    result['phase'] = 'MCP_LIST_TOOLS'
                    available = {t.name: t for t in (await session.list_tools()).tools}
                    required = {'atlassianUserInfo', 'getAccessibleAtlassianResources', 'getVisibleJiraProjects'}
                    result['capabilities'] = sorted(set(available) & READ_ONLY_TOOL_ALLOWLIST)
                    if required - set(available):
                        raise ConnectionFailure('MCP_CAPABILITIES_MISSING')
                    result['checks']['capabilities'] = 'OK'

                    async def read(name, values=None):
                        result['tools_invoked'].append(name)
                        response = await call_read_only_tool(session, name, _schema_arguments(available[name], values or {}))
                        if getattr(response, 'isError', False):
                            payload = str(_tool_payload(response)).casefold()
                            if '403' in payload or 'forbidden' in payload or 'permission' in payload:
                                raise ConnectionFailure('JIRA_PERMISSION_DENIED')
                            if '401' in payload or 'unauthorized' in payload:
                                raise ConnectionFailure('OAUTH_INVALID')
                            raise ConnectionFailure('JIRA_SITE_UNAVAILABLE')
                        return _tool_payload(response)

                    result['phase'] = 'READ_USER'
                    account = await read('atlassianUserInfo')
                    if not isinstance(account, dict) or not (account.get('accountId') or account.get('account_id') or account.get('id')):
                        raise ConnectionFailure('ATLASSIAN_ACCOUNT_UNAVAILABLE')
                    result['account'] = account.get('displayName') or account.get('name')
                    result['checks']['account'] = 'OK'
                    result['phase'] = 'READ_ACCESSIBLE_RESOURCES'
                    resources = _records(await read('getAccessibleAtlassianResources'), ('resources', 'sites'))
                    resource = next((r for r in resources if urlparse(str(r.get('url', ''))).hostname == urlparse(self.settings.atlassian_site_url).hostname), None)
                    if not resource:
                        raise ConnectionFailure('JIRA_SITE_UNAVAILABLE')
                    cloud = resource.get('id') or resource.get('cloudId') or resource.get('cloud_id')
                    if not cloud:
                        raise ConnectionFailure('JIRA_SITE_UNAVAILABLE')
                    result['checks']['site'] = 'OK'
                    result['phase'] = 'READ_VISIBLE_PROJECTS'
                    # Bounded pagination avoids declaring AT absent from a partial first page.
                    for offset in range(0, 1000, 50):
                        payload = await read('getVisibleJiraProjects', {'cloudId': cloud, 'maxResults': 50, 'startAt': offset})
                        projects = _records(payload, ('projects',))
                        if any(str(p.get('key', '')).upper() == 'AT' for p in projects):
                            result['checks']['space'] = 'OK'
                            attempt.provider = provider
                            return
                        if len(projects) < 50 or (isinstance(payload, dict) and payload.get('isLast') is True):
                            raise ConnectionFailure('SPACE_UNAVAILABLE')
                        if not _schema_arguments(available['getVisibleJiraProjects'], {'startAt': offset}):
                            raise ConnectionFailure('MCP_CAPABILITIES_MISSING')
                    raise ConnectionFailure('MCP_CAPABILITIES_MISSING')

    def _provider(
        self,
        attempt: OAuthAttempt,
        *,
        redirect_handler,
        callback_handler,
    ) -> OAuthClientProvider:
        metadata = OAuthClientMetadata(
            redirect_uris=[self.settings.atlassian_oauth_callback_url],
            token_endpoint_auth_method="none",
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            client_name="Agente Jira - Objetivo 3B.2",
            software_id="agente-jira",
            software_version="0.11.0",
        )
        return OAuthClientProvider(
            self.settings.atlassian_mcp_url,
            client_metadata=metadata,
            storage=attempt.storage,
            redirect_handler=redirect_handler,
            callback_handler=callback_handler,
            timeout=300,
        )

    def _storage(self, username: str) -> InMemoryOAuthStorage | EncryptedFileOAuthStorage:
        if self._protector is None:
            return InMemoryOAuthStorage()
        directory = (
            self.settings.atlassian_oauth_storage_dir
            or self.settings.database_path.parent / "atlassian_oauth"
        )
        return EncryptedFileOAuthStorage(directory, username, self._protector)

    async def _discover(self, attempt: OAuthAttempt) -> dict[str, Any]:
        if attempt.provider is None:
            raise AtlassianIntegrationError("No existe un proveedor OAuth activo.")
        async with self.new_atlassian_http_client(auth=attempt.provider, follow_redirects=True, timeout=60) as client:
            async with streamable_http_client(
                self.settings.atlassian_mcp_url,
                http_client=client,
            ) as (read_stream, write_stream, _):
                async with ClientSession(read_stream, write_stream) as session:
                    attempt.stage = "MCP_INITIALIZE"
                    await session.initialize()
                    attempt.stage = "MCP_LIST_TOOLS"
                    tools_result = await session.list_tools()
                    attempt.available_tools = {tool.name: tool for tool in tools_result.tools}
                    return await self._discover_with_session(attempt, session)

    async def _read_all_issue_type_fields(
        self,
        attempt: OAuthAttempt,
        session: McpSessionLike,
        *,
        cloud_id: str,
        project_id_or_key: str,
        issue_type_id: str,
    ) -> list[dict[str, Any]]:
        """Read required and optional create fields across every metadata page."""

        fields_by_id: dict[str, dict[str, Any]] = {}
        start_at = 0
        previous_page_ids: tuple[str, ...] | None = None
        for _page_number in range(FIELD_METADATA_MAX_PAGES):
            field_payload = await self._invoke_with_session(
                attempt,
                session,
                "getJiraIssueTypeMetaWithFields",
                {
                    "cloudId": cloud_id,
                    "projectKey": project_id_or_key,
                    "issueTypeId": issue_type_id,
                    "startAt": start_at,
                    "maxResults": FIELD_METADATA_MAX_RESULTS,
                    # Atlassian defaults this flag to true. Business fields such as
                    # Sprint and tracking type are optional and would be omitted.
                    "requiredFieldsOnly": False,
                },
            )
            page_fields = _field_records(field_payload)
            page_ids = tuple(
                str(field.get("fieldId") or field.get("key") or field.get("id") or "")
                for field in page_fields
            )
            if previous_page_ids is not None and page_ids == previous_page_ids:
                break
            previous_page_ids = page_ids
            for field in page_fields:
                field_id = str(
                    field.get("fieldId") or field.get("key") or field.get("id") or ""
                ).strip()
                identity = field_id or _normalize_identity(field.get("name"))
                if identity:
                    fields_by_id.setdefault(identity, field)

            if not page_fields:
                break
            if not isinstance(field_payload, dict):
                break
            if field_payload.get("isLast") is True:
                break
            total = field_payload.get("total")
            if isinstance(total, (int, float)) and start_at + len(page_fields) >= int(total):
                break
            if (
                "total" not in field_payload
                and "isLast" not in field_payload
                and len(page_fields) < FIELD_METADATA_MAX_RESULTS
            ):
                break
            start_at += len(page_fields)
        else:
            raise AtlassianIntegrationError(
                "Los metadatos de campos Jira excedieron el límite seguro de paginación."
            )
        return list(fields_by_id.values())

    async def _discover_with_session(
        self,
        attempt: OAuthAttempt,
        session: McpSessionLike,
    ) -> dict[str, Any]:
        required = {"atlassianUserInfo", "getAccessibleAtlassianResources", "getVisibleJiraProjects"}
        missing = sorted(required - set(attempt.available_tools))
        if missing:
            raise AtlassianIntegrationError(
                "El servidor MCP no expuso las herramientas mínimas: " + ", ".join(missing)
            )

        attempt.stage = "READ_USER"
        user_payload = await self._invoke_with_session(attempt, session, 'atlassianUserInfo', {})
        if not isinstance(user_payload, dict) or not (user_payload.get('accountId') or user_payload.get('account_id') or user_payload.get('id')):
            raise ConnectionFailure('ATLASSIAN_ACCOUNT_UNAVAILABLE')
        attempt.stage = "READ_ACCESSIBLE_RESOURCES"
        resources_payload = await self._invoke_with_session(attempt, session, 'getAccessibleAtlassianResources', {})
        resources = _records(resources_payload, ("resources", "sites"))
        expected_host = urlparse(self.settings.atlassian_site_url).hostname
        resource = next(
            (
                item
                for item in resources
                if urlparse(str(item.get("url") or "")).hostname == expected_host
            ),
            None,
        )
        if resource is None:
            visible = ", ".join(str(item.get("url")) for item in resources if item.get("url"))
            raise AtlassianIntegrationError(
                f"La cuenta autorizada no tiene visible {self.settings.atlassian_site_url}. "
                f"Sitios devueltos: {visible or 'ninguno'}."
            )
        cloud_id = resource.get("id") or resource.get("cloudId") or resource.get("cloud_id")
        if not cloud_id:
            raise AtlassianIntegrationError("Atlassian no devolvió el cloudId del sitio objetivo.")

        attempt.stage = "READ_VISIBLE_PROJECTS"
        projects_payload = await self._invoke_with_session(
            attempt,
            session,
            "getVisibleJiraProjects",
            {"cloudId": cloud_id, "maxResults": VISIBLE_PROJECTS_MAX_RESULTS},
        )
        projects = _records(projects_payload, ("projects",))
        normalized_projects: list[dict[str, Any]] = []
        for key in TARGET_SPACES:
            raw = next((item for item in projects if str(item.get("key", "")).upper() == key), None)
            normalized_projects.append(
                {
                    "key": key,
                    "found": raw is not None,
                    "id": (raw or {}).get("id") or (raw or {}).get("projectId"),
                    "name": (raw or {}).get("name"),
                    "project_type": (raw or {}).get("projectTypeKey")
                    or (raw or {}).get("projectType"),
                    "work_types": [],
                }
            )

        for project in normalized_projects:
            if not project["found"] or "getJiraProjectIssueTypesMetadata" not in attempt.available_tools:
                continue
            attempt.stage = f"READ_WORK_TYPES_{project['key']}"
            issue_payload = await self._invoke_with_session(
                attempt,
                session,
                "getJiraProjectIssueTypesMetadata",
                {"cloudId": cloud_id, "projectKey": project["id"] or project["key"]},
            )
            issue_types = _records(issue_payload, ("issueTypes",))
            for raw_issue in issue_types:
                issue = {
                    "id": raw_issue.get("id") or raw_issue.get("issueTypeId"),
                    "name": raw_issue.get("name"),
                    "subtask": raw_issue.get("subtask", False),
                    "fields": [],
                }
                if (
                    issue["id"]
                    and "getJiraIssueTypeMetaWithFields" in attempt.available_tools
                    and (
                        bool(issue.get("subtask"))
                        or _normalize_identity(issue["name"])
                        in {"epic", "story", "task", "bug", "subtask", "sub-task", "subtarea"}
                    )
                ):
                    attempt.stage = f"READ_FIELDS_{project['key']}_{issue['name']}"
                    fields = await self._read_all_issue_type_fields(
                        attempt,
                        session,
                        cloud_id=str(cloud_id),
                        project_id_or_key=str(project["id"] or project["key"]),
                        issue_type_id=str(issue["id"]),
                    )
                    assignee_field = next(
                        (
                            field
                            for field in fields
                            if str(field.get("fieldId") or field.get("key") or field.get("id") or "").lower()
                            == "assignee"
                        ),
                        None,
                    )
                    allowed_values = (
                        assignee_field.get("allowedValues", [])
                        if isinstance(assignee_field, dict)
                        else []
                    )
                    if (
                        isinstance(allowed_values, list)
                        and isinstance(assignee_field, dict)
                        and "allowedValues" in assignee_field
                    ):
                        allowed_accounts = {
                            str(
                                value.get("accountId")
                                or value.get("account_id")
                                or value.get("id")
                                or ""
                            )
                            for value in allowed_values
                            if isinstance(value, dict)
                        }
                        allowed_accounts.discard("")
                        attempt.assignee_allowed_accounts[
                            f"{project['key']}:{issue['id']}"
                        ] = allowed_accounts
                    issue["fields"] = []
                    for field in fields:
                        normalized_field = {
                            "id": field.get("fieldId") or field.get("key") or field.get("id"),
                            "name": field.get("name"),
                            "required": field.get("required", False),
                        }
                        business_key = _business_field_key(field)
                        if business_key:
                            normalized_field["business_key"] = business_key
                            normalized_field["options"] = _business_field_options(field)
                        issue["fields"].append(normalized_field)
                project["work_types"].append(issue)

        account = user_payload if isinstance(user_payload, dict) else {"raw": user_payload}
        return {
            "verified_at": _utc_now(),
            "site_url": resource.get("url") or self.settings.atlassian_site_url,
            "site_name": resource.get("name"),
            "cloud_id": cloud_id,
            "atlassian_user": {
                "account_id": account.get("accountId") or account.get("account_id") or account.get("id"),
                "display_name": account.get("displayName") or account.get("display_name") or account.get("name"),
                "email": account.get("email") or account.get("emailAddress"),
            },
            "spaces": normalized_projects,
            "read_tools_available": sorted(
                set(attempt.available_tools).intersection(READ_ONLY_TOOL_ALLOWLIST)
            ),
            "write_tools_exposed_by_server": len(
                set(attempt.available_tools) - READ_ONLY_TOOL_ALLOWLIST
            ),
        }

    async def _invoke(
        self,
        attempt: OAuthAttempt,
        name: str,
        values: dict[str, Any],
    ) -> Any:
        if attempt.provider is None:
            raise AtlassianIntegrationError("No existe un proveedor OAuth activo.")
        async with self.new_atlassian_http_client(auth=attempt.provider, follow_redirects=True, timeout=60) as client:
            async with streamable_http_client(
                self.settings.atlassian_mcp_url,
                http_client=client,
            ) as (read_stream, write_stream, _):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    return await self._invoke_with_session(attempt, session, name, values)

    async def _invoke_with_session(
        self,
        attempt: OAuthAttempt,
        session: McpSessionLike,
        name: str,
        values: dict[str, Any],
    ) -> Any:
        ensure_read_only_tool(name)
        tool = attempt.available_tools.get(name)
        if tool is None:
            raise AtlassianIntegrationError(f"El servidor MCP no expuso la herramienta '{name}'.")
        started = perf_counter()
        trace = current_trace()
        if trace is not None:
            trace.call_started()
        try:
            result = await call_read_only_tool(session, name, _schema_arguments(tool, values))
        except Exception:
            if trace is not None:
                trace.record_call(name, (perf_counter() - started) * 1000, result="ERROR")
            raise
        finally:
            if trace is not None:
                trace.call_finished()
        if trace is not None:
            trace.record_call(
                name,
                (perf_counter() - started) * 1000,
                result="ERROR" if getattr(result, "isError", False) else "OK",
            )
        if getattr(result, "isError", False):
            payload = _tool_payload(result)
            raise AtlassianIntegrationError(f"Atlassian rechazó '{name}': {payload}")
        return _tool_payload(result)

    def _connected_attempt(self, username: str) -> OAuthAttempt:
        attempt = self._attempts.get(username)
        if attempt is None or not attempt.connected:
            raise AtlassianIntegrationError("Primero conecta tu cuenta Atlassian.")
        return attempt

    async def _surface_task_failure(self, attempt: OAuthAttempt) -> None:
        if attempt.task and attempt.task.done() and not attempt.task.cancelled():
            exception = attempt.task.exception()
            if exception:
                attempt.diagnostic_failure = failure_report(exception, attempt.stage)
                attempt.error = attempt.diagnostic_failure['message']
        if attempt.error:
            raise AtlassianIntegrationError(attempt.error)

    @classmethod
    def _safe_error(cls, exc: BaseException, stage: str = "UNKNOWN") -> str:
        """Flatten task-group errors while redacting OAuth credentials and callback data."""

        leaves: list[BaseException] = []

        def collect(current: BaseException) -> None:
            if isinstance(current, BaseExceptionGroup):
                for nested in current.exceptions:
                    collect(nested)
            else:
                leaves.append(current)

        collect(exc)
        details: list[str] = []
        for leaf in leaves[:4]:
            if isinstance(leaf, AtlassianIntegrationError):
                detail = str(leaf)
            elif isinstance(leaf, httpx.HTTPStatusError):
                request = leaf.request
                detail = (
                    f"HTTP {leaf.response.status_code} en "
                    f"{request.method} {request.url.host}{request.url.path}"
                )
                response_text = leaf.response.text.strip()
                if response_text:
                    detail += f": {response_text[:300]}"
            else:
                message = str(leaf).strip()
                detail = type(leaf).__name__ + (f": {message}" if message else "")
            detail = cls._redact_sensitive(detail)
            if detail not in details:
                details.append(detail)
        summary = "; ".join(details) or type(exc).__name__
        return f"Falló la conexión Atlassian en la etapa {stage}: {summary}"

    @staticmethod
    def _redact_sensitive(value: str) -> str:
        value = re.sub(r'(?i)Bearer\s+[^\s"\x27,;]+', 'Bearer [REDACTED]', value)
        value = re.sub(r'(?i)(["\x27]?(?:access_token|refresh_token|id_token|client_secret|cookie|set-cookie|authorization|code_verifier|code_challenge|state|code)["\x27]?\s*[:=]\s*)(?:"[^"\n]*"|\x27[^\x27\n]*\x27|[^\s,;&]+)', r'\1[REDACTED]', value)
        redacted = re.sub(
            r"(?i)(access_token|refresh_token|authorization|client_secret)\s*[:=]\s*[^\s,;&]+",
            r"\1=[REDACTED]",
            value,
        )
        redacted = re.sub(
            r"(?i)([?&](?:code|state)=)[^&\s]+",
            r"\1[REDACTED]",
            redacted,
        )
        return redacted[:700]
