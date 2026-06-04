"""Pure builders for the Phase 13 dashboard projection.

Deterministic, no I/O — mirrors the style of ``avs.py`` and ``classifier.py`` so
the analytics are unit-testable in isolation. The materialization adapter
(``api/adapters/scan_projection.py``) loads samples/classifications from the DB,
builds the lightweight ``ProjectionSample`` rows below, calls these builders,
and upserts the four ``scan_*`` projection tables.

Design (from competitive research): every rate metric carries a 95% Wilson
interval; mention rate and citation rate are tracked separately; everything is
broken out per engine (provider) and per intent (journey stage); actions are
evidence-backed and source-targeted.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from api.domain.avs import (
    AVSSample,
    avs_from_subindices,
    compute_subindices,
    first_mention_position,
    normalized_aliases,
    wilson_interval,
)
from api.domain.classifier import host_from_url

# source_class → action_role. Replaces the legacy static domain allowlist; the
# class itself comes from the (LLM-backed, cached) source classifier.
_ACTION_ROLE_BY_SOURCE_CLASS = {
    "OWNED": "monitor_only",
    "EARNED-HIGH": "digital_pr_target",
    "EARNED-MID": "direct_citation_target",
    "UGC": "community_target",
    "COMPETITOR": "competitive_evidence",
    "UNKNOWN": "review_needed",
}

SCOPE_OVERALL = "overall"
SCOPE_PROVIDER = "provider"
SCOPE_JOURNEY = "journey_stage"
SCOPE_PROVIDER_JOURNEY = "provider_journey"


@dataclass(frozen=True)
class CitationFact:
    """One cited URL observed in a sample, with its classified source domain."""
    url: str
    domain: str
    source_class: str | None = None
    source_confidence: float | None = None
    source_rank: int | None = None


@dataclass(frozen=True)
class ProjectionSample:
    """Normalized per-sample input for the projection builders."""
    sample_id: str
    question_id: str
    provider: str
    journey_stage: str
    text: str
    stance_label: str
    stance_confidence: float = 1.0
    question_weight: float = 1.0
    web_search_used: bool | None = None
    citations: list[CitationFact] = field(default_factory=list)


@dataclass(frozen=True)
class MetricRow:
    scope_type: str
    provider: str | None
    journey_stage: str | None
    total_questions: int
    total_samples: int
    mention_count: int
    mention_rate: float
    mention_rate_ci_lower_95: float
    mention_rate_ci_upper_95: float
    citation_count: int
    citation_rate: float
    citation_rate_ci_lower_95: float
    citation_rate_ci_upper_95: float
    avs_value: float
    presence: float
    prominence: float
    positivity: float
    avg_position: float | None


@dataclass(frozen=True)
class CitationRow:
    sample_id: str
    provider: str
    question_id: str
    journey_stage: str
    citation_url: str
    source_domain: str
    registered_domain: str
    source_rank: int | None
    source_class: str | None
    source_confidence: float | None
    action_role: str | None
    is_brand_citation: bool
    is_competitor_citation: bool
    web_search_used: bool | None


@dataclass(frozen=True)
class CompetitorRow:
    competitor_name: str
    scope_type: str
    provider: str | None
    journey_stage: str | None
    mention_count: int
    mention_rate: float
    mention_rate_ci_lower_95: float
    mention_rate_ci_upper_95: float
    share_of_voice: float
    citation_count: int


@dataclass(frozen=True)
class ActionRow:
    action_key: str
    title: str
    description: str
    priority: str
    category: str
    effort: str
    impact_estimate: float
    score: float
    sort_order: int
    action_role: str | None
    target_provider: str | None
    target_journey_stage: str | None
    target_questions: list[str]
    competing_sources: list[dict]
    competing_competitors: list[str]
    evidence: dict


def action_role_for_source_class(source_class: str | None) -> str:
    return _ACTION_ROLE_BY_SOURCE_CLASS.get((source_class or "UNKNOWN").upper(), "review_needed")


def _avs_samples(rows: list[ProjectionSample]) -> dict[tuple[str, str], list[AVSSample]]:
    by_pair: dict[tuple[str, str], list[AVSSample]] = {}
    for i, s in enumerate(rows):
        by_pair.setdefault((s.question_id, s.provider), []).append(
            AVSSample(
                question_id=s.question_id,
                provider=s.provider,
                sample_index=i,
                text=s.text,
                stance_label=s.stance_label,
                stance_confidence=s.stance_confidence,
                question_weight=s.question_weight,
            )
        )
    return by_pair


def build_metric_rows(rows: list[ProjectionSample], *, brand_aliases: list[str],
                      owned_domains: list[str]) -> list[MetricRow]:
    """Overall + per-provider + per-journey + per-(provider,journey) metric rows."""
    aliases = normalized_aliases(brand_aliases)
    out: list[MetricRow] = [
        _metric_row_with_citations(rows, aliases, owned_domains, scope_type=SCOPE_OVERALL,
                                   provider=None, journey_stage=None)
    ]
    for provider in sorted({s.provider for s in rows}):
        bucket = [s for s in rows if s.provider == provider]
        out.append(_metric_row_with_citations(bucket, aliases, owned_domains,
                                               scope_type=SCOPE_PROVIDER, provider=provider, journey_stage=None))
    for stage in sorted({s.journey_stage for s in rows}):
        bucket = [s for s in rows if s.journey_stage == stage]
        out.append(_metric_row_with_citations(bucket, aliases, owned_domains,
                                               scope_type=SCOPE_JOURNEY, provider=None, journey_stage=stage))
    for provider in sorted({s.provider for s in rows}):
        for stage in sorted({s.journey_stage for s in rows if s.provider == provider}):
            bucket = [s for s in rows if s.provider == provider and s.journey_stage == stage]
            out.append(_metric_row_with_citations(bucket, aliases, owned_domains,
                                                   scope_type=SCOPE_PROVIDER_JOURNEY,
                                                   provider=provider, journey_stage=stage))
    return out


def _metric_row_with_citations(rows: list[ProjectionSample], aliases: list[str],
                               owned_domains: list[str], *, scope_type: str,
                               provider: str | None, journey_stage: str | None) -> MetricRow:
    total_samples = len(rows)
    positions: list[float] = []
    mention_count = 0
    citation_count = 0
    owned = {d.lower() for d in owned_domains}
    for s in rows:
        pos = first_mention_position(s.text, aliases)
        if pos is not None:
            mention_count += 1
            positions.append(float(pos[0]))
        if owned and any(c.domain and any(c.domain.lower().endswith(o) for o in owned) for c in s.citations):
            citation_count += 1

    mention_rate = mention_count / total_samples if total_samples else 0.0
    m_lo, m_hi = wilson_interval(mention_count, total_samples)
    citation_rate = citation_count / total_samples if total_samples else 0.0
    c_lo, c_hi = wilson_interval(citation_count, total_samples)
    indices = compute_subindices(_avs_samples(rows), target_aliases=aliases)
    avg_position = round(sum(positions) / len(positions), 4) if positions else None

    return MetricRow(
        scope_type=scope_type, provider=provider, journey_stage=journey_stage,
        total_questions=len({s.question_id for s in rows}), total_samples=total_samples,
        mention_count=mention_count, mention_rate=round(mention_rate, 5),
        mention_rate_ci_lower_95=round(m_lo, 5), mention_rate_ci_upper_95=round(m_hi, 5),
        citation_count=citation_count, citation_rate=round(citation_rate, 5),
        citation_rate_ci_lower_95=round(c_lo, 5), citation_rate_ci_upper_95=round(c_hi, 5),
        avs_value=round(avs_from_subindices(indices), 3),
        presence=round(indices.presence, 5), prominence=round(indices.prominence, 5),
        positivity=round(indices.positivity, 5), avg_position=avg_position,
    )


def build_citation_rows(rows: list[ProjectionSample], *, owned_domains: list[str],
                        competitor_domains: list[str]) -> list[CitationRow]:
    owned = {d.lower() for d in owned_domains}
    competitor = {d.lower() for d in competitor_domains}
    out: list[CitationRow] = []
    for s in rows:
        for c in s.citations:
            domain = (c.domain or host_from_url(c.url)).lower()
            is_brand = bool(domain) and any(domain.endswith(o) for o in owned)
            is_competitor = bool(domain) and any(domain.endswith(o) for o in competitor)
            out.append(
                CitationRow(
                    sample_id=s.sample_id,
                    provider=s.provider,
                    question_id=s.question_id,
                    journey_stage=s.journey_stage,
                    citation_url=c.url,
                    source_domain=domain,
                    registered_domain=domain,
                    source_rank=c.source_rank,
                    source_class=c.source_class,
                    source_confidence=c.source_confidence,
                    action_role=action_role_for_source_class(c.source_class),
                    is_brand_citation=is_brand,
                    is_competitor_citation=is_competitor,
                    web_search_used=s.web_search_used,
                )
            )
    return out


def detect_competitor_mentions(text: str, competitor_aliases: dict[str, list[str]]) -> set[str]:
    """Return the set of competitor names whose alias appears in the text."""
    mentioned: set[str] = set()
    for name, aliases in competitor_aliases.items():
        norm = normalized_aliases(aliases or [name])
        if first_mention_position(text, norm) is not None:
            mentioned.add(name)
    return mentioned


def build_competitor_rows(rows: list[ProjectionSample], *, brand_aliases: list[str],
                          competitors: dict[str, list[str]]) -> list[CompetitorRow]:
    """Per-competitor overall + per-provider presence and share of voice.

    Share of voice = competitor mentions / (brand mentions + all competitor
    mentions) within the scope.
    """
    brand_norm = normalized_aliases(brand_aliases)

    def _rows_for(bucket: list[ProjectionSample]) -> dict[str, int]:
        counts = {name: 0 for name in competitors}
        for s in bucket:
            for name in detect_competitor_mentions(s.text, competitors):
                counts[name] += 1
        return counts

    def _brand_mentions(bucket: list[ProjectionSample]) -> int:
        return sum(1 for s in bucket if first_mention_position(s.text, brand_norm) is not None)

    out: list[CompetitorRow] = []

    def _emit(bucket: list[ProjectionSample], scope_type: str, provider: str | None) -> None:
        total = len(bucket)
        comp_counts = _rows_for(bucket)
        brand = _brand_mentions(bucket)
        denom = brand + sum(comp_counts.values())
        for name, count in comp_counts.items():
            lo, hi = wilson_interval(count, total)
            sov = (count / denom) if denom else 0.0
            out.append(
                CompetitorRow(
                    competitor_name=name, scope_type=scope_type, provider=provider, journey_stage=None,
                    mention_count=count, mention_rate=round(count / total, 5) if total else 0.0,
                    mention_rate_ci_lower_95=round(lo, 5), mention_rate_ci_upper_95=round(hi, 5),
                    share_of_voice=round(sov, 5), citation_count=0,
                )
            )

    _emit(rows, SCOPE_OVERALL, None)
    for provider in sorted({s.provider for s in rows}):
        _emit([s for s in rows if s.provider == provider], SCOPE_PROVIDER, provider)
    return out


_EFFORT_BY_ROLE = {
    "digital_pr_target": "high",
    "direct_citation_target": "medium",
    "community_target": "medium",
    "competitive_evidence": "medium",
    "monitor_only": "low",
    "review_needed": "low",
}


def build_action_plan(metric_rows: list[MetricRow], citation_rows: list[CitationRow],
                      competitor_rows: list[CompetitorRow], *, brand_name: str,
                      limit: int = 20) -> list[ActionRow]:
    """Prioritized, evidence-backed actions.

    Two families, ranked by estimated AVS-point impact ÷ effort:
    1. Weak intent/provider scopes (low mention rate) → "win these questions".
    2. Source opportunities: non-owned domains repeatedly cited where the brand
       is absent → "get cited on domain X" (role from source_class).
    """
    actions: list[ActionRow] = []

    # 1. Weak scopes: provider and journey scopes with low mention rate.
    weak_scopes = [
        m for m in metric_rows
        if m.scope_type in {SCOPE_PROVIDER, SCOPE_JOURNEY} and m.total_samples >= 3 and m.mention_rate < 0.5
    ]
    for m in sorted(weak_scopes, key=lambda r: r.mention_rate):
        scope_label = m.provider or m.journey_stage or "overall"
        impact = round((0.5 - m.mention_rate) * 100, 2)
        actions.append(
            ActionRow(
                action_key=f"weak:{m.scope_type}:{scope_label}",
                title=f"Improve visibility for {scope_label}",
                description=(
                    f"{brand_name} appears in only {m.mention_count}/{m.total_samples} "
                    f"answers for {scope_label} (mention rate {m.mention_rate:.0%}, "
                    f"95% CI {m.mention_rate_ci_lower_95:.0%}–{m.mention_rate_ci_upper_95:.0%})."
                ),
                priority="high" if m.mention_rate < 0.25 else "medium",
                category="weak_visibility",
                effort="medium",
                impact_estimate=impact,
                score=round((0.5 - m.mention_rate) * (m.total_samples ** 0.5), 4),
                sort_order=0,
                action_role=None,
                target_provider=m.provider,
                target_journey_stage=m.journey_stage,
                target_questions=[],
                competing_sources=[],
                competing_competitors=[],
                evidence={"mention_rate": m.mention_rate, "ci": [m.mention_rate_ci_lower_95, m.mention_rate_ci_upper_95]},
            )
        )

    # 2. Source opportunities: non-owned, non-UNKNOWN domains cited frequently.
    domain_counts: dict[str, dict] = {}
    for c in citation_rows:
        if c.is_brand_citation or not c.source_domain:
            continue
        entry = domain_counts.setdefault(
            c.source_domain,
            {"count": 0, "source_class": c.source_class, "action_role": c.action_role,
             "providers": set(), "questions": set()},
        )
        entry["count"] += 1
        entry["providers"].add(c.provider)
        if c.question_id:
            entry["questions"].add(c.question_id)

    for domain, entry in sorted(domain_counts.items(), key=lambda kv: kv[1]["count"], reverse=True):
        if entry["count"] < 2:
            continue
        role = entry["action_role"] or "review_needed"
        actions.append(
            ActionRow(
                action_key=f"source:{domain}",
                title=f"Earn presence on {domain}",
                description=(
                    f"{domain} ({entry['source_class'] or 'UNKNOWN'}) was cited "
                    f"{entry['count']} times where {brand_name} was not the source."
                ),
                priority="high" if entry["count"] >= 5 else "medium",
                category="source_opportunity",
                effort=_EFFORT_BY_ROLE.get(role, "medium"),
                impact_estimate=round(min(entry["count"] * 1.5, 15.0), 2),
                score=round(float(entry["count"]), 4),
                sort_order=0,
                action_role=role,
                target_provider=sorted(entry["providers"])[0] if entry["providers"] else None,
                target_journey_stage=None,
                target_questions=sorted(entry["questions"])[:10],
                competing_sources=[{"domain": domain, "source_class": entry["source_class"], "count": entry["count"]}],
                competing_competitors=[],
                evidence={"citation_count": entry["count"], "providers": sorted(entry["providers"])},
            )
        )

    ranked = sorted(actions, key=lambda a: a.score, reverse=True)[:limit]
    return [
        ActionRow(**{**a.__dict__, "sort_order": i})  # type: ignore[arg-type]
        for i, a in enumerate(ranked)
    ]
