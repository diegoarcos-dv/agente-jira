from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any, Protocol


class ControlledJiraGateway(Protocol):
    async def create_single_task_and_readback(
        self,
        username: str,
        create_arguments: dict[str, Any],
        readback_fields: list[str],
        timeout_seconds: int,
    ) -> dict[str, Any]: ...


def canonical_hash(value: Any) -> str:
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
        found = _nested_issue(payload.get(key))
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


def _option_matches(actual: Any, expected: dict[str, Any]) -> bool:
    if not isinstance(actual, dict):
        return _normalize(actual) in {
            _normalize(expected.get("id")),
            _normalize(expected.get("name")),
            _normalize(expected.get("value")),
        }
    actual_id = actual.get("id") or actual.get("jira_id")
    actual_name = actual.get("name") or actual.get("value") or actual.get("label")
    expected_id = expected.get("id") or expected.get("jira_id")
    expected_name = expected.get("name") or expected.get("value") or expected.get("label")
    return bool(
        (expected_id and str(actual_id or "") == str(expected_id))
        or (expected_name and _normalize(actual_name) == _normalize(expected_name))
    )


def readback_checks(
    payload: Any,
    issue_key: str | None,
    arguments: dict[str, Any],
    sprint_resolution: dict[str, Any] | None = None,
    expected_fields: dict[str, Any] | None = None,
) -> dict[str, bool]:
    expected_fields = expected_fields or {}
    issue = _nested_issue(payload)
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
    if expected_fields.get("priority"):
        checks["priority"] = False
    if issue is None:
        return checks

    fields = issue.get("fields") or {}
    project = fields.get("project") or {}
    issue_type = fields.get("issuetype") or {}
    assignee = fields.get("assignee") or {}
    checks.update(
        {
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
    )
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
    priority = expected_fields.get("priority")
    if isinstance(priority, dict):
        field_id = str(priority.get("field_id") or "priority")
        checks["priority"] = _option_matches(fields.get(field_id) or fields.get("priority"), priority)
    return checks


class ControlledJiraCreateCore:
    """The only application core allowed to invoke createJiraIssue and verify its result."""

    def __init__(self, gateway: ControlledJiraGateway):
        self.gateway = gateway

    @staticmethod
    def validate_tool_contract(
        tool_readiness: dict[str, Any],
        *,
        require_additional_fields: bool = False,
    ) -> list[str]:
        create_tool = tool_readiness.get("create") or {}
        readback_tool = tool_readiness.get("readback") or {}
        errors: list[str] = []
        if not create_tool.get("exposed") or not readback_tool.get("exposed"):
            errors.append("Rovo debe exponer createJiraIssue y getJiraIssue.")
            return errors
        create_schema = create_tool.get("input_schema") or {}
        readback_schema = readback_tool.get("input_schema") or {}
        if not {"cloudId", "projectKey", "issueTypeName", "summary"}.issubset(
            set(create_schema.get("required") or [])
        ):
            errors.append("El contrato anunciado de createJiraIssue no es compatible.")
        properties = set((create_schema.get("properties") or {}).keys())
        if require_additional_fields and "additional_fields" not in properties:
            errors.append("createJiraIssue no expone additional_fields.")
        if not {"cloudId", "issueIdOrKey"}.issubset(
            set(readback_schema.get("required") or [])
        ):
            errors.append("El contrato anunciado de getJiraIssue no es compatible.")
        return errors

    async def create_and_verify(
        self,
        username: str,
        create_arguments: dict[str, Any],
        readback_fields: list[str],
        timeout_seconds: int,
        *,
        sprint_resolution: dict[str, Any] | None = None,
        expected_fields: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        gateway_result = await self.gateway.create_single_task_and_readback(
            username,
            copy.deepcopy(create_arguments),
            list(readback_fields),
            timeout_seconds,
        )
        issue_key = gateway_result.get("issue_key")
        checks = readback_checks(
            gateway_result.get("readback"),
            issue_key,
            create_arguments,
            sprint_resolution,
            expected_fields,
        )
        verified = bool(issue_key) and all(checks.values())
        return {
            "status": "CREATED_VERIFIED" if verified else "CREATED_UNVERIFIED",
            "issue_key": issue_key,
            "verified": verified,
            "checks": checks,
            "readback": gateway_result.get("readback"),
            "readback_error": gateway_result.get("readback_error"),
            "real_mcp_calls": int(gateway_result.get("real_mcp_calls", 2)),
            "create_elapsed_ms": gateway_result.get("create_elapsed_ms"),
            "readback_elapsed_ms": gateway_result.get("readback_elapsed_ms"),
        }
