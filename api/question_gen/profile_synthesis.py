"""AI-drafted profile fields for onboarding ("AI drafts, you confirm").

Given a brand and its crawled homepage text, an LLM synthesizes clean, editable
fields - a plain-language description, an industry, target audiences, and
suggested competitors. This is the confirm-first replacement for the regex slot
extraction (offerings/locations) that produced garbage: the model reads the site
copy and writes natural language, and the user edits before anything runs.

Deliberately lean and stateless (mirrors question_gen/review.py):
- Input is the clean crawl text (tagline + about copy), never the regex slots.
- Nothing is persisted here; the route returns the fields and the browser holds
  them for the user to confirm.
- A deterministic fallback covers free tier and provider failures so onboarding
  never dead-ends.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import re

from api.domain.ports import UpstreamLLMProvider

logger = logging.getLogger(__name__)

PROFILE_SYNTHESIS_SEED = 1207
_LLM_PROVIDERS = {"openrouter", "openai", "anthropic"}
_MAX_AUDIENCES = 6
_MAX_COMPETITORS = 8


@dataclass(frozen=True)
class DraftedFields:
    description: str
    industry: str
    audiences: list[str]
    competitors: list[str]
    provider: str
    model: str


def synthesize_profile_fields(
    *,
    brand_name: str,
    crawl_artifacts: dict | None,
    provider: UpstreamLLMProvider,
    existing_competitors: list[str] | None = None,
    variation: int = 0,
) -> DraftedFields:
    """Draft {description, industry, audiences, competitors} for the review UI."""
    brand = _clean(brand_name) or "the brand"
    tagline, about = _clean_source_text(crawl_artifacts)
    existing = _string_list(existing_competitors)
    provider_name = str(getattr(provider, "provider", "")).strip().lower()

    if provider_name in _LLM_PROVIDERS:
        try:
            fields = _llm_fields(brand, tagline, about, existing, provider, variation)
            if fields and fields.description:
                return fields
            logger.warning("profile synthesis: %s returned no usable draft, using fallback", provider_name)
        except Exception as exc:  # never dead-end onboarding on a provider fault
            logger.warning("profile synthesis: %s failed (%s), using fallback", provider_name, exc)

    return _fallback_fields(brand, tagline, about, existing, provider_name)


# ---------------------------------------------------------------------------
# LLM path
# ---------------------------------------------------------------------------

def _llm_fields(brand, tagline, about, existing, provider, variation) -> DraftedFields:
    prompt = _render_prompt(brand, tagline, about, existing)
    response = provider.complete(
        prompt=prompt,
        seed=PROFILE_SYNTHESIS_SEED + variation,
        temperature=0.4 if not variation else 0.6,
        idempotency_key=f"profile-fields:{brand}:{variation}",
    )
    data = _coerce_json(response.text) or {}
    description = _clean(data.get("description"))[:500]
    industry = _clean(data.get("industry"))[:120]
    audiences = _string_list(data.get("audiences"))[:_MAX_AUDIENCES]
    # Suggested competitors: keep the user's existing ones first, then the model's.
    competitors = _dedupe(existing + _string_list(data.get("competitors")))[:_MAX_COMPETITORS]
    return DraftedFields(
        description=description,
        industry=industry,
        audiences=audiences,
        competitors=competitors,
        provider="openrouter" if getattr(provider, "provider", "") == "openrouter" else str(getattr(provider, "provider", "llm")),
        model=str(response.model),
    )


def _render_prompt(brand, tagline, about, existing) -> str:
    competitor_line = ", ".join(existing) if existing else "(none provided)"
    site_text = "\n".join(part for part in (f"Tagline: {tagline}" if tagline else "", f"About: {about}" if about else "") if part)
    site_block = site_text or "(no site text was captured; use what you know about the brand)"
    return f"""You are AISO's onboarding assistant. Draft a business profile for "{brand}" that the user will confirm.

Site text captured from {brand}'s homepage:
{site_block}

Return ONLY a JSON object, no prose and no code fence:
{{"description": "...", "industry": "...", "audiences": ["..."], "competitors": ["..."]}}

- "description": 1-2 plain sentences on what {brand} does and who it is for. No marketing fluff, no legalese. <= 400 chars.
- "industry": a short category label (e.g. "AI creative tools", "CRM software", "boutique skincare spa").
- "audiences": 2-5 short phrases for who buys/uses it (e.g. "creative teams", "enterprise support leaders").
- "competitors": up to 6 real competing brands. Keep these already provided: {competitor_line}. Add real ones you know; if unsure, return only the provided list. Never invent fake names.

Base everything on the site text and what you reliably know about {brand}. Do not include Terms-of-Service or legal boilerplate.
"""


# ---------------------------------------------------------------------------
# Deterministic fallback
# ---------------------------------------------------------------------------

def _fallback_fields(brand, tagline, about, existing, provider_name) -> DraftedFields:
    # Build a description from the cleanest available site copy.
    source = about or tagline
    description = _first_sentences(source, limit=2) if source else f"{brand} - add a short description of what you do."
    industry = _clean(tagline)[:80] if tagline and len(tagline.split()) <= 8 else ""
    return DraftedFields(
        description=description[:500],
        industry=industry,
        audiences=[],
        competitors=_dedupe(existing)[:_MAX_COMPETITORS],
        provider=provider_name or "local",
        model="fallback",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean_source_text(crawl_artifacts: dict | None) -> tuple[str, str]:
    auto = {}
    if isinstance(crawl_artifacts, dict):
        raw = crawl_artifacts.get("auto_extracted")
        auto = raw if isinstance(raw, dict) else {}
    tagline = _clean(auto.get("tagline"))
    about = _clean(auto.get("about_copy"))
    return tagline, about


def _coerce_json(text: str):
    clean = str(text or "").strip()
    if clean.startswith("```"):
        clean = re.sub(r"^```(?:json)?\s*", "", clean, flags=re.I)
        clean = re.sub(r"\s*```$", "", clean)
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", clean, flags=re.S)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                return None
    return None


def _clean(value) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _first_sentences(text: str, *, limit: int) -> str:
    parts = re.split(r"(?<=[.!?])\s+", _clean(text))
    return " ".join(parts[:limit]).strip()


def _string_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_clean(item) for item in value if _clean(item)]


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.casefold()
        if item and key not in seen:
            seen.add(key)
            out.append(item)
    return out
