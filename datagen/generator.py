"""Synthetic data generator (Step 5 of docs/PLAN.md).

Everything the detectors are measured on is produced here, with every injected case
labelled in ``datagen/ground_truth.json``. Deterministic for a given ``--seed``.
"""
from __future__ import annotations

import json
import random
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from faker import Faker
from sqlalchemy import delete, text
from sqlalchemy.orm import Session

from app.core.config import REPO_ROOT
from app.models.core import (
    AccessLog,
    ApprovedIntake,
    AuditLog,
    Consent,
    CorrectionRequest,
    Enrolment,
    EnrolmentHistory,
    Flag,
    FlagHistory,
    Institution,
    Program,
    Student,
    Upload,
    User,
    Vault,
    VerificationRequest,
)
from app.services.rules import supernumerary_caps, year_calendar
from app.services.users import CREDENTIALS_PATH
from datagen import vocab
from datagen.builder import DataBuilder, GroundTruthCase

GROUND_TRUTH_PATH = Path(__file__).resolve().parent / "ground_truth.json"
DEFAULT_YEARS = ("2025-26", "2026-27")
# Share of the student target allocated to base year-1 cohorts (the rest is
# supernumerary admissions, lateral entrants and the injected scenarios).
BASE_COHORT_SHARE = 0.70

# Tables wiped by a reseed, children first.
WIPE_ORDER = (
    FlagHistory,
    Flag,
    CorrectionRequest,
    VerificationRequest,
    Consent,
    AccessLog,
    AuditLog,
    EnrolmentHistory,
    Enrolment,
    Vault,
    User,
    Student,
    Upload,
    ApprovedIntake,
    Program,
    Institution,
)


class SyntheticDataGenerator:
    def __init__(
        self,
        db: Session,
        *,
        seed: int = 42,
        institutions: int = 40,
        students: int = 15000,
        years: tuple[str, ...] = DEFAULT_YEARS,
        ground_truth_path: Path | None = None,
        scenario_module: Any = None,
        vary_contact_formats: bool = False,
    ) -> None:
        self.db = db
        self.ground_truth_path = ground_truth_path or GROUND_TRUTH_PATH
        # The demo seed writes the sign-in sheet at the repo root; any other run (tests,
        # the robustness dataset) writes its own beside its ground truth, so it can never
        # overwrite the demo operator's passwords.
        if self.ground_truth_path == GROUND_TRUTH_PATH:
            self.credentials_path = CREDENTIALS_PATH
        else:
            self.credentials_path = self.ground_truth_path.with_name(
                f"{self.ground_truth_path.stem}_credentials.csv"
            )
        self.scenario_module = scenario_module
        self.seed = seed
        self.institution_count = institutions
        self.student_target = students
        self.years = years
        self.rng = random.Random(seed)
        self.faker = Faker("en_IN")
        Faker.seed(seed)
        self.b = DataBuilder(self.rng, self.faker)
        self.b.vary_contact_formats = vary_contact_formats

        # Filled during generation.
        self.clean_institution_id: int | None = None
        self.programs_by_institution: dict[int, list[dict[str, Any]]] = {}
        self.cohorts: dict[tuple[int, str], list[int]] = {}  # (program_id, year) -> student ids
        # A TFW or PMSSS student keeps that seat category when they move into year 2,
        # so progression has to know how each cohort member was admitted.
        self.admission_type_of: dict[tuple[int, str, int], str] = {}
        # Everyone enrolled in a programme-year, with the year of study they are in, so
        # progression can advance each student by one year rather than assuming year 2.
        self.enrolled_of: dict[tuple[int, str], list[tuple[int, int]]] = {}
        self.upload_by: dict[tuple[int, str], dict[str, Any]] = {}
        self.demo_students: list[dict[str, Any]] = []

    # ================================================================== public

    def run(self) -> dict[str, Any]:
        self.wipe()
        self.build_institutions()
        self.build_uploads()
        self.build_base_cohorts()
        self.inject_scenarios()
        self.persist()
        ground_truth = self.write_ground_truth()
        return ground_truth

    # ================================================================== phases

    def wipe(self) -> None:
        for model in WIPE_ORDER:
            self.db.execute(delete(model))
        self.db.commit()
        if self.db.bind is not None and self.db.bind.dialect.name == "sqlite":
            for table in ("sqlite_sequence",):
                try:
                    self.db.execute(text(f"DELETE FROM {table}"))
                except Exception:  # pragma: no cover - table may not exist
                    self.db.rollback()
        self.db.commit()

    # ---------------------------------------------------------------- structure

    def build_institutions(self) -> None:
        stems = list(vocab.NAME_STEMS)
        self.rng.shuffle(stems)
        for index in range(self.institution_count):
            stem = stems[index % len(stems)]
            suffix = vocab.INSTITUTION_SUFFIXES[index % len(vocab.INSTITUTION_SUFFIXES)]
            state, region = vocab.STATES[index % len(vocab.STATES)]
            institution = self.b.add_institution(
                name=f"{stem} {suffix}",
                state=state,
                region=region,
                type_=self.rng.choice(vocab.INSTITUTION_TYPES),
            )

            programs: list[dict[str, Any]] = []
            branches = list(vocab.BTECH_BRANCHES)
            self.rng.shuffle(branches)
            for branch in branches[: self.rng.randint(2, 3)]:
                programs.append(
                    self.b.add_program(
                        institution_id=institution["id"],
                        course="B.Tech",
                        branch=branch,
                        level="UG",
                        mode="regular",
                    )
                )
            for course, branch, level, mode in vocab.PG_PROGRAMS:
                if self.rng.random() < 0.55:
                    programs.append(
                        self.b.add_program(
                            institution_id=institution["id"],
                            course=course,
                            branch=branch,
                            level=level,
                            mode=mode,
                        )
                    )
            # Roughly a quarter of institutions also run an online / ODL programme.
            if self.rng.random() < 0.25:
                course, branch, level, mode = self.rng.choice(vocab.ONLINE_PROGRAMS)
                programs.append(
                    self.b.add_program(
                        institution_id=institution["id"],
                        course=course,
                        branch=branch,
                        level=level,
                        mode=mode,
                    )
                )

            # CLAUDE.md section on data generation: 3-6 programmes per institution.
            while len(programs) < 3:
                branch = branches[len(programs) % len(branches)]
                if any(p["branch"] == branch and p["course"] == "B.Tech" for p in programs):
                    branch = branches[(len(programs) + 3) % len(branches)]
                programs.append(
                    self.b.add_program(
                        institution_id=institution["id"],
                        course="B.Tech",
                        branch=branch,
                        level="UG",
                        mode="regular",
                    )
                )

            for program in programs:
                intake = self.rng.choice(vocab.INTAKE_CHOICES)
                for year in self.years:
                    self.b.add_intake(
                        program_id=program["id"],
                        academic_year=year,
                        intake=intake,
                        caps=supernumerary_caps(intake),
                    )
                program["intake"] = intake
            self.programs_by_institution[institution["id"]] = programs

        # The last institution is the clean "model" one (no issues at all).
        self.clean_institution_id = self.b.institutions[-1]["id"]

    def build_uploads(self) -> None:
        """One upload per institution per year, timed inside the reporting window."""
        for institution in self.b.institutions:
            for year in self.years:
                calendar = year_calendar(year)
                deadline = calendar.reporting_deadline
                earliest = datetime.combine(calendar.admission_window_end, datetime.min.time())
                span_hours = max(int((deadline - earliest).total_seconds() // 3600), 1)
                created_at = earliest + timedelta(hours=self.rng.randint(1, span_hours))
                upload = self.b.add_upload(
                    institution_id=institution["id"],
                    filename=f"students_{year.replace('-', '_')}.xlsx",
                    academic_year=year,
                    created_at=created_at,
                    rows_total=0,
                    rows_ok=0,
                    rows_error=0,
                    quality_score=self.rng.randint(74, 98),
                )
                self.upload_by[(institution["id"], year)] = upload

    # ---------------------------------------------------------------- cohorts

    def _total_year1_capacity(self) -> int:
        return sum(
            program["intake"]
            for program in self.b.programs
            if program["mode"] == "regular" and program["course"] == "B.Tech"
        ) + sum(
            program["intake"]
            for program in self.b.programs
            if program["mode"] == "regular" and program["course"] != "B.Tech"
        )

    def build_base_cohorts(self) -> None:
        """Year-1 cohorts for each year, plus progression of the first year's cohort.

        The per-programme fill ratio is scaled so the total number of distinct students
        lands near ``--students``.
        """
        capacity = max(self._total_year1_capacity(), 1)
        # Supernumerary seats, lateral entrants and the injected scenarios add students on
        # top of the base cohorts, so aim the base cohorts a little under the target.
        per_year_target = self.student_target / len(self.years) * BASE_COHORT_SHARE
        base_fill = min(max(per_year_target / capacity, 0.35), 0.95)

        first_year, *later_years = self.years

        for year in self.years:
            calendar = year_calendar(year)
            for institution in self.b.institutions:
                for program in self.programs_by_institution[institution["id"]]:
                    upload = self.upload_by[(institution["id"], year)]
                    # Wide spread: some programmes nearly full, others half empty.
                    fill = min(base_fill * self.rng.uniform(0.6, 1.35), 0.99)
                    if program["mode"] == "online":
                        fill *= 0.6
                    count = max(int(program["intake"] * fill), 5)
                    cohort: list[int] = []
                    enrolled: list[tuple[int, int]] = []
                    for _ in range(count):
                        nationality, apaar_status, registry_status = self._identity_mix()
                        student_id = self.b.add_student(
                            nationality_status=nationality,
                            apaar_status=apaar_status,
                            registry_status=registry_status,
                            # A small share of first-year entrants are under 18
                            # (CLAUDE.md section 5 rule 12: parental consent).
                            minor=self.rng.random() < 0.015,
                        )
                        admitted_on = self.b.random_date_in(
                            calendar.admission_window_start, calendar.admission_window_end
                        )
                        self.b.add_enrolment(
                            student_id=student_id,
                            program=program,
                            academic_year=year,
                            year_of_study=1,
                            admission_type="regular",
                            admitted_on=admitted_on,
                            created_at=upload["created_at"]
                            + timedelta(seconds=self.rng.randint(0, 3600)),
                            upload_id=upload["id"],
                            registry_status=registry_status,
                        )
                        cohort.append(student_id)
                        self.admission_type_of[(program["id"], year, student_id)] = "regular"
                        enrolled.append((student_id, 1))
                    for student_id in self._add_supernumerary(program, year, upload, calendar):
                        cohort.append(student_id)
                        enrolled.append((student_id, 1))
                    self.cohorts[(program["id"], year)] = cohort

                    # In the first year of data, also seed a second-year cohort: these
                    # students were admitted before our records begin. Without them the
                    # first year has one cohort and the second has two, which would show
                    # up as every branch doubling year on year.
                    if year == first_year:
                        senior_count = max(int(count * self.rng.uniform(0.85, 1.0)), 4)
                        for _ in range(senior_count):
                            nationality, apaar_status, registry_status = self._identity_mix()
                            student_id = self.b.add_student(
                                nationality_status=nationality,
                                apaar_status=apaar_status,
                                registry_status=registry_status,
                            )
                            self.b.add_enrolment(
                                student_id=student_id,
                                program=program,
                                academic_year=year,
                                year_of_study=2,
                                admission_type="regular",
                                admitted_on=None,
                                created_at=upload["created_at"],
                                upload_id=upload["id"],
                            )
                            self.admission_type_of[(program["id"], year, student_id)] = "regular"
                            enrolled.append((student_id, 2))
                    self.enrolled_of[(program["id"], year)] = enrolled

        # Progression: first-year cohort moves into year 2 in the next year.
        for index, year in enumerate(later_years):
            previous_year = self.years[index]
            calendar = year_calendar(year)
            for program in self.b.programs:
                previous_enrolled = self.enrolled_of.get((program["id"], previous_year), [])
                if not previous_enrolled:
                    continue
                previous_cohort = [student_id for student_id, _year in previous_enrolled]
                year_of_study_of = dict(previous_enrolled)
                upload = self.upload_by[(program["institution_id"], year)]
                # A small, normal share leaves with a proper status.
                leavers = set(
                    self.rng.sample(
                        previous_cohort, k=max(int(len(previous_cohort) * 0.03), 1)
                    )
                )
                for student_id in previous_cohort:
                    admission_type = self.admission_type_of.get(
                        (program["id"], previous_year, student_id), "regular"
                    )
                    next_year_of_study = min(year_of_study_of.get(student_id, 1) + 1, 4)
                    if student_id in leavers:
                        self.b.add_enrolment(
                            student_id=student_id,
                            program=program,
                            academic_year=year,
                            year_of_study=next_year_of_study,
                            admission_type=admission_type,
                            status=self.rng.choice(["dropped", "migrated", "cancelled"]),
                            admitted_on=None,
                            created_at=upload["created_at"],
                            upload_id=upload["id"],
                        )
                        continue
                    self.b.add_enrolment(
                        student_id=student_id,
                        program=program,
                        academic_year=year,
                        year_of_study=next_year_of_study,
                        admission_type=admission_type,
                        admitted_on=None,
                        created_at=upload["created_at"]
                        + timedelta(seconds=self.rng.randint(0, 3600)),
                        upload_id=upload["id"],
                    )
                    self.enrolled_of.setdefault((program["id"], year), []).append(
                        (student_id, next_year_of_study)
                    )
                # Lateral entrants join in year 2, inside the lateral window.
                if program["mode"] == "regular" and self.rng.random() < 0.5:
                    caps = supernumerary_caps(program["intake"])
                    lateral_count = self.rng.randint(1, max(caps.get("lateral", 1) // 2, 1))
                    for _ in range(lateral_count):
                        student_id = self.b.add_student()
                        self.b.add_enrolment(
                            student_id=student_id,
                            program=program,
                            academic_year=year,
                            year_of_study=2,
                            admission_type="lateral",
                            admitted_on=self.b.random_date_in(
                                calendar.admission_window_start, calendar.lateral_window_end
                            ),
                            created_at=upload["created_at"],
                            upload_id=upload["id"],
                        )

    def _identity_mix(self) -> tuple[str, str, str]:
        """Nationality / apaar_status / registry status for an ordinary student.

        ~2% are FN or OCI with ``apaar_status = not_applicable`` (valid, not an error),
        and ~1% carry a registry problem (scenario E).
        """
        roll = self.rng.random()
        if roll < 0.012:
            return self.rng.choice(("fn", "oci")), "not_applicable", "skipped"
        if roll < 0.027:
            return "nri", "pending", "skipped"
        return "indian", "provided", "match"

    def _add_supernumerary(
        self,
        program: dict[str, Any],
        year: str,
        upload: dict[str, Any],
        calendar: Any,
    ) -> list[int]:
        """Valid supernumerary admissions, always within the configured caps.

        Returns the student ids, which join the cohort so they progress into year 2 like
        anyone else instead of silently vanishing.
        """
        created: list[int] = []
        if program["mode"] != "regular":
            return created
        caps = supernumerary_caps(program["intake"])
        # How often a programme uses a quota at all, and how much of its cap it uses.
        # FN/PIO/OCI admissions are genuinely rare: most institutions have none, so a
        # 2% FN/OCI population overall comes mostly from the identity mix, not here.
        usage = {
            "tfw": (0.65, 0.5),
            "fn_pio_oci": (0.12, 0.2),
            "pmsss": (0.45, 0.5),
        }
        for admission_type in ("tfw", "fn_pio_oci", "pmsss"):
            cap = caps.get(admission_type, 0)
            probability, cap_share = usage[admission_type]
            if cap <= 0 or self.rng.random() > probability:
                continue
            # Always within the configured cap: only scenario A injects a breach.
            ceiling = max(int(cap * cap_share), 1)
            count = self.rng.randint(1, ceiling)
            for _ in range(count):
                if admission_type == "fn_pio_oci":
                    student_id = self.b.add_student(
                        nationality_status=self.rng.choice(("fn", "oci")),
                        apaar_status="not_applicable",
                        registry_status="skipped",
                    )
                else:
                    student_id = self.b.add_student()
                self.b.add_enrolment(
                    student_id=student_id,
                    program=program,
                    academic_year=year,
                    year_of_study=1,
                    admission_type=admission_type,
                    admitted_on=self.b.random_date_in(
                        calendar.admission_window_start, calendar.admission_window_end
                    ),
                    created_at=upload["created_at"],
                    upload_id=upload["id"],
                )
                self.admission_type_of[(program["id"], year, student_id)] = admission_type
                created.append(student_id)
        return created

    # ---------------------------------------------------------------- scenarios

    def inject_scenarios(self) -> None:
        if self.scenario_module is not None:
            self.scenario_module.inject_all(self)
            return
        from datagen import scenarios

        scenarios.inject_all(self)

    # ---------------------------------------------------------------- persistence

    def persist(self) -> None:
        """Bulk-insert everything, then recount upload row totals."""
        self.db.bulk_insert_mappings(Institution, self.b.institutions)
        self.db.bulk_insert_mappings(Program, self.b.programs)
        self.db.bulk_insert_mappings(ApprovedIntake, self.b.intakes)
        self.db.bulk_insert_mappings(Upload, self.b.uploads)
        self.db.bulk_insert_mappings(Student, self.b.students)
        self.db.bulk_insert_mappings(Vault, self.b.vault_rows)
        self.db.bulk_insert_mappings(Enrolment, self.b.enrolments)
        self.db.commit()

        counts: dict[int, int] = {}
        for enrolment in self.b.enrolments:
            if enrolment["upload_id"] is not None:
                counts[enrolment["upload_id"]] = counts.get(enrolment["upload_id"], 0) + 1
        for upload in self.db.query(Upload).all():
            rows_ok = counts.get(upload.id, 0)
            errors = int(rows_ok * self.rng.uniform(0.0, 0.03))
            upload.rows_ok = rows_ok
            upload.rows_error = errors
            upload.rows_total = rows_ok + errors
        self.db.commit()

        self.populate_registry()
        self.create_users_and_demo_data()

    def populate_registry(self) -> None:
        """Insert every issued APAAR into the mock registry's own database.

        ``not_found`` identities are deliberately left out, and ``mismatch`` ones are
        inserted under a different name so the registry disagrees with the college.
        """
        from registry.app.db import IssuedApaar, SessionLocal, init_registry_db

        init_registry_db()
        session = SessionLocal()
        try:
            session.query(IssuedApaar).delete()
            rows: list[dict[str, Any]] = []
            for identity in self.b.raw:
                if not identity.apaar or identity.registry_status in ("not_found", "invalid_format", "skipped"):
                    continue
                if identity.registry_status == "mismatch":
                    rows.append(
                        {
                            "apaar": identity.apaar,
                            "name": self.faker.name(),  # registry disagrees with the college
                            "dob": identity.dob.isoformat(),
                        }
                    )
                else:
                    rows.append(
                        {
                            "apaar": identity.apaar,
                            "name": identity.name,
                            "dob": identity.dob.isoformat(),
                        }
                    )
            session.bulk_insert_mappings(IssuedApaar, rows)
            session.commit()
        finally:
            session.close()

    def create_users_and_demo_data(self) -> None:
        from datagen import demo

        demo.create_users_and_demo_data(self)


    # ---------------------------------------------------------------- live injection




    # ---------------------------------------------------------------- ground truth

    def write_ground_truth(self) -> dict[str, Any]:
        by_scenario: dict[str, list[dict[str, Any]]] = {}
        for case in self.b.cases:
            by_scenario.setdefault(case.scenario, []).append(case.as_dict())

        clean = next(
            (inst for inst in self.b.institutions if inst["id"] == self.clean_institution_id), None
        )
        payload = {
            "generated_at": datetime.now().replace(microsecond=0).isoformat(),
            "seed": self.seed,
            "years": list(self.years),
            "counts": {
                "institutions": len(self.b.institutions),
                "programs": len(self.b.programs),
                "students": len(self.b.students),
                "enrolments": len(self.b.enrolments),
                "uploads": len(self.b.uploads),
                "labelled_cases": len(self.b.cases),
            },
            "clean_institution": {"id": clean["id"], "name": clean["name"]} if clean else None,
            "demo_students": self.demo_students,
            "scenarios": by_scenario,
        }
        self.ground_truth_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return payload


def generate(
    db: Session,
    *,
    seed: int = 42,
    institutions: int = 40,
    students: int = 15000,
    years: tuple[str, ...] = DEFAULT_YEARS,
    ground_truth_path: Path | None = None,
    scenario_module: Any = None,
    vary_contact_formats: bool = False,
) -> dict[str, Any]:
    generator = SyntheticDataGenerator(
        db,
        seed=seed,
        institutions=institutions,
        students=students,
        years=years,
        ground_truth_path=ground_truth_path,
        scenario_module=scenario_module,
        vary_contact_formats=vary_contact_formats,
    )
    return generator.run()
