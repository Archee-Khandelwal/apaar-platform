"""Institution-facing request/response schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import ADMISSION_TYPES, APAAR_STATUSES, NATIONALITY_STATUSES


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
