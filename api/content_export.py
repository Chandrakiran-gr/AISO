"""Content export module for AISO.

Generates PDF and DOCX files from ContentDraft records.
Files are written to a secure, non-web-accessible temp directory
and served directly as binary downloads via the export endpoint.

Design choices:
- reportlab for PDF: battle-tested, no external font loading required
- python-docx for DOCX: de-facto standard, clean API
- Files are generated on-demand and not persisted between requests
- No user-supplied filenames reach the filesystem; UUIDs are used internally
"""

from __future__ import annotations

import io
import re
import textwrap
from datetime import datetime, timezone
from typing import Literal

ExportFormat = Literal["pdf", "docx"]


# ── Text helpers ──────────────────────────────────────────────────────────────

def _clean_content(raw: str) -> str:
    """Strip excess whitespace; preserve intentional double-newlines as paragraphs."""
    lines = raw.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    cleaned = "\n".join(line.rstrip() for line in lines)
    # Collapse runs of 3+ blank lines to 2
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned


def _split_paragraphs(text: str) -> list[str]:
    """Split on double-newlines; return non-empty paragraphs."""
    return [p.strip() for p in text.split("\n\n") if p.strip()]


def _is_heading(paragraph: str) -> bool:
    """Heuristic: starts with # or ALL CAPS short line."""
    if paragraph.startswith("#"):
        return True
    first_line = paragraph.split("\n")[0].strip()
    return (
        first_line.isupper()
        and len(first_line) < 100
        and not first_line.endswith(".")
    )


def _heading_text(paragraph: str) -> str:
    return re.sub(r"^#+\s*", "", paragraph.split("\n")[0]).strip()


def _is_list_item(line: str) -> bool:
    return bool(re.match(r"^[-*•]\s+", line.strip())) or bool(re.match(r"^\d+\.\s+", line.strip()))


def _strip_list_marker(line: str) -> str:
    return re.sub(r"^[-*•\d]+\.?\s+", "", line.strip())


# ── PDF export ────────────────────────────────────────────────────────────────

def _export_pdf(title: str, content: str, client_name: str, content_type: str) -> bytes:
    """Generate a clean PDF using reportlab."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    except ImportError as exc:
        raise RuntimeError(
            "reportlab is required for PDF export. Run: pip install reportlab"
        ) from exc

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        rightMargin=2.5 * cm,
        leftMargin=2.5 * cm,
        topMargin=2.8 * cm,
        bottomMargin=2.5 * cm,
        title=title,
        author="AISO Global",
        subject=f"{content_type.replace('_', ' ').title()} — {client_name}",
    )

    # ── Styles ──
    base_styles = getSampleStyleSheet()
    DARK = colors.HexColor("#0f1117")
    TEAL = colors.HexColor("#00d4aa")
    MUTED = colors.HexColor("#8b94a8")

    style_title = ParagraphStyle(
        "AisoTitle",
        parent=base_styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=22,
        leading=28,
        textColor=DARK,
        spaceAfter=6,
    )
    style_meta = ParagraphStyle(
        "AisoMeta",
        parent=base_styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=13,
        textColor=MUTED,
        spaceAfter=18,
    )
    style_h2 = ParagraphStyle(
        "AisoH2",
        parent=base_styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=18,
        textColor=DARK,
        spaceBefore=14,
        spaceAfter=5,
    )
    style_body = ParagraphStyle(
        "AisoBody",
        parent=base_styles["Normal"],
        fontName="Helvetica",
        fontSize=10.5,
        leading=16,
        textColor=DARK,
        spaceAfter=8,
    )
    style_bullet = ParagraphStyle(
        "AisoBullet",
        parent=base_styles["Normal"],
        fontName="Helvetica",
        fontSize=10.5,
        leading=15,
        textColor=DARK,
        leftIndent=14,
        bulletIndent=0,
        spaceBefore=1,
        spaceAfter=1,
    )
    style_footer = ParagraphStyle(
        "AisoFooter",
        parent=base_styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        leading=11,
        textColor=MUTED,
    )

    story = []

    # ── Title block ──
    story.append(Paragraph(_escape_xml(title), style_title))
    now_str = datetime.now(timezone.utc).strftime("%B %d, %Y")
    story.append(Paragraph(
        f"{client_name} · {content_type.replace('_', ' ').title()} · {now_str}",
        style_meta,
    ))
    story.append(Spacer(1, 0.2 * cm))

    # ── Body ──
    cleaned = _clean_content(content)
    paragraphs = _split_paragraphs(cleaned)

    for para in paragraphs:
        if _is_heading(para):
            story.append(Paragraph(_escape_xml(_heading_text(para)), style_h2))
        else:
            lines = para.split("\n")
            in_list = False
            buffer_lines: list[str] = []

            for line in lines:
                if _is_list_item(line):
                    # Flush any buffered prose first
                    if buffer_lines:
                        story.append(Paragraph(_escape_xml(" ".join(buffer_lines)), style_body))
                        buffer_lines = []
                    in_list = True
                    story.append(Paragraph(
                        f"• {_escape_xml(_strip_list_marker(line))}",
                        style_bullet,
                    ))
                else:
                    if in_list and line.strip():
                        # Continuation of list item (wrapped line)
                        story.append(Paragraph(
                            f"  {_escape_xml(line.strip())}",
                            style_bullet,
                        ))
                    else:
                        in_list = False
                        if line.strip():
                            buffer_lines.append(line.strip())

            if buffer_lines:
                story.append(Paragraph(_escape_xml(" ".join(buffer_lines)), style_body))

        story.append(Spacer(1, 0.12 * cm))

    # ── Footer ──
    story.append(Spacer(1, 0.8 * cm))
    story.append(Paragraph(
        f"Generated by AISO Global · {now_str}",
        style_footer,
    ))

    doc.build(story)
    buf.seek(0)
    return buf.read()


def _escape_xml(text: str) -> str:
    """Escape characters that would break reportlab XML parsing."""
    return (
        text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


# ── DOCX export ───────────────────────────────────────────────────────────────

def _export_docx(title: str, content: str, client_name: str, content_type: str) -> bytes:
    """Generate a clean DOCX using python-docx."""
    try:
        from docx import Document
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.oxml.ns import qn
        from docx.shared import Pt, RGBColor
    except ImportError as exc:
        raise RuntimeError(
            "python-docx is required for DOCX export. Run: pip install python-docx"
        ) from exc

    doc = Document()

    # ── Page margins ──
    from docx.shared import Cm
    for section in doc.sections:
        section.top_margin = Cm(2.8)
        section.bottom_margin = Cm(2.5)
        section.left_margin = Cm(2.5)
        section.right_margin = Cm(2.5)

    # ── Core properties ──
    doc.core_properties.title = title
    doc.core_properties.author = "AISO Global"
    doc.core_properties.subject = f"{content_type.replace('_', ' ').title()} — {client_name}"

    # ── Title ──
    title_para = doc.add_heading(title, level=1)
    _set_heading_color(title_para, RGBColor(0x0F, 0x11, 0x17))

    # ── Meta line ──
    now_str = datetime.now(timezone.utc).strftime("%B %d, %Y")
    meta = doc.add_paragraph(f"{client_name} · {content_type.replace('_', ' ').title()} · {now_str}")
    meta.runs[0].font.size = Pt(9)
    meta.runs[0].font.color.rgb = RGBColor(0x8B, 0x94, 0xA8)
    meta.space_after = Pt(16)

    # ── Body ──
    cleaned = _clean_content(content)
    paragraphs = _split_paragraphs(cleaned)

    for para in paragraphs:
        if _is_heading(para):
            h = doc.add_heading(_heading_text(para), level=2)
            _set_heading_color(h, RGBColor(0x0F, 0x11, 0x17))
        else:
            lines = para.split("\n")
            for line in lines:
                if _is_list_item(line):
                    p = doc.add_paragraph(_strip_list_marker(line), style="List Bullet")
                    p.runs[0].font.size = Pt(10.5)
                elif line.strip():
                    p = doc.add_paragraph(line.strip())
                    if p.runs:
                        p.runs[0].font.size = Pt(10.5)

    # ── Footer ──
    doc.add_paragraph("")
    footer_p = doc.add_paragraph(f"Generated by AISO Global · {now_str}")
    if footer_p.runs:
        footer_p.runs[0].font.size = Pt(8)
        footer_p.runs[0].font.color.rgb = RGBColor(0x8B, 0x94, 0xA8)

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.read()


def _set_heading_color(para: "Any", color: "Any") -> None:
    """Apply font color to all runs in a heading paragraph."""
    for run in para.runs:
        run.font.color.rgb = color


# ── Public API ────────────────────────────────────────────────────────────────

def export_draft(
    title: str,
    content: str,
    client_name: str,
    content_type: str,
    fmt: ExportFormat,
) -> tuple[bytes, str, str]:
    """Export a content draft to bytes.

    Returns:
        (file_bytes, mime_type, safe_filename)
    """
    safe_title = re.sub(r"[^\w\s-]", "", title).strip()
    safe_title = re.sub(r"[\s-]+", "_", safe_title)[:60] or "aiso_draft"
    safe_name = safe_title.lower()

    if fmt == "pdf":
        file_bytes = _export_pdf(title, content, client_name, content_type)
        return file_bytes, "application/pdf", f"{safe_name}.pdf"
    elif fmt == "docx":
        file_bytes = _export_docx(title, content, client_name, content_type)
        mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        return file_bytes, mime, f"{safe_name}.docx"
    else:
        raise ValueError(f"Unsupported export format: {fmt}")
