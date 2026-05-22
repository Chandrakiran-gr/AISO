"""Structured client context drafting from public website evidence."""

from __future__ import annotations

from typing import Any, Iterable
from urllib.parse import urlparse
import json
import re
import unicodedata

from api.database import Client


PROFILE_VERSION = "client_context.v1"
DEFAULT_SCAN_OBJECTIVE = {
    "objective": "",
    "label": "",
    "optimization_objectives": [],
    "custom_objective": "",
    "custom": "",
    "source_url": "fallback",
    "confidence": 0.45,
}


def _clean(value: Any) -> str:
    text = "".join(
        char
        for char in str(value or "")
        if not (unicodedata.category(char).startswith("C") or unicodedata.category(char) == "So")
    )
    return re.sub(r"\s+", " ", text).strip()


def _looks_like_scraped_copy(text: str) -> bool:
    clean = _clean(text)
    lowered = clean.casefold()
    if not clean:
        return True
    if len(clean) > 90 and re.search(r"[.;!?]", clean):
        return True
    if len(clean.split()) > 12:
        return True
    blocked_fragments = (
        "affected by nature",
        "anyone wanting",
        "book now",
        "choose the best provider",
        "defined, lifted, and polished",
        "everyday pollutants",
        "featuring pain",
        "ideal for",
        "learn more",
        "perfect for refreshing",
        "removes unwanted hair",
        "we use gentle",
    )
    if any(fragment in lowered for fragment in blocked_fragments):
        return True
    if re.search(r"\bADD-?ONS?:?\b", clean, re.I):
        return True
    return False


def _sanitize_profile_name(name: Any, item_type: str) -> str:
    clean = _clean(name)
    if not clean:
        return ""
    if item_type in {"category", "offering", "offering_group", "product_brand"} and "|" in clean:
        clean = _clean(clean.split("|", 1)[0])
    if item_type == "offering":
        clean = re.sub(r"^The\s+", "", clean, flags=re.I)
    strict_types = {
        "category",
        "competitor_business",
        "offering",
        "offering_group",
        "product_brand",
        "service_area",
        "visibility_market",
    }
    if item_type in strict_types and _looks_like_scraped_copy(clean):
        return ""
    if item_type == "product_brand" and _reject_brand_candidate(clean):
        return ""
    if item_type == "persona":
        clean = re.sub(r"^(?:for|ideal for)\s+", "", clean, flags=re.I)
        clean = re.split(
            r"\bto\s+(?:avoid|help|improve|minimi[sz]e|reduce)\b",
            clean,
            maxsplit=1,
            flags=re.I,
        )[0]
        clean = clean.strip(" .,:;-")
        lowered = clean.casefold()
        if lowered == "mature":
            clean = "mature skin"
            lowered = clean.casefold()
        blocked_personas = {
            "anyone",
            "anyone with light",
            "light",
            "overall skin",
            "refreshing and rejuvenating skin",
            "regular skin",
            "regular skin maintenance",
            "regular maintenance with minimal irritation",
            "straight, light",
            "straight",
            "those",
            "your skin",
            "your skin skin",
        }
        if lowered in blocked_personas:
            return ""
        if any(fragment in lowered for fragment in ("maintenance through", "through targeted", "skin skin")):
            return ""
        if _looks_like_scraped_copy(clean) or len(clean) > 80:
            return ""
        if len(clean) < 4:
            return ""
    return clean


def _strip_inline_cta(value: str) -> str:
    clean = _clean(value)
    clean = re.sub(r"\s*>?\s*(?:Book Now|Learn More|Get Directions)\s*$", "", clean, flags=re.I)
    return _clean(clean)


def _dedupe_key(name: str, item_type: str | None) -> str:
    clean = _clean(name).casefold()
    if item_type == "physical_location":
        address = re.sub(r"\b(?:suite|ste)\s*#?\s*(\d+)\b", r"suite \1", clean)
        street = re.search(
            r"\b(\d{2,5}\s+[^,]+?\b(?:avenue|ave|street|st|road|rd|drive|dr|boulevard|blvd|lane|ln|way))\b",
            address,
        )
        suite = re.search(r"\bsuite\s*\d+\b", address)
        zip_code = re.search(r"\b\d{5}(?:-\d{4})?\b", address)
        if street and zip_code:
            suite_key = f" {suite.group(0)}" if suite else ""
            return f"address:{street.group(1)}{suite_key} {zip_code.group(0)}"
    return re.sub(r"[^a-z0-9]+", " ", clean).strip()


def _dedupe_items(items: Iterable[dict[str, Any]], *, key: str = "name", limit: int = 30) -> list[dict[str, Any]]:
    seen: dict[str, int] = {}
    result: list[dict[str, Any]] = []
    for item in items:
        item_type = _clean(item.get("type")) or ""
        name = _sanitize_profile_name(item.get(key), item_type)
        if not name:
            continue
        normalized = _dedupe_key(name, item_type or None)
        next_item = dict(item)
        next_item[key] = name
        if normalized in seen:
            existing_index = seen[normalized]
            existing_name = _clean(result[existing_index].get(key))
            if len(name) < len(existing_name):
                result[existing_index] = next_item
            continue
        seen[normalized] = len(result)
        result.append(next_item)
        if len(result) >= limit:
            break
    return result


def _item(name: str, item_type: str, confidence: float, source_url: str, **extra: Any) -> dict[str, Any]:
    clean_name = _sanitize_profile_name(name, item_type)
    payload = {
        "name": clean_name,
        "type": item_type,
        "confidence": round(float(confidence), 2),
        "source_url": source_url,
    }
    payload.update({key: value for key, value in extra.items() if value not in (None, "", [])})
    return payload


def _client_competitors(client: Client) -> list[str]:
    if not client.competitors:
        return []
    try:
        parsed = json.loads(client.competitors)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [_clean(item) for item in parsed if _clean(item)]


def _flatten_json_ld(value: Any) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    if isinstance(value, list):
        for item in value:
            objects.extend(_flatten_json_ld(item))
    elif isinstance(value, dict):
        objects.append(value)
        graph = value.get("@graph")
        if isinstance(graph, list):
            objects.extend(_flatten_json_ld(graph))
    return objects


def _jsonld_type(value: Any) -> str:
    raw = value.get("@type") if isinstance(value, dict) else ""
    if isinstance(raw, list):
        return " ".join(str(item) for item in raw)
    return str(raw or "")


def _name_from_jsonld(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    raw = value.get("name") or value.get("headline") or value.get("serviceType")
    if isinstance(raw, dict):
        raw = raw.get("name")
    return _clean(raw)


def _iter_jsonld_offers(value: dict[str, Any]) -> Iterable[dict[str, Any]]:
    for key in ("offers", "makesOffer", "hasOfferCatalog"):
        raw = value.get(key)
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict):
                    yield item
        elif isinstance(raw, dict):
            yield raw


def _price_from_text(text: str) -> str | None:
    match = re.search(r"(\$\s?\d+(?:[,.]\d{2})?|\d+\s?(?:minutes|mins|min|hours|hrs))", text, re.I)
    return _clean(match.group(1)) if match else None


def _duration_from_text(text: str) -> str | None:
    match = re.search(r"(\d+\s?(?:minutes|mins|min|hours|hrs))", text, re.I)
    return _clean(match.group(1)) if match else None


def _looks_like_group(text: str) -> bool:
    lowered = text.casefold()
    if _skip_context_text(text):
        return False
    if any(term in lowered for term in ("prices subject to change", "results-driven")):
        return False
    plural_group_terms = (
        "treatments",
        "services",
        "packages",
        "memberships",
        "menu",
        "programs",
        "classes",
        "solutions",
    )
    return any(term in lowered for term in plural_group_terms) and not _price_from_text(text)


def _looks_like_offering(text: str) -> bool:
    lowered = text.casefold()
    if _skip_context_text(text):
        return False
    if len(text) < 3:
        return False
    # Reject negation and declarative sentences — these are marketing copy, not service names
    # e.g. "Private sessions do not scale." or "Not a chat bot. Not a private session."
    if re.match(r"not\s+an?\s", lowered):
        return False
    if re.search(r"\b(?:do not|does not|don't|doesn't|is not|are not|isn't|aren't|cannot|can't|won't|will not)\b", lowered):
        return False
    if re.search(r"\b(?:provide|provides|include|includes|targeting|designed to|serving|specializing)\b", lowered):
        return False
    if _price_from_text(text):
        return True
    return any(
        term in lowered
        for term in (
            "consultation",
            "appointment",
            "session",
            "service",
            "repair",
            "installation",
            "audit",
            "assessment",
        )
    )


def _offering_confidence(text: str, *, is_heading: bool) -> float:
    if _price_from_text(text):
        return 0.76
    if is_heading:
        return 0.72
    return 0.56


def _extract_offering_name(text: str) -> str:
    cleaned = re.sub(r"\s+\$\s?\d+(?:[,.]\d{2})?.*$", "", text).strip()
    cleaned = re.sub(r"\s+\d+\s?(?:minutes|mins|min|hours|hrs).*$", "", cleaned, flags=re.I).strip()
    cleaned = re.split(r"\s[-–—]\s", cleaned, maxsplit=1)[0].strip()
    return cleaned or text


def _skip_context_text(text: str) -> bool:
    lowered = text.casefold()
    noisy_terms = (
        "account",
        "available only",
        "book an appointment",
        "gift card",
        "group appointment",
        "home service menu",
        "ideal for",
        "join and save",
        "looking for",
        "most popular",
        "one session",
        "subscribe",
        "cookie",
        "copyright",
        "powered by",
        "purchase",
        "questions?",
        "results-driven",
        "sign in",
        "signed in",
        "sign out",
        "create account",
        "my account",
        "email:",
        "phone:",
        "book now",
        "learn more",
        "get directions",
    )
    return any(term in lowered for term in noisy_terms)


def _extract_brand_names(text: str) -> list[str]:
    brands: list[str] = []
    patterns = [
        r"(?:use|uses|carry|carries|sells|sold|partnered with)\s+([A-Z][A-Za-z0-9&' ]+)",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            candidate = _clean(match.group(1))
            candidate = re.sub(r"\s+(?:products|skincare|line|brand).*$", "", candidate, flags=re.I)
            if candidate and len(candidate.split()) <= 5 and not _reject_brand_candidate(candidate):
                brands.append(candidate)
    return brands


def _reject_brand_candidate(candidate: str) -> bool:
    clean = _clean(candidate)
    lowered = clean.casefold()
    blocked = {
        "pain",
        "pain free",
        "online bookings",
        "all rights reserved",
    }
    if lowered in blocked:
        return True
    if re.fullmatch(r"[A-Z0-9&' -]+", clean):
        return True
    return any(token in lowered.split() for token in {"pain", "free", "booking", "bookings", "copyright"})


def _extract_personas(text: str, source_url: str) -> list[dict[str, Any]]:
    personas: list[dict[str, Any]] = []
    patterns = (
        r"\bfor\s+([a-z][a-z -]{2,50}\s(?:clients?|customers?|homeowners|founders|teams|users?))\b",
        r"\b(first-time\s+[a-z -]{2,45}\sclients?)\b",
        r"\b(?:ideal for|suitable for|good for)\s+([^.;]{2,70})",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.I):
            candidate = _clean(match.group(1))
            candidate = re.split(
                r"\b(?:or|and anyone|without|with harsh|who|through|for a|to help|while)\b|[,.;]",
                candidate,
                maxsplit=1,
                flags=re.I,
            )[0]
            candidate = _sanitize_profile_name(candidate, "persona")
            if candidate:
                personas.append(_item(candidate, "persona", 0.58, source_url))
    return personas


def _buyer_contexts_from_profile_items(
    personas: list[dict[str, Any]],
    goals: list[dict[str, Any]],
    categories: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    contexts: list[dict[str, Any]] = []
    category_name = _clean(categories[0].get("name")) if categories else "this category"
    clean_goals = [_clean(item.get("name")) for item in goals if _clean(item.get("name"))]
    default_goal = clean_goals[0] if clean_goals else f"choose the right {category_name}"

    for persona in personas[:6]:
        label = _sanitize_profile_name(persona.get("name"), "persona")
        if not label:
            continue
        contexts.append(
            {
                "label": label,
                "audience_type": label,
                "problem": default_goal,
                "desired_outcome": f"confidently choose {category_name}",
                "trigger_event": "",
                "constraints": "",
                "decision_criteria": "trust, relevance, proof, and fit",
                "priority": "medium",
                "source_url": persona.get("source_url") or "derived_context",
                "confidence": min(float(persona.get("confidence") or 0.52), 0.72),
            }
        )

    if not contexts and categories:
        contexts.append(
            {
                "label": "Primary buyer",
                "audience_type": "local or target customer",
                "problem": f"find a trusted {category_name}",
                "desired_outcome": f"choose the right {category_name}",
                "trigger_event": "",
                "constraints": "",
                "decision_criteria": "trust, relevance, proof, and availability",
                "priority": "medium",
                "source_url": "fallback",
                "confidence": 0.45,
            }
        )

    return contexts


def _clean_physical_address(address: str) -> str:
    clean = _clean(address)
    clean = re.sub(r"\b(?:suite|ste)\s*#?\s*(\d+)\b", r"Suite \1", clean, flags=re.I)
    clean = re.sub(r"\bMassachusetts\b", "MA", clean, flags=re.I)
    parts: list[str] = []
    seen: set[str] = set()
    for part in (piece.strip(" ,") for piece in clean.split(",")):
        if not part:
            continue
        key = part.casefold()
        if key in seen:
            continue
        seen.add(key)
        parts.append(part)
    return ", ".join(parts)


def _extract_location_items(text: str, source_url: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    physical: list[dict[str, Any]] = []
    service_areas: list[dict[str, Any]] = []
    visibility: list[dict[str, Any]] = []
    city_state = re.findall(r"\b([A-Z][A-Za-z .'-]+,\s?[A-Z]{2})\b", text)
    for location in city_state:
        physical.append(_item(location, "physical_location", 0.72, source_url))
    for match in re.finditer(
        r"\b(\d{2,5}\s+[^.;\n,]+\b(?:Avenue|Ave|Street|St|Road|Rd|Drive|Dr|Boulevard|Blvd|Lane|Ln|Way)\b[^.;\n,]*,\s*(?:Suite\s*\d+,\s*)?[A-Z][A-Za-z .'-]+,\s*[A-Z]{2}\s*\d{5})\b",
        text,
        re.I,
    ):
        address = _clean_physical_address(match.group(1))
        if re.match(r"\d+\s+(?:daily|monthly|weekly|yearly)\b", address, re.I):
            continue
        physical.append(_item(address, "physical_location", 0.82, source_url))
    for match in re.finditer(r"(?:serving|serves|service areas include|available in)\s+([^.;\n]+)", text, re.I):
        area_text = re.split(r"\b(?:since| is | with treatments| tailored)\b", match.group(1), maxsplit=1, flags=re.I)[0]
        for area in re.split(r",| and ", area_text):
            clean = _clean(re.sub(r"^(?:nearby|surrounding|including)\s+", "", area, flags=re.I))
            if 2 < len(clean) < 60:
                service_areas.append(_item(clean, "service_area", 0.66, source_url))
    for match in re.finditer(r"(?:near|around|throughout)\s+([A-Z][A-Za-z .'-]+)", text):
        visibility.append(_item(match.group(1), "visibility_market", 0.48, source_url, usage="visibility_only"))
    return physical, service_areas, visibility


def _infer_category(text: str, source_url: str, client: Client) -> list[dict[str, Any]]:
    categories: list[dict[str, Any]] = []
    if client.industry:
        categories.append(_item(client.industry, "category", 0.86, source_url or client.url))
    category_patterns = [
        r"\b([A-Z][A-Za-z ]+)\s+(?:services|studio|clinic|spa|salon|agency|company|platform|consultancy)\b",
    ]
    for pattern in category_patterns:
        for match in re.finditer(pattern, text, re.I):
            candidate = _clean(match.group(1)).lower()
            if len(candidate.split()) > 5:
                continue
            if " is " in candidate:
                continue
            if any(
                noisy in candidate
                for noisy in (
                    "alone",
                    "book book",
                    "home service",
                    "may not",
                    "more radiant",
                    "service menu",
                    "stand alone",
                )
            ):
                continue
            if candidate in {"home service", "home services"} and not re.search(
                r"\b(repair|installation|plumbing|roofing|hvac|cleaning|contractor|electrician)\b",
                text,
                re.I,
            ):
                continue
            if candidate and not candidate.startswith(("our ", "the ")):
                categories.append(_item(candidate, "category", 0.58, source_url))
    return categories


def build_context_profile(client: Client, evidence: dict[str, Any]) -> tuple[dict[str, Any], list[str], str]:
    pages = evidence.get("pages") if isinstance(evidence, dict) else []
    pages = pages if isinstance(pages, list) else []
    warnings: list[str] = [str(item) for item in evidence.get("warnings", [])] if isinstance(evidence, dict) else []

    categories: list[dict[str, Any]] = []
    offering_groups: list[dict[str, Any]] = []
    offerings: list[dict[str, Any]] = []
    product_brands: list[dict[str, Any]] = []
    physical_locations: list[dict[str, Any]] = []
    service_areas: list[dict[str, Any]] = []
    visibility_markets: list[dict[str, Any]] = []
    differentiators: list[dict[str, Any]] = []
    goals: list[dict[str, Any]] = []
    personas: list[dict[str, Any]] = []
    guardrails: list[str] = []
    business_name = client.name
    business_type = "business"
    primary_source = client.url

    for page in pages:
        if not isinstance(page, dict):
            continue
        source_url = str(page.get("url") or primary_source)
        page_text_items = [
            str(page.get("title") or ""),
            *[str(item) for item in page.get("headings", []) if item],
            *[str(item) for item in page.get("text_blocks", []) if item],
        ]
        heading_names = {_clean(item) for item in page.get("headings", []) if item}
        page_text = " ".join(page_text_items)
        categories.extend(_infer_category(page_text, source_url, client))

        for json_ld in page.get("json_ld", []) if isinstance(page.get("json_ld"), list) else []:
            for obj in _flatten_json_ld(json_ld):
                obj_type = _jsonld_type(obj).casefold()
                obj_name = _name_from_jsonld(obj)
                if obj_name and any(term in obj_type for term in ("localbusiness", "organization", "store", "restaurant", "beautysalon")):
                    business_name = obj_name
                    business_type = obj_type or "business"
                    primary_source = source_url
                if obj_name and any(term in obj_type for term in ("service", "product")):
                    item_type = "product_brand" if "brand" in obj_type else "offering"
                    target = product_brands if item_type == "product_brand" else offerings
                    target.append(_item(obj_name, item_type, 0.82, source_url, bookable=item_type == "offering"))
                for offer in _iter_jsonld_offers(obj):
                    offered = offer.get("itemOffered") if isinstance(offer, dict) else None
                    raw_name = _name_from_jsonld(offered) or _name_from_jsonld(offer)
                    if raw_name:
                        offerings.append(_item(raw_name, "offering", 0.82, source_url, bookable=True))
                address = obj.get("address") if isinstance(obj, dict) else None
                if isinstance(address, dict):
                    locality = _clean(address.get("addressLocality"))
                    region = _clean(address.get("addressRegion"))
                    location = ", ".join(part for part in (locality, region) if part)
                    if location:
                        physical_locations.append(_item(location, "physical_location", 0.88, source_url))

        for text in page_text_items:
            clean = _clean(text)
            if not clean:
                continue
            if _looks_like_group(clean):
                offering_groups.append(_item(clean, "offering_group", 0.72, source_url, bookable=False))
            elif _looks_like_offering(clean):
                offerings.append(
                    _item(
                        _extract_offering_name(clean),
                        "offering",
                        _offering_confidence(clean, is_heading=clean in heading_names),
                        source_url,
                        price=_price_from_text(clean) if "$" in clean else None,
                        duration=_duration_from_text(clean),
                        bookable=True,
                    )
                )
            for brand in _extract_brand_names(clean):
                product_brands.append(_item(brand, "product_brand", 0.74, source_url))
            if any(term in clean.casefold() for term in ("award", "certified", "customized", "personalized", "specializing", "family-owned")):
                differentiators.append(_item(_strip_inline_cta(clean), "differentiator", 0.55, source_url))
            personas.extend(_extract_personas(_strip_inline_cta(clean), source_url))

        page_physical, page_service, page_visibility = _extract_location_items(page_text, source_url)
        physical_locations.extend(page_physical)
        service_areas.extend(page_service)
        visibility_markets.extend(page_visibility)
        if page.get("stop_reason"):
            warnings.append(f"Booking CTA required login, payment, CAPTCHA, or sensitive form fields near {source_url}.")

    competitors = [
        _item(name, "competitor_business", 0.95, "manual_onboarding")
        for name in _client_competitors(client)
    ]
    if not offerings:
        warnings.append("No services found.")
    if offering_groups and not offerings:
        warnings.append("Term may be a category/group instead of a bookable offering.")
    if pages and not any(item.get("confidence", 0) >= 0.7 for item in offerings):
        warnings.append("Classification confidence is low.")
    if not physical_locations and not service_areas and client.location:
        visibility_markets.append(_item(client.location, "visibility_market", 0.5, "manual_onboarding", usage="visibility_only"))
        warnings.append("Location may be visibility-only.")
    if not pages:
        warnings.append("Website content appears contradictory or incomplete.")

    host = urlparse(client.url).hostname or client.url
    if not categories:
        categories.append(_item(client.industry or host, "category", 0.42, "fallback"))

    if not goals:
        fallback_category = client.industry or host or "business category"
        goals.append(_item(f"Choose the right {fallback_category}", "goal", 0.45, "fallback"))
    if not personas:
        personas.append(_item("Local customers", "persona", 0.45, "fallback"))
    clean_categories = _dedupe_items(categories, limit=12)
    clean_personas = _dedupe_items(personas, limit=12)
    clean_goals = _dedupe_items(goals, limit=12)
    buyer_contexts = _buyer_contexts_from_profile_items(clean_personas, clean_goals, clean_categories)
    guardrails.extend(
        [
            "Do not compare product brands as competitors.",
            "Do not treat offering groups as bookable services unless explicitly marked bookable.",
            "Do not use visibility-only markets for urgent booking prompts.",
        ]
    )

    profile = {
        "version": PROFILE_VERSION,
        "business": {
            "name": business_name,
            "type": business_type or "business",
            "confidence": 0.88 if business_name != client.name else 0.72,
            "source_url": primary_source,
            "website_url": client.url,
        },
        "categories": clean_categories,
        "offering_groups": _dedupe_items(offering_groups, limit=12),
        "offerings": _dedupe_items(offerings, limit=30),
        "product_brands": _dedupe_items(product_brands, limit=20),
        "competitors": _dedupe_items(competitors, limit=12),
        "locations": {
            "physical_locations": _dedupe_items(physical_locations, limit=12),
            "service_areas": _dedupe_items(service_areas, limit=20),
            "visibility_markets": _dedupe_items(visibility_markets, limit=20),
            "excluded_locations": [],
        },
        "goals": clean_goals,
        "personas": clean_personas,
        "differentiators": _dedupe_items(differentiators, limit=12),
        "scan_objective": dict(DEFAULT_SCAN_OBJECTIVE),
        "buyer_contexts": buyer_contexts[:8],
        "guardrails": guardrails,
    }

    status = "draft"
    if not profile["offerings"] or any("confidence is low" in warning for warning in warnings):
        status = "needs_review"
    return profile, _dedupe_warning_list(warnings), status


def _dedupe_warning_list(warnings: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for warning in warnings:
        clean = _clean(warning)
        if not clean or clean in seen:
            continue
        seen.add(clean)
        result.append(clean)
    return result[:20]
