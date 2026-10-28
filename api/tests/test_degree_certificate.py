"""Degree certificates with APAAR + student ID, the PDF writer, and the public check."""
from __future__ import annotations

import re
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.crypto import hash_apaar, mask_apaar, mask_name, vault_encrypt
from app.models.core import AccessLog, AuditLog, Enrolment, IssuedDocument, Program, Student, User, Vault
from app.services import documents
from app.services.pdf import PdfDocument, text_width, wrap

YEAR = "2026-27"
APAAR = "123456781234"


@pytest.fixture()
def completed(db: Session, users, two_institutions) -> dict:
    first, second = two_institutions
    program = db.execute(select(Program).where(Program.institution_id == first.id)).scalars().first()
    account = db.execute(select(User).where(User.username == "student_demo1")).scalar_one()
    student = db.get(Student, account.student_id)
    student.apaar_hash = hash_apaar(APAAR)
    student.apaar_masked = mask_apaar(APAAR)
    student.apaar_status = "provided"
    student.name_masked = mask_name("Rahul Sharma")
    db.add(
        Vault(
            student_id=student.id,
            apaar_enc=vault_encrypt(APAAR),
            name_enc=vault_encrypt("Rahul Sharma"),
            dob_enc=vault_encrypt("2004-03-12"),
        )
    )
    enrolment = Enrolment(
        student_id=student.id,
        program_id=program.id,
        institution_id=first.id,
        academic_year=YEAR,
        year_of_study=4,
        admission_type="regular",
        status="completed",
        admitted_on=date(2026, 8, 5),
    )
    admitted = Enrolment(
        student_id=student.id,
        program_id=program.id,
        institution_id=first.id,
        academic_year="2025-26",
        year_of_study=3,
        admission_type="regular",
        status="admitted",
        admitted_on=date(2025, 8, 5),
    )
    db.add_all([enrolment, admitted])
    db.commit()
    return {"enrolment": enrolment, "admitted": admitted, "student": student, "first": first}


def _pdf_is_well_formed(content: bytes) -> None:
    assert content.startswith(b"%PDF-1.4")
    assert content.rstrip().endswith(b"%%EOF")
    offset = int(re.search(rb"startxref\n(\d+)", content).group(1))
    assert content[offset : offset + 4] == b"xref"
    # Every object offset in the xref table must point at "<n> 0 obj".
    table = content[offset:].split(b"trailer")[0].splitlines()[3:]
    for number, row in enumerate(table, start=1):
        position = int(row[:10])
        assert content[position:].startswith(f"{number} 0 obj".encode())


# --------------------------------------------------------------------------- pdf writer


def test_pdf_writer_produces_a_valid_file_with_searchable_text() -> None:
    pdf = PdfDocument(title="Test (with parens)")
    pdf.text(40, 60, "Hello — APAAR (masked) \\ ok", size=12, weight="bold")
    pdf.qr(40, 100, 100, "https://example.invalid/verify?doc=abc")
    pdf.new_page()
    pdf.rect(40, 40, 100, 20, fill=(1, 0, 0), stroke=(0, 0, 0))
    content = pdf.to_bytes()
    _pdf_is_well_formed(content)
    assert b"/Count 2" in content
    assert b"Hello \\227 APAAR \\(masked\\) \\\\ ok" in content


def test_text_measurement_and_wrapping() -> None:
    assert text_width("iii", 10) < text_width("WWW", 10)
    lines = wrap("one two three four five six seven", 60, 10)
    assert len(lines) > 1
    assert all(text_width(line, 10) <= 60 or " " not in line for line in lines)


# --------------------------------------------------------------------------- issuing


def test_institution_issues_a_certificate_with_apaar_and_student_id(
    client: TestClient, auth, completed, db: Session
) -> None:
    listing = client.get("/institution/degree-certificates", headers=auth("institution"))
    assert listing.status_code == 200
    rows = listing.json()["items"]
    assert [row["enrolment_id"] for row in rows] == [completed["enrolment"].id]
    assert rows[0]["certificate"] is None
    assert rows[0]["apaar_masked"] == "XXXX-XXXX-1234"

    response = client.post(
        "/institution/degree-certificates",
        json={"enrolment_id": completed["enrolment"].id},
        headers=auth("institution"),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["created"] is True
    assert body["serial"].startswith("DC-2026-")
    assert "/verify?doc=" in body["verify_url"]

    document = db.execute(select(IssuedDocument)).scalar_one()
    assert document.claims["apaar"] == "XXXX-XXXX-1234"
    assert document.claims["sid"].endswith(f"/2026/{completed['enrolment'].id:06d}")
    assert APAAR not in str(document.claims)
    assert "Rahul" not in str(document.claims)

    again = client.post(
        "/institution/degree-certificates",
        json={"enrolment_id": completed["enrolment"].id},
        headers=auth("institution"),
    )
    assert again.json()["created"] is False
    assert again.json()["serial"] == body["serial"]
    assert db.query(AuditLog).filter(AuditLog.action == "degree_certificate_issued").count() == 1


def test_certificate_downloads_as_pdf_and_html_masked_by_default(
    client: TestClient, auth, completed
) -> None:
    serial = client.post(
        "/institution/degree-certificates",
        json={"enrolment_id": completed["enrolment"].id},
        headers=auth("institution"),
    ).json()["serial"]

    pdf = client.get(f"/institution/degree-certificates/{serial}", headers=auth("institution"))
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    _pdf_is_well_formed(pdf.content)
    assert b"XXXX-XXXX-1234" in pdf.content
    assert b"Student ID" in pdf.content
    assert APAAR.encode() not in pdf.content
    assert b"synthetic" in pdf.content

    html = client.get(
        f"/institution/degree-certificates/{serial}", params={"format": "html"}, headers=auth("institution")
    )
    assert html.status_code == 200
    assert "XXXX-XXXX-1234" in html.text
    assert "Rahul Sharma" not in html.text
    assert "data:image/png;base64," in html.text


def test_full_identity_display_prints_vault_values_and_logs_the_access(
    client: TestClient, auth, completed, db: Session, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "certificate_identity_display", "full")
    serial = client.post(
        "/institution/degree-certificates",
        json={"enrolment_id": completed["enrolment"].id},
        headers=auth("institution"),
    ).json()["serial"]
    html = client.get(
        f"/institution/degree-certificates/{serial}", params={"format": "html"}, headers=auth("institution")
    )
    assert "1234-5678-1234" in html.text
    assert "Rahul Sharma" in html.text
    log = db.execute(select(AccessLog).where(AccessLog.action == "degree_certificate_printed")).scalar_one()
    assert log.student_id == completed["student"].id
    # The QR still carries only masked claims.
    document = db.execute(select(IssuedDocument)).scalar_one()
    assert APAAR not in str(document.claims)


def test_only_completed_enrolments_get_a_certificate(client: TestClient, auth, completed) -> None:
    response = client.post(
        "/institution/degree-certificates",
        json={"enrolment_id": completed["admitted"].id},
        headers=auth("institution"),
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "NOT_COMPLETED"


def test_another_institution_cannot_issue_or_read_the_certificate(
    client: TestClient, auth, completed
) -> None:
    response = client.post(
        "/institution/degree-certificates",
        json={"enrolment_id": completed["enrolment"].id},
        headers=auth("institution_other"),
    )
    assert response.status_code == 404
    serial = client.post(
        "/institution/degree-certificates",
        json={"enrolment_id": completed["enrolment"].id},
        headers=auth("institution"),
    ).json()["serial"]
    assert client.get(f"/institution/degree-certificates/{serial}", headers=auth("institution_other")).status_code == 404
    assert client.get("/institution/degree-certificates", headers=auth("institution_other")).json()["items"] == []
    assert client.get("/institution/degree-certificates", headers=auth("student")).status_code == 403


# --------------------------------------------------------------------------- public check


def _token(client: TestClient, auth, completed) -> tuple[str, str]:
    body = client.post(
        "/institution/degree-certificates",
        json={"enrolment_id": completed["enrolment"].id},
        headers=auth("institution"),
    ).json()
    return body["serial"], body["verify_url"].split("doc=", 1)[1]


def test_public_check_confirms_a_genuine_certificate(client: TestClient, auth, completed) -> None:
    serial, token = _token(client, auth, completed)
    response = client.get(f"/verify/document/{token}")
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "genuine"
    assert body["kind"] == "degree_certificate"
    assert body["serial"] == serial
    assert body["claims"]["apaar"] == "XXXX-XXXX-1234"
    assert body["claims"]["yr"] == YEAR


def test_public_check_reports_revocation_and_tampering(client: TestClient, auth, completed) -> None:
    serial, token = _token(client, auth, completed)

    header, payload, signature = token.split(".")
    forged = f"{header}.{payload[:-2]}AA.{signature}"
    forged_check = client.get(f"/verify/document/{forged}").json()
    assert forged_check["state"] == "invalid"
    assert forged_check["claims"] is None
    assert client.get("/verify/document/not-a-token").json()["state"] == "invalid"

    short = client.post(
        f"/institution/degree-certificates/{serial}/revoke",
        json={"reason": "typo"},
        headers=auth("institution"),
    )
    assert short.status_code == 400
    revoked = client.post(
        f"/institution/degree-certificates/{serial}/revoke",
        json={"reason": "Issued against the wrong enrolment record."},
        headers=auth("institution"),
    )
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "revoked"
    body = client.get(f"/verify/document/{token}").json()
    assert body["state"] == "revoked"
    assert body["revoked_at"] is not None


def test_a_signed_token_whose_claims_were_not_issued_is_invalid(
    client: TestClient, auth, completed, db: Session
) -> None:
    _serial, token = _token(client, auth, completed)
    claims = documents.decode_token(token)
    claims["prog"] = "M.Tech — Something Else"
    resigned = documents.sign_claims(claims)
    assert client.get(f"/verify/document/{resigned}").json()["state"] == "invalid"
