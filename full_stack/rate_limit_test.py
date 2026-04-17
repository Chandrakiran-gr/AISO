"""
One-off test: measure T (avg sec per webish call) and L (API rate limit from headers).
Run from repo root: python full_stack/rate_limit_test.py
"""
import os
import sys
import time
from pathlib import Path

_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from dotenv import load_dotenv
load_dotenv(_repo_root / ".env")

from openai import OpenAI

# Same model as webish
MODEL = "gpt-4o-search-preview"
NUM_CALLS = 5
TEST_QUERY = "What is 2+2? Reply in one short sentence."

def main():
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        print("OPENAI_API_KEY not set. Set it in .env at repo root.")
        sys.exit(1)

    client = OpenAI(api_key=key)
    times = []
    limit_requests = remaining_requests = reset_requests = None
    limit_tokens = remaining_tokens = reset_tokens = None

    print(f"Making {NUM_CALLS} requests to {MODEL} (simple query)...")
    for i in range(NUM_CALLS):
        t0 = time.perf_counter()
        try:
            raw = client.chat.completions.with_raw_response.create(
                model=MODEL,
                messages=[{"role": "user", "content": TEST_QUERY}],
            )
            elapsed = time.perf_counter() - t0
            times.append(elapsed)
            # Parse headers (first response wins for limit values)
            h = raw.headers
            if limit_requests is None:
                limit_requests = h.get("x-ratelimit-limit-requests")
                remaining_requests = h.get("x-ratelimit-remaining-requests")
                reset_requests = h.get("x-ratelimit-reset-requests")
                limit_tokens = h.get("x-ratelimit-limit-tokens")
                remaining_tokens = h.get("x-ratelimit-remaining-tokens")
                reset_tokens = h.get("x-ratelimit-reset-tokens")
            print(f"  {i+1}/{NUM_CALLS}: {elapsed:.1f}s")
        except Exception as e:
            print(f"  {i+1}/{NUM_CALLS}: ERROR {e}")
            break

    if not times:
        print("No successful calls.")
        sys.exit(1)

    T_avg = sum(times) / len(times)
    T_min, T_max = min(times), max(times)

    print()
    print("--- Results ---")
    print(f"  T (avg sec per request): {T_avg:.1f}s  (min={T_min:.1f}s, max={T_max:.1f}s)")
    print("  L (from API headers):")
    print(f"    x-ratelimit-limit-requests:    {limit_requests}")
    print(f"    x-ratelimit-remaining-requests: {remaining_requests}")
    print(f"    x-ratelimit-reset-requests:    {reset_requests}")
    print(f"    x-ratelimit-limit-tokens:      {limit_tokens}")
    print(f"    x-ratelimit-remaining-tokens:  {remaining_tokens}")
    print(f"    x-ratelimit-reset-tokens:      {reset_tokens}")

    if limit_requests is not None:
        try:
            L = int(limit_requests)
            X_suggested = max(1, min(L, int(L * T_avg / 60)))
            print()
            print(f"  Suggested X (workers): ~{X_suggested}  (formula: min(L, L*T/60) with L={L}, T={T_avg:.1f}s)")
        except (ValueError, TypeError):
            pass

if __name__ == "__main__":
    main()
