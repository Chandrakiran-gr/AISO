"""AISO assistant tool definitions and dispatcher.

Defines 12 tools for the Claude tool-use agent loop.
All tools are read-only or write-with-confirmation.
Tool results pass through sanitization before being
returned to the LLM.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from api.database import (
    Action,
    Client,
    ClientContext,
    ContentDraft,
    Scan,
    ScanAnalysis,
    ScanCitation,
    ScanResult,
)


# ── Tool schemas (Claude tool-use format) ────────────────────────────────────

TOOLS: list[dict[str, Any]] = [
    {
        "name": "read_scan_findings",
        "description": (
            "Read detailed scan findings from the client's latest completed scan. "
            "Use this when you need to understand what AI providers said about specific "
            "topics, questions, or groups. Filter by question text, provider, or group "
            "to get focused results. Always use this before making specific claims about "
            "scan data — do not guess."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "Filter to questions containing this text (case-insensitive substring match).",
                },
                "provider": {
                    "type": "string",
                    "enum": ["openai", "claude", "perplexity", "gemini"],
                    "description": "Filter to a specific AI provider.",
                },
                "group": {
                    "type": "string",
                    "enum": ["G1", "G2", "G3", "G4", "G5", "G6", "G7"],
                    "description": "Filter to a specific intent group.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default 10, max 25).",
                },
            },
        },
    },
    {
        "name": "read_competitor_analysis",
        "description": (
            "Read competitor mention data from the latest scan. Shows which competitors "
            "are being recommended by AI providers and how often, compared to the client. "
            "Use this when the user asks why a competitor ranks higher or who is outperforming them."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "competitor_name": {
                    "type": "string",
                    "description": "Filter to a specific competitor name (optional).",
                },
            },
        },
    },
    {
        "name": "read_citation_sources",
        "description": (
            "Read the source domains and URLs that AI providers are citing in their answers. "
            "Shows which websites are being referenced and how often. Use this to understand "
            "what sources AI providers trust and cite for this client's topic area."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "provider": {
                    "type": "string",
                    "enum": ["openai", "claude", "perplexity", "gemini"],
                    "description": "Filter to a specific provider (optional).",
                },
                "owner_type": {
                    "type": "string",
                    "enum": ["client", "competitor", "third_party"],
                    "description": "Filter by source ownership type (optional).",
                },
            },
        },
    },
    {
        "name": "read_client_profile",
        "description": (
            "Read the full confirmed client business profile including name, industry, "
            "location, offerings, competitors, target personas, and website evidence. "
            "Use this before writing any content to ensure accuracy."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "read_action_details",
        "description": (
            "Read the full details of a specific action item including evidence, "
            "target questions, target providers, and remediation type. "
            "Use this when the user asks about a specific action or wants to work on one."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action_id": {
                    "type": "string",
                    "description": "The UUID of the action item.",
                },
            },
            "required": ["action_id"],
        },
    },
    {
        "name": "list_visibility_gaps",
        "description": (
            "List the most significant visibility gaps from the latest scan: "
            "questions where the client is not mentioned, providers where visibility "
            "is lowest, and competitors who outperform. Returns a structured summary "
            "of the top gaps with evidence. Use this for status checks and gap analysis."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Maximum gaps to return (default 5, max 10).",
                },
            },
        },
    },
    {
        "name": "save_content_draft",
        "description": (
            "Save a finalized content draft that the user has approved in the conversation. "
            "Only call this when the user explicitly says to save, keep, or finalize the content. "
            "Do NOT save automatically after writing — wait for user approval."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Title for the content draft (max 160 characters).",
                },
                "content": {
                    "type": "string",
                    "description": "The full content to save (max 12000 characters).",
                },
                "content_type": {
                    "type": "string",
                    "enum": [
                        "blog_post",
                        "faq_page",
                        "linkedin_post",
                        "platform_listing",
                        "review_response",
                        "schema_markup",
                        "other",
                    ],
                    "description": "The type of content being saved.",
                },
                "source_action_id": {
                    "type": "string",
                    "description": "The action item ID this content addresses (optional).",
                },
            },
            "required": ["title", "content", "content_type"],
        },
    },
    {
        "name": "update_action_status",
        "description": (
            "Mark an action item as done or dismissed. Only call this when the user "
            "explicitly confirms they have completed or want to dismiss an action."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action_id": {
                    "type": "string",
                    "description": "The UUID of the action item.",
                },
                "status": {
                    "type": "string",
                    "enum": ["done", "dismissed"],
                    "description": "The new status to set.",
                },
            },
            "required": ["action_id", "status"],
        },
    },
    {
        "name": "list_content_drafts",
        "description": (
            "List existing content drafts for the client. Use this when the user asks "
            "to see their saved content, or wants to export a previously saved draft."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["pending_review", "approved", "rejected", "archived"],
                    "description": "Filter by draft status (optional, returns all if omitted).",
                },
            },
        },
    },
    {
        "name": "export_content_draft",
        "description": (
            "Generate a downloadable PDF or DOCX export of a saved content draft. "
            "Use this when the user explicitly asks to export, download, or get a file "
            "of a draft. Returns a download URL the user can click. "
            "The draft must already be saved (use save_content_draft first if needed)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "draft_id": {
                    "type": "string",
                    "description": "The UUID of the content draft to export.",
                },
                "format": {
                    "type": "string",
                    "enum": ["pdf", "docx"],
                    "description": "Export format: 'pdf' for PDF, 'docx' for Word document.",
                },
            },
            "required": ["draft_id", "format"],
        },
    },
]


# ── Tool dispatcher ──────────────────────────────────────────────────────────

def _safe_json(value: str | None) -> Any:
    if not value:
        return {}
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return {}


def _latest_scan(db: Session, client_id: str) -> Scan | None:
    return db.query(Scan).filter(
        Scan.client_id == client_id,
        Scan.status == "complete",
    ).order_by(Scan.created_at.desc()).first()


def _tool_read_scan_findings(
    tool_input: dict[str, Any],
    db: Session,
    client_id: str,
    **_kwargs: Any,
) -> dict[str, Any]:
    scan = _latest_scan(db, client_id)
    if not scan:
        return {"error": "No completed scan found for this client."}

    question_filter = (tool_input.get("question") or "").strip().lower()
    provider_filter = (tool_input.get("provider") or "").strip().lower()
    group_filter = (tool_input.get("group") or "").strip().upper()
    limit = min(int(tool_input.get("limit") or 10), 25)

    query = db.query(ScanCitation).filter(
        ScanCitation.client_id == client_id,
        ScanCitation.scan_id == scan.id,
    )
    if provider_filter:
        query = query.filter(ScanCitation.provider == provider_filter)
    if group_filter:
        query = query.filter(ScanCitation.group == group_filter)

    citations = query.order_by(ScanCitation.created_at.asc()).all()

    # Apply question filter in Python (substring match)
    if question_filter:
        citations = [c for c in citations if question_filter in (c.question or "").lower()]

    # Deduplicate by question + provider
    seen: set[tuple[str, str]] = set()
    results: list[dict[str, Any]] = []
    for cit in citations:
        key = ((cit.question or ""), (cit.provider or ""))
        if key in seen:
            continue
        seen.add(key)
        results.append({
            "question": cit.question,
            "group": cit.group,
            "provider": cit.provider,
            "answer_excerpt": (cit.answer_excerpt or "")[:400],
            "cited_sources": [cit.source_domain] if cit.source_domain else [],
        })
        if len(results) >= limit:
            break

    return {
        "scan_id": scan.id,
        "scan_date": scan.completed_at.isoformat() if scan.completed_at else None,
        "total_results": len(results),
        "findings": results,
    }


def _tool_read_competitor_analysis(
    tool_input: dict[str, Any],
    db: Session,
    client_id: str,
    **_kwargs: Any,
) -> dict[str, Any]:
    scan = _latest_scan(db, client_id)
    if not scan:
        return {"error": "No completed scan found."}

    competitor_filter = (tool_input.get("competitor_name") or "").strip().lower()

    rows = db.query(ScanResult).filter(
        ScanResult.client_id == client_id,
        ScanResult.scan_id == scan.id,
    ).all()

    # Aggregate competitor counts across providers
    competitor_totals: dict[str, dict[str, int]] = {}
    client_mentions = 0
    client_total = 0

    for row in rows:
        client_mentions += row.mention_count or 0
        client_total += row.total_questions or 0
        for name, count in _safe_json(row.competitor_data).items():
            if competitor_filter and competitor_filter not in name.lower():
                continue
            if name not in competitor_totals:
                competitor_totals[name] = {"total_mentions": 0, "by_provider": {}}
            competitor_totals[name]["total_mentions"] += int(count)
            competitor_totals[name]["by_provider"][row.provider] = (
                competitor_totals[name]["by_provider"].get(row.provider, 0) + int(count)
            )

    sorted_competitors = sorted(
        competitor_totals.items(), key=lambda x: -x[1]["total_mentions"]
    )

    return {
        "client_mentions": client_mentions,
        "client_total_questions": client_total,
        "client_mention_rate": round(client_mentions / client_total * 100, 1) if client_total else 0,
        "competitors": [
            {
                "name": name,
                "total_mentions": data["total_mentions"],
                "by_provider": data["by_provider"],
            }
            for name, data in sorted_competitors[:10]
        ],
    }


def _tool_read_citation_sources(
    tool_input: dict[str, Any],
    db: Session,
    client_id: str,
    **_kwargs: Any,
) -> dict[str, Any]:
    scan = _latest_scan(db, client_id)
    if not scan:
        return {"error": "No completed scan found."}

    provider_filter = (tool_input.get("provider") or "").strip().lower()
    owner_filter = (tool_input.get("owner_type") or "").strip().lower()

    query = db.query(ScanCitation).filter(
        ScanCitation.client_id == client_id,
        ScanCitation.scan_id == scan.id,
        ScanCitation.source_domain.isnot(None),
    )
    if provider_filter:
        query = query.filter(ScanCitation.provider == provider_filter)
    if owner_filter:
        query = query.filter(ScanCitation.owner_type == owner_filter)

    citations = query.all()

    domain_counts: dict[str, dict[str, Any]] = {}
    for cit in citations:
        domain = cit.source_domain or ""
        if domain not in domain_counts:
            domain_counts[domain] = {
                "domain": domain,
                "count": 0,
                "providers": set(),
                "owner_type": cit.owner_type,
            }
        domain_counts[domain]["count"] += 1
        domain_counts[domain]["providers"].add(cit.provider or "")

    results = sorted(domain_counts.values(), key=lambda x: -x["count"])
    for r in results:
        r["providers"] = list(r["providers"])

    return {"sources": results[:20]}


def _tool_read_client_profile(
    tool_input: dict[str, Any],
    db: Session,
    client_id: str,
    **_kwargs: Any,
) -> dict[str, Any]:
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        return {"error": "Client not found."}

    context = db.query(ClientContext).filter(
        ClientContext.client_id == client_id,
        ClientContext.status == "confirmed",
    ).first()
    profile = _safe_json(context.profile_json if context else None)

    return {
        "name": client.name,
        "url": client.url,
        "industry": client.industry,
        "location": client.location,
        "profile": profile if isinstance(profile, dict) else {},
    }


def _tool_read_action_details(
    tool_input: dict[str, Any],
    db: Session,
    client_id: str,
    **_kwargs: Any,
) -> dict[str, Any]:
    action_id = (tool_input.get("action_id") or "").strip()
    if not action_id:
        return {"error": "action_id is required."}

    action = db.query(Action).filter(
        Action.id == action_id,
        Action.client_id == client_id,
    ).first()
    if not action:
        return {"error": f"Action {action_id} not found."}

    return {
        "id": action.id,
        "title": action.title,
        "description": action.description,
        "priority": action.priority,
        "evidence_summary": action.evidence_summary,
        "remediation_type": action.remediation_type,
        "impact_estimate": action.impact_estimate,
        "target_questions": _safe_json(action.target_questions_json),
        "target_providers": _safe_json(action.target_providers_json),
        "evidence_json": _safe_json(action.evidence_json),
        "status": action.status,
    }


def _tool_list_visibility_gaps(
    tool_input: dict[str, Any],
    db: Session,
    client_id: str,
    client_name: str = "",
    **_kwargs: Any,
) -> dict[str, Any]:
    limit = min(int(tool_input.get("limit") or 5), 10)
    scan = _latest_scan(db, client_id)
    if not scan:
        return {"error": "No completed scan found."}

    # Get top open actions as primary gap signals
    actions = db.query(Action).filter(
        Action.client_id == client_id,
        Action.status == "open",
    ).order_by(
        Action.sort_order.asc(),
        Action.score.desc(),
    ).limit(limit).all()

    gaps = []
    for action in actions:
        gaps.append({
            "title": action.title,
            "priority": action.priority,
            "evidence": action.evidence_summary,
            "remediation": action.remediation_type,
            "impact_estimate": action.impact_estimate,
            "target_providers": _safe_json(action.target_providers_json),
        })

    # Provider score summary
    rows = db.query(ScanResult).filter(
        ScanResult.client_id == client_id,
        ScanResult.scan_id == scan.id,
    ).all()
    provider_scores: dict[str, dict[str, float]] = {}
    for row in rows:
        p = row.provider
        if p not in provider_scores:
            provider_scores[p] = {"total": 0, "mentions": 0}
        provider_scores[p]["total"] += row.total_questions or 0
        provider_scores[p]["mentions"] += row.mention_count or 0

    scores = {
        p: round(d["mentions"] / d["total"] * 100, 1) if d["total"] else 0
        for p, d in provider_scores.items()
    }

    return {
        "scan_id": scan.id,
        "provider_scores": scores,
        "top_gaps": gaps,
    }


def _tool_save_content_draft(
    tool_input: dict[str, Any],
    db: Session,
    client_id: str,
    user_id: str,
    conversation_id: str | None = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    title = str(tool_input.get("title") or "").strip()[:160]
    content = str(tool_input.get("content") or "").strip()[:12000]
    content_type = str(tool_input.get("content_type") or "other").strip()
    source_action_id = (tool_input.get("source_action_id") or "").strip() or None

    if not title or not content:
        return {"error": "title and content are required."}

    valid_types = {
        "blog_post", "faq_page", "linkedin_post",
        "platform_listing", "review_response", "schema_markup", "other",
    }
    if content_type not in valid_types:
        content_type = "other"

    now = datetime.now(timezone.utc)
    draft = ContentDraft(
        id=str(uuid.uuid4()),
        conversation_id=conversation_id,
        client_id=client_id,
        created_by=user_id,
        content_type=content_type,
        title=title,
        content=content,
        status="pending_review",
        source_action_id=source_action_id,
        created_at=now,
        updated_at=now,
    )
    db.add(draft)
    db.flush()

    return {
        "saved": True,
        "draft_id": draft.id,
        "title": draft.title,
        "content_type": draft.content_type,
        "status": draft.status,
    }


def _tool_update_action_status(
    tool_input: dict[str, Any],
    db: Session,
    client_id: str,
    user_id: str,
    **_kwargs: Any,
) -> dict[str, Any]:
    action_id = (tool_input.get("action_id") or "").strip()
    new_status = (tool_input.get("status") or "").strip()

    if not action_id:
        return {"error": "action_id is required."}
    if new_status not in {"done", "dismissed"}:
        return {"error": "status must be 'done' or 'dismissed'."}

    action = db.query(Action).filter(
        Action.id == action_id,
        Action.client_id == client_id,
    ).first()
    if not action:
        return {"error": f"Action {action_id} not found."}

    action.status = new_status
    if new_status == "done":
        action.completed_at = datetime.now(timezone.utc)
    db.flush()

    return {
        "updated": True,
        "action_id": action.id,
        "title": action.title,
        "new_status": new_status,
    }


def _tool_list_content_drafts(
    tool_input: dict[str, Any],
    db: Session,
    client_id: str,
    **_kwargs: Any,
) -> dict[str, Any]:
    status_filter = (tool_input.get("status") or "").strip()
    query = db.query(ContentDraft).filter(ContentDraft.client_id == client_id)
    if status_filter:
        query = query.filter(ContentDraft.status == status_filter)
    drafts = query.order_by(ContentDraft.updated_at.desc()).limit(20).all()
    return {
        "drafts": [
            {
                "id": d.id,
                "title": d.title,
                "content_type": d.content_type,
                "status": d.status,
                "created_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d in drafts
        ]
    }


def _tool_export_content_draft(
    tool_input: dict[str, Any],
    db: Session,
    client_id: str,
    **_kwargs: Any,
) -> dict[str, Any]:
    """Return a download URL for an export — the actual generation happens in the HTTP endpoint."""
    draft_id = (tool_input.get("draft_id") or "").strip()
    fmt = (tool_input.get("format") or "pdf").strip().lower()

    if not draft_id:
        return {"error": "draft_id is required."}
    if fmt not in {"pdf", "docx"}:
        return {"error": "format must be 'pdf' or 'docx'."}

    draft = db.query(ContentDraft).filter(
        ContentDraft.id == draft_id,
        ContentDraft.client_id == client_id,
    ).first()
    if not draft:
        return {"error": f"Draft {draft_id} not found."}
    if draft.status in {"archived", "rejected"}:
        return {"error": f"Cannot export a draft with status '{draft.status}'."}

    # Return the URL path so the assistant can present a clickable link
    download_url = f"/api/proxy/v1/assistant/content-drafts/{draft_id}/export?format={fmt}"
    return {
        "export_ready": True,
        "draft_id": draft_id,
        "title": draft.title,
        "format": fmt,
        "download_url": download_url,
    }


# ── Dispatcher ───────────────────────────────────────────────────────────────

_TOOL_HANDLERS = {
    "read_scan_findings": _tool_read_scan_findings,
    "read_competitor_analysis": _tool_read_competitor_analysis,
    "read_citation_sources": _tool_read_citation_sources,
    "read_client_profile": _tool_read_client_profile,
    "read_action_details": _tool_read_action_details,
    "list_visibility_gaps": _tool_list_visibility_gaps,
    "save_content_draft": _tool_save_content_draft,
    "update_action_status": _tool_update_action_status,
    "list_content_drafts": _tool_list_content_drafts,
    "export_content_draft": _tool_export_content_draft,
}

# Human-readable labels shown in the frontend activity indicator
TOOL_ACTIVITY_LABELS: dict[str, str] = {
    "read_scan_findings": "Analyzing scan data...",
    "read_competitor_analysis": "Analyzing competitor mentions...",
    "read_citation_sources": "Reading citation sources...",
    "read_client_profile": "Reading business profile...",
    "read_action_details": "Loading action details...",
    "list_visibility_gaps": "Identifying visibility gaps...",
    "save_content_draft": "Saving content draft...",
    "update_action_status": "Updating action status...",
    "list_content_drafts": "Loading content drafts...",
    "export_content_draft": "Preparing export...",
}


def execute_tool(
    tool_name: str,
    tool_input: dict[str, Any],
    db: Session,
    client_id: str,
    user_id: str,
    client_name: str = "",
    conversation_id: str | None = None,
) -> dict[str, Any]:
    """Dispatch a tool call to its handler. Returns a result dict."""
    handler = _TOOL_HANDLERS.get(tool_name)
    if not handler:
        return {"error": f"Unknown tool: {tool_name}"}
    try:
        return handler(
            tool_input,
            db=db,
            client_id=client_id,
            user_id=user_id,
            client_name=client_name,
            conversation_id=conversation_id,
        )
    except Exception as exc:
        return {"error": f"Tool execution failed: {type(exc).__name__}"}
