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

from api.database import get_db, Scan, Client

router = APIRouter(tags=["pipeline"])


class ScanCreate(BaseModel):
    client_id: str
    providers: List[str] = ["openai", "claude", "perplexity", "gemini"]
    groups:    List[str] = ["G1", "G2", "G3"]

    @property
    def providers_valid(self) -> bool:
        valid = {"openai", "claude", "perplexity", "gemini"}
        return all(p in valid for p in self.providers)

    @property
    def groups_valid(self) -> bool:
        valid = {"G1", "G2", "G3", "G4", "G5", "G6", "G7"}
        return all(g in valid for g in self.groups)


class ScanResponse(BaseModel):
    id:         str
    client_id:  str
    status:     str
    providers:  Optional[List[str]]
    groups:     Optional[List[str]]
    started_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


PLACEHOLDER_USER_ID = "dev-user-001"


async def run_pipeline(scan_id: str, client_id: str, providers: List[str], groups: List[str]):
    """
    Background task — runs the full AISO pipeline.
    TODO Phase 3: Import and call setup2.py, collect.py, analysis1.py, analysis2.py
    For now: simulates a pipeline run with status updates.
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

        # TODO: Replace with actual pipeline calls:
        # from full_stack.setup2 import main as setup_main
        # from full_stack.collect import main as collect_main
        # from full_stack.analysis1 import main as analysis1_main
        # from full_stack.analysis2 import main as analysis2_main

        # Simulate pipeline completion
        import asyncio
        await asyncio.sleep(2)

        scan.status = "complete"
        scan.completed_at = datetime.now(timezone.utc)
        db.commit()
        print(f"[AISO Pipeline] Scan {scan_id} complete.")
    except Exception as e:
        scan = db.query(Scan).filter(Scan.id == scan_id).first()
        if scan:
            scan.status = "failed"
            scan.error = str(e)
            db.commit()
        print(f"[AISO Pipeline] Scan {scan_id} FAILED: {e}")
    finally:
        db.close()


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

    background_tasks.add_task(
        run_pipeline, scan.id, client_id, payload.providers, payload.groups
    )

    scan.providers = json.loads(scan.providers)  # type: ignore
    scan.groups    = json.loads(scan.groups)      # type: ignore
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
    return scans


@router.get("/clients/{client_id}/scans/{scan_id}", response_model=ScanResponse)
async def get_scan(client_id: str, scan_id: str, db: Session = Depends(get_db)):
    """Get a single scan status."""
    scan = db.query(Scan).filter(
        Scan.id == scan_id,
        Scan.client_id == client_id,
    ).first()
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")
    if scan.providers: scan.providers = json.loads(scan.providers)
    if scan.groups:    scan.groups    = json.loads(scan.groups)
    return scan
