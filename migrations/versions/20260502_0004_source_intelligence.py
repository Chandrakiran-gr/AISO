"""Add source intelligence profile metadata.

Revision ID: 20260502_0004
Revises: 20260427_0003
Create Date: 2026-05-02
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260502_0004"
down_revision = "20260427_0003"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def _has_column(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def _has_index(table_name: str, index_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(index["name"] == index_name for index in inspector.get_indexes(table_name))


def _add_column(table_name: str, column: sa.Column) -> None:
    if not _has_column(table_name, column.name):
        op.add_column(table_name, column)


def upgrade() -> None:
    if not _has_table("source_profiles"):
        op.create_table(
            "source_profiles",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("client_id", sa.String(), sa.ForeignKey("clients.id"), nullable=False),
            sa.Column("canonical_url", sa.Text(), nullable=False),
            sa.Column("source_domain", sa.String(), nullable=True),
            sa.Column("source_title", sa.Text(), nullable=True),
            sa.Column("owner_type", sa.String(), nullable=True),
            sa.Column("source_type", sa.String(), nullable=True),
            sa.Column("action_role", sa.String(), nullable=True),
            sa.Column("actionability_score", sa.Float(), nullable=True),
            sa.Column("influence_score", sa.Float(), nullable=True),
            sa.Column("relevance_score", sa.Float(), nullable=True),
            sa.Column("client_mentioned", sa.Boolean(), nullable=True),
            sa.Column("competitors_mentioned_json", sa.Text(), nullable=True),
            sa.Column("topics_json", sa.Text(), nullable=True),
            sa.Column("fetch_status", sa.String(), nullable=True),
            sa.Column("last_fetched_at", sa.DateTime(), nullable=True),
            sa.Column("last_enriched_at", sa.DateTime(), nullable=True),
            sa.Column("classification_reason", sa.Text(), nullable=True),
            sa.Column("metadata_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )

    indexes = [
        ("ix_source_profiles_client_id", ["client_id"], False),
        ("ix_source_profiles_client_domain", ["client_id", "source_domain"], False),
        ("ix_source_profiles_owner", ["client_id", "owner_type"], False),
        ("ix_source_profiles_action_role", ["client_id", "action_role"], False),
        ("ix_source_profiles_source_type", ["client_id", "source_type"], False),
        ("ix_source_profiles_client_url", ["client_id", "canonical_url"], True),
    ]
    for index_name, columns, unique in indexes:
        if not _has_index("source_profiles", index_name):
            op.create_index(index_name, "source_profiles", columns, unique=unique)

    if _has_table("scan_citations"):
        _add_column("scan_citations", sa.Column("source_profile_id", sa.String(), nullable=True))
        _add_column("scan_citations", sa.Column("canonical_url", sa.Text(), nullable=True))
        _add_column("scan_citations", sa.Column("citation_origin", sa.String(), nullable=True))
        _add_column("scan_citations", sa.Column("cited_text", sa.Text(), nullable=True))
        _add_column("scan_citations", sa.Column("web_search_used", sa.Boolean(), nullable=True))
        _add_column("scan_citations", sa.Column("source_type", sa.String(), nullable=True))
        _add_column("scan_citations", sa.Column("owner_type", sa.String(), nullable=True))
        _add_column("scan_citations", sa.Column("action_role", sa.String(), nullable=True))
        _add_column("scan_citations", sa.Column("actionability_score", sa.Float(), nullable=True))
        _add_column("scan_citations", sa.Column("influence_score", sa.Float(), nullable=True))
        _add_column("scan_citations", sa.Column("relevance_score", sa.Float(), nullable=True))
        _add_column("scan_citations", sa.Column("confidence_score", sa.Float(), nullable=True))
        _add_column("scan_citations", sa.Column("classification_reason", sa.Text(), nullable=True))
        if not _has_index("scan_citations", "ix_scan_citations_source_profile_id"):
            op.create_index("ix_scan_citations_source_profile_id", "scan_citations", ["source_profile_id"])


def downgrade() -> None:
    if _has_table("scan_citations"):
        if _has_index("scan_citations", "ix_scan_citations_source_profile_id"):
            op.drop_index("ix_scan_citations_source_profile_id", table_name="scan_citations")
        for column_name in (
            "classification_reason",
            "confidence_score",
            "relevance_score",
            "influence_score",
            "actionability_score",
            "action_role",
            "owner_type",
            "source_type",
            "web_search_used",
            "cited_text",
            "citation_origin",
            "canonical_url",
            "source_profile_id",
        ):
            if _has_column("scan_citations", column_name):
                op.drop_column("scan_citations", column_name)

    if _has_table("source_profiles"):
        for index_name in (
            "ix_source_profiles_client_url",
            "ix_source_profiles_source_type",
            "ix_source_profiles_action_role",
            "ix_source_profiles_owner",
            "ix_source_profiles_client_domain",
            "ix_source_profiles_client_id",
        ):
            if _has_index("source_profiles", index_name):
                op.drop_index(index_name, table_name="source_profiles")
        op.drop_table("source_profiles")

