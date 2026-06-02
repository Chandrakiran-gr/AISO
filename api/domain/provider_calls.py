"""Pure provider-call helpers for downstream scan execution."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import hashlib
import json
from typing import Any


RAW_RESPONSE_INLINE_LIMIT_BYTES = 64 * 1024
PROVIDER_MEASUREMENT_PROMPT_KEY = "scan_provider_measurement"
PROVIDER_MEASUREMENT_PROMPT_VERSION = "provider-call-1.0.0"


PROVIDER_SYSTEM_INSTRUCTION = (
    "You are answering a real buyer's question for an AI search visibility measurement. "
    "Answer naturally and use current public information when available. "
    "Do not mention AISO, scans, evaluation, or this measurement process."
)


def build_provider_prompt(*, question_text: str, cache_bust: dict[str, str]) -> str:
    """Build the exact prompt sent to measured providers, including cache-bust entropy."""

    return "\n\n".join(
        [
            f"System: {PROVIDER_SYSTEM_INSTRUCTION}",
            f"Cache-bust metadata: {_canonical_json_text(cache_bust)}",
            f"User question: {question_text.strip()}",
        ]
    )


def provider_request_payload(
    *,
    scan_id: str,
    question_id: str,
    provider: str,
    planned_provider_model: str,
    prompt: str,
    seed: int | None,
    temperature: Decimal,
    top_p: Decimal,
    idempotency_key: str,
    methodology_version: str,
    cache_bust: dict[str, str],
    prompt_version: str,
    prompt_hash: str,
) -> dict[str, Any]:
    return {
        "scan_id": scan_id,
        "question_id": question_id,
        "provider": provider,
        "planned_provider_model": planned_provider_model,
        "prompt": prompt,
        "seed": seed,
        "temperature": str(temperature),
        "top_p": str(top_p),
        "idempotency_key": idempotency_key,
        "methodology_version": methodology_version,
        "cache_bust": cache_bust,
        "prompt_version": prompt_version,
        "prompt_hash": prompt_hash,
    }


def hash_payload(payload: dict[str, Any]) -> bytes:
    return hashlib.sha256(_canonical_json(payload)).digest()


def hash_text(value: str) -> bytes:
    return hashlib.sha256(value.encode("utf-8")).digest()


def response_received_at(value: datetime | None, *, fallback: datetime) -> datetime:
    return value or fallback


def _canonical_json(payload: dict[str, Any]) -> bytes:
    return _canonical_json_text(payload).encode("utf-8")


def _canonical_json_text(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
