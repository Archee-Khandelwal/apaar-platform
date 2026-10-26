"""In-memory builders for synthetic rows, written to the DB in bulk.

Rows are accumulated as plain dicts with explicit primary keys and inserted with
``bulk_insert_mappings``, which keeps a 15,000-student seed to a few seconds.

Privacy: contact details only ever reach the database as HMAC hashes, and raw
APAAR / name / DOB go to the encrypted vault — the same crypto module the API uses
(CLAUDE.md section 5 rules 1 and 2).
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from app.core.crypto import (
    hash_email,
    hash_name,
    hash_phone,
    hmac_hash,
    is_minor,
    mask_apaar,
    mask_name,
    vault_encrypt,
)


@dataclass
class RawIdentity:
    """Clear-text identity, used for the vault and the mock registry only."""

    student_id: int
    apaar: str | None
    name: str
    dob: date
    registry_status: str


@dataclass
class GroundTruthCase:
    """One injected, labelled case. ``key`` is what evaluate.py matches flags on."""

    scenario: str
    flag_type: str
    key_kind: str  # student | enrolment | program_year | institution_year
    key: str
    institution_id: int | None = None
    institution_name: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario,
            "flag_type": self.flag_type,
            "key_kind": self.key_kind,
            "key": self.key,
            "institution_id": self.institution_id,
            "institution_name": self.institution_name,
            "details": self.details,
        }


class DataBuilder:
    """Accumulates institutions, programs, students, enrolments, uploads and labels."""

    def __init__(self, rng: random.Random, faker: Any) -> None:
        self.rng = rng
        self.faker = faker

        self.institutions: list[dict[str, Any]] = []
        self.programs: list[dict[str, Any]] = []
        self.intakes: list[dict[str, Any]] = []
        self.students: list[dict[str, Any]] = []
        self.vault_rows: list[dict[str, Any]] = []
        self.enrolments: list[dict[str, Any]] = []
        self.uploads: list[dict[str, Any]] = []
        self.raw: list[RawIdentity] = []
        self.cases: list[GroundTruthCase] = []

        # When set, every generated contact is written in a random real-world format
        # before hashing (spaces, +91 prefixes, uppercase emails). The normalised value
        # must be identical, which is what the robustness run checks.
        self.vary_contact_formats = False
        self._next_ids: dict[str, int] = {}
        self._used_apaar: set[str] = set()
        self._used_phone: set[str] = set()

    # ------------------------------------------------------------------ ids

    def next_id(self, table: str) -> int:
        value = self._next_ids.get(table, 0) + 1
        self._next_ids[table] = value
        return value

    # ------------------------------------------------------------------ identifiers

    def new_apaar(self, *, digits: int = 12) -> str:
        while True:
            low = 10 ** (digits - 1)
            value = str(self.rng.randint(low, 10 * low - 1))
            if value not in self._used_apaar:
                self._used_apaar.add(value)
                return value

    def sequential_apaars(self, count: int, *, gap: int = 1) -> list[str]:
        """A run of near-consecutive APAAR IDs (scenario G)."""
        start = self.rng.randint(100_000_000_000, 999_999_999_000 - count * gap)
        run: list[str] = []
        value = start
        for _ in range(count):
            while str(value) in self._used_apaar:
                value += 1
            run.append(str(value))
            self._used_apaar.add(str(value))
            value += self.rng.choice([gap, gap, gap + 1])
        return run

    def format_phone(self, phone: str) -> str:
        """Write the same number the way a college spreadsheet might."""
        if not self.vary_contact_formats:
            return phone
        return self.rng.choice(
            [
                phone,
                f"+91 {phone[:5]} {phone[5:]}",
                f"+91-{phone}",
                f"0{phone}",
                f"{phone[:3]} {phone[3:6]} {phone[6:]}",
                f" {phone} ",
                f"91{phone}",
            ]
        )

    def format_email(self, email: str) -> str:
        if not self.vary_contact_formats:
            return email
        return self.rng.choice([email, email.upper(), email.capitalize(), f"  {email} "])

    def new_phone(self) -> str:
        while True:
            value = f"{self.rng.choice('6789')}{self.rng.randint(10**8, 10**9 - 1)}"
            if value not in self._used_phone:
                self._used_phone.add(value)
                return value

    # ------------------------------------------------------------------ institutions

    def add_institution(
        self, *, name: str, state: str, region: str, type_: str, district: str | None = None
    ) -> dict[str, Any]:
        row = {
            "id": self.next_id("institutions"),
            "aicte_permanent_id": f"1-{self.rng.randint(1_000_000_000, 9_999_999_999)}",
            "name": name,
            "state": state,
            "region": region,
            "type": type_,
            "district": district,
            "created_at": datetime(2020, 6, 1),
        }
        self.institutions.append(row)
        return row

    def add_program(
        self, *, institution_id: int, course: str, branch: str, level: str, mode: str
    ) -> dict[str, Any]:
        row = {
            "id": self.next_id("programs"),
            "institution_id": institution_id,
            "course": course,
            "branch": branch,
            "level": level,
            "mode": mode,
            "created_at": datetime(2020, 6, 1),
        }
        self.programs.append(row)
        return row

    def add_intake(
        self, *, program_id: int, academic_year: str, intake: int, caps: dict[str, int]
    ) -> dict[str, Any]:
        row = {
            "id": self.next_id("approved_intake"),
            "program_id": program_id,
            "academic_year": academic_year,
            "intake": intake,
            "supernumerary_caps": caps,
            "created_at": datetime(2020, 6, 1),
        }
        self.intakes.append(row)
        return row

    # ------------------------------------------------------------------ students

    def add_student(
        self,
        *,
        name: str | None = None,
        dob: date | None = None,
        apaar: str | None = None,
        apaar_status: str = "provided",
        nationality_status: str = "indian",
        registry_status: str = "match",
        guardian_phone: str | None = None,
        phone: str | None = None,
        email: str | None = None,
        gender: str | None = None,
        category: str | None = None,
        minor: bool = False,
    ) -> int:
        """Create one student row (+ vault row). Returns the student id."""
        student_id = self.next_id("students")
        name = name or self.faker.name()
        if dob is None:
            birth_year = self.rng.randint(2009, 2010) if minor else self.rng.randint(2003, 2007)
            dob = date(birth_year, self.rng.randint(1, 12), self.rng.randint(1, 28))

        if apaar_status == "provided" and apaar is None:
            apaar = self.new_apaar()

        guardian_phone = self.format_phone(guardian_phone or self.new_phone())
        phone = self.format_phone(phone or self.new_phone())
        email = self.format_email(
            email or f"{name.split()[0].lower()}.{student_id}@example.invalid"
        )

        self.students.append(
            {
                "id": student_id,
                "apaar_hash": hmac_hash(apaar) if apaar else None,
                "apaar_masked": mask_apaar(apaar) if apaar else "XXXX-XXXX-XXXX",
                "apaar_status": apaar_status,
                "name_masked": mask_name(name),
                "name_hash": hash_name(name),
                "dob_hash": hmac_hash(dob.isoformat()),
                "gender": gender or self.rng.choices(("M", "F", "O"), (0.66, 0.335, 0.005))[0],
                "category": category or self.rng.choices(
                    ("GEN", "OBC-NCL", "SC", "ST", "EWS"), (0.38, 0.30, 0.15, 0.07, 0.10)
                )[0],
                "nationality_status": nationality_status,
                "dob_year": dob.year,
                "is_minor": is_minor(dob, as_of=date(2026, 10, 26)),
                "phone_hash": hash_phone(phone),
                "email_hash": hash_email(email),
                "guardian_phone_hash": hash_phone(guardian_phone),
                "registry_status": registry_status if apaar else "skipped",
                "created_at": datetime(2026, 1, 1),
            }
        )
        self.vault_rows.append(
            {
                "id": student_id,
                "student_id": student_id,
                "apaar_enc": vault_encrypt(apaar) if apaar else None,
                "name_enc": vault_encrypt(name),
                "dob_enc": vault_encrypt(dob.isoformat()),
                "created_at": datetime(2026, 1, 1),
            }
        )
        self.raw.append(
            RawIdentity(
                student_id=student_id,
                apaar=apaar,
                name=name,
                dob=dob,
                registry_status=registry_status if apaar else "skipped",
            )
        )
        return student_id

    # ------------------------------------------------------------------ enrolments

    def add_enrolment(
        self,
        *,
        student_id: int,
        program: dict[str, Any],
        academic_year: str,
        year_of_study: int = 1,
        admission_type: str = "regular",
        status: str = "admitted",
        admitted_on: date | None = None,
        created_at: datetime | None = None,
        upload_id: int | None = None,
        registry_status: str | None = None,
        student_confirmation: str = "unconfirmed",
    ) -> dict[str, Any]:
        row = {
            "id": self.next_id("enrolments"),
            "student_id": student_id,
            "program_id": program["id"],
            "institution_id": program["institution_id"],
            "academic_year": academic_year,
            "year_of_study": year_of_study,
            "admission_type": admission_type,
            "status": status,
            "admitted_on": admitted_on,
            "upload_id": upload_id,
            "version": 1,
            "student_confirmation": student_confirmation,
            "registry_status": registry_status,
            "created_at": created_at or datetime(2026, 10, 1),
        }
        self.enrolments.append(row)
        return row

    def add_upload(
        self,
        *,
        institution_id: int,
        filename: str,
        academic_year: str,
        created_at: datetime,
        rows_total: int,
        rows_ok: int,
        rows_error: int,
        quality_score: int,
        uploaded_by: str | None = None,
    ) -> dict[str, Any]:
        row = {
            "id": self.next_id("uploads"),
            "institution_id": institution_id,
            "filename": filename,
            "state": "completed",
            "academic_year": academic_year,
            "rows_total": rows_total,
            "rows_ok": rows_ok,
            "rows_error": rows_error,
            "rows_warning": 0,
            "blank_rows_skipped": 0,
            "quality_score": quality_score,
            "column_mapping": {},
            "proposed_mapping": [],
            "issues": [],
            "registry_summary": {},
            "raw_path": None,
            "uploaded_by": uploaded_by,
            "created_at": created_at,
        }
        self.uploads.append(row)
        return row

    # ------------------------------------------------------------------ labels

    def label(self, case: GroundTruthCase) -> None:
        self.cases.append(case)

    # ------------------------------------------------------------------ helpers

    def random_date_in(self, start: date, end: date) -> date:
        span = (end - start).days
        return start + timedelta(days=self.rng.randint(0, max(span, 0)))
