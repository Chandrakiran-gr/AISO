"""Pure helpers for downstream scan-run kickoff."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import hashlib
import json
from typing import Any
from uuid import UUID


SCAN_EXECUTION_METHODOLOGY_VERSION = (
    "AVS-1.0.0+N-sampling-1.0.0+classifier-1.0.0+"
    "question-bank-1.0.0+pricing-1.0.0+execution-1.0.0+versioning-1.0.0"
)
SAMPLES_PER_CELL = 1  # one query per question per engine (must match api.domain.sampling)
DEFAULT_SCAN_PROVIDERS = ("openai", "claude", "perplexity", "gemini")
VALID_SCAN_PROVIDERS = frozenset(DEFAULT_SCAN_PROVIDERS)
VALID_LATENCY_CLASSES = frozenset({"standard", "priority"})


@dataclass(frozen=True)
class ManifestEntry:
    question_id: str
    bank_version_id: str
    weight_at_scan: Decimal
    state_at_scan: str


@dataclass(frozen=True)
class ScanRunPlan:
    source_scan_id: str
    providers: tuple[str, ...]
    samples_per_cell: int
    question_count: int
    total_calls: int
    manifest_hash: str
    methodology_version: str
    cost_budget_usd: Decimal
    latency_class: str


def validate_idempotency_key(value: str) -> str:
    return _validate_uuid4(value, field_name="Idempotency-Key")


def validate_scan_run_id(value: str) -> str:
    return _validate_uuid4(value, field_name="source_scan_id")


def _validate_uuid4(value: str, *, field_name: str) -> str:
    cleaned = str(value or "").strip()
    try:
        parsed = UUID(cleaned, version=4)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a UUIDv4") from exc
    if str(parsed) != cleaned.lower():
        raise ValueError(f"{field_name} must be a canonical UUIDv4")
    return cleaned


def normalize_providers(providers: list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for provider in providers or DEFAULT_SCAN_PROVIDERS:
        item = str(provider or "").strip().lower()
        if not item or item in seen:
            continue
        if item not in VALID_SCAN_PROVIDERS:
            raise ValueError(f"Unsupported provider: {provider}")
        cleaned.append(item)
        seen.add(item)
    if not cleaned:
        raise ValueError("At least one provider is required")
    return tuple(cleaned)


def normalize_latency_class(latency_class: str | None) -> str:
    cleaned = str(latency_class or "standard").strip().lower()
    if cleaned not in VALID_LATENCY_CLASSES:
        raise ValueError(f"Unsupported latency_class: {latency_class}")
    return cleaned


def build_scan_run_plan(
    *,
    source_scan_id: str,
    providers: tuple[str, ...],
    manifest_entries: list[ManifestEntry],
    cost_budget_usd: Decimal,
    latency_class: str,
) -> ScanRunPlan:
    if not manifest_entries:
        raise ValueError("scan_manifest is required before creating a downstream scan run")
    total_calls = len(manifest_entries) * len(providers) * SAMPLES_PER_CELL
    return ScanRunPlan(
        source_scan_id=source_scan_id,
        providers=providers,
        samples_per_cell=SAMPLES_PER_CELL,
        question_count=len(manifest_entries),
        total_calls=total_calls,
        manifest_hash=scan_manifest_hash(manifest_entries),
        methodology_version=SCAN_EXECUTION_METHODOLOGY_VERSION,
        cost_budget_usd=cost_budget_usd,
        latency_class=latency_class,
    )


def request_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def scan_manifest_hash(entries: list[ManifestEntry]) -> str:
    canonical_entries = [
        {
            "question_id": entry.question_id,
            "bank_version_id": entry.bank_version_id,
            "weight_at_scan": str(entry.weight_at_scan),
            "state_at_scan": entry.state_at_scan,
        }
        for entry in sorted(entries, key=lambda item: item.question_id)
    ]
    return request_hash({"scan_manifest": canonical_entries})
