from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.execution_policy import load_execution_policy
from app.main import create_app
from app.objective_4a import JiraExecutionPreparationService, SimulatedJiraCreateGateway
from app.objective_4b import JiraControlledExecutionService, Objective4BError
from app.repository import ProposalRepository
from tests.test_dry_run import approved_proposal
from tests.test_objective_4a import ready_dry_run


PROJECT_DIR = Path(__file__).resolve().parents[2]
POLICY_4A = PROJECT_DIR / "config" / "jira_execution_policy_v1.json"
POLICY_4B = PROJECT_DIR / "config" / "jira_execution_policy_4b.json"
POLICY_SCHEMA = PROJECT_DIR / "docs" / "schemas" / "jira_execution_policy_v1.schema.json"
USERNAME = "admin@agentejira.local"


def jira_snapshot() -> dict:
    return {
        "cloud_id": "cloud-123",
        "site_url": "https://dpti.atlassian.net",
        "atlassian_user": {"account_id": "reporter-1", "display_name": "Jose"},
        "spaces": [{
            "key": "AT",
            "found": True,
            "id": "100",
            "name": "AT",
            "project_type": "software",
            "work_types": [{
                "id": "10",
                "name": "Task",
                "subtask": False,
                "fields": [{
                    "id": "customfield_10483",
                    "name": "Tipo de seguimiento",
                    "required": False,
                    "options": [{
                        "value": "Semanal",
                        "label": "Semanal",
                        "jira_id": "20001",
                    }],
                }, {
                    "id": "customfield_10020",
                    "name": "Sprint",
                    "required": False,
                    "business_key": "sprint",
                    "options": [],
                }],
            }, {
                "id": "11",
                "name": "Bug",
                "subtask": False,
                "fields": [{
                    "id": "customfield_10483",
                    "name": "Tipo de seguimiento",
                    "required": False,
                    "options": [{"value": "Semanal", "label": "Semanal", "jira_id": "20001"}],
                }, {
                    "id": "customfield_10020", "name": "Sprint", "required": False,
                    "business_key": "sprint", "options": [],
                }],
            }, {
                "id": "12",
                "name": "Story",
                "subtask": False,
                "fields": [{
                    "id": "customfield_10483",
                    "name": "Tipo de seguimiento",
                    "required": False,
                    "options": [{"value": "Semanal", "label": "Semanal", "jira_id": "20001"}],
                }, {
                    "id": "customfield_10020", "name": "Sprint", "required": False,
                    "business_key": "sprint", "options": [],
                }],
            }],
        }],
    }


def tool_readiness() -> dict:
    return {
        "create": {
            "exposed": True,
            "input_schema": {
                "required": ["cloudId", "projectKey", "issueTypeName", "summary"],
                "properties": {
                    "cloudId": {}, "projectKey": {}, "issueTypeName": {},
                    "summary": {}, "description": {}, "assignee_account_id": {},
                    "additional_fields": {}, "contentFormat": {},
                    "responseContentFormat": {},
                },
            },
        },
        "readback": {
            "exposed": True,
            "input_schema": {
                "required": ["cloudId", "issueIdOrKey"],
                "properties": {"cloudId": {}, "issueIdOrKey": {}, "fields": {}},
            },
        },
    }


def seed_simulated_intent(repository: ProposalRepository) -> tuple[dict, dict, dict]:
    proposal = approved_proposal()
    dry_run = ready_dry_run(proposal, status="READY")
    repository.save(proposal)
    repository.save_dry_run(dry_run)
    service = JiraExecutionPreparationService(
        repository,
        load_execution_policy(POLICY_4A, POLICY_SCHEMA),
        SimulatedJiraCreateGateway(),
        now=lambda: datetime(2026, 7, 20, 16, 0, tzinfo=UTC),
    )
    prepared = service.prepare(proposal, dry_run, "ROW-0006", USERNAME, jira_snapshot())
    service.confirm(prepared["execution_id"], prepared["payload_hash"], USERNAME)
    simulated = service.simulate(prepared["execution_id"], USERNAME)
    return proposal, dry_run, simulated


class FakeControlledGateway:
    def __init__(self, outcome: str = "success", sprints: list[dict] | None = None) -> None:
        self.outcome = outcome
        self.calls: list[dict] = []
        self.sprints = sprints or []
        self.sprint_calls: list[dict] = []

    async def list_sprints(self, username: str, space: str, *, force_refresh: bool = False):
        self.sprint_calls.append({
            "username": username,
            "space": space,
            "force_refresh": force_refresh,
        })
        return self.sprints

    async def create_single_task_and_readback(
        self,
        username: str,
        create_arguments: dict,
        readback_fields: list[str],
        timeout_seconds: int,
    ) -> dict:
        self.calls.append({
            "username": username,
            "arguments": create_arguments,
            "readback_fields": readback_fields,
            "timeout_seconds": timeout_seconds,
        })
        if self.outcome == "rejected":
            error = RuntimeError("Jira rechazo la creacion")
            error.outcome_uncertain = False
            error.real_mcp_calls = 1
            raise error
        if self.outcome == "unknown":
            error = TimeoutError("La respuesta se interrumpio despues del envio")
            error.outcome_uncertain = True
            error.real_mcp_calls = 1
            raise error
        assignee = create_arguments["assignee_account_id"]
        fields = {
            "summary": create_arguments["summary"],
            "project": {"key": "AT"},
            "issuetype": {"name": create_arguments["issueTypeName"]},
            "assignee": {"accountId": assignee},
        }
        sprint_id = (create_arguments.get("additional_fields") or {}).get("customfield_10020")
        if sprint_id is not None:
            fields["customfield_10020"] = [{"id": sprint_id, "name": "SPT-ACTIVO", "state": "active"}]
        return {
            "issue_key": "AT-9001",
            "real_mcp_calls": 2,
            "readback": {
                "key": "AT-9001",
                "fields": fields,
            },
        }


def objective_4b_service(tmp_path: Path, gateway: FakeControlledGateway):
    repository = ProposalRepository(tmp_path / "objective-4b.db")
    _, _, simulated = seed_simulated_intent(repository)
    service = JiraControlledExecutionService(
        repository,
        load_execution_policy(POLICY_4B, POLICY_SCHEMA),
        gateway,
        now=lambda: datetime(2026, 7, 20, 16, 1, tzinfo=UTC),
    )
    return repository, simulated, service


def test_controlled_write_creates_once_reads_back_and_is_idempotent(tmp_path: Path):
    gateway = FakeControlledGateway()
    repository, simulated, service = objective_4b_service(tmp_path, gateway)

    prepared = service.prepare(simulated["execution_id"], USERNAME, jira_snapshot(), tool_readiness())
    arguments = prepared["real_execution"]["payload"]["arguments"]
    assert prepared["status"] == "REAL_PREPARED"
    assert arguments["projectKey"] == "AT"
    assert arguments["issueTypeName"] == "Task"
    assert arguments["assignee_account_id"] == "jira-jose"
    assert arguments["additional_fields"]["labels"] == ["agente-test"]

    confirmed = service.confirm(
        simulated["execution_id"],
        prepared["real_execution"]["payload_hash"],
        service.CONFIRMATION_PHRASE,
        USERNAME,
    )
    assert confirmed["status"] == "REAL_CONFIRMED"

    result = asyncio.run(service.execute(simulated["execution_id"], USERNAME))
    repeated = asyncio.run(service.execute(simulated["execution_id"], USERNAME))

    assert result["status"] == "CREATED_VERIFIED"
    assert result["real_execution"]["issue_key"] == "AT-9001"
    assert result["real_execution"]["real_mcp_calls"] == 2
    assert result["real_execution"]["automatic_retries"] == 0
    assert result["real_execution"]["readback"]["checks"] == {
        "issue_key": True,
        "summary": True,
        "space": True,
        "work_type": True,
        "assignee": True,
    }
    assert repeated["reused"] is True
    assert len(gateway.calls) == 1
    assert repository.get_execution_intent(simulated["execution_id"])["status"] == "CREATED_VERIFIED"


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [("rejected", "REJECTED"), ("unknown", "UNKNOWN")],
)
def test_rejection_and_uncertain_outcome_never_retry(
    tmp_path: Path,
    outcome: str,
    expected: str,
):
    gateway = FakeControlledGateway(outcome)
    _, simulated, service = objective_4b_service(tmp_path, gateway)
    prepared = service.prepare(simulated["execution_id"], USERNAME, jira_snapshot(), tool_readiness())
    service.confirm(
        simulated["execution_id"],
        prepared["real_execution"]["payload_hash"],
        service.CONFIRMATION_PHRASE,
        USERNAME,
    )

    first = asyncio.run(service.execute(simulated["execution_id"], USERNAME))
    second = asyncio.run(service.execute(simulated["execution_id"], USERNAME))

    assert first["status"] == expected
    assert first["real_execution"]["automatic_retries"] == 0
    assert second["reused"] is True
    assert len(gateway.calls) == 1


def test_wrong_phrase_and_safe_policy_block_before_any_write(tmp_path: Path):
    gateway = FakeControlledGateway()
    _, simulated, service = objective_4b_service(tmp_path, gateway)
    prepared = service.prepare(simulated["execution_id"], USERNAME, jira_snapshot(), tool_readiness())
    with pytest.raises(Objective4BError, match="frase"):
        service.confirm(
            simulated["execution_id"],
            prepared["real_execution"]["payload_hash"],
            "SI",
            USERNAME,
        )
    assert gateway.calls == []

    safe_repository = ProposalRepository(tmp_path / "safe-policy.db")
    _, _, safe_simulated = seed_simulated_intent(safe_repository)
    safe_service = JiraControlledExecutionService(
        safe_repository,
        load_execution_policy(POLICY_4A, POLICY_SCHEMA),
        gateway,
    )
    with pytest.raises(Objective4BError, match="kill switch"):
        safe_service.prepare(safe_simulated["execution_id"], USERNAME, jira_snapshot(), tool_readiness())
    assert gateway.calls == []


def test_real_payload_converts_numeric_sprint_id_and_rejects_an_unresolved_name():
    numeric = JiraControlledExecutionService._additional_fields(
        {"customfield_10020": "321"},
        jira_snapshot(),
    )
    assert numeric["customfield_10020"] == 321

    with pytest.raises(Objective4BError, match="ID numerico"):
        JiraControlledExecutionService._additional_fields(
            {"customfield_10020": "SPT-SEMANA-30-31-2026"},
            jira_snapshot(),
        )


def seed_simulated_intent_with_sprint(repository: ProposalRepository) -> dict:
    proposal = approved_proposal()
    proposal["items"][0]["generated"]["fields"]["sprint"] = "SPT-ACTIVO"
    dry_run = ready_dry_run(proposal, status="READY")
    dry_item = dry_run["items"][0]
    dry_item["logical_payload"]["jira_fields"]["customfield_10020"] = "321"
    dry_item["sprint_resolution"] = {
        "selected": {
            "id": "321",
            "name": "SPT-ACTIVO",
            "state": "active",
            "board_id": "45",
            "source": "ROVO_MCP_JQL",
        },
        "mode": "PLAN_NAME_MATCH",
        "requested": "SPT-ACTIVO",
        "error": None,
        "warning": None,
    }
    repository.save(proposal)
    repository.save_dry_run(dry_run)
    simulator = JiraExecutionPreparationService(
        repository,
        load_execution_policy(POLICY_4A, POLICY_SCHEMA),
        SimulatedJiraCreateGateway(),
        now=lambda: datetime(2026, 7, 20, 16, 0, tzinfo=UTC),
    )
    prepared = simulator.prepare(proposal, dry_run, "ROW-0006", USERNAME, jira_snapshot())
    simulator.confirm(prepared["execution_id"], prepared["payload_hash"], USERNAME)
    return simulator.simulate(prepared["execution_id"], USERNAME)


def test_sprint_is_revalidated_immediately_before_the_only_create(tmp_path: Path):
    repository = ProposalRepository(tmp_path / "objective-4b-sprint.db")
    simulated = seed_simulated_intent_with_sprint(repository)
    gateway = FakeControlledGateway(sprints=[{
        "id": "321", "name": "SPT-ACTIVO", "state": "active", "board_id": "45"
    }])
    service = JiraControlledExecutionService(
        repository,
        load_execution_policy(POLICY_4B, POLICY_SCHEMA),
        gateway,
        now=lambda: datetime(2026, 7, 20, 16, 1, tzinfo=UTC),
    )
    prepared = service.prepare(simulated["execution_id"], USERNAME, jira_snapshot(), tool_readiness())
    service.confirm(
        simulated["execution_id"],
        prepared["real_execution"]["payload_hash"],
        service.CONFIRMATION_PHRASE,
        USERNAME,
    )

    result = asyncio.run(service.execute(simulated["execution_id"], USERNAME))

    assert result["status"] == "CREATED_VERIFIED"
    assert result["real_execution"]["sprint_revalidated_at"] is not None
    assert result["real_execution"]["readback"]["checks"]["sprint"] is True
    assert "customfield_10020" in gateway.calls[0]["readback_fields"]
    assert gateway.sprint_calls == [{
        "username": USERNAME, "space": "AT", "force_refresh": True
    }]
    assert len(gateway.calls) == 1


def test_closed_sprint_blocks_before_create_and_keeps_confirmation(tmp_path: Path):
    repository = ProposalRepository(tmp_path / "objective-4b-closed-sprint.db")
    simulated = seed_simulated_intent_with_sprint(repository)
    gateway = FakeControlledGateway(sprints=[])
    service = JiraControlledExecutionService(
        repository,
        load_execution_policy(POLICY_4B, POLICY_SCHEMA),
        gateway,
        now=lambda: datetime(2026, 7, 20, 16, 1, tzinfo=UTC),
    )
    prepared = service.prepare(simulated["execution_id"], USERNAME, jira_snapshot(), tool_readiness())
    service.confirm(
        simulated["execution_id"],
        prepared["real_execution"]["payload_hash"],
        service.CONFIRMATION_PHRASE,
        USERNAME,
    )

    with pytest.raises(Objective4BError, match="ya no esta activo/futuro"):
        asyncio.run(service.execute(simulated["execution_id"], USERNAME))

    assert gateway.calls == []
    assert repository.get_execution_intent(simulated["execution_id"])["status"] == "REAL_CONFIRMED"

class FakeApiManager(FakeControlledGateway):
    async def ensure_restored(self, _username: str) -> bool:
        return True

    def connected_snapshot(self, _username: str) -> dict:
        return jira_snapshot()

    def objective_4_tool_readiness(self, _username: str) -> dict:
        return tool_readiness()

    def status(self, _username: str) -> dict:
        return {
            "connected": True,
            "phase": "CONNECTED",
            "oauth_storage": "OS_ENCRYPTED",
            "jira_write_enabled": False,
            "write_tools_blocked": True,
            "error": None,
            "snapshot": jira_snapshot(),
        }


def test_objective_4b_api_flow_uses_fake_gateway_and_exposes_evidence(tmp_path: Path):
    manager = FakeApiManager()
    settings = Settings(
        database_path=tmp_path / "api-4b.db",
        schema_path=PROJECT_DIR / "docs" / "schemas" / "jira_proposal_v1_1.schema.json",
        frontend_dist=tmp_path / "dist",
        frozen_template_path=(
            PROJECT_DIR / "releases" / "plantilla_excel_v1_1"
            / "plantilla_plan_trabajo_jira_v1_1.xlsx"
        ),
        local_user=USERNAME,
        local_password="AgenteJira2026!",
        jira_execution_policy_path=POLICY_4B,
        jira_execution_policy_schema_path=POLICY_SCHEMA,
    )
    with TestClient(create_app(settings, atlassian_manager=manager)) as client:
        _, _, simulated = seed_simulated_intent(client.app.state.proposal_service.repository)
        login = client.post(
            "/api/auth/login",
            json={"username": USERNAME, "password": settings.local_password},
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        integration_status = client.get(
            "/api/integrations/atlassian/status",
            headers=headers,
        )
        assert integration_status.status_code == 200
        assert integration_status.json()["jira_write_enabled"] is True
        assert integration_status.json()["write_tools_blocked"] is False

        prepared_response = client.post(
            f"/api/objectives/4b/executions/{simulated['execution_id']}/prepare",
            headers=headers,
        )
        assert prepared_response.status_code == 200, prepared_response.text
        prepared = prepared_response.json()
        confirmed_response = client.post(
            f"/api/objectives/4b/executions/{simulated['execution_id']}/confirm",
            headers=headers,
            json={
                "payload_hash": prepared["real_execution"]["payload_hash"],
                "confirmation_phrase": "CREAR 1 TASK EN AT",
            },
        )
        assert confirmed_response.status_code == 200, confirmed_response.text
        executed_response = client.post(
            f"/api/objectives/4b/executions/{simulated['execution_id']}/execute",
            headers=headers,
        )
        assert executed_response.status_code == 200, executed_response.text
        assert executed_response.json()["status"] == "CREATED_VERIFIED"
        assert len(manager.calls) == 1

        evidence = client.get(
            f"/api/objectives/4b/executions/{simulated['execution_id']}/evidence",
            headers=headers,
        )
        assert evidence.status_code == 200
        assert evidence.json()["objective"] == "4B"
        assert evidence.json()["automatic_retries"] == 0
        assert evidence.json()["execution"]["real_execution"]["issue_key"] == "AT-9001"
