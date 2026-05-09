"""API routes for the onboarding crawler.

Endpoints:
    POST /v1/onboarding-workspaces
    POST /v1/onboarding-workspaces/{workspace_id}/crawl-jobs
    GET  /v1/crawl-jobs/{job_id}
    GET  /v1/crawl-jobs/{job_id}/pages
    GET  /v1/crawl-jobs/{job_id}/business-profile
    GET  /v1/crawl-jobs/{job_id}/evidence
"""

from __future__ import annotations

import json
import uuid
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
    KBChunk,
    OnboardingWorkspace,
)
from api.crawler.worker import run_crawl_job
from api.database import Client, get_db

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

    # Enqueue crawl execution in the background.
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
