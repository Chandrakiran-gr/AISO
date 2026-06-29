"""Email OTP verification + password reset flow (backend).

Deterministic code via patching generate_code; email send is patched to a no-op
(the real sender already no-ops without RESEND_API_KEY, but patching keeps logs clean
and lets us assert it was/wasn't called).
"""

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from sqlalchemy import event

from tests._pgharness import make_test_engine, reset_schema, using_postgres
from api.auth import verify_internal_request
from api.database import Client, EmailAuthCode, PendingSignup, User, get_db
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
        # The signin-grant endpoint is gated to server-to-server callers; bypass that
        # gate here so the grant tests cover grant logic, not the internal-secret check.
        app.dependency_overrides[verify_internal_request] = lambda: None
        self.client = TestClient(app, base_url="http://localhost")

        gen = patch("api.auth_otp.generate_code", return_value=CODE)
        gen.start()
        self.addCleanup(gen.stop)
        self.send = patch("api.routes.auth.send_otp_email")
        self.mock_send = self.send.start()
        self.addCleanup(self.send.stop)

    def tearDown(self):
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(verify_internal_request, None)
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
    def test_signup_creates_pending_not_user(self):
        r = self._signup()
        self.assertEqual(r.status_code, 201, r.text)
        self.assertIsNone(self._user("new@example.com"))  # no users row until verified
        self.mock_send.assert_called_once()
        s = self.Session()
        try:
            pending = s.query(PendingSignup).filter_by(email="new@example.com").all()
            self.assertEqual(len(pending), 1)
        finally:
            s.close()

    def test_login_unknown_until_verified(self):
        self._signup()
        r = self.client.post(
            "/api/v1/auth/credentials/verify",
            json={"email": "new@example.com", "password": PW},
        )
        self.assertEqual(r.status_code, 401)  # the account does not exist until verified

    def test_verify_creates_user_and_login_works(self):
        self._signup()
        r = self.client.post(
            "/api/v1/auth/verify-otp", json={"email": "new@example.com", "code": CODE}
        )
        self.assertEqual(r.status_code, 200, r.text)
        user = self._user("new@example.com")
        self.assertIsNotNone(user)
        self.assertTrue(user.email_verified)
        self.assertEqual(user.provider, "credentials")
        s = self.Session()
        try:
            self.assertEqual(s.query(PendingSignup).count(), 0)  # pending row consumed
        finally:
            s.close()
        # login now succeeds
        r2 = self.client.post(
            "/api/v1/auth/credentials/verify",
            json={"email": "new@example.com", "password": PW},
        )
        self.assertEqual(r2.status_code, 200, r2.text)

    def test_wrong_code_then_lockout_creates_no_user(self):
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
        # even the correct code is rejected once locked, and no account was created
        r = self.client.post(
            "/api/v1/auth/verify-otp", json={"email": "new@example.com", "code": CODE}
        )
        self.assertEqual(r.status_code, 429)
        self.assertIsNone(self._user("new@example.com"))

    def test_signup_blocked_when_verified_account_exists(self):
        self._signup()
        self.client.post(
            "/api/v1/auth/verify-otp", json={"email": "new@example.com", "code": CODE}
        )
        # a real account now owns the email → a fresh signup is rejected
        r = self._signup()
        self.assertEqual(r.status_code, 409)

    def test_resignup_resumes_without_duplicate(self):
        self._signup()
        # immediate re-signup is within the cooldown: no new email, no dup row, no user
        r = self._signup()
        self.assertEqual(r.status_code, 201, r.text)
        self.mock_send.assert_called_once()
        self.assertIsNone(self._user("new@example.com"))
        s = self.Session()
        try:
            self.assertEqual(
                s.query(PendingSignup).filter_by(email="new@example.com").count(), 1
            )
        finally:
            s.close()

    def test_forgot_then_reset_password(self):
        # forgot/reset operate on a real (verified) account, so create one first
        self._signup()
        self.client.post(
            "/api/v1/auth/verify-otp", json={"email": "new@example.com", "code": CODE}
        )
        r = self.client.post("/api/v1/auth/forgot-password", json={"email": "new@example.com"})
        self.assertEqual(r.status_code, 200)
        r = self.client.post(
            "/api/v1/auth/reset-password",
            json={"email": "new@example.com", "code": CODE, "new_password": NEW_PW},
        )
        self.assertEqual(r.status_code, 200, r.text)
        # new password works, old does not
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
        self._signup()  # sends one code immediately
        r = self.client.post("/api/v1/auth/resend-otp", json={"email": "new@example.com"})
        self.assertEqual(r.status_code, 429)  # within 60s cooldown
        self.assertEqual(r.json()["detail"], "rate_limited")

    # signin grant (auto sign-in to onboarding after verification)
    def _verify(self, email="new@example.com"):
        return self.client.post("/api/v1/auth/verify-otp", json={"email": email, "code": CODE})

    def test_verify_returns_grant_and_consume_signs_in(self):
        self._signup()
        token = self._verify().json().get("signin_token")
        self.assertTrue(token)  # a one-time grant is returned on successful verify
        c = self.client.post(
            "/api/v1/auth/consume-signin-token",
            json={"email": "new@example.com", "token": token},
        )
        self.assertEqual(c.status_code, 200, c.text)
        self.assertEqual(c.json()["email"], "new@example.com")

    def test_signin_grant_is_single_use(self):
        self._signup()
        token = self._verify().json()["signin_token"]
        first = self.client.post(
            "/api/v1/auth/consume-signin-token",
            json={"email": "new@example.com", "token": token},
        )
        self.assertEqual(first.status_code, 200)
        second = self.client.post(
            "/api/v1/auth/consume-signin-token",
            json={"email": "new@example.com", "token": token},
        )
        self.assertEqual(second.status_code, 401)

    def test_signin_grant_rejects_wrong_token(self):
        self._signup()
        self._verify()
        bad = self.client.post(
            "/api/v1/auth/consume-signin-token",
            json={"email": "new@example.com", "token": "not-a-real-grant-token"},
        )
        self.assertEqual(bad.status_code, 401)

    def test_signin_grant_expired_is_rejected(self):
        self._signup()
        token = self._verify().json()["signin_token"]
        s = self.Session()
        try:
            row = (
                s.query(EmailAuthCode)
                .filter_by(purpose="signin_grant")
                .order_by(EmailAuthCode.created_at.desc())
                .first()
            )
            row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
            s.commit()
        finally:
            s.close()
        r = self.client.post(
            "/api/v1/auth/consume-signin-token",
            json={"email": "new@example.com", "token": token},
        )
        self.assertEqual(r.status_code, 401)


class AccountDeletionTests(unittest.TestCase):
    def setUp(self):
        self.engine = make_test_engine()
        if not using_postgres():  # enforce FK cascade on SQLite (prod-faithful)
            event.listen(
                self.engine,
                "connect",
                lambda dbapi_con, _rec: dbapi_con.execute("PRAGMA foreign_keys=ON"),
            )
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

    def tearDown(self):
        app.dependency_overrides.pop(get_db, None)
        self.engine.dispose()

    def _seed(self):
        s = self.Session()
        try:
            s.add(User(id="del-1", email="del@example.com", password_hash="x",
                       provider="credentials", is_active=True, email_verified=True))
            s.flush()
            s.add(Client(id="c-del", user_id="del-1", name="Biz", url="https://del.example.com"))
            s.commit()
        finally:
            s.close()

    def _counts(self):
        s = self.Session()
        try:
            return (
                s.query(User).filter_by(id="del-1").count(),
                s.query(Client).filter_by(user_id="del-1").count(),
            )
        finally:
            s.close()

    def test_wrong_phrase_does_not_delete(self):
        self._seed()
        r = self.client.post(
            "/api/v1/auth/delete-account",
            json={"confirmation": "delete my account"},
            headers={"X-User-Id": "del-1"},
        )
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["detail"], "confirmation_mismatch")
        self.assertEqual(self._counts(), (1, 1))

    def test_correct_phrase_deletes_and_cascades(self):
        self._seed()
        r = self.client.post(
            "/api/v1/auth/delete-account",
            json={"confirmation": "I confirm to delete my account"},
            headers={"X-User-Id": "del-1"},
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self._counts(), (0, 0))  # user + their client (cascade) gone

    def test_requires_authentication(self):
        r = self.client.post(
            "/api/v1/auth/delete-account",
            json={"confirmation": "I confirm to delete my account"},
        )
        self.assertEqual(r.status_code, 401)


if __name__ == "__main__":
    unittest.main()
