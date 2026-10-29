"""Step 6: the upload pipeline — mapping, validation, idempotency, quality report."""
from __future__ import annotations

import io
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import REPO_ROOT
from app.models.core import ApprovedIntake, Enrolment, Flag, Institution, Program, Student, Vault
from app.services.rules import supernumerary_caps, year_calendar
from app.services.upload import read_table, resolve_program

YEAR = "2026-27"
SAMPLES = REPO_ROOT / "samples"

HEADERS = [
    "Sr. No.", "APAAR No.", "Stu. Nm", "M/F", "D.O.B", "Cat.", "Nationality",
    "Mob No", "Email id", "Parent Contact", "Course", "Branch / Spec.",
    "Acad Yr", "Yr", "Adm. Type", "Adm Dt", "Status", "Remarks",
]


@pytest.fixture()
def program(db: Session, two_institutions) -> Program:
    """The first institution's B.Tech CSE programme, with intake 30 and 19 admitted."""
    first, _ = two_institutions
    program = db.execute(select(Program).where(Program.institution_id == first.id)).scalars().first()
    db.add(
        ApprovedIntake(
            program_id=program.id,
            academic_year=YEAR,
            intake=30,
            supernumerary_caps=supernumerary_caps(30),
        )
    )
    calendar = year_calendar(YEAR)
    for index in range(19):
        student = Student(
            apaar_masked=f"XXXX-XXXX-{index:04d}", name_masked="S**** E.", dob_year=2006
        )
        db.add(student)
        db.flush()
        db.add(
            Enrolment(
                student_id=student.id,
                program_id=program.id,
                institution_id=first.id,
                academic_year=YEAR,
                year_of_study=1,
                admission_type="regular",
                status="admitted",
                admitted_on=calendar.admission_window_start,
            )
        )
    db.commit()
    return program


def _csv(rows: list[dict[str, str]], headers: list[str] | None = None) -> bytes:
    import csv

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=headers or HEADERS)
    writer.writeheader()
    for row in rows:
        writer.writerow({key: row.get(key, "") for key in (headers or HEADERS)})
    return buffer.getvalue().encode()


def _row(index: int, program: Program, *, apaar: str | None = None, **overrides) -> dict[str, str]:
    calendar = year_calendar(YEAR)
    admitted = calendar.admission_window_start + timedelta(days=index % 30)
    row = {
        "Sr. No.": str(index + 1),
        "APAAR No.": apaar if apaar is not None else f"9{index:011d}",
        "Stu. Nm": f"Student Number{index}",
        "M/F": "Male" if index % 2 else "female",
        "D.O.B": f"{(index % 28) + 1:02d}/03/2006",
        "Cat.": "obc",
        "Nationality": "Indian",
        "Mob No": f"+91 9{index:09d}",
        "Email id": f"student{index}@example.invalid",
        "Parent Contact": f"08{index:09d}",
        "Course": program.course,
        "Branch / Spec.": "CSE",
        "Acad Yr": "2026-2027",
        "Yr": "1",
        "Adm. Type": "Regular",
        "Adm Dt": admitted.strftime("%d/%m/%Y"),
        "Status": "Admitted",
        "Remarks": "-",
    }
    row.update(overrides)
    return row


def _upload(client: TestClient, headers: dict[str, str], content: bytes, name: str) -> dict:
    response = client.post(
        "/institution/uploads",
        headers=headers,
        files={"file": (name, content, "text/csv")},
        data={"academic_year": YEAR},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _confirm(client: TestClient, headers: dict[str, str], upload_id: int, mapping: dict) -> dict:
    response = client.post(
        f"/institution/uploads/{upload_id}/confirm-mapping",
        headers=headers,
        json={"mapping": mapping, "defaults": {"academic_year": YEAR}},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _regular_year1(db: Session, program: Program) -> int:
    return db.scalar(
        select(func.count())
        .select_from(Enrolment)
        .where(
            Enrolment.program_id == program.id,
            Enrolment.academic_year == YEAR,
            Enrolment.admission_type == "regular",
            Enrolment.year_of_study == 1,
            Enrolment.status.in_(("admitted", "completed")),
        )
    )


# ------------------------------------------------------------------ mapping


def test_mapping_is_proposed_for_messy_headers(client: TestClient, auth, program) -> None:
    headers = auth("institution")
    body = _upload(client, headers, _csv([_row(i, program) for i in range(3)]), "messy.csv")

    assert body["state"] == "pending_mapping"
    assert body["rows_total"] == 3
    proposals = {item["source_column"]: item for item in body["proposed_mapping"]}
    assert proposals["Stu. Nm"]["field"] == "student_name"
    assert proposals["APAAR No."]["field"] == "apaar_id"
    assert proposals["D.O.B"]["field"] == "dob"
    assert proposals["Adm Dt"]["field"] == "admission_date"
    assert proposals["Parent Contact"]["field"] == "guardian_phone"
    # Columns that are not student data are left unmapped.
    assert proposals["Sr. No."]["field"] is None
    assert proposals["Remarks"]["field"] is None
    # Confidence and sample values are shown so a human can check the guess.
    assert proposals["Stu. Nm"]["confidence"] > 0.8
    assert proposals["Stu. Nm"]["sample_values"]
    assert body["unmapped_required_fields"] == []


def test_nothing_is_stored_until_the_mapping_is_confirmed(
    client: TestClient, auth, program, db: Session
) -> None:
    before = db.scalar(select(func.count()).select_from(Student))
    _upload(client, auth("institution"), _csv([_row(i, program) for i in range(3)]), "x.csv")
    assert db.scalar(select(func.count()).select_from(Student)) == before


def test_blank_rows_are_skipped(client: TestClient, auth, program) -> None:
    rows = [_row(i, program) for i in range(4)]
    rows.insert(2, {key: "" for key in HEADERS})
    body = _upload(client, auth("institution"), _csv(rows), "blanks.csv")
    assert body["rows_total"] == 4
    assert body["blank_rows_skipped"] >= 1


def test_branch_abbreviations_resolve_to_the_approved_programme(db: Session, program) -> None:
    from app.services.upload import _Context
    from app.services.registry_client import RegistryClient

    institution = db.get(Institution, program.institution_id)
    context = _Context(
        institution=institution,
        programs=[program],
        actor="test",
        registry=RegistryClient(),
    )
    assert resolve_program(context, "B.Tech", "CSE", None) is program
    assert resolve_program(context, "B.Tech", "Computer Science and Engineering", None) is program
    assert resolve_program(context, "B.Tech", "Mechanical Engineering", None) is None
    assert resolve_program(context, "MBA", "CSE", None) is None


# ------------------------------------------------------------------ validation


def test_valid_rows_are_stored_with_hashes_and_a_vault_row(
    client: TestClient, auth, program, db: Session
) -> None:
    headers = auth("institution")
    body = _upload(client, headers, _csv([_row(i, program) for i in range(5)]), "ok.csv")
    mapping = {item["source_column"]: item["field"] for item in body["proposed_mapping"]}
    report = _confirm(client, headers, body["upload_id"], mapping)

    assert report["rows_ok"] == 5
    assert report["rows_error"] == 0
    assert report["enrolments_created"] == 5
    assert report["state"] == "completed"

    student = db.execute(
        select(Student).where(Student.name_masked.like("S%")).order_by(Student.id.desc())
    ).scalars().first()
    assert student.apaar_masked.startswith("XXXX-XXXX-")
    assert len(student.guardian_phone_hash) == 64
    assert db.execute(select(Vault).where(Vault.student_id == student.id)).scalar_one() is not None


def test_invalid_rows_are_reported_with_fix_suggestions_and_not_stored(
    client: TestClient, auth, program, db: Session
) -> None:
    rows = [
        _row(0, program, **{"APAAR No.": "12345678"}),   # too short -> error
        _row(1, program, **{"D.O.B": "31/02/2006"}),     # impossible date -> error
        _row(2, program, **{"Stu. Nm": ""}),             # missing name -> error
        _row(3, program),                                 # good
        _row(4, program),                                 # good
    ]
    headers = auth("institution")
    body = _upload(client, headers, _csv(rows), "errors.csv")
    mapping = {item["source_column"]: item["field"] for item in body["proposed_mapping"]}
    report = _confirm(client, headers, body["upload_id"], mapping)

    codes = {issue["code"] for issue in report["issues"]}
    assert "INVALID_APAAR" in codes
    assert "INVALID_DATE" in codes
    assert "MISSING_REQUIRED" in codes
    assert report["rows_error"] == 3
    assert report["rows_ok"] == 2
    assert report["enrolments_created"] == 2
    assert all(issue["fix_suggestion"] for issue in report["issues"])
    # Rejected rows never reach the database.
    assert _regular_year1(db, program) == 19 + 2


def test_a_foreign_national_without_an_apaar_id_is_accepted_silently(
    client: TestClient, auth, program, db: Session
) -> None:
    """CLAUDE.md section 6: not_applicable is valid for FN/OCI and is NOT an error."""
    headers = auth("institution")
    body = _upload(
        client,
        headers,
        _csv([_row(0, program, **{"APAAR No.": "", "Nationality": "Foreign National"})]),
        "fn.csv",
    )
    mapping = {item["source_column"]: item["field"] for item in body["proposed_mapping"]}
    report = _confirm(client, headers, body["upload_id"], mapping)

    assert report["rows_ok"] == 1
    assert report["rows_error"] == 0
    assert report["issues"] == []
    student = db.execute(
        select(Student).where(Student.nationality_status == "fn")
    ).scalars().one()
    assert student.apaar_status == "not_applicable"
    assert student.apaar_hash is None


def test_an_indian_student_without_an_apaar_id_is_stored_as_pending_with_a_warning(
    client: TestClient, auth, program, db: Session
) -> None:
    headers = auth("institution")
    body = _upload(
        client,
        headers,
        _csv([_row(0, program, **{"APAAR No.": "", "Nationality": "Indian"})]),
        "pending.csv",
    )
    mapping = {item["source_column"]: item["field"] for item in body["proposed_mapping"]}
    report = _confirm(client, headers, body["upload_id"], mapping)

    assert report["rows_ok"] == 1  # 'pending' is a legitimate apaar_status, not an error
    assert report["rows_warning"] == 1
    assert "APAAR_REQUIRED" in {issue["code"] for issue in report["issues"]}
    assert db.execute(
        select(Student).where(Student.apaar_status == "pending")
    ).scalars().first() is not None


def test_claiming_not_applicable_for_an_indian_student_is_an_error(
    client: TestClient, auth, program
) -> None:
    """The real error case: an Indian student declared exempt from APAAR."""
    headers = HEADERS + ["APAAR Status"]
    rows = [
        {**_row(0, program, **{"APAAR No.": "", "Nationality": "Indian"}), "APAAR Status": "not_applicable"},
        {**_row(1, program, **{"APAAR No.": "", "Nationality": "OCI"}), "APAAR Status": "not_applicable"},
    ]
    auth_headers = auth("institution")
    body = _upload(client, auth_headers, _csv(rows, headers), "claim.csv")
    mapping = {item["source_column"]: item["field"] for item in body["proposed_mapping"]}
    assert mapping["APAAR Status"] == "apaar_status"
    report = _confirm(client, auth_headers, body["upload_id"], mapping)

    assert report["rows_error"] == 1  # the Indian row only
    assert report["rows_ok"] == 1  # the OCI row is legitimate
    codes = {issue["code"] for issue in report["issues"]}
    assert "NOT_APPLICABLE_NOT_ALLOWED" in codes


def test_late_admission_raises_a_warning_and_a_flag(
    client: TestClient, auth, program, db: Session
) -> None:
    calendar = year_calendar(YEAR)
    late = (calendar.admission_window_end + timedelta(days=20)).strftime("%d/%m/%Y")
    headers = auth("institution")
    body = _upload(client, headers, _csv([_row(0, program, **{"Adm Dt": late})]), "late.csv")
    mapping = {item["source_column"]: item["field"] for item in body["proposed_mapping"]}
    report = _confirm(client, headers, body["upload_id"], mapping)

    assert report["rows_ok"] == 1  # a warning, not a rejection
    assert "LATE_ADMISSION" in {issue["code"] for issue in report["issues"]}
    flag = db.execute(select(Flag).where(Flag.type == "LATE_ADMISSION")).scalars().first()
    assert flag is not None
    assert flag.explanation
    assert flag.evidence["admitted_on"]


def test_lateral_entry_is_moved_to_year_two(client: TestClient, auth, program, db: Session) -> None:
    headers = auth("institution")
    body = _upload(
        client, headers, _csv([_row(0, program, **{"Adm. Type": "Lateral Entry", "Yr": "1"})]), "lat.csv"
    )
    mapping = {item["source_column"]: item["field"] for item in body["proposed_mapping"]}
    report = _confirm(client, headers, body["upload_id"], mapping)

    assert "LATERAL_YEAR_MISMATCH" in {issue["code"] for issue in report["issues"]}
    enrolment = db.execute(
        select(Enrolment).where(Enrolment.admission_type == "lateral")
    ).scalars().one()
    assert enrolment.year_of_study == 2
    # And it is not counted against year-1 intake.
    assert _regular_year1(db, program) == 19


def test_duplicate_rows_inside_one_upload_are_rejected(
    client: TestClient, auth, program, db: Session
) -> None:
    row = _row(0, program)
    headers = auth("institution")
    body = _upload(client, headers, _csv([row, dict(row)]), "dupe.csv")
    mapping = {item["source_column"]: item["field"] for item in body["proposed_mapping"]}
    report = _confirm(client, headers, body["upload_id"], mapping)

    assert "DUPLICATE_IN_UPLOAD" in {issue["code"] for issue in report["issues"]}
    assert report["enrolments_created"] == 1
    assert db.execute(select(Flag).where(Flag.type == "DUPLICATE_IN_UPLOAD")).scalars().first()


# ------------------------------------------------------------------ idempotency (Step 5 review)


def test_uploading_the_same_file_twice_does_not_inflate_intake(
    client: TestClient, auth, program, db: Session
) -> None:
    """36 rows on top of 19 admitted puts a 30-seat programme exactly 25 over intake.

    Uploading the identical file again must leave it at 25 over, not 50.
    """
    headers = auth("institution")
    content = _csv([_row(i, program) for i in range(36)])
    intake = db.execute(
        select(ApprovedIntake).where(ApprovedIntake.program_id == program.id)
    ).scalar_one().intake
    assert intake == 30

    first = _upload(client, headers, content, "sample_1.csv")
    mapping = {item["source_column"]: item["field"] for item in first["proposed_mapping"]}
    first_report = _confirm(client, headers, first["upload_id"], mapping)

    assert first_report["enrolments_created"] == 36
    assert first_report["already_reported"] == 0
    assert _regular_year1(db, program) - intake == 25

    # Same file, second time.
    second = _upload(client, headers, content, "sample_1.csv")
    second_report = _confirm(client, headers, second["upload_id"], mapping)

    assert second_report["already_reported"] == 36
    assert second_report["enrolments_created"] == 0
    assert second_report["rows_error"] == 0
    assert "ALREADY_REPORTED" in second_report["issue_counts"]
    assert _regular_year1(db, program) - intake == 25, "re-upload inflated the seat count"
    assert db.scalar(select(func.count()).select_from(Enrolment).where(
        Enrolment.program_id == program.id
    )) == 19 + 36


def test_partially_overlapping_upload_only_adds_the_new_rows(
    client: TestClient, auth, program, db: Session
) -> None:
    headers = auth("institution")
    first = _upload(client, headers, _csv([_row(i, program) for i in range(10)]), "a.csv")
    mapping = {item["source_column"]: item["field"] for item in first["proposed_mapping"]}
    _confirm(client, headers, first["upload_id"], mapping)
    before = _regular_year1(db, program)

    # Rows 5-14: five already reported, five new.
    second = _upload(client, headers, _csv([_row(i, program) for i in range(5, 15)]), "b.csv")
    report = _confirm(client, headers, second["upload_id"], mapping)

    assert report["already_reported"] == 5
    assert report["enrolments_created"] == 5
    assert _regular_year1(db, program) == before + 5


def test_already_reported_rows_do_not_duplicate_students(
    client: TestClient, auth, program, db: Session
) -> None:
    headers = auth("institution")
    content = _csv([_row(i, program) for i in range(6)])
    first = _upload(client, headers, content, "c.csv")
    mapping = {item["source_column"]: item["field"] for item in first["proposed_mapping"]}
    _confirm(client, headers, first["upload_id"], mapping)
    students_after_first = db.scalar(select(func.count()).select_from(Student))

    second = _upload(client, headers, content, "c.csv")
    _confirm(client, headers, second["upload_id"], mapping)

    assert db.scalar(select(func.count()).select_from(Student)) == students_after_first


# ------------------------------------------------------------------ robustness


def test_a_garbage_file_does_not_crash(client: TestClient, auth, program) -> None:
    headers = auth("institution")
    content = (SAMPLES / "sample_3_garbage.csv").read_bytes()
    body = _upload(client, headers, content, "sample_3_garbage.csv")
    mapping = {item["source_column"]: item["field"] for item in body["proposed_mapping"]}
    # No required field can be mapped, so confirming is a clean 400, not a crash.
    response = client.post(
        f"/institution/uploads/{body['upload_id']}/confirm-mapping",
        headers=headers,
        json={"mapping": mapping, "defaults": {}},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_an_empty_file_is_rejected_cleanly(client: TestClient, auth, program) -> None:
    response = client.post(
        "/institution/uploads",
        headers=auth("institution"),
        files={"file": ("empty.csv", b"", "text/csv")},
    )
    assert response.status_code == 400


def test_an_unsupported_file_type_is_rejected(client: TestClient, auth, program) -> None:
    response = client.post(
        "/institution/uploads",
        headers=auth("institution"),
        files={"file": ("notes.pdf", b"%PDF-1.4 nonsense", "application/pdf")},
    )
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "UNSUPPORTED_FILE"


def test_reading_the_real_messy_sample_workbook() -> None:
    parse = read_table((SAMPLES / "sample_2_dirty_errors.xlsx").read_bytes(), "s2.xlsx")
    assert parse.rows
    assert "Stu. Nm" in parse.headers
    assert parse.blank_rows_skipped >= 1


def test_confirming_twice_is_a_conflict(client: TestClient, auth, program) -> None:
    headers = auth("institution")
    body = _upload(client, headers, _csv([_row(0, program)]), "once.csv")
    mapping = {item["source_column"]: item["field"] for item in body["proposed_mapping"]}
    _confirm(client, headers, body["upload_id"], mapping)
    again = client.post(
        f"/institution/uploads/{body['upload_id']}/confirm-mapping",
        headers=headers,
        json={"mapping": mapping, "defaults": {}},
    )
    assert again.status_code == 409


# ------------------------------------------------------------------ tenant isolation + RBAC


def test_another_institution_cannot_see_or_confirm_the_upload(
    client: TestClient, auth, program
) -> None:
    body = _upload(client, auth("institution"), _csv([_row(0, program)]), "mine.csv")
    other = auth("institution_other")

    assert client.get(f"/institution/uploads/{body['upload_id']}", headers=other).status_code == 404
    assert (
        client.post(
            f"/institution/uploads/{body['upload_id']}/confirm-mapping",
            headers=other,
            json={"mapping": {}, "defaults": {}},
        ).status_code
        == 404
    )
    assert client.get("/institution/uploads", headers=other).json()["total"] == 0


def test_upload_routes_require_the_institution_role(client: TestClient, auth, program) -> None:
    for role in ("aicte_officer", "student", "verifier", "admin"):
        assert client.get("/institution/uploads", headers=auth(role)).status_code == 403
        assert client.get("/institution/template", headers=auth(role)).status_code == 403


def test_upload_list_and_template(client: TestClient, auth, program) -> None:
    headers = auth("institution")
    _upload(client, headers, _csv([_row(0, program)]), "listed.csv")
    listing = client.get("/institution/uploads?page=1&page_size=10", headers=headers).json()
    assert listing["total"] == 1
    assert listing["items"][0]["filename"] == "listed.csv"

    template = client.get("/institution/template", headers=headers)
    assert template.status_code == 200
    assert "apaar_id" in template.text.splitlines()[0]


def test_errors_csv_lists_every_issue(client: TestClient, auth, program) -> None:
    headers = auth("institution")
    body = _upload(
        client, headers, _csv([_row(0, program, **{"APAAR No.": "123"}), _row(1, program)]), "e.csv"
    )
    mapping = {item["source_column"]: item["field"] for item in body["proposed_mapping"]}
    _confirm(client, headers, body["upload_id"], mapping)

    csv_text = client.get(
        f"/institution/uploads/{body['upload_id']}/errors.csv", headers=headers
    ).text
    assert "INVALID_APAAR" in csv_text
    assert csv_text.splitlines()[0].startswith("row,severity,code")


# ------------------------------------------------------------------ registry behaviour


def test_registry_down_still_stores_rows(
    client: TestClient, auth, program, db: Session, monkeypatch
) -> None:
    """CLAUDE.md Step 4 rule: an upload must not fail because the registry is offline."""
    from app.services import upload as upload_module
    from app.services.registry_client import RegistryClient, RegistryResult

    def unavailable(self, records):  # noqa: ANN001
        return [
            RegistryResult(status="source_unavailable", ref=record.ref, message="down")
            for record in records
        ]

    monkeypatch.setattr(RegistryClient, "verify_batch", unavailable)

    headers = auth("institution")
    body = _upload(client, headers, _csv([_row(i, program) for i in range(3)]), "down.csv")
    mapping = {item["source_column"]: item["field"] for item in body["proposed_mapping"]}
    report = _confirm(client, headers, body["upload_id"], mapping)

    assert report["rows_ok"] == 3
    assert report["enrolments_created"] == 3
    assert report["registry_check"]["source_unavailable"] == 3
    assert "REGISTRY_UNAVAILABLE" in report["issue_counts"]
    # No registry-disagreement flag is raised when the source was simply unreachable.
    assert db.execute(
        select(Flag).where(Flag.type.in_(("APAAR_NOT_FOUND", "APAAR_MISMATCH")))
    ).scalars().first() is None


# ------------------------------------------------------------------ quality score


def test_quality_score_rewards_clean_complete_files(client: TestClient, auth, program) -> None:
    headers = auth("institution")
    clean = _upload(client, headers, _csv([_row(i, program) for i in range(10)]), "clean.csv")
    mapping = {item["source_column"]: item["field"] for item in clean["proposed_mapping"]}
    clean_report = _confirm(client, headers, clean["upload_id"], mapping)

    dirty_rows = [_row(i, program) for i in range(10, 20)]
    for row in dirty_rows[:5]:
        row["APAAR No."] = "123"
    dirty = _upload(client, headers, _csv(dirty_rows), "dirty.csv")
    dirty_report = _confirm(client, headers, dirty["upload_id"], mapping)

    assert clean_report["quality_score"] > dirty_report["quality_score"]
    assert 0 <= dirty_report["quality_score"] <= 100


# ------------------------------------------------------------------ demo samples vs registry


def test_sample_1_raises_excess_intake_and_no_apaar_not_found(
    client: TestClient, auth, users, db: Session, monkeypatch
) -> None:
    """The demo file must show only its own story: no 'not in registry' noise."""
    import httpx
    import pandas as pd
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.services.registry_client import RegistryClient
    from app.services.users import DemoAccount, upsert_user
    from datagen.samples import IDENTITIES_PATH, register_sample_identities
    from registry.app.db import Base as RegistryBase
    from registry.app.db import get_registry_db
    from registry.app.main import app as registry_app

    # A throwaway registry holding only what the seed registers for the samples.
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    RegistryBase.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, expire_on_commit=False)
    with maker() as session:
        assert register_sample_identities(session) > 0

    def override():
        with maker() as session:
            yield session

    registry_app.dependency_overrides[get_registry_db] = override
    registry_http = TestClient(registry_app)

    def bridge(request: httpx.Request) -> httpx.Response:
        forwarded = registry_http.post(request.url.path, content=request.content, headers=request.headers)
        return httpx.Response(forwarded.status_code, content=forwarded.content)

    monkeypatch.setattr(
        RegistryClient,
        "_client",
        lambda self: httpx.Client(
            base_url="http://registry",
            headers={"X-API-Key": self.api_key},
            transport=httpx.MockTransport(bridge),
        ),
    )

    try:
        path = SAMPLES / "sample_1_excess_intake.xlsx"
        frame = pd.read_excel(path, dtype=str).fillna("")
        frame = frame[frame["APAAR No."].str.strip() != ""]
        # The committed file and the registry seed list must not drift apart.
        import json

        known = {item["apaar"] for item in json.loads(IDENTITIES_PATH.read_text(encoding="utf-8"))}
        assert set(frame["APAAR No."].str.strip()) <= known

        institution = Institution(
            aicte_permanent_id="1-7700112233", name="Kolhanpur College of Engineering",
            state="Maharashtra", region="West", type="private_unaided",
        )
        db.add(institution)
        db.flush()
        program = Program(
            institution_id=institution.id, course=frame["Course"].iloc[0],
            branch=frame["Branch / Spec."].iloc[0], level="UG", mode="regular",
        )
        db.add(program)
        db.flush()
        db.add(
            ApprovedIntake(
                program_id=program.id, academic_year=YEAR, intake=len(frame) - 25,
                supernumerary_caps=supernumerary_caps(len(frame) - 25),
            )
        )
        upsert_user(
            db,
            DemoAccount(
                username="kolhanpur32_admin", role="institution",
                display_name="Kolhanpur — Data Cell", label=institution.name,
                institution_id=institution.id,
            ),
            password="Test-Pass-2026",
        )
        db.commit()

        headers = auth("kolhanpur32_admin")
        body = _upload(client, headers, path.read_bytes(), path.name)
        mapping = {item["source_column"]: item["field"] for item in body["proposed_mapping"]}
        _confirm(client, headers, body["upload_id"], mapping)

        types = [flag_type for (flag_type,) in db.execute(select(Flag.type)).all()]
        assert "EXCESS_INTAKE" in types
        assert types.count("APAAR_NOT_FOUND") == 0
    finally:
        registry_app.dependency_overrides.pop(get_registry_db, None)
        registry_http.close()
