"""Step 12 (institution side): own flags, versioned status changes, certificate."""
from __future__ import annotations

import json
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crypto import hmac_hash, mask_apaar, mask_name
from app.models.core import (
    ApprovedIntake,
    AuditLog,
    Enrolment,
    EnrolmentHistory,
    Flag,
    Program,
    Student,
    Upload,
)
from app.services.flags import CROSS_INSTITUTION_NOTICE
from app.services.rules import supernumerary_caps

YEAR = "2026-27"


@pytest.fixture()
def setup(db: Session, two_institutions) -> dict:
    first, second = two_institutions
    program = db.execute(select(Program).where(Program.institution_id == first.id)).scalars().first()
    other_program = db.execute(
        select(Program).where(Program.institution_id == second.id)
    ).scalars().first()
    db.add(
        ApprovedIntake(
            program_id=program.id,
            academic_year=YEAR,
            intake=120,
            supernumerary_caps=supernumerary_caps(120),
        )
    )
    db.add(
        Upload(
            institution_id=first.id,
            filename="students.xlsx",
            state="completed",
            academic_year=YEAR,
            rows_total=20,
            rows_ok=20,
            quality_score=88,
        )
    )

    students = []
    for index in range(3):
        apaar = f"{222222220000 + index:012d}"
        student = Student(
            apaar_hash=hmac_hash(apaar),
            apaar_masked=mask_apaar(apaar),
            apaar_status="provided",
            name_masked=mask_name(f"Student Number{index}"),
            dob_year=2006,
        )
        db.add(student)
        db.flush()
        db.add(
            Enrolment(
                student_id=student.id,
                program_id=program.id,
                institution_id=first.id,
                academic_year=YEAR,
                year_of_study=1,
                admission_type="regular",
                status="admitted",
                admitted_on=date(2026, 8, 5),
            )
        )
        students.append(student)
    db.commit()

    return {
        "first": first,
        "second": second,
        "program": program,
        "other_program": other_program,
        "students": students,
    }


def add_flag(db: Session, **kwargs) -> Flag:
    defaults = {
        "type": "LATE_ADMISSION",
        "severity": "medium",
        "status": "open",
        "title": "A finding",
        "explanation": "Something to fix.",
        "evidence": {},
        "notes": [],
        "academic_year": YEAR,
    }
    defaults.update(kwargs)
    defaults.setdefault("dedupe_key", f"test:{defaults['type']}:{defaults.get('student_id')}")
    flag = Flag(**defaults)
    db.add(flag)
    db.commit()
    return flag


# ------------------------------------------------------------------ own flags only


def test_institution_sees_only_its_own_flags(client: TestClient, auth, setup, db: Session) -> None:
    add_flag(db, institution_id=setup["first"].id, title="Mine")
    add_flag(db, institution_id=setup["second"].id, title="Theirs", dedupe_key="test:other")

    body = client.get("/institution/flags", headers=auth("institution")).json()
    assert body["total"] == 1
    assert body["items"][0]["title"] == "Mine"

    other = client.get("/institution/flags", headers=auth("institution_other")).json()
    assert other["total"] == 1
    assert other["items"][0]["title"] == "Theirs"


def test_duplicate_flag_never_names_the_other_college(
    client: TestClient, auth, setup, db: Session
) -> None:
    """CLAUDE.md section 5 rule 10."""
    add_flag(
        db,
        type="CROSS_INSTITUTION_DUPLICATE",
        severity="high",
        institution_id=setup["first"].id,
        student_id=setup["students"][0].id,
        title="Same APAAR ID enrolled full-time at two institutions",
        explanation=f"Enrolled at {setup['first'].name} and {setup['second'].name}.",
        evidence={
            "apaar_masked": setup["students"][0].apaar_masked,
            "sides": [
                {"institution_id": setup["first"].id, "institution_name": setup["first"].name},
                {"institution_id": setup["second"].id, "institution_name": setup["second"].name},
            ],
            "institutions": [setup["first"].name, setup["second"].name],
        },
    )

    body = client.get("/institution/flags", headers=auth("institution")).json()
    row = body["items"][0]
    blob = json.dumps(row)
    assert setup["second"].name not in blob
    assert setup["first"].name not in blob
    assert row["explanation"] == CROSS_INSTITUTION_NOTICE
    assert row["title"] == "Possible duplicate enrolment"
    assert "sides" not in row["evidence"]
    # The masked APAAR is still there, so the college can find the record.
    assert row["evidence"]["apaar_masked"] == setup["students"][0].apaar_masked


def test_institution_flag_filters(client: TestClient, auth, setup, db: Session) -> None:
    add_flag(db, institution_id=setup["first"].id, type="LATE_ADMISSION", severity="medium")
    add_flag(
        db,
        institution_id=setup["first"].id,
        type="EXCESS_INTAKE",
        severity="high",
        dedupe_key="test:excess",
    )
    headers = auth("institution")
    assert client.get("/institution/flags?type=EXCESS_INTAKE", headers=headers).json()["total"] == 1
    assert client.get("/institution/flags?severity=high", headers=headers).json()["total"] == 1
    assert client.get("/institution/flags?status=open", headers=headers).json()["total"] == 2


# ------------------------------------------------------------------ institution case actions


def test_institution_can_mark_its_flag_reviewed_or_resolved(
    client: TestClient, auth, setup, db: Session
) -> None:
    flag = add_flag(db, institution_id=setup["first"].id)
    headers = auth("institution")

    reviewed = client.patch(
        f"/institution/flags/{flag.id}", headers=headers, json={"status": "under_review"}
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["status"] == "under_review"

    resolved = client.patch(
        f"/institution/flags/{flag.id}",
        headers=headers,
        json={"status": "resolved", "note": "Row corrected and re-uploaded."},
    )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "resolved"


def test_institution_cannot_escalate_or_dismiss(client: TestClient, auth, setup, db: Session) -> None:
    flag = add_flag(db, institution_id=setup["first"].id)
    for status in ("dismissed", "escalated"):
        response = client.patch(
            f"/institution/flags/{flag.id}",
            headers=auth("institution"),
            json={"status": status, "note": "Trying it on."},
        )
        assert response.status_code == 403
        assert "AICTE" in response.json()["error"]["message"]


def test_resolving_requires_saying_what_changed(client: TestClient, auth, setup, db: Session) -> None:
    flag = add_flag(db, institution_id=setup["first"].id)
    response = client.patch(
        f"/institution/flags/{flag.id}", headers=auth("institution"), json={"status": "resolved"}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "REASON_REQUIRED"


def test_institution_cannot_touch_another_colleges_flag(
    client: TestClient, auth, setup, db: Session
) -> None:
    flag = add_flag(db, institution_id=setup["second"].id, dedupe_key="test:theirs")
    response = client.patch(
        f"/institution/flags/{flag.id}",
        headers=auth("institution"),
        json={"status": "under_review"},
    )
    assert response.status_code == 404  # not 403: we do not confirm it exists


# ------------------------------------------------------------------ students list


def test_students_list_is_masked_and_scoped(client: TestClient, auth, setup) -> None:
    body = client.get(f"/institution/students?academic_year={YEAR}", headers=auth("institution")).json()
    assert body["total"] == 3
    row = body["items"][0]
    assert row["apaar_masked"].startswith("XXXX-XXXX-")
    assert "*" in row["name_masked"]
    assert row["enrolment"]["course"] == "B.Tech"
    assert json.dumps(body).count("@") == 0

    other = client.get("/institution/students", headers=auth("institution_other")).json()
    assert other["total"] == 0


def test_students_list_filters(client: TestClient, auth, setup) -> None:
    headers = auth("institution")
    assert client.get("/institution/students?year_of_study=1", headers=headers).json()["total"] == 3
    assert client.get("/institution/students?year_of_study=2", headers=headers).json()["total"] == 0
    assert (
        client.get("/institution/students?apaar_status=provided", headers=headers).json()["total"] == 3
    )
    masked = client.get("/institution/students", headers=headers).json()["items"][0]["apaar_masked"]
    assert client.get(f"/institution/students?q={masked[-4:]}", headers=headers).json()["total"] >= 1


# ------------------------------------------------------------------ status changes


def test_status_change_is_versioned_with_a_reason(
    client: TestClient, auth, setup, db: Session
) -> None:
    enrolment = db.execute(select(Enrolment)).scalars().first()
    response = client.patch(
        f"/institution/enrolments/{enrolment.id}/status",
        headers=auth("institution"),
        json={
            "status": "cancelled",
            "reason": "Admission cancelled on student request; fee refunded.",
            "effective_date": "2026-09-12",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "cancelled"
    assert body["previous_status"] == "admitted"
    assert body["version"] == 2
    assert body["audit_log_id"]

    history = db.execute(
        select(EnrolmentHistory).where(EnrolmentHistory.enrolment_id == enrolment.id)
    ).scalars().one()
    assert history.from_status == "admitted"
    assert history.to_status == "cancelled"
    assert history.version == 2
    assert history.changed_by == "vit_admin"
    assert history.effective_date == date(2026, 9, 12)

    audit = db.execute(
        select(AuditLog).where(AuditLog.action == "enrolment_status_changed")
    ).scalars().one()
    assert audit.payload["to"] == "cancelled"


def test_status_change_needs_a_real_reason(client: TestClient, auth, setup, db: Session) -> None:
    enrolment = db.execute(select(Enrolment)).scalars().first()
    response = client.patch(
        f"/institution/enrolments/{enrolment.id}/status",
        headers=auth("institution"),
        json={"status": "dropped", "reason": "left"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "REASON_REQUIRED"


def test_every_lifecycle_status_is_accepted(client: TestClient, auth, setup, db: Session) -> None:
    enrolments = list(db.execute(select(Enrolment)).scalars())
    for enrolment, status in zip(enrolments, ("cancelled", "migrated", "dropped")):
        response = client.patch(
            f"/institution/enrolments/{enrolment.id}/status",
            headers=auth("institution"),
            json={"status": status, "reason": f"Student {status} as per register entry."},
        )
        assert response.status_code == 200, status


def test_repeating_the_same_status_is_a_conflict(
    client: TestClient, auth, setup, db: Session
) -> None:
    enrolment = db.execute(select(Enrolment)).scalars().first()
    response = client.patch(
        f"/institution/enrolments/{enrolment.id}/status",
        headers=auth("institution"),
        json={"status": "admitted", "reason": "No change at all really."},
    )
    assert response.status_code == 409


def test_cancelling_an_excess_admission_closes_the_flag(
    client: TestClient, auth, setup, db: Session
) -> None:
    """The seat matrix is recomputed after a status change."""
    program = setup["program"]
    intake = db.execute(
        select(ApprovedIntake).where(ApprovedIntake.program_id == program.id)
    ).scalar_one()
    intake.intake = 2  # now the 3 admitted students are one over
    db.commit()

    from app.services.detectors import run_all_detectors

    run_all_detectors(db, institution_id=setup["first"].id)
    db.commit()
    flag = db.execute(select(Flag).where(Flag.type == "EXCESS_INTAKE")).scalars().one()
    assert flag.status == "open"

    enrolment = db.execute(select(Enrolment)).scalars().first()
    client.patch(
        f"/institution/enrolments/{enrolment.id}/status",
        headers=auth("institution"),
        json={"status": "cancelled", "reason": "Cancelled to correct the intake breach."},
    )
    db.expire_all()
    assert db.get(Flag, flag.id).status == "resolved"


def test_another_institution_cannot_change_our_enrolment(
    client: TestClient, auth, setup, db: Session
) -> None:
    enrolment = db.execute(select(Enrolment)).scalars().first()
    response = client.patch(
        f"/institution/enrolments/{enrolment.id}/status",
        headers=auth("institution_other"),
        json={"status": "cancelled", "reason": "Not my student at all, but trying."},
    )
    assert response.status_code == 404


# ------------------------------------------------------------------ certificate


def test_certificate_is_issued_when_nothing_serious_is_open(
    client: TestClient, auth, setup, db: Session
) -> None:
    add_flag(db, institution_id=setup["first"].id, severity="medium")  # medium does not block
    response = client.get(
        f"/institution/compliance-certificate?academic_year={YEAR}", headers=auth("institution")
    )
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Data Compliance Certificate" in response.text
    assert setup["first"].name in response.text
    assert "all data is synthetic" in response.text
    assert "cert:" in response.text  # the verification reference

    audit = db.execute(
        select(AuditLog).where(AuditLog.action == "certificate_issued")
    ).scalars().one()
    assert audit.payload["academic_year"] == YEAR


def test_certificate_is_refused_with_an_open_high_flag(
    client: TestClient, auth, setup, db: Session
) -> None:
    add_flag(db, institution_id=setup["first"].id, severity="high", type="EXCESS_INTAKE")
    response = client.get(
        f"/institution/compliance-certificate?academic_year={YEAR}", headers=auth("institution")
    )
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "CERTIFICATE_NOT_ELIGIBLE"
    assert error["details"]["blocking_flags"][0]["type"] == "EXCESS_INTAKE"


def test_certificate_eligibility_can_be_checked_without_issuing(
    client: TestClient, auth, setup, db: Session
) -> None:
    add_flag(db, institution_id=setup["first"].id, severity="critical", type="GHOST_CLUSTER")
    body = client.get(
        f"/institution/compliance-certificate?academic_year={YEAR}&format=json",
        headers=auth("institution"),
    ).json()
    assert body["eligible"] is False
    assert body["reasons"]
    assert body["students_reported"] == 3


def test_a_resolved_flag_no_longer_blocks_the_certificate(
    client: TestClient, auth, setup, db: Session
) -> None:
    flag = add_flag(db, institution_id=setup["first"].id, severity="high")
    assert (
        client.get(
            f"/institution/compliance-certificate?academic_year={YEAR}", headers=auth("institution")
        ).status_code
        == 409
    )
    flag.status = "resolved"
    db.commit()
    assert (
        client.get(
            f"/institution/compliance-certificate?academic_year={YEAR}", headers=auth("institution")
        ).status_code
        == 200
    )


# ------------------------------------------------------------------ dashboard


def test_dashboard_summarises_the_institution(client: TestClient, auth, setup, db: Session) -> None:
    add_flag(db, institution_id=setup["first"].id, severity="high")
    body = client.get(f"/institution/dashboard?academic_year={YEAR}", headers=auth("institution")).json()
    assert body["students_reported"] == 3
    assert body["open_flags"]["high"] == 1
    assert body["latest_quality_score"] == 88
    assert body["quality_trend"]
    assert body["seat_matrix_summary"]["approved_intake"] == 120
    assert body["compliance_certificate_eligible"] is False
    assert body["compliance_certificate_reasons"]


def test_institution_routes_refuse_other_roles(client: TestClient, auth, setup) -> None:
    for path in (
        "/institution/flags",
        "/institution/students",
        "/institution/dashboard",
        f"/institution/compliance-certificate?academic_year={YEAR}",
    ):
        for role in ("aicte_officer", "aicte_viewer", "student", "verifier", "admin"):
            assert client.get(path, headers=auth(role)).status_code == 403, f"{path} {role}"
