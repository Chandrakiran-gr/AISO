"""Deterministic scan gap report generation.

The gap report is the client-facing interpretation layer: it turns raw provider
answers into appeared/missed query rows, cited source opportunities, and ranked
fixes without spending additional LLM/API credits.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable, Mapping
from urllib.parse import urlsplit

from full_stack.scan_metrics import (
    ClientIdentity,
    aggregate_scan_results,
    extract_scan_citations,
    _answer_excerpt,
    _first_position,
    _mention_rank,
    _name_aliases,
)


GROUP_LABELS = {
    "G1": "Local discovery",
    "G2": "Branded direct",
    "G3": "Competitors and alternatives",
    "G4": "Transactional and price",
    "G5": "Trust, reviews and safety",
    "G6": "Concern, outcome and fit",
    "G7": "Method comparison and head-to-head",
    "all": "All questions",
}

GROUP_IMPACT = {
    "G1": 8.5,
    "G2": 6.0,
    "G3": 8.8,
    "G4": 9.4,
    "G5": 8.0,
    "G6": 9.2,
    "G7": 9.0,
}


@dataclass(frozen=True)
class GapReportInput:
    rows: list[Mapping[str, str]]
    fieldnames: list[str]
    identity: ClientIdentity
    client_url: str | None = None
    scan_id: str | None = None
    client_id: str | None = None
    client_name: str | None = None


def _provider_names(fieldnames: Iterable[str]) -> list[str]:
    return sorted(
        name.removeprefix("response_")
        for name in fieldnames
        if name.startswith("response_")
    )


def _client_domain(client_url: str | None) -> str | None:
    raw = str(client_url or "").strip()
    if not raw:
        return None
    if not raw.startswith(("http://", "https://")):
        raw = f"https://{raw}"
    try:
        domain = urlsplit(raw).netloc.lower()
    except ValueError:
        return None
    return domain.removeprefix("www.") or None


def _competitors_in_answer(answer: str, competitors: Iterable[str]) -> list[str]:
    result: list[str] = []
    for competitor in competitors:
        if _first_position(answer, _name_aliases(competitor)) is not None:
            result.append(competitor)
    return result


def _citation_key(provider: str, group: str | None, question: str | None) -> tuple[str, str, str]:
    return (provider, group or "", question or "")


def _question_priority(group: str, appeared: bool, competitors: list[str], source_count: int) -> float:
    score = GROUP_IMPACT.get(group, 6.0)
    if not appeared:
        score += 1.2
    if competitors:
        score += 0.9
    if source_count:
        score += 0.5
    return round(min(score, 10.0), 2)


def _source_title(domain: str) -> str:
    if domain.endswith("google.com"):
        return "Strengthen Google Business Profile and local proof"
    if domain.endswith("yelp.com"):
        return "Improve Yelp/review proof for missed queries"
    if domain.endswith("facebook.com") or domain.endswith("instagram.com"):
        return "Improve social profile proof and service language"
    return f"Build citation/proof coverage on {domain}"


def _impact_label(score: float) -> str:
    if score >= 8.5:
        return "high"
    if score >= 6.5:
        return "medium"
    return "low"


def build_gap_report(payload: GapReportInput) -> dict[str, Any]:
    providers = _provider_names(payload.fieldnames)
    client_domain = _client_domain(payload.client_url)
    aggregate_rows = aggregate_scan_results(payload.rows, payload.fieldnames, payload.identity)
    citation_rows = extract_scan_citations(payload.rows, payload.fieldnames)
    citations_by_answer: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)

    for citation in citation_rows:
        citations_by_answer[_citation_key(citation.provider, citation.group, citation.question)].append(
            {
                "url": citation.citation_url,
                "title": citation.citation_title,
                "domain": citation.source_domain,
                "rank": citation.source_rank,
            }
        )

    query_rows: list[dict[str, Any]] = []
    source_buckets: dict[str, dict[str, Any]] = {}
    competitor_pressure: dict[str, dict[str, Any]] = {}
    group_provider: dict[tuple[str, str], dict[str, int]] = {}

    for row in payload.rows:
        group = str(row.get("group") or "all")
        question = str(row.get("question") or "").strip()
        for provider in providers:
            answer = str(row.get(f"response_{provider}") or "")
            if not answer.strip():
                continue

            rank = _mention_rank(answer, payload.identity.focal_aliases, payload.identity.competitors)
            appeared = rank is not None
            competitors = _competitors_in_answer(answer, payload.identity.competitors)
            sources = citations_by_answer.get(_citation_key(provider, group, question), [])
            bucket = group_provider.setdefault((group, provider), {"total": 0, "appeared": 0, "missed": 0})
            bucket["total"] += 1
            if appeared:
                bucket["appeared"] += 1
            else:
                bucket["missed"] += 1

            if not appeared:
                for source in sources:
                    domain = str(source.get("domain") or "").lower()
                    if not domain or domain == client_domain:
                        continue
                    source_bucket = source_buckets.setdefault(
                        domain,
                        {
                            "domain": domain,
                            "missed_query_count": 0,
                            "providers": set(),
                            "groups": set(),
                            "example_questions": [],
                            "top_urls": [],
                        },
                    )
                    source_bucket["missed_query_count"] += 1
                    source_bucket["providers"].add(provider)
                    source_bucket["groups"].add(group)
                    if question and question not in source_bucket["example_questions"]:
                        source_bucket["example_questions"].append(question)
                    if source.get("url") and source["url"] not in source_bucket["top_urls"]:
                        source_bucket["top_urls"].append(source["url"])

                for competitor in competitors:
                    pressure = competitor_pressure.setdefault(
                        competitor,
                        {
                            "name": competitor,
                            "missed_query_count": 0,
                            "providers": set(),
                            "groups": set(),
                            "example_questions": [],
                        },
                    )
                    pressure["missed_query_count"] += 1
                    pressure["providers"].add(provider)
                    pressure["groups"].add(group)
                    if question and question not in pressure["example_questions"]:
                        pressure["example_questions"].append(question)

            query_rows.append(
                {
                    "question": question,
                    "group": group,
                    "group_label": GROUP_LABELS.get(group, group),
                    "provider": provider,
                    "appeared": appeared,
                    "mention_rank": rank,
                    "competitors_mentioned": competitors,
                    "cited_sources": sources,
                    "answer_excerpt": _answer_excerpt(answer, limit=360),
                    "priority_score": _question_priority(group, appeared, competitors, len(sources)),
                }
            )

    total_queries = len(query_rows)
    appeared_count = sum(1 for row in query_rows if row["appeared"])
    missed_count = total_queries - appeared_count

    weak_segments = []
    for result in aggregate_rows:
        if result.visibility_score >= 70:
            continue
        weak_segments.append(
            {
                "provider": result.provider,
                "group": result.group,
                "group_label": GROUP_LABELS.get(result.group, result.group),
                "score": result.visibility_score,
                "appeared": result.mention_count,
                "total": result.total_questions,
                "missed": max((result.total_questions or 0) - (result.mention_count or 0), 0),
            }
        )
    weak_segments.sort(key=lambda item: (item["score"], -GROUP_IMPACT.get(item["group"], 0)))

    source_opportunities = []
    for source in source_buckets.values():
        source_opportunities.append(
            {
                "domain": source["domain"],
                "missed_query_count": source["missed_query_count"],
                "providers": sorted(source["providers"]),
                "groups": sorted(source["groups"]),
                "example_questions": source["example_questions"][:3],
                "top_urls": source["top_urls"][:3],
            }
        )
    source_opportunities.sort(key=lambda item: item["missed_query_count"], reverse=True)

    competitor_gaps = []
    for pressure in competitor_pressure.values():
        competitor_gaps.append(
            {
                "name": pressure["name"],
                "missed_query_count": pressure["missed_query_count"],
                "providers": sorted(pressure["providers"]),
                "groups": sorted(pressure["groups"]),
                "example_questions": pressure["example_questions"][:3],
            }
        )
    competitor_gaps.sort(key=lambda item: item["missed_query_count"], reverse=True)

    priority_fixes: list[dict[str, Any]] = []
    for segment in weak_segments[:4]:
        score = GROUP_IMPACT.get(segment["group"], 6.0) + (70 - segment["score"]) / 20
        priority_fixes.append(
            {
                "title": f"Close {segment['group_label']} gaps on {segment['provider']}",
                "impact": _impact_label(score),
                "score": round(min(score, 10.0), 2),
                "why": (
                    f"{segment['missed']} of {segment['total']} provider-question results did not mention "
                    f"{payload.identity.focal_name}."
                ),
                "next_step": "Add or improve service, FAQ, review, and proof content matching these missed query intents.",
                "evidence": {
                    "provider": segment["provider"],
                    "group": segment["group"],
                    "visibility_score": segment["score"],
                },
            }
        )

    for source in source_opportunities[:3]:
        score = min(9.5, 6.5 + source["missed_query_count"] * 0.4)
        priority_fixes.append(
            {
                "title": _source_title(source["domain"]),
                "impact": _impact_label(score),
                "score": round(score, 2),
                "why": f"{source['domain']} was cited on {source['missed_query_count']} missed query results.",
                "next_step": "Earn, update, or align proof on this source so AI systems can connect it back to the business.",
                "evidence": {
                    "domain": source["domain"],
                    "example_questions": source["example_questions"][:2],
                    "top_urls": source["top_urls"][:2],
                },
            }
        )

    for competitor in competitor_gaps[:2]:
        score = min(9.3, 7.0 + competitor["missed_query_count"] * 0.35)
        priority_fixes.append(
            {
                "title": f"Create comparison proof against {competitor['name']}",
                "impact": _impact_label(score),
                "score": round(score, 2),
                "why": f"{competitor['name']} appeared in {competitor['missed_query_count']} missed query results.",
                "next_step": "Add comparison, alternative, differentiator, and review proof for the same intents.",
                "evidence": {
                    "competitor": competitor["name"],
                    "example_questions": competitor["example_questions"][:2],
                },
            }
        )

    priority_fixes.sort(key=lambda item: item["score"], reverse=True)

    return {
        "client_id": payload.client_id,
        "client_name": payload.client_name or payload.identity.focal_name,
        "scan_id": payload.scan_id,
        "summary": {
            "total_provider_question_results": total_queries,
            "appeared_count": appeared_count,
            "missed_count": missed_count,
            "appearance_rate": round((appeared_count / total_queries) * 100, 2) if total_queries else 0.0,
            "source_opportunity_count": len(source_opportunities),
            "competitor_gap_count": len(competitor_gaps),
        },
        "coverage": [
            {
                "group": group,
                "group_label": GROUP_LABELS.get(group, group),
                "provider": provider,
                **counts,
                "appearance_rate": round((counts["appeared"] / counts["total"]) * 100, 2) if counts["total"] else 0.0,
            }
            for (group, provider), counts in sorted(group_provider.items())
        ],
        "weak_segments": weak_segments,
        "source_opportunities": source_opportunities[:20],
        "competitor_gaps": competitor_gaps[:20],
        "priority_fixes": priority_fixes[:8],
        "query_results": sorted(query_rows, key=lambda item: (item["appeared"], -item["priority_score"]))[:200],
    }
