"""Unit tests for the per-user tier capability model (api/entitlements.py)."""

import os
import unittest
from unittest.mock import patch

from api.entitlements import (
    BILLING_FLAT,
    BILLING_NONE,
    BILLING_PER_SEAT,
    PLAN_CUSTOM,
    PLAN_FREE,
    PLAN_PRO,
    ROLE_ADMIN,
    ROLE_USER,
    TIER_CAPABILITIES,
    TierCapabilities,
    apply_account_entitlements,
    capabilities_for_user,
    default_plan_tier,
    entitlements_for_user,
    max_clients_for_user,
    phase13_enabled_for_user,
    uses_managed_keys_for_user,
)


class _U:
    """Minimal attribute-bag stand-in for a SQLAlchemy User (no DB needed)."""

    def __init__(self, plan_tier=None, account_role=None, email=""):
        self.plan_tier = plan_tier
        self.account_role = account_role
        self.email = email


def _without_default_plan_env():
    """patch.dict context that removes AISO_DEFAULT_PLAN_TIER (restored on exit)."""
    ctx = patch.dict(os.environ, {}, clear=False)
    return ctx


class CapabilityTableTests(unittest.TestCase):
    def test_table_values_match_spec(self):
        self.assertEqual(TIER_CAPABILITIES[PLAN_FREE], TierCapabilities(1, False, False, BILLING_NONE))
        self.assertEqual(TIER_CAPABILITIES[PLAN_PRO], TierCapabilities(1, True, True, BILLING_FLAT))
        self.assertEqual(TIER_CAPABILITIES[PLAN_CUSTOM], TierCapabilities(None, True, True, BILLING_PER_SEAT))

    def test_max_clients_per_tier(self):
        self.assertEqual(max_clients_for_user(_U(PLAN_FREE)), 1)
        self.assertEqual(max_clients_for_user(_U(PLAN_PRO)), 1)
        self.assertIsNone(max_clients_for_user(_U(PLAN_CUSTOM)))

    def test_admin_role_maps_to_custom_capabilities(self):
        caps = capabilities_for_user(_U(plan_tier=PLAN_FREE, account_role=ROLE_ADMIN))
        self.assertIsNone(caps.max_clients)
        self.assertTrue(caps.allow_phase13)
        self.assertEqual(caps.billing_model, BILLING_PER_SEAT)

    def test_unknown_or_empty_tier_falls_back_to_free(self):
        self.assertEqual(max_clients_for_user(_U("garbage")), 1)
        self.assertEqual(max_clients_for_user(_U(None)), 1)


class EntitlementsForUserTests(unittest.TestCase):
    def test_populates_max_clients(self):
        self.assertEqual(entitlements_for_user(_U(PLAN_FREE)).max_clients, 1)
        self.assertEqual(entitlements_for_user(_U(PLAN_PRO)).max_clients, 1)
        self.assertIsNone(entitlements_for_user(_U(PLAN_CUSTOM)).max_clients)

    def test_managed_keys_and_billing(self):
        free = entitlements_for_user(_U(PLAN_FREE))
        self.assertFalse(free.uses_managed_keys)
        self.assertFalse(free.allow_phase13)
        self.assertEqual(free.billing_model, BILLING_NONE)

        custom = entitlements_for_user(_U(PLAN_CUSTOM))
        self.assertTrue(custom.uses_managed_keys)
        self.assertEqual(custom.billing_model, BILLING_PER_SEAT)

    def test_admin_role_surfaced_as_custom(self):
        ent = entitlements_for_user(_U(plan_tier=PLAN_FREE, account_role=ROLE_ADMIN))
        self.assertEqual(ent.account_role, ROLE_ADMIN)
        self.assertEqual(ent.plan_tier, PLAN_CUSTOM)

    def test_display_gates_permissive_for_all_tiers(self):
        for plan in (PLAN_FREE, PLAN_PRO, PLAN_CUSTOM):
            ent = entitlements_for_user(_U(plan))
            self.assertTrue(ent.can_download_artifacts)
            self.assertTrue(ent.can_view_full_citations)
            self.assertTrue(ent.can_view_source_graph)


class Phase13RoutingTests(unittest.TestCase):
    def test_master_switch_off_blocks_all_tiers(self):
        with patch.dict(os.environ, {"AISO_SCAN_ENGINE": "legacy"}):
            self.assertFalse(phase13_enabled_for_user(_U(PLAN_PRO)))
            self.assertFalse(phase13_enabled_for_user(_U(PLAN_CUSTOM)))
            self.assertFalse(phase13_enabled_for_user(_U(PLAN_FREE)))

    def test_master_switch_on_respects_tier(self):
        with patch.dict(os.environ, {"AISO_SCAN_ENGINE": "phase13"}):
            self.assertFalse(phase13_enabled_for_user(_U(PLAN_FREE)))
            self.assertTrue(phase13_enabled_for_user(_U(PLAN_PRO)))
            self.assertTrue(phase13_enabled_for_user(_U(PLAN_CUSTOM)))

    def test_uses_managed_keys_matches_allow_phase13(self):
        self.assertFalse(uses_managed_keys_for_user(_U(PLAN_FREE)))
        self.assertTrue(uses_managed_keys_for_user(_U(PLAN_PRO)))
        self.assertTrue(uses_managed_keys_for_user(_U(PLAN_CUSTOM)))


class StickyEntitlementsTests(unittest.TestCase):
    def test_default_plan_tier_is_free(self):
        with _without_default_plan_env():
            os.environ.pop("AISO_DEFAULT_PLAN_TIER", None)
            self.assertEqual(default_plan_tier(), PLAN_FREE)

    def test_new_user_defaults_to_free(self):
        with _without_default_plan_env():
            os.environ.pop("AISO_DEFAULT_PLAN_TIER", None)
            u = _U(plan_tier=None, email="new@example.com")
            apply_account_entitlements(u)
            self.assertEqual(u.plan_tier, PLAN_FREE)
            self.assertEqual(u.account_role, ROLE_USER)

    def test_existing_free_user_stays_free(self):
        # Regression for the prior bug that bumped free -> pro on every login.
        u = _U(plan_tier=PLAN_FREE, account_role=ROLE_USER, email="f@example.com")
        apply_account_entitlements(u)
        self.assertEqual(u.plan_tier, PLAN_FREE)
        self.assertEqual(u.account_role, ROLE_USER)

    def test_existing_pro_user_preserved(self):
        u = _U(plan_tier=PLAN_PRO, account_role=ROLE_USER, email="p@example.com")
        apply_account_entitlements(u)
        self.assertEqual(u.plan_tier, PLAN_PRO)

    def test_existing_custom_user_preserved(self):
        u = _U(plan_tier=PLAN_CUSTOM, account_role=ROLE_USER, email="c@example.com")
        apply_account_entitlements(u)
        self.assertEqual(u.plan_tier, PLAN_CUSTOM)

    def test_admin_email_forces_custom_admin_over_stored_plan(self):
        with patch.dict(os.environ, {"AISO_ADMIN_EMAILS": "admin@aisoglobal.com"}):
            u = _U(plan_tier=PLAN_PRO, account_role=ROLE_USER, email="ADMIN@aisoglobal.com")
            apply_account_entitlements(u)
            self.assertEqual(u.plan_tier, PLAN_CUSTOM)
            self.assertEqual(u.account_role, ROLE_ADMIN)

    def test_row_already_admin_preserved_even_without_admin_email(self):
        u = _U(plan_tier=PLAN_FREE, account_role=ROLE_ADMIN, email="someone@example.com")
        apply_account_entitlements(u)
        self.assertEqual(u.account_role, ROLE_ADMIN)
        self.assertEqual(u.plan_tier, PLAN_CUSTOM)


if __name__ == "__main__":
    unittest.main()
