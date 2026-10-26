"""Access log: every detail view / reveal (CLAUDE.md section 5 rule 7).

The student can read their own rows back through ``GET /student/access-log``, so an
officer revealing a student's details is visible to that student.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.core import AccessLog


def log_access(
    db: Session,
    *,
    actor: str,
    role: str,
    action: str,
    target: str,
    reason: str | None = None,
    student_id: int | None = None,
    purpose: str | None = None,
) -> AccessLog:
    """Append one access-log row. Caller commits."""
    entry = AccessLog(
        actor=actor,
        role=role,
        action=action,
        target=target,
        reason=reason,
        student_id=student_id,
        purpose=purpose,
    )
    db.add(entry)
    db.flush()
    return entry
