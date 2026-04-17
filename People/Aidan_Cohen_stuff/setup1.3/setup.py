import sys
import re
import json
import csv
import os
from pathlib import Path

# Ensure repo root is on sys.path (this file lives at People/Aidan_Cohen_stuff/setup2/setup.py)
_repo_root = Path(__file__).resolve().parent.parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from dotenv import load_dotenv
load_dotenv(_repo_root / ".env")

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")


# ── helpers ───────────────────────────────────────────────────────────────────

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
    """20-segment loading bar (same style as aoi_benchmark_scoreing_0.py)."""
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


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    if not OPENAI_API_KEY:
        print("OPENAI_API_KEY not set. See full_stack/.env.example.")
        sys.exit(1)

    # 1.1 — get slug (from CLI or prompt)
    if len(sys.argv) >= 2:
        slug = normalize_slug(sys.argv[1])
    else:
        raw = input("Business identifier (slug, e.g. acme_corp): ").strip()
        slug = normalize_slug(raw)

    if not slug:
        print("Slug cannot be empty.")
        sys.exit(1)

    client_folder = _repo_root / slug

    # idempotency check
    if (client_folder / "query_template_bank.csv").exists() or (client_folder / "config.json").exists():
        print(f"Already set up for '{slug}'. Delete bank CSVs and config.json to re-run setup.")
        sys.exit(1)

    client_folder.mkdir(parents=True, exist_ok=True)
    print(f"Created folder: {client_folder}")
    # loading bar (same style as aoi_benchmark_scoreing_0.py) — phase 1/5
    _bar(1, 5)

    # 1.2 — chat + datafile
    datafile = collect_context(slug, client_folder)
    _bar(2, 5)

    # 1.4 — generate rows via AI
    template_rows, value_rows = generate_rows(datafile)
    _bar(3, 5)

    # 1.5 — write CSVs
    write_bank_csvs(client_folder, template_rows, value_rows)
    _bar(4, 5)

    # 1.6 — write config
    write_config(client_folder, slug, datafile)
    _bar(5, 5)

    print()
    print(f"Setup complete for '{slug}'.")
    print(f"Recommend reviewing {client_folder / 'query_template_bank.csv'} and {client_folder / 'value_bank.csv'} before running collect.")
    print(f"Run collect: python full_stack/collect.py {slug}")


# ── 1.2 ──────────────────────────────────────────────────────────────────────

def collect_context(slug: str, client_folder: Path) -> dict:
    """Run interactive chat. Blocks until required fields collected. Writes datafile.json."""
    print("\nPlease do this quick chat so we can set up your AISO banks.\n")

    def ask(prompt, required=True):
        while True:
            val = input(prompt).strip()
            if val or not required:
                return val
            print("  (required — please enter a value)")

    industry = ask("Industry / category (e.g. tours, restaurants, legal services): ")
    products = ask("Products or services (short list): ")
    geography = ask("Geography (city, region, or 'nationwide'): ")
    display_name = ask("Display name (optional, press Enter to skip): ", required=False)
    example_raw = ask("1-3 example queries (optional, comma-separated, press Enter to skip): ", required=False)
    target_customer = ask("Target customer (optional, press Enter to skip): ", required=False)

    example_queries = [q.strip() for q in example_raw.split(",") if q.strip()] if example_raw else []

    data = {
        "slug": slug,
        "industry": industry,
        "products_services": products,
        "geography": geography,
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


# ── 1.4 ──────────────────────────────────────────────────────────────────────

def generate_rows(datafile: dict):
    """Use AI to generate template_rows and value_rows. Validates with build_queries_from_matrix."""
    from openai import OpenAI
    from full_stack.schema import TEMPLATE_HEADERS, VALUE_HEADERS
    from full_stack.lib import build_queries_from_matrix

    client = OpenAI(api_key=OPENAI_API_KEY)

    for key in ("industry", "products_services", "geography"):
        if not datafile.get(key):
            print(f"datafile missing required field: {key}")
            sys.exit(1)

    # 1.4.2 — generate template rows
    template_prompt = f"""You are generating query template rows for an AI search optimization system.

Client info:
{json.dumps(datafile, indent=2)}

Generate 5-8 template rows as a JSON array of objects.
Each object must have exactly these keys: {TEMPLATE_HEADERS}
Each value must be a search query string containing at least one placeholder from: {{service}}, {{city}}, {{brand}}, {{landmark}}, {{neighborhood}}, {{pain_point}}, {{vibe}}, {{location}}
Return only valid JSON with no explanation and no markdown fences."""

    r1 = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": template_prompt}],
        temperature=0.4,
    )
    template_rows = json.loads(_strip_fences(r1.choices[0].message.content))
    print(f"Generated {len(template_rows)} template rows.")

    # 1.4.3 — generate value rows
    value_prompt = f"""You are generating value bank rows for an AI search optimization system.

Client info:
{json.dumps(datafile, indent=2)}

Generate 5-8 value rows as a JSON array of objects.
Each object must have exactly these keys: {VALUE_HEADERS}
Values should be realistic and specific to this client's industry, products, and geography.
Return only valid JSON with no explanation and no markdown fences."""

    r2 = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": value_prompt}],
        temperature=0.4,
    )
    value_rows = json.loads(_strip_fences(r2.choices[0].message.content))
    print(f"Generated {len(value_rows)} value rows.")

    # 1.4.4 — validate
    questions = build_queries_from_matrix(template_rows, value_rows)
    if not questions:
        print("Validation failed: build_queries_from_matrix returned empty list.")
        sys.exit(1)
    if any("{" in q for q in questions):
        print("Validation failed: unfilled placeholders in generated questions.")
        sys.exit(1)
    print(f"Matrix validated: {len(questions)} questions generated.")

    return template_rows, value_rows


# ── 1.5 ──────────────────────────────────────────────────────────────────────

def write_bank_csvs(client_folder: Path, template_rows: list, value_rows: list):
    from full_stack.schema import TEMPLATE_HEADERS, VALUE_HEADERS

    t_path = client_folder / "query_template_bank.csv"
    with open(t_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=TEMPLATE_HEADERS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(template_rows)
    print(f"Written: {t_path}")

    v_path = client_folder / "value_bank.csv"
    with open(v_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=VALUE_HEADERS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(value_rows)
    print(f"Written: {v_path}")


# ── 1.6 ──────────────────────────────────────────────────────────────────────

def write_config(client_folder: Path, slug: str, datafile: dict):
    config = {"slug": slug}
    if datafile.get("display_name"):
        config["display_name"] = datafile["display_name"]
    config_path = client_folder / "config.json"
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    print(f"Written: {config_path}")


if __name__ == "__main__":
    main()
