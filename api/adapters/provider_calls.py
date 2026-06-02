"""SQLAlchemy adapter for executing planned provider samples."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import os
from typing import Any, Mapping

from sqlalchemy import or_
from sqlalchemy.orm import Session

from api import storage
from api.adapters.audit_log import write_audit_event
from api.adapters.execution_state import record_step_once, safe_error, scan_step
from api.adapters.prompt_registry import ensure_prompt_version
from api.database import (
    CostLedgerEntry,
    ExecutionSample,
    QuestionBankQuestion,
    ScanProgress,
    ScanRun,
)
from api.domain.ports import LLMProvider, ProviderResponse
from api.domain.provider_calls import (
    PROVIDER_MEASUREMENT_PROMPT_KEY,
    PROVIDER_MEASUREMENT_PROMPT_VERSION,
    PROVIDER_SYSTEM_INSTRUCTION,
    RAW_RESPONSE_INLINE_LIMIT_BYTES,
    build_provider_prompt,
    hash_payload,
    hash_text,
    provider_request_payload,
    response_received_at,
)


class ProviderCallExecutionError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 409):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class ProviderCallExecutionResult:
    scan_run_id: str
    planned_count: int
    executed_count: int
    failed_count: int
    skipped_count: int
    completed_calls: int
    failed_calls: int
    stage: str
    already_recorded: bool = False
    budget_exhausted: bool = False


async def execute_provider_samples(
    db: Session,
    *,
    scan_run_id: str,
    provider_clients: Mapping[str, LLMProvider],
    actor_id: str,
    limit: int | None = None,
) -> ProviderCallExecutionResult:
    run = db.query(ScanRun).filter(ScanRun.id == scan_run_id).first()
    if not run:
        raise ProviderCallExecutionError("Scan run not found", status_code=404)

    progress = db.query(ScanProgress).filter(ScanProgress.scan_run_id == scan_run_id).first()
    if not progress:
        raise ProviderCallExecutionError("Scan progress not found", status_code=409)

    planned_samples = _planned_samples(db, scan_run_id=run.id)
    if not planned_samples:
        raise ProviderCallExecutionError("Sample plan must be prepared before provider execution", status_code=409)

    prompt_version = ensure_prompt_version(
        db,
        prompt_key=PROVIDER_MEASUREMENT_PROMPT_KEY,
        version=PROVIDER_MEASUREMENT_PROMPT_VERSION,
        prompt_text=PROVIDER_SYSTEM_INSTRUCTION,
        provider="aiso",
        model="measured-provider",
    )

    if scan_step(db, scan_run_id=run.id, step_id="provider_calls", event="succeeded"):
        counts = _refresh_progress(db, run=run, progress=progress)
        return ProviderCallExecutionResult(
            scan_run_id=run.id,
            planned_count=len(planned_samples),
            executed_count=0,
            failed_count=0,
            skipped_count=len(planned_samples),
            completed_calls=counts["completed_calls"],
            failed_calls=counts["failed_calls"],
            stage=progress.stage,
            already_recorded=True,
        )

    question_texts = _question_texts(db, client_id=run.client_id, samples=planned_samples)
    pending = [sample for sample in planned_samples if not _is_terminal(sample)]
    if limit is not None:
        pending = pending[: max(0, limit)]

    executed_count = 0
    failed_count = 0
    budget_exhausted = False
    for sample in pending:
        request_hash = _request_hash(
            run,
            sample,
            question_texts[sample.question_id],
            prompt_version=prompt_version.version,
            prompt_hash=prompt_version.prompt_hash,
        )
        if _budget_exhausted(run):
            _persist_provider_failure(
                sample,
                request_payload_hash=request_hash,
                reason="cost_budget_exhausted",
            )
            failed_count += 1
            budget_exhausted = True
            continue

        provider = provider_clients.get(sample.provider)
        if provider is None:
            _persist_provider_failure(
                sample,
                request_payload_hash=request_hash,
                reason=f"Provider adapter is not configured: {sample.provider}",
            )
            failed_count += 1
            continue

        try:
            response = await provider.complete(
                prompt=build_provider_prompt(
                    question_text=question_texts[sample.question_id],
                    cache_bust=sample.cache_bust or {},
                ),
                seed=sample.seed,
                temperature=float(sample.temperature),
                top_p=float(sample.top_p),
                idempotency_key=sample.provider_idem_key,
            )
        except Exception as exc:
            _persist_provider_failure(
                sample,
                request_payload_hash=request_hash,
                reason=safe_error(exc),
            )
            failed_count += 1
            continue

        _persist_provider_success(run, sample, response=response, request_payload_hash=request_hash)
        _record_cost(db, run=run, provider=sample.provider, usd=Decimal(str(response.cost_usd or 0)))
        if _budget_exhausted(run):
            budget_exhausted = True
        executed_count += 1

    counts = _refresh_progress(db, run=run, progress=progress)
    terminal_count = counts["completed_calls"] + counts["failed_calls"]
    skipped_count = len(planned_samples) - len(pending)

    if terminal_count == len(planned_samples):
        recorded = record_step_once(
            db,
            scan_run_id=run.id,
            step_id="provider_calls",
            event="succeeded",
            payload={
                "planned_count": len(planned_samples),
                "completed_calls": counts["completed_calls"],
                "failed_calls": counts["failed_calls"],
                "cost_spent_usd": str(run.cost_spent_usd),
                "budget_exhausted": budget_exhausted,
            },
        )
        if recorded:
            _write_provider_call_audit(
                db,
                actor_id=actor_id,
                action="scan_run.provider_calls_completed",
                resource_id=run.id,
                after_state={
                    "scan_run_id": run.id,
                    "planned_count": len(planned_samples),
                    "completed_calls": counts["completed_calls"],
                    "failed_calls": counts["failed_calls"],
                    "stage": progress.stage,
                    "cost_spent_usd": str(run.cost_spent_usd),
                    "budget_exhausted": budget_exhausted,
                },
                reason="Executed all planned provider samples",
                correlation_id=run.idempotency_key,
            )

    db.flush()
    return ProviderCallExecutionResult(
        scan_run_id=run.id,
        planned_count=len(planned_samples),
        executed_count=executed_count,
        failed_count=failed_count,
        skipped_count=skipped_count,
        completed_calls=counts["completed_calls"],
        failed_calls=counts["failed_calls"],
        stage=progress.stage,
        budget_exhausted=budget_exhausted,
    )


def _planned_samples(db: Session, *, scan_run_id: str) -> list[ExecutionSample]:
    return (
        db.query(ExecutionSample)
        .filter(ExecutionSample.scan_run_id == scan_run_id)
        .order_by(
            ExecutionSample.question_id.asc(),
            ExecutionSample.provider.asc(),
            ExecutionSample.sample_index.asc(),
        )
        .all()
    )


def _question_texts(db: Session, *, client_id: str, samples: list[ExecutionSample]) -> dict[str, str]:
    question_ids = sorted({sample.question_id for sample in samples})
    rows = (
        db.query(QuestionBankQuestion)
        .filter(QuestionBankQuestion.client_id == client_id, QuestionBankQuestion.question_id.in_(question_ids))
        .all()
    )
    texts = {row.question_id: row.text for row in rows}
    missing = [question_id for question_id in question_ids if question_id not in texts]
    if missing:
        raise ProviderCallExecutionError(
            f"Question text missing for sample plan: {', '.join(missing[:5])}",
            status_code=409,
        )
    return texts


def _is_terminal(sample: ExecutionSample) -> bool:
    return bool(sample.raw_response_hash or sample.failure_reason)


def _request_hash(
    run: ScanRun,
    sample: ExecutionSample,
    question_text: str,
    *,
    prompt_version: str,
    prompt_hash: str,
) -> bytes:
    prompt = build_provider_prompt(question_text=question_text, cache_bust=sample.cache_bust or {})
    payload = provider_request_payload(
        scan_id=run.id,
        question_id=sample.question_id,
        provider=sample.provider,
        planned_provider_model=sample.planned_provider_model,
        prompt=prompt,
        seed=sample.seed,
        temperature=sample.temperature,
        top_p=sample.top_p,
        idempotency_key=sample.provider_idem_key,
        methodology_version=sample.methodology_version or run.methodology_version,
        cache_bust=sample.cache_bust or {},
        prompt_version=prompt_version,
        prompt_hash=prompt_hash,
    )
    return hash_payload(payload)


def _persist_provider_success(
    run: ScanRun,
    sample: ExecutionSample,
    *,
    response: ProviderResponse,
    request_payload_hash: bytes,
) -> None:
    now = _utcnow()
    text = response.text or ""
    sample.request_payload_hash = request_payload_hash
    _persist_raw_response_text(run, sample, text)
    sample.raw_response_hash = response.raw_response_hash or hash_text(text)
    sample.raw_response = _raw_response_payload(response)
    sample.provider_model = response.model
    sample.system_fingerprint = response.system_fingerprint
    sample.input_tokens = response.input_tokens
    sample.output_tokens = response.output_tokens
    sample.total_tokens = response.total_tokens
    sample.response_received_at = response_received_at(response.response_received_at, fallback=now)
    sample.latency_ms = response.latency_ms
    sample.cost_usd = _money6(Decimal(str(response.cost_usd or 0)))
    sample.failure_reason = None


def _persist_provider_failure(
    sample: ExecutionSample,
    *,
    request_payload_hash: bytes,
    reason: str,
) -> None:
    sample.request_payload_hash = request_payload_hash
    sample.raw_response = None
    sample.raw_response_text = None
    sample.raw_response_pointer = None
    sample.raw_response_hash = None
    sample.provider_model = None
    sample.cost_usd = Decimal("0")
    sample.failure_reason = reason[:500]


def _persist_raw_response_text(run: ScanRun, sample: ExecutionSample, text: str) -> None:
    if len(text.encode("utf-8")) <= RAW_RESPONSE_INLINE_LIMIT_BYTES:
        sample.raw_response_text = text
        sample.raw_response_pointer = None
        return

    filename = f"{sample.question_id}_{sample.provider}_{sample.sample_index}.txt"
    path = storage.build_scan_artifact_path(run.client_id, run.id, filename, stage="raw_responses")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    sample.raw_response_text = None
    sample.raw_response_pointer = storage.repo_relative_path(path)


def _raw_response_payload(response: ProviderResponse) -> dict[str, Any]:
    return {
        "provider": response.provider,
        "model": response.model,
        "usage": {
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
            "total_tokens": response.total_tokens,
        },
        "metadata": _sanitize_metadata(response.raw_metadata),
    }


def _sanitize_metadata(value: Any) -> Any:
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            lowered = key_text.lower()
            if any(marker in lowered for marker in ("api_key", "authorization", "cookie", "password", "secret", "token")):
                clean[key_text] = "[redacted]"
            else:
                clean[key_text] = _sanitize_metadata(item)
        return clean
    if isinstance(value, list):
        return [_sanitize_metadata(item) for item in value[:50]]
    if isinstance(value, tuple):
        return [_sanitize_metadata(item) for item in value[:50]]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _record_cost(db: Session, *, run: ScanRun, provider: str, usd: Decimal) -> None:
    cost = _money6(usd)
    if cost <= 0:
        return
    ledger = (
        db.query(CostLedgerEntry)
        .filter(CostLedgerEntry.scan_run_id == run.id, CostLedgerEntry.provider == provider)
        .first()
    )
    if not ledger:
        ledger = CostLedgerEntry(scan_run_id=run.id, provider=provider, spent_usd=Decimal("0"))
        db.add(ledger)
    ledger.spent_usd = _money6(Decimal(ledger.spent_usd or 0) + cost)
    run.cost_spent_usd = _money4(Decimal(run.cost_spent_usd or 0) + cost)


def _budget_exhausted(run: ScanRun) -> bool:
    return Decimal(run.cost_spent_usd or 0) >= Decimal(run.cost_budget_usd or 0)


def _refresh_progress(db: Session, *, run: ScanRun, progress: ScanProgress) -> dict[str, int]:
    terminal_filter = or_(
        ExecutionSample.raw_response_hash.is_not(None),
        ExecutionSample.failure_reason.is_not(None),
    )
    completed_calls = (
        db.query(ExecutionSample)
        .filter(
            ExecutionSample.scan_run_id == run.id,
            ExecutionSample.raw_response_hash.is_not(None),
            ExecutionSample.failure_reason.is_(None),
        )
        .count()
    )
    failed_calls = (
        db.query(ExecutionSample)
        .filter(ExecutionSample.scan_run_id == run.id, ExecutionSample.failure_reason.is_not(None))
        .count()
    )
    terminal_calls = db.query(ExecutionSample).filter(ExecutionSample.scan_run_id == run.id, terminal_filter).count()

    providers = list(run.providers or [])
    per_provider: dict[str, Any] = {}
    for provider in providers:
        completed = (
            db.query(ExecutionSample)
            .filter(
                ExecutionSample.scan_run_id == run.id,
                ExecutionSample.provider == provider,
                ExecutionSample.raw_response_hash.is_not(None),
                ExecutionSample.failure_reason.is_(None),
            )
            .count()
        )
        failed = (
            db.query(ExecutionSample)
            .filter(
                ExecutionSample.scan_run_id == run.id,
                ExecutionSample.provider == provider,
                ExecutionSample.failure_reason.is_not(None),
            )
            .count()
        )
        current = dict((progress.per_provider or {}).get(provider) or {})
        current["completed"] = completed
        current["failed"] = failed
        current["last_status"] = "provider_calls_completed" if completed + failed == current.get("planned", 0) else "provider_calls_running"
        per_provider[provider] = current

    progress.completed_calls = completed_calls
    progress.failed_calls = failed_calls
    progress.per_provider = per_provider
    progress.stage = "provider_calls_completed" if terminal_calls == progress.total_calls else "provider_calls_running"
    if _has_budget_exhaustion(db, scan_run_id=run.id):
        run.status = "partial"
        run.completeness = "partial_degraded"
        progress.status = "partial"
    progress.updated_at = _utcnow()
    return {"completed_calls": completed_calls, "failed_calls": failed_calls}


def _has_budget_exhaustion(db: Session, *, scan_run_id: str) -> bool:
    return (
        db.query(ExecutionSample)
        .filter(
            ExecutionSample.scan_run_id == scan_run_id,
            ExecutionSample.failure_reason == "cost_budget_exhausted",
        )
        .first()
        is not None
    )


def _write_provider_call_audit(
    db: Session,
    *,
    actor_id: str,
    action: str,
    resource_id: str,
    after_state: dict[str, Any],
    reason: str,
    correlation_id: str,
) -> None:
    write_audit_event(
        db,
        actor_type="system" if actor_id == "system" else "user",
        actor_id=actor_id,
        action=action,
        resource_type="scan_run",
        resource_id=resource_id,
        after_state=after_state,
        reason=reason,
        correlation_id=correlation_id,
        hmac_key=_audit_hmac_key(),
        hmac_key_version=_audit_hmac_key_version(),
    )


def _audit_hmac_key() -> bytes:
    value = os.getenv("AISO_AUDIT_HMAC_KEY")
    if value:
        return value.encode("utf-8")
    if os.getenv("ENV") == "production":
        raise ProviderCallExecutionError("Audit HMAC key is not configured", status_code=500)
    return b"aiso-local-dev-audit-key"


def _audit_hmac_key_version() -> int:
    return int(os.getenv("AISO_AUDIT_HMAC_KEY_VERSION", "1"))


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _money4(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.0001"))


def _money6(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.000001"))
