"""Read the Phase 13 dashboard projection tables into the legacy JSON shapes.

These functions let the existing dashboard endpoints serve Phase 13 data without
changing the frontend: they assemble the same response shapes the legacy
gap-report / actions / sources / citations endpoints return, but sourced from the
materialized ``scan_metric`` / ``scan_citation`` / ``scan_competitor`` /
``scan_action`` tables. Gated by ``AISO_SCAN_ENGINE`` at the route layer.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from api.adapters.scan_runs import JOURNEY_LABELS
from api.database import (
    ScanAction,
    ScanCitationP13,
    ScanCompetitor,
    ScanMetric,
    ScanRun,
)


def latest_phase13_scan_id(db: Session, *, client_id: str) -> str | None:
    """Most recent published (succeeded/partial) Phase 13 scan for the client."""
    row = (
        db.query(ScanRun.id)
        .filter(ScanRun.client_id == client_id, ScanRun.status.in_(("succeeded", "partial")))
        .order_by(ScanRun.finished_at.is_(None).asc(), ScanRun.finished_at.desc(), ScanRun.enqueued_at.desc())
        .first()
    )
    return row[0] if row else None


def _resolve_scan_id(db: Session, *, client_id: str, scan_id: str | None) -> str | None:
    return scan_id or latest_phase13_scan_id(db, client_id=client_id)


def phase13_actions(db: Session, *, client_id: str, scan_id: str | None, status: str | None) -> list[dict[str, Any]]:
    """Actions in the legacy ActionResponse shape, sourced from scan_action."""
    target = _resolve_scan_id(db, client_id=client_id, scan_id=scan_id)
    if not target:
        return []
    query = db.query(ScanAction).filter(ScanAction.scan_id == target, ScanAction.client_id == client_id)
    if status:
        query = query.filter(ScanAction.status == status)
    rows = query.order_by(
        ScanAction.sort_order.is_(None).asc(),
        ScanAction.sort_order.asc(),
        ScanAction.score.is_(None).asc(),
        ScanAction.score.desc(),
        ScanAction.created_at.desc(),
    ).all()
    return [_action_payload(a) for a in rows]


def _action_payload(a: ScanAction) -> dict[str, Any]:
    impact = float(a.impact_estimate) if a.impact_estimate is not None else None
    return {
        "id": a.id,
        "client_id": a.client_id,
        "scan_id": a.scan_id,
        "action_key": a.action_key,
        "title": a.title,
        "description": a.description,
        "priority": a.priority,
        "category": a.category,
        "impact_pts": (f"+{impact:.0f} pts" if impact is not None else None),
        "effort": a.effort,
        "score": float(a.score) if a.score is not None else None,
        "sort_order": a.sort_order,
        "evidence_json": json.dumps(a.evidence_json) if a.evidence_json is not None else None,
        "remediation_type": a.action_role,
        "target_questions_json": json.dumps(a.target_questions_json) if a.target_questions_json is not None else None,
        "target_providers_json": (json.dumps([a.target_provider]) if a.target_provider else None),
        "evidence_summary": a.description,
        "impact_estimate": impact,
        "status": a.status,
        "created_at": a.created_at,
        "completed_at": None,
    }


def _journey_label(stage: str | None) -> str:
    return JOURNEY_LABELS.get(stage or "", stage or "")
