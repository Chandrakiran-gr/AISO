"""Initial AISO schema.

Revision ID: 20260425_0001
Revises:
Create Date: 2026-04-25
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260425_0001"
down_revision = None
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def _has_index(table_name: str, index_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(
        index["name"] == index_name for index in inspector.get_indexes(table_name)
    )


def _create_index(
    index_name: str,
    table_name: str,
    columns: list[str],
    *,
    unique: bool = False,
) -> None:
    if not _has_index(table_name, index_name):
        op.create_index(index_name, table_name, columns, unique=unique)


def upgrade() -> None:
    if not _has_table("users"):
        op.create_table(
            "users",
            sa.Column("id", sa.String(), primary_key=True, nullable=False),
            sa.Column("email", sa.String(), nullable=False),
            sa.Column("name", sa.String(), nullable=True),
            sa.Column("password_hash", sa.String(), nullable=True),
            sa.Column("provider", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=True),
        )
    _create_index("ix_users_email", "users", ["email"], unique=True)

    if not _has_table("clients"):
        op.create_table(
            "clients",
            sa.Column("id", sa.String(), primary_key=True, nullable=False),
            sa.Column("user_id", sa.String(), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("url", sa.String(), nullable=False),
            sa.Column("industry", sa.String(), nullable=True),
            sa.Column("location", sa.String(), nullable=True),
            sa.Column("competitors", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        )
    _create_index("ix_clients_user_id", "clients", ["user_id"])

    if not _has_table("scans"):
        op.create_table(
            "scans",
            sa.Column("id", sa.String(), primary_key=True, nullable=False),
            sa.Column("client_id", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=True),
            sa.Column("providers", sa.Text(), nullable=True),
            sa.Column("groups", sa.Text(), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["client_id"], ["clients.id"]),
        )
    _create_index("ix_scans_client_id", "scans", ["client_id"])

    if not _has_table("scan_results"):
        op.create_table(
            "scan_results",
            sa.Column("id", sa.String(), primary_key=True, nullable=False),
            sa.Column("scan_id", sa.String(), nullable=False),
            sa.Column("client_id", sa.String(), nullable=False),
            sa.Column("provider", sa.String(), nullable=False),
            sa.Column("group", sa.String(), nullable=False),
            sa.Column("total_questions", sa.Integer(), nullable=True),
            sa.Column("mention_count", sa.Integer(), nullable=True),
            sa.Column("avg_position", sa.Float(), nullable=True),
            sa.Column("visibility_score", sa.Float(), nullable=True),
            sa.Column("competitor_data", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["client_id"], ["clients.id"]),
            sa.ForeignKeyConstraint(["scan_id"], ["scans.id"]),
        )
    _create_index("ix_scan_results_client_id", "scan_results", ["client_id"])
    _create_index("ix_scan_results_scan_id", "scan_results", ["scan_id"])

    if not _has_table("scan_artifacts"):
        op.create_table(
            "scan_artifacts",
            sa.Column("id", sa.String(), primary_key=True, nullable=False),
            sa.Column("client_id", sa.String(), nullable=False),
            sa.Column("scan_id", sa.String(), nullable=True),
            sa.Column("artifact_type", sa.String(), nullable=False),
            sa.Column("file_format", sa.String(), nullable=True),
            sa.Column("storage_backend", sa.String(), nullable=False),
            sa.Column("storage_path", sa.Text(), nullable=False),
            sa.Column("original_filename", sa.String(), nullable=True),
            sa.Column("mime_type", sa.String(), nullable=True),
            sa.Column("size_bytes", sa.BigInteger(), nullable=True),
            sa.Column("sha256", sa.String(), nullable=True),
            sa.Column("metadata_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["client_id"], ["clients.id"]),
            sa.ForeignKeyConstraint(["scan_id"], ["scans.id"]),
        )
    _create_index("ix_scan_artifacts_client_id", "scan_artifacts", ["client_id"])
    _create_index("ix_scan_artifacts_scan_id", "scan_artifacts", ["scan_id"])
    _create_index(
        "ix_scan_artifacts_client_scan",
        "scan_artifacts",
        ["client_id", "scan_id"],
    )
    _create_index("ix_scan_artifacts_type", "scan_artifacts", ["artifact_type"])

    if not _has_table("scan_analysis"):
        op.create_table(
            "scan_analysis",
            sa.Column("id", sa.String(), primary_key=True, nullable=False),
            sa.Column("client_id", sa.String(), nullable=False),
            sa.Column("scan_id", sa.String(), nullable=False),
            sa.Column("provider", sa.String(), nullable=True),
            sa.Column("group", sa.String(), nullable=True),
            sa.Column("analysis_type", sa.String(), nullable=False),
            sa.Column("summary", sa.Text(), nullable=True),
            sa.Column("strengths_json", sa.Text(), nullable=True),
            sa.Column("weaknesses_json", sa.Text(), nullable=True),
            sa.Column("recommendations_json", sa.Text(), nullable=True),
            sa.Column("raw_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["client_id"], ["clients.id"]),
            sa.ForeignKeyConstraint(["scan_id"], ["scans.id"]),
        )
    _create_index("ix_scan_analysis_client_id", "scan_analysis", ["client_id"])
    _create_index("ix_scan_analysis_scan_id", "scan_analysis", ["scan_id"])
    _create_index(
        "ix_scan_analysis_client_scan",
        "scan_analysis",
        ["client_id", "scan_id"],
    )
    _create_index("ix_scan_analysis_scope", "scan_analysis", ["provider", "group"])

    if not _has_table("scan_citations"):
        op.create_table(
            "scan_citations",
            sa.Column("id", sa.String(), primary_key=True, nullable=False),
            sa.Column("client_id", sa.String(), nullable=False),
            sa.Column("scan_id", sa.String(), nullable=False),
            sa.Column("provider", sa.String(), nullable=False),
            sa.Column("group", sa.String(), nullable=True),
            sa.Column("question", sa.Text(), nullable=True),
            sa.Column("answer_excerpt", sa.Text(), nullable=True),
            sa.Column("citation_url", sa.Text(), nullable=False),
            sa.Column("citation_title", sa.Text(), nullable=True),
            sa.Column("source_domain", sa.String(), nullable=True),
            sa.Column("source_rank", sa.Integer(), nullable=True),
            sa.Column("metadata_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["client_id"], ["clients.id"]),
            sa.ForeignKeyConstraint(["scan_id"], ["scans.id"]),
        )
    _create_index("ix_scan_citations_client_id", "scan_citations", ["client_id"])
    _create_index("ix_scan_citations_scan_id", "scan_citations", ["scan_id"])
    _create_index(
        "ix_scan_citations_client_scan",
        "scan_citations",
        ["client_id", "scan_id"],
    )
    _create_index(
        "ix_scan_citations_provider_group",
        "scan_citations",
        ["provider", "group"],
    )
    _create_index("ix_scan_citations_domain", "scan_citations", ["source_domain"])

    if not _has_table("actions"):
        op.create_table(
            "actions",
            sa.Column("id", sa.String(), primary_key=True, nullable=False),
            sa.Column("client_id", sa.String(), nullable=False),
            sa.Column("scan_id", sa.String(), nullable=True),
            sa.Column("title", sa.String(), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("priority", sa.String(), nullable=True),
            sa.Column("category", sa.String(), nullable=True),
            sa.Column("impact_pts", sa.String(), nullable=True),
            sa.Column("effort", sa.String(), nullable=True),
            sa.Column("status", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["client_id"], ["clients.id"]),
            sa.ForeignKeyConstraint(["scan_id"], ["scans.id"]),
        )
    _create_index("ix_actions_client_id", "actions", ["client_id"])


def downgrade() -> None:
    for table_name in (
        "actions",
        "scan_citations",
        "scan_analysis",
        "scan_artifacts",
        "scan_results",
        "scans",
        "clients",
        "users",
    ):
        if _has_table(table_name):
            op.drop_table(table_name)
