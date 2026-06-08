"""postgres parity: Gen-2 json -> jsonb, dedup approved_by_user_id FK

Two PostgreSQL-only corrections. They are no-ops on SQLite, which stores JSON as
TEXT and reflects foreign keys anonymously, so neither issue is visible there
(this is exactly why they slipped past the SQLite-based checks):

1. Several Gen-2 columns were created as plain ``json`` by migrations 0014-0018
   (their local ``_json_type`` had no JSONB variant), but the models intend
   JSONB. Convert them so the schema matches the models on PostgreSQL.

2. ``crawl_business_profiles.approved_by_user_id`` carries a DUPLICATE FK:
   migration 0007 created one (named ``..._users``) and the Phase-0 reconciliation
   (0019) added a second, because the SQLite ``alembic check`` did not see 0007's.
   Collapse to a single ``ON DELETE SET NULL`` foreign key.

Revision ID: 20260607_0029
Revises: 20260607_0028
Create Date: 2026-06-07 22:30:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260607_0029"
down_revision = "20260607_0028"
branch_labels = None
depends_on = None


def _json_type():
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


# Gen-2 columns created as plain `json` on PostgreSQL by 0014-0018; models want JSONB.
GEN2_JSON_COLUMNS = [
    ("domain_classification", "evidence"),
    ("scan_actions", "target_questions_json"),
    ("scan_actions", "competing_sources_json"),
    ("scan_actions", "competing_competitors_json"),
    ("scan_actions", "evidence_json"),
    ("scan_question_results", "cited_sources_json"),
    ("scan_question_results", "competitors_mentioned_json"),
]

# Same defensive cast as 0027/0028. These Gen-2 tables are empty today, but the
# safe cast keeps the conversion robust if they ever hold data on a future run.
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


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return  # SQLite already matches the models (JSON==TEXT; anonymous FKs)

    op.execute(SAFE_JSONB_DDL)
    for table, col in GEN2_JSON_COLUMNS:
        op.alter_column(
            table, col, existing_type=sa.JSON(), type_=_json_type(),
            existing_nullable=True, postgresql_using=f"pg_temp.safe_jsonb({col}::text)",
        )

    # Collapse any FK(s) on approved_by_user_id down to one canonical SET NULL FK.
    inspector = sa.inspect(bind)
    for fk in inspector.get_foreign_keys("crawl_business_profiles"):
        if fk.get("constrained_columns") == ["approved_by_user_id"] and fk.get("name"):
            op.drop_constraint(fk["name"], "crawl_business_profiles", type_="foreignkey")
    op.create_foreign_key(
        "fk_crawl_business_profiles_approved_by_user_id",
        "crawl_business_profiles", "users",
        ["approved_by_user_id"], ["id"], ondelete="SET NULL",
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return
    for table, col in GEN2_JSON_COLUMNS:
        op.alter_column(
            table, col, existing_type=_json_type(), type_=sa.JSON(),
            existing_nullable=True, postgresql_using=f"{col}::json",
        )
    # The duplicate FK was a defect; the consolidated single FK is left in place.
