"""Per-user business (client) creation limits.

The hard guarantee is a Postgres ``BEFORE INSERT`` trigger (migration 0030) that
raises SQLSTATE ``P0LIM`` when a user exceeds their plan's business count. This
module provides:

- ``enforce_client_creation_limit`` — an app-level pre-check (clean UX + testable
  on SQLite, which has no trigger), and
- ``is_client_limit_violation`` / ``business_limit_403`` — translation of the
  trigger's error into an HTTP 403 (the race-proof backstop on Postgres).

Limits come from the user's tier (``api.entitlements``): free/pro = 1 business,
custom = unlimited.
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from api.database import Client, User
from api.entitlements import max_clients_for_user

CLIENT_LIMIT_SQLSTATE = "P0LIM"
CLIENT_LIMIT_MESSAGE = "client_business_limit_exceeded"
_HTTP_DETAIL = "Business limit reached for your plan. Upgrade to add more."


def business_limit_403() -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_HTTP_DETAIL)


def enforce_client_creation_limit(db: Session, user_id: str) -> None:
    """Raise 403 if creating another business would exceed the user's plan limit.

    Custom tier (``max_clients`` is ``None``) is unlimited. This is a pre-check
    only; the Postgres trigger is the race-proof backstop. An unknown user
    resolves to the free limit (1) via the entitlements default.
    """
    user = db.query(User).filter(User.id == user_id).first()
    limit = max_clients_for_user(user)
    if limit is None:
        return  # unlimited (custom)
    existing = db.query(Client).filter(Client.user_id == user_id).count()
    if existing >= limit:
        raise business_limit_403()


def is_client_limit_violation(exc: BaseException) -> bool:
    """True if a DB error is the client-limit trigger firing (SQLSTATE P0LIM)."""
    for obj in (exc, getattr(exc, "orig", None)):
        if obj is None:
            continue
        code = getattr(obj, "pgcode", None) or getattr(obj, "sqlstate", None)
        if code == CLIENT_LIMIT_SQLSTATE:
            return True
        if CLIENT_LIMIT_MESSAGE in str(obj):
            return True
    return False
