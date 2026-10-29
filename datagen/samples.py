"""Deliberately messy sample uploads for the live demo (Step 5 of docs/PLAN.md).

Three files with the kind of mess a real college spreadsheet has: odd headers, mixed
date formats, blank rows, stray totals, bad APAAR IDs. One of them pushes a programme
past its approved intake, which is scenario A on stage.
"""
from __future__ import annotations

import json
import random
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from app.core.config import REPO_ROOT
from app.services.rules import year_calendar
from datagen.generator import GROUND_TRUTH_PATH

SAMPLES_DIR = REPO_ROOT / "samples"
YEAR = "2026-27"
# Who the sample files' valid APAAR IDs belong to (clean name and DOB), for the registry.
IDENTITIES_PATH = SAMPLES_DIR / "sample_identities.json"

# Headers a college actually sends us — nothing matches our canonical field names.
MESSY_HEADERS = {
    "apaar_id": "APAAR No.",
    "student_name": "Stu. Nm",
    "gender": "M/F",
    "dob": "D.O.B",
    "category": "Cat.",
    "nationality_status": "Nationality",
    "phone": "Mob No",
    "email": "Email id",
    "guardian_phone": "Parent Contact",
    "course": "Course",
    "branch": "Branch / Spec.",
    "academic_year": "Acad Yr",
    "year_of_study": "Yr",
    "admission_type": "Adm. Type",
    "admission_date": "Adm Dt",
    "status": "Status",
}


def _mixed_date(value: date, rng: random.Random) -> str:
    return rng.choice(
        [
            value.strftime("%d/%m/%Y"),
            value.strftime("%Y-%m-%d"),
            value.strftime("%d-%m-%Y"),
            value.strftime("%d.%m.%Y"),
        ]
    )


def _row(
    rng: random.Random,
    names: list[str],
    calendar,
    *,
    index: int,
    course: str = "B.Tech",
    branch: str = "CSE",
    facts: list[dict[str, str]] | None = None,
) -> dict[str, str]:
    dob = date(rng.randint(2004, 2008), rng.randint(1, 12), rng.randint(1, 28))
    admitted = calendar.admission_window_start + timedelta(
        days=rng.randint(0, (calendar.admission_window_end - calendar.admission_window_start).days)
    )
    row = {
        MESSY_HEADERS["apaar_id"]: f"{rng.randint(10**11, 10**12 - 1)}",
        MESSY_HEADERS["student_name"]: names[index % len(names)],
        MESSY_HEADERS["gender"]: rng.choice(["M", "F", "Male", "female"]),
        MESSY_HEADERS["dob"]: _mixed_date(dob, rng),
        MESSY_HEADERS["category"]: rng.choice(["GEN", "OBC-NCL", "SC", "ST", "EWS", "obc"]),
        MESSY_HEADERS["nationality_status"]: rng.choice(["Indian", "indian", "INDIAN"]),
        MESSY_HEADERS["phone"]: f"+91 {rng.randint(70000, 99999)} {rng.randint(10000, 99999)}",
        MESSY_HEADERS["email"]: f"student{index}@example.invalid",
        MESSY_HEADERS["guardian_phone"]: f"0{rng.randint(7000000000, 9999999999)}",
        MESSY_HEADERS["course"]: course,
        MESSY_HEADERS["branch"]: branch,
        MESSY_HEADERS["academic_year"]: rng.choice(["2026-27", "2026-2027"]),
        MESSY_HEADERS["year_of_study"]: "1",
        MESSY_HEADERS["admission_type"]: rng.choice(["Regular", "regular", "REGULAR"]),
        MESSY_HEADERS["admission_date"]: _mixed_date(admitted, rng),
        MESSY_HEADERS["status"]: rng.choice(["Admitted", "admitted"]),
    }
    if facts is not None:
        # The clean facts behind the messy cells, for printing these students' documents.
        category = row[MESSY_HEADERS["category"]]
        facts.append(
            {
                "apaar": row[MESSY_HEADERS["apaar_id"]],
                "name": row[MESSY_HEADERS["student_name"]],
                "dob": dob.isoformat(),
                "category": "OBC-NCL" if category.lower() == "obc" else category,
                "admission_type": "regular",
                "nationality_status": "indian",
                "academic_year": YEAR,
            }
        )
    return row


def register_sample_identities(session=None) -> int:
    """Add the sample files' valid APAAR IDs to the mock registry. Returns how many were added.

    Registry entries only: nobody is enrolled. IDs already in the registry are left alone.
    Pass a session to target a specific registry database (tests do).
    """
    from registry.app.db import IssuedApaar, SessionLocal, init_registry_db

    identities = json.loads(IDENTITIES_PATH.read_text(encoding="utf-8"))
    own = session is None
    if own:
        init_registry_db()
        session = SessionLocal()
    try:
        added = 0
        for item in identities:
            if session.get(IssuedApaar, item["apaar"]) is None:
                session.add(IssuedApaar(apaar=item["apaar"], name=item["name"], dob=item["dob"]))
                added += 1
        session.commit()
        return added
    finally:
        if own:
            session.close()


def _excess_target() -> dict | None:
    """Pick a real programme that this upload will actually push past its intake.

    Looks for a programme sitting 10-60 seats under its approved intake for the current
    year, so the demo story is "upload -> EXCESS_INTAKE appears", not "excess was
    already there". Returns None if the database has not been seeded yet.
    """
    try:
        from sqlalchemy import func, select

        from app.core.db import SessionLocal
        from app.models.core import ApprovedIntake, Enrolment, Institution, Program, User
    except ImportError:  # pragma: no cover - defensive
        return None

    clean_id = None
    if GROUND_TRUTH_PATH.exists():
        data = json.loads(GROUND_TRUTH_PATH.read_text())
        clean_id = (data.get("clean_institution") or {}).get("id")

    db = SessionLocal()
    try:
        admitted = {
            (program_id, year): count
            for program_id, year, count in db.execute(
                select(Enrolment.program_id, Enrolment.academic_year, func.count())
                .where(
                    Enrolment.admission_type == "regular",
                    Enrolment.year_of_study == 1,
                    Enrolment.status.in_(("admitted", "completed")),
                )
                .group_by(Enrolment.program_id, Enrolment.academic_year)
            ).all()
        }
        rows = db.execute(
            select(Program, ApprovedIntake, Institution)
            .join(ApprovedIntake, ApprovedIntake.program_id == Program.id)
            .join(Institution, Institution.id == Program.institution_id)
            .where(
                ApprovedIntake.academic_year == YEAR,
                Program.mode == "regular",
                Program.course == "B.Tech",
            )
            .order_by(Program.id)
        ).all()

        best: dict | None = None
        for program, intake_row, institution in rows:
            if clean_id is not None and institution.id == clean_id:
                continue
            headroom = intake_row.intake - admitted.get((program.id, YEAR), 0)
            if not 10 <= headroom <= 60:
                continue
            # Prefer a larger programme: a 120-seat course makes a better demo than a 30.
            better = best is None or (intake_row.intake, -headroom) > (
                best["approved_intake"],
                -best["headroom"],
            )
            if better:
                best = {
                    "institution_id": institution.id,
                    "institution_name": institution.name,
                    "program_id": program.id,
                    "course": program.course,
                    "branch": program.branch,
                    "approved_intake": intake_row.intake,
                    "admitted": admitted.get((program.id, YEAR), 0),
                    "headroom": headroom,
                }
        if best is not None:
            login = db.execute(
                select(User.username).where(
                    User.role == "institution", User.institution_id == best["institution_id"]
                )
            ).scalar_one_or_none()
            best["institution_login"] = login or "the institution account"
        return best
    finally:
        db.close()


def write_samples(*, seed: int = 42) -> list[Path]:
    """Write the three sample files. Returns the paths written."""
    rng = random.Random(seed + 7)
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    calendar = year_calendar(YEAR)
    names = [
        "Rahul Sharma", "Aisha Khan", "Vikram Patel", "Sneha Iyer", "Arjun Nair",
        "Priya Menon", "Rohit Verma", "Fatima Shaikh", "Karthik Reddy", "Neha Gupta",
        "Imran Qureshi", "Divya Pillai", "Sandeep Yadav", "Meera Joshi", "Tarun Bose",
    ]
    written: list[Path] = []

    # ---------------------------------------------------------------- 1. excess intake
    target = _excess_target()
    excess_by = 25
    if target:
        row_count = target["headroom"] + excess_by
        course, branch = target["course"], target["branch"]
    else:
        row_count, course, branch = 70, "B.Tech", "CSE"
    facts: list[dict[str, str]] = []
    rows = [
        _row(rng, names, calendar, index=i, course=course, branch=branch, facts=facts)
        for i in range(row_count)
    ]
    # Blank rows and a stray total line in the middle of the sheet.
    rows.insert(12, {key: "" for key in rows[0]})
    rows.insert(40, {key: "" for key in rows[0]})
    rows.append(
        {**{key: "" for key in rows[0]}, MESSY_HEADERS["student_name"]: f"TOTAL = {row_count}"}
    )
    frame = pd.DataFrame(rows)
    path = SAMPLES_DIR / "sample_1_excess_intake.xlsx"
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        frame.to_excel(writer, index=False, sheet_name="Sheet1")
    written.append(path)

    # ------------------------------------------- 4. documents for the first few of those students
    from datagen.documents import write_sample_zip

    zip_path = write_sample_zip(facts[:5], path=SAMPLES_DIR / "sample_4_documents.zip", seed=seed)
    if zip_path is not None:
        written.append(zip_path)

    # ---------------------------------------------------------------- 2. dirty errors
    facts_2: list[dict[str, str]] = []
    rows = [_row(rng, names, calendar, index=i, facts=facts_2) for i in range(45)]
    rows[3][MESSY_HEADERS["apaar_id"]] = "12345678"          # too short
    rows[5][MESSY_HEADERS["apaar_id"]] = "1234-5678-12AB"    # not digits
    rows[7][MESSY_HEADERS["apaar_id"]] = ""                   # missing
    rows[7][MESSY_HEADERS["nationality_status"]] = "Foreign National"
    rows[9][MESSY_HEADERS["dob"]] = "31/02/2006"              # impossible date
    rows[11][MESSY_HEADERS["dob"]] = ""
    rows[13][MESSY_HEADERS["admission_date"]] = "15/11/2026"  # after the cutoff
    rows[15][MESSY_HEADERS["student_name"]] = ""              # missing name
    rows[17][MESSY_HEADERS["nationality_status"]] = "Indian"
    rows[17][MESSY_HEADERS["apaar_id"]] = ""                  # not_applicable but Indian
    duplicate = dict(rows[20])
    rows.insert(21, duplicate)                                 # duplicate inside the upload
    rows.insert(30, {key: "" for key in rows[0]})
    frame = pd.DataFrame(rows)
    path = SAMPLES_DIR / "sample_2_dirty_errors.xlsx"
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        frame.to_excel(writer, index=False, sheet_name="Admissions 2026-27")
    written.append(path)

    # The registry must know every correctly formatted APAAR in sample 1 and 2, so the demo
    # uploads raise only the flags they are about. Deliberately invalid IDs were overwritten
    # in the rows above and are left out. Nobody is enrolled: these are registry entries only.
    sent = {
        str(cell).strip()
        for row in rows
        for cell in [row[MESSY_HEADERS["apaar_id"]]]
        if str(cell).strip().isdigit() and len(str(cell).strip()) == 12
    }
    identities = {
        fact["apaar"]: {"apaar": fact["apaar"], "name": fact["name"], "dob": fact["dob"]}
        for fact in [*facts, *(f for f in facts_2 if f["apaar"] in sent)]
    }
    IDENTITIES_PATH.write_text(json.dumps(list(identities.values()), indent=1), encoding="utf-8")
    written.append(IDENTITIES_PATH)
    register_sample_identities()

    # ---------------------------------------------------------------- 3. garbage CSV
    path = SAMPLES_DIR / "sample_3_garbage.csv"
    path.write_text(
        "Annual Report 2026\n"
        ",,,\n"
        "Section A,,,\n"
        "notes,,,\n"
        "this file has no usable student columns at all,,,\n"
        ",,,\n",
        encoding="utf-8",
    )
    written.append(path)

    # ---------------------------------------------------------------- README for the demo
    readme = SAMPLES_DIR / "README.md"
    if target:
        excess_hint = (
            f"Upload it as **{target['institution_name']}** "
            f"(`{target['institution_login']}`): {target['course']} {target['branch']} has "
            f"{target['admitted']} of {target['approved_intake']} approved seats filled, so "
            f"{target['headroom'] + excess_by} more rows push it {excess_by} seats past intake "
            f"and raise EXCESS_INTAKE."
        )
    else:
        excess_hint = "Upload it as any institution to push a programme past its approved intake."
    readme.write_text(
        "# Sample uploads (all synthetic)\n\n"
        "Deliberately messy files for the live demo. Column headers do not match our\n"
        "canonical field names on purpose — the mapping screen has to work them out.\n\n"
        f"- `sample_1_excess_intake.xlsx` — {row_count} clean-ish rows, two blank rows and a\n"
        f"  stray `TOTAL = {row_count}` line. {excess_hint}\n"
        "- `sample_2_dirty_errors.xlsx` — short / non-numeric / missing APAAR IDs, an\n"
        "  impossible date (31/02/2006), a post-cutoff admission, a missing name, a row\n"
        "  claiming no APAAR while being Indian, and a duplicate row inside the file.\n"
        "- `sample_3_garbage.csv` — no usable columns at all. The pipeline must reject it\n"
        "  cleanly instead of crashing.\n"
        "- `sample_4_documents.zip` — the documents of the first five students in\n"
        "  `sample_1_excess_intake.xlsx`, named `<APAAR ID>_<document type>.pdf`. Upload it on\n"
        "  **Documents** after importing sample 1. Most are verified with the issuer\n"
        "  automatically; the second student's Class 12 marksheet was edited after issue\n"
        "  (rejected) and the third student's ID proof belongs to someone else (sent to an\n"
        "  AICTE officer).\n",
        encoding="utf-8",
    )
    written.append(readme)
    return written
