"""Defer signup persistence until email is verified.

Adds ``pending_signups``, which holds a credentials-account signup (hashed password
+ hashed OTP) until the email OTP is verified. The real ``users`` row is created
only on verification, so the users table holds only verified accounts.

Also removes legacy *unverified* credentials accounts left over from the previous
flow (which created a users row at signup). Those rows squatted the email yet could
never log in (login requires a verified email); deleting them frees the address so
the owner can sign up again into the new pending-verification flow. Unverified
accounts have no clients/scans (login is blocked before onboarding), so the cascade
clears only their ``email_auth_codes``. OAuth accounts are pre-verified and untouched.

Revision ID: 20260627_0035
Revises: 20260627_0034
Create Date: 2026-06-27 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260627_0035"
down_revision = "20260627_0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pending_signups",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("code_hash", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("send_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("window_started_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("last_sent_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_pending_signups_email", "pending_signups", ["email"], unique=True)

    # Free emails squatted by legacy unverified credentials accounts so their owners
    # can re-signup into the new flow. Boolean param adapts to the backend dialect.
    op.get_bind().execute(
        sa.text(
            "DELETE FROM users WHERE provider = 'credentials' AND email_verified = :unverified"
        ),
        {"unverified": False},
    )


def downgrade() -> None:
    op.drop_index("ix_pending_signups_email", table_name="pending_signups")
    op.drop_table("pending_signups")
