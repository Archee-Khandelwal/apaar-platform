"""User provisioning, password policy and the demo credentials file.

One account per role, plus one ``institution`` account per institution and the demo
student accounts. Every account gets its **own random password**; only its bcrypt hash
is stored. The plain passwords are written once, at seed time, to the gitignored
``demo_credentials.csv`` so the demo operator can sign in — they never reach the
database or the API.
"""
from __future__ import annotations

import csv
import secrets
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import REPO_ROOT
from app.core.security import hash_password
from app.models.core import Institution, Student, User

CREDENTIALS_PATH = REPO_ROOT / "demo_credentials.csv"
# No 0/O, 1/l/I: these passwords are read off a sheet and typed in during a demo.
_PASSWORD_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
MIN_PASSWORD_LENGTH = 10


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


@dataclass(frozen=True)
class Credential:
    """A freshly issued password, kept only long enough to write the credentials file."""

    username: str
    role: str
    password: str
    label: str


def generate_password() -> str:
    """Three groups of four from a 56-symbol alphabet: about 69 bits of entropy."""
    groups = ("".join(secrets.choice(_PASSWORD_ALPHABET) for _ in range(4)) for _ in range(3))
    return "-".join(groups)


def password_problems(password: str, *, username: str) -> list[str]:
    """Plain-English reasons a new password is refused; empty when it is acceptable."""
    problems: list[str] = []
    if len(password) < MIN_PASSWORD_LENGTH:
        problems.append(f"Use at least {MIN_PASSWORD_LENGTH} characters.")
    if username and username.lower() in password.lower():
        problems.append("Do not include your username.")
    kinds = sum(
        (
            any(ch.islower() for ch in password),
            any(ch.isupper() for ch in password),
            any(ch.isdigit() for ch in password),
            any(not ch.isalnum() for ch in password),
        )
    )
    if kinds < 3:
        problems.append("Mix at least three of: lower case, upper case, digits, symbols.")
    return problems


def set_password(user: User, password: str, *, must_change: bool = False) -> None:
    """Store the bcrypt hash and end every session issued under the old password."""
    user.password_hash = hash_password(password)
    user.token_version = (user.token_version or 1) + 1
    user.must_change_password = must_change
    user.password_changed_at = datetime.utcnow()


def upsert_user(db: Session, account: DemoAccount, *, password: str) -> User:
    user = db.execute(select(User).where(User.username == account.username)).scalar_one_or_none()
    if user is None:
        user = User(username=account.username, token_version=1)
        db.add(user)
    set_password(user, password)
    user.role = account.role
    user.display_name = account.display_name
    user.demo_label = account.label
    user.institution_id = account.institution_id
    user.student_id = account.student_id
    user.verifier_name = account.verifier_name
    user.verifier_type = account.verifier_type
    user.is_active = True
    db.flush()
    return user


def _issue(db: Session, account: DemoAccount) -> Credential:
    password = generate_password()
    upsert_user(db, account, password=password)
    return Credential(account.username, account.role, password, account.label)


def ensure_base_demo_users(db: Session) -> list[Credential]:
    """Create the role accounts that do not depend on seeded data."""
    return [_issue(db, account) for account in BASE_ACCOUNTS]


def _slug(name: str, institution_id: int) -> str:
    """Login stem for an institution account.

    Deliberately the invented first word plus the institution id, not initials:
    initials of made-up names can collide with real institute acronyms, which
    CLAUDE.md section 5 rule 13 rules out.
    """
    first = next((word for word in name.replace("-", " ").split() if word), "inst")
    return f"{''.join(ch for ch in first.lower() if ch.isalnum())[:14]}{institution_id}"


def ensure_institution_users(db: Session) -> list[Credential]:
    """One ``institution`` account per institution, each with its own password.

    Accounts that already exist keep their password and are not returned.
    """
    created: list[Credential] = []
    used: set[str] = {
        row for row in db.execute(select(User.username)).scalars()
    }
    for institution in db.execute(select(Institution).order_by(Institution.id)).scalars():
        existing = db.execute(
            select(User).where(User.role == "institution", User.institution_id == institution.id)
        ).scalar_one_or_none()
        if existing is not None:
            continue
        base = f"{_slug(institution.name, institution.id)}_admin"
        username = base
        suffix = 2
        while username in used:
            username = f"{base}{suffix}"
            suffix += 1
        used.add(username)
        created.append(
            _issue(
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
) -> Credential:
    return _issue(
        db,
        DemoAccount(
            username=username,
            role="student",
            display_name=display_name,
            label=label,
            student_id=student.id,
        ),
    )


def write_credentials(credentials: list[Credential], path: Path = CREDENTIALS_PATH) -> Path:
    """Write the demo sign-in sheet. The file is gitignored and never served."""
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["username", "role", "password", "label"])
        for item in sorted(credentials, key=lambda c: (c.role, c.username)):
            writer.writerow([item.username, item.role, item.password, item.label])
    return path
