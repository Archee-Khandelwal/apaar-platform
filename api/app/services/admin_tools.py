"""Demo tooling (Step 19 of docs/PLAN.md).

The tamper test deserves a note: it copies the audit log into a temporary table,
alters one row there, and runs the same ``verify_chain`` over the copy. The real log is
append-only and is never modified, which is the property being demonstrated.
"""
from __future__ import annotations

import time
from typing import Any

from sqlalchemy import Column, Integer, MetaData, Table, func, select
from sqlalchemy.orm import Session

from app.core.audit import log_audit, verify_chain
from app.core.db import Base, engine
from app.models.core import AuditLog


def audit_status(db: Session) -> dict[str, Any]:
    result = verify_chain(db)
    total = db.scalar(select(func.count()).select_from(AuditLog)) or 0
    return {
        "ok": result.ok,
        "rows_checked": result.rows_checked,
        "rows_total": total,
        "first_broken_row": result.first_broken_row,
    }


def tamper_test(db: Session, *, actor: str) -> dict[str, Any]:
    """Prove the chain detects an edit, without touching the real log."""
    started = time.perf_counter()
    metadata = MetaData()
    source = AuditLog.__table__

    # A throwaway table with the same shape as audit_log.
    copy_table = Table(
        f"audit_log_tamper_{int(time.time())}",
        metadata,
        *[column.copy() for column in source.columns],
    )
    copy_table.create(bind=db.get_bind())

    class CopiedAuditLog(Base):  # type: ignore[misc]
        __table__ = copy_table
        __mapper_args__ = {"primary_key": [copy_table.c.id]}

    try:
        rows = list(db.execute(select(AuditLog).order_by(AuditLog.id)).scalars())
        if len(rows) < 3:
            return {
                "copy_rows": len(rows),
                "detected": False,
                "message": "Not enough audit rows to run the tamper test; reseed first.",
            }

        db.execute(
            copy_table.insert(),
            [
                {
                    "id": row.id,
                    "actor": row.actor,
                    "role": row.role,
                    "action": row.action,
                    "target": row.target,
                    "payload": row.payload,
                    "created_at": row.created_at,
                    "prev_hash": row.prev_hash,
                    "hash": row.hash,
                }
                for row in rows
            ],
        )
        db.flush()

        # Tamper with a row in the middle of the copy.
        target_id = rows[len(rows) // 2].id
        db.execute(
            copy_table.update()
            .where(copy_table.c.id == target_id)
            .values(payload={"tampered": True, "note": "edited in the copy only"})
        )
        db.flush()

        result = verify_chain(db, model=CopiedAuditLog)  # type: ignore[arg-type]
        log_audit(
            db,
            actor=actor,
            role="admin",
            action="audit_tamper_test",
            target="audit_log",
            payload={"tampered_row_id": target_id, "detected": not result.ok},
        )
        db.commit()

        return {
            "copy_rows": len(rows),
            "tampered_row_id": target_id,
            "detected": not result.ok,
            "first_broken_row_id": (result.first_broken_row or {}).get("id"),
            "first_broken_row": result.first_broken_row,
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "message": (
                f"Tamper detected at row {(result.first_broken_row or {}).get('id')} — the stored "
                "hash no longer matches sha256(prev_hash + canonical_json(row)). The real audit "
                "log was not modified; this ran against a copy."
            )
            if not result.ok
            else "The chain did not detect the edit, which would be a bug.",
        }
    finally:
        Base.registry._dispose_cls(CopiedAuditLog)  # type: ignore[attr-defined]
        copy_table.drop(bind=db.get_bind(), checkfirst=True)
        db.commit()
