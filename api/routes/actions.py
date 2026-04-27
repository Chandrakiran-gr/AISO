"""Action plan routes for AISO."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from api.auth import get_current_user_id
from api.database import Action, Client, get_db

router = APIRouter(tags=["actions"])

VALID_STATUSES = {"open", "done", "dismissed"}


class ActionResponse(BaseModel):
    id: str
    client_id: str
    scan_id: Optional[str]
    title: str
    description: Optional[str]
    priority: Optional[str]
    category: Optional[str]
    impact_pts: Optional[str]
    effort: Optional[str]
    status: Optional[str]
    created_at: datetime
    completed_at: Optional[datetime]

    class Config:
        from_attributes = True


class ActionUpdate(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def status_must_be_supported(cls, value: str) -> str:
        clean = str(value or "").strip().lower()
        if clean not in VALID_STATUSES:
            raise ValueError("Unsupported action status")
        return clean


def _ensure_client(db: Session, client_id: str, user_id: str) -> Client:
    client = db.query(Client).filter(
        Client.id == client_id,
        Client.user_id == user_id,
    ).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


@router.get("/clients/{client_id}/actions", response_model=List[ActionResponse])
async def list_actions(
    client_id: str,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    """List recommendation actions for a client."""
    _ensure_client(db, client_id, user_id)
    return db.query(Action).filter(
        Action.client_id == client_id,
    ).order_by(Action.created_at.desc()).all()


@router.patch("/clients/{client_id}/actions/{action_id}", response_model=ActionResponse)
async def update_action(
    client_id: str,
    action_id: str,
    payload: ActionUpdate,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    """Update the lifecycle state for one action item."""
    _ensure_client(db, client_id, user_id)
    action = db.query(Action).filter(
        Action.id == action_id,
        Action.client_id == client_id,
    ).first()
    if not action:
        raise HTTPException(status_code=404, detail="Action not found")

    action.status = payload.status
    action.completed_at = (
        datetime.now(timezone.utc) if payload.status == "done" else None
    )
    db.commit()
    db.refresh(action)
    return action
