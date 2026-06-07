"""phase 4: drop dead scan_analysis, rename clients.competitors -> competitor_names

- scan_analysis: never populated (no producer) and its only reader (the assistant
  scan-history summaries) always returned empty; dropped along with that dead code.
- clients.competitors -> competitor_names: disambiguates the competitor NAMES store
  from clients.competitor_domains (domains). The API field stays "competitors".

Uses native RENAME COLUMN (SQLite >= 3.25 and PostgreSQL) so the heavily
referenced ``clients`` table is not recreated. The drop is guarded so it is
idempotent for a create_all-adopt database that never had the table.

Revision ID: 20260606_0022
Revises: 20260606_0021
Create Date: 2026-06-06 15:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260606_0022"
down_revision = "20260606_0021"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    op.alter_column("clients", "competitors", new_column_name="competitor_names")
    if _has_table("scan_analysis"):
        op.drop_table("scan_analysis")


def downgrade() -> None:
    op.alter_column("clients", "competitor_names", new_column_name="competitors")
    if not _has_table("scan_analysis"):
        op.create_table(
            "scan_analysis",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("client_id", sa.String(), nullable=False),
            sa.Column("scan_id", sa.String(), nullable=False),
            sa.Column("provider", sa.String(), nullable=True),
            sa.Column("group", sa.String(), nullable=True),
            sa.Column("analysis_type", sa.String(), nullable=False, server_default="visibility_summary"),
            sa.Column("summary", sa.Text(), nullable=True),
            sa.Column("strengths_json", sa.Text(), nullable=True),
            sa.Column("weaknesses_json", sa.Text(), nullable=True),
            sa.Column("recommendations_json", sa.Text(), nullable=True),
            sa.Column("raw_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["scan_id"], ["scans.id"], ondelete="CASCADE"),
        )
        op.create_index("ix_scan_analysis_client_scan", "scan_analysis", ["client_id", "scan_id"])
        op.create_index("ix_scan_analysis_scope", "scan_analysis", ["provider", "group"])
