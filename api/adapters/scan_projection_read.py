"""Read the Phase 13 dashboard projection tables into the legacy JSON shapes.

These functions let the existing dashboard endpoints serve Phase 13 data without
changing the frontend: they assemble the same response shapes the legacy
gap-report / actions / sources / citations endpoints return, but sourced from the
materialized ``scan_metric`` / ``scan_citation`` / ``scan_competitor`` /
``scan_action`` tables. Gated by ``AISO_SCAN_ENGINE`` at the route layer.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from api.adapters.scan_runs import JOURNEY_LABELS
from api.database import (
    Client,
    ScanAction,
    ScanCitationP13,
    ScanCompetitor,
    ScanMetric,
    ScanQuestionResult,
    ScanRun,
)
from api.domain.classifier import host_from_url

# source_class -> the action_role vocabulary the existing frontend groups by.
_LEGACY_ACTION_ROLE = {
    "OWNED": "monitor_only",
    "EARNED-HIGH": "partnership_or_pr_target",
    "EARNED-MID": "direct_citation_target",
    "UGC": "listing_or_profile_target",
    "COMPETITOR": "competitive_evidence",
    "UNKNOWN": "direct_citation_target",
}
# Plain-language, jargon-free labels a non-marketer business owner understands.
_PLAIN_SOURCE_LABEL = {
    "OWNED": "Your own website",
    "EARNED-HIGH": "Trusted news / authority site",
    "EARNED-MID": "Review or directory site",
    "UGC": "Community site (Reddit, forums, Q&A)",
    "COMPETITOR": "A competitor's site",
    "UNKNOWN": "Other website",
}
_PLAIN_NEXT_STEP = {
    "partnership_or_pr_target": "Get featured or mentioned on this trusted site (PR, guest articles, partnerships).",
    "direct_citation_target": "Get your business listed and accurately described on this site.",
    "listing_or_profile_target": "Create or claim your profile here and keep it accurate and active.",
    "competitive_evidence": "See why a competitor is named here, and earn a presence on the same site.",
    "monitor_only": "This is your own site — keep the page that answers this question clear and up to date.",
}


def _owner_type(source_class: str | None) -> str:
    sc = (source_class or "UNKNOWN").upper()
    if sc == "OWNED":
        return "brand_owned"
    if sc == "COMPETITOR":
        return "competitor_owned"
    return "third_party"


def _source_type(source_class: str | None) -> str:
    return {
        "OWNED": "brand_site",
        "EARNED-HIGH": "authority_publication",
        "EARNED-MID": "review_or_directory",
        "UGC": "community_forum",
        "COMPETITOR": "competitor_site",
    }.get((source_class or "UNKNOWN").upper(), "unknown_review_needed")


def _legacy_action_role(source_class: str | None) -> str:
    return _LEGACY_ACTION_ROLE.get((source_class or "UNKNOWN").upper(), "direct_citation_target")


def _plain_source_label(source_class: str | None) -> str:
    return _PLAIN_SOURCE_LABEL.get((source_class or "UNKNOWN").upper(), "Other website")


def latest_phase13_scan_id(db: Session, *, client_id: str) -> str | None:
    """Most recent published (succeeded/partial) Phase 13 scan for the client."""
    row = (
        db.query(ScanRun.id)
        .filter(ScanRun.client_id == client_id, ScanRun.status.in_(("succeeded", "partial")))
        .order_by(ScanRun.finished_at.is_(None).asc(), ScanRun.finished_at.desc(), ScanRun.enqueued_at.desc())
        .first()
    )
    return row[0] if row else None


def _resolve_scan_id(db: Session, *, client_id: str, scan_id: str | None) -> str | None:
    return scan_id or latest_phase13_scan_id(db, client_id=client_id)


def phase13_actions(db: Session, *, client_id: str, scan_id: str | None, status: str | None) -> list[dict[str, Any]]:
    """Actions in the legacy ActionResponse shape, sourced from scan_action."""
    target = _resolve_scan_id(db, client_id=client_id, scan_id=scan_id)
    if not target:
        return []
    query = db.query(ScanAction).filter(ScanAction.scan_id == target, ScanAction.client_id == client_id)
    if status:
        query = query.filter(ScanAction.status == status)
    rows = query.order_by(
        ScanAction.sort_order.is_(None).asc(),
        ScanAction.sort_order.asc(),
        ScanAction.score.is_(None).asc(),
        ScanAction.score.desc(),
        ScanAction.created_at.desc(),
    ).all()
    return [_action_payload(a) for a in rows]


def _action_payload(a: ScanAction) -> dict[str, Any]:
    impact = float(a.impact_estimate) if a.impact_estimate is not None else None
    return {
        "id": a.id,
        "client_id": a.client_id,
        "scan_id": a.scan_id,
        "action_key": a.action_key,
        "title": a.title,
        "description": a.description,
        "priority": a.priority,
        "category": a.category,
        "impact_pts": (f"+{impact:.0f} pts" if impact is not None else None),
        "effort": a.effort,
        "score": float(a.score) if a.score is not None else None,
        "sort_order": a.sort_order,
        "evidence_json": json.dumps(a.evidence_json) if a.evidence_json is not None else None,
        "remediation_type": a.action_role,
        "target_questions_json": json.dumps(a.target_questions_json) if a.target_questions_json is not None else None,
        "target_providers_json": (json.dumps([a.target_provider]) if a.target_provider else None),
        "evidence_summary": a.description,
        "impact_estimate": impact,
        "status": a.status,
        "created_at": a.created_at,
        "completed_at": None,
    }


def _journey_label(stage: str | None) -> str:
    return JOURNEY_LABELS.get(stage or "", stage or "")


def _pct(numerator: int, denominator: int) -> float:
    return round((numerator / denominator) * 100, 2) if denominator else 0.0


def _cited_source_payload(c) -> dict[str, Any]:
    """A single cited source in plain language for the frontend."""
    return {
        "url": c.get("url"),
        "domain": c.get("domain"),
        "source_class": c.get("source_class"),
        "source_label": _plain_source_label(c.get("source_class")),
        "owner_type": _owner_type(c.get("source_class")),
        "source_type": _source_type(c.get("source_class")),
        "action_role": _legacy_action_role(c.get("source_class")),
        "is_you": bool(c.get("is_brand")),
    }


def phase13_citations(db: Session, *, client_id: str, scan_id: str | None) -> list[dict[str, Any]]:
    """Per-citation list in the legacy CitationResponse shape, from scan_citation."""
    target = _resolve_scan_id(db, client_id=client_id, scan_id=scan_id)
    if not target:
        return []
    text_by_q = _question_text_map(db, scan_id=target)
    rows = (
        db.query(ScanCitationP13)
        .filter(ScanCitationP13.scan_id == target, ScanCitationP13.client_id == client_id)
        .order_by(ScanCitationP13.provider.asc(), ScanCitationP13.source_rank.asc().nullslast())
        .all()
    )
    out = []
    for c in rows:
        out.append({
            "id": c.id,
            "provider": c.provider,
            "group": c.journey_stage,
            "question": text_by_q.get(c.question_id),
            "answer_excerpt": c.answer_excerpt,
            "citation_url": c.citation_url,
            "citation_title": None,
            "source_domain": c.source_domain,
            "source_rank": c.source_rank,
            "canonical_url": c.canonical_url,
            "citation_origin": None,
            "cited_text": None,
            "web_search_used": c.web_search_used,
            "source_type": _source_type(c.source_class),
            "owner_type": _owner_type(c.source_class),
            "action_role": _legacy_action_role(c.source_class),
            "actionability_score": float(c.source_confidence) * 10 if c.source_confidence is not None else None,
            "influence_score": None,
            "relevance_score": None,
            "confidence_score": float(c.source_confidence) * 10 if c.source_confidence is not None else None,
            "classification_reason": _plain_source_label(c.source_class),
            "created_at": c.created_at,
        })
    return out


def _question_text_map(db: Session, *, scan_id: str) -> dict[str, str]:
    return {
        qr.question_id: (qr.question_text or "")
        for qr in db.query(ScanQuestionResult.question_id, ScanQuestionResult.question_text)
        .filter(ScanQuestionResult.scan_id == scan_id)
        .all()
    }


def phase13_sources(db: Session, *, client_id: str, scan_id: str | None,
                    action_role: str | None = None, min_actionability: float | None = None,
                    limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    """Source-domain rollup in the legacy SourceProfileResponse shape."""
    target = _resolve_scan_id(db, client_id=client_id, scan_id=scan_id)
    if not target:
        return []
    text_by_q = _question_text_map(db, scan_id=target)
    buckets: dict[str, dict[str, Any]] = {}
    for c in db.query(ScanCitationP13).filter(ScanCitationP13.scan_id == target).all():
        domain = c.registered_domain or c.source_domain
        if not domain:
            continue
        b = buckets.setdefault(domain, {
            "id": f"{target}:{domain}", "canonical_url": c.citation_url, "source_domain": domain,
            "source_title": None, "owner_type": _owner_type(c.source_class),
            "source_type": _source_type(c.source_class), "action_role": _legacy_action_role(c.source_class),
            "actionability_score": float(c.source_confidence) * 10 if c.source_confidence is not None else 0.0,
            "influence_score": None, "relevance_score": None,
            "client_mentioned": bool(c.is_brand_citation), "competitors_mentioned": [], "topics": [],
            "fetch_status": None, "classification_reason": _plain_source_label(c.source_class),
            "citation_count": 0, "prompt_count": 0, "_providers": set(),
            "example_questions": [], "top_urls": [],
        })
        b["citation_count"] += 1
        b["_providers"].add(c.provider)
        if c.citation_url and c.citation_url not in b["top_urls"]:
            b["top_urls"].append(c.citation_url)
        q = text_by_q.get(c.question_id)
        if q and q not in b["example_questions"]:
            b["example_questions"].append(q)

    rows = []
    for b in buckets.values():
        if action_role and b["action_role"] != action_role:
            continue
        if min_actionability is not None and b["actionability_score"] < min_actionability:
            continue
        b["provider_count"] = len(b.pop("_providers"))
        b["prompt_count"] = len(b["example_questions"])
        b["example_questions"] = b["example_questions"][:3]
        b["top_urls"] = b["top_urls"][:5]
        rows.append(b)
    rows.sort(key=lambda x: (x["actionability_score"], x["citation_count"]), reverse=True)
    return rows[offset:offset + limit]


def phase13_gap_report(db: Session, *, client: Client, scan_id: str | None) -> dict[str, Any]:
    """Assemble the dashboard gap-report from the projection tables.

    Same top-level keys as the legacy report so the frontend renders unchanged,
    with all user-facing text in plain language.
    """
    target = _resolve_scan_id(db, client_id=client.id, scan_id=scan_id)
    if not target:
        return {"client_id": client.id, "client_name": client.name, "scan_id": None,
                "summary": {}, "coverage": [], "weak_segments": [], "source_opportunities": [],
                "source_intelligence": {}, "competitor_gaps": [], "priority_fixes": [],
                "query_results": [], "report_source": "phase13_projection"}

    metrics = db.query(ScanMetric).filter(ScanMetric.scan_id == target).all()
    citations = db.query(ScanCitationP13).filter(ScanCitationP13.scan_id == target).all()
    competitors = db.query(ScanCompetitor).filter(
        ScanCompetitor.scan_id == target, ScanCompetitor.scope_type == "overall").all()
    qresults = db.query(ScanQuestionResult).filter(ScanQuestionResult.scan_id == target).all()

    overall = next((m for m in metrics if m.scope_type == "overall"), None)
    total = overall.total_samples if overall else 0
    appeared = overall.mention_count if overall else 0
    missed = max(total - appeared, 0)

    coverage, weak_segments = [], []
    for m in metrics:
        if m.scope_type != "provider_journey":
            continue
        score = float(m.avs_value or 0.0)
        appeared_n, total_n = m.mention_count, m.total_samples
        missed_n = max(total_n - appeared_n, 0)
        label = _journey_label(m.journey_stage)
        coverage.append({"group": m.journey_stage, "group_label": label, "provider": m.provider,
                         "total": total_n, "appeared": appeared_n, "missed": missed_n,
                         "appearance_rate": _pct(appeared_n, total_n)})
        if score < 70:
            weak_segments.append({"provider": m.provider, "group": m.journey_stage, "group_label": label,
                                  "score": round(score, 2), "appeared": appeared_n, "total": total_n,
                                  "missed": missed_n})
    weak_segments.sort(key=lambda x: x["score"])

    # which (question, provider) pairs the brand missed
    missed_pairs = {(qr.question_id, qr.provider) for qr in qresults if not qr.appeared}

    source_buckets: dict[str, dict[str, Any]] = {}
    for c in citations:
        if c.is_brand_citation:
            continue
        if (c.question_id, c.provider) not in missed_pairs:
            continue
        domain = c.registered_domain or c.source_domain
        if not domain:
            continue
        b = source_buckets.setdefault(domain, {
            "domain": domain, "missed_query_count": 0, "providers": set(), "groups": set(),
            "example_questions": [], "top_urls": [],
            "owner_type": _owner_type(c.source_class), "source_type": _source_type(c.source_class),
            "action_role": _legacy_action_role(c.source_class), "source_label": _plain_source_label(c.source_class),
            "actionability_score": float(c.source_confidence) * 10 if c.source_confidence is not None else 0.0,
            "confidence_score": float(c.source_confidence) * 10 if c.source_confidence is not None else 0.0,
            "classification_reason": _plain_source_label(c.source_class),
            "next_step": _PLAIN_NEXT_STEP.get(_legacy_action_role(c.source_class), ""),
        })
        b["missed_query_count"] += 1
        b["providers"].add(c.provider)
        if c.journey_stage:
            b["groups"].add(c.journey_stage)
        if c.citation_url and c.citation_url not in b["top_urls"]:
            b["top_urls"].append(c.citation_url)

    text_by_q = {qr.question_id: (qr.question_text or "") for qr in qresults}
    for qr in qresults:
        if qr.appeared:
            continue
        for c in (qr.cited_sources_json or []):
            dom = c.get("domain")
            if dom in source_buckets and text_by_q.get(qr.question_id):
                ex = source_buckets[dom]["example_questions"]
                if text_by_q[qr.question_id] not in ex:
                    ex.append(text_by_q[qr.question_id])

    source_opportunities = sorted(
        ({**b, "providers": sorted(b["providers"]), "groups": sorted(b["groups"]),
          "example_questions": b["example_questions"][:3], "top_urls": b["top_urls"][:3]}
         for b in source_buckets.values()),
        key=lambda x: (x["actionability_score"], x["missed_query_count"]), reverse=True,
    )

    def _by_role(role): return [s for s in source_opportunities if s["action_role"] == role]
    source_intelligence = {
        "direct_targets": [s for s in source_opportunities
                           if s["action_role"] in {"direct_citation_target", "listing_or_profile_target"}][:20],
        "listing_targets": _by_role("listing_or_profile_target")[:20],
        "publisher_targets": _by_role("partnership_or_pr_target")[:20],
        "authority_content_gaps": _by_role("content_gap_signal")[:20],
        "competitive_evidence": [s for s in source_opportunities
                                 if s["action_role"] == "competitive_evidence"
                                 or s["owner_type"] == "competitor_owned"][:20],
        "noise_sources": _by_role("ignore")[:20],
    }

    competitor_gaps = [{"name": c.competitor_name, "missed_query_count": c.mention_count,
                        "share_of_voice": float(c.share_of_voice or 0.0), "providers": [], "groups": [],
                        "example_questions": []}
                       for c in sorted(competitors, key=lambda x: x.mention_count, reverse=True)]

    priority_fixes = _build_priority_fixes(weak_segments, source_intelligence["direct_targets"], client.name)

    query_results = sorted(
        ({"question": qr.question_text, "group": qr.journey_stage, "group_label": _journey_label(qr.journey_stage),
          "provider": qr.provider, "appeared": qr.appeared, "mention_rank": qr.mention_rank,
          "competitors_mentioned": qr.competitors_mentioned_json or [],
          "cited_sources": [_cited_source_payload(c) for c in (qr.cited_sources_json or [])],
          "answer_excerpt": qr.answer_excerpt, "priority_score": float(qr.priority_score or 0.0)}
         for qr in qresults),
        key=lambda item: (item["appeared"], -item["priority_score"]),
    )[:200]

    return {
        "client_id": client.id, "client_name": client.name, "scan_id": target,
        "summary": {
            "total_provider_question_results": total, "appeared_count": appeared, "missed_count": missed,
            "appearance_rate": _pct(appeared, total), "source_opportunity_count": len(source_opportunities),
            "competitor_gap_count": len(competitor_gaps),
            "actionable_source_count": len(source_intelligence["direct_targets"]) + len(source_intelligence["publisher_targets"]),
            "competitive_evidence_count": len(source_intelligence["competitive_evidence"]),
        },
        "coverage": coverage, "weak_segments": weak_segments,
        "source_opportunities": source_opportunities[:20], "source_intelligence": source_intelligence,
        "competitive_evidence": source_intelligence["competitive_evidence"],
        "competitor_gaps": competitor_gaps[:20], "priority_fixes": priority_fixes[:8],
        "query_results": query_results, "report_source": "phase13_projection",
    }


def _build_priority_fixes(weak_segments, direct_targets, brand_name):
    fixes = []
    for seg in weak_segments[:4]:
        fixes.append({
            "title": f"Get mentioned more in {seg['group_label']} questions on {seg['provider']}",
            "impact": "High" if seg["score"] < 40 else "Medium",
            "score": round(min(8.0 + (70 - seg["score"]) / 20, 10.0), 2),
            "why": f"{brand_name} was named in only {seg['appeared']} of {seg['total']} AI answers here.",
            "next_step": "Add clear, helpful content that directly answers these questions on your site.",
            "evidence": {"provider": seg["provider"], "group": seg["group"], "visibility_score": seg["score"]},
        })
    for src in direct_targets[:3]:
        fixes.append({
            "title": f"Get your business onto {src['domain']}",
            "impact": "High" if src["missed_query_count"] >= 5 else "Medium",
            "score": round(min(6.5 + src["missed_query_count"] * 0.4, 9.5), 2),
            "why": f"{src['source_label']} ({src['domain']}) was used by the AI for "
                   f"{src['missed_query_count']} questions where you weren't mentioned.",
            "next_step": src.get("next_step") or "Earn an accurate presence on this site.",
            "evidence": {"domain": src["domain"], "example_questions": src["example_questions"][:2],
                         "top_urls": src["top_urls"][:2]},
        })
    fixes.sort(key=lambda x: x["score"], reverse=True)
    return fixes
