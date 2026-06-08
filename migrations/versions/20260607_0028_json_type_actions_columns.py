"""phase 3 (batch 4b): actions Text-JSON columns -> JSON

actions.evidence_json / target_questions_json / target_providers_json -> JSON
type (JSONB on PostgreSQL). The action engine normalizes its data-dict values to
structures (via _json_or_none) when creating Action rows; reads use the
pass-through _safe_json helpers; and the ActionResponse API model re-serializes
these fields to JSON strings (mode="before" validator) to keep the response
contract (Optional[str]) unchanged for the frontend.

``actions`` is populated, so (like 0027) we cast via the session-local
``pg_temp.safe_jsonb`` so any empty/non-JSON legacy value becomes NULL rather than
aborting the migration.

Revision ID: 20260607_0028
Revises: 20260607_0027
Create Date: 2026-06-07 02:30:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260607_0028"
down_revision = "20260607_0027"
branch_labels = None
depends_on = None


def _json_type():
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


SAFE_JSONB_DDL = """
CREATE OR REPLACE FUNCTION pg_temp.safe_jsonb(t text) RETURNS jsonb AS $fn$
BEGIN
    IF t IS NULL OR btrim(t) = '' THEN
        RETURN NULL;
    END IF;
    RETURN t::jsonb;
EXCEPTION WHEN others THEN
    RETURN NULL;
END;
$fn$ LANGUAGE plpgsql;
"""


COLUMNS = ["evidence_json", "target_questions_json", "target_providers_json"]


def upgrade() -> None:
    is_pg = op.get_bind().dialect.name == "postgresql"
    if is_pg:
        op.execute(SAFE_JSONB_DDL)
    with op.batch_alter_table("actions", schema=None) as batch:
        for col in COLUMNS:
            using = f"pg_temp.safe_jsonb({col})" if is_pg else None
            batch.alter_column(col, existing_type=sa.Text(), type_=_json_type(),
                               existing_nullable=True, postgresql_using=using)


def downgrade() -> None:
    with op.batch_alter_table("actions", schema=None) as batch:
        for col in COLUMNS:
            batch.alter_column(col, existing_type=_json_type(), type_=sa.Text(),
                               existing_nullable=True, postgresql_using=f"{col}::text")
