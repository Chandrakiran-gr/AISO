"""Email verification + password reset.

Adds email-confirmation state to ``users`` (email_verified / verified_at) and a
one-time-code table (``email_auth_codes``) backing both the signup OTP and the
forgot-password flow. Existing accounts predate verification and are backfilled as
verified so they are not locked out of login.

Revision ID: 20260627_0034
Revises: 20260626_0033
Create Date: 2026-06-27 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260627_0034"
down_revision = "20260626_0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("users", sa.Column("verified_at", sa.DateTime(), nullable=True))
    # Existing accounts predate verification — mark them verified so login isn't blocked.
    op.execute("UPDATE users SET email_verified = true, verified_at = CURRENT_TIMESTAMP")
    op.create_table(
        "email_auth_codes",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("code_hash", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_email_auth_codes_user_purpose", "email_auth_codes", ["user_id", "purpose"])


def downgrade() -> None:
    op.drop_index("ix_email_auth_codes_user_purpose", table_name="email_auth_codes")
    op.drop_table("email_auth_codes")
    op.drop_column("users", "verified_at")
    op.drop_column("users", "email_verified")
