"""Synthetic data generator CLI.

Usage:
    python -m datagen --seed 42 --institutions 40 --students 15000
"""
from __future__ import annotations

import argparse
import time

from app.core.db import SessionLocal, init_db
from datagen.generator import DEFAULT_YEARS, generate


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="datagen", description="Generate synthetic APAAR data")
    parser.add_argument("--seed", type=int, default=42, help="deterministic seed")
    parser.add_argument("--institutions", type=int, default=40)
    parser.add_argument("--students", type=int, default=15000)
    parser.add_argument(
        "--years", nargs="*", default=list(DEFAULT_YEARS), help="academic years to generate"
    )
    parser.add_argument(
        "--no-samples", action="store_true", help="skip writing the messy sample files"
    )
    parser.add_argument(
        "--no-detectors", action="store_true", help="skip running the detectors after seeding"
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    started = time.perf_counter()

    init_db()
    db = SessionLocal()
    try:
        ground_truth = generate(
            db,
            seed=args.seed,
            institutions=args.institutions,
            students=args.students,
            years=tuple(args.years),
        )
    finally:
        db.close()

    if not args.no_samples:
        from datagen.samples import write_samples

        written = write_samples(seed=args.seed)
        print(f"Sample upload files: {', '.join(path.name for path in written)}")

    if not args.no_detectors:
        try:
            from app.services.detectors import run_all_detectors

            db = SessionLocal()
            try:
                summary = run_all_detectors(db)
                print(
                    "Detectors: "
                    + ", ".join(f"{key}={value}" for key, value in summary.items())
                )
            finally:
                db.close()
        except ImportError:
            print("Detectors not implemented yet (Steps 7-11) — skipping.")

    counts = ground_truth["counts"]
    elapsed = time.perf_counter() - started
    print(
        "Seeded {institutions} institutions, {programs} programs, {students} students, "
        "{enrolments} enrolments, {uploads} uploads, {labelled_cases} labelled cases "
        "in {elapsed:.1f}s".format(elapsed=elapsed, **counts)
    )
    print("Ground truth: datagen/ground_truth.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
