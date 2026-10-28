"""Step 19: admin demo tooling."""
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import log_audit
from app.models.core import AuditLog

ADMIN_ROUTES = (
    ("GET", "/admin/status"),
    ("POST", "/admin/audit/tamper-test"),
)


def test_admin_routes_refuse_every_other_role(client: TestClient, auth, users) -> None:
    for method, path in ADMIN_ROUTES:
        for role in ("institution", "aicte_officer", "aicte_viewer", "student", "verifier"):
            response = client.request(method, path, headers=auth(role))
            assert response.status_code == 403, f"{method} {path} allowed {role}"


def test_audit_verify_is_open_to_admin_and_officer_only(client: TestClient, auth) -> None:
    for role in ("admin", "aicte_officer"):
        assert client.get("/admin/audit/verify", headers=auth(role)).status_code == 200
    for role in ("institution", "aicte_viewer", "student", "verifier"):
        assert client.get("/admin/audit/verify", headers=auth(role)).status_code == 403


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


