"""
Browser path for webish: Playwright automation to ChatGPT.
Fallback/verification path — use sparingly.
"""
import argparse
import json
import os
import re
import time
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

# Ensure repo root on path when run as script (so webish resolves)
_path = Path(__file__).resolve().parent.parent
if str(_path) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(_path))

from webish.selectors import CHAT_INPUT, CHAT_INPUT_FALLBACK, LAST_ASSISTANT_MESSAGE

load_dotenv()

HEADLESS = os.getenv("WEBISH_BROWSER_HEADLESS", "true").lower() in ("true", "1", "yes")
SESSION_PATH = os.getenv("CHATGPT_SESSION_PATH")
RESPONSE_TIMEOUT = int(os.getenv("WEBISH_RESPONSE_TIMEOUT", "60")) * 1000  # ms


def _launch_browser():
    """Launch Chromium/Chrome and create context. Uses real Chrome if available to reduce bot detection. Loads session from CHATGPT_SESSION_PATH if present."""
    pw = sync_playwright().start()
    launch_opts = {
        "headless": HEADLESS,
        "args": ["--disable-blink-features=AutomationControlled"],
        "ignore_default_args": ["--enable-automation"],
    }
    try:
        browser = pw.chromium.launch(channel="chrome", **launch_opts)
    except Exception:
        browser = pw.chromium.launch(**launch_opts)
    if SESSION_PATH and os.path.isfile(SESSION_PATH):
        context = browser.new_context(storage_state=SESSION_PATH)
    else:
        context = browser.new_context()
    context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
    return pw, browser, context


def _save_session(context) -> None:
    """Save context storage state to CHATGPT_SESSION_PATH. Create .session/ dir if needed."""
    if not SESSION_PATH:
        return
    parent = os.path.dirname(SESSION_PATH)
    if parent:
        os.makedirs(parent, exist_ok=True)
    context.storage_state(path=SESSION_PATH)


def _navigate_to_chatgpt(context) -> object:
    """Navigate to ChatGPT; wait for page load. Returns page (chat UI or login prompt visible)."""
    page = context.new_page()
    page.goto("https://chat.openai.com", wait_until="load", timeout=30000)
    return page


def _inject_and_submit(page, query: str) -> None:
    """Type query into chat input and submit. ChatGPT's textarea can be hidden in DOM; use attached + force."""
    for selector in (CHAT_INPUT, CHAT_INPUT_FALLBACK):
        inp = page.locator(selector).first
        try:
            inp.wait_for(state="attached", timeout=10000)
            break
        except Exception:
            continue
    else:
        raise RuntimeError("Could not find chat input textarea")
    inp.fill(query, force=True)
    page.keyboard.press("Enter")  # fill() focuses element; keyboard works without actionability checks


def _wait_for_completion(page) -> None:
    """Wait for browser to finish responding: last assistant message text stops changing."""
    stability_sec = 2.0
    poll_interval = 0.35
    last_text = ""
    stable_since = None
    deadline = time.monotonic() + (RESPONSE_TIMEOUT / 1000)
    while time.monotonic() < deadline:
        blocks = page.locator(LAST_ASSISTANT_MESSAGE)
        if blocks.count() == 0:
            time.sleep(poll_interval)
            continue
        text = blocks.last.inner_text()
        if text == last_text and text:
            if stable_since is None:
                stable_since = time.monotonic()
            elif time.monotonic() - stable_since >= stability_sec:
                break
        else:
            stable_since = None
        last_text = text
        time.sleep(poll_interval)
    time.sleep(1.0)  # Let DOM settle


def _open_chatgpt():
    """Launch, create context (load session if exists), navigate to ChatGPT. Returns (pw, browser, context, page)."""
    pw, browser, context = _launch_browser()
    page = _navigate_to_chatgpt(context)
    return pw, browser, context, page


def _smoke_test() -> dict:
    """Navigate to example.com; return title and page content. Verifies page load works."""
    pw, browser, context = _launch_browser()
    try:
        page = context.new_page()
        page.goto("https://example.com")
        title = page.title()
        content = page.content()
        return {"title": title, "content": content[:500]}
    finally:
        context.close()
        browser.close()
        pw.stop()


def _extract_links_js() -> str:
    """JS: extract citation links from last assistant message and nearby DOM (ChatGPT varies structure)."""
    return """
    () => {
        const blocks = document.querySelectorAll("[data-message-author-role='assistant']");
        if (!blocks.length) return [];
        const last = blocks[blocks.length - 1];
        const root = document.querySelector("main") || document.body;
        const anchors = root.querySelectorAll("a[href^='http']");
        const lastRect = last.getBoundingClientRect();
        const seen = new Set();
        const out = [];
        for (const a of anchors) {
            const href = (a.getAttribute("href") || "").trim();
            if (!href || seen.has(href)) continue;
            if (href.includes("openai.com") || href.includes("apple.com") || href.startsWith("javascript:")) continue;
            const rect = a.getBoundingClientRect();
            if (rect.top < lastRect.top - 500) continue;
            seen.add(href);
            const label = (a.textContent || href).trim().slice(0, 200);
            out.push({ text: label || href, url: href });
        }
        return out;
    }
    """


def _parse_urls_from_text(text: str) -> list[dict]:
    """Extract URLs from text: markdown [label](url) and bare https?:// URLs."""
    links = []
    seen = set()
    for m in re.finditer(r"\[([^\]]*)\]\(([^)]+)\)", text):
        url = m.group(2).strip()
        if url.startswith("http") and url not in seen:
            seen.add(url)
            links.append({"text": (m.group(1) or url)[:200], "url": url})
    for m in re.finditer(r"https?://[^\s)\]]+", text):
        url = m.group(0).rstrip(".,;:)")
        if url not in seen and "openai.com" not in url:
            seen.add(url)
            links.append({"text": url[:200], "url": url})
    return links


def _extract_response(page) -> dict:
    """Find last assistant message, extract text and links. Return {text, links: [{text, url}]}."""
    blocks = page.locator(LAST_ASSISTANT_MESSAGE)
    if blocks.count() == 0:
        return {"text": "", "links": []}
    last = blocks.last
    text = last.inner_text()
    links = []
    try:
        links = page.evaluate(_extract_links_js())
    except Exception:
        pass
    if not links:
        for a in last.locator("a[href^='http']").all():
            try:
                href = a.get_attribute("href")
                if href and "openai.com" not in href:
                    label = a.inner_text() or href
                    links.append({"text": (label or href)[:200], "url": href})
            except Exception:
                pass
    if not links:
        try:
            html = last.inner_html()
            for m in re.finditer(r'href=["\'](https?://[^"\']+)["\']', html):
                u = m.group(1)
                if "openai.com" not in u and not any(l["url"] == u for l in links):
                    links.append({"text": u[:200], "url": u})
        except Exception:
            pass
    if not links:
        links = _parse_urls_from_text(text)
    return {"text": text, "links": links}


def browser_query(query: str) -> dict:
    """Run full browser flow: open ChatGPT, submit query, wait, extract. Returns {text, links}."""
    pw, browser, context, page = _open_chatgpt()
    try:
        _inject_and_submit(page, query)
        try:
            _wait_for_completion(page)
        except Exception as e:
            err_msg = str(e).lower()
            if "timeout" in err_msg or "timed out" in err_msg:
                partial = _extract_response(page)
                partial["error"] = "timeout"
                return partial
            raise
        return _extract_response(page)
    finally:
        context.close()
        browser.close()
        pw.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", type=str, help="Query to submit (not yet implemented)")
    parser.add_argument("--save-session", action="store_true", help="First-run: open ChatGPT, wait for manual login, save session")
    parser.add_argument("--smoke", action="store_true", help="Run smoke test (example.com)")
    args = parser.parse_args()

    if args.save_session:
        pw, browser, context, page = _open_chatgpt()
        try:
            print("Log in to ChatGPT in the browser. Session will auto-save when chat UI appears...")
            for selector in (CHAT_INPUT, CHAT_INPUT_FALLBACK):
                try:
                    page.locator(selector).first.wait_for(state="attached", timeout=300000)  # 5 min
                    break
                except Exception:
                    continue
            _save_session(context)
            print(f"Session saved to {SESSION_PATH or 'CHATGPT_SESSION_PATH not set'}")
        finally:
            context.close()
            browser.close()
            pw.stop()
    elif args.query:
        result = browser_query(args.query)
        print(json.dumps(result, indent=2))
    else:
        result = _smoke_test()
        print("title:", result["title"])
        print("content preview:", result["content"][:200], "...")
