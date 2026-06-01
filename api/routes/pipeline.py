"""
Pipeline router — triggers and monitors AISO pipeline runs.
Wraps setup2.py → collect.py → analysis1.py → analysis2.py
"""

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query, status
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field, field_validator
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
import uuid
import json
import os
import csv

from api.database import get_db, Action, Scan, Client, ClientContext, ScanArtifact, ScanCitation, ScanResult, SourceProfile, User
from api.auth import get_current_user_id
from api.adapters.scan_runs import (
    phase13_metrics_for_client,
    phase13_timeline_points_for_clients,
    scan_run_list_projections_for_client,
)
from api.entitlements import entitlements_for_user
from api.scan_workspace import MANUAL_GROUP, prepare_scan_workspace
from api.scan_capabilities import VALID_SCAN_GROUPS, competitor_names_for_scan, validate_scan_group_capabilities
from api.storage import (
    ArtifactStorageError,
    download_onedrive_artifact,
    materialize_artifact_file,
    resolve_local_artifact_path,
)
from full_stack.gap_report import GapReportInput, build_gap_report
from full_stack.scan_metrics import load_client_identity, read_collect_csv

router = APIRouter(tags=["pipeline"])

DEFAULT_PROVIDERS = ["openai", "claude", "perplexity", "gemini"]
DEFAULT_GROUPS = ["G1", "G2", "G4"]

GAP_GROUP_LABELS = {
    "G1": "Local discovery",
    "G2": "Branded direct",
    "G3": "Competitors and alternatives",
    "G4": "Transactional and price",
    "G5": "Trust, reviews and safety",
    "G6": "Concern, outcome and fit",
    "G7": "Method comparison and head-to-head",
    "all": "All questions",
}

GAP_GROUP_IMPACT = {
    "G1": 8.5,
    "G2": 6.0,
    "G3": 8.8,
    "G4": 9.4,
    "G5": 8.0,
    "G6": 9.2,
    "G7": 9.0,
}


def _is_manual_group(group: str | None) -> bool:
    return str(group or "").strip().upper() == MANUAL_GROUP


def _normalize_custom_question(value: str) -> str:
    return " ".join(str(value or "").split())


def _validate_custom_questions(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise ValueError("custom_questions must be a list of strings")

    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            raise ValueError("Custom questions must be strings")
        clean = _normalize_custom_question(item)
        if not clean:
            raise ValueError("Custom questions cannot be empty")
        key = clean.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(clean)
    return normalized


class BYOKKeys(BaseModel):
    """Per-request API keys supplied by the user (BYOK — Bring Your Own Key).
    Keys are received over HTTPS, used in memory for this scan, and immediately discarded.
    They are NEVER written to the database or logged.
    """
    openai:     Optional[str] = None
    claude:     Optional[str] = None
    perplexity: Optional[str] = None
    gemini:     Optional[str] = None


class ScanCreate(BaseModel):
    client_id: str
    providers: List[str] = Field(default_factory=lambda: DEFAULT_PROVIDERS.copy())
    groups:    List[str] = Field(default_factory=lambda: DEFAULT_GROUPS.copy())
    custom_questions: List[str] = Field(default_factory=list)
    byok_keys: Optional[BYOKKeys] = None  # BYOK: user's own API keys (never stored)

    @field_validator("custom_questions", mode="before")
    @classmethod
    def custom_questions_valid(cls, value: Any) -> list[str]:
        return _validate_custom_questions(value)

    @property
    def providers_valid(self) -> bool:
        valid = {"openai", "claude", "perplexity", "gemini"}
        return all(p in valid for p in self.providers)

    @property
    def groups_valid(self) -> bool:
        return all(g in VALID_SCAN_GROUPS for g in self.groups)


class ScanResponse(BaseModel):
    id:                str
    client_id:         str
    status:            str
    providers:         Optional[List[str]]
    groups:            Optional[List[str]]
    skipped_providers: Optional[List[str]] = None  # providers skipped due to missing key
    started_at:        Optional[datetime]
    completed_at:      Optional[datetime] = None
    created_at:        datetime
    error:             Optional[str] = None

    class Config:
        from_attributes = True


class ScanArtifactResponse(BaseModel):
    id: str
    artifact_type: str
    file_format: Optional[str]
    storage_backend: str
    storage_path: str
    original_filename: Optional[str]
    mime_type: Optional[str]
    size_bytes: Optional[int]
    sha256: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class ScanDetailResponse(ScanResponse):
    artifacts: List[ScanArtifactResponse] = Field(default_factory=list)


class CitationResponse(BaseModel):
    id: str
    provider: str
    group: Optional[str]
    question: Optional[str]
    answer_excerpt: Optional[str]
    citation_url: str
    citation_title: Optional[str]
    source_domain: Optional[str]
    source_rank: Optional[int]
    canonical_url: Optional[str] = None
    citation_origin: Optional[str] = None
    cited_text: Optional[str] = None
    web_search_used: Optional[bool] = None
    source_type: Optional[str] = None
    owner_type: Optional[str] = None
    action_role: Optional[str] = None
    actionability_score: Optional[float] = None
    influence_score: Optional[float] = None
    relevance_score: Optional[float] = None
    confidence_score: Optional[float] = None
    classification_reason: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class CustomQuestionProviderResult(BaseModel):
    mentioned: bool
    answer_excerpt: Optional[str] = None
    citations: List[dict[str, Any]] = Field(default_factory=list)


class CustomQuestionResult(BaseModel):
    question: str
    providers: Dict[str, CustomQuestionProviderResult] = Field(default_factory=dict)


class CustomQuestionsResponse(BaseModel):
    scan_id: str
    client_id: str
    data_status: str
    questions: List[CustomQuestionResult] = Field(default_factory=list)


class SourceProfileResponse(BaseModel):
    id: str
    canonical_url: str
    source_domain: Optional[str]
    source_title: Optional[str]
    owner_type: Optional[str]
    source_type: Optional[str]
    action_role: Optional[str]
    actionability_score: Optional[float]
    influence_score: Optional[float]
    relevance_score: Optional[float]
    client_mentioned: Optional[bool]
    competitors_mentioned: List[str] = Field(default_factory=list)
    topics: List[str] = Field(default_factory=list)
    fetch_status: Optional[str]
    classification_reason: Optional[str]
    citation_count: int = 0
    prompt_count: int = 0
    provider_count: int = 0
    example_questions: List[str] = Field(default_factory=list)
    top_urls: List[str] = Field(default_factory=list)


class ProviderMetric(BaseModel):
    id: str
    score: float
    mention_count: int
    total_questions: int
    avg_position: Optional[float]


def _can_download_artifacts(db: Session, user_id: str) -> bool:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return False
    return entitlements_for_user(user).can_download_artifacts


def _resolve_local_artifact_path(artifact: ScanArtifact) -> Path:
    if artifact.storage_backend != "local":
        raise HTTPException(status_code=404, detail="Artifact is not available locally")
    try:
        return resolve_local_artifact_path(artifact.storage_path)
    except ArtifactStorageError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


class GroupMetric(BaseModel):
    id: str
    label: str
    score: float
    mention_count: int
    total_questions: int


class CompetitorMetric(BaseModel):
    name: str
    score: float
    mention_count: int
    provider_scores: Dict[str, float] = Field(default_factory=dict)
    provider_mentions: Dict[str, int] = Field(default_factory=dict)
    is_you: bool = False


class MetricsResponse(BaseModel):
    client_id: str
    client_name: str
    scan_id: str
    status: str
    overall_score: float
    visibility_score: Optional[float] = None
    total_questions: int
    provider_metrics: List[ProviderMetric]
    group_metrics: List[GroupMetric]
    competitors: List[CompetitorMetric]


class TimelineMetrics(BaseModel):
    overall_score: float
    total_questions: int
    mention_count: int
    gap_count: int
    action_count: int
    completed_action_count: int
    action_completion_rate: float


class ScanMetricsTimelinePoint(BaseModel):
    client_id: str
    client_name: str
    scan_id: str
    status: str
    created_at: datetime
    completed_at: Optional[datetime] = None
    metrics: TimelineMetrics


GROUP_LABELS = {
    "G1": "Category & local discovery",
    "G2": "Direct brand",
    "G3": "Competitors & alternatives",
    "G4": "Transactional & bottom-funnel",
    "G5": "Trust, reviews & risk",
    "G6": "Fit: persona, occasion, constraint",
    "G7": "Head-to-head choice",
    "all": "All questions",
}


def _redact_known_secrets(text: str, secrets: Optional[dict]) -> str:
    """Avoid reflecting BYOK values if a provider ever echoes request config."""
    redacted = text
    for value in (secrets or {}).values():
        secret = str(value or "").strip()
        if len(secret) >= 8:
            redacted = redacted.replace(secret, "[redacted]")
    return redacted


def _extract_script_failure(script_name: str, return_code: int, output: str) -> str:
    """Turn subprocess output into a concise, user-facing scan failure."""
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    for line in reversed(lines):
        if "consecutive empty responses" in line:
            return line.removeprefix("RuntimeError:").strip()
        if line.startswith("RuntimeError:"):
            return line.removeprefix("RuntimeError:").strip()

    ignored_prefixes = (
        "File ",
        "Traceback ",
        "^",
        "from ",
        "See README",
        "https://",
        "All support for ",
    )
    for line in reversed(lines[-12:]):
        if line.startswith(ignored_prefixes):
            continue
        if "FutureWarning" in line:
            continue
        if len(line) <= 240:
            return f"{script_name} failed: {line}"

    return f"{script_name} failed with exit code {return_code}"


def _estimate_api_calls(
    query_bank_path,
    groups: List[str],
    providers: List[str],
    pick_all: Optional[int] = None,
) -> tuple[int, int, int]:
    """Estimate collect.py calls from the local query bank for terminal logs."""
    if not query_bank_path.exists():
        return 0, len(providers), 0

    group_counts: dict[str, int] = {}
    with query_bank_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            group = str(row.get("group") or "all")
            group_counts[group] = group_counts.get(group, 0) + 1

    selected_groups = list(dict.fromkeys(groups or list(group_counts)))
    if group_counts.get(MANUAL_GROUP, 0) and MANUAL_GROUP not in selected_groups:
        selected_groups.append(MANUAL_GROUP)
    if pick_all is None:
        question_count = sum(group_counts.get(group, 0) for group in selected_groups)
    else:
        question_count = sum(
            group_counts.get(group, 0)
            if group == MANUAL_GROUP
            else min(group_counts.get(group, 0), pick_all)
            for group in selected_groups
        )
    provider_count = len(providers)
    return question_count, provider_count, question_count * provider_count


def _collect_groups(groups: List[str], custom_questions: List[str] | None) -> list[str]:
    collect_groups = list(dict.fromkeys(groups))
    if custom_questions and MANUAL_GROUP not in collect_groups:
        collect_groups.append(MANUAL_GROUP)
    return collect_groups


def _env_positive_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        print(f"[AISO Pipeline] {name} must be an integer; using {default}.")
        return default
    if value <= 0:
        print(f"[AISO Pipeline] {name} must be positive; using {default}.")
        return default
    return value


async def run_pipeline(
    scan_id: str,
    client_id: str,
    providers: List[str],
    groups: List[str],
    custom_questions: Optional[List[str]] = None,
    byok_keys: Optional[dict] = None,
):
    """
    Background task — runs the full AISO pipeline.

    BYOK: Resolves which API keys to use per provider.
    Priority: server env key (Pro) > BYOK user key (Free) > skip provider.
    Keys are used in memory only and never persisted.
    """
    from api.database import SessionLocal, Scan
    db = SessionLocal()
    try:
        scan = db.query(Scan).filter(Scan.id == scan_id).first()
        if not scan:
            return
        scan.status = "running"
        scan.started_at = datetime.now(timezone.utc)
        db.commit()

        # ── Resolve active providers via BYOK key merging ─────────────────────
        # Server env keys (Pro users). BYOK fills gaps for Free tier.
        env_key_map = {
            "openai":     os.environ.get("OPENAI_API_KEY",      "").strip(),
            "claude":     os.environ.get("ANTHROPIC_API_KEY",   "").strip(),
            "perplexity": os.environ.get("PERPLEXITY_API_KEY",  "").strip(),
            "gemini":     os.environ.get("GOOGLE_AI_API_KEY",   "").strip(),
        }
        byok = byok_keys or {}

        active_providers: List[str] = []
        skipped_providers: List[str] = []

        for p in providers:
            # Server key takes priority; fall back to user's BYOK key
            key = env_key_map.get(p) or byok.get(p, "").strip()
            if key:
                active_providers.append(p)
            else:
                skipped_providers.append(p)
                print(f"[AISO Pipeline] Scan {scan_id}: skipping '{p}' — no API key available.")

        if skipped_providers:
            print(f"[AISO Pipeline] Providers skipped (no key): {skipped_providers}")
            print("[AISO Pipeline] Add keys in /dashboard/settings or contact support for managed keys.")

        if not active_providers:
            raise RuntimeError("No providers available — please add at least one API key in Settings.")

        client = db.query(Client).filter(Client.id == client_id).first()
        if not client:
            raise RuntimeError("Client not found for scan workspace preparation.")

        context_profile = _confirmed_context_profile(db, client_id)
        custom_questions = custom_questions or []
        collect_groups = _collect_groups(groups, custom_questions)

        client_folder = prepare_scan_workspace(
            client,
            context_profile=context_profile,
            selected_groups=groups,
            custom_questions=custom_questions,
        )
        print(f"[AISO Pipeline] Scan workspace ready: {client_folder}")
        ranking_report_path = client_folder / "question_ranking_report.json"
        if ranking_report_path.exists():
            try:
                ranking_report = json.loads(ranking_report_path.read_text(encoding="utf-8"))
                summary = ranking_report.get("summary", {})
                print(
                    "[AISO Pipeline] Question ranking: "
                    f"{summary.get('candidates_generated', 0)} candidates generated, "
                    f"{summary.get('candidates_rejected', 0)} rejected, "
                    f"{summary.get('final_selected', 0)} final selected."
                )
            except (OSError, json.JSONDecodeError):
                print("[AISO Pipeline] Question ranking report could not be read.")

        # ── Run real pipeline via subprocess ─────────────────────────────────
        # Keys are passed as env var overrides — never written to disk.
        # collect.py receives explicit provider/group args and matching env vars.
        import asyncio
        import pathlib
        import sys

        repo_root = pathlib.Path(__file__).resolve().parent.parent.parent
        collect_script  = repo_root / "full_stack" / "collect.py"
        analysis_script = repo_root / "full_stack" / "analysis1.py"

        # Build subprocess environment: inherit current env + add resolved keys
        sub_env = os.environ.copy()
        if byok_keys:
            for provider, key in (byok_keys or {}).items():
                if key:
                    env_var = {
                        "openai":     "OPENAI_API_KEY",
                        "claude":     "ANTHROPIC_API_KEY",
                        "perplexity": "PERPLEXITY_API_KEY",
                        "gemini":     "GOOGLE_AI_API_KEY",
                    }.get(provider)
                    if env_var:
                        sub_env[env_var] = key

        # Pass which providers to actually run
        sub_env["AISO_PROVIDERS"] = ",".join(active_providers)
        sub_env["AISO_GROUPS"]    = ",".join(collect_groups)
        sub_env["AISO_CLIENT_ID"] = client_id
        sub_env["AISO_SCAN_ID"]   = scan_id

        workspace_arg = str(client_folder)

        async def run_script(script: pathlib.Path, extra_args: list[str] | None = None) -> tuple[int, str]:
            if not script.exists():
                print(f"[AISO Pipeline] Script not found: {script} — skipping")
                return 0, ""
            command = [sys.executable, str(script), workspace_arg]
            if extra_args:
                command.extend(extra_args)
            proc = await asyncio.create_subprocess_exec(
                *command,
                env=sub_env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            stdout, _ = await proc.communicate()
            output = _redact_known_secrets(stdout.decode(errors="replace"), byok_keys)
            if stdout:
                print(f"[AISO Pipeline] {script.name}:\n{output}")
            return proc.returncode or 0, output

        pick_all_raw = os.environ.get("AISO_PICK_ALL", "").strip()
        pick_all_value = _env_positive_int("AISO_PICK_ALL", 0) if pick_all_raw else 0
        pick_all = pick_all_value if pick_all_value > 0 else None
        estimated_questions, estimated_providers, estimated_calls = _estimate_api_calls(
            client_folder / "query_template_bank.csv",
            collect_groups,
            active_providers,
            pick_all,
        )
        print(
            "[AISO Pipeline] Estimated API calls: "
            f"{estimated_questions} questions × {estimated_providers} providers = {estimated_calls}"
        )

        collect_args = [
            "--providers", ",".join(active_providers),
            "--groups", ",".join(collect_groups),
            "--yes",
        ]
        if pick_all is not None:
            collect_args.extend(["--pick-all", str(pick_all)])

        collect_rc, collect_output = await run_script(collect_script, collect_args)
        if collect_rc != 0:
            raise RuntimeError(_extract_script_failure("collect.py", collect_rc, collect_output))

        if os.environ.get("AISO_RUN_LEGACY_ANALYSIS", "").strip() == "1":
            await run_script(analysis_script)  # opt-in only: legacy CSV mutation path

        scan.status = "complete"
        scan.completed_at = datetime.now(timezone.utc)
        # Store which providers were actually run vs skipped
        scan.providers = json.dumps(active_providers)
        if skipped_providers:
            scan.error = json.dumps({"skipped_providers": skipped_providers})
        db.commit()
        print(f"[AISO Pipeline] Scan {scan_id} complete. Ran: {active_providers}")
        try:
            from full_stack.source_enrichment import enrich_source_profiles_for_scan

            enrichment = enrich_source_profiles_for_scan(scan_id, client_id)
            if enrichment.enabled:
                print(
                    "[AISO Pipeline] Source enrichment: "
                    f"{enrichment.enriched}/{enrichment.attempted} enriched, "
                    f"{enrichment.failed} failed, {enrichment.skipped} skipped."
                )
        except Exception as enrichment_error:
            print(f"[AISO Pipeline] Source enrichment skipped safely: {enrichment_error}")
    except Exception as e:
        scan = db.query(Scan).filter(Scan.id == scan_id).first()
        if scan:
            scan.status = "failed"
            scan.error = str(e)
            db.commit()
        print(f"[AISO Pipeline] Scan {scan_id} FAILED: {e}")
    finally:
        db.close()
        # Security: byok_keys dict is released here — Python GC will reclaim memory.
        byok_keys = None  # noqa: F841


@router.post("/clients/{client_id}/scans", response_model=ScanResponse, status_code=status.HTTP_202_ACCEPTED)
async def start_scan(
    client_id: str,
    payload: ScanCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id)
):
    """Trigger a new pipeline scan for a client. Returns immediately; runs in background."""
    # BOLA check — ensure client belongs to user
    client = db.query(Client).filter(
        Client.id == client_id,
        Client.user_id == user_id,
    ).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    if not payload.providers_valid:
        raise HTTPException(status_code=422, detail="Invalid provider(s)")
    if not payload.groups_valid:
        raise HTTPException(status_code=422, detail="Invalid group(s)")
    context_profile = _confirmed_context_profile(db, client_id)
    competitor_names = competitor_names_for_scan(client, context_profile)
    groups_ok, group_message = validate_scan_group_capabilities(payload.groups, competitor_names)
    if not groups_ok:
        raise HTTPException(status_code=400, detail=group_message)

    scan = Scan(
        id=str(uuid.uuid4()),
        client_id=client_id,
        status="pending",
        providers=json.dumps(payload.providers),
        groups=json.dumps(payload.groups),
    )
    db.add(scan)
    db.commit()
    db.refresh(scan)

    # Extract BYOK keys as plain dict (never stored — passed only to background task)
    byok_dict = payload.byok_keys.model_dump(exclude_none=True) if payload.byok_keys else {}

    background_tasks.add_task(
        run_pipeline,
        scan.id,
        client_id,
        payload.providers,
        payload.groups,
        payload.custom_questions,
        byok_dict,
    )

    return _scan_response(scan)


@router.get("/clients/{client_id}/scans", response_model=List[ScanResponse])
async def list_scans(
    client_id: str,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id)
):
    """List all scans for a client."""
    client = db.query(Client).filter(
        Client.id == client_id,
        Client.user_id == user_id,
    ).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    scans = db.query(Scan).filter(Scan.client_id == client_id).order_by(Scan.created_at.desc()).all()
    legacy_responses = [_scan_response(scan) for scan in scans]
    seen_scan_ids = {item["id"] for item in legacy_responses}
    phase13_responses = [
        item
        for item in scan_run_list_projections_for_client(db, client_id=client_id)
        if item["id"] not in seen_scan_ids
    ]
    return sorted(
        [*legacy_responses, *phase13_responses],
        key=lambda item: item["created_at"],
        reverse=True,
    )


def _safe_json_dict(value: Optional[str]) -> Dict[str, int]:
    if not value:
        return {}
    try:
        data = json.loads(value)
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    result: Dict[str, int] = {}
    for key, count in data.items():
        try:
            result[str(key)] = int(count)
        except (TypeError, ValueError):
            continue
    return result


def _scan_result_rows(db: Session, client_id: str, scan_id: str) -> List[ScanResult]:
    result_rows = db.query(ScanResult).filter(
        ScanResult.scan_id == scan_id,
        ScanResult.client_id == client_id,
    ).all()
    return [row for row in result_rows if not _is_manual_group(row.group)]


def _build_metrics_response(client: Client, scan: Scan, result_rows: List[ScanResult]) -> MetricsResponse:
    total_questions = sum(row.total_questions or 0 for row in result_rows)
    total_mentions = sum(row.mention_count or 0 for row in result_rows)

    provider_buckets: Dict[str, Dict[str, float]] = {}
    group_buckets: Dict[str, Dict[str, int]] = {}
    client_competitors = _client_competitors(client)
    competitor_counts: Dict[str, int] = {
        name: 0 for name in client_competitors
    }
    competitor_provider_counts: Dict[str, Dict[str, int]] = {
        name: {} for name in client_competitors
    }

    for row in result_rows:
        provider_bucket = provider_buckets.setdefault(
            row.provider,
            {
                "total": 0,
                "mentions": 0,
                "position_sum": 0.0,
                "position_weight": 0,
            },
        )
        provider_bucket["total"] += row.total_questions or 0
        provider_bucket["mentions"] += row.mention_count or 0
        if row.avg_position is not None and row.mention_count:
            provider_bucket["position_sum"] += row.avg_position * row.mention_count
            provider_bucket["position_weight"] += row.mention_count

        group_bucket = group_buckets.setdefault(
            row.group,
            {"total": 0, "mentions": 0},
        )
        group_bucket["total"] += row.total_questions or 0
        group_bucket["mentions"] += row.mention_count or 0

        for name, count in _safe_json_dict(row.competitor_data).items():
            competitor_counts[name] = competitor_counts.get(name, 0) + count
            provider_counts = competitor_provider_counts.setdefault(name, {})
            provider_counts[row.provider] = provider_counts.get(row.provider, 0) + count

    provider_metrics = []
    for provider, bucket in sorted(provider_buckets.items()):
        total = int(bucket["total"])
        mentions = int(bucket["mentions"])
        position_weight = int(bucket["position_weight"])
        avg_position = (
            round(float(bucket["position_sum"]) / position_weight, 2)
            if position_weight
            else None
        )
        provider_metrics.append(
            ProviderMetric(
                id=provider,
                score=_weighted_score(mentions, total),
                mention_count=mentions,
                total_questions=total,
                avg_position=avg_position,
            )
        )

    group_metrics = []
    for group, bucket in sorted(group_buckets.items()):
        total = int(bucket["total"])
        mentions = int(bucket["mentions"])
        group_metrics.append(
            GroupMetric(
                id=group,
                label=GROUP_LABELS.get(group, group),
                score=_weighted_score(mentions, total),
                mention_count=mentions,
                total_questions=total,
            )
        )

    provider_totals = {
        item.id: item.total_questions for item in provider_metrics
    }
    user_provider_mentions = {
        item.id: item.mention_count for item in provider_metrics
    }
    user_provider_scores = {
        item.id: item.score for item in provider_metrics
    }

    competitors = [
        CompetitorMetric(
            name=client.name,
            score=_weighted_score(total_mentions, total_questions),
            mention_count=total_mentions,
            provider_scores=user_provider_scores,
            provider_mentions=user_provider_mentions,
            is_you=True,
        )
    ]
    competitors.extend(
        CompetitorMetric(
            name=name,
            score=_weighted_score(count, total_questions),
            mention_count=count,
            provider_scores={
                provider: _weighted_score(
                    competitor_provider_counts.get(name, {}).get(provider, 0),
                    provider_total,
                )
                for provider, provider_total in provider_totals.items()
            },
            provider_mentions={
                provider: competitor_provider_counts.get(name, {}).get(provider, 0)
                for provider in provider_totals
            },
            is_you=False,
        )
        for name, count in competitor_counts.items()
    )
    competitors.sort(key=lambda item: item.score, reverse=True)

    return MetricsResponse(
        client_id=client.id,
        client_name=client.name,
        scan_id=scan.id,
        status=scan.status,
        overall_score=_weighted_score(total_mentions, total_questions),
        total_questions=total_questions,
        provider_metrics=provider_metrics,
        group_metrics=group_metrics,
        competitors=competitors,
    )


def _timeline_point_for_scan(
    db: Session,
    client: Client,
    scan: Scan,
    result_rows: List[ScanResult],
) -> ScanMetricsTimelinePoint:
    total_questions = sum(row.total_questions or 0 for row in result_rows)
    mention_count = sum(row.mention_count or 0 for row in result_rows)
    action_count = db.query(Action.id).filter(
        Action.client_id == client.id,
        Action.scan_id == scan.id,
    ).count()
    completed_action_count = db.query(Action.id).filter(
        Action.client_id == client.id,
        Action.scan_id == scan.id,
        Action.status == "done",
    ).count()

    return ScanMetricsTimelinePoint(
        client_id=client.id,
        client_name=client.name,
        scan_id=scan.id,
        status=scan.status,
        created_at=scan.created_at,
        completed_at=scan.completed_at,
        metrics=TimelineMetrics(
            overall_score=_weighted_score(mention_count, total_questions),
            total_questions=total_questions,
            mention_count=mention_count,
            gap_count=max(total_questions - mention_count, 0),
            action_count=action_count,
            completed_action_count=completed_action_count,
            action_completion_rate=_weighted_score(completed_action_count, action_count),
        ),
    )


def _confirmed_context_profile(db: Session, client_id: str) -> Optional[dict]:
    context = db.query(ClientContext).filter(
        ClientContext.client_id == client_id,
        ClientContext.status == "confirmed",
    ).first()
    if not context or not context.profile_json:
        return None
    try:
        data = json.loads(context.profile_json)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _client_competitors(client: Client) -> List[str]:
    if not client.competitors:
        return []
    try:
        data = json.loads(client.competitors)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    return [str(item) for item in data if str(item).strip()]


def _weighted_score(mentions: int, total: int) -> float:
    return round((mentions / total) * 100, 2) if total else 0.0


def _client_domain(client_url: Optional[str]) -> Optional[str]:
    raw = str(client_url or "").strip()
    if not raw:
        return None
    if not raw.startswith(("http://", "https://")):
        raw = f"https://{raw}"
    try:
        host = urlsplit(raw).netloc.lower()
    except ValueError:
        return None
    return host.removeprefix("www.") or None


def _answer_mentions_client(answer: Optional[str], client: Client) -> bool:
    clean = str(answer or "").lower()
    if not clean:
        return False
    names = {
        str(client.name or "").strip().lower(),
        str(client.id or "").replace("_", " ").replace("-", " ").strip().lower(),
    }
    return any(name and name in clean for name in names)


def _gap_impact_label(score: float) -> str:
    if score >= 8.5:
        return "high"
    if score >= 6.5:
        return "medium"
    return "low"


def _citation_source_payload(citation: ScanCitation) -> dict[str, Any]:
    return {
        "url": citation.citation_url,
        "title": citation.citation_title,
        "domain": citation.source_domain,
        "rank": citation.source_rank,
        "canonical_url": citation.canonical_url or citation.citation_url,
        "citation_origin": citation.citation_origin,
        "cited_text": citation.cited_text,
        "web_search_used": citation.web_search_used,
        "owner_type": citation.owner_type or "unknown",
        "source_type": citation.source_type or "unknown_review_needed",
        "action_role": citation.action_role or "direct_citation_target",
        "actionability_score": float(citation.actionability_score or 0),
        "influence_score": float(citation.influence_score or 0),
        "relevance_score": float(citation.relevance_score or 0),
        "confidence_score": float(citation.confidence_score or 0),
        "classification_reason": citation.classification_reason,
    }


def _source_title(domain: str) -> str:
    if domain.endswith("google.com"):
        return "Strengthen Google Business Profile and local proof"
    if domain.endswith("yelp.com"):
        return "Improve Yelp/review proof for missed queries"
    if domain.endswith("facebook.com") or domain.endswith("instagram.com"):
        return "Improve social profile proof and service language"
    return f"Build citation/proof coverage on {domain}"


def _db_backed_gap_report(db: Session, client: Client, scan: Scan) -> dict[str, Any]:
    """Build proof view from persisted scan rows when the raw CSV is unavailable."""
    results = db.query(ScanResult).filter(
        ScanResult.scan_id == scan.id,
        ScanResult.client_id == client.id,
    ).all()
    citations = db.query(ScanCitation).filter(
        ScanCitation.scan_id == scan.id,
        ScanCitation.client_id == client.id,
    ).all()
    results = [row for row in results if not _is_manual_group(row.group)]
    citations = [row for row in citations if not _is_manual_group(row.group)]

    total_results = sum(int(row.total_questions or 0) for row in results)
    appeared_count = sum(int(row.mention_count or 0) for row in results)
    missed_count = max(total_results - appeared_count, 0)
    client_domain = _client_domain(client.url)

    coverage = []
    weak_segments = []
    competitor_counts: dict[str, int] = {}
    for row in results:
        total = int(row.total_questions or 0)
        appeared = int(row.mention_count or 0)
        missed = max(total - appeared, 0)
        score = float(row.visibility_score or _weighted_score(appeared, total))
        group = row.group or "all"
        provider = row.provider or "unknown"
        coverage.append(
            {
                "group": group,
                "group_label": GAP_GROUP_LABELS.get(group, group),
                "provider": provider,
                "total": total,
                "appeared": appeared,
                "missed": missed,
                "appearance_rate": _weighted_score(appeared, total),
            }
        )
        if score < 70:
            weak_segments.append(
                {
                    "provider": provider,
                    "group": group,
                    "group_label": GAP_GROUP_LABELS.get(group, group),
                    "score": score,
                    "appeared": appeared,
                    "total": total,
                    "missed": missed,
                }
            )
        for name, count in _safe_json_dict(row.competitor_data).items():
            competitor_counts[name] = competitor_counts.get(name, 0) + count

    weak_segments.sort(key=lambda item: (item["score"], -GAP_GROUP_IMPACT.get(item["group"], 0)))

    citations_by_query: dict[tuple[str, str, str], list[ScanCitation]] = {}
    for citation in citations:
        key = (citation.provider, citation.group or "all", citation.question or "")
        citations_by_query.setdefault(key, []).append(citation)

    source_buckets: dict[str, dict[str, Any]] = {}
    query_results = []
    for (provider, group, question), query_citations in citations_by_query.items():
        answer_excerpt = next((item.answer_excerpt for item in query_citations if item.answer_excerpt), None)
        appeared = _answer_mentions_client(answer_excerpt, client)
        source_payloads = [_citation_source_payload(item) for item in query_citations]
        query_results.append(
            {
                "question": question,
                "group": group,
                "group_label": GAP_GROUP_LABELS.get(group, group),
                "provider": provider,
                "appeared": appeared,
                "mention_rank": 1 if appeared else None,
                "competitors_mentioned": [],
                "cited_sources": source_payloads,
                "answer_excerpt": answer_excerpt,
                "priority_score": round(min(GAP_GROUP_IMPACT.get(group, 6.0) + (0 if appeared else 1.2), 10.0), 2),
            }
        )
        if appeared:
            continue
        for source in source_payloads:
            domain = str(source.get("domain") or "").lower()
            if not domain or domain == client_domain:
                continue
            bucket = source_buckets.setdefault(
                domain,
                {
                    "domain": domain,
                    "missed_query_count": 0,
                    "providers": set(),
                    "groups": set(),
                    "example_questions": [],
                    "top_urls": [],
                    "owner_type": source.get("owner_type") or "unknown",
                    "source_type": source.get("source_type") or "unknown_review_needed",
                    "action_role": source.get("action_role") or "direct_citation_target",
                    "actionability_score": float(source.get("actionability_score") or 0),
                    "confidence_score": float(source.get("confidence_score") or 0),
                    "classification_reason": source.get("classification_reason"),
                },
            )
            bucket["missed_query_count"] += 1
            bucket["providers"].add(provider)
            bucket["groups"].add(group)
            if question and question not in bucket["example_questions"]:
                bucket["example_questions"].append(question)
            if source.get("url") and source["url"] not in bucket["top_urls"]:
                bucket["top_urls"].append(source["url"])
            bucket["actionability_score"] = max(
                float(bucket.get("actionability_score") or 0),
                float(source.get("actionability_score") or 0),
            )
            bucket["confidence_score"] = max(
                float(bucket.get("confidence_score") or 0),
                float(source.get("confidence_score") or 0),
            )

    source_opportunities = [
        {
            "domain": source["domain"],
            "missed_query_count": source["missed_query_count"],
            "providers": sorted(source["providers"]),
            "groups": sorted(source["groups"]),
            "example_questions": source["example_questions"][:3],
            "top_urls": source["top_urls"][:3],
            "owner_type": source.get("owner_type") or "unknown",
            "source_type": source.get("source_type") or "unknown_review_needed",
            "action_role": source.get("action_role") or "direct_citation_target",
            "actionability_score": round(float(source.get("actionability_score") or 0), 2),
            "confidence_score": round(float(source.get("confidence_score") or 0), 2),
            "classification_reason": source.get("classification_reason"),
        }
        for source in source_buckets.values()
    ]
    source_opportunities.sort(
        key=lambda item: (item["actionability_score"], item["missed_query_count"]),
        reverse=True,
    )

    listing_targets = [
        source for source in source_opportunities
        if source["action_role"] == "listing_or_profile_target"
    ]
    direct_targets = [
        source for source in source_opportunities
        if source["action_role"] in {"direct_citation_target", "listing_or_profile_target"}
    ]
    publisher_targets = [
        source for source in source_opportunities
        if source["action_role"] == "partnership_or_pr_target"
    ]
    authority_content_gaps = [
        source for source in source_opportunities
        if source["action_role"] == "content_gap_signal"
    ]
    competitive_evidence = [
        source for source in source_opportunities
        if source["action_role"] == "competitive_evidence" or source["owner_type"] == "competitor_owned"
    ]
    noise_sources = [
        source for source in source_opportunities
        if source["action_role"] == "ignore" or source["source_type"] == "low_value_or_noise"
    ]

    competitor_gaps = [
        {
            "name": name,
            "missed_query_count": count,
            "providers": [],
            "groups": [],
            "example_questions": [],
        }
        for name, count in sorted(competitor_counts.items(), key=lambda item: item[1], reverse=True)
    ]

    priority_fixes: list[dict[str, Any]] = []
    for segment in weak_segments[:4]:
        score = GAP_GROUP_IMPACT.get(segment["group"], 6.0) + (70 - segment["score"]) / 20
        priority_fixes.append(
            {
                "title": f"Close {segment['group_label']} gaps on {segment['provider']}",
                "impact": _gap_impact_label(score),
                "score": round(min(score, 10.0), 2),
                "why": (
                    f"{segment['missed']} of {segment['total']} provider-question results did not mention "
                    f"{client.name}."
                ),
                "next_step": "Add or improve service, FAQ, review, and proof content matching these missed query intents.",
                "evidence": {
                    "provider": segment["provider"],
                    "group": segment["group"],
                    "visibility_score": segment["score"],
                },
            }
        )
    for source in direct_targets[:3]:
        score = min(9.5, 6.5 + source["missed_query_count"] * 0.4)
        priority_fixes.append(
            {
                "title": _source_title(source["domain"]),
                "impact": _gap_impact_label(score),
                "score": round(score, 2),
                "why": f"{source['domain']} was cited on {source['missed_query_count']} missed query results.",
                "next_step": "Create, claim, improve, or align proof on this source if it is realistically influenceable.",
                "evidence": {
                    "domain": source["domain"],
                    "source_type": source["source_type"],
                    "action_role": source["action_role"],
                    "example_questions": source["example_questions"][:2],
                    "top_urls": source["top_urls"][:2],
                },
            }
        )
    priority_fixes.sort(key=lambda item: item["score"], reverse=True)

    web_search_known = [item for item in citations if item.web_search_used is not None]
    web_search_used_count = sum(1 for item in web_search_known if item.web_search_used)
    return {
        "client_id": client.id,
        "client_name": client.name,
        "scan_id": scan.id,
        "summary": {
            "total_provider_question_results": total_results,
            "appeared_count": appeared_count,
            "missed_count": missed_count,
            "appearance_rate": _weighted_score(appeared_count, total_results),
            "source_opportunity_count": len(source_opportunities),
            "competitor_gap_count": len(competitor_gaps),
            "actionable_source_count": len(direct_targets) + len(publisher_targets),
            "competitive_evidence_count": len(competitive_evidence),
            "content_gap_count": len(authority_content_gaps),
            "low_confidence_source_count": sum(1 for item in source_opportunities if item["confidence_score"] < 6),
            "web_search_coverage": {
                "known_source_count": len(web_search_known),
                "used_source_count": web_search_used_count,
                "coverage_rate": _weighted_score(web_search_used_count, len(web_search_known)),
            },
        },
        "coverage": coverage,
        "weak_segments": weak_segments,
        "source_opportunities": source_opportunities[:20],
        "source_intelligence": {
            "direct_targets": direct_targets[:20],
            "listing_targets": listing_targets[:20],
            "publisher_targets": publisher_targets[:20],
            "authority_content_gaps": authority_content_gaps[:20],
            "competitive_evidence": competitive_evidence[:20],
            "noise_sources": noise_sources[:20],
        },
        "competitive_evidence": competitive_evidence[:20],
        "authority_content_gaps": authority_content_gaps[:20],
        "noise_sources": noise_sources[:20],
        "competitor_gaps": competitor_gaps[:20],
        "priority_fixes": priority_fixes[:8],
        "query_results": sorted(query_results, key=lambda item: (item["appeared"], -item["priority_score"]))[:200],
        "report_source": "database_fallback",
    }


@router.get("/clients/{client_id}/metrics", response_model=MetricsResponse)
async def get_client_metrics(
    client_id: str,
    scan_id: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id)
):
    """Return aggregated visibility metrics for a client's scan results."""
    client = db.query(Client).filter(
        Client.id == client_id,
        Client.user_id == user_id,
    ).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    phase13_metrics = phase13_metrics_for_client(
        db,
        client_id=client_id,
        user_id=user_id,
        scan_id=scan_id,
    )
    if phase13_metrics:
        return MetricsResponse(**phase13_metrics)

    if scan_id:
        scan = db.query(Scan).filter(
            Scan.id == scan_id,
            Scan.client_id == client_id,
        ).first()
    else:
        scan = None
        scans = db.query(Scan).filter(
            Scan.client_id == client_id,
        ).order_by(Scan.created_at.desc()).all()
        for candidate in scans:
            has_results = db.query(ScanResult.id).filter(
                ScanResult.scan_id == candidate.id,
                ScanResult.client_id == client_id,
            ).first()
            if has_results:
                scan = candidate
                break

    if not scan:
        raise HTTPException(status_code=404, detail="No scan metrics found")

    result_rows = _scan_result_rows(db, client_id, scan.id)
    if not result_rows:
        raise HTTPException(status_code=404, detail="No scan metrics found")

    return _build_metrics_response(client, scan, result_rows)


@router.get("/scans/metrics/timeline", response_model=List[ScanMetricsTimelinePoint])
async def get_scan_metrics_timeline(
    client_id: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    """Return chronological scan-level metrics for progress trend charts."""
    clients_query = db.query(Client).filter(Client.user_id == user_id)
    if client_id:
        clients_query = clients_query.filter(Client.id == client_id)

    clients = clients_query.all()
    if client_id and not clients:
        raise HTTPException(status_code=404, detail="Client not found")
    if not clients:
        return []

    client_by_id = {client.id: client for client in clients}
    phase13_points = phase13_timeline_points_for_clients(db, clients=client_by_id)
    phase13_scan_ids = {point["scan_id"] for point in phase13_points}

    scans = db.query(Scan).filter(
        Scan.client_id.in_(list(client_by_id.keys())),
    ).order_by(Scan.created_at.asc()).all()

    points: List[ScanMetricsTimelinePoint] = []
    points.extend(ScanMetricsTimelinePoint(**point) for point in phase13_points)
    for scan in scans:
        if scan.id in phase13_scan_ids:
            continue
        client = client_by_id.get(scan.client_id)
        if not client:
            continue
        result_rows = _scan_result_rows(db, client.id, scan.id)
        if not result_rows:
            continue
        points.append(_timeline_point_for_scan(db, client, scan, result_rows))

    return sorted(points, key=lambda point: point.completed_at or point.created_at)


@router.get("/clients/{client_id}/gap-report")
async def get_client_gap_report(
    client_id: str,
    scan_id: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    """Return appeared/missed queries, source gaps, and ranked fixes for a scan."""
    client = db.query(Client).filter(
        Client.id == client_id,
        Client.user_id == user_id,
    ).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    if scan_id:
        scan = db.query(Scan).filter(
            Scan.id == scan_id,
            Scan.client_id == client_id,
        ).first()
    else:
        scan = None
        scans = db.query(Scan).filter(
            Scan.client_id == client_id,
        ).order_by(Scan.created_at.desc()).all()
        for candidate in scans:
            has_results = db.query(ScanResult.id).filter(
                ScanResult.scan_id == candidate.id,
                ScanResult.client_id == client_id,
            ).first()
            if has_results:
                scan = candidate
                break

    if not scan:
        raise HTTPException(status_code=404, detail="No completed scan results found")

    artifact = db.query(ScanArtifact).filter(
        ScanArtifact.scan_id == scan.id,
        ScanArtifact.client_id == client_id,
        ScanArtifact.artifact_type == "collect_csv",
    ).order_by(ScanArtifact.created_at.desc()).first()
    if not artifact:
        return _db_backed_gap_report(db, client, scan)

    try:
        with materialize_artifact_file(artifact) as artifact_path:
            rows, fieldnames = read_collect_csv(artifact_path)
            identity = load_client_identity(
                artifact_path.parent,
                fallback_name=client.name,
                fallback_competitors=_client_competitors(client),
            )
    except ArtifactStorageError as exc:
        print(f"[AISO Gap Report] Falling back to DB rows for scan {scan.id}: {exc}")
        return _db_backed_gap_report(db, client, scan)
    return build_gap_report(
        GapReportInput(
            rows=rows,
            fieldnames=fieldnames,
            identity=identity,
            client_url=client.url,
            scan_id=scan.id,
            client_id=client.id,
            client_name=client.name,
        )
    )


def _parse_skipped(error_field: Optional[str]) -> List[str]:
    """Extract skipped_providers from the error JSON field (never raises)."""
    if not error_field:
        return []
    try:
        data = json.loads(error_field)
        if isinstance(data, dict):
            return data.get("skipped_providers", [])
    except Exception:
        pass
    return []


def _friendly_scan_error(message: str) -> str:
    generic_collect_failures = (
        "collect.py exited with code",
        "collect.py failed with exit code",
    )
    if any(marker in message for marker in generic_collect_failures):
        return (
            "Scan collection failed. Check the selected provider API keys, quota, "
            "and rate limits, then run a new scan."
        )
    return message


def _public_error(error_field: Optional[str]) -> Optional[str]:
    """Return a user-facing scan error while hiding skipped-provider metadata."""
    if not error_field:
        return None
    try:
        data = json.loads(error_field)
        if isinstance(data, dict):
            message = data.get("error") or data.get("message")
            return _friendly_scan_error(str(message)) if message else None
    except Exception:
        pass
    return _friendly_scan_error(error_field)


def _json_list(value: Optional[str]) -> Optional[List[str]]:
    if not value:
        return None
    try:
        data = json.loads(value)
    except Exception:
        return None
    if not isinstance(data, list):
        return None
    return [str(item) for item in data]


def _scan_response(scan: Scan) -> dict:
    return {
        "id": scan.id,
        "client_id": scan.client_id,
        "status": scan.status,
        "providers": _json_list(scan.providers),
        "groups": _json_list(scan.groups),
        "skipped_providers": _parse_skipped(scan.error),
        "started_at": scan.started_at,
        "completed_at": scan.completed_at,
        "created_at": scan.created_at,
        "error": _public_error(scan.error),
    }


def _provider_names_from_collect(fieldnames: List[str]) -> list[str]:
    return [
        field.removeprefix("response_")
        for field in fieldnames
        if field.startswith("response_")
    ]


def _short_answer_excerpt(answer: str, limit: int = 420) -> Optional[str]:
    clean = " ".join(str(answer or "").split())
    if not clean:
        return None
    return clean if len(clean) <= limit else clean[: limit - 1].rstrip() + "…"


@router.get("/clients/{client_id}/scans/{scan_id}", response_model=ScanDetailResponse)
async def get_scan(
    client_id: str,
    scan_id: str,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id)
):
    """Get a single scan — used by onboarding to poll status."""
    # Ensure client belongs to user first
    client = db.query(Client).filter(
        Client.id == client_id,
        Client.user_id == user_id,
    ).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    scan = db.query(Scan).filter(
        Scan.id == scan_id,
        Scan.client_id == client_id,
    ).first()
    if not scan:
        phase13_scan = next(
            (
                item
                for item in scan_run_list_projections_for_client(db, client_id=client_id)
                if item["id"] == scan_id
            ),
            None,
        )
        if not phase13_scan:
            raise HTTPException(status_code=404, detail="Scan not found")
        return {**phase13_scan, "artifacts": []}
    artifacts = db.query(ScanArtifact).filter(
        ScanArtifact.scan_id == scan_id,
        ScanArtifact.client_id == client_id,
    ).order_by(ScanArtifact.created_at.desc()).all()
    return {**_scan_response(scan), "artifacts": artifacts}


@router.get("/clients/{client_id}/scans/{scan_id}/artifacts/{artifact_id}/download")
async def download_scan_artifact(
    client_id: str,
    scan_id: str,
    artifact_id: str,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    """Download a local scan artifact when the account has export access."""
    client = db.query(Client).filter(
        Client.id == client_id,
        Client.user_id == user_id,
    ).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    artifact = db.query(ScanArtifact).filter(
        ScanArtifact.id == artifact_id,
        ScanArtifact.scan_id == scan_id,
        ScanArtifact.client_id == client_id,
    ).first()
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")
    if not _can_download_artifacts(db, user_id):
        raise HTTPException(status_code=403, detail="Artifact export requires Pro access")

    if artifact.storage_backend == "local":
        path = _resolve_local_artifact_path(artifact)
        return FileResponse(
            path,
            media_type=artifact.mime_type or "application/octet-stream",
            filename=artifact.original_filename or path.name,
        )
    if artifact.storage_backend == "onedrive":
        try:
            content = download_onedrive_artifact(artifact.storage_path)
        except ArtifactStorageError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        headers = {
            "Content-Disposition": (
                f'attachment; filename="{artifact.original_filename or "aiso-artifact"}"'
            )
        }
        return Response(
            content=content,
            media_type=artifact.mime_type or "application/octet-stream",
            headers=headers,
        )
    raise HTTPException(status_code=404, detail="Artifact storage backend is not supported")


@router.get(
    "/clients/{client_id}/scans/{scan_id}/citations",
    response_model=List[CitationResponse],
)
async def list_scan_citations(
    client_id: str,
    scan_id: str,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    """List citation/source evidence for a scan when available."""
    client = db.query(Client).filter(
        Client.id == client_id,
        Client.user_id == user_id,
    ).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    scan = db.query(Scan).filter(
        Scan.id == scan_id,
        Scan.client_id == client_id,
    ).first()
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")

    return db.query(ScanCitation).filter(
        ScanCitation.client_id == client_id,
        ScanCitation.scan_id == scan_id,
    ).order_by(
        ScanCitation.provider.asc(),
        ScanCitation.group.asc(),
        ScanCitation.question.asc(),
        ScanCitation.source_rank.asc(),
    ).all()


@router.get(
    "/clients/{client_id}/scans/{scan_id}/custom-questions",
    response_model=CustomQuestionsResponse,
)
async def list_scan_custom_questions(
    client_id: str,
    scan_id: str,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    """Return scan-specific custom question results without mixing them into benchmarks."""
    client = db.query(Client).filter(
        Client.id == client_id,
        Client.user_id == user_id,
    ).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    scan = db.query(Scan).filter(
        Scan.id == scan_id,
        Scan.client_id == client_id,
    ).first()
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")

    citations = db.query(ScanCitation).filter(
        ScanCitation.client_id == client_id,
        ScanCitation.scan_id == scan_id,
        ScanCitation.group == MANUAL_GROUP,
    ).order_by(
        ScanCitation.question.asc(),
        ScanCitation.provider.asc(),
        ScanCitation.source_rank.asc(),
    ).all()
    citations_by_answer: dict[tuple[str, str], list[ScanCitation]] = {}
    for citation in citations:
        key = (citation.question or "", citation.provider or "")
        citations_by_answer.setdefault(key, []).append(citation)

    question_map: dict[str, dict[str, Any]] = {}

    def ensure_question(question: str) -> dict[str, Any]:
        return question_map.setdefault(question, {"question": question, "providers": {}})

    artifact = db.query(ScanArtifact).filter(
        ScanArtifact.scan_id == scan.id,
        ScanArtifact.client_id == client_id,
        ScanArtifact.artifact_type == "collect_csv",
    ).order_by(ScanArtifact.created_at.desc()).first()
    data_status = "artifact_missing"

    if artifact:
        try:
            with materialize_artifact_file(artifact) as artifact_path:
                rows, fieldnames = read_collect_csv(artifact_path)
                providers = _provider_names_from_collect(fieldnames)
                for row in rows:
                    if not _is_manual_group(row.get("group")):
                        continue
                    question = str(row.get("question") or "").strip()
                    if not question:
                        continue
                    entry = ensure_question(question)
                    for provider in providers:
                        answer = str(row.get(f"response_{provider}") or "")
                        error = str(row.get(f"error_{provider}") or "")
                        if not answer and not error:
                            continue
                        entry["providers"][provider] = {
                            "mentioned": _answer_mentions_client(answer, client) if answer else False,
                            "answer_excerpt": _short_answer_excerpt(answer),
                            "citations": [
                                _citation_source_payload(item)
                                for item in citations_by_answer.get((question, provider), [])
                            ],
                        }
                data_status = "complete"
        except ArtifactStorageError:
            data_status = "artifact_unavailable"

    if not question_map and citations:
        for citation in citations:
            question = str(citation.question or "").strip()
            provider = str(citation.provider or "").strip()
            if not question or not provider:
                continue
            entry = ensure_question(question)
            provider_payload = entry["providers"].setdefault(
                provider,
                {
                    "mentioned": _answer_mentions_client(citation.answer_excerpt, client),
                    "answer_excerpt": citation.answer_excerpt,
                    "citations": [],
                },
            )
            provider_payload["citations"].append(_citation_source_payload(citation))
        data_status = "citations_only"

    return {
        "scan_id": scan_id,
        "client_id": client_id,
        "data_status": data_status if question_map else "empty",
        "questions": list(question_map.values()),
    }


@router.get(
    "/clients/{client_id}/sources",
    response_model=List[SourceProfileResponse],
)
async def list_client_sources(
    client_id: str,
    scan_id: Optional[str] = Query(default=None),
    owner_type: Optional[str] = Query(default=None),
    source_type: Optional[str] = Query(default=None),
    action_role: Optional[str] = Query(default=None),
    min_actionability: Optional[float] = Query(default=None, ge=0, le=10),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    """List classified source graph profiles for a client."""
    client = db.query(Client).filter(
        Client.id == client_id,
        Client.user_id == user_id,
    ).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    query = db.query(SourceProfile).filter(SourceProfile.client_id == client_id)
    if scan_id:
        scan = db.query(Scan).filter(
            Scan.id == scan_id,
            Scan.client_id == client_id,
        ).first()
        if not scan:
            raise HTTPException(status_code=404, detail="Scan not found")
        urls = [
            row[0]
            for row in db.query(ScanCitation.canonical_url).filter(
                ScanCitation.client_id == client_id,
                ScanCitation.scan_id == scan_id,
                ScanCitation.canonical_url.isnot(None),
            ).distinct().all()
        ]
        if not urls:
            return []
        query = query.filter(SourceProfile.canonical_url.in_(urls))
    if owner_type:
        query = query.filter(SourceProfile.owner_type == owner_type)
    if source_type:
        query = query.filter(SourceProfile.source_type == source_type)
    if action_role:
        query = query.filter(SourceProfile.action_role == action_role)
    if min_actionability is not None:
        query = query.filter(SourceProfile.actionability_score >= min_actionability)

    profiles = query.order_by(
        SourceProfile.influence_score.desc().nullslast(),
        SourceProfile.actionability_score.desc().nullslast(),
        SourceProfile.source_domain.asc(),
    ).offset(offset).limit(limit).all()

    def _json_list(raw: str | None) -> list:
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return []
        return data if isinstance(data, list) else []

    def _json_dict(raw: str | None) -> dict:
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    responses: list[SourceProfileResponse] = []
    for profile in profiles:
        metadata = _json_dict(profile.metadata_json)
        responses.append(
            SourceProfileResponse(
                id=profile.id,
                canonical_url=profile.canonical_url,
                source_domain=profile.source_domain,
                source_title=profile.source_title,
                owner_type=profile.owner_type,
                source_type=profile.source_type,
                action_role=profile.action_role,
                actionability_score=profile.actionability_score,
                influence_score=profile.influence_score,
                relevance_score=profile.relevance_score,
                client_mentioned=profile.client_mentioned,
                competitors_mentioned=_json_list(profile.competitors_mentioned_json),
                topics=_json_list(profile.topics_json),
                fetch_status=profile.fetch_status,
                classification_reason=profile.classification_reason,
                citation_count=int(metadata.get("citation_count") or 0),
                prompt_count=int(metadata.get("unique_question_count") or 0),
                provider_count=int(metadata.get("provider_count") or 0),
                example_questions=list(metadata.get("example_questions") or [])[:5],
                top_urls=list(metadata.get("top_urls") or [])[:5],
            )
        )
    return responses
