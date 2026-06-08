"""LLM adapters for Phase 12 profile drafting."""

from __future__ import annotations

from typing import Any
import hashlib
import json
import os

import requests

from api.domain.ports import UpstreamProviderResponse
from api.adapters.openai_chat import OpenAIChatAdapter


DEFAULT_PROFILE_DRAFT_MODEL = "claude-sonnet-4-20250514"


class AnthropicProfileDraftAdapter:
    """Claude adapter for confirmable profile drafting.

    The API key comes from process environment, not from user BYOK storage, and
    is never returned, logged, or persisted.
    """

    provider = "anthropic"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        timeout_seconds: float = 30.0,
    ):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        self.model = model or os.getenv("AISO_PROFILE_DRAFT_MODEL", DEFAULT_PROFILE_DRAFT_MODEL)
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
            raise RuntimeError("ANTHROPIC_API_KEY is required for Claude profile drafting")

        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": self.model,
                "max_tokens": 1800,
                "temperature": temperature,
                "metadata": {"user_id": hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()[:64]},
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        text = _anthropic_text(payload)
        return UpstreamProviderResponse(
            text=text,
            provider="anthropic",
            model=str(payload.get("model") or self.model),
            raw_metadata={
                "id": payload.get("id"),
                "stop_reason": payload.get("stop_reason"),
                "usage": payload.get("usage"),
                "seed": seed,
            },
        )


class HeuristicProfileDraftAdapter:
    """Deterministic local adapter used when Claude credentials are absent."""

    provider = "local"
    model = "profile-draft-heuristic-v1"

    def complete(
        self,
        *,
        prompt: str,
        seed: int,
        temperature: float,
        idempotency_key: str,
    ) -> UpstreamProviderResponse:
        inputs = _extract_inputs(prompt)
        existing = inputs.get("existing_profile") if isinstance(inputs.get("existing_profile"), dict) else {}
        artifacts = inputs.get("crawl_artifacts") if isinstance(inputs.get("crawl_artifacts"), dict) else {}
        auto = artifacts.get("auto_extracted") if isinstance(artifacts.get("auto_extracted"), dict) else {}

        taxonomy = auto.get("product_service_taxonomy") if isinstance(auto.get("product_service_taxonomy"), list) else []
        category = str(existing.get("category") or "").strip()
        if not category and taxonomy:
            category = str(taxonomy[0]).strip()

        nap = auto.get("nap") if isinstance(auto.get("nap"), dict) else {}
        geographic_scope = dict(existing.get("geographic_scope") or {})
        if nap:
            geographic_scope.setdefault("nap", nap)

        payload = {
            "category": category,
            "geographic_scope": geographic_scope,
            "icp": existing.get("icp") if isinstance(existing.get("icp"), dict) else {},
            "competitors": existing.get("competitors") if isinstance(existing.get("competitors"), list) else [],
            "personas": existing.get("personas") if isinstance(existing.get("personas"), dict) else {},
            "field_sources": {
                "category": "crawled" if category and taxonomy else "needs_you",
                "geographic_scope": "crawled" if nap else "needs_you",
                "icp": "needs_you",
                "competitors": "needs_you",
                "personas": "needs_you",
                "objective": "needs_you",
            },
            "rationale": {
                "category": "Derived from public product/service taxonomy." if taxonomy else "No reliable category evidence.",
                "geographic_scope": "Derived from public LocalBusiness/NAP evidence." if nap else "No reliable geography evidence.",
                "icp": "ICP requires customer confirmation.",
                "competitors": "Competitors must be declared by the customer.",
                "objective": "Strategic objective must be selected by the customer.",
            },
        }
        return UpstreamProviderResponse(
            text=json.dumps(payload, sort_keys=True),
            provider=self.provider,
            model=self.model,
            raw_metadata={
                "seed": seed,
                "temperature": temperature,
                "idempotency_hash": hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest(),
            },
        )


def managed_profile_draft_provider():
    """Managed (pro/custom) provider: OpenAI, falling back to heuristic if unkeyed."""
    openai = OpenAIChatAdapter(purpose="profile drafting", max_tokens=1800)
    return openai if openai.available() else HeuristicProfileDraftAdapter()


def heuristic_profile_draft_provider():
    """Free-tier provider: deterministic local drafting, no server LLM spend."""
    return HeuristicProfileDraftAdapter()


def default_profile_draft_provider():
    anthropic = AnthropicProfileDraftAdapter()
    return anthropic if anthropic.available() else HeuristicProfileDraftAdapter()


def _anthropic_text(payload: dict[str, Any]) -> str:
    pieces: list[str] = []
    for block in payload.get("content", []) if isinstance(payload.get("content"), list) else []:
        if isinstance(block, dict) and block.get("type") == "text":
            pieces.append(str(block.get("text") or ""))
    return "\n".join(piece for piece in pieces if piece).strip()


def _extract_inputs(prompt: str) -> dict[str, Any]:
    start = prompt.find("<inputs>")
    end = prompt.rfind("</inputs>")
    if start < 0 or end < 0 or end <= start:
        return {}
    raw = prompt[start + len("<inputs>"):end].strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
