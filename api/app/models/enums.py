"""Domain vocabularies (CLAUDE.md sections 6, 7 and 8).

Stored as plain strings for SQLite friendliness; validated at the Pydantic layer.
"""
from __future__ import annotations

from typing import Final, Literal

Role = Literal["institution", "aicte_viewer", "aicte_officer", "student", "verifier", "admin"]
ROLES: Final[tuple[str, ...]] = (
    "institution",
    "aicte_viewer",
    "aicte_officer",
    "student",
    "verifier",
    "admin",
)

ApaarStatus = Literal["provided", "pending", "not_applicable"]
APAAR_STATUSES: Final[tuple[str, ...]] = ("provided", "pending", "not_applicable")

NationalityStatus = Literal["indian", "nri", "oci", "fn"]
NATIONALITY_STATUSES: Final[tuple[str, ...]] = ("indian", "nri", "oci", "fn")
# apaar_status=not_applicable is valid ONLY for these (CLAUDE.md section 6).
APAAR_EXEMPT_NATIONALITIES: Final[tuple[str, ...]] = ("fn", "oci")

ProgramMode = Literal["regular", "online"]
PROGRAM_MODES: Final[tuple[str, ...]] = ("regular", "online")

AdmissionType = Literal["regular", "lateral", "tfw", "fn_pio_oci", "pmsss", "other_supernumerary"]
ADMISSION_TYPES: Final[tuple[str, ...]] = (
    "regular",
    "lateral",
    "tfw",
    "fn_pio_oci",
    "pmsss",
    "other_supernumerary",
)
SUPERNUMERARY_TYPES: Final[tuple[str, ...]] = (
    "lateral",
    "tfw",
    "fn_pio_oci",
    "pmsss",
    "other_supernumerary",
)

EnrolmentStatus = Literal["admitted", "cancelled", "migrated", "dropped", "completed"]
ENROLMENT_STATUSES: Final[tuple[str, ...]] = (
    "admitted",
    "cancelled",
    "migrated",
    "dropped",
    "completed",
)
# Statuses that occupy a seat / count as an active enrolment.
ACTIVE_ENROLMENT_STATUSES: Final[tuple[str, ...]] = ("admitted", "completed")

StudentConfirmation = Literal["unconfirmed", "confirmed", "disputed"]
STUDENT_CONFIRMATIONS: Final[tuple[str, ...]] = ("unconfirmed", "confirmed", "disputed")

UploadState = Literal["pending_mapping", "validating", "completed", "failed"]
UPLOAD_STATES: Final[tuple[str, ...]] = ("pending_mapping", "validating", "completed", "failed")

Severity = Literal["low", "medium", "high", "critical"]
SEVERITIES: Final[tuple[str, ...]] = ("low", "medium", "high", "critical")
SEVERITY_ORDER: Final[dict[str, int]] = {"low": 1, "medium": 2, "high": 3, "critical": 4}

FlagStatus = Literal["open", "under_review", "escalated", "dismissed", "resolved"]
FLAG_STATUSES: Final[tuple[str, ...]] = (
    "open",
    "under_review",
    "escalated",
    "dismissed",
    "resolved",
)
OPEN_FLAG_STATUSES: Final[tuple[str, ...]] = ("open", "under_review", "escalated")

# Exactly the flag types from CLAUDE.md section 8 — no others may be created.
FlagType = Literal[
    "INVALID_APAAR",
    "APAAR_NOT_FOUND",
    "APAAR_MISMATCH",
    "DUPLICATE_IN_UPLOAD",
    "EXCESS_INTAKE",
    "CROSS_INSTITUTION_DUPLICATE",
    "POSSIBLE_DUAL_DEGREE",
    "IDENTITY_DUPLICATE",
    "GHOST_CLUSTER",
    "SEQUENTIAL_APAAR",
    "LATE_ADMISSION",
    "LAST_MINUTE_BULK",
    "PHANTOM_PROGRESSION",
    "STUDENT_DISPUTE",
    "STATISTICAL_ANOMALY",
]
FLAG_TYPES: Final[tuple[str, ...]] = (
    "INVALID_APAAR",
    "APAAR_NOT_FOUND",
    "APAAR_MISMATCH",
    "DUPLICATE_IN_UPLOAD",
    "EXCESS_INTAKE",
    "CROSS_INSTITUTION_DUPLICATE",
    "POSSIBLE_DUAL_DEGREE",
    "IDENTITY_DUPLICATE",
    "GHOST_CLUSTER",
    "SEQUENTIAL_APAAR",
    "LATE_ADMISSION",
    "LAST_MINUTE_BULK",
    "PHANTOM_PROGRESSION",
    "STUDENT_DISPUTE",
    "STATISTICAL_ANOMALY",
)

ConsentStatus = Literal["pending", "approved", "denied", "revoked", "expired"]
CONSENT_STATUSES: Final[tuple[str, ...]] = ("pending", "approved", "denied", "revoked", "expired")

RegistryStatus = Literal["match", "mismatch", "not_found", "consent_required", "source_unavailable", "skipped"]
REGISTRY_STATUSES: Final[tuple[str, ...]] = (
    "match",
    "mismatch",
    "not_found",
    "consent_required",
    "source_unavailable",
    "skipped",
)

VERIFIER_PURPOSES: Final[dict[str, str]] = {
    "employment_verification": "Employment background verification",
    "higher_education_admission": "Admission to higher education",
    "scholarship": "Scholarship / fee waiver check",
    "regulatory_audit": "Regulatory audit",
}
