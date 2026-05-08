"""Account role and plan entitlement helpers for AISO."""

from __future__ import annotations

import os
from dataclasses import dataclass

PLAN_FREE = "free"
PLAN_PRO = "pro"
PLAN_CUSTOM = "custom"

ROLE_USER = "user"
ROLE_ADMIN = "admin"

VALID_PLAN_TIERS = {PLAN_FREE, PLAN_PRO, PLAN_CUSTOM}
VALID_ACCOUNT_ROLES = {ROLE_USER, ROLE_ADMIN}


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
    """Default new-account plan.

    Private beta defaults to Pro so every account can exercise the full product
    before tiered cutdowns are enabled.
    """
    configured = os.getenv("AISO_DEFAULT_PLAN_TIER", PLAN_PRO).strip().lower()
    return configured if configured in VALID_PLAN_TIERS else PLAN_PRO


def plan_for_email(email: str) -> str:
    return PLAN_CUSTOM if _clean_email(email) in configured_admin_emails() else default_plan_tier()


def role_for_email(email: str) -> str:
    return ROLE_ADMIN if _clean_email(email) in configured_admin_emails() else ROLE_USER


def apply_account_entitlements(user: object) -> None:
    """Apply private-beta plan/role defaults to a SQLAlchemy User object."""
    email = _clean_email(getattr(user, "email", ""))
    desired_role = role_for_email(email)
    desired_plan = plan_for_email(email)
    current_role = str(getattr(user, "account_role", "") or "").lower()
    current_plan = str(getattr(user, "plan_tier", "") or "").lower()

    if current_role == ROLE_ADMIN or desired_role == ROLE_ADMIN:
        setattr(user, "account_role", ROLE_ADMIN)
        setattr(user, "plan_tier", PLAN_CUSTOM)
        return

    setattr(user, "account_role", desired_role)
    if current_plan not in VALID_PLAN_TIERS or current_plan == PLAN_FREE:
        setattr(user, "plan_tier", desired_plan)


@dataclass(frozen=True)
class UserEntitlements:
    plan_tier: str
    account_role: str
    can_download_artifacts: bool
    can_view_full_citations: bool
    can_view_source_graph: bool
    max_clients: int | None


def entitlements_for_user(user: object) -> UserEntitlements:
    """Centralized entitlement map.

    For private beta all persisted users are effectively Pro-or-better. Later,
    Free tier limits should be changed here instead of scattered through routes.
    """
    plan = str(getattr(user, "plan_tier", "") or default_plan_tier()).lower()
    role = str(getattr(user, "account_role", "") or ROLE_USER).lower()
    if role == ROLE_ADMIN or plan == PLAN_CUSTOM:
        return UserEntitlements(
            plan_tier=PLAN_CUSTOM,
            account_role=ROLE_ADMIN if role == ROLE_ADMIN else ROLE_USER,
            can_download_artifacts=True,
            can_view_full_citations=True,
            can_view_source_graph=True,
            max_clients=None,
        )
    return UserEntitlements(
        plan_tier=PLAN_PRO,
        account_role=ROLE_USER,
        can_download_artifacts=True,
        can_view_full_citations=True,
        can_view_source_graph=True,
        max_clients=None,
    )
