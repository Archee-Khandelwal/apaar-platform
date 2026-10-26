"""Perturbed scenarios for the robustness run (`make eval-robust`).

Same scenario names as `datagen/scenarios.py`, so the evaluation harness scores them
the same way, but every case is deliberately *off* the shape the detectors were built
against: typo'd names, contacts written in other formats, cluster sizes spanning 6-40
students on 3-6 contacts, dual degrees in other programme combinations, an admission one
day late, and an intake breach of a single seat.

Nothing here is allowed to influence detector thresholds. Misses are findings.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

from app.services.rules import supernumerary_caps, year_calendar
from datagen.builder import GroundTruthCase
from datagen.scenarios import (
    _count_admission_type,
    _count_regular_year1,
    _eligible_institutions,
    _pick_program,
    _regular_programs,
    _reserved,
    _sample,
    _student_index,
)

CURRENT_YEAR = "2026-27"


# --------------------------------------------------------------------------- name noise


def typo(name: str, rng: Any, kind: str) -> str:
    """Return the same person's name, written differently."""
    if kind == "spacing":
        parts = name.split()
        return "  ".join(parts) + " "
    if kind == "case":
        return name.upper()
    if kind == "reordered":
        parts = name.split()
        return " ".join(reversed(parts)) if len(parts) > 1 else name
    if kind == "letter":
        index = rng.randrange(1, max(len(name) - 1, 2))
        if name[index] == " ":
            index += 1
        doubled = name[:index] + name[index] + name[index:]
        return doubled
    if kind == "initial":
        parts = name.split()
        return f"{parts[0]} {parts[-1][0]}." if len(parts) > 1 else name
    return name


# --------------------------------------------------------------------------- A: 1 seat over


def scenario_a_one_seat_over(gen: Any) -> None:
    """Intake breaches of 1, 2 and 8 seats — the 1-seat case is the hard one."""
    year = CURRENT_YEAR
    calendar = year_calendar(year)
    candidates = [
        inst for inst in _eligible_institutions(gen) if _regular_programs(gen, inst["id"])
    ]
    for institution, excess in zip(_sample(gen, candidates, 3), (1, 2, 8)):
        program = gen.rng.choice(_regular_programs(gen, institution["id"]))
        _reserved(gen).add(program["id"])
        upload = gen.upload_by[(institution["id"], year)]
        current = _count_regular_year1(gen, program["id"], year)
        for _ in range(max(program["intake"] + excess - current, excess)):
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
                    "perturbation": f"excess of only {excess} seat(s)",
                    "approved_intake": program["intake"],
                    "expected_excess": excess,
                },
            )
        )


# --------------------------------------------------------------------------- B: clusters


def scenario_b_varied_clusters(gen: Any) -> None:
    """Clusters of 6-40 students on 3-6 contacts, one spread across two institutions."""
    year = CURRENT_YEAR
    calendar = year_calendar(year)
    candidates = [
        inst for inst in _eligible_institutions(gen) if _regular_programs(gen, inst["id"])
    ]
    specs = [(6, 3), (9, 4), (14, 3), (22, 6), (40, 5)]
    chosen = _sample(gen, candidates, len(specs) + 2)

    for institution, (size, contacts) in zip(chosen, specs):
        program = _pick_program(gen, institution["id"], adding=size)
        if program is None:
            continue
        upload = gen.upload_by[(institution["id"], year)]
        phones = [gen.b.new_phone() for _ in range(contacts)]
        shared_email = f"cell.{institution['id']}@example.invalid"
        members: list[int] = []
        for index in range(size):
            student_id = gen.b.add_student(
                guardian_phone=phones[index % len(phones)], email=shared_email
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
            members.append(student_id)
        gen.b.label(
            GroundTruthCase(
                scenario="B_ghost_cluster",
                flag_type="GHOST_CLUSTER",
                key_kind="institution_year",
                key=f"{institution['id']}|{year}",
                institution_id=institution["id"],
                institution_name=institution["name"],
                details={
                    "perturbation": f"{size} students on {contacts + 1} shared contacts",
                    "students": size,
                    "guardian_contacts": contacts,
                    "shared_contacts": contacts + 1,
                    "students_per_contact": round(size / (contacts + 1), 2),
                    "student_ids": members,
                    "band": "tiny" if size < 8 else ("medium" if size < 20 else "large"),
                },
            )
        )

    # One cluster split across two institutions, sharing contacts in mixed formats.
    if len(chosen) >= len(specs) + 2:
        first, second = chosen[len(specs)], chosen[len(specs) + 1]
        phones = [gen.b.new_phone() for _ in range(3)]
        shared_email = "joint.cell@example.invalid"
        members: list[int] = []
        for position, institution in enumerate((first, second)):
            program = _pick_program(gen, institution["id"], adding=8)
            if program is None:
                continue
            upload = gen.upload_by[(institution["id"], year)]
            for index in range(8):
                student_id = gen.b.add_student(
                    guardian_phone=phones[(index + position) % len(phones)],
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
                members.append(student_id)
        for institution in (first, second):
            gen.b.label(
                GroundTruthCase(
                    scenario="B_ghost_cluster",
                    flag_type="GHOST_CLUSTER",
                    key_kind="institution_year",
                    key=f"{institution['id']}|{year}",
                    institution_id=institution["id"],
                    institution_name=institution["name"],
                    details={
                        "perturbation": "16 students split across TWO institutions",
                        "students": 16,
                        "guardian_contacts": 3,
                        "student_ids": members,
                        "band": "cross_institution",
                    },
                )
            )

    # Controls: families of 2-7 on one contact, in varied formats. Must not be flagged.
    for institution in _sample(gen, candidates, 5):
        program = _pick_program(gen, institution["id"], adding=7)
        if program is None:
            continue
        upload = gen.upload_by[(institution["id"], year)]
        shared = gen.b.new_phone()
        size = gen.rng.randint(2, 7)
        members = []
        for _ in range(size):
            student_id = gen.b.add_student(guardian_phone=shared)
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
            members.append(student_id)
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
                    "student_ids": members,
                    "perturbation": f"family of {size} with the contact in mixed formats",
                },
            )
        )


# --------------------------------------------------------------------------- C and D


def scenario_c_duplicates(gen: Any) -> None:
    """Cross-institution duplicates, including one pair in different years of study."""
    year = CURRENT_YEAR
    calendar = year_calendar(year)
    institutions = [
        inst for inst in _eligible_institutions(gen) if _regular_programs(gen, inst["id"])
    ]
    picked = 0
    attempts = 0
    while picked < 8 and attempts < 300:
        attempts += 1
        source = gen.rng.choice(institutions)
        program = gen.rng.choice(_regular_programs(gen, source["id"]))
        cohort = gen.cohorts.get((program["id"], year), [])
        if not cohort:
            continue
        student_id = gen.rng.choice(cohort)
        if _student_index(gen)[student_id]["apaar_status"] != "provided":
            continue
        other = gen.rng.choice([inst for inst in institutions if inst["id"] != source["id"]])
        other_program = _pick_program(gen, other["id"], adding=1)
        if other_program is None:
            continue
        upload = gen.upload_by[(other["id"], year)]
        # Half the cases are in a different year of study at the second institution.
        year_of_study = 2 if picked % 2 else 1
        gen.b.add_enrolment(
            student_id=student_id,
            program=other_program,
            academic_year=year,
            year_of_study=year_of_study,
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
                    "perturbation": f"second enrolment in year {year_of_study}",
                    "institutions": [source["name"], other["name"]],
                },
            )
        )
        picked += 1


def scenario_d_dual_degrees(gen: Any) -> None:
    """Dual degrees across other programme combinations, including same-institution."""
    year = CURRENT_YEAR
    calendar = year_calendar(year)
    online_programs = [
        program
        for program in gen.b.programs
        if program["mode"] == "online" and program["institution_id"] != gen.clean_institution_id
    ]
    if not online_programs:
        return
    institutions = {inst["id"]: inst for inst in gen.b.institutions}
    picked = 0
    attempts = 0
    while picked < 8 and attempts < 400:
        attempts += 1
        online_program = gen.rng.choice(online_programs)
        sources = [
            program
            for program in gen.b.programs
            if program["mode"] == "regular"
            and program["institution_id"] != online_program["institution_id"]
            and program["institution_id"] != gen.clean_institution_id
            and program["id"] not in _reserved(gen)
        ]
        if not sources:
            continue
        program = gen.rng.choice(sources)
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
            year_of_study=gen.rng.choice([1, 2]),
            admission_type=gen.rng.choice(["regular", "lateral"]),
            admitted_on=gen.b.random_date_in(
                calendar.admission_window_start, calendar.lateral_window_end
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
                    "perturbation": (
                        f"{program['course']} regular + {online_program['course']} online"
                    ),
                    "must_not_be_fraud": True,
                },
            )
        )
        picked += 1


# --------------------------------------------------------------------------- E, F, G, H, I


def scenario_e_apaar_problems(gen: Any) -> None:
    from datagen.scenarios import scenario_e_apaar_problems as base

    base(gen)


def scenario_f_one_day_late(gen: Any) -> None:
    """Admissions exactly one day after the cutoff, and one exactly on it (not late)."""
    year = CURRENT_YEAR
    calendar = year_calendar(year)
    candidates = [
        inst for inst in _eligible_institutions(gen) if _regular_programs(gen, inst["id"])
    ]
    for institution in _sample(gen, candidates, 2):
        program = _pick_program(gen, institution["id"], adding=14)
        if program is None:
            continue
        upload = gen.upload_by[(institution["id"], year)]

        for offset in (1, 1, 1, 1, 1, 2, 3):
            student_id = gen.b.add_student()
            late_date = calendar.admission_window_end + timedelta(days=offset)
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
                        "perturbation": f"{offset} day(s) after the cutoff",
                        "admitted_on": late_date.isoformat(),
                        "cutoff": calendar.admission_window_end.isoformat(),
                    },
                )
            )

        # Exactly ON the cutoff: in time, must NOT be flagged.
        for _ in range(3):
            student_id = gen.b.add_student()
            enrolment = gen.b.add_enrolment(
                student_id=student_id,
                program=program,
                academic_year=year,
                year_of_study=1,
                admission_type="regular",
                admitted_on=calendar.admission_window_end,
                created_at=upload["created_at"],
                upload_id=upload["id"],
            )
            gen.b.label(
                GroundTruthCase(
                    scenario="F_on_time_control",
                    flag_type="NONE",
                    key_kind="enrolment",
                    key=str(enrolment["id"]),
                    institution_id=institution["id"],
                    institution_name=institution["name"],
                    details={"perturbation": "admitted exactly on the cutoff date"},
                )
            )


def scenario_g_sequential(gen: Any) -> None:
    """Two runs: one tight block of 11, one looser block of 16 with bigger gaps."""
    year = CURRENT_YEAR
    calendar = year_calendar(year)
    candidates = [
        inst for inst in _eligible_institutions(gen) if _regular_programs(gen, inst["id"])
    ]
    for institution, (length, gap) in zip(_sample(gen, candidates, 2), ((11, 1), (16, 3))):
        program = _pick_program(gen, institution["id"], adding=length)
        if program is None:
            continue
        upload = gen.upload_by[(institution["id"], year)]
        run = gen.b.sequential_apaars(length, gap=gap)
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
        gen.b.label(
            GroundTruthCase(
                scenario="G_sequential_apaar",
                flag_type="SEQUENTIAL_APAAR",
                key_kind="institution_year",
                key=f"{institution['id']}|{year}",
                institution_id=institution["id"],
                institution_name=institution["name"],
                details={
                    "perturbation": f"run of {length} with gaps of up to {gap}",
                    "run_length": length,
                },
            )
        )


def scenario_h_last_minute(gen: Any) -> None:
    """One institution at 45% in the window (just over threshold), one at 85%."""
    year = CURRENT_YEAR
    calendar = year_calendar(year)
    candidates = [
        inst for inst in _eligible_institutions(gen) if _regular_programs(gen, inst["id"])
    ]
    for institution, share in zip(_sample(gen, candidates, 2), (0.45, 0.85)):
        rows = [
            row
            for row in gen.b.enrolments
            if row["institution_id"] == institution["id"] and row["academic_year"] == year
        ]
        if not rows:
            continue
        bulk = gen.rng.sample(rows, int(len(rows) * share))
        for row in bulk:
            row["created_at"] = calendar.reporting_deadline - timedelta(
                hours=gen.rng.uniform(0.1, 5.5)
            )
        gen.b.label(
            GroundTruthCase(
                scenario="H_last_minute_bulk",
                flag_type="LAST_MINUTE_BULK",
                key_kind="institution_year",
                key=f"{institution['id']}|{year}",
                institution_id=institution["id"],
                institution_name=institution["name"],
                details={
                    "perturbation": f"{int(share * 100)}% of records in the final 6 hours",
                    "share_percent": int(share * 100),
                },
            )
        )


def scenario_i_phantom(gen: Any) -> None:
    from datagen.scenarios import scenario_i_phantom_progression as base

    base(gen)


# --------------------------------------------------------------------------- J: typo'd names


def scenario_j_identity_duplicates(gen: Any) -> None:
    """One person, two APAAR IDs — with the name written differently each time.

    Spacing and case variations survive normalisation and should be caught. A doubled
    letter or a reordered name will not match an exact normalised-name hash, and is
    expected to be missed: that is the finding, not a bug to paper over.
    """
    year = CURRENT_YEAR
    calendar = year_calendar(year)
    candidates = [
        inst for inst in _eligible_institutions(gen) if _regular_programs(gen, inst["id"])
    ]
    if len(candidates) < 2:
        return

    perturbations = ["exact", "spacing", "case", "letter", "reordered", "initial"]
    for kind in perturbations:
        name = gen.faker.name()
        dob = date(gen.rng.randint(2004, 2007), gen.rng.randint(1, 12), gen.rng.randint(1, 28))
        guardian = gen.b.new_phone()
        pair = _sample(gen, candidates, 2)
        if len(pair) < 2:
            return
        ids: list[int] = []
        for position, institution in enumerate(pair):
            program = _pick_program(gen, institution["id"], adding=1)
            if program is None:
                continue
            upload = gen.upload_by[(institution["id"], year)]
            written = name if position == 0 else typo(name, gen.rng, kind)
            student_id = gen.b.add_student(name=written, dob=dob, guardian_phone=guardian)
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
            ids.append(student_id)

        for student_id in ids:
            gen.b.label(
                GroundTruthCase(
                    scenario="J_identity_duplicate",
                    flag_type="IDENTITY_DUPLICATE",
                    key_kind="student",
                    key=str(student_id),
                    institution_id=pair[0]["id"],
                    institution_name=pair[0]["name"],
                    details={
                        "perturbation": f"second record's name written with a {kind} variation",
                        "variation": kind,
                        "pair": ids,
                    },
                )
            )


# --------------------------------------------------------------------------- K


def scenario_k_supernumerary(gen: Any) -> None:
    from datagen.scenarios import scenario_k_supernumerary_misuse as base

    base(gen)


SCENARIOS = {
    "A_excess_intake": scenario_a_one_seat_over,
    "B_ghost_cluster": scenario_b_varied_clusters,
    "C_cross_institution_duplicate": scenario_c_duplicates,
    "D_dual_degree": scenario_d_dual_degrees,
    "E_apaar_problems": scenario_e_apaar_problems,
    "F_late_admission": scenario_f_one_day_late,
    "G_sequential_apaar": scenario_g_sequential,
    "H_last_minute_bulk": scenario_h_last_minute,
    "I_phantom_progression": scenario_i_phantom,
    "J_identity_duplicate": scenario_j_identity_duplicates,
    "K_supernumerary_misuse": scenario_k_supernumerary,
}


def inject_all(gen: Any) -> None:
    for _name, func in SCENARIOS.items():
        func(gen)
