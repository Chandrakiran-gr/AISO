"""phase 3 (batch 3b): client_contexts Text-JSON columns -> JSON

client_contexts.profile_json / evidence_json / warnings_json -> JSON type
(JSONB on PostgreSQL). Reads go through the pass-through-aware _safe_json_loads
helpers; writes (client_context route, crawler worker/route, pipeline read)
assign/consume dicts and lists directly.

Revision ID: 20260607_0026
Revises: 20260607_0025
Create Date: 2026-06-07 01:30:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260607_0026"
down_revision = "20260607_0025"
branch_labels = None
depends_on = None


def _json_type():
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


COLUMNS = ["profile_json", "evidence_json", "warnings_json"]


def upgrade() -> None:
    with op.batch_alter_table("client_contexts", schema=None) as batch:
        for col in COLUMNS:
            batch.alter_column(col, existing_type=sa.Text(), type_=_json_type(),
                               existing_nullable=True, postgresql_using=f"{col}::jsonb")


def downgrade() -> None:
    with op.batch_alter_table("client_contexts", schema=None) as batch:
        for col in COLUMNS:
            batch.alter_column(col, existing_type=_json_type(), type_=sa.Text(),
                               existing_nullable=True, postgresql_using=f"{col}::text")
