"""Heuristic detectors (Step 10 of docs/PLAN.md).

Four patterns that a counts-only return can never show:

* ``SEQUENTIAL_APAAR``  — a run of near-consecutive APAAR IDs in one cohort, which
  suggests IDs were generated rather than collected from real students.
* ``LATE_ADMISSION``    — admissions after the cutoff, aggregated per institution
  (individual rows are flagged during upload validation).
* ``LAST_MINUTE_BULK``  — a large share of an institution's records created in the final
  hours before the reporting deadline.
* ``PHANTOM_PROGRESSION`` — year-2 regular students with no year-1 record (and not
  lateral entrants), and students who vanish between years with no exit status.

Raw APAAR IDs are decrypted only inside ``detect_sequential_apaar`` for sorting, and only
masked values ever reach a flag.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.core.crypto import mask_apaar, vault_decrypt
from app.models.core import Enrolment, Institution, Program, Student, Upload, Vault
from app.models.enums import ACTIVE_ENROLMENT_STATUSES
from app.services.flags import resolve_stale_flags, upsert_flag
from app.services.rules import calendar_thresholds, known_academic_years, year_calendar

# --- thresholds (tuning choices) ---------------------------------------------------
SEQUENTIAL_MIN_RUN = 10
SEQUENTIAL_MAX_GAP = 3  # consecutive IDs differing by at most this much continue a run
LATE_ADMISSION_MIN_COUNT = 5


@dataclass
class Run:
    apaars: list[str]
    student_ids: list[int]

    @property
    def length(self) -> int:
        return len(self.apaars)


def _institution_name(db: Session, institution_id: int) -> str:
    institution = db.get(Institution, institution_id)
    return institution.name if institution else f"institution {institution_id}"


# --------------------------------------------------------------------------- sequential


def find_runs(pairs: list[tuple[int, int]]) -> list[Run]:
    """``pairs`` is (apaar_as_int, student_id), unsorted. Returns runs of near-consecutive IDs."""
    ordered = sorted(pairs)
    runs: list[Run] = []
    current: list[tuple[int, int]] = []

    for item in ordered:
        if not current:
            current = [item]
            continue
        if 0 < item[0] - current[-1][0] <= SEQUENTIAL_MAX_GAP:
            current.append(item)
            continue
        if len(current) >= SEQUENTIAL_MIN_RUN:
            runs.append(Run([f"{value:012d}" for value, _ in current], [sid for _, sid in current]))
        current = [item]

    if len(current) >= SEQUENTIAL_MIN_RUN:
        runs.append(Run([f"{value:012d}" for value, _ in current], [sid for _, sid in current]))
    return runs


def detect_sequential_apaar(db: Session, *, academic_year: str | None = None) -> dict[str, int]:
    """Flag runs of near-consecutive APAAR IDs within one institution and year."""
    statement = (
        select(Enrolment.institution_id, Enrolment.academic_year, Student.id, Vault.apaar_enc)
        .join(Student, Student.id == Enrolment.student_id)
        .join(Vault, Vault.student_id == Student.id)
        .where(
            Student.apaar_hash.is_not(None),
            Student.apaar_status == "provided",
            Enrolment.status.in_(ACTIVE_ENROLMENT_STATUSES),
        )
    )
    if academic_year:
        statement = statement.where(Enrolment.academic_year == academic_year)

    cohorts: dict[tuple[int, str], list[tuple[int, int]]] = defaultdict(list)
    seen: set[tuple[int, str, int]] = set()
    for institution_id, year, student_id, apaar_enc in db.execute(statement).all():
        if (institution_id, year, student_id) in seen:
            continue
        seen.add((institution_id, year, student_id))
        raw = vault_decrypt(apaar_enc)  # decrypted here only, to sort numerically
        if not raw or not raw.isdigit():
            continue
        cohorts[(institution_id, year)].append((int(raw), student_id))

    created = 0
    updated = 0
    keep: set[str] = set()

    for (institution_id, year), pairs in cohorts.items():
        for index, run in enumerate(find_runs(pairs)):
            dedupe_key = f"institution:{institution_id}:{year}:run{index}"
            keep.add(dedupe_key)
            severity = "high" if run.length >= 2 * SEQUENTIAL_MIN_RUN else "medium"
            _flag, was_created = upsert_flag(
                db,
                type="SEQUENTIAL_APAAR",
                dedupe_key=dedupe_key,
                severity=severity,
                title=f"{run.length} near-consecutive APAAR IDs in one cohort",
                explanation=(
                    f"{_institution_name(db, institution_id)} reported {run.length} students in "
                    f"{year} whose APAAR IDs run almost consecutively from "
                    f"{mask_apaar(run.apaars[0])} to {mask_apaar(run.apaars[-1])}. APAAR IDs are "
                    "issued nationally over time, so a block this tight in one cohort suggests "
                    "the IDs were generated rather than collected from students."
                ),
                evidence={
                    "run_length": run.length,
                    "first_masked": mask_apaar(run.apaars[0]),
                    "last_masked": mask_apaar(run.apaars[-1]),
                    "max_gap": SEQUENTIAL_MAX_GAP,
                    "student_ids": run.student_ids[:50],
                    "academic_year": year,
                },
                institution_id=institution_id,
                academic_year=year,
            )
            created += int(was_created)
            updated += int(not was_created)

    closed = resolve_stale_flags(db, type="SEQUENTIAL_APAAR", keep_keys=keep)
    db.flush()
    return {
        "sequential_apaar": created,
        "sequential_apaar_updated": updated,
        "sequential_apaar_closed": closed,
    }


# --------------------------------------------------------------------------- late admissions


def detect_late_admissions(db: Session, *, academic_year: str | None = None) -> dict[str, int]:
    """Aggregate per institution: how many admissions fell after the cutoff, and what share."""
    years = [academic_year] if academic_year else list(known_academic_years())
    thresholds = calendar_thresholds()
    share_threshold = thresholds.get("late_admission_institution_share_percent", 2.0)

    created = 0
    updated = 0
    keep: set[str] = set()

    for year in years:
        try:
            calendar = year_calendar(year)
        except KeyError:  # pragma: no cover - a year without a calendar entry
            continue

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

    closed = resolve_stale_flags(
        db,
        type="LATE_ADMISSION",
        keep_keys=keep | _per_enrolment_late_keys(db),
    )
    db.flush()
    return {
        "late_admission_institutions": created,
        "late_admission_updated": updated,
        "late_admission_closed": closed,
    }


def _per_enrolment_late_keys(db: Session) -> set[str]:
    """Per-row LATE_ADMISSION flags raised during upload validation must survive."""
    from app.models.core import Flag

    return {
        flag.dedupe_key
        for flag in db.execute(
            select(Flag).where(Flag.type == "LATE_ADMISSION", Flag.enrolment_id.is_not(None))
        ).scalars()
    }


# --------------------------------------------------------------------------- last-minute bulk


def detect_last_minute_bulk(db: Session, *, academic_year: str | None = None) -> dict[str, int]:
    """Flag institutions that filed most of their records just before the deadline."""
    years = [academic_year] if academic_year else list(known_academic_years())
    thresholds = calendar_thresholds()
    window_hours = thresholds.get("last_minute_bulk_window_hours", 6.0)
    share_threshold = thresholds.get("last_minute_bulk_share_percent", 40.0)

    created = 0
    updated = 0
    keep: set[str] = set()

    for year in years:
        try:
            calendar = year_calendar(year)
        except KeyError:  # pragma: no cover
            continue
        window_start = calendar.reporting_deadline - timedelta(hours=window_hours)

        rows = db.execute(
            select(
                Enrolment.institution_id,
                func.count(),
                func.sum(
                    case(
                        (
                            (Enrolment.created_at >= window_start)
                            & (Enrolment.created_at <= calendar.reporting_deadline),
                            1,
                        ),
                        else_=0,
                    )
                ),
            )
            .where(Enrolment.academic_year == year)
            .group_by(Enrolment.institution_id)
        ).all()

        for institution_id, total, in_window in rows:
            total = int(total or 0)
            in_window = int(in_window or 0)
            if total == 0 or in_window == 0:
                continue
            share = in_window / total * 100.0
            if share < share_threshold:
                continue

            dedupe_key = f"institution:{institution_id}:{year}:LAST_MINUTE_BULK"
            keep.add(dedupe_key)
            severity = "high" if share >= 60 else "medium"
            _flag, was_created = upsert_flag(
                db,
                type="LAST_MINUTE_BULK",
                dedupe_key=dedupe_key,
                severity=severity,
                title=f"{share:.0f}% of records filed in the last {window_hours:g} hours",
                explanation=(
                    f"{_institution_name(db, institution_id)} created {in_window} of its {total} "
                    f"{year} records ({share:.1f}%) within {window_hours:g} hours of the reporting "
                    f"deadline ({calendar.reporting_deadline.isoformat()}). Data entered in one "
                    "late burst is more likely to be bulk-generated than collected as students "
                    "were admitted."
                ),
                evidence={
                    "records_in_window": in_window,
                    "total_records": total,
                    "share_percent": round(share, 2),
                    "window_hours": window_hours,
                    "deadline": calendar.reporting_deadline.isoformat(),
                    "threshold_percent": share_threshold,
                    "academic_year": year,
                },
                institution_id=institution_id,
                academic_year=year,
            )
            created += int(was_created)
            updated += int(not was_created)

    closed = resolve_stale_flags(db, type="LAST_MINUTE_BULK", keep_keys=keep)
    db.flush()
    return {
        "last_minute_bulk": created,
        "last_minute_bulk_updated": updated,
        "last_minute_bulk_closed": closed,
    }


# --------------------------------------------------------------------------- progression


def detect_phantom_progression(db: Session) -> dict[str, int]:
    """Year-2 students with no year-1 record, and students who vanish with no exit status."""
    years = list(known_academic_years())
    if len(years) < 2:
        return {"phantom_progression": 0, "phantom_progression_updated": 0, "phantom_progression_closed": 0}

    created = 0
    updated = 0
    keep: set[str] = set()

    for previous_year, year in zip(years, years[1:]):
        # (a) year-2 regular students with no record in the previous year.
        current_rows = db.execute(
            select(Enrolment, Program)
            .join(Program, Program.id == Enrolment.program_id)
            .where(
                Enrolment.academic_year == year,
                Enrolment.year_of_study == 2,
                Enrolment.admission_type == "regular",  # lateral entrants legitimately start here
                Enrolment.status.in_(ACTIVE_ENROLMENT_STATUSES),
            )
        ).all()

        previous_students = {
            student_id
            for student_id in db.execute(
                select(Enrolment.student_id).where(Enrolment.academic_year == previous_year).distinct()
            ).scalars()
        }

        for enrolment, program in current_rows:
            if enrolment.student_id in previous_students:
                continue
            dedupe_key = f"student:{enrolment.student_id}:{year}:no_year1"
            keep.add(dedupe_key)
            student = db.get(Student, enrolment.student_id)
            _flag, was_created = upsert_flag(
                db,
                type="PHANTOM_PROGRESSION",
                dedupe_key=dedupe_key,
                severity="medium",
                title="Year-2 student with no first-year record",
                explanation=(
                    f"{student.apaar_masked if student else 'This student'} is reported in year 2 of "
                    f"{program.course} {program.branch} in {year}, but was never reported in "
                    f"{previous_year} and is not a lateral entrant. Either the first year was never "
                    "filed or the student does not exist."
                ),
                evidence={
                    "kind": "year2_without_year1",
                    "apaar_masked": student.apaar_masked if student else None,
                    "academic_year": year,
                    "previous_year": previous_year,
                    "program": f"{program.course} {program.branch}",
                    "admission_type": enrolment.admission_type,
                },
                institution_id=enrolment.institution_id,
                student_id=enrolment.student_id,
                enrolment_id=enrolment.id,
                academic_year=year,
            )
            created += int(was_created)
            updated += int(not was_created)

        # (b) students present last year who vanish this year with no exit status.
        previous_rows = db.execute(
            select(Enrolment)
            .where(
                Enrolment.academic_year == previous_year,
                Enrolment.status.in_(ACTIVE_ENROLMENT_STATUSES),
            )
        ).scalars()
        current_students = {
            student_id
            for student_id in db.execute(
                select(Enrolment.student_id).where(Enrolment.academic_year == year).distinct()
            ).scalars()
        }

        for enrolment in previous_rows:
            if enrolment.student_id in current_students:
                continue
            if enrolment.status != "admitted":
                continue  # completed / cancelled / migrated / dropped is a proper exit
            # A final-year student finishing is not a phantom; we only know year_of_study.
            dedupe_key = f"student:{enrolment.student_id}:{previous_year}:vanished"
            keep.add(dedupe_key)
            student = db.get(Student, enrolment.student_id)
            _flag, was_created = upsert_flag(
                db,
                type="PHANTOM_PROGRESSION",
                dedupe_key=dedupe_key,
                severity="medium",
                title="Student disappeared without an exit status",
                explanation=(
                    f"{student.apaar_masked if student else 'This student'} was reported as admitted "
                    f"in {previous_year} but appears nowhere in {year}, and was never marked "
                    "cancelled, migrated, dropped or completed. A student who leaves must be "
                    "reported with a status."
                ),
                evidence={
                    "kind": "vanished_without_status",
                    "apaar_masked": student.apaar_masked if student else None,
                    "previous_year": previous_year,
                    "academic_year": year,
                    "last_known_status": enrolment.status,
                    "last_known_year_of_study": enrolment.year_of_study,
                },
                institution_id=enrolment.institution_id,
                student_id=enrolment.student_id,
                enrolment_id=enrolment.id,
                academic_year=previous_year,
            )
            created += int(was_created)
            updated += int(not was_created)

    closed = resolve_stale_flags(db, type="PHANTOM_PROGRESSION", keep_keys=keep)
    db.flush()
    return {
        "phantom_progression": created,
        "phantom_progression_updated": updated,
        "phantom_progression_closed": closed,
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
    summary.update(detect_sequential_apaar(db, academic_year=academic_year))
    summary.update(detect_late_admissions(db, academic_year=academic_year))
    summary.update(detect_last_minute_bulk(db, academic_year=academic_year))
    summary.update(detect_phantom_progression(db))
    summary.update(detect_apaar_problems(db))
    return summary
