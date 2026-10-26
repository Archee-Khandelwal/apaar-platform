"""AICTE-side routes.

Roles: ``aicte_viewer`` sees aggregates and masked rows with small-count suppression;
``aicte_officer`` additionally sees flag evidence, may reveal and may manage cases.
Step 7 adds the seat-matrix view; the rest of this router lands in Step 12.
"""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.access_log import log_access
from app.core.db import get_db
from app.core.errors import raise_not_found
from app.core.security import CurrentUser, require_role, suppress_small_counts
from app.models.core import Cluster, Flag, Institution
from app.schemas.common import PageParams, page_params, paginate
from app.schemas.institution import (
    ClusterDetailOut,
    ClusterPage,
    ClusterSummaryOut,
    SeatMatrixOut,
)
from app.services.graph import ATTRIBUTE_LABELS
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


# --------------------------------------------------------------------------- graph


def _institution_names(db: Session, ids: list[int]) -> list[dict[str, Any]]:
    if not ids:
        return []
    rows = db.execute(select(Institution).where(Institution.id.in_(ids))).scalars()
    return [{"id": row.id, "name": row.name} for row in rows]


@router.get("/graph/clusters", response_model=ClusterPage)
def list_clusters(
    min_score: Annotated[float | None, Query(ge=0, le=100)] = None,
    severity: Annotated[str | None, Query()] = None,
    institution_id: Annotated[int | None, Query()] = None,
    kind: Annotated[str, Query(pattern="^(suspicious|normal)$")] = "suspicious",
    params: PageParams = Depends(page_params),
    user: CurrentUser = Depends(require_role("aicte_viewer", "aicte_officer")),
    db: Session = Depends(get_db),
) -> ClusterPage:
    """Ghost-student clusters, highest score first. Summaries are masked."""
    conditions = [Cluster.kind == kind]
    if min_score is not None:
        conditions.append(Cluster.score >= min_score)
    if severity:
        conditions.append(Cluster.severity == severity)

    rows = list(
        db.execute(select(Cluster).where(*conditions).order_by(Cluster.score.desc())).scalars()
    )
    if institution_id is not None:
        rows = [row for row in rows if institution_id in (row.institution_ids or [])]

    total = len(rows)
    page_rows = rows[params.offset : params.offset + params.page_size]

    flags = {
        flag.cluster_id: flag.id
        for flag in db.execute(select(Flag).where(Flag.type == "GHOST_CLUSTER")).scalars()
        if flag.cluster_id is not None
    }

    items = [
        {
            "cluster_id": row.id,
            "score": row.score,
            "severity": row.severity,
            "kind": row.kind,
            "student_count": row.student_count,
            "shared_attributes": (row.metrics or {}).get("shared_attributes", {}),
            "institutions": _institution_names(db, row.institution_ids or []),
            "academic_year": row.academic_year,
            "summary": row.summary,
            "flag_id": flags.get(row.id),
            "created_at": row.created_at,
        }
        for row in page_rows
    ]
    payload = paginate(items, total, PageParams(page=params.page, page_size=params.page_size, sort="-score"))
    return ClusterPage(**suppress_small_counts(payload, user.role, keep_keys=("student_count",)))


@router.get("/graph/clusters/{cluster_id}", response_model=ClusterDetailOut)
def cluster_detail(
    cluster_id: int,
    user: CurrentUser = Depends(require_role("aicte_viewer", "aicte_officer")),
    db: Session = Depends(get_db),
) -> ClusterDetailOut:
    """Cytoscape-ready graph. Labels are masked and contacts are numbered, never shown."""
    cluster = db.get(Cluster, cluster_id)
    if cluster is None:
        raise_not_found("No such cluster.")

    # CLAUDE.md section 5 rule 7: every detail view is logged.
    entry = log_access(
        db,
        actor=user.username,
        role=user.role,
        action="view_cluster",
        target=f"cluster:{cluster_id}",
    )
    db.commit()

    graph = cluster.graph or {"nodes": [], "edges": []}
    return ClusterDetailOut(
        cluster_id=cluster.id,
        score=cluster.score,
        severity=cluster.severity,
        kind=cluster.kind,
        summary=cluster.summary,
        metrics=cluster.metrics or {},
        legend={
            "student": "Student (colour = institution)",
            **{key: f"Shared {label.lower()}" for key, label in ATTRIBUTE_LABELS.items()},
        },
        nodes=graph.get("nodes", []),
        edges=graph.get("edges", []),
        access_log_id=entry.id,
    )


@router.get("/graph/clusters/{cluster_id}/normal-comparison", response_model=ClusterDetailOut)
def normal_comparison(
    cluster_id: int,
    user: CurrentUser = Depends(require_role("aicte_viewer", "aicte_officer")),
    db: Session = Depends(get_db),
) -> ClusterDetailOut:
    """A healthy family cluster, for the side-by-side comparison (Step 17.3)."""
    cluster = db.get(Cluster, cluster_id)
    if cluster is None:
        raise_not_found("No such cluster.")

    normal = db.execute(
        select(Cluster)
        .where(Cluster.kind == "normal")
        .order_by(Cluster.student_count.desc())
        .limit(1)
    ).scalar_one_or_none()
    if normal is None:
        raise_not_found("No healthy cluster available for comparison.")

    graph = normal.graph or {"nodes": [], "edges": []}
    return ClusterDetailOut(
        cluster_id=normal.id,
        score=normal.score,
        severity=normal.severity,
        kind=normal.kind,
        summary=normal.summary,
        metrics=normal.metrics or {},
        legend={"student": "Student (colour = institution)", **{
            key: f"Shared {label.lower()}" for key, label in ATTRIBUTE_LABELS.items()
        }},
        nodes=graph.get("nodes", []),
        edges=graph.get("edges", []),
    )
