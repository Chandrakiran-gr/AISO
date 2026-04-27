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
    provider       = Column(String, nullable=False)             # LLM provider id
    group          = Column(String, nullable=True)
    question       = Column(Text, nullable=True)
    answer_excerpt = Column(Text, nullable=True)
    citation_url   = Column(Text, nullable=False)
    citation_title = Column(Text, nullable=True)
    source_domain  = Column(String, nullable=True)
    source_rank    = Column(Integer, nullable=True)
    metadata_json  = Column(Text, nullable=True)                # JSON provider citation metadata
    created_at     = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class Action(Base):
    """AI-generated action items for a client."""
    __tablename__ = "actions"

    id          = Column(String, primary_key=True)            # UUID
    client_id   = Column(String, ForeignKey("clients.id"), nullable=False, index=True)
    scan_id     = Column(String, ForeignKey("scans.id"), nullable=True)
    title       = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    priority    = Column(String, default="medium")            # "high" | "medium" | "low"
    category    = Column(String, nullable=True)               # "on-page" | "entity" | "off-page"
    impact_pts  = Column(String, nullable=True)               # "+3-5 pts"
    effort      = Column(String, nullable=True)               # "30 min" | "1 hour"
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
