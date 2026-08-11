from __future__ import annotations

import re
from typing import Any, Iterable


BUG_TERMS = re.compile(
    r"\b(bug|error|falla|defecto|cors|incidencia|no funciona|bloqueo)\b",
    re.IGNORECASE,
)
STORY_TERMS = re.compile(
    r"\b(como usuario|historia|requerimiento|capacidad|caso de uso)\b",
    re.IGNORECASE,
)
EPIC_TERMS = re.compile(
    r"\b(epic|épica|programa|iniciativa|proyecto completo|migración integral)\b",
    re.IGNORECASE,
)
SUBTASK_TERMS = re.compile(r"\b(subtask|subtarea|sub-tarea)\b", re.IGNORECASE)


def normalize_title(activity: str) -> str:
    title = re.sub(r"\s+", " ", activity).strip(" \t\r\n-")
    if len(title) <= 140:
        return title
    return title[:137].rstrip() + "..."


def infer_work_type(activity: str, context: str | None = None) -> tuple[str, float, str]:
    evidence = " ".join(part for part in (activity, context) if part)
    if BUG_TERMS.search(evidence):
        return "Bug", 0.96, "El texto describe un error, falla, defecto o incidencia."
    if SUBTASK_TERMS.search(evidence):
        return "Subtask", 0.84, "El texto identifica explícitamente una subtarea."
    if EPIC_TERMS.search(evidence):
        return "Epic", 0.78, "El texto parece representar una iniciativa amplia."
    if STORY_TERMS.search(evidence):
        return "Story", 0.82, "El texto expresa una necesidad o capacidad funcional."
    return "Task", 0.88, "La actividad describe trabajo concreto sin evidencia de otro tipo."


def build_description(source: dict[str, Any]) -> str:
    sections = [f"Actividad: {source['actividad']}"]
    if source.get("contexto_resultado"):
        sections.append(f"Resultado esperado: {source['contexto_resultado']}")
    if source.get("frente_trabajo_origen"):
        sections.append(f"Frente de trabajo: {source['frente_trabajo_origen']}")
    if source.get("comentarios"):
        sections.append(f"Antecedentes o restricciones: {source['comentarios']}")
    if source.get("fecha_objetivo"):
        sections.append(f"Fecha objetivo informada: {source['fecha_objetivo']}")
    sections.append(f"Referencia de origen: fila {source['source_row']} de la plantilla.")
    return "\n\n".join(sections)


def collect_review_requirements(
    source: dict[str, Any],
    assignee: dict[str, str | None],
    work_type: str,
    work_type_confidence: float,
    *,
    parent_row_id: str | None = None,
    confirmed_fields: Iterable[str] = (),
    source_state_overridden: bool = False,
    reactivation_reviewed: bool = False,
) -> list[dict[str, str]]:
    """Return every actionable blocker instead of stopping at the first one."""

    confirmed = set(confirmed_fields)
    requirements: list[dict[str, str]] = []
    if source_state_overridden and not reactivation_reviewed:
        requirements.append(
            {
                "code": "REACTIVATION_REVIEW_REQUIRED",
                "field": "confirm_reactivation",
                "message": "Revisa los campos y confirma la reactivación de la actividad.",
            }
        )
    if assignee["resolution"] != "RESOLVED":
        reason_by_resolution = {
            "AMBIGUOUS": "Selecciona una sola persona del catálogo.",
            "NOT_FOUND": "Selecciona un responsable disponible en el catálogo.",
            "INACTIVE": "Selecciona un responsable activo en el catálogo.",
        }
        requirements.append(
            {
                "code": "ASSIGNEE_UNRESOLVED",
                "field": "assignee_account_id",
                "message": reason_by_resolution.get(
                    str(assignee["resolution"]),
                    "Selecciona un responsable único.",
                ),
            }
        )
    if source["estado_actual"] == "Por confirmar" and "source_state" not in confirmed:
        requirements.append(
            {
                "code": "SOURCE_STATE_UNCONFIRMED",
                "field": "confirm_source_state",
                "message": "Confirma que la actividad sigue vigente.",
            }
        )
    if work_type == "Subtask" and not parent_row_id:
        requirements.append(
            {
                "code": "SUBTASK_PARENT_MISSING",
                "field": "work_type",
                "message": "Cambia el Work Type o identifica una actividad padre.",
            }
        )
    if work_type_confidence < 0.8 and "work_type" not in confirmed:
        requirements.append(
            {
                "code": "WORK_TYPE_UNCONFIRMED",
                "field": "work_type",
                "message": "Confirma el Work Type propuesto.",
            }
        )
    return requirements


def decide(
    source: dict[str, Any],
    assignee: dict[str, str | None],
    work_type: str,
    work_type_confidence: float,
    *,
    parent_row_id: str | None = None,
    confirmed_fields: Iterable[str] = (),
    source_state_overridden: bool = False,
    reactivation_reviewed: bool = False,
) -> tuple[str, str, list[str]]:
    state = source["estado_actual"]
    warnings: list[str] = []
    if state in {"Completada", "Rechazada"} and not source_state_overridden:
        return (
            "EXCLUIR",
            f"La actividad está marcada como {state.lower()} en el archivo fuente.",
            warnings,
        )

    requirements = collect_review_requirements(
        source,
        assignee,
        work_type,
        work_type_confidence,
        parent_row_id=parent_row_id,
        confirmed_fields=confirmed_fields,
        source_state_overridden=source_state_overridden,
        reactivation_reviewed=reactivation_reviewed,
    )
    if requirements:
        return (
            "REVISAR",
            "Pendientes por resolver: "
            + " ".join(requirement["message"] for requirement in requirements),
            warnings,
        )
    return (
        "INCLUIR",
        "La fila cumple los campos mínimos y las reglas deterministas del MVP.",
        warnings,
    )
