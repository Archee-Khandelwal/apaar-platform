"""Step 19: admin demo tooling."""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import log_audit
from app.models.core import AuditLog, Enrolment, Flag, Institution, Program, Student

ADMIN_ROUTES = (
    ("GET", "/admin/scenarios"),
    ("GET", "/admin/status"),
    ("GET", "/admin/audit/verify"),
    ("POST", "/admin/audit/tamper-test"),
    ("POST", "/admin/run-detectors"),
)


def test_admin_routes_refuse_every_other_role(client: TestClient, auth, users) -> None:
    for method, path in ADMIN_ROUTES:
        for role in ("institution", "aicte_officer", "aicte_viewer", "student", "verifier"):
            response = client.request(method, path, headers=auth(role))
            assert response.status_code == 403, f"{method} {path} allowed {role}"


def test_admin_has_no_student_data_route(client: TestClient, auth, users) -> None:
    """admin is a demo operator, not a superuser (Step-0 decision 3)."""
    headers = auth("admin")
    for path in ("/aicte/flags", "/aicte/overview", "/institution/students", "/student/me"):
        assert client.get(path, headers=headers).status_code == 403


def test_status_reports_counts_and_audit_health(
    client: TestClient, auth, users, db: Session
) -> None:
    log_audit(db, actor="admin", role="admin", action="test_event", target="x")
    db.commit()

    body = client.get("/admin/status", headers=auth("admin")).json()
    assert body["counts"]["institutions"] == 2
    assert body["audit"]["ok"] is True
    assert body["audit"]["rows_total"] >= 1
    assert body["demo_mode"] is True


def test_scenarios_are_listed_with_their_flag_types(client: TestClient, auth, users) -> None:
    body = client.get("/admin/scenarios", headers=auth("admin")).json()
    names = {item["name"] for item in body["scenarios"]}
    assert "B_ghost_cluster" in names
    assert "D_dual_degree" in names
    for item in body["scenarios"]:
        assert item["label"]
        assert item["flag_types"]


def test_audit_verify_passes_on_an_untouched_chain(
    client: TestClient, auth, users, db: Session
) -> None:
    for index in range(3):
        log_audit(db, actor="admin", role="admin", action=f"event_{index}", target="x")
    db.commit()

    body = client.get("/admin/audit/verify", headers=auth("admin")).json()
    assert body["ok"] is True
    assert body["first_broken_row"] is None
    assert body["checked_at"]


def test_audit_verify_catches_a_real_tampering(
    client: TestClient, auth, users, db: Session
) -> None:
    for index in range(3):
        log_audit(db, actor="admin", role="admin", action=f"event_{index}", target="x")
    db.commit()

    rows = db.execute(select(AuditLog).order_by(AuditLog.id)).scalars().all()
    rows[1].payload = {"tampered": True}
    db.commit()

    body = client.get("/admin/audit/verify", headers=auth("admin")).json()
    assert body["ok"] is False
    assert body["first_broken_row"]["id"] == rows[1].id


def test_tamper_test_detects_an_edit_without_touching_the_real_log(
    client: TestClient, auth, users, db: Session
) -> None:
    for index in range(6):
        log_audit(db, actor="admin", role="admin", action=f"event_{index}", target="x")
    db.commit()
    before = [
        (row.id, row.hash, row.prev_hash)
        for row in db.execute(select(AuditLog).order_by(AuditLog.id)).scalars()
    ]

    body = client.post("/admin/audit/tamper-test", headers=auth("admin")).json()
    assert body["detected"] is True
    assert body["tampered_row_id"]
    assert body["first_broken_row_id"] == body["tampered_row_id"]
    assert "was not modified" in body["message"]

    # The real chain is still intact, and still verifies.
    after = [
        (row.id, row.hash, row.prev_hash)
        for row in db.execute(select(AuditLog).order_by(AuditLog.id)).scalars()
    ]
    assert after[: len(before)] == before
    assert client.get("/admin/audit/verify", headers=auth("admin")).json()["ok"] is True


def test_the_tamper_test_is_itself_audited(client: TestClient, auth, users, db: Session) -> None:
    for index in range(4):
        log_audit(db, actor="admin", role="admin", action=f"event_{index}", target="x")
    db.commit()
    client.post("/admin/audit/tamper-test", headers=auth("admin"))

    entry = db.execute(
        select(AuditLog).where(AuditLog.action == "audit_tamper_test")
    ).scalars().one()
    assert entry.payload["detected"] is True


def test_rerunning_detectors_is_idempotent(client: TestClient, auth, users, db: Session) -> None:
    headers = auth("admin")
    first = client.post("/admin/run-detectors", headers=headers).json()
    assert first["status"] == "ok"
    before = db.scalar(select(Flag.id).order_by(Flag.id.desc()))
    second = client.post("/admin/run-detectors", headers=headers).json()
    assert second["status"] == "ok"
    assert db.scalar(select(Flag.id).order_by(Flag.id.desc())) == before


def test_an_unknown_scenario_is_404(client: TestClient, auth, users) -> None:
    response = client.post("/admin/load-scenario/Z_not_real", headers=auth("admin"))
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_loading_a_scenario_injects_it_live(
    client: TestClient, auth, users, db: Session, two_institutions
) -> None:
    """A live injection must add rows and raise the scenario's flag type."""
    from app.models.core import ApprovedIntake, Upload
    from app.services.rules import supernumerary_caps

    # The injection needs programmes with intake, an upload to attach to, and a cohort.
    first, second = two_institutions
    for institution in (first, second):
        program = db.execute(
            select(Program).where(Program.institution_id == institution.id)
        ).scalars().first()
        db.add(
            ApprovedIntake(
                program_id=program.id,
                academic_year="2026-27",
                intake=120,
                supernumerary_caps=supernumerary_caps(120),
            )
        )
        db.add(
            Upload(
                institution_id=institution.id,
                filename="seed.xlsx",
                state="completed",
                academic_year="2026-27",
            )
        )
        for index in range(20):
            student = Student(apaar_masked=f"XXXX-XXXX-{index:04d}", name_masked="S**** T.")
            db.add(student)
            db.flush()
            db.add(
                Enrolment(
                    student_id=student.id,
                    program_id=program.id,
                    institution_id=institution.id,
                    academic_year="2026-27",
                    year_of_study=1,
                    admission_type="regular",
                    status="admitted",
                    admitted_on=date(2026, 8, 1),
                )
            )
    db.commit()

    students_before = db.scalar(select(Student.id).order_by(Student.id.desc()))
    response = client.post("/admin/load-scenario/B_ghost_cluster", headers=auth("admin"))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "injected"
    assert body["added"]["students"] > 0
    assert body["added"]["enrolments"] > 0

    # New students really landed, and the cluster detector saw them.
    assert db.scalar(select(Student.id).order_by(Student.id.desc())) > students_before
    assert body["flags_after"]["GHOST_CLUSTER"] > body["flags_before"]["GHOST_CLUSTER"]

    entry = db.execute(
        select(AuditLog).where(AuditLog.action == "load_scenario")
    ).scalars().one()
    assert entry.payload["added"]["students"] > 0
