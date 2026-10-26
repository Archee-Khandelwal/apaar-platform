"""Ghost-student graph detector (Step 9 of docs/PLAN.md) — the headline feature.

We build a bipartite graph: student nodes on one side, contact-attribute nodes
(guardian phone, student phone, email) on the other, with an edge wherever a student
reported that contact. Connected components are then families, or clusters.

A normal family shares one guardian contact across 1-3 students. A ghost cluster is
dozens of "students" hanging off two or three phone numbers. The thresholds below are
deliberately **size-aware as well as ratio-aware**, because the generated data contains
both a 6-student family on one contact (ratio 6.0, legitimate) and an 8-student cluster
on three contacts (ratio 2.7, fabricated) — a ratio-only rule would get both wrong.

Everything surfaced is masked: attribute nodes are labelled "Guardian contact #1", never
a hash or a number (CLAUDE.md section 5 rules 1 and 6).
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import networkx as nx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.core import Cluster, Enrolment, Institution, Program, Student
from app.models.enums import ACTIVE_ENROLMENT_STATUSES
from app.services.flags import resolve_stale_flags, upsert_flag

# --- thresholds (tuning choices, not regulation) -----------------------------------
MIN_CLUSTER_STUDENTS = 8  # a family of up to 6-7 siblings/cousins is plausible
MIN_STUDENTS_PER_CONTACT = 2.0  # ... but not two or more students per contact at that size
# No hard cap on the number of shared contacts: a 30-student cluster on 10 contacts is
# still a cluster, and the ratio above already captures "suspiciously few contacts".
# A single contact shared across institutions is suspicious at a lower student count.
CROSS_INSTITUTION_MIN_STUDENTS = 5
NORMAL_FAMILY_MAX = 3  # what a "normal" sibling group looks like, used in explanations

ATTRIBUTE_LABELS = {
    "guardian_phone": "Guardian contact",
    "phone": "Student contact",
    "email": "Email address",
}
ATTRIBUTE_WEIGHT = {"guardian_phone": 1.0, "phone": 0.8, "email": 0.6}


@dataclass
class ClusterCandidate:
    student_ids: list[int]
    attributes: list[tuple[str, str, int]]  # (attribute_type, hash, how many students)
    institution_ids: list[int]
    academic_years: list[str]

    @property
    def size(self) -> int:
        return len(self.student_ids)

    @property
    def shared_attributes(self) -> list[tuple[str, str, int]]:
        """Only the contacts that actually link two or more students.

        Every student also reports their own phone and email, which appear as
        degree-1 nodes. Counting those would make a 26-student cluster look like it had
        54 contacts, so the thresholds below use shared contacts only.
        """
        return [item for item in self.attributes if item[2] >= 2]

    @property
    def attribute_count(self) -> int:
        return len(self.shared_attributes)

    @property
    def total_attribute_count(self) -> int:
        return len(self.attributes)

    @property
    def students_per_contact(self) -> float:
        return self.size / max(self.attribute_count, 1)

    def counts_by_type(self) -> dict[str, int]:
        counts: dict[str, int] = defaultdict(int)
        for attribute_type, _hash, _degree in self.shared_attributes:
            counts[attribute_type] += 1
        return dict(counts)


@dataclass
class ScoredCluster:
    candidate: ClusterCandidate
    score: float
    severity: str
    reasons: list[str] = field(default_factory=list)


def _attribute_nodes(student: Student) -> list[tuple[str, str]]:
    nodes: list[tuple[str, str]] = []
    if student.guardian_phone_hash:
        nodes.append(("guardian_phone", student.guardian_phone_hash))
    if student.phone_hash:
        nodes.append(("phone", student.phone_hash))
    if student.email_hash:
        nodes.append(("email", student.email_hash))
    return nodes


def build_graph(db: Session, *, academic_year: str | None = None) -> nx.Graph:
    """Student nodes plus attribute nodes, edges student -> each contact they reported."""
    statement = select(Student)
    if academic_year:
        statement = (
            select(Student)
            .join(Enrolment, Enrolment.student_id == Student.id)
            .where(
                Enrolment.academic_year == academic_year,
                Enrolment.status.in_(ACTIVE_ENROLMENT_STATUSES),
            )
            .distinct()
        )

    graph = nx.Graph()
    students = list(db.execute(statement).scalars())
    student_ids = [student.id for student in students]

    institutions_by_student: dict[int, set[int]] = defaultdict(set)
    years_by_student: dict[int, set[str]] = defaultdict(set)
    if student_ids:
        for student_id, institution_id, year in db.execute(
            select(Enrolment.student_id, Enrolment.institution_id, Enrolment.academic_year).where(
                Enrolment.student_id.in_(student_ids),
                Enrolment.status.in_(ACTIVE_ENROLMENT_STATUSES),
            )
        ).all():
            institutions_by_student[student_id].add(institution_id)
            years_by_student[student_id].add(year)

    for student in students:
        attributes = _attribute_nodes(student)
        if not attributes:
            continue
        node = f"s{student.id}"
        graph.add_node(
            node,
            kind="student",
            student_id=student.id,
            institution_ids=sorted(institutions_by_student.get(student.id, set())),
            academic_years=sorted(years_by_student.get(student.id, set())),
        )
        for attribute_type, value_hash in attributes:
            attribute_node = f"{attribute_type}:{value_hash}"
            graph.add_node(attribute_node, kind=attribute_type, value_hash=value_hash)
            graph.add_edge(node, attribute_node, attribute_type=attribute_type)
    return graph


def find_candidates(graph: nx.Graph) -> list[ClusterCandidate]:
    """One candidate per connected component that has more than one student."""
    candidates: list[ClusterCandidate] = []
    for component in nx.connected_components(graph):
        student_ids: list[int] = []
        attributes: list[tuple[str, str, int]] = []
        institutions: set[int] = set()
        years: set[str] = set()
        for node in component:
            data = graph.nodes[node]
            if data["kind"] == "student":
                student_ids.append(data["student_id"])
                institutions.update(data.get("institution_ids") or [])
                years.update(data.get("academic_years") or [])
            else:
                attributes.append((data["kind"], data["value_hash"], graph.degree(node)))
        if len(student_ids) < 2:
            continue
        candidates.append(
            ClusterCandidate(
                student_ids=sorted(student_ids),
                attributes=sorted(attributes),
                institution_ids=sorted(institutions),
                academic_years=sorted(years),
            )
        )
    return candidates


def is_suspicious(candidate: ClusterCandidate) -> tuple[bool, list[str]]:
    """Size-aware rule. Returns (suspicious, reasons)."""
    reasons: list[str] = []

    big_enough = candidate.size >= MIN_CLUSTER_STUDENTS
    dense = candidate.students_per_contact >= MIN_STUDENTS_PER_CONTACT

    if big_enough and dense:
        reasons.append(
            f"{candidate.size} students are linked through only {candidate.attribute_count} "
            f"contact(s) — {candidate.students_per_contact:.1f} students per contact, where a "
            f"family normally has 1 contact for {NORMAL_FAMILY_MAX} students at most"
        )

    if len(candidate.institution_ids) > 1 and candidate.size >= CROSS_INSTITUTION_MIN_STUDENTS:
        reasons.append(
            f"the same contact details are shared by {candidate.size} students across "
            f"{len(candidate.institution_ids)} institutions, which a single family would not do"
        )

    return bool(reasons), reasons


def score_cluster(candidate: ClusterCandidate) -> ScoredCluster:
    """0-100. Size, density and the number of institutions involved all push it up."""
    _suspicious, reasons = is_suspicious(candidate)

    size_part = min(candidate.size / 30.0, 1.0) * 45.0
    density_part = min(candidate.students_per_contact / 10.0, 1.0) * 30.0
    institution_part = min(max(len(candidate.institution_ids) - 1, 0) / 2.0, 1.0) * 15.0
    weight = max(
        (
            ATTRIBUTE_WEIGHT.get(attribute_type, 0.5)
            for attribute_type, _hash, _degree in candidate.shared_attributes
        ),
        default=0.5,
    )
    type_part = weight * 10.0

    score = round(min(size_part + density_part + institution_part + type_part, 100.0), 1)

    if score >= 75:
        severity = "critical"
    elif score >= 55:
        severity = "high"
    else:
        # Anything that trips the rule is worth a look: "low" is reserved for the
        # healthy clusters kept for the side-by-side comparison.
        severity = "medium" if reasons else "low"
    return ScoredCluster(candidate=candidate, score=score, severity=severity, reasons=reasons)


def _summary_text(
    cluster: ScoredCluster, institution_names: list[str], attribute_counts: dict[str, int]
) -> str:
    where = institution_names[0] if len(institution_names) == 1 else f"{len(institution_names)} institutions"
    contacts = ", ".join(
        f"{count} {ATTRIBUTE_LABELS.get(attribute_type, attribute_type).lower()}"
        + ("s" if count != 1 else "")
        for attribute_type, count in sorted(attribute_counts.items())
    )
    return (
        f"{cluster.candidate.size} students at {where} share only {contacts} — "
        f"typical families share one contact per 1-{NORMAL_FAMILY_MAX} students."
    )


def _graph_payload(
    db: Session,
    candidate: ClusterCandidate,
    *,
    institution_names: dict[int, str],
) -> dict[str, Any]:
    """Cytoscape-ready JSON. Labels are masked; contacts are numbered, never shown."""
    students = {
        student.id: student
        for student in db.execute(
            select(Student).where(Student.id.in_(candidate.student_ids))
        ).scalars()
    }
    programs: dict[int, tuple[str, str, int]] = {}
    for enrolment, program in db.execute(
        select(Enrolment, Program)
        .join(Program, Program.id == Enrolment.program_id)
        .where(
            Enrolment.student_id.in_(candidate.student_ids),
            Enrolment.status.in_(ACTIVE_ENROLMENT_STATUSES),
        )
        .order_by(Enrolment.academic_year.desc())
    ).all():
        programs.setdefault(
            enrolment.student_id,
            (f"{program.course} {program.branch}", enrolment.academic_year, enrolment.institution_id),
        )

    # Number the attribute nodes per type: "Guardian contact #1", "#2", ...
    numbering: dict[tuple[str, str], int] = {}
    per_type: dict[str, int] = defaultdict(int)
    # Only the shared contacts are drawn: a node per student's own phone would add
    # nothing to the picture.
    for attribute_type, value_hash, _degree in candidate.shared_attributes:
        per_type[attribute_type] += 1
        numbering[(attribute_type, value_hash)] = per_type[attribute_type]

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    for student_id in candidate.student_ids:
        student = students.get(student_id)
        if student is None:  # pragma: no cover
            continue
        program, year, institution_id = programs.get(student_id, ("—", "—", 0))
        nodes.append(
            {
                "data": {
                    "id": f"s{student_id}",
                    "label": student.name_masked,
                    "type": "student",
                    "student_id": student_id,
                    "apaar_masked": student.apaar_masked,
                    "institution": institution_names.get(institution_id, "—"),
                    "institution_id": institution_id,
                    "program": program,
                    "academic_year": year,
                }
            }
        )

    for (attribute_type, value_hash), number in numbering.items():
        label = f"{ATTRIBUTE_LABELS.get(attribute_type, attribute_type)} #{number}"
        node_id = f"{attribute_type}-{number}"
        degree = 0
        for student_id in candidate.student_ids:
            student = students.get(student_id)
            if student is None:  # pragma: no cover
                continue
            if getattr(student, f"{attribute_type}_hash", None) == value_hash:
                degree += 1
                edges.append(
                    {
                        "data": {
                            "source": f"s{student_id}",
                            "target": node_id,
                            "attribute_type": attribute_type,
                            "label": ATTRIBUTE_LABELS.get(attribute_type, attribute_type).lower(),
                        }
                    }
                )
        nodes.append(
            {
                "data": {
                    "id": node_id,
                    "label": label,
                    "type": attribute_type,
                    "degree": degree,
                }
            }
        )

    return {"nodes": nodes, "edges": edges}


def detect_ghost_clusters(
    db: Session, *, academic_year: str | None = None
) -> dict[str, int]:
    """Rebuild the graph, store clusters, and raise GHOST_CLUSTER flags."""
    graph = build_graph(db, academic_year=academic_year)
    candidates = find_candidates(graph)

    institution_names = {
        institution.id: institution.name
        for institution in db.execute(select(Institution)).scalars()
    }

    suspicious: list[ScoredCluster] = []
    normal: list[ScoredCluster] = []
    for candidate in candidates:
        scored = score_cluster(candidate)
        (suspicious if scored.reasons else normal).append(scored)

    # Replace stored clusters: ids are regenerated each run, flags are keyed by content.
    db.query(Cluster).delete()
    db.flush()

    created = 0
    updated = 0
    keep: set[str] = set()

    for scored in sorted(suspicious, key=lambda item: item.score, reverse=True):
        candidate = scored.candidate
        attribute_counts = candidate.counts_by_type()
        names = [institution_names.get(i, "—") for i in candidate.institution_ids]
        summary = _summary_text(scored, names, attribute_counts)
        payload = _graph_payload(db, candidate, institution_names=institution_names)
        year = candidate.academic_years[-1] if candidate.academic_years else academic_year

        cluster = Cluster(
            score=scored.score,
            severity=scored.severity,
            student_count=candidate.size,
            attribute_count=candidate.attribute_count,
            institutions_involved=len(candidate.institution_ids),
            kind="suspicious",
            academic_year=year,
            summary=summary,
            metrics={
                "student_count": candidate.size,
                "attribute_count": candidate.attribute_count,
                "students_per_contact": round(candidate.students_per_contact, 2),
                "attributes_per_student": round(candidate.attribute_count / candidate.size, 3),
                "total_contact_values": candidate.total_attribute_count,
                "institutions_involved": len(candidate.institution_ids),
                "shared_attributes": attribute_counts,
                "reasons": scored.reasons,
            },
            graph=payload,
            member_student_ids=candidate.student_ids,
            institution_ids=candidate.institution_ids,
        )
        db.add(cluster)
        db.flush()

        dedupe_key = "cluster:" + ",".join(str(i) for i in candidate.student_ids[:50])
        keep.add(dedupe_key)
        _flag, was_created = upsert_flag(
            db,
            type="GHOST_CLUSTER",
            dedupe_key=dedupe_key,
            severity=scored.severity,
            title=f"Cluster of {candidate.size} students sharing {candidate.attribute_count} contact(s)",
            explanation=summary + " Why this was flagged: " + "; ".join(scored.reasons) + ".",
            evidence={
                "cluster_id": cluster.id,
                "score": scored.score,
                "student_count": candidate.size,
                "shared_attributes": attribute_counts,
                "students_per_contact": round(candidate.students_per_contact, 2),
                "institutions": names,
                "student_ids_masked": [
                    node["data"]["apaar_masked"]
                    for node in payload["nodes"]
                    if node["data"]["type"] == "student"
                ][:20],
                "reasons": scored.reasons,
            },
            institution_id=candidate.institution_ids[0] if candidate.institution_ids else None,
            cluster_id=cluster.id,
            academic_year=year,
        )
        created += int(was_created)
        updated += int(not was_created)

    # Keep a handful of healthy clusters for the "compare with a normal cluster" toggle.
    for scored in sorted(normal, key=lambda item: item.candidate.size, reverse=True)[:12]:
        candidate = scored.candidate
        names = [institution_names.get(i, "—") for i in candidate.institution_ids]
        db.add(
            Cluster(
                score=scored.score,
                severity="low",
                student_count=candidate.size,
                attribute_count=candidate.attribute_count,
                institutions_involved=len(candidate.institution_ids),
                kind="normal",
                academic_year=candidate.academic_years[-1] if candidate.academic_years else None,
                summary=(
                    f"{candidate.size} students at {names[0] if names else '—'} share "
                    f"{candidate.attribute_count} contact(s) — consistent with a family."
                ),
                metrics={
                    "student_count": candidate.size,
                    "attribute_count": candidate.attribute_count,
                    "students_per_contact": round(candidate.students_per_contact, 2),
                    "institutions_involved": len(candidate.institution_ids),
                    "shared_attributes": candidate.counts_by_type(),
                },
                graph=_graph_payload(db, candidate, institution_names=institution_names),
                member_student_ids=candidate.student_ids,
                institution_ids=candidate.institution_ids,
            )
        )

    closed = resolve_stale_flags(db, type="GHOST_CLUSTER", keep_keys=keep)
    db.flush()
    return {
        "ghost_clusters": created,
        "ghost_clusters_updated": updated,
        "ghost_clusters_closed": closed,
        "normal_clusters_kept": len(normal[:12]),
    }
