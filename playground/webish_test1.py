"""
Basic test script for webish: API path and browser (ChatGPT) path.
Run from repo root: python playground/webish_test1.py
"""
import sys
from pathlib import Path

# Ensure repo root on path
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from webish import webish
from webish.browser_query import browser_query

QUERY = "tell me about the best kayak tours in santa barbara "

def test_api():
    """Test webish() using the API (no browser)."""
    print("--- Testing webish() (API mode) ---")
    result = webish(QUERY, mode="api")
    print(result)
    print()


def test_browser():
    """Test browser path: opens ChatGPT, submits query, records response."""
    print("--- Testing browser path (opens ChatGPT window) ---")
    result = browser_query(QUERY)
    print("Text:", result.get("text", "")[:500])
    if result.get("links"):
        print("Links:", result["links"])
    if result.get("error"):
        print("Error:", result["error"])
    print()


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Test webish API and/or browser path")
    p.add_argument("--api", action="store_true", help="Run webish() in API mode")
    p.add_argument("--browser", action="store_true", help="Run browser_query() (opens ChatGPT)")
    p.add_argument("--query", default=QUERY, help="Query to send (default: short math)")
    args = p.parse_args()

    QUERY = args.query
    if args.api:
        test_api()
    elif args.browser:
        test_browser()
    else:
        print("Running both: API first, then browser.")
        test_api()
        test_browser()
