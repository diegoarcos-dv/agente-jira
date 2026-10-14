from __future__ import annotations

import json
import re
from datetime import date as CalendarDate
from typing import Any

from pydantic import Field, ValidationError

from .minutes import MinutesActivity, StrictModel, canonical, date_supported
from .minutes_deterministic import ExplicitCandidate


class EnrichmentItem(StrictModel):
    candidate_id: str = Field(min_length=1, max_length=40)
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(default="", max_length=4000)
    project_or_front: str | None = Field(default=None, max_length=300)
    responsible_candidate_text: str | None = Field(default=None, max_length=200)
    due_date_candidate: CalendarDate | None = None
    requires_review: bool = True
    notes: list[str] = Field(default_factory=list, max_length=10)


class EnrichmentResponse(StrictModel):
    enrichments: list[EnrichmentItem] = Field(max_length=50)


def enrichment_payload(candidates: tuple[ExplicitCandidate, ...]) -> list[dict[str, Any]]:
    return [{"candidate_id": c.candidate_id, "source_section": c.source_section,
             "source_evidence": c.source_evidence, "text": c.normalized_text,
             "possible_duplicate": c.possible_duplicate} for c in candidates]


def _explicit_responsible(value: str | None, candidate: ExplicitCandidate) -> bool:
    if not value or canonical(value) not in canonical(candidate.source_evidence):
        return False
    return bool(re.search(r"\b(responsable|a cargo|asignad[oa]|se compromete|realizar[aá]|deber[aá]|confirmar[aá]|coordinar[aá]|ejecutar[aá])\b", canonical(candidate.source_evidence)))


def _safe_item(candidate: ExplicitCandidate, item: EnrichmentItem | None) -> MinutesActivity:
    title = candidate.normalized_text.rstrip(".")[:200] or "Actividad pendiente"
    description = candidate.source_evidence[:4000]
    responsible = None
    due = None
    project = None
    notes: list[str] = []
    if item is not None:
        if item.title.strip():
            title = item.title.strip()[:200]
        if item.description.strip():
            description = item.description.strip()[:4000]
        if item.project_or_front and canonical(item.project_or_front) in canonical(candidate.source_evidence):
            project = item.project_or_front.strip()[:300]
        if _explicit_responsible(item.responsible_candidate_text, candidate):
            responsible = item.responsible_candidate_text.strip()[:200]
        elif item.responsible_candidate_text:
            notes.append("Responsable sugerido por IA sin atribución explícita; por definir.")
        if item.due_date_candidate and date_supported(item.due_date_candidate, candidate.source_evidence):
            due = item.due_date_candidate
        elif item.due_date_candidate:
            notes.append("Fecha sugerida por IA sin evidencia explícita; por definir.")
        notes.extend(item.notes)
    return MinutesActivity(title=title, description=description if len(description) >= 3 else title,
        responsible_candidate=responsible, responsible_evidence=(candidate.source_evidence if responsible else None),
        due_date_candidate=due, due_date_evidence=(candidate.source_evidence if due else None),
        project_or_front=project, source_section=candidate.source_section,
        source_evidence=candidate.source_evidence, work_type_candidate="Task", inferred=False,
        requires_review=True)


def build_activities(candidates: tuple[ExplicitCandidate, ...], raw: str | None) -> tuple[list[MinutesActivity], list[str], bool]:
    """Apply an enrichment response without trusting it for identity/evidence.

    Returns activities, warnings, and a boolean indicating whether the response
    passed cardinality and schema validation.
    """
    activities, warnings, ok, _ = build_activities_with_diagnostics(candidates, raw)
    return activities, warnings, ok


def build_activities_with_diagnostics(
    candidates: tuple[ExplicitCandidate, ...], raw: str | None,
) -> tuple[list[MinutesActivity], list[str], bool, str | None]:
    """Validate a completed model response and retain exact deterministic fallback."""
    fallback = [_safe_item(candidate, None) for candidate in candidates]
    if not raw:
        return fallback, [], False, "MINUTES_ENRICHMENT_EMPTY_RESPONSE"
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return fallback, ["Ollama respondió, pero el contenido no es JSON válido."], False, "MINUTES_ENRICHMENT_INVALID_JSON"
    try:
        parsed = EnrichmentResponse.model_validate(payload)
    except (ValidationError, ValueError, TypeError):
        return fallback, ["La respuesta JSON del modelo no pasó la validación de enrichment."], False, "MINUTES_ENRICHMENT_SCHEMA_INVALID"
    expected = {c.candidate_id for c in candidates}
    received = [item.candidate_id for item in parsed.enrichments]
    if set(received) != expected or len(received) != len(expected):
        return fallback, ["La respuesta de IA no corresponde uno a uno con los candidate_id de origen."], False, "MINUTES_ENRICHMENT_CANDIDATE_MISMATCH"
    by_id = {item.candidate_id: item for item in parsed.enrichments}
    return [_safe_item(candidate, by_id[candidate.candidate_id]) for candidate in candidates], [], True, None
