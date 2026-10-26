"""Step 12: AICTE APIs, case management, reveal, and the role boundaries."""
from __future__ import annotations

import json
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crypto import hash_phone, hmac_hash, mask_apaar, mask_name, vault_encrypt
from app.models.core import (
    AccessLog,
    ApprovedIntake,
    AuditLog,
    Enrolment,
    Flag,
    Institution,
    InstitutionRisk,
    Program,
    ReminderLog,
    Student,
    Upload,
    Vault,
)
from app.services.rules import supernumerary_caps

YEAR = "2026-27"
PREVIOUS = "2025-26"

# Every AICTE route, with the roles that must be refused.
AICTE_ROUTES = (
    ("GET", "/aicte/overview"),
    ("GET", "/aicte/institutions"),
    ("GET", "/aicte/flags"),
    ("GET", "/aicte/non-reporting"),
    ("GET", "/aicte/reports/trends"),
    ("GET", "/aicte/reports/trends.csv"),
    ("GET", "/aicte/risk"),
    ("GET", "/aicte/inspection-shortlist"),
    ("GET", "/aicte/graph/clusters"),
)
OFFICER_ONLY_ROUTES = (
    ("POST", "/aicte/reveal"),
    ("POST", "/aicte/remind/1"),
)


@pytest.fixture()
def dataset(db: Session, two_institutions) -> dict:
    """Two institutions, one student each, one flag each, risk rows and an upload."""
    first, second = two_institutions
    programs = {
        institution.id: db.execute(
            select(Program).where(Program.institution_id == institution.id)
        ).scalars().first()
        for institution in (first, second)
    }
    students: dict[int, Student] = {}

    for index, institution in enumerate((first, second)):
        program = programs[institution.id]
        db.add(
            ApprovedIntake(
                program_id=program.id,
                academic_year=YEAR,
                intake=120,
                supernumerary_caps=supernumerary_caps(120),
            )
        )
        apaar = f"{111111110000 + index:012d}"
        student = Student(
            apaar_hash=hmac_hash(apaar),
            apaar_masked=mask_apaar(apaar),
            apaar_status="provided",
            name_masked=mask_name("Rahul Sharma"),
            dob_year=2006,
            gender="M",
            category="OBC-NCL",
            guardian_phone_hash=hash_phone(f"98765000{index:02d}"),
            registry_status="match",
        )
        db.add(student)
        db.flush()
        db.add(
            Vault(
                student_id=student.id,
                apaar_enc=vault_encrypt(apaar),
                name_enc=vault_encrypt("Rahul Sharma"),
                dob_enc=vault_encrypt("2006-03-12"),
            )
        )
        students[institution.id] = student
        for year in (PREVIOUS, YEAR):
            db.add(
                Enrolment(
                    student_id=student.id,
                    program_id=program.id,
                    institution_id=institution.id,
                    academic_year=year,
                    year_of_study=1 if year == PREVIOUS else 2,
                    admission_type="regular",
                    status="admitted",
                    admitted_on=date(2026, 8, 1),
                )
            )
        db.add(
            Upload(
                institution_id=institution.id,
                filename=f"students_{index}.xlsx",
                state="completed",
                academic_year=YEAR,
                rows_total=10,
                rows_ok=10,
                quality_score=90 - index * 20,
            )
        )
        db.add(
            InstitutionRisk(
                institution_id=institution.id,
                academic_year=YEAR,
                score=80.0 - index * 40,
                band="critical" if index == 0 else "medium",
                reasons=[f"Reason for {institution.name}."],
            )
        )

    db.add_all(
        [
            Flag(
                type="GHOST_CLUSTER",
                severity="critical",
                status="open",
                institution_id=first.id,
                student_id=students[first.id].id,
                title="Cluster of 30 students sharing 2 contacts",
                explanation="30 students share only 2 guardian contacts.",
                evidence={"score": 90, "student_count": 30, "institutions": [first.name]},
                dedupe_key="cluster:test-1",
                academic_year=YEAR,
                notes=[],
            ),
            Flag(
                type="EXCESS_INTAKE",
                severity="high",
                status="open",
                institution_id=second.id,
                program_id=programs[second.id].id,
                title="Admissions exceed approved intake",
                explanation="130 regular admissions vs 120 approved intake.",
                evidence={"excess": 10, "approved_intake": 120},
                dedupe_key="program:test-2",
                academic_year=YEAR,
                notes=[],
            ),
            Flag(
                type="CROSS_INSTITUTION_DUPLICATE",
                severity="high",
                status="open",
                institution_id=first.id,
                student_id=students[first.id].id,
                title="Same APAAR ID enrolled full-time at two institutions",
                explanation=f"Enrolled at {first.name} and {second.name} in {YEAR}.",
                evidence={
                    "apaar_masked": students[first.id].apaar_masked,
                    "sides": [
                        {"institution_id": first.id, "institution_name": first.name},
                        {"institution_id": second.id, "institution_name": second.name},
                    ],
                    "institutions": [first.name, second.name],
                },
                dedupe_key="student:test-3",
                academic_year=YEAR,
                notes=[],
            ),
        ]
    )
    db.commit()
    return {"first": first, "second": second, "programs": programs, "students": students}


# ------------------------------------------------------------------ RBAC


def test_every_aicte_route_refuses_other_roles(client: TestClient, auth, dataset) -> None:
    for method, path in AICTE_ROUTES:
        for role in ("institution", "student", "verifier", "admin"):
            response = client.request(method, path, headers=auth(role))
            assert response.status_code == 403, f"{method} {path} allowed {role}"
            assert response.json()["error"]["code"] == "FORBIDDEN_ROLE"


def test_officer_only_routes_refuse_the_viewer(client: TestClient, auth, dataset) -> None:
    assert (
        client.post(
            "/aicte/reveal",
            headers=auth("aicte_viewer"),
            json={"student_id": 1, "reason": "A perfectly good reason here."},
        ).status_code
        == 403
    )
    assert client.post(f"/aicte/remind/{dataset['first'].id}", headers=auth("aicte_viewer")).status_code == 403
    assert (
        client.patch("/aicte/flags/1", headers=auth("aicte_viewer"), json={"status": "under_review"}).status_code
        == 403
    )


def test_aicte_routes_require_a_token(client: TestClient, dataset) -> None:
    for method, path in AICTE_ROUTES + OFFICER_ONLY_ROUTES:
        assert client.request(method, path).status_code == 401


# ------------------------------------------------------------------ overview


def test_overview_counts_from_student_level_records(client: TestClient, auth, dataset) -> None:
    body = client.get(f"/aicte/overview?academic_year={YEAR}", headers=auth("aicte_officer")).json()
    assert body["academic_year"] == YEAR
    assert body["kpis"]["institutions_total"] == 2
    assert body["kpis"]["students_reported"] == 2
    assert body["kpis"]["total_excess_seats"] == 10
    assert body["kpis"]["open_flags"]["critical"] == 1
    assert body["kpis"]["open_flags"]["high"] == 2
    assert body["suppression_applied"] is False
    types = {row["type"] for row in body["flags_by_type"]}
    assert {"GHOST_CLUSTER", "EXCESS_INTAKE", "CROSS_INSTITUTION_DUPLICATE"} == types
    assert len(body["by_state"]) == 2


def test_overview_suppresses_small_counts_for_the_viewer(client: TestClient, auth, dataset) -> None:
    """CLAUDE.md section 5 rule 9."""
    body = client.get(f"/aicte/overview?academic_year={YEAR}", headers=auth("aicte_viewer")).json()
    assert body["suppression_applied"] is True
    assert body["kpis"]["institutions_total"] == "<5"
    assert body["kpis"]["students_reported"] == "<5"
    assert body["by_state"][0]["institutions"] == "<5"
    # Zero stays zero; it reveals nothing.
    assert body["by_state"][0]["excess_seats"] in (0, "<5")


def test_overview_can_be_filtered_by_state(client: TestClient, auth, dataset) -> None:
    body = client.get(
        f"/aicte/overview?academic_year={YEAR}&state=Madhya Pradesh", headers=auth("aicte_officer")
    ).json()
    assert body["kpis"]["institutions_total"] == 1
    assert [row["state"] for row in body["by_state"]] == ["Madhya Pradesh"]


# ------------------------------------------------------------------ institutions


def test_institution_list_search_filter_and_sort(client: TestClient, auth, dataset) -> None:
    headers = auth("aicte_officer")
    body = client.get("/aicte/institutions", headers=headers).json()
    assert body["total"] == 2
    assert body["items"][0]["risk_score"] >= body["items"][1]["risk_score"]  # -risk_score default

    searched = client.get("/aicte/institutions?q=Vindhyashree", headers=headers).json()
    assert searched["total"] == 1

    by_state = client.get("/aicte/institutions?state=Odisha", headers=headers).json()
    assert by_state["total"] == 1
    assert by_state["items"][0]["state"] == "Odisha"

    risky = client.get("/aicte/institutions?risk_min=60", headers=headers).json()
    assert risky["total"] == 1
    assert risky["items"][0]["risk_score"] == 80.0

    by_flag = client.get("/aicte/institutions?has_flag_type=EXCESS_INTAKE", headers=headers).json()
    assert by_flag["total"] == 1
    assert by_flag["items"][0]["excess_seats"] == 10


def test_institution_profile_has_risk_reasons_and_flags(client: TestClient, auth, dataset) -> None:
    first = dataset["first"]
    body = client.get(
        f"/aicte/institutions/{first.id}?academic_year={YEAR}", headers=auth("aicte_officer")
    ).json()
    assert body["institution"]["name"] == first.name
    assert body["risk"]["score"] == 80.0
    assert body["risk"]["reasons"]
    assert body["reporting"]["uploads"] == 1
    assert body["seat_matrix_summary"]["approved_intake"] == 120
    assert {flag["type"] for flag in body["flags"]} == {"GHOST_CLUSTER", "CROSS_INSTITUTION_DUPLICATE"}
    assert body["upload_timeline"]


def test_unknown_institution_is_404(client: TestClient, auth, dataset) -> None:
    assert client.get("/aicte/institutions/9999", headers=auth("aicte_officer")).status_code == 404


# ------------------------------------------------------------------ flag queue


def test_flag_queue_filters_and_facets(client: TestClient, auth, dataset) -> None:
    headers = auth("aicte_officer")
    body = client.get("/aicte/flags", headers=headers).json()
    assert body["total"] == 3
    assert body["facets"]["by_severity"] == {"critical": 1, "high": 2}
    assert body["facets"]["by_status"] == {"open": 3}

    by_type = client.get("/aicte/flags?type=EXCESS_INTAKE", headers=headers).json()
    assert by_type["total"] == 1

    by_severity = client.get("/aicte/flags?severity=critical", headers=headers).json()
    assert by_severity["total"] == 1

    by_state = client.get("/aicte/flags?state=Odisha", headers=headers).json()
    assert by_state["total"] == 1

    searched = client.get("/aicte/flags?q=approved intake", headers=headers).json()
    assert searched["total"] == 1


def test_flag_queue_sorts_severity_by_seriousness_not_alphabet(
    client: TestClient, auth, dataset
) -> None:
    body = client.get("/aicte/flags?sort=-severity", headers=auth("aicte_officer")).json()
    assert body["items"][0]["severity"] == "critical"


def test_flag_queue_paginates(client: TestClient, auth, dataset) -> None:
    body = client.get("/aicte/flags?page=1&page_size=2", headers=auth("aicte_officer")).json()
    assert len(body["items"]) == 2
    assert body["total"] == 3
    assert body["total_pages"] == 2


def test_viewer_sees_masked_flag_rows_without_evidence(client: TestClient, auth, dataset) -> None:
    """Step-0 decision 3: type, severity, institution, state, status and counts only."""
    body = client.get("/aicte/flags", headers=auth("aicte_viewer")).json()
    row = body["items"][0]
    assert row["type"]
    assert row["severity"]
    assert row["institution_name"]
    assert row["state"]
    assert row["evidence"] is None
    assert row["notes"] is None
    assert row["student_id"] is None
    assert row["assigned_to"] is None


def test_officer_sees_full_evidence(client: TestClient, auth, dataset) -> None:
    body = client.get("/aicte/flags", headers=auth("aicte_officer")).json()
    assert any(row["evidence"] for row in body["items"])


def test_flag_detail_gives_the_officer_the_case_file(client: TestClient, auth, dataset, db) -> None:
    flag = db.execute(select(Flag).where(Flag.type == "GHOST_CLUSTER")).scalars().one()
    body = client.get(f"/aicte/flags/{flag.id}", headers=auth("aicte_officer")).json()
    assert body["evidence"]["student_count"] == 30
    assert body["students"][0]["apaar_masked"].startswith("XXXX-XXXX-")
    assert any(item["type"] == "CROSS_INSTITUTION_DUPLICATE" for item in body["related_flags"])


def test_flag_detail_for_a_viewer_hides_the_case_file(client: TestClient, auth, dataset, db) -> None:
    flag = db.execute(select(Flag).where(Flag.type == "GHOST_CLUSTER")).scalars().one()
    body = client.get(f"/aicte/flags/{flag.id}", headers=auth("aicte_viewer")).json()
    assert body["evidence"] is None
    assert body["history"] == []
    assert body["students"] == []


def test_viewing_a_student_case_file_is_access_logged(
    client: TestClient, auth, dataset, db: Session
) -> None:
    flag = db.execute(select(Flag).where(Flag.type == "GHOST_CLUSTER")).scalars().one()
    client.get(f"/aicte/flags/{flag.id}", headers=auth("aicte_officer"))
    entry = db.execute(
        select(AccessLog).where(AccessLog.action == "view_flag_detail")
    ).scalars().first()
    assert entry is not None
    assert entry.student_id == flag.student_id


# ------------------------------------------------------------------ case management


def test_officer_can_review_assign_and_note(client: TestClient, auth, dataset, db: Session) -> None:
    flag = db.execute(select(Flag).where(Flag.type == "EXCESS_INTAKE")).scalars().one()
    response = client.patch(
        f"/aicte/flags/{flag.id}",
        headers=auth("aicte_officer"),
        json={
            "status": "under_review",
            "assigned_to": "aicte_officer1",
            "note": "Called the data cell; awaiting their response.",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["flag"]["status"] == "under_review"
    assert body["flag"]["assigned_to"] == "aicte_officer1"
    assert body["flag"]["notes"][0]["note"].startswith("Called")
    assert body["audit_log_id"]

    detail = client.get(f"/aicte/flags/{flag.id}", headers=auth("aicte_officer")).json()
    assert detail["history"][0]["from"] == "open"
    assert detail["history"][0]["to"] == "under_review"
    assert detail["history"][0]["actor"] == "aicte_officer1"


def test_every_case_change_is_audited(client: TestClient, auth, dataset, db: Session) -> None:
    flag = db.execute(select(Flag).where(Flag.type == "EXCESS_INTAKE")).scalars().one()
    client.patch(
        f"/aicte/flags/{flag.id}",
        headers=auth("aicte_officer"),
        json={"status": "escalated", "reason": "Both institutions confirmed the enrolment."},
    )
    entry = db.execute(
        select(AuditLog).where(AuditLog.action == "flag_updated").order_by(AuditLog.id.desc())
    ).scalars().first()
    assert entry is not None
    assert entry.payload["changes"]["status"] == {"from": "open", "to": "escalated"}
    assert entry.payload["reason"].startswith("Both institutions")
    assert entry.hash and entry.prev_hash


def test_dismissing_a_flag_requires_a_reason(client: TestClient, auth, dataset, db: Session) -> None:
    flag = db.execute(select(Flag).where(Flag.type == "EXCESS_INTAKE")).scalars().one()
    refused = client.patch(
        f"/aicte/flags/{flag.id}", headers=auth("aicte_officer"), json={"status": "dismissed"}
    )
    assert refused.status_code == 400
    assert refused.json()["error"]["code"] == "REASON_REQUIRED"

    allowed = client.patch(
        f"/aicte/flags/{flag.id}",
        headers=auth("aicte_officer"),
        json={"status": "dismissed", "reason": "Verified against the admission register."},
    )
    assert allowed.status_code == 200


def test_an_unknown_status_is_rejected(client: TestClient, auth, dataset, db: Session) -> None:
    flag = db.execute(select(Flag).where(Flag.type == "EXCESS_INTAKE")).scalars().one()
    response = client.patch(
        f"/aicte/flags/{flag.id}", headers=auth("aicte_officer"), json={"status": "deleted"}
    )
    assert response.status_code == 422


# ------------------------------------------------------------------ reveal


def test_reveal_returns_raw_identifiers_and_logs_the_access(
    client: TestClient, auth, dataset, db: Session
) -> None:
    student = dataset["students"][dataset["first"].id]
    response = client.post(
        "/aicte/reveal",
        headers=auth("aicte_officer"),
        json={
            "student_id": student.id,
            "reason": "Verifying duplicate enrolment case with both institutions.",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["apaar_id"] == "111111110000"
    assert body["name"] == "Rahul Sharma"
    assert body["dob"] == "2006-03-12"
    assert body["enrolments"]
    assert body["notice"].startswith("This access has been logged")

    entry = db.get(AccessLog, body["access_log_id"])
    assert entry.action == "reveal_student_details"
    assert entry.role == "aicte_officer"
    assert entry.student_id == student.id
    assert entry.reason.startswith("Verifying duplicate")

    audit = db.execute(
        select(AuditLog).where(AuditLog.action == "reveal_student_details")
    ).scalars().one()
    assert audit.payload["access_log_id"] == entry.id


def test_reveal_never_returns_contact_details(client: TestClient, auth, dataset) -> None:
    """CLAUDE.md section 5 rule 1: contacts exist only as hashes, even on reveal."""
    student = dataset["students"][dataset["first"].id]
    body = client.post(
        "/aicte/reveal",
        headers=auth("aicte_officer"),
        json={"student_id": student.id, "reason": "Checking the duplicate enrolment case."},
    ).json()
    blob = json.dumps(body)
    assert "phone" not in blob
    assert "@" not in blob
    assert "hash" not in blob


def test_reveal_demands_a_real_reason(client: TestClient, auth, dataset) -> None:
    student = dataset["students"][dataset["first"].id]
    for reason in ("", "   ", "ok", "checking"):
        response = client.post(
            "/aicte/reveal",
            headers=auth("aicte_officer"),
            json={"student_id": student.id, "reason": reason} if reason else {"student_id": student.id, "reason": " "},
        )
        assert response.status_code == 400, reason
        assert response.json()["error"]["code"] == "REASON_REQUIRED"


def test_reveal_of_an_unknown_student_is_404(client: TestClient, auth, dataset) -> None:
    response = client.post(
        "/aicte/reveal",
        headers=auth("aicte_officer"),
        json={"student_id": 99999, "reason": "Checking a case file reference."},
    )
    assert response.status_code == 404


# ------------------------------------------------------------------ non-reporting


def test_non_reporting_lists_institutions_with_no_data(
    client: TestClient, auth, dataset, db: Session
) -> None:
    # A third institution that never reported.
    silent = Institution(
        aicte_permanent_id="1-7777777777",
        name="Tamravati College of Engineering",
        state="Kerala",
        region="South",
        type="private_unaided",
    )
    db.add(silent)
    db.commit()

    body = client.get(f"/aicte/non-reporting?academic_year={YEAR}", headers=auth("aicte_officer")).json()
    assert body["total"] == 1
    assert body["items"][0]["institution_id"] == silent.id
    assert body["items"][0]["reminders_sent"] == 0


def test_reminder_is_mocked_logged_and_officer_only(
    client: TestClient, auth, dataset, db: Session
) -> None:
    institution = dataset["first"]
    response = client.post(f"/aicte/remind/{institution.id}", headers=auth("aicte_officer"))
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "queued_mock"
    assert body["audit_log_id"]

    assert db.execute(select(ReminderLog)).scalars().one().institution_id == institution.id
    audit = db.execute(select(AuditLog).where(AuditLog.action == "reminder_sent")).scalars().one()
    assert audit.payload["mock"] is True


def test_reminder_for_an_unknown_institution_is_404(client: TestClient, auth, dataset) -> None:
    assert client.post("/aicte/remind/9999", headers=auth("aicte_officer")).status_code == 404


# ------------------------------------------------------------------ trends


def test_trends_by_dimension_with_year_on_year(client: TestClient, auth, dataset) -> None:
    body = client.get(
        f"/aicte/reports/trends?dimension=branch&academic_year={PREVIOUS}&academic_year={YEAR}",
        headers=auth("aicte_officer"),
    ).json()
    assert body["dimension"] == "branch"
    assert body["academic_years"] == [PREVIOUS, YEAR]
    series = body["series"][0]
    assert series["values"][PREVIOUS] == 2
    assert series["values"][YEAR] == 2
    assert series["yoy_growth_pct"] == 0.0
    assert body["csv_url"].startswith("/aicte/reports/trends.csv")


def test_trends_supports_every_documented_dimension(client: TestClient, auth, dataset) -> None:
    for dimension in ("state", "branch", "category", "gender", "year", "mode", "admission_type"):
        response = client.get(
            f"/aicte/reports/trends?dimension={dimension}", headers=auth("aicte_officer")
        )
        assert response.status_code == 200, dimension
        assert response.json()["dimension"] == dimension


def test_trends_csv_export(client: TestClient, auth, dataset) -> None:
    text = client.get(
        "/aicte/reports/trends.csv?dimension=category", headers=auth("aicte_officer")
    ).text
    assert text.splitlines()[0].startswith("category,")
    assert "yoy_growth_pct" in text.splitlines()[0]


def test_trends_are_suppressed_for_the_viewer(client: TestClient, auth, dataset) -> None:
    body = client.get("/aicte/reports/trends?dimension=branch", headers=auth("aicte_viewer")).json()
    assert body["series"][0]["values"][YEAR] == "<5"


def test_an_unknown_dimension_is_rejected(client: TestClient, auth, dataset) -> None:
    assert (
        client.get("/aicte/reports/trends?dimension=nonsense", headers=auth("aicte_officer")).status_code
        == 422
    )


def test_trends_can_compare_new_admissions_like_for_like(
    client: TestClient, auth, dataset
) -> None:
    """Total enrolment is not comparable while senior years are still filling up."""
    headers = auth("aicte_officer")
    total = client.get("/aicte/reports/trends?dimension=branch", headers=headers).json()
    assert total["new_admissions_only"] is False
    assert "senior years filling up" in " ".join(total["notes"])

    new_only = client.get(
        "/aicte/reports/trends?dimension=branch&new_admissions_only=true", headers=headers
    ).json()
    assert new_only["new_admissions_only"] is True
    assert "year-1 entrants plus lateral entrants" in " ".join(new_only["notes"])
    # The dataset's year-2 students are excluded from the new-admissions view.
    assert new_only["series"][0]["values"][YEAR] < total["series"][0]["values"][YEAR]


def test_non_reporting_says_how_long_until_the_deadline(
    client: TestClient, auth, dataset, db: Session
) -> None:
    silent = Institution(
        aicte_permanent_id="1-8888888888",
        name="Kaladgi Institute of Technology",
        state="Goa",
        region="West",
        type="private_unaided",
    )
    db.add(silent)
    db.commit()

    row = client.get(
        f"/aicte/non-reporting?academic_year={YEAR}", headers=auth("aicte_officer")
    ).json()["items"][0]
    assert row["days_overdue"] >= 0
    assert row["days_to_deadline"] is not None
    assert row["reporting_deadline"]
