"""Step 11: anomaly detection, risk scoring and the inspection shortlist."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.core import (
    ApprovedIntake,
    Enrolment,
    Flag,
    Institution,
    InstitutionRisk,
    Program,
    Student,
)
from app.services.risk import (
    FEATURE_NAMES,
    FLAG_TYPE_WEIGHTS,
    compute_features,
    compute_risk,
    detect_statistical_anomalies,
    inspection_shortlist,
)
from app.services.rules import supernumerary_caps

YEAR = "2026-27"
REPO = Path(__file__).resolve().parents[2]
EVALUATION = REPO / "docs" / "EVALUATION.md"


@pytest.fixture()
def seeded_states(db: Session) -> list[Institution]:
    """12 institutions in one state, each with a filled programme, so the model can fit."""
    institutions: list[Institution] = []
    for index in range(12):
        institution = Institution(
            aicte_permanent_id=f"1-90000000{index:02d}",
            name=f"Kaveripura {index} Institute of Technology",
            state="Karnataka",
            region="South",
            type="private_unaided",
        )
        db.add(institution)
        db.flush()
        program = Program(
            institution_id=institution.id,
            course="B.Tech",
            branch="Computer Science and Engineering",
            level="UG",
            mode="regular",
        )
        db.add(program)
        db.flush()
        db.add(
            ApprovedIntake(
                program_id=program.id,
                academic_year=YEAR,
                intake=120,
                supernumerary_caps=supernumerary_caps(120),
            )
        )
        for _ in range(100):
            student = Student(
                apaar_masked="XXXX-XXXX-0000",
                name_masked="S**** T.",
                category="GEN",
                gender="M",
                registry_status="match",
            )
            db.add(student)
            db.flush()
            db.add(
                Enrolment(
                    student_id=student.id,
                    program_id=program.id,
                    institution_id=institution.id,
                    academic_year=YEAR,
                    year_of_study=1,
                    admission_type="regular",
                    status="admitted",
                    admitted_on=date(2026, 8, 1),
                )
            )
        institutions.append(institution)
    db.commit()
    return institutions


# ------------------------------------------------------------------ features


def test_features_are_computed_for_every_institution(db: Session, seeded_states) -> None:
    features = compute_features(db, academic_year=YEAR)
    assert len(features) == 12
    for row in features:
        assert set(row.values) == set(FEATURE_NAMES)
    normal = features[0]
    assert normal.values["fill_ratio"] == pytest.approx(100 / 120, abs=0.01)
    assert normal.values["late_admission_pct"] == 0.0
    assert normal.values["missing_or_invalid_apaar_pct"] == 0.0


def test_an_outlier_shows_up_in_its_features(db: Session, seeded_states) -> None:
    """Give one institution a skewed category mix and bad APAAR data."""
    odd = seeded_states[0]
    for student in db.execute(
        select(Student)
        .join(Enrolment, Enrolment.student_id == Student.id)
        .where(Enrolment.institution_id == odd.id)
        .limit(60)
    ).scalars():
        student.category = "ST"
        student.registry_status = "not_found"
    db.commit()

    features = {row.institution_id: row for row in compute_features(db, academic_year=YEAR)}
    assert features[odd.id].values["category_mix_distance"] > 0.3
    assert features[odd.id].values["missing_or_invalid_apaar_pct"] > 50
    assert features[seeded_states[1].id].values["category_mix_distance"] < 0.2


# ------------------------------------------------------------------ anomaly


def test_anomaly_flags_explain_themselves_against_the_state_median(
    db: Session, seeded_states
) -> None:
    odd = seeded_states[0]
    for student in db.execute(
        select(Student)
        .join(Enrolment, Enrolment.student_id == Student.id)
        .where(Enrolment.institution_id == odd.id)
        .limit(80)
    ).scalars():
        student.registry_status = "not_found"
        student.category = "ST"
    db.commit()

    summary = detect_statistical_anomalies(db, academic_year=YEAR, contamination=0.1)
    db.commit()
    assert summary["statistical_anomalies"] >= 1

    flags = list(db.execute(select(Flag).where(Flag.type == "STATISTICAL_ANOMALY")).scalars())
    assert odd.id in {flag.institution_id for flag in flags}
    flag = next(item for item in flags if item.institution_id == odd.id)
    assert flag.evidence["top_contributors"]
    top = flag.evidence["top_contributors"][0]
    assert {"feature", "label", "value", "state_median", "deviation_ratio", "direction"} <= set(top)
    # The explanation is a checkable comparison, not "the model said so".
    assert "state median" in flag.explanation
    assert "ranking signal" in flag.explanation
    assert flag.evidence["anomaly_score"] >= 0


def test_too_few_institutions_skips_the_model(db: Session, two_institutions) -> None:
    summary = detect_statistical_anomalies(db, academic_year=YEAR)
    assert summary["statistical_anomalies"] == 0


# ------------------------------------------------------------------ risk score


def _flag(db: Session, institution_id: int, type_: str, severity: str = "high") -> Flag:
    flag = Flag(
        type=type_,
        severity=severity,
        status="open",
        institution_id=institution_id,
        title=f"{type_} title",
        explanation=f"A clear explanation of the {type_} finding. Second sentence ignored.",
        evidence={},
        dedupe_key=f"{institution_id}:{type_}",
        notes=[],
    )
    db.add(flag)
    db.commit()
    return flag


def test_risk_score_rises_with_flag_weight_and_severity(db: Session, seeded_states) -> None:
    light, heavy = seeded_states[0], seeded_states[1]
    _flag(db, light.id, "LATE_ADMISSION", "medium")
    _flag(db, heavy.id, "GHOST_CLUSTER", "critical")

    results = {row["institution_id"]: row for row in compute_risk(db, academic_year=YEAR)}
    db.commit()
    assert results[heavy.id]["risk_score"] > results[light.id]["risk_score"]
    assert results[heavy.id]["band"] in ("high", "critical")


def test_every_institution_gets_three_reasons_in_plain_english(
    db: Session, seeded_states
) -> None:
    institution = seeded_states[0]
    for type_ in ("GHOST_CLUSTER", "EXCESS_INTAKE", "SEQUENTIAL_APAAR", "LATE_ADMISSION"):
        _flag(db, institution.id, type_)

    results = {row["institution_id"]: row for row in compute_risk(db, academic_year=YEAR)}
    db.commit()
    reasons = results[institution.id]["top_reasons"]
    assert len(reasons) == 3
    assert all(reason.endswith(".") for reason in reasons)
    # Highest-weighted flag first.
    assert "GHOST_CLUSTER" in reasons[0]


def test_a_clean_institution_scores_zero_and_says_so(db: Session, seeded_states) -> None:
    results = {row["institution_id"]: row for row in compute_risk(db, academic_year=YEAR)}
    db.commit()
    clean = results[seeded_states[3].id]
    assert clean["risk_score"] == 0.0
    assert clean["band"] == "low"
    assert "No open findings" in clean["top_reasons"][0]


def test_a_legal_dual_degree_never_adds_risk(db: Session, seeded_states) -> None:
    assert FLAG_TYPE_WEIGHTS["POSSIBLE_DUAL_DEGREE"] == 0.0
    institution = seeded_states[0]
    _flag(db, institution.id, "POSSIBLE_DUAL_DEGREE", "low")
    results = {row["institution_id"]: row for row in compute_risk(db, academic_year=YEAR)}
    db.commit()
    assert results[institution.id]["risk_score"] == 0.0


def test_dismissed_flags_stop_counting(db: Session, seeded_states) -> None:
    institution = seeded_states[0]
    flag = _flag(db, institution.id, "GHOST_CLUSTER", "critical")
    before = {row["institution_id"]: row for row in compute_risk(db, academic_year=YEAR)}
    db.commit()

    flag.status = "dismissed"
    db.commit()
    after = {row["institution_id"]: row for row in compute_risk(db, academic_year=YEAR)}
    db.commit()
    assert after[institution.id]["risk_score"] < before[institution.id]["risk_score"]


def test_risk_is_stored_and_overwritten_not_duplicated(db: Session, seeded_states) -> None:
    _flag(db, seeded_states[0].id, "EXCESS_INTAKE")
    compute_risk(db, academic_year=YEAR)
    db.commit()
    compute_risk(db, academic_year=YEAR)
    db.commit()
    rows = list(db.execute(select(InstitutionRisk)).scalars())
    assert len(rows) == 12
    assert len({row.institution_id for row in rows}) == 12


# ------------------------------------------------------------------ shortlist


def test_shortlist_is_ranked_and_suggests_concrete_checks(db: Session, seeded_states) -> None:
    _flag(db, seeded_states[0].id, "GHOST_CLUSTER", "critical")
    _flag(db, seeded_states[1].id, "EXCESS_INTAKE", "high")
    compute_risk(db, academic_year=YEAR)
    db.commit()

    items = inspection_shortlist(db, limit=5)
    assert items[0]["rank"] == 1
    assert items[0]["institution_id"] == seeded_states[0].id
    assert items[0]["reasons"]
    assert "guardian contacts" in " ".join(items[0]["suggested_checks"]).lower()
    assert "headcount" in " ".join(items[1]["suggested_checks"]).lower()


# ------------------------------------------------------------------ routes


def test_risk_and_shortlist_routes(client: TestClient, auth, db: Session, seeded_states) -> None:
    _flag(db, seeded_states[0].id, "GHOST_CLUSTER", "critical")
    compute_risk(db, academic_year=YEAR)
    db.commit()

    # Filtered by state: the auth fixture also creates two institutions elsewhere.
    body = client.get("/aicte/risk?state=Karnataka", headers=auth("aicte_officer")).json()
    assert body["total"] == 12
    assert body["items"][0]["risk_score"] > 0
    assert body["items"][0]["top_reasons"]

    shortlist = client.get("/aicte/inspection-shortlist?limit=3", headers=auth("aicte_viewer")).json()
    assert len(shortlist["items"]) == 3
    assert shortlist["items"][0]["suggested_checks"]
    assert shortlist["csv_url"] == "/aicte/inspection-shortlist.csv"

    csv_text = client.get(
        "/aicte/inspection-shortlist.csv?limit=3", headers=auth("aicte_officer")
    ).text
    assert csv_text.splitlines()[0].startswith("rank,institution_id")
    assert len(csv_text.strip().splitlines()) == 4


def test_risk_routes_enforce_roles(client: TestClient, auth) -> None:
    for role in ("institution", "student", "verifier", "admin"):
        assert client.get("/aicte/risk", headers=auth(role)).status_code == 403
        assert client.get("/aicte/inspection-shortlist", headers=auth(role)).status_code == 403


# ------------------------------------------------------------------ the evaluation report


@pytest.mark.skipif(not EVALUATION.exists(), reason="run `make eval` first")
def test_evaluation_report_states_its_limitations() -> None:
    """The numbers must never be presented without the caveat."""
    text = EVALUATION.read_text()
    assert "Precision" in text
    assert "Recall" in text
    assert "What these numbers do and do not show" in text
    assert "not* evidence of accuracy on" in text or "not evidence of accuracy" in text
    assert "Legal dual degrees wrongly flagged as fraud" in text


# ------------------------------------------------------------------ supernumerary misuse


def _add_supernumerary(db: Session, institution: Institution, *, tfw: int, regular: int) -> None:
    program = db.execute(
        select(Program).where(Program.institution_id == institution.id)
    ).scalars().first()
    for index in range(tfw + regular):
        student = Student(apaar_masked="XXXX-XXXX-1111", name_masked="S**** T.")
        db.add(student)
        db.flush()
        db.add(
            Enrolment(
                student_id=student.id,
                program_id=program.id,
                institution_id=institution.id,
                academic_year=YEAR,
                year_of_study=1,
                admission_type="tfw" if index < tfw else "regular",
                status="admitted",
                admitted_on=date(2026, 8, 1),
            )
        )
    db.commit()


def test_supernumerary_share_far_above_peers_is_flagged_for_review(
    db: Session, seeded_states
) -> None:
    from app.services.risk import detect_supernumerary_misuse

    # Peers report a couple of TFW admissions each; one institution reports many.
    for institution in seeded_states[1:]:
        _add_supernumerary(db, institution, tfw=2, regular=0)
    _add_supernumerary(db, seeded_states[0], tfw=20, regular=0)

    summary = detect_supernumerary_misuse(db, academic_year=YEAR)
    db.commit()
    assert summary["supernumerary_misuse"] == 1

    flag = db.execute(
        select(Flag).where(Flag.type == "STATISTICAL_ANOMALY")
    ).scalars().one()
    assert flag.institution_id == seeded_states[0].id
    assert flag.evidence["signal"] == "supernumerary_share"
    assert flag.severity == "medium"  # a signal, not a finding
    # It must explain itself as a possibility, not a conclusion.
    assert "possible mislabelling of regular admissions" in flag.explanation
    assert "not proof" in flag.explanation
    assert flag.evidence["peer_median_percent"] < flag.evidence["share_percent"]
    assert flag.evidence["denominator"] == "year-1 entrants plus lateral entrants"


def test_a_thin_supernumerary_share_is_not_flagged(db: Session, seeded_states) -> None:
    """A 100% share built from 5 students is noise, not a signal."""
    from app.services.risk import detect_supernumerary_misuse

    for institution in seeded_states[1:]:
        _add_supernumerary(db, institution, tfw=1, regular=0)
    _add_supernumerary(db, seeded_states[0], tfw=5, regular=0)

    summary = detect_supernumerary_misuse(db, academic_year=YEAR)
    db.commit()
    assert summary["supernumerary_misuse"] == 0


def test_the_misuse_signal_is_never_reported_as_excess_intake(
    db: Session, seeded_states
) -> None:
    """Within-cap supernumerary use must not become an intake breach."""
    from app.services.intake import run_intake_compliance
    from app.services.risk import detect_supernumerary_misuse

    for institution in seeded_states[1:]:
        _add_supernumerary(db, institution, tfw=2, regular=0)
    _add_supernumerary(db, seeded_states[0], tfw=6, regular=0)  # cap is 6 for intake 120

    detect_supernumerary_misuse(db, academic_year=YEAR)
    run_intake_compliance(db, academic_year=YEAR)
    db.commit()
    assert db.execute(select(Flag).where(Flag.type == "EXCESS_INTAKE")).scalars().first() is None


def test_the_two_statistical_anomaly_detectors_do_not_close_each_others_flags(
    db: Session, seeded_states
) -> None:
    """Both write STATISTICAL_ANOMALY; each must reconcile only its own keys."""
    from app.services.risk import detect_statistical_anomalies, detect_supernumerary_misuse

    for institution in seeded_states[1:]:
        _add_supernumerary(db, institution, tfw=2, regular=0)
    _add_supernumerary(db, seeded_states[0], tfw=20, regular=0)
    for student in db.execute(
        select(Student)
        .join(Enrolment, Enrolment.student_id == Student.id)
        .where(Enrolment.institution_id == seeded_states[1].id)
        .limit(60)
    ).scalars():
        student.registry_status = "not_found"
    db.commit()

    detect_supernumerary_misuse(db, academic_year=YEAR)
    db.commit()
    detect_statistical_anomalies(db, academic_year=YEAR, contamination=0.1)
    db.commit()
    detect_supernumerary_misuse(db, academic_year=YEAR)
    db.commit()

    flags = list(db.execute(select(Flag).where(Flag.type == "STATISTICAL_ANOMALY")).scalars())
    signals = [(flag.evidence or {}).get("signal") for flag in flags]
    assert "supernumerary_share" in signals
    open_misuse = [
        flag
        for flag in flags
        if (flag.evidence or {}).get("signal") == "supernumerary_share"
        and flag.status == "open"
    ]
    assert open_misuse, "the IsolationForest detector closed the misuse flag"


def test_the_misuse_signal_adds_only_modest_risk(db: Session, seeded_states) -> None:
    from app.services.risk import FLAG_TYPE_WEIGHTS

    assert FLAG_TYPE_WEIGHTS["STATISTICAL_ANOMALY"] < FLAG_TYPE_WEIGHTS["EXCESS_INTAKE"]
    assert FLAG_TYPE_WEIGHTS["STATISTICAL_ANOMALY"] < FLAG_TYPE_WEIGHTS["GHOST_CLUSTER"]
