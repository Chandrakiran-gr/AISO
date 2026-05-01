"""Context-aware, deterministic question generation and value ranking."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable, Mapping
import json
import os
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

DEFAULT_GROUP_TARGETS = {
    "G1": 14,
    "G2": 18,
    "G3": 22,
    "G4": 24,
    "G5": 20,
    "G6": 12,
    "G7": 16,
}

DEFAULT_CANDIDATE_LIMIT_PER_GROUP = 150

QUERY_BANK_HEADERS = [
    "question",
    "group",
    "group_label",
    "group_rank",
    "intent_score",
    "popularity_score",
    "cpc_proxy_score",
    "final_rank_score",
    "human_realism_score",
    "ai_visibility_opportunity_score",
    "citation_actionability_score",
    "specificity_score",
    "evidence_confidence_score",
    "local_relevance_score",
    "diversity_penalty",
    "rank_reason",
]

STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "around",
    "at",
    "best",
    "can",
    "do",
    "does",
    "for",
    "from",
    "how",
    "i",
    "in",
    "is",
    "it",
    "me",
    "near",
    "of",
    "or",
    "should",
    "the",
    "to",
    "what",
    "where",
    "which",
    "who",
    "with",
    "you",
}

PURCHASE_TERMS = {
    "appointment": 1.6,
    "available": 1.2,
    "book": 2.2,
    "booking": 2.0,
    "buy": 2.0,
    "cost": 2.0,
    "deal": 1.0,
    "estimate": 1.7,
    "hire": 2.0,
    "open now": 1.7,
    "price": 2.0,
    "pricing": 2.0,
    "quote": 1.8,
    "reviews": 1.3,
    "same day": 1.6,
    "schedule": 2.0,
    "today": 1.2,
}

COMPARISON_TERMS = {
    "alternative": 1.7,
    "alternatives": 1.7,
    "better": 1.4,
    "choose": 1.5,
    "compare": 1.5,
    "instead": 1.2,
    "recommend": 1.1,
    "recommended": 1.1,
    "reviews": 1.2,
    "trustworthy": 1.2,
    "worth": 1.2,
}

GROUP_INTENT_BASE = {
    "G1": 5.6,
    "G2": 7.0,
    "G3": 8.1,
    "G4": 9.0,
    "G5": 7.2,
    "G6": 6.4,
    "G7": 8.4,
}

GROUP_COMMERCIAL_BASE = {
    "G1": 5.8,
    "G2": 7.6,
    "G3": 7.8,
    "G4": 9.0,
    "G5": 5.8,
    "G6": 5.2,
    "G7": 7.2,
}

GROUP_VISIBILITY_BASE = {
    "G1": 7.2,
    "G2": 8.0,
    "G3": 9.2,
    "G4": 8.4,
    "G5": 8.7,
    "G6": 6.8,
    "G7": 9.0,
}


@dataclass(frozen=True)
class QuestionCandidate:
    question: str
    group: str
    metadata: dict[str, Any]


@dataclass
class RankedQuestion:
    candidate: QuestionCandidate
    scores: dict[str, float]
    final_rank_score: float
    diversity_penalty: float = 0.0
    selected: bool = False
    group_rank: int | None = None
    rejected_reason: str | None = None
    rank_reason: str = ""


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _items(profile: dict[str, Any], key: str) -> list[dict[str, Any]]:
    raw = profile.get(key, [])
    return raw if isinstance(raw, list) else []


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


def _fallback_item(name: str, item_type: str, confidence: float = 0.55) -> dict[str, Any]:
    return {"name": name, "type": item_type, "confidence": confidence, "source_url": "fallback"}


def _named_items(
    profile: dict[str, Any],
    key: str,
    *,
    fallback: str,
    item_type: str,
    limit: int = 12,
    bookable_only: bool = False,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in _items(profile, key):
        if not isinstance(item, dict):
            continue
        if bookable_only and item.get("bookable") is False:
            continue
        name = _clean(item.get("name"))
        normalized = re.sub(r"[^a-z0-9]+", " ", name.casefold()).strip()
        if not name or normalized in seen:
            continue
        next_item = dict(item)
        next_item["name"] = name
        next_item.setdefault("type", item_type)
        next_item.setdefault("confidence", 0.7)
        result.append(next_item)
        seen.add(normalized)
        if len(result) >= limit:
            break
    return result or [_fallback_item(fallback, item_type, 0.45)]


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


def _near_duplicate_key(question: str) -> str:
    tokens = [token for token in _content_tokens(question) if token not in STOPWORDS]
    return " ".join(tokens[:14])


def _content_tokens(text: str) -> list[str]:
    return [
        token
        for token in re.sub(r"[^a-z0-9]+", " ", text.casefold()).split()
        if token and token not in STOPWORDS
    ]


def _similarity(left: str, right: str) -> float:
    left_tokens = set(_content_tokens(left))
    right_tokens = set(_content_tokens(right))
    if not left_tokens or not right_tokens:
        return 0.0
    jaccard = len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
    sequence = SequenceMatcher(None, left.casefold(), right.casefold()).ratio()
    return max(jaccard, sequence * 0.85)


def _clamp(value: float, low: float = 0.0, high: float = 10.0) -> float:
    return round(max(low, min(high, value)), 2)


def _term_score(question: str, terms: Mapping[str, float]) -> float:
    lowered = question.casefold()
    return sum(weight for term, weight in terms.items() if term in lowered)


def _env_positive_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _parse_group_targets(selected_groups: Iterable[str] | None = None) -> dict[str, int]:
    selected = list(selected_groups or GROUP_LABELS.keys())
    targets = {group: DEFAULT_GROUP_TARGETS.get(group, 12) for group in selected if group in GROUP_LABELS}
    raw = os.environ.get("AISO_QUESTION_GROUP_TARGETS", "").strip()
    if raw:
        for part in raw.split(","):
            if ":" not in part:
                continue
            group, value = [piece.strip().upper() for piece in part.split(":", 1)]
            if group not in GROUP_LABELS:
                continue
            try:
                parsed = int(value)
            except ValueError:
                continue
            if parsed > 0:
                targets[group] = parsed
        return {group: targets[group] for group in selected if group in targets}

    total_raw = os.environ.get("AISO_QUESTION_FINAL_TOTAL", "").strip()
    if total_raw:
        try:
            total = int(total_raw)
        except ValueError:
            total = 0
        if total > 0 and selected:
            weights = {group: DEFAULT_GROUP_TARGETS.get(group, 12) for group in selected if group in GROUP_LABELS}
            weight_sum = sum(weights.values()) or 1
            allocated = {group: max(1, int(total * weight / weight_sum)) for group, weight in weights.items()}
            while sum(allocated.values()) < total:
                group = max(weights, key=lambda key: weights[key] - allocated.get(key, 0))
                allocated[group] += 1
            while sum(allocated.values()) > total:
                group = max(allocated, key=allocated.get)
                if allocated[group] > 1:
                    allocated[group] -= 1
                else:
                    break
            return allocated

    return targets


def validate_question(candidate: QuestionCandidate) -> tuple[bool, str | None]:
    q = candidate.question.casefold()
    meta = candidate.metadata
    left = meta.get("left_type")
    right = meta.get("right_type")
    group = meta.get("group")
    location_usage = meta.get("location_usage")

    if "{" in q or "}" in q or "[" in q or "]" in q:
        return False, "reject unresolved placeholder"
    if not candidate.question.endswith("?"):
        return False, "reject non-question fragment"
    if len(_content_tokens(candidate.question)) < 3:
        return False, "reject low-information question"

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


def _confidence(*items: dict[str, Any] | None) -> float:
    values: list[float] = []
    for item in items:
        if not item:
            continue
        try:
            values.append(float(item.get("confidence", 0.7)))
        except (TypeError, ValueError):
            values.append(0.7)
    if not values:
        return 0.55
    return sum(values) / len(values)


def _add_candidate(
    target: list[QuestionCandidate],
    question: str,
    group: str,
    *,
    evidence_items: Iterable[dict[str, Any] | None] = (),
    **metadata: Any,
) -> None:
    metadata["evidence_confidence"] = _confidence(*list(evidence_items))
    target.append(_make(question, group, **metadata))


def _generate_candidates(profile: dict[str, Any], selected_groups: Iterable[str]) -> list[QuestionCandidate]:
    business = profile.get("business") if isinstance(profile.get("business"), dict) else {}
    client = _clean(business.get("name")) or "the business"
    categories = _named_items(profile, "categories", fallback="local business category", item_type="category", limit=8)
    offerings = _named_items(profile, "offerings", fallback=categories[0]["name"], item_type="offering", limit=24, bookable_only=True)
    offering_groups = _named_items(profile, "offering_groups", fallback=categories[0]["name"], item_type="offering_group", limit=12)
    brands = [item for item in _named_items(profile, "product_brands", fallback="", item_type="product_brand", limit=10) if item["name"]]
    competitors = _named_items(profile, "competitors", fallback="another local business", item_type="competitor_business", limit=12)
    goals = _named_items(profile, "goals", fallback="choose the best provider", item_type="goal", limit=12)
    personas = _named_items(profile, "personas", fallback="local customers", item_type="persona", limit=12)
    group_set = set(selected_groups)

    candidates: list[QuestionCandidate] = []

    if "G1" in group_set:
        category_templates = [
            "Who are the best {category} providers in {location}?",
            "What {category} businesses do people recommend around {location}?",
            "Which {category} options near {location} have strong reviews?",
            "Where should I look for a trusted {category} near {location}?",
            "What are the top-rated {category} choices in {location}?",
            "Which local {category} is best for {goal} in {location}?",
        ]
        offering_templates = [
            "Where can I find trusted {offering} near {location}?",
            "Who offers highly rated {offering} in {location}?",
            "What is the best place for {offering} around {location}?",
            "Which providers near {location} are known for {offering}?",
            "Where do people recommend going for {offering} near {location}?",
            "What {offering} options are worth considering in {location}?",
        ]
        for category in categories:
            for goal in goals[:3]:
                for location, usage in _locations(profile, "g1")[:5]:
                    for template in category_templates:
                        _add_candidate(
                            candidates,
                            template.format(category=category["name"], goal=goal["name"], location=location),
                            "G1",
                            evidence_items=(category, goal),
                            location_usage=usage,
                            location=location,
                            category=category["name"],
                            left_type="category",
                            pattern="category_discovery",
                        )
        for offering in offerings:
            for location, usage in _locations(profile, "g1")[:4]:
                for template in offering_templates:
                    _add_candidate(
                        candidates,
                        template.format(offering=offering["name"], location=location),
                        "G1",
                        evidence_items=(offering,),
                        location_usage=usage,
                        location=location,
                        offering=offering["name"],
                        left_type="offering",
                        pattern="offering_discovery",
                    )

    if "G2" in group_set:
        offering_templates = [
            "Does {client} offer {offering}?",
            "Is {client} a good choice for {offering}?",
            "What should I know before booking {offering} at {client}?",
            "How does {client} describe its {offering} service?",
            "Is {offering} at {client} worth it?",
            "What results can customers expect from {offering} at {client}?",
            "Who is {offering} at {client} best suited for?",
            "How much does {offering} cost at {client}?",
        ]
        group_templates = [
            "What should customers know about {group_name} at {client}?",
            "Which services are included in {group_name} at {client}?",
            "How should I choose within {group_name} at {client}?",
            "Is {group_name} at {client} right for {goal}?",
        ]
        for offering in offerings:
            for template in offering_templates:
                _add_candidate(
                    candidates,
                    template.format(client=client, offering=offering["name"]),
                    "G2",
                    evidence_items=(offering,),
                    offering=offering["name"],
                    left_type="business",
                    right_type="offering",
                    pattern="direct_offering",
                )
        for group_name in offering_groups:
            for goal in goals[:3]:
                for template in group_templates:
                    _add_candidate(
                        candidates,
                        template.format(client=client, group_name=group_name["name"], goal=goal["name"]),
                        "G2",
                        evidence_items=(group_name, goal),
                        offering_group=group_name["name"],
                        left_type="business",
                        right_type="offering_group",
                        offering_group_bookable=False,
                        pattern="direct_group",
                    )
        for brand in brands:
            for template in (
                "Does {client} use or carry {brand}?",
                "What does {client} use {brand} for?",
                "Is {brand} available through {client}?",
            ):
                _add_candidate(
                    candidates,
                    template.format(client=client, brand=brand["name"]),
                    "G2",
                    evidence_items=(brand,),
                    product_brand=brand["name"],
                    left_type="business",
                    right_type="product_brand",
                    pattern="direct_brand_product",
                )

    if "G3" in group_set:
        for competitor in competitors:
            for category in categories[:4]:
                for location, usage in _locations(profile, "g3")[:4]:
                    for template in (
                        "What are the best alternatives to {competitor} for {category} in {location}?",
                        "Who competes with {competitor} for {category} near {location}?",
                        "Which {category} providers near {location} are better alternatives to {competitor}?",
                        "What local businesses should I compare with {competitor} for {category}?",
                    ):
                        _add_candidate(
                            candidates,
                            template.format(competitor=competitor["name"], category=category["name"], location=location),
                            "G3",
                            evidence_items=(competitor, category),
                            location_usage=usage,
                            location=location,
                            competitor=competitor["name"],
                            category=category["name"],
                            left_type="business",
                            right_type="business",
                            pattern="competitor_alternative",
                        )
            for offering in offerings[:8]:
                for template in (
                    "How does {client} compare with {competitor} for {offering}?",
                    "Is {client} or {competitor} better for {offering}?",
                    "What is the best alternative to {competitor} for {offering}?",
                    "Should I switch from {competitor} to {client} for {offering}?",
                    "Which business is more trusted for {offering}: {client} or {competitor}?",
                    "Where should I book {offering} instead of {competitor}?",
                ):
                    _add_candidate(
                        candidates,
                        template.format(client=client, competitor=competitor["name"], offering=offering["name"]),
                        "G3",
                        evidence_items=(competitor, offering),
                        competitor=competitor["name"],
                        offering=offering["name"],
                        left_type="business",
                        right_type="business",
                        pattern="offering_comparison",
                    )

    if "G4" in group_set:
        for offering in offerings:
            for location, usage in _locations(profile, "g4")[:5]:
                for template in (
                    "Where can I book {offering} with {client} in {location}?",
                    "How much does {offering} cost at {client} near {location}?",
                    "Can I schedule {offering} at {client} near {location}?",
                    "Is {offering} available at {client} in {location} this week?",
                    "What is the price for {offering} at {client} near {location}?",
                    "Where can I get a quote for {offering} near {location}?",
                    "How do I book an appointment for {offering} at {client} near {location}?",
                    "What should I expect when booking {offering} at {client} in {location}?",
                ):
                    _add_candidate(
                        candidates,
                        template.format(client=client, offering=offering["name"], location=location),
                        "G4",
                        evidence_items=(offering,),
                        location_usage=usage,
                        location=location,
                        offering=offering["name"],
                        left_type="business",
                        right_type="offering",
                        pattern="transactional_offering",
                    )

    if "G5" in group_set:
        for offering in offerings[:12]:
            for template in (
                "Is {client} trustworthy for {offering}?",
                "What should I check before booking {offering} at {client}?",
                "What do reviews say about {offering} at {client}?",
                "Is {client} safe and reputable for {offering}?",
                "What are the risks of choosing {offering} at {client}?",
                "How do customers rate {client} for {offering}?",
                "What proof should I look for before choosing {client} for {offering}?",
                "Does {client} have credible results for {offering}?",
            ):
                _add_candidate(
                    candidates,
                    template.format(client=client, offering=offering["name"]),
                    "G5",
                    evidence_items=(offering,),
                    offering=offering["name"],
                    left_type="business",
                    right_type="offering",
                    pattern="trust_offering",
                )
        for competitor in competitors[:6]:
            for template in (
                "Which has stronger reviews, {client} or {competitor}?",
                "Is {client} more trustworthy than {competitor}?",
                "What complaints should I compare between {client} and {competitor}?",
                "Which business has better customer proof, {client} or {competitor}?",
                "Which business is safer to choose, {client} or {competitor}?",
                "Which business has more reliable proof, {client} or {competitor}?",
                "What should I verify before choosing {client} over {competitor}?",
                "Do customers trust {client} more than {competitor}?",
            ):
                _add_candidate(
                    candidates,
                    template.format(client=client, competitor=competitor["name"]),
                    "G5",
                    evidence_items=(competitor,),
                    competitor=competitor["name"],
                    left_type="business",
                    right_type="business",
                    pattern="trust_competitor",
                )

    if "G6" in group_set:
        for persona in personas[:8]:
            for offering in offerings[:8]:
                for template in (
                    "Is {offering} at {client} a good fit for {persona}?",
                    "Which {offering} option is best for {persona}?",
                    "Should {persona} choose {client} for {offering}?",
                    "What should {persona} know before booking {offering}?",
                    "Is {offering} gentle enough for {persona}?",
                ):
                    _add_candidate(
                        candidates,
                        template.format(client=client, offering=offering["name"], persona=persona["name"]),
                        "G6",
                        evidence_items=(offering, persona),
                        offering=offering["name"],
                        persona=persona["name"],
                        left_type="offering",
                        right_type="business",
                        pattern="persona_fit",
                    )
        for goal in goals[:8]:
            for offering in offerings[:8]:
                for template in (
                    "Which {offering} option helps with {goal}?",
                    "Is {offering} the right choice for {goal}?",
                    "What service should I choose for {goal}: {offering} or another option?",
                    "Can {offering} help someone trying to {goal}?",
                ):
                    _add_candidate(
                        candidates,
                        template.format(offering=offering["name"], goal=goal["name"]),
                        "G6",
                        evidence_items=(offering, goal),
                        offering=offering["name"],
                        goal=goal["name"],
                        left_type="offering",
                        pattern="goal_fit",
                    )

    if "G7" in group_set:
        for competitor in competitors[:8]:
            for offering in offerings[:8]:
                for template in (
                    "Should I choose {client} or {competitor} for {offering}?",
                    "Which is better for {offering}: {client} or {competitor}?",
                    "Who should I book for {offering}, {client} or {competitor}?",
                    "Which has better reviews for {offering}, {client} or {competitor}?",
                    "Which business is worth it for {offering}: {client} or {competitor}?",
                    "What is the better choice for {offering}, {client} or {competitor}?",
                    "Which business should I trust for {offering}: {client} or {competitor}?",
                    "Which business is more likely to recommend for {offering}, {client} or {competitor}?",
                ):
                    _add_candidate(
                        candidates,
                        template.format(client=client, competitor=competitor["name"], offering=offering["name"]),
                        "G7",
                        evidence_items=(competitor, offering),
                        competitor=competitor["name"],
                        offering=offering["name"],
                        left_type="business",
                        right_type="business",
                        pattern="head_to_head_offering",
                    )
            for goal in goals[:6]:
                for template in (
                    "Which is better for {goal}: {client} or {competitor}?",
                    "Should I choose {client} or {competitor} if I want to {goal}?",
                    "Which business is the safer choice for {goal}, {client} or {competitor}?",
                    "Which business is more trusted for {goal}, {client} or {competitor}?",
                ):
                    _add_candidate(
                        candidates,
                        template.format(client=client, competitor=competitor["name"], goal=goal["name"]),
                        "G7",
                        evidence_items=(competitor, goal),
                        competitor=competitor["name"],
                        goal=goal["name"],
                        left_type="business",
                        right_type="business",
                        pattern="head_to_head_goal",
                    )

    return candidates


class QuestionValueRanker:
    """Ranks context-aware questions for AI visibility opportunity."""

    def __init__(self, candidate_limit_per_group: int = DEFAULT_CANDIDATE_LIMIT_PER_GROUP):
        self.candidate_limit_per_group = candidate_limit_per_group

    def rank_and_select(
        self,
        candidates: list[QuestionCandidate],
        *,
        group_targets: Mapping[str, int],
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        validated: list[QuestionCandidate] = []
        rejected: list[dict[str, Any]] = []
        exact_seen: set[str] = set()
        for candidate in candidates:
            ok, reason = validate_question(candidate)
            if not ok:
                rejected.append(self._report_candidate(candidate, selected=False, rejected_reason=reason))
                continue
            key = _near_duplicate_key(candidate.question)
            if key in exact_seen:
                rejected.append(self._report_candidate(candidate, selected=False, rejected_reason="reject duplicate question"))
                continue
            exact_seen.add(key)
            validated.append(candidate)

        ranked_by_group: dict[str, list[RankedQuestion]] = {group: [] for group in group_targets}
        for candidate in validated:
            if candidate.group not in group_targets:
                continue
            bucket = ranked_by_group.setdefault(candidate.group, [])
            scores = self._score(candidate)
            final_score = self._final_score(scores, diversity_penalty=0.0)
            bucket.append(RankedQuestion(candidate=candidate, scores=scores, final_rank_score=final_score))

        selected_rows: list[dict[str, Any]] = []
        report_candidates: list[dict[str, Any]] = [*rejected]
        selected_count_by_group: dict[str, int] = {}

        for group, target in group_targets.items():
            bucket = sorted(ranked_by_group.get(group, []), key=lambda item: item.final_rank_score, reverse=True)
            overflow = bucket[self.candidate_limit_per_group :]
            for ranked in overflow:
                ranked.rejected_reason = "reject candidate limit overflow"
                report_candidates.append(self._report_ranked(ranked))
            bucket = bucket[: self.candidate_limit_per_group]
            chosen: list[RankedQuestion] = []
            remaining = bucket[:]
            while remaining and len(chosen) < target:
                best_index = 0
                best_score = -999.0
                best_penalty = 0.0
                for index, ranked in enumerate(remaining):
                    if any(_similarity(ranked.candidate.question, selected.candidate.question) >= 0.88 for selected in chosen):
                        continue
                    penalty = self._diversity_penalty(ranked.candidate, chosen)
                    adjusted = self._final_score(ranked.scores, penalty)
                    if adjusted > best_score:
                        best_index = index
                        best_score = adjusted
                        best_penalty = penalty
                if best_score < -900:
                    ranked = remaining.pop(0)
                    best_penalty = self._diversity_penalty(ranked.candidate, chosen) + 1.0
                    best_score = self._final_score(ranked.scores, best_penalty)
                else:
                    ranked = remaining.pop(best_index)
                ranked.diversity_penalty = best_penalty
                ranked.final_rank_score = best_score
                ranked.selected = True
                ranked.group_rank = len(chosen) + 1
                ranked.rank_reason = self._rank_reason(ranked)
                chosen.append(ranked)

            selected_count_by_group[group] = len(chosen)
            selected_rows.extend(self._row_from_ranked(ranked) for ranked in chosen)
            chosen_questions = {ranked.candidate.question for ranked in chosen}
            for ranked in bucket:
                if ranked.candidate.question not in chosen_questions:
                    ranked.rejected_reason = ranked.rejected_reason or "not selected by group target"
                    report_candidates.append(self._report_ranked(ranked))
            report_candidates.extend(self._report_ranked(ranked) for ranked in chosen)

        summary = {
            "candidates_generated": len(candidates),
            "candidates_validated": len(validated),
            "candidates_rejected": len(rejected),
            "final_selected": len(selected_rows),
            "group_targets": dict(group_targets),
            "selected_by_group": selected_count_by_group,
            "candidate_limit_per_group": self.candidate_limit_per_group,
            "ranking_mode": "deterministic",
        }
        report = {"summary": summary, "candidates": report_candidates}
        return selected_rows, report

    def _score(self, candidate: QuestionCandidate) -> dict[str, float]:
        q = candidate.question
        group = candidate.group
        purchase = _clamp(GROUP_INTENT_BASE.get(group, 5.0) + _term_score(q, PURCHASE_TERMS) * 0.55 + _term_score(q, COMPARISON_TERMS) * 0.25)
        commercial = _clamp(GROUP_COMMERCIAL_BASE.get(group, 5.0) + _term_score(q, PURCHASE_TERMS) * 0.35 + _term_score(q, COMPARISON_TERMS) * 0.2)
        human = self._human_realism_score(candidate)
        opportunity = self._visibility_opportunity_score(candidate)
        actionability = self._citation_actionability_score(candidate)
        specificity = self._specificity_score(candidate)
        evidence = _clamp(float(candidate.metadata.get("evidence_confidence", 0.55)) * 10.0)
        local = self._local_relevance_score(candidate)
        return {
            "human_realism_score": human,
            "purchase_intent_score": purchase,
            "ai_visibility_opportunity_score": opportunity,
            "citation_actionability_score": actionability,
            "specificity_score": specificity,
            "evidence_confidence_score": evidence,
            "commercial_proxy_score": commercial,
            "local_relevance_score": local,
        }

    def _final_score(self, scores: Mapping[str, float], diversity_penalty: float) -> float:
        score = (
            0.22 * scores["ai_visibility_opportunity_score"]
            + 0.18 * scores["purchase_intent_score"]
            + 0.16 * scores["citation_actionability_score"]
            + 0.14 * scores["human_realism_score"]
            + 0.12 * scores["specificity_score"]
            + 0.08 * scores["commercial_proxy_score"]
            + 0.06 * scores["evidence_confidence_score"]
            + 0.04 * scores["local_relevance_score"]
            - diversity_penalty
        )
        return round(score, 4)

    def _human_realism_score(self, candidate: QuestionCandidate) -> float:
        q = candidate.question
        lowered = q.casefold()
        score = 7.2
        if lowered.startswith(("who ", "what ", "where ", "which ", "how ", "is ", "does ", "can ", "should ")):
            score += 1.2
        if any(phrase in lowered for phrase in ("should i", "where can i", "what should i", "is ", "does ")):
            score += 0.8
        if len(q.split()) < 5:
            score -= 2.0
        if len(q.split()) > 18:
            score -= 0.6
        if re.search(r"\b(best|top|near me)\b.*\b(best|top|near me)\b", lowered):
            score -= 0.7
        return _clamp(score)

    def _visibility_opportunity_score(self, candidate: QuestionCandidate) -> float:
        meta = candidate.metadata
        score = GROUP_VISIBILITY_BASE.get(candidate.group, 6.5)
        if meta.get("competitor"):
            score += 1.0
        if meta.get("offering"):
            score += 0.65
        if meta.get("location") and meta.get("location_usage") != "fallback":
            score += 0.35
        if candidate.group in {"G3", "G5", "G7"}:
            score += 0.5
        return _clamp(score)

    def _citation_actionability_score(self, candidate: QuestionCandidate) -> float:
        lowered = candidate.question.casefold()
        score = 5.5
        if any(term in lowered for term in ("review", "reviews", "trustworthy", "complaints", "reputable", "safe")):
            score += 2.2
        if any(term in lowered for term in ("cost", "price", "pricing", "book", "schedule", "appointment", "quote")):
            score += 1.8
        if any(term in lowered for term in ("compare", "alternative", "better", "choose", "instead")):
            score += 1.5
        if candidate.metadata.get("offering"):
            score += 0.6
        if candidate.metadata.get("competitor"):
            score += 0.5
        return _clamp(score)

    def _specificity_score(self, candidate: QuestionCandidate) -> float:
        meta = candidate.metadata
        score = 4.5
        for key, weight in (
            ("offering", 1.7),
            ("competitor", 1.3),
            ("location", 1.0),
            ("goal", 0.9),
            ("persona", 0.8),
            ("product_brand", 0.7),
            ("category", 0.6),
        ):
            if meta.get(key):
                score += weight
        if meta.get("location_usage") == "fallback":
            score -= 0.8
        return _clamp(score)

    def _local_relevance_score(self, candidate: QuestionCandidate) -> float:
        usage = candidate.metadata.get("location_usage")
        if usage == "physical":
            return 9.0
        if usage == "service_area":
            return 8.0
        if usage == "visibility_market":
            return 5.8 if candidate.group in {"G1", "G3", "G5"} else 3.0
        return 5.0

    def _diversity_penalty(self, candidate: QuestionCandidate, selected: list[RankedQuestion]) -> float:
        penalty = 0.0
        for key, weight in (("offering", 0.35), ("competitor", 0.25), ("pattern", 0.22), ("location", 0.15)):
            value = candidate.metadata.get(key)
            if not value:
                continue
            count = sum(1 for item in selected if item.candidate.metadata.get(key) == value)
            if count:
                penalty += min(1.4, count * weight)
        return round(penalty, 3)

    def _rank_reason(self, ranked: RankedQuestion) -> str:
        scores = ranked.scores
        meta = ranked.candidate.metadata
        reasons: list[str] = []
        if scores["purchase_intent_score"] >= 8.5:
            reasons.append("high buyer intent")
        if scores["ai_visibility_opportunity_score"] >= 8.5:
            reasons.append("strong AI visibility opportunity")
        if scores["citation_actionability_score"] >= 8.0:
            reasons.append("likely to expose actionable citations")
        if meta.get("offering"):
            reasons.append(f"confirmed offering: {meta['offering']}")
        if meta.get("competitor"):
            reasons.append(f"competitor context: {meta['competitor']}")
        if meta.get("location") and meta.get("location_usage") != "fallback":
            reasons.append(f"location context: {meta['location']}")
        if not reasons:
            reasons.append("balanced context-aware coverage")
        return "High value: " + "; ".join(reasons[:4]) + "."

    def _row_from_ranked(self, ranked: RankedQuestion) -> dict[str, Any]:
        scores = ranked.scores
        return {
            "question": ranked.candidate.question,
            "group": ranked.candidate.group,
            "group_label": GROUP_LABELS[ranked.candidate.group],
            "group_rank": ranked.group_rank or "",
            "intent_score": scores["purchase_intent_score"],
            "popularity_score": "",
            "cpc_proxy_score": scores["commercial_proxy_score"],
            "final_rank_score": ranked.final_rank_score,
            "human_realism_score": scores["human_realism_score"],
            "ai_visibility_opportunity_score": scores["ai_visibility_opportunity_score"],
            "citation_actionability_score": scores["citation_actionability_score"],
            "specificity_score": scores["specificity_score"],
            "evidence_confidence_score": scores["evidence_confidence_score"],
            "local_relevance_score": scores["local_relevance_score"],
            "diversity_penalty": ranked.diversity_penalty,
            "rank_reason": ranked.rank_reason,
        }

    def _report_ranked(self, ranked: RankedQuestion) -> dict[str, Any]:
        report = self._report_candidate(
            ranked.candidate,
            selected=ranked.selected,
            rejected_reason=ranked.rejected_reason,
        )
        report.update(
            {
                "group_rank": ranked.group_rank,
                "scores": ranked.scores,
                "final_rank_score": ranked.final_rank_score,
                "diversity_penalty": ranked.diversity_penalty,
                "rank_reason": ranked.rank_reason,
            }
        )
        return report

    def _report_candidate(
        self,
        candidate: QuestionCandidate,
        *,
        selected: bool,
        rejected_reason: str | None,
    ) -> dict[str, Any]:
        return {
            "question": candidate.question,
            "group": candidate.group,
            "selected": selected,
            "rejected_reason": rejected_reason,
            "metadata": candidate.metadata,
        }


def profile_to_question_rows(
    profile: dict[str, Any],
    *,
    limit_per_group: int | None = None,
    selected_groups: Iterable[str] | None = None,
    candidate_limit_per_group: int | None = None,
    report_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    groups = [group for group in (selected_groups or GROUP_LABELS.keys()) if group in GROUP_LABELS]
    if limit_per_group is not None:
        group_targets = {group: limit_per_group for group in groups}
    else:
        group_targets = _parse_group_targets(groups)
    candidate_limit = candidate_limit_per_group or _env_positive_int(
        "AISO_QUESTION_CANDIDATE_LIMIT_PER_GROUP",
        DEFAULT_CANDIDATE_LIMIT_PER_GROUP,
    )
    candidates = _generate_candidates(profile, groups)
    ranker = QuestionValueRanker(candidate_limit_per_group=candidate_limit)
    rows, report = ranker.rank_and_select(candidates, group_targets=group_targets)
    if report_path:
        Path(report_path).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return rows
