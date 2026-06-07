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

Alembic migrations are the single source of truth for the schema in **every**
environment, including local development. Set up or update any database with:

```bash
.venv/bin/alembic upgrade head
```

Implicit `create_all()` on app startup is **off by default**
(`AISO_AUTO_CREATE_TABLES=0`). It only ever creates *missing* tables and never
alters existing ones, so leaving it on silently drifts the live schema away from
the migrations. Enable it (`=1`) only for a throwaway local DB you don't care
about. A CI guard (`tests/test_migration_model_sync.py`) fails the build if the
models and migrations ever diverge again.

## Migrations

Run migrations from the repository root:

```bash
.venv/bin/alembic upgrade head
```

If your local `aiso.db` already exists because it was created before Alembic was
introduced, mark it as current after confirming the schema exists:

```bash
.venv/bin/alembic stamp head
```

Useful inspection commands:

```bash
.venv/bin/alembic current
.venv/bin/alembic history
```

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

## Referential Integrity & Delete Policy

Foreign keys are enforced in every environment. PostgreSQL does this natively;
SQLite does not unless `PRAGMA foreign_keys=ON` is set per connection, so the app
engine sets it via a connect-event listener in `api/database.py`. (The test suite
builds minimal fixtures on its own engines and relies on SQLite's lax default;
the delete policy is verified directly in `tests/test_db_integrity.py`.)

`ON DELETE` rules (migration `0020`):

| Behavior | Applies to | Effect |
| --- | --- | --- |
| `CASCADE` | client / scan / user / conversation-owned rows | Deleting the parent deletes the owned rows (e.g. deleting a client removes its scans, citations, actions, onboarding crawl tree, question bank, …). |
| `SET NULL` | optional cross-links: `content_drafts.conversation_id` / `.source_action_id` / `.reviewed_by`, `crawl_business_profiles.approved_by_user_id`, `scan_citations.source_profile_id`, `question_bridge.new_question_id`, `question_deprecation.replaced_by`, `question_bank_version.parent_version_id` | The owning row survives; only the reference is cleared. |
| `NO ACTION` (protected) | `scan_provenance.*` and every `methodology_version_set_id` reference | Immutable/compliance records: the parent cannot be deleted while referenced. `audit_event` has no FKs and is likewise immutable. |

Note: with FK enforcement on and **no** `relationship()` definitions yet, the ORM
does not infer parent-before-child insert ordering. Application flows that create
a parent and child in a single flush must add them in dependency order (the app's
per-step commits already do this).

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

- Add follow-up Alembic migrations for future schema changes.
- Add account-linking metadata if additional OAuth providers are introduced.
- Add object storage behind the artifact metadata contract.
- Add retention rules for local artifacts and expired scans.
