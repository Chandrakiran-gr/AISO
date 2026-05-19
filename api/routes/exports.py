"""Content export routes for AISO assistant drafts.

Endpoints:
  GET /assistant/content-drafts/{draft_id}/export?format=pdf
  GET /assistant/content-drafts/{draft_id}/export?format=docx

Returns a binary file download streamed directly to the client.
Access is gated by the same client-ownership check as all other
assistant endpoints (no BOLA: user must own the draft's client).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from api.auth import get_current_user_id
from api.content_export import export_draft
from api.database import Client, ClientContext, ContentDraft, get_db

router = APIRouter(prefix="/assistant", tags=["assistant"])

ALLOWED_FORMATS = {"pdf", "docx"}


def _client_name_for_draft(db: Session, draft: ContentDraft) -> str:
    """Return the client name associated with a draft."""
    client = db.query(Client).filter(Client.id == draft.client_id).first()
    return client.name if client else "Unknown"


@router.get(
    "/content-drafts/{draft_id}/export",
    summary="Export a content draft as PDF or DOCX",
    response_description="Binary file download (application/pdf or .docx MIME type)",
)
async def export_content_draft(
    draft_id: str,
    format: str = Query(default="pdf", description="Export format: 'pdf' or 'docx'"),
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    """Download a content draft as a formatted PDF or Word document.

    The draft must belong to a client that the authenticated user owns.
    The draft must be in 'approved' or 'pending_review' status — archived
    and rejected drafts are not exportable.
    """
    fmt = format.strip().lower()
    if fmt not in ALLOWED_FORMATS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported format '{fmt}'. Use 'pdf' or 'docx'.",
        )

    # Load draft
    draft = db.query(ContentDraft).filter(ContentDraft.id == draft_id).first()
    if not draft:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Content draft not found")

    # BOLA check — user must own the draft's client
    client = db.query(Client).filter(
        Client.id == draft.client_id,
        Client.user_id == user_id,
    ).first()
    if not client:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Content draft access denied",
        )

    # Guard: don't export archived/rejected drafts
    if draft.status in {"archived", "rejected"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot export a draft with status '{draft.status}'.",
        )

    # Generate file in-memory
    try:
        file_bytes, mime_type, filename = export_draft(
            title=draft.title,
            content=draft.content,
            client_name=client.name or "",
            content_type=draft.content_type,
            fmt=fmt,  # type: ignore[arg-type]
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Export generation failed. Please try again.",
        ) from exc

    # Record the export format on the draft (non-blocking — best effort)
    try:
        draft.export_format = fmt
        db.commit()
    except Exception:
        db.rollback()

    return Response(
        content=file_bytes,
        media_type=mime_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(file_bytes)),
            "Cache-Control": "private, no-store",
        },
    )
