from __future__ import annotations

import asyncio
import copy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.dry_run import JiraDryRunService
from app.errors import ProposalStateError
from app.main import create_app
from app.repository import ProposalRepository


class FakeJiraReadGateway:
    def __init__(self):
        self.calls: list[tuple[str, str, str]] = []

    def connected_snapshot(self, _username: str):
        return {
            "verified_at": "2026-07-17T14:00:00Z",
            "site_url": "https://dpti.atlassian.net",
            "atlassian_user": {"account_id": "reporter-1"},
            "spaces": [
                {
                    "key": "AT",
                    "found": True,
                    "id": "100",
                    "name": "AT",
                    "project_type": "software",
                    "work_types": [
                        {
                            "id": "10",
                            "name": "Task",
                            "subtask": False,
                            "fields": [
                                {"id": "project", "name": "Project", "required": True},
                                {"id": "reporter", "name": "Reporter", "required": True},
                                {"id": "summary", "name": "Summary", "required": True},
                                {"id": "description", "name": "Description", "required": False},
                                {"id": "assignee", "name": "Assignee", "required": False},
                                {
                                    "id": "customfield_10483",
                                    "name": "Tipo de seguimiento",
                                    "required": False,
                                    "business_key": "tipo_seguimiento",
                                    "options": [
                                        {"value": "Semanal", "label": "Semanal"},
                                        {"value": "Mensual", "label": "Mensual"},
                                    ],
                                },
                            ],
                        },
                        {
                            "id": "11",
                            "name": "Subtarea",
                            "subtask": True,
                            "fields": [],
                        },
                    ],
                }
            ],
        }

    async def find_assignees(self, username: str, space: str, query: str):
        self.calls.append((username, space, query))
        return [
            {
                "account_id": "jira-jose",
                "display_name": "José Calleja",
                "email": "jose.calleja@empresa.test",
                "active": True,
                "capability": "findAssignableUsers",
            }
        ]


def approved_proposal(work_type: str = "Task"):
    return {
        "proposal_id": "11111111-1111-4111-8111-111111111111",
        "version": 4,
        "template_version": "1.1",
        "status": "APPROVED",
        "source_file": {"name": "plan.xlsx", "sha256": "a" * 64},
        "defaults": {"space": "AT"},
        "items": [
            {
                "source": {"source_row": 6},
                "generated": {
                    "row_id": "ROW-0006",
                    "decision": "INCLUIR",
                    "work_type": work_type,
                    "title": "Validar integración",
                    "description": "Validar el contrato de integración.",
                    "space": "AT",
                    "parent_row_id": None,
                    "assignee": {
                        "display_name": "José Calleja",
                        "email": "jose@example.com",
                        "account_id": "local-jose",
                    },
                    "fields": {
                        "tipo_seguimiento": "Semanal",
                        "due_date": "2026-08-15",
                        "iniciativa": "Piloto",
                        "linea_trabajo": None,
                        "sprint": None,
                        "semaforo": None,
                    },
                },
            },
            {
                "source": {"source_row": 7},
                "generated": {
                    "row_id": "ROW-0007",
                    "decision": "EXCLUIR",
                    "work_type": "Bug",
                    "title": "Actividad terminada",
                    "description": "No debe ejecutarse.",
                    "space": "AT",
                    "parent_row_id": None,
                    "assignee": {},
                    "fields": {},
                },
            },
        ],
        "created_at": "2026-07-17T13:00:00Z",
        "created_by": "tester",
        "approved_at": "2026-07-17T13:00:00Z",
        "approved_by": "tester",
    }


def test_dry_run_is_read_only_auditable_and_idempotent(tmp_path: Path):
    repository = ProposalRepository(tmp_path / "dry-run.db")
    gateway = FakeJiraReadGateway()
    service = JiraDryRunService(repository, gateway)
    proposal = approved_proposal()

    first = asyncio.run(service.generate(proposal, "admin@agentejira.local"))
    second = asyncio.run(service.generate(proposal, "admin@agentejira.local"))

    assert first["status"] == "READY"
    assert first["summary"] == {
        "ready": 1,
        "ready_with_warnings": 0,
        "blocked": 0,
        "skipped": 1,
    }
    assert first["write_performed"] is False
    assert first["items"][0]["assignee"]["account_id"] == "jira-jose"
    assert first["items"][0]["idempotency_key"].startswith("AJI-")
    assert second["dry_run_id"] == first["dry_run_id"]
    assert second["reused"] is True
    assert gateway.calls == [
        ("admin@agentejira.local", "AT", "José Calleja"),
        ("admin@agentejira.local", "AT", "José Calleja"),
    ]


def test_dry_run_blocks_a_general_value_that_is_no_longer_allowed_in_jira(tmp_path: Path):
    repository = ProposalRepository(tmp_path / "dry-run-options.db")
    gateway = FakeJiraReadGateway()
    service = JiraDryRunService(repository, gateway)
    proposal = approved_proposal()
    proposal["items"][0]["generated"]["fields"]["tipo_seguimiento"] = "Quincenal"

    result = asyncio.run(service.generate(proposal, "admin@agentejira.local"))

    assert result["status"] == "BLOCKED"
    assert result["items"][0]["errors"] == [
        {
            "code": "FIELD_VALUE_NOT_ALLOWED",
            "field": "tipo_seguimiento",
            "message": "El valor 'Quincenal' ya no aparece entre las opciones vigentes de 'Tipo de seguimiento' en Jira.",
        }
    ]


def test_dry_run_resolves_a_sprint_name_to_its_numeric_id(tmp_path: Path):
    class SprintGateway(FakeJiraReadGateway):
        def connected_snapshot(self, username: str):
            value = super().connected_snapshot(username)
            value["spaces"][0]["work_types"][0]["fields"].append({
                "id": "customfield_10020",
                "name": "Sprint",
                "required": False,
                "business_key": "sprint",
                "options": [],
            })
            return value

        async def list_sprints(self, _username: str, _space: str, *, force_refresh: bool = False):
            assert force_refresh is True
            return [{
                "id": "321",
                "name": "SPT-SEMANA-30-31-2026",
                "state": "active",
                "board_id": "45",
                "source": "ROVO_MCP_JQL",
            }]

    proposal = approved_proposal()
    proposal["items"][0]["generated"]["fields"]["sprint"] = "SPT-SEMANA-30-31-2026"
    service = JiraDryRunService(ProposalRepository(tmp_path / "sprint-name.db"), SprintGateway())
    ready = asyncio.run(service.generate(proposal, "tester"))

    assert ready["status"] == "READY"
    assert ready["items"][0]["logical_payload"]["jira_fields"]["customfield_10020"] == "321"
    assert ready["items"][0]["sprint_resolution"]["mode"] == "PLAN_NAME_MATCH"
    assert ready["items"][0]["sprint_resolution"]["selected"]["name"] == "SPT-SEMANA-30-31-2026"


def test_at_team_managed_subtask_without_fields_is_blocked(tmp_path: Path):
    service = JiraDryRunService(
        ProposalRepository(tmp_path / "subtask.db"),
        FakeJiraReadGateway(),
    )

    result = asyncio.run(service.generate(approved_proposal("Subtask"), "tester"))

    assert result["status"] == "BLOCKED"
    codes = {issue["code"] for issue in result["items"][0]["errors"]}
    assert "WORK_TYPE_FIELDS_UNAVAILABLE" in codes
    assert "ASSIGNEE_FIELD_UNAVAILABLE" not in codes
    assert "SUBTASK_PARENT_REQUIRED" in codes
    assert result["write_performed"] is False


def test_account_lookup_without_assignability_evidence_is_a_dry_run_warning(tmp_path: Path):
    class LookupOnlyGateway(FakeJiraReadGateway):
        async def find_assignees(self, username: str, space: str, query: str):
            users = await super().find_assignees(username, space, query)
            users[0]["capability"] = "lookupJiraAccountId"
            return users

    service = JiraDryRunService(
        ProposalRepository(tmp_path / "lookup-only.db"),
        LookupOnlyGateway(),
    )

    result = asyncio.run(service.generate(approved_proposal(), "tester"))

    assert result["status"] == "READY_WITH_WARNINGS"
    assert result["summary"]["ready_with_warnings"] == 1
    assert "ASSIGNEE_ASSIGNABILITY_UNVERIFIED" in {
        issue["code"] for issue in result["items"][0]["warnings"]
    }
    assert result["items"][0]["errors"] == []
    assert result["write_performed"] is False


def test_dry_run_rejects_a_non_approved_proposal(tmp_path: Path):
    service = JiraDryRunService(
        ProposalRepository(tmp_path / "state.db"),
        FakeJiraReadGateway(),
    )
    proposal = copy.deepcopy(approved_proposal())
    proposal["status"] = "VALIDATED"

    with pytest.raises(ProposalStateError):
        asyncio.run(service.generate(proposal, "tester"))


def test_dry_run_api_never_exposes_a_write_operation(tmp_path: Path):
    project_dir = Path(__file__).resolve().parents[2]
    settings = Settings(
        database_path=tmp_path / "api.db",
        schema_path=project_dir / "docs" / "schemas" / "jira_proposal_v1_1.schema.json",
        frontend_dist=tmp_path / "dist",
        frozen_template_path=(
            project_dir
            / "releases"
            / "plantilla_excel_v1_1"
            / "plantilla_plan_trabajo_jira_v1_1.xlsx"
        ),
        local_user="admin@agentejira.local",
        local_password="AgenteJira2026!",
    )
    gateway = FakeJiraReadGateway()
    with TestClient(create_app(settings, atlassian_manager=gateway)) as client:
        client.app.state.proposal_service.repository.save(approved_proposal())
        login = client.post(
            "/api/auth/login",
            json={
                "username": "admin@agentejira.local",
                "password": "AgenteJira2026!",
            },
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        response = client.post(
            "/api/proposals/11111111-1111-4111-8111-111111111111/dry-run",
            headers=headers,
        )

        assert response.status_code == 200, response.text
        assert response.json()["write_performed"] is False
        assert response.json()["status"] == "READY"

        reopened = copy.deepcopy(approved_proposal())
        reopened["version"] += 1
        reopened["status"] = "VALIDATED"
        reopened["approved_at"] = None
        reopened["approved_by"] = None
        client.app.state.proposal_service.repository.save(reopened)

        historical = client.get(
            "/api/proposals/11111111-1111-4111-8111-111111111111/dry-run/latest",
            headers=headers,
        )
        assert historical.status_code == 200, historical.text
        assert historical.json()["proposal_version"] == approved_proposal()["version"]
        assert historical.json()["stale"] is True
        assert historical.json()["summary"] == {
            "ready": 1,
            "ready_with_warnings": 0,
            "blocked": 0,
            "skipped": 1,
        }
        assert gateway.calls == [
            ("admin@agentejira.local", "AT", "José Calleja")
        ]


def test_approval_and_final_dry_run_are_one_read_only_api_action(tmp_path: Path):
    project_dir = Path(__file__).resolve().parents[2]
    settings = Settings(
        database_path=tmp_path / "approve-dry-run.db",
        schema_path=project_dir / "docs" / "schemas" / "jira_proposal_v1_1.schema.json",
        frontend_dist=tmp_path / "dist",
        frozen_template_path=(
            project_dir
            / "releases"
            / "plantilla_excel_v1_1"
            / "plantilla_plan_trabajo_jira_v1_1.xlsx"
        ),
        local_user="admin@agentejira.local",
        local_password="AgenteJira2026!",
    )
    gateway = FakeJiraReadGateway()
    draft = copy.deepcopy(approved_proposal())
    draft["status"] = "VALIDATED"
    draft["approved_at"] = None
    draft["approved_by"] = None

    with TestClient(create_app(settings, atlassian_manager=gateway)) as client:
        # Save bypasses validation only to isolate the lifecycle orchestration in this test.
        client.app.state.proposal_service.repository.save(draft)
        client.app.state.proposal_service.validator.validate = lambda _proposal: None
        login = client.post(
            "/api/auth/login",
            json={
                "username": "admin@agentejira.local",
                "password": "AgenteJira2026!",
            },
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        response = client.post(
            "/api/proposals/11111111-1111-4111-8111-111111111111/approve-and-dry-run",
            headers=headers,
        )

        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["proposal"]["status"] == "APPROVED"
        assert payload["proposal"]["version"] == draft["version"] + 1
        assert payload["dry_run"]["proposal_version"] == payload["proposal"]["version"]
        assert payload["dry_run"]["write_performed"] is False
        assert payload["dry_run"]["status"] == "READY"

        evidence = client.get(
            "/api/proposals/11111111-1111-4111-8111-111111111111/dry-run-evidence",
            headers=headers,
        )
        assert evidence.status_code == 200
        assert evidence.json()["objective"] == "3B.2"
        assert evidence.json()["mode"] == "DRY_RUN_NO_WRITE"
        assert evidence.json()["jira_prevalidation"]["write_performed"] is False
