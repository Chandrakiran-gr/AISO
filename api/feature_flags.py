"""Runtime feature flags for the AISO backend.

Phase 13 cutover is gated by ``AISO_SCAN_ENGINE`` so the new scan engine can be
rolled out with the legacy ``run_pipeline`` path kept as a one-release fallback.

- ``phase13``: scans execute on the Phase 13 saga (sampling → provider calls →
  classification → AVS → projection → publish) via the Procrastinate worker, and
  dashboard reads come from Phase 13 data.
- ``legacy`` (default): scans run the legacy ``collect.py`` pipeline and the
  dashboard reads legacy ``ScanResult``/``ScanCitation``/``Action`` tables.

The code default is intentionally ``legacy`` until the Phase 1 native consumers
(gap-report / actions / sources / citations) are wired. Until then, enabling
``phase13`` produces AVS metrics but empty gap-report/actions on the dashboard.
Flip the default to ``phase13`` when Phase 1 (endpoint rewire) lands; in the
meantime production opts in explicitly via the ``AISO_SCAN_ENGINE`` env var.
"""

from __future__ import annotations

import os

SCAN_ENGINE_PHASE13 = "phase13"
SCAN_ENGINE_LEGACY = "legacy"
_VALID_ENGINES = {SCAN_ENGINE_PHASE13, SCAN_ENGINE_LEGACY}
_DEFAULT_ENGINE = SCAN_ENGINE_LEGACY


def scan_engine() -> str:
    """Return the active scan engine, defaulting to ``legacy``.

    Unknown values fall back to the default so a typo never silently switches
    engines.
    """
    value = (os.getenv("AISO_SCAN_ENGINE") or _DEFAULT_ENGINE).strip().lower()
    return value if value in _VALID_ENGINES else _DEFAULT_ENGINE


def is_phase13_engine() -> bool:
    return scan_engine() == SCAN_ENGINE_PHASE13
