"""Append-only, hash-chained audit log (CLAUDE.md section 5 rule 8).

Each row stores ``prev_hash`` and ``hash = sha256(prev_hash + canonical_json(row))``.
Editing or deleting any row breaks every hash after it, which ``verify_chain()`` reports.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.core import AuditLog

GENESIS_HASH = "0" * 64
# Fields that participate in the chain, in a fixed order.
CHAINED_FIELDS = ("id", "actor", "role", "action", "target", "payload", "created_at")


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def canonical_json(row: dict[str, Any]) -> str:
    """Deterministic JSON: fixed key order, no insignificant whitespace."""
    ordered = {key: row.get(key) for key in CHAINED_FIELDS}
    return json.dumps(ordered, sort_keys=True, separators=(",", ":"), default=_json_default)


def compute_hash(prev_hash: str, row: dict[str, Any]) -> str:
    return hashlib.sha256((prev_hash + canonical_json(row)).encode("utf-8")).hexdigest()


def _row_dict(entry: AuditLog) -> dict[str, Any]:
    return {
        "id": entry.id,
        "actor": entry.actor,
        "role": entry.role,
        "action": entry.action,
        "target": entry.target,
        "payload": entry.payload,
        "created_at": entry.created_at,
    }


def last_hash(db: Session) -> str:
    entry = db.execute(select(AuditLog).order_by(AuditLog.id.desc()).limit(1)).scalar_one_or_none()
    return entry.hash if entry else GENESIS_HASH


def log_audit(
    db: Session,
    *,
    actor: str,
    role: str,
    action: str,
    target: str | None = None,
    payload: dict[str, Any] | None = None,
) -> AuditLog:
    """Append one audit row and link it into the chain. Caller commits."""
    entry = AuditLog(
        actor=actor,
        role=role,
        action=action,
        target=target,
        payload=payload or {},
        prev_hash=last_hash(db),
        hash="",
    )
    db.add(entry)
    db.flush()  # assigns the id, which is part of the hashed content
    entry.hash = compute_hash(entry.prev_hash, _row_dict(entry))
    db.flush()
    return entry


@dataclass
class ChainCheck:
    ok: bool
    rows_checked: int
    first_broken_row: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "rows_checked": self.rows_checked,
            "first_broken_row": self.first_broken_row,
        }


def verify_chain(db: Session, *, model: type[AuditLog] = AuditLog) -> ChainCheck:
    """Recompute every hash. Returns ok, or the first row that does not match."""
    rows = list(db.execute(select(model).order_by(model.id.asc())).scalars())
    prev = GENESIS_HASH
    for index, entry in enumerate(rows, start=1):
        expected = compute_hash(prev, _row_dict(entry))
        if entry.prev_hash != prev or entry.hash != expected:
            return ChainCheck(
                ok=False,
                rows_checked=index,
                first_broken_row={
                    "id": entry.id,
                    "action": entry.action,
                    "expected_hash": expected,
                    "stored_hash": entry.hash,
                    "expected_prev_hash": prev,
                    "stored_prev_hash": entry.prev_hash,
                    "created_at": entry.created_at.isoformat() if entry.created_at else None,
                },
            )
        prev = entry.hash
    return ChainCheck(ok=True, rows_checked=len(rows))
