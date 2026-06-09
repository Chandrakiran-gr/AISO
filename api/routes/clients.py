"""
Clients router — CRUD for client profiles.
Each user currently has one client/business profile.
"""

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
from uuid import UUID, uuid4
import json

from sqlalchemy.exc import SQLAlchemyError

from api.database import get_db, Client, User
from api.auth import get_current_user_id
from api.client_identity import canonical_business_url, resolve_user_business
from api.client_limits import (
    business_limit_403,
    enforce_client_creation_limit,
    is_client_limit_violation,
)

router = APIRouter(tags=["clients"])


# ── Schemas (Pydantic validation) ────────────────────────────────────────────

class ClientCreate(BaseModel):
    # Existing client UUID. New clients get a server-generated UUID when omitted.
    id:           Optional[str] = None
    display_name: Optional[str] = None   # alias for name
    name:         Optional[str] = None   # legacy field
    url:          Optional[str] = None
    industry:     Optional[str] = None
    location:     Optional[str] = None
    competitors:  Optional[List[str]] = None

    @property
    def resolved_name(self) -> str:
        return (self.display_name or self.name or "").strip()

    @property
    def resolved_url(self) -> str:
        return (self.url or "").strip()


class ClientResponse(BaseModel):
    id:          str
    name:        str
    url:         str
    industry:    Optional[str]
    location:    Optional[str]
    competitors: Optional[List[str]]

    class Config:
        from_attributes = True


def _clean_competitors(value: Optional[List[str]]) -> Optional[List[str]]:
    if not value:
        return None
    cleaned = [" ".join(str(item).strip().split()) for item in value]
    cleaned = [item for item in cleaned if item]
    return cleaned or None


def _canonical_uuid4(value: Optional[str], *, field_name: str) -> Optional[str]:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    try:
        parsed = UUID(cleaned, version=4)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"{field_name} must be a UUIDv4") from exc
    if str(parsed) != cleaned.lower():
        raise HTTPException(status_code=422, detail=f"{field_name} must be a canonical UUIDv4")
    return str(parsed)


def _serialize_client(client: Client) -> ClientResponse:
    competitors = client.competitor_names if isinstance(client.competitor_names, list) else None
    return ClientResponse(
        id=client.id,
        name=client.name,
        url=client.url,
        industry=client.industry,
        location=client.location,
        competitors=competitors,
    )


def _apply_client_payload(
    client: Client,
    payload: ClientCreate,
    resolved_name: str,
    *,
    preserve_omitted: bool,
) -> None:
    fields_set = payload.model_fields_set
    client.name = resolved_name
    if not preserve_omitted or "url" in fields_set:
        client.url = canonical_business_url(payload.resolved_url) if payload.resolved_url else client.url
    if not preserve_omitted or "industry" in fields_set:
        client.industry = payload.industry
    if not preserve_omitted or "location" in fields_set:
        client.location = payload.location
    if not preserve_omitted or "competitors" in fields_set:
        client.competitor_names = _clean_competitors(payload.competitors)


@router.get("/clients", response_model=List[ClientResponse])
async def list_clients(
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id)
):
    """List all clients for the current user (most-recently-updated first)."""
    clients = (
        db.query(Client)
        .filter(Client.user_id == user_id)
        .order_by(Client.updated_at.desc())
        .all()
    )
    return [_serialize_client(client) for client in clients]


@router.post("/clients", response_model=ClientResponse, status_code=status.HTTP_201_CREATED)
async def create_client(
    payload: ClientCreate,
    response: Response,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id)
):
    """Create or update the current user's single business profile."""
    resolved_name = payload.resolved_name
    if not resolved_name:
        raise HTTPException(status_code=422, detail="name or display_name is required")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    # The incoming id only identifies an existing business to reuse (any format,
    # incl. legacy non-UUID ids); a genuinely new business gets a server-minted
    # UUID below — callers never set the id.
    existing = resolve_user_business(db, user, client_id=payload.id, url=payload.resolved_url)
    if existing:
        _apply_client_payload(existing, payload, resolved_name, preserve_omitted=True)
        db.commit()
        db.refresh(existing)
        response.status_code = status.HTTP_200_OK
        return _serialize_client(existing)

    # New business: enforce the per-user plan limit (free/pro = 1, custom = unlimited).
    enforce_client_creation_limit(db, user_id)
    new_id = str(uuid4())
    client = Client(
        id=new_id,
        user_id=user_id,
        name=resolved_name,
        url=canonical_business_url(payload.resolved_url) if payload.resolved_url else f"https://example.com/{new_id}",
        industry=payload.industry,
        location=payload.location,
        competitor_names=_clean_competitors(payload.competitors),
    )
    db.add(client)
    try:
        db.commit()
    except SQLAlchemyError as exc:  # Postgres trigger backstop (race-safe)
        db.rollback()
        if is_client_limit_violation(exc):
            raise business_limit_403() from exc
        raise
    db.refresh(client)
    return _serialize_client(client)


@router.get("/clients/{client_id}", response_model=ClientResponse)
async def get_client(
    client_id: str,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id)
):
    """Get a specific client profile."""
    client = db.query(Client).filter(
        Client.id == client_id,
        Client.user_id == user_id,
    ).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    return _serialize_client(client)


@router.delete("/clients/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_client(
    client_id: str,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id)
):
    """Delete a client profile."""
    client = db.query(Client).filter(
        Client.id == client_id,
        Client.user_id == user_id,
    ).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    db.delete(client)
    db.commit()
