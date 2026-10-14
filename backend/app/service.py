from __future__ import annotations

import copy
import uuid
from time import perf_counter
from datetime import UTC, datetime
from typing import Any

from .catalog import FakeAssigneeCatalog, normalize_name
from .corrections import build_correction_workflow
from .errors import ProposalStateError
from .models import BulkProposalUpdate, ItemUpdate, PlanDefaults, ProposalDefaultsUpdate
from .hierarchy import JiraHierarchyError, validate_parent_relation
from .parser import ParsedPlan, TemplateParser
from .repository import ProposalRepository
from .rules import (
    build_description,
    collect_review_requirements,
    decide,
    infer_work_type,
    normalize_title,
)
from .schema import ProposalSchemaValidator
from .performance import current_trace


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


class ProposalService:
    def __init__(
        self,
        repository: ProposalRepository,
        validator: ProposalSchemaValidator,
        parser: TemplateParser | None = None,
        catalog: FakeAssigneeCatalog | None = None,
    ):
        self.repository = repository
        self.validator = validator
        self.parser = parser or TemplateParser()
        self.catalog = catalog or FakeAssigneeCatalog()

    def create_from_workbook(
        self,
        filename: str,
        content: bytes,
        defaults: PlanDefaults,
        created_by: str,
        *,
        parsed: ParsedPlan | None = None,
        assignee_overrides: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        trace = current_trace()
        started = perf_counter()
        parse_started = perf_counter()
        parsed = parsed or self.parser.parse(filename, content)
        if trace is not None:
            trace.record_phase("import_parse", (perf_counter() - parse_started) * 1000)
        rules_started = perf_counter()
        proposal = self._build_proposal(
            parsed,
            defaults,
            created_by,
            assignee_overrides=assignee_overrides,
        )
        if trace is not None:
            trace.record_phase("normalization_rules_proposal", (perf_counter() - rules_started) * 1000)
        validation_started = perf_counter()
        self.validator.validate(proposal)
        stored = self.repository.save(proposal)
        if trace is not None:
            trace.record_phase("proposal_validation_save", (perf_counter() - validation_started) * 1000)
            trace.record_phase("proposal_total", (perf_counter() - started) * 1000)
        return stored

    def _build_proposal(
        self,
        parsed: ParsedPlan,
        defaults: PlanDefaults,
        created_by: str,
        *,
        resolve_assignees: bool = True,
        assignee_overrides: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        items = []
        for source in parsed.rows:
            captured_responsible = source["responsable_display"]
            override = (assignee_overrides or {}).get(normalize_name(captured_responsible))
            assignee = override or (
                self.catalog.resolve(captured_responsible)
                if resolve_assignees
                else {
                    "display_name": captured_responsible,
                    "email": None,
                    "account_id": None,
                    "resolution": "NOT_FOUND",
                }
            )
            work_type, confidence, type_reason = infer_work_type(
                source["actividad"],
                source.get("contexto_resultado"),
            )
            decision, decision_reason, warnings = decide(
                source,
                assignee,
                work_type,
                confidence,
            )
            pending_requirements = collect_review_requirements(
                source,
                assignee,
                work_type,
                confidence,
            )
            warnings.append(type_reason)
            items.append(
                {
                    "source": source,
                    "generated": {
                        "row_id": f"ROW-{source['source_row']:04d}",
                        "create_in_jira": decision == "INCLUIR",
                        "decision": decision,
                        "decision_reason": decision_reason,
                        "work_type": work_type,
                        "title": normalize_title(source["actividad"]),
                        "description": build_description(source),
                        "space": defaults.space,
                        "parent_row_id": None,
                        "assignee": assignee,
                        "fields": {
                            "iniciativa": clean_optional(defaults.iniciativa),
                            "linea_trabajo": clean_optional(defaults.linea_trabajo),
                            "sprint": clean_optional(defaults.sprint),
                            "tipo_seguimiento": clean_optional(
                                source.get("tipo_seguimiento_origen") or defaults.tipo_seguimiento
                            ),
                            "semaforo": clean_optional(defaults.semaforo),
                            "due_date": source.get("fecha_objetivo"),
                        },
                        "confidence": confidence,
                    },
                    "validation": {
                        "errors": [],
                        "warnings": warnings,
                        "pending_requirements": pending_requirements,
                    },
                    "review": {
                        "user_modified": False,
                        "approved": False,
                        "review_note": None,
                        "confirmed_fields": [],
                        "source_state_override": None,
                        "source_state_override_reason": None,
                        "source_state_override_at": None,
                        "source_state_override_by": None,
                        "reactivation_reviewed": False,
                    },
                    "execution": {
                        "idempotency_key": None,
                        "jira_issue_key": None,
                        "result": "NOT_STARTED",
                        "error_code": None,
                    },
                }
            )

        status = "NEEDS_INPUT" if any(
            item["generated"]["decision"] == "REVISAR" for item in items
        ) else "VALIDATED"
        return {
            "proposal_id": str(uuid.uuid4()),
            "version": 1,
            "template_version": parsed.template_version,
            "status": status,
            "source_file": {"name": parsed.filename, "sha256": parsed.sha256},
            "defaults": defaults.model_dump(),
            "items": items,
            "created_at": utc_now(),
            "created_by": created_by,
            "approved_at": None,
            "approved_by": None,
        }

    def create_from_minutes(self, document, document_hash, warnings, notes, created_by, *, prompt_version="minutes-v1",
                            extraction_mode="LLM_INFERRED", enrichment=None):

        rows = [{
            "source_row": index + 6, "actividad": activity.title,
            "responsable_display": activity.responsible_candidate or "Por definir",
            "frente_trabajo_origen": activity.project_or_front or document.project,
            "contexto_resultado": activity.description,
            "fecha_objetivo": activity.due_date_candidate.isoformat() if activity.due_date_candidate else None,
            "estado_actual": "Por confirmar", "comentarios": None,
            "tipo_seguimiento_origen": None, "source_section": activity.source_section,
            "source_evidence": activity.source_evidence, "inferred": activity.inferred,
        } for index, activity in enumerate(document.activities)]
        # ParsedPlan is the normalized data carrier; no workbook or Excel parser is used.
        parsed = ParsedPlan("Minuta — " + (document.project or "Notas de reunión"), document_hash, "1.2", rows)
        proposal = self._build_proposal(parsed, PlanDefaults(space="AT"), created_by, resolve_assignees=False)
        for item, activity, activity_notes in zip(proposal["items"], document.activities, notes):
            item["generated"]["work_type"] = activity.work_type_candidate
            item["generated"]["confidence"] = .7  # Candidate, always needs human confirmation.
            item["generated"]["description"] = activity.description
            self._revalidate_item(item)
            item["validation"]["warnings"] = [
                "Extraída de minuta; revisa el compromiso y verifica los campos con Jira.",
                "El responsable candidato requiere seleccionar una persona en Jira.",
                *activity_notes,
            ]
        proposal["minutes"] = {"prompt_version": prompt_version, "extraction_mode": extraction_mode,
            "document": document.model_dump(mode="json", exclude={"activities"}), "warnings": warnings}
        if enrichment is not None:
            proposal["minutes"]["enrichment"] = enrichment
        self.validator.validate(proposal)
        return self.repository.save(proposal)

    def create_from_minute_draft(self, draft: dict[str, Any], created_by: str) -> dict[str, Any]:
        """Create a Proposal from the edited draft without parsing or invoking AI again."""
        rows = [{
            "source_row": index + 6,
            "actividad": row["actividad"],
            "responsable_display": row["responsable"],
            "frente_trabajo_origen": row.get("proyecto_o_frente"),
            "contexto_resultado": row.get("contexto_o_resultado"),
            "fecha_objetivo": row.get("fecha_objetivo"),
            "estado_actual": "Por confirmar",
            "comentarios": row.get("comentarios"),
            "tipo_seguimiento_origen": row.get("tipo_de_seguimiento"),
            "area_responsable": row.get("area_responsable"),
            "area_source": row.get("area_source") or "LOCAL",
            "area_status": row.get("area_status") or "UNSPECIFIED",
            "area_candidates": row.get("area_candidates") or [],
            "area_mentions": row.get("area_mentions") or [],
            "source_section": row.get("source_section"),
            "source_evidence": row.get("source_evidence") or "Actividad capturada en borrador.",
            "inferred": row.get("extraction_mode") == "LLM_INFERRED",
        } for index, row in enumerate(draft["rows"])]
        parsed = ParsedPlan(
            "Minuta — " + (draft.get("document", {}).get("project") or "Plan de trabajo"),
            draft["source_hash"], "1.3", rows,
        )
        overrides = {}
        for row in draft["rows"]:
            if row.get("responsable_account_id"):
                overrides[normalize_name(row["responsable"])] = {
                    "display_name": row["responsable"], "email": None,
                    "account_id": row["responsable_account_id"], "resolution": "RESOLVED",
                }
        proposal = self._build_proposal(parsed, PlanDefaults(space=str(draft.get("jira_space_key") or "AT")), created_by,
                                        resolve_assignees=False, assignee_overrides=overrides)
        proposal["minutes"] = {
            "prompt_version": "minute-excel-draft-v1",
            "extraction_mode": draft.get("extraction_mode", "DETERMINISTIC_FALLBACK"),
            "document": {**draft.get("document", {}), "draft_id": draft["draft_id"],
                         "draft_version": draft["version"],
                         "candidate_ids": [row["candidate_id"] for row in draft["rows"]],
                         "jira_space_key": draft.get("jira_space_key", "AT"),
                         "tracking_option_ids": {
                             row["candidate_id"]: row.get("tipo_de_seguimiento_id")
                             for row in draft["rows"] if row.get("tipo_de_seguimiento_id")
                         },
                         "responsable_resolution": {
                             row["candidate_id"]: row.get("responsable_resolution_status")
                             for row in draft["rows"] if row.get("responsable_resolution_status")
                         }},
            "warnings": draft.get("warnings", []),
        }
        self.validator.validate(proposal)
        return self.repository.save(proposal)

    def update_item(
        self,
        proposal_id: str,
        row_id: str,
        update: ItemUpdate,
        modified_by: str,
        verified_assignee: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        current = self.repository.get(proposal_id)
        if current is None:
            return None
        if current["status"] == "APPROVED":
            raise ProposalStateError(
                "La propuesta aprobada está bloqueada. Reábrela para crear una versión editable."
            )
        proposal = copy.deepcopy(current)
        item = next(
            (candidate for candidate in proposal["items"] if candidate["generated"]["row_id"] == row_id),
            None,
        )
        if item is None:
            raise KeyError(row_id)

        changes = update.model_dump(exclude_unset=True)
        minutes_fields = {"responsible_candidate_text", "area_responsable", "due_date_candidate", "project_or_front", "context", "comments"}
        if minutes_fields.intersection(changes):
            if "minutes" not in proposal:
                source_values = {
                    "responsible_candidate_text": item["source"].get("responsable_display"),
                    "area_responsable": item["source"].get("area_responsable"),
                    "due_date_candidate": item["source"].get("fecha_objetivo"),
                    "project_or_front": item["source"].get("frente_trabajo_origen"),
                    "context": item["source"].get("contexto_resultado"),
                    "comments": item["source"].get("comentarios"),
                }
                changed_source_fields = []
                for field in minutes_fields.intersection(changes):
                    submitted = changes[field]
                    if field == "due_date_candidate" and submitted is not None:
                        submitted = submitted.isoformat()
                    if submitted != source_values[field]:
                        changed_source_fields.append(field)
                if changed_source_fields:
                    raise ValueError("Estos campos de origen sólo se editan en propuestas de minuta.")
                for field in minutes_fields:
                    changes.pop(field, None)
            else:
                previous_candidate = item["source"]["responsable_display"]
                for field, source_field in {"responsible_candidate_text": "responsable_display",
                        "area_responsable": "area_responsable",
                        "project_or_front": "frente_trabajo_origen", "context": "contexto_resultado",
                        "comments": "comentarios"}.items():
                    if field in changes:
                        item["source"][source_field] = clean_optional(changes[field])
                        if field == "area_responsable":
                            item["source"]["area_source"] = "LOCAL"
                            item["source"]["area_status"] = "EXPLICIT" if changes[field] else "UNSPECIFIED"
                if "responsible_candidate_text" in changes:
                    candidate = item["source"]["responsable_display"] or "Por definir"
                    item["source"]["responsable_display"] = candidate
                    if candidate != previous_candidate:
                        item["generated"]["assignee"] = {"display_name": candidate, "email": None,
                            "account_id": None, "resolution": "NOT_FOUND"}
                if "due_date_candidate" in changes:
                    due = changes["due_date_candidate"]
                    item["source"]["fecha_objetivo"] = due.isoformat() if due else None
                    item["generated"]["fields"]["due_date"] = item["source"]["fecha_objetivo"]
        changes.pop("assignee_query", None)
        current_item_work_type = item["generated"]["work_type"]
        for field in ("title", "description", "work_type"):
            if field in changes:
                item["generated"][field] = changes[field]
        if "parent_row_id" in changes:
            item["generated"]["parent_row_id"] = changes["parent_row_id"]
        if "tipo_seguimiento" in changes:
            item["generated"].setdefault("fields", {})["tipo_seguimiento"] = clean_optional(
                changes["tipo_seguimiento"]
            )

        items_by_row = {
            candidate["generated"]["row_id"]: candidate
            for candidate in proposal["items"]
        }
        try:
            validate_parent_relation(
                row_id,
                item["generated"]["work_type"],
                item["generated"].get("parent_row_id"),
                items_by_row,
            )
        except JiraHierarchyError as exc:
            raise ValueError(str(exc)) from exc

        confirmed_fields = set(item["review"].get("confirmed_fields", []))
        if (
            changes.get("confirm_work_type")
            or (
                "work_type" in changes
                and changes["work_type"] != current_item_work_type
            )
        ):
            confirmed_fields.add("work_type")
        if changes.get("confirm_source_state"):
            confirmed_fields.add("source_state")
        if changes.get("confirm_reactivation"):
            item["review"]["reactivation_reviewed"] = True
        item["review"]["confirmed_fields"] = sorted(confirmed_fields)

        if changes.get("assignee_account_id"):
            resolved_assignee = verified_assignee
            if resolved_assignee is not None:
                if resolved_assignee.get("account_id") != changes["assignee_account_id"]:
                    raise ValueError("La cuenta Jira verificada no coincide con la selección enviada.")
                resolved_assignee = {
                    "display_name": resolved_assignee.get("display_name"),
                    "email": resolved_assignee.get("email"),
                    "account_id": resolved_assignee.get("account_id"),
                    "resolution": "RESOLVED",
                }
            else:
                resolved_assignee = self.catalog.get_by_account_id(changes["assignee_account_id"])
            if resolved_assignee is None:
                raise ValueError("El responsable seleccionado no fue verificado contra Jira.")
            if resolved_assignee["resolution"] != "RESOLVED":
                raise ValueError("El responsable seleccionado no está activo.")
            item["generated"]["assignee"] = resolved_assignee
        if "review_note" in changes:
            item["review"]["review_note"] = changes["review_note"]
        item["review"]["user_modified"] = True
        item["review"]["approved"] = False
        self._revalidate_item(item)

        proposal["version"] = current["version"] + 1
        proposal["status"] = (
            "NEEDS_INPUT"
            if any(entry["generated"]["decision"] == "REVISAR" for entry in proposal["items"])
            else "VALIDATED"
        )
        proposal["created_at"] = utc_now()
        proposal["created_by"] = modified_by
        proposal["approved_at"] = None
        proposal["approved_by"] = None
        self.validator.validate(proposal)
        return self.repository.save(proposal)

    def update_defaults(
        self,
        proposal_id: str,
        update: ProposalDefaultsUpdate,
        modified_by: str,
    ) -> dict[str, Any] | None:
        """Create a version with updated plan values, including approved proposals.

        The source workbook and every historical version remain immutable. An approved
        proposal becomes editable again because its Jira validation no longer describes
        the updated values.
        """

        current = self.repository.get(proposal_id)
        if current is None:
            return None
        proposal = copy.deepcopy(current)
        defaults = {
            key: clean_optional(value) if key != "space" else value
            for key, value in update.model_dump().items()
        }
        proposal["defaults"] = defaults
        for item in proposal["items"]:
            generated = item["generated"]
            generated["space"] = defaults["space"]
            generated_fields = generated.setdefault("fields", {})
            for field_name in (
                "iniciativa",
                "linea_trabajo",
                "sprint",
                "tipo_seguimiento",
                "semaforo",
            ):
                generated_fields[field_name] = defaults[field_name]
            item["review"]["approved"] = False
            self._revalidate_item(item)

        proposal["version"] = current["version"] + 1
        proposal["status"] = (
            "NEEDS_INPUT"
            if any(entry["generated"]["decision"] == "REVISAR" for entry in proposal["items"])
            else "VALIDATED"
        )
        proposal["created_at"] = utc_now()
        proposal["created_by"] = modified_by
        proposal["approved_at"] = None
        proposal["approved_by"] = None
        self.validator.validate(proposal)
        return self.repository.save(proposal)

    def bulk_update_items(
        self,
        proposal_id: str,
        update: BulkProposalUpdate,
        modified_by: str,
    ) -> dict[str, Any] | None:
        """Apply one safe catalog value to several local rows in one version."""
        current = self.repository.get(proposal_id)
        if current is None:
            return None
        if current["status"] == "APPROVED":
            raise ProposalStateError("La propuesta aprobada está bloqueada. Reábrela antes de corregirla.")
        proposal = copy.deepcopy(current)
        selected = set(update.row_ids or [item["generated"]["row_id"] for item in proposal["items"]])
        rows = {item["generated"]["row_id"] for item in proposal["items"]}
        unknown = selected - rows
        if unknown:
            raise KeyError(sorted(unknown)[0])
        if not selected:
            raise ValueError("Selecciona al menos una actividad.")
        if update.field == "work_type" and update.value not in {"Epic", "Story", "Task", "Bug", "Subtask"}:
            raise ValueError("El Work Type seleccionado no es válido.")
        changed = 0
        for item in proposal["items"]:
            if item["generated"]["row_id"] not in selected or item["generated"]["decision"] == "EXCLUIR":
                continue
            generated = item["generated"]
            if update.field == "work_type":
                generated["work_type"] = update.value
                item["review"].setdefault("confirmed_fields", [])
                if "work_type" not in item["review"]["confirmed_fields"]:
                    item["review"]["confirmed_fields"].append("work_type")
                    item["review"]["confirmed_fields"].sort()
            else:
                generated.setdefault("fields", {})[update.field] = clean_optional(update.value)
            item["review"]["user_modified"] = True
            item["review"]["approved"] = False
            self._revalidate_item(item)
            changed += 1
        if changed == 0:
            raise ValueError("No hay actividades activas para actualizar.")
        proposal["version"] = current["version"] + 1
        proposal["status"] = "NEEDS_INPUT" if any(
            item["generated"]["decision"] == "REVISAR" for item in proposal["items"]
        ) else "VALIDATED"
        proposal["created_at"] = utc_now()
        proposal["created_by"] = modified_by
        proposal["approved_at"] = None
        proposal["approved_by"] = None
        self.validator.validate(proposal)
        return self.repository.save(proposal)

    def exclude_items(
        self,
        proposal_id: str,
        row_ids: list[str],
        reason: str,
        modified_by: str,
    ) -> dict[str, Any] | None:
        """Exclude selected activities locally without performing Jira writes."""

        current = self.repository.get(proposal_id)
        if current is None:
            return None
        if current["status"] == "APPROVED":
            raise ProposalStateError("La propuesta aprobada está bloqueada. Reábrela antes de excluir actividades.")
        selected = set(row_ids)
        known = {item["generated"]["row_id"] for item in current["items"]}
        unknown = selected - known
        if unknown:
            raise KeyError(sorted(unknown)[0])
        if not selected:
            raise ValueError("Selecciona al menos una actividad para excluir.")

        proposal = copy.deepcopy(current)
        for item in proposal["items"]:
            generated = item["generated"]
            row_id = generated["row_id"]
            if row_id not in selected:
                if generated.get("parent_row_id") in selected and generated["decision"] != "EXCLUIR":
                    raise ValueError(
                        f"No puedes excluir {generated['parent_row_id']} mientras {row_id} dependa de esa actividad."
                    )
                continue
            item["review"].update(
                {
                    "manual_exclusion_reason": reason.strip(),
                    "manual_excluded_at": utc_now(),
                    "manual_excluded_by": modified_by,
                    "user_modified": True,
                    "approved": False,
                }
            )
            self._revalidate_item(item)

        proposal["version"] = current["version"] + 1
        proposal["status"] = "NEEDS_INPUT" if any(
            item["generated"]["decision"] == "REVISAR" for item in proposal["items"]
        ) else "VALIDATED"
        proposal["created_at"] = utc_now()
        proposal["created_by"] = modified_by
        proposal["approved_at"] = None
        proposal["approved_by"] = None
        self.validator.validate(proposal)
        return self.repository.save(proposal)

    def prepare_for_display(self, proposal: dict[str, Any]) -> dict[str, Any]:
        """Hydrate proposals created before Objective 1.1 without changing storage."""

        hydrated = copy.deepcopy(proposal)
        for item in hydrated["items"]:
            item["review"].setdefault("confirmed_fields", [])
            item["review"].setdefault("source_state_override", None)
            item["review"].setdefault("source_state_override_reason", None)
            item["review"].setdefault("source_state_override_at", None)
            item["review"].setdefault("source_state_override_by", None)
            item["review"].setdefault("reactivation_reviewed", False)
            item["review"].setdefault("manual_exclusion_reason", None)
            item["review"].setdefault("manual_excluded_at", None)
            item["review"].setdefault("manual_excluded_by", None)
            if "pending_requirements" not in item["validation"]:
                self._revalidate_item(item)
        return hydrated

    @staticmethod
    def _revalidate_item(item: dict[str, Any]) -> None:
        generated = item["generated"]
        manual_exclusion_reason = item["review"].get("manual_exclusion_reason")
        if manual_exclusion_reason:
            generated["decision"] = "EXCLUIR"
            generated["decision_reason"] = manual_exclusion_reason
            generated["create_in_jira"] = False
            item["validation"]["pending_requirements"] = []
            return
        confirmed_fields = item["review"].get("confirmed_fields", [])
        decision, decision_reason, _ = decide(
            item["source"],
            generated["assignee"],
            generated["work_type"],
            generated["confidence"],
            parent_row_id=generated.get("parent_row_id"),
            confirmed_fields=confirmed_fields,
            source_state_overridden=bool(item["review"].get("source_state_override")),
            reactivation_reviewed=bool(item["review"].get("reactivation_reviewed")),
        )
        generated["decision"] = decision
        generated["decision_reason"] = decision_reason
        generated["create_in_jira"] = decision == "INCLUIR"
        item["validation"]["pending_requirements"] = collect_review_requirements(
            item["source"],
            generated["assignee"],
            generated["work_type"],
            generated["confidence"],
            parent_row_id=generated.get("parent_row_id"),
            confirmed_fields=confirmed_fields,
            source_state_overridden=bool(item["review"].get("source_state_override")),
            reactivation_reviewed=bool(item["review"].get("reactivation_reviewed")),
        )

    def reactivate_item(
        self,
        proposal_id: str,
        row_id: str,
        reason: str,
        modified_by: str,
    ) -> dict[str, Any] | None:
        current = self.repository.get(proposal_id)
        if current is None:
            return None
        if current["status"] == "APPROVED":
            raise ProposalStateError(
                "La propuesta aprobada está bloqueada. Reábrela antes de recuperar actividades."
            )
        proposal = copy.deepcopy(current)
        item = next(
            (entry for entry in proposal["items"] if entry["generated"]["row_id"] == row_id),
            None,
        )
        if item is None:
            raise KeyError(row_id)
        manual_exclusion = bool(item["review"].get("manual_exclusion_reason"))
        source_state_exclusion = (
            item["generated"]["decision"] == "EXCLUIR"
            and item["source"]["estado_actual"] in {"Completada", "Rechazada"}
        )
        if not manual_exclusion and not source_state_exclusion:
            raise ProposalStateError(
                "Solo se pueden recuperar actividades excluidas de esta propuesta."
            )
        now = utc_now()
        if manual_exclusion:
            item["review"].update(
                {
                    "manual_exclusion_reason": None,
                    "manual_excluded_at": None,
                    "manual_excluded_by": None,
                    "review_note": f"Actividad recuperada: {reason.strip()}",
                    "user_modified": True,
                    "approved": False,
                }
            )
        else:
            item["review"].update({
                "source_state_override": "ACTIVE",
                "source_state_override_reason": reason.strip(),
                "source_state_override_at": now,
                "source_state_override_by": modified_by,
                "reactivation_reviewed": False,
                "user_modified": True,
                "approved": False,
            })
        self._revalidate_item(item)
        proposal["version"] = current["version"] + 1
        proposal["status"] = "NEEDS_INPUT" if any(
            entry["generated"]["decision"] == "REVISAR" for entry in proposal["items"]
        ) else "VALIDATED"
        proposal["created_at"] = now
        proposal["created_by"] = modified_by
        proposal["approved_at"] = None
        proposal["approved_by"] = None
        self.validator.validate(proposal)
        return self.repository.save(proposal)

    def update_jira_assignee(
        self,
        proposal_id: str,
        row_id: str,
        jira_assignee: dict[str, Any],
        modified_by: str,
    ) -> dict[str, Any] | None:
        current = self.repository.get(proposal_id)
        if current is None:
            return None
        if current["status"] == "APPROVED":
            raise ProposalStateError(
                "Reabre la propuesta antes de corregir el responsable Jira."
            )
        proposal = copy.deepcopy(current)
        item = next(
            (
                entry
                for entry in proposal["items"]
                if entry["generated"]["row_id"] == row_id
            ),
            None,
        )
        if item is None:
            raise KeyError(row_id)
        if item["generated"]["decision"] == "EXCLUIR":
            raise ProposalStateError(
                "No se puede asignar una cuenta Jira a una actividad excluida."
            )
        item["generated"]["assignee"] = {
            "display_name": jira_assignee["display_name"],
            "email": jira_assignee.get("email"),
            "account_id": jira_assignee["account_id"],
            "resolution": "RESOLVED",
        }
        item["review"]["user_modified"] = True
        item["review"]["approved"] = False
        item["review"]["review_note"] = "Responsable verificado contra Jira mediante Rovo MCP."
        self._revalidate_item(item)
        proposal["version"] = current["version"] + 1
        proposal["status"] = (
            "NEEDS_INPUT"
            if any(entry["generated"]["decision"] == "REVISAR" for entry in proposal["items"])
            else "VALIDATED"
        )
        proposal["created_at"] = utc_now()
        proposal["created_by"] = modified_by
        proposal["approved_at"] = None
        proposal["approved_by"] = None
        self.validator.validate(proposal)
        return self.repository.save(proposal)

    def approve_proposal(
        self, proposal_id: str, approved_by: str
    ) -> dict[str, Any] | None:
        current = self.repository.get(proposal_id)
        if current is None:
            return None
        if current["status"] == "APPROVED":
            raise ProposalStateError("La propuesta ya está aprobada.")
        if any(item["generated"]["decision"] == "REVISAR" for item in current["items"]):
            raise ProposalStateError(
                "La propuesta todavía tiene actividades que requieren revisión."
            )
        latest_dry_run = self.repository.get_latest_dry_run(proposal_id)
        if latest_dry_run is not None:
            correction_workflow = build_correction_workflow(current, latest_dry_run)
            pending_user = correction_workflow["summary"]["pending_user"]
            if pending_user:
                raise ProposalStateError(
                    f"Resuelve {pending_user} correcciones de Jira antes de aprobar."
                )
        proposal = copy.deepcopy(current)
        now = utc_now()
        proposal["version"] = current["version"] + 1
        proposal["status"] = "APPROVED"
        proposal["created_at"] = now
        proposal["created_by"] = approved_by
        proposal["approved_at"] = now
        proposal["approved_by"] = approved_by
        self.validator.validate(proposal)
        return self.repository.save(proposal)

    def reopen_proposal(
        self, proposal_id: str, reopened_by: str
    ) -> dict[str, Any] | None:
        current = self.repository.get(proposal_id)
        if current is None:
            return None
        if current["status"] != "APPROVED":
            raise ProposalStateError("Solo una propuesta aprobada puede reabrirse.")
        proposal = copy.deepcopy(current)
        proposal["version"] = current["version"] + 1
        proposal["status"] = (
            "NEEDS_INPUT"
            if any(item["generated"]["decision"] == "REVISAR" for item in proposal["items"])
            else "VALIDATED"
        )
        proposal["created_at"] = utc_now()
        proposal["created_by"] = reopened_by
        proposal["approved_at"] = None
        proposal["approved_by"] = None
        self.validator.validate(proposal)
        return self.repository.save(proposal)

    @staticmethod
    def summarize(
        proposal: dict[str, Any],
        *,
        archived_at: str | None = None,
        archived_by: str | None = None,
        deleted_at: str | None = None,
        deleted_by: str | None = None,
        purge_at: str | None = None,
        display_name: str | None = None,
        display_name_updated_at: str | None = None,
        display_name_updated_by: str | None = None,
    ) -> dict[str, Any]:
        counts = {"INCLUIR": 0, "REVISAR": 0, "EXCLUIR": 0}
        for item in proposal["items"]:
            counts[item["generated"]["decision"]] += 1
        return {
            "proposal_id": proposal["proposal_id"],
            "version": proposal["version"],
            "status": proposal["status"],
            "source_file": proposal["source_file"]["name"],
            "display_name": display_name or proposal["source_file"]["name"].rsplit(".", 1)[0],
            "space": proposal["defaults"]["space"],
            "counts": counts,
            "created_at": proposal.get("created_at"),
            "archived": archived_at is not None,
            "archived_at": archived_at,
            "archived_by": archived_by,
            "deleted": deleted_at is not None,
            "deleted_at": deleted_at,
            "deleted_by": deleted_by,
            "purge_at": purge_at,
            "display_name_updated_at": display_name_updated_at,
            "display_name_updated_by": display_name_updated_by,
        }
