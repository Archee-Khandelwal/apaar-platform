"""Student and verifier schemas."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field


class StudentSelf(BaseModel):
    student_id: int
    apaar_masked: str
    apaar_status: str
    name: str | None = None
    dob: str | None = None
    is_minor: bool
    nationality_status: str
    category: str | None = None
    gender: str | None = None


class StudentEnrolmentView(BaseModel):
    id: int
    institution_name: str
    program: str
    mode: str
    academic_year: str
    year_of_study: int
    admission_type: str
    status: str
    admitted_on: date | None = None
    reported_by_upload_at: datetime | None = None
    confirmation: str
    version: int


class StudentMeOut(BaseModel):
    student: StudentSelf
    enrolments: list[StudentEnrolmentView]
    open_cases: list[dict[str, Any]] = Field(default_factory=list)
    pending_consents: int = 0


class ConfirmResponse(BaseModel):
    enrolment_id: int
    confirmation: str
    confirmed_at: datetime
    audit_log_id: int | None = None


class DisputeRequest(BaseModel):
    reason: str = Field(min_length=10, max_length=2000)
    category: str = "other"


class DisputeResponse(BaseModel):
    enrolment_id: int
    confirmation: str
    flag: dict[str, Any]
    message: str
    audit_log_id: int | None = None


class CorrectionRequestIn(BaseModel):
    enrolment_id: int | None = None
    field: str = Field(min_length=1, max_length=64)
    correct_value: str = Field(min_length=1, max_length=255)
    note: str | None = Field(default=None, max_length=2000)


class CorrectionOut(BaseModel):
    correction_id: int
    status: str
    institution_name: str
    field: str
    correct_value: str
    response_note: str | None = None
    created_at: datetime


class CorrectionPage(BaseModel):
    items: list[CorrectionOut]
    page: int
    page_size: int
    total: int
    total_pages: int
    sort: str | None = None


class AccessLogRow(BaseModel):
    id: int
    at: datetime
    actor_role: str
    actor_label: str
    action: str
    reason: str | None = None
    purpose: str | None = None
    target: str


class AccessLogPage(BaseModel):
    items: list[AccessLogRow]
    page: int
    page_size: int
    total: int
    total_pages: int
    sort: str | None = None


class ConsentRow(BaseModel):
    consent_id: int
    status: str
    verifier_name: str
    verifier_type: str | None = None
    purpose: str
    purpose_label: str
    will_share: list[str]
    requested_at: datetime
    responded_at: datetime | None = None
    revoked_at: datetime | None = None
    expires_at: datetime | None = None
    parental_consent_required: bool


class ConsentPage(BaseModel):
    items: list[ConsentRow]
    page: int
    page_size: int
    total: int
    total_pages: int
    sort: str | None = None


class ApproveConsentRequest(BaseModel):
    validity_minutes: int | None = Field(default=None, ge=1, le=1440)


class DenyConsentRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=2000)


class ConsentActionResponse(BaseModel):
    consent_id: int
    status: str
    approved_at: datetime | None = None
    denied_at: datetime | None = None
    revoked_at: datetime | None = None
    expires_at: datetime | None = None
    shared_fields: list[str] = Field(default_factory=list)
    tokens_invalidated: int | None = None
    audit_log_id: int | None = None


class IdCardOut(BaseModel):
    apaar_masked: str
    name: str | None = None
    institution_name: str | None = None
    program: str | None = None
    academic_year: str | None = None
    year_of_study: int | None = None
    status: str | None = None
    is_minor: bool
    token: str
    token_expires_at: datetime
    qr_png_base64: str
    verify_url: str


# --------------------------------------------------------------------------- verifier


class PurposeOut(BaseModel):
    value: str
    label: str


class PurposesResponse(BaseModel):
    purposes: list[PurposeOut]


class VerificationRequestIn(BaseModel):
    apaar: str = Field(min_length=1, max_length=20)
    purpose: str
    note: str | None = Field(default=None, max_length=500)


class VerificationRequestOut(BaseModel):
    request_id: int
    status: str
    apaar_masked: str
    purpose: str
    consent_id: int | None = None
    notification: str | None = None
    parental_consent_required: bool = False
    requested_at: datetime
    expires_at: datetime | None = None
    message: str | None = None


class MinimalResult(BaseModel):
    """CLAUDE.md section 5 rule 11: verified, programme, year. Nothing else."""

    verified: bool
    program: str | None = None
    academic_year: str | None = None


class VerificationStatusOut(BaseModel):
    request_id: int
    status: str
    apaar_masked: str
    purpose: str
    requested_at: datetime
    responded_at: datetime | None = None
    expires_at: datetime | None = None
    result: MinimalResult | None = None


class VerificationPage(BaseModel):
    items: list[VerificationStatusOut]
    page: int
    page_size: int
    total: int
    total_pages: int
    sort: str | None = None


class TokenCheckOut(BaseModel):
    state: str
    verified: bool | None = None
    program: str | None = None
    academic_year: str | None = None
    institution_name: str | None = None
    checked_at: datetime


class DocumentCheckOut(BaseModel):
    """Public check of a signed document. Only ``state`` is set unless it is genuine or revoked."""

    state: str
    kind: str | None = None
    serial: str | None = None
    issued_at: datetime | None = None
    revoked_at: datetime | None = None
    claims: dict[str, Any] | None = None
    signature_alg: str | None = None
    key_id: str | None = None
    checked_at: datetime
