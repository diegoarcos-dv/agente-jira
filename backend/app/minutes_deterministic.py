"""Conservative, source-preserving extraction for explicit minutes sections.

This module deliberately has no network or Jira dependencies.  It identifies
candidate actions from sections that explicitly name pending work; a separate
LLM step may enrich the candidates, but can never change their identity or
evidence.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher


SECTION_NAMES = (
    "Pendientes", "Acuerdos", "Compromisos", "Acciones",
    "Próximos pasos", "Tareas", "Seguimiento",
)


def _fold(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in value if not unicodedata.combining(ch)).casefold()


_SECTION_KEYS = {_fold(name): name for name in SECTION_NAMES}
_BULLET_RE = re.compile(r"^\s*(?:(?:[-*•‣▪◦])\s+|\d+\s*[.)]\s+|[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]\s*[.)]\s+)")
_HEADING_RE = re.compile(r"^\s*(?P<name>[A-Za-zÁÉÍÓÚÜÑáéíóúüñ][^:]*)\s*:?[ \t]*$")
_INLINE_HEADING_RE = re.compile(r"(?i)(?<!\w)(pendientes|acuerdos|compromisos|acciones|próximos\s+pasos|tareas|seguimiento)\s*:\s*")
_ACTION_RE = re.compile(
    r"^(?:acordar|actualizar|analizar|asignar|cerrar|completar|confirmar|coordinar|crear|definir|documentar|ejecutar|enviar|establecer|evaluar|formalizar|generar|implementar|preparar|publicar|revisar|validar|verificar|realizar|solicitar|programar|notificar|dar|hacer|mantener|resolver|seleccionar|definir)\b",
    re.IGNORECASE,
)
_SIGNOFF_RE = re.compile(r"^(?:quedamos\s+atentos|saludos(?:\s+cordiales)?|atentamente|equipo\s+vic)\.?$", re.IGNORECASE)
_UNHEADED_TASK_NOUN_RE = re.compile(
    r"^(?:dar\s+seguimiento\s+a|seguimiento\s+(?:de|a)|revision\s+de|validacion\s+de|"
    r"coordinacion\s+de|actualizacion\s+de|implementacion\s+de|preparacion\s+de|"
    r"entrega\s+de|elaboracion\s+de|atencion\s+de|correccion\s+de|solicitud\s+de|gestion\s+de)\b",
    re.IGNORECASE,
)
_UNHEADED_COMMITMENT_RE = re.compile(
    r"\b(?:responsable\s*:|a\s+cargo\s+de|asignad[oa]\s+(?:a|:)|se\s+compromete|"
    r"deber[aá]|fecha\s+(?:objetivo|de\s+entrega)\s*:|(?:20\d{2}-\d{1,2}-\d{1,2})|"
    r"\d{1,2}/\d{1,2}/20\d{2})\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ExplicitCandidate:
    candidate_id: str
    source_section: str
    source_evidence: str
    source_start: int
    source_end: int
    normalized_text: str
    context: str = ""
    possible_duplicate: bool = False
    requires_review: bool = True


@dataclass(frozen=True)
class DeterministicExtraction:
    candidates: tuple[ExplicitCandidate, ...]
    sections: tuple[str, ...]
    extraction_mode: str
    warnings: tuple[str, ...] = ()


def _is_heading(line: str) -> str | None:
    match = _HEADING_RE.match(line)
    if not match:
        return None
    return _SECTION_KEYS.get(_fold(match.group("name").strip()))


def _strip_marker(line: str) -> tuple[str, bool]:
    match = _BULLET_RE.match(line)
    if match:
        return line[match.end():].strip(), True
    return line.strip(), False


def _looks_like_label(line: str) -> bool:
    """Teams/labels in a colon continuation are not independent activities."""
    text, _ = _strip_marker(line)
    if not text:
        return True
    if _ACTION_RE.match(text):
        return False
    # A continuation is usually a short noun phrase.  Long declarative lines
    # are safer as a separate candidate.
    return len(text.split()) <= 12 and not re.search(r"[.!?]$", text)


def _split_inline_actions(text: str) -> list[str]:
    parts: list[str] = []
    for semicolon_part in re.split(r"\s*;\s*", text):
        semicolon_part = semicolon_part.strip()
        if not semicolon_part:
            continue
        pieces = re.split(r"\s+y\s+(?=(?:acordar|actualizar|analizar|asignar|cerrar|completar|confirmar|coordinar|crear|definir|documentar|ejecutar|enviar|establecer|evaluar|formalizar|generar|implementar|preparar|publicar|revisar|validar|verificar|realizar|solicitar|programar|notificar|resolver|seleccionar)\b)", semicolon_part, flags=re.IGNORECASE)
        parts.extend(piece.strip() for piece in pieces if piece.strip())
    return parts


def _candidate_blocks(lines: list[str]) -> list[tuple[str, int, int]]:
    blocks: list[tuple[str, int, int]] = []
    current: list[str] = []
    start = 0
    continuation = False
    continuation_group = False
    for index, raw in enumerate(lines):
        text, marked = _strip_marker(raw)
        if not text:
            continue
        if not continuation_group and _SIGNOFF_RE.match(text):
            if current:
                blocks.append(("\n".join(current), start, index - 1))
                current = []
            continuation = continuation_group = False
            continue
        if not current:
            current, start, continuation = [text], index, text.endswith(":")
            continuation_group = continuation
            continue
        if continuation_group and _looks_like_label(raw):
            current.append(text)
            continuation = text.endswith(":")
            continue
        # Bullets and numbering are strong boundaries.  For unmarked prose,
        # action verbs and sentence boundaries are conservative boundaries too.
        if marked or _ACTION_RE.match(text) or not continuation:
            blocks.append((" ".join(current), start, index - 1))
            current, start, continuation = [text], index, text.endswith(":")
            continuation_group = continuation
        else:
            current.append(text)
            continuation = text.endswith(":")
    if current:
        blocks.append((" ".join(current), start, len(lines) - 1))
    return blocks


def _unheaded_list_candidates(text: str) -> list[ExplicitCandidate]:
    """Recover clearly task-like marked list items outside a named section.

    Meeting notes often contain numbered follow-ups without a ``Pendientes``
    heading.  Only list items with an explicit action verb, a recognized
    follow-up noun phrase, or a clear commitment/deadline marker are admitted;
    ordinary agenda topics and unstructured prose remain untouched.
    """
    lines = text.splitlines()
    items: list[tuple[int, int, list[str], str]] = []
    current_start: int | None = None
    current_lines: list[str] = []

    def flush(end_index: int) -> None:
        nonlocal current_start, current_lines
        if current_start is not None and current_lines:
            first_body, _ = _strip_marker(current_lines[0])
            body = " ".join([first_body, *(value.strip() for value in current_lines[1:])]).strip()
            folded = _fold(body)
            explicit_signal = bool(
                _ACTION_RE.match(first_body)
                or _UNHEADED_TASK_NOUN_RE.match(folded)
                or _UNHEADED_COMMITMENT_RE.search(folded)
            )
            if explicit_signal and len(body.split()) >= 3:
                items.append((current_start, end_index, current_lines[:], body.rstrip(".")))
        current_start = None
        current_lines = []

    for index, raw in enumerate(lines):
        stripped = raw.strip()
        if not stripped:
            if current_start is not None:
                flush(index - 1)
            continue
        _, marked = _strip_marker(raw)
        if marked:
            if current_start is not None:
                flush(index - 1)
            current_start, current_lines = index, [raw]
            continue
        # Indented continuation lines belong to the preceding marked item.
        if current_start is not None and raw[:1].isspace():
            current_lines.append(raw)
        elif current_start is not None:
            flush(index - 1)
    if current_start is not None:
        flush(len(lines) - 1)

    candidates: list[ExplicitCandidate] = []
    for start_line, _end_line, evidence_lines, normalized in items:
        evidence = "\n".join(value.strip() for value in evidence_lines if value.strip())
        source_start = text.find(evidence)
        if source_start < 0:
            source_start = sum(len(line) + 1 for line in lines[:start_line])
        candidates.append(ExplicitCandidate(
            candidate_id=f"ACT-{len(candidates) + 1:03d}",
            source_section="Lista sin encabezado",
            source_evidence=evidence,
            source_start=source_start,
            source_end=source_start + len(evidence),
            normalized_text=normalized,
        ))
    return candidates


def extract_explicit(normalized_text: str) -> DeterministicExtraction:
    """Extract only actions under a recognized explicit section.

    Evidence is copied from the normalized input and offsets point into that
    exact string.  If no recognized section exists, no candidates are guessed.
    """
    lines = normalized_text.splitlines()
    candidates: list[ExplicitCandidate] = []
    sections: list[str] = []
    warnings: list[str] = []
    offset = 0
    active: str | None = None
    section_lines: list[str] = []
    section_start_offset = 0

    def flush() -> None:
        nonlocal section_lines, section_start_offset
        if not active or not section_lines:
            section_lines = []
            return
        for block, begin, end in _candidate_blocks(section_lines):
            evidence = "\n".join(line.strip() for line in section_lines[begin:end + 1] if line.strip())
            # Ignore accidental section prose that is too short to be useful.
            if len(evidence) < 3:
                continue
            local_prefix = "\n".join(section_lines[:begin])
            start = section_start_offset + (len(local_prefix) + (1 if local_prefix else 0))
            # Offsets are best effort after whitespace normalization; evidence
            # itself remains authoritative and is always checked by validation.
            end_offset = start + len(evidence)
            candidates.append(ExplicitCandidate(
                candidate_id=f"ACT-{len(candidates) + 1:03d}",
                source_section=active,
                source_evidence=evidence,
                source_start=start,
                source_end=end_offset,
                normalized_text=block.rstrip("."),
            ))
        section_lines = []

    for line in lines + [""]:
        heading = _is_heading(line)
        inline_rest = None
        if not heading:
            # Only a label at the beginning of a line starts a section.  Text
            # such as "Tipo de seguimiento: Semanal" inside an activity must
            # remain part of that activity and its evidence.
            inline = _INLINE_HEADING_RE.match(line)
            if inline:
                heading = _SECTION_KEYS.get(_fold(inline.group(1)))
                inline_rest = line[inline.end():].strip()
        if heading:
            flush()
            active = heading
            sections.append(heading)
            section_start_offset = offset + len(line) + 1
            if inline_rest:
                section_lines.extend(_split_inline_actions(inline_rest))
            offset += len(line) + 1
            continue
        if active is not None and line.strip():
            section_lines.append(line)
        elif active is not None and not line.strip():
            # Blank lines terminate an explicit section only when the next
            # non-empty line is another heading; keeping them here allows
            # multiline candidates without inventing an action.
            pass
        offset += len(line) + 1
    flush()

    # The named-section path remains unchanged.  If the document has no
    # recognized section, recover only task-like entries from marked lists.
    if not sections:
        candidates.extend(_unheaded_list_candidates(normalized_text))
        if candidates:
            warnings.append("Se detectaron actividades en una lista sin encabezado; confirma que sean compromisos vigentes.")

    # Exact duplicate candidates are removed; fuzzy matches remain visible and
    # are marked for review rather than silently discarded.
    unique: list[ExplicitCandidate] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = _fold(candidate.source_evidence)
        if key in seen:
            warnings.append("Se omitió una actividad exactamente duplicada.")
            continue
        seen.add(key)
        current_fold = _fold(candidate.normalized_text)
        possible = any(
            SequenceMatcher(None, current_fold, _fold(prev.normalized_text)).ratio() >= .60
            or (len(current_fold.split()) >= 2 and " ".join(current_fold.split()[:2]) == " ".join(_fold(prev.normalized_text).split()[:2]))
            for prev in unique
        )
        unique.append(ExplicitCandidate(**{**candidate.__dict__, "possible_duplicate": possible}))
        if possible and len(unique) > 1:
            warnings.append("Hay actividades parecidas que requieren revisión.")

    # IDs are deterministic for the normalized document and contiguous after
    # exact duplicate removal.
    unique = [ExplicitCandidate(**{**candidate.__dict__, "candidate_id": f"ACT-{index:03d}"})
              for index, candidate in enumerate(unique, 1)]
    mode = ("DETERMINISTIC_EXPLICIT" if sections and unique else
            "DETERMINISTIC_LIST" if unique else
            "DETERMINISTIC_FALLBACK" if sections else "LLM_INFERRED")
    return DeterministicExtraction(tuple(unique), tuple(dict.fromkeys(sections)), mode, tuple(dict.fromkeys(warnings)))
