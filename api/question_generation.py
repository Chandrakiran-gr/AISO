"""Context-aware conversational question bank generation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable
import re


GROUP_LABELS = {
    "G1": "Category & local discovery (unbranded)",
    "G2": "Direct brand (client named)",
    "G3": "Competitors & alternatives",
    "G4": "Transactional & bottom-funnel",
    "G5": "Trust, reviews & risk",
    "G6": "Fit: persona, occasion, constraint",
    "G7": "Head-to-head choice",
}

QUERY_BANK_HEADERS = [
    "question",
    "group",
    "group_label",
    "group_rank",
    "intent_score",
    "popularity_score",
    "cpc_proxy_score",
    "rank_reason",
]


@dataclass(frozen=True)
class QuestionCandidate:
    question: str
    group: str
    metadata: dict[str, Any]


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _items(profile: dict[str, Any], key: str) -> list[dict[str, Any]]:
    raw = profile.get(key, [])
    return raw if isinstance(raw, list) else []


def _names(items: Iterable[dict[str, Any]], *, fallback: str, limit: int = 8, bookable_only: bool = False) -> list[str]:
    names: list[str] = []
    for item in items:
        if bookable_only and item.get("bookable") is False:
            continue
        name = _clean(item.get("name"))
        if name:
            names.append(name)
        if len(names) >= limit:
            break
    return _dedupe(names) or [fallback]


def _locations(profile: dict[str, Any], usage: str) -> list[tuple[str, str]]:
    locations = profile.get("locations") if isinstance(profile.get("locations"), dict) else {}
    physical = [(item.get("name"), "physical") for item in locations.get("physical_locations", []) if isinstance(item, dict)]
    service = [(item.get("name"), "service_area") for item in locations.get("service_areas", []) if isinstance(item, dict)]
    visibility = [(item.get("name"), "visibility_market") for item in locations.get("visibility_markets", []) if isinstance(item, dict)]
    if usage == "g1":
        raw = [*physical, *service, *visibility]
    elif usage in {"g2", "g4", "g6"}:
        raw = [*physical, *service]
    elif usage in {"g3", "g5"}:
        raw = [*physical, *service, *visibility]
    else:
        raw = []
    cleaned = [(_clean(name), kind) for name, kind in raw if _clean(name)]
    return _dedupe_location_pairs(cleaned) or [("your area", "fallback")]


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        clean = _clean(value)
        key = re.sub(r"[^a-z0-9]+", " ", clean.casefold()).strip()
        if not clean or key in seen:
            continue
        seen.add(key)
        result.append(clean)
    return result


def _dedupe_location_pairs(values: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: set[str] = set()
    result: list[tuple[str, str]] = []
    for name, kind in values:
        key = re.sub(r"[^a-z0-9]+", " ", name.casefold()).strip()
        if not name or key in seen:
            continue
        seen.add(key)
        result.append((name, kind))
    return result


def _near_duplicate_key(question: str) -> str:
    stop = {"the", "a", "an", "for", "in", "near", "me", "with", "to", "and", "or", "is", "are", "does"}
    tokens = [
        token
        for token in re.sub(r"[^a-z0-9]+", " ", question.casefold()).split()
        if token not in stop
    ]
    return " ".join(tokens[:14])


def validate_question(candidate: QuestionCandidate) -> tuple[bool, str | None]:
    q = candidate.question.casefold()
    meta = candidate.metadata
    left = meta.get("left_type")
    right = meta.get("right_type")
    group = meta.get("group")
    location_usage = meta.get("location_usage")

    compared = any(token in q for token in (" vs ", " versus ", " compare ", " compared with ", " better than "))
    if compared and {left, right} == {"offering", "business"}:
        return False, "reject offering-vs-business comparison"
    if compared and {left, right} == {"product_brand", "offering"}:
        if not any(token in q for token in ("uses", "sells", "carries")):
            return False, "reject product-brand-vs-offering comparison"
    if meta.get("offering_group_bookable") is False and any(token in q for token in ("book ", "schedule ", "appointment")):
        return False, "reject offering group as bookable service"
    if location_usage == "visibility_market" and (
        group == "G4" or any(token in q for token in ("open now", "same day", "book ", "schedule "))
    ):
        return False, "reject urgent booking prompt for visibility-only market"
    if location_usage == "landmark" and not meta.get("location_confirmed"):
        return False, "reject unconfirmed landmark"
    return True, None


def _make(question: str, group: str, **metadata: Any) -> QuestionCandidate:
    metadata.setdefault("group", group)
    return QuestionCandidate(_clean(question), group, metadata)


def profile_to_question_rows(profile: dict[str, Any], *, limit_per_group: int = 24) -> list[dict[str, Any]]:
    business = profile.get("business") if isinstance(profile.get("business"), dict) else {}
    client = _clean(business.get("name")) or "the business"
    categories = _names(_items(profile, "categories"), fallback="local business category")
    offerings = _names(_items(profile, "offerings"), fallback=categories[0], bookable_only=True)
    offering_groups = _names(_items(profile, "offering_groups"), fallback=categories[0])
    brands = _names(_items(profile, "product_brands"), fallback="", limit=5)
    competitors = _names(_items(profile, "competitors"), fallback="another local business", limit=6)
    goals = _names(_items(profile, "goals"), fallback="choose the best provider", limit=5)
    personas = _names(_items(profile, "personas"), fallback="local customers", limit=5)

    if brands == [""]:
        brands = []

    candidates: list[QuestionCandidate] = []

    for category in categories[:3]:
        for location, usage in _locations(profile, "g1")[:4]:
            candidates.extend(
                [
                    _make(f"Who are the best {category} providers in {location}?", "G1", location_usage=usage, left_type="category"),
                    _make(f"What {category} businesses do people recommend around {location}?", "G1", location_usage=usage, left_type="category"),
                ]
            )
    for offering in offerings[:5]:
        for location, usage in _locations(profile, "g1")[:2]:
            candidates.append(_make(f"Where can I find trusted {offering} near {location}?", "G1", location_usage=usage, left_type="offering"))

    for offering in offerings[:8]:
        candidates.extend(
            [
                _make(f"Does {client} offer {offering}?", "G2", left_type="business", right_type="offering"),
                _make(f"Is {client} a good choice for {offering}?", "G2", left_type="business", right_type="offering"),
            ]
        )
    for group_name in offering_groups[:4]:
        candidates.append(
            _make(
                f"What should customers know about {group_name} at {client}?",
                "G2",
                left_type="business",
                right_type="offering_group",
                offering_group_bookable=False,
            )
        )
    for brand in brands[:4]:
        candidates.append(_make(f"Does {client} use or carry {brand}?", "G2", left_type="business", right_type="product_brand"))

    for competitor in competitors[:5]:
        for category in categories[:2]:
            for location, usage in _locations(profile, "g3")[:2]:
                candidates.append(_make(f"What are the best alternatives to {competitor} for {category} in {location}?", "G3", location_usage=usage, left_type="business", right_type="business"))
        for offering in offerings[:3]:
            candidates.append(_make(f"How does {client} compare with {competitor} for {offering}?", "G3", left_type="business", right_type="business"))

    for offering in offerings[:8]:
        for location, usage in _locations(profile, "g4")[:3]:
            candidates.extend(
                [
                    _make(f"Where can I book {offering} with {client} in {location}?", "G4", location_usage=usage, left_type="business", right_type="offering"),
                    _make(f"How much does {offering} cost at {client}?", "G4", location_usage=usage, left_type="business", right_type="offering"),
                ]
            )

    for offering in offerings[:6]:
        candidates.extend(
            [
                _make(f"Is {client} trustworthy for {offering}?", "G5", left_type="business", right_type="offering"),
                _make(f"What should I check before booking {offering} at {client}?", "G5", left_type="business", right_type="offering"),
            ]
        )
    for competitor in competitors[:3]:
        candidates.append(_make(f"Which has stronger reviews, {client} or {competitor}?", "G5", left_type="business", right_type="business"))

    for persona in personas[:4]:
        for offering in offerings[:5]:
            candidates.append(_make(f"Is {offering} at {client} a good fit for {persona}?", "G6", left_type="offering", right_type="business"))
    for goal in goals[:4]:
        for offering in offerings[:4]:
            candidates.append(_make(f"Which {offering} option helps with {goal}?", "G6", left_type="offering"))

    for competitor in competitors[:5]:
        for offering in offerings[:5]:
            candidates.append(_make(f"Should I choose {client} or {competitor} for {offering}?", "G7", left_type="business", right_type="business"))
    for goal in goals[:4]:
        for competitor in competitors[:3]:
            candidates.append(_make(f"Which is better for {goal}: {client} or {competitor}?", "G7", left_type="business", right_type="business"))

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    group_counts: dict[str, int] = {}
    for candidate in candidates:
        ok, reason = validate_question(candidate)
        if not ok:
            continue
        key = f"{candidate.group}:{_near_duplicate_key(candidate.question)}"
        if key in seen:
            continue
        seen.add(key)
        count = group_counts.get(candidate.group, 0)
        if count >= limit_per_group:
            continue
        group_counts[candidate.group] = count + 1
        rows.append(
            {
                "question": candidate.question,
                "group": candidate.group,
                "group_label": GROUP_LABELS[candidate.group],
                "group_rank": count + 1,
                "intent_score": 8 if candidate.group in {"G3", "G4", "G7"} else 7,
                "popularity_score": "",
                "cpc_proxy_score": 6 if candidate.group in {"G3", "G4"} else 5,
                "rank_reason": reason or "Generated from confirmed client context.",
            }
        )

    return rows
