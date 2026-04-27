"""
Clients router — CRUD for client profiles.
Each user can have multiple clients (businesses being tracked).
"""

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
import uuid
import json

from api.database import get_db, Client
from api.auth import get_current_user_id

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


def _competitors_json(value: Optional[List[str]]) -> Optional[str]:
    if not value:
        return None
    cleaned = [" ".join(str(item).strip().split()) for item in value]
    cleaned = [item for item in cleaned if item]
    return json.dumps(cleaned) if cleaned else None


def _serialize_client(client: Client) -> ClientResponse:
    competitors = None
    if client.competitors:
        try:
            parsed = json.loads(client.competitors)
            competitors = parsed if isinstance(parsed, list) else None
        except json.JSONDecodeError:
            competitors = None
    return ClientResponse(
        id=client.id,
        name=client.name,
        url=client.url,
        industry=client.industry,
        location=client.location,
        competitors=competitors,
    )


@router.get("/clients", response_model=List[ClientResponse])
async def list_clients(
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id)
):
    """List all clients for the current user."""
    clients = db.query(Client).filter(Client.user_id == user_id).all()
    return [_serialize_client(client) for client in clients]


@router.post("/clients", response_model=ClientResponse, status_code=status.HTTP_201_CREATED)
async def create_client(
    payload: ClientCreate,
    response: Response,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id)
):
    """Create or update a client profile for the current user."""
    resolved_name = payload.resolved_name
    if not resolved_name:
        raise HTTPException(status_code=422, detail="name or display_name is required")

    client_id = (payload.id or str(uuid.uuid4())).strip()

    existing = db.query(Client).filter(Client.id == client_id).first()
    if existing:
        if existing.user_id != user_id:
            raise HTTPException(status_code=409, detail="Client id already exists")

        fields_set = payload.model_fields_set
        existing.name = resolved_name
        if "url" in fields_set:
            existing.url = payload.resolved_url or existing.url
        if "industry" in fields_set:
            existing.industry = payload.industry
        if "location" in fields_set:
            existing.location = payload.location
        if "competitors" in fields_set:
            existing.competitors = _competitors_json(payload.competitors)
        db.commit()
        db.refresh(existing)
        response.status_code = status.HTTP_200_OK
        return _serialize_client(existing)

    client = Client(
        id=client_id,
        user_id=user_id,
        name=resolved_name,
        url=payload.resolved_url or f"https://example.com/{client_id}",
        industry=payload.industry,
        location=payload.location,
        competitors=_competitors_json(payload.competitors),
    )
    db.add(client)
    db.commit()
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
