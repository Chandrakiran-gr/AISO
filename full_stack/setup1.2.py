import sys
import re
import json
import csv
import os
import time
import math
from pathlib import Path
from typing import List, Dict

# Ensure repo root is on sys.path
_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from dotenv import load_dotenv
load_dotenv(_repo_root / ".env")

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
# ── Constants (single source of truth — BUILD-TIME DEFAULTS) ──────────────
TARGET_TEMPLATE_ROWS = 50
TARGET_VALUE_ROWS = 100
MAX_EXPANSION_CAP = 5000
TESTER_QUESTION_COUNT = 50
TOP_N_AFTER_TRENDS = 25
EMBEDDING_SIMILARITY_THRESHOLD = 0.85
EMBEDDING_MODEL = "text-embedding-3-small"
TRENDS_GEO = "US"
TRENDS_TIMEWINDOW = "today 12-m"

# Intent buckets: (name, cap); caps sum to 50
INTENT_BUCKETS = [
    ("best X", 8),
    ("X near me / X in [place]", 8),
    ("how much / cost / price X", 6),
    ("X vs Y", 6),
    ("what is X", 6),
    ("how to X", 6),
    ("X for [audience]", 5),
    ("X open / hours", 5),
]


# ── Helpers ──────────────────────────────────────────────────────────────────

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


def _bar(current: int, total: int) -> None:
    """20-segment progress bar."""
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


# ── Step 1.1: operating_model normalization ───────────────────────────────────

def _normalize_operating_model(raw: str) -> str:
    """Normalize user input to: physical | online | both. Default: both."""
    lower = raw.lower().strip()
    if any(kw in lower for kw in ("online", "internet", "anywhere", "digital", "virtual", "remote")):
        return "online"
    if any(kw in lower for kw in ("physical", "brick", "mortar", "storefront", "in-person", "in person")):
        return "physical"
    if any(kw in lower for kw in ("both", "hybrid")):
        return "both"
    return "both"  # default per BUILD-TIME DEFAULTS


# ── Step 1: Collect context ───────────────────────────────────────────────────

def collect_context(slug: str, client_folder: Path) -> dict:
    """Interactive chat to collect all client context fields."""
    print("\nPlease do this quick chat so we can set up your AISO banks.\n")

    def ask(prompt, required=True):
        while True:
            val = input(prompt).strip()
            if val or not required:
                return val
            print("  (required — please enter a value)")

    # Core fields
    industry = ask("Industry / category (e.g. tours, restaurants, legal services): ")
    products = ask("Products or services (short list): ")
    geography = ask("Geography (city, region, or 'nationwide'): ")
    display_name = ask("Display name (optional, press Enter to skip): ", required=False)
    example_raw = ask("1-3 example queries (optional, comma-separated, press Enter to skip): ", required=False)
    target_customer = ask("Target customer (optional, press Enter to skip): ", required=False)

    # Step 1.1.1 — operating_model (wording per BUILD-TIME DEFAULTS)
    raw_model = ask("Does this business operate from a physical location, only online, or both? (physical / online / both): ")
    operating_model = _normalize_operating_model(raw_model)

    # Step 1.1.2 — operating_region (wording per BUILD-TIME DEFAULTS)
    if operating_model == "online":
        operating_region = ask(
            "Where does it operate? (city, region, or country — e.g. Santa Barbara, California, or 'nationwide', or 'online only'): ",
            required=False
        ) or "online only"
    else:
        operating_region = ask(
            "Where does it operate? (city, region, or country — e.g. Santa Barbara, California, or 'nationwide', or 'online only'): "
        )

    example_queries = [q.strip() for q in example_raw.split(",") if q.strip()] if example_raw else []

    data = {
        "slug": slug,
        "industry": industry,
        "products_services": products,
        "geography": geography,
        "operating_model": operating_model,
        "operating_region": operating_region,
    }
    if display_name:
        data["display_name"] = display_name
    if example_queries:
        data["example_queries"] = example_queries
    if target_customer:
        data["target_customer"] = target_customer

    datafile_path = client_folder / "datafile.json"
    with open(datafile_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"\nDatafile written: {datafile_path}")
    return data


# ── Step 1.2.1.1: Build location-rules string ─────────────────────────────────

def _build_location_rules(datafile: dict) -> str:
    """Build location-aware rules string from operating_model and operating_region."""
    model = datafile.get("operating_model", "both")
    region = datafile.get("operating_region", "")

    if model == "online":
        rules = (
            "Location rules: This business operates ONLINE ONLY. "
            "Avoid or minimize location placeholders ({city}, {landmark}, {neighborhood}, {location}) in templates and values. "
            "Prefer generic, non-location-specific phrasing. "
            "Do NOT generate 'X near me' or 'X in [city]' as primary formats."
        )
    elif model == "physical":
        rules = (
            "Location rules: This business operates from a PHYSICAL LOCATION. "
            "Require at least one template or value set using a location placeholder ({city}, {landmark}, {neighborhood}, or {location}). "
            "Local-intent queries (near me, in [city], [neighborhood]) are highly important."
        )
    else:  # both
        rules = (
            "Location rules: This business operates BOTH physically and online. "
            "Include a mix of location-specific and generic templates. "
            "At least one template should use a location placeholder ({city}, {landmark}, {neighborhood}, or {location})."
        )

    if region and region.lower() not in ("online only", "online", "anywhere"):
        rules += f" Operating region: {region}. Use this as example place names where appropriate in generated questions."

    return rules


# ── Step 2.1: Generate candidates + dedupe to 50 ─────────────────────────────

def _get_openai_client():
    from openai import OpenAI
    return OpenAI(api_key=OPENAI_API_KEY)


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


def _embed_texts(texts: List[str], client) -> List[List[float]]:
    """Embed a list of texts using text-embedding-3-small."""
    response = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=texts,
    )
    return [item.embedding for item in response.data]


def _generate_candidate_questions(datafile: dict, location_rules: str, client, count_hint: int = 70) -> List[str]:
    """Step 2.1.2: Call LLM for ~60-80 candidate tester questions with bucket/quota prompt."""
    # Step 2.1.1 — bucket/quota description encoded in prompt
    bucket_desc = "\n".join(
        f"  - \"{name}\" (target ~{cap})" for name, cap in INTENT_BUCKETS
    )

    prompt = f"""You are generating tester search questions for an AI search optimization system.

Client info:
{json.dumps(datafile, indent=2)}

{location_rules}

Generate exactly {count_hint} search questions that real people would type when looking for this business.

Intent buckets — spread your questions proportionally across these categories:
{bucket_desc}

Requirements:
- Each question must belong to a distinct idea or format (no two that are the same concept)
- At least 2 questions from each bucket
- Mix of short (3-5 words) and long-tail (7+ words) questions
- Questions should sound natural, like real people searching — not marketing copy

Return a JSON array of strings, one question per element.
No explanation, no markdown fences, just the JSON array."""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
    )
    raw = _strip_fences(response.choices[0].message.content)
    try:
        candidates = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(candidates, list):
        return []
    return [str(q).strip() for q in candidates if str(q).strip()]


def _dedupe_to_50(datafile: dict, location_rules: str, client) -> List[str]:
    """Steps 2.1.1–2.1.3: Generate candidates and dedupe by embedding similarity to exactly 50."""
    accepted: List[str] = []
    accepted_embeddings: List[List[float]] = []

    max_rounds = 6
    round_num = 0

    while len(accepted) < TESTER_QUESTION_COUNT and round_num < max_rounds:
        round_num += 1
        needed = TESTER_QUESTION_COUNT - len(accepted)
        request_count = max(70, needed + 30)
        print(f"\n  [round {round_num}] accepted={len(accepted)}, requesting {request_count} candidates...")

        candidates = _generate_candidate_questions(datafile, location_rules, client, count_hint=request_count)
        if not candidates:
            print("  Warning: LLM returned no candidates.")
            break

        # Step 2.1.3.1 — embed candidates
        try:
            embeddings = _embed_texts(candidates, client)
        except Exception as e:
            print(f"  Warning: embedding failed ({e}). Using exact-string dedupe fallback.")
            for q in candidates:
                if q not in accepted and len(accepted) < TESTER_QUESTION_COUNT:
                    accepted.append(q)
            break

        # Step 2.1.3.2 — filter by threshold
        for q, emb in zip(candidates, embeddings):
            if len(accepted) >= TESTER_QUESTION_COUNT:
                break
            if not accepted_embeddings:
                accepted.append(q)
                accepted_embeddings.append(emb)
                continue
            max_sim = max(_cosine_similarity(emb, acc_emb) for acc_emb in accepted_embeddings)
            if max_sim < EMBEDDING_SIMILARITY_THRESHOLD:
                accepted.append(q)
                accepted_embeddings.append(emb)

    # Step 2.1.3.3 — finalize to exactly 50
    if len(accepted) > TESTER_QUESTION_COUNT:
        accepted = accepted[:TESTER_QUESTION_COUNT]
    if len(accepted) < TESTER_QUESTION_COUNT:
        print(f"  Warning: only {len(accepted)} unique questions after {max_rounds} rounds (target {TESTER_QUESTION_COUNT}).")

    print(f"  Tester questions: {len(accepted)} unique questions selected.")
    return accepted


# ── Step 2.2: Rank by trends → top 25 ────────────────────────────────────────

def _get_trend_scores(tester_questions: List[str]) -> Dict[str, float]:
    """Steps 2.2.1.1–2.2.1.3: pytrends score per question. Fallback on failure."""
    try:
        from pytrends.request import TrendReq
    except ImportError:
        print("Trends unavailable (pytrends not installed); using first 25 by order.")
        return _fallback_scores(tester_questions)

    question_to_score: Dict[str, float] = {}

    try:
        # Step 2.2.1.1 — init pytrends
        pytrends = TrendReq(hl="en-US", tz=360)

        # Step 2.2.1.2 — score each question (one at a time with delay to avoid rate limits)
        for i, question in enumerate(tester_questions):
            keyword = question[:100]  # pytrends keyword length limit
            try:
                pytrends.build_payload([keyword], timeframe=TRENDS_TIMEWINDOW, geo=TRENDS_GEO)
                df = pytrends.interest_over_time()
                if df.empty or keyword not in df.columns:
                    score = 0.0
                else:
                    series = df[keyword].dropna()
                    if len(series) > 1:
                        score = float(series.mean())
                    elif len(series) == 1:
                        score = float(series.iloc[-1])
                    else:
                        score = 0.0
                question_to_score[question] = score
                time.sleep(0.6)  # respect rate limits
            except Exception:
                question_to_score[question] = 0.0

        # Step 2.2.1.3 — if all zeros, apply fallback
        if all(v == 0.0 for v in question_to_score.values()):
            print("Trends unavailable; using first 25 by order.")
            return _fallback_scores(tester_questions)

        return question_to_score

    except Exception as e:
        # Step 2.2.1.3 — full fallback
        print(f"Trends unavailable ({e}); using first 25 by order.")
        return _fallback_scores(tester_questions)


def _fallback_scores(tester_questions: List[str]) -> Dict[str, float]:
    """Fallback: first 25 by list order get score 1.0, rest 0.0."""
    scores = {}
    for i, q in enumerate(tester_questions):
        scores[q] = 1.0 if i < TOP_N_AFTER_TRENDS else 0.0
    return scores


def _select_top25(tester_questions: List[str], question_to_score: Dict[str, float], client_folder: Path) -> List[str]:
    """Step 2.2.2: Sort by score descending, return top 25. Write debug JSON."""
    sorted_questions = sorted(tester_questions, key=lambda q: question_to_score.get(q, 0.0), reverse=True)
    top25 = sorted_questions[:TOP_N_AFTER_TRENDS]

    debug_path = client_folder / "top25_tester_questions.json"
    with open(debug_path, "w", encoding="utf-8") as f:
        json.dump(
            {"top25": top25, "all_scores": {q: question_to_score.get(q, 0.0) for q in sorted_questions}},
            f, indent=2, ensure_ascii=False
        )
    print(f"\n  Top 25 written to: {debug_path}")
    return top25


# ── Step 3: Generate large banks shaped by top 25 + validate ─────────────────

def _generate_template_rows(datafile: dict, top25: List[str], location_rules: str, client) -> List[Dict]:
    """Step 3.2.1.1: Generate TARGET_TEMPLATE_ROWS template rows via LLM."""
    from full_stack.schema import TEMPLATE_HEADERS

    top25_block = "\n".join(f"  {i+1}. {q}" for i, q in enumerate(top25))

    # Step 3.1.2 — top 25 included as examples in prompt
    prompt = f"""You are generating query template rows for an AI search optimization system.

Client info:
{json.dumps(datafile, indent=2)}

{location_rules}

Example questions (match this style and variety):
{top25_block}

Generate exactly {TARGET_TEMPLATE_ROWS} template rows as a JSON array of objects.
Each object must have exactly these keys: {TEMPLATE_HEADERS}
Each value must be a search query string containing at least one placeholder from: {{service}}, {{city}}, {{brand}}, {{landmark}}, {{neighborhood}}, {{pain_point}}, {{vibe}}, {{location}}
Vary the styles, intents, and formats across rows — use the example questions above as style guides.
Return only valid JSON — no explanation, no markdown fences."""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.5,
    )
    raw = _strip_fences(response.choices[0].message.content)
    rows = json.loads(raw)
    if not isinstance(rows, list):
        raise ValueError("Template rows LLM response is not a list.")
    print(f"  Generated {len(rows)} template rows.")
    return rows


def _generate_value_rows(datafile: dict, top25: List[str], location_rules: str, client) -> List[Dict]:
    """Step 3.2.1.2: Generate TARGET_VALUE_ROWS value rows via LLM."""
    from full_stack.schema import VALUE_HEADERS

    top25_block = "\n".join(f"  {i+1}. {q}" for i, q in enumerate(top25))

    # Step 3.1.2 — top 25 included as examples in prompt
    prompt = f"""You are generating value bank rows for an AI search optimization system.

Client info:
{json.dumps(datafile, indent=2)}

{location_rules}

Example questions (match the style and real-world phrasing of these):
{top25_block}

Generate exactly {TARGET_VALUE_ROWS} value rows as a JSON array of objects.
Each object must have exactly these keys: {VALUE_HEADERS}
Values should be realistic and specific to this client's industry, products, and geography.
Vary each row — different services, cities, landmarks, vibes, pain points, etc.
Return only valid JSON — no explanation, no markdown fences."""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.5,
    )
    raw = _strip_fences(response.choices[0].message.content)
    rows = json.loads(raw)
    if not isinstance(rows, list):
        raise ValueError("Value rows LLM response is not a list.")
    print(f"  Generated {len(rows)} value rows.")
    return rows


def generate_large_banks(datafile: dict, top25: List[str], location_rules: str):
    """Steps 3.1–3.2: Generate and validate template + value rows."""
    from full_stack.lib import build_queries_from_matrix

    client = _get_openai_client()

    # Step 3.2.1.1
    template_rows = _generate_template_rows(datafile, top25, location_rules, client)
    # Step 3.2.1.2
    value_rows = _generate_value_rows(datafile, top25, location_rules, client)

    # Step 3.2.2.1 — call build_queries_from_matrix
    expanded = build_queries_from_matrix(template_rows, value_rows)

    # Step 3.2.2.2 — check for unfilled placeholders
    bad = [q for q in expanded if "{" in q]
    if bad:
        print(f"  Warning: {len(bad)} questions have unfilled placeholders. Examples: {bad[:3]}")
        expanded = [q for q in expanded if "{" not in q]
        print(f"  Filtered to {len(expanded)} clean questions.")

    # Step 3.2.2.3 — enforce cap; truncation only affects in-memory validation list
    if len(expanded) > MAX_EXPANSION_CAP:
        print(f"  Warning: expanded count {len(expanded)} exceeds MAX_EXPANSION_CAP={MAX_EXPANSION_CAP}. Truncating.")
        expanded = expanded[:MAX_EXPANSION_CAP]

    if not expanded:
        print("  Validation failed: no valid expanded questions after validation.")
        sys.exit(1)

    print(f"  Matrix validated: {len(expanded)} questions.")
    return template_rows, value_rows


# ── Step 4: Write artifacts ───────────────────────────────────────────────────

def write_bank_csvs(client_folder: Path, template_rows: list, value_rows: list):
    """Steps 4.1.1–4.1.2: Write query_template_bank.csv and value_bank.csv."""
    from full_stack.schema import TEMPLATE_HEADERS, VALUE_HEADERS

    # Step 4.1.1
    t_path = client_folder / "query_template_bank.csv"
    with open(t_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=TEMPLATE_HEADERS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(template_rows)
    print(f"Written: {t_path}")

    # Step 4.1.2
    v_path = client_folder / "value_bank.csv"
    with open(v_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=VALUE_HEADERS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(value_rows)
    print(f"Written: {v_path}")


def write_config(client_folder: Path, slug: str, datafile: dict):
    """Step 4.1.3: Write config.json."""
    config = {"slug": slug}
    if datafile.get("display_name"):
        config["display_name"] = datafile["display_name"]
    config_path = client_folder / "config.json"
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    print(f"Written: {config_path}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    # Step 0.1.1 — API key check (exit with clear message if missing)
    if not OPENAI_API_KEY:
        print("OPENAI_API_KEY not set. See full_stack/.env.example.")
        sys.exit(1)

    # Step 0.1.1 — slug from CLI or prompt
    if len(sys.argv) >= 2:
        slug = normalize_slug(sys.argv[1])
    else:
        raw = input("Business identifier (slug, e.g. acme_corp): ").strip()
        slug = normalize_slug(raw)

    if not slug:
        print("Slug cannot be empty.")
        sys.exit(1)

    client_folder = _repo_root / "clients" / slug

    # Step 0.1.1 — idempotency: refuse if banks/config already exist
    if (client_folder / "query_template_bank.csv").exists() or (client_folder / "config.json").exists():
        print(f"Already set up for '{slug}'. Delete bank CSVs and config.json to re-run setup.")
        sys.exit(1)

    # Step 0.1.2 — create client folder under clients/
    client_folder.mkdir(parents=True, exist_ok=True)
    print(f"Created folder: {client_folder}")

    # ── Phase 1: Collect context ──────────────────────────────────────────
    datafile = collect_context(slug, client_folder)
    _bar(1, 5)

    # Step 1.2.1.1 — build location rules from datafile (injected into all downstream prompts)
    location_rules = _build_location_rules(datafile)

    # ── Phase 2: Tester questions ─────────────────────────────────────────
    print("\n\nGenerating 50 unique tester questions...")
    openai_client = _get_openai_client()
    tester_questions = _dedupe_to_50(datafile, location_rules, openai_client)
    _bar(2, 5)

    # ── Phase 3: Trends ranking → top 25 ─────────────────────────────────
    print("\n\nRanking by Google Trends...")
    question_to_score = _get_trend_scores(tester_questions)
    top25 = _select_top25(tester_questions, question_to_score, client_folder)
    print("  Top 25 selected.")
    _bar(3, 5)

    # ── Phase 4: Generate large banks ────────────────────────────────────
    print("\n\nGenerating large template and value banks...")
    template_rows, value_rows = generate_large_banks(datafile, top25, location_rules)
    _bar(4, 5)

    # ── Phase 5: Write artifacts ──────────────────────────────────────────
    write_bank_csvs(client_folder, template_rows, value_rows)
    write_config(client_folder, slug, datafile)
    _bar(5, 5)

    # Step 4.2.1 — print review + next-step guidance
    print()
    print(f"Setup complete for '{slug}'.")
    print(f"Recommend reviewing {client_folder / 'query_template_bank.csv'} and {client_folder / 'value_bank.csv'} before running collect.")
    print(f"Run collect: python full_stack/collect.py {slug}")


if __name__ == "__main__":
    main()
