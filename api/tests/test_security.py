"""Phase 3 security: credentials, login throttling, password change and reset, and the
full route x role RBAC matrix.

The matrix is an explicit specification. A route added to the app without an entry here
fails ``test_the_matrix_covers_every_route``, so nobody can ship an endpoint whose access
rule has not been written down and tested.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.main import app
from app.models.core import AuditLog, Institution, User
from app.services.users import (
    ensure_institution_users,
    generate_password,
    password_problems,
    write_credentials,
)
from tests.conftest import TEST_PASSWORD

REPO = Path(__file__).resolve().parents[2]
ROLES = ("institution", "aicte_viewer", "aicte_officer", "student", "verifier", "admin")
PUBLIC = "public"
ANY = "any signed-in role"

# (method, path) -> roles allowed. Path parameters are filled with harmless dummies.
ROUTE_ROLES: dict[tuple[str, str], object] = {
    ("GET", "/health"): PUBLIC,
    ("POST", "/auth/login"): PUBLIC,
    ("GET", "/auth/demo-users"): PUBLIC,
    ("GET", "/verify/token/{token}"): PUBLIC,
    ("GET", "/verify/document/{token}"): PUBLIC,
    ("GET", "/auth/me"): ANY,
    ("POST", "/auth/change-password"): ANY,
    ("GET", "/institution/me"): {"institution"},
    ("GET", "/institution/template"): {"institution"},
    ("POST", "/institution/uploads"): {"institution"},
    ("POST", "/institution/uploads/{upload_id}/confirm-mapping"): {"institution"},
    ("GET", "/institution/uploads"): {"institution"},
    ("GET", "/institution/uploads/{upload_id}"): {"institution"},
    ("GET", "/institution/uploads/{upload_id}/errors.csv"): {"institution"},
    ("GET", "/institution/seat-matrix"): {"institution"},
    ("GET", "/institution/flags"): {"institution"},
    ("PATCH", "/institution/flags/{flag_id}"): {"institution"},
    ("GET", "/institution/students"): {"institution"},
    ("PATCH", "/institution/enrolments/{enrolment_id}/status"): {"institution"},
    ("GET", "/institution/degree-certificates"): {"institution"},
    ("POST", "/institution/degree-certificates"): {"institution"},
    ("GET", "/institution/degree-certificates/{serial}"): {"institution"},
    ("POST", "/institution/degree-certificates/{serial}/revoke"): {"institution"},
    ("GET", "/institution/dashboard"): {"institution"},
    ("GET", "/institution/documents/rules"): {"institution"},
    ("GET", "/institution/documents"): {"institution"},
    ("GET", "/institution/students/{student_id}/documents"): {"institution"},
    ("POST", "/institution/students/{student_id}/documents"): {"institution"},
    ("POST", "/institution/documents/bulk"): {"institution"},
    ("GET", "/institution/documents/{document_id}/file"): {"institution"},
    ("POST", "/aicte/documents/{document_id}/file"): {"aicte_officer"},
    ("GET", "/aicte/documents/review"): {"aicte_officer"},
    ("POST", "/aicte/documents/{document_id}/case"): {"aicte_officer"},
    ("POST", "/aicte/documents/{document_id}/decision"): {"aicte_officer"},
    ("POST", "/aicte/documents/{document_id}/recheck"): {"aicte_officer"},
    ("GET", "/student/documents"): {"student"},
    ("GET", "/student/documents/{document_id}/file"): {"student"},
    ("GET", "/aicte/overview"): {"aicte_viewer", "aicte_officer"},
    ("GET", "/aicte/institutions"): {"aicte_viewer", "aicte_officer"},
    ("GET", "/aicte/institutions/{institution_id}"): {"aicte_viewer", "aicte_officer"},
    ("GET", "/aicte/institutions/{institution_id}/seat-matrix"): {"aicte_viewer", "aicte_officer"},
    ("GET", "/aicte/flags"): {"aicte_viewer", "aicte_officer"},
    ("GET", "/aicte/flags/{flag_id}"): {"aicte_viewer", "aicte_officer"},
    ("PATCH", "/aicte/flags/{flag_id}"): {"aicte_officer"},
    ("POST", "/aicte/reveal"): {"aicte_officer"},
    ("GET", "/aicte/reports/trends"): {"aicte_viewer", "aicte_officer"},
    ("GET", "/aicte/reports/trends.csv"): {"aicte_viewer", "aicte_officer"},
    ("GET", "/aicte/reconciliation/summary"): {"aicte_viewer", "aicte_officer"},
    ("GET", "/aicte/reconciliation/records"): {"aicte_viewer", "aicte_officer"},
    ("GET", "/aicte/reconciliation/records.csv"): {"aicte_viewer", "aicte_officer"},
    ("GET", "/aicte/reconciliation/records/{enrolment_id}"): {"aicte_viewer", "aicte_officer"},
    ("GET", "/aicte/master"): {"aicte_officer", "admin"},
    ("POST", "/aicte/master/import"): {"aicte_officer", "admin"},
    ("GET", "/aicte/master/template/{kind}"): {"aicte_officer", "admin"},
    ("GET", "/institution/reconciliation"): {"institution"},
    ("GET", "/student/me"): {"student"},
    ("POST", "/student/corrections"): {"student"},
    ("GET", "/student/corrections"): {"student"},
    ("GET", "/student/access-log"): {"student"},
    ("GET", "/student/consents"): {"student"},
    ("POST", "/student/consents/{consent_id}/approve"): {"student"},
    ("POST", "/student/consents/{consent_id}/deny"): {"student"},
    ("POST", "/student/consents/{consent_id}/revoke"): {"student"},
    ("GET", "/student/id-card"): {"student"},
    ("GET", "/verifier/purposes"): {"verifier", "institution"},
    ("POST", "/verifier/requests"): {"verifier", "institution"},
    ("GET", "/verifier/requests"): {"verifier", "institution"},
    ("GET", "/verifier/requests/{request_id}"): {"verifier", "institution"},
    ("GET", "/admin/status"): {"admin"},
    ("POST", "/admin/reseed"): {"admin"},
    ("GET", "/admin/audit/verify"): {"admin", "aicte_officer"},
    ("POST", "/admin/audit/tamper-test"): {"admin"},
    ("GET", "/admin/users"): {"admin"},
    ("POST", "/admin/users/{user_id}/reset-password"): {"admin"},
}

# Allowed-role calls that would do something heavy or destructive to the test database.
SKIP_ALLOWED_CALL = {("POST", "/admin/reseed")}

FRAMEWORK_PATHS = {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}


def _concrete(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "999999", path)


def _app_routes() -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for route in app.routes:
        path = getattr(route, "path", "")
        if path in FRAMEWORK_PATHS or not hasattr(route, "dependant"):
            continue
        for method in route.methods - {"HEAD", "OPTIONS"}:
            found.add((method, path))
    return found


# ------------------------------------------------------------------ RBAC matrix


def test_the_matrix_covers_every_route() -> None:
    routes = _app_routes()
    missing = sorted(routes - set(ROUTE_ROLES))
    stale = sorted(set(ROUTE_ROLES) - routes)
    assert not missing, f"routes with no access rule in the RBAC matrix: {missing}"
    assert not stale, f"matrix entries for routes that no longer exist: {stale}"


def test_every_protected_route_refuses_a_missing_token(client: TestClient, users) -> None:
    for (method, path), allowed in ROUTE_ROLES.items():
        if allowed == PUBLIC:
            continue
        response = client.request(method, _concrete(path))
        assert response.status_code == 401, f"{method} {path} without a token -> {response.status_code}"


def test_every_route_refuses_every_role_it_does_not_allow(client: TestClient, auth) -> None:
    headers = {role: auth(role) for role in ROLES}
    checked = 0
    for (method, path), allowed in ROUTE_ROLES.items():
        if allowed in (PUBLIC, ANY):
            continue
        for role in ROLES:
            if role in allowed:  # type: ignore[operator]
                continue
            response = client.request(method, _concrete(path), headers=headers[role])
            assert response.status_code == 403, f"{method} {path} let {role} through ({response.status_code})"
            assert response.json()["error"]["code"] == "FORBIDDEN_ROLE"
            checked += 1
    assert checked > 200


def test_every_route_admits_the_roles_it_allows(client: TestClient, auth) -> None:
    """An allowed role may get 404 or 422 for dummy ids, but never 401 or 403."""
    headers = {role: auth(role) for role in ROLES}
    for (method, path), allowed in ROUTE_ROLES.items():
        if allowed == PUBLIC or (method, path) in SKIP_ALLOWED_CALL:
            continue
        roles = ROLES if allowed == ANY else sorted(allowed)  # type: ignore[arg-type]
        for role in roles:
            response = client.request(method, _concrete(path), headers=headers[role])
            assert response.status_code not in (401, 403), (
                f"{method} {path} refused allowed role {role}: {response.status_code} {response.text[:200]}"
            )


# ------------------------------------------------------------------ credentials


def test_each_institution_gets_its_own_random_password(db: Session, two_institutions) -> None:
    credentials = ensure_institution_users(db)
    db.commit()
    assert len(credentials) == 2
    assert credentials[0].password != credentials[1].password
    for credential in credentials:
        user = db.execute(select(User).where(User.username == credential.username)).scalar_one()
        assert user.password_hash.startswith("$2b$"), "passwords must be bcrypt hashes"
        assert credential.password not in user.password_hash
        # Nothing on the row holds the plain password.
        for column in User.__table__.columns:
            assert getattr(user, column.name) != credential.password


def test_generated_passwords_are_unique_and_meet_the_policy() -> None:
    passwords = {generate_password() for _ in range(200)}
    assert len(passwords) == 200
    for password in list(passwords)[:20]:
        assert password_problems(password, username="someone") == []


def test_credentials_are_written_only_to_a_gitignored_file(tmp_path: Path, db, two_institutions) -> None:
    credentials = ensure_institution_users(db)
    path = write_credentials(credentials, tmp_path / "demo_credentials.csv")
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    assert {row["username"] for row in rows} == {c.username for c in credentials}
    ignored = (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "demo_credentials.csv" in ignored
    assert "*_credentials.csv" in ignored


def test_no_route_or_schema_hands_out_a_password(client: TestClient, users) -> None:
    body = client.get("/auth/demo-users").json()
    assert body["users"]
    assert all(set(entry) == {"username", "role", "label"} for entry in body["users"])
    assert "demo_password" not in {column.name for column in User.__table__.columns}


# ------------------------------------------------------------------ login throttling


def _login(client: TestClient, username: str, password: str):
    return client.post("/auth/login", json={"username": username, "password": password})


def test_repeated_failures_lock_the_account_for_a_while(client: TestClient, users) -> None:
    for _ in range(settings.login_max_failures_per_account):
        assert _login(client, "vit_admin", "wrong-password").status_code == 401
    locked = _login(client, "vit_admin", TEST_PASSWORD)  # even the right password waits
    assert locked.status_code == 429
    assert locked.json()["error"]["code"] == "TOO_MANY_ATTEMPTS"
    assert locked.json()["error"]["details"]["retry_after_seconds"] > 0
    # Another account is not affected.
    assert _login(client, "kti_admin", TEST_PASSWORD).status_code == 200


def test_a_successful_login_clears_the_failure_count(client: TestClient, users) -> None:
    for _ in range(settings.login_max_failures_per_account - 1):
        _login(client, "vit_admin", "wrong-password")
    assert _login(client, "vit_admin", TEST_PASSWORD).status_code == 200
    for _ in range(settings.login_max_failures_per_account - 1):
        _login(client, "vit_admin", "wrong-password")
    assert _login(client, "vit_admin", TEST_PASSWORD).status_code == 200


def test_one_client_guessing_many_accounts_is_throttled(client: TestClient, users) -> None:
    for index in range(settings.login_max_failures_per_client):
        _login(client, f"no_such_user_{index}", "x")
    assert _login(client, "kti_admin", TEST_PASSWORD).status_code == 429


def test_logins_and_failures_are_in_the_audit_chain(client: TestClient, users, db: Session) -> None:
    _login(client, "vit_admin", "wrong-password")
    _login(client, "vit_admin", TEST_PASSWORD)
    actions = [row.action for row in db.execute(select(AuditLog).order_by(AuditLog.id)).scalars()]
    assert "login_failed" in actions and "login" in actions
    for row in db.execute(select(AuditLog)).scalars():
        assert "wrong-password" not in str(row.payload)


# ------------------------------------------------------------------ password change


def test_changing_a_password_ends_every_other_session(client: TestClient, auth, db: Session) -> None:
    old = auth("institution")
    response = client.post(
        "/auth/change-password",
        headers=old,
        json={"current_password": TEST_PASSWORD, "new_password": "Brand-New-Pass-77"},
    )
    assert response.status_code == 200, response.text
    fresh = {"Authorization": f"Bearer {response.json()['access_token']}"}

    stale = client.get("/institution/me", headers=old)
    assert stale.status_code == 401
    assert stale.json()["error"]["code"] == "TOKEN_REVOKED"
    assert client.get("/institution/me", headers=fresh).status_code == 200
    assert _login(client, "vit_admin", TEST_PASSWORD).status_code == 401
    assert _login(client, "vit_admin", "Brand-New-Pass-77").status_code == 200
    assert db.execute(select(AuditLog).where(AuditLog.action == "password_changed")).scalars().first()


def test_a_password_change_needs_the_current_password(client: TestClient, auth) -> None:
    response = client.post(
        "/auth/change-password",
        headers=auth("institution"),
        json={"current_password": "not-it", "new_password": "Brand-New-Pass-77"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "BAD_CREDENTIALS"


@pytest.mark.parametrize("weak", ["short1A", "alllowercaseletters", "vit_admin-Pass-99"])
def test_weak_passwords_are_refused(client: TestClient, auth, weak: str) -> None:
    response = client.post(
        "/auth/change-password",
        headers=auth("institution"),
        json={"current_password": TEST_PASSWORD, "new_password": weak},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "WEAK_PASSWORD"


# ------------------------------------------------------------------ admin reset


def test_admin_reset_issues_a_one_time_password(client: TestClient, auth, db: Session) -> None:
    target_headers = auth("institution")
    target = db.execute(select(User).where(User.username == "vit_admin")).scalar_one()

    response = client.post(f"/admin/users/{target.id}/reset-password", headers=auth("admin"))
    assert response.status_code == 200
    body = response.json()
    temporary = body["temporary_password"]
    assert body["must_change_password"] is True

    # The old session is gone, and the old password no longer works.
    assert client.get("/institution/me", headers=target_headers).status_code == 401
    assert _login(client, "vit_admin", TEST_PASSWORD).status_code == 401

    # The temporary password only unlocks the change form.
    login = _login(client, "vit_admin", temporary).json()
    assert login["user"]["must_change_password"] is True
    temp_headers = {"Authorization": f"Bearer {login['access_token']}"}
    blocked = client.get("/institution/me", headers=temp_headers)
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "PASSWORD_CHANGE_REQUIRED"

    changed = client.post(
        "/auth/change-password",
        headers=temp_headers,
        json={"current_password": temporary, "new_password": "Chosen-By-Me-42"},
    )
    assert changed.status_code == 200
    final = {"Authorization": f"Bearer {changed.json()['access_token']}"}
    assert client.get("/institution/me", headers=final).status_code == 200

    entry = db.execute(select(AuditLog).where(AuditLog.action == "password_reset")).scalars().one()
    assert temporary not in str(entry.payload)


def test_the_admin_account_list_carries_no_student_details(
    client: TestClient, auth, db: Session
) -> None:
    body = client.get("/admin/users?role=student", headers=auth("admin")).json()
    assert body["total"] == 1
    row = body["items"][0]
    assert row["display_name"] == "Student account"
    assert "XXXX" not in str(row)


def test_an_unknown_account_cannot_be_reset(client: TestClient, auth) -> None:
    assert client.post("/admin/users/99999/reset-password", headers=auth("admin")).status_code == 404


def test_institution_accounts_cannot_be_created_for_unknown_institutions(db: Session) -> None:
    """ensure_institution_users is driven by the institutions table, nothing else."""
    assert ensure_institution_users(db) == []
    db.add(Institution(aicte_permanent_id="1-1", name="Tamravati College of Engineering",
                       state="Kerala", region="South", type="private_unaided"))
    db.commit()
    assert len(ensure_institution_users(db)) == 1


# ------------------------------------------------------------------ audit coverage


def test_security_relevant_events_land_in_a_valid_audit_chain(
    client: TestClient, auth, db: Session
) -> None:
    from app.core.audit import verify_chain
    from app.models.core import Student

    institution = auth("institution")
    client.post(
        "/institution/uploads", headers=institution,
        files={"file": ("s.csv", b"APAAR ID,Student Name\n123412341234,Asha Rao\n", "text/csv")},
        data={"academic_year": "2026-27"},
    )
    student = db.execute(select(Student)).scalars().first()
    client.post("/aicte/reveal", headers=auth("aicte_officer"),
                json={"student_id": student.id, "reason": "Checking a reported duplicate."})
    _login(client, "vit_admin", "wrong-password")

    actions = {row.action for row in db.execute(select(AuditLog)).scalars()}
    assert {"login", "login_failed", "upload_created", "reveal_student_details"} <= actions
    assert verify_chain(db).ok is True
