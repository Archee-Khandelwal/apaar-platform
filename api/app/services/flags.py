"""Flag creation and lookup.

Every flag carries a human-readable ``explanation`` and structured ``evidence``
(CLAUDE.md section 8) and is keyed by a stable ``dedupe_key`` so re-running a detector
updates the existing flag instead of creating a second one.

Flags shown to an institution never name another institution (CLAUDE.md section 5
rule 10) — ``sanitise_for_institution`` is the single place that rewriting happens.
"""
from __future__ import annotations

import copy
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.core import Flag
from app.models.enums import FLAG_TYPES, OPEN_FLAG_STATUSES, SEVERITIES

CROSS_INSTITUTION_NOTICE = "Possible duplicate enrolment — contact AICTE."

# Flag types whose evidence could identify another institution.
CROSS_INSTITUTION_TYPES = (
    "CROSS_INSTITUTION_DUPLICATE",
    "POSSIBLE_DUAL_DEGREE",
    "IDENTITY_DUPLICATE",
)


def upsert_flag(
    db: Session,
    *,
    type: str,
    dedupe_key: str,
    severity: str,
    title: str,
    explanation: str,
    evidence: dict[str, Any] | None = None,
    institution_id: int | None = None,
    student_id: int | None = None,
    enrolment_id: int | None = None,
    program_id: int | None = None,
    academic_year: str | None = None,
) -> tuple[Flag, bool]:
    """Create or update one flag. Returns ``(flag, created)``.

    An existing flag that an officer has dismissed or resolved is not reopened by a
    detector re-run; its evidence is refreshed so the case file stays accurate.
    """
    if type not in FLAG_TYPES:
        raise ValueError(f"Unknown flag type {type!r} — see CLAUDE.md section 8")
    if severity not in SEVERITIES:
        raise ValueError(f"Unknown severity {severity!r}")

    existing = db.execute(
        select(Flag).where(Flag.type == type, Flag.dedupe_key == dedupe_key)
    ).scalar_one_or_none()

    if existing is not None:
        existing.severity = severity
        existing.title = title
        existing.explanation = explanation
        existing.evidence = evidence or {}
        existing.institution_id = institution_id
        existing.student_id = student_id
        existing.enrolment_id = enrolment_id
        existing.program_id = program_id
        existing.academic_year = academic_year
        db.flush()
        return existing, False

    flag = Flag(
        type=type,
        dedupe_key=dedupe_key,
        severity=severity,
        status="open",
        title=title,
        explanation=explanation,
        evidence=evidence or {},
        institution_id=institution_id,
        student_id=student_id,
        enrolment_id=enrolment_id,
        program_id=program_id,
        academic_year=academic_year,
        notes=[],
    )
    db.add(flag)
    db.flush()
    return flag, True


def resolve_stale_flags(
    db: Session,
    *,
    type: str,
    keep_keys: set[str],
    institution_id: int | None = None,
    key_suffix: str | None = None,
) -> int:
    """Auto-resolve open flags of one type whose finding no longer exists.

    Used by idempotent detector re-runs: if a college fixes its data, the flag closes
    itself with a note rather than lingering in the queue.

    ``key_suffix`` limits reconciliation to one detector's dedupe-key namespace, for
    detectors that share a flag type.
    """
    statement = select(Flag).where(Flag.type == type, Flag.status.in_(OPEN_FLAG_STATUSES))
    if institution_id is not None:
        statement = statement.where(Flag.institution_id == institution_id)

    closed = 0
    for flag in db.execute(statement).scalars():
        if flag.dedupe_key in keep_keys:
            continue
        if key_suffix is not None and not flag.dedupe_key.endswith(key_suffix):
            continue
        flag.status = "resolved"
        notes = list(flag.notes or [])
        notes.append(
            {
                "author": "system",
                "note": "Finding no longer present in the reported data; closed automatically.",
            }
        )
        flag.notes = notes
        closed += 1
    if closed:
        db.flush()
    return closed


def sanitise_for_institution(flag: Flag | dict[str, Any]) -> dict[str, Any]:
    """Institution-facing view of a flag: never names another institution."""
    data = (
        flag
        if isinstance(flag, dict)
        else {
            "id": flag.id,
            "type": flag.type,
            "severity": flag.severity,
            "status": flag.status,
            "title": flag.title,
            "explanation": flag.explanation,
            "evidence": copy.deepcopy(flag.evidence or {}),
            "student_id": flag.student_id,
            "enrolment_id": flag.enrolment_id,
            "academic_year": flag.academic_year,
            "program_id": flag.program_id,
            "created_at": flag.created_at,
        }
    )

    if data["type"] in CROSS_INSTITUTION_TYPES:
        data["title"] = "Possible duplicate enrolment"
        data["explanation"] = CROSS_INSTITUTION_NOTICE
        evidence = data.get("evidence") or {}
        data["evidence"] = {
            key: value
            for key, value in evidence.items()
            if key in ("apaar_masked", "academic_year", "your_program", "student_id")
        }
        data["evidence"].setdefault("notice", CROSS_INSTITUTION_NOTICE)
    else:
        evidence = data.get("evidence") or {}
        # Strip any other institution's identity from evidence of any flag type.
        for key in ("sides", "institutions", "other_institution", "other_institution_id",
                    "other_institution_name", "institution_ids", "institution_names"):
            evidence.pop(key, None)
        data["evidence"] = evidence

    data.pop("institution_id", None)
    data.pop("institution_name", None)
    return data
