"""
Test harness: run API (and optionally browser) on fixed query set.
Output: structured JSON for comparison.
"""
import json
import sys
from pathlib import Path

from webish.api_query import api_query as _api_query


def load_queries(queries_path: Path) -> list[str]:
    lines = queries_path.read_text(encoding="utf-8").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")]


def run_api(queries: list[str], out_path: Path) -> list[dict]:
    results = []
    for q in queries:
        try:
            r = _api_query(q)
            results.append({
                "query": q,
                "response": {"text": r["text"], "links": r["links"]},
                "source": "api",
                "error": None,
            })
        except Exception as e:
            results.append({
                "query": q,
                "response": None,
                "source": "api",
                "error": str(e),
            })
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    return results


def run_browser(queries: list[str], out_path: Path) -> list[dict]:
    try:
        from webish.browser_query import browser_query
    except ImportError:
        raise RuntimeError(
            "browser path not implemented. Run with --mode api only."
        )
    results = []
    for q in queries:
        try:
            r = browser_query(q)
            results.append({
                "query": q,
                "response": {"text": r["text"], "links": r["links"]},
                "source": "browser",
                "error": None,
            })
        except Exception as e:
            results.append({
                "query": q,
                "response": None,
                "source": "browser",
                "error": str(e),
            })
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    return results


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=["api", "browser", "both"],
        default="api",
        help="Which path(s) to run",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parent / "results",
        help="Output directory",
    )
    args = parser.parse_args()

    webish_dir = Path(__file__).resolve().parent
    queries_path = webish_dir / "queries.txt"
    if not queries_path.exists():
        print("queries.txt not found", file=sys.stderr)
        sys.exit(1)

    queries = load_queries(queries_path)
    out = args.out
    out.mkdir(parents=True, exist_ok=True)

    if args.mode in ("api", "both"):
        run_api(queries, out / "api_output.json")
        print("API output written to", out / "api_output.json")

    if args.mode in ("browser", "both"):
        try:
            run_browser(queries, out / "browser_output.json")
            print("Browser output written to", out / "browser_output.json")
        except RuntimeError as e:
            print(e, file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
