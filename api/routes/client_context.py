"""Client context discovery and confirmation endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from api.auth import get_current_user_id
from api.database import Client, ClientContext, get_db
from api.scan_capabilities import profile_competitor_names
from api.scan_objectives import ScanObjectiveValidationError, normalize_scan_objective

router = APIRouter(tags=["client-context"])

VALID_STATUSES = {"not_started", "discovering", "draft", "confirmed", "needs_review", "failed"}


class ClientContextResponse(BaseModel):
    client_id: str
    status: str
    profile_json: Optional[dict[str, Any]] = None
    evidence_json: Optional[dict[str, Any]] = None
    warnings_json: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ClientContextUpdate(BaseModel):
    status: str = "confirmed"
    profile_json: dict[str, Any]
    warnings_json: list[str] = Field(default_factory=list)

    @field_validator("profile_json")
    @classmethod
    def validate_profile_json(cls, value: dict[str, Any]) -> dict[str, Any]:
        profile = dict(value or {})
        try:
            profile["scan_objective"] = normalize_scan_objective(
                profile.get("scan_objective"),
                reject_unknown=True,
            )
        except ScanObjectiveValidationError as exc:
            raise ValueError(str(exc)) from exc
        return profile


def _ensure_client(db: Session, client_id: str, user_id: str) -> Client:
    client = db.query(Client).filter(Client.id == client_id, Client.user_id == user_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


def _safe_json_loads(value: Any, fallback: Any) -> Any:
    if not value:
        return fallback
    if isinstance(value, (list, dict)):  # JSON-typed column already parsed
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return fallback


def _serialize_context(context: ClientContext) -> ClientContextResponse:
    return ClientContextResponse(
        client_id=context.client_id,
        status=context.status,
        profile_json=_safe_json_loads(context.profile_json, None),
        evidence_json=_safe_json_loads(context.evidence_json, None),
        warnings_json=_safe_json_loads(context.warnings_json, []),
        created_at=context.created_at,
        updated_at=context.updated_at,
    )


def _get_or_create_context(db: Session, client_id: str) -> ClientContext:
    context = db.query(ClientContext).filter(ClientContext.client_id == client_id).first()
    if context:
        return context
    now = datetime.now(timezone.utc)
    context = ClientContext(
        client_id=client_id,
        status="not_started",
        created_at=now,
        updated_at=now,
    )
    db.add(context)
    db.flush()
    return context


@router.get("/clients/{client_id}/context", response_model=ClientContextResponse)
async def get_client_context(
    client_id: str,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    """Return the current draft/confirmed context for a client."""
    _ensure_client(db, client_id, user_id)
    context = db.query(ClientContext).filter(ClientContext.client_id == client_id).first()
    if not context:
        now = datetime.now(timezone.utc)
        return ClientContextResponse(
            client_id=client_id,
            status="not_started",
            profile_json=None,
            evidence_json=None,
            warnings_json=[],
            created_at=now,
            updated_at=now,
        )
    return _serialize_context(context)


@router.put("/clients/{client_id}/context", response_model=ClientContextResponse)
async def update_client_context(
    client_id: str,
    payload: ClientContextUpdate,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    """Save edited context from onboarding/settings."""
    client = _ensure_client(db, client_id, user_id)
    clean_status = str(payload.status or "").strip().lower()
    if clean_status not in VALID_STATUSES:
        raise HTTPException(status_code=422, detail="Unsupported context status")
    if clean_status == "discovering":
        raise HTTPException(status_code=422, detail="Context cannot be manually saved as discovering")

    context = _get_or_create_context(db, client_id)
    context.status = clean_status
    context.profile_json = payload.profile_json
    context.warnings_json = payload.warnings_json
    context.updated_at = datetime.now(timezone.utc)
    client.competitor_names = profile_competitor_names(payload.profile_json)
    client.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(context)
    return _serialize_context(context)
