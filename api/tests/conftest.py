"""Shared pytest fixtures.

Every test run gets its own throwaway SQLite database and fixed test secrets, so tests
never touch the demo database and never depend on a developer's .env.
"""
from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

# Must be set before app.core.config is imported anywhere.
_TMP = Path(tempfile.mkdtemp(prefix="apaar_tests_"))
os.environ["HMAC_KEY"] = "0" * 64
os.environ["VAULT_KEY"] = "YkxZSk1nQ2pQTnBXUXJTdFV2V3hZekFCQ0RFRkdISUo="
os.environ["JWT_SECRET"] = "test-jwt-secret-not-for-production"
os.environ["REGISTRY_API_KEY"] = "test-registry-key"
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP / 'apaar_test.db'}"
os.environ["REGISTRY_DATABASE_URL"] = f"sqlite:///{_TMP / 'registry_test.db'}"
os.environ["DEMO_MODE"] = "true"
os.environ["CURRENT_ACADEMIC_YEAR"] = "2026-27"
os.environ["BCRYPT_ROUNDS"] = "4"  # bcrypt at 12 rounds makes the suite needlessly slow

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from app.core.db import Base, get_db  # noqa: E402
from app.main import app as fastapi_app  # noqa: E402
from app.models.core import Institution, Program, Student  # noqa: E402
from app.core.ratelimit import login_throttle  # noqa: E402
from app.services.users import BASE_ACCOUNTS, DemoAccount, upsert_user  # noqa: E402

# Every test account shares this password; seeded demo accounts each get a random one.
TEST_PASSWORD = "Test-Pass-2026"


@pytest.fixture(autouse=True)
def _fresh_login_throttle() -> Iterator[None]:
    """Failed logins in one test must not throttle the next."""
    login_throttle.reset()
    yield
    login_throttle.reset()


@pytest.fixture()
def db() -> Iterator[Session]:
    """A fresh in-memory database per test, shared by the TestClient below."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=__import__("sqlalchemy.pool", fromlist=["StaticPool"]).StaticPool,
    )
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = maker()
    session.info["maker"] = maker
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def client(db: Session) -> Iterator[TestClient]:
    """TestClient wired to the test database (startup's create_all is harmless)."""

    def override_get_db() -> Iterator[Session]:
        yield db

    fastapi_app.dependency_overrides[get_db] = override_get_db
    with TestClient(fastapi_app) as test_client:
        yield test_client
    fastapi_app.dependency_overrides.pop(get_db, None)


@pytest.fixture()
def two_institutions(db: Session) -> tuple[Institution, Institution]:
    """Two fictional institutions, each with one regular B.Tech CSE programme."""
    first = Institution(
        aicte_permanent_id="1-4432219876",
        name="Vindhyashree Institute of Technology",
        state="Madhya Pradesh",
        region="Central",
        type="private_unaided",
    )
    second = Institution(
        aicte_permanent_id="1-5521130099",
        name="Kharapur Technical Institute",
        state="Odisha",
        region="East",
        type="private_unaided",
    )
    db.add_all([first, second])
    db.flush()
    for institution in (first, second):
        db.add(
            Program(
                institution_id=institution.id,
                course="B.Tech",
                branch="Computer Science and Engineering",
                level="UG",
                mode="regular",
            )
        )
    db.flush()
    db.commit()
    return first, second


@pytest.fixture()
def users(db: Session, two_institutions: tuple[Institution, Institution]) -> dict[str, str]:
    """Create one account per role (two institution accounts) and return username per role."""
    first, second = two_institutions
    for account in BASE_ACCOUNTS:
        upsert_user(db, account, password=TEST_PASSWORD)

    student = Student(apaar_masked="XXXX-XXXX-1234", name_masked="R**** S.", dob_year=2006)
    db.add(student)
    db.flush()

    upsert_user(
        db,
        DemoAccount(
            username="vit_admin",
            role="institution",
            display_name=f"{first.name} — Data Cell",
            label=first.name,
            institution_id=first.id,
        ),
        password=TEST_PASSWORD,
    )
    upsert_user(
        db,
        DemoAccount(
            username="kti_admin",
            role="institution",
            display_name=f"{second.name} — Data Cell",
            label=second.name,
            institution_id=second.id,
        ),
        password=TEST_PASSWORD,
    )
    upsert_user(
        db,
        DemoAccount(
            username="student_demo1",
            role="student",
            display_name="Demo Student",
            label="Student",
            student_id=student.id,
        ),
        password=TEST_PASSWORD,
    )
    db.commit()
    return {
        "institution": "vit_admin",
        "institution_other": "kti_admin",
        "aicte_viewer": "aicte_viewer1",
        "aicte_officer": "aicte_officer1",
        "student": "student_demo1",
        "verifier": "verifier_demo",
        "admin": "admin",
    }


@pytest.fixture()
def auth(client: TestClient, users: dict[str, str]):
    """``auth("institution")`` -> Authorization header dict for that role."""

    def _auth(role_or_username: str) -> dict[str, str]:
        username = users.get(role_or_username, role_or_username)
        response = client.post(
            "/auth/login", json={"username": username, "password": TEST_PASSWORD}
        )
        assert response.status_code == 200, response.text
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    return _auth
