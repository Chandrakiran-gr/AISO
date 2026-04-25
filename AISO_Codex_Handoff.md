# AISO Platform — Codex Handoff Document
**Date:** April 24, 2026  
**Project:** AISO (AI Search Optimization) by Sapienic  
**Author:** Antigravity (Handoff to Codex)

This document contains the complete context, architecture, and exact state of the AISO platform development. It is designed to get the Codex AI assistant up to speed immediately.

---

## 1. Project Overview & Architecture
AISO is a B2B SaaS platform that measures and optimizes a brand's visibility across Generative AI search engines (ChatGPT, Claude, Perplexity, Gemini). It replaces traditional SEO tracking with "AI Visibility Scoring".

### Tech Stack
*   **Frontend**: Next.js 16 (App Router), React 19, CSS Modules (Vanilla CSS, no Tailwind).
*   **Backend**: FastAPI (Python 3.14), SQLAlchemy, SQLite (Dev) / PostgreSQL (Prod).
*   **Auth**: NextAuth.js (Auth.js v5) with Google OAuth + Credentials fallback.
*   **Security**: Edge Middleware (`proxy.ts`) with strict CSP, HSTS, Rate Limiting, and CSRF protection.

### Key Architectural Decisions
*   **BYOK (Bring Your Own Key) Pipeline**: To avoid storing sensitive API keys, users provide their keys in the frontend during onboarding. Keys are stored ephemerally in `sessionStorage`, sent to FastAPI during the scan request, passed as environment variables to the Python `collect.py` subprocess, and immediately destroyed. They never touch a database or log file.
*   **Secure API Proxy**: The frontend does not call FastAPI directly. It calls a Next.js proxy (`/api/proxy/[...path]/route.ts`), which validates the NextAuth session and attaches an `X-User-Id` header before forwarding the request to FastAPI.
*   **Subprocess Execution**: The FastAPI server handles CRUD and orchestration but offloads the heavy LLM data collection to a standalone Python script (`full_stack/collect.py`) using `asyncio.create_subprocess_exec`.

---

## 2. Current Development State (What's Done)

The codebase is currently on branch `feat/byok-bring-your-own-key`. It is **100% stable, builds with 0 TypeScript errors**, and all routes are wired.

### Frontend Features ✅
*   **Marketing Site**: `/`, `/about`, `/pricing`, `/faq`, `/login`, `/signup`.
*   **Onboarding Wizard**: `/onboarding` — 3-step flow capturing URL, Providers, and BYOK keys. Fires a real `POST` to the backend.
*   **Dashboard**: `/dashboard` — Overview with live scan status polling.
*   **Scan History**: `/dashboard/scans` — List of all historical scans.
*   **Competitor Benchmarking**: `/dashboard/competitors` — Podium and leaderboard UI.
*   **Auth Guard**: `proxy.ts` strictly protects `/dashboard/*` and manages rate limiting.

### Backend Features ✅
*   **Database**: SQLAlchemy schema ready (`User`, `Client`, `Scan`, `ScanResult`).
*   **Clients API**: CRUD operations (`/clients`) protected by BOLA (Broken Object Level Auth) via `X-User-Id`.
*   **Pipeline API**: `/clients/{id}/scans` orchestrates the background task and BYOK key injection.
*   **Auth Validation**: `api/auth.py` contains the `get_current_user_id` dependency, rejecting requests without the secure proxy header.

---

## 3. Pending Tasks (Where Codex Takes Over)

The application is functionally complete from a UI/UX and orchestration perspective. The final step before launch is connecting the real LLM output data to the dashboard.

### Priority 1: Finish the Python Pipeline Data Persistence
Currently, `api/routes/pipeline.py` successfully triggers `full_stack/collect.py`. However, the collection script currently outputs data to JSON/CSV files locally (from the CLI MVP phase). 
*   **Codex Task**: Update `full_stack/collect.py` and `full_stack/analysis2.py` to write their final aggregated scores and results directly into the `ScanResult` SQLite/Postgres table, associated with the current `AISO_SCAN_ID`.

### Priority 2: Un-Mock the Dashboard UI
The Next.js dashboard UI (`web/app/dashboard/page.tsx` and `competitors/page.tsx`) currently renders beautiful mock data using constants (e.g., `PLACEHOLDER_PROVIDERS`, `MOCK_COMPETITORS`).
*   **Codex Task**: Once the Python pipeline writes real data to `ScanResult`, expose a FastAPI endpoint (e.g., `GET /clients/{id}/metrics`) to serve this data, and wire it into the React components.

### Priority 3: Vercel Deployment
*   **Codex Task**: Setup the `.env.production` variables in Vercel, configure the custom domain (`chandrakiranguthavariramesh.me` or similar), and deploy the Next.js app. Deploy FastAPI to Render/Railway.

---

## 4. Environment Variables Map

### Frontend (`web/.env.local`)
```env
# NextAuth
AUTH_SECRET="generate-a-secure-random-string"
AUTH_URL="http://localhost:3000/api/auth"

# OAuth (Google)
AUTH_GOOGLE_ID="your-google-client-id"
AUTH_GOOGLE_SECRET="your-google-client-secret"

# Backend Connection
NEXT_PUBLIC_API_URL="http://localhost:8000"
```

### Backend (`/.env`)
```env
# Database
DATABASE_URL="sqlite:///./aiso.db"

# Server (Pro-tier fallback keys — Free tier uses BYOK)
OPENAI_API_KEY=""
ANTHROPIC_API_KEY=""
PERPLEXITY_API_KEY=""
GOOGLE_AI_API_KEY=""
```

---

## 5. How to Run Locally

1. **Start the FastAPI Backend:**
   ```bash
   cd /Users/chandrakirangr/Documents/AISO
   source .venv/bin/activate
   uvicorn api.main:app --reload --port 8000
   ```

2. **Start the Next.js Frontend:**
   ```bash
   cd /Users/chandrakirangr/Documents/AISO/web
   npm run dev
   ```

## 6. Closing Notes for Codex
*   **Strict Rule:** Do **not** install TailwindCSS. The user explicitly requested a Vanilla CSS modules architecture (`*.module.css`) combined with CSS variable tokens defined in `globals.css`.
*   **Strict Rule:** Maintain the BYOK zero-persistence security model. Do not ever save API keys to the database.
*   **Design:** Maintain the dark-mode, glassmorphism UI aesthetic with subtle micro-animations (as seen in `competitors.module.css`).

Good luck! The platform is 90% there and ready for the final data wiring.
