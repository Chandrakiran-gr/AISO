"""OpenRouter (OpenAI-compatible) chat adapter for managed onboarding LLM steps.

Onboarding *generation* - business description, competitors, and the review
question prompts - runs through OpenRouter free/open models (DeepSeek, Qwen,
Llama) instead of a paid first-party API key. This is a deliberate cost choice:
the output is text the user confirms before anything runs, so an open model is
more than adequate.

The downstream SCAN engine is untouched. It still queries the real answer
engines (ChatGPT, Claude, Perplexity, Gemini) - swapping those would change what
we measure. This adapter is for onboarding generation only.

Configuration (all env, never BYOK):
  OPENROUTER_API_KEY            - the key (required). ONBOARDING_LLM_API_KEY also honored.
  ONBOARDING_LLM_MODEL          - primary model id (default DeepSeek V3 free).
  ONBOARDING_LLM_FALLBACK_MODELS- comma-separated ids tried on rate-limit/empty.
  ONBOARDING_LLM_BASE_URL       - OpenAI-compatible base (default OpenRouter).
  ONBOARDING_LLM_REFERER        - OpenRouter attribution referer (optional).

The key comes from the process environment, never from user BYOK storage, and is
never returned, logged, or persisted.
"""

from __future__ import annotations

from typing import Any
import logging
import os

import requests

from api.domain.ports import UpstreamProviderResponse

logger = logging.getLogger(__name__)

DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
# Model ids rotate on OpenRouter; these are overridable via env so a retired id
# is a config change, not a code change. Chosen from the live free catalog and
# smoke-tested for clean JSON output + latency (Nemotron-super ~2s, Nemotron-ultra
# ~5s, gpt-oss ~10s), across two vendors so a single-provider throttle still
# leaves a working fallback.
DEFAULT_ONBOARDING_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"
DEFAULT_FALLBACK_MODELS: tuple[str, ...] = (
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "openai/gpt-oss-20b:free",
)
# Statuses worth trying the next model for: throttling, transient upstream
# faults, and model-not-found (a retired/renamed free id, so fall through to the
# next model rather than hard-fail). A 400 is a real request error - do not mask it.
_RETRYABLE_STATUS = {404, 408, 409, 429, 500, 502, 503, 504}
# Free/open models cap completion length well below the paid tiers; an
# over-large max_tokens can 400. Clamp to a safe ceiling (env-overridable).
DEFAULT_MAX_OUTPUT_TOKENS = 8000


def _max_output_cap() -> int:
    raw = os.getenv("ONBOARDING_LLM_MAX_OUTPUT_TOKENS", "").strip()
    if raw.isdigit() and int(raw) > 0:
        return int(raw)
    return DEFAULT_MAX_OUTPUT_TOKENS


def _configured_models() -> list[str]:
    """Ordered, de-duplicated model list: primary first, then fallbacks."""
    primary = os.getenv("ONBOARDING_LLM_MODEL", "").strip() or DEFAULT_ONBOARDING_MODEL
    raw_fallbacks = os.getenv("ONBOARDING_LLM_FALLBACK_MODELS", "").strip()
    fallbacks = (
        [m.strip() for m in raw_fallbacks.split(",") if m.strip()]
        if raw_fallbacks
        else list(DEFAULT_FALLBACK_MODELS)
    )
    ordered: list[str] = []
    for model in [primary, *fallbacks]:
        if model and model not in ordered:
            ordered.append(model)
    return ordered


class OpenRouterChatAdapter:
    """OpenRouter chat-completions adapter implementing ``UpstreamLLMProvider``.

    Reusable across onboarding steps (``purpose``/``max_tokens`` are the only
    per-step differences). On a rate-limit or transient fault it walks the
    configured fallback models before giving up, so a throttled free model never
    dead-ends onboarding.
    """

    provider = "openrouter"

    def __init__(
        self,
        *,
        purpose: str,
        max_tokens: int,
        api_key: str | None = None,
        models: list[str] | None = None,
        base_url: str | None = None,
        timeout_seconds: float = 60.0,
    ):
        self.purpose = purpose
        self.max_tokens = max_tokens
        self.api_key = (
            api_key
            or os.getenv("OPENROUTER_API_KEY")
            or os.getenv("ONBOARDING_LLM_API_KEY")
            or ""
        )
        self.base_url = (
            base_url or os.getenv("ONBOARDING_LLM_BASE_URL") or DEFAULT_OPENROUTER_BASE_URL
        ).rstrip("/")
        self.models = list(models) if models else _configured_models()
        # `.model` advertises the primary; the actual model used is echoed back
        # in the response metadata (a fallback may have served the request).
        self.model = self.models[0] if self.models else DEFAULT_ONBOARDING_MODEL
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
            raise RuntimeError(f"OPENROUTER_API_KEY is required for OpenRouter {self.purpose}")

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            # OpenRouter attribution headers (optional but recommended).
            "HTTP-Referer": os.getenv("ONBOARDING_LLM_REFERER", "https://www.aisoglobal.com"),
            "X-Title": "AISO",
        }
        errors: list[str] = []
        for model in self.models:
            try:
                response = requests.post(
                    url,
                    headers=headers,
                    json={
                        "model": model,
                        "max_tokens": min(self.max_tokens, _max_output_cap()),
                        "temperature": temperature,
                        "seed": seed,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                    timeout=self.timeout_seconds,
                )
            except requests.RequestException as exc:
                errors.append(f"{model}: request error {exc}")
                logger.warning("OpenRouter %s: request error on %s: %s", self.purpose, model, exc)
                continue

            if response.status_code in _RETRYABLE_STATUS:
                errors.append(f"{model}: HTTP {response.status_code}")
                logger.warning(
                    "OpenRouter %s: %s returned HTTP %s, trying next model",
                    self.purpose,
                    model,
                    response.status_code,
                )
                continue

            response.raise_for_status()
            payload = response.json()
            text = _openrouter_text(payload)
            if not text:
                # Free models occasionally return empty content; treat as retryable.
                errors.append(f"{model}: empty completion")
                logger.warning("OpenRouter %s: %s returned empty completion", self.purpose, model)
                continue

            return UpstreamProviderResponse(
                text=text,
                provider="openrouter",
                model=str(payload.get("model") or model),
                raw_metadata={
                    "id": payload.get("id"),
                    "finish_reason": _openrouter_finish_reason(payload),
                    "usage": payload.get("usage"),
                    "seed": seed,
                    "requested_model": model,
                },
            )

        raise RuntimeError(
            f"OpenRouter {self.purpose} failed for all models "
            f"({', '.join(self.models)}): {'; '.join(errors)}"
        )


def _openrouter_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices") if isinstance(payload.get("choices"), list) else []
    if not choices or not isinstance(choices[0], dict):
        return ""
    message = choices[0].get("message") if isinstance(choices[0].get("message"), dict) else {}
    return str(message.get("content") or "").strip()


def _openrouter_finish_reason(payload: dict[str, Any]):
    choices = payload.get("choices") if isinstance(payload.get("choices"), list) else []
    if choices and isinstance(choices[0], dict):
        return choices[0].get("finish_reason")
    return None
