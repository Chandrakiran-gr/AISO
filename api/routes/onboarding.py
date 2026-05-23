"""Phase 12 onboarding intake API.

This adapter owns HTTP/auth/database concerns. Minimum Context Floor decisions
live in ``api.domain.onboarding`` so the business rule stays framework-free.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session
import yaml

from api.adapters.profile_draft import default_profile_draft_provider
from api.adapters.prompt_registry import ensure_prompt_version
from api.auth import get_current_user_id
from api.database import BusinessProfile, Client, get_db
from api.domain.onboarding import (
    context_floor_met,
    merge_profile_patch,
    missing_context_fields,
    normalize_objective,
    normalize_vertical,
    profile_data_from_snapshot,
)
from api.domain.ports import BusinessProfileSnapshot, LLMProvider
from api.domain.profile_draft import (
    PROFILE_DRAFT_PROMPT_KEY,
    PROFILE_DRAFT_PROMPT_VERSION,
    generate_profile_draft,
    profile_draft_artifact,
    render_profile_draft_prompt,
)

router = APIRouter(tags=["onboarding"])
SCHEMA_DIR = Path(__file__).resolve().parents[2] / "intake_schemas"


class OnboardingStartRequest(BaseModel):
    client_id: Optional[str] = None
    display_name: Optional[str] = None
    name: Optional[str] = None
    url: str
    vertical: str
    objective: str
    category: Optional[str] = None

    @property
    def resolved_name(self) -> str:
        return " ".join((self.display_name or self.name or "").split())

    @property
    def resolved_url(self) -> str:
        return self.url.strip()


class OnboardingPatchRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    vertical: Optional[str] = None
    objective: Optional[str] = None
    category: Optional[str] = None
    icp: Optional[dict[str, Any]] = None
    geographic_scope: Optional[dict[str, Any]] = None
    competitors: Optional[list[str]] = None
    personas: Optional[dict[str, Any]] = None
    crawl_artifacts: Optional[dict[str, Any]] = None


class BusinessProfileResponse(BaseModel):
    onboarding_id: str
    client_id: str
    vertical: str
    objective: str
    category: str
    icp: dict[str, Any] = Field(default_factory=dict)
    geographic_scope: dict[str, Any] = Field(default_factory=dict)
    competitors: list[str] = Field(default_factory=list)
    personas: dict[str, Any] = Field(default_factory=dict)
    crawl_artifacts: dict[str, Any] = Field(default_factory=dict)
    floor_met: bool
    missing_fields: list[str] = Field(default_factory=list)
    onboarding_completed_at: Optional[datetime] = None
    founder_reviewed_at: Optional[datetime] = None


class OnboardingStartResponse(BusinessProfileResponse):
    client_name: str
    client_url: str


class OnboardingSubmitResponse(BaseModel):
    ok: bool
    onboarding_id: str
    client_id: str
    floor_met: bool
    missing_fields: list[str] = Field(default_factory=list)
    onboarding_completed_at: datetime


class ProfileDraftResponse(BusinessProfileResponse):
    field_sources: dict[str, str] = Field(default_factory=dict)
    field_flags: dict[str, str] = Field(default_factory=dict)
    rationale: dict[str, str] = Field(default_factory=dict)
    prompt_version: str
    prompt_hash: str
    provider: str
    model: str


class ConfirmProfileRequest(OnboardingPatchRequest):
    pass


class IntakeFieldResponse(BaseModel):
    id: str
    label: str
    type: str
    required: bool = False
    placeholder: Optional[str] = None
    patch_field: str
    options: list[str] = Field(default_factory=list)
    validators: dict[str, Any] = Field(default_factory=dict)


class IntakeSchemaResponse(BaseModel):
    vertical: str
    label: str
    description: str = ""
    required_fields: list[str] = Field(default_factory=list)
    fields: list[IntakeFieldResponse] = Field(default_factory=list)


def _profile_snapshot(profile: BusinessProfile) -> BusinessProfileSnapshot:
    return BusinessProfileSnapshot(
        client_id=profile.client_id,
        vertical=profile.vertical,
        objective=profile.objective,
        category=profile.category or "",
        icp=_dict_or_empty(profile.icp),
        geographic_scope=_dict_or_empty(profile.geographic_scope),
        competitors=_list_or_empty(profile.competitors),
        personas=_dict_or_empty(profile.personas),
        crawl_artifacts=_dict_or_empty(profile.crawl_artifacts),
        floor_met=bool(profile.floor_met),
        onboarding_completed_at=profile.onboarding_completed_at,
        founder_reviewed_at=profile.founder_reviewed_at,
    )


def _profile_response(profile: BusinessProfile) -> BusinessProfileResponse:
    snapshot = _profile_snapshot(profile)
    return BusinessProfileResponse(
        onboarding_id=profile.client_id,
        client_id=profile.client_id,
        vertical=snapshot.vertical,
        objective=snapshot.objective,
        category=snapshot.category,
        icp=snapshot.icp,
        geographic_scope=snapshot.geographic_scope,
        competitors=snapshot.competitors,
        personas=snapshot.personas,
        crawl_artifacts=snapshot.crawl_artifacts,
        floor_met=snapshot.floor_met,
        missing_fields=missing_context_fields(snapshot),
        onboarding_completed_at=snapshot.onboarding_completed_at,
        founder_reviewed_at=snapshot.founder_reviewed_at,
    )


def _profile_draft_meta(profile: BusinessProfile) -> dict[str, Any]:
    artifacts = _dict_or_empty(profile.crawl_artifacts)
    draft = artifacts.get("profile_draft") if isinstance(artifacts.get("profile_draft"), dict) else {}
    return draft


def _apply_profile_data(profile: BusinessProfile, data: dict[str, Any]) -> None:
    profile.vertical = data["vertical"]
    profile.objective = data["objective"]
    profile.category = str(data.get("category") or "").strip()
    profile.icp = _dict_or_empty(data.get("icp"))
    profile.geographic_scope = _dict_or_empty(data.get("geographic_scope"))
    profile.competitors = _list_or_empty(data.get("competitors"))
    profile.personas = _dict_or_empty(data.get("personas"))
    profile.crawl_artifacts = _dict_or_empty(data.get("crawl_artifacts"))
    profile.floor_met = context_floor_met(_profile_snapshot(profile))
    profile.updated_at = datetime.now(timezone.utc)
    if not profile.floor_met:
        profile.onboarding_completed_at = None


def _apply_profile_patch_or_raise(profile: BusinessProfile, patch: dict[str, Any]) -> None:
    current = profile_data_from_snapshot(_profile_snapshot(profile))
    try:
        merged = merge_profile_patch(current, patch)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _apply_profile_data(profile, merged)


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list_or_empty(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _client_for_user(db: Session, client_id: str, user_id: str) -> Client:
    client = db.query(Client).filter(Client.id == client_id, Client.user_id == user_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Onboarding profile not found")
    return client


def _profile_for_user(db: Session, onboarding_id: str, user_id: str) -> BusinessProfile:
    client = _client_for_user(db, onboarding_id, user_id)
    profile = db.query(BusinessProfile).filter(BusinessProfile.client_id == client.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Onboarding profile not found")
    return profile


def _profile_draft_response(
    profile: BusinessProfile,
    *,
    prompt_hash: str,
    provider: str,
    model: str,
) -> ProfileDraftResponse:
    base = _profile_response(profile)
    meta = _profile_draft_meta(profile)
    field_sources = _dict_or_empty(meta.get("field_sources"))
    rationale = _dict_or_empty(meta.get("rationale"))
    return ProfileDraftResponse(
        **base.model_dump(),
        field_sources=field_sources,
        field_flags=field_sources,
        rationale={str(key): str(value) for key, value in rationale.items()},
        prompt_version=str(meta.get("prompt_version") or PROFILE_DRAFT_PROMPT_VERSION),
        prompt_hash=prompt_hash,
        provider=provider,
        model=model,
    )


def get_profile_draft_provider() -> LLMProvider:
    return default_profile_draft_provider()


def _load_intake_schema(vertical: str) -> IntakeSchemaResponse:
    try:
        normalized = normalize_vertical(vertical)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Intake schema not found") from exc

    schema_path = SCHEMA_DIR / f"{normalized}.yml"
    if not schema_path.exists():
        raise HTTPException(status_code=404, detail="Intake schema not found")

    with schema_path.open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    if not isinstance(raw, dict):
        raise HTTPException(status_code=500, detail="Invalid intake schema")
    try:
        return IntakeSchemaResponse.model_validate(raw)
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Invalid intake schema") from exc


@router.get("/onboarding/intake-schemas/{vertical}", response_model=IntakeSchemaResponse)
async def get_intake_schema(vertical: str):
    """Return a vertical-conditioned intake schema for the onboarding UI."""
    return _load_intake_schema(vertical)


@router.post(
    "/onboarding/start",
    response_model=OnboardingStartResponse,
    status_code=status.HTTP_201_CREATED,
)
async def start_onboarding(
    payload: OnboardingStartRequest,
    response: Response,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    """Create a client and business-profile shell for the upstream pipeline."""
    name = payload.resolved_name
    if not name:
        raise HTTPException(status_code=422, detail="name or display_name is required")
    if not payload.resolved_url:
        raise HTTPException(status_code=422, detail="url is required")

    try:
        vertical = normalize_vertical(payload.vertical)
        objective = normalize_objective(payload.objective)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    client_id = (payload.client_id or str(uuid.uuid4())).strip()
    client = db.query(Client).filter(Client.id == client_id).first()
    if client and client.user_id != user_id:
        raise HTTPException(status_code=409, detail="Client id already exists")

    now = datetime.now(timezone.utc)
    if client:
        client.name = name
        client.url = payload.resolved_url
        client.updated_at = now
        response.status_code = status.HTTP_200_OK
    else:
        client = Client(
            id=client_id,
            user_id=user_id,
            name=name,
            url=payload.resolved_url,
            created_at=now,
            updated_at=now,
        )
        db.add(client)

    profile = db.query(BusinessProfile).filter(BusinessProfile.client_id == client_id).first()
    if profile:
        profile.vertical = vertical
        profile.objective = objective
        profile.category = payload.category or profile.category or ""
        profile.floor_met = False
        profile.onboarding_completed_at = None
        profile.updated_at = now
    else:
        profile = BusinessProfile(
            client_id=client_id,
            vertical=vertical,
            objective=objective,
            category=payload.category or "",
            icp={},
            geographic_scope={},
            competitors=[],
            personas={},
            crawl_artifacts={},
            floor_met=False,
            created_at=now,
            updated_at=now,
        )
        db.add(profile)

    db.commit()
    db.refresh(client)
    db.refresh(profile)
    profile_response = _profile_response(profile)
    return OnboardingStartResponse(
        **profile_response.model_dump(),
        client_name=client.name,
        client_url=client.url,
    )


@router.patch("/onboarding/{onboarding_id}", response_model=BusinessProfileResponse)
async def patch_onboarding(
    onboarding_id: str,
    payload: OnboardingPatchRequest,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    """Update business-profile fields incrementally during intake."""
    profile = _profile_for_user(db, onboarding_id, user_id)
    patch = payload.model_dump(exclude_unset=True)
    _apply_profile_patch_or_raise(profile, patch)
    db.commit()
    db.refresh(profile)
    return _profile_response(profile)


@router.post("/onboarding/{onboarding_id}/draft-profile", response_model=ProfileDraftResponse)
async def draft_business_profile(
    onboarding_id: str,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
    provider: LLMProvider = Depends(get_profile_draft_provider),
):
    """Generate a customer-confirmable profile draft from crawl artifacts."""
    profile = _profile_for_user(db, onboarding_id, user_id)
    snapshot = _profile_snapshot(profile)
    if not snapshot.crawl_artifacts:
        raise HTTPException(status_code=409, detail="Crawl artifacts are required before profile drafting")

    prompt_text = render_profile_draft_prompt(snapshot)
    provider_name = str(getattr(provider, "provider", "llm"))
    model_name = str(getattr(provider, "model", "unknown"))
    prompt_row = ensure_prompt_version(
        db,
        prompt_key=PROFILE_DRAFT_PROMPT_KEY,
        version=PROFILE_DRAFT_PROMPT_VERSION,
        prompt_text=prompt_text,
        provider=provider_name,
        model=model_name,
    )
    result = generate_profile_draft(
        snapshot,
        provider,
        idempotency_key=f"profile-draft:{profile.client_id}:{prompt_row.prompt_hash}",
    )
    data = dict(result.profile_data)
    artifacts = dict(_dict_or_empty(data.get("crawl_artifacts")))
    artifacts["profile_draft"] = profile_draft_artifact(
        result=result,
        prompt_version_id=prompt_row.id,
    )
    data["crawl_artifacts"] = artifacts
    _apply_profile_data(profile, data)
    db.commit()
    db.refresh(profile)
    return _profile_draft_response(
        profile,
        prompt_hash=prompt_row.prompt_hash,
        provider=result.provider_response.provider,
        model=result.provider_response.model,
    )


@router.post("/onboarding/{onboarding_id}/confirm-profile", response_model=OnboardingSubmitResponse)
async def confirm_business_profile(
    onboarding_id: str,
    payload: ConfirmProfileRequest | None = None,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    """Apply customer edits, validate the floor, and complete onboarding."""
    profile = _profile_for_user(db, onboarding_id, user_id)
    if payload is not None:
        patch = payload.model_dump(exclude_unset=True)
        if patch:
            _apply_profile_patch_or_raise(profile, patch)

    snapshot = _profile_snapshot(profile)
    missing = missing_context_fields(snapshot)
    if missing:
        profile.floor_met = False
        profile.onboarding_completed_at = None
        profile.updated_at = datetime.now(timezone.utc)
        db.commit()
        raise HTTPException(
            status_code=400,
            detail={"error": "ContextFloorNotMet", "missing_fields": missing},
        )

    completed_at = datetime.now(timezone.utc)
    artifacts = dict(_dict_or_empty(profile.crawl_artifacts))
    confirmation = artifacts.get("profile_confirmation") if isinstance(artifacts.get("profile_confirmation"), dict) else {}
    confirmation.update({"confirmed_at": completed_at.isoformat(), "actor": "customer"})
    artifacts["profile_confirmation"] = confirmation
    profile.crawl_artifacts = artifacts
    profile.floor_met = True
    profile.onboarding_completed_at = completed_at
    profile.updated_at = completed_at
    db.commit()
    db.refresh(profile)
    return OnboardingSubmitResponse(
        ok=True,
        onboarding_id=profile.client_id,
        client_id=profile.client_id,
        floor_met=True,
        missing_fields=[],
        onboarding_completed_at=profile.onboarding_completed_at or completed_at,
    )


@router.post("/onboarding/{onboarding_id}/submit", response_model=OnboardingSubmitResponse)
async def submit_onboarding(
    onboarding_id: str,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    """Validate the Minimum Context Floor and complete the intake if it passes."""
    profile = _profile_for_user(db, onboarding_id, user_id)
    snapshot = _profile_snapshot(profile)
    missing = missing_context_fields(snapshot)
    if missing:
        profile.floor_met = False
        profile.onboarding_completed_at = None
        profile.updated_at = datetime.now(timezone.utc)
        db.commit()
        raise HTTPException(
            status_code=400,
            detail={"error": "ContextFloorNotMet", "missing_fields": missing},
        )

    completed_at = datetime.now(timezone.utc)
    profile.floor_met = True
    profile.onboarding_completed_at = completed_at
    profile.updated_at = completed_at
    db.commit()
    db.refresh(profile)
    return OnboardingSubmitResponse(
        ok=True,
        onboarding_id=profile.client_id,
        client_id=profile.client_id,
        floor_met=True,
        missing_fields=[],
        onboarding_completed_at=profile.onboarding_completed_at or completed_at,
    )
