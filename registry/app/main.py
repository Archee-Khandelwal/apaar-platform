"""Mock APAAR registry (port 8001).

A production-shaped stand-in for the real APAAR / ABC registry API: the same request and
response shapes, the same statuses and the same API-key auth we would use against the
real service. Swapping in the real registry means replacing
``api/app/services/registry_client.py`` and nothing else.

All data here is synthetic.
"""
from __future__ import annotations

import random
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field
from rapidfuzz import fuzz
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from registry.app.config import registry_settings
from registry.app.db import IssuedApaar, get_registry_db, init_registry_db

MAX_BATCH = 500

app = FastAPI(
    title="Mock APAAR Registry",
    version=registry_settings.version,
    description="Synthetic APAAR registry for the SIH26263 prototype. All data is synthetic.",
)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _simulate_latency() -> None:
    """20-50 ms, so the demo feels like a real network call."""
    low = registry_settings.registry_latency_min_ms
    high = max(low, registry_settings.registry_latency_max_ms)
    time.sleep(random.uniform(low, high) / 1000.0)


def require_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    if x_api_key != registry_settings.registry_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": "BAD_API_KEY", "message": "Invalid or missing X-API-Key."}},
        )


def mask(apaar: str | None) -> str:
    digits = "".join(ch for ch in (apaar or "") if ch.isdigit())
    return f"XXXX-XXXX-{digits[-4:]}" if len(digits) >= 4 else "XXXX-XXXX-XXXX"


class VerifyRequest(BaseModel):
    apaar: str = Field(min_length=1, max_length=20)
    name: str | None = None
    dob: str | None = None
    consent_token: str | None = None


class VerifyResult(BaseModel):
    apaar_masked: str
    status: str  # match | mismatch | not_found | consent_required
    name_similarity: int | None = None
    dob_match: bool | None = None
    checked_at: str
    source: str = "mock_apaar_registry_v1"
    ref: str | None = None


class BatchRecord(VerifyRequest):
    ref: str | None = None


class BatchRequest(BaseModel):
    records: list[BatchRecord] = Field(max_length=MAX_BATCH)


class BatchResponse(BaseModel):
    checked_at: str
    count: int
    results: list[VerifyResult]


class BulkInsertRecord(BaseModel):
    apaar: str
    name: str
    dob: str


class BulkInsertRequest(BaseModel):
    records: list[BulkInsertRecord]


def _lookup(db: Session, record: VerifyRequest) -> VerifyResult:
    digits = "".join(ch for ch in record.apaar if ch.isdigit())
    row = db.execute(select(IssuedApaar).where(IssuedApaar.apaar == digits)).scalar_one_or_none()
    checked_at = _now()

    if row is None:
        return VerifyResult(apaar_masked=mask(digits), status="not_found", checked_at=checked_at)

    # A real registry would require the holder's consent token for a full comparison.
    if record.name is None and record.dob is None:
        if record.consent_token is None:
            return VerifyResult(
                apaar_masked=mask(digits), status="consent_required", checked_at=checked_at
            )
        return VerifyResult(apaar_masked=mask(digits), status="match", checked_at=checked_at)

    similarity = (
        int(round(fuzz.token_sort_ratio((record.name or "").strip().lower(), row.name.strip().lower())))
        if record.name
        else None
    )
    dob_match = (record.dob or "")[:10] == row.dob if record.dob else None

    name_ok = similarity is None or similarity >= registry_settings.name_match_threshold
    dob_ok = dob_match is None or dob_match
    return VerifyResult(
        apaar_masked=mask(digits),
        status="match" if (name_ok and dob_ok) else "mismatch",
        name_similarity=similarity,
        dob_match=dob_match,
        checked_at=checked_at,
    )


@app.on_event("startup")
def on_startup() -> None:
    init_registry_db()


@app.get("/health", tags=["meta"])
def health(db: Session = Depends(get_registry_db)) -> dict:
    try:
        issued = db.execute(select(func.count()).select_from(IssuedApaar)).scalar_one()
    except Exception:  # pragma: no cover - table may not exist yet
        issued = 0
    return {
        "status": "ok",
        "service": "registry",
        "version": registry_settings.version,
        "issued_count": issued,
    }


verify_router = APIRouter(dependencies=[Depends(require_api_key)], tags=["verify"])


@verify_router.post("/verify", response_model=VerifyResult)
def verify(payload: VerifyRequest, db: Session = Depends(get_registry_db)) -> VerifyResult:
    _simulate_latency()
    return _lookup(db, payload)


@verify_router.post("/verify/batch", response_model=BatchResponse)
def verify_batch(payload: BatchRequest, db: Session = Depends(get_registry_db)) -> BatchResponse:
    if len(payload.records) > MAX_BATCH:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={
                "error": {
                    "code": "BATCH_TOO_LARGE",
                    "message": f"At most {MAX_BATCH} records per batch.",
                }
            },
        )
    _simulate_latency()
    results: list[VerifyResult] = []
    for record in payload.records:
        result = _lookup(db, record)
        result.ref = record.ref
        results.append(result)
    return BatchResponse(checked_at=_now(), count=len(results), results=results)


@verify_router.post("/registry/apaar/bulk")
def bulk_insert(payload: BulkInsertRequest, db: Session = Depends(get_registry_db)) -> dict:
    """Seeding hook used by /datagen. Not part of the real registry's public surface."""
    inserted = 0
    skipped = 0
    for record in payload.records:
        digits = "".join(ch for ch in record.apaar if ch.isdigit())
        exists = db.get(IssuedApaar, digits)
        if exists is not None:
            skipped += 1
            continue
        db.add(IssuedApaar(apaar=digits, name=record.name, dob=record.dob[:10]))
        inserted += 1
    db.commit()
    issued = db.execute(select(func.count()).select_from(IssuedApaar)).scalar_one()
    return {"inserted": inserted, "skipped_existing": skipped, "issued_count": issued}


app.include_router(verify_router)
