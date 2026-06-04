"""Runtime feature flags for the AISO backend.

Phase 13 cutover is gated by ``AISO_SCAN_ENGINE`` so the new scan engine can be
rolled out with the legacy ``run_pipeline`` path kept as a one-release fallback.

- ``phase13`` (default): scans execute on the Phase 13 saga (sampling →
  provider calls → classification → AVS → projection → publish) via the
  Procrastinate worker, and dashboard reads come from Phase 13 data.
- ``legacy``: scans run the legacy ``collect.py`` pipeline and the dashboard
  reads legacy ``ScanResult``/``ScanCitation``/``Action`` tables.
"""

from __future__ import annotations

import os

SCAN_ENGINE_PHASE13 = "phase13"
SCAN_ENGINE_LEGACY = "legacy"
_VALID_ENGINES = {SCAN_ENGINE_PHASE13, SCAN_ENGINE_LEGACY}


def scan_engine() -> str:
    """Return the active scan engine, defaulting to ``phase13``.

    Unknown values fall back to ``phase13`` so a typo never silently routes
    production back to the legacy engine.
    """
    value = (os.getenv("AISO_SCAN_ENGINE") or SCAN_ENGINE_PHASE13).strip().lower()
    return value if value in _VALID_ENGINES else SCAN_ENGINE_PHASE13


def is_phase13_engine() -> bool:
    return scan_engine() == SCAN_ENGINE_PHASE13
