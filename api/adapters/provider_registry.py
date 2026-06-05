"""Provider registry for downstream scan execution."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
import importlib
import time
from typing import Any, Callable

from api.domain.ports import LLMProvider, ProviderResponse


PROVIDER_QUERY_MODULES = {
    "openai": ("webish.providers.openai_provider", "query"),
    "claude": ("webish.providers.claude_provider", "query"),
    "perplexity": ("webish.providers.perplexity_provider", "query"),
    "gemini": ("webish.providers.gemini_provider", "query"),
}


class WebishProviderAdapter(LLMProvider):
    """Wrap provider API modules behind the Phase 13 LLMProvider port."""

    def __init__(self, *, provider_name: str, query: Callable[[str], Any]) -> None:
        self.provider_name = provider_name
        self.query = query

    async def complete(
        self,
        *,
        prompt: str,
        seed: int | None,
        temperature: float,
        top_p: float,
        idempotency_key: str,
    ) -> ProviderResponse:
        started = time.monotonic()
        result = await asyncio.to_thread(self.query, prompt)
        latency_ms = int((time.monotonic() - started) * 1000)
        error = str(getattr(result, "error", "") or "").strip()
        if error:
            raise RuntimeError(error)

        usage = _safe_call(result, "safe_usage_metadata")
        raw_metadata = _safe_call(result, "safe_raw_metadata")
        return ProviderResponse(
            text=str(getattr(result, "response", "") or ""),
            provider=str(getattr(result, "provider", None) or self.provider_name),
            model=str(getattr(result, "model", None) or "unknown"),
            cost_usd=0.0,
            raw_metadata={
                "provider_metadata": raw_metadata,
                "usage_metadata": usage,
                # Structured citation/source URLs are first-class evidence for the
                # Phase 13 dashboard projection (citation-rate, source intelligence).
                # Forward them so extraction is provider-agnostic and not dependent
                # on deep-parsing each provider's raw dump.
                "citations": _to_dict_list(getattr(result, "citations", None)),
                "search_results": _to_dict_list(getattr(result, "search_results", None)),
                "web_search_used": getattr(result, "web_search_used", None),
                "search_queries": list(getattr(result, "search_queries", []) or []),
                "sampling": {
                    "seed": seed,
                    "temperature": temperature,
                    "top_p": top_p,
                    "idempotency_key": idempotency_key,
                },
            },
            input_tokens=_token_value(usage, "input_tokens", "prompt_tokens"),
            output_tokens=_token_value(usage, "output_tokens", "completion_tokens"),
            total_tokens=_token_value(usage, "total_tokens"),
            latency_ms=latency_ms,
            response_received_at=datetime.now(timezone.utc),
        )


def default_provider_clients() -> dict[str, LLMProvider]:
    return {
        provider: WebishProviderAdapter(provider_name=provider, query=_load_query(module_name, function_name))
        for provider, (module_name, function_name) in PROVIDER_QUERY_MODULES.items()
    }


def _load_query(module_name: str, function_name: str) -> Callable[[str], Any]:
    module = importlib.import_module(module_name)
    query = getattr(module, function_name)
    if not callable(query):
        raise RuntimeError(f"Provider query is not callable: {module_name}.{function_name}")
    return query


def _to_dict_list(items: Any) -> list[dict[str, Any]]:
    """Serialize a list of citation/search-result dataclasses to plain dicts."""
    if not items:
        return []
    out: list[dict[str, Any]] = []
    for item in items:
        to_dict = getattr(item, "to_dict", None)
        if callable(to_dict):
            value = to_dict()
            if isinstance(value, dict):
                out.append(value)
        elif isinstance(item, dict):
            out.append(item)
    return out


def _safe_call(value: Any, method_name: str) -> dict[str, Any]:
    method = getattr(value, method_name, None)
    if not callable(method):
        return {}
    result = method()
    return result if isinstance(result, dict) else {"value": result}


def _token_value(payload: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = payload.get(key)
        if value is None:
            continue
        try:
            return int(Decimal(str(value)))
        except Exception:
            continue
    return None
