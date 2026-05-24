"""Domain ports and framework-neutral data contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, AsyncIterator, Literal, Protocol
from uuid import UUID


@dataclass(frozen=True)
class BusinessProfileSnapshot:
    client_id: str
    vertical: str
    objective: str
    category: str = ""
    icp: dict[str, Any] = field(default_factory=dict)
    geographic_scope: dict[str, Any] = field(default_factory=dict)
    competitors: list[str] = field(default_factory=list)
    personas: dict[str, Any] = field(default_factory=dict)
    crawl_artifacts: dict[str, Any] = field(default_factory=dict)
    floor_met: bool = False
    onboarding_completed_at: datetime | None = None
    founder_reviewed_at: datetime | None = None


class BusinessProfileStore(Protocol):
    def get_profile(self, client_id: str) -> BusinessProfileSnapshot | None: ...


@dataclass(frozen=True)
class UpstreamProviderResponse:
    """Synchronous Phase 12 provider response kept for upstream prompt flows."""

    text: str
    provider: str
    model: str
    raw_metadata: dict[str, Any] = field(default_factory=dict)


class UpstreamLLMProvider(Protocol):
    """Synchronous Phase 12 LLM seam kept for the completed upstream pipeline."""

    def complete(
        self,
        *,
        prompt: str,
        seed: int,
        temperature: float,
        idempotency_key: str,
    ) -> UpstreamProviderResponse: ...


@dataclass(frozen=True)
class ScanEnqueueResult:
    enqueued: bool
    provider: str
    job_id: str | None = None
    error: str | None = None


class UpstreamScanExecutor(Protocol):
    """Synchronous Phase 12 scan enqueue seam kept until the new engine replaces it."""

    def enqueue(self, *, scan_id: str, client_id: str) -> ScanEnqueueResult: ...


ScanStatus = Literal["queued", "running", "succeeded", "partial", "failed", "cancelled"]


@dataclass(frozen=True)
class ScanHandle:
    scan_run_id: UUID
    idempotency_key: str
    enqueued_at: datetime
    methodology_version: str


@dataclass(frozen=True)
class ProviderProgress:
    provider: str
    completed: int
    failed: int
    rate_limited: int
    last_status: str


@dataclass(frozen=True)
class ScanProgress:
    status: ScanStatus
    total_calls: int
    completed_calls: int
    failed_calls: int
    per_provider: dict[str, ProviderProgress]
    eta_seconds: int | None
    cost_spent_usd: float
    cost_budget_usd: float


@dataclass(frozen=True)
class ProviderResponse:
    """Downstream provider-call result with first-class provenance fields."""

    text: str
    provider: str
    model: str
    raw_metadata: dict[str, Any] = field(default_factory=dict)
    system_fingerprint: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    latency_ms: int | None = None
    request_payload_hash: bytes | None = None
    raw_response_hash: bytes | None = None
    response_received_at: datetime | None = None


class ScanExecutor(Protocol):
    async def enqueue(
        self,
        *,
        scan_run_id: UUID,
        idempotency_key: str,
        client_id: UUID,
        methodology_version: str,
        cost_budget_usd: float,
        priority: int = 0,
    ) -> ScanHandle: ...

    async def status(self, scan_run_id: UUID) -> ScanProgress: ...

    async def cancel(self, scan_run_id: UUID, reason: str) -> None: ...


class ProgressReporter(Protocol):
    async def report(self, scan_run_id: UUID, progress: ScanProgress) -> None: ...

    async def subscribe(self, scan_run_id: UUID) -> AsyncIterator[ScanProgress]: ...


class LLMProvider(Protocol):
    async def complete(
        self,
        *,
        prompt: str,
        seed: int,
        temperature: float,
        idempotency_key: str,
    ) -> ProviderResponse: ...


class CostLedger(Protocol):
    async def record(self, scan_run_id: UUID, provider: str, usd: float) -> float: ...

    async def remaining(self, scan_run_id: UUID) -> float: ...
