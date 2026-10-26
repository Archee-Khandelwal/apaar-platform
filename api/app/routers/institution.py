"""Institution routes.

Tenant isolation: ``institution_id`` comes from ``require_institution_scope`` (the JWT)
and never from a path, query or body parameter (CLAUDE.md section 5 rule 5).
"""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.errors import api_error, raise_not_found
from app.core.security import CurrentUser, require_institution_scope, require_role
from app.models.core import Institution, Program, Upload
from app.schemas.common import PageParams, page_params, paginate
from app.schemas.institution import (
    ConfirmMappingRequest,
    InstitutionProfile,
    ProgramOut,
    QualityReport,
    SeatMatrixOut,
    UploadCreateResponse,
    UploadPage,
)
from app.services import upload as upload_service
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
