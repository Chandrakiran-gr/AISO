"""phase 3 (batch 1): clients.competitor_names Text -> JSON

Pilot of the JSON-as-Text -> JSON normalization. On SQLite JSON is stored as
TEXT so existing JSON-string values keep working (the ORM now parses them on
read); on PostgreSQL the column becomes JSONB (validation + queryability). The
``postgresql_using`` cast converts the existing text values to jsonb.

Revision ID: 20260607_0023
Revises: 20260606_0022
Create Date: 2026-06-07 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260607_0023"
down_revision = "20260606_0022"
branch_labels = None
depends_on = None


def _json_type():
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    with op.batch_alter_table("clients", schema=None) as batch:
        batch.alter_column(
            "competitor_names",
            existing_type=sa.Text(),
            type_=_json_type(),
            existing_nullable=True,
            postgresql_using="competitor_names::jsonb",
        )


def downgrade() -> None:
    with op.batch_alter_table("clients", schema=None) as batch:
        batch.alter_column(
            "competitor_names",
            existing_type=_json_type(),
            type_=sa.Text(),
            existing_nullable=True,
            postgresql_using="competitor_names::text",
        )
