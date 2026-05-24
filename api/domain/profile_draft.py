"""Confirmable business-profile drafting from crawler artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
import json
import re

from api.domain.ports import BusinessProfileSnapshot, UpstreamLLMProvider, UpstreamProviderResponse


PROFILE_DRAFT_PROMPT_KEY = "profile_draft"
PROFILE_DRAFT_PROMPT_VERSION = "profile_draft-1.0.0"
PROFILE_DRAFT_SEED = 1204

FIELD_CRAWLED = "crawled"
FIELD_GUESSED = "guessed"
FIELD_NEEDS_YOU = "needs_you"
FIELD_SOURCES = {FIELD_CRAWLED, FIELD_GUESSED, FIELD_NEEDS_YOU}

PROFILE_DRAFT_SYSTEM_PROMPT = """<system>
You draft AISO onboarding business profiles from public crawl artifacts.

Return JSON only. Do not wrap it in markdown.

Rules:
- Use only the supplied crawl_artifacts and existing_profile.
- Auto-extract brand/category, public NAP, product/service taxonomy, public pricing, and schema.org entities when evidence exists.
- You may infer broad category, geography, and persona only when strongly implied; mark those fields as "guessed".
- Do not invent ICP firmographics, ACV, competitors, strategic objective, licenses, compliance constraints, or deal-loss information.
- Mark any human-owned or insufficiently evidenced field as "needs_you".
- Preserve existing customer-entered values when present, but still flag fields that require customer confirmation as "needs_you".

Output shape:
{
  "category": "string",
  "geographic_scope": {},
  "icp": {},
  "competitors": [],
  "personas": {},
  "field_sources": {
    "category": "crawled|guessed|needs_you",
    "geographic_scope": "crawled|guessed|needs_you",
    "icp": "crawled|guessed|needs_you",
    "competitors": "crawled|guessed|needs_you",
    "personas": "crawled|guessed|needs_you",
    "objective": "needs_you"
  },
  "rationale": {}
}
</system>"""


@dataclass(frozen=True)
class ProfileDraftResult:
    profile_data: dict[str, Any]
    field_sources: dict[str, str]
    rationale: dict[str, str]
    provider_response: UpstreamProviderResponse
    prompt_text: str


def render_profile_draft_prompt(snapshot: BusinessProfileSnapshot) -> str:
    payload = {
        "existing_profile": {
            "client_id": snapshot.client_id,
            "vertical": snapshot.vertical,
            "objective": snapshot.objective,
            "category": snapshot.category,
            "icp": snapshot.icp,
            "geographic_scope": snapshot.geographic_scope,
            "competitors": snapshot.competitors,
            "personas": snapshot.personas,
        },
        "crawl_artifacts": snapshot.crawl_artifacts,
    }
    return (
        f"{PROFILE_DRAFT_SYSTEM_PROMPT}\n\n"
        "<inputs>\n"
        f"{json.dumps(payload, sort_keys=True, ensure_ascii=False)}\n"
        "</inputs>"
    )


def generate_profile_draft(
    snapshot: BusinessProfileSnapshot,
    provider: UpstreamLLMProvider,
    *,
    idempotency_key: str,
) -> ProfileDraftResult:
    prompt_text = render_profile_draft_prompt(snapshot)
    response = provider.complete(
        prompt=prompt_text,
        seed=PROFILE_DRAFT_SEED,
        temperature=0.1,
        idempotency_key=idempotency_key,
    )
    raw = _parse_json_response(response.text)
    profile_data, field_sources, rationale = build_confirmable_profile_draft(snapshot, raw)
    return ProfileDraftResult(
        profile_data=profile_data,
        field_sources=field_sources,
        rationale=rationale,
        provider_response=response,
        prompt_text=prompt_text,
    )


def build_confirmable_profile_draft(
    snapshot: BusinessProfileSnapshot,
    llm_payload: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, str], dict[str, str]]:
    llm_payload = llm_payload if isinstance(llm_payload, dict) else {}
    artifacts = snapshot.crawl_artifacts if isinstance(snapshot.crawl_artifacts, dict) else {}
    auto = artifacts.get("auto_extracted") if isinstance(artifacts.get("auto_extracted"), dict) else {}

    category = _clean(llm_payload.get("category")) or snapshot.category or _category_from_artifacts(auto)
    geographic_scope = _dict_value(llm_payload.get("geographic_scope")) or snapshot.geographic_scope or _geography_from_artifacts(auto)
    icp = _dict_value(llm_payload.get("icp")) or snapshot.icp
    competitors = _list_value(llm_payload.get("competitors")) or snapshot.competitors
    personas = _dict_value(llm_payload.get("personas")) or snapshot.personas

    raw_sources = llm_payload.get("field_sources") if isinstance(llm_payload.get("field_sources"), dict) else {}
    field_sources = {
        "category": _source(raw_sources.get("category")) or (FIELD_CRAWLED if category and _category_from_artifacts(auto) else FIELD_GUESSED if category else FIELD_NEEDS_YOU),
        "geographic_scope": _source(raw_sources.get("geographic_scope")) or (FIELD_CRAWLED if geographic_scope and _geography_from_artifacts(auto) else FIELD_GUESSED if geographic_scope else FIELD_NEEDS_YOU),
        "icp": FIELD_NEEDS_YOU,
        "competitors": FIELD_NEEDS_YOU,
        "personas": _source(raw_sources.get("personas")) or (FIELD_GUESSED if personas else FIELD_NEEDS_YOU),
        "objective": FIELD_NEEDS_YOU,
    }

    rationale = _rationale(llm_payload.get("rationale"))
    profile_data = {
        "vertical": snapshot.vertical,
        "objective": snapshot.objective,
        "category": category,
        "icp": icp,
        "geographic_scope": geographic_scope,
        "competitors": competitors,
        "personas": personas,
        "crawl_artifacts": snapshot.crawl_artifacts,
    }
    return profile_data, field_sources, rationale


def profile_draft_artifact(
    *,
    result: ProfileDraftResult,
    prompt_version_id: str,
    prompt_version: str = PROFILE_DRAFT_PROMPT_VERSION,
) -> dict[str, Any]:
    return {
        "schema_version": "profile_draft.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "prompt_key": PROFILE_DRAFT_PROMPT_KEY,
        "prompt_version": prompt_version,
        "prompt_version_id": prompt_version_id,
        "provider": result.provider_response.provider,
        "model": result.provider_response.model,
        "field_sources": result.field_sources,
        "rationale": result.rationale,
    }


def _parse_json_response(text: str) -> dict[str, Any]:
    clean = str(text or "").strip()
    if clean.startswith("```"):
        clean = re.sub(r"^```(?:json)?\s*", "", clean, flags=re.I)
        clean = re.sub(r"\s*```$", "", clean)
    try:
        parsed = json.loads(clean)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", clean, flags=re.S)
        if not match:
            return {}
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}
    return parsed if isinstance(parsed, dict) else {}


def _category_from_artifacts(auto: dict[str, Any]) -> str:
    taxonomy = auto.get("product_service_taxonomy")
    if isinstance(taxonomy, list):
        for item in taxonomy:
            clean = _clean(item)
            if clean:
                return clean
    schema_types = auto.get("schema_entity_types")
    if isinstance(schema_types, list) and schema_types:
        return " / ".join(_clean(item) for item in schema_types if _clean(item))
    return ""


def _geography_from_artifacts(auto: dict[str, Any]) -> dict[str, Any]:
    nap = auto.get("nap")
    if isinstance(nap, dict) and nap:
        return {"nap": nap}
    return {}


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list_value(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        clean = _clean(item)
        if clean and clean not in result:
            result.append(clean)
    return result


def _source(value: Any) -> str:
    clean = _clean(value)
    return clean if clean in FIELD_SOURCES else ""


def _rationale(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): _clean(raw) for key, raw in value.items() if _clean(raw)}


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())
