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


def _row(rng: random.Random, names: list[str], calendar, *, index: int) -> dict[str, str]:
    dob = date(rng.randint(2004, 2008), rng.randint(1, 12), rng.randint(1, 28))
    admitted = calendar.admission_window_start + timedelta(
        days=rng.randint(0, (calendar.admission_window_end - calendar.admission_window_start).days)
    )
    return {
        MESSY_HEADERS["apaar_id"]: f"{rng.randint(10**11, 10**12 - 1)}",
        MESSY_HEADERS["student_name"]: names[index % len(names)],
        MESSY_HEADERS["gender"]: rng.choice(["M", "F", "Male", "female"]),
        MESSY_HEADERS["dob"]: _mixed_date(dob, rng),
        MESSY_HEADERS["category"]: rng.choice(["GEN", "OBC-NCL", "SC", "ST", "EWS", "obc"]),
        MESSY_HEADERS["nationality_status"]: rng.choice(["Indian", "indian", "INDIAN"]),
        MESSY_HEADERS["phone"]: f"+91 {rng.randint(70000, 99999)} {rng.randint(10000, 99999)}",
        MESSY_HEADERS["email"]: f"student{index}@example.invalid",
        MESSY_HEADERS["guardian_phone"]: f"0{rng.randint(7000000000, 9999999999)}",
        MESSY_HEADERS["course"]: "B.Tech",
        MESSY_HEADERS["branch"]: "CSE",
        MESSY_HEADERS["academic_year"]: rng.choice(["2026-27", "2026-2027"]),
        MESSY_HEADERS["year_of_study"]: "1",
        MESSY_HEADERS["admission_type"]: rng.choice(["Regular", "regular", "REGULAR"]),
        MESSY_HEADERS["admission_date"]: _mixed_date(admitted, rng),
        MESSY_HEADERS["status"]: rng.choice(["Admitted", "admitted"]),
    }


def _ground_truth_excess_case() -> dict | None:
    if not GROUND_TRUTH_PATH.exists():
        return None
    data = json.loads(GROUND_TRUTH_PATH.read_text())
    cases = data.get("scenarios", {}).get("A_excess_intake", [])
    return cases[0] if cases else None


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
    case = _ground_truth_excess_case()
    rows = [_row(rng, names, calendar, index=i) for i in range(70)]
    # Blank rows and a stray total line in the middle of the sheet.
    rows.insert(12, {key: "" for key in rows[0]})
    rows.insert(40, {key: "" for key in rows[0]})
    rows.append({**{key: "" for key in rows[0]}, MESSY_HEADERS["student_name"]: "TOTAL = 70"})
    frame = pd.DataFrame(rows)
    path = SAMPLES_DIR / "sample_1_excess_intake.xlsx"
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        frame.to_excel(writer, index=False, sheet_name="Sheet1")
    written.append(path)

    # ---------------------------------------------------------------- 2. dirty errors
    rows = [_row(rng, names, calendar, index=i) for i in range(45)]
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
    excess_hint = (
        f"Uploading this as **{case['institution_name']}** pushes "
        f"{case['details'].get('program', 'a programme')} past its approved intake "
        f"({case['details'].get('approved_intake')} seats) and raises EXCESS_INTAKE."
        if case
        else "Uploading this as any institution pushes a programme past its approved intake."
    )
    readme.write_text(
        "# Sample uploads (all synthetic)\n\n"
        "Deliberately messy files for the live demo. Column headers do not match our\n"
        "canonical field names on purpose — the mapping screen has to work them out.\n\n"
        f"- `sample_1_excess_intake.xlsx` — 70 clean-ish rows, two blank rows and a stray\n"
        f"  `TOTAL = 70` line. {excess_hint}\n"
        "- `sample_2_dirty_errors.xlsx` — short / non-numeric / missing APAAR IDs, an\n"
        "  impossible date (31/02/2006), a post-cutoff admission, a missing name, a row\n"
        "  claiming no APAAR while being Indian, and a duplicate row inside the file.\n"
        "- `sample_3_garbage.csv` — no usable columns at all. The pipeline must reject it\n"
        "  cleanly instead of crashing.\n",
        encoding="utf-8",
    )
    written.append(readme)
    return written
