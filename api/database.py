"""
AISO Database — SQLite (local dev) / PostgreSQL (production)
SQLAlchemy ORM setup with all core models.
Swap DATABASE_URL env var to switch backends.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from datetime import datetime, timezone
import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./aiso.db")

# SQLite needs check_same_thread=False for async compatibility
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# ── Models ───────────────────────────────────────────────────────────────────

class User(Base):
    """Platform user — created on signup."""
    __tablename__ = "users"

    id            = Column(String, primary_key=True)          # UUID
    email         = Column(String, unique=True, nullable=False, index=True)
    name          = Column(String, nullable=True)
    password_hash = Column(String, nullable=True)             # Null for OAuth users
    provider      = Column(String, default="credentials")     # "google" | "credentials"
    plan_tier     = Column(String, default="pro", nullable=False)  # free | pro | custom
    account_role  = Column(String, default="user", nullable=False) # user | admin
    created_at    = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    is_active     = Column(Boolean, default=True)


class Client(Base):
    """A business being tracked by a user."""
    __tablename__ = "clients"

    id           = Column(String, primary_key=True)           # UUID
    user_id      = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    name         = Column(String, nullable=False)             # "Boston Brew Coffee"
    url          = Column(String, nullable=False)             # "https://bostonbrew.com"
    industry     = Column(String, nullable=True)
    location     = Column(String, nullable=True)
    competitors  = Column(Text, nullable=True)                # JSON array of competitor names
    created_at   = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at   = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class ClientContext(Base):
    """Confirmed client context extracted from public website evidence."""
    __tablename__ = "client_contexts"
    __table_args__ = (
        Index("ix_client_contexts_status", "status"),
    )

    client_id     = Column(String, ForeignKey("clients.id"), primary_key=True)
    status        = Column(String, default="not_started", nullable=False)  # not_started | discovering | draft | confirmed | needs_review | failed
    profile_json  = Column(Text, nullable=True)                            # structured draft/confirmed profile
    evidence_json = Column(Text, nullable=True)                            # website evidence + source URLs
    warnings_json = Column(Text, nullable=True)                            # uncertainty/safety/classification warnings
    created_at    = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at    = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class Conversation(Base):
    """Persisted assistant conversation scoped to one client and user."""
    __tablename__ = "conversations"
    __table_args__ = (
        Index("ix_conversations_client_user", "client_id", "user_id"),
        Index("ix_conversations_archived", "archived_at"),
    )

    id          = Column(String, primary_key=True)
    client_id   = Column(String, ForeignKey("clients.id"), nullable=False, index=True)
    user_id     = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    title       = Column(String, nullable=True)
    created_at  = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at  = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    archived_at = Column(DateTime, nullable=True)


class Message(Base):
    """One persisted assistant conversation message."""
    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_messages_conversation_created", "conversation_id", "created_at"),
        Index("ix_messages_role", "role"),
    )

    id              = Column(String, primary_key=True)
    conversation_id = Column(String, ForeignKey("conversations.id"), nullable=False, index=True)
    role            = Column(String, nullable=False)  # user | assistant | system
    content         = Column(Text, nullable=False)
    metadata_json   = Column(Text, nullable=True)
    created_at      = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class Scan(Base):
    """A pipeline run for a client."""
    __tablename__ = "scans"

    id          = Column(String, primary_key=True)            # UUID
    client_id   = Column(String, ForeignKey("clients.id"), nullable=False, index=True)
    status      = Column(String, default="pending")           # pending | running | complete | failed
    providers   = Column(Text, nullable=True)                 # JSON array ["openai","claude",...]
    groups      = Column(Text, nullable=True)                 # JSON array ["G1","G2",...]
    started_at  = Column(DateTime, nullable=True)
    completed_at= Column(DateTime, nullable=True)
    error       = Column(Text, nullable=True)
    created_at  = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class ScanResult(Base):
    """Aggregated results for a scan."""
    __tablename__ = "scan_results"

    id                = Column(String, primary_key=True)      # UUID
    scan_id           = Column(String, ForeignKey("scans.id"), nullable=False, index=True)
    client_id         = Column(String, ForeignKey("clients.id"), nullable=False, index=True)
    provider          = Column(String, nullable=False)         # "openai" | "claude" | ...
    group             = Column(String, nullable=False)         # "G1" ... "G7"
    total_questions   = Column(Integer, default=0)
    mention_count     = Column(Integer, default=0)
    avg_position      = Column(Float, nullable=True)
    visibility_score  = Column(Float, nullable=True)           # 0.0 – 100.0
    competitor_data   = Column(Text, nullable=True)            # JSON: {competitor: mention_count}
    created_at        = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class ScanArtifact(Base):
    """Metadata for generated or uploaded scan files.

    Raw CSV/XLSX/PDF/JSON files live in local storage today and can move to S3
    later. The database stores only metadata and an addressable storage path.
    """
    __tablename__ = "scan_artifacts"
    __table_args__ = (
        Index("ix_scan_artifacts_client_scan", "client_id", "scan_id"),
        Index("ix_scan_artifacts_type", "artifact_type"),
    )

    id                = Column(String, primary_key=True)       # UUID
    client_id         = Column(String, ForeignKey("clients.id"), nullable=False, index=True)
    scan_id           = Column(String, ForeignKey("scans.id"), nullable=True, index=True)
    artifact_type     = Column(String, nullable=False)          # collect_csv | report
    file_format       = Column(String, nullable=True)           # csv | xlsx | json | pdf
    storage_backend   = Column(String, default="local", nullable=False)  # local | s3
    storage_path      = Column(Text, nullable=False)            # repo-relative path or object key
    original_filename = Column(String, nullable=True)
    mime_type         = Column(String, nullable=True)
    size_bytes        = Column(BigInteger, nullable=True)
    sha256            = Column(String, nullable=True)
    metadata_json     = Column(Text, nullable=True)             # JSON for non-query metadata
    created_at        = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class ScanAnalysis(Base):
    """Structured analysis generated from scan results."""
    __tablename__ = "scan_analysis"
    __table_args__ = (
        Index("ix_scan_analysis_client_scan", "client_id", "scan_id"),
        Index("ix_scan_analysis_scope", "provider", "group"),
    )

    id                   = Column(String, primary_key=True)    # UUID
    client_id            = Column(String, ForeignKey("clients.id"), nullable=False, index=True)
    scan_id              = Column(String, ForeignKey("scans.id"), nullable=False, index=True)
    provider             = Column(String, nullable=True)        # null for cross-provider analysis
    group                = Column(String, nullable=True)        # null for cross-group analysis
    analysis_type        = Column(String, default="visibility_summary", nullable=False)
    summary              = Column(Text, nullable=True)
    strengths_json       = Column(Text, nullable=True)          # JSON array
    weaknesses_json      = Column(Text, nullable=True)          # JSON array
    recommendations_json = Column(Text, nullable=True)          # JSON array
    raw_json             = Column(Text, nullable=True)          # source model/tool output
    created_at           = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class SourceProfile(Base):
    """Client-specific source graph profile across scans."""
    __tablename__ = "source_profiles"
    __table_args__ = (
        Index("ix_source_profiles_client_domain", "client_id", "source_domain"),
        Index("ix_source_profiles_owner", "client_id", "owner_type"),
        Index("ix_source_profiles_action_role", "client_id", "action_role"),
        Index("ix_source_profiles_source_type", "client_id", "source_type"),
        Index("ix_source_profiles_client_url", "client_id", "canonical_url", unique=True),
    )

    id                         = Column(String, primary_key=True)
    client_id                  = Column(String, ForeignKey("clients.id"), nullable=False, index=True)
    canonical_url              = Column(Text, nullable=False)
    source_domain              = Column(String, nullable=True)
    source_title               = Column(Text, nullable=True)
    owner_type                 = Column(String, nullable=True)
    source_type                = Column(String, nullable=True)
    action_role                = Column(String, nullable=True)
    actionability_score        = Column(Float, nullable=True)
    influence_score            = Column(Float, nullable=True)
    relevance_score            = Column(Float, nullable=True)
    client_mentioned           = Column(Boolean, nullable=True)
    competitors_mentioned_json = Column(Text, nullable=True)
    topics_json                = Column(Text, nullable=True)
    fetch_status               = Column(String, nullable=True)
    last_fetched_at            = Column(DateTime, nullable=True)
    last_enriched_at           = Column(DateTime, nullable=True)
    classification_reason      = Column(Text, nullable=True)
    metadata_json              = Column(Text, nullable=True)
    created_at                 = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at                 = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class ScanCitation(Base):
    """Source-level evidence cited by provider answers."""
    __tablename__ = "scan_citations"
    __table_args__ = (
        Index("ix_scan_citations_client_scan", "client_id", "scan_id"),
        Index("ix_scan_citations_provider_group", "provider", "group"),
        Index("ix_scan_citations_domain", "source_domain"),
    )

    id             = Column(String, primary_key=True)           # UUID
    client_id      = Column(String, ForeignKey("clients.id"), nullable=False, index=True)
    scan_id        = Column(String, ForeignKey("scans.id"), nullable=False, index=True)
    source_profile_id = Column(String, ForeignKey("source_profiles.id"), nullable=True, index=True)
    provider       = Column(String, nullable=False)             # LLM provider id
    group          = Column(String, nullable=True)
    question       = Column(Text, nullable=True)
    answer_excerpt = Column(Text, nullable=True)
    citation_url   = Column(Text, nullable=False)
    citation_title = Column(Text, nullable=True)
    source_domain  = Column(String, nullable=True)
    source_rank    = Column(Integer, nullable=True)
    canonical_url  = Column(Text, nullable=True)
    citation_origin = Column(String, nullable=True)
    cited_text     = Column(Text, nullable=True)
    web_search_used = Column(Boolean, nullable=True)
    source_type    = Column(String, nullable=True)
    owner_type     = Column(String, nullable=True)
    action_role    = Column(String, nullable=True)
    actionability_score = Column(Float, nullable=True)
    influence_score = Column(Float, nullable=True)
    relevance_score = Column(Float, nullable=True)
    confidence_score = Column(Float, nullable=True)
    classification_reason = Column(Text, nullable=True)
    metadata_json  = Column(Text, nullable=True)                # JSON provider citation metadata
    created_at     = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class Action(Base):
    """AI-generated action items for a client."""
    __tablename__ = "actions"
    __table_args__ = (
        Index("ix_actions_client_scan", "client_id", "scan_id"),
        Index("ix_actions_status", "status"),
        Index("ix_actions_scan_key", "scan_id", "action_key", unique=True),
    )

    id          = Column(String, primary_key=True)            # UUID
    client_id   = Column(String, ForeignKey("clients.id"), nullable=False, index=True)
    scan_id     = Column(String, ForeignKey("scans.id"), nullable=True)
    action_key  = Column(String, nullable=True)               # stable deterministic key per scan
    title       = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    priority    = Column(String, default="medium")            # "high" | "medium" | "low"
    category    = Column(String, nullable=True)               # "on-page" | "entity" | "off-page"
    impact_pts  = Column(String, nullable=True)               # "+3-5 pts"
    effort      = Column(String, nullable=True)               # "30 min" | "1 hour"
    score       = Column(Float, nullable=True)                # ranking score from deterministic engine
    sort_order  = Column(Integer, nullable=True)              # stable UI ordering
    evidence_json = Column(Text, nullable=True)               # JSON evidence behind the recommendation
    status      = Column(String, default="open")              # "open" | "done" | "dismissed"
    created_at  = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at= Column(DateTime, nullable=True)


# ── DB helpers ───────────────────────────────────────────────────────────────

def get_db() -> Session:  # type: ignore[return]
    """FastAPI dependency — yields a DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create local development tables when auto-create is enabled.

    Production deployments should apply Alembic migrations instead of relying
    on implicit table creation at app startup.
    """
    auto_create_default = "0" if os.getenv("ENV") == "production" else "1"
    auto_create = os.getenv("AISO_AUTO_CREATE_TABLES", auto_create_default)
    if auto_create != "1":
        print("[AISO DB] Auto table creation disabled; run Alembic migrations.")
        return

    Base.metadata.create_all(bind=engine)
    print("[AISO DB] Tables initialised.")
