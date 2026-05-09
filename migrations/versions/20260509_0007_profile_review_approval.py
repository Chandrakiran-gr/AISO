"""Add profile review and approval columns.

Revision ID: 20260509_0007
Revises: 20260509_0006
Create Date: 2026-05-09
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260509_0007"
down_revision = "20260509_0006"
branch_labels = None
depends_on = None


def _has_column(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(col["name"] == column_name for col in inspector.get_columns(table_name))


def _has_fk(table_name: str, constraint_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(fk.get("name") == constraint_name for fk in inspector.get_foreign_keys(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    if not _has_column("crawl_business_profiles", "profile_status"):
        op.add_column(
            "crawl_business_profiles",
            sa.Column("profile_status", sa.String(), nullable=True),
        )
        # Backfill existing rows.
        profiles = sa.table("crawl_business_profiles", sa.column("profile_status", sa.String()))
        op.execute(profiles.update().where(profiles.c.profile_status.is_(None)).values(profile_status="draft_extracted"))

        if bind.dialect.name != "sqlite":
            op.alter_column("crawl_business_profiles", "profile_status", nullable=False, existing_type=sa.String())

    if not _has_column("crawl_business_profiles", "approved_at"):
        op.add_column(
            "crawl_business_profiles",
            sa.Column("approved_at", sa.DateTime(), nullable=True),
        )

    if not _has_column("crawl_business_profiles", "approved_by_user_id"):
        op.add_column(
            "crawl_business_profiles",
            sa.Column("approved_by_user_id", sa.String(), nullable=True),
        )
    if bind.dialect.name != "sqlite" and not _has_fk(
        "crawl_business_profiles",
        "fk_crawl_business_profiles_approved_by_user_id_users",
    ):
        op.create_foreign_key(
            "fk_crawl_business_profiles_approved_by_user_id_users",
            "crawl_business_profiles",
            "users",
            ["approved_by_user_id"],
            ["id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "sqlite" and _has_fk(
        "crawl_business_profiles",
        "fk_crawl_business_profiles_approved_by_user_id_users",
    ):
        op.drop_constraint(
            "fk_crawl_business_profiles_approved_by_user_id_users",
            "crawl_business_profiles",
            type_="foreignkey",
        )
    for col in ("approved_by_user_id", "approved_at", "profile_status"):
        if _has_column("crawl_business_profiles", col):
            op.drop_column("crawl_business_profiles", col)
