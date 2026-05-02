"""Shared scan capability rules for group availability.

These rules keep the onboarding UI and FastAPI scan endpoint aligned. Competitor
inputs are optional for the business profile, but competitor-only scan groups
must not silently fall back to placeholders.
"""

from __future__ import annotations

from typing import Any, Iterable
import json
import re

from api.database import Client


VALID_SCAN_GROUPS = {"G1", "G2", "G3", "G4", "G5", "G6", "G7"}
COMPETITOR_REQUIRED_GROUPS = {"G3"}
COMPETITOR_REDUCED_WITHOUT_INPUT_GROUPS = {"G7"}


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        clean = _clean(value)
        key = clean.casefold()
        if not clean or key in seen:
            continue
        seen.add(key)
        result.append(clean)
    return result


def _client_competitors(client: Client) -> list[str]:
    if not client.competitors:
        return []
    try:
        parsed = json.loads(client.competitors)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return _dedupe(str(item) for item in parsed)


def profile_competitor_names(profile: dict[str, Any] | None) -> list[str]:
    """Return confirmed competitor names from a context profile."""
    if not isinstance(profile, dict):
        return []
    raw = profile.get("competitors")
    if not isinstance(raw, list):
        return []
    names: list[str] = []
    for item in raw:
        if isinstance(item, dict):
            names.append(str(item.get("name") or ""))
        else:
            names.append(str(item or ""))
    return _dedupe(names)


def competitor_names_for_scan(client: Client, profile: dict[str, Any] | None = None) -> list[str]:
    """Combine DB competitors and confirmed context competitors."""
    return _dedupe([*_client_competitors(client), *profile_competitor_names(profile)])


def validate_scan_group_capabilities(groups: Iterable[str], competitors: Iterable[str]) -> tuple[bool, str | None]:
    """Validate selected scan groups against available context."""
    selected = {str(group).upper() for group in groups}
    competitor_count = len(_dedupe(competitors))
    if competitor_count == 0 and selected & COMPETITOR_REQUIRED_GROUPS:
        return (
            False,
            "Add at least one competitor to run G3 Competitors & alternatives, or deselect G3 and continue without competitor coverage.",
        )
    return True, None


def group_capability_summary(groups: Iterable[str], competitors: Iterable[str]) -> dict[str, Any]:
    selected = {str(group).upper() for group in groups}
    competitor_count = len(_dedupe(competitors))
    unavailable = sorted(COMPETITOR_REQUIRED_GROUPS & selected) if competitor_count == 0 else []
    reduced = sorted(COMPETITOR_REDUCED_WITHOUT_INPUT_GROUPS & selected) if competitor_count == 0 else []
    ok, message = validate_scan_group_capabilities(selected, competitors)
    return {
        "ok": ok,
        "message": message,
        "competitor_count": competitor_count,
        "unavailable_groups": unavailable,
        "reduced_groups": reduced,
    }
