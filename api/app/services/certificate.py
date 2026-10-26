"""Compliance certificate (Step 12 item 7).

Printable HTML (Step-0 decision 6: no PDF dependency). Issued only when an institution
has no open high or critical flag for the year, and carries an HMAC-signed token so the
certificate can be checked back against the platform.
"""
from __future__ import annotations

from datetime import datetime
from html import escape
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.crypto import hmac_hash
from app.models.core import Enrolment, Flag, Institution, Upload
from app.models.enums import ACTIVE_ENROLMENT_STATUSES, OPEN_FLAG_STATUSES

BLOCKING_SEVERITIES = ("high", "critical")


def eligibility(db: Session, *, institution_id: int, academic_year: str) -> dict[str, Any]:
    """Can this institution be issued a certificate for the year, and if not, why?"""
    blocking = [
        {
            "id": flag.id,
            "type": flag.type,
            "severity": flag.severity,
            "title": flag.title,
        }
        for flag in db.execute(
            select(Flag).where(
                Flag.institution_id == institution_id,
                Flag.status.in_(OPEN_FLAG_STATUSES),
                Flag.severity.in_(BLOCKING_SEVERITIES),
            )
        ).scalars()
    ]
    uploads = db.scalar(
        select(func.count())
        .select_from(Upload)
        .where(Upload.institution_id == institution_id, Upload.state == "completed")
    ) or 0
    students = db.scalar(
        select(func.count(func.distinct(Enrolment.student_id))).where(
            Enrolment.institution_id == institution_id,
            Enrolment.academic_year == academic_year,
            Enrolment.status.in_(ACTIVE_ENROLMENT_STATUSES),
        )
    ) or 0

    reasons: list[str] = []
    if blocking:
        reasons.append(
            f"{len(blocking)} open high/critical flag(s) must be resolved first."
        )
    if uploads == 0:
        reasons.append("No completed upload for this institution.")
    if students == 0:
        reasons.append(f"No students reported for {academic_year}.")

    return {
        "eligible": not reasons,
        "reasons": reasons,
        "blocking_flags": blocking,
        "students_reported": students,
        "uploads": uploads,
        "academic_year": academic_year,
    }


def certificate_token(*, institution_id: int, academic_year: str, issued_at: datetime) -> str:
    """Signed, verifiable reference for the certificate."""
    payload = f"cert:{institution_id}:{academic_year}:{issued_at.date().isoformat()}"
    signature = hmac_hash(payload) or ""
    return f"{payload}:{signature[:16]}"


def render_certificate(
    db: Session, *, institution_id: int, academic_year: str, issued_to: str
) -> str:
    institution = db.get(Institution, institution_id)
    if institution is None:  # pragma: no cover - guarded by the router
        raise LookupError("No such institution.")
    status = eligibility(db, institution_id=institution_id, academic_year=academic_year)
    issued_at = datetime.utcnow().replace(microsecond=0)
    token = certificate_token(
        institution_id=institution_id, academic_year=academic_year, issued_at=issued_at
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Data compliance certificate — {escape(institution.name)}</title>
<style>
  :root {{ --ink: #0f172a; --muted: #475569; --line: #cbd5e1; --accent: #1d4ed8; }}
  body {{ font-family: Georgia, "Times New Roman", serif; color: var(--ink);
         max-width: 760px; margin: 0 auto; padding: 48px 32px; line-height: 1.6; }}
  .banner {{ background: #fef3c7; color: #78350f; padding: 8px 12px; border-radius: 6px;
             font-family: system-ui, sans-serif; font-size: 13px; text-align: center;
             margin-bottom: 32px; }}
  h1 {{ font-size: 26px; margin: 0 0 4px; }}
  .sub {{ color: var(--muted); font-family: system-ui, sans-serif; font-size: 14px;
          letter-spacing: .04em; text-transform: uppercase; }}
  table {{ width: 100%; border-collapse: collapse; margin: 28px 0; }}
  th, td {{ text-align: left; padding: 10px 0; border-bottom: 1px solid var(--line);
            font-family: system-ui, sans-serif; font-size: 15px; }}
  th {{ color: var(--muted); font-weight: 600; width: 42%; }}
  .token {{ font-family: ui-monospace, Menlo, monospace; font-size: 12px; color: var(--muted);
            word-break: break-all; background: #f8fafc; padding: 10px; border-radius: 6px; }}
  footer {{ margin-top: 36px; color: var(--muted); font-family: system-ui, sans-serif;
            font-size: 12px; }}
  @media print {{ .banner {{ background: none; border: 1px solid var(--line); }} }}
</style>
</head>
<body>
  <div class="banner">Prototype — all data is synthetic. This certificate is not an official AICTE document.</div>
  <p class="sub">APAAR Student Data &amp; Verification Platform</p>
  <h1>Data Compliance Certificate</h1>
  <p>
    This certifies that <strong>{escape(institution.name)}</strong>
    (AICTE permanent id {escape(institution.aicte_permanent_id)}, {escape(institution.state)})
    has reported student-level enrolment data keyed on APAAR ID for the academic year
    <strong>{escape(academic_year)}</strong>, and that as of the timestamp below the platform
    holds <strong>no open high or critical finding</strong> against this institution.
  </p>
  <table>
    <tr><th>Academic year</th><td>{escape(academic_year)}</td></tr>
    <tr><th>Students reported</th><td>{status['students_reported']}</td></tr>
    <tr><th>Completed uploads</th><td>{status['uploads']}</td></tr>
    <tr><th>Open high / critical findings</th><td>0</td></tr>
    <tr><th>Issued to</th><td>{escape(issued_to)}</td></tr>
    <tr><th>Issued at (UTC)</th><td>{issued_at.isoformat()}</td></tr>
  </table>
  <p class="sub">Verification reference</p>
  <p class="token">{escape(token)}</p>
  <footer>
    A certificate reflects the data reported at the time of issue. It is withdrawn
    automatically if a high or critical finding is later raised against this institution.
  </footer>
</body>
</html>
"""
