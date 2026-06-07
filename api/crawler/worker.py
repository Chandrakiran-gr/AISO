"""Crawl worker for onboarding website discovery.

The worker intentionally reuses the hardened public ingestion path and the
client-context profile builder. That keeps Step 2 aligned with the scan
question-generation context and avoids maintaining two competing scrapers.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from api.client_context_service import build_context_profile
from api.crawler.artifacts import build_crawl_artifacts
from api.crawler.models import (
    CrawlBusinessProfile,
    CrawlJob,
    CrawlPage,
    ExtractionEvidence,
    KBChunk,
    OnboardingWorkspace,
)
from api.crawler.policy import classify_page_type
from api.crawler.url_utils import extract_domain, normalize_url
from api.database import BusinessProfile, Client, ClientContext, SessionLocal
from api.website_ingestion import FetchPage, IngestionConfig, discover_website

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _positive_int_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return max(1, value)


def _non_negative_float_env(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return max(0.0, value)


def _bounded_ingestion_config(job: CrawlJob) -> IngestionConfig:
    """Bound crawler scope even if a direct API caller requests a huge crawl."""
    max_pages_cap = _positive_int_env("AISO_CRAWLER_MAX_PAGES", 25)
    max_depth_cap = _positive_int_env("AISO_CRAWLER_MAX_DEPTH", 3)
    max_playwright_pages = _positive_int_env("AISO_CRAWLER_MAX_PLAYWRIGHT_PAGES", 5)
    return IngestionConfig(
        max_pages=max(1, min(job.max_pages, max_pages_cap)),
        max_depth=max(0, min(job.max_depth, max_depth_cap)),
        total_timeout_seconds=_non_negative_float_env("AISO_CRAWLER_TOTAL_TIMEOUT_SECONDS", 60.0),
        allow_playwright_fallback=bool(job.allow_playwright_fallback),
        max_playwright_pages=max(1, min(max_playwright_pages, 5)),
    )


def _safe_name_list(items: Any, *, limit: int = 50) -> list[str]:
    if not isinstance(items, list):
        return []
    names: list[str] = []
    for item in items:
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip()
        else:
            name = str(item or "").strip()
        if name and name not in names:
            names.append(name)
        if len(names) >= limit:
            break
    return names


def _flatten_locations(profile: dict[str, Any]) -> list[str]:
    locations = profile.get("locations")
    if not isinstance(locations, dict):
        return []
    result: list[str] = []
    for key in ("physical_locations", "service_areas", "visibility_markets"):
        result.extend(_safe_name_list(locations.get(key), limit=20))
    return result


def _build_description(profile: dict[str, Any]) -> str | None:
    differentiators = profile.get("differentiators")
    if isinstance(differentiators, list):
        for item in differentiators:
            if isinstance(item, dict) and item.get("name"):
                return str(item["name"])
    goals = profile.get("goals")
    if isinstance(goals, list):
        for item in goals:
            if isinstance(item, dict) and item.get("name"):
                return str(item["name"])
    return None


def _important_pages(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    pages = evidence.get("pages") if isinstance(evidence, dict) else []
    result: list[dict[str, Any]] = []
    for page in pages if isinstance(pages, list) else []:
        if not isinstance(page, dict):
            continue
        url = str(page.get("url") or "")
        title = str(page.get("title") or "")
        result.append(
            {
                "url": url,
                "title": title,
                "page_type": classify_page_type(url, title),
                "status_code": page.get("status_code"),
            }
        )
    return result[:30]


def _collect_social_links(evidence: dict[str, Any]) -> list[str]:
    pages = evidence.get("pages") if isinstance(evidence, dict) else []
    social_domains = (
        "facebook.com",
        "instagram.com",
        "linkedin.com",
        "tiktok.com",
        "youtube.com",
        "x.com",
        "twitter.com",
    )
    links: list[str] = []
    for page in pages if isinstance(pages, list) else []:
        if not isinstance(page, dict):
            continue
        for link in page.get("links", []) if isinstance(page.get("links"), list) else []:
            if not isinstance(link, dict):
                continue
            href = str(link.get("href") or "")
            host = (urlparse(href).hostname or "").casefold()
            if any(host == domain or host.endswith(f".{domain}") for domain in social_domains):
                normalized = normalize_url(href)
                if normalized and normalized not in links:
                    links.append(normalized)
            if len(links) >= 20:
                return links
    return links


def _content_hash(page: dict[str, Any]) -> str:
    payload = _dump_json(
        {
            "title": page.get("title"),
            "headings": page.get("headings", []),
            "text_blocks": page.get("text_blocks", []),
        }
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _status_for_page(page: dict[str, Any]) -> str:
    if page.get("stop_reason"):
        return "blocked"
    status_code = page.get("status_code")
    if isinstance(status_code, int) and status_code >= 400:
        return "failed"
    return "parsed"


def _chunk_blocks(page: dict[str, Any]) -> list[str]:
    blocks: list[str] = []
    for value in page.get("headings", []) if isinstance(page.get("headings"), list) else []:
        text = str(value or "").strip()
        if text:
            blocks.append(text)
    for value in page.get("text_blocks", []) if isinstance(page.get("text_blocks"), list) else []:
        text = str(value or "").strip()
        if text:
            blocks.append(text)

    chunks: list[str] = []
    current = ""
    for block in blocks[:80]:
        candidate = f"{current}\n{block}".strip() if current else block
        if len(candidate) > 1400 and current:
            chunks.append(current)
            current = block
        else:
            current = candidate
        if len(chunks) >= 25:
            break
    if current and len(chunks) < 25:
        chunks.append(current)
    return chunks


def _iter_profile_evidence(profile: dict[str, Any], fallback_url: str) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []

    business = profile.get("business")
    if isinstance(business, dict):
        name = str(business.get("name") or "").strip()
        if name:
            evidence.append(
                {
                    "field_name": "business.name",
                    "field_value": name,
                    "source_url": str(business.get("source_url") or fallback_url),
                    "source_text": name,
                    "confidence": business.get("confidence"),
                }
            )

    for section in (
        "categories",
        "offering_groups",
        "offerings",
        "product_brands",
        "competitors",
        "goals",
        "personas",
        "differentiators",
    ):
        items = profile.get(section)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            evidence.append(
                {
                    "field_name": f"{section}.name",
                    "field_value": name,
                    "source_url": str(item.get("source_url") or fallback_url),
                    "source_text": str(item.get("description") or name),
                    "confidence": item.get("confidence"),
                }
            )

    locations = profile.get("locations")
    if isinstance(locations, dict):
        for section in ("physical_locations", "service_areas", "visibility_markets"):
            items = locations.get(section)
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "").strip()
                if not name:
                    continue
                evidence.append(
                    {
                        "field_name": f"locations.{section}.name",
                        "field_value": name,
                        "source_url": str(item.get("source_url") or fallback_url),
                        "source_text": name,
                        "confidence": item.get("confidence"),
                    }
                )
    return evidence[:250]


def _replace_job_rows(db: Session, job_id: str) -> None:
    db.query(ExtractionEvidence).filter(ExtractionEvidence.job_id == job_id).delete()
    db.query(KBChunk).filter(KBChunk.job_id == job_id).delete()
    db.query(CrawlBusinessProfile).filter(CrawlBusinessProfile.job_id == job_id).delete()
    db.query(CrawlPage).filter(CrawlPage.job_id == job_id).delete()


def _page_persistence_score(page: dict[str, Any]) -> tuple[int, int, int]:
    text_blocks = page.get("text_blocks")
    headings = page.get("headings")
    status_code = page.get("status_code")
    readable = 0 if page.get("stop_reason") else 1
    successful_response = 1 if isinstance(status_code, int) and 200 <= status_code < 400 else 0
    content_size = (
        len(text_blocks) if isinstance(text_blocks, list) else 0
    ) + (
        len(headings) if isinstance(headings, list) else 0
    )
    return readable, successful_response, content_size


def _dedupe_pages_for_persistence(
    pages: list[Any],
    *,
    fallback_url: str,
) -> tuple[list[dict[str, Any]], int]:
    """Collapse duplicate normalized URLs before hitting the DB unique index."""
    order: list[str] = []
    pages_by_url: dict[str, dict[str, Any]] = {}
    duplicate_count = 0
    for page in pages:
        if not isinstance(page, dict):
            continue
        page_url = str(page.get("url") or fallback_url)
        normalized_url = normalize_url(page_url)
        if not normalized_url:
            continue
        existing = pages_by_url.get(normalized_url)
        if existing is None:
            order.append(normalized_url)
            pages_by_url[normalized_url] = page
            continue
        duplicate_count += 1
        if _page_persistence_score(page) > _page_persistence_score(existing):
            pages_by_url[normalized_url] = page
    return [pages_by_url[url] for url in order], duplicate_count


def _upsert_client_context(
    db: Session,
    *,
    client_id: str,
    status: str,
    profile: dict[str, Any] | None,
    evidence: dict[str, Any] | None,
    warnings: list[str],
) -> None:
    now = _utcnow()
    context = db.query(ClientContext).filter(ClientContext.client_id == client_id).first()
    if not context:
        context = ClientContext(client_id=client_id, created_at=now)
        db.add(context)
    context.status = status
    context.profile_json = profile if profile is not None else context.profile_json
    context.evidence_json = evidence if evidence is not None else context.evidence_json
    context.warnings_json = warnings
    context.updated_at = now


def _persist_phase12_crawl_artifacts(
    db: Session,
    *,
    client_id: str,
    evidence: dict[str, Any],
    profile: dict[str, Any],
    warnings: list[str],
) -> dict[str, Any]:
    artifact = build_crawl_artifacts(
        evidence=evidence,
        profile=profile,
        warnings=warnings,
    )
    business_profile = db.query(BusinessProfile).filter(
        BusinessProfile.client_id == client_id,
    ).first()
    if business_profile:
        business_profile.crawl_artifacts = artifact
        business_profile.updated_at = _utcnow()
    return artifact


def run_crawl_job(
    job_id: str,
    *,
    fetch_page: FetchPage | None = None,
    render_page: FetchPage | None = None,
) -> None:
    """Execute a crawl job and persist pages, evidence, and draft profile."""
    db = SessionLocal()
    try:
        job = db.query(CrawlJob).filter(CrawlJob.id == job_id).first()
        if not job:
            logger.error("Crawl job %s not found", job_id)
            return

        workspace = db.query(OnboardingWorkspace).filter(
            OnboardingWorkspace.id == job.workspace_id,
        ).first()
        if not workspace:
            logger.error("Crawl job %s has no workspace", job_id)
            return

        client = db.query(Client).filter(Client.id == workspace.client_id).first()
        if not client:
            logger.error("Crawl job %s has no client", job_id)
            return

        if job.status != "queued":
            logger.warning(
                "Crawl job %s has status '%s', expected 'queued' — skipping",
                job_id,
                job.status,
            )
            return

        now = _utcnow()
        job.status = "running"
        job.started_at = now
        job.updated_at = now
        workspace.status = "active"
        workspace.updated_at = now
        db.commit()
        logger.info("Crawl job %s started", job_id)

        _replace_job_rows(db, job_id)
        db.commit()

        evidence = discover_website(
            workspace.website_url,
            config=_bounded_ingestion_config(job),
            fetch_page=fetch_page,
            render_page=render_page,
        )
        pages = evidence.get("pages") if isinstance(evidence, dict) else []
        pages = pages if isinstance(pages, list) else []
        pages, duplicate_page_count = _dedupe_pages_for_persistence(
            pages,
            fallback_url=workspace.website_url,
        )
        if isinstance(evidence, dict):
            evidence = {**evidence, "pages": pages, "page_count": len(pages)}
        if duplicate_page_count:
            logger.info(
                "Crawl job %s collapsed %s duplicate page URL(s) before persistence",
                job_id,
                duplicate_page_count,
            )
        warnings = [str(item) for item in evidence.get("warnings", [])] if isinstance(evidence, dict) else []

        page_id_by_url: dict[str, str] = {}
        for depth, page in enumerate(pages):
            if not isinstance(page, dict):
                continue
            page_url = str(page.get("url") or workspace.website_url)
            normalized_url = normalize_url(page_url)
            page_id = str(uuid.uuid4())
            page_id_by_url[normalized_url] = page_id
            title = str(page.get("title") or "") or None
            page_row = CrawlPage(
                id=page_id,
                job_id=job_id,
                url=page_url,
                normalized_url=normalized_url,
                final_url=page_url,
                domain=extract_domain(page_url) or workspace.normalized_domain,
                title=title,
                page_type=classify_page_type(page_url, title or ""),
                status=_status_for_page(page),
                status_code=page.get("status_code") if isinstance(page.get("status_code"), int) else None,
                content_type=str(page.get("content_type") or "") or None,
                depth=min(depth, job.max_depth),
                content_hash=_content_hash(page),
                error_message=str(page.get("stop_reason") or "") or None,
                extraction_summary={
                    "heading_count": len(page.get("headings", [])) if isinstance(page.get("headings"), list) else 0,
                    "text_block_count": len(page.get("text_blocks", [])) if isinstance(page.get("text_blocks"), list) else 0,
                    "link_count": len(page.get("links", [])) if isinstance(page.get("links"), list) else 0,
                    "button_count": len(page.get("buttons", [])) if isinstance(page.get("buttons"), list) else 0,
                    "stop_reason": page.get("stop_reason"),
                },
                fetched_at=_utcnow(),
            )
            db.add(page_row)

            for index, chunk in enumerate(_chunk_blocks(page)):
                db.add(
                    KBChunk(
                        id=str(uuid.uuid4()),
                        job_id=job_id,
                        page_id=page_id,
                        source_url=page_url,
                        title=title,
                        page_type=page_row.page_type,
                        chunk_index=index,
                        chunk_text=chunk,
                        token_estimate=max(1, len(chunk) // 4),
                        metadata_json={"source": "website_ingestion"},
                    )
                )

        profile, profile_warnings, context_status = build_context_profile(client, evidence)
        warnings = list(dict.fromkeys([*warnings, *profile_warnings]))
        _persist_phase12_crawl_artifacts(
            db,
            client_id=client.id,
            evidence=evidence,
            profile=profile,
            warnings=warnings,
        )
        business = profile.get("business") if isinstance(profile, dict) else {}
        categories = profile.get("categories") if isinstance(profile, dict) else []
        offerings = profile.get("offerings") if isinstance(profile, dict) else []
        product_brands = profile.get("product_brands") if isinstance(profile, dict) else []
        category_names = _safe_name_list(categories, limit=1)

        profile_row = CrawlBusinessProfile(
            id=str(uuid.uuid4()),
            workspace_id=workspace.id,
            job_id=job_id,
            client_id=client.id,
            company_name=str(business.get("name") or client.name) if isinstance(business, dict) else client.name,
            website=str(business.get("website_url") or workspace.website_url) if isinstance(business, dict) else workspace.website_url,
            domain=workspace.normalized_domain,
            description=_build_description(profile),
            industry=category_names[0] if category_names else client.industry,
            products=_safe_name_list(product_brands, limit=30),
            services=_safe_name_list(offerings, limit=60),
            locations=_flatten_locations(profile),
            contacts={},
            social_links=_collect_social_links(evidence),
            important_pages=_important_pages(evidence),
            missing_fields=warnings,
            confidence_score=float(business.get("confidence") or 0.5) if isinstance(business, dict) else 0.5,
            profile_status="draft_extracted",
            created_at=_utcnow(),
            updated_at=_utcnow(),
        )
        db.add(profile_row)

        for item in _iter_profile_evidence(profile, workspace.website_url):
            source_url = item["source_url"]
            page_id = page_id_by_url.get(normalize_url(source_url))
            db.add(
                ExtractionEvidence(
                    id=str(uuid.uuid4()),
                    job_id=job_id,
                    page_id=page_id,
                    field_name=item["field_name"],
                    field_value=item["field_value"],
                    source_url=source_url,
                    source_text=item["source_text"],
                    extraction_method="website_ingestion_profile_builder",
                    confidence_score=float(item["confidence"]) if item.get("confidence") is not None else None,
                )
            )

        job.pages_discovered = int(evidence.get("page_count") or len(pages)) if isinstance(evidence, dict) else len(pages)
        job.pages_queued = len(pages)
        job.pages_crawled = sum(1 for page in pages if isinstance(page, dict) and not page.get("stop_reason"))
        job.pages_skipped = sum(1 for page in pages if isinstance(page, dict) and page.get("stop_reason"))
        job.pages_failed = 0
        job.status = "completed_with_warnings" if warnings else "completed"
        job.warnings = warnings
        job.error_message = None
        job.completed_at = _utcnow()
        job.updated_at = _utcnow()

        workspace.status = "review_ready"
        workspace.updated_at = _utcnow()
        _upsert_client_context(
            db,
            client_id=client.id,
            status=context_status,
            profile=profile,
            evidence=evidence,
            warnings=warnings,
        )

        db.commit()
        logger.info("Crawl job %s completed with %s pages", job_id, len(pages))

    except Exception:
        logger.exception("Crawl job %s failed with an unexpected error", job_id)
        try:
            db.rollback()
            job = db.query(CrawlJob).filter(CrawlJob.id == job_id).first()
            if job:
                job.status = "failed"
                job.error_message = "Website discovery failed. Please review the URL or enter the profile manually."
                job.completed_at = _utcnow()
                job.updated_at = _utcnow()
                workspace = db.query(OnboardingWorkspace).filter(
                    OnboardingWorkspace.id == job.workspace_id,
                ).first()
                if workspace:
                    workspace.status = "review_needed"
                    workspace.updated_at = _utcnow()
                    _upsert_client_context(
                        db,
                        client_id=workspace.client_id,
                        status="failed",
                        profile=None,
                        evidence=None,
                        warnings=["Website discovery failed. Please review the URL or enter the profile manually."],
                    )
                db.commit()
        except Exception:
            logger.exception("Failed to mark crawl job %s as failed", job_id)
    finally:
        db.close()
