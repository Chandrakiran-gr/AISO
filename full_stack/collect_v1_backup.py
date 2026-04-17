import sys
import re
import csv
import os
import json
from pathlib import Path
from glob import glob

question_number = 100

# Ensure repo root is on sys.path
_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from dotenv import load_dotenv
load_dotenv(_repo_root / ".env")

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")


def normalize_slug(raw: str) -> str:
    slug = raw.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    return slug.strip("_")


def main():
    if not OPENAI_API_KEY:
        print("OPENAI_API_KEY not set. See full_stack/.env.example.")
        sys.exit(1)

    # 2.1.1 — resolve client folder
    if len(sys.argv) >= 2:
        arg = sys.argv[1]
    else:
        arg = input("Business folder path or slug: ").strip()

    client_folder, slug = resolve_client_folder(arg)

    # 2.1.2 — require bank CSVs
    t_path = client_folder / "query_template_bank.csv"
    v_path = client_folder / "value_bank.csv"
    if not t_path.exists():
        print(f"Missing query_template_bank.csv in {client_folder}")
        sys.exit(1)
    if not v_path.exists():
        print(f"Missing value_bank.csv in {client_folder}")
        sys.exit(1)

    # 2.2 — load banks
    from full_stack.lib import read_csv_to_rows, build_queries_from_matrix, call_webish

    template_rows = read_csv_to_rows(t_path)
    if not template_rows:
        print(f"query_template_bank.csv is empty or has no data rows: {t_path}")
        sys.exit(1)

    value_rows = read_csv_to_rows(v_path)
    if not value_rows:
        print(f"value_bank.csv is empty or has no data rows: {v_path}")
        sys.exit(1)

    # 2.3 — build question list
    questions = build_queries_from_matrix(template_rows, value_rows)
    if not questions or any("{" in q for q in questions):
        print("Failed to build question list — check bank CSV structure.")
        sys.exit(1)
    print(f"Built {len(questions)} questions.")

    # 2.4 — run webish per question
    records = []
    total = len(questions)

    if len(questions) > question_number:
        q = questions

        questions = []
       
        n = round(len(q) / question_number)


        for i in range(len(q)):
            if i % n == 0:

                questions.append(q[i])

    print("only running " + str(len(questions)) + " questions")

    total = len(questions)

    for i, question in enumerate(questions):
        try:
            response = call_webish(question)
            records.append((question, response, ""))
        except Exception as e:
            records.append((question, "", str(e)))
        # loading bar (same style as aoi_benchmark_scoreing_0.py)
        loading_bar = ""
        filled = round((i + 1) / total * 20) if total else 0
        for _ in range(filled):
            loading_bar += "█"
        for _ in range(20 - filled):
            loading_bar += "_"
        try:
            print("\r" + loading_bar, end="", flush=True)
        except UnicodeEncodeError:
            print("\r" + loading_bar.replace("█", "#"), end="", flush=True)

    print(f"\nDone. {sum(1 for _, _, e in records if not e)} succeeded, {sum(1 for _, _, e in records if e)} failed.")

    # 2.5.1 — determine next N
    pattern = str(client_folder / f"{slug}_aisodata*.csv")
    existing = glob(pattern)
    indices = []
    for p in existing:
        name = Path(p).stem
        m = re.search(r"_aisodata(\d+)$", name)
        if m:
            indices.append(int(m.group(1)))
    next_n = (max(indices) + 1) if indices else 0
    out_path = client_folder / f"{slug}_aisodata{next_n}.csv"
    while out_path.exists():
        next_n += 1
        out_path = client_folder / f"{slug}_aisodata{next_n}.csv"

    # 2.5.2 — write CSV
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["question", "response", "error"])
        for question, response, error in records:
            writer.writerow([question, response, error])

    print(f"Written: {out_path} ({len(records)} rows)")


def resolve_client_folder(arg: str):
    """Resolve arg (path or slug) to (client_folder_path, slug). Exits on failure."""
    p = Path(arg)
    if p.exists() and p.is_dir():
        client_folder = p.resolve()
    else:
        slug = normalize_slug(arg)
        client_folder = _repo_root / slug
        if not client_folder.exists():
            print(f"Business folder not found: {client_folder}")
            sys.exit(1)

    # derive slug: prefer config.json, fall back to folder name
    config_path = client_folder / "config.json"
    if config_path.exists():
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
        slug = cfg.get("slug", client_folder.name)
    else:
        slug = normalize_slug(client_folder.name)

    return client_folder, slug


if __name__ == "__main__":
    main()
