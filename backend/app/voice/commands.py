from __future__ import annotations

import inspect
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any
from uuid import uuid4

from ..atlassian import AtlassianIntegrationError
from ..auth import AuthenticatedUser
from .context import VoiceContextStore
from .jira import (
    VoiceJiraConfirmationError,
    VoiceJiraCreationService,
    VoiceJiraValidationError,
)
from .models import (
    VoiceConversationContext,
    VoiceDraftAssignee,
    VoiceIntent,
    VoiceJiraOperationView,
    VoicePendingConfirmation,
    VoiceTaskDraft,
)


class CommandRisk(str, Enum):
    READ_ONLY = "READ_ONLY"
    LOCAL_WRITE = "LOCAL_WRITE"
    JIRA_WRITE = "JIRA_WRITE"
    FORBIDDEN = "FORBIDDEN"


@dataclass(frozen=True)
class CommandDefinition:
    name: str
    risk: CommandRisk
    handler: str | None


@dataclass(frozen=True)
class CommandOutcome:
    status: str
    message: str
    context: VoiceConversationContext
    risk: CommandRisk
    draft: VoiceTaskDraft | None = None
    requires_confirmation: bool = False
    persist_context: bool = True
    jira_operation: VoiceJiraOperationView | None = None


COMMAND_REGISTRY: dict[str, CommandDefinition] = {
    "help": CommandDefinition("help", CommandRisk.READ_ONLY, "_help"),
    "get_app_status": CommandDefinition(
        "get_app_status", CommandRisk.READ_ONLY, "_get_app_status"
    ),
    "get_jira_status": CommandDefinition(
        "get_jira_status", CommandRisk.READ_ONLY, "_get_jira_status"
    ),
    "get_current_proposal_summary": CommandDefinition(
        "get_current_proposal_summary",
        CommandRisk.READ_ONLY,
        "_get_current_proposal_summary",
    ),
    "list_validation_errors": CommandDefinition(
        "list_validation_errors", CommandRisk.READ_ONLY, "_list_validation_errors"
    ),
    "list_pending_items": CommandDefinition(
        "list_pending_items", CommandRisk.READ_ONLY, "_list_pending_items"
    ),
    "create_proposal": CommandDefinition(
        "create_proposal", CommandRisk.LOCAL_WRITE, "_unsupported_proposal_creation"
    ),
    "show_current_draft": CommandDefinition(
        "show_current_draft", CommandRisk.READ_ONLY, "_show_current_draft"
    ),
    "prepare_local_task": CommandDefinition(
        "prepare_local_task", CommandRisk.LOCAL_WRITE, "_prepare_local_task"
    ),
    "set_draft_summary": CommandDefinition(
        "set_draft_summary", CommandRisk.LOCAL_WRITE, "_set_draft_summary"
    ),
    "set_draft_description": CommandDefinition(
        "set_draft_description", CommandRisk.LOCAL_WRITE, "_set_draft_description"
    ),
    "set_draft_assignee": CommandDefinition(
        "set_draft_assignee", CommandRisk.LOCAL_WRITE, "_set_draft_assignee"
    ),
    "set_draft_priority": CommandDefinition(
        "set_draft_priority", CommandRisk.LOCAL_WRITE, "_set_draft_priority"
    ),
    "set_draft_issue_type": CommandDefinition(
        "set_draft_issue_type", CommandRisk.LOCAL_WRITE, "_set_draft_issue_type"
    ),
    "cancel_current_draft": CommandDefinition(
        "cancel_current_draft", CommandRisk.LOCAL_WRITE, "_cancel_current_draft"
    ),
    "clear_voice_context": CommandDefinition(
        "clear_voice_context", CommandRisk.LOCAL_WRITE, "_clear_voice_context"
    ),
    "confirm_pending_action": CommandDefinition(
        "confirm_pending_action", CommandRisk.LOCAL_WRITE, "_confirm_pending_action"
    ),
    "confirm_jira_create": CommandDefinition(
        "confirm_jira_create", CommandRisk.JIRA_WRITE, "_confirm_jira_create"
    ),
    "reject_pending_action": CommandDefinition(
        "reject_pending_action", CommandRisk.LOCAL_WRITE, "_reject_pending_action"
    ),
    "prepare_task": CommandDefinition("prepare_task", CommandRisk.JIRA_WRITE, None),
    "create_task": CommandDefinition("create_task", CommandRisk.JIRA_WRITE, None),
    "request_jira_create": CommandDefinition(
        "request_jira_create", CommandRisk.JIRA_WRITE, "_request_jira_create"
    ),
    "create_jira_issue": CommandDefinition("create_jira_issue", CommandRisk.JIRA_WRITE, None),
    "update_task": CommandDefinition("update_task", CommandRisk.JIRA_WRITE, None),
    "delete_task": CommandDefinition("delete_task", CommandRisk.JIRA_WRITE, None),
    "send_to_jira": CommandDefinition("send_to_jira", CommandRisk.JIRA_WRITE, None),
    "change_policy": CommandDefinition("change_policy", CommandRisk.FORBIDDEN, None),
    "run_command": CommandDefinition("run_command", CommandRisk.FORBIDDEN, None),
}


class VoicePermissionGate:
    """Deterministic allowlist. Voice can never alter the global execution policy."""

    enabled_risks = frozenset({CommandRisk.READ_ONLY, CommandRisk.LOCAL_WRITE})
    controlled_jira_commands = frozenset({"request_jira_create", "confirm_jira_create"})

    def __init__(self, execution_policy=None):
        self.execution_policy = execution_policy

    def allows(self, definition: CommandDefinition) -> bool:
        if definition.risk in self.enabled_risks:
            return True
        if definition.name not in self.controlled_jira_commands or self.execution_policy is None:
            return False
        violations = self.execution_policy.direct_create_gate_violations(
            space="AT",
            work_type="Task",
            tool_name="createJiraIssue",
            exact_active_account=True,
            assignee_in_atomic_create=True,
            second_confirmation=True,
        )
        return not violations


class VoiceCommandRouter:
    def __init__(
        self,
        repository,
        proposal_service,
        atlassian_manager,
        execution_policy,
        context_store: VoiceContextStore,
        jira_creation_service: VoiceJiraCreationService | None = None,
    ):
        self.repository = repository
        self.proposal_service = proposal_service
        self.atlassian_manager = atlassian_manager
        self.execution_policy = execution_policy
        self.context_store = context_store
        self.jira_creation_service = jira_creation_service
        self.gate = VoicePermissionGate(execution_policy)

    async def execute(
        self,
        intent: VoiceIntent,
        user: AuthenticatedUser,
        current_proposal_id: str | None,
        context: VoiceConversationContext,
    ) -> CommandOutcome:
        if current_proposal_id:
            context.active_proposal_id = current_proposal_id
        definition = COMMAND_REGISTRY.get(intent.intent)
        if definition is None:
            return CommandOutcome(
                status="needs_clarification",
                message=(
                    "No reconozco esa instrucción. Di ‘ayuda’ para conocer las consultas "
                    "y cambios de borrador local disponibles."
                ),
                context=context,
                risk=CommandRisk.READ_ONLY,
                persist_context=False,
            )
        context.last_intent = intent.intent
        if not self.gate.allows(definition):
            self.context_store.save(context)
            if definition.risk is CommandRisk.JIRA_WRITE:
                unsupported = definition.name not in self.gate.controlled_jira_commands
                return CommandOutcome(
                    status="blocked",
                    message=(
                        "Esa escritura Jira mediante voz no está soportada. El borrador no fue enviado."
                        if unsupported
                        else "La creación controlada por voz no está habilitada por la política local actual. "
                        "Vic no puede habilitar ni cambiar esa política."
                    ),
                    context=context,
                    risk=definition.risk,
                    draft=self._active_draft(context),
                    persist_context=False,
                )
            return CommandOutcome(
                status="blocked",
                message="Esa operación está prohibida para el asistente de voz.",
                context=context,
                risk=definition.risk,
                draft=self._active_draft(context),
                persist_context=False,
            )
        handler = getattr(self, definition.handler or "", None)
        if handler is None:
            return CommandOutcome(
                status="needs_clarification",
                message="La instrucción no tiene una operación habilitada.",
                context=context,
                risk=definition.risk,
                persist_context=False,
            )
        outcome = handler(intent, user, current_proposal_id, context, definition.risk)
        if inspect.isawaitable(outcome):
            outcome = await outcome
        if outcome.persist_context:
            self.context_store.save(outcome.context)
        return outcome

    @staticmethod
    def _active_draft(context: VoiceConversationContext) -> VoiceTaskDraft | None:
        if context.draft and context.draft.status == "draft" and context.active_draft_id:
            return context.draft
        return None

    @staticmethod
    def _argument(intent: VoiceIntent, name: str) -> str | None:
        value = intent.arguments.get(name)
        if not isinstance(value, str):
            return None
        value = value.strip()
        return value or None

    def _draft_or_outcome(
        self,
        context: VoiceConversationContext,
        risk: CommandRisk,
    ) -> tuple[VoiceTaskDraft | None, CommandOutcome | None]:
        draft = self._active_draft(context)
        if draft is not None:
            return draft, None
        return None, CommandOutcome(
            status="needs_clarification",
            message="No hay una tarea local en preparación. Primero pide crear una tarea.",
            context=context,
            risk=risk,
            persist_context=False,
        )

    def _invalidate_confirmation_for_draft_change(
        self,
        context: VoiceConversationContext,
    ) -> None:
        if self.jira_creation_service is not None:
            self.jira_creation_service.invalidate_pending(context)
        elif context.pending_confirmation:
            context.pending_confirmation = None

    def _proposal_space(self, proposal_id: str | None) -> str:
        if proposal_id:
            proposal = self.repository.get(proposal_id)
            space = ((proposal or {}).get("defaults") or {}).get("space")
            if space in {"AT", "ASIT", "MTTI"}:
                return space
        return "AT"

    def _help(self, _intent, _user, _proposal_id, context, risk) -> CommandOutcome:
        return CommandOutcome(
            status="completed",
            message=(
                "Puedo consultar la aplicación y Jira, preparar una tarea local, completar "
                "su responsable, prioridad, tipo, resumen y descripción, mostrarla o cancelarla. "
                "Cuando la política local lo permite, puedo prepararla y crear una Task en Jira "
                "sólo después de tu confirmación explícita."
            ),
            context=context,
            risk=risk,
            draft=self._active_draft(context),
        )

    def _unsupported_proposal_creation(
        self, _intent, _user, _proposal_id, context, risk
    ) -> CommandOutcome:
        return CommandOutcome(
            status="blocked",
            message=(
                "Entendí que quieres generar una nueva propuesta. Esa función todavía no está "
                "disponible por voz: usa Nuevo proyecto y carga la Plantilla Excel v1.1. "
                "No se hizo ningún cambio."
            ),
            context=context,
            risk=risk,
            draft=self._active_draft(context),
            persist_context=False,
        )

    def _get_app_status(self, _intent, _user, _proposal_id, context, risk) -> CommandOutcome:
        proposals = self.repository.list_latest_with_lifecycle()
        active = sum(1 for _proposal, lifecycle in proposals if not lifecycle["archived_at"])
        jira_mode = getattr(self.execution_policy, "mode", "READ_ONLY")
        return CommandOutcome(
            status="completed",
            message=(
                f"La aplicación local está disponible. Hay {active} propuesta(s) activa(s). "
                f"El modo general es {jira_mode}; la voz usa confirmación y ejecución controlada."
            ),
            context=context,
            risk=risk,
            draft=self._active_draft(context),
        )

    def _get_jira_status(self, _intent, user, _proposal_id, context, risk) -> CommandOutcome:
        status = self.atlassian_manager.status(user.username)
        if status.get("connected"):
            target = status.get("target_site") or "el sitio configurado"
            message = (
                f"Jira está conectada con {target}. La voz puede consultar, preparar y, "
                "con confirmación explícita, crear una Task de forma controlada."
            )
        else:
            message = f"Jira no está conectada. Estado actual: {status.get('phase', 'DISCONNECTED')}."
        return CommandOutcome(
            status="completed",
            message=message,
            context=context,
            risk=risk,
            draft=self._active_draft(context),
        )

    def _resolve_proposal(self, proposal_id: str | None) -> tuple[dict[str, Any] | None, str]:
        if proposal_id:
            proposal = self.repository.get(proposal_id)
            lifecycle = self.repository.get_lifecycle(proposal_id)
            return proposal, lifecycle.get("display_name") or ""
        for proposal, lifecycle in self.repository.list_latest_with_lifecycle():
            if not lifecycle["archived_at"]:
                return proposal, lifecycle.get("display_name") or ""
        return None, ""

    def _get_current_proposal_summary(
        self, _intent, _user, proposal_id, context, risk
    ) -> CommandOutcome:
        proposal, display_name = self._resolve_proposal(proposal_id)
        if proposal is None:
            return CommandOutcome(
                status="needs_clarification",
                message="No hay una propuesta activa para resumir.",
                context=context,
                risk=risk,
                persist_context=False,
            )
        summary = self.proposal_service.summarize(proposal, display_name=display_name or None)
        counts = summary["counts"]
        return CommandOutcome(
            status="completed",
            message=(
                f"{summary['display_name']}, versión {summary['version']}: "
                f"{counts['INCLUIR']} por incluir, {counts['REVISAR']} por revisar y "
                f"{counts['EXCLUIR']} excluido(s). Estado {summary['status']}."
            ),
            context=context,
            risk=risk,
            draft=self._active_draft(context),
        )

    def _list_validation_errors(
        self, _intent, _user, proposal_id, context, risk
    ) -> CommandOutcome:
        proposal, _display_name = self._resolve_proposal(proposal_id)
        if proposal is None:
            return CommandOutcome(
                status="needs_clarification",
                message="No hay una propuesta activa para revisar.",
                context=context,
                risk=risk,
                persist_context=False,
            )
        errors: list[str] = []
        warnings = 0
        for item in proposal["items"]:
            row_id = item["generated"]["row_id"]
            errors.extend(
                f"{row_id}: {message}" for message in item["validation"].get("errors", [])
            )
            warnings += len(item["validation"].get("warnings", []))
        if not errors:
            message = (
                f"La propuesta no tiene errores de validación. Hay {warnings} advertencia(s)."
            )
        else:
            preview = "; ".join(errors[:5])
            remainder = len(errors) - 5
            suffix = f"; y {remainder} más" if remainder > 0 else ""
            message = f"Hay {len(errors)} error(es): {preview}{suffix}."
        return CommandOutcome(
            status="completed",
            message=message,
            context=context,
            risk=risk,
            draft=self._active_draft(context),
        )

    def _list_pending_items(
        self, _intent, _user, proposal_id, context, risk
    ) -> CommandOutcome:
        proposal, _display_name = self._resolve_proposal(proposal_id)
        if proposal is None:
            return CommandOutcome(
                status="needs_clarification",
                message="No hay una propuesta activa para revisar.",
                context=context,
                risk=risk,
                persist_context=False,
            )
        pending = [
            item
            for item in proposal["items"]
            if item["generated"]["decision"] == "REVISAR"
            or item["validation"].get("pending_requirements")
        ]
        if not pending:
            message = "La propuesta no tiene elementos pendientes de revisión."
        else:
            names = [
                f"{item['generated']['row_id']}: {item['generated']['title']}"
                for item in pending[:5]
            ]
            remainder = len(pending) - 5
            suffix = f"; y {remainder} más" if remainder > 0 else ""
            message = f"Hay {len(pending)} pendiente(s): {'; '.join(names)}{suffix}."
        return CommandOutcome(
            status="completed",
            message=message,
            context=context,
            risk=risk,
            draft=self._active_draft(context),
        )

    def _prepare_local_task(self, intent, _user, proposal_id, context, risk) -> CommandOutcome:
        summary = self._argument(intent, "summary")
        if not summary:
            return CommandOutcome(
                status="needs_clarification",
                message="Indícame el resumen de la tarea que quieres preparar.",
                context=context,
                risk=risk,
                persist_context=False,
            )
        if len(summary) > 255:
            return CommandOutcome(
                status="needs_clarification",
                message="El resumen es demasiado largo. Redúcelo a 255 caracteres.",
                context=context,
                risk=risk,
                persist_context=False,
            )
        issue_type = self._argument(intent, "issue_type") or "Task"
        if issue_type not in {"Epic", "Story", "Task", "Bug", "Subtask"}:
            return CommandOutcome(
                status="needs_clarification",
                message="El tipo debe ser Epic, Story, Task, Bug o Subtask.",
                context=context,
                risk=risk,
                persist_context=False,
            )
        draft = VoiceTaskDraft(
            id=f"VOICE-DRAFT-{uuid4().hex[:12].upper()}",
            issue_type=issue_type,
            summary=summary,
            space=self._proposal_space(proposal_id),
        )
        context.draft = draft
        context.active_draft_id = draft.id
        context.pending_question = "assignee"
        context.pending_confirmation = None
        context.assignee_candidates = []
        return CommandOutcome(
            status="completed",
            message=(
                f"Preparé una {draft.issue_type} local para {draft.summary}. "
                "Todavía no se ha enviado nada a Jira. ¿A quién quieres asignarla?"
            ),
            context=context,
            risk=risk,
            draft=draft,
        )

    def _set_draft_summary(self, intent, _user, _proposal_id, context, risk) -> CommandOutcome:
        draft, error = self._draft_or_outcome(context, risk)
        if error:
            return error
        summary = self._argument(intent, "summary")
        if not summary:
            return CommandOutcome(
                status="needs_clarification",
                message="Indícame el nuevo resumen.",
                context=context,
                risk=risk,
                persist_context=False,
            )
        if len(summary) > 255:
            return CommandOutcome(
                status="needs_clarification",
                message="El resumen es demasiado largo. Redúcelo a 255 caracteres.",
                context=context,
                risk=risk,
                draft=draft,
                persist_context=False,
            )
        self._invalidate_confirmation_for_draft_change(context)
        draft.summary = summary
        return CommandOutcome(
            status="completed",
            message=f"Listo. Cambié el resumen a {summary}.",
            context=context,
            risk=risk,
            draft=draft,
        )

    def _set_draft_description(
        self, intent, _user, _proposal_id, context, risk
    ) -> CommandOutcome:
        draft, error = self._draft_or_outcome(context, risk)
        if error:
            return error
        description = self._argument(intent, "description")
        if not description:
            return CommandOutcome(
                status="needs_clarification",
                message="Indícame la nueva descripción.",
                context=context,
                risk=risk,
                persist_context=False,
            )
        self._invalidate_confirmation_for_draft_change(context)
        draft.description = description
        return CommandOutcome(
            status="completed",
            message="Listo. Actualicé la descripción del borrador local.",
            context=context,
            risk=risk,
            draft=draft,
        )

    async def _set_draft_assignee(
        self, intent, user, _proposal_id, context, risk
    ) -> CommandOutcome:
        draft, error = self._draft_or_outcome(context, risk)
        if error:
            return error
        query = self._argument(intent, "assignee")
        if not query:
            return CommandOutcome(
                status="needs_clarification",
                message="Indícame el nombre del responsable.",
                context=context,
                risk=risk,
                persist_context=False,
            )
        try:
            candidates = await self.atlassian_manager.find_assignees(
                user.username,
                draft.space,
                query,
            )
        except AtlassianIntegrationError:
            return CommandOutcome(
                status="needs_clarification",
                message=(
                    f"No pude identificar a {query} en Jira. Conecta Jira o proporciona "
                    "un nombre más preciso."
                ),
                context=context,
                risk=risk,
                draft=draft,
                persist_context=False,
            )
        usable = [
            item
            for item in candidates
            if item.get("active", True) and item.get("account_id") and item.get("display_name")
        ]
        if not usable:
            return CommandOutcome(
                status="needs_clarification",
                message=f"No pude identificar a {query} en Jira.",
                context=context,
                risk=risk,
                draft=draft,
                persist_context=False,
            )
        if len(usable) > 1:
            context.assignee_candidates = [
                VoiceDraftAssignee(
                    display_name=str(item["display_name"]),
                    account_id=str(item["account_id"]),
                    email=item.get("email"),
                )
                for item in usable[:5]
            ]
            context.pending_question = "assignee"
            names = ", ".join(item.display_name for item in context.assignee_candidates)
            return CommandOutcome(
                status="needs_clarification",
                message=f"Encontré más de un resultado para {query}: {names}. Necesito que selecciones cuál.",
                context=context,
                risk=risk,
                draft=draft,
            )
        selected = usable[0]
        self._invalidate_confirmation_for_draft_change(context)
        draft.assignee = VoiceDraftAssignee(
            display_name=str(selected["display_name"]),
            account_id=str(selected["account_id"]),
            email=selected.get("email"),
        )
        context.assignee_candidates = []
        context.pending_question = "priority"
        return CommandOutcome(
            status="completed",
            message=f"Listo. La asigné a {draft.assignee.display_name}. ¿Qué prioridad quieres?",
            context=context,
            risk=risk,
            draft=draft,
        )

    def _set_draft_priority(self, intent, _user, _proposal_id, context, risk) -> CommandOutcome:
        draft, error = self._draft_or_outcome(context, risk)
        if error:
            return error
        priority = self._argument(intent, "priority")
        allowed = {"Highest", "High", "Medium", "Low", "Lowest"}
        if priority not in allowed:
            return CommandOutcome(
                status="needs_clarification",
                message="La prioridad debe ser máxima, alta, media, baja o mínima.",
                context=context,
                risk=risk,
                draft=draft,
                persist_context=False,
            )
        self._invalidate_confirmation_for_draft_change(context)
        draft.priority = priority
        context.pending_question = "review"
        labels = {
            "Highest": "máxima",
            "High": "alta",
            "Medium": "media",
            "Low": "baja",
            "Lowest": "mínima",
        }
        return CommandOutcome(
            status="completed",
            message=f"Perfecto. La tarea quedó con prioridad {labels[priority]}. ¿Quieres revisarla?",
            context=context,
            risk=risk,
            draft=draft,
        )

    def _set_draft_issue_type(self, intent, _user, _proposal_id, context, risk) -> CommandOutcome:
        draft, error = self._draft_or_outcome(context, risk)
        if error:
            return error
        issue_type = self._argument(intent, "issue_type")
        if issue_type not in {"Epic", "Story", "Task", "Bug", "Subtask"}:
            return CommandOutcome(
                status="needs_clarification",
                message="El tipo debe ser Epic, Story, Task, Bug o Subtask.",
                context=context,
                risk=risk,
                draft=draft,
                persist_context=False,
            )
        self._invalidate_confirmation_for_draft_change(context)
        draft.issue_type = issue_type
        return CommandOutcome(
            status="completed",
            message=f"Listo. Cambié el tipo a {issue_type}.",
            context=context,
            risk=risk,
            draft=draft,
        )

    async def _request_jira_create(
        self,
        intent,
        user,
        proposal_id,
        context,
        risk,
    ) -> CommandOutcome:
        if self.jira_creation_service is None:
            return CommandOutcome(
                status="blocked",
                message="La integración controlada de voz con Jira no está disponible.",
                context=context,
                risk=risk,
                draft=self._active_draft(context),
                persist_context=False,
            )
        draft = self._active_draft(context)
        if draft is None:
            prepared = self._prepare_local_task(intent, user, proposal_id, context, risk)
            if prepared.draft is None:
                return prepared
            draft = prepared.draft

        summary = self._argument(intent, "summary")
        if summary and summary != draft.summary:
            changed = self._set_draft_summary(
                VoiceIntent(intent="set_draft_summary", arguments={"summary": summary}, confidence=1),
                user,
                proposal_id,
                context,
                CommandRisk.LOCAL_WRITE,
            )
            if changed.status != "completed":
                return changed
        description = self._argument(intent, "description")
        if description and description != draft.description:
            changed = self._set_draft_description(
                VoiceIntent(
                    intent="set_draft_description",
                    arguments={"description": description},
                    confidence=1,
                ),
                user,
                proposal_id,
                context,
                CommandRisk.LOCAL_WRITE,
            )
            if changed.status != "completed":
                return changed
        issue_type = self._argument(intent, "issue_type")
        if issue_type and issue_type != draft.issue_type:
            changed = self._set_draft_issue_type(
                VoiceIntent(
                    intent="set_draft_issue_type",
                    arguments={"issue_type": issue_type},
                    confidence=1,
                ),
                user,
                proposal_id,
                context,
                CommandRisk.LOCAL_WRITE,
            )
            if changed.status != "completed":
                return changed
        assignee = self._argument(intent, "assignee")
        if assignee:
            changed = await self._set_draft_assignee(
                VoiceIntent(
                    intent="set_draft_assignee",
                    arguments={"assignee": assignee},
                    confidence=1,
                ),
                user,
                proposal_id,
                context,
                CommandRisk.LOCAL_WRITE,
            )
            if changed.status != "completed":
                return changed
        priority = self._argument(intent, "priority")
        if priority and priority != draft.priority:
            changed = self._set_draft_priority(
                VoiceIntent(
                    intent="set_draft_priority",
                    arguments={"priority": priority},
                    confidence=1,
                ),
                user,
                proposal_id,
                context,
                CommandRisk.LOCAL_WRITE,
            )
            if changed.status != "completed":
                return changed

        try:
            operation, pending = await self.jira_creation_service.prepare(draft, user, context)
        except VoiceJiraValidationError as exc:
            return CommandOutcome(
                status="validation_error",
                message=str(exc),
                context=context,
                risk=risk,
                draft=draft,
            )
        context.pending_confirmation = pending
        context.pending_question = None
        labels = {
            "Highest": "Máxima",
            "High": "Alta",
            "Medium": "Media",
            "Low": "Baja",
            "Lowest": "Mínima",
        }
        preview = operation.preview
        details = [
            f"Tipo: {preview.issue_type}.",
            f"Resumen: {preview.summary}.",
            f"Responsable: {preview.assignee or 'Sin asignar'}.",
        ]
        if preview.priority:
            details.append(f"Prioridad: {labels.get(preview.priority, preview.priority)}.")
        return CommandOutcome(
            status="awaiting_confirmation",
            message=(
                "La tarea está lista para crear en Jira. "
                + " ".join(details)
                + " ¿Confirmas que la cree?"
            ),
            context=context,
            risk=risk,
            draft=draft,
            requires_confirmation=True,
            jira_operation=operation,
        )

    async def _confirm_jira_create(
        self,
        _intent,
        user,
        _proposal_id,
        context,
        risk,
    ) -> CommandOutcome:
        pending = context.pending_confirmation
        if not isinstance(pending, VoicePendingConfirmation) or pending.action != "create_jira_issue":
            return CommandOutcome(
                status="needs_clarification",
                message="No hay una creación Jira pendiente. Un ‘sí’ aislado no ejecuta cambios.",
                context=context,
                risk=risk,
                draft=self._active_draft(context),
                persist_context=False,
            )
        if self.jira_creation_service is None or not pending.payload_hash:
            return CommandOutcome(
                status="execution_error",
                message="La ejecución controlada no está disponible.",
                context=context,
                risk=risk,
                draft=self._active_draft(context),
                persist_context=False,
            )
        return await self.confirm_jira(
            user,
            context,
            pending.confirmation_id,
            pending.payload_hash,
        )

    async def confirm_jira(
        self,
        user: AuthenticatedUser,
        context: VoiceConversationContext,
        confirmation_id: str,
        payload_hash: str,
    ) -> CommandOutcome:
        try:
            operation = await self.jira_creation_service.confirm_and_execute(
                user,
                context,
                confirmation_id,
                payload_hash,
            )
        except VoiceJiraConfirmationError as exc:
            return CommandOutcome(
                status="validation_error",
                message=str(exc),
                context=context,
                risk=CommandRisk.JIRA_WRITE,
                draft=self._active_draft(context),
            )
        if operation.state == "SUCCESS":
            message = f"Listo. La tarea {operation.issue_key} fue creada y verificada correctamente."
            status = "completed"
        elif operation.state == "UNKNOWN_RESULT":
            message = (
                "No pude verificar el resultado. No volveré a enviarlo automáticamente "
                "para evitar un duplicado."
            )
            status = "unknown_result"
        elif operation.state == "CANCELLED":
            message = "Cancelé la creación. No se hizo ningún cambio en Jira."
            status = "cancelled"
        else:
            message = "Jira rechazó la creación. No se realizó un reintento automático."
            status = "execution_error"
        return CommandOutcome(
            status=status,
            message=message,
            context=context,
            risk=CommandRisk.JIRA_WRITE,
            draft=self._active_draft(context),
            jira_operation=operation,
        )

    def cancel_jira(
        self,
        user: AuthenticatedUser,
        context: VoiceConversationContext,
        confirmation_id: str,
        payload_hash: str,
    ) -> CommandOutcome:
        if self.jira_creation_service is None:
            return CommandOutcome(
                status="execution_error",
                message="La ejecución controlada no está disponible.",
                context=context,
                risk=CommandRisk.JIRA_WRITE,
                persist_context=False,
            )
        try:
            operation = self.jira_creation_service.cancel_pending(
                user,
                context,
                confirmation_id,
                payload_hash,
            )
        except VoiceJiraConfirmationError as exc:
            return CommandOutcome(
                status="needs_clarification",
                message=str(exc),
                context=context,
                risk=CommandRisk.JIRA_WRITE,
                draft=self._active_draft(context),
                persist_context=False,
            )
        unknown = operation.state == "UNKNOWN_RESULT"
        return CommandOutcome(
            status="unknown_result" if unknown else "cancelled",
            message=(
                "La solicitud ya había comenzado. No la reenviaré; el resultado requiere verificación."
                if unknown
                else "Cancelé la creación. No se hizo ningún cambio en Jira."
            ),
            context=context,
            risk=CommandRisk.JIRA_WRITE,
            draft=self._active_draft(context),
            jira_operation=operation,
        )

    def _show_current_draft(self, _intent, _user, _proposal_id, context, risk) -> CommandOutcome:
        draft, error = self._draft_or_outcome(context, risk)
        if error:
            return error
        context.pending_question = None
        return CommandOutcome(
            status="completed",
            message=(
                f"Te muestro la {draft.issue_type} preparada. Todavía no se ha enviado nada a Jira."
            ),
            context=context,
            risk=risk,
            draft=draft,
        )

    def _cancel_current_draft(self, _intent, _user, _proposal_id, context, risk) -> CommandOutcome:
        draft, error = self._draft_or_outcome(context, risk)
        if error:
            return error
        if self.jira_creation_service is not None:
            self.jira_creation_service.invalidate_pending(context, "DRAFT_CANCEL_REQUESTED")
        now = datetime.now(UTC)
        context.pending_confirmation = VoicePendingConfirmation(
            action="cancel_current_draft",
            confirmation_id=f"VCANCEL-{uuid4().hex[:20].upper()}",
            draft_id=draft.id,
            created_at=now.isoformat(),
            expires_at=(now + timedelta(minutes=10)).isoformat(),
        )
        context.pending_question = None
        return CommandOutcome(
            status="awaiting_confirmation",
            message=f"¿Quieres descartar la {draft.issue_type} local ‘{draft.summary}’?",
            context=context,
            risk=risk,
            draft=draft,
            requires_confirmation=True,
        )

    def _confirm_pending_action(
        self, _intent, _user, _proposal_id, context, risk
    ) -> CommandOutcome:
        pending = context.pending_confirmation
        if not isinstance(pending, VoicePendingConfirmation) or pending.action != "cancel_current_draft":
            return CommandOutcome(
                status="needs_clarification",
                message="No hay una confirmación pendiente. Un ‘sí’ aislado no ejecuta cambios.",
                context=context,
                risk=risk,
                draft=self._active_draft(context),
                persist_context=False,
            )
        draft = self._active_draft(context)
        if draft is None or draft.id != pending.draft_id:
            context.pending_confirmation = None
            return CommandOutcome(
                status="needs_clarification",
                message="La tarea local ya no está activa.",
                context=context,
                risk=risk,
            )
        draft.status = "cancelled"
        context.active_draft_id = None
        context.pending_confirmation = None
        context.pending_question = None
        context.assignee_candidates = []
        return CommandOutcome(
            status="cancelled",
            message="Listo. Descarté la tarea local. No se realizó ningún cambio en Jira.",
            context=context,
            risk=risk,
            draft=draft,
        )

    def _reject_pending_action(self, _intent, _user, _proposal_id, context, risk) -> CommandOutcome:
        pending = context.pending_confirmation
        if isinstance(pending, VoicePendingConfirmation) and pending.action == "create_jira_issue":
            if self.jira_creation_service is None or not pending.payload_hash:
                return CommandOutcome(
                    status="execution_error",
                    message="La creación pendiente no tiene un mecanismo seguro disponible.",
                    context=context,
                    risk=CommandRisk.JIRA_WRITE,
                    draft=self._active_draft(context),
                    persist_context=False,
                )
            try:
                operation = self.jira_creation_service.cancel_pending(
                    _user,
                    context,
                    pending.confirmation_id,
                    pending.payload_hash,
                )
            except VoiceJiraConfirmationError as exc:
                return CommandOutcome(
                    status="needs_clarification",
                    message=str(exc),
                    context=context,
                    risk=CommandRisk.JIRA_WRITE,
                    draft=self._active_draft(context),
                    persist_context=False,
                )
            return CommandOutcome(
                status="cancelled" if operation.state == "CANCELLED" else "unknown_result",
                message=(
                    "Cancelé la creación. No se hizo ningún cambio en Jira."
                    if operation.state == "CANCELLED"
                    else "La solicitud ya había comenzado y no se reenviará. El resultado requiere verificación."
                ),
                context=context,
                risk=CommandRisk.JIRA_WRITE,
                draft=self._active_draft(context),
                jira_operation=operation,
            )
        if pending:
            context.pending_confirmation = None
            message = "De acuerdo. Conservé la tarea local."
        elif context.pending_question:
            context.pending_question = None
            message = "De acuerdo. Dejé la tarea local como está."
        else:
            return CommandOutcome(
                status="needs_clarification",
                message="No hay una pregunta pendiente que rechazar.",
                context=context,
                risk=risk,
                draft=self._active_draft(context),
                persist_context=False,
            )
        return CommandOutcome(
            status="completed",
            message=message,
            context=context,
            risk=risk,
            draft=self._active_draft(context),
        )

    def _clear_voice_context(self, _intent, user, _proposal_id, _context, risk) -> CommandOutcome:
        if self.jira_creation_service is not None:
            self.jira_creation_service.invalidate_pending(_context, "CONTEXT_CLEARED")
        self.context_store.clear(user)
        context = self.context_store.get(user)
        return CommandOutcome(
            status="completed",
            message="Listo. Olvidé el contexto de voz de esta sesión.",
            context=context,
            risk=risk,
            persist_context=False,
        )
