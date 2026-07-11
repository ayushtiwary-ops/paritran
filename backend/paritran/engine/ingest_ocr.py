"""Document ingest for POST /api/intake/artefact (SPEC 9.1, engine side).

``extract_text(path)`` returns ``{"text": str, "method": "pdf-text"|"ocr",
"pages": int}``.

Extraction order, per SPEC 9.1:

1. PDFs go through pdfplumber first. Pages carrying a text layer are read
   directly.
2. Any PDF page WITHOUT a text layer is rasterized (pdfplumber/pypdfium2,
   300 dpi) and OCR'd with pytesseract. If OCR was needed for one or more
   pages, ``method`` reports ``"ocr"`` honestly, never ``"pdf-text"``.
3. Image files (scans) are OCR'd directly with pytesseract.

Anything else raises :class:`UnsupportedArtefactError` listing the
supported types. OCR requires the ``tesseract`` binary on PATH (installed
in the API image via ``infra/docker/Dockerfile.api``); when it is absent
pytesseract's own TesseractNotFoundError propagates with its clear
install hint.

This module extracts text only. Intake hashing (SHA-256 of the artefact
bytes), audit-chain append, and NER over the extracted text are composed
by the API layer, keeping this function side-effect free and testable.
"""

from __future__ import annotations

from pathlib import Path

import pdfplumber
import pytesseract
from PIL import Image, ImageSequence

__all__ = ["SUPPORTED_SUFFIXES", "UnsupportedArtefactError", "extract_text"]

_PDF_SUFFIXES = frozenset({".pdf"})
_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"})
SUPPORTED_SUFFIXES: frozenset[str] = _PDF_SUFFIXES | _IMAGE_SUFFIXES

_OCR_RESOLUTION_DPI = 300


class UnsupportedArtefactError(ValueError):
    """Raised for artefact types the ingest engine cannot process."""

    def __init__(self, suffix: str):
        supported = ", ".join(sorted(SUPPORTED_SUFFIXES))
        super().__init__(
            f"unsupported artefact type {suffix or '(no extension)'!r}: "
            f"supported types are {supported} "
            "(PDF via pdfplumber with OCR fallback, images via Tesseract OCR)"
        )


def _ocr_image(image: Image.Image) -> str:
    """OCR one PIL image. Grayscale conversion, then pytesseract."""
    return pytesseract.image_to_string(image.convert("L"))


def _extract_pdf(path: Path) -> dict:
    texts: list[str] = []
    ocr_pages = 0
    with pdfplumber.open(path) as pdf:
        n_pages = len(pdf.pages)
        for page in pdf.pages:
            layer = page.extract_text() or ""
            if layer.strip():
                texts.append(layer)
            else:
                # No text layer on this page: rasterize and OCR (SPEC 9.1).
                ocr_pages += 1
                rendered = page.to_image(resolution=_OCR_RESOLUTION_DPI).original
                texts.append(_ocr_image(rendered))
    return {
        "text": "\n".join(texts),
        "method": "ocr" if ocr_pages else "pdf-text",
        "pages": n_pages,
    }


def _extract_image(path: Path) -> dict:
    texts: list[str] = []
    with Image.open(path) as image:
        frames = 0
        for frame in ImageSequence.Iterator(image):
            frames += 1
            texts.append(_ocr_image(frame))
    return {"text": "\n".join(texts), "method": "ocr", "pages": frames}


def extract_text(path: str | Path) -> dict:
    """Extract text from a PDF or image artefact.

    Returns ``{"text": str, "method": "pdf-text"|"ocr", "pages": int}``.
    ``method`` is ``"pdf-text"`` only when every page came from a real PDF
    text layer; if OCR contributed anywhere the method is ``"ocr"``.

    Raises FileNotFoundError for a missing path and
    :class:`UnsupportedArtefactError` for anything that is not a PDF or a
    supported image type.
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"artefact not found: {p}")
    suffix = p.suffix.lower()
    if suffix in _PDF_SUFFIXES:
        return _extract_pdf(p)
    if suffix in _IMAGE_SUFFIXES:
        return _extract_image(p)
    raise UnsupportedArtefactError(suffix)
