"""Robustness dataset generator (`make eval-robust`).

Builds a SECOND dataset with a different seed, contacts written in varied formats, and
the perturbed scenarios in ``datagen/robust_scenarios.py`` — cases the detectors were
not built or tuned against. It writes to its own database so the demo data is untouched.

Usage:
    python -m datagen.robust --seed 2026
"""
from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ROBUST_DB = REPO_ROOT / "apaar_robust.db"
ROBUST_REGISTRY_DB = REPO_ROOT / "registry_robust.db"
GROUND_TRUTH_ROBUST = REPO_ROOT / "datagen" / "ground_truth_robust.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="datagen.robust", description="Generate the robustness dataset"
    )
    parser.add_argument("--seed", type=int, default=2026, help="different from the demo seed")
    parser.add_argument("--institutions", type=int, default=24)
    parser.add_argument("--students", type=int, default=7000)
    return parser


def main() -> int:
    args = build_parser().parse_args()

    # Point the whole stack at the robustness database before importing anything that
    # builds an engine from settings.
    os.environ["DATABASE_URL"] = f"sqlite:///{ROBUST_DB}"
    os.environ["REGISTRY_DATABASE_URL"] = f"sqlite:///{ROBUST_REGISTRY_DB}"

    for path in (ROBUST_DB, ROBUST_REGISTRY_DB):
        path.unlink(missing_ok=True)
        for suffix in ("-wal", "-shm"):
            Path(str(path) + suffix).unlink(missing_ok=True)

    from app.core.db import SessionLocal, init_db
    from app.services.detectors import run_all_detectors
    from datagen import robust_scenarios
    from datagen.generator import generate

    started = time.perf_counter()
    init_db()
    db = SessionLocal()
    try:
        ground_truth = generate(
            db,
            seed=args.seed,
            institutions=args.institutions,
            students=args.students,
            ground_truth_path=GROUND_TRUTH_ROBUST,
            scenario_module=robust_scenarios,
            vary_contact_formats=True,
        )
    finally:
        db.close()

    db = SessionLocal()
    try:
        summary = run_all_detectors(db)
    finally:
        db.close()

    counts = ground_truth["counts"]
    print(
        "Robustness dataset: {institutions} institutions, {students} students, "
        "{enrolments} enrolments, {labelled_cases} labelled cases "
        "(seed {seed}, contact formats varied) in {elapsed:.1f}s".format(
            elapsed=time.perf_counter() - started, seed=args.seed, **counts
        )
    )
    print("Detectors: " + ", ".join(f"{key}={value}" for key, value in summary.items()))
    print(f"Database: {ROBUST_DB.name}   Ground truth: {GROUND_TRUTH_ROBUST.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
