"""Step 13: student portal, consent, verifier flow and signed tokens."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crypto import hash_apaar, mask_apaar, mask_name, vault_encrypt
from app.models.core import (
    AccessLog,
    AuditLog,
    Consent,
    CorrectionRequest,
    Enrolment,
    Flag,
    Institution,
    Program,
    Student,
    User,
    Vault,
    VerificationRequest,
)
from app.services.tokens import issue_token, parse_token

YEAR = "2026-27"
APAAR = "123456781234"


@pytest.fixture()
def student_setup(db: Session, users, two_institutions) -> dict:
    """Give the demo student a real enrolment, a vault row and an APAAR ID."""
    first, second = two_institutions
    program = db.execute(select(Program).where(Program.institution_id == first.id)).scalars().first()
    other = db.execute(select(Program).where(Program.institution_id == second.id)).scalars().first()

    account = db.execute(select(User).where(User.username == "student_demo1")).scalar_one()
    student = db.get(Student, account.student_id)
    student.apaar_hash = hash_apaar(APAAR)
    student.apaar_masked = mask_apaar(APAAR)
    student.apaar_status = "provided"
    student.name_masked = mask_name("Rahul Sharma")
    student.is_minor = False
    db.add(
        Vault(
            student_id=student.id,
            apaar_enc=vault_encrypt(APAAR),
            name_enc=vault_encrypt("Rahul Sharma"),
            dob_enc=vault_encrypt("2006-03-12"),
        )
    )
    enrolment = Enrolment(
        student_id=student.id,
        program_id=program.id,
        institution_id=first.id,
        academic_year=YEAR,
        year_of_study=1,
        admission_type="regular",
        status="admitted",
        admitted_on=date(2026, 8, 5),
    )
    db.add(enrolment)
    db.flush()
    db.commit()
    return {
        "student": student,
        "enrolment": enrolment,
        "program": program,
        "other_program": other,
        "first": first,
        "second": second,
    }


def verifier_account(db: Session) -> User:
    return db.execute(select(User).where(User.username == "verifier_demo")).scalar_one()


# ------------------------------------------------------------------ student: own records


def test_student_sees_what_the_college_reported(client: TestClient, auth, student_setup) -> None:
    body = client.get("/student/me", headers=auth("student")).json()
    assert body["student"]["apaar_masked"] == "XXXX-XXXX-1234"
    assert body["student"]["name"] == "Rahul Sharma"  # their own name, in full
    assert body["student"]["dob"] == "2006-03-12"
    assert len(body["enrolments"]) == 1
    row = body["enrolments"][0]
    assert row["institution_name"] == student_setup["first"].name
    assert row["confirmation"] == "unconfirmed"
    assert row["program"].startswith("B.Tech")


def test_student_routes_refuse_other_roles(client: TestClient, auth, student_setup) -> None:
    for path in ("/student/me", "/student/access-log", "/student/consents", "/student/id-card"):
        for role in ("institution", "aicte_officer", "aicte_viewer", "verifier", "admin"):
            assert client.get(path, headers=auth(role)).status_code == 403, f"{path} {role}"


def test_a_student_cannot_touch_another_students_enrolment(
    client: TestClient, auth, student_setup, db: Session
) -> None:
    other_student = Student(apaar_masked="XXXX-XXXX-9999", name_masked="A**** B.")
    db.add(other_student)
    db.flush()
    foreign = Enrolment(
        student_id=other_student.id,
        program_id=student_setup["other_program"].id,
        institution_id=student_setup["second"].id,
        academic_year=YEAR,
    )
    db.add(foreign)
    db.commit()

    headers = auth("student")
    assert client.post(f"/student/enrolments/{foreign.id}/confirm", headers=headers).status_code == 404
    assert (
        client.post(
            f"/student/enrolments/{foreign.id}/dispute",
            headers=headers,
            json={"reason": "This is not mine at all.", "category": "not_my_enrolment"},
        ).status_code
        == 404
    )


# ------------------------------------------------------------------ confirm / dispute


def test_confirming_an_enrolment(client: TestClient, auth, student_setup, db: Session) -> None:
    enrolment = student_setup["enrolment"]
    body = client.post(f"/student/enrolments/{enrolment.id}/confirm", headers=auth("student")).json()
    assert body["confirmation"] == "confirmed"
    assert body["audit_log_id"]
    db.expire_all()
    assert db.get(Enrolment, enrolment.id).student_confirmation == "confirmed"


def test_disputing_raises_a_critical_flag_for_aicte_and_the_college(
    client: TestClient, auth, student_setup, db: Session
) -> None:
    enrolment = student_setup["enrolment"]
    response = client.post(
        f"/student/enrolments/{enrolment.id}/dispute",
        headers=auth("student"),
        json={"reason": "I never applied to or joined this institution.", "category": "not_my_enrolment"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["confirmation"] == "disputed"
    assert body["flag"]["type"] == "STUDENT_DISPUTE"
    assert body["flag"]["severity"] == "critical"
    assert "AICTE has been notified" in body["message"]

    flag = db.execute(select(Flag).where(Flag.type == "STUDENT_DISPUTE")).scalars().one()
    assert flag.institution_id == student_setup["first"].id
    assert flag.student_id == student_setup["student"].id
    assert flag.evidence["raised_by"] == "student"
    assert "never applied" in flag.explanation


def test_a_dispute_does_not_change_the_enrolment_status(
    client: TestClient, auth, student_setup, db: Session
) -> None:
    """Step-0 decision 8: AICTE resolves it; the record is not silently altered."""
    enrolment = student_setup["enrolment"]
    client.post(
        f"/student/enrolments/{enrolment.id}/dispute",
        headers=auth("student"),
        json={"reason": "I never joined this college at all.", "category": "not_my_enrolment"},
    )
    db.expire_all()
    refreshed = db.get(Enrolment, enrolment.id)
    assert refreshed.status == "admitted"
    assert refreshed.student_confirmation == "disputed"
    assert refreshed.version == 1


def test_the_college_sees_the_dispute_in_its_own_inbox(
    client: TestClient, auth, student_setup
) -> None:
    enrolment = student_setup["enrolment"]
    client.post(
        f"/student/enrolments/{enrolment.id}/dispute",
        headers=auth("student"),
        json={"reason": "This enrolment was never mine.", "category": "not_my_enrolment"},
    )
    inbox = client.get("/institution/flags", headers=auth("institution")).json()
    assert inbox["total"] == 1
    assert inbox["items"][0]["type"] == "STUDENT_DISPUTE"
    assert inbox["items"][0]["severity"] == "critical"


def test_a_dispute_needs_a_real_reason_and_a_known_category(
    client: TestClient, auth, student_setup
) -> None:
    enrolment = student_setup["enrolment"]
    headers = auth("student")
    short = client.post(
        f"/student/enrolments/{enrolment.id}/dispute", headers=headers, json={"reason": "no"}
    )
    assert short.status_code == 422
    bad_category = client.post(
        f"/student/enrolments/{enrolment.id}/dispute",
        headers=headers,
        json={"reason": "A perfectly adequate reason.", "category": "made_up"},
    )
    assert bad_category.status_code == 422


# ------------------------------------------------------------------ corrections


def test_a_correction_request_reaches_the_institution(
    client: TestClient, auth, student_setup, db: Session
) -> None:
    response = client.post(
        "/student/corrections",
        headers=auth("student"),
        json={
            "enrolment_id": student_setup["enrolment"].id,
            "field": "category",
            "correct_value": "EWS",
            "note": "Fresh certificate issued in July 2026.",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "sent_to_institution"
    assert body["institution_name"] == student_setup["first"].name

    assert db.execute(select(CorrectionRequest)).scalars().one().field == "category"
    inbox = client.get("/institution/flags", headers=auth("institution")).json()
    assert any("correction request" in row["title"] for row in inbox["items"])

    listed = client.get("/student/corrections", headers=auth("student")).json()
    assert listed["total"] == 1
    assert listed["items"][0]["correct_value"] == "EWS"


# ------------------------------------------------------------------ access log


def test_student_sees_who_accessed_their_data_with_role_labels(
    client: TestClient, auth, student_setup, db: Session
) -> None:
    student = student_setup["student"]
    # An officer reveals their details.
    client.post(
        "/aicte/reveal",
        headers=auth("aicte_officer"),
        json={"student_id": student.id, "reason": "Checking a duplicate enrolment case."},
    )

    body = client.get("/student/access-log", headers=auth("student")).json()
    assert body["total"] >= 1
    row = body["items"][0]
    assert row["actor_role"] == "aicte_officer"
    assert row["actor_label"] == "AICTE Officer"
    assert "Checking a duplicate" in row["reason"]
    # The officer's username is not shown to the student.
    assert "aicte_officer1" not in json.dumps(body)


def test_access_log_is_scoped_to_the_student(
    client: TestClient, auth, student_setup, db: Session
) -> None:
    other = Student(apaar_masked="XXXX-XXXX-7777", name_masked="Z**** Q.")
    db.add(other)
    db.flush()
    db.add(
        AccessLog(
            actor="aicte_officer1",
            role="aicte_officer",
            action="reveal_student_details",
            target=f"student:{other.id}",
            student_id=other.id,
            reason="Someone else's case entirely.",
        )
    )
    db.commit()

    body = client.get("/student/access-log", headers=auth("student")).json()
    assert all(row["target"] != f"student:{other.id}" for row in body["items"])


# ------------------------------------------------------------------ verifier flow


def test_verifier_learns_nothing_before_the_student_approves(
    client: TestClient, auth, student_setup, db: Session
) -> None:
    """CLAUDE.md section 5 rule 11."""
    created = client.post(
        "/verifier/requests",
        headers=auth("verifier"),
        json={"apaar": APAAR, "purpose": "employment_verification", "note": "Offer stage"},
    )
    assert created.status_code == 201
    body = created.json()
    assert body["status"] == "pending"
    assert body["apaar_masked"] == "XXXX-XXXX-1234"
    assert body["parental_consent_required"] is False
    assert "No data is shared until they approve" in body["message"]

    status_body = client.get(f"/verifier/requests/{body['request_id']}", headers=auth("verifier")).json()
    assert status_body["status"] == "pending"
    assert status_body["result"] is None
    # Nothing about the student leaks into the pending response.
    blob = json.dumps(status_body)
    assert "Rahul" not in blob
    assert "B.Tech" not in blob


def test_an_unknown_apaar_looks_identical_to_a_known_one(
    client: TestClient, auth, student_setup
) -> None:
    """Step-0 decision 10: the endpoint must not reveal which APAAR IDs exist."""
    known = client.post(
        "/verifier/requests",
        headers=auth("verifier"),
        json={"apaar": APAAR, "purpose": "employment_verification"},
    ).json()
    unknown = client.post(
        "/verifier/requests",
        headers=auth("verifier"),
        json={"apaar": "999988887777", "purpose": "employment_verification"},
    ).json()

    assert known["status"] == unknown["status"] == "pending"
    assert known["message"] == unknown["message"]
    assert known["notification"] == unknown["notification"]
    assert set(known) == set(unknown)


def test_the_raw_apaar_is_never_stored_by_a_request(
    client: TestClient, auth, student_setup, db: Session
) -> None:
    client.post(
        "/verifier/requests",
        headers=auth("verifier"),
        json={"apaar": APAAR, "purpose": "employment_verification"},
    )
    request = db.execute(select(VerificationRequest)).scalars().first()
    assert request.apaar_masked == "XXXX-XXXX-1234"
    assert request.apaar_hash == hash_apaar(APAAR)
    assert APAAR not in json.dumps(
        {key: str(value) for key, value in vars(request).items() if not key.startswith("_")}
    )


def test_a_free_text_purpose_is_rejected(client: TestClient, auth, student_setup) -> None:
    response = client.post(
        "/verifier/requests",
        headers=auth("verifier"),
        json={"apaar": APAAR, "purpose": "because I feel like it"},
    )
    assert response.status_code == 422


def test_purposes_are_a_fixed_list(client: TestClient, auth, student_setup) -> None:
    body = client.get("/verifier/purposes", headers=auth("verifier")).json()
    values = {item["value"] for item in body["purposes"]}
    assert "employment_verification" in values
    assert all(item["label"] for item in body["purposes"])


def test_approval_gives_the_verifier_the_minimal_result_only(
    client: TestClient, auth, student_setup, db: Session
) -> None:
    created = client.post(
        "/verifier/requests",
        headers=auth("verifier"),
        json={"apaar": APAAR, "purpose": "employment_verification"},
    ).json()
    consent_id = created["consent_id"]

    approved = client.post(f"/student/consents/{consent_id}/approve", headers=auth("student"), json={})
    assert approved.status_code == 200
    assert approved.json()["shared_fields"] == ["verified", "program", "academic_year"]

    body = client.get(f"/verifier/requests/{created['request_id']}", headers=auth("verifier")).json()
    assert body["status"] == "approved"
    assert body["result"] == {
        "verified": True,
        "program": "B.Tech — Computer Science and Engineering",
        "academic_year": YEAR,
    }
    # Nothing else: no name, no DOB, no institution, no flags.
    blob = json.dumps(body)
    for leak in ("Rahul", "2006-03-12", student_setup["first"].name, "XXXX-XXXX-1234"):
        if leak == "XXXX-XXXX-1234":
            continue  # the masked id the verifier already supplied is fine
        assert leak not in blob


def test_reading_an_approved_result_is_access_logged(
    client: TestClient, auth, student_setup, db: Session
) -> None:
    created = client.post(
        "/verifier/requests",
        headers=auth("verifier"),
        json={"apaar": APAAR, "purpose": "scholarship"},
    ).json()
    client.post(f"/student/consents/{created['consent_id']}/approve", headers=auth("student"), json={})
    client.get(f"/verifier/requests/{created['request_id']}", headers=auth("verifier"))

    actions = {
        row.action
        for row in db.execute(
            select(AccessLog).where(AccessLog.student_id == student_setup["student"].id)
        ).scalars()
    }
    assert "verification_requested" in actions
    assert "verification_result_read" in actions

    # And the student can see both in their own timeline.
    body = client.get("/student/access-log", headers=auth("student")).json()
    labels = {row["actor_label"] for row in body["items"]}
    assert "Employer / verifier" in labels


def test_denied_and_expired_requests_carry_no_result(
    client: TestClient, auth, student_setup, db: Session
) -> None:
    denied = client.post(
        "/verifier/requests",
        headers=auth("verifier"),
        json={"apaar": APAAR, "purpose": "employment_verification"},
    ).json()
    client.post(
        f"/student/consents/{denied['consent_id']}/deny",
        headers=auth("student"),
        json={"reason": "I did not apply to this employer."},
    )
    body = client.get(f"/verifier/requests/{denied['request_id']}", headers=auth("verifier")).json()
    assert body["status"] == "denied"
    assert body["result"] is None

    # Expiry: push the request and consent into the past.
    expired = client.post(
        "/verifier/requests",
        headers=auth("verifier"),
        json={"apaar": APAAR, "purpose": "scholarship"},
    ).json()
    past = datetime.utcnow() - timedelta(hours=1)
    db.get(VerificationRequest, expired["request_id"]).expires_at = past
    db.get(Consent, expired["consent_id"]).expires_at = past
    db.commit()

    body = client.get(f"/verifier/requests/{expired['request_id']}", headers=auth("verifier")).json()
    assert body["status"] == "expired"
    assert body["result"] is None


def test_a_verifier_cannot_read_another_verifiers_request(
    client: TestClient, auth, student_setup, db: Session
) -> None:
    created = client.post(
        "/verifier/requests",
        headers=auth("verifier"),
        json={"apaar": APAAR, "purpose": "employment_verification"},
    ).json()
    from app.services.users import DemoAccount, upsert_user

    upsert_user(
        db,
        DemoAccount(
            username="verifier_two",
            role="verifier",
            display_name="Brahmaputri Analytics LLP",
            label="Second employer",
            verifier_name="Brahmaputri Analytics LLP",
            verifier_type="employer",
        ),
    )
    db.commit()
    assert (
        client.get(f"/verifier/requests/{created['request_id']}", headers=auth("verifier_two")).status_code
        == 404
    )


def test_verifier_routes_refuse_other_roles(client: TestClient, auth, student_setup) -> None:
    for role in ("institution", "student", "aicte_officer", "aicte_viewer", "admin"):
        assert client.get("/verifier/purposes", headers=auth(role)).status_code == 403
        assert client.get("/verifier/requests", headers=auth(role)).status_code == 403


# ------------------------------------------------------------------ minors


def test_a_minor_is_marked_as_needing_parental_consent(
    client: TestClient, auth, student_setup, db: Session
) -> None:
    """CLAUDE.md section 5 rule 12."""
    student_setup["student"].is_minor = True
    db.commit()

    body = client.post(
        "/verifier/requests",
        headers=auth("verifier"),
        json={"apaar": APAAR, "purpose": "higher_education_admission"},
    ).json()
    assert body["parental_consent_required"] is True
    assert "parental consent" in body["message"]

    consents = client.get("/student/consents", headers=auth("student")).json()
    assert consents["items"][0]["parental_consent_required"] is True


# ------------------------------------------------------------------ consent management


def test_consent_list_shows_what_will_be_shared(client: TestClient, auth, student_setup) -> None:
    client.post(
        "/verifier/requests",
        headers=auth("verifier"),
        json={"apaar": APAAR, "purpose": "employment_verification"},
    )
    body = client.get("/student/consents", headers=auth("student")).json()
    row = body["items"][0]
    assert row["status"] == "pending"
    assert row["verifier_name"] == "Nilgiri Softworks Pvt Ltd"
    assert row["purpose_label"] == "Employment background verification"
    assert row["will_share"] == ["verified yes/no", "programme", "academic year"]


def test_answering_the_same_request_twice_is_a_conflict(
    client: TestClient, auth, student_setup
) -> None:
    created = client.post(
        "/verifier/requests",
        headers=auth("verifier"),
        json={"apaar": APAAR, "purpose": "employment_verification"},
    ).json()
    headers = auth("student")
    assert client.post(f"/student/consents/{created['consent_id']}/approve", headers=headers, json={}).status_code == 200
    assert client.post(f"/student/consents/{created['consent_id']}/deny", headers=headers, json={}).status_code == 409


def test_a_student_cannot_answer_another_students_consent(
    client: TestClient, auth, student_setup, db: Session
) -> None:
    other = Student(apaar_masked="XXXX-XXXX-5555", name_masked="Y**** X.")
    db.add(other)
    db.flush()
    consent = Consent(
        student_id=other.id,
        verifier_name="Nilgiri Softworks Pvt Ltd",
        purpose="employment_verification",
        status="pending",
        requested_at=datetime.utcnow(),
    )
    db.add(consent)
    db.commit()
    assert (
        client.post(f"/student/consents/{consent.id}/approve", headers=auth("student"), json={}).status_code
        == 404
    )


# ------------------------------------------------------------------ tokens


def test_id_card_carries_a_masked_apaar_and_a_signed_qr(
    client: TestClient, auth, student_setup
) -> None:
    body = client.get("/student/id-card", headers=auth("student")).json()
    assert body["apaar_masked"] == "XXXX-XXXX-1234"
    assert body["name"] == "Rahul Sharma"
    assert body["program"].startswith("B.Tech")
    assert body["qr_png_base64"].startswith("iVBOR")  # PNG magic bytes in base64
    assert body["verify_url"].endswith(body["token"])
    payload, state = parse_token(body["token"])
    assert state == "genuine"
    assert payload.student_id == student_setup["student"].id


def test_token_check_is_public_and_returns_the_minimal_result(
    client: TestClient, auth, student_setup
) -> None:
    token = client.get("/student/id-card", headers=auth("student")).json()["token"]
    body = client.get(f"/verify/token/{token}").json()  # no Authorization header
    assert body["state"] == "genuine"
    assert body["verified"] is True
    assert body["program"].startswith("B.Tech")
    assert body["academic_year"] == YEAR
    assert "name" not in body


def test_a_tampered_token_is_invalid(client: TestClient, auth, student_setup) -> None:
    token = client.get("/student/id-card", headers=auth("student")).json()["token"]
    for broken in (token[:-4] + "0000", token.replace("v1.", "v2."), "nonsense", ""):
        body = client.get(f"/verify/token/{broken or 'x'}").json()
        assert body["state"] == "invalid", broken
        assert body.get("verified") is None
        assert body.get("program") is None


def test_changing_the_student_id_inside_a_token_is_invalid(
    client: TestClient, auth, student_setup
) -> None:
    """The signature covers the student id, so it cannot be swapped."""
    token = client.get("/student/id-card", headers=auth("student")).json()["token"]
    parts = token.split(".")
    parts[1] = str(int(parts[1]) + 1)
    assert client.get(f"/verify/token/{'.'.join(parts)}").json()["state"] == "invalid"


def test_an_expired_token_says_expired(client: TestClient, student_setup) -> None:
    token, _expires = issue_token(student_id=student_setup["student"].id, ttl_minutes=-5)
    body = client.get(f"/verify/token/{token}").json()
    assert body["state"] == "expired"
    assert body.get("program") is None


def test_revoking_consent_invalidates_the_token_immediately(
    client: TestClient, auth, student_setup, db: Session
) -> None:
    created = client.post(
        "/verifier/requests",
        headers=auth("verifier"),
        json={"apaar": APAAR, "purpose": "employment_verification"},
    ).json()
    consent_id = created["consent_id"]
    client.post(f"/student/consents/{consent_id}/approve", headers=auth("student"), json={})

    token, _expires = issue_token(student_id=student_setup["student"].id, consent_id=consent_id)
    assert client.get(f"/verify/token/{token}").json()["state"] == "genuine"

    revoked = client.post(f"/student/consents/{consent_id}/revoke", headers=auth("student"))
    assert revoked.status_code == 200
    assert revoked.json()["tokens_invalidated"] == 1

    body = client.get(f"/verify/token/{token}").json()
    assert body["state"] == "revoked"
    assert body.get("program") is None

    # And the verifier's result disappears with it.
    status_body = client.get(f"/verifier/requests/{created['request_id']}", headers=auth("verifier")).json()
    assert status_body["status"] == "revoked"
    assert status_body["result"] is None


def test_every_token_check_is_audited(client: TestClient, auth, student_setup, db: Session) -> None:
    token = client.get("/student/id-card", headers=auth("student")).json()["token"]
    client.get(f"/verify/token/{token}")
    client.get("/verify/token/rubbish")
    states = [
        row.payload["state"]
        for row in db.execute(select(AuditLog).where(AuditLog.action == "token_checked")).scalars()
    ]
    assert "genuine" in states
    assert "invalid" in states
