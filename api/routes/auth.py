"""Auth persistence routes for AISO.

NextAuth handles browser sessions. These endpoints make that session durable in
the AISO database for OAuth and credentials accounts.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, field_validator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.auth import (
    get_current_user_id,
    hash_password,
    normalize_email,
    verify_internal_request,
    verify_password,
)
from api.database import Client, User, get_db
from api.entitlements import apply_account_entitlements, entitlements_for_user
from api.email import EmailSendError, send_otp_email
from api.auth_otp import (
    OtpRateLimited,
    PURPOSE_RESET,
    PURPOSE_SIGNUP,
    consume_signin_grant,
    issue_code,
    issue_signin_grant,
    verify_code,
)
from api.pending_signup import (
    resend_pending_code,
    start_pending_signup,
    verify_pending_signup,
)

router = APIRouter(prefix="/auth", tags=["auth"])

PASSWORD_POLICY_MESSAGE = (
    "Password must be at least 8 characters and include uppercase, lowercase, "
    "number, and special character."
)
PASSWORD_POLICY_PATTERN = re.compile(
    r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^A-Za-z0-9\s]).{8,}$"
)


class CredentialsSignup(BaseModel):
    name: Optional[str] = None
    email: str
    password: str

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        clean = " ".join(value.strip().split())
        return clean[:120] or None

    @field_validator("password")
    @classmethod
    def password_must_be_strong(cls, value: str) -> str:
        if not PASSWORD_POLICY_PATTERN.match(value or ""):
            raise ValueError(PASSWORD_POLICY_MESSAGE)
        return value


class CredentialsVerify(BaseModel):
    email: str
    password: str


class OAuthUserUpsert(BaseModel):
    email: str
    name: Optional[str] = None
    provider: str = "google"

    @field_validator("provider")
    @classmethod
    def provider_must_be_supported(cls, value: str) -> str:
        clean = str(value or "").strip().lower()
        if clean not in {"google"}:
            raise ValueError("Unsupported OAuth provider")
        return clean

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        clean = " ".join(value.strip().split())
        return clean[:120] or None


class AuthUserResponse(BaseModel):
    id: str
    email: str
    name: Optional[str]
    provider: str
    plan_tier: str
    account_role: str
    created_at: datetime
    is_active: bool

    class Config:
        from_attributes = True


class EntitlementsResponse(BaseModel):
    """Per-user tier + entitlements for the frontend (live, never cached)."""

    user_id: str
    email: str
    plan_tier: str
    account_role: str
    max_clients: Optional[int]
    uses_managed_keys: bool
    business_count: int
    billing_model: str
    can_download_artifacts: bool
    can_view_full_citations: bool
    can_view_source_graph: bool


class VerifyOtp(BaseModel):
    email: str
    code: str


class ResendOtp(BaseModel):
    email: str


class ForgotPassword(BaseModel):
    email: str


class ResetPassword(BaseModel):
    email: str
    code: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def password_must_be_strong(cls, value: str) -> str:
        if not PASSWORD_POLICY_PATTERN.match(value or ""):
            raise ValueError(PASSWORD_POLICY_MESSAGE)
        return value


class OkResponse(BaseModel):
    ok: bool = True
    status: Optional[str] = None
    # One-time grant returned by verify-otp so the client can sign in immediately.
    signin_token: Optional[str] = None


class ConsumeSigninToken(BaseModel):
    email: str
    token: str


class DeleteAccount(BaseModel):
    confirmation: str


@router.get("/me", response_model=EntitlementsResponse)
def get_me(
    response: Response,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> EntitlementsResponse:
    """Return the current user's tier + entitlements + live business count.

    Drives the frontend's tier-aware UI (BYOK vs managed keys, business limit,
    feature gates). Tier can change via admin/billing, so it must never be
    cached at the HTTP layer.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="Unknown user")
    ent = entitlements_for_user(user)
    business_count = db.query(Client).filter(Client.user_id == user_id).count()
    response.headers["Cache-Control"] = "no-store"
    return EntitlementsResponse(
        user_id=user.id,
        email=user.email,
        plan_tier=ent.plan_tier,
        account_role=ent.account_role,
        max_clients=ent.max_clients,
        uses_managed_keys=ent.uses_managed_keys,
        business_count=business_count,
        billing_model=ent.billing_model,
        can_download_artifacts=ent.can_download_artifacts,
        can_view_full_citations=ent.can_view_full_citations,
        can_view_source_graph=ent.can_view_source_graph,
    )


def _find_user_by_email(db: Session, email: str) -> User | None:
    return db.query(User).filter(User.email == email).first()


def _otp_failure_http(reason: str) -> HTTPException:
    if reason == "locked":
        return HTTPException(status_code=429, detail="too_many_attempts")
    if reason == "expired":
        return HTTPException(status_code=400, detail="code_expired")
    return HTTPException(status_code=400, detail="invalid_code")


def _migrate_legacy_client_owner(
    db: Session,
    legacy_user_id: str,
    user_id: str,
) -> None:
    """Move old email-scoped client rows onto the durable DB user id."""
    if legacy_user_id == user_id:
        return
    db.query(Client).filter(Client.user_id == legacy_user_id).update(
        {Client.user_id: user_id},
        synchronize_session=False,
    )


@router.post(
    "/signup",
    response_model=OkResponse,
    status_code=status.HTTP_201_CREATED,
)
def signup_with_credentials(
    payload: CredentialsSignup,
    db: Session = Depends(get_db),
) -> OkResponse:
    """Begin an email/password signup: stash a pending record and email an OTP.

    No ``users`` row is created here -- the account is only persisted once the OTP
    is verified (see ``verify-otp``), so the users table holds only verified
    accounts. A re-signup with the same email resumes the same pending record.
    """
    email = normalize_email(payload.email)
    existing = _find_user_by_email(db, email)
    if existing:  # the email already belongs to a real (verified) account
        raise HTTPException(status_code=409, detail="Email already exists")

    try:
        code = start_pending_signup(
            db,
            email=email,
            name=payload.name,
            password_hash=hash_password(payload.password),
        )
        send_otp_email(to=email, code=code, purpose=PURPOSE_SIGNUP)
    except OtpRateLimited:
        db.rollback()  # a code was sent moments ago; the existing one still works
    except EmailSendError:
        pass  # code stored; the user can resend after the cooldown
    return OkResponse(ok=True, status="verification_sent")


@router.post("/credentials/verify", response_model=AuthUserResponse)
def verify_credentials(
    payload: CredentialsVerify,
    db: Session = Depends(get_db),
) -> User:
    """Verify credentials for NextAuth without exposing password hashes."""
    email = normalize_email(payload.email)
    user = _find_user_by_email(db, email)
    if (
        not user
        or not user.is_active
        or not user.password_hash
        or not verify_password(payload.password, user.password_hash)
    ):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not user.email_verified:
        raise HTTPException(status_code=403, detail="email_not_verified")

    apply_account_entitlements(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/oauth/upsert", response_model=AuthUserResponse)
def upsert_oauth_user(
    payload: OAuthUserUpsert,
    db: Session = Depends(get_db),
    _: None = Depends(verify_internal_request),
) -> User:
    """Create or update a durable DB user after successful OAuth login."""
    email = normalize_email(payload.email)
    user = _find_user_by_email(db, email)

    if user:
        if payload.name and payload.name != user.name:
            user.name = payload.name
        if not user.provider:
            user.provider = payload.provider
    else:
        user = User(
            id=str(uuid.uuid4()),
            email=email,
            name=payload.name,
            provider=payload.provider,
            password_hash=None,
            is_active=True,
        )
        apply_account_entitlements(user)
        db.add(user)
        db.flush()
    apply_account_entitlements(user)
    # OAuth providers verify the email, so these accounts are pre-verified.
    if not user.email_verified:
        user.email_verified = True
        user.verified_at = datetime.now(timezone.utc)

    _migrate_legacy_client_owner(db, legacy_user_id=email, user_id=user.id)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = _find_user_by_email(db, email)
        if existing:
            return existing
        raise
    db.refresh(user)
    return user


@router.post("/verify-otp", response_model=OkResponse)
def verify_email_otp(payload: VerifyOtp, db: Session = Depends(get_db)) -> OkResponse:
    """Confirm a signup OTP and create the real, verified account.

    The pending signup (hashed password + name) is promoted to a ``users`` row
    only here, after the code checks out. The pending record is then deleted.
    """
    email = normalize_email(payload.email)
    existing = _find_user_by_email(db, email)
    if existing and existing.email_verified:  # already promoted (e.g. double submit)
        return OkResponse(ok=True, status="already_verified")

    ok, reason, pending = verify_pending_signup(db, email=email, code=payload.code)
    if not ok or pending is None:
        raise _otp_failure_http(reason)

    user = User(
        id=str(uuid.uuid4()),
        email=pending.email,
        name=pending.name,
        password_hash=pending.password_hash,
        provider="credentials",
        is_active=True,
        email_verified=True,
        verified_at=datetime.now(timezone.utc),
    )
    apply_account_entitlements(user)
    db.add(user)
    db.flush()  # parent before child (FK): user.id must exist before the grant row
    token = issue_signin_grant(db, user=user)
    db.delete(pending)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()  # raced with a concurrent verify; treat as success if the user now exists
        if _find_user_by_email(db, email):
            return OkResponse(ok=True, status="already_verified")
        raise HTTPException(status_code=400, detail="invalid_code")
    # Return a one-time grant so the client can sign in and go straight to onboarding.
    return OkResponse(ok=True, signin_token=token)


@router.post("/consume-signin-token", response_model=AuthUserResponse)
def consume_signin_token(
    payload: ConsumeSigninToken,
    db: Session = Depends(get_db),
    _: None = Depends(verify_internal_request),
) -> User:
    """Exchange a one-time post-verification grant for the user (no password).

    Backs NextAuth's credentials ``authorize`` token path, so a just-verified
    account is signed in and sent straight to onboarding. The grant is single-use
    and expires in minutes; anything invalid is a generic 401. Gated to
    server-to-server callers (internal secret), matching ``/oauth/upsert``.
    """
    email = normalize_email(payload.email)
    user = _find_user_by_email(db, email)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="invalid_grant")
    if not consume_signin_grant(db, user=user, token=payload.token):
        raise HTTPException(status_code=401, detail="invalid_grant")
    apply_account_entitlements(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/resend-otp", response_model=OkResponse)
def resend_email_otp(payload: ResendOtp, db: Session = Depends(get_db)) -> OkResponse:
    """Resend the signup OTP for a pending signup (rate-limited)."""
    email = normalize_email(payload.email)
    try:
        code = resend_pending_code(db, email=email)
    except OtpRateLimited as exc:
        raise HTTPException(status_code=429, detail="rate_limited") from exc
    if code is not None:
        try:
            send_otp_email(to=email, code=code, purpose=PURPOSE_SIGNUP)
        except EmailSendError as exc:
            raise HTTPException(status_code=502, detail="email_send_failed") from exc
    return OkResponse(ok=True)


@router.post("/forgot-password", response_model=OkResponse)
def forgot_password(payload: ForgotPassword, db: Session = Depends(get_db)) -> OkResponse:
    """Email a password-reset OTP. Always 200 (no account enumeration)."""
    email = normalize_email(payload.email)
    user = _find_user_by_email(db, email)
    if user and user.password_hash:  # only credentials accounts have a password to reset
        try:
            code = issue_code(db, user=user, purpose=PURPOSE_RESET)
            send_otp_email(to=user.email, code=code, purpose=PURPOSE_RESET)
        except (OtpRateLimited, EmailSendError):
            pass  # never reveal account state or rate-limit on the reset path
    return OkResponse(ok=True)


@router.post("/reset-password", response_model=OkResponse)
def reset_password(payload: ResetPassword, db: Session = Depends(get_db)) -> OkResponse:
    """Set a new password using the reset OTP. Proving inbox control also verifies the email."""
    email = normalize_email(payload.email)
    user = _find_user_by_email(db, email)
    if not user or not user.password_hash:
        raise HTTPException(status_code=400, detail="invalid_code")
    ok, reason = verify_code(db, user=user, purpose=PURPOSE_RESET, code=payload.code)
    if not ok:
        raise _otp_failure_http(reason)
    user.password_hash = hash_password(payload.new_password)
    if not user.email_verified:
        user.email_verified = True
        user.verified_at = datetime.now(timezone.utc)
    db.commit()
    return OkResponse(ok=True)


DELETE_ACCOUNT_PHRASE = "I confirm to delete my account"


@router.post("/delete-account", response_model=OkResponse)
def delete_account(
    payload: DeleteAccount,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> OkResponse:
    """Permanently delete the current account and all related data.

    Requires the exact confirmation phrase (also enforced in the UI). Deletion
    cascades via DB foreign keys (clients -> scans/profiles/citations/actions/
    conversations/drafts). ``scan_provenance`` is the one FK without ON DELETE
    CASCADE, so its (Gen-2) rows are cleared first to avoid blocking the cascade.
    """
    if payload.confirmation.strip() != DELETE_ACCOUNT_PHRASE:
        raise HTTPException(status_code=400, detail="confirmation_mismatch")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="not_found")

    db.execute(
        text(
            "DELETE FROM scan_provenance WHERE scan_id IN ("
            " SELECT sr.id FROM scan_runs sr"
            " JOIN clients c ON c.id = sr.client_id WHERE c.user_id = :uid)"
        ),
        {"uid": user_id},
    )
    db.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": user_id})
    db.commit()
    return OkResponse(ok=True)
