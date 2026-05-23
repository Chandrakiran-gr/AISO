"""Database-backed hash chain for prompt versions."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import hashlib
import json
import uuid

from sqlalchemy.orm import Session

from api.database import MethodologyPromptVersion


ZERO_HASH = "0" * 64


def ensure_prompt_version(
    db: Session,
    *,
    prompt_key: str,
    version: str,
    prompt_text: str,
    provider: str,
    model: str,
) -> MethodologyPromptVersion:
    prompt_hash = hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()
    existing = db.query(MethodologyPromptVersion).filter(
        MethodologyPromptVersion.prompt_key == prompt_key,
        MethodologyPromptVersion.version == version,
        MethodologyPromptVersion.prompt_hash == prompt_hash,
    ).first()
    if existing:
        return existing

    previous = db.query(MethodologyPromptVersion).filter(
        MethodologyPromptVersion.prompt_key == prompt_key,
    ).order_by(MethodologyPromptVersion.created_at.desc()).first()
    prev_chain_hash = previous.chain_hash if previous else ZERO_HASH
    event_payload: dict[str, Any] = {
        "prompt_key": prompt_key,
        "version": version,
        "prompt_hash": prompt_hash,
        "provider": provider,
        "model": model,
    }
    canonical = json.dumps(event_payload, sort_keys=True, separators=(",", ":"))
    chain_hash = hashlib.sha256(f"{prev_chain_hash}{canonical}".encode("utf-8")).hexdigest()
    row = MethodologyPromptVersion(
        id=str(uuid.uuid4()),
        prompt_key=prompt_key,
        version=version,
        provider=provider,
        model=model,
        prompt_text=prompt_text,
        prompt_hash=prompt_hash,
        prev_chain_hash=prev_chain_hash,
        chain_hash=chain_hash,
        created_at=datetime.now(timezone.utc),
    )
    db.add(row)
    db.flush()
    return row
