"""Review-prompt generation for the onboarding "Review prompts" step.

Produces a small, natural-language prompt set split into "branded" (the buyer
names your brand) and "category" (category-level demand with no brand named)
that the user reviews and edits before launching a scan. This replaces the
deterministic G1-G7 slot-template generator whose regex-extracted
"offerings"/"locations" produced garbage prompts.

Design notes:
- Lean prompt. We ask the model for short question STRINGS in two buckets, not
  the heavy Phase 12 lattice (journey/frame/intent/persona per row) - that made a
  free model time out. Small output -> fast, reliable review screen.
- Stateless. Nothing is persisted. The browser holds the editable list and sends
  the approved prompts to the scan endpoint, exactly how custom questions flow.
  "Regenerate" bumps ``variation`` for a fresh set.
- Never dead-ends. On any provider failure, or for the free-tier heuristic
  provider, a deterministic profile-based fallback fills the set so onboarding
  always advances.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import re

from api.database import Client
from api.domain.ports import BusinessProfileSnapshot, UpstreamLLMProvider
from api.domain.question_generation import (
    QUESTION_GENERATION_SEED,
    context_from_snapshot,
    heuristic_question_candidates,
    prompt_kind,
)

logger = logging.getLogger(__name__)

DEFAULT_REVIEW_PROMPT_COUNT = 45
_MAX_TOTAL_PROMPTS = 80
# Pass-through LLM adapters (prompt in -> text out). The heuristic/local adapter
# has its own prompt contract, so it takes the deterministic path instead.
_LLM_PROVIDERS = {"openrouter", "openai", "anthropic"}

_FRAME_FOR_KIND = {"branded": "brand_only", "category": "unbranded_category"}


@dataclass(frozen=True)
class ReviewPrompt:
    text: str
    kind: str  # "branded" | "category"
    journey_stage: str
    brand_frame: str
    rationale: str | None = None


@dataclass(frozen=True)
class ReviewPromptSet:
    prompts: list[ReviewPrompt]
    provider: str
    model: str


def generate_review_prompts(
    *,
    client: Client,
    snapshot: BusinessProfileSnapshot,
    provider: UpstreamLLMProvider,
    final_count: int = DEFAULT_REVIEW_PROMPT_COUNT,
    variation: int = 0,
) -> ReviewPromptSet:
    """Generate the natural-language prompt set for the review screen.

    ``variation`` (bumped by the UI's "Regenerate") shifts the seed and raises
    temperature so a second call returns a fresh set rather than the same list.
    """
    context = context_from_snapshot(snapshot, brand_name=client.name)
    provider_name = str(getattr(provider, "provider", "")).strip().lower()

    if provider_name in _LLM_PROVIDERS:
        try:
            prompts, model = _llm_review_prompts(context, provider, final_count, variation)
            if prompts:
                return ReviewPromptSet(prompts=prompts, provider=provider_name, model=model)
            logger.warning("review prompts: %s returned no usable prompts, using fallback", provider_name)
        except Exception as exc:  # never dead-end onboarding on a provider fault
            logger.warning("review prompts: %s failed (%s), using fallback", provider_name, exc)

    prompts = _fallback_review_prompts(context, final_count)
    return ReviewPromptSet(
        prompts=prompts,
        provider=provider_name or "local",
        model=str(getattr(provider, "model", "heuristic")),
    )


# ---------------------------------------------------------------------------
# LLM path
# ---------------------------------------------------------------------------

def _llm_review_prompts(
    context, provider, final_count: int, variation: int
) -> tuple[list[ReviewPrompt], str]:
    branded_n = max(4, round(final_count * 0.15))
    category_n = max(1, final_count - branded_n)
    prompt_text = _render_review_prompt(context, branded_n, category_n)
    response = provider.complete(
        prompt=prompt_text,
        seed=QUESTION_GENERATION_SEED + variation,
        temperature=min(0.9, 0.6 + 0.1 * variation),
        idempotency_key=f"review-prompts:{context.client_id}:{variation}",
    )
    prompts = _parse_review_payload(response.text, context)
    return prompts, str(response.model)


def _render_review_prompt(context, branded_n: int, category_n: int) -> str:
    brand = context.brand_name or "the brand"
    category = context.category or "solution"
    competitors = [c for c in context.competitors if str(c).strip()]
    competitor_line = ", ".join(competitors) if competitors else "(none provided)"
    audience = _audience(context)
    geo = _geo(context)
    competitor_rule = (
        f"Only name real competitors from this list: {competitor_line}."
        if competitors
        else "No competitor list was provided - do NOT invent competitors or write comparison/'vs'/'alternatives to' questions."
    )
    return f"""You are AISO's onboarding assistant. A business wants to measure how visible it is when real buyers ask AI assistants (ChatGPT, Claude, Perplexity, Gemini) about its category and brand.

Business: {brand}
Category: {category}
Who is searching: {audience}
Market: {geo}
Competitors: {competitor_line}

Write natural-language questions a real buyer would type into an AI assistant while researching this. Return ONLY a JSON object, no prose and no code fence:
{{"branded": ["..."], "category": ["..."]}}

"branded": ~{branded_n} questions that NAME the brand "{brand}" - e.g. "{brand} reviews", "is {brand} good for {audience}", "{brand} pricing", "{brand} vs a competitor".
"category": ~{category_n} category-level questions that name NO brand - e.g. "best {category} for ...", "top {category} tools for ...", "how do I choose a {category}".

Rules:
- Natural and conversational, 6 to 16 words. A real person would actually ask these.
- No keyword stuffing, no numbering, no duplicates, no markdown.
- Vary the intent across discovery, comparison, pricing, reviews/trust, and fit for {audience}.
- {competitor_rule}
"""


def _parse_review_payload(text: str, context) -> list[ReviewPrompt]:
    data = _coerce_json(text)
    prompts: list[ReviewPrompt] = []
    seen: set[str] = set()

    def add(raw_text, kind: str, brand_frame: str | None = None):
        clean = _clean(raw_text)
        if not clean:
            return
        key = clean.casefold()
        if key in seen or len(prompts) >= _MAX_TOTAL_PROMPTS:
            return
        seen.add(key)
        frame = (brand_frame or _FRAME_FOR_KIND[kind]).strip().lower()
        # A branded prompt that names a competitor is a comparison.
        if kind == "branded" and _names_competitor(clean, context):
            frame = "branded_comparison"
        prompts.append(
            ReviewPrompt(text=clean, kind=kind, journey_stage=_infer_stage(clean), brand_frame=frame)
        )

    if isinstance(data, dict):
        for item in data.get("branded") or []:
            add(item if isinstance(item, str) else (item or {}).get("question") or (item or {}).get("text"), "branded")
        for item in data.get("category") or []:
            add(item if isinstance(item, str) else (item or {}).get("question") or (item or {}).get("text"), "category")
    elif isinstance(data, list):
        # Some models return a flat array of objects; classify by brand_frame or text.
        for item in data:
            if isinstance(item, str):
                add(item, "category")
                continue
            if not isinstance(item, dict):
                continue
            raw = item.get("question") or item.get("text")
            frame = str(item.get("brand_frame") or "").strip().lower()
            kind = prompt_kind(frame) if frame else _kind_from_text(raw, context)
            add(raw, kind, frame or None)
    return prompts


# ---------------------------------------------------------------------------
# Deterministic fallback (free tier / provider failure)
# ---------------------------------------------------------------------------

def _fallback_review_prompts(context, final_count: int) -> list[ReviewPrompt]:
    candidates = heuristic_question_candidates(context)
    prompts: list[ReviewPrompt] = []
    seen: set[str] = set()
    for candidate in candidates:
        clean = _clean(candidate.text)
        key = clean.casefold()
        if not clean or key in seen:
            continue
        seen.add(key)
        prompts.append(
            ReviewPrompt(
                text=clean,
                kind=prompt_kind(candidate.brand_frame),
                journey_stage=candidate.journey_stage,
                brand_frame=candidate.brand_frame,
                rationale=candidate.rationale,
            )
        )
        if len(prompts) >= final_count:
            break
    return prompts


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _coerce_json(text: str):
    clean = str(text or "").strip()
    if clean.startswith("```"):
        clean = re.sub(r"^```(?:json)?\s*", "", clean, flags=re.I)
        clean = re.sub(r"\s*```$", "", clean)
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        pass
    for pattern in (r"\{.*\}", r"\[.*\]"):
        match = re.search(pattern, clean, flags=re.S)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                continue
    return None


def _clean(value) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    text = text.strip().strip("-•*").strip()
    text = re.sub(r"^\d+[.)]\s*", "", text)  # drop stray list numbering
    if len(text) > 500:
        text = text[:500].rstrip()
    return text


def _audience(context) -> str:
    parts: list[str] = []
    for value in context.personas.values():
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
        elif isinstance(value, list):
            parts.extend(str(item).strip() for item in value if str(item).strip())
    firm = context.icp.get("firmographics") if isinstance(context.icp.get("firmographics"), dict) else {}
    industry = str(firm.get("industry") or context.icp.get("industry") or "").strip()
    if industry:
        parts.append(f"{industry} companies")
    # Cap to keep generated prompts tight - a long run-on audience produces
    # clunky questions ("... support RevOps manager SaaS companies").
    unique = list(dict.fromkeys(parts))[:2]
    return ", ".join(unique) or "the target buyer"


def _geo(context) -> str:
    geo = context.geographic_scope if isinstance(context.geographic_scope, dict) else {}
    if isinstance(geo.get("description"), str) and geo["description"].strip():
        return geo["description"].strip()
    countries = geo.get("countries") if isinstance(geo.get("countries"), list) else []
    named = ", ".join(str(c).strip() for c in countries if str(c).strip())
    return named or "global"


def _names_competitor(text: str, context) -> bool:
    lower = text.lower()
    return any(str(c).strip() and str(c).strip().lower() in lower for c in context.competitors)


def _kind_from_text(text, context) -> str:
    lower = str(text or "").lower()
    brand = (context.brand_name or "").strip().lower()
    return "branded" if brand and brand in lower else "category"


def _infer_stage(text: str) -> str:
    lower = text.lower()
    if any(w in lower for w in ("price", "pricing", "cost", "how much", "quote", "per month", "per user", "plan")):
        return "J4"
    if any(w in lower for w in ("review", "complaint", "trust", "reliable", "legit", "reputation", "worth it")):
        return "J5"
    if any(w in lower for w in (" vs ", "versus", "alternative", "compare", "better than", "instead of", "switch from")):
        return "J3"
    if any(w in lower for w in ("best ", "top ", "what is", "which ", "how do i choose", "looking for", "recommend")):
        return "J1"
    return "J2"
