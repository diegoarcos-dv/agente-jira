from __future__ import annotations

import copy
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar
from uuid import uuid4

from ..atlassian import AtlassianIntegrationError
from ..auth import AuthenticatedUser
from ..config import Settings
from ..controlled_jira import ControlledJiraCreateCore, canonical_hash
from ..dry_run import _field_kind, _normalize, _work_type_matches
from ..execution_policy import JiraExecutionPolicy
from ..repository import ProposalRepository
from .models import (
    VoiceConversationContext,
    VoiceJiraOperationView,
    VoiceJiraPreview,
    VoicePendingConfirmation,
    VoiceTaskDraft,
)


class VoiceJiraValidationError(RuntimeError):
    pass


class VoiceJiraConfirmationError(RuntimeError):
    pass


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)


def _safe_identity_hash(value: str) -> str:
    return canonical_hash({"identity": value})[:24]


def _draft_fingerprint(draft: VoiceTaskDraft) -> dict[str, Any]:
    return draft.model_dump(exclude={"status"}, mode="json")


def _priority_field(fields: list[dict[str, Any]]) -> dict[str, Any] | None:
    return next(
        (
            field
            for field in fields
            if _normalize(field.get("id")) in {"priority", "prioridad"}
            or _normalize(field.get("name")) in {"priority", "prioridad"}
        ),
        None,
    )


class VoiceJiraCreationService:
    """Voice adapter into the shared controlled Jira create/readback core."""

    TERMINAL_STATUSES: ClassVar[set[str]] = {
        "CREATED_VERIFIED",
        "CREATED_UNVERIFIED",
        "REJECTED",
        "UNKNOWN",
        "CANCELLED",
    }

    def __init__(
        self,
        repository: ProposalRepository,
        policy: JiraExecutionPolicy,
        atlassian_manager,
        create_core: ControlledJiraCreateCore,
        settings: Settings,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.repository = repository
        self.policy = policy
        self.atlassian_manager = atlassian_manager
        self.create_core = create_core
        self.settings = settings
        self.now = now

    async def prepare(
        self,
        draft: VoiceTaskDraft,
        user: AuthenticatedUser,
        context: VoiceConversationContext,
    ) -> tuple[VoiceJiraOperationView, VoicePendingConfirmation]:
        existing = context.pending_confirmation
        if (
            isinstance(existing, VoicePendingConfirmation)
            and existing.action == "create_jira_issue"
            and existing.draft_id == draft.id
            and existing.execution_id
            and canonical_hash(_draft_fingerprint(draft))
            == canonical_hash(
                (self.repository.get_execution_intent(existing.execution_id) or {}).get(
                    "draft_fingerprint", {}
                )
            )
        ):
            stored = self.repository.get_execution_intent(existing.execution_id)
            if stored and stored.get("status") == "VOICE_PREPARED":
                return self._view(stored, reused=True), existing

        if draft.issue_type == "Subtask" and not draft.parent_issue_key:
            raise VoiceJiraValidationError(
                "No puedo preparar la Subtask: falta una clave Jira padre válida."
            )
        if draft.issue_type != "Task":
            raise VoiceJiraValidationError(
                "Gate Voice 3 permite crear por voz únicamente Task. "
                "Epic, Story, Bug y Subtask continúan disponibles en el flujo web 4E."
            )
        restore = getattr(self.atlassian_manager, "ensure_restored", None)
        if restore is not None:
            await restore(user.username)
        try:
            snapshot = self.atlassian_manager.connected_snapshot(user.username)
            tools = self.atlassian_manager.objective_4_tool_readiness(user.username)
        except AtlassianIntegrationError as exc:
            raise VoiceJiraValidationError(
                "Jira no está conectada. No se preparó ninguna creación."
            ) from exc

        contract_errors = self.create_core.validate_tool_contract(
            tools,
            require_additional_fields=True,
        )
        if contract_errors:
            raise VoiceJiraValidationError(" ".join(contract_errors))

        space = next(
            (
                item
                for item in snapshot.get("spaces", [])
                if item.get("key") == draft.space and item.get("found", True)
            ),
            None,
        )
        if space is None:
            raise VoiceJiraValidationError(f"El Space {draft.space} no está visible en Jira.")
        work_type = next(
            (
                item
                for item in space.get("work_types", [])
                if _work_type_matches(draft.issue_type, item.get("name"))
            ),
            None,
        )
        if work_type is None:
            raise VoiceJiraValidationError(
                f"{draft.issue_type} no existe en el Space {draft.space}."
            )
        fields = list(work_type.get("fields") or [])
        if not fields:
            raise VoiceJiraValidationError(
                f"Jira no devolvió los campos de {draft.space} / {draft.issue_type}."
            )
        if not draft.summary.strip():
            raise VoiceJiraValidationError("Necesito un resumen válido antes de crear la Task.")

        exact_active_account = False
        if draft.assignee is not None:
            try:
                candidates = await self.atlassian_manager.find_assignees(
                    user.username,
                    draft.space,
                    draft.assignee.display_name,
                )
            except AtlassianIntegrationError as exc:
                raise VoiceJiraValidationError(
                    "No pude volver a validar el responsable en Jira."
                ) from exc
            exact = [
                candidate
                for candidate in candidates
                if candidate.get("active", True)
                and str(candidate.get("account_id") or "") == draft.assignee.account_id
            ]
            exact_active_account = len(exact) == 1
            if not exact_active_account:
                raise VoiceJiraValidationError(
                    f"El responsable {draft.assignee.display_name} ya no tiene una coincidencia "
                    "activa e inequívoca en Jira."
                )

            constraint = f"{draft.space}:{work_type.get('id')}"
            allowed_accounts = snapshot.get("_assignee_allowed_accounts", {})
            if constraint in allowed_accounts and draft.assignee.account_id not in set(
                allowed_accounts[constraint]
            ):
                raise VoiceJiraValidationError(
                    f"{draft.assignee.display_name} no es asignable para {draft.issue_type} "
                    f"en {draft.space}."
                )
        elif self.policy.document["require_exact_active_account"]:
            raise VoiceJiraValidationError(
                "No puedo crearla todavía. Necesito que indiques un responsable válido."
            )

        priority_field = _priority_field(fields)
        validated_priority: dict[str, str] | None = None
        if draft.priority:
            validate_priority = getattr(self.atlassian_manager, "validate_priority", None)
            if validate_priority is None:
                raise VoiceJiraValidationError(
                    "La integración Jira no permite validar Prioridad de forma segura."
                )
            try:
                validated_priority = await validate_priority(
                    user.username,
                    draft.space,
                    draft.priority,
                )
            except AtlassianIntegrationError as exc:
                raise VoiceJiraValidationError(
                    f"La prioridad {draft.priority} no pudo validarse en Jira."
                ) from exc

        values = {
            "project": draft.space,
            "issuetype": work_type.get("id"),
            "summary": draft.summary,
            "description": draft.description,
            "assignee": draft.assignee.account_id if draft.assignee else None,
            "reporter": (snapshot.get("atlassian_user") or {}).get("account_id"),
            "priority": draft.priority,
            "parent": draft.parent_issue_key,
        }
        missing: list[str] = []
        for field in fields:
            if not field.get("required"):
                continue
            kind = _field_kind(field)
            if kind is None and field is priority_field:
                kind = "priority"
            if kind is None:
                missing.append(str(field.get("name") or field.get("id") or "desconocido"))
            elif not values.get(kind):
                missing.append(str(field.get("name") or kind))
        if missing:
            raise VoiceJiraValidationError(
                "No puedo crearla todavía. Faltan campos obligatorios de Jira: "
                + ", ".join(missing)
                + "."
            )

        additional_fields: dict[str, Any] = {
            "labels": [self.policy.document["test_label"]]
        }
        expected_fields: dict[str, Any] = {}
        readback_fields = ["summary", "description", "issuetype", "assignee", "project", "labels"]
        if draft.priority and validated_priority:
            priority_id = str((priority_field or {}).get("id") or "priority")
            additional_fields[priority_id] = {"name": validated_priority["name"]}
            selected = next(
                (
                    option
                    for option in priority_field.get("options", [])
                    if _normalize(option.get("value") or option.get("label") or option.get("name"))
                    == _normalize(draft.priority)
                ),
                None,
            )
            expected_fields["priority"] = {
                "field_id": priority_id,
                "id": (selected or {}).get("jira_id") or (selected or {}).get("id"),
                "name": draft.priority,
            }
            readback_fields.append(priority_id)

        arguments = {
            "cloudId": snapshot.get("cloud_id"),
            "projectKey": draft.space,
            "issueTypeName": draft.issue_type,
            "summary": draft.summary.strip(),
            "description": draft.description.strip() if draft.description else None,
            "assignee_account_id": draft.assignee.account_id if draft.assignee else None,
            "additional_fields": additional_fields,
            "contentFormat": "markdown",
            "responseContentFormat": "markdown",
        }
        arguments = {
            key: value
            for key, value in arguments.items()
            if value is not None and value != {}
        }
        policy_violations = self.policy.direct_create_gate_violations(
            space=draft.space,
            work_type=draft.issue_type,
            tool_name="createJiraIssue",
            exact_active_account=exact_active_account,
            assignee_in_atomic_create=bool(arguments.get("assignee_account_id")),
            second_confirmation=True,
        )
        if policy_violations:
            raise VoiceJiraValidationError(
                "La política de ejecución bloqueó la preparación: "
                + ", ".join(policy_violations)
            )

        now = self.now()
        payload_hash = canonical_hash(arguments)
        confirmation_id = f"VCONF-{uuid4().hex[:24].upper()}"
        session_hash = _safe_identity_hash(context.session_id)
        execution_hash = canonical_hash(
            {
                "username": user.username,
                "session_hash": session_hash,
                "draft_id": draft.id,
                "payload_hash": payload_hash,
                "confirmation_id": confirmation_id,
            }
        )
        execution_id = f"VOICE-{execution_hash[:32].upper()}"
        preview = VoiceJiraPreview(
            issue_type=draft.issue_type,
            summary=draft.summary,
            description=draft.description,
            assignee=draft.assignee.display_name if draft.assignee else None,
            priority=draft.priority,
            space=draft.space,
            parent=draft.parent_issue_key,
        )
        created_at = _iso(now)
        expires_at = _iso(
            now + timedelta(seconds=self.settings.voice_jira_confirmation_ttl_seconds)
        )
        intent = {
            "objective": "VOICE-3",
            "mode": "CONTROLLED_VOICE_CREATE",
            "execution_id": execution_id,
            "status": "VOICE_PREPARED",
            "proposal_id": f"VOICE-{session_hash}",
            "proposal_version": 1,
            "row_id": draft.id,
            "dry_run_id": confirmation_id,
            "idempotency_key": f"AJV-{execution_hash[:40]}",
            "payload_hash": payload_hash,
            "payload": {"tool": "createJiraIssue", "arguments": arguments},
            "draft_id": draft.id,
            "draft_fingerprint": _draft_fingerprint(draft),
            "draft_hash": canonical_hash(_draft_fingerprint(draft)),
            "session_hash": session_hash,
            "confirmation": {
                "action": "create_jira_issue",
                "confirmation_id": confirmation_id,
                "expires_at": expires_at,
                "confirmed_at": None,
                "confirmed_by": None,
            },
            "preview": preview.model_dump(mode="json"),
            "readback_fields": list(dict.fromkeys(readback_fields)),
            "expected_fields": expected_fields,
            "created_at": created_at,
            "updated_at": created_at,
            "created_by": user.username,
            "submitted_at": None,
            "completed_at": None,
            "issue_key": None,
            "issue_url": None,
            "readback": None,
            "result": None,
            "error": None,
            "real_mcp_calls": 0,
            "automatic_retries": 0,
            "create_elapsed_ms": None,
            "readback_elapsed_ms": None,
            "audit": [self._audit("VOICE_PREPARED", user.username, session_hash, now)],
        }
        stored, reused = self.repository.save_execution_intent(intent)
        pending = VoicePendingConfirmation(
            action="create_jira_issue",
            confirmation_id=confirmation_id,
            execution_id=execution_id,
            draft_id=draft.id,
            payload_hash=payload_hash,
            created_at=created_at,
            expires_at=expires_at,
            preview=preview,
        )
        return self._view(stored, reused=reused), pending

    async def confirm_and_execute(
        self,
        user: AuthenticatedUser,
        context: VoiceConversationContext,
        confirmation_id: str,
        payload_hash: str,
    ) -> VoiceJiraOperationView:
        pending = context.pending_confirmation
        if not isinstance(pending, VoicePendingConfirmation) or pending.action != "create_jira_issue":
            raise VoiceJiraConfirmationError(
                "No hay una creación Jira pendiente. Un ‘sí’ aislado no ejecuta cambios."
            )
        if pending.confirmation_id != confirmation_id or pending.payload_hash != payload_hash:
            raise VoiceJiraConfirmationError(
                "La confirmación no corresponde al payload preparado."
            )
        if not pending.execution_id:
            raise VoiceJiraConfirmationError("La confirmación no tiene una ejecución válida.")
        intent = self.repository.get_execution_intent(pending.execution_id)
        if intent is None:
            context.pending_confirmation = None
            raise VoiceJiraConfirmationError("La preparación Jira ya no existe.")
        self._assert_identity(intent, user, context)
        if self.now() > _parse_iso(pending.expires_at):
            self._cancel_intent(intent, user.username, "CONFIRMATION_EXPIRED")
            context.pending_confirmation = None
            raise VoiceJiraConfirmationError(
                "La confirmación expiró. Prepara nuevamente la creación."
            )
        draft = context.draft
        if (
            draft is None
            or draft.id != pending.draft_id
            or canonical_hash(_draft_fingerprint(draft)) != intent.get("draft_hash")
        ):
            self._cancel_intent(intent, user.username, "DRAFT_CHANGED")
            context.pending_confirmation = None
            raise VoiceJiraConfirmationError(
                "El borrador cambió. La confirmación anterior quedó invalidada."
            )
        if intent.get("payload_hash") != payload_hash:
            context.pending_confirmation = None
            raise VoiceJiraConfirmationError(
                "El hash del payload cambió. Prepara nuevamente la creación."
            )
        if intent["status"] in self.TERMINAL_STATUSES:
            context.pending_confirmation = None
            return self._view(intent, reused=True)
        if intent["status"] == "SUBMITTED":
            context.pending_confirmation = None
            return self._view(intent, reused=True, forced_state="UNKNOWN_RESULT")
        if intent["status"] != "VOICE_PREPARED":
            raise VoiceJiraConfirmationError(
                "La operación ya no está esperando confirmación y no se reenviará."
            )

        arguments = intent["payload"]["arguments"]
        violations = self.policy.direct_create_gate_violations(
            space=str(arguments.get("projectKey") or ""),
            work_type=str(arguments.get("issueTypeName") or ""),
            tool_name="createJiraIssue",
            exact_active_account=bool(arguments.get("assignee_account_id")),
            assignee_in_atomic_create=bool(arguments.get("assignee_account_id")),
            second_confirmation=True,
        )
        if violations:
            raise VoiceJiraConfirmationError(
                "La política bloqueó la ejecución: " + ", ".join(violations)
            )

        now = self.now()
        intent["status"] = "VOICE_CONFIRMED"
        intent["updated_at"] = _iso(now)
        intent["confirmation"]["confirmed_at"] = _iso(now)
        intent["confirmation"]["confirmed_by"] = user.username
        intent["audit"].append(
            self._audit("VOICE_CONFIRMED", user.username, intent["session_hash"], now)
        )
        if not self.repository.transition_execution_intent(intent, "VOICE_PREPARED"):
            current = self.repository.get_execution_intent(intent["execution_id"])
            context.pending_confirmation = None
            if current is None:
                raise VoiceJiraConfirmationError("La ejecución dejó de estar disponible.")
            return self._view(current, reused=True, forced_state="UNKNOWN_RESULT")

        now = self.now()
        intent["status"] = "SUBMITTED"
        intent["submitted_at"] = _iso(now)
        intent["updated_at"] = _iso(now)
        intent["audit"].append(
            self._audit("SUBMITTED", user.username, intent["session_hash"], now)
        )
        if not self.repository.transition_execution_intent(intent, "VOICE_CONFIRMED"):
            current = self.repository.get_execution_intent(intent["execution_id"])
            context.pending_confirmation = None
            if current is None:
                raise VoiceJiraConfirmationError("La ejecución dejó de estar disponible.")
            return self._view(current, reused=True, forced_state="UNKNOWN_RESULT")
        context.pending_confirmation = None

        try:
            result = await self.create_core.create_and_verify(
                user.username,
                arguments,
                intent["readback_fields"],
                int(self.policy.document["execution_timeout_seconds"]),
                expected_fields=intent.get("expected_fields"),
            )
        except Exception as exc:  # noqa: BLE001 - cualquier fallo posterior al envío debe clasificarse sin retry
            now = self.now()
            uncertain = bool(getattr(exc, "outcome_uncertain", False))
            intent["status"] = "UNKNOWN" if uncertain else "REJECTED"
            intent["updated_at"] = _iso(now)
            intent["completed_at"] = _iso(now)
            intent["real_mcp_calls"] = int(getattr(exc, "real_mcp_calls", 1))
            intent["automatic_retries"] = 0
            intent["result"] = "OUTCOME_UNKNOWN" if uncertain else "JIRA_REJECTED"
            intent["error"] = str(exc)[:700]
            intent["audit"].append(
                self._audit(intent["status"], user.username, intent["session_hash"], now)
            )
            self.repository.update_execution_intent(intent)
            return self._view(intent)

        now = self.now()
        intent["status"] = result["status"]
        intent["updated_at"] = _iso(now)
        intent["completed_at"] = _iso(now)
        intent["issue_key"] = result.get("issue_key")
        intent["issue_url"] = (
            f"{self.settings.atlassian_site_url.rstrip('/')}/browse/{result['issue_key']}"
            if result.get("issue_key")
            else None
        )
        intent["readback"] = {
            "checks": result["checks"],
            "payload": result.get("readback"),
            "error": result.get("readback_error"),
        }
        intent["real_mcp_calls"] = int(result.get("real_mcp_calls", 2))
        intent["automatic_retries"] = 0
        intent["result"] = (
            "CREATED_AND_VERIFIED"
            if result["verified"]
            else "CREATED_READBACK_INCOMPLETE"
        )
        intent["create_elapsed_ms"] = result.get("create_elapsed_ms")
        intent["readback_elapsed_ms"] = result.get("readback_elapsed_ms")
        intent["audit"].append(
            self._audit(intent["status"], user.username, intent["session_hash"], now)
        )
        self.repository.update_execution_intent(intent)
        return self._view(intent)

    def cancel_pending(
        self,
        user: AuthenticatedUser,
        context: VoiceConversationContext,
        confirmation_id: str,
        payload_hash: str,
    ) -> VoiceJiraOperationView:
        pending = context.pending_confirmation
        if not isinstance(pending, VoicePendingConfirmation) or pending.action != "create_jira_issue":
            raise VoiceJiraConfirmationError("No hay una creación Jira pendiente para cancelar.")
        if pending.confirmation_id != confirmation_id or pending.payload_hash != payload_hash:
            raise VoiceJiraConfirmationError("La cancelación no corresponde al payload preparado.")
        intent = self.repository.get_execution_intent(str(pending.execution_id or ""))
        if intent is None:
            context.pending_confirmation = None
            raise VoiceJiraConfirmationError("La preparación Jira ya no existe.")
        self._assert_identity(intent, user, context)
        if intent["status"] == "SUBMITTED":
            context.pending_confirmation = None
            return self._view(intent, reused=True, forced_state="UNKNOWN_RESULT")
        if intent["status"] not in self.TERMINAL_STATUSES:
            self._cancel_intent(intent, user.username, "USER_CANCELLED")
        context.pending_confirmation = None
        return self._view(intent)

    def invalidate_pending(
        self,
        context: VoiceConversationContext,
        reason: str = "DRAFT_CHANGED",
    ) -> None:
        pending = context.pending_confirmation
        if not isinstance(pending, VoicePendingConfirmation) or pending.action != "create_jira_issue":
            return
        intent = self.repository.get_execution_intent(str(pending.execution_id or ""))
        if (
            intent
            and intent.get("created_by") == context.username
            and intent.get("session_hash") == _safe_identity_hash(context.session_id)
            and intent.get("status") not in self.TERMINAL_STATUSES
            and intent.get("status") != "SUBMITTED"
        ):
            self._cancel_intent(intent, context.username, reason)
        context.pending_confirmation = None

    def _assert_identity(
        self,
        intent: dict[str, Any],
        user: AuthenticatedUser,
        context: VoiceConversationContext,
    ) -> None:
        if intent.get("created_by") != user.username:
            raise VoiceJiraConfirmationError("La preparación pertenece a otro usuario.")
        if intent.get("session_hash") != _safe_identity_hash(context.session_id):
            raise VoiceJiraConfirmationError("La preparación pertenece a otra sesión.")
        if context.username != user.username:
            raise VoiceJiraConfirmationError("La sesión autenticada cambió.")

    def _cancel_intent(self, intent: dict[str, Any], username: str, event: str) -> None:
        now = self.now()
        intent["status"] = "CANCELLED"
        intent["updated_at"] = _iso(now)
        intent["completed_at"] = _iso(now)
        intent["result"] = event
        intent["audit"].append(
            self._audit("CANCELLED", username, intent["session_hash"], now, event)
        )
        self.repository.update_execution_intent(intent)

    @staticmethod
    def _audit(
        state: str,
        username: str,
        session_hash: str,
        at: datetime,
        event: str | None = None,
    ) -> dict[str, Any]:
        return {
            "state": state,
            "event": event or state,
            "at": _iso(at),
            "user": _safe_identity_hash(username),
            "session": session_hash,
        }

    @staticmethod
    def _state(status: str) -> str:
        return {
            "VOICE_PREPARED": "AWAITING_CONFIRMATION",
            "VOICE_CONFIRMED": "CREATING_JIRA",
            "SUBMITTED": "VERIFYING_JIRA",
            "CREATED_VERIFIED": "SUCCESS",
            "CREATED_UNVERIFIED": "UNKNOWN_RESULT",
            "UNKNOWN": "UNKNOWN_RESULT",
            "REJECTED": "EXECUTION_ERROR",
            "CANCELLED": "CANCELLED",
        }.get(status, "EXECUTION_ERROR")

    def _view(
        self,
        intent: dict[str, Any],
        *,
        reused: bool = False,
        forced_state: str | None = None,
    ) -> VoiceJiraOperationView:
        return VoiceJiraOperationView(
            execution_id=intent["execution_id"],
            state=forced_state or self._state(intent["status"]),
            payload_hash=intent["payload_hash"],
            preview=VoiceJiraPreview.model_validate(copy.deepcopy(intent["preview"])),
            issue_key=intent.get("issue_key"),
            issue_url=intent.get("issue_url"),
            readback_checks=copy.deepcopy((intent.get("readback") or {}).get("checks") or {}),
            create_elapsed_ms=intent.get("create_elapsed_ms"),
            readback_elapsed_ms=intent.get("readback_elapsed_ms"),
            reused=reused,
        )
