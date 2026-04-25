"""
setup2.py  —  AISO Intelligent Question Pipeline (setup 1.3)

Two-section setup that replaces template×value cross-product with
AI-scored, AI-ranked query banks built from 7 structured group types.

────────────────────────────────────────────────────────────────────
SECTION 1  —  Immutable Client Profile  (run once, never overwrite)
  Phase 1.1  collect_core_profile()     →  client_profile.json
  Phase 1.2  generate_value_bank()      →  value_bank.csv   (17-token schema)
  Phase 1.3  generate_group_templates() →  groups/G*/templates.txt  (500 per group)

SECTION 2  —  Dynamic Profile & Ranking  (re-run anytime)
  Phase 2.1  collect_dynamic_brief()    →  client_brief.txt
  Phase 2.2  score_intent()             →  groups/G*/scored.jsonl  (intent 1-10)
  Phase 2.3  score_popularity()         →  groups/G*/scored.jsonl  (trends 0-100)
  Phase 2.4  rank_questions()           →  groups/G*/ranked.jsonl
  Phase 2.5  write_outputs()            →  query_template_bank.csv + ranking_report.json
────────────────────────────────────────────────────────────────────

Usage:
    python3 full_stack/setup2.py <slug>                    # full run
    python3 full_stack/setup2.py <slug> --resume           # skip phases whose output exists
    python3 full_stack/setup2.py <slug> --section 1        # section 1 only
    python3 full_stack/setup2.py <slug> --section 2        # section 2 only
    python3 full_stack/setup2.py <slug> --resume --section 2  # re-score/re-rank only
"""

import sys
import re
import json
import csv
import os
import time
import math
import argparse
import textwrap
from pathlib import Path
from typing import List, Dict, Optional, Tuple

# ── Path bootstrap ────────────────────────────────────────────────────────────
_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from dotenv import load_dotenv
load_dotenv(_repo_root / ".env")

OPENAI_API_KEY  = os.environ.get("OPENAI_API_KEY", "").strip()

# ── LLM Backend ───────────────────────────────────────────────────────────────
# "local" = Ollama (default, free, private)  |  "api" = OpenAI
# Override via CLI (--llm local|api) or .env (LLM_BACKEND=api)
LLM_BACKEND  = os.environ.get("LLM_BACKEND",  "local").strip().lower()
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3").strip()
OLLAMA_HOST  = os.environ.get("OLLAMA_HOST",  "http://localhost:11434").strip()

# ── Constants ─────────────────────────────────────────────────────────────────
TEMPLATES_PER_GROUP    = 150  # default — override with --templates-per-group
INTENT_BATCH_SIZE      = 25   # questions per GPT-4o-mini scoring call
TRENDS_SLEEP_SEC       = 2.0  # default — override with --trends-sleep
TRENDS_BATCH_SIZE      = 5    # keywords compared per Trends call (max 5)
TRENDS_TIMEWINDOW      = "today 12-m"
PRE_FILTER_SIZE        = 300  # default — override with --pre-filter
TOP_QUESTIONS_PER_GROUP = 75  # default — override with --top-questions

# ── 17-token value bank schema ────────────────────────────────────────────────
# Square-bracket placeholders used in all G1-G7 templates.
VALUE_BANK_TOKENS = [
    "client",
    "competitor", "competitor_a", "competitor_b",
    "option_a", "option_b",
    "category", "service", "product",
    "city", "neighborhood", "landmark", "region", "state_or_country", "zip_or_area",
    "goal", "use_case", "persona_or_occasion", "audience",
    "price_or_budget", "timeframe", "qualifier",
]

# ── Query Group Definitions (G1–G7) ──────────────────────────────────────────
# Each group defines: id, name, label, forbidden tokens, required tokens,
# and the exact LLM generation prompt (from setup1.3_plan.txt).

QUERY_GROUPS = [
    {
        "id": "G1",
        "name": "category_local_discovery",
        "label": "Category & local discovery (unbranded)",
        "forbidden": ["[client]", "[competitor]", "[competitor_a]", "[competitor_b]",
                      "[option_a]", "[option_b]"],
        "required": [],
        "prompt_body": textwrap.dedent("""\
            Generate ~{n} unique query templates (one per line) for G1.

            Intent & volume: Favor phrasing people actually search in high volume and that
            imply choosing a provider soon (ready to pick / visit / call / book), not idle
            trivia. Prefer commercial + local patterns (best/top/near me/open now/reviews
            implied/cheap vs luxury tradeoffs) where still unbranded.

            Variance: Mix many structures — questions, commands, "I need…", "looking for…",
            comparisons of approach, urgency, distance, time windows, constraints — and many
            ideas (open now, walk-in, same day, quality vs price, fastest, most trusted as a
            category, neighborhoods, landmarks, driving distance, "good enough",
            "worth it for tourists", etc.). Avoid repeating the same skeleton; vary length
            and angle.

            Placeholders: Use ONLY placeholders from the master list below. For G1 do NOT
            use [client], [competitor], [competitor_a], [competitor_b], [option_a],
            [option_b]. Use the rest of the list liberally and in many combinations across
            the lines.

            Output: Plain text, one template per line, no numbering, no blank lines.
        """),
    },
    {
        "id": "G2",
        "name": "direct_brand",
        "label": "Direct brand (client named)",
        "forbidden": ["[competitor]", "[competitor_a]", "[competitor_b]",
                      "[option_a]", "[option_b]"],
        "required": ["[client]"],
        "prompt_body": textwrap.dedent("""\
            Generate ~{n} unique query templates (one per line) for G2.

            Intent & volume: Prioritize high-intent branded patterns (pricing, hours, book,
            locations, services, policies, "do they offer…", insurance, cancellation, wait
            times, packages) that reflect real search volume and near-purchase decisions.

            Variance: Many structures (direct questions, implied task, troubleshooting,
            "is [client] good for…", first-timer vs repeat, mobile vs desktop-style
            phrasing). Many ideas (specific SKUs/services, edge cases, same-day,
            membership, gift cards, corporate, refunds).

            Placeholders: [client] is required in every line. Do NOT use competitor
            placeholders as the only brand (that's G3). Combine [client] with [city],
            [service], [product], [goal], [timeframe], [price_or_budget], [qualifier],
            [zip_or_area], etc., across the set.

            Output: Plain text, one template per line, no numbering, no blank lines.
        """),
    },
    {
        "id": "G3",
        "name": "competitors_alternatives",
        "label": "Competitors & alternatives (switching / competitive set)",
        "forbidden": [],
        "required": ["[competitor]"],   # at least one of the competitor tokens
        "prompt_body": textwrap.dedent("""\
            Generate ~{n} unique query templates (one per line) for G3.

            Intent & volume: Emphasize switching, evaluation before purchase, and
            comparison — phrasing that matches high-volume competitive search (alternatives,
            vs, cheaper than, better than, problems with X, leaving X).

            Variance: Many structures (vs, alternatives, "should I switch", "if I liked X
            will I like Y", multi-brand, "who beats…", complaints-led). Many ideas (price,
            quality, speed, location, niche use cases).

            Placeholders: Every line must include at least one of [competitor],
            [competitor_a], [competitor_b] (combine as needed). Do NOT use only [client]
            without a competitive frame. Mix in [city], [category], [service], [goal],
            [price_or_budget], [timeframe], [qualifier], [region], etc.

            Output: Plain text, one template per line, no numbering, no blank lines.
        """),
    },
    {
        "id": "G4",
        "name": "transactional_bottom_funnel",
        "label": "Transactional & bottom-funnel (money / book / buy / now)",
        "forbidden": [],
        "required": [],
        "prompt_body": textwrap.dedent("""\
            Generate ~{n} unique query templates (one per line) for G4.

            Intent & volume: Maximize purchase / booking / money signals — the kinds of
            queries that keyword tools show as high commercial intent and strong volume
            (cost, quote, book, appointment, deal, insurance accepted, deposit, same day,
            walk-in, package price).

            Variance: Many structures (how much, total cost, hidden fees, payment plans,
            book tonight, waitlist, cancellation cost, "under $X", compare quotes). Many
            ideas (urgency, insurance, tipping, add-ons, group booking, peak pricing).

            Placeholders: Lean on [price_or_budget], [timeframe], [city], [neighborhood],
            [service], [category], [product], [goal], [qualifier], [client], [competitor]
            where it still reads transaction-first (not review-first).

            Output: Plain text, one template per line, no numbering, no blank lines.
        """),
    },
    {
        "id": "G5",
        "name": "trust_reviews_risk",
        "label": "Trust, reviews & risk (pre-purchase anxiety)",
        "forbidden": [],
        "required": [],
        "prompt_body": textwrap.dedent("""\
            Generate ~{n} unique query templates (one per line) for G5.

            Intent & volume: Focus on pre-purchase trust queries that still have high
            search volume (reviews, BBB, lawsuits, reddit, "too good to be true", refund
            reputation). These should support a buy decision, not academic research.

            Variance: Many structures (is it legit, worth it, overrated, red flags,
            "anyone had issues", comparison to expectations). Many ideas (quality
            consistency, safety, hygiene, upsell fear, warranty, authenticity).

            Placeholders: Rotate [client], [competitor], [category], [service], [city],
            [neighborhood], [goal], [qualifier]. Do NOT make price quote or booking slot
            the main hook (that's G4).

            Output: Plain text, one template per line, no numbering, no blank lines.
        """),
    },
    {
        "id": "G6",
        "name": "fit_persona_occasion",
        "label": "Fit: persona, occasion, constraint",
        "forbidden": [],
        "required": ["[persona_or_occasion]"],
        "prompt_body": textwrap.dedent("""\
            Generate ~{n} unique query templates (one per line) for G6.

            Intent & volume: Bias toward high-intent fit queries (someone is close to
            picking but needs the right match): families, dates, accessibility, skill level,
            budget band, vibe, corporate, events, anxiety/special needs. Use phrasing that
            mirrors high-volume long-tail "best for X" patterns.

            Variance: Many structures ("for my mom", "kid-friendly", "if I'm picky",
            "if I'm on a budget", "anniversary", "team building"). Many persona/occasion
            dimensions; avoid repeating one template shape.

            STRICT RULE — EVERY single line MUST contain [persona_or_occasion] (or
            [audience] or [use_case]). Any line without one of these tokens will be
            discarded automatically. Do NOT write a single line without a persona or
            occasion placeholder.

            Placeholders: [persona_or_occasion] / [audience] / [use_case] REQUIRED on
            every line. Also mix [category], [service], [city], [neighborhood], [landmark],
            [goal], [qualifier], [price_or_budget], [timeframe] for variety.

            Output: Plain text, one template per line, no numbering, no blank lines.
        """),
    },
    {
        "id": "G7",
        "name": "head_to_head_choice",
        "label": "Head-to-head choice (shortlist / pick one)",
        "forbidden": [],
        "required": ["[option_a]"],
        "prompt_body": textwrap.dedent("""\
            Generate ~{n} unique query templates (one per line) for G7.

            Intent & volume: Force decision language that people use when ready to choose
            (which is better, pick one, final decision, "if you had to choose"). Favor
            patterns associated with strong commercial follow-through.

            Variance: Many structures (A vs B, ranked choice, "tie-breaker", "if budget
            matters", "if quality matters", triage questions). Many ideas (brand vs brand,
            approach vs approach, location tradeoffs, speed vs quality).

            STRICT RULE — EVERY single line MUST contain [option_a]. Any line without
            [option_a] will be discarded automatically. Most lines should also include
            [option_b] or [competitor_b] to form a proper A vs B structure.

            Placeholders: [option_a] REQUIRED on every line. Pair with [option_b] and/or
            [competitor_a] / [competitor_b] for forced-choice framing. Add [goal], [city],
            [category], [service], [price_or_budget], [qualifier], [timeframe] for variety.
            No broad "list all alternatives" without a tight pick-one structure.

            Output: Plain text, one template per line, no numbering, no blank lines.
        """),
    },
]

# ── Helpers ───────────────────────────────────────────────────────────────────

def normalize_slug(raw: str) -> str:
    slug = raw.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    return slug.strip("_")


def _strip_fences(text: str) -> str:
    lines = text.strip().splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines)


def _bar(current: int, total: int, label: str = "") -> None:
    filled = round(current / total * 30) if total else 0
    bar = "█" * filled + "░" * (30 - filled)
    suffix = f" {label}" if label else ""
    try:
        print(f"\r[{bar}] {current}/{total}{suffix}", end="", flush=True)
    except UnicodeEncodeError:
        bar = "#" * filled + "-" * (30 - filled)
        print(f"\r[{bar}] {current}/{total}{suffix}", end="", flush=True)


def _openai_client():
    from openai import OpenAI
    return OpenAI(api_key=OPENAI_API_KEY)


# ── LLM backends ─────────────────────────────────────────────────────────────

def _llm_openai(
    prompt: str,
    *,
    model: str = "gpt-4o-mini",
    temperature: float = 0.2,
    json_mode: bool = False,
    max_tokens: Optional[int] = None,
    system: Optional[str] = None,
) -> str:
    """Call OpenAI API (gpt-4o / gpt-4o-mini). Retries with exponential backoff."""
    client = _openai_client()
    messages: List[Dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    kwargs: Dict = {
        "model":       model,
        "messages":    messages,
        "temperature": temperature,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    if max_tokens:
        kwargs["max_tokens"] = max_tokens

    for attempt in range(3):
        try:
            resp = client.chat.completions.create(**kwargs)
            return resp.choices[0].message.content
        except Exception as exc:
            if attempt < 2:
                wait = 2 ** attempt
                print(f"\n  [openai] attempt {attempt + 1} failed ({exc.__class__.__name__}), retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise
    raise RuntimeError("_llm_openai: exhausted retries")


def _llm_local(
    prompt: str,
    *,
    temperature: float = 0.2,
    json_mode: bool = False,
    system: Optional[str] = None,
) -> str:
    """
    Call a local Ollama model (e.g. llama3).
    Requires Ollama running: ollama serve
    Install: https://ollama.com  +  ollama pull llama3

    json_mode: OpenAI's API-level JSON enforcement is unavailable in Ollama;
    we inject a strong JSON-only instruction into the prompt instead.
    The existing _strip_fences() + json.loads() chain handles the output.
    """
    try:
        import ollama as _ollama
    except ImportError as exc:
        raise RuntimeError(
            "ollama package not installed.\n"
            "  Fix: python3 -m pip install --break-system-packages ollama\n"
            "  Or switch to API mode: --llm api"
        ) from exc

    messages: List[Dict] = []
    if system:
        messages.append({"role": "system", "content": system})

    user_content = prompt
    if json_mode:
        user_content = (
            prompt
            + "\n\nCRITICAL: respond with ONLY valid JSON. "
            "No explanation, no markdown fences, no text outside the JSON."
        )
    messages.append({"role": "user", "content": user_content})

    client = _ollama.Client(host=OLLAMA_HOST)

    for attempt in range(3):
        try:
            resp = client.chat(
                model=OLLAMA_MODEL,
                messages=messages,
                options={"temperature": temperature},
            )
            return resp.message.content
        except Exception as exc:
            err = str(exc).lower()
            if any(k in err for k in ("connection", "refused", "connect", "not found", "unreachable")):
                raise RuntimeError(
                    f"Ollama not reachable at {OLLAMA_HOST}.\n"
                    "  → Start Ollama:       ollama serve\n"
                    f"  → Pull the model:     ollama pull {OLLAMA_MODEL}\n"
                    "  → Or use API instead: --llm api"
                ) from exc
            if attempt < 2:
                wait = 2 ** attempt
                print(f"\n  [local] attempt {attempt + 1} failed ({exc.__class__.__name__}), retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise
    raise RuntimeError("_llm_local: exhausted retries")


def llm_call(
    prompt: str,
    *,
    model: str = "gpt-4o-mini",
    temperature: float = 0.2,
    json_mode: bool = False,
    max_tokens: Optional[int] = None,
    system: Optional[str] = None,
) -> str:
    """
    Single entry point for ALL LLM calls in this pipeline.
    Routes to local Ollama or OpenAI API based on LLM_BACKEND global.

    Switch via CLI :  --llm local   (default)  |  --llm api
    Switch via env :  LLM_BACKEND=local        |  LLM_BACKEND=api

    Args:
      prompt      : the user-facing prompt
      model       : OpenAI model name (ignored in local mode)
      temperature : 0.0 = deterministic, 1.0 = creative
      json_mode   : JSON-only output (API-enforced for OpenAI; prompt-injected for local)
      max_tokens  : optional output token cap (OpenAI only)
      system      : optional system message
    """
    if LLM_BACKEND == "local":
        return _llm_local(
            prompt,
            temperature=temperature,
            json_mode=json_mode,
            system=system,
        )
    return _llm_openai(
        prompt,
        model=model,
        temperature=temperature,
        json_mode=json_mode,
        max_tokens=max_tokens,
        system=system,
    )


# ── CSV companion writer ─────────────────────────────────────────────────────────

def _write_csv_from_jsonl(jsonl_path: Path) -> None:
    """
    Write a companion .csv next to any .jsonl file for easy human inspection.
    Open in Excel or Google Sheets. Safe to call after every JSONL write.
    """
    rows = []
    for line in jsonl_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    if not rows:
        return
    # Collect all keys in order of first appearance (union across all rows)
    keys: List[str] = []
    seen_keys: set = set()
    for row in rows:
        for k in row.keys():
            if k not in seen_keys:
                keys.append(k)
                seen_keys.add(k)
    csv_path = jsonl_path.with_suffix(".csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _resolve_client_folder(slug: str) -> Path:
    clients_dir = _repo_root / "clients" / slug
    if clients_dir.exists():
        return clients_dir
    return _repo_root / slug  # legacy fallback


# ── Phase 1.1: Immutable Core Profile ────────────────────────────────────────

def collect_core_profile(slug: str, client_folder: Path) -> dict:
    """
    Interactive questions to build the immutable client profile.
    Saved to client_profile.json. Will NOT overwrite if it exists.
    """
    profile_path = client_folder / "client_profile.json"
    if profile_path.exists():
        print("  client_profile.json already exists — loading (immutable).")
        with open(profile_path, encoding="utf-8") as f:
            return json.load(f)

    print("\n┌─ Section 1: Immutable Client Profile ─────────────────────────────┐")
    print("│  These answers are saved permanently and will not be asked again.  │")
    print("└───────────────────────────────────────────────────────────────────┘\n")

    def ask(prompt: str, required: bool = True) -> str:
        while True:
            val = input(prompt).strip()
            if val or not required:
                return val
            print("  (required — please enter a value)")

    industry       = ask("Industry / category (e.g. adventure tours, restaurants): ")
    products       = ask("Products or services offered (comma-separated): ")
    geography      = ask("Primary geography (city, region, or 'nationwide'): ")
    display_name   = ask("Business display name (e.g. 'Santa Barbara Adventure Co'): ")
    competitors_raw = ask("Main competitors (comma-separated, at least 1-3 names): ")
    target_customer = ask("Target customer (e.g. 'families and couples visiting SB'): ")
    unique_value   = ask("Unique value proposition (1-2 sentences): ")

    # Operating model
    raw_model = ask("Operating model — physical location, online-only, or both? [physical/online/both]: ")
    lower = raw_model.lower()
    if any(k in lower for k in ("online", "digital", "anywhere", "internet")):
        op_model = "online"
    elif any(k in lower for k in ("physical", "brick", "storefront", "in-person")):
        op_model = "physical"
    else:
        op_model = "both"

    if op_model == "online":
        op_region = ask("Service region (e.g. 'US nationwide', or 'online only'): ", required=False) or "online only"
    else:
        op_region = ask("Service region (city, state, or country — e.g. 'Santa Barbara, CA'): ")

    competitors = [c.strip() for c in competitors_raw.split(",") if c.strip()]

    profile = {
        "slug":             slug,
        "display_name":     display_name,
        "industry":         industry,
        "products_services": products,
        "geography":        geography,
        "operating_model":  op_model,
        "operating_region": op_region,
        "competitors":      competitors,
        "target_customer":  target_customer,
        "unique_value":     unique_value,
        "_immutable":       True,
        "_note":            "Do NOT edit this file. Re-run setup2.py to regenerate.",
    }

    with open(profile_path, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2, ensure_ascii=False)
    print("\n  ✓ client_profile.json written.")
    return profile


# ── Phase 1.2: Value Bank (17-token schema) ───────────────────────────────────

def generate_value_bank(profile: dict, client_folder: Path, resume: bool) -> List[Dict]:
    """
    AI generates 10-15 value rows covering all 17 placeholder token types
    specific to this client. Saved to value_bank.csv.
    """
    vbank_path = client_folder / "value_bank.csv"
    if resume and vbank_path.exists():
        print("  [resume] value_bank.csv exists — skipping generation.")
        rows = []
        with open(vbank_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(dict(row))
        return rows

    print("\n  Generating value bank (17-token schema)...")

    competitors_str = ", ".join(profile.get("competitors", ["[competitor name]"]))
    token_list = "\n".join(f"  - {t}" for t in VALUE_BANK_TOKENS)

    prompt = f"""You are building a value bank for an AI search optimization system.

Client profile:
{json.dumps({k: v for k, v in profile.items() if not k.startswith("_")}, indent=2)}

Generate 12 value rows as a JSON array of objects.
Each object must have EXACTLY these keys (one per row, no extras):
{token_list}

Rules:
- client: always "{profile.get('display_name', profile['slug'])}"
- competitor / competitor_a / competitor_b: rotate through these real competitors: {competitors_str}
- option_a / option_b: two options in a head-to-head frame (can be services, approaches, or brands)
- city / neighborhood / landmark / region: real places for {profile.get('geography', 'the area')}
- state_or_country / zip_or_area: relevant to the geography
- service / product / category: specific to {profile.get('products_services', 'their offerings')}
- goal / use_case / persona_or_occasion / audience: realistic for {profile.get('target_customer', 'their customers')}
- price_or_budget: realistic price bands for this industry
- timeframe: realistic booking/visit windows (today, this weekend, etc.)
- qualifier: realistic quality/trait descriptors (award-winning, family-friendly, etc.)

Make each row a distinct "scenario" with different values — vary geography, persona, service, etc.
Return ONLY valid JSON — no explanation, no markdown fences.
"""

    raw = _strip_fences(llm_call(prompt, model="gpt-4o", temperature=0.5))
    rows = json.loads(raw)
    if not isinstance(rows, list) or not rows:
        raise ValueError("Value bank generation returned unexpected format.")

    # Normalize: ensure all token columns exist in every row
    clean_rows = []
    for row in rows:
        clean_row = {tok: str(row.get(tok, "")).strip() for tok in VALUE_BANK_TOKENS}
        clean_rows.append(clean_row)

    with open(vbank_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=VALUE_BANK_TOKENS)
        writer.writeheader()
        writer.writerows(clean_rows)

    print(f"  ✓ value_bank.csv written ({len(clean_rows)} rows).")
    return clean_rows


# ── Phase 1.3: Group Template Banks ──────────────────────────────────────────

def _build_master_token_list() -> str:
    return "  " + "\n  ".join(f"[{t}]" for t in VALUE_BANK_TOKENS)


def generate_group_templates(profile: dict, client_folder: Path, resume: bool) -> Dict[str, List[str]]:
    """
    For each of G1-G7, generate ~500 query templates using the exact LLM
    prompts from the spec. Templates use [square-bracket] placeholders.
    Saves to groups/<id>_<name>/templates.txt (one template per line).
    Returns dict: group_id -> list of template strings.
    """
    groups_dir = client_folder / "groups"
    groups_dir.mkdir(exist_ok=True)

    client_context = json.dumps(
        {k: v for k, v in profile.items() if not k.startswith("_")},
        indent=2
    )
    master_tokens = _build_master_token_list()

    all_templates: Dict[str, List[str]] = {}

    for i, group in enumerate(QUERY_GROUPS):
        gid   = group["id"]
        gname = group["name"]
        glabel = group["label"]
        group_dir = groups_dir / f"{gid}_{gname}"
        group_dir.mkdir(exist_ok=True)
        tpath = group_dir / "templates.txt"

        if resume and tpath.exists():
            templates = [ln.strip() for ln in tpath.read_text(encoding="utf-8").splitlines() if ln.strip()]
            print(f"  [resume] {gid}: {len(templates)} templates loaded.")
            all_templates[gid] = templates
            continue

        print(f"\n  Generating {TEMPLATES_PER_GROUP} templates for {gid} — {glabel}...")

        # Build system + user prompt
        system_msg = (
            f"You are building query template banks for AISO (AI Search Optimization) benchmarking.\n"
            f"Group: {glabel}\n\n"
            f"Client:\n{client_context}\n\n"
            f"Master placeholder list (ONLY use these tokens, spelled exactly as shown):\n"
            f"{master_tokens}"
        )
        user_msg = group["prompt_body"].format(n=TEMPLATES_PER_GROUP)

        # Generate in 2 batches of 250 to improve quality and reliability
        templates: List[str] = []
        for batch_num in range(2):
            batch_prompt = user_msg + f"\n\n(Batch {batch_num + 1} of 2 — generate a fresh set, no repeats from batch 1.)"
            batch_text = llm_call(
                batch_prompt,
                model="gpt-4o",
                temperature=0.8,
                max_tokens=4096,
                system=system_msg,
            ).strip()
            batch_lines = [ln.strip() for ln in batch_text.splitlines() if ln.strip()]
            # Remove numbering if model added it despite instructions
            batch_lines = [re.sub(r"^\d+[\.\)]\s*", "", ln) for ln in batch_lines]
            templates.extend(batch_lines)

        # Deduplicate (case-insensitive)
        seen: set = set()
        unique: List[str] = []
        for t in templates:
            key = t.lower()
            if key not in seen:
                seen.add(key)
                unique.append(t)

        # Validate: warn if forbidden tokens used
        forbidden = group.get("forbidden", [])
        violations = [t for t in unique if any(fb in t for fb in forbidden)]
        if violations:
            print(f"  ⚠ {len(violations)} templates in {gid} use forbidden tokens — removing.")
            unique = [t for t in unique if not any(fb in t for fb in forbidden)]

        # Warn if required tokens missing
        required = group.get("required", [])
        if required:
            missing_req = [t for t in unique if not any(rq in t for rq in required)]
            if missing_req:
                print(f"  ⚠ {len(missing_req)} templates in {gid} missing required token — removing.")
                unique = [t for t in unique if any(rq in t for rq in required)]

        # Trim to target count
        unique = unique[:TEMPLATES_PER_GROUP]

        tpath.write_text("\n".join(unique), encoding="utf-8")
        all_templates[gid] = unique
        _bar(i + 1, len(QUERY_GROUPS), label=f"{gid} done ({len(unique)} templates)")

    print()
    return all_templates


# ── Phase 2.1: Dynamic Client Brief ──────────────────────────────────────────

def collect_dynamic_brief(client_folder: Path, resume: bool) -> Tuple[str, Path]:
    """
    Free-text dynamic client brief — filled in by the operator.
    Each run saves a NEW timestamped file: client_brief_YYYYMMDD_HHMMSS.txt
    Old briefs are never overwritten — you always have the full history.
    --resume: loads the most recent existing brief without prompting.
    Returns (brief_text, brief_path).
    """
    from datetime import datetime

    # Glob all existing briefs — ISO timestamp name means alphabetical == chronological
    existing_briefs = sorted(
        client_folder.glob("client_brief_*.txt"),
        key=lambda p: p.name,
        reverse=True,  # newest first
    )

    if resume and existing_briefs:
        latest = existing_briefs[0]
        print(f"  [resume] Loading latest brief: {latest.name}")
        return latest.read_text(encoding="utf-8"), latest

    print("\n┌─ Section 2: Dynamic Client Brief ─────────────────────────────────┐")
    print("│  Enter current goals, targeting, focus areas, competitive context. │")
    print("│  Each run creates a new timestamped file — old briefs are kept.    │")
    if existing_briefs:
        print(f"│  Previous brief: {existing_briefs[0].name:<51}│")
    print("│  Press ENTER twice when done.                                      │")
    print("└───────────────────────────────────────────────────────────────────┘\n")

    lines = []
    blank_count = 0
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line == "":
            blank_count += 1
            if blank_count >= 2:
                break
            lines.append("")
        else:
            blank_count = 0
            lines.append(line)

    brief = "\n".join(lines).strip()
    if not brief:
        brief = "(No client brief provided — ranking will rely on profile and scores only.)"

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    brief_path = client_folder / f"client_brief_{timestamp}.txt"
    brief_path.write_text(brief, encoding="utf-8")
    print(f"\n  ✓ Brief saved: {brief_path.name}")
    return brief, brief_path


# ── Phase 2.2a: Expand Templates → Actual Questions ─────────────────────────

def expand_templates_to_questions(
    all_templates: Dict[str, List[str]],
    value_rows: List[Dict],
) -> Dict[str, List[str]]:
    """
    Expand each template × each value_bank row → a fully-resolved question string.
    Filters out combinations that still contain unfilled [placeholders].
    Deduplicates within each group while preserving order.
    Returns dict: group_id -> list of expanded question strings.
    """
    TOKEN_RE = re.compile(r"\[[a-z_]+\]")
    all_questions: Dict[str, List[str]] = {}

    for gid, templates in all_templates.items():
        raw_questions: List[str] = []
        for tmpl in templates:
            for vrow in value_rows:
                q = tmpl
                for token, val in vrow.items():
                    if val:
                        q = q.replace(f"[{token}]", val)
                if not TOKEN_RE.search(q):   # only keep fully-resolved questions
                    raw_questions.append(q)
        # Deduplicate, preserve order
        seen: set = set()
        unique: List[str] = []
        for q in raw_questions:
            if q not in seen:
                seen.add(q)
                unique.append(q)
        
        # OPTIMIZATION: Cap at 150 questions per group to speed up intent scoring
        import random
        random.seed(42) # Deterministic for resumability
        if len(unique) > 150:
            unique = random.sample(unique, 150)
            
        all_questions[gid] = unique

    return all_questions


# ── Phase 2.2b helper: Geo code for regional Trends ──────────────────────────

def _extract_geo_code(geography: str) -> str:
    """
    Map a client geography string to a pytrends geo code.
    E.g. "Santa Barbara, CA" -> "US-CA", "nationwide" -> "US".
    """
    US_STATES = {
        "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
        "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
        "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
        "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
        "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
        "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
        "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
        "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
        "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
        "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
        "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
        "vermont": "VT", "virginia": "VA", "washington": "WA", "west virginia": "WV",
        "wisconsin": "WI", "wyoming": "WY",
    }
    geo_lower = geography.lower().strip()
    if any(k in geo_lower for k in ("nationwide", "online", "national", "worldwide", "global")):
        return "US"
    # Two-letter abbreviation at end: ", CA" or " CA"
    m = re.search(r",?\s+([A-Z]{2})\s*$", geography)
    if m and m.group(1).upper() in US_STATES.values():
        return f"US-{m.group(1).upper()}"
    # Full state name anywhere in string
    for name, abbr in US_STATES.items():
        if name in geo_lower:
            return f"US-{abbr}"
    return "US"


# ── Phase 2.2: Intent to Buy Scoring ─────────────────────────────────────────

def score_intent(
    all_questions: Dict[str, List[str]],
    client_folder: Path,
    profile: dict,
    resume: bool,
) -> Dict[str, List[Dict]]:
    """
    Score each EXPANDED QUESTION for purchase intent (1-10) using GPT-4o-mini.
    Batched at INTENT_BATCH_SIZE per API call.
    Saves/updates groups/<G*>/scored.jsonl  (key: "question", not "template").
    Returns dict: group_id -> list of {question, intent_score, intent_reason}.
    """
    context_snippet = (
        f"Industry: {profile.get('industry', 'N/A')}, "
        f"Services: {profile.get('products_services', 'N/A')}, "
        f"Geography: {profile.get('geography', 'N/A')}"
    )
    all_scored: Dict[str, List[Dict]] = {}

    for group in QUERY_GROUPS:
        gid = group["id"]
        questions = all_questions.get(gid, [])
        if not questions:
            all_scored[gid] = []
            continue

        group_dir = client_folder / "groups" / f"{gid}_{group['name']}"
        scored_path = group_dir / "scored.jsonl"

        # Load existing scored entries for resume (keyed by question text)
        existing: Dict[str, Dict] = {}
        if resume and scored_path.exists():
            for line in scored_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    entry = json.loads(line)
                    key = entry.get("question", entry.get("template", ""))
                    if key:
                        existing[key] = entry

        to_score = [q for q in questions if q not in existing or "intent_score" not in existing[q]]

        if not to_score:
            print(f"  [resume] {gid}: intent scores complete ({len(questions):,} questions).")
            all_scored[gid] = [existing.get(q, {"question": q}) for q in questions]
            continue

        print(f"\n  Scoring intent for {gid} ({len(to_score):,} questions)...")

        for batch_start in range(0, len(to_score), INTENT_BATCH_SIZE):
            batch = to_score[batch_start: batch_start + INTENT_BATCH_SIZE]
            batch_json = json.dumps(batch)

            prompt = f"""You are scoring search questions for purchase intent for an AISO system.

Client context: {context_snippet}

Score each question on a scale of 1-10 for PURCHASE INTENT:
  10 = Strongly implies the user is about to buy/book/hire/pay
   8 = High intent — clearly ready to pick a provider or make a decision
   5 = Mid-funnel — evaluating, researching with near-purchase signals
   3 = Low intent — general curiosity or awareness
   1 = No purchase intent — purely informational

Questions to score:
{batch_json}

Return a JSON array of objects, one per question, in the SAME ORDER. Each object:
  {{ "question": "<exact question text>", "intent_score": <1-10>, "intent_reason": "<1 sentence>" }}

Return ONLY valid JSON, no explanation, no markdown fences."""

            raw = llm_call(prompt, model="gpt-4o-mini", temperature=0.2, json_mode=True)
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                items = parsed.get("results", parsed.get("questions", list(parsed.values())[0]))
            else:
                items = parsed

            for item in items:
                q_text = item.get("question", "")
                entry = existing.get(q_text, {"question": q_text})
                entry["intent_score"]  = item.get("intent_score", 5)
                entry["intent_reason"] = item.get("intent_reason", "")
                existing[q_text] = entry

            _bar(batch_start + len(batch), len(to_score), f"{gid} intent")

        # Write JSONL + companion CSV
        with open(scored_path, "w", encoding="utf-8") as f:
            for q in questions:
                entry = existing.get(q, {"question": q, "intent_score": 5, "intent_reason": ""})
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        _write_csv_from_jsonl(scored_path)

        all_scored[gid] = [existing.get(q, {"question": q}) for q in questions]

    print()
    return all_scored


# ── Phase 2.3: Popularity Scoring (Google Trends — regional, batched) ─────────

def _extract_keywords(text: str, profile: Optional[dict] = None) -> List[str]:
    """
    Extract a 2-3 word search keyword phrase from an expanded question for Trends.

    Improvements over v1:
      - 3x larger stop list: question words, auxiliaries, fillers all stripped
      - Profile vocabulary anchoring: known service/location terms float to the front,
        so the phrase captures what matters for THIS client (not generic words)
      - 3-word max (down from 4): Google Trends accuracy peaks at 1-3 words;
        4-word queries return too-narrow results and more empty DataFrames

    Examples (for a kayak tour operator in Santa Barbara):
      'how do i book a kayak tour near stearns wharf'  -> 'kayak tour stearns'
      'which is safer for kids in santa barbara'        -> 'santa barbara kids'  (loc-anchored)
      'best whale watching tours available this weekend' -> 'whale watching tours'
    """
    clean = re.sub(r"[^\w\s]", " ", text.lower())
    words = clean.split()

    STOP = {
        # Articles, prepositions, conjunctions
        "the", "a", "an", "in", "of", "to", "and", "or", "for", "at", "by",
        "on", "up", "as", "if", "so", "its", "it",
        # Pronouns
        "i", "me", "my", "we", "our", "you", "your", "they", "their", "them",
        "this", "that", "these", "those", "there", "here", "some", "any",
        # Question words
        "what", "where", "how", "who", "when", "which", "why",
        # Auxiliary verbs
        "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did",
        "will", "would", "could", "should", "can", "may", "might", "must", "shall",
        # Common filler verbs
        "get", "got", "make", "made", "use", "used", "let", "take", "go", "going",
        "find", "look", "looking", "want", "help", "try", "trying",
        "know", "see", "come", "need",
        # Filler adjectives / adverbs
        "best", "good", "great", "top", "near", "like", "also", "just",
        "very", "really", "too", "more", "most", "many", "much", "other",
        "right", "new", "old", "big", "same", "different", "near", "with",
    }

    filtered = [w for w in words if w not in STOP and len(w) > 2]
    if not filtered:
        return []

    # Anchor on client vocabulary: lift known service/location words to the front
    if profile:
        vocab_raw = " ".join([
            str(profile.get("products_services", "")),
            str(profile.get("industry", "")),
            str(profile.get("geography", "")),
            str(profile.get("display_name", "")),
        ])
        vocab_words = set(re.sub(r"[^\w\s]", " ", vocab_raw.lower()).split())
        known   = [w for w in filtered if w in vocab_words]
        unknown = [w for w in filtered if w not in vocab_words]
        ordered = known + unknown
    else:
        ordered = filtered

    # 2-3 words is the Trends sweet spot
    phrase = " ".join(ordered[:3]).strip()
    return [phrase] if phrase else []


def _trends_fetch_batch(
    pytrends, keywords: List[str], timeframe: str, geo: str, max_retries: int = 3
) -> Dict[str, Optional[float]]:
    """
    Fetch Trends interest for a keyword batch (up to 5).
    Returns {keyword: score_0_to_100} or {keyword: None} when data is unavailable.
    None = genuinely unknown, NOT zero. Callers must handle None explicitly.
    Uses exponential back-off on rate-limit / connection errors.
    Hard 30-second timeout per attempt via concurrent.futures to prevent hanging.
    """
    import concurrent.futures

    def _do_fetch() -> Dict[str, Optional[float]]:
        pytrends.build_payload(keywords, timeframe=timeframe, geo=geo)
        df = pytrends.interest_over_time()
        result: Dict[str, Optional[float]] = {}
        for kw in keywords:
            if not df.empty and kw in df.columns:
                series = df[kw].dropna()
                result[kw] = float(series.mean()) if len(series) else None
            else:
                result[kw] = None
        return result

    for attempt in range(max_retries):
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_do_fetch)
                try:
                    return future.result(timeout=30)  # 30-second hard timeout
                except concurrent.futures.TimeoutError:
                    print(f"\n  ⚠ Trends timeout on attempt {attempt + 1} — skipping batch (will mark as None)")
                    if attempt < max_retries - 1:
                        time.sleep(TRENDS_SLEEP_SEC * (3 ** attempt))
                    else:
                        return {kw: None for kw in keywords}
        except Exception:
            if attempt < max_retries - 1:
                time.sleep(TRENDS_SLEEP_SEC * (3 ** attempt))  # 2.0s, 6.0s, 18.0s
            else:
                return {kw: None for kw in keywords}  # unknown — not zero
    return {kw: None for kw in keywords}


def score_popularity(
    all_scored: Dict[str, List[Dict]],
    client_folder: Path,
    profile: dict,
    resume: bool,
) -> Dict[str, List[Dict]]:
    """
    Add popularity_score (0-100 or None) to each question via Google Trends.
    None = data genuinely unavailable (not zero, not a fake filler).
    Fixes vs old version:
      - Returns None when keyword empty, Trends missing, or geo has no data
      - Per-batch retry with exponential back-off via _trends_fetch_batch()
      - Sentinel -1.0 cleanup — no score ever escapes as negative
      - Resume check uses key-presence (not value check) so None entries are not re-fetched
      - Writes scored.csv alongside scored.jsonl for easy inspection
    """
    try:
        from pytrends.request import TrendReq
        pytrends = TrendReq(hl="en-US", tz=360)
        trends_available = True
    except ImportError:
        print("  pytrends not installed — popularity_score will be None (unknown) for all questions.")
        print("  Install it: python3 -m pip install pytrends")
        trends_available = False

    geo_code = _extract_geo_code(profile.get("geography", "US"))
    print(f"  Google Trends geo: {geo_code}  (from: '{profile.get('geography', 'US')}')")

    for group in QUERY_GROUPS:
        gid = group["id"]
        entries = all_scored.get(gid, [])
        if not entries:
            continue

        group_dir = client_folder / "groups" / f"{gid}_{group['name']}"
        scored_path = group_dir / "scored.jsonl"

        # Key presence (not value) determines if scoring was done:
        # None is a valid result (no Trends data), missing key means not processed
        already_done = all("popularity_score" in e for e in entries)
        if resume and already_done:
            print(f"  [resume] {gid}: popularity scores complete.")
            continue

        print(f"\n  Popularity scoring {gid} ({len(entries):,} questions)...")

        # Map each question to a keyword phrase; build unique-keyword scoring dict
        keyword_to_score: Dict[str, Optional[float]] = {}
        question_to_kw: Dict[str, str] = {}

        for entry in entries:
            q = entry.get("question", "")
            kws = _extract_keywords(q, profile=profile)
            kw = kws[0] if kws else ""
            question_to_kw[q] = kw
            if kw and kw not in keyword_to_score:
                keyword_to_score[kw] = -1.0  # sentinel

        unique_kws = [kw for kw, s in keyword_to_score.items() if isinstance(s, float) and s < 0]
        print(f"    {len(unique_kws)} unique keyword phrases (batches of {TRENDS_BATCH_SIZE})...")

        if trends_available and unique_kws:
            total_batches = math.ceil(len(unique_kws) / TRENDS_BATCH_SIZE)
            for b_idx, batch_start in enumerate(range(0, len(unique_kws), TRENDS_BATCH_SIZE)):
                batch_kws   = unique_kws[batch_start: batch_start + TRENDS_BATCH_SIZE]
                batch_trunc = [kw[:100] for kw in batch_kws]
                scores = _trends_fetch_batch(pytrends, batch_trunc, TRENDS_TIMEWINDOW, geo_code)
                for kw, kw_t in zip(batch_kws, batch_trunc):
                    keyword_to_score[kw] = scores.get(kw_t)  # None or float — never fake
                time.sleep(TRENDS_SLEEP_SEC)
                _bar(b_idx + 1, total_batches, f"{gid} trends")
        else:
            # pytrends unavailable — mark all as unknown
            for kw in unique_kws:
                keyword_to_score[kw] = None

        # Safety net: any sentinel -1.0 that escaped → unknown
        for kw in unique_kws:
            raw = keyword_to_score.get(kw, None)
            if isinstance(raw, float) and raw < 0:
                keyword_to_score[kw] = None

        # Map scores back (None = unknown, not zero — preserved honestly)
        for entry in entries:
            q  = entry.get("question", "")
            kw = question_to_kw.get(q, "")
            pop = keyword_to_score.get(kw) if kw else None  # None when kw empty
            entry["popularity_score"] = round(pop, 1) if pop is not None else None

        # Rewrite JSONL + companion CSV
        with open(scored_path, "w", encoding="utf-8") as f:
            for entry in entries:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        _write_csv_from_jsonl(scored_path)

    print()
    return all_scored


# ── Phase 2.3b: CPC Proxy Scoring (free, rule-based) ─────────────────────────

# Commercial value by group type (based on paid search industry patterns)
_GROUP_CPC_BASE: Dict[str, float] = {
    "G4": 9.0,  # Transactional / bottom-funnel — highest advertiser intent
    "G2": 8.0,  # Direct brand — high brand-protection bids
    "G3": 7.0,  # Competitors & alternatives — comparison shoppers, high CPCs
    "G1": 6.0,  # Category & local discovery — moderate commercial value
    "G7": 5.5,  # Head-to-head choice — decision-stage comparison
    "G6": 5.0,  # Persona / occasion fit — niche targeting
    "G5": 4.5,  # Trust, reviews & risk — informational, lowest CPC
}

# Commercial keyword set — presence in a question signals high advertiser competition
_COMMERCIAL_TERMS = frozenset([
    "book", "booking", "reserve", "reservation", "buy", "purchase", "order",
    "hire", "rent", "rental", "price", "pricing", "cost", "quote", "estimate",
    "deal", "discount", "coupon", "offer", "package", "voucher", "promo",
    "near me", "nearby", "open now", "available today", "available now",
    "affordable", "cheap", "best value", "top rated", "highest rated",
    "compare", "vs", "versus", "alternative", "instead of",
])


def score_cpc_proxy(
    all_scored: Dict[str, List[Dict]],
    client_folder: Path,
) -> Dict[str, List[Dict]]:
    """
    Add cpc_proxy_score (1.0 – 10.0) to every question entry using two free signals:

      1. Group-type base score: derived from known paid-search commercial value.
         G4 (transactional) = 9.0  ...  G5 (trust/reviews) = 4.5

      2. Commercial keyword bonus: +0.5 per matched term, capped at +2.0.
         Terms like 'book', 'price', 'rent', 'near me', 'compare vs' are
         associated with high advertiser competition in real keyword auctions.

    This is labeled as a PROXY — not real CPC data from a paid API.
    It genuinely correlates with CPC because:
      - Group types map directly to purchase funnel stages advertisers target.
      - Commercial terms are exactly what triggers high-bid ad campaigns.
    No external API. No cost. Runs instantly.
    """
    for group in QUERY_GROUPS:
        gid   = group["id"]
        base  = _GROUP_CPC_BASE.get(gid, 5.0)
        entries = all_scored.get(gid, [])
        group_dir = client_folder / "groups" / f"{gid}_{group['name']}"
        scored_path = group_dir / "scored.jsonl"

        for entry in entries:
            q_lower = entry.get("question", "").lower()
            bonus = sum(0.5 for term in _COMMERCIAL_TERMS if term in q_lower)
            bonus = min(2.0, bonus)
            entry["cpc_proxy_score"] = round(min(10.0, base + bonus), 1)

        # Persist all three scores (intent + popularity + CPC) to JSONL + CSV
        if scored_path.exists() and entries:
            with open(scored_path, "w", encoding="utf-8") as f:
                for entry in entries:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            _write_csv_from_jsonl(scored_path)

    total = sum(len(v) for v in all_scored.values())
    print(f"  CPC proxy scores assigned to {total:,} questions (free rule-based, no API).")
    return all_scored


# ── OpenAI pricing (April 2025) — update if prices change ──────────────────
_LLM_PRICE: Dict[str, Dict[str, float]] = {
    "gpt-4o-mini": {"input": 0.15,  "output": 0.60},   # per 1M tokens
    "gpt-4o":      {"input": 2.50,  "output": 10.00},
}


def _print_cost_estimate(all_questions: Dict[str, List[str]]) -> None:
    """
    Print a cost breakdown BEFORE making any API calls.
    Shows $0.00 when running in local mode (Ollama).

    Methodology (API mode):
      Intent scoring (GPT-4o-mini):
        Input:  ~150 tokens/question (prompt template + question text in batch)
        Output: ~30  tokens/question (JSON object with score + reason)
      Ranking (GPT-4o):
        Input:  PRE_FILTER_SIZE * ~20 tokens/question + ~800 token prompt overhead
        Output: PRE_FILTER_SIZE * ~15 tokens/question (rank + reason JSON)
      Note: Section 1 (template/value-bank generation) is a one-time cost not shown here.
    """
    total_q  = sum(len(v) for v in all_questions.values())
    n_groups = len(QUERY_GROUPS)
    width    = 58

    if LLM_BACKEND == "local":
        model_label = f"Ollama · {OLLAMA_MODEL}"
        print(f"\n  ┌─ Cost Estimate (Section 2) ─{'─' * (width - 27)}┐")
        print(f"  │  Questions to score  : {total_q:>8,}  ({n_groups} groups){' ' * (width - 38)}│")
        print(f"  │  LLM backend         : local ({model_label}){' ' * max(0, width - 24 - len(model_label))}│")
        print(f"  │  {'─' * (width - 4)} │")
        print("  │  Estimated total     : ~$    0.00  (local model — no API cost)        │")
        print("  │  Note: quality may differ from GPT-4o for ranking step               │")
        print(f"  └{'─' * (width)}┘")
        print()
        return

    # Intent scoring: GPT-4o-mini
    intent_in   = total_q * 150
    intent_out  = total_q * 30
    intent_cost = (
        (intent_in  / 1_000_000) * _LLM_PRICE["gpt-4o-mini"]["input"] +
        (intent_out / 1_000_000) * _LLM_PRICE["gpt-4o-mini"]["output"]
    )

    # Ranking: GPT-4o  (PRE_FILTER_SIZE questions per group)
    rank_in   = (PRE_FILTER_SIZE * 20 + 800) * n_groups
    rank_out  = PRE_FILTER_SIZE * 15 * n_groups
    rank_cost = (
        (rank_in  / 1_000_000) * _LLM_PRICE["gpt-4o"]["input"] +
        (rank_out / 1_000_000) * _LLM_PRICE["gpt-4o"]["output"]
    )

    total_cost = intent_cost + rank_cost

    print(f"\n  ┌─ Cost Estimate (Section 2) ─{'─' * (width - 27)}┐")
    print(f"  │  Questions to score  : {total_q:>8,}  ({n_groups} groups){' ' * (width - 38)}│")
    print(f"  │  Intent (GPT-4o-mini): ~${intent_cost:>7.2f}  ({total_q:,} questions){' ' * max(0, width - 36 - len(str(total_q)))}│")
    print(f"  │  Ranking (GPT-4o)    : ~${rank_cost:>7.2f}  ({PRE_FILTER_SIZE}/group × {n_groups} groups){' ' * max(0, width - 40)}│")
    print(f"  │  {'─' * (width - 4)} │")
    print(f"  │  Estimated total     : ~${total_cost:>7.2f}                                  │")
    print("  │  Tip: --resume skips groups that are already scored/ranked                │")
    print(f"  └{'─' * (width)}┘")
    print()


# ── Phase 2.4: AI-Driven Ranking ──────────────────────────────────────────────

def _combined_score(entry: Dict) -> float:
    """
    Pre-filter score with honest missing-data handling.

    When popularity_score is None (Trends unavailable / no data for this keyword),
    its 30% weight is redistributed between intent and CPC rather than substituting
    a made-up number. Renormalised weights: intent 0.5/0.7 ≈ 71%, CPC 0.2/0.7 ≈ 29%.
    """
    intent = float(entry.get("intent_score",   5))
    cpc    = float(entry.get("cpc_proxy_score", 5))
    pop    = entry.get("popularity_score")  # Optional[float] — may be None

    if pop is None:
        # Popularity unknown — score on intent + CPC only (weights renormalised)
        return intent * 0.714 + cpc * 0.286

    return intent * 0.5 + (float(pop) / 10.0) * 0.3 + cpc * 0.2


def rank_questions(
    all_scored: Dict[str, List[Dict]],
    profile: dict,
    brief: str,
    client_folder: Path,
    resume: bool,
) -> Dict[str, List[Dict]]:
    """
    For each group:
      1. Pre-filter: sort all questions by combined score, keep top PRE_FILTER_SIZE.
      2. GPT-4o reads pre-filtered questions + client profile + brief, assigns group_rank.
    Saves to groups/<G*>/ranked.jsonl.
    Returns dict: group_id -> ranked entries (sorted by group_rank).
    """
    profile_snippet = json.dumps(
        {k: v for k, v in profile.items() if not k.startswith("_")},
        indent=2
    )
    all_ranked: Dict[str, List[Dict]] = {}

    for group in QUERY_GROUPS:
        gid = group["id"]
        entries = all_scored.get(gid, [])
        if not entries:
            all_ranked[gid] = []
            continue

        group_dir = client_folder / "groups" / f"{gid}_{group['name']}"
        ranked_path = group_dir / "ranked.jsonl"

        if resume and ranked_path.exists():
            ranked = []
            for line in ranked_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    ranked.append(json.loads(line))
            ranked.sort(key=lambda e: e.get("group_rank", 9999))
            all_ranked[gid] = ranked
            print(f"  [resume] {gid}: rankings loaded ({len(ranked):,} questions).")
            continue

        # Step 1: Pre-filter — sort by combined score, take top PRE_FILTER_SIZE
        sorted_entries = sorted(entries, key=_combined_score, reverse=True)
        candidates = sorted_entries[:PRE_FILTER_SIZE]
        print(f"\n  Ranking {gid}: {len(entries):,} questions -> pre-filter to top {len(candidates)} -> GPT-4o...")

        # Step 2: Build compact list for GPT-4o
        scored_list = [
            {
                "i":      i + 1,
                "q":      e.get("question", ""),
                "intent": e.get("intent_score", 5),
                "pop":    e.get("popularity_score"),  # None → null in JSON (unknown, not zero)
                "cpc":    e.get("cpc_proxy_score", 5),
            }
            for i, e in enumerate(candidates)
        ]

        prompt = f"""You are ranking search questions for an AISO (AI Search Optimization) client.

CLIENT PROFILE:
{profile_snippet}

CLIENT BRIEF (current goals & priorities):
{brief}

GROUP: {group["label"]}

Task: Rank ALL {len(candidates)} questions from 1 (most valuable) to {len(candidates)} (least valuable).

Ranking criteria — priority order:
  1. Client brief alignment: does this question reflect what the client needs to rank for RIGHT NOW?
  2. Intent to buy (field: "intent", 1-10): higher = more purchase-ready
  3. Popularity (field: "pop", 0-100 or null): higher = more searched; null means no data — do NOT penalise
  4. CPC proxy (field: "cpc", 1-10): higher = more commercial value (advertiser intent signal)

QUESTIONS:
{json.dumps(scored_list, ensure_ascii=False)}

Return a JSON array of ALL {len(candidates)} objects:
  {{ "i": <original index>, "group_rank": <1 to {len(candidates)}>, "rank_reason": "<1-2 sentences>" }}

group_rank 1 = most valuable. Every question exactly once. No ties.
Return ONLY valid JSON array, no explanation, no markdown fences."""

        raw = _strip_fences(llm_call(prompt, model="gpt-4o", temperature=0.1))
        ranked_items = json.loads(raw)
        if isinstance(ranked_items, dict):
            ranked_items = list(ranked_items.values())[0]

        # Merge rank data back
        index_to_rank = {item["i"]: item for item in ranked_items}
        ranked_candidates = []
        for i, entry in enumerate(candidates):
            rank_info = index_to_rank.get(i + 1, {})
            merged = dict(entry)
            merged["group_rank"]  = rank_info.get("group_rank", i + 1)
            merged["rank_reason"] = rank_info.get("rank_reason", "")
            merged["group"]       = gid
            merged["group_label"] = group["label"]
            ranked_candidates.append(merged)

        ranked_candidates.sort(key=lambda e: e["group_rank"])

        with open(ranked_path, "w", encoding="utf-8") as f:
            for entry in ranked_candidates:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        _write_csv_from_jsonl(ranked_path)

        all_ranked[gid] = ranked_candidates
        top_q = ranked_candidates[0].get("question", "")[:80]
        print(f"  {gid} ranked. #1: {top_q}")

    return all_ranked


# ── Phase 2.5: Write Final Outputs ────────────────────────────────────────────

RANKED_BANK_HEADERS = [
    "question", "group", "group_label",
    "group_rank", "intent_score", "popularity_score", "cpc_proxy_score", "rank_reason",
]

def write_outputs(
    all_ranked: Dict[str, List[Dict]],
    client_folder: Path,
) -> Path:
    """
    Merge top-N questions from each group into query_template_bank.csv.
    collect.py detects the 'question' column and reads questions directly
    — no expansion needed at collection time.
    """
    bank_rows: List[Dict] = []
    report_rows: List[Dict] = []

    for group in QUERY_GROUPS:
        gid = group["id"]
        entries = all_ranked.get(gid, [])
        top = entries[:TOP_QUESTIONS_PER_GROUP]

        for entry in top:
            pop = entry.get("popularity_score")
            bank_rows.append({
                "question":         entry.get("question", ""),
                "group":            gid,
                "group_label":      group["label"],
                "group_rank":       entry.get("group_rank", ""),
                "intent_score":     entry.get("intent_score", ""),
                "popularity_score": "" if pop is None else pop,
                "cpc_proxy_score":  entry.get("cpc_proxy_score", ""),
                "rank_reason":      entry.get("rank_reason", ""),
            })
            report_rows.append(entry)

    # Write ranked bank
    bank_path = client_folder / "query_template_bank.csv"
    with open(bank_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=RANKED_BANK_HEADERS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(bank_rows)

    # Write full report (gitignored)
    report_path = client_folder / "ranking_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report_rows, f, indent=2, ensure_ascii=False)

    print(f"\n  query_template_bank.csv written  {len(bank_rows)} ranked questions ({len(QUERY_GROUPS)} groups).")
    print("  ranking_report.json written.")
    return bank_path


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    # declared at top so argparse help strings can reference current default values
    global TEMPLATES_PER_GROUP, TRENDS_SLEEP_SEC, PRE_FILTER_SIZE, TOP_QUESTIONS_PER_GROUP
    global LLM_BACKEND

    parser = argparse.ArgumentParser(
        description="AISO setup2 — Intelligent question pipeline (setup 1.3)"
    )
    parser.add_argument("slug",      help="Client slug (e.g. sbaco)")
    parser.add_argument("--resume",   action="store_true",
                        help="Skip phases whose output files already exist")
    parser.add_argument("--dry-run",  action="store_true",
                        help="Expand templates, print cost estimate, then exit without calling any APIs")
    parser.add_argument("--section", choices=["1", "2"], default=None,
                        help="Run only section 1 or section 2 (default: both)")

    # ── Tunable pipeline constants (see optimal ranges in help text) ──────────
    parser.add_argument(
        "--templates-per-group", type=int, default=TEMPLATES_PER_GROUP,
        metavar="N",
        help=(
            "Templates generated per query group in Section 1. "
            "Optimal range: 100-300 (first/test run), up to 500 (production). "
            "More templates = more questions = more Trends calls + higher OpenAI cost. "
            f"Default: {TEMPLATES_PER_GROUP}"
        ),
    )
    parser.add_argument(
        "--trends-sleep", type=float, default=TRENDS_SLEEP_SEC,
        metavar="SECS",
        help=(
            "Seconds to sleep between Google Trends batch requests. "
            "Optimal range: 2.0-5.0 (safe/test), 0.8-1.5 (production, higher block risk). "
            "Lower = faster but Google may block the session mid-run. "
            f"Default: {TRENDS_SLEEP_SEC}"
        ),
    )
    parser.add_argument(
        "--pre-filter", type=int, default=PRE_FILTER_SIZE,
        metavar="N",
        help=(
            "Questions sent to GPT-4o for final ranking (pre-filtered by combined score). "
            "Optimal range: 150-300 (first run), up to 500 (production). "
            "Higher = better ranking quality but larger prompt = more cost + slower. "
            f"Default: {PRE_FILTER_SIZE}"
        ),
    )
    parser.add_argument(
        "--top-questions", type=int, default=TOP_QUESTIONS_PER_GROUP,
        metavar="N",
        help=(
            "Top-N questions kept per group in the final query_template_bank.csv. "
            "Optimal range: 50-100 (first run), up to 200 (production). "
            f"Default: {TOP_QUESTIONS_PER_GROUP}"
        ),
    )
    parser.add_argument(
        "--llm", choices=["local", "api"], default=None,
        metavar="BACKEND",
        help=(
            "LLM backend to use. "
            "'local' = Ollama (free, private, requires ollama serve). "
            "'api'   = OpenAI (gpt-4o / gpt-4o-mini, requires OPENAI_API_KEY). "
            f"Default: {LLM_BACKEND} (from LLM_BACKEND env var)"
        ),
    )
    args = parser.parse_args()

    # ── Apply --llm override first (needed for the API key check below) ──────
    if args.llm is not None:
        LLM_BACKEND = args.llm

    if LLM_BACKEND == "api" and not OPENAI_API_KEY:
        print("OPENAI_API_KEY not set but --llm api was requested. See full_stack/.env.example.")
        sys.exit(1)

    slug = normalize_slug(args.slug)
    if not slug:
        print("Slug cannot be empty.")
        sys.exit(1)

    # ── Apply remaining CLI overrides to module-level constants ──────────────
    TEMPLATES_PER_GROUP     = args.templates_per_group
    TRENDS_SLEEP_SEC        = args.trends_sleep
    PRE_FILTER_SIZE         = args.pre_filter
    TOP_QUESTIONS_PER_GROUP = args.top_questions

    client_folder = _repo_root / "clients" / slug
    client_folder.mkdir(parents=True, exist_ok=True)

    # ── Print run configuration ───────────────────────────────────────────────
    w = 62
    if LLM_BACKEND == "local":
        backend_label = f"local  (Ollama · {OLLAMA_MODEL} @ {OLLAMA_HOST})"
    else:
        backend_label = "api    (OpenAI · gpt-4o-mini / gpt-4o)"
    print(f"\n AISO setup2  {slug} ")
    print(f"\n  ┌─ Run Configuration ─{'─' * (w - 19)}┐")
    print(f"  │  llm-backend          : {backend_label:<39}│")
    print(f"  │  templates-per-group  : {TEMPLATES_PER_GROUP:<6}  [safe: 100-300 │ production: 500]  │")
    print(f"  │  trends-sleep (sec)   : {TRENDS_SLEEP_SEC:<6.1f}  [safe:  ≥2.0  │ production: 0.8]  │")
    print(f"  │  pre-filter size      : {PRE_FILTER_SIZE:<6}  [safe: 150-300 │ production: 500]  │")
    print(f"  │  top-questions/group  : {TOP_QUESTIONS_PER_GROUP:<6}  [safe:  50-100 │ production: 200]  │")
    print(f"  └{'─' * w}┘")

    run_s1 = args.section in (None, "1")
    run_s2 = args.section in (None, "2")

    # ── Section 1 ──────────────────────────────────────────────────────────
    if run_s1:
        print("\n SECTION 1: Immutable Client Profile\n")

        profile = collect_core_profile(slug, client_folder)
        _bar(1, 3, "profile done")
        print()

        value_rows = generate_value_bank(profile, client_folder, resume=args.resume)
        _bar(2, 3, "value bank done")
        print()

        all_templates = generate_group_templates(profile, client_folder, resume=args.resume)
        _bar(3, 3, "templates done")
        print()

        total_t = sum(len(v) for v in all_templates.values())
        print(f"\n  Section 1 complete  {total_t} templates across {len(QUERY_GROUPS)} groups.")

    # Load profile + templates for section 2 (when running section 2 only)
    if run_s2 and not run_s1:
        profile_path = client_folder / "client_profile.json"
        if not profile_path.exists():
            print("client_profile.json not found  run --section 1 first.")
            sys.exit(1)
        with open(profile_path, encoding="utf-8") as f:
            profile = json.load(f)

        all_templates = {}
        for group in QUERY_GROUPS:
            gid, gname = group["id"], group["name"]
            tpath = client_folder / "groups" / f"{gid}_{gname}" / "templates.txt"
            if tpath.exists():
                all_templates[gid] = [
                    ln.strip() for ln in tpath.read_text(encoding="utf-8").splitlines() if ln.strip()
                ]
            else:
                all_templates[gid] = []

    # ── Section 2 ──────────────────────────────────────────────────────────
    if run_s2:
        print("\n SECTION 2: Dynamic Profile & Ranking\n")

        # 2.1  Dynamic brief
        brief, brief_path = collect_dynamic_brief(client_folder, resume=args.resume)
        _bar(1, 6, "brief done")
        print()

        # 2.2a  Expand templates x value bank  actual questions
        vbank_path = client_folder / "value_bank.csv"
        if not vbank_path.exists():
            print("value_bank.csv not found  run --section 1 first.")
            sys.exit(1)
        value_rows_s2 = []
        with open(vbank_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                value_rows_s2.append(dict(row))

        print(f"  Expanding {sum(len(v) for v in all_templates.values())} templates "
              f"x {len(value_rows_s2)} value rows...")
        all_questions = expand_templates_to_questions(all_templates, value_rows_s2)
        total_q = sum(len(v) for v in all_questions.values())
        print(f"   {total_q:,} questions across {len(QUERY_GROUPS)} groups.")

        _print_cost_estimate(all_questions)

        if args.dry_run:
            print("  [dry-run] Inputs valid. No API calls made.")
            print("  [dry-run] Remove --dry-run flag to execute the full pipeline.")
            sys.exit(0)

        # 2.2  Intent scoring
        all_scored = score_intent(all_questions, client_folder, profile, resume=args.resume)
        _bar(2, 6, "intent scored")
        print()

        # 2.3  Popularity scoring (regional, batched)
        all_scored = score_popularity(all_scored, client_folder, profile, resume=args.resume)
        _bar(3, 6, "popularity scored")
        print()

        # 2.3b CPC proxy scoring (free, instant, rule-based)
        all_scored = score_cpc_proxy(all_scored, client_folder)
        _bar(4, 6, "CPC proxy scored")
        print()

        # 2.4  AI ranking (pre-filtered, all 3 scores visible to GPT-4o)
        all_ranked = rank_questions(all_scored, profile, brief, client_folder, resume=args.resume)
        _bar(5, 6, "ranked")
        print()

        # 2.5  Write outputs
        bank_path = write_outputs(all_ranked, client_folder)
        _bar(6, 6, "outputs written")
        print()

        print("\n Setup2 complete ")
        print(f"  Client  : {slug}")
        print(f"  Profile : {client_folder / 'client_profile.json'}")
        print(f"  Brief   : {brief_path.name}")
        print(f"  Bank    : {bank_path}  ({sum(len(v[:TOP_QUESTIONS_PER_GROUP]) for v in all_ranked.values())} questions)")
        print(f"\n  Run collect : python3 full_stack/collect.py {slug}")
        print(f"  Re-rank     : python3 full_stack/setup2.py {slug} --resume --section 2")


if __name__ == "__main__":
    main()

