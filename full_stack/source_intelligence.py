"""Deterministic source intelligence for AISO scan evidence.

This module turns provider citations into a source graph signal. It is kept
pure and dependency-light so collection, persistence, gap reports, and tests can
all use the same canonicalization and classification logic.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


TRACKING_QUERY_PARAMS = {
    "fbclid",
    "gclid",
    "gbraid",
    "igshid",
    "mc_cid",
    "mc_eid",
    "msclkid",
    "twclid",
}

DIRECTORY_OR_REVIEW_DOMAINS = {
    "angi.com",
    "bbb.org",
    "birdeye.com",
    "clutch.co",
    "facebook.com",
    "g2.com",
    "google.com",
    "maps.google.com",
    "nextdoor.com",
    "trustpilot.com",
    "tripadvisor.com",
    "yelp.com",
    "yellowpages.com",
    "zocdoc.com",
}

MARKETPLACE_OR_BOOKING_DOMAINS = {
    "booksy.com",
    "classpass.com",
    "fresha.com",
    "glossgenius.com",
    "mindbodyonline.com",
    "square.site",
    "vagaro.com",
}

AUTHORITY_DOMAINS = {
    "aad.org",
    "asds.net",
    "clevelandclinic.org",
    "healthline.com",
    "mayoclinic.org",
    "nih.gov",
    "ncbi.nlm.nih.gov",
    "pmc.ncbi.nlm.nih.gov",
    "webmd.com",
}

SOCIAL_OR_UGC_DOMAINS = {
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "pinterest.com",
    "reddit.com",
    "tiktok.com",
    "twitter.com",
    "x.com",
    "youtube.com",
}

LOW_VALUE_OR_SEARCH_DOMAINS = {
    "bing.com",
    "duckduckgo.com",
    "google.com/search",
    "search.yahoo.com",
}

LOCAL_PUBLISHER_HINTS = {
    "boston",
    "chicago",
    "daily",
    "gazette",
    "guide",
    "local",
    "magazine",
    "miami",
    "newyork",
    "news",
    "post",
    "tribune",
}

GROUP_IMPACT_WEIGHT = {
    "G1": 0.80,
    "G2": 0.55,
    "G3": 0.88,
    "G4": 0.95,
    "G5": 0.75,
    "G6": 0.92,
    "G7": 0.90,
    "all": 0.60,
}


@dataclass(frozen=True)
class SourceClassification:
    owner_type: str
    source_type: str
    action_role: str
    actionability_score: float
    relevance_score: float
    confidence_score: float
    classification_reason: str


@dataclass(frozen=True)
class SourceScores:
    influence_score: float
    opportunity_score: float


def clean_url(raw_url: str) -> str:
    url = str(raw_url or "").strip().strip("<>\"'")
    return url.rstrip(".,;:!?)]+}")


def canonicalize_url(raw_url: str) -> str | None:
    """Normalize URLs for dedupe and durable source profile keys."""
    url = clean_url(raw_url)
    if not url.startswith(("http://", "https://")):
        return None
    try:
        parsed = urlsplit(url)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None

    netloc = parsed.netloc.lower().removeprefix("www.")
    if netloc.endswith(":80") and parsed.scheme == "http":
        netloc = netloc[:-3]
    if netloc.endswith(":443") and parsed.scheme == "https":
        netloc = netloc[:-4]

    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in TRACKING_QUERY_PARAMS
    ]
    query.sort()
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")

    return urlunsplit((parsed.scheme.lower(), netloc, path, urlencode(query, doseq=True), ""))


def source_domain(raw_url: str | None) -> str | None:
    if not raw_url:
        return None
    canonical = canonicalize_url(raw_url)
    if not canonical:
        return None
    return urlsplit(canonical).netloc.lower().removeprefix("www.") or None


def answer_excerpt(text: str, limit: int = 420) -> str | None:
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    if not clean:
        return None
    return clean if len(clean) <= limit else clean[: limit - 1].rstrip() + "…"


def _domain_matches(domain: str, candidates: Iterable[str]) -> bool:
    return any(domain == candidate or domain.endswith(f".{candidate}") for candidate in candidates)


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in re.split(r"[^a-z0-9]+", value.lower())
        if len(token) >= 4 and token not in {"company", "business", "skincare", "wellness"}
    }


def _competitor_hint(domain: str, title: str | None, competitors: Iterable[str]) -> str | None:
    haystack = f"{domain} {title or ''}".lower()
    for competitor in competitors:
        tokens = _tokens(competitor)
        if tokens and any(token in haystack for token in tokens):
            return competitor
    return None


def classify_source(
    canonical_url: str,
    title: str | None = None,
    client_domain: str | None = None,
    competitors: Iterable[str] = (),
) -> SourceClassification:
    """Classify source ownership and actionability without LLM calls."""
    domain = source_domain(canonical_url) or ""
    parsed_path = urlsplit(canonical_url).path.lower()
    if client_domain and domain == client_domain.removeprefix("www."):
        return SourceClassification(
            owner_type="owned",
            source_type="client_site",
            action_role="monitor_only",
            actionability_score=5.5,
            relevance_score=8.0,
            confidence_score=9.5,
            classification_reason="This is the client's owned domain.",
        )

    if (
        any(domain == item or domain.endswith(f".{item}") for item in {"bing.com", "duckduckgo.com", "search.yahoo.com"})
        or (domain == "google.com" and parsed_path.startswith("/search"))
        or any(f"{domain}{parsed_path}".startswith(item) for item in LOW_VALUE_OR_SEARCH_DOMAINS)
    ):
        return SourceClassification(
            owner_type="third_party",
            source_type="low_value_or_noise",
            action_role="ignore",
            actionability_score=0.5,
            relevance_score=2.0,
            confidence_score=7.0,
            classification_reason="Search/result utility URL is not a durable citation target.",
        )

    if _domain_matches(domain, MARKETPLACE_OR_BOOKING_DOMAINS):
        return SourceClassification(
            owner_type="third_party",
            source_type="marketplace_or_booking",
            action_role="listing_or_profile_target",
            actionability_score=8.2,
            relevance_score=8.0,
            confidence_score=9.0,
            classification_reason="Booking marketplace/listing source can often be claimed or optimized.",
        )

    if _domain_matches(domain, DIRECTORY_OR_REVIEW_DOMAINS):
        return SourceClassification(
            owner_type="third_party",
            source_type="directory_or_review",
            action_role="listing_or_profile_target",
            actionability_score=8.5,
            relevance_score=8.0,
            confidence_score=8.5,
            classification_reason="Directory or review source can usually be improved through profile and review work.",
        )

    if _domain_matches(domain, AUTHORITY_DOMAINS) or domain.endswith((".edu", ".gov")):
        return SourceClassification(
            owner_type="third_party",
            source_type="authority_reference",
            action_role="content_gap_signal",
            actionability_score=4.8,
            relevance_score=7.0,
            confidence_score=8.0,
            classification_reason="Authority source is useful for content strategy, not a direct listing target.",
        )

    if _domain_matches(domain, SOCIAL_OR_UGC_DOMAINS):
        return SourceClassification(
            owner_type="third_party",
            source_type="social_or_ugc",
            action_role="monitor_only",
            actionability_score=5.0,
            relevance_score=6.0,
            confidence_score=8.0,
            classification_reason="Social or user-generated source is useful signal but less controllable.",
        )

    competitor = _competitor_hint(domain, title, competitors)
    if competitor:
        return SourceClassification(
            owner_type="competitor_owned",
            source_type="competitor_site",
            action_role="competitive_evidence",
            actionability_score=2.5,
            relevance_score=8.5,
            confidence_score=7.5,
            classification_reason=f"Source appears to belong to or primarily describe competitor {competitor}.",
        )

    if any(hint in domain for hint in LOCAL_PUBLISHER_HINTS):
        return SourceClassification(
            owner_type="third_party",
            source_type="local_publisher",
            action_role="partnership_or_pr_target",
            actionability_score=6.8,
            relevance_score=7.5,
            confidence_score=6.5,
            classification_reason="Local or editorial publisher may be influenceable through PR/content proof.",
        )

    return SourceClassification(
        owner_type="third_party",
        source_type="unknown_review_needed",
        action_role="direct_citation_target",
        actionability_score=6.0,
        relevance_score=6.0,
        confidence_score=5.5,
        classification_reason="Third-party source needs review but may be a citation opportunity.",
    )


def score_source(
    citation_count: int,
    unique_question_count: int,
    provider_count: int,
    groups: Iterable[str],
    avg_source_rank: float | None,
    classification: SourceClassification,
    missed_query_count: int = 0,
) -> SourceScores:
    """Score source influence and opportunity on a 0-10 scale."""
    citation_score = min(citation_count / 10, 1.0)
    prompt_score = min(unique_question_count / 8, 1.0)
    provider_score = min(provider_count / 4, 1.0)
    group_score = max((GROUP_IMPACT_WEIGHT.get(group, 0.6) for group in groups), default=0.6)
    rank_score = 0.5
    if avg_source_rank:
        rank_score = max(0.15, 1.0 - min(avg_source_rank - 1, 9) / 10)

    influence = (
        0.30 * prompt_score
        + 0.20 * provider_score
        + 0.20 * group_score
        + 0.15 * citation_score
        + 0.15 * rank_score
    ) * 10

    actionability_multiplier = max(classification.actionability_score, 0.1) / 8
    missed_multiplier = 1.15 if missed_query_count else 0.95
    competitor_multiplier = 1.2 if classification.owner_type == "competitor_owned" else 1.0
    confidence_multiplier = max(classification.confidence_score, 1.0) / 10
    opportunity = influence * actionability_multiplier * missed_multiplier * competitor_multiplier * confidence_multiplier

    return SourceScores(
        influence_score=round(min(influence, 10.0), 2),
        opportunity_score=round(min(opportunity, 10.0), 2),
    )


def _extract_markdown_links(text: str) -> list[tuple[str, str]]:
    return [
        (label.strip(), clean_url(url))
        for label, url in re.findall(r"\[([^\]]{1,240})\]\((https?://[^)\s]+)\)", text or "")
    ]


def _extract_bare_urls(text: str) -> list[str]:
    return [clean_url(match.group(0)) for match in re.finditer(r"https?://[^\s<>\]\)\"']+", text or "")]


def provider_result_to_evidence_records(
    *,
    result: Any,
    provider_name: str,
    question: str,
    group: str | None,
    scan_id: str | None,
    client_id: str | None,
) -> list[dict[str, Any]]:
    """Convert a provider result into streaming JSONL-safe evidence records."""
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    excerpt = answer_excerpt(getattr(result, "response", "") or "")
    model = getattr(result, "model", None)
    provider = getattr(result, "provider", None) or provider_name
    web_search_used = getattr(result, "web_search_used", None)
    search_queries = list(getattr(result, "search_queries", []) or [])
    usage_metadata = dict(getattr(result, "usage_metadata", {}) or {})
    provider_metadata = dict(getattr(result, "safe_raw_metadata", lambda: {})() or {})

    def add_record(
        *,
        raw_url: str,
        title: str | None,
        cited_text: str | None,
        rank: int | None,
        origin: str,
        raw_metadata: Mapping[str, Any] | None = None,
    ) -> None:
        canonical = canonicalize_url(raw_url)
        if not canonical or canonical in seen:
            return
        seen.add(canonical)
        records.append(
            {
                "schema_version": 1,
                "scan_id": scan_id,
                "client_id": client_id,
                "provider": provider,
                "model": model,
                "question": question,
                "group": group,
                "answer_excerpt": excerpt,
                "web_search_used": web_search_used,
                "source": {
                    "url": raw_url,
                    "canonical_url": canonical,
                    "domain": source_domain(canonical),
                    "title": title,
                    "cited_text": cited_text,
                    "source_rank": rank,
                    "origin": origin,
                },
                "search_queries": search_queries,
                "usage_metadata": usage_metadata,
                "provider_metadata": {
                    **provider_metadata,
                    "source_metadata": dict(raw_metadata or {}),
                },
            }
        )

    for citation in getattr(result, "citations", []) or []:
        add_record(
            raw_url=getattr(citation, "url", ""),
            title=getattr(citation, "title", None),
            cited_text=getattr(citation, "cited_text", None),
            rank=getattr(citation, "source_rank", None),
            origin=getattr(citation, "origin", None) or "native_citation",
            raw_metadata=getattr(citation, "raw_metadata", {}) or {},
        )

    for search_result in getattr(result, "search_results", []) or []:
        add_record(
            raw_url=getattr(search_result, "url", ""),
            title=getattr(search_result, "title", None),
            cited_text=getattr(search_result, "snippet", None),
            rank=getattr(search_result, "result_rank", None),
            origin="native_search_result",
            raw_metadata=getattr(search_result, "raw_metadata", {}) or {},
        )

    if not records and getattr(result, "response", ""):
        rank = 0
        for title, url in _extract_markdown_links(result.response):
            rank += 1
            add_record(
                raw_url=url,
                title=title or None,
                cited_text=None,
                rank=rank,
                origin="markdown_fallback",
            )
        markdown_seen = set(seen)
        for url in _extract_bare_urls(result.response):
            canonical = canonicalize_url(url)
            if canonical and canonical not in markdown_seen:
                rank += 1
                add_record(
                    raw_url=url,
                    title=None,
                    cited_text=None,
                    rank=rank,
                    origin="bare_url",
                )

    return records


def read_source_evidence_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                records.append(item)
    return records
