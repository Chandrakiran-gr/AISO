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
    name:        str
    url:         str
    industry:    Optional[str] = None
    location:    Optional[str] = None
    competitors: Optional[List[str]] = None

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Name cannot be empty")
        if len(v) > 200:
            raise ValueError("Name too long (max 200 chars)")
        return v

    @field_validator("url")
    @classmethod
    def url_valid(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("URL must start with http:// or https://")
        if len(v) > 500:
            raise ValueError("URL too long")
        return v.strip()

    @field_validator("competitors")
    @classmethod
    def limit_competitors(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v and len(v) > 10:
            raise ValueError("Maximum 10 competitors allowed")
        return v


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
    """Create a new client profile."""
    client = Client(
        id=str(uuid.uuid4()),
        user_id=PLACEHOLDER_USER_ID,
        name=payload.name,
        url=payload.url,
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
