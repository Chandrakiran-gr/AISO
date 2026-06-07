"""
AISO Database — SQLite (local dev) / PostgreSQL (production)
SQLAlchemy ORM setup with all core models.
Swap DATABASE_URL env var to switch backends.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker, Session
from datetime import datetime, timezone
import os
import sqlite3

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./aiso.db")

# SQLite needs check_same_thread=False for async compatibility
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
    echo=False,
)


@event.listens_for(engine, "connect")
def _enforce_sqlite_foreign_keys(dbapi_connection, connection_record):
    """Turn on foreign-key enforcement for the application's SQLite connections.

    SQLite ships with FK constraints DISABLED per connection, so without this
    ``ON DELETE`` rules never fire and dangling references go undetected.
    PostgreSQL enforces FKs natively, so this is a no-op there (guarded by the
    DBAPI connection type). Scoped to the app ``engine`` deliberately: the test
    suite builds minimal fixtures on its own engines and relies on SQLite's lax
    default, so enforcement is verified separately in test_db_integrity.py.
    """
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def _json_type():
    return JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql")


def _text_array_type():
    return JSON().with_variant(postgresql.ARRAY(Text()), "postgresql")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


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
    user_id      = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name         = Column(String, nullable=False)             # "Boston Brew Coffee"
    url          = Column(String, nullable=False)             # "https://bostonbrew.com"
    industry     = Column(String, nullable=True)
    location     = Column(String, nullable=True)
    competitor_names = Column(_json_type(), nullable=True)    # competitor names; clients.competitor_domains holds domains
    tier          = Column(String, default="free", nullable=False)  # free | pro | growth | scale | enterprise
    cost_budget_default_usd = Column(Numeric(10, 2), default=5, nullable=False)
    byok          = Column(Boolean, default=False, nullable=False)
    byok_keys     = Column(_json_type(), nullable=True)        # Secret references/metadata only; never raw keys.
    owned_domains = Column(_text_array_type(), nullable=True)
    competitor_domains = Column(_text_array_type(), nullable=True)
    created_at   = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at   = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class BusinessProfile(Base):
    """Phase 12 upstream-pipeline profile confirmed before question generation."""
    __tablename__ = "business_profile"
    __table_args__ = (
        CheckConstraint(
            "vertical IN ("
            "'b2b_saas','b2b_services','local_services','ecommerce',"
            "'regulated_healthcare','regulated_legal','regulated_financial',"
            "'consumer_brand','marketplace','agency','enterprise'"
            ")",
            name="ck_business_profile_vertical",
        ),
        CheckConstraint(
            "objective IN ("
            "'awareness','consideration','preference',"
            "'reputation_defense','competitive_intelligence'"
            ")",
            name="ck_business_profile_objective",
        ),
    )

    client_id       = Column(String, ForeignKey("clients.id", ondelete="CASCADE"), primary_key=True)
    vertical        = Column(String, nullable=False)
    objective       = Column(String, nullable=False)
    category        = Column(String, nullable=False, default="")
    icp             = Column(_json_type(), nullable=False, default=dict)
    geographic_scope = Column(_json_type(), nullable=False, default=dict)
    competitors     = Column(_text_array_type(), nullable=False, default=list)
    personas        = Column(_json_type(), nullable=False, default=dict)
    crawl_artifacts = Column(_json_type(), nullable=False, default=dict)
    onboarding_completed_at = Column(DateTime, nullable=True)
    founder_reviewed_at = Column(DateTime, nullable=True)
    floor_met       = Column(Boolean, nullable=False, default=False)
    created_at      = Column(DateTime, nullable=False, default=_utcnow)
    updated_at      = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)


class MethodologyPromptVersion(Base):
    """Insert-only prompt version record with a hash-chain link."""
    __tablename__ = "methodology_prompt_version"
    __table_args__ = (
        UniqueConstraint(
            "prompt_key",
            "version",
            "prompt_hash",
            name="uq_methodology_prompt_version_hash",
        ),
        Index("ix_methodology_prompt_version_key", "prompt_key"),
    )

    id              = Column(String, primary_key=True)
    prompt_key      = Column(String, nullable=False)
    version         = Column(String, nullable=False)
    provider        = Column(String, nullable=False)
    model           = Column(String, nullable=False)
    prompt_text     = Column(Text, nullable=False)
    prompt_hash     = Column(String, nullable=False)
    prev_chain_hash = Column(String, nullable=False)
    chain_hash      = Column(String, nullable=False)
    created_at      = Column(DateTime, nullable=False, default=_utcnow)


class MethodologyVersionSet(Base):
    """Composable methodology versions stamped onto downstream scans."""
    __tablename__ = "methodology_version_set"
    __table_args__ = (
        Index("ix_methodology_version_set_validity", "valid_from", "valid_to"),
    )

    id                              = Column(String, primary_key=True)
    label                           = Column(Text, nullable=False, unique=True)
    avs_formula_version             = Column(Text, nullable=False)
    bank_version                    = Column(Text, nullable=False)
    stance_classifier_version       = Column(Text, nullable=False)
    source_classifier_version       = Column(Text, nullable=False)
    sampling_config_version         = Column(Text, nullable=False)
    provider_model_snapshot_version = Column(Text, nullable=False)
    valid_from                      = Column(DateTime, nullable=False)
    valid_to                        = Column(DateTime, nullable=True)
    sys_period                      = Column(Text, nullable=False)
    spec_document_url               = Column(Text, nullable=False)
    spec_document_hash              = Column(LargeBinary, nullable=False)
    change_memo_url                 = Column(Text, nullable=True)
    approved_by                     = Column(Text, nullable=False)
    approved_at                     = Column(DateTime, nullable=False)
    shadow_run_started_at           = Column(DateTime, nullable=True)
    shadow_run_ended_at             = Column(DateTime, nullable=True)
    superseded_by                   = Column(String, ForeignKey("methodology_version_set.id"), nullable=True)


class ScanRun(Base):
    """Spec-compliant downstream scan run, separate from the legacy scans table."""
    __tablename__ = "scan_runs"
    __table_args__ = (
        UniqueConstraint("client_id", "idempotency_key", name="uq_scan_runs_client_idempotency"),
        Index("idx_scan_runs_client_status", "client_id", "status"),
    )

    id                         = Column(String, primary_key=True)
    client_id                  = Column(String, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    idempotency_key            = Column(Text, nullable=False)
    methodology_version        = Column(Text, nullable=False)
    methodology_version_set_id = Column(String, ForeignKey("methodology_version_set.id"), nullable=True)
    status                     = Column(Text, nullable=False)
    completeness               = Column(Text, nullable=True)
    cost_budget_usd            = Column(Numeric(10, 4), nullable=False)
    cost_spent_usd             = Column(Numeric(10, 4), nullable=False, default=0)
    latency_class              = Column(Text, nullable=False)
    providers                  = Column(_json_type(), nullable=False, default=list)
    enqueued_at                = Column(DateTime, nullable=False, default=_utcnow)
    started_at                 = Column(DateTime, nullable=True)
    finished_at                = Column(DateTime, nullable=True)
    error_summary              = Column(_json_type(), nullable=True)


class ScanProgress(Base):
    """Polling progress projection for a downstream scan run."""
    __tablename__ = "scan_progress"

    scan_run_id     = Column(String, ForeignKey("scan_runs.id", ondelete="CASCADE"), primary_key=True)
    status          = Column(Text, nullable=False)
    stage           = Column(Text, nullable=False, default="queued")
    total_calls     = Column(Integer, nullable=False)
    completed_calls = Column(Integer, nullable=False, default=0)
    failed_calls    = Column(Integer, nullable=False, default=0)
    per_provider    = Column(_json_type(), nullable=False, default=dict)
    eta_seconds     = Column(Integer, nullable=True)
    updated_at      = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)


class ExecutionSample(Base):
    """Idempotent provider-call result row used by the execution saga."""
    __tablename__ = "execution_samples"

    scan_run_id        = Column(String, ForeignKey("scan_runs.id", ondelete="CASCADE"), primary_key=True)
    question_id        = Column(Text, primary_key=True)
    provider           = Column(Text, primary_key=True)
    sample_index       = Column(Integer, primary_key=True)
    planned_provider_model = Column(Text, nullable=False, default="unknown")
    provider_model     = Column(Text, nullable=True)
    temperature        = Column(Numeric(4, 3), nullable=False, default=0.700)
    top_p              = Column(Numeric(4, 3), nullable=False, default=1.000)
    seed               = Column(BigInteger, nullable=True)
    sample_plan_hash   = Column(LargeBinary, nullable=True)
    request_payload_hash = Column(LargeBinary, nullable=True)
    raw_response       = Column(_json_type(), nullable=True)
    raw_response_text  = Column(Text, nullable=True)
    raw_response_pointer = Column(Text, nullable=True)
    raw_response_hash  = Column(LargeBinary, nullable=True)
    system_fingerprint = Column(Text, nullable=True)
    cost_usd           = Column(Numeric(10, 6), nullable=False, default=0)
    provider_idem_key  = Column(Text, nullable=False)
    input_tokens       = Column(Integer, nullable=True)
    output_tokens      = Column(Integer, nullable=True)
    total_tokens       = Column(Integer, nullable=True)
    response_received_at = Column(DateTime, nullable=True)
    latency_ms         = Column(Integer, nullable=True)
    methodology_version = Column(Text, nullable=False, default="")
    cache_bust         = Column(_json_type(), nullable=False, default=dict)
    classified_stance  = Column(Text, nullable=True)
    classified_source  = Column(Text, nullable=True)
    failure_reason     = Column(Text, nullable=True)
    created_at         = Column(DateTime, nullable=False, default=_utcnow)


class ScanStep(Base):
    """Idempotency ledger for every saga step transition."""
    __tablename__ = "scan_steps"
    __table_args__ = (
        CheckConstraint(
            "event IN ('started','succeeded','failed','compensated')",
            name="ck_scan_steps_event",
        ),
        Index("idx_scan_steps_at", "scan_run_id", "occurred_at"),
    )

    scan_run_id = Column(String, ForeignKey("scan_runs.id", ondelete="CASCADE"), primary_key=True)
    step_id     = Column(Text, primary_key=True)
    event       = Column(Text, primary_key=True)
    attempt     = Column(Integer, primary_key=True, default=1)
    payload     = Column(_json_type(), nullable=True)
    occurred_at = Column(DateTime, nullable=False, default=_utcnow)


class IdempotencyKey(Base):
    """HTTP idempotency store for scan-run creation and replay."""
    __tablename__ = "idempotency_keys"
    __table_args__ = (
        Index("idx_idempotency_gc", "created_at"),
    )

    key             = Column(Text, primary_key=True)
    scope           = Column(Text, nullable=False)
    request_hash    = Column(Text, nullable=False)
    response_status = Column(Integer, nullable=True)
    response_body   = Column(_json_type(), nullable=True)
    created_at      = Column(DateTime, nullable=False, default=_utcnow)
    locked_at       = Column(DateTime, nullable=True)
    completed_at    = Column(DateTime, nullable=True)


class CostLedgerEntry(Base):
    """Per-provider spend ledger for one scan run."""
    __tablename__ = "cost_ledger"

    scan_run_id = Column(String, ForeignKey("scan_runs.id", ondelete="CASCADE"), primary_key=True)
    provider    = Column(Text, primary_key=True)
    spent_usd   = Column(Numeric(10, 6), nullable=False, default=0)
    updated_at  = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)


class ScanRawResponseArchive(Base):
    """Non-final raw response archive prepared before final scan provenance."""
    __tablename__ = "scan_raw_response_archive"
    __table_args__ = (
        UniqueConstraint("scan_id", "archive_type", name="uq_scan_raw_response_archive_type"),
        Index("ix_scan_raw_response_archive_scan", "scan_id"),
    )

    id            = Column(String, primary_key=True)
    scan_id       = Column(String, ForeignKey("scan_runs.id", ondelete="CASCADE"), nullable=False)
    archive_type  = Column(Text, nullable=False)
    sample_count  = Column(Integer, nullable=False)
    archive_url   = Column(Text, nullable=False)
    archive_hash  = Column(LargeBinary, nullable=False)
    created_at    = Column(DateTime, nullable=False, default=_utcnow)


class ScanProvenance(Base):
    """Immutable provenance record for completed downstream scan inputs/outputs."""
    __tablename__ = "scan_provenance"
    __table_args__ = (
        Index("ix_scan_provenance_client", "client_id"),
    )

    scan_id                    = Column(String, ForeignKey("scan_runs.id"), primary_key=True)
    client_id                  = Column(String, ForeignKey("clients.id"), nullable=False)
    methodology_version_set_id = Column(String, ForeignKey("methodology_version_set.id"), nullable=False)
    scan_started_at            = Column(DateTime, nullable=False)
    scan_completed_at          = Column(DateTime, nullable=False)
    question_count             = Column(Integer, nullable=False)
    sample_count               = Column(Integer, nullable=False)
    raw_response_archive_url   = Column(Text, nullable=False)
    raw_response_archive_hash  = Column(LargeBinary, nullable=False)
    scan_manifest_hash         = Column(LargeBinary, nullable=False)
    git_sha                    = Column(Text, nullable=False)
    computed_by_host           = Column(Text, nullable=False)
    prev_provenance_hash       = Column(LargeBinary, nullable=True)
    this_provenance_hash       = Column(LargeBinary, nullable=False)
    signed_at                  = Column(DateTime, nullable=False, default=_utcnow)


class Sample(Base):
    """Canonical raw LLM response sample used for classification and AVS."""
    __tablename__ = "samples"
    __table_args__ = (
        UniqueConstraint(
            "scan_id",
            "question_id",
            "provider",
            "sample_index",
            name="uq_sample_scan_question_provider_index",
        ),
        Index("ix_sample_scan_provider", "scan_id", "provider"),
    )

    id                   = Column(String, primary_key=True)
    scan_id              = Column(String, ForeignKey("scan_runs.id", ondelete="CASCADE"), nullable=False)
    question_id          = Column(String, nullable=False)
    provider             = Column(Text, nullable=False)
    provider_model       = Column(Text, nullable=False)
    system_fingerprint   = Column(Text, nullable=True)
    temperature          = Column(Numeric(4, 3), nullable=False)
    top_p                = Column(Numeric(4, 3), nullable=False, default=1.000)
    seed                 = Column(BigInteger, nullable=True)
    sample_index         = Column(Integer, nullable=False)
    request_payload_hash = Column(LargeBinary, nullable=False)
    raw_response_text    = Column(Text, nullable=False)
    raw_response_pointer = Column(Text, nullable=True)
    raw_response_hash    = Column(LargeBinary, nullable=False)
    response_received_at = Column(DateTime, nullable=False)
    latency_ms           = Column(Integer, nullable=True)
    input_tokens         = Column(Integer, nullable=True)
    output_tokens        = Column(Integer, nullable=True)
    total_tokens         = Column(Integer, nullable=True)
    methodology_version  = Column(Text, nullable=False, default="")


class Classification(Base):
    """Classifier judgment row for stance/source outputs consumed by AVS."""
    __tablename__ = "classification"
    __table_args__ = (
        # Declared as a unique Index (not a UniqueConstraint) to match migration
        # 0017, which created it via CREATE UNIQUE INDEX. Functionally identical
        # (uniqueness on the triple) but keeps models == migrations on both
        # SQLite and PostgreSQL so ``alembic check`` stays clean.
        Index(
            "uq_classification_sample_type_version",
            "sample_id",
            "classifier_type",
            "classifier_version",
            unique=True,
        ),
        Index("ix_classification_sample_type", "sample_id", "classifier_type"),
    )

    id                     = Column(String, primary_key=True)
    sample_id              = Column(String, ForeignKey("samples.id", ondelete="CASCADE"), nullable=False)
    classifier_type        = Column(Text, nullable=False)
    classifier_version     = Column(Text, nullable=False)
    classifier_model       = Column(Text, nullable=False)
    prompt_hash            = Column(LargeBinary, nullable=False)
    self_consistency_n     = Column(Integer, nullable=True)
    individual_judgments   = Column(_json_type(), nullable=True)
    consensus_value        = Column(Text, nullable=False)
    consensus_confidence   = Column(Numeric(5, 4), nullable=True)
    judged_at              = Column(DateTime, nullable=False, default=_utcnow)


class DomainClassification(Base):
    """Source-classifier cache keyed by eTLD+1 domain."""
    __tablename__ = "domain_classification"
    __table_args__ = (
        Index("ix_domain_classification_expires_at", "expires_at"),
    )

    domain             = Column(Text, primary_key=True)
    classifier_version = Column(Text, primary_key=True)
    source_class       = Column(Text, nullable=False)
    classifier_model   = Column(Text, nullable=False)
    prompt_hash        = Column(LargeBinary, nullable=True)
    confidence         = Column(Numeric(5, 4), nullable=False, default=0)
    source             = Column(Text, nullable=False)
    evidence           = Column(_json_type(), nullable=True)
    expires_at         = Column(DateTime, nullable=True)
    created_at         = Column(DateTime, nullable=False, default=_utcnow)
    updated_at         = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)


class AVSComputation(Base):
    """Computed AVS projection for one scan under one methodology version set."""
    __tablename__ = "avs_computation"
    __table_args__ = (
        UniqueConstraint(
            "scan_id",
            "methodology_version_set_id",
            name="uq_avs_computation_scan_methodology",
        ),
        Index("ix_avs_computation_scan_primary", "scan_id", "is_primary"),
    )

    id                         = Column(String, primary_key=True)
    scan_id                    = Column(String, ForeignKey("scan_provenance.scan_id", ondelete="CASCADE"), nullable=False)
    methodology_version_set_id = Column(String, ForeignKey("methodology_version_set.id"), nullable=False)
    avs_value                  = Column(Numeric(6, 3), nullable=False)
    presence                   = Column(Numeric(6, 5), nullable=False)
    prominence                 = Column(Numeric(6, 5), nullable=False)
    positivity                 = Column(Numeric(6, 5), nullable=False)
    ci_lower_95                = Column(Numeric(6, 3), nullable=False)
    ci_upper_95                = Column(Numeric(6, 3), nullable=False)
    ci_method                  = Column(Text, nullable=False)
    bootstrap_iterations       = Column(Integer, nullable=True)
    computed_at                = Column(DateTime, nullable=False, default=_utcnow)
    computed_by_git_sha        = Column(Text, nullable=False)
    is_primary                 = Column(Boolean, nullable=False, default=True)


class ScanMetric(Base):
    """Phase 13 dashboard projection: scoped visibility metrics with CIs.

    One row per (scan, scope_type, provider?, journey_stage?). scope_type is one
    of 'overall' | 'provider' | 'journey_stage' | 'provider_journey'. Mention rate
    and citation rate are tracked separately, each with a 95% Wilson interval.
    """
    __tablename__ = "scan_metrics"
    __table_args__ = (
        UniqueConstraint(
            "scan_id", "scope_type", "provider", "journey_stage",
            name="uq_scan_metric_scope",
        ),
        Index("ix_scan_metric_scan", "scan_id"),
    )

    id                         = Column(String, primary_key=True)
    scan_id                    = Column(String, ForeignKey("scan_runs.id", ondelete="CASCADE"), nullable=False)
    client_id                  = Column(String, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    methodology_version_set_id = Column(String, ForeignKey("methodology_version_set.id"), nullable=True)
    scope_type                 = Column(Text, nullable=False)
    provider                   = Column(Text, nullable=True)
    journey_stage              = Column(Text, nullable=True)
    total_questions            = Column(Integer, nullable=False, default=0)
    total_samples              = Column(Integer, nullable=False, default=0)
    mention_count              = Column(Integer, nullable=False, default=0)
    mention_rate               = Column(Numeric(6, 5), nullable=True)
    mention_rate_ci_lower_95   = Column(Numeric(6, 5), nullable=True)
    mention_rate_ci_upper_95   = Column(Numeric(6, 5), nullable=True)
    citation_count             = Column(Integer, nullable=False, default=0)
    citation_rate              = Column(Numeric(6, 5), nullable=True)
    citation_rate_ci_lower_95  = Column(Numeric(6, 5), nullable=True)
    citation_rate_ci_upper_95  = Column(Numeric(6, 5), nullable=True)
    avs_value                  = Column(Numeric(6, 3), nullable=True)
    presence                   = Column(Numeric(6, 5), nullable=True)
    prominence                 = Column(Numeric(6, 5), nullable=True)
    positivity                 = Column(Numeric(6, 5), nullable=True)
    avs_ci_lower_95            = Column(Numeric(6, 3), nullable=True)
    avs_ci_upper_95            = Column(Numeric(6, 3), nullable=True)
    avg_position               = Column(Numeric(8, 4), nullable=True)
    computed_at                = Column(DateTime, nullable=False, default=_utcnow)


class ScanCitationP13(Base):
    """Phase 13 native citation: a brand/source URL referenced in a sample.

    Distinct from the legacy ``scan_citations`` table; FKs to ``scan_runs`` and
    ``sample`` for auditability back to the exact answer.
    """
    __tablename__ = "scan_source_citations"
    __table_args__ = (
        Index("ix_scan_citation_scan_domain", "scan_id", "source_domain"),
        Index("ix_scan_citation_scan_class", "scan_id", "source_class"),
    )

    id                         = Column(String, primary_key=True)
    scan_id                    = Column(String, ForeignKey("scan_runs.id", ondelete="CASCADE"), nullable=False)
    client_id                  = Column(String, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    methodology_version_set_id = Column(String, ForeignKey("methodology_version_set.id"), nullable=True)
    sample_id                  = Column(String, nullable=True)
    provider                   = Column(Text, nullable=False)
    question_id                = Column(String, nullable=True)
    journey_stage              = Column(Text, nullable=True)
    citation_url               = Column(Text, nullable=False)
    canonical_url              = Column(Text, nullable=True)
    source_domain              = Column(Text, nullable=True)
    registered_domain          = Column(Text, nullable=True)
    source_rank                = Column(Integer, nullable=True)
    source_class               = Column(Text, nullable=True)
    source_confidence          = Column(Numeric(5, 4), nullable=True)
    action_role                = Column(Text, nullable=True)
    is_brand_citation          = Column(Boolean, nullable=False, default=False)
    is_competitor_citation     = Column(Boolean, nullable=False, default=False)
    web_search_used            = Column(Boolean, nullable=True)
    answer_excerpt             = Column(Text, nullable=True)
    created_at                 = Column(DateTime, nullable=False, default=_utcnow)


class ScanCompetitor(Base):
    """Phase 13 dashboard projection: competitor presence + share of voice."""
    __tablename__ = "scan_competitors"
    __table_args__ = (
        UniqueConstraint(
            "scan_id", "competitor_name", "scope_type", "provider", "journey_stage",
            name="uq_scan_competitor_scope",
        ),
        Index("ix_scan_competitor_scan", "scan_id"),
    )

    id                         = Column(String, primary_key=True)
    scan_id                    = Column(String, ForeignKey("scan_runs.id", ondelete="CASCADE"), nullable=False)
    client_id                  = Column(String, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    methodology_version_set_id = Column(String, ForeignKey("methodology_version_set.id"), nullable=True)
    competitor_name            = Column(Text, nullable=False)
    scope_type                 = Column(Text, nullable=False)
    provider                   = Column(Text, nullable=True)
    journey_stage              = Column(Text, nullable=True)
    mention_count              = Column(Integer, nullable=False, default=0)
    mention_rate               = Column(Numeric(6, 5), nullable=True)
    mention_rate_ci_lower_95   = Column(Numeric(6, 5), nullable=True)
    mention_rate_ci_upper_95   = Column(Numeric(6, 5), nullable=True)
    share_of_voice             = Column(Numeric(6, 5), nullable=True)
    citation_count             = Column(Integer, nullable=False, default=0)
    computed_at                = Column(DateTime, nullable=False, default=_utcnow)


class ScanAction(Base):
    """Phase 13 dashboard projection: a prioritized, evidence-backed action."""
    __tablename__ = "scan_actions"
    __table_args__ = (
        UniqueConstraint("scan_id", "action_key", name="uq_scan_action_key"),
        Index("ix_scan_action_scan", "scan_id"),
    )

    id                         = Column(String, primary_key=True)
    scan_id                    = Column(String, ForeignKey("scan_runs.id", ondelete="CASCADE"), nullable=False)
    client_id                  = Column(String, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    methodology_version_set_id = Column(String, ForeignKey("methodology_version_set.id"), nullable=True)
    action_key                 = Column(String, nullable=False)
    title                      = Column(Text, nullable=False)
    description                = Column(Text, nullable=True)
    priority                   = Column(Text, nullable=True)
    category                   = Column(Text, nullable=True)
    effort                     = Column(Text, nullable=True)
    impact_estimate            = Column(Numeric(6, 3), nullable=True)
    score                      = Column(Numeric(8, 4), nullable=True)
    sort_order                 = Column(Integer, nullable=True)
    action_role                = Column(Text, nullable=True)
    target_provider            = Column(Text, nullable=True)
    target_journey_stage       = Column(Text, nullable=True)
    target_questions_json      = Column(_json_type(), nullable=True)
    competing_sources_json     = Column(_json_type(), nullable=True)
    competing_competitors_json = Column(_json_type(), nullable=True)
    evidence_json              = Column(_json_type(), nullable=True)
    status                     = Column(Text, nullable=False, default="open")
    created_at                 = Column(DateTime, nullable=False, default=_utcnow)


class ScanQuestionResult(Base):
    """Phase 13 dashboard projection: per-(question, provider) appearance + sources.

    Backs the 'Missed Questions' view. Materialized at publish so dashboard reads
    are fast and tied to the signed scan, rather than recomputed from raw samples.
    """
    __tablename__ = "scan_question_results"
    __table_args__ = (
        UniqueConstraint("scan_id", "question_id", "provider", name="uq_scan_question_result"),
        Index("ix_scan_question_result_scan", "scan_id"),
    )

    id                         = Column(String, primary_key=True)
    scan_id                    = Column(String, ForeignKey("scan_runs.id", ondelete="CASCADE"), nullable=False)
    client_id                  = Column(String, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    methodology_version_set_id = Column(String, ForeignKey("methodology_version_set.id"), nullable=True)
    question_id                = Column(String, nullable=False)
    question_text              = Column(Text, nullable=True)
    provider                   = Column(Text, nullable=False)
    journey_stage              = Column(Text, nullable=True)
    total_samples              = Column(Integer, nullable=False, default=0)
    mention_count              = Column(Integer, nullable=False, default=0)
    appeared                   = Column(Boolean, nullable=False, default=False)
    mention_rank               = Column(Integer, nullable=True)
    avg_position               = Column(Numeric(8, 4), nullable=True)
    cited_sources_json         = Column(_json_type(), nullable=True)
    competitors_mentioned_json = Column(_json_type(), nullable=True)
    answer_excerpt             = Column(Text, nullable=True)
    priority_score             = Column(Numeric(6, 2), nullable=True)
    created_at                 = Column(DateTime, nullable=False, default=_utcnow)


class AuditEvent(Base):
    """Insert-only hash-chained audit event."""
    __tablename__ = "audit_event"
    __table_args__ = (
        Index("idx_audit_event_resource", "resource_type", "resource_id"),
        Index("idx_audit_event_actor", "actor_type", "actor_id"),
        Index("idx_audit_event_correlation", "correlation_id"),
    )

    id               = Column(Integer, primary_key=True, autoincrement=True)
    event_time       = Column(DateTime, nullable=False, default=_utcnow)
    actor_type       = Column(Text, nullable=False)
    actor_id         = Column(Text, nullable=False)
    actor_session_id = Column(Text, nullable=True)
    source_ip        = Column(String, nullable=True)
    user_agent       = Column(Text, nullable=True)
    action           = Column(Text, nullable=False)
    resource_type    = Column(Text, nullable=False)
    resource_id      = Column(Text, nullable=False)
    before_state     = Column(_json_type(), nullable=True)
    after_state      = Column(_json_type(), nullable=True)
    reason           = Column(Text, nullable=True)
    correlation_id   = Column(String, nullable=True)
    txid             = Column(BigInteger, nullable=False, default=0)
    prev_event_hash  = Column(LargeBinary, nullable=True)
    event_hash       = Column(LargeBinary, nullable=False)
    hmac_key_version = Column(Integer, nullable=False)


class ClientContext(Base):
    """Confirmed client context extracted from public website evidence."""
    __tablename__ = "client_contexts"
    __table_args__ = (
        Index("ix_client_contexts_status", "status"),
    )

    client_id     = Column(String, ForeignKey("clients.id", ondelete="CASCADE"), primary_key=True)
    status        = Column(String, default="not_started", nullable=False)  # not_started | discovering | draft | confirmed | needs_review | failed
    profile_json  = Column(_json_type(), nullable=True)                    # structured draft/confirmed profile
    evidence_json = Column(_json_type(), nullable=True)                    # website evidence + source URLs
    warnings_json = Column(_json_type(), nullable=True)                    # uncertainty/safety/classification warnings
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
    client_id   = Column(String, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id     = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title       = Column(String, nullable=True)
    summary_json = Column(_json_type(), nullable=True)
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
    conversation_id = Column(String, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    role            = Column(String, nullable=False)  # user | assistant | system
    content         = Column(Text, nullable=False)
    metadata_json   = Column(_json_type(), nullable=True)
    created_at      = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class ContentDraft(Base):
    """Human-reviewed content generated from assistant conversations."""
    __tablename__ = "content_drafts"
    __table_args__ = (
        Index("ix_content_drafts_client_status", "client_id", "status"),
        Index("ix_content_drafts_conversation", "conversation_id"),
    )

    id              = Column(String, primary_key=True)
    conversation_id = Column(String, ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True)
    client_id       = Column(String, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by      = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    content_type    = Column(String, nullable=False)          # blog_post | linkedin_post | platform_listing | review_response | faq_page | schema_markup | other
    title           = Column(String, nullable=False)
    content         = Column(Text, nullable=False)
    status          = Column(String, default="pending_review", nullable=False)  # pending_review | approved | rejected | archived
    reviewed_by     = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at     = Column(DateTime, nullable=True)
    review_notes    = Column(Text, nullable=True)
    source_action_id     = Column(String, ForeignKey("actions.id", ondelete="SET NULL"), nullable=True)   # Action that triggered this content
    target_questions_json = Column(_json_type(), nullable=True)  # JSON array of scan questions this content targets
    export_format   = Column(String, nullable=True)           # pdf | docx | null
    export_path     = Column(Text, nullable=True)             # Local path to exported file
    created_at      = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at      = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class AssistantRateLimitEvent(Base):
    """Per-user assistant usage event for sliding-window rate limits."""
    __tablename__ = "assistant_rate_limit_events"
    __table_args__ = (
        Index("ix_assistant_rate_limit_user_event_created", "user_id", "event_type", "created_at"),
    )

    id         = Column(String, primary_key=True)
    user_id    = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type = Column(String, nullable=False, default="assistant_message")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)


class Scan(Base):
    """A pipeline run for a client."""
    __tablename__ = "scans"

    id          = Column(String, primary_key=True)            # UUID
    client_id   = Column(String, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    status      = Column(String, default="pending")           # pending | running | complete | failed
    providers   = Column(_json_type(), nullable=True)         # JSON array ["openai","claude",...]
    groups      = Column(_json_type(), nullable=True)         # JSON array ["G1","G2",...]
    started_at  = Column(DateTime, nullable=True)
    completed_at= Column(DateTime, nullable=True)
    error       = Column(Text, nullable=True)
    created_at  = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class ScanResult(Base):
    """Aggregated results for a scan."""
    __tablename__ = "scan_results"

    id                = Column(String, primary_key=True)      # UUID
    scan_id           = Column(String, ForeignKey("scans.id", ondelete="CASCADE"), nullable=False, index=True)
    client_id         = Column(String, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    provider          = Column(String, nullable=False)         # "openai" | "claude" | ...
    group             = Column(String, nullable=False)         # "G1" ... "G7"
    total_questions   = Column(Integer, default=0)
    mention_count     = Column(Integer, default=0)
    avg_position      = Column(Float, nullable=True)
    visibility_score  = Column(Float, nullable=True)           # 0.0 – 100.0
    competitor_data   = Column(_json_type(), nullable=True)    # JSON: {competitor: mention_count}
    created_at        = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class QuestionCandidate(Base):
    """Generated candidate question before realism/scoring/selection."""
    __tablename__ = "question_candidate"
    __table_args__ = (
        UniqueConstraint(
            "client_id",
            "text_hash",
            "generator_version",
            name="uq_question_candidate_client_hash_generator",
        ),
        Index("ix_question_candidate_client", "client_id"),
        Index("ix_question_candidate_scan_run", "scan_run_id"),
    )

    id                     = Column(String, primary_key=True)
    client_id              = Column(String, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    scan_run_id            = Column(String, nullable=True)
    text                   = Column(Text, nullable=False)
    text_hash              = Column(String, nullable=False)
    journey_stage          = Column(String, nullable=False)
    brand_frame            = Column(String, nullable=False)
    intent_class           = Column(String, nullable=False)
    persona                = Column(String, nullable=True)
    locality               = Column(String, nullable=True)
    rationale              = Column(Text, nullable=True)
    realism_score          = Column(Numeric(5, 3), nullable=True)
    selected               = Column(Boolean, nullable=False, default=False)
    generator_version      = Column(String, nullable=False)
    realism_filter_version = Column(String, nullable=False)
    created_at             = Column(DateTime, nullable=False, default=_utcnow)


class QuestionScore(Base):
    """Immutable score row for one candidate under a scorer version."""
    __tablename__ = "question_candidate_score"

    question_id = Column(String, ForeignKey("question_candidate.id", ondelete="CASCADE"), primary_key=True)
    scored_at   = Column(DateTime, primary_key=True)
    d1_buyer_plausibility = Column(Numeric(5, 3), nullable=True)
    d2_commercial_proximity = Column(Numeric(5, 3), nullable=True)
    d3_cognitive_answerability = Column(Numeric(5, 3), nullable=True)
    d4_diagnostic_power = Column(Numeric(5, 3), nullable=True)
    d5_statistical_identifiability = Column(Numeric(5, 3), nullable=True)
    weighted_score = Column(Numeric(5, 3), nullable=False)
    rationale      = Column(Text, nullable=True)
    scorer_version = Column(String, nullable=False)


class QuestionBankVersion(Base):
    """Versioned canonical measurement question bank for a client."""
    __tablename__ = "question_bank_version"

    bank_version_id   = Column(String, primary_key=True)
    client_id         = Column(String, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    avs_version       = Column(Text, nullable=False)
    effective_from    = Column(DateTime, nullable=False)
    effective_to      = Column(DateTime, nullable=True)
    n_core            = Column(Integer, nullable=False)
    n_tail            = Column(Integer, nullable=False)
    n_total           = Column(Integer, nullable=False)
    rotation_reason   = Column(Text, nullable=True)
    parent_version_id = Column(String, ForeignKey("question_bank_version.bank_version_id", ondelete="SET NULL"), nullable=True)
    created_at        = Column(DateTime, nullable=False, default=_utcnow)


class QuestionBankQuestion(Base):
    """Canonical immutable question used by scan manifests."""
    __tablename__ = "question"
    __table_args__ = (
        CheckConstraint(
            "journey_stage IN ('J1','J2','J3','J4','J5','J6')",
            name="ck_question_journey_stage",
        ),
        CheckConstraint(
            "brand_frame IN ('U','B','C')",
            name="ck_question_brand_frame",
        ),
        CheckConstraint(
            "source IN ('generated','manual','imported')",
            name="ck_question_source",
        ),
        UniqueConstraint("client_id", "text_hash", name="uq_question_client_text_hash"),
    )

    question_id   = Column(String, primary_key=True)
    client_id     = Column(String, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    text          = Column(Text, nullable=False)
    text_hash     = Column(Text, nullable=False)
    journey_stage = Column(Text, nullable=False)
    brand_frame   = Column(Text, nullable=False)
    locality      = Column(Text, nullable=False, default="L0")
    persona_id    = Column(String, nullable=True)
    source        = Column(Text, nullable=False)
    created_at    = Column(DateTime, nullable=False, default=_utcnow)


class QuestionBankScore(Base):
    """Canonical question-bank score row from question-bank-1.0.md."""
    __tablename__ = "question_score"

    question_id          = Column(String, ForeignKey("question.question_id", ondelete="CASCADE"), primary_key=True)
    scored_at            = Column(DateTime, primary_key=True)
    journey_match        = Column(Numeric(5, 3), nullable=True)
    brand_frame_match    = Column(Numeric(5, 3), nullable=True)
    demand_signal        = Column(Numeric(5, 3), nullable=True)
    commercial_prox      = Column(Numeric(5, 3), nullable=True)
    buyer_plausibility   = Column(Numeric(5, 3), nullable=True)
    scope_calibration    = Column(Numeric(5, 3), nullable=True)
    objective_alignment  = Column(Numeric(5, 3), nullable=True)
    construct_coverage   = Column(Numeric(5, 3), nullable=True)
    provider_diff        = Column(Numeric(5, 3), nullable=True)
    goodhart_resistance  = Column(Numeric(5, 3), nullable=True)
    answer_stability     = Column(Numeric(5, 3), nullable=True)
    composite            = Column(Numeric(5, 3), nullable=False)
    scorer_version       = Column(Text, nullable=False)


class QuestionBankMembership(Base):
    """Membership and HT weight for a question in a bank version."""
    __tablename__ = "question_bank_membership"
    __table_args__ = (
        CheckConstraint(
            "state IN ('FROZEN','TAIL','BRIDGE_IN','BRIDGE_OUT')",
            name="ck_question_bank_membership_state",
        ),
    )

    bank_version_id = Column(String, ForeignKey("question_bank_version.bank_version_id", ondelete="CASCADE"), primary_key=True)
    question_id     = Column(String, ForeignKey("question.question_id", ondelete="CASCADE"), primary_key=True)
    state           = Column(Text, nullable=False)
    weight          = Column(Numeric(6, 4), nullable=False, default=1)
    entered_at      = Column(DateTime, nullable=False)


class ScanManifest(Base):
    """Question manifest fixed at scan start."""
    __tablename__ = "scan_manifest"

    scan_id        = Column(String, primary_key=True)
    question_id    = Column(String, ForeignKey("question.question_id", ondelete="CASCADE"), primary_key=True)
    bank_version_id = Column(String, ForeignKey("question_bank_version.bank_version_id", ondelete="CASCADE"), nullable=False)
    weight_at_scan = Column(Numeric(6, 4), nullable=False)
    state_at_scan  = Column(Text, nullable=False)


class QuestionBridge(Base):
    """Bridge record for rotated questions."""
    __tablename__ = "question_bridge"
    __table_args__ = (
        CheckConstraint(
            "bridge_method IN ('parallel_measurement','rasch_latent','none')",
            name="ck_question_bridge_method",
        ),
    )

    bridge_id         = Column(String, primary_key=True)
    old_question_id   = Column(String, ForeignKey("question.question_id", ondelete="CASCADE"), nullable=False)
    new_question_id   = Column(String, ForeignKey("question.question_id", ondelete="SET NULL"), nullable=True)
    bridge_scan_id    = Column(String, nullable=True)
    equivalence_score = Column(Numeric(5, 3), nullable=True)
    bridge_method     = Column(Text, nullable=False)
    avs_version_pre   = Column(Text, nullable=True)
    avs_version_post  = Column(Text, nullable=True)
    created_at        = Column(DateTime, nullable=False, default=_utcnow)


class QuestionDeprecation(Base):
    """Deprecation record for a canonical question."""
    __tablename__ = "question_deprecation"

    question_id    = Column(String, ForeignKey("question.question_id", ondelete="CASCADE"), primary_key=True)
    deprecated_at  = Column(DateTime, nullable=False)
    reason         = Column(Text, nullable=False)
    replaced_by    = Column(String, ForeignKey("question.question_id", ondelete="SET NULL"), nullable=True)


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
    client_id         = Column(String, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    scan_id           = Column(String, ForeignKey("scans.id", ondelete="CASCADE"), nullable=True, index=True)
    artifact_type     = Column(String, nullable=False)          # collect_csv | report
    file_format       = Column(String, nullable=True)           # csv | xlsx | json | pdf
    storage_backend   = Column(String, default="local", nullable=False)  # local | s3
    storage_path      = Column(Text, nullable=False)            # repo-relative path or object key
    original_filename = Column(String, nullable=True)
    mime_type         = Column(String, nullable=True)
    size_bytes        = Column(BigInteger, nullable=True)
    sha256            = Column(String, nullable=True)
    metadata_json     = Column(Text, nullable=True)             # storage-serialized JSON string (kept Text: produced by the storage layer)
    created_at        = Column(DateTime, default=lambda: datetime.now(timezone.utc))


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
    client_id                  = Column(String, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
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
    competitors_mentioned_json = Column(_json_type(), nullable=True)
    topics_json                = Column(_json_type(), nullable=True)
    fetch_status               = Column(String, nullable=True)
    last_fetched_at            = Column(DateTime, nullable=True)
    last_enriched_at           = Column(DateTime, nullable=True)
    classification_reason      = Column(Text, nullable=True)
    metadata_json              = Column(_json_type(), nullable=True)
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
    client_id      = Column(String, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    scan_id        = Column(String, ForeignKey("scans.id", ondelete="CASCADE"), nullable=False, index=True)
    source_profile_id = Column(String, ForeignKey("source_profiles.id", ondelete="SET NULL"), nullable=True, index=True)
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
    metadata_json  = Column(_json_type(), nullable=True)        # JSON provider citation metadata
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
    client_id   = Column(String, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    scan_id     = Column(String, ForeignKey("scans.id", ondelete="CASCADE"), nullable=True)
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
    remediation_type      = Column(String, nullable=True)     # blog_post | faq_page | schema_markup | listing_update | review_response | page_optimization | linkedin_post
    target_questions_json  = Column(Text, nullable=True)      # JSON array of question strings this action addresses
    target_providers_json  = Column(Text, nullable=True)      # JSON array of provider names (e.g. ["perplexity","openai"])
    evidence_summary       = Column(Text, nullable=True)      # Human-readable paragraph: why this matters, what scan found
    impact_estimate        = Column(Float, nullable=True)     # 0-100 predicted score improvement
    status      = Column(String, default="open")              # "open" | "done" | "dismissed"
    created_at  = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at= Column(DateTime, nullable=True)


# ── Relationships (core ownership graph) ─────────────────────────────────────
# Assigned imperatively after the mapped classes are defined. ``passive_deletes``
# defers to the database ON DELETE rules from migration 0020 — the ORM does not
# emit child DELETE/UPDATE on parent delete, it trusts the DB cascade. Only
# unambiguous single-FK pairs are mapped; tables with multiple FKs to the same
# parent (e.g. content_drafts → users) are intentionally left unmapped.
# Collections use cascade="all, delete-orphan" + passive_deletes=True so the ORM
# defers entirely to the database ON DELETE CASCADE rather than emitting its own
# child DELETE/UPDATE (which would otherwise try to NULL a NOT NULL FK on a
# loaded child when the parent is deleted).
_OWNS = {"cascade": "all, delete-orphan", "passive_deletes": True}

User.clients = relationship("Client", back_populates="user", **_OWNS)
Client.user = relationship("User", back_populates="clients")

Client.scans = relationship("Scan", back_populates="client", **_OWNS)
Scan.client = relationship("Client", back_populates="scans")

Client.scan_runs = relationship("ScanRun", back_populates="client", **_OWNS)
ScanRun.client = relationship("Client", back_populates="scan_runs")

Scan.results = relationship("ScanResult", back_populates="scan", **_OWNS)
ScanResult.scan = relationship("Scan", back_populates="results")

Scan.citations = relationship("ScanCitation", back_populates="scan", **_OWNS)
ScanCitation.scan = relationship("Scan", back_populates="citations")

Conversation.messages = relationship("Message", back_populates="conversation", **_OWNS)
Message.conversation = relationship("Conversation", back_populates="messages")


# ── DB helpers ───────────────────────────────────────────────────────────────

def get_db() -> Session:  # type: ignore[return]
    """FastAPI dependency — yields a DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Optionally create tables from models when explicitly opted in.

    Alembic migrations are the single source of truth for the schema in EVERY
    environment — run ``alembic upgrade head``. Implicit ``create_all()`` is OFF
    by default (in dev and prod alike) because it silently drifts the live
    schema away from the migrations (it only creates *missing* tables and never
    alters existing ones). Enable it only for throwaway local experiments by
    setting ``AISO_AUTO_CREATE_TABLES=1``. Unit tests build their own schema via
    ``Base.metadata.create_all`` on a dedicated engine and do not use this path.
    """
    auto_create = os.getenv("AISO_AUTO_CREATE_TABLES", "0")
    if auto_create != "1":
        print("[AISO DB] Auto table creation disabled; run `alembic upgrade head`.")
        return

    Base.metadata.create_all(bind=engine)
    print("[AISO DB] Tables initialised via create_all (AISO_AUTO_CREATE_TABLES=1).")
