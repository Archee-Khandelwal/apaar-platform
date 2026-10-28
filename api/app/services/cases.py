"""Flag queries, case management and the reveal path (Step 12 of docs/PLAN.md).

Role boundaries live here, in one place:

* ``aicte_viewer`` gets masked flag rows with no ``evidence``, ``notes`` or ``history``
  (Step-0 decision 3), and small-count suppression on any breakdown.
* ``aicte_officer`` gets the full case file, may change status, assign and add notes.
* an ``institution`` gets only its own flags, with another college never named
  (CLAUDE.md section 5 rule 10) via ``flags.sanitise_for_institution``.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.core.access_log import log_access
from app.core.audit import log_audit
from app.core.crypto import vault_decrypt
from app.models.core import (
    Enrolment,
    Flag,
    FlagHistory,
    Institution,
    Program,
    Student,
    Vault,
)
from app.models.enums import FLAG_STATUSES, OPEN_FLAG_STATUSES, SEVERITY_ORDER

REVEAL_MIN_REASON = 10

# Fields a viewer may see on a flag. Everything else is officer-only.
VIEWER_FLAG_FIELDS = (
    "id",
    "type",
    "severity",
    "status",
    "title",
    "explanation",
    "institution_id",
    "institution_name",
    "state",
    "academic_year",
    "created_at",
)

FLAG_SORTS = {
    "created_at": Flag.created_at,
    "severity": Flag.severity,
    "type": Flag.type,
    "status": Flag.status,
}


def flag_to_dict(
    flag: Flag,
    *,
    role: str,
    institution_name: str | None = None,
    state: str | None = None,
) -> dict[str, Any]:
    """One flag, shaped for the caller's role."""
    full: dict[str, Any] = {
        "id": flag.id,
        "type": flag.type,
        "severity": flag.severity,
        "status": flag.status,
        "title": flag.title,
        "explanation": flag.explanation,
        "evidence": flag.evidence or {},
        "institution_id": flag.institution_id,
        "institution_name": institution_name,
        "state": state,
        "student_id": flag.student_id,
        "enrolment_id": flag.enrolment_id,
        "program_id": flag.program_id,
        "academic_year": flag.academic_year,
        "assigned_to": flag.assigned_to,
        "notes": flag.notes or [],
        "created_at": flag.created_at,
    }
    if role == "aicte_viewer":
        return {key: value for key, value in full.items() if key in VIEWER_FLAG_FIELDS}
    return full


def build_flag_query(
    *,
    types: list[str] | None = None,
    severities: list[str] | None = None,
    statuses: list[str] | None = None,
    state: str | None = None,
    institution_id: int | None = None,
    academic_year: str | None = None,
    assigned_to: str | None = None,
    student_id: int | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    search: str | None = None,
    open_only: bool = False,
) -> Select:
    """The one query builder every flag listing uses."""
    statement = select(Flag, Institution).outerjoin(
        Institution, Institution.id == Flag.institution_id
    )
    if types:
        statement = statement.where(Flag.type.in_(types))
    if severities:
        statement = statement.where(Flag.severity.in_(severities))
    if statuses:
        statement = statement.where(Flag.status.in_(statuses))
    if open_only:
        statement = statement.where(Flag.status.in_(OPEN_FLAG_STATUSES))
    if state:
        statement = statement.where(Institution.state == state)
    if institution_id is not None:
        statement = statement.where(Flag.institution_id == institution_id)
    if academic_year:
        statement = statement.where(Flag.academic_year == academic_year)
    if assigned_to:
        statement = statement.where(Flag.assigned_to == assigned_to)
    if student_id is not None:
        statement = statement.where(Flag.student_id == student_id)
    if created_from is not None:
        statement = statement.where(Flag.created_at >= created_from)
    if created_to is not None:
        statement = statement.where(Flag.created_at <= created_to)
    if search:
        pattern = f"%{search.strip()}%"
        statement = statement.where(
            Flag.title.ilike(pattern) | Flag.explanation.ilike(pattern) | Flag.type.ilike(pattern)
        )
    return statement


def order_flags(statement: Select, sort: str | None) -> Select:
    """Severity sorts by seriousness, not alphabetically."""
    sort = sort or "-severity"
    descending = sort.startswith("-")
    field = sort.lstrip("-")

    if field == "severity":
        # Severity must sort by seriousness, not alphabetically ("critical" < "low").
        from sqlalchemy import case as sa_case

        rank = sa_case(SEVERITY_ORDER, value=Flag.severity, else_=0)
        return statement.order_by(rank.desc() if descending else rank.asc(), Flag.id.desc())

    column = FLAG_SORTS.get(field, Flag.created_at)
    return statement.order_by(column.desc() if descending else column.asc(), Flag.id.desc())


def flag_facets(db: Session, statement: Select) -> dict[str, dict[str, int]]:
    """Counts by type, severity and status for the current filter set."""
    rows = list(db.execute(statement).all())
    flags = [row[0] for row in rows]
    return {
        "by_type": dict(Counter(flag.type for flag in flags)),
        "by_severity": dict(Counter(flag.severity for flag in flags)),
        "by_status": dict(Counter(flag.status for flag in flags)),
    }


# --------------------------------------------------------------------------- case actions


ALLOWED_INSTITUTION_STATUSES = ("under_review", "resolved")


def update_flag(
    db: Session,
    *,
    flag: Flag,
    actor: str,
    role: str,
    status: str | None = None,
    assigned_to: str | None = None,
    note: str | None = None,
    reason: str | None = None,
) -> tuple[Flag, int | None]:
    """Apply a case action and audit it. Returns (flag, audit_log_id)."""
    previous_status = flag.status
    changed: dict[str, Any] = {}

    if status is not None and status != flag.status:
        if status not in FLAG_STATUSES:
            raise ValueError(f"Unknown flag status {status!r}")
        flag.status = status
        changed["status"] = {"from": previous_status, "to": status}

    if assigned_to is not None and assigned_to != flag.assigned_to:
        changed["assigned_to"] = {"from": flag.assigned_to, "to": assigned_to}
        flag.assigned_to = assigned_to or None

    if note:
        notes = list(flag.notes or [])
        notes.append(
            {
                "author": actor,
                "role": role,
                "note": note,
                "created_at": datetime.utcnow().replace(microsecond=0).isoformat(),
            }
        )
        flag.notes = notes
        changed["note_added"] = True

    if not changed:
        return flag, None

    entry = log_audit(
        db,
        actor=actor,
        role=role,
        action="flag_updated",
        target=f"flag:{flag.id}",
        payload={"changes": changed, "reason": reason, "flag_type": flag.type},
    )
    db.add(
        FlagHistory(
            flag_id=flag.id,
            from_status=previous_status,
            to_status=flag.status,
            actor=actor,
            reason=reason or note,
            audit_log_id=entry.id,
        )
    )
    db.flush()
    return flag, entry.id


def flag_history(db: Session, flag_id: int) -> list[dict[str, Any]]:
    rows = db.execute(
        select(FlagHistory).where(FlagHistory.flag_id == flag_id).order_by(FlagHistory.id)
    ).scalars()
    return [
        {
            "from": row.from_status,
            "to": row.to_status,
            "actor": row.actor,
            "reason": row.reason,
            "at": row.created_at,
            "audit_log_id": row.audit_log_id,
        }
        for row in rows
    ]


# --------------------------------------------------------------------------- reveal


class RevealError(ValueError):
    """Raised when a reveal is attempted without an adequate reason."""


def reveal_student(
    db: Session, *, student_id: int, reason: str, actor: str, role: str
) -> dict[str, Any]:
    """Decrypt one student's identifiers for an officer, with a mandatory reason.

    CLAUDE.md section 5 rules 6 and 7: this is the only route that returns raw APAAR,
    name and DOB, and every call is written to the access log, which the student can
    read. Contact details are never returned, even here.
    """
    reason = (reason or "").strip()
    if len(reason) < REVEAL_MIN_REASON:
        raise RevealError(
            f"A reason of at least {REVEAL_MIN_REASON} characters is required to reveal "
            "student details."
        )

    student = db.get(Student, student_id)
    if student is None:
        raise LookupError("No such student.")
    vault = db.execute(select(Vault).where(Vault.student_id == student_id)).scalar_one_or_none()

    enrolments: list[dict[str, Any]] = []
    for enrolment, program, institution in db.execute(
        select(Enrolment, Program, Institution)
        .join(Program, Program.id == Enrolment.program_id)
        .join(Institution, Institution.id == Enrolment.institution_id)
        .where(Enrolment.student_id == student_id)
        .order_by(Enrolment.academic_year.desc(), Enrolment.id.asc())
    ).all():
        enrolments.append(
            {
                "id": enrolment.id,
                "institution_id": institution.id,
                "institution_name": institution.name,
                "program": f"{program.course} {program.branch}",
                "mode": program.mode,
                "academic_year": enrolment.academic_year,
                "year_of_study": enrolment.year_of_study,
                "admission_type": enrolment.admission_type,
                "status": enrolment.status,
                "admitted_on": enrolment.admitted_on,
            }
        )

    entry = log_access(
        db,
        actor=actor,
        role=role,
        action="reveal_student_details",
        target=f"student:{student_id}",
        reason=reason,
        student_id=student_id,
    )
    log_audit(
        db,
        actor=actor,
        role=role,
        action="reveal_student_details",
        target=f"student:{student_id}",
        payload={"reason": reason, "access_log_id": entry.id},
    )
    db.flush()

    return {
        "student_id": student_id,
        "apaar_id": vault_decrypt(vault.apaar_enc) if vault else None,
        "apaar_status": student.apaar_status,
        "name": vault_decrypt(vault.name_enc) if vault else None,
        "dob": vault_decrypt(vault.dob_enc) if vault else None,
        "gender": student.gender,
        "category": student.category,
        "nationality_status": student.nationality_status,
        "is_minor": student.is_minor,
        "enrolments": enrolments,
        "access_log_id": entry.id,
        "revealed_at": entry.created_at,
        "notice": "This access has been logged and is visible to the student.",
    }
