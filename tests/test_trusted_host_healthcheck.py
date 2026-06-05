"""TrustedHostMiddleware must accept Railway's healthcheck host."""

from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from api.main import app


class TrustedHostHealthcheckTests(unittest.TestCase):
    def test_railway_healthcheck_host_is_allowed(self):
        # Railway's container healthcheck arrives with Host: healthcheck.railway.app.
        client = TestClient(app, base_url="http://healthcheck.railway.app")
        resp = client.get("/api/v1/health")
        self.assertEqual(resp.status_code, 200)

    def test_unknown_host_is_still_rejected(self):
        # The middleware still enforces — an arbitrary host is rejected.
        client = TestClient(app, base_url="http://evil.example.com")
        resp = client.get("/api/v1/health")
        self.assertEqual(resp.status_code, 400)


if __name__ == "__main__":
    unittest.main()
