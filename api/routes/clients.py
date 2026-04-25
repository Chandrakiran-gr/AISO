"""
Clients router — CRUD for client profiles.
Each user can have multiple clients (businesses being tracked).
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, HttpUrl, field_validator
from typing import Optional, List
import uuid
import json

from api.database import get_db, Client

router = APIRouter(tags=["clients"])


# ── Schemas (Pydantic validation) ────────────────────────────────────────────

class ClientCreate(BaseModel):
    # Onboarding sends: id (slug) + display_name
    id:           Optional[str] = None   # optional slug; auto-generated if absent
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


# ── Routes ───────────────────────────────────────────────────────────────────

# TODO: Add real auth dependency once NextAuth + API token are wired together
# For now: placeholder user_id
PLACEHOLDER_USER_ID = "dev-user-001"


@router.get("/clients", response_model=List[ClientResponse])
async def list_clients(db: Session = Depends(get_db)):
    """List all clients for the current user."""
    clients = db.query(Client).filter(Client.user_id == PLACEHOLDER_USER_ID).all()
    for c in clients:
        if c.competitors:
            c.competitors = json.loads(c.competitors)
    return clients


@router.post("/clients", response_model=ClientResponse, status_code=status.HTTP_201_CREATED)
async def create_client(payload: ClientCreate, db: Session = Depends(get_db)):
    """Create a new client profile. Returns 409 if a client with the same id/slug already exists."""
    resolved_name = payload.resolved_name
    if not resolved_name:
        raise HTTPException(status_code=422, detail="name or display_name is required")

    client_id = (payload.id or str(uuid.uuid4())).strip()

    # 409 if slug already exists — onboarding reuses the client
    existing = db.query(Client).filter(Client.id == client_id).first()
    if existing:
        if existing.competitors:
            existing.competitors = json.loads(existing.competitors)
        raise HTTPException(status_code=409, detail="Client already exists", headers={"X-Client-Id": client_id})

    client = Client(
        id=client_id,
        user_id=PLACEHOLDER_USER_ID,
        name=resolved_name,
        url=payload.resolved_url or f"https://example.com/{client_id}",
        industry=payload.industry,
        location=payload.location,
        competitors=json.dumps(payload.competitors) if payload.competitors else None,
    )
    db.add(client)
    db.commit()
    db.refresh(client)
    if client.competitors:
        client.competitors = json.loads(client.competitors)  # type: ignore
    return client


@router.get("/clients/{client_id}", response_model=ClientResponse)
async def get_client(client_id: str, db: Session = Depends(get_db)):
    """Get a single client by ID."""
    client = db.query(Client).filter(
        Client.id == client_id,
        Client.user_id == PLACEHOLDER_USER_ID,
    ).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    if client.competitors:
        client.competitors = json.loads(client.competitors)
    return client


@router.delete("/clients/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_client(client_id: str, db: Session = Depends(get_db)):
    """Delete a client and all associated data."""
    client = db.query(Client).filter(
        Client.id == client_id,
        Client.user_id == PLACEHOLDER_USER_ID,
    ).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    db.delete(client)
    db.commit()
