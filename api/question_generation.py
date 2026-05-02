"""Context-aware, deterministic question generation and value ranking."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable, Mapping
import json
import os
import re
import unicodedata


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
    "G1": 8,
    "G2": 8,
    "G3": 8,
    "G4": 8,
    "G5": 8,
    "G6": 10,
    "G7": 10,
}

DEFAULT_EXTENDED_GROUP_TARGETS = {
    "G1": 16,
    "G2": 12,
    "G3": 16,
    "G4": 14,
    "G5": 12,
    "G6": 20,
    "G7": 20,
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
    "objective_alignment_score",
    "buyer_context_score",
    "evidence_confidence_score",
    "local_relevance_score",
    "diversity_penalty",
    "priority",
    "intent_subtype",
    "query_mode",
    "market_rationale",
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

HIGH_VALUE_INTENTS = {
    "adjacency",
    "aftercare",
    "concern",
    "first_time",
    "head_to_head",
    "method_comparison",
    "near_me",
    "outcome",
    "persona",
    "price",
    "transactional",
}

BAD_ENTITY_MARKERS = (
    "additional facial add-ons",
    "affected by nature",
    "book now",
    "can be booked as stand-alone",
    "defined, lifted, and polished",
    "everyday pollutants",
    "ideal for sensitive skin",
    "perfect for refreshing",
)

BANK_QC_FORBIDDEN_PATTERNS = (
    (re.compile(r"another local business", re.I), "unresolved competitor placeholder"),
    (re.compile(r"choose the best provider", re.I), "unresolved goal placeholder"),
    (re.compile(r"improve visibility for relevant buyer searches", re.I), "internal scan objective leaked into question"),
    (re.compile(r"\bnear me\b", re.I), "literal near-me query is unsupported in provider API runs"),
    (re.compile(r"\bin near me\b", re.I), "malformed near-me phrasing"),
    (re.compile(r"\banother approach\b", re.I), "vague comparison phrasing"),
    (re.compile(r"\bADD-?ONS?:?\b", re.I), "scraped add-on label"),
    (re.compile(r"✨"), "scraped emoji/noise"),
)

INTERNAL_SCAN_INTENT_MARKERS = (
    "improve visibility for relevant buyer searches",
    "high-intent buyer visibility",
    "ai visibility",
)

SKINCARE_MARKERS = (
    "acne",
    "aesthetic",
    "brow",
    "dermaplane",
    "facial",
    "lash",
    "medspa",
    "microneedling",
    "peel",
    "skin",
    "spa",
)

SKINCARE_MARKET_EXPANSION = [
    ("Cambridge, MA", "growth_market", 9.5),
    ("Back Bay Boston, MA", "growth_market", 9.4),
    ("Brighton Boston, MA", "growth_market", 9.1),
    ("Allston Boston, MA", "growth_market", 9.0),
    ("Beacon Hill Boston, MA", "growth_market", 8.9),
    ("Boston, MA", "growth_market", 8.8),
    ("Newton, MA", "core_market", 8.2),
    ("Brookline, MA", "core_market", 8.0),
    ("Chestnut Hill, MA", "secondary_market", 6.8),
    ("Needham, MA", "secondary_market", 6.4),
    ("Wellesley, MA", "secondary_market", 6.2),
]

LOCATION_QUALIFIERS = {
    "allston": "Allston Boston, MA",
    "back bay": "Back Bay Boston, MA",
    "beacon hill": "Beacon Hill Boston, MA",
    "boston": "Boston, MA",
    "brighton": "Brighton Boston, MA",
    "brookline": "Brookline, MA",
    "cambridge": "Cambridge, MA",
    "chestnut hill": "Chestnut Hill, MA",
    "greater boston": "Greater Boston, MA",
    "needham": "Needham, MA",
    "newton": "Newton, MA",
    "newton centre": "Newton Centre, MA",
    "newton center": "Newton Centre, MA",
    "wellesley": "Wellesley, MA",
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
    text = "".join(
        char
        for char in str(value or "")
        if not (unicodedata.category(char).startswith("C") or unicodedata.category(char) == "So")
    )
    return re.sub(r"\s+", " ", text).strip()


def _is_internal_scan_intent(value: Any) -> bool:
    lowered = _clean(value).casefold()
    return any(marker in lowered for marker in INTERNAL_SCAN_INTENT_MARKERS)


def _qualify_location_name(value: Any) -> str:
    clean = _clean(value)
    if not clean:
        return ""
    normalized = re.sub(r"[^a-z0-9]+", " ", clean.casefold()).strip()
    if normalized in LOCATION_QUALIFIERS:
        return LOCATION_QUALIFIERS[normalized]
    if re.search(r"\b(?:ma|massachusetts|boston|united states|usa)\b", normalized) or "," in clean:
        return clean
    return clean


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


def _looks_like_bad_entity(value: str) -> bool:
    clean = _clean(value)
    lowered = clean.casefold()
    if not clean:
        return True
    if any(marker in lowered for marker in BAD_ENTITY_MARKERS):
        return True
    if "✨" in clean or re.search(r"\bADD-?ONS?:?\b", clean, re.I):
        return True
    if len(clean) > 90 and re.search(r"[.;]", clean):
        return True
    if len(clean.split()) > 12 and not re.search(r"\b(?:consultation|combo|package)\b", lowered):
        return True
    if re.match(r"^(?:a|an|the)\s+(?:gentle|non-invasive|antioxidant|signature|advanced)\b", lowered):
        return True
    return False


def _is_street_address(value: str) -> bool:
    return bool(
        re.search(
            r"\b\d{2,5}\s+[^,]+?\b(?:avenue|ave|street|st|road|rd|drive|dr|boulevard|blvd|lane|ln|way)\b",
            value,
            re.I,
        )
    )


def _safe_entity_name(value: Any, *, allow_sentence: bool = False) -> str:
    clean = _clean(value)
    if _is_internal_scan_intent(clean):
        return ""
    if allow_sentence:
        clean = re.sub(r"\s*>?\s*(?:Book Now|Learn More|Get Directions)\s*$", "", clean, flags=re.I)
        return clean[:160].rstrip(" ,.;")
    if _looks_like_bad_entity(clean):
        return ""
    return clean


def _dedupe_location_pairs(values: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: set[str] = set()
    result: list[tuple[str, str]] = []
    for name, kind in values:
        name = _qualify_location_name(name)
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
        name = _safe_entity_name(item.get("name"), allow_sentence=key in {"personas", "goals"})
        if key in {"offerings", "competitors", "product_brands", "offering_groups"} and not name:
            continue
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
    cleaned = [(_qualify_location_name(name), kind) for name, kind in raw if _clean(name)]
    return _dedupe_location_pairs(cleaned) or [("your area", "fallback")]


def _is_skincare_context(profile: dict[str, Any]) -> bool:
    haystack = " ".join(
        [
            *[item.get("name", "") for item in _items(profile, "categories") if isinstance(item, dict)],
            *[item.get("name", "") for item in _items(profile, "offerings") if isinstance(item, dict)],
            *[item.get("name", "") for item in _items(profile, "offering_groups") if isinstance(item, dict)],
        ]
    ).casefold()
    return any(marker in haystack for marker in SKINCARE_MARKERS)


def _market_locations(profile: dict[str, Any]) -> list[dict[str, Any]]:
    base: list[dict[str, Any]] = []
    local_candidates: list[str] = []
    for name, usage in _locations(profile, "g1"):
        if usage == "fallback" or _is_street_address(name):
            continue
        if usage in {"physical", "service_area"}:
            local_candidates.append(name)
        weight = {"physical": 8.4, "service_area": 7.8, "visibility_market": 5.8}.get(usage, 5.0)
        base.append({"name": name, "usage": usage, "weight": weight})
    if local_candidates:
        base.insert(0, {"name": local_candidates[0], "usage": "local_proxy", "weight": 10.0})
    if _is_skincare_context(profile):
        base.extend({"name": name, "usage": usage, "weight": weight} for name, usage, weight in SKINCARE_MARKET_EXPANSION)

    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for item in sorted(base, key=lambda row: float(row["weight"]), reverse=True):
        key = re.sub(r"[^a-z0-9]+", " ", item["name"].casefold()).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result or [{"name": "local area", "usage": "fallback", "weight": 4.0}]


def _generic_offering_name(name: str) -> str:
    lowered = name.casefold()
    replacements = (
        ("balanced bliss", "classic facial"),
        ("brightening bliss", "vitamin C facial"),
        ("deluxe dermaplane", "dermaplane facial"),
        ("hydroboost", "hydrodermabrasion facial"),
        ("hydro boost", "hydrodermabrasion facial"),
        ("acne clearing oxygen", "oxygen facial"),
        ("lift and tighten", "anti-aging facial"),
        ("dermapeel", "dermaplane and chemical peel combo"),
        ("micro-dermabrasion", "microdermabrasion"),
        ("microdermabrasion", "microdermabrasion"),
        ("collagen boost microneedling", "microneedling"),
        ("revitalizing bliss", "revitalizing facial"),
        ("chemical peel", "chemical peel"),
    )
    for marker, generic in replacements:
        if marker in lowered:
            return generic
    if "brow" in lowered or "lash" in lowered:
        return "brow and lash services"
    clean = re.sub(r"\b(?:classic|signature|deluxe|renewal|plus)\b", "", name, flags=re.I)
    return _clean(clean).lower() or name.lower()


def _search_terms_for_offering(offering: dict[str, Any]) -> dict[str, Any]:
    name = _clean(offering.get("name"))
    generic = _clean(offering.get("generic_name") or offering.get("generic_term") or _generic_offering_name(name))
    aliases = [
        _clean(alias)
        for alias in offering.get("aliases", [])
        if isinstance(offering.get("aliases"), list) and _clean(alias)
    ]
    lowered = f"{name} {generic} {' '.join(aliases)}".casefold()
    concerns: list[str] = []
    outcomes: list[str] = []
    comparisons: list[str] = []
    adjacency: list[str] = []

    if any(term in lowered for term in ("chemical peel", "vitamin c", "brightening", "dermapeel")):
        concerns += ["hyperpigmentation", "melasma", "dark spots", "acne marks", "sun damage"]
        outcomes += ["brighter skin", "even skin tone", "smoother texture"]
        comparisons += ["chemical peel vs laser", "chemical peel vs microneedling"]
    if any(term in lowered for term in ("dermaplane", "microdermabrasion", "hydrodermabrasion")):
        concerns += ["blackheads", "clogged pores", "dull skin", "rough texture"]
        outcomes += ["glowing skin", "smooth skin before an event"]
        comparisons += ["dermaplane vs microdermabrasion", "hydrodermabrasion vs HydraFacial"]
        adjacency += ["HydraFacial alternative"]
    if any(term in lowered for term in ("acne", "oxygen")):
        concerns += ["acne", "breakouts", "oily skin", "congested skin"]
        outcomes += ["clearer skin", "calmer acne-prone skin"]
    if any(term in lowered for term in ("anti-aging", "lift", "tighten", "microneedling", "collagen")):
        concerns += ["fine lines", "sagging skin", "skin laxity"]
        outcomes += ["firmer skin", "non-injectable anti-aging results"]
        comparisons += ["microneedling vs chemical peel", "microneedling vs laser"]
        adjacency += ["Botox alternative", "Morpheus8 alternative"]
    if any(term in lowered for term in ("facial", "classic", "signature")):
        concerns += ["sensitive skin", "first facial", "dull skin"]
        outcomes += ["hydrated skin", "pre-event glow"]
    if any(term in lowered for term in ("brow", "lash")):
        concerns += ["uneven brows", "straight lashes"]
        outcomes += ["natural-looking brows and lashes"]

    explicit_concerns = offering.get("concerns") if isinstance(offering.get("concerns"), list) else []
    explicit_outcomes = offering.get("outcomes") if isinstance(offering.get("outcomes"), list) else []
    explicit_comparisons = offering.get("comparisons") if isinstance(offering.get("comparisons"), list) else []
    explicit_adjacency = offering.get("adjacency") if isinstance(offering.get("adjacency"), list) else []

    return {
        "branded": name,
        "generic": generic,
        "aliases": _dedupe(aliases),
        "concerns": _dedupe([*(str(item) for item in explicit_concerns), *concerns])[:8],
        "outcomes": _dedupe([*(str(item) for item in explicit_outcomes), *outcomes])[:6],
        "comparisons": _dedupe([*(str(item) for item in explicit_comparisons), *comparisons])[:6],
        "adjacency": _dedupe([*(str(item) for item in explicit_adjacency), *adjacency])[:4],
    }


def _scan_objective(profile: dict[str, Any]) -> dict[str, str]:
    raw = profile.get("scan_objective")
    if not isinstance(raw, dict):
        return {
            "objective": "high_intent_visibility",
            "label": "Improve high-intent buyer visibility",
            "custom": "",
        }
    objective = _clean(raw.get("objective")) or "high_intent_visibility"
    label = _clean(raw.get("label")) or objective.replace("_", " ")
    custom = _clean(raw.get("custom"))
    return {"objective": objective, "label": label, "custom": custom}


def _buyer_contexts(profile: dict[str, Any], goals: list[dict[str, Any]], personas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    raw = profile.get("buyer_contexts")
    result: list[dict[str, Any]] = []
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            label = _clean(item.get("label") or item.get("audience_type"))
            problem = _clean(item.get("problem"))
            outcome = _clean(item.get("desired_outcome") or item.get("outcome"))
            constraint = _clean(item.get("constraints") or item.get("constraint"))
            criteria = _clean(item.get("decision_criteria"))
            if _is_internal_scan_intent(problem):
                problem = ""
            if _is_internal_scan_intent(outcome):
                outcome = ""
            if _is_internal_scan_intent(constraint):
                constraint = ""
            if _is_internal_scan_intent(criteria):
                criteria = ""
            if not label or not any((problem, outcome, constraint, criteria)):
                continue
            result.append(
                {
                    "label": label[:90],
                    "audience_type": _clean(item.get("audience_type"))[:90],
                    "problem": problem[:120],
                    "desired_outcome": outcome[:120],
                    "trigger_event": _clean(item.get("trigger_event"))[:120],
                    "constraints": constraint[:120],
                    "decision_criteria": criteria[:140],
                    "priority": _clean(item.get("priority")) or "medium",
                    "source_url": _clean(item.get("source_url")) or "manual_onboarding",
                    "confidence": item.get("confidence", 0.7),
                }
            )
    if result:
        return result[:10]

    first_persona = _clean(personas[0].get("name")) if personas else "target customers"
    first_goal = _clean(goals[0].get("name")) if goals else "choose the right provider"
    if _is_internal_scan_intent(first_goal):
        first_goal = "choose the right provider"
    return [
        {
            "label": first_persona,
            "audience_type": first_persona,
            "problem": first_goal,
            "desired_outcome": "make a confident decision",
            "trigger_event": "",
            "constraints": "",
            "decision_criteria": "trust, relevance, proof, and fit",
            "priority": "medium",
            "source_url": "derived_context",
            "confidence": 0.45,
        }
    ]


def _post_purchase_templates(profile: dict[str, Any], category_name: str, generic_offering: str) -> tuple[str, ...]:
    haystack = f"{category_name} {generic_offering}".casefold()
    if _is_skincare_context(profile):
        return (
            f"{generic_offering} aftercare?",
            f"what should I avoid after {generic_offering}?",
            f"{generic_offering} recovery time?",
        )
    if any(term in haystack for term in ("software", "saas", "platform", "crm", "app", "tool")):
        return (
            f"what support should I expect after buying {category_name}?",
            f"{category_name} onboarding checklist?",
            f"{category_name} implementation timeline?",
        )
    if any(term in haystack for term in ("contractor", "repair", "plumber", "roof", "hvac", "electrician", "home service")):
        return (
            f"what happens after a {category_name} service visit?",
            f"{category_name} warranty questions?",
            f"how to prepare for a {category_name} appointment?",
        )
    return (
        f"what should I expect after choosing {category_name}?",
        f"what support should I expect after booking {generic_offering}?",
    )


def _competitor_tier(competitor: dict[str, Any]) -> str:
    explicit = _clean(competitor.get("tier") or competitor.get("competitor_tier")).casefold()
    if explicit in {"direct", "adjacent"}:
        return explicit
    name = _clean(competitor.get("name")).casefold()
    if any(term in name for term in ("medical", "aesthetic", "medspa", "dr.", "doctor", "botox", "laser")):
        return "adjacent"
    return "direct"


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


def _parse_group_targets(
    selected_groups: Iterable[str] | None = None,
    *,
    env_name: str = "AISO_QUESTION_GROUP_TARGETS",
    total_env_name: str = "AISO_QUESTION_FINAL_TOTAL",
    default_targets: Mapping[str, int] | None = None,
) -> dict[str, int]:
    selected = list(selected_groups or GROUP_LABELS.keys())
    base_targets = default_targets or DEFAULT_GROUP_TARGETS
    targets = {group: base_targets.get(group, 12) for group in selected if group in GROUP_LABELS}
    raw = os.environ.get(env_name, "").strip()
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

    total_raw = os.environ.get(total_env_name, "").strip()
    if total_raw:
        try:
            total = int(total_raw)
        except ValueError:
            total = 0
        if total > 0 and selected:
            weights = {group: base_targets.get(group, 12) for group in selected if group in GROUP_LABELS}
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
    if "another local business" in q or "choose the best provider" in q or "another approach" in q:
        return False, "reject fallback placeholder"
    if "near me" in q:
        return False, "reject literal near-me query for provider API run"
    if _is_internal_scan_intent(candidate.question):
        return False, "reject internal scan objective in question"
    if "✨" in candidate.question or re.search(r"\bADD-?ONS?:?\b", candidate.question, re.I):
        return False, "reject scraped formatting noise"
    if _is_street_address(candidate.question):
        return False, "reject street-address query"
    for key in ("offering", "branded_offering", "competitor", "goal", "persona", "offering_group"):
        value = _clean(meta.get(key))
        if value and _looks_like_bad_entity(value):
            return False, "reject noisy extracted entity"
    if not candidate.question.endswith("?"):
        return False, "reject non-question fragment"
    if len(_content_tokens(candidate.question)) < 3:
        return False, "reject low-information question"
    if len(candidate.question) > 190:
        return False, "reject overlong generated question"

    compared = any(token in q for token in (" vs ", " versus ", " compare ", " compared with ", " better than "))
    if compared and {left, right} == {"offering", "business"}:
        return False, "reject offering-vs-business comparison"
    if compared and meta.get("competitor_tier") == "adjacent" and candidate.group == "G7":
        return False, "reject adjacent competitor head-to-head"
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


def audit_question_bank_rows(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Run bank-level QC over the final rows that will be written for collection."""
    materialized = [dict(row) for row in rows]
    issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    questions: list[str] = []
    group_counts: dict[str, int] = {}
    subtype_counts: dict[str, int] = {}
    mode_counts: dict[str, int] = {}
    priority_counts: dict[str, int] = {}
    opener_counts: dict[str, int] = {}

    if not materialized:
        issues.append({"severity": "error", "message": "question bank is empty"})

    for index, row in enumerate(materialized, start=1):
        question = _clean(row.get("question"))
        questions.append(question)
        group = _clean(row.get("group"))
        subtype = _clean(row.get("intent_subtype"))
        mode = _clean(row.get("query_mode"))
        priority = _clean(row.get("priority")) or "medium"
        group_counts[group] = group_counts.get(group, 0) + 1
        subtype_counts[subtype] = subtype_counts.get(subtype, 0) + 1
        mode_counts[mode] = mode_counts.get(mode, 0) + 1
        priority_counts[priority] = priority_counts.get(priority, 0) + 1

        opener = " ".join(question.casefold().split()[:4])
        if opener:
            opener_counts[opener] = opener_counts.get(opener, 0) + 1

        if not question:
            issues.append({"severity": "error", "row": index, "message": "empty question"})
            continue
        if not question.endswith("?"):
            issues.append({"severity": "error", "row": index, "question": question, "message": "question must end with ?"})
        if len(question) > 190:
            issues.append({"severity": "error", "row": index, "question": question, "message": "question is too long"})
        if _is_street_address(question):
            issues.append({"severity": "error", "row": index, "question": question, "message": "street address used as search geography"})
        for pattern, message in BANK_QC_FORBIDDEN_PATTERNS:
            if pattern.search(question):
                issues.append({"severity": "error", "row": index, "question": question, "message": message})

    duplicates = sorted(question for question in set(questions) if question and questions.count(question) > 1)
    for question in duplicates:
        issues.append({"severity": "error", "question": question, "message": "duplicate final question"})

    total = len(materialized)
    if total:
        most_common_opener = max(opener_counts.items(), key=lambda item: item[1], default=("", 0))
        if most_common_opener[1] / total > 0.35:
            warnings.append(
                {
                    "severity": "warning",
                    "message": "question phrasing may be over-templated",
                    "opener": most_common_opener[0],
                    "count": most_common_opener[1],
                }
            )
        if not any(" near " in question.casefold() for question in questions):
            warnings.append({"severity": "warning", "message": "bank has no localized near-query proxies"})
        if not any(group_counts.get(group, 0) for group in ("G3", "G7")):
            warnings.append({"severity": "warning", "message": "bank has no competitor/head-to-head coverage"})
        if not any(subtype_counts.get(subtype, 0) for subtype in ("concern", "method_comparison", "adjacency", "price")):
            warnings.append({"severity": "warning", "message": "bank is missing major market-intent layers"})
        if mode_counts.get("keyword", 0) == 0:
            warnings.append({"severity": "warning", "message": "bank has no keyword-form queries"})

    return {
        "passed": not issues,
        "issue_count": len(issues),
        "warning_count": len(warnings),
        "issues": issues,
        "warnings": warnings,
        "coverage": {
            "total_questions": total,
            "groups": group_counts,
            "intent_subtypes": subtype_counts,
            "query_modes": mode_counts,
            "priorities": priority_counts,
        },
    }


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
    competitors = [
        item
        for item in _named_items(profile, "competitors", fallback="", item_type="competitor_business", limit=12)
        if item["name"]
    ]
    goals = [
        item
        for item in _named_items(profile, "goals", fallback="", item_type="goal", limit=12)
        if item["name"] and item["name"].casefold() != "choose the best provider" and not _is_internal_scan_intent(item["name"])
    ]
    personas = [
        item
        for item in _named_items(profile, "personas", fallback="", item_type="persona", limit=12)
        if item["name"] and not _looks_like_bad_entity(item["name"])
    ] or [_fallback_item("first-time customers", "persona", 0.45)]
    scan_objective = _scan_objective(profile)
    buyer_contexts = _buyer_contexts(profile, goals, personas)
    offering_terms = [(offering, _search_terms_for_offering(offering)) for offering in offerings]
    market_locations = _market_locations(profile)
    direct_competitors = [item for item in competitors if _competitor_tier(item) == "direct"]
    adjacent_competitors = [item for item in competitors if _competitor_tier(item) == "adjacent"]
    category_name = categories[0]["name"]
    group_set = set(selected_groups)

    candidates: list[QuestionCandidate] = []

    if "G1" in group_set:
        for location in market_locations[:10]:
            location_name = location["name"]
            if location["usage"] == "local_proxy":
                location_questions = [
                    (f"best {category_name} near {location_name}", "near_me", "keyword"),
                    (f"{category_name} near {location_name}", "near_me", "keyword"),
                    (f"top rated {category_name} near {location_name}", "near_me", "keyword"),
                    (f"Which {category_name} should I choose near {location_name}?", "near_me", "conversational"),
                ]
            else:
                location_questions = [
                    (f"best {category_name} {location_name}", "local_discovery", "keyword"),
                    (f"{category_name} {location_name}", "local_discovery", "keyword"),
                    (f"top rated {category_name} {location_name}", "local_discovery", "keyword"),
                ]
                location_questions.append((f"Which {category_name} should I choose in {location_name}?", "local_discovery", "conversational"))
            for question, subtype, mode in location_questions:
                _add_candidate(
                    candidates,
                    question if question.endswith("?") else f"{question}?",
                    "G1",
                    evidence_items=(categories[0],),
                    category=category_name,
                    location=location_name,
                    location_usage=location["usage"],
                    geography_weight=location["weight"],
                    intent_subtype=subtype,
                    query_mode=mode,
                    priority="high" if location["usage"] in {"local_proxy", "growth_market"} else "medium",
                    pattern="category_discovery",
                    left_type="category",
                )
        for offering, terms in offering_terms:
            for location in market_locations[:8]:
                question = (
                    f"best {terms['generic']} near {location['name']}?"
                    if location["usage"] == "local_proxy"
                    else f"best {terms['generic']} {location['name']}?"
                )
                _add_candidate(
                    candidates,
                    question,
                    "G1",
                    evidence_items=(offering,),
                    offering=terms["generic"],
                    branded_offering=terms["branded"],
                    location=location["name"],
                    location_usage=location["usage"],
                    geography_weight=location["weight"],
                    intent_subtype="near_me" if location["usage"] == "local_proxy" else "local_discovery",
                    query_mode="keyword",
                    priority="high" if location["usage"] in {"local_proxy", "growth_market"} else "medium",
                    pattern="generic_offering_discovery",
                    left_type="offering",
                )

    if "G2" in group_set:
        for offering, terms in offering_terms:
            for question, subtype, mode, priority in (
                (f"Does {client} offer {terms['branded']}?", "branded_direct", "conversational", "high"),
                (f"{client} {terms['generic']}?", "branded_direct", "keyword", "high"),
                (f"Is {terms['branded']} at {client} worth it?", "branded_direct", "conversational", "medium"),
                (f"How much does {terms['branded']} cost at {client}?", "price", "conversational", "high"),
            ):
                _add_candidate(
                    candidates,
                    question,
                    "G2",
                    evidence_items=(offering,),
                    offering=terms["branded"],
                    generic_offering=terms["generic"],
                    left_type="business",
                    right_type="offering",
                    intent_subtype=subtype,
                    query_mode=mode,
                    priority=priority,
                    pattern="branded_offering",
                )
        for group_name in offering_groups:
            _add_candidate(
                candidates,
                f"Which services are included in {group_name['name']} at {client}?",
                "G2",
                evidence_items=(group_name,),
                offering_group=group_name["name"],
                left_type="business",
                right_type="offering_group",
                offering_group_bookable=False,
                intent_subtype="branded_direct",
                query_mode="conversational",
                priority="low",
                pattern="branded_group",
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
                    intent_subtype="branded_direct",
                    query_mode="conversational",
                    priority="low",
                    pattern="direct_brand_product",
                )

    if "G3" in group_set:
        for competitor in direct_competitors:
            for category in categories[:4]:
                for location in market_locations[:5]:
                    if location["usage"] == "local_proxy":
                        competitor_questions = (
                            f"What are the best alternatives to {competitor['name']} for {category['name']} near {location['name']}?",
                            f"{competitor['name']} alternatives near {location['name']}?",
                        )
                    else:
                        competitor_questions = (
                            f"What are the best alternatives to {competitor['name']} for {category['name']} in {location['name']}?",
                            f"{competitor['name']} alternatives {location['name']}?",
                        )
                    for question in competitor_questions:
                        _add_candidate(
                            candidates,
                            question,
                            "G3",
                            evidence_items=(competitor, category),
                            location_usage=location["usage"],
                            location=location["name"],
                            geography_weight=location["weight"],
                            competitor=competitor["name"],
                            competitor_tier="direct",
                            category=category["name"],
                            left_type="business",
                            right_type="business",
                            intent_subtype="competitor_swap",
                            query_mode="keyword" if " alternatives " in f" {question.casefold()} " else "conversational",
                            priority="high",
                            pattern="competitor_alternative",
                        )
            for offering, terms in offering_terms[:8]:
                for template in (
                    "What is the best alternative to {competitor} for {offering}?",
                    "{competitor} vs {client} for {offering}?",
                ):
                    _add_candidate(
                        candidates,
                        template.format(client=client, competitor=competitor["name"], offering=terms["generic"]),
                        "G3",
                        evidence_items=(competitor, offering),
                        competitor=competitor["name"],
                        competitor_tier="direct",
                        offering=terms["generic"],
                        branded_offering=terms["branded"],
                        left_type="business",
                        right_type="business",
                        intent_subtype="competitor_swap",
                        query_mode="keyword" if " vs " in template else "conversational",
                        priority="high",
                        pattern="offering_comparison",
                    )
        for competitor in adjacent_competitors:
            for location in market_locations[:4]:
                _add_candidate(
                    candidates,
                    f"{category_name} vs medspa {location['name']}?",
                    "G3",
                    evidence_items=(competitor, categories[0]),
                    competitor=competitor["name"],
                    competitor_tier="adjacent",
                    category=category_name,
                    location=location["name"],
                    location_usage=location["usage"],
                    geography_weight=location["weight"],
                    left_type="category",
                    right_type="business",
                    intent_subtype="adjacency",
                    query_mode="keyword",
                    priority="medium",
                    pattern="adjacent_category",
                )

    if "G4" in group_set:
        booking_locations = [item for item in market_locations if item["usage"] != "visibility_market"][:8]
        for offering, terms in offering_terms:
            for location in booking_locations:
                if location["usage"] == "local_proxy":
                    transactional_questions = (
                        (f"{terms['generic']} cost near {location['name']}", "price", "keyword"),
                        (f"how much does {terms['generic']} cost near {location['name']}?", "price", "conversational"),
                        (f"book {terms['generic']} near {location['name']}", "transactional", "keyword"),
                        (f"Where can I book {terms['generic']} near {location['name']}?", "transactional", "conversational"),
                    )
                else:
                    transactional_questions = (
                        (f"{terms['generic']} cost {location['name']}", "price", "keyword"),
                        (f"how much does {terms['generic']} cost in {location['name']}?", "price", "conversational"),
                        (f"book {terms['generic']} in {location['name']}", "transactional", "keyword"),
                        (f"Where can I book {terms['generic']} near {location['name']}?", "transactional", "conversational"),
                    )
                for question, subtype, mode in transactional_questions:
                    _add_candidate(
                        candidates,
                        question if question.endswith("?") else f"{question}?",
                        "G4",
                        evidence_items=(offering,),
                        location_usage=location["usage"],
                        location=location["name"],
                        geography_weight=location["weight"],
                        offering=terms["generic"],
                        branded_offering=terms["branded"],
                        left_type="business",
                        right_type="offering",
                        intent_subtype=subtype,
                        query_mode=mode,
                        priority="high",
                        pattern=f"{subtype}_offering",
                    )
        for context in buyer_contexts[:6]:
            label = context["label"]
            problem = context.get("problem") or context.get("desired_outcome") or "a purchase decision"
            _add_candidate(
                candidates,
                f"how much should {label} budget for {category_name}?",
                "G4",
                evidence_items=(categories[0],),
                category=category_name,
                buyer_context=label,
                problem=problem,
                scan_objective=scan_objective["objective"],
                left_type="category",
                intent_subtype="price",
                query_mode="conversational",
                priority="medium",
                pattern="buyer_budget",
            )

    if "G5" in group_set:
        for offering, terms in offering_terms[:12]:
            for template in (
                "{client} reviews?",
                "Is {client} worth it for {offering}?",
                "Is {offering} safe for sensitive skin?",
                "{offering} recovery time?",
                "{offering} side effects?",
            ):
                _add_candidate(
                    candidates,
                    template.format(client=client, offering=terms["generic"]),
                    "G5",
                    evidence_items=(offering,),
                    offering=terms["generic"],
                    branded_offering=terms["branded"],
                    left_type="business",
                    right_type="offering",
                    intent_subtype="safety" if any(term in template for term in ("safe", "recovery", "side effects")) else "branded_trust",
                    query_mode="keyword" if template.startswith(("{client}", "{offering}")) else "conversational",
                    priority="high" if "reviews" in template else "medium",
                    pattern="trust_safety",
                )
            for question in _post_purchase_templates(profile, category_name, terms["generic"])[:2]:
                _add_candidate(
                    candidates,
                    question,
                    "G5",
                    evidence_items=(offering,),
                    offering=terms["generic"],
                    branded_offering=terms["branded"],
                    left_type="offering",
                    intent_subtype="aftercare",
                    query_mode="keyword",
                    priority="medium",
                    pattern="post_purchase",
                )
        for context in buyer_contexts[:6]:
            constraint = context.get("constraints") or context.get("problem")
            if constraint:
                _add_candidate(
                    candidates,
                    f"is {category_name} safe for {constraint}?",
                    "G5",
                    evidence_items=(categories[0],),
                    category=category_name,
                    buyer_context=context["label"],
                    problem=context.get("problem"),
                    constraint=constraint,
                    scan_objective=scan_objective["objective"],
                    left_type="category",
                    intent_subtype="safety",
                    query_mode="conversational",
                    priority="medium",
                    pattern="buyer_risk",
                )
        for competitor in direct_competitors[:6]:
            for template in (
                "Which has stronger reviews, {client} or {competitor}?",
                "Is {client} more trustworthy than {competitor}?",
                "{client} vs {competitor} reviews?",
            ):
                _add_candidate(
                    candidates,
                    template.format(client=client, competitor=competitor["name"]),
                    "G5",
                    evidence_items=(competitor,),
                    competitor=competitor["name"],
                    competitor_tier="direct",
                    left_type="business",
                    right_type="business",
                    intent_subtype="branded_trust",
                    query_mode="keyword" if " vs " in template else "conversational",
                    priority="high",
                    pattern="trust_competitor",
                )

    if "G6" in group_set:
        for offering, terms in offering_terms[:12]:
            for concern in terms["concerns"][:6]:
                for location in market_locations[:4]:
                    _add_candidate(
                        candidates,
                        f"best treatment for {concern} {location['name']}?",
                        "G6",
                        evidence_items=(offering,),
                        offering=terms["generic"],
                        branded_offering=terms["branded"],
                        concern=concern,
                        location=location["name"],
                        location_usage=location["usage"],
                        geography_weight=location["weight"],
                        left_type="offering",
                        intent_subtype="concern",
                        query_mode="keyword",
                        priority="high",
                        pattern="concern_treatment",
                    )
            for outcome in terms["outcomes"][:4]:
                for template in (
                    "how to get {outcome}?",
                    "best facial for {outcome}?",
                ):
                    _add_candidate(
                        candidates,
                        template.format(outcome=outcome),
                        "G6",
                        evidence_items=(offering,),
                        offering=terms["generic"],
                        branded_offering=terms["branded"],
                        goal=outcome,
                        left_type="offering",
                        intent_subtype="outcome",
                        query_mode="keyword",
                        priority="high",
                        pattern="outcome_fit",
                    )
        for persona in personas[:5]:
            for offering, terms in offering_terms[:6]:
                _add_candidate(
                    candidates,
                    f"Is {terms['generic']} good for {persona['name']}?",
                    "G6",
                    evidence_items=(offering, persona),
                    offering=terms["generic"],
                    branded_offering=terms["branded"],
                    persona=persona["name"],
                    left_type="offering",
                    right_type="persona",
                    intent_subtype="persona",
                    query_mode="conversational",
                    priority="medium",
                    pattern="persona_fit",
                )
        for context in buyer_contexts[:8]:
            label = context["label"]
            problem = context.get("problem")
            outcome = context.get("desired_outcome")
            constraint = context.get("constraints")
            criteria = context.get("decision_criteria")
            if problem:
                _add_candidate(
                    candidates,
                    f"best {category_name} for {problem}?",
                    "G6",
                    evidence_items=(categories[0],),
                    category=category_name,
                    buyer_context=label,
                    problem=problem,
                    scan_objective=scan_objective["objective"],
                    left_type="category",
                    intent_subtype="concern",
                    query_mode="keyword",
                    priority="high" if context.get("priority") == "high" else "medium",
                    pattern="buyer_problem",
                )
            if outcome:
                _add_candidate(
                    candidates,
                    f"how to {outcome}?",
                    "G6",
                    evidence_items=(categories[0],),
                    category=category_name,
                    buyer_context=label,
                    goal=outcome,
                    scan_objective=scan_objective["objective"],
                    left_type="category",
                    intent_subtype="outcome",
                    query_mode="keyword",
                    priority="high" if context.get("priority") == "high" else "medium",
                    pattern="buyer_outcome",
                )
            if constraint:
                _add_candidate(
                    candidates,
                    f"{category_name} for {constraint}?",
                    "G6",
                    evidence_items=(categories[0],),
                    category=category_name,
                    buyer_context=label,
                    constraint=constraint,
                    scan_objective=scan_objective["objective"],
                    left_type="category",
                    intent_subtype="persona",
                    query_mode="keyword",
                    priority="medium",
                    pattern="buyer_constraint",
                )
            if criteria:
                _add_candidate(
                    candidates,
                    f"what should {label} look for when choosing {category_name}?",
                    "G6",
                    evidence_items=(categories[0],),
                    category=category_name,
                    buyer_context=label,
                    decision_criteria=criteria,
                    scan_objective=scan_objective["objective"],
                    left_type="category",
                    intent_subtype="first_time",
                    query_mode="conversational",
                    priority="medium",
                    pattern="buyer_decision_criteria",
                )
        occasion_questions = (
            ("wedding facial timeline", "facial before vacation", "pre-event glow treatment")
            if _is_skincare_context(profile)
            else (
                f"{category_name} buying timeline",
                f"{category_name} before a major decision",
                f"when should I contact a {category_name} provider",
            )
        )
        for occasion in occasion_questions:
            _add_candidate(
                candidates,
                f"{occasion}?",
                "G6",
                evidence_items=(categories[0],),
                category=category_name,
                goal=occasion,
                intent_subtype="occasion",
                query_mode="keyword",
                priority="medium",
                pattern="occasion",
            )
        education_questions = (
            ("first facial what to expect?", "do I need a consultation before a facial?", "how often should I get a facial?")
            if _is_skincare_context(profile)
            else (
                f"first time choosing {category_name} what to expect?",
                f"do I need a consultation before choosing {category_name}?",
                f"how often should I review my {category_name} provider?",
            )
        )
        for question in education_questions:
            _add_candidate(
                candidates,
                question,
                "G6",
                evidence_items=(categories[0],),
                category=category_name,
                intent_subtype="first_time" if "first" in question or "consultation" in question else "timing",
                query_mode="keyword",
                priority="medium",
                pattern="education_timing",
            )

    if "G7" in group_set:
        local_target = next((item for item in market_locations if item["usage"] == "local_proxy"), market_locations[0])
        local_phrase = f"near {local_target['name']}" if local_target["usage"] == "local_proxy" else f"in {local_target['name']}"
        for offering, terms in offering_terms[:10]:
            base_comparisons = list(terms["comparisons"][:5])
            if not base_comparisons:
                base_comparisons = [
                    f"{terms['generic']} vs other {category_name} options",
                    f"{terms['generic']} vs premium {category_name}",
                    f"how should I compare {terms['generic']} options",
                ]
            for comparison in base_comparisons:
                _add_candidate(
                    candidates,
                    f"{comparison}?",
                    "G7",
                    evidence_items=(offering,),
                    offering=terms["generic"],
                    branded_offering=terms["branded"],
                    left_type="method",
                    right_type="method",
                    intent_subtype="method_comparison",
                    query_mode="keyword",
                    priority="high",
                    pattern="method_comparison",
                )
            adjacency_terms = list(terms["adjacency"][:3])
            if not adjacency_terms:
                adjacency_terms = [f"alternatives to {terms['generic']}", f"{terms['generic']} alternatives"]
            for adjacent in adjacency_terms:
                _add_candidate(
                    candidates,
                    f"{adjacent} {local_phrase}?",
                    "G7",
                    evidence_items=(offering,),
                    offering=terms["generic"],
                    branded_offering=terms["branded"],
                    left_type="offering",
                    right_type="adjacent_service",
                    intent_subtype="adjacency",
                    query_mode="keyword",
                    priority="high",
                    pattern="adjacency_intercept",
                )
        if _is_skincare_context(profile):
            for question, subtype in (
                (f"HydraFacial alternative {local_phrase}?", "adjacency"),
                (f"hydrodermabrasion vs HydraFacial {local_phrase}?", "method_comparison"),
                (f"facial spa vs medspa {local_phrase}?", "adjacency"),
                (f"Botox alternative for anti-aging skin {local_phrase}?", "adjacency"),
            ):
                _add_candidate(
                    candidates,
                    question,
                    "G7",
                    evidence_items=(categories[0],),
                    category=category_name,
                    location=local_target["name"],
                    location_usage=local_target["usage"],
                    geography_weight=local_target["weight"],
                    left_type="method",
                    right_type="adjacent_service",
                    intent_subtype=subtype,
                    query_mode="keyword",
                    priority="high",
                    pattern="skincare_adjacency",
                )
        for competitor in direct_competitors[:8]:
            for offering, terms in offering_terms[:8]:
                for template in (
                    "Which is better for {offering}: {client} or {competitor}?",
                    "Which has better reviews for {offering}, {client} or {competitor}?",
                    "{client} vs {competitor} for {offering}?",
                ):
                    _add_candidate(
                        candidates,
                        template.format(client=client, competitor=competitor["name"], offering=terms["generic"]),
                        "G7",
                        evidence_items=(competitor, offering),
                        competitor=competitor["name"],
                        competitor_tier="direct",
                        offering=terms["generic"],
                        branded_offering=terms["branded"],
                        left_type="business",
                        right_type="business",
                        intent_subtype="head_to_head",
                        query_mode="keyword" if " vs " in template else "conversational",
                        priority="high",
                        pattern="head_to_head_offering",
                    )

    for candidate in candidates:
        candidate.metadata.setdefault("scan_objective", scan_objective["objective"])
        candidate.metadata.setdefault("scan_objective_label", scan_objective["label"])
        if scan_objective.get("custom"):
            candidate.metadata.setdefault("scan_objective_custom", scan_objective["custom"])

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
        subtype = candidate.metadata.get("intent_subtype")
        priority_bonus = {"high": 0.8, "medium": 0.25, "low": -0.35}.get(candidate.metadata.get("priority"), 0.0)
        subtype_bonus = 0.65 if subtype in HIGH_VALUE_INTENTS else 0.0
        purchase = _clamp(
            GROUP_INTENT_BASE.get(group, 5.0)
            + _term_score(q, PURCHASE_TERMS) * 0.55
            + _term_score(q, COMPARISON_TERMS) * 0.25
            + priority_bonus
            + subtype_bonus
        )
        commercial = _clamp(
            GROUP_COMMERCIAL_BASE.get(group, 5.0)
            + _term_score(q, PURCHASE_TERMS) * 0.35
            + _term_score(q, COMPARISON_TERMS) * 0.2
            + priority_bonus
        )
        human = self._human_realism_score(candidate)
        opportunity = self._visibility_opportunity_score(candidate)
        actionability = self._citation_actionability_score(candidate)
        specificity = self._specificity_score(candidate)
        objective = self._objective_alignment_score(candidate)
        buyer_context = self._buyer_context_score(candidate)
        evidence = _clamp(float(candidate.metadata.get("evidence_confidence", 0.55)) * 10.0)
        local = self._local_relevance_score(candidate)
        return {
            "human_realism_score": human,
            "purchase_intent_score": purchase,
            "ai_visibility_opportunity_score": opportunity,
            "citation_actionability_score": actionability,
            "specificity_score": specificity,
            "objective_alignment_score": objective,
            "buyer_context_score": buyer_context,
            "evidence_confidence_score": evidence,
            "commercial_proxy_score": commercial,
            "local_relevance_score": local,
        }

    def _final_score(self, scores: Mapping[str, float], diversity_penalty: float) -> float:
        score = (
            0.20 * scores["ai_visibility_opportunity_score"]
            + 0.16 * scores["purchase_intent_score"]
            + 0.14 * scores["citation_actionability_score"]
            + 0.11 * scores["human_realism_score"]
            + 0.10 * scores["specificity_score"]
            + 0.10 * scores["objective_alignment_score"]
            + 0.08 * scores["buyer_context_score"]
            + 0.05 * scores["commercial_proxy_score"]
            + 0.03 * scores["evidence_confidence_score"]
            + 0.03 * scores["local_relevance_score"]
            - diversity_penalty
        )
        return round(score, 4)

    def _human_realism_score(self, candidate: QuestionCandidate) -> float:
        q = candidate.question
        lowered = q.casefold()
        score = 7.2
        if candidate.metadata.get("query_mode") == "keyword":
            score += 0.5
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
        if meta.get("intent_subtype") in HIGH_VALUE_INTENTS:
            score += 0.9
        if meta.get("competitor"):
            score += 1.0
        if meta.get("offering"):
            score += 0.65
        if meta.get("concern") or meta.get("goal"):
            score += 0.55
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
        if candidate.metadata.get("intent_subtype") in {"concern", "method_comparison", "adjacency", "aftercare", "safety"}:
            score += 1.4
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
            ("concern", 1.0),
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
        if candidate.metadata.get("geography_weight"):
            return _clamp(float(candidate.metadata["geography_weight"]))
        usage = candidate.metadata.get("location_usage")
        if usage == "local_proxy":
            return 10.0
        if usage == "growth_market":
            return 9.2
        if usage == "physical":
            return 9.0
        if usage == "service_area":
            return 8.0
        if usage == "visibility_market":
            return 5.8 if candidate.group in {"G1", "G3", "G5"} else 3.0
        return 5.0

    def _objective_alignment_score(self, candidate: QuestionCandidate) -> float:
        objective = str(candidate.metadata.get("scan_objective") or "high_intent_visibility")
        subtype = str(candidate.metadata.get("intent_subtype") or "")
        usage = str(candidate.metadata.get("location_usage") or "")
        score = 5.5
        if objective == "find_competitor_gaps":
            if candidate.metadata.get("competitor") or subtype in {"competitor_swap", "head_to_head", "branded_trust"}:
                score += 3.2
            if candidate.group in {"G3", "G7"}:
                score += 1.0
        elif objective == "local_discovery_visibility":
            if subtype in {"near_me", "local_discovery"} or usage in {"local_proxy", "growth_market", "service_area", "physical"}:
                score += 3.0
        elif objective == "trust_citation_proof":
            if subtype in {"branded_trust", "safety", "aftercare"} or candidate.group == "G5":
                score += 3.0
        elif objective == "new_market_service_audience":
            if usage == "growth_market" or candidate.metadata.get("buyer_context") or subtype in {"persona", "outcome", "concern"}:
                score += 2.8
        else:
            if subtype in {"price", "transactional", "concern", "outcome", "near_me"}:
                score += 2.6
        return _clamp(score)

    def _buyer_context_score(self, candidate: QuestionCandidate) -> float:
        meta = candidate.metadata
        score = 4.8
        if meta.get("buyer_context"):
            score += 2.4
        if meta.get("problem") or meta.get("concern"):
            score += 1.3
        if meta.get("goal"):
            score += 1.0
        if meta.get("constraint") or meta.get("decision_criteria") or meta.get("persona"):
            score += 1.0
        if meta.get("intent_subtype") in {"concern", "outcome", "persona", "first_time", "aftercare"}:
            score += 0.8
        return _clamp(score)

    def _diversity_penalty(self, candidate: QuestionCandidate, selected: list[RankedQuestion]) -> float:
        penalty = 0.0
        for key, weight in (
            ("offering", 0.35),
            ("competitor", 0.25),
            ("pattern", 0.22),
            ("location", 0.15),
            ("buyer_context", 0.22),
            ("intent_subtype", 0.28),
            ("query_mode", 0.18),
        ):
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
        if meta.get("intent_subtype"):
            reasons.append(f"{str(meta['intent_subtype']).replace('_', ' ')} coverage")
        if meta.get("offering"):
            reasons.append(f"confirmed offering: {meta['offering']}")
        if meta.get("competitor"):
            reasons.append(f"competitor context: {meta['competitor']}")
        if meta.get("buyer_context"):
            reasons.append(f"buyer context: {meta['buyer_context']}")
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
            "objective_alignment_score": scores["objective_alignment_score"],
            "buyer_context_score": scores["buyer_context_score"],
            "evidence_confidence_score": scores["evidence_confidence_score"],
            "local_relevance_score": scores["local_relevance_score"],
            "diversity_penalty": ranked.diversity_penalty,
            "priority": ranked.candidate.metadata.get("priority", "medium"),
            "intent_subtype": ranked.candidate.metadata.get("intent_subtype", ""),
            "query_mode": ranked.candidate.metadata.get("query_mode", ""),
            "market_rationale": self._market_rationale(ranked),
            "rank_reason": ranked.rank_reason,
        }

    def _market_rationale(self, ranked: RankedQuestion) -> str:
        meta = ranked.candidate.metadata
        pieces: list[str] = []
        if meta.get("intent_subtype"):
            pieces.append(str(meta["intent_subtype"]).replace("_", " "))
        if meta.get("query_mode"):
            pieces.append(f"{meta['query_mode']} query")
        if meta.get("location_usage") == "local_proxy":
            pieces.append(f"near-me proxy: {meta.get('location')}")
        elif meta.get("location_usage") == "growth_market":
            pieces.append(f"growth market: {meta.get('location')}")
        elif meta.get("location"):
            pieces.append(f"local market: {meta.get('location')}")
        if meta.get("competitor_tier"):
            pieces.append(f"{meta['competitor_tier']} competitor")
        if meta.get("buyer_context"):
            pieces.append(f"buyer context: {meta['buyer_context']}")
        if meta.get("branded_offering") and meta.get("offering") != meta.get("branded_offering"):
            pieces.append(f"generic term for {meta['branded_offering']}")
        return "; ".join(pieces) or "balanced audit coverage"

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
    target_env_name: str = "AISO_QUESTION_GROUP_TARGETS",
    total_env_name: str = "AISO_QUESTION_FINAL_TOTAL",
    default_group_targets: Mapping[str, int] | None = None,
) -> list[dict[str, Any]]:
    groups = [group for group in (selected_groups or GROUP_LABELS.keys()) if group in GROUP_LABELS]
    if limit_per_group is not None:
        group_targets = {group: limit_per_group for group in groups}
    else:
        group_targets = _parse_group_targets(
            groups,
            env_name=target_env_name,
            total_env_name=total_env_name,
            default_targets=default_group_targets,
        )
    candidate_limit = candidate_limit_per_group or _env_positive_int(
        "AISO_QUESTION_CANDIDATE_LIMIT_PER_GROUP",
        DEFAULT_CANDIDATE_LIMIT_PER_GROUP,
    )
    candidates = _generate_candidates(profile, groups)
    ranker = QuestionValueRanker(candidate_limit_per_group=candidate_limit)
    rows, report = ranker.rank_and_select(candidates, group_targets=group_targets)
    quality_control = audit_question_bank_rows(rows)
    report["quality_control"] = quality_control
    if report_path:
        Path(report_path).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    if not quality_control["passed"]:
        messages = "; ".join(issue["message"] for issue in quality_control["issues"][:5])
        raise ValueError(f"Question bank QC failed: {messages}")
    return rows
