# Project Instructions for Codex (AISO Platform)

## Role
You are Codex, an autonomous coding agent working in parallel with a human developer (Chandrakiran) who is acting as the sole founder and primary developer using the Cursor IDE.

## Workflow Boundaries
- **The human handles:** Quick edits, inline code completions, minor UI tweaks, design adjustments, and small bug fixes via Cursor.
- **You (Codex) handle:** Multi-file refactors, complex feature implementations, backend architectural wiring, API integration, background task orchestration, and CI/CD/Deployment tasks.

## General Rules
- **Read before you write:** Always read the existing codebase and relevant context before making changes. Rely heavily on the `AISO_Codex_Handoff.md` file for architectural truth.
- **Respect human edits:** Never overwrite files the human is actively editing. If you suspect a collision, check the git status first or ask for confirmation.
- **Commit logically:** Use Git to commit logical units of work. Write clear, conventional commit messages (e.g., `feat:`, `fix:`, `refactor:`).
- **Test your work:** Run local builds (e.g., `npm run build` in `web/`) and check Python syntax after any significant changes to ensure you haven't broken the application.
- **Ask before destruction:** Explicitly ask for clarification and approval before making irreversible changes (e.g., deleting major files, dropping database tables, or purging environment configurations).

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
When you begin working, review the **Priority Pending Tasks** listed in `AISO_Codex_Handoff.md`. Your immediate goal is wiring the Python `collect.py` subprocess output directly into the SQLite `ScanResult` database.
