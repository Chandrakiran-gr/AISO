"""Add hash-chained methodology prompt versions.

Revision ID: 20260522_0013
Revises: 20260522_0012
Create Date: 2026-05-22
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260522_0013"
down_revision = "20260522_0012"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    if _table_exists("methodology_prompt_version"):
        return
    op.create_table(
        "methodology_prompt_version",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("prompt_key", sa.String(), nullable=False),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("prompt_text", sa.Text(), nullable=False),
        sa.Column("prompt_hash", sa.String(), nullable=False),
        sa.Column("prev_chain_hash", sa.String(), nullable=False),
        sa.Column("chain_hash", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "prompt_key",
            "version",
            "prompt_hash",
            name="uq_methodology_prompt_version_hash",
        ),
    )
    op.create_index("ix_methodology_prompt_version_key", "methodology_prompt_version", ["prompt_key"])


def downgrade() -> None:
    if _table_exists("methodology_prompt_version"):
        op.drop_table("methodology_prompt_version")
