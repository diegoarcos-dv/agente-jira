"""Safe semantic candidates for informal Spanish meeting notes.

The local model is optional: this module deliberately retains a small, fully
deterministic language layer so that an unavailable Ollama instance never turns
an otherwise understandable commitment into an empty proposal.  Model output is
represented by strict Pydantic models and must still pass the same evidence and
business validation used by the rest of Minutes.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, timedelta

from pydantic import ConfigDict, BaseModel, Field, ValidationError


SEMANTIC_PROMPT_VERSION = "minutes_semantic_v1"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SemanticItem(_StrictModel):
    title: str = Field(min_length=3, max_length=200)
    responsible_name: str | None = Field(default=None, max_length=200)
    responsible_role: str | None = Field(default=None, max_length=80)
    collaborators: list[str] = Field(default_factory=list, max_length=10)
    activity_evidence: str | None = Field(default=None, max_length=2000)
    area_evidence: str | None = Field(default=None, max_length=2000)
    responsible_evidence: str | None = Field(default=None, max_length=2000)
    collaborators_evidence: str | None = Field(default=None, max_length=2000)
    due_date_text: str | None = Field(default=None, max_length=120)
    area: str | None = Field(default=None, max_length=200)
    project: str | None = Field(default=None, max_length=300)
    context: str | None = Field(default=None, max_length=2000)
    confidence: float = Field(ge=0, le=1)
    evidence: str = Field(min_length=5, max_length=4000)
    needs_review: bool = True


class SemanticResponse(_StrictModel):
    activities: list[SemanticItem] = Field(default_factory=list, max_length=50)


@dataclass(frozen=True)
class SemanticCandidate:
    title: str
    responsible_name: str | None
    collaborators: tuple[str, ...]
    due_date: date | None
    due_date_text: str | None
    project: str | None
    context: str
    evidence: str
    confidence: float
    source: str = "semantic"
    area: str | None = None
    activity_evidence: str | None = None
    area_evidence: str | None = None
    responsible_evidence: str | None = None
    collaborators_evidence: str | None = None
    responsible_role: str | None = None


_MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10, "noviembre": 11,
    "diciembre": 12,
}
_WEEKDAYS = {"lunes": 0, "martes": 1, "miercoles": 2, "miércoles": 2, "jueves": 3,
             "viernes": 4, "sabado": 5, "sábado": 5, "domingo": 6}
_VERBS = {
    "hacer": "Realizar", "haga": "Realizar", "hará": "Realizar", "hara": "Realizar",
    "desarrollar": "Desarrollar", "crear": "Crear", "revisar": "Revisar",
    "revise": "Revisar", "revisará": "Revisar", "revisara": "Revisar",
    "checar": "Revisar", "cheque": "Revisar", "validar": "Validar", "valida": "Validar",
    "preparar": "Preparar", "prepara": "Preparar", "documentar": "Documentar",
    "enviar": "Enviar", "entregar": "Entregar", "investigar": "Investigar",
    "actualizar": "Actualizar", "corregir": "Corregir", "implementar": "Implementar",
    "implemente": "Implementar", "implementar": "Implementar", "probar": "Probar",
    "coordinar": "Coordinar", "confirmar": "Confirmar", "solicitar": "Solicitar",
    "validar": "Validar", "validará": "Validar", "validara": "Validar",
    "preparará": "Preparar", "preparara": "Preparar", "debe": "",
}
_ACTION_WORDS = "|".join(sorted((re.escape(word) for word in _VERBS), key=len, reverse=True))
_NEGATED = re.compile(r"\b(?:no\s+(?:va\s+a\s+)?|no\s+debe(?:rá)?\s+|no\s+necesitamos\s+)", re.I)
_COMPLETED = re.compile(r"\b(?:ya\s+(?:termin[oó]|complet[oó]|finaliz[oó])|se\s+(?:termin[oó]|complet[oó]))\b", re.I)
_HISTORICAL = re.compile(r"\b(?:fue|fueron|ha\s+sido|hab[ií]a\s+sido)\s+(?:desarrollad[oa]s?|cread[oa]s?|implementad[oa]s?)\b", re.I)


def _fold(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    return "".join(char for char in value if not unicodedata.combining(char)).casefold()


def _clean_name(value: str | None) -> str | None:
    if not value:
        return None
    candidate = re.sub(r"\s+", " ", value).strip(" ,.;:")
    candidate = re.sub(r"^(?:(?:el|la)\s+)?(?:ingeniero|ing\.?|lic\.?|sr\.?|sra\.?)\s+", "", candidate, flags=re.I)
    return candidate[:200] or None


def parse_due_date(value: str | None, *, today: date | None = None) -> date | None:
    """Parse Spanish MX dates deterministically (numeric dates are DD/MM/YYYY)."""
    if not value:
        return None
    today = today or date.today()
    folded = _fold(value)
    match = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b", folded)
    if match:
        year = int(match.group(3))
        year = 2000 + year if year < 100 else year
        try:
            return date(year, int(match.group(2)), int(match.group(1)))
        except ValueError:
            return None
    match = re.search(r"\b(\d{1,2})\s+de\s+(%s)(?:\s+de\s+(\d{4}))?\b" % "|".join(_MONTHS), folded)
    if match:
        year = int(match.group(3)) if match.group(3) else today.year
        try:
            return date(year, _MONTHS[match.group(2)], int(match.group(1)))
        except ValueError:
            return None
    if "pasado manana" in folded:
        return today + timedelta(days=2)
    if "manana" in folded:
        return today + timedelta(days=1)
    for name, weekday in _WEEKDAYS.items():
        if re.search(rf"\b(?:el\s+)?{name}\b", folded):
            offset = (weekday - today.weekday()) % 7
            return today + timedelta(days=offset or 7)
    if "fin de mes" in folded:
        first_next = date(today.year + (today.month == 12), (today.month % 12) + 1, 1)
        return first_next - timedelta(days=1)
    match = re.search(r"\bantes\s+del\s+(\d{1,2})\b", folded)
    if match:
        try:
            return date(today.year, today.month, int(match.group(1)))
        except ValueError:
            return None
    return None


def _due_expression(text: str) -> tuple[date | None, str | None]:
    patterns = (
        r"\b\d{1,2}/\d{1,2}/\d{2,4}\b",
        r"\b\d{1,2}\s+de\s+(?:%s)(?:\s+de\s+\d{4})?\b" % "|".join(_MONTHS),
        r"\bpasado\s+mañana\b|\bmañana\b|\b(?:el\s+)?(?:lunes|martes|miércoles|miercoles|jueves|viernes|sábado|sabado|domingo)\b",
        r"\b(?:para\s+)?fin\s+de\s+mes\b|\bantes\s+del\s+\d{1,2}\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return parse_due_date(match.group(0)), match.group(0)
    return None, None


def _title(verb: str, object_text: str) -> str | None:
    object_text = re.sub(r"\b(?:para|antes del|el día|dia)\b.*$", "", object_text, flags=re.I).strip(" ,.;")
    object_text = re.sub(r"^se\s+", "", object_text, flags=re.I)
    if not object_text:
        return None
    if verb.casefold() in {"hacer", "haga", "hará", "hara"} and re.search(r"\bagente\b", object_text, re.I):
        verb = "Desarrollar"
    title = f"{_VERBS.get(verb.casefold(), verb.capitalize())} {object_text}"
    return re.sub(r"\s+", " ", title).strip()[:200]


def _split_actions(text: str) -> list[str]:
    # "y que" is a strong task boundary; comma-separated noun complements are
    # expanded only after a concrete verb (desarrollo, pruebas, documentación).
    result = [part.strip() for part in re.split(r"\s+y\s+que\s+", text, flags=re.I) if part.strip()]
    expanded: list[str] = []
    for part in result:
        match = re.match(rf"(?P<verb>{_ACTION_WORDS})\s+(?P<objects>.+)", part, re.I)
        if match and re.search(r"\b(?:desarrollo|pruebas?|documentaci[oó]n)\b", match.group("objects"), re.I) and "," in match.group("objects"):
            objects = re.split(r"\s*,\s*|\s+y\s+", match.group("objects"))
            expanded.extend(f"{match.group('verb')} {obj}" for obj in objects if obj.strip())
        else:
            expanded.append(part)
    return expanded


def _display_name(value: str | None) -> str | None:
    """Give all-lowercase names a display form without changing their identity."""
    value = _clean_name(value)
    if not value:
        return None
    if value == value.lower():
        return " ".join(part.capitalize() for part in value.split())
    return value


def _names(value: str) -> tuple[str, ...]:
    """Extract a small, literal list of people after a role cue."""
    value = re.sub(r"\b(?:como\s+)?(?:desarrolladores?|desarroladores?|colaboradores?|participantes?)\b.*$", "", value, flags=re.I)
    value = re.sub(r"\b(?:con\s+apoyo\s+de|junto\s+con)\s+", "", value, flags=re.I)
    people: list[str] = []
    for part in re.split(r"\s*(?:,|\by\b|\be\b)\s*", value, flags=re.I):
        name = _display_name(part)
        if not name or len(name.split()) > 4:
            continue
        folded = _fold(name)
        if folded in {"a cargo", "a cargo de", "con apoyo"}:
            continue
        if any(word in folded.split() for word in {"el", "la", "los", "las", "del", "desarrollo", "proyecto"}):
            continue
        if name not in people:
            people.append(name)
    return tuple(people[:10])


def _area_display(value: str) -> str:
    value = re.sub(r"^(?:la\s+de|el\s+área\s+de|el\s+area\s+de)\s+", "", value.strip(" ,.;"), flags=re.I)
    known = {
        "desarrollo tecnologico": "Desarrollo Tecnológico",
        "arquitecturas ti": "Arquitecturas TI",
        "big data": "Big Data",
    }
    return known.get(_fold(value), " ".join(part.capitalize() for part in value.split()))


def _explicit_area(text: str) -> tuple[str | None, str | None]:
    patterns = (
        r"\b(?:el\s+)?[áa]rea\s+(?:que\s+)?(?:lo\s+)?(?:desarrollar[aá]|har[aá]|ser[aá]\s+responsable)\s+es\s+(?:la\s+de\s+)?(?P<area>[^,.;]+)",
        r"\b(?P<area>desarrollo\s+tecnol[oó]gico|arquitecturas\s+ti|big\s+data)\s+(?:lo\s+)?(?:desarrollar[aá]|har[aá]|ser[aá]\s+responsable)",
        r"\bqueda\s+con\s+(?P<area>desarrollo\s+tecnol[oó]gico|arquitecturas\s+ti|big\s+data)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            area = _area_display(match.group("area"))
            return area, match.group(0).strip()
    return None, None


def _role_people(text: str) -> tuple[str | None, tuple[str, ...], str | None, str | None]:
    """Return one explicit lead and supporting collaborators, never choosing at random."""
    lead_evidence = None
    lead_names: tuple[str, ...] = ()
    lead_patterns = (
        r"\ba\s+cargo\s+(?:de(?:l)?\s+)?(?:(?:el|la)\s+)?(?:ingeniero|ing\.?|lic\.?)?\s*(?P<names>[^,.;]+)",
        r"\b(?P<names>[A-Za-zÁÉÍÓÚÜÑáéíóúüñ.'-]+(?:\s+[A-Za-zÁÉÍÓÚÜÑáéíóúüñ.'-]+){0,3})\s+estar[aá]\s+a\s+cargo\b",
        r"\b(?:responsable|l[ií]der)\s*(?::|ser[aá])\s*(?P<names>[^,.;]+)",
        r"\b(?P<names>[A-Za-zÁÉÍÓÚÜÑáéíóúüñ.'-]+(?:\s+[A-Za-zÁÉÍÓÚÜÑáéíóúüñ.'-]+){0,3})\s+se\s+encargar[aá]\b",
    )
    for pattern in lead_patterns:
        match = re.search(pattern, text, re.I)
        if match:
            lead_names = _names(match.group("names"))
            if lead_names:
                lead_evidence = match.group(0).strip()
                break
    collaborators: list[str] = []
    collaborators_evidence = None
    collaborator_patterns = (
        r"\b(?:desarrolladores?|desarroladores?)\s+(?P<names>[^,.;]+)",
        r"\bcon\s+(?P<names>[^,.;]+?)\s+como\s+desarrolladores?\b",
        r"\bcon\s+apoyo\s+de\s+(?P<names>[^,.;]+)",
        r"\b(?P<names>[A-Za-zÁÉÍÓÚÜÑáéíóúüñ.'-]+(?:\s+[A-Za-zÁÉÍÓÚÜÑáéíóúüñ.'-]+){0,3})\s+apoyar[aá]\s+el\s+desarrollo\b",
    )
    for pattern in collaborator_patterns:
        match = re.search(pattern, text, re.I)
        if not match:
            continue
        found = _names(match.group("names"))
        if found:
            collaborators_evidence = match.group(0).strip()
            collaborators.extend(name for name in found if name not in collaborators)
    if len(lead_names) == 1:
        leader = lead_names[0]
    else:
        # "a cargo de Jose y Gis" has no unique Jira assignee.
        leader = None
        collaborators = list(lead_names) + [name for name in collaborators if name not in lead_names]
    return leader, tuple(collaborators[:10]), lead_evidence, collaborators_evidence


def _project_description_candidate(text: str, due_date: date | None, due_text: str | None) -> SemanticCandidate | None:
    """Turn a future project description into one coherent activity, not many fragments."""
    project_match = re.search(r"\b(?:el\s+)?proyecto\s+consiste\s+en\s+(?P<description>[^,.;]+)", text, re.I)
    if not project_match:
        return None
    future = re.search(r"\b(?:lo\s+desarrollar[aá]|ser[aá]\s+desarrollad[oa]|estar[aá]\s+a\s+cargo|ser[aá]\s+responsable|se\s+encargar[aá])\b", text, re.I)
    if not future:
        return None
    description = project_match.group("description").strip()
    support = re.search(r"\bpara\s+(?:dar\s+)?soporte\s+a\s+(?:los\s+)?(?P<target>[^,.;]+)", description, re.I)
    core = description[:support.start()].strip(" ,.;") if support else description
    if not core:
        return None
    target = support.group("target").strip(" ,.;") if support else None
    target = re.sub(r"\btelmex\b", "Telmex", target or "", flags=re.I)
    title = f"Desarrollar {core}"
    project = core.removeprefix("un ").removeprefix("una ").strip().capitalize()
    context = ""
    if target:
        title = f"{title} para soporte a {target}"
        project = f"{project} de soporte"
        context = f"Dar soporte a {target}."
    area, area_evidence = _explicit_area(text)
    leader, collaborators, leader_evidence, collaborators_evidence = _role_people(text)
    evidence = text[:4000]
    return SemanticCandidate(title[:200], leader, collaborators, due_date, due_text, project[:300], context or description,
                             evidence, .86 if leader else .75, "semantic_rule", area=area,
                             activity_evidence=project_match.group(0).strip(), area_evidence=area_evidence,
                             responsible_evidence=leader_evidence, collaborators_evidence=collaborators_evidence,
                             responsible_role="lead" if leader else None)


def _collective_responsibility_candidate(text: str, due_date: date | None, due_text: str | None) -> SemanticCandidate | None:
    """Keep multiple people as candidates when the note provides no leader."""
    collective = re.search(r"\b(?:el\s+)?(?P<object>desarrollo(?:\s+[^,.;]+)?)\s+lo\s+har[aá]n\s+(?P<names>[^.;]+)", text, re.I)
    if collective:
        collaborators = _names(collective.group("names"))
        if collaborators:
            return SemanticCandidate("Realizar " + collective.group("object").strip(), None, collaborators,
                                     due_date, due_text, None, "Responsables por seleccionar en Jira.", text[:4000], .72,
                                     "semantic_rule", collaborators_evidence=collective.group(0).strip())
    area_owner = re.search(r"\b(?P<area>desarrollo\s+tecnol[oó]gico|arquitecturas\s+ti|big\s+data)\s+ser[aá]\s+responsable\s+de(?:l)?\s+(?P<object>[^.;]+)", text, re.I)
    if area_owner:
        area = _area_display(area_owner.group("area"))
        return SemanticCandidate("Desarrollar " + area_owner.group("object").strip(), None, (), due_date, due_text,
                                 None, "Responsable Jira por seleccionar.", text[:4000], .7, "semantic_rule", area=area,
                                 activity_evidence=area_owner.group(0).strip(), area_evidence=area_owner.group(0).strip())
    leader, collaborators, leader_evidence, collaborators_evidence = _role_people(text)
    if leader and collaborators and re.search(r"\bdesarrollo\b", text, re.I):
        return SemanticCandidate("Coordinar el desarrollo", leader, collaborators, due_date, due_text, None,
                                 "Trabajo de desarrollo con equipo técnico.", text[:4000], .7, "semantic_rule",
                                 responsible_evidence=leader_evidence, collaborators_evidence=collaborators_evidence,
                                 responsible_role="lead")
    return None


def extract_rule_candidates(text: str, *, today: date | None = None) -> list[SemanticCandidate]:
    """Conservative Spanish-NL fallback for commitments outside explicit sections."""
    text = re.sub(r"\s+", " ", text).strip()
    if not text or _NEGATED.search(text) or _COMPLETED.search(text) or _HISTORICAL.search(text):
        return []
    due_date, due_text = _due_expression(text)
    project_candidate = _project_description_candidate(text, due_date, due_text)
    if project_candidate:
        return [project_candidate]
    collective_candidate = _collective_responsibility_candidate(text, due_date, due_text)
    if collective_candidate:
        return [collective_candidate]
    candidates: list[SemanticCandidate] = []
    # Assignment phrasing preserves the assignee across coordinated actions.
    person_name = r"[A-ZÁÉÍÓÜÑ][\wÁÉÍÓÚÜÑáéíóúüñ.'-]+(?:\s+[A-ZÁÉÍÓÚÜÑ][\wÁÉÍÓÚÜÑáéíóúüñ.'-]+){0,2}"
    assigned = re.search(r"\benc[aá]rgale\s+(?:a|al)\s+(?P<person>(?:(?:el|la)\s+)?(?:ingeniero|ing\.?|lic\.?)?\s*" + person_name + r")\s+que\s+(?P<actions>.+)", text, re.I)
    # Informal notes often put the assignment after the activity and use
    # lowercase names: "Tenemos que hacer X, asígnalo a jose calleja".
    # This remains an explicit assignment, unlike a bare person mention.
    trailing_assignment = None
    if not assigned:
        loose_person = r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ.'-]+(?:\s+(?!y\b|para\b|lo\b|la\b|el\b|con\b)[A-Za-zÁÉÍÓÚÜÑáéíóúüñ.'-]+){0,2}"
        trailing_assignment = re.search(
            r"\b(?:as[ií]gn(?:a|alo|ala)|pon)\s+(?:a\s+)?(?P<person>" + loose_person + r")\b",
            text,
            re.I,
        )
    responsible = _clean_name((assigned or trailing_assignment).group("person")) if (assigned or trailing_assignment) else None
    if assigned:
        action_text = assigned.group("actions")
    elif trailing_assignment:
        action_text = text[:trailing_assignment.start()].strip(" ,.;")
        action_text = re.sub(r"^(?:tenemos\s+que|hay\s+que|necesitamos\s+que|se\s+acord[oó]\s+que|qued[oó]\s+pendiente\s+)(?:hacer\s+)?", "", action_text, flags=re.I)
        if not action_text:
            action_text = text
    else:
        action_text = text
    chunks = _split_actions(action_text)
    # Direct named commitments can coexist in the same sentence.
    if not (assigned or trailing_assignment):
        chunks = []
        direct = re.finditer(
            rf"\b(?P<person>{person_name})\s+(?:(?:debe|deberá|debera|deber[ií]a|va\s+a|tiene\s+que|se\s+encarga\s+de|queda\s+a\s+cargo\s+de)\s+)?(?P<verb>{_ACTION_WORDS})\s+(?P<object>[^.;]+?)(?=(?:\s+y\s+[A-ZÁÉÍÓÚÜÑ]|[.;]|$))",
            text,
        )
        for match in direct:
            if _fold(match.group("verb")) in {"participara", "participará"}:
                continue
            chunks.append((match.group("object"), _clean_name(match.group("person")), match.group("verb")))
        if not chunks:
            chunks = [(text, None, None)]
    for chunk in chunks:
        if isinstance(chunk, tuple):
            raw, owner, supplied_verb = chunk
        else:
            raw, owner, supplied_verb = chunk, responsible, None
        raw = re.sub(r"\s+(?:y\s+)?esto\s+tiene\s+que\s+quedar.*$", "", raw, flags=re.I).strip(" ,.;")
        match = re.search(rf"\b(?P<verb>{_ACTION_WORDS})\s+(?P<object>.+)", raw, re.I)
        if not match and supplied_verb:
            match = re.match(r"(?P<object>.+)", raw)
            verb = supplied_verb
        elif match:
            verb = match.group("verb")
        else:
            continue
        object_text = match.group("object") if "object" in match.groupdict() else raw
        collaborator_match = re.search(r"\bcon\s+(?P<name>[A-Za-zÁÉÍÓÚÜÑáéíóúüñ.'-]+)", object_text, re.I)
        collaborators: tuple[str, ...] = ()
        context = ""
        if collaborator_match:
            collaborator = _clean_name(collaborator_match.group("name"))
            if collaborator and collaborator != owner:
                collaborators = (collaborator,)
                context = f"Coordinar la actividad con {collaborator}."
            object_text = re.sub(r"\s+con\s+[A-Za-zÁÉÍÓÚÜÑáéíóúüñ.'-]+", "", object_text, flags=re.I)
        title = _title(verb, object_text)
        if title and re.fullmatch(r"Revisar los requisitos", title, re.I):
            prior_agent = next((item.title.removeprefix("Desarrollar ") for item in candidates
                                if item.title.casefold().startswith("desarrollar un agente")), None)
            if prior_agent:
                title = f"Revisar los requisitos del {prior_agent.removeprefix('un ')}"
        if not title:
            continue
        candidates.append(SemanticCandidate(title, owner, collaborators, due_date, due_text, None,
                                             context or raw[:2000], text, .72, "semantic_rule"))
    unique: list[SemanticCandidate] = []
    for candidate in candidates:
        key = (_fold(candidate.title), _fold(candidate.responsible_name or ""))
        if key not in {(_fold(item.title), _fold(item.responsible_name or "")) for item in unique}:
            unique.append(candidate)
    return unique


def parse_llm_response(raw: str, source_text: str) -> list[SemanticCandidate]:
    """Strictly parse a semantic response; code fences are the only repair."""
    cleaned = raw.strip()
    fence = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", cleaned, re.S | re.I)
    if fence:
        cleaned = fence.group(1)
    try:
        response = SemanticResponse.model_validate(json.loads(cleaned))
    except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as exc:
        raise ValueError("semantic JSON invalid") from exc
    source_folded = _fold(source_text)
    candidates = []
    for item in response.activities:
        if _fold(item.evidence) not in source_folded:
            raise ValueError("semantic evidence invalid")
        due = parse_due_date(item.due_date_text)
        candidates.append(SemanticCandidate(item.title, _clean_name(item.responsible_name),
                                             tuple(filter(None, (_clean_name(v) for v in item.collaborators))),
                                             due, item.due_date_text, item.project,
                                             item.context or item.evidence, item.evidence,
                                             item.confidence, "semantic_llm", area=item.area,
                                             activity_evidence=item.activity_evidence or item.evidence,
                                             area_evidence=item.area_evidence,
                                             responsible_evidence=item.responsible_evidence,
                                             collaborators_evidence=item.collaborators_evidence,
                                             responsible_role=item.responsible_role))
    return candidates
