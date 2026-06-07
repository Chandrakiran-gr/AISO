"""SQLAlchemy models for the onboarding crawler.

All models share ``Base`` from ``api.database`` so that Alembic and
``init_db()`` discover them automatically.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)

from api.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Onboarding Workspace ────────────────────────────────────────────────────

class OnboardingWorkspace(Base):
    """One workspace per client/website pair.

    Wraps crawl jobs, profile, KB chunks, and evidence for a single
    client-authorized website.
    """
    __tablename__ = "onboarding_workspaces"
    __table_args__ = (
        Index("ix_onboarding_workspaces_client", "client_id"),
        Index("ix_onboarding_workspaces_domain", "normalized_domain"),
    )

    id                = Column(String, primary_key=True)
    client_id         = Column(String, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    website_url       = Column(Text, nullable=False)
    normalized_domain = Column(String, nullable=False)
    allowed_domains   = Column(Text, nullable=False)       # JSON array
    consent_confirmed = Column(Boolean, nullable=False, default=False)
    status            = Column(String, nullable=False, default="created")  # created | active | archived
    created_at        = Column(DateTime, nullable=False, default=_utcnow)
    updated_at        = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)


# ── Crawl Job ────────────────────────────────────────────────────────────────

class CrawlJob(Base):
    """A single crawl execution within an onboarding workspace.

    Statuses: queued | running | completed | completed_with_warnings | failed | cancelled
    """
    __tablename__ = "crawl_jobs"
    __table_args__ = (
        Index("ix_crawl_jobs_workspace", "workspace_id"),
        Index("ix_crawl_jobs_status", "status"),
    )

    id                       = Column(String, primary_key=True)
    workspace_id             = Column(String, ForeignKey("onboarding_workspaces.id", ondelete="CASCADE"), nullable=False)
    status                   = Column(String, nullable=False, default="queued")
    crawl_mode               = Column(String, nullable=False, default="standard")  # homepage_preview | standard | selected_urls
    max_pages                = Column(Integer, nullable=False, default=100)
    max_depth                = Column(Integer, nullable=False, default=3)
    allow_playwright_fallback = Column(Boolean, nullable=False, default=True)
    pages_discovered         = Column(Integer, nullable=False, default=0)
    pages_queued             = Column(Integer, nullable=False, default=0)
    pages_crawled            = Column(Integer, nullable=False, default=0)
    pages_skipped            = Column(Integer, nullable=False, default=0)
    pages_failed             = Column(Integer, nullable=False, default=0)
    warnings                 = Column(Text, nullable=True)        # JSON array
    error_message            = Column(Text, nullable=True)
    started_at               = Column(DateTime, nullable=True)
    completed_at             = Column(DateTime, nullable=True)
    created_at               = Column(DateTime, nullable=False, default=_utcnow)
    updated_at               = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)


# ── Crawl Page ───────────────────────────────────────────────────────────────

class CrawlPage(Base):
    """One crawled (or discovered) page within a crawl job.

    Page statuses: queued | fetching | fetched | parsed | skipped | blocked | failed | not_modified
    """
    __tablename__ = "crawl_pages"
    __table_args__ = (
        Index("ix_crawl_pages_job", "job_id"),
        Index("uq_crawl_pages_job_url", "job_id", "normalized_url", unique=True),
    )

    id                 = Column(String, primary_key=True)
    job_id             = Column(String, ForeignKey("crawl_jobs.id", ondelete="CASCADE"), nullable=False)
    url                = Column(Text, nullable=False)
    normalized_url     = Column(Text, nullable=False)
    final_url          = Column(Text, nullable=True)
    domain             = Column(String, nullable=False)
    title              = Column(Text, nullable=True)
    page_type          = Column(String, nullable=True)        # homepage | about | contact | services | …
    status             = Column(String, nullable=False, default="queued")
    status_code        = Column(Integer, nullable=True)
    content_type       = Column(String, nullable=True)
    depth              = Column(Integer, nullable=False, default=0)
    discovered_from_url = Column(Text, nullable=True)
    content_hash       = Column(String, nullable=True)        # sha256 of raw HTML
    raw_html_path      = Column(Text, nullable=True)          # local path or S3 key
    error_message      = Column(Text, nullable=True)
    extraction_summary = Column(Text, nullable=True)          # JSON summary
    fetched_at         = Column(DateTime, nullable=True)
    created_at         = Column(DateTime, nullable=False, default=_utcnow)
    updated_at         = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)


# ── Business Profile ─────────────────────────────────────────────────────────

class CrawlBusinessProfile(Base):
    """Aggregated business profile extracted from a crawl job."""
    __tablename__ = "crawl_business_profiles"
    __table_args__ = (
        Index("ix_crawl_business_profiles_workspace", "workspace_id"),
        Index("ix_crawl_business_profiles_job", "job_id"),
    )

    id               = Column(String, primary_key=True)
    workspace_id     = Column(String, ForeignKey("onboarding_workspaces.id", ondelete="CASCADE"), nullable=False)
    job_id           = Column(String, ForeignKey("crawl_jobs.id", ondelete="CASCADE"), nullable=False)
    client_id        = Column(String, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    company_name     = Column(Text, nullable=True)
    website          = Column(Text, nullable=True)
    domain           = Column(String, nullable=True)
    description      = Column(Text, nullable=True)
    industry         = Column(String, nullable=True)
    products         = Column(Text, nullable=True)            # JSON array
    services         = Column(Text, nullable=True)            # JSON array
    locations        = Column(Text, nullable=True)            # JSON array
    contacts         = Column(Text, nullable=True)            # JSON object
    social_links     = Column(Text, nullable=True)            # JSON array
    important_pages  = Column(Text, nullable=True)            # JSON array
    missing_fields   = Column(Text, nullable=True)            # JSON array
    confidence_score     = Column(Float, nullable=True)
    profile_status       = Column(String, nullable=False, default="draft_extracted")  # draft_extracted | approved
    approved_at          = Column(DateTime, nullable=True)
    approved_by_user_id  = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at           = Column(DateTime, nullable=False, default=_utcnow)
    updated_at           = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)


# ── Extraction Evidence ──────────────────────────────────────────────────────

class ExtractionEvidence(Base):
    """Field-level evidence — every extracted fact is traceable to source."""
    __tablename__ = "extraction_evidence"
    __table_args__ = (
        Index("ix_extraction_evidence_job", "job_id"),
        Index("ix_extraction_evidence_field", "field_name"),
    )

    id                = Column(String, primary_key=True)
    job_id            = Column(String, ForeignKey("crawl_jobs.id", ondelete="CASCADE"), nullable=False)
    page_id           = Column(String, ForeignKey("crawl_pages.id", ondelete="CASCADE"), nullable=True)
    field_name        = Column(String, nullable=False)
    field_value       = Column(Text, nullable=True)
    source_url        = Column(Text, nullable=False)
    source_text       = Column(Text, nullable=True)
    extraction_method = Column(String, nullable=False)
    confidence_score  = Column(Float, nullable=True)
    created_at        = Column(DateTime, nullable=False, default=_utcnow)


# ── KB Chunks ────────────────────────────────────────────────────────────────

class KBChunk(Base):
    """RAG-ready text chunk from a crawled page.

    Stores cleaned text with source metadata.  Embeddings (vector IDs)
    are Phase 2 — only the text and metadata are stored now.
    """
    __tablename__ = "kb_chunks"
    __table_args__ = (
        Index("ix_kb_chunks_job", "job_id"),
        Index("ix_kb_chunks_page", "page_id"),
    )

    id                  = Column(String, primary_key=True)
    job_id              = Column(String, ForeignKey("crawl_jobs.id", ondelete="CASCADE"), nullable=False)
    page_id             = Column(String, ForeignKey("crawl_pages.id", ondelete="CASCADE"), nullable=False)
    source_url          = Column(Text, nullable=False)
    title               = Column(Text, nullable=True)
    page_type           = Column(String, nullable=True)
    chunk_index         = Column(Integer, nullable=False)
    chunk_text          = Column(Text, nullable=False)
    token_estimate      = Column(Integer, nullable=True)
    metadata_json       = Column(Text, nullable=True)         # JSON for extra metadata
    embedding_vector_id = Column(String, nullable=True)       # Phase 2
    created_at          = Column(DateTime, nullable=False, default=_utcnow)
