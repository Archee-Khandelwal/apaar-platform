"""Synthetic data generator entrypoint (filled in at Step 5).

Usage: python -m datagen --seed 42
"""
from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="datagen", description="Generate synthetic APAAR data")
    parser.add_argument("--seed", type=int, default=42, help="deterministic seed")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    print(f"datagen placeholder (seed={args.seed}) — implemented in Step 5 of docs/PLAN.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
