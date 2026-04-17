import sys
import re
import csv
import os
import json
import time
from pathlib import Path

# Ensure repo root is on sys.path
_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from dotenv import load_dotenv
load_dotenv(_repo_root / ".env")


def humanize(slug_or_name: str) -> str:
    """Convert slug/folder name to display name: underscores → spaces, title-cased."""
    return slug_or_name.replace("_", " ").title()


def ai_assign(ai_client, response_text: str, link_text: str, link_url: str, column_names_ordered: list) -> str:
    """Step 4.2.1.2 — AI-based link-to-column assigner.
    Returns one of column_names_ordered (including 'Unassigned').
    """
    cols_str = ", ".join(column_names_ordered)
    prompt = (
        f"Given this response text and this link [{link_text}]({link_url}), "
        f"which business does this link belong to? "
        f"Choose exactly one from: {cols_str}. "
        f"Reply with only that name, or 'Unassigned' if it doesn't belong to any listed business.\n\n"
        f"Response text:\n{response_text}"
    )
    resp = ai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    result = resp.choices[0].message.content.strip()
    if result not in column_names_ordered:
        result = "Unassigned"
    return result


def rule_assign(link_text: str, link_url: str, column_names_ordered: list) -> str | None:
    """Step 4.2.1.1 — Rule-based link-to-column assigner.
    Returns column name if link text or URL domain clearly matches one business; else None.
    """
    from urllib.parse import urlparse
    try:
        domain = urlparse(link_url).netloc.lower().replace("www.", "")
    except Exception:
        domain = ""

    candidates = []
    for col in column_names_ordered:
        if col == "Unassigned":
            continue
        col_norm = normalize_name(col)
        col_slug = re.sub(r"[^a-z0-9]+", "", col_norm)  # stripped for domain match
        link_text_norm = normalize_name(link_text)
        # Match if column name is contained in link text, or col slug in domain
        if col_norm in link_text_norm or col_slug in domain.replace(".", ""):
            candidates.append(col)

    if len(candidates) == 1:
        return candidates[0]
    return None


def extract_links(s: str) -> list:
    """Step 4.1.1 — Extract all [text](url) markdown links from string.
    Returns list of (text, url) tuples.
    """
    return re.findall(r'\[([^\]]*)\]\(([^)]*)\)', s)


def normalize_name(name: str) -> str:
    """Lowercase, strip, collapse whitespace — for same-brand grouping."""
    return re.sub(r"\s+", " ", name.lower().strip())


def group_by_brand(names: list) -> list:
    """Step 2.3.1.1 — Group name variants that refer to the same brand.
    Two names are in the same group if one contains the other (normalized).
    Returns list of groups (each group = list of variant strings).
    """
    groups = []
    for name in names:
        norm = normalize_name(name)
        placed = False
        for group in groups:
            for existing in group:
                en = normalize_name(existing)
                if norm in en or en in norm:
                    group.append(name)
                    placed = True
                    break
            if placed:
                break
        if not placed:
            groups.append([name])
    return groups


def pick_canonical(group: list) -> str:
    """Step 2.3.1.2 — Pick canonical name per group.
    Use the longest name that contains all others; else first occurrence.
    """
    # Sort by length descending; pick first that contains all others (normalized)
    sorted_group = sorted(group, key=len, reverse=True)
    for candidate in sorted_group:
        cn = normalize_name(candidate)
        if all(normalize_name(other) in cn for other in group):
            return candidate
    return group[0]  # fallback: first occurrence


def main():
    # Step 0 — API key check (DONE — do not modify)
    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY not set. See full_stack/.env.example.")
        sys.exit(1)

    # Step 1.1.1 — Get raw argument (DONE — do not modify)
    arg = sys.argv[1] if len(sys.argv) >= 2 else input("Business folder path or slug: ").strip()
    if not arg:
        print("No slug or path provided.")
        sys.exit(1)

    # Step 1.1.2.1 — Resolve arg to client_folder (DONE — do not modify)
    from full_stack.collect import resolve_client_folder
    client_folder, _ = resolve_client_folder(arg)

    # Step 1.1.2.2 — Load config.json (DONE — do not modify)
    config_path = client_folder / "config.json"
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except Exception:
            config = {}
    else:
        config = {}

    # Step 1.1.2.3 — Set slug from config or folder name (DONE — do not modify)
    from full_stack.collect import normalize_slug
    slug = config.get("slug", client_folder.name) if config else normalize_slug(client_folder.name)

    # Step 1.2.1 — Glob for aiso CSVs (DONE — do not modify)
    candidate_paths = list(client_folder.glob(f"{slug}_aisodata*.csv"))

    # Step 1.2.2 — Parse N; choose max N or exit (DONE — do not modify)
    if not candidate_paths:
        print(f"No aiso data file found in {client_folder} for slug '{slug}'.")
        sys.exit(1)
    best = None
    best_n = -1
    for p in candidate_paths:
        m = re.search(r"_aisodata(\d+)$", p.stem)
        if m:
            n = int(m.group(1))
            if n > best_n:
                best_n = n
                best = p
    if best is None:
        print(f"No aiso data file found in {client_folder} for slug '{slug}'.")
        sys.exit(1)
    path_to_csv = best

    # Step 1.3.1 — Read CSV into rows (DONE — do not modify)
    with open(path_to_csv, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames) if reader.fieldnames else []
        rows = list(reader)

    # Step 1.3.2 — Set header_list; validate required columns (DONE — do not modify)
    header_list = fieldnames
    for col in ("question", "response", "error"):
        if col not in header_list:
            print(f"CSV missing required columns (question, response, error): {path_to_csv}")
            sys.exit(1)

    # Step 1.4 — Already-analyzed check (DONE — do not modify)
    if "Unassigned" in header_list:
        print(f"Analysis is already completed for the aiso data in {slug}.")
        sys.exit(0)

    # Step 2.1.1 — config already loaded in 1.1.2.2; reuse here (DONE — do not modify)
    # config is already a dict (possibly empty) from above

    # Step 2.1.2 — Derive focal_name (DONE — do not modify)
    focal_name = (
        config.get("name") or
        config.get("business_name") or
        (humanize(config["slug"]) if config.get("slug") else None) or
        humanize(client_folder.name)
    )

    # Step 2.2.1 — Collect non-empty response strings (DONE — do not modify)
    response_texts = [row["response"].strip() for row in rows if row["response"].strip()]

    # Step 2.2.2.1 — Early exit if no responses (DONE — do not modify)
    if not response_texts:
        raw_business_names_list = []
    else:
        # Step 2.2.2.2 — Build batches (DONE — do not modify)
        BATCH_SIZE = 20
        batches = [response_texts[i:i + BATCH_SIZE] for i in range(0, len(response_texts), BATCH_SIZE)]

        # Step 2.2.2.3 — Call AI per batch; collect business names (DONE — do not modify)
        import openai
        client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        raw_business_names_list = []
        for batch in batches:
            batch_text = "\n---\n".join(batch)
            prompt = (
                f"From the following text(s), list every business or company name mentioned. "
                f"Return only the names, one per line. "
                f"Do not include the focal business name '{focal_name}' in the list.\n\n"
                f"{batch_text}"
            )
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
            )
            names = [
                n.strip() for n in response.choices[0].message.content.splitlines()
                if n.strip()
            ]
            raw_business_names_list.extend(names)
            time.sleep(0.2)

    # Step 2.3.1.1 — Group raw names by brand (DONE — do not modify)
    groups = group_by_brand(raw_business_names_list)

    # Step 2.3.1.2 — Pick canonical name per group (DONE — do not modify)
    unique_business_names = [pick_canonical(g) for g in groups]

    # Step 2.3.2 — Remove focal from competitor list (DONE — do not modify)
    from full_stack.collect import normalize_slug
    def _match_focal(name):
        return (
            name == focal_name or
            name.lower() == focal_name.lower() or
            normalize_slug(name) == normalize_slug(focal_name)
        )
    competitor_names_only = [n for n in unique_business_names if not _match_focal(n)]

    # Step 2.3.3 — Build column_names_ordered (DONE — do not modify)
    column_names_ordered = [focal_name] + competitor_names_only + ["Unassigned"]

    # Step 3.1 — Define new_header (DONE — do not modify)
    new_header = header_list + column_names_ordered

    # Step 4.1.2 — Apply link parser to every row (DONE — do not modify)
    per_row_list_of_links = [extract_links(row["response"]) for row in rows]

    # Step 4.2.1.3 — Loop; assign each link via rule or AI (DONE — do not modify)
    import openai as _openai
    _ai_client = _openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    assignments_per_link = []  # list of [(link_text, link_url, col_name), ...] per row
    total_links = sum(len(l) for l in per_row_list_of_links)
    done = 0
    for i, links in enumerate(per_row_list_of_links):
        row_assignments = []
        for link_text, link_url in links:
            col = rule_assign(link_text, link_url, column_names_ordered)
            if col is None:
                col = ai_assign(_ai_client, rows[i]["response"], link_text, link_url, column_names_ordered)
                time.sleep(0.1)
            row_assignments.append((link_text, link_url, col))
            done += 1
            # loading bar (same style as aoi_benchmark_scoreing_0.py)
            loading_bar = ""
            filled = min(20, round(done / total_links * 20)) if total_links else 0
            for _ in range(filled):
                loading_bar += "█"
            for _ in range(20 - filled):
                loading_bar += "_"
            try:
                print("\r" + loading_bar, end="", flush=True)
            except UnicodeEncodeError:
                print("\r" + loading_bar.replace("█", "#"), end="", flush=True)
        assignments_per_link.append(row_assignments)
    print()

    # Step 4.2.2 — per_row_assignments aligned with rows (DONE — do not modify)
    per_row_assignments = assignments_per_link  # index i → list of (text, url, col) for rows[i]

    # Step 4.3.1 — Ensure each row has all new_header keys (DONE — do not modify)
    for row in rows:
        for key in new_header:
            if key not in row:
                row[key] = ""

    # Step 4.3.2 — Fill new column cells with assigned links, newline-separated (DONE — do not modify)
    for i, row in enumerate(rows):
        col_to_links: dict = {col: [] for col in column_names_ordered}
        for link_text, link_url, col in per_row_assignments[i]:
            col_to_links[col].append(f"[{link_text}]({link_url})")
        for col in column_names_ordered:
            row[col] = "\n".join(col_to_links[col])

    # Step 5.1.1.1 — Open path_to_csv and create DictWriter (DONE — do not modify)
    with open(path_to_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=new_header, quoting=csv.QUOTE_NONNUMERIC)

        # Step 5.1.1.2 — Write header and rows; close file (DONE — do not modify)
        writer.writeheader()
        writer.writerows(rows)

    # Step 5.1.2 — Re-read CSV and verify structure (DONE — do not modify)
    with open(path_to_csv, newline="", encoding="utf-8") as f:
        verify_reader = csv.DictReader(f)
        verify_fields = list(verify_reader.fieldnames or [])
        verify_rows = list(verify_reader)
    assert verify_fields == new_header, f"Header mismatch after write: {verify_fields}"
    assert len(verify_rows) == len(rows), f"Row count mismatch after write: {len(verify_rows)} vs {len(rows)}"

    print(f"Done. Written: {path_to_csv}")
    print(f"Columns added: {column_names_ordered}")


if __name__ == "__main__":
    main()
