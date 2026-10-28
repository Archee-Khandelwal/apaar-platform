"""Synthetic documents for seeded students (Phase 5, step 6).

For a sample of students this module

* prints every document on their checklist as a PDF (a marksheet, an allotment letter,
  an OCI card ...) with a reference number and a QR code;
* registers the genuine ones with the mock Issuer & DigiLocker registry (hash + key facts);
* stores them as the institution's submission and runs the real verification pipeline;
* deliberately breaks some, and labels each break in ``ground_truth.json`` so
  ``make eval`` can score the pipeline.

Labelled cases (``case`` in the ground truth):

=================  ===========================================  ==================
case               what was done                                expected outcome
=================  ===========================================  ==================
genuine            issued and submitted unchanged               auto_verified
name_mismatch      someone else's genuine document submitted    needs_review
dob_mismatch       genuine, but the DOB differs from the record needs_review
tampered           marks edited after issue, file re-saved      rejected
not_at_issuer      a reference no issuer has ever issued        needs_review
resaved            same facts, file re-saved after issue        needs_review
=================  ===========================================  ==================

Every issuer name is invented, and every document says it is a synthetic sample.
"""
from __future__ import annotations

import hashlib
import io
import json
import random
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from faker import Faker
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crypto import vault_decrypt
from app.models.core import Enrolment, Institution, Program, Student, Vault
from app.services.pdf import PdfDocument
from app.services.rules import document_types, required_documents

SYNTHETIC_BANNER = "SYNTHETIC SAMPLE - NOT A REAL DOCUMENT"

# doc_type -> (issuer names, reference prefix). All invented.
ISSUERS: dict[str, tuple[tuple[str, ...], str]] = {
    "class12_marksheet": (
        (
            "Vindhyachal Council of School Examinations",
            "Sahyadri Board of Higher Secondary Education",
            "Coromandel School Examination Board",
            "Kaveri Senior Secondary Board",
        ),
        "SSE",
    ),
    "admission_letter": (("Jyotirmay Joint Seat Allotment Authority",), "JSA"),
    "id_proof": (("Bharat Resident Identity Authority (synthetic)",), "RID"),
    "diploma_marksheet": (("Board of Technical Diploma Studies (synthetic)",), "TDS"),
    "income_certificate": (("Office of the Tehsildar, Saptagiri Tehsil",), "INC"),
    "pmsss_allotment": (("Special Scholarship Allotment Cell (synthetic)",), "PMS"),
    "category_certificate": (("Office of the Sub-Divisional Magistrate, Nandivan",), "CAT"),
    "nri_status_proof": (("Overseas Residence Attestation Office (synthetic)",), "NRI"),
    "oci_card": (("Overseas Citizen Registry (synthetic)",), "OCI"),
    "passport": (("Passport Issuing Office (synthetic)",), "PPT"),
    "visa": (("Student Visa Office (synthetic)",), "VSA"),
}

CASE_EXPECTATIONS: dict[str, tuple[str, tuple[str, ...]]] = {
    "genuine": ("auto_verified", ("VERIFIED_WITH_ISSUER", "DATA_MATCHED")),
    "name_mismatch": ("needs_review", ("NAME_MISMATCH",)),
    "dob_mismatch": ("needs_review", ("DOB_MISMATCH",)),
    "tampered": ("rejected", ("ISSUER_MISMATCH", "EDITED_AFTER_ISSUE")),
    "not_at_issuer": ("needs_review", ("NOT_AT_ISSUER",)),
    "resaved": ("needs_review", ("EDITED_AFTER_ISSUE",)),
}

# How many of each broken case to inject (the rest of the sample is genuine).
CASE_COUNTS = {"name_mismatch": 8, "dob_mismatch": 5, "tampered": 8, "not_at_issuer": 8, "resaved": 4}


@dataclass
class Holder:
    student_id: int
    institution_id: int
    institution_name: str
    program: str
    academic_year: str
    admission_type: str
    category: str | None
    nationality_status: str
    name: str
    dob: str  # ISO

    @property
    def required(self) -> list[str]:
        return required_documents(
            admission_type=self.admission_type,
            category=self.category,
            nationality_status=self.nationality_status,
        )


@dataclass
class PrintedDocument:
    doc_type: str
    reference_no: str
    issuer_name: str
    holder_name: str
    holder_dob: str
    issued_on: date
    details: dict[str, Any] = field(default_factory=dict)
    modified: datetime | None = None

    def render(self) -> bytes:
        label = document_types().get(self.doc_type, {}).get("label", self.doc_type)
        issued = datetime.combine(self.issued_on, datetime.min.time()).replace(hour=10)
        pdf = PdfDocument(
            title=f"{label} {self.reference_no}",
            producer="Issuer document service (synthetic)" if self.modified is None else "PDF Editor Pro",
            created=issued,
            modified=self.modified,
        )
        pdf.text(48, 52, self.issuer_name, size=15, weight="bold")
        pdf.text(48, 74, label, size=12)
        pdf.text(48, 92, SYNTHETIC_BANNER, size=8, color=(0.6, 0.1, 0.1))
        pdf.line(48, 104, 547, 104)
        lines = [
            f"Reference No: {self.reference_no}",
            f"Name: {self.holder_name}",
            f"Date of Birth: {date.fromisoformat(self.holder_dob):%d/%m/%Y}",
        ]
        if "roll_no" in self.details:
            lines.append(f"Roll No: {self.details['roll_no']}")
        if "year" in self.details:
            lines.append(f"Year: {self.details['year']}")
        if "marks_obtained" in self.details:
            lines.append(f"Total Marks: {self.details['marks_obtained']} / {self.details['marks_total']}")
        lines += [f"Issued by: {self.issuer_name}", f"Issued on: {self.issued_on:%d/%m/%Y}"]
        for index, line in enumerate(lines):
            pdf.text(48, 132 + index * 22, line, size=11)
        pdf.qr(447, 120, 100, f"APAARDOC|ref={self.reference_no}|issuer={self.issuer_name}")
        pdf.text(447, 232, "Scan to verify with issuer", size=7)
        return pdf.to_bytes()


# --------------------------------------------------------------------------- printing


def _reference(rng: random.Random, doc_type: str, year: int) -> str:
    prefix = ISSUERS[doc_type][1]
    return f"{prefix}-{year}-{rng.randint(100000, 999999)}"


def print_document(rng: random.Random, doc_type: str, holder_name: str, holder_dob: str, academic_year: str) -> PrintedDocument:
    """A genuine document as its issuer would have printed it."""
    start_year = int(academic_year[:4])
    issuer = rng.choice(ISSUERS[doc_type][0])
    details: dict[str, Any] = {"roll_no": str(rng.randint(1000000, 9999999))}
    if doc_type in ("class12_marksheet", "diploma_marksheet"):
        issued_year = start_year if doc_type == "class12_marksheet" else start_year - 1
        total = 500 if doc_type == "class12_marksheet" else 1000
        details |= {"year": issued_year, "marks_obtained": rng.randint(int(total * 0.55), int(total * 0.97)), "marks_total": total}
        issued_on = date(issued_year, 6, rng.randint(1, 25))
    elif doc_type in ("admission_letter", "pmsss_allotment"):
        details |= {"year": start_year}
        issued_on = date(start_year, 7, rng.randint(5, 28))
    else:
        issued_on = date(start_year - rng.randint(0, 3), rng.randint(1, 12), rng.randint(1, 28))
    return PrintedDocument(
        doc_type=doc_type,
        reference_no=_reference(rng, doc_type, issued_on.year),
        issuer_name=issuer,
        holder_name=holder_name,
        holder_dob=holder_dob,
        issued_on=issued_on,
        details=details,
    )


# --------------------------------------------------------------------------- issuer registry


def issuer_record(document: PrintedDocument, data: bytes) -> dict[str, Any]:
    return {
        "reference_no": document.reference_no,
        "doc_type": document.doc_type,
        "issuer_name": document.issuer_name,
        "holder_name": document.holder_name,
        "holder_dob": document.holder_dob,
        "issued_on": document.issued_on.isoformat(),
        "sha256": hashlib.sha256(data).hexdigest(),
        "details": document.details,
        "status": "valid",
    }


def register_with_issuer(records: list[dict[str, Any]], *, replace: bool) -> None:
    from issuer.app.db import IssuedRecord, SessionLocal, init_issuer_db

    init_issuer_db()
    session = SessionLocal()
    try:
        if replace:
            session.query(IssuedRecord).delete()
        for record in records:
            session.merge(IssuedRecord(**record))
        session.commit()
    finally:
        session.close()


def in_process_issuer() -> Any:
    """An IssuerClient that calls the issuer registry's logic directly, so seeding does
    not need the service running (and is not slowed by its simulated latency)."""
    from app.services.issuer_client import IssuerClient
    from issuer.app.db import SessionLocal
    from issuer.app.main import VerifyRequest, _verify

    def handler(request: httpx.Request) -> httpx.Response:
        session = SessionLocal()
        try:
            result = _verify(session, VerifyRequest(**json.loads(request.content)))
        finally:
            session.close()
        return httpx.Response(200, json=result.model_dump())

    return IssuerClient(base_url="http://issuer.local", transport=httpx.MockTransport(handler))


# --------------------------------------------------------------------------- holders


def load_holders(db: Session, *, institution_ids: list[int] | None = None, limit: int | None = None,
                 academic_year: str = "2026-27", rng: random.Random | None = None) -> list[Holder]:
    statement = (
        select(Student, Enrolment, Institution, Program, Vault)
        .join(Enrolment, Enrolment.student_id == Student.id)
        .join(Institution, Institution.id == Enrolment.institution_id)
        .join(Program, Program.id == Enrolment.program_id)
        .join(Vault, Vault.student_id == Student.id)
        .where(Enrolment.academic_year == academic_year, Enrolment.status == "admitted",
               Enrolment.year_of_study == 1, Student.registry_status == "match")
        .order_by(Student.id)
    )
    if institution_ids is not None:
        statement = statement.where(Enrolment.institution_id.in_(institution_ids))
    rows = list(db.execute(statement).all())
    if rng is not None and limit is not None and len(rows) > limit:
        rows = sorted(rng.sample(rows, limit), key=lambda row: row[0].id)
    elif limit is not None:
        rows = rows[:limit]
    holders = []
    for student, enrolment, institution, program, vault in rows:
        name, dob = vault_decrypt(vault.name_enc), vault_decrypt(vault.dob_enc)
        if not name or not dob:
            continue
        holders.append(Holder(
            student_id=student.id, institution_id=institution.id, institution_name=institution.name,
            program=f"{program.course} {program.branch}", academic_year=enrolment.academic_year,
            admission_type=enrolment.admission_type, category=student.category,
            nationality_status=student.nationality_status, name=name, dob=dob,
        ))
    return holders


# --------------------------------------------------------------------------- breaking documents


def _break(case: str, document: PrintedDocument, holder: Holder, rng: random.Random, faker: Faker) -> tuple[PrintedDocument, PrintedDocument | None]:
    """Return (what is submitted, what the issuer holds or None)."""
    if case == "genuine":
        return document, document
    if case == "name_mismatch":
        other = PrintedDocument(**{**document.__dict__, "holder_name": faker.name()})
        return other, other
    if case == "dob_mismatch":
        shifted = (date.fromisoformat(holder.dob) + timedelta(days=rng.choice((-400, -38, 61, 365)))).isoformat()
        genuine = PrintedDocument(**{**document.__dict__, "holder_dob": shifted})
        return genuine, genuine
    if case == "tampered":
        details = dict(document.details)
        if "marks_obtained" in details:
            details["marks_obtained"] = min(details["marks_total"], details["marks_obtained"] + rng.randint(40, 90))
        else:
            details["roll_no"] = str(int(details["roll_no"]) + rng.randint(11, 99))
        edited = PrintedDocument(**{**document.__dict__, "details": details,
                                    "modified": datetime.combine(document.issued_on, datetime.min.time()) + timedelta(days=rng.randint(40, 300))})
        return edited, document
    if case == "not_at_issuer":
        return PrintedDocument(**{**document.__dict__, "reference_no": _reference(rng, document.doc_type, document.issued_on.year) + "X"}), None
    if case == "resaved":
        resaved = PrintedDocument(**{**document.__dict__, "modified": datetime.combine(document.issued_on, datetime.min.time()) + timedelta(days=rng.randint(20, 200))})
        return resaved, document
    raise ValueError(case)


def _breakable(doc_type: str, case: str) -> bool:
    # Tampering is told apart by an edited fact, so it needs a document that prints one.
    return case != "tampered" or doc_type in ("class12_marksheet", "diploma_marksheet", "admission_letter")


# --------------------------------------------------------------------------- seeding


def build_documents(gen: Any, *, students: int = 120) -> list[dict[str, Any]]:
    """Seed documents for a sample of students and return their ground-truth labels."""
    from app.services.document_verification import verify_document
    from app.services.student_documents import store_document

    db: Session = gen.db
    rng = random.Random(gen.seed + 2026)
    faker = Faker("en_IN")
    faker.seed_instance(gen.seed + 2026)
    excluded = {gen.clean_institution_id, getattr(gen, "demo_document_institution_id", None)}
    eligible = [inst["id"] for inst in gen.b.institutions if inst["id"] not in excluded]
    holders = load_holders(db, institution_ids=eligible, limit=students, rng=rng)

    plan: list[tuple[Holder, str, str]] = [(holder, doc_type, "genuine") for holder in holders for doc_type in holder.required]
    for case, count in CASE_COUNTS.items():
        candidates = [index for index, (_, doc_type, current) in enumerate(plan)
                      if current == "genuine" and _breakable(doc_type, case)]
        for index in rng.sample(candidates, min(count, len(candidates))):
            holder, doc_type, _ = plan[index]
            plan[index] = (holder, doc_type, case)

    issued: list[dict[str, Any]] = []
    submissions: list[tuple[Holder, str, str, bytes]] = []
    for holder, doc_type, case in plan:
        genuine = print_document(rng, doc_type, holder.name, holder.dob, holder.academic_year)
        submitted, at_issuer = _break(case, genuine, holder, rng, faker)
        if at_issuer is not None:
            issued.append(issuer_record(at_issuer, at_issuer.render()))
        submissions.append((holder, doc_type, case, submitted.render()))
    register_with_issuer(issued, replace=True)

    issuer = in_process_issuer()
    labels: list[dict[str, Any]] = []
    for holder, doc_type, case, data in submissions:
        document = store_document(
            db, institution_id=holder.institution_id, student_id=holder.student_id, doc_type=doc_type,
            filename=f"{doc_type}.pdf", data=data, actor="seed", channel="zip",
        )
        verify_document(db, document, issuer=issuer)
        expected, reasons = CASE_EXPECTATIONS[case]
        labels.append({
            "key": f"{holder.student_id}|{doc_type}",
            "document_id": document.id,
            "case": case,
            "institution_id": holder.institution_id,
            "institution_name": holder.institution_name,
            "expected_status": expected,
            "expected_reasons": list(reasons),
        })
    db.commit()
    return labels


# --------------------------------------------------------------------------- demo ZIP


def write_sample_zip(students: list[dict[str, Any]], *, path: Path, seed: int = 42) -> Path | None:
    """The ZIP the demo college uploads right after ``sample_1_excess_intake.xlsx``: the
    documents of the first few students in that sheet, matched by APAAR ID. One marksheet
    was edited after issue and one ID proof belongs to someone else, so the officer's
    review queue has something real to decide.

    ``students``: dicts with apaar, name, dob (ISO), category, admission_type,
    nationality_status, academic_year.
    """
    if not students:
        return None
    rng = random.Random(seed + 77)
    faker = Faker("en_IN")
    faker.seed_instance(seed + 77)
    cases = {(1, "class12_marksheet"): "tampered", (2, "id_proof"): "name_mismatch"}
    issued: list[dict[str, Any]] = []
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for index, student in enumerate(students):
            holder = Holder(
                student_id=0, institution_id=0, institution_name="", program="",
                academic_year=student["academic_year"], admission_type=student["admission_type"],
                category=student.get("category"), nationality_status=student["nationality_status"],
                name=student["name"], dob=student["dob"],
            )
            for doc_type in holder.required:
                case = cases.get((index, doc_type), "genuine")
                genuine = print_document(rng, doc_type, holder.name, holder.dob, holder.academic_year)
                submitted, at_issuer = _break(case, genuine, holder, rng, faker)
                if at_issuer is not None:
                    issued.append(issuer_record(at_issuer, at_issuer.render()))
                archive.writestr(f"{student['apaar']}_{doc_type}.pdf", submitted.render())
    register_with_issuer(issued, replace=False)
    path.write_bytes(buffer.getvalue())
    return path
