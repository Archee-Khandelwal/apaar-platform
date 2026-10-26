"""HMAC-signed verification tokens (Step 13 of docs/PLAN.md).

A token says "consent N for student M is valid until T", and nothing else. It is signed
with HMAC_KEY, so it cannot be forged or edited, and it carries no personal data — the
details are looked up server-side after the signature, expiry and consent status check.

States: ``genuine | expired | revoked | invalid``.
"""
from __future__ import annotations

import hmac
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.crypto import hmac_key  # single source of the keyed digest
from app.models.core import Consent, Enrolment, Institution, Program, Student

VERSION = "v1"
SIGNATURE_LENGTH = 32


@dataclass
class TokenPayload:
    student_id: int
    consent_id: int | None
    expires_at: int  # unix seconds

    def body(self) -> str:
        return f"{VERSION}.{self.student_id}.{self.consent_id or 0}.{self.expires_at}"


def _sign(body: str) -> str:
    import hashlib

    return hmac.new(hmac_key(), body.encode("utf-8"), hashlib.sha256).hexdigest()[
        :SIGNATURE_LENGTH
    ]


def issue_token(
    *, student_id: int, consent_id: int | None = None, ttl_minutes: int | None = None
) -> tuple[str, datetime]:
    """Returns (token, expires_at)."""
    ttl = ttl_minutes if ttl_minutes is not None else settings.verify_token_ttl_minutes
    expires = datetime.now(timezone.utc) + timedelta(minutes=ttl)
    payload = TokenPayload(
        student_id=student_id, consent_id=consent_id, expires_at=int(expires.timestamp())
    )
    body = payload.body()
    return f"{body}.{_sign(body)}", expires.replace(tzinfo=None)


def parse_token(token: str) -> tuple[TokenPayload | None, str]:
    """Verify the signature and expiry. Returns (payload, state)."""
    if not token:
        return None, "invalid"
    parts = token.strip().split(".")
    if len(parts) != 5 or parts[0] != VERSION:
        return None, "invalid"
    version, student_id, consent_id, expires_at, signature = parts
    body = f"{version}.{student_id}.{consent_id}.{expires_at}"
    if not hmac.compare_digest(_sign(body), signature):
        return None, "invalid"
    try:
        payload = TokenPayload(
            student_id=int(student_id),
            consent_id=int(consent_id) or None,
            expires_at=int(expires_at),
        )
    except ValueError:
        return None, "invalid"
    if payload.expires_at < int(time.time()):
        return payload, "expired"
    return payload, "genuine"


def verify_token(db: Session, token: str) -> dict[str, Any]:
    """Full check: signature, expiry, consent still live, then the minimal response."""
    checked_at = datetime.utcnow().replace(microsecond=0)
    payload, state = parse_token(token)
    if payload is None or state != "genuine":
        return {"state": state, "checked_at": checked_at}

    if payload.consent_id is not None:
        consent = db.get(Consent, payload.consent_id)
        if consent is None:
            return {"state": "invalid", "checked_at": checked_at}
        if consent.status == "revoked":
            return {"state": "revoked", "checked_at": checked_at}
        if consent.status != "approved":
            return {"state": "invalid", "checked_at": checked_at}

    student = db.get(Student, payload.student_id)
    if student is None:
        return {"state": "invalid", "checked_at": checked_at}

    row = db.execute(
        select(Enrolment, Program, Institution)
        .join(Program, Program.id == Enrolment.program_id)
        .join(Institution, Institution.id == Enrolment.institution_id)
        .where(
            Enrolment.student_id == payload.student_id,
            Enrolment.status.in_(("admitted", "completed")),
        )
        .order_by(Enrolment.academic_year.desc())
        .limit(1)
    ).first()

    if row is None:
        return {"state": "genuine", "verified": False, "checked_at": checked_at}

    enrolment, program, institution = row
    return {
        "state": "genuine",
        "verified": True,
        "program": f"{program.course} — {program.branch}",
        "academic_year": enrolment.academic_year,
        "institution_name": institution.name,
        "checked_at": checked_at,
    }
