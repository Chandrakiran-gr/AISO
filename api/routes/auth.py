"""Auth persistence routes for AISO.

NextAuth handles browser sessions. These endpoints make that session durable in
the AISO database for OAuth and credentials accounts.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.auth import (
    hash_password,
    normalize_email,
    verify_internal_request,
    verify_password,
)
from api.database import Client, User, get_db

router = APIRouter(prefix="/auth", tags=["auth"])


class CredentialsSignup(BaseModel):
    name: Optional[str] = None
    email: str
    password: str

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        clean = " ".join(value.strip().split())
        return clean[:120] or None


class CredentialsVerify(BaseModel):
    email: str
    password: str


class OAuthUserUpsert(BaseModel):
    email: str
    name: Optional[str] = None
    provider: str = "google"

    @field_validator("provider")
    @classmethod
    def provider_must_be_supported(cls, value: str) -> str:
        clean = str(value or "").strip().lower()
        if clean not in {"google"}:
            raise ValueError("Unsupported OAuth provider")
        return clean

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        clean = " ".join(value.strip().split())
        return clean[:120] or None


class AuthUserResponse(BaseModel):
    id: str
    email: str
    name: Optional[str]
    provider: str
    created_at: datetime
    is_active: bool

    class Config:
        from_attributes = True


def _find_user_by_email(db: Session, email: str) -> User | None:
    return db.query(User).filter(User.email == email).first()


def _migrate_legacy_client_owner(
    db: Session,
    legacy_user_id: str,
    user_id: str,
) -> None:
    """Move old email-scoped client rows onto the durable DB user id."""
    if legacy_user_id == user_id:
        return
    db.query(Client).filter(Client.user_id == legacy_user_id).update(
        {Client.user_id: user_id},
        synchronize_session=False,
    )


@router.post(
    "/signup",
    response_model=AuthUserResponse,
    status_code=status.HTTP_201_CREATED,
)
def signup_with_credentials(
    payload: CredentialsSignup,
    db: Session = Depends(get_db),
) -> User:
    """Create an email/password account and persist it in the users table."""
    email = normalize_email(payload.email)
    existing = _find_user_by_email(db, email)
    if existing:
        raise HTTPException(status_code=409, detail="Email already exists")

    user = User(
        id=str(uuid.uuid4()),
        email=email,
        name=payload.name,
        password_hash=hash_password(payload.password),
        provider="credentials",
        is_active=True,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Email already exists")
    db.refresh(user)
    return user


@router.post("/credentials/verify", response_model=AuthUserResponse)
def verify_credentials(
    payload: CredentialsVerify,
    db: Session = Depends(get_db),
) -> User:
    """Verify credentials for NextAuth without exposing password hashes."""
    email = normalize_email(payload.email)
    user = _find_user_by_email(db, email)
    if (
        not user
        or not user.is_active
        or not user.password_hash
        or not verify_password(payload.password, user.password_hash)
    ):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    return user


@router.post("/oauth/upsert", response_model=AuthUserResponse)
def upsert_oauth_user(
    payload: OAuthUserUpsert,
    db: Session = Depends(get_db),
    _: None = Depends(verify_internal_request),
) -> User:
    """Create or update a durable DB user after successful OAuth login."""
    email = normalize_email(payload.email)
    user = _find_user_by_email(db, email)

    if user:
        if payload.name and payload.name != user.name:
            user.name = payload.name
        if not user.provider:
            user.provider = payload.provider
    else:
        user = User(
            id=str(uuid.uuid4()),
            email=email,
            name=payload.name,
            provider=payload.provider,
            password_hash=None,
            is_active=True,
        )
        db.add(user)
        db.flush()

    _migrate_legacy_client_owner(db, legacy_user_id=email, user_id=user.id)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = _find_user_by_email(db, email)
        if existing:
            return existing
        raise
    db.refresh(user)
    return user
