from __future__ import annotations

import hashlib
import json
import unicodedata
import asyncio
from time import perf_counter
from datetime import UTC, datetime
from typing import Any, Protocol

from .errors import ProposalStateError
from .hierarchy import JiraHierarchyError, validate_parent_relation
from .repository import ProposalRepository
from .sprints import resolve_sprint
from .performance import current_trace


class JiraReadGateway(Protocol):
    def connected_snapshot(self, username: str) -> dict[str, Any]: ...

    async def find_assignees(
        self, username: str, space: str, query: str
    ) -> list[dict[str, Any]]: ...

    async def list_sprints(
        self, username: str, space: str, *, force_refresh: bool = False
    ) -> list[dict[str, Any]]: ...


WORK_TYPE_ALIASES = {
    "epic": {"epic"},
    "story": {"story", "historia"},
    "task": {"task", "tarea"},
    "bug": {"bug", "defecto", "incidencia"},
    "subtask": {"subtask", "sub task", "sub tarea", "subtarea"},
}

FIELD_ALIASES = {
    "project": {"project", "proyecto"},
    "issuetype": {"issuetype", "issue type", "tipo de incidencia", "tipo de trabajo"},
    "summary": {"summary", "resumen", "titulo"},
    "description": {"description", "descripcion"},
    "assignee": {"assignee", "responsable", "asignado"},
    "reporter": {"reporter", "informador", "creador"},
    "parent": {"parent", "padre"},
    "due_date": {"duedate", "due date", "fecha de vencimiento", "fecha objetivo"},
    "iniciativa": {"iniciativa", "initiative"},
    "linea_trabajo": {"linea de trabajo", "linea trabajo", "workstream"},
    "sprint": {"sprint"},
    "tipo_seguimiento": {"tipo de seguimiento", "tipo seguimiento"},
    "semaforo": {"semaforo", "traffic light"},
}


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _normalize(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(character for character in text if not unicodedata.combining(character))
    return " ".join("".join(character if character.isalnum() else " " for character in text.lower()).split())


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _field_kind(field: dict[str, Any]) -> str | None:
    candidates = {_normalize(field.get("id")), _normalize(field.get("name"))}
    for kind, aliases in FIELD_ALIASES.items():
        if candidates.intersection({_normalize(alias) for alias in aliases}):
            return kind
    return None


def _work_type_matches(requested: str, actual: str | None) -> bool:
    requested_key = _normalize(requested).replace(" ", "")
    actual_value = _normalize(actual)
    aliases = WORK_TYPE_ALIASES.get(requested_key, {_normalize(requested)})
    return actual_value in {_normalize(alias) for alias in aliases}


class JiraDryRunService:
    """Builds an immutable execution preview using only Jira read capabilities."""

    def __init__(
        self,
        repository: ProposalRepository,
        jira: JiraReadGateway,
        *,
        read_concurrency: int = 4,
    ):
        self.repository = repository
        self.jira = jira
        self.read_concurrency = max(1, min(8, int(read_concurrency)))

    async def generate(
        self,
        proposal: dict[str, Any],
        username: str,
    ) -> dict[str, Any]:
        if proposal["status"] != "APPROVED":
            raise ProposalStateError(
                "El Dry run sólo puede generarse para una propuesta aprobada y bloqueada."
            )

        trace = current_trace()
        if trace is not None:
            trace.proposal_id = str(proposal.get("proposal_id"))
            trace.activity_count = len(proposal.get("items", []))
        started_total = perf_counter()
        snapshot_started = perf_counter()
        snapshot = self.jira.connected_snapshot(username)
        if trace is not None:
            trace.record_cache_event("jira_snapshot", cache_status="HIT", phase="snapshot_jira", proposal_id=str(proposal.get("proposal_id")))
            trace.record_phase("snapshot_jira", (perf_counter() - snapshot_started) * 1000)
        proposal_hash = _canonical_hash(proposal)
        spaces = {space["key"]: space for space in snapshot.get("spaces", [])}
        rows = {
            item["generated"]["row_id"]: item
            for item in proposal["items"]
        }
        assignee_cache: dict[tuple[str, str], list[dict[str, Any]]] = {}
        assignee_cache_errors: dict[tuple[str, str], str] = {}
        sprint_cache: dict[str, list[dict[str, Any]]] = {}
        sprint_cache_errors: dict[str, str] = {}
        await self._prefetch_reads(
            proposal,
            username,
            spaces,
            assignee_cache,
            assignee_cache_errors,
            sprint_cache,
            sprint_cache_errors,
        )
        items: list[dict[str, Any]] = []

        for item in proposal["items"]:
            generated = item["generated"]
            row_id = generated["row_id"]
            if generated["decision"] == "EXCLUIR":
                items.append(
                    {
                        "row_id": row_id,
                        "source_row": item["source"]["source_row"],
                        "status": "SKIPPED",
                        "title": generated["title"],
                        "space": generated["space"],
                        "work_type": generated["work_type"],
                        "errors": [],
                        "warnings": [
                            {
                                "code": "EXCLUDED_BY_APPROVED_PROPOSAL",
                                "field": "decision",
                                "message": "La versión aprobada excluye esta actividad de cualquier ejecución.",
                            }
                        ],
                        "target": None,
                        "assignee": None,
                        "logical_payload": None,
                        "idempotency_key": None,
                    }
                )
                continue

            errors: list[dict[str, str]] = []
            warnings: list[dict[str, str]] = []
            space_key = generated["space"]
            work_type_started = perf_counter()
            space = spaces.get(space_key)
            if space is None or not space.get("found"):
                errors.append(self._issue("SPACE_NOT_VISIBLE", "space", f"El Space {space_key} no está visible en Jira."))
                work_type = None
            else:
                work_type = next(
                    (
                        candidate
                        for candidate in space.get("work_types", [])
                        if _work_type_matches(generated["work_type"], candidate.get("name"))
                    ),
                    None,
                )
                if work_type is None:
                    errors.append(
                        self._issue(
                            "WORK_TYPE_NOT_AVAILABLE",
                            "work_type",
                            f"{generated['work_type']} no existe en el Space {space_key}.",
                        )
                    )

            fields = (work_type or {}).get("fields", [])
            if work_type is not None and not fields:
                errors.append(
                    self._issue(
                        "WORK_TYPE_FIELDS_UNAVAILABLE",
                        "work_type",
                        f"Jira no devolvió metadatos de campos para {work_type.get('name')} en {space_key}.",
                    )
                )
            if trace is not None:
                trace.record_phase("work_type_fields", (perf_counter() - work_type_started) * 1000)

            if not str(generated.get("title") or "").strip():
                errors.append(self._issue("TITLE_REQUIRED", "title", "El título está vacío."))
            if not str(generated.get("description") or "").strip():
                errors.append(self._issue("DESCRIPTION_REQUIRED", "description", "La descripción está vacía."))
            if not str(generated.get("fields", {}).get("tipo_seguimiento") or "").strip():
                issue = self._issue(
                    "TRACKING_TYPE_REQUIRED",
                    "tipo_seguimiento",
                    "La normativa requiere Tipo de seguimiento antes de enviar a Jira.",
                )
                tracking_field = next(
                    (field for field in fields if _field_kind(field) == "tipo_seguimiento"), None
                )
                if tracking_field and isinstance(tracking_field.get("options"), list):
                    issue["options"] = [
                        {"value": option.get("value") or option.get("label"), "jira_id": option.get("jira_id")}
                        for option in tracking_field["options"]
                        if isinstance(option, dict) and (option.get("value") or option.get("label"))
                    ]
                errors.append(issue)

            assignee_result = await self._resolve_assignee(
                username,
                space_key,
                generated.get("assignee") or {},
                assignee_cache,
                assignee_cache_errors=assignee_cache_errors,
                row_id=row_id,
            )
            errors.extend(assignee_result["errors"])
            warnings.extend(assignee_result["warnings"])
            assignee = assignee_result["assignee"]

            if assignee and assignee.get("validation") == "JIRA_ACCOUNT_MATCH":
                constraint_key = f"{space_key}:{(work_type or {}).get('id')}"
                allowed_by_work_type = snapshot.get("_assignee_allowed_accounts", {})
                if constraint_key in allowed_by_work_type:
                    if assignee.get("account_id") in allowed_by_work_type[constraint_key]:
                        assignee["validation"] = "JIRA_ASSIGNABLE_USER_MATCH"
                    else:
                        errors.append(
                            self._issue(
                                "ASSIGNEE_NOT_ASSIGNABLE",
                                "assignee",
                                f"La cuenta de '{assignee.get('display_name')}' no aparece entre los valores asignables de este Work Type.",
                            )
                        )
                else:
                    warnings.append(
                        self._issue(
                            "ASSIGNEE_ASSIGNABILITY_UNVERIFIED",
                            "assignee",
                            "Rovo confirmó la cuenta, pero su MCP público no permite comprobar si es asignable en este Space y Work Type. Esta advertencia no bloquea el Dry run sin escritura; será una validación obligatoria antes de crear actividades.",
                        )
                    )

            field_kinds = {_field_kind(field) for field in fields}
            if fields and "assignee" not in field_kinds:
                errors.append(
                    self._issue(
                        "ASSIGNEE_FIELD_UNAVAILABLE",
                        "assignee",
                        f"El Work Type {generated['work_type']} no permite establecer Responsable.",
                    )
                )

            parent_row_id = generated.get("parent_row_id")
            try:
                validate_parent_relation(
                    row_id,
                    generated["work_type"],
                    parent_row_id,
                    rows,
                    require_included=True,
                )
            except JiraHierarchyError as exc:
                errors.append(
                    self._issue(
                        "SUBTASK_PARENT_REQUIRED"
                        if generated["work_type"] == "Subtask" and not parent_row_id
                        else "PARENT_RELATION_INVALID",
                        "parent_row_id",
                        str(exc),
                    )
                )

            values = {
                "project": space_key,
                "issuetype": (work_type or {}).get("id"),
                "summary": generated.get("title"),
                "description": generated.get("description"),
                "assignee": (assignee or {}).get("account_id"),
                "reporter": snapshot.get("atlassian_user", {}).get("account_id"),
                "parent": parent_row_id,
                "due_date": generated.get("fields", {}).get("due_date"),
                "iniciativa": generated.get("fields", {}).get("iniciativa"),
                "linea_trabajo": generated.get("fields", {}).get("linea_trabajo"),
                "sprint": generated.get("fields", {}).get("sprint"),
                "tipo_seguimiento": generated.get("fields", {}).get("tipo_seguimiento"),
                "semaforo": generated.get("fields", {}).get("semaforo"),
            }
            sprint_resolution = None
            sprint_field = next(
                (field for field in fields if _field_kind(field) == "sprint"),
                None,
            )
            if sprint_field is not None:
                list_sprints = getattr(self.jira, "list_sprints", None)
                if list_sprints is None:
                    errors.append(
                        self._issue(
                            "SPRINT_CATALOG_UNAVAILABLE",
                            "sprint",
                            "La integracion Jira no permite recuperar el catalogo vigente de Sprints.",
                        )
                    )
                else:
                    if space_key not in sprint_cache:
                        try:
                            sprint_cache[space_key] = await list_sprints(
                                username,
                                space_key,
                                force_refresh=True,
                            )
                        except Exception as exc:
                            sprint_cache_errors[space_key] = str(exc)[:240]
                            sprint_cache[space_key] = []
                    elif trace is not None:
                        trace.record_cache_event("list_sprints", cache_status="HIT", phase="catalog_sprint", proposal_id=str(proposal.get("proposal_id")), row_id=row_id)
                    if space_key in sprint_cache_errors:
                        errors.append(
                            self._issue(
                                "SPRINT_CATALOG_UNAVAILABLE",
                                "sprint",
                                "No fue posible recuperar los Sprints vigentes de Jira: "
                                + sprint_cache_errors[space_key],
                            )
                        )
                    else:
                        sprint_resolution = resolve_sprint(values.get("sprint"), sprint_cache[space_key])
                        if sprint_resolution.get("error"):
                            errors.append(sprint_resolution["error"])
                        if sprint_resolution.get("warning"):
                            warnings.append(sprint_resolution["warning"])
                        selected_sprint = sprint_resolution.get("selected")
                        values["sprint"] = selected_sprint.get("id") if selected_sprint else None
            field_validation_started = perf_counter()
            for field in fields:
                kind = _field_kind(field)
                selected_value = values.get(kind) if kind else None
                if kind == "sprint":
                    continue
                options = field.get("options")
                if not selected_value or not isinstance(options, list) or not options:
                    continue
                allowed = {
                    _normalize(option.get("value") or option.get("label"))
                    for option in options
                    if isinstance(option, dict)
                }
                if _normalize(selected_value) not in allowed:
                    issue = self._issue(
                        "FIELD_VALUE_NOT_ALLOWED",
                        kind,
                        f"El valor '{selected_value}' ya no aparece entre las opciones vigentes de '{field.get('name') or kind}' en Jira.",
                    )
                    option_details = [
                        {"value": option.get("value") or option.get("label"), "jira_id": option.get("jira_id")}
                        for option in options
                        if isinstance(option, dict) and (option.get("value") or option.get("label"))
                    ]
                    if any(option.get("jira_id") for option in option_details):
                        issue["options"] = option_details
                    errors.append(issue)
            for field in fields:
                if not field.get("required"):
                    continue
                kind = _field_kind(field)
                if kind is None:
                    errors.append(
                        self._issue(
                            "REQUIRED_FIELD_UNMAPPED",
                            str(field.get("id") or field.get("name") or "unknown"),
                            f"El campo obligatorio '{field.get('name') or field.get('id')}' no tiene un mapeo seguro.",
                        )
                    )
                elif not values.get(kind):
                    errors.append(
                        self._issue(
                            "REQUIRED_FIELD_MISSING",
                            kind,
                            f"Falta un valor para el campo obligatorio '{field.get('name') or kind}'.",
                        )
                    )

            if trace is not None:
                trace.record_phase("tracking_global_fields", (perf_counter() - field_validation_started) * 1000)

            mapped_fields = {
                str(field.get("id")): values.get(kind)
                for field in fields
                if (kind := _field_kind(field))
                and kind != "parent"
                and values.get(kind) is not None
            }
            logical_payload = {
                "project_key": space_key,
                "project_id": (space or {}).get("id"),
                "work_type": (work_type or {}).get("name") or generated["work_type"],
                "work_type_id": (work_type or {}).get("id"),
                "summary": generated.get("title"),
                "description": generated.get("description"),
                "assignee_account_id": (assignee or {}).get("account_id"),
                "parent_row_id": parent_row_id,
                "jira_fields": mapped_fields,
            }
            item_fingerprint = {
                "proposal_hash": proposal_hash,
                "row_id": row_id,
                "logical_payload": logical_payload,
            }
            idempotency_key = f"AJI-{_canonical_hash(item_fingerprint)[:32]}"
            item_status = "BLOCKED" if errors else (
                "READY_WITH_WARNINGS" if warnings else "READY"
            )
            items.append(
                {
                    "row_id": row_id,
                    "source_row": item["source"]["source_row"],
                    "status": item_status,
                    "title": generated["title"],
                    "space": space_key,
                    "work_type": generated["work_type"],
                    "parent_row_id": parent_row_id,
                    "errors": errors,
                    "warnings": warnings,
                    "target": {
                        "project_name": (space or {}).get("name"),
                        "project_type": (space or {}).get("project_type"),
                        "jira_work_type": (work_type or {}).get("name"),
                        "required_field_count": len([field for field in fields if field.get("required")]),
                    },
                    "assignee": assignee,
                    "sprint_resolution": sprint_resolution,
                    "logical_payload": logical_payload,
                    "idempotency_key": idempotency_key,
                }
            )

        ready = sum(item["status"] == "READY" for item in items)
        ready_with_warnings = sum(
            item["status"] == "READY_WITH_WARNINGS" for item in items
        )
        blocked = sum(item["status"] == "BLOCKED" for item in items)
        skipped = sum(item["status"] == "SKIPPED" for item in items)
        stable_manifest = {
            "proposal_id": proposal["proposal_id"],
            "proposal_version": proposal["version"],
            "proposal_hash": proposal_hash,
            "site_url": snapshot.get("site_url"),
            "items": [
                {
                    "row_id": item["row_id"],
                    "status": item["status"],
                    "idempotency_key": item["idempotency_key"],
                    "logical_payload": item["logical_payload"],
                    "sprint_resolution": item.get("sprint_resolution"),
                    "errors": item["errors"],
                    "warnings": item["warnings"],
                }
                for item in items
            ],
        }
        dry_run_id = f"DRY-{_canonical_hash(stable_manifest)[:32]}"
        document = {
            "dry_run_id": dry_run_id,
            "proposal_id": proposal["proposal_id"],
            "proposal_version": proposal["version"],
            "proposal_hash": proposal_hash,
            "generated_at": _utc_now(),
            "generated_by": username,
            "jira_snapshot_verified_at": snapshot.get("verified_at"),
            "site_url": snapshot.get("site_url"),
            "status": "BLOCKED" if blocked else (
                "READY_WITH_WARNINGS" if ready_with_warnings else "READY"
            ),
            "summary": {
                "ready": ready,
                "ready_with_warnings": ready_with_warnings,
                "blocked": blocked,
                "skipped": skipped,
            },
            "items": items,
            "write_performed": False,
        }
        stored, reused = self.repository.save_dry_run(document)
        if trace is not None:
            trace.record_phase("dry_run", (perf_counter() - started_total) * 1000)
        return {**stored, "reused": reused}

    async def _resolve_assignee(
        self,
        username: str,
        space: str,
        requested: dict[str, Any],
        cache: dict[tuple[str, str], list[dict[str, Any]]],
        *,
        assignee_cache_errors: dict[tuple[str, str], str] | None = None,
        row_id: str | None = None,
    ) -> dict[str, Any]:
        display_name = str(requested.get("display_name") or "").strip()
        email = str(requested.get("email") or "").strip()
        query = email if email and not email.lower().endswith("@example.com") else display_name
        if not query:
            return {
                "assignee": None,
                "errors": [self._issue("ASSIGNEE_REQUIRED", "assignee", "No existe un responsable para buscar en Jira.")],
                "warnings": [],
            }
        key = (space, _normalize(query))
        if key not in cache:
            cache[key] = await self.jira.find_assignees(username, space, query)
        else:
            trace = current_trace()
            if trace is not None:
                trace.record_cache_event("find_assignees", cache_status="HIT", phase="assignee_resolution", row_id=row_id)
        if assignee_cache_errors and key in assignee_cache_errors:
            return {
                "assignee": None,
                "errors": [
                    self._issue(
                        "ASSIGNEE_LOOKUP_UNAVAILABLE",
                        "assignee",
                        "No fue posible consultar responsables en Jira: "
                        + assignee_cache_errors[key],
                    )
                ],
                "warnings": [],
            }
        candidates = cache[key]
        exact = [
            candidate
            for candidate in candidates
            if (
                email
                and candidate.get("email")
                and _normalize(candidate.get("email")) == _normalize(email)
            )
            or _normalize(candidate.get("display_name")) == _normalize(display_name)
        ]
        if len(exact) == 0:
            return {
                "assignee": None,
                "errors": [
                    self._issue(
                        "ASSIGNEE_NOT_FOUND",
                        "assignee",
                        f"No se encontró una coincidencia exacta y activa para '{display_name}' en Jira.",
                    )
                ],
                "warnings": [],
            }
        if len(exact) > 1:
            return {
                "assignee": None,
                "errors": [self._issue("ASSIGNEE_AMBIGUOUS", "assignee", f"Jira devolvió más de una coincidencia para '{display_name}'.")],
                "warnings": [],
            }
        candidate = exact[0]
        if not candidate.get("active", True):
            return {
                "assignee": None,
                "errors": [self._issue("ASSIGNEE_INACTIVE", "assignee", f"'{display_name}' está inactivo en Jira.")],
                "warnings": [],
            }
        assignability_verified = candidate.get("capability") == "findAssignableUsers"
        return {
            "assignee": {
                "display_name": candidate.get("display_name"),
                "email": candidate.get("email"),
                "account_id": candidate.get("account_id"),
                "validation": (
                    "JIRA_ASSIGNABLE_USER_MATCH"
                    if assignability_verified
                    else "JIRA_ACCOUNT_MATCH"
                ),
            },
            "errors": [],
            "warnings": [],
        }

    async def _prefetch_reads(
        self,
        proposal: dict[str, Any],
        username: str,
        spaces: dict[str, dict[str, Any]],
        assignee_cache: dict[tuple[str, str], list[dict[str, Any]]],
        assignee_cache_errors: dict[tuple[str, str], str],
        sprint_cache: dict[str, list[dict[str, Any]]],
        sprint_cache_errors: dict[str, str],
    ) -> None:
        """Resolve independent read-only catalogs once, with bounded concurrency.

        This is deliberately request-scoped. It never caches credentials, write
        authorization, preflight results, or idempotency decisions across requests.
        """
        trace = current_trace()
        started = perf_counter()
        assignee_queries: dict[tuple[str, str], tuple[str, str]] = {}
        sprint_spaces: set[str] = set()
        list_sprints = getattr(self.jira, "list_sprints", None)
        for item in proposal.get("items", []):
            generated = item.get("generated") or {}
            if generated.get("decision") == "EXCLUIR":
                continue
            space_key = str(generated.get("space") or "")
            requested = generated.get("assignee") or {}
            display_name = str(requested.get("display_name") or "").strip()
            email = str(requested.get("email") or "").strip()
            query = email if email and not email.lower().endswith("@example.com") else display_name
            if query:
                assignee_queries.setdefault(
                    (space_key, _normalize(query)),
                    (space_key, query),
                )
            space = spaces.get(space_key)
            work_type = next(
                (
                    candidate
                    for candidate in (space or {}).get("work_types", [])
                    if _work_type_matches(generated.get("work_type", ""), candidate.get("name"))
                ),
                None,
            )
            if list_sprints is not None and any(
                _field_kind(field) == "sprint" for field in (work_type or {}).get("fields", [])
            ):
                sprint_spaces.add(space_key)

        semaphore = asyncio.Semaphore(self.read_concurrency)

        async def fetch_assignee(key: tuple[str, str], request: tuple[str, str]) -> None:
            space_key, query = request
            async with semaphore:
                try:
                    assignee_cache[key] = await self.jira.find_assignees(username, space_key, query)
                except Exception as exc:
                    assignee_cache_errors[key] = str(exc)[:240]
                    assignee_cache[key] = []

        async def fetch_sprints(space_key: str) -> None:
            async with semaphore:
                try:
                    sprint_cache[space_key] = await list_sprints(
                        username,
                        space_key,
                        force_refresh=True,
                    )
                except Exception as exc:
                    sprint_cache_errors[space_key] = str(exc)[:240]
                    sprint_cache[space_key] = []

        tasks = [
            fetch_assignee(key, request)
            for key, request in assignee_queries.items()
        ]
        if list_sprints is not None:
            tasks.extend(fetch_sprints(space_key) for space_key in sorted(sprint_spaces))
        if tasks:
            await asyncio.gather(*tasks)
        if trace is not None:
            trace.record_phase("read_prefetch", (perf_counter() - started) * 1000)

    @staticmethod
    def _issue(code: str, field: str, message: str) -> dict[str, Any]:
        return {"code": code, "field": field, "message": message}
