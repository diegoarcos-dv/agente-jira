from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from openpyxl import load_workbook
from openpyxl.utils.datetime import from_excel

from .errors import ValidationIssue, WorkbookValidationError


CAPTURE_SHEET = "PLAN_DE_TRABAJO"
HEADER_ROW = 5
FIRST_DATA_ROW = 6
LAST_DATA_ROW = 55
EXPECTED_HEADERS = (
    "Actividad *",
    "Responsable *",
    "Frente_de_trabajo_o_Proyecto",
    "Contexto_o_Resultado",
    "Fecha_Objetivo",
    "Estado_Actual",
    "Comentarios",
)
ALLOWED_STATES = {
    "Pendiente",
    "En curso",
    "En pausa",
    "Completada",
    "Rechazada",
    "Por confirmar",
}
STATE_ALIASES = {
    "pendiente": "Pendiente",
    "en curso": "En curso",
    "en proceso": "En curso",
    "en pausa": "En pausa",
    "pausada": "En pausa",
    "completada": "Completada",
    "completado": "Completada",
    "terminada": "Completada",
    "terminado": "Completada",
    "rechazada": "Rechazada",
    "rechazado": "Rechazada",
    "cancelada": "Rechazada",
    "cancelado": "Rechazada",
    "por confirmar": "Por confirmar",
}


@dataclass(frozen=True)
class ParsedPlan:
    filename: str
    sha256: str
    rows: list[dict[str, Any]]


def clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or None


def normalize_state(value: Any) -> str:
    text = clean_text(value)
    if not text:
        return "Pendiente"
    return STATE_ALIASES.get(text.casefold(), text)


def normalize_date(value: Any, epoch: datetime) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (int, float)):
        try:
            converted = from_excel(value, epoch=epoch)
            return (
                converted.date().isoformat()
                if isinstance(converted, datetime)
                else converted.isoformat()
            )
        except (ValueError, OverflowError, TypeError):
            return None

    text = clean_text(value)
    if not text:
        return None
    for format_string in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(text, format_string).date().isoformat()
        except ValueError:
            continue
    return None


class TemplateParser:
    def parse(self, filename: str, content: bytes) -> ParsedPlan:
        issues: list[ValidationIssue] = []
        if not filename.lower().endswith(".xlsx"):
            raise WorkbookValidationError(
                "El archivo debe tener extensión .xlsx.",
                [ValidationIssue("INVALID_EXTENSION", "Sólo se acepta la plantilla .xlsx.")],
            )
        if not content:
            raise WorkbookValidationError(
                "El archivo está vacío.",
                [ValidationIssue("EMPTY_FILE", "Selecciona un archivo Excel con contenido.")],
            )

        try:
            workbook = load_workbook(io.BytesIO(content), data_only=False, read_only=False)
        except Exception as exc:
            raise WorkbookValidationError(
                "No fue posible abrir el archivo Excel.",
                [ValidationIssue("INVALID_XLSX", f"El archivo no es un .xlsx válido: {exc}")],
            ) from exc

        if CAPTURE_SHEET not in workbook.sheetnames:
            raise WorkbookValidationError(
                "La plantilla no contiene la hoja de captura requerida.",
                [
                    ValidationIssue(
                        "MISSING_SHEET",
                        f"Se esperaba la hoja '{CAPTURE_SHEET}'.",
                    )
                ],
            )

        sheet = workbook[CAPTURE_SHEET]
        actual_headers = tuple(clean_text(sheet.cell(HEADER_ROW, col).value) for col in range(1, 8))
        if actual_headers != EXPECTED_HEADERS:
            for index, (expected, actual) in enumerate(zip(EXPECTED_HEADERS, actual_headers), 1):
                if actual != expected:
                    issues.append(
                        ValidationIssue(
                            "INVALID_HEADER",
                            f"Se esperaba '{expected}' y se encontró '{actual or '(vacío)'}'.",
                            row=HEADER_ROW,
                            column=sheet.cell(HEADER_ROW, index).column_letter,
                        )
                    )
            raise WorkbookValidationError(
                "Los encabezados no corresponden a la Plantilla Excel v1.1.",
                issues,
            )

        version_text = clean_text(sheet["A3"].value) or ""
        if "v1.1" not in version_text.casefold():
            raise WorkbookValidationError(
                "No se pudo confirmar la versión 1.1 de la plantilla.",
                [
                    ValidationIssue(
                        "INVALID_TEMPLATE_VERSION",
                        "La celda A3 debe identificar la plantilla como v1.1.",
                        row=3,
                        column="A",
                    )
                ],
            )

        rows: list[dict[str, Any]] = []
        for row_number in range(FIRST_DATA_ROW, LAST_DATA_ROW + 1):
            values = [sheet.cell(row_number, col).value for col in range(1, 8)]
            activity = clean_text(values[0])
            responsible = clean_text(values[1])
            optional_values = [
                clean_text(values[2]),
                clean_text(values[3]),
                values[4],
                clean_text(values[6]),
            ]
            state = normalize_state(values[5])
            is_empty_reserved_row = (
                not activity
                and not responsible
                and not any(optional_values)
                and state == "Pendiente"
            )
            if is_empty_reserved_row:
                continue

            if not activity:
                issues.append(
                    ValidationIssue(
                        "MISSING_ACTIVITY",
                        "La actividad es obligatoria.",
                        row=row_number,
                        column="A",
                    )
                )
            if not responsible:
                issues.append(
                    ValidationIssue(
                        "MISSING_ASSIGNEE",
                        "El responsable principal es obligatorio.",
                        row=row_number,
                        column="B",
                    )
                )
            if state not in ALLOWED_STATES:
                issues.append(
                    ValidationIssue(
                        "INVALID_STATE",
                        f"El estado '{state}' no pertenece al catálogo v1.1.",
                        row=row_number,
                        column="F",
                    )
                )

            normalized_date = normalize_date(values[4], workbook.epoch)
            if values[4] not in (None, "") and normalized_date is None:
                issues.append(
                    ValidationIssue(
                        "INVALID_DATE",
                        "La fecha debe ser una fecha Excel o usar el formato AAAA-MM-DD.",
                        row=row_number,
                        column="E",
                    )
                )

            if activity and responsible and state in ALLOWED_STATES:
                rows.append(
                    {
                        "source_row": row_number,
                        "actividad": activity,
                        "responsable_display": responsible,
                        "frente_trabajo_origen": clean_text(values[2]),
                        "contexto_resultado": clean_text(values[3]),
                        "fecha_objetivo": normalized_date,
                        "estado_actual": state,
                        "comentarios": clean_text(values[6]),
                    }
                )

        if issues:
            raise WorkbookValidationError(
                f"Se encontraron {len(issues)} problemas en las filas capturadas.",
                issues,
            )
        if not rows:
            raise WorkbookValidationError(
                "La plantilla no contiene actividades.",
                [
                    ValidationIssue(
                        "NO_ACTIVITIES",
                        "Captura al menos una actividad y un responsable entre las filas 6 y 55.",
                    )
                ],
            )
        return ParsedPlan(
            filename=filename,
            sha256=hashlib.sha256(content).hexdigest(),
            rows=rows,
        )

