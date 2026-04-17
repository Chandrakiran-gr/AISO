"""
Public API: webish(query, mode="api") -> str
Returns ChatGPT-quality, web-backed answer as string with inline links.
"""
import re

from webish.api_query import api_query


def _format_result(result: dict) -> str:
    """Format {text, links} into a single string with inline [text](url)."""
    text = result.get("text", "")
    links = result.get("links", [])
    error = result.get("error")

    if not links and not error:
        return text

    # Append error note if present (e.g. browser timeout)
    if error:
        text = text.rstrip()
        if text:
            text += "\n\n"
        text += f"_[{error}]_"

    if not links:
        return text

    # Extract URLs already present as [text](url) in text
    urls_in_text = set()
    for m in re.finditer(r"\[([^\]]*)\]\(([^)]+)\)", text):
        urls_in_text.add(m.group(2).strip())

    # Append any links not already inline (common for browser path)
    appended = []
    for lnk in links:
        url = lnk.get("url", "").strip()
        if not url or url in urls_in_text:
            continue
        label = lnk.get("text", url)
        appended.append(f"[{label}]({url})")

    if appended:
        text = text.rstrip()
        if text and not text.endswith("\n"):
            text += "\n\n"
        text += "\n**Sources:**\n" + "\n".join(appended)

    return text


def webish(query: str, mode: str = "api") -> str:
    """
    One-call API for web-backed answers.

    Args:
        query: The question or prompt.
        mode: "api" (default) or "browser" — force path.

    Returns:
        Answer text with inline links [text](url).
    """
    if mode == "browser":
        from webish.browser_query import browser_query
        result = browser_query(query)
    else:
        result = api_query(query)

    return _format_result(result)
