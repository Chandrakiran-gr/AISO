"""
Pipeline router — triggers and monitors AISO pipeline runs.
Wraps setup2.py → collect.py → analysis1.py → analysis2.py
"""

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Dict, List, Optional
from datetime import datetime, timezone
import uuid
import json
import os

from api.database import get_db, Scan, Client, ScanResult
from api.auth import get_current_user_id

router = APIRouter(tags=["pipeline"])


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
    providers: List[str] = ["openai", "claude", "perplexity", "gemini"]
    groups:    List[str] = ["G1", "G2", "G3"]
    byok_keys: Optional[BYOKKeys] = None  # BYOK: user's own API keys (never stored)

    @property
    def providers_valid(self) -> bool:
        valid = {"openai", "claude", "perplexity", "gemini"}
        return all(p in valid for p in self.providers)

    @property
    def groups_valid(self) -> bool:
        valid = {"G1", "G2", "G3", "G4", "G5", "G6", "G7"}
        return all(g in valid for g in self.groups)


class ScanResponse(BaseModel):
    id:                str
    client_id:         str
    status:            str
    providers:         Optional[List[str]]
    groups:            Optional[List[str]]
    skipped_providers: Optional[List[str]]  # providers skipped due to missing key
    started_at:        Optional[datetime]
    created_at:        datetime

    class Config:
        from_attributes = True


class ProviderMetric(BaseModel):
    id: str
    score: float
    mention_count: int
    total_questions: int
    avg_position: Optional[float]


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
    "G7": "Post-purchase support",
    "all": "All questions",
}


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
            print(f"[AISO Pipeline] Add keys in /dashboard/settings or contact support for managed keys.")

        if not active_providers:
            raise RuntimeError("No providers available — please add at least one API key in Settings.")

        # ── Run real pipeline via subprocess ─────────────────────────────────
        # Keys are passed as env var overrides — never written to disk.
        # collect.py receives explicit provider/group args and matching env vars.
        import asyncio, sys, pathlib

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

        async def run_script(script: pathlib.Path, extra_args: list[str] | None = None) -> int:
            if not script.exists():
                print(f"[AISO Pipeline] Script not found: {script} — skipping")
                return 0
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
            if stdout:
                print(f"[AISO Pipeline] {script.name}:\n{stdout.decode(errors='replace')}")
            return proc.returncode or 0

        collect_args = [
            "--providers", ",".join(active_providers),
            "--groups", ",".join(groups),
            "--pick-all", os.environ.get("AISO_PICK_ALL", "14"),
            "--yes",
        ]

        collect_rc = await run_script(collect_script, collect_args)
        if collect_rc != 0:
            raise RuntimeError(f"collect.py exited with code {collect_rc}")

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

    scan.providers = json.loads(scan.providers)  # type: ignore
    scan.groups    = json.loads(scan.groups)      # type: ignore
    scan.skipped_providers = []  # type: ignore  # populated after pipeline runs
    return scan


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
    for s in scans:
        if s.providers: s.providers = json.loads(s.providers)
        if s.groups:    s.groups    = json.loads(s.groups)
        s.skipped_providers = _parse_skipped(s.error)  # type: ignore
    return scans


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
    competitor_counts: Dict[str, int] = {
        name: 0 for name in _client_competitors(client)
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

    competitors = [
        CompetitorMetric(
            name=client.name,
            score=_weighted_score(total_mentions, total_questions),
            mention_count=total_mentions,
            is_you=True,
        )
    ]
    competitors.extend(
        CompetitorMetric(
            name=name,
            score=_weighted_score(count, total_questions),
            mention_count=count,
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


@router.get("/clients/{client_id}/scans/{scan_id}", response_model=ScanResponse)
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
    if scan.providers: scan.providers = json.loads(scan.providers)  # type: ignore
    if scan.groups:    scan.groups    = json.loads(scan.groups)      # type: ignore
    scan.skipped_providers = _parse_skipped(scan.error)             # type: ignore
    return scan
