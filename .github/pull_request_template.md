<!--
AISO PR template — Phase 0 SDLC hardening.
Fill every section. PRs into `main` are reviewed by QA (evidence gate) and depth-reviewed before merge.
Keep one branch = one PR (see BRANCHING.md).
-->

## What
<!-- One-line summary of the change. -->

## Why
<!-- The problem / motivation. Link the task or issue. -->

## How tested
<!-- Commands run + result. Backend: pytest (incl. phase12/phase13 where touched), against Postgres via TEST_DATABASE_URL for parity. Frontend: build + typecheck. Paste/attach the relevant output. -->

## Evidence
<!-- CI run link, test output, staging URL, screenshots. "Released for merge" requires posted evidence, not assertions. -->

## Scope
<!-- Confirm the diff touches only what this PR claims. List the files/areas. -->

## Guardrail checklist (AISO hard guardrails — tick each)
- [ ] **BYOK zero-persistence** — no user LLM API key written to DB, logs, or files (keys stay in-memory / subprocess env only).
- [ ] **Proxy-only** — frontend reaches FastAPI only via the Next secure proxy `/api/proxy/[...path]`; no client-side direct backend calls.
- [ ] **No secrets committed** — no keys/tokens/.env values added (gitleaks clean).
- [ ] **No destructive / migration-on-real-data** actions without explicit owner approval.
- [ ] **Migrations** (if any) are backward-compatible (expand/contract) and reversible (`upgrade`+`downgrade` tested on SQLite + Postgres).

## Rollback
<!-- How to revert this safely: revert-the-merge PR + redeploy; for DB changes, the rollback path (expand/contract; downgrade only when safe). -->

---
<!-- Merge gate (see BRANCHING.md): merges to `main` require a green CI run, QA's evidence-backed "Released for merge", and the repo owner's explicit approval. -->
