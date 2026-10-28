"""Demo accounts and demo-only consent state (Step-0 decision 2: eight demo students)."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from app.core.access_log import log_access
from app.core.audit import log_audit
from app.core.config import settings
from app.models.core import Consent, Enrolment, Institution, Student, User, VerificationRequest
from app.services.users import (
    DEMO_PASSWORD,
    ensure_base_demo_users,
    ensure_institution_users,
    ensure_student_user,
)

if TYPE_CHECKING:  # pragma: no cover
    from datagen.generator import SyntheticDataGenerator


def _first_case_student(
    gen: SyntheticDataGenerator, scenario: str, flag_type: str | None = None
) -> int | None:
    for case in gen.b.cases:
        if case.scenario != scenario or case.key_kind != "student":
            continue
        if flag_type is None or case.flag_type == flag_type:
            return int(case.key)
    return None


def create_users_and_demo_data(gen: SyntheticDataGenerator) -> None:
    db = gen.db
    ensure_base_demo_users(db)
    ensure_institution_users(db)
    db.commit()

    institutions = {row.id: row for row in db.execute(select(Institution)).scalars()}

    def institution_name_for(student_id: int) -> str:
        enrolment = db.execute(
            select(Enrolment)
            .where(Enrolment.student_id == student_id)
            .order_by(Enrolment.academic_year.desc())
            .limit(1)
        ).scalar_one_or_none()
        if enrolment is None:
            return "—"
        return institutions[enrolment.institution_id].name

    picks: list[tuple[str, int | None, str]] = [
        (
            "student_mismatch",
            _first_case_student(gen, "E_apaar_problems", "APAAR_MISMATCH"),
            "Student — reported name/DOB does not match the APAAR registry",
        ),
        (
            "student_duplicate",
            _first_case_student(gen, "C_cross_institution_duplicate"),
            "Student — reported by two institutions (duplicate enrolment victim)",
        ),
        (
            "student_dual",
            _first_case_student(gen, "D_dual_degree"),
            "Student — legitimate dual degree (regular + online)",
        ),
        ("student_minor", None, "Student — under 18 (parental consent required)"),
        ("student_fn", None, "Student — foreign national, APAAR not applicable"),
        ("student_clean", None, "Student — clean record at the model institution"),
        ("student_pending", None, "Student — has a pending verifier request"),
        ("student_revoked", None, "Student — revoked a consent earlier"),
    ]

    used: set[int] = {sid for _, sid, _ in picks if sid}

    def pick(**criteria: Any) -> int | None:
        statement = select(Student.id)
        if criteria.get("minor"):
            statement = statement.where(Student.is_minor.is_(True))
        if criteria.get("fn"):
            statement = statement.where(
                Student.nationality_status.in_(("fn", "oci")),
                Student.apaar_status == "not_applicable",
            )
        if criteria.get("clean"):
            statement = statement.join(Enrolment, Enrolment.student_id == Student.id).where(
                Enrolment.institution_id == gen.clean_institution_id
            )
        if criteria.get("ordinary"):
            statement = statement.where(
                Student.apaar_status == "provided", Student.registry_status == "match"
            )
        candidates = [
            student_id
            for student_id in db.execute(statement.limit(2000)).scalars()
            if student_id not in used
        ]
        if not candidates:
            return None
        # Deterministic, but spread across institutions rather than the lowest ids.
        student_id = gen.rng.choice(candidates)
        used.add(student_id)
        return student_id

    resolved: list[tuple[str, int, str]] = []
    for username, student_id, label in picks:
        if student_id is None:
            if username == "student_minor":
                student_id = pick(minor=True) or pick(ordinary=True)
            elif username == "student_fn":
                student_id = pick(fn=True) or pick(ordinary=True)
            elif username == "student_clean":
                student_id = pick(clean=True) or pick(ordinary=True)
            else:
                student_id = pick(ordinary=True)
        if student_id is None:
            continue
        resolved.append((username, student_id, label))

    gen.demo_students = []
    for username, student_id, label in resolved:
        student = db.get(Student, student_id)
        if student is None:
            continue
        ensure_student_user(
            db,
            student=student,
            username=username,
            label=f"{label} — {institution_name_for(student_id)}",
            display_name=f"{student.name_masked} ({student.apaar_masked})",
        )
        gen.demo_students.append(
            {
                "username": username,
                "password": DEMO_PASSWORD,
                "student_id": student_id,
                "label": label,
                "apaar_masked": student.apaar_masked,
                "is_minor": student.is_minor,
                "institution": institution_name_for(student_id),
            }
        )
    db.commit()

    _create_consent_state(gen, resolved)


def _create_consent_state(
    gen: SyntheticDataGenerator, resolved: list[tuple[str, int, str]]
) -> None:
    """A pending verifier request and a revoked consent, so those screens have content."""
    db = gen.db
    verifier = db.execute(select(User).where(User.username == "verifier_demo")).scalar_one_or_none()
    if verifier is None:
        return
    by_username = {username: student_id for username, student_id, _ in resolved}
    now = datetime.now().replace(microsecond=0)

    pending_student_id = by_username.get("student_pending")
    if pending_student_id is not None:
        student = db.get(Student, pending_student_id)
        consent = Consent(
            student_id=pending_student_id,
            verifier_user_id=verifier.id,
            verifier_name=verifier.verifier_name or verifier.display_name,
            verifier_type=verifier.verifier_type,
            purpose="employment_verification",
            status="pending",
            parental_consent_required=bool(student and student.is_minor),
            requested_at=now - timedelta(hours=2),
            expires_at=now + timedelta(hours=settings.consent_request_ttl_hours - 2),
            shared_fields=["verified", "program", "academic_year"],
        )
        db.add(consent)
        db.flush()
        db.add(
            VerificationRequest(
                verifier_user_id=verifier.id,
                apaar_hash=student.apaar_hash if student else None,
                apaar_masked=student.apaar_masked if student else "XXXX-XXXX-XXXX",
                student_id=pending_student_id,
                consent_id=consent.id,
                purpose="employment_verification",
                note="Offer-stage check (demo)",
                status="pending",
                expires_at=consent.expires_at,
            )
        )

    revoked_student_id = by_username.get("student_revoked")
    if revoked_student_id is not None:
        student = db.get(Student, revoked_student_id)
        consent = Consent(
            student_id=revoked_student_id,
            verifier_user_id=verifier.id,
            verifier_name=verifier.verifier_name or verifier.display_name,
            verifier_type=verifier.verifier_type,
            purpose="higher_education_admission",
            status="revoked",
            requested_at=now - timedelta(days=3),
            responded_at=now - timedelta(days=3, hours=-1),
            revoked_at=now - timedelta(days=1),
            expires_at=now + timedelta(hours=24),
            shared_fields=["verified", "program", "academic_year"],
        )
        db.add(consent)
        db.flush()
        db.add(
            VerificationRequest(
                verifier_user_id=verifier.id,
                apaar_hash=student.apaar_hash if student else None,
                apaar_masked=student.apaar_masked if student else "XXXX-XXXX-XXXX",
                student_id=revoked_student_id,
                consent_id=consent.id,
                purpose="higher_education_admission",
                # A revoked consent leaves no result behind, which is what
                # app/services/consent.revoke_consent does for a live request.
                status="revoked",
                result=None,
                responded_at=consent.responded_at,
                expires_at=consent.expires_at,
            )
        )

    for student_id, purpose, label in (
        (pending_student_id, "employment_verification", "Employment background verification"),
        (revoked_student_id, "higher_education_admission", "Admission to higher education"),
    ):
        if student_id is None:
            continue
        log_access(
            db,
            actor=verifier.username,
            role="verifier",
            action="verification_requested",
            target=f"student:{student_id}",
            student_id=student_id,
            purpose=purpose,
            reason=f"Verification requested for {label}.",
        )
    if revoked_student_id is not None:
        log_access(
            db,
            actor=verifier.username,
            role="verifier",
            action="verification_result_read",
            target=f"student:{revoked_student_id}",
            student_id=revoked_student_id,
            purpose="higher_education_admission",
            reason="Consented verification for Admission to higher education.",
        )

    log_audit(
        db,
        actor="datagen",
        role="admin",
        action="seed_database",
        target="database",
        payload={"seed": gen.seed, "students": len(gen.b.students)},
    )
    db.commit()
