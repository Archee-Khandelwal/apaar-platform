"""Phase 6: AICTE master records and the reconciliation of each submitted record against
them — the six checks, the master-records import, the AICTE and institution views, and
that a document change recomputes the result."""
from __future__ import annotations

import io
from datetime import date

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crypto import hmac_hash, mask_apaar, mask_name, vault_encrypt
from app.models.core import (
    AccessLog,
    ApprovedIntake,
    AuditLog,
    Enrolment,
    InstitutionApproval,
    MasterImport,
    Program,
    Reconciliation,
    Student,
    StudentDocument,
    Vault,
)
from app.services.reconciliation import reconcile
from app.services.rules import required_documents, supernumerary_caps

YEAR = "2026-27"
PDF = b"%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF\n"


def _program(db: Session, institution) -> Program:
    return db.execute(select(Program).where(Program.institution_id == institution.id)).scalars().first()


def _master(db: Session, institution, *, intake: int = 60, status: str = "approved",
            programme_status: str = "approved") -> Program:
    program = _program(db, institution)
    db.add(InstitutionApproval(institution_id=institution.id, academic_year=YEAR, status=status))
    db.add(ApprovedIntake(program_id=program.id, academic_year=YEAR, intake=intake,
                          supernumerary_caps=supernumerary_caps(intake), status=programme_status))
    db.commit()
    return program


def _student(db: Session, institution, apaar: str, *, registry: str | None = "match", documents: bool = True,
             admitted_on: date = date(2026, 8, 1), admission_type: str = "regular") -> Student:
    program = _program(db, institution)
    student = Student(apaar_hash=hmac_hash(apaar), apaar_masked=mask_apaar(apaar), apaar_status="provided",
                      name_masked=mask_name("Kavya Menon"), nationality_status="indian", category="GEN",
                      dob_year=2006, registry_status=registry)
    db.add(student)
    db.flush()
    db.add(Vault(student_id=student.id, apaar_enc=vault_encrypt(apaar), name_enc=vault_encrypt("Kavya Menon"),
                 dob_enc=vault_encrypt("2006-05-04")))
    db.add(Enrolment(student_id=student.id, program_id=program.id, institution_id=institution.id,
                     academic_year=YEAR, year_of_study=1, admission_type=admission_type, status="admitted",
                     admitted_on=admitted_on))
    if documents:
        for doc_type in required_documents(admission_type=admission_type, category="GEN", nationality_status="indian"):
            db.add(StudentDocument(student_id=student.id, institution_id=institution.id, doc_type=doc_type,
                                   original_filename="d.pdf", content_type="application/pdf", size_bytes=1,
                                   sha256="0" * 64, content_enc=b"x", verification_status="verified",
                                   issuer_status="verified"))
    db.commit()
    return student


def _result(db: Session, student: Student) -> Reconciliation:
    return db.execute(select(Reconciliation).where(Reconciliation.student_id == student.id)).scalars().one()


def _csv(text: str) -> dict:
    return {"file": ("master.csv", text.encode(), "text/csv")}


# ------------------------------------------------------------------ the six checks


def test_a_clean_record_is_confirmed_with_every_check_passing(db: Session, two_institutions) -> None:
    first, _ = two_institutions
    _master(db, first)
    student = _student(db, first, "710000000001")
    reconcile(db)
    row = _result(db, student)
    assert row.overall == "confirmed"
    assert set(row.checks) == {"institution_approved", "programme_approved", "within_intake",
                               "apaar_verified", "documents_verified", "no_duplicate"}
    assert all(check["result"] == "pass" for check in row.checks.values())


def test_missing_documents_and_a_registry_mismatch_need_review(db: Session, two_institutions) -> None:
    first, _ = two_institutions
    _master(db, first)
    no_docs = _student(db, first, "710000000002", documents=False)
    mismatch = _student(db, first, "710000000003", registry="mismatch")
    reconcile(db)
    assert _result(db, no_docs).overall == "needs_review"
    docs = _result(db, no_docs).checks["documents_verified"]
    assert docs["result"] == "review" and "Not yet submitted" in docs["message"] and docs["fix"].startswith("Upload")
    assert _result(db, mismatch).overall == "needs_review"
    assert _result(db, mismatch).checks["apaar_verified"]["result"] == "review"


def test_an_unknown_apaar_id_is_rejected(db: Session, two_institutions) -> None:
    first, _ = two_institutions
    _master(db, first)
    student = _student(db, first, "710000000004", registry="not_found")
    reconcile(db)
    assert _result(db, student).overall == "rejected"
    assert "no record" in _result(db, student).checks["apaar_verified"]["message"]


def test_admissions_past_intake_are_rejected_latest_first(db: Session, two_institutions) -> None:
    first, _ = two_institutions
    _master(db, first, intake=1)
    early = _student(db, first, "710000000005", admitted_on=date(2026, 7, 1))
    late = _student(db, first, "710000000006", admitted_on=date(2026, 9, 1))
    reconcile(db)
    assert _result(db, early).checks["within_intake"]["result"] == "pass"
    over = _result(db, late).checks["within_intake"]
    assert over["result"] == "fail" and "2 of 2" in over["message"] and _result(db, late).overall == "rejected"


def test_an_institution_without_fresh_admissions_is_rejected_for_year_one_entrants(db: Session, two_institutions) -> None:
    first, _ = two_institutions
    _master(db, first, status="no_admission")
    student = _student(db, first, "710000000007")
    reconcile(db)
    check = _result(db, student).checks["institution_approved"]
    assert check["result"] == "fail" and "not permitted fresh admissions" in check["message"]


def test_a_withdrawn_programme_is_rejected_and_a_missing_record_too(db: Session, two_institutions) -> None:
    first, second = two_institutions
    _master(db, first, programme_status="withdrawn")
    withdrawn = _student(db, first, "710000000008")
    unapproved = _student(db, second, "710000000009")  # no master records at all for the second institution
    reconcile(db)
    assert "withdrawn" in _result(db, withdrawn).checks["programme_approved"]["message"]
    assert _result(db, unapproved).checks["institution_approved"]["result"] == "fail"
    assert _result(db, unapproved).checks["programme_approved"]["result"] == "fail"


# ------------------------------------------------------------------ master-records import


def test_importing_institution_approvals_changes_the_result_and_reports_bad_rows(
    client: TestClient, auth, db: Session, two_institutions
) -> None:
    first, _ = two_institutions
    _master(db, first)
    student = _student(db, first, "710000000010")
    reconcile(db)
    assert _result(db, student).overall == "confirmed"

    text = (
        "aicte_permanent_id,academic_year,status,reference\n"
        f"{first.aicte_permanent_id},{YEAR},no_admission,EOA/2026/9\n"
        "9-9999999999,2026-27,approved,\n"
        f"{first.aicte_permanent_id},2026,approved,\n"
        f"{first.aicte_permanent_id},{YEAR},banana,\n"
    )
    response = client.post("/aicte/master/import", headers=auth("aicte_officer"), data={"kind": "institutions"},
                           files=_csv(text))
    assert response.status_code == 201, response.text
    body = response.json()
    assert (body["rows_total"], body["rows_ok"], body["rows_error"]) == (4, 1, 3)
    assert [issue["row"] for issue in body["issues"]] == [3, 4, 5]
    db.expire_all()
    assert _result(db, student).overall == "rejected"
    assert db.get(InstitutionApproval, 1).source == "import"
    assert db.execute(select(AuditLog).where(AuditLog.action == "master_records_import")).scalars().one()


def test_importing_programmes_from_excel_creates_programme_and_intake(
    client: TestClient, auth, db: Session, two_institutions
) -> None:
    first, _ = two_institutions
    buffer = io.BytesIO()
    pd.DataFrame([{
        "aicte_permanent_id": first.aicte_permanent_id, "course": "B.Tech", "branch": "Data Science",
        "academic_year": YEAR, "intake": 30, "status": "approved",
    }]).to_excel(buffer, index=False)
    response = client.post(
        "/aicte/master/import", headers=auth("admin"), data={"kind": "programmes"},
        files={"file": ("programmes.xlsx", buffer.getvalue(), "application/octet-stream")},
    )
    assert response.status_code == 201, response.text
    assert response.json()["rows_ok"] == 1
    program = db.execute(select(Program).where(Program.branch == "Data Science")).scalar_one()
    intake = db.execute(select(ApprovedIntake).where(ApprovedIntake.program_id == program.id)).scalar_one()
    assert (intake.intake, intake.status, intake.source) == (30, "approved", "import")
    assert intake.supernumerary_caps == supernumerary_caps(30)
    assert db.execute(select(MasterImport)).scalars().one().kind == "programmes"


def test_a_file_missing_columns_or_of_the_wrong_type_is_refused(client: TestClient, auth) -> None:
    headers = auth("aicte_officer")
    bad_columns = client.post("/aicte/master/import", headers=headers, data={"kind": "institutions"},
                              files=_csv("aicte_permanent_id,status\n1,approved\n"))
    assert bad_columns.status_code == 400 and "academic_year" in bad_columns.json()["error"]["message"]
    wrong_type = client.post("/aicte/master/import", headers=headers, data={"kind": "institutions"},
                             files={"file": ("x.pdf", PDF, "application/pdf")})
    assert wrong_type.status_code == 400


def test_only_aicte_officers_and_admins_may_import(client: TestClient, auth) -> None:
    for role in ("institution", "aicte_viewer", "student", "verifier"):
        response = client.post("/aicte/master/import", headers=auth(role), data={"kind": "institutions"},
                               files=_csv("aicte_permanent_id,academic_year,status\n"))
        assert response.status_code == 403, role


# ------------------------------------------------------------------ AICTE screens


@pytest.fixture()
def world(db: Session, two_institutions):
    first, second = two_institutions
    _master(db, first)
    good = _student(db, first, "720000000001")
    pending = _student(db, first, "720000000002", documents=False)
    rejected = _student(db, first, "720000000003", registry="not_found")
    other = _student(db, second, "720000000004")  # second institution has no master records
    reconcile(db)
    db.commit()
    return {"first": first, "second": second, "good": good, "pending": pending, "rejected": rejected, "other": other}


def test_the_dashboard_counts_each_status_and_hides_small_counts_from_the_viewer(
    client: TestClient, auth, world
) -> None:
    officer = client.get("/aicte/reconciliation/summary", headers=auth("aicte_officer")).json()
    row = next(item for item in officer["items"] if item["institution_id"] == world["first"].id)
    assert (row["confirmed"], row["needs_review"], row["rejected"], row["records"]) == (1, 1, 1, 3)
    assert officer["totals"]["records"] == 4

    viewer = client.get("/aicte/reconciliation/summary", headers=auth("aicte_viewer")).json()
    row = next(item for item in viewer["items"] if item["institution_id"] == world["first"].id)
    assert row["confirmed"] == row["needs_review"] == row["rejected"] == row["records"] == "<5"


def test_records_can_be_retrieved_by_apaar_institution_status_and_failing_check(
    client: TestClient, auth, world
) -> None:
    headers = auth("aicte_officer")
    full = client.get("/aicte/reconciliation/records", headers=headers, params={"q": "720000000002"}).json()
    assert [item["student_id"] for item in full["items"]] == [world["pending"].id]
    assert full["items"][0]["apaar_masked"] == "XXXX-XXXX-0002"
    assert "720000000002" not in str(full)

    last4 = client.get("/aicte/reconciliation/records", headers=headers, params={"q": "0003"}).json()
    assert [item["student_id"] for item in last4["items"]] == [world["rejected"].id]

    scoped = client.get("/aicte/reconciliation/records", headers=headers,
                        params={"institution_id": world["first"].id, "overall": "needs_review"}).json()
    assert scoped["total"] == 1 and scoped["items"][0]["problems"][0]["check"] == "documents_verified"

    failing = client.get("/aicte/reconciliation/records", headers=headers,
                         params={"failing_check": "apaar_verified"}).json()
    assert [item["student_id"] for item in failing["items"]] == [world["rejected"].id]


def test_the_csv_holds_confirmed_records_only_and_masked_identifiers(client: TestClient, auth, world, db: Session) -> None:
    response = client.get("/aicte/reconciliation/records.csv", headers=auth("aicte_viewer"),
                          params={"institution_id": world["first"].id})
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/csv")
    lines = response.text.strip().splitlines()
    assert len(lines) == 2  # header + the one confirmed record
    assert "XXXX-XXXX-0001" in lines[1] and "720000000001" not in response.text
    assert db.execute(select(AccessLog).where(AccessLog.action == "export_confirmed_records")).scalars().one()


def test_the_record_page_shows_submitted_data_apaar_documents_and_checks(client: TestClient, auth, world, db: Session) -> None:
    enrolment = db.execute(select(Enrolment).where(Enrolment.student_id == world["pending"].id)).scalar_one()
    body = client.get(f"/aicte/reconciliation/records/{enrolment.id}", headers=auth("aicte_viewer")).json()
    assert body["overall"] == "needs_review"
    assert body["submitted"]["category"] == "GEN" and body["apaar"]["registry_status"] == "match"
    assert body["master"]["approved_intake"] == 60 and body["master"]["institution_status"] == "approved"
    assert {item["status"] for item in body["documents"]} == {"missing"}
    assert [check["check"] for check in body["checks"]][0] == "institution_approved" and len(body["checks"]) == 6
    assert db.execute(select(AccessLog).where(AccessLog.action == "view_reconciliation_record")).scalars().one()
    assert client.get("/aicte/reconciliation/records/999999", headers=auth("aicte_viewer")).status_code == 404


def test_reconciliation_routes_refuse_other_roles(client: TestClient, auth) -> None:
    for role in ("institution", "student", "verifier", "admin"):
        for path in ("/aicte/reconciliation/summary", "/aicte/reconciliation/records", "/aicte/reconciliation/records.csv"):
            assert client.get(path, headers=auth(role)).status_code == 403, (role, path)


# ------------------------------------------------------------------ institution screen


def test_an_institution_sees_only_its_own_status_and_what_to_fix(client: TestClient, auth, world) -> None:
    body = client.get("/institution/reconciliation", headers=auth("institution")).json()
    assert body["counts"] == {"confirmed": 1, "needs_review": 1, "rejected": 1}
    assert {item["student_id"] for item in body["items"]} == {
        world["good"].id, world["pending"].id, world["rejected"].id}
    checks = [entry["check"] for entry in body["to_fix"]]
    assert checks[0] == "apaar_verified"  # a failure outranks a review item
    assert {"documents_verified"} <= set(checks)
    assert all(entry["fix"] for entry in body["to_fix"])

    other = client.get("/institution/reconciliation", headers=auth("institution_other")).json()
    assert other["records"] == 1 and other["counts"]["rejected"] == 1
    assert {item["student_id"] for item in other["items"]} == {world["other"].id}
    assert world["first"].name not in str(other)


def test_a_duplicate_finding_never_names_the_other_college(client: TestClient, auth, world, db: Session) -> None:
    from app.models.core import Flag

    db.add(Flag(type="CROSS_INSTITUTION_DUPLICATE", severity="high", institution_id=world["first"].id,
                student_id=world["good"].id, title="t", explanation="e",
                evidence={"other_institution": world["second"].name}, status="open", dedupe_key="test-dup-1"))
    db.commit()
    reconcile(db)
    db.commit()
    body = client.get("/institution/reconciliation", headers=auth("institution"), params={"overall": "rejected"}).json()
    text = str(body)
    assert "contact AICTE" in text and world["second"].name not in text


# ------------------------------------------------------------------ recomputed on change


def test_uploading_a_document_recomputes_the_result(client: TestClient, auth, world, db: Session) -> None:
    assert "admission_letter" in _result(db, world["pending"]).checks["documents_verified"]["missing"]
    response = client.post(
        f"/institution/students/{world['pending'].id}/documents", headers=auth("institution"),
        files={"file": ("a.pdf", PDF, "application/octet-stream")}, data={"doc_type": "admission_letter"},
    )
    assert response.status_code == 201, response.text
    db.expire_all()
    assert "admission_letter" not in _result(db, world["pending"]).checks["documents_verified"]["missing"]
