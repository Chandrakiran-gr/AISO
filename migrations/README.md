# AISO Database Migrations

Alembic manages durable schema changes for SQLite local development and
PostgreSQL production.

Common commands:

```bash
.venv/bin/alembic upgrade head
.venv/bin/alembic current
.venv/bin/alembic history
```

If an existing local `aiso.db` was already created with SQLAlchemy
`create_all()`, run:

```bash
.venv/bin/alembic stamp head
```

Fresh databases should use `upgrade head`.
