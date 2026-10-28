"""Document routes for institutions, AICTE officers and students (Phases 4 and 5).

Who may read a stored document, and how:

* the **owning institution** — its ``institution_id`` comes from the JWT only;
* an **AICTE officer** — only with a written reason, which goes to the access log;
* the **student** it belongs to — their ``student_id`` comes from the JWT only.

Every read is access-logged and re-hashed against the SHA-256 taken at upload.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.errors import api_error, raise_not_found
from app.core.security import CurrentUser, require_institution_scope, require_role
from app.models.core import Institution, StudentDocument
from app.schemas.common import PageParams, page_params, paginate
from app.schemas.documents import (
    BulkUploadReport,
    CaseFileOut,
    ReviewDecisionIn,
    ReviewDecisionOut,
    ReviewPage,
    ChecklistRulesOut,
    DocumentOverviewPage,
    DocumentSummaryOut,
    DocumentTypeOut,
    DocumentViewRequest,
    StudentChecklistOut,
    StudentDocumentList,
    StudentDocumentOut,
)
from app.services import student_documents as documents
from app.services.document_verification import (
    ReviewError,
    case_file,
    record_decision,
    review_counts,
    review_queue,
    verify_document,
)
from app.services.reconciliation import reconcile_student, reconcile_student_set
from app.services.rules import document_checklist, document_types
from app.services.student_documents import DocumentIntegrityError, DocumentRejected

router = APIRouter(tags=["documents"])


def _rejected(exc: DocumentRejected):
    code_status = {
        "FILE_TOO_LARGE": status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        "UNSUPPORTED_FILE": status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        "UNSAFE_FILE": status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
    }
    return api_error(code_status.get(exc.code, status.HTTP_400_BAD_REQUEST), exc.code, exc.message)


def _file_response(document: StudentDocument, data: bytes) -> Response:
    return Response(
        content=data,
        media_type=document.content_type,
        headers={
            "Content-Disposition": f'inline; filename="document-{document.id}.{document.content_type.split("/")[-1]}"',
            "X-Content-SHA256": document.sha256,
            # Served bytes are never sniffed or cached by the browser.
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )


def _serve(db: Session, document: StudentDocument, *, actor: str, role: str, reason: str | None) -> Response:
    try:
        data = documents.read_document(db, document=document, actor=actor, role=role, reason=reason)
    except DocumentIntegrityError as exc:
        reconcile_student(db, document.student_id)
        db.commit()  # keep the access-log row, the flag and the rejected status
        raise api_error(status.HTTP_409_CONFLICT, "DOCUMENT_TAMPERED", str(exc))
    db.commit()
    return _file_response(document, data)


# --------------------------------------------------------------------------- institution


@router.get("/institution/documents/rules", response_model=ChecklistRulesOut)
def checklist_rules(user: CurrentUser = Depends(require_role("institution"))) -> ChecklistRulesOut:
    config = document_checklist()
    return ChecklistRulesOut(
        checklist_set=str(config.get("checklist_set", "unknown")),
        document_types=[
            DocumentTypeOut(doc_type=key, label=value.get("label", key), issuer_kind=value.get("issuer_kind"))
            for key, value in document_types().items()
        ],
        required=config.get("required", {}),
        limits=config.get("limits", {}),
    )


@router.get("/institution/documents", response_model=DocumentOverviewPage)
def documents_overview(
    status_filter: Annotated[str | None, Query(alias="status", pattern="^(missing|uploaded|verified|rejected)$")] = None,
    q: Annotated[str | None, Query(max_length=40)] = None,
    academic_year: Annotated[str | None, Query()] = None,
    params: PageParams = Depends(page_params),
    institution_id: int = Depends(require_institution_scope),
    db: Session = Depends(get_db),
) -> DocumentOverviewPage:
    """Every enrolled student with their checklist progress."""
    year = academic_year or settings.current_academic_year
    everyone = documents.institution_overview(db, institution_id=institution_id, academic_year=year)
    totals = {key: 0 for key in ("missing", "uploaded", "verified", "rejected")}
    for row in everyone:
        totals[row["status"]] += 1
    rows = documents.institution_overview(
        db, institution_id=institution_id, academic_year=year, status=status_filter, search=q
    )
    page_rows = rows[params.offset : params.offset + params.page_size]
    return DocumentOverviewPage(**paginate(page_rows, len(rows), params), totals=totals)


@router.get("/institution/students/{student_id}/documents", response_model=StudentChecklistOut)
def student_checklist(
    student_id: int,
    institution_id: int = Depends(require_institution_scope),
    db: Session = Depends(get_db),
) -> StudentChecklistOut:
    try:
        return StudentChecklistOut(**documents.checklist(db, institution_id=institution_id, student_id=student_id))
    except LookupError:
        raise_not_found("No such student at this institution.")


@router.post(
    "/institution/students/{student_id}/documents",
    response_model=DocumentSummaryOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    student_id: int,
    file: Annotated[UploadFile, File()],
    doc_type: Annotated[str, Form(max_length=48)],
    user: CurrentUser = Depends(require_role("institution")),
    institution_id: int = Depends(require_institution_scope),
    db: Session = Depends(get_db),
) -> DocumentSummaryOut:
    data = await file.read(documents.max_file_bytes() + 1)
    try:
        document = documents.store_document(
            db,
            institution_id=institution_id,
            student_id=student_id,
            doc_type=doc_type,
            filename=file.filename or doc_type,
            data=data,
            actor=user.username,
        )
    except LookupError:
        raise_not_found("No such student at this institution.")
    except DocumentRejected as exc:
        raise _rejected(exc)
    verify_document(db, document)
    reconcile_student(db, student_id)
    db.commit()
    return DocumentSummaryOut(**documents.document_summary(document))


@router.post("/institution/documents/bulk", response_model=BulkUploadReport)
async def upload_documents_zip(
    file: Annotated[UploadFile, File()],
    user: CurrentUser = Depends(require_role("institution")),
    institution_id: int = Depends(require_institution_scope),
    db: Session = Depends(get_db),
) -> BulkUploadReport:
    """A ZIP of ``<APAAR or student id>_<document type>.pdf`` files (or one folder per student)."""
    limit = int(float(documents.document_limits().get("zip_max_total_mb", 200)) * 1024 * 1024)
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise api_error(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "FILE_TOO_LARGE", "The ZIP is too large.")
    try:
        report = documents.import_zip(db, institution_id=institution_id, data=data, actor=user.username)
    except DocumentRejected as exc:
        raise _rejected(exc)
    changed: set[int] = set()
    for row in report["results"]:
        if row.get("document_id"):
            stored = db.get(StudentDocument, row["document_id"])
            verify_document(db, stored)
            changed.add(stored.student_id)
    if changed:
        reconcile_student_set(db, changed)
    db.commit()
    return BulkUploadReport(**report)


@router.get("/institution/documents/{document_id}/file")
def institution_document_file(
    document_id: int,
    user: CurrentUser = Depends(require_role("institution")),
    institution_id: int = Depends(require_institution_scope),
    db: Session = Depends(get_db),
) -> Response:
    document = db.get(StudentDocument, document_id)
    if document is None or document.institution_id != institution_id:
        raise_not_found("No such document for this institution.")
    return _serve(db, document, actor=user.username, role="institution", reason=None)


# --------------------------------------------------------------------------- AICTE officer


@router.post("/aicte/documents/{document_id}/file")
def officer_document_file(
    document_id: int,
    payload: DocumentViewRequest,
    user: CurrentUser = Depends(require_role("aicte_officer")),
    db: Session = Depends(get_db),
) -> Response:
    """An officer may open any document, but only with a reason, which the student sees."""
    document = db.get(StudentDocument, document_id)
    if document is None:
        raise_not_found("No such document.")
    return _serve(db, document, actor=user.username, role="aicte_officer", reason=payload.reason.strip())


@router.get("/aicte/documents/review", response_model=ReviewPage)
def document_review_queue(
    status_filter: Annotated[
        str, Query(alias="status", pattern="^(needs_review|rejected|auto_verified|verified|pending|all)$")
    ] = "needs_review",
    institution_id: Annotated[int | None, Query()] = None,
    doc_type: Annotated[str | None, Query(max_length=48)] = None,
    params: PageParams = Depends(page_params),
    user: CurrentUser = Depends(require_role("aicte_officer")),
    db: Session = Depends(get_db),
) -> ReviewPage:
    """The officer's queue. Masked: opening a case needs a reason."""
    rows = review_queue(db, status=status_filter, institution_id=institution_id, doc_type=doc_type)
    page_rows = rows[params.offset : params.offset + params.page_size]
    return ReviewPage(**paginate(page_rows, len(rows), params), counts=review_counts(db))


@router.post("/aicte/documents/{document_id}/case", response_model=CaseFileOut)
def document_case(
    document_id: int,
    payload: DocumentViewRequest,
    user: CurrentUser = Depends(require_role("aicte_officer")),
    db: Session = Depends(get_db),
) -> CaseFileOut:
    """Submitted data beside what the document says, the issuer's answer and the tamper
    checks. Shows identity data, so the reason is access-logged."""
    document = db.get(StudentDocument, document_id)
    if document is None:
        raise_not_found("No such document.")
    body = case_file(db, document=document, actor=user.username, reason=payload.reason.strip())
    db.commit()
    return CaseFileOut(**body)


@router.post("/aicte/documents/{document_id}/decision", response_model=ReviewDecisionOut)
def document_decision(
    document_id: int,
    payload: ReviewDecisionIn,
    user: CurrentUser = Depends(require_role("aicte_officer")),
    db: Session = Depends(get_db),
) -> ReviewDecisionOut:
    document = db.get(StudentDocument, document_id)
    if document is None:
        raise_not_found("No such document.")
    try:
        record_decision(db, document=document, decision=payload.decision, reason=payload.reason, actor=user.username)
    except ReviewError as exc:
        raise api_error(status.HTTP_409_CONFLICT, "CANNOT_DECIDE", str(exc))
    reconcile_student(db, document.student_id)
    db.commit()
    return ReviewDecisionOut(
        document_id=document.id,
        verification_status=document.verification_status,
        review_decision=document.review_decision or payload.decision,
        reviewed_by=user.username,
    )


@router.post("/aicte/documents/{document_id}/recheck", response_model=DocumentSummaryOut)
def document_recheck(
    document_id: int,
    user: CurrentUser = Depends(require_role("aicte_officer")),
    db: Session = Depends(get_db),
) -> DocumentSummaryOut:
    """Run every check again, e.g. after the issuer was unavailable. An officer's earlier
    decision is kept on record but the new automatic outcome replaces the status."""
    document = db.get(StudentDocument, document_id)
    if document is None:
        raise_not_found("No such document.")
    verify_document(db, document)
    reconcile_student(db, document.student_id)
    db.commit()
    return DocumentSummaryOut(**documents.document_summary(document))


# --------------------------------------------------------------------------- student


@router.get("/student/documents", response_model=StudentDocumentList)
def my_documents(
    user: CurrentUser = Depends(require_role("student")),
    db: Session = Depends(get_db),
) -> StudentDocumentList:
    if user.student_id is None:
        raise_not_found("This account is not linked to a student record.")
    types = document_types()
    rows = db.execute(
        select(StudentDocument, Institution)
        .join(Institution, Institution.id == StudentDocument.institution_id)
        .where(StudentDocument.student_id == user.student_id, StudentDocument.is_current.is_(True))
        .order_by(StudentDocument.created_at.desc())
    ).all()
    return StudentDocumentList(
        items=[
            StudentDocumentOut(
                id=document.id,
                doc_type=document.doc_type,
                label=types.get(document.doc_type, {}).get("label", document.doc_type),
                institution_name=institution.name,
                uploaded_at=document.created_at,
                status=documents.CHECKLIST_STATUS.get(document.verification_status, "uploaded"),
            )
            for document, institution in rows
        ]
    )


@router.get("/student/documents/{document_id}/file")
def my_document_file(
    document_id: int,
    user: CurrentUser = Depends(require_role("student")),
    db: Session = Depends(get_db),
) -> Response:
    document = db.get(StudentDocument, document_id)
    if document is None or user.student_id is None or document.student_id != user.student_id:
        raise_not_found("No such document.")
    return _serve(db, document, actor=user.username, role="student", reason="Student viewed their own document")
