from __future__ import annotations

from typing import Any


USER_ACTION_CODES = {
    "ASSIGNEE_REQUIRED",
    "ASSIGNEE_NOT_FOUND",
    "ASSIGNEE_AMBIGUOUS",
    "ASSIGNEE_INACTIVE",
    "ASSIGNEE_NOT_ASSIGNABLE",
    "TITLE_REQUIRED",
    "DESCRIPTION_REQUIRED",
    "WORK_TYPE_NOT_AVAILABLE",
}


def _user_instruction(issue: dict[str, Any]) -> str:
    field = issue.get("field")
    if field == "assignee":
        return "Busca y selecciona una cuenta Jira real para esta actividad."
    if field == "title":
        return "Completa o corrige el título de la actividad."
    if field == "description":
        return "Completa o corrige la descripción de la actividad."
    if field == "work_type":
        return "Selecciona un Work Type disponible en el Space."
    return "Corrige el dato indicado y guarda la actividad."


def _technical_instruction(_issues: list[dict[str, Any]]) -> str:
    return (
        "No necesitas modificar esta actividad. La aplicación debe completar "
        "esta validación técnica en la prevalidación final."
    )


def _was_corrected(
    proposal_item: dict[str, Any],
    dry_item: dict[str, Any],
    issue: dict[str, Any],
) -> bool:
    generated = proposal_item.get("generated", {})
    review = proposal_item.get("review", {})
    historical = dry_item.get("logical_payload") or {}
    field = issue.get("field")

    if field == "assignee":
        current = generated.get("assignee") or {}
        current_account = current.get("account_id")
        old_account = historical.get("assignee_account_id")
        verified_by_rovo = str(review.get("review_note") or "").startswith(
            "Responsable verificado contra Jira"
        )
        return bool(
            current_account
            and current_account != old_account
            and verified_by_rovo
        )
    if field == "title":
        return bool(str(generated.get("title") or "").strip()) and (
            generated.get("title") != historical.get("summary")
        )
    if field == "description":
        return bool(str(generated.get("description") or "").strip()) and (
            generated.get("description") != historical.get("description")
        )
    if field == "work_type":
        return generated.get("work_type") != dry_item.get("work_type")
    return False


def build_correction_workflow(
    proposal: dict[str, Any],
    dry_run: dict[str, Any],
) -> dict[str, Any]:
    active = (
        dry_run.get("status") == "BLOCKED"
        and dry_run.get("proposal_version") != proposal.get("version")
        and proposal.get("status") != "APPROVED"
    )
    proposal_items = {
        item.get("generated", {}).get("row_id"): item
        for item in proposal.get("items", [])
    }
    items: list[dict[str, Any]] = []

    if active:
        for dry_item in dry_run.get("items", []):
            if dry_item.get("status") != "BLOCKED":
                continue
            row_id = dry_item.get("row_id")
            proposal_item = proposal_items.get(row_id)
            if proposal_item is None:
                continue
            errors = dry_item.get("errors", [])
            user_issues = [
                issue for issue in errors if issue.get("code") in USER_ACTION_CODES
            ]
            technical_issues = [
                issue for issue in errors if issue.get("code") not in USER_ACTION_CODES
            ]
            unresolved_user = [
                issue
                for issue in user_issues
                if not _was_corrected(proposal_item, dry_item, issue)
            ]

            if unresolved_user:
                category = "USER_ACTION"
                instruction = _user_instruction(unresolved_user[0])
                visible_issues = unresolved_user
            elif technical_issues:
                category = "TECHNICAL"
                instruction = _technical_instruction(technical_issues)
                visible_issues = technical_issues
            else:
                category = "CORRECTED"
                instruction = (
                    "La corrección fue guardada y se comprobará en la "
                    "prevalidación final."
                )
                visible_issues = user_issues

            items.append(
                {
                    "row_id": row_id,
                    "category": category,
                    "instruction": instruction,
                    "issues": visible_issues,
                }
            )

    return {
        "active": active,
        "summary": {
            "pending_user": sum(
                item["category"] == "USER_ACTION" for item in items
            ),
            "technical": sum(item["category"] == "TECHNICAL" for item in items),
            "corrected": sum(item["category"] == "CORRECTED" for item in items),
        },
        "items": items,
    }
