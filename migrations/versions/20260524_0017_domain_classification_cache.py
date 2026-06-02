"""Add source classifier domain cache.

Revision ID: 20260524_0017
Revises: 20260524_0016
Create Date: 2026-05-24 00:17:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260524_0017"
down_revision = "20260524_0016"
branch_labels = None
depends_on = None


def _json_type():
    return sa.JSON().with_variant(sa.JSON(), "sqlite")


def _table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def _create_index(index_name: str, table_name: str, columns: list[str]) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {index["name"] for index in inspector.get_indexes(table_name)}
    if index_name not in existing:
        op.create_index(index_name, table_name, columns)


def _create_unique_index(index_name: str, table_name: str, columns: list[str]) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {index["name"] for index in inspector.get_indexes(table_name)}
    if index_name not in existing:
        op.create_index(index_name, table_name, columns, unique=True)


def _retarget_sample_scan_fk_to_scan_runs() -> None:
    if not _table_exists("sample"):
        return
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    constraint_name = bind.execute(
        sa.text(
            """
            SELECT conname
            FROM pg_constraint
            WHERE conrelid = 'sample'::regclass
              AND contype = 'f'
              AND pg_get_constraintdef(oid) LIKE '%scan_provenance%'
            LIMIT 1
            """
        )
    ).scalar()
    if constraint_name:
        op.drop_constraint(constraint_name, "sample", type_="foreignkey")
    existing_scan_run_fk = bind.execute(
        sa.text(
            """
            SELECT conname
            FROM pg_constraint
            WHERE conrelid = 'sample'::regclass
              AND contype = 'f'
              AND pg_get_constraintdef(oid) LIKE '%scan_runs%'
            LIMIT 1
            """
        )
    ).scalar()
    if not existing_scan_run_fk:
        op.create_foreign_key(
            "fk_sample_scan_run",
            "sample",
            "scan_runs",
            ["scan_id"],
            ["id"],
            ondelete="CASCADE",
        )


def upgrade() -> None:
    _retarget_sample_scan_fk_to_scan_runs()

    if not _table_exists("scan_raw_response_archive"):
        op.create_table(
            "scan_raw_response_archive",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("scan_id", sa.String(), nullable=False),
            sa.Column("archive_type", sa.Text(), nullable=False),
            sa.Column("sample_count", sa.Integer(), nullable=False),
            sa.Column("archive_url", sa.Text(), nullable=False),
            sa.Column("archive_hash", sa.LargeBinary(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["scan_id"], ["scan_runs.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("scan_id", "archive_type", name="uq_scan_raw_response_archive_type"),
        )
    _create_index("ix_scan_raw_response_archive_scan", "scan_raw_response_archive", ["scan_id"])

    if not _table_exists("domain_classification"):
        op.create_table(
            "domain_classification",
            sa.Column("domain", sa.Text(), primary_key=True),
            sa.Column("classifier_version", sa.Text(), primary_key=True),
            sa.Column("source_class", sa.Text(), nullable=False),
            sa.Column("classifier_model", sa.Text(), nullable=False),
            sa.Column("prompt_hash", sa.LargeBinary(), nullable=True),
            sa.Column("confidence", sa.Numeric(5, 4), nullable=False, server_default="0"),
            sa.Column("source", sa.Text(), nullable=False),
            sa.Column("evidence", _json_type(), nullable=True),
            sa.Column("expires_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
    _create_index("ix_domain_classification_expires_at", "domain_classification", ["expires_at"])
    if _table_exists("classification"):
        _create_unique_index(
            "uq_classification_sample_type_version",
            "classification",
            ["sample_id", "classifier_type", "classifier_version"],
        )


def downgrade() -> None:
    # Phase 13 migrations are forward-only in local adoption tests; keep the
    # downgrade no-op to avoid destructive cache loss during iterative rollout.
    pass
