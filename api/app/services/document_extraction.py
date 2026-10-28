"""Read what a document says (Phase 5, step 1).

Order of attempts, cheapest first:

1. the PDF's own text layer (pdfplumber) — exact, and what a digitally issued document has;
2. OCR (Tesseract via pytesseract) for scans and photos, or a PDF with no text layer;
3. the QR code (pyzbar) when the text does not carry a reference number.

Every optional tool degrades gracefully: without Tesseract a scan simply yields no text
and the document goes to an officer with the reason "could not be read".
"""
from __future__ import annotations

import io
import logging
import re
import shutil
from dataclasses import dataclass, field
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.config import settings

logger = logging.getLogger("apaar.extraction")

WINDOWS_TESSERACT = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
MIN_TEXT_CHARS = 20  # below this, a PDF's text layer is treated as absent

_DATE = r"(\d{1,2}[/\-.]\d{1,2}[/\-.]\d{4}|\d{4}-\d{2}-\d{2})"
_PATTERNS: dict[str, re.Pattern[str]] = {
    "reference_no": re.compile(r"Reference\s*(?:No\.?|Number)\s*[:\-]\s*([A-Z0-9][A-Z0-9\-/]{3,39})", re.I),
    "name": re.compile(r"(?:Candidate(?:'s)?\s+Name|Student\s+Name|Holder(?:'s)?\s+Name|Name)\s*[:\-]\s*([A-Za-z][A-Za-z .']{1,80})", re.I),
    "dob": re.compile(r"(?:Date\s+of\s+Birth|D\.?O\.?B\.?)\s*[:\-]\s*" + _DATE, re.I),
    "roll_no": re.compile(r"(?:Roll|Registration|Enrolment|Passport|Card)\s*(?:No\.?|Number)\s*[:\-]\s*([A-Z0-9][A-Z0-9\-/]{2,30})", re.I),
    "issuer": re.compile(r"(?:Issued\s+by|Board|Issuing\s+Authority)\s*[:\-]\s*([^\n]{3,120})", re.I),
    "year": re.compile(r"(?:Year\s+of\s+Passing|Admission\s+Year|Session|Year)\s*[:\-]\s*(\d{4})", re.I),
    "marks": re.compile(r"(?:Total\s+Marks|Marks(?:\s+Obtained)?)\s*[:\-]\s*(\d{1,4})\s*/\s*(\d{1,4})", re.I),
    "issued_on": re.compile(r"(?:Issued\s+on|Date\s+of\s+Issue|Issue\s+Date)\s*[:\-]\s*" + _DATE, re.I),
}
_QR_REFERENCE = re.compile(r"ref=([A-Z0-9][A-Z0-9\-/]{3,39})", re.I)


@dataclass
class Extraction:
    method: str = "none"  # text | ocr | none
    text: str = ""
    fields: dict[str, Any] = field(default_factory=dict)
    qr: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def readable(self) -> bool:
        return len(self.text.strip()) >= MIN_TEXT_CHARS or bool(self.fields.get("reference_no"))


# --------------------------------------------------------------------------- tools


@lru_cache
def tesseract_path() -> str | None:
    """Where tesseract is, or None. Checked once per process."""
    for candidate in (settings.tesseract_cmd, shutil.which("tesseract"), str(WINDOWS_TESSERACT)):
        if candidate and Path(candidate).exists():
            return candidate
    return None


def ocr_available() -> bool:
    try:
        import pytesseract  # noqa: F401
    except ImportError:  # pragma: no cover - dependency missing
        return False
    return tesseract_path() is not None


def _ocr(image: Any) -> str:
    if not ocr_available():
        return ""
    import pytesseract

    pytesseract.pytesseract.tesseract_cmd = tesseract_path()
    try:
        return pytesseract.image_to_string(image) or ""
    except Exception as exc:  # pragma: no cover - tesseract crashed on a bad image
        logger.warning("OCR failed: %s", exc)
        return ""


def _decode_qr(image: Any) -> list[str]:
    try:
        from pyzbar.pyzbar import decode
    except Exception:  # pragma: no cover - zbar DLL missing
        return []
    try:
        return [item.data.decode("utf-8", "replace") for item in decode(image)]
    except Exception as exc:  # pragma: no cover
        logger.warning("QR decode failed: %s", exc)
        return []


# --------------------------------------------------------------------------- parsing


def parse_date(value: str | None) -> str | None:
    """dd/mm/yyyy, dd-mm-yyyy, dd.mm.yyyy or yyyy-mm-dd -> ISO yyyy-mm-dd."""
    if not value:
        return None
    value = value.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def parse_pdf_date(value: Any) -> str | None:
    """PDF metadata date (D:YYYYMMDDHHmmSS...) -> ISO date."""
    if not value:
        return None
    text = str(value)
    match = re.search(r"(\d{4})(\d{2})(\d{2})", text)
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3))).isoformat()
    except ValueError:
        return None


def parse_fields(text: str) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for key, pattern in _PATTERNS.items():
        match = pattern.search(text)
        if not match:
            continue
        if key == "marks":
            fields["marks_obtained"] = int(match.group(1))
            fields["marks_total"] = int(match.group(2))
        elif key in ("dob", "issued_on"):
            parsed = parse_date(match.group(1))
            if parsed:
                fields[key] = parsed
        elif key == "name":
            fields[key] = " ".join(match.group(1).split()).strip(" .")
        elif key in ("reference_no", "roll_no"):
            fields[key] = match.group(1).strip().upper()
        else:
            fields[key] = match.group(1).strip()
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if first_line:
        fields.setdefault("issuer", first_line[:120])
    return fields


# --------------------------------------------------------------------------- extraction


def extract(data: bytes, content_type: str) -> Extraction:
    if content_type == "application/pdf":
        return _extract_pdf(data)
    return _extract_image(data)


def _extract_pdf(data: bytes) -> Extraction:
    import pdfplumber

    result = Extraction()
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            result.metadata = {
                "producer": pdf.metadata.get("Producer"),
                "created": parse_pdf_date(pdf.metadata.get("CreationDate")),
                "modified": parse_pdf_date(pdf.metadata.get("ModDate")),
            }
            text = "\n".join((page.extract_text() or "") for page in pdf.pages[:5])
            first_page = pdf.pages[0] if pdf.pages else None
            if len(text.strip()) >= MIN_TEXT_CHARS:
                result.method = "text"
            elif first_page is not None and ocr_available():
                image = first_page.to_image(resolution=200).original
                text = _ocr(image)
                result.method = "ocr" if text.strip() else "none"
                result.qr = _decode_qr(image)
            elif first_page is not None:
                result.notes.append("No text layer and OCR is not installed.")
            result.text = text
            result.fields = parse_fields(text)
            if "reference_no" not in result.fields and first_page is not None and not result.qr:
                result.qr = _decode_qr(first_page.to_image(resolution=150).original)
    except Exception as exc:  # malformed PDF: the officer gets it
        logger.warning("PDF could not be read: %s", exc)
        result.notes.append("The PDF could not be opened.")
    _apply_qr(result)
    return result


def _extract_image(data: bytes) -> Extraction:
    from PIL import Image

    result = Extraction()
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception as exc:
        logger.warning("Image could not be read: %s", exc)
        result.notes.append("The image could not be opened.")
        return result
    result.qr = _decode_qr(image)
    if ocr_available():
        result.text = _ocr(image.convert("RGB"))
        result.method = "ocr" if result.text.strip() else "none"
    else:
        result.notes.append("This is a scan and OCR (Tesseract) is not installed.")
    result.fields = parse_fields(result.text)
    _apply_qr(result)
    return result


def _apply_qr(result: Extraction) -> None:
    """The QR's reference wins only when the text did not yield one."""
    for payload in result.qr:
        match = _QR_REFERENCE.search(payload)
        if match:
            result.fields.setdefault("reference_no", match.group(1).upper())
            result.fields["qr_reference"] = match.group(1).upper()
            break
