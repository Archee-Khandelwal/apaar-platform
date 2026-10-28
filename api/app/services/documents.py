"""Signed, verifiable documents: degree certificates and student records.

A document's QR carries a compact JWS (a JWT) whose claims are exactly what the paper
prints — masked APAAR, student ID, programme, year, issuer, serial. The signature
proves the platform issued those claims; the ``issued_documents`` row lets the public
check also report a revocation.

States: ``genuine | revoked | invalid`` (the same words as the ID-card token check).
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timezone
from typing import Any

import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import log_audit
from app.core.config import settings
from app.core.crypto import hmac_key
from app.models.core import IssuedDocument, utcnow

ALGORITHM = "HS256"
KEY_ID = "apaar-doc-hs256-v1"
DOCUMENT_KINDS = ("degree_certificate", "student_record")
SERIAL_PREFIX = {"degree_certificate": "DC", "student_record": "SR"}


class DocumentError(Exception):
    """A document cannot be issued or changed as asked."""


def _signing_key() -> bytes:
    # A purpose-bound key derived from HMAC_KEY, so a document signature can never be
    # replayed as any other HMAC the platform computes.
    return hmac.new(hmac_key(), b"apaar-document-signing-v1", hashlib.sha256).digest()


def sign_claims(claims: dict[str, Any]) -> str:
    return jwt.encode(claims, _signing_key(), algorithm=ALGORITHM, headers={"kid": KEY_ID})


def decode_token(token: str) -> dict[str, Any] | None:
    """Signature check only. Returns the claims, or None when the token is not ours."""
    try:
        return jwt.decode(
            token.strip(),
            _signing_key(),
            algorithms=[ALGORITHM],
            options={"require": ["typ", "sn", "iat"]},
        )
    except jwt.InvalidTokenError:
        return None


def verify_url(token: str) -> str:
    return f"{settings.web_url}/verify?doc={token}"


def new_serial(kind: str, academic_year: str | None = None) -> str:
    year = (academic_year or settings.current_academic_year)[:4]
    return f"{SERIAL_PREFIX[kind]}-{year}-{secrets.token_hex(4).upper()}"


def issue_document(
    db: Session,
    *,
    kind: str,
    claims: dict[str, Any],
    student_id: int,
    actor: str,
    role: str,
    institution_id: int | None = None,
    enrolment_id: int | None = None,
    academic_year: str | None = None,
) -> tuple[IssuedDocument, str]:
    """Persist a document and return it with its signed token."""
    if kind not in DOCUMENT_KINDS:
        raise DocumentError(f"Unknown document kind {kind!r}.")
    issued_at = datetime.now(timezone.utc).replace(microsecond=0)
    serial = new_serial(kind, academic_year)
    full_claims = {"typ": kind, "sn": serial, "iat": int(issued_at.timestamp()), **claims}

    document = IssuedDocument(
        serial=serial,
        kind=kind,
        student_id=student_id,
        institution_id=institution_id,
        enrolment_id=enrolment_id,
        claims=full_claims,
        status="valid",
        issued_by=actor,
    )
    db.add(document)
    db.flush()
    log_audit(
        db,
        actor=actor,
        role=role,
        action=f"{kind}_issued",
        target=f"document:{serial}",
        payload={"student_id": student_id, "enrolment_id": enrolment_id},
    )
    return document, sign_claims(full_claims)


def token_for(document: IssuedDocument) -> str:
    """Re-sign the stored claims (deterministic for HS256, so the QR never changes)."""
    return sign_claims(dict(document.claims))


def revoke_document(db: Session, *, document: IssuedDocument, actor: str, role: str, reason: str) -> None:
    if document.status == "revoked":
        raise DocumentError("This document is already revoked.")
    if len(reason.strip()) < 10:
        raise DocumentError("A reason of at least 10 characters is required to revoke a document.")
    document.status = "revoked"
    document.revoked_at = utcnow()
    document.revoke_reason = reason.strip()
    log_audit(
        db,
        actor=actor,
        role=role,
        action=f"{document.kind}_revoked",
        target=f"document:{document.serial}",
        payload={"reason": reason.strip()},
    )
    db.flush()


def check_document(db: Session, token: str) -> dict[str, Any]:
    """Public check: signature, then the live status of the serial it names.

    Anything but ``genuine`` returns only the state, so a failed check says nothing
    about whether the serial exists.
    """
    checked_at = datetime.utcnow().replace(microsecond=0)
    claims = decode_token(token or "")
    if claims is None or claims.get("typ") not in DOCUMENT_KINDS:
        return {"state": "invalid", "checked_at": checked_at}

    document = db.execute(
        select(IssuedDocument).where(IssuedDocument.serial == claims["sn"])
    ).scalar_one_or_none()
    # A validly signed token whose claims differ from what we stored was not issued
    # by this platform in that form.
    if document is None or dict(document.claims) != claims:
        return {"state": "invalid", "checked_at": checked_at}

    printed = {key: value for key, value in claims.items() if key not in ("typ", "sn", "iat")}
    result: dict[str, Any] = {
        "state": "revoked" if document.status == "revoked" else "genuine",
        "kind": document.kind,
        "serial": document.serial,
        "issued_at": datetime.fromtimestamp(claims["iat"], tz=timezone.utc).replace(tzinfo=None),
        "claims": printed,
        "signature_alg": ALGORITHM,
        "key_id": KEY_ID,
        "checked_at": checked_at,
    }
    if document.status == "revoked":
        result["revoked_at"] = document.revoked_at
    return result
