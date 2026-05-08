"""Add user entitlement metadata.

Revision ID: 20260508_0005
Revises: 20260502_0004
Create Date: 2026-05-08
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260508_0005"
down_revision = "20260502_0004"
branch_labels = None
depends_on = None


def _has_column(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def upgrade() -> None:
    if not _has_column("users", "plan_tier"):
        op.add_column("users", sa.Column("plan_tier", sa.String(), nullable=True))
    if not _has_column("users", "account_role"):
        op.add_column("users", sa.Column("account_role", sa.String(), nullable=True))

    users = sa.table(
        "users",
        sa.column("plan_tier", sa.String()),
        sa.column("account_role", sa.String()),
    )
    op.execute(users.update().where(users.c.plan_tier.is_(None)).values(plan_tier="pro"))
    op.execute(users.update().where(users.c.account_role.is_(None)).values(account_role="user"))

    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        op.alter_column("users", "plan_tier", nullable=False, existing_type=sa.String())
        op.alter_column("users", "account_role", nullable=False, existing_type=sa.String())


def downgrade() -> None:
    if _has_column("users", "account_role"):
        op.drop_column("users", "account_role")
    if _has_column("users", "plan_tier"):
        op.drop_column("users", "plan_tier")
