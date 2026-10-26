"""Column mapping: messy spreadsheet headers -> canonical fields.

Colleges send "Stu. Nm", "APAAR No.", "D.O.B", "Adm Dt". We propose a mapping with a
confidence per column using a synonym dictionary first and rapidfuzz as the fallback,
and the institution confirms or edits it before anything is validated or stored.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from rapidfuzz import fuzz, process

CANONICAL_FIELDS: tuple[str, ...] = (
    "apaar_id",
    "apaar_status",
    "student_name",
    "gender",
    "dob",
    "category",
    "nationality_status",
    "phone",
    "email",
    "guardian_phone",
    "course",
    "branch",
    "program_mode",
    "academic_year",
    "year_of_study",
    "admission_type",
    "admission_date",
    "status",
)

REQUIRED_FIELDS: tuple[str, ...] = (
    "student_name",
    "dob",
    "course",
    "branch",
    "academic_year",
    "admission_date",
)

# Known header spellings. Matched after normalisation (lowercase, punctuation stripped).
SYNONYMS: dict[str, tuple[str, ...]] = {
    "apaar_id": (
        "apaar", "apaar id", "apaar no", "apaar number", "apaarid", "apaar uid",
        "abc id", "abc account id", "academic bank of credits id", "apaar/abc id",
    ),
    "apaar_status": ("apaar status", "apaar availability", "apaar flag"),
    "student_name": (
        "student name", "name", "name of student", "stu nm", "stu name", "student",
        "candidate name", "full name", "student full name",
    ),
    "gender": ("gender", "sex", "m f", "m/f", "gender m f"),
    "dob": ("dob", "d o b", "date of birth", "birth date", "birthdate", "dt of birth"),
    "category": ("category", "cat", "social category", "reservation category", "caste category"),
    "nationality_status": ("nationality", "nationality status", "citizenship", "national status"),
    "phone": (
        "phone", "mobile", "mobile no", "mob no", "contact no", "student mobile",
        "phone number", "cell", "contact number",
    ),
    "email": ("email", "email id", "e mail", "mail id", "email address"),
    "guardian_phone": (
        "guardian phone", "parent contact", "parent phone", "father mobile",
        "mother mobile", "guardian mobile", "parent mobile no", "guardian contact",
        "parent/guardian contact", "emergency contact",
    ),
    "course": ("course", "programme", "program", "degree", "course name"),
    "branch": (
        "branch", "branch spec", "specialisation", "specialization", "discipline",
        "branch specialisation", "stream", "branch name",
    ),
    "program_mode": ("mode", "program mode", "programme mode", "delivery mode", "regular online"),
    "academic_year": ("academic year", "acad yr", "ay", "session", "academic session", "year"),
    "year_of_study": (
        "year of study", "yr", "current year", "study year", "year studying", "sem year",
    ),
    "admission_type": (
        "admission type", "adm type", "entry type", "quota", "admission category",
        "seat type", "entry mode",
    ),
    "admission_date": (
        "admission date", "adm dt", "adm date", "date of admission", "doa", "joining date",
        "date of joining",
    ),
    "status": ("status", "enrolment status", "enrollment status", "student status", "remarks status"),
}

# Headers that are definitely not student data.
IGNORE_HEADERS: tuple[str, ...] = (
    "sr no", "s no", "sl no", "serial", "sno", "roll no", "roll number", "unnamed",
    "remarks", "remark", "notes", "signature", "photo", "fee paid", "total",
)

_PUNCT = re.compile(r"[^a-z0-9]+")


def normalise_header(header: Any) -> str:
    text = _PUNCT.sub(" ", str(header).strip().lower()).strip()
    return re.sub(r"\s+", " ", text)


@dataclass
class ColumnProposal:
    source_column: str
    field: str | None
    confidence: float
    sample_values: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_column": self.source_column,
            "field": self.field,
            "confidence": round(self.confidence, 2),
            "sample_values": self.sample_values,
        }


_SYNONYM_LOOKUP: dict[str, str] = {
    normalise_header(spelling): field
    for field, spellings in SYNONYMS.items()
    for spelling in spellings
}
_SYNONYM_LOOKUP.update({normalise_header(field): field for field in CANONICAL_FIELDS})


def match_header(header: Any) -> tuple[str | None, float]:
    """Return (field, confidence 0-1) for one incoming header."""
    normalised = normalise_header(header)
    if not normalised or normalised.startswith("unnamed"):
        return None, 0.0
    if any(normalised == ignore or normalised.startswith(ignore) for ignore in IGNORE_HEADERS):
        return None, 0.0

    exact = _SYNONYM_LOOKUP.get(normalised)
    if exact:
        return exact, 1.0

    # Fuzzy match against every known spelling, then take that spelling's field.
    best = process.extractOne(normalised, list(_SYNONYM_LOOKUP.keys()), scorer=fuzz.WRatio)
    if best is None:
        return None, 0.0
    spelling, score, _ = best
    if score < 70:
        return None, round(score / 100.0, 2)
    return _SYNONYM_LOOKUP[spelling], round(score / 100.0, 2)


def propose_mapping(
    headers: list[Any], samples: dict[Any, list[Any]] | None = None
) -> list[ColumnProposal]:
    """Propose one field per incoming column, keeping the best claim on a contested field."""
    samples = samples or {}
    proposals: list[ColumnProposal] = []
    for header in headers:
        field, confidence = match_header(header)
        values = [
            str(value)
            for value in (samples.get(header) or [])
            if value is not None and str(value).strip() not in ("", "nan")
        ][:3]
        proposals.append(
            ColumnProposal(
                source_column=str(header),
                field=field,
                confidence=confidence,
                sample_values=values,
            )
        )

    # If two columns claim the same field, the more confident one keeps it.
    best_for_field: dict[str, ColumnProposal] = {}
    for proposal in proposals:
        if proposal.field is None:
            continue
        held = best_for_field.get(proposal.field)
        if held is None or proposal.confidence > held.confidence:
            if held is not None:
                held.field = None
            best_for_field[proposal.field] = proposal
        else:
            proposal.field = None
    return proposals


def unmapped_required_fields(mapping: dict[str, str | None]) -> list[str]:
    mapped = {field for field in mapping.values() if field}
    return [field for field in REQUIRED_FIELDS if field not in mapped]
