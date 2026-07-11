"""Tests for paritran.engine.ingest_ocr (SPEC 9.1 engine side).

Plain-python tests, no db marker. OCR tests skip cleanly when the
tesseract binary is absent; sample tests skip when the committed
dataset/samples binaries are not present in the checkout (they are
regenerated deterministically by scripts/make_samples.py).

Honesty note on assertions: the PDF text layer is byte-faithful, so the
PDF test asserts the full planted identifier set. OCR output varies with
tesseract version and image noise, so the scan test asserts only what is
honestly stable (phone and account digits) and no more.
"""

import shutil
from pathlib import Path

import pytest

from paritran.engine.ingest_ocr import (
    SUPPORTED_SUFFIXES,
    UnsupportedArtefactError,
    extract_text,
)
from paritran.engine.ner import extract

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLES_DIR = REPO_ROOT / "dataset" / "samples"
PDF_SAMPLE = SAMPLES_DIR / "complaint_sample.pdf"
PNG_SAMPLE = SAMPLES_DIR / "complaint_scan.png"

# Planted by scripts/make_samples.py in both bundled documents.
PLANTED_ALL = {
    ("9876543210", "phone"),
    ("fraudster@upi", "upi"),
    ("203.0.113.7", "ipv4"),
    ("123456789012", "account"),
}
# The honest OCR floor: digit strings survive tesseract reliably; the UPI
# handle and dotted IP may not on every tesseract version.
PLANTED_OCR_MINIMUM = {
    ("9876543210", "phone"),
    ("123456789012", "account"),
}

needs_tesseract = pytest.mark.skipif(
    shutil.which("tesseract") is None,
    reason="tesseract binary not installed",
)
needs_samples = pytest.mark.skipif(
    not (PDF_SAMPLE.is_file() and PNG_SAMPLE.is_file()),
    reason="bundled synthetic samples missing "
    "(regenerate with scripts/make_samples.py)",
)


@needs_samples
def test_pdf_with_text_layer_uses_pdfplumber():
    result = extract_text(PDF_SAMPLE)
    assert result["method"] == "pdf-text"
    assert result["pages"] == 1
    assert "SYNTHETIC SAMPLE, ZERO REAL PII" in result["text"]
    for identifier, _ in PLANTED_ALL:
        assert identifier in result["text"], identifier
    # NER over the extracted text recovers exactly the planted set.
    assert set(extract(result["text"])) == PLANTED_ALL


@needs_samples
@needs_tesseract
def test_scanned_image_uses_ocr():
    result = extract_text(PNG_SAMPLE)
    assert result["method"] == "ocr"
    assert result["pages"] == 1
    found = set(extract(result["text"]))
    missing = PLANTED_OCR_MINIMUM - found
    assert not missing, f"OCR + NER lost identifiers: {missing}"


@needs_tesseract
def test_pdf_without_text_layer_falls_back_to_ocr(tmp_path):
    """An image-only PDF page has no text layer and must route through OCR."""
    from fpdf import FPDF
    from PIL import Image, ImageDraw, ImageFont

    png = tmp_path / "page.png"
    image = Image.new("RGB", (1400, 260), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=44)
    draw.text((60, 60), "Debited from account 123456789012 today.", fill="black", font=font)
    image.save(png)

    pdf_path = tmp_path / "scanned.pdf"
    pdf = FPDF(format="A4")
    pdf.add_page()
    pdf.image(str(png), x=10, y=40, w=190)
    pdf.output(str(pdf_path))

    result = extract_text(pdf_path)
    assert result["method"] == "ocr"
    assert result["pages"] == 1
    assert "123456789012" in result["text"]
    assert ("123456789012", "account") in set(extract(result["text"]))


@needs_tesseract
def test_mixed_pdf_reports_ocr_honestly(tmp_path):
    """One text page + one image-only page: method must say ocr, not pdf-text."""
    from fpdf import FPDF
    from PIL import Image, ImageDraw, ImageFont

    png = tmp_path / "page.png"
    image = Image.new("RGB", (1400, 260), "white")
    ImageDraw.Draw(image).text(
        (60, 60),
        "Caller used mobile 9876543210 repeatedly.",
        fill="black",
        font=ImageFont.load_default(size=44),
    )
    image.save(png)

    pdf_path = tmp_path / "mixed.pdf"
    pdf = FPDF(format="A4")
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    pdf.cell(0, 8, "Typed page: account 123456789012 was debited.")
    pdf.add_page()
    pdf.image(str(png), x=10, y=40, w=190)
    pdf.output(str(pdf_path))

    result = extract_text(pdf_path)
    assert result["method"] == "ocr"
    assert result["pages"] == 2
    assert "123456789012" in result["text"]  # from the real text layer
    assert "9876543210" in result["text"]  # from OCR


def test_unsupported_type_raises_with_supported_list(tmp_path):
    bogus = tmp_path / "evidence.docx"
    bogus.write_bytes(b"not a real docx")
    with pytest.raises(UnsupportedArtefactError) as exc:
        extract_text(bogus)
    message = str(exc.value)
    assert ".pdf" in message
    assert ".png" in message
    # It is a ValueError subclass so generic handlers still catch it.
    assert isinstance(exc.value, ValueError)


def test_missing_file_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        extract_text(tmp_path / "nope.pdf")


def test_supported_suffixes_cover_spec_types():
    assert {".pdf", ".png", ".jpg", ".jpeg"} <= SUPPORTED_SUFFIXES
