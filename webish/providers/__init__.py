"""
Provider registry for the AISO multi-provider collect pipeline.

Usage:
    from webish.providers import get_active_providers, PROVIDER_CONCURRENCY

    providers = get_active_providers()
    # → {"openai": <fn>, "claude": <fn>, ...}  only those with API keys set

Providers are returned in PROVIDER_ORDER (consistent column ordering in CSV output).
"""
import os
from typing import Callable

from webish.providers.base import ProviderResult

# Canonical display names used in CSV column headers and progress output
PROVIDER_ORDER = ["openai", "claude", "perplexity", "gemini"]

# Environment variable each provider requires
PROVIDER_ENV_KEYS: dict[str, str] = {
    "openai":     "OPENAI_API_KEY",
    "claude":     "ANTHROPIC_API_KEY",
    "perplexity": "PERPLEXITY_API_KEY",
    "gemini":     "GOOGLE_AI_API_KEY",
}

# Max simultaneous API calls per provider (tune to each provider's rate limits)
DEFAULT_PROVIDER_CONCURRENCY: dict[str, int] = {
    "openai":     5,
    "claude":     5,  # ↑ from 3: more parallel calls offset per-call latency
    "perplexity": 3,
    "gemini":     2,
}


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name, "").strip()
    if not value:
        return default
    try:
        parsed = int(value)
    except ValueError:
        print(f"{name} must be an integer; using {default}.")
        return default
    return max(1, parsed)


PROVIDER_CONCURRENCY: dict[str, int] = {
    name: _env_int(f"AISO_{name.upper()}_CONCURRENCY", default)
    for name, default in DEFAULT_PROVIDER_CONCURRENCY.items()
}


def get_active_providers() -> dict[str, Callable[[str], ProviderResult]]:
    """
    Return an ordered dict of {provider_name: query_fn} for every provider
    whose API key is present and non-empty in the environment.

    Providers are returned in PROVIDER_ORDER for consistent CSV column ordering.
    """
    from webish.providers import (
        openai_provider,
        claude_provider,
        perplexity_provider,
        gemini_provider,
    )

    registry: dict[str, Callable[[str], ProviderResult]] = {
        "openai":     openai_provider.query,
        "claude":     claude_provider.query,
        "perplexity": perplexity_provider.query,
        "gemini":     gemini_provider.query,
    }

    return {
        name: registry[name]
        for name in PROVIDER_ORDER
        if os.environ.get(PROVIDER_ENV_KEYS[name], "").strip()
    }


def list_provider_status() -> list[tuple[str, bool, str]]:
    """
    Return a status list: [(provider_name, is_active, env_var_name), ...]
    Useful for startup diagnostics.
    """
    return [
        (
            name,
            bool(os.environ.get(PROVIDER_ENV_KEYS[name], "").strip()),
            PROVIDER_ENV_KEYS[name],
        )
        for name in PROVIDER_ORDER
    ]


def get_active_providers_multiturn() -> dict[str, Callable]:
    """
    Return an ordered dict of {provider_name: query_with_followup_fn}
    for every provider whose API key is present.

    Each function has the signature:
        (question: str, followup: str) -> tuple[ProviderResult, ProviderResult]
    """
    from webish.providers import (
        openai_provider,
        claude_provider,
        perplexity_provider,
        gemini_provider,
    )

    registry: dict[str, Callable] = {
        "openai":     openai_provider.query_with_followup,
        "claude":     claude_provider.query_with_followup,
        "perplexity": perplexity_provider.query_with_followup,
        "gemini":     gemini_provider.query_with_followup,
    }

    return {
        name: registry[name]
        for name in PROVIDER_ORDER
        if os.environ.get(PROVIDER_ENV_KEYS[name], "").strip()
    }
