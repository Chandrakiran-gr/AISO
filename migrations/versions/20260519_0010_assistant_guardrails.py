"""Add assistant guardrails metadata and rate limit events.

Revision ID: 20260519_0010
Revises: 20260519_0009
Create Date: 2026-05-19
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260519_0010"
down_revision = "20260519_0009"
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


def upgrade() -> None:
    if not _has_column("conversations", "summary_json"):
        op.add_column("conversations", sa.Column("summary_json", sa.Text(), nullable=True))

    if not _has_table("assistant_rate_limit_events"):
        op.create_table(
            "assistant_rate_limit_events",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("user_id", sa.String(), nullable=False),
            sa.Column("event_type", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    indexes = (
        ("ix_assistant_rate_limit_events_user_id", ["user_id"]),
        ("ix_assistant_rate_limit_events_created_at", ["created_at"]),
        ("ix_assistant_rate_limit_user_event_created", ["user_id", "event_type", "created_at"]),
    )
    for index_name, columns in indexes:
        if not _has_index("assistant_rate_limit_events", index_name):
            op.create_index(index_name, "assistant_rate_limit_events", columns)


def downgrade() -> None:
    if _has_table("assistant_rate_limit_events"):
        for index_name in (
            "ix_assistant_rate_limit_user_event_created",
            "ix_assistant_rate_limit_events_created_at",
            "ix_assistant_rate_limit_events_user_id",
        ):
            if _has_index("assistant_rate_limit_events", index_name):
                op.drop_index(index_name, table_name="assistant_rate_limit_events")
        op.drop_table("assistant_rate_limit_events")

    if _has_column("conversations", "summary_json"):
        op.drop_column("conversations", "summary_json")
