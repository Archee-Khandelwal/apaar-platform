"""Step 8: duplicate and identity detection — and the dual-degree distinction."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crypto import hash_name, hash_phone, hmac_hash, mask_apaar, mask_name, vault_encrypt
from app.models.core import Enrolment, Flag, Institution, Program, Student, Vault
from app.services.duplicates import (
    detect_identity_duplicates,
    run_duplicate_detection,
)
from app.services.flags import CROSS_INSTITUTION_NOTICE, sanitise_for_institution

YEAR = "2026-27"
REPO = Path(__file__).resolve().parents[2]
GROUND_TRUTH = REPO / "datagen" / "ground_truth.json"
DEMO_DB = REPO / "apaar.db"


def _demo_session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(f"sqlite:///{DEMO_DB}")
    return sessionmaker(bind=engine, expire_on_commit=False)()


@pytest.fixture()
def online_program(db: Session, two_institutions) -> Program:
    """Give the second institution an online/ODL programme."""
    _, second = two_institutions
    program = Program(
        institution_id=second.id,
        course="MBA",
        branch="General (Online/ODL)",
        level="PG",
        mode="online",
    )
    db.add(program)
    db.commit()
    return program


def make_student(
    db: Session,
    *,
    apaar: str | None = "123456781234",
    name: str = "Rahul Sharma",
    dob: date = date(2006, 3, 12),
    guardian: str = "9876500000",
) -> Student:
    student = Student(
        apaar_hash=hmac_hash(apaar) if apaar else None,
        apaar_masked=mask_apaar(apaar) if apaar else "XXXX-XXXX-XXXX",
        apaar_status="provided" if apaar else "not_applicable",
        name_masked=mask_name(name),
        name_hash=hash_name(name),
        dob_hash=hmac_hash(dob.isoformat()),
        dob_year=dob.year,
        guardian_phone_hash=hash_phone(guardian),
    )
    db.add(student)
    db.flush()
    db.add(
        Vault(
            student_id=student.id,
            apaar_enc=vault_encrypt(apaar) if apaar else None,
            name_enc=vault_encrypt(name),
            dob_enc=vault_encrypt(dob.isoformat()),
        )
    )
    db.flush()
    return student


def enrol(
    db: Session,
    student: Student,
    program: Program,
    *,
    year: str = YEAR,
    status: str = "admitted",
    year_of_study: int = 1,
    admission_type: str = "regular",
) -> Enrolment:
    enrolment = Enrolment(
        student_id=student.id,
        program_id=program.id,
        institution_id=program.institution_id,
        academic_year=year,
        year_of_study=year_of_study,
        admission_type=admission_type,
        status=status,
        admitted_on=date(2026, 8, 1),
    )
    db.add(enrolment)
    db.commit()
    return enrolment


def programs(db: Session, two_institutions) -> tuple[Program, Program]:
    first, second = two_institutions
    return (
        db.execute(select(Program).where(Program.institution_id == first.id)).scalars().first(),
        db.execute(select(Program).where(Program.institution_id == second.id)).scalars().first(),
    )


def flags_of(db: Session, type_: str) -> list[Flag]:
    return list(db.execute(select(Flag).where(Flag.type == type_)).scalars())


# ------------------------------------------------------------------ cross-institution


def test_two_full_time_regular_enrolments_are_flagged_as_likely_fraud(
    db: Session, two_institutions
) -> None:
    first_program, second_program = programs(db, two_institutions)
    student = make_student(db)
    enrol(db, student, first_program)
    enrol(db, student, second_program)

    summary = run_duplicate_detection(db)
    db.commit()

    assert summary["cross_institution_duplicates"] == 1
    assert summary["possible_dual_degrees"] == 0
    flag = flags_of(db, "CROSS_INSTITUTION_DUPLICATE")[0]
    assert flag.severity == "high"
    assert flag.evidence["is_fraud_indicator"] is True
    assert flag.evidence["classification_reason"] == "both_full_time_regular"
    assert len(flag.evidence["sides"]) == 2
    assert "not a permitted dual degree" in flag.explanation
    # Both institutions are named for the officer.
    assert len(flag.evidence["institutions"]) == 2


def test_one_online_enrolment_makes_it_a_legal_dual_degree(
    db: Session, two_institutions, online_program
) -> None:
    """CLAUDE.md section 6: the same APAAR at two institutions is legal if one is ODL."""
    first_program, _ = programs(db, two_institutions)
    student = make_student(db)
    enrol(db, student, first_program)
    enrol(db, student, online_program)

    summary = run_duplicate_detection(db)
    db.commit()

    assert summary["possible_dual_degrees"] == 1
    assert summary["cross_institution_duplicates"] == 0
    assert flags_of(db, "CROSS_INSTITUTION_DUPLICATE") == []
    flag = flags_of(db, "POSSIBLE_DUAL_DEGREE")[0]
    assert flag.severity == "low"
    assert flag.evidence["is_fraud_indicator"] is False
    assert "permitted" in flag.explanation
    assert "fraud" in flag.explanation  # explicitly says it is NOT fraud


def test_same_institution_twice_is_not_a_cross_institution_duplicate(
    db: Session, two_institutions
) -> None:
    first_program, _ = programs(db, two_institutions)
    second_at_same = Program(
        institution_id=first_program.institution_id,
        course="MBA",
        branch="General",
        level="PG",
        mode="regular",
    )
    db.add(second_at_same)
    db.commit()

    student = make_student(db)
    enrol(db, student, first_program)
    enrol(db, student, second_at_same)

    run_duplicate_detection(db)
    db.commit()
    assert flags_of(db, "CROSS_INSTITUTION_DUPLICATE") == []


def test_different_years_are_not_a_duplicate(db: Session, two_institutions) -> None:
    """A student who migrates between years is not enrolled twice at once."""
    first_program, second_program = programs(db, two_institutions)
    student = make_student(db)
    enrol(db, student, first_program, year="2025-26")
    enrol(db, student, second_program, year=YEAR)

    run_duplicate_detection(db)
    db.commit()
    assert flags_of(db, "CROSS_INSTITUTION_DUPLICATE") == []


def test_a_cancelled_enrolment_is_not_a_duplicate(db: Session, two_institutions) -> None:
    first_program, second_program = programs(db, two_institutions)
    student = make_student(db)
    enrol(db, student, first_program)
    enrol(db, student, second_program, status="cancelled")

    run_duplicate_detection(db)
    db.commit()
    assert flags_of(db, "CROSS_INSTITUTION_DUPLICATE") == []


def test_lateral_entry_at_a_second_institution_is_still_full_time(
    db: Session, two_institutions
) -> None:
    first_program, second_program = programs(db, two_institutions)
    student = make_student(db)
    enrol(db, student, first_program)
    enrol(db, student, second_program, admission_type="lateral", year_of_study=2)

    run_duplicate_detection(db)
    db.commit()
    assert len(flags_of(db, "CROSS_INSTITUTION_DUPLICATE")) == 1


def test_a_student_without_an_apaar_id_is_not_matched_by_apaar(
    db: Session, two_institutions
) -> None:
    first_program, second_program = programs(db, two_institutions)
    student = make_student(db, apaar=None)
    enrol(db, student, first_program)
    enrol(db, student, second_program)

    run_duplicate_detection(db)
    db.commit()
    assert flags_of(db, "CROSS_INSTITUTION_DUPLICATE") == []


def test_rerunning_does_not_duplicate_flags_and_closes_fixed_ones(
    db: Session, two_institutions
) -> None:
    first_program, second_program = programs(db, two_institutions)
    student = make_student(db)
    enrol(db, student, first_program)
    second = enrol(db, student, second_program)

    run_duplicate_detection(db)
    db.commit()
    run_duplicate_detection(db)
    db.commit()
    assert len(flags_of(db, "CROSS_INSTITUTION_DUPLICATE")) == 1

    second.status = "cancelled"
    db.commit()
    run_duplicate_detection(db)
    db.commit()
    assert flags_of(db, "CROSS_INSTITUTION_DUPLICATE")[0].status == "resolved"


# ------------------------------------------------------------------ rule 10


def test_the_institution_view_never_names_the_other_college(
    db: Session, two_institutions
) -> None:
    """CLAUDE.md section 5 rule 10."""
    first_program, second_program = programs(db, two_institutions)
    student = make_student(db)
    enrol(db, student, first_program)
    enrol(db, student, second_program)
    run_duplicate_detection(db)
    db.commit()

    flag = flags_of(db, "CROSS_INSTITUTION_DUPLICATE")[0]
    other_name = db.get(Institution, second_program.institution_id).name
    assert other_name in json.dumps(flag.evidence)  # the officer sees it

    sanitised = sanitise_for_institution(flag)
    blob = json.dumps(sanitised, default=str)
    assert other_name not in blob
    assert db.get(Institution, first_program.institution_id).name not in blob
    assert sanitised["explanation"] == CROSS_INSTITUTION_NOTICE
    assert sanitised["title"] == "Possible duplicate enrolment"
    assert "sides" not in sanitised["evidence"]
    assert "institutions" not in sanitised["evidence"]
    assert sanitised["evidence"]["apaar_masked"] == student.apaar_masked


def test_sanitised_dual_degree_flag_also_hides_the_other_college(
    db: Session, two_institutions, online_program
) -> None:
    first_program, _ = programs(db, two_institutions)
    student = make_student(db)
    enrol(db, student, first_program)
    enrol(db, student, online_program)
    run_duplicate_detection(db)
    db.commit()

    flag = flags_of(db, "POSSIBLE_DUAL_DEGREE")[0]
    sanitised = sanitise_for_institution(flag)
    assert db.get(Institution, online_program.institution_id).name not in json.dumps(
        sanitised, default=str
    )


# ------------------------------------------------------------------ identity duplicates


def test_one_person_with_two_apaar_ids_is_flagged(db: Session, two_institutions) -> None:
    first_program, second_program = programs(db, two_institutions)
    shared = {"name": "Imran Qureshi", "dob": date(2005, 4, 2), "guardian": "9811122233"}
    first = make_student(db, apaar="111122223333", **shared)
    second = make_student(db, apaar="444455556666", **shared)
    enrol(db, first, first_program)
    enrol(db, second, second_program)

    summary = detect_identity_duplicates(db)
    db.commit()

    assert summary["identity_duplicates"] == 2  # one flag per record
    flags = flags_of(db, "IDENTITY_DUPLICATE")
    assert {flag.student_id for flag in flags} == {first.id, second.id}
    flag = flags[0]
    assert flag.evidence["matched_on"] == ["name", "date_of_birth", "guardian_phone"]
    assert flag.evidence["student_ids"] == sorted([first.id, second.id])
    assert "one per student for life" in flag.explanation


def test_the_real_name_never_appears_in_an_identity_flag(db: Session, two_institutions) -> None:
    """The name is decrypted inside the service for matching only."""
    first_program, second_program = programs(db, two_institutions)
    shared = {"name": "Priyanka Venkataraman", "dob": date(2005, 1, 9), "guardian": "9800011122"}
    first = make_student(db, apaar="222233334444", **shared)
    second = make_student(db, apaar="555566667777", **shared)
    enrol(db, first, first_program)
    enrol(db, second, second_program)
    detect_identity_duplicates(db)
    db.commit()

    for flag in flags_of(db, "IDENTITY_DUPLICATE"):
        blob = json.dumps(flag.evidence) + flag.explanation + flag.title
        assert "Priyanka" not in blob
        assert "Venkataraman" not in blob
        assert "9800011122" not in blob


def test_same_person_details_but_one_apaar_is_not_an_identity_duplicate(
    db: Session, two_institutions
) -> None:
    """Twins reported once each, or one student reported twice, must not collide here."""
    first_program, second_program = programs(db, two_institutions)
    shared = {"name": "Sneha Iyer", "dob": date(2006, 6, 6), "guardian": "9700011122"}
    student = make_student(db, apaar="999988887777", **shared)
    enrol(db, student, first_program)

    detect_identity_duplicates(db)
    db.commit()
    assert flags_of(db, "IDENTITY_DUPLICATE") == []


def test_siblings_with_different_dobs_are_not_identity_duplicates(
    db: Session, two_institutions
) -> None:
    first_program, second_program = programs(db, two_institutions)
    first = make_student(db, apaar="121212121212", name="Arjun Nair", dob=date(2005, 2, 2), guardian="9666611122")
    second = make_student(db, apaar="131313131313", name="Arjun Nair", dob=date(2007, 9, 9), guardian="9666611122")
    enrol(db, first, first_program)
    enrol(db, second, second_program)

    detect_identity_duplicates(db)
    db.commit()
    assert flags_of(db, "IDENTITY_DUPLICATE") == []


def test_same_name_and_dob_but_different_guardian_is_not_flagged(
    db: Session, two_institutions
) -> None:
    first_program, second_program = programs(db, two_institutions)
    first = make_student(db, apaar="141414141414", name="Rohit Verma", dob=date(2006, 5, 5), guardian="9611111111")
    second = make_student(db, apaar="151515151515", name="Rohit Verma", dob=date(2006, 5, 5), guardian="9622222222")
    enrol(db, first, first_program)
    enrol(db, second, second_program)

    detect_identity_duplicates(db)
    db.commit()
    assert flags_of(db, "IDENTITY_DUPLICATE") == []


def test_name_matching_ignores_case_and_spacing(db: Session, two_institutions) -> None:
    first_program, second_program = programs(db, two_institutions)
    first = make_student(db, apaar="161616161616", name="Neha  Gupta", dob=date(2006, 7, 7), guardian="9633333333")
    second = make_student(db, apaar="171717171717", name="neha gupta", dob=date(2006, 7, 7), guardian="9633333333")
    enrol(db, first, first_program)
    enrol(db, second, second_program)

    detect_identity_duplicates(db)
    db.commit()
    assert len(flags_of(db, "IDENTITY_DUPLICATE")) == 2


# ------------------------------------------------------------------ ground truth


@pytest.mark.skipif(
    not (GROUND_TRUTH.exists() and DEMO_DB.exists()), reason="run `make reset` first"
)
def test_scenarios_c_d_and_j_are_classified_correctly() -> None:
    truth = json.loads(GROUND_TRUTH.read_text())["scenarios"]
    db = _demo_session()
    try:
        by_type: dict[str, set[int]] = {}
        for type_ in ("CROSS_INSTITUTION_DUPLICATE", "POSSIBLE_DUAL_DEGREE", "IDENTITY_DUPLICATE"):
            by_type[type_] = {
                flag.student_id
                for flag in db.execute(select(Flag).where(Flag.type == type_)).scalars()
                if flag.student_id is not None
            }

        # C: every injected fraud case is flagged as fraud.
        c_students = {int(case["key"]) for case in truth["C_cross_institution_duplicate"]}
        assert c_students <= by_type["CROSS_INSTITUTION_DUPLICATE"], (
            f"missed: {sorted(c_students - by_type['CROSS_INSTITUTION_DUPLICATE'])}"
        )

        # D: legal dual degrees are recorded as dual degrees and NEVER as fraud.
        d_students = {int(case["key"]) for case in truth["D_dual_degree"]}
        assert d_students <= by_type["POSSIBLE_DUAL_DEGREE"], (
            f"missed: {sorted(d_students - by_type['POSSIBLE_DUAL_DEGREE'])}"
        )
        false_fraud = d_students & by_type["CROSS_INSTITUTION_DUPLICATE"]
        assert not false_fraud, f"dual-degree students wrongly flagged as fraud: {sorted(false_fraud)}"

        # J: both records of each person are flagged.
        j_students = {int(case["key"]) for case in truth["J_identity_duplicate"]}
        assert j_students <= by_type["IDENTITY_DUPLICATE"], (
            f"missed: {sorted(j_students - by_type['IDENTITY_DUPLICATE'])}"
        )
    finally:
        db.close()
