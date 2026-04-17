"""
Single entry point: env check -> harness -> compare report.
Usage: python -m webish.run_webish --mode api
"""
import os
import subprocess
import sys
from pathlib import Path

# Load .env: webish folder first, then repo root (same as api_query)
_root = Path(__file__).resolve().parent
_ENV = _root / ".env"
if not _ENV.exists():
    _ENV = _root.parent / ".env"  # repo root
if _ENV.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_ENV)
    except ImportError:
        with open(_ENV, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    k, v = k.strip(), v.strip().strip('"').strip("'")
                    if k and k not in os.environ:
                        os.environ[k] = v


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=["api", "full"],
        default="api",
        help="api = harness --mode api + compare; full = harness --mode both + compare",
    )
    args = parser.parse_args()

    if not os.environ.get("OPENAI_API_KEY", "").strip():
        print("OPENAI_API_KEY not set. Copy .env.example to .env and set the key.")
        sys.exit(1)

    # Use repo root as cwd so webish resolves (parent of webish)
    root = Path(__file__).resolve().parent.parent
    harness_mode = "api" if args.mode == "api" else "both"

    r = subprocess.run(
        [sys.executable, "-m", "webish.test_harness", "--mode", harness_mode],
        cwd=root,
    )
    if r.returncode != 0:
        sys.exit(r.returncode)

    r = subprocess.run(
        [sys.executable, "-m", "webish.compare_report"],
        cwd=root,
    )
    sys.exit(r.returncode if r.returncode is not None else 0)


if __name__ == "__main__":
    main()
