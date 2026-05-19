"""Add assistant conversations and messages.

Revision ID: 20260518_0008
Revises: 20260509_0007
Create Date: 2026-05-18
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260518_0008"
down_revision = "20260509_0007"
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
    if not _has_table("conversations"):
        op.create_table(
            "conversations",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("client_id", sa.String(), nullable=False),
            sa.Column("user_id", sa.String(), nullable=False),
            sa.Column("title", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.Column("archived_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["client_id"], ["clients.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    if not _has_index("conversations", "ix_conversations_client_id"):
        op.create_index("ix_conversations_client_id", "conversations", ["client_id"])
    if not _has_index("conversations", "ix_conversations_user_id"):
        op.create_index("ix_conversations_user_id", "conversations", ["user_id"])
    if not _has_index("conversations", "ix_conversations_client_user"):
        op.create_index("ix_conversations_client_user", "conversations", ["client_id", "user_id"])
    if not _has_index("conversations", "ix_conversations_archived"):
        op.create_index("ix_conversations_archived", "conversations", ["archived_at"])

    if not _has_table("messages"):
        op.create_table(
            "messages",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("conversation_id", sa.String(), nullable=False),
            sa.Column("role", sa.String(), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("metadata_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    if not _has_index("messages", "ix_messages_conversation_id"):
        op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])
    if not _has_index("messages", "ix_messages_conversation_created"):
        op.create_index("ix_messages_conversation_created", "messages", ["conversation_id", "created_at"])
    if not _has_index("messages", "ix_messages_role"):
        op.create_index("ix_messages_role", "messages", ["role"])


def downgrade() -> None:
    for table_name, indexes in (
        (
            "messages",
            (
                "ix_messages_role",
                "ix_messages_conversation_created",
                "ix_messages_conversation_id",
            ),
        ),
        (
            "conversations",
            (
                "ix_conversations_archived",
                "ix_conversations_client_user",
                "ix_conversations_user_id",
                "ix_conversations_client_id",
            ),
        ),
    ):
        if not _has_table(table_name):
            continue
        for index_name in indexes:
            if _has_index(table_name, index_name):
                op.drop_index(index_name, table_name=table_name)

    if _has_table("messages"):
        op.drop_table("messages")
    if _has_table("conversations"):
        op.drop_table("conversations")
