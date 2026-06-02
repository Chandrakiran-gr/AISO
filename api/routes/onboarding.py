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

from api.adapters.scan_executor import default_scan_executor
from api.adapters.profile_draft import default_profile_draft_provider
from api.adapters.question_scorer import default_question_scorer_provider
from api.adapters.question_generation import default_question_generation_provider
from api.adapters.realism_filter import default_realism_filter_provider
from api.adapters.prompt_registry import ensure_prompt_version
from api.auth import get_current_user_id
from api.database import BusinessProfile, Client, get_db
from api.domain.onboarding import (
    VERTICAL_DISPLAY_ORDER,
    context_floor_met,
    merge_profile_patch,
    missing_context_fields,
    normalize_objective,
    normalize_vertical,
    profile_data_from_snapshot,
)
from api.domain.ports import BusinessProfileSnapshot, UpstreamLLMProvider, UpstreamScanExecutor
from api.domain.profile_draft import (
    PROFILE_DRAFT_PROMPT_KEY,
    PROFILE_DRAFT_PROMPT_VERSION,
    generate_profile_draft,
    profile_draft_artifact,
    render_profile_draft_prompt,
)
from api.domain.question_generation import COMPETITOR_BRAND_FRAMES, QUESTION_GENERATION_PROMPT_VERSION
from api.domain.question_scorer import QUESTION_SCORER_PROMPT_VERSION
from api.domain.question_selection import (
    DEFAULT_FRAME_MIN,
    DEFAULT_INTENT_BAND,
    DEFAULT_JOURNEY_MIN,
    DEFAULT_SELECTION_TARGET_N,
)
from api.domain.realism_filter import REALISM_FILTER_PROMPT_VERSION
from api.question_gen.export import (
    QUESTION_CSV_COLUMNS,
    QuestionExportError,
    export_questions_and_enqueue_scan,
)
from api.question_gen.scorer import apply_question_scorer
from api.question_gen.selector import QuestionSelectionError, apply_question_selection
from api.question_gen.realism import apply_realism_filter
from api.question_gen.service import generate_and_persist_question_candidates

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


def _canonical_uuid4(value: Optional[str], *, field_name: str) -> Optional[str]:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    try:
        parsed = uuid.UUID(cleaned, version=4)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"{field_name} must be a UUIDv4") from exc
    if str(parsed) != cleaned.lower():
        raise HTTPException(status_code=422, detail=f"{field_name} must be a canonical UUIDv4")
    return str(parsed)


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


class QuestionGenerationRequest(BaseModel):
    target_n: int = Field(default=50, ge=1)
    scan_run_id: Optional[str] = None


class QuestionGenerationResponse(BaseModel):
    ok: bool
    onboarding_id: str
    client_id: str
    target_n: int
    candidate_count: int
    prompt_version: str
    prompt_hash: str
    prompt_version_id: str
    generator_version: str
    provider: str
    model: str
    distribution: dict[str, int] = Field(default_factory=dict)
    brand_frame_distribution: dict[str, int] = Field(default_factory=dict)


class RealismFilterRequest(BaseModel):
    scan_run_id: Optional[str] = None
    generator_version: Optional[str] = None


class RealismFilterResponse(BaseModel):
    ok: bool
    onboarding_id: str
    client_id: str
    evaluated_count: int
    passed_count: int
    failed_count: int
    threshold: float
    prompt_version: str
    prompt_hash: str
    prompt_version_id: str
    realism_filter_version: str
    provider: str
    model: str


class QuestionScorerRequest(BaseModel):
    scan_run_id: Optional[str] = None
    generator_version: Optional[str] = None
    limit: Optional[int] = Field(default=None, ge=1)


class QuestionScorerResponse(BaseModel):
    ok: bool
    onboarding_id: str
    client_id: str
    evaluated_count: int
    scored_count: int
    human_review_count: int
    human_review_question_ids: list[str] = Field(default_factory=list)
    prompt_version: str
    prompt_hash: str
    prompt_version_id: str
    scorer_version: str
    provider: str
    model: str
    min_gwet_ac2: float
    agreement_threshold: float


class QuestionSelectionRequest(BaseModel):
    target_n: int = Field(default=DEFAULT_SELECTION_TARGET_N, ge=1)
    critical_question_ids: list[str] = Field(default_factory=list, max_length=3)
    journey_min: Optional[dict[str, int]] = None
    frame_min: Optional[dict[str, int]] = None
    intent_band: Optional[dict[str, tuple[float, float]]] = None
    personas: Optional[list[str]] = None
    scan_run_id: Optional[str] = None
    generator_version: Optional[str] = None
    selection_mode: Optional[str] = Field(default="default")
    lambda_mmr: Optional[float] = Field(default=None, ge=0)


class QuestionSelectionResponse(BaseModel):
    ok: bool
    onboarding_id: str
    client_id: str
    target_n: int
    objective: Optional[str] = None
    objective_journey_targets: dict[str, int] = Field(default_factory=dict)
    selected_count: int
    selected_question_ids: list[str]
    solver_status: str
    solver_seconds: float
    objective_value: float
    mmr_lambda: float
    high_similarity_pair_count: int
    journey_distribution: dict[str, int] = Field(default_factory=dict)
    frame_distribution: dict[str, int] = Field(default_factory=dict)
    intent_distribution: dict[str, int] = Field(default_factory=dict)
    persona_distribution: dict[str, int] = Field(default_factory=dict)
    journey_min: dict[str, int] = Field(default_factory=lambda: dict(DEFAULT_JOURNEY_MIN))
    frame_min: dict[str, int] = Field(default_factory=lambda: dict(DEFAULT_FRAME_MIN))
    intent_band: dict[str, tuple[float, float]] = Field(default_factory=lambda: dict(DEFAULT_INTENT_BAND))
    scan_id: str
    scan_status: str
    question_csv_artifact_id: str
    question_csv_storage_backend: str
    question_csv_storage_path: str
    question_csv_filename: str
    question_csv_columns: list[str] = Field(default_factory=lambda: list(QUESTION_CSV_COLUMNS))
    enqueue_enqueued: bool
    enqueue_provider: str
    enqueue_job_id: Optional[str] = None
    enqueue_error: Optional[str] = None


class IntakeFieldResponse(BaseModel):
    id: str
    label: str
    type: str
    required: bool = False
    hint: Optional[str] = None
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


class IntakeVerticalResponse(BaseModel):
    id: str
    label: str
    description: str = ""
    example: Optional[str] = None


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


def _persona_constraints(snapshot: BusinessProfileSnapshot) -> list[str]:
    personas: list[str] = []

    def collect(value: Any) -> None:
        if isinstance(value, str) and value.strip():
            personas.append(value.strip())
        elif isinstance(value, list):
            for item in value:
                collect(item)
        elif isinstance(value, dict):
            for item in value.values():
                collect(item)

    collect(snapshot.personas)
    return list(dict.fromkeys(personas))


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


def get_profile_draft_provider() -> UpstreamLLMProvider:
    return default_profile_draft_provider()


def get_scan_executor() -> UpstreamScanExecutor:
    return default_scan_executor()


def get_question_scorer_provider() -> UpstreamLLMProvider:
    return default_question_scorer_provider()


def get_question_generation_provider() -> UpstreamLLMProvider:
    return default_question_generation_provider()


def get_realism_filter_provider() -> UpstreamLLMProvider:
    return default_realism_filter_provider()


def _load_intake_schema(vertical: str) -> IntakeSchemaResponse:
    raw = _read_intake_schema(vertical)
    try:
        return IntakeSchemaResponse.model_validate(raw)
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Invalid intake schema") from exc


def _read_intake_schema(vertical: str) -> dict[str, Any]:
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
    return raw


@router.get("/onboarding/intake-verticals", response_model=list[IntakeVerticalResponse])
async def list_intake_verticals():
    """Return schema-backed business types for the onboarding UI."""
    verticals: list[IntakeVerticalResponse] = []
    for vertical in VERTICAL_DISPLAY_ORDER:
        raw = _read_intake_schema(vertical)
        try:
            schema = IntakeSchemaResponse.model_validate(raw)
        except Exception as exc:
            raise HTTPException(status_code=500, detail="Invalid intake schema") from exc
        example = raw.get("example")
        verticals.append(
            IntakeVerticalResponse(
                id=schema.vertical,
                label=schema.label,
                description=schema.description,
                example=example if isinstance(example, str) else None,
            )
        )
    return verticals


@router.get("/onboarding/intake-schemas/{vertical}", response_model=IntakeSchemaResponse)
async def get_intake_schema(vertical: str):
    """Return a vertical-conditioned intake schema for the onboarding UI."""
    return _load_intake_schema(vertical)


@router.get("/onboarding/{onboarding_id}", response_model=BusinessProfileResponse)
async def get_onboarding_profile(
    onboarding_id: str,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    """Return the saved onboarding profile for repeat scans and review flows."""
    profile = _profile_for_user(db, onboarding_id, user_id)
    return _profile_response(profile)


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

    client_id = _canonical_uuid4(payload.client_id, field_name="client_id") or str(uuid.uuid4())
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
        db.flush()

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
    provider: UpstreamLLMProvider = Depends(get_profile_draft_provider),
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


@router.post("/onboarding/{onboarding_id}/generate-questions", response_model=QuestionGenerationResponse)
async def generate_onboarding_questions(
    onboarding_id: str,
    payload: QuestionGenerationRequest | None = None,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
    provider: UpstreamLLMProvider = Depends(get_question_generation_provider),
):
    """Generate and persist the 3x candidate pool after profile confirmation."""
    payload = payload or QuestionGenerationRequest()
    client = _client_for_user(db, onboarding_id, user_id)
    profile = db.query(BusinessProfile).filter(BusinessProfile.client_id == client.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Onboarding profile not found")

    snapshot = _profile_snapshot(profile)
    missing = missing_context_fields(snapshot)
    if missing or not snapshot.floor_met or not snapshot.onboarding_completed_at:
        raise HTTPException(
            status_code=409,
            detail={"error": "ProfileNotConfirmed", "missing_fields": missing},
        )

    try:
        run = generate_and_persist_question_candidates(
            db,
            client=client,
            snapshot=snapshot,
            provider=provider,
            target_n=payload.target_n,
            scan_run_id=payload.scan_run_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    db.commit()
    return QuestionGenerationResponse(
        ok=True,
        onboarding_id=profile.client_id,
        client_id=profile.client_id,
        target_n=payload.target_n,
        candidate_count=len(run.candidates),
        prompt_version=QUESTION_GENERATION_PROMPT_VERSION,
        prompt_hash=run.prompt_hash,
        prompt_version_id=run.prompt_version_id,
        generator_version=run.generator_version,
        provider=run.provider,
        model=run.model,
        distribution=run.distribution,
        brand_frame_distribution=run.brand_frame_distribution,
    )


@router.post("/onboarding/{onboarding_id}/score-questions", response_model=QuestionScorerResponse)
async def score_onboarding_questions(
    onboarding_id: str,
    payload: QuestionScorerRequest | None = None,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
    provider: UpstreamLLMProvider = Depends(get_question_scorer_provider),
):
    """Run the v1 five-dimension scorer over realism-passing candidates."""
    payload = payload or QuestionScorerRequest()
    profile = _profile_for_user(db, onboarding_id, user_id)
    run = apply_question_scorer(
        db,
        client_id=profile.client_id,
        snapshot=_profile_snapshot(profile),
        provider=provider,
        scan_run_id=payload.scan_run_id,
        generator_version=payload.generator_version,
        limit=payload.limit,
    )
    if run.evaluated_count == 0:
        raise HTTPException(status_code=409, detail="No question candidates available for scoring")

    db.commit()
    return QuestionScorerResponse(
        ok=True,
        onboarding_id=profile.client_id,
        client_id=profile.client_id,
        evaluated_count=run.evaluated_count,
        scored_count=run.scored_count,
        human_review_count=run.human_review_count,
        human_review_question_ids=run.human_review_question_ids,
        prompt_version=QUESTION_SCORER_PROMPT_VERSION,
        prompt_hash=run.prompt_hash,
        prompt_version_id=run.prompt_version_id,
        scorer_version=run.scorer_version,
        provider=run.provider,
        model=run.model,
        min_gwet_ac2=run.min_gwet_ac2,
        agreement_threshold=run.agreement_threshold,
    )


@router.post("/onboarding/{onboarding_id}/select-questions", response_model=QuestionSelectionResponse)
async def select_onboarding_questions(
    onboarding_id: str,
    payload: QuestionSelectionRequest | None = None,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
    executor: UpstreamScanExecutor = Depends(get_scan_executor),
):
    """Select the final question portfolio from scored candidates using the Phase 12 MIP."""
    payload = payload or QuestionSelectionRequest()
    profile = _profile_for_user(db, onboarding_id, user_id)
    snapshot = _profile_snapshot(profile)
    personas = payload.personas if payload.personas is not None else _persona_constraints(snapshot)
    has_competitors = bool(snapshot.competitors)
    frame_min = payload.frame_min or dict(DEFAULT_FRAME_MIN)
    if not has_competitors:
        frame_min = {
            frame: minimum
            for frame, minimum in frame_min.items()
            if frame not in COMPETITOR_BRAND_FRAMES
        }
    try:
        run = apply_question_selection(
            db,
            client_id=profile.client_id,
            target_n=payload.target_n,
            critical_question_ids=payload.critical_question_ids,
            journey_min=payload.journey_min,
            frame_min=frame_min,
            intent_band=payload.intent_band,
            personas=personas,
            scan_run_id=payload.scan_run_id,
            generator_version=payload.generator_version,
            objective=snapshot.objective,
            selection_mode=payload.selection_mode,
            lambda_mmr=payload.lambda_mmr,
            has_competitors=has_competitors,
        )
        export = export_questions_and_enqueue_scan(
            db,
            client_id=profile.client_id,
            executor=executor,
            target_n=payload.target_n,
            scan_run_id=payload.scan_run_id,
        )
    except QuestionSelectionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except QuestionExportError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    db.commit()
    return QuestionSelectionResponse(
        ok=True,
        onboarding_id=profile.client_id,
        client_id=profile.client_id,
        target_n=run.target_n,
        objective=run.objective,
        objective_journey_targets=run.objective_stage_targets,
        selected_count=len(run.selected_ids),
        selected_question_ids=run.selected_ids,
        solver_status=run.solver_status,
        solver_seconds=run.solver_seconds,
        objective_value=run.objective_value,
        mmr_lambda=run.mmr_lambda,
        high_similarity_pair_count=run.high_similarity_pair_count,
        journey_distribution=run.journey_distribution,
        frame_distribution=run.frame_distribution,
        intent_distribution=run.intent_distribution,
        persona_distribution=run.persona_distribution,
        journey_min=payload.journey_min or dict(DEFAULT_JOURNEY_MIN),
        frame_min=frame_min,
        intent_band=payload.intent_band or dict(DEFAULT_INTENT_BAND),
        scan_id=export.scan_id,
        scan_status=export.scan_status,
        question_csv_artifact_id=export.artifact_id,
        question_csv_storage_backend=export.artifact_storage_backend,
        question_csv_storage_path=export.artifact_storage_path,
        question_csv_filename=export.artifact_original_filename,
        question_csv_columns=list(QUESTION_CSV_COLUMNS),
        enqueue_enqueued=export.enqueue_result.enqueued,
        enqueue_provider=export.enqueue_result.provider,
        enqueue_job_id=export.enqueue_result.job_id,
        enqueue_error=export.enqueue_result.error,
    )


@router.post("/onboarding/{onboarding_id}/filter-realism", response_model=RealismFilterResponse)
async def filter_onboarding_question_realism(
    onboarding_id: str,
    payload: RealismFilterRequest | None = None,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
    provider: UpstreamLLMProvider = Depends(get_realism_filter_provider),
):
    """Run the v1 realism filter over persisted question candidates."""
    payload = payload or RealismFilterRequest()
    profile = _profile_for_user(db, onboarding_id, user_id)
    run = apply_realism_filter(
        db,
        client_id=profile.client_id,
        vertical=profile.vertical,
        provider=provider,
        scan_run_id=payload.scan_run_id,
        generator_version=payload.generator_version,
    )
    if run.evaluated_count == 0:
        raise HTTPException(status_code=409, detail="No question candidates available for realism filtering")

    db.commit()
    return RealismFilterResponse(
        ok=True,
        onboarding_id=profile.client_id,
        client_id=profile.client_id,
        evaluated_count=run.evaluated_count,
        passed_count=run.passed_count,
        failed_count=run.failed_count,
        threshold=run.threshold,
        prompt_version=REALISM_FILTER_PROMPT_VERSION,
        prompt_hash=run.prompt_hash,
        prompt_version_id=run.prompt_version_id,
        realism_filter_version=run.realism_filter_version,
        provider=run.provider,
        model=run.model,
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
