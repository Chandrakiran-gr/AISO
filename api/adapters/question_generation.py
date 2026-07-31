"""LLM adapters for Phase 12 question generation."""

from __future__ import annotations

from typing import Any
import hashlib
import json
import os

import requests

from api.domain.ports import UpstreamProviderResponse
from api.adapters.openai_chat import OpenAIChatAdapter
from api.adapters.openrouter_chat import OpenRouterChatAdapter
from api.domain.question_generation import (
    QUESTION_GENERATION_SEED,
    context_from_runtime_payload,
    heuristic_question_candidates,
)


DEFAULT_QUESTION_GENERATION_MODEL = "claude-sonnet-4-20250514"


class AnthropicQuestionGenerationAdapter:
    """Claude adapter for candidate-pool generation.

    Credentials are process environment configuration only. User BYOK values are
    never read from or written to this path.
    """

    provider = "anthropic"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        timeout_seconds: float = 60.0,
    ):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        self.model = model or os.getenv("AISO_QUESTION_GENERATION_MODEL", DEFAULT_QUESTION_GENERATION_MODEL)
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
            raise RuntimeError("ANTHROPIC_API_KEY is required for Claude question generation")

        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": self.model,
                "max_tokens": 12000,
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


class HeuristicQuestionGenerationAdapter:
    """Deterministic local adapter used when Claude credentials are absent."""

    provider = "local"
    model = "question-generation-heuristic-v1"

    def complete(
        self,
        *,
        prompt: str,
        seed: int,
        temperature: float,
        idempotency_key: str,
    ) -> UpstreamProviderResponse:
        payload = _extract_runtime_inputs(prompt)
        context = context_from_runtime_payload(payload)
        candidates = heuristic_question_candidates(context)
        rows = [
            {
                "question": candidate.text,
                "journey_stage": candidate.journey_stage,
                "brand_frame": candidate.brand_frame,
                "intent_class": candidate.intent_class,
                "persona": candidate.persona,
                "locality": candidate.locality,
                "rationale": candidate.rationale,
            }
            for candidate in candidates
        ]
        return UpstreamProviderResponse(
            text=json.dumps(rows, sort_keys=True),
            provider=self.provider,
            model=self.model,
            raw_metadata={
                "seed": seed or QUESTION_GENERATION_SEED,
                "temperature": temperature,
                "idempotency_hash": hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest(),
            },
        )


def managed_question_generation_provider():
    """Managed (pro/custom) provider for candidate generation.

    Prefers OpenRouter (free/open models) when ``OPENROUTER_API_KEY`` is set -
    the company's chosen onboarding-generation backend, so onboarding never
    spends a paid first-party key. Falls back to OpenAI when only that key is
    configured, then to the deterministic heuristic so an unkeyed environment
    still produces a candidate pool.
    """
    openrouter = OpenRouterChatAdapter(purpose="question generation", max_tokens=12000)
    if openrouter.available():
        return openrouter
    openai = OpenAIChatAdapter(purpose="question generation", max_tokens=12000)
    return openai if openai.available() else HeuristicQuestionGenerationAdapter()


def heuristic_question_generation_provider():
    """Free-tier provider: deterministic local generation, no server LLM spend."""
    return HeuristicQuestionGenerationAdapter()


def default_question_generation_provider():
    anthropic = AnthropicQuestionGenerationAdapter()
    return anthropic if anthropic.available() else HeuristicQuestionGenerationAdapter()


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
