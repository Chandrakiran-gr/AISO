"""Shared SQLAlchemy helpers for scan-execution saga state."""

from __future__ import annotations

from typing import Any

from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from api.database import ScanStep


def scan_step(db: Session, *, scan_run_id: str, step_id: str, event: str) -> ScanStep | None:
    return (
        db.query(ScanStep)
        .filter(
            ScanStep.scan_run_id == scan_run_id,
            ScanStep.step_id == step_id,
            ScanStep.event == event,
            ScanStep.attempt == 1,
        )
        .first()
    )


def record_step_once(
    db: Session,
    *,
    scan_run_id: str,
    step_id: str,
    event: str,
    payload: dict[str, Any],
) -> bool:
    if scan_step(db, scan_run_id=scan_run_id, step_id=step_id, event=event):
        return False

    values = {
        "scan_run_id": scan_run_id,
        "step_id": step_id,
        "event": event,
        "attempt": 1,
        "payload": payload,
    }
    dialect_name = db.bind.dialect.name if db.bind is not None else ""
    if dialect_name == "postgresql":
        statement = postgres_insert(ScanStep).values(**values).on_conflict_do_nothing(
            index_elements=["scan_run_id", "step_id", "event", "attempt"]
        )
        result = db.execute(statement)
        return bool(result.rowcount)
    if dialect_name == "sqlite":
        statement = sqlite_insert(ScanStep).values(**values).on_conflict_do_nothing(
            index_elements=["scan_run_id", "step_id", "event", "attempt"]
        )
        result = db.execute(statement)
        return bool(result.rowcount)

    db.add(ScanStep(**values))
    db.flush()
    return True


def safe_error(exc: Exception) -> str:
    message = str(exc).strip() or exc.__class__.__name__
    return message[:500]
