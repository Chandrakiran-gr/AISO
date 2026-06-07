"""Local scan workspace preparation for AISO.

The API-created onboarding flow needs the same minimum files that the legacy
CLI collector expects. This module creates those files deterministically without
calling an LLM, so a fresh local user can launch a scan with zero extra infra.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Iterable

from api.database import Client
from api.question_generation import DEFAULT_EXTENDED_GROUP_TARGETS, QUERY_BANK_HEADERS, profile_to_question_rows
from api.scan_capabilities import competitor_names_for_scan

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

GROUP_LABELS = {
    "G1": "Category & local discovery (unbranded)",
    "G2": "Direct brand (client named)",
    "G3": "Competitors & alternatives",
    "G4": "Transactional & bottom-funnel",
    "G5": "Trust, reviews & risk",
    "G6": "Fit: persona, occasion, constraint",
    "G7": "Head-to-head choice",
}

MANUAL_GROUP = "MANUAL"
MANUAL_GROUP_LABEL = "Custom Questions"


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().casefold() in {"1", "true", "yes", "on"}


def normalize_slug(raw: str) -> str:
    """Match collect.py slug normalization so API and CLI agree on paths."""
    slug = str(raw or "").lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    return slug.strip("_") or "client"


def scan_workspace_slugs(client: Client) -> tuple[str, str]:
    """Return (workspace folder slug, public file slug) for a client scan.

    The public file slug follows the current business name so generated files
    do not keep stale onboarding ids after the single-client profile is edited.
    The workspace folder adds a short opaque hash for concurrent-scan safety.
    """
    public_slug = normalize_slug(client.name or client.id)
    suffix = hashlib.sha256(str(client.id or public_slug).encode("utf-8")).hexdigest()[:8]
    return f"{public_slug}__{suffix}", public_slug


def _split_competitors(value) -> list[str]:
    """Accept a JSON list (the competitor_names column) or a legacy comma string."""
    if not value:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value).split(",") if item.strip()]


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
            "{category} near {city} with good reviews",
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
            "same day {service} appointment near {city}",
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
            "{service} for {persona_or_occasion} near {city}",
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
    competitors = _split_competitors(client.competitor_names)
    competitor_a = competitors[0] if competitors else ""
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
        "goal": f"choose the right {category}",
        "use_case": "a near-term purchase decision",
        "persona_or_occasion": "first-time customers",
        "audience": "local customers",
        "price_or_budget": "a fair budget",
        "timeframe": "this week",
        "qualifier": "trusted",
    }


def _first_context_name(profile: dict, key: str, fallback: str, *, bookable_only: bool = False) -> str:
    values = profile.get(key, [])
    if not isinstance(values, list):
        return fallback
    for item in values:
        if not isinstance(item, dict):
            continue
        if bookable_only and item.get("bookable") is False:
            continue
        name = str(item.get("name") or "").strip()
        if name:
            return name
    return fallback


def _context_locations(profile: dict) -> tuple[str, str]:
    locations = profile.get("locations") if isinstance(profile.get("locations"), dict) else {}
    for key in ("physical_locations", "service_areas", "visibility_markets"):
        values = locations.get(key, [])
        if not isinstance(values, list):
            continue
        for item in values:
            if isinstance(item, dict) and str(item.get("name") or "").strip():
                name = str(item["name"]).strip()
                parts = [part.strip() for part in name.split(",") if part.strip()]
                return (parts[0], parts[-1] if len(parts) > 1 else name)
    return ("your area", "your region")


def _context_profile_values(client: Client, profile: dict) -> dict[str, str]:
    fallback = _profile_values(client)
    business = profile.get("business") if isinstance(profile.get("business"), dict) else {}
    client_name = str(business.get("name") or client.name).strip()
    category = _first_context_name(profile, "categories", fallback["category"])
    service = _first_context_name(profile, "offerings", category, bookable_only=True)
    group = _first_context_name(profile, "offering_groups", category)
    product = _first_context_name(profile, "product_brands", service)
    competitor = _first_context_name(profile, "competitors", fallback["competitor"])
    city, region = _context_locations(profile)
    goal = _first_context_name(profile, "goals", fallback["goal"])
    persona = _first_context_name(profile, "personas", fallback["persona_or_occasion"])
    return {
        **fallback,
        "client": client_name,
        "competitor": competitor,
        "competitor_a": competitor,
        "competitor_b": _first_context_name(profile, "competitors", competitor),
        "option_a": client_name,
        "option_b": competitor,
        "category": category,
        "service": service,
        "product": product,
        "city": city,
        "neighborhood": city,
        "landmark": city,
        "region": region,
        "state_or_country": region,
        "zip_or_area": city,
        "goal": goal,
        "use_case": goal,
        "persona_or_occasion": persona,
        "audience": persona,
    }


def _fallback_context_profile(client: Client, competitors: list[str]) -> dict:
    """Build a minimal context profile when onboarding context is absent."""
    values = _profile_values(client)
    category = values["category"]
    service = values["service"]
    city = values["city"]
    region = values["region"]
    locations = {
        "physical_locations": [],
        "service_areas": [],
        "visibility_markets": [],
        "excluded_locations": [],
    }
    if city and city != "your area":
        locations["service_areas"].append(
            {"name": city, "type": "service_area", "confidence": 0.55, "source_url": client.url or ""}
        )
    if region and region not in {city, "your region"}:
        locations["visibility_markets"].append(
            {"name": region, "type": "visibility_market", "confidence": 0.5, "source_url": client.url or ""}
        )

    return {
        "business": {"name": client.name, "website_url": client.url},
        "categories": [{"name": category, "type": "category", "confidence": 0.5, "source_url": client.url or ""}],
        "offering_groups": [],
        "offerings": [{"name": service, "type": "offering", "bookable": True, "confidence": 0.45}],
        "product_brands": [],
        "competitors": [
            {"name": competitor, "type": "competitor_business", "confidence": 0.75, "source_url": "manual"}
            for competitor in competitors
        ],
        "locations": locations,
        "goals": [
            {
                "name": f"choose the right {category}",
                "type": "goal",
                "confidence": 0.5,
                "source_url": "manual",
            }
        ],
        "personas": [{"name": "first-time buyers", "type": "persona", "confidence": 0.45, "source_url": "manual"}],
        "buyer_contexts": [
            {
                "label": "Primary buyers",
                "audience_type": "primary",
                "problem": f"Need help choosing a trusted {category}",
                "desired_outcome": "Find a provider they can confidently contact or book",
                "trigger_event": "Near-term purchase research",
                "constraints": "Trust, availability, proof, and fit",
                "decision_criteria": "Reputation, relevant proof, pricing clarity, and local availability",
                "priority": "high",
                "source": "manual",
                "confidence": 0.5,
            }
        ],
        "scan_objective": {
            "objective": "",
            "label": "",
            "optimization_objectives": [],
            "custom_objective": "",
            "custom": "",
        },
        "differentiators": [],
        "guardrails": [],
    }


def _render_question(template: str, values: dict[str, str]) -> str:
    result = template
    for key, value in values.items():
        result = result.replace(f"{{{key}}}", value)
    return re.sub(r"\s+", " ", result).strip()


def _manual_question_rows(custom_questions: Iterable[str] | None) -> list[dict[str, str]]:
    """Build scan-specific custom question rows that bypass ranking/scoring."""
    rows: list[dict[str, str]] = []
    for index, question in enumerate(custom_questions or [], start=1):
        clean = re.sub(r"\s+", " ", str(question or "")).strip()
        if not clean:
            continue
        row = {header: "" for header in QUERY_BANK_HEADERS}
        row.update(
            {
                "question": clean,
                "group": MANUAL_GROUP,
                "group_label": MANUAL_GROUP_LABEL,
                "group_rank": str(index),
                "intent_subtype": "client_authored",
                "query_mode": "client_authored",
                "priority": "manual",
                "rank_reason": "Client-authored question for this scan.",
            }
        )
        rows.append(row)
    return rows


def prepare_scan_workspace(
    client: Client,
    context_profile: dict | None = None,
    selected_groups: list[str] | None = None,
    custom_questions: list[str] | None = None,
) -> Path:
    """Create/update the local client folder needed by collect.py."""
    workspace_slug, public_slug = scan_workspace_slugs(client)
    client_folder = CLIENTS_ROOT / workspace_slug
    client_folder.mkdir(parents=True, exist_ok=True)

    competitors = competitor_names_for_scan(client, context_profile)
    profile = {
        "slug": public_slug,
        "display_name": client.name,
        "name": client.name,
        "website_url": client.url,
        "industry": client.industry,
        "location": client.location,
        "competitors": competitors,
        "confirmed_context": context_profile or None,
        "_generated_by": "api.scan_workspace",
    }
    (client_folder / "client_profile.json").write_text(
        json.dumps(profile, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (client_folder / "config.json").write_text(
        json.dumps(
            {
                "slug": public_slug,
                "display_name": client.name,
                "business_name": client.name,
                "url": client.url,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    values = _context_profile_values(client, context_profile) if context_profile else _profile_values(client)
    with (client_folder / "value_bank.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=VALUE_BANK_HEADERS)
        writer.writeheader()
        writer.writerow({key: values.get(key, "") for key in VALUE_BANK_HEADERS})

    bank_path = client_folder / "query_template_bank.csv"
    question_profile = context_profile or _fallback_context_profile(client, competitors)
    rows = profile_to_question_rows(
        question_profile,
        selected_groups=selected_groups,
        report_path=client_folder / "question_ranking_report.json",
    )
    rows.extend(_manual_question_rows(custom_questions))
    if _env_flag("AISO_QUESTION_WRITE_EXTENDED_BANK"):
        extended_rows = profile_to_question_rows(
            question_profile,
            selected_groups=selected_groups,
            report_path=client_folder / "question_ranking_report_extended.json",
            target_env_name="AISO_QUESTION_EXTENDED_GROUP_TARGETS",
            total_env_name="AISO_QUESTION_EXTENDED_TOTAL",
            default_group_targets=DEFAULT_EXTENDED_GROUP_TARGETS,
        )
        with (client_folder / "query_template_bank_extended.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=QUERY_BANK_HEADERS)
            writer.writeheader()
            writer.writerows(extended_rows)

    with bank_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=QUERY_BANK_HEADERS)
        writer.writeheader()
        writer.writerows(rows)

    return client_folder
