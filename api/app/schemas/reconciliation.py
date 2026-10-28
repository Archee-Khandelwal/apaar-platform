"""Reconciliation and AICTE master-record schemas (Phase 6)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import Page, Suppressible


class ProblemOut(BaseModel):
    check: str
    label: str
    result: str = Field(description="review | fail")
    message: str
    fix: str | None = None


class ReconRowOut(BaseModel):
    enrolment_id: int
    student_id: int
    apaar_masked: str
    name_masked: str
    institution_id: int
    institution_name: str
    program_id: int
    programme: str
    academic_year: str
    year_of_study: int
    admission_type: str
    overall: str = Field(description="confirmed | needs_review | rejected")
    problems: list[ProblemOut] = Field(default_factory=list)


class ProgrammeOption(BaseModel):
    program_id: int
    label: str


class ReconPage(Page[ReconRowOut]):
    programmes: list[ProgrammeOption] = Field(default_factory=list, description="Programmes of the filtered institution")


class StatusCounts(BaseModel):
    confirmed: Suppressible
    needs_review: Suppressible
    rejected: Suppressible
    records: Suppressible


class InstitutionSummaryOut(StatusCounts):
    institution_id: int
    name: str
    state: str
    aicte_permanent_id: str


class SummaryOut(BaseModel):
    academic_year: str
    totals: StatusCounts
    items: list[InstitutionSummaryOut]


class RecordDetailOut(ReconRowOut):
    submitted: dict[str, Any]
    apaar: dict[str, Any]
    master: dict[str, Any]
    documents: list[dict[str, Any]]
    checks: list[dict[str, Any]]
    computed_at: datetime


class ToFixOut(BaseModel):
    check: str
    label: str
    result: str
    fix: str | None = None
    example: str
    records: int


class InstitutionViewOut(BaseModel):
    academic_year: str
    counts: dict[str, int]
    records: int
    to_fix: list[ToFixOut]
    items: list[ReconRowOut]
    page: int
    page_size: int
    total: int
    total_pages: int


class MasterImportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    filename: str
    rows_total: int
    rows_ok: int
    rows_error: int
    issues: list[dict[str, Any]]
    actor: str
    created_at: datetime


class MasterStatusOut(BaseModel):
    approvals: dict[str, int]
    programme_records: dict[str, int]
    imports: list[MasterImportOut]
