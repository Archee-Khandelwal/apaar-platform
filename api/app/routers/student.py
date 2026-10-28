"""Student routes.

``student_id`` comes from the JWT only — no student id appears in any path, query or
body, so one student can never read another's record (CLAUDE.md section 5 rule 5 applied
to students).
"""
from __future__ import annotations

import base64
import io
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import log_audit
from app.core.config import settings
from app.core.crypto import vault_decrypt
from app.core.db import get_db
from app.core.errors import api_error, raise_not_found
from app.core.security import CurrentUser, require_role
from app.models.core import (
    AccessLog,
    Consent,
    CorrectionRequest,
    Enrolment,
    Flag,
    Institution,
    Program,
    Student,
    Upload,
    Vault,
)
from app.schemas.common import PageParams, page_params, paginate
from app.schemas.student import (
    AccessLogPage,
    ApproveConsentRequest,
    ConsentActionResponse,
    ConsentPage,
    CorrectionOut,
    CorrectionPage,
    CorrectionRequestIn,
    DenyConsentRequest,
    IdCardOut,
    StudentMeOut,
)
from app.services.consent import (
    approve_consent,
    consent_rows,
    deny_consent,
    expire_stale,
    revoke_consent,
)
from app.services.flags import upsert_flag
from app.services.tokens import issue_token

router = APIRouter(prefix="/student", tags=["student"])


# The access log shows a role label, never another person's username.
ROLE_LABELS = {
    "aicte_officer": "AICTE Officer",
    "aicte_viewer": "AICTE Analyst",
    "institution": "Your institution",
    "verifier": "Employer / verifier",
    "student": "You",
    "admin": "Platform operator",
}


def _require_student(user: CurrentUser) -> int:
    if user.student_id is None:
        raise api_error(
            status.HTTP_403_FORBIDDEN,
            "TENANT_SCOPE_VIOLATION",
            "This account is not linked to a student record.",
        )
    return user.student_id


def _own_enrolment(db: Session, enrolment_id: int, student_id: int) -> Enrolment:
    enrolment = db.get(Enrolment, enrolment_id)
    if enrolment is None or enrolment.student_id != student_id:
        raise_not_found("No such enrolment for this student.")
    return enrolment


@router.get("/me", response_model=StudentMeOut)
def me(
    user: CurrentUser = Depends(require_role("student")),
    db: Session = Depends(get_db),
) -> StudentMeOut:
    """What the institutions have reported about this student."""
    student_id = _require_student(user)
    student = db.get(Student, student_id)
    if student is None:  # pragma: no cover
        raise_not_found("Student record not found.")
    vault = db.execute(select(Vault).where(Vault.student_id == student_id)).scalar_one_or_none()

    enrolments: list[dict[str, Any]] = []
    for enrolment, program, institution in db.execute(
        select(Enrolment, Program, Institution)
        .join(Program, Program.id == Enrolment.program_id)
        .join(Institution, Institution.id == Enrolment.institution_id)
        .where(Enrolment.student_id == student_id)
        .order_by(Enrolment.academic_year.desc(), Enrolment.id.asc())
    ).all():
        upload = db.get(Upload, enrolment.upload_id) if enrolment.upload_id else None
        enrolments.append(
            {
                "id": enrolment.id,
                "institution_name": institution.name,
                "program": f"{program.course} — {program.branch}",
                "mode": program.mode,
                "academic_year": enrolment.academic_year,
                "year_of_study": enrolment.year_of_study,
                "admission_type": enrolment.admission_type,
                "status": enrolment.status,
                "admitted_on": enrolment.admitted_on,
                "reported_by_upload_at": upload.created_at if upload else None,
                "version": enrolment.version,
            }
        )

    open_cases = [
        {
            "flag_id": flag.id,
            "type": flag.type,
            "status": flag.status,
            "created_at": flag.created_at,
        }
        for flag in db.execute(
            select(Flag).where(
                Flag.student_id == student_id,
                Flag.type == "STUDENT_CORRECTION",
            )
        ).scalars()
    ]
    expire_stale(db)
    pending = db.scalar(
        select(func.count())
        .select_from(Consent)
        .where(Consent.student_id == student_id, Consent.status == "pending")
    ) or 0
    db.commit()

    return StudentMeOut(
        student={
            "student_id": student.id,
            "apaar_masked": student.apaar_masked,
            "apaar_status": student.apaar_status,
            "name": vault_decrypt(vault.name_enc) if vault else None,
            "dob": vault_decrypt(vault.dob_enc) if vault else None,
            "is_minor": student.is_minor,
            "nationality_status": student.nationality_status,
            "category": student.category,
            "gender": student.gender,
        },
        enrolments=enrolments,
        open_cases=open_cases,
        pending_consents=pending,
    )


@router.post("/corrections", response_model=CorrectionOut, status_code=status.HTTP_201_CREATED)
def request_correction(
    payload: CorrectionRequestIn,
    user: CurrentUser = Depends(require_role("student")),
    db: Session = Depends(get_db),
) -> CorrectionOut:
    """Ask the institution to correct a field. Lands in their flag inbox."""
    student_id = _require_student(user)
    if payload.enrolment_id is not None:
        enrolment = _own_enrolment(db, payload.enrolment_id, student_id)
        institution_id = enrolment.institution_id
    else:
        enrolment = db.execute(
            select(Enrolment)
            .where(Enrolment.student_id == student_id)
            .order_by(Enrolment.academic_year.desc())
            .limit(1)
        ).scalar_one_or_none()
        if enrolment is None:
            raise_not_found("No enrolment on record to correct.")
        institution_id = enrolment.institution_id

    correction = CorrectionRequest(
        student_id=student_id,
        institution_id=institution_id,
        enrolment_id=enrolment.id,
        field=payload.field.strip(),
        correct_value=payload.correct_value.strip(),
        note=payload.note,
        status="sent_to_institution",
    )
    db.add(correction)
    db.flush()

    student = db.get(Student, student_id)
    upsert_flag(
        db,
        type="STUDENT_CORRECTION",
        dedupe_key=f"correction:{correction.id}",
        severity="low",
        title=f"Student correction request: {correction.field}",
        explanation=(
            f"The student holding {student.apaar_masked if student else 'this APAAR ID'} asks the "
            f"institution to correct '{correction.field}' to '{correction.correct_value}'."
            + (f" Note: {payload.note}" if payload.note else "")
        ),
        evidence={
            "field": correction.field,
            "correct_value": correction.correct_value,
            "note": payload.note,
            "correction_id": correction.id,
            "raised_by": "student",
        },
        institution_id=institution_id,
        student_id=student_id,
        enrolment_id=enrolment.id,
        academic_year=enrolment.academic_year,
    )
    log_audit(
        db,
        actor=user.username,
        role="student",
        action="correction_requested",
        target=f"correction:{correction.id}",
        payload={"field": correction.field},
    )
    db.commit()

    institution = db.get(Institution, institution_id)
    return CorrectionOut(
        correction_id=correction.id,
        status=correction.status,
        institution_name=institution.name if institution else "—",
        field=correction.field,
        correct_value=correction.correct_value,
        response_note=correction.response_note,
        created_at=correction.created_at,
    )


@router.get("/corrections", response_model=CorrectionPage)
def list_corrections(
    params: PageParams = Depends(page_params),
    user: CurrentUser = Depends(require_role("student")),
    db: Session = Depends(get_db),
) -> CorrectionPage:
    student_id = _require_student(user)
    rows = list(
        db.execute(
            select(CorrectionRequest, Institution)
            .join(Institution, Institution.id == CorrectionRequest.institution_id)
            .where(CorrectionRequest.student_id == student_id)
            .order_by(CorrectionRequest.created_at.desc())
        ).all()
    )
    total = len(rows)
    page_rows = rows[params.offset : params.offset + params.page_size]
    items = [
        {
            "correction_id": correction.id,
            "status": correction.status,
            "institution_name": institution.name,
            "field": correction.field,
            "correct_value": correction.correct_value,
            "response_note": correction.response_note,
            "created_at": correction.created_at,
        }
        for correction, institution in page_rows
    ]
    return CorrectionPage(
        **paginate(items, total, PageParams(page=params.page, page_size=params.page_size, sort="-created_at"))
    )


@router.get("/access-log", response_model=AccessLogPage)
def my_access_log(
    action: Annotated[str | None, Query()] = None,
    params: PageParams = Depends(page_params),
    user: CurrentUser = Depends(require_role("student")),
    db: Session = Depends(get_db),
) -> AccessLogPage:
    """"Who accessed my data." Actors appear as role labels, not usernames."""
    student_id = _require_student(user)
    conditions = [AccessLog.student_id == student_id]
    if action:
        conditions.append(AccessLog.action == action)

    total = db.scalar(select(func.count()).select_from(AccessLog).where(*conditions)) or 0
    rows = db.execute(
        select(AccessLog)
        .where(*conditions)
        .order_by(AccessLog.created_at.desc(), AccessLog.id.desc())
        .offset(params.offset)
        .limit(params.page_size)
    ).scalars()

    items = [
        {
            "id": row.id,
            "at": row.created_at,
            "actor_role": row.role,
            "actor_label": ROLE_LABELS.get(row.role, row.role),
            "action": row.action,
            "reason": row.reason,
            "purpose": row.purpose,
            "target": row.target,
        }
        for row in rows
    ]
    return AccessLogPage(
        **paginate(items, total, PageParams(page=params.page, page_size=params.page_size, sort="-created_at"))
    )


# --------------------------------------------------------------------------- consent


def _own_consent(db: Session, consent_id: int, student_id: int) -> Consent:
    consent = db.get(Consent, consent_id)
    if consent is None or consent.student_id != student_id:
        raise_not_found("No such consent request for this student.")
    return consent


@router.get("/consents", response_model=ConsentPage)
def list_consents(
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    params: PageParams = Depends(page_params),
    user: CurrentUser = Depends(require_role("student")),
    db: Session = Depends(get_db),
) -> ConsentPage:
    student_id = _require_student(user)
    rows = consent_rows(db, student_id=student_id, status=status_filter)
    db.commit()
    total = len(rows)
    page_rows = rows[params.offset : params.offset + params.page_size]
    return ConsentPage(
        **paginate(
            page_rows, total, PageParams(page=params.page, page_size=params.page_size, sort="-requested_at")
        )
    )


@router.post("/consents/{consent_id}/approve", response_model=ConsentActionResponse)
def approve(
    consent_id: int,
    payload: ApproveConsentRequest | None = None,
    user: CurrentUser = Depends(require_role("student")),
    db: Session = Depends(get_db),
) -> ConsentActionResponse:
    student_id = _require_student(user)
    consent = _own_consent(db, consent_id, student_id)
    if consent.status != "pending":
        raise api_error(
            status.HTTP_409_CONFLICT, "CONFLICT", f"This request is already {consent.status}."
        )
    result = approve_consent(
        db,
        consent=consent,
        actor=user.username,
        validity_minutes=payload.validity_minutes if payload else None,
    )
    db.commit()
    return ConsentActionResponse(
        consent_id=result["consent_id"],
        status="approved",
        approved_at=result["approved_at"],
        expires_at=result["expires_at"],
        shared_fields=result["shared_fields"],
    )


@router.post("/consents/{consent_id}/deny", response_model=ConsentActionResponse)
def deny(
    consent_id: int,
    payload: DenyConsentRequest | None = None,
    user: CurrentUser = Depends(require_role("student")),
    db: Session = Depends(get_db),
) -> ConsentActionResponse:
    student_id = _require_student(user)
    consent = _own_consent(db, consent_id, student_id)
    if consent.status != "pending":
        raise api_error(
            status.HTTP_409_CONFLICT, "CONFLICT", f"This request is already {consent.status}."
        )
    result = deny_consent(
        db, consent=consent, actor=user.username, reason=payload.reason if payload else None
    )
    db.commit()
    return ConsentActionResponse(
        consent_id=result["consent_id"], status="denied", denied_at=result["denied_at"]
    )


@router.post("/consents/{consent_id}/revoke", response_model=ConsentActionResponse)
def revoke(
    consent_id: int,
    user: CurrentUser = Depends(require_role("student")),
    db: Session = Depends(get_db),
) -> ConsentActionResponse:
    """Revoking invalidates any token already issued for this consent."""
    student_id = _require_student(user)
    consent = _own_consent(db, consent_id, student_id)
    if consent.status not in ("approved", "pending"):
        raise api_error(
            status.HTTP_409_CONFLICT,
            "CONFLICT",
            f"A {consent.status} consent cannot be revoked.",
        )
    result = revoke_consent(db, consent=consent, actor=user.username)
    db.commit()
    return ConsentActionResponse(
        consent_id=result["consent_id"],
        status="revoked",
        revoked_at=result["revoked_at"],
        tokens_invalidated=result["tokens_invalidated"],
    )


# --------------------------------------------------------------------------- ID card


@router.get("/id-card", response_model=IdCardOut)
def id_card(
    user: CurrentUser = Depends(require_role("student")),
    db: Session = Depends(get_db),
) -> IdCardOut:
    """Masked APAAR plus a QR holding a short-lived signed token."""
    import qrcode

    student_id = _require_student(user)
    student = db.get(Student, student_id)
    if student is None:  # pragma: no cover
        raise_not_found("Student record not found.")
    vault = db.execute(select(Vault).where(Vault.student_id == student_id)).scalar_one_or_none()

    row = db.execute(
        select(Enrolment, Program, Institution)
        .join(Program, Program.id == Enrolment.program_id)
        .join(Institution, Institution.id == Enrolment.institution_id)
        .where(Enrolment.student_id == student_id, Enrolment.status.in_(("admitted", "completed")))
        .order_by(Enrolment.academic_year.desc())
        .limit(1)
    ).first()

    token, expires_at = issue_token(student_id=student_id)
    verify_url = f"{settings.web_url}/verify?token={token}"

    image = qrcode.make(verify_url)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    qr_base64 = base64.b64encode(buffer.getvalue()).decode("ascii")

    enrolment, program, institution = row if row else (None, None, None)
    return IdCardOut(
        apaar_masked=student.apaar_masked,
        name=vault_decrypt(vault.name_enc) if vault else None,
        institution_name=institution.name if institution else None,
        program=f"{program.course} — {program.branch}" if program else None,
        academic_year=enrolment.academic_year if enrolment else None,
        year_of_study=enrolment.year_of_study if enrolment else None,
        status=enrolment.status if enrolment else None,
        is_minor=student.is_minor,
        token=token,
        token_expires_at=expires_at,
        qr_png_base64=qr_base64,
        verify_url=verify_url,
    )


# --------------------------------------------------------------------------- degree certificates


@router.get("/degree-certificates")
def my_degree_certificates(
    user: CurrentUser = Depends(require_role("student")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """The student's own issued degree certificates, with the QR that verifies each."""
    from app.models.core import IssuedDocument
    from app.services import degree_certificate
    from app.services.documents import token_for, verify_url

    student_id = _require_student(user)
    documents = db.execute(
        select(IssuedDocument)
        .where(IssuedDocument.student_id == student_id, IssuedDocument.kind == degree_certificate.KIND)
        .order_by(IssuedDocument.created_at.desc())
    ).scalars()
    items = []
    for document in documents:
        url = verify_url(token_for(document))
        items.append(
            {
                "serial": document.serial,
                "status": document.status,
                "issued_at": document.created_at,
                "institution": document.claims.get("inst"),
                "program": document.claims.get("prog"),
                "academic_year": document.claims.get("yr"),
                "verify_url": url,
                "qr": degree_certificate._qr_data_uri(url),
            }
        )
    return {"items": items}


@router.get("/degree-certificates/{serial}")
def my_degree_certificate_file(
    serial: str,
    user: CurrentUser = Depends(require_role("student")),
    db: Session = Depends(get_db),
):
    """The printable PDF of one of the student's own certificates (masked identity only)."""
    from fastapi import Response

    from app.models.core import IssuedDocument
    from app.services import degree_certificate
    from app.services.documents import token_for

    student_id = _require_student(user)
    document = db.execute(
        select(IssuedDocument).where(
            IssuedDocument.serial == serial, IssuedDocument.kind == degree_certificate.KIND
        )
    ).scalar_one_or_none()
    if document is None or document.student_id != student_id:
        raise_not_found("No such certificate.")
    if document.status != "valid":
        raise api_error(status.HTTP_409_CONFLICT, "REVOKED", "This certificate has been revoked.")
    identity = {"apaar": document.claims["apaar"], "name": document.claims["name"]}
    return Response(
        content=degree_certificate.render_pdf(document, token_for(document), identity),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{document.serial}.pdf"'},
    )
