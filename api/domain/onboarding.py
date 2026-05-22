"""Business-profile intake and Minimum Context Floor rules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from api.domain.ports import BusinessProfileSnapshot


VERTICAL_CODES = {
    "b2b_saas",
    "b2b_services",
    "local_services",
    "ecommerce",
    "regulated_healthcare",
    "regulated_legal",
    "regulated_financial",
    "consumer_brand",
    "marketplace",
    "agency",
    "enterprise",
}

OBJECTIVE_CODES = {
    "awareness",
    "consideration",
    "preference",
    "reputation_defense",
    "competitive_intelligence",
}


@dataclass(frozen=True)
class ContextRequirement:
    field: str
    min_items: int | None = None


MINIMUM_CONTEXT_FLOOR: dict[str, tuple[ContextRequirement, ...]] = {
    "b2b_saas": (
        ContextRequirement("category"),
        ContextRequirement("icp.firmographics.industry"),
        ContextRequirement("icp.firmographics.employee_band"),
        ContextRequirement("icp.firmographics.revenue_band"),
        ContextRequirement("icp.firmographics.geography"),
        ContextRequirement("icp.acv_band"),
        ContextRequirement("competitors", min_items=3),
        ContextRequirement("personas.primary"),
        ContextRequirement("objective"),
        ContextRequirement("geographic_scope"),
    ),
    "b2b_services": (
        ContextRequirement("icp.service_offerings"),
        ContextRequirement("icp.firmographics"),
        ContextRequirement("icp.engagement_size_band"),
        ContextRequirement("competitors", min_items=3),
        ContextRequirement("personas.primary"),
        ContextRequirement("geographic_scope"),
        ContextRequirement("icp.specialization"),
    ),
    "local_services": (
        ContextRequirement("geographic_scope.nap"),
        ContextRequirement("geographic_scope.service_radius"),
        ContextRequirement("icp.service_taxonomy"),
        ContextRequirement("competitors", min_items=3),
        ContextRequirement("icp.license_cert_numbers"),
        ContextRequirement("objective"),
        ContextRequirement("geographic_scope.hours"),
    ),
    "ecommerce": (
        ContextRequirement("category"),
        ContextRequirement("icp.price_tier_band"),
        ContextRequirement("icp.target_demographic"),
        ContextRequirement("competitors", min_items=3),
        ContextRequirement("icp.marketplace_presence"),
        ContextRequirement("geographic_scope.shipping"),
        ContextRequirement("icp.values_positioning"),
    ),
    "regulated_healthcare": (
        ContextRequirement("category"),
        ContextRequirement("geographic_scope.jurisdictions"),
        ContextRequirement("icp.license_numbers"),
        ContextRequirement("icp.hipaa_constraints"),
        ContextRequirement("icp.prohibited_claims"),
        ContextRequirement("personas.primary"),
        ContextRequirement("competitors", min_items=3),
    ),
    "regulated_legal": (
        ContextRequirement("category"),
        ContextRequirement("geographic_scope.jurisdictions"),
        ContextRequirement("icp.bar_admissions"),
        ContextRequirement("icp.aba_model_rule_constraints"),
        ContextRequirement("icp.prohibited_claims"),
        ContextRequirement("personas.primary"),
        ContextRequirement("competitors", min_items=3),
    ),
    "regulated_financial": (
        ContextRequirement("category"),
        ContextRequirement("geographic_scope.jurisdictions"),
        ContextRequirement("icp.finra_sec_registrations"),
        ContextRequirement("icp.prohibited_claims"),
        ContextRequirement("personas.primary"),
        ContextRequirement("competitors", min_items=3),
    ),
    "consumer_brand": (
        ContextRequirement("icp.brand_archetype"),
        ContextRequirement("icp.product_line_breadth"),
        ContextRequirement("icp.price_tier"),
        ContextRequirement("icp.distribution_channels"),
        ContextRequirement("competitors", min_items=3),
        ContextRequirement("icp.target"),
        ContextRequirement("geographic_scope"),
    ),
    "marketplace": (
        ContextRequirement("icp.supply_value_proposition"),
        ContextRequirement("icp.demand_value_proposition"),
        ContextRequirement("icp.supply_taxonomy"),
        ContextRequirement("icp.demand_icp"),
        ContextRequirement("competitors", min_items=3),
        ContextRequirement("geographic_scope"),
        ContextRequirement("objective"),
    ),
    "agency": (
        ContextRequirement("icp.client_roster_size"),
        ContextRequirement("icp.vertical_distribution"),
        ContextRequirement("icp.aiso_use_case"),
    ),
    "enterprise": (
        ContextRequirement("category"),
        ContextRequirement("icp.firmographics.industry"),
        ContextRequirement("icp.firmographics.employee_band"),
        ContextRequirement("icp.firmographics.revenue_band"),
        ContextRequirement("icp.firmographics.geography"),
        ContextRequirement("icp.acv_band"),
        ContextRequirement("competitors", min_items=3),
        ContextRequirement("personas.primary"),
        ContextRequirement("objective"),
        ContextRequirement("geographic_scope"),
        ContextRequirement("icp.procurement_signals"),
        ContextRequirement("icp.analyst_recognition"),
        ContextRequirement("icp.reference_customer_logos"),
        ContextRequirement("icp.deployment_model"),
        ContextRequirement("icp.buying_committee_size"),
        ContextRequirement("icp.sales_cycle_length_band"),
    ),
}

PATCH_FIELD_PATHS: dict[str, tuple[str, ...]] = {
    "industry": ("icp", "firmographics", "industry"),
    "employee_band": ("icp", "firmographics", "employee_band"),
    "revenue_band": ("icp", "firmographics", "revenue_band"),
    "firmographic_geography": ("icp", "firmographics", "geography"),
    "icp_geography": ("icp", "firmographics", "geography"),
    "acv_band": ("icp", "acv_band"),
    "engagement_size_band": ("icp", "engagement_size_band"),
    "service_offerings": ("icp", "service_offerings"),
    "specialization": ("icp", "specialization"),
    "primary_persona": ("personas", "primary"),
    "economic_buyer": ("personas", "economic_buyer"),
    "end_user": ("personas", "end_user"),
    "nap": ("geographic_scope", "nap"),
    "service_radius": ("geographic_scope", "service_radius"),
    "hours": ("geographic_scope", "hours"),
    "jurisdictions": ("geographic_scope", "jurisdictions"),
    "shipping_geographic_scope": ("geographic_scope", "shipping"),
    "shipping_scope": ("geographic_scope", "shipping"),
    "service_taxonomy": ("icp", "service_taxonomy"),
    "license_cert_numbers": ("icp", "license_cert_numbers"),
    "license_numbers": ("icp", "license_numbers"),
    "hipaa_constraints": ("icp", "hipaa_constraints"),
    "bar_admissions": ("icp", "bar_admissions"),
    "aba_model_rule_constraints": ("icp", "aba_model_rule_constraints"),
    "finra_sec_registrations": ("icp", "finra_sec_registrations"),
    "prohibited_claims": ("icp", "prohibited_claims"),
    "price_tier_band": ("icp", "price_tier_band"),
    "target_demographic": ("icp", "target_demographic"),
    "marketplace_presence": ("icp", "marketplace_presence"),
    "values_positioning": ("icp", "values_positioning"),
    "brand_archetype": ("icp", "brand_archetype"),
    "product_line_breadth": ("icp", "product_line_breadth"),
    "price_tier": ("icp", "price_tier"),
    "distribution_channels": ("icp", "distribution_channels"),
    "target": ("icp", "target"),
    "supply_value_proposition": ("icp", "supply_value_proposition"),
    "demand_value_proposition": ("icp", "demand_value_proposition"),
    "supply_taxonomy": ("icp", "supply_taxonomy"),
    "demand_icp": ("icp", "demand_icp"),
    "client_roster_size": ("icp", "client_roster_size"),
    "vertical_distribution": ("icp", "vertical_distribution"),
    "aiso_use_case": ("icp", "aiso_use_case"),
    "procurement_signals": ("icp", "procurement_signals"),
    "analyst_recognition": ("icp", "analyst_recognition"),
    "reference_customer_logos": ("icp", "reference_customer_logos"),
    "deployment_model": ("icp", "deployment_model"),
    "buying_committee_size": ("icp", "buying_committee_size"),
    "sales_cycle_length_band": ("icp", "sales_cycle_length_band"),
}

TOP_LEVEL_FIELDS = {
    "vertical",
    "objective",
    "category",
    "icp",
    "geographic_scope",
    "competitors",
    "personas",
    "crawl_artifacts",
}


def normalize_vertical(value: str) -> str:
    vertical = str(value or "").strip().lower()
    if vertical not in VERTICAL_CODES:
        raise ValueError(f"Unsupported vertical: {value}")
    return vertical


def normalize_objective(value: str) -> str:
    objective = str(value or "").strip().lower().replace(" ", "_").replace("-", "_")
    if objective not in OBJECTIVE_CODES:
        raise ValueError(f"Unsupported objective: {value}")
    return objective


def normalize_competitors(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("competitors must be a list of strings")

    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            raise ValueError("competitors must be a list of strings")
        clean = " ".join(item.strip().split())
        if not clean:
            continue
        key = clean.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(clean)
    return normalized


def merge_profile_patch(profile_data: dict[str, Any], raw_patch: dict[str, Any]) -> dict[str, Any]:
    merged = _deep_copy_profile(profile_data)

    for field, value in raw_patch.items():
        if value is None:
            continue
        if field == "vertical":
            merged[field] = normalize_vertical(value)
        elif field == "objective":
            merged[field] = normalize_objective(value)
        elif field == "competitors":
            merged[field] = normalize_competitors(value)
        elif field in {"icp", "geographic_scope", "personas", "crawl_artifacts"}:
            existing = merged.get(field) if isinstance(merged.get(field), dict) else {}
            if not isinstance(value, dict):
                raise ValueError(f"{field} must be an object")
            merged[field] = _deep_merge(existing, value)
        elif field in TOP_LEVEL_FIELDS:
            merged[field] = value
        elif field in PATCH_FIELD_PATHS:
            _set_path(merged, PATCH_FIELD_PATHS[field], value)
        else:
            _set_path(merged, ("icp", field), value)

    return merged


def missing_context_fields(snapshot: BusinessProfileSnapshot) -> list[str]:
    profile = profile_data_from_snapshot(snapshot)
    requirements = MINIMUM_CONTEXT_FLOOR.get(snapshot.vertical, ())
    missing: list[str] = []

    for requirement in requirements:
        value = _get_path(profile, requirement.field)
        if not _is_present(value, min_items=requirement.min_items):
            missing.append(requirement.field)

    return missing


def context_floor_met(snapshot: BusinessProfileSnapshot) -> bool:
    return not missing_context_fields(snapshot)


def profile_data_from_snapshot(snapshot: BusinessProfileSnapshot) -> dict[str, Any]:
    return {
        "client_id": snapshot.client_id,
        "vertical": snapshot.vertical,
        "objective": snapshot.objective,
        "category": snapshot.category,
        "icp": snapshot.icp,
        "geographic_scope": snapshot.geographic_scope,
        "competitors": snapshot.competitors,
        "personas": snapshot.personas,
        "crawl_artifacts": snapshot.crawl_artifacts,
    }


def _deep_copy_profile(profile_data: dict[str, Any]) -> dict[str, Any]:
    copied: dict[str, Any] = {}
    for key, value in profile_data.items():
        if isinstance(value, dict):
            copied[key] = _deep_merge({}, value)
        elif isinstance(value, list):
            copied[key] = list(value)
        else:
            copied[key] = value
    return copied


def _deep_merge(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in incoming.items():
        if isinstance(value, dict):
            existing = merged.get(key) if isinstance(merged.get(key), dict) else {}
            merged[key] = _deep_merge(existing, value)
        elif isinstance(value, list):
            merged[key] = list(value)
        else:
            merged[key] = value
    return merged


def _set_path(data: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    cursor = data
    for part in path[:-1]:
        current = cursor.get(part)
        if not isinstance(current, dict):
            current = {}
            cursor[part] = current
        cursor = current
    cursor[path[-1]] = value


def _get_path(data: dict[str, Any], path: str) -> Any:
    cursor: Any = data
    for part in path.split("."):
        if not isinstance(cursor, dict):
            return None
        cursor = cursor.get(part)
    return cursor


def _is_present(value: Any, *, min_items: int | None = None) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        if min_items is not None:
            return len([item for item in value if _is_present(item)]) >= min_items
        return bool(value)
    if isinstance(value, dict):
        if min_items is not None:
            return len(value) >= min_items
        return any(_is_present(item) for item in value.values())
    return True
