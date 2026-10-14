from __future__ import annotations

import json
import copy
import logging
import hashlib
import secrets
import subprocess
import tempfile
import re
import webbrowser
import sys
from datetime import UTC, datetime, timedelta
from time import perf_counter
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from .atlassian import AtlassianIntegrationError, AtlassianIntegrationManager, work_type_matches
from .catalog import normalize_name
from .auth import (
    AuthenticatedUser,
    AuthProvider,
    FederatedAuthProvider,
    SESSION_COOKIE,
    get_auth_provider,
    require_user,
)
from .config import CURRENT_TEMPLATE_VERSION, Settings, get_settings
from .controlled_jira import ControlledJiraCreateCore
from .corrections import build_correction_workflow
from .dry_run import JiraDryRunService
from .dashboard import DashboardDataError, DashboardDataService
from .errors import ProposalStateError, WorkbookValidationError
from .execution_policy import load_execution_policy
from .models import (
    BulkProposalUpdate,
    ItemUpdate,
    JiraAssigneeSelectionRequest,
    JiraBatchConfirmRequest,
    JiraBatchPrepareRequest,
    JiraRealConfirmRequest,
    JiraSimulationConfirmRequest,
    JiraSimulationPrepareRequest,
    LoginRequest,
    PlanDefaults,
    ProposalDefaultsUpdate,
    ProposalExclusionRequest,
    ProposalMetadataUpdate,
    ReactivationRequest,
)
from .objective_4a import (
    JiraExecutionPreparationService,
    Objective4AError,
    SimulatedJiraCreateGateway,
)
from .objective_4b import JiraControlledExecutionService, Objective4BError
from .objective_4c1 import JiraControlledBatchService, Objective4C1Error
from .repository import ProposalRepository
from .schema import ProposalSchemaValidator
from .service import ProposalService, utc_now
from .minutes import MinutesService, MinutesRequest, MinutesError
from .minute_drafts import MinuteDraftError, MinuteDraftService
from .voice.commands import VoiceCommandRouter
from .voice.context import VoiceContextStore
from .voice.errors import VoiceInputError, VoiceTimeoutError, VoiceUnavailableError
from .voice.jira import VoiceJiraCreationService
from .voice.models import (
    VoiceCommandResponse,
    VoiceContextView,
    VoiceJiraCancelRequest,
    VoiceJiraConfirmRequest,
    VoiceStatusResponse,
)
from .voice.service import VoiceCommandService
from .jira_write_lock import GlobalJiraWriteLock, GlobalJiraWriteLockError
from .performance import PerformanceRegistry, PerformanceTrace, log_summary, reset_trace, set_trace

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
logger = logging.getLogger(__name__)
VOICE_AUDIO_TYPES = frozenset(
    {
        "audio/webm",
        "audio/ogg",
        "audio/mp4",
        "audio/mpeg",
        "audio/wav",
        "audio/x-wav",
    }
)


def create_app(
    settings: Settings | None = None,
    atlassian_manager: AtlassianIntegrationManager | None = None,
    voice_service: VoiceCommandService | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    repository = ProposalRepository(settings.database_path)
    federated_auth_provider = FederatedAuthProvider(settings, repository)
    service = ProposalService(
        repository=repository,
        validator=ProposalSchemaValidator(settings.schema_path),
    )

    app = FastAPI(
        title="Agente Jira - MVP local",
        version="0.22.0",
        description=(
            "Genera propuestas Jira revisables desde las Plantillas Excel v1.1 a v1.3. "
            "Consulta metadatos Jira mediante OAuth 2.1 y Rovo MCP. La escritura "
            "permanece deshabilitada por defecto. Los modos explícitos 4B a 4E "
            "permiten lotes de hasta cinco actividades en AT, incluyendo Epic, "
            "Subtask y relaciones padre-hijo verificadas mediante lectura posterior."
        ),
    )
    app.state.settings = settings
    # Bind authentication to the app's settings so tests and local instances do
    # not silently share the module-level provider or its environment.
    app.dependency_overrides[get_auth_provider] = lambda: federated_auth_provider
    app.state.auth_provider = federated_auth_provider
    app.state.repository = repository
    app.state.proposal_service = service
    app.state.minutes_service = MinutesService(settings, service)
    app.state.minute_drafts = MinuteDraftService(
        settings.database_path,
        service,
        Path(__file__).resolve().parents[2] / "releases" / "plantilla_excel_v1_3" / "plantilla_plan_trabajo_jira_v1_3.xlsx",
    )
    app.state.jira_write_lock = GlobalJiraWriteLock(settings.jira_write_lock_ttl_seconds)
    app.state.performance_registry = PerformanceRegistry()
    app.state.atlassian_manager = atlassian_manager or AtlassianIntegrationManager(
        settings,
        write_lock=app.state.jira_write_lock,
    )

    def assert_global_write_available(username: str) -> None:
        app.state.jira_write_lock.ensure_unlocked(username)
    app.state.jira_execution_policy = load_execution_policy(
        settings.jira_execution_policy_path,
        settings.jira_execution_policy_schema_path,
    )
    app.state.dry_run_service = JiraDryRunService(
        repository,
        app.state.atlassian_manager,
        read_concurrency=settings.jira_read_concurrency,
    )
    app.state.dashboard_service = DashboardDataService(
        app.state.atlassian_manager,
        settings.database_path.parent / "dashboard_snapshots",
        jira_write_enabled=app.state.jira_execution_policy.jira_write_enabled,
        write_lock=app.state.jira_write_lock,
    )
    app.state.jira_simulator = SimulatedJiraCreateGateway()
    app.state.objective_4a_service = JiraExecutionPreparationService(
        repository,
        app.state.jira_execution_policy,
        app.state.jira_simulator,
    )
    app.state.controlled_jira_create_core = ControlledJiraCreateCore(
        app.state.atlassian_manager
    )
    app.state.objective_4b_service = JiraControlledExecutionService(
        repository,
        app.state.jira_execution_policy,
        app.state.atlassian_manager,
        create_core=app.state.controlled_jira_create_core,
    )
    app.state.objective_4c1_service = JiraControlledBatchService(
        repository,
        app.state.jira_execution_policy,
        app.state.atlassian_manager,
        create_core=app.state.controlled_jira_create_core,
    )
    app.state.voice_context_store = VoiceContextStore(
        settings.database_path,
        settings.voice_context_ttl_seconds,
    )
    app.state.voice_jira_creation_service = VoiceJiraCreationService(
        repository,
        app.state.jira_execution_policy,
        app.state.atlassian_manager,
        app.state.controlled_jira_create_core,
        settings,
    )
    app.state.voice_service = voice_service or VoiceCommandService(
        settings,
        VoiceCommandRouter(
            repository,
            service,
            app.state.atlassian_manager,
            app.state.jira_execution_policy,
            app.state.voice_context_store,
            app.state.voice_jira_creation_service,
        ),
        context_store=app.state.voice_context_store,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def performance_middleware(request: Request, call_next):
        trace = PerformanceTrace(operation=f"{request.method} {request.url.path}")
        token = set_trace(trace)
        response = None
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            trace.record_phase("http_request", (perf_counter() - trace.started_at) * 1000)
            summary = trace.summary(status_code=status_code)
            app.state.performance_registry.add(summary)
            log_summary(summary)
            if response is not None:
                response.headers["X-Request-ID"] = trace.request_id
                response.headers["Server-Timing"] = f"app;dur={summary['duration_ms']}"
            reset_trace(token)

    @app.exception_handler(WorkbookValidationError)
    async def workbook_error_handler(_request, exc: WorkbookValidationError):
        return JSONResponse(
            status_code=422,
            content={
                "detail": exc.message,
                "issues": [issue.as_dict() for issue in exc.issues],
            },
        )

    @app.exception_handler(MinutesError)
    async def minutes_error_handler(_request, exc: MinutesError):
        content = {"detail": str(exc), "code": exc.code, "retryable": exc.retryable}
        if exc.ollama_status is not None:
            content["ollama_status"] = exc.ollama_status
        return JSONResponse(status_code=exc.status_code, content=content)

    @app.exception_handler(MinuteDraftError)
    async def minute_draft_error_handler(_request, exc: MinuteDraftError):
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc), "code": exc.code})

    async def refresh_minute_tracking_catalog(draft_id: str, username: str) -> dict:
        draft = app.state.minute_drafts.get(draft_id, username)
        space = str(draft.get("jira_space_key") or "AT").upper()
        manager = app.state.atlassian_manager
        area_options: list[dict[str, str]] = []
        try:
            restore = getattr(manager, "ensure_restored", None)
            if restore is not None:
                await restore(username)
            try:
                snapshot = manager.connected_snapshot(username)
            except AtlassianIntegrationError:
                snapshot = {}
            area_options = [
                {
                    "key": str(project.get("key") or ""),
                    "value": str(project.get("name") or project.get("key") or ""),
                    "label": " · ".join(part for part in (
                        str(project.get("key") or ""),
                        str(project.get("name") or ""),
                    ) if part),
                }
                for project in snapshot.get("spaces", [])
                if project.get("key") or project.get("name")
            ]
            catalog = manager.jira_field_catalog(username, space, "Task", "customfield_10147")
            catalog_status = "READY" if catalog.get("options") else "UNAVAILABLE"
            result = app.state.minute_drafts.set_tracking_catalog(
                draft_id, username, options=catalog.get("options", []), status=catalog_status,
                field_id=catalog.get("field_id"),
            )
            return {"state": result.get("catalog_status", catalog_status), "space": space, "work_type": "Task",
                    "field_id": catalog.get("field_id"), "field_name": catalog.get("field_name"),
                    "options": result.get("tracking_options", []), "area_options": area_options, "draft": result}
        except Exception:
            result = app.state.minute_drafts.set_tracking_catalog(
                draft_id, username, options=[], status="UNAVAILABLE", field_id="customfield_10147",
            )
            return {"state": result.get("catalog_status", "UNAVAILABLE"), "space": space, "work_type": "Task",
                    "field_id": "customfield_10147", "options": result.get("tracking_options", []),
                    "area_options": area_options,
                    "draft": result}

    @app.get("/api/minutes/status")
    async def minutes_status(_user: AuthenticatedUser = Depends(require_user)):
        return await app.state.minutes_service.status()

    @app.post("/api/minutes/analyze")
    async def minutes_analyze(payload: MinutesRequest, user: AuthenticatedUser = Depends(require_user)):
        if payload.output == "draft":
            started = perf_counter()
            draft = app.state.minute_drafts.create(payload.text, user.username,
                                                   enrichment_enabled=settings.minutes_ai_enabled)
            first_ms = round((perf_counter() - started) * 1000, 1)
            if draft["enrichment"]["state"] == "PENDING":
                import asyncio
                asyncio.create_task(app.state.minutes_service.enrich_draft(draft, app.state.minute_drafts))
            return {"draft_id": draft["draft_id"], "draft": draft,
                    "time_to_first_proposal_ms": None, "time_to_first_draft_ms": first_ms}
        return await app.state.minutes_service.analyze(payload.text, user.username)

    @app.get("/api/minutes/drafts/latest")
    def latest_minute_draft(user: AuthenticatedUser = Depends(require_user)):
        draft = app.state.minute_drafts.latest(user.username)
        if draft is None:
            raise HTTPException(status_code=404, detail="No hay un borrador de minuta guardado.")
        return draft

    @app.get("/api/minutes/drafts/{draft_id}")
    def get_minute_draft(draft_id: str, user: AuthenticatedUser = Depends(require_user)):
        return app.state.minute_drafts.get(draft_id, user.username)

    @app.get("/api/minutes/drafts/{draft_id}/catalog")
    async def minute_draft_tracking_catalog(draft_id: str, user: AuthenticatedUser = Depends(require_user)):
        return await refresh_minute_tracking_catalog(draft_id, user.username)

    @app.get("/api/admin/responsible-area-map/{account_id}")
    def get_responsible_area_map(account_id: str, user: AuthenticatedUser = Depends(require_user)):
        if user.role != "ADMIN":
            raise HTTPException(status_code=403, detail="Sólo un administrador puede consultar el catálogo de áreas.")
        return {"account_id": account_id, "areas": app.state.minute_drafts.area_mappings.areas_for(account_id)}

    @app.put("/api/admin/responsible-area-map/{account_id}")
    def replace_responsible_area_map(account_id: str, payload: dict, user: AuthenticatedUser = Depends(require_user)):
        if user.role != "ADMIN":
            raise HTTPException(status_code=403, detail="Sólo un administrador puede modificar el catálogo de áreas.")
        areas = payload.get("areas")
        if not isinstance(areas, list) or any(not isinstance(item, dict) for item in areas):
            raise HTTPException(status_code=422, detail="areas debe ser una lista de áreas locales válidas.")
        app.state.minute_drafts.replace_responsible_areas(account_id, areas)
        return {"account_id": account_id, "areas": app.state.minute_drafts.area_mappings.areas_for(account_id)}

    @app.patch("/api/minutes/drafts/{draft_id}/rows/{candidate_id}")
    async def update_minute_draft_row(draft_id: str, candidate_id: str, payload: dict,
                                      user: AuthenticatedUser = Depends(require_user)):
        expected_version = int(payload.get("expected_version", 0))
        changes = dict(payload.get("changes") or {})
        account_id = changes.get("responsable_account_id")
        lookup_query = str(changes.pop("responsable_lookup_query", "") or "").strip()
        if account_id:
            draft = app.state.minute_drafts.get(draft_id, user.username)
            space = str(draft.get("jira_space_key") or "AT").upper()
            query = lookup_query or str(changes.get("responsable") or "").strip()
            if len(query) < 2:
                raise MinuteDraftError("Selecciona el responsable desde los resultados Jira.", 422, "ASSIGNEE_NOT_VERIFIED")
            try:
                candidates = await app.state.atlassian_manager.find_assignees(user.username, space, query)
            except AtlassianIntegrationError as exc:
                raise MinuteDraftError("No fue posible verificar el responsable con Jira.", 409, "ASSIGNEE_LOOKUP_UNAVAILABLE") from exc
            selected = next((item for item in candidates if item.get("account_id") == account_id and item.get("active", True)), None)
            if selected is None:
                raise MinuteDraftError("El responsable seleccionado ya no está disponible en Jira.", 422, "ASSIGNEE_NOT_VERIFIED")
            changes["responsable"] = selected.get("display_name") or query
        updated = app.state.minute_drafts.update_row(draft_id, candidate_id, user.username, expected_version, changes)
        # Areas are local metadata resolved only after Jira has verified the
        # selected account. This never writes to Jira or treats a Space as area.
        if "responsable" in changes or "responsable_account_id" in changes:
            return app.state.minute_drafts.apply_responsible_area_resolution(
                draft_id, candidate_id, user.username, updated["version"],
            )
        return updated

    @app.patch("/api/minutes/drafts/{draft_id}/project-responsible")
    async def update_minute_project_responsible(draft_id: str, payload: dict,
                                                user: AuthenticatedUser = Depends(require_user)):
        """Verify only a document-level owner; this never changes task rows or Jira."""
        expected_version = int(payload.get("expected_version", 0))
        changes = dict(payload.get("changes") or {})
        account_id = changes.get("project_responsible_account_id")
        lookup_query = str(changes.pop("project_responsible_lookup_query", "") or "").strip()
        if account_id:
            draft = app.state.minute_drafts.get(draft_id, user.username)
            space = str(draft.get("jira_space_key") or "AT").upper()
            document = draft.get("document") or {}
            query = lookup_query or str(changes.get("project_responsible") or document.get("project_responsible") or "").strip()
            if len(query) < 2:
                raise MinuteDraftError("Selecciona el responsable del proyecto desde los resultados Jira.", 422, "ASSIGNEE_NOT_VERIFIED")
            try:
                candidates = await app.state.atlassian_manager.find_assignees(user.username, space, query)
            except AtlassianIntegrationError as exc:
                raise MinuteDraftError("No fue posible verificar el responsable del proyecto con Jira.", 409, "ASSIGNEE_LOOKUP_UNAVAILABLE") from exc
            selected = next((item for item in candidates if item.get("account_id") == account_id and item.get("active", True)), None)
            if selected is None:
                raise MinuteDraftError("El responsable del proyecto seleccionado ya no está disponible en Jira.", 422, "ASSIGNEE_NOT_VERIFIED")
            changes["project_responsible"] = selected.get("display_name") or query
        return app.state.minute_drafts.update_project_responsible(
            draft_id, user.username, expected_version, changes,
        )

    @app.post("/api/minutes/drafts/{draft_id}/rows")
    def add_minute_draft_row(draft_id: str, payload: dict, user: AuthenticatedUser = Depends(require_user)):
        return app.state.minute_drafts.add_row(draft_id, user.username, int(payload.get("expected_version", 0)))

    @app.delete("/api/minutes/drafts/{draft_id}/rows/{candidate_id}")
    def delete_minute_draft_row(draft_id: str, candidate_id: str, expected_version: int = Query(...),
                                user: AuthenticatedUser = Depends(require_user)):
        return app.state.minute_drafts.delete_row(draft_id, candidate_id, user.username, expected_version)

    @app.post("/api/minutes/drafts/{draft_id}/validate")
    async def validate_minute_draft(draft_id: str, user: AuthenticatedUser = Depends(require_user)):
        await refresh_minute_tracking_catalog(draft_id, user.username)
        return app.state.minute_drafts.validate(draft_id, user.username)

    @app.get("/api/minutes/drafts/{draft_id}/xlsx")
    def download_minute_draft(draft_id: str, user: AuthenticatedUser = Depends(require_user)):
        content = app.state.minute_drafts.export_xlsx(draft_id, user.username)
        filename = f"plan_trabajo_jira_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
        return Response(content=content,
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="{filename}"'})

    @app.post("/api/minutes/drafts/{draft_id}/proposal")
    async def proposal_from_minute_draft(draft_id: str, payload: dict | None = None,
                                         user: AuthenticatedUser = Depends(require_user)):
        await refresh_minute_tracking_catalog(draft_id, user.username)
        candidate_ids = payload.get("candidate_ids") if payload else None
        return app.state.minute_drafts.to_proposal(draft_id, user.username, candidate_ids)

    @app.get("/api/proposals/{proposal_id}/enrichment")
    def get_minutes_enrichment(
        proposal_id: str,
        _user: AuthenticatedUser = Depends(require_user),
    ):
        proposal = repository.get(proposal_id)
        if proposal is None:
            raise HTTPException(status_code=404, detail="Propuesta no encontrada.")
        if not proposal.get("minutes"):
            raise HTTPException(status_code=404, detail="La propuesta no proviene de una minuta.")
        enrichment = repository.get_minutes_enrichment(proposal_id)
        if enrichment is None:
            return {"proposal_id": proposal_id, "state": "NONE", "suggestions": []}
        if proposal.get("version") != enrichment.get("base_version") and enrichment.get("state") not in {"STALE"}:
            enrichment = {**enrichment, "state": "STALE",
                           "message": "La Proposal cambió mientras la IA trabajaba; las sugerencias no se aplicaron."}
        return enrichment

    @app.exception_handler(ProposalStateError)
    async def proposal_state_error_handler(_request, exc: ProposalStateError):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(Objective4AError)
    async def objective_4a_error_handler(_request, exc: Objective4AError):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(Objective4BError)
    async def objective_4b_error_handler(_request, exc: Objective4BError):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(Objective4C1Error)
    async def objective_4c1_error_handler(_request, exc: Objective4C1Error):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(GlobalJiraWriteLockError)
    async def global_jira_write_lock_error_handler(_request, exc: GlobalJiraWriteLockError):
        return JSONResponse(
            status_code=409,
            content={"detail": str(exc), "code": exc.code, "state": exc.state},
        )

    @app.get("/api/health")
    def health() -> dict[str, object]:
        return {
            "status": "ok",
            "mode": "local",
            "external_connections": True,
            "atlassian_mcp_mode": (
                "controlled_hierarchy_batch"
                if app.state.jira_execution_policy.mode == "CONTROLLED_HIERARCHY_BATCH"
                else "controlled_multi_type_batch"
                if app.state.jira_execution_policy.mode == "CONTROLLED_MULTI_TYPE_BATCH"
                else "controlled_batch"
                if app.state.jira_execution_policy.mode == "CONTROLLED_BATCH"
                else "single_controlled_task"
                if app.state.jira_execution_policy.mode == "SINGLE_CANARY"
                else "read_only"
            ),
            "jira_write_enabled": app.state.jira_execution_policy.jira_write_enabled,
            # Kept for backwards-compatible health consumers.  Report the
            # active execution mode truthfully instead of advertising the
            # retired local-only 4A simulator while real batch creation is on.
            "objective_4a_mode": app.state.jira_execution_policy.mode.casefold(),
            "template_version": CURRENT_TEMPLATE_VERSION,
        }

    @app.get("/api/objectives/4/readiness")
    async def objective_4_readiness(
        user: AuthenticatedUser = Depends(require_user),
    ) -> dict[str, object]:
        restore = getattr(app.state.atlassian_manager, "ensure_restored", None)
        if restore is not None:
            await restore(user.username)
        policy = app.state.jira_execution_policy
        inspect_tools = getattr(
            app.state.atlassian_manager,
            "objective_4_tool_readiness",
            None,
        )
        tools = (
            inspect_tools(user.username)
            if inspect_tools is not None
            else {
                "connected": False,
                "inspection_only": True,
                "tools_invoked": 0,
                "create": {"name": "createJiraIssue", "exposed": False, "input_schema": None},
                "readback": {"name": "getJiraIssue", "exposed": False, "input_schema": None},
            }
        )
        simulation_violations = policy.simulation_readiness()
        integration = app.state.atlassian_manager.status(user.username)
        snapshot = integration.get("snapshot") or {}
        at_space = next(
            (space for space in snapshot.get("spaces", []) if space.get("key") == "AT"),
            None,
        )
        task = next(
            (
                work_type
                for work_type in (at_space or {}).get("work_types", [])
                if str(work_type.get("name") or "").lower() in {"task", "tarea"}
            ),
            None,
        )
        real_canary_checks = {
            "atlassian_connected": bool(integration.get("connected")),
            "create_tool_exposed": bool(tools["create"]["exposed"]),
            "readback_tool_exposed": bool(tools["readback"]["exposed"]),
            "at_visible": bool(at_space and at_space.get("found")),
            "task_metadata_available": bool(task and task.get("fields")),
        }
        real_policy_active = (
            policy.mode == "SINGLE_CANARY"
            and policy.jira_write_enabled
            and not policy.document["automatic_retry"]
        )
        batch_policy_active = (
            policy.mode in {"CONTROLLED_BATCH", "CONTROLLED_MULTI_TYPE_BATCH", "CONTROLLED_HIERARCHY_BATCH"}
            and policy.jira_write_enabled
            and not policy.document["automatic_retry"]
            and int(policy.document["max_items_per_execution"]) <= 5
        )
        real_ready = all(real_canary_checks.values()) and real_policy_active
        batch_ready = all(real_canary_checks.values()) and batch_policy_active
        allowed_type_contracts = {
            name: next(
                (
                    work_type
                    for work_type in (at_space or {}).get("work_types", [])
                    if work_type_matches(name, work_type)
                ),
                None,
            )
            for name in policy.document["allowed_work_types"]
        }
        all_allowed_types_ready = all(
            contract and contract.get("fields")
            for contract in allowed_type_contracts.values()
        )
        if policy.mode in {"CONTROLLED_MULTI_TYPE_BATCH", "CONTROLLED_HIERARCHY_BATCH"}:
            real_canary_checks["all_allowed_work_types_available"] = bool(all_allowed_types_ready)
            batch_ready = all(real_canary_checks.values()) and batch_policy_active
        return {
            "objective": (
                "4E"
                if policy.mode == "CONTROLLED_HIERARCHY_BATCH"
                else "4D"
                if policy.mode == "CONTROLLED_MULTI_TYPE_BATCH"
                else "4C.1"
                if batch_policy_active
                else "4A"
            ),
            "status": (
                "READY_FOR_CONTROLLED_HIERARCHY_BATCH"
                if batch_ready and policy.mode == "CONTROLLED_HIERARCHY_BATCH"
                else "READY_FOR_CONTROLLED_MULTI_TYPE_BATCH"
                if batch_ready and policy.mode == "CONTROLLED_MULTI_TYPE_BATCH"
                else "READY_FOR_CONTROLLED_BATCH"
                if batch_ready
                else "READY_FOR_CONTROLLED_WRITE"
                if real_ready
                else "READY_FOR_SIMULATION"
                if not simulation_violations
                else "BLOCKED"
            ),
            "jira_write_enabled": policy.jira_write_enabled,
            "simulation_only": not real_policy_active and not batch_policy_active,
            "policy": policy.public_summary(),
            "policy_violations": (
                simulation_violations
                if not real_policy_active and not batch_policy_active
                else []
            ),
            "mcp_tools": tools,
            "task_contract": {
                "space": "AT",
                "space_id": (at_space or {}).get("id"),
                "work_type": "Task",
                "work_type_id": (task or {}).get("id"),
                "fields": (task or {}).get("fields", []),
            },
            "work_type_contracts": allowed_type_contracts,
            "real_canary_checks": real_canary_checks,
            "real_canary_ready": all(real_canary_checks.values()),
            "controlled_write_ready": real_ready,
            "batch_write_ready": batch_ready,
            "confirmation_phrase": JiraControlledExecutionService.CONFIRMATION_PHRASE,
            "next_gate": (
                "SELECT_PARENT_BEFORE_CHILD_BATCH"
                if batch_ready and policy.mode == "CONTROLLED_HIERARCHY_BATCH"
                else "SELECT_ONE_TO_FIVE_TASKS"
                if batch_ready
                else
                "EXPLICIT_IN_APP_CONFIRMATION"
                if real_ready
                else "START_WITH_OBJECTIVE_4B_POLICY"
            ),
        }

    @app.post("/api/auth/login")
    def login(
        credentials: LoginRequest,
        provider: AuthProvider = Depends(get_auth_provider),
    ):
        session = provider.login(credentials)
        payload = session.model_dump(exclude={"session_token"})
        # This endpoint is the explicitly enabled local recovery path.  Tests
        # and local recovery clients retain bearer compatibility; normal OAuth
        # login never returns a session token to frontend JavaScript.
        payload["access_token"] = session.session_token or ""
        payload["radar_telegram_url"] = settings.news_telegram_url
        return JSONResponse(content=payload)

    def _safe_return_path(value: str | None) -> str:
        return value if value and value.startswith("/") and not value.startswith("//") else "/"

    def _session_user_payload(user: AuthenticatedUser) -> dict[str, str]:
        return {
            "username": user.username,
            "display_name": user.display_name,
            "role": user.role,
            "email": user.email or "",
            "atlassian_account_id": user.atlassian_account_id or "",
        }

    def _cookie_response(path: str, session_token: str) -> RedirectResponse:
        response = RedirectResponse(url=path, status_code=303)
        response.set_cookie(
            SESSION_COOKIE, session_token, httponly=True, samesite="lax",
            secure=urlparse(settings.atlassian_oauth_callback_url).scheme == "https", path="/",
        )
        return response

    @app.get("/api/auth/me")
    def auth_me(user: AuthenticatedUser = Depends(require_user)):
        onboarding = app.state.repository.get_onboarding_status(user.user_id) if user.user_id is not None else None
        return {
            "access_token": "", "token_type": "bearer", "user": _session_user_payload(user),
            "radar_telegram_url": settings.news_telegram_url,
            "onboarding": {
                "version": int((onboarding or {}).get("onboarding_version") or 0),
                "current_version": 1,
                "required": int((onboarding or {}).get("onboarding_version") or 0) < 1,
                "completed_at": (onboarding or {}).get("onboarding_completed_at"),
                "skipped_at": (onboarding or {}).get("onboarding_skipped_at"),
            },
        }

    @app.get("/api/onboarding/status")
    def onboarding_status(user: AuthenticatedUser = Depends(require_user)):
        value = app.state.repository.get_onboarding_status(user.user_id) if user.user_id is not None else None
        version = int((value or {}).get("onboarding_version") or 0)
        return {
            "version": version, "current_version": 1, "required": version < 1,
            "completed_at": (value or {}).get("onboarding_completed_at"),
            "skipped_at": (value or {}).get("onboarding_skipped_at"),
        }

    @app.post("/api/onboarding/complete")
    def onboarding_complete(user: AuthenticatedUser = Depends(require_user)):
        if user.user_id is None:
            raise HTTPException(status_code=401, detail="Autenticación requerida.")
        now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        value = app.state.repository.mark_onboarding_complete(user.user_id, 1, now) or {}
        return {"version": int(value.get("onboarding_version") or 0), "current_version": 1,
                "required": False, "completed_at": value.get("onboarding_completed_at"),
                "skipped_at": value.get("onboarding_skipped_at")}

    @app.post("/api/onboarding/skip")
    def onboarding_skip(user: AuthenticatedUser = Depends(require_user)):
        if user.user_id is None:
            raise HTTPException(status_code=401, detail="Autenticación requerida.")
        now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        value = app.state.repository.mark_onboarding_skipped(user.user_id, 1, now) or {}
        return {"version": int(value.get("onboarding_version") or 0), "current_version": 1,
                "required": False, "completed_at": value.get("onboarding_completed_at"),
                "skipped_at": value.get("onboarding_skipped_at")}

    @app.post("/api/auth/logout")
    def auth_logout(request: Request, user: AuthenticatedUser = Depends(require_user)):
        token = getattr(request.state, "session_token", "")
        if token:
            app.state.auth_provider.logout(token)
        response = Response(status_code=204)
        response.delete_cookie(SESSION_COOKIE, path="/")
        return response

    @app.get("/api/auth/atlassian/start")
    async def atlassian_login_start(return_path: str | None = Query(default=None)):
        pending_identity = "oauth-login:" + secrets.token_urlsafe(18)
        try:
            result = await app.state.atlassian_manager.begin_connect(pending_identity)
            state = parse_qs(urlparse(result["authorization_url"]).query).get("state", [""])[0]
            if not state:
                await app.state.atlassian_manager.disconnect(pending_identity)
                raise AtlassianIntegrationError("OAUTH_STATE_INVALID")
            now = datetime.now(UTC)
            now_iso = now.isoformat().replace("+00:00", "Z")
            app.state.repository.record_oauth_state(
                hashlib.sha256(state.encode("utf-8")).hexdigest(), pending_identity, _safe_return_path(return_path),
                now_iso, (now + timedelta(minutes=10)).isoformat().replace("+00:00", "Z"),
            )
            app.state.repository.audit_auth_event("AUTH_ATLASSIAN_STARTED", now_iso)
            return result
        except AtlassianIntegrationError as exc:
            # The integration manager only exposes allowlisted, user-safe
            # diagnostics (never URLs, codes or tokens).  Returning that
            # message lets the login screen distinguish an unavailable MCP
            # endpoint from a failed consent flow.
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/api/auth/atlassian/unlink")
    async def atlassian_unlink(user: AuthenticatedUser = Depends(require_user)):
        await app.state.atlassian_manager.disconnect(user.username)
        if user.user_id is not None:
            app.state.repository.clear_atlassian_credential_metadata(user.user_id)
            app.state.repository.audit_auth_event("ATLASSIAN_UNLINKED", datetime.now(UTC).isoformat(), user.user_id)
        return Response(status_code=204)

    @app.post("/api/auth/admin/users")
    def authorize_app_user(
        payload: dict[str, str],
        user: AuthenticatedUser = Depends(require_user),
    ):
        """Pre-authorize a corporate account before its first Atlassian login."""

        if user.role != "ADMIN":
            raise HTTPException(status_code=403, detail="Sólo un administrador puede autorizar usuarios.")
        email = str(payload.get("email") or "").strip()
        display_name = str(payload.get("display_name") or email).strip()
        role = str(payload.get("role") or "USER").upper()
        if not email or "@" not in email or role not in {"ADMIN", "USER"}:
            raise HTTPException(status_code=422, detail="Nombre, correo y rol válidos son obligatorios.")
        username = "atlassian:" + hashlib.sha256(email.casefold().encode("utf-8")).hexdigest()[:24]
        result = app.state.repository.ensure_authorized_user(
            username=username, email=email, display_name=display_name, role=role, status="PENDING",
        )
        app.state.repository.audit_auth_event(
            "USER_AUTHORIZED", datetime.now(UTC).isoformat().replace("+00:00", "Z"), user.user_id,
        )
        return {
            "id": result["id"], "email": result["email"], "display_name": result["display_name"],
            "role": result["role"], "status": result["status"],
        }

    @app.get("/api/jira/write-lock")
    def jira_write_lock_status(user: AuthenticatedUser = Depends(require_user)):
        return app.state.jira_write_lock.status()

    @app.post("/api/jira/write-lock/unlock")
    def jira_write_lock_unlock(user: AuthenticatedUser = Depends(require_user)):
        # Every authenticated corporate user may open their own short-lived
        # creation window. Proposal, dry-run and second-confirmation gates
        # still apply, and Jira enforces the real account permissions.
        authorized = user.role in {"ADMIN", "USER"}
        return app.state.jira_write_lock.unlock(user.username, authorized=authorized)

    @app.post("/api/jira/write-lock/lock")
    def jira_write_lock_lock(user: AuthenticatedUser = Depends(require_user)):
        return app.state.jira_write_lock.lock(user.username)

    @app.get("/api/diagnostics/performance")
    def performance_diagnostics(user: AuthenticatedUser = Depends(require_user)):
        return {
            "latest": app.state.performance_registry.latest(),
            "recent": app.state.performance_registry.list()[-10:],
        }

    @app.get("/api/dashboard/status")
    def dashboard_status(user: AuthenticatedUser = Depends(require_user)):
        return app.state.dashboard_service.status(user.username)

    @app.get("/api/dashboard/summary")
    def dashboard_summary(user: AuthenticatedUser = Depends(require_user)):
        try:
            return app.state.dashboard_service.get_summary(user.username)
        except DashboardDataError as exc:
            raise HTTPException(status_code=409 if exc.state == "NO_DATA" else 503,
                                detail={"message": str(exc), "state": exc.state}) from exc

    @app.get("/api/dashboard/spaces/{space_key}")
    def dashboard_space(space_key: str, user: AuthenticatedUser = Depends(require_user)):
        try:
            return app.state.dashboard_service.get_space(user.username, space_key)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Espacio fuera del alcance de lectura del Dashboard.") from exc
        except DashboardDataError as exc:
            raise HTTPException(status_code=409 if exc.state == "NO_DATA" else 503,
                                detail={"message": str(exc), "state": exc.state}) from exc

    @app.get("/api/dashboard/issues")
    def dashboard_issues(
        space: str | None = Query(default=None),
        category: str | None = Query(default=None, pattern="^(todo|in_progress|done|unknown)?$"),
        issue_type: str | None = Query(default=None, alias="type"),
        type_name: str | None = Query(default=None, alias="work_type"),
        priority: str | None = Query(default=None),
        assignee: str | None = Query(default=None),
        tracking: str | None = Query(default=None),
        epic_key: str | None = Query(default=None, alias="epic"),
        overdue: bool = Query(default=False),
        unassigned: bool = Query(default=False),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=50, ge=1, le=200),
        user: AuthenticatedUser = Depends(require_user),
    ):
        try:
            return app.state.dashboard_service.get_issues(
                user.username, space=space, category=category, issue_type=issue_type,
                type_name=type_name, priority=priority, assignee=assignee, tracking=tracking,
                epic_key=epic_key, overdue=overdue,
                unassigned=unassigned, page=page, page_size=page_size,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Espacio fuera del alcance de lectura del Dashboard.") from exc
        except DashboardDataError as exc:
            raise HTTPException(status_code=409 if exc.state == "NO_DATA" else 503,
                                detail={"message": str(exc), "state": exc.state}) from exc

    @app.post("/api/dashboard/refresh", status_code=202)
    async def dashboard_refresh(user: AuthenticatedUser = Depends(require_user)):
        # This endpoint schedules only Jira reads; it has no access to a write gateway.
        return app.state.dashboard_service.refresh(user.username)

    @app.get("/api/voice/status", response_model=VoiceStatusResponse)
    def voice_status(user: AuthenticatedUser = Depends(require_user)):
        """Return side-effect-free voice state; it never loads a model."""
        return app.state.voice_service.get_status()

    @app.post("/api/voice/activate", response_model=VoiceStatusResponse)
    async def activate_voice(user: AuthenticatedUser = Depends(require_user)):
        """Run lightweight capability checks without loading voice resources."""
        return await app.state.voice_service.activate()

    @app.get("/api/session")
    def session(user: AuthenticatedUser = Depends(require_user)):
        return {"username": user.username, "display_name": user.display_name}

    @app.post("/api/voice/command", response_model=VoiceCommandResponse)
    async def voice_command(
        audio: UploadFile = File(...),
        proposal_id: str | None = Form(default=None),
        spoken_response: bool = Form(default=False),
        user: AuthenticatedUser = Depends(require_user),
    ):
        content_type = (audio.content_type or "").strip().lower()
        media_type = content_type.split(";", 1)[0]
        if media_type not in VOICE_AUDIO_TYPES:
            await audio.close()
            raise HTTPException(
                status_code=415,
                detail="El formato de audio no es compatible.",
            )
        try:
            content = await audio.read(settings.voice_max_audio_bytes + 1)
        finally:
            await audio.close()
        if not content:
            raise HTTPException(status_code=400, detail="El audio está vacío.")
        if len(content) > settings.voice_max_audio_bytes:
            raise HTTPException(
                status_code=413,
                detail=(
                    "El audio supera el límite local de "
                    f"{settings.voice_max_audio_bytes // (1024 * 1024)} MB."
                ),
            )
        try:
            return await app.state.voice_service.process(
                content,
                content_type,
                user,
                current_proposal_id=proposal_id,
                spoken_response=spoken_response,
            )
        except VoiceInputError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except VoiceUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except VoiceTimeoutError as exc:
            raise HTTPException(status_code=504, detail=str(exc)) from exc

    @app.get("/api/voice/context", response_model=VoiceContextView)
    def voice_context(user: AuthenticatedUser = Depends(require_user)):
        return app.state.voice_service.get_context(user)

    @app.delete("/api/voice/context", response_model=VoiceContextView)
    def clear_voice_context(user: AuthenticatedUser = Depends(require_user)):
        return app.state.voice_service.clear_context(user)

    @app.post("/api/voice/jira/confirm", response_model=VoiceCommandResponse)
    async def confirm_voice_jira_create(
        request: VoiceJiraConfirmRequest,
        user: AuthenticatedUser = Depends(require_user),
    ):
        assert_global_write_available(user.username)
        return await app.state.voice_service.confirm_jira(
            user,
            request.confirmation_id,
            request.payload_hash,
            request.spoken_response,
        )

    @app.post("/api/voice/jira/cancel", response_model=VoiceCommandResponse)
    async def cancel_voice_jira_create(
        request: VoiceJiraCancelRequest,
        user: AuthenticatedUser = Depends(require_user),
    ):
        return await app.state.voice_service.cancel_jira(
            user,
            request.confirmation_id,
            request.payload_hash,
            request.spoken_response,
        )

    @app.get("/api/integrations/atlassian/status")
    async def atlassian_status(user: AuthenticatedUser = Depends(require_user)):
        restore = getattr(app.state.atlassian_manager, "ensure_restored", None)
        if restore is not None:
            await restore(user.username)
        status = app.state.atlassian_manager.status(user.username)
        status["jira_write_enabled"] = app.state.jira_execution_policy.jira_write_enabled
        status["write_tools_blocked"] = not app.state.jira_execution_policy.jira_write_enabled
        status["global_write_lock"] = app.state.jira_write_lock.status()
        status["performance"] = app.state.performance_registry.latest()
        return status

    @app.post("/api/integrations/atlassian/connect")
    async def atlassian_connect(user: AuthenticatedUser = Depends(require_user)):
        try:
            return await app.state.atlassian_manager.begin_connect(user.username)
        except AtlassianIntegrationError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except Exception as exc:  # pragma: no cover - network/client variants
            logger.warning("Unexpected failure while starting Atlassian OAuth category=%s", type(exc).__name__)
            raise HTTPException(
                status_code=502,
                detail="No se pudo iniciar la conexión con Atlassian. Verifica la red o inténtalo de nuevo más tarde.",
            ) from exc

    @app.post("/api/integrations/atlassian/connect/external")
    async def atlassian_connect_external(user: AuthenticatedUser = Depends(require_user)):
        """Start OAuth and open Atlassian in the user's normal browser.

        The embedded Codex browser can render Atlassian's consent shell as a blank
        page.  Keeping the local app open while the default browser handles OAuth
        also lets the status poller observe the callback without losing the local
        session.
        """
        try:
            result = await app.state.atlassian_manager.begin_connect(user.username)
            if not webbrowser.open_new_tab(result["authorization_url"]):
                raise AtlassianIntegrationError("No se pudo abrir el navegador predeterminado para Atlassian.")
            return {**result, "browser": "external"}
        except AtlassianIntegrationError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except Exception as exc:  # pragma: no cover - platform/browser variants
            logger.warning("Unable to open external Atlassian OAuth browser category=%s", type(exc).__name__)
            raise HTTPException(
                status_code=502,
                detail="No se pudo abrir el navegador para Atlassian. Intenta desde un navegador externo.",
            ) from exc

    @app.get("/api/integrations/atlassian/callback")
    async def atlassian_callback(
        code: str | None = Query(default=None),
        state: str | None = Query(default=None),
        error: str | None = Query(default=None),
    ):
        state_hash = hashlib.sha256(state.encode("utf-8")).hexdigest() if state else ""
        now_iso = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        login_state = (
            app.state.repository.consume_oauth_state(state_hash, now_iso) if state_hash else None
        )
        if error:
            await app.state.atlassian_manager.deny_callback(state)
            if login_state:
                app.state.repository.audit_auth_event("AUTH_ATLASSIAN_DENIED", now_iso)
                return RedirectResponse(url="/?auth=ACCESS_DENIED", status_code=303)
            return RedirectResponse(url="/?atlassian=denied", status_code=303)
        if not code or not state:
            return RedirectResponse(url="/?atlassian=OAUTH_CALLBACK_INVALID", status_code=303)
        try:
            status_result = await app.state.atlassian_manager.finish_callback(code, state)
        except AtlassianIntegrationError as exc:
            marker = "STATE_INVALID" if str(exc) == "OAUTH_STATE_INVALID" else "TOKEN_EXCHANGE_FAILED"
            if login_state:
                app.state.repository.audit_auth_event("AUTH_ATLASSIAN_DENIED", now_iso, detail=marker)
                return RedirectResponse(url=f"/?auth={marker}", status_code=303)
            legacy_marker = "OAUTH_STATE_INVALID" if marker == "STATE_INVALID" else "error"
            return RedirectResponse(url=f"/?atlassian={legacy_marker}", status_code=303)

        # Existing configuration OAuth callbacks remain supported. An OAuth
        # state created by the login endpoint must also be persisted, unexpired,
        # and one-use before it creates an app session.
        if not login_state:
            return RedirectResponse(url="/?atlassian=connected", status_code=303)

        snapshot = status_result.get("snapshot") if isinstance(status_result, dict) else None
        identity = (snapshot or {}).get("atlassian_user") if isinstance(snapshot, dict) else None
        account_id = str((identity or {}).get("account_id") or "").strip()
        email = str((identity or {}).get("email") or "").strip().casefold()
        pending_identity = str(login_state["pending_identity"])
        if not account_id:
            await app.state.atlassian_manager.disconnect(pending_identity)
            app.state.repository.audit_auth_event("AUTH_ATLASSIAN_DENIED", now_iso, detail="IDENTITY_UNAVAILABLE")
            return RedirectResponse(url="/?auth=IDENTITY_UNAVAILABLE", status_code=303)

        app_user = app.state.repository.get_app_user_by_account_id(account_id)
        linked_now = False
        legacy_bootstrap = False
        auto_authorized = False
        if app_user is None and email:
            candidate = app.state.repository.get_app_user_by_email(email)
            if candidate is not None and candidate.get("atlassian_account_id") is None:
                app_user = candidate

        # The former local administrator only migrates after the saved OAuth
        # credential proves it belongs to this same Atlassian account.
        if app_user is None:
            legacy_admin = app.state.repository.get_app_user_by_username(settings.local_user)
            if legacy_admin and legacy_admin.get("status") == "PENDING" and not legacy_admin.get("atlassian_account_id"):
                try:
                    legacy_status = await app.state.atlassian_manager.ensure_restored(settings.local_user)
                    legacy_identity = (legacy_status.get("snapshot") or {}).get("atlassian_user") or {}
                    if str(legacy_identity.get("account_id") or "") == account_id:
                        app_user = legacy_admin
                except Exception:
                    app_user = None
                # A DPAPI credential from the previous single-user app can be
                # unreadable after a Windows/profile change. During this one
                # migration only, its presence proves the local operator owns
                # the legacy installation; the fresh OAuth flow already proved
                # access to the configured corporate Jira site. Once linked,
                # this branch can never run again for that administrator.
                if app_user is None and getattr(
                    app.state.atlassian_manager, "has_persisted_credentials", lambda _username: False
                )(settings.local_user):
                    app_user = legacy_admin
                    legacy_bootstrap = True

        # This deployment admits every valid corporate OAuth identity for the
        # configured Jira site. Jira remains the authority for what that user
        # can actually read or create.
        if app_user is None and settings.allow_all_corporate_users and email:
            username = "atlassian:" + hashlib.sha256(account_id.encode("utf-8")).hexdigest()[:24]
            app_user = app.state.repository.ensure_authorized_user(
                username=username,
                email=email,
                display_name=str((identity or {}).get("display_name") or email),
                role="USER",
                status="ACTIVE",
            )
            auto_authorized = True

        if app_user is None or app_user.get("status") == "DISABLED":
            await app.state.atlassian_manager.disconnect(pending_identity)
            app.state.repository.audit_auth_event("LOGIN_DENIED", now_iso, detail="NO_ALLOWED_LOCAL_USER")
            return RedirectResponse(url="/?auth=NO_ALLOWED_LOCAL_USER", status_code=303)

        if app_user.get("atlassian_account_id") != account_id:
            try:
                app_user = app.state.repository.link_atlassian_account(int(app_user["id"]), account_id, now_iso)
                linked_now = True
            except ValueError:
                await app.state.atlassian_manager.disconnect(pending_identity)
                app.state.repository.audit_auth_event("LOGIN_DENIED", now_iso, detail="ACCOUNT_ID_MISMATCH")
                return RedirectResponse(url="/?auth=NO_ALLOWED_LOCAL_USER", status_code=303)

        await app.state.atlassian_manager.rebind_user(pending_identity, str(app_user["username"]))
        metadata = app.state.atlassian_manager.credential_metadata(str(app_user["username"]))
        app.state.repository.save_atlassian_credential_metadata(
            user_id=int(app_user["id"]), account_id=account_id, storage_key=str(app_user["username"]),
            expires_at=metadata.get("expires_at"), scopes=metadata.get("scopes"),
            cloud_id=metadata.get("cloud_id"), site_url=metadata.get("site_url"), now=now_iso,
        )
        app.state.repository.touch_app_user_login(int(app_user["id"]), now_iso)
        app.state.repository.audit_auth_event(
            "LEGACY_ADMIN_BOOTSTRAP" if legacy_bootstrap else "USER_AUTO_AUTHORIZED" if auto_authorized else "USER_LINKED" if linked_now else "AUTH_ATLASSIAN_SUCCESS",
            now_iso,
            int(app_user["id"]),
        )
        session = app.state.auth_provider.create_session(app_user)
        return _cookie_response(str(login_state["return_path"]), session.session_token or "")

    @app.post("/api/integrations/atlassian/disconnect")
    async def atlassian_disconnect(user: AuthenticatedUser = Depends(require_user)):
        await app.state.atlassian_manager.disconnect(user.username)
        result = app.state.atlassian_manager.status(user.username)
        result["global_write_lock"] = app.state.jira_write_lock.status()
        return result

    @app.post("/api/integrations/atlassian/refresh")
    async def atlassian_refresh(user: AuthenticatedUser = Depends(require_user)):
        try:
            result = await app.state.atlassian_manager.refresh(user.username)
            result["global_write_lock"] = app.state.jira_write_lock.status()
            return result
        except AtlassianIntegrationError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post('/api/integrations/atlassian/diagnose')
    async def atlassian_diagnose(user: AuthenticatedUser = Depends(require_user)):
        manager = app.state.atlassian_manager
        await manager.diagnostics.check(user.username)
        status = manager.status(user.username)
        status['jira_write_enabled'] = app.state.jira_execution_policy.jira_write_enabled
        status['write_tools_blocked'] = not status['jira_write_enabled']
        status['global_write_lock'] = app.state.jira_write_lock.status()
        status['performance'] = app.state.performance_registry.latest()
        return status

    @app.get("/api/integrations/atlassian/assignees")
    async def atlassian_assignees(
        space: str = Query(...),
        q: str = Query(...),
        user: AuthenticatedUser = Depends(require_user),
    ):
        try:
            return await app.state.atlassian_manager.find_assignees(
                user.username,
                space.upper(),
                q,
            )
        except AtlassianIntegrationError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/integrations/atlassian/sprints")
    async def atlassian_sprints(
        space: str = Query(...),
        refresh: bool = Query(default=False),
        user: AuthenticatedUser = Depends(require_user),
    ):
        try:
            return await app.state.atlassian_manager.list_sprints(
                user.username,
                space.upper(),
                force_refresh=refresh,
            )
        except AtlassianIntegrationError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/template/v1.2")
    @app.get("/api/template/v1.3")
    async def download_dynamic_template(request: Request, user: AuthenticatedUser = Depends(require_user)):
        """Build a versioned template from the current read-only Jira tracking catalog."""
        template_version = "1.3" if request.url.path.endswith("v1.3") else "1.2"
        restore = getattr(app.state.atlassian_manager, "ensure_restored", None)
        if restore is not None:
            await restore(user.username)
        try:
            catalog = app.state.atlassian_manager.jira_field_catalog(
                user.username, "AT", "Task", "customfield_10147"
            )
        except AtlassianIntegrationError:
            catalog = {
                "space": "AT",
                "work_type": "Task",
                "field_id": "customfield_10147",
                "field_name": "Tipo de seguimiento",
                "options": [],
                "fetched_at": None,
                "status": "unavailable",
            }
        output_dir = settings.database_path.parent / "generated_templates"
        output_dir.mkdir(parents=True, exist_ok=True)
        safe_id = hashlib.sha256(user.username.casefold().encode()).hexdigest()[:16]
        output_path = output_dir / f"plantilla_plan_trabajo_jira_v{template_version.replace('.', '_')}_{safe_id}.xlsx"
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8", delete=False) as handle:
            json.dump(catalog, handle, ensure_ascii=False)
            catalog_path = handle.name
        try:
            subprocess.run(
                [
                    sys.executable,
                    str(settings.frozen_template_path.parent.parent.parent / "scripts" / f"build_template_v{template_version.replace('.', '')}.py"),
                    catalog_path,
                    str(output_path),
                ],
                check=True,
                capture_output=True,
                text=True,
                cwd=str(settings.frozen_template_path.parent.parent.parent),
            )
        finally:
            Path(catalog_path).unlink(missing_ok=True)
        return FileResponse(
            output_path,
            filename=f"plantilla_plan_trabajo_jira_v{template_version.replace('.', '_')}.xlsx",
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"X-Catalog-Status": catalog["status"]},
        )

    @app.get("/api/template")
    def download_template(version: str = Query(default="1.1", pattern=r"^1\.(1|2|3)$")):
        if version == "1.2":
            template_path = settings.frozen_template_path.parent.parent / "plantilla_excel_v1_2" / "plantilla_plan_trabajo_jira_v1_2.xlsx"
            if not template_path.exists():
                raise HTTPException(status_code=404, detail="La plantilla v1.2 no está disponible en esta instalación local.")
        elif version == "1.3":
            template_path = settings.frozen_template_path.parent.parent / "plantilla_excel_v1_3" / "plantilla_plan_trabajo_jira_v1_3.xlsx"
            if not template_path.exists():
                raise HTTPException(status_code=404, detail="La plantilla v1.3 no está disponible en esta instalación local.")
        else:
            template_path = settings.frozen_template_path
        return FileResponse(
            template_path,
            filename=f"plantilla_plan_trabajo_jira_v{version.replace('.', '_')}.xlsx",
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    @app.post("/api/proposals", status_code=201)
    async def create_proposal(
        file: UploadFile = File(...),
        space: str = Form(...),
        iniciativa: str | None = Form(default=None),
        linea_trabajo: str | None = Form(default=None),
        sprint: str | None = Form(default=None),
        tipo_seguimiento: str | None = Form(default=None),
        semaforo: str | None = Form(default=None),
        user: AuthenticatedUser = Depends(require_user),
    ):
        content = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail="El archivo supera el límite local de 10 MB.",
            )
        try:
            defaults = PlanDefaults(
                space=space,
                iniciativa=iniciativa,
                linea_trabajo=linea_trabajo,
                sprint=sprint,
                tipo_seguimiento=tipo_seguimiento,
                semaforo=semaforo,
            )
        except ValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail="Los valores generales del plan no son válidos.",
            ) from exc
        parsed = service.parser.parse(file.filename or "plantilla.xlsx", content)
        assignee_overrides: dict[str, dict[str, str | None]] = {}
        manager = app.state.atlassian_manager
        try:
            restore = getattr(manager, "ensure_restored", None)
            if restore is not None:
                await restore(user.username)
            if manager.status(user.username).get("connected"):
                responsible_queries = {
                    str(row.get("responsable_display") or "").strip()
                    for row in parsed.rows
                    if str(row.get("responsable_display") or "").strip()
                    and normalize_name(str(row.get("responsable_display"))) != "por definir"
                }
                for query in responsible_queries:
                    try:
                        candidates = await manager.find_assignees(user.username, space, query)
                    except Exception as exc:  # Jira lookup is best-effort; import remains local-first.
                        logger.info("Automatic Jira assignee lookup skipped category=%s", type(exc).__name__)
                        continue
                    normalized_query = normalize_name(query)
                    exact = [
                        candidate
                        for candidate in candidates
                        if candidate.get("active", True)
                        and candidate.get("account_id")
                        and (
                            normalize_name(str(candidate.get("display_name") or "")) == normalized_query
                            or normalize_name(str(candidate.get("email") or "")) == normalized_query
                        )
                    ]
                    if len(exact) == 1:
                        candidate = exact[0]
                        assignee_overrides[normalized_query] = {
                            "display_name": str(candidate.get("display_name") or query),
                            "email": candidate.get("email"),
                            "account_id": str(candidate["account_id"]),
                            "resolution": "RESOLVED",
                        }
        except Exception as exc:  # A temporary Jira outage must not prevent a local proposal.
            logger.info("Automatic Jira assignee resolution unavailable category=%s", type(exc).__name__)
        return service.create_from_workbook(
            filename=file.filename or "plantilla.xlsx",
            content=content,
            defaults=defaults,
            created_by=user.username,
            parsed=parsed,
            assignee_overrides=assignee_overrides,
        )

    @app.get("/api/proposals")
    def list_proposals(
    include_trash: bool = Query(False),
        _user: AuthenticatedUser = Depends(require_user),
    ):
        repository.purge_expired_trash(utc_now())
        return [
            service.summarize(proposal, **lifecycle)
            for proposal, lifecycle in repository.list_latest_with_lifecycle(
                include_trashed=include_trash,
            )
        ]

    @app.post("/api/proposals/{proposal_id}/archive")
    def archive_proposal(
        proposal_id: str,
        user: AuthenticatedUser = Depends(require_user),
    ):
        if repository.get_lifecycle(proposal_id).get("deleted_at"):
            raise HTTPException(
                status_code=409,
                detail="La propuesta está en la papelera; restáurala antes de archivarla.",
            )
        archived_at = utc_now()
        if not repository.set_archived(
            proposal_id,
            archived_at=archived_at,
            archived_by=user.username,
        ):
            raise HTTPException(status_code=404, detail="Propuesta no encontrada.")
        proposal = repository.get(proposal_id)
        return service.summarize(proposal, **repository.get_lifecycle(proposal_id))

    @app.post("/api/proposals/{proposal_id}/trash")
    def trash_proposal(
        proposal_id: str,
        user: AuthenticatedUser = Depends(require_user),
    ):
        deleted_at = utc_now()
        purge_at = (datetime.now(UTC) + timedelta(days=30)).isoformat().replace("+00:00", "Z")
        if not repository.set_trashed(
            proposal_id,
            deleted_at=deleted_at,
            deleted_by=user.username,
            purge_at=purge_at,
        ):
            raise HTTPException(status_code=404, detail="Propuesta no encontrada.")
        proposal = repository.get(proposal_id)
        return service.summarize(proposal, **repository.get_lifecycle(proposal_id))

    @app.post("/api/proposals/{proposal_id}/restore")
    def restore_proposal(
        proposal_id: str,
        _user: AuthenticatedUser = Depends(require_user),
    ):
        if repository.get_lifecycle(proposal_id).get("deleted_at"):
            repository.set_trashed(
                proposal_id,
                deleted_at=None,
                deleted_by=None,
                purge_at=None,
            )
        if not repository.set_archived(
            proposal_id,
            archived_at=None,
            archived_by=None,
        ):
            raise HTTPException(status_code=404, detail="Propuesta no encontrada.")
        proposal = repository.get(proposal_id)
        return service.summarize(proposal, **repository.get_lifecycle(proposal_id))

    @app.delete("/api/proposals/{proposal_id}/permanent")
    def permanently_delete_proposal(
        proposal_id: str,
        _user: AuthenticatedUser = Depends(require_user),
    ):
        result = repository.permanently_delete_trashed(proposal_id)
        if result == "NOT_FOUND":
            raise HTTPException(status_code=404, detail="Propuesta no encontrada.")
        if result == "NOT_IN_TRASH":
            raise HTTPException(
                status_code=409,
                detail="Sólo puedes borrar definitivamente una propuesta que esté en la papelera.",
            )
        return {"proposal_id": proposal_id, "permanently_deleted": True}

    @app.patch("/api/proposals/{proposal_id}/metadata")
    def update_proposal_metadata(
        proposal_id: str,
        update: ProposalMetadataUpdate,
        user: AuthenticatedUser = Depends(require_user),
    ):
        display_name = update.display_name.strip()
        if not display_name:
            raise HTTPException(status_code=422, detail="El nombre no puede quedar vacío.")
        updated_at = utc_now()
        if not repository.set_display_name(
            proposal_id,
            display_name=display_name,
            updated_at=updated_at,
            updated_by=user.username,
        ):
            raise HTTPException(status_code=404, detail="Propuesta no encontrada.")
        proposal = repository.get(proposal_id)
        return service.summarize(
            proposal,
            **repository.get_lifecycle(proposal_id),
        )

    @app.patch("/api/proposals/{proposal_id}/defaults")
    def update_proposal_defaults(
        proposal_id: str,
        update: ProposalDefaultsUpdate,
        user: AuthenticatedUser = Depends(require_user),
    ):
        proposal = service.update_defaults(
            proposal_id=proposal_id,
            update=update,
            modified_by=user.username,
        )
        if proposal is None:
            raise HTTPException(status_code=404, detail="Propuesta no encontrada.")
        return proposal

    @app.get("/api/assignees")
    def list_assignees(_user: AuthenticatedUser = Depends(require_user)):
        return service.catalog.list_users()

    @app.get("/api/proposals/{proposal_id}")
    def get_proposal(
        proposal_id: str,
        version: int | None = Query(default=None, ge=1),
        _user: AuthenticatedUser = Depends(require_user),
    ):
        proposal = repository.get(proposal_id, version)
        if proposal is None:
            raise HTTPException(status_code=404, detail="Propuesta no encontrada.")
        return service.prepare_for_display(proposal)

    @app.patch("/api/proposals/{proposal_id}/items/{row_id}")
    async def update_item(
        proposal_id: str,
        row_id: str,
        update: ItemUpdate,
        user: AuthenticatedUser = Depends(require_user),
    ):
        verified_assignee = None
        if update.assignee_account_id and update.assignee_query:
            current = repository.get(proposal_id)
            if current is None:
                raise HTTPException(status_code=404, detail="Propuesta no encontrada.")
            current_item = next(
                (
                    entry
                    for entry in current["items"]
                    if entry["generated"]["row_id"] == row_id
                ),
                None,
            )
            if current_item is None:
                raise HTTPException(status_code=404, detail=f"No existe la fila '{row_id}'.")
            try:
                candidates = await app.state.atlassian_manager.find_assignees(
                    user.username,
                    current_item["generated"]["space"],
                    update.assignee_query,
                )
            except AtlassianIntegrationError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            verified_assignee = next(
                (
                    candidate
                    for candidate in candidates
                    if candidate.get("account_id") == update.assignee_account_id
                    and candidate.get("active", True)
                ),
                None,
            )
            if verified_assignee is None:
                raise HTTPException(
                    status_code=422,
                    detail="La cuenta seleccionada ya no aparece como una coincidencia activa en Jira.",
                )
        try:
            proposal = service.update_item(
                proposal_id=proposal_id,
                row_id=row_id,
                update=update,
                modified_by=user.username,
                verified_assignee=verified_assignee,
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail=f"No existe la fila '{row_id}' en la propuesta.",
            ) from exc
        except ProposalStateError:
            raise
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if proposal is None:
            raise HTTPException(status_code=404, detail="Propuesta no encontrada.")
        return proposal

    @app.post("/api/proposals/{proposal_id}/bulk-update")
    def bulk_update_proposal(
        proposal_id: str,
        update: BulkProposalUpdate,
        user: AuthenticatedUser = Depends(require_user),
    ):
        try:
            proposal = service.bulk_update_items(proposal_id, update, user.username)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"No existe la fila '{exc.args[0]}'.") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if proposal is None:
            raise HTTPException(status_code=404, detail="Propuesta no encontrada.")
        return proposal

    @app.post("/api/proposals/{proposal_id}/exclude")
    def exclude_proposal_items(
        proposal_id: str,
        request: ProposalExclusionRequest,
        user: AuthenticatedUser = Depends(require_user),
    ):
        try:
            proposal = service.exclude_items(
                proposal_id,
                request.row_ids,
                request.reason,
                user.username,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"No existe la fila '{exc.args[0]}'.") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if proposal is None:
            raise HTTPException(status_code=404, detail="Propuesta no encontrada.")
        return proposal

    @app.post("/api/proposals/{proposal_id}/items/{row_id}/reactivate")
    def reactivate_item(
        proposal_id: str,
        row_id: str,
        request: ReactivationRequest,
        user: AuthenticatedUser = Depends(require_user),
    ):
        try:
            proposal = service.reactivate_item(
                proposal_id,
                row_id,
                request.reason,
                user.username,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"No existe la fila '{row_id}'.") from exc
        if proposal is None:
            raise HTTPException(status_code=404, detail="Propuesta no encontrada.")
        return proposal

    @app.patch("/api/proposals/{proposal_id}/items/{row_id}/jira-assignee")
    async def update_jira_assignee(
        proposal_id: str,
        row_id: str,
        request: JiraAssigneeSelectionRequest,
        user: AuthenticatedUser = Depends(require_user),
    ):
        proposal = repository.get(proposal_id)
        if proposal is None:
            raise HTTPException(status_code=404, detail="Propuesta no encontrada.")
        item = next(
            (
                entry
                for entry in proposal["items"]
                if entry["generated"]["row_id"] == row_id
            ),
            None,
        )
        if item is None:
            raise HTTPException(status_code=404, detail=f"No existe la fila '{row_id}'.")
        try:
            candidates = await app.state.atlassian_manager.find_assignees(
                user.username,
                item["generated"]["space"],
                request.query,
            )
        except AtlassianIntegrationError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        selected = next(
            (
                candidate
                for candidate in candidates
                if candidate.get("account_id") == request.account_id
                and candidate.get("active", True)
            ),
            None,
        )
        if selected is None:
            raise HTTPException(
                status_code=422,
                detail="La cuenta seleccionada ya no aparece como una coincidencia activa en Jira.",
            )
        try:
            updated = service.update_jira_assignee(
                proposal_id,
                row_id,
                selected,
                user.username,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"No existe la fila '{row_id}'.") from exc
        if updated is None:
            raise HTTPException(status_code=404, detail="Propuesta no encontrada.")
        return updated

    @app.post("/api/proposals/{proposal_id}/approve")
    def approve_proposal(
        proposal_id: str,
        user: AuthenticatedUser = Depends(require_user),
    ):
        proposal = service.approve_proposal(proposal_id, user.username)
        if proposal is None:
            raise HTTPException(status_code=404, detail="Propuesta no encontrada.")
        return proposal

    @app.post("/api/proposals/{proposal_id}/approve-and-dry-run")
    async def approve_and_generate_jira_dry_run(
        proposal_id: str,
        user: AuthenticatedUser = Depends(require_user),
    ):
        restore = getattr(app.state.atlassian_manager, "ensure_restored", None)
        if restore is not None:
            await restore(user.username)
        try:
            app.state.atlassian_manager.connected_snapshot(user.username)
        except AtlassianIntegrationError as exc:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Conecta Atlassian antes de aprobar. La propuesta no fue bloqueada "
                    "porque todavía no puede ejecutarse la prevalidación final."
                ),
            ) from exc
        proposal = service.approve_proposal(proposal_id, user.username)
        if proposal is None:
            raise HTTPException(status_code=404, detail="Propuesta no encontrada.")
        try:
            dry_run = await app.state.dry_run_service.generate(proposal, user.username)
        except AtlassianIntegrationError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"proposal": proposal, "dry_run": dry_run}

    @app.post("/api/proposals/{proposal_id}/reopen")
    def reopen_proposal(
        proposal_id: str,
        user: AuthenticatedUser = Depends(require_user),
    ):
        proposal = service.reopen_proposal(proposal_id, user.username)
        if proposal is None:
            raise HTTPException(status_code=404, detail="Propuesta no encontrada.")
        return proposal

    @app.get("/api/proposals/{proposal_id}/approved-export")
    def download_approved_proposal(
        proposal_id: str,
        _user: AuthenticatedUser = Depends(require_user),
    ):
        proposal = repository.get(proposal_id)
        if proposal is None:
            raise HTTPException(status_code=404, detail="Propuesta no encontrada.")
        if proposal["status"] != "APPROVED":
            raise ProposalStateError(
                "La descarga final solo está disponible para una propuesta aprobada."
            )
        lifecycle = repository.get_lifecycle(proposal_id)
        export = {
            "display_name": lifecycle.get("display_name")
            or proposal["source_file"]["name"].rsplit(".", 1)[0],
            "proposal": proposal,
        }
        safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", export["display_name"]).strip("_")
        safe_name = safe_name or "propuesta_aprobada"
        return Response(
            content=json.dumps(export, ensure_ascii=False, indent=2),
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="{safe_name}_v{proposal["version"]}.json"'
            },
        )

    @app.post("/api/proposals/{proposal_id}/dry-run")
    async def generate_jira_dry_run(
        proposal_id: str,
        user: AuthenticatedUser = Depends(require_user),
    ):
        proposal = repository.get(proposal_id)
        if proposal is None:
            raise HTTPException(status_code=404, detail="Propuesta no encontrada.")
        restore = getattr(app.state.atlassian_manager, "ensure_restored", None)
        if restore is not None:
            await restore(user.username)
        try:
            return await app.state.dry_run_service.generate(proposal, user.username)
        except AtlassianIntegrationError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/proposals/{proposal_id}/preflight")
    async def preflight_proposal(
        proposal_id: str,
        user: AuthenticatedUser = Depends(require_user),
    ):
        """Read-only Jira preflight immediately after upload; never approves or writes."""
        proposal = repository.get(proposal_id)
        if proposal is None:
            raise HTTPException(status_code=404, detail="La propuesta no existe.")
        preview = copy.deepcopy(proposal)
        preview["status"] = "APPROVED"
        try:
            return await app.state.dry_run_service.generate(preview, user.username)
        except AtlassianIntegrationError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/proposals/{proposal_id}/dry-run/latest")
    def get_latest_jira_dry_run(
        proposal_id: str,
        _user: AuthenticatedUser = Depends(require_user),
    ):
        proposal = repository.get(proposal_id)
        if proposal is None:
            raise HTTPException(status_code=404, detail="Propuesta no encontrada.")
        dry_run = repository.get_latest_dry_run(proposal_id)
        if dry_run is None:
            raise HTTPException(
                status_code=404,
                detail="La versión actual todavía no tiene un Dry run.",
            )
        return {
            **dry_run,
            "reused": True,
            "stale": dry_run["proposal_version"] != proposal["version"],
            "correction_workflow": build_correction_workflow(proposal, dry_run),
        }

    @app.get("/api/proposals/{proposal_id}/dry-run-evidence")
    def download_jira_dry_run_evidence(
        proposal_id: str,
        _user: AuthenticatedUser = Depends(require_user),
    ):
        proposal = repository.get(proposal_id)
        if proposal is None:
            raise HTTPException(status_code=404, detail="Propuesta no encontrada.")
        dry_run = repository.get_latest_dry_run(proposal_id)
        if dry_run is None:
            raise HTTPException(status_code=404, detail="Aún no existe evidencia de prevalidación.")
        lifecycle = repository.get_lifecycle(proposal_id)
        display_name = (
            lifecycle.get("display_name")
            or proposal["source_file"]["name"].rsplit(".", 1)[0]
        )
        evidence = {
            "objective": "3B.2",
            "mode": "DRY_RUN_NO_WRITE",
            "display_name": display_name,
            "proposal": proposal,
            "jira_prevalidation": dry_run,
        }
        safe_name = (
            re.sub(r"[^A-Za-z0-9_-]+", "_", display_name).strip("_")
            or "prevalidacion_jira"
        )
        return Response(
            content=json.dumps(evidence, ensure_ascii=False, indent=2),
            media_type="application/json",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{safe_name}_evidencia_3B2_'
                    f'v{dry_run["proposal_version"]}.json"'
                )
            },
        )

    @app.post("/api/proposals/{proposal_id}/objective-4a/prepare")
    async def prepare_objective_4a_simulation(
        proposal_id: str,
        request: JiraSimulationPrepareRequest,
        user: AuthenticatedUser = Depends(require_user),
    ):
        proposal = repository.get(proposal_id)
        if proposal is None:
            raise HTTPException(status_code=404, detail="Propuesta no encontrada.")
        dry_run = repository.get_latest_dry_run(proposal_id)
        if dry_run is None:
            raise Objective4AError("Ejecuta primero la prevalidacion final de Jira.")
        restore = getattr(app.state.atlassian_manager, "ensure_restored", None)
        if restore is not None:
            await restore(user.username)
        try:
            snapshot = app.state.atlassian_manager.connected_snapshot(user.username)
        except AtlassianIntegrationError as exc:
            raise Objective4AError(
                "Conecta Atlassian para preparar la simulacion con la identidad actual."
            ) from exc
        return app.state.objective_4a_service.prepare(
            proposal,
            dry_run,
            request.row_id,
            user.username,
            snapshot,
        )

    @app.post("/api/objectives/4a/executions/{execution_id}/confirm")
    def confirm_objective_4a_simulation(
        execution_id: str,
        request: JiraSimulationConfirmRequest,
        user: AuthenticatedUser = Depends(require_user),
    ):
        return app.state.objective_4a_service.confirm(
            execution_id,
            request.payload_hash,
            user.username,
        )

    @app.post("/api/objectives/4a/executions/{execution_id}/simulate")
    def run_objective_4a_simulation(
        execution_id: str,
        user: AuthenticatedUser = Depends(require_user),
    ):
        return app.state.objective_4a_service.simulate(execution_id, user.username)

    @app.post("/api/objectives/4a/executions/{execution_id}/cancel")
    def cancel_objective_4a_simulation(
        execution_id: str,
        user: AuthenticatedUser = Depends(require_user),
    ):
        return app.state.objective_4a_service.cancel(execution_id, user.username)

    @app.get("/api/proposals/{proposal_id}/objective-4a/latest")
    def get_latest_objective_4a_simulation(
        proposal_id: str,
        user: AuthenticatedUser = Depends(require_user),
    ):
        proposal = repository.get(proposal_id)
        if proposal is None:
            raise HTTPException(status_code=404, detail="Propuesta no encontrada.")
        intent = app.state.objective_4a_service.latest(proposal_id)
        if intent is None or intent.get("created_by") != user.username:
            raise HTTPException(
                status_code=404,
                detail="Esta propuesta aun no tiene una simulacion del Objetivo 4A.",
            )
        return intent

    @app.get("/api/objectives/4a/executions/{execution_id}/evidence")
    def download_objective_4a_evidence(
        execution_id: str,
        user: AuthenticatedUser = Depends(require_user),
    ):
        intent = repository.get_execution_intent(execution_id)
        if intent is None or intent.get("created_by") != user.username:
            raise HTTPException(status_code=404, detail="Evidencia no encontrada.")
        evidence = {
            "objective": "4A",
            "mode": "SIMULATION_ONLY",
            "jira_write_enabled": False,
            "write_performed": False,
            "execution": intent,
        }
        return Response(
            content=json.dumps(evidence, ensure_ascii=False, indent=2),
            media_type="application/json",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{execution_id}_evidencia_4A.json"'
                )
            },
        )

    @app.post("/api/objectives/4b/executions/{execution_id}/prepare")
    async def prepare_objective_4b_write(
        execution_id: str,
        user: AuthenticatedUser = Depends(require_user),
    ):
        restore = getattr(app.state.atlassian_manager, "ensure_restored", None)
        if restore is not None:
            await restore(user.username)
        try:
            snapshot = app.state.atlassian_manager.connected_snapshot(user.username)
            tools = app.state.atlassian_manager.objective_4_tool_readiness(user.username)
        except AtlassianIntegrationError as exc:
            raise Objective4BError("Conecta Atlassian antes de preparar el envio real.") from exc
        return app.state.objective_4b_service.prepare(
            execution_id,
            user.username,
            snapshot,
            tools,
        )

    @app.post("/api/objectives/4b/executions/{execution_id}/confirm")
    def confirm_objective_4b_write(
        execution_id: str,
        request: JiraRealConfirmRequest,
        user: AuthenticatedUser = Depends(require_user),
    ):
        return app.state.objective_4b_service.confirm(
            execution_id,
            request.payload_hash,
            request.confirmation_phrase,
            user.username,
        )

    @app.post("/api/objectives/4b/executions/{execution_id}/execute")
    async def execute_objective_4b_write(
        execution_id: str,
        user: AuthenticatedUser = Depends(require_user),
    ):
        assert_global_write_available(user.username)
        return await app.state.objective_4b_service.execute(execution_id, user.username)

    @app.get("/api/objectives/4b/executions/{execution_id}/evidence")
    def download_objective_4b_evidence(
        execution_id: str,
        user: AuthenticatedUser = Depends(require_user),
    ):
        intent = repository.get_execution_intent(execution_id)
        if intent is None or intent.get("created_by") != user.username:
            raise HTTPException(status_code=404, detail="Evidencia no encontrada.")
        if "real_execution" not in intent:
            raise HTTPException(status_code=404, detail="La ejecucion real aun no existe.")
        evidence = {
            "objective": "4B",
            "mode": "SINGLE_CONTROLLED_TASK",
            "automatic_retries": 0,
            "execution": intent,
        }
        return Response(
            content=json.dumps(evidence, ensure_ascii=False, indent=2),
            media_type="application/json",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{execution_id}_evidencia_4B.json"'
                )
            },
        )

    @app.post("/api/proposals/{proposal_id}/objective-4c1/prepare")
    async def prepare_objective_4c1_batch(
        proposal_id: str,
        request: JiraBatchPrepareRequest,
        user: AuthenticatedUser = Depends(require_user),
    ):
        restore = getattr(app.state.atlassian_manager, "ensure_restored", None)
        if restore is not None:
            await restore(user.username)
        try:
            snapshot = app.state.atlassian_manager.connected_snapshot(user.username)
            tools = app.state.atlassian_manager.objective_4_tool_readiness(user.username)
        except AtlassianIntegrationError as exc:
            raise Objective4C1Error("Conecta Atlassian antes de preparar el lote.") from exc
        return app.state.objective_4c1_service.prepare(
            proposal_id,
            request.row_ids,
            user.username,
            snapshot,
            tools,
        )

    @app.get("/api/proposals/{proposal_id}/objective-4c1/latest")
    def get_latest_objective_4c1_batch(
        proposal_id: str,
        user: AuthenticatedUser = Depends(require_user),
    ):
        intent = app.state.objective_4c1_service.latest(proposal_id)
        if intent is None or intent.get("created_by") != user.username:
            raise HTTPException(status_code=404, detail="Esta propuesta aun no tiene un lote controlado.")
        return intent

    @app.get("/api/proposals/{proposal_id}/objective-4c2/progress")
    def get_objective_4c2_progress(
        proposal_id: str,
        _user: AuthenticatedUser = Depends(require_user),
    ):
        return app.state.objective_4c1_service.progress(proposal_id)

    @app.post("/api/objectives/4c1/batches/{execution_id}/confirm")
    def confirm_objective_4c1_batch(
        execution_id: str,
        request: JiraBatchConfirmRequest,
        user: AuthenticatedUser = Depends(require_user),
    ):
        return app.state.objective_4c1_service.confirm(
            execution_id,
            request.payload_hash,
            request.confirmation_phrase,
            user.username,
        )

    @app.post("/api/objectives/4c1/batches/{execution_id}/revalidate")
    async def revalidate_objective_4c1_batch(
        execution_id: str,
        user: AuthenticatedUser = Depends(require_user),
    ):
        return await app.state.objective_4c1_service.revalidate(execution_id, user.username)

    @app.post("/api/objectives/4c1/batches/{execution_id}/execute")
    async def execute_objective_4c1_batch(
        execution_id: str,
        user: AuthenticatedUser = Depends(require_user),
    ):
        assert_global_write_available(user.username)
        result = await app.state.objective_4c1_service.execute(execution_id, user.username)
        intent = repository.get_execution_intent(execution_id)
        if intent and intent.get("proposal_id"):
            app.state.minute_drafts.sync_proposal_execution(intent["proposal_id"], user.username)
        return result

    @app.get("/api/objectives/4c1/batches/{execution_id}/evidence")
    def download_objective_4c1_evidence(
        execution_id: str,
        user: AuthenticatedUser = Depends(require_user),
    ):
        intent = repository.get_execution_intent(execution_id)
        if (
            intent is None
            or intent.get("objective") not in {"4C.1", "4D", "4E"}
            or intent.get("created_by") != user.username
        ):
            raise HTTPException(status_code=404, detail="Evidencia de lote no encontrada.")
        evidence = {
            "objective": intent.get("objective"),
            "mode": intent.get("mode"),
            "stop_on_first_failure": True,
            "automatic_retries": 0,
            "execution": intent,
        }
        return Response(
            content=json.dumps(evidence, ensure_ascii=False, indent=2),
            media_type="application/json",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{execution_id}_evidencia_{intent.get("objective", "4C1").replace(".", "")}.json"'
                )
            },
        )

    mount_frontend(app, settings.frontend_dist)
    return app


def mount_frontend(app: FastAPI, dist_path: Path) -> None:
    assets_path = dist_path / "assets"
    if assets_path.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_path), name="assets")

    index_path = dist_path / "index.html"
    if not index_path.exists():
        return

    @app.get("/")
    def frontend_index():
        return FileResponse(index_path)

    @app.get("/{path:path}")
    def frontend_fallback(path: str):
        candidate = dist_path / path
        if candidate.is_file() and dist_path in candidate.resolve().parents:
            return FileResponse(candidate)
        return FileResponse(index_path)


app = create_app()
