"""Duplicate and identity detection (Step 8 of docs/PLAN.md).

Three findings, and the distinction between them is the point:

* ``CROSS_INSTITUTION_DUPLICATE`` — the same APAAR ID with active enrolments at two or
  more institutions in the same academic year, **all full-time regular**. Likely fraud.
* ``POSSIBLE_DUAL_DEGREE`` — the same situation but at least one programme is online/ODL.
  This is legal (CLAUDE.md section 6), so it is informational, severity low, and must
  never be presented as fraud.
* ``IDENTITY_DUPLICATE`` — two different APAAR IDs that look like the same person: same
  normalised name, same date of birth and same guardian phone.

Privacy: the name is decrypted only inside this module, for matching, and is never
returned or logged. Institution-facing wording is handled by
``flags.sanitise_for_institution`` (CLAUDE.md section 5 rule 10).
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.crypto import normalize_name, vault_decrypt
from app.models.core import Enrolment, Institution, Program, Student, Vault
from app.models.enums import ACTIVE_ENROLMENT_STATUSES
from app.services.flags import resolve_stale_flags, upsert_flag

MIN_INSTITUTIONS = 2


@dataclass
class EnrolmentSide:
    """One side of a duplicate: where and how a student is enrolled."""

    enrolment_id: int
    institution_id: int
    institution_name: str
    program_id: int
    program: str
    mode: str
    admission_type: str
    year_of_study: int
    status: str
    admitted_on: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "enrolment_id": self.enrolment_id,
            "institution_id": self.institution_id,
            "institution_name": self.institution_name,
            "program_id": self.program_id,
            "program": self.program,
            "mode": self.mode,
            "admission_type": self.admission_type,
            "year_of_study": self.year_of_study,
            "status": self.status,
            "admitted_on": self.admitted_on,
        }

    @property
    def is_full_time_regular(self) -> bool:
        """Full-time means a regular-mode programme; lateral entry is still full time."""
        return self.mode == "regular"


def _sides_by_student_year(
    db: Session, *, academic_year: str | None = None
) -> dict[tuple[int, str], list[EnrolmentSide]]:
    """Active enrolments grouped by (student, academic year)."""
    statement = (
        select(Enrolment, Program, Institution)
        .join(Program, Program.id == Enrolment.program_id)
        .join(Institution, Institution.id == Enrolment.institution_id)
        .where(Enrolment.status.in_(ACTIVE_ENROLMENT_STATUSES))
    )
    if academic_year:
        statement = statement.where(Enrolment.academic_year == academic_year)

    grouped: dict[tuple[int, str], list[EnrolmentSide]] = defaultdict(list)
    for enrolment, program, institution in db.execute(statement).all():
        grouped[(enrolment.student_id, enrolment.academic_year)].append(
            EnrolmentSide(
                enrolment_id=enrolment.id,
                institution_id=institution.id,
                institution_name=institution.name,
                program_id=program.id,
                program=f"{program.course} {program.branch}",
                mode=program.mode,
                admission_type=enrolment.admission_type,
                year_of_study=enrolment.year_of_study,
                status=enrolment.status,
                admitted_on=enrolment.admitted_on.isoformat() if enrolment.admitted_on else None,
            )
        )
    return grouped


def classify_sides(sides: list[EnrolmentSide]) -> tuple[str | None, str]:
    """Decide what a multi-institution enrolment set is. Returns (flag_type, reason)."""
    institutions = {side.institution_id for side in sides}
    if len(institutions) < MIN_INSTITUTIONS:
        return None, "single_institution"

    full_time = [side for side in sides if side.is_full_time_regular]
    online = [side for side in sides if not side.is_full_time_regular]

    if online:
        # Legal dual degree: at least one enrolment is online / ODL.
        return "POSSIBLE_DUAL_DEGREE", "at_least_one_online_or_odl"
    if len({side.institution_id for side in full_time}) >= MIN_INSTITUTIONS:
        return "CROSS_INSTITUTION_DUPLICATE", "both_full_time_regular"
    return None, "not_concurrent"  # pragma: no cover - defensive


def detect_cross_institution_duplicates(
    db: Session, *, academic_year: str | None = None
) -> dict[str, int]:
    """Flag the same APAAR ID enrolled at two institutions in one year."""
    created = 0
    updated = 0
    dual_created = 0
    keep: dict[str, set[str]] = {"CROSS_INSTITUTION_DUPLICATE": set(), "POSSIBLE_DUAL_DEGREE": set()}

    for (student_id, year), sides in _sides_by_student_year(db, academic_year=academic_year).items():
        flag_type, reason = classify_sides(sides)
        if flag_type is None:
            continue

        student = db.get(Student, student_id)
        if student is None:  # pragma: no cover - referential integrity
            continue
        # A student with no APAAR ID cannot be matched across institutions by APAAR;
        # IDENTITY_DUPLICATE covers that case instead.
        if student.apaar_hash is None:
            continue

        dedupe_key = f"student:{student_id}:{year}"
        keep[flag_type].add(dedupe_key)
        names = sorted({side.institution_name for side in sides})

        if flag_type == "CROSS_INSTITUTION_DUPLICATE":
            severity = "high"
            title = "Same APAAR ID enrolled full-time at two institutions"
            explanation = (
                f"APAAR {student.apaar_masked} has active full-time regular enrolments at "
                + " and ".join(
                    f"{side.institution_name} ({side.program}, year {side.year_of_study})"
                    for side in sides
                )
                + f" in {year}. Neither programme is online/ODL, so this is not a permitted "
                "dual degree."
            )
        else:
            severity = "low"
            title = "Possible dual degree (one enrolment is online/ODL)"
            online_side = next(side for side in sides if not side.is_full_time_regular)
            regular_sides = [side for side in sides if side.is_full_time_regular]
            explanation = (
                f"APAAR {student.apaar_masked} appears at {len(set(s.institution_id for s in sides))} "
                f"institutions in {year}, but {online_side.institution_name}'s "
                f"{online_side.program} is an online/ODL programme"
                + (
                    f" alongside a regular enrolment at {regular_sides[0].institution_name}"
                    if regular_sides
                    else ""
                )
                + ". Studying one regular and one online programme is permitted, so this is "
                "recorded for information, not as fraud."
            )

        flag, was_created = upsert_flag(
            db,
            type=flag_type,
            dedupe_key=dedupe_key,
            severity=severity,
            title=title,
            explanation=explanation,
            evidence={
                "apaar_masked": student.apaar_masked,
                "academic_year": year,
                "classification_reason": reason,
                "sides": [side.as_dict() for side in sides],
                "institutions": names,
                "is_fraud_indicator": flag_type == "CROSS_INSTITUTION_DUPLICATE",
            },
            # The flag belongs to the first institution for queue purposes; the officer
            # view shows both sides, the institution view names neither.
            institution_id=sides[0].institution_id,
            student_id=student_id,
            enrolment_id=sides[0].enrolment_id,
            academic_year=year,
        )
        if flag_type == "POSSIBLE_DUAL_DEGREE":
            dual_created += int(was_created)
        else:
            created += int(was_created)
        updated += int(not was_created)

    closed = 0
    for flag_type, keys in keep.items():
        closed += resolve_stale_flags(db, type=flag_type, keep_keys=keys)

    db.flush()
    return {
        "cross_institution_duplicates": created,
        "possible_dual_degrees": dual_created,
        "duplicates_updated": updated,
        "duplicates_closed": closed,
    }


def detect_identity_duplicates(db: Session) -> dict[str, int]:
    """Flag two different APAAR IDs that look like one person.

    Match key: same normalised name + same DOB + same guardian phone. The name is
    decrypted only here, for comparison, and never leaves this function.
    """
    candidates = db.execute(
        select(Student).where(
            Student.apaar_hash.is_not(None),
            Student.dob_hash.is_not(None),
            Student.guardian_phone_hash.is_not(None),
            Student.name_hash.is_not(None),
        )
    ).scalars()

    groups: dict[tuple[str, str, str], list[Student]] = defaultdict(list)
    for student in candidates:
        groups[(student.name_hash, student.dob_hash, student.guardian_phone_hash)].append(student)

    created = 0
    updated = 0
    keep: set[str] = set()

    for (_name_hash, _dob_hash, _guardian_hash), members in groups.items():
        distinct_apaar = {student.apaar_hash for student in members}
        if len(members) < 2 or len(distinct_apaar) < 2:
            continue

        # Confirm on the decrypted names: the hash matched a normalised form, and we
        # want the evidence to say the names really are the same person's.
        names = set()
        for student in members:
            vault = db.execute(select(Vault).where(Vault.student_id == student.id)).scalar_one_or_none()
            if vault is not None:
                names.add(normalize_name(vault_decrypt(vault.name_enc)))
        if len(names) > 1:  # pragma: no cover - a hash collision would be needed
            continue

        member_ids = sorted(student.id for student in members)
        institutions = _institutions_for(db, member_ids)

        for student in members:
            dedupe_key = f"student:{student.id}:IDENTITY_DUPLICATE"
            keep.add(dedupe_key)
            others = [other for other in members if other.id != student.id]
            _flag, was_created = upsert_flag(
                db,
                type="IDENTITY_DUPLICATE",
                dedupe_key=dedupe_key,
                severity="high",
                title="One person appears to hold two APAAR IDs",
                explanation=(
                    f"{student.apaar_masked} and "
                    + ", ".join(other.apaar_masked for other in others)
                    + " were reported with the same name, the same date of birth "
                    f"({student.dob_year}) and the same guardian contact. An APAAR ID is meant "
                    "to be one per student for life, so these records are likely the same person."
                ),
                evidence={
                    "apaar_masked": student.apaar_masked,
                    "other_apaar_masked": [other.apaar_masked for other in others],
                    "student_ids": member_ids,
                    "dob_year": student.dob_year,
                    "matched_on": ["name", "date_of_birth", "guardian_phone"],
                    "institutions": institutions,
                },
                institution_id=_primary_institution(db, student.id),
                student_id=student.id,
            )
            created += int(was_created)
            updated += int(not was_created)

    closed = resolve_stale_flags(db, type="IDENTITY_DUPLICATE", keep_keys=keep)
    db.flush()
    return {
        "identity_duplicates": created,
        "identity_duplicates_updated": updated,
        "identity_duplicates_closed": closed,
    }


def _institutions_for(db: Session, student_ids: list[int]) -> list[str]:
    rows = db.execute(
        select(Institution.name)
        .join(Enrolment, Enrolment.institution_id == Institution.id)
        .where(Enrolment.student_id.in_(student_ids))
        .distinct()
    ).scalars()
    return sorted(rows)


def _primary_institution(db: Session, student_id: int) -> int | None:
    return db.scalar(
        select(Enrolment.institution_id)
        .where(Enrolment.student_id == student_id)
        .order_by(Enrolment.academic_year.desc(), Enrolment.id.asc())
        .limit(1)
    )


def run_duplicate_detection(
    db: Session, *, academic_year: str | None = None
) -> dict[str, int]:
    summary = detect_cross_institution_duplicates(db, academic_year=academic_year)
    summary.update(detect_identity_duplicates(db))
    return summary
