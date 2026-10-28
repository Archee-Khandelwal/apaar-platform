"""Reconciliation: confirm each submitted record against AICTE's own records (Phase 6).

For every active enrolment an institution reported, six checks:

=====================  ==============================================================
institution_approved   AICTE's approval record for that year (``institution_approvals``)
programme_approved     the programme's approved-intake record for that year is ``approved``
within_intake          the admission is inside approved intake (or inside its
                       supernumerary category's cap) — ranked by admission date
apaar_verified         the APAAR registry matched name and DOB (FN/OCI exempt)
documents_verified     every required document is verified
no_duplicate           no open cross-institution or identity duplicate
=====================  ==============================================================

Each check is ``pass``, ``review`` or ``fail`` with a plain-English explanation and, for
the institution, what to do about it. Overall: any fail -> Rejected, any review ->
Needs review, otherwise Confirmed.

Results are stored (``reconciliation``) and recomputed after every detector run, document
change and master-records import, so dashboards read a table instead of re-deriving it.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.core import (
    ApprovedIntake,
    Enrolment,
    Flag,
    Institution,
    InstitutionApproval,
    Program,
    Reconciliation,
    Student,
    StudentDocument,
)
from app.models.enums import ACTIVE_ENROLMENT_STATUSES, OPEN_FLAG_STATUSES
from app.services.flags import CROSS_INSTITUTION_NOTICE
from app.services.intake import entry_year, seat_matrix_from_counts
from app.services.rules import counts_within_intake, document_types, known_academic_years, required_documents

CHECKS = (
    ("institution_approved", "Institution approved by AICTE"),
    ("programme_approved", "Programme approved for the year"),
    ("within_intake", "Within approved intake"),
    ("apaar_verified", "APAAR verified (name and DOB)"),
    ("documents_verified", "Documents verified"),
    ("no_duplicate", "No duplicate enrolment"),
)
CHECK_LABELS = dict(CHECKS)
OVERALL_LABELS = {"confirmed": "Confirmed", "needs_review": "Needs review", "rejected": "Rejected"}
VERIFIED_DOCUMENT = ("auto_verified", "verified")


def _check(result: str, message: str, fix: str | None = None, **detail: Any) -> dict[str, Any]:
    return {"result": result, "message": message, "fix": fix, **detail}


def overall_of(checks: dict[str, dict[str, Any]]) -> str:
    results = {check["result"] for check in checks.values()}
    if "fail" in results:
        return "rejected"
    if "review" in results:
        return "needs_review"
    return "confirmed"


@dataclass
class _Row:
    enrolment: Enrolment
    student: Student
    program: Program


# --------------------------------------------------------------------------- the checks


def _institution_check(status: str | None, year: str, is_entry: bool, name: str) -> dict[str, Any]:
    if status == "approved":
        return _check("pass", f"{name} holds AICTE approval for {year}.")
    if status == "no_admission" and not is_entry:
        return _check("pass", f"{name} may not admit new students in {year}, but this is a continuing student.")
    if status == "no_admission":
        return _check(
            "fail",
            f"AICTE's record shows {name} was not permitted fresh admissions in {year}, yet this student was admitted that year.",
            f"These admissions cannot be confirmed. Contact AICTE about the {year} approval.",
        )
    return _check(
        "fail",
        f"AICTE has no approval on record for {name} in {year}.",
        "Contact AICTE: without approval for the year no admission can be confirmed.",
    )


def _programme_check(intake: ApprovedIntake | None, program: Program, year: str, is_entry: bool) -> dict[str, Any]:
    label = f"{program.course} {program.branch}"
    if intake is not None and intake.status == "approved":
        return _check("pass", f"{label} is approved for {year} with an intake of {intake.intake}.")
    if intake is not None and intake.status == "withdrawn" and not is_entry:
        return _check("pass", f"{label} is closed to fresh admissions in {year}; this is a continuing student.")
    reason = "was withdrawn (closed for fresh admission)" if intake is not None else "has no approval on record"
    return _check(
        "fail",
        f"{label} {reason} for {year} in AICTE's records.",
        "Move the student to an approved programme, or cancel the admission.",
    )


def _apaar_check(student: Student) -> dict[str, Any]:
    if student.apaar_status == "not_applicable":
        if student.nationality_status in ("fn", "oci"):
            return _check("pass", "No APAAR ID: valid for a foreign national / OCI student.")
        return _check("fail", "No APAAR ID, but the student is not FN/OCI.", "Add the student's APAAR ID and re-upload.")
    status = student.registry_status
    if status == "match":
        return _check("pass", f"{student.apaar_masked} matched the APAAR registry on name and date of birth.")
    if status == "invalid_format":
        return _check("fail", f"{student.apaar_masked} is not a valid 12-digit APAAR ID.", "Correct the APAAR ID and re-upload the record.")
    if status == "not_found":
        return _check("fail", f"The APAAR registry has no record of {student.apaar_masked}.", "Check the APAAR ID with the student and re-upload.")
    if status == "mismatch":
        return _check(
            "review",
            "The name or date of birth reported differs from the APAAR registry.",
            "Correct the reported name/DOB, or ask the student to update their APAAR record.",
        )
    return _check(
        "review",
        "The APAAR ID has not been checked against the registry yet (pending, or the registry was unavailable).",
        "Nothing to do now: it is re-checked automatically.",
    )


def _documents_check(required: list[str], held: dict[str, StudentDocument]) -> dict[str, Any]:
    labels = {key: value.get("label", key) for key, value in document_types().items()}
    missing = [doc_type for doc_type in required if doc_type not in held]
    rejected = [doc_type for doc_type in required if doc_type in held and held[doc_type].verification_status == "rejected"]
    waiting = [doc_type for doc_type in required if doc_type in held and held[doc_type].verification_status not in VERIFIED_DOCUMENT + ("rejected",)]
    detail = {"required": len(required), "missing": missing, "rejected": rejected, "waiting": waiting}
    if rejected:
        names = ", ".join(labels.get(item, item) for item in rejected)
        return _check("fail", f"Rejected: {names}.", f"Replace the rejected {names.lower()}.", **detail)
    if missing:
        names = ", ".join(labels.get(item, item) for item in missing)
        return _check("review", f"Not yet submitted: {names}.", f"Upload: {names}.", **detail)
    if waiting:
        names = ", ".join(labels.get(item, item) for item in waiting)
        return _check("review", f"Awaiting AICTE officer review: {names}.", "Nothing to do: an AICTE officer is reviewing.", **detail)
    return _check("pass", f"All {len(required)} required documents are verified.", **detail)


def _duplicate_check(student_id: int, fraud: set[int], dual: set[int]) -> dict[str, Any]:
    if student_id in fraud:
        return _check(
            "fail",
            "An open duplicate-enrolment finding involves this student.",
            CROSS_INSTITUTION_NOTICE,
        )
    if student_id in dual:
        return _check("pass", "Also enrolled elsewhere in an online/ODL programme: a legal dual degree.")
    return _check("pass", "No duplicate enrolment found.")


# --------------------------------------------------------------------------- ranking


def beyond_intake(rows: list[_Row], intakes: dict[tuple[int, str], ApprovedIntake]) -> dict[int, str]:
    """Enrolment ids that fall past approved intake (or their category's cap), each with
    the sentence that explains it. The latest admissions are the ones past the line."""
    groups: dict[tuple[int, str], list[_Row]] = defaultdict(list)
    for row in rows:
        groups[(row.program.id, row.enrolment.academic_year)].append(row)

    within = set(counts_within_intake())
    outside: dict[int, str] = {}
    for (program_id, year), members in groups.items():
        record = intakes.get((program_id, year))
        intake = record.intake if record else 0
        counts: dict[tuple[str, int], int] = defaultdict(int)
        for row in members:
            counts[(row.enrolment.admission_type, row.enrolment.year_of_study)] += 1
        matrix = seat_matrix_from_counts(program=members[0].program, academic_year=year, intake=intake, counts=counts)

        def order(row: _Row) -> tuple[date, int]:
            return (row.enrolment.admitted_on or date.max, row.enrolment.id)

        if matrix.regular_excess:
            regular = sorted((row for row in members if row.enrolment.admission_type in within and row.enrolment.year_of_study == 1), key=order)
            for position, row in enumerate(regular[intake:], start=intake + 1):
                outside[row.enrolment.id] = (
                    f"Admission {position} of {len(regular)} regular admissions against {intake} approved seats "
                    f"in {matrix.course} {matrix.branch}, {year}."
                )
        for bucket in matrix.buckets:
            if not bucket.excess:
                continue
            entrants = sorted(
                (row for row in members if row.enrolment.admission_type == bucket.admission_type
                 and row.enrolment.year_of_study == entry_year(bucket.admission_type)),
                key=order,
            )
            for position, row in enumerate(entrants[bucket.cap:], start=bucket.cap + 1):
                outside[row.enrolment.id] = (
                    f"{bucket.label} admission {position} of {len(entrants)} against a cap of {bucket.cap} "
                    f"in {matrix.course} {matrix.branch}, {year}."
                )
    return outside


# --------------------------------------------------------------------------- reconcile


def reconcile(
    db: Session,
    *,
    academic_year: str | None = None,
    institution_id: int | None = None,
    student_ids: set[int] | None = None,
) -> dict[str, int]:
    """Recompute and store results. Ranking needs whole programmes, so a student-scoped
    run still loads the programmes those students are in."""
    years = [academic_year] if academic_year else list(known_academic_years())
    conditions = [Enrolment.academic_year.in_(years), Enrolment.status.in_(ACTIVE_ENROLMENT_STATUSES)]
    if institution_id is not None:
        conditions.append(Enrolment.institution_id == institution_id)
    if student_ids is not None:
        programs = {
            program_id
            for (program_id,) in db.execute(
                select(Enrolment.program_id).where(Enrolment.student_id.in_(student_ids or {-1}), Enrolment.academic_year.in_(years))
            ).all()
        }
        conditions.append(Enrolment.program_id.in_(programs or {-1}))

    rows = [
        _Row(enrolment, student, program)
        for enrolment, student, program in db.execute(
            select(Enrolment, Student, Program)
            .join(Student, Student.id == Enrolment.student_id)
            .join(Program, Program.id == Enrolment.program_id)
            .where(*conditions)
        ).all()
    ]
    institutions = {row.id: row for row in db.execute(select(Institution)).scalars()}
    approvals = {
        (row.institution_id, row.academic_year): row.status
        for row in db.execute(select(InstitutionApproval).where(InstitutionApproval.academic_year.in_(years))).scalars()
    }
    intakes = {
        (row.program_id, row.academic_year): row
        for row in db.execute(select(ApprovedIntake).where(ApprovedIntake.academic_year.in_(years))).scalars()
    }
    fraud: set[int] = set()
    dual: set[int] = set()
    for flag in db.execute(
        select(Flag).where(
            Flag.type.in_(("CROSS_INSTITUTION_DUPLICATE", "IDENTITY_DUPLICATE", "POSSIBLE_DUAL_DEGREE")),
            Flag.status.in_(OPEN_FLAG_STATUSES),
        )
    ).scalars():
        if flag.student_id is None:
            continue
        (dual if flag.type == "POSSIBLE_DUAL_DEGREE" else fraud).add(flag.student_id)
        for other in (flag.evidence or {}).get("student_ids", []) or []:
            if flag.type == "IDENTITY_DUPLICATE":
                fraud.add(int(other))

    wanted_students = {row.student.id for row in rows}
    documents: dict[tuple[int, int], dict[str, StudentDocument]] = defaultdict(dict)
    for document in db.execute(
        select(StudentDocument).where(StudentDocument.is_current.is_(True))
    ).scalars():
        if document.student_id in wanted_students:
            documents[(document.student_id, document.institution_id)][document.doc_type] = document

    outside = beyond_intake(rows, intakes)

    targets = rows if student_ids is None else [row for row in rows if row.student.id in student_ids]
    ids = [row.enrolment.id for row in targets]
    for start in range(0, len(ids), 900):
        db.execute(delete(Reconciliation).where(Reconciliation.enrolment_id.in_(ids[start : start + 900])))

    now = datetime.utcnow()
    tallies = {"confirmed": 0, "needs_review": 0, "rejected": 0}
    results = []
    for row in targets:
        enrolment, student, program = row.enrolment, row.student, row.program
        institution = institutions[enrolment.institution_id]
        year = enrolment.academic_year
        is_entry = enrolment.year_of_study == 1 or (enrolment.admission_type == "lateral" and enrolment.year_of_study == 2)
        within_check = (
            _check("fail", outside[enrolment.id], "Cancel this admission, or record the supernumerary category it was made under (within that category's cap).")
            if enrolment.id in outside
            else _check("pass", "Inside approved intake (supernumerary seats counted against their own caps).")
        )
        checks = {
            "institution_approved": _institution_check(approvals.get((institution.id, year)), year, is_entry, institution.name),
            "programme_approved": _programme_check(intakes.get((program.id, year)), program, year, is_entry),
            "within_intake": within_check,
            "apaar_verified": _apaar_check(student),
            "documents_verified": _documents_check(
                required_documents(
                    admission_type=enrolment.admission_type,
                    category=student.category,
                    nationality_status=student.nationality_status,
                ),
                documents.get((student.id, institution.id), {}),
            ),
            "no_duplicate": _duplicate_check(student.id, fraud, dual),
        }
        overall = overall_of(checks)
        tallies[overall] += 1
        results.append(
            {
                "enrolment_id": enrolment.id,
                "student_id": student.id,
                "institution_id": institution.id,
                "program_id": program.id,
                "academic_year": year,
                "overall": overall,
                "checks": checks,
                "computed_at": now,
            }
        )
    db.bulk_insert_mappings(Reconciliation, results)
    db.flush()
    return {f"reconciled_{key}": value for key, value in tallies.items()}


def reconcile_student(db: Session, student_id: int) -> None:
    reconcile(db, student_ids={student_id})
