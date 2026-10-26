"""Step 2: the audit chain validates, and any tampering is detected."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.audit import GENESIS_HASH, compute_hash, log_audit, verify_chain
from app.core.db import Base
from app.core.access_log import log_access
from app.models.core import AccessLog, AuditLog, Student


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()


def _three_rows(db: Session) -> None:
    log_audit(db, actor="vit_admin", role="institution", action="upload_created", target="upload:1")
    log_audit(db, actor="aicte_officer1", role="aicte_officer", action="flag_status_change", target="flag:1")
    log_audit(db, actor="admin", role="admin", action="reseed", target="database")
    db.commit()


def test_empty_chain_is_valid(db: Session) -> None:
    result = verify_chain(db)
    assert result.ok is True
    assert result.rows_checked == 0


def test_valid_chain_passes(db: Session) -> None:
    _three_rows(db)
    result = verify_chain(db)
    assert result.ok is True
    assert result.rows_checked == 3


def test_first_row_links_to_genesis(db: Session) -> None:
    _three_rows(db)
    rows = db.query(AuditLog).order_by(AuditLog.id).all()
    assert rows[0].prev_hash == GENESIS_HASH
    assert rows[1].prev_hash == rows[0].hash
    assert rows[2].prev_hash == rows[1].hash


def test_tampered_payload_is_detected(db: Session) -> None:
    _three_rows(db)
    target = db.query(AuditLog).order_by(AuditLog.id).all()[1]
    target.payload = {"tampered": True}
    db.commit()

    result = verify_chain(db)
    assert result.ok is False
    assert result.first_broken_row is not None
    assert result.first_broken_row["id"] == target.id


def test_tampered_actor_is_detected(db: Session) -> None:
    _three_rows(db)
    target = db.query(AuditLog).order_by(AuditLog.id).all()[0]
    target.actor = "someone_else"
    db.commit()

    result = verify_chain(db)
    assert result.ok is False
    assert result.first_broken_row["id"] == target.id


def test_deleted_row_breaks_the_chain(db: Session) -> None:
    _three_rows(db)
    rows = db.query(AuditLog).order_by(AuditLog.id).all()
    db.delete(rows[1])
    db.commit()

    result = verify_chain(db)
    assert result.ok is False
    assert result.first_broken_row["id"] == rows[2].id


def test_rehashing_a_tampered_row_still_breaks_the_following_row(db: Session) -> None:
    """An attacker who recomputes one row's own hash still breaks the next link."""
    _three_rows(db)
    rows = db.query(AuditLog).order_by(AuditLog.id).all()
    target = rows[1]
    target.payload = {"tampered": True}
    target.hash = compute_hash(
        target.prev_hash,
        {
            "id": target.id,
            "actor": target.actor,
            "role": target.role,
            "action": target.action,
            "target": target.target,
            "payload": target.payload,
            "created_at": target.created_at,
        },
    )
    db.commit()

    result = verify_chain(db)
    assert result.ok is False
    assert result.first_broken_row["id"] == rows[2].id


def test_access_log_records_actor_role_action_target_reason(db: Session) -> None:
    student = Student(apaar_masked="XXXX-XXXX-1234", name_masked="R**** S.")
    db.add(student)
    db.flush()

    log_access(
        db,
        actor="aicte_officer1",
        role="aicte_officer",
        action="reveal_student_details",
        target=f"student:{student.id}",
        reason="Verifying duplicate enrolment case #501.",
        student_id=student.id,
    )
    db.commit()

    entry = db.query(AccessLog).one()
    assert entry.actor == "aicte_officer1"
    assert entry.role == "aicte_officer"
    assert entry.action == "reveal_student_details"
    assert entry.target == f"student:{student.id}"
    assert entry.reason.startswith("Verifying")
    assert entry.created_at is not None
