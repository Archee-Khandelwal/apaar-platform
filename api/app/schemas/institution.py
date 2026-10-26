"""Institution-facing request/response schemas."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import ADMISSION_TYPES, APAAR_STATUSES, NATIONALITY_STATUSES
from app.schemas.common import Suppressible


class ProgramOut(BaseModel):
    id: int
    course: str
    branch: str
    level: str
    mode: str


class InstitutionProfile(BaseModel):
    id: int
    aicte_permanent_id: str
    name: str
    state: str
    region: str
    type: str
    programs: list[ProgramOut]


class ColumnProposalOut(BaseModel):
    source_column: str
    field: str | None = None
    confidence: float
    sample_values: list[str] = Field(default_factory=list)


class UploadCreateResponse(BaseModel):
    upload_id: int
    filename: str
    state: str
    rows_total: int
    blank_rows_skipped: int
    detected_sheet: str | None = None
    proposed_mapping: list[ColumnProposalOut]
    unmapped_required_fields: list[str]
    available_fields: list[str]


class ConfirmMappingRequest(BaseModel):
    """``mapping`` is source column -> canonical field (or null to ignore the column)."""

    mapping: dict[str, str | None]
    defaults: dict[str, Any] = Field(default_factory=dict)


class RowIssueOut(BaseModel):
    row: int
    severity: str
    code: str
    field: str | None = None
    message: str
    value_masked: str | None = None
    fix_suggestion: str


class FlagStub(BaseModel):
    id: int
    type: str
    severity: str


class QualityReport(BaseModel):
    upload_id: int
    filename: str
    state: str
    academic_year: str | None = None
    quality_score: int | None = None
    rows_total: int
    rows_ok: int
    rows_error: int
    rows_warning: int
    blank_rows_skipped: int
    already_reported: int = 0
    enrolments_created: int | None = None
    students_created: int | None = None
    registry_check: dict[str, int] = Field(default_factory=dict)
    issue_counts: dict[str, int] = Field(default_factory=dict)
    flags_created: list[FlagStub] = Field(default_factory=list)
    issues: list[RowIssueOut] = Field(default_factory=list)
    issues_truncated: bool = False
    column_mapping: dict[str, str | None] = Field(default_factory=dict)
    errors_csv_url: str
    created_at: datetime


class UploadSummary(BaseModel):
    id: int
    filename: str
    state: str
    academic_year: str | None = None
    rows_total: int
    rows_ok: int
    rows_error: int
    rows_warning: int
    quality_score: int | None = None
    created_at: datetime


class UploadPage(BaseModel):
    items: list[UploadSummary]
    page: int
    page_size: int
    total: int
    total_pages: int
    sort: str | None = None


class SupernumeraryBucketOut(BaseModel):
    admission_type: str
    label: str
    admitted: int
    cap: int
    cap_basis: str
    valid: int
    excess: int


class ProgramSeatMatrixOut(BaseModel):
    program_id: int
    course: str
    branch: str
    mode: str
    academic_year: str
    approved_intake: int
    regular_admitted: int
    regular_excess: int
    supernumerary: list[SupernumeraryBucketOut] = Field(default_factory=list)
    total_admitted: int
    valid_supernumerary: int
    supernumerary_excess: int
    vacant_regular_seats: int
    excess: int
    explanation: str
    rule_set: str
    flag_id: int | None = None


class SeatMatrixTotals(BaseModel):
    approved_intake: int
    regular_admitted: int
    valid_supernumerary: int
    total_admitted: int
    excess: int


class SeatMatrixOut(BaseModel):
    academic_year: str
    rule_set: str
    programs: list[ProgramSeatMatrixOut]
    totals: SeatMatrixTotals


class ClusterSummaryOut(BaseModel):
    cluster_id: int
    score: float
    severity: str
    kind: str
    student_count: Suppressible
    shared_attributes: dict[str, Suppressible] = Field(default_factory=dict)
    institutions: list[dict[str, Any]] = Field(default_factory=list)
    academic_year: str | None = None
    summary: str
    flag_id: int | None = None
    created_at: datetime


class ClusterPage(BaseModel):
    items: list[ClusterSummaryOut]
    page: int
    page_size: int
    total: int
    total_pages: int
    sort: str | None = None


class ClusterDetailOut(BaseModel):
    cluster_id: int
    score: float
    severity: str
    kind: str
    summary: str
    metrics: dict[str, Any] = Field(default_factory=dict)
    legend: dict[str, str] = Field(default_factory=dict)
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)
    access_log_id: int | None = None


class RiskRowOut(BaseModel):
    institution_id: int
    name: str
    state: str
    risk_score: float
    band: str
    top_reasons: list[str] = Field(default_factory=list)
    components: dict[str, float] = Field(default_factory=dict)
    open_flags: Suppressible = 0


class RiskPage(BaseModel):
    items: list[RiskRowOut]
    page: int
    page_size: int
    total: int
    total_pages: int
    sort: str | None = None


class ShortlistRowOut(BaseModel):
    rank: int
    institution_id: int
    name: str
    state: str
    risk_score: float
    band: str
    reasons: list[str] = Field(default_factory=list)
    suggested_checks: list[str] = Field(default_factory=list)


class ShortlistOut(BaseModel):
    generated_at: datetime
    academic_year: str
    items: list[ShortlistRowOut]
    csv_url: str


class InstitutionFlagOut(BaseModel):
    """Institution view of a flag: another college is never named (CLAUDE.md rule 10)."""

    id: int
    type: str
    severity: str
    status: str
    title: str
    explanation: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    student_id: int | None = None
    enrolment_id: int | None = None
    cluster_id: int | None = None
    program_id: int | None = None
    academic_year: str | None = None
    created_at: datetime


class InstitutionFlagPage(BaseModel):
    items: list[InstitutionFlagOut]
    page: int
    page_size: int
    total: int
    total_pages: int
    sort: str | None = None


class InstitutionFlagUpdate(BaseModel):
    status: str | None = None
    note: str | None = Field(default=None, max_length=2000)


class StudentEnrolmentOut(BaseModel):
    id: int
    program_id: int
    course: str
    branch: str
    academic_year: str
    year_of_study: int
    admission_type: str
    status: str
    admitted_on: date | None = None
    version: int


class StudentRowOut(BaseModel):
    student_id: int
    apaar_masked: str
    apaar_status: str
    name_masked: str
    gender: str | None = None
    category: str | None = None
    nationality_status: str
    dob_year: int | None = None
    is_minor: bool
    flag_count: int
    student_confirmation: str
    enrolment: StudentEnrolmentOut


class StudentPage(BaseModel):
    items: list[StudentRowOut]
    page: int
    page_size: int
    total: int
    total_pages: int
    sort: str | None = None


class EnrolmentStatusUpdate(BaseModel):
    status: str
    reason: str = Field(min_length=1, max_length=2000)
    effective_date: date | None = None


class EnrolmentStatusResponse(BaseModel):
    enrolment_id: int
    status: str
    previous_status: str
    version: int
    changed_at: datetime
    audit_log_id: int | None = None


class QualityPoint(BaseModel):
    upload_id: int
    created_at: datetime
    quality_score: int | None = None


class InstitutionDashboard(BaseModel):
    academic_year: str
    students_reported: int
    open_flags: dict[str, int]
    latest_quality_score: int | None = None
    quality_trend: list[QualityPoint] = Field(default_factory=list)
    seat_matrix_summary: dict[str, Any]
    compliance_certificate_eligible: bool
    compliance_certificate_reasons: list[str] = Field(default_factory=list)
    last_upload_at: datetime | None = None
