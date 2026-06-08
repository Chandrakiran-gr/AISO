"""phase 3 (batch 4a): legacy scan data Text-JSON columns -> JSON

scans.providers/groups, scan_results.competitor_data, scan_citations.metadata_json,
source_profiles.competitors_mentioned_json/topics_json/metadata_json,
scan_artifacts.metadata_json -> JSON type (JSONB on PostgreSQL). Producers in
full_stack/scan_metrics.py, source_enrichment.py and routes/pipeline.py now write
lists/dicts; reads go through the pass-through-aware _safe_json/_json_loads helpers.

(scans.error is intentionally left as Text — it holds plain text or JSON.)

These are POPULATED legacy tables (e.g. scan_citations ~1.5k rows) and some rows
hold values a plain ``::jsonb`` cast rejects — empty strings or non-JSON legacy
text — which made the deploy fail with ``invalid input syntax for type json``
(surfacing as an SSL EOF on the managed Postgres). We therefore cast via a
session-local ``pg_temp.safe_jsonb`` that maps NULL/empty/invalid text to NULL
instead of aborting the whole migration.

Revision ID: 20260607_0027
Revises: 20260607_0026
Create Date: 2026-06-07 02:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260607_0027"
down_revision = "20260607_0026"
branch_labels = None
depends_on = None


def _json_type():
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


# Session-local cast that never aborts on malformed legacy text: NULL/empty/invalid
# values become SQL NULL (the app's pass-through JSON readers already treat those as
# "missing"). Idempotent across migrations that share the same connection/transaction.
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


COLUMNS = [
    ("scans", "providers"),
    ("scans", "groups"),
    ("scan_results", "competitor_data"),
    ("scan_citations", "metadata_json"),
    ("source_profiles", "competitors_mentioned_json"),
    ("source_profiles", "topics_json"),
    ("source_profiles", "metadata_json"),
]
# Note: scan_artifacts.metadata_json stays Text — its value is a storage-layer
# pre-serialized JSON string (opaque blob), not app-queried structured data.


def upgrade() -> None:
    is_pg = op.get_bind().dialect.name == "postgresql"
    if is_pg:
        op.execute(SAFE_JSONB_DDL)
    for table, col in COLUMNS:
        using = f"pg_temp.safe_jsonb({col})" if is_pg else None
        with op.batch_alter_table(table, schema=None) as batch:
            batch.alter_column(col, existing_type=sa.Text(), type_=_json_type(),
                               existing_nullable=True, postgresql_using=using)


def downgrade() -> None:
    for table, col in COLUMNS:
        with op.batch_alter_table(table, schema=None) as batch:
            batch.alter_column(col, existing_type=_json_type(), type_=sa.Text(),
                               existing_nullable=True, postgresql_using=f"{col}::text")
