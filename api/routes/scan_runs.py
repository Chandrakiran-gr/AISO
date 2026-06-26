"""Spec-compliant downstream scan-run API."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.adapters.scan_execution import (
    ScanExecutionError,
    default_scan_executor,
    ensure_scan_run_enqueued,
)
from api.adapters.scan_runs import (
    ScanRunKickoffError,
    complete_scan_run_idempotency_response,
    create_or_replay_scan_run,
    dashboard_projection_for_scan_run,
    progress_for_scan_run,
)
from api.auth import get_current_user_id
from api.database import get_db
from api.domain.ports import ScanExecutor
from api.domain.scan_runs import DEFAULT_SCAN_PROVIDERS
from api.feature_flags import is_phase13_engine


router = APIRouter(tags=["scan-runs"])


def get_scan_executor(request: Request) -> ScanExecutor:
    executor = getattr(request.app.state, "scan_executor", None)
    if executor is None:
        executor = default_scan_executor()
        request.app.state.scan_executor = executor
    return executor


class ScanRunCreateRequest(BaseModel):
    source_scan_id: str = Field(..., min_length=1)
    providers: list[str] = Field(default_factory=lambda: list(DEFAULT_SCAN_PROVIDERS))
    cost_budget_usd: Decimal | None = Field(default=None, ge=0)
    latency_class: str = Field(default="standard")


@router.post("/clients/{client_id}/scan-runs")
async def create_scan_run(
    client_id: str,
    payload: ScanRunCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
    executor: ScanExecutor = Depends(get_scan_executor),
):
    # Phase 13 (Gen-2) is parked behind AISO_SCAN_ENGINE. While the engine is the
    # legacy default, this direct kickoff route refuses so no path can run Gen-2.
    if not is_phase13_engine():
        raise HTTPException(status_code=404, detail="Phase 13 scan engine is disabled")
    if not idempotency_key:
        raise HTTPException(status_code=400, detail="Idempotency-Key header is required")
    try:
        result = create_or_replay_scan_run(
            db,
            client_id=client_id,
            user_id=user_id,
            source_scan_id=payload.source_scan_id,
            idempotency_key=idempotency_key,
            providers=payload.providers,
            cost_budget_usd=payload.cost_budget_usd,
            latency_class=payload.latency_class,
            complete_idempotency_response=False,
        )
    except ScanRunKickoffError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    db.commit()
    try:
        await ensure_scan_run_enqueued(
            db,
            scan_run_id=result.body["scan_run_id"],
            actor_id=user_id,
            executor=executor,
        )
    except ScanExecutionError as exc:
        try:
            db.commit()
        except Exception:
            db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    complete_scan_run_idempotency_response(
        db,
        idempotency_key=idempotency_key,
        status_code=result.status_code,
        body=result.body,
    )
    db.commit()
    return JSONResponse(status_code=result.status_code, content=result.body)


@router.get("/scan-runs/{scan_run_id}/progress")
async def get_scan_run_progress(
    scan_run_id: str,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> dict[str, Any]:
    progress = progress_for_scan_run(db, scan_run_id=scan_run_id, user_id=user_id)
    if progress is None:
        raise HTTPException(status_code=404, detail="Scan run not found")
    return progress


@router.get("/scan-runs/{scan_run_id}/dashboard-projection")
async def get_scan_run_dashboard_projection(
    scan_run_id: str,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> dict[str, Any]:
    projection = dashboard_projection_for_scan_run(db, scan_run_id=scan_run_id, user_id=user_id)
    if projection is None:
        raise HTTPException(status_code=404, detail="Scan run not found")
    return projection
