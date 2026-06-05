"""Backfill the Phase 13 dashboard projection for already-published scan runs.

Scans published before the projection saga step existed (or whose projection
failed) won't have scan_metric/scan_citation/scan_competitor/scan_action/
scan_question_result rows. This materializes them so the phase13 dashboard
endpoints have data without re-running the scan.

Usage:
    .venv/bin/python scripts/backfill_phase13_projection.py            # all published, missing only
    .venv/bin/python scripts/backfill_phase13_projection.py --force    # re-materialize even if present
    .venv/bin/python scripts/backfill_phase13_projection.py --scan-id <id>
    .venv/bin/python scripts/backfill_phase13_projection.py --client-id <id>
    .venv/bin/python scripts/backfill_phase13_projection.py --dry-run
"""

from __future__ import annotations

import argparse
import sys

from api.adapters.scan_projection import materialize_dashboard_projection
from api.database import ScanMetric, ScanRun, SessionLocal

_PUBLISHED = ("succeeded", "partial")


def _target_runs(db, *, scan_id: str | None, client_id: str | None, force: bool) -> list[str]:
    query = db.query(ScanRun.id).filter(ScanRun.status.in_(_PUBLISHED))
    if scan_id:
        query = query.filter(ScanRun.id == scan_id)
    if client_id:
        query = query.filter(ScanRun.client_id == client_id)
    ids = [row[0] for row in query.order_by(ScanRun.enqueued_at.asc()).all()]
    if force:
        return ids
    # only runs without an existing projection
    return [
        rid for rid in ids
        if not db.query(ScanMetric.id).filter(ScanMetric.scan_id == rid).first()
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill Phase 13 dashboard projection")
    parser.add_argument("--scan-id", default=None)
    parser.add_argument("--client-id", default=None)
    parser.add_argument("--force", action="store_true", help="re-materialize even if rows already exist")
    parser.add_argument("--dry-run", action="store_true", help="list targets, make no changes")
    args = parser.parse_args(argv)

    db = SessionLocal()
    try:
        targets = _target_runs(db, scan_id=args.scan_id, client_id=args.client_id, force=args.force)
        print(f"[backfill] {len(targets)} scan run(s) to process"
              + (" (dry run)" if args.dry_run else ""))
        if args.dry_run:
            for rid in targets:
                print(f"  would materialize: {rid}")
            return 0

        ok = failed = 0
        for rid in targets:
            try:
                result = materialize_dashboard_projection(db, scan_run_id=rid)
                db.commit()
                ok += 1
                print(f"  ok {rid}: metrics={result.metric_count} citations={result.citation_count} "
                      f"competitors={result.competitor_count} actions={result.action_count} "
                      f"questions={result.question_count}")
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                failed += 1
                print(f"  FAILED {rid}: {exc}")
        print(f"[backfill] done: {ok} ok, {failed} failed")
        return 1 if failed else 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
