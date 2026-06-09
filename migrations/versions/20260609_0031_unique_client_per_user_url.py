"""Enforce one business per (user, url): UNIQUE index on clients(user_id, url).

The permanent database backstop for the duplicate-business bug (the re-scan flow
used to mint a new Client every run). Together with the per-user business-count
trigger (0030) and the application's upsert-by-identity, a duplicate business is
now rejected by the database regardless of the calling code path.

Prerequisite: NO existing ``(user_id, url)`` duplicates. Run
``python scripts/consolidate_duplicate_clients.py --apply`` first. ``upgrade``
guards on this and fails loudly (rather than with a cryptic unique violation) if
duplicates remain.

Revision ID: 20260609_0031
Revises: 20260608_0030
Create Date: 2026-06-09 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260609_0031"
down_revision = "20260608_0030"
branch_labels = None
depends_on = None

_INDEX = "uq_clients_user_url"


def _index_exists() -> bool:
    inspector = sa.inspect(op.get_bind())
    return _INDEX in {ix["name"] for ix in inspector.get_indexes("clients")}


def upgrade() -> None:
    bind = op.get_bind()
    remaining = bind.execute(
        sa.text(
            "SELECT count(*) FROM "
            "(SELECT 1 FROM clients GROUP BY user_id, url HAVING count(*) > 1) AS dupes"
        )
    ).scalar() or 0
    if remaining:
        raise RuntimeError(
            f"{remaining} duplicate (user_id, url) client group(s) still exist. "
            "Run `python scripts/consolidate_duplicate_clients.py --apply` "
            "(after a backup) before applying this migration."
        )
    if not _index_exists():
        op.create_index(_INDEX, "clients", ["user_id", "url"], unique=True)


def downgrade() -> None:
    if _index_exists():
        op.drop_index(_INDEX, table_name="clients")
