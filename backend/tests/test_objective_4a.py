from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.execution_policy import load_execution_policy
from app.main import create_app
from app.objective_4a import (
    JiraExecutionPreparationService,
    Objective4AError,
    SimulatedJiraCreateGateway,
)
from app.repository import ProposalRepository
from tests.test_dry_run import FakeJiraReadGateway, approved_proposal


PROJECT_DIR = Path(__file__).resolve().parents[2]
POLICY = PROJECT_DIR / "config" / "jira_execution_policy_v1.json"
POLICY_4B = PROJECT_DIR / "config" / "jira_execution_policy_4b.json"
POLICY_SCHEMA = PROJECT_DIR / "docs" / "schemas" / "jira_execution_policy_v1.schema.json"


def ready_dry_run(proposal: dict, *, status: str = "READY") -> dict:
    generated = proposal["items"][0]["generated"]
    warning = []
    if status == "READY_WITH_WARNINGS":
        warning = [{
            "code": "ASSIGNEE_ASSIGNABILITY_UNVERIFIED",
            "field": "assignee",
            "message": "Cuenta exacta; asignabilidad se comprobara en la operacion atomica.",
        }]
    blocked = 1 if status == "BLOCKED" else 0
    return {
        "dry_run_id": "DRY-" + "d" * 32,
        "proposal_id": proposal["proposal_id"],
        "proposal_version": proposal["version"],
        "proposal_hash": "p" * 64,
        "generated_at": "2026-07-20T15:00:00Z",
        "generated_by": "admin@agentejira.local",
        "jira_snapshot_verified_at": "2026-07-20T14:59:00Z",
        "site_url": "https://dpti.atlassian.net",
        "status": status,
        "summary": {
            "ready": 0 if status != "READY" else 1,
            "ready_with_warnings": 1 if status == "READY_WITH_WARNINGS" else 0,
            "blocked": blocked,
            "skipped": 1,
        },
        "items": [{
            "row_id": generated["row_id"],
            "source_row": 6,
            "status": status,
            "title": generated["title"],
            "space": generated["space"],
            "work_type": generated["work_type"],
            "errors": ([{"code": "TEST_BLOCK", "field": "test", "message": "Bloqueo"}]
                       if blocked else []),
            "warnings": warning,
            "target": {
                "project_name": "AT",
                "project_type": "software",
                "jira_work_type": "Task",
                "required_field_count": 3,
            },
            "assignee": {
                "display_name": "Jose Calleja",
                "email": "jose@example.com",
                "account_id": "jira-jose",
                "validation": "JIRA_ACCOUNT_MATCH",
            },
            "logical_payload": {
                "project_key": "AT",
                "project_id": "100",
                "work_type": "Task",
                "work_type_id": "10",
                "summary": generated["title"],
                "description": generated["description"],
                "assignee_account_id": "jira-jose",
                "parent_row_id": None,
                "jira_fields": {
                    "summary": generated["title"],
                    "description": generated["description"],
                    "assignee": "jira-jose",
                },
            },
            "idempotency_key": "AJI-" + "a" * 32,
        }],
        "write_performed": False,
    }


def snapshot() -> dict:
    return {
        "cloud_id": "cloud-123",
        "site_url": "https://dpti.atlassian.net",
        "atlassian_user": {"account_id": "reporter-1", "display_name": "Jose"},
    }


def service_fixture(tmp_path: Path, now: list[datetime]):
    repository = ProposalRepository(tmp_path / "objective-4a.db")
    proposal = approved_proposal()
    dry_run = ready_dry_run(proposal, status="READY_WITH_WARNINGS")
    repository.save(proposal)
    repository.save_dry_run(dry_run)
    simulator = SimulatedJiraCreateGateway()
    service = JiraExecutionPreparationService(
        repository,
        load_execution_policy(POLICY, POLICY_SCHEMA),
        simulator,
        now=lambda: now[0],
    )
    return repository, proposal, dry_run, simulator, service


def test_prepare_confirm_and_simulate_never_reaches_mcp_or_jira(tmp_path: Path):
    now = [datetime(2026, 7, 20, 16, 0, tzinfo=UTC)]
    repository, proposal, dry_run, simulator, service = service_fixture(tmp_path, now)

    prepared = service.prepare(
        proposal,
        dry_run,
        "ROW-0006",
        "admin@agentejira.local",
        snapshot(),
    )
    confirmed = service.confirm(
        prepared["execution_id"],
        prepared["payload_hash"],
        "admin@agentejira.local",
    )
    simulated = service.simulate(
        prepared["execution_id"],
        "admin@agentejira.local",
    )

    assert prepared["status"] == "PREPARED"
    assert confirmed["status"] == "CONFIRMED"
    assert simulated["status"] == "SIMULATED"
    assert simulated["preview"]["title"].startswith("AgenteTest_Task_")
    assert simulated["simulation"]["simulated_calls"] == 1
    assert simulated["simulation"]["real_mcp_calls"] == 0
    assert simulated["simulation"]["write_performed"] is False
    assert simulated["simulation"]["result"]["jira_issue_created"] is False
    assert len(simulator.calls) == 1
    assert repository.get_execution_intent(prepared["execution_id"])["status"] == "SIMULATED"


def test_local_simulation_remains_available_while_controlled_4b_policy_is_active(tmp_path: Path):
    now = [datetime(2026, 7, 20, 16, 0, tzinfo=UTC)]
    repository = ProposalRepository(tmp_path / "objective-4a-under-4b.db")
    proposal = approved_proposal()
    dry_run = ready_dry_run(proposal, status="READY")
    repository.save(proposal)
    repository.save_dry_run(dry_run)
    simulator = SimulatedJiraCreateGateway()
    service = JiraExecutionPreparationService(
        repository,
        load_execution_policy(POLICY_4B, POLICY_SCHEMA),
        simulator,
        now=lambda: now[0],
    )

    prepared = service.prepare(proposal, dry_run, "ROW-0006", "admin@agentejira.local", snapshot())
    service.confirm(prepared["execution_id"], prepared["payload_hash"], "admin@agentejira.local")
    result = service.simulate(prepared["execution_id"], "admin@agentejira.local")

    assert result["status"] == "SIMULATED"
    assert result["simulation"]["real_mcp_calls"] == 0
    assert result["simulation"]["write_performed"] is False
    assert len(simulator.calls) == 1


def test_changed_hash_invalidates_confirmation_and_makes_zero_simulator_calls(tmp_path: Path):
    now = [datetime(2026, 7, 20, 16, 0, tzinfo=UTC)]
    repository, proposal, dry_run, simulator, service = service_fixture(tmp_path, now)
    prepared = service.prepare(
        proposal, dry_run, "ROW-0006", "admin@agentejira.local", snapshot()
    )

    with pytest.raises(Objective4AError, match="vista previa cambio"):
        service.confirm(
            prepared["execution_id"],
            "0" * 64,
            "admin@agentejira.local",
        )

    stored = repository.get_execution_intent(prepared["execution_id"])
    assert stored["status"] == "INVALIDATED"
    assert simulator.calls == []


def test_confirmation_expires_and_can_be_prepared_again(tmp_path: Path):
    now = [datetime(2026, 7, 20, 16, 0, tzinfo=UTC)]
    _, proposal, dry_run, simulator, service = service_fixture(tmp_path, now)
    prepared = service.prepare(
        proposal, dry_run, "ROW-0006", "admin@agentejira.local", snapshot()
    )
    now[0] += timedelta(minutes=16)

    with pytest.raises(Objective4AError, match="caduco"):
        service.confirm(
            prepared["execution_id"],
            prepared["payload_hash"],
            "admin@agentejira.local",
        )

    rearmed = service.prepare(
        proposal, dry_run, "ROW-0006", "admin@agentejira.local", snapshot()
    )
    assert rearmed["status"] == "PREPARED"
    assert rearmed["reused"] is True
    assert simulator.calls == []


def test_changed_proposal_invalidates_prepared_intent(tmp_path: Path):
    now = [datetime(2026, 7, 20, 16, 0, tzinfo=UTC)]
    repository, proposal, dry_run, simulator, service = service_fixture(tmp_path, now)
    prepared = service.prepare(
        proposal, dry_run, "ROW-0006", "admin@agentejira.local", snapshot()
    )
    changed = copy.deepcopy(proposal)
    changed["version"] += 1
    changed["status"] = "DRAFT"
    repository.save(changed)

    with pytest.raises(Objective4AError, match="cambiaron"):
        service.confirm(
            prepared["execution_id"],
            prepared["payload_hash"],
            "admin@agentejira.local",
        )

    stored = repository.get_execution_intent(prepared["execution_id"])
    assert stored["status"] == "INVALIDATED"
    assert stored["audit"][-1]["event"] == "PROPOSAL_OR_DRY_RUN_CHANGED"
    assert simulator.calls == []


def test_prepare_rejects_blocked_dry_run_and_non_task(tmp_path: Path):
    now = [datetime(2026, 7, 20, 16, 0, tzinfo=UTC)]
    _, proposal, _, simulator, service = service_fixture(tmp_path, now)
    blocked = ready_dry_run(proposal, status="BLOCKED")
    with pytest.raises(Objective4AError, match="bloqueos"):
        service.prepare(
            proposal, blocked, "ROW-0006", "admin@agentejira.local", snapshot()
        )

    non_task = ready_dry_run(proposal)
    non_task["items"][0]["work_type"] = "Bug"
    with pytest.raises(Objective4AError, match="Task"):
        service.prepare(
            proposal, non_task, "ROW-0006", "admin@agentejira.local", snapshot()
        )
    assert simulator.calls == []


def test_objective_4a_api_flow_and_evidence_are_simulation_only(tmp_path: Path):
    settings = Settings(
        database_path=tmp_path / "api-4a.db",
        schema_path=PROJECT_DIR / "docs" / "schemas" / "jira_proposal_v1_1.schema.json",
        frontend_dist=tmp_path / "dist",
        frozen_template_path=(
            PROJECT_DIR / "releases" / "plantilla_excel_v1_1"
            / "plantilla_plan_trabajo_jira_v1_1.xlsx"
        ),
        local_user="admin@agentejira.local",
        local_password="AgenteJira2026!",
    )
    gateway = FakeJiraReadGateway()
    proposal = approved_proposal()
    dry_run = ready_dry_run(proposal)

    with TestClient(create_app(settings, atlassian_manager=gateway)) as client:
        repository = client.app.state.proposal_service.repository
        repository.save(proposal)
        repository.save_dry_run(dry_run)
        login = client.post(
            "/api/auth/login",
            json={"username": settings.local_user, "password": settings.local_password},
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        prepared_response = client.post(
            f"/api/proposals/{proposal['proposal_id']}/objective-4a/prepare",
            headers=headers,
            json={"row_id": "ROW-0006"},
        )
        assert prepared_response.status_code == 200, prepared_response.text
        prepared = prepared_response.json()
        confirmed = client.post(
            f"/api/objectives/4a/executions/{prepared['execution_id']}/confirm",
            headers=headers,
            json={"payload_hash": prepared["payload_hash"], "confirmed": True},
        )
        assert confirmed.status_code == 200, confirmed.text
        simulated = client.post(
            f"/api/objectives/4a/executions/{prepared['execution_id']}/simulate",
            headers=headers,
        )
        assert simulated.status_code == 200, simulated.text
        assert simulated.json()["simulation"]["real_mcp_calls"] == 0
        assert simulated.json()["simulation"]["write_performed"] is False
        assert len(client.app.state.jira_simulator.calls) == 1

        evidence = client.get(
            f"/api/objectives/4a/executions/{prepared['execution_id']}/evidence",
            headers=headers,
        )
        assert evidence.status_code == 200
        assert evidence.json()["mode"] == "SIMULATION_ONLY"
        assert evidence.json()["write_performed"] is False
        assert evidence.json()["execution"]["status"] == "SIMULATED"
