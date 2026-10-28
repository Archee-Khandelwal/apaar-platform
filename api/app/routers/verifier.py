"""Verifier routes, and the public token check.

A verifier receives nothing until the student approves, and then only
``verified / programme / academic year`` (CLAUDE.md section 5 rule 11). The token check
at ``/verify/token/{token}`` is public, because that is the point of a QR code.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.access_log import log_access
from app.core.audit import log_audit
from app.core.db import get_db
from app.core.errors import api_error, raise_not_found
from app.core.security import CurrentUser, require_role
from app.models.core import User, VerificationRequest
from app.models.enums import VERIFIER_PURPOSES
from app.schemas.common import PageParams, page_params, paginate
from app.schemas.student import (
    DocumentCheckOut,
    PurposeOut,
    PurposesResponse,
    TokenCheckOut,
    VerificationPage,
    VerificationRequestIn,
    VerificationRequestOut,
    VerificationStatusOut,
)
from app.services.consent import create_verification_request, expire_stale
from app.services.documents import check_document
from app.services.tokens import verify_token

router = APIRouter(tags=["verifier"])


@router.get("/verifier/purposes", response_model=PurposesResponse)
def purposes(
    user: CurrentUser = Depends(require_role("verifier")),
) -> PurposesResponse:
    """The fixed list a request must choose from; free-text purposes are not accepted."""
    return PurposesResponse(
        purposes=[PurposeOut(value=value, label=label) for value, label in VERIFIER_PURPOSES.items()]
    )


@router.post(
    "/verifier/requests", response_model=VerificationRequestOut, status_code=status.HTTP_201_CREATED
)
def create_request(
    payload: VerificationRequestIn,
    user: CurrentUser = Depends(require_role("verifier")),
    db: Session = Depends(get_db),
) -> VerificationRequestOut:
    """Ask a student for consent. The APAAR ID is hashed on receipt and never stored raw.

    An unknown APAAR produces the same ``pending`` response as a known one, so this
    endpoint cannot be used to discover which APAAR IDs exist (Step-0 decision 10).
    """
    verifier = db.get(User, user.id)
    try:
        result = create_verification_request(
            db,
            verifier_user=verifier,
            apaar=payload.apaar,
            purpose=payload.purpose,
            note=payload.note,
        )
    except ValueError as exc:
        raise api_error(422, "VALIDATION_ERROR", str(exc))
    db.commit()
    return VerificationRequestOut(**result)


@router.get("/verifier/requests", response_model=VerificationPage)
def list_requests(
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    params: PageParams = Depends(page_params),
    user: CurrentUser = Depends(require_role("verifier")),
    db: Session = Depends(get_db),
) -> VerificationPage:
    expire_stale(db)
    db.commit()

    conditions = [VerificationRequest.verifier_user_id == user.id]
    if status_filter:
        conditions.append(VerificationRequest.status == status_filter)

    total = db.scalar(select(func.count()).select_from(VerificationRequest).where(*conditions)) or 0
    rows = db.execute(
        select(VerificationRequest)
        .where(*conditions)
        .order_by(VerificationRequest.created_at.desc())
        .offset(params.offset)
        .limit(params.page_size)
    ).scalars()

    items = [_request_out(row) for row in rows]
    return VerificationPage(
        **paginate(items, total, PageParams(page=params.page, page_size=params.page_size, sort="-created_at"))
    )


def _request_out(request: VerificationRequest) -> dict:
    return {
        "request_id": request.id,
        "status": request.status,
        "apaar_masked": request.apaar_masked,
        "purpose": request.purpose,
        "requested_at": request.created_at,
        "responded_at": request.responded_at,
        "expires_at": request.expires_at,
        # Only an approved request carries a result, and only the minimal one.
        "result": request.result if request.status == "approved" else None,
    }


@router.get("/verifier/requests/{request_id}", response_model=VerificationStatusOut)
def request_status(
    request_id: int,
    user: CurrentUser = Depends(require_role("verifier")),
    db: Session = Depends(get_db),
) -> VerificationStatusOut:
    expire_stale(db)
    request = db.get(VerificationRequest, request_id)
    if request is None or request.verifier_user_id != user.id:
        raise_not_found("No such verification request.")

    if request.status == "approved" and request.student_id is not None:
        # Reading an approved result is an access to that student's data.
        log_access(
            db,
            actor=user.username,
            role="verifier",
            action="verification_result_read",
            target=f"student:{request.student_id}",
            student_id=request.student_id,
            purpose=request.purpose,
            reason=f"Consented verification for {VERIFIER_PURPOSES.get(request.purpose, request.purpose)}.",
        )
    db.commit()
    return VerificationStatusOut(**_request_out(request))


# --------------------------------------------------------------------------- public check


@router.get("/verify/token/{token}", response_model=TokenCheckOut)
def check_token(token: str, db: Session = Depends(get_db)) -> TokenCheckOut:
    """Public QR / token check. Returns genuine | expired | revoked | invalid.

    Anything other than ``genuine`` returns the state and nothing else, so a failed
    check never leaks whether the token referred to a real student.
    """
    result = verify_token(db, token)
    log_audit(
        db,
        actor="public",
        role="verifier",
        action="token_checked",
        target="token",
        payload={"state": result["state"]},
    )
    db.commit()
    return TokenCheckOut(**result)


@router.get("/verify/document/{token}", response_model=DocumentCheckOut)
def check_signed_document(token: str, db: Session = Depends(get_db)) -> DocumentCheckOut:
    """Public check of a degree certificate or student record QR.

    Returns genuine | revoked | invalid. The claims returned are the masked ones already
    printed on the document, so the check reveals nothing the holder could not read.
    """
    result = check_document(db, token)
    log_audit(
        db,
        actor="public",
        role="verifier",
        action="document_checked",
        target=f"document:{result.get('serial') or 'unknown'}",
        payload={"state": result["state"], "kind": result.get("kind")},
    )
    db.commit()
    return DocumentCheckOut(**result)
