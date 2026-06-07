"""phase 3 (batch 4a): legacy scan data Text-JSON columns -> JSON

scans.providers/groups, scan_results.competitor_data, scan_citations.metadata_json,
source_profiles.competitors_mentioned_json/topics_json/metadata_json,
scan_artifacts.metadata_json -> JSON type (JSONB on PostgreSQL). Producers in
full_stack/scan_metrics.py, source_enrichment.py and routes/pipeline.py now write
lists/dicts; reads go through the pass-through-aware _safe_json/_json_loads helpers.

(scans.error is intentionally left as Text — it holds plain text or JSON.)

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
    for table, col in COLUMNS:
        with op.batch_alter_table(table, schema=None) as batch:
            batch.alter_column(col, existing_type=sa.Text(), type_=_json_type(),
                               existing_nullable=True, postgresql_using=f"{col}::jsonb")


def downgrade() -> None:
    for table, col in COLUMNS:
        with op.batch_alter_table(table, schema=None) as batch:
            batch.alter_column(col, existing_type=_json_type(), type_=sa.Text(),
                               existing_nullable=True, postgresql_using=f"{col}::text")
