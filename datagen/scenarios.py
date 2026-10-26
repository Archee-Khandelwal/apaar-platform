"""Labelled fraud / data-quality scenarios A-J (Step 5 of docs/PLAN.md).

Every injected case is recorded in ``ground_truth.json`` so ``make eval`` can measure
precision and recall per detector. The clean "model" institution is never touched.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

from app.core.crypto import hash_name, hash_phone, hmac_hash, mask_apaar, vault_encrypt
from app.services.rules import supernumerary_caps, year_calendar
from datagen.builder import GroundTruthCase

if TYPE_CHECKING:  # pragma: no cover
    from datagen.generator import SyntheticDataGenerator

CURRENT_YEAR = "2026-27"


# --------------------------------------------------------------------------- helpers


def _sample(gen: SyntheticDataGenerator, population: list[Any], k: int) -> list[Any]:
    """Sample without blowing up on a small run (the tests seed only a few institutions)."""
    if not population:
        return []
    return gen.rng.sample(population, min(k, len(population)))


def _excluded_institutions(gen: SyntheticDataGenerator) -> set[int]:
    """Institutions no scenario may touch: the clean model one and the non-reporting ones."""
    return {gen.clean_institution_id} | getattr(gen, "non_reporting_ids", set())


def _eligible_institutions(gen: SyntheticDataGenerator) -> list[dict[str, Any]]:
    excluded = _excluded_institutions(gen)
    return [inst for inst in gen.b.institutions if inst["id"] not in excluded]


def _eligible_programs(gen: SyntheticDataGenerator, *, mode: str | None = None) -> list[dict[str, Any]]:
    """Programmes at institutions a scenario may touch."""
    excluded = _excluded_institutions(gen)
    return [
        program
        for program in gen.b.programs
        if program["institution_id"] not in excluded
        and (mode is None or program["mode"] == mode)
    ]


def _reserved(gen: SyntheticDataGenerator) -> set[int]:
    """Programmes whose seat counts another scenario owns and must not be disturbed."""
    if not hasattr(gen, "reserved_programs"):
        gen.reserved_programs = set()  # type: ignore[attr-defined]
    return gen.reserved_programs  # type: ignore[attr-defined]


def _pick_program(
    gen: SyntheticDataGenerator, institution_id: int, *, adding: int = 0, year: str = CURRENT_YEAR
) -> dict[str, Any] | None:
    """Pick a programme that can absorb ``adding`` more year-1 students without tipping
    over its approved intake, so injected students never create an unlabelled
    EXCESS_INTAKE case."""
    candidates = [
        program
        for program in _regular_programs(gen, institution_id)
        if program["id"] not in _reserved(gen)
    ]
    if not candidates:
        return None
    with_room = [
        program
        for program in candidates
        if _count_regular_year1(gen, program["id"], year) + adding <= program["intake"]
    ]
    return gen.rng.choice(with_room or candidates)


def _regular_programs(gen: SyntheticDataGenerator, institution_id: int) -> list[dict[str, Any]]:
    return [
        program
        for program in gen.programs_by_institution[institution_id]
        if program["mode"] == "regular"
    ]


def _count_admission_type(
    gen: SyntheticDataGenerator, program_id: int, year: str, admission_type: str
) -> int:
    return sum(
        1
        for row in gen.b.enrolments
        if row["program_id"] == program_id
        and row["academic_year"] == year
        and row["admission_type"] == admission_type
        and row["status"] in ("admitted", "completed")
    )


def _count_regular_year1(gen: SyntheticDataGenerator, program_id: int, year: str) -> int:
    return sum(
        1
        for row in gen.b.enrolments
        if row["program_id"] == program_id
        and row["academic_year"] == year
        and row["admission_type"] == "regular"
        and row["year_of_study"] == 1
        and row["status"] in ("admitted", "completed")
    )


def _vault_index(gen: SyntheticDataGenerator) -> dict[int, dict[str, Any]]:
    return {row["student_id"]: row for row in gen.b.vault_rows}


def _student_index(gen: SyntheticDataGenerator) -> dict[int, dict[str, Any]]:
    return {row["id"]: row for row in gen.b.students}


# --------------------------------------------------------------------------- A


def scenario_a_excess_intake(gen: SyntheticDataGenerator) -> None:
    """Three institutions over approved intake once valid supernumerary seats are excluded.

    One of them is over by just 3 seats, which is the hard case a counts-only return
    would never surface.
    """
    year = CURRENT_YEAR
    calendar = year_calendar(year)
    candidates = [
        inst for inst in _eligible_institutions(gen) if _regular_programs(gen, inst["id"])
    ]
    chosen = _sample(gen, candidates, 3)

    for institution, excess in zip(chosen, (3, 12, 25)):
        program = gen.rng.choice(_regular_programs(gen, institution["id"]))
        _reserved(gen).add(program["id"])
        upload = gen.upload_by[(institution["id"], year)]
        current = _count_regular_year1(gen, program["id"], year)
        target = program["intake"] + excess
        to_add = target - current
        if to_add <= 0:  # already at or above target; trim nothing, just relabel
            to_add = excess
        for _ in range(to_add):
            student_id = gen.b.add_student()
            gen.b.add_enrolment(
                student_id=student_id,
                program=program,
                academic_year=year,
                year_of_study=1,
                admission_type="regular",
                admitted_on=gen.b.random_date_in(
                    calendar.admission_window_start, calendar.admission_window_end
                ),
                created_at=upload["created_at"],
                upload_id=upload["id"],
            )
        gen.b.label(
            GroundTruthCase(
                scenario="A_excess_intake",
                flag_type="EXCESS_INTAKE",
                key_kind="program_year",
                key=f"{program['id']}|{year}",
                institution_id=institution["id"],
                institution_name=institution["name"],
                details={
                    "program": f"{program['course']} {program['branch']}",
                    "approved_intake": program["intake"],
                    "expected_excess": excess,
                    "cause": "regular admissions beyond approved intake",
                },
            )
        )

    # A fourth case that is over ONLY because a supernumerary bucket exceeds its cap.
    remaining = [inst for inst in candidates if inst["id"] not in {c["id"] for c in chosen}]
    if not remaining:
        return
    institution = gen.rng.choice(remaining)
    program = gen.rng.choice(_regular_programs(gen, institution["id"]))
    _reserved(gen).add(program["id"])
    upload = gen.upload_by[(institution["id"], year)]
    caps = supernumerary_caps(program["intake"])
    cap = caps.get("tfw", 0)
    over_by = 4
    for _ in range(cap + over_by):
        student_id = gen.b.add_student()
        gen.b.add_enrolment(
            student_id=student_id,
            program=program,
            academic_year=year,
            year_of_study=1,
            admission_type="tfw",
            admitted_on=gen.b.random_date_in(
                calendar.admission_window_start, calendar.admission_window_end
            ),
            created_at=upload["created_at"],
            upload_id=upload["id"],
        )
    gen.b.label(
        GroundTruthCase(
            scenario="A_excess_intake",
            flag_type="EXCESS_INTAKE",
            key_kind="program_year",
            key=f"{program['id']}|{year}",
            institution_id=institution["id"],
            institution_name=institution["name"],
            details={
                "program": f"{program['course']} {program['branch']}",
                "approved_intake": program["intake"],
                "expected_excess": over_by,
                "cause": "TFW supernumerary admissions beyond their cap",
                "tfw_cap": cap,
            },
        )
    )


# --------------------------------------------------------------------------- B


def scenario_b_ghost_clusters(gen: SyntheticDataGenerator) -> None:
    """Two institutions with a cluster of 25-35 students sharing 2-3 guardian contacts."""
    year = CURRENT_YEAR
    calendar = year_calendar(year)
    candidates = [
        inst for inst in _eligible_institutions(gen) if _regular_programs(gen, inst["id"])
    ]
    # Two blatant clusters plus one deliberately subtler cluster, so evaluation shows
    # the detector catches a medium case and not only the obvious ones.
    cluster_specs: list[tuple[int, int, int, str]] = [
        (25, 35, 2, "large"),
        (25, 35, 3, "large"),
        (8, 10, 3, "medium"),
    ]
    for institution, (size_min, size_max, contacts, band) in zip(
        _sample(gen, candidates, len(cluster_specs)), cluster_specs
    ):
        program = _pick_program(gen, institution["id"], adding=size_max)
        if program is None:
            continue
        upload = gen.upload_by[(institution["id"], year)]
        size = gen.rng.randint(size_min, size_max)
        guardian_phones = [gen.b.new_phone() for _ in range(contacts)]
        # Fabricated rows are typically entered by one person, who also reuses a single
        # contact email. That shared email is what links the guardian-phone groups into
        # one component rather than two or three unconnected stars.
        shared_email = f"admissions.cell{institution['id']}@example.invalid"
        member_ids: list[int] = []
        for index in range(size):
            student_id = gen.b.add_student(
                guardian_phone=guardian_phones[index % len(guardian_phones)],
                email=shared_email,
            )
            gen.b.add_enrolment(
                student_id=student_id,
                program=program,
                academic_year=year,
                year_of_study=1,
                admission_type="regular",
                admitted_on=gen.b.random_date_in(
                    calendar.admission_window_start, calendar.admission_window_end
                ),
                created_at=upload["created_at"],
                upload_id=upload["id"],
            )
            member_ids.append(student_id)

        gen.b.label(
            GroundTruthCase(
                scenario="B_ghost_cluster",
                flag_type="GHOST_CLUSTER",
                key_kind="institution_year",
                key=f"{institution['id']}|{year}",
                institution_id=institution["id"],
                institution_name=institution["name"],
                details={
                    "band": band,
                    "students": size,
                    "guardian_contacts": len(guardian_phones),
                    "shared_contacts": contacts + 1,  # guardian phones + the shared email
                    "students_per_contact": round(size / (contacts + 1), 1),
                    "student_ids": member_ids,
                    "program": f"{program['course']} {program['branch']}",
                },
            )
        )

    # Larger-but-legitimate groups: an extended family, or students who gave a shared
    # hostel / warden contact. 4-6 students on one contact sits between normal siblings
    # and a ghost cluster, so the detector's threshold has to be a real decision rather
    # than a trivially separable one. These must NOT be flagged either.
    for institution in _sample(gen, candidates, 3):
        program = _pick_program(gen, institution["id"], adding=6)
        if program is None:
            continue
        upload = gen.upload_by[(institution["id"], year)]
        shared = gen.b.new_phone()
        size = gen.rng.randint(4, 6)
        member_ids: list[int] = []
        for _ in range(size):
            student_id = gen.b.add_student(guardian_phone=shared)
            member_ids.append(student_id)
            gen.b.add_enrolment(
                student_id=student_id,
                program=program,
                academic_year=year,
                year_of_study=1,
                admission_type="regular",
                admitted_on=gen.b.random_date_in(
                    calendar.admission_window_start, calendar.admission_window_end
                ),
                created_at=upload["created_at"],
                upload_id=upload["id"],
            )
        gen.b.label(
            GroundTruthCase(
                scenario="B_sibling_control",
                flag_type="NONE",
                key_kind="institution_year",
                key=f"{institution['id']}|{year}",
                institution_id=institution["id"],
                institution_name=institution["name"],
                details={
                    "students": size,
                    "guardian_contacts": 1,
                    "student_ids": member_ids,
                    "note": (
                        f"{size} students sharing one guardian/warden contact — "
                        "legitimate, must not be flagged"
                    ),
                },
            )
        )

    # Normal sibling pairs — these must NOT be flagged (false-positive control).
    for institution in _sample(gen, candidates, 6):
        program = _pick_program(gen, institution["id"], adding=3)
        if program is None:
            continue
        upload = gen.upload_by[(institution["id"], year)]
        shared = gen.b.new_phone()
        sibling_ids: list[int] = []
        for _ in range(gen.rng.randint(2, 3)):
            student_id = gen.b.add_student(guardian_phone=shared)
            sibling_ids.append(student_id)
            gen.b.add_enrolment(
                student_id=student_id,
                program=program,
                academic_year=year,
                year_of_study=1,
                admission_type="regular",
                admitted_on=gen.b.random_date_in(
                    calendar.admission_window_start, calendar.admission_window_end
                ),
                created_at=upload["created_at"],
                upload_id=upload["id"],
            )
        gen.b.label(
            GroundTruthCase(
                scenario="B_sibling_control",
                flag_type="NONE",
                key_kind="institution_year",
                key=f"{institution['id']}|{year}",
                institution_id=institution["id"],
                institution_name=institution["name"],
                details={
                    "students": len(sibling_ids),
                    "guardian_contacts": 1,
                    "student_ids": sibling_ids,
                    "note": "2-3 siblings sharing one guardian contact — must not be flagged",
                },
            )
        )


# --------------------------------------------------------------------------- C and D


def scenario_c_cross_institution_duplicates(gen: SyntheticDataGenerator) -> None:
    """15 students with the same APAAR in two full-time regular programmes, same year."""
    year = CURRENT_YEAR
    calendar = year_calendar(year)
    institutions = [
        inst for inst in _eligible_institutions(gen) if _regular_programs(gen, inst["id"])
    ]

    picked = 0
    attempts = 0
    while picked < 15 and attempts < 200:
        attempts += 1
        source = gen.rng.choice(institutions)
        program = gen.rng.choice(_regular_programs(gen, source["id"]))
        cohort = gen.cohorts.get((program["id"], year), [])
        if not cohort:
            continue
        student_id = gen.rng.choice(cohort)
        student = _student_index(gen)[student_id]
        if student["apaar_status"] != "provided":
            continue

        other = gen.rng.choice([inst for inst in institutions if inst["id"] != source["id"]])
        other_program = _pick_program(gen, other["id"], adding=1)
        if other_program is None:
            continue
        upload = gen.upload_by[(other["id"], year)]
        gen.b.add_enrolment(
            student_id=student_id,
            program=other_program,
            academic_year=year,
            year_of_study=1,
            admission_type="regular",
            admitted_on=gen.b.random_date_in(
                calendar.admission_window_start, calendar.admission_window_end
            ),
            created_at=upload["created_at"],
            upload_id=upload["id"],
        )
        gen.b.label(
            GroundTruthCase(
                scenario="C_cross_institution_duplicate",
                flag_type="CROSS_INSTITUTION_DUPLICATE",
                key_kind="student",
                key=str(student_id),
                institution_id=source["id"],
                institution_name=source["name"],
                details={
                    "academic_year": year,
                    "institutions": [source["name"], other["name"]],
                    "both_full_time_regular": True,
                },
            )
        )
        picked += 1


def scenario_d_dual_degree(gen: SyntheticDataGenerator) -> None:
    """10 students with one regular and one online/ODL enrolment — legal, not fraud."""
    year = CURRENT_YEAR
    calendar = year_calendar(year)
    online_programs = _eligible_programs(gen, mode="online")
    if not online_programs:
        return

    institutions = {inst["id"]: inst for inst in gen.b.institutions}
    picked = 0
    attempts = 0
    while picked < 10 and attempts < 300:
        attempts += 1
        online_program = gen.rng.choice(online_programs)
        source_candidates = [
            program
            for program in _eligible_programs(gen, mode="regular")
            if program["institution_id"] != online_program["institution_id"]
        ]
        if not source_candidates:
            continue
        program = gen.rng.choice(source_candidates)
        if program["id"] in _reserved(gen):
            continue
        cohort = gen.cohorts.get((program["id"], year), [])
        if not cohort:
            continue
        student_id = gen.rng.choice(cohort)
        if _student_index(gen)[student_id]["apaar_status"] != "provided":
            continue
        upload = gen.upload_by[(online_program["institution_id"], year)]
        gen.b.add_enrolment(
            student_id=student_id,
            program=online_program,
            academic_year=year,
            year_of_study=1,
            admission_type="regular",
            admitted_on=gen.b.random_date_in(
                calendar.admission_window_start, calendar.admission_window_end
            ),
            created_at=upload["created_at"],
            upload_id=upload["id"],
        )
        gen.b.label(
            GroundTruthCase(
                scenario="D_dual_degree",
                flag_type="POSSIBLE_DUAL_DEGREE",
                key_kind="student",
                key=str(student_id),
                institution_id=program["institution_id"],
                institution_name=institutions[program["institution_id"]]["name"],
                details={
                    "academic_year": year,
                    "regular_program": f"{program['course']} {program['branch']}",
                    "online_program": f"{online_program['course']} {online_program['branch']}",
                    "must_not_be_fraud": True,
                },
            )
        )
        picked += 1


# --------------------------------------------------------------------------- E


def scenario_e_apaar_problems(gen: SyntheticDataGenerator) -> None:
    """About 1% of records carry an APAAR problem: invalid format, not found, mismatch."""
    students = _student_index(gen)
    vaults = _vault_index(gen)
    provided = [
        row["id"]
        for row in gen.b.students
        if row["apaar_status"] == "provided" and row["registry_status"] == "match"
    ]
    # Keep the clean institution's students out of it.
    clean_students = {
        row["student_id"]
        for row in gen.b.enrolments
        if row["institution_id"] == gen.clean_institution_id
    }
    provided = [sid for sid in provided if sid not in clean_students]
    sample_size = max(int(len(provided) * 0.01), 30)
    sample = gen.rng.sample(provided, min(sample_size, len(provided)))

    institutions = {inst["id"]: inst for inst in gen.b.institutions}
    institution_by_student: dict[int, int] = {}
    for row in gen.b.enrolments:
        institution_by_student.setdefault(row["student_id"], row["institution_id"])

    for index, student_id in enumerate(sample):
        problem = ("invalid_format", "not_found", "mismatch")[index % 3]
        student = students[student_id]
        identity = next(item for item in gen.b.raw if item.student_id == student_id)

        if problem == "invalid_format":
            broken = gen.b.new_apaar(digits=11)  # 11 digits: fails the format check
            student["apaar_hash"] = hmac_hash(broken)
            student["apaar_masked"] = mask_apaar(broken)
            vaults[student_id]["apaar_enc"] = vault_encrypt(broken)
            identity.apaar = broken
            flag_type = "INVALID_APAAR"
        elif problem == "not_found":
            flag_type = "APAAR_NOT_FOUND"
        else:
            flag_type = "APAAR_MISMATCH"

        student["registry_status"] = problem
        identity.registry_status = problem
        for row in gen.b.enrolments:
            if row["student_id"] == student_id:
                row["registry_status"] = problem

        institution_id = institution_by_student.get(student_id)
        gen.b.label(
            GroundTruthCase(
                scenario="E_apaar_problems",
                flag_type=flag_type,
                key_kind="student",
                key=str(student_id),
                institution_id=institution_id,
                institution_name=institutions[institution_id]["name"] if institution_id else None,
                details={"problem": problem},
            )
        )


# --------------------------------------------------------------------------- F, G, H


def scenario_f_late_admissions(gen: SyntheticDataGenerator) -> None:
    """About 40 admissions after the admission cutoff, at two institutions."""
    year = CURRENT_YEAR
    calendar = year_calendar(year)
    candidates = [
        inst for inst in _eligible_institutions(gen) if _regular_programs(gen, inst["id"])
    ]
    for institution in _sample(gen, candidates, 2):
        program = _pick_program(gen, institution["id"], adding=20)
        if program is None:
            continue
        upload = gen.upload_by[(institution["id"], year)]
        for _ in range(20):
            student_id = gen.b.add_student()
            late_date = calendar.admission_window_end + timedelta(days=gen.rng.randint(5, 30))
            enrolment = gen.b.add_enrolment(
                student_id=student_id,
                program=program,
                academic_year=year,
                year_of_study=1,
                admission_type="regular",
                admitted_on=late_date,
                created_at=upload["created_at"],
                upload_id=upload["id"],
            )
            gen.b.label(
                GroundTruthCase(
                    scenario="F_late_admission",
                    flag_type="LATE_ADMISSION",
                    key_kind="enrolment",
                    key=str(enrolment["id"]),
                    institution_id=institution["id"],
                    institution_name=institution["name"],
                    details={
                        "admitted_on": late_date.isoformat(),
                        "cutoff": calendar.admission_window_end.isoformat(),
                    },
                )
            )


def scenario_g_sequential_apaar(gen: SyntheticDataGenerator) -> None:
    """One institution with a run of 20 near-consecutive APAAR IDs."""
    year = CURRENT_YEAR
    calendar = year_calendar(year)
    candidates = [
        inst for inst in _eligible_institutions(gen) if _regular_programs(gen, inst["id"])
    ]
    if not candidates:
        return
    institution = gen.rng.choice(candidates)
    program = _pick_program(gen, institution["id"], adding=20)
    if program is None:
        return
    upload = gen.upload_by[(institution["id"], year)]
    run = gen.b.sequential_apaars(20)
    student_ids: list[int] = []
    for apaar in run:
        student_id = gen.b.add_student(apaar=apaar)
        gen.b.add_enrolment(
            student_id=student_id,
            program=program,
            academic_year=year,
            year_of_study=1,
            admission_type="regular",
            admitted_on=gen.b.random_date_in(
                calendar.admission_window_start, calendar.admission_window_end
            ),
            created_at=upload["created_at"],
            upload_id=upload["id"],
        )
        student_ids.append(student_id)

    gen.b.label(
        GroundTruthCase(
            scenario="G_sequential_apaar",
            flag_type="SEQUENTIAL_APAAR",
            key_kind="institution_year",
            key=f"{institution['id']}|{year}",
            institution_id=institution["id"],
            institution_name=institution["name"],
            details={
                "run_length": len(run),
                "first_masked": mask_apaar(run[0]),
                "last_masked": mask_apaar(run[-1]),
                "student_ids": student_ids,
            },
        )
    )


def scenario_h_last_minute_bulk(gen: SyntheticDataGenerator) -> None:
    """One institution reports 60% of its records in the final 6 hours before the deadline."""
    year = CURRENT_YEAR
    calendar = year_calendar(year)
    candidates = [
        inst for inst in _eligible_institutions(gen) if _regular_programs(gen, inst["id"])
    ]
    if not candidates:
        return
    institution = gen.rng.choice(candidates)
    rows = [
        row
        for row in gen.b.enrolments
        if row["institution_id"] == institution["id"] and row["academic_year"] == year
    ]
    if not rows:
        return

    late_upload = gen.b.add_upload(
        institution_id=institution["id"],
        filename=f"students_{year.replace('-', '_')}_final.xlsx",
        academic_year=year,
        created_at=calendar.reporting_deadline - timedelta(hours=3),
        rows_total=0,
        rows_ok=0,
        rows_error=0,
        quality_score=gen.rng.randint(55, 70),
    )

    bulk = gen.rng.sample(rows, int(len(rows) * 0.6))
    for row in bulk:
        row["created_at"] = calendar.reporting_deadline - timedelta(
            hours=gen.rng.uniform(0.2, 5.8)
        )
        row["upload_id"] = late_upload["id"]

    gen.b.label(
        GroundTruthCase(
            scenario="H_last_minute_bulk",
            flag_type="LAST_MINUTE_BULK",
            key_kind="institution_year",
            key=f"{institution['id']}|{year}",
            institution_id=institution["id"],
            institution_name=institution["name"],
            details={
                "share_percent": 60,
                "window_hours": 6,
                "records_in_window": len(bulk),
                "total_records": len(rows),
            },
        )
    )


# --------------------------------------------------------------------------- I


def scenario_i_phantom_progression(gen: SyntheticDataGenerator) -> None:
    """Year-2 regular students with no year-1 record, and students who vanish silently."""
    year = CURRENT_YEAR
    previous_year = gen.years[0]
    candidates = [
        inst for inst in _eligible_institutions(gen) if _regular_programs(gen, inst["id"])
    ]

    if not candidates:
        return

    # (a) Year-2 regular students who were never in year 1 and are not lateral entrants.
    institution = gen.rng.choice(candidates)
    program = _pick_program(gen, institution["id"])
    if program is None:
        return
    upload = gen.upload_by[(institution["id"], year)]
    for _ in range(12):
        student_id = gen.b.add_student()
        gen.b.add_enrolment(
            student_id=student_id,
            program=program,
            academic_year=year,
            year_of_study=2,
            admission_type="regular",
            admitted_on=None,
            created_at=upload["created_at"],
            upload_id=upload["id"],
        )
        gen.b.label(
            GroundTruthCase(
                scenario="I_phantom_progression",
                flag_type="PHANTOM_PROGRESSION",
                key_kind="student",
                key=str(student_id),
                institution_id=institution["id"],
                institution_name=institution["name"],
                details={
                    "kind": "year2_without_year1",
                    "program": f"{program['course']} {program['branch']}",
                },
            )
        )

    # (b) Students present in year 1 who disappear in year 2 with no exit status.
    others = [inst for inst in candidates if inst["id"] != institution["id"]]
    if not others:
        return
    other = gen.rng.choice(others)
    other_program = _pick_program(gen, other["id"])
    if other_program is None:
        return
    cohort = gen.cohorts.get((other_program["id"], previous_year), [])
    vanishing = set(gen.rng.sample(cohort, min(15, len(cohort))))
    if vanishing:
        before = len(gen.b.enrolments)
        gen.b.enrolments = [
            row
            for row in gen.b.enrolments
            if not (
                row["student_id"] in vanishing
                and row["academic_year"] == year
                and row["program_id"] == other_program["id"]
            )
        ]
        removed = before - len(gen.b.enrolments)
        for student_id in vanishing:
            gen.b.label(
                GroundTruthCase(
                    scenario="I_phantom_progression",
                    flag_type="PHANTOM_PROGRESSION",
                    key_kind="student",
                    key=str(student_id),
                    institution_id=other["id"],
                    institution_name=other["name"],
                    details={
                        "kind": "vanished_without_status",
                        "previous_year": previous_year,
                        "removed_rows": removed,
                    },
                )
            )


# --------------------------------------------------------------------------- J


def scenario_j_identity_duplicates(gen: SyntheticDataGenerator) -> None:
    """Eight people holding two different APAAR IDs (same name, DOB and guardian phone)."""
    year = CURRENT_YEAR
    calendar = year_calendar(year)
    candidates = [
        inst for inst in _eligible_institutions(gen) if _regular_programs(gen, inst["id"])
    ]

    if len(candidates) < 2:
        return

    for _ in range(8):
        name = gen.faker.name()
        dob = date(gen.rng.randint(2004, 2007), gen.rng.randint(1, 12), gen.rng.randint(1, 28))
        guardian_phone = gen.b.new_phone()
        pair_ids: list[int] = []
        pair_institutions: list[dict[str, Any]] = _sample(gen, candidates, 2)
        if len(pair_institutions) < 2:
            return

        for institution in pair_institutions:
            program = _pick_program(gen, institution["id"], adding=1)
            if program is None:
                continue
            upload = gen.upload_by[(institution["id"], year)]
            student_id = gen.b.add_student(
                name=name, dob=dob, guardian_phone=guardian_phone
            )
            gen.b.add_enrolment(
                student_id=student_id,
                program=program,
                academic_year=year,
                year_of_study=1,
                admission_type="regular",
                admitted_on=gen.b.random_date_in(
                    calendar.admission_window_start, calendar.admission_window_end
                ),
                created_at=upload["created_at"],
                upload_id=upload["id"],
            )
            pair_ids.append(student_id)

        for student_id in pair_ids:
            gen.b.label(
                GroundTruthCase(
                    scenario="J_identity_duplicate",
                    flag_type="IDENTITY_DUPLICATE",
                    key_kind="student",
                    key=str(student_id),
                    institution_id=pair_institutions[0]["id"],
                    institution_name=pair_institutions[0]["name"],
                    details={
                        "pair": pair_ids,
                        "same_name_dob_guardian": True,
                        "different_apaar": True,
                    },
                )
            )


# --------------------------------------------------------------------------- K


def scenario_k_supernumerary_misuse(gen: SyntheticDataGenerator) -> None:
    """One institution labels an unusual share of admissions as TFW / other supernumerary.

    Every bucket stays INSIDE its cap, so this is not an intake breach — it is the
    pattern you would expect if regular admissions were being relabelled to keep them
    outside approved intake. The detector must raise it as a review signal, not as
    EXCESS_INTAKE.
    """
    year = CURRENT_YEAR
    calendar = year_calendar(year)
    candidates = [
        inst
        for inst in _eligible_institutions(gen)
        if len(_regular_programs(gen, inst["id"])) >= 2
    ]
    if not candidates:
        return
    institution = gen.rng.choice(candidates)
    upload = gen.upload_by[(institution["id"], year)]

    added: dict[str, int] = {"tfw": 0, "other_supernumerary": 0}
    for program in _regular_programs(gen, institution["id"]):
        _reserved(gen).add(program["id"])
        caps = supernumerary_caps(program["intake"])
        for admission_type in ("tfw", "other_supernumerary"):
            cap = caps.get(admission_type, 0)
            if cap <= 0:
                continue
            # Top up TO almost the whole cap, counting what is already reported:
            # legal, but far above what peers report. Adding on top of existing
            # admissions would breach the cap and turn this into a real EXCESS_INTAKE.
            existing = _count_admission_type(gen, program["id"], year, admission_type)
            count = max(int(cap * 0.95) - existing, 0)
            for _ in range(count):
                student_id = gen.b.add_student()
                gen.b.add_enrolment(
                    student_id=student_id,
                    program=program,
                    academic_year=year,
                    year_of_study=1,
                    admission_type=admission_type,
                    admitted_on=gen.b.random_date_in(
                        calendar.admission_window_start, calendar.admission_window_end
                    ),
                    created_at=upload["created_at"],
                    upload_id=upload["id"],
                )
                added[admission_type] += 1

    if not sum(added.values()):
        return

    gen.b.label(
        GroundTruthCase(
            scenario="K_supernumerary_misuse",
            flag_type="STATISTICAL_ANOMALY",
            key_kind="institution_year",
            key=f"{institution['id']}|{year}",
            institution_id=institution["id"],
            institution_name=institution["name"],
            details={
                "signal": "supernumerary_share",
                "added": added,
                "within_caps": True,
                "note": (
                    "Every bucket is inside its cap, so this must NOT be flagged as "
                    "EXCESS_INTAKE - only as a review signal."
                ),
            },
        )
    )


# --------------------------------------------------------------------------- entry point

SCENARIOS = {
    "A_excess_intake": scenario_a_excess_intake,
    "B_ghost_cluster": scenario_b_ghost_clusters,
    "C_cross_institution_duplicate": scenario_c_cross_institution_duplicates,
    "D_dual_degree": scenario_d_dual_degree,
    "E_apaar_problems": scenario_e_apaar_problems,
    "F_late_admission": scenario_f_late_admissions,
    "G_sequential_apaar": scenario_g_sequential_apaar,
    "H_last_minute_bulk": scenario_h_last_minute_bulk,
    "I_phantom_progression": scenario_i_phantom_progression,
    "J_identity_duplicate": scenario_j_identity_duplicates,
    "K_supernumerary_misuse": scenario_k_supernumerary_misuse,
}


def inject_all(gen: SyntheticDataGenerator) -> None:
    for name, func in SCENARIOS.items():
        func(gen)
