"""Add client context profiles.

Revision ID: 20260427_0003
Revises: 20260427_0002
Create Date: 2026-04-27
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260427_0003"
down_revision = "20260427_0002"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def _has_index(table_name: str, index_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(index["name"] == index_name for index in inspector.get_indexes(table_name))


def upgrade() -> None:
    if not _has_table("client_contexts"):
        op.create_table(
            "client_contexts",
            sa.Column("client_id", sa.String(), sa.ForeignKey("clients.id"), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="not_started"),
            sa.Column("profile_json", sa.Text(), nullable=True),
            sa.Column("evidence_json", sa.Text(), nullable=True),
            sa.Column("warnings_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("client_id"),
        )

    if not _has_index("client_contexts", "ix_client_contexts_status"):
        op.create_index("ix_client_contexts_status", "client_contexts", ["status"])


def downgrade() -> None:
    if not _has_table("client_contexts"):
        return

    if _has_index("client_contexts", "ix_client_contexts_status"):
        op.drop_index("ix_client_contexts_status", table_name="client_contexts")
    op.drop_table("client_contexts")
