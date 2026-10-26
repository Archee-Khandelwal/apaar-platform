"""Step 5: the generator is deterministic, labelled, and never stores raw identifiers."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.crypto import hash_phone, hmac_hash, vault_decrypt
from app.core.db import Base
from app.models.core import Enrolment, Institution, Program, Student, Upload, User, Vault
from datagen.generator import generate

SMALL = {"institutions": 8, "students": 900, "seed": 7}


def _fresh_session() -> Session:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()


@pytest.fixture(scope="module")
def seeded(tmp_path_factory: pytest.TempPathFactory) -> tuple[Session, dict[str, Any]]:
    """One small generated dataset shared by this module's tests."""
    path = tmp_path_factory.mktemp("gt") / "ground_truth.json"
    db = _fresh_session()
    ground_truth = generate(db, ground_truth_path=path, **SMALL)
    return db, ground_truth


# ------------------------------------------------------------------ shape


def test_counts_are_consistent_with_the_ground_truth_file(seeded) -> None:
    db, ground_truth = seeded
    assert db.scalar(select(func.count()).select_from(Institution)) == 8
    students = db.scalar(select(func.count()).select_from(Student))
    # The injected scenarios have fixed sizes (a 30-student ghost cluster, 15 duplicate
    # students, 40 late admissions, ...), so on a deliberately small run they dominate
    # the --students target. The default 40-institution seed lands near 15,000.
    assert students >= 600
    assert ground_truth["counts"]["students"] == students
    assert ground_truth["counts"]["enrolments"] == db.scalar(
        select(func.count()).select_from(Enrolment)
    )


def test_the_student_target_scales_the_base_cohorts(tmp_path: Path) -> None:
    small = generate(
        _fresh_session(), ground_truth_path=tmp_path / "small.json", **dict(SMALL, students=900)
    )
    large = generate(
        _fresh_session(), ground_truth_path=tmp_path / "large.json", **dict(SMALL, students=4000)
    )
    assert large["counts"]["students"] > small["counts"]["students"]


def test_every_institution_has_three_to_six_programs(seeded) -> None:
    db, _ = seeded
    rows = db.execute(
        select(Program.institution_id, func.count()).group_by(Program.institution_id)
    ).all()
    assert len(rows) == 8
    assert all(3 <= count <= 6 for _, count in rows)


def test_institution_names_are_clearly_invented(seeded) -> None:
    """CLAUDE.md section 5 rule 13: never a real college name."""
    db, _ = seeded
    names = [row.name for row in db.execute(select(Institution)).scalars()]
    forbidden = ("IIT", "NIT", "VIT", "Manipal", "BITS", "Anna University", "Jadavpur")
    for name in names:
        assert not any(token.lower() in name.lower() for token in forbidden), name


def test_both_academic_years_and_progression_exist(seeded) -> None:
    db, ground_truth = seeded
    years = {row for row in db.execute(select(Enrolment.academic_year).distinct()).scalars()}
    assert years == set(ground_truth["years"])
    # At least some students appear in both years (year 1 -> year 2 progression).
    repeated = db.execute(
        select(Enrolment.student_id)
        .group_by(Enrolment.student_id)
        .having(func.count(func.distinct(Enrolment.academic_year)) > 1)
        .limit(5)
    ).scalars()
    assert list(repeated)


def test_lateral_entrants_only_appear_in_year_two(seeded) -> None:
    db, _ = seeded
    years = db.execute(
        select(Enrolment.year_of_study)
        .where(Enrolment.admission_type == "lateral")
        .distinct()
    ).scalars()
    assert set(years) <= {2}


def test_status_lifecycle_values_are_valid(seeded) -> None:
    db, _ = seeded
    statuses = set(db.execute(select(Enrolment.status).distinct()).scalars())
    assert statuses <= {"admitted", "cancelled", "migrated", "dropped", "completed"}


# ------------------------------------------------------------------ privacy


PHONE_RE = re.compile(r"\b[6-9]\d{9}\b")


def test_no_raw_contact_details_are_stored(seeded) -> None:
    """CLAUDE.md section 5 rule 1: contacts exist only as HMAC hashes."""
    db, _ = seeded
    for student in db.execute(select(Student).limit(300)).scalars():
        blob = " ".join(
            str(value)
            for key, value in vars(student).items()
            if not key.startswith("_") and value is not None
        )
        assert not PHONE_RE.search(blob), f"raw phone number in students row {student.id}"
        assert "@" not in blob, f"raw email in students row {student.id}"


def test_hashes_are_keyed_hex_digests(seeded) -> None:
    db, _ = seeded
    student = db.execute(
        select(Student).where(Student.guardian_phone_hash.is_not(None)).limit(1)
    ).scalar_one()
    assert re.fullmatch(r"[0-9a-f]{64}", student.guardian_phone_hash)
    assert re.fullmatch(r"[0-9a-f]{64}", student.phone_hash)


def test_apaar_is_masked_in_the_main_table_and_raw_only_in_the_vault(seeded) -> None:
    """CLAUDE.md section 5 rule 2."""
    db, _ = seeded
    student = db.execute(
        select(Student).where(Student.apaar_status == "provided").limit(1)
    ).scalar_one()
    assert student.apaar_masked.startswith("XXXX-XXXX-")
    vault = db.execute(select(Vault).where(Vault.student_id == student.id)).scalar_one()

    raw_apaar = vault_decrypt(vault.apaar_enc)
    assert raw_apaar is not None and raw_apaar.isdigit()
    # The main table's hash is the keyed HMAC of the vaulted value.
    assert student.apaar_hash == hmac_hash(raw_apaar)
    assert student.apaar_masked.endswith(raw_apaar[-4:])
    # The vault holds a real name and DOB; the main table holds only a mask.
    assert vault_decrypt(vault.name_enc)
    assert vault_decrypt(vault.dob_enc)
    assert "*" in student.name_masked


def test_ghost_clusters_share_a_handful_of_guardian_contacts(seeded) -> None:
    db, ground_truth = seeded
    cases = ground_truth["scenarios"].get("B_ghost_cluster", [])
    if not cases:
        pytest.skip("no ghost cluster injected in this small run")

    for case in cases:
        member_ids = case["details"]["student_ids"]
        hashes = {db.get(Student, student_id).guardian_phone_hash for student_id in member_ids}
        assert len(hashes) == case["details"]["guardian_contacts"]
        assert len(member_ids) == case["details"]["students"]

    bands = {case["details"]["band"] for case in cases}
    assert "large" in bands
    assert "medium" in bands, "a subtler 8-10 student cluster must be injected too"

    large = [case for case in cases if case["details"]["band"] == "large"]
    medium = [case for case in cases if case["details"]["band"] == "medium"]
    assert all(25 <= case["details"]["students"] <= 35 for case in large)
    assert all(8 <= case["details"]["students"] <= 10 for case in medium)
    # The medium cluster's students-per-contact ratio is deliberately family-sized, so
    # a ratio-only detector would miss it: size has to count too.
    assert all(case["details"]["students_per_contact"] < 4 for case in medium)
    # Clusters are at different institutions.
    assert len({case["institution_id"] for case in cases}) == len(cases)


def test_family_controls_are_smaller_than_the_cluster_threshold(seeded) -> None:
    """4-6 students on one contact must stay below the ghost-cluster size threshold."""
    _, ground_truth = seeded
    controls = ground_truth["scenarios"].get("B_sibling_control", [])
    assert controls
    for case in controls:
        assert case["flag_type"] == "NONE"
        assert case["details"].get("students", 2) <= 6


# ------------------------------------------------------------------ domain rules


def test_apaar_not_applicable_only_for_foreign_nationals_and_oci(seeded) -> None:
    """CLAUDE.md section 6: not_applicable is valid ONLY for FN/OCI, and is not an error."""
    db, _ = seeded
    rows = db.execute(
        select(Student).where(Student.apaar_status == "not_applicable")
    ).scalars()
    rows = list(rows)
    assert rows, "expected some FN/OCI students without an APAAR ID"
    for student in rows:
        assert student.nationality_status in ("fn", "oci")
        assert student.apaar_hash is None


def test_some_students_are_minors(seeded) -> None:
    db, _ = seeded
    assert db.scalar(
        select(func.count()).select_from(Student).where(Student.is_minor.is_(True))
    ) > 0


def test_registry_problems_are_about_one_percent(seeded) -> None:
    db, _ = seeded
    provided = db.scalar(
        select(func.count()).select_from(Student).where(Student.apaar_status == "provided")
    )
    problems = db.scalar(
        select(func.count())
        .select_from(Student)
        .where(Student.registry_status.in_(("invalid_format", "not_found", "mismatch")))
    )
    assert problems > 0
    assert problems / provided < 0.08  # small runs use a floor of 30 cases


# ------------------------------------------------------------------ ground truth


def test_ground_truth_labels_every_scenario(seeded) -> None:
    _, ground_truth = seeded
    scenarios = ground_truth["scenarios"]
    for name in (
        "A_excess_intake",
        "B_ghost_cluster",
        "C_cross_institution_duplicate",
        "D_dual_degree",
        "E_apaar_problems",
        "F_late_admission",
        "G_sequential_apaar",
        "H_last_minute_bulk",
        "I_phantom_progression",
        "J_identity_duplicate",
    ):
        assert scenarios.get(name), f"scenario {name} produced no labelled cases"


def test_ground_truth_cases_carry_a_match_key(seeded) -> None:
    _, ground_truth = seeded
    for cases in ground_truth["scenarios"].values():
        for case in cases:
            assert case["key_kind"] in ("student", "enrolment", "program_year", "institution_year")
            assert case["key"]
            assert case["flag_type"]


def test_dual_degree_cases_are_not_labelled_as_fraud(seeded) -> None:
    _, ground_truth = seeded
    for case in ground_truth["scenarios"]["D_dual_degree"]:
        assert case["flag_type"] == "POSSIBLE_DUAL_DEGREE"
        assert case["details"]["must_not_be_fraud"] is True


def test_clean_institution_has_no_labelled_cases(seeded) -> None:
    _, ground_truth = seeded
    clean_id = ground_truth["clean_institution"]["id"]
    offending = [
        case
        for cases in ground_truth["scenarios"].values()
        for case in cases
        if case["institution_id"] == clean_id and case["flag_type"] != "NONE"
    ]
    assert offending == []


def test_eight_demo_students_cover_the_required_cases(seeded) -> None:
    _, ground_truth = seeded
    usernames = {entry["username"] for entry in ground_truth["demo_students"]}
    assert {
        "student_ghost",
        "student_duplicate",
        "student_dual",
        "student_minor",
        "student_fn",
        "student_clean",
        "student_pending",
        "student_revoked",
    } <= usernames


def test_demo_users_exist_for_every_role(seeded) -> None:
    db, _ = seeded
    roles = set(db.execute(select(User.role).distinct()).scalars())
    assert {"institution", "aicte_viewer", "aicte_officer", "student", "verifier", "admin"} <= roles
    # One institution account per institution.
    assert db.scalar(
        select(func.count()).select_from(User).where(User.role == "institution")
    ) == 8


# ------------------------------------------------------------------ determinism


def test_the_same_seed_produces_the_same_dataset(tmp_path: Path) -> None:
    first_db = _fresh_session()
    second_db = _fresh_session()
    first = generate(first_db, ground_truth_path=tmp_path / "a.json", **SMALL)
    second = generate(second_db, ground_truth_path=tmp_path / "b.json", **SMALL)

    assert first["counts"] == second["counts"]
    masked_first = sorted(first_db.execute(select(Student.apaar_masked)).scalars())
    masked_second = sorted(second_db.execute(select(Student.apaar_masked)).scalars())
    assert masked_first == masked_second
    assert [case["key"] for cases in first["scenarios"].values() for case in cases] == [
        case["key"] for cases in second["scenarios"].values() for case in cases
    ]


def test_a_different_seed_produces_a_different_dataset(tmp_path: Path) -> None:
    other = dict(SMALL, seed=SMALL["seed"] + 1)
    first_db = _fresh_session()
    second_db = _fresh_session()
    generate(first_db, ground_truth_path=tmp_path / "c.json", **SMALL)
    generate(second_db, ground_truth_path=tmp_path / "d.json", **other)
    masked_first = sorted(first_db.execute(select(Student.apaar_masked)).scalars())
    masked_second = sorted(second_db.execute(select(Student.apaar_masked)).scalars())
    assert masked_first != masked_second


def test_reseeding_the_same_database_does_not_accumulate_rows(tmp_path: Path) -> None:
    db = _fresh_session()
    first = generate(db, ground_truth_path=tmp_path / "e.json", **SMALL)
    second = generate(db, ground_truth_path=tmp_path / "f.json", **SMALL)
    assert first["counts"] == second["counts"]
    assert db.scalar(select(func.count()).select_from(Student)) == second["counts"]["students"]


# ------------------------------------------------------------------ registry + samples


def test_issued_apaars_land_in_the_registry_database(seeded) -> None:
    db, _ = seeded
    from registry.app.db import IssuedApaar, SessionLocal as RegistrySession

    registry_db = RegistrySession()
    try:
        issued = registry_db.scalar(select(func.count()).select_from(IssuedApaar))
        assert issued > 0
        # A 'match' student's APAAR must be present with the same name as the college sent.
        student = db.execute(
            select(Student).where(Student.registry_status == "match").limit(1)
        ).scalar_one()
        vault = db.execute(select(Vault).where(Vault.student_id == student.id)).scalar_one()
        raw = vault_decrypt(vault.apaar_enc)
        row = registry_db.get(IssuedApaar, raw)
        assert row is not None
        assert row.name == vault_decrypt(vault.name_enc)
    finally:
        registry_db.close()


def test_not_found_students_are_absent_from_the_registry(seeded) -> None:
    db, _ = seeded
    from registry.app.db import IssuedApaar, SessionLocal as RegistrySession

    student = db.execute(
        select(Student).where(Student.registry_status == "not_found").limit(1)
    ).scalar_one_or_none()
    if student is None:
        pytest.skip("no not_found case in this run")
    vault = db.execute(select(Vault).where(Vault.student_id == student.id)).scalar_one()
    registry_db = RegistrySession()
    try:
        assert registry_db.get(IssuedApaar, vault_decrypt(vault.apaar_enc)) is None
    finally:
        registry_db.close()


def test_sample_files_exist_and_are_messy() -> None:
    """Reads the committed sample files; it must not regenerate them.

    write_samples() targets whichever programme is under-filled in the live database,
    so calling it here would rewrite the repo's samples against a test database.
    """
    import pandas as pd

    from datagen.samples import SAMPLES_DIR

    assert (SAMPLES_DIR / "sample_1_excess_intake.xlsx").exists()
    assert (SAMPLES_DIR / "sample_2_dirty_errors.xlsx").exists()
    assert (SAMPLES_DIR / "sample_3_garbage.csv").exists()

    frame = pd.read_excel(SAMPLES_DIR / "sample_2_dirty_errors.xlsx")
    # Headers deliberately do not match our canonical field names.
    assert "Stu. Nm" in frame.columns
    assert "APAAR No." in frame.columns
    assert "student_name" not in frame.columns
    # And there is at least one blank row to skip.
    assert frame.isna().all(axis=1).any()
