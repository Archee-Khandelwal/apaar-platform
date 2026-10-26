"""Consent lifecycle and the verifier flow (Step 13 of docs/PLAN.md).

The rule that shapes this module: **a verifier learns nothing until the student
approves** (CLAUDE.md section 5 rule 11). A request for an APAAR ID that does not exist
looks exactly like one that does, so the response cannot be used to probe whether an
APAAR is registered (Step-0 decision 10).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.access_log import log_access
from app.core.audit import log_audit
from app.core.config import settings
from app.core.crypto import hash_apaar, mask_apaar
from app.models.core import Consent, Enrolment, Institution, Program, Student, VerificationRequest
from app.models.enums import ACTIVE_ENROLMENT_STATUSES, VERIFIER_PURPOSES
from app.services.tokens import issue_token

SHARED_FIELDS = ["verified", "program", "academic_year"]
PARENTAL_NOTICE = "parental consent required"


def expire_stale(db: Session) -> int:
    """Move pending consents and requests past their expiry into ``expired``."""
    now = datetime.utcnow()
    changed = 0
    for consent in db.execute(
        select(Consent).where(
            Consent.status == "pending",
            Consent.expires_at.is_not(None),
            Consent.expires_at < now,
        )
    ).scalars():
        consent.status = "expired"
        changed += 1
    for request in db.execute(
        select(VerificationRequest).where(
            VerificationRequest.status == "pending",
            VerificationRequest.expires_at.is_not(None),
            VerificationRequest.expires_at < now,
        )
    ).scalars():
        request.status = "expired"
        changed += 1
    if changed:
        db.flush()
    return changed


def create_verification_request(
    db: Session,
    *,
    verifier_user,
    apaar: str,
    purpose: str,
    note: str | None = None,
) -> dict[str, Any]:
    """Create a pending request and the student's consent record.

    The raw APAAR is hashed immediately and never stored. If no student matches, the
    request is still created and still reads as ``pending`` — otherwise the endpoint
    would reveal which APAAR IDs exist.
    """
    if purpose not in VERIFIER_PURPOSES:
        raise ValueError(f"purpose must be one of {', '.join(VERIFIER_PURPOSES)}")

    apaar_hash = hash_apaar(apaar)
    masked = mask_apaar(apaar)
    student = (
        db.execute(select(Student).where(Student.apaar_hash == apaar_hash)).scalar_one_or_none()
        if apaar_hash
        else None
    )

    now = datetime.utcnow().replace(microsecond=0)
    expires_at = now + timedelta(hours=settings.consent_request_ttl_hours)
    parental = bool(student and student.is_minor)

    consent: Consent | None = None
    if student is not None:
        consent = Consent(
            student_id=student.id,
            verifier_user_id=verifier_user.id,
            verifier_name=verifier_user.verifier_name or verifier_user.display_name,
            verifier_type=verifier_user.verifier_type,
            purpose=purpose,
            status="pending",
            parental_consent_required=parental,
            requested_at=now,
            expires_at=expires_at,
            shared_fields=list(SHARED_FIELDS),
        )
        db.add(consent)
        db.flush()

    request = VerificationRequest(
        verifier_user_id=verifier_user.id,
        apaar_hash=apaar_hash,
        apaar_masked=masked,
        student_id=student.id if student else None,
        consent_id=consent.id if consent else None,
        purpose=purpose,
        note=note,
        status="pending",
        expires_at=expires_at,
    )
    db.add(request)
    db.flush()

    log_audit(
        db,
        actor=verifier_user.username,
        role="verifier",
        action="verification_requested",
        target=f"request:{request.id}",
        payload={"purpose": purpose, "apaar_masked": masked},
    )
    if student is not None:
        # The student can see who asked, even before they answer.
        log_access(
            db,
            actor=verifier_user.username,
            role="verifier",
            action="verification_requested",
            target=f"student:{student.id}",
            student_id=student.id,
            purpose=purpose,
            reason=f"Verification requested for {VERIFIER_PURPOSES[purpose]}.",
        )
    db.flush()

    message = (
        "The student has been asked for consent. No data is shared until they approve."
        if not parental
        else (
            "The student is a minor, so parental consent is required. No data is shared "
            "until consent is given."
        )
    )
    return {
        "request_id": request.id,
        "status": "pending",
        "apaar_masked": masked,
        "consent_id": consent.id if consent else None,
        "notification": "mock_otp_sent",
        "parental_consent_required": parental,
        "purpose": purpose,
        "requested_at": request.created_at,
        "expires_at": expires_at,
        "message": message,
    }


def minimal_result(db: Session, *, student_id: int) -> dict[str, Any]:
    """Exactly what a verifier may learn: verified, programme, year (CLAUDE.md rule 11)."""
    row = db.execute(
        select(Enrolment, Program)
        .join(Program, Program.id == Enrolment.program_id)
        .where(
            Enrolment.student_id == student_id,
            Enrolment.status.in_(ACTIVE_ENROLMENT_STATUSES),
        )
        .order_by(Enrolment.academic_year.desc())
        .limit(1)
    ).first()
    if row is None:
        return {"verified": False, "program": None, "academic_year": None}
    enrolment, program = row
    return {
        "verified": True,
        "program": f"{program.course} — {program.branch}",
        "academic_year": enrolment.academic_year,
    }


def approve_consent(
    db: Session, *, consent: Consent, actor: str, validity_minutes: int | None = None
) -> dict[str, Any]:
    """Approve, fill in the verifier's minimal result, and issue a signed token."""
    now = datetime.utcnow().replace(microsecond=0)
    consent.status = "approved"
    consent.responded_at = now
    token, token_expires = issue_token(
        student_id=consent.student_id, consent_id=consent.id, ttl_minutes=validity_minutes
    )
    consent.token_expires_at = token_expires

    result = minimal_result(db, student_id=consent.student_id)
    for request in db.execute(
        select(VerificationRequest).where(VerificationRequest.consent_id == consent.id)
    ).scalars():
        request.status = "approved"
        request.result = result
        request.responded_at = now

    log_audit(
        db,
        actor=actor,
        role="student",
        action="consent_approved",
        target=f"consent:{consent.id}",
        payload={"purpose": consent.purpose, "shared_fields": consent.shared_fields},
    )
    db.flush()
    return {
        "consent_id": consent.id,
        "status": "approved",
        "approved_at": now,
        "expires_at": token_expires,
        "shared_fields": consent.shared_fields,
        "token": token,
    }


def deny_consent(db: Session, *, consent: Consent, actor: str, reason: str | None) -> dict[str, Any]:
    now = datetime.utcnow().replace(microsecond=0)
    consent.status = "denied"
    consent.responded_at = now
    consent.deny_reason = reason
    for request in db.execute(
        select(VerificationRequest).where(VerificationRequest.consent_id == consent.id)
    ).scalars():
        request.status = "denied"
        request.result = None
        request.responded_at = now
    log_audit(
        db,
        actor=actor,
        role="student",
        action="consent_denied",
        target=f"consent:{consent.id}",
        payload={"purpose": consent.purpose},
    )
    db.flush()
    return {"consent_id": consent.id, "status": "denied", "denied_at": now}


def revoke_consent(db: Session, *, consent: Consent, actor: str) -> dict[str, Any]:
    """Revoking invalidates every token issued for this consent immediately."""
    now = datetime.utcnow().replace(microsecond=0)
    consent.status = "revoked"
    consent.revoked_at = now
    consent.token_expires_at = None
    tokens_invalidated = 0
    for request in db.execute(
        select(VerificationRequest).where(VerificationRequest.consent_id == consent.id)
    ).scalars():
        if request.status == "approved":
            tokens_invalidated += 1
        request.status = "revoked"
        request.result = None
    log_audit(
        db,
        actor=actor,
        role="student",
        action="consent_revoked",
        target=f"consent:{consent.id}",
        payload={"purpose": consent.purpose, "tokens_invalidated": tokens_invalidated},
    )
    db.flush()
    return {
        "consent_id": consent.id,
        "status": "revoked",
        "revoked_at": now,
        "tokens_invalidated": tokens_invalidated,
    }


def consent_rows(db: Session, *, student_id: int, status: str | None = None) -> list[dict[str, Any]]:
    expire_stale(db)
    statement = select(Consent).where(Consent.student_id == student_id)
    if status:
        statement = statement.where(Consent.status == status)
    rows = db.execute(statement.order_by(Consent.requested_at.desc())).scalars()
    return [
        {
            "consent_id": consent.id,
            "status": consent.status,
            "verifier_name": consent.verifier_name,
            "verifier_type": consent.verifier_type,
            "purpose": consent.purpose,
            "purpose_label": VERIFIER_PURPOSES.get(consent.purpose, consent.purpose),
            "will_share": [
                "verified yes/no",
                "programme",
                "academic year",
            ],
            "requested_at": consent.requested_at,
            "responded_at": consent.responded_at,
            "revoked_at": consent.revoked_at,
            "expires_at": consent.expires_at,
            "parental_consent_required": consent.parental_consent_required,
        }
        for consent in rows
    ]
