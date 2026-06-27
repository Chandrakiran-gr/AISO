"""Pending signups: hold a credentials-account signup until its email OTP is
verified, so the ``users`` table only ever contains verified accounts.

A pending row carries the hashed password and the hashed OTP. On successful
verification the caller creates the real ``User`` from this row and deletes it.
Rate-limiting mirrors :mod:`api.auth_otp` (60s resend cooldown, 5 sends/hour) but
is tracked inline on the single per-email row rather than via a code history.
"""

from __future__ import annotations

import hmac
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from api import auth_otp
from api.auth_otp import (
    CODE_TTL,
    MAX_ATTEMPTS,
    MAX_PER_HOUR,
    RESEND_COOLDOWN,
    OtpRateLimited,
)
from api.database import PendingSignup

# Abandoned pending rows are purged opportunistically once this stale.
STALE_AFTER = timedelta(days=1)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _get(db: Session, email: str) -> PendingSignup | None:
    return db.query(PendingSignup).filter(PendingSignup.email == email).first()


def _enforce_rate_limit(row: PendingSignup, now: datetime) -> None:
    """Raise ``OtpRateLimited`` on the resend cooldown or the hourly cap."""
    last_sent = _as_utc(row.last_sent_at)
    if last_sent and last_sent > now - RESEND_COOLDOWN:
        raise OtpRateLimited("Please wait before requesting another code.")
    window_start = _as_utc(row.window_started_at) or now
    if now - window_start >= timedelta(hours=1):  # window expired -> reset the counter
        row.window_started_at = now
        row.send_count = 0
    if (row.send_count or 0) >= MAX_PER_HOUR:
        raise OtpRateLimited("Too many codes requested. Try again later.")


def _issue(row: PendingSignup, now: datetime) -> str:
    """Set a fresh code on the row, bump the send counters, return the plaintext."""
    code = auth_otp.generate_code()
    row.code_hash = auth_otp.hash_code(code)
    row.expires_at = now + CODE_TTL
    row.attempts = 0
    row.send_count = (row.send_count or 0) + 1
    row.last_sent_at = now
    return code


def start_pending_signup(db: Session, *, email: str, name: str | None, password_hash: str) -> str:
    """Create or refresh the pending signup for ``email``; return the OTP to email.

    A re-signup with the same email resumes the same row. Raises ``OtpRateLimited``
    on the cooldown / hourly cap (the caller may roll back and swallow it, since a
    valid code was already sent). ``email`` must already be normalized.
    """
    now = _now()
    # Opportunistic cleanup of long-abandoned rows (bounded, no cron needed).
    db.query(PendingSignup).filter(
        PendingSignup.expires_at < now - STALE_AFTER
    ).delete(synchronize_session=False)

    row = _get(db, email)
    if row is None:
        row = PendingSignup(
            id=str(uuid.uuid4()),
            email=email,
            name=name,
            password_hash=password_hash,
            code_hash="",
            expires_at=now,
            attempts=0,
            send_count=0,
            window_started_at=now,
            # Backdate so the very first send clears the cooldown check below.
            last_sent_at=now - RESEND_COOLDOWN - timedelta(seconds=1),
        )
        db.add(row)
        db.flush()
    else:
        row.name = name
        row.password_hash = password_hash  # latest password wins on resume

    _enforce_rate_limit(row, now)
    code = _issue(row, now)
    db.commit()
    return code


def resend_pending_code(db: Session, *, email: str) -> str | None:
    """Re-issue the OTP for an existing pending signup; return the plaintext.

    Returns ``None`` (silently) when there is no pending signup for the email.
    Raises ``OtpRateLimited`` on the cooldown / hourly cap.
    """
    now = _now()
    row = _get(db, email)
    if row is None:
        return None
    _enforce_rate_limit(row, now)
    code = _issue(row, now)
    db.commit()
    return code


def verify_pending_signup(
    db: Session, *, email: str, code: str
) -> tuple[bool, str, PendingSignup | None]:
    """Verify a submitted code against the pending signup.

    Returns ``(ok, reason, row)``. ``reason`` is one of ``ok`` / ``no_code`` /
    ``expired`` / ``locked`` / ``mismatch``. On success the still-attached ``row``
    is returned so the caller can mint the real user and delete it. Wrong codes
    increment attempts; once attempts reach the cap the code is locked.
    """
    now = _now()
    row = _get(db, email)
    if row is None:
        return False, "no_code", None
    if (_as_utc(row.expires_at) or now) < now:
        return False, "expired", None
    if row.attempts >= MAX_ATTEMPTS:
        return False, "locked", None

    submitted = "".join(ch for ch in str(code or "") if ch.isdigit())
    if submitted and hmac.compare_digest(auth_otp.hash_code(submitted), row.code_hash):
        return True, "ok", row

    row.attempts += 1
    db.commit()
    return False, ("locked" if row.attempts >= MAX_ATTEMPTS else "mismatch"), None
