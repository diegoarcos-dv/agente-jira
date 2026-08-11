from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


class ExecutionPolicyError(RuntimeError):
    """Raised when the Jira execution policy is invalid or unsafe."""


@dataclass(frozen=True)
class JiraExecutionPolicy:
    document: dict[str, Any]
    path: Path

    @property
    def mode(self) -> str:
        return str(self.document["mode"])

    @property
    def jira_write_enabled(self) -> bool:
        return bool(self.document["jira_write_enabled"])

    @property
    def required_write_tool(self) -> str:
        return str(self.document["required_write_tool"])

    def public_summary(self) -> dict[str, Any]:
        """Return only non-secret controls suitable for diagnostics and UI."""

        keys = (
            "policy_version",
            "mode",
            "jira_write_enabled",
            "allowed_spaces",
            "allowed_work_types",
            "max_items_per_execution",
            "title_prefix",
            "required_write_tool",
            "blocked_write_tools",
            "automatic_retry",
            "allowed_environment",
        )
        return {key: self.document[key] for key in keys}

    def planning_readiness(self) -> list[str]:
        """Return violations of the safe Objective 4A preparation state."""

        violations: list[str] = []
        if self.mode != "PLANNING_ONLY":
            violations.append("POLICY_NOT_PLANNING_ONLY")
        if self.jira_write_enabled:
            violations.append("JIRA_WRITE_MUST_REMAIN_DISABLED")
        if self.document["automatic_retry"]:
            violations.append("AUTOMATIC_RETRY_MUST_REMAIN_DISABLED")
        return violations

    def simulation_readiness(self) -> list[str]:
        """Validate that the local-only simulator remains safe in either supported mode."""

        violations: list[str] = []
        if self.mode not in {"PLANNING_ONLY", "SINGLE_CANARY", "CONTROLLED_BATCH", "CONTROLLED_MULTI_TYPE_BATCH", "CONTROLLED_HIERARCHY_BATCH"}:
            violations.append("POLICY_MODE_UNSUPPORTED_FOR_SIMULATION")
        if self.mode == "PLANNING_ONLY" and self.jira_write_enabled:
            violations.append("PLANNING_POLICY_CANNOT_WRITE")
        if self.mode == "SINGLE_CANARY" and not self.jira_write_enabled:
            violations.append("CONTROLLED_WRITE_POLICY_INCONSISTENT")
        if self.mode == "CONTROLLED_BATCH" and not self.jira_write_enabled:
            violations.append("CONTROLLED_BATCH_POLICY_INCONSISTENT")
        if self.mode == "CONTROLLED_MULTI_TYPE_BATCH" and not self.jira_write_enabled:
            violations.append("CONTROLLED_MULTI_TYPE_BATCH_POLICY_INCONSISTENT")
        if self.mode == "CONTROLLED_HIERARCHY_BATCH" and not self.jira_write_enabled:
            violations.append("CONTROLLED_HIERARCHY_BATCH_POLICY_INCONSISTENT")
        if self.document["automatic_retry"]:
            violations.append("AUTOMATIC_RETRY_MUST_REMAIN_DISABLED")
        return violations

    def canary_gate_violations(
        self,
        *,
        space: str,
        work_type: str,
        item_count: int,
        tool_name: str,
        approved_version_current: bool,
        dry_run_current: bool,
        dry_run_blockers: int,
        exact_active_account: bool,
        assignee_in_atomic_create: bool,
        second_confirmation: bool,
    ) -> list[str]:
        """Evaluate all gates without invoking Jira or any MCP tool."""

        checks = (
            (self.mode == "SINGLE_CANARY", "POLICY_MODE_BLOCKED"),
            (self.jira_write_enabled, "JIRA_WRITE_DISABLED"),
            (space in self.document["allowed_spaces"], "SPACE_NOT_ALLOWED"),
            (work_type in self.document["allowed_work_types"], "WORK_TYPE_NOT_ALLOWED"),
            (item_count == 1, "EXACTLY_ONE_ITEM_REQUIRED"),
            (
                item_count <= self.document["max_items_per_execution"],
                "EXECUTION_ITEM_LIMIT_EXCEEDED",
            ),
            (tool_name == self.required_write_tool, "WRITE_TOOL_NOT_ALLOWED"),
            (approved_version_current, "APPROVED_VERSION_NOT_CURRENT"),
            (dry_run_current, "DRY_RUN_NOT_CURRENT"),
            (dry_run_blockers == 0, "DRY_RUN_HAS_BLOCKERS"),
            (exact_active_account, "ATLASSIAN_ACCOUNT_NOT_CONFIRMED"),
            (assignee_in_atomic_create, "ASSIGNEE_NOT_IN_ATOMIC_CREATE"),
            (second_confirmation, "SECOND_CONFIRMATION_REQUIRED"),
        )
        return [code for condition, code in checks if not condition]

    def batch_gate_violations(
        self,
        *,
        spaces: set[str],
        work_types: set[str],
        item_count: int,
        tool_name: str,
        approved_version_current: bool,
        dry_run_current: bool,
        dry_run_blockers: int,
        all_accounts_confirmed: bool,
        assignees_in_atomic_create: bool,
        second_confirmation: bool,
    ) -> list[str]:
        checks = (
            (self.mode in {"CONTROLLED_BATCH", "CONTROLLED_MULTI_TYPE_BATCH", "CONTROLLED_HIERARCHY_BATCH"}, "POLICY_MODE_BLOCKED"),
            (self.jira_write_enabled, "JIRA_WRITE_DISABLED"),
            (bool(spaces) and spaces.issubset(set(self.document["allowed_spaces"])), "SPACE_NOT_ALLOWED"),
            (bool(work_types) and work_types.issubset(set(self.document["allowed_work_types"])), "WORK_TYPE_NOT_ALLOWED"),
            (item_count >= 1, "AT_LEAST_ONE_ITEM_REQUIRED"),
            (item_count <= self.document["max_items_per_execution"], "EXECUTION_ITEM_LIMIT_EXCEEDED"),
            (tool_name == self.required_write_tool, "WRITE_TOOL_NOT_ALLOWED"),
            (approved_version_current, "APPROVED_VERSION_NOT_CURRENT"),
            (dry_run_current, "DRY_RUN_NOT_CURRENT"),
            (dry_run_blockers == 0, "DRY_RUN_HAS_BLOCKERS"),
            (all_accounts_confirmed, "ATLASSIAN_ACCOUNT_NOT_CONFIRMED"),
            (assignees_in_atomic_create, "ASSIGNEE_NOT_IN_ATOMIC_CREATE"),
            (second_confirmation, "SECOND_CONFIRMATION_REQUIRED"),
            (not self.document["automatic_retry"], "AUTOMATIC_RETRY_MUST_REMAIN_DISABLED"),
        )
        return [code for condition, code in checks if not condition]


def load_execution_policy(policy_path: Path, schema_path: Path) -> JiraExecutionPolicy:
    try:
        document = json.loads(policy_path.read_text(encoding="utf-8"))
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExecutionPolicyError(f"No fue posible leer la politica Jira: {exc}") from exc

    errors = sorted(
        Draft202012Validator(schema).iter_errors(document),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        details = "; ".join(error.message for error in errors)
        raise ExecutionPolicyError(f"La politica Jira no cumple su esquema: {details}")

    policy = JiraExecutionPolicy(document=document, path=policy_path)
    if document["mode"] == "PLANNING_ONLY" and document["jira_write_enabled"]:
        raise ExecutionPolicyError(
            "Una politica PLANNING_ONLY no puede habilitar escrituras en Jira."
        )
    return policy
