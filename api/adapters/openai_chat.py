"""Shared OpenAI chat-completions adapter for managed onboarding LLM steps.

Used by the **pro/custom** onboarding path (profile draft, question generation,
scoring, realism). Free tier never reaches this — it runs the deterministic
heuristic adapters so a free signup never spends the company's API budget.

The OpenAI key comes from the process environment, never from user BYOK storage,
and is never returned, logged, or persisted.
"""

from __future__ import annotations

from typing import Any
import os

import requests

from api.domain.ports import UpstreamProviderResponse

OPENAI_CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_ONBOARDING_OPENAI_MODEL = "gpt-4o"


class OpenAIChatAdapter:
    """OpenAI chat-completions adapter implementing the ``UpstreamLLMProvider`` port.

    One generic adapter reused across the onboarding steps; ``purpose`` (for error
    messages) and ``max_tokens`` are the only per-step differences. The model
    defaults to ``gpt-4o`` and is overridable via ``AISO_ONBOARDING_OPENAI_MODEL``.
    """

    provider = "openai"

    def __init__(
        self,
        *,
        purpose: str,
        max_tokens: int,
        api_key: str | None = None,
        model: str | None = None,
        timeout_seconds: float = 60.0,
    ):
        self.purpose = purpose
        self.max_tokens = max_tokens
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self.model = model or os.getenv("AISO_ONBOARDING_OPENAI_MODEL", DEFAULT_ONBOARDING_OPENAI_MODEL)
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
            raise RuntimeError(f"OPENAI_API_KEY is required for OpenAI {self.purpose}")

        response = requests.post(
            OPENAI_CHAT_COMPLETIONS_URL,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "max_tokens": self.max_tokens,
                "temperature": temperature,
                "seed": seed,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        return UpstreamProviderResponse(
            text=_openai_text(payload),
            provider="openai",
            model=str(payload.get("model") or self.model),
            raw_metadata={
                "id": payload.get("id"),
                "finish_reason": _openai_finish_reason(payload),
                "usage": payload.get("usage"),
                "seed": seed,
            },
        )


def _openai_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices") if isinstance(payload.get("choices"), list) else []
    if not choices or not isinstance(choices[0], dict):
        return ""
    message = choices[0].get("message") if isinstance(choices[0].get("message"), dict) else {}
    return str(message.get("content") or "").strip()


def _openai_finish_reason(payload: dict[str, Any]):
    choices = payload.get("choices") if isinstance(payload.get("choices"), list) else []
    if choices and isinstance(choices[0], dict):
        return choices[0].get("finish_reason")
    return None
