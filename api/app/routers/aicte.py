"""AICTE-side routes.

Roles: ``aicte_viewer`` sees aggregates and masked rows with small-count suppression;
``aicte_officer`` additionally sees flag evidence, may reveal and may manage cases.
Step 7 adds the seat-matrix view; the rest of this router lands in Step 12.
"""
from __future__ import annotations

from typing import Annotated, Any

import csv
import io
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.access_log import log_access
from app.core.audit import log_audit
from app.core.config import settings
from app.core.db import get_db
from app.core.errors import api_error, raise_not_found
from app.core.security import CurrentUser, require_role, suppress_small_counts
from app.models.core import Cluster, Flag, Institution, InstitutionRisk, ReminderLog, Student
from app.models.enums import FLAG_STATUSES
from app.schemas.common import PageParams, page_params, paginate
from app.schemas.aicte import (
    FlagDetailOut,
    FlagOut,
    FlagPage,
    FlagUpdateRequest,
    FlagUpdateResponse,
    InstitutionPage,
    InstitutionProfileOut,
    NonReportingPage,
    OverviewOut,
    ReminderResponse,
    RevealRequest,
    RevealResponse,
    TrendsOut,
)
from app.schemas.institution import (
    ClusterDetailOut,
    ClusterPage,
    ClusterSummaryOut,
    RiskPage,
    RiskRowOut,
    SeatMatrixOut,
    ShortlistOut,
)
from app.services.aggregates import (
    institution_profile,
    institution_rows,
    national_overview,
    non_reporting,
    trends,
    trends_csv,
)
from app.services.cases import (
    RevealError,
    build_flag_query,
    flag_facets,
    flag_history,
    flag_to_dict,
    order_flags,
    reveal_student,
    update_flag,
)
from app.services.graph import ATTRIBUTE_LABELS
from app.services.intake import institution_seat_matrix
from app.services.risk import inspection_shortlist
from app.services.rules import known_academic_years

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


# --------------------------------------------------------------------------- risk


@router.get("/risk", response_model=RiskPage)
def risk_leaderboard(
    state: Annotated[str | None, Query()] = None,
    band: Annotated[str | None, Query(pattern="^(low|medium|high|critical)$")] = None,
    params: PageParams = Depends(page_params),
    user: CurrentUser = Depends(require_role("aicte_viewer", "aicte_officer")),
    db: Session = Depends(get_db),
) -> RiskPage:
    """Institutions ranked by risk, each with the top three reasons in plain English."""
    statement = (
        select(InstitutionRisk, Institution)
        .join(Institution, Institution.id == InstitutionRisk.institution_id)
        .order_by(InstitutionRisk.score.desc(), Institution.name.asc())
    )
    if state:
        statement = statement.where(Institution.state == state)
    if band:
        statement = statement.where(InstitutionRisk.band == band)

    rows = list(db.execute(statement).all())
    total = len(rows)
    page_rows = rows[params.offset : params.offset + params.page_size]

    items = [
        {
            "institution_id": institution.id,
            "name": institution.name,
            "state": institution.state,
            "risk_score": risk.score,
            "band": risk.band,
            "top_reasons": risk.reasons or [],
            "components": {"flags": risk.flag_component, "anomaly": risk.anomaly_component},
            "open_flags": (risk.features or {}).get("open_flags", 0),
        }
        for risk, institution in page_rows
    ]
    payload = paginate(
        items, total, PageParams(page=params.page, page_size=params.page_size, sort="-risk_score")
    )
    return RiskPage(**suppress_small_counts(payload, user.role))


@router.get("/inspection-shortlist", response_model=ShortlistOut)
def shortlist(
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
    state: Annotated[str | None, Query()] = None,
    user: CurrentUser = Depends(require_role("aicte_viewer", "aicte_officer")),
    db: Session = Depends(get_db),
) -> ShortlistOut:
    """Recommended for physical inspection, with the reason and what to check on site."""
    items = inspection_shortlist(db, limit=limit if state is None else 50)
    if state:
        items = [item for item in items if item["state"] == state][:limit]
        for rank, item in enumerate(items, start=1):
            item["rank"] = rank
    return ShortlistOut(
        generated_at=datetime.now(),
        academic_year=settings.current_academic_year,
        items=items,
        csv_url="/aicte/inspection-shortlist.csv",
    )


@router.get("/inspection-shortlist.csv", response_class=PlainTextResponse)
def shortlist_csv(
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
    user: CurrentUser = Depends(require_role("aicte_viewer", "aicte_officer")),
    db: Session = Depends(get_db),
) -> PlainTextResponse:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["rank", "institution_id", "name", "state", "risk_score", "band", "reasons"])
    for item in inspection_shortlist(db, limit=limit):
        writer.writerow(
            [
                item["rank"],
                item["institution_id"],
                item["name"],
                item["state"],
                item["risk_score"],
                item["band"],
                " | ".join(item["reasons"]),
            ]
        )
    return PlainTextResponse(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="inspection_shortlist.csv"'},
    )


# --------------------------------------------------------------------------- overview


@router.get("/overview", response_model=OverviewOut)
def overview(
    academic_year: Annotated[str | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
    user: CurrentUser = Depends(require_role("aicte_viewer", "aicte_officer")),
    db: Session = Depends(get_db),
) -> OverviewOut:
    """National KPIs and a state-wise breakdown, counted from student-level records."""
    payload = national_overview(
        db, academic_year=academic_year or settings.current_academic_year, state=state
    )
    payload["suppression_applied"] = user.role == "aicte_viewer"
    return OverviewOut(**suppress_small_counts(payload, user.role, keep_keys=("avg_risk",)))


# --------------------------------------------------------------------------- institutions


@router.get("/institutions", response_model=InstitutionPage)
def list_institutions(
    q: Annotated[str | None, Query(max_length=120)] = None,
    state: Annotated[str | None, Query()] = None,
    region: Annotated[str | None, Query()] = None,
    type: Annotated[str | None, Query()] = None,
    risk_min: Annotated[float | None, Query(ge=0, le=100)] = None,
    risk_max: Annotated[float | None, Query(ge=0, le=100)] = None,
    reporting: Annotated[str | None, Query(pattern="^(yes|no)$")] = None,
    has_flag_type: Annotated[str | None, Query()] = None,
    academic_year: Annotated[str | None, Query()] = None,
    params: PageParams = Depends(page_params),
    user: CurrentUser = Depends(require_role("aicte_viewer", "aicte_officer")),
    db: Session = Depends(get_db),
) -> InstitutionPage:
    rows = institution_rows(
        db,
        academic_year=academic_year or settings.current_academic_year,
        search=q,
        state=state,
        region=region,
        type_=type,
        risk_min=risk_min,
        risk_max=risk_max,
        reporting=reporting,
        has_flag_type=has_flag_type,
    )

    sort = params.sort or "-risk_score"
    field = sort.lstrip("-")
    reverse = sort.startswith("-")
    sort_keys = {
        "risk_score": lambda row: row["risk_score"],
        "name": lambda row: row["name"],
        "students_reported": lambda row: row["students_reported"],
        "excess_seats": lambda row: row["excess_seats"],
    }
    rows.sort(key=sort_keys.get(field, sort_keys["risk_score"]), reverse=reverse)

    total = len(rows)
    page_rows = rows[params.offset : params.offset + params.page_size]
    payload = paginate(
        page_rows, total, PageParams(page=params.page, page_size=params.page_size, sort=sort)
    )
    return InstitutionPage(
        **suppress_small_counts(payload, user.role, keep_keys=("risk_score", "days_overdue"))
    )


@router.get("/institutions/{institution_id}", response_model=InstitutionProfileOut)
def institution_detail(
    institution_id: int,
    academic_year: Annotated[str | None, Query()] = None,
    user: CurrentUser = Depends(require_role("aicte_viewer", "aicte_officer")),
    db: Session = Depends(get_db),
) -> InstitutionProfileOut:
    try:
        profile = institution_profile(
            db,
            institution_id=institution_id,
            academic_year=academic_year or settings.current_academic_year,
        )
    except LookupError:
        raise_not_found("No such institution.")

    statement = build_flag_query(institution_id=institution_id)
    flags = [
        flag_to_dict(flag, role=user.role, institution_name=inst.name if inst else None,
                     state=inst.state if inst else None)
        for flag, inst in db.execute(order_flags(statement, "-severity")).all()
    ]
    profile["flags"] = flags
    return InstitutionProfileOut(
        **suppress_small_counts(profile, user.role, keep_keys=("score", "risk_score"))
    )


# --------------------------------------------------------------------------- flags


@router.get("/flags", response_model=FlagPage)
def list_flags(
    type: Annotated[list[str] | None, Query()] = None,
    severity: Annotated[list[str] | None, Query()] = None,
    status: Annotated[list[str] | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
    institution_id: Annotated[int | None, Query()] = None,
    academic_year: Annotated[str | None, Query()] = None,
    assigned_to: Annotated[str | None, Query()] = None,
    cluster_id: Annotated[int | None, Query()] = None,
    student_id: Annotated[int | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    open_only: Annotated[bool, Query()] = False,
    params: PageParams = Depends(page_params),
    user: CurrentUser = Depends(require_role("aicte_viewer", "aicte_officer")),
    db: Session = Depends(get_db),
) -> FlagPage:
    """The flag queue. Viewers get masked rows with no evidence (Step-0 decision 3)."""
    statement = build_flag_query(
        types=type,
        severities=severity,
        statuses=status,
        state=state,
        institution_id=institution_id,
        academic_year=academic_year,
        assigned_to=assigned_to,
        cluster_id=cluster_id,
        student_id=student_id,
        search=q,
        open_only=open_only,
    )
    facets = flag_facets(db, statement)
    ordered = order_flags(statement, params.sort)
    rows = list(db.execute(ordered).all())
    total = len(rows)
    page_rows = rows[params.offset : params.offset + params.page_size]

    items = [
        flag_to_dict(
            flag,
            role=user.role,
            institution_name=institution.name if institution else None,
            state=institution.state if institution else None,
        )
        for flag, institution in page_rows
    ]
    payload = paginate(
        items, total, PageParams(page=params.page, page_size=params.page_size, sort=params.sort or "-severity")
    )
    payload["facets"] = facets
    return FlagPage(**suppress_small_counts(payload, user.role))


@router.get("/flags/{flag_id}", response_model=FlagDetailOut)
def flag_detail(
    flag_id: int,
    user: CurrentUser = Depends(require_role("aicte_viewer", "aicte_officer")),
    db: Session = Depends(get_db),
) -> FlagDetailOut:
    flag = db.get(Flag, flag_id)
    if flag is None:
        raise_not_found("No such flag.")
    institution = db.get(Institution, flag.institution_id) if flag.institution_id else None
    payload = flag_to_dict(
        flag,
        role=user.role,
        institution_name=institution.name if institution else None,
        state=institution.state if institution else None,
    )

    if user.role == "aicte_officer":
        payload["history"] = flag_history(db, flag_id)
        related = []
        if flag.student_id is not None:
            for other, _institution in db.execute(
                build_flag_query(student_id=flag.student_id)
            ).all():
                if other.id != flag.id:
                    related.append(
                        {"id": other.id, "type": other.type, "severity": other.severity}
                    )
        payload["related_flags"] = related
        if flag.student_id is not None:
            student = db.get(Student, flag.student_id)
            if student is not None:
                payload["students"] = [
                    {
                        "student_id": student.id,
                        "apaar_masked": student.apaar_masked,
                        "name_masked": student.name_masked,
                        "is_minor": student.is_minor,
                    }
                ]
        # Looking at a student's case file is a detail view (CLAUDE.md rule 7).
        if flag.student_id is not None:
            log_access(
                db,
                actor=user.username,
                role=user.role,
                action="view_flag_detail",
                target=f"flag:{flag.id}",
                student_id=flag.student_id,
            )
            db.commit()

    return FlagDetailOut(**payload)


@router.patch("/flags/{flag_id}", response_model=FlagUpdateResponse)
def update_flag_route(
    flag_id: int,
    payload: FlagUpdateRequest,
    user: CurrentUser = Depends(require_role("aicte_officer")),
    db: Session = Depends(get_db),
) -> FlagUpdateResponse:
    """Case management: status, assignment and notes. Officer only, always audited."""
    flag = db.get(Flag, flag_id)
    if flag is None:
        raise_not_found("No such flag.")
    if payload.status is not None and payload.status not in FLAG_STATUSES:
        raise api_error(
            422,
            "VALIDATION_ERROR",
            f"status must be one of {', '.join(FLAG_STATUSES)}.",
        )
    if payload.status in ("dismissed", "resolved") and not (payload.reason or payload.note):
        raise api_error(
            400,
            "REASON_REQUIRED",
            "Dismissing or resolving a flag requires a reason or a note.",
        )

    flag, audit_log_id = update_flag(
        db,
        flag=flag,
        actor=user.username,
        role=user.role,
        status=payload.status,
        assigned_to=payload.assigned_to,
        note=payload.note,
        reason=payload.reason,
    )
    db.commit()

    institution = db.get(Institution, flag.institution_id) if flag.institution_id else None
    return FlagUpdateResponse(
        flag=FlagOut(
            **flag_to_dict(
                flag,
                role=user.role,
                institution_name=institution.name if institution else None,
                state=institution.state if institution else None,
            )
        ),
        audit_log_id=audit_log_id,
    )


# --------------------------------------------------------------------------- reveal


@router.post("/reveal", response_model=RevealResponse)
def reveal(
    payload: RevealRequest,
    user: CurrentUser = Depends(require_role("aicte_officer")),
    db: Session = Depends(get_db),
) -> RevealResponse:
    """Decrypt one student's identifiers. Officer only, reason mandatory, always logged."""
    try:
        result = reveal_student(
            db,
            student_id=payload.student_id,
            reason=payload.reason,
            actor=user.username,
            role=user.role,
        )
    except RevealError as exc:
        raise api_error(400, "REASON_REQUIRED", str(exc))
    except LookupError:
        raise_not_found("No such student.")
    db.commit()
    return RevealResponse(**result)


# --------------------------------------------------------------------------- non-reporting


@router.get("/non-reporting", response_model=NonReportingPage)
def list_non_reporting(
    academic_year: Annotated[str | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
    params: PageParams = Depends(page_params),
    user: CurrentUser = Depends(require_role("aicte_viewer", "aicte_officer")),
    db: Session = Depends(get_db),
) -> NonReportingPage:
    rows = non_reporting(
        db, academic_year=academic_year or settings.current_academic_year, state=state
    )
    total = len(rows)
    page_rows = rows[params.offset : params.offset + params.page_size]
    payload = paginate(
        page_rows, total, PageParams(page=params.page, page_size=params.page_size, sort="name")
    )
    return NonReportingPage(
        **suppress_small_counts(payload, user.role, keep_keys=("days_overdue",))
    )


@router.post("/remind/{institution_id}", response_model=ReminderResponse)
def send_reminder(
    institution_id: int,
    academic_year: Annotated[str | None, Query()] = None,
    user: CurrentUser = Depends(require_role("aicte_officer")),
    db: Session = Depends(get_db),
) -> ReminderResponse:
    """Mocked notification. Nothing is sent anywhere; the action is logged."""
    institution = db.get(Institution, institution_id)
    if institution is None:
        raise_not_found("No such institution.")
    year = academic_year or settings.current_academic_year

    message = (
        f"Student data for {year} is overdue. Please upload student-level records "
        f"keyed on APAAR ID."
    )
    reminder = ReminderLog(
        institution_id=institution_id,
        academic_year=year,
        channel="email",
        message=message,
        actor=user.username,
    )
    db.add(reminder)
    db.flush()
    entry = log_audit(
        db,
        actor=user.username,
        role=user.role,
        action="reminder_sent",
        target=f"institution:{institution_id}",
        payload={"academic_year": year, "channel": "email", "mock": True},
    )
    db.commit()

    return ReminderResponse(
        institution_id=institution_id,
        channel="email",
        status="queued_mock",
        message=message,
        sent_at=reminder.created_at,
        audit_log_id=entry.id,
    )


# --------------------------------------------------------------------------- trends


@router.get("/reports/trends", response_model=TrendsOut)
def report_trends(
    dimension: Annotated[str, Query(pattern="^(state|branch|category|gender|year|mode|admission_type)$")] = "branch",
    academic_year: Annotated[list[str] | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
    institution_id: Annotated[int | None, Query()] = None,
    new_admissions_only: Annotated[bool, Query()] = False,
    user: CurrentUser = Depends(require_role("aicte_viewer", "aicte_officer")),
    db: Session = Depends(get_db),
) -> TrendsOut:
    years = academic_year or list(known_academic_years())
    payload = trends(
        db,
        dimension=dimension,
        academic_years=years,
        state=state,
        institution_id=institution_id,
        new_admissions_only=new_admissions_only,
    )
    payload["csv_url"] = (
        f"/aicte/reports/trends.csv?dimension={dimension}"
        f"&new_admissions_only={str(new_admissions_only).lower()}"
    )
    return TrendsOut(**suppress_small_counts(payload, user.role, keep_keys=("yoy_growth_pct",)))


@router.get("/reports/trends.csv", response_class=PlainTextResponse)
def report_trends_csv(
    dimension: Annotated[str, Query(pattern="^(state|branch|category|gender|year|mode|admission_type)$")] = "branch",
    academic_year: Annotated[list[str] | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
    new_admissions_only: Annotated[bool, Query()] = False,
    user: CurrentUser = Depends(require_role("aicte_viewer", "aicte_officer")),
    db: Session = Depends(get_db),
) -> PlainTextResponse:
    years = academic_year or list(known_academic_years())
    payload = trends(
        db,
        dimension=dimension,
        academic_years=years,
        state=state,
        new_admissions_only=new_admissions_only,
    )
    payload = suppress_small_counts(payload, user.role, keep_keys=("yoy_growth_pct",))
    return PlainTextResponse(
        content=trends_csv(payload),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="trends_{dimension}.csv"'},
    )
