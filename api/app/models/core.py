"""SQLAlchemy models for every table in CLAUDE.md section 7."""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


# ----------------------------------------------------------------- institutions & programs


class Institution(Base, TimestampMixin):
    __tablename__ = "institutions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    aicte_permanent_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    state: Mapped[str] = mapped_column(String(64), index=True)
    region: Mapped[str] = mapped_column(String(32), index=True)
    type: Mapped[str] = mapped_column(String(32))
    district: Mapped[str | None] = mapped_column(String(64), nullable=True)

    programs: Mapped[list["Program"]] = relationship(back_populates="institution")


class Program(Base, TimestampMixin):
    __tablename__ = "programs"
    __table_args__ = (
        UniqueConstraint("institution_id", "course", "branch", "mode", name="uq_program_identity"),
        Index("ix_programs_institution", "institution_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    institution_id: Mapped[int] = mapped_column(ForeignKey("institutions.id"), index=True)
    course: Mapped[str] = mapped_column(String(64))
    branch: Mapped[str] = mapped_column(String(128))
    level: Mapped[str] = mapped_column(String(16))  # UG | PG | Diploma
    mode: Mapped[str] = mapped_column(String(16), default="regular")  # regular | online

    institution: Mapped[Institution] = relationship(back_populates="programs")
    intakes: Mapped[list["ApprovedIntake"]] = relationship(back_populates="program")


class ApprovedIntake(Base, TimestampMixin):
    __tablename__ = "approved_intake"
    __table_args__ = (
        UniqueConstraint("program_id", "academic_year", name="uq_intake_program_year"),
        Index("ix_intake_year", "academic_year"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    program_id: Mapped[int] = mapped_column(ForeignKey("programs.id"), index=True)
    academic_year: Mapped[str] = mapped_column(String(16), index=True)
    intake: Mapped[int] = mapped_column(Integer)
    # {"tfw": 15, "lateral": 30, ...} resolved from intake_rules.yaml at seed time.
    supernumerary_caps: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    program: Mapped[Program] = relationship(back_populates="intakes")


# ----------------------------------------------------------------- students & the vault


class Student(Base, TimestampMixin):
    """No raw contact details, name, DOB or APAAR ID — see app/core/crypto.py."""

    __tablename__ = "students"
    __table_args__ = (
        Index("ix_students_apaar_hash", "apaar_hash"),
        Index("ix_students_guardian_phone_hash", "guardian_phone_hash"),
        Index("ix_students_phone_hash", "phone_hash"),
        Index("ix_students_email_hash", "email_hash"),
        Index("ix_students_identity", "name_hash", "dob_hash", "guardian_phone_hash"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    apaar_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    apaar_masked: Mapped[str] = mapped_column(String(20), default="XXXX-XXXX-XXXX")
    apaar_status: Mapped[str] = mapped_column(String(20), default="provided", index=True)
    name_masked: Mapped[str] = mapped_column(String(64), default="***")
    name_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    dob_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    gender: Mapped[str | None] = mapped_column(String(16), nullable=True)
    category: Mapped[str | None] = mapped_column(String(24), nullable=True)
    nationality_status: Mapped[str] = mapped_column(String(16), default="indian", index=True)
    dob_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_minor: Mapped[bool] = mapped_column(Boolean, default=False)
    phone_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    email_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    guardian_phone_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    registry_status: Mapped[str | None] = mapped_column(String(24), nullable=True)

    vault: Mapped["Vault | None"] = relationship(
        back_populates="student", uselist=False, cascade="all, delete-orphan"
    )
    enrolments: Mapped[list["Enrolment"]] = relationship(back_populates="student")


class Vault(Base, TimestampMixin):
    """Fernet-encrypted raw identifiers. The only place these values exist."""

    __tablename__ = "vault"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), unique=True, index=True)
    apaar_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    name_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    dob_enc: Mapped[str | None] = mapped_column(Text, nullable=True)

    student: Mapped[Student] = relationship(back_populates="vault")


class Enrolment(Base, TimestampMixin):
    __tablename__ = "enrolments"
    __table_args__ = (
        Index("ix_enrolments_program_year", "program_id", "academic_year"),
        Index("ix_enrolments_student_year", "student_id", "academic_year"),
        Index("ix_enrolments_institution_year", "institution_id", "academic_year"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), index=True)
    program_id: Mapped[int] = mapped_column(ForeignKey("programs.id"), index=True)
    # Denormalised for tenant-scoped queries; always equals program.institution_id.
    institution_id: Mapped[int] = mapped_column(ForeignKey("institutions.id"), index=True)
    academic_year: Mapped[str] = mapped_column(String(16), index=True)
    year_of_study: Mapped[int] = mapped_column(Integer, default=1)
    admission_type: Mapped[str] = mapped_column(String(32), default="regular", index=True)
    status: Mapped[str] = mapped_column(String(16), default="admitted", index=True)
    admitted_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    upload_id: Mapped[int | None] = mapped_column(ForeignKey("uploads.id"), nullable=True, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    student_confirmation: Mapped[str] = mapped_column(String(16), default="unconfirmed")
    registry_status: Mapped[str | None] = mapped_column(String(24), nullable=True)

    student: Mapped[Student] = relationship(back_populates="enrolments")
    program: Mapped[Program] = relationship()
    institution: Mapped[Institution] = relationship()


class EnrolmentHistory(Base, TimestampMixin):
    """Versioned status history (CLAUDE.md section 6: status lifecycle with history)."""

    __tablename__ = "enrolment_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    enrolment_id: Mapped[int] = mapped_column(ForeignKey("enrolments.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    from_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    to_status: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    changed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)


class Upload(Base, TimestampMixin):
    __tablename__ = "uploads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    institution_id: Mapped[int] = mapped_column(ForeignKey("institutions.id"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    state: Mapped[str] = mapped_column(String(24), default="pending_mapping", index=True)
    academic_year: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    rows_total: Mapped[int] = mapped_column(Integer, default=0)
    rows_ok: Mapped[int] = mapped_column(Integer, default=0)
    rows_error: Mapped[int] = mapped_column(Integer, default=0)
    rows_warning: Mapped[int] = mapped_column(Integer, default=0)
    blank_rows_skipped: Mapped[int] = mapped_column(Integer, default=0)
    quality_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    column_mapping: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    proposed_mapping: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    issues: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    registry_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    raw_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    uploaded_by: Mapped[str | None] = mapped_column(String(64), nullable=True)


class Flag(Base, TimestampMixin):
    """Every flag carries a human-readable explanation and structured evidence."""

    __tablename__ = "flags"
    __table_args__ = (
        Index("ix_flags_type_status", "type", "status"),
        Index("ix_flags_institution", "institution_id"),
        Index("ix_flags_dedupe", "type", "dedupe_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[str] = mapped_column(String(40), index=True)
    severity: Mapped[str] = mapped_column(String(16), default="medium", index=True)
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)
    institution_id: Mapped[int | None] = mapped_column(ForeignKey("institutions.id"), nullable=True)
    student_id: Mapped[int | None] = mapped_column(ForeignKey("students.id"), nullable=True, index=True)
    enrolment_id: Mapped[int | None] = mapped_column(ForeignKey("enrolments.id"), nullable=True)
    cluster_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    program_id: Mapped[int | None] = mapped_column(ForeignKey("programs.id"), nullable=True)
    academic_year: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(255))
    explanation: Mapped[str] = mapped_column(Text)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    assigned_to: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    notes: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    # Stable identity of the underlying finding, so re-running detectors updates in place.
    dedupe_key: Mapped[str] = mapped_column(String(128), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    institution: Mapped[Institution | None] = relationship()


class FlagHistory(Base, TimestampMixin):
    __tablename__ = "flag_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    flag_id: Mapped[int] = mapped_column(ForeignKey("flags.id"), index=True)
    from_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    actor: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    audit_log_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Cluster(Base, TimestampMixin):
    """A connected component from the ghost-student graph (Step 9)."""

    __tablename__ = "clusters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    severity: Mapped[str] = mapped_column(String(16), default="medium")
    student_count: Mapped[int] = mapped_column(Integer, default=0)
    attribute_count: Mapped[int] = mapped_column(Integer, default=0)
    institutions_involved: Mapped[int] = mapped_column(Integer, default=0)
    kind: Mapped[str] = mapped_column(String(24), default="suspicious")  # suspicious | normal
    academic_year: Mapped[str | None] = mapped_column(String(16), nullable=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    graph: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    member_student_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    institution_ids: Mapped[list[int]] = mapped_column(JSON, default=list)


class InstitutionRisk(Base, TimestampMixin):
    """Computed risk score per institution (Step 11)."""

    __tablename__ = "institution_risk"
    __table_args__ = (UniqueConstraint("institution_id", name="uq_risk_institution"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    institution_id: Mapped[int] = mapped_column(ForeignKey("institutions.id"), index=True)
    academic_year: Mapped[str] = mapped_column(String(16))
    score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    band: Mapped[str] = mapped_column(String(16), default="low")
    flag_component: Mapped[float] = mapped_column(Float, default=0.0)
    anomaly_component: Mapped[float] = mapped_column(Float, default=0.0)
    reasons: Mapped[list[str]] = mapped_column(JSON, default=list)
    features: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    computed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ----------------------------------------------------------------- users, logs, consent


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(24), index=True)
    display_name: Mapped[str] = mapped_column(String(128), default="")
    institution_id: Mapped[int | None] = mapped_column(ForeignKey("institutions.id"), nullable=True)
    student_id: Mapped[int | None] = mapped_column(ForeignKey("students.id"), nullable=True)
    verifier_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    verifier_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    demo_label: Mapped[str | None] = mapped_column(String(160), nullable=True)
    demo_password: Mapped[str | None] = mapped_column(String(64), nullable=True)  # demo mode only
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class AccessLog(Base, TimestampMixin):
    """Every detail view / reveal (CLAUDE.md section 5 rule 7)."""

    __tablename__ = "access_log"
    __table_args__ = (Index("ix_access_log_student", "student_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor: Mapped[str] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(24))
    action: Mapped[str] = mapped_column(String(64), index=True)
    target: Mapped[str] = mapped_column(String(128), index=True)
    student_id: Mapped[int | None] = mapped_column(ForeignKey("students.id"), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    purpose: Mapped[str | None] = mapped_column(String(64), nullable=True)


class AuditLog(Base):
    """Append-only, hash-chained (CLAUDE.md section 5 rule 8)."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor: Mapped[str] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(24))
    action: Mapped[str] = mapped_column(String(64), index=True)
    target: Mapped[str | None] = mapped_column(String(128), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))


class Consent(Base, TimestampMixin):
    __tablename__ = "consents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), index=True)
    verifier_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    verifier_name: Mapped[str] = mapped_column(String(128))
    verifier_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    purpose: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    parental_consent_required: Mapped[bool] = mapped_column(Boolean, default=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deny_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    shared_fields: Mapped[list[str]] = mapped_column(JSON, default=list)


class VerificationRequest(Base, TimestampMixin):
    """A verifier's request. The APAAR ID is hashed on receipt and never stored raw."""

    __tablename__ = "verification_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    verifier_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    apaar_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    apaar_masked: Mapped[str] = mapped_column(String(20), default="XXXX-XXXX-XXXX")
    student_id: Mapped[int | None] = mapped_column(ForeignKey("students.id"), nullable=True)
    consent_id: Mapped[int | None] = mapped_column(ForeignKey("consents.id"), nullable=True)
    purpose: Mapped[str] = mapped_column(String(64))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class CorrectionRequest(Base, TimestampMixin):
    """A student's correction request, routed to the institution's flag inbox."""

    __tablename__ = "correction_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), index=True)
    institution_id: Mapped[int] = mapped_column(ForeignKey("institutions.id"), index=True)
    enrolment_id: Mapped[int | None] = mapped_column(ForeignKey("enrolments.id"), nullable=True)
    field: Mapped[str] = mapped_column(String(64))
    correct_value: Mapped[str] = mapped_column(String(255))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="sent_to_institution", index=True)
    response_note: Mapped[str | None] = mapped_column(Text, nullable=True)


class ReminderLog(Base, TimestampMixin):
    """Mocked non-reporting reminders (Step 12)."""

    __tablename__ = "reminder_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    institution_id: Mapped[int] = mapped_column(ForeignKey("institutions.id"), index=True)
    academic_year: Mapped[str] = mapped_column(String(16))
    channel: Mapped[str] = mapped_column(String(24), default="email")
    message: Mapped[str] = mapped_column(Text, default="")
    actor: Mapped[str | None] = mapped_column(String(64), nullable=True)
