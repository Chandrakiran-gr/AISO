"""Procrastinate worker entrypoint for the Phase 13 scan saga.

The API process (uvicorn) only *defers* scan jobs onto the Procrastinate
queue; a separate worker process must consume them and run the orchestrated
saga (sampling → provider calls → classification → AVS → projection → publish).

Run the worker with:

    procrastinate worker --app api.worker:app --concurrency 1

This requires a PostgreSQL ``DATABASE_URL`` (or ``PROCRASTINATE_DATABASE_URL``);
the queue cannot run on SQLite. The worker and the API-side executor register
the same task name/queue against the same database, so deferred jobs are
picked up here.
"""

from __future__ import annotations

from api.adapters.scan_execution import build_procrastinate_app

# Module-level ``app`` is what the ``procrastinate worker --app`` CLI imports.
# ``_task`` is registered as a side effect of construction; we keep a reference
# so linters don't flag it as unused.
app, _task = build_procrastinate_app()


__all__ = ["app"]
