"""Readers for the two versioned rule files in app/rules/.

No cap, percentage or date is hardcoded in Python — it all comes from
``intake_rules.yaml`` and ``reporting_calendar.yaml`` (CLAUDE.md section 6).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.core.config import RULES_DIR

INTAKE_RULES_PATH = RULES_DIR / "intake_rules.yaml"
CALENDAR_PATH = RULES_DIR / "reporting_calendar.yaml"


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):  # pragma: no cover - malformed file
        raise ValueError(f"{path.name} must contain a YAML mapping")
    return data


@lru_cache
def intake_rules() -> dict[str, Any]:
    return _load_yaml(INTAKE_RULES_PATH)


@lru_cache
def reporting_calendar() -> dict[str, Any]:
    return _load_yaml(CALENDAR_PATH)


def rule_set_version() -> str:
    return str(intake_rules().get("rule_set", "unknown"))


def calendar_set_version() -> str:
    return str(reporting_calendar().get("calendar_set", "unknown"))


def counts_within_intake() -> tuple[str, ...]:
    return tuple(intake_rules().get("counts_within_intake", ["regular"]))


def supernumerary_rules() -> dict[str, dict[str, Any]]:
    return dict(intake_rules().get("supernumerary", {}))


def _round_cap(value: float) -> int:
    mode = str(intake_rules().get("cap_rounding", "floor")).lower()
    if mode == "ceil":
        return int(math.ceil(value))
    if mode == "round":
        return int(round(value))
    return int(math.floor(value))


def supernumerary_caps(intake: int) -> dict[str, int]:
    """Absolute seat caps per supernumerary category for a programme's approved intake."""
    return {
        name: _round_cap(intake * float(rule.get("cap_percent", 0.0)) / 100.0)
        for name, rule in supernumerary_rules().items()
    }


def lateral_adds_vacant_year1() -> bool:
    rule = supernumerary_rules().get("lateral", {})
    return bool(rule.get("add_vacant_year1_seats", False))


def excess_severity(excess: int, intake: int) -> str:
    """Severity of an EXCESS_INTAKE flag, from the configured thresholds."""
    if excess <= 0:
        return "low"
    bands = intake_rules().get("excess_severity", {})
    share = (excess / intake * 100.0) if intake else 100.0
    if share <= float(bands.get("low_max_percent", 1.0)):
        return "low"
    if share <= float(bands.get("medium_max_percent", 5.0)):
        return "medium"
    if share <= float(bands.get("high_max_percent", 15.0)):
        return "high"
    return "critical"


@dataclass(frozen=True)
class YearCalendar:
    academic_year: str
    admission_window_start: date
    admission_window_end: date
    lateral_window_end: date
    reporting_deadline: datetime

    def is_late(self, admitted_on: date | None, admission_type: str = "regular") -> bool:
        if admitted_on is None:
            return False
        cutoff = self.lateral_window_end if admission_type == "lateral" else self.admission_window_end
        return admitted_on > cutoff


def _as_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _as_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, 23, 59, 59)
    return datetime.fromisoformat(str(value))


def year_calendar(academic_year: str) -> YearCalendar:
    years = reporting_calendar().get("years", {})
    entry = years.get(academic_year)
    if entry is None:
        raise KeyError(
            f"No calendar entry for {academic_year} — add it to app/rules/reporting_calendar.yaml"
        )
    return YearCalendar(
        academic_year=academic_year,
        admission_window_start=_as_date(entry["admission_window_start"]),
        admission_window_end=_as_date(entry["admission_window_end"]),
        lateral_window_end=_as_date(entry.get("lateral_window_end", entry["admission_window_end"])),
        reporting_deadline=_as_datetime(entry["reporting_deadline"]),
    )


def known_academic_years() -> tuple[str, ...]:
    return tuple(sorted(reporting_calendar().get("years", {}).keys()))


def calendar_thresholds() -> dict[str, float]:
    raw = reporting_calendar().get("thresholds", {})
    return {key: float(value) for key, value in raw.items()}
