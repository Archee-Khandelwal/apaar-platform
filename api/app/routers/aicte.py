"""AICTE-side routes.

Roles: ``aicte_viewer`` sees aggregates and masked rows with small-count suppression;
``aicte_officer`` additionally sees flag evidence, may reveal and may manage cases.
Step 7 adds the seat-matrix view; the rest of this router lands in Step 12.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.errors import raise_not_found
from app.core.security import CurrentUser, require_role
from app.models.core import Institution
from app.schemas.institution import SeatMatrixOut
from app.services.intake import institution_seat_matrix

router = APIRouter(prefix="/aicte", tags=["aicte"])


@router.get("/institutions/{institution_id}/seat-matrix", response_model=SeatMatrixOut)
def institution_seat_matrix_view(
    institution_id: int,
    academic_year: Annotated[str, Query(min_length=7, max_length=7)],
    user: CurrentUser = Depends(require_role("aicte_viewer", "aicte_officer")),
    db: Session = Depends(get_db),
) -> SeatMatrixOut:
    if db.get(Institution, institution_id) is None:
        raise_not_found("No such institution.")
    return SeatMatrixOut(
        **institution_seat_matrix(
            db, institution_id=institution_id, academic_year=academic_year
        )
    )
