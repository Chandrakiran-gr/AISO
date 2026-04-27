"""Deterministic action recommendations for completed AISO scans.

The engine follows a simple production-safe pattern:
candidate generation -> scoring -> category-aware re-ranking.
It is intentionally deterministic so actions are explainable, testable, and
cheap to generate during scan persistence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable
import json


GROUP_LABELS = {
    "G1": "category and local discovery",
    "G2": "direct brand questions",
    "G3": "competitor and alternative comparisons",
    "G4": "transactional buying intent",
    "G5": "trust, reviews, and risk",
    "G6": "fit, persona, and constraint questions",
    "G7": "head-to-head choice questions",
    "all": "all questions",
}

PROVIDER_LABELS = {
    "openai": "ChatGPT",
    "claude": "Claude",
    "perplexity": "Perplexity",
    "gemini": "Gemini",
}

GROUP_IMPORTANCE = {
    "G2": 10,
    "G3": 9,
    "G5": 8,
    "G7": 8,
    "G4": 6,
    "G1": 5,
    "G6": 4,
}

PRIORITY_ORDER = {"high": 3, "medium": 2, "low": 1}


@dataclass(frozen=True)
class ActionCandidate:
    action_key: str
    title: str
    description: str
    priority: str
    category: str
    impact_pts: str
    effort: str
    score: float
    evidence: dict[str, Any]


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _score(mentions: int, total: int) -> float:
    return round((mentions / total) * 100, 2) if total else 0.0


def _label_provider(provider: str) -> str:
    return PROVIDER_LABELS.get(provider, provider)


def _label_group(group: str) -> str:
    return GROUP_LABELS.get(group, group)


def _competitor_data(result: Any) -> dict[str, int]:
    raw = getattr(result, "competitor_data", {}) or {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return {}
    if not isinstance(raw, dict):
        return {}
    return {
        str(name): _as_int(count)
        for name, count in raw.items()
        if str(name).strip()
    }


def _result_buckets(results: Iterable[Any], attr: str) -> dict[str, dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    for result in results:
        key = str(getattr(result, attr, "") or "all")
        bucket = buckets.setdefault(
            key,
            {
                "mentions": 0,
                "total": 0,
                "providers": set(),
                "groups": set(),
            },
        )
        bucket["mentions"] += _as_int(getattr(result, "mention_count", 0))
        bucket["total"] += _as_int(getattr(result, "total_questions", 0))
        bucket["providers"].add(str(getattr(result, "provider", "")))
        bucket["groups"].add(str(getattr(result, "group", "")))
    return buckets


def _citation_summary(citations: Iterable[Any]) -> dict[str, Any]:
    total = 0
    domains: set[str] = set()
    by_provider: dict[str, int] = {}
    by_group: dict[str, int] = {}

    for citation in citations:
        total += 1
        provider = str(getattr(citation, "provider", "") or "")
        group = str(getattr(citation, "group", "") or "")
        domain = str(getattr(citation, "source_domain", "") or "").strip()
        if domain:
            domains.add(domain)
        if provider:
            by_provider[provider] = by_provider.get(provider, 0) + 1
        if group:
            by_group[group] = by_group.get(group, 0) + 1

    return {
        "total": total,
        "domains": sorted(domains),
        "by_provider": by_provider,
        "by_group": by_group,
    }


def _overall_candidate(overall: float, total_questions: int) -> ActionCandidate | None:
    if overall < 35:
        return ActionCandidate(
            action_key="overall:entity-foundation",
            title="Strengthen the core business entity signals",
            description=(
                "AI providers are rarely naming the business. Add clear brand, category, "
                "location, service, pricing, and FAQ copy to the homepage and key service pages."
            ),
            priority="high",
            category="entity",
            impact_pts="+8-12 pts",
            effort="2-4 hours",
            score=96 - (overall * 0.25),
            evidence={
                "kind": "overall_visibility",
                "overall_score": overall,
                "total_questions": total_questions,
            },
        )

    if overall < 60:
        return ActionCandidate(
            action_key="overall:comparison-trust",
            title="Add comparison and trust content",
            description=(
                "The business is visible but not dominant. Publish direct answers for reviews, "
                "comparisons, risks, guarantees, and fit questions so AI systems have stronger copy to reuse."
            ),
            priority="medium",
            category="content",
            impact_pts="+5-8 pts",
            effort="3-5 hours",
            score=74 - (overall * 0.15),
            evidence={
                "kind": "overall_visibility",
                "overall_score": overall,
                "total_questions": total_questions,
            },
        )

    return None


def _weak_group_candidates(group_buckets: dict[str, dict[str, Any]]) -> list[ActionCandidate]:
    candidates: list[ActionCandidate] = []
    for group, bucket in group_buckets.items():
        total = _as_int(bucket["total"])
        mentions = _as_int(bucket["mentions"])
        group_score = _score(mentions, total)
        if total == 0 or group_score >= 65:
            continue

        label = _label_group(group)
        priority = "high" if group_score < 35 else "medium"
        candidates.append(
            ActionCandidate(
                action_key=f"group:{group}:answer-content",
                title=f"Build answer-ready content for {label}",
                description=(
                    f"This intent area scored {round(group_score)}/100 across {total} "
                    "provider-question results. Publish concise answer-first content that names the business, "
                    "the service, the location, and the decision criteria customers ask about."
                ),
                priority=priority,
                category="content",
                impact_pts="+3-6 pts",
                effort="1-3 hours",
                score=(100 - group_score) * 0.55 + min(total, 28) + GROUP_IMPORTANCE.get(group, 3),
                evidence={
                    "kind": "weak_intent_group",
                    "group": group,
                    "group_label": label,
                    "score": group_score,
                    "mention_count": mentions,
                    "total_questions": total,
                    "providers": sorted(provider for provider in bucket["providers"] if provider),
                },
            )
        )
    return candidates


def _provider_gap_candidates(
    provider_buckets: dict[str, dict[str, Any]],
    overall: float,
) -> list[ActionCandidate]:
    candidates: list[ActionCandidate] = []
    for provider, bucket in provider_buckets.items():
        total = _as_int(bucket["total"])
        mentions = _as_int(bucket["mentions"])
        provider_score = _score(mentions, total)
        gap = max(0.0, overall - provider_score)
        if total == 0 or (provider_score >= 50 and gap < 15):
            continue

        label = _label_provider(provider)
        priority = "high" if provider_score < 30 else "medium"
        candidates.append(
            ActionCandidate(
                action_key=f"provider:{provider}:visibility-gap",
                title=f"Improve visibility in {label}",
                description=(
                    f"{label} mentioned the business in {mentions}/{total} relevant results. "
                    "Add provider-readable answer sections with clear service descriptions, comparison copy, "
                    "and proof points that directly match the missed question patterns."
                ),
                priority=priority,
                category="provider",
                impact_pts="+3-7 pts",
                effort="1-3 hours",
                score=(100 - provider_score) * 0.45 + gap * 1.4 + min(total, 20),
                evidence={
                    "kind": "provider_gap",
                    "provider": provider,
                    "provider_label": label,
                    "score": provider_score,
                    "overall_score": overall,
                    "mention_count": mentions,
                    "total_questions": total,
                    "groups": sorted(group for group in bucket["groups"] if group),
                },
            )
        )
    return candidates


def _competitor_candidate(
    results: Iterable[Any],
    overall: float,
    total_questions: int,
) -> ActionCandidate | None:
    if total_questions == 0:
        return None

    competitor_counts: dict[str, int] = {}
    competitor_providers: dict[str, set[str]] = {}
    for result in results:
        provider = str(getattr(result, "provider", "") or "")
        for name, count in _competitor_data(result).items():
            competitor_counts[name] = competitor_counts.get(name, 0) + count
            if count > 0 and provider:
                competitor_providers.setdefault(name, set()).add(provider)

    if not competitor_counts:
        return None

    competitor, mentions = max(competitor_counts.items(), key=lambda item: item[1])
    competitor_score = _score(mentions, total_questions)
    if competitor_score < 15 and competitor_score < max(0, overall - 5):
        return None

    gap = competitor_score - overall
    priority = "high" if gap >= 10 else "medium"
    return ActionCandidate(
        action_key=f"competitor:{competitor.lower()}:close-gap",
        title=f"Close the AI recommendation gap with {competitor}",
        description=(
            f"{competitor} is being named in {mentions}/{total_questions} comparable results. "
            "Create comparison, alternative, and proof content that explains when customers should choose your business."
        ),
        priority=priority,
        category="competitor",
        impact_pts="+4-8 pts",
        effort="2-5 hours",
        score=62 + max(gap, 0) * 1.2 + min(mentions, 24),
        evidence={
            "kind": "competitor_pressure",
            "competitor": competitor,
            "competitor_score": competitor_score,
            "overall_score": overall,
            "mention_count": mentions,
            "total_questions": total_questions,
            "providers": sorted(competitor_providers.get(competitor, set())),
        },
    )


def _citation_candidate(
    citation_summary: dict[str, Any],
    provider_count: int,
    group_count: int,
    overall: float,
) -> ActionCandidate | None:
    citation_count = _as_int(citation_summary["total"])
    domains = list(citation_summary["domains"])
    minimum_domains = min(3, max(1, provider_count))

    if citation_count > 0 and len(domains) >= minimum_domains:
        return None

    priority = "high" if citation_count == 0 and overall < 60 else "medium"
    return ActionCandidate(
        action_key="proof:citeable-sources",
        title="Add citeable proof sources AI can reference",
        description=(
            "The scan has limited source evidence. Add or strengthen review pages, service pages, "
            "case studies, local listings, and FAQ content that AI providers can cite when recommending the business."
        ),
        priority=priority,
        category="proof",
        impact_pts="+3-6 pts",
        effort="2-4 hours",
        score=82 if citation_count == 0 else 58 + (minimum_domains - len(domains)) * 7,
        evidence={
            "kind": "citation_coverage",
            "citation_count": citation_count,
            "unique_source_domains": len(domains),
            "source_domains": domains[:5],
            "provider_count": provider_count,
            "group_count": group_count,
        },
    )


def _maintenance_candidate(overall: float, total_questions: int) -> ActionCandidate:
    return ActionCandidate(
        action_key="maintenance:scan-review",
        title="Maintain current AI visibility coverage",
        description=(
            "The latest scan shows healthy coverage. Keep answer pages current, watch competitor movement, "
            "and rerun the scan after meaningful website or review changes."
        ),
        priority="low",
        category="monitoring",
        impact_pts="+1-2 pts",
        effort="30 minutes",
        score=max(42, overall * 0.45),
        evidence={
            "kind": "maintenance",
            "overall_score": overall,
            "total_questions": total_questions,
        },
    )


def _rank_candidates(candidates: Iterable[ActionCandidate], limit: int) -> list[ActionCandidate]:
    deduped: dict[str, ActionCandidate] = {}
    for candidate in candidates:
        current = deduped.get(candidate.action_key)
        if current is None or candidate.score > current.score:
            deduped[candidate.action_key] = candidate

    sorted_candidates = sorted(
        deduped.values(),
        key=lambda item: (
            item.score,
            PRIORITY_ORDER.get(item.priority, 0),
            item.action_key,
        ),
        reverse=True,
    )

    selected: list[ActionCandidate] = []
    overflow: list[ActionCandidate] = []
    category_counts: dict[str, int] = {}
    for candidate in sorted_candidates:
        if len(selected) >= limit:
            break
        count = category_counts.get(candidate.category, 0)
        if count >= 2:
            overflow.append(candidate)
            continue
        selected.append(candidate)
        category_counts[candidate.category] = count + 1

    for candidate in overflow:
        if len(selected) >= limit:
            break
        selected.append(candidate)

    return selected[:limit]


def build_action_recommendations(
    results: list[Any],
    citations: Iterable[Any] | None = None,
    *,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Return deterministic action rows ready for persistence."""
    if not results:
        return []

    total_questions = sum(_as_int(getattr(result, "total_questions", 0)) for result in results)
    total_mentions = sum(_as_int(getattr(result, "mention_count", 0)) for result in results)
    overall = _score(total_mentions, total_questions)
    group_buckets = _result_buckets(results, "group")
    provider_buckets = _result_buckets(results, "provider")
    summary = _citation_summary(citations or [])

    candidates: list[ActionCandidate] = []
    overall_candidate = _overall_candidate(overall, total_questions)
    if overall_candidate:
        candidates.append(overall_candidate)
    candidates.extend(_weak_group_candidates(group_buckets))
    candidates.extend(_provider_gap_candidates(provider_buckets, overall))

    competitor_candidate = _competitor_candidate(results, overall, total_questions)
    if competitor_candidate:
        candidates.append(competitor_candidate)

    citation_candidate = _citation_candidate(
        summary,
        provider_count=len(provider_buckets),
        group_count=len(group_buckets),
        overall=overall,
    )
    if citation_candidate:
        candidates.append(citation_candidate)

    if not candidates or overall >= 70:
        candidates.append(_maintenance_candidate(overall, total_questions))

    ranked = _rank_candidates(candidates, limit)
    return [
        {
            "action_key": candidate.action_key,
            "title": candidate.title,
            "description": candidate.description,
            "priority": candidate.priority,
            "category": candidate.category,
            "impact_pts": candidate.impact_pts,
            "effort": candidate.effort,
            "score": round(candidate.score, 2),
            "sort_order": index,
            "evidence_json": json.dumps(candidate.evidence, sort_keys=True),
            "status": "open",
        }
        for index, candidate in enumerate(ranked, start=1)
    ]
