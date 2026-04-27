"""Add action plan recommendation metadata.

Revision ID: 20260427_0002
Revises: 20260425_0001
Create Date: 2026-04-27
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260427_0002"
down_revision = "20260425_0001"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def _has_column(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(
        column["name"] == column_name
        for column in inspector.get_columns(table_name)
    )


def _has_index(table_name: str, index_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(
        index["name"] == index_name for index in inspector.get_indexes(table_name)
    )


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    if not _has_column(table_name, column.name):
        op.add_column(table_name, column)


def _create_index_if_missing(
    index_name: str,
    table_name: str,
    columns: list[str],
    *,
    unique: bool = False,
) -> None:
    if not _has_index(table_name, index_name):
        op.create_index(index_name, table_name, columns, unique=unique)


def upgrade() -> None:
    if not _has_table("actions"):
        return

    _add_column_if_missing("actions", sa.Column("action_key", sa.String(), nullable=True))
    _add_column_if_missing("actions", sa.Column("score", sa.Float(), nullable=True))
    _add_column_if_missing("actions", sa.Column("sort_order", sa.Integer(), nullable=True))
    _add_column_if_missing("actions", sa.Column("evidence_json", sa.Text(), nullable=True))

    _create_index_if_missing(
        "ix_actions_client_scan",
        "actions",
        ["client_id", "scan_id"],
    )
    _create_index_if_missing("ix_actions_status", "actions", ["status"])
    _create_index_if_missing(
        "ix_actions_scan_key",
        "actions",
        ["scan_id", "action_key"],
        unique=True,
    )


def downgrade() -> None:
    if not _has_table("actions"):
        return

    for index_name in (
        "ix_actions_scan_key",
        "ix_actions_status",
        "ix_actions_client_scan",
    ):
        if _has_index("actions", index_name):
            op.drop_index(index_name, table_name="actions")

    for column_name in ("evidence_json", "sort_order", "score", "action_key"):
        if _has_column("actions", column_name):
            op.drop_column("actions", column_name)
