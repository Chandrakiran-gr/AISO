"""Legacy-pipeline key resolution by tier: free scans are BYOK-only and never
read or leak the company's server provider keys."""

import unittest
from unittest.mock import patch

from api.routes.pipeline import (
    PROVIDER_ENV_VARS,
    build_subprocess_env,
    resolve_active_providers,
)


class ResolveActiveProvidersTests(unittest.TestCase):
    def test_free_scan_ignores_server_keys(self):
        # Server keys present, but a free (BYOK-only) scan with no BYOK keys must
        # skip every provider — it never reads the company's server keys.
        env = {var: "sk-server" for var in PROVIDER_ENV_VARS.values()}
        with patch.dict("os.environ", env, clear=False):
            active, skipped = resolve_active_providers(
                ["openai", "claude"], byok_keys={}, use_managed_keys=False
            )
        self.assertEqual(active, [])
        self.assertEqual(set(skipped), {"openai", "claude"})

    def test_free_scan_uses_byok_only(self):
        env = {var: "sk-server" for var in PROVIDER_ENV_VARS.values()}
        with patch.dict("os.environ", env, clear=False):
            active, skipped = resolve_active_providers(
                ["openai", "claude"], byok_keys={"openai": "sk-user"}, use_managed_keys=False
            )
        self.assertEqual(active, ["openai"])
        self.assertEqual(skipped, ["claude"])

    def test_managed_scan_uses_server_keys(self):
        env = {var: "sk-server" for var in PROVIDER_ENV_VARS.values()}
        with patch.dict("os.environ", env, clear=False):
            active, skipped = resolve_active_providers(
                ["openai", "claude"], byok_keys={}, use_managed_keys=True
            )
        self.assertEqual(set(active), {"openai", "claude"})
        self.assertEqual(skipped, [])

    def test_managed_scan_missing_server_key_skips(self):
        with patch.dict("os.environ", {}, clear=True):
            active, skipped = resolve_active_providers(
                ["openai"], byok_keys={}, use_managed_keys=True
            )
        self.assertEqual(active, [])
        self.assertEqual(skipped, ["openai"])


class BuildSubprocessEnvTests(unittest.TestCase):
    def test_free_scan_scrubs_server_keys(self):
        base = {var: "sk-server" for var in PROVIDER_ENV_VARS.values()}
        base["UNRELATED"] = "keep-me"
        sub = build_subprocess_env(base, byok_keys={}, use_managed_keys=False)
        for var in PROVIDER_ENV_VARS.values():
            self.assertNotIn(var, sub)  # server keys must not leak to the subprocess
        self.assertEqual(sub["UNRELATED"], "keep-me")

    def test_free_scan_layers_byok_after_scrub(self):
        base = {var: "sk-server" for var in PROVIDER_ENV_VARS.values()}
        sub = build_subprocess_env(base, byok_keys={"openai": "sk-user"}, use_managed_keys=False)
        self.assertEqual(sub["OPENAI_API_KEY"], "sk-user")
        self.assertNotIn("ANTHROPIC_API_KEY", sub)  # provider without BYOK stays scrubbed

    def test_managed_scan_keeps_server_keys(self):
        base = {var: "sk-server" for var in PROVIDER_ENV_VARS.values()}
        sub = build_subprocess_env(base, byok_keys={}, use_managed_keys=True)
        self.assertEqual(sub["OPENAI_API_KEY"], "sk-server")

    def test_does_not_mutate_base_env(self):
        base = {"OPENAI_API_KEY": "sk-server"}
        build_subprocess_env(base, byok_keys={}, use_managed_keys=False)
        self.assertEqual(base["OPENAI_API_KEY"], "sk-server")  # original untouched


if __name__ == "__main__":
    unittest.main()
