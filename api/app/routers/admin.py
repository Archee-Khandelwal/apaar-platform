"""Admin routes: demo tooling only.

``admin`` is a demo operator, not a superuser: there is deliberately no route here that
returns student data (Step-0 decision 3).
"""
from __future__ import annotations

import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import log_audit
from app.core.config import settings
from app.core.db import get_db
from app.core.errors import api_error
from app.core.security import CurrentUser, require_role
from app.models.core import (
    Cluster,
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

SCENARIOS: dict[str, dict[str, Any]] = {
    "A_excess_intake": {
        "label": "Excess admissions beyond approved intake",
        "flag_types": ["EXCESS_INTAKE"],
    },
    "B_ghost_cluster": {"label": "Ghost-student cluster", "flag_types": ["GHOST_CLUSTER"]},
    "C_cross_institution_duplicate": {
        "label": "Same APAAR at two full-time institutions",
        "flag_types": ["CROSS_INSTITUTION_DUPLICATE"],
    },
    "D_dual_degree": {
        "label": "Legitimate dual degree (must NOT be fraud)",
        "flag_types": ["POSSIBLE_DUAL_DEGREE"],
    },
    "E_apaar_problems": {
        "label": "Invalid / unknown / mismatched APAAR",
        "flag_types": ["INVALID_APAAR", "APAAR_NOT_FOUND", "APAAR_MISMATCH"],
    },
    "F_late_admission": {"label": "Admissions after the cutoff", "flag_types": ["LATE_ADMISSION"]},
    "G_sequential_apaar": {
        "label": "Near-consecutive APAAR ID run",
        "flag_types": ["SEQUENTIAL_APAAR"],
    },
    "H_last_minute_bulk": {
        "label": "Records filed in a last-minute burst",
        "flag_types": ["LAST_MINUTE_BULK"],
    },
    "I_phantom_progression": {
        "label": "Phantom year-to-year progression",
        "flag_types": ["PHANTOM_PROGRESSION"],
    },
    "J_identity_duplicate": {
        "label": "One person with two APAAR IDs",
        "flag_types": ["IDENTITY_DUPLICATE"],
    },
    "K_supernumerary_misuse": {
        "label": "Supernumerary share far above peers",
        "flag_types": ["STATISTICAL_ANOMALY"],
    },
}


class ReseedRequest(BaseModel):
    seed: int = 42
    institutions: int = Field(default=40, ge=2, le=200)
    students: int = Field(default=15000, ge=100, le=60000)


@router.get("/scenarios")
def list_scenarios(user: CurrentUser = Depends(require_role("admin"))) -> dict[str, Any]:
    return {
        "scenarios": [
            {"name": name, "label": config["label"], "flag_types": config["flag_types"]}
            for name, config in SCENARIOS.items()
        ]
    }


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
        "clusters": db.scalar(select(func.count()).select_from(Cluster)) or 0,
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


@router.post("/load-scenario/{name}")
def load_scenario(
    name: str,
    user: CurrentUser = Depends(require_role("admin")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Re-inject one scenario into the live database and re-run the detectors."""
    if name not in SCENARIOS:
        raise api_error(
            status.HTTP_404_NOT_FOUND,
            "NOT_FOUND",
            f"Unknown scenario {name!r}. Call GET /admin/scenarios for the list.",
        )

    from datagen import scenarios as scenario_module
    from datagen.generator import SyntheticDataGenerator

    before = {
        flag_type: db.scalar(
            select(func.count()).select_from(Flag).where(Flag.type == flag_type)
        )
        or 0
        for flag_type in SCENARIOS[name]["flag_types"]
    }

    # Rebuild the generator's in-memory view of the existing database, then run just
    # this scenario against it and persist only what it added.
    generator = SyntheticDataGenerator(db, seed=int(time.time()) % 100000)
    generator.adopt_existing()
    scenario_module.SCENARIOS[name](generator)
    added = generator.persist_additions()
    detectors = run_all_detectors(db)

    after = {
        flag_type: db.scalar(
            select(func.count()).select_from(Flag).where(Flag.type == flag_type)
        )
        or 0
        for flag_type in SCENARIOS[name]["flag_types"]
    }
    log_audit(
        db,
        actor=user.username,
        role="admin",
        action="load_scenario",
        target=f"scenario:{name}",
        payload={"added": added, "flags_before": before, "flags_after": after},
    )
    db.commit()

    return {
        "scenario": name,
        "label": SCENARIOS[name]["label"],
        "status": "injected",
        "added": added,
        "flags_before": before,
        "flags_after": after,
        "detectors": detectors,
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


@router.post("/run-detectors")
def rerun_detectors(
    academic_year: Annotated[str | None, Query()] = None,
    user: CurrentUser = Depends(require_role("admin")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    summary = run_all_detectors(db, academic_year=academic_year)
    log_audit(
        db, actor=user.username, role="admin", action="run_detectors", target="database", payload=summary
    )
    db.commit()
    return {"status": "ok", **summary}
