"""Business (client) identity helpers — one profile per business.

A business is identified by its owner plus its normalized URL. These helpers let
the create/onboarding paths **reuse an existing business** instead of minting a
new Client on every scan, and back the ``UNIQUE(user_id, url)`` guarantee.
"""

from __future__ import annotations

from urllib.parse import urlparse

from sqlalchemy.orm import Session

from api.crawler.url_utils import normalize_url
from api.database import Client
from api.entitlements import max_clients_for_user


def business_url_key(url: str) -> str:
    """Stable, scheme-/www-insensitive identity key for a business URL.

    Reuses the crawler's ``normalize_url`` (lowercased host, trailing-slash and
    tracking-param normalization) and additionally drops the scheme and a
    leading ``www.`` so ``http://www.x.com/`` and ``https://x.com`` resolve to
    the same business.
    """
    norm = normalize_url(url)
    if not norm:
        return ""
    parsed = urlparse(norm)
    host = (parsed.hostname or "").removeprefix("www.")
    if not host:
        return norm  # unparseable — fall back to the normalized string
    path = parsed.path if parsed.path and parsed.path != "/" else ""
    return f"{host}{path}"


def canonical_business_url(url: str) -> str:
    """The URL form stored on ``clients.url`` (normalized; preserves host/scheme
    so it remains a valid crawl seed)."""
    return normalize_url(url) or url


def _most_recent(clients: list[Client]) -> Client:
    return max(clients, key=lambda c: (c.updated_at or c.created_at))


def resolve_user_business(
    db: Session,
    user: object,
    *,
    client_id: str | None,
    url: str | None,
) -> Client | None:
    """Find the business this request should operate on, or ``None`` to create.

    Resolution order:
      1. An explicit, user-owned ``client_id`` (the normal re-scan path).
      2. A business of this user whose URL matches (``business_url_key``).
      3. For single-business tiers (free/pro), the user's existing business — so
         editing the URL on a re-scan still updates in place instead of creating
         a second profile.
    Returns ``None`` only when the user has no business to reuse (genuine create).
    """
    user_id = getattr(user, "id", None)
    if not user_id:
        return None

    if client_id:
        owned = (
            db.query(Client)
            .filter(Client.id == client_id, Client.user_id == user_id)
            .first()
        )
        if owned is not None:
            return owned

    user_clients = db.query(Client).filter(Client.user_id == user_id).all()
    if not user_clients:
        return None

    key = business_url_key(url or "")
    if key:
        matches = [c for c in user_clients if business_url_key(c.url or "") == key]
        if matches:
            return _most_recent(matches)

    # No URL match: single-business tiers (free/pro) reuse their one business.
    if max_clients_for_user(user) == 1:
        return _most_recent(user_clients)
    return None
