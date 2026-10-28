"""Institution routes.

Tenant isolation: ``institution_id`` comes from ``require_institution_scope`` (the JWT)
and never from a path, query or body parameter (CLAUDE.md section 5 rule 5).
"""
from __future__ import annotations

from collections import Counter
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import log_audit
from app.core.config import settings
from app.core.db import get_db
from app.core.errors import api_error, raise_not_found
from app.core.security import CurrentUser, require_institution_scope, require_role
from app.models.core import (
    Enrolment,
    EnrolmentHistory,
    Flag,
    Institution,
    IssuedDocument,
    Program,
    Student,
    Upload,
)
from app.models.enums import ACTIVE_ENROLMENT_STATUSES, ENROLMENT_STATUSES, OPEN_FLAG_STATUSES
from app.schemas.common import PageParams, page_params, paginate
from app.schemas.institution import (
    ConfirmMappingRequest,
    DegreeCertificateIssue,
    DegreeCertificateList,
    DegreeCertificateOut,
    EnrolmentStatusResponse,
    EnrolmentStatusUpdate,
    InstitutionDashboard,
    InstitutionFlagOut,
    InstitutionFlagPage,
    InstitutionFlagUpdate,
    InstitutionProfile,
    ProgramOut,
    QualityReport,
    RevokeRequest,
    SeatMatrixOut,
    StudentPage,
    UploadCreateResponse,
    UploadPage,
)
from app.services import upload as upload_service
from app.services.cases import (
    ALLOWED_INSTITUTION_STATUSES,
    build_flag_query,
    order_flags,
    update_flag,
)
from app.services import degree_certificate
from app.services.certificate import eligibility, render_certificate
from app.services.detectors import run_all_detectors
from app.services.documents import DocumentError, revoke_document, token_for, verify_url
from app.services.flags import sanitise_for_institution
from app.services.intake import institution_seat_matrix
from app.services.upload import UploadError

router = APIRouter(prefix="/institution", tags=["institution"])

UPLOAD_SORTS = {
    "created_at": Upload.created_at,
    "quality_score": Upload.quality_score,
    "rows_total": Upload.rows_total,
}


def _own_upload(db: Session, upload_id: int, institution_id: int) -> Upload:
    upload = db.get(Upload, upload_id)
    if upload is None or upload.institution_id != institution_id:
        # 404 rather than 403: we do not confirm another institution's upload exists.
        raise_not_found("No such upload for this institution.")
    return upload


@router.get("/me", response_model=InstitutionProfile)
def my_institution(
    institution_id: int = Depends(require_institution_scope),
    db: Session = Depends(get_db),
) -> InstitutionProfile:
    institution = db.get(Institution, institution_id)
    if institution is None:  # pragma: no cover - a JWT always points at a real row
        raise_not_found("Institution not found.")
    programs = db.execute(
        select(Program).where(Program.institution_id == institution_id).order_by(Program.id)
    ).scalars()
    return InstitutionProfile(
        id=institution.id,
        aicte_permanent_id=institution.aicte_permanent_id,
        name=institution.name,
        state=institution.state,
        region=institution.region,
        type=institution.type,
        programs=[
            ProgramOut(
                id=program.id,
                course=program.course,
                branch=program.branch,
                level=program.level,
                mode=program.mode,
            )
            for program in programs
        ],
    )


@router.get("/template", response_class=PlainTextResponse)
def download_template(
    institution_id: int = Depends(require_institution_scope),
) -> PlainTextResponse:
    return PlainTextResponse(
        content=upload_service.template_csv(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="apaar_upload_template.csv"'},
    )


@router.post(
    "/uploads", response_model=UploadCreateResponse, status_code=status.HTTP_201_CREATED
)
async def create_upload(
    file: Annotated[UploadFile, File()],
    academic_year: Annotated[str | None, Form()] = None,
    user: CurrentUser = Depends(require_role("institution")),
    institution_id: int = Depends(require_institution_scope),
    db: Session = Depends(get_db),
) -> UploadCreateResponse:
    """Parse the file and propose a column mapping. Nothing is validated or stored yet."""
    content = await file.read()
    if not content:
        raise api_error(
            status.HTTP_400_BAD_REQUEST, "VALIDATION_ERROR", "The uploaded file is empty."
        )
    try:
        result = upload_service.create_upload(
            db,
            institution_id=institution_id,
            filename=file.filename or "upload.xlsx",
            content=content,
            academic_year=academic_year,
            actor=user.username,
        )
    except UploadError as exc:
        raise api_error(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "UNSUPPORTED_FILE", str(exc))
    db.commit()
    return UploadCreateResponse(**result)


@router.post("/uploads/{upload_id}/confirm-mapping", response_model=QualityReport)
def confirm_mapping(
    upload_id: int,
    payload: ConfirmMappingRequest,
    user: CurrentUser = Depends(require_role("institution")),
    institution_id: int = Depends(require_institution_scope),
    db: Session = Depends(get_db),
) -> QualityReport:
    """Validate every row, store what is valid, and return the quality report."""
    upload = _own_upload(db, upload_id, institution_id)
    if upload.state == "completed":
        raise api_error(
            status.HTTP_409_CONFLICT,
            "CONFLICT",
            "This upload has already been processed. Upload the file again to re-import it.",
        )
    try:
        report = upload_service.confirm_mapping(
            db,
            upload=upload,
            mapping=payload.mapping,
            defaults=payload.defaults,
            actor=user.username,
        )
    except UploadError as exc:
        db.rollback()
        raise api_error(status.HTTP_400_BAD_REQUEST, "VALIDATION_ERROR", str(exc))
    db.commit()
    return QualityReport(**report)


@router.get("/uploads", response_model=UploadPage)
def list_uploads(
    state: Annotated[str | None, Query()] = None,
    academic_year: Annotated[str | None, Query()] = None,
    params: PageParams = Depends(page_params),
    institution_id: int = Depends(require_institution_scope),
    db: Session = Depends(get_db),
) -> UploadPage:
    conditions = [Upload.institution_id == institution_id]
    if state:
        conditions.append(Upload.state == state)
    if academic_year:
        conditions.append(Upload.academic_year == academic_year)

    total = db.scalar(select(func.count()).select_from(Upload).where(*conditions)) or 0

    sort = params.sort or "-created_at"
    column = UPLOAD_SORTS.get(sort.lstrip("-"), Upload.created_at)
    order = column.desc() if sort.startswith("-") else column.asc()

    rows = db.execute(
        select(Upload)
        .where(*conditions)
        .order_by(order, Upload.id.desc())
        .offset(params.offset)
        .limit(params.page_size)
    ).scalars()

    items = [
        {
            "id": row.id,
            "filename": row.filename,
            "state": row.state,
            "academic_year": row.academic_year,
            "rows_total": row.rows_total,
            "rows_ok": row.rows_ok,
            "rows_error": row.rows_error,
            "rows_warning": row.rows_warning,
            "quality_score": row.quality_score,
            "created_at": row.created_at,
        }
        for row in rows
    ]
    return UploadPage(**paginate(items, total, PageParams(page=params.page, page_size=params.page_size, sort=sort)))


@router.get("/uploads/{upload_id}", response_model=QualityReport)
def get_upload(
    upload_id: int,
    institution_id: int = Depends(require_institution_scope),
    db: Session = Depends(get_db),
) -> QualityReport:
    upload = _own_upload(db, upload_id, institution_id)
    return QualityReport(**upload_service.quality_report(upload))


@router.get("/uploads/{upload_id}/errors.csv", response_class=PlainTextResponse)
def download_errors(
    upload_id: int,
    institution_id: int = Depends(require_institution_scope),
    db: Session = Depends(get_db),
) -> PlainTextResponse:
    upload = _own_upload(db, upload_id, institution_id)
    return PlainTextResponse(
        content=upload_service.errors_csv(upload),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="upload_{upload_id}_errors.csv"'
        },
    )


@router.get("/seat-matrix", response_model=SeatMatrixOut)
def seat_matrix(
    academic_year: Annotated[str, Query(min_length=7, max_length=7)],
    institution_id: int = Depends(require_institution_scope),
    db: Session = Depends(get_db),
) -> SeatMatrixOut:
    """Approved intake vs regular vs each supernumerary bucket vs excess, per programme."""
    return SeatMatrixOut(
        **institution_seat_matrix(
            db, institution_id=institution_id, academic_year=academic_year
        )
    )


# --------------------------------------------------------------------------- flags


@router.get("/flags", response_model=InstitutionFlagPage)
def my_flags(
    type: Annotated[list[str] | None, Query()] = None,
    severity: Annotated[list[str] | None, Query()] = None,
    status: Annotated[list[str] | None, Query()] = None,
    academic_year: Annotated[str | None, Query()] = None,
    params: PageParams = Depends(page_params),
    institution_id: int = Depends(require_institution_scope),
    db: Session = Depends(get_db),
) -> InstitutionFlagPage:
    """Own flags only. Another institution is never named (CLAUDE.md rule 10)."""
    statement = build_flag_query(
        types=type,
        severities=severity,
        statuses=status,
        academic_year=academic_year,
        institution_id=institution_id,
    )
    rows = list(db.execute(order_flags(statement, params.sort)).all())
    total = len(rows)
    page_rows = rows[params.offset : params.offset + params.page_size]
    items = [sanitise_for_institution(flag) for flag, _institution in page_rows]
    return InstitutionFlagPage(
        **paginate(
            items,
            total,
            PageParams(page=params.page, page_size=params.page_size, sort=params.sort or "-severity"),
        )
    )


@router.patch("/flags/{flag_id}", response_model=InstitutionFlagOut)
def update_my_flag(
    flag_id: int,
    payload: InstitutionFlagUpdate,
    user: CurrentUser = Depends(require_role("institution")),
    institution_id: int = Depends(require_institution_scope),
    db: Session = Depends(get_db),
) -> InstitutionFlagOut:
    """An institution may mark its own flag under review or resolved, and add a note.

    Escalating and dismissing stay with AICTE.
    """
    flag = db.get(Flag, flag_id)
    if flag is None or flag.institution_id != institution_id:
        raise_not_found("No such flag for this institution.")
    if payload.status is not None and payload.status not in ALLOWED_INSTITUTION_STATUSES:
        raise api_error(
            status.HTTP_403_FORBIDDEN,
            "FORBIDDEN_ROLE",
            "An institution may only set a flag to under_review or resolved; "
            "escalating or dismissing is done by AICTE.",
        )
    if payload.status == "resolved" and not payload.note:
        raise api_error(
            status.HTTP_400_BAD_REQUEST,
            "REASON_REQUIRED",
            "Say what was corrected before marking a finding resolved.",
        )

    flag, _audit_id = update_flag(
        db,
        flag=flag,
        actor=user.username,
        role="institution",
        status=payload.status,
        note=payload.note,
    )
    db.commit()
    return InstitutionFlagOut(**sanitise_for_institution(flag))


# --------------------------------------------------------------------------- students


@router.get("/students", response_model=StudentPage)
def my_students(
    q: Annotated[str | None, Query(max_length=40)] = None,
    program_id: Annotated[int | None, Query()] = None,
    academic_year: Annotated[str | None, Query()] = None,
    year_of_study: Annotated[int | None, Query(ge=1, le=6)] = None,
    admission_type: Annotated[str | None, Query()] = None,
    apaar_status: Annotated[str | None, Query()] = None,
    enrolment_status: Annotated[str | None, Query()] = None,
    params: PageParams = Depends(page_params),
    institution_id: int = Depends(require_institution_scope),
    db: Session = Depends(get_db),
) -> StudentPage:
    """Own students, masked. Raw identifiers are never returned here."""
    conditions = [Enrolment.institution_id == institution_id]
    if program_id is not None:
        conditions.append(Enrolment.program_id == program_id)
    if academic_year:
        conditions.append(Enrolment.academic_year == academic_year)
    if year_of_study is not None:
        conditions.append(Enrolment.year_of_study == year_of_study)
    if admission_type:
        conditions.append(Enrolment.admission_type == admission_type)
    if enrolment_status:
        conditions.append(Enrolment.status == enrolment_status)
    if apaar_status:
        conditions.append(Student.apaar_status == apaar_status)
    if q:
        pattern = f"%{q.strip()}%"
        conditions.append(Student.apaar_masked.ilike(pattern) | Student.name_masked.ilike(pattern))

    statement = (
        select(Enrolment, Student, Program)
        .join(Student, Student.id == Enrolment.student_id)
        .join(Program, Program.id == Enrolment.program_id)
        .where(*conditions)
    )
    total = len(list(db.execute(statement).all()))
    rows = list(
        db.execute(
            statement.order_by(Student.name_masked.asc(), Enrolment.id.asc())
            .offset(params.offset)
            .limit(params.page_size)
        ).all()
    )

    flag_counts = {
        row[0]: int(row[1])
        for row in db.execute(
            select(Flag.student_id, func.count())
            .where(Flag.institution_id == institution_id, Flag.student_id.is_not(None))
            .group_by(Flag.student_id)
        ).all()
    }

    items = [
        {
            "student_id": student.id,
            "apaar_masked": student.apaar_masked,
            "apaar_status": student.apaar_status,
            "name_masked": student.name_masked,
            "gender": student.gender,
            "category": student.category,
            "nationality_status": student.nationality_status,
            "dob_year": student.dob_year,
            "is_minor": student.is_minor,
            "flag_count": flag_counts.get(student.id, 0),
            "student_confirmation": enrolment.student_confirmation,
            "enrolment": {
                "id": enrolment.id,
                "program_id": program.id,
                "course": program.course,
                "branch": program.branch,
                "academic_year": enrolment.academic_year,
                "year_of_study": enrolment.year_of_study,
                "admission_type": enrolment.admission_type,
                "status": enrolment.status,
                "admitted_on": enrolment.admitted_on,
                "version": enrolment.version,
            },
        }
        for enrolment, student, program in rows
    ]
    return StudentPage(
        **paginate(items, total, PageParams(page=params.page, page_size=params.page_size, sort="name_masked"))
    )


@router.patch("/enrolments/{enrolment_id}/status", response_model=EnrolmentStatusResponse)
def change_enrolment_status(
    enrolment_id: int,
    payload: EnrolmentStatusUpdate,
    user: CurrentUser = Depends(require_role("institution")),
    institution_id: int = Depends(require_institution_scope),
    db: Session = Depends(get_db),
) -> EnrolmentStatusResponse:
    """Cancel / migrate / drop / complete an enrolment, with a reason. Versioned."""
    enrolment = db.get(Enrolment, enrolment_id)
    if enrolment is None or enrolment.institution_id != institution_id:
        raise_not_found("No such enrolment for this institution.")
    if payload.status not in ENROLMENT_STATUSES:
        raise api_error(
            422, "VALIDATION_ERROR", f"status must be one of {', '.join(ENROLMENT_STATUSES)}."
        )
    if len(payload.reason.strip()) < 10:
        raise api_error(
            status.HTTP_400_BAD_REQUEST,
            "REASON_REQUIRED",
            "A reason of at least 10 characters is required for a status change.",
        )

    previous = enrolment.status
    if previous == payload.status:
        raise api_error(
            status.HTTP_409_CONFLICT, "CONFLICT", f"This enrolment is already {previous}."
        )

    enrolment.status = payload.status
    enrolment.version += 1
    db.add(
        EnrolmentHistory(
            enrolment_id=enrolment.id,
            version=enrolment.version,
            from_status=previous,
            to_status=payload.status,
            reason=payload.reason.strip(),
            effective_date=payload.effective_date,
            changed_by=user.username,
        )
    )
    entry = log_audit(
        db,
        actor=user.username,
        role="institution",
        action="enrolment_status_changed",
        target=f"enrolment:{enrolment.id}",
        payload={
            "from": previous,
            "to": payload.status,
            "reason": payload.reason.strip(),
            "version": enrolment.version,
        },
    )
    db.flush()

    # A cancellation can take a programme back under its approved intake.
    run_all_detectors(db, institution_id=institution_id, commit=False)
    db.commit()

    return EnrolmentStatusResponse(
        enrolment_id=enrolment.id,
        status=enrolment.status,
        previous_status=previous,
        version=enrolment.version,
        changed_at=entry.created_at,
        audit_log_id=entry.id,
    )


# --------------------------------------------------------------------------- certificate


@router.get("/compliance-certificate")
def compliance_certificate(
    academic_year: Annotated[str, Query(min_length=7, max_length=7)],
    format: Annotated[str, Query(pattern="^(html|json)$")] = "html",
    user: CurrentUser = Depends(require_role("institution")),
    institution_id: int = Depends(require_institution_scope),
    db: Session = Depends(get_db),
):
    """Printable HTML certificate, only when no high or critical finding is open."""
    status_payload = eligibility(
        db, institution_id=institution_id, academic_year=academic_year
    )
    if format == "json":
        return status_payload
    if not status_payload["eligible"]:
        raise api_error(
            status.HTTP_409_CONFLICT,
            "CERTIFICATE_NOT_ELIGIBLE",
            " ".join(status_payload["reasons"]),
            {"blocking_flags": status_payload["blocking_flags"]},
        )

    html = render_certificate(
        db,
        institution_id=institution_id,
        academic_year=academic_year,
        issued_to=user.display_name or user.username,
    )
    log_audit(
        db,
        actor=user.username,
        role="institution",
        action="certificate_issued",
        target=f"institution:{institution_id}",
        payload={"academic_year": academic_year},
    )
    db.commit()
    return HTMLResponse(content=html)


# --------------------------------------------------------------------------- degree certificates


def _own_certificate(db: Session, serial: str, institution_id: int) -> IssuedDocument:
    document = db.execute(
        select(IssuedDocument).where(
            IssuedDocument.serial == serial, IssuedDocument.kind == degree_certificate.KIND
        )
    ).scalar_one_or_none()
    if document is None or document.institution_id != institution_id:
        raise_not_found("No such certificate for this institution.")
    return document


def _certificate_out(document: IssuedDocument, token: str, created: bool) -> DegreeCertificateOut:
    base = f"/institution/degree-certificates/{document.serial}"
    return DegreeCertificateOut(
        serial=document.serial,
        status=document.status,
        created=created,
        issued_at=document.created_at,
        verify_url=verify_url(token),
        pdf_url=f"{base}?format=pdf",
        html_url=f"{base}?format=html",
    )


@router.get("/degree-certificates", response_model=DegreeCertificateList)
def list_degree_certificates(
    academic_year: Annotated[str | None, Query()] = None,
    institution_id: int = Depends(require_institution_scope),
    db: Session = Depends(get_db),
) -> DegreeCertificateList:
    """Completed enrolments, each with the certificate issued for it, if any."""
    return DegreeCertificateList(
        items=degree_certificate.completed_enrolments(
            db, institution_id=institution_id, academic_year=academic_year
        ),
        identity_display=settings.certificate_identity_display,
    )


@router.post(
    "/degree-certificates", response_model=DegreeCertificateOut, status_code=status.HTTP_201_CREATED
)
def issue_degree_certificate(
    payload: DegreeCertificateIssue,
    user: CurrentUser = Depends(require_role("institution")),
    institution_id: int = Depends(require_institution_scope),
    db: Session = Depends(get_db),
) -> DegreeCertificateOut:
    """Issue a signed degree certificate for one of this institution's completed enrolments.

    Idempotent: a second call for the same enrolment returns the certificate already issued.
    """
    try:
        document, token, created = degree_certificate.issue_for_enrolment(
            db, institution_id=institution_id, enrolment_id=payload.enrolment_id, actor=user.username
        )
    except LookupError:
        raise_not_found("No such enrolment for this institution.")
    except DocumentError as exc:
        raise api_error(status.HTTP_409_CONFLICT, "NOT_COMPLETED", str(exc))
    db.commit()
    return _certificate_out(document, token, created)


@router.get("/degree-certificates/{serial}")
def degree_certificate_file(
    serial: str,
    format: Annotated[str, Query(pattern="^(pdf|html)$")] = "pdf",
    user: CurrentUser = Depends(require_role("institution")),
    institution_id: int = Depends(require_institution_scope),
    db: Session = Depends(get_db),
):
    """The printable certificate, as PDF (default) or HTML."""
    document = _own_certificate(db, serial, institution_id)
    if document.status != "valid":
        raise api_error(status.HTTP_409_CONFLICT, "REVOKED", "This certificate has been revoked.")
    token = token_for(document)
    identity = degree_certificate.printed_identity(db, document=document, actor=user.username)
    db.commit()
    if format == "html":
        return HTMLResponse(content=degree_certificate.render_html(document, token, identity))
    return Response(
        content=degree_certificate.render_pdf(document, token, identity),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{document.serial}.pdf"'},
    )


@router.post("/degree-certificates/{serial}/revoke", response_model=DegreeCertificateOut)
def revoke_degree_certificate(
    serial: str,
    payload: RevokeRequest,
    user: CurrentUser = Depends(require_role("institution")),
    institution_id: int = Depends(require_institution_scope),
    db: Session = Depends(get_db),
) -> DegreeCertificateOut:
    """Withdraw a certificate. The public check reports it as revoked from then on."""
    document = _own_certificate(db, serial, institution_id)
    if document.status == "revoked":
        raise api_error(status.HTTP_409_CONFLICT, "CONFLICT", "This certificate is already revoked.")
    try:
        revoke_document(db, document=document, actor=user.username, role="institution", reason=payload.reason)
    except DocumentError as exc:
        raise api_error(status.HTTP_400_BAD_REQUEST, "REASON_REQUIRED", str(exc))
    db.commit()
    return _certificate_out(document, token_for(document), False)


# --------------------------------------------------------------------------- dashboard


@router.get("/dashboard", response_model=InstitutionDashboard)
def dashboard(
    academic_year: Annotated[str | None, Query()] = None,
    institution_id: int = Depends(require_institution_scope),
    db: Session = Depends(get_db),
) -> InstitutionDashboard:
    year = academic_year or settings.current_academic_year
    matrix = institution_seat_matrix(db, institution_id=institution_id, academic_year=year)

    uploads = list(
        db.execute(
            select(Upload)
            .where(Upload.institution_id == institution_id, Upload.quality_score.is_not(None))
            .order_by(Upload.created_at.asc())
        ).scalars()
    )
    flags = list(
        db.execute(
            select(Flag).where(
                Flag.institution_id == institution_id, Flag.status.in_(OPEN_FLAG_STATUSES)
            )
        ).scalars()
    )
    counts = Counter(flag.severity for flag in flags)
    certificate = eligibility(db, institution_id=institution_id, academic_year=year)

    return InstitutionDashboard(
        academic_year=year,
        students_reported=db.scalar(
            select(func.count(func.distinct(Enrolment.student_id))).where(
                Enrolment.institution_id == institution_id,
                Enrolment.academic_year == year,
                Enrolment.status.in_(ACTIVE_ENROLMENT_STATUSES),
            )
        )
        or 0,
        open_flags={severity: counts.get(severity, 0) for severity in ("low", "medium", "high", "critical")},
        latest_quality_score=uploads[-1].quality_score if uploads else None,
        quality_trend=[
            {
                "upload_id": upload.id,
                "created_at": upload.created_at,
                "quality_score": upload.quality_score,
            }
            for upload in uploads[-10:]
        ],
        seat_matrix_summary=matrix["totals"],
        compliance_certificate_eligible=certificate["eligible"],
        compliance_certificate_reasons=certificate["reasons"],
        last_upload_at=max((upload.created_at for upload in uploads), default=None),
    )
