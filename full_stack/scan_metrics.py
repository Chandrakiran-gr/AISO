"""
Scan metric aggregation and persistence for AISO.

This module is intentionally deterministic. It derives durable visibility
metrics from collected provider responses without making extra LLM calls, so a
scan cannot unexpectedly spend a user's BYOK quota after collection completes.
"""

from __future__ import annotations

import csv
import json
import re
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping

from full_stack.action_recommendations import build_action_recommendations
from full_stack.source_intelligence import (
    canonicalize_url,
    classify_source,
    read_source_evidence_jsonl,
    score_source,
    source_domain as canonical_source_domain,
)


@dataclass(frozen=True)
class ClientIdentity:
    """Names used to detect the focal business and competitors in responses."""

    focal_name: str
    focal_aliases: tuple[str, ...]
    competitors: tuple[str, ...]


@dataclass(frozen=True)
class AggregatedScanResult:
    """A DB-ready aggregate for one provider and one intent group."""

    provider: str
    group: str
    total_questions: int
    mention_count: int
    avg_position: float | None
    visibility_score: float
    competitor_data: dict[str, int]


@dataclass(frozen=True)
class ExtractedCitation:
    """A DB-ready source citation extracted from one provider answer."""

    provider: str
    group: str | None
    question: str | None
    answer_excerpt: str | None
    citation_url: str
    citation_title: str | None
    source_domain: str | None
    source_rank: int
    metadata: dict[str, object]
    canonical_url: str | None = None
    citation_origin: str | None = None
    cited_text: str | None = None
    web_search_used: bool | None = None
    source_type: str | None = None
    owner_type: str | None = None
    action_role: str | None = None
    actionability_score: float | None = None
    influence_score: float | None = None
    relevance_score: float | None = None
    confidence_score: float | None = None
    classification_reason: str | None = None


def _normalize_slug(raw: str) -> str:
    slug = raw.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    return slug.strip("_")


def _humanize(raw: str) -> str:
    return raw.replace("_", " ").replace("-", " ").title()


def _dedupe(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        clean = re.sub(r"\s+", " ", str(value or "")).strip()
        if not clean:
            continue
        key = clean.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(clean)
    return tuple(result)


def _name_aliases(name: str) -> tuple[str, ...]:
    clean = re.sub(r"\s+", " ", str(name or "")).strip()
    if not clean:
        return ()

    aliases = [clean]
    slug = _normalize_slug(clean)
    if slug:
        aliases.append(_humanize(slug))
        aliases.append(slug.replace("_", " "))

    first_token = re.split(r"[\s&,\-]+", clean, maxsplit=1)[0].strip()
    generic_first_tokens = {"the", "and", "spa", "company", "co", "inc", "llc"}
    if len(first_token) >= 3 and first_token.casefold() not in generic_first_tokens:
        aliases.append(first_token)

    suffix_pattern = re.compile(
        r"\b(inc|llc|ltd|co|company|corp|corporation|skincare|wellness|spa)\b\.?",
        re.IGNORECASE,
    )
    without_suffix = suffix_pattern.sub("", clean)
    without_suffix = re.sub(r"\s+", " ", without_suffix).strip(" ,-")
    if without_suffix and without_suffix.casefold() != clean.casefold():
        aliases.append(without_suffix)

    return _dedupe(aliases)


def _load_json(path: Path) -> Mapping[str, object]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def load_client_identity(
    client_folder: Path,
    fallback_name: str | None = None,
    fallback_competitors: Iterable[str] | None = None,
) -> ClientIdentity:
    """
    Load focal and competitor names from the client folder.

    setup2 writes client_profile.json; older flows may write config.json or
    datafile.json. Fallbacks let API callers supply DB values if files are
    incomplete.
    """
    profile = _load_json(client_folder / "client_profile.json")
    config = _load_json(client_folder / "config.json")
    datafile = _load_json(client_folder / "datafile.json")

    focal_name = (
        str(profile.get("display_name") or "")
        or str(profile.get("name") or "")
        or str(config.get("display_name") or "")
        or str(config.get("name") or "")
        or str(config.get("business_name") or "")
        or str(datafile.get("display_name") or "")
        or str(datafile.get("business_name") or "")
        or str(fallback_name or "")
        or _humanize(client_folder.name)
    )

    raw_competitors: list[str] = []
    for source in (profile, config, datafile):
        value = source.get("competitors")
        if isinstance(value, list):
            raw_competitors.extend(str(v) for v in value)
        elif isinstance(value, str):
            raw_competitors.extend(v.strip() for v in value.split(","))
    if fallback_competitors:
        raw_competitors.extend(str(v) for v in fallback_competitors)

    competitors = _dedupe(
        c for c in raw_competitors if c.casefold() != focal_name.casefold()
    )
    aliases = _dedupe([focal_name, *_name_aliases(focal_name)])
    return ClientIdentity(
        focal_name=focal_name,
        focal_aliases=aliases,
        competitors=competitors,
    )


def _compile_aliases(aliases: Iterable[str]) -> list[re.Pattern[str]]:
    patterns: list[re.Pattern[str]] = []
    for alias in aliases:
        clean = re.sub(r"\s+", " ", alias).strip()
        if len(clean) < 2:
            continue
        escaped = re.escape(clean)
        escaped = escaped.replace(r"\ ", r"[\s\-_&]+")
        patterns.append(
            re.compile(rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])", re.IGNORECASE)
        )
    return patterns


def _first_position(text: str, aliases: Iterable[str]) -> int | None:
    if not text:
        return None
    positions: list[int] = []
    for pattern in _compile_aliases(aliases):
        match = pattern.search(text)
        if match:
            positions.append(match.start())
    return min(positions) if positions else None


def _mention_rank(
    response_text: str,
    focal_aliases: Iterable[str],
    competitors: Iterable[str],
) -> int | None:
    focal_pos = _first_position(response_text, focal_aliases)
    if focal_pos is None:
        return None

    competitors_before = 0
    for competitor in competitors:
        comp_pos = _first_position(response_text, _name_aliases(competitor))
        if comp_pos is not None and comp_pos < focal_pos:
            competitors_before += 1
    return competitors_before + 1


def read_collect_csv(csv_path: Path) -> tuple[list[dict[str, str]], list[str]]:
    """Read a collect.py CSV and return rows plus header fields."""
    with open(csv_path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return list(reader), list(reader.fieldnames or [])


def _clean_url(raw_url: str) -> str:
    url = str(raw_url or "").strip().strip("<>\"'")
    return url.rstrip(".,;:!?)]+}")


def _normalize_url(raw_url: str) -> str | None:
    return canonicalize_url(raw_url)


def _source_domain(raw_url: str) -> str | None:
    return canonical_source_domain(raw_url)


def _answer_excerpt(text: str, limit: int = 420) -> str | None:
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    if not clean:
        return None
    return clean if len(clean) <= limit else clean[: limit - 1].rstrip() + "…"


def _extract_markdown_links(text: str) -> list[tuple[str, str]]:
    return [
        (label.strip(), _clean_url(url))
        for label, url in re.findall(r"\[([^\]]{1,240})\]\((https?://[^)\s]+)\)", text)
    ]


def _extract_bare_urls(text: str) -> list[str]:
    return [
        _clean_url(match.group(0))
        for match in re.finditer(r"https?://[^\s<>\]\)\"']+", text)
    ]


def extract_scan_citations(
    rows: list[Mapping[str, str]],
    fieldnames: list[str],
    identity: ClientIdentity | None = None,
    client_domain: str | None = None,
) -> list[ExtractedCitation]:
    """
    Extract source URLs from provider responses.

    Duplicates are removed only within one answer. Repeated citations across
    questions, providers, or scans remain as durable signal.
    """
    provider_names = [
        name.removeprefix("response_")
        for name in fieldnames
        if name.startswith("response_")
    ]
    citations: list[ExtractedCitation] = []

    for row in rows:
        group = str(row.get("group") or "") or None
        question = str(row.get("question") or "") or None
        for provider in provider_names:
            response_text = str(row.get(f"response_{provider}") or "")
            if not response_text.strip():
                continue

            candidates: list[tuple[str | None, str, str]] = []
            for title, url in _extract_markdown_links(response_text):
                candidates.append((title or None, url, "markdown"))
            markdown_normalized = {
                normalized
                for _, url, _ in candidates
                if (normalized := _normalize_url(url))
            }
            for url in _extract_bare_urls(response_text):
                normalized = _normalize_url(url)
                if normalized and normalized not in markdown_normalized:
                    candidates.append((None, url, "bare_url"))

            seen_in_answer: set[str] = set()
            source_rank = 0
            for title, url, citation_type in candidates:
                normalized = _normalize_url(url)
                if not normalized or normalized in seen_in_answer:
                    continue
                seen_in_answer.add(normalized)
                source_rank += 1

                domain = _source_domain(normalized)
                clean_title = title
                if clean_title and clean_title.strip().isdigit():
                    clean_title = None
                classification = classify_source(
                    normalized,
                    title=clean_title,
                    client_domain=client_domain,
                    competitors=identity.competitors if identity else (),
                )
                citations.append(
                    ExtractedCitation(
                        provider=provider,
                        group=group,
                        question=question,
                        answer_excerpt=_answer_excerpt(response_text),
                        citation_url=normalized,
                        citation_title=clean_title,
                        source_domain=domain,
                        source_rank=source_rank,
                        metadata={
                            "citation_type": citation_type,
                            "normalized_url": normalized,
                        },
                        canonical_url=normalized,
                        citation_origin=f"{citation_type}_fallback",
                        source_type=classification.source_type,
                        owner_type=classification.owner_type,
                        action_role=classification.action_role,
                        actionability_score=classification.actionability_score,
                        relevance_score=classification.relevance_score,
                        confidence_score=classification.confidence_score,
                        classification_reason=classification.classification_reason,
                    )
                )

    return citations


def extract_source_evidence_citations(
    evidence_records: list[Mapping[str, object]],
    identity: ClientIdentity,
    client_domain: str | None = None,
) -> list[ExtractedCitation]:
    """Convert structured source evidence JSONL rows into DB-ready citations."""
    citations: list[ExtractedCitation] = []
    for item in evidence_records:
        source = item.get("source")
        if not isinstance(source, Mapping):
            continue
        raw_url = str(source.get("url") or source.get("canonical_url") or "")
        canonical = canonicalize_url(str(source.get("canonical_url") or raw_url))
        if not canonical:
            continue
        title = str(source.get("title") or "").strip() or None
        rank_raw = source.get("source_rank")
        try:
            source_rank = int(rank_raw) if rank_raw is not None else 1
        except (TypeError, ValueError):
            source_rank = 1
        classification = classify_source(
            canonical,
            title=title,
            client_domain=client_domain,
            competitors=identity.competitors,
        )
        metadata = {
            "schema_version": item.get("schema_version"),
            "search_queries": item.get("search_queries") or [],
            "usage_metadata": item.get("usage_metadata") or {},
            "provider_metadata": item.get("provider_metadata") or {},
        }
        citations.append(
            ExtractedCitation(
                provider=str(item.get("provider") or "unknown"),
                group=str(item.get("group") or "") or None,
                question=str(item.get("question") or "") or None,
                answer_excerpt=str(item.get("answer_excerpt") or "") or None,
                citation_url=canonical,
                citation_title=title,
                source_domain=canonical_source_domain(canonical),
                source_rank=source_rank,
                metadata=metadata,
                canonical_url=canonical,
                citation_origin=str(source.get("origin") or "native_citation"),
                cited_text=str(source.get("cited_text") or "") or None,
                web_search_used=bool(item.get("web_search_used")) if item.get("web_search_used") is not None else None,
                source_type=classification.source_type,
                owner_type=classification.owner_type,
                action_role=classification.action_role,
                actionability_score=classification.actionability_score,
                relevance_score=classification.relevance_score,
                confidence_score=classification.confidence_score,
                classification_reason=classification.classification_reason,
            )
        )
    return citations


def find_source_evidence_path(csv_path: Path) -> Path | None:
    """Return the source evidence JSONL path paired with a collect CSV, if present."""
    direct_name = csv_path.name.replace("_aisodata_", "_source_evidence_")
    direct = csv_path.with_name(Path(direct_name).with_suffix(".jsonl").name)
    if direct.exists():
        return direct
    candidates = sorted(
        csv_path.parent.glob("*_source_evidence_*.jsonl"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def _client_domain_from_folder(client_folder: Path) -> str | None:
    for filename in ("client_profile.json", "config.json", "datafile.json"):
        data = _load_json(client_folder / filename)
        for key in ("url", "website_url", "website", "business_url"):
            value = str(data.get(key) or "").strip()
            if value:
                domain = canonical_source_domain(value if value.startswith(("http://", "https://")) else f"https://{value}")
                if domain:
                    return domain
    return None


def _citation_text(citation: ExtractedCitation) -> str:
    return " ".join(
        value
        for value in (
            citation.citation_title,
            citation.cited_text,
            citation.answer_excerpt,
            citation.question,
            citation.citation_url,
        )
        if value
    )


def _citation_mentions_client(citation: ExtractedCitation, identity: ClientIdentity, client_domain: str | None) -> bool:
    if client_domain and citation.source_domain == client_domain:
        return True
    return _first_position(_citation_text(citation), identity.focal_aliases) is not None


def _citation_competitors(citation: ExtractedCitation, identity: ClientIdentity) -> list[str]:
    text = _citation_text(citation)
    return [
        competitor
        for competitor in identity.competitors
        if _first_position(text, _name_aliases(competitor)) is not None
    ]


def _source_profile_payloads(
    citations: list[ExtractedCitation],
    identity: ClientIdentity,
    client_domain: str | None,
) -> dict[str, dict[str, object]]:
    buckets: dict[str, dict[str, object]] = {}
    for citation in citations:
        canonical = citation.canonical_url or canonicalize_url(citation.citation_url)
        if not canonical:
            continue
        bucket = buckets.setdefault(
            canonical,
            {
                "citations": [],
                "questions": set(),
                "providers": set(),
                "groups": set(),
                "ranks": [],
                "competitors": set(),
            },
        )
        bucket["citations"].append(citation)
        if citation.question:
            bucket["questions"].add(citation.question)
        bucket["providers"].add(citation.provider)
        if citation.group:
            bucket["groups"].add(citation.group)
        if citation.source_rank:
            bucket["ranks"].append(citation.source_rank)
        for competitor in _citation_competitors(citation, identity):
            bucket["competitors"].add(competitor)

    payloads: dict[str, dict[str, object]] = {}
    for canonical, bucket in buckets.items():
        bucket_citations: list[ExtractedCitation] = bucket["citations"]  # type: ignore[assignment]
        first = bucket_citations[0]
        groups = sorted(bucket["groups"])  # type: ignore[arg-type]
        ranks = list(bucket["ranks"])  # type: ignore[arg-type]
        classification = classify_source(
            canonical,
            title=first.citation_title,
            client_domain=client_domain,
            competitors=identity.competitors,
        )
        scores = score_source(
            citation_count=len(bucket_citations),
            unique_question_count=len(bucket["questions"]),  # type: ignore[arg-type]
            provider_count=len(bucket["providers"]),  # type: ignore[arg-type]
            groups=groups,
            avg_source_rank=(sum(ranks) / len(ranks)) if ranks else None,
            classification=classification,
        )
        client_mentioned = any(_citation_mentions_client(citation, identity, client_domain) for citation in bucket_citations)
        competitors_mentioned = sorted(bucket["competitors"])  # type: ignore[arg-type]
        payloads[canonical] = {
            "canonical_url": canonical,
            "source_domain": first.source_domain or canonical_source_domain(canonical),
            "source_title": first.citation_title,
            "owner_type": classification.owner_type,
            "source_type": classification.source_type,
            "action_role": classification.action_role,
            "actionability_score": classification.actionability_score,
            "influence_score": scores.influence_score,
            "relevance_score": classification.relevance_score,
            "client_mentioned": client_mentioned,
            "competitors_mentioned": competitors_mentioned,
            "topics": groups,
            "classification_reason": classification.classification_reason,
            "metadata": {
                "citation_count": len(bucket_citations),
                "unique_question_count": len(bucket["questions"]),  # type: ignore[arg-type]
                "provider_count": len(bucket["providers"]),  # type: ignore[arg-type]
                "providers": sorted(bucket["providers"]),  # type: ignore[arg-type]
                "example_questions": sorted(bucket["questions"])[:5],  # type: ignore[arg-type]
                "top_urls": [citation.citation_url for citation in bucket_citations[:5]],
                "confidence_score": classification.confidence_score,
                "opportunity_score": scores.opportunity_score,
            },
        }
    return payloads


def aggregate_scan_results(
    rows: list[Mapping[str, str]],
    fieldnames: list[str],
    identity: ClientIdentity,
) -> list[AggregatedScanResult]:
    """Aggregate per-provider, per-group visibility metrics from collect rows."""
    provider_names = [
        name.removeprefix("response_")
        for name in fieldnames
        if name.startswith("response_")
    ]
    if not provider_names:
        return []

    buckets: dict[tuple[str, str], dict[str, object]] = {}

    for row in rows:
        group = str(row.get("group") or "all")
        for provider in provider_names:
            key = (provider, group)
            bucket = buckets.setdefault(
                key,
                {
                    "total": 0,
                    "mentions": 0,
                    "positions": [],
                    "competitors": defaultdict(int),
                },
            )
            bucket["total"] = int(bucket["total"]) + 1

            response_text = str(row.get(f"response_{provider}") or "")
            rank = _mention_rank(
                response_text,
                identity.focal_aliases,
                identity.competitors,
            )
            if rank is not None:
                bucket["mentions"] = int(bucket["mentions"]) + 1
                positions = bucket["positions"]
                assert isinstance(positions, list)
                positions.append(rank)

            competitor_counts = bucket["competitors"]
            assert isinstance(competitor_counts, defaultdict)
            for competitor in identity.competitors:
                if _first_position(response_text, _name_aliases(competitor)) is not None:
                    competitor_counts[competitor] += 1

    results: list[AggregatedScanResult] = []
    for (provider, group), bucket in sorted(buckets.items()):
        total = int(bucket["total"])
        mentions = int(bucket["mentions"])
        positions = bucket["positions"]
        assert isinstance(positions, list)
        avg_position = round(sum(positions) / len(positions), 2) if positions else None
        visibility_score = round((mentions / total) * 100, 2) if total else 0.0
        competitor_counts = bucket["competitors"]
        assert isinstance(competitor_counts, defaultdict)

        results.append(
            AggregatedScanResult(
                provider=provider,
                group=group,
                total_questions=total,
                mention_count=mentions,
                avg_position=avg_position,
                visibility_score=visibility_score,
                competitor_data=dict(sorted(competitor_counts.items())),
            )
        )

    return results


def aggregate_collect_csv(
    csv_path: Path,
    client_folder: Path,
    fallback_name: str | None = None,
    fallback_competitors: Iterable[str] | None = None,
) -> list[AggregatedScanResult]:
    """Convenience wrapper for CSV read + identity load + aggregation."""
    rows, fieldnames = read_collect_csv(csv_path)
    identity = load_client_identity(
        client_folder,
        fallback_name=fallback_name,
        fallback_competitors=fallback_competitors,
    )
    return aggregate_scan_results(rows, fieldnames, identity)


def persist_collect_csv_results(
    csv_path: Path,
    scan_id: str,
    client_id: str,
    client_folder: Path,
    fallback_name: str | None = None,
    fallback_competitors: Iterable[str] | None = None,
) -> list[AggregatedScanResult]:
    """
    Persist collect.py metrics into scan_results.

    Writes are idempotent for a scan_id: existing rows for the scan are removed
    before inserting the freshly aggregated result set.
    """
    rows, fieldnames = read_collect_csv(csv_path)
    identity = load_client_identity(
        client_folder,
        fallback_name=fallback_name,
        fallback_competitors=fallback_competitors,
    )
    results = aggregate_scan_results(rows, fieldnames, identity)
    if not results:
        return []
    client_domain = _client_domain_from_folder(client_folder)
    evidence_path = find_source_evidence_path(csv_path)
    evidence_records = read_source_evidence_jsonl(evidence_path) if evidence_path else []
    citations = (
        extract_source_evidence_citations(evidence_records, identity, client_domain)
        if evidence_records
        else extract_scan_citations(rows, fieldnames, identity=identity, client_domain=client_domain)
    )
    source_profiles = _source_profile_payloads(citations, identity, client_domain)

    from api.database import Action, ScanArtifact, ScanCitation, ScanResult, SessionLocal, SourceProfile
    from api.storage import describe_configured_artifact

    db = SessionLocal()
    try:
        db.query(ScanResult).filter(ScanResult.scan_id == scan_id).delete()
        db.query(Action).filter(Action.scan_id == scan_id).delete()
        # Only CSV artifacts are registered. JSON/JSONL files are used
        # internally for citation extraction but must not be shown to users.
        registered_artifact_types = [
            "question_bank_csv",
            "collect_questions_csv",
            "collect_csv",
        ]
        db.query(ScanArtifact).filter(
            ScanArtifact.scan_id == scan_id,
            ScanArtifact.artifact_type.in_(registered_artifact_types),
        ).delete()
        db.query(ScanCitation).filter(ScanCitation.scan_id == scan_id).delete()
        for result in results:
            db.add(
                ScanResult(
                    id=str(uuid.uuid4()),
                    scan_id=scan_id,
                    client_id=client_id,
                    provider=result.provider,
                    group=result.group,
                    total_questions=result.total_questions,
                    mention_count=result.mention_count,
                    avg_position=result.avg_position,
                    visibility_score=result.visibility_score,
                    competitor_data=result.competitor_data,
                )
            )
        # Only register CSV artifacts. JSON/JSONL files (question_ranking_report.json,
        # source_evidence_jsonl) are used internally for analysis but must not be
        # saved as downloadable artifact records shown to users.
        artifact_specs: list[tuple[Path, str, str]] = [
            (
                client_folder / "query_template_bank.csv",
                "question_bank_csv",
                "Final selected question bank used by collect.py.",
            ),
        ]
        collect_question_name = csv_path.name.replace("_aisodata_", "_collect_questions_")
        if collect_question_name != csv_path.name:
            artifact_specs.append(
                (
                    csv_path.with_name(collect_question_name),
                    "collect_questions_csv",
                    "Questions selected for this scan run.",
                )
            )
        artifact_specs.append(
            (
                csv_path,
                "collect_csv",
                "Raw provider responses used to aggregate scan metrics.",
            )
        )

        for artifact_path, artifact_type, description in artifact_specs:
            if not artifact_path.exists():
                continue
            artifact = describe_configured_artifact(
                artifact_path,
                artifact_type=artifact_type,
                client_name=identity.focal_name,
                client_id=client_id,
                scan_id=scan_id,
                metadata={
                    "source": "full_stack.collect",
                    "description": description,
                    **({"schema_version": 1} if artifact_type == "source_evidence_jsonl" else {}),
                },
            )
            db.add(
                ScanArtifact(
                    id=str(uuid.uuid4()),
                    scan_id=scan_id,
                    client_id=client_id,
                    **artifact,
                )
            )

        profile_ids_by_url: dict[str, str] = {}
        now = datetime.now(timezone.utc)
        for canonical_url, payload in source_profiles.items():
            profile = db.query(SourceProfile).filter(
                SourceProfile.client_id == client_id,
                SourceProfile.canonical_url == canonical_url,
            ).first()
            if not profile:
                profile = SourceProfile(
                    id=str(uuid.uuid4()),
                    client_id=client_id,
                    canonical_url=canonical_url,
                    created_at=now,
                )
                db.add(profile)
            profile.source_domain = str(payload.get("source_domain") or "") or None
            profile.source_title = str(payload.get("source_title") or "") or None
            profile.owner_type = str(payload.get("owner_type") or "") or None
            profile.source_type = str(payload.get("source_type") or "") or None
            profile.action_role = str(payload.get("action_role") or "") or None
            profile.actionability_score = payload.get("actionability_score")  # type: ignore[assignment]
            profile.influence_score = payload.get("influence_score")  # type: ignore[assignment]
            profile.relevance_score = payload.get("relevance_score")  # type: ignore[assignment]
            profile.client_mentioned = bool(payload.get("client_mentioned"))
            profile.competitors_mentioned_json = payload.get("competitors_mentioned") or []
            profile.topics_json = payload.get("topics") or []
            profile.fetch_status = profile.fetch_status or "metadata_only"
            profile.classification_reason = str(payload.get("classification_reason") or "") or None
            profile.metadata_json = payload.get("metadata") or {}
            profile.updated_at = now
            profile_ids_by_url[canonical_url] = profile.id

        # source_profiles must be INSERTed before the scan_citations that FK to
        # them (scan_citations.source_profile_id -> source_profiles). These models
        # have no ORM relationship on that column, so within a single flush the
        # unit of work orders inserts by table name — emitting scan_citations
        # before source_profiles and tripping the FK. Persist the parents first.
        db.flush()

        for citation in citations:
            canonical = citation.canonical_url or canonicalize_url(citation.citation_url)
            db.add(
                ScanCitation(
                    id=str(uuid.uuid4()),
                    scan_id=scan_id,
                    client_id=client_id,
                    source_profile_id=profile_ids_by_url.get(canonical or ""),
                    provider=citation.provider,
                    group=citation.group,
                    question=citation.question,
                    answer_excerpt=citation.answer_excerpt,
                    citation_url=citation.citation_url,
                    citation_title=citation.citation_title,
                    source_domain=citation.source_domain,
                    source_rank=citation.source_rank,
                    canonical_url=canonical,
                    citation_origin=citation.citation_origin,
                    cited_text=citation.cited_text,
                    web_search_used=citation.web_search_used,
                    source_type=citation.source_type,
                    owner_type=citation.owner_type,
                    action_role=citation.action_role,
                    actionability_score=citation.actionability_score,
                    influence_score=source_profiles.get(canonical or "", {}).get("influence_score"),  # type: ignore[arg-type]
                    relevance_score=citation.relevance_score,
                    confidence_score=citation.confidence_score,
                    classification_reason=citation.classification_reason,
                    metadata_json=citation.metadata,
                )
            )
        for action in build_action_recommendations(results, citations):
            db.add(
                Action(
                    id=str(uuid.uuid4()),
                    scan_id=scan_id,
                    client_id=client_id,
                    **action,
                )
            )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    return results
