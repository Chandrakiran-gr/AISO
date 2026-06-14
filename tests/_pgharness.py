"""Test database harness: SQLite by default, real Postgres on demand.

Most tests historically ran on in-memory SQLite, which does NOT enforce foreign
keys — so production-only integrity bugs (FK insert-ordering, etc.) passed in CI
and broke in prod. Set ``TEST_DATABASE_URL`` to a Postgres URL and the same tests
run prod-faithfully (FKs enforced, JSONB/types/constraints identical).

Provisioning the Postgres instance is left to the caller/CI (e.g. spin a cluster
and export ``TEST_DATABASE_URL``) — doing it in-process under pytest proved
unreliable. Usage in a test's ``setUp``:

    from tests._pgharness import make_test_engine, reset_schema
    self.engine = make_test_engine()
    reset_schema(self.engine)
"""

from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

# Import every model module so all tables are registered on Base.metadata.
import api.database as _database  # noqa: F401
import api.crawler.models  # noqa: F401
from api.database import Base


def using_postgres() -> bool:
    return bool(os.environ.get("TEST_DATABASE_URL"))


def make_test_engine():
    """Postgres engine when TEST_DATABASE_URL is set, else in-memory SQLite."""
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        return create_engine(url)
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def reset_schema(engine) -> None:
    """Give a test a clean schema.

    On shared Postgres this drops and recreates every table (per-test isolation);
    on a fresh in-memory SQLite engine the drop is a no-op and create builds it.
    """
    if using_postgres():
        Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
