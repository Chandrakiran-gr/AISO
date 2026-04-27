"""Local scan workspace preparation for AISO.

The API-created onboarding flow needs the same minimum files that the legacy
CLI collector expects. This module creates those files deterministically without
calling an LLM, so a fresh local user can launch a scan with zero extra infra.
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Iterable

from api.database import Client

REPO_ROOT = Path(__file__).resolve().parent.parent
CLIENTS_ROOT = REPO_ROOT / "clients"

VALUE_BANK_HEADERS = [
    "client",
    "competitor",
    "competitor_a",
    "competitor_b",
    "option_a",
    "option_b",
    "category",
    "service",
    "product",
    "city",
    "neighborhood",
    "landmark",
    "region",
    "state_or_country",
    "zip_or_area",
    "goal",
    "use_case",
    "persona_or_occasion",
    "audience",
    "price_or_budget",
    "timeframe",
    "qualifier",
]

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

GROUP_LABELS = {
    "G1": "Category & local discovery (unbranded)",
    "G2": "Direct brand (client named)",
    "G3": "Competitors & alternatives",
    "G4": "Transactional & bottom-funnel",
    "G5": "Trust, reviews & risk",
    "G6": "Fit: persona, occasion, constraint",
    "G7": "Head-to-head choice",
}


def normalize_slug(raw: str) -> str:
    """Match collect.py slug normalization so API and CLI agree on paths."""
    slug = str(raw or "").lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    return slug.strip("_") or "client"


def _split_competitors(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, list):
        return [str(item).strip() for item in parsed if str(item).strip()]
    return [item.strip() for item in value.split(",") if item.strip()]


def _first_non_empty(values: Iterable[str | None], fallback: str) -> str:
    for value in values:
        clean = str(value or "").strip()
        if clean:
            return clean
    return fallback


def _location_parts(location: str | None) -> tuple[str, str]:
    clean = str(location or "").strip()
    if not clean:
        return ("your area", "your region")
    parts = [part.strip() for part in clean.split(",") if part.strip()]
    if len(parts) >= 2:
        return (parts[0], parts[-1])
    return (clean, clean)


def _question_templates() -> dict[str, list[str]]:
    return {
        "G1": [
            "best {category} in {city}",
            "top rated {service} near {city}",
            "where to find trusted {category} in {region}",
            "{category} near me with good reviews",
            "recommended {service} providers in {city}",
            "affordable {category} options in {region}",
            "high quality {service} in {city}",
            "best local {category} for {goal}",
            "{category} open now near {city}",
            "who offers {service} around {city}",
            "most trusted {category} near {landmark}",
            "local {category} for {use_case}",
        ],
        "G2": [
            "is {client} good for {service}",
            "{client} reviews for {category}",
            "does {client} offer {service}",
            "{client} pricing for {service}",
            "book {client} for {use_case}",
            "{client} near {city} hours and availability",
            "is {client} worth it for {goal}",
            "{client} vs other {category} providers",
            "what services does {client} provide",
            "{client} customer experience",
            "can {client} help with {goal}",
            "{client} appointment availability {timeframe}",
        ],
        "G3": [
            "best alternatives to {competitor}",
            "{competitor} vs other {category} providers",
            "who is better than {competitor} for {service}",
            "companies like {competitor} near {city}",
            "{competitor_a} vs {competitor_b} for {goal}",
            "switching from {competitor} to another {category}",
            "cheaper alternatives to {competitor} in {region}",
            "best {competitor} competitors for {use_case}",
            "{competitor} reviews compared with local options",
            "where else to go instead of {competitor}",
            "top {category} brands competing with {competitor}",
            "is there a better option than {competitor} for {service}",
        ],
        "G4": [
            "book {service} in {city} {timeframe}",
            "{service} cost in {region}",
            "get a quote for {category} near {city}",
            "same day {service} appointment near me",
            "{category} under {price_or_budget}",
            "best place to buy {product} near {city}",
            "schedule {service} for {use_case}",
            "{category} deals near {city}",
            "where can I book {service} now",
            "{service} availability this week",
            "compare prices for {category} in {region}",
            "fastest way to book {service} near {city}",
        ],
        "G5": [
            "is {client} legit",
            "{client} complaints and reviews",
            "is {category} in {city} safe and trustworthy",
            "{competitor} complaints compared with {client}",
            "best reviewed {category} near {city}",
            "red flags when choosing {service}",
            "is {client} worth the price",
            "{category} providers with strong reputation in {region}",
            "most reliable {service} near {city}",
            "customer reviews for {service} providers",
            "trusted {category} for {audience}",
            "what to know before booking {service}",
        ],
        "G6": [
            "best {category} for {persona_or_occasion} in {city}",
            "{service} for {persona_or_occasion} near me",
            "is {client} good for {persona_or_occasion}",
            "best {category} for {audience}",
            "{service} for {use_case}",
            "{category} for {persona_or_occasion} under {price_or_budget}",
            "where should {audience} book {service}",
            "best local {category} for {goal}",
            "{service} for first time {persona_or_occasion}",
            "{category} near {city} for {audience}",
            "which {service} fits {persona_or_occasion}",
            "recommended {category} for {use_case}",
        ],
        "G7": [
            "{option_a} vs {option_b} which is better",
            "should I choose {option_a} or {option_b}",
            "{option_a} compared with {competitor_a}",
            "{option_a} vs {competitor_b} for {goal}",
            "pick one {option_a} or {option_b}",
            "is {option_a} better than {option_b} for {use_case}",
            "{option_a} vs {option_b} price and quality",
            "which should I book {option_a} or {option_b}",
            "{option_a} vs {option_b} near {city}",
            "final choice between {option_a} and {option_b}",
            "best option for {persona_or_occasion}: {option_a} or {option_b}",
            "which has better reviews {option_a} or {option_b}",
        ],
    }


def _profile_values(client: Client) -> dict[str, str]:
    competitors = _split_competitors(client.competitors)
    competitor_a = competitors[0] if competitors else "a leading competitor"
    competitor_b = competitors[1] if len(competitors) > 1 else competitor_a
    city, region = _location_parts(client.location)
    category = _first_non_empty([client.industry], "business")
    service = category

    return {
        "client": client.name,
        "competitor": competitor_a,
        "competitor_a": competitor_a,
        "competitor_b": competitor_b,
        "option_a": client.name,
        "option_b": competitor_a,
        "category": category,
        "service": service,
        "product": f"{category} service",
        "city": city,
        "neighborhood": city,
        "landmark": city,
        "region": region,
        "state_or_country": region,
        "zip_or_area": city,
        "goal": "choose the best provider",
        "use_case": "a near-term purchase decision",
        "persona_or_occasion": "first-time customers",
        "audience": "local customers",
        "price_or_budget": "a fair budget",
        "timeframe": "this week",
        "qualifier": "trusted",
    }


def _render_question(template: str, values: dict[str, str]) -> str:
    result = template
    for key, value in values.items():
        result = result.replace(f"{{{key}}}", value)
    return re.sub(r"\s+", " ", result).strip()


def prepare_scan_workspace(client: Client) -> Path:
    """Create/update the local client folder needed by collect.py."""
    slug = normalize_slug(client.id)
    client_folder = CLIENTS_ROOT / slug
    client_folder.mkdir(parents=True, exist_ok=True)

    competitors = _split_competitors(client.competitors)
    profile = {
        "slug": slug,
        "display_name": client.name,
        "name": client.name,
        "website_url": client.url,
        "industry": client.industry,
        "location": client.location,
        "competitors": competitors,
        "_generated_by": "api.scan_workspace",
    }
    (client_folder / "client_profile.json").write_text(
        json.dumps(profile, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (client_folder / "config.json").write_text(
        json.dumps(
            {
                "slug": slug,
                "display_name": client.name,
                "business_name": client.name,
                "url": client.url,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    values = _profile_values(client)
    with (client_folder / "value_bank.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=VALUE_BANK_HEADERS)
        writer.writeheader()
        writer.writerow({key: values.get(key, "") for key in VALUE_BANK_HEADERS})

    bank_path = client_folder / "query_template_bank.csv"
    templates = _question_templates()
    rows: list[dict[str, str | int | float]] = []
    for group_id, group_templates in templates.items():
        for rank, template in enumerate(group_templates, start=1):
            rows.append(
                {
                    "question": _render_question(template, values),
                    "group": group_id,
                    "group_label": GROUP_LABELS[group_id],
                    "group_rank": rank,
                    "intent_score": 7,
                    "popularity_score": "",
                    "cpc_proxy_score": 5,
                    "rank_reason": "Generated from onboarding profile for local-first scan launch.",
                }
            )

    with bank_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=QUERY_BANK_HEADERS)
        writer.writeheader()
        writer.writerows(rows)

    return client_folder
