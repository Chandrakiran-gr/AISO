import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.auth import hash_password, verify_password
from api.database import Base, Client, User
from api.routes.auth import (
    CredentialsSignup,
    CredentialsVerify,
    OAuthUserUpsert,
    signup_with_credentials,
    upsert_oauth_user,
    verify_credentials,
)


class AuthPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def test_password_hashes_are_verified_without_storing_plaintext(self):
        stored_hash = hash_password("correct-horse-battery")

        self.assertNotIn("correct-horse-battery", stored_hash)
        self.assertTrue(verify_password("correct-horse-battery", stored_hash))
        self.assertFalse(verify_password("wrong-password", stored_hash))

    def test_credentials_signup_persists_user_and_login_verifies(self):
        session = self.Session()
        try:
            created = signup_with_credentials(
                CredentialsSignup(
                    name="Jane Founder",
                    email="JANE@Example.COM",
                    password="secure-password",
                ),
                db=session,
            )

            self.assertEqual(created.email, "jane@example.com")
            self.assertEqual(created.provider, "credentials")
            self.assertNotEqual(created.password_hash, "secure-password")
            self.assertEqual(session.query(User).count(), 1)

            verified = verify_credentials(
                CredentialsVerify(
                    email="jane@example.com",
                    password="secure-password",
                ),
                db=session,
            )
            self.assertEqual(verified.id, created.id)
        finally:
            session.close()

    def test_credentials_signup_rejects_duplicate_email(self):
        session = self.Session()
        try:
            payload = CredentialsSignup(
                name="Jane Founder",
                email="jane@example.com",
                password="secure-password",
            )
            signup_with_credentials(payload, db=session)

            with self.assertRaises(HTTPException) as error:
                signup_with_credentials(payload, db=session)

            self.assertEqual(error.exception.status_code, 409)
        finally:
            session.close()

    def test_google_oauth_upsert_persists_user_and_migrates_legacy_clients(self):
        session = self.Session()
        try:
            session.add(
                Client(
                    id="client-1",
                    user_id="founder@example.com",
                    name="AISO Demo",
                    url="https://example.com",
                )
            )
            session.commit()

            user = upsert_oauth_user(
                OAuthUserUpsert(
                    email="Founder@Example.com",
                    name="Founder",
                    provider="google",
                ),
                db=session,
                _=None,
            )

            self.assertEqual(user.email, "founder@example.com")
            self.assertEqual(user.provider, "google")
            self.assertIsNone(user.password_hash)
            self.assertEqual(session.query(User).count(), 1)
            self.assertEqual(session.query(Client).one().user_id, user.id)

            same_user = upsert_oauth_user(
                OAuthUserUpsert(
                    email="founder@example.com",
                    name="Founder Updated",
                    provider="google",
                ),
                db=session,
                _=None,
            )

            self.assertEqual(same_user.id, user.id)
            self.assertEqual(session.query(User).count(), 1)
            self.assertEqual(same_user.name, "Founder Updated")
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()
