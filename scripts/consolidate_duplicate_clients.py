#!/usr/bin/env python
"""Consolidate duplicate businesses (Client rows) created by the pre-fix re-scan bug.

Before the one-profile-per-business fix, every re-scan minted a new Client, so a
user accumulated many duplicate businesses (one per scan), each with its scans
scattered under it. This script collapses each ``(user, business-url)`` group to
ONE canonical Client and deletes the duplicates; Postgres ON DELETE CASCADE then
removes the duplicates' scans and scattered data.

Canonical selection (highest wins): has a confirmed context > most scans >
most-recently updated. Override per business with ``--pin <client_id>``.

Safety:
  - **Dry-run by default** — prints exactly what would be kept/deleted (with scan
    counts). Pass ``--apply`` to execute (one transaction).
  - Take a fresh ``pg_dump`` backup before ``--apply`` against prod.

Deletion order matters: ``scan_provenance.client_id`` has no cascade and its
``scan_id`` FK blocks ``scan_runs`` deletion, so we delete a duplicate's
provenance first (``avs_computation`` cascades from it), then the Client (which
cascades ``scan_runs`` + every other CASCADE child).

Usage:
    DATABASE_URL=... python scripts/consolidate_duplicate_clients.py            # dry-run
    DATABASE_URL=... python scripts/consolidate_duplicate_clients.py --apply
    DATABASE_URL=... python scripts/consolidate_duplicate_clients.py --pin <id> --apply
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict

from sqlalchemy import create_engine, func
from sqlalchemy.orm import Session, sessionmaker

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.client_identity import business_url_key  # noqa: E402
from api.database import (  # noqa: E402
    Client,
    ClientContext,
    Scan,
    ScanProvenance,
    ScanRun,
    User,
)


def _scan_counts(db: Session, client_id: str) -> tuple[int, int]:
    p13 = db.query(func.count(ScanRun.id)).filter(ScanRun.client_id == client_id).scalar() or 0
    legacy = db.query(func.count(Scan.id)).filter(Scan.client_id == client_id).scalar() or 0
    return int(p13), int(legacy)


def _has_confirmed_context(db: Session, client_id: str) -> bool:
    ctx = db.query(ClientContext).filter(ClientContext.client_id == client_id).first()
    return bool(ctx and getattr(ctx, "status", None) == "confirmed")


def delete_client_cascade(db: Session, client_id: str) -> None:
    """Delete one Client and (via DB cascade) all of its data.

    ``scan_provenance`` is removed first because its ``client_id`` FK has no
    cascade and its ``scan_id`` FK blocks ``scan_runs`` deletion. Deleting it
    cascades ``avs_computation``; the Client delete then cascades the rest.
    """
    db.query(ScanProvenance).filter(ScanProvenance.client_id == client_id).delete(
        synchronize_session=False
    )
    db.query(Client).filter(Client.id == client_id).delete(synchronize_session=False)


def plan_consolidation(db: Session, *, pinned: set[str] | None = None) -> list[dict]:
    """Group clients by (user, business-url) and pick a canonical per duplicate group."""
    pinned = pinned or set()
    groups: dict[tuple[str, str], list[Client]] = defaultdict(list)
    for client in db.query(Client).all():
        groups[(client.user_id, business_url_key(client.url or ""))].append(client)

    plan: list[dict] = []
    for (user_id, key), members in sorted(groups.items(), key=lambda kv: kv[0]):
        if len(members) < 2:
            continue
        scored = []
        for c in members:
            p13, legacy = _scan_counts(db, c.id)
            scored.append(
                {
                    "client": c,
                    "p13": p13,
                    "legacy": legacy,
                    "scans": p13 + legacy,
                    "confirmed": _has_confirmed_context(db, c.id),
                    "updated": c.updated_at or c.created_at,
                }
            )
        pinned_here = [s for s in scored if s["client"].id in pinned]
        canonical = (
            pinned_here[0]
            if pinned_here
            else max(scored, key=lambda s: (s["confirmed"], s["scans"], s["updated"]))
        )
        plan.append(
            {
                "user_id": user_id,
                "url_key": key,
                "canonical": canonical,
                "duplicates": [s for s in scored if s["client"].id != canonical["client"].id],
            }
        )
    return plan


def consolidate(db: Session, *, apply: bool = False, pinned: set[str] | None = None) -> list[dict]:
    """Run (or dry-run) the consolidation. Returns the plan for reporting/tests."""
    plan = plan_consolidation(db, pinned=pinned)
    if apply:
        for group in plan:
            for dup in group["duplicates"]:
                delete_client_cascade(db, dup["client"].id)
        db.commit()
    return plan


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="execute the deletes (default: dry-run)")
    parser.add_argument("--pin", action="append", default=[], help="force a client_id to be canonical (repeatable)")
    args = parser.parse_args()

    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL is required")
    db = sessionmaker(bind=create_engine(url))()
    email_by_user = {u.id: u.email for u in db.query(User).all()}

    plan = plan_consolidation(db, pinned=set(args.pin))
    if not plan:
        print("No duplicate (user, business-url) groups. Nothing to consolidate.")
        return

    total_drop = 0
    for group in plan:
        who = email_by_user.get(group["user_id"], group["user_id"])
        kc = group["canonical"]
        print(f"\n[{who}] business '{group['url_key']}' — {len(group['duplicates']) + 1} rows")
        print(
            f"  KEEP {kc['client'].id}  name={kc['client'].name!r}  "
            f"scans={kc['scans']} (p13 {kc['p13']}/legacy {kc['legacy']})  confirmed={kc['confirmed']}"
        )
        for dup in group["duplicates"]:
            total_drop += 1
            dc = dup["client"]
            print(
                f"  DROP {dc.id}  name={dc.name!r}  "
                f"scans={dup['scans']} (p13 {dup['p13']}/legacy {dup['legacy']})  confirmed={dup['confirmed']}"
            )

    print(f"\nGroups with duplicates: {len(plan)} | businesses to delete: {total_drop}")
    if not args.apply:
        print("DRY-RUN — no changes made. Re-run with --apply to execute.")
        return

    consolidate(db, apply=True, pinned=set(args.pin))
    print(f"APPLIED — deleted {total_drop} duplicate businesses (cascade removed their data).")


if __name__ == "__main__":
    main()
