import sys
import re
import csv
import json
import os
import time
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from playwright.sync_api import sync_playwright

# Ensure repo root is on sys.path (same as analysis1 lines 10-13)
_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))


# ── Constants (single source of truth per SPECIFICATIONS) ────────────────────

ADDABLE_SUBSTRINGS = (
    "visit", "tourism", "chamber", "visitor", "travel",
    "directory", "cms.", "revize", "paddle", "kayak",
)

NOT_ADDABLE_EXACT = {"en.wikipedia.org"}
NOT_ADDABLE_TOKENS = (
    "wikipedia", "nps.gov", "latimes", "nytimes", "npr.org", "bbc", "cnn", "reuters", "apnews",
    "tripadvisor", "yelp.com", "facebook.com", "instagram.com", "linkedin.com", "google.com",
    "twitter.com", "x.com", "reddit.com", "pinterest.com",
)

STATE_TOKENS = ("florida", "maine", "texas", "hawaii", "oregon", "california", "arizona", "nevada", "colorado")

URL_PATH_KEYWORDS = ("add", "list", "submit", "directory", "businesses", "list-your")

# Only these path keywords count as a real "add your business" / register page (not browse/list pages)
STRONG_REGISTER_PATH_KEYWORDS = (
    "add-your", "list-your", "get-listed", "submit-listing",
    "register", "signup", "sign-up", "list-your-business", "add-your-business",
)

# Phrases that indicate the page allows listing/claiming a business (feasibility check)
FEASIBILITY_PHRASES = (
    "add your business", "list your business", "add your company", "list your company",
    "submit your business", "get listed", "claim your business", "claim this business",
    "register your business", "sign up", "add a listing", "submit a listing",
    "list your", "add your", "submit", "directory", "listing form",
    "business listing", "join our directory", "add listing",
)
FEASIBILITY_FETCH_TIMEOUT = 5  # seconds


# ── Helpers ───────────────────────────────────────────────────────────────────

def extract_links(s: str) -> list:
    """Step 3.1.1 — Extract all [text](url) markdown links. Returns list of (text, url) tuples."""
    return re.findall(r'\[([^\]]*)\]\(([^)]*)\)', s)


def extract_domain(url: str):
    """Step 3.1.2 — Extract bare domain from URL. Returns None if invalid/empty."""
    try:
        netloc = urlparse(url).netloc
    except Exception:
        return None
    if not netloc:
        return None
    d = netloc.lower().replace("www.", "", 1)
    return d if d else None


def is_addable(domain: str) -> bool:
    """Step 5.1 — True if domain matches any addable pattern."""
    d = domain.lower()
    return any(sub in d for sub in ADDABLE_SUBSTRINGS)


def is_not_addable(domain: str) -> bool:
    """Step 5.2 — True if domain matches any not-addable pattern."""
    d = domain.lower()
    if d in NOT_ADDABLE_EXACT:
        return True
    if any(tok in d for tok in NOT_ADDABLE_TOKENS):
        return True
    return False


def pick_best_url(domain: str, urls_seen: list) -> str:
    """Step 5.3 — Prefer URL whose path contains a submission keyword; else base URL."""
    for url in urls_seen:
        try:
            path = urlparse(url).path.lower()
        except Exception:
            continue
        if any(kw in path for kw in URL_PATH_KEYWORDS):
            return url
    return "https://" + domain


def direct_url(domain: str) -> str:
    """Main page OpenAI would have started at for this domain (base URL)."""
    return "https://" + domain + "/"


def path_looks_like_register(path: str) -> bool:
    """True only if path clearly suggests an add-your-business / register page."""
    if not path:
        return False
    p = path.lower()
    return any(kw in p for kw in STRONG_REGISTER_PATH_KEYWORDS)


def pick_best_register_url(domain: str, urls_seen: list) -> tuple[str | None, bool]:
    """Best cited URL that looks like a register page, or (None, False).
    Returns (url or None, from_citation). Caller uses direct when url is None."""
    for url in urls_seen:
        try:
            path = urlparse(url).path
        except Exception:
            continue
        if path_looks_like_register(path):
            return (url, True)
    return (None, False)


def parse_agent_response(text: str) -> tuple:
    """Step 7.2.2 — Parse LLM response into (action, value).

    Returns one of:
      ("FOUND", url_string)
      ("CLICK", href_string)
      ("GIVE_UP", None)
    Malformed or unrecognized output → ("GIVE_UP", None).
    """
    if not text:
        return ("GIVE_UP", None)
    line = text.strip().splitlines()[0].strip()  # use first non-empty line
    upper = line.upper()
    if upper.startswith("FOUND"):
        parts = line.split(None, 1)
        if len(parts) == 2:
            url = parts[1].strip()
            if url.startswith(("http://", "https://")):
                return ("FOUND", url)
        return ("GIVE_UP", None)
    if upper.startswith("CLICK"):
        parts = line.split(None, 1)
        if len(parts) == 2:
            href = parts[1].strip()
            if href:
                return ("CLICK", href)
        return ("GIVE_UP", None)
    if upper.startswith("GIVE_UP"):
        return ("GIVE_UP", None)
    return ("GIVE_UP", None)


def build_agent_prompt(page_url: str, links: list, business_context: dict) -> str:
    """Step 7.2.1 — Build the agent prompt for FOUND / CLICK / GIVE_UP decision.

    business_context: dict with keys like industry, products_services, geography (from datafile).
    links: list of {text, href}.
    Returns a prompt string to send to the LLM.
    """
    industry = business_context.get("industry", "")
    products = business_context.get("products_services", "")
    geography = business_context.get("geography", "")
    slug = business_context.get("slug", "")

    links_block = "\n".join(
        f"  [{i+1}] text={lk['text']!r}  href={lk['href']!r}"
        for i, lk in enumerate(links[:80])  # cap at 80 links to stay within token limits
    ) or "  (no links found on this page)"

    return f"""You are an AI agent helping to find where a business can be registered or listed on a website.

BUSINESS CONTEXT:
  Slug: {slug}
  Industry: {industry}
  Products/Services: {products}
  Geography: {geography}

CURRENT PAGE URL: {page_url}

LINKS ON THIS PAGE:
{links_block}

YOUR GOAL: Find a concrete place on this website where a business like the one above can be added, registered, or listed. Valid targets include:
  - A "Add your business" or "List your business" form or page
  - A "Submit a listing" or "Get listed" link
  - A "Contact us to register your business" page
  - A directory signup or join page

RESPOND with EXACTLY one of these three formats (no other text):

  FOUND <exact_url>
    — You found a concrete URL where the business can be added/registered.
      <exact_url> must be the full URL (starting with http/https) of that specific page or link.

  CLICK <href>
    — You see a link that might lead to the registration/listing page. Click it.
      <href> must be the exact href value from the links list above.

  GIVE_UP
    — You cannot find any way to add or register a business on this site.

Rules:
- Prefer FOUND if you already see a direct link to an add/register/list page in the links list.
- Use CLICK only if a link plausibly leads to a registration page (do not click navigation links like "Home" or "About").
- Use GIVE_UP if there is no evidence the site accepts business listings.
- Do not guess or fabricate URLs. Only use URLs/hrefs that appear in the links list or the current page URL.
"""


def get_page_content(url: str, page=None, timeout_ms: int = 15000) -> dict:
    """Step 7.1.2 — Open URL in browser and return page representation.

    Returns dict with:
      url   — current URL after navigation (may differ if redirected)
      links — list of {text, href} for all <a href> elements on the page

    If 'page' (a Playwright Page) is provided, navigate in-place.
    If not, launch a temporary headless browser (for standalone use/testing).
    """
    def _extract(pg):
        try:
            pg.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
        except Exception:
            pass  # proceed even if load timed out; extract what loaded
        current_url = pg.url
        links = []
        try:
            for el in pg.query_selector_all("a[href]"):
                try:
                    href = el.get_attribute("href") or ""
                    text = (el.inner_text() or "").strip()
                    if href:
                        links.append({"text": text, "href": href})
                except Exception:
                    continue
        except Exception:
            pass
        return {"url": current_url, "links": links}

    if page is not None:
        return _extract(page)
    else:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            pg = browser.new_page()
            try:
                result = _extract(pg)
            finally:
                browser.close()
        return result


_AGENT_MAX_STEPS = 10
_AGENT_DOMAIN_TIMEOUT = 60  # seconds total per domain


def run_agent_for_domain(domain: str, register_url: str, slug: str, datafile: dict) -> str:
    """Step 7.3.1 — Browser + LLM agent loop for a single domain.

    Opens register_url in a headless browser. Calls OpenAI with the current page
    content. Follows FOUND/CLICK/GIVE_UP instructions up to _AGENT_MAX_STEPS clicks
    or _AGENT_DOMAIN_TIMEOUT seconds total.

    Returns the integrateable URL (string) if found, or "" if not.
    """
    from openai import OpenAI

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return ""

    client = OpenAI(api_key=api_key)
    business_context = dict(datafile)
    business_context["slug"] = slug

    deadline = time.time() + _AGENT_DOMAIN_TIMEOUT

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            # Load starting URL
            content = get_page_content(register_url, page=page)

            for _step in range(_AGENT_MAX_STEPS):
                if time.time() > deadline:
                    break

                prompt = build_agent_prompt(content["url"], content["links"], business_context)
                try:
                    response = client.chat.completions.create(
                        model="gpt-4o",
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0,
                        max_tokens=200,
                    )
                    raw = response.choices[0].message.content or ""
                except Exception:
                    break

                action, value = parse_agent_response(raw)

                if action == "FOUND":
                    return value
                elif action == "CLICK":
                    # Navigate to href (handle relative URLs)
                    href = value
                    if href.startswith("http://") or href.startswith("https://"):
                        next_url = href
                    elif href.startswith("/"):
                        parsed = urlparse(content["url"])
                        next_url = f"{parsed.scheme}://{parsed.netloc}{href}"
                    else:
                        # relative path
                        base = content["url"].rstrip("/")
                        next_url = f"{base}/{href.lstrip('/')}"
                    content = get_page_content(next_url, page=page)
                else:  # GIVE_UP
                    break
        finally:
            browser.close()

    return ""


def _bar(current: int, total: int) -> None:
    """20-segment loading bar (same style as setup.py, collect.py, aoi_benchmark)."""
    loading_bar = ""
    filled = round(current / total * 20) if total else 0
    for _ in range(filled):
        loading_bar += "█"
    for _ in range(20 - filled):
        loading_bar += "_"
    try:
        print("\r" + loading_bar, end="", flush=True)
    except UnicodeEncodeError:
        print("\r" + loading_bar.replace("█", "#"), end="", flush=True)


def check_listing_feasibility(url: str, timeout_sec: float = FEASIBILITY_FETCH_TIMEOUT) -> str:
    """Fetch URL and check if page contains listing/claim signals. Returns 'yes', 'no', or 'error'."""
    if not url or not url.startswith(("http://", "https://")):
        return "error"
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; analysis2-feasibility-check/1.0)"})
        with urlopen(req, timeout=timeout_sec) as resp:
            raw = resp.read()
            try:
                text = raw.decode("utf-8", errors="replace")
            except Exception:
                text = raw.decode("latin-1", errors="replace")
    except (URLError, HTTPError, OSError, TimeoutError, Exception):
        return "error"
    text_lower = text.lower()
    # Form tag suggests a submission flow
    if "<form" in text_lower:
        return "yes"
    for phrase in FEASIBILITY_PHRASES:
        if phrase in text_lower:
            return "yes"
    return "no"


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    # ── Step 1.1 — Get raw argument ────────────────────────────────────────────
    argv = [a for a in sys.argv[1:] if a.strip()]
    if argv:
        arg = argv[0].strip()
    else:
        arg = input("Business folder path or slug: ").strip()
    if not arg:
        print("No slug or path provided.")
        sys.exit(1)

    # ── Step 1.2 — Resolve arg to (client_folder, slug) ──────────────────────
    from full_stack.collect import resolve_client_folder
    client_folder, slug = resolve_client_folder(arg)
    # (Step 1.3 — resolve_client_folder exits if folder missing)

    # ── Step 1.4 — Glob for candidate aiso CSVs ──────────────────────────────
    candidate_paths = list(client_folder.glob(f"{slug}_aisodata*.csv"))

    # ── Step 1.5.1 — Read header per candidate path ──────────────────────────
    path_to_header = {}
    for p in candidate_paths:
        with open(p, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            path_to_header[p] = list(reader.fieldnames or [])

    # ── Step 1.5.2 — Filter to paths with "Unassigned" in header ─────────────
    enriched_paths = [p for p in candidate_paths if "Unassigned" in path_to_header[p]]

    # ── Step 1.6.1 — Exit if no enriched paths ───────────────────────────────
    if not enriched_paths:
        print("No enriched aiso data found. Run analysis1 first.")
        sys.exit(1)

    # ── Step 1.6.2 — Pick path with max N ────────────────────────────────────
    best_path = None
    best_n = -1
    for p in enriched_paths:
        m = re.search(r"_aisodata(\d+)$", p.stem)
        if m:
            n = int(m.group(1))
            if n > best_n:
                best_n = n
                best_path = p
    if best_path is None:
        print("No enriched aiso data found. Run analysis1 first.")
        sys.exit(1)
    path_to_csv = best_path
    N = best_n

    # ── Step 1.7 — Read CSV into rows; capture header ─────────────────────────
    with open(path_to_csv, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        header_list = list(reader.fieldnames or [])
        rows = list(reader)

    # ── Step 2.1 — Identify business columns ─────────────────────────────────
    business_cols = [c for c in header_list if c not in ("question", "response", "error")]
    if not business_cols:
        print("No business columns found (expected focal, competitors, Unassigned).")
        sys.exit(1)

    # ── Step 2.2 — Set focal_col and other_business_cols ─────────────────────
    focal_col = business_cols[0]
    other_business_cols = business_cols[1:]

    # ── Step 3.1.1/3.1.2 — Helpers defined above (extract_links, extract_domain)

    # ── Step 3.2 — Iterate rows and business columns; parse links ────────────
    raw_records = []  # list of (domain, url, col)
    for row in rows:
        for col in business_cols:
            cell = (row.get(col) or "")
            for _text, url in extract_links(cell):
                domain = extract_domain(url)
                if domain:
                    raw_records.append((domain, url, col))

    # ── Step 3.3 — Build domain_to_info ──────────────────────────────────────
    domain_to_info: dict = {}
    for domain, url, col in raw_records:
        if domain not in domain_to_info:
            domain_to_info[domain] = {"urls_seen": [], "source_columns": set()}
        if url not in domain_to_info[domain]["urls_seen"]:
            domain_to_info[domain]["urls_seen"].append(url)
        domain_to_info[domain]["source_columns"].add(col)

    # ── Step 4.1 — Exclude focal-only domains ────────────────────────────────
    filtered_domains = [
        d for d, info in domain_to_info.items()
        if info["source_columns"] - {focal_col} != set()
    ]

    # ── Step 5.1 — Build initial addable set ─────────────────────────────────
    candidate_addable = {d for d in filtered_domains if is_addable(d)}

    # ── Step 5.2 — Remove not-addable domains ────────────────────────────────
    candidate_addable_filtered = {d for d in candidate_addable if not is_not_addable(d)}

    # ── Step 5.2.1.1 — Apply blocklist ───────────────────────────────────────
    blocklist_path = client_folder / "addable_blocklist.txt"
    blocklist_set: set = set()
    if blocklist_path.exists():
        for line in blocklist_path.read_text(encoding="utf-8").splitlines():
            line = line.strip().lower()
            if line and not line.startswith("#"):
                blocklist_set.add(line)
    after_blocklist = candidate_addable_filtered - blocklist_set

    # ── Step 5.2.1.2 — Apply allowlist ───────────────────────────────────────
    allowlist_path = client_folder / "addable_allowlist.txt"
    if allowlist_path.exists():
        allowlist_domains = set()
        for line in allowlist_path.read_text(encoding="utf-8").splitlines():
            line = line.strip().lower()
            if line and not line.startswith("#"):
                allowlist_domains.add(line)
        after_allowlist = after_blocklist | {d for d in allowlist_domains if d not in blocklist_set}
    else:
        after_allowlist = after_blocklist

    # ── Step 5.2.1.3.1 — Load datafile and get geography string ──────────────
    try:
        datafile = json.loads((client_folder / "datafile.json").read_text(encoding="utf-8"))
        geography = datafile.get("geography") or datafile.get("config", {}).get("geography")
        geography_str = (geography or "").lower()
    except (FileNotFoundError, json.JSONDecodeError):
        geography_str = ""

    # ── Step 5.2.1.3.2 — Exclude wrong-region domains ────────────────────────
    if geography_str:
        addable_domains = {
            d for d in after_allowlist
            if not any(
                (token in d.lower()) and (token not in geography_str)
                for token in STATE_TOKENS
            )
        }
    else:
        addable_domains = after_allowlist

    # ── Step 5.3 — Pick best URL per addable domain ───────────────────────────
    domain_to_best_url: dict = {}
    for domain in addable_domains:
        if domain not in domain_to_info:
            # allowlisted domain not seen in data — use base URL
            domain_to_best_url[domain] = "https://" + domain
        else:
            domain_to_best_url[domain] = pick_best_url(domain, domain_to_info[domain]["urls_seen"])

    # ── Step 5.4 — Register URL: only use cited link if it looks like real add page ─
    domain_to_register_url: dict = {}
    domain_to_register_from_citation: dict = {}
    for domain in addable_domains:
        direct = direct_url(domain)
        if domain not in domain_to_info:
            domain_to_register_url[domain] = direct
            domain_to_register_from_citation[domain] = False
        else:
            url, from_citation = pick_best_register_url(domain, domain_to_info[domain]["urls_seen"])
            domain_to_register_url[domain] = url if url else direct
            domain_to_register_from_citation[domain] = from_citation

    # ── Step 7.3.2 — Call run_agent_for_domain for every addable domain; fill domain_to_integrateable ─
    try:
        _biz_context = dict(datafile)
    except NameError:
        _biz_context = {}
    _biz_context["slug"] = slug
    domain_to_integrateable: dict = {}
    sorted_domains_agent = sorted(addable_domains)
    total_agent = len(sorted_domains_agent)
    print(f"Running AI agent on {total_agent} addable domain(s)...")
    for _ai, _domain in enumerate(sorted_domains_agent):
        _reg_url = domain_to_register_url[_domain]
        domain_to_integrateable[_domain] = run_agent_for_domain(_domain, _reg_url, slug, _biz_context)
        _bar(_ai + 1, total_agent)
    if total_agent:
        print()

    # ── Step 7.4 — Old feasibility logic removed (replaced by AI agent in 7.3.2) ─
    addable_for_output = addable_domains

    # ── Steps 7.5 / 8.1 — Build output rows (3 columns: register, direct, integrateable) ──
    output_rows = [
        {
            "register": domain_to_register_url[d],
            "direct": direct_url(d),
            "integrateable": domain_to_integrateable[d],
        }
        for d in sorted(addable_for_output)
    ]

    # ── Step 8.2 — Write CSV ──────────────────────────────────────────────────
    output_path = client_folder / f"{slug}_aisodata{N}_new_addable.csv"
    fieldnames = ["register", "direct", "integrateable"]
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(output_rows)
    print(f"Written: {output_path} ({len(output_rows)} addable sites).")


if __name__ == "__main__":
    main()
