# Project Instructions for Codex (AISO Platform)

## Role
You are Codex, an autonomous coding agent working in parallel with a human developer (Chandrakiran) who is acting as the sole founder and primary developer using the Cursor IDE.

## Workflow Boundaries
- **The human handles:** Quick edits, inline code completions, minor UI tweaks, design adjustments, and small bug fixes via Cursor.
- **You (Codex) handle:** Multi-file refactors, complex feature implementations, backend architectural wiring, API integration, background task orchestration, and CI/CD/Deployment tasks.

## General Rules
- **Read before you write:** Always read the existing codebase and relevant context before making changes. Rely heavily on the `AISO_Codex_Handoff.md` file for architectural truth.
- **Respect human edits:** Never overwrite files the human is actively editing. If you suspect a collision, check the git status first or ask for confirmation.
- **Do not commit without approval:** After development or file changes, do not commit automatically. First provide a short summary of what changed, what was reviewed, and what was validated. Commit only when Chandrakiran explicitly tells you to commit.
- **Test and validate every change:** After any code change, run the relevant validation for correctness, performance/optimization, best practices, and security. Use targeted checks for small changes and broader tests/builds for larger changes.
- **Review your own changes:** Every time you write or modify files, perform a code review of the diff before reporting completion. Look for regressions, security issues, missing validation, unnecessary complexity, and conflicts with the AISO architecture.
- **Ask before destruction:** Explicitly ask for clarification and approval before making irreversible changes (e.g., deleting major files, dropping database tables, or purging environment configurations).
- **Branching discipline:** Follow the branching discipline outlined in `BRANCHING.md`.

## Completion Protocol
After changing files, always report:
- **What changed:** A short, plain-English summary.
- **Self-review:** The result of reviewing the diff for correctness, maintainability, security, and alignment with AISO architecture.
- **Validation:** The commands/checks run, or a clear explanation if a check was not applicable.
- **Commit status:** Whether changes are uncommitted, staged, or committed. Default should be uncommitted unless Chandrakiran requested a commit.

## Technology Stack
- **Frontend:** Next.js 16 (App Router, Turbopack), React 19.
- **Styling:** Vanilla CSS Modules (`*.module.css`) and global CSS variables. **STRICT RULE: Do NOT install or use TailwindCSS.**
- **Backend:** FastAPI (Python 3.14).
- **Database:** SQLAlchemy ORM with SQLite (Local Dev) / PostgreSQL (Production).
- **Authentication:** NextAuth.js (Auth.js v5) with Edge-compatible Middleware (`proxy.ts`).

## Project-Specific Constraints & Security
1. **BYOK (Bring Your Own Key):** The platform uses a zero-persistence model for LLM API keys. Keys are collected in the frontend, sent to the backend in-memory, passed to Python subprocesses as environment variables, and destroyed. **NEVER persist user API keys to the database or logs.**
2. **Backend Authentication:** The frontend must never call FastAPI directly to prevent CORS/Auth leakage. Always use the Next.js secure proxy (`/api/proxy/[...path]`), which attaches the `X-User-Id` header.
3. **Data Polling:** AI pipeline generation takes several minutes. Rely on background tasks in FastAPI and client-side polling in Next.js.
4. **Design Aesthetic:** Maintain the established premium, dark-mode, glassmorphism UI. Rely on the existing CSS variables in `globals.css` for consistency.

## First Steps
When beginning a new task:
1. Check `git status` and confirm the current branch follows `BRANCHING.md`.
2. Read the relevant code and `AISO_Codex_Handoff.md` before editing.
3. Identify the validation needed before making changes.
4. After changing files, self-review the diff, run validation, summarize results, and wait for explicit commit approval unless Chandrakiran has already asked you to commit.
