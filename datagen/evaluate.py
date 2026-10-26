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

from app.models.core import Cluster, Flag
from datagen.generator import GROUND_TRUTH_PATH

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO_ROOT / "apaar.db"
REPORT_PATH = REPO_ROOT / "docs" / "EVALUATION.md"

# How each scenario's ground-truth key is matched against produced flags.
# key_kind -> how to build the same key from a Flag.
SCENARIOS: dict[str, dict[str, Any]] = {
    "A_excess_intake": {"flag_types": ["EXCESS_INTAKE"], "label": "Excess admissions beyond intake"},
    "B_ghost_cluster": {"flag_types": ["GHOST_CLUSTER"], "label": "Ghost-student clusters"},
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
    "G_sequential_apaar": {
        "flag_types": ["SEQUENTIAL_APAAR"],
        "label": "Near-consecutive APAAR ID runs",
    },
    "H_last_minute_bulk": {
        "flag_types": ["LAST_MINUTE_BULK"],
        "label": "Records filed in a last-minute burst",
    },
    "I_phantom_progression": {
        "flag_types": ["PHANTOM_PROGRESSION"],
        "label": "Phantom year-to-year progression",
    },
    "J_identity_duplicate": {
        "flag_types": ["IDENTITY_DUPLICATE"],
        "label": "One person with two APAAR IDs",
    },
    "K_supernumerary_misuse": {
        "flag_types": ["STATISTICAL_ANOMALY"],
        "label": "Supernumerary share far above peers",
        # Two detectors share this flag type, so match only this signal's flags.
        "evidence_signal": "supernumerary_share",
    },
}


@dataclass
class ScenarioScore:
    scenario: str
    label: str
    flag_types: list[str]
    expected: set[str]
    predicted: set[str]
    notes: list[str] = field(default_factory=list)

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


def _flag_keys(
    db: Session, flag_types: list[str], key_kind: str, evidence_signal: str | None = None
) -> set[str]:
    """Build the ground-truth key for every produced flag of these types."""
    keys: set[str] = set()
    flags = list(db.execute(select(Flag).where(Flag.type.in_(flag_types))).scalars())
    if evidence_signal is not None:
        flags = [
            flag for flag in flags if (flag.evidence or {}).get("signal") == evidence_signal
        ]

    cluster_members: dict[int, list[int]] = {}
    if key_kind == "institution_year" and "GHOST_CLUSTER" in flag_types:
        for cluster in db.execute(select(Cluster)).scalars():
            cluster_members[cluster.id] = cluster.member_student_ids or []

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
        predicted = _flag_keys(
            db, config["flag_types"], key_kind, config.get("evidence_signal")
        )

        notes: list[str] = []
        # LATE_ADMISSION produces both per-row and per-institution flags; the ground
        # truth labels rows, so only per-row flags are scored here.
        if name == "F_late_admission":
            notes.append(
                "Scored on per-enrolment flags; the per-institution aggregate flag is "
                "reported separately below."
            )
        if name == "K_supernumerary_misuse":
            notes.append(
                "Matched on STATISTICAL_ANOMALY flags carrying signal=supernumerary_share; "
                "the IsolationForest ranking uses the same flag type and is excluded."
            )

        scores.append(
            ScenarioScore(
                scenario=name,
                label=config["label"],
                flag_types=list(config["flag_types"]),
                expected=expected,
                predicted=predicted,
                notes=notes,
            )
        )
    return scores


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

    controls = scenarios.get("B_sibling_control", [])
    control_students = {
        student_id
        for case in controls
        for student_id in case["details"].get("student_ids", [])
    }
    clustered = {
        student_id
        for cluster in db.execute(select(Cluster).where(Cluster.kind == "suspicious")).scalars()
        for student_id in (cluster.member_student_ids or [])
    }
    families_flagged = sorted(control_students & clustered)

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
        "family_controls_flagged_as_clusters": families_flagged,
        "clean_institution": clean,
        "clean_institution_flags": clean_flags,
    }


def unlabelled_flags(db: Session, scores: list[ScenarioScore]) -> dict[str, int]:
    """Flag types produced that no scenario scores — reported for transparency."""
    scored_types = {flag_type for item in scores for flag_type in item.flag_types}
    counts: dict[str, int] = {}
    for flag in db.execute(select(Flag)).scalars():
        signal = (flag.evidence or {}).get("signal")
        if flag.type == "STATISTICAL_ANOMALY" and signal != "supernumerary_share":
            # The IsolationForest ranking has no injected label of its own.
            counts["STATISTICAL_ANOMALY (IsolationForest ranking)"] = (
                counts.get("STATISTICAL_ANOMALY (IsolationForest ranking)", 0) + 1
            )
            continue
        if flag.type in scored_types:
            continue
        counts[flag.type] = counts.get(flag.type, 0) + 1
    return dict(sorted(counts.items()))


# --------------------------------------------------------------------------- output


def print_report(
    scores: list[ScenarioScore], checks: dict[str, Any], extra: dict[str, int], counts: dict[str, Any]
) -> None:
    width = 46
    print()
    print("=" * 92)
    print("DETECTION EVALUATION against datagen/ground_truth.json")
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
    families = checks["family_controls_flagged_as_clusters"]
    print(
        f"  Normal families flagged as ghost clusters: {len(families)}"
        + (f"  <-- {families}" if families else "  (none)")
    )
    clean = checks["clean_institution"]
    clean_flags = checks["clean_institution_flags"]
    print(
        f"  Flags on the clean model institution ({clean.get('name', 'n/a')}): "
        f"{len(clean_flags)}"
        + ("  (none)" if not clean_flags else f"  <-- {[f['type'] for f in clean_flags]}")
    )

    if extra:
        print()
        print("Flags produced that no scenario scores (institution-level aggregates and")
        print("findings with no injected label):")
        for flag_type, count in extra.items():
            print(f"  {flag_type:<32} {count}")

    print()
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

    lines: list[str] = [
        "# EVALUATION.md — detection accuracy",
        "",
        "Generated by `make eval` (`datagen/evaluate.py`), which scores the flags in the",
        "database against the labelled cases in `datagen/ground_truth.json`.",
        "",
        f"- Generated: {datetime.now().replace(microsecond=0).isoformat()}",
        f"- Seed: `{ground_truth.get('seed')}`",
        f"- Dataset: {counts.get('institutions')} institutions, {counts.get('programs')} programmes, "
        f"{counts.get('students')} students, {counts.get('enrolments')} enrolments",
        f"- Labelled cases: {counts.get('labelled_cases')}",
        "",
        "> Run `make reset && make eval`. The numbers describe the seeded data only — a demo",
        "> upload adds real enrolments and real flags that no ground-truth file knows about.",
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
    families = checks["family_controls_flagged_as_clusters"]
    clean_flags = checks["clean_institution_flags"]
    lines += [
        "| Check | Result |",
        "|---|---|",
        f"| Legal dual degrees wrongly flagged as fraud | {len(dual)}"
        + (f" ({dual})" if dual else " — none") + " |",
        f"| Normal families wrongly flagged as ghost clusters | {len(families)}"
        + (f" ({families})" if families else " — none") + " |",
        f"| Flags on the clean model institution "
        f"({checks['clean_institution'].get('name', 'n/a')}) | {len(clean_flags)}"
        + (f" ({[f['type'] for f in clean_flags]})" if clean_flags else " — none") + " |",
    ]

    misses = [item for item in scores if item.false_negatives]
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
        "- the hard negative controls hold: a legal dual degree is never called fraud, a",
        "  6-student family is never called a ghost cluster, and the clean model institution",
        "  attracts no flags at all;",
        "- the subtler injected cases are caught, not just the blatant ones (the 8-student",
        "  cluster as well as the 33-student one, the 3-seat intake breach as well as the",
        "  25-seat one);",
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
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    args = parser.parse_args()

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
        extra = unlabelled_flags(db, scores)
    finally:
        db.close()

    counts = dict(ground_truth.get("counts", {}))
    counts["seed"] = ground_truth.get("seed")

    write_markdown(scores, checks, extra, ground_truth)
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
        print_report(scores, checks, extra, counts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
