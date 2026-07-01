#!/usr/bin/env python3
"""CI guardrail (static backstop): BYOK keys are never persisted/logged.

Hard guardrail (CLAUDE.md): user-supplied LLM API keys (BYOK) live in memory
only — never written to the DB, logs, or files. ``api/database.py`` keeps a
dormant ``clients.byok_keys`` JSON column documented "Secret references/metadata
only; never raw keys", so the column legitimately *exists*; what must never
happen is a raw key value flowing into it (or into a logger / file).

This static check is a FAST, NON-EXHAUSTIVE backstop for the naive regression
(someone assigns a key to the column, logs the request, or serializes it to
disk). It is provably insufficient on its own — a non-literal path (splat into
a constructor, encode-then-store, log the whole request object) evades it. The
real guarantee is the behavioral test ``tests/test_byok_zero_persistence.py``
(sentinel absent from all DB tables + logs + files), and human review of every
key-touching PR. This check just makes the obvious mistake loud and cheap.

Detection over ``api/`` and ``full_stack/`` ``*.py``:
  1. Attribute assignment of a key into the column: ``<x>.byok_keys = <...>``
     (the column definition ``byok_keys = Column(...)`` has no leading dot, so
     it is not matched).
  2. A persistence / logging / serialization sink on a line that also mentions
     ``byok``: print / logging / .write / json.dump(s) / .to_csv / open(...).

Lines containing an allowlisted token (the intended in-memory/ephemeral paths)
are exempt — see ALLOW_TOKENS.

Exit 0 = clean; exit 1 = at least one suspicious line (prints file:line).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCAN_ROOTS = [REPO_ROOT / "api", REPO_ROOT / "full_stack"]
SKIP_DIRS = {"__pycache__", ".venv", "venv", "node_modules"}

# This script itself and the behavioral test legitimately mention these tokens.
SKIP_FILES = {
    "scripts/ci/check_byok_static.py",
    "tests/test_byok_zero_persistence.py",
}

# (1) Raw key written onto the model attribute (the column).
ATTR_ASSIGN = re.compile(r"\.byok_keys\s*=(?!=)")

# (2) Sink calls — if a sink appears on a line mentioning byok, flag it.
SINK = re.compile(
    r"(?:\bprint\s*\(|\blog(?:ger|ging)?\b[^=]*\.(?:debug|info|warning|warn|error|critical|exception)\s*\(|"
    r"\.write\s*\(|\bjson\.dumps?\s*\(|\.to_csv\s*\(|\bopen\s*\()",
    re.IGNORECASE,
)
MENTIONS_BYOK = re.compile(r"byok", re.IGNORECASE)

# Intended in-memory / ephemeral / metadata-only paths — exempt.
ALLOW_TOKENS = (
    "build_subprocess_env",     # BYOK → subprocess env only (intended path)
    "sub_env",                  # the ephemeral env dict
    "_redact_known_secrets",    # scrubbing, not persisting
    "model_dump",               # extracting to a plain dict passed to the task
    "byok_submitted",           # boolean flag, not the key value
    "= None",                   # explicit release (byok_keys = None)
    "Optional[",                # type annotation
    "Column(",                  # the ORM column definition
    "# byok-ok",                # explicit, reviewed escape hatch (use sparingly)
)


def _rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _iter_py():
    for root in SCAN_ROOTS:
        if not root.is_dir():
            continue
        for path in root.rglob("*.py"):
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            if _rel(path) in SKIP_FILES:
                continue
            yield path


def _is_allowlisted(line: str) -> bool:
    return any(tok in line for tok in ALLOW_TOKENS)


def main() -> int:
    violations: list[str] = []
    for path in _iter_py():
        rel = _rel(path)
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            hit = False
            if ATTR_ASSIGN.search(line) and not _is_allowlisted(line):
                hit = True
            elif MENTIONS_BYOK.search(line) and SINK.search(line) and not _is_allowlisted(line):
                hit = True
            if hit:
                violations.append(f"{rel}:{lineno}: {stripped}")

    if violations:
        print("[byok-static] FAIL — possible BYOK key persistence/logging:")
        for v in violations:
            print(f"  {v}")
        print(
            "\nBYOK keys must never reach the DB, logs, or files. If this line "
            "is a reviewed, genuinely-safe path, route it through the intended "
            "ephemeral mechanism (build_subprocess_env) or annotate it `# byok-ok` "
            "with justification. Remember: the behavioral test "
            "tests/test_byok_zero_persistence.py is the authoritative guarantee."
        )
        return 1

    print("[byok-static] OK — no naive BYOK persistence/logging pattern found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
