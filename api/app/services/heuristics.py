"""Rule-based detectors that run over the stored records (Step 10 of docs/PLAN.md).

* ``LATE_ADMISSION`` — admissions after the cutoff, flagged per row and aggregated per
  institution (rows are also flagged during upload validation).
* ``INVALID_APAAR`` / ``APAAR_NOT_FOUND`` / ``APAAR_MISMATCH`` — students whose APAAR ID
  failed format validation or the registry lookup.
"""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models.core import Enrolment, Institution, Student
from app.models.enums import ACTIVE_ENROLMENT_STATUSES
from app.services.flags import resolve_stale_flags, upsert_flag
from app.services.rules import calendar_thresholds, known_academic_years, year_calendar

# --- thresholds (tuning choices) ---------------------------------------------------
LATE_ADMISSION_MIN_COUNT = 5


def _institution_name(db: Session, institution_id: int) -> str:
    institution = db.get(Institution, institution_id)
    return institution.name if institution else f"institution {institution_id}"

# --------------------------------------------------------------------------- late admissions


def detect_late_admissions(db: Session, *, academic_year: str | None = None) -> dict[str, int]:
    """Flag each post-cutoff admission, and aggregate the share per institution.

    Uploads raise the per-row flag as the data arrives; this covers seeded data and any
    row whose admission date was corrected later. Both use the same dedupe key, so a row
    is never flagged twice.
    """
    years = [academic_year] if academic_year else list(known_academic_years())
    thresholds = calendar_thresholds()
    share_threshold = thresholds.get("late_admission_institution_share_percent", 2.0)

    created = 0
    updated = 0
    rows_created = 0
    keep: set[str] = set()

    for year in years:
        try:
            calendar = year_calendar(year)
        except KeyError:  # pragma: no cover - a year without a calendar entry
            continue

        # --- per-enrolment flags -------------------------------------------------
        late_enrolments = db.execute(
            select(Enrolment)
            .where(
                Enrolment.academic_year == year,
                Enrolment.status.in_(ACTIVE_ENROLMENT_STATUSES),
                Enrolment.admitted_on.is_not(None),
            )
        ).scalars()
        for enrolment in late_enrolments:
            cutoff = (
                calendar.lateral_window_end
                if enrolment.admission_type == "lateral"
                else calendar.admission_window_end
            )
            if enrolment.admitted_on is None or enrolment.admitted_on <= cutoff:
                continue
            dedupe_key = f"enrolment:{enrolment.id}:LATE_ADMISSION"
            keep.add(dedupe_key)
            student = db.get(Student, enrolment.student_id)
            _flag, was_created = upsert_flag(
                db,
                type="LATE_ADMISSION",
                dedupe_key=dedupe_key,
                severity="medium",
                title="Admission recorded after the cutoff date",
                explanation=(
                    f"{student.apaar_masked if student else 'This student'} was admitted on "
                    f"{enrolment.admitted_on.isoformat()}, after the {year} "
                    f"{'lateral-entry' if enrolment.admission_type == 'lateral' else 'admission'} "
                    f"cutoff of {cutoff.isoformat()}. Admissions after the cutoff need specific "
                    "approval."
                ),
                evidence={
                    "admitted_on": enrolment.admitted_on.isoformat(),
                    "cutoff": cutoff.isoformat(),
                    "admission_type": enrolment.admission_type,
                    "academic_year": year,
                    "apaar_masked": student.apaar_masked if student else None,
                },
                institution_id=enrolment.institution_id,
                student_id=enrolment.student_id,
                enrolment_id=enrolment.id,
                academic_year=year,
            )
            rows_created += int(was_created)
            updated += int(not was_created)

        # --- per-institution aggregate -------------------------------------------
        rows = db.execute(
            select(
                Enrolment.institution_id,
                Enrolment.admission_type,
                func.count(),
                func.sum(
                    case((Enrolment.admitted_on > calendar.admission_window_end, 1), else_=0)
                ),
            )
            .where(
                Enrolment.academic_year == year,
                Enrolment.status.in_(ACTIVE_ENROLMENT_STATUSES),
                Enrolment.admitted_on.is_not(None),
            )
            .group_by(Enrolment.institution_id, Enrolment.admission_type)
        ).all()

        per_institution: dict[int, dict[str, int]] = defaultdict(lambda: {"total": 0, "late": 0})
        for institution_id, admission_type, total, late in rows:
            cutoff = (
                calendar.lateral_window_end
                if admission_type == "lateral"
                else calendar.admission_window_end
            )
            if admission_type == "lateral":
                # Recount lateral entrants against their own, later window.
                late = db.scalar(
                    select(func.count())
                    .select_from(Enrolment)
                    .where(
                        Enrolment.academic_year == year,
                        Enrolment.institution_id == institution_id,
                        Enrolment.admission_type == "lateral",
                        Enrolment.status.in_(ACTIVE_ENROLMENT_STATUSES),
                        Enrolment.admitted_on > cutoff,
                    )
                ) or 0
            per_institution[institution_id]["total"] += int(total or 0)
            per_institution[institution_id]["late"] += int(late or 0)

        for institution_id, counts in per_institution.items():
            late = counts["late"]
            total = counts["total"]
            if late < LATE_ADMISSION_MIN_COUNT:
                continue
            share = (late / total * 100.0) if total else 0.0
            if share < share_threshold:
                continue

            dedupe_key = f"institution:{institution_id}:{year}:LATE_ADMISSION"
            keep.add(dedupe_key)
            severity = "high" if share >= 10 else "medium"
            _flag, was_created = upsert_flag(
                db,
                type="LATE_ADMISSION",
                dedupe_key=dedupe_key,
                severity=severity,
                title=f"{late} admissions after the {year} cutoff",
                explanation=(
                    f"{_institution_name(db, institution_id)} reported {late} of {total} "
                    f"admissions ({share:.1f}%) with an admission date after the "
                    f"{year} cutoff of {calendar.admission_window_end.isoformat()}. Admissions "
                    "after the cutoff need specific approval."
                ),
                evidence={
                    "late_count": late,
                    "total_admissions": total,
                    "share_percent": round(share, 2),
                    "cutoff": calendar.admission_window_end.isoformat(),
                    "threshold_percent": share_threshold,
                    "academic_year": year,
                },
                institution_id=institution_id,
                academic_year=year,
            )
            created += int(was_created)
            updated += int(not was_created)

    closed = resolve_stale_flags(db, type="LATE_ADMISSION", keep_keys=keep)
    db.flush()
    return {
        "late_admission_rows": rows_created,
        "late_admission_institutions": created,
        "late_admission_updated": updated,
        "late_admission_closed": closed,
    }


# --------------------------------------------------------------------------- registry problems


def detect_apaar_problems(db: Session) -> dict[str, int]:
    """Raise flags for students whose APAAR ID failed validation or registry lookup.

    Uploads flag their own rows as they arrive; this covers seeded data and any row whose
    status changed after a re-check.
    """
    mapping = {
        "invalid_format": ("INVALID_APAAR", "medium", "APAAR ID is not a valid 12-digit ID"),
        "not_found": ("APAAR_NOT_FOUND", "high", "APAAR ID not found in the registry"),
        "mismatch": ("APAAR_MISMATCH", "medium", "Reported details do not match the APAAR registry"),
    }
    created = 0
    updated = 0
    keep: dict[str, set[str]] = {flag_type: set() for flag_type, _, _ in mapping.values()}

    for status, (flag_type, severity, title) in mapping.items():
        rows = db.execute(
            select(Student, Enrolment)
            .join(Enrolment, Enrolment.student_id == Student.id)
            .where(Student.registry_status == status)
        ).all()
        seen: set[int] = set()
        for student, enrolment in rows:
            if student.id in seen:
                continue
            seen.add(student.id)
            dedupe_key = f"student:{student.id}:{flag_type}"
            keep[flag_type].add(dedupe_key)
            explanations = {
                "invalid_format": (
                    f"The institution reported {student.apaar_masked} as this student's APAAR ID, "
                    "but it is not a valid 12-digit APAAR ID, so it cannot be verified."
                ),
                "not_found": (
                    f"APAAR {student.apaar_masked} was reported by the institution but the APAAR "
                    "registry has no record of it."
                ),
                "mismatch": (
                    f"The name or date of birth reported for {student.apaar_masked} does not match "
                    "the APAAR registry record for that ID."
                ),
            }
            _flag, was_created = upsert_flag(
                db,
                type=flag_type,
                dedupe_key=dedupe_key,
                severity=severity,
                title=title,
                explanation=explanations[status],
                evidence={
                    "apaar_masked": student.apaar_masked,
                    "registry_status": status,
                    "apaar_status": student.apaar_status,
                    "academic_year": enrolment.academic_year,
                },
                institution_id=enrolment.institution_id,
                student_id=student.id,
                enrolment_id=enrolment.id,
                academic_year=enrolment.academic_year,
            )
            created += int(was_created)
            updated += int(not was_created)

    closed = 0
    for flag_type, keys in keep.items():
        closed += resolve_stale_flags(db, type=flag_type, keep_keys=keys | _upload_level_keys(db, flag_type))
    db.flush()
    return {"apaar_problems": created, "apaar_problems_updated": updated, "apaar_problems_closed": closed}


def _upload_level_keys(db: Session, flag_type: str) -> set[str]:
    """Aggregated per-upload flags (e.g. rejected rows) are not per-student findings."""
    from app.models.core import Flag

    return {
        flag.dedupe_key
        for flag in db.execute(select(Flag).where(Flag.type == flag_type)).scalars()
        if flag.dedupe_key.startswith("upload:")
    }


# --------------------------------------------------------------------------- entry point


def run_heuristics(db: Session, *, academic_year: str | None = None) -> dict[str, int]:
    summary: dict[str, int] = {}
    summary.update(detect_late_admissions(db, academic_year=academic_year))
    summary.update(detect_apaar_problems(db))
    return summary
