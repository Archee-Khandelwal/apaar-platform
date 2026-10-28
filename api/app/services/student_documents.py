"""Document submission by institutions (Phase 4).

An institution attaches documents to its own students, one at a time or as a ZIP. Three
guarantees:

* **Type by content.** The first bytes decide whether a file is a PDF, JPEG or PNG; the
  extension and the declared content type are ignored. PDFs that carry JavaScript or
  launch actions are refused outright.
* **Encrypted at rest.** The bytes are stored Fernet-encrypted with the vault key, next
  to the SHA-256 of the plaintext taken at upload.
* **Tamper-evident.** Every read decrypts and re-hashes. A mismatch (or a ciphertext that
  no longer decrypts) marks the document, raises a ``DOCUMENT_TAMPERED`` flag, and the
  file is not served.

Who may read a document — the owning institution, an AICTE officer with a reason, or the
student — is decided by the routers; every read here writes the access log.
"""
from __future__ import annotations

import hashlib
import io
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.access_log import log_access
from app.core.audit import log_audit
from app.core.crypto import CryptoConfigError, decrypt_bytes, encrypt_bytes, hmac_hash
from app.models.core import Enrolment, Student, StudentDocument
from app.services.flags import upsert_flag
from app.services.rules import document_limits, document_types, required_documents

PDF, JPEG, PNG = "application/pdf", "image/jpeg", "image/png"
_EXTENSION = {PDF: "pdf", JPEG: "jpg", PNG: "png"}
# PDF names that make a document active content rather than a document.
_UNSAFE_PDF = (b"/JavaScript", b"/JS", b"/Launch", b"/EmbeddedFile", b"/RichMedia")

# The status an institution sees on its checklist, from the verification status.
CHECKLIST_STATUS = {
    "pending": "uploaded",
    "needs_review": "uploaded",
    "auto_verified": "verified",
    "verified": "verified",
    "rejected": "rejected",
}


class DocumentRejected(Exception):
    """A file that will not be stored. ``code`` is the API error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class DocumentIntegrityError(Exception):
    """The stored file no longer matches the hash taken at upload."""


# --------------------------------------------------------------------------- inspection


def sniff_content_type(data: bytes) -> str | None:
    if data.startswith(b"%PDF-"):
        return PDF
    if data.startswith(b"\xff\xd8\xff"):
        return JPEG
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return PNG
    return None


def max_file_bytes() -> int:
    return int(float(document_limits().get("max_file_mb", 5)) * 1024 * 1024)


def inspect_file(data: bytes) -> str:
    """Return the sniffed content type, or raise DocumentRejected with the reason."""
    if not data:
        raise DocumentRejected("EMPTY_FILE", "The file is empty.")
    if len(data) > max_file_bytes():
        raise DocumentRejected(
            "FILE_TOO_LARGE",
            f"The file is {len(data) / 1024 / 1024:.1f} MB; the limit is "
            f"{document_limits().get('max_file_mb', 5)} MB.",
        )
    content_type = sniff_content_type(data)
    accepted = document_limits().get("accepted_types", [PDF, JPEG, PNG])
    if content_type is None or content_type not in accepted:
        raise DocumentRejected(
            "UNSUPPORTED_FILE",
            "Only PDF, JPEG and PNG files are accepted, and the file's contents (not its "
            "name) decide which it is.",
        )
    if content_type == PDF and any(marker in data for marker in _UNSAFE_PDF):
        raise DocumentRejected(
            "UNSAFE_FILE",
            "This PDF contains scripts, launch actions or embedded files and was refused.",
        )
    return content_type


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --------------------------------------------------------------------------- students


@dataclass(frozen=True)
class StudentContext:
    student: Student
    enrolment: Enrolment

    @property
    def required(self) -> list[str]:
        return required_documents(
            admission_type=self.enrolment.admission_type,
            category=self.student.category,
            nationality_status=self.student.nationality_status,
        )


def student_context(db: Session, *, institution_id: int, student_id: int) -> StudentContext:
    """The student's latest enrolment *at this institution*. LookupError otherwise, so a
    college can never attach a file to (or read the checklist of) someone else's student."""
    enrolment = db.execute(
        select(Enrolment)
        .where(Enrolment.student_id == student_id, Enrolment.institution_id == institution_id)
        .order_by(Enrolment.academic_year.desc(), Enrolment.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    student = db.get(Student, student_id) if enrolment else None
    if enrolment is None or student is None:
        raise LookupError("No such student at this institution.")
    return StudentContext(student=student, enrolment=enrolment)


def current_documents(db: Session, *, student_id: int, institution_id: int) -> dict[str, StudentDocument]:
    rows = db.execute(
        select(StudentDocument).where(
            StudentDocument.student_id == student_id,
            StudentDocument.institution_id == institution_id,
            StudentDocument.is_current.is_(True),
        )
    ).scalars()
    return {row.doc_type: row for row in rows}


def document_summary(document: StudentDocument) -> dict[str, Any]:
    return {
        "id": document.id,
        "doc_type": document.doc_type,
        "original_filename": document.original_filename,
        "content_type": document.content_type,
        "size_bytes": document.size_bytes,
        "sha256": document.sha256,
        "uploaded_at": document.created_at,
        "uploaded_by": document.uploaded_by,
        "upload_channel": document.upload_channel,
        "verification_status": document.verification_status,
        "issuer_status": document.issuer_status,
        "integrity_ok": document.integrity_ok,
        "reasons": document.reasons or [],
        "review_decision": document.review_decision,
        "review_reason": document.review_reason,
    }


def checklist(db: Session, *, institution_id: int, student_id: int) -> dict[str, Any]:
    context = student_context(db, institution_id=institution_id, student_id=student_id)
    types = document_types()
    documents = current_documents(db, student_id=student_id, institution_id=institution_id)
    items = []
    for doc_type in context.required:
        document = documents.get(doc_type)
        items.append(
            {
                "doc_type": doc_type,
                "label": types.get(doc_type, {}).get("label", doc_type),
                "status": CHECKLIST_STATUS.get(document.verification_status, "uploaded")
                if document
                else "missing",
                "document": document_summary(document) if document else None,
            }
        )
    counts = {status: 0 for status in ("missing", "uploaded", "verified", "rejected")}
    for item in items:
        counts[item["status"]] += 1
    student = context.student
    return {
        "student_id": student.id,
        "apaar_masked": student.apaar_masked,
        "name_masked": student.name_masked,
        "nationality_status": student.nationality_status,
        "category": student.category,
        "admission_type": context.enrolment.admission_type,
        "academic_year": context.enrolment.academic_year,
        "items": items,
        "counts": counts,
        "complete": counts["missing"] == 0 and counts["rejected"] == 0,
    }


# --------------------------------------------------------------------------- storing


def store_document(
    db: Session,
    *,
    institution_id: int,
    student_id: int,
    doc_type: str,
    filename: str,
    data: bytes,
    actor: str,
    channel: str = "single",
) -> StudentDocument:
    """Validate, encrypt and store one document. Caller commits."""
    context = student_context(db, institution_id=institution_id, student_id=student_id)
    if doc_type not in document_types():
        raise DocumentRejected("UNKNOWN_DOCUMENT_TYPE", f"'{doc_type}' is not a known document type.")
    if doc_type not in context.required:
        raise DocumentRejected(
            "NOT_REQUIRED",
            f"'{doc_type}' is not on this student's checklist ({', '.join(context.required)}).",
        )
    content_type = inspect_file(data)

    for previous in current_documents(db, student_id=student_id, institution_id=institution_id).values():
        if previous.doc_type == doc_type:
            previous.is_current = False

    safe_name = PurePosixPath(filename.replace("\\", "/")).name[:200] or f"{doc_type}.{_EXTENSION[content_type]}"
    document = StudentDocument(
        student_id=student_id,
        institution_id=institution_id,
        enrolment_id=context.enrolment.id,
        doc_type=doc_type,
        original_filename=safe_name,
        content_type=content_type,
        size_bytes=len(data),
        sha256=sha256_hex(data),
        content_enc=encrypt_bytes(data),
        is_current=True,
        upload_channel=channel,
        uploaded_by=actor,
        verification_status="pending",
        integrity_checked_at=datetime.utcnow(),
    )
    db.add(document)
    db.flush()
    log_audit(
        db,
        actor=actor,
        role="institution",
        action="document_uploaded",
        target=f"document:{document.id}",
        payload={
            "student_id": student_id,
            "doc_type": doc_type,
            "sha256": document.sha256,
            "size_bytes": document.size_bytes,
            "content_type": content_type,
            "channel": channel,
        },
    )
    return document


# --------------------------------------------------------------------------- reading


def read_document(
    db: Session,
    *,
    document: StudentDocument,
    actor: str,
    role: str,
    reason: str | None = None,
) -> bytes:
    """Decrypt, re-hash, log the access and return the bytes. Caller commits.

    Raises DocumentIntegrityError when the stored file no longer matches its upload hash;
    the document is marked and a DOCUMENT_TAMPERED flag is raised before raising.
    """
    log_access(
        db,
        actor=actor,
        role=role,
        action="view_document",
        target=f"document:{document.id}",
        reason=reason,
        student_id=document.student_id,
    )
    data = verify_integrity(db, document)
    if data is None:
        raise DocumentIntegrityError(
            "This document no longer matches the hash recorded when it was uploaded."
        )
    return data


def verify_integrity(db: Session, document: StudentDocument) -> bytes | None:
    """Re-hash the stored file. Returns the bytes, or None (and records why) if tampered."""
    document.integrity_checked_at = datetime.utcnow()
    try:
        data = decrypt_bytes(document.content_enc)
    except CryptoConfigError:
        data = None
    if data is not None and sha256_hex(data) == document.sha256:
        return data

    document.integrity_ok = False
    document.verification_status = "rejected"
    reason = {
        "code": "STORAGE_TAMPERED",
        "message": "The stored file no longer matches the SHA-256 recorded at upload.",
    }
    if reason not in (document.reasons or []):
        document.reasons = [*(document.reasons or []), reason]
    upsert_flag(
        db,
        type="DOCUMENT_TAMPERED",
        dedupe_key=f"document:{document.id}:storage",
        severity="critical",
        title="A stored document failed its integrity check",
        explanation=(
            f"The {document.doc_type.replace('_', ' ')} uploaded on "
            f"{document.created_at:%d %b %Y} no longer matches the SHA-256 recorded at upload "
            f"({document.sha256[:12]}…). It has been withheld and rejected."
        ),
        evidence={
            "document_id": document.id,
            "doc_type": document.doc_type,
            "recorded_sha256": document.sha256,
            "check": "re-hash on view",
        },
        institution_id=document.institution_id,
        student_id=document.student_id,
        enrolment_id=document.enrolment_id,
    )
    log_audit(
        db,
        actor="system",
        role="system",
        action="document_integrity_failed",
        target=f"document:{document.id}",
        payload={"recorded_sha256": document.sha256},
    )
    return None


# --------------------------------------------------------------------------- bulk ZIP


_STUDENT_KEY = re.compile(r"^(?:S)?(\d+)$", re.IGNORECASE)


def _resolve_student(db: Session, institution_id: int, key: str) -> int | None:
    """A 12-digit key is an APAAR ID; any other number is our student id."""
    key = key.strip()
    if re.fullmatch(r"\d{12}", key):
        student_id = db.execute(
            select(Student.id)
            .join(Enrolment, Enrolment.student_id == Student.id)
            .where(Student.apaar_hash == hmac_hash(key), Enrolment.institution_id == institution_id)
            .limit(1)
        ).scalar_one_or_none()
        return student_id
    match = _STUDENT_KEY.match(key)
    if not match:
        return None
    candidate = int(match.group(1))
    exists = db.scalar(
        select(func.count())
        .select_from(Enrolment)
        .where(Enrolment.student_id == candidate, Enrolment.institution_id == institution_id)
    )
    return candidate if exists else None


def _split_entry(name: str) -> tuple[str, str] | None:
    """``<key>/<doc_type>.pdf`` or ``<key>_<doc_type>.pdf`` -> (key, doc_type)."""
    path = PurePosixPath(name.replace("\\", "/"))
    stem = path.stem
    if len(path.parts) >= 2:
        return path.parts[-2], stem
    if "_" in stem:
        key, doc_type = stem.split("_", 1)
        return key, doc_type
    return None


def import_zip(
    db: Session, *, institution_id: int, data: bytes, actor: str
) -> dict[str, Any]:
    """Store every recognisable file in a ZIP; report each file's outcome. Caller commits.

    Nothing is extracted to disk. Entry sizes are checked against the header *and* while
    reading, so a ZIP bomb or a lying header cannot exhaust memory.
    """
    limits = document_limits()
    max_files = int(limits.get("zip_max_files", 500))
    max_total = int(float(limits.get("zip_max_total_mb", 200)) * 1024 * 1024)
    per_file = max_file_bytes()

    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise DocumentRejected("UNSUPPORTED_FILE", "That file is not a valid ZIP archive.") from exc

    entries = [info for info in archive.infolist() if not info.is_dir()]
    if len(entries) > max_files:
        raise DocumentRejected("TOO_MANY_FILES", f"The ZIP has {len(entries)} files; the limit is {max_files}.")
    if sum(info.file_size for info in entries) > max_total:
        raise DocumentRejected(
            "FILE_TOO_LARGE", f"The ZIP expands past the {limits.get('zip_max_total_mb', 200)} MB limit."
        )

    results: list[dict[str, Any]] = []
    stored = 0
    for info in entries:
        name = info.filename
        if PurePosixPath(name).name.startswith(".") or "__MACOSX" in name:
            continue
        outcome: dict[str, Any] = {"file": name}
        parsed = _split_entry(name)
        if parsed is None:
            results.append({**outcome, "status": "skipped", "reason": "Name it <APAAR or student id>_<document type>.pdf"})
            continue
        key, doc_type = parsed
        outcome["doc_type"] = doc_type
        student_id = _resolve_student(db, institution_id, key)
        if student_id is None:
            results.append({**outcome, "status": "rejected", "reason": "No student with that APAAR ID or student id at your institution."})
            continue
        outcome["student_id"] = student_id
        if info.file_size > per_file:
            results.append({**outcome, "status": "rejected", "reason": "File is over the size limit."})
            continue
        with archive.open(info) as handle:
            content = handle.read(per_file + 1)
        try:
            document = store_document(
                db,
                institution_id=institution_id,
                student_id=student_id,
                doc_type=doc_type,
                filename=PurePosixPath(name).name,
                data=content,
                actor=actor,
                channel="zip",
            )
        except DocumentRejected as exc:
            results.append({**outcome, "status": "rejected", "reason": exc.message})
            continue
        stored += 1
        results.append({**outcome, "status": "stored", "document_id": document.id})

    log_audit(
        db,
        actor=actor,
        role="institution",
        action="documents_bulk_uploaded",
        target=f"institution:{institution_id}",
        payload={"files": len(entries), "stored": stored},
    )
    return {
        "files": len(results),
        "stored": stored,
        "rejected": sum(1 for row in results if row["status"] == "rejected"),
        "skipped": sum(1 for row in results if row["status"] == "skipped"),
        "results": results,
    }


# --------------------------------------------------------------------------- overview


def institution_overview(
    db: Session, *, institution_id: int, academic_year: str, status: str | None = None, search: str | None = None
) -> list[dict[str, Any]]:
    """One row per enrolled student with their checklist progress."""
    enrolments = list(
        db.execute(
            select(Enrolment, Student)
            .join(Student, Student.id == Enrolment.student_id)
            .where(Enrolment.institution_id == institution_id, Enrolment.academic_year == academic_year)
            .order_by(Student.id)
        ).all()
    )
    documents: dict[int, dict[str, StudentDocument]] = {}
    for document in db.execute(
        select(StudentDocument).where(
            StudentDocument.institution_id == institution_id, StudentDocument.is_current.is_(True)
        )
    ).scalars():
        documents.setdefault(document.student_id, {})[document.doc_type] = document

    rows: list[dict[str, Any]] = []
    for enrolment, student in enrolments:
        if search and search.strip().lower() not in student.apaar_masked.lower() and search.strip() != str(student.id):
            continue
        required = required_documents(
            admission_type=enrolment.admission_type,
            category=student.category,
            nationality_status=student.nationality_status,
        )
        held = documents.get(student.id, {})
        counts = {key: 0 for key in ("missing", "uploaded", "verified", "rejected")}
        for doc_type in required:
            document = held.get(doc_type)
            counts[CHECKLIST_STATUS.get(document.verification_status, "uploaded") if document else "missing"] += 1
        row_status = (
            "rejected" if counts["rejected"] else
            "missing" if counts["missing"] else
            "verified" if counts["verified"] == len(required) else "uploaded"
        )
        if status and status != row_status:
            continue
        rows.append(
            {
                "student_id": student.id,
                "apaar_masked": student.apaar_masked,
                "name_masked": student.name_masked,
                "admission_type": enrolment.admission_type,
                "nationality_status": student.nationality_status,
                "required": len(required),
                "counts": counts,
                "status": row_status,
                "missing": [doc_type for doc_type in required if doc_type not in held],
            }
        )
    return rows
