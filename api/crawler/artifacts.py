"""Structured crawl artifact builder for Phase 12 onboarding."""

from __future__ import annotations

from typing import Any

from api.crawler.policy import classify_page_type

SCHEMA_TYPES = (
    "LocalBusiness",
    "Product",
    "Service",
    "Organization",
    "Offer",
    "FAQPage",
)


def build_crawl_artifacts(
    *,
    evidence: dict[str, Any],
    profile: dict[str, Any],
    warnings: list[str],
) -> dict[str, Any]:
    """Build the JSONB payload stored on ``business_profile.crawl_artifacts``."""
    pages = evidence.get("pages") if isinstance(evidence, dict) else []
    pages = pages if isinstance(pages, list) else []
    structured_data = extract_schema_entities(evidence)

    return {
        "schema_version": "crawl_artifacts.v1",
        "start_url": evidence.get("start_url"),
        "page_count": evidence.get("page_count", len(pages)),
        "rendered_dom": bool(evidence.get("rendered_dom")),
        "playwright_invocations": int(evidence.get("playwright_invocations") or 0),
        "partial": bool(evidence.get("partial")),
        "truncation_reason": evidence.get("truncation_reason"),
        "tier1": {
            "attempted_urls": _clean_list(evidence.get("tier1_attempted")),
            "fetched_urls": _clean_list(evidence.get("tier1_fetched")),
        },
        "pages": [_page_summary(page) for page in pages if isinstance(page, dict)],
        "structured_data": structured_data,
        "auto_extracted": _auto_extracted(profile, structured_data, pages),
        "warnings": _dedupe([str(item) for item in warnings if str(item).strip()]),
    }


def extract_schema_entities(evidence: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    pages = evidence.get("pages") if isinstance(evidence, dict) else []
    entities: dict[str, list[dict[str, Any]]] = {schema_type: [] for schema_type in SCHEMA_TYPES}

    for page in pages if isinstance(pages, list) else []:
        if not isinstance(page, dict):
            continue
        source_url = str(page.get("url") or "")
        for json_ld in page.get("json_ld", []) if isinstance(page.get("json_ld"), list) else []:
            for obj in _flatten_json_ld(json_ld):
                for schema_type in _matching_schema_types(obj):
                    entities[schema_type].append(_entity_summary(obj, source_url))

    return {key: _dedupe_entities(value) for key, value in entities.items() if value}


def _auto_extracted(
    profile: dict[str, Any],
    structured_data: dict[str, list[dict[str, Any]]],
    pages: list[Any],
) -> dict[str, Any]:
    business = profile.get("business") if isinstance(profile, dict) else {}
    organization = _first_entity(structured_data, "Organization") or _first_entity(structured_data, "LocalBusiness")
    return {
        "brand_name": _clean((business or {}).get("name") if isinstance(business, dict) else None)
        or _clean((organization or {}).get("name") if isinstance(organization, dict) else None),
        "tagline": _first_home_heading(pages),
        "about_copy": _first_page_text(pages, "about"),
        "nap": _nap(structured_data),
        "product_service_taxonomy": _taxonomy(profile, structured_data),
        "pricing_tiers": _pricing(structured_data),
        "customer_logos_or_case_studies": _customer_names(pages),
        "blog_topic_distribution": _blog_topics(pages),
        "schema_entity_types": sorted(structured_data.keys()),
    }


def _page_summary(page: dict[str, Any]) -> dict[str, Any]:
    json_ld_types = sorted(
        {
            schema_type
            for json_ld in page.get("json_ld", []) if isinstance(page.get("json_ld"), list)
            for obj in _flatten_json_ld(json_ld)
            for schema_type in _matching_schema_types(obj)
        }
    )
    text_blocks = page.get("text_blocks") if isinstance(page.get("text_blocks"), list) else []
    page_type = page.get("page_type") or classify_page_type(
        str(page.get("url") or ""),
        str(page.get("title") or ""),
    )
    return {
        "url": page.get("url"),
        "title": page.get("title"),
        "page_type": page_type,
        "status_code": page.get("status_code"),
        "content_type": page.get("content_type"),
        "headings": _clean_list(page.get("headings"))[:8],
        "text_sample": " ".join(str(item) for item in text_blocks[:3])[:600],
        "structured_data_types": json_ld_types,
        "stop_reason": page.get("stop_reason"),
        "rendered_dom": bool(page.get("rendered_dom")),
        "playwright_fallback_reason": page.get("playwright_fallback_reason"),
    }


def _page_type(page: Any) -> str:
    if not isinstance(page, dict):
        return ""
    return str(
        page.get("page_type")
        or classify_page_type(str(page.get("url") or ""), str(page.get("title") or ""))
        or ""
    )


def _nap(structured_data: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    business = _first_entity(structured_data, "LocalBusiness")
    if not isinstance(business, dict):
        return {}
    return {
        key: value
        for key, value in {
            "name": _clean(business.get("name")),
            "telephone": _clean(business.get("telephone")),
            "address": business.get("address") if isinstance(business.get("address"), dict) else {},
            "source_url": business.get("source_url"),
        }.items()
        if value not in ("", {}, [])
    }


def _taxonomy(profile: dict[str, Any], structured_data: dict[str, list[dict[str, Any]]]) -> list[str]:
    names: list[str] = []
    for section in ("offerings", "product_brands", "categories"):
        for item in profile.get(section, []) if isinstance(profile.get(section), list) else []:
            if isinstance(item, dict):
                names.append(_clean(item.get("name")))
    for schema_type in ("Service", "Product", "Offer"):
        for entity in structured_data.get(schema_type, []):
            names.append(_clean(entity.get("name")))
    return _dedupe([name for name in names if name])


def _customer_names(pages: list[Any]) -> list[str]:
    names: list[str] = []
    for page in pages:
        if not isinstance(page, dict) or _page_type(page) not in {"testimonials", "case_study", "other"}:
            continue
        url = str(page.get("url") or "").casefold()
        title = str(page.get("title") or "").casefold()
        if not any(term in f"{url} {title}" for term in ("customer", "case", "client")):
            continue
        headings = page.get("headings") if isinstance(page.get("headings"), list) else []
        for heading in headings:
            clean = _clean(heading)
            if clean and len(clean.split()) <= 7:
                names.append(clean)
    return _dedupe(names)[:30]


def _blog_topics(pages: list[Any]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for page in pages:
        if not isinstance(page, dict) or _page_type(page) != "blog":
            continue
        for heading in page.get("headings", []) if isinstance(page.get("headings"), list) else []:
            topic = _clean(heading)
            if not topic or len(topic.split()) > 10:
                continue
            counts[topic] = counts.get(topic, 0) + 1
    return [
        {"topic": topic, "count": count}
        for topic, count in sorted(counts.items(), key=lambda item: (-item[1], item[0].casefold()))[:30]
    ]


def _pricing(structured_data: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for entity in structured_data.get("Offer", []):
        price = _clean(entity.get("price"))
        name = _clean(entity.get("name"))
        if price or name:
            rows.append(
                {
                    "name": name,
                    "price": price,
                    "price_currency": _clean(entity.get("priceCurrency")),
                    "source_url": entity.get("source_url"),
                }
            )
    return _dedupe_entities(rows)


def _entity_summary(obj: dict[str, Any], source_url: str) -> dict[str, Any]:
    summary = {
        "type": _type_strings(obj),
        "name": _entity_name(obj),
        "description": _clean(obj.get("description")),
        "url": _clean(obj.get("url")),
        "source_url": source_url,
    }
    address = obj.get("address")
    if isinstance(address, dict):
        summary["address"] = {
            "streetAddress": _clean(address.get("streetAddress")),
            "addressLocality": _clean(address.get("addressLocality")),
            "addressRegion": _clean(address.get("addressRegion")),
            "postalCode": _clean(address.get("postalCode")),
        }
    for key in ("price", "priceCurrency", "availability", "telephone"):
        if _clean(obj.get(key)):
            summary[key] = _clean(obj.get(key))
    return {key: value for key, value in summary.items() if value not in ("", [], {})}


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
        for key in ("offers", "makesOffer", "hasOfferCatalog"):
            raw = value.get(key)
            objects.extend(_flatten_json_ld(raw))
        main_entity = value.get("mainEntity")
        objects.extend(_flatten_json_ld(main_entity))
    return objects


def _matching_schema_types(obj: dict[str, Any]) -> list[str]:
    raw_types = {item.casefold() for item in _type_strings(obj)}
    matches: list[str] = []
    for schema_type in SCHEMA_TYPES:
        if schema_type.casefold() in raw_types:
            matches.append(schema_type)
    return matches


def _type_strings(obj: dict[str, Any]) -> list[str]:
    raw = obj.get("@type")
    if isinstance(raw, list):
        return [_clean(item) for item in raw if _clean(item)]
    return [_clean(raw)] if _clean(raw) else []


def _entity_name(obj: dict[str, Any]) -> str:
    raw = obj.get("name") or obj.get("headline") or obj.get("serviceType")
    if isinstance(raw, dict):
        raw = raw.get("name")
    item_offered = obj.get("itemOffered")
    if not raw and isinstance(item_offered, dict):
        raw = item_offered.get("name")
    return _clean(raw)


def _first_entity(structured_data: dict[str, list[dict[str, Any]]], schema_type: str) -> dict[str, Any] | None:
    rows = structured_data.get(schema_type, [])
    return rows[0] if rows else None


def _first_home_heading(pages: list[Any]) -> str:
    for page in pages:
        if not isinstance(page, dict):
            continue
        if page.get("page_type") in {"homepage", None}:
            headings = page.get("headings") if isinstance(page.get("headings"), list) else []
            for heading in headings:
                clean = _clean(heading)
                if clean:
                    return clean
    return ""


def _first_page_text(pages: list[Any], page_type: str) -> str:
    for page in pages:
        if not isinstance(page, dict) or page.get("page_type") != page_type:
            continue
        blocks = page.get("text_blocks") if isinstance(page.get("text_blocks"), list) else []
        return " ".join(str(block) for block in blocks[:4])[:1000]
    return ""


def _clean_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return _dedupe([_clean(item) for item in value if _clean(item)])


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _dedupe_entities(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for value in values:
        key = "|".join(str(value.get(part) or "") for part in ("type", "name", "url", "source_url", "price"))
        if key.casefold() in seen:
            continue
        seen.add(key.casefold())
        result.append(value)
    return result


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())
