"""Phase 3: a college can never read or change another college's rows.

Every institution endpoint is attacked three ways — another college's id in the URL, an
``institution_id`` smuggled into the query string, and one smuggled into the body — and
must answer 404 (never confirming the row exists) or simply ignore the smuggled value.
"""
from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crypto import hmac_hash, mask_apaar, mask_name, vault_encrypt
from app.models.core import Enrolment, Flag, Institution, Program, Student, Upload, Vault
from app.services import degree_certificate

YEAR = "2026-27"


def _seed_college(db: Session, institution: Institution, index: int) -> dict[str, Any]:
    program = db.execute(select(Program).where(Program.institution_id == institution.id)).scalars().first()
    apaar = f"{555500000000 + index:012d}"
    student = Student(
        apaar_hash=hmac_hash(apaar),
        apaar_masked=mask_apaar(apaar),
        apaar_status="provided",
        name_masked=mask_name("Meera Iyer"),
        dob_year=2003,
        registry_status="match",
    )
    db.add(student)
    db.flush()
    db.add(Vault(student_id=student.id, apaar_enc=vault_encrypt(apaar),
                 name_enc=vault_encrypt("Meera Iyer"), dob_enc=vault_encrypt("2003-01-15")))
    upload = Upload(institution_id=institution.id, filename=f"college_{index}.xlsx",
                    state="pending_mapping", academic_year=YEAR, uploaded_by="someone")
    db.add(upload)
    db.flush()
    enrolment = Enrolment(student_id=student.id, program_id=program.id, institution_id=institution.id,
                          academic_year=YEAR, year_of_study=4, admission_type="regular",
                          status="completed", admitted_on=date(2023, 8, 1), upload_id=upload.id)
    db.add(enrolment)
    db.flush()
    flag = Flag(type="LATE_ADMISSION", severity="low", status="open", institution_id=institution.id,
                student_id=student.id, enrolment_id=enrolment.id, title="Late admission",
                explanation="Admitted after the cutoff.", evidence={}, dedupe_key=f"t:{index}",
                academic_year=YEAR, notes=[])
    db.add(flag)
    db.flush()
    document, _token, _created = degree_certificate.issue_for_enrolment(
        db, institution_id=institution.id, enrolment_id=enrolment.id, actor="setup"
    )
    db.commit()
    return {"institution": institution, "student": student, "enrolment": enrolment,
            "upload": upload, "flag": flag, "serial": document.serial}


@pytest.fixture()
def colleges(db: Session, two_institutions, users) -> dict[str, dict[str, Any]]:
    first, second = two_institutions
    return {"own": _seed_college(db, first, 1), "other": _seed_college(db, second, 2)}


def _not_found(response) -> None:
    assert response.status_code == 404, f"expected 404, got {response.status_code}: {response.text[:200]}"
    assert response.json()["error"]["code"] == "NOT_FOUND"


# ------------------------------------------------------------------ ids in the URL


def test_another_colleges_upload_cannot_be_read_or_confirmed(client: TestClient, auth, colleges) -> None:
    headers = auth("institution")
    other = colleges["other"]["upload"].id
    _not_found(client.get(f"/institution/uploads/{other}", headers=headers))
    _not_found(client.get(f"/institution/uploads/{other}/errors.csv", headers=headers))
    _not_found(client.post(f"/institution/uploads/{other}/confirm-mapping", headers=headers,
                           json={"mapping": {"APAAR": "apaar_id"}}))


def test_another_colleges_flag_cannot_be_changed(client: TestClient, auth, colleges, db: Session) -> None:
    other = colleges["other"]["flag"]
    response = client.patch(f"/institution/flags/{other.id}", headers=auth("institution"),
                            json={"status": "under_review", "note": "Trying to close a rival's flag."})
    _not_found(response)
    db.expire_all()
    assert db.get(Flag, other.id).status == "open"


def test_another_colleges_enrolment_cannot_be_changed(client: TestClient, auth, colleges, db: Session) -> None:
    other = colleges["other"]["enrolment"]
    response = client.patch(f"/institution/enrolments/{other.id}/status", headers=auth("institution"),
                            json={"status": "cancelled", "reason": "Not ours, trying anyway."})
    _not_found(response)
    db.expire_all()
    assert db.get(Enrolment, other.id).status == "completed"


def test_another_colleges_certificates_are_out_of_reach(client: TestClient, auth, colleges) -> None:
    headers = auth("institution")
    other = colleges["other"]
    _not_found(client.post("/institution/degree-certificates", headers=headers,
                           json={"enrolment_id": other["enrolment"].id}))
    _not_found(client.get(f"/institution/degree-certificates/{other['serial']}", headers=headers))
    _not_found(client.post(f"/institution/degree-certificates/{other['serial']}/revoke", headers=headers,
                           json={"reason": "Revoking a rival's certificate."}))


# ------------------------------------------------------------------ institution_id in the query


LIST_ROUTES = (
    "/institution/me",
    "/institution/students",
    "/institution/uploads",
    "/institution/flags",
    "/institution/seat-matrix?academic_year=2026-27",
    "/institution/dashboard",
    "/institution/degree-certificates",
)


def test_an_institution_id_in_the_query_string_is_ignored(client: TestClient, auth, colleges) -> None:
    headers = auth("institution")
    own, other = colleges["own"], colleges["other"]
    joiner = lambda path: "&" if "?" in path else "?"  # noqa: E731
    for path in LIST_ROUTES:
        plain = client.get(path, headers=headers)
        smuggled = client.get(f"{path}{joiner(path)}institution_id={other['institution'].id}", headers=headers)
        assert plain.status_code == smuggled.status_code == 200, path
        assert plain.json() == smuggled.json(), path

    students = client.get(f"/institution/students?institution_id={other['institution'].id}", headers=headers).json()
    assert {row["student_id"] for row in students["items"]} == {own["student"].id}
    uploads = client.get(f"/institution/uploads?institution_id={other['institution'].id}", headers=headers).json()
    assert {row["id"] for row in uploads["items"]} == {own["upload"].id}
    flags = client.get(f"/institution/flags?institution_id={other['institution'].id}", headers=headers).json()
    assert {row["id"] for row in flags["items"]} == {own["flag"].id}
    me = client.get(f"/institution/me?institution_id={other['institution'].id}", headers=headers).json()
    assert me["id"] == own["institution"].id


# ------------------------------------------------------------------ institution_id in the body


def test_an_institution_id_in_a_body_is_ignored(client: TestClient, auth, colleges, db: Session) -> None:
    headers = auth("institution")
    own, other = colleges["own"], colleges["other"]

    # A status change on our own row, with the other college's id in the body.
    response = client.patch(
        f"/institution/enrolments/{own['enrolment'].id}/status", headers=headers,
        json={"status": "completed", "reason": "Re-confirming.", "institution_id": other["institution"].id},
    )
    assert response.status_code in (200, 409)
    db.expire_all()
    assert db.get(Enrolment, own["enrolment"].id).institution_id == own["institution"].id

    # An upload posted with the other college's id as a form field lands with us.
    csv_body = b"APAAR ID,Student Name,DOB\n123412341234,Asha Rao,2005-01-01\n"
    created = client.post(
        "/institution/uploads", headers=headers,
        files={"file": ("students.csv", csv_body, "text/csv")},
        data={"academic_year": YEAR, "institution_id": str(other["institution"].id)},
    )
    assert created.status_code == 201, created.text
    upload = db.get(Upload, created.json()["upload_id"])
    assert upload.institution_id == own["institution"].id


def test_the_other_college_is_never_named_in_our_responses(client: TestClient, auth, colleges) -> None:
    headers = auth("institution")
    other_name = colleges["other"]["institution"].name
    for path in LIST_ROUTES:
        assert other_name not in client.get(path, headers=headers).text, path
