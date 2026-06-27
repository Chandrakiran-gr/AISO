"""Email OTP verification + password reset flow (backend).

Deterministic code via patching generate_code; email send is patched to a no-op
(the real sender already no-ops without RESEND_API_KEY, but patching keeps logs clean
and lets us assert it was/wasn't called).
"""

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from tests._pgharness import make_test_engine, reset_schema
from api.database import EmailAuthCode, User, get_db
from api.main import app

CODE = "123456"
PW = "Aa1!aaaa"
NEW_PW = "Bb2@bbbb"


class AuthOtpTests(unittest.TestCase):
    def setUp(self):
        self.engine = make_test_engine()
        reset_schema(self.engine)
        self.Session = sessionmaker(bind=self.engine, autoflush=False)

        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app, base_url="http://localhost")

        gen = patch("api.auth_otp.generate_code", return_value=CODE)
        gen.start()
        self.addCleanup(gen.stop)
        self.send = patch("api.routes.auth.send_otp_email")
        self.mock_send = self.send.start()
        self.addCleanup(self.send.stop)

    def tearDown(self):
        app.dependency_overrides.pop(get_db, None)
        self.engine.dispose()

    # helpers
    def _signup(self, email="new@example.com"):
        return self.client.post(
            "/api/v1/auth/signup", json={"email": email, "password": PW, "name": "New"}
        )

    def _user(self, email):
        s = self.Session()
        try:
            return s.query(User).filter(User.email == email).first()
        finally:
            s.close()

    # tests
    def test_signup_creates_unverified_and_sends_code(self):
        r = self._signup()
        self.assertEqual(r.status_code, 201, r.text)
        self.assertFalse(self._user("new@example.com").email_verified)
        self.mock_send.assert_called_once()
        s = self.Session()
        try:
            codes = s.query(EmailAuthCode).filter_by(purpose="signup_verify").all()
            self.assertEqual(len(codes), 1)
            self.assertIsNone(codes[0].consumed_at)
        finally:
            s.close()

    def test_login_blocked_until_verified(self):
        self._signup()
        r = self.client.post(
            "/api/v1/auth/credentials/verify",
            json={"email": "new@example.com", "password": PW},
        )
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()["detail"], "email_not_verified")

    def test_verify_then_login_works(self):
        self._signup()
        r = self.client.post(
            "/api/v1/auth/verify-otp", json={"email": "new@example.com", "code": CODE}
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(self._user("new@example.com").email_verified)
        # login now succeeds
        r2 = self.client.post(
            "/api/v1/auth/credentials/verify",
            json={"email": "new@example.com", "password": PW},
        )
        self.assertEqual(r2.status_code, 200, r2.text)

    def test_wrong_code_then_lockout(self):
        self._signup()
        for _ in range(4):
            r = self.client.post(
                "/api/v1/auth/verify-otp", json={"email": "new@example.com", "code": "000000"}
            )
            self.assertEqual(r.status_code, 400)
            self.assertEqual(r.json()["detail"], "invalid_code")
        # 5th wrong attempt → locked
        r = self.client.post(
            "/api/v1/auth/verify-otp", json={"email": "new@example.com", "code": "000000"}
        )
        self.assertEqual(r.status_code, 429)
        self.assertEqual(r.json()["detail"], "too_many_attempts")
        # even the correct code is rejected once locked
        r = self.client.post(
            "/api/v1/auth/verify-otp", json={"email": "new@example.com", "code": CODE}
        )
        self.assertEqual(r.status_code, 429)
        self.assertFalse(self._user("new@example.com").email_verified)

    def test_forgot_then_reset_password(self):
        self._signup()
        r = self.client.post("/api/v1/auth/forgot-password", json={"email": "new@example.com"})
        self.assertEqual(r.status_code, 200)
        r = self.client.post(
            "/api/v1/auth/reset-password",
            json={"email": "new@example.com", "code": CODE, "new_password": NEW_PW},
        )
        self.assertEqual(r.status_code, 200, r.text)
        # reset also verified the email; new password works, old does not
        ok = self.client.post(
            "/api/v1/auth/credentials/verify",
            json={"email": "new@example.com", "password": NEW_PW},
        )
        self.assertEqual(ok.status_code, 200, ok.text)
        bad = self.client.post(
            "/api/v1/auth/credentials/verify",
            json={"email": "new@example.com", "password": PW},
        )
        self.assertEqual(bad.status_code, 401)

    def test_forgot_password_unknown_email_is_200_and_silent(self):
        r = self.client.post("/api/v1/auth/forgot-password", json={"email": "nobody@example.com"})
        self.assertEqual(r.status_code, 200)
        self.mock_send.assert_not_called()

    def test_resend_cooldown(self):
        self._signup()  # issues one code immediately
        r = self.client.post("/api/v1/auth/resend-otp", json={"email": "new@example.com"})
        self.assertEqual(r.status_code, 429)  # within 60s cooldown


if __name__ == "__main__":
    unittest.main()
