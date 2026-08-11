from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "output" / "pdf" / "plan_tecnico_agente_jira_v0.6.pdf"
OUT = ROOT / "tmp" / "pdfs" / "plan_tecnico_agente_jira_v0.6"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    document = pdfium.PdfDocument(str(PDF))
    rendered = []
    for index in range(len(document)):
        page = document[index]
        image = page.render(scale=2.0).to_pil().convert("RGB")
        path = OUT / f"page-{index + 1:02d}.png"
        image.save(path, optimize=True)
        rendered.append(image)

    thumb_w, thumb_h = 240, 340
    cols = 4
    rows = (len(rendered) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * (thumb_w + 20) + 20, rows * (thumb_h + 38) + 20), "#D8DEE5")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    for index, image in enumerate(rendered):
        image.thumbnail((thumb_w, thumb_h))
        col, row = index % cols, index // cols
        x = 20 + col * (thumb_w + 20)
        y = 20 + row * (thumb_h + 38)
        sheet.paste(image, (x, y))
        draw.text((x, y + thumb_h + 7), f"Página {index + 1}", fill="#1F2937", font=font)
    sheet.save(OUT / "contact-sheet.png", optimize=True)
    print(OUT)


if __name__ == "__main__":
    main()
