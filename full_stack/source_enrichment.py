"""Bounded source-page enrichment for AISO source intelligence.

This module intentionally does not crawl broadly. It fetches only the top
source profiles already observed in a completed scan, extracts compact public
signals, and updates the durable source graph. Scan completion must not depend
on enrichment success.
"""

from __future__ import annotations

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from api import database as database_module
from api.website_ingestion import FetchResult, IngestionConfig, extract_html_evidence, fetch_public_page
from full_stack.source_intelligence import classify_source, source_domain


FetchSourcePage = Callable[[str, IngestionConfig], FetchResult]


@dataclass(frozen=True)
class SourceEnrichmentConfig:
    enabled: bool = True
    max_sources: int = 20
    timeout_seconds: float = 5.0
    max_bytes: int = 1_000_000
    concurrency: int = 3

    @classmethod
    def from_env(cls) -> "SourceEnrichmentConfig":
        return cls(
            enabled=_env_bool("AISO_SOURCE_ENRICHMENT_ENABLED", True),
            max_sources=_env_int("AISO_SOURCE_ENRICHMENT_MAX_SOURCES", 20),
            timeout_seconds=_env_float("AISO_SOURCE_ENRICHMENT_TIMEOUT_SEC", 5.0),
            max_bytes=_env_int("AISO_SOURCE_ENRICHMENT_MAX_BYTES", 1_000_000),
            concurrency=_env_int("AISO_SOURCE_ENRICHMENT_CONCURRENCY", 3),
        )


@dataclass(frozen=True)
class SourceEnrichmentSummary:
    attempted: int
    enriched: int
    failed: int
    skipped: int
    enabled: bool


@dataclass(frozen=True)
class _PendingSourceProfile:
    id: str
    canonical_url: str
    source_title: str | None
    client_mentioned: bool
    competitors_mentioned_json: str | None
    metadata_json: str | None


@dataclass(frozen=True)
class _EnrichedSourceProfile:
    id: str
    source_title: str | None
    owner_type: str | None
    source_type: str | None
    action_role: str | None
    actionability_score: float | None
    relevance_score: float | None
    client_mentioned: bool | None
    competitors_mentioned: list[str]
    fetch_status: str
    classification_reason: str | None
    metadata: dict[str, object]
    fetched_at: datetime
    ok: bool


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(0, int(raw))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(0.1, float(raw))
    except ValueError:
        return default


def _json_loads(value: str | None, fallback: object) -> object:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _competitors_from_client(client: database_module.Client) -> list[str]:
    value = _json_loads(client.competitors, [])
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return []


def _contains_name(text: str, name: str) -> bool:
    clean = re.sub(r"\s+", " ", name or "").strip()
    if len(clean) < 2:
        return False
    return re.search(rf"(?<![A-Za-z0-9]){re.escape(clean)}(?![A-Za-z0-9])", text, re.IGNORECASE) is not None


def _mentions_any(text: str, names: list[str]) -> list[str]:
    return [name for name in names if _contains_name(text, name)]


def _compact_text(evidence: dict[str, object]) -> str:
    pieces: list[str] = []
    for key in ("title",):
        value = evidence.get(key)
        if isinstance(value, str):
            pieces.append(value)
    for key, limit in (("headings", 12), ("text_blocks", 24)):
        values = evidence.get(key)
        if isinstance(values, list):
            pieces.extend(str(item) for item in values[:limit])
    return re.sub(r"\s+", " ", " ".join(pieces)).strip()


def _compact_metadata(
    *,
    existing_metadata: dict[str, object],
    evidence: dict[str, object],
    fetch_result: FetchResult,
    enriched_at: datetime,
) -> dict[str, object]:
    headings = evidence.get("headings") if isinstance(evidence.get("headings"), list) else []
    text_blocks = evidence.get("text_blocks") if isinstance(evidence.get("text_blocks"), list) else []
    metadata = dict(existing_metadata)
    metadata["enrichment"] = {
        "source": "static_http",
        "final_url": fetch_result.final_url,
        "status_code": fetch_result.status_code,
        "content_type": fetch_result.content_type,
        "title": evidence.get("title") or None,
        "headings": [str(item) for item in headings[:8]],
        "text_snippets": [str(item) for item in text_blocks[:8]],
        "stop_reason": evidence.get("stop_reason") or None,
        "enriched_at": enriched_at.isoformat(),
    }
    return metadata


def _priority_score(profile: database_module.SourceProfile) -> float:
    influence = float(profile.influence_score or 0)
    actionability = float(profile.actionability_score or 0)
    relevance = float(profile.relevance_score or 0)
    return (0.55 * influence) + (0.35 * actionability) + (0.10 * relevance)


def _fetch_and_extract(
    pending: _PendingSourceProfile,
    *,
    client_name: str,
    client_domain: str | None,
    competitors: list[str],
    names_to_find: list[str],
    ingestion_config: IngestionConfig,
    fetch_page: FetchSourcePage,
) -> _EnrichedSourceProfile:
    now = datetime.now(timezone.utc)
    try:
        result = fetch_page(pending.canonical_url, ingestion_config)
        evidence = extract_html_evidence(result.text, result.final_url)
        page_text = _compact_text(evidence)
        client_mentioned = _contains_name(page_text, client_name) or pending.client_mentioned
        existing_competitors = _json_loads(pending.competitors_mentioned_json, [])
        competitors_mentioned = sorted(
            set(_mentions_any(page_text, competitors))
            | set(existing_competitors if isinstance(existing_competitors, list) else [])
        )
        title = str(evidence.get("title") or pending.source_title or "").strip() or None
        classification = classify_source(
            pending.canonical_url,
            title=title,
            client_domain=client_domain,
            competitors=competitors,
        )
        existing_metadata = _json_loads(pending.metadata_json, {})
        metadata = _compact_metadata(
            existing_metadata=existing_metadata if isinstance(existing_metadata, dict) else {},
            evidence=evidence,
            fetch_result=result,
            enriched_at=now,
        )
        metadata["mentions"] = {
            "client": client_mentioned,
            "competitors": competitors_mentioned,
            "names_checked": names_to_find,
        }
        return _EnrichedSourceProfile(
            id=pending.id,
            source_title=title,
            owner_type=classification.owner_type,
            source_type=classification.source_type,
            action_role=classification.action_role,
            actionability_score=classification.actionability_score,
            relevance_score=classification.relevance_score,
            client_mentioned=client_mentioned,
            competitors_mentioned=competitors_mentioned,
            fetch_status="stopped" if evidence.get("stop_reason") else "fetched",
            classification_reason=classification.classification_reason,
            metadata=metadata,
            fetched_at=now,
            ok=True,
        )
    except Exception as exc:  # noqa: BLE001 - enrichment is best-effort per source
        existing_metadata = _json_loads(pending.metadata_json, {})
        metadata = existing_metadata if isinstance(existing_metadata, dict) else {}
        metadata["enrichment"] = {
            "source": "static_http",
            "error": str(exc)[:240],
            "enriched_at": now.isoformat(),
        }
        return _EnrichedSourceProfile(
            id=pending.id,
            source_title=pending.source_title,
            owner_type=None,
            source_type=None,
            action_role=None,
            actionability_score=None,
            relevance_score=None,
            client_mentioned=None,
            competitors_mentioned=[],
            fetch_status="failed",
            classification_reason=None,
            metadata=metadata,
            fetched_at=now,
            ok=False,
        )


def enrich_source_profiles_for_scan(
    scan_id: str,
    client_id: str,
    *,
    config: SourceEnrichmentConfig | None = None,
    fetch_page: FetchSourcePage = fetch_public_page,
) -> SourceEnrichmentSummary:
    """Fetch and enrich the top source profiles for one completed scan.

    This function is idempotent for source profile rows: it updates compact
    metadata and status fields but never creates duplicate profiles.
    """
    config = config or SourceEnrichmentConfig.from_env()
    if not config.enabled or config.max_sources <= 0:
        return SourceEnrichmentSummary(attempted=0, enriched=0, failed=0, skipped=0, enabled=False)

    db = database_module.SessionLocal()
    attempted = enriched = failed = skipped = 0
    try:
        client = db.query(database_module.Client).filter(
            database_module.Client.id == client_id,
        ).first()
        if not client:
            return SourceEnrichmentSummary(attempted=0, enriched=0, failed=0, skipped=0, enabled=True)

        profile_ids = {
            profile_id
            for (profile_id,) in db.query(database_module.ScanCitation.source_profile_id).filter(
                database_module.ScanCitation.scan_id == scan_id,
                database_module.ScanCitation.client_id == client_id,
                database_module.ScanCitation.source_profile_id.isnot(None),
            ).all()
            if profile_id
        }
        if not profile_ids:
            return SourceEnrichmentSummary(attempted=0, enriched=0, failed=0, skipped=0, enabled=True)

        profiles = db.query(database_module.SourceProfile).filter(
            database_module.SourceProfile.client_id == client_id,
            database_module.SourceProfile.id.in_(profile_ids),
        ).all()
        profiles.sort(key=_priority_score, reverse=True)
        selected = profiles[: config.max_sources]
        skipped = max(0, len(profiles) - len(selected))
        pending_profiles = [
            _PendingSourceProfile(
                id=profile.id,
                canonical_url=profile.canonical_url,
                source_title=profile.source_title,
                client_mentioned=bool(profile.client_mentioned),
                competitors_mentioned_json=profile.competitors_mentioned_json,
                metadata_json=profile.metadata_json,
            )
            for profile in selected
        ]
        competitors = _competitors_from_client(client)
        client_url = client.url if str(client.url or "").startswith(("http://", "https://")) else f"https://{client.url}"
        client_domain = source_domain(client_url)
        names_to_find = [client.name, *competitors]
        ingestion_config = IngestionConfig(
            max_pages=1,
            max_depth=0,
            max_bytes=config.max_bytes,
            timeout_seconds=config.timeout_seconds,
            max_redirects=3,
        )

        for profile in selected:
            profile.fetch_status = "fetching"
        db.commit()

        max_workers = max(1, min(config.concurrency, len(pending_profiles) or 1))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(
                    _fetch_and_extract,
                    pending,
                    client_name=client.name,
                    client_domain=client_domain,
                    competitors=competitors,
                    names_to_find=names_to_find,
                    ingestion_config=ingestion_config,
                    fetch_page=fetch_page,
                )
                for pending in pending_profiles
            ]
            for future in as_completed(futures):
                attempted += 1
                update = future.result()
                profile = db.query(database_module.SourceProfile).filter(
                    database_module.SourceProfile.id == update.id,
                    database_module.SourceProfile.client_id == client_id,
                ).first()
                if not profile:
                    skipped += 1
                    continue
                if update.ok:
                    profile.source_title = update.source_title or profile.source_title
                    profile.owner_type = update.owner_type
                    profile.source_type = update.source_type
                    profile.action_role = update.action_role
                    profile.actionability_score = update.actionability_score
                    profile.relevance_score = update.relevance_score
                    profile.client_mentioned = update.client_mentioned
                    profile.competitors_mentioned_json = json.dumps(update.competitors_mentioned)
                    profile.classification_reason = update.classification_reason
                    enriched += 1
                else:
                    failed += 1
                profile.fetch_status = update.fetch_status
                profile.last_fetched_at = update.fetched_at
                profile.last_enriched_at = update.fetched_at
                profile.metadata_json = json.dumps(update.metadata)
                profile.updated_at = update.fetched_at
                db.commit()

        return SourceEnrichmentSummary(
            attempted=attempted,
            enriched=enriched,
            failed=failed,
            skipped=skipped,
            enabled=True,
        )
    finally:
        db.close()
