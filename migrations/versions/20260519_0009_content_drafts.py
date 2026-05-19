"""Add assistant content drafts.

Revision ID: 20260519_0009
Revises: 20260518_0008
Create Date: 2026-05-19
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260519_0009"
down_revision = "20260518_0008"
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
    if not _has_table("content_drafts"):
        op.create_table(
            "content_drafts",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("conversation_id", sa.String(), nullable=True),
            sa.Column("client_id", sa.String(), nullable=False),
            sa.Column("created_by", sa.String(), nullable=False),
            sa.Column("content_type", sa.String(), nullable=False),
            sa.Column("title", sa.String(), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("reviewed_by", sa.String(), nullable=True),
            sa.Column("reviewed_at", sa.DateTime(), nullable=True),
            sa.Column("review_notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["client_id"], ["clients.id"]),
            sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"]),
            sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
            sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    indexes = (
        ("ix_content_drafts_client_id", ["client_id"]),
        ("ix_content_drafts_created_by", ["created_by"]),
        ("ix_content_drafts_client_status", ["client_id", "status"]),
        ("ix_content_drafts_conversation", ["conversation_id"]),
    )
    for index_name, columns in indexes:
        if not _has_index("content_drafts", index_name):
            op.create_index(index_name, "content_drafts", columns)


def downgrade() -> None:
    if not _has_table("content_drafts"):
        return

    for index_name in (
        "ix_content_drafts_conversation",
        "ix_content_drafts_client_status",
        "ix_content_drafts_created_by",
        "ix_content_drafts_client_id",
    ):
        if _has_index("content_drafts", index_name):
            op.drop_index(index_name, table_name="content_drafts")

    op.drop_table("content_drafts")
