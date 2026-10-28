"""Reconciliation and AICTE master-record routes (Phase 6).

* AICTE (viewer and officer): the per-institution dashboard, the filtered record list, one
  record's side-by-side page and the "Retrieve data" CSV of confirmed records. All masked;
  the viewer's counts below 5 are suppressed.
* AICTE officer or admin: import the master records (approvals and approved intake).
* Institution: its own reconciliation status and what to fix. Its ``institution_id`` comes
  from the JWT only.
"""
from __future__ import annotations

import math
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.core.access_log import log_access
from app.core.config import settings
from app.core.db import get_db
from app.core.errors import api_error, raise_not_found
from app.core.security import CurrentUser, require_institution_scope, require_role, suppress_small_counts
from app.schemas.common import PageParams, page_params, paginate
from app.schemas.reconciliation import (
    InstitutionViewOut,
    MasterImportOut,
    MasterStatusOut,
    ReconPage,
    RecordDetailOut,
    SummaryOut,
)
from app.services import master_records, reconciliation_views as views
from app.services.rules import known_academic_years

router = APIRouter(tags=["reconciliation"])

MAX_IMPORT_BYTES = 10 * 1024 * 1024
OVERALL_PATTERN = "^(confirmed|needs_review|rejected)$"
CHECK_PATTERN = "^(institution_approved|programme_approved|within_intake|apaar_verified|documents_verified|no_duplicate)$"


def _year(value: str | None) -> str:
    year = value or settings.current_academic_year
    if year not in known_academic_years():
        raise api_error(400, "UNKNOWN_ACADEMIC_YEAR", f"Unknown academic year '{year}'.")
    return year


# --------------------------------------------------------------------------- AICTE


@router.get("/aicte/reconciliation/summary", response_model=SummaryOut)
def reconciliation_summary(
    academic_year: Annotated[str | None, Query()] = None,
    state: Annotated[str | None, Query(max_length=64)] = None,
    q: Annotated[str | None, Query(max_length=64)] = None,
    user: CurrentUser = Depends(require_role("aicte_viewer", "aicte_officer")),
    db: Session = Depends(get_db),
) -> SummaryOut:
    payload = views.institution_summary(db, academic_year=_year(academic_year), state=state, q=q)
    return SummaryOut(**suppress_small_counts(payload, user.role))


@router.get("/aicte/reconciliation/records", response_model=ReconPage)
def reconciliation_records(
    institution_id: Annotated[int | None, Query()] = None,
    program_id: Annotated[int | None, Query()] = None,
    academic_year: Annotated[str | None, Query()] = None,
    overall: Annotated[str | None, Query(pattern=OVERALL_PATTERN)] = None,
    failing_check: Annotated[str | None, Query(pattern=CHECK_PATTERN)] = None,
    q: Annotated[str | None, Query(max_length=32)] = None,
    params: PageParams = Depends(page_params),
    user: CurrentUser = Depends(require_role("aicte_viewer", "aicte_officer")),
    db: Session = Depends(get_db),
) -> ReconPage:
    """Retrieve data: search by APAAR (full ID or last digits), institution, programme, year."""
    items, total = views.list_records(
        db, offset=params.offset, limit=params.page_size, failing_check=failing_check,
        institution_id=institution_id, program_id=program_id, academic_year=academic_year, overall=overall, q=q,
    )
    programmes = views.programme_options(db, institution_id) if institution_id is not None else []
    return ReconPage(**paginate(items, total, params), programmes=programmes)


@router.get("/aicte/reconciliation/records.csv", response_class=PlainTextResponse)
def reconciliation_records_csv(
    institution_id: Annotated[int | None, Query()] = None,
    program_id: Annotated[int | None, Query()] = None,
    academic_year: Annotated[str | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=32)] = None,
    user: CurrentUser = Depends(require_role("aicte_viewer", "aicte_officer")),
    db: Session = Depends(get_db),
) -> PlainTextResponse:
    """Confirmed records only, masked identifiers. The export is access-logged."""
    body = views.confirmed_csv(
        db, institution_id=institution_id, program_id=program_id, academic_year=academic_year, q=q
    )
    log_access(
        db, actor=user.username, role=user.role, action="export_confirmed_records",
        target=f"institution:{institution_id or 'all'}",
    )
    db.commit()
    return PlainTextResponse(
        content=body, media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="confirmed_records.csv"'},
    )


@router.get("/aicte/reconciliation/records/{enrolment_id}", response_model=RecordDetailOut)
def reconciliation_record(
    enrolment_id: int,
    user: CurrentUser = Depends(require_role("aicte_viewer", "aicte_officer")),
    db: Session = Depends(get_db),
) -> RecordDetailOut:
    detail = views.record_detail(db, enrolment_id)
    if detail is None:
        raise_not_found("No reconciliation record for that enrolment.")
    log_access(
        db, actor=user.username, role=user.role, action="view_reconciliation_record",
        target=f"student:{detail['student_id']}", student_id=detail["student_id"],
    )
    db.commit()
    return RecordDetailOut(**detail)


# --------------------------------------------------------------------------- master records


@router.get("/aicte/master", response_model=MasterStatusOut)
def master_status(
    user: CurrentUser = Depends(require_role("aicte_officer", "admin")),
    db: Session = Depends(get_db),
) -> MasterStatusOut:
    return MasterStatusOut.model_validate(master_records.master_status(db))


@router.post("/aicte/master/import", response_model=MasterImportOut, status_code=201)
async def master_import(
    kind: Annotated[str, Form(pattern="^(institutions|programmes)$")],
    file: Annotated[UploadFile, File()],
    user: CurrentUser = Depends(require_role("aicte_officer", "admin")),
    db: Session = Depends(get_db),
) -> MasterImportOut:
    """Import AICTE's own approvals (CSV or Excel). Bad rows are reported, not fatal."""
    data = await file.read(MAX_IMPORT_BYTES + 1)
    if len(data) > MAX_IMPORT_BYTES:
        raise api_error(413, "FILE_TOO_LARGE", "The import file is too large (10 MB at most).")
    try:
        record = master_records.import_master(
            db, kind=kind, filename=file.filename or f"{kind}.csv", data=data, actor=user.username
        )
    except master_records.MasterImportError as exc:
        db.rollback()
        raise api_error(400, "BAD_MASTER_FILE", str(exc))
    db.commit()
    return MasterImportOut.model_validate(record, from_attributes=True)


@router.get("/aicte/master/template/{kind}", response_class=PlainTextResponse)
def master_template(
    kind: str,
    user: CurrentUser = Depends(require_role("aicte_officer", "admin")),
) -> PlainTextResponse:
    if kind not in master_records.KINDS:
        raise_not_found("Unknown template.")
    return PlainTextResponse(master_records.template_csv(kind), media_type="text/csv")


# --------------------------------------------------------------------------- institution


@router.get("/institution/reconciliation", response_model=InstitutionViewOut)
def my_reconciliation(
    academic_year: Annotated[str | None, Query()] = None,
    overall: Annotated[str | None, Query(pattern=OVERALL_PATTERN)] = None,
    params: PageParams = Depends(page_params),
    user: CurrentUser = Depends(require_role("institution")),
    institution_id: int = Depends(require_institution_scope),
    db: Session = Depends(get_db),
) -> InstitutionViewOut:
    year = _year(academic_year)
    summary = views.institution_view(db, institution_id=institution_id, academic_year=year)
    items, total = views.list_records(
        db, offset=params.offset, limit=params.page_size, institution_id=institution_id,
        academic_year=year, overall=overall,
    )
    pages = max(1, math.ceil(total / params.page_size)) if total else 0
    return InstitutionViewOut(
        **summary, items=items, page=params.page, page_size=params.page_size, total=total, total_pages=pages
    )
