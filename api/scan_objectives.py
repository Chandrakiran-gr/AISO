"""Shared scan objective validation and normalization."""

from __future__ import annotations

from typing import Any
import re
import unicodedata


MAX_CUSTOM_OBJECTIVE_LENGTH = 500

SCAN_OBJECTIVE_OPTIONS: tuple[tuple[str, str], ...] = (
    ("high_intent_visibility", "Improve high-intent buyer visibility"),
    ("find_competitor_gaps", "Find why AI recommends competitors"),
    ("local_discovery_visibility", "Improve local discovery visibility"),
    ("trust_citation_proof", "Improve trust, reviews, and citation proof"),
    ("new_market_service_audience", "Validate a new market, service, or audience"),
)

SCAN_OBJECTIVE_LABELS = dict(SCAN_OBJECTIVE_OPTIONS)
SCAN_OBJECTIVE_IDS = frozenset(SCAN_OBJECTIVE_LABELS)


class ScanObjectiveValidationError(ValueError):
    """Raised when a client-submitted scan objective is invalid."""


def _clean_text(value: Any) -> str:
    text = "".join(
        char
        for char in str(value or "")
        if not (unicodedata.category(char).startswith("C") or unicodedata.category(char) == "So")
    )
    return re.sub(r"\s+", " ", text).strip()


def _clean_objective_ids(values: Any, *, reject_unknown: bool) -> list[str]:
    if not isinstance(values, list):
        return []

    selected: list[str] = []
    seen: set[str] = set()
    for value in values:
        objective_id = _clean_text(value)
        if not objective_id:
            continue
        if objective_id not in SCAN_OBJECTIVE_IDS:
            if reject_unknown:
                raise ScanObjectiveValidationError(f"Unsupported scan objective: {objective_id}")
            continue
        if objective_id not in seen:
            selected.append(objective_id)
            seen.add(objective_id)
    return selected


def normalize_scan_objective(raw: Any, *, reject_unknown: bool = False) -> dict[str, Any]:
    """Normalize current and legacy scan objective payloads."""

    payload = raw if isinstance(raw, dict) else {}
    objectives = _clean_objective_ids(payload.get("optimization_objectives"), reject_unknown=reject_unknown)

    legacy_objective = _clean_text(payload.get("objective"))
    if legacy_objective and not objectives:
        if legacy_objective not in SCAN_OBJECTIVE_IDS:
            if reject_unknown:
                raise ScanObjectiveValidationError(f"Unsupported scan objective: {legacy_objective}")
        else:
            objectives = [legacy_objective]

    custom_objective = _clean_text(payload.get("custom_objective") or payload.get("custom"))
    if len(custom_objective) > MAX_CUSTOM_OBJECTIVE_LENGTH:
        raise ScanObjectiveValidationError(
            f"Custom objective must be {MAX_CUSTOM_OBJECTIVE_LENGTH} characters or fewer"
        )

    labels = [SCAN_OBJECTIVE_LABELS[objective] for objective in objectives]
    primary_objective = objectives[0] if objectives else ""

    return {
        "objective": primary_objective,
        "label": ", ".join(labels),
        "optimization_objectives": objectives,
        "custom_objective": custom_objective,
        "custom": custom_objective,
        "source_url": _clean_text(payload.get("source_url")) or "manual_onboarding",
        "confidence": payload.get("confidence") if isinstance(payload.get("confidence"), (int, float)) else 0.9,
    }
