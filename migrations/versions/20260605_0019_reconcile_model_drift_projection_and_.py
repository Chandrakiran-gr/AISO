"""reconcile model drift: projection and integrity foreign keys, not-null

Brings the migration head back in lockstep with ``api.database`` /
``api.crawler.models`` after the schema drifted via ``create_all()``. All
changes were verified data-safe against the live DB before authoring:

- No NULLs in ``users.plan_tier`` / ``users.account_role`` /
  ``crawl_business_profiles.profile_status`` (NOT NULL is safe).
- No orphan rows for any of the added foreign keys.

The Gen-2 projection tables (scan_metric/scan_citation/scan_competitor/
scan_action/scan_question_result) were created in 0018 with ``client_id`` and
``methodology_version_set_id`` as plain columns; the models declare them as real
foreign keys. Their ``scan_id`` FK already carries ``ON DELETE CASCADE`` (0018),
which the models now also declare, so it is left untouched.

The ``classification`` unique key is intentionally NOT touched here: 0017 created
it as ``CREATE UNIQUE INDEX`` and the model now declares it as a unique Index to
match (functionally identical to a UniqueConstraint), keeping models == migrations.

Revision ID: 20260605_0019
Revises: 20260604_0018
Create Date: 2026-06-05 23:45:50.088841
"""

from alembic import op
import sqlalchemy as sa


revision = "20260605_0019"
down_revision = "20260604_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("content_drafts", schema=None) as batch_op:
        batch_op.create_foreign_key(
            "fk_content_drafts_source_action_id", "actions", ["source_action_id"], ["id"]
        )

    with op.batch_alter_table("crawl_business_profiles", schema=None) as batch_op:
        batch_op.alter_column("profile_status", existing_type=sa.VARCHAR(), nullable=False)
        batch_op.create_foreign_key(
            "fk_crawl_business_profiles_approved_by_user_id", "users", ["approved_by_user_id"], ["id"]
        )

    with op.batch_alter_table("scan_citations", schema=None) as batch_op:
        batch_op.create_foreign_key(
            "fk_scan_citations_source_profile_id", "source_profiles", ["source_profile_id"], ["id"]
        )

    # ── Gen-2 projection tables: promote client_id / methodology_version_set_id
    #    to real foreign keys. scan_id (ON DELETE CASCADE) is preserved as-is.
    for table in (
        "scan_action",
        "scan_citation",
        "scan_competitor",
        "scan_metric",
        "scan_question_result",
    ):
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.create_foreign_key(
                f"fk_{table}_client_id", "clients", ["client_id"], ["id"]
            )
            batch_op.create_foreign_key(
                f"fk_{table}_methodology_version_set_id",
                "methodology_version_set",
                ["methodology_version_set_id"],
                ["id"],
            )

    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.alter_column("plan_tier", existing_type=sa.VARCHAR(), nullable=False)
        batch_op.alter_column("account_role", existing_type=sa.VARCHAR(), nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.alter_column("account_role", existing_type=sa.VARCHAR(), nullable=True)
        batch_op.alter_column("plan_tier", existing_type=sa.VARCHAR(), nullable=True)

    for table in (
        "scan_action",
        "scan_citation",
        "scan_competitor",
        "scan_metric",
        "scan_question_result",
    ):
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.drop_constraint(f"fk_{table}_methodology_version_set_id", type_="foreignkey")
            batch_op.drop_constraint(f"fk_{table}_client_id", type_="foreignkey")

    with op.batch_alter_table("scan_citations", schema=None) as batch_op:
        batch_op.drop_constraint("fk_scan_citations_source_profile_id", type_="foreignkey")

    with op.batch_alter_table("crawl_business_profiles", schema=None) as batch_op:
        batch_op.drop_constraint("fk_crawl_business_profiles_approved_by_user_id", type_="foreignkey")
        batch_op.alter_column("profile_status", existing_type=sa.VARCHAR(), nullable=True)

    with op.batch_alter_table("content_drafts", schema=None) as batch_op:
        batch_op.drop_constraint("fk_content_drafts_source_action_id", type_="foreignkey")
