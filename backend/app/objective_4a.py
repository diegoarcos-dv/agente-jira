from __future__ import annotations

import copy
import hashlib
import json
import re
import unicodedata
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

from .execution_policy import JiraExecutionPolicy
from .repository import ProposalRepository


class Objective4AError(RuntimeError):
    pass


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _summary_slug(value: str, limit: int = 56) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = "".join(
        character
        for character in normalized
        if not unicodedata.combining(character) and ord(character) < 128
    )
    slug = re.sub(r"[^A-Za-z0-9]+", "_", ascii_value).strip("_")
    return (slug or "Actividad")[:limit]


class SimulatedJiraCreateGateway:
    """Local-only test double. It deliberately has no MCP client or network dependency."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def simulate_create(self, payload: dict[str, Any]) -> dict[str, Any]:
        cloned = copy.deepcopy(payload)
        self.calls.append(cloned)
        return {
            "simulation_key": f"SIM-AT-{_canonical_hash(cloned)[:12].upper()}",
            "accepted": True,
            "transport": "LOCAL_SIMULATOR",
            "mcp_tool_invoked": None,
            "jira_issue_created": False,
        }


class JiraExecutionPreparationService:
    CONFIRMATION_TTL = timedelta(minutes=15)

    def __init__(
        self,
        repository: ProposalRepository,
        policy: JiraExecutionPolicy,
        simulator: SimulatedJiraCreateGateway | None = None,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.repository = repository
        self.policy = policy
        self.simulator = simulator or SimulatedJiraCreateGateway()
        self.now = now

    def prepare(
        self,
        proposal: dict[str, Any],
        dry_run: dict[str, Any],
        row_id: str,
        username: str,
        jira_snapshot: dict[str, Any] | None,
    ) -> dict[str, Any]:
        self._assert_simulation_safe()
        if proposal.get("status") != "APPROVED":
            raise Objective4AError("La simulacion requiere una propuesta aprobada e inmutable.")
        if dry_run.get("proposal_version") != proposal.get("version"):
            raise Objective4AError("El Dry run no corresponde a la version aprobada actual.")
        if dry_run.get("write_performed") is not False:
            raise Objective4AError("La evidencia de prevalidacion no garantiza cero escrituras.")
        if dry_run.get("summary", {}).get("blocked", 0) != 0:
            raise Objective4AError(
                "Resuelve todos los bloqueos del Dry run antes de preparar la simulacion."
            )

        item = next((entry for entry in dry_run.get("items", []) if entry["row_id"] == row_id), None)
        if item is None:
            raise Objective4AError("La actividad elegida no pertenece al Dry run actual.")
        if item.get("status") not in {"READY", "READY_WITH_WARNINGS"}:
            raise Objective4AError("La actividad elegida no esta lista para una simulacion.")
        if item.get("space") not in self.policy.document["allowed_spaces"]:
            raise Objective4AError("El Objetivo 4A solo permite preparar una Task en AT.")
        if item.get("work_type") not in self.policy.document["allowed_work_types"]:
            raise Objective4AError("El Objetivo 4A solo permite el Work Type Task.")
        logical = item.get("logical_payload")
        if not isinstance(logical, dict):
            raise Objective4AError("El Dry run no contiene un payload logico verificable.")
        assignee = item.get("assignee") or {}
        if not assignee.get("account_id"):
            raise Objective4AError("La actividad no tiene una cuenta Atlassian exacta y activa.")

        now = self.now()
        proposal_short = str(proposal["proposal_id"]).split("-")[0].upper()
        canary_title = (
            f"{self.policy.document['title_prefix']}"
            f"{now.strftime('%Y%m%d_%H%M')}_{proposal_short}_{_summary_slug(item['title'])}"
        )[:255]
        snapshot = jira_snapshot or {}
        candidate_arguments = {
            "cloudId": snapshot.get("cloud_id"),
            "projectKey": logical.get("project_key"),
            "issueTypeId": logical.get("work_type_id"),
            "summary": canary_title,
            "description": logical.get("description"),
            "assigneeAccountId": logical.get("assignee_account_id"),
            "fields": logical.get("jira_fields") or {},
            "labels": [self.policy.document["test_label"]],
        }
        payload = {
            "tool": self.policy.required_write_tool,
            "contract_status": "CANDIDATE_UNTIL_REAL_SCHEMA_IS_CONFIRMED",
            "arguments": candidate_arguments,
        }
        payload_hash = _canonical_hash(payload)
        stable_key = {
            "proposal_id": proposal["proposal_id"],
            "proposal_version": proposal["version"],
            "row_id": row_id,
            "dry_run_id": dry_run["dry_run_id"],
            "payload_hash": payload_hash,
        }
        execution_id = f"EXE-{_canonical_hash(stable_key)[:32]}"
        created_at = _iso(now)
        intent = {
            "objective": "4A",
            "mode": "SIMULATION_ONLY",
            "execution_id": execution_id,
            "status": "PREPARED",
            "proposal_id": proposal["proposal_id"],
            "proposal_version": proposal["version"],
            "row_id": row_id,
            "dry_run_id": dry_run["dry_run_id"],
            "idempotency_key": item["idempotency_key"],
            "payload_hash": payload_hash,
            "payload": payload,
            "preview": {
                "title": canary_title,
                "description": logical.get("description"),
                "space": item["space"],
                "work_type": item["work_type"],
                "assignee": {
                    "display_name": assignee.get("display_name"),
                    "account_id": assignee.get("account_id"),
                    "validation": assignee.get("validation"),
                },
                "warnings": item.get("warnings", []),
            },
            "policy": self.policy.public_summary(),
            "created_at": created_at,
            "updated_at": created_at,
            "created_by": username,
            "confirmation": {
                "required": True,
                "expires_at": _iso(now + self.CONFIRMATION_TTL),
                "confirmed_at": None,
                "confirmed_by": None,
            },
            "simulation": {
                "simulated_calls": 0,
                "real_mcp_calls": 0,
                "write_performed": False,
                "result": None,
            },
            "audit": [self._audit("PREPARED", username, now, "SIMULATION_PREPARED")],
        }
        stored, reused = self.repository.save_execution_intent(intent)
        if reused and stored["status"] in {"EXPIRED", "CANCELLED"}:
            stored["status"] = "PREPARED"
            stored["updated_at"] = created_at
            stored["confirmation"] = intent["confirmation"]
            stored["audit"].append(
                self._audit("PREPARED", username, now, "SIMULATION_REPREPARED")
            )
            stored = self.repository.update_execution_intent(stored)
        return {**stored, "reused": reused, "jira_write_enabled": False}

    def confirm(
        self,
        execution_id: str,
        payload_hash: str,
        username: str,
    ) -> dict[str, Any]:
        intent = self._get_owned(execution_id, username)
        if intent["status"] != "PREPARED":
            raise Objective4AError("La preparacion ya no espera confirmacion.")
        self._assert_current(intent, username)
        self._assert_not_expired(intent, username)
        if not secrets_compare(intent["payload_hash"], payload_hash):
            self._invalidate(intent, username, "PAYLOAD_HASH_CHANGED")
            raise Objective4AError(
                "La vista previa cambio. Vuelve a preparar la simulacion antes de confirmar."
            )

        now = self.now()
        intent["status"] = "CONFIRMED"
        intent["updated_at"] = _iso(now)
        intent["confirmation"]["confirmed_at"] = _iso(now)
        intent["confirmation"]["confirmed_by"] = username
        intent["audit"].append(
            self._audit("CONFIRMED", username, now, "SECOND_CONFIRMATION_ACCEPTED")
        )
        updated = self.repository.update_execution_intent(intent)
        return {**updated, "reused": False, "jira_write_enabled": False}

    def simulate(self, execution_id: str, username: str) -> dict[str, Any]:
        self._assert_simulation_safe()
        intent = self._get_owned(execution_id, username)
        if intent["status"] == "SIMULATED":
            return {**intent, "reused": True, "jira_write_enabled": False}
        if intent["status"] != "CONFIRMED":
            raise Objective4AError("Confirma la vista previa antes de ejecutar la simulacion.")
        self._assert_current(intent, username)
        self._assert_not_expired(intent, username)
        if _canonical_hash(intent["payload"]) != intent["payload_hash"]:
            self._invalidate(intent, username, "PAYLOAD_CHANGED_AFTER_CONFIRMATION")
            raise Objective4AError("La confirmacion caduco porque el payload cambio.")

        result = self.simulator.simulate_create(intent["payload"])
        now = self.now()
        intent["status"] = "SIMULATED"
        intent["updated_at"] = _iso(now)
        intent["simulation"] = {
            "simulated_calls": 1,
            "real_mcp_calls": 0,
            "write_performed": False,
            "result": result,
        }
        intent["audit"].append(
            self._audit("SIMULATED", username, now, "LOCAL_SIMULATOR_COMPLETED")
        )
        updated = self.repository.update_execution_intent(intent)
        return {**updated, "reused": False, "jira_write_enabled": False}

    def cancel(self, execution_id: str, username: str) -> dict[str, Any]:
        intent = self._get_owned(execution_id, username)
        if intent["status"] not in {"PREPARED", "CONFIRMED"}:
            raise Objective4AError("Esta preparacion ya no puede cancelarse.")
        now = self.now()
        intent["status"] = "CANCELLED"
        intent["updated_at"] = _iso(now)
        intent["audit"].append(self._audit("CANCELLED", username, now, "USER_CANCELLED"))
        updated = self.repository.update_execution_intent(intent)
        return {**updated, "reused": False, "jira_write_enabled": False}

    def latest(self, proposal_id: str) -> dict[str, Any] | None:
        intent = self.repository.get_latest_execution_intent(proposal_id, objective="4A")
        if intent is None:
            return None
        return {**intent, "reused": True, "jira_write_enabled": False}

    def _assert_simulation_safe(self) -> None:
        violations = self.policy.simulation_readiness()
        if violations:
            raise Objective4AError(
                "La politica no permite ejecutar la simulacion local: " + ", ".join(violations)
            )

    def _assert_current(self, intent: dict[str, Any], username: str) -> None:
        proposal = self.repository.get(intent["proposal_id"])
        dry_run = self.repository.get_latest_dry_run(intent["proposal_id"])
        if (
            proposal is None
            or proposal.get("version") != intent["proposal_version"]
            or proposal.get("status") != "APPROVED"
            or dry_run is None
            or dry_run.get("dry_run_id") != intent["dry_run_id"]
        ):
            self._invalidate(intent, username, "PROPOSAL_OR_DRY_RUN_CHANGED")
            raise Objective4AError(
                "La propuesta o su Dry run cambiaron; prepara una vista previa nueva."
            )

    def _assert_not_expired(self, intent: dict[str, Any], username: str) -> None:
        if self.now() <= _parse_iso(intent["confirmation"]["expires_at"]):
            return
        self._invalidate(intent, username, "CONFIRMATION_EXPIRED", status="EXPIRED")
        raise Objective4AError("La confirmacion caduco; vuelve a preparar la simulacion.")

    def _invalidate(
        self,
        intent: dict[str, Any],
        username: str,
        event: str,
        status: str = "INVALIDATED",
    ) -> None:
        now = self.now()
        intent["status"] = status
        intent["updated_at"] = _iso(now)
        intent["audit"].append(self._audit(status, username, now, event))
        self.repository.update_execution_intent(intent)

    def _get_owned(self, execution_id: str, username: str) -> dict[str, Any]:
        intent = self.repository.get_execution_intent(execution_id)
        if intent is None:
            raise Objective4AError("No existe la preparacion solicitada.")
        if intent["created_by"] != username:
            raise Objective4AError("La preparacion pertenece a otro usuario.")
        return intent

    @staticmethod
    def _audit(state: str, username: str, at: datetime, event: str) -> dict[str, Any]:
        return {
            "state": state,
            "event": event,
            "at": _iso(at),
            "by": username,
            "real_mcp_calls": 0,
            "write_performed": False,
        }


def secrets_compare(left: str, right: str) -> bool:
    # Local import keeps the domain service free of authentication/session concerns.
    import hmac

    return hmac.compare_digest(left, right)
