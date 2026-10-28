"""Phase 4: document submission — checklist, content sniffing, encryption at rest,
bulk ZIP import, who may download, and tamper detection on every read."""
from __future__ import annotations

import io
import zipfile
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crypto import encrypt_bytes, hmac_hash, mask_apaar, mask_name, vault_encrypt
from app.models.core import (
    AccessLog,
    AuditLog,
    Enrolment,
    Flag,
    Program,
    Student,
    StudentDocument,
    User,
    Vault,
)
from app.services.rules import required_documents

YEAR = "2026-27"
PDF = b"%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


def _student(db: Session, institution, *, apaar: str, nationality: str = "indian",
             category: str | None = "GEN", admission_type: str = "regular") -> Student:
    program = db.execute(select(Program).where(Program.institution_id == institution.id)).scalars().first()
    student = Student(apaar_hash=hmac_hash(apaar), apaar_masked=mask_apaar(apaar), apaar_status="provided",
                      name_masked=mask_name("Kavya Menon"), nationality_status=nationality, category=category,
                      dob_year=2006, registry_status="match")
    db.add(student)
    db.flush()
    db.add(Vault(student_id=student.id, apaar_enc=vault_encrypt(apaar), name_enc=vault_encrypt("Kavya Menon"),
                 dob_enc=vault_encrypt("2006-05-04")))
    db.add(Enrolment(student_id=student.id, program_id=program.id, institution_id=institution.id,
                     academic_year=YEAR, year_of_study=1, admission_type=admission_type, status="admitted",
                     admitted_on=date(2026, 8, 1)))
    db.commit()
    return student


@pytest.fixture()
def setup(db: Session, two_institutions, users) -> dict:
    first, second = two_institutions
    return {
        "first": first,
        "second": second,
        "student": _student(db, first, apaar="700000000001"),
        "foreign": _student(db, second, apaar="700000000002"),
    }


def _upload(client: TestClient, headers, student_id: int, doc_type: str, data: bytes, name: str = "doc.pdf"):
    return client.post(
        f"/institution/students/{student_id}/documents",
        headers=headers,
        files={"file": (name, data, "application/octet-stream")},
        data={"doc_type": doc_type},
    )


# ------------------------------------------------------------------ the checklist rules


def test_the_checklist_comes_from_the_yaml_rules() -> None:
    assert required_documents(admission_type="regular", category="GEN", nationality_status="indian") == [
        "admission_letter", "class12_marksheet", "id_proof",
    ]
    assert "category_certificate" in required_documents(admission_type="regular", category="SC", nationality_status="indian")
    assert "nri_status_proof" in required_documents(admission_type="regular", category=None, nationality_status="nri")
    assert "oci_card" in required_documents(admission_type="fn_pio_oci", category=None, nationality_status="oci")
    fn = required_documents(admission_type="fn_pio_oci", category=None, nationality_status="fn")
    assert {"passport", "visa"} <= set(fn) and fn.count("passport") == 1  # no repeats
    assert "diploma_marksheet" in required_documents(admission_type="lateral", category="GEN", nationality_status="indian")


def test_a_new_student_starts_with_everything_missing(client: TestClient, auth, setup) -> None:
    body = client.get(f"/institution/students/{setup['student'].id}/documents", headers=auth("institution")).json()
    assert [item["doc_type"] for item in body["items"]] == ["admission_letter", "class12_marksheet", "id_proof"]
    assert body["counts"] == {"missing": 3, "uploaded": 0, "verified": 0, "rejected": 0}
    assert body["complete"] is False


# ------------------------------------------------------------------ type by content


def test_a_pdf_upload_is_stored_encrypted_with_its_hash(client: TestClient, auth, setup, db: Session) -> None:
    response = _upload(client, auth("institution"), setup["student"].id, "admission_letter", PDF)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["content_type"] == "application/pdf"
    document = db.get(StudentDocument, body["id"])
    import hashlib

    assert document.sha256 == hashlib.sha256(PDF).hexdigest()
    assert PDF not in document.content_enc and b"%PDF" not in document.content_enc
    checklist = client.get(f"/institution/students/{setup['student'].id}/documents", headers=auth("institution")).json()
    assert checklist["items"][0]["status"] == "uploaded"
    assert db.execute(select(AuditLog).where(AuditLog.action == "document_uploaded")).scalars().one()


def test_the_type_is_decided_by_content_not_the_name(client: TestClient, auth, setup) -> None:
    headers = auth("institution")
    png_named_pdf = _upload(client, headers, setup["student"].id, "id_proof", PNG, name="scan.pdf")
    assert png_named_pdf.status_code == 201
    assert png_named_pdf.json()["content_type"] == "image/png"
    jpeg = _upload(client, headers, setup["student"].id, "class12_marksheet", JPEG, name="marks.png")
    assert jpeg.json()["content_type"] == "image/jpeg"


@pytest.mark.parametrize(
    "payload",
    [b"MZ\x90\x00 an executable renamed to pdf", b"<html><script>alert(1)</script></html>", b"plain text"],
)
def test_anything_that_is_not_a_pdf_jpeg_or_png_is_refused(client: TestClient, auth, setup, payload) -> None:
    response = _upload(client, auth("institution"), setup["student"].id, "admission_letter", payload, name="ok.pdf")
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "UNSUPPORTED_FILE"


def test_a_pdf_with_javascript_is_refused(client: TestClient, auth, setup) -> None:
    evil = PDF.replace(b"/Type /Catalog", b"/Type /Catalog /OpenAction << /S /JavaScript /JS (app.alert(1)) >>")
    response = _upload(client, auth("institution"), setup["student"].id, "admission_letter", evil)
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "UNSAFE_FILE"


def test_files_over_the_size_limit_are_refused(client: TestClient, auth, setup) -> None:
    big = PDF + b"0" * (5 * 1024 * 1024 + 10)
    response = _upload(client, auth("institution"), setup["student"].id, "admission_letter", big)
    assert response.status_code == 413


def test_a_document_type_not_on_the_checklist_is_refused(client: TestClient, auth, setup) -> None:
    response = _upload(client, auth("institution"), setup["student"].id, "oci_card", PDF)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "NOT_REQUIRED"


def test_a_reupload_supersedes_the_earlier_file(client: TestClient, auth, setup, db: Session) -> None:
    headers = auth("institution")
    first = _upload(client, headers, setup["student"].id, "admission_letter", PDF).json()
    second = _upload(client, headers, setup["student"].id, "admission_letter", PDF + b"% v2\n").json()
    assert db.get(StudentDocument, first["id"]).is_current is False
    assert db.get(StudentDocument, second["id"]).is_current is True


# ------------------------------------------------------------------ bulk ZIP


def _zip(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def test_a_zip_is_matched_by_apaar_id_or_student_id(client: TestClient, auth, setup, db: Session) -> None:
    student = setup["student"]
    archive = _zip({
        "700000000001_admission_letter.pdf": PDF,
        f"{student.id}/class12_marksheet.pdf": PDF,
        f"S{student.id}_id_proof.png": PNG,
        "700000000002_admission_letter.pdf": PDF,       # the other college's student
        "999999999999_admission_letter.pdf": PDF,       # nobody
        "700000000001_passport.pdf": PDF,               # not on the checklist
        f"{student.id}_admission_letter.exe": b"MZ..",  # not a document
        "readme.txt": b"hello",                         # cannot be matched to anyone
    })
    response = client.post("/institution/documents/bulk", headers=auth("institution"),
                           files={"file": ("docs.zip", archive, "application/zip")})
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["stored"] == 3
    assert report["rejected"] == 4
    assert report["skipped"] == 1
    checklist = client.get(f"/institution/students/{student.id}/documents", headers=auth("institution")).json()
    assert checklist["counts"]["missing"] == 0
    # Nothing was attached to the other college's student.
    assert not db.execute(select(StudentDocument).where(StudentDocument.student_id == setup["foreign"].id)).scalars().all()


def test_a_zip_with_too_many_files_is_refused(client: TestClient, auth, setup) -> None:
    archive = _zip({f"{index}_admission_letter.pdf": PDF for index in range(501)})
    response = client.post("/institution/documents/bulk", headers=auth("institution"),
                           files={"file": ("docs.zip", archive, "application/zip")})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "TOO_MANY_FILES"


def test_a_zip_bomb_is_refused_before_it_is_expanded(client: TestClient, auth, setup) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("700000000001_admission_letter.pdf", b"%PDF-" + b"\x00" * (210 * 1024 * 1024))
    response = client.post("/institution/documents/bulk", headers=auth("institution"),
                           files={"file": ("bomb.zip", buffer.getvalue(), "application/zip")})
    assert response.status_code == 413


def test_something_that_is_not_a_zip_is_refused(client: TestClient, auth, setup) -> None:
    response = client.post("/institution/documents/bulk", headers=auth("institution"),
                           files={"file": ("docs.zip", PDF, "application/zip")})
    assert response.status_code == 415


# ------------------------------------------------------------------ who may read a document


def _stored(client: TestClient, auth, setup) -> int:
    return _upload(client, auth("institution"), setup["student"].id, "admission_letter", PDF).json()["id"]


def test_the_owning_institution_can_download_and_it_is_logged(client: TestClient, auth, setup, db: Session) -> None:
    document_id = _stored(client, auth, setup)
    response = client.get(f"/institution/documents/{document_id}/file", headers=auth("institution"))
    assert response.status_code == 200
    assert response.content == PDF
    assert response.headers["x-content-type-options"] == "nosniff"
    entry = db.execute(select(AccessLog).where(AccessLog.action == "view_document")).scalars().one()
    assert entry.student_id == setup["student"].id


def test_another_institution_cannot_download_it(client: TestClient, auth, setup) -> None:
    document_id = _stored(client, auth, setup)
    response = client.get(f"/institution/documents/{document_id}/file", headers=auth("institution_other"))
    assert response.status_code == 404
    assert client.get(f"/institution/students/{setup['student'].id}/documents",
                      headers=auth("institution_other")).status_code == 404
    assert _upload(client, auth("institution_other"), setup["student"].id, "admission_letter", PDF).status_code == 404


def test_an_officer_needs_a_reason_and_the_reason_is_logged(client: TestClient, auth, setup, db: Session) -> None:
    document_id = _stored(client, auth, setup)
    headers = auth("aicte_officer")
    assert client.post(f"/aicte/documents/{document_id}/file", headers=headers, json={}).status_code == 422
    assert client.post(f"/aicte/documents/{document_id}/file", headers=headers, json={"reason": "x"}).status_code == 422
    response = client.post(f"/aicte/documents/{document_id}/file", headers=headers,
                           json={"reason": "Reviewing a mismatched marksheet."})
    assert response.status_code == 200
    entry = db.execute(select(AccessLog).where(AccessLog.role == "aicte_officer")).scalars().one()
    assert entry.reason == "Reviewing a mismatched marksheet."
    assert client.post(f"/aicte/documents/{document_id}/file", headers=auth("aicte_viewer"),
                       json={"reason": "Just curious about this file."}).status_code == 403


def test_the_student_can_read_their_own_documents_only(client: TestClient, auth, setup, db: Session) -> None:
    document_id = _stored(client, auth, setup)
    user_row = db.execute(select(User).where(User.username == "student_demo1")).scalar_one()
    other_student = user_row.student_id
    user_row.student_id = setup["student"].id
    db.commit()
    headers = auth("student")
    listing = client.get("/student/documents", headers=headers).json()
    assert [item["id"] for item in listing["items"]] == [document_id]
    assert client.get(f"/student/documents/{document_id}/file", headers=headers).status_code == 200

    user_row.student_id = other_student
    db.commit()
    assert client.get(f"/student/documents/{document_id}/file", headers=auth("student")).status_code == 404


# ------------------------------------------------------------------ tamper detection


def test_a_file_altered_in_storage_is_withheld_and_flagged(client: TestClient, auth, setup, db: Session) -> None:
    document_id = _stored(client, auth, setup)
    document = db.get(StudentDocument, document_id)
    # Someone with database access swaps the file for another, correctly encrypted one.
    document.content_enc = encrypt_bytes(PDF.replace(b"Catalog", b"Catalox"))
    db.commit()

    response = client.get(f"/institution/documents/{document_id}/file", headers=auth("institution"))
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "DOCUMENT_TAMPERED"
    db.expire_all()
    document = db.get(StudentDocument, document_id)
    assert document.integrity_ok is False
    assert document.verification_status == "rejected"
    flag = db.execute(select(Flag).where(Flag.type == "DOCUMENT_TAMPERED")).scalars().one()
    assert flag.severity == "critical" and flag.explanation and flag.evidence["document_id"] == document_id


def test_a_corrupted_ciphertext_is_also_caught(client: TestClient, auth, setup, db: Session) -> None:
    document_id = _stored(client, auth, setup)
    document = db.get(StudentDocument, document_id)
    document.content_enc = document.content_enc[:-5] + b"AAAAA"
    db.commit()
    response = client.get(f"/institution/documents/{document_id}/file", headers=auth("institution"))
    assert response.status_code == 409


def test_the_overview_counts_students_by_checklist_state(client: TestClient, auth, setup) -> None:
    headers = auth("institution")
    _upload(client, headers, setup["student"].id, "admission_letter", PDF)
    body = client.get("/institution/documents", headers=headers).json()
    assert body["total"] == 1
    row = body["items"][0]
    assert row["status"] == "missing"
    assert row["missing"] == ["class12_marksheet", "id_proof"]
    assert body["totals"]["missing"] == 1
