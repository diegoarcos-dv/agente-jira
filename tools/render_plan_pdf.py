from __future__ import annotations

import html
import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    HRFlowable,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Preformatted,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.tableofcontents import TableOfContents


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs" / "plan_tecnico_agente_jira_v0.6.md"
OUTPUT = ROOT / "output" / "pdf" / "plan_tecnico_agente_jira_v0.6.pdf"

PAGE_WIDTH, PAGE_HEIGHT = A4
LEFT = 18 * mm
RIGHT = 18 * mm
TOP = 20 * mm
BOTTOM = 18 * mm
CONTENT_WIDTH = PAGE_WIDTH - LEFT - RIGHT

NAVY = colors.HexColor("#17365D")
BLUE = colors.HexColor("#1F5E93")
CYAN = colors.HexColor("#2D8FC4")
PALE_BLUE = colors.HexColor("#EAF3F8")
PALE_GRAY = colors.HexColor("#F4F6F8")
MID_GRAY = colors.HexColor("#64748B")
DARK = colors.HexColor("#1F2937")
RULE = colors.HexColor("#C9D4DF")
WHITE = colors.white


def register_fonts() -> tuple[str, str, str, str]:
    font_dir = Path("C:/Windows/Fonts")
    candidates = {
        "body": ("SegoeUI", font_dir / "segoeui.ttf"),
        "bold": ("SegoeUI-Semibold", font_dir / "seguisb.ttf"),
        "italic": ("SegoeUI-Italic", font_dir / "segoeuii.ttf"),
        "mono": ("Consolas", font_dir / "consola.ttf"),
    }
    if all(path.exists() for _, path in candidates.values()):
        for name, path in candidates.values():
            pdfmetrics.registerFont(TTFont(name, str(path)))
        pdfmetrics.registerFontFamily(
            "SegoeUI",
            normal="SegoeUI",
            bold="SegoeUI-Semibold",
            italic="SegoeUI-Italic",
            boldItalic="SegoeUI-Semibold",
        )
        return "SegoeUI", "SegoeUI-Semibold", "SegoeUI-Italic", "Consolas"
    return "Helvetica", "Helvetica-Bold", "Helvetica-Oblique", "Courier"


BODY_FONT, BOLD_FONT, ITALIC_FONT, MONO_FONT = register_fonts()


def make_styles():
    sample = getSampleStyleSheet()
    return {
        "body": ParagraphStyle(
            "Body",
            parent=sample["BodyText"],
            fontName=BODY_FONT,
            fontSize=9.2,
            leading=13.1,
            textColor=DARK,
            spaceAfter=5.5,
            allowWidows=0,
            allowOrphans=0,
        ),
        "small": ParagraphStyle(
            "Small",
            parent=sample["BodyText"],
            fontName=BODY_FONT,
            fontSize=7.5,
            leading=10,
            textColor=MID_GRAY,
        ),
        "h1": ParagraphStyle(
            "Heading1",
            parent=sample["Heading1"],
            fontName=BOLD_FONT,
            fontSize=16,
            leading=20,
            textColor=NAVY,
            spaceBefore=13,
            spaceAfter=7,
            keepWithNext=True,
        ),
        "h2": ParagraphStyle(
            "Heading2",
            parent=sample["Heading2"],
            fontName=BOLD_FONT,
            fontSize=12.2,
            leading=15.5,
            textColor=BLUE,
            spaceBefore=10,
            spaceAfter=5,
            keepWithNext=True,
        ),
        "h3": ParagraphStyle(
            "Heading3",
            parent=sample["Heading3"],
            fontName=BOLD_FONT,
            fontSize=10.2,
            leading=13.2,
            textColor=CYAN,
            spaceBefore=7,
            spaceAfter=4,
            keepWithNext=True,
        ),
        "h4": ParagraphStyle(
            "Heading4",
            parent=sample["Heading4"],
            fontName=BOLD_FONT,
            fontSize=9.4,
            leading=12.2,
            textColor=NAVY,
            spaceBefore=6,
            spaceAfter=3,
            keepWithNext=True,
        ),
        "bullet": ParagraphStyle(
            "Bullet",
            parent=sample["BodyText"],
            fontName=BODY_FONT,
            fontSize=9,
            leading=12.5,
            leftIndent=12,
            firstLineIndent=-7,
            spaceAfter=2.8,
            textColor=DARK,
        ),
        "number": ParagraphStyle(
            "Number",
            parent=sample["BodyText"],
            fontName=BODY_FONT,
            fontSize=9,
            leading=12.5,
            leftIndent=16,
            firstLineIndent=-12,
            spaceAfter=3,
            textColor=DARK,
        ),
        "code": ParagraphStyle(
            "Code",
            parent=sample["Code"],
            fontName=MONO_FONT,
            fontSize=7.2,
            leading=9.6,
            leftIndent=7,
            rightIndent=7,
            borderColor=RULE,
            borderWidth=0.5,
            borderPadding=7,
            backColor=PALE_GRAY,
            textColor=colors.HexColor("#263238"),
            spaceBefore=4,
            spaceAfter=7,
        ),
        "table": ParagraphStyle(
            "TableCell",
            parent=sample["BodyText"],
            fontName=BODY_FONT,
            fontSize=7.35,
            leading=9.4,
            textColor=DARK,
        ),
        "table_header": ParagraphStyle(
            "TableHeader",
            parent=sample["BodyText"],
            fontName=BOLD_FONT,
            fontSize=7.4,
            leading=9.4,
            textColor=WHITE,
        ),
        "toc_title": ParagraphStyle(
            "TOCTitle",
            parent=sample["Heading1"],
            fontName=BOLD_FONT,
            fontSize=20,
            leading=24,
            textColor=NAVY,
            spaceAfter=12,
        ),
        "cover_title": ParagraphStyle(
            "CoverTitle",
            parent=sample["Title"],
            fontName=BOLD_FONT,
            fontSize=28,
            leading=34,
            textColor=WHITE,
            alignment=TA_LEFT,
            spaceAfter=8,
        ),
        "cover_subtitle": ParagraphStyle(
            "CoverSubtitle",
            parent=sample["BodyText"],
            fontName=BODY_FONT,
            fontSize=13,
            leading=18,
            textColor=colors.HexColor("#DCEAF5"),
        ),
        "cover_meta": ParagraphStyle(
            "CoverMeta",
            parent=sample["BodyText"],
            fontName=BODY_FONT,
            fontSize=10,
            leading=15,
            textColor=WHITE,
        ),
    }


STYLES = make_styles()


def inline_markup(text: str) -> str:
    placeholders: list[str] = []

    def hold(value: str) -> str:
        placeholders.append(value)
        return f"@@PH{len(placeholders) - 1}@@"

    text = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        lambda m: hold(
            f'<link href="{html.escape(m.group(2), quote=True)}" color="#1F5E93">'
            f"{html.escape(m.group(1))}</link>"
        ),
        text,
    )
    text = re.sub(
        r"`([^`]+)`",
        lambda m: hold(
            f'<font name="{MONO_FONT}" color="#354B5E">{html.escape(m.group(1))}</font>'
        ),
        text,
    )
    text = html.escape(text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<i>\1</i>", text)
    for idx, value in enumerate(placeholders):
        text = text.replace(f"@@PH{idx}@@", value)
    return text


def parse_table(lines: list[str]) -> Table:
    rows: list[list[str]] = []
    for line in lines:
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-{3,}:?", cell or "") for cell in cells):
            continue
        rows.append(cells)
    columns = max(len(row) for row in rows)
    normalized = [row + [""] * (columns - len(row)) for row in rows]
    data = []
    for row_idx, row in enumerate(normalized):
        style = STYLES["table_header"] if row_idx == 0 else STYLES["table"]
        data.append([Paragraph(inline_markup(cell), style) for cell in row])

    longest = [max(len(row[col]) for row in normalized) for col in range(columns)]
    total = sum(max(8, n) for n in longest)
    widths = [CONTENT_WIDTH * max(8, n) / total for n in longest]
    min_width = 23 * mm
    if columns <= 4:
        widths = [max(min_width, width) for width in widths]
        scale = CONTENT_WIDTH / sum(widths)
        widths = [width * scale for width in widths]
    else:
        widths = [CONTENT_WIDTH / columns] * columns

    table = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    commands = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.35, RULE),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    for row_idx in range(1, len(data)):
        commands.append(
            ("BACKGROUND", (0, row_idx), (-1, row_idx), WHITE if row_idx % 2 else PALE_BLUE)
        )
    table.setStyle(TableStyle(commands))
    return table


def markdown_flowables(text: str):
    lines = text.splitlines()
    flowables = []
    paragraph: list[str] = []
    in_code = False
    code_language = ""
    code_lines: list[str] = []
    first_title_skipped = False

    def flush_paragraph():
        nonlocal paragraph
        if paragraph:
            joined = " ".join(item.strip() for item in paragraph)
            flowables.append(Paragraph(inline_markup(joined), STYLES["body"]))
            paragraph = []

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped.startswith("```"):
            flush_paragraph()
            if not in_code:
                in_code = True
                code_language = stripped[3:].strip()
                code_lines = []
            else:
                code_text = "\n".join(code_lines)
                flowables.append(Preformatted(code_text, STYLES["code"], maxLineLength=92))
                in_code = False
                code_language = ""
                code_lines = []
            i += 1
            continue
        if in_code:
            code_lines.append(line.replace("\t", "    "))
            i += 1
            continue

        if stripped.startswith("|") and stripped.endswith("|"):
            flush_paragraph()
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith("|") and lines[i].strip().endswith("|"):
                table_lines.append(lines[i])
                i += 1
            flowables.append(parse_table(table_lines))
            flowables.append(Spacer(1, 6))
            continue

        heading = re.match(r"^(#{1,4})\s+(.+)$", stripped)
        if heading:
            flush_paragraph()
            level = len(heading.group(1))
            title = heading.group(2).strip()
            if level == 1 and not first_title_skipped:
                first_title_skipped = True
                i += 1
                continue
            flowables.append(Paragraph(inline_markup(title), STYLES[f"h{level}"]))
            i += 1
            continue

        bullet = re.match(r"^(\s*)[-*]\s+(.+)$", line)
        if bullet:
            flush_paragraph()
            depth = len(bullet.group(1).replace("\t", "    ")) // 2
            style = ParagraphStyle(
                f"Bullet{depth}",
                parent=STYLES["bullet"],
                leftIndent=12 + depth * 11,
                firstLineIndent=-7,
            )
            flowables.append(Paragraph(f"•&nbsp;&nbsp;{inline_markup(bullet.group(2))}", style))
            i += 1
            continue

        numbered = re.match(r"^(\s*)(\d+)\.\s+(.+)$", line)
        if numbered:
            flush_paragraph()
            depth = len(numbered.group(1).replace("\t", "    ")) // 2
            style = ParagraphStyle(
                f"Number{depth}",
                parent=STYLES["number"],
                leftIndent=16 + depth * 11,
                firstLineIndent=-12,
            )
            flowables.append(
                Paragraph(
                    f"{numbered.group(2)}.&nbsp;&nbsp;{inline_markup(numbered.group(3))}", style
                )
            )
            i += 1
            continue

        if stripped in {"---", "***"}:
            flush_paragraph()
            flowables.append(Spacer(1, 3))
            flowables.append(HRFlowable(width="100%", thickness=0.5, color=RULE))
            flowables.append(Spacer(1, 3))
            i += 1
            continue

        if not stripped:
            flush_paragraph()
        else:
            paragraph.append(stripped)
        i += 1

    flush_paragraph()
    return flowables


class PlanDocument(BaseDocTemplate):
    def __init__(self, filename: Path):
        super().__init__(
            str(filename),
            pagesize=A4,
            leftMargin=LEFT,
            rightMargin=RIGHT,
            topMargin=TOP,
            bottomMargin=BOTTOM,
            title="Plan técnico - Agente de generación controlada de work items en Jira",
            author="Equipo del proyecto Agente Jira",
            subject="Plan técnico v0.6",
        )
        frame = Frame(LEFT, BOTTOM, CONTENT_WIDTH, PAGE_HEIGHT - TOP - BOTTOM, id="normal")
        self.addPageTemplates(
            [
                PageTemplate(id="cover", frames=frame, onPage=self.cover_page),
                PageTemplate(id="body", frames=frame, onPage=self.body_page),
            ]
        )
        self._bookmark_counter = 0

    def beforeDocument(self):
        self._bookmark_counter = 0

    def afterFlowable(self, flowable):
        if isinstance(flowable, Paragraph) and flowable.style.name in {"Heading1", "Heading2", "Heading3", "Heading4"}:
            # El H1 principal vive en la portada; los H2 del Markdown son secciones raíz.
            level = {"Heading1": 0, "Heading2": 0, "Heading3": 1, "Heading4": 2}[flowable.style.name]
            text = flowable.getPlainText()
            key = f"heading-{self._bookmark_counter}"
            self._bookmark_counter += 1
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(text, key, level=level, closed=False)
            if flowable.style.name != "Heading4":
                self.notify("TOCEntry", (level, text, self.page, key))

    def cover_page(self, canvas, doc):
        canvas.saveState()
        canvas.setFillColor(NAVY)
        canvas.rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT, fill=1, stroke=0)
        canvas.setFillColor(CYAN)
        canvas.rect(0, PAGE_HEIGHT - 12 * mm, PAGE_WIDTH, 12 * mm, fill=1, stroke=0)
        canvas.setFillColor(colors.HexColor("#244C75"))
        canvas.circle(PAGE_WIDTH - 22 * mm, 27 * mm, 44 * mm, fill=1, stroke=0)
        canvas.restoreState()

    def body_page(self, canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(RULE)
        canvas.setLineWidth(0.4)
        canvas.line(LEFT, PAGE_HEIGHT - 12 * mm, PAGE_WIDTH - RIGHT, PAGE_HEIGHT - 12 * mm)
        canvas.setFont(BODY_FONT, 7.2)
        canvas.setFillColor(MID_GRAY)
        canvas.drawString(LEFT, PAGE_HEIGHT - 9 * mm, "AGENTE JIRA · PLAN TÉCNICO V0.6")
        canvas.drawRightString(PAGE_WIDTH - RIGHT, PAGE_HEIGHT - 9 * mm, "16 JULIO 2026")
        canvas.line(LEFT, 12 * mm, PAGE_WIDTH - RIGHT, 12 * mm)
        canvas.drawString(LEFT, 8.2 * mm, "Documento técnico de trabajo")
        canvas.drawRightString(PAGE_WIDTH - RIGHT, 8.2 * mm, f"Página {doc.page}")
        canvas.restoreState()


def build_pdf():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    source_text = SOURCE.read_text(encoding="utf-8")

    toc = TableOfContents()
    toc.levelStyles = [
        ParagraphStyle(
            "TOC1",
            fontName=BOLD_FONT,
            fontSize=9.2,
            leading=13,
            leftIndent=0,
            firstLineIndent=0,
            textColor=NAVY,
            spaceBefore=3,
        ),
        ParagraphStyle(
            "TOC2",
            fontName=BODY_FONT,
            fontSize=8.2,
            leading=11.5,
            leftIndent=12,
            firstLineIndent=0,
            textColor=DARK,
        ),
        ParagraphStyle(
            "TOC3",
            fontName=BODY_FONT,
            fontSize=7.7,
            leading=10.5,
            leftIndent=24,
            firstLineIndent=0,
            textColor=MID_GRAY,
        ),
    ]

    story = [
        Spacer(1, 35 * mm),
        Paragraph("Plan técnico", STYLES["cover_title"]),
        Paragraph(
            "Agente de generación controlada de work items en Jira",
            STYLES["cover_subtitle"],
        ),
        Spacer(1, 16 * mm),
        HRFlowable(width="42%", thickness=2, color=CYAN, hAlign="LEFT"),
        Spacer(1, 8 * mm),
        Paragraph(
            "Plantilla v1.1 congelada · AWS · AgentCore · Vertex AI · Rovo MCP",
            STYLES["cover_subtitle"],
        ),
        Spacer(1, 68 * mm),
        Table(
            [
                [Paragraph("Versión", STYLES["cover_meta"]), Paragraph("0.6", STYLES["cover_meta"])],
                [Paragraph("Fecha", STYLES["cover_meta"]), Paragraph("16 de julio de 2026", STYLES["cover_meta"])],
                [Paragraph("Estado", STYLES["cover_meta"]), Paragraph("Objetivo 1 implementado y verificado", STYLES["cover_meta"])],
            ],
            colWidths=[28 * mm, 80 * mm],
            style=TableStyle(
                [
                    ("TEXTCOLOR", (0, 0), (-1, -1), WHITE),
                    ("FONTNAME", (0, 0), (0, -1), BOLD_FONT),
                    ("FONTNAME", (1, 0), (1, -1), BODY_FONT),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#6C8BA8")),
                ]
            ),
        ),
        NextPageTemplate("body"),
        PageBreak(),
        Paragraph("Contenido", STYLES["toc_title"]),
        Paragraph(
            "Índice de secciones del plan técnico consolidado.",
            STYLES["body"],
        ),
        Spacer(1, 4 * mm),
        toc,
        PageBreak(),
    ]
    story.extend(markdown_flowables(source_text))

    doc = PlanDocument(OUTPUT)
    doc.multiBuild(story)
    print(OUTPUT)


if __name__ == "__main__":
    build_pdf()
