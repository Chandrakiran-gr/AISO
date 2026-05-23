"""Scan executor adapters for Phase 12 enqueue seams."""

from __future__ import annotations

from api.domain.ports import ScanEnqueueResult


class StubScanExecutor:
    """Phase 12 enqueue seam for the deferred scan-execution implementation."""

    provider = "procrastinate_stub"

    def enqueue(self, *, scan_id: str, client_id: str) -> ScanEnqueueResult:
        return ScanEnqueueResult(
            enqueued=True,
            provider=self.provider,
            job_id=f"phase12-scan:{client_id}:{scan_id}",
        )


def default_scan_executor() -> StubScanExecutor:
    return StubScanExecutor()
