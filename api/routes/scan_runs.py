"""Spec-compliant downstream scan-run API."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.adapters.scan_runs import (
    ScanRunKickoffError,
    create_or_replay_scan_run,
    progress_for_scan_run,
)
from api.auth import get_current_user_id
from api.database import get_db
from api.domain.scan_runs import DEFAULT_SCAN_PROVIDERS


router = APIRouter(tags=["scan-runs"])


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
):
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
        )
    except ScanRunKickoffError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

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
