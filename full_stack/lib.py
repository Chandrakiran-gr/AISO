import sys
from pathlib import Path

# Ensure repo root (Integrated_ai/) is on sys.path
_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

import csv
from typing import List, Dict


def read_csv_to_rows(csv_path) -> List[Dict[str, str]]:
    """Read a CSV file with header row. Returns list of dicts (one per data row, keys = headers). UTF-8."""
    rows = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(dict(row))
    return rows


def build_queries_from_matrix(template_rows: List[Dict], value_rows: List[Dict]) -> List[str]:
    """Expand template x value matrix. Replaces {placeholder} tokens with value columns. Returns list of question strings."""
    result = []
    for t_row in template_rows:
        for _, raw_template in t_row.items():
            if not raw_template:
                continue
            raw_template = raw_template.strip()
            for v_row in value_rows:
                try:
                    filled = raw_template.format(**v_row)
                    result.append(filled)
                except KeyError:
                    continue
    return result


def call_webish(query: str) -> str:
    """Call webish(query, mode='api') and return the response string."""
    from webish.webish import webish
    return webish(query, mode="api")
