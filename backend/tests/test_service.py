from __future__ import annotations

from pathlib import Path

import pytest

from app.models import ItemUpdate, PlanDefaults, ProposalDefaultsUpdate
from app.errors import ProposalStateError
from app.repository import ProposalRepository
from app.schema import ProposalSchemaValidator
from app.service import ProposalService
from tests.conftest import SCHEMA, workbook_bytes


def make_service(tmp_path: Path) -> ProposalService:
    return ProposalService(
        ProposalRepository(tmp_path / "service.db"),
        ProposalSchemaValidator(SCHEMA),
    )


def test_service_generates_schema_valid_proposal(tmp_path: Path, sample_workbook: bytes):
    service = make_service(tmp_path)
    proposal = service.create_from_workbook(
        "plan.xlsx",
        sample_workbook,
        PlanDefaults(space="AT", iniciativa="Piloto IA", tipo_seguimiento="Semanal"),
        "tester@example.com",
    )

    assert proposal["version"] == 1
    assert proposal["template_version"] == "1.1"
    assert [item["generated"]["decision"] for item in proposal["items"]] == [
        "INCLUIR",
        "EXCLUIR",
        "REVISAR",
    ]
    assert proposal["items"][0]["generated"]["assignee"]["account_id"] == "local-account-giselle"
    assert proposal["items"][1]["generated"]["work_type"] == "Bug"
    assert proposal["items"][0]["generated"]["fields"]["iniciativa"] == "Piloto IA"
    assert proposal["items"][2]["validation"]["pending_requirements"] == [
        {
            "code": "ASSIGNEE_UNRESOLVED",
            "field": "assignee_account_id",
            "message": "Selecciona un responsable disponible en el catálogo.",
        }
    ]


def test_item_edit_saves_subtask_parent_atomically(tmp_path: Path, sample_workbook: bytes):
    service = make_service(tmp_path)
    original = service.create_from_workbook(
        "plan.xlsx", sample_workbook, PlanDefaults(space="AT"), "tester@example.com"
    )
    parent_row = original["items"][0]["generated"]["row_id"]
    child_row = original["items"][2]["generated"]["row_id"]

    updated = service.update_item(
        original["proposal_id"],
        child_row,
        ItemUpdate(
            work_type="Subtask",
            parent_row_id=parent_row,
            assignee_account_id="local-account-wilfrido",
        ),
        "reviewer@example.com",
    )

    child = next(item for item in updated["items"] if item["generated"]["row_id"] == child_row)
    assert child["generated"]["work_type"] == "Subtask"
    assert child["generated"]["parent_row_id"] == parent_row
    assert child["generated"]["decision"] == "INCLUIR"

    with pytest.raises(ValueError, match="propia actividad padre"):
        service.update_item(
            original["proposal_id"],
            child_row,
            ItemUpdate(work_type="Subtask", parent_row_id=child_row),
            "reviewer@example.com",
        )


def test_item_edit_creates_new_version_without_mutating_source(
    tmp_path: Path,
    sample_workbook: bytes,
):
    service = make_service(tmp_path)
    original = service.create_from_workbook(
        "plan.xlsx",
        sample_workbook,
        PlanDefaults(space="AT"),
        "tester@example.com",
    )
    row_id = original["items"][2]["generated"]["row_id"]
    updated = service.update_item(
        original["proposal_id"],
        row_id,
        ItemUpdate(
            title="Definir reglas del backend",
            review_note="Confirmado durante la revisión.",
            assignee_account_id="local-account-wilfrido",
        ),
        "reviewer@example.com",
    )

    assert updated is not None
    assert updated["version"] == 2
    assert updated["source_file"] == original["source_file"]
    assert updated["items"][2]["source"] == original["items"][2]["source"]
    assert updated["items"][2]["generated"]["title"] == "Definir reglas del backend"
    assert updated["items"][2]["generated"]["assignee"]["resolution"] == "RESOLVED"
    assert updated["items"][2]["generated"]["assignee"]["account_id"] == "local-account-wilfrido"
    assert updated["items"][2]["generated"]["decision"] == "INCLUIR"
    assert updated["items"][2]["validation"]["pending_requirements"] == []
    assert service.repository.get(original["proposal_id"], 1) == original


def test_item_edit_saves_verified_jira_assignee_and_other_changes_atomically(
    tmp_path: Path,
    sample_workbook: bytes,
):
    service = make_service(tmp_path)
    original = service.create_from_workbook(
        "plan.xlsx", sample_workbook, PlanDefaults(space="AT"), "tester@example.com"
    )
    row_id = original["items"][2]["generated"]["row_id"]

    updated = service.update_item(
        original["proposal_id"],
        row_id,
        ItemUpdate(
            title="Definir reglas ajustadas",
            description="Descripción editada en la misma sesión.",
            review_note="Cambio combinado",
            assignee_account_id="jira-real-wilfrido",
            assignee_query="Wilfrido Hernández",
        ),
        "reviewer@example.com",
        verified_assignee={
            "account_id": "jira-real-wilfrido",
            "display_name": "Wilfrido Hernández",
            "email": "wilfrido@empresa.test",
            "active": True,
        },
    )

    assert updated["version"] == original["version"] + 1
    edited = updated["items"][2]
    assert edited["generated"]["title"] == "Definir reglas ajustadas"
    assert edited["generated"]["description"] == "Descripción editada en la misma sesión."
    assert edited["generated"]["assignee"] == {
        "account_id": "jira-real-wilfrido",
        "display_name": "Wilfrido Hernández",
        "email": "wilfrido@empresa.test",
        "resolution": "RESOLVED",
    }
    assert edited["review"]["review_note"] == "Cambio combinado"


def test_real_jira_assignee_replaces_the_local_catalog_mapping(
    tmp_path: Path,
    sample_workbook: bytes,
):
    service = make_service(tmp_path)
    original = service.create_from_workbook(
        "plan.xlsx",
        sample_workbook,
        PlanDefaults(space="AT", tipo_seguimiento="Semanal"),
        "tester@example.com",
    )

    updated = service.update_jira_assignee(
        original["proposal_id"],
        original["items"][0]["generated"]["row_id"],
        {
            "account_id": "jira-real-giselle",
            "display_name": "Giselle Bello",
            "email": "giselle@empresa.test",
        },
        "reviewer@example.com",
    )

    assert updated["version"] == 2
    assignee = updated["items"][0]["generated"]["assignee"]
    assert assignee == {
        "account_id": "jira-real-giselle",
        "display_name": "Giselle Bello",
        "email": "giselle@empresa.test",
        "resolution": "RESOLVED",
    }
    assert "Rovo MCP" in updated["items"][0]["review"]["review_note"]


def test_general_values_create_a_new_version_and_propagate_to_every_item(
    tmp_path: Path,
    sample_workbook: bytes,
):
    service = make_service(tmp_path)
    original = service.create_from_workbook(
        "plan.xlsx",
        sample_workbook,
        PlanDefaults(space="AT", iniciativa="Valor anterior"),
        "tester@example.com",
    )

    updated = service.update_defaults(
        original["proposal_id"],
        ProposalDefaultsUpdate(
            space="ASIT",
            iniciativa="Agentes Telmex",
            linea_trabajo="Automatizaci\u00f3n",
            sprint="SPT-31-2026",
            tipo_seguimiento="Semanal",
            semaforo="Verde",
        ),
        "reviewer@example.com",
    )

    assert updated is not None
    assert updated["version"] == 2
    assert updated["defaults"]["space"] == "ASIT"
    assert all(item["generated"]["space"] == "ASIT" for item in updated["items"])
    assert all(
        item["generated"]["fields"]["iniciativa"] == "Agentes Telmex"
        and item["generated"]["fields"]["linea_trabajo"] == "Automatizaci\u00f3n"
        and item["generated"]["fields"]["sprint"] == "SPT-31-2026"
        and item["generated"]["fields"]["tipo_seguimiento"] == "Semanal"
        and item["generated"]["fields"]["semaforo"] == "Verde"
        for item in updated["items"]
    )
    assert service.repository.get(original["proposal_id"], 1)["defaults"]["iniciativa"] == "Valor anterior"


def test_editing_defaults_reopens_an_approved_proposal_as_a_new_version(
    tmp_path: Path,
    sample_workbook: bytes,
):
    service = make_service(tmp_path)
    original = service.create_from_workbook(
        "plan.xlsx", sample_workbook, PlanDefaults(space="AT"), "creator@example.com"
    )
    resolved = service.update_item(
        original["proposal_id"],
        original["items"][2]["generated"]["row_id"],
        ItemUpdate(assignee_account_id="local-account-wilfrido"),
        "reviewer@example.com",
    )
    approved = service.approve_proposal(original["proposal_id"], "approver@example.com")

    updated = service.update_defaults(
        original["proposal_id"],
        ProposalDefaultsUpdate(space="AT", tipo_seguimiento="Mensual"),
        "reviewer@example.com",
    )

    assert updated is not None
    assert updated["version"] == approved["version"] + 1
    assert updated["status"] == "VALIDATED"
    assert updated["approved_at"] is None
    assert updated["approved_by"] is None
    assert all(item["review"]["approved"] is False for item in updated["items"])
    assert service.repository.get(original["proposal_id"], approved["version"])["status"] == "APPROVED"


def test_approval_waits_for_actionable_jira_corrections(
    tmp_path: Path,
    sample_workbook: bytes,
):
    service = make_service(tmp_path)
    original = service.create_from_workbook(
        "plan.xlsx",
        sample_workbook,
        PlanDefaults(space="AT"),
        "tester@example.com",
    )
    resolved = service.update_item(
        original["proposal_id"],
        original["items"][2]["generated"]["row_id"],
        ItemUpdate(assignee_account_id="local-account-wilfrido"),
        "reviewer@example.com",
    )
    row_id = resolved["items"][0]["generated"]["row_id"]
    service.repository.save_dry_run(
        {
            "dry_run_id": "DRY-correction-guard",
            "proposal_id": original["proposal_id"],
            "proposal_version": original["version"],
            "status": "BLOCKED",
            "generated_at": "2026-07-17T18:00:00Z",
            "generated_by": "tester@example.com",
            "items": [
                {
                    "row_id": row_id,
                    "status": "BLOCKED",
                    "work_type": "Task",
                    "logical_payload": {"assignee_account_id": None},
                    "errors": [
                        {
                            "code": "ASSIGNEE_NOT_FOUND",
                            "field": "assignee",
                            "message": "Cuenta no encontrada.",
                        }
                    ],
                }
            ],
        }
    )

    with pytest.raises(ProposalStateError, match="correcciones de Jira"):
        service.approve_proposal(original["proposal_id"], "approver@example.com")

    corrected = service.update_jira_assignee(
        original["proposal_id"],
        row_id,
        {
            "account_id": "jira-real-giselle",
            "display_name": "Giselle Bello",
            "email": "giselle@empresa.test",
        },
        "reviewer@example.com",
    )
    approved = service.approve_proposal(original["proposal_id"], "approver@example.com")

    assert corrected["version"] == resolved["version"] + 1
    assert approved["status"] == "APPROVED"


def test_activity_stays_in_review_until_every_requirement_is_resolved(tmp_path: Path):
    service = make_service(tmp_path)
    workbook = workbook_bytes(
        [[
            "Definir estrategia de anonimización",
            "Wilfrido / José",
            "Diseño",
            "Proteger datos sensibles",
            None,
            "Por confirmar",
            None,
        ]]
    )
    original = service.create_from_workbook(
        "plan.xlsx",
        workbook,
        PlanDefaults(space="AT"),
        "tester@example.com",
    )
    row_id = original["items"][0]["generated"]["row_id"]
    assert [
        requirement["code"]
        for requirement in original["items"][0]["validation"]["pending_requirements"]
    ] == ["ASSIGNEE_UNRESOLVED", "SOURCE_STATE_UNCONFIRMED"]

    partially_resolved = service.update_item(
        original["proposal_id"],
        row_id,
        ItemUpdate(assignee_account_id="local-account-wilfrido"),
        "reviewer@example.com",
    )
    assert partially_resolved["items"][0]["generated"]["decision"] == "REVISAR"
    assert [
        requirement["code"]
        for requirement in partially_resolved["items"][0]["validation"]["pending_requirements"]
    ] == ["SOURCE_STATE_UNCONFIRMED"]

    resolved = service.update_item(
        original["proposal_id"],
        row_id,
        ItemUpdate(confirm_source_state=True),
        "reviewer@example.com",
    )
    assert resolved["version"] == 3
    assert resolved["items"][0]["generated"]["decision"] == "INCLUIR"
    assert resolved["items"][0]["validation"]["pending_requirements"] == []


def test_reactivation_approval_lock_and_reopen_are_versioned(
    tmp_path: Path,
    sample_workbook: bytes,
):
    service = make_service(tmp_path)
    original = service.create_from_workbook(
        "plan.xlsx", sample_workbook, PlanDefaults(space="AT"), "creator@example.com"
    )
    excluded = original["items"][1]
    review = original["items"][2]

    reactivated = service.reactivate_item(
        original["proposal_id"],
        excluded["generated"]["row_id"],
        "La actividad sigue vigente por decisión del comité.",
        "reviewer@example.com",
    )
    assert reactivated["version"] == 2
    assert reactivated["items"][1]["source"] == excluded["source"]
    assert reactivated["items"][1]["generated"]["decision"] == "REVISAR"
    assert reactivated["items"][1]["review"]["source_state_override"] == "ACTIVE"

    confirmed = service.update_item(
        original["proposal_id"],
        excluded["generated"]["row_id"],
        ItemUpdate(confirm_reactivation=True),
        "reviewer@example.com",
    )
    assert confirmed["version"] == 3
    assert confirmed["items"][1]["generated"]["decision"] == "INCLUIR"

    resolved = service.update_item(
        original["proposal_id"],
        review["generated"]["row_id"],
        ItemUpdate(assignee_account_id="local-account-wilfrido"),
        "reviewer@example.com",
    )
    assert resolved["status"] == "VALIDATED"

    approved = service.approve_proposal(original["proposal_id"], "approver@example.com")
    assert approved["version"] == 5
    assert approved["status"] == "APPROVED"
    assert approved["approved_by"] == "approver@example.com"

    try:
        service.update_item(
            original["proposal_id"],
            excluded["generated"]["row_id"],
            ItemUpdate(title="Cambio indebido"),
            "reviewer@example.com",
        )
        assert False, "La edición de una propuesta aprobada debió bloquearse."
    except ProposalStateError:
        pass

    reopened = service.reopen_proposal(original["proposal_id"], "editor@example.com")
    assert reopened["version"] == 6
    assert reopened["status"] == "VALIDATED"
    assert reopened["approved_at"] is None
    assert service.repository.get(original["proposal_id"], 5)["status"] == "APPROVED"
