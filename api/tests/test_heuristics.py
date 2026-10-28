"""Step 10: the late-admission and APAAR-registry detectors."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crypto import hmac_hash, mask_apaar, mask_name, vault_encrypt
from app.models.core import Enrolment, Flag, Program, Student, Vault
from app.services.heuristics import detect_apaar_problems, detect_late_admissions
from app.services.rules import year_calendar

YEAR = "2026-27"
PREVIOUS = "2025-26"
REPO = Path(__file__).resolve().parents[2]
GROUND_TRUTH = REPO / "datagen" / "ground_truth.json"
DEMO_DB = REPO / "apaar.db"


def _demo_session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    return sessionmaker(bind=create_engine(f"sqlite:///{DEMO_DB}"), expire_on_commit=False)()


@pytest.fixture()
def program(db: Session, two_institutions) -> Program:
    first, _ = two_institutions
    return db.execute(select(Program).where(Program.institution_id == first.id)).scalars().first()


def add(
    db: Session,
    program: Program,
    *,
    apaar: str | None = None,
    year: str = YEAR,
    year_of_study: int = 1,
    admission_type: str = "regular",
    status: str = "admitted",
    admitted_on: date | None = None,
    created_at: datetime | None = None,
    registry_status: str | None = None,
) -> Student:
    student = Student(
        apaar_hash=hmac_hash(apaar) if apaar else None,
        apaar_masked=mask_apaar(apaar) if apaar else "XXXX-XXXX-XXXX",
        apaar_status="provided" if apaar else "pending",
        name_masked=mask_name("Test Student"),
        registry_status=registry_status,
    )
    db.add(student)
    db.flush()
    if apaar:
        db.add(Vault(student_id=student.id, apaar_enc=vault_encrypt(apaar)))
    db.add(
        Enrolment(
            student_id=student.id,
            program_id=program.id,
            institution_id=program.institution_id,
            academic_year=year,
            year_of_study=year_of_study,
            admission_type=admission_type,
            status=status,
            admitted_on=admitted_on or date(2026, 8, 1),
            created_at=created_at or datetime(2026, 10, 1),
        )
    )
    db.commit()
    return student


def flags(db: Session, type_: str) -> list[Flag]:
    return list(db.execute(select(Flag).where(Flag.type == type_)).scalars())


# ------------------------------------------------------------------ late admissions


def test_late_admissions_are_aggregated_per_institution(db: Session, program) -> None:
    calendar = year_calendar(YEAR)
    for _ in range(90):
        add(db, program, admitted_on=calendar.admission_window_start)
    for _ in range(10):
        add(db, program, admitted_on=calendar.admission_window_end + timedelta(days=12))

    summary = detect_late_admissions(db, academic_year=YEAR)
    db.commit()
    assert summary["late_admission_institutions"] == 1
    flag = [f for f in flags(db, "LATE_ADMISSION") if f.enrolment_id is None][0]
    assert flag.evidence["late_count"] == 10
    assert flag.evidence["total_admissions"] == 100
    assert flag.evidence["share_percent"] == 10.0
    assert "after the" in flag.explanation


def test_a_couple_of_late_admissions_is_not_flagged(db: Session, program) -> None:
    calendar = year_calendar(YEAR)
    for _ in range(100):
        add(db, program, admitted_on=calendar.admission_window_start)
    for _ in range(2):
        add(db, program, admitted_on=calendar.admission_window_end + timedelta(days=3))
    detect_late_admissions(db, academic_year=YEAR)
    db.commit()
    assert [f for f in flags(db, "LATE_ADMISSION") if f.enrolment_id is None] == []


def test_lateral_entrants_are_judged_against_their_own_later_window(
    db: Session, program
) -> None:
    calendar = year_calendar(YEAR)
    # After the regular cutoff but inside the lateral window: not late.
    inside = calendar.admission_window_end + timedelta(days=5)
    assert inside <= calendar.lateral_window_end
    for _ in range(30):
        add(db, program, admission_type="lateral", year_of_study=2, admitted_on=inside)
    detect_late_admissions(db, academic_year=YEAR)
    db.commit()
    assert [f for f in flags(db, "LATE_ADMISSION") if f.enrolment_id is None] == []


# ------------------------------------------------------------------ APAAR problems


def test_registry_problems_become_flags(db: Session, program) -> None:
    add(db, program, apaar="111111111111", registry_status="not_found")
    add(db, program, apaar="222222222222", registry_status="mismatch")
    add(db, program, apaar="33333333333", registry_status="invalid_format")
    add(db, program, apaar="444444444444", registry_status="match")

    summary = detect_apaar_problems(db)
    db.commit()
    assert summary["apaar_problems"] == 3
    assert len(flags(db, "APAAR_NOT_FOUND")) == 1
    assert len(flags(db, "APAAR_MISMATCH")) == 1
    assert len(flags(db, "INVALID_APAAR")) == 1
    assert flags(db, "APAAR_NOT_FOUND")[0].severity == "high"
    for type_ in ("APAAR_NOT_FOUND", "APAAR_MISMATCH", "INVALID_APAAR"):
        flag = flags(db, type_)[0]
        assert flag.explanation
        assert flag.evidence["apaar_masked"].startswith("XXXX-XXXX-")


# ------------------------------------------------------------------ idempotency


def test_run_all_detectors_is_idempotent(db: Session, program) -> None:
    from app.services.detectors import run_all_detectors

    calendar = year_calendar(YEAR)
    for _ in range(10):
        add(db, program, admitted_on=calendar.admission_window_end + timedelta(days=9))
    add(db, program, apaar="888888888888", registry_status="not_found")

    first = run_all_detectors(db)
    before = len(list(db.execute(select(Flag)).scalars()))
    second = run_all_detectors(db)
    after = len(list(db.execute(select(Flag)).scalars()))

    assert before == after, "a second run created duplicate flags"
    assert first["late_admission_institutions"] == 1
    assert second["late_admission_institutions"] == 0
    assert second["late_admission_updated"] >= 1
    assert "duration_ms" in second


# ------------------------------------------------------------------ ground truth


@pytest.mark.skipif(
    not (GROUND_TRUTH.exists() and DEMO_DB.exists()), reason="run `make reset` first"
)
def test_scenario_f_is_detected() -> None:
    truth = json.loads(GROUND_TRUTH.read_text())["scenarios"]
    db = _demo_session()
    try:
        # F: both institutions with post-cutoff admissions are flagged.
        f_institutions = {case["institution_id"] for case in truth["F_late_admission"]}
        flagged = {
            flag.institution_id
            for flag in db.execute(
                select(Flag).where(Flag.type == "LATE_ADMISSION", Flag.enrolment_id.is_(None))
            ).scalars()
        }
        assert f_institutions <= flagged, f"missed: {sorted(f_institutions - flagged)}"
    finally:
        db.close()
