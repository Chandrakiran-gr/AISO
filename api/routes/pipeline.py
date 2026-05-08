"""
Pipeline router — triggers and monitors AISO pipeline runs.
Wraps setup2.py → collect.py → analysis1.py → analysis2.py
"""

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query, status
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import Dict, List, Optional
from datetime import datetime, timezone
from pathlib import Path
import uuid
import json
import os
import csv

from api.database import get_db, Scan, Client, ClientContext, ScanArtifact, ScanCitation, ScanResult, SourceProfile, User
from api.auth import get_current_user_id
from api.scan_workspace import prepare_scan_workspace
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
DEFAULT_ARTIFACT_ACCESS_EMAILS = {"admin@aisoglobal.com"}


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
    byok_keys: Optional[BYOKKeys] = None  # BYOK: user's own API keys (never stored)

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


def _configured_artifact_access_emails() -> set[str]:
    configured = {
        email.strip().lower()
        for email in os.getenv("AISO_ARTIFACT_ACCESS_EMAILS", "").split(",")
        if email.strip()
    }
    return DEFAULT_ARTIFACT_ACCESS_EMAILS | configured


def _can_download_artifacts(db: Session, user_id: str) -> bool:
    plan = os.getenv("AISO_PLAN", os.getenv("NEXT_PUBLIC_AISO_PLAN", "free")).strip().lower()
    if plan in {"pro", "agency"}:
        return True

    user = db.query(User).filter(User.id == user_id).first()
    email = (user.email if user else "").strip().lower()
    return bool(email and email in _configured_artifact_access_emails())


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
    total_questions: int
    provider_metrics: List[ProviderMetric]
    group_metrics: List[GroupMetric]
    competitors: List[CompetitorMetric]


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

    selected_groups = groups or list(group_counts)
    if pick_all is None:
        question_count = sum(group_counts.get(group, 0) for group in selected_groups)
    else:
        question_count = sum(min(group_counts.get(group, 0), pick_all) for group in selected_groups)
    provider_count = len(providers)
    return question_count, provider_count, question_count * provider_count


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

        client_folder = prepare_scan_workspace(client, context_profile=context_profile, selected_groups=groups)
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
        sub_env["AISO_GROUPS"]    = ",".join(groups)
        sub_env["AISO_CLIENT_ID"] = client_id
        sub_env["AISO_SCAN_ID"]   = scan_id

        async def run_script(script: pathlib.Path, extra_args: list[str] | None = None) -> tuple[int, str]:
            if not script.exists():
                print(f"[AISO Pipeline] Script not found: {script} — skipping")
                return 0, ""
            command = [sys.executable, str(script), client_id]
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
            groups,
            active_providers,
            pick_all,
        )
        print(
            "[AISO Pipeline] Estimated API calls: "
            f"{estimated_questions} questions × {estimated_providers} providers = {estimated_calls}"
        )

        collect_args = [
            "--providers", ",".join(active_providers),
            "--groups", ",".join(groups),
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
        run_pipeline, scan.id, client_id, payload.providers, payload.groups, byok_dict
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
    return [_scan_response(scan) for scan in scans]


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

    result_rows = db.query(ScanResult).filter(
        ScanResult.scan_id == scan.id,
        ScanResult.client_id == client_id,
    ).all()
    if not result_rows:
        raise HTTPException(status_code=404, detail="No scan metrics found")

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
        raise HTTPException(status_code=404, detail="Raw scan artifact not found for gap report")

    try:
        with materialize_artifact_file(artifact) as artifact_path:
            rows, fieldnames = read_collect_csv(artifact_path)
            identity = load_client_identity(
                artifact_path.parent,
                fallback_name=client.name,
                fallback_competitors=_client_competitors(client),
            )
    except ArtifactStorageError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
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
        raise HTTPException(status_code=404, detail="Scan not found")
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
