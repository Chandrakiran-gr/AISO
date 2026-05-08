# AISO Staging / Private Beta Deployment

This guide deploys AISO for an early private beta, not hardened public
production.

Recommended staging stack:

- Frontend: Vercel, root directory `web`
- Backend: Railway web service from the repository root
- Database: Railway Postgres
- Artifact storage: Railway/local filesystem only for staging; move to S3/R2
  before relying on durable raw export downloads in production

## 1. Backend on Railway

Create a Railway project and add:

1. A Postgres service.
2. A web service connected to this repository.

Use the repository root for the backend service. `railway.json` configures:

```text
build: pip install -r api/requirements.txt -r requirements.txt
start: uvicorn api.main:app --host 0.0.0.0 --port ${PORT}
health: /api/v1/health
```

Set these Railway backend variables:

```env
ENV=staging
NODE_ENV=production
DATABASE_URL=<Railway Postgres public or private connection string>
AISO_AUTO_CREATE_TABLES=0
AISO_INTERNAL_API_SECRET=<strong random secret>
AUTH_SECRET=<same value as Vercel AUTH_SECRET or another strong shared secret>
AISO_ALLOWED_ORIGINS=https://<your-vercel-staging-domain>
AISO_ALLOWED_HOSTS=<your-railway-api-domain>,*.up.railway.app
AISO_ARTIFACT_ACCESS_EMAILS=admin@aisoglobal.com
AISO_INGEST_RENDERED=0
AISO_SOURCE_ENRICHMENT_ENABLED=1
AISO_SOURCE_ENRICHMENT_MAX_SOURCES=20
AISO_SOURCE_ENRICHMENT_TIMEOUT_SEC=5
AISO_SOURCE_ENRICHMENT_MAX_BYTES=1000000
AISO_SOURCE_ENRICHMENT_CONCURRENCY=3
```

For OneDrive artifact storage, generate the refresh token locally:

```bash
MICROSOFT_CLIENT_ID=<application-client-id> \
MICROSOFT_CLIENT_SECRET=<client-secret> \
MICROSOFT_TENANT=consumers \
.venv/bin/python scripts/onedrive_auth.py
```

Then add these Railway backend variables:

```env
AISO_STORAGE_BACKEND=onedrive
AISO_ONEDRIVE_BASE_PATH=/AISO
MICROSOFT_TENANT=consumers
MICROSOFT_CLIENT_ID=<application-client-id>
MICROSOFT_CLIENT_SECRET=<client-secret>
MICROSOFT_REFRESH_TOKEN=<refresh-token-from-helper>
```

Artifacts will be uploaded under:

```text
/AISO/clients/<client-slug>--<client-id-prefix>/scans/<scan-id>/
```

For managed Pro/Custom scans, also set provider keys on Railway:

```env
OPENAI_API_KEY=<managed key>
ANTHROPIC_API_KEY=<managed key>
PERPLEXITY_API_KEY=<managed key>
GOOGLE_AI_API_KEY=<managed key>
AISO_OPENAI_CONCURRENCY=5
AISO_CLAUDE_CONCURRENCY=5
AISO_PERPLEXITY_CONCURRENCY=3
AISO_GEMINI_CONCURRENCY=2
AISO_GEMINI_MIN_INTERVAL_SEC=0
```

Run migrations after Postgres is attached:

```bash
railway run alembic upgrade head
```

If using the Railway shell from the repo root, make sure the command sees the
same `DATABASE_URL` as the deployed backend.

## 2. Frontend on Vercel

Create a Vercel project from the same repository.

Set:

```text
Root Directory: web
Build Command: npm run build
Install Command: npm install
Output: default Next.js output
```

Set these Vercel variables:

```env
NODE_ENV=production
NEXT_PUBLIC_APP_URL=https://<your-vercel-staging-domain>
AUTH_URL=https://<your-vercel-staging-domain>/api/auth
AUTH_SECRET=<same value used for the backend auth secret>
AUTH_GOOGLE_ID=<google oauth client id>
AUTH_GOOGLE_SECRET=<google oauth secret>
AISO_INTERNAL_API_SECRET=<same value used by backend>
NEXT_PUBLIC_API_URL=https://<your-railway-api-domain>
AISO_API_URL=https://<your-railway-api-domain>
NEXT_PUBLIC_AISO_PLAN=free
NEXT_PUBLIC_AISO_ARTIFACT_ACCESS_EMAILS=admin@aisoglobal.com
```

`AISO_API_URL` is server-only and is the preferred value for the Next.js proxy.
`NEXT_PUBLIC_API_URL` is kept for compatibility and should point to the same
Railway backend.

## 3. Google OAuth

In Google Cloud Console, add the staging callback:

```text
https://<your-vercel-staging-domain>/api/auth/callback/google
```

For local development, keep:

```text
http://localhost:3000/api/auth/callback/google
```

## 4. Private Beta Operating Notes

- Keep the staging URL private.
- Do not enable public billing flows from staging.
- Do not store BYOK provider keys in database rows, logs, or artifacts.
- Keep `AISO_AUTO_CREATE_TABLES=0` and use Alembic migrations.
- Keep `AISO_INGEST_RENDERED=0` unless the Railway service has Chromium
  installed and monitored.
- Raw CSV/JSONL exports on Railway local disk are acceptable only for staging.
  They can disappear across redeploys depending on service storage behavior.

## 5. Smoke Test

After both services are deployed:

```bash
curl https://<your-railway-api-domain>/api/v1/health
```

Then verify in the Vercel app:

1. Sign up or sign in with `admin@aisoglobal.com`.
2. Create a business through onboarding.
3. Confirm context.
4. Launch a small scan with one provider.
5. Check dashboard, scan history, responses/proof, and action plan.

## 6. Before Public Production

Before public launch, add:

- Durable object storage for artifacts, preferably S3/R2.
- Real entitlement and billing enforcement.
- Route-level rate limiting that preserves Auth.js JSON contracts.
- Production logging/monitoring/alerts.
- Backup and restore process for Postgres.
- Strong domain/CSP settings for the final production domain.
- Secrets manager workflow for managed provider keys.
