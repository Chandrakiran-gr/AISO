"""Pure audit-log hashing helpers.

The database adapter owns persistence. This module only canonicalizes event
payloads and computes the HMAC link required by versioning-1.0.md.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any


ZERO_EVENT_HASH = b"\x00" * 32


@dataclass(frozen=True)
class AuditChainViolation:
    event_id: int
    reason: str


def canonical_serialize(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode(
        "utf-8"
    )


def compute_event_hash(
    *,
    prev_event_hash: bytes | None,
    event_payload: dict[str, Any],
    hmac_key: bytes,
) -> bytes:
    previous = prev_event_hash if prev_event_hash is not None else ZERO_EVENT_HASH
    canonical = canonical_serialize(event_payload)
    return hmac.new(hmac_key, previous + canonical, hashlib.sha256).digest()
