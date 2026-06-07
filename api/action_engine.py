"""Evidence-grounded action engine for AISO.

Reads scan results, citations, and analysis data to produce specific,
actionable recommendations with full evidence chains. Replaces the old
vague action generation with deterministic, scan-evidence-backed actions.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from api.database import (
    Action,
    Client,
    ClientContext,
    Scan,
    ScanCitation,
    ScanResult,
)


# ── Action categories ─────────────────────────────────────────────────────────

CATEGORY_MISSING_MENTION = "missing_mention"
CATEGORY_WEAK_POSITION = "weak_position"
CATEGORY_CITATION_GAP = "citation_gap"
CATEGORY_PROVIDER_BLIND_SPOT = "provider_blind_spot"
CATEGORY_ENTITY_CONFUSION = "entity_confusion"
CATEGORY_CONTENT_OPPORTUNITY = "content_opportunity"
CATEGORY_SCHEMA_GAP = "schema_gap"

# Intent group impact weights (higher = more important to fix)
GROUP_IMPACT_WEIGHTS: dict[str, float] = {
    "G1": 8.5,   # Category & local discovery
    "G2": 6.0,   # Direct brand
    "G3": 8.8,   # Competitors & alternatives
    "G4": 9.4,   # Transactional & bottom-funnel
    "G5": 8.0,   # Trust, reviews & risk
    "G6": 9.2,   # Fit: persona, occasion, constraint
    "G7": 9.0,   # Head-to-head choice
}

PROVIDER_DISPLAY: dict[str, str] = {
    "openai": "ChatGPT",
    "claude": "Claude",
    "perplexity": "Perplexity",
    "gemini": "Gemini",
}

GROUP_LABELS: dict[str, str] = {
    "G1": "local discovery",
    "G2": "branded",
    "G3": "competitor comparison",
    "G4": "transactional/booking",
    "G5": "trust and reviews",
    "G6": "fit and persona",
    "G7": "head-to-head",
}

# Priority thresholds
HIGH_IMPACT_THRESHOLD = 70.0
MEDIUM_IMPACT_THRESHOLD = 40.0


def _stable_key(scan_id: str, category: str, discriminator: str) -> str:
    """Deterministic action key to avoid duplicate actions across re-runs."""
    raw = f"{scan_id}:{category}:{discriminator}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _priority_from_impact(impact: float) -> str:
    if impact >= HIGH_IMPACT_THRESHOLD:
        return "high"
    if impact >= MEDIUM_IMPACT_THRESHOLD:
        return "medium"
    return "low"


def _safe_json(value: Any) -> Any:
    if not value:
        return {}
    if isinstance(value, (list, dict)):  # JSON-typed column already parsed
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return {}


def _json_or_none(value: Any) -> Any:
    """Normalize an action-data value for a JSON column: pass through list/dict,
    parse a legacy JSON string, and use None for empty. (The action-data dict
    still carries JSON strings from json.dumps; this stores them as structures.)"""
    if not value:
        return None
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return None


def _provider_name(provider_id: str) -> str:
    return PROVIDER_DISPLAY.get(provider_id, provider_id.title())


# ── Evidence extraction from scan data ─────────────────────────────────────────

def _question_level_data(
    db: Session, client_id: str, scan_id: str, client_name: str,
) -> dict[str, Any]:
    """Extract question-level mention data from citations.

    Returns a dict keyed by question text, with per-provider mention info,
    competitor mentions, and source data.
    """
    citations = db.query(ScanCitation).filter(
        ScanCitation.client_id == client_id,
        ScanCitation.scan_id == scan_id,
    ).all()

    questions: dict[str, dict[str, Any]] = {}
    client_lower = (client_name or "").strip().casefold()

    for cit in citations:
        q = (cit.question or "").strip()
        if not q:
            continue
        if q not in questions:
            questions[q] = {
                "group": cit.group,
                "providers_with_client": [],
                "providers_without_client": [],
                "competitor_mentions": {},
                "cited_sources": [],
            }
        entry = questions[q]

        # Check if the client is mentioned in this citation's answer
        answer = (cit.answer_excerpt or "").casefold()
        provider = cit.provider or ""

        if client_lower and client_lower in answer:
            if provider not in entry["providers_with_client"]:
                entry["providers_with_client"].append(provider)
        else:
            if provider not in entry["providers_without_client"]:
                entry["providers_without_client"].append(provider)

        # Track competitor mentions from citation sources
        if cit.source_domain:
            entry["cited_sources"].append({
                "domain": cit.source_domain,
                "provider": provider,
                "owner_type": cit.owner_type,
            })

    return questions


def _provider_gap_analysis(
    result_rows: list[ScanResult],
) -> dict[str, dict[str, Any]]:
    """Per-provider aggregated performance from ScanResult rows."""
    providers: dict[str, dict[str, Any]] = {}
    for row in result_rows:
        p = row.provider
        if p not in providers:
            providers[p] = {
                "total_questions": 0,
                "mention_count": 0,
                "visibility_scores": [],
                "groups": {},
            }
        bucket = providers[p]
        bucket["total_questions"] += row.total_questions or 0
        bucket["mention_count"] += row.mention_count or 0
        if row.visibility_score is not None:
            bucket["visibility_scores"].append(row.visibility_score)

        group = row.group or "unknown"
        if group not in bucket["groups"]:
            bucket["groups"][group] = {"total": 0, "mentions": 0, "score": 0.0}
        g = bucket["groups"][group]
        g["total"] += row.total_questions or 0
        g["mentions"] += row.mention_count or 0
        g["score"] = row.visibility_score or 0.0

    # Compute averages
    for p, data in providers.items():
        scores = data["visibility_scores"]
        data["avg_score"] = sum(scores) / len(scores) if scores else 0.0
    return providers


def _competitor_data(result_rows: list[ScanResult]) -> dict[str, int]:
    """Aggregate competitor mention counts across all results."""
    counts: dict[str, int] = {}
    for row in result_rows:
        for name, count in _safe_json(row.competitor_data).items():
            counts[name] = counts.get(name, 0) + int(count)
    return counts


# ── Action generators ──────────────────────────────────────────────────────────

def _missing_mention_actions(
    scan_id: str,
    client_id: str,
    client_name: str,
    question_data: dict[str, dict[str, Any]],
    competitor_names: list[str],
) -> list[dict[str, Any]]:
    """Actions for questions where client is absent but competitors present."""
    actions: list[dict[str, Any]] = []
    competitor_lower = {c.casefold() for c in competitor_names if c}

    # Group missing-mention questions by group for batching
    group_gaps: dict[str, list[str]] = {}
    for question, data in question_data.items():
        if data["providers_with_client"]:
            continue  # Client is mentioned somewhere
        if not data["providers_without_client"]:
            continue
        group = data.get("group", "unknown")
        group_gaps.setdefault(group, []).append(question)

    for group, questions in group_gaps.items():
        if not questions:
            continue
        sample_questions = questions[:3]
        impact = min(
            len(questions) * GROUP_IMPACT_WEIGHTS.get(group, 5.0),
            95.0,
        )
        group_label = GROUP_LABELS.get(group, group)

        evidence = (
            f"Your business is not mentioned by any AI provider for "
            f"{len(questions)} {group_label} question{'s' if len(questions) != 1 else ''}. "
            f"Example: \"{sample_questions[0]}\"."
        )
        if len(sample_questions) > 1:
            evidence += f" Also: \"{sample_questions[1]}\"."

        actions.append({
            "client_id": client_id,
            "scan_id": scan_id,
            "action_key": _stable_key(scan_id, CATEGORY_MISSING_MENTION, group),
            "title": f"Not mentioned for {group_label} queries ({group})",
            "description": (
                f"AI search providers don't mention {client_name} for "
                f"{len(questions)} {group_label} queries. Creating content "
                f"that directly answers these questions can close the gap."
            ),
            "priority": _priority_from_impact(impact),
            "category": CATEGORY_MISSING_MENTION,
            "impact_estimate": round(impact, 1),
            "remediation_type": "blog_post",
            "target_questions_json": json.dumps(questions[:10]),
            "target_providers_json": json.dumps(
                list({p for q in questions for p in question_data[q]["providers_without_client"]})
            ),
            "evidence_summary": evidence,
            "evidence_json": json.dumps({
                "category": CATEGORY_MISSING_MENTION,
                "group": group,
                "question_count": len(questions),
                "sample_questions": sample_questions,
            }),
        })

    return actions


def _weak_position_actions(
    scan_id: str,
    client_id: str,
    client_name: str,
    provider_data: dict[str, dict[str, Any]],
    competitor_counts: dict[str, int],
) -> list[dict[str, Any]]:
    """Actions for providers where client appears but below competitors."""
    actions: list[dict[str, Any]] = []
    total_client_mentions = sum(d["mention_count"] for d in provider_data.values())

    for competitor, comp_count in sorted(competitor_counts.items(), key=lambda x: -x[1]):
        if comp_count <= total_client_mentions:
            continue
        gap_ratio = comp_count / max(total_client_mentions, 1)
        if gap_ratio < 1.3:
            continue  # Not a significant gap
        impact = min(gap_ratio * 20, 85.0)

        actions.append({
            "client_id": client_id,
            "scan_id": scan_id,
            "action_key": _stable_key(scan_id, CATEGORY_WEAK_POSITION, competitor),
            "title": f"Outperformed by {competitor}",
            "description": (
                f"{competitor} is mentioned {comp_count} times across AI providers, "
                f"compared to your {total_client_mentions}. Strengthening your proof "
                f"signals and content can close this gap."
            ),
            "priority": _priority_from_impact(impact),
            "category": CATEGORY_WEAK_POSITION,
            "impact_estimate": round(impact, 1),
            "remediation_type": "page_optimization",
            "target_questions_json": None,
            "target_providers_json": json.dumps(list(provider_data.keys())),
            "evidence_summary": (
                f"{competitor} appears {comp_count} times vs. your {total_client_mentions}. "
                f"They are {gap_ratio:.1f}x more visible across AI search."
            ),
            "evidence_json": json.dumps({
                "category": CATEGORY_WEAK_POSITION,
                "competitor": competitor,
                "competitor_mentions": comp_count,
                "client_mentions": total_client_mentions,
                "gap_ratio": round(gap_ratio, 2),
            }),
        })

    return actions[:3]  # Cap at top 3 competitors


def _provider_blind_spot_actions(
    scan_id: str,
    client_id: str,
    client_name: str,
    provider_data: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Actions for providers where client is invisible but visible on others."""
    actions: list[dict[str, Any]] = []
    if len(provider_data) < 2:
        return actions

    scores = {p: d["avg_score"] for p, d in provider_data.items()}
    best_score = max(scores.values()) if scores else 0
    if best_score < 20:
        return actions  # No provider has decent visibility

    for provider, score in scores.items():
        if score >= best_score * 0.5:
            continue  # This provider is reasonably close to best
        if score >= 30:
            continue  # Absolute score isn't too bad

        visible_on = [p for p, s in scores.items() if s >= best_score * 0.5 and p != provider]
        if not visible_on:
            continue

        impact = min((best_score - score) * 1.2, 80.0)
        p_name = _provider_name(provider)
        visible_names = [_provider_name(p) for p in visible_on]

        actions.append({
            "client_id": client_id,
            "scan_id": scan_id,
            "action_key": _stable_key(scan_id, CATEGORY_PROVIDER_BLIND_SPOT, provider),
            "title": f"Low visibility on {p_name}",
            "description": (
                f"Your visibility on {p_name} is {score:.0f}/100, significantly lower than "
                f"{', '.join(visible_names)} ({', '.join(f'{s:.0f}' for p, s in scores.items() if p in visible_on)}). "
                f"Content optimized for {p_name}'s citation style can help."
            ),
            "priority": _priority_from_impact(impact),
            "category": CATEGORY_PROVIDER_BLIND_SPOT,
            "impact_estimate": round(impact, 1),
            "remediation_type": "blog_post",
            "target_questions_json": None,
            "target_providers_json": json.dumps([provider]),
            "evidence_summary": (
                f"{p_name} scores {score:.0f}/100 while you score "
                f"{best_score:.0f}/100 on your best provider. "
                f"This gap suggests {p_name} doesn't have enough source material to cite you."
            ),
            "evidence_json": json.dumps({
                "category": CATEGORY_PROVIDER_BLIND_SPOT,
                "provider": provider,
                "provider_score": round(score, 1),
                "best_score": round(best_score, 1),
                "all_scores": {p: round(s, 1) for p, s in scores.items()},
            }),
        })

    return actions


def _content_opportunity_actions(
    scan_id: str,
    client_id: str,
    client_name: str,
    provider_data: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Actions for high-impact question groups with zero or near-zero presence."""
    actions: list[dict[str, Any]] = []

    # Aggregate across providers by group
    group_totals: dict[str, dict[str, int]] = {}
    for p, data in provider_data.items():
        for group, gdata in data.get("groups", {}).items():
            if group not in group_totals:
                group_totals[group] = {"total": 0, "mentions": 0}
            group_totals[group]["total"] += gdata["total"]
            group_totals[group]["mentions"] += gdata["mentions"]

    for group, totals in group_totals.items():
        if totals["total"] == 0:
            continue
        mention_rate = totals["mentions"] / totals["total"]
        if mention_rate >= 0.15:
            continue  # Some presence — not a total gap
        group_weight = GROUP_IMPACT_WEIGHTS.get(group, 5.0)
        if group_weight < 7.0:
            continue  # Not a high-impact group

        impact = min(group_weight * 8 * (1 - mention_rate), 90.0)
        group_label = GROUP_LABELS.get(group, group)

        remediation = "faq_page" if group in {"G5", "G6"} else "blog_post"

        actions.append({
            "client_id": client_id,
            "scan_id": scan_id,
            "action_key": _stable_key(scan_id, CATEGORY_CONTENT_OPPORTUNITY, group),
            "title": f"Content gap for {group_label} queries",
            "description": (
                f"You're mentioned in only {totals['mentions']} of {totals['total']} "
                f"{group_label} questions ({mention_rate:.0%}). "
                f"These are high-intent queries — content targeting them can "
                f"significantly improve your AI visibility."
            ),
            "priority": _priority_from_impact(impact),
            "category": CATEGORY_CONTENT_OPPORTUNITY,
            "impact_estimate": round(impact, 1),
            "remediation_type": remediation,
            "target_questions_json": None,
            "target_providers_json": json.dumps(list(provider_data.keys())),
            "evidence_summary": (
                f"Only {mention_rate:.0%} mention rate for {group_label} questions "
                f"({group}). These carry a {group_weight}/10 intent weight."
            ),
            "evidence_json": json.dumps({
                "category": CATEGORY_CONTENT_OPPORTUNITY,
                "group": group,
                "mention_rate": round(mention_rate, 3),
                "total_questions": totals["total"],
                "mentions": totals["mentions"],
                "group_weight": group_weight,
            }),
        })

    return actions


# ── Main engine ────────────────────────────────────────────────────────────────

def generate_actions(
    db: Session,
    client: Client,
    scan: Scan,
) -> list[Action]:
    """Generate evidence-grounded actions from a completed scan.

    Returns a list of Action ORM objects (not yet committed). The caller
    decides whether to commit or inspect first.
    """
    client_name = client.name or ""
    scan_id = scan.id
    client_id = client.id

    # 1. Load scan result rows
    result_rows = db.query(ScanResult).filter(
        ScanResult.scan_id == scan_id,
        ScanResult.client_id == client_id,
    ).all()
    if not result_rows:
        return []

    # 2. Build per-provider gap analysis
    provider_data = _provider_gap_analysis(result_rows)

    # 3. Build question-level data from citations
    question_data = _question_level_data(db, client_id, scan_id, client_name)

    # 4. Aggregate competitor mentions
    competitor_counts = _competitor_data(result_rows)

    # 5. Get competitor names from client profile
    competitor_names = []
    if isinstance(client.competitor_names, list):
        competitor_names = [str(c).strip() for c in client.competitor_names if str(c).strip()]

    # 6. Generate actions from each category
    raw_actions: list[dict[str, Any]] = []

    raw_actions.extend(_missing_mention_actions(
        scan_id, client_id, client_name, question_data, competitor_names,
    ))
    raw_actions.extend(_weak_position_actions(
        scan_id, client_id, client_name, provider_data, competitor_counts,
    ))
    raw_actions.extend(_provider_blind_spot_actions(
        scan_id, client_id, client_name, provider_data,
    ))
    raw_actions.extend(_content_opportunity_actions(
        scan_id, client_id, client_name, provider_data,
    ))

    # 7. Sort by impact estimate (highest first) and assign sort_order
    raw_actions.sort(key=lambda a: -(a.get("impact_estimate") or 0))

    orm_actions: list[Action] = []
    for idx, data in enumerate(raw_actions):
        action = Action(
            id=str(uuid.uuid4()),
            client_id=data["client_id"],
            scan_id=data["scan_id"],
            action_key=data["action_key"],
            title=data["title"],
            description=data["description"],
            priority=data["priority"],
            category=data["category"],
            impact_estimate=data.get("impact_estimate"),
            remediation_type=data.get("remediation_type"),
            target_questions_json=_json_or_none(data.get("target_questions_json")),
            target_providers_json=_json_or_none(data.get("target_providers_json")),
            evidence_summary=data.get("evidence_summary"),
            evidence_json=_json_or_none(data.get("evidence_json")),
            score=data.get("impact_estimate"),
            sort_order=idx,
            status="open",
            created_at=datetime.now(timezone.utc),
        )
        orm_actions.append(action)

    return orm_actions


def regenerate_actions_for_scan(db: Session, client: Client, scan: Scan) -> int:
    """Delete existing actions for a scan and regenerate from evidence.

    Returns the count of new actions created.
    """
    # Remove old actions for this scan (upsert by action_key would also work,
    # but full replace is simpler and avoids stale entries)
    db.query(Action).filter(
        Action.scan_id == scan.id,
        Action.client_id == client.id,
    ).delete(synchronize_session=False)

    actions = generate_actions(db, client, scan)
    for action in actions:
        db.add(action)

    db.flush()
    return len(actions)
