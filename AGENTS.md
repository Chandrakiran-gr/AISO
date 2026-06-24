# AISO - Agent Instructions

Common instructions for any agent (Claude Code, Codex, Cursor) working on AISO,
a B2B platform that measures brand visibility across AI answer engines
(ChatGPT, Claude, Perplexity, Gemini).

## Working Agreement
- Read the relevant code before you write. Treat AISO_Codex_Handoff.md as architectural truth.
- Do not commit or push unless asked. First summarize the diff and what you validated, then wait for explicit approval.
- Commit messages never list the AI agent as co-author.
- Branch per BRANCHING.md. Never push to main (see CONTRIBUTING.md).
- Ask before irreversible actions: deleting files, dropping tables, purging env or config.
- After any change: self-review the diff, run validation, then report what changed, what you validated, and commit status.

## Conventions
- Never use the em dash. Use a plain dash instead.
- Never hand-edit CHANGELOG.md or any file marked as auto-generated.
- When writing or substantially editing long Markdown, put each full sentence on its own line.
  Preserve normal Markdown structure, but do not wrap multiple sentences onto one physical line.

## Engineering Standards
- When making technical decisions, do not give much weight to development cost or speed.
  Instead, prefer quality, simplicity, robustness, scalability, and long-term maintainability.
- Fix bugs by reproducing them end-to-end first, as close as possible to how a real user hits them (onboarding -> scan -> dashboard), before changing code.
- Cover the real user flow with end-to-end tests, not just unit tests.
  A unit test that mocks the database, executor, or provider can pass while the integrated onboarding -> scan -> dashboard path 500s in production, which is exactly how the FK-insert-ordering bugs shipped.
- Hold the line: if you see a lint error, test failure, or flaky test, fix it even when it is unrelated to your task.
- Be picky about the UI. The aesthetic is premium dark-mode glassmorphism driven by globals.css variables. If something looks off, get it fixed.

## AISO House Rules (hard-won - do not relearn these in production)
- Postgres is the source of truth. Validate migrations and tests on Postgres, not SQLite. SQLite silently hides DROP CONSTRAINT, JSON-vs-JSONB, FK-name, and FK-insert-ordering failures. Tests default to SQLite; set TEST_DATABASE_URL to run them prod-faithfully (FKs enforced) via the harness in tests/_pgharness.py.
- FK insert ordering. Models carry bare ForeignKey columns with few relationship()s, and prod sessions use autoflush=False, so the unit of work can INSERT a child row before its parent in one flush and 500 on Postgres. Flush the parent before adding child rows. New tests must run with FK enforcement ON and autoflush=False.
- Migrations must be idempotent and must never raise. Prod auto-runs `alembic upgrade head` on deploy, so a raising migration fails the deploy. Guard seed inserts with an existence check.
- Scans run for minutes. Use background tasks (Procrastinate) plus client-side polling, never a synchronous request that waits for the scan.
- Never persist or log user API keys. BYOK keys are in-memory only, passed to subprocesses as env vars, then destroyed.
- Free tier never spends server keys. Free -> legacy engine plus BYOK. Pro and custom -> Phase 13 engine plus managed keys.
- One business per user. A re-scan reuses the existing profile and never creates a new one.
- The frontend never calls FastAPI directly. Always go through the Next.js proxy (/api/proxy/[...path]), which attaches X-User-Id.

## Stack
- Frontend: Next.js 16 (App Router, Turbopack), React 19, vanilla CSS Modules. Do NOT install TailwindCSS.
- Backend: FastAPI (Python 3.14), SQLAlchemy ORM, Alembic migrations.
- Database: Postgres in prod (source of truth); SQLite locally for convenience only.
- Async: Procrastinate worker queue. Deploy: Railway (API plus Worker plus Postgres). Auth: NextAuth v5 via proxy.ts.

## Repo Map
- api/ - Phase 13 scan engine (paid tiers, managed provider keys): scan_runs, scan_bridge, scan_execution, adapters, routes.
- full_stack/ - legacy Gen-1 scan engine (free tier, BYOK): collect.py, scan_metrics.py. Permanent, never retired. Do not cross-wire the two engines.
- web/ - Next.js frontend. migrations/ - Alembic migrations. tests/ - unittest suite (FK-faithful harness in tests/_pgharness.py).

## Read for depth (keep this file small)
- Architecture and current state -> AISO_Codex_Handoff.md
- Branch and PR rules -> BRANCHING.md, CONTRIBUTING.md
- Open known gaps -> KNOWN_ISSUES.md
