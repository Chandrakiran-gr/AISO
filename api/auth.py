import base64
import hashlib
import hmac
import os
import re
import secrets
from typing import Optional

from fastapi import Header, HTTPException

PASSWORD_ALGORITHM = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 600_000
PASSWORD_SALT_BYTES = 16
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email(email: str) -> str:
    """Normalize an email address for identity lookup."""
    clean = str(email or "").strip().lower()
    if len(clean) > 254 or not EMAIL_RE.match(clean):
        raise HTTPException(status_code=422, detail="Valid email is required")
    return clean


def validate_password(password: str) -> str:
    """Validate password length without logging or returning the secret."""
    if not isinstance(password, str) or not 8 <= len(password) <= 128:
        raise HTTPException(
            status_code=422,
            detail="Password must be between 8 and 128 characters",
        )
    return password


def hash_password(password: str) -> str:
    """Hash a password with PBKDF2-HMAC-SHA256 using a per-password salt."""
    password = validate_password(password)
    salt = secrets.token_bytes(PASSWORD_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PASSWORD_ITERATIONS,
    )
    return "$".join(
        [
            PASSWORD_ALGORITHM,
            str(PASSWORD_ITERATIONS),
            base64.urlsafe_b64encode(salt).decode("ascii"),
            base64.urlsafe_b64encode(digest).decode("ascii"),
        ]
    )


def verify_password(password: str, stored_hash: str | None) -> bool:
    """Verify a plaintext password against a stored hash."""
    if not password or not stored_hash:
        return False

    try:
        algorithm, iterations_raw, salt_raw, digest_raw = stored_hash.split("$", 3)
        if algorithm != PASSWORD_ALGORITHM:
            return False
        iterations = int(iterations_raw)
        salt = base64.urlsafe_b64decode(salt_raw.encode("ascii"))
        expected = base64.urlsafe_b64decode(digest_raw.encode("ascii"))
    except (ValueError, TypeError):
        return False

    actual = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return hmac.compare_digest(actual, expected)


def get_current_user_id(x_user_id: Optional[str] = Header(None)) -> str:
    """
    Dependency that extracts the authenticated user ID from the X-User-Id header.
    This header is securely set by the Next.js frontend proxy after verifying the NextAuth session.
    """
    if not x_user_id:
        raise HTTPException(status_code=401, detail="Unauthorized — missing X-User-Id header")
    return x_user_id


def verify_internal_request(
    x_aiso_internal_secret: Optional[str] = Header(None),
) -> None:
    """Protect server-to-server auth writes such as OAuth user upserts."""
    expected = os.getenv("AISO_INTERNAL_API_SECRET") or os.getenv("AUTH_SECRET")
    if not expected:
        if os.getenv("ENV") == "production":
            raise HTTPException(
                status_code=500,
                detail="Internal auth secret is not configured",
            )
        return

    if not x_aiso_internal_secret or not hmac.compare_digest(
        x_aiso_internal_secret,
        expected,
    ):
        raise HTTPException(status_code=401, detail="Unauthorized")
