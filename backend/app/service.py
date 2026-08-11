from __future__ import annotations

import copy
import uuid
from datetime import UTC, datetime
from typing import Any

from .catalog import FakeAssigneeCatalog
from .corrections import build_correction_workflow
from .errors import ProposalStateError
from .models import ItemUpdate, PlanDefaults, ProposalDefaultsUpdate
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
    ) -> dict[str, Any]:
        parsed = self.parser.parse(filename, content)
        proposal = self._build_proposal(parsed, defaults, created_by)
        self.validator.validate(proposal)
        return self.repository.save(proposal)

    def _build_proposal(
        self,
        parsed: ParsedPlan,
        defaults: PlanDefaults,
        created_by: str,
    ) -> dict[str, Any]:
        items = []
        for source in parsed.rows:
            assignee = self.catalog.resolve(source["responsable_display"])
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
                            "tipo_seguimiento": clean_optional(defaults.tipo_seguimiento),
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
            "template_version": "1.1",
            "status": status,
            "source_file": {"name": parsed.filename, "sha256": parsed.sha256},
            "defaults": defaults.model_dump(),
            "items": items,
            "created_at": utc_now(),
            "created_by": created_by,
            "approved_at": None,
            "approved_by": None,
        }

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
        changes.pop("assignee_query", None)
        current_item_work_type = item["generated"]["work_type"]
        for field in ("title", "description", "work_type"):
            if field in changes:
                item["generated"][field] = changes[field]
        if "parent_row_id" in changes:
            item["generated"]["parent_row_id"] = changes["parent_row_id"]

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
            if "pending_requirements" not in item["validation"]:
                self._revalidate_item(item)
        return hydrated

    @staticmethod
    def _revalidate_item(item: dict[str, Any]) -> None:
        generated = item["generated"]
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
        if item["generated"]["decision"] != "EXCLUIR" or item["source"]["estado_actual"] not in {
            "Completada",
            "Rechazada",
        }:
            raise ProposalStateError(
                "Solo se pueden reactivar actividades excluidas por su estado en el archivo fuente."
            )
        now = utc_now()
        item["review"].update(
            {
                "source_state_override": "ACTIVE",
                "source_state_override_reason": reason.strip(),
                "source_state_override_at": now,
                "source_state_override_by": modified_by,
                "reactivation_reviewed": False,
                "user_modified": True,
                "approved": False,
            }
        )
        self._revalidate_item(item)
        proposal["version"] = current["version"] + 1
        proposal["status"] = "NEEDS_INPUT"
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
            "display_name_updated_at": display_name_updated_at,
            "display_name_updated_by": display_name_updated_by,
        }
