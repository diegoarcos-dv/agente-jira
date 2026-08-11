from __future__ import annotations

from pathlib import Path
import json
import re

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from .auth import AuthenticatedUser, AuthProvider, get_auth_provider, require_user
from .atlassian import AtlassianIntegrationError, AtlassianIntegrationManager
from .config import Settings, get_settings
from .corrections import build_correction_workflow
from .dry_run import JiraDryRunService
from .errors import ProposalStateError, WorkbookValidationError
from .execution_policy import load_execution_policy
from .models import (
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


MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def create_app(
    settings: Settings | None = None,
    atlassian_manager: AtlassianIntegrationManager | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    repository = ProposalRepository(settings.database_path)
    service = ProposalService(
        repository=repository,
        validator=ProposalSchemaValidator(settings.schema_path),
    )

    app = FastAPI(
        title="Agente Jira - MVP local",
        version="0.20.0",
        description=(
            "Genera propuestas Jira revisables desde la Plantilla Excel v1.1. "
            "Consulta metadatos Jira mediante OAuth 2.1 y Rovo MCP. La escritura "
            "permanece deshabilitada por defecto. Los modos explicitos 4B a 4E "
            "permiten lotes de hasta cinco actividades en AT, incluyendo Epic, "
            "Subtask y relaciones padre-hijo verificadas mediante lectura posterior."
        ),
    )
    app.state.settings = settings
    app.state.proposal_service = service
    app.state.atlassian_manager = atlassian_manager or AtlassianIntegrationManager(settings)
    app.state.jira_execution_policy = load_execution_policy(
        settings.jira_execution_policy_path,
        settings.jira_execution_policy_schema_path,
    )
    app.state.dry_run_service = JiraDryRunService(
        repository,
        app.state.atlassian_manager,
    )
    app.state.jira_simulator = SimulatedJiraCreateGateway()
    app.state.objective_4a_service = JiraExecutionPreparationService(
        repository,
        app.state.jira_execution_policy,
        app.state.jira_simulator,
    )
    app.state.objective_4b_service = JiraControlledExecutionService(
        repository,
        app.state.jira_execution_policy,
        app.state.atlassian_manager,
    )
    app.state.objective_4c1_service = JiraControlledBatchService(
        repository,
        app.state.jira_execution_policy,
        app.state.atlassian_manager,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(WorkbookValidationError)
    async def workbook_error_handler(_request, exc: WorkbookValidationError):
        return JSONResponse(
            status_code=422,
            content={
                "detail": exc.message,
                "issues": [issue.as_dict() for issue in exc.issues],
            },
        )

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
            "objective_4a_mode": "simulation_only",
            "template_version": "1.1",
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
                    if str(work_type.get("name") or "").lower() == name.lower()
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
        return provider.login(credentials)

    @app.get("/api/session")
    def session(user: AuthenticatedUser = Depends(require_user)):
        return {"username": user.username, "display_name": user.display_name}

    @app.get("/api/integrations/atlassian/status")
    async def atlassian_status(user: AuthenticatedUser = Depends(require_user)):
        restore = getattr(app.state.atlassian_manager, "ensure_restored", None)
        if restore is not None:
            await restore(user.username)
        status = app.state.atlassian_manager.status(user.username)
        status["jira_write_enabled"] = app.state.jira_execution_policy.jira_write_enabled
        status["write_tools_blocked"] = not app.state.jira_execution_policy.jira_write_enabled
        return status

    @app.post("/api/integrations/atlassian/connect")
    async def atlassian_connect(user: AuthenticatedUser = Depends(require_user)):
        try:
            return await app.state.atlassian_manager.begin_connect(user.username)
        except AtlassianIntegrationError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/api/integrations/atlassian/callback")
    async def atlassian_callback(
        code: str | None = Query(default=None),
        state: str | None = Query(default=None),
        error: str | None = Query(default=None),
    ):
        if error:
            await app.state.atlassian_manager.deny_callback(state)
            return RedirectResponse(url="/?atlassian=denied", status_code=303)
        if not code or not state:
            raise HTTPException(status_code=400, detail="Callback OAuth incompleto.")
        try:
            await app.state.atlassian_manager.finish_callback(code, state)
        except AtlassianIntegrationError as exc:
            return RedirectResponse(url="/?atlassian=error", status_code=303)
        return RedirectResponse(url="/?atlassian=connected", status_code=303)

    @app.post("/api/integrations/atlassian/disconnect")
    async def atlassian_disconnect(user: AuthenticatedUser = Depends(require_user)):
        await app.state.atlassian_manager.disconnect(user.username)
        return app.state.atlassian_manager.status(user.username)

    @app.post("/api/integrations/atlassian/refresh")
    async def atlassian_refresh(user: AuthenticatedUser = Depends(require_user)):
        try:
            return await app.state.atlassian_manager.refresh(user.username)
        except AtlassianIntegrationError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

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

    @app.get("/api/template")
    def download_template():
        return FileResponse(
            settings.frozen_template_path,
            filename="plantilla_plan_trabajo_jira_v1_1.xlsx",
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
        return service.create_from_workbook(
            filename=file.filename or "plantilla.xlsx",
            content=content,
            defaults=defaults,
            created_by=user.username,
        )

    @app.get("/api/proposals")
    def list_proposals(_user: AuthenticatedUser = Depends(require_user)):
        return [
            service.summarize(proposal, **lifecycle)
            for proposal, lifecycle in repository.list_latest_with_lifecycle()
        ]

    @app.post("/api/proposals/{proposal_id}/archive")
    def archive_proposal(
        proposal_id: str,
        user: AuthenticatedUser = Depends(require_user),
    ):
        archived_at = utc_now()
        if not repository.set_archived(
            proposal_id,
            archived_at=archived_at,
            archived_by=user.username,
        ):
            raise HTTPException(status_code=404, detail="Propuesta no encontrada.")
        proposal = repository.get(proposal_id)
        return service.summarize(
            proposal,
            archived_at=archived_at,
            archived_by=user.username,
        )

    @app.post("/api/proposals/{proposal_id}/restore")
    def restore_proposal(
        proposal_id: str,
        _user: AuthenticatedUser = Depends(require_user),
    ):
        if not repository.set_archived(
            proposal_id,
            archived_at=None,
            archived_by=None,
        ):
            raise HTTPException(status_code=404, detail="Propuesta no encontrada.")
        proposal = repository.get(proposal_id)
        return service.summarize(proposal)

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

    @app.post("/api/objectives/4c1/batches/{execution_id}/execute")
    async def execute_objective_4c1_batch(
        execution_id: str,
        user: AuthenticatedUser = Depends(require_user),
    ):
        return await app.state.objective_4c1_service.execute(execution_id, user.username)

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
