from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import logging
import os
import re
import tempfile
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from time import perf_counter
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from .atlassian import (
    AtlassianIntegrationError,
    AtlassianIntegrationManager,
    _field_records,
    _records,
    _schema_arguments,
    _tool_payload,
)

logger = logging.getLogger(__name__)

# Dashboard reads have their own scope. TARGET_SPACES and every write allowlist
# remain untouched because proposal and write flows depend on those policies.
DASHBOARD_READ_SPACE_KEYS = ("ASIT", "AT", "BD", "MTTI", "OPC")
DASHBOARD_ISSUE_FIELDS = (
    "summary", "status", "priority", "issuetype", "assignee", "created",
    "updated", "resolution", "resolutiondate", "duedate", "parent", "labels",
    "components", "fixVersions", "customfield_10147",
)
PAGE_SIZE = 100
MAX_ISSUE_PAGES = 1000
MAX_PROJECT_PAGES = 100
MAX_TYPE_PAGES = 20
MAX_RETRY_AFTER_SECONDS = 60


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _date(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except (ValueError, TypeError):
        return None


def _identity(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def _category(issue: dict[str, Any]) -> str:
    value = issue.get("fields", {}).get("status") or {}
    normalized = str(value.get("category") or "").casefold()
    if normalized in {"new", "indeterminate", "done"}:
        return normalized
    category = value.get("statusCategory") or {}
    key = str(category.get("key") or "").casefold()
    return {"new": "todo", "indeterminate": "in_progress", "done": "done"}.get(key, "unknown")


def _field_option(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return {"id": str(value["id"]) if value.get("id") is not None else None,
                "name": value.get("name") or value.get("value") or "Sin valor"}
    if value is None:
        return None
    return {"id": str(value), "name": str(value)}


def _serialise_sprint(value: Any) -> list[dict[str, Any]]:
    values = value if isinstance(value, list) else [value]
    result = []
    for sprint in values:
        if not isinstance(sprint, dict) or sprint.get("id") is None:
            continue
        result.append({
            "id": str(sprint["id"]),
            "name": sprint.get("name") or f"Sprint {sprint['id']}",
            "state": str(sprint.get("state") or "unknown").casefold(),
            "start_date": sprint.get("startDate") or sprint.get("start_date"),
            "end_date": sprint.get("endDate") or sprint.get("end_date"),
            "board_id": str(sprint.get("boardId") or sprint.get("rapidViewId") or "") or None,
        })
    return result


class DashboardDataError(RuntimeError):
    def __init__(self, message: str, *, state: str = "ERROR", retry_after: float | None = None):
        super().__init__(message)
        self.state = state
        self.retry_after = retry_after


class DashboardDataService:
    """Authenticated Jira reader, local snapshot manager, and pure aggregations."""

    def __init__(self, manager: AtlassianIntegrationManager, snapshot_root: Path,
                 *, jira_write_enabled: bool = False, write_lock: Any = None):
        self.manager = manager
        self.snapshot_root = snapshot_root
        self.jira_write_enabled = jira_write_enabled
        self.write_lock = write_lock or getattr(manager, "write_lock", None)
        self._cache: dict[str, dict[str, Any]] = {}
        self._runtime: dict[str, dict[str, Any]] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _path(self, username: str) -> Path:
        identity = hashlib.sha256(username.strip().casefold().encode("utf-8")).hexdigest()
        return self.snapshot_root / f"{identity}.json"

    def _load(self, username: str) -> dict[str, Any] | None:
        if username in self._cache:
            return self._cache[username]
        path = self._path(username)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("version") != 1 or payload.get("owner") != hashlib.sha256(username.strip().casefold().encode("utf-8")).hexdigest():
                raise ValueError("Snapshot version or owner mismatch")
            self._cache[username] = payload
            return payload
        except (OSError, ValueError, json.JSONDecodeError):
            logger.exception("Dashboard snapshot could not be loaded")
            raise DashboardDataError("No se pudo leer el snapshot local del Dashboard.")

    def _runtime_state(self, username: str) -> dict[str, Any]:
        state = self._runtime.get(username)
        if state is None:
            snapshot = self._load(username)
            state = self._runtime[username] = {
                "state": "ACTUALIZADO" if snapshot else "NO_DATA",
                "started_at": None,
                "last_error": None,
                "failed_spaces": [],
                "attempt": None,
            }
        return state

    def status(self, username: str) -> dict[str, Any]:
        snapshot = self._load(username)
        runtime = self._runtime_state(username)
        if runtime["state"] == "NO_DATA" and snapshot:
            runtime["state"] = "ACTUALIZADO"
        lock_status = self.write_lock.status() if self.write_lock and hasattr(self.write_lock, "status") else {"state": "LOCKED"}
        return {
            "state": runtime["state"],
            "has_snapshot": snapshot is not None,
            "last_updated": snapshot.get("created_at") if snapshot else None,
            "last_duration_ms": snapshot.get("duration_ms") if snapshot else None,
            "issues_read": snapshot.get("performance", {}).get("issues_read") if snapshot else None,
            "jira_reads": snapshot.get("performance", {}).get("jira_reads") if snapshot else None,
            "mcp_calls": snapshot.get("performance", {}).get("mcp_calls") if snapshot else None,
            "errors": snapshot.get("performance", {}).get("errors") if snapshot else 0,
            "timeouts": snapshot.get("performance", {}).get("timeouts") if snapshot else 0,
            "rate_limits": snapshot.get("performance", {}).get("rate_limits") if snapshot else 0,
            "cache_hits": snapshot.get("performance", {}).get("cache_hits") if snapshot else 0,
            "refresh_started_at": runtime.get("started_at"),
            "error": runtime.get("last_error"),
            "failed_spaces": runtime.get("failed_spaces", []),
            "jira_write_enabled": self.jira_write_enabled,
            "write_lock": lock_status.get("state", "LOCKED"),
        }

    def get_summary(self, username: str) -> dict[str, Any]:
        snapshot = self._load(username)
        if snapshot is None:
            raise DashboardDataError("Todavía no hay snapshot. Actualiza los datos de Jira.", state="NO_DATA")
        space_summaries = [snapshot["spaces"][key]["summary"] for key in DASHBOARD_READ_SPACE_KEYS
                           if key in snapshot["spaces"]]
        global_work_types: dict[str, dict[str, Any]] = {}
        global_priorities: dict[tuple[str, str], int] = Counter()
        global_statuses: dict[tuple[str, str, str], int] = Counter()
        global_workers: dict[str, dict[str, Any]] = {}
        dashboard_issues: list[dict[str, Any]] = []
        for key in DASHBOARD_READ_SPACE_KEYS:
            space = snapshot["spaces"].get(key) or {}
            for work_type in space.get("work_types", []):
                normalized = _identity(work_type["name"])
                item = global_work_types.setdefault(normalized, {"name": work_type["name"], "count": 0,
                                                                  "spaces": [], "space_types": []})
                item["count"] += work_type["count"]
                item["spaces"].append(key)
                item["space_types"].append({"space": key, "id": work_type["id"], "count": work_type["count"]})
            for priority in space.get("summary", {}).get("priorities", []):
                global_priorities[(str(priority.get("id") or ""), priority["name"])] += priority["count"]
            for status in space.get("summary", {}).get("statuses", []):
                global_statuses[(status["name"], status["category"], status.get("id") or "")] += status["count"]
            for issue in space.get("issues", []):
                fields = issue.get("fields", {})
                status = fields.get("status") or {}
                assignee = fields.get("assignee") or {}
                priority = fields.get("priority") or {}
                issue_type = fields.get("issuetype") or {}
                parent = fields.get("parent") or {}
                tracking = fields.get("customfield_10147") or {}
                dashboard_issues.append({
                    "key": issue.get("key"), "space": key,
                    "summary": fields.get("summary") or "(Sin resumen)",
                    "status": {"id": status.get("id"), "name": status.get("name"),
                               "category": status.get("category", "unknown")},
                    "assignee": {"displayName": assignee.get("displayName")} if assignee.get("displayName") else None,
                    "priority": {"id": priority.get("id"), "name": priority.get("name")} if priority else None,
                    "duedate": fields.get("duedate"),
                    "issuetype": {"id": issue_type.get("id"), "name": issue_type.get("name")}
                                 if issue_type else None,
                    "created": fields.get("created"), "updated": fields.get("updated"),
                    "resolutiondate": fields.get("resolutiondate"),
                    "parent": {"key": parent.get("key")} if parent.get("key") else None,
                    "tracking": {"id": tracking.get("id"), "name": tracking.get("name")}
                                if tracking else None,
                })
                worker_key = issue.get("assignee_key") or "__UNASSIGNED__"
                current = global_workers.setdefault(worker_key, {"display_name": (issue.get("fields", {}).get("assignee") or {}).get("displayName") or "Sin responsable",
                                                                 "active": 0, "todo": 0, "in_progress": 0, "overdue": 0})
                category = issue.get("fields", {}).get("status", {}).get("category")
                if category != "done":
                    current["active"] += 1
                    current["todo"] += category == "new"
                    current["in_progress"] += category == "indeterminate"
                    due = issue.get("fields", {}).get("duedate")
                    if due and date.fromisoformat(due) < datetime.now(ZoneInfo("America/Mexico_City")).date():
                        current["overdue"] += 1
        for value in global_work_types.values():
            value["spaces"] = sorted(set(value["spaces"]))
        return {
            "created_at": snapshot["created_at"],
            "duration_ms": snapshot["duration_ms"],
            "performance": snapshot["performance"],
            "spaces": space_summaries,
            "issues": dashboard_issues,
            "global": {**aggregate_global(space_summaries),
                       "work_types": sorted(global_work_types.values(), key=lambda value: (-value["count"], value["name"])),
                       "priorities": [{"id": priority_id or None, "name": name, "count": count}
                                      for (priority_id, name), count in sorted(global_priorities.items())],
                       "statuses": [{"name": name, "category": category, "id": status_id or None, "count": count}
                                    for (name, category, status_id), count in sorted(global_statuses.items())],
                       "workload": sorted(global_workers.values(), key=lambda value: (-value["active"], value["display_name"].casefold()))},
        }

    def get_space(self, username: str, key: str) -> dict[str, Any]:
        key = key.upper()
        if key not in DASHBOARD_READ_SPACE_KEYS:
            raise KeyError(key)
        snapshot = self._load(username)
        if snapshot is None or key not in snapshot["spaces"]:
            raise DashboardDataError("Este espacio todavía no tiene datos en el snapshot.", state="NO_DATA")
        result = copy.deepcopy(snapshot["spaces"][key])
        result.pop("issues", None)
        result.pop("metadata", None)
        return result

    def get_issues(
        self, username: str, *, space: str | None = None, category: str | None = None,
        issue_type: str | None = None, type_name: str | None = None, priority: str | None = None,
        assignee: str | None = None, tracking: str | None = None,
        epic_key: str | None = None, overdue: bool = False, unassigned: bool = False,
        page: int = 1, page_size: int = 50,
    ) -> dict[str, Any]:
        snapshot = self._load(username)
        if snapshot is None:
            raise DashboardDataError("Todavía no hay snapshot. Actualiza los datos de Jira.", state="NO_DATA")
        if space and space.upper() not in DASHBOARD_READ_SPACE_KEYS:
            raise KeyError(space)
        as_of = _date(snapshot["created_at"]) or _utc_now()
        today = as_of.astimezone(ZoneInfo("America/Mexico_City")).date()
        found = []
        keys = [space.upper()] if space else list(DASHBOARD_READ_SPACE_KEYS)
        for key in keys:
            current = snapshot["spaces"].get(key)
            if not current:
                continue
            for issue in current["issues"]:
                fields = issue["fields"]
                category_filter = {"todo": "new", "in_progress": "indeterminate"}.get(category, category)
                if category_filter and _category(issue) != category_filter:
                    continue
                if issue_type and str((fields.get("issuetype") or {}).get("id")) != issue_type:
                    continue
                if type_name and _identity((fields.get("issuetype") or {}).get("name")) != _identity(type_name):
                    continue
                if priority == "NONE":
                    if fields.get("priority"):
                        continue
                elif priority and str((fields.get("priority") or {}).get("id")) != priority:
                    continue
                who = (fields.get("assignee") or {}).get("displayName")
                if unassigned and who:
                    continue
                if assignee and _identity(who) != _identity(assignee):
                    continue
                parent_key = (fields.get("parent") or {}).get("key")
                if epic_key and parent_key != epic_key and issue.get("key") != epic_key:
                    continue
                tracking_value = fields.get("customfield_10147") or {}
                if tracking == "NONE":
                    if tracking_value:
                        continue
                elif tracking and str(tracking_value.get("id") or "") != tracking:
                    continue
                due = fields.get("duedate")
                is_overdue = bool(_category(issue) != "done" and due and date.fromisoformat(due) < today)
                if overdue and not is_overdue:
                    continue
                found.append({"key": issue["key"], "space": key, "summary": fields.get("summary") or "(Sin resumen)",
                              "status": fields.get("status"), "assignee": fields.get("assignee"),
                              "priority": fields.get("priority"), "duedate": due,
                              "issuetype": fields.get("issuetype")})
        found.sort(key=lambda issue: (issue["space"], issue["key"]))
        page = max(1, page)
        page_size = min(200, max(1, page_size))
        start = (page - 1) * page_size
        return {"total": len(found), "page": page, "page_size": page_size,
                "issues": found[start:start + page_size], "snapshot_at": snapshot["created_at"]}

    def refresh(self, username: str) -> dict[str, Any]:
        runtime = self._runtime_state(username)
        task = self._tasks.get(username)
        if task and not task.done():
            return self.status(username)
        runtime.update(state="ACTUALIZANDO", started_at=_utc_now().isoformat(), last_error=None, failed_spaces=[])
        self._tasks[username] = asyncio.create_task(self._run_refresh(username))
        return self.status(username)

    async def _run_refresh(self, username: str) -> None:
        lock = self._locks.setdefault(username, asyncio.Lock())
        if lock.locked():
            return
        async with lock:
            started = perf_counter()
            runtime = self._runtime_state(username)
            counters = {"calls": 0, "jira_reads": 0, "mcp_calls": 0, "errors": 0,
                        "timeouts": 0, "rate_limits": 0, "cache_hits": 0, "http_statuses": Counter()}
            failed_spaces: list[dict[str, Any]] = []
            new_spaces: dict[str, Any] = {}
            try:
                restore = getattr(self.manager, "ensure_restored", None)
                if restore:
                    await restore(username)
                attempt = self.manager._connected_attempt(username)
                if not attempt.snapshot or not attempt.snapshot.get("cloud_id"):
                    raise DashboardDataError("La conexión Jira no expone un sitio listo para lectura.", state="JIRA_DISCONNECTED")
                cloud_id = attempt.snapshot["cloud_id"]
                schemas = attempt.available_tools
                project_tool = schemas.get("getVisibleJiraProjects")
                if project_tool is None:
                    raise DashboardDataError("MCP no publicó la herramienta de proyectos requerida.", state="JIRA_DISCONNECTED")
                event_responses: list[dict[str, Any]] = []

                async def response_hook(response: httpx.Response) -> None:
                    event_responses.append({"status": response.status_code,
                                            "retry_after": response.headers.get("Retry-After")})
                    counters["http_statuses"][str(response.status_code)] += 1

                timeout = httpx.Timeout(60.0, connect=20.0)
                async with self.manager.new_atlassian_http_client(
                    auth=attempt.provider,
                    follow_redirects=True,
                    timeout=timeout,
                    event_hooks={"response": [response_hook]},
                ) as client:
                    async with streamable_http_client(self.manager.settings.atlassian_mcp_url,
                                                       http_client=client) as (read_stream, write_stream, _):
                        async with ClientSession(read_stream, write_stream) as session:
                            await asyncio.wait_for(session.initialize(), 60)
                            counters["mcp_calls"] += 1

                            async def invoke(name: str, values: dict[str, Any], *, project: bool = False) -> Any:
                                if project:
                                    tool = project_tool
                                else:
                                    tool = schemas.get(name)
                                if tool is None:
                                    raise DashboardDataError(f"MCP no publicó la herramienta {name}.")
                                args = _schema_arguments(tool, values)
                                properties = (tool.inputSchema or {}).get("properties", {})
                                if name == "getVisibleJiraProjects":
                                    # The MCP schema defaults this endpoint to action=create.
                                    # Dashboard inventory always asks for browse visibility.
                                    for explicit in ("action", "expandIssueTypes"):
                                        if explicit in values and explicit in properties:
                                            args[explicit] = values[explicit]
                                if name == "searchJiraIssuesUsingJql" and "searchResultMode" in properties:
                                    args["searchResultMode"] = "issues"
                                counters["calls"] += 1
                                counters["jira_reads"] += 1
                                counters["mcp_calls"] += 1
                                before = len(event_responses)
                                try:
                                    result = await asyncio.wait_for(
                                        self.manager._invoke_with_session(attempt, session, name, args), 70
                                    )
                                    if getattr(result, "isError", False):
                                        result = _tool_payload(result)
                                        raise DashboardDataError(str(result)[:500])
                                    return result
                                except (httpx.TimeoutException, asyncio.TimeoutError) as exc:
                                    counters["timeouts"] += 1
                                    counters["errors"] += 1
                                    raise DashboardDataError("Jira tardó demasiado al consultar datos.", state="ERROR") from exc
                                except Exception as exc:
                                    responses = event_responses[before:]
                                    limited = next((response for response in responses if response["status"] == 429), None)
                                    payload = str(exc)
                                    retry_match = re.search(r"retry[- ]after\s*[:=]?\s*(\d+(?:\.\d+)?)", payload, re.I)
                                    delay_value = (limited or {}).get("retry_after")
                                    try:
                                        delay = float(delay_value) if delay_value else float(retry_match.group(1)) if retry_match else None
                                    except (ValueError, TypeError):
                                        delay = None
                                    if limited or "429" in payload or "rate limit" in payload.casefold():
                                        counters["rate_limits"] += 1
                                        if delay is not None and 0 < delay <= MAX_RETRY_AFTER_SECONDS:
                                            await asyncio.sleep(delay)
                                            counters["calls"] += 1
                                            counters["jira_reads"] += 1
                                            counters["mcp_calls"] += 1
                                            try:
                                                result = await asyncio.wait_for(
                                                    self.manager._invoke_with_session(attempt, session, name, args), 70
                                                )
                                                if not getattr(result, "isError", False):
                                                    return result
                                            except Exception:
                                                pass
                                        counters["errors"] += 1
                                        raise DashboardDataError(
                                            "Jira limitó las consultas. Se respetó Retry-After una sola vez cuando estuvo disponible.",
                                            state="RATE_LIMITED", retry_after=delay,
                                        ) from exc
                                    counters["errors"] += 1
                                    if "403" in payload or "permission" in payload.casefold() or "forbidden" in payload.casefold():
                                        raise DashboardDataError("La cuenta no tiene permiso para leer este contenido.", state="NO_PERMISSION") from exc
                                    raise DashboardDataError(payload[:500] or "Falló la consulta READ ONLY de Jira.") from exc

                            projects: list[dict[str, Any]] = []
                            for offset in range(MAX_PROJECT_PAGES):
                                payload = await invoke("getVisibleJiraProjects", {
                                    "cloudId": cloud_id, "action": "browse", "startAt": offset * 50,
                                    "maxResults": 50, "expandIssueTypes": False,
                                }, project=True)
                                page = _records(payload, ("projects",))
                                projects.extend(page)
                                if len(page) < 50 or (isinstance(payload, dict) and (
                                    payload.get("isLast") is True or offset * 50 + len(page) >= payload.get("total", float("inf"))
                                )):
                                    break
                            else:
                                raise DashboardDataError("La lista de proyectos excedió el límite de páginas.")

                            for key in DASHBOARD_READ_SPACE_KEYS:
                                try:
                                    project = next((value for value in projects if str(value.get("key", "")).upper() == key), None)
                                    if project is None:
                                        failed_spaces.append({"key": key, "state": "NO_PERMISSION", "message": "No aparece en proyectos accesibles."})
                                        continue
                                    type_payload = await invoke("getJiraProjectIssueTypesMetadata", {
                                        "cloudId": cloud_id, "projectKey": key, "startAt": 0, "maxResults": 200,
                                    })
                                    types = _records(type_payload, ("issueTypes",))
                                    if not types:
                                        raise DashboardDataError("Jira no devolvió Work Types para este espacio.", state="PARTIAL")

                                    fields_by_type: dict[str, list[dict[str, Any]]] = {}
                                    work_types = []
                                    sprint_field_ids: set[str] = set()
                                    for work_type in types:
                                        issue_type_id = str(work_type.get("id", ""))
                                        all_fields: dict[str, dict[str, Any]] = {}
                                        offset = 0
                                        for _ in range(MAX_TYPE_PAGES):
                                            field_payload = await invoke("getJiraIssueTypeMetaWithFields", {
                                                "cloudId": cloud_id, "projectKey": key,
                                                "issueTypeId": issue_type_id, "startAt": offset,
                                                "maxResults": 50, "requiredFieldsOnly": False,
                                            })
                                            field_records = _field_records(field_payload)
                                            for record in field_records:
                                                field_id = str(record.get("fieldId") or record.get("key") or record.get("id") or "")
                                                if field_id:
                                                    all_fields[field_id] = record
                                            total = field_payload.get("total") if isinstance(field_payload, dict) else None
                                            if (not field_records or (isinstance(field_payload, dict) and field_payload.get("isLast") is True)
                                                or isinstance(total, (int, float)) and offset + len(field_records) >= int(total)
                                                or not isinstance(total, (int, float)) and len(field_records) < 50):
                                                break
                                            offset += len(field_records)
                                        else:
                                            raise DashboardDataError(f"Metadatos de {key}/{issue_type_id} excedieron el límite de páginas.")
                                        fields_by_type[issue_type_id] = list(all_fields.values())
                                        for field_id, field_info in all_fields.items():
                                            schema = field_info.get("schema") or {}
                                            if "sprint" in str(field_info.get("name", "")).casefold() or "sprint" in str(schema.get("custom", "")).casefold():
                                                sprint_field_ids.add(field_id)
                                        work_types.append({"id": issue_type_id, "name": work_type.get("name") or "Desconocido",
                                                           "subtask": bool(work_type.get("subtask")),
                                                           "hierarchy_level": work_type.get("hierarchyLevel")})
                                    fields = list(dict.fromkeys([*DASHBOARD_ISSUE_FIELDS, *sorted(sprint_field_ids)]))
                                    type_definitions = {}
                                    for issue_type_id, field_records in fields_by_type.items():
                                        track = {}
                                        priorities = {}
                                        parent_available = False
                                        for info in field_records:
                                            field_id = str(info.get("fieldId") or info.get("key") or info.get("id") or "")
                                            if field_id == "customfield_10147":
                                                track = {"available": True, "name": info.get("name"), "types": [],
                                                         "options": [{"id": str(v.get("id")), "name": v.get("value") or v.get("name")}
                                                                     for v in info.get("allowedValues", []) if isinstance(v, dict)]}
                                            elif field_id == "priority":
                                                priorities = {str(v.get("id")): v.get("name") for v in info.get("allowedValues", []) if isinstance(v, dict)}
                                            elif field_id == "parent":
                                                parent_available = True
                                        type_definitions[issue_type_id] = {"tracking": track, "priorities": priorities,
                                                                          "parent_available": parent_available}

                                    raw_issues: list[dict[str, Any]] = []
                                    seen: set[str] = set()
                                    page_token = None
                                    page_count = 0
                                    seen_tokens: set[str] = set()
                                    for _ in range(MAX_ISSUE_PAGES):
                                        args: dict[str, Any] = {
                                            "cloudId": cloud_id,
                                            "jql": f'project = "{key}" ORDER BY key ASC',
                                            "maxResults": PAGE_SIZE, "fields": fields,
                                            "searchResultMode": "issues", "responseContentFormat": "adf",
                                        }
                                        if page_token:
                                            args["nextPageToken"] = page_token
                                        payload = await invoke("searchJiraIssuesUsingJql", args)
                                        if not isinstance(payload, dict) or not isinstance(payload.get("issues"), list):
                                            raise DashboardDataError("Jira devolvió una página de issues incompleta.", state="PARTIAL")
                                        page_issues = payload["issues"]
                                        for issue in page_issues:
                                            issue_key = str(issue.get("key") or "")
                                            if not issue_key.startswith(key + "-"):
                                                raise DashboardDataError("JQL devolvió un issue fuera del espacio solicitado.")
                                            if issue_key in seen:
                                                raise DashboardDataError("Jira repitió un issue al paginar el espacio.")
                                            seen.add(issue_key)
                                            raw_issues.append(issue)
                                        page_count += 1
                                        page_token = payload.get("nextPageToken")
                                        if not page_token:
                                            if payload.get("isLast") is False:
                                                raise DashboardDataError("La página no fue final y Jira omitió el token de continuación.", state="PARTIAL")
                                            break
                                        if page_token in seen_tokens:
                                            raise DashboardDataError("Jira repitió el token de paginación.", state="PARTIAL")
                                        seen_tokens.add(page_token)
                                    else:
                                        raise DashboardDataError("La consulta excedió el límite de páginas de issues.", state="PARTIAL")

                                    new_spaces[key] = self._normalise_space(
                                        key, project, work_types, type_definitions, sprint_field_ids,
                                        raw_issues,
                                    )
                                    new_spaces[key]["performance"] = {"issues_read": len(raw_issues), "pages": page_count}
                                except DashboardDataError as exc:
                                    failed_spaces.append({"key": key, "state": exc.state, "message": str(exc)})
                                except Exception as exc:
                                    logger.exception("Dashboard read failed for %s", key)
                                    failed_spaces.append({"key": key, "state": "ERROR", "message": str(exc)[:500]})

                if failed_spaces or set(new_spaces) != set(DASHBOARD_READ_SPACE_KEYS):
                    failure_state = ("RATE_LIMITED" if any(f["state"] == "RATE_LIMITED" for f in failed_spaces)
                                     else "NO_PERMISSION" if not new_spaces and failed_spaces and all(f["state"] == "NO_PERMISSION" for f in failed_spaces)
                                     else "PARTIAL")
                    runtime.update(state=failure_state,
                                   last_error="La actualización quedó parcial; se conserva el último snapshot completo.",
                                   failed_spaces=failed_spaces)
                    return

                now = _utc_now()
                duration = round((perf_counter() - started) * 1000, 2)
                combined = {"created_at": now.isoformat(), "duration_ms": duration,
                            "spaces": new_spaces, "version": 1,
                            "performance": {**{k: counters[k] for k in ("calls", "jira_reads", "mcp_calls", "errors", "timeouts", "rate_limits", "cache_hits")},
                                            "issues_read": sum(len(space["issues"]) for space in new_spaces.values()),
                                            "pages": sum(space["performance"]["pages"] for space in new_spaces.values()),
                                            "http_statuses": dict(counters["http_statuses"]),
                                            "duration_ms": duration},
                            "owner": hashlib.sha256(username.strip().casefold().encode("utf-8")).hexdigest()}
                path = self._path(username)
                path.parent.mkdir(parents=True, exist_ok=True)
                descriptor, temporary = tempfile.mkstemp(prefix="dashboard-", suffix=".tmp", dir=path.parent)
                try:
                    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                        json.dump(combined, stream, ensure_ascii=False, separators=(",", ":"))
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.replace(temporary, path)
                except Exception:
                    Path(temporary).unlink(missing_ok=True)
                    raise
                self._cache[username] = combined
                runtime.update(state="ACTUALIZADO", last_error=None, failed_spaces=[])
            except DashboardDataError as exc:
                counters["errors"] += 1
                if exc.state == "JIRA_DISCONNECTED":
                    runtime["state"] = "JIRA_DISCONNECTED"
                elif exc.state == "RATE_LIMITED":
                    runtime["state"] = "RATE_LIMITED"
                else:
                    runtime["state"] = "STALE" if self._load(username) else exc.state
                runtime["last_error"] = str(exc)
                runtime["failed_spaces"] = failed_spaces
            except Exception as exc:
                logger.exception("Dashboard refresh failed")
                runtime.update(state="STALE" if self._load(username) else "ERROR",
                               last_error=str(exc)[:500], failed_spaces=failed_spaces)

    @staticmethod
    def _normalise_space(
        key: str, project: dict[str, Any], work_types: list[dict[str, Any]],
        type_definitions: dict[str, Any], sprint_field_ids: set[str],
        raw_issues: list[dict[str, Any]],
    ) -> dict[str, Any]:
        by_type: Counter[str] = Counter()
        status_counts: Counter[tuple[str, str, str]] = Counter()
        priority_counts: Counter[tuple[str, str]] = Counter()
        tracking_counts: Counter[tuple[str, str]] = Counter()
        workers: dict[str, dict[str, Any]] = {}
        sprints: dict[str, dict[str, Any]] = {}
        issue_rows: list[dict[str, Any]] = []
        epics: list[dict[str, Any]] = []
        metadata_tracking: dict[str, Any] = {}
        metadata_priorities: dict[str, str] = {}
        parent_supported = False
        for type_id, definition in type_definitions.items():
            if definition.get("tracking", {}).get("available"):
                previous = metadata_tracking.get("options", {})
                metadata_tracking = {"available": True, "name": definition["tracking"].get("name") or "Tipo de seguimiento",
                                     "types": [], "options": previous}
                metadata_tracking["types"].append(type_id)
                for option in definition["tracking"].get("options", []):
                    if option.get("id"):
                        metadata_tracking["options"][option["id"]] = option.get("name")
            metadata_priorities.update(definition.get("priorities", {}))
            parent_supported = parent_supported or definition.get("parent_available", False)

        for raw in raw_issues:
            fields = raw.get("fields") or {}
            issue_type = fields.get("issuetype") or {}
            issue_type_id = str(issue_type.get("id") or "")
            issue_type_name = issue_type.get("name") or "Desconocido"
            status = fields.get("status") or {}
            status_category = status.get("statusCategory") or {}
            category = str(status_category.get("key") or "unknown").casefold()
            priority = fields.get("priority")
            priority_value = _field_option(priority)
            if priority_value:
                priority_counts[(priority_value["id"] or "", priority_value["name"])] += 1
            else:
                priority_counts[("", "Sin prioridad")] += 1
            track = fields.get("customfield_10147")
            tracking_value = _field_option(track)
            if tracking_value:
                tracking_counts[(tracking_value["id"] or "", tracking_value["name"])] += 1
            else:
                tracking_counts[("", "Sin valor")] += 1
            due = fields.get("duedate")
            assignee_raw = fields.get("assignee") or {}
            account_id = assignee_raw.get("accountId") or assignee_raw.get("account_id")
            display_name = assignee_raw.get("displayName") if account_id else None
            worker_key = str(account_id) if account_id else "__UNASSIGNED__"
            worker = workers.setdefault(worker_key, {"display_name": display_name or "Sin responsable", "active": 0,
                                                       "todo": 0, "in_progress": 0, "overdue": 0, "total_assigned": 0})
            if account_id:
                worker["total_assigned"] += 1
            if category != "done":
                worker["active"] += 1
                if category == "new": worker["todo"] += 1
                elif category == "indeterminate": worker["in_progress"] += 1
            if due and category != "done":
                try:
                    if date.fromisoformat(due) < datetime.now(ZoneInfo("America/Mexico_City")).date():
                        worker["overdue"] += 1
                except ValueError:
                    pass
            by_type[issue_type_id] += 1
            status_counts[(str(status.get("id") or ""), status.get("name") or "Desconocido", category)] += 1
            parent = fields.get("parent") or {}
            components = fields.get("components") or []
            versions = fields.get("fixVersions") or []
            sprint_values = []
            for sprint_field_id in sprint_field_ids:
                sprint_values.extend(_serialise_sprint(fields.get(sprint_field_id)))
            # Keep a compact issue record for cached charts and read-only drill-down.
            issue = {
                "key": raw.get("key"), "id": raw.get("id"), "fields": {
                    "summary": fields.get("summary"),
                    "status": {"id": str(status.get("id")) if status.get("id") is not None else None,
                               "name": status.get("name"), "category": category,
                               "category_name": status_category.get("name")},
                    "priority": priority_value,
                    "issuetype": {"id": issue_type_id, "name": issue_type_name,
                                  "subtask": bool(issue_type.get("subtask")),
                                  "hierarchy_level": issue_type.get("hierarchyLevel")},
                    "assignee": {"displayName": display_name} if account_id else None,
                    "created": fields.get("created"), "updated": fields.get("updated"),
                    "resolution": _field_option(fields.get("resolution")),
                    "resolutiondate": fields.get("resolutiondate"), "duedate": due,
                    "parent": {"key": parent.get("key"), "summary": parent.get("fields", {}).get("summary")}
                              if parent.get("key") else None,
                    "labels": fields.get("labels") or [],
                    "components": [c.get("name") for c in components if isinstance(c, dict)],
                    "fixVersions": [v.get("name") for v in versions if isinstance(v, dict)],
                    "sprints": sprint_values,
                    "customfield_10147": tracking_value,
                },
                "assignee_key": hashlib.sha256(str(account_id).encode("utf-8")).hexdigest() if account_id else None,
            }
            issue_rows.append(issue)
            if issue_type.get("hierarchyLevel") == 1 or issue_type_name.casefold() == "epic":
                epics.append(issue)
            for sprint in sprint_values:
                sprint_id = sprint["id"]
                current = sprints.setdefault(sprint_id, {**sprint, "issue_keys": []})
                current["issue_keys"].append(issue["key"])

        now = _utc_now()
        recent_cutoff = now - timedelta(days=7)
        recent_30d_cutoff = now - timedelta(days=30)
        local_today = now.astimezone(ZoneInfo("America/Mexico_City")).date()
        active = [issue for issue in issue_rows if issue["fields"]["status"]["category"] != "done"]
        todo = [issue for issue in issue_rows if issue["fields"]["status"]["category"] == "new"]
        in_progress = [issue for issue in issue_rows if issue["fields"]["status"]["category"] == "indeterminate"]
        done = [issue for issue in issue_rows if issue["fields"]["status"]["category"] == "done"]
        overdue = [issue for issue in active if issue["fields"].get("duedate") and date.fromisoformat(issue["fields"]["duedate"]) < local_today]
        due_soon = [issue for issue in active if issue["fields"].get("duedate") and local_today <= date.fromisoformat(issue["fields"]["duedate"]) <= local_today + timedelta(days=7)]
        created_recent = sum(bool((value := _date(issue["fields"].get("created"))) and recent_cutoff <= value <= now) for issue in issue_rows)
        updated_recent = sum(bool((value := _date(issue["fields"].get("updated"))) and recent_cutoff <= value <= now) for issue in issue_rows)
        updated_30d = sum(bool((value := _date(issue["fields"].get("updated"))) and recent_30d_cutoff <= value <= now) for issue in issue_rows)
        done_dates = [issue["fields"].get("resolutiondate") for issue in done]
        known_done = sum(bool(_date(value) and _date(value) >= now - timedelta(days=7)) for value in done_dates)
        unknown_done_dates = sum(not value or _date(value) is None for value in done_dates)
        status_output = [{"id": status_id or None, "name": name, "category": category,
                          "count": count} for (status_id, name, category), count in sorted(status_counts.items())]
        types_output = []
        type_names = {str(value.get("id")): value for value in work_types}
        for type_id, definition in type_names.items():
            count = by_type[type_id]
            types_output.append({"id": type_id, "name": definition["name"], "subtask": definition["subtask"],
                                 "hierarchy_level": definition.get("hierarchy_level"), "count": count,
                                 "percent": round(count / len(issue_rows) * 100, 2) if issue_rows else 0})
        types_output.sort(key=lambda item: (-item["count"], item["name"]))
        priorities_output = [{"id": priority_id or None, "name": name, "count": count}
                             for (priority_id, name), count in sorted(priority_counts.items())]
        workload = sorted(workers.values(), key=lambda item: (-item["active"], item["display_name"].casefold()))
        # Epic progress is computed only from direct parent evidence in this Space snapshot.
        epic_progress = []
        issue_by_key = {issue["key"]: issue for issue in issue_rows}
        for epic in epics:
            children = [issue for issue in issue_rows if (issue["fields"].get("parent") or {}).get("key") == epic["key"]]
            groups = Counter(issue["fields"]["status"]["category"] for issue in children)
            total = len(children)
            epic_progress.append({"key": epic["key"], "summary": epic["fields"].get("summary"),
                                  "total_children": total, "done": groups["done"],
                                  "in_progress": groups["indeterminate"], "todo": groups["new"],
                                  "progress_percent": round(groups["done"] / total * 100, 1) if total else None,
                                  "state": "ACTUALIZADO" if total else "N/D"})
        parent_keys = {str((issue["fields"].get("parent") or {}).get("key")) for issue in issue_rows
                       if (issue["fields"].get("parent") or {}).get("key")}
        parent_count = sum(bool(issue["fields"].get("parent")) for issue in issue_rows)
        parent_confidence = "ACTUALIZADO" if parent_supported and all(parent in issue_by_key for parent in parent_keys) else "PARTIAL" if parent_count or parent_supported else "N/D"
        sprint_values = sorted(sprints.values(), key=lambda item: (item["state"], item.get("name", "")))
        tracking_options = metadata_tracking.get("options", {})
        tracking_populated = sum(count for (_id, name), count in tracking_counts.items() if name != "Sin valor")
        tracking_empty = next((count for (_id, name), count in tracking_counts.items() if name == "Sin valor"), 0)
        summary = {
            "key": key, "name": project.get("name") or key, "id": str(project.get("id") or ""),
            "project_type": project.get("projectTypeKey"), "style": project.get("style"),
            "lead": (project.get("lead") or {}).get("displayName") if isinstance(project.get("lead"), dict) else None,
            "access": "YES", "total": len(issue_rows), "todo": len(todo),
            "in_progress": len(in_progress), "done": len(done),
            "unknown_status_category": sum(_category(issue) == "unknown" for issue in issue_rows),
            "unassigned": sum(issue["fields"].get("assignee") is None for issue in issue_rows),
            "active": len(active), "overdue": len(overdue), "due_next_7d": len(due_soon),
            "has_due_date": sum(bool(issue["fields"].get("duedate")) for issue in issue_rows),
            "no_due_date": sum(not issue["fields"].get("duedate") for issue in issue_rows),
            "created_7d": created_recent, "updated_7d": updated_recent, "updated_30d": updated_30d,
            "recent_activity": updated_30d > 0,
            "completed_7d": {"value": known_done if not unknown_done_dates else None,
                             "known_count": known_done, "missing_resolutiondate": unknown_done_dates,
                             "state": "ACTUALIZADO" if not unknown_done_dates else "PARTIAL"},
            "last_issue_updated": max((issue["fields"].get("updated") or "" for issue in issue_rows), default=None),
            "statuses": status_output, "work_types": types_output, "priorities": priorities_output,
            "workload": workload, "active_assignees": sum(w["active"] > 0 and w["display_name"] != "Sin responsable" for w in workload),
            "sprint": {"supported": bool(sprint_field_ids), "state": "ACTUALIZADO" if sprint_field_ids else "NOT_APPLICABLE",
                       "active": [s for s in sprint_values if s["state"] == "active"],
                       "future": [s for s in sprint_values if s["state"] == "future"],
                       "issues_in_active": len({key for s in sprint_values if s["state"] == "active" for key in s["issue_keys"]}),
                       "note": "Sólo sprints con issues visibles; la API MCP no enumera sprints vacíos."},
            "epics": {"supported": any(w.get("hierarchy_level") == 1 or w["name"].casefold() == "epic" for w in work_types),
                      "state": parent_confidence, "items": epic_progress,
                      "children_visible": parent_count, "parent_relationship_confidence": parent_confidence},
            "tracking": {"available": bool(metadata_tracking), "state": "ACTUALIZADO" if metadata_tracking else "N/D",
                         "name": metadata_tracking.get("name"), "available_types": metadata_tracking.get("types", []),
                         "options": [{"id": option_id, "name": name,
                                      "count": next((count for (value_id, _), count in tracking_counts.items() if value_id == option_id), 0)}
                                     for option_id, name in tracking_options.items()],
                         "populated": tracking_populated, "empty": tracking_empty,
                         "context_note": "La disponibilidad se informa según metadatos por Work Type."},
            "freshness": "Sin actividad reciente" if not updated_30d else None,
        }
        return {"summary": summary, "work_types": types_output, "issues": issue_rows,
                "metadata": {"priorities": metadata_priorities, "tracking": metadata_tracking,
                             "sprint_field_ids": sorted(sprint_field_ids)}}


def aggregate_global(spaces: list[dict[str, Any]]) -> dict[str, Any]:
    keys = ("total", "todo", "in_progress", "done", "unassigned", "active", "overdue", "due_next_7d",
            "has_due_date", "no_due_date", "created_7d", "updated_7d", "updated_30d")
    metrics = {key: sum(int(space.get(key) or 0) for space in spaces) for key in keys}
    metrics["completed_7d"] = {
        "value": sum(space["completed_7d"]["value"] for space in spaces)
        if all(space["completed_7d"]["value"] is not None for space in spaces) else None,
        "missing_resolutiondate": sum(space["completed_7d"]["missing_resolutiondate"] for space in spaces),
        "state": "ACTUALIZADO" if all(space["completed_7d"]["value"] is not None for space in spaces) else "PARTIAL",
    }
    return metrics
