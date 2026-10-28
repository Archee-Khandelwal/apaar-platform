"""Reads over the stored reconciliation results (Phase 6): the per-institution dashboard,
the drill-down list, one record's side-by-side page, the "Retrieve data" search and its CSV,
and the institution's own "what to fix" view.

Everything here returns masked identifiers only. Revealing a name or APAAR ID is the
officer's separate, reason-gated ``/aicte/reveal``.
"""
from __future__ import annotations

import csv
import io
from collections import Counter
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.core.crypto import hmac_hash
from app.models.core import (
    ApprovedIntake,
    Enrolment,
    Institution,
    InstitutionApproval,
    Program,
    Reconciliation,
    Student,
    StudentDocument,
)
from app.services.reconciliation import CHECK_LABELS, CHECKS, OVERALL_LABELS
from app.services.rules import document_types, required_documents

OVERALL = tuple(OVERALL_LABELS)  # confirmed, needs_review, rejected
REGISTRY_LABELS = {
    "match": "Matched the APAAR registry on name and date of birth",
    "mismatch": "Registry found the ID but name or date of birth differs",
    "not_found": "No such APAAR ID in the registry",
    "invalid_format": "Not a valid 12-digit APAAR ID",
    None: "Not checked yet",
}


def program_label(program: Program) -> str:
    suffix = " (online)" if program.mode == "online" else ""
    return f"{program.course} {program.branch}{suffix}"


# --------------------------------------------------------------------------- dashboard


def institution_summary(
    db: Session, *, academic_year: str, state: str | None = None, q: str | None = None
) -> dict[str, Any]:
    """Counts per status for every institution with records in the year."""
    stmt = (
        select(Reconciliation.institution_id, Reconciliation.overall, func.count())
        .where(Reconciliation.academic_year == academic_year)
        .group_by(Reconciliation.institution_id, Reconciliation.overall)
    )
    counts: dict[int, dict[str, int]] = {}
    for institution_id, overall, count in db.execute(stmt).all():
        counts.setdefault(institution_id, dict.fromkeys(OVERALL, 0))[overall] = count

    names = select(Institution).where(Institution.id.in_(counts or {-1}))
    if state:
        names = names.where(Institution.state == state)
    if q:
        names = names.where(Institution.name.ilike(f"%{q.strip()}%"))
    items = []
    totals = dict.fromkeys(OVERALL, 0)
    for institution in db.execute(names.order_by(Institution.name)).scalars():
        row = counts[institution.id]
        for key in OVERALL:
            totals[key] += row[key]
        items.append(
            {
                "institution_id": institution.id,
                "name": institution.name,
                "state": institution.state,
                "aicte_permanent_id": institution.aicte_permanent_id,
                "records": sum(row.values()),
                **row,
            }
        )
    items.sort(key=lambda item: (-(item["rejected"] + item["needs_review"]), item["name"]))
    return {"academic_year": academic_year, "totals": {**totals, "records": sum(totals.values())}, "items": items}


# --------------------------------------------------------------------------- record lists


def _problems(checks: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"check": key, "label": CHECK_LABELS[key], "result": checks[key]["result"],
         "message": checks[key]["message"], "fix": checks[key].get("fix")}
        for key, _ in CHECKS
        if key in checks and checks[key]["result"] != "pass"
    ]


def records_statement(
    *,
    institution_id: int | None = None,
    program_id: int | None = None,
    academic_year: str | None = None,
    overall: str | None = None,
    failing_check: str | None = None,
    q: str | None = None,
) -> Select:
    stmt = (
        select(Reconciliation, Student, Enrolment, Program, Institution)
        .join(Student, Student.id == Reconciliation.student_id)
        .join(Enrolment, Enrolment.id == Reconciliation.enrolment_id)
        .join(Program, Program.id == Reconciliation.program_id)
        .join(Institution, Institution.id == Reconciliation.institution_id)
    )
    if institution_id is not None:
        stmt = stmt.where(Reconciliation.institution_id == institution_id)
    if program_id is not None:
        stmt = stmt.where(Reconciliation.program_id == program_id)
    if academic_year:
        stmt = stmt.where(Reconciliation.academic_year == academic_year)
    if overall:
        stmt = stmt.where(Reconciliation.overall == overall)
    if q:
        text = q.strip()
        digits = "".join(ch for ch in text if ch.isdigit())
        if len(digits) == 12:  # a full APAAR ID is matched on its HMAC, never stored or compared raw
            stmt = stmt.where(Student.apaar_hash == hmac_hash(digits))
        elif text.isdigit():
            stmt = stmt.where(Student.apaar_masked.like(f"%{text}"))
        else:
            stmt = stmt.where(Student.name_masked.ilike(f"%{text}%"))
    # failing_check is applied in Python by the callers (the checks are a JSON column).
    return stmt.order_by(Institution.name, Program.branch, Reconciliation.enrolment_id)


def programme_options(db: Session, institution_id: int) -> list[dict[str, Any]]:
    programs = db.execute(select(Program).where(Program.institution_id == institution_id).order_by(Program.course, Program.branch)).scalars()
    return [{"program_id": program.id, "label": program_label(program)} for program in programs]


def _row(record: Reconciliation, student: Student, enrolment: Enrolment, program: Program,
         institution: Institution) -> dict[str, Any]:
    return {
        "enrolment_id": enrolment.id,
        "student_id": student.id,
        "apaar_masked": student.apaar_masked,
        "name_masked": student.name_masked,
        "institution_id": institution.id,
        "institution_name": institution.name,
        "program_id": program.id,
        "programme": program_label(program),
        "academic_year": record.academic_year,
        "year_of_study": enrolment.year_of_study,
        "admission_type": enrolment.admission_type,
        "overall": record.overall,
        "problems": _problems(record.checks or {}),
    }


def list_records(
    db: Session, *, offset: int, limit: int, failing_check: str | None = None, **filters: Any
) -> tuple[list[dict[str, Any]], int]:
    stmt = records_statement(**filters)
    if failing_check is None:
        total = db.execute(select(func.count()).select_from(stmt.order_by(None).subquery())).scalar_one()
        rows = db.execute(stmt.offset(offset).limit(limit)).all()
        return [_row(*row) for row in rows], total
    matching = [
        row for row in db.execute(stmt).all()
        if (row[0].checks or {}).get(failing_check, {}).get("result") in ("review", "fail")
    ]
    return [_row(*row) for row in matching[offset : offset + limit]], len(matching)


def confirmed_csv(db: Session, **filters: Any) -> str:
    """Confirmed records only, masked. Cells that a spreadsheet would run as a formula are
    prefixed so an institution name cannot become one."""
    filters["overall"] = "confirmed"
    filters.pop("failing_check", None)
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow([
        "record_id", "apaar_masked", "name_masked", "institution", "aicte_permanent_id", "state", "programme",
        "level", "mode", "academic_year", "year_of_study", "admission_type", "category", "nationality_status",
        "reconciled_at",
    ])

    def safe(value: Any) -> Any:
        return "'" + value if isinstance(value, str) and value[:1] in ("=", "+", "-", "@") else value

    for record, student, enrolment, program, institution in db.execute(records_statement(**filters)).all():
        writer.writerow([safe(cell) for cell in [
            enrolment.id, student.apaar_masked, student.name_masked, institution.name, institution.aicte_permanent_id,
            institution.state, f"{program.course} {program.branch}", program.level, program.mode, record.academic_year,
            enrolment.year_of_study, enrolment.admission_type, student.category or "", student.nationality_status,
            record.computed_at.isoformat(timespec="seconds"),
        ]])
    return out.getvalue()


# --------------------------------------------------------------------------- one record


def record_detail(db: Session, enrolment_id: int) -> dict[str, Any] | None:
    found = db.execute(records_statement().where(Reconciliation.enrolment_id == enrolment_id)).first()
    if found is None:
        return None
    record, student, enrolment, program, institution = found
    year = record.academic_year
    approval = db.execute(
        select(InstitutionApproval).where(
            InstitutionApproval.institution_id == institution.id, InstitutionApproval.academic_year == year
        )
    ).scalar_one_or_none()
    intake = db.execute(
        select(ApprovedIntake).where(ApprovedIntake.program_id == program.id, ApprovedIntake.academic_year == year)
    ).scalar_one_or_none()

    labels = {key: value.get("label", key) for key, value in document_types().items()}
    held = {
        document.doc_type: document
        for document in db.execute(
            select(StudentDocument).where(
                StudentDocument.student_id == student.id,
                StudentDocument.institution_id == institution.id,
                StudentDocument.is_current.is_(True),
            )
        ).scalars()
    }
    required = required_documents(
        admission_type=enrolment.admission_type, category=student.category, nationality_status=student.nationality_status
    )
    documents = [
        {
            "doc_type": doc_type,
            "label": labels.get(doc_type, doc_type),
            "status": held[doc_type].verification_status if doc_type in held else "missing",
            "issuer_status": held[doc_type].issuer_status if doc_type in held else None,
            "document_id": held[doc_type].id if doc_type in held else None,
        }
        for doc_type in required
    ]
    checks = record.checks or {}
    return {
        **_row(record, student, enrolment, program, institution),
        "submitted": {
            "gender": student.gender,
            "category": student.category,
            "nationality_status": student.nationality_status,
            "dob_year": student.dob_year,
            "is_minor": student.is_minor,
            "level": program.level,
            "mode": program.mode,
            "enrolment_status": enrolment.status,
            "admitted_on": enrolment.admitted_on,
            "state": institution.state,
            "aicte_permanent_id": institution.aicte_permanent_id,
        },
        "apaar": {
            "apaar_status": student.apaar_status,
            "registry_status": student.registry_status,
            "result": REGISTRY_LABELS.get(student.registry_status, REGISTRY_LABELS[None]),
        },
        "master": {
            "institution_status": approval.status if approval else None,
            "institution_reference": approval.reference if approval else None,
            "programme_status": intake.status if intake else None,
            "approved_intake": intake.intake if intake else None,
            "supernumerary_caps": intake.supernumerary_caps if intake else {},
        },
        "documents": documents,
        "checks": [
            {"check": key, "label": label, **checks[key]} for key, label in CHECKS if key in checks
        ],
        "computed_at": record.computed_at,
    }


# --------------------------------------------------------------------------- institution


def institution_view(db: Session, *, institution_id: int, academic_year: str) -> dict[str, Any]:
    """Status counts and a grouped "what to fix" list for one institution."""
    rows = db.execute(
        select(Reconciliation).where(
            Reconciliation.institution_id == institution_id, Reconciliation.academic_year == academic_year
        )
    ).scalars().all()
    counts = Counter(row.overall for row in rows)
    to_fix: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        for problem in _problems(row.checks or {}):
            key = (problem["check"], problem["fix"] or "")
            entry = to_fix.setdefault(
                key,
                {"check": problem["check"], "label": problem["label"], "result": problem["result"],
                 "fix": problem["fix"], "example": problem["message"], "records": 0},
            )
            entry["records"] += 1
            if problem["result"] == "fail":
                entry["result"] = "fail"
    ordered = sorted(to_fix.values(), key=lambda item: (item["result"] != "fail", -item["records"]))
    return {
        "academic_year": academic_year,
        "counts": {key: counts.get(key, 0) for key in OVERALL},
        "records": len(rows),
        "to_fix": ordered,
    }
