from __future__ import annotations

import re
import sys
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Preformatted,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs" / "documentacion_tecnica_agente_jira_v1.1.md"
OUTPUT = ROOT / "output" / "pdf" / "documentacion_tecnica_agente_jira_v1.1.pdf"

NAVY = colors.HexColor("#0B2948")
BLUE = colors.HexColor("#1976B9")
LIGHT_BLUE = colors.HexColor("#EAF4FB")
PALE = colors.HexColor("#F5F8FA")
GREEN = colors.HexColor("#2D8A61")
AMBER = colors.HexColor("#B87316")
TEXT = colors.HexColor("#182433")
MUTED = colors.HexColor("#607184")
RULE = colors.HexColor("#CFDAE3")


def register_fonts() -> None:
    fonts = Path("C:/Windows/Fonts")
    candidates = {
        "Body": fonts / "arial.ttf",
        "Body-Bold": fonts / "arialbd.ttf",
        "Mono": fonts / "consola.ttf",
    }
    if all(path.exists() for path in candidates.values()):
        for name, path in candidates.items():
            pdfmetrics.registerFont(TTFont(name, str(path)))
    else:
        pdfmetrics.registerFont(TTFont("Body", str(fonts / "segoeui.ttf")))
        pdfmetrics.registerFont(TTFont("Body-Bold", str(fonts / "segoeuib.ttf")))
        pdfmetrics.registerFont(TTFont("Mono", str(fonts / "consola.ttf")))


class NumberedCanvas(canvas.Canvas):
    def showPage(self):
        self._draw_chrome()
        super().showPage()

    def _draw_chrome(self) -> None:
        width, height = A4
        page = self._pageNumber
        self.saveState()
        if page == 1:
            self.setFillColor(NAVY)
            self.rect(0, height - 24 * mm, width, 24 * mm, fill=1, stroke=0)
            self.setFillColor(BLUE)
            self.rect(0, height - 27 * mm, width, 3 * mm, fill=1, stroke=0)
        else:
            self.setStrokeColor(RULE)
            self.line(18 * mm, height - 15 * mm, width - 18 * mm, height - 15 * mm)
            self.setFont("Helvetica-Bold", 8)
            self.setFillColor(NAVY)
            self.drawString(18 * mm, height - 11 * mm, "AGENTE JIRA")
            self.setFont("Helvetica", 8)
            self.setFillColor(MUTED)
            self.drawRightString(
                width - 18 * mm,
                height - 11 * mm,
                "Documentacion tecnica consolidada v1.1",
            )
        self.setStrokeColor(RULE)
        self.line(18 * mm, 15 * mm, width - 18 * mm, 15 * mm)
        self.setFont("Helvetica", 7.5)
        self.setFillColor(MUTED)
        self.drawString(18 * mm, 10 * mm, "Uso interno - Estado al 20 de julio de 2026")
        self.drawRightString(width - 18 * mm, 10 * mm, f"Pagina {page}")
        self.restoreState()


def inline(text: str) -> str:
    value = escape(text.strip())
    value = re.sub(r"`([^`]+)`", r'<font name="Mono" color="#0B5B91">\1</font>', value)
    value = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", value)
    return value


def styles():
    base = getSampleStyleSheet()
    return {
        "cover_kicker": ParagraphStyle(
            "CoverKicker", fontName="Body-Bold", fontSize=10, leading=13,
            textColor=BLUE, spaceAfter=8, tracking=1.4,
        ),
        "cover_title": ParagraphStyle(
            "CoverTitle", fontName="Body-Bold", fontSize=28, leading=33,
            textColor=NAVY, spaceAfter=10,
        ),
        "cover_subtitle": ParagraphStyle(
            "CoverSubtitle", fontName="Body", fontSize=13, leading=18,
            textColor=MUTED, spaceAfter=20,
        ),
        "h1": ParagraphStyle(
            "H1", parent=base["Heading1"], fontName="Body-Bold", fontSize=17,
            leading=21, textColor=NAVY, spaceBefore=12, spaceAfter=8,
            keepWithNext=True,
        ),
        "h2": ParagraphStyle(
            "H2", parent=base["Heading2"], fontName="Body-Bold", fontSize=12,
            leading=15, textColor=BLUE, spaceBefore=9, spaceAfter=5,
            keepWithNext=True,
        ),
        "body": ParagraphStyle(
            "Body", parent=base["BodyText"], fontName="Body", fontSize=9.4,
            leading=13.3, textColor=TEXT, spaceAfter=6, alignment=TA_LEFT,
        ),
        "bullet": ParagraphStyle(
            "Bullet", parent=base["BodyText"], fontName="Body", fontSize=9.2,
            leading=12.8, textColor=TEXT, leftIndent=14, firstLineIndent=-8,
            bulletIndent=3, spaceAfter=3,
        ),
        "small": ParagraphStyle(
            "Small", parent=base["BodyText"], fontName="Body", fontSize=8,
            leading=10.5, textColor=MUTED,
        ),
        "code": ParagraphStyle(
            "Code", fontName="Mono", fontSize=7.8, leading=10.3,
            textColor=NAVY, leftIndent=8, rightIndent=8, borderColor=RULE,
            borderWidth=0.5, borderPadding=8, backColor=PALE, spaceBefore=4,
            spaceAfter=8,
        ),
    }


def table_flow(rows: list[list[str]], page_width: float, s: dict) -> Table:
    count = len(rows[0])
    if count == 2:
        widths = [page_width * 0.30, page_width * 0.70]
    elif count == 3:
        widths = [page_width * 0.18, page_width * 0.19, page_width * 0.63]
    else:
        widths = [page_width / count] * count
    data = [
        [Paragraph(inline(cell), s["small"] if row_index else ParagraphStyle(
            f"TableHeader{row_index}", parent=s["small"], fontName="Body-Bold", textColor=colors.white
        )) for cell in row]
        for row_index, row in enumerate(rows)
    ]
    table = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BACKGROUND", (0, 1), (-1, -1), colors.white),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PALE]),
        ("GRID", (0, 0), (-1, -1), 0.35, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


def parse_table(lines: list[str], start: int) -> tuple[list[list[str]], int]:
    raw = []
    index = start
    while index < len(lines) and lines[index].strip().startswith("|"):
        cells = [cell.strip() for cell in lines[index].strip().strip("|").split("|")]
        raw.append(cells)
        index += 1
    if len(raw) > 1 and all(re.fullmatch(r":?-{3,}:?", cell) for cell in raw[1]):
        raw.pop(1)
    return raw, index


def build_story(source: str, s: dict, page_width: float):
    lines = source.splitlines()
    story = []
    title = lines[0].lstrip("# ")
    story.extend([
        Spacer(1, 35 * mm),
        Paragraph("DOCUMENTO TÉCNICO CONSOLIDADO", s["cover_kicker"]),
        Paragraph(inline(title), s["cover_title"]),
        Paragraph(
            "De la Plantilla Excel v1.1 a la ejecución controlada mediante Atlassian Rovo MCP",
            s["cover_subtitle"],
        ),
    ])
    index = 1
    while index < len(lines) and not lines[index].strip():
        index += 1
    if index < len(lines) and lines[index].strip().startswith("|"):
        rows, index = parse_table(lines, index)
        story.append(table_flow(rows, page_width, s))
    story.extend([
        Spacer(1, 11 * mm),
        Paragraph(
            "Estado seguro actual: Jira en modo de sólo lectura. La preparación del Objetivo 4 no habilita escrituras.",
            ParagraphStyle(
                "CoverCallout", parent=s["body"], fontName="Body-Bold", fontSize=10,
                leading=14, textColor=GREEN, borderColor=colors.HexColor("#B8DEC9"),
                borderWidth=0.8, borderPadding=10, backColor=colors.HexColor("#EEF8F2"),
            ),
        ),
        PageBreak(),
    ])

    paragraph_buffer: list[str] = []

    def flush_paragraph():
        if paragraph_buffer:
            story.append(Paragraph(inline(" ".join(paragraph_buffer)), s["body"]))
            paragraph_buffer.clear()

    in_code = False
    code_lines: list[str] = []
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if stripped.startswith("```"):
            flush_paragraph()
            if in_code:
                story.append(Preformatted("\n".join(code_lines), s["code"]))
                code_lines.clear()
                in_code = False
            else:
                in_code = True
            index += 1
            continue
        if in_code:
            code_lines.append(line)
            index += 1
            continue
        if not stripped:
            flush_paragraph()
            index += 1
            continue
        if stripped.startswith("|"):
            flush_paragraph()
            rows, index = parse_table(lines, index)
            story.append(Spacer(1, 2 * mm))
            story.append(table_flow(rows, page_width, s))
            story.append(Spacer(1, 4 * mm))
            continue
        if stripped.startswith("### "):
            flush_paragraph()
            story.append(Paragraph(inline(stripped[4:]), s["h2"]))
        elif stripped.startswith("## "):
            flush_paragraph()
            story.append(Paragraph(inline(stripped[3:]), s["h1"]))
        elif re.match(r"^\d+\.\s", stripped):
            flush_paragraph()
            number, text = stripped.split(". ", 1)
            story.append(Paragraph(inline(text), s["bullet"], bulletText=f"{number}."))
        elif stripped.startswith("- "):
            flush_paragraph()
            story.append(Paragraph(inline(stripped[2:]), s["bullet"], bulletText="-"))
        else:
            paragraph_buffer.append(stripped)
        index += 1
    flush_paragraph()
    return story


def main() -> int:
    register_fonts()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    source = SOURCE.read_text(encoding="utf-8")
    s = styles()
    width, height = A4
    frame = Frame(
        18 * mm,
        18 * mm,
        width - 36 * mm,
        height - 36 * mm,
        leftPadding=0,
        rightPadding=0,
        topPadding=3 * mm,
        bottomPadding=3 * mm,
    )
    document = BaseDocTemplate(
        str(OUTPUT),
        pagesize=A4,
        title="Agente Jira - Documentación técnica consolidada v1.1",
        author="Proyecto Agente Jira",
        subject="Estado técnico, arquitectura y preparación del Objetivo 4",
    )
    document.addPageTemplates([PageTemplate(id="all", frames=[frame])])
    story = build_story(source, s, width - 36 * mm)
    document.build(story, canvasmaker=NumberedCanvas)
    print(OUTPUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
