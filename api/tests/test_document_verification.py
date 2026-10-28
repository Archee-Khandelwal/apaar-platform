"""Phase 5: document verification — extraction, data match, issuer check, tamper check,
the decision, and the officer review queue."""
from __future__ import annotations

import io
import json
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crypto import hmac_hash, mask_apaar, mask_name, vault_encrypt
from app.models.core import AccessLog, AuditLog, Enrolment, Program, Student, StudentDocument, Vault
from app.services import document_verification
from app.services.document_extraction import extract, ocr_available, parse_date, parse_fields
from app.services.document_verification import Findings, compare_identity, decide
from app.services.issuer_client import IssuerResult
from datagen.documents import PrintedDocument, in_process_issuer, issuer_record, register_with_issuer

NAME, DOB = "Kavya Menon", "2006-05-04"


def _printed(**overrides) -> PrintedDocument:
    values = dict(
        doc_type="class12_marksheet", reference_no="SSE-2026-123456", issuer_name="Kaveri Senior Secondary Board",
        holder_name=NAME, holder_dob=DOB, issued_on=date(2026, 6, 10),
        details={"roll_no": "4455667", "year": 2026, "marks_obtained": 431, "marks_total": 500},
    )
    values.update(overrides)
    return PrintedDocument(**values)


@pytest.fixture()
def student(db: Session, two_institutions, users) -> Student:
    first, _ = two_institutions
    program = db.execute(select(Program).where(Program.institution_id == first.id)).scalars().first()
    row = Student(apaar_hash=hmac_hash("700000000001"), apaar_masked=mask_apaar("700000000001"),
                  apaar_status="provided", name_masked=mask_name(NAME), nationality_status="indian",
                  category="GEN", dob_year=2006, registry_status="match")
    db.add(row)
    db.flush()
    db.add(Vault(student_id=row.id, apaar_enc=vault_encrypt("700000000001"), name_enc=vault_encrypt(NAME),
                 dob_enc=vault_encrypt(DOB)))
    db.add(Enrolment(student_id=row.id, program_id=program.id, institution_id=first.id, academic_year="2026-27",
                     year_of_study=1, admission_type="regular", status="admitted", admitted_on=date(2026, 8, 1)))
    db.commit()
    return row


@pytest.fixture()
def issuer_up(monkeypatch):
    """Route the pipeline's issuer calls to the issuer registry logic, in process."""
    register_with_issuer([], replace=True)
    monkeypatch.setattr(document_verification, "IssuerClient", lambda *a, **k: in_process_issuer())


def _upload(client: TestClient, headers, student_id: int, data: bytes, doc_type: str = "class12_marksheet"):
    return client.post(f"/institution/students/{student_id}/documents", headers=headers,
                       files={"file": ("doc.pdf", data, "application/pdf")}, data={"doc_type": doc_type})


# ------------------------------------------------------------------ extraction


def test_fields_are_read_from_a_digital_pdf() -> None:
    reading = extract(_printed().render(), "application/pdf")
    assert reading.method == "text"
    fields = reading.fields
    assert fields["reference_no"] == "SSE-2026-123456"
    assert fields["name"] == NAME
    assert fields["dob"] == DOB
    assert fields["roll_no"] == "4455667"
    assert fields["year"] == "2026"
    assert (fields["marks_obtained"], fields["marks_total"]) == (431, 500)
    assert fields["issued_on"] == "2026-06-10"
    assert reading.metadata["created"] == "2026-06-10"


def test_dates_are_normalised() -> None:
    assert parse_date("04/05/2006") == "2006-05-04"
    assert parse_date("04-05-2006") == "2006-05-04"
    assert parse_date("2006-05-04") == "2006-05-04"
    assert parse_date("31/02/2006") is None
    assert parse_fields("Board of Nothing\nName: A. B. Rao\n")["name"] == "A. B. Rao"


@pytest.mark.skipif(not ocr_available(), reason="Tesseract is not installed")
def test_a_scanned_image_is_read_by_ocr_and_its_qr_decoded() -> None:
    import qrcode
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (1400, 700), "white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("arial.ttf", 34)
    except OSError:  # pragma: no cover - non-Windows font path
        font = ImageFont.load_default()
    for index, line in enumerate(["Kaveri Senior Secondary Board", "Reference No: SSE-2026-123456",
                                  f"Name: {NAME}", "Date of Birth: 04/05/2006", "Roll No: 4455667"]):
        draw.text((40, 40 + index * 60), line, fill="black", font=font)
    image.paste(qrcode.make("APAARDOC|ref=SSE-2026-123456").resize((260, 260)), (1080, 40))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")

    reading = extract(buffer.getvalue(), "image/png")
    assert reading.method == "ocr"
    assert reading.fields["name"] == NAME
    assert reading.fields["dob"] == DOB
    assert reading.fields["qr_reference"] == "SSE-2026-123456"


def test_a_qr_code_supplies_the_reference_when_the_text_has_none() -> None:
    from app.services.pdf import PdfDocument

    pdf = PdfDocument(title="ID")
    pdf.text(48, 60, "Identity card", size=14)
    pdf.text(48, 90, f"Name: {NAME}")
    pdf.qr(400, 60, 120, "APAARDOC|ref=RID-2024-555111")
    reading = extract(pdf.to_bytes(), "application/pdf")
    assert reading.fields["reference_no"] == "RID-2024-555111"


# ------------------------------------------------------------------ data match


def test_names_match_fuzzily_and_dates_exactly() -> None:
    same = compare_identity({"name": NAME, "dob": DOB}, {"name": "KAVYA  MENON", "dob": DOB})
    assert same["name"]["match"] is True and same["dob"]["match"] is True
    reordered = compare_identity({"name": NAME, "dob": DOB}, {"name": "Menon Kavya", "dob": DOB})
    assert reordered["name"]["match"] is True
    other = compare_identity({"name": NAME, "dob": DOB}, {"name": "Ritu Saxena", "dob": "2006-05-05"})
    assert other["name"]["match"] is False and other["dob"]["match"] is False
    assert "Ritu" not in json.dumps(other), "the comparison stores scores, never names"


# ------------------------------------------------------------------ the decision


def _findings(**overrides) -> Findings:
    values = dict(
        integrity_ok=True, readable=True, reference_no="SSE-1",
        issuer=IssuerResult(status="verified", matched_by="hash", issuer_name="Board", holder_name_match=True, holder_dob_match=True),
        identity=compare_identity({"name": NAME, "dob": DOB}, {"name": NAME, "dob": DOB}),
        metadata_edit=None, doc_type="class12_marksheet",
    )
    values.update(overrides)
    return Findings(**values)


@pytest.mark.parametrize(
    ("overrides", "status", "code"),
    [
        ({}, "auto_verified", "VERIFIED_WITH_ISSUER"),
        ({"integrity_ok": False}, "rejected", "STORAGE_TAMPERED"),
        ({"issuer": IssuerResult(status="mismatch", differing_facts=["marks_obtained"])}, "rejected", "ISSUER_MISMATCH"),
        ({"issuer": IssuerResult(status="revoked")}, "rejected", "ISSUER_REVOKED"),
        ({"issuer": IssuerResult(status="not_found")}, "needs_review", "NOT_AT_ISSUER"),
        ({"issuer": IssuerResult(status="unavailable")}, "needs_review", "ISSUER_UNAVAILABLE"),
        ({"reference_no": None, "issuer": None}, "needs_review", "NO_REFERENCE"),
        ({"readable": False}, "needs_review", "UNREADABLE"),
        ({"metadata_edit": "edited later"}, "needs_review", "EDITED_AFTER_ISSUE"),
        ({"identity": compare_identity({"name": NAME, "dob": DOB}, {"name": "Ritu Saxena", "dob": DOB})}, "needs_review", "NAME_MISMATCH"),
        ({"identity": compare_identity({"name": NAME, "dob": DOB}, {"name": NAME, "dob": "2001-01-01"})}, "needs_review", "DOB_MISMATCH"),
    ],
)
def test_every_rule_of_the_decision(overrides, status, code) -> None:
    outcome, reasons = decide(_findings(**overrides))
    assert outcome == status
    assert code in {reason["code"] for reason in reasons}
    assert all(reason["message"] for reason in reasons), "every reason is explained"


# ------------------------------------------------------------------ the issuer registry


def test_the_issuer_registry_verifies_by_hash_by_facts_or_says_mismatch() -> None:
    from issuer.app.config import issuer_settings
    from issuer.app.main import app as issuer_app

    genuine = _printed()
    data = genuine.render()
    register_with_issuer([issuer_record(genuine, data)], replace=True)
    client = TestClient(issuer_app)
    headers = {"X-API-Key": issuer_settings.issuer_api_key}
    import hashlib

    def verify(**body):
        return client.post("/documents/verify", headers=headers, json={"reference_no": "SSE-2026-123456", **body}).json()

    assert client.post("/documents/verify", json={"reference_no": "X"}).status_code == 401
    by_hash = verify(sha256=hashlib.sha256(data).hexdigest(), holder_name="kavya menon", holder_dob=DOB)
    assert (by_hash["status"], by_hash["matched_by"], by_hash["holder_name_match"]) == ("verified", "hash", True)
    by_facts = verify(sha256="0" * 64, facts={"roll_no": "4455667", "year": "2026", "marks_obtained": 431, "marks_total": 500})
    assert (by_facts["status"], by_facts["matched_by"]) == ("verified", "facts")
    edited = verify(sha256="0" * 64, facts={"roll_no": "4455667", "marks_obtained": 499, "marks_total": 500})
    assert edited["status"] == "mismatch" and edited["differing_facts"] == ["marks_obtained"]
    assert verify(reference_no="SSE-0000-000000")["status"] == "not_found"
    assert client.get("/documents/SSE-2026-123456", headers=headers).json()["issuer_name"] == "Kaveri Senior Secondary Board"


# ------------------------------------------------------------------ the pipeline, end to end


def test_a_genuine_document_is_auto_verified(client: TestClient, auth, student, issuer_up, db: Session) -> None:
    genuine = _printed()
    data = genuine.render()
    register_with_issuer([issuer_record(genuine, data)], replace=False)
    body = _upload(client, auth("institution"), student.id, data).json()
    assert body["verification_status"] == "auto_verified", body["reasons"]
    assert body["issuer_status"] == "verified"
    checklist = client.get(f"/institution/students/{student.id}/documents", headers=auth("institution")).json()
    assert next(item for item in checklist["items"] if item["doc_type"] == "class12_marksheet")["status"] == "verified"
    assert db.execute(select(AuditLog).where(AuditLog.action == "document_verified")).scalars().one()


def test_an_edited_marksheet_is_rejected_with_both_reasons(client: TestClient, auth, student, issuer_up) -> None:
    genuine = _printed()
    register_with_issuer([issuer_record(genuine, genuine.render())], replace=False)
    edited = _printed(details={**genuine.details, "marks_obtained": 497}, modified=datetime(2026, 9, 1))
    body = _upload(client, auth("institution"), student.id, edited.render()).json()
    assert body["verification_status"] == "rejected"
    codes = {reason["code"] for reason in body["reasons"]}
    assert {"ISSUER_MISMATCH", "EDITED_AFTER_ISSUE"} <= codes


def test_someone_elses_document_goes_to_an_officer(client: TestClient, auth, student, issuer_up) -> None:
    other = _printed(holder_name="Ritu Saxena", reference_no="SSE-2026-999111")
    data = other.render()
    register_with_issuer([issuer_record(other, data)], replace=False)
    body = _upload(client, auth("institution"), student.id, data).json()
    assert body["verification_status"] == "needs_review"
    assert body["issuer_status"] == "verified"  # genuine — just not this student's
    assert "NAME_MISMATCH" in {reason["code"] for reason in body["reasons"]}


def test_an_unknown_reference_goes_to_an_officer(client: TestClient, auth, student, issuer_up) -> None:
    body = _upload(client, auth("institution"), student.id, _printed(reference_no="SSE-2026-000000").render()).json()
    assert body["verification_status"] == "needs_review"
    assert body["issuer_status"] == "not_found"


def test_an_unreachable_issuer_is_never_a_pass_and_can_be_rechecked(
    client: TestClient, auth, student, db: Session, monkeypatch
) -> None:
    genuine = _printed()
    data = genuine.render()
    body = _upload(client, auth("institution"), student.id, data).json()  # issuer at port 9: down
    assert body["verification_status"] == "needs_review"
    assert body["issuer_status"] == "unavailable"

    register_with_issuer([issuer_record(genuine, data)], replace=True)
    monkeypatch.setattr(document_verification, "IssuerClient", lambda *a, **k: in_process_issuer())
    rechecked = client.post(f"/aicte/documents/{body['id']}/recheck", headers=auth("aicte_officer")).json()
    assert rechecked["verification_status"] == "auto_verified"


def test_the_name_read_from_a_document_is_stored_encrypted(client: TestClient, auth, student, issuer_up, db: Session) -> None:
    body = _upload(client, auth("institution"), student.id, _printed().render()).json()
    document = db.get(StudentDocument, body["id"])
    for column in ("extracted", "data_match", "issuer_result", "tamper", "reasons"):
        assert "Kavya" not in json.dumps(getattr(document, column), default=str), column
    assert document.extracted_identity_enc and "Kavya" not in document.extracted_identity_enc


# ------------------------------------------------------------------ the officer review queue


@pytest.fixture()
def flagged(client: TestClient, auth, student, issuer_up) -> int:
    other = _printed(holder_name="Ritu Saxena", reference_no="SSE-2026-999111")
    data = other.render()
    register_with_issuer([issuer_record(other, data)], replace=False)
    return _upload(client, auth("institution"), student.id, data).json()["id"]


def test_the_review_queue_is_masked(client: TestClient, auth, flagged) -> None:
    body = client.get("/aicte/documents/review", headers=auth("aicte_officer")).json()
    assert body["total"] == 1 and body["counts"]["needs_review"] == 1
    row = body["items"][0]
    assert row["apaar_masked"].startswith("XXXX-XXXX-") and "Kavya" not in json.dumps(row)
    assert client.get("/aicte/documents/review", headers=auth("aicte_viewer")).status_code == 403


def test_opening_a_case_needs_a_reason_and_shows_both_sides(client: TestClient, auth, flagged, db: Session) -> None:
    headers = auth("aicte_officer")
    assert client.post(f"/aicte/documents/{flagged}/case", headers=headers, json={"reason": "short"}).status_code == 422
    case = client.post(f"/aicte/documents/{flagged}/case", headers=headers,
                       json={"reason": "Reviewing a name mismatch on a marksheet."}).json()
    name_row = next(row for row in case["comparison"] if row["field"] == "Name")
    assert (name_row["submitted"], name_row["on_document"], name_row["match"]) == (NAME, "Ritu Saxena", False)
    assert case["issuer"]["label"] == "Verified with issuer"
    assert case["extracted"]["reference_no"] == "SSE-2026-999111"
    entry = db.execute(select(AccessLog).where(AccessLog.action == "view_document_case")).scalars().one()
    assert entry.reason == "Reviewing a name mismatch on a marksheet."


def test_an_officer_decision_is_recorded_in_the_audit_chain(client: TestClient, auth, flagged, db: Session) -> None:
    headers = auth("aicte_officer")
    assert client.post(f"/aicte/documents/{flagged}/decision", headers=headers,
                       json={"decision": "approve", "reason": "ok"}).status_code == 422
    response = client.post(f"/aicte/documents/{flagged}/decision", headers=headers,
                           json={"decision": "reject", "reason": "The marksheet belongs to another candidate."})
    assert response.json()["verification_status"] == "rejected"
    entry = db.execute(select(AuditLog).where(AuditLog.action == "document_review_decision")).scalars().one()
    assert entry.payload["decision"] == "reject"
    from app.core.audit import verify_chain

    assert verify_chain(db).ok
    checklist = client.get("/institution/documents", headers=auth("institution")).json()
    assert checklist["items"][0]["status"] == "rejected"


def test_a_document_that_failed_integrity_cannot_be_approved(client: TestClient, auth, flagged, db: Session) -> None:
    document = db.get(StudentDocument, flagged)
    document.integrity_ok = False
    db.commit()
    response = client.post(f"/aicte/documents/{flagged}/decision", headers=auth("aicte_officer"),
                           json={"decision": "approve", "reason": "Looks fine to me on screen."})
    assert response.status_code == 409
