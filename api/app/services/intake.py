"""Intake compliance engine (Step 7 of docs/PLAN.md).

Approved intake covers *regular* admissions only. Supernumerary categories (TFW, lateral
entry, FN/PIO/OCI, PMSSS, other approved) sit OUTSIDE approved intake, each capped by
``app/rules/intake_rules.yaml``. Excess is therefore:

    excess = max(regular_admitted - approved_intake, 0)
           + sum over supernumerary buckets of max(admitted - cap, 0)

Lateral entrants join in year 2 and are never counted against year-1 intake; their cap
may also absorb seats left vacant in year 1 when the rule set says so.

Every computation returns a step-by-step explanation, which becomes the EXCESS_INTAKE
flag's evidence — no unexplained flags (CLAUDE.md section 8).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.core import ApprovedIntake, Enrolment, Flag, Institution, Program
from app.models.enums import ACTIVE_ENROLMENT_STATUSES, SUPERNUMERARY_TYPES
from app.services.flags import resolve_stale_flags, upsert_flag
from app.services.rules import (
    counts_within_intake,
    excess_severity,
    lateral_adds_vacant_year1,
    rule_set_version,
    supernumerary_caps,
    supernumerary_rules,
)


@dataclass
class BucketResult:
    admission_type: str
    label: str
    admitted: int
    cap: int
    cap_basis: str
    valid: int
    excess: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "admission_type": self.admission_type,
            "label": self.label,
            "admitted": self.admitted,
            "cap": self.cap,
            "cap_basis": self.cap_basis,
            "valid": self.valid,
            "excess": self.excess,
        }


@dataclass
class SeatMatrix:
    program_id: int
    institution_id: int
    course: str
    branch: str
    mode: str
    academic_year: str
    approved_intake: int
    regular_admitted: int
    regular_excess: int
    buckets: list[BucketResult] = field(default_factory=list)
    rule_set: str = ""

    @property
    def supernumerary_admitted(self) -> int:
        return sum(bucket.admitted for bucket in self.buckets)

    @property
    def valid_supernumerary(self) -> int:
        return sum(bucket.valid for bucket in self.buckets)

    @property
    def supernumerary_excess(self) -> int:
        return sum(bucket.excess for bucket in self.buckets)

    @property
    def total_admitted(self) -> int:
        return self.regular_admitted + self.supernumerary_admitted

    @property
    def excess(self) -> int:
        return self.regular_excess + self.supernumerary_excess

    @property
    def vacant_regular_seats(self) -> int:
        return max(self.approved_intake - self.regular_admitted, 0)

    def explanation(self) -> str:
        """Plain-English arithmetic, in the order a human would check it."""
        parts = [
            f"{self.regular_admitted} regular admissions vs {self.approved_intake} approved intake"
        ]
        parts.append(
            f"{self.regular_excess} excess regular"
            if self.regular_excess
            else f"{self.vacant_regular_seats} seats vacant"
        )

        used = [bucket for bucket in self.buckets if bucket.admitted]
        if used:
            details = ", ".join(
                f"{bucket.label} {bucket.admitted}/{bucket.cap}"
                + (f" → {bucket.excess} excess" if bucket.excess else " ok")
                for bucket in used
            )
            parts.append(f"supernumerary: {details}")
        else:
            parts.append("no supernumerary admissions")

        parts.append(
            f"{self.valid_supernumerary} valid supernumerary"
            if self.valid_supernumerary
            else "no valid supernumerary seats used"
        )
        parts.append(f"total excess = {self.excess}")
        return ". ".join(parts) + "."

    def as_dict(self) -> dict[str, Any]:
        return {
            "program_id": self.program_id,
            "course": self.course,
            "branch": self.branch,
            "mode": self.mode,
            "academic_year": self.academic_year,
            "approved_intake": self.approved_intake,
            "regular_admitted": self.regular_admitted,
            "regular_excess": self.regular_excess,
            "supernumerary": [bucket.as_dict() for bucket in self.buckets],
            "total_admitted": self.total_admitted,
            "valid_supernumerary": self.valid_supernumerary,
            "supernumerary_excess": self.supernumerary_excess,
            "vacant_regular_seats": self.vacant_regular_seats,
            "excess": self.excess,
            "explanation": self.explanation(),
            "rule_set": self.rule_set,
        }


def _admission_counts(db: Session, program_id: int, academic_year: str) -> dict[tuple[str, int], int]:
    """Active admissions grouped by (admission_type, year_of_study)."""
    rows = db.execute(
        select(Enrolment.admission_type, Enrolment.year_of_study, func.count())
        .where(
            Enrolment.program_id == program_id,
            Enrolment.academic_year == academic_year,
            Enrolment.status.in_(ACTIVE_ENROLMENT_STATUSES),
        )
        .group_by(Enrolment.admission_type, Enrolment.year_of_study)
    ).all()
    return {(admission_type, year): count for admission_type, year, count in rows}


def compute_seat_matrix(
    db: Session, *, program: Program, academic_year: str, intake: int | None = None
) -> SeatMatrix:
    """Seat matrix for one programme and year, with a step-by-step explanation."""
    if intake is None:
        row = db.execute(
            select(ApprovedIntake).where(
                ApprovedIntake.program_id == program.id,
                ApprovedIntake.academic_year == academic_year,
            )
        ).scalar_one_or_none()
        intake = row.intake if row else 0

    counts = _admission_counts(db, program.id, academic_year)
    within_intake = counts_within_intake()

    # Only year-1 entrants of an intake-counting type consume approved intake.
    regular_admitted = sum(
        count
        for (admission_type, year_of_study), count in counts.items()
        if admission_type in within_intake and year_of_study == 1
    )
    regular_excess = max(regular_admitted - intake, 0)

    caps = supernumerary_caps(intake)
    rules = supernumerary_rules()
    vacant_year1 = max(intake - regular_admitted, 0)

    buckets: list[BucketResult] = []
    for admission_type in SUPERNUMERARY_TYPES:
        rule = rules.get(admission_type, {})
        # A supernumerary seat is consumed in the year the student ENTERS on it, which
        # the rule file gives as applies_to_year (1 for TFW/FN/PMSSS, 2 for lateral).
        # Counting a continuing year-2 TFW student again would double-charge the cap.
        entry_year = int(rule.get("applies_to_year", 1))
        admitted = sum(
            count
            for (candidate_type, year_of_study), count in counts.items()
            if candidate_type == admission_type and year_of_study == entry_year
        )
        cap = caps.get(admission_type, 0)
        cap_percent = float(rule.get("cap_percent", 0.0))
        cap_basis = f"{cap_percent:g}% of approved intake (year {entry_year} entrants)"

        if admission_type == "lateral" and lateral_adds_vacant_year1():
            cap += vacant_year1
            cap_basis += " + seats left vacant in year 1"

        if admitted == 0 and cap == 0:
            continue
        valid = min(admitted, cap)
        buckets.append(
            BucketResult(
                admission_type=admission_type,
                label=str(rule.get("label", admission_type)),
                admitted=admitted,
                cap=cap,
                cap_basis=cap_basis,
                valid=valid,
                excess=max(admitted - cap, 0),
            )
        )

    return SeatMatrix(
        program_id=program.id,
        institution_id=program.institution_id,
        course=program.course,
        branch=program.branch,
        mode=program.mode,
        academic_year=academic_year,
        approved_intake=intake,
        regular_admitted=regular_admitted,
        regular_excess=regular_excess,
        buckets=buckets,
        rule_set=rule_set_version(),
    )


def institution_seat_matrix(
    db: Session, *, institution_id: int, academic_year: str
) -> dict[str, Any]:
    """Seat matrices for every programme at one institution, plus totals."""
    programs = list(
        db.execute(
            select(Program).where(Program.institution_id == institution_id).order_by(Program.id)
        ).scalars()
    )
    matrices = [
        compute_seat_matrix(db, program=program, academic_year=academic_year)
        for program in programs
    ]

    flags_by_program = {
        flag.program_id: flag.id
        for flag in db.execute(
            select(Flag).where(
                Flag.type == "EXCESS_INTAKE",
                Flag.institution_id == institution_id,
                Flag.academic_year == academic_year,
            )
        ).scalars()
    }

    payload = []
    for matrix in matrices:
        entry = matrix.as_dict()
        entry["flag_id"] = flags_by_program.get(matrix.program_id)
        payload.append(entry)

    return {
        "academic_year": academic_year,
        "rule_set": rule_set_version(),
        "programs": payload,
        "totals": {
            "approved_intake": sum(matrix.approved_intake for matrix in matrices),
            "regular_admitted": sum(matrix.regular_admitted for matrix in matrices),
            "valid_supernumerary": sum(matrix.valid_supernumerary for matrix in matrices),
            "total_admitted": sum(matrix.total_admitted for matrix in matrices),
            "excess": sum(matrix.excess for matrix in matrices),
        },
    }


def _title_for(matrix: SeatMatrix) -> str:
    return (
        f"Admissions exceed approved intake in {matrix.course} {matrix.branch} "
        f"({matrix.academic_year})"
    )


def run_intake_compliance(
    db: Session,
    *,
    institution_id: int | None = None,
    academic_year: str | None = None,
) -> dict[str, int]:
    """Recompute seat matrices and create/update EXCESS_INTAKE flags.

    Idempotent: re-running updates existing flags in place, and a programme that is no
    longer over intake has its open flag resolved automatically.
    """
    conditions = []
    if institution_id is not None:
        conditions.append(Program.institution_id == institution_id)

    statement = select(ApprovedIntake, Program).join(Program, Program.id == ApprovedIntake.program_id)
    if academic_year is not None:
        conditions.append(ApprovedIntake.academic_year == academic_year)
    if conditions:
        statement = statement.where(*conditions)

    created = 0
    updated = 0
    keep_keys: set[str] = set()

    for intake_row, program in db.execute(statement).all():
        matrix = compute_seat_matrix(
            db, program=program, academic_year=intake_row.academic_year, intake=intake_row.intake
        )
        if matrix.excess <= 0:
            continue

        dedupe_key = f"program:{program.id}:{intake_row.academic_year}"
        keep_keys.add(dedupe_key)
        causes = []
        if matrix.regular_excess:
            causes.append(f"{matrix.regular_excess} regular admissions beyond approved intake")
        for bucket in matrix.buckets:
            if bucket.excess:
                causes.append(
                    f"{bucket.excess} {bucket.label} admissions beyond its cap of {bucket.cap}"
                )

        _flag, was_created = upsert_flag(
            db,
            type="EXCESS_INTAKE",
            dedupe_key=dedupe_key,
            severity=excess_severity(matrix.excess, intake_row.intake),
            title=_title_for(matrix),
            explanation=matrix.explanation() + " Cause: " + "; ".join(causes) + ".",
            evidence=matrix.as_dict() | {"causes": causes},
            institution_id=program.institution_id,
            program_id=program.id,
            academic_year=intake_row.academic_year,
        )
        created += int(was_created)
        updated += int(not was_created)

    closed = resolve_stale_flags(
        db, type="EXCESS_INTAKE", keep_keys=keep_keys, institution_id=institution_id
    )
    db.flush()
    return {"excess_flags_created": created, "excess_flags_updated": updated, "excess_flags_closed": closed}
