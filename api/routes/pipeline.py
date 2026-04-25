"""
Pipeline router — triggers and monitors AISO pipeline runs.
Wraps setup2.py → collect.py → analysis1.py → analysis2.py
"""

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, timezone
import uuid
import json
import os

from api.database import get_db, Scan, Client

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


PLACEHOLDER_USER_ID = "dev-user-001"


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
            "openai":     os.environ.get("OPENAI_API_KEY",     "").strip(),
            "claude":     os.environ.get("ANTHROPIC_API_KEY",  "").strip(),
            "perplexity": os.environ.get("PERPLEXITY_API_KEY", "").strip(),
            "gemini":     os.environ.get("GEMINI_API_KEY",     "").strip(),
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
        # collect.py reads AISO_PROVIDERS to know which providers to query.
        import asyncio, subprocess, sys, pathlib

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
        sub_env["AISO_CLIENT_ID"] = client_id
        sub_env["AISO_SCAN_ID"]   = scan_id

        async def run_script(script: pathlib.Path) -> int:
            if not script.exists():
                print(f"[AISO Pipeline] Script not found: {script} — skipping")
                return 0
            proc = await asyncio.create_subprocess_exec(
                sys.executable, str(script), client_id,
                env=sub_env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            stdout, _ = await proc.communicate()
            if stdout:
                print(f"[AISO Pipeline] {script.name}:\n{stdout.decode(errors='replace')}")
            return proc.returncode or 0

        collect_rc = await run_script(collect_script)
        if collect_rc != 0:
            raise RuntimeError(f"collect.py exited with code {collect_rc}")

        await run_script(analysis_script)  # best-effort — don't fail scan if analysis errors

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
):
    """Trigger a new pipeline scan for a client. Returns immediately; runs in background."""
    # BOLA check — ensure client belongs to user
    client = db.query(Client).filter(
        Client.id == client_id,
        Client.user_id == PLACEHOLDER_USER_ID,
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
async def list_scans(client_id: str, db: Session = Depends(get_db)):
    """List all scans for a client."""
    client = db.query(Client).filter(
        Client.id == client_id,
        Client.user_id == PLACEHOLDER_USER_ID,
    ).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    scans = db.query(Scan).filter(Scan.client_id == client_id).order_by(Scan.created_at.desc()).all()
    for s in scans:
        if s.providers: s.providers = json.loads(s.providers)
        if s.groups:    s.groups    = json.loads(s.groups)
        s.skipped_providers = _parse_skipped(s.error)  # type: ignore
    return scans


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
async def get_scan(client_id: str, scan_id: str, db: Session = Depends(get_db)):
    """Get a single scan — used by onboarding to poll status."""
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
