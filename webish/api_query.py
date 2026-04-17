"""
API path for webish: Chat Completions used by webish().

Note: earlier versions used `gpt-4o-search-preview` to get built-in web-search behavior.
This can fail with `429 insufficient_quota` if that search-specific model has no quota
for your project/organization, so the default model is now GPT-5.1 Chat.
"""
import os
import re
import time
from pathlib import Path

# Load .env: webish folder first, then repo root
_webish_dir = Path(__file__).resolve().parent
_ENV_FILE = _webish_dir / ".env"
if not _ENV_FILE.exists():
    _ENV_FILE = _webish_dir.parent.parent / ".env"  # repo root
if _ENV_FILE.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_ENV_FILE)
    except ImportError:
        with open(_ENV_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    k, v = k.strip(), v.strip().strip('"').strip("'")
                    if k and k not in os.environ:
                        os.environ[k] = v

from openai import OpenAI
from openai import RateLimitError

# Model used for webish() calls.
# We try GPT-5.1 first (what you asked for), but if your project/org doesn't have quota
# for that specific model we fall back to a model that usually has quota.
WEBISH_MODEL = "gpt-5.1-chat-latest"
WEBISH_MODEL_FALLBACK = "gpt-4o-mini"
WEBISH_TEMP = 0.4

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Copy webish/.env.example to .env and set OPENAI_API_KEY."
        )
    if _client is None:
        _client = OpenAI(api_key=key)
    return _client


def _load_browser_like_prompt() -> str:
    p = Path(__file__).resolve().parent / "prompts" / "browser_like.txt"
    if p.exists():
        return p.read_text(encoding="utf-8").strip()
    return (
        "You are a helpful assistant. "
        "If you include sources or links, format them inline as [text](url). "
        "Use numbered lists for recommendations."
    )


SYSTEM_PROMPT: str = _load_browser_like_prompt()


def _parse_links_from_text(text: str) -> list[dict[str, str]]:
    """Extract [text](url) links from response text."""
    links = []
    for m in re.finditer(r"\[([^\]]*)\]\(([^)]+)\)", text):
        links.append({"text": m.group(1), "url": m.group(2)})
    return links


def api_query(query: str) -> dict:
    """
    Run a web-search-backed query via OpenAI Chat Completions.
    Returns {text, links} in normalized format.
    On 429: retry with exponential backoff (2^n sec, max 3 retries); respect Retry-After.
    If we specifically hit `insufficient_quota` for the primary model, we fall back to
    `WEBISH_MODEL_FALLBACK`.
    """
    client = _get_client()
    system = SYSTEM_PROMPT

    # Try primary model first; if it's blocked by insufficient quota, try fallback.
    model_candidates = [WEBISH_MODEL]
    if WEBISH_MODEL_FALLBACK:
        model_candidates.append(WEBISH_MODEL_FALLBACK)

    last_err = None
    for model_i, model in enumerate(model_candidates):
        for attempt in range(4):  # 1 initial + 3 retries
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": query},
                    ],
                )
                content = response.choices[0].message.content or ""
                links = _parse_links_from_text(content)
                return {"text": content, "links": links}
            except RateLimitError as e:
                last_err = e

                # If the primary model has no quota, don't bother retrying it.
                if "insufficient_quota" in str(e) and model_i == 0:
                    break

                if attempt >= 3:
                    raise

                retry_after = None
                if hasattr(e, "response") and e.response is not None:
                    headers = getattr(e.response, "headers", None) or {}
                    retry_after = (headers.get("Retry-After") or headers.get("retry-after"))

                wait = 2**attempt
                if retry_after is not None:
                    try:
                        wait = int(retry_after)
                    except (ValueError, TypeError):
                        pass
                time.sleep(wait)
            except Exception:
                raise

    raise last_err


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", required=True, help="Query string")
    args = parser.parse_args()
    result = api_query(args.query)
    print(result["text"])
    if result["links"]:
        print("\n--- Links ---")
        for lnk in result["links"]:
            print(f"  [{lnk['text']}]({lnk['url']})")


if __name__ == "__main__":
    main()
