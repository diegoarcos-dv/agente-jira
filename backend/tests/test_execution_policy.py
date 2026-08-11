from __future__ import annotations

import json

import pytest

from app.execution_policy import ExecutionPolicyError, load_execution_policy


def test_frozen_policy_is_valid_and_keeps_jira_write_disabled(client):
    settings = client.app.state.settings
    policy = load_execution_policy(
        settings.jira_execution_policy_path,
        settings.jira_execution_policy_schema_path,
    )

    assert policy.mode == "PLANNING_ONLY"
    assert policy.jira_write_enabled is False
    assert policy.planning_readiness() == []
    assert policy.simulation_readiness() == []


def test_controlled_write_policy_still_allows_the_local_only_simulator(client):
    settings = client.app.state.settings
    policy = load_execution_policy(
        settings.jira_execution_policy_path.parent / "jira_execution_policy_4b.json",
        settings.jira_execution_policy_schema_path,
    )

    assert policy.jira_write_enabled is True
    assert policy.planning_readiness() != []
    assert policy.simulation_readiness() == []


def test_controlled_batch_policy_is_bounded_to_five_tasks(client):
    settings = client.app.state.settings
    policy = load_execution_policy(
        settings.jira_execution_policy_path.parent / "jira_execution_policy_4c1.json",
        settings.jira_execution_policy_schema_path,
    )

    assert policy.mode == "CONTROLLED_BATCH"
    assert policy.document["max_items_per_execution"] == 5
    assert policy.simulation_readiness() == []
    assert policy.batch_gate_violations(
        spaces={"AT"},
        work_types={"Task"},
        item_count=5,
        tool_name="createJiraIssue",
        approved_version_current=True,
        dry_run_current=True,
        dry_run_blockers=0,
        all_accounts_confirmed=True,
        assignees_in_atomic_create=True,
        second_confirmation=True,
    ) == []


def test_multi_type_policy_allows_only_task_bug_and_story(client):
    settings = client.app.state.settings
    policy = load_execution_policy(
        settings.jira_execution_policy_path.parent / "jira_execution_policy_4d.json",
        settings.jira_execution_policy_schema_path,
    )

    assert policy.mode == "CONTROLLED_MULTI_TYPE_BATCH"
    assert policy.document["allowed_work_types"] == ["Task", "Bug", "Story"]
    assert policy.simulation_readiness() == []
    assert policy.batch_gate_violations(
        spaces={"AT"}, work_types={"Task", "Bug", "Story"}, item_count=3,
        tool_name="createJiraIssue", approved_version_current=True,
        dry_run_current=True, dry_run_blockers=0, all_accounts_confirmed=True,
        assignees_in_atomic_create=True, second_confirmation=True,
    ) == []
    assert "WORK_TYPE_NOT_ALLOWED" in policy.batch_gate_violations(
        spaces={"AT"}, work_types={"Epic"}, item_count=1,
        tool_name="createJiraIssue", approved_version_current=True,
        dry_run_current=True, dry_run_blockers=0, all_accounts_confirmed=True,
        assignees_in_atomic_create=True, second_confirmation=True,
    )


def test_hierarchy_policy_is_bounded_and_explicitly_allows_epic_and_subtask(client):
    settings = client.app.state.settings
    policy = load_execution_policy(
        settings.jira_execution_policy_path.parent / "jira_execution_policy_4e.json",
        settings.jira_execution_policy_schema_path,
    )

    assert policy.mode == "CONTROLLED_HIERARCHY_BATCH"
    assert policy.document["allowed_work_types"] == ["Task", "Bug", "Story", "Epic", "Subtask"]
    assert policy.document["max_items_per_execution"] == 5
    assert policy.document["automatic_retry"] is False
    assert policy.simulation_readiness() == []
    assert policy.batch_gate_violations(
        spaces={"AT"}, work_types={"Epic", "Story", "Task", "Subtask"}, item_count=4,
        tool_name="createJiraIssue", approved_version_current=True,
        dry_run_current=True, dry_run_blockers=0, all_accounts_confirmed=True,
        assignees_in_atomic_create=True, second_confirmation=True,
    ) == []


def test_planning_only_policy_cannot_enable_write(client, tmp_path):
    settings = client.app.state.settings
    document = json.loads(settings.jira_execution_policy_path.read_text(encoding="utf-8"))
    document["jira_write_enabled"] = True
    unsafe_path = tmp_path / "unsafe-policy.json"
    unsafe_path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ExecutionPolicyError, match="PLANNING_ONLY"):
        load_execution_policy(unsafe_path, settings.jira_execution_policy_schema_path)


def test_canary_gates_reject_every_unsafe_input(client):
    policy = client.app.state.jira_execution_policy

    violations = policy.canary_gate_violations(
        space="ASIT",
        work_type="Bug",
        item_count=2,
        tool_name="editJiraIssue",
        approved_version_current=False,
        dry_run_current=False,
        dry_run_blockers=3,
        exact_active_account=False,
        assignee_in_atomic_create=False,
        second_confirmation=False,
    )

    assert "POLICY_MODE_BLOCKED" in violations
    assert "JIRA_WRITE_DISABLED" in violations
    assert "SPACE_NOT_ALLOWED" in violations
    assert "WORK_TYPE_NOT_ALLOWED" in violations
    assert "EXACTLY_ONE_ITEM_REQUIRED" in violations
    assert "WRITE_TOOL_NOT_ALLOWED" in violations
    assert "SECOND_CONFIRMATION_REQUIRED" in violations


def test_objective_4_readiness_is_authenticated_and_never_enables_write(
    client,
    auth_headers,
):
    unauthorized = client.get("/api/objectives/4/readiness")
    assert unauthorized.status_code == 401

    response = client.get("/api/objectives/4/readiness", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["objective"] == "4A"
    assert body["status"] == "READY_FOR_SIMULATION"
    assert body["jira_write_enabled"] is False
    assert body["policy"]["mode"] == "PLANNING_ONLY"
    assert body["policy"]["automatic_retry"] is False
    assert body["mcp_tools"]["inspection_only"] is True
    assert body["mcp_tools"]["tools_invoked"] == 0
    assert body["simulation_only"] is True
    assert body["real_canary_ready"] is False
