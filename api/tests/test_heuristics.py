"""Step 10: the heuristic detectors."""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crypto import hmac_hash, mask_apaar, mask_name, vault_encrypt
from app.models.core import Enrolment, Flag, Program, Student, Vault
from app.services.heuristics import (
    SEQUENTIAL_MIN_RUN,
    detect_apaar_problems,
    detect_last_minute_bulk,
    detect_late_admissions,
    detect_phantom_progression,
    detect_sequential_apaar,
    find_runs,
)
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


# ------------------------------------------------------------------ sequential APAAR


def test_find_runs_detects_a_tight_block() -> None:
    pairs = [(100_000_000_000 + i, i) for i in range(12)]
    runs = find_runs(pairs)
    assert len(runs) == 1
    assert runs[0].length == 12


def test_find_runs_ignores_short_blocks() -> None:
    assert find_runs([(100_000_000_000 + i, i) for i in range(SEQUENTIAL_MIN_RUN - 1)]) == []


def test_find_runs_tolerates_small_gaps_but_not_large_ones() -> None:
    tight = [(100_000_000_000 + i * 3, i) for i in range(11)]  # gap 3, within tolerance
    assert find_runs(tight)[0].length == 11
    scattered = [(100_000_000_000 + i * 50, i) for i in range(11)]
    assert find_runs(scattered) == []


def test_find_runs_is_order_independent() -> None:
    pairs = [(100_000_000_000 + i, i) for i in range(11)]
    assert find_runs(list(reversed(pairs)))[0].length == 11


def test_sequential_apaar_is_flagged_with_masked_evidence(db: Session, program) -> None:
    base = 123_456_780_000
    for offset in range(14):
        add(db, program, apaar=f"{base + offset:012d}")
    summary = detect_sequential_apaar(db)
    db.commit()

    assert summary["sequential_apaar"] == 1
    flag = flags(db, "SEQUENTIAL_APAAR")[0]
    assert flag.evidence["run_length"] == 14
    assert flag.evidence["first_masked"].startswith("XXXX-XXXX-")
    assert "issued nationally over time" in flag.explanation
    # No raw APAAR ID anywhere in the flag.
    blob = json.dumps(flag.evidence) + flag.explanation
    assert not re.search(r"\b\d{12}\b", blob)


def test_scattered_apaars_are_not_flagged(db: Session, program) -> None:
    for offset in range(20):
        add(db, program, apaar=f"{123_000_000_000 + offset * 977:012d}")
    detect_sequential_apaar(db)
    db.commit()
    assert flags(db, "SEQUENTIAL_APAAR") == []


def test_a_run_split_across_institutions_is_not_one_run(
    db: Session, two_institutions, program
) -> None:
    _, second = two_institutions
    other = db.execute(select(Program).where(Program.institution_id == second.id)).scalars().first()
    base = 555_000_000_000
    for offset in range(8):
        add(db, program, apaar=f"{base + offset:012d}")
    for offset in range(8, 16):
        add(db, other, apaar=f"{base + offset:012d}")
    detect_sequential_apaar(db)
    db.commit()
    assert flags(db, "SEQUENTIAL_APAAR") == []  # 8 each, below the threshold


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


# ------------------------------------------------------------------ last-minute bulk


def test_a_late_burst_of_records_is_flagged(db: Session, program) -> None:
    calendar = year_calendar(YEAR)
    for _ in range(30):
        add(db, program, created_at=calendar.reporting_deadline - timedelta(days=20))
    for _ in range(70):
        add(db, program, created_at=calendar.reporting_deadline - timedelta(hours=2))

    summary = detect_last_minute_bulk(db, academic_year=YEAR)
    db.commit()
    assert summary["last_minute_bulk"] == 1
    flag = flags(db, "LAST_MINUTE_BULK")[0]
    assert flag.evidence["records_in_window"] == 70
    assert flag.evidence["share_percent"] == 70.0
    assert flag.severity == "high"
    assert "within 6 hours" in flag.explanation


def test_steady_reporting_is_not_flagged(db: Session, program) -> None:
    calendar = year_calendar(YEAR)
    for day in range(40):
        add(db, program, created_at=calendar.reporting_deadline - timedelta(days=day + 1))
    detect_last_minute_bulk(db, academic_year=YEAR)
    db.commit()
    assert flags(db, "LAST_MINUTE_BULK") == []


# ------------------------------------------------------------------ phantom progression


def test_year_two_without_year_one_is_flagged(db: Session, program) -> None:
    add(db, program, year=YEAR, year_of_study=2, admission_type="regular")
    summary = detect_phantom_progression(db)
    db.commit()
    assert summary["phantom_progression"] == 1
    flag = flags(db, "PHANTOM_PROGRESSION")[0]
    assert flag.evidence["kind"] == "year2_without_year1"
    assert "not a lateral entrant" in flag.explanation


def test_lateral_entrants_in_year_two_are_not_phantoms(db: Session, program) -> None:
    add(db, program, year=YEAR, year_of_study=2, admission_type="lateral")
    detect_phantom_progression(db)
    db.commit()
    assert flags(db, "PHANTOM_PROGRESSION") == []


def test_a_properly_progressed_student_is_not_a_phantom(db: Session, program) -> None:
    student = add(db, program, year=PREVIOUS, year_of_study=1)
    db.add(
        Enrolment(
            student_id=student.id,
            program_id=program.id,
            institution_id=program.institution_id,
            academic_year=YEAR,
            year_of_study=2,
            admission_type="regular",
            status="admitted",
        )
    )
    db.commit()
    detect_phantom_progression(db)
    db.commit()
    assert flags(db, "PHANTOM_PROGRESSION") == []


def test_vanishing_without_a_status_is_flagged(db: Session, program) -> None:
    add(db, program, year=PREVIOUS, year_of_study=1, status="admitted")
    summary = detect_phantom_progression(db)
    db.commit()
    assert summary["phantom_progression"] == 1
    flag = flags(db, "PHANTOM_PROGRESSION")[0]
    assert flag.evidence["kind"] == "vanished_without_status"
    assert "must be reported with a status" in flag.explanation


def test_leaving_with_a_proper_status_is_not_flagged(db: Session, program) -> None:
    for status in ("cancelled", "migrated", "dropped", "completed"):
        add(db, program, year=PREVIOUS, year_of_study=1, status=status)
    detect_phantom_progression(db)
    db.commit()
    assert flags(db, "PHANTOM_PROGRESSION") == []


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
    base = 777_000_000_000
    for offset in range(12):
        add(db, program, apaar=f"{base + offset:012d}")
    for _ in range(10):
        add(db, program, admitted_on=calendar.admission_window_end + timedelta(days=9))
    add(db, program, apaar="888888888888", registry_status="not_found")

    first = run_all_detectors(db)
    before = len(list(db.execute(select(Flag)).scalars()))
    second = run_all_detectors(db)
    after = len(list(db.execute(select(Flag)).scalars()))

    assert before == after, "a second run created duplicate flags"
    assert first["sequential_apaar"] == 1
    assert second["sequential_apaar"] == 0
    assert second["sequential_apaar_updated"] == 1
    assert "duration_ms" in second


# ------------------------------------------------------------------ ground truth


@pytest.mark.skipif(
    not (GROUND_TRUTH.exists() and DEMO_DB.exists()), reason="run `make reset` first"
)
def test_scenarios_f_g_h_and_i_are_detected() -> None:
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

        # G: the sequential run is found at the right institution and year.
        g_case = truth["G_sequential_apaar"][0]
        g_flags = list(db.execute(select(Flag).where(Flag.type == "SEQUENTIAL_APAAR")).scalars())
        assert g_flags, "sequential APAAR run not detected"
        assert g_case["institution_id"] in {flag.institution_id for flag in g_flags}
        assert max(flag.evidence["run_length"] for flag in g_flags) >= 10

        # H: the last-minute bulk filer is found.
        h_case = truth["H_last_minute_bulk"][0]
        h_flags = list(db.execute(select(Flag).where(Flag.type == "LAST_MINUTE_BULK")).scalars())
        assert h_case["institution_id"] in {flag.institution_id for flag in h_flags}
        assert h_flags[0].evidence["share_percent"] >= 40

        # I: every injected phantom student is flagged, and only those.
        i_students = {int(case["key"]) for case in truth["I_phantom_progression"]}
        i_flagged = {
            flag.student_id
            for flag in db.execute(select(Flag).where(Flag.type == "PHANTOM_PROGRESSION")).scalars()
        }
        assert i_students <= i_flagged, f"missed: {sorted(i_students - i_flagged)}"
        assert not (i_flagged - i_students), (
            f"{len(i_flagged - i_students)} false phantom-progression flags"
        )
    finally:
        db.close()
