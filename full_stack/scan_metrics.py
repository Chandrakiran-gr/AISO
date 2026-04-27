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
from pathlib import Path
from typing import Iterable, Mapping


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
    results = aggregate_collect_csv(
        csv_path,
        client_folder,
        fallback_name=fallback_name,
        fallback_competitors=fallback_competitors,
    )
    if not results:
        return []

    from api.database import Action, ScanArtifact, ScanResult, SessionLocal
    from api.storage import describe_local_artifact

    db = SessionLocal()
    try:
        db.query(ScanResult).filter(ScanResult.scan_id == scan_id).delete()
        db.query(Action).filter(Action.scan_id == scan_id).delete()
        db.query(ScanArtifact).filter(
            ScanArtifact.scan_id == scan_id,
            ScanArtifact.artifact_type == "collect_csv",
        ).delete()
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
                    competitor_data=json.dumps(result.competitor_data),
                )
            )
        artifact = describe_local_artifact(
            csv_path,
            artifact_type="collect_csv",
            metadata={
                "source": "full_stack.collect",
                "description": "Raw provider responses used to aggregate scan metrics.",
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
        for action in _recommend_actions(results):
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


def _recommend_actions(
    results: list[AggregatedScanResult],
) -> list[dict[str, str]]:
    """Create deterministic action recommendations from scan aggregates."""
    if not results:
        return []

    total_questions = sum(result.total_questions for result in results)
    total_mentions = sum(result.mention_count for result in results)
    overall = round((total_mentions / total_questions) * 100, 2) if total_questions else 0
    actions: list[dict[str, str]] = []

    if overall < 35:
        actions.append(
            {
                "title": "Strengthen entity signals on your homepage",
                "description": (
                    "AI providers are rarely naming the business. Add clear brand, "
                    "category, location, services, and FAQ copy to the homepage."
                ),
                "priority": "high",
                "category": "entity",
                "impact_pts": "+8-12 pts",
                "effort": "2-4 hours",
                "status": "open",
            }
        )
    elif overall < 60:
        actions.append(
            {
                "title": "Improve comparison and trust content",
                "description": (
                    "The business is visible but not dominant. Add pages that answer "
                    "comparison, review, risk, and fit questions directly."
                ),
                "priority": "medium",
                "category": "content",
                "impact_pts": "+5-8 pts",
                "effort": "3-5 hours",
                "status": "open",
            }
        )

    weak_groups = sorted(
        results,
        key=lambda item: (item.visibility_score, -item.total_questions),
    )[:3]
    for result in weak_groups:
        if result.visibility_score >= 70:
            continue
        actions.append(
            {
                "title": f"Create answers for {result.group} intent questions",
                "description": (
                    f"{result.provider} mentioned the business in "
                    f"{result.mention_count}/{result.total_questions} questions for "
                    f"{result.group}. Publish concise answer-first content for this intent."
                ),
                "priority": "high" if result.visibility_score < 35 else "medium",
                "category": "content",
                "impact_pts": "+3-6 pts",
                "effort": "1-3 hours",
                "status": "open",
            }
        )

    if not actions:
        actions.append(
            {
                "title": "Maintain current AI visibility coverage",
                "description": (
                    "The latest scan shows strong visibility. Keep content fresh and "
                    "monitor competitor movement with the next scan."
                ),
                "priority": "low",
                "category": "monitoring",
                "impact_pts": "+1-2 pts",
                "effort": "30 minutes",
                "status": "open",
            }
        )

    deduped: list[dict[str, str]] = []
    seen: set[str] = set()
    for action in actions:
        if action["title"] in seen:
            continue
        seen.add(action["title"])
        deduped.append(action)
    return deduped[:5]
