"""
Re-runs the original 124 questions from benchmark_data_0 through GPT-4o-mini
using the exact same settings as aoi_benchmark_0.py, then updates
SBACO_mesureable_results.csv with new percentage data.
"""

import sys
import re
import csv
import pandas as pd
from openai import OpenAI
import gspread
from google.oauth2.service_account import Credentials

# ── Config (mirrors aoi_benchmark_0.py exactly) ──────────────────────────────

SERVICE_ACCOUNT_FILE = r"C:\Users\aidan\Documents\Integrated_ai\SBACO\aio_benchmark\integratedai-aio-sbaco-3574b6eeec4a.json"

VALUE_BANK_SHEET_ID       = "1vjygw5WtihPQDtCgXO4wuJlDrrvdmIU_2NJxuveoiOA"
VALUE_BANK_TAB            = "Sheet1"

QUERY_TEMPLATE_SHEET_ID   = "1u-pvrFWtE5_XY3F8F_6fbaPSS3aIM5dWcO8XIN0YCto"
QUERY_TEMPLATE_TAB        = "Sheet1"

BENCHMARK_DATA_0          = r"C:\Users\aidan\Documents\Integrated_ai\SBACO\aio_benchmark\benchmark_data_0.csv"
OUTPUT_CSV                = r"C:\Users\aidan\Documents\Integrated_ai\SBACO\aio_benchmark\benchmark_retest_original_124.csv"
RESULTS_CSV               = r"C:\Users\aidan\Documents\Integrated_ai\playground\SBACO_mesureable_results.csv"

COMPANIES = [
    "Santa Barbara Surf School",
    "Island Packers",
    "Surf Happens",
    "Santa Barbara Adventure Company",
    "Santa Barbara Wine Tours",
]

# Load API key from .env
def load_api_key():
    env_path = r"C:\Users\aidan\Documents\Integrated_ai\SBACO\aio_benchmark\.env"
    with open(env_path, "r") as f:
        for line in f:
            line = line.strip()
            if line.startswith("OPENAI_API_KEY"):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("OPENAI_API_KEY not found in .env")

openai_api_key = load_api_key()

# ── Step 1: Pull same templates + values from Google Sheets ──────────────────

def get_sheet_records(sheet_id, tab_name):
    scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    creds  = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=scopes)
    client = gspread.authorize(creds)
    ws     = client.open_by_key(sheet_id).worksheet(tab_name)
    headers = [h.strip() for h in ws.row_values(1)]
    data    = ws.get_all_values()[1:]
    records = []
    for row in data:
        if not any(cell.strip() for cell in row):
            continue
        row += [""] * (len(headers) - len(row))
        record = {h: c.strip() for h, c in zip(headers, row) if c.strip()}
        records.append(record)
    return records

def build_queries(template_rows, value_rows):
    result = []
    for t_row in template_rows:
        for _, raw_template in t_row.items():
            if not raw_template:
                continue
            for v_row in value_rows:
                try:
                    result.append(raw_template.strip().format(**v_row))
                except KeyError:
                    continue
    return result

print("Fetching templates and values from Google Sheets...")
templates = get_sheet_records(QUERY_TEMPLATE_SHEET_ID, QUERY_TEMPLATE_TAB)
values    = get_sheet_records(VALUE_BANK_SHEET_ID, VALUE_BANK_TAB)
questions = build_queries(templates, values)
print(f"Generated {len(questions)} questions (expect 124)")

# ── Step 2: Query GPT-4o-mini exactly like aoi_benchmark_0.py ────────────────

openai_client = OpenAI(api_key=openai_api_key)
response_list = []

print("Querying GPT-4o-mini (3x per question)...")
for i, question in enumerate(questions):
    response = ["", "", ""]
    for j in range(3):
        response[j] = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": question}],
            temperature=0.4,
            max_tokens=1024,
        ).choices[0].message.content.strip()
    response_list.append(response)

    # Loading bar
    filled = round((i + 1) / len(questions) * 20)
    bar = "#" * filled + "_" * (20 - filled)
    print(f"\r[{bar}] {i+1}/{len(questions)}", end="", flush=True)

print("\nDone. Saving benchmark_data_2.csv...")
pd.DataFrame(response_list).to_csv(OUTPUT_CSV, index=False)

# ── Step 3: Count mentions and recalculate percentages ───────────────────────

with open(OUTPUT_CSV, "r", encoding="utf-8", errors="replace") as f:
    content = f.read()

counts = {c: len(re.findall(re.escape(c), content)) for c in COMPANIES}
total  = sum(counts.values())

print(f"\nTotal mentions across all 5 companies: {total}")
for c, n in counts.items():
    print(f"  {n:4d}  {n/total*100:.1f}%  {c}")

# ── Step 4: Update SBACO_mesureable_results.csv ──────────────────────────────

results = pd.read_csv(RESULTS_CSV)

# Rename old second benchmark column to clarify it came from data_1
results.columns = [
    "Rank", "Company",
    "Mentions 7/14/2025", "% of Mentions 7/14/2025",
    "Mentions 3/13/2026 (data_1)", "% of Mentions 3/13/2026 (data_1)",
]

# Add new apples-to-apples retest columns
results["Mentions Retest (same Qs)"] = [counts[c] for c in COMPANIES]
results["% of Mentions Retest (same Qs)"] = [
    f"{counts[c]/total*100:.1f}%" for c in COMPANIES
]

results.to_csv(RESULTS_CSV, index=False)
print(f"\nUpdated {RESULTS_CSV}")
