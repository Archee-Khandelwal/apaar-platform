"""Document verification (Phase 5).

Four independent checks, then one decision:

1. **Extraction** — what the document says (``document_extraction``).
2. **Data match** — does it say the same as the submitted student record? Name by fuzzy
   match (rapidfuzz, >= 90), date of birth exactly.
3. **Issuer check** — does the issuer (board, counselling authority, immigration office,
   via the mock DigiLocker registry) know this reference, and is this the document it
   issued? Verified with issuer / Not found at issuer / Details mismatch / Issuer
   unavailable.
4. **Tamper check** — the upload hash is re-checked, and PDF metadata showing an edit
   after the document's issue date is called out.

``decide`` turns the findings into Auto-verified, Needs officer review or Rejected, and
every outcome carries its reasons. Officers resolve the review queue with a logged reason.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from rapidfuzz import fuzz
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.access_log import log_access
from app.core.audit import log_audit
from app.core.crypto import vault_decrypt, vault_encrypt
from app.models.core import Institution, Student, StudentDocument, Vault
from app.services.document_extraction import extract
from app.services.issuer_client import IssuerClient, IssuerResult
from app.services.rules import document_types
from app.services.student_documents import verify_integrity

NAME_THRESHOLD = 90

ISSUER_LABELS = {
    "verified": "Verified with issuer",
    "not_found": "Not found at issuer",
    "mismatch": "Details mismatch",
    "revoked": "Revoked by issuer",
    "unavailable": "Issuer unavailable",
    "not_checked": "Not checked",
}

# Reasons that reject a document outright; any other warning sends it to an officer.
REJECTING = {"STORAGE_TAMPERED", "ISSUER_MISMATCH", "ISSUER_REVOKED"}
REVIEW_STATUSES = ("needs_review", "rejected", "auto_verified", "verified", "pending")


def _reason(code: str, message: str, severity: str = "warning") -> dict[str, str]:
    return {"code": code, "message": message, "severity": severity}


# --------------------------------------------------------------------------- identity


def _submitted_identity(db: Session, student_id: int) -> dict[str, str | None]:
    vault = db.execute(select(Vault).where(Vault.student_id == student_id)).scalar_one_or_none()
    if vault is None:
        return {"name": None, "dob": None}
    return {"name": vault_decrypt(vault.name_enc), "dob": vault_decrypt(vault.dob_enc)}


def _normalise_name(value: str | None) -> str:
    return " ".join((value or "").lower().replace(".", " ").split())


def name_score(left: str | None, right: str | None) -> int | None:
    if not left or not right:
        return None
    return int(round(fuzz.token_sort_ratio(_normalise_name(left), _normalise_name(right))))


def compare_identity(submitted: dict[str, str | None], read: dict[str, str | None]) -> dict[str, Any]:
    """Field-by-field comparison. Stored with no raw values: scores and booleans only."""
    score = name_score(submitted.get("name"), read.get("name"))
    dob_match = None
    if submitted.get("dob") and read.get("dob"):
        dob_match = submitted["dob"] == read["dob"]
    return {
        "name": {
            "on_document": read.get("name") is not None,
            "score": score,
            "match": None if score is None else score >= NAME_THRESHOLD,
            "rule": f"fuzzy name match >= {NAME_THRESHOLD}",
        },
        "dob": {
            "on_document": read.get("dob") is not None,
            "match": dob_match,
            "rule": "exact date of birth",
        },
    }


# --------------------------------------------------------------------------- tamper


def metadata_edited_after_issue(metadata: dict[str, Any], issued_on: str | None) -> str | None:
    """A message if the PDF was modified after the date it says it was issued."""
    modified = metadata.get("modified")
    if not modified:
        return None
    baseline = issued_on or metadata.get("created")
    if not baseline:
        return None
    if date.fromisoformat(modified) > date.fromisoformat(baseline):
        return (
            f"The file's metadata says it was edited on {modified}, after its issue date "
            f"{baseline} (producer: {metadata.get('producer') or 'unknown'})."
        )
    return None


# --------------------------------------------------------------------------- decision


@dataclass
class Findings:
    integrity_ok: bool
    readable: bool
    reference_no: str | None
    issuer: IssuerResult | None
    identity: dict[str, Any]
    metadata_edit: str | None
    doc_type: str


def decide(findings: Findings) -> tuple[str, list[dict[str, str]]]:
    """(verification_status, reasons). Pure: every rule is visible in one place."""
    reasons: list[dict[str, str]] = []
    label = document_types().get(findings.doc_type, {}).get("label", findings.doc_type)

    if not findings.integrity_ok:
        reasons.append(_reason("STORAGE_TAMPERED", "The stored file no longer matches the SHA-256 recorded at upload.", "error"))
    if not findings.readable:
        reasons.append(_reason("UNREADABLE", "No text could be read from the file (a scan without OCR, or a damaged file)."))

    issuer = findings.issuer
    if findings.reference_no is None:
        reasons.append(_reason("NO_REFERENCE", f"No reference number or QR code was found on this {label.lower()}, so the issuer could not be asked."))
    elif issuer is None or issuer.status == "unavailable":
        reasons.append(_reason("ISSUER_UNAVAILABLE", "The issuer registry did not answer. An officer can re-check it later."))
    elif issuer.status == "not_found":
        reasons.append(_reason("NOT_AT_ISSUER", f"No issuer knows reference {findings.reference_no}."))
    elif issuer.status == "revoked":
        reasons.append(_reason("ISSUER_REVOKED", f"The issuer has revoked {findings.reference_no}.", "error"))
    elif issuer.status == "mismatch":
        differing = ", ".join(fact.replace("_", " ") for fact in issuer.differing_facts) or "the file itself"
        reasons.append(_reason("ISSUER_MISMATCH", f"The issuer holds {findings.reference_no}, but this copy differs from what was issued ({differing}).", "error"))
    else:
        how = "an identical file (SHA-256)" if issuer.matched_by == "hash" else "matching key facts"
        reasons.append(_reason("VERIFIED_WITH_ISSUER", f"{issuer.issuer_name or 'The issuer'} confirms {findings.reference_no} by {how}.", "info"))
        if issuer.doc_type_match is False:
            reasons.append(_reason("WRONG_DOCUMENT_TYPE", f"The issuer says {findings.reference_no} is a {issuer.doc_type}, not a {label.lower()}."))

    name = findings.identity["name"]
    if name["match"] is False:
        reasons.append(_reason("NAME_MISMATCH", f"The name on the document does not match the submitted record (similarity {name['score']}%)."))
    elif name["match"] is None and not (issuer and issuer.holder_name_match):
        reasons.append(_reason("NAME_NOT_FOUND", "No holder name could be read from the document."))
    if findings.identity["dob"]["match"] is False or (issuer and issuer.holder_dob_match is False):
        reasons.append(_reason("DOB_MISMATCH", "The date of birth on the document does not match the submitted record."))
    if issuer and issuer.holder_name_match is False and name["match"] is not False:
        reasons.append(_reason("HOLDER_MISMATCH", "The issuer's record of this document names someone other than the submitted student."))

    if findings.metadata_edit:
        reasons.append(_reason("EDITED_AFTER_ISSUE", findings.metadata_edit))

    codes = {reason["code"] for reason in reasons}
    if codes & REJECTING:
        return "rejected", reasons
    if any(reason["severity"] == "warning" for reason in reasons):
        return "needs_review", reasons
    if issuer is not None and issuer.status == "verified":
        reasons.append(_reason("DATA_MATCHED", "Name and date of birth match the submitted record.", "info"))
        return "auto_verified", reasons
    return "needs_review", reasons  # pragma: no cover - every path above sets a warning


# --------------------------------------------------------------------------- the pipeline


def verify_document(
    db: Session, document: StudentDocument, *, issuer: IssuerClient | None = None
) -> StudentDocument:
    """Run every check and record the outcome. Caller commits."""
    data = verify_integrity(db, document)
    submitted = _submitted_identity(db, document.student_id)
    reading = extract(data, document.content_type) if data is not None else None
    fields = reading.fields if reading else {}
    read_identity = {"name": fields.get("name"), "dob": fields.get("dob")}

    issuer_result: IssuerResult | None = None
    reference_no = fields.get("reference_no")
    if data is not None and reference_no:
        issuer_result = (issuer or IssuerClient()).verify(
            reference_no=reference_no,
            doc_type=document.doc_type,
            sha256=document.sha256,
            holder_name=submitted.get("name"),
            holder_dob=submitted.get("dob"),
            facts={key: fields[key] for key in ("roll_no", "year", "marks_obtained", "marks_total") if key in fields},
        )

    identity = compare_identity(submitted, read_identity)
    metadata = reading.metadata if reading else {}
    metadata_edit = metadata_edited_after_issue(metadata, fields.get("issued_on")) if reading else None
    status, reasons = decide(
        Findings(
            integrity_ok=data is not None,
            readable=bool(reading and reading.readable),
            reference_no=reference_no,
            issuer=issuer_result,
            identity=identity,
            metadata_edit=metadata_edit,
            doc_type=document.doc_type,
        )
    )

    document.extracted = {
        "method": reading.method if reading else "none",
        "reference_no": reference_no,
        "qr_reference": fields.get("qr_reference"),
        "issuer": fields.get("issuer"),
        "roll_no": fields.get("roll_no"),
        "year": fields.get("year"),
        "marks_obtained": fields.get("marks_obtained"),
        "marks_total": fields.get("marks_total"),
        "issued_on": fields.get("issued_on"),
        "text_chars": len(reading.text) if reading else 0,
        "notes": reading.notes if reading else [],
    }
    document.extracted_identity_enc = vault_encrypt(json.dumps(read_identity))
    document.data_match = identity
    document.issuer_status = issuer_result.status if issuer_result else "not_checked"
    document.issuer_result = issuer_result.as_dict() if issuer_result else {}
    document.tamper = {
        "integrity_ok": data is not None,
        "metadata": metadata,
        "edited_after_issue": metadata_edit,
    }
    document.reasons = reasons
    document.verification_status = status
    document.verified_at = datetime.utcnow()
    log_audit(
        db,
        actor="system",
        role="system",
        action="document_verified",
        target=f"document:{document.id}",
        payload={
            "status": status,
            "issuer_status": document.issuer_status,
            "reasons": [reason["code"] for reason in reasons],
        },
    )
    return document


# --------------------------------------------------------------------------- officer review


def review_queue(
    db: Session,
    *,
    status: str | None = "needs_review",
    institution_id: int | None = None,
    doc_type: str | None = None,
) -> list[dict[str, Any]]:
    """Masked rows only: an officer gives a reason before seeing any identity data."""
    conditions = [StudentDocument.is_current.is_(True)]
    if status and status != "all":
        conditions.append(StudentDocument.verification_status == status)
    if institution_id is not None:
        conditions.append(StudentDocument.institution_id == institution_id)
    if doc_type:
        conditions.append(StudentDocument.doc_type == doc_type)
    rows = db.execute(
        select(StudentDocument, Student, Institution)
        .join(Student, Student.id == StudentDocument.student_id)
        .join(Institution, Institution.id == StudentDocument.institution_id)
        .where(*conditions)
        .order_by(StudentDocument.created_at.asc(), StudentDocument.id.asc())
    ).all()
    types = document_types()
    return [
        {
            "document_id": document.id,
            "doc_type": document.doc_type,
            "label": types.get(document.doc_type, {}).get("label", document.doc_type),
            "verification_status": document.verification_status,
            "issuer_status": document.issuer_status,
            "issuer_label": ISSUER_LABELS.get(document.issuer_status, document.issuer_status),
            "reasons": document.reasons or [],
            "student_id": student.id,
            "apaar_masked": student.apaar_masked,
            "name_masked": student.name_masked,
            "institution_id": institution.id,
            "institution_name": institution.name,
            "uploaded_at": document.created_at,
        }
        for document, student, institution in rows
    ]


def review_counts(db: Session) -> dict[str, int]:
    rows = db.execute(
        select(StudentDocument.verification_status, func.count())
        .where(StudentDocument.is_current.is_(True))
        .group_by(StudentDocument.verification_status)
    ).all()
    counts = {status: 0 for status in REVIEW_STATUSES}
    counts.update({status: int(count) for status, count in rows})
    return counts


def case_file(db: Session, *, document: StudentDocument, actor: str, reason: str) -> dict[str, Any]:
    """Submitted vs extracted data, side by side. Identity data, so a reason is required
    and the access is logged where the student can see it. Caller commits."""
    log_access(
        db,
        actor=actor,
        role="aicte_officer",
        action="view_document_case",
        target=f"document:{document.id}",
        reason=reason,
        student_id=document.student_id,
    )
    student = db.get(Student, document.student_id)
    institution = db.get(Institution, document.institution_id)
    vault = db.execute(select(Vault).where(Vault.student_id == document.student_id)).scalar_one_or_none()
    read = json.loads(vault_decrypt(document.extracted_identity_enc) or "{}") if document.extracted_identity_enc else {}
    extracted = document.extracted or {}
    match = document.data_match or {}
    submitted = {
        "name": vault_decrypt(vault.name_enc) if vault else None,
        "dob": vault_decrypt(vault.dob_enc) if vault else None,
        "apaar": vault_decrypt(vault.apaar_enc) if vault and vault.apaar_enc else None,
    }
    comparison = [
        {"field": "Name", "submitted": submitted["name"], "on_document": read.get("name"),
         "match": (match.get("name") or {}).get("match"), "detail": (match.get("name") or {}).get("score")},
        {"field": "Date of birth", "submitted": submitted["dob"], "on_document": read.get("dob"),
         "match": (match.get("dob") or {}).get("match"), "detail": None},
    ]
    types = document_types()
    return {
        "document_id": document.id,
        "doc_type": document.doc_type,
        "label": types.get(document.doc_type, {}).get("label", document.doc_type),
        "content_type": document.content_type,
        "sha256": document.sha256,
        "uploaded_at": document.created_at,
        "uploaded_by": document.uploaded_by,
        "verification_status": document.verification_status,
        "reasons": document.reasons or [],
        "student": {
            "student_id": student.id if student else None,
            "apaar_masked": student.apaar_masked if student else None,
            "apaar": submitted["apaar"],
            "is_minor": bool(student and student.is_minor),
            "nationality_status": student.nationality_status if student else None,
        },
        "institution": {"id": institution.id, "name": institution.name} if institution else None,
        "comparison": comparison,
        "extracted": {key: value for key, value in extracted.items() if value not in (None, [], "")},
        "issuer": {
            "status": document.issuer_status,
            "label": ISSUER_LABELS.get(document.issuer_status, document.issuer_status),
            **(document.issuer_result or {}),
        },
        "tamper": document.tamper or {},
        "integrity_ok": document.integrity_ok,
        "review": {
            "decision": document.review_decision,
            "reason": document.review_reason,
            "by": document.reviewed_by,
            "at": document.reviewed_at,
        },
    }


class ReviewError(ValueError):
    pass


def record_decision(
    db: Session, *, document: StudentDocument, decision: str, reason: str, actor: str
) -> StudentDocument:
    """An officer approves or rejects. Hash-chained in the audit log. Caller commits."""
    if decision not in ("approve", "reject"):
        raise ReviewError("decision must be approve or reject")
    if len(reason.strip()) < 10:
        raise ReviewError("Give a reason of at least 10 characters.")
    if decision == "approve" and not document.integrity_ok:
        raise ReviewError("A document that failed its integrity check cannot be approved.")
    previous = document.verification_status
    document.verification_status = "verified" if decision == "approve" else "rejected"
    document.review_decision = decision
    document.review_reason = reason.strip()
    document.reviewed_by = actor
    document.reviewed_at = datetime.utcnow()
    log_audit(
        db,
        actor=actor,
        role="aicte_officer",
        action="document_review_decision",
        target=f"document:{document.id}",
        payload={"decision": decision, "from": previous, "to": document.verification_status, "reason": reason.strip()},
    )
    return document
