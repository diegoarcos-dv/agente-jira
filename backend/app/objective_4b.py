from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any, Callable, Protocol

from .execution_policy import JiraExecutionPolicy
from .repository import ProposalRepository
from .sprints import revalidate_sprint


class Objective4BError(RuntimeError):
    pass


class ControlledJiraWriteGateway(Protocol):
    async def list_sprints(
        self, username: str, space: str, *, force_refresh: bool = False
    ) -> list[dict[str, Any]]: ...

    async def create_single_task_and_readback(
        self,
        username: str,
        create_arguments: dict[str, Any],
        readback_fields: list[str],
        timeout_seconds: int,
    ) -> dict[str, Any]: ...


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _normalize(value: Any) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def _nested_issue(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    if isinstance(payload.get("fields"), dict) and (payload.get("key") or payload.get("id")):
        return payload
    for key in ("issue", "data", "result", "value"):
        nested = payload.get(key)
        found = _nested_issue(nested)
        if found is not None:
            return found
    return None


def _contains_sprint_id(value: Any, expected_id: str) -> bool:
    if isinstance(value, list):
        return any(_contains_sprint_id(candidate, expected_id) for candidate in value)
    if isinstance(value, dict):
        if str(value.get("id") or value.get("sprintId") or "") == expected_id:
            return True
        return any(_contains_sprint_id(candidate, expected_id) for candidate in value.values())
    if isinstance(value, str):
        return bool(re.search(rf"(?:^|[,\[])id={re.escape(expected_id)}(?:,|\])", value))
    return str(value) == expected_id


class JiraControlledExecutionService:
    CONFIRMATION_TTL = timedelta(minutes=10)
    CONFIRMATION_PHRASE = "CREAR 1 TASK EN AT"
    TERMINAL_STATUSES = {
        "CREATED_VERIFIED",
        "CREATED_UNVERIFIED",
        "REJECTED",
        "UNKNOWN",
    }

    def __init__(
        self,
        repository: ProposalRepository,
        policy: JiraExecutionPolicy,
        gateway: ControlledJiraWriteGateway,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.repository = repository
        self.policy = policy
        self.gateway = gateway
        self.now = now

    def prepare(
        self,
        execution_id: str,
        username: str,
        jira_snapshot: dict[str, Any],
        tool_readiness: dict[str, Any],
    ) -> dict[str, Any]:
        intent = self._owned(execution_id, username)
        if intent["status"] in {
            "REAL_PREPARED",
            "REAL_CONFIRMED",
            "SUBMITTED",
            *self.TERMINAL_STATUSES,
        }:
            return {**intent, "reused": True}
        if intent["status"] != "SIMULATED":
            raise Objective4BError("Completa primero la simulacion local de esta actividad.")
        proposal, dry_run, dry_item = self._current_documents(intent)
        create_tool = tool_readiness.get("create") or {}
        readback_tool = tool_readiness.get("readback") or {}
        if not create_tool.get("exposed") or not readback_tool.get("exposed"):
            raise Objective4BError(
                "Rovo debe exponer createJiraIssue y getJiraIssue antes de habilitar el envio."
            )
        create_schema = create_tool.get("input_schema") or {}
        readback_schema = readback_tool.get("input_schema") or {}
        if not {"cloudId", "projectKey", "issueTypeName", "summary"}.issubset(
            set(create_schema.get("required") or [])
        ):
            raise Objective4BError("El contrato anunciado de createJiraIssue no es compatible.")
        if not {"cloudId", "issueIdOrKey"}.issubset(
            set(readback_schema.get("required") or [])
        ):
            raise Objective4BError("El contrato anunciado de getJiraIssue no es compatible.")

        assignee = dry_item.get("assignee") or {}
        violations = self.policy.canary_gate_violations(
            space=dry_item.get("space"),
            work_type=dry_item.get("work_type"),
            item_count=1,
            tool_name="createJiraIssue",
            approved_version_current=proposal.get("status") == "APPROVED",
            dry_run_current=dry_run.get("dry_run_id") == intent.get("dry_run_id"),
            dry_run_blockers=dry_run.get("summary", {}).get("blocked", 0),
            exact_active_account=bool(assignee.get("account_id")),
            assignee_in_atomic_create=bool(assignee.get("account_id")),
            second_confirmation=True,
        )
        if violations:
            raise Objective4BError("El kill switch bloqueo el envio: " + ", ".join(violations))

        candidate = intent.get("payload", {}).get("arguments", {})
        additional_fields = self._additional_fields(
            candidate.get("fields") or {},
            jira_snapshot,
        )
        labels = list(dict.fromkeys([self.policy.document["test_label"]]))
        if labels:
            additional_fields["labels"] = labels
        real_arguments = {
            "cloudId": jira_snapshot.get("cloud_id") or candidate.get("cloudId"),
            "projectKey": "AT",
            "issueTypeName": "Task",
            "summary": candidate.get("summary"),
            "description": candidate.get("description"),
            "assignee_account_id": assignee.get("account_id"),
            "additional_fields": additional_fields,
            "contentFormat": "markdown",
            "responseContentFormat": "markdown",
        }
        real_arguments = {
            key: value
            for key, value in real_arguments.items()
            if value is not None and value != {}
        }
        now = self.now()
        intent["status"] = "REAL_PREPARED"
        intent["jira_write_enabled"] = True
        intent["updated_at"] = _iso(now)
        sprint_resolution = copy.deepcopy(dry_item.get("sprint_resolution"))
        if sprint_resolution and (sprint_resolution.get("selected") or {}).get("id"):
            sprint_field = self._sprint_field(jira_snapshot)
            if not sprint_field or not sprint_field.get("id"):
                raise Objective4BError(
                    "Jira ya no publico el campo Sprint para AT / Task. Actualiza la prevalidacion."
                )
            sprint_resolution["field_id"] = str(sprint_field["id"])

        intent["real_execution"] = {
            "mode": "SINGLE_CONTROLLED_TASK",
            "confirmation_phrase": self.CONFIRMATION_PHRASE,
            "payload": {"tool": "createJiraIssue", "arguments": real_arguments},
            "payload_hash": _hash(real_arguments),
            "prepared_at": _iso(now),
            "confirmed_at": None,
            "submitted_at": None,
            "completed_at": None,
            "real_mcp_calls": 0,
            "automatic_retries": 0,
            "issue_key": None,
            "issue_url": None,
            "result": None,
            "error": None,
            "readback": None,
            "sprint_resolution": sprint_resolution,
            "sprint_revalidated_at": None,
        }
        intent["real_confirmation"] = {
            "expires_at": _iso(now + self.CONFIRMATION_TTL),
            "confirmed_at": None,
            "confirmed_by": None,
        }
        intent["audit"].append(self._audit("REAL_PREPARED", username, now, "REAL_WRITE_PREPARED"))
        updated = self.repository.update_execution_intent(intent)
        return {**updated, "reused": False}

    def confirm(
        self,
        execution_id: str,
        payload_hash: str,
        confirmation_phrase: str,
        username: str,
    ) -> dict[str, Any]:
        intent = self._owned(execution_id, username)
        if intent["status"] != "REAL_PREPARED":
            raise Objective4BError("El envio real ya no espera confirmacion.")
        self._assert_not_expired(intent)
        self._current_documents(intent)
        real = intent["real_execution"]
        if payload_hash != real["payload_hash"]:
            raise Objective4BError("El payload real cambio; prepara nuevamente el envio.")
        if confirmation_phrase.strip().upper() != self.CONFIRMATION_PHRASE:
            raise Objective4BError("La frase de confirmacion no coincide.")
        now = self.now()
        intent["status"] = "REAL_CONFIRMED"
        intent["updated_at"] = _iso(now)
        intent["real_confirmation"]["confirmed_at"] = _iso(now)
        intent["real_confirmation"]["confirmed_by"] = username
        intent["real_execution"]["confirmed_at"] = _iso(now)
        intent["audit"].append(self._audit("REAL_CONFIRMED", username, now, "REAL_WRITE_CONFIRMED"))
        return self.repository.update_execution_intent(intent)

    async def execute(self, execution_id: str, username: str) -> dict[str, Any]:
        intent = self._owned(execution_id, username)
        if intent["status"] in self.TERMINAL_STATUSES:
            return {**intent, "reused": True}
        if intent["status"] != "REAL_CONFIRMED":
            raise Objective4BError("Confirma el envio real antes de crear la Task.")
        self._assert_not_expired(intent)
        proposal, dry_run, dry_item = self._current_documents(intent)
        real = intent["real_execution"]
        violations = self.policy.canary_gate_violations(
            space=dry_item.get("space"),
            work_type=dry_item.get("work_type"),
            item_count=1,
            tool_name="createJiraIssue",
            approved_version_current=proposal.get("status") == "APPROVED",
            dry_run_current=dry_run.get("dry_run_id") == intent.get("dry_run_id"),
            dry_run_blockers=dry_run.get("summary", {}).get("blocked", 0),
            exact_active_account=bool((dry_item.get("assignee") or {}).get("account_id")),
            assignee_in_atomic_create=bool(real["payload"]["arguments"].get("assignee_account_id")),
            second_confirmation=bool(intent["real_confirmation"].get("confirmed_at")),
        )
        if violations:
            raise Objective4BError("El kill switch bloqueo el envio: " + ", ".join(violations))

        sprint_resolution = real.get("sprint_resolution") or {}
        selected_sprint = sprint_resolution.get("selected") or {}
        if selected_sprint.get("id"):
            list_sprints = getattr(self.gateway, "list_sprints", None)
            if list_sprints is None:
                raise Objective4BError(
                    "No se puede revalidar el Sprint inmediatamente antes de escribir; no se creo ninguna actividad."
                )
            try:
                current_sprints = await list_sprints(
                    username,
                    str(dry_item.get("space") or "AT"),
                    force_refresh=True,
                )
            except Exception as exc:
                raise Objective4BError(
                    "No fue posible revalidar el Sprint contra Jira; no se creo ninguna actividad: "
                    + str(exc)[:300]
                ) from exc
            current = revalidate_sprint(str(selected_sprint["id"]), current_sprints)
            if current is None:
                raise Objective4BError(
                    f"El Sprint '{selected_sprint.get('name')}' ya no esta activo/futuro o dejo de ser visible. "
                    "Actualiza la prevalidacion antes de intentar el envio. No se creo ninguna actividad."
                )
            now = self.now()
            real["sprint_resolution"]["selected"] = current
            real["sprint_revalidated_at"] = _iso(now)
            intent["updated_at"] = _iso(now)
            intent["audit"].append(
                self._audit("REAL_CONFIRMED", username, now, "SPRINT_ID_AND_STATE_CONFIRMED")
            )
            self.repository.update_execution_intent(intent)

        now = self.now()
        intent["status"] = "SUBMITTED"
        intent["updated_at"] = _iso(now)
        real["submitted_at"] = _iso(now)
        intent["audit"].append(self._audit("SUBMITTED", username, now, "ONE_CREATE_CALL_SUBMITTED"))
        self.repository.update_execution_intent(intent)

        try:
            readback_fields = ["summary", "description", "issuetype", "assignee", "project", "labels"]
            sprint_field_id = (real.get("sprint_resolution") or {}).get("field_id")
            if sprint_field_id:
                readback_fields.append(str(sprint_field_id))
            gateway_result = await self.gateway.create_single_task_and_readback(
                username,
                copy.deepcopy(real["payload"]["arguments"]),
                readback_fields,
                int(self.policy.document["execution_timeout_seconds"]),
            )
        except Exception as exc:
            now = self.now()
            uncertain = bool(getattr(exc, "outcome_uncertain", False))
            intent["status"] = "UNKNOWN" if uncertain else "REJECTED"
            intent["updated_at"] = _iso(now)
            real["completed_at"] = _iso(now)
            real["real_mcp_calls"] = int(getattr(exc, "real_mcp_calls", 1))
            real["error"] = str(exc)[:700]
            real["result"] = "OUTCOME_UNKNOWN" if uncertain else "JIRA_REJECTED"
            intent["audit"].append(
                self._audit(intent["status"], username, now, real["result"], real["real_mcp_calls"])
            )
            return self.repository.update_execution_intent(intent)

        issue_key = gateway_result.get("issue_key")
        readback = gateway_result.get("readback")
        checks = self._readback_checks(
            readback,
            issue_key,
            real["payload"]["arguments"],
            real.get("sprint_resolution"),
        )
        verified = bool(issue_key) and all(checks.values())
        now = self.now()
        intent["status"] = "CREATED_VERIFIED" if verified else "CREATED_UNVERIFIED"
        intent["updated_at"] = _iso(now)
        real["completed_at"] = _iso(now)
        real["real_mcp_calls"] = int(gateway_result.get("real_mcp_calls", 2))
        real["issue_key"] = issue_key
        real["issue_url"] = (
            f"https://dpti.atlassian.net/browse/{issue_key}" if issue_key else None
        )
        real["result"] = "CREATED_AND_VERIFIED" if verified else "CREATED_READBACK_INCOMPLETE"
        real["readback"] = {"checks": checks, "payload": readback}
        intent["audit"].append(
            self._audit(intent["status"], username, now, real["result"], real["real_mcp_calls"])
        )
        return self.repository.update_execution_intent(intent)

    def _current_documents(self, intent: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        proposal = self.repository.get(intent["proposal_id"])
        dry_run = self.repository.get_latest_dry_run(intent["proposal_id"])
        if (
            proposal is None
            or proposal.get("version") != intent.get("proposal_version")
            or proposal.get("status") != "APPROVED"
            or dry_run is None
            or dry_run.get("dry_run_id") != intent.get("dry_run_id")
            or dry_run.get("summary", {}).get("blocked", 0) != 0
        ):
            raise Objective4BError("La propuesta o su prevalidacion cambiaron; no se permite escribir.")
        item = next(
            (entry for entry in dry_run.get("items", []) if entry.get("row_id") == intent.get("row_id")),
            None,
        )
        if item is None:
            raise Objective4BError("La actividad ya no pertenece a la prevalidacion vigente.")
        return proposal, dry_run, item

    def _owned(self, execution_id: str, username: str) -> dict[str, Any]:
        intent = self.repository.get_execution_intent(execution_id)
        if intent is None:
            raise Objective4BError("No existe la ejecucion solicitada.")
        if intent.get("created_by") != username:
            raise Objective4BError("La ejecucion pertenece a otro usuario.")
        return intent

    def _assert_not_expired(self, intent: dict[str, Any]) -> None:
        confirmation = intent.get("real_confirmation") or {}
        if self.now() > _parse_iso(confirmation.get("expires_at", "1970-01-01T00:00:00Z")):
            raise Objective4BError("La confirmacion real caduco; prepara nuevamente el envio.")

    @staticmethod
    def _sprint_field(
        snapshot: dict[str, Any],
        space_key: str = "AT",
        work_type_name: str = "Task",
    ) -> dict[str, Any] | None:
        for space in snapshot.get("spaces", []):
            if space.get("key") != space_key:
                continue
            for work_type in space.get("work_types", []):
                expected = {_normalize(work_type_name)}
                if _normalize(work_type_name) == "task":
                    expected.add("tarea")
                if _normalize(work_type.get("name")) not in expected:
                    continue
                return next(
                    (
                        field
                        for field in work_type.get("fields", [])
                        if _normalize(field.get("business_key") or field.get("name")) == "sprint"
                    ),
                    None,
                )
        return None

    @staticmethod
    def _additional_fields(
        raw_fields: dict[str, Any],
        snapshot: dict[str, Any],
        space_key: str = "AT",
        work_type_name: str = "Task",
    ) -> dict[str, Any]:
        blocked = {"project", "issuetype", "summary", "description", "assignee", "reporter", "parent"}
        metadata: dict[str, dict[str, Any]] = {}
        for space in snapshot.get("spaces", []):
            if space.get("key") != space_key:
                continue
            for work_type in space.get("work_types", []):
                expected = {_normalize(work_type_name)}
                if _normalize(work_type_name) == "task":
                    expected.add("tarea")
                if _normalize(work_type.get("name")) not in expected:
                    continue
                metadata.update({str(field.get("id")): field for field in work_type.get("fields", []) if field.get("id")})
        result: dict[str, Any] = {}
        for field_id, value in raw_fields.items():
            if _normalize(field_id).replace(" ", "") in blocked or value is None or value == "":
                continue
            field = metadata.get(str(field_id), {})
            selected = next(
                (
                    option
                    for option in field.get("options", [])
                    if _normalize(option.get("value") or option.get("label")) == _normalize(value)
                ),
                None,
            )
            is_sprint = _normalize(field.get("business_key") or field.get("name")) == "sprint"
            if is_sprint:
                sprint_id = selected.get("jira_id") if selected else value
                if not str(sprint_id or "").strip().isdigit():
                    raise Objective4BError(
                        f"El Sprint '{value}' no tiene un ID numerico verificable. "
                        "Actualiza la prevalidacion para resolver nuevamente su nombre contra Jira."
                    )
                result[str(field_id)] = int(str(sprint_id).strip())
            else:
                result[str(field_id)] = (
                    {"id": selected["jira_id"]}
                    if selected and selected.get("jira_id")
                    else value
                )
        return result

    @staticmethod
    def _readback_checks(
        payload: Any,
        issue_key: str | None,
        arguments: dict[str, Any],
        sprint_resolution: dict[str, Any] | None = None,
    ) -> dict[str, bool]:
        issue = _nested_issue(payload)
        if issue is None:
            checks = {
                "issue_key": bool(issue_key),
                "summary": False,
                "space": False,
                "work_type": False,
                "assignee": False,
            }
            if (sprint_resolution or {}).get("selected"):
                checks["sprint"] = False
            if ((arguments.get("additional_fields") or {}).get("parent") or {}).get("key"):
                checks["parent"] = False
            return checks
        fields = issue.get("fields") or {}
        project = fields.get("project") or {}
        issue_type = fields.get("issuetype") or {}
        assignee = fields.get("assignee") or {}
        checks = {
            "issue_key": _normalize(issue.get("key")) == _normalize(issue_key),
            "summary": fields.get("summary") == arguments.get("summary"),
            "space": _normalize(project.get("key")) == _normalize(arguments.get("projectKey")),
            "work_type": (
                _normalize(issue_type.get("name")) == _normalize(arguments.get("issueTypeName"))
                or (
                    _normalize(arguments.get("issueTypeName")) == "task"
                    and _normalize(issue_type.get("name")) == "tarea"
                )
            ),
            "assignee": str(assignee.get("accountId") or assignee.get("account_id") or "")
            == str(arguments.get("assignee_account_id") or ""),
        }
        selected_sprint = (sprint_resolution or {}).get("selected") or {}
        sprint_field_id = (sprint_resolution or {}).get("field_id")
        if selected_sprint.get("id") and sprint_field_id:
            checks["sprint"] = _contains_sprint_id(
                fields.get(str(sprint_field_id)),
                str(selected_sprint["id"]),
            )
        expected_parent = ((arguments.get("additional_fields") or {}).get("parent") or {}).get("key")
        if expected_parent:
            parent = fields.get("parent") or {}
            checks["parent"] = _normalize(parent.get("key")) == _normalize(expected_parent)
        return checks

    @staticmethod
    def _audit(
        state: str,
        username: str,
        at: datetime,
        event: str,
        real_mcp_calls: int = 0,
    ) -> dict[str, Any]:
        return {
            "state": state,
            "event": event,
            "at": _iso(at),
            "by": username,
            "real_mcp_calls": real_mcp_calls,
            "write_performed": state in {"CREATED_VERIFIED", "CREATED_UNVERIFIED"},
        }
