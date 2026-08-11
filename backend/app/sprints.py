from __future__ import annotations

import unicodedata
from typing import Any


VALID_SPRINT_STATES = frozenset({"active", "future"})


def normalize_sprint_text(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(character for character in text if not unicodedata.combining(character))
    return " ".join(text.casefold().split())


def normalize_sprint_catalog(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return a deterministic, safe catalog keyed by Jira's numeric Sprint ID."""

    by_id: dict[str, dict[str, Any]] = {}
    for value in values:
        sprint_id = str(value.get("id") or "").strip()
        name = str(value.get("name") or "").strip()
        state = str(value.get("state") or "").strip().casefold()
        if not sprint_id.isdigit() or not name or state not in VALID_SPRINT_STATES:
            continue
        normalized = {
            "id": sprint_id,
            "name": name,
            "state": state,
            "board_id": (
                str(value.get("board_id") or value.get("boardId"))
                if value.get("board_id") is not None or value.get("boardId") is not None
                else None
            ),
            "source": str(value.get("source") or "JIRA_MCP_JQL"),
        }
        previous = by_id.get(sprint_id)
        if previous is None or (previous["state"] == "future" and state == "active"):
            by_id[sprint_id] = normalized
    return sorted(
        by_id.values(),
        key=lambda sprint: (sprint["state"] != "active", normalize_sprint_text(sprint["name"]), int(sprint["id"])),
    )


def resolve_sprint(
    requested: str | None,
    catalog: list[dict[str, Any]],
) -> dict[str, Any]:
    """Apply PLAN_VALUE_THEN_ACTIVE without silently choosing an ambiguous Sprint."""

    sprints = normalize_sprint_catalog(catalog)
    requested_text = str(requested or "").strip()
    if requested_text:
        requested_key = normalize_sprint_text(requested_text)
        matches = [
            sprint
            for sprint in sprints
            if sprint["id"] == requested_text
            or normalize_sprint_text(sprint["name"]) == requested_key
        ]
        if len(matches) == 1:
            return {
                "selected": matches[0],
                "mode": "ID_MATCH" if matches[0]["id"] == requested_text else "PLAN_NAME_MATCH",
                "requested": requested_text,
                "error": None,
                "warning": None,
            }
        if len(matches) > 1:
            return {
                "selected": None,
                "mode": "AMBIGUOUS_PLAN_VALUE",
                "requested": requested_text,
                "error": {
                    "code": "SPRINT_AMBIGUOUS",
                    "field": "sprint",
                    "message": f"Jira devolvio mas de un Sprint vigente llamado '{requested_text}'. Selecciona uno de la lista.",
                },
                "warning": None,
            }
        return {
            "selected": None,
            "mode": "PLAN_VALUE_NOT_FOUND",
            "requested": requested_text,
            "error": {
                "code": "SPRINT_NOT_FOUND",
                "field": "sprint",
                "message": f"El Sprint '{requested_text}' no existe o ya no esta activo/futuro en Jira. Actualiza el catalogo y selecciona un valor vigente.",
            },
            "warning": None,
        }

    active = [sprint for sprint in sprints if sprint["state"] == "active"]
    if len(active) == 1:
        return {
            "selected": active[0],
            "mode": "AUTO_SINGLE_ACTIVE",
            "requested": None,
            "error": None,
            "warning": {
                "code": "SPRINT_AUTO_SELECTED",
                "field": "sprint",
                "message": f"Se selecciono automaticamente el unico Sprint activo: '{active[0]['name']}'.",
            },
        }
    if len(active) > 1:
        return {
            "selected": None,
            "mode": "MULTIPLE_ACTIVE",
            "requested": None,
            "error": {
                "code": "SPRINT_SELECTION_REQUIRED",
                "field": "sprint",
                "message": "Hay mas de un Sprint activo visible para este Space. Selecciona uno antes de continuar.",
            },
            "warning": None,
        }
    return {
        "selected": None,
        "mode": "NO_ACTIVE_SPRINT",
        "requested": None,
        "error": None,
        "warning": {
            "code": "SPRINT_NOT_SELECTED",
            "field": "sprint",
            "message": "No hay un Sprint activo visible. La actividad continuara sin Sprint, salvo que selecciones uno futuro.",
        },
    }


def revalidate_sprint(
    sprint_id: str,
    catalog: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Return the current active/future Sprint or None when it can no longer be proven safe."""

    return next(
        (sprint for sprint in normalize_sprint_catalog(catalog) if sprint["id"] == str(sprint_id)),
        None,
    )
