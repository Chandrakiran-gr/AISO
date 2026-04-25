# AISO Database Foundation

AISO uses SQLAlchemy with SQLite for local development and PostgreSQL for
production. The app database stores durable product records, structured scan
results, citations, analysis, and metadata for generated files. It should not be
used as the primary binary file bucket.

## Current Backend

Local development defaults to:

```env
DATABASE_URL=sqlite:///./aiso.db
```

Production should use PostgreSQL:

```env
DATABASE_URL=postgresql://user:password@host:5432/aiso
```

FastAPI initializes tables on startup through `api.database.init_db()`. This is
acceptable for the current local phase. Before production, add Alembic
migrations so schema changes are explicit, reviewable, and reversible.

## Core Tables

| Table | Purpose |
| --- | --- |
| `users` | Platform users persisted from Google OAuth and email/password signup. |
| `clients` | Businesses being tracked by a user. |
| `scans` | Pipeline runs for a client. |
| `scan_results` | Aggregated provider/group visibility metrics. |
| `scan_artifacts` | Metadata for generated or uploaded data/report files. |
| `scan_analysis` | Structured summaries, strengths, weaknesses, and recommendations. |
| `scan_citations` | Source-level evidence cited by AI providers. |
| `actions` | Future user-facing recommendation tasks. |

## File Storage Strategy

For now, generated files can live on local disk under a deterministic structure:

```text
storage/
  clients/
    {client_id}/
      scans/
        {scan_id}/
          raw/
            responses.csv
            citations.xlsx
          processed/
            analysis.json
```

The database stores only metadata:

```text
artifact_type
file_format
storage_backend
storage_path
original_filename
mime_type
size_bytes
sha256
metadata_json
```

This keeps the current setup free of infrastructure cost while making a future
S3 move straightforward. In that future state, only `storage_backend` and
`storage_path` need to change, for example:

```text
storage_backend = s3
storage_path = clients/{client_id}/scans/{scan_id}/raw/responses.csv
```

## Security Rules

- Never store BYOK provider API keys in any table or artifact metadata.
- Store email/password account passwords only as salted password hashes.
- Protect server-to-server OAuth user upserts with `AISO_INTERNAL_API_SECRET`
  in production.
- Scope every client, scan, artifact, analysis row, and citation row through
  `client_id` and, where applicable, `scan_id`.
- Keep the Next.js proxy as the only browser path to FastAPI so backend access
  remains tied to the authenticated session.
- Store file hashes for integrity checks, but do not store file contents in the
  relational database unless there is a future explicit reason.

## Production Hardening Still Needed

- Add Alembic migrations.
- Add account-linking metadata if additional OAuth providers are introduced.
- Add object storage behind the artifact metadata contract.
- Add cascade/delete policy for client-owned records.
- Add retention rules for local artifacts and expired scans.
