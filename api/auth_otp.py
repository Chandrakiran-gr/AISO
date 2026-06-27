"""One-time codes for email verification and password reset.

Codes are 6-digit, hashed (HMAC-SHA256 with a server pepper) at rest, single-use,
short-lived (10 min), attempt-limited, and rate-limited on issuance. Plaintext codes
exist only transiently to email; the database never stores them.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from api.database import EmailAuthCode, User

PURPOSE_SIGNUP = "signup_verify"
PURPOSE_RESET = "password_reset"
VALID_PURPOSES = {PURPOSE_SIGNUP, PURPOSE_RESET}

CODE_TTL = timedelta(minutes=10)
MAX_ATTEMPTS = 5
RESEND_COOLDOWN = timedelta(seconds=60)
MAX_PER_HOUR = 5


class OtpRateLimited(RuntimeError):
    """Issuance blocked by the resend cooldown or the hourly cap."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _pepper() -> bytes:
    secret = os.getenv("AISO_INTERNAL_API_SECRET") or os.getenv("AUTH_SECRET") or "dev-insecure-otp-pepper"
    return secret.encode("utf-8")


def generate_code() -> str:
    """A uniformly-random 6-digit code (leading zeros preserved)."""
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_code(code: str) -> str:
    return hmac.new(_pepper(), code.encode("utf-8"), hashlib.sha256).hexdigest()


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def issue_code(db: Session, *, user: User, purpose: str) -> str:
    """Create + persist a new code for (user, purpose); return the plaintext to email.

    Raises ``OtpRateLimited`` on cooldown / hourly cap. Invalidates any prior
    unconsumed codes so only the newest is valid. The user row must already exist.
    """
    if purpose not in VALID_PURPOSES:
        raise ValueError(f"Unknown OTP purpose: {purpose}")
    now = _now()

    recent = (
        db.query(EmailAuthCode)
        .filter(EmailAuthCode.user_id == user.id, EmailAuthCode.purpose == purpose)
        .order_by(EmailAuthCode.created_at.desc())
        .all()
    )
    hour_ago = now - timedelta(hours=1)
    if sum(1 for c in recent if (_as_utc(c.created_at) or now) >= hour_ago) >= MAX_PER_HOUR:
        raise OtpRateLimited("Too many codes requested. Try again later.")
    if recent and (_as_utc(recent[0].created_at) or now) > now - RESEND_COOLDOWN:
        raise OtpRateLimited("Please wait before requesting another code.")

    for c in recent:  # invalidate prior unconsumed codes for this purpose
        if c.consumed_at is None:
            c.consumed_at = now

    code = generate_code()
    db.add(
        EmailAuthCode(
            id=str(uuid.uuid4()),
            user_id=user.id,
            purpose=purpose,
            code_hash=hash_code(code),
            expires_at=now + CODE_TTL,
            attempts=0,
        )
    )
    db.commit()
    return code


def verify_code(db: Session, *, user: User, purpose: str, code: str) -> tuple[bool, str]:
    """Verify a submitted code. Returns ``(ok, reason)``.

    ``reason`` is one of: ``ok``, ``no_code``, ``expired``, ``locked``, ``mismatch``.
    A correct code is consumed (single-use). Wrong codes increment attempts; once
    attempts reach the cap the code is locked.
    """
    if purpose not in VALID_PURPOSES:
        raise ValueError(f"Unknown OTP purpose: {purpose}")
    now = _now()
    row = (
        db.query(EmailAuthCode)
        .filter(
            EmailAuthCode.user_id == user.id,
            EmailAuthCode.purpose == purpose,
            EmailAuthCode.consumed_at.is_(None),
        )
        .order_by(EmailAuthCode.created_at.desc())
        .first()
    )
    if row is None:
        return False, "no_code"
    if (_as_utc(row.expires_at) or now) < now:
        return False, "expired"
    if row.attempts >= MAX_ATTEMPTS:
        return False, "locked"

    submitted = "".join(ch for ch in str(code or "") if ch.isdigit())
    if submitted and hmac.compare_digest(hash_code(submitted), row.code_hash):
        row.consumed_at = now
        db.commit()
        return True, "ok"

    row.attempts += 1
    db.commit()
    return False, ("locked" if row.attempts >= MAX_ATTEMPTS else "mismatch")
