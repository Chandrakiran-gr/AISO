#!/usr/bin/env python3
"""CI guardrail: the frontend reaches FastAPI ONLY via the Next secure proxy.

Hard guardrail (CLAUDE.md): the browser/Next app must talk to the FastAPI
backend exclusively through ``/api/proxy/[...path]`` — that route is the single
place ``X-User-Id`` is attached. Any other ``web/`` code that points at the
backend base URL (env var or absolute host) bypasses that boundary.

Detection (static, fail-the-build): flag any ``web/`` source file that
references the backend base — the env vars that resolve it
(``AISO_API_URL`` / ``NEXT_PUBLIC_API_URL``) or an absolute backend host
(``api.sapienic.com`` / ``localhost:8000``) — EXCEPT a small, explicit
allowlist of server-side callers that legitimately reach the backend directly
and cannot self-proxy.

Allowlist (the subtle, QA-reviewed exceptions):
  * web/app/api/proxy/[...path]/route.ts — IS the secure proxy.
  * web/lib/auth-api.ts               — server-only (``import "server-only"``)
                                          NextAuth→FastAPI auth calls; runs
                                          before a session/proxy exists, so it
                                          cannot route through the proxy.
  * web/proxy.ts                       — middleware; references the hosts only
                                          inside the CSP ``connect-src`` header
                                          string, not as a fetch target.

This is a static backstop, not a substitute for review: a determined bypass
(string-built URL, indirection) can evade it. It exists to catch the naive,
common regression — a client component fetching the backend directly.

Exit 0 = clean; exit 1 = at least one violation (prints file:line).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WEB_ROOT = REPO_ROOT / "web"

# Files permitted to reference the backend base directly (repo-relative posix).
ALLOWLIST = {
    "web/app/api/proxy/[...path]/route.ts",
    "web/lib/auth-api.ts",
    "web/proxy.ts",
}

# Directories under web/ we never scan (generated / vendored).
SKIP_DIRS = {"node_modules", ".next", "dist", "build", ".turbo"}

SCAN_SUFFIXES = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}

# Markers that mean "this code knows the backend base" — i.e. a direct path.
BACKEND_MARKERS = (
    re.compile(r"\bAISO_API_URL\b"),
    re.compile(r"\bNEXT_PUBLIC_API_URL\b"),
    re.compile(r"api\.sapienic\.com"),
    re.compile(r"localhost:8000"),
)


def _rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _iter_web_sources():
    for path in WEB_ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in SCAN_SUFFIXES:
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(WEB_ROOT).parts):
            continue
        yield path


def main() -> int:
    if not WEB_ROOT.is_dir():
        print(f"[proxy-only] web/ not found at {WEB_ROOT}; nothing to check.")
        return 0

    violations: list[str] = []
    for path in _iter_web_sources():
        rel = _rel(path)
        if rel in ALLOWLIST:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for marker in BACKEND_MARKERS:
                if marker.search(line):
                    violations.append(f"{rel}:{lineno}: {line.strip()}")
                    break

    if violations:
        print("[proxy-only] FAIL — frontend code reaches the backend outside the proxy:")
        for v in violations:
            print(f"  {v}")
        print(
            "\nFix: route the call through /api/proxy/[...path] (X-User-Id is "
            "attached there). If this is a legitimate server-side caller that "
            "cannot self-proxy, add it to ALLOWLIST in this script with a "
            "review note."
        )
        return 1

    print("[proxy-only] OK — no frontend code reaches the backend outside the secure proxy.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
