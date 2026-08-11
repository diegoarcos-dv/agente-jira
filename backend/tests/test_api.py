from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_reports_read_only_atlassian_capability(client: TestClient):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "mode": "local",
        "external_connections": True,
        "atlassian_mcp_mode": "read_only",
        "jira_write_enabled": False,
        "objective_4a_mode": "simulation_only",
        "template_version": "1.1",
    }


def test_login_rejects_invalid_password(client: TestClient):
    response = client.post(
        "/api/auth/login",
        json={"username": "admin@agentejira.local", "password": "incorrecta"},
    )
    assert response.status_code == 401


def test_upload_review_and_version_flow(
    client: TestClient,
    auth_headers: dict[str, str],
    sample_workbook: bytes,
):
    created = client.post(
        "/api/proposals",
        headers=auth_headers,
        files={
            "file": (
                "plan.xlsx",
                sample_workbook,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        data={"space": "AT", "iniciativa": "Piloto"},
    )
    assert created.status_code == 201, created.text
    proposal = created.json()
    assert len(proposal["items"]) == 3

    listed = client.get("/api/proposals", headers=auth_headers)
    assert listed.status_code == 200
    assert listed.json()[0]["counts"] == {
        "INCLUIR": 1,
        "REVISAR": 1,
        "EXCLUIR": 1,
    }
    assignees = client.get("/api/assignees", headers=auth_headers)
    assert assignees.status_code == 200
    assert any(
        assignee["account_id"] == "local-account-wilfrido"
        for assignee in assignees.json()
    )

    review_item = next(
        item for item in proposal["items"] if item["generated"]["decision"] == "REVISAR"
    )
    updated = client.patch(
        f"/api/proposals/{proposal['proposal_id']}/items/{review_item['generated']['row_id']}",
        headers=auth_headers,
        json={
            "title": "Definir reglas del backend",
            "description": review_item["generated"]["description"],
            "work_type": "Task",
            "review_note": "Revisión local",
            "assignee_account_id": "local-account-wilfrido",
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["version"] == 2
    assert updated.json()["status"] == "VALIDATED"
    updated_item = next(
        item
        for item in updated.json()["items"]
        if item["generated"]["row_id"] == review_item["generated"]["row_id"]
    )
    assert updated_item["generated"]["assignee"]["resolution"] == "RESOLVED"
    assert updated_item["generated"]["decision"] == "INCLUIR"
    assert updated_item["validation"]["pending_requirements"] == []

    archived = client.post(
        f"/api/proposals/{proposal['proposal_id']}/archive",
        headers=auth_headers,
    )
    assert archived.status_code == 200
    assert archived.json()["archived"] is True

    listed_archived = client.get("/api/proposals", headers=auth_headers)
    assert listed_archived.json()[0]["archived"] is True

    restored = client.post(
        f"/api/proposals/{proposal['proposal_id']}/restore",
        headers=auth_headers,
    )
    assert restored.status_code == 200
    assert restored.json()["archived"] is False

    renamed = client.patch(
        f"/api/proposals/{proposal['proposal_id']}/metadata",
        headers=auth_headers,
        json={"display_name": "Plan de reclasificación AT"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["display_name"] == "Plan de reclasificación AT"
    assert renamed.json()["source_file"] == "plan.xlsx"

    approved = client.post(
        f"/api/proposals/{proposal['proposal_id']}/approve",
        headers=auth_headers,
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "APPROVED"

    download = client.get(
        f"/api/proposals/{proposal['proposal_id']}/approved-export",
        headers=auth_headers,
    )
    assert download.status_code == 200
    assert download.json()["display_name"] == "Plan de reclasificación AT"
    assert download.json()["proposal"]["status"] == "APPROVED"
    assert "attachment" in download.headers["content-disposition"]

    locked = client.patch(
        f"/api/proposals/{proposal['proposal_id']}/items/{review_item['generated']['row_id']}",
        headers=auth_headers,
        json={"title": "Cambio no permitido"},
    )
    assert locked.status_code == 409

    reopened = client.post(
        f"/api/proposals/{proposal['proposal_id']}/reopen",
        headers=auth_headers,
    )
    assert reopened.status_code == 200
    assert reopened.json()["status"] == "VALIDATED"

    class JiraLookup:
        async def find_assignees(self, _username: str, space: str, query: str):
            assert space == "AT"
            assert query == "Wilfrido Hernández"
            return [{
                "account_id": "jira-real-wilfrido",
                "display_name": "Wilfrido Hernández",
                "email": "wilfrido@empresa.test",
                "active": True,
            }]

    client.app.state.atlassian_manager = JiraLookup()
    real_assignee = client.patch(
        f"/api/proposals/{proposal['proposal_id']}/items/{review_item['generated']['row_id']}/jira-assignee",
        headers=auth_headers,
        json={
            "account_id": "jira-real-wilfrido",
            "query": "Wilfrido Hernández",
        },
    )
    assert real_assignee.status_code == 200, real_assignee.text
    assert real_assignee.json()["version"] == 5
    updated_real_item = next(
        item
        for item in real_assignee.json()["items"]
        if item["generated"]["row_id"] == review_item["generated"]["row_id"]
    )
    assert updated_real_item["generated"]["assignee"]["account_id"] == "jira-real-wilfrido"


def test_upload_returns_actionable_header_error(
    client: TestClient,
    auth_headers: dict[str, str],
):
    response = client.post(
        "/api/proposals",
        headers=auth_headers,
        files={
            "file": (
                "plan.xlsx",
                b"not-an-xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        data={"space": "AT"},
    )
    assert response.status_code == 422
    assert response.json()["issues"][0]["code"] == "INVALID_XLSX"


def test_general_values_endpoint_versions_and_propagates_the_plan(
    client: TestClient,
    auth_headers: dict[str, str],
    sample_workbook: bytes,
):
    created = client.post(
        "/api/proposals",
        headers=auth_headers,
        files={
            "file": (
                "plan.xlsx",
                sample_workbook,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        data={"space": "AT", "iniciativa": "Original"},
    ).json()

    response = client.patch(
        f"/api/proposals/{created['proposal_id']}/defaults",
        headers=auth_headers,
        json={
            "space": "MTTI",
            "iniciativa": "Agentes Telmex",
            "linea_trabajo": "Automatizaci\u00f3n",
            "sprint": "SPT-31-2026",
            "tipo_seguimiento": "Semanal",
            "semaforo": "Verde",
        },
    )

    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["version"] == created["version"] + 1
    assert updated["defaults"]["space"] == "MTTI"
    assert all(item["generated"]["space"] == "MTTI" for item in updated["items"])
    assert all(
        item["generated"]["fields"]["tipo_seguimiento"] == "Semanal"
        for item in updated["items"]
    )


def test_template_download_is_available_without_productive_credentials(client: TestClient):
    response = client.get("/api/template")
    assert response.status_code == 200
    assert response.content[:2] == b"PK"
