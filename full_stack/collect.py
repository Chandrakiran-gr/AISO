"""
collect — Multi-Provider AISO Data Collector (v2: Group-Aware)

Reads the ranked query_template_bank.csv from setup2, lets the operator pick
how many top-ranked questions to collect from each group (G1–G7), and runs
them across all configured AI providers in parallel.

Output files (timestamped — never overwrites):
    {slug}_collect_questions_{YYYYMMDD_HHMMSS}.csv   — which questions were selected
    {slug}_aisodata_{YYYYMMDD_HHMMSS}.csv            — AI responses

CSV schema for aisodata:
    question | group | group_rank
             | response_openai | response_claude | response_perplexity | response_gemini
             | error_openai    | error_claude    | error_perplexity    | error_gemini

Columns are only created for providers whose API key is set in .env.

Usage:
    python full_stack/collect.py <slug>                     # interactive group picker
    python full_stack/collect.py <slug> --pick-all 15       # 15 from each group (non-interactive)
    python full_stack/collect.py <slug> --providers openai,claude
    python full_stack/collect.py <slug> --groups G1,G2 --pick-all 14 --yes
    python full_stack/collect.py <slug> --limit 20          # legacy flat limit (non-group mode)
"""
import sys
import re
import csv
import os
import json
import argparse
import threading
import itertools
import time
from datetime import datetime
from collections import defaultdict, OrderedDict
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Optional

# Ensure repo root is on sys.path
_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from dotenv import load_dotenv
load_dotenv(_repo_root / ".env")

# Total worker threads shared across all providers
MAX_WORKERS = 20

# Default max questions per collect run (override with --limit N, or --limit 0 for all)
DEFAULT_LIMIT = 100

# Default questions per group when user presses Enter at the interactive prompt
# 7 groups × ~14/group ≈ 100 total
DEFAULT_PER_GROUP = 14

# Provider pacing is opt-in for projects with tight provider rate limits.
DEFAULT_PROVIDER_MIN_INTERVAL_SEC = {
    "gemini": 0.0,
}


def _env_float(name: str, default: float) -> float:
    value = os.environ.get(name, "").strip()
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        print(f"{name} must be a number; using {default}.")
        return default


# ─── Spinner ──────────────────────────────────────────────────────────────────

class _Spinner:
    """Animated terminal spinner for blocking operations."""
    FRAMES = "|/-\\"

    def __init__(self, message):
        self.message = message
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        for frame in itertools.cycle(self.FRAMES):
            if self._stop.is_set():
                break
            try:
                print(f"\r{self.message} {frame}", end="", flush=True)
            except UnicodeEncodeError:
                print(f"\r{self.message} ?", end="", flush=True)
            time.sleep(0.1)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *args):
        self._stop.set()
        self._thread.join()
        print(f"\r{self.message} done.   ")


# ─── Client folder resolution ─────────────────────────────────────────────────

def normalize_slug(raw: str) -> str:
    """Convert any string to a safe folder slug (lowercase, underscores)."""
    slug = raw.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    return slug.strip("_")


def _resolve_client_folder(arg: str):
    """
    Resolve arg (path or slug) to (client_folder_path, slug). Exits on failure.

    Search order:
      1. Exact path if arg looks like a directory path
      2. clients/<slug>   ← new canonical location
      3. <repo_root>/<slug>  ← backward compat for existing folders
    """
    p = Path(arg)
    if p.exists() and p.is_dir():
        client_folder = p.resolve()
    else:
        slug = normalize_slug(arg)
        # New canonical location
        client_folder = _repo_root / "clients" / slug
        if not client_folder.exists():
            # Backward compat: check repo root (pre-reorganization folders)
            client_folder = _repo_root / slug
            if not client_folder.exists():
                print("Business folder not found. Tried:")
                print(f"  {_repo_root / 'clients' / slug}")
                print(f"  {_repo_root / slug}")
                sys.exit(1)

    # Derive slug: prefer config.json, fall back to folder name
    config_path = client_folder / "config.json"
    if config_path.exists():
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
        slug = cfg.get("slug", client_folder.name)
    else:
        slug = normalize_slug(client_folder.name)

    return client_folder, slug


# Public alias so analysis scripts can import it from full_stack.collect
resolve_client_folder = _resolve_client_folder


# ─── Timestamp helper ─────────────────────────────────────────────────────────

def _timestamp() -> str:
    """Return current local time as YYYYMMDD_HHMMSS for filenames."""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _split_csv_arg(value: Optional[str]) -> List[str]:
    """Parse comma-separated CLI/env values while preserving caller ordering."""
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


# ─── Group-aware question picker ──────────────────────────────────────────────

def _load_grouped_bank(bank_path: Path) -> OrderedDict:
    """
    Load query_template_bank.csv and return questions grouped by group ID.
    Each group is sorted by group_rank (1 = best, ascending).
    Returns OrderedDict: group_id -> list of row dicts, sorted by rank.
    """
    rows: List[Dict] = []
    with open(bank_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(dict(row))

    # Group by 'group' column, preserving order of first appearance
    groups: OrderedDict = OrderedDict()
    for row in rows:
        gid = row.get("group", "")
        if gid not in groups:
            groups[gid] = []
        groups[gid].append(row)

    # Sort each group by group_rank (ascending — rank 1 = best)
    for gid in groups:
        groups[gid].sort(key=lambda r: int(r.get("group_rank", 9999)))

    return groups


def _interactive_group_picker(
    grouped: OrderedDict,
    pick_all: Optional[int] = None,
    select_all: bool = False,
) -> List[Dict]:
    """
    Show available groups and let the operator pick how many from each.
    Returns the selected question rows (sorted by group, then rank).

    If pick_all is set, skip interactive prompts and take that many from each.
    """
    # Display the group summary table
    print("\n  ┌─ Available Question Groups ────────────────────────────────────────────┐")
    print("  │  Group  │ Label                                          │  Available  │")
    print("  ├─────────┼────────────────────────────────────────────────┼─────────────┤")
    for gid, rows in grouped.items():
        label = rows[0].get("group_label", gid) if rows else gid
        # Truncate long labels for display
        label_display = label[:46] + ".." if len(label) > 48 else label
        print(f"  │  {gid:<5}  │ {label_display:<46} │  {len(rows):>5}      │")
    total_available = sum(len(rows) for rows in grouped.values())
    print("  ├─────────┼────────────────────────────────────────────────┼─────────────┤")
    print(f"  │  Total  │                                                │  {total_available:>5}      │")
    print("  └─────────┴────────────────────────────────────────────────┴─────────────┘")

    # Collect picks per group
    picks: Dict[str, int] = {}

    if select_all:
        for gid, rows in grouped.items():
            picks[gid] = len(rows)
        print("\n  Curated bank mode: taking every ranked question in the selected groups.")
    elif pick_all is not None:
        # Non-interactive mode
        for gid, rows in grouped.items():
            picks[gid] = min(pick_all, len(rows))
        print(f"\n  --pick-all {pick_all}: taking top {pick_all} from each group.")
    else:
        # Interactive mode — ask for each group
        print("\n  How many top-ranked questions from each group?")
        print(f"  (Press Enter for default={DEFAULT_PER_GROUP}, type 0 to skip a group)\n")

        for gid, rows in grouped.items():
            label = rows[0].get("group_label", gid) if rows else gid
            available = len(rows)

            while True:
                try:
                    raw = input(f"  {gid} - {label} ({available} available) [{DEFAULT_PER_GROUP}]: ").strip()
                    if raw == "":
                        n = DEFAULT_PER_GROUP
                    else:
                        n = int(raw)

                    if n < 0:
                        print("    Please enter 0 or a positive number.")
                        continue
                    if n > available:
                        print(f"    Only {available} available. Capping at {available}.")
                        n = available

                    picks[gid] = n
                    break
                except ValueError:
                    print("    Invalid number. Try again.")
                except (KeyboardInterrupt, EOFError):
                    print("\n\n  Cancelled.")
                    sys.exit(0)

    # Select top-ranked questions from each group
    selected: List[Dict] = []
    for gid, rows in grouped.items():
        n = picks.get(gid, 0)
        if n > 0:
            # rows are already sorted by group_rank (ascending), so [:n] = top N
            selected.extend(rows[:n])

    return selected


def _print_collection_plan(
    selected: List[Dict],
    grouped: OrderedDict,
    provider_names: List[str],
) -> None:
    """Print a summary of what will be collected before proceeding."""
    # Count per group
    group_counts: OrderedDict = OrderedDict()
    for gid in grouped:
        group_counts[gid] = 0
    for row in selected:
        gid = row.get("group", "?")
        group_counts[gid] = group_counts.get(gid, 0) + 1

    total_q = len(selected)
    total_calls = total_q * len(provider_names)

    print("\n  ┌─ Collection Plan ─────────────────────────────────────────────────────┐")
    # Print groups in rows of 3
    items = list(group_counts.items())
    for i in range(0, len(items), 3):
        chunk = items[i:i+3]
        cells = "  │  ".join(f"{gid}: {cnt:>3} questions" for gid, cnt in chunk)
        line = f"  │  {cells}"
        # Pad to fixed width
        line = f"{line:<75}│"
        print(line)
    print(f"  │{'─' * 75}│")
    providers_str = ", ".join(provider_names)
    summary = f"  │  Total: {total_q} questions × {len(provider_names)} providers ({providers_str}) = {total_calls} API calls"
    print(f"{summary:<76}│")
    print(f"  └{'─' * 75}┘")


def _save_questions_log(
    selected: List[Dict],
    client_folder: Path,
    slug: str,
    ts: str,
) -> Path:
    """
    Save the selected questions to a timestamped CSV log.
    This records exactly which questions were collected in this run.
    """
    log_path = client_folder / f"{slug}_collect_questions_{ts}.csv"
    fieldnames = ["question", "group", "group_label", "group_rank", "intent_score"]

    with open(log_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in selected:
            writer.writerow({k: row.get(k, "") for k in fieldnames})

    print(f"  Questions log: {log_path.name}")
    return log_path


# ─── Follow-up config loader ──────────────────────────────────────────────────

def _load_followup(client_folder: Path, cli_followup: Optional[str]) -> Optional[str]:
    """
    Resolve the follow-up question to use (if any).

    Priority:
      1. --followup CLI flag (highest)
      2. collect_config.json in the client folder
      3. None (no follow-up — single-turn mode)
    """
    # CLI override takes priority
    if cli_followup is not None:
        followup = cli_followup.strip()
        if followup:
            return followup
        return None  # --followup "" disables even if config exists

    # Check client config file
    config_path = client_folder / "collect_config.json"
    if config_path.exists():
        try:
            cfg = json.loads(config_path.read_text(encoding="utf-8"))
            followup = cfg.get("followup", "").strip()
            if followup:
                return followup
        except (json.JSONDecodeError, KeyError) as e:
            print(f"  ⚠ Warning: could not read {config_path.name}: {e}")

    return None


# ─── Entry point ──────────────────────────────────────────────────────────────

def main():
    from webish.providers import (
        get_active_providers,
        list_provider_status,
        PROVIDER_CONCURRENCY,
    )
    from webish.providers.base import ProviderResult
    from full_stack.source_intelligence import provider_result_to_evidence_records

    # ── Step 1: Parse CLI args ─────────────────────────────────────────────────
    parser = argparse.ArgumentParser(
        description="Collect AI responses for a client across multiple providers."
    )
    parser.add_argument("slug", nargs="?", help="Business folder path or slug")
    parser.add_argument(
        "--limit", type=int, default=DEFAULT_LIMIT,
        help=f"Max questions to run (default: {DEFAULT_LIMIT}). Pass 0 for no limit. "
             "Note: in v2 group mode, use --pick-all instead."
    )
    parser.add_argument(
        "--providers", type=str, default=None,
        help="Comma-separated subset of providers to use, e.g. 'openai,claude'"
    )
    parser.add_argument(
        "--groups", type=str, default=None,
        help="Comma-separated setup2 v2 groups to collect, e.g. 'G1,G2,G3'. "
             "Defaults to AISO_GROUPS when set."
    )
    parser.add_argument(
        "--pick-all", type=int, default=None, dest="pick_all",
        metavar="N",
        help="Non-interactive: take top N questions from every group (skips prompts). "
             "Only applies to setup2 v2 banks with group columns."
    )
    parser.add_argument(
        "--yes", action="store_true",
        help="Skip confirmation prompts. Automatically enabled when AISO_SCAN_ID is set."
    )
    parser.add_argument(
        "--followup", type=str, default=None,
        metavar='"QUESTION"',
        help='Follow-up question to ask after each initial response (multi-turn). '
             'Overrides collect_config.json. Pass empty string to disable: --followup ""'
    )
    args = parser.parse_args()

    if args.limit is not None and args.limit < 0:
        print("--limit must be 0 (no limit) or a positive integer.")
        sys.exit(1)
    if args.pick_all is not None and args.pick_all <= 0:
        print("--pick-all must be a positive integer.")
        sys.exit(1)

    # --limit 0 means no limit
    effective_limit = None if args.limit == 0 else args.limit
    backend_scan_mode = bool(os.environ.get("AISO_SCAN_ID", "").strip())
    auto_confirm = args.yes or backend_scan_mode

    if backend_scan_mode and args.pick_all is None and os.environ.get("AISO_PICK_ALL", "").strip():
        per_group = os.environ.get("AISO_PICK_ALL", "").strip()
        try:
            args.pick_all = int(per_group)
        except ValueError:
            print("AISO_PICK_ALL must be a positive integer.")
            sys.exit(1)
        if args.pick_all <= 0:
            print("AISO_PICK_ALL must be a positive integer.")
            sys.exit(1)

    # ── Step 2: Discover active providers ─────────────────────────────────────
    active_providers = get_active_providers()

    # Apply --providers filter, falling back to backend orchestration env.
    provider_filter = args.providers or os.environ.get("AISO_PROVIDERS")
    if provider_filter:
        requested = [p.lower() for p in _split_csv_arg(provider_filter)]
        unknown = [p for p in requested if p not in active_providers]
        if unknown:
            print(f"Unknown or unconfigured providers: {unknown}")
            print("Available (keys set):", list(active_providers.keys()))
            sys.exit(1)
        active_providers = {k: v for k, v in active_providers.items() if k in requested}

    if not active_providers:
        print("\nNo provider API keys are configured. Set at least one in your .env:\n")
        for name, is_active, env_var in list_provider_status():
            status = "✓ set" if is_active else "✗ missing"
            print(f"  {status}  {env_var}")
        sys.exit(1)

    print("Active providers:", ", ".join(active_providers.keys()))

    # ── Step 3: Resolve client folder ─────────────────────────────────────────
    if args.slug:
        arg = args.slug.strip()
    else:
        arg = input("Business folder path or slug: ").strip()
    if not arg:
        print("No business folder or slug provided.")
        sys.exit(1)

    with _Spinner("Resolving business folder..."):
        client_folder, slug = _resolve_client_folder(arg)
    print(f"  -> {client_folder}")

    # ── Step 3.5: Follow-up question (DISABLED — single-turn only for now) ──────
    # To re-enable multi-turn: uncomment the block below and remove the two lines after.
    # followup_question = _load_followup(client_folder, args.followup)
    # if followup_question:
    #     print(f"\n  Follow-up enabled: \"{followup_question}\"")
    #     print("  (Each question will be a 2-turn conversation)")
    #     multiturn_providers = get_active_providers_multiturn()
    #     if args.providers:
    #         requested = [p.strip().lower() for p in args.providers.split(",") if p.strip()]
    #         multiturn_providers = {k: v for k, v in multiturn_providers.items() if k in requested}
    # else:
    #     multiturn_providers = None
    followup_question = None   # single-turn mode
    multiturn_providers = None  # single-turn mode

    # ── Step 4: Validate bank CSVs ────────────────────────────────────────────
    t_path = client_folder / "query_template_bank.csv"
    v_path = client_folder / "value_bank.csv"
    if not t_path.exists():
        print(f"Missing query_template_bank.csv in {client_folder}")
        sys.exit(1)
    if not v_path.exists():
        print(f"Missing value_bank.csv in {client_folder}")
        sys.exit(1)

    # ── Step 5: Load banks and build question list ─────────────────────────────
    from full_stack.lib import read_csv_to_rows, build_queries_from_matrix

    print("Reading query template bank...", end=" ", flush=True)
    template_rows = read_csv_to_rows(t_path)
    if not template_rows:
        print(f"\nquery_template_bank.csv is empty: {t_path}")
        sys.exit(1)
    print(f"{len(template_rows)} rows loaded.")

    # ── Format detection ───────────────────────────────────────────────────────
    # setup2 v2 (current): 'question' + 'group' + 'group_rank' columns
    # setup2 v1 (old):     'template' column — [bracket] placeholders, expand here.
    # setup1.x (legacy):   matrix columns like 'core_service' — {curly} expansion.

    is_setup2_v2 = ("question" in template_rows[0] and "group" in template_rows[0]
                     and "group_rank" in template_rows[0])
    is_setup2_v1 = not is_setup2_v2 and "template" in template_rows[0]

    # Timestamp for all output files in this run
    ts = _timestamp()

    if is_setup2_v2:
        # ── v2 GROUP-AWARE PATH ──────────────────────────────────────────────
        print("Bank format: setup2 v2 (ranked groups — group-aware collection).\n")

        grouped = _load_grouped_bank(t_path)
        group_filter = _split_csv_arg(args.groups or os.environ.get("AISO_GROUPS"))
        if group_filter:
            unknown_groups = [gid for gid in group_filter if gid not in grouped]
            if unknown_groups:
                print(f"Unknown groups: {unknown_groups}")
                print("Available groups:", list(grouped.keys()))
                sys.exit(1)
            grouped = OrderedDict((gid, grouped[gid]) for gid in group_filter)

        # Backend scans use the curated ranked bank by default. AISO_PICK_ALL remains
        # an explicit admin cap when operators need to reduce provider calls.
        selected_rows = _interactive_group_picker(
            grouped,
            pick_all=args.pick_all,
            select_all=backend_scan_mode and args.pick_all is None,
        )

        if not selected_rows:
            print("\n  No questions selected. Exiting.")
            sys.exit(0)

        # Print collection plan and confirm
        provider_names = list(active_providers.keys())
        _print_collection_plan(selected_rows, grouped, provider_names)

        # Confirm before proceeding
        if not auto_confirm:
            try:
                confirm = input("\n  Proceed? [Y/n]: ").strip().lower()
            except (KeyboardInterrupt, EOFError):
                print("\n\n  Cancelled.")
                sys.exit(0)
            if confirm and confirm not in ("y", "yes", ""):
                print("  Cancelled.")
                sys.exit(0)

        # Save questions log
        _save_questions_log(selected_rows, client_folder, slug, ts)

        # Extract question strings (preserving rank order per group)
        questions = [row["question"].strip() for row in selected_rows]

        # Also keep selected_rows metadata for enriching the output CSV
        question_metadata = {
            row["question"].strip(): row for row in selected_rows
        }

    elif is_setup2_v1:
        # v1: expand [placeholder] templates with value_bank rows
        print("Bank format: setup2 v1 (ranked templates — [bracket] placeholders).")

        print("Reading value bank...", end=" ", flush=True)
        value_rows = read_csv_to_rows(v_path)
        if not value_rows:
            print(f"\nvalue_bank.csv is empty: {v_path}")
            sys.exit(1)
        print(f"{len(value_rows)} value rows loaded.")

        def _expand_ranked(template_rows: list, value_rows: list) -> list:
            """
            Expand each template against each value row by substituting
            [token] with the row's value for that token.
            Skips combinations that still have unfilled [tokens] after substitution.
            """
            import re as _re
            TOKEN_RE = _re.compile(r"\[([a-z_]+)\]")
            questions = []
            for trow in template_rows:
                tmpl = trow.get("template", "").strip()
                if not tmpl:
                    continue
                for vrow in value_rows:
                    q = tmpl
                    for token, val in vrow.items():
                        if val:
                            q = q.replace(f"[{token}]", val)
                    if not TOKEN_RE.search(q):
                        questions.append(q)
            return questions

        with _Spinner(f"Expanding {len(template_rows)} ranked templates × {len(value_rows)} value rows..."):
            questions = _expand_ranked(template_rows, value_rows)

        if not questions:
            print("No questions generated — check that value_bank.csv covers template placeholders.")
            sys.exit(1)

        # Deduplicate while preserving rank order
        seen: set = set()
        unique_questions = []
        for q in questions:
            if q not in seen:
                seen.add(q)
                unique_questions.append(q)
        questions = unique_questions
        question_metadata = {}  # No group metadata in v1

        if effective_limit is not None:
            questions = questions[:effective_limit]

        provider_names = list(active_providers.keys())

    else:
        # Legacy path: {curly-brace} cross-product
        print("Bank format: legacy (template×value matrix — {curly-brace} placeholders).")

        print("Reading value bank...", end=" ", flush=True)
        value_rows = read_csv_to_rows(v_path)
        if not value_rows:
            print(f"\nvalue_bank.csv is empty: {v_path}")
            sys.exit(1)
        print(f"{len(value_rows)} value rows loaded.")

        with _Spinner(f"Building matrix ({len(template_rows)} templates × {len(value_rows)} values)..."):
            questions = build_queries_from_matrix(template_rows, value_rows)

        if not questions:
            print("Failed to build question list — check bank CSV structure.")
            sys.exit(1)
        if any("{" in q for q in questions):
            print("Unfilled placeholders detected — check bank CSV structure.")
            sys.exit(1)

        question_metadata = {}  # No group metadata in legacy

        if effective_limit is not None:
            questions = questions[:effective_limit]

        provider_names = list(active_providers.keys())

    total_questions = len(questions)
    total_tasks = total_questions * len(provider_names)
    print(
        f"\n  {total_questions} questions × {len(provider_names)} providers "
        f"= {total_tasks} API calls (single-turn)."
    )

    # ── Step 6: Determine output file path (timestamped) ──────────────────────
    out_path = client_folder / f"{slug}_aisodata_{ts}.csv"
    evidence_path = client_folder / f"{slug}_source_evidence_{ts}.jsonl"
    print(f"  Output: {out_path.name}")
    print(f"  Source evidence: {evidence_path.name}")

    # ── Step 7: Build CSV fieldnames ──────────────────────────────────────────
    # Include group + group_rank metadata if available (v2 mode)
    base_fields = ["question"]
    if question_metadata:
        base_fields.extend(["group", "group_label", "group_rank"])

    response_fields = (
        [f"response_{p}" for p in provider_names]
        + [f"error_{p}"    for p in provider_names]
    )

    # Follow-up columns — DISABLED (single-turn mode)
    # To re-enable: uncomment the block below
    # followup_fields = []
    # if followup_question:
    #     followup_fields = (
    #         ["followup_question"]
    #         + [f"followup_response_{p}" for p in provider_names]
    #         + [f"followup_error_{p}"    for p in provider_names]
    #     )
    followup_fields = []  # single-turn mode

    fieldnames = base_fields + response_fields + followup_fields

    # ── Step 8: Concurrency setup ──────────────────────────────────────────────
    # Per-provider semaphores prevent any single provider from being over-called.
    semaphores = {
        name: threading.Semaphore(PROVIDER_CONCURRENCY.get(name, 3))
        for name in provider_names
    }
    provider_rate_locks = {name: threading.Lock() for name in provider_names}
    provider_last_call_at: dict[str, float] = defaultdict(float)
    provider_min_interval = {
        name: _env_float(
            f"AISO_{name.upper()}_MIN_INTERVAL_SEC",
            DEFAULT_PROVIDER_MIN_INTERVAL_SEC.get(name, 0.0),
        )
        for name in provider_names
    }

    # ── Step 9: Mutable state (all accessed only in main thread via as_completed)
    pending: dict[int, dict[str, ProviderResult]] = defaultdict(dict)
    pending_followup: dict[int, dict[str, ProviderResult]] = defaultdict(dict)
    provider_done: dict[str, int] = defaultdict(int)
    rows_written = 0
    tasks_succeeded = 0
    tasks_failed = 0
    consecutive_empty = 0
    recent_empty_errors: list[str] = []
    MAX_CONSECUTIVE_EMPTY = 5 * len(provider_names)

    question_timeout_sec = float(
        os.environ.get("COLLECT_QUESTION_TIMEOUT_SEC", "120")
    )

    # ── Step 10: Worker function (closure — captures active_providers, semaphores)
    def _task_worker(q_idx: int, provider_name: str) -> tuple:
        """
        Call one provider for one question (single-turn mode).

        Returns (q_idx, provider_name, ProviderResult, None)

        Multi-turn follow-up is DISABLED. To re-enable, restore the
        multi-turn branch from git history and uncomment follow-up logic.
        """
        question = questions[q_idx]
        with semaphores[provider_name]:
            min_interval = provider_min_interval.get(provider_name, 0.0)
            if min_interval > 0:
                with provider_rate_locks[provider_name]:
                    elapsed = time.monotonic() - provider_last_call_at[provider_name]
                    wait_for = min_interval - elapsed
                    if wait_for > 0:
                        time.sleep(wait_for)
                    provider_last_call_at[provider_name] = time.monotonic()
            # Single-turn only
            try:
                result = active_providers[provider_name](question)
            except Exception as e:
                result = ProviderResult(error=str(e))
            return q_idx, provider_name, result, None

        # ── MULTI-TURN DISABLED ───────────────────────────────────────────────
        # To re-enable follow-up questions, replace the block above with:
        # if followup_question and multiturn_providers:
        #     try:
        #         r1, r2 = multiturn_providers[provider_name](question, followup_question)
        #     except Exception as e:
        #         r1 = ProviderResult(error=str(e))
        #         r2 = ProviderResult(error=str(e))
        #     return q_idx, provider_name, r1, r2
        # ─────────────────────────────────────────────────────────────────────

    # ── Step 11: Open output file and run ─────────────────────────────────────
    outfile = open(out_path, "w", newline="", encoding="utf-8")
    writer = csv.DictWriter(outfile, fieldnames=fieldnames, quoting=csv.QUOTE_NONNUMERIC)
    writer.writeheader()
    outfile.flush()
    evidence_file = open(evidence_path, "w", encoding="utf-8")

    def _write_source_evidence(q_idx: int, provider_name: str, result: ProviderResult) -> None:
        """Stream structured source evidence sidecar rows for one provider answer."""
        q_text = questions[q_idx]
        meta = question_metadata.get(q_text, {})
        records = provider_result_to_evidence_records(
            result=result,
            provider_name=provider_name,
            question=q_text,
            group=meta.get("group") or None,
            scan_id=os.environ.get("AISO_SCAN_ID", "").strip() or None,
            client_id=os.environ.get("AISO_CLIENT_ID", "").strip() or slug,
        )
        for record in records:
            evidence_file.write(json.dumps(record, ensure_ascii=True, sort_keys=True) + "\n")
        if records:
            evidence_file.flush()

    # Submit all (question_idx × provider) tasks as a flat pool
    executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)
    all_futures = {
        executor.submit(_task_worker, q_idx, provider_name): (q_idx, provider_name)
        for q_idx in range(total_questions)
        for provider_name in provider_names
    }
    print(f"\n  Submitted {total_tasks} tasks across {MAX_WORKERS} workers. Running...\n")

    def _write_row(q_idx: int) -> None:
        """Assemble and write a complete CSV row for q_idx."""
        row_data = pending[q_idx]
        q_text = questions[q_idx]
        row = {"question": q_text}

        # Add group metadata if available
        meta = question_metadata.get(q_text, {})
        if question_metadata:
            row["group"] = meta.get("group", "")
            row["group_label"] = meta.get("group_label", "")
            row["group_rank"] = meta.get("group_rank", "")

        # Round 1 responses
        for p in provider_names:
            r = row_data.get(p, ProviderResult(error="not_called"))
            row[f"response_{p}"] = r.response
            row[f"error_{p}"] = r.error

        # Round 2 follow-up — DISABLED (single-turn mode)
        # if followup_question:
        #     row["followup_question"] = followup_question
        #     fu_data = pending_followup.get(q_idx, {})
        #     for p in provider_names:
        #         r = fu_data.get(p, ProviderResult(error="not_called"))
        #         row[f"followup_response_{p}"] = r.response
        #         row[f"followup_error_{p}"] = r.error

        writer.writerow(row)
        outfile.flush()

    def _progress_line() -> str:
        """Build a compact progress string."""
        filled = round(rows_written / total_questions * 20) if total_questions else 0
        bar = "#" * filled + "_" * (20 - filled)
        provider_counts = " ".join(
            f"{name[:4]}={provider_done[name]}/{total_questions}"
            for name in provider_names
        )
        return f"\r[{bar}] {provider_counts} | ok={tasks_succeeded} fail={tasks_failed}   "

    def _compact_error(provider_name: str, error: str) -> str:
        """Keep provider errors useful in terminal/API failures without flooding output."""
        clean = " ".join(str(error or "").split())
        if not clean:
            return ""
        return f"{provider_name}: {clean[:360]}"

    try:
        for future in as_completed(all_futures, timeout=question_timeout_sec * total_tasks):
            # Unpack result (failures caught inside _task_worker — always returns tuple)
            try:
                q_idx, provider_name, result, followup_result = future.result()
            except Exception as e:
                q_idx, provider_name = all_futures[future]
                result = ProviderResult(error=str(e))
                followup_result = ProviderResult(error=str(e)) if followup_question else None

            # Aggregate round 1
            pending[q_idx][provider_name] = result
            provider_done[provider_name] += 1
            _write_source_evidence(q_idx, provider_name, result)

            # Aggregate round 2 (if multi-turn)
            if followup_result is not None:
                pending_followup[q_idx][provider_name] = followup_result

            # Stats (count both rounds)
            if result.response.strip():
                tasks_succeeded += 1
                consecutive_empty = 0
                recent_empty_errors.clear()
            else:
                tasks_failed += 1
                consecutive_empty += 1
                compact_error = _compact_error(provider_name, result.error)
                if compact_error:
                    recent_empty_errors.append(compact_error)
                    recent_empty_errors[:] = recent_empty_errors[-MAX_CONSECUTIVE_EMPTY:]

            if followup_result is not None:
                if followup_result.response.strip():
                    tasks_succeeded += 1
                else:
                    tasks_failed += 1

            if consecutive_empty >= MAX_CONSECUTIVE_EMPTY:
                last_error = f" Last provider error: {recent_empty_errors[-1]}" if recent_empty_errors else ""
                raise RuntimeError(
                    f"{consecutive_empty} consecutive empty responses — "
                    "likely an API configuration issue. Check your keys and quota."
                    f"{last_error}"
                )

            # Write row immediately once all providers have responded for this question
            if len(pending[q_idx]) == len(provider_names):
                _write_row(q_idx)
                del pending[q_idx]
                if q_idx in pending_followup:
                    del pending_followup[q_idx]
                rows_written += 1

            print(_progress_line(), end="", flush=True)

    except KeyboardInterrupt:
        print(f"\n\nInterrupted. {rows_written}/{total_questions} rows written to {out_path.name}")
        executor.shutdown(wait=False, cancel_futures=True)
        outfile.close()
        evidence_file.close()
        sys.exit(0)
    except Exception:
        executor.shutdown(wait=False, cancel_futures=True)
        outfile.close()
        evidence_file.close()
        raise
    else:
        executor.shutdown(wait=True)
        outfile.close()
        evidence_file.close()

    print("\n\nDone.")
    print(f"  Rows written : {rows_written} / {total_questions}")
    print(f"  API calls    : {tasks_succeeded} succeeded, {tasks_failed} failed")
    print(f"  Output       : {out_path}")
    print(f"  Evidence     : {evidence_path}")

    scan_id = os.environ.get("AISO_SCAN_ID", "").strip()
    scan_client_id = os.environ.get("AISO_CLIENT_ID", "").strip() or slug
    if scan_id:
        from full_stack.scan_metrics import persist_collect_csv_results

        persisted = persist_collect_csv_results(
            out_path,
            scan_id=scan_id,
            client_id=scan_client_id,
            client_folder=client_folder,
        )
        print(f"  ScanResult rows persisted : {len(persisted)}")


if __name__ == "__main__":
    main()
