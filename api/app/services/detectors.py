"""Single entry point for every detector (Step 10 item 5 of docs/PLAN.md).

``run_all_detectors`` is called after seeding, after an upload is confirmed, and by the
admin reseed endpoint. It is **idempotent**: flags are keyed by a stable dedupe_key, so
re-running updates findings in place instead of creating duplicates, and findings that
have disappeared are resolved automatically.

Detectors are added here as each step lands:
  Step 7  intake compliance (EXCESS_INTAKE)
  Step 8  duplicates (CROSS_INSTITUTION_DUPLICATE, POSSIBLE_DUAL_DEGREE,
          IDENTITY_DUPLICATE)
  Step 9  ghost-student graph (GHOST_CLUSTER)
"""
from __future__ import annotations

import logging
import time
from typing import Any

from sqlalchemy.orm import Session

from app.services.duplicates import run_duplicate_detection
from app.services.graph import detect_ghost_clusters
from app.services.intake import run_intake_compliance

logger = logging.getLogger("apaar.detectors")


def run_all_detectors(
    db: Session,
    *,
    institution_id: int | None = None,
    academic_year: str | None = None,
    commit: bool = True,
) -> dict[str, Any]:
    """Run every detector. Returns a summary of what each one created or updated."""
    started = time.perf_counter()
    summary: dict[str, Any] = {}

    summary.update(
        run_intake_compliance(db, institution_id=institution_id, academic_year=academic_year)
    )

    summary.update(run_duplicate_detection(db, academic_year=academic_year))
    summary.update(detect_ghost_clusters(db, academic_year=academic_year))

    if commit:
        db.commit()
    summary["duration_ms"] = int((time.perf_counter() - started) * 1000)
    logger.info("Detectors finished: %s", summary)
    return summary
