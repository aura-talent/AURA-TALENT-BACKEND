"""Markdown resume → PDF via fpdf2 (pure Python, no system dependencies)."""

import markdown as md_lib
from fpdf import FPDF
from fpdf.fonts import FontFace

# fpdf2 core fonts are latin-1 only; map common unicode punctuation so
# LLM-generated text doesn't raise FPDFUnicodeEncodingException.
_UNICODE_FALLBACKS = {
    "–": "-", "—": "--", "‘": "'", "’": "'",
    "“": '"', "”": '"', "•": "-", "…": "...",
    " ": " ", "→": "->", "✓": "+", "✔": "+",
}


def _latin1_safe(text: str) -> str:
    for char, repl in _UNICODE_FALLBACKS.items():
        text = text.replace(char, repl)
    return text.encode("latin-1", errors="replace").decode("latin-1")


def markdown_to_pdf(md_text: str) -> bytes:
    html = md_lib.markdown(md_text, extensions=["tables", "sane_lists"])
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_margins(left=18, top=15, right=18)
    pdf.add_page()
    pdf.set_font("helvetica", size=10)
    ink = (20, 20, 20)
    pdf.write_html(_latin1_safe(html), li_prefix_color=ink, tag_styles={
        "h1": FontFace(color=ink, size_pt=20),
        "h2": FontFace(color=ink, size_pt=13),
        "h3": FontFace(color=ink, size_pt=11),
        "a": FontFace(color=(40, 80, 160)),
    })
    return bytes(pdf.output())
