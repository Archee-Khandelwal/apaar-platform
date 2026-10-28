"""Demo user provisioning.

One account per role, plus one ``institution`` account per institution and the eight
demo student accounts listed in docs/PLAN.md (Step-0 decision 2). Demo passwords are
stored in plain text in ``users.demo_password`` **only** so the role switcher can show
them; the real credential is always the bcrypt hash in ``password_hash``.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.core import Institution, Student, User

DEMO_PASSWORD = "demo1234"


@dataclass(frozen=True)
class DemoAccount:
    username: str
    role: str
    display_name: str
    label: str
    institution_id: int | None = None
    student_id: int | None = None
    verifier_name: str | None = None
    verifier_type: str | None = None


BASE_ACCOUNTS: tuple[DemoAccount, ...] = (
    DemoAccount(
        username="aicte_officer1",
        role="aicte_officer",
        display_name="AICTE Officer — Monitoring Cell",
        label="AICTE Officer (flag details, reveal, case management)",
    ),
    DemoAccount(
        username="aicte_viewer1",
        role="aicte_viewer",
        display_name="AICTE Analyst — Statistics",
        label="AICTE Analyst (aggregates and masked rows only)",
    ),
    DemoAccount(
        username="admin",
        role="admin",
        display_name="Demo Operator",
        label="Demo operator (reseed, audit chain)",
    ),
    DemoAccount(
        username="verifier_demo",
        role="verifier",
        display_name="Nilgiri Softworks Pvt Ltd",
        label="Employer — Nilgiri Softworks (verification requests)",
        verifier_name="Nilgiri Softworks Pvt Ltd",
        verifier_type="employer",
    ),
)


def upsert_user(db: Session, account: DemoAccount, *, password: str = DEMO_PASSWORD) -> User:
    user = db.execute(select(User).where(User.username == account.username)).scalar_one_or_none()
    if user is None:
        user = User(username=account.username)
        db.add(user)
    user.password_hash = hash_password(password)
    user.role = account.role
    user.display_name = account.display_name
    user.demo_label = account.label
    user.demo_password = password
    user.institution_id = account.institution_id
    user.student_id = account.student_id
    user.verifier_name = account.verifier_name
    user.verifier_type = account.verifier_type
    user.is_active = True
    db.flush()
    return user


def ensure_base_demo_users(db: Session) -> list[User]:
    """Create the role accounts that do not depend on seeded data."""
    return [upsert_user(db, account) for account in BASE_ACCOUNTS]


def _slug(name: str, institution_id: int) -> str:
    """Login stem for an institution account.

    Deliberately the invented first word plus the institution id, not initials:
    initials of made-up names can collide with real institute acronyms, which
    CLAUDE.md section 5 rule 13 rules out.
    """
    first = next((word for word in name.replace("-", " ").split() if word), "inst")
    return f"{''.join(ch for ch in first.lower() if ch.isalnum())[:14]}{institution_id}"


def ensure_institution_users(db: Session) -> list[User]:
    """One ``institution`` account per institution: ``<initials>_admin``."""
    created: list[User] = []
    used: set[str] = {
        row for row in db.execute(select(User.username)).scalars()
    }
    for institution in db.execute(select(Institution).order_by(Institution.id)).scalars():
        existing = db.execute(
            select(User).where(User.role == "institution", User.institution_id == institution.id)
        ).scalar_one_or_none()
        if existing is not None:
            created.append(existing)
            continue
        base = f"{_slug(institution.name, institution.id)}_admin"
        username = base
        suffix = 2
        while username in used:
            username = f"{base}{suffix}"
            suffix += 1
        used.add(username)
        created.append(
            upsert_user(
                db,
                DemoAccount(
                    username=username,
                    role="institution",
                    display_name=f"{institution.name} — Data Cell",
                    label=f"{institution.name} ({institution.state})",
                    institution_id=institution.id,
                ),
            )
        )
    return created


def ensure_student_user(
    db: Session, *, student: Student, username: str, label: str, display_name: str
) -> User:
    return upsert_user(
        db,
        DemoAccount(
            username=username,
            role="student",
            display_name=display_name,
            label=label,
            student_id=student.id,
        ),
    )
