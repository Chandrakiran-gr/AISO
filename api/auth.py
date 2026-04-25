"""
AISO API Auth — JWT verification dependency for FastAPI.

Flow:
  1. Next.js /api/token issues a HS256 JWT signed with AUTH_SECRET
  2. Frontend attaches it as: Authorization: Bearer <token>
  3. FastAPI routes use Depends(get_current_user) to verify & decode

The secret must match AUTH_SECRET in web/.env.local
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from pydantic import BaseModel
from typing import Optional
import os

_SECRET    = os.getenv("AUTH_SECRET", "dev-secret-change-me")
_ALGORITHM = "HS256"
_ISSUER    = "aiso-web"
_AUDIENCE  = "aiso-api"

bearer_scheme = HTTPBearer(auto_error=False)


class TokenUser(BaseModel):
    """The decoded user identity from the JWT."""
    id:    str
    email: str
    name:  Optional[str] = None


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> TokenUser:
    """
    FastAPI dependency — decodes and validates the Bearer JWT.
    Raises 401 if token is missing, expired, or tampered.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    try:
        payload = jwt.decode(
            token,
            _SECRET,
            algorithms=[_ALGORITHM],
            issuer=_ISSUER,
            audience=_AUDIENCE,
        )
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        )

    sub   = payload.get("sub")
    email = payload.get("email", "")

    if not sub:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token missing sub")

    return TokenUser(id=sub, email=email, name=payload.get("name"))


def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> Optional[TokenUser]:
    """
    Like get_current_user but returns None instead of 401 if no token.
    Useful for public endpoints that optionally use auth context.
    """
    if credentials is None:
        return None
    try:
        return get_current_user(credentials)
    except HTTPException:
        return None
