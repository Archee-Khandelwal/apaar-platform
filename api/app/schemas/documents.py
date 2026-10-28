"""Document submission and verification schemas (Phases 4 and 5)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class DocumentSummaryOut(BaseModel):
    id: int
    doc_type: str
    original_filename: str
    content_type: str
    size_bytes: int
    sha256: str
    uploaded_at: datetime
    uploaded_by: str | None = None
    upload_channel: str
    verification_status: str
    issuer_status: str
    integrity_ok: bool
    reasons: list[dict[str, Any]] = Field(default_factory=list)
    review_decision: str | None = None
    review_reason: str | None = None


class ChecklistItemOut(BaseModel):
    doc_type: str
    label: str
    status: str = Field(description="missing | uploaded | verified | rejected")
    document: DocumentSummaryOut | None = None


class StudentChecklistOut(BaseModel):
    student_id: int
    apaar_masked: str
    name_masked: str
    nationality_status: str
    category: str | None = None
    admission_type: str
    academic_year: str
    items: list[ChecklistItemOut]
    counts: dict[str, int]
    complete: bool


class DocumentOverviewRow(BaseModel):
    student_id: int
    apaar_masked: str
    name_masked: str
    admission_type: str
    nationality_status: str
    required: int
    counts: dict[str, int]
    status: str
    missing: list[str]


class DocumentOverviewPage(BaseModel):
    items: list[DocumentOverviewRow]
    page: int
    page_size: int
    total: int
    total_pages: int
    sort: str | None = None
    totals: dict[str, int] = Field(default_factory=dict)


class DocumentTypeOut(BaseModel):
    doc_type: str
    label: str
    issuer_kind: str | None = None


class ChecklistRulesOut(BaseModel):
    checklist_set: str
    document_types: list[DocumentTypeOut]
    required: dict[str, Any]
    limits: dict[str, Any]


class BulkUploadResult(BaseModel):
    file: str
    status: str = Field(description="stored | rejected | skipped")
    reason: str | None = None
    doc_type: str | None = None
    student_id: int | None = None
    document_id: int | None = None


class BulkUploadReport(BaseModel):
    files: int
    stored: int
    rejected: int
    skipped: int
    results: list[BulkUploadResult]


class StudentDocumentOut(BaseModel):
    id: int
    doc_type: str
    label: str
    institution_name: str
    uploaded_at: datetime
    status: str


class StudentDocumentList(BaseModel):
    items: list[StudentDocumentOut]


class DocumentViewRequest(BaseModel):
    reason: str = Field(min_length=10, max_length=500)


# --------------------------------------------------------------------------- review (Phase 5)


class ReviewRow(BaseModel):
    document_id: int
    doc_type: str
    label: str
    verification_status: str
    issuer_status: str
    issuer_label: str
    reasons: list[dict[str, Any]]
    student_id: int
    apaar_masked: str
    name_masked: str
    institution_id: int
    institution_name: str
    uploaded_at: datetime


class ReviewPage(BaseModel):
    items: list[ReviewRow]
    page: int
    page_size: int
    total: int
    total_pages: int
    sort: str | None = None
    counts: dict[str, int]


class CaseFileOut(BaseModel):
    document_id: int
    doc_type: str
    label: str
    content_type: str
    sha256: str
    uploaded_at: datetime
    uploaded_by: str | None = None
    verification_status: str
    reasons: list[dict[str, Any]]
    student: dict[str, Any]
    institution: dict[str, Any] | None = None
    comparison: list[dict[str, Any]]
    extracted: dict[str, Any]
    issuer: dict[str, Any]
    tamper: dict[str, Any]
    integrity_ok: bool
    review: dict[str, Any]


class ReviewDecisionIn(BaseModel):
    decision: str = Field(pattern="^(approve|reject)$")
    reason: str = Field(min_length=10, max_length=1000)


class ReviewDecisionOut(BaseModel):
    document_id: int
    verification_status: str
    review_decision: str
    reviewed_by: str
    audit_log_id: int | None = None
