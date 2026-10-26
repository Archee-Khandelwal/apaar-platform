"""Row-level validation for institution uploads (Step 6 of docs/PLAN.md).

Each issue carries a code, a human-readable message and a concrete fix suggestion, so
the quality report tells a college exactly what to change. Invalid rows are reported,
never stored.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from app.core.crypto import is_valid_apaar, normalize_apaar, normalize_phone
from app.models.enums import (
    ADMISSION_TYPES,
    APAAR_EXEMPT_NATIONALITIES,
    APAAR_STATUSES,
    ENROLMENT_STATUSES,
    NATIONALITY_STATUSES,
    PROGRAM_MODES,
)
from app.services.rules import YearCalendar

DOB_MIN_YEAR = 1950
DOB_MAX_AGE = 80
DOB_MIN_AGE = 14  # A technical-programme entrant younger than this is implausible.

ACADEMIC_YEAR_RE = re.compile(r"^(20\d{2})\s*[-/]\s*(\d{2}|20\d{2})$")

DATE_FORMATS = (
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%d.%m.%Y",
    "%d/%m/%y",
    "%d-%b-%Y",
    "%d %b %Y",
    "%d %B %Y",
    "%b %d, %Y",
    "%m/%d/%Y",  # tried last: ambiguous with %d/%m/%Y
    "%Y/%m/%d",
)

GENDER_MAP = {
    "m": "M", "male": "M", "boy": "M",
    "f": "F", "female": "F", "girl": "F", "w": "F",
    "o": "O", "other": "O", "transgender": "O", "t": "O",
}

CATEGORY_MAP = {
    "gen": "GEN", "general": "GEN", "open": "GEN", "ur": "GEN",
    "obc": "OBC-NCL", "obc ncl": "OBC-NCL", "obcncl": "OBC-NCL", "obc-ncl": "OBC-NCL",
    "sc": "SC", "st": "ST", "ews": "EWS", "ebc": "EWS",
}

NATIONALITY_MAP = {
    "indian": "indian", "india": "indian", "in": "indian", "resident indian": "indian",
    "nri": "nri", "non resident indian": "nri",
    "oci": "oci", "overseas citizen of india": "oci", "pio": "oci",
    "fn": "fn", "foreign": "fn", "foreign national": "fn", "foreigner": "fn",
}

ADMISSION_TYPE_MAP = {
    "regular": "regular", "normal": "regular", "first year": "regular", "fresh": "regular",
    "lateral": "lateral", "lateral entry": "lateral", "le": "lateral", "second year entry": "lateral",
    "tfw": "tfw", "tuition fee waiver": "tfw", "fee waiver": "tfw",
    "fn": "fn_pio_oci", "fn pio oci": "fn_pio_oci", "foreign national": "fn_pio_oci",
    "pio": "fn_pio_oci", "oci": "fn_pio_oci", "nri": "fn_pio_oci",
    "pmsss": "pmsss", "pm special scholarship scheme": "pmsss",
    "supernumerary": "other_supernumerary", "other": "other_supernumerary",
}

STATUS_MAP = {
    "admitted": "admitted", "active": "admitted", "enrolled": "admitted", "studying": "admitted",
    "cancelled": "cancelled", "canceled": "cancelled", "admission cancelled": "cancelled",
    "migrated": "migrated", "transferred": "migrated",
    "dropped": "dropped", "dropout": "dropped", "discontinued": "dropped",
    "completed": "completed", "passed": "completed", "graduated": "completed",
}

MODE_MAP = {
    "regular": "regular", "full time": "regular", "ft": "regular", "offline": "regular",
    "online": "online", "odl": "online", "distance": "online", "online odl": "online",
}

FIX_SUGGESTIONS = {
    "MISSING_REQUIRED": "Fill this column for the row and upload again.",
    "INVALID_APAAR": (
        "An APAAR ID is exactly 12 digits. Check the student's APAAR / ABC card and correct it."
    ),
    "APAAR_REQUIRED": (
        "Indian students need an APAAR ID. Enter it, or set apaar_status to 'pending' if the "
        "student has applied but not yet received one."
    ),
    "NOT_APPLICABLE_NOT_ALLOWED": (
        "'not_applicable' is only valid for foreign national or OCI students. Set "
        "nationality_status to fn or oci, or provide the APAAR ID."
    ),
    "INVALID_DATE": "Use a real calendar date in DD/MM/YYYY or YYYY-MM-DD format.",
    "IMPLAUSIBLE_DOB": "Check the date of birth — it implies an impossible age for this programme.",
    "INVALID_ENUM": "Use one of the allowed values listed in the upload template.",
    "INVALID_ACADEMIC_YEAR": "Write the academic year as 2026-27.",
    "INVALID_YEAR_OF_STUDY": "Year of study must be a whole number between 1 and 6.",
    "LATERAL_YEAR_MISMATCH": (
        "Lateral entrants join in year 2. Set year_of_study to 2, or correct the admission type."
    ),
    "LATE_ADMISSION": (
        "Attach the approval for this late admission, or correct the admission date."
    ),
    "DUPLICATE_IN_UPLOAD": (
        "The same student appears more than once in this file. Remove the duplicate row."
    ),
    "ALREADY_REPORTED": (
        "This enrolment was already reported in an earlier upload, so it was skipped. No action "
        "needed unless the details have changed."
    ),
    "UNKNOWN_PROGRAM": (
        "No approved programme matches this course and branch. Check the spelling against your "
        "approved programme list."
    ),
    "APAAR_NOT_FOUND": (
        "The APAAR registry has no record of this ID. Verify it with the student before resubmitting."
    ),
    "APAAR_MISMATCH": (
        "The name or date of birth does not match the APAAR registry. Correct the spelling or the "
        "date of birth to match the student's APAAR record."
    ),
    "REGISTRY_UNAVAILABLE": (
        "The APAAR registry could not be reached, so this row was stored and marked for re-check. "
        "No action needed."
    ),
}


@dataclass
class RowIssue:
    row: int
    severity: str  # error | warning | info
    code: str
    field: str | None = None
    message: str = ""
    value_masked: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "row": self.row,
            "severity": self.severity,
            "code": self.code,
            "field": self.field,
            "message": self.message,
            "value_masked": self.value_masked,
            "fix_suggestion": FIX_SUGGESTIONS.get(self.code, "Check this value and upload again."),
        }


@dataclass
class ParsedRow:
    row_number: int
    values: dict[str, Any] = field(default_factory=dict)
    issues: list[RowIssue] = field(default_factory=list)

    @property
    def has_error(self) -> bool:
        return any(issue.severity == "error" for issue in self.issues)

    @property
    def has_warning(self) -> bool:
        return any(issue.severity == "warning" for issue in self.issues)


def _blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    return str(value).strip().lower() in ("", "nan", "none", "null", "-", "na", "n/a")


def clean_text(value: Any) -> str | None:
    if _blank(value):
        return None
    return " ".join(str(value).split())


def parse_date(value: Any) -> tuple[date | None, bool]:
    """Parse a date in any of the formats a college might use.

    Returns ``(date, recognised)``: ``(None, False)`` when the text is not a date at all,
    ``(None, True)`` when it looks like a date but is not a real one (e.g. 31/02/2006).
    """
    if _blank(value):
        return None, False
    if isinstance(value, datetime):
        return value.date(), True
    if isinstance(value, date):
        return value, True

    text = str(value).strip()
    if text.endswith(" 00:00:00"):
        text = text[: -len(" 00:00:00")]

    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date(), True
        except ValueError:
            continue

    # Looks like a date (three numeric parts) but is not a valid one.
    if re.fullmatch(r"\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}", text):
        return None, True
    return None, False


def parse_academic_year(value: Any) -> str | None:
    """``2026-27``, ``2026-2027`` and ``2026/27`` all normalise to ``2026-27``."""
    text = clean_text(value)
    if text is None:
        return None
    match = ACADEMIC_YEAR_RE.match(text.replace(" ", ""))
    if not match:
        return None
    start, end = match.groups()
    end_short = end[-2:]
    if int(end_short) != (int(start) + 1) % 100:
        return None
    return f"{start}-{end_short}"


def _map_enum(value: Any, table: dict[str, str]) -> str | None:
    text = clean_text(value)
    if text is None:
        return None
    key = re.sub(r"[^a-z0-9 ]+", " ", text.lower()).strip()
    key = re.sub(r"\s+", " ", key)
    return table.get(key)


def validate_row(
    row_number: int,
    raw: dict[str, Any],
    *,
    calendar: YearCalendar | None,
    defaults: dict[str, Any] | None = None,
) -> ParsedRow:
    """Validate and normalise one mapped row. Required fields and domain rules only —
    registry checks and duplicate detection happen over the whole batch."""
    defaults = defaults or {}
    parsed = ParsedRow(row_number=row_number)
    issues = parsed.issues

    def get(field_name: str) -> Any:
        value = raw.get(field_name)
        if _blank(value):
            return defaults.get(field_name)
        return value

    # ---------------------------------------------------------------- name
    name = clean_text(get("student_name"))
    if name is None:
        issues.append(
            RowIssue(row_number, "error", "MISSING_REQUIRED", "student_name", "Student name is missing.")
        )
    parsed.values["student_name"] = name

    # ---------------------------------------------------------------- nationality / APAAR
    nationality_raw = get("nationality_status")
    nationality = _map_enum(nationality_raw, NATIONALITY_MAP)
    if nationality is None and not _blank(nationality_raw):
        issues.append(
            RowIssue(
                row_number,
                "warning",
                "INVALID_ENUM",
                "nationality_status",
                f"Unrecognised nationality {clean_text(nationality_raw)!r}; assumed Indian.",
            )
        )
    nationality = nationality or "indian"
    parsed.values["nationality_status"] = nationality

    apaar_raw = get("apaar_id")
    apaar = normalize_apaar(apaar_raw) if not _blank(apaar_raw) else None
    status_raw = get("apaar_status")
    apaar_status = clean_text(status_raw)
    apaar_status = apaar_status.lower().replace(" ", "_") if apaar_status else None
    if apaar_status not in APAAR_STATUSES:
        if apaar_status is not None:
            issues.append(
                RowIssue(
                    row_number,
                    "warning",
                    "INVALID_ENUM",
                    "apaar_status",
                    f"Unrecognised apaar_status {apaar_status!r}; inferred from the APAAR ID column.",
                )
            )
        apaar_status = "provided" if apaar else ("not_applicable" if nationality in APAAR_EXEMPT_NATIONALITIES else "pending")

    if apaar_status == "not_applicable" and nationality not in APAAR_EXEMPT_NATIONALITIES:
        issues.append(
            RowIssue(
                row_number,
                "error",
                "NOT_APPLICABLE_NOT_ALLOWED",
                "apaar_status",
                "apaar_status 'not_applicable' is only valid for foreign national / OCI students.",
            )
        )
    elif apaar is None and apaar_status == "provided":
        issues.append(
            RowIssue(row_number, "error", "APAAR_REQUIRED", "apaar_id", "APAAR ID is missing.")
        )
    elif apaar is not None and not is_valid_apaar(apaar):
        issues.append(
            RowIssue(
                row_number,
                "error",
                "INVALID_APAAR",
                "apaar_id",
                f"APAAR ID must be exactly 12 digits (found {len(apaar)}).",
                value_masked=f"XXXX-XXXX-{apaar[-4:]}" if len(apaar) >= 4 else "XXXX-XXXX-XXXX",
            )
        )
    elif apaar is None and apaar_status == "pending" and nationality == "indian":
        issues.append(
            RowIssue(
                row_number,
                "warning",
                "APAAR_REQUIRED",
                "apaar_id",
                "No APAAR ID yet; row accepted as 'pending'.",
            )
        )

    parsed.values["apaar_id"] = apaar
    parsed.values["apaar_status"] = apaar_status

    # ---------------------------------------------------------------- dob
    dob, recognised = parse_date(get("dob"))
    if dob is None:
        if recognised:
            issues.append(
                RowIssue(row_number, "error", "INVALID_DATE", "dob", "Date of birth is not a real date.")
            )
        else:
            issues.append(
                RowIssue(row_number, "error", "MISSING_REQUIRED", "dob", "Date of birth is missing or unreadable.")
            )
    else:
        reference = calendar.admission_window_end if calendar else date.today()
        age = reference.year - dob.year - ((reference.month, reference.day) < (dob.month, dob.day))
        if dob.year < DOB_MIN_YEAR or age > DOB_MAX_AGE or age < DOB_MIN_AGE:
            issues.append(
                RowIssue(
                    row_number,
                    "error",
                    "IMPLAUSIBLE_DOB",
                    "dob",
                    f"Date of birth implies an age of {age} at admission.",
                )
            )
    parsed.values["dob"] = dob

    # ---------------------------------------------------------------- simple enums
    parsed.values["gender"] = _map_enum(get("gender"), GENDER_MAP)
    parsed.values["category"] = _map_enum(get("category"), CATEGORY_MAP)
    parsed.values["program_mode"] = _map_enum(get("program_mode"), MODE_MAP)

    status = _map_enum(get("status"), STATUS_MAP)
    if status is None and not _blank(get("status")):
        issues.append(
            RowIssue(
                row_number,
                "warning",
                "INVALID_ENUM",
                "status",
                f"Unrecognised status {clean_text(get('status'))!r}; assumed 'admitted'.",
            )
        )
    parsed.values["status"] = status or "admitted"
    if parsed.values["status"] not in ENROLMENT_STATUSES:  # pragma: no cover - map guarantees this
        parsed.values["status"] = "admitted"

    admission_type = _map_enum(get("admission_type"), ADMISSION_TYPE_MAP)
    if admission_type is None and not _blank(get("admission_type")):
        issues.append(
            RowIssue(
                row_number,
                "warning",
                "INVALID_ENUM",
                "admission_type",
                f"Unrecognised admission type {clean_text(get('admission_type'))!r}; assumed 'regular'.",
            )
        )
    admission_type = admission_type or "regular"
    if admission_type not in ADMISSION_TYPES:  # pragma: no cover
        admission_type = "regular"
    parsed.values["admission_type"] = admission_type

    # ---------------------------------------------------------------- programme
    course = clean_text(get("course"))
    branch = clean_text(get("branch"))
    if course is None:
        issues.append(RowIssue(row_number, "error", "MISSING_REQUIRED", "course", "Course is missing."))
    if branch is None:
        issues.append(RowIssue(row_number, "error", "MISSING_REQUIRED", "branch", "Branch is missing."))
    parsed.values["course"] = course
    parsed.values["branch"] = branch

    # ---------------------------------------------------------------- academic year / year of study
    academic_year = parse_academic_year(get("academic_year"))
    if academic_year is None:
        raw_year = clean_text(get("academic_year"))
        issues.append(
            RowIssue(
                row_number,
                "error",
                "MISSING_REQUIRED" if raw_year is None else "INVALID_ACADEMIC_YEAR",
                "academic_year",
                "Academic year is missing." if raw_year is None else f"{raw_year!r} is not an academic year.",
            )
        )
    parsed.values["academic_year"] = academic_year

    year_of_study_raw = get("year_of_study")
    year_of_study: int | None = None
    if not _blank(year_of_study_raw):
        try:
            year_of_study = int(float(str(year_of_study_raw).strip()))
        except ValueError:
            year_of_study = None
        if year_of_study is None or not 1 <= year_of_study <= 6:
            issues.append(
                RowIssue(
                    row_number,
                    "warning",
                    "INVALID_YEAR_OF_STUDY",
                    "year_of_study",
                    f"Year of study {clean_text(year_of_study_raw)!r} is not between 1 and 6.",
                )
            )
            year_of_study = None
    if year_of_study is None:
        year_of_study = 2 if admission_type == "lateral" else 1
    if admission_type == "lateral" and year_of_study == 1:
        # CLAUDE.md section 6: lateral entrants join in year 2.
        issues.append(
            RowIssue(
                row_number,
                "warning",
                "LATERAL_YEAR_MISMATCH",
                "year_of_study",
                "Lateral entry recorded in year 1; corrected to year 2 so it is not counted "
                "against year-1 intake.",
            )
        )
        year_of_study = 2
    parsed.values["year_of_study"] = year_of_study

    # ---------------------------------------------------------------- admission date
    admitted_on, recognised = parse_date(get("admission_date"))
    if admitted_on is None:
        if recognised:
            issues.append(
                RowIssue(
                    row_number, "error", "INVALID_DATE", "admission_date", "Admission date is not a real date."
                )
            )
        else:
            issues.append(
                RowIssue(
                    row_number,
                    "error",
                    "MISSING_REQUIRED",
                    "admission_date",
                    "Admission date is missing or unreadable.",
                )
            )
    elif calendar is not None and calendar.is_late(admitted_on, admission_type):
        cutoff = (
            calendar.lateral_window_end if admission_type == "lateral" else calendar.admission_window_end
        )
        issues.append(
            RowIssue(
                row_number,
                "warning",
                "LATE_ADMISSION",
                "admission_date",
                f"Admission date {admitted_on.isoformat()} is after the "
                f"{calendar.academic_year} cutoff ({cutoff.isoformat()}).",
            )
        )
    parsed.values["admission_date"] = admitted_on

    # ---------------------------------------------------------------- contacts (hashed later)
    parsed.values["phone"] = normalize_phone(get("phone"))
    parsed.values["email"] = clean_text(get("email"))
    parsed.values["guardian_phone"] = normalize_phone(get("guardian_phone"))

    return parsed
