"""LLM adapters for Phase 12 realism filtering."""

from __future__ import annotations

from typing import Any
import hashlib
import json
import os
import re

import requests

from api.domain.ports import UpstreamProviderResponse
from api.adapters.openai_chat import OpenAIChatAdapter
from api.adapters.openrouter_chat import OpenRouterChatAdapter
from api.domain.realism_filter import length_penalty, token_count


DEFAULT_REALISM_FILTER_MODEL = "claude-sonnet-4-20250514"


class AnthropicRealismFilterAdapter:
    """Claude adapter for the n=3 realism judge."""

    provider = "anthropic"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        timeout_seconds: float = 30.0,
    ):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        self.model = model or os.getenv("AISO_REALISM_FILTER_MODEL", DEFAULT_REALISM_FILTER_MODEL)
        self.timeout_seconds = timeout_seconds

    def available(self) -> bool:
        return bool(self.api_key)

    def complete(
        self,
        *,
        prompt: str,
        seed: int,
        temperature: float,
        idempotency_key: str,
    ) -> UpstreamProviderResponse:
        if not self.api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is required for Claude realism filtering")

        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": self.model,
                "max_tokens": 300,
                "temperature": temperature,
                "metadata": {"user_id": hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()[:64]},
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        return UpstreamProviderResponse(
            text=_anthropic_text(payload),
            provider="anthropic",
            model=str(payload.get("model") or self.model),
            raw_metadata={
                "id": payload.get("id"),
                "stop_reason": payload.get("stop_reason"),
                "usage": payload.get("usage"),
                "seed": seed,
            },
        )


class HeuristicRealismFilterAdapter:
    """Deterministic local realism judge for tests and offline development."""

    provider = "local"
    model = "realism-filter-heuristic-v1"

    def complete(
        self,
        *,
        prompt: str,
        seed: int,
        temperature: float,
        idempotency_key: str,
    ) -> UpstreamProviderResponse:
        payload = _extract_runtime_inputs(prompt)
        question = str(payload.get("question") or "")
        vertical = str(payload.get("vertical") or "")
        score, rationale = heuristic_realism_score(question, vertical)
        return UpstreamProviderResponse(
            text=json.dumps({"score": score, "rationale": rationale}, sort_keys=True),
            provider=self.provider,
            model=self.model,
            raw_metadata={
                "seed": seed,
                "temperature": temperature,
                "idempotency_hash": hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest(),
            },
        )


def managed_realism_filter_provider():
    """Managed (pro/custom) provider for realism filtering.

    Prefers OpenRouter (free/open models) when keyed, then OpenAI, then the
    deterministic heuristic - onboarding never spends a paid first-party key.
    """
    openrouter = OpenRouterChatAdapter(purpose="realism filtering", max_tokens=300)
    if openrouter.available():
        return openrouter
    openai = OpenAIChatAdapter(purpose="realism filtering", max_tokens=300)
    return openai if openai.available() else HeuristicRealismFilterAdapter()


def heuristic_realism_filter_provider():
    """Free-tier provider: deterministic local realism judge, no server LLM spend."""
    return HeuristicRealismFilterAdapter()


def default_realism_filter_provider():
    anthropic = AnthropicRealismFilterAdapter()
    return anthropic if anthropic.available() else HeuristicRealismFilterAdapter()


def heuristic_realism_score(question: str, vertical: str) -> tuple[float, str]:
    text = re.sub(r"\s+", " ", str(question or "").strip())
    lower = text.lower()
    count = token_count(text)
    if length_penalty(text) == 0.0:
        return 0.0, "Outside the v1 token-length bounds."
    if any(marker in text for marker in ("{{", "}}", "{", "}", "[", "]", "<", ">")):
        return 1.0, "Contains template residue."
    if re.search(r"\btop\s+\d+\b", lower) or "2026" in lower or "best best" in lower:
        return 2.0, "Looks like keyword-stuffed search phrasing."
    if re.search(r"\b\d+\s*[-–]\s*\d+\s+employees\b", lower) or re.search(r"\b\d+\s*[-–]\s*\d+\s+people\b", lower):
        return 3.0, "Overly narrow specificity makes the question unlikely verbatim."
    if re.search(r"\bwhat'?s the best for (our|my|the) team\b", lower):
        return 2.0, "Missing the entity being evaluated."
    if lower.startswith("tell me about ") and count <= 6:
        return 4.0, "Too generic to be a strong buyer question."
    if re.search(r"\b(lorem ipsum|asdf|n/a|xxx)\b", lower):
        return 1.0, "Contains placeholder or nonsense text."
    if lower.count(" near me") > 1:
        return 3.0, "Repeats local modifier unnaturally."
    if "guaranteed cure" in lower:
        return 2.0, "Contains prohibited claim style language."
    if count < 6 or count > 18:
        return 6.5, "Understandable but outside the target length band."
    if not text.endswith("?"):
        return 6.0, "Question is not well-formed as a question."
    if _has_specific_context(lower, vertical):
        return 9.0, "Natural buyer phrasing with concrete context."
    return 7.5, "Plausible buyer phrasing."


def _has_specific_context(lower: str, vertical: str) -> bool:
    buyer_markers = (
        "for ",
        "with ",
        "vs",
        "integrate",
        "pricing",
        "reviews",
        "alternatives",
        "compare",
        "shortlist",
        "demo",
        "support",
        "near me",
        "cost",
        "worth it",
    )
    vertical_markers = {
        "b2b_saas": ("crm", "saas", "sales", "revops", "pipeline", "implementation", "hubspot", "salesforce"),
        "local_services": ("near me", "licensed", "emergency", "appointment", "repair", "cost"),
        "ecommerce": ("buy", "reviews", "under", "worth it", "shipping", "return"),
    }
    markers = vertical_markers.get(vertical, ())
    return any(marker in lower for marker in buyer_markers) or any(marker in lower for marker in markers)


def _anthropic_text(payload: dict[str, Any]) -> str:
    pieces: list[str] = []
    for block in payload.get("content", []) if isinstance(payload.get("content"), list) else []:
        if isinstance(block, dict) and block.get("type") == "text":
            pieces.append(str(block.get("text") or ""))
    return "\n".join(piece for piece in pieces if piece).strip()


def _extract_runtime_inputs(prompt: str) -> dict[str, Any]:
    start = prompt.find("<runtime_inputs>")
    end = prompt.rfind("</runtime_inputs>")
    if start < 0 or end < 0 or end <= start:
        return {}
    raw = prompt[start + len("<runtime_inputs>"):end].strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
