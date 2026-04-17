"""
Compare API vs browser output: business names and links overlap.
Produce report with ~95% equivalence metrics.
"""
import json
import re
import sys
from pathlib import Path


def _normalize_url(url: str) -> str:
    u = url.lower().strip().rstrip("/")
    u = re.sub(r"#.*$", "", u)
    if u.startswith("https://"):
        u = "http://" + u[8:]
    elif u.startswith("http://"):
        pass
    return u


def _extract_links(text: str) -> set[str]:
    urls = set()
    for m in re.finditer(r"\[([^\]]*)\]\(([^)]+)\)", text):
        urls.add(_normalize_url(m.group(2)))
    for m in re.finditer(r'href="([^"]+)"', text, re.I):
        urls.add(_normalize_url(m.group(1)))
    return urls


def _extract_business_names(text: str) -> set[str]:
    """Heuristic: capitalize-first tokens in numbered-list items, proper nouns before — or :"""
    names = set()
    for m in re.finditer(r"(?:^|\n)\s*\d+[.)]\s*([^—:\n]+?)(?:\s*[—:]|$)", text):
        name = m.group(1).strip()
        name = re.sub(r"^The\s+", "", name, flags=re.I).strip()
        name = re.sub(r"[,.]$", "", name).strip()
        if len(name) > 2:
            names.add(name.lower())
    return names


def _overlap(s_api: set, s_browser: set) -> float:
    if not s_browser:
        return 1.0 if not s_api else 0.0
    inter = len(s_api & s_browser)
    return inter / len(s_browser)


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--api",
        type=Path,
        default=Path(__file__).resolve().parent / "results" / "api_output.json",
    )
    parser.add_argument(
        "--browser",
        type=Path,
        default=Path(__file__).resolve().parent / "results" / "browser_output.json",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parent / "results" / "comparison_report.json",
    )
    args = parser.parse_args()

    if not args.api.exists():
        print("API output not found:", args.api, file=sys.stderr)
        sys.exit(1)

    api_data = json.loads(args.api.read_text(encoding="utf-8"))
    if not args.browser.exists():
        print("Browser output not found; run test_harness --mode both first", file=sys.stderr)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        report = {
            "api_only": True,
            "message": "Browser output not found; run test_harness --mode both first",
            "api_queries": len(api_data),
        }
        args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print("Wrote API-only report to", args.out)
        sys.exit(0)

    browser_data = json.loads(args.browser.read_text(encoding="utf-8"))

    # Build query -> {api, browser} map
    by_query: dict[str, dict] = {}
    for r in api_data:
        by_query.setdefault(r["query"], {})["api"] = r
    for r in browser_data:
        by_query.setdefault(r["query"], {})["browser"] = r

    report_entries = []
    passes = 0
    for q, both in by_query.items():
        api_r = both.get("api")
        browser_r = both.get("browser")
        if not api_r or not browser_r or api_r.get("error") or browser_r.get("error"):
            report_entries.append({
                "query": q,
                "status": "skipped",
                "reason": "missing or error",
            })
            continue

        api_text = (api_r.get("response") or {}).get("text") or ""
        api_links = (api_r.get("response") or {}).get("links") or []
        api_link_strs = {_normalize_url(l.get("url", "")) for l in api_links if l.get("url")}
        api_link_strs |= _extract_links(api_text)

        browser_text = (browser_r.get("response") or {}).get("text") or ""
        browser_links = (browser_r.get("response") or {}).get("links") or []
        browser_link_strs = {_normalize_url(l.get("url", "")) for l in browser_links if l.get("url")}
        browser_link_strs |= _extract_links(browser_text)

        api_names = _extract_business_names(api_text)
        browser_names = _extract_business_names(browser_text)

        link_overlap = _overlap(api_link_strs, browser_link_strs)
        name_overlap = _overlap(api_names, browser_names)
        threshold = 0.95
        link_ok = link_overlap >= threshold
        name_ok = name_overlap >= threshold
        entry_pass = link_ok and name_ok
        if entry_pass:
            passes += 1

        report_entries.append({
            "query": q,
            "status": "pass" if entry_pass else "fail",
            "link_overlap": round(link_overlap, 4),
            "name_overlap": round(name_overlap, 4),
            "link_ok": link_ok,
            "name_ok": name_ok,
        })

    n_valid = sum(1 for e in report_entries if e.get("status") in ("pass", "fail"))
    min_pass = (int(0.95 * n_valid) + 1) if n_valid else 0
    overall_pass = passes >= min_pass

    report = {
        "api_only": False,
        "overall_pass": overall_pass,
        "passes": passes,
        "min_pass": min_pass,
        "valid_queries": n_valid,
        "entries": report_entries,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("Comparison report written to", args.out)
    print(f"Overall: {'PASS' if overall_pass else 'FAIL'} ({passes}/{n_valid} queries)")


if __name__ == "__main__":
    main()
