"""Step 3: login, RBAC, tenant isolation and small-count suppression."""
from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.errors import install_error_handlers
from app.core.security import (
    CurrentUser,
    assert_owned_by_institution,
    require_institution_scope,
    require_role,
    suppress_small_counts,
)
from app.models.core import Enrolment, Institution, Program, Student
from app.services.users import DEMO_PASSWORD


# ------------------------------------------------------------------ login


def test_login_returns_jwt_with_role_and_scope(client: TestClient, users: dict[str, str]) -> None:
    response = client.post("/auth/login", json={"username": "vit_admin", "password": DEMO_PASSWORD})
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] > 0
    assert body["user"]["role"] == "institution"
    assert body["user"]["institution_id"] is not None


def test_login_with_wrong_password_is_401(client: TestClient, users: dict[str, str]) -> None:
    response = client.post("/auth/login", json={"username": "vit_admin", "password": "nope"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "BAD_CREDENTIALS"


def test_login_with_unknown_user_is_401_with_the_same_code(client: TestClient, users) -> None:
    response = client.post("/auth/login", json={"username": "ghost", "password": DEMO_PASSWORD})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "BAD_CREDENTIALS"


def test_me_requires_a_token(client: TestClient, users) -> None:
    assert client.get("/auth/me").status_code == 401


def test_me_rejects_a_tampered_token(client: TestClient, auth) -> None:
    headers = auth("institution")
    headers["Authorization"] = headers["Authorization"][:-3] + "aaa"
    response = client.get("/auth/me", headers=headers)
    assert response.status_code == 401


def test_demo_users_lists_one_account_per_role(client: TestClient, users) -> None:
    body = client.get("/auth/demo-users").json()
    assert body["demo_mode"] is True
    roles = {entry["role"] for entry in body["users"]}
    assert {"institution", "aicte_viewer", "aicte_officer", "student", "verifier", "admin"} <= roles
    assert all(entry["password"] for entry in body["users"])


# ------------------------------------------------------------------ RBAC / tenant isolation


def _db_override(db: Session):
    """FastAPI needs a generator function, not a callable returning an iterator."""

    def _override():
        yield db

    return _override


def _scoped_app() -> FastAPI:
    """A miniature app exercising the shared dependencies exactly as routers use them."""
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/aicte-only")
    def aicte_only(user: CurrentUser = Depends(require_role("aicte_viewer", "aicte_officer"))):
        return {"role": user.role}

    @app.get("/officer-only")
    def officer_only(user: CurrentUser = Depends(require_role("aicte_officer"))):
        return {"role": user.role}

    @app.get("/my-students")
    def my_students(
        institution_id: int = Depends(require_institution_scope),
        db: Session = Depends(get_db),
    ):
        rows = (
            db.query(Enrolment).filter(Enrolment.institution_id == institution_id).all()
        )
        return {"institution_id": institution_id, "count": len(rows)}

    @app.get("/my-students/{row_institution_id}")
    def my_students_by_id(
        row_institution_id: int,
        institution_id: int = Depends(require_institution_scope),
        db: Session = Depends(get_db),
    ):
        """Deliberately accepts an id in the path to prove the guard rejects it."""
        assert_owned_by_institution(institution_id, row_institution_id)
        return {"institution_id": institution_id}

    return app


def test_wrong_role_gets_403(client: TestClient, auth, db: Session) -> None:
    scoped = _scoped_app()
    scoped.dependency_overrides[get_db] = _db_override(db)
    with TestClient(scoped) as scoped_client:
        response = scoped_client.get("/aicte-only", headers=auth("institution"))
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "FORBIDDEN_ROLE"
        assert response.json()["error"]["details"]["actual_role"] == "institution"


def test_viewer_cannot_use_an_officer_only_route(client: TestClient, auth, db: Session) -> None:
    scoped = _scoped_app()
    scoped.dependency_overrides[get_db] = _db_override(db)
    with TestClient(scoped) as scoped_client:
        assert scoped_client.get("/officer-only", headers=auth("aicte_viewer")).status_code == 403
        assert scoped_client.get("/officer-only", headers=auth("aicte_officer")).status_code == 200


def test_institution_scope_comes_from_the_jwt_not_the_request(
    client: TestClient, auth, db: Session, two_institutions
) -> None:
    first, second = two_institutions
    program = db.query(Program).filter(Program.institution_id == second.id).one()
    student = Student(apaar_masked="XXXX-XXXX-9999", name_masked="A**** K.")
    db.add(student)
    db.flush()
    db.add(
        Enrolment(
            student_id=student.id,
            program_id=program.id,
            institution_id=second.id,
            academic_year="2026-27",
        )
    )
    db.commit()

    scoped = _scoped_app()
    scoped.dependency_overrides[get_db] = _db_override(db)
    with TestClient(scoped) as scoped_client:
        # The first institution has no enrolments, the second has one.
        assert scoped_client.get("/my-students", headers=auth("institution")).json() == {
            "institution_id": first.id,
            "count": 0,
        }
        assert scoped_client.get("/my-students", headers=auth("institution_other")).json() == {
            "institution_id": second.id,
            "count": 1,
        }


def test_institution_cannot_reach_another_institution_by_passing_its_id(
    client: TestClient, auth, db: Session, two_institutions
) -> None:
    first, second = two_institutions
    scoped = _scoped_app()
    scoped.dependency_overrides[get_db] = _db_override(db)
    with TestClient(scoped) as scoped_client:
        own = scoped_client.get(f"/my-students/{first.id}", headers=auth("institution"))
        other = scoped_client.get(f"/my-students/{second.id}", headers=auth("institution"))
    assert own.status_code == 200
    # 404, not 403: we do not confirm that the other institution's row exists.
    assert other.status_code == 404
    assert other.json()["error"]["code"] == "NOT_FOUND"


# ------------------------------------------------------------------ suppression


def test_suppression_hides_counts_below_five_for_viewers() -> None:
    data = {"state": "Goa", "institutions": 2, "students_reported": 318, "open_flags": 4}
    suppressed = suppress_small_counts(data, "aicte_viewer")
    assert suppressed["institutions"] == "<5"
    assert suppressed["open_flags"] == "<5"
    assert suppressed["students_reported"] == 318
    assert suppressed["state"] == "Goa"


def test_suppression_does_not_apply_to_officers() -> None:
    data = {"open_flags": 4}
    assert suppress_small_counts(data, "aicte_officer") == {"open_flags": 4}
    assert suppress_small_counts(data, "admin") == {"open_flags": 4}


def test_suppression_is_recursive_and_keeps_identifiers_and_totals() -> None:
    data = {
        "total": 3,
        "page": 1,
        "by_state": [{"state": "Goa", "institutions": 2, "institution_id": 4}],
        "nested": {"counts": {"high": 1, "low": 9}},
    }
    out = suppress_small_counts(data, "aicte_viewer")
    assert out["total"] == 3  # totals are not cell counts
    assert out["page"] == 1
    assert out["by_state"][0]["institutions"] == "<5"
    assert out["by_state"][0]["institution_id"] == 4  # an id, not a count
    assert out["nested"]["counts"] == {"high": "<5", "low": 9}


def test_suppression_leaves_zero_and_booleans_alone() -> None:
    out = suppress_small_counts({"excess": 0, "eligible": True}, "aicte_viewer")
    assert out["excess"] == 0
    assert out["eligible"] is True
