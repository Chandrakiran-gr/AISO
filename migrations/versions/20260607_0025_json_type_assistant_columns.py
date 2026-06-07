"""phase 3 (batch 3a): assistant Text-JSON columns -> JSON

conversations.summary_json, messages.metadata_json, content_drafts.target_questions_json
move to the JSON type (JSONB on PostgreSQL). Reads go through the (now
pass-through-aware) _safe_json_loads helpers; writes assign dicts/lists directly.

Revision ID: 20260607_0025
Revises: 20260607_0024
Create Date: 2026-06-07 01:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260607_0025"
down_revision = "20260607_0024"
branch_labels = None
depends_on = None


def _json_type():
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


COLUMNS = [
    ("conversations", "summary_json"),
    ("messages", "metadata_json"),
    ("content_drafts", "target_questions_json"),
]


def upgrade() -> None:
    for table, col in COLUMNS:
        with op.batch_alter_table(table, schema=None) as batch:
            batch.alter_column(col, existing_type=sa.Text(), type_=_json_type(),
                               existing_nullable=True, postgresql_using=f"{col}::jsonb")


def downgrade() -> None:
    for table, col in COLUMNS:
        with op.batch_alter_table(table, schema=None) as batch:
            batch.alter_column(col, existing_type=_json_type(), type_=sa.Text(),
                               existing_nullable=True, postgresql_using=f"{col}::text")
