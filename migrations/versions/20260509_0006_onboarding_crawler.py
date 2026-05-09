"""Create onboarding crawler tables.

Revision ID: 20260509_0006
Revises: 20260508_0005
Create Date: 2026-05-09
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260509_0006"
down_revision = "20260508_0005"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    # ── onboarding_workspaces ────────────────────────────────────────────
    if not _table_exists("onboarding_workspaces"):
        op.create_table(
            "onboarding_workspaces",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("client_id", sa.String(), sa.ForeignKey("clients.id"), nullable=False),
            sa.Column("website_url", sa.Text(), nullable=False),
            sa.Column("normalized_domain", sa.String(), nullable=False),
            sa.Column("allowed_domains", sa.Text(), nullable=False),
            sa.Column("consent_confirmed", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("status", sa.String(), nullable=False, server_default="created"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_onboarding_workspaces_client", "onboarding_workspaces", ["client_id"])
        op.create_index("ix_onboarding_workspaces_domain", "onboarding_workspaces", ["normalized_domain"])

    # ── crawl_jobs ────────────────────────────────────────────────────────
    if not _table_exists("crawl_jobs"):
        op.create_table(
            "crawl_jobs",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("workspace_id", sa.String(), sa.ForeignKey("onboarding_workspaces.id"), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="queued"),
            sa.Column("crawl_mode", sa.String(), nullable=False, server_default="standard"),
            sa.Column("max_pages", sa.Integer(), nullable=False, server_default=sa.text("100")),
            sa.Column("max_depth", sa.Integer(), nullable=False, server_default=sa.text("3")),
            sa.Column("allow_playwright_fallback", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("pages_discovered", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("pages_queued", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("pages_crawled", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("pages_skipped", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("pages_failed", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("warnings", sa.Text(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_crawl_jobs_workspace", "crawl_jobs", ["workspace_id"])
        op.create_index("ix_crawl_jobs_status", "crawl_jobs", ["status"])

    # ── crawl_pages ───────────────────────────────────────────────────────
    if not _table_exists("crawl_pages"):
        op.create_table(
            "crawl_pages",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("job_id", sa.String(), sa.ForeignKey("crawl_jobs.id"), nullable=False),
            sa.Column("url", sa.Text(), nullable=False),
            sa.Column("normalized_url", sa.Text(), nullable=False),
            sa.Column("final_url", sa.Text(), nullable=True),
            sa.Column("domain", sa.String(), nullable=False),
            sa.Column("title", sa.Text(), nullable=True),
            sa.Column("page_type", sa.String(), nullable=True),
            sa.Column("status", sa.String(), nullable=False, server_default="queued"),
            sa.Column("status_code", sa.Integer(), nullable=True),
            sa.Column("content_type", sa.String(), nullable=True),
            sa.Column("depth", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("discovered_from_url", sa.Text(), nullable=True),
            sa.Column("content_hash", sa.String(), nullable=True),
            sa.Column("raw_html_path", sa.Text(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("extraction_summary", sa.Text(), nullable=True),
            sa.Column("fetched_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_crawl_pages_job", "crawl_pages", ["job_id"])
        op.create_index("uq_crawl_pages_job_url", "crawl_pages", ["job_id", "normalized_url"], unique=True)

    # ── crawl_business_profiles ───────────────────────────────────────────
    if not _table_exists("crawl_business_profiles"):
        op.create_table(
            "crawl_business_profiles",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("workspace_id", sa.String(), sa.ForeignKey("onboarding_workspaces.id"), nullable=False),
            sa.Column("job_id", sa.String(), sa.ForeignKey("crawl_jobs.id"), nullable=False),
            sa.Column("client_id", sa.String(), sa.ForeignKey("clients.id"), nullable=False),
            sa.Column("company_name", sa.Text(), nullable=True),
            sa.Column("website", sa.Text(), nullable=True),
            sa.Column("domain", sa.String(), nullable=True),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("industry", sa.String(), nullable=True),
            sa.Column("products", sa.Text(), nullable=True),
            sa.Column("services", sa.Text(), nullable=True),
            sa.Column("locations", sa.Text(), nullable=True),
            sa.Column("contacts", sa.Text(), nullable=True),
            sa.Column("social_links", sa.Text(), nullable=True),
            sa.Column("important_pages", sa.Text(), nullable=True),
            sa.Column("missing_fields", sa.Text(), nullable=True),
            sa.Column("confidence_score", sa.Float(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_crawl_business_profiles_workspace", "crawl_business_profiles", ["workspace_id"])
        op.create_index("ix_crawl_business_profiles_job", "crawl_business_profiles", ["job_id"])

    # ── extraction_evidence ───────────────────────────────────────────────
    if not _table_exists("extraction_evidence"):
        op.create_table(
            "extraction_evidence",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("job_id", sa.String(), sa.ForeignKey("crawl_jobs.id"), nullable=False),
            sa.Column("page_id", sa.String(), sa.ForeignKey("crawl_pages.id"), nullable=True),
            sa.Column("field_name", sa.String(), nullable=False),
            sa.Column("field_value", sa.Text(), nullable=True),
            sa.Column("source_url", sa.Text(), nullable=False),
            sa.Column("source_text", sa.Text(), nullable=True),
            sa.Column("extraction_method", sa.String(), nullable=False),
            sa.Column("confidence_score", sa.Float(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_extraction_evidence_job", "extraction_evidence", ["job_id"])
        op.create_index("ix_extraction_evidence_field", "extraction_evidence", ["field_name"])

    # ── kb_chunks ─────────────────────────────────────────────────────────
    if not _table_exists("kb_chunks"):
        op.create_table(
            "kb_chunks",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("job_id", sa.String(), sa.ForeignKey("crawl_jobs.id"), nullable=False),
            sa.Column("page_id", sa.String(), sa.ForeignKey("crawl_pages.id"), nullable=False),
            sa.Column("source_url", sa.Text(), nullable=False),
            sa.Column("title", sa.Text(), nullable=True),
            sa.Column("page_type", sa.String(), nullable=True),
            sa.Column("chunk_index", sa.Integer(), nullable=False),
            sa.Column("chunk_text", sa.Text(), nullable=False),
            sa.Column("token_estimate", sa.Integer(), nullable=True),
            sa.Column("metadata_json", sa.Text(), nullable=True),
            sa.Column("embedding_vector_id", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_kb_chunks_job", "kb_chunks", ["job_id"])
        op.create_index("ix_kb_chunks_page", "kb_chunks", ["page_id"])


def downgrade() -> None:
    for table in ("kb_chunks", "extraction_evidence", "crawl_business_profiles", "crawl_pages", "crawl_jobs", "onboarding_workspaces"):
        if _table_exists(table):
            op.drop_table(table)
