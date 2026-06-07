"""phase 3 (batch 2): crawler Text-JSON columns -> JSON

Converts the onboarding-crawler JSON-as-Text columns to the proper JSON type
(JSONB on PostgreSQL). Reads now funnel through _safe_json_loads (which accepts
already-parsed values) and writes pass lists/dicts directly instead of _dump_json.

Revision ID: 20260607_0024
Revises: 20260607_0023
Create Date: 2026-06-07 00:30:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260607_0024"
down_revision = "20260607_0023"
branch_labels = None
depends_on = None


def _json_type():
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


# (table, column, nullable)
COLUMNS = [
    ("onboarding_workspaces", "allowed_domains", False),
    ("crawl_jobs", "warnings", True),
    ("crawl_pages", "extraction_summary", True),
    ("crawl_business_profiles", "products", True),
    ("crawl_business_profiles", "services", True),
    ("crawl_business_profiles", "locations", True),
    ("crawl_business_profiles", "contacts", True),
    ("crawl_business_profiles", "social_links", True),
    ("crawl_business_profiles", "important_pages", True),
    ("crawl_business_profiles", "missing_fields", True),
    ("kb_chunks", "metadata_json", True),
]


def upgrade() -> None:
    for table, col, nullable in COLUMNS:
        with op.batch_alter_table(table, schema=None) as batch:
            batch.alter_column(
                col,
                existing_type=sa.Text(),
                type_=_json_type(),
                existing_nullable=nullable,
                postgresql_using=f"{col}::jsonb",
            )


def downgrade() -> None:
    for table, col, nullable in COLUMNS:
        with op.batch_alter_table(table, schema=None) as batch:
            batch.alter_column(
                col,
                existing_type=_json_type(),
                type_=sa.Text(),
                existing_nullable=nullable,
                postgresql_using=f"{col}::text",
            )
