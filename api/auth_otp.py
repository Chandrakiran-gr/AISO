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
PURPOSE_SIGNIN = "signin_grant"
VALID_PURPOSES = {PURPOSE_SIGNUP, PURPOSE_RESET, PURPOSE_SIGNIN}

CODE_TTL = timedelta(minutes=10)
MAX_ATTEMPTS = 5
RESEND_COOLDOWN = timedelta(seconds=60)
MAX_PER_HOUR = 5

# A one-time grant minted right after email verification so the freshly created
# account can be signed in (and sent to onboarding) without re-entering a password.
# Opaque token (not a 6-digit code), short-lived, single-use.
SIGNIN_GRANT_TTL = timedelta(minutes=2)

# Password-reset link token: opaque, single-use, emailed inside a link. Longer-lived
# than an OTP since the user reads the email and then clicks. Consumed only when the
# new password is submitted (never on opening the link), so link prefetchers can't burn it.
RESET_TOKEN_TTL = timedelta(minutes=15)


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


def generate_url_token() -> str:
    """A high-entropy opaque, URL-safe token (signin grant + password-reset link)."""
    return secrets.token_urlsafe(32)


def issue_signin_grant(db: Session, *, user: User) -> str:
    """Mint a single-use signin grant for ``user``; return the plaintext token.

    Stored hashed (reusing ``email_auth_codes``) like every other code. Does not
    commit -- the caller commits alongside the row that created the account, so the
    grant and the user land in the same transaction. Invalidates prior grants.
    """
    now = _now()
    for row in (
        db.query(EmailAuthCode)
        .filter(
            EmailAuthCode.user_id == user.id,
            EmailAuthCode.purpose == PURPOSE_SIGNIN,
            EmailAuthCode.consumed_at.is_(None),
        )
        .all()
    ):
        row.consumed_at = now
    token = generate_url_token()
    db.add(
        EmailAuthCode(
            id=str(uuid.uuid4()),
            user_id=user.id,
            purpose=PURPOSE_SIGNIN,
            code_hash=hash_code(token),
            expires_at=now + SIGNIN_GRANT_TTL,
            attempts=0,
        )
    )
    return token


def consume_signin_grant(db: Session, *, user: User, token: str) -> bool:
    """Validate + consume a signin grant for ``user``. Returns whether it was valid.

    Single-use and time-limited. Does not commit -- the caller commits. A wrong or
    expired token simply returns ``False`` (no attempt counter: the token is opaque
    and unguessable, so brute force is not a concern).
    """
    now = _now()
    row = (
        db.query(EmailAuthCode)
        .filter(
            EmailAuthCode.user_id == user.id,
            EmailAuthCode.purpose == PURPOSE_SIGNIN,
            EmailAuthCode.consumed_at.is_(None),
        )
        .order_by(EmailAuthCode.created_at.desc())
        .first()
    )
    if row is None:
        return False
    if (_as_utc(row.expires_at) or now) < now:
        return False
    if not token or not hmac.compare_digest(hash_code(token), row.code_hash):
        return False
    row.consumed_at = now
    return True


def issue_reset_token(db: Session, *, user: User) -> str:
    """Mint a single-use password-reset token; return the plaintext for the email link.

    Rate-limited like ``issue_code`` (60s cooldown + hourly cap) and invalidates any
    prior unconsumed reset tokens, so only the newest link works. Commits.
    """
    now = _now()
    recent = (
        db.query(EmailAuthCode)
        .filter(EmailAuthCode.user_id == user.id, EmailAuthCode.purpose == PURPOSE_RESET)
        .order_by(EmailAuthCode.created_at.desc())
        .all()
    )
    hour_ago = now - timedelta(hours=1)
    if sum(1 for c in recent if (_as_utc(c.created_at) or now) >= hour_ago) >= MAX_PER_HOUR:
        raise OtpRateLimited("Too many reset requests. Try again later.")
    if recent and (_as_utc(recent[0].created_at) or now) > now - RESEND_COOLDOWN:
        raise OtpRateLimited("Please wait before requesting another reset link.")
    for c in recent:  # invalidate prior unconsumed reset tokens
        if c.consumed_at is None:
            c.consumed_at = now

    token = generate_url_token()
    db.add(
        EmailAuthCode(
            id=str(uuid.uuid4()),
            user_id=user.id,
            purpose=PURPOSE_RESET,
            code_hash=hash_code(token),
            expires_at=now + RESET_TOKEN_TTL,
            attempts=0,
        )
    )
    db.commit()
    return token


def consume_reset_token(db: Session, *, token: str) -> User | None:
    """Validate + consume a password-reset token; return its user (or ``None``).

    The token alone identifies the row (looked up by its hash), so the reset link
    needs no email in the URL. Single-use and time-limited. Does not commit -- the
    caller sets the new password and commits in the same transaction.
    """
    now = _now()
    if not token:
        return None
    row = (
        db.query(EmailAuthCode)
        .filter(
            EmailAuthCode.purpose == PURPOSE_RESET,
            EmailAuthCode.code_hash == hash_code(token),
            EmailAuthCode.consumed_at.is_(None),
        )
        .order_by(EmailAuthCode.created_at.desc())
        .first()
    )
    if row is None:
        return None
    if (_as_utc(row.expires_at) or now) < now:
        return None
    user = db.query(User).filter(User.id == row.user_id).first()
    if user is None:
        return None
    row.consumed_at = now
    return user
