"""Phase 13 dashboard projection tables.

Native materialized analytics for the dashboard (metrics with CIs, citations,
competitors, actions), all FK'd to scan_runs — replacing the legacy
ScanResult/ScanCitation/Action read path behind AISO_SCAN_ENGINE.

Revision ID: 20260604_0018
Revises: 20260524_0017
Create Date: 2026-06-04 00:18:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260604_0018"
down_revision = "20260524_0017"
branch_labels = None
depends_on = None


def _json_type():
    return sa.JSON().with_variant(sa.JSON(), "sqlite")


def _table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def _create_index(index_name: str, table_name: str, columns: list[str], *, unique: bool = False) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {index["name"] for index in inspector.get_indexes(table_name)}
    if index_name not in existing:
        op.create_index(index_name, table_name, columns, unique=unique)


def upgrade() -> None:
    if not _table_exists("scan_metric"):
        op.create_table(
            "scan_metric",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("scan_id", sa.String(), nullable=False),
            sa.Column("client_id", sa.String(), nullable=False),
            sa.Column("methodology_version_set_id", sa.String(), nullable=False),
            sa.Column("scope_type", sa.Text(), nullable=False),
            sa.Column("provider", sa.Text(), nullable=True),
            sa.Column("journey_stage", sa.Text(), nullable=True),
            sa.Column("total_questions", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("total_samples", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("mention_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("mention_rate", sa.Numeric(6, 5), nullable=True),
            sa.Column("mention_rate_ci_lower_95", sa.Numeric(6, 5), nullable=True),
            sa.Column("mention_rate_ci_upper_95", sa.Numeric(6, 5), nullable=True),
            sa.Column("citation_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("citation_rate", sa.Numeric(6, 5), nullable=True),
            sa.Column("citation_rate_ci_lower_95", sa.Numeric(6, 5), nullable=True),
            sa.Column("citation_rate_ci_upper_95", sa.Numeric(6, 5), nullable=True),
            sa.Column("avs_value", sa.Numeric(6, 3), nullable=True),
            sa.Column("presence", sa.Numeric(6, 5), nullable=True),
            sa.Column("prominence", sa.Numeric(6, 5), nullable=True),
            sa.Column("positivity", sa.Numeric(6, 5), nullable=True),
            sa.Column("avs_ci_lower_95", sa.Numeric(6, 3), nullable=True),
            sa.Column("avs_ci_upper_95", sa.Numeric(6, 3), nullable=True),
            sa.Column("avg_position", sa.Numeric(8, 4), nullable=True),
            sa.Column("computed_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["scan_id"], ["scan_runs.id"], ondelete="CASCADE"),
            sa.UniqueConstraint(
                "scan_id", "scope_type", "provider", "journey_stage",
                name="uq_scan_metric_scope",
            ),
        )
    _create_index("ix_scan_metric_scan", "scan_metric", ["scan_id"])

    if not _table_exists("scan_citation"):
        op.create_table(
            "scan_citation",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("scan_id", sa.String(), nullable=False),
            sa.Column("client_id", sa.String(), nullable=False),
            sa.Column("methodology_version_set_id", sa.String(), nullable=False),
            sa.Column("sample_id", sa.String(), nullable=True),
            sa.Column("provider", sa.Text(), nullable=False),
            sa.Column("question_id", sa.String(), nullable=True),
            sa.Column("journey_stage", sa.Text(), nullable=True),
            sa.Column("citation_url", sa.Text(), nullable=False),
            sa.Column("canonical_url", sa.Text(), nullable=True),
            sa.Column("source_domain", sa.Text(), nullable=True),
            sa.Column("registered_domain", sa.Text(), nullable=True),
            sa.Column("source_rank", sa.Integer(), nullable=True),
            sa.Column("source_class", sa.Text(), nullable=True),
            sa.Column("source_confidence", sa.Numeric(5, 4), nullable=True),
            sa.Column("action_role", sa.Text(), nullable=True),
            sa.Column("is_brand_citation", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("is_competitor_citation", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("web_search_used", sa.Boolean(), nullable=True),
            sa.Column("answer_excerpt", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["scan_id"], ["scan_runs.id"], ondelete="CASCADE"),
        )
    _create_index("ix_scan_citation_scan_domain", "scan_citation", ["scan_id", "source_domain"])
    _create_index("ix_scan_citation_scan_class", "scan_citation", ["scan_id", "source_class"])

    if not _table_exists("scan_competitor"):
        op.create_table(
            "scan_competitor",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("scan_id", sa.String(), nullable=False),
            sa.Column("client_id", sa.String(), nullable=False),
            sa.Column("methodology_version_set_id", sa.String(), nullable=False),
            sa.Column("competitor_name", sa.Text(), nullable=False),
            sa.Column("scope_type", sa.Text(), nullable=False),
            sa.Column("provider", sa.Text(), nullable=True),
            sa.Column("journey_stage", sa.Text(), nullable=True),
            sa.Column("mention_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("mention_rate", sa.Numeric(6, 5), nullable=True),
            sa.Column("mention_rate_ci_lower_95", sa.Numeric(6, 5), nullable=True),
            sa.Column("mention_rate_ci_upper_95", sa.Numeric(6, 5), nullable=True),
            sa.Column("share_of_voice", sa.Numeric(6, 5), nullable=True),
            sa.Column("citation_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("computed_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["scan_id"], ["scan_runs.id"], ondelete="CASCADE"),
            sa.UniqueConstraint(
                "scan_id", "competitor_name", "scope_type", "provider", "journey_stage",
                name="uq_scan_competitor_scope",
            ),
        )
    _create_index("ix_scan_competitor_scan", "scan_competitor", ["scan_id"])

    if not _table_exists("scan_action"):
        op.create_table(
            "scan_action",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("scan_id", sa.String(), nullable=False),
            sa.Column("client_id", sa.String(), nullable=False),
            sa.Column("methodology_version_set_id", sa.String(), nullable=False),
            sa.Column("action_key", sa.String(), nullable=False),
            sa.Column("title", sa.Text(), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("priority", sa.Text(), nullable=True),
            sa.Column("category", sa.Text(), nullable=True),
            sa.Column("effort", sa.Text(), nullable=True),
            sa.Column("impact_estimate", sa.Numeric(6, 3), nullable=True),
            sa.Column("score", sa.Numeric(8, 4), nullable=True),
            sa.Column("sort_order", sa.Integer(), nullable=True),
            sa.Column("action_role", sa.Text(), nullable=True),
            sa.Column("target_provider", sa.Text(), nullable=True),
            sa.Column("target_journey_stage", sa.Text(), nullable=True),
            sa.Column("target_questions_json", _json_type(), nullable=True),
            sa.Column("competing_sources_json", _json_type(), nullable=True),
            sa.Column("competing_competitors_json", _json_type(), nullable=True),
            sa.Column("evidence_json", _json_type(), nullable=True),
            sa.Column("status", sa.Text(), nullable=False, server_default="open"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["scan_id"], ["scan_runs.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("scan_id", "action_key", name="uq_scan_action_key"),
        )
    _create_index("ix_scan_action_scan", "scan_action", ["scan_id"])


def downgrade() -> None:
    # Phase 13 migrations are forward-only in local adoption tests.
    pass
