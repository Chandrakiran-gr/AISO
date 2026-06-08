"""Account role and plan entitlement helpers for AISO.

This module is the single source of truth for what each subscription tier may do.
Tier lives on ``User.plan_tier`` (``free`` | ``pro`` | ``custom``) — never on a
client/business. The capability table below drives scan-engine routing, provider
key handling, business-count limits, and billing model:

- ``free``   — 1 business, legacy scan engine, BYOK (own keys), no server spend.
- ``pro``    — 1 business, Phase 13 engine, managed (server) keys, flat billing.
- ``custom`` — unlimited businesses, Phase 13, managed keys, per-seat billing.

Admin emails (``AISO_ADMIN_EMAILS``) are always treated as ``custom``/``admin``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from api.feature_flags import is_phase13_engine

PLAN_FREE = "free"
PLAN_PRO = "pro"
PLAN_CUSTOM = "custom"

ROLE_USER = "user"
ROLE_ADMIN = "admin"

BILLING_NONE = "none"
BILLING_FLAT = "flat"
BILLING_PER_SEAT = "per_seat"

VALID_PLAN_TIERS = {PLAN_FREE, PLAN_PRO, PLAN_CUSTOM}
VALID_ACCOUNT_ROLES = {ROLE_USER, ROLE_ADMIN}
VALID_BILLING_MODELS = {BILLING_NONE, BILLING_FLAT, BILLING_PER_SEAT}


def _clean_email(value: str) -> str:
    return str(value or "").strip().lower()


def configured_admin_emails() -> set[str]:
    """Return founder/admin emails configured for this deployment."""
    return {
        _clean_email(email)
        for email in os.getenv("AISO_ADMIN_EMAILS", "admin@aisoglobal.com").split(",")
        if _clean_email(email)
    }


def default_plan_tier() -> str:
    """Default plan for a brand-new account.

    New accounts start on **free** (own keys, legacy engine) and upgrade to
    ``pro``/``custom`` for managed keys + the Phase 13 engine. Overridable via
    ``AISO_DEFAULT_PLAN_TIER`` but never silently invalid.
    """
    configured = os.getenv("AISO_DEFAULT_PLAN_TIER", PLAN_FREE).strip().lower()
    return configured if configured in VALID_PLAN_TIERS else PLAN_FREE


def plan_for_email(email: str) -> str:
    """Admin emails map to ``custom``; everyone else to the default (``free``)."""
    return PLAN_CUSTOM if _clean_email(email) in configured_admin_emails() else default_plan_tier()


def role_for_email(email: str) -> str:
    return ROLE_ADMIN if _clean_email(email) in configured_admin_emails() else ROLE_USER


def apply_account_entitlements(user: object) -> None:
    """Apply role/plan defaults to a SQLAlchemy ``User`` on signup/login/OAuth.

    Sticky and idempotent:
    - Admin emails (or a row already marked admin) → ``custom`` / ``admin``.
    - A brand-new user with no valid stored plan → the default (``free``).
    - An existing user's valid ``plan_tier`` is preserved verbatim — we never
      bump ``free`` → ``pro`` on login (the prior behaviour that prevented a
      free account from ever sticking).
    """
    email = _clean_email(getattr(user, "email", ""))
    current_role = str(getattr(user, "account_role", "") or "").lower()

    if current_role == ROLE_ADMIN or role_for_email(email) == ROLE_ADMIN:
        setattr(user, "account_role", ROLE_ADMIN)
        setattr(user, "plan_tier", PLAN_CUSTOM)
        return

    setattr(user, "account_role", ROLE_USER)
    current_plan = str(getattr(user, "plan_tier", "") or "").lower()
    if current_plan not in VALID_PLAN_TIERS:
        # None/empty/garbage == brand-new or never set → safe default.
        setattr(user, "plan_tier", default_plan_tier())
    # else: keep the stored tier exactly as-is (free stays free).


@dataclass(frozen=True)
class TierCapabilities:
    """What a single tier is allowed to do. The one place tier rules live."""

    max_clients: int | None      # max businesses; None == unlimited (custom)
    allow_phase13: bool          # Phase 13 (managed-key) scan engine
    uses_managed_keys: bool      # server provider keys vs the user's BYOK keys
    billing_model: str           # none | flat | per_seat


TIER_CAPABILITIES: dict[str, TierCapabilities] = {
    PLAN_FREE: TierCapabilities(
        max_clients=1, allow_phase13=False, uses_managed_keys=False, billing_model=BILLING_NONE
    ),
    PLAN_PRO: TierCapabilities(
        max_clients=1, allow_phase13=True, uses_managed_keys=True, billing_model=BILLING_FLAT
    ),
    PLAN_CUSTOM: TierCapabilities(
        max_clients=None, allow_phase13=True, uses_managed_keys=True, billing_model=BILLING_PER_SEAT
    ),
}


def _normalized_tier(user: object) -> str:
    """Resolve the effective tier for a user. Admin role always maps to custom;
    an unknown/empty stored plan falls back to the safe default (free)."""
    role = str(getattr(user, "account_role", "") or ROLE_USER).lower()
    if role == ROLE_ADMIN:
        return PLAN_CUSTOM
    plan = str(getattr(user, "plan_tier", "") or "").lower()
    return plan if plan in VALID_PLAN_TIERS else PLAN_FREE


def capabilities_for_user(user: object) -> TierCapabilities:
    return TIER_CAPABILITIES[_normalized_tier(user)]


def phase13_enabled_for_user(user: object) -> bool:
    """Whether a NEW scan for this user runs on Phase 13 (managed keys).

    Gated by the global ``AISO_SCAN_ENGINE`` master switch AND the user's tier.
    Free tier never runs on Phase 13 — it stays on the legacy/BYOK path so a
    free user never consumes the company's API budget.
    """
    if not is_phase13_engine():
        return False
    return capabilities_for_user(user).allow_phase13


def max_clients_for_user(user: object) -> int | None:
    """Max businesses the user may create; ``None`` means unlimited (custom)."""
    return capabilities_for_user(user).max_clients


def uses_managed_keys_for_user(user: object) -> bool:
    """True when the user's scans/onboarding run on server keys (pro/custom)."""
    return capabilities_for_user(user).uses_managed_keys


@dataclass(frozen=True)
class UserEntitlements:
    plan_tier: str
    account_role: str
    can_download_artifacts: bool
    can_view_full_citations: bool
    can_view_source_graph: bool
    max_clients: int | None
    allow_phase13: bool
    uses_managed_keys: bool
    billing_model: str


def entitlements_for_user(user: object) -> UserEntitlements:
    """Centralized entitlement map, populated from ``TIER_CAPABILITIES``.

    Display gates (downloads / full citations / source graph) remain permissive
    for all tiers during private beta; tighten them in one place (here) later.
    """
    tier = _normalized_tier(user)
    caps = TIER_CAPABILITIES[tier]
    role = ROLE_ADMIN if str(getattr(user, "account_role", "") or "").lower() == ROLE_ADMIN else ROLE_USER
    return UserEntitlements(
        plan_tier=tier,
        account_role=role,
        can_download_artifacts=True,
        can_view_full_citations=True,
        can_view_source_graph=True,
        max_clients=caps.max_clients,
        allow_phase13=caps.allow_phase13,
        uses_managed_keys=caps.uses_managed_keys,
        billing_model=caps.billing_model,
    )
