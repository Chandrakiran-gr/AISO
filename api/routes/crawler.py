"""API routes for the onboarding crawler.

Endpoints:
    POST /v1/onboarding-workspaces
    POST /v1/onboarding-workspaces/{workspace_id}/crawl-jobs
    GET  /v1/crawl-jobs/{job_id}
    GET  /v1/crawl-jobs/{job_id}/pages
    GET  /v1/crawl-jobs/{job_id}/business-profile
    GET  /v1/crawl-jobs/{job_id}/evidence
    GET  /v1/onboarding-workspaces/{workspace_id}/review
    PATCH /v1/onboarding-workspaces/{workspace_id}/business-profile
    POST /v1/onboarding-workspaces/{workspace_id}/approve
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.auth import get_current_user_id
from api.crawler.consent import validate_crawl_request
from api.crawler.models import (
    CrawlBusinessProfile,
    CrawlJob,
    CrawlPage,
    ExtractionEvidence,
    OnboardingWorkspace,
)
from api.crawler.worker import run_crawl_job
from api.database import Client, ClientContext, get_db

router = APIRouter(tags=["onboarding-crawler"])

# ── Pydantic Schemas ─────────────────────────────────────────────────────────

VALID_CRAWL_MODES = {"homepage_preview", "standard", "selected_urls"}


class CreateWorkspaceRequest(BaseModel):
    client_id: str
    website_url: str
    consent_confirmed: bool = False


class WorkspaceResponse(BaseModel):
    workspace_id: str
    client_id: str
    status: str
    website_url: str
    normalized_domain: str
    allowed_domains: list[str]
    consent_confirmed: bool


class CreateCrawlJobRequest(BaseModel):
    crawl_mode: str = "standard"
    max_pages: int = Field(default=100, ge=1, le=1000)
    max_depth: int = Field(default=3, ge=0, le=10)


class CrawlJobResponse(BaseModel):
    job_id: str
    workspace_id: str
    status: str
    crawl_mode: str
    max_pages: int
    max_depth: int
    pages_discovered: int
    pages_crawled: int
    pages_skipped: int
    pages_failed: int
    warnings: list[str]
    error_message: Optional[str]
    started_at: Optional[str]
    completed_at: Optional[str]
    created_at: str


class CrawlPageResponse(BaseModel):
    url: str
    title: Optional[str]
    page_type: Optional[str]
    status: str
    status_code: Optional[int]
    content_hash: Optional[str]
    crawled_at: Optional[str]


class EvidenceResponse(BaseModel):
    field_name: str
    field_value: Optional[str]
    source_url: str
    source_text: Optional[str]
    extraction_method: str
    confidence: Optional[float]


class EditProfileRequest(BaseModel):
    company_name: Optional[str] = None
    description: Optional[str] = None
    industry: Optional[str] = None
    products: Optional[list[str]] = None
    services: Optional[list[str]] = None
    locations: Optional[list[str]] = None
    contacts: Optional[dict[str, Any]] = None
    social_links: Optional[list[str]] = None


# ── Helpers ──────────────────────────────────────────────────────────────────

def _safe_json_loads(value: str | None, fallback: Any = None) -> Any:
    if not value:
        return fallback if fallback is not None else []
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return fallback if fallback is not None else []


def _serialize_job(job: CrawlJob) -> CrawlJobResponse:
    return CrawlJobResponse(
        job_id=job.id,
        workspace_id=job.workspace_id,
        status=job.status,
        crawl_mode=job.crawl_mode,
        max_pages=job.max_pages,
        max_depth=job.max_depth,
        pages_discovered=job.pages_discovered,
        pages_crawled=job.pages_crawled,
        pages_skipped=job.pages_skipped,
        pages_failed=job.pages_failed,
        warnings=_safe_json_loads(job.warnings, []),
        error_message=job.error_message,
        started_at=job.started_at.isoformat() if job.started_at else None,
        completed_at=job.completed_at.isoformat() if job.completed_at else None,
        created_at=job.created_at.isoformat(),
    )


def _ensure_client(db: Session, client_id: str, user_id: str) -> Client:
    """Verify the client exists and belongs to the authenticated user."""
    client = db.query(Client).filter(
        Client.id == client_id,
        Client.user_id == user_id,
    ).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.post(
    "/onboarding-workspaces",
    response_model=WorkspaceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_workspace(
    payload: CreateWorkspaceRequest,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    """Create an onboarding workspace for a client website.

    Requires consent confirmation and a valid public URL.
    """
    # Verify client ownership.
    _ensure_client(db, payload.client_id, user_id)

    # Validate consent + URL safety.
    try:
        validated = validate_crawl_request(
            payload.website_url,
            payload.consent_confirmed,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    workspace_id = str(uuid.uuid4())
    workspace = OnboardingWorkspace(
        id=workspace_id,
        client_id=payload.client_id,
        website_url=validated["safe_url"],
        normalized_domain=validated["normalized_domain"],
        allowed_domains=json.dumps(validated["allowed_domains"], ensure_ascii=False),
        consent_confirmed=True,
        status="created",
    )
    db.add(workspace)
    db.commit()
    db.refresh(workspace)

    return WorkspaceResponse(
        workspace_id=workspace.id,
        client_id=workspace.client_id,
        status=workspace.status,
        website_url=workspace.website_url,
        normalized_domain=workspace.normalized_domain,
        allowed_domains=_safe_json_loads(workspace.allowed_domains, []),
        consent_confirmed=workspace.consent_confirmed,
    )


@router.post(
    "/onboarding-workspaces/{workspace_id}/crawl-jobs",
    response_model=CrawlJobResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_crawl_job(
    workspace_id: str,
    payload: CreateCrawlJobRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    """Start a crawl job within an onboarding workspace."""
    workspace = db.query(OnboardingWorkspace).filter(
        OnboardingWorkspace.id == workspace_id,
    ).first()
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    # Verify ownership via client.
    _ensure_client(db, workspace.client_id, user_id)

    if payload.crawl_mode not in VALID_CRAWL_MODES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid crawl_mode. Must be one of: {', '.join(sorted(VALID_CRAWL_MODES))}",
        )

    job_id = str(uuid.uuid4())
    job = CrawlJob(
        id=job_id,
        workspace_id=workspace_id,
        status="queued",
        crawl_mode=payload.crawl_mode,
        max_pages=payload.max_pages,
        max_depth=payload.max_depth,
    )
    db.add(job)

    # Mark workspace as active.
    workspace.status = "active"
    db.commit()
    db.refresh(job)

    # Enqueue crawl execution in the background. Tests can disable the worker
    # so endpoint-shape assertions stay deterministic and network-free.
    if os.getenv("AISO_CRAWLER_DISABLE_WORKER", "0") != "1":
        background_tasks.add_task(run_crawl_job, job_id)

    return _serialize_job(job)


@router.get("/crawl-jobs/{job_id}", response_model=CrawlJobResponse)
async def get_crawl_job(
    job_id: str,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    """Return the current status and counters for a crawl job."""
    job = db.query(CrawlJob).filter(CrawlJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Crawl job not found")

    # Verify ownership via workspace → client.
    workspace = db.query(OnboardingWorkspace).filter(
        OnboardingWorkspace.id == job.workspace_id,
    ).first()
    if workspace:
        _ensure_client(db, workspace.client_id, user_id)

    return _serialize_job(job)


@router.get("/crawl-jobs/{job_id}/pages")
async def list_crawl_pages(
    job_id: str,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    """List pages discovered/crawled in a job.

    Returns actual page records when available (Phase 2+), or an empty
    list for Phase 1 stub jobs.
    """
    job = db.query(CrawlJob).filter(CrawlJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Crawl job not found")

    workspace = db.query(OnboardingWorkspace).filter(
        OnboardingWorkspace.id == job.workspace_id,
    ).first()
    if workspace:
        _ensure_client(db, workspace.client_id, user_id)

    pages = db.query(CrawlPage).filter(CrawlPage.job_id == job_id).all()
    return {
        "pages": [
            CrawlPageResponse(
                url=page.url,
                title=page.title,
                page_type=page.page_type,
                status=page.status,
                status_code=page.status_code,
                content_hash=page.content_hash,
                crawled_at=page.fetched_at.isoformat() if page.fetched_at else None,
            ).model_dump()
            for page in pages
        ]
    }


@router.get("/crawl-jobs/{job_id}/business-profile")
async def get_business_profile(
    job_id: str,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    """Return the aggregated business profile for a crawl job.

    Returns the profile when available (Phase 2+), or null for
    Phase 1 stub jobs.
    """
    job = db.query(CrawlJob).filter(CrawlJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Crawl job not found")

    workspace = db.query(OnboardingWorkspace).filter(
        OnboardingWorkspace.id == job.workspace_id,
    ).first()
    if workspace:
        _ensure_client(db, workspace.client_id, user_id)

    profile = db.query(CrawlBusinessProfile).filter(
        CrawlBusinessProfile.job_id == job_id,
    ).first()

    if not profile:
        return {"profile": None}

    return {
        "profile": {
            "company_name": profile.company_name,
            "description": profile.description,
            "website": profile.website,
            "industry": profile.industry,
            "products": _safe_json_loads(profile.products, []),
            "services": _safe_json_loads(profile.services, []),
            "locations": _safe_json_loads(profile.locations, []),
            "contacts": _safe_json_loads(profile.contacts, {}),
            "social_links": _safe_json_loads(profile.social_links, []),
            "important_pages": _safe_json_loads(profile.important_pages, []),
            "missing_fields": _safe_json_loads(profile.missing_fields, []),
            "confidence_score": profile.confidence_score,
        }
    }


@router.get("/crawl-jobs/{job_id}/evidence")
async def list_evidence(
    job_id: str,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    """List extraction evidence for a crawl job.

    Returns actual evidence records when available (Phase 2+), or an
    empty list for Phase 1 stub jobs.
    """
    job = db.query(CrawlJob).filter(CrawlJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Crawl job not found")

    workspace = db.query(OnboardingWorkspace).filter(
        OnboardingWorkspace.id == job.workspace_id,
    ).first()
    if workspace:
        _ensure_client(db, workspace.client_id, user_id)

    evidence = db.query(ExtractionEvidence).filter(
        ExtractionEvidence.job_id == job_id,
    ).all()
    return {
        "evidence": [
            EvidenceResponse(
                field_name=item.field_name,
                field_value=item.field_value,
                source_url=item.source_url,
                source_text=item.source_text,
                extraction_method=item.extraction_method,
                confidence=item.confidence_score,
            ).model_dump()
            for item in evidence
        ]
    }


def _serialize_profile(profile: CrawlBusinessProfile) -> dict[str, Any]:
    """Serialize a business profile to a dict."""
    return {
        "profile_id": profile.id,
        "company_name": profile.company_name,
        "description": profile.description,
        "website": profile.website,
        "domain": profile.domain,
        "industry": profile.industry,
        "products": _safe_json_loads(profile.products, []),
        "services": _safe_json_loads(profile.services, []),
        "locations": _safe_json_loads(profile.locations, []),
        "contacts": _safe_json_loads(profile.contacts, {}),
        "social_links": _safe_json_loads(profile.social_links, []),
        "important_pages": _safe_json_loads(profile.important_pages, []),
        "missing_fields": _safe_json_loads(profile.missing_fields, []),
        "confidence_score": profile.confidence_score,
        "profile_status": profile.profile_status,
        "approved_at": profile.approved_at.isoformat() if profile.approved_at else None,
    }


def _get_workspace_with_auth(
    workspace_id: str, db: Session, user_id: str,
) -> OnboardingWorkspace:
    """Fetch a workspace and verify ownership via client."""
    workspace = db.query(OnboardingWorkspace).filter(
        OnboardingWorkspace.id == workspace_id,
    ).first()
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    _ensure_client(db, workspace.client_id, user_id)
    return workspace


def _latest_job_for_workspace(db: Session, workspace_id: str) -> CrawlJob | None:
    return db.query(CrawlJob).filter(
        CrawlJob.workspace_id == workspace_id,
    ).order_by(CrawlJob.created_at.desc()).first()


def _latest_profile_for_workspace(db: Session, workspace_id: str) -> CrawlBusinessProfile | None:
    job = _latest_job_for_workspace(db, workspace_id)
    if job:
        profile = db.query(CrawlBusinessProfile).filter(
            CrawlBusinessProfile.job_id == job.id,
        ).order_by(CrawlBusinessProfile.created_at.desc()).first()
        if profile:
            return profile
    return db.query(CrawlBusinessProfile).filter(
        CrawlBusinessProfile.workspace_id == workspace_id,
    ).order_by(CrawlBusinessProfile.created_at.desc()).first()


def _first_location_name(raw_locations: str | None) -> str | None:
    locations = _safe_json_loads(raw_locations, [])
    if not isinstance(locations, list):
        return None
    for location in locations:
        if isinstance(location, str) and location.strip():
            return location.strip()
        if isinstance(location, dict) and str(location.get("name") or "").strip():
            return str(location["name"]).strip()
    return None


def _profile_items_from_names(
    names: list[Any],
    *,
    item_type: str,
    source_url: str | None,
    confidence: float,
    extra: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_name in names:
        name = raw_name.get("name") if isinstance(raw_name, dict) else raw_name
        name = str(name or "").strip()
        if not name:
            continue
        dedupe_key = name.casefold()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        item = {
            "name": name,
            "type": item_type,
            "confidence": confidence,
            "source_url": source_url,
        }
        if extra:
            item.update(extra)
        items.append(item)
    return items


def _sync_client_context_from_profile(
    db: Session,
    *,
    client: Client,
    profile: CrawlBusinessProfile,
    status_value: str,
    warnings: list[str] | None = None,
) -> None:
    """Keep the existing client-context flow aligned with approved crawler data."""
    now = datetime.now(timezone.utc)
    context = db.query(ClientContext).filter(ClientContext.client_id == client.id).first()
    if not context:
        context = ClientContext(client_id=client.id, created_at=now)
        db.add(context)

    existing_profile = _safe_json_loads(context.profile_json, {})
    if not isinstance(existing_profile, dict):
        existing_profile = {}

    business = existing_profile.get("business")
    if not isinstance(business, dict):
        business = {}
    business.update(
        {
            "name": profile.company_name or client.name,
            "website_url": profile.website or client.url,
            "source_url": profile.website or client.url,
            "confidence": profile.confidence_score or business.get("confidence") or 0.72,
        }
    )
    existing_profile["business"] = business

    source_url = profile.website or client.url
    confidence = profile.confidence_score or 0.72

    if profile.industry:
        existing_profile["categories"] = [
            {
                "name": profile.industry,
                "type": "category",
                "confidence": confidence,
                "source_url": source_url,
            }
        ]

    services = _safe_json_loads(profile.services, [])
    if isinstance(services, list):
        service_items = _profile_items_from_names(
            services,
            item_type="offering",
            source_url=source_url,
            confidence=confidence,
            extra={"bookable": True},
        )
        if service_items:
            existing_profile["offerings"] = service_items

    products = _safe_json_loads(profile.products, [])
    if isinstance(products, list):
        product_items = _profile_items_from_names(
            products,
            item_type="product_brand",
            source_url=source_url,
            confidence=confidence,
        )
        if product_items:
            existing_profile["product_brands"] = product_items

    locations = _safe_json_loads(profile.locations, [])
    if isinstance(locations, list):
        location_items = _profile_items_from_names(
            locations,
            item_type="physical_location",
            source_url=source_url,
            confidence=confidence,
        )
        if location_items:
            profile_locations = existing_profile.get("locations")
            if not isinstance(profile_locations, dict):
                profile_locations = {}
            profile_locations["physical_locations"] = location_items
            existing_profile["locations"] = profile_locations

    context.status = status_value
    context.profile_json = json.dumps(existing_profile, ensure_ascii=False)
    context.warnings_json = json.dumps(warnings or _safe_json_loads(profile.missing_fields, []), ensure_ascii=False)
    context.updated_at = now


# ── Review & Approval Endpoints ──────────────────────────────────────────────


@router.get("/onboarding-workspaces/{workspace_id}/review")
async def get_review_bundle(
    workspace_id: str,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    """Return the full review bundle for the frontend review screen.

    Includes workspace status, draft business profile, evidence,
    discovered pages, and the client slug (Client.id).
    """
    workspace = _get_workspace_with_auth(workspace_id, db, user_id)

    # Find the latest crawl job for this workspace.
    job = _latest_job_for_workspace(db, workspace_id)

    # Profile.
    profile = None
    profile_data = None
    if job:
        profile = db.query(CrawlBusinessProfile).filter(
            CrawlBusinessProfile.job_id == job.id,
        ).first()
        if profile:
            profile_data = _serialize_profile(profile)

    # Pages.
    pages = []
    if job:
        page_rows = db.query(CrawlPage).filter(CrawlPage.job_id == job.id).all()
        pages = [
            {
                "url": p.url,
                "title": p.title,
                "page_type": p.page_type,
                "status": p.status,
            }
            for p in page_rows
        ]

    # Evidence.
    evidence = []
    if job:
        ev_rows = db.query(ExtractionEvidence).filter(
            ExtractionEvidence.job_id == job.id,
        ).all()
        evidence = [
            {
                "field_name": e.field_name,
                "field_value": e.field_value,
                "source_url": e.source_url,
                "extraction_method": e.extraction_method,
                "confidence": e.confidence_score,
            }
            for e in ev_rows
        ]

    # Client slug.
    client = db.query(Client).filter(Client.id == workspace.client_id).first()

    return {
        "workspace_id": workspace.id,
        "workspace_status": workspace.status,
        "client_slug": client.id if client else None,
        "client_name": client.name if client else None,
        "profile": profile_data,
        "pages": pages,
        "evidence": evidence,
        "job": _serialize_job(job).model_dump() if job else None,
    }


@router.patch("/onboarding-workspaces/{workspace_id}/business-profile")
async def edit_business_profile(
    workspace_id: str,
    payload: EditProfileRequest,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    """Edit the draft business profile.

    Only allowed while profile_status == 'draft_extracted'.
    """
    workspace = _get_workspace_with_auth(workspace_id, db, user_id)

    # Find the latest profile.
    profile = _latest_profile_for_workspace(db, workspace_id)

    if not profile:
        raise HTTPException(status_code=404, detail="No business profile found for this workspace")

    if profile.profile_status != "draft_extracted":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Profile is '{profile.profile_status}' and cannot be edited. Only draft profiles can be modified.",
        )

    # Apply edits — only update fields that were provided.
    if payload.company_name is not None:
        profile.company_name = payload.company_name
    if payload.description is not None:
        profile.description = payload.description
    if payload.industry is not None:
        profile.industry = payload.industry
    if payload.products is not None:
        profile.products = json.dumps(payload.products, ensure_ascii=False)
    if payload.services is not None:
        profile.services = json.dumps(payload.services, ensure_ascii=False)
    if payload.locations is not None:
        profile.locations = json.dumps(payload.locations, ensure_ascii=False)
    if payload.contacts is not None:
        profile.contacts = json.dumps(payload.contacts, ensure_ascii=False)
    if payload.social_links is not None:
        profile.social_links = json.dumps(payload.social_links, ensure_ascii=False)

    profile.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(profile)

    return {"profile": _serialize_profile(profile)}


@router.post("/onboarding-workspaces/{workspace_id}/approve")
async def approve_business_profile(
    workspace_id: str,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    """Approve the extracted business profile.

    Validates required fields, locks the profile, enriches the Client
    record, and marks the workspace as pipeline_ready.
    """
    workspace = _get_workspace_with_auth(workspace_id, db, user_id)

    # Find the latest profile.
    profile = _latest_profile_for_workspace(db, workspace_id)

    if not profile:
        raise HTTPException(status_code=404, detail="No business profile found for this workspace")

    if profile.profile_status != "draft_extracted":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Profile is already '{profile.profile_status}'. Only draft profiles can be approved.",
        )

    # Validate required fields.
    if not (profile.company_name or "").strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="company_name is required before approval.",
        )
    if not (profile.website or "").strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="website is required before approval.",
        )

    # Lock the profile.
    now = datetime.now(timezone.utc)
    profile.profile_status = "approved"
    profile.approved_at = now
    profile.approved_by_user_id = user_id
    profile.updated_at = now

    # Enrich the Client record with approved data.
    client = db.query(Client).filter(Client.id == workspace.client_id).first()
    if client:
        if profile.company_name:
            client.name = profile.company_name
        if profile.industry:
            client.industry = profile.industry
        location_name = _first_location_name(profile.locations)
        if location_name:
            client.location = location_name
        client.updated_at = now
        _sync_client_context_from_profile(
            db,
            client=client,
            profile=profile,
            status_value="confirmed",
        )

    # Mark workspace as pipeline_ready.
    workspace.status = "pipeline_ready"
    workspace.updated_at = now

    db.commit()
    db.refresh(profile)

    return {
        "profile": _serialize_profile(profile),
        "workspace_status": workspace.status,
        "client_slug": client.id if client else None,
    }
