"""The institution upload pipeline (Step 6 of docs/PLAN.md).

Flow: ``POST /institution/uploads`` parses the file and proposes a column mapping
(state ``pending_mapping``); ``POST .../confirm-mapping`` validates every row, checks the
APAAR registry in batches, stores the valid rows and returns a quality report.

Two guarantees worth calling out:

* **Nothing invalid is stored.** Rows with errors are reported with a fix suggestion.
* **Re-uploading is safe.** A row whose student already has an enrolment for the same
  programme and academic year is reported as ``already_reported`` and skipped, so the
  same file twice cannot create duplicate enrolments or inflate intake counts.
"""
from __future__ import annotations

import csv
import io
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import pandas as pd
from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import log_audit
from app.core.config import UPLOAD_DIR, settings
from app.core.crypto import (
    hash_email,
    hash_name,
    hash_phone,
    hmac_hash,
    is_minor,
    mask_apaar,
    mask_name,
    vault_encrypt,
)
from app.models.core import Enrolment, Institution, Program, Student, Upload, Vault
from app.services.flags import upsert_flag
from app.services.mapping import (
    CANONICAL_FIELDS,
    REQUIRED_FIELDS,
    propose_mapping,
    unmapped_required_fields,
)
from app.services.registry_client import RegistryClient, RegistryRecord
from app.services.rules import known_academic_years, year_calendar
from app.services.validation import ParsedRow, RowIssue, validate_row

MAX_ISSUES_IN_RESPONSE = 200
SAMPLE_VALUES = 3

# Common branch abbreviations, so "CSE" finds "Computer Science and Engineering".
BRANCH_ABBREVIATIONS: dict[str, str] = {
    "cse": "computer science and engineering",
    "cs": "computer science and engineering",
    "cse ai": "computer science and engineering",
    "it": "information technology",
    "ece": "electronics and communication engineering",
    "ec": "electronics and communication engineering",
    "eee": "electrical engineering",
    "ee": "electrical engineering",
    "me": "mechanical engineering",
    "mech": "mechanical engineering",
    "ce": "civil engineering",
    "civil": "civil engineering",
    "aids": "artificial intelligence and data science",
    "ai ds": "artificial intelligence and data science",
    "ai": "artificial intelligence and data science",
    "ds": "artificial intelligence and data science",
    "general": "general",
}

_PUNCT = re.compile(r"[^a-z0-9]+")


def _norm(text: str | None) -> str:
    return re.sub(r"\s+", " ", _PUNCT.sub(" ", (text or "").lower())).strip()


class UploadError(Exception):
    """Raised for a file we cannot read at all."""


# --------------------------------------------------------------------------- parsing


@dataclass
class ParseResult:
    headers: list[str]
    rows: list[dict[str, Any]]
    blank_rows_skipped: int
    sheet_name: str | None


def read_table(content: bytes, filename: str) -> ParseResult:
    """Read an Excel or CSV upload into rows, skipping fully blank rows."""
    name = (filename or "").lower()
    try:
        if name.endswith((".xlsx", ".xlsm", ".xls")):
            book = pd.read_excel(io.BytesIO(content), sheet_name=None, dtype=object)
            if not book:
                raise UploadError("The workbook has no sheets.")
            # Use the sheet with the most non-empty cells.
            sheet_name, frame = max(book.items(), key=lambda item: item[1].notna().sum().sum())
        elif name.endswith((".csv", ".txt", ".tsv")):
            separator = "\t" if name.endswith(".tsv") else None
            frame = pd.read_csv(
                io.BytesIO(content),
                dtype=object,
                sep=separator,
                engine="python",
                skip_blank_lines=True,
                # A ragged file still reaches the mapping screen, where it fails with a
                # clear "required fields are not mapped" message instead of a hard reject.
                on_bad_lines="skip",
            )
            sheet_name = None
        else:
            raise UploadError(
                "Unsupported file type. Upload .xlsx, .xls or .csv using the provided template."
            )
    except UploadError:
        raise
    except Exception as exc:  # pandas raises a zoo of exceptions on malformed files
        raise UploadError(f"The file could not be read ({type(exc).__name__}).") from exc

    if frame is None or frame.empty:
        return ParseResult(headers=[], rows=[], blank_rows_skipped=0, sheet_name=sheet_name)

    frame = frame.dropna(axis=1, how="all")
    before = len(frame)
    frame = frame.dropna(axis=0, how="all")
    blank_rows_skipped = before - len(frame)

    headers = [str(column) for column in frame.columns]
    rows: list[dict[str, Any]] = []
    for offset, (_, series) in enumerate(frame.iterrows(), start=2):  # row 1 is the header
        values = {str(column): series[column] for column in frame.columns}
        if all(
            value is None or (isinstance(value, float) and pd.isna(value)) or str(value).strip() == ""
            for value in values.values()
        ):
            blank_rows_skipped += 1
            continue
        values["__row__"] = offset
        rows.append(values)

    return ParseResult(
        headers=headers,
        rows=rows,
        blank_rows_skipped=blank_rows_skipped,
        sheet_name=str(sheet_name) if sheet_name is not None else None,
    )


def _samples(parse: ParseResult) -> dict[str, list[Any]]:
    out: dict[str, list[Any]] = {}
    for header in parse.headers:
        values: list[Any] = []
        for row in parse.rows:
            value = row.get(header)
            if value is None or str(value).strip() in ("", "nan"):
                continue
            values.append(value)
            if len(values) >= SAMPLE_VALUES:
                break
        out[header] = values
    return out


def _upload_path(upload_id: int, filename: str) -> Any:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", filename or "upload")[:80]
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    return UPLOAD_DIR / f"{upload_id}_{safe}"


# --------------------------------------------------------------------------- step 1


def create_upload(
    db: Session,
    *,
    institution_id: int,
    filename: str,
    content: bytes,
    academic_year: str | None,
    actor: str,
) -> dict[str, Any]:
    """Parse the file, store it, and propose a column mapping. Nothing is validated yet."""
    if len(content) > settings.max_upload_mb * 1024 * 1024:
        raise UploadError(f"File is larger than {settings.max_upload_mb} MB.")

    parse = read_table(content, filename)
    proposals = propose_mapping(parse.headers, _samples(parse))

    upload = Upload(
        institution_id=institution_id,
        filename=filename,
        state="pending_mapping",
        academic_year=academic_year,
        rows_total=len(parse.rows),
        blank_rows_skipped=parse.blank_rows_skipped,
        proposed_mapping=[proposal.as_dict() for proposal in proposals],
        column_mapping={},
        issues=[],
        registry_summary={},
        uploaded_by=actor,
    )
    db.add(upload)
    db.flush()

    path = _upload_path(upload.id, filename)
    path.write_bytes(content)
    upload.raw_path = str(path)

    log_audit(
        db,
        actor=actor,
        role="institution",
        action="upload_created",
        target=f"upload:{upload.id}",
        payload={
            "filename": filename,
            "rows_total": upload.rows_total,
            "institution_id": institution_id,
        },
    )
    db.flush()

    mapping = {proposal.source_column: proposal.field for proposal in proposals}
    return {
        "upload_id": upload.id,
        "filename": filename,
        "state": upload.state,
        "rows_total": upload.rows_total,
        "blank_rows_skipped": upload.blank_rows_skipped,
        "detected_sheet": parse.sheet_name,
        "proposed_mapping": upload.proposed_mapping,
        "unmapped_required_fields": unmapped_required_fields(mapping),
        "available_fields": list(CANONICAL_FIELDS),
    }


# --------------------------------------------------------------------------- step 2


@dataclass
class _Context:
    institution: Institution
    programs: list[Program]
    actor: str
    registry: RegistryClient
    existing_students_by_apaar: dict[str, Student] = field(default_factory=dict)
    existing_students_by_identity: dict[tuple, Student] = field(default_factory=dict)
    existing_enrolments: set[tuple] = field(default_factory=set)


def _load_context(db: Session, institution_id: int, actor: str, registry: RegistryClient) -> _Context:
    institution = db.get(Institution, institution_id)
    if institution is None:  # pragma: no cover - guarded by the router
        raise UploadError("Unknown institution.")
    programs = list(
        db.execute(select(Program).where(Program.institution_id == institution_id)).scalars()
    )
    return _Context(institution=institution, programs=programs, actor=actor, registry=registry)


def resolve_program(context: _Context, course: str | None, branch: str | None, mode: str | None) -> Program | None:
    """Match a reported course/branch to one of this institution's approved programmes."""
    if not course or not branch:
        return None
    course_norm = _norm(course)
    branch_norm = _norm(branch)
    branch_expanded = BRANCH_ABBREVIATIONS.get(branch_norm, branch_norm)

    best: tuple[float, Program] | None = None
    for program in context.programs:
        if _norm(program.course) != course_norm and fuzz.ratio(_norm(program.course), course_norm) < 85:
            continue
        if mode and program.mode != mode:
            continue
        candidate_branch = _norm(program.branch)
        score = max(
            fuzz.ratio(candidate_branch, branch_expanded),
            fuzz.partial_ratio(candidate_branch, branch_expanded),
        )
        # An online programme's branch carries "(Online/ODL)"; don't let that win by accident.
        if mode is None and program.mode == "online":
            score -= 10
        if score >= 80 and (best is None or score > best[0]):
            best = (score, program)
    return best[1] if best else None


def _identity_key(values: dict[str, Any]) -> tuple:
    return (
        hash_name(values.get("student_name")),
        hmac_hash(values["dob"].isoformat()) if values.get("dob") else None,
        hash_phone(values.get("guardian_phone")),
    )


def _load_existing(db: Session, context: _Context, parsed_rows: list[ParsedRow]) -> None:
    """Pre-load the students and enrolments this upload might already have reported."""
    apaar_hashes = {
        hmac_hash(row.values["apaar_id"])
        for row in parsed_rows
        if row.values.get("apaar_id")
    }
    identity_keys = {_identity_key(row.values) for row in parsed_rows}

    if apaar_hashes:
        for student in db.execute(
            select(Student).where(Student.apaar_hash.in_(apaar_hashes))
        ).scalars():
            context.existing_students_by_apaar[student.apaar_hash] = student

    name_hashes = {key[0] for key in identity_keys if key[0]}
    if name_hashes:
        for student in db.execute(
            select(Student).where(Student.name_hash.in_(name_hashes))
        ).scalars():
            context.existing_students_by_identity[
                (student.name_hash, student.dob_hash, student.guardian_phone_hash)
            ] = student

    student_ids = {
        student.id
        for student in list(context.existing_students_by_apaar.values())
        + list(context.existing_students_by_identity.values())
    }
    if student_ids:
        for enrolment in db.execute(
            select(Enrolment).where(
                Enrolment.institution_id == context.institution.id,
                Enrolment.student_id.in_(student_ids),
            )
        ).scalars():
            context.existing_enrolments.add(
                (enrolment.student_id, enrolment.program_id, enrolment.academic_year)
            )


def _find_student(context: _Context, values: dict[str, Any]) -> Student | None:
    apaar = values.get("apaar_id")
    if apaar:
        found = context.existing_students_by_apaar.get(hmac_hash(apaar))
        if found is not None:
            return found
    key = _identity_key(values)
    if all(part is not None for part in key):
        return context.existing_students_by_identity.get(key)
    return None


def confirm_mapping(
    db: Session,
    *,
    upload: Upload,
    mapping: dict[str, str | None],
    defaults: dict[str, Any] | None,
    actor: str,
    registry: RegistryClient | None = None,
) -> dict[str, Any]:
    """Validate every row, check the registry, store what is valid, and report."""
    if upload.raw_path is None:
        raise UploadError("The uploaded file is no longer available; please upload it again.")

    content = open(upload.raw_path, "rb").read()
    parse = read_table(content, upload.filename)
    defaults = {key: value for key, value in (defaults or {}).items() if value not in (None, "")}

    missing = unmapped_required_fields(mapping)
    missing = [field_name for field_name in missing if field_name not in defaults]
    if missing:
        raise UploadError(
            "These required fields are not mapped: " + ", ".join(missing)
        )

    upload.state = "validating"
    upload.column_mapping = {key: value for key, value in mapping.items()}
    db.flush()

    context = _load_context(db, upload.institution_id, actor, registry or RegistryClient())

    # ---------------------------------------------------------------- validate rows
    default_year = defaults.get("academic_year") or upload.academic_year
    calendars = {
        year: year_calendar(year) for year in known_academic_years()
    }
    parsed_rows: list[ParsedRow] = []
    for row in parse.rows:
        mapped: dict[str, Any] = {}
        for source_column, field_name in mapping.items():
            if field_name:
                mapped[field_name] = row.get(source_column)
        year_hint = mapped.get("academic_year") or default_year
        from app.services.validation import parse_academic_year

        normalised_year = parse_academic_year(year_hint) if year_hint else None
        parsed_rows.append(
            validate_row(
                int(row["__row__"]),
                mapped,
                calendar=calendars.get(normalised_year or ""),
                defaults=defaults,
            )
        )

    # ---------------------------------------------------------------- programme resolution
    for parsed in parsed_rows:
        if parsed.has_error:
            continue
        program = resolve_program(
            context,
            parsed.values.get("course"),
            parsed.values.get("branch"),
            parsed.values.get("program_mode"),
        )
        if program is None:
            parsed.issues.append(
                RowIssue(
                    parsed.row_number,
                    "error",
                    "UNKNOWN_PROGRAM",
                    "branch",
                    f"No approved programme matches "
                    f"{parsed.values.get('course')} / {parsed.values.get('branch')}.",
                )
            )
        else:
            parsed.values["program_id"] = program.id
            parsed.values["program_mode"] = program.mode

    # ---------------------------------------------------------------- duplicates in the file
    seen: dict[tuple, int] = {}
    for parsed in parsed_rows:
        if parsed.has_error:
            continue
        apaar = parsed.values.get("apaar_id")
        key = (
            ("apaar", hmac_hash(apaar))
            if apaar
            else ("identity", _identity_key(parsed.values))
        ) + (parsed.values.get("program_id"), parsed.values.get("academic_year"))
        first_row = seen.get(key)
        if first_row is not None:
            parsed.issues.append(
                RowIssue(
                    parsed.row_number,
                    "error",
                    "DUPLICATE_IN_UPLOAD",
                    "apaar_id",
                    f"This student also appears in row {first_row} of this file.",
                    value_masked=mask_apaar(apaar) if apaar else None,
                )
            )
        else:
            seen[key] = parsed.row_number

    # ---------------------------------------------------------------- registry batch check
    _load_existing(db, context, parsed_rows)

    checkable = [
        parsed
        for parsed in parsed_rows
        if not parsed.has_error and parsed.values.get("apaar_id") and parsed.values.get("dob")
    ]
    registry_summary: Counter[str] = Counter()
    if checkable:
        records = [
            RegistryRecord(
                apaar=parsed.values["apaar_id"],
                name=parsed.values.get("student_name"),
                dob=parsed.values["dob"].isoformat(),
                ref=str(parsed.row_number),
            )
            for parsed in checkable
        ]
        results = context.registry.verify_batch(records)
        by_row = {result.ref: result for result in results}
        for parsed in checkable:
            result = by_row.get(str(parsed.row_number))
            status = result.status if result else "source_unavailable"
            parsed.values["registry_status"] = status
            registry_summary[status] += 1
            if status == "not_found":
                parsed.issues.append(
                    RowIssue(
                        parsed.row_number,
                        "warning",
                        "APAAR_NOT_FOUND",
                        "apaar_id",
                        "The APAAR registry has no record of this ID.",
                        value_masked=mask_apaar(parsed.values["apaar_id"]),
                    )
                )
            elif status == "mismatch":
                parsed.issues.append(
                    RowIssue(
                        parsed.row_number,
                        "warning",
                        "APAAR_MISMATCH",
                        "student_name",
                        "Name or date of birth does not match the APAAR registry"
                        + (
                            f" (name similarity {result.name_similarity}%)."
                            if result and result.name_similarity is not None
                            else "."
                        ),
                        value_masked=mask_apaar(parsed.values["apaar_id"]),
                    )
                )
            elif status == "source_unavailable":
                parsed.issues.append(
                    RowIssue(
                        parsed.row_number,
                        "warning",
                        "REGISTRY_UNAVAILABLE",
                        "apaar_id",
                        "The APAAR registry could not be reached; row stored and marked for re-check.",
                    )
                )
    for parsed in parsed_rows:
        if not parsed.has_error and parsed.values.get("apaar_id") is None:
            parsed.values["registry_status"] = "skipped"
            registry_summary["skipped_no_apaar"] += 1

    # ---------------------------------------------------------------- persist
    stored = _persist_rows(db, context, parsed_rows, upload)

    # ---------------------------------------------------------------- report
    issues = [issue.as_dict() for parsed in parsed_rows for issue in parsed.issues]
    rows_error = sum(1 for parsed in parsed_rows if parsed.has_error)
    rows_warning = sum(1 for parsed in parsed_rows if not parsed.has_error and parsed.has_warning)
    rows_ok = len(parsed_rows) - rows_error

    upload.rows_total = len(parsed_rows)
    upload.rows_ok = rows_ok
    upload.rows_error = rows_error
    upload.rows_warning = rows_warning
    upload.blank_rows_skipped = parse.blank_rows_skipped
    upload.issues = issues
    upload.registry_summary = dict(registry_summary)
    upload.quality_score = compute_quality_score(
        rows_total=len(parsed_rows),
        rows_error=rows_error,
        rows_warning=rows_warning,
        mapping=mapping,
    )
    upload.state = "completed"
    db.flush()

    flags_created = _flags_for_upload(db, context, upload, parsed_rows, stored)

    # Recompute the seat matrix for this institution; a new upload can push a programme
    # past its approved intake (Step 7 item 3).
    from app.services.detectors import run_all_detectors

    run_all_detectors(db, institution_id=context.institution.id, commit=False)

    log_audit(
        db,
        actor=actor,
        role="institution",
        action="upload_confirmed",
        target=f"upload:{upload.id}",
        payload={
            "rows_total": upload.rows_total,
            "rows_ok": rows_ok,
            "rows_error": rows_error,
            "already_reported": stored["already_reported"],
            "enrolments_created": stored["enrolments_created"],
            "quality_score": upload.quality_score,
        },
    )
    db.flush()

    # Include any EXCESS_INTAKE flag raised or refreshed by this upload.
    from app.models.core import Flag as _Flag

    excess_flags = db.execute(
        select(_Flag).where(
            _Flag.type == "EXCESS_INTAKE",
            _Flag.institution_id == context.institution.id,
            _Flag.status.in_(("open", "under_review", "escalated")),
        )
    ).scalars()
    known = {entry["id"] for entry in flags_created}
    for flag in excess_flags:
        if flag.id not in known:
            flags_created.append({"id": flag.id, "type": flag.type, "severity": flag.severity})

    return quality_report(upload, flags_created=flags_created, stored=stored)


def _persist_rows(
    db: Session, context: _Context, parsed_rows: list[ParsedRow], upload: Upload
) -> dict[str, Any]:
    """Store valid rows. Skips anything already reported for this programme and year."""
    created_students = 0
    created_enrolments = 0
    already_reported = 0
    updated_students = 0

    for parsed in parsed_rows:
        if parsed.has_error:
            continue
        values = parsed.values
        program_id = values.get("program_id")
        academic_year = values.get("academic_year")
        if program_id is None or academic_year is None:  # pragma: no cover - guarded above
            continue

        student = _find_student(context, values)
        if student is None:
            student = _create_student(db, values)
            created_students += 1
            if student.apaar_hash:
                context.existing_students_by_apaar[student.apaar_hash] = student
            context.existing_students_by_identity[
                (student.name_hash, student.dob_hash, student.guardian_phone_hash)
            ] = student
        else:
            if values.get("registry_status") and student.registry_status != values["registry_status"]:
                student.registry_status = values["registry_status"]
                updated_students += 1

        key = (student.id, program_id, academic_year)
        if key in context.existing_enrolments:
            # Idempotency: the same row in a second upload must not create a second
            # enrolment or push the seat matrix up.
            already_reported += 1
            parsed.issues.append(
                RowIssue(
                    parsed.row_number,
                    "info",
                    "ALREADY_REPORTED",
                    None,
                    "This enrolment was already reported earlier, so the row was skipped.",
                    value_masked=student.apaar_masked,
                )
            )
            continue

        enrolment = Enrolment(
            student_id=student.id,
            program_id=program_id,
            institution_id=context.institution.id,
            academic_year=academic_year,
            year_of_study=values.get("year_of_study") or 1,
            admission_type=values.get("admission_type") or "regular",
            status=values.get("status") or "admitted",
            admitted_on=values.get("admission_date"),
            upload_id=upload.id,
            version=1,
            registry_status=values.get("registry_status"),
        )
        db.add(enrolment)
        db.flush()
        parsed.values["enrolment_id"] = enrolment.id
        parsed.values["student_id"] = student.id
        context.existing_enrolments.add(key)
        created_enrolments += 1

    db.flush()
    return {
        "students_created": created_students,
        "students_updated": updated_students,
        "enrolments_created": created_enrolments,
        "already_reported": already_reported,
    }


def _create_student(db: Session, values: dict[str, Any]) -> Student:
    """Create a student row (hashes + masks) and its vault row (raw identifiers)."""
    apaar = values.get("apaar_id")
    name = values.get("student_name")
    dob: date | None = values.get("dob")

    student = Student(
        apaar_hash=hmac_hash(apaar) if apaar else None,
        apaar_masked=mask_apaar(apaar) if apaar else "XXXX-XXXX-XXXX",
        apaar_status=values.get("apaar_status") or "provided",
        name_masked=mask_name(name),
        name_hash=hash_name(name),
        dob_hash=hmac_hash(dob.isoformat()) if dob else None,
        gender=values.get("gender"),
        category=values.get("category"),
        nationality_status=values.get("nationality_status") or "indian",
        dob_year=dob.year if dob else None,
        is_minor=is_minor(dob) if dob else False,
        phone_hash=hash_phone(values.get("phone")),
        email_hash=hash_email(values.get("email")),
        guardian_phone_hash=hash_phone(values.get("guardian_phone")),
        registry_status=values.get("registry_status"),
    )
    db.add(student)
    db.flush()
    db.add(
        Vault(
            student_id=student.id,
            apaar_enc=vault_encrypt(apaar) if apaar else None,
            name_enc=vault_encrypt(name),
            dob_enc=vault_encrypt(dob.isoformat()) if dob else None,
        )
    )
    db.flush()
    return student


def _flags_for_upload(
    db: Session,
    context: _Context,
    upload: Upload,
    parsed_rows: list[ParsedRow],
    stored: dict[str, Any],
) -> list[dict[str, Any]]:
    """Raise the flags this upload itself evidences. Seat matrix and cross-institution
    detectors run separately (Steps 7-10)."""
    created: list[dict[str, Any]] = []
    institution_id = context.institution.id
    by_code: dict[str, list[RowIssue]] = defaultdict(list)
    for parsed in parsed_rows:
        for issue in parsed.issues:
            by_code[issue.code].append(issue)

    # Aggregated, per-upload flags for rejected rows.
    for code, flag_type, severity, title in (
        ("INVALID_APAAR", "INVALID_APAAR", "medium", "Invalid APAAR IDs in upload"),
        ("DUPLICATE_IN_UPLOAD", "DUPLICATE_IN_UPLOAD", "medium", "Duplicate rows inside one upload"),
    ):
        issues = by_code.get(code) or []
        if not issues:
            continue
        rows = [issue.row for issue in issues][:50]
        flag, was_created = upsert_flag(
            db,
            type=flag_type,
            dedupe_key=f"upload:{upload.id}:{flag_type}",
            severity=severity,
            title=f"{title} ({len(issues)} rows)",
            explanation=(
                f"{len(issues)} row(s) in '{upload.filename}' were rejected: "
                f"{issues[0].message} Rejected rows are not stored, so this does not affect "
                f"enrolment counts."
            ),
            evidence={
                "upload_id": upload.id,
                "filename": upload.filename,
                "row_count": len(issues),
                "rows": rows,
                "example": issues[0].as_dict(),
            },
            institution_id=institution_id,
            academic_year=upload.academic_year,
        )
        created.append({"id": flag.id, "type": flag.type, "severity": flag.severity})

    # Per-student / per-enrolment flags for rows we did store.
    for parsed in parsed_rows:
        if parsed.has_error:
            continue
        student_id = parsed.values.get("student_id")
        enrolment_id = parsed.values.get("enrolment_id")
        if student_id is None:
            continue
        year = parsed.values.get("academic_year")

        for issue in parsed.issues:
            if issue.code == "APAAR_NOT_FOUND":
                flag, _ = upsert_flag(
                    db,
                    type="APAAR_NOT_FOUND",
                    dedupe_key=f"student:{student_id}:APAAR_NOT_FOUND",
                    severity="high",
                    title="APAAR ID not found in the registry",
                    explanation=(
                        f"APAAR {parsed.values.get('apaar_masked') or mask_apaar(parsed.values.get('apaar_id'))} "
                        "was reported by the institution but the APAAR registry has no record of it."
                    ),
                    evidence={
                        "apaar_masked": mask_apaar(parsed.values.get("apaar_id")),
                        "upload_id": upload.id,
                        "row": parsed.row_number,
                        "registry_status": "not_found",
                    },
                    institution_id=institution_id,
                    student_id=student_id,
                    enrolment_id=enrolment_id,
                    academic_year=year,
                )
                created.append({"id": flag.id, "type": flag.type, "severity": flag.severity})
            elif issue.code == "APAAR_MISMATCH":
                flag, _ = upsert_flag(
                    db,
                    type="APAAR_MISMATCH",
                    dedupe_key=f"student:{student_id}:APAAR_MISMATCH",
                    severity="medium",
                    title="Reported details do not match the APAAR registry",
                    explanation=(
                        f"The institution reported a name or date of birth that does not match the "
                        f"APAAR registry for {mask_apaar(parsed.values.get('apaar_id'))}."
                    ),
                    evidence={
                        "apaar_masked": mask_apaar(parsed.values.get("apaar_id")),
                        "upload_id": upload.id,
                        "row": parsed.row_number,
                        "registry_status": "mismatch",
                    },
                    institution_id=institution_id,
                    student_id=student_id,
                    enrolment_id=enrolment_id,
                    academic_year=year,
                )
                created.append({"id": flag.id, "type": flag.type, "severity": flag.severity})
            elif issue.code == "LATE_ADMISSION" and enrolment_id is not None:
                flag, _ = upsert_flag(
                    db,
                    type="LATE_ADMISSION",
                    dedupe_key=f"enrolment:{enrolment_id}:LATE_ADMISSION",
                    severity="medium",
                    title="Admission recorded after the cutoff date",
                    explanation=issue.message,
                    evidence={
                        "admitted_on": parsed.values["admission_date"].isoformat(),
                        "upload_id": upload.id,
                        "row": parsed.row_number,
                        "admission_type": parsed.values.get("admission_type"),
                    },
                    institution_id=institution_id,
                    student_id=student_id,
                    enrolment_id=enrolment_id,
                    academic_year=year,
                )
                created.append({"id": flag.id, "type": flag.type, "severity": flag.severity})

    db.flush()
    return created


# --------------------------------------------------------------------------- reporting


def compute_quality_score(
    *, rows_total: int, rows_error: int, rows_warning: int, mapping: dict[str, str | None]
) -> int:
    """0-100. Errors dominate; warnings and missing useful columns cost a little."""
    if rows_total == 0:
        return 0
    base = (rows_total - rows_error) / rows_total * 100.0
    warning_penalty = (rows_warning / rows_total) * 10.0

    mapped = {field_name for field_name in mapping.values() if field_name}
    # These are not required, but without them we cannot detect ghost clusters or
    # report demographics, so an upload that omits them is lower quality.
    useful = ("apaar_id", "guardian_phone", "phone", "email", "category", "gender", "admission_type")
    mapping_penalty = sum(2.0 for field_name in useful if field_name not in mapped)

    return int(max(0.0, min(100.0, round(base - warning_penalty - mapping_penalty))))


def quality_report(
    upload: Upload,
    *,
    flags_created: list[dict[str, Any]] | None = None,
    stored: dict[str, Any] | None = None,
) -> dict[str, Any]:
    issues = list(upload.issues or [])
    counts = Counter(issue["code"] for issue in issues)
    return {
        "upload_id": upload.id,
        "filename": upload.filename,
        "state": upload.state,
        "academic_year": upload.academic_year,
        "quality_score": upload.quality_score,
        "rows_total": upload.rows_total,
        "rows_ok": upload.rows_ok,
        "rows_error": upload.rows_error,
        "rows_warning": upload.rows_warning,
        "blank_rows_skipped": upload.blank_rows_skipped,
        "already_reported": (stored or {}).get("already_reported", counts.get("ALREADY_REPORTED", 0)),
        "enrolments_created": (stored or {}).get("enrolments_created"),
        "students_created": (stored or {}).get("students_created"),
        "registry_check": upload.registry_summary or {},
        "issue_counts": dict(counts),
        "flags_created": flags_created or [],
        "issues": issues[:MAX_ISSUES_IN_RESPONSE],
        "issues_truncated": len(issues) > MAX_ISSUES_IN_RESPONSE,
        "column_mapping": upload.column_mapping or {},
        "errors_csv_url": f"/institution/uploads/{upload.id}/errors.csv",
        "created_at": upload.created_at,
    }


def errors_csv(upload: Upload) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["row", "severity", "code", "field", "message", "fix_suggestion"])
    for issue in upload.issues or []:
        writer.writerow(
            [
                issue.get("row"),
                issue.get("severity"),
                issue.get("code"),
                issue.get("field") or "",
                issue.get("message") or "",
                issue.get("fix_suggestion") or "",
            ]
        )
    return buffer.getvalue()


def template_csv() -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(CANONICAL_FIELDS)
    writer.writerow(
        [
            "123456781234", "provided", "Rahul Sharma", "M", "2006-03-12", "OBC-NCL", "indian",
            "9876543210", "rahul.sharma@example.com", "9876500000", "B.Tech",
            "Computer Science and Engineering", "regular", "2026-27", "1", "regular",
            "2026-08-05", "admitted",
        ]
    )
    writer.writerow(
        [
            "", "not_applicable", "Chen Wei", "M", "2005-07-19", "GEN", "fn", "9811100000",
            "chen.wei@example.com", "9811100001", "B.Tech", "Mechanical Engineering",
            "regular", "2026-27", "1", "fn_pio_oci", "2026-08-11", "admitted",
        ]
    )
    return buffer.getvalue()


REQUIRED_FIELDS_FOR_TEMPLATE = REQUIRED_FIELDS
