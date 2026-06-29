"""Transactional email via Resend — OTP verification and password reset.

Sends through the Resend HTTPS API. When ``RESEND_API_KEY`` is unset (local/dev),
this falls back to logging the message — including the code — so the verification
flow is testable end-to-end without a configured provider.

The sender is ``AISO_EMAIL_FROM`` (default: Resend's shared test sender, which only
delivers to your own Resend account email). Set it to
``AISO <noreply@aisoglobal.com>`` once aisoglobal.com is verified in Resend.
"""

from __future__ import annotations

import logging
import os

import requests

logger = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"
DEFAULT_FROM = "AISO <onboarding@resend.dev>"
SEND_TIMEOUT_SECONDS = 15


class EmailSendError(RuntimeError):
    """Raised when the email provider rejects or cannot receive a send."""


def _from_address() -> str:
    return os.getenv("AISO_EMAIL_FROM", DEFAULT_FROM)


def send_email(*, to: str, subject: str, html: str) -> None:
    """Send one transactional email. No-op-with-log when RESEND_API_KEY is unset."""
    api_key = os.getenv("RESEND_API_KEY")
    if not api_key:
        logger.warning("RESEND_API_KEY unset — email NOT sent (dev fallback). to=%s subject=%r", to, subject)
        logger.warning("DEV EMAIL BODY:\n%s", html)
        return
    try:
        resp = requests.post(
            RESEND_API_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"from": _from_address(), "to": [to], "subject": subject, "html": html},
            timeout=SEND_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        logger.error("Resend request failed: %s", exc)
        raise EmailSendError("Email provider unreachable") from exc
    if resp.status_code >= 400:
        # Log status only; the body can echo the recipient address.
        logger.error("Resend send failed: status=%s body=%s", resp.status_code, resp.text[:300])
        raise EmailSendError(f"Email send failed ({resp.status_code})")


def send_otp_email(*, to: str, code: str, purpose: str) -> None:
    """Send a one-time code for signup verification or password reset."""
    if purpose == "password_reset":
        subject = "Reset your AISO password"
        heading = "Reset your password"
        intro = "Use this code to reset your AISO password. It expires in 10 minutes."
    else:
        subject = "Verify your AISO email"
        heading = "Verify your email"
        intro = "Welcome to AISO. Use this code to verify your email address. It expires in 10 minutes."
    send_email(to=to, subject=subject, html=_otp_html(heading=heading, intro=intro, code=code))


def _otp_html(*, heading: str, intro: str, code: str) -> str:
    return f"""\
<div style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;max-width:480px;margin:0 auto;padding:32px 24px;color:#111">
  <h1 style="font-size:20px;margin:0 0 12px">{heading}</h1>
  <p style="font-size:14px;line-height:1.5;color:#444;margin:0 0 24px">{intro}</p>
  <div style="font-size:32px;font-weight:700;letter-spacing:8px;background:#f4f4f5;border-radius:10px;padding:18px;text-align:center;color:#111">{code}</div>
  <p style="font-size:12px;color:#888;margin:24px 0 0">If you didn't request this, you can ignore this email.</p>
</div>"""


def send_reset_link_email(*, to: str, link: str) -> None:
    """Email a password-reset link (click -> set a new password). No code to copy."""
    send_email(
        to=to,
        subject="Reset your AISO password",
        html=_reset_link_html(link=link),
    )


def _reset_link_html(*, link: str) -> str:
    return f"""\
<div style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;max-width:480px;margin:0 auto;padding:32px 24px;color:#111">
  <h1 style="font-size:20px;margin:0 0 12px">Reset your password</h1>
  <p style="font-size:14px;line-height:1.5;color:#444;margin:0 0 24px">Click the button below to choose a new AISO password. This link expires in 15 minutes and can be used once.</p>
  <a href="{link}" style="display:inline-block;background:#111;color:#fff;text-decoration:none;font-size:14px;font-weight:600;padding:12px 24px;border-radius:10px">Reset password</a>
  <p style="font-size:12px;color:#888;margin:24px 0 8px">Or paste this link into your browser:</p>
  <p style="font-size:12px;color:#888;margin:0 0 24px;word-break:break-all">{link}</p>
  <p style="font-size:12px;color:#888;margin:0">If you didn't request this, you can ignore this email and your password stays the same.</p>
</div>"""
