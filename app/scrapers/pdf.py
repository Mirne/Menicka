"""Read a menu published as a PDF.

Text PDFs (exported from Word etc.) give their text directly. Scanned PDFs have no
text layer, so their pages are rendered to pictures and read by OCR.
"""
from __future__ import annotations

import io
import logging

from . import ocr
from .base import clean_space

log = logging.getLogger(__name__)

MAX_PAGES = 6


def lines_from_pdf(data: bytes) -> tuple[list[str], bool]:
    """Return (text lines, read_by_ocr)."""
    import pypdfium2 as pdfium  # imported lazily: only needed for PDFs

    pdf = pdfium.PdfDocument(data)
    lines: list[str] = []
    used_ocr = False
    try:
        for i in range(min(len(pdf), MAX_PAGES)):
            page = pdf[i]
            text = page.get_textpage().get_text_bounded()
            page_lines = [clean_space(l) for l in text.replace("\r", "\n").split("\n")]
            page_lines = [l for l in page_lines if l]
            if sum(len(l) for l in page_lines) < 40 and ocr.available():
                # No text layer: a scan. ~2400 px wide is enough for OCR without upscaling.
                scale = 2400 / max(page.get_width(), 1)
                image = page.render(scale=scale).to_pil()
                buf = io.BytesIO()
                image.save(buf, format="PNG")
                page_lines = ocr.lines_from_image(buf.getvalue())
                used_ocr = True
            lines += page_lines
    finally:
        pdf.close()
    return lines, used_ocr
