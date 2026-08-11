from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import logging
import re
import secrets
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
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
from .oauth_storage import EncryptedFileOAuthStorage, WindowsDpapiProtector


logger = logging.getLogger(__name__)

TARGET_SPACES = ("AT", "ASIT", "MTTI")
VISIBLE_PROJECTS_MAX_RESULTS = 50

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
    arguments: dict[str, Any] = {}
    aliases = {
        "cloudId": ("cloudId", "cloud_id"),
        "projectKey": ("projectKey", "projectIdOrKey", "projectId", "project"),
        "issueTypeId": ("issueTypeId", "issueType", "issuetypeId"),
        "query": ("query", "searchString", "searchTerm", "text", "username"),
        "jql": ("jql",),
        "maxResults": ("maxResults", "limit"),
        "nextPageToken": ("nextPageToken", "pageToken"),
        "issueIdOrKey": ("issueIdOrKey", "issueKey", "issueId"),
        "fields": ("fields",),
        "fieldsByKeys": ("fieldsByKeys",),
        "responseContentFormat": ("responseContentFormat",),
    }
    for canonical, candidates in aliases.items():
        if canonical not in values:
            continue
        for candidate in candidates:
            if candidate in properties:
                arguments[candidate] = values[canonical]
                break
    return arguments


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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
    snapshot: dict[str, Any] | None = None
    error: str | None = None
    connected: bool = False
    stage: str = "IDLE"
    sprint_cache: dict[str, tuple[datetime, list[dict[str, Any]]]] = field(default_factory=dict)


class AtlassianIntegrationManager:
    """Per-user OAuth + read-only Rovo MCP integration for the local MVP."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._attempts: dict[str, OAuthAttempt] = {}
        self._states: dict[str, OAuthAttempt] = {}
        self._restore_locks: dict[str, asyncio.Lock] = {}
        try:
            self._protector = WindowsDpapiProtector()
            self._oauth_storage_kind = "OS_ENCRYPTED"
        except RuntimeError:
            self._protector = None
            self._oauth_storage_kind = "MEMORY_ONLY"

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
            raise AtlassianIntegrationError(
                "Atlassian no entregó la URL de autorización dentro del tiempo esperado."
            ) from exc
        if attempt.error:
            raise AtlassianIntegrationError(attempt.error)
        if not attempt.authorization_url:
            raise AtlassianIntegrationError("No se recibió la URL de autorización de Atlassian.")
        return {"authorization_url": attempt.authorization_url, "phase": "AWAITING_USER_CONSENT"}

    async def finish_callback(self, code: str, state: str) -> dict[str, Any]:
        attempt = self._states.get(state)
        if attempt is None:
            raise AtlassianIntegrationError("El estado OAuth no existe o ya venció.")
        await attempt.callback_queue.put((code, state))
        if attempt.task is None:
            raise AtlassianIntegrationError("La autorización OAuth no tiene una tarea activa.")
        try:
            await asyncio.wait_for(asyncio.shield(attempt.task), timeout=90)
        except TimeoutError as exc:
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
            await self.disconnect(attempt.username)

    async def disconnect(self, username: str) -> None:
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
            attempt.storage.clear()
        else:
            self._storage(username).clear()

    async def ensure_restored(self, username: str) -> dict[str, Any]:
        """Recover a previously authorized session without asking for consent again."""

        if username in self._attempts:
            return self.status(username)
        lock = self._restore_locks.setdefault(username, asyncio.Lock())
        async with lock:
            if username in self._attempts:
                return self.status(username)
            storage = self._storage(username)
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
                attempt.snapshot = await self._discover(attempt)
                attempt.connected = True
                attempt.stage = "COMPLETE"
            except Exception as exc:
                attempt.error = self._safe_error(exc, attempt.stage)
            return self.status(username)

    async def refresh(self, username: str) -> dict[str, Any]:
        await self.ensure_restored(username)
        attempt = self._attempts.get(username)
        if (
            attempt is None
            or attempt.provider is None
            or attempt.storage.tokens is None
        ):
            raise AtlassianIntegrationError("Primero conecta tu cuenta Atlassian.")
        attempt.error = None
        attempt.connected = False
        try:
            attempt.snapshot = await self._discover(attempt)
            attempt.connected = True
            attempt.stage = "COMPLETE"
        except Exception as exc:
            attempt.error = self._safe_error(exc, attempt.stage)
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
        return exact or active_users

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
        now = datetime.now(timezone.utc)
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
            async with httpx.AsyncClient(
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
                        create_started = True
                        call_count = 1
                        try:
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
                                }
                        except Exception as exc:
                            return {
                                "issue_key": issue_key,
                                "create_response": create_payload,
                                "readback": None,
                                "readback_error": self._safe_error(exc, "READBACK_CREATED_TASK"),
                                "real_mcp_calls": 2,
                            }
                        return {
                            "issue_key": issue_key,
                            "create_response": create_payload,
                            "readback": read_payload,
                            "readback_error": None,
                            "real_mcp_calls": 2,
                        }

        try:
            return await asyncio.wait_for(operation(), timeout=timeout_seconds)
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
            return await attempt.callback_queue.get()

        provider = self._provider(
            attempt,
            redirect_handler=redirect_handler,
            callback_handler=callback_handler,
        )
        attempt.provider = provider
        attempt.stage = "OAUTH_AND_MCP_CONNECT"
        try:
            async with httpx.AsyncClient(auth=provider, follow_redirects=True, timeout=60) as client:
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
            logger.exception("Atlassian OAuth/MCP connection failed")
            attempt.error = self._safe_error(exc, attempt.stage)
            attempt.redirect_ready.set()

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
        async with httpx.AsyncClient(auth=attempt.provider, follow_redirects=True, timeout=60) as client:
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
        user_payload = _tool_payload(await call_read_only_tool(session, "atlassianUserInfo"))
        attempt.stage = "READ_ACCESSIBLE_RESOURCES"
        resources_payload = _tool_payload(
            await call_read_only_tool(session, "getAccessibleAtlassianResources")
        )
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
                    and str(issue["name"] or "").lower()
                    in {"epic", "story", "task", "bug", "subtask", "sub-task"}
                ):
                    attempt.stage = f"READ_FIELDS_{project['key']}_{issue['name']}"
                    field_payload = await self._invoke_with_session(
                        attempt,
                        session,
                        "getJiraIssueTypeMetaWithFields",
                        {
                            "cloudId": cloud_id,
                            "projectKey": project["id"] or project["key"],
                            "issueTypeId": issue["id"],
                        },
                    )
                    fields = _field_records(field_payload)
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
        async with httpx.AsyncClient(auth=attempt.provider, follow_redirects=True, timeout=60) as client:
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
        result = await call_read_only_tool(session, name, _schema_arguments(tool, values))
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
                attempt.error = self._safe_error(exception, attempt.stage)
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
