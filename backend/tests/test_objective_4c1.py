from __future__ import annotations

import asyncio
import copy
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.execution_policy import load_execution_policy
from app.main import create_app
from app.objective_4c1 import JiraControlledBatchService, Objective4C1Error
from app.repository import ProposalRepository
from tests.test_dry_run import approved_proposal
from tests.test_objective_4a import ready_dry_run
from tests.test_objective_4b import jira_snapshot, tool_readiness


PROJECT_DIR = Path(__file__).resolve().parents[2]
POLICY = PROJECT_DIR / "config" / "jira_execution_policy_4c1.json"
POLICY_4D = PROJECT_DIR / "config" / "jira_execution_policy_4d.json"
POLICY_4E = PROJECT_DIR / "config" / "jira_execution_policy_4e.json"
SCHEMA = PROJECT_DIR / "docs" / "schemas" / "jira_execution_policy_v1.schema.json"
USERNAME = "admin@agentejira.local"


def seed_batch(
    repository: ProposalRepository,
    count: int = 3,
    sprint: bool = False,
    work_types: list[str] | None = None,
):
    proposal = approved_proposal()
    proposal["items"] = []
    base = approved_proposal()["items"][0]
    for number in range(6, 6 + count):
        item = copy.deepcopy(base)
        item["source"]["source_row"] = number
        item["generated"]["row_id"] = f"ROW-{number:04d}"
        item["generated"]["title"] = f"Actividad {number}"
        if work_types:
            item["generated"]["work_type"] = work_types[number - 6]
        proposal["items"].append(item)
    dry_run = ready_dry_run(proposal, status="READY")
    base_dry_item = dry_run["items"][0]
    dry_run["items"] = []
    for number in range(6, 6 + count):
        item = copy.deepcopy(base_dry_item)
        item["row_id"] = f"ROW-{number:04d}"
        item["source_row"] = number
        item["title"] = f"Actividad {number}"
        item["idempotency_key"] = f"AJI-{number:032d}"
        item["logical_payload"]["summary"] = item["title"]
        item["logical_payload"]["jira_fields"]["summary"] = item["title"]
        if work_types:
            work_type = work_types[number - 6]
            item["work_type"] = work_type
            item["logical_payload"]["work_type"] = work_type
            item["logical_payload"]["work_type_id"] = {
                "Task": "10", "Bug": "11", "Story": "12", "Epic": "13", "Subtask": "14"
            }[work_type]
        if sprint:
            item["logical_payload"]["jira_fields"]["customfield_10020"] = "321"
            item["sprint_resolution"] = {
                "selected": {"id": "321", "name": "SPT-ACTIVO", "state": "active"},
                "mode": "PLAN_NAME_MATCH",
                "requested": "SPT-ACTIVO",
                "error": None,
                "warning": None,
            }
        dry_run["items"].append(item)
    dry_run["summary"] = {"ready": count, "ready_with_warnings": 0, "blocked": 0, "skipped": 0}
    repository.save(proposal)
    repository.save_dry_run(dry_run)
    return proposal, dry_run


class BatchGateway:
    def __init__(self, fail_at: int | None = None, uncertain: bool = False, verified: bool = True, sprints=None):
        self.fail_at = fail_at
        self.uncertain = uncertain
        self.verified = verified
        self.calls: list[dict] = []
        self.sprint_calls: list[dict] = []
        self.sprints = sprints if sprints is not None else []

    async def list_sprints(self, username, space, *, force_refresh=False):
        self.sprint_calls.append({"username": username, "space": space, "force_refresh": force_refresh})
        return self.sprints

    async def create_single_task_and_readback(self, username, create_arguments, readback_fields, timeout_seconds):
        self.calls.append(copy.deepcopy(create_arguments))
        index = len(self.calls)
        if self.fail_at == index:
            error = RuntimeError("fallo controlado")
            error.outcome_uncertain = self.uncertain
            error.real_mcp_calls = 1
            raise error
        key = f"AT-{9000 + index}"
        return {
            "issue_key": key,
            "real_mcp_calls": 2,
            "readback": {
                "key": key,
                "fields": {
                    "summary": create_arguments["summary"] if self.verified else "otro",
                    "project": {"key": "AT"},
                    "issuetype": {"name": create_arguments["issueTypeName"]},
                    "assignee": {"accountId": create_arguments["assignee_account_id"]},
                    "customfield_10020": [{"id": 321}],
                    **({"parent": copy.deepcopy(create_arguments["additional_fields"]["parent"])}
                       if (create_arguments.get("additional_fields") or {}).get("parent") else {}),
                },
            },
        }


class WrongParentGateway(BatchGateway):
    async def create_single_task_and_readback(self, username, create_arguments, readback_fields, timeout_seconds):
        result = await super().create_single_task_and_readback(
            username, create_arguments, readback_fields, timeout_seconds
        )
        parent = (create_arguments.get("additional_fields") or {}).get("parent")
        if parent:
            result["readback"]["fields"]["parent"] = {"key": "AT-0000"}
        return result


def hierarchy_snapshot() -> dict:
    snapshot = jira_snapshot()
    snapshot["spaces"][0]["work_types"].extend([
        {
            "id": "13", "name": "Epic", "subtask": False,
            "fields": [{"id": "labels", "name": "Labels", "required": False}],
        },
        {
            "id": "14", "name": "Subtask", "subtask": True,
            "fields": [
                {"id": "parent", "name": "Parent", "required": True},
                {"id": "labels", "name": "Labels", "required": False},
            ],
        },
    ])
    return snapshot


def seed_hierarchy(repository: ProposalRepository):
    proposal = approved_proposal()
    base = copy.deepcopy(proposal["items"][0])
    definitions = [
        ("ROW-0006", "Epic", "Epic de autenticacion", None),
        ("ROW-0007", "Story", "Historia de acceso", "ROW-0006"),
        ("ROW-0008", "Task", "Configurar permisos", None),
        ("ROW-0009", "Subtask", "Validar permisos", "ROW-0008"),
    ]
    proposal["items"] = []
    for index, (row_id, work_type, title, parent_row_id) in enumerate(definitions, start=6):
        item = copy.deepcopy(base)
        item["source"]["source_row"] = index
        item["generated"].update({
            "row_id": row_id,
            "work_type": work_type,
            "title": title,
            "parent_row_id": parent_row_id,
            "decision": "INCLUIR",
            "create_in_jira": True,
        })
        proposal["items"].append(item)
    dry_run = ready_dry_run(proposal, status="READY")
    dry_run["items"] = []
    base_dry = ready_dry_run(approved_proposal(), status="READY")["items"][0]
    for index, (row_id, work_type, title, parent_row_id) in enumerate(definitions, start=6):
        item = copy.deepcopy(base_dry)
        item.update({
            "row_id": row_id,
            "source_row": index,
            "title": title,
            "work_type": work_type,
            "parent_row_id": parent_row_id,
            "idempotency_key": f"AJI-HIER-{index:024d}",
        })
        item["logical_payload"].update({
            "summary": title,
            "work_type": work_type,
            "work_type_id": {"Epic": "13", "Story": "12", "Task": "10", "Subtask": "14"}[work_type],
            "parent_row_id": parent_row_id,
        })
        dry_run["items"].append(item)
    dry_run["summary"] = {"ready": 4, "ready_with_warnings": 0, "blocked": 0, "skipped": 0}
    repository.save(proposal)
    repository.save_dry_run(dry_run)
    return proposal, dry_run


def service(tmp_path: Path, gateway: BatchGateway, count: int = 3, sprint: bool = False):
    repository = ProposalRepository(tmp_path / "batch.db")
    proposal, dry_run = seed_batch(repository, count, sprint)
    batch_service = JiraControlledBatchService(
        repository,
        load_execution_policy(POLICY, SCHEMA),
        gateway,
        now=lambda: datetime(2026, 7, 20, 18, 0, tzinfo=UTC),
    )
    return repository, proposal, dry_run, batch_service


def prepare_confirm(batch_service, proposal, dry_run):
    prepared = batch_service.prepare(
        proposal["proposal_id"],
        [item["row_id"] for item in dry_run["items"]],
        USERNAME,
        jira_snapshot(),
        tool_readiness(),
    )
    confirmed = batch_service.confirm(
        prepared["execution_id"], prepared["payload_hash"], prepared["confirmation_phrase"], USERNAME
    )
    return prepared, confirmed


def test_batch_creates_three_sequentially_and_reuses_terminal_result(tmp_path: Path):
    gateway = BatchGateway()
    _, proposal, dry_run, batch_service = service(tmp_path, gateway)
    prepared, _ = prepare_confirm(batch_service, proposal, dry_run)

    result = asyncio.run(batch_service.execute(prepared["execution_id"], USERNAME))
    repeated = asyncio.run(batch_service.execute(prepared["execution_id"], USERNAME))

    assert result["status"] == "COMPLETED"
    assert result["summary"]["created_verified"] == 3
    assert result["real_mcp_calls"] == 6
    assert result["automatic_retries"] == 0
    assert [item["issue_key"] for item in result["items"]] == ["AT-9001", "AT-9002", "AT-9003"]
    assert repeated["reused"] is True
    assert len(gateway.calls) == 3


@pytest.mark.parametrize(
    ("uncertain", "expected_status", "item_status"),
    [(False, "STOPPED_REJECTED", "REJECTED"), (True, "STOPPED_UNKNOWN", "UNKNOWN")],
)
def test_batch_stops_on_first_failure_without_retry(tmp_path: Path, uncertain, expected_status, item_status):
    gateway = BatchGateway(fail_at=2, uncertain=uncertain)
    _, proposal, dry_run, batch_service = service(tmp_path, gateway)
    prepared, _ = prepare_confirm(batch_service, proposal, dry_run)

    result = asyncio.run(batch_service.execute(prepared["execution_id"], USERNAME))

    assert result["status"] == expected_status
    assert [item["status"] for item in result["items"]] == ["CREATED_VERIFIED", item_status, "NOT_ATTEMPTED"]
    assert result["automatic_retries"] == 0
    assert len(gateway.calls) == 2


def test_batch_stops_when_readback_is_incomplete(tmp_path: Path):
    gateway = BatchGateway(verified=False)
    _, proposal, dry_run, batch_service = service(tmp_path, gateway)
    prepared, _ = prepare_confirm(batch_service, proposal, dry_run)
    result = asyncio.run(batch_service.execute(prepared["execution_id"], USERNAME))

    assert result["status"] == "STOPPED_UNVERIFIED"
    assert result["items"][0]["status"] == "CREATED_UNVERIFIED"
    assert all(item["status"] == "NOT_ATTEMPTED" for item in result["items"][1:])
    assert len(gateway.calls) == 1


def test_batch_revalidates_sprint_once_before_any_write(tmp_path: Path):
    gateway = BatchGateway(sprints=[])
    _, proposal, dry_run, batch_service = service(tmp_path, gateway, sprint=True)
    prepared, _ = prepare_confirm(batch_service, proposal, dry_run)

    with pytest.raises(Objective4C1Error, match="no esta activo/futuro"):
        asyncio.run(batch_service.execute(prepared["execution_id"], USERNAME))

    assert gateway.calls == []
    assert len(gateway.sprint_calls) == 1


def test_batch_rejects_more_than_five_before_write(tmp_path: Path):
    gateway = BatchGateway()
    _, proposal, dry_run, batch_service = service(tmp_path, gateway, count=6)
    with pytest.raises(Objective4C1Error, match="entre 1 y 5"):
        batch_service.prepare(
            proposal["proposal_id"],
            [item["row_id"] for item in dry_run["items"]],
            USERNAME,
            jira_snapshot(),
            tool_readiness(),
        )
    assert gateway.calls == []


def test_batch_reuses_same_selection_and_blocks_overlap(tmp_path: Path):
    gateway = BatchGateway()
    _, proposal, dry_run, batch_service = service(tmp_path, gateway)
    first_ids = [dry_run["items"][0]["row_id"], dry_run["items"][1]["row_id"]]
    first = batch_service.prepare(
        proposal["proposal_id"], first_ids, USERNAME, jira_snapshot(), tool_readiness()
    )
    repeated = batch_service.prepare(
        proposal["proposal_id"], first_ids, USERNAME, jira_snapshot(), tool_readiness()
    )
    assert repeated["execution_id"] == first["execution_id"]
    assert repeated["reused"] is True

    with pytest.raises(Objective4C1Error, match="otro lote"):
        batch_service.prepare(
            proposal["proposal_id"],
            [dry_run["items"][1]["row_id"], dry_run["items"][2]["row_id"]],
            USERNAME,
            jira_snapshot(),
            tool_readiness(),
        )


def test_4c2_continues_a_large_plan_in_disjoint_batches_of_five(tmp_path: Path):
    gateway = BatchGateway()
    _, proposal, dry_run, batch_service = service(tmp_path, gateway, count=7)
    first_ids = [item["row_id"] for item in dry_run["items"][:5]]
    first = batch_service.prepare(
        proposal["proposal_id"], first_ids, USERNAME, jira_snapshot(), tool_readiness()
    )
    batch_service.confirm(
        first["execution_id"], first["payload_hash"], first["confirmation_phrase"], USERNAME
    )
    completed = asyncio.run(batch_service.execute(first["execution_id"], USERNAME))
    assert completed["status"] == "COMPLETED"

    calls_before_progress = len(gateway.calls)
    progress = batch_service.progress(proposal["proposal_id"])
    assert progress["objective"] == "4C.2"
    assert progress["counts"]["created_verified"] == 5
    assert progress["counts"]["available"] == 2
    assert progress["available_row_ids"] == [item["row_id"] for item in dry_run["items"][5:]]
    assert len(gateway.calls) == calls_before_progress

    next_batch = batch_service.prepare(
        proposal["proposal_id"],
        progress["available_row_ids"],
        USERNAME,
        jira_snapshot(),
        tool_readiness(),
    )
    assert next_batch["status"] == "BATCH_PREPARED"
    assert len(next_batch["items"]) == 2


def test_4d_creates_and_verifies_a_mixed_task_bug_story_batch(tmp_path: Path):
    gateway = BatchGateway()
    repository = ProposalRepository(tmp_path / "mixed.db")
    proposal, dry_run = seed_batch(
        repository, count=3, work_types=["Task", "Bug", "Story"]
    )
    batch_service = JiraControlledBatchService(
        repository,
        load_execution_policy(POLICY_4D, SCHEMA),
        gateway,
        now=lambda: datetime(2026, 7, 20, 19, 0, tzinfo=UTC),
    )
    prepared = batch_service.prepare(
        proposal["proposal_id"],
        [item["row_id"] for item in dry_run["items"]],
        USERNAME,
        jira_snapshot(),
        tool_readiness(),
    )

    assert prepared["objective"] == "4D"
    assert prepared["mode"] == "CONTROLLED_WORK_ITEM_BATCH"
    assert prepared["confirmation_phrase"] == "CREAR 3 ACTIVIDADES EN AT"
    assert [item["payload"]["arguments"]["issueTypeName"] for item in prepared["items"]] == ["Task", "Bug", "Story"]
    assert prepared["items"][0]["preview"]["title"].startswith("AgenteTest_Task_")
    assert prepared["items"][1]["preview"]["title"].startswith("AgenteTest_Bug_")
    assert prepared["items"][2]["preview"]["title"].startswith("AgenteTest_Story_")

    batch_service.confirm(
        prepared["execution_id"], prepared["payload_hash"], prepared["confirmation_phrase"], USERNAME
    )
    completed = asyncio.run(batch_service.execute(prepared["execution_id"], USERNAME))
    assert completed["status"] == "COMPLETED"
    assert completed["summary"]["created_verified"] == 3
    assert [call["issueTypeName"] for call in gateway.calls] == ["Task", "Bug", "Story"]
    assert all(all(item["readback"]["checks"].values()) for item in completed["items"])


def test_4e_orders_parents_resolves_keys_and_verifies_both_hierarchy_levels(tmp_path: Path):
    gateway = BatchGateway()
    repository = ProposalRepository(tmp_path / "hierarchy.db")
    proposal, dry_run = seed_hierarchy(repository)
    batch_service = JiraControlledBatchService(
        repository,
        load_execution_policy(POLICY_4E, SCHEMA),
        gateway,
        now=lambda: datetime(2026, 7, 20, 20, 0, tzinfo=UTC),
    )
    prepared = batch_service.prepare(
        proposal["proposal_id"],
        ["ROW-0007", "ROW-0009", "ROW-0006", "ROW-0008"],
        USERNAME,
        hierarchy_snapshot(),
        tool_readiness(),
    )

    assert prepared["objective"] == "4E"
    assert prepared["mode"] == "CONTROLLED_HIERARCHY_BATCH"
    assert prepared["row_ids"] == ["ROW-0006", "ROW-0007", "ROW-0008", "ROW-0009"]
    assert prepared["items"][1]["payload"]["arguments"]["additional_fields"]["parent"] == {"key": "$ROW-0006"}
    assert prepared["items"][3]["payload"]["arguments"]["additional_fields"]["parent"] == {"key": "$ROW-0008"}

    batch_service.confirm(
        prepared["execution_id"], prepared["payload_hash"], prepared["confirmation_phrase"], USERNAME
    )
    completed = asyncio.run(batch_service.execute(prepared["execution_id"], USERNAME))

    assert completed["status"] == "COMPLETED"
    assert [call["issueTypeName"] for call in gateway.calls] == ["Epic", "Story", "Task", "Subtask"]
    assert gateway.calls[1]["additional_fields"]["parent"] == {"key": "AT-9001"}
    assert gateway.calls[3]["additional_fields"]["parent"] == {"key": "AT-9003"}
    assert completed["items"][1]["readback"]["checks"]["parent"] is True
    assert completed["items"][3]["readback"]["checks"]["parent"] is True
    assert completed["real_mcp_calls"] == 8
    assert completed["automatic_retries"] == 0


def test_4e_requires_uncreated_parent_in_same_batch(tmp_path: Path):
    gateway = BatchGateway()
    repository = ProposalRepository(tmp_path / "hierarchy-missing-parent.db")
    proposal, _ = seed_hierarchy(repository)
    batch_service = JiraControlledBatchService(
        repository,
        load_execution_policy(POLICY_4E, SCHEMA),
        gateway,
    )

    with pytest.raises(Objective4C1Error, match="Incluye primero la actividad padre ROW-0006"):
        batch_service.prepare(
            proposal["proposal_id"], ["ROW-0007"], USERNAME, hierarchy_snapshot(), tool_readiness()
        )
    assert gateway.calls == []


def test_4e_child_can_use_verified_parent_from_previous_batch(tmp_path: Path):
    gateway = BatchGateway()
    repository = ProposalRepository(tmp_path / "hierarchy-successive.db")
    proposal, _ = seed_hierarchy(repository)
    batch_service = JiraControlledBatchService(
        repository,
        load_execution_policy(POLICY_4E, SCHEMA),
        gateway,
        now=lambda: datetime(2026, 7, 20, 20, 30, tzinfo=UTC),
    )
    first = batch_service.prepare(
        proposal["proposal_id"], ["ROW-0006"], USERNAME, hierarchy_snapshot(), tool_readiness()
    )
    batch_service.confirm(first["execution_id"], first["payload_hash"], first["confirmation_phrase"], USERNAME)
    assert asyncio.run(batch_service.execute(first["execution_id"], USERNAME))["status"] == "COMPLETED"

    second = batch_service.prepare(
        proposal["proposal_id"], ["ROW-0007"], USERNAME, hierarchy_snapshot(), tool_readiness()
    )
    assert second["items"][0]["preview"]["parent_issue_key"] == "AT-9001"
    batch_service.confirm(second["execution_id"], second["payload_hash"], second["confirmation_phrase"], USERNAME)
    completed = asyncio.run(batch_service.execute(second["execution_id"], USERNAME))
    assert completed["status"] == "COMPLETED"
    assert gateway.calls[1]["additional_fields"]["parent"] == {"key": "AT-9001"}


def test_4e_stops_when_jira_readback_reports_a_different_parent(tmp_path: Path):
    gateway = WrongParentGateway()
    repository = ProposalRepository(tmp_path / "hierarchy-wrong-parent.db")
    proposal, _ = seed_hierarchy(repository)
    batch_service = JiraControlledBatchService(
        repository,
        load_execution_policy(POLICY_4E, SCHEMA),
        gateway,
        now=lambda: datetime(2026, 7, 20, 21, 0, tzinfo=UTC),
    )
    prepared = batch_service.prepare(
        proposal["proposal_id"], ["ROW-0006", "ROW-0007"], USERNAME, hierarchy_snapshot(), tool_readiness()
    )
    batch_service.confirm(
        prepared["execution_id"], prepared["payload_hash"], prepared["confirmation_phrase"], USERNAME
    )

    completed = asyncio.run(batch_service.execute(prepared["execution_id"], USERNAME))

    assert completed["status"] == "STOPPED_UNVERIFIED"
    assert completed["summary"]["created_verified"] == 1
    assert completed["summary"]["created_unverified"] == 1
    assert completed["items"][1]["readback"]["checks"]["parent"] is False
    assert completed["automatic_retries"] == 0


class ApiBatchManager(BatchGateway):
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
            "jira_write_enabled": True,
            "write_tools_blocked": False,
            "error": None,
            "snapshot": jira_snapshot(),
        }


def test_objective_4c1_api_flow_and_evidence(tmp_path: Path):
    manager = ApiBatchManager()
    settings = Settings(
        database_path=tmp_path / "api-batch.db",
        schema_path=PROJECT_DIR / "docs" / "schemas" / "jira_proposal_v1_1.schema.json",
        frontend_dist=tmp_path / "dist",
        frozen_template_path=PROJECT_DIR / "releases" / "plantilla_excel_v1_1" / "plantilla_plan_trabajo_jira_v1_1.xlsx",
        local_user=USERNAME,
        local_password="AgenteJira2026!",
        jira_execution_policy_path=POLICY,
        jira_execution_policy_schema_path=SCHEMA,
    )
    with TestClient(create_app(settings, atlassian_manager=manager)) as client:
        proposal, dry_run = seed_batch(client.app.state.proposal_service.repository, count=2)
        login = client.post("/api/auth/login", json={"username": USERNAME, "password": settings.local_password})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        readiness = client.get("/api/objectives/4/readiness", headers=headers)
        assert readiness.status_code == 200
        assert readiness.json()["status"] == "READY_FOR_CONTROLLED_BATCH"
        prepared_response = client.post(
            f"/api/proposals/{proposal['proposal_id']}/objective-4c1/prepare",
            headers=headers,
            json={"row_ids": [item["row_id"] for item in dry_run["items"]]},
        )
        assert prepared_response.status_code == 200, prepared_response.text
        prepared = prepared_response.json()
        confirmed_response = client.post(
            f"/api/objectives/4c1/batches/{prepared['execution_id']}/confirm",
            headers=headers,
            json={"payload_hash": prepared["payload_hash"], "confirmation_phrase": prepared["confirmation_phrase"]},
        )
        assert confirmed_response.status_code == 200
        executed = client.post(
            f"/api/objectives/4c1/batches/{prepared['execution_id']}/execute",
            headers=headers,
        )
        assert executed.status_code == 200, executed.text
        assert executed.json()["status"] == "COMPLETED"
        progress = client.get(
            f"/api/proposals/{proposal['proposal_id']}/objective-4c2/progress",
            headers=headers,
        )
        assert progress.status_code == 200
        assert progress.json()["counts"]["created_verified"] == 2
        assert progress.json()["counts"]["available"] == 0
        evidence = client.get(
            f"/api/objectives/4c1/batches/{prepared['execution_id']}/evidence",
            headers=headers,
        )
        assert evidence.status_code == 200
        assert evidence.json()["stop_on_first_failure"] is True
        assert len(manager.calls) == 2


def test_objective_4d_readiness_requires_all_three_work_type_contracts(tmp_path: Path):
    manager = ApiBatchManager()
    settings = Settings(
        database_path=tmp_path / "api-4d.db",
        schema_path=PROJECT_DIR / "docs" / "schemas" / "jira_proposal_v1_1.schema.json",
        frontend_dist=tmp_path / "dist",
        frozen_template_path=PROJECT_DIR / "releases" / "plantilla_excel_v1_1" / "plantilla_plan_trabajo_jira_v1_1.xlsx",
        local_user=USERNAME,
        local_password="AgenteJira2026!",
        jira_execution_policy_path=POLICY_4D,
        jira_execution_policy_schema_path=SCHEMA,
    )
    with TestClient(create_app(settings, atlassian_manager=manager)) as client:
        login = client.post("/api/auth/login", json={"username": USERNAME, "password": settings.local_password})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        readiness = client.get("/api/objectives/4/readiness", headers=headers)
        assert readiness.status_code == 200
        body = readiness.json()
        assert body["objective"] == "4D"
        assert body["status"] == "READY_FOR_CONTROLLED_MULTI_TYPE_BATCH"
        assert set(body["work_type_contracts"]) == {"Task", "Bug", "Story"}
        assert body["real_canary_checks"]["all_allowed_work_types_available"] is True


def test_objective_4e_readiness_requires_all_five_hierarchy_contracts(tmp_path: Path):
    manager = ApiBatchManager()
    manager.connected_snapshot = lambda _username: hierarchy_snapshot()
    manager.status = lambda _username: {
        "connected": True, "phase": "CONNECTED", "oauth_storage": "OS_ENCRYPTED",
        "jira_write_enabled": True, "write_tools_blocked": False, "error": None,
        "snapshot": hierarchy_snapshot(),
    }
    settings = Settings(
        database_path=tmp_path / "api-4e.db",
        schema_path=PROJECT_DIR / "docs" / "schemas" / "jira_proposal_v1_1.schema.json",
        frontend_dist=tmp_path / "dist",
        frozen_template_path=PROJECT_DIR / "releases" / "plantilla_excel_v1_1" / "plantilla_plan_trabajo_jira_v1_1.xlsx",
        local_user=USERNAME,
        local_password="AgenteJira2026!",
        jira_execution_policy_path=POLICY_4E,
        jira_execution_policy_schema_path=SCHEMA,
    )
    with TestClient(create_app(settings, atlassian_manager=manager)) as client:
        login = client.post("/api/auth/login", json={"username": USERNAME, "password": settings.local_password})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        response = client.get("/api/objectives/4/readiness", headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert body["objective"] == "4E"
        assert body["status"] == "READY_FOR_CONTROLLED_HIERARCHY_BATCH"
        assert set(body["work_type_contracts"]) == {"Task", "Bug", "Story", "Epic", "Subtask"}
        assert body["next_gate"] == "SELECT_PARENT_BEFORE_CHILD_BATCH"
