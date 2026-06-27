"""Drop dead columns (bucket-1 schema hygiene).

Removes five columns that are unused by production code and empty in production
(verified before applying):

- ``clients.tier`` — dead; tier is authoritative on ``users.plan_tier``. The
  column even used a different, drift-prone vocabulary (free/pro/growth/scale/
  enterprise vs the real free/pro/custom) and nothing reads it.
- ``clients.byok`` / ``clients.byok_keys`` — never read or written; BYOK keys are
  passed in-memory per request and never persisted, so the columns are unused
  (and a latent security smell). Confirmed empty in production.
- ``content_drafts.export_path`` — "reserved for future" CDN/S3 export, never used.
- ``content_drafts.target_questions_json`` — dead on content_drafts (the live
  ``target_questions_json`` lives on ``actions``). Confirmed empty in production.

Scope note: Gen-2 / question-bank / Phase-13 projection columns are intentionally
NOT touched here. They belong to the parked Phase 13 engine and its unfinished
read path; dropping them now would break the Gen-2 release. They are deferred to
the Gen-2 release.

Revision ID: 20260626_0033
Revises: 20260609_0032
Create Date: 2026-06-26 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260626_0033"
down_revision = "20260609_0032"
branch_labels = None
depends_on = None


def _json_type():
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    with op.batch_alter_table("clients") as batch_op:
        batch_op.drop_column("tier")
        batch_op.drop_column("byok")
        batch_op.drop_column("byok_keys")
    with op.batch_alter_table("content_drafts") as batch_op:
        batch_op.drop_column("export_path")
        batch_op.drop_column("target_questions_json")


def downgrade() -> None:
    with op.batch_alter_table("clients") as batch_op:
        batch_op.add_column(sa.Column("tier", sa.String(), nullable=False, server_default="free"))
        batch_op.add_column(sa.Column("byok", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("byok_keys", _json_type(), nullable=True))
    with op.batch_alter_table("content_drafts") as batch_op:
        batch_op.add_column(sa.Column("target_questions_json", _json_type(), nullable=True))
        batch_op.add_column(sa.Column("export_path", sa.Text(), nullable=True))
