web: uvicorn api.main:app --host 0.0.0.0 --port ${PORT}
worker: procrastinate --app api.worker:app worker --concurrency 1
release: alembic upgrade head && procrastinate --app api.worker:app schema --apply
