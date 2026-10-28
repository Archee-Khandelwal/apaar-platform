"""AICTE master records: the approvals AICTE itself holds (Phase 6).

Two CSV/Excel imports, done by AICTE and never by an institution:

``institutions``  aicte_permanent_id, academic_year, status (approved | no_admission |
                  not_approved), reference (optional)
``programmes``    aicte_permanent_id, course, branch, academic_year, intake, status
                  (approved | withdrawn), level (optional, UG default), mode (optional,
                  regular default)

Each row is validated on its own; a bad row is reported and skipped, never fatal. A
programme AICTE approves that the institution has not reported yet is created, so the
reconciliation can compare against it. Afterwards the reconciliation is recomputed for the
institutions touched.
"""
from __future__ import annotations

import io
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import log_audit
from app.models.core import ApprovedIntake, Institution, InstitutionApproval, MasterImport, Program
from app.services.reconciliation import reconcile
from app.services.rules import supernumerary_caps

KINDS = ("institutions", "programmes")
INSTITUTION_STATUSES = ("approved", "no_admission", "not_approved")
PROGRAMME_STATUSES = ("approved", "withdrawn")
LEVELS = ("UG", "PG", "Diploma")
MODES = ("regular", "online")
MAX_ROWS = 20000
MAX_ISSUES_KEPT = 200

REQUIRED: dict[str, tuple[str, ...]] = {
    "institutions": ("aicte_permanent_id", "academic_year", "status"),
    "programmes": ("aicte_permanent_id", "course", "branch", "academic_year", "intake", "status"),
}


class MasterImportError(ValueError):
    """The file as a whole cannot be read (not a row problem)."""


def _frame(data: bytes, filename: str) -> pd.DataFrame:
    name = filename.lower()
    try:
        if name.endswith((".xlsx", ".xlsm")):
            frame = pd.read_excel(io.BytesIO(data), dtype=str, engine="openpyxl")
        elif name.endswith(".csv"):
            frame = pd.read_csv(io.BytesIO(data), dtype=str, encoding="utf-8-sig", keep_default_na=False)
        else:
            raise MasterImportError("Upload a .csv or .xlsx file.")
    except MasterImportError:
        raise
    except Exception as exc:  # unreadable or corrupt file
        raise MasterImportError(f"The file could not be read: {exc.__class__.__name__}.") from exc
    if len(frame) > MAX_ROWS:
        raise MasterImportError(f"At most {MAX_ROWS} rows per import.")
    frame.columns = [str(column).strip().lower().replace(" ", "_") for column in frame.columns]
    return frame.fillna("")


def _text(row: pd.Series, column: str) -> str:
    return str(row.get(column, "")).strip()


def _valid_year(value: str) -> bool:
    parts = value.split("-")
    return (
        len(parts) == 2
        and len(parts[0]) == 4
        and len(parts[1]) == 2
        and parts[0].isdigit()
        and parts[1].isdigit()
        and int(parts[0][2:]) + 1 == int(parts[1]) % 100
    )


def _institution_row(db: Session, row: pd.Series, institutions: dict[str, Institution]) -> tuple[Institution, dict[str, Any]]:
    institution = institutions.get(_text(row, "aicte_permanent_id"))
    if institution is None:
        raise ValueError("Unknown AICTE permanent id: this institution is not in the system.")
    year, status = _text(row, "academic_year"), _text(row, "status").lower()
    if not _valid_year(year):
        raise ValueError(f"Academic year '{year}' must look like 2026-27.")
    if status not in INSTITUTION_STATUSES:
        raise ValueError(f"Status '{status}' must be one of {', '.join(INSTITUTION_STATUSES)}.")
    existing = db.execute(
        select(InstitutionApproval).where(
            InstitutionApproval.institution_id == institution.id, InstitutionApproval.academic_year == year
        )
    ).scalar_one_or_none()
    values = {"status": status, "reference": _text(row, "reference") or None, "source": "import"}
    if existing is None:
        db.add(InstitutionApproval(institution_id=institution.id, academic_year=year, **values))
    else:
        for key, value in values.items():
            setattr(existing, key, value)
    return institution, {}


def _programme_row(db: Session, row: pd.Series, institutions: dict[str, Institution]) -> tuple[Institution, dict[str, Any]]:
    institution = institutions.get(_text(row, "aicte_permanent_id"))
    if institution is None:
        raise ValueError("Unknown AICTE permanent id: this institution is not in the system.")
    year, status = _text(row, "academic_year"), _text(row, "status").lower()
    course, branch = _text(row, "course"), _text(row, "branch")
    level = _text(row, "level") or "UG"
    mode = (_text(row, "mode") or "regular").lower()
    if not _valid_year(year):
        raise ValueError(f"Academic year '{year}' must look like 2026-27.")
    if status not in PROGRAMME_STATUSES:
        raise ValueError(f"Status '{status}' must be one of {', '.join(PROGRAMME_STATUSES)}.")
    if level not in LEVELS or mode not in MODES:
        raise ValueError(f"Level must be one of {', '.join(LEVELS)} and mode one of {', '.join(MODES)}.")
    try:
        intake = int(float(_text(row, "intake")))
    except ValueError:
        raise ValueError("Intake must be a whole number.") from None
    if intake < 0 or intake > 5000:
        raise ValueError("Intake must be between 0 and 5000.")

    program = db.execute(
        select(Program).where(
            Program.institution_id == institution.id, Program.course == course, Program.branch == branch, Program.mode == mode
        )
    ).scalar_one_or_none()
    if program is None:
        program = Program(institution_id=institution.id, course=course, branch=branch, level=level, mode=mode)
        db.add(program)
        db.flush()
    record = db.execute(
        select(ApprovedIntake).where(ApprovedIntake.program_id == program.id, ApprovedIntake.academic_year == year)
    ).scalar_one_or_none()
    if record is None:
        db.add(
            ApprovedIntake(
                program_id=program.id, academic_year=year, intake=intake, status=status,
                supernumerary_caps=supernumerary_caps(intake), source="import",
            )
        )
    else:
        record.intake, record.status, record.source = intake, status, "import"
        record.supernumerary_caps = supernumerary_caps(intake)
    return institution, {}


def import_master(db: Session, *, kind: str, filename: str, data: bytes, actor: str) -> MasterImport:
    """Apply one import. Caller commits."""
    if kind not in KINDS:
        raise MasterImportError(f"kind must be one of {', '.join(KINDS)}.")
    frame = _frame(data, filename)
    missing = [column for column in REQUIRED[kind] if column not in frame.columns]
    if missing:
        raise MasterImportError(f"Missing column(s): {', '.join(missing)}.")

    institutions = {row.aicte_permanent_id: row for row in db.execute(select(Institution)).scalars()}
    handler = _institution_row if kind == "institutions" else _programme_row
    touched: set[int] = set()
    years: set[str] = set()
    issues: list[dict[str, Any]] = []
    ok = 0
    for position, (_, row) in enumerate(frame.iterrows(), start=2):  # row 1 is the header
        try:  # every check runs before the handler writes, so a bad row leaves nothing behind
            institution, _ = handler(db, row, institutions)
        except ValueError as exc:
            if len(issues) < MAX_ISSUES_KEPT:
                issues.append({"row": position, "message": str(exc)})
            continue
        touched.add(institution.id)
        years.add(_text(row, "academic_year"))
        ok += 1

    record = MasterImport(
        kind=kind, filename=filename[:255], rows_total=len(frame), rows_ok=ok,
        rows_error=len(frame) - ok, issues=issues, actor=actor,
    )
    db.add(record)
    db.flush()
    for year in sorted(years):
        if len(touched) > 10:
            reconcile(db, academic_year=year)
        else:
            for institution_id in sorted(touched):
                reconcile(db, academic_year=year, institution_id=institution_id)
    log_audit(
        db, actor=actor, role="aicte_officer", action="master_records_import", target=f"master_import:{record.id}",
        payload={"kind": kind, "filename": filename[:255], "rows_ok": ok, "rows_error": len(frame) - ok},
    )
    return record


def template_csv(kind: str) -> str:
    if kind == "institutions":
        return "aicte_permanent_id,academic_year,status,reference\n1-0000000000,2026-27,approved,EOA/2026-27/0001\n"
    return "aicte_permanent_id,course,branch,academic_year,intake,status,level,mode\n1-0000000000,B.Tech,Computer Science and Engineering,2026-27,60,approved,UG,regular\n"


def master_status(db: Session) -> dict[str, Any]:
    """What the master records hold, and the latest imports, for the AICTE screen."""
    from sqlalchemy import func

    approvals = dict(db.execute(select(InstitutionApproval.status, func.count()).group_by(InstitutionApproval.status)).all())
    programmes = dict(db.execute(select(ApprovedIntake.status, func.count()).group_by(ApprovedIntake.status)).all())
    imports = db.execute(select(MasterImport).order_by(MasterImport.id.desc()).limit(10)).scalars().all()
    return {"approvals": approvals, "programme_records": programmes, "imports": imports}
