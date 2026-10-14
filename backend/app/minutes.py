from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import unicodedata
from datetime import date as CalendarDate, datetime, timezone
from difflib import SequenceMatcher
from time import perf_counter
from typing import Literal
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .config import Settings
from .minutes_prompt import prompt_for
from .minutes_deterministic import extract_explicit
from .minutes_semantic import (SEMANTIC_PROMPT_VERSION, SemanticCandidate,
                               extract_rule_candidates, parse_llm_response)

logger = logging.getLogger(__name__)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class MinutesRequest(StrictModel):
    text: str = Field(max_length=100000)
    output: Literal["proposal", "draft"] = "proposal"


class Participant(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    role: str | None = Field(default=None, max_length=200)


class MinutesActivity(StrictModel):
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=3, max_length=4000)
    responsible_candidate: str | None = Field(default=None, max_length=200)
    responsible_role: str | None = Field(default=None, max_length=80)
    responsible_evidence: str | None = Field(default=None, max_length=2000)
    collaborators: list[str] = Field(default_factory=list, max_length=10)
    collaborators_evidence: str | None = Field(default=None, max_length=2000)
    area_candidate: str | None = Field(default=None, max_length=200)
    area_evidence: str | None = Field(default=None, max_length=2000)
    activity_evidence: str | None = Field(default=None, max_length=2000)
    due_date_candidate: CalendarDate | None = None
    due_date_evidence: str | None = Field(default=None, max_length=2000)
    project_or_front: str | None = Field(default=None, max_length=300)
    source_section: str | None = Field(default=None, max_length=200)
    source_evidence: str = Field(min_length=10, max_length=4000)
    work_type_candidate: Literal["Task", "Bug", "Story"] = "Task"
    inferred: bool = False
    requires_review: bool = True
    extraction_source: Literal["deterministic", "semantic_rule", "semantic_llm", "merged"] = "deterministic"


class MinutesDocument(StrictModel):
    document_type: Literal["meeting_minutes", "notes", "email", "agreements"]
    date: CalendarDate | None = None
    project: str | None = Field(default=None, max_length=300)
    # Document-level context. It must never become the assignee of an activity
    # unless the activity has its own supported attribution.
    project_responsible: str | None = Field(default=None, max_length=200)
    project_responsible_evidence: str | None = Field(default=None, max_length=2000)
    objective: str | None = Field(default=None, max_length=2000)
    participants: list[Participant] = Field(default_factory=list, max_length=100)
    # An explicit section may legitimately contain no actions (dataset E).
    # The UI can then ask for clarification without inventing a task.
    activities: list[MinutesActivity] = Field(default_factory=list, max_length=50)


class MinutesError(Exception):
    def __init__(self, message: str, status_code: int = 422, *, code: str = "MINUTES_ANALYSIS_FAILED",
                 retryable: bool = False, ollama_status: int | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.retryable = retryable
        self.ollama_status = ollama_status


def normalize_text(text: str) -> tuple[str, int]:
    text = unicodedata.normalize("NFKC", text).replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[^\S\n]+", " ", line).strip() for line in text.splitlines()]
    text = "\n".join(lines).strip()
    removed = 0
    # Whole documents repeated consecutively, including copies without blank separators.
    while len(text) > 1:
        midpoint = len(text) // 2
        left, right = text[:midpoint].strip(), text[midpoint:].strip()
        if left != right:
            break
        text = left
        removed += 1
    blocks = re.split(r"\n\s*\n", text)
    seen, unique = set(), []
    for block in blocks:
        # Do not drop short headers that might introduce a different section.
        if len(block) >= 80 and block in seen:
            removed += 1
            continue
        seen.add(block)
        unique.append(block)
    return "\n\n".join(unique), removed


def canonical(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip().casefold()


def date_supported(value: CalendarDate, evidence: str) -> bool:
    # Conservative: unsupported/relative dates remain empty and require review.
    months = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
    formats = [value.isoformat(), value.strftime("%d/%m/%Y"),
               f"{value.day}/{value.month}/{value.year}",
               f"{value.day} de {months[value.month - 1]} de {value.year}"]
    return any(canonical(candidate) in canonical(evidence) for candidate in formats)


def validate_extraction(document: MinutesDocument, text: str) -> tuple[MinutesDocument, list[str], list[list[str]]]:
    document = document.model_copy(deep=True)
    warnings: list[str] = []
    if document.date and not date_supported(document.date, text):
        document.date = None
        warnings.append("Fecha del documento no sustentada; por confirmar.")
    if document.project_responsible:
        evidence = document.project_responsible_evidence or ""
        project_role = re.search(
            r"\b(responsable\s+(?:del|de la)\s+(?:proyecto|frente)|l[ií]der\s+(?:del|de la)\s+(?:proyecto|frente)|project\s+(?:owner|manager))\b",
            canonical(evidence),
        )
        if not (evidence and project_role and canonical(evidence) in canonical(text)
                and canonical(document.project_responsible) in canonical(evidence)):
            document.project_responsible = None
            document.project_responsible_evidence = None
            warnings.append("Responsable del proyecto no sustentado explícitamente; por confirmar.")
    document.participants = [p for p in document.participants if canonical(p.name) in canonical(text)]
    unique: list[MinutesActivity] = []
    activity_warnings: list[list[str]] = []
    signatures = set()
    for activity in document.activities:
        if canonical(activity.source_evidence) not in canonical(text):
            raise MinutesError("No pude estructurar esta minuta con suficiente seguridad. La evidencia no coincide con el documento.",
                               code="MINUTES_EVIDENCE_INVALID")
        notes: list[str] = []
        if activity.source_section and canonical(activity.source_section) not in canonical(text):
            activity.source_section = None
            notes.append("Sección de origen por confirmar.")
        if activity.responsible_candidate:
            evidence = activity.responsible_evidence or ""
            # Names in participant lists or unrelated paragraphs cannot assign actions.
            attributed = re.search(r"\b(responsable|a cargo|asignad[oa]|se compromete|realizará|realizara|deberá|debera|confirmará|confirmara|coordinará|coordinara|ejecutará|ejecutara|encargale|encárgale|hará|hara|haga|revisará|revisara|revise|cheque|implementará|implementara|implemente|preparará|preparara|prepara|valida)\b", canonical(evidence))
            if not (evidence and attributed and canonical(evidence) in canonical(activity.source_evidence)
                    and canonical(activity.responsible_candidate) in canonical(evidence)):
                activity.responsible_candidate = None
                activity.responsible_evidence = None
                notes.append("Responsable no atribuido explícitamente a esta acción; por definir.")
        if activity.due_date_candidate:
            evidence = activity.due_date_evidence or ""
            deadline = re.search(r"\b(entrega|límite|limite|antes del|fecha objetivo|para el|a más tardar|vence|tiene que quedar|debe quedar|para)\b", canonical(evidence))
            if not (evidence and deadline and canonical(evidence) in canonical(activity.source_evidence)
                    and date_supported(activity.due_date_candidate, evidence)):
                activity.due_date_candidate = None
                activity.due_date_evidence = None
                notes.append("Fecha objetivo no sustentada como plazo de esta acción; por definir.")
        signature = (canonical(activity.title), canonical(activity.source_evidence),
                     activity.responsible_candidate, activity.due_date_candidate, activity.project_or_front)
        if signature in signatures:
            warnings.append("Se omitió una actividad exactamente duplicada.")
            continue
        signatures.add(signature)
        for index, other in enumerate(unique):
            if (canonical(other.source_evidence) == canonical(activity.source_evidence)
                    or SequenceMatcher(None, canonical(other.title), canonical(activity.title)).ratio() >= .78):
                notes.append("Posible duplicado; comparar el origen antes de incluir.")
                activity_warnings[index].append("Posible duplicado; comparar el origen antes de incluir.")
        if activity.inferred:
            notes.append("Acción inferida del contexto; confirma que es un compromiso vigente.")
        activity.requires_review = True
        unique.append(activity)
        activity_warnings.append(notes)
    document.activities = unique
    return document, list(dict.fromkeys(warnings)), activity_warnings


def _semantic_activity(candidate: SemanticCandidate) -> MinutesActivity:
    collaborators = list(dict.fromkeys(candidate.collaborators))
    context = candidate.context
    if collaborators and not context:
        context = "Coordinar la actividad con " + ", ".join(collaborators) + "."
    return MinutesActivity(
        title=candidate.title,
        description=(context or candidate.evidence)[:4000],
        responsible_candidate=candidate.responsible_name,
        responsible_role=candidate.responsible_role,
        responsible_evidence=candidate.responsible_evidence or (candidate.evidence if candidate.responsible_name else None),
        collaborators=collaborators,
        collaborators_evidence=candidate.collaborators_evidence,
        area_candidate=candidate.area,
        area_evidence=candidate.area_evidence,
        activity_evidence=candidate.activity_evidence,
        due_date_candidate=candidate.due_date,
        due_date_evidence=candidate.evidence if candidate.due_date else None,
        project_or_front=candidate.project,
        source_section=None,
        source_evidence=candidate.evidence,
        work_type_candidate="Task",
        inferred=candidate.source != "semantic_rule",
        requires_review=True,
        extraction_source=candidate.source if candidate.source in {"semantic_rule", "semantic_llm"} else "semantic_rule",
    )


def _merge_activities(deterministic: list[MinutesActivity], semantic: list[MinutesActivity]) -> list[MinutesActivity]:
    """Keep deterministic facts and avoid adding the same commitment twice."""
    result = list(deterministic)
    for incoming in semantic:
        match = next((existing for existing in result if
                      SequenceMatcher(None, canonical(existing.title), canonical(incoming.title)).ratio() >= .82
                      and canonical(existing.responsible_candidate or "") == canonical(incoming.responsible_candidate or "")
                      and existing.due_date_candidate == incoming.due_date_candidate), None)
        if match is None:
            result.append(incoming)
            continue
        # Literal extraction wins for fields it already substantiates. Preserve
        # collaborators only as explanatory context, never as Jira assignees.
        if not match.collaborators and incoming.collaborators:
            match.collaborators = incoming.collaborators
            if incoming.description and incoming.description not in match.description:
                match.description = (match.description + " " + incoming.description)[:4000]
        match.extraction_source = "merged"
    return result


class MinutesService:
    def __init__(self, settings: Settings, proposal_service, transport=None):
        self.settings = settings
        self.proposals = proposal_service
        self.transport = transport
        self._active = False
        self._enrichment_tasks: dict[str, asyncio.Task] = {}
        self._semantic_cache: dict[tuple[str, str, str], list[SemanticCandidate]] = {}

    def _client(self):
        return httpx.AsyncClient(base_url=self.settings.ollama_base_url,
            timeout=5, trust_env=False, follow_redirects=False, transport=self.transport)

    def _uses_deterministic_hybrid(self) -> bool:
        # Deployments that explicitly retain the old v1/v2 prompt preserve the
        # legacy end-to-end behavior. The new default always starts from rules.
        return self.settings.minutes_prompt_version == SEMANTIC_PROMPT_VERSION

    async def _semantic_model_candidates(self, normalized: str, document_hash: str) -> list[SemanticCandidate]:
        """Ask Ollama for a strict semantic proposal; failures intentionally fall back."""
        key = (document_hash, self.settings.minutes_llm_model, SEMANTIC_PROMPT_VERSION)
        if key in self._semantic_cache:
            return self._semantic_cache[key]
        availability = await self.status()
        if availability.get("enrichment_state") != "READY":
            logger.info("minutes_semantic_fallback hash=%s reason=%s", document_hash,
                        availability.get("enrichment_code") or availability.get("code"))
            return []
        _, prompt = prompt_for(SEMANTIC_PROMPT_VERSION)
        payload = {
            "model": self.settings.minutes_llm_model, "stream": False, "think": False,
            "format": "json", "options": {"temperature": 0, "num_predict": 2048, "num_ctx": 8192},
            "messages": [{"role": "system", "content": prompt},
                         {"role": "user", "content": json.dumps({"document": normalized}, ensure_ascii=False)}],
        }
        started = perf_counter()
        try:
            async with self._client() as client:
                response = await client.post("/api/chat", json=payload,
                                             timeout=min(self.settings.minutes_timeout_seconds, 45))
                response.raise_for_status()
                raw = response.json().get("message", {}).get("content")
            if not isinstance(raw, str):
                raise ValueError("semantic response missing")
            candidates = parse_llm_response(raw, normalized)
            self._semantic_cache[key] = candidates
            logger.info("minutes_semantic_llm hash=%s activities=%d llm_ms=%.0f", document_hash,
                        len(candidates), (perf_counter() - started) * 1000)
            return candidates
        except (httpx.HTTPError, TimeoutError, ValueError, TypeError, KeyError, ValidationError):
            logger.info("minutes_semantic_fallback hash=%s reason=invalid_or_unavailable", document_hash)
            return []

    async def status(self) -> dict:
        result = {"state": "DISABLED", "code": "MINUTES_AI_DISABLED", "model": self.settings.minutes_llm_model or None,
                  "ollama_available": False, "model_found": False,
                  "enrichment_code": "MINUTES_AI_DISABLED",
                  "max_chars": self.settings.minutes_max_chars,
                  "detail": "El análisis inteligente de minutas está deshabilitado por configuración."}
        if not self.settings.minutes_ai_enabled:
            result.update(state="READY", code="MINUTES_DETERMINISTIC_READY", mode="DETERMINISTIC_ONLY",
                          enrichment_state="DISABLED", model=None,
                          detail="Parser determinista listo. El enriquecimiento IA está deshabilitado.")
            return result
        if self._uses_deterministic_hybrid():
            result.update(state="READY", code="MINUTES_DETERMINISTIC_READY", mode="DETERMINISTIC_FIRST",
                          enrichment_state="UNAVAILABLE",
                          enrichment_code="MINUTES_ENRICHMENT_UNAVAILABLE",
                          detail="Parser determinista listo. Se comprobará la mejora IA opcional.")
        result["state"] = "UNAVAILABLE"
        result["code"] = "MINUTES_MODEL_UNAVAILABLE"
        if not self._uses_deterministic_hybrid():
            result["detail"] = "El análisis inteligente de minutas no está disponible."
        url = urlsplit(self.settings.ollama_base_url)
        if url.scheme not in {"http", "https"} or url.hostname not in {"localhost", "127.0.0.1", "::1"} or url.username or url.password:
            failure = "OLLAMA_BASE_URL debe apuntar a Ollama local (loopback)."
            return self._status_after_enrichment_check(result, failure, "MINUTES_OLLAMA_URL_INVALID")
        try:
            async with self._client() as client:
                response = await client.get("/api/tags")
                response.raise_for_status()
                models = response.json()["models"]
                names = {m.get("name", m.get("model")) for m in models}
            result["ollama_available"] = True
        except httpx.TimeoutException:
            result["code"] = "MINUTES_MODEL_TIMEOUT"
            return self._status_after_enrichment_check(
                result, "Ollama agotó el tiempo de comprobación.", "MINUTES_OLLAMA_TIMEOUT")
        except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError):
            return self._status_after_enrichment_check(
                result, "Ollama no responde.", "MINUTES_OLLAMA_UNAVAILABLE")
        model = self.settings.minutes_enrichment_model if self._uses_deterministic_hybrid() else self.settings.minutes_llm_model
        if not model:
            missing_model = ("Falta configurar MINUTES_ENRICHMENT_MODEL." if self._uses_deterministic_hybrid()
                             else "Falta configurar MINUTES_LLM_MODEL.")
            return self._status_after_enrichment_check(result, missing_model, "MINUTES_MODEL_NOT_CONFIGURED")
        elif model not in names:
            return self._status_after_enrichment_check(
                result, f"El modelo configurado '{model}' no está instalado en Ollama.", "MINUTES_MODEL_NOT_INSTALLED")
        else:
            result.update(state="READY", code="MINUTES_READY", model=model, model_found=True,
                          detail="Parser determinista listo. El modelo local está disponible para el enriquecimiento opcional."
                          if self._uses_deterministic_hybrid() else "Modelo local disponible para analizar minutas.")
            if self._uses_deterministic_hybrid():
                result.update(mode="DETERMINISTIC_FIRST", enrichment_state="READY",
                              enrichment_code="MINUTES_ENRICHMENT_READY")
        return result

    def _status_after_enrichment_check(self, result: dict, detail: str, failure_code: str) -> dict:
        if self._uses_deterministic_hybrid():
            result.update(state="READY", code="MINUTES_DETERMINISTIC_READY", mode="DETERMINISTIC_FIRST",
                          enrichment_state="UNAVAILABLE",
                          enrichment_code=failure_code,
                          detail=f"Parser determinista listo. El enriquecimiento IA opcional no está disponible: {detail}")
        else:
            result["enrichment_code"] = failure_code
            result["detail"] += f" {detail}"
        return result

    async def analyze(self, text: str, username: str) -> dict:
        if len(text) > self.settings.minutes_max_chars:
            raise MinutesError(f"La minuta supera el máximo de {self.settings.minutes_max_chars} caracteres.",
                               code="MINUTES_CONTEXT_TOO_LARGE")
        normalized, removed = normalize_text(text)
        if len(normalized) < 40:
            raise MinutesError("Pega al menos 40 caracteres con los acuerdos o pendientes de la reunión.",
                               code="MINUTES_INPUT_TOO_SHORT")
        if self._active:
            raise MinutesError("Ya hay una minuta en análisis. Espera a que termine.", 409,
                               code="MINUTES_ANALYSIS_IN_PROGRESS", retryable=True)
        self._active = True
        started = perf_counter()
        status = "ERROR"
        document_hash = hashlib.sha256(normalized.encode()).hexdigest()
        prompt_version, system_prompt = prompt_for(self.settings.minutes_prompt_version)
        try:
            # G2 uses deterministic extraction when the selected local model is
            # the approved lightweight enrichment model.  Existing legacy
            # configurations retain the v1/v2 end-to-end path for compatibility.
            if not self.settings.minutes_ai_enabled or self._uses_deterministic_hybrid():
                result = await self._analyze_hybrid(normalized, removed, username, document_hash, started)
                status = "OK"
                return result
            async with asyncio.timeout(self.settings.minutes_timeout_seconds):
                availability = await self.status()
                if availability["state"] != "READY":
                    raise MinutesError(availability["detail"], 504 if availability.get("code") == "MINUTES_MODEL_TIMEOUT" else 503,
                                       code=availability.get("code", "MINUTES_MODEL_UNAVAILABLE"), retryable=True)
                payload = {"model": self.settings.minutes_llm_model, "stream": False, "think": False,
                    # Gemma4 rejects the full schema grammar (HTTP 400). Keep
                    # JSON mode here and retain Pydantic/evidence validation below.
                    "format": "json",
                    "options": {"temperature": 0, "num_predict": 4096, "num_ctx": 16384},
                                 "messages": [{"role": "system", "content": system_prompt},
                                 {"role": "user", "content": json.dumps({"document": normalized}, ensure_ascii=False)}]}
                async with self._client() as client:
                    response = await client.post("/api/chat", json=payload, timeout=self.settings.minutes_timeout_seconds)
                    try:
                        response.raise_for_status()
                    except httpx.HTTPStatusError as exc:
                        status_code = exc.response.status_code
                        # Inspect only a bounded, non-user-facing error marker;
                        # never return Ollama's body to the client or logs.
                        safe_error = (exc.response.text or "")[:500].casefold()
                        context_error = status_code == 413 or (status_code == 400 and any(
                            marker in safe_error for marker in ("context", "too many tokens", "maximum token", "prompt too large")))
                        category = ("MINUTES_MODEL_UNAVAILABLE" if status_code >= 500 else
                                    "MINUTES_CONTEXT_TOO_LARGE" if context_error else
                                    "MINUTES_MODEL_REQUEST_REJECTED")
                        message = ("La minuta excede el contexto que acepta el modelo local. Intenta con menos texto."
                                   if context_error
                                   else "El modelo local configurado no está disponible." if status_code >= 500
                                   else "El modelo local rechazó la solicitud; revisa el formato o la configuración del modelo.")
                        raise MinutesError(message, 422 if context_error else 503 if status_code >= 500 else 502,
                                           code=category, retryable=category != "MINUTES_CONTEXT_TOO_LARGE",
                                           ollama_status=status_code) from None
                    try:
                        body = response.json()
                        content = body["message"]["content"]
                    except (ValueError, KeyError, TypeError):
                        raise MinutesError("No pude estructurar esta minuta con suficiente seguridad: el modelo no produjo una respuesta JSON utilizable.", 502,
                                           code="MINUTES_INVALID_JSON") from None
                if not isinstance(content, str) or len(content) > 200000:
                    raise MinutesError("No pude estructurar esta minuta con suficiente seguridad: el modelo no produjo una estructura válida.", 422,
                                       code="MINUTES_INVALID_JSON")
                try:
                    document = MinutesDocument.model_validate_json(content)
                except ValidationError:
                    raise MinutesError("No pude estructurar esta minuta con suficiente seguridad: la estructura no pasó la validación.", 422,
                                       code="MINUTES_VALIDATION_FAILED") from None
                document, warnings, notes = validate_extraction(document, normalized)
                if removed:
                    warnings.insert(0, f"Se omitieron {removed} bloques de texto repetidos.")
                proposal = self.proposals.create_from_minutes(document, document_hash, warnings, notes, username,
                                                               prompt_version=prompt_version)
                status = "OK"
                return {"proposal_id": proposal["proposal_id"], "proposal": proposal,
                        "document": document.model_dump(mode="json", exclude={"activities"}),
                        "activities": document.model_dump(mode="json")["activities"], "warnings": warnings}
        except (TimeoutError, httpx.TimeoutException):
            raise MinutesError("El modelo tardó demasiado en analizar la minuta. Intenta con menos texto.", 504,
                               code="MINUTES_MODEL_TIMEOUT", retryable=True) from None
        except httpx.HTTPError:
            raise MinutesError("El modelo local configurado no está disponible.", 503,
                               code="MINUTES_MODEL_UNAVAILABLE", retryable=True) from None
        except MinutesError:
            raise
        except (ValueError, KeyError, TypeError):
            logger.exception("minutes analysis invalid deterministic result")
            raise MinutesError("No pude estructurar esta minuta con suficiente seguridad: el modelo no produjo una estructura válida.", 422,
                               code="MINUTES_INVALID_JSON") from None
        finally:
            self._active = False
            logger.info("minutes_analysis hash=%s chars=%d output_limit=%d duration_ms=%.0f status=%s",
                        document_hash, len(normalized), 4096, (perf_counter() - started) * 1000, status)

    async def _analyze_hybrid(self, normalized: str, removed: int, username: str,
                              document_hash: str, started: float) -> dict:
        """Merge literal extraction with safe semantic candidates before Preview."""
        deterministic_started = perf_counter()
        extraction = extract_explicit(normalized)
        warnings = list(extraction.warnings)
        if removed:
            warnings.insert(0, f"Se omitieron {removed} bloques de texto repetidos.")
        from .minutes_enrichment import build_activities, enrichment_payload
        activities, _, _ = build_activities(extraction.candidates, None)
        deterministic_ms = round((perf_counter() - deterministic_started) * 1000, 1)
        # Natural-language extraction is purposely separate from the old
        # section/list parser.  It is used when no explicit candidate exists,
        # and the local model may improve/confirm it but can never be required.
        semantic_started = perf_counter()
        semantic_rules = extract_rule_candidates(normalized) if not extraction.candidates else []
        semantic_llm: list[SemanticCandidate] = []
        if semantic_rules and self.settings.minutes_ai_enabled:
            semantic_llm = await self._semantic_model_candidates(normalized, document_hash)
        semantic_ms = round((perf_counter() - semantic_started) * 1000, 1)
        merge_started = perf_counter()
        semantic_activities = [_semantic_activity(item) for item in (semantic_llm or semantic_rules)]
        if semantic_rules and semantic_llm:
            semantic_activities = _merge_activities(
                [_semantic_activity(item) for item in semantic_rules], semantic_activities)
        activities = _merge_activities(activities, semantic_activities)
        merge_ms = round((perf_counter() - merge_started) * 1000, 1)
        if not activities:
            warnings.append("No se detectaron actividades explícitas o compromisos accionables; no se generaron tareas.")
        project_responsible, project_responsible_evidence = _project_responsible_from_text(normalized)
        document = MinutesDocument(document_type="meeting_minutes", date=_date_from_text(normalized),
                                   project=_project_from_text(normalized), objective=None,
                                   project_responsible=project_responsible,
                                   project_responsible_evidence=project_responsible_evidence,
                                   participants=_participants_from_text(normalized), activities=activities)
        document, validation_warnings, notes = validate_extraction(document, normalized)
        warnings.extend(validation_warnings)
        started_at = _now_iso()
        # Existing enrichment remains limited to literal candidates; semantic
        # discovery already has its own strict response and fallback above.
        enrichment_enabled = self.settings.minutes_ai_enabled and bool(extraction.candidates)
        initial_enrichment = ({"state": "PENDING", "base_version": 1,
                               "message": "La mejora opcional con IA está en curso."}
                              if enrichment_enabled else None)
        proposal = self.proposals.create_from_minutes(document, document_hash, warnings, notes, username,
                                                       prompt_version=SEMANTIC_PROMPT_VERSION,
                                                       extraction_mode=("HYBRID_SEMANTIC" if semantic_activities else "DETERMINISTIC_FALLBACK"),
                                                       enrichment=initial_enrichment)
        first_ms = round((perf_counter() - started) * 1000, 1)
        if enrichment_enabled:
            self.proposals.repository.save_minutes_enrichment(
                proposal["proposal_id"], base_version=proposal["version"], state="PENDING",
                suggestions=[], message="La mejora opcional con IA está en curso.", started_at=started_at,
            )
            task = asyncio.create_task(self._run_enrichment(
                proposal["proposal_id"], proposal["version"], extraction, normalized, username,
                started_at, enrichment_payload,
            ))
            self._enrichment_tasks[proposal["proposal_id"]] = task
            task.add_done_callback(lambda _task, pid=proposal["proposal_id"]: self._enrichment_tasks.pop(pid, None))
        logger.info("minutes_hybrid hash=%s deterministic=%d semantic_rules=%d semantic_llm=%d merged=%d deterministic_ms=%.1f semantic_ms=%.1f merge_ms=%.1f total_ms=%.1f",
                    document_hash, len(extraction.candidates), len(semantic_rules), len(semantic_llm),
                    len(activities), deterministic_ms, semantic_ms, merge_ms, first_ms)
        result = {"proposal_id": proposal["proposal_id"], "proposal": proposal,
                  "document": document.model_dump(mode="json", exclude={"activities"}),
                  "activities": document.model_dump(mode="json")["activities"], "warnings": warnings,
                  "extraction_mode": ("HYBRID_SEMANTIC" if semantic_activities else "DETERMINISTIC_FALLBACK"),
                  "candidate_count": len(extraction.candidates), "semantic_candidate_count": len(semantic_activities),
                  "time_to_first_proposal_ms": first_ms}
        if enrichment_enabled:
            result["enrichment"] = {"state": "PENDING", "base_version": proposal["version"],
                                    "message": "La mejora opcional con IA está en curso."}
        return result

    async def _run_enrichment(self, proposal_id: str, base_version: int, extraction, normalized: str,
                              username: str, started_at: str, enrichment_payload) -> None:
        from .minutes_enrichment import build_activities_with_diagnostics
        started = perf_counter()
        state, message, suggestions, failure_code = "READY", None, [], None
        try:
            availability = await self.status()
            if availability.get("enrichment_state") != "READY":
                state = "FAILED"
                message = availability.get("detail") or "El enriquecimiento opcional con IA no está disponible."
                failure_code = availability.get("enrichment_code") or availability.get("code")
            else:
                _, system_prompt = prompt_for("minutes-enrich-v1")
                payload = {"model": self.settings.minutes_enrichment_model, "stream": False, "think": False,
                           "format": "json", "options": {"temperature": 0, "num_predict": 1536, "num_ctx": 8192},
                           "messages": [{"role": "system", "content": system_prompt},
                                        {"role": "user", "content": json.dumps({"candidates": enrichment_payload(extraction.candidates)}, ensure_ascii=False)}]}
                try:
                    async with self._client() as client:
                        response = await client.post("/api/chat", json=payload,
                                                     timeout=self.settings.minutes_enrichment_timeout_seconds)
                        response.raise_for_status()
                        body = response.json()
                    raw = body.get("message", {}).get("content") if isinstance(body, dict) else None
                    if not isinstance(raw, str) or not raw.strip():
                        state, message, failure_code = (
                            "FAILED", "Ollama respondió sin contenido JSON de enrichment.",
                            "MINUTES_ENRICHMENT_EMPTY_RESPONSE",
                        )
                except (httpx.TimeoutException, TimeoutError):
                    state, message, failure_code = (
                        "FAILED",
                        f"Ollama superó el límite de {self.settings.minutes_enrichment_timeout_seconds:g} s para el enrichment.",
                        "MINUTES_ENRICHMENT_TIMEOUT",
                    )
                except httpx.HTTPStatusError as exc:
                    state, message, failure_code = (
                        "FAILED", f"Ollama rechazó la solicitud de enrichment (HTTP {exc.response.status_code}).",
                        "MINUTES_ENRICHMENT_HTTP_ERROR",
                    )
                except httpx.HTTPError:
                    state, message, failure_code = (
                        "FAILED", "Ollama dejó de responder durante el enrichment.", "MINUTES_OLLAMA_UNAVAILABLE",
                    )
                except (ValueError, TypeError, AttributeError):
                    state, message, failure_code = (
                        "FAILED", "Ollama respondió con una estructura que no contiene message.content.",
                        "MINUTES_ENRICHMENT_INVALID_RESPONSE",
                    )
                if state != "FAILED":
                    enriched, validation_warnings, did_enrich, failure_code = build_activities_with_diagnostics(
                        extraction.candidates, raw)
                    if not did_enrich:
                        state = "FAILED"
                        message = validation_warnings[0] if validation_warnings else "La respuesta de IA no pasó la validación de enrichment."
                        failure_code = failure_code or "MINUTES_ENRICHMENT_FAILED"
                    else:
                        for index, activity in enumerate(enriched):
                            base = extraction.candidates[index]
                            if activity.title != base.normalized_text.rstrip(".") or activity.description != base.source_evidence:
                                suggestions.append({"row_id": f"ROW-{index + 6:04d}",
                                                    "title": activity.title, "description": activity.description,
                                                    "base_title": base.normalized_text.rstrip("."),
                                                    "base_description": base.source_evidence})
                        if not suggestions:
                            state, message = "READY", "Las actividades ya tienen una redacción adecuada."
                        else:
                            state, message = "READY", "Hay mejoras de redacción disponibles."
        except Exception:
            logger.exception("minutes enrichment failed proposal=%s", proposal_id)
            state, message, failure_code = (
                "FAILED", "Ocurrió un error técnico durante el enrichment opcional con IA.",
                "MINUTES_ENRICHMENT_FAILED",
            )
        current = self.proposals.repository.get(proposal_id)
        if current is None or current.get("version") != base_version:
            state = "STALE"
            message = "La Proposal cambió mientras la IA trabajaba; las sugerencias no se aplicaron."
            failure_code = "MINUTES_ENRICHMENT_STALE"
        self.proposals.repository.save_minutes_enrichment(
            proposal_id, base_version=base_version, state=state, suggestions=suggestions,
            message=message, failure_code=failure_code, started_at=started_at, completed_at=_now_iso(),
            duration_ms=round((perf_counter() - started) * 1000, 1),
        )

    async def enrich_draft(self, draft: dict, draft_service) -> None:
        """Produce source-bound suggestions for a draft without mutating edited cells."""
        from .minutes_enrichment import build_activities_with_diagnostics, enrichment_payload
        started = perf_counter()
        state, message, suggestions, failure_code = "READY", None, [], None
        try:
            availability = await self.status()
            if availability.get("enrichment_state") != "READY":
                state, failure_code = "FAILED", availability.get("enrichment_code") or availability.get("code")
                message = "Las actividades fueron detectadas. Algunas mejoras automáticas no estuvieron disponibles."
            else:
                extraction = extract_explicit(draft["source_text"])
                _, system_prompt = prompt_for("minutes-enrich-v1")
                payload = {"model": self.settings.minutes_enrichment_model, "stream": False, "think": False,
                           "format": "json", "options": {"temperature": 0, "num_predict": 1536, "num_ctx": 8192},
                           "messages": [{"role": "system", "content": system_prompt},
                                        {"role": "user", "content": json.dumps({"candidates": enrichment_payload(extraction.candidates)}, ensure_ascii=False)}]}
                async with self._client() as client:
                    response = await client.post("/api/chat", json=payload,
                                                 timeout=self.settings.minutes_enrichment_timeout_seconds)
                    response.raise_for_status()
                    raw = response.json().get("message", {}).get("content")
                enriched, warnings, valid, failure_code = build_activities_with_diagnostics(extraction.candidates, raw)
                if not valid:
                    state = "FAILED"
                    message = warnings[0] if warnings else "La mejora automática no produjo sugerencias válidas."
                else:
                    for candidate, activity in zip(extraction.candidates, enriched):
                        fields = []
                        base_title = candidate.normalized_text.rstrip(".")[:200]
                        if activity.title != base_title:
                            fields.append({"field": "actividad", "value": activity.title})
                        if activity.description != candidate.source_evidence:
                            fields.append({"field": "contexto_o_resultado", "value": activity.description})
                        if activity.project_or_front:
                            fields.append({"field": "proyecto_o_frente", "value": activity.project_or_front})
                        if activity.responsible_candidate:
                            fields.append({"field": "responsable", "value": activity.responsible_candidate})
                        if activity.due_date_candidate:
                            fields.append({"field": "fecha_objetivo", "value": activity.due_date_candidate.isoformat()})
                        if fields:
                            suggestions.append({"candidate_id": candidate.candidate_id, "fields": fields})
                    message = "Hay mejoras de redacción disponibles." if suggestions else "Las actividades ya tienen una redacción adecuada."
        except (httpx.HTTPError, TimeoutError, ValueError, TypeError, AttributeError):
            state, failure_code = "FAILED", "MINUTES_ENRICHMENT_UNAVAILABLE"
            message = "Las actividades fueron detectadas. Algunas mejoras automáticas no estuvieron disponibles."
        except Exception:
            logger.exception("minute draft enrichment failed draft=%s", draft.get("draft_id"))
            state, failure_code = "FAILED", "MINUTES_ENRICHMENT_FAILED"
            message = "Las actividades fueron detectadas. Algunas mejoras automáticas no estuvieron disponibles."
        draft_service.save_enrichment(
            draft["draft_id"], draft["owner"], draft["version"], state=state, suggestions=suggestions,
            message=message, failure_code=failure_code, duration_ms=round((perf_counter() - started) * 1000, 1),
        )


def _project_from_text(text: str) -> str | None:
    for line in text.splitlines():
        match = re.match(r"^\s*Proyecto(?:\s*/\s*Requerimiento)?\s*:\s*(.+)$", line, re.IGNORECASE)
        if match:
            return match.group(1).strip()[:300]
    return None


def _project_responsible_from_text(text: str) -> tuple[str | None, str | None]:
    """Read an explicitly labelled project owner without assigning any task."""
    labels = (
        r"responsable\s+(?:del|de la)\s+(?:proyecto|frente)",
        r"l[ií]der\s+(?:del|de la)\s+(?:proyecto|frente)",
        r"coordinador(?:a)?\s+(?:del|de la)\s+(?:proyecto|frente)",
        r"project\s+owner",
        r"project\s+manager",
    )
    for line in text.splitlines():
        match = re.match(r"^\s*(?:" + "|".join(labels) + r")\s*:\s*(.+?)\s*$", line, re.IGNORECASE)
        if not match:
            continue
        value = re.sub(r"\s+", " ", match.group(1)).strip(" .;,:-")[:200]
        if value:
            return value, line.strip()[:2000]
    return None, None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _date_from_text(text: str) -> CalendarDate | None:
    match = re.search(r"(?im)^\s*Fecha\s*:\s*(\d{1,2})/(\d{1,2})/(\d{4})\s*$", text)
    if not match:
        return None
    try:
        return CalendarDate(int(match.group(3)), int(match.group(2)), int(match.group(1)))
    except ValueError:
        return None


def _participants_from_text(text: str) -> list[Participant]:
    """Extract only explicit participant labels; never assigns their actions."""
    participants: list[Participant] = []
    for line in text.splitlines():
        match = re.match(r"^\s*(L[ií]der\s+Usuario|Participantes?)\s*:\s*(.+)$", line, re.IGNORECASE)
        if not match:
            continue
        role = match.group(1).strip()
        raw_names = re.split(r"\s*(?:,|;|\by\b|\bequipo\s+de\b)\s*", match.group(2), flags=re.IGNORECASE)
        for raw_name in raw_names:
            name = raw_name.strip(" .\t")
            if len(name) >= 2 and not any(canonical(p.name) == canonical(name) for p in participants):
                participants.append(Participant(name=name[:200], role=role[:200]))
    return participants[:100]
