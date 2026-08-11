from __future__ import annotations

import copy
import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any, Callable, Protocol

from .execution_policy import JiraExecutionPolicy
from .hierarchy import JiraHierarchyError, ordered_row_ids, validate_parent_relation
from .objective_4a import _summary_slug
from .objective_4b import JiraControlledExecutionService, Objective4BError
from .repository import ProposalRepository
from .sprints import revalidate_sprint


class Objective4C1Error(RuntimeError):
    pass


class ControlledJiraBatchGateway(Protocol):
    async def list_sprints(
        self, username: str, space: str, *, force_refresh: bool = False
    ) -> list[dict[str, Any]]: ...

    async def create_single_task_and_readback(
        self,
        username: str,
        create_arguments: dict[str, Any],
        readback_fields: list[str],
        timeout_seconds: int,
    ) -> dict[str, Any]: ...


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class JiraControlledBatchService:
    """Creates a bounded AT/Task batch sequentially and stops on the first anomaly."""

    CONFIRMATION_TTL = timedelta(minutes=10)
    TERMINAL_STATUSES = {
        "COMPLETED",
        "STOPPED_REJECTED",
        "STOPPED_UNKNOWN",
        "STOPPED_UNVERIFIED",
    }

    def __init__(
        self,
        repository: ProposalRepository,
        policy: JiraExecutionPolicy,
        gateway: ControlledJiraBatchGateway,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.repository = repository
        self.policy = policy
        self.gateway = gateway
        self.now = now

    @property
    def objective(self) -> str:
        if self.policy.mode == "CONTROLLED_HIERARCHY_BATCH":
            return "4E"
        return "4D" if self.policy.mode == "CONTROLLED_MULTI_TYPE_BATCH" else "4C.1"

    def prepare(
        self,
        proposal_id: str,
        row_ids: list[str],
        username: str,
        jira_snapshot: dict[str, Any],
        tool_readiness: dict[str, Any],
    ) -> dict[str, Any]:
        proposal, dry_run = self._current_documents(proposal_id)
        hierarchy_mode = self.policy.mode == "CONTROLLED_HIERARCHY_BATCH"
        selected_ids = list(dict.fromkeys(row_ids))
        if len(selected_ids) != len(row_ids):
            raise Objective4C1Error("La seleccion contiene actividades duplicadas.")
        if not 1 <= len(selected_ids) <= int(self.policy.document["max_items_per_execution"]):
            raise Objective4C1Error("Selecciona entre 1 y 5 actividades para el lote controlado.")

        create_tool = tool_readiness.get("create") or {}
        readback_tool = tool_readiness.get("readback") or {}
        if not create_tool.get("exposed") or not readback_tool.get("exposed"):
            raise Objective4C1Error("Rovo debe exponer createJiraIssue y getJiraIssue.")
        if not {"cloudId", "projectKey", "issueTypeName", "summary"}.issubset(
            set((create_tool.get("input_schema") or {}).get("required") or [])
        ):
            raise Objective4C1Error("El contrato anunciado de createJiraIssue no es compatible.")
        if hierarchy_mode and "additional_fields" not in set(
            ((create_tool.get("input_schema") or {}).get("properties") or {}).keys()
        ):
            raise Objective4C1Error(
                "createJiraIssue no expone additional_fields; no se puede enviar una relación padre-hijo segura."
            )
        if not {"cloudId", "issueIdOrKey"}.issubset(
            set((readback_tool.get("input_schema") or {}).get("required") or [])
        ):
            raise Objective4C1Error("El contrato anunciado de getJiraIssue no es compatible.")

        indexed = {item.get("row_id"): item for item in dry_run.get("items", [])}
        selected: list[dict[str, Any]] = []
        for row_id in selected_ids:
            item = indexed.get(row_id)
            if item is None:
                raise Objective4C1Error(f"La actividad {row_id} no pertenece al Dry run actual.")
            if item.get("status") not in {"READY", "READY_WITH_WARNINGS"}:
                raise Objective4C1Error(f"La actividad {row_id} no esta lista para Jira.")
            selected.append(item)

        prior_batches = self.repository.list_execution_intents(
            proposal_id,
            objective=self.objective,
            proposal_version=proposal["version"],
        )
        known_parent_issue_keys = {
            previous_item.get("row_id"): previous_item.get("issue_key")
            for previous in prior_batches
            for previous_item in previous.get("items", [])
            if previous_item.get("status") == "CREATED_VERIFIED"
            and previous_item.get("issue_key")
        }
        if hierarchy_mode:
            proposal_items = {
                entry["generated"]["row_id"]: entry
                for entry in proposal.get("items", [])
            }
            parent_by_row = {
                item["row_id"]: (item.get("logical_payload") or {}).get("parent_row_id")
                for item in selected
            }
            for item in selected:
                parent_row_id = parent_by_row[item["row_id"]]
                try:
                    validate_parent_relation(
                        item["row_id"],
                        str(item.get("work_type") or ""),
                        parent_row_id,
                        proposal_items,
                        require_included=True,
                    )
                except JiraHierarchyError as exc:
                    raise Objective4C1Error(str(exc)) from exc
                if (
                    parent_row_id
                    and parent_row_id not in selected_ids
                    and parent_row_id not in known_parent_issue_keys
                ):
                    raise Objective4C1Error(
                        f"Incluye primero la actividad padre {parent_row_id} en este lote, "
                        "o créala y verifícala en un lote anterior."
                    )
            try:
                selected_ids = ordered_row_ids(selected_ids, parent_by_row)
            except JiraHierarchyError as exc:
                raise Objective4C1Error(str(exc)) from exc
            selected_by_row = {item["row_id"]: item for item in selected}
            selected = [selected_by_row[row_id] for row_id in selected_ids]
        same_batch = next(
            (
                previous
                for previous in prior_batches
                if previous.get("dry_run_id") == dry_run.get("dry_run_id")
                and previous.get("row_ids") == selected_ids
            ),
            None,
        )
        if same_batch is not None:
            return {**same_batch, "reused": True}
        previously_attempted = {
            previous_item.get("idempotency_key")
            for previous in prior_batches
            for previous_item in previous.get("items", [])
            if previous_item.get("status") != "NOT_ATTEMPTED"
        }
        duplicates = [
            item["row_id"]
            for item in selected
            if item.get("idempotency_key") in previously_attempted
        ]
        if duplicates:
            raise Objective4C1Error(
                "Estas actividades ya pertenecen a otro lote preparado o intentado: "
                + ", ".join(duplicates)
                + ". Reutiliza su evidencia o crea una nueva version de la propuesta."
            )

        violations = self.policy.batch_gate_violations(
            spaces={str(item.get("space") or "") for item in selected},
            work_types={str(item.get("work_type") or "") for item in selected},
            item_count=len(selected),
            tool_name="createJiraIssue",
            approved_version_current=proposal.get("status") == "APPROVED",
            dry_run_current=dry_run.get("proposal_version") == proposal.get("version"),
            dry_run_blockers=int(dry_run.get("summary", {}).get("blocked", 0)),
            all_accounts_confirmed=all(bool((item.get("assignee") or {}).get("account_id")) for item in selected),
            assignees_in_atomic_create=all(bool((item.get("assignee") or {}).get("account_id")) for item in selected),
            second_confirmation=True,
        )
        if violations:
            raise Objective4C1Error("El kill switch bloqueo el lote: " + ", ".join(violations))

        now = self.now()
        proposal_short = str(proposal["proposal_id"]).split("-")[0].upper()
        batch_items: list[dict[str, Any]] = []
        for position, item in enumerate(selected, start=1):
            logical = item.get("logical_payload") or {}
            if not logical:
                raise Objective4C1Error(f"La actividad {item['row_id']} no tiene payload verificable.")
            work_type_name = str(item.get("work_type") or "")
            space_key = str(item.get("space") or "")
            try:
                additional_fields = JiraControlledExecutionService._additional_fields(
                    logical.get("jira_fields") or {},
                    jira_snapshot,
                    space_key,
                    work_type_name,
                )
            except Objective4BError as exc:
                raise Objective4C1Error(str(exc)) from exc
            additional_fields["labels"] = [self.policy.document["test_label"]]
            parent_row_id = logical.get("parent_row_id") if hierarchy_mode else None
            if parent_row_id:
                parent_key = known_parent_issue_keys.get(parent_row_id)
                additional_fields["parent"] = {"key": parent_key or f"${parent_row_id}"}
            sprint_resolution = copy.deepcopy(item.get("sprint_resolution"))
            if sprint_resolution and (sprint_resolution.get("selected") or {}).get("id"):
                sprint_field = JiraControlledExecutionService._sprint_field(
                    jira_snapshot,
                    space_key,
                    work_type_name,
                )
                if not sprint_field or not sprint_field.get("id"):
                    raise Objective4C1Error(
                        f"Jira no publico el campo Sprint para {space_key} / {work_type_name}."
                    )
                sprint_resolution["field_id"] = str(sprint_field["id"])
            configured_prefix = str(self.policy.document["title_prefix"])
            item_prefix = (
                f"{configured_prefix}{work_type_name}_"
                if configured_prefix == "AgenteTest_"
                else configured_prefix
            )
            title = (
                f"{item_prefix}"
                f"{now.strftime('%Y%m%d_%H%M')}_{proposal_short}_{position}_"
                f"{_summary_slug(str(item.get('title') or 'Actividad'))}"
            )[:255]
            arguments = {
                "cloudId": jira_snapshot.get("cloud_id"),
                "projectKey": space_key,
                "issueTypeName": work_type_name,
                "summary": title,
                "description": logical.get("description"),
                "assignee_account_id": (item.get("assignee") or {}).get("account_id"),
                "additional_fields": additional_fields,
                "contentFormat": "markdown",
                "responseContentFormat": "markdown",
            }
            arguments = {key: value for key, value in arguments.items() if value is not None and value != {}}
            item_hash = _hash(arguments)
            batch_items.append({
                "position": position,
                "row_id": item["row_id"],
                "idempotency_key": item["idempotency_key"],
                "status": "PENDING",
                "payload": {"tool": "createJiraIssue", "arguments": arguments},
                "payload_hash": item_hash,
                "preview": {
                    "title": title,
                    "source_title": item.get("title"),
                    "space": item.get("space"),
                    "work_type": item.get("work_type"),
                    "assignee": copy.deepcopy(item.get("assignee")),
                    "parent_row_id": parent_row_id,
                    "parent_issue_key": known_parent_issue_keys.get(parent_row_id),
                },
                "parent_reference": {
                    "row_id": parent_row_id,
                    "issue_key": known_parent_issue_keys.get(parent_row_id),
                } if parent_row_id else None,
                "resolved_parent": None,
                "submitted_payload_hash": None,
                "sprint_resolution": sprint_resolution,
                "sprint_revalidated_at": None,
                "submitted_at": None,
                "completed_at": None,
                "real_mcp_calls": 0,
                "automatic_retries": 0,
                "issue_key": None,
                "issue_url": None,
                "result": None,
                "error": None,
                "readback": None,
            })

        batch_hash = _hash([
            {"row_id": item["row_id"], "idempotency_key": item["idempotency_key"], "payload_hash": item["payload_hash"]}
            for item in batch_items
        ])
        execution_id = f"BAT-{batch_hash[:32].upper()}"
        created_at = _iso(now)
        multi_type = self.policy.mode in {"CONTROLLED_MULTI_TYPE_BATCH", "CONTROLLED_HIERARCHY_BATCH"}
        phrase = (
            f"CREAR {len(batch_items)} ACTIVIDADES EN AT"
            if multi_type
            else f"CREAR {len(batch_items)} TASKS EN AT"
        )
        intent = {
            "objective": self.objective,
            "mode": "CONTROLLED_HIERARCHY_BATCH" if hierarchy_mode else "CONTROLLED_WORK_ITEM_BATCH" if multi_type else "CONTROLLED_TASK_BATCH",
            "execution_id": execution_id,
            "status": "BATCH_PREPARED",
            "proposal_id": proposal["proposal_id"],
            "proposal_version": proposal["version"],
            "row_id": f"BATCH-{_hash(selected_ids)[:20].upper()}",
            "row_ids": selected_ids,
            "dry_run_id": dry_run["dry_run_id"],
            "idempotency_key": f"AJB-{batch_hash[:40]}",
            "payload_hash": batch_hash,
            "confirmation_phrase": phrase,
            "confirmation": {
                "required": True,
                "expires_at": _iso(now + self.CONFIRMATION_TTL),
                "confirmed_at": None,
                "confirmed_by": None,
            },
            "items": batch_items,
            "known_parent_issue_keys": known_parent_issue_keys,
            "summary": self._summary(batch_items),
            "policy": self.policy.public_summary(),
            "created_at": created_at,
            "updated_at": created_at,
            "created_by": username,
            "started_at": None,
            "completed_at": None,
            "real_mcp_calls": 0,
            "automatic_retries": 0,
            "audit": [self._audit("BATCH_PREPARED", username, now, "BATCH_PREPARED")],
        }
        stored, reused = self.repository.save_execution_intent(intent)
        return {**stored, "reused": reused}

    def confirm(
        self,
        execution_id: str,
        payload_hash: str,
        confirmation_phrase: str,
        username: str,
    ) -> dict[str, Any]:
        intent = self._owned(execution_id, username)
        if intent["status"] != "BATCH_PREPARED":
            raise Objective4C1Error("El lote ya no espera confirmacion.")
        self._assert_not_expired(intent)
        self._current_documents(intent["proposal_id"], intent)
        if payload_hash != intent["payload_hash"]:
            raise Objective4C1Error("El contenido del lote cambio; preparalo nuevamente.")
        if confirmation_phrase.strip().upper() != intent["confirmation_phrase"]:
            raise Objective4C1Error("La frase de confirmacion no coincide.")
        now = self.now()
        intent["status"] = "BATCH_CONFIRMED"
        intent["updated_at"] = _iso(now)
        intent["confirmation"]["confirmed_at"] = _iso(now)
        intent["confirmation"]["confirmed_by"] = username
        intent["audit"].append(self._audit("BATCH_CONFIRMED", username, now, "BATCH_CONFIRMED"))
        return self.repository.update_execution_intent(intent)

    async def execute(self, execution_id: str, username: str) -> dict[str, Any]:
        intent = self._owned(execution_id, username)
        if intent["status"] in self.TERMINAL_STATUSES:
            return {**intent, "reused": True}
        if intent["status"] == "BATCH_RUNNING":
            raise Objective4C1Error(
                "El lote quedo en ejecucion. No se reanudara automaticamente; reconcilia sus claves en Jira."
            )
        if intent["status"] != "BATCH_CONFIRMED":
            raise Objective4C1Error("Confirma el lote antes de crear las actividades.")
        self._assert_not_expired(intent)
        proposal, dry_run = self._current_documents(intent["proposal_id"], intent)
        items = intent["items"]
        violations = self.policy.batch_gate_violations(
            spaces={str(item["preview"]["space"]) for item in items},
            work_types={str(item["preview"]["work_type"]) for item in items},
            item_count=len(items),
            tool_name="createJiraIssue",
            approved_version_current=proposal.get("status") == "APPROVED",
            dry_run_current=dry_run.get("dry_run_id") == intent.get("dry_run_id"),
            dry_run_blockers=int(dry_run.get("summary", {}).get("blocked", 0)),
            all_accounts_confirmed=all(bool((item["preview"].get("assignee") or {}).get("account_id")) for item in items),
            assignees_in_atomic_create=all(bool(item["payload"]["arguments"].get("assignee_account_id")) for item in items),
            second_confirmation=bool(intent["confirmation"].get("confirmed_at")),
        )
        if violations:
            raise Objective4C1Error("El kill switch bloqueo el lote: " + ", ".join(violations))

        await self._revalidate_all_sprints(intent, username)
        now = self.now()
        intent["status"] = "BATCH_RUNNING"
        intent["started_at"] = _iso(now)
        intent["updated_at"] = _iso(now)
        intent["audit"].append(self._audit("BATCH_RUNNING", username, now, "SEQUENTIAL_BATCH_STARTED"))
        self.repository.update_execution_intent(intent)

        resolved_keys = copy.deepcopy(intent.get("known_parent_issue_keys") or {})
        for index, item in enumerate(items):
            create_arguments = copy.deepcopy(item["payload"]["arguments"])
            parent_reference = item.get("parent_reference") or {}
            parent_row_id = parent_reference.get("row_id")
            if parent_row_id:
                parent_key = resolved_keys.get(parent_row_id)
                if not parent_key:
                    item["status"] = "REJECTED"
                    item["result"] = "PARENT_KEY_UNRESOLVED"
                    item["error"] = f"No se pudo resolver la clave Jira de la actividad padre {parent_row_id}."
                    item["completed_at"] = _iso(self.now())
                    self._stop(intent, index, "STOPPED_REJECTED", username)
                    return self.repository.update_execution_intent(intent)
                create_arguments.setdefault("additional_fields", {})["parent"] = {"key": parent_key}
                item["resolved_parent"] = {"row_id": parent_row_id, "issue_key": parent_key}
            item["submitted_payload_hash"] = _hash(create_arguments)
            now = self.now()
            item["status"] = "SUBMITTED"
            item["submitted_at"] = _iso(now)
            intent["updated_at"] = _iso(now)
            self.repository.update_execution_intent(intent)
            try:
                readback_fields = ["summary", "description", "issuetype", "assignee", "project", "labels"]
                if parent_row_id:
                    readback_fields.append("parent")
                sprint_field_id = (item.get("sprint_resolution") or {}).get("field_id")
                if sprint_field_id:
                    readback_fields.append(str(sprint_field_id))
                result = await self.gateway.create_single_task_and_readback(
                    username,
                    create_arguments,
                    readback_fields,
                    int(self.policy.document["execution_timeout_seconds"]),
                )
            except Exception as exc:
                uncertain = bool(getattr(exc, "outcome_uncertain", False))
                item["status"] = "UNKNOWN" if uncertain else "REJECTED"
                item["result"] = "OUTCOME_UNKNOWN" if uncertain else "JIRA_REJECTED"
                item["error"] = str(exc)[:700]
                item["real_mcp_calls"] = int(getattr(exc, "real_mcp_calls", 1))
                item["completed_at"] = _iso(self.now())
                self._stop(intent, index, "STOPPED_UNKNOWN" if uncertain else "STOPPED_REJECTED", username)
                return self.repository.update_execution_intent(intent)

            issue_key = result.get("issue_key")
            checks = JiraControlledExecutionService._readback_checks(
                result.get("readback"),
                issue_key,
                create_arguments,
                item.get("sprint_resolution"),
            )
            verified = bool(issue_key) and all(checks.values())
            item["status"] = "CREATED_VERIFIED" if verified else "CREATED_UNVERIFIED"
            item["issue_key"] = issue_key
            item["issue_url"] = f"https://dpti.atlassian.net/browse/{issue_key}" if issue_key else None
            item["real_mcp_calls"] = int(result.get("real_mcp_calls", 2))
            item["completed_at"] = _iso(self.now())
            item["result"] = "CREATED_AND_VERIFIED" if verified else "CREATED_READBACK_INCOMPLETE"
            item["readback"] = {"checks": checks, "payload": result.get("readback")}
            if not verified:
                self._stop(intent, index, "STOPPED_UNVERIFIED", username)
                return self.repository.update_execution_intent(intent)
            resolved_keys[item["row_id"]] = issue_key
            intent["summary"] = self._summary(items)
            intent["real_mcp_calls"] = sum(int(entry.get("real_mcp_calls", 0)) for entry in items)
            intent["updated_at"] = _iso(self.now())
            self.repository.update_execution_intent(intent)

        now = self.now()
        intent["status"] = "COMPLETED"
        intent["completed_at"] = _iso(now)
        intent["updated_at"] = _iso(now)
        intent["summary"] = self._summary(items)
        intent["real_mcp_calls"] = sum(int(item.get("real_mcp_calls", 0)) for item in items)
        intent["audit"].append(self._audit("COMPLETED", username, now, "ALL_ITEMS_CREATED_AND_VERIFIED"))
        return self.repository.update_execution_intent(intent)

    def latest(self, proposal_id: str) -> dict[str, Any] | None:
        return self.repository.get_latest_execution_intent(proposal_id, objective=self.objective)

    def progress(self, proposal_id: str) -> dict[str, Any]:
        proposal, dry_run = self._current_documents(proposal_id)
        eligible = [
            item
            for item in dry_run.get("items", [])
            if item.get("status") in {"READY", "READY_WITH_WARNINGS"}
            and item.get("space") == "AT"
            and item.get("work_type") in self.policy.document["allowed_work_types"]
        ]
        batches = self.repository.list_execution_intents(
            proposal_id,
            objective=self.objective,
            proposal_version=proposal["version"],
        )
        latest_by_key: dict[str, dict[str, Any]] = {}
        for batch in reversed(batches):
            for item in batch.get("items", []):
                key = item.get("idempotency_key")
                if key:
                    latest_by_key[key] = item
        available_row_ids: list[str] = []
        counts = {
            "eligible": len(eligible),
            "available": 0,
            "reserved": 0,
            "created_verified": 0,
            "created_unverified": 0,
            "rejected": 0,
            "unknown": 0,
        }
        for item in eligible:
            previous = latest_by_key.get(item.get("idempotency_key"))
            status = (previous or {}).get("status")
            if previous is None or status == "NOT_ATTEMPTED":
                available_row_ids.append(item["row_id"])
                counts["available"] += 1
            elif status == "CREATED_VERIFIED":
                counts["created_verified"] += 1
            elif status == "CREATED_UNVERIFIED":
                counts["created_unverified"] += 1
            elif status == "REJECTED":
                counts["rejected"] += 1
            elif status == "UNKNOWN":
                counts["unknown"] += 1
            else:
                counts["reserved"] += 1
        return {
            "objective": self.objective if self.objective in {"4D", "4E"} else "4C.2",
            "mode": (
                "SUCCESSIVE_HIERARCHY_BATCHES"
                if self.objective == "4E"
                else
                "SUCCESSIVE_MULTI_TYPE_BATCHES"
                if self.objective == "4D"
                else "SUCCESSIVE_CONTROLLED_BATCHES"
            ),
            "proposal_id": proposal_id,
            "proposal_version": proposal["version"],
            "dry_run_id": dry_run["dry_run_id"],
            "max_items_per_batch": int(self.policy.document["max_items_per_execution"]),
            "available_row_ids": available_row_ids,
            "counts": counts,
            "batch_count": len(batches),
            "real_mcp_calls": sum(int(batch.get("real_mcp_calls", 0)) for batch in batches),
            "automatic_retries": 0,
        }

    async def _revalidate_all_sprints(self, intent: dict[str, Any], username: str) -> None:
        sprint_items = [item for item in intent["items"] if ((item.get("sprint_resolution") or {}).get("selected") or {}).get("id")]
        if not sprint_items:
            return
        try:
            current_sprints = await self.gateway.list_sprints(username, "AT", force_refresh=True)
        except Exception as exc:
            raise Objective4C1Error(
                "No fue posible revalidar los Sprints; no se creo ninguna actividad: " + str(exc)[:300]
            ) from exc
        for item in sprint_items:
            selected = item["sprint_resolution"]["selected"]
            current = revalidate_sprint(str(selected["id"]), current_sprints)
            if current is None:
                raise Objective4C1Error(
                    f"El Sprint '{selected.get('name')}' ya no esta activo/futuro. No se creo ninguna actividad."
                )
            item["sprint_resolution"]["selected"] = current
            item["sprint_revalidated_at"] = _iso(self.now())
        intent["updated_at"] = _iso(self.now())
        intent["audit"].append(self._audit("BATCH_CONFIRMED", username, self.now(), "ALL_SPRINTS_REVALIDATED"))
        self.repository.update_execution_intent(intent)

    def _current_documents(
        self, proposal_id: str, intent: dict[str, Any] | None = None
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        proposal = self.repository.get(proposal_id)
        dry_run = self.repository.get_latest_dry_run(proposal_id)
        if proposal is None or proposal.get("status") != "APPROVED" or dry_run is None:
            raise Objective4C1Error("Se requiere una propuesta aprobada y su Dry run vigente.")
        if dry_run.get("proposal_version") != proposal.get("version") or dry_run.get("summary", {}).get("blocked", 0) != 0:
            raise Objective4C1Error("La propuesta o su prevalidacion cambiaron; no se permite escribir.")
        if intent and (
            intent.get("proposal_version") != proposal.get("version")
            or intent.get("dry_run_id") != dry_run.get("dry_run_id")
        ):
            raise Objective4C1Error("La propuesta o su prevalidacion cambiaron; prepara un lote nuevo.")
        return proposal, dry_run

    def _owned(self, execution_id: str, username: str) -> dict[str, Any]:
        intent = self.repository.get_execution_intent(execution_id)
        if intent is None or intent.get("objective") != self.objective:
            raise Objective4C1Error("No existe el lote solicitado.")
        if intent.get("created_by") != username:
            raise Objective4C1Error("El lote pertenece a otro usuario.")
        return intent

    def _assert_not_expired(self, intent: dict[str, Any]) -> None:
        if self.now() > _parse_iso(intent["confirmation"]["expires_at"]):
            raise Objective4C1Error("La confirmacion caduco; prepara nuevamente el lote.")

    def _stop(self, intent: dict[str, Any], failed_index: int, status: str, username: str) -> None:
        for item in intent["items"][failed_index + 1:]:
            if item["status"] == "PENDING":
                item["status"] = "NOT_ATTEMPTED"
                item["result"] = "STOPPED_AFTER_PREVIOUS_ITEM"
        now = self.now()
        intent["status"] = status
        intent["completed_at"] = _iso(now)
        intent["updated_at"] = _iso(now)
        intent["summary"] = self._summary(intent["items"])
        intent["real_mcp_calls"] = sum(int(item.get("real_mcp_calls", 0)) for item in intent["items"])
        intent["audit"].append(self._audit(status, username, now, "BATCH_STOPPED_ON_FIRST_FAILURE"))

    @staticmethod
    def _summary(items: list[dict[str, Any]]) -> dict[str, int]:
        return {
            "total": len(items),
            "pending": sum(item["status"] == "PENDING" for item in items),
            "submitted": sum(item["status"] == "SUBMITTED" for item in items),
            "created_verified": sum(item["status"] == "CREATED_VERIFIED" for item in items),
            "created_unverified": sum(item["status"] == "CREATED_UNVERIFIED" for item in items),
            "rejected": sum(item["status"] == "REJECTED" for item in items),
            "unknown": sum(item["status"] == "UNKNOWN" for item in items),
            "not_attempted": sum(item["status"] == "NOT_ATTEMPTED" for item in items),
        }

    @staticmethod
    def _audit(state: str, username: str, at: datetime, event: str) -> dict[str, Any]:
        return {"state": state, "event": event, "at": _iso(at), "by": username}
