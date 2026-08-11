from __future__ import annotations

from typing import Any


STANDARD_WORK_TYPES = {"Task", "Bug", "Story"}


class JiraHierarchyError(ValueError):
    pass


def allowed_parent_types(child_work_type: str) -> set[str]:
    if child_work_type == "Subtask":
        return set(STANDARD_WORK_TYPES)
    if child_work_type in STANDARD_WORK_TYPES:
        return {"Epic"}
    return set()


def validate_parent_relation(
    child_row_id: str,
    child_work_type: str,
    parent_row_id: str | None,
    items_by_row: dict[str, dict[str, Any]],
    *,
    require_included: bool = False,
) -> None:
    required = child_work_type == "Subtask"
    if not parent_row_id:
        if required:
            raise JiraHierarchyError("Una Subtask requiere una actividad padre de tipo Task, Bug o Story.")
        return
    if parent_row_id == child_row_id:
        raise JiraHierarchyError("Una actividad no puede ser su propia actividad padre.")
    parent = items_by_row.get(parent_row_id)
    if parent is None:
        raise JiraHierarchyError(f"La actividad padre {parent_row_id} no existe en esta propuesta.")
    generated = parent.get("generated") or parent
    if require_included and generated.get("decision") != "INCLUIR":
        raise JiraHierarchyError("La actividad padre debe estar incluida en la propuesta.")
    if generated.get("decision") == "EXCLUIR":
        raise JiraHierarchyError("Una actividad excluida no puede usarse como actividad padre.")
    parent_work_type = str(generated.get("work_type") or "")
    allowed = allowed_parent_types(child_work_type)
    if parent_work_type not in allowed:
        if child_work_type == "Subtask":
            raise JiraHierarchyError("Una Subtask sólo puede depender directamente de una Task, Bug o Story.")
        if child_work_type in STANDARD_WORK_TYPES:
            raise JiraHierarchyError(f"Una {child_work_type} sólo puede usar una Epic como actividad padre.")
        raise JiraHierarchyError(f"Una {child_work_type} no admite actividad padre en este objetivo.")


def ordered_row_ids(
    selected_row_ids: list[str],
    parent_by_row: dict[str, str | None],
) -> list[str]:
    """Stable topological order; raises on a dependency cycle."""

    selected = set(selected_row_ids)
    order_index = {row_id: index for index, row_id in enumerate(selected_row_ids)}
    children: dict[str, list[str]] = {row_id: [] for row_id in selected_row_ids}
    indegree = {row_id: 0 for row_id in selected_row_ids}
    for child, parent in parent_by_row.items():
        if child in selected and parent in selected:
            children[parent].append(child)
            indegree[child] += 1
    ready = sorted((row for row, degree in indegree.items() if degree == 0), key=order_index.get)
    result: list[str] = []
    while ready:
        row_id = ready.pop(0)
        result.append(row_id)
        for child in sorted(children[row_id], key=order_index.get):
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
                ready.sort(key=order_index.get)
    if len(result) != len(selected_row_ids):
        raise JiraHierarchyError("La selección contiene un ciclo en las relaciones padre-hijo.")
    return result
