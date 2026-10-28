"""AICTE-facing schemas. Viewer-visible counts are typed as Suppressible ("<5")."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import Suppressible


class OpenFlagCounts(BaseModel):
    low: Suppressible = 0
    medium: Suppressible = 0
    high: Suppressible = 0
    critical: Suppressible = 0


class OverviewKpis(BaseModel):
    institutions_total: Suppressible
    institutions_reporting: Suppressible
    institutions_non_reporting: Suppressible
    students_reported: Suppressible
    total_excess_seats: Suppressible
    open_flags: OpenFlagCounts
    avg_data_quality: int | None = None


class FlagTypeCount(BaseModel):
    type: str
    count: Suppressible
    max_severity: str


class StateRow(BaseModel):
    state: str
    institutions: Suppressible
    institutions_reporting: Suppressible
    students_reported: Suppressible
    open_flags: Suppressible
    excess_seats: Suppressible


class OverviewOut(BaseModel):
    academic_year: str
    kpis: OverviewKpis
    flags_by_type: list[FlagTypeCount]
    by_state: list[StateRow]
    suppression_applied: bool
    generated_at: datetime


class InstitutionRow(BaseModel):
    id: int
    aicte_permanent_id: str
    name: str
    state: str
    region: str
    type: str
    students_reported: Suppressible
    open_flags: OpenFlagCounts
    open_flags_total: Suppressible
    excess_seats: Suppressible
    last_upload_at: datetime | None = None


class InstitutionPage(BaseModel):
    items: list[InstitutionRow]
    page: int
    page_size: int
    total: int
    total_pages: int
    sort: str | None = None


class FlagOut(BaseModel):
    """Officer view. A viewer receives only the subset in cases.VIEWER_FLAG_FIELDS."""

    id: int
    type: str
    severity: str
    status: str
    title: str
    explanation: str
    institution_id: int | None = None
    institution_name: str | None = None
    state: str | None = None
    academic_year: str | None = None
    created_at: datetime
    evidence: dict[str, Any] | None = None
    student_id: int | None = None
    enrolment_id: int | None = None
    program_id: int | None = None
    assigned_to: str | None = None
    notes: list[dict[str, Any]] | None = None


class FlagFacets(BaseModel):
    by_type: dict[str, Suppressible] = Field(default_factory=dict)
    by_severity: dict[str, Suppressible] = Field(default_factory=dict)
    by_status: dict[str, Suppressible] = Field(default_factory=dict)


class FlagPage(BaseModel):
    items: list[FlagOut]
    page: int
    page_size: int
    total: int
    total_pages: int
    sort: str | None = None
    facets: FlagFacets


class FlagDetailOut(FlagOut):
    history: list[dict[str, Any]] = Field(default_factory=list)
    related_flags: list[dict[str, Any]] = Field(default_factory=list)
    students: list[dict[str, Any]] = Field(default_factory=list)


class FlagUpdateRequest(BaseModel):
    status: str | None = None
    assigned_to: str | None = None
    note: str | None = Field(default=None, max_length=2000)
    reason: str | None = Field(default=None, max_length=2000)


class FlagUpdateResponse(BaseModel):
    flag: FlagOut
    audit_log_id: int | None = None


class RevealRequest(BaseModel):
    student_id: int
    reason: str = Field(min_length=1, max_length=2000)


class RevealedEnrolment(BaseModel):
    id: int
    institution_id: int
    institution_name: str
    program: str
    mode: str
    academic_year: str
    year_of_study: int
    admission_type: str
    status: str
    admitted_on: date | None = None


class RevealResponse(BaseModel):
    student_id: int
    apaar_id: str | None = None
    apaar_status: str
    name: str | None = None
    dob: str | None = None
    gender: str | None = None
    category: str | None = None
    nationality_status: str
    is_minor: bool
    enrolments: list[RevealedEnrolment]
    access_log_id: int
    revealed_at: datetime
    notice: str


class TrendSeries(BaseModel):
    key: str
    values: dict[str, Suppressible]
    yoy_growth_pct: float | None = None


class TrendsOut(BaseModel):
    dimension: str
    academic_years: list[str]
    series: list[TrendSeries]
    notes: list[str] = Field(default_factory=list)
    new_admissions_only: bool = False
    csv_url: str


class InstitutionProfileOut(BaseModel):
    institution: dict[str, Any]
    reporting: dict[str, Any]
    seat_matrix_summary: dict[str, Any]
    flags: list[FlagOut]
    upload_timeline: list[dict[str, Any]]
