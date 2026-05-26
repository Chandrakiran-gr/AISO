"""SQLAlchemy adapter for classifier-1.0 stance and source judgments."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import asyncio
import hashlib
import json
import os
from pathlib import Path
import time
import uuid
from typing import Any

from sqlalchemy.orm import Session

from api import storage
from api.adapters.audit_log import write_audit_event
from api.adapters.execution_state import record_step_once, safe_error, scan_step
from api.adapters.prompt_registry import ensure_prompt_version
from api.database import (
    Classification,
    Client,
    CostLedgerEntry,
    DomainClassification,
    ExecutionSample,
    QuestionBankQuestion,
    Sample,
    ScanProgress,
    ScanRawResponseArchive,
    ScanRun,
)
from api.domain.classifier import (
    CLASSIFIER_VERSION,
    SOURCE_MODEL_NAME,
    SOURCE_PROMPT_KEY,
    SOURCE_PROMPT_VERSION,
    SOURCE_SYSTEM_PROMPT,
    SOURCE_TEMPERATURE,
    STANCE_MODEL_NAME,
    STANCE_PROMPT_KEY,
    STANCE_PROMPT_VERSION,
    STANCE_SELF_CONSISTENCY_N,
    STANCE_SYSTEM_PROMPT,
    STANCE_TEMPERATURE,
    PROMPT_TOP_P,
    SourceDomainJudgment,
    citation_urls,
    consensus_source,
    consensus_stance,
    host_from_url,
    parse_source_class,
    source_judgment_payload,
    source_prompt,
    stance_prompt,
    static_source_class,
)
from api.domain.ports import LLMProvider
from api.domain.ports import ProviderResponse


SOURCE_CACHE_TTL_DAYS = 90
RAW_RESPONSE_ARCHIVE_TYPE = "provider_raw_responses"
CLASSIFIER_COST_PROVIDER = "claude_classifier"
CLASSIFIER_INPUT_USD_PER_MILLION = Decimal("3.00")
CLASSIFIER_OUTPUT_USD_PER_MILLION = Decimal("15.00")
CLASSIFIER_PROMPT_SENTINEL = "AISO_CLASSIFIER_PROMPT_V1:"


class ClassificationExecutionError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 409):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class ClassificationExecutionResult:
    scan_run_id: str
    successful_sample_count: int
    canonical_sample_count: int
    stance_classification_count: int
    source_classification_count: int
    skipped_count: int
    failed_count: int
    stage: str
    already_recorded: bool = False


async def execute_sample_classifications(
    db: Session,
    *,
    scan_run_id: str,
    judge_provider: LLMProvider,
    actor_id: str,
    source_judge_provider: LLMProvider | None = None,
    limit: int | None = None,
) -> ClassificationExecutionResult:
    run = db.query(ScanRun).filter(ScanRun.id == scan_run_id).first()
    if not run:
        raise ClassificationExecutionError("Scan run not found", status_code=404)

    progress = db.query(ScanProgress).filter(ScanProgress.scan_run_id == scan_run_id).first()
    if not progress:
        raise ClassificationExecutionError("Scan progress not found", status_code=409)

    successful_samples = _successful_execution_samples(db, scan_run_id=run.id)
    if not successful_samples:
        raise ClassificationExecutionError("No successful provider samples are available for classification", status_code=409)

    if scan_step(db, scan_run_id=run.id, step_id="classify_samples", event="succeeded"):
        counts = _classification_counts(db, run=run, successful_samples=successful_samples)
        _refresh_progress(db, run=run, progress=progress, successful_sample_count=len(successful_samples))
        return ClassificationExecutionResult(
            scan_run_id=run.id,
            successful_sample_count=len(successful_samples),
            canonical_sample_count=counts["canonical_samples"],
            stance_classification_count=counts["stance"],
            source_classification_count=counts["source"],
            skipped_count=len(successful_samples),
            failed_count=0,
            stage=progress.stage,
            already_recorded=True,
        )

    _ensure_raw_response_archive(db, run=run)
    stance_prompt_version = ensure_prompt_version(
        db,
        prompt_key=STANCE_PROMPT_KEY,
        version=STANCE_PROMPT_VERSION,
        prompt_text=STANCE_SYSTEM_PROMPT,
        provider="anthropic",
        model=STANCE_MODEL_NAME,
    )
    source_prompt_version = ensure_prompt_version(
        db,
        prompt_key=SOURCE_PROMPT_KEY,
        version=SOURCE_PROMPT_VERSION,
        prompt_text=SOURCE_SYSTEM_PROMPT,
        provider="anthropic",
        model=SOURCE_MODEL_NAME,
    )

    source_judge = source_judge_provider or judge_provider
    client = db.query(Client).filter(Client.id == run.client_id).one()
    question_texts = _question_texts(db, client_id=run.client_id, samples=successful_samples)
    target_names = _target_names(client)

    pending = successful_samples[: max(0, limit)] if limit is not None else successful_samples
    failed_count = 0
    skipped_count = 0
    for execution_sample in pending:
        raw_text = _sample_text(execution_sample)
        canonical = _ensure_canonical_sample(db, execution_sample=execution_sample, raw_text=raw_text)

        if _classification_exists(db, sample_id=canonical.id, classifier_type="stance"):
            skipped_count += 1
        else:
            try:
                await _classify_stance(
                    db,
                    run=run,
                    execution_sample=execution_sample,
                    canonical_sample=canonical,
                    question_text=question_texts[execution_sample.question_id],
                    raw_text=raw_text,
                    target_names=target_names,
                    judge_provider=judge_provider,
                    prompt_hash=bytes.fromhex(stance_prompt_version.prompt_hash),
                )
            except Exception as exc:
                failed_count += 1
                _record_classifier_failure(
                    db,
                    run=run,
                    classifier_type="stance",
                    sample_id=canonical.id,
                    exc=exc,
                )

        if _classification_exists(db, sample_id=canonical.id, classifier_type="source"):
            skipped_count += 1
        else:
            try:
                await _classify_source(
                    db,
                    run=run,
                    client=client,
                    execution_sample=execution_sample,
                    canonical_sample=canonical,
                    raw_text=raw_text,
                    source_judge_provider=source_judge,
                    prompt_hash=bytes.fromhex(source_prompt_version.prompt_hash),
                )
            except Exception as exc:
                failed_count += 1
                _record_classifier_failure(
                    db,
                    run=run,
                    classifier_type="source",
                    sample_id=canonical.id,
                    exc=exc,
                )

    counts = _classification_counts(db, run=run, successful_samples=successful_samples)
    _refresh_progress(db, run=run, progress=progress, successful_sample_count=len(successful_samples))
    all_classified = _all_successful_samples_classified(db, run=run, successful_samples=successful_samples)
    if failed_count and not all_classified:
        _mark_classification_failed(
            db,
            run=run,
            progress=progress,
            failed_count=failed_count,
            counts=counts,
            actor_id=actor_id,
        )
        db.flush()
        raise ClassificationExecutionError(
            f"Classifier failed for {failed_count} sample classifier task(s)",
            status_code=503,
        )

    if all_classified:
        recorded = record_step_once(
            db,
            scan_run_id=run.id,
            step_id="classify_samples",
            event="succeeded",
            payload={
                "successful_sample_count": len(successful_samples),
                "canonical_sample_count": counts["canonical_samples"],
                "stance_classification_count": counts["stance"],
                "source_classification_count": counts["source"],
                "classifier_version": CLASSIFIER_VERSION,
                "failed_count": failed_count,
            },
        )
        if recorded:
            _write_classifier_audit(
                db,
                actor_id=actor_id,
                action="scan_run.samples_classified",
                resource_id=run.id,
                after_state={
                    "scan_run_id": run.id,
                    "successful_sample_count": len(successful_samples),
                    "stance_classification_count": counts["stance"],
                    "source_classification_count": counts["source"],
                    "stage": progress.stage,
                    "classifier_version": CLASSIFIER_VERSION,
                },
                reason="Classified successful provider samples with classifier-1.0",
                correlation_id=run.idempotency_key,
            )

    db.flush()
    return ClassificationExecutionResult(
        scan_run_id=run.id,
        successful_sample_count=len(successful_samples),
        canonical_sample_count=counts["canonical_samples"],
        stance_classification_count=counts["stance"],
        source_classification_count=counts["source"],
        skipped_count=skipped_count,
        failed_count=failed_count,
        stage=progress.stage,
    )


def default_classifier_judge() -> LLMProvider:
    return ClaudeClassifierJudge()


class ClaudeClassifierJudge(LLMProvider):
    """Claude Sonnet judge adapter for classifier-1.0 without web search."""

    def __init__(self, *, model: str | None = None, max_tokens: int = 256) -> None:
        self.model = model or os.getenv("AISO_CLASSIFIER_CLAUDE_MODEL", "claude-sonnet-4-20250514")
        self.max_tokens = max_tokens

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
        response = await asyncio.to_thread(
            self._complete_sync,
            prompt=prompt,
            temperature=temperature,
            top_p=top_p,
        )
        latency_ms = int((time.monotonic() - started) * 1000)
        text, usage, raw_metadata = response
        return ProviderResponse(
            text=text,
            provider="claude",
            model=self.model,
            raw_metadata={
                "usage": usage,
                "classifier": {
                    "seed": seed,
                    "temperature": temperature,
                    "top_p": top_p,
                    "idempotency_key": idempotency_key,
                },
                "response": raw_metadata,
            },
            input_tokens=_usage_value(usage, "input_tokens"),
            output_tokens=_usage_value(usage, "output_tokens"),
            total_tokens=_usage_value(usage, "total_tokens"),
            latency_ms=latency_ms,
            response_received_at=_utcnow(),
        )

    def _complete_sync(self, *, prompt: str, temperature: float, top_p: float) -> tuple[str, dict[str, Any], dict[str, Any]]:
        api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set.")
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)
        system, user_prompt = _split_classifier_prompt(prompt)
        system_block: str | list[dict[str, Any]]
        if system:
            system_block = [
                {
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
        else:
            system_block = ""
        message = client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system_block,
            temperature=temperature,
            top_p=top_p,
            messages=[{"role": "user", "content": user_prompt}],
        )
        blocks = getattr(message, "content", []) or []
        text = "\n".join(str(getattr(block, "text", "") or "") for block in blocks).strip()
        raw_metadata = message.model_dump() if hasattr(message, "model_dump") else {}
        usage = raw_metadata.get("usage") if isinstance(raw_metadata.get("usage"), dict) else {}
        return text, usage, raw_metadata if isinstance(raw_metadata, dict) else {}


async def _classify_stance(
    db: Session,
    *,
    run: ScanRun,
    execution_sample: ExecutionSample,
    canonical_sample: Sample,
    question_text: str,
    raw_text: str,
    target_names: list[str],
    judge_provider: LLMProvider,
    prompt_hash: bytes,
) -> None:
    target_name = target_names[0] if target_names else "target business"
    prompt = stance_prompt(target_name=target_name, question_text=question_text, answer_text=raw_text)
    judgments: list[str] = []
    model = STANCE_MODEL_NAME
    for index in range(STANCE_SELF_CONSISTENCY_N):
        _raise_if_budget_exhausted(run)
        response = await judge_provider.complete(
            prompt=_classifier_prompt_payload(system_prompt=STANCE_SYSTEM_PROMPT, user_prompt=prompt),
            seed=_seed_for_classifier(execution_sample.seed, index),
            temperature=STANCE_TEMPERATURE,
            top_p=PROMPT_TOP_P,
            idempotency_key=f"classifier:stance:{canonical_sample.id}:{CLASSIFIER_VERSION}:{index}",
        )
        _record_cost(db, run=run, usd=_classifier_cost(response))
        judgments.append(response.text)
        model = response.model or model

    consensus = consensus_stance(judgments)
    db.add(
        Classification(
            id=str(uuid.uuid4()),
            sample_id=canonical_sample.id,
            classifier_type="stance",
            classifier_version=CLASSIFIER_VERSION,
            classifier_model=model,
            prompt_hash=prompt_hash,
            self_consistency_n=STANCE_SELF_CONSISTENCY_N,
            individual_judgments=consensus.individual_judgments,
            consensus_value=consensus.label,
            consensus_confidence=_decimal_confidence(consensus.confidence),
            judged_at=_utcnow(),
        )
    )
    execution_sample.classified_stance = consensus.label


async def _classify_source(
    db: Session,
    *,
    run: ScanRun,
    client: Client,
    execution_sample: ExecutionSample,
    canonical_sample: Sample,
    raw_text: str,
    source_judge_provider: LLMProvider,
    prompt_hash: bytes,
) -> None:
    judgments: list[SourceDomainJudgment] = []
    raw_metadata = execution_sample.raw_response if isinstance(execution_sample.raw_response, dict) else {}
    for url in citation_urls(raw_text, raw_metadata=raw_metadata):
        host = host_from_url(url)
        if not host:
            continue
        domain = _registered_domain(host)
        judgment = await _classify_domain(
            db,
            run=run,
            client=client,
            domain=domain,
            url=url,
            answer_excerpt=raw_text,
            source_judge_provider=source_judge_provider,
            prompt_hash=prompt_hash,
        )
        judgments.append(judgment)

    consensus = consensus_source(judgments)
    db.add(
        Classification(
            id=str(uuid.uuid4()),
            sample_id=canonical_sample.id,
            classifier_type="source",
            classifier_version=CLASSIFIER_VERSION,
            classifier_model=SOURCE_MODEL_NAME,
            prompt_hash=prompt_hash,
            self_consistency_n=1,
            individual_judgments=source_judgment_payload(consensus.judgments),
            consensus_value=consensus.source_class,
            consensus_confidence=_decimal_confidence(consensus.confidence),
            judged_at=_utcnow(),
        )
    )
    execution_sample.classified_source = consensus.source_class


async def _classify_domain(
    db: Session,
    *,
    run: ScanRun,
    client: Client,
    domain: str,
    url: str,
    answer_excerpt: str,
    source_judge_provider: LLMProvider,
    prompt_hash: bytes,
) -> SourceDomainJudgment:
    if _domain_matches(domain, _client_domains(client.owned_domains) | {_registered_domain(host_from_url(client.url))}):
        return SourceDomainJudgment(domain=domain, source_class="OWNED", source="client_override", confidence=1.0)
    if _domain_matches(domain, _client_domains(client.competitor_domains)):
        return SourceDomainJudgment(domain=domain, source_class="COMPETITOR", source="client_override", confidence=1.0)

    static_class = static_source_class(domain)
    if static_class:
        _upsert_domain_cache(
            db,
            domain=domain,
            source_class=static_class,
            classifier_model="static-seed",
            prompt_hash=None,
            confidence=0.90,
            source="static_seed",
            evidence={"url": url},
            expires_at=None,
        )
        return SourceDomainJudgment(domain=domain, source_class=static_class, source="static_seed", confidence=0.90)

    cached = (
        db.query(DomainClassification)
        .filter(
            DomainClassification.domain == domain,
            DomainClassification.classifier_version == CLASSIFIER_VERSION,
        )
        .first()
    )
    if cached and _domain_cache_fresh(cached):
        return SourceDomainJudgment(
            domain=domain,
            source_class=cached.source_class,
            source="cache",
            confidence=float(cached.confidence or 0),
            prompt_hash=cached.prompt_hash,
            raw_judgment=(cached.evidence or {}).get("raw_judgment") if isinstance(cached.evidence, dict) else None,
        )

    prompt = source_prompt(domain=domain, url=url, answer_excerpt=answer_excerpt)
    _raise_if_budget_exhausted(run)
    response = await source_judge_provider.complete(
        prompt=_classifier_prompt_payload(system_prompt=SOURCE_SYSTEM_PROMPT, user_prompt=prompt),
        seed=None,
        temperature=SOURCE_TEMPERATURE,
        top_p=PROMPT_TOP_P,
        idempotency_key=f"classifier:source:{domain}:{CLASSIFIER_VERSION}",
    )
    _record_cost(db, run=run, usd=_classifier_cost(response))
    source_class = parse_source_class(response.text)
    _upsert_domain_cache(
        db,
        domain=domain,
        source_class=source_class,
        classifier_model=response.model or SOURCE_MODEL_NAME,
        prompt_hash=prompt_hash,
        confidence=0.75 if source_class != "UNKNOWN" else 0.40,
        source="llm_fallback",
        evidence={"url": url, "raw_judgment": response.text},
        expires_at=_utcnow() + timedelta(days=SOURCE_CACHE_TTL_DAYS),
    )
    return SourceDomainJudgment(
        domain=domain,
        source_class=source_class,
        source="llm_fallback",
        confidence=0.75 if source_class != "UNKNOWN" else 0.40,
        prompt_hash=prompt_hash,
        raw_judgment=response.text,
    )


def _ensure_raw_response_archive(db: Session, *, run: ScanRun) -> ScanRawResponseArchive:
    existing = (
        db.query(ScanRawResponseArchive)
        .filter(
            ScanRawResponseArchive.scan_id == run.id,
            ScanRawResponseArchive.archive_type == RAW_RESPONSE_ARCHIVE_TYPE,
        )
        .first()
    )
    if existing:
        return existing

    successful_samples = _successful_execution_samples(db, scan_run_id=run.id)
    archive_payload = _raw_response_archive_payload(successful_samples)
    archive_bytes = json.dumps(archive_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    archive_hash = hashlib.sha256(archive_bytes).digest()
    archive_path = storage.build_scan_artifact_path(
        run.client_id,
        run.id,
        "raw_response_archive.json",
        stage="raw_responses",
    )
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    archive_path.write_bytes(archive_bytes)

    row = ScanRawResponseArchive(
        id=str(uuid.uuid4()),
        scan_id=run.id,
        archive_type=RAW_RESPONSE_ARCHIVE_TYPE,
        sample_count=len(successful_samples),
        archive_url=storage.repo_relative_path(archive_path),
        archive_hash=archive_hash,
        created_at=_utcnow(),
    )
    db.add(row)
    db.flush()
    return row


def _ensure_canonical_sample(db: Session, *, execution_sample: ExecutionSample, raw_text: str) -> Sample:
    sample_id = _canonical_sample_id(execution_sample)
    existing = db.query(Sample).filter(Sample.id == sample_id).first()
    if existing:
        return existing
    row = Sample(
        id=sample_id,
        scan_id=execution_sample.scan_run_id,
        question_id=execution_sample.question_id,
        provider=execution_sample.provider,
        provider_model=execution_sample.provider_model or execution_sample.planned_provider_model,
        system_fingerprint=execution_sample.system_fingerprint,
        temperature=execution_sample.temperature,
        top_p=execution_sample.top_p,
        seed=execution_sample.seed,
        sample_index=execution_sample.sample_index,
        request_payload_hash=execution_sample.request_payload_hash or b"",
        raw_response_text=raw_text,
        raw_response_pointer=execution_sample.raw_response_pointer,
        raw_response_hash=execution_sample.raw_response_hash or hashlib.sha256(raw_text.encode("utf-8")).digest(),
        response_received_at=execution_sample.response_received_at or _utcnow(),
        latency_ms=execution_sample.latency_ms,
        input_tokens=execution_sample.input_tokens,
        output_tokens=execution_sample.output_tokens,
        total_tokens=execution_sample.total_tokens,
        methodology_version=execution_sample.methodology_version or "",
    )
    db.add(row)
    db.flush()
    return row


def _successful_execution_samples(db: Session, *, scan_run_id: str) -> list[ExecutionSample]:
    return (
        db.query(ExecutionSample)
        .filter(
            ExecutionSample.scan_run_id == scan_run_id,
            ExecutionSample.raw_response_hash.is_not(None),
            ExecutionSample.failure_reason.is_(None),
        )
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
        raise ClassificationExecutionError(
            f"Question text missing for classification: {', '.join(missing[:5])}",
            status_code=409,
        )
    return texts


def _classification_exists(db: Session, *, sample_id: str, classifier_type: str) -> bool:
    return (
        db.query(Classification)
        .filter(
            Classification.sample_id == sample_id,
            Classification.classifier_type == classifier_type,
            Classification.classifier_version == CLASSIFIER_VERSION,
        )
        .first()
        is not None
    )


def _all_successful_samples_classified(db: Session, *, run: ScanRun, successful_samples: list[ExecutionSample]) -> bool:
    sample_ids = [_canonical_sample_id(sample) for sample in successful_samples]
    if not sample_ids:
        return False
    stance_count = (
        db.query(Classification)
        .filter(
            Classification.sample_id.in_(sample_ids),
            Classification.classifier_type == "stance",
            Classification.classifier_version == CLASSIFIER_VERSION,
        )
        .count()
    )
    source_count = (
        db.query(Classification)
        .filter(
            Classification.sample_id.in_(sample_ids),
            Classification.classifier_type == "source",
            Classification.classifier_version == CLASSIFIER_VERSION,
        )
        .count()
    )
    return stance_count == len(sample_ids) and source_count == len(sample_ids)


def _classification_counts(db: Session, *, run: ScanRun, successful_samples: list[ExecutionSample]) -> dict[str, int]:
    sample_ids = [_canonical_sample_id(sample) for sample in successful_samples]
    if not sample_ids:
        return {"canonical_samples": 0, "stance": 0, "source": 0}
    canonical_samples = db.query(Sample).filter(Sample.id.in_(sample_ids)).count()
    stance_count = (
        db.query(Classification)
        .filter(Classification.sample_id.in_(sample_ids), Classification.classifier_type == "stance")
        .count()
    )
    source_count = (
        db.query(Classification)
        .filter(Classification.sample_id.in_(sample_ids), Classification.classifier_type == "source")
        .count()
    )
    return {"canonical_samples": canonical_samples, "stance": stance_count, "source": source_count}


def _refresh_progress(
    db: Session,
    *,
    run: ScanRun,
    progress: ScanProgress,
    successful_sample_count: int,
) -> None:
    sample_ids = [_canonical_sample_id(sample) for sample in _successful_execution_samples(db, scan_run_id=run.id)]
    classified_rows = 0
    if sample_ids:
        classified_rows = (
            db.query(Classification)
            .filter(
                Classification.sample_id.in_(sample_ids),
                Classification.classifier_type.in_(["stance", "source"]),
                Classification.classifier_version == CLASSIFIER_VERSION,
            )
            .count()
        )
    expected_rows = successful_sample_count * 2
    progress.stage = "classification_completed" if expected_rows and classified_rows >= expected_rows else "classification_running"
    progress.updated_at = _utcnow()


def _upsert_domain_cache(
    db: Session,
    *,
    domain: str,
    source_class: str,
    classifier_model: str,
    prompt_hash: bytes | None,
    confidence: float,
    source: str,
    evidence: dict[str, Any],
    expires_at: datetime | None,
) -> None:
    row = (
        db.query(DomainClassification)
        .filter(
            DomainClassification.domain == domain,
            DomainClassification.classifier_version == CLASSIFIER_VERSION,
        )
        .first()
    )
    if not row:
        row = DomainClassification(domain=domain, classifier_version=CLASSIFIER_VERSION, created_at=_utcnow())
        db.add(row)
    row.source_class = source_class
    row.classifier_model = classifier_model
    row.prompt_hash = prompt_hash
    row.confidence = _decimal_confidence(confidence)
    row.source = source
    row.evidence = evidence
    row.expires_at = expires_at
    row.updated_at = _utcnow()


def _domain_cache_fresh(row: DomainClassification) -> bool:
    if row.expires_at is None:
        return True
    expires_at = row.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at > _utcnow()


def _mark_classification_failed(
    db: Session,
    *,
    run: ScanRun,
    progress: ScanProgress,
    failed_count: int,
    counts: dict[str, int],
    actor_id: str,
) -> None:
    progress.stage = "classification_failed"
    progress.updated_at = _utcnow()
    run.error_summary = {
        "stage": "classification",
        "failed_count": failed_count,
        "stance_classification_count": counts["stance"],
        "source_classification_count": counts["source"],
        "retryable": True,
    }
    recorded = record_step_once(
        db,
        scan_run_id=run.id,
        step_id="classify_samples",
        event="failed",
        payload={
            "failed_count": failed_count,
            "stance_classification_count": counts["stance"],
            "source_classification_count": counts["source"],
            "retryable": True,
        },
    )
    if recorded:
        _write_classifier_audit(
            db,
            actor_id=actor_id,
            action="scan.classifier.gate_failure",
            resource_id=run.id,
            after_state={
                "scan_run_id": run.id,
                "stage": progress.stage,
                "failed_count": failed_count,
                "retryable": True,
            },
            reason="Classifier failed before all successful provider samples were classified",
            correlation_id=run.idempotency_key,
        )


def _record_classifier_failure(
    db: Session,
    *,
    run: ScanRun,
    classifier_type: str,
    sample_id: str,
    exc: Exception,
) -> None:
    record_step_once(
        db,
        scan_run_id=run.id,
        step_id=f"classifier_{classifier_type}:{sample_id}",
        event="failed",
        payload={"classifier_type": classifier_type, "sample_id": sample_id, "reason": safe_error(exc)},
    )


def _classifier_prompt_payload(*, system_prompt: str, user_prompt: str) -> str:
    payload = {
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
    }
    return CLASSIFIER_PROMPT_SENTINEL + json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _split_classifier_prompt(prompt: str) -> tuple[str | None, str]:
    if not prompt.startswith(CLASSIFIER_PROMPT_SENTINEL):
        return None, prompt
    raw = prompt[len(CLASSIFIER_PROMPT_SENTINEL) :]
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None, prompt
    if not isinstance(payload, dict):
        return None, prompt
    system_prompt = payload.get("system_prompt")
    user_prompt = payload.get("user_prompt")
    if not isinstance(system_prompt, str) or not isinstance(user_prompt, str):
        return None, prompt
    return system_prompt, user_prompt


def _classifier_cost(response: ProviderResponse) -> Decimal:
    explicit = Decimal(str(response.cost_usd or 0))
    if explicit > 0:
        return _money6(explicit)
    input_tokens = Decimal(response.input_tokens or 0)
    output_tokens = Decimal(response.output_tokens or 0)
    usd = (
        (input_tokens * CLASSIFIER_INPUT_USD_PER_MILLION)
        + (output_tokens * CLASSIFIER_OUTPUT_USD_PER_MILLION)
    ) / Decimal("1000000")
    return _money6(usd)


def _record_cost(db: Session, *, run: ScanRun, usd: Decimal) -> None:
    cost = _money6(usd)
    if cost <= 0:
        return
    ledger = (
        db.query(CostLedgerEntry)
        .filter(CostLedgerEntry.scan_run_id == run.id, CostLedgerEntry.provider == CLASSIFIER_COST_PROVIDER)
        .first()
    )
    if not ledger:
        ledger = CostLedgerEntry(scan_run_id=run.id, provider=CLASSIFIER_COST_PROVIDER, spent_usd=Decimal("0"))
        db.add(ledger)
    ledger.spent_usd = _money6(Decimal(ledger.spent_usd or 0) + cost)
    run.cost_spent_usd = _money4(Decimal(run.cost_spent_usd or 0) + cost)


def _raise_if_budget_exhausted(run: ScanRun) -> None:
    if Decimal(run.cost_spent_usd or 0) >= Decimal(run.cost_budget_usd or 0):
        raise ClassificationExecutionError("cost_budget_exhausted", status_code=402)


def _write_classifier_audit(
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


def _raw_response_archive_payload(samples: list[ExecutionSample]) -> list[dict[str, Any]]:
    return [
        {
            "question_id": sample.question_id,
            "provider": sample.provider,
            "provider_model": sample.provider_model,
            "sample_index": sample.sample_index,
            "raw_response_hash": sample.raw_response_hash.hex() if sample.raw_response_hash else None,
            "raw_response_text": _sample_text(sample),
            "raw_response_pointer": sample.raw_response_pointer,
            "response_received_at": sample.response_received_at.isoformat() if sample.response_received_at else None,
        }
        for sample in samples
    ]


def _target_names(client: Client) -> list[str]:
    names = [client.name]
    return [name.strip() for name in names if isinstance(name, str) and name.strip()]


def _client_domains(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {_registered_domain(host_from_url(str(item))) for item in value if str(item).strip()}


def _domain_matches(domain: str, candidates: set[str]) -> bool:
    clean = {candidate for candidate in candidates if candidate}
    return domain in clean


def _registered_domain(host: str) -> str:
    if not host:
        return ""
    try:
        from publicsuffix2 import get_sld

        return (get_sld(host) or host).lower()
    except Exception:
        parts = host.lower().strip(".").split(".")
        if len(parts) <= 2:
            return host.lower().strip(".")
        return ".".join(parts[-2:])


def _sample_text(sample: ExecutionSample) -> str:
    if sample.raw_response_text is not None:
        return sample.raw_response_text
    if sample.raw_response_pointer:
        pointer = Path(sample.raw_response_pointer)
        if not pointer.is_absolute():
            pointer = storage.REPO_ROOT / pointer
        return pointer.read_text(encoding="utf-8")
    return ""


def _canonical_sample_id(sample: ExecutionSample) -> str:
    name = f"{sample.scan_run_id}:{sample.question_id}:{sample.provider}:{sample.sample_index}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, name))


def _seed_for_classifier(seed: int | None, index: int) -> int | None:
    if seed is None:
        return None
    return int(seed) + index + 1


def _decimal_confidence(value: float) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.0001"))


def _money4(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.0001"))


def _money6(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.000001"))


def _usage_value(payload: dict[str, Any], key: str) -> int | None:
    value = payload.get(key)
    if value is None:
        return None
    try:
        return int(Decimal(str(value)))
    except Exception:
        return None


def _audit_hmac_key() -> bytes:
    value = os.getenv("AISO_AUDIT_HMAC_KEY")
    if value:
        return value.encode("utf-8")
    if os.getenv("ENV") == "production":
        raise ClassificationExecutionError("Audit HMAC key is not configured", status_code=500)
    return b"aiso-local-dev-audit-key"


def _audit_hmac_key_version() -> int:
    return int(os.getenv("AISO_AUDIT_HMAC_KEY_VERSION", "1"))


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)
