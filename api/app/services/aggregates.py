"""National aggregates, institution profiles, non-reporting and trends (Step 12).

Everything here is counted from student-level records — which is the whole point of the
platform: AICTE currently receives totals it cannot drill into.
"""
from __future__ import annotations

import csv
import io
from collections import Counter
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.core import (
    ApprovedIntake,
    Enrolment,
    Flag,
    Institution,
    InstitutionRisk,
    Program,
    ReminderLog,
    Student,
    Upload,
)
from app.models.enums import ACTIVE_ENROLMENT_STATUSES, OPEN_FLAG_STATUSES


def _severity_counts(rows: list[str]) -> dict[str, int]:
    counts = Counter(rows)
    return {severity: counts.get(severity, 0) for severity in ("low", "medium", "high", "critical")}


def national_overview(db: Session, *, academic_year: str, state: str | None = None) -> dict[str, Any]:
    """KPIs plus a state-wise breakdown, all from student-level rows."""
    institution_filter = [Institution.state == state] if state else []

    institutions = list(db.execute(select(Institution).where(*institution_filter)).scalars())
    institution_ids = [institution.id for institution in institutions]
    if not institution_ids:
        institution_ids = [-1]

    reporting_ids = {
        row
        for row in db.execute(
            select(Enrolment.institution_id)
            .where(
                Enrolment.academic_year == academic_year,
                Enrolment.institution_id.in_(institution_ids),
            )
            .distinct()
        ).scalars()
    }

    students_reported = (
        db.scalar(
            select(func.count(func.distinct(Enrolment.student_id))).where(
                Enrolment.academic_year == academic_year,
                Enrolment.status.in_(ACTIVE_ENROLMENT_STATUSES),
                Enrolment.institution_id.in_(institution_ids),
            )
        )
        or 0
    )

    open_flags = list(
        db.execute(
            select(Flag.severity, Flag.type, Flag.institution_id).where(
                Flag.status.in_(OPEN_FLAG_STATUSES),
                Flag.institution_id.in_(institution_ids),
            )
        ).all()
    )
    flags_by_type = Counter(row[1] for row in open_flags)
    max_severity: dict[str, str] = {}
    from app.models.enums import SEVERITY_ORDER

    for severity, flag_type, _institution_id in open_flags:
        current = max_severity.get(flag_type)
        if current is None or SEVERITY_ORDER[severity] > SEVERITY_ORDER[current]:
            max_severity[flag_type] = severity

    excess_total = 0
    for flag in db.execute(
        select(Flag).where(
            Flag.type == "EXCESS_INTAKE",
            Flag.status.in_(OPEN_FLAG_STATUSES),
            Flag.academic_year == academic_year,
            Flag.institution_id.in_(institution_ids),
        )
    ).scalars():
        excess_total += int((flag.evidence or {}).get("excess", 0) or 0)

    quality = db.scalar(
        select(func.avg(Upload.quality_score)).where(
            Upload.quality_score.is_not(None), Upload.institution_id.in_(institution_ids)
        )
    )

    # ---- state-wise breakdown
    by_state: dict[str, dict[str, Any]] = {}
    for institution in institutions:
        bucket = by_state.setdefault(
            institution.state,
            {
                "state": institution.state,
                "institutions": 0,
                "institutions_reporting": 0,
                "students_reported": 0,
                "open_flags": 0,
                "excess_seats": 0,
                "avg_risk": 0.0,
            },
        )
        bucket["institutions"] += 1
        if institution.id in reporting_ids:
            bucket["institutions_reporting"] += 1

    student_rows = db.execute(
        select(Institution.state, func.count(func.distinct(Enrolment.student_id)))
        .join(Enrolment, Enrolment.institution_id == Institution.id)
        .where(
            Enrolment.academic_year == academic_year,
            Enrolment.status.in_(ACTIVE_ENROLMENT_STATUSES),
            Institution.id.in_(institution_ids),
        )
        .group_by(Institution.state)
    ).all()
    for state_name, count in student_rows:
        if state_name in by_state:
            by_state[state_name]["students_reported"] = int(count or 0)

    flag_rows = db.execute(
        select(Institution.state, func.count())
        .join(Flag, Flag.institution_id == Institution.id)
        .where(Flag.status.in_(OPEN_FLAG_STATUSES), Institution.id.in_(institution_ids))
        .group_by(Institution.state)
    ).all()
    for state_name, count in flag_rows:
        if state_name in by_state:
            by_state[state_name]["open_flags"] = int(count or 0)

    risk_rows = db.execute(
        select(Institution.state, func.avg(InstitutionRisk.score))
        .join(InstitutionRisk, InstitutionRisk.institution_id == Institution.id)
        .where(Institution.id.in_(institution_ids))
        .group_by(Institution.state)
    ).all()
    for state_name, average in risk_rows:
        if state_name in by_state:
            by_state[state_name]["avg_risk"] = round(float(average or 0.0), 1)

    states_by_id = {institution.id: institution.state for institution in institutions}
    for flag in db.execute(
        select(Flag).where(
            Flag.type == "EXCESS_INTAKE",
            Flag.status.in_(OPEN_FLAG_STATUSES),
            Flag.academic_year == academic_year,
            Flag.institution_id.in_(institution_ids),
        )
    ).scalars():
        state_name = states_by_id.get(flag.institution_id)
        if state_name in by_state:
            by_state[state_name]["excess_seats"] += int((flag.evidence or {}).get("excess", 0) or 0)

    return {
        "academic_year": academic_year,
        "kpis": {
            "institutions_total": len(institutions),
            "institutions_reporting": len(reporting_ids),
            "institutions_non_reporting": len(institutions) - len(reporting_ids),
            "students_reported": students_reported,
            "total_excess_seats": excess_total,
            "open_flags": _severity_counts([row[0] for row in open_flags]),
            "avg_data_quality": int(round(float(quality))) if quality is not None else None,
        },
        "flags_by_type": [
            {"type": flag_type, "count": count, "max_severity": max_severity.get(flag_type, "low")}
            for flag_type, count in sorted(flags_by_type.items(), key=lambda item: -item[1])
        ],
        "by_state": sorted(by_state.values(), key=lambda item: item["state"]),
        "generated_at": datetime.utcnow().replace(microsecond=0),
    }


def institution_rows(
    db: Session,
    *,
    academic_year: str,
    search: str | None = None,
    state: str | None = None,
    region: str | None = None,
    type_: str | None = None,
    risk_min: float | None = None,
    risk_max: float | None = None,
    reporting: str | None = None,
    has_flag_type: str | None = None,
) -> list[dict[str, Any]]:
    """One row per institution for the AICTE list view."""
    conditions = []
    if state:
        conditions.append(Institution.state == state)
    if region:
        conditions.append(Institution.region == region)
    if type_:
        conditions.append(Institution.type == type_)
    if search:
        pattern = f"%{search.strip()}%"
        conditions.append(
            Institution.name.ilike(pattern) | Institution.aicte_permanent_id.ilike(pattern)
        )

    institutions = list(db.execute(select(Institution).where(*conditions)).scalars())
    ids = [institution.id for institution in institutions] or [-1]

    students = {
        row[0]: int(row[1] or 0)
        for row in db.execute(
            select(Enrolment.institution_id, func.count(func.distinct(Enrolment.student_id)))
            .where(
                Enrolment.academic_year == academic_year,
                Enrolment.status.in_(ACTIVE_ENROLMENT_STATUSES),
                Enrolment.institution_id.in_(ids),
            )
            .group_by(Enrolment.institution_id)
        ).all()
    }
    last_upload = {
        row[0]: row[1]
        for row in db.execute(
            select(Upload.institution_id, func.max(Upload.created_at))
            .where(Upload.institution_id.in_(ids))
            .group_by(Upload.institution_id)
        ).all()
    }
    risk = {
        row.institution_id: row
        for row in db.execute(
            select(InstitutionRisk).where(InstitutionRisk.institution_id.in_(ids))
        ).scalars()
    }

    flags_by_institution: dict[int, list[Flag]] = {}
    for flag in db.execute(
        select(Flag).where(Flag.status.in_(OPEN_FLAG_STATUSES), Flag.institution_id.in_(ids))
    ).scalars():
        flags_by_institution.setdefault(flag.institution_id, []).append(flag)

    rows: list[dict[str, Any]] = []
    for institution in institutions:
        flags = flags_by_institution.get(institution.id, [])
        if has_flag_type and not any(flag.type == has_flag_type for flag in flags):
            continue
        risk_row = risk.get(institution.id)
        score = risk_row.score if risk_row else 0.0
        if risk_min is not None and score < risk_min:
            continue
        if risk_max is not None and score > risk_max:
            continue
        is_reporting = institution.id in students
        if reporting == "yes" and not is_reporting:
            continue
        if reporting == "no" and is_reporting:
            continue

        excess = sum(
            int((flag.evidence or {}).get("excess", 0) or 0)
            for flag in flags
            if flag.type == "EXCESS_INTAKE"
        )
        rows.append(
            {
                "id": institution.id,
                "aicte_permanent_id": institution.aicte_permanent_id,
                "name": institution.name,
                "state": institution.state,
                "region": institution.region,
                "type": institution.type,
                "students_reported": students.get(institution.id, 0),
                "risk_score": score,
                "risk_band": risk_row.band if risk_row else "low",
                "open_flags": _severity_counts([flag.severity for flag in flags]),
                "excess_seats": excess,
                "last_upload_at": last_upload.get(institution.id),
            }
        )
    return rows


def institution_profile(db: Session, *, institution_id: int, academic_year: str) -> dict[str, Any]:
    from app.services.intake import institution_seat_matrix

    institution = db.get(Institution, institution_id)
    if institution is None:
        raise LookupError("No such institution.")

    risk = db.execute(
        select(InstitutionRisk).where(InstitutionRisk.institution_id == institution_id)
    ).scalar_one_or_none()

    uploads = list(
        db.execute(
            select(Upload)
            .where(Upload.institution_id == institution_id)
            .order_by(Upload.created_at.desc())
        ).scalars()
    )
    matrix = institution_seat_matrix(db, institution_id=institution_id, academic_year=academic_year)

    return {
        "institution": {
            "id": institution.id,
            "aicte_permanent_id": institution.aicte_permanent_id,
            "name": institution.name,
            "state": institution.state,
            "region": institution.region,
            "type": institution.type,
        },
        "risk": {
            "score": risk.score if risk else 0.0,
            "band": risk.band if risk else "low",
            "reasons": (risk.reasons if risk else []) or [],
            "components": {
                "flags": risk.flag_component if risk else 0.0,
                "anomaly": risk.anomaly_component if risk else 0.0,
            },
        },
        "reporting": {
            "uploads": len(uploads),
            "last_upload_at": uploads[0].created_at if uploads else None,
            "students_reported": db.scalar(
                select(func.count(func.distinct(Enrolment.student_id))).where(
                    Enrolment.institution_id == institution_id,
                    Enrolment.academic_year == academic_year,
                    Enrolment.status.in_(ACTIVE_ENROLMENT_STATUSES),
                )
            )
            or 0,
            "avg_quality_score": int(
                round(
                    sum(upload.quality_score or 0 for upload in uploads if upload.quality_score)
                    / max(len([u for u in uploads if u.quality_score]), 1)
                )
            )
            if uploads
            else None,
        },
        "seat_matrix_summary": matrix["totals"],
        "upload_timeline": [
            {
                "upload_id": upload.id,
                "filename": upload.filename,
                "created_at": upload.created_at,
                "rows_ok": upload.rows_ok,
                "rows_error": upload.rows_error,
                "quality_score": upload.quality_score,
            }
            for upload in uploads[:20]
        ],
    }


def non_reporting(
    db: Session, *, academic_year: str, state: str | None = None
) -> list[dict[str, Any]]:
    """Institutions with no enrolment reported for the year."""
    from app.services.rules import year_calendar

    conditions = [Institution.state == state] if state else []
    institutions = list(db.execute(select(Institution).where(*conditions)).scalars())

    reported = {
        row
        for row in db.execute(
            select(Enrolment.institution_id)
            .where(Enrolment.academic_year == academic_year)
            .distinct()
        ).scalars()
    }
    reminders: dict[int, list[ReminderLog]] = {}
    for reminder in db.execute(
        select(ReminderLog).where(ReminderLog.academic_year == academic_year)
    ).scalars():
        reminders.setdefault(reminder.institution_id, []).append(reminder)

    try:
        deadline = year_calendar(academic_year).reporting_deadline
    except KeyError:  # pragma: no cover
        deadline = None
    now = datetime.utcnow()

    rows: list[dict[str, Any]] = []
    for institution in institutions:
        if institution.id in reported:
            continue
        sent = sorted(reminders.get(institution.id, []), key=lambda item: item.created_at)
        last_upload = db.scalar(
            select(func.max(Upload.created_at)).where(Upload.institution_id == institution.id)
        )
        rows.append(
            {
                "institution_id": institution.id,
                "name": institution.name,
                "state": institution.state,
                "last_upload_at": last_upload,
                "days_overdue": max((now - deadline).days, 0) if deadline else 0,
                # Before the deadline passes, "0 days overdue" is true but unhelpful.
                "days_to_deadline": max((deadline - now).days, 0) if deadline else None,
                "reporting_deadline": deadline,
                "reminders_sent": len(sent),
                "last_reminder_at": sent[-1].created_at if sent else None,
            }
        )
    return sorted(rows, key=lambda row: row["name"])


# --------------------------------------------------------------------------- trends

TREND_DIMENSIONS = ("state", "branch", "category", "gender", "year", "mode", "admission_type")


def trends(
    db: Session,
    *,
    dimension: str,
    academic_years: list[str],
    state: str | None = None,
    institution_id: int | None = None,
    new_admissions_only: bool = False,
) -> dict[str, Any]:
    """Enrolment trends on one dimension, across the given years.

    ``new_admissions_only`` counts year-1 entrants plus lateral entrants, which is the
    like-for-like comparison for admissions. Total enrolment is not comparable across
    years while the dataset is still filling up its senior years.
    """
    if dimension not in TREND_DIMENSIONS:
        raise ValueError(f"Unknown dimension {dimension!r}")

    key_column = {
        "state": Institution.state,
        "branch": Program.branch,
        "category": Student.category,
        "gender": Student.gender,
        "year": Enrolment.year_of_study,
        "mode": Program.mode,
        "admission_type": Enrolment.admission_type,
    }[dimension]

    conditions = [
        Enrolment.academic_year.in_(academic_years),
        Enrolment.status.in_(ACTIVE_ENROLMENT_STATUSES),
    ]
    if state:
        conditions.append(Institution.state == state)
    if institution_id is not None:
        conditions.append(Enrolment.institution_id == institution_id)
    if new_admissions_only:
        conditions.append(
            (Enrolment.year_of_study == 1) | (Enrolment.admission_type == "lateral")
        )

    rows = db.execute(
        select(key_column, Enrolment.academic_year, func.count(func.distinct(Enrolment.student_id)))
        .join(Program, Program.id == Enrolment.program_id)
        .join(Institution, Institution.id == Enrolment.institution_id)
        .join(Student, Student.id == Enrolment.student_id)
        .where(*conditions)
        .group_by(key_column, Enrolment.academic_year)
    ).all()

    series: dict[str, dict[str, int]] = {}
    for key, year, count in rows:
        label = str(key) if key is not None else "Not reported"
        series.setdefault(label, {})[year] = int(count or 0)

    ordered_years = sorted(academic_years)
    output = []
    for label, values in sorted(series.items()):
        first = values.get(ordered_years[0], 0) if ordered_years else 0
        last = values.get(ordered_years[-1], 0) if ordered_years else 0
        growth = round((last - first) / first * 100, 1) if first else None
        output.append(
            {
                "key": label,
                "values": {year: values.get(year, 0) for year in ordered_years},
                "yoy_growth_pct": growth,
            }
        )

    return {
        "dimension": dimension,
        "academic_years": ordered_years,
        "series": output,
        "notes": [
            "Counts are distinct students with an active enrolment "
            "(status admitted or completed).",
            (
                "New admissions only: year-1 entrants plus lateral entrants."
                if new_admissions_only
                else "Total enrolment across all years of study, so growth also reflects "
                "senior years filling up."
            ),
        ],
        "new_admissions_only": new_admissions_only,
    }


def trends_csv(payload: dict[str, Any]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    years = payload["academic_years"]
    writer.writerow([payload["dimension"], *years, "yoy_growth_pct"])
    for row in payload["series"]:
        writer.writerow(
            [row["key"], *[row["values"].get(year, 0) for year in years], row["yoy_growth_pct"]]
        )
    return buffer.getvalue()
