"""Degree certificates that print the APAAR ID beside the student ID (PS requirement 10).

Issued by the degree-awarding institution, only for an enrolment it reported and
marked ``completed``. The certificate prints the APAAR ID and name masked by default
(``CERTIFICATE_IDENTITY_DISPLAY=full`` prints them in full for the final print run,
which is an access to vault data and is logged). The QR always carries the masked
claims, so scanning one reveals nothing that is not already on the paper.
"""
from __future__ import annotations

import base64
import io
from datetime import datetime, timezone
from html import escape
from typing import Any

import qrcode
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.access_log import log_access
from app.core.config import settings
from app.core.crypto import vault_decrypt
from app.models.core import Enrolment, Institution, IssuedDocument, Program, Student, Vault
from app.services.documents import DocumentError, issue_document, token_for, verify_url
from app.services.pdf import LINE, MUTED, PdfDocument

KIND = "degree_certificate"
SYNTHETIC_NOTICE = "Prototype — all data is synthetic. Not an official degree certificate."


def student_number(enrolment: Enrolment, institution: Institution) -> str:
    """The student ID printed beside the APAAR ID.

    Uploads do not yet carry the institution's own roll number, so this is a stable
    platform-issued enrolment number: AICTE permanent id / entry year / enrolment id.
    """
    return f"{institution.aicte_permanent_id}/{enrolment.academic_year[:4]}/{enrolment.id:06d}"


def _program_label(program: Program) -> str:
    return f"{program.course} — {program.branch}"


def completed_enrolments(
    db: Session, *, institution_id: int, academic_year: str | None = None
) -> list[dict[str, Any]]:
    """Enrolments this institution has marked completed, with any certificate issued."""
    conditions = [Enrolment.institution_id == institution_id, Enrolment.status == "completed"]
    if academic_year:
        conditions.append(Enrolment.academic_year == academic_year)
    rows = db.execute(
        select(Enrolment, Student, Program, Institution)
        .join(Student, Student.id == Enrolment.student_id)
        .join(Program, Program.id == Enrolment.program_id)
        .join(Institution, Institution.id == Enrolment.institution_id)
        .where(*conditions)
        .order_by(Enrolment.academic_year.desc(), Enrolment.id)
    ).all()
    documents = {
        document.enrolment_id: document
        for document in db.execute(
            select(IssuedDocument).where(
                IssuedDocument.kind == KIND,
                IssuedDocument.institution_id == institution_id,
                IssuedDocument.status == "valid",
            )
        ).scalars()
    }
    items = []
    for enrolment, student, program, institution in rows:
        document = documents.get(enrolment.id)
        items.append(
            {
                "enrolment_id": enrolment.id,
                "student_number": student_number(enrolment, institution),
                "apaar_masked": student.apaar_masked,
                "name_masked": student.name_masked,
                "program": _program_label(program),
                "academic_year": enrolment.academic_year,
                "certificate": (
                    {
                        "serial": document.serial,
                        "status": document.status,
                        "issued_at": document.created_at,
                    }
                    if document
                    else None
                ),
            }
        )
    return items


def issue_for_enrolment(
    db: Session, *, institution_id: int, enrolment_id: int, actor: str
) -> tuple[IssuedDocument, str, bool]:
    """Issue (or return the existing) certificate. Returns (document, token, created)."""
    enrolment = db.get(Enrolment, enrolment_id)
    if enrolment is None or enrolment.institution_id != institution_id:
        raise LookupError("No such enrolment for this institution.")
    if enrolment.status != "completed":
        raise DocumentError(
            "A degree certificate can only be issued for a completed enrolment. "
            "Mark the student as completed first."
        )

    existing = db.execute(
        select(IssuedDocument).where(
            IssuedDocument.kind == KIND,
            IssuedDocument.enrolment_id == enrolment_id,
            IssuedDocument.status == "valid",
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing, token_for(existing), False

    student = db.get(Student, enrolment.student_id)
    program = db.get(Program, enrolment.program_id)
    institution = db.get(Institution, institution_id)
    claims = {
        "apaar": student.apaar_masked if student.apaar_status == "provided" else "not applicable",
        "sid": student_number(enrolment, institution),
        "name": student.name_masked,
        "prog": _program_label(program),
        "level": program.level,
        "yr": enrolment.academic_year,
        "inst": institution.name,
        "aicte_id": institution.aicte_permanent_id,
    }
    document, token = issue_document(
        db,
        kind=KIND,
        claims=claims,
        student_id=student.id,
        institution_id=institution_id,
        enrolment_id=enrolment_id,
        academic_year=enrolment.academic_year,
        actor=actor,
        role="institution",
    )
    return document, token, True


def printed_identity(db: Session, *, document: IssuedDocument, actor: str) -> dict[str, str]:
    """APAAR and name as printed. Full values come from the vault, and are logged."""
    claims = document.claims
    if settings.certificate_identity_display != "full":
        return {"apaar": claims["apaar"], "name": claims["name"]}

    vault = db.execute(
        select(Vault).where(Vault.student_id == document.student_id)
    ).scalar_one_or_none()
    log_access(
        db,
        actor=actor,
        role="institution",
        action="degree_certificate_printed",
        target=f"student:{document.student_id}",
        student_id=document.student_id,
        reason=f"Full identity printed on degree certificate {document.serial}.",
    )
    apaar = vault_decrypt(vault.apaar_enc) if vault and vault.apaar_enc else None
    return {
        "apaar": f"{apaar[:4]}-{apaar[4:8]}-{apaar[8:]}" if apaar else claims["apaar"],
        "name": (vault_decrypt(vault.name_enc) if vault and vault.name_enc else None) or claims["name"],
    }


def _issued_on(document: IssuedDocument) -> str:
    issued = datetime.fromtimestamp(document.claims["iat"], tz=timezone.utc)
    return issued.strftime("%d %B %Y")


def render_pdf(document: IssuedDocument, token: str, identity: dict[str, str]) -> bytes:
    claims = document.claims
    pdf = PdfDocument(title=f"Degree certificate {document.serial}")
    width = pdf.width
    accent = (0.11, 0.30, 0.85)

    pdf.rect(28, 28, width - 56, pdf.height - 56, stroke=accent, line_width=2)
    pdf.rect(36, 36, width - 72, pdf.height - 72, stroke=LINE, line_width=0.75)
    pdf.rect(56, 56, width - 112, 22, fill=(1.0, 0.95, 0.78))
    pdf.text(width / 2, 71, SYNTHETIC_NOTICE, size=9, color=(0.47, 0.21, 0.06), align="center")

    pdf.text(width / 2, 130, claims["inst"].upper(), size=15, weight="bold", align="center")
    pdf.text(width / 2, 148, f"AICTE permanent id {claims['aicte_id']}", size=9, color=MUTED, align="center")
    pdf.text(width / 2, 210, "DEGREE CERTIFICATE", size=26, weight="bold", color=accent, align="center")

    y = pdf.paragraph(
        80, 260, "This is to certify that", width=width - 160, size=12, color=MUTED, align="center"
    )
    pdf.text(width / 2, y + 16, identity["name"], size=22, weight="bold", align="center")
    y = pdf.paragraph(
        80,
        y + 50,
        f"has completed the programme {claims['prog']} ({claims['level']}) and has been "
        f"awarded the degree in the academic year {claims['yr']}.",
        width=width - 160,
        size=12,
        align="center",
    )

    rows = (
        ("APAAR ID", identity["apaar"]),
        ("Student ID", claims["sid"]),
        ("Programme", claims["prog"]),
        ("Academic year", claims["yr"]),
        ("Certificate serial", document.serial),
        ("Date of issue", _issued_on(document)),
    )
    y += 24
    for label, value in rows:
        pdf.text(110, y, label, size=10, color=MUTED)
        pdf.text(250, y, str(value), size=11, weight="bold")
        pdf.line(110, y + 8, width - 110, y + 8)
        y += 26

    qr_size = 130
    qr_top = pdf.height - 110 - qr_size
    pdf.qr(80, qr_top, qr_size, verify_url(token))
    pdf.paragraph(
        230,
        qr_top + 20,
        "Scan to verify. The QR carries a digital signature over the details above, "
        "and the verification page also reports whether the certificate has been revoked.",
        width=width - 310,
        size=9,
        color=MUTED,
    )
    pdf.text(230, qr_top + 100, f"Verify at {settings.web_url}/verify", size=9, color=MUTED)
    pdf.line(width - 230, qr_top + qr_size - 6, width - 80, qr_top + qr_size - 6, color=MUTED)
    pdf.text(width - 155, qr_top + qr_size + 8, "Controller of Examinations", size=9, color=MUTED, align="center")
    return pdf.to_bytes()


def _qr_data_uri(data: str) -> str:
    buffer = io.BytesIO()
    qrcode.make(data, border=2).save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def render_html(document: IssuedDocument, token: str, identity: dict[str, str]) -> str:
    claims = document.claims
    rows = "".join(
        f"<tr><th>{escape(label)}</th><td>{escape(str(value))}</td></tr>"
        for label, value in (
            ("APAAR ID", identity["apaar"]),
            ("Student ID", claims["sid"]),
            ("Programme", claims["prog"]),
            ("Academic year", claims["yr"]),
            ("Certificate serial", document.serial),
            ("Date of issue", _issued_on(document)),
        )
    )
    url = verify_url(token)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Degree certificate {escape(document.serial)}</title>
<style>
  body {{ font-family: Georgia, "Times New Roman", serif; color: #0f172a; margin: 0; background: #f8fafc; }}
  .sheet {{ max-width: 760px; margin: 24px auto; background: #fff; border: 3px double #1d4ed8;
            padding: 40px 48px; text-align: center; }}
  .banner {{ background: #fef3c7; color: #78350f; padding: 6px 10px; border-radius: 6px;
             font: 12px system-ui, sans-serif; }}
  h1 {{ color: #1d4ed8; letter-spacing: .08em; font-size: 30px; margin: 28px 0 8px; }}
  .inst {{ font-size: 18px; font-weight: bold; text-transform: uppercase; margin-top: 24px; }}
  .muted {{ color: #475569; font: 13px system-ui, sans-serif; }}
  .name {{ font-size: 26px; font-weight: bold; margin: 8px 0 16px; }}
  table {{ margin: 24px auto; border-collapse: collapse; text-align: left; font: 14px system-ui, sans-serif; }}
  th {{ color: #475569; font-weight: 500; padding: 6px 24px 6px 0; }}
  td {{ font-weight: 600; padding: 6px 0; border-bottom: 1px solid #e2e8f0; }}
  .verify {{ display: flex; gap: 20px; align-items: center; text-align: left; margin-top: 24px; }}
  .verify img {{ width: 140px; height: 140px; }}
  @media print {{ body {{ background: #fff; }} .sheet {{ margin: 0; }} }}
</style>
</head>
<body>
<div class="sheet">
  <div class="banner">{escape(SYNTHETIC_NOTICE)}</div>
  <div class="inst">{escape(claims['inst'])}</div>
  <div class="muted">AICTE permanent id {escape(claims['aicte_id'])}</div>
  <h1>DEGREE CERTIFICATE</h1>
  <p class="muted">This is to certify that</p>
  <div class="name">{escape(identity['name'])}</div>
  <p>has completed the programme {escape(claims['prog'])} ({escape(claims['level'])}) and has been
     awarded the degree in the academic year {escape(claims['yr'])}.</p>
  <table>{rows}</table>
  <div class="verify">
    <img src="{_qr_data_uri(url)}" alt="Verification QR code">
    <p class="muted">Scan to verify. The QR carries a digital signature over the details above,
      and the verification page also reports whether the certificate has been revoked.<br>
      <a href="{escape(url)}">Open the verification page</a></p>
  </div>
</div>
</body>
</html>
"""
