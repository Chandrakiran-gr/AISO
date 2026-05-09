"""Crawl worker stub — placeholder for actual crawl execution.

Phase 1: transitions job status without fetching any pages.
Phase 2: will perform actual HTTP fetching, parsing, extraction, and chunking.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from api.database import SessionLocal
from api.crawler.models import CrawlJob

logger = logging.getLogger(__name__)


def run_crawl_job(job_id: str) -> None:
    """Execute a crawl job (Phase 1 stub).

    In Phase 2 this function will:
      - Load the workspace and crawl policy
      - Check robots.txt
      - Fetch the homepage and sitemap
      - Discover and score internal URLs
      - Crawl pages up to max_pages / max_depth
      - Run extractors and store evidence
      - Build the business profile
      - Create RAG-ready KB chunks
      - Transition to completed / completed_with_warnings / failed

    For now it transitions queued → running → completed and records
    that Phase 2 execution is pending.
    """
    db = SessionLocal()
    try:
        job = db.query(CrawlJob).filter(CrawlJob.id == job_id).first()
        if not job:
            logger.error("Crawl job %s not found", job_id)
            return

        if job.status != "queued":
            logger.warning(
                "Crawl job %s has status '%s', expected 'queued' — skipping",
                job_id,
                job.status,
            )
            return

        # Transition: queued → running
        now = datetime.now(timezone.utc)
        job.status = "running"
        job.started_at = now
        job.updated_at = now
        db.commit()
        logger.info("Crawl job %s started (Phase 1 stub)", job_id)

        # Phase 1: no actual crawling — mark with distinct stub status.
        job.status = "completed_with_warnings"
        job.completed_at = datetime.now(timezone.utc)
        job.updated_at = datetime.now(timezone.utc)
        job.warnings = json.dumps(
            [
                "Crawl worker is in Phase 1 stub mode. No pages were fetched.",
                "Actual crawling will be enabled in Phase 2.",
            ],
            ensure_ascii=False,
        )
        db.commit()
        logger.info("Crawl job %s completed (Phase 1 stub — no pages fetched)", job_id)

    except Exception:
        logger.exception("Crawl job %s failed with an unexpected error", job_id)
        try:
            job = db.query(CrawlJob).filter(CrawlJob.id == job_id).first()
            if job:
                job.status = "failed"
                job.error_message = "Unexpected worker error"
                job.completed_at = datetime.now(timezone.utc)
                job.updated_at = datetime.now(timezone.utc)
                db.commit()
        except Exception:
            logger.exception("Failed to mark crawl job %s as failed", job_id)
    finally:
        db.close()
