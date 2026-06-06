# Phase 13 Go-Live — Deployment Runbook (Railway)

This is the **"you apply"** half of Phase 0. The code is committed; these steps
stand up the worker and flip production to the Phase 13 engine on **Railway**.
Nothing here is destructive until Step 5 (deleting the `production` branch).

> Phase 13 requires **PostgreSQL** (the Procrastinate queue cannot run on
> SQLite) and a **separate worker process** to execute scans. Without the
> worker, scans enqueue but never run.

The frontend (Vercel) needs no change for Phase 0.

---

## 1. One-time: DB migrations + queue schema

Against the **production Postgres** `DATABASE_URL`:

```bash
railway run alembic upgrade head
railway run procrastinate --app api.worker:app schema --apply   # idempotent; creates procrastinate_* tables
```

> ⚠️ Run these at **deploy time, not build time** — they need a live Postgres
> connection. Do **not** put them in a Nixpacks `Procfile` `release:` line: Railway
> runs that during the image build (no `DATABASE_URL`), which fails the build.
> Use `railway run …` (above) against the linked project, or a Railway
> **pre-deploy command** on the service (Settings → Deploy → Pre-deploy Command),
> which runs in the deploy environment with env vars present.

---

## 2. Environment variables (API service)

```
AISO_SCAN_ENGINE=phase13      # master switch; code default is "legacy"
```

**Tier routing — important.** `AISO_SCAN_ENGINE=phase13` is a *master switch*, not a
global cutover. Scans are routed **per client tier**:
- **Paid tier** (`Client.tier` ≠ `"free"`) → Phase 13 engine (server-side keys).
- **Free tier** (the default) → legacy engine, using the user's **own BYOK keys**.

So a free user never consumes your API budget. To put a client on Phase 13, set its
`tier` to a paid value (e.g. `pro`). To **test** Phase 13, set a test client's tier:
```sql
UPDATE clients SET tier = 'pro' WHERE id = '<your-test-client-id>';
```
Setting `AISO_SCAN_ENGINE=legacy` is the kill-switch — everyone back to legacy.

These must already be present (the worker needs them too — Step 3):
`DATABASE_URL` (Postgres), `ANTHROPIC_API_KEY` (required — the classifier runs on
Claude; add `OPENAI_API_KEY`/`PERPLEXITY_API_KEY`/`GOOGLE_AI_API_KEY` for those
providers), `AISO_AUDIT_HMAC_KEY`, `AISO_STORAGE_BACKEND`, `AISO_STORAGE_ROOT`.

---

## 3. Add the worker service (Railway)

1. Railway dashboard → your project → **New → Service → from the same repo**.
2. Service **Settings → Start Command**:
   `procrastinate --app api.worker:app worker --concurrency 1`
   Build command unchanged: `pip install -r api/requirements.txt -r requirements.txt`.
3. Service **Variables**: give the worker the **same** variables as the API service —
   at minimum `DATABASE_URL`, all provider keys, `AISO_AUDIT_HMAC_KEY`,
   `AISO_STORAGE_BACKEND`, `AISO_STORAGE_ROOT`. (The worker calls the providers
   and signs provenance, so it needs the keys.) Reference the same Postgres plugin
   so `DATABASE_URL` matches the API.
4. Set the worker's deploy **branch = `main`**.
5. Deploy. Watch logs for `Starting worker on queues ...`.

> The API and worker are two Railway services in one project sharing one Postgres.
> Both deploy from `main`.

---

## 4. Confirm the API deploys from `main`

API service → **Settings → Source → Branch = `main`** (the unused `production`
branch is being retired in Step 5).

---

## 5. Verify end-to-end

1. Run a scan through the app (onboarding → launch), or:
   ```bash
   curl -X POST https://<api>/api/v1/clients/<client_id>/scans \
     -H 'Content-Type: application/json' -H 'X-User-Id: <user>' \
     -d '{"client_id":"<client_id>","providers":["openai","claude"],"groups":["G1","G2"]}'
   ```
2. Watch the **worker service logs** — the saga runs (sampling → provider calls →
   classification → AVS → publish).
3. Poll `GET /api/v1/clients/<client_id>/scans/<scan_id>` → `pending → complete`
   (or `failed`).
4. Dashboard `/metrics` shows a real AVS with confidence intervals.

> Phase 1 (native gap-report / actions / citations on Phase 13 data) is separate;
> until it lands, gap-report/actions read the legacy path and may be sparse for
> Phase 13 scans. Expected during the transition.

---

## 5b. (Optional) Backfill the dashboard projection for old scans

New scans materialize the dashboard projection automatically. To populate it for
scans published before this rollout (so their gap-report/actions show up under
`phase13`):

```bash
python scripts/backfill_phase13_projection.py --dry-run   # preview
python scripts/backfill_phase13_projection.py             # materialize missing
```

Run with the prod `DATABASE_URL` exported (e.g. `railway run`).

---

## 6. Retire the `production` branch (after Steps 1–5 verified)

Nothing references `production` anymore (Render config removed; Railway deploys
from `main`):

```bash
git push origin --delete production
git branch -D production   # local, if present
```

---

## Rollback

Instant revert to the legacy engine with no code redeploy:

```
AISO_SCAN_ENGINE=legacy
```

Set it on the API service and restart. Scans return to `run_pipeline`. The worker
can keep running (it just receives no new jobs).

---

## Known gap

BYOK (bring-your-own-key) is **not** propagated to the worker-run saga in Phase 0
— Phase 13 scans use server-managed provider keys. If a user submits BYOK keys to
a Phase 13 scan they are ignored. BYOK-over-queue is a separate design.
