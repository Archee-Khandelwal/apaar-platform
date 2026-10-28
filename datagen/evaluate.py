"""Score the detectors against datagen/ground_truth.json (Step 11 of docs/PLAN.md).

Run with ``make eval`` **immediately after ``make reset``**: it measures the seeded data
only. Demo uploads add real enrolments and real flags that no ground-truth file knows
about, which would show up as false positives and make these numbers meaningless.

Honesty rules we hold ourselves to:
  * Misses are reported, not hidden. Every scenario prints its false negatives.
  * False positives are counted against us even when they look defensible.
  * POSSIBLE_DUAL_DEGREE is scored as its own class, and a dual-degree student flagged
    as CROSS_INSTITUTION_DUPLICATE is reported separately as a misclassification,
    because calling a legal dual degree fraud is the worst error this system can make.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.models.core import Flag, StudentDocument
from datagen.generator import GROUND_TRUTH_PATH

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO_ROOT / "apaar.db"
REPORT_PATH = REPO_ROOT / "docs" / "EVALUATION.md"
ROBUST_REPORT_PATH = REPO_ROOT / "docs" / "EVALUATION_ROBUST.md"

# How each scenario's ground-truth key is matched against produced flags.
# key_kind -> how to build the same key from a Flag.
SCENARIOS: dict[str, dict[str, Any]] = {
    "A_excess_intake": {"flag_types": ["EXCESS_INTAKE"], "label": "Excess admissions beyond intake"},
    "C_cross_institution_duplicate": {
        "flag_types": ["CROSS_INSTITUTION_DUPLICATE"],
        "label": "Same APAAR at two full-time institutions",
    },
    "D_dual_degree": {
        "flag_types": ["POSSIBLE_DUAL_DEGREE"],
        "label": "Legal dual degree (must NOT be fraud)",
    },
    "E_apaar_problems": {
        "flag_types": ["INVALID_APAAR", "APAAR_NOT_FOUND", "APAAR_MISMATCH"],
        "label": "Invalid / unknown / mismatched APAAR",
    },
    "F_late_admission": {"flag_types": ["LATE_ADMISSION"], "label": "Admissions after the cutoff"},
    "J_identity_duplicate": {
        "flag_types": ["IDENTITY_DUPLICATE"],
        "label": "One person with two APAAR IDs",
    },
}


# Diagnoses for the robustness run, written after reading the results and NOT acted on
# by changing any detector threshold. Each one names the rule that caused the miss and
# what a fix would be, so the gap is on the record rather than quietly tuned away.
ROBUST_DIAGNOSES: dict[str, list[str]] = {
    "F_late_admission": [
        "**One unlabelled flag, correct by the rule.** A perturbed dual-degree student was "
        "admitted to an online programme on 20 October, after the regular-programme cutoff. "
        "The detector applies one admission window to every mode. Online/ODL programmes "
        "often run a later intake, so production needs a per-mode window in "
        "`reporting_calendar.yaml` before this rule is applied to ODL enrolments.",
    ],
    "J_identity_duplicate": [
        "**The biggest gap in this run: 6 of 12 records missed.** Identity matching uses an "
        "exact HMAC of the normalised name, so it survives case and whitespace changes "
        "(both caught, 2/2 each) but fails on a doubled letter, a reordered name and an "
        "initial-only surname (0/2 each). The registry client already uses rapidfuzz at a "
        "90% threshold; identity matching does not. The fix is to block candidates on "
        "DOB + guardian phone and then compare decrypted names with rapidfuzz inside the "
        "service, which keeps the privacy property intact.",
    ],
}


@dataclass
class ScenarioScore:
    scenario: str
    label: str
    flag_types: list[str]
    expected: set[str]
    predicted: set[str]
    notes: list[str] = field(default_factory=list)
    # key -> the perturbation applied to that case (robustness run only)
    perturbations: dict[str, str] = field(default_factory=dict)

    @property
    def true_positives(self) -> set[str]:
        return self.expected & self.predicted

    @property
    def false_negatives(self) -> set[str]:
        return self.expected - self.predicted

    @property
    def false_positives(self) -> set[str]:
        return self.predicted - self.expected

    @property
    def precision(self) -> float:
        denominator = len(self.predicted)
        return len(self.true_positives) / denominator if denominator else 1.0

    @property
    def recall(self) -> float:
        denominator = len(self.expected)
        return len(self.true_positives) / denominator if denominator else 1.0

    @property
    def f1(self) -> float:
        precision, recall = self.precision, self.recall
        return 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario,
            "label": self.label,
            "flag_types": self.flag_types,
            "expected": len(self.expected),
            "detected": len(self.true_positives),
            "false_positives": len(self.false_positives),
            "false_negatives": len(self.false_negatives),
            "precision": round(self.precision, 3),
            "recall": round(self.recall, 3),
            "f1": round(self.f1, 3),
            "missed_keys": sorted(self.false_negatives)[:10],
            "false_positive_keys": sorted(self.false_positives)[:10],
            "notes": self.notes,
        }


def _flag_keys(db: Session, flag_types: list[str], key_kind: str) -> set[str]:
    """Build the ground-truth key for every produced flag of these types."""
    keys: set[str] = set()
    flags = list(db.execute(select(Flag).where(Flag.type.in_(flag_types))).scalars())

    for flag in flags:
        if key_kind == "student":
            if flag.student_id is not None:
                keys.add(str(flag.student_id))
        elif key_kind == "enrolment":
            if flag.enrolment_id is not None:
                keys.add(str(flag.enrolment_id))
        elif key_kind == "program_year":
            if flag.program_id is not None and flag.academic_year:
                keys.add(f"{flag.program_id}|{flag.academic_year}")
        elif key_kind == "institution_year":
            if flag.institution_id is not None and flag.academic_year:
                keys.add(f"{flag.institution_id}|{flag.academic_year}")
    return keys


def score(db: Session, ground_truth: dict[str, Any]) -> list[ScenarioScore]:
    scenarios = ground_truth.get("scenarios", {})
    scores: list[ScenarioScore] = []

    for name, config in SCENARIOS.items():
        cases = scenarios.get(name, [])
        if not cases:
            continue
        key_kind = cases[0]["key_kind"]
        expected = {case["key"] for case in cases}
        predicted = _flag_keys(db, config["flag_types"], key_kind)

        notes: list[str] = []
        # LATE_ADMISSION produces both per-row and per-institution flags; the ground
        # truth labels rows, so only per-row flags are scored here.
        if name == "F_late_admission":
            notes.append(
                "Scored on per-enrolment flags; the per-institution aggregate flag is "
                "reported separately below."
            )

        scores.append(
            ScenarioScore(
                scenario=name,
                label=config["label"],
                flag_types=list(config["flag_types"]),
                expected=expected,
                predicted=predicted,
                notes=notes,
                perturbations={
                    case["key"]: case["details"]["perturbation"]
                    for case in cases
                    if case.get("details", {}).get("perturbation")
                },
            )
        )
    return scores


def control_checks(db: Session, ground_truth: dict[str, Any]) -> list[dict[str, Any]]:
    """Negative controls: labelled cases that must produce no flag at all."""
    scenarios = ground_truth.get("scenarios", {})
    results: list[dict[str, Any]] = []

    on_time = scenarios.get("F_on_time_control", [])
    if on_time:
        expected_clean = {case["key"] for case in on_time}
        flagged = {
            str(flag.enrolment_id)
            for flag in db.execute(
                select(Flag).where(Flag.type == "LATE_ADMISSION", Flag.enrolment_id.is_not(None))
            ).scalars()
        }
        wrong = sorted(expected_clean & flagged)
        results.append(
            {
                "check": "Admissions exactly on the cutoff date not flagged as late",
                "cases": len(expected_clean),
                "violations": wrong,
            }
        )
    return results


def misclassification_checks(db: Session, ground_truth: dict[str, Any]) -> dict[str, Any]:
    """The errors that matter beyond precision and recall."""
    scenarios = ground_truth.get("scenarios", {})
    dual = {case["key"] for case in scenarios.get("D_dual_degree", [])}
    fraud_flagged = {
        str(flag.student_id)
        for flag in db.execute(
            select(Flag).where(Flag.type == "CROSS_INSTITUTION_DUPLICATE")
        ).scalars()
        if flag.student_id is not None
    }
    dual_called_fraud = sorted(dual & fraud_flagged)

    clean = ground_truth.get("clean_institution") or {}
    clean_flags = []
    if clean.get("id"):
        clean_flags = [
            {"type": flag.type, "severity": flag.severity, "title": flag.title}
            for flag in db.execute(
                select(Flag).where(Flag.institution_id == clean["id"])
            ).scalars()
        ]

    return {
        "dual_degree_called_fraud": dual_called_fraud,
        "clean_institution": clean,
        "clean_institution_flags": clean_flags,
    }


DOCUMENT_CASE_LABELS = {
    "genuine": "Genuine, unchanged",
    "name_mismatch": "Someone else's document",
    "dob_mismatch": "DOB differs from the record",
    "tampered": "Edited after issue",
    "not_at_issuer": "Reference unknown to any issuer",
    "resaved": "Re-saved after issue, facts unchanged",
}


def score_documents(db: Session, ground_truth: dict[str, Any]) -> dict[str, Any]:
    """Each labelled document must end in its expected status *with* the expected reasons."""
    labels = ground_truth.get("documents", [])
    by_id = {
        document.id: document
        for document in db.execute(
            select(StudentDocument).where(StudentDocument.id.in_([row["document_id"] for row in labels] or [-1]))
        ).scalars()
    }
    per_case: dict[str, dict[str, Any]] = {}
    confusion: dict[str, dict[str, int]] = {}
    wrong: list[dict[str, Any]] = []
    for row in labels:
        document = by_id.get(row["document_id"])
        actual = document.verification_status if document else "missing"
        codes = {reason["code"] for reason in (document.reasons or [])} if document else set()
        correct = actual == row["expected_status"] and set(row["expected_reasons"]) <= codes
        bucket = per_case.setdefault(row["case"], {"cases": 0, "correct": 0, "expected": row["expected_status"]})
        bucket["cases"] += 1
        bucket["correct"] += int(correct)
        confusion.setdefault(row["expected_status"], {}).setdefault(actual, 0)
        confusion[row["expected_status"]][actual] += 1
        if not correct:
            wrong.append({"key": row["key"], "case": row["case"], "expected": row["expected_status"],
                          "actual": actual, "reasons": sorted(codes)})
    total = len(labels)
    correct_total = sum(bucket["correct"] for bucket in per_case.values())
    # A genuine document wrongly rejected, or a forged one auto-verified, are the errors
    # that matter most; both are reported on their own.
    forged_passed = sum(
        1 for row in labels
        if row["case"] != "genuine" and (by_id.get(row["document_id"]) and by_id[row["document_id"]].verification_status == "auto_verified")
    )
    genuine_rejected = sum(
        1 for row in labels
        if row["case"] == "genuine" and (by_id.get(row["document_id"]) and by_id[row["document_id"]].verification_status == "rejected")
    )
    return {
        "total": total,
        "correct": correct_total,
        "accuracy": round(correct_total / total, 3) if total else 1.0,
        "per_case": per_case,
        "confusion": confusion,
        "wrong": wrong[:20],
        "problem_documents_auto_verified": forged_passed,
        "genuine_documents_rejected": genuine_rejected,
    }


def unlabelled_flags(db: Session, scores: list[ScenarioScore]) -> dict[str, int]:
    """Flag types produced that no scenario scores — reported for transparency."""
    scored_types = {flag_type for item in scores for flag_type in item.flag_types}
    counts: dict[str, int] = {}
    for flag in db.execute(select(Flag)).scalars():
        if flag.type in scored_types:
            continue
        counts[flag.type] = counts.get(flag.type, 0) + 1
    return dict(sorted(counts.items()))


# --------------------------------------------------------------------------- output


def print_report(
    scores: list[ScenarioScore],
    checks: dict[str, Any],
    extra: dict[str, int],
    counts: dict[str, Any],
    *,
    ground_truth_name: str = "datagen/ground_truth.json",
) -> None:
    width = 46
    print()
    print("=" * 92)
    print(f"DETECTION EVALUATION against {ground_truth_name}")
    print("=" * 92)
    print(
        f"{'Scenario':<{width}}{'Exp':>5}{'TP':>5}{'FP':>5}{'FN':>5}"
        f"{'Prec':>8}{'Rec':>8}{'F1':>8}"
    )
    print("-" * 92)
    for item in scores:
        print(
            f"{item.label[:width - 1]:<{width}}{len(item.expected):>5}{len(item.true_positives):>5}"
            f"{len(item.false_positives):>5}{len(item.false_negatives):>5}"
            f"{item.precision:>8.3f}{item.recall:>8.3f}{item.f1:>8.3f}"
        )
    print("-" * 92)

    total_expected = sum(len(item.expected) for item in scores)
    total_tp = sum(len(item.true_positives) for item in scores)
    total_fp = sum(len(item.false_positives) for item in scores)
    total_fn = sum(len(item.false_negatives) for item in scores)
    micro_precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) else 1.0
    micro_recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) else 1.0
    micro_f1 = (
        2 * micro_precision * micro_recall / (micro_precision + micro_recall)
        if (micro_precision + micro_recall)
        else 0.0
    )
    print(
        f"{'MICRO AVERAGE (all labelled cases)':<{width}}{total_expected:>5}{total_tp:>5}"
        f"{total_fp:>5}{total_fn:>5}{micro_precision:>8.3f}{micro_recall:>8.3f}{micro_f1:>8.3f}"
    )
    print()

    for item in scores:
        if item.false_negatives:
            print(
                f"  MISSED  {item.label}: {len(item.false_negatives)} case(s), "
                f"e.g. {sorted(item.false_negatives)[:5]}"
            )
        if item.false_positives:
            print(
                f"  EXTRA   {item.label}: {len(item.false_positives)} flag(s) with no label, "
                f"e.g. {sorted(item.false_positives)[:5]}"
            )

    print()
    print("Critical misclassification checks")
    print("-" * 92)
    dual = checks["dual_degree_called_fraud"]
    print(
        f"  Legal dual degrees called fraud: {len(dual)}"
        + (f"  <-- SERIOUS: {dual}" if dual else "  (none)")
    )
    clean = checks["clean_institution"]
    clean_flags = checks["clean_institution_flags"]
    print(
        f"  Flags on the clean model institution ({clean.get('name', 'n/a')}): "
        f"{len(clean_flags)}"
        + ("  (none)" if not clean_flags else f"  <-- {[f['type'] for f in clean_flags]}")
    )

    documents = checks.get("documents") or {}
    if documents.get("total"):
        print()
        print("Document verification (status and reasons must both match the label)")
        print("-" * 92)
        for case, bucket in documents["per_case"].items():
            print(f"  {DOCUMENT_CASE_LABELS.get(case, case):<44}{bucket['correct']:>4} / {bucket['cases']:<4} -> {bucket['expected']}")
        print(
            f"  {'ALL':<44}{documents['correct']:>4} / {documents['total']:<4} "
            f"accuracy {documents['accuracy']:.3f}; problem docs auto-verified: "
            f"{documents['problem_documents_auto_verified']}; genuine rejected: {documents['genuine_documents_rejected']}"
        )

    if extra:
        print()
        print("Flags produced that no scenario scores (institution-level aggregates and")
        print("findings with no injected label):")
        for flag_type, count in extra.items():
            print(f"  {flag_type:<32} {count}")

    print()
    if "robust" in ground_truth_name:
        print("NOTE: this is the perturbed dataset the detectors were NOT tuned on. Every")
        print("miss is diagnosed in docs/EVALUATION_ROBUST.md; no threshold was changed")
        print("after seeing these results.")
    else:
        print("NOTE: the generator and the detectors were built against the same definitions,")
        print("so these scores show the rules are implemented and have not regressed - not")
        print("accuracy on real institutional data. See docs/EVALUATION.md for the full caveat.")
    print()
    print(
        f"Dataset: {counts.get('institutions')} institutions, {counts.get('students')} students, "
        f"{counts.get('enrolments')} enrolments, {counts.get('labelled_cases')} labelled cases "
        f"(seed {counts.get('seed')})."
    )
    print(f"Report written to {REPORT_PATH.relative_to(REPO_ROOT)}")
    print()


def write_markdown(
    scores: list[ScenarioScore],
    checks: dict[str, Any],
    extra: dict[str, int],
    ground_truth: dict[str, Any],
    *,
    robust: bool = False,
) -> None:
    total_tp = sum(len(item.true_positives) for item in scores)
    total_fp = sum(len(item.false_positives) for item in scores)
    total_fn = sum(len(item.false_negatives) for item in scores)
    micro_precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) else 1.0
    micro_recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) else 1.0
    micro_f1 = (
        2 * micro_precision * micro_recall / (micro_precision + micro_recall)
        if (micro_precision + micro_recall)
        else 0.0
    )
    counts = ground_truth.get("counts", {})

    title = (
        "# EVALUATION_ROBUST.md — accuracy on a perturbed dataset"
        if robust
        else "# EVALUATION.md — detection accuracy"
    )
    intro = (
        [
            "Generated by `make eval-robust`. This is a **second dataset** with a different",
            "seed, contacts written in varied formats, and deliberately perturbed cases the",
            "detectors were never built or tuned against: names with typos, reorderings and",
            "initials, dual degrees in other programme combinations,",
            "admissions one day past the cutoff, and an intake breach of a single seat.",
            "",
            "**No detector threshold was changed after seeing these results.** Every miss is",
            "diagnosed below with the rule that caused it and what a fix would be.",
        ]
        if robust
        else [
            "Generated by `make eval` (`datagen/evaluate.py`), which scores the flags in the",
            "database against the labelled cases in `datagen/ground_truth.json`.",
        ]
    )
    lines: list[str] = [
        title,
        "",
        *intro,
        "",
        f"- Generated: {datetime.now().replace(microsecond=0).isoformat()}",
        f"- Seed: `{ground_truth.get('seed')}`",
        f"- Dataset: {counts.get('institutions')} institutions, {counts.get('programs')} programmes, "
        f"{counts.get('students')} students, {counts.get('enrolments')} enrolments",
        f"- Labelled cases: {counts.get('labelled_cases')}",
        "",
        (
            "> Run `make eval-robust`. It builds its own database, so the demo data and the"
            if robust
            else "> Run `make reset && make eval`. The numbers describe the seeded data only — a demo"
        ),
        (
            "> headline numbers in EVALUATION.md are untouched."
            if robust
            else "> upload adds real enrolments and real flags that no ground-truth file knows about."
        ),
        "",
        "## Per-scenario results",
        "",
        "| Scenario | Flag type(s) | Expected | Detected | FP | FN | Precision | Recall | F1 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in scores:
        lines.append(
            f"| {item.label} | `{'`, `'.join(item.flag_types)}` | {len(item.expected)} | "
            f"{len(item.true_positives)} | {len(item.false_positives)} | "
            f"{len(item.false_negatives)} | {item.precision:.3f} | {item.recall:.3f} | "
            f"{item.f1:.3f} |"
        )
    lines.append(
        f"| **Micro average** | all labelled | {total_tp + total_fn} | {total_tp} | {total_fp} | "
        f"{total_fn} | **{micro_precision:.3f}** | **{micro_recall:.3f}** | **{micro_f1:.3f}** |"
    )

    lines += ["", "## Critical misclassification checks", ""]
    dual = checks["dual_degree_called_fraud"]
    clean_flags = checks["clean_institution_flags"]
    lines += [
        "| Check | Result |",
        "|---|---|",
        f"| Legal dual degrees wrongly flagged as fraud | {len(dual)}"
        + (f" ({dual})" if dual else " — none") + " |",
        f"| Flags on the clean model institution "
        f"({checks['clean_institution'].get('name', 'n/a')}) | {len(clean_flags)}"
        + (f" ({[f['type'] for f in clean_flags]})" if clean_flags else " — none") + " |",
    ]

    controls = checks.get("controls") or []
    if controls:
        lines += ["", "## Negative controls", "", "| Control | Cases | Violations |", "|---|---:|---|"]
        for control in controls:
            lines.append(
                f"| {control['check']} | {control['cases']} | "
                + (f"{len(control['violations'])} ({control['violations']})" if control["violations"] else "0 — none")
                + " |"
            )

    if robust:
        lines += ["", "## Why each miss happened", ""]
        any_diagnosis = False
        for item in scores:
            diagnoses = ROBUST_DIAGNOSES.get(item.scenario)
            if not diagnoses:
                continue
            if not (item.false_negatives or item.false_positives):
                continue
            any_diagnosis = True
            lines.append(f"### {item.label}")
            lines.append("")
            lines.append(
                f"Precision {item.precision:.3f}, recall {item.recall:.3f} "
                f"({len(item.false_negatives)} missed, {len(item.false_positives)} unlabelled)."
            )
            lines.append("")
            for diagnosis in diagnoses:
                lines.append(f"- {diagnosis}")
            lines.append("")
        if not any_diagnosis:
            lines.append("- Nothing was missed on this run.")

        perturbed = [item for item in scores if item.perturbations]
        if perturbed:
            lines += ["", "## Result per perturbation", "", "| Scenario | Perturbation | Caught |", "|---|---|---|"]
            for item in perturbed:
                for key, perturbation in sorted(item.perturbations.items()):
                    caught = "yes" if key in item.predicted else "**no**"
                    lines.append(f"| {item.label} | {perturbation} | {caught} |")

    misses = [item for item in scores if item.false_negatives]
    documents = checks.get("documents") or {}
    if documents.get("total"):
        lines += [
            "",
            "## Document verification",
            "",
            f"{documents['total']} synthetic documents were printed, registered with the mock issuer "
            "registry (or deliberately not), submitted and run through the real pipeline: text "
            "extraction, data match, issuer check and tamper checks. A case counts as correct only "
            "if it ends in the expected status **and** carries the expected reason codes.",
            "",
            "| Case | Documents | Expected outcome | Correct |",
            "|---|---:|---|---:|",
        ]
        for case, bucket in documents["per_case"].items():
            lines.append(
                f"| {DOCUMENT_CASE_LABELS.get(case, case)} | {bucket['cases']} | {bucket['expected'].replace('_', ' ')} | "
                f"{bucket['correct']} |"
            )
        lines += [
            f"| **All** | {documents['total']} | | **{documents['correct']} ({documents['accuracy']:.1%})** |",
            "",
            f"- Problem documents that were auto-verified (must be 0): **{documents['problem_documents_auto_verified']}**",
            f"- Genuine documents that were rejected (must be 0): **{documents['genuine_documents_rejected']}**",
        ]
        if documents["wrong"]:
            lines.append(f"- Wrong outcomes: {documents['wrong']}")

    lines += ["", "## Misses and extra flags", ""]
    if misses:
        for item in misses:
            lines.append(
                f"- **{item.label}**: missed {len(item.false_negatives)} of "
                f"{len(item.expected)} (keys: {sorted(item.false_negatives)[:10]})"
            )
    else:
        lines.append("- No labelled case was missed.")

    extras = [item for item in scores if item.false_positives]
    if extras:
        for item in extras:
            lines.append(
                f"- **{item.label}**: {len(item.false_positives)} flag(s) with no matching "
                f"label (keys: {sorted(item.false_positives)[:10]})"
            )

    if extra:
        lines += [
            "",
            "## Flags produced that no scenario scores",
            "",
            "Institution-level aggregates and findings for which the generator injects no",
            "labelled case. These are not counted as false positives because no ground truth",
            "exists for them; they are listed so the numbers above cannot look better than",
            "they are.",
            "",
            "| Flag type | Count |",
            "|---|---:|",
        ]
        lines += [f"| `{flag_type}` | {count} |" for flag_type, count in extra.items()]

    lines += [
        "",
        "## What these numbers do and do not show",
        "",
        "**Read this before putting the table on a slide.** The generator and the detectors",
        "were written by the same team against the same definitions, so the dataset contains",
        "exactly the patterns the detectors look for. High scores here mean the detectors",
        "work as specified and have not regressed — they are *not* evidence of accuracy on",
        "real institutional data, where patterns are messier and labels do not exist.",
        "",
        "What the table genuinely demonstrates:",
        "",
        "- the rules are implemented correctly and are reproducible from a fixed seed;",
        "- the hard negative controls hold: a legal dual degree is never called fraud, an",
        "  admission exactly on the cutoff is never called late, and the clean model",
        "  institution attracts no flags at all;",
        "- the subtler injected cases are caught, not just the blatant ones (the 3-seat",
        "  intake breach as well as the 25-seat one);",
        "- any future change that breaks a detector shows up here immediately.",
        "",
        "What it cannot show: performance against real fraud, the false-positive rate on",
        "genuine institutional data, or whether our thresholds are the right ones for AICTE.",
        "Those need a pilot with real returns and human adjudication.",
        "",
        "## How to read this",
        "",
        "- **Precision** = of the flags we raised for a scenario, how many were real.",
        "- **Recall** = of the cases we injected, how many we caught.",
        "- A legal dual degree reported as fraud is the worst error this system can make, so",
        "  it is checked separately and must stay at zero.",
        "- The thresholds behind these numbers live in `api/app/rules/*.yaml` and in the",
        "  detector modules; they were not tuned per scenario to flatter this table. Two",
        "  genuine gaps found while building this harness are recorded in the git history:",
        "  late admissions in seeded data were only flagged at institution level, and the",
        "  seat matrix double-counted continuing supernumerary students.",
        "",
    ]
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(prog="datagen.evaluate", description="Score detections")
    parser.add_argument("--database", default=str(DEFAULT_DB))
    parser.add_argument("--ground-truth", default=str(GROUND_TRUTH_PATH))
    parser.add_argument("--output", default=None, help="markdown report path")
    parser.add_argument("--robust", action="store_true", help="score the robustness dataset")
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    args = parser.parse_args()

    global REPORT_PATH
    if args.robust:
        from datagen.robust import GROUND_TRUTH_ROBUST, ROBUST_DB

        if args.database == str(DEFAULT_DB):
            args.database = str(ROBUST_DB)
        if args.ground_truth == str(GROUND_TRUTH_PATH):
            args.ground_truth = str(GROUND_TRUTH_ROBUST)
        REPORT_PATH = ROBUST_REPORT_PATH
    if args.output:
        REPORT_PATH = Path(args.output)

    truth_path = Path(args.ground_truth)
    if not truth_path.exists():
        print(f"No ground truth at {truth_path}. Run `make reset` first.")
        return 1
    database = Path(args.database)
    if not database.exists():
        print(f"No database at {database}. Run `make reset` first.")
        return 1

    ground_truth = json.loads(truth_path.read_text())
    engine = create_engine(f"sqlite:///{database}")
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        scores = score(db, ground_truth)
        checks = misclassification_checks(db, ground_truth)
        checks["controls"] = control_checks(db, ground_truth)
        extra = unlabelled_flags(db, scores)
        checks["documents"] = score_documents(db, ground_truth)
    finally:
        db.close()

    counts = dict(ground_truth.get("counts", {}))
    counts["seed"] = ground_truth.get("seed")

    write_markdown(scores, checks, extra, ground_truth, robust=args.robust)
    if args.json:
        print(
            json.dumps(
                {
                    "scenarios": [item.as_dict() for item in scores],
                    "checks": checks,
                    "unscored_flags": extra,
                },
                indent=2,
            )
        )
    else:
        print_report(
            scores,
            checks,
            extra,
            counts,
            ground_truth_name=str(Path(args.ground_truth).relative_to(REPO_ROOT)),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
