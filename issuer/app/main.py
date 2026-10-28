"""Mock Issuer & DigiLocker registry (port 8002).

A production-shaped stand-in for the services that would confirm a submitted document
is genuine: school boards, counselling authorities and immigration offices, reached the
way DigiLocker's issuer APIs are — by the reference number (or QR) printed on the
document. Same request/response shapes and API-key auth we would use for real; swapping
it in means replacing ``api/app/services/issuer_client.py`` and nothing else.

A document is ``verified`` when its SHA-256 equals the issued file's, or — for a re-scan,
whose bytes can never match — when every key fact read from it matches the record.
``mismatch`` means the reference exists but the document says something else (an edited
copy). ``not_found`` means no issuer knows the reference.

All data here is synthetic.
"""
from __future__ import annotations

import random
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field
from rapidfuzz import fuzz
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from issuer.app.config import issuer_settings
from issuer.app.db import IssuedRecord, get_issuer_db, init_issuer_db

app = FastAPI(
    title="Mock Issuer & DigiLocker Registry",
    version=issuer_settings.version,
    description="Synthetic document issuers for the SIH26263 prototype. All data is synthetic.",
)

# Facts compared when the hash does not match. Year and marks are what an edited
# marksheet changes; the roll number is what a borrowed one gives away.
COMPARED_FACTS = ("roll_no", "year", "marks_obtained", "marks_total")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _simulate_latency() -> None:
    low = issuer_settings.issuer_latency_min_ms
    high = max(low, issuer_settings.issuer_latency_max_ms)
    time.sleep(random.uniform(low, high) / 1000.0)


def require_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    if x_api_key != issuer_settings.issuer_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": "BAD_API_KEY", "message": "Invalid or missing X-API-Key."}},
        )


class VerifyRequest(BaseModel):
    reference_no: str = Field(min_length=1, max_length=40)
    doc_type: str | None = None
    sha256: str | None = Field(default=None, min_length=64, max_length=64)
    holder_name: str | None = None
    holder_dob: str | None = None  # ISO
    facts: dict[str, Any] = Field(default_factory=dict)


class VerifyResult(BaseModel):
    reference_no: str
    status: str  # verified | mismatch | not_found | revoked
    matched_by: str | None = None  # hash | facts
    issuer_name: str | None = None
    doc_type: str | None = None
    issued_on: str | None = None
    doc_type_match: bool | None = None
    holder_name_match: bool | None = None
    holder_dob_match: bool | None = None
    differing_facts: list[str] = Field(default_factory=list)
    checked_at: str
    source: str = "mock_issuer_registry_v1"


def _same(value: Any, other: Any) -> bool:
    return str(value).strip().lower() == str(other).strip().lower()


def _verify(db: Session, payload: VerifyRequest) -> VerifyResult:
    record = db.get(IssuedRecord, payload.reference_no.strip().upper())
    if record is None:
        return VerifyResult(reference_no=payload.reference_no, status="not_found", checked_at=_now())

    result = VerifyResult(
        reference_no=record.reference_no,
        status="verified",
        issuer_name=record.issuer_name,
        doc_type=record.doc_type,
        issued_on=record.issued_on,
        doc_type_match=None if payload.doc_type is None else payload.doc_type == record.doc_type,
        holder_name_match=None
        if payload.holder_name is None
        else fuzz.token_sort_ratio(payload.holder_name.lower(), record.holder_name.lower())
        >= issuer_settings.name_match_threshold,
        holder_dob_match=None
        if payload.holder_dob is None or record.holder_dob is None
        else payload.holder_dob == record.holder_dob,
        checked_at=_now(),
    )
    if record.status == "revoked":
        result.status = "revoked"
        return result
    if payload.sha256 and payload.sha256.lower() == record.sha256:
        result.matched_by = "hash"
        return result

    differing = [
        fact
        for fact in COMPARED_FACTS
        if fact in record.details and fact in payload.facts and not _same(payload.facts[fact], record.details[fact])
    ]
    compared = [fact for fact in COMPARED_FACTS if fact in record.details and fact in payload.facts]
    if differing or not compared:
        # Either it says something the issuer never issued, or there is nothing to
        # compare and the bytes differ: both mean this is not the issued document.
        result.status = "mismatch"
        result.differing_facts = differing
        return result
    result.matched_by = "facts"
    return result


@app.on_event("startup")
def on_startup() -> None:
    init_issuer_db()


@app.get("/health", tags=["meta"])
def health(db: Session = Depends(get_issuer_db)) -> dict:
    return {
        "status": "ok",
        "service": "mock-issuer-registry",
        "records": db.scalar(select(func.count()).select_from(IssuedRecord)) or 0,
        "time": _now(),
    }


@app.post("/documents/verify", response_model=VerifyResult, dependencies=[Depends(require_api_key)])
def verify(payload: VerifyRequest, db: Session = Depends(get_issuer_db)) -> VerifyResult:
    _simulate_latency()
    return _verify(db, payload)


@app.get("/documents/{reference_no}", dependencies=[Depends(require_api_key)])
def lookup(reference_no: str, db: Session = Depends(get_issuer_db)) -> dict:
    """What a QR scan resolves to: who issued it, what it is and when. No holder data."""
    record = db.get(IssuedRecord, reference_no.strip().upper())
    if record is None:
        raise HTTPException(status_code=404, detail={"error": {"code": "NOT_FOUND", "message": "Unknown reference."}})
    return {
        "reference_no": record.reference_no,
        "issuer_name": record.issuer_name,
        "doc_type": record.doc_type,
        "issued_on": record.issued_on,
        "status": record.status,
    }
