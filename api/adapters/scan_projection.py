"""Materialize the Phase 13 dashboard projection from scan data.

Loads samples + classifications + manifest for a completed scan, builds the pure
``ProjectionSample`` rows, runs the deterministic builders in
``api.domain.scan_projection``, and upserts the four ``scan_*`` projection tables.
Wired as a saga step (``materialize_dashboard_projection``) between
``compute_scan_avs`` and ``publish_scan``.

Idempotent: deletes any existing projection rows for the scan before re-inserting,
so a retried saga step (or a backfill) produces the same result.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from api.database import (
    Classification,
    Client,
    ExecutionSample,
    QuestionBankQuestion,
    Sample,
    ScanAction,
    ScanCitationP13,
    ScanCompetitor,
    ScanManifest,
    ScanMetric,
    ScanQuestionResult,
    ScanRun,
)
from api.domain.classifier import citation_urls, host_from_url, registered_domain
from api.domain.scan_projection import (
    CitationFact,
    ProjectionSample,
    build_action_plan,
    build_citation_rows,
    build_competitor_rows,
    build_metric_rows,
    build_question_results,
    effective_owned_domains,
)

_PROJECTION_MODELS = (ScanMetric, ScanCitationP13, ScanCompetitor, ScanAction, ScanQuestionResult)


@dataclass(frozen=True)
class ProjectionResult:
    metric_count: int
    citation_count: int
    competitor_count: int
    action_count: int
    question_count: int = 0


class ProjectionError(RuntimeError):
    pass


def materialize_dashboard_projection(db: Session, *, scan_run_id: str, actor_id: str = "system") -> ProjectionResult:
    run = db.query(ScanRun).filter(ScanRun.id == scan_run_id).first()
    if not run:
        raise ProjectionError(f"Scan run not found: {scan_run_id}")
    client = db.query(Client).filter(Client.id == run.client_id).first()
    if not client:
        raise ProjectionError(f"Client not found for scan run: {scan_run_id}")

    # Idempotent: clear any prior projection for this scan.
    for model in _PROJECTION_MODELS:
        db.query(model).filter(model.scan_id == scan_run_id).delete(synchronize_session=False)

    rows = _build_projection_samples(db, scan_run_id=scan_run_id, client_id=client.id)
    if not rows:
        db.flush()
        return ProjectionResult(0, 0, 0, 0)

    brand_aliases = [client.name]
    owned = effective_owned_domains(client.url, list(client.owned_domains or []))
    competitor_domains = list(client.competitor_domains or [])
    competitors = {name: [name] for name in _competitor_names(client)}

    metric_rows = build_metric_rows(rows, brand_aliases=brand_aliases, owned_domains=owned)
    citation_rows = build_citation_rows(rows, owned_domains=owned, competitor_domains=competitor_domains)
    competitor_rows = build_competitor_rows(rows, brand_aliases=brand_aliases, competitors=competitors)
    question_rows = build_question_results(rows, brand_aliases=brand_aliases, competitors=competitors,
                                           owned_domains=owned)
    action_rows = build_action_plan(metric_rows, citation_rows, competitor_rows, brand_name=client.name)

    mvs = run.methodology_version_set_id
    for m in metric_rows:
        db.add(ScanMetric(
            id=str(uuid.uuid4()), scan_id=scan_run_id, client_id=client.id, methodology_version_set_id=mvs,
            scope_type=m.scope_type, provider=m.provider, journey_stage=m.journey_stage,
            total_questions=m.total_questions, total_samples=m.total_samples,
            mention_count=m.mention_count, mention_rate=m.mention_rate,
            mention_rate_ci_lower_95=m.mention_rate_ci_lower_95, mention_rate_ci_upper_95=m.mention_rate_ci_upper_95,
            citation_count=m.citation_count, citation_rate=m.citation_rate,
            citation_rate_ci_lower_95=m.citation_rate_ci_lower_95, citation_rate_ci_upper_95=m.citation_rate_ci_upper_95,
            avs_value=m.avs_value, presence=m.presence, prominence=m.prominence, positivity=m.positivity,
            avg_position=m.avg_position,
        ))
    for c in citation_rows:
        db.add(ScanCitationP13(
            id=str(uuid.uuid4()), scan_id=scan_run_id, client_id=client.id, methodology_version_set_id=mvs,
            sample_id=c.sample_id, provider=c.provider, question_id=c.question_id, journey_stage=c.journey_stage,
            citation_url=c.citation_url, canonical_url=None, source_domain=c.source_domain,
            registered_domain=c.registered_domain, source_rank=c.source_rank, source_class=c.source_class,
            source_confidence=c.source_confidence, action_role=c.action_role,
            is_brand_citation=c.is_brand_citation, is_competitor_citation=c.is_competitor_citation,
            web_search_used=c.web_search_used, answer_excerpt=None,
        ))
    for cp in competitor_rows:
        db.add(ScanCompetitor(
            id=str(uuid.uuid4()), scan_id=scan_run_id, client_id=client.id, methodology_version_set_id=mvs,
            competitor_name=cp.competitor_name, scope_type=cp.scope_type, provider=cp.provider,
            journey_stage=cp.journey_stage, mention_count=cp.mention_count, mention_rate=cp.mention_rate,
            mention_rate_ci_lower_95=cp.mention_rate_ci_lower_95, mention_rate_ci_upper_95=cp.mention_rate_ci_upper_95,
            share_of_voice=cp.share_of_voice, citation_count=cp.citation_count,
        ))
    for a in action_rows:
        db.add(ScanAction(
            id=str(uuid.uuid4()), scan_id=scan_run_id, client_id=client.id, methodology_version_set_id=mvs,
            action_key=a.action_key, title=a.title, description=a.description, priority=a.priority,
            category=a.category, effort=a.effort, impact_estimate=a.impact_estimate, score=a.score,
            sort_order=a.sort_order, action_role=a.action_role, target_provider=a.target_provider,
            target_journey_stage=a.target_journey_stage, target_questions_json=a.target_questions,
            competing_sources_json=a.competing_sources, competing_competitors_json=a.competing_competitors,
            evidence_json=a.evidence, status="open",
        ))

    for qr in question_rows:
        db.add(ScanQuestionResult(
            id=str(uuid.uuid4()), scan_id=scan_run_id, client_id=client.id, methodology_version_set_id=mvs,
            question_id=qr.question_id, question_text=qr.question_text, provider=qr.provider,
            journey_stage=qr.journey_stage, total_samples=qr.total_samples, mention_count=qr.mention_count,
            appeared=qr.appeared, mention_rank=qr.mention_rank, avg_position=qr.avg_position,
            cited_sources_json=qr.cited_sources, competitors_mentioned_json=qr.competitors_mentioned,
            answer_excerpt=qr.answer_excerpt, priority_score=qr.priority_score,
        ))

    db.flush()
    return ProjectionResult(len(metric_rows), len(citation_rows), len(competitor_rows),
                            len(action_rows), len(question_rows))


def _build_projection_samples(db: Session, *, scan_run_id: str, client_id: str) -> list[ProjectionSample]:
    samples = db.query(Sample).filter(Sample.scan_id == scan_run_id).all()
    if not samples:
        return []

    # question_id -> (journey_stage, weight)
    manifest_rows = (
        db.query(ScanManifest, QuestionBankQuestion)
        .join(QuestionBankQuestion, QuestionBankQuestion.question_id == ScanManifest.question_id)
        .filter(ScanManifest.scan_id == scan_run_id, QuestionBankQuestion.client_id == client_id)
        .all()
    )
    journey_by_q = {m.question_id: (q.journey_stage, float(m.weight_at_scan)) for m, q in manifest_rows}
    text_by_q = {q.question_id: (q.text or "") for _m, q in manifest_rows}

    sample_ids = [s.id for s in samples]
    stance_by_sample: dict[str, tuple[str, float]] = {}
    source_domains_by_sample: dict[str, dict[str, tuple[str, float | None]]] = {}
    for cls in (
        db.query(Classification)
        .filter(Classification.sample_id.in_(sample_ids))
        .all()
    ):
        if cls.classifier_type == "stance":
            stance_by_sample[cls.sample_id] = (cls.consensus_value, float(cls.consensus_confidence or 1.0))
        elif cls.classifier_type == "source":
            domain_map: dict[str, tuple[str, float | None]] = {}
            for judgment in cls.individual_judgments or []:
                dom = registered_domain(host_from_url(str(judgment.get("domain") or "")))
                if dom:
                    conf = judgment.get("confidence")
                    domain_map[dom] = (str(judgment.get("source_class") or "UNKNOWN"),
                                       float(conf) if conf is not None else None)
            source_domains_by_sample[cls.sample_id] = domain_map

    # (question_id, provider, sample_index) -> ExecutionSample (for structured citations)
    exec_by_key = {
        (es.question_id, es.provider, es.sample_index): es
        for es in db.query(ExecutionSample).filter(ExecutionSample.scan_run_id == scan_run_id).all()
    }

    out: list[ProjectionSample] = []
    for s in samples:
        stance, stance_conf = stance_by_sample.get(s.id, ("N", 1.0))
        journey, weight = journey_by_q.get(s.question_id, ("J2", 1.0))
        es = exec_by_key.get((s.question_id, s.provider, s.sample_index))
        raw_meta = es.raw_response if es and isinstance(es.raw_response, dict) else {}
        web_search_used = None
        if isinstance(raw_meta, dict):
            meta = raw_meta.get("metadata")
            if isinstance(meta, dict):
                web_search_used = meta.get("web_search_used")

        source_map = source_domains_by_sample.get(s.id, {})
        citations: list[CitationFact] = []
        for url in citation_urls(s.raw_response_text or "", raw_metadata=raw_meta):
            dom = registered_domain(host_from_url(url))
            src_class, src_conf = source_map.get(dom, (None, None))
            citations.append(CitationFact(url=url, domain=dom, source_class=src_class, source_confidence=src_conf))

        out.append(ProjectionSample(
            sample_id=s.id, question_id=s.question_id, provider=s.provider, journey_stage=journey,
            text=s.raw_response_text or "", stance_label=stance, stance_confidence=stance_conf,
            question_weight=weight, web_search_used=web_search_used, citations=citations,
            question_text=text_by_q.get(s.question_id, ""),
        ))
    return out


def _competitor_names(client: Client) -> list[str]:
    if not client.competitors:
        return []
    try:
        data = json.loads(client.competitors)
    except (TypeError, ValueError):
        return []
    if isinstance(data, list):
        return [str(name).strip() for name in data if str(name).strip()]
    return []
