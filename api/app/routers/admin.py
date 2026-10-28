"""Admin routes: demo tooling only.

``admin`` is a demo operator, not a superuser: there is deliberately no route here that
returns student data (Step-0 decision 3).
"""
from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import log_audit
from app.core.config import settings
from app.core.db import get_db
from app.core.security import CurrentUser, require_role
from app.models.core import (
    Consent,
    Enrolment,
    Flag,
    Institution,
    Program,
    Student,
    Upload,
)
from app.services.admin_tools import audit_status, tamper_test
from app.services.detectors import run_all_detectors

router = APIRouter(prefix="/admin", tags=["admin"])

class ReseedRequest(BaseModel):
    seed: int = 42
    institutions: int = Field(default=40, ge=2, le=200)
    students: int = Field(default=15000, ge=100, le=60000)


@router.get("/status")
def demo_status(
    user: CurrentUser = Depends(require_role("admin")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Row counts and audit health, for the demo operator's control panel."""
    counts = {
        "institutions": db.scalar(select(func.count()).select_from(Institution)) or 0,
        "programs": db.scalar(select(func.count()).select_from(Program)) or 0,
        "students": db.scalar(select(func.count()).select_from(Student)) or 0,
        "enrolments": db.scalar(select(func.count()).select_from(Enrolment)) or 0,
        "uploads": db.scalar(select(func.count()).select_from(Upload)) or 0,
        "flags": db.scalar(select(func.count()).select_from(Flag)) or 0,
        "consents": db.scalar(select(func.count()).select_from(Consent)) or 0,
    }
    flags_by_type = {
        row[0]: int(row[1])
        for row in db.execute(select(Flag.type, func.count()).group_by(Flag.type)).all()
    }
    return {
        "counts": counts,
        "flags_by_type": dict(sorted(flags_by_type.items())),
        "audit": audit_status(db),
        "current_academic_year": settings.current_academic_year,
        "demo_mode": settings.demo_mode,
    }


@router.post("/reseed")
def reseed(
    payload: ReseedRequest | None = None,
    user: CurrentUser = Depends(require_role("admin")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Wipe and regenerate the whole demo dataset, then run every detector."""
    import time

    from datagen.generator import generate

    options = payload or ReseedRequest()
    started = time.perf_counter()
    ground_truth = generate(
        db,
        seed=options.seed,
        institutions=options.institutions,
        students=options.students,
    )
    detectors = run_all_detectors(db)
    log_audit(
        db,
        actor=user.username,
        role="admin",
        action="reseed",
        target="database",
        payload={"seed": options.seed, "counts": ground_truth["counts"]},
    )
    db.commit()

    return {
        "status": "ok",
        "seed": options.seed,
        "duration_ms": int((time.perf_counter() - started) * 1000),
        "counts": ground_truth["counts"],
        "detectors": detectors,
        "ground_truth_path": "datagen/ground_truth.json",
    }


@router.get("/audit/verify")
def verify_audit(
    user: CurrentUser = Depends(require_role("admin")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Recompute every hash in the audit chain."""
    from datetime import datetime

    result = audit_status(db)
    result["checked_at"] = datetime.utcnow().replace(microsecond=0)
    return result


@router.post("/audit/tamper-test")
def run_tamper_test(
    user: CurrentUser = Depends(require_role("admin")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Edit one row in a COPY of the audit log and show the chain catching it."""
    return tamper_test(db, actor=user.username)


