"""Per-user tier backfill + client business-limit trigger (EXPAND).

Part of moving subscription tier from per-client to per-user:

- Backfill ``users.plan_tier`` / ``account_role``: admin emails (``AISO_ADMIN_EMAILS``)
  -> ``custom`` / ``admin``; everyone else -> ``free`` (existing users keep their
  own BYOK keys on the legacy engine until they upgrade).
- Install a PostgreSQL ``BEFORE INSERT`` trigger on ``clients`` enforcing the
  per-user business-count limit (free/pro = 1, custom = unlimited). SQLite has no
  trigger; the app-level check in ``api/client_limits.py`` covers it there.

The new-user default (``free``) is the model's Python-side default in
``api/database.py`` — ``users.plan_tier`` has no DB server_default, so there is
nothing to alter here.

This is the EXPAND half of an expand/contract change: it deliberately does NOT
touch ``clients.tier`` (dropped later in 0031, once the code that stopped reading
it is fully live).

Revision ID: 20260608_0030
Revises: 20260607_0029
Create Date: 2026-06-08 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

from api.entitlements import configured_admin_emails


revision = "20260608_0030"
down_revision = "20260607_0029"
branch_labels = None
depends_on = None


_USERS = sa.table(
    "users",
    sa.column("email", sa.String()),
    sa.column("plan_tier", sa.String()),
    sa.column("account_role", sa.String()),
)


# BEFORE INSERT trigger: the per-user business-count limit varies by the owner's
# tier, so it must JOIN users.plan_tier — only a trigger can express that (a
# unique index / exclusion constraint cannot). The advisory lock serializes
# concurrent inserts for the same owner so two requests can't both pass the
# count check; it is released automatically at transaction end.
_CLIENT_LIMIT_FUNCTION = """
CREATE OR REPLACE FUNCTION enforce_client_business_limit() RETURNS trigger AS $fn$
DECLARE
    v_plan  text;
    v_count int;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtext(NEW.user_id));

    SELECT lower(coalesce(plan_tier, 'free')) INTO v_plan FROM users WHERE id = NEW.user_id;
    v_plan := coalesce(v_plan, 'free');

    IF v_plan = 'custom' THEN
        RETURN NEW;  -- unlimited businesses
    END IF;

    -- free and pro both allow a single business.
    SELECT count(*) INTO v_count FROM clients WHERE user_id = NEW.user_id;
    IF v_count >= 1 THEN
        RAISE EXCEPTION 'client_business_limit_exceeded: user=% plan=%', NEW.user_id, v_plan
            USING ERRCODE = 'P0LIM';
    END IF;

    RETURN NEW;
END;
$fn$ LANGUAGE plpgsql;
"""

_CLIENT_LIMIT_TRIGGER = """
DROP TRIGGER IF EXISTS trg_client_business_limit ON clients;
CREATE TRIGGER trg_client_business_limit
    BEFORE INSERT ON clients
    FOR EACH ROW EXECUTE FUNCTION enforce_client_business_limit();
"""


def upgrade() -> None:
    bind = op.get_bind()

    # 1) Backfill tiers — set-based, case-insensitive, idempotent. All dialects.
    admin_emails = sorted(configured_admin_emails())
    if admin_emails:
        op.execute(
            _USERS.update()
            .where(sa.func.lower(_USERS.c.email).in_(admin_emails))
            .values(plan_tier="custom", account_role="admin")
        )
        op.execute(
            _USERS.update()
            .where(~sa.func.lower(_USERS.c.email).in_(admin_emails))
            .values(plan_tier="free")
        )
    else:
        op.execute(_USERS.update().values(plan_tier="free"))

    # 2) PostgreSQL business-limit trigger (the hard guarantee). SQLite relies on
    #    the app-level pre-check in api/client_limits.py.
    if bind.dialect.name == "postgresql":
        op.execute(_CLIENT_LIMIT_FUNCTION)
        op.execute(_CLIENT_LIMIT_TRIGGER)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_client_business_limit ON clients;")
        op.execute("DROP FUNCTION IF EXISTS enforce_client_business_limit();")
    # Backfilled tier values are intentionally left as-is on downgrade.
