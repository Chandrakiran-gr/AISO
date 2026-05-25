"""Pure N-sampling helpers for scan execution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import hashlib
import json
from typing import Any
from uuid import NAMESPACE_URL, uuid5


SAMPLING_CONFIG_VERSION = "N-sampling-1.0.0"
SAMPLES_PER_CELL = 5
SAMPLING_TEMPERATURE = Decimal("0.700")
SAMPLING_TOP_P = Decimal("1.000")
SEED_MODULUS = 2**31
PROVIDERS_WITHOUT_SEED = frozenset({"claude"})


@dataclass(frozen=True)
class SamplePlanEntry:
    scan_id: str
    question_id: str
    provider: str
    planned_provider_model: str
    provider_model_snapshot_version: str
    sample_index: int
    seed: int | None
    temperature: Decimal
    top_p: Decimal
    provider_idempotency_key: str
    cache_bust: dict[str, str]
    methodology_version: str
    sample_plan_hash: bytes


def deterministic_seed(*, scan_id: str, question_id: str, provider: str, sample_index: int) -> int:
    material = _canonical_json(
        {
            "scan_id": scan_id,
            "question_id": question_id,
            "provider": provider,
            "sample_index": sample_index,
        }
    )
    return int(hashlib.sha256(material).hexdigest(), 16) % SEED_MODULUS


def provider_idempotency_key(*, scan_id: str, question_id: str, provider: str, sample_index: int) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            f"aiso-provider-call:{scan_id}:{question_id}:{provider}:{sample_index}",
        )
    )


def cache_bust_payload(
    *,
    scan_id: str,
    question_id: str,
    provider: str,
    sample_index: int,
    issued_at: datetime,
) -> dict[str, str]:
    return {
        "scan_id": scan_id,
        "ts": issued_at.isoformat(),
        "uuid": str(uuid5(NAMESPACE_URL, f"aiso-cache-bust:{scan_id}:{question_id}:{provider}:{sample_index}")),
    }


def sample_plan_hash(payload: dict[str, Any]) -> bytes:
    return hashlib.sha256(_canonical_json(payload)).digest()


def build_sample_plan(
    *,
    scan_id: str,
    question_ids: list[str],
    providers: list[str],
    provider_models: dict[str, str],
    provider_model_snapshot_version: str,
    issued_at: datetime,
    methodology_version: str,
) -> list[SamplePlanEntry]:
    entries: list[SamplePlanEntry] = []
    for question_id in question_ids:
        for provider in providers:
            planned_provider_model = provider_models[provider]
            for sample_index in range(SAMPLES_PER_CELL):
                # Anthropic/Claude does not expose a seed parameter. Per
                # N-sampling-1.0, preserve the deterministic sample index and
                # idempotency key, but store seed as null for unsupported APIs.
                seed = (
                    None
                    if provider in PROVIDERS_WITHOUT_SEED
                    else deterministic_seed(
                        scan_id=scan_id,
                        question_id=question_id,
                        provider=provider,
                        sample_index=sample_index,
                    )
                )
                cache_bust = cache_bust_payload(
                    scan_id=scan_id,
                    question_id=question_id,
                    provider=provider,
                    sample_index=sample_index,
                    issued_at=issued_at,
                )
                plan_payload = {
                    "scan_id": scan_id,
                    "question_id": question_id,
                    "provider": provider,
                    "planned_provider_model": planned_provider_model,
                    "provider_model_snapshot_version": provider_model_snapshot_version,
                    "sample_index": sample_index,
                    "seed": seed,
                    "temperature": str(SAMPLING_TEMPERATURE),
                    "top_p": str(SAMPLING_TOP_P),
                    "cache_bust": cache_bust,
                    "methodology_version": methodology_version,
                    "sampling_config_version": SAMPLING_CONFIG_VERSION,
                }
                entries.append(
                    SamplePlanEntry(
                        scan_id=scan_id,
                        question_id=question_id,
                        provider=provider,
                        planned_provider_model=planned_provider_model,
                        provider_model_snapshot_version=provider_model_snapshot_version,
                        sample_index=sample_index,
                        seed=seed,
                        temperature=SAMPLING_TEMPERATURE,
                        top_p=SAMPLING_TOP_P,
                        provider_idempotency_key=provider_idempotency_key(
                            scan_id=scan_id,
                            question_id=question_id,
                            provider=provider,
                            sample_index=sample_index,
                        ),
                        cache_bust=cache_bust,
                        methodology_version=methodology_version,
                        sample_plan_hash=sample_plan_hash(plan_payload),
                    )
                )
    return entries


def _canonical_json(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
