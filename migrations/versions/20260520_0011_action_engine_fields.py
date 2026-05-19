"""Add evidence-grounded fields to actions and content drafts.

Revision ID: 20260520_0011
Revises: 20260519_0010
Create Date: 2026-05-20
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260520_0011"
down_revision = "20260519_0010"
branch_labels = None
depends_on = None


def _has_column(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def upgrade() -> None:
    # ── Action: evidence-grounded fields for the new action engine ──
    action_columns = (
        ("remediation_type", sa.String()),
        ("target_questions_json", sa.Text()),
        ("target_providers_json", sa.Text()),
        ("evidence_summary", sa.Text()),
        ("impact_estimate", sa.Float()),
    )
    for column_name, column_type in action_columns:
        if not _has_column("actions", column_name):
            op.add_column("actions", sa.Column(column_name, column_type, nullable=True))

    # ── ContentDraft: action linkage, targeting, and export support ──
    draft_columns = (
        ("source_action_id", sa.String()),
        ("target_questions_json", sa.Text()),
        ("export_format", sa.String()),
        ("export_path", sa.Text()),
    )
    for column_name, column_type in draft_columns:
        if not _has_column("content_drafts", column_name):
            op.add_column("content_drafts", sa.Column(column_name, column_type, nullable=True))

    # Foreign key for source_action_id → actions.id
    # SQLite does not support ADD FOREIGN KEY, so we add the column only.
    # PostgreSQL production can add the constraint in a follow-up migration.


def downgrade() -> None:
    for column_name in ("export_path", "export_format", "target_questions_json", "source_action_id"):
        if _has_column("content_drafts", column_name):
            op.drop_column("content_drafts", column_name)

    for column_name in ("impact_estimate", "evidence_summary", "target_providers_json", "target_questions_json", "remediation_type"):
        if _has_column("actions", column_name):
            op.drop_column("actions", column_name)
