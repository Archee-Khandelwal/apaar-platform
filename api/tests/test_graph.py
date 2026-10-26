"""Step 9: the ghost-student graph detector."""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crypto import hash_email, hash_phone, hmac_hash, mask_apaar, mask_name
from app.models.core import AccessLog, Cluster, Enrolment, Flag, Program, Student
from app.services.graph import (
    MIN_CLUSTER_STUDENTS,
    build_graph,
    detect_ghost_clusters,
    find_candidates,
    score_cluster,
)

YEAR = "2026-27"
REPO = Path(__file__).resolve().parents[2]
GROUND_TRUTH = REPO / "datagen" / "ground_truth.json"
DEMO_DB = REPO / "apaar.db"


def _demo_session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    return sessionmaker(bind=create_engine(f"sqlite:///{DEMO_DB}"), expire_on_commit=False)()


def add_group(
    db: Session,
    program: Program,
    *,
    count: int,
    guardian_phones: list[str],
    shared_email: str | None = None,
    year: str = YEAR,
) -> list[int]:
    """Add ``count`` students sharing the given guardian phones (round-robin)."""
    ids: list[int] = []
    for index in range(count):
        apaar = f"{9_000_000_000_00 + len(ids) + hash(program.id) % 1000:012d}"[:12]
        student = Student(
            apaar_hash=hmac_hash(f"{program.id}-{year}-{index}"),
            apaar_masked=mask_apaar(apaar),
            name_masked=mask_name(f"Student Number{index}"),
            guardian_phone_hash=hash_phone(guardian_phones[index % len(guardian_phones)]),
            phone_hash=hash_phone(f"9{index:09d}{program.id:02d}"[-10:]),
            email_hash=hash_email(shared_email) if shared_email else hash_email(f"s{index}.{program.id}@x.invalid"),
        )
        db.add(student)
        db.flush()
        db.add(
            Enrolment(
                student_id=student.id,
                program_id=program.id,
                institution_id=program.institution_id,
                academic_year=year,
                year_of_study=1,
                admission_type="regular",
                status="admitted",
                admitted_on=date(2026, 8, 1),
            )
        )
        ids.append(student.id)
    db.commit()
    return ids


@pytest.fixture()
def programs(db: Session, two_institutions) -> tuple[Program, Program]:
    first, second = two_institutions
    return (
        db.execute(select(Program).where(Program.institution_id == first.id)).scalars().first(),
        db.execute(select(Program).where(Program.institution_id == second.id)).scalars().first(),
    )


def clusters(db: Session, kind: str = "suspicious") -> list[Cluster]:
    return list(
        db.execute(select(Cluster).where(Cluster.kind == kind).order_by(Cluster.score.desc())).scalars()
    )


# ------------------------------------------------------------------ graph construction


def test_graph_links_students_to_their_contacts(db: Session, programs) -> None:
    first, _ = programs
    add_group(db, first, count=3, guardian_phones=["9811100000"], shared_email="shared@x.invalid")
    graph = build_graph(db)

    student_nodes = [n for n, d in graph.nodes(data=True) if d["kind"] == "student"]
    guardian_nodes = [n for n, d in graph.nodes(data=True) if d["kind"] == "guardian_phone"]
    assert len(student_nodes) == 3
    assert len(guardian_nodes) == 1  # one shared number
    assert graph.degree(guardian_nodes[0]) == 3


def test_components_separate_unrelated_families(db: Session, programs) -> None:
    first, second = programs
    add_group(db, first, count=3, guardian_phones=["9811100000"])
    add_group(db, second, count=2, guardian_phones=["9822200000"])
    candidates = find_candidates(build_graph(db))
    assert sorted(candidate.size for candidate in candidates) == [2, 3]


def test_shared_contacts_exclude_each_students_own_phone(db: Session, programs) -> None:
    """A cluster's contact count must not include every member's unique phone/email."""
    first, _ = programs
    add_group(db, first, count=10, guardian_phones=["9811100000", "9811100001"], shared_email="one@x.invalid")
    candidate = max(find_candidates(build_graph(db)), key=lambda item: item.size)
    assert candidate.size == 10
    assert candidate.attribute_count == 3  # 2 guardian numbers + 1 shared email
    assert candidate.total_attribute_count > candidate.attribute_count  # the unique phones
    assert candidate.students_per_contact == pytest.approx(10 / 3, abs=0.01)


# ------------------------------------------------------------------ the rule


def test_a_large_cluster_on_few_contacts_is_flagged(db: Session, programs) -> None:
    first, _ = programs
    add_group(db, first, count=30, guardian_phones=["9811100000", "9811100001"], shared_email="cell@x.invalid")
    summary = detect_ghost_clusters(db)
    db.commit()

    assert summary["ghost_clusters"] == 1
    cluster = clusters(db)[0]
    assert cluster.student_count == 30
    assert cluster.severity in ("high", "critical")
    assert "share only" in cluster.summary
    assert cluster.metrics["reasons"]


def test_a_medium_cluster_is_also_flagged(db: Session, programs) -> None:
    """8 students on 4 contacts: the same ratio as a 3-sibling family, but bigger."""
    first, _ = programs
    add_group(
        db, first, count=8,
        guardian_phones=["9811100000", "9811100001", "9811100002"],
        shared_email="cell@x.invalid",
    )
    detect_ghost_clusters(db)
    db.commit()

    found = clusters(db)
    assert len(found) == 1
    assert found[0].student_count == 8
    assert found[0].severity != "low"  # 'low' is reserved for healthy clusters


def test_normal_sibling_pairs_are_not_flagged(db: Session, programs) -> None:
    first, second = programs
    add_group(db, first, count=2, guardian_phones=["9811100000"])
    add_group(db, second, count=3, guardian_phones=["9822200000"])
    summary = detect_ghost_clusters(db)
    db.commit()
    assert summary["ghost_clusters"] == 0
    assert clusters(db) == []


def test_a_six_student_family_on_one_contact_is_not_flagged(db: Session, programs) -> None:
    """The hard control: ratio 6.0, worse than the medium cluster's 2.0, but small."""
    first, _ = programs
    add_group(db, first, count=6, guardian_phones=["9811100000"])
    detect_ghost_clusters(db)
    db.commit()
    assert clusters(db) == []
    assert clusters(db, "normal")  # kept for the comparison view


def test_the_size_threshold_is_the_discriminator(db: Session, programs) -> None:
    first, _ = programs
    add_group(db, first, count=MIN_CLUSTER_STUDENTS - 1, guardian_phones=["9811100000"])
    detect_ghost_clusters(db)
    db.commit()
    assert clusters(db) == []

    add_group(db, first, count=1, guardian_phones=["9811100000"])  # now at the threshold
    detect_ghost_clusters(db)
    db.commit()
    assert len(clusters(db)) == 1


def test_one_contact_shared_across_institutions_is_flagged_sooner(
    db: Session, programs
) -> None:
    first, second = programs
    shared = "9833300000"
    add_group(db, first, count=3, guardian_phones=[shared])
    add_group(db, second, count=3, guardian_phones=[shared])
    detect_ghost_clusters(db)
    db.commit()

    found = clusters(db)
    assert len(found) == 1
    assert found[0].institutions_involved == 2
    assert any("institutions" in reason for reason in found[0].metrics["reasons"])


def test_score_rises_with_size_density_and_institutions(db: Session, programs) -> None:
    first, _ = programs
    add_group(db, first, count=10, guardian_phones=["9811100000"])
    small = score_cluster(max(find_candidates(build_graph(db)), key=lambda c: c.size))

    add_group(db, first, count=25, guardian_phones=["9811100000"])
    big = score_cluster(max(find_candidates(build_graph(db)), key=lambda c: c.size))
    assert big.score > small.score


# ------------------------------------------------------------------ privacy


def test_the_graph_payload_never_contains_a_hash_or_a_phone_number(
    db: Session, programs
) -> None:
    first, _ = programs
    add_group(db, first, count=12, guardian_phones=["9811100000", "9811100001"], shared_email="cell@x.invalid")
    detect_ghost_clusters(db)
    db.commit()

    blob = json.dumps(clusters(db)[0].graph)
    assert "9811100000" not in blob
    assert "cell@x.invalid" not in blob
    assert not re.search(r"\b[0-9a-f]{64}\b", blob), "a hash leaked into the graph payload"
    assert "Guardian contact #1" in blob
    assert "Guardian contact #2" in blob
    # Student labels are masked.
    for node in clusters(db)[0].graph["nodes"]:
        if node["data"]["type"] == "student":
            assert "*" in node["data"]["label"]
            assert node["data"]["apaar_masked"].startswith("XXXX-XXXX-")


def test_only_shared_contacts_are_drawn(db: Session, programs) -> None:
    first, _ = programs
    add_group(db, first, count=9, guardian_phones=["9811100000"])
    detect_ghost_clusters(db)
    db.commit()
    nodes = clusters(db)[0].graph["nodes"]
    kinds = [node["data"]["type"] for node in nodes]
    assert kinds.count("student") == 9
    assert kinds.count("guardian_phone") == 1
    assert "phone" not in kinds  # each student's own phone is not drawn


# ------------------------------------------------------------------ idempotency


def test_rerunning_does_not_duplicate_clusters_or_flags(db: Session, programs) -> None:
    first, _ = programs
    add_group(db, first, count=15, guardian_phones=["9811100000"])
    detect_ghost_clusters(db)
    db.commit()
    detect_ghost_clusters(db)
    db.commit()

    assert len(clusters(db)) == 1
    assert len(list(db.execute(select(Flag).where(Flag.type == "GHOST_CLUSTER")).scalars())) == 1


# ------------------------------------------------------------------ routes


def test_cluster_routes_are_aicte_only_and_log_access(
    client: TestClient, auth, db: Session, programs
) -> None:
    first, _ = programs
    add_group(db, first, count=14, guardian_phones=["9811100000"])
    detect_ghost_clusters(db)
    db.commit()
    cluster_id = clusters(db)[0].id

    for role in ("institution", "student", "verifier", "admin"):
        assert client.get("/aicte/graph/clusters", headers=auth(role)).status_code == 403

    listing = client.get("/aicte/graph/clusters", headers=auth("aicte_officer")).json()
    assert listing["total"] == 1
    assert listing["items"][0]["summary"]
    assert listing["items"][0]["flag_id"]

    detail = client.get(f"/aicte/graph/clusters/{cluster_id}", headers=auth("aicte_officer"))
    assert detail.status_code == 200
    body = detail.json()
    assert len(body["nodes"]) == 15  # 14 students + 1 shared contact
    assert body["edges"]
    assert body["legend"]["student"]
    assert body["access_log_id"]

    # CLAUDE.md section 5 rule 7: the view is in the access log.
    entry = db.get(AccessLog, body["access_log_id"])
    assert entry.action == "view_cluster"
    assert entry.target == f"cluster:{cluster_id}"


def test_viewer_gets_suppressed_counts(client: TestClient, auth, db: Session, programs) -> None:
    first, second = programs
    add_group(db, first, count=14, guardian_phones=["9811100000"])
    add_group(db, second, count=9, guardian_phones=["9822200000"])
    detect_ghost_clusters(db)
    db.commit()

    body = client.get("/aicte/graph/clusters", headers=auth("aicte_viewer")).json()
    counts = [item["shared_attributes"] for item in body["items"]]
    # One shared guardian contact per cluster is a count below 5 -> suppressed.
    assert all(entry.get("guardian_phone") == "<5" for entry in counts)


def test_normal_comparison_returns_a_healthy_cluster(
    client: TestClient, auth, db: Session, programs
) -> None:
    first, second = programs
    add_group(db, first, count=20, guardian_phones=["9811100000"])
    add_group(db, second, count=3, guardian_phones=["9822200000"])
    detect_ghost_clusters(db)
    db.commit()
    cluster_id = clusters(db)[0].id

    body = client.get(
        f"/aicte/graph/clusters/{cluster_id}/normal-comparison", headers=auth("aicte_officer")
    ).json()
    assert body["kind"] == "normal"
    assert body["metrics"]["student_count"] == 3
    assert "consistent with a family" in body["summary"]


def test_unknown_cluster_is_404(client: TestClient, auth) -> None:
    assert client.get("/aicte/graph/clusters/999", headers=auth("aicte_officer")).status_code == 404


# ------------------------------------------------------------------ ground truth


@pytest.mark.skipif(
    not (GROUND_TRUTH.exists() and DEMO_DB.exists()), reason="run `make reset` first"
)
def test_all_three_seeded_clusters_are_found_with_no_false_positives() -> None:
    truth = json.loads(GROUND_TRUTH.read_text())["scenarios"]
    db = _demo_session()
    try:
        found = list(
            db.execute(select(Cluster).where(Cluster.kind == "suspicious")).scalars()
        )
        found_institutions = {ids for cluster in found for ids in (cluster.institution_ids or [])}

        injected = {case["institution_id"] for case in truth["B_ghost_cluster"]}
        assert injected <= found_institutions, (
            f"clusters missed at institutions {sorted(injected - found_institutions)}"
        )

        # Each injected cluster is ONE component, with the right size.
        by_institution = {
            cluster.institution_ids[0]: cluster for cluster in found if cluster.institution_ids
        }
        for case in truth["B_ghost_cluster"]:
            cluster = by_institution[case["institution_id"]]
            assert cluster.student_count == case["details"]["students"], (
                f"{case['institution_name']}: cluster fragmented or merged "
                f"({cluster.student_count} vs {case['details']['students']})"
            )

        # And the sibling / family controls produced none.
        control_institutions = {case["institution_id"] for case in truth["B_sibling_control"]}
        false_positives = control_institutions & found_institutions
        assert not false_positives, f"families flagged as clusters: {sorted(false_positives)}"

        # The medium cluster is found too, not just the blatant ones.
        medium = [case for case in truth["B_ghost_cluster"] if case["details"]["band"] == "medium"]
        assert medium
        assert by_institution[medium[0]["institution_id"]].severity != "low"
    finally:
        db.close()
