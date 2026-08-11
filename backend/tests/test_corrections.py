from app.corrections import build_correction_workflow


def _proposal_item(row_id: str, account_id: str, review_note: str | None = None):
    return {
        "generated": {
            "row_id": row_id,
            "title": f"Actividad {row_id}",
            "description": "Descripcion completa",
            "work_type": "Task",
            "assignee": {"account_id": account_id},
        },
        "review": {"review_note": review_note},
    }


def test_correction_workflow_separates_user_technical_and_corrected_rows():
    proposal = {
        "version": 7,
        "status": "VALIDATED",
        "items": [
            _proposal_item("ROW-1", "local-vicente"),
            _proposal_item("ROW-2", "jira-alfredo"),
            _proposal_item(
                "ROW-3",
                "jira-raul",
                "Responsable verificado contra Jira mediante Rovo MCP.",
            ),
        ],
    }
    dry_run = {
        "proposal_version": 6,
        "status": "BLOCKED",
        "items": [
            {
                "row_id": "ROW-1",
                "status": "BLOCKED",
                "work_type": "Task",
                "logical_payload": {"assignee_account_id": None},
                "errors": [{"code": "ASSIGNEE_NOT_FOUND", "field": "assignee", "message": "No encontrada"}],
            },
            {
                "row_id": "ROW-2",
                "status": "BLOCKED",
                "work_type": "Task",
                "logical_payload": {"assignee_account_id": "jira-alfredo"},
                "errors": [{"code": "ASSIGNEE_ASSIGNABILITY_UNVERIFIED", "field": "assignee", "message": "Sin evidencia"}],
            },
            {
                "row_id": "ROW-3",
                "status": "BLOCKED",
                "work_type": "Task",
                "logical_payload": {"assignee_account_id": None},
                "errors": [{"code": "ASSIGNEE_NOT_FOUND", "field": "assignee", "message": "No encontrada"}],
            },
        ],
    }

    workflow = build_correction_workflow(proposal, dry_run)

    assert workflow["active"] is True
    assert workflow["summary"] == {
        "pending_user": 1,
        "technical": 1,
        "corrected": 1,
    }
    assert [item["category"] for item in workflow["items"]] == [
        "USER_ACTION",
        "TECHNICAL",
        "CORRECTED",
    ]


def test_correction_workflow_is_inactive_for_same_version():
    proposal = {"version": 6, "status": "APPROVED", "items": []}
    dry_run = {"proposal_version": 6, "status": "BLOCKED", "items": []}

    workflow = build_correction_workflow(proposal, dry_run)

    assert workflow["active"] is False
    assert workflow["summary"] == {
        "pending_user": 0,
        "technical": 0,
        "corrected": 0,
    }
