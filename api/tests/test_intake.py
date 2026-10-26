"""Step 7: the intake compliance engine, with hand-calculated cases."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.core import ApprovedIntake, Enrolment, Flag, Program, Student
from app.services.intake import compute_seat_matrix, run_intake_compliance
from app.services.rules import supernumerary_caps

YEAR = "2026-27"
REPO = Path(__file__).resolve().parents[2]
GROUND_TRUTH = REPO / "datagen" / "ground_truth.json"
DEMO_DB = REPO / "apaar.db"


def _demo_session():
    """A session on the seeded demo database, not the hermetic test one."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(f"sqlite:///{DEMO_DB}")
    return sessionmaker(bind=engine, expire_on_commit=False)()


@pytest.fixture()
def program(db: Session, two_institutions) -> Program:
    """A 300-seat B.Tech CSE programme: caps are TFW 15, lateral 30, FN 45, PMSSS 15."""
    first, _ = two_institutions
    program = db.execute(select(Program).where(Program.institution_id == first.id)).scalars().first()
    db.add(
        ApprovedIntake(
            program_id=program.id,
            academic_year=YEAR,
            intake=300,
            supernumerary_caps=supernumerary_caps(300),
        )
    )
    db.commit()
    return program


def admit(
    db: Session,
    program: Program,
    count: int,
    *,
    admission_type: str = "regular",
    year_of_study: int = 1,
    status: str = "admitted",
) -> None:
    for _ in range(count):
        student = Student(apaar_masked="XXXX-XXXX-0000", name_masked="S**** T.")
        db.add(student)
        db.flush()
        db.add(
            Enrolment(
                student_id=student.id,
                program_id=program.id,
                institution_id=program.institution_id,
                academic_year=YEAR,
                year_of_study=year_of_study,
                admission_type=admission_type,
                status=status,
                admitted_on=date(2026, 8, 1),
            )
        )
    db.commit()


def matrix(db: Session, program: Program):
    return compute_seat_matrix(db, program=program, academic_year=YEAR)


def bucket(result, admission_type: str):
    return next(item for item in result.buckets if item.admission_type == admission_type)


# ------------------------------------------------------------------ hand-calculated cases


def test_caps_come_from_the_rule_file(program, db: Session) -> None:
    caps = supernumerary_caps(300)
    assert caps == {"tfw": 15, "lateral": 30, "fn_pio_oci": 45, "pmsss": 15, "other_supernumerary": 6}


def test_exactly_at_intake_is_not_excess(db: Session, program) -> None:
    admit(db, program, 300)
    result = matrix(db, program)
    assert result.regular_admitted == 300
    assert result.regular_excess == 0
    assert result.excess == 0
    assert result.vacant_regular_seats == 0
    assert "300 regular admissions vs 300 approved intake" in result.explanation()


def test_under_intake_is_not_excess(db: Session, program) -> None:
    admit(db, program, 280)
    result = matrix(db, program)
    assert result.excess == 0
    assert result.vacant_regular_seats == 20
    assert "20 seats vacant" in result.explanation()


def test_over_by_regular_admissions(db: Session, program) -> None:
    admit(db, program, 303)
    result = matrix(db, program)
    assert result.regular_excess == 3
    assert result.excess == 3


def test_supernumerary_within_caps_is_not_excess(db: Session, program) -> None:
    """312 admitted on a 300-seat programme can be fully legal."""
    admit(db, program, 300)
    admit(db, program, 6, admission_type="tfw")
    admit(db, program, 4, admission_type="fn_pio_oci")
    admit(db, program, 2, admission_type="pmsss")
    result = matrix(db, program)
    assert result.total_admitted == 312
    assert result.valid_supernumerary == 12
    assert result.excess == 0
    assert bucket(result, "tfw").excess == 0


def test_over_only_because_a_supernumerary_bucket_exceeds_its_cap(db: Session, program) -> None:
    admit(db, program, 290)  # under intake
    admit(db, program, 19, admission_type="tfw")  # cap is 15
    result = matrix(db, program)
    assert result.regular_excess == 0
    assert bucket(result, "tfw").admitted == 19
    assert bucket(result, "tfw").cap == 15
    assert bucket(result, "tfw").valid == 15
    assert bucket(result, "tfw").excess == 4
    assert result.excess == 4
    assert "Tuition Fee Waiver 19/15" in result.explanation()


def test_excess_sums_regular_and_supernumerary_breaches(db: Session, program) -> None:
    admit(db, program, 305)  # 5 over
    admit(db, program, 18, admission_type="tfw")  # 3 over its cap of 15
    result = matrix(db, program)
    assert result.regular_excess == 5
    assert result.supernumerary_excess == 3
    assert result.excess == 8


def test_lateral_entry_is_not_counted_against_year_one_intake(db: Session, program) -> None:
    """CLAUDE.md section 6: lateral entrants join in year 2."""
    admit(db, program, 300)
    admit(db, program, 25, admission_type="lateral", year_of_study=2)
    result = matrix(db, program)
    assert result.regular_admitted == 300  # lateral entrants are not in this number
    assert result.regular_excess == 0
    assert result.excess == 0
    assert bucket(result, "lateral").admitted == 25


def test_lateral_cap_absorbs_seats_left_vacant_in_year_one(db: Session, program) -> None:
    """Cap is 10% of intake (30) plus year-1 vacancies, per the rule file."""
    admit(db, program, 280)  # 20 seats vacant in year 1
    admit(db, program, 45, admission_type="lateral", year_of_study=2)
    result = matrix(db, program)
    lateral = bucket(result, "lateral")
    assert lateral.cap == 30 + 20
    assert lateral.excess == 0
    assert "vacant in year 1" in lateral.cap_basis

    admit(db, program, 10, admission_type="lateral", year_of_study=2)  # now 55 > 50
    assert bucket(matrix(db, program), "lateral").excess == 5


def test_year_two_regular_students_do_not_consume_year_one_intake(db: Session, program) -> None:
    admit(db, program, 290, year_of_study=1)
    admit(db, program, 280, year_of_study=2)  # last year's cohort, now in year 2
    result = matrix(db, program)
    assert result.regular_admitted == 290
    assert result.excess == 0


def test_cancelled_and_dropped_students_free_their_seats(db: Session, program) -> None:
    admit(db, program, 300)
    admit(db, program, 10, status="cancelled")
    admit(db, program, 5, status="dropped")
    admit(db, program, 3, status="migrated")
    result = matrix(db, program)
    assert result.regular_admitted == 300  # only active statuses count
    assert result.excess == 0


def test_completed_students_still_count_as_occupying_a_seat(db: Session, program) -> None:
    admit(db, program, 301, status="completed")
    assert matrix(db, program).regular_excess == 1


def test_explanation_reads_like_the_arithmetic(db: Session, program) -> None:
    admit(db, program, 303)
    admit(db, program, 6, admission_type="tfw")
    admit(db, program, 33, admission_type="lateral", year_of_study=2)
    explanation = matrix(db, program).explanation()
    assert explanation.startswith("303 regular admissions vs 300 approved intake")
    assert "3 excess regular" in explanation
    assert "Tuition Fee Waiver 6/15 ok" in explanation
    assert "total excess =" in explanation


# ------------------------------------------------------------------ flags


def test_flag_is_raised_with_the_seat_matrix_as_evidence(db: Session, program) -> None:
    admit(db, program, 312)
    summary = run_intake_compliance(db, institution_id=program.institution_id)
    db.commit()
    assert summary["excess_flags_created"] == 1

    flag = db.execute(select(Flag).where(Flag.type == "EXCESS_INTAKE")).scalars().one()
    assert flag.severity in ("low", "medium", "high", "critical")
    assert flag.program_id == program.id
    assert flag.academic_year == YEAR
    assert "12 excess regular" in flag.explanation
    assert "Cause:" in flag.explanation
    assert flag.evidence["approved_intake"] == 300
    assert flag.evidence["excess"] == 12
    assert flag.evidence["rule_set"] == "APH_2026_27_v1"
    assert flag.evidence["causes"]


def test_no_flag_when_compliant(db: Session, program) -> None:
    admit(db, program, 300)
    admit(db, program, 15, admission_type="tfw")
    run_intake_compliance(db, institution_id=program.institution_id)
    db.commit()
    assert db.execute(select(Flag).where(Flag.type == "EXCESS_INTAKE")).scalars().first() is None


def test_rerunning_updates_the_flag_instead_of_duplicating_it(db: Session, program) -> None:
    admit(db, program, 303)
    run_intake_compliance(db, institution_id=program.institution_id)
    db.commit()
    first = db.execute(select(Flag).where(Flag.type == "EXCESS_INTAKE")).scalars().one()

    admit(db, program, 10)  # now 13 over
    summary = run_intake_compliance(db, institution_id=program.institution_id)
    db.commit()

    flags = list(db.execute(select(Flag).where(Flag.type == "EXCESS_INTAKE")).scalars())
    assert len(flags) == 1
    assert flags[0].id == first.id
    assert summary["excess_flags_updated"] == 1
    assert flags[0].evidence["excess"] == 13


def test_flag_closes_itself_when_the_college_fixes_the_data(db: Session, program) -> None:
    admit(db, program, 305)
    run_intake_compliance(db, institution_id=program.institution_id)
    db.commit()

    # The college cancels the excess admissions.
    extra = list(
        db.execute(
            select(Enrolment).where(Enrolment.program_id == program.id).limit(5)
        ).scalars()
    )
    for enrolment in extra:
        enrolment.status = "cancelled"
    db.commit()

    summary = run_intake_compliance(db, institution_id=program.institution_id)
    db.commit()
    assert summary["excess_flags_closed"] == 1
    flag = db.execute(select(Flag).where(Flag.type == "EXCESS_INTAKE")).scalars().one()
    assert flag.status == "resolved"
    assert "no longer present" in flag.notes[-1]["note"]


def test_severity_scales_with_the_size_of_the_breach(db: Session, program, two_institutions) -> None:
    admit(db, program, 303)  # 1% of 300 -> low
    run_intake_compliance(db, institution_id=program.institution_id)
    db.commit()
    assert db.execute(select(Flag)).scalars().one().severity == "low"

    admit(db, program, 60)  # 21% over -> critical
    run_intake_compliance(db, institution_id=program.institution_id)
    db.commit()
    assert db.execute(select(Flag)).scalars().one().severity == "critical"


# ------------------------------------------------------------------ routes


def test_institution_sees_only_its_own_seat_matrix(
    client: TestClient, auth, db: Session, program
) -> None:
    admit(db, program, 305)
    run_intake_compliance(db, institution_id=program.institution_id)
    db.commit()

    body = client.get(f"/institution/seat-matrix?academic_year={YEAR}", headers=auth("institution")).json()
    assert body["rule_set"] == "APH_2026_27_v1"
    assert body["totals"]["excess"] == 5
    assert body["programs"][0]["explanation"]
    assert body["programs"][0]["flag_id"] is not None

    # The other institution has no intake rows, so no programmes with a matrix.
    other = client.get(
        f"/institution/seat-matrix?academic_year={YEAR}", headers=auth("institution_other")
    ).json()
    assert other["totals"]["excess"] == 0


def test_aicte_can_read_any_institutions_seat_matrix(
    client: TestClient, auth, db: Session, program
) -> None:
    admit(db, program, 302)
    db.commit()
    url = f"/aicte/institutions/{program.institution_id}/seat-matrix?academic_year={YEAR}"
    for role in ("aicte_viewer", "aicte_officer"):
        response = client.get(url, headers=auth(role))
        assert response.status_code == 200
        assert response.json()["totals"]["excess"] == 2


def test_seat_matrix_routes_enforce_roles(client: TestClient, auth, program) -> None:
    url = f"/aicte/institutions/{program.institution_id}/seat-matrix?academic_year={YEAR}"
    for role in ("institution", "student", "verifier", "admin"):
        assert client.get(url, headers=auth(role)).status_code == 403
    for role in ("aicte_officer", "student", "verifier"):
        assert (
            client.get(f"/institution/seat-matrix?academic_year={YEAR}", headers=auth(role)).status_code
            == 403
        )


# ------------------------------------------------------------------ ground truth


@pytest.mark.skipif(
    not (GROUND_TRUTH.exists() and DEMO_DB.exists()), reason="run `make reset` first"
)
def test_scenario_a_is_detected_exactly_in_the_seeded_database() -> None:
    """Every injected EXCESS_INTAKE case is found, with the excess we injected."""
    cases = json.loads(GROUND_TRUTH.read_text())["scenarios"]["A_excess_intake"]
    db = _demo_session()
    try:
        flags = {
            f"{flag.program_id}|{flag.academic_year}": flag
            for flag in db.execute(select(Flag).where(Flag.type == "EXCESS_INTAKE")).scalars()
        }
        missed = [case["key"] for case in cases if case["key"] not in flags]
        assert not missed, f"scenario A cases not flagged: {missed}"
        # And no EXCESS_INTAKE flags beyond the injected ones: the base data respects
        # every supernumerary cap, so there are no false positives.
        extra = sorted(set(flags) - {case["key"] for case in cases})
        assert not extra, f"unexpected EXCESS_INTAKE flags: {extra}"

        for case in cases:
            flag = flags[case["key"]]
            expected = case["details"]["expected_excess"]
            assert flag.evidence["excess"] == expected, (
                f"{case['institution_name']}: expected {expected} excess, "
                f"got {flag.evidence['excess']}"
            )
            assert flag.explanation
    finally:
        db.close()
