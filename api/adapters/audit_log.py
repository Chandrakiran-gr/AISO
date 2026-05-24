"""SQLAlchemy adapter for the hash-chained audit log."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from sqlalchemy.orm import Session

from api.database import AuditEvent
from api.domain.audit_log import (
    AuditChainViolation,
    ZERO_EVENT_HASH,
    compute_event_hash,
)


def _as_bytes(value: bytes | memoryview | None) -> bytes | None:
    if value is None:
        return None
    if isinstance(value, memoryview):
        return value.tobytes()
    return value


def _event_payload(
    *,
    actor_type: str,
    actor_id: str,
    action: str,
    resource_type: str,
    resource_id: str,
    hmac_key_version: int,
    actor_session_id: str | None = None,
    source_ip: str | None = None,
    user_agent: str | None = None,
    before_state: dict[str, Any] | None = None,
    after_state: dict[str, Any] | None = None,
    reason: str | None = None,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    return {
        "actor_type": actor_type,
        "actor_id": actor_id,
        "actor_session_id": actor_session_id,
        "source_ip": source_ip,
        "user_agent": user_agent,
        "action": action,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "before_state": before_state,
        "after_state": after_state,
        "reason": reason,
        "correlation_id": correlation_id,
        "hmac_key_version": hmac_key_version,
    }


def _payload_from_row(event: AuditEvent) -> dict[str, Any]:
    return _event_payload(
        actor_type=event.actor_type,
        actor_id=event.actor_id,
        actor_session_id=event.actor_session_id,
        source_ip=event.source_ip,
        user_agent=event.user_agent,
        action=event.action,
        resource_type=event.resource_type,
        resource_id=event.resource_id,
        before_state=event.before_state,
        after_state=event.after_state,
        reason=event.reason,
        correlation_id=event.correlation_id,
        hmac_key_version=event.hmac_key_version,
    )


def write_audit_event(
    db: Session,
    *,
    actor_type: str,
    actor_id: str,
    action: str,
    resource_type: str,
    resource_id: str,
    hmac_key: bytes,
    hmac_key_version: int,
    actor_session_id: str | None = None,
    source_ip: str | None = None,
    user_agent: str | None = None,
    before_state: dict[str, Any] | None = None,
    after_state: dict[str, Any] | None = None,
    reason: str | None = None,
    correlation_id: str | None = None,
) -> AuditEvent:
    previous = db.query(AuditEvent).order_by(AuditEvent.id.desc()).first()
    prev_hash = _as_bytes(previous.event_hash) if previous else ZERO_EVENT_HASH
    payload = _event_payload(
        actor_type=actor_type,
        actor_id=actor_id,
        actor_session_id=actor_session_id,
        source_ip=source_ip,
        user_agent=user_agent,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        before_state=before_state,
        after_state=after_state,
        reason=reason,
        correlation_id=correlation_id,
        hmac_key_version=hmac_key_version,
    )
    event_hash = compute_event_hash(
        prev_event_hash=prev_hash,
        event_payload=payload,
        hmac_key=hmac_key,
    )
    event = AuditEvent(
        event_time=datetime.now(timezone.utc),
        actor_type=actor_type,
        actor_id=actor_id,
        actor_session_id=actor_session_id,
        source_ip=source_ip,
        user_agent=user_agent,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        before_state=before_state,
        after_state=after_state,
        reason=reason,
        correlation_id=correlation_id,
        txid=0,
        prev_event_hash=prev_hash,
        event_hash=event_hash,
        hmac_key_version=hmac_key_version,
    )
    db.add(event)
    db.flush()
    return event


def verify_audit_chain(
    db: Session,
    *,
    hmac_keys: Mapping[int, bytes],
) -> list[AuditChainViolation]:
    violations: list[AuditChainViolation] = []
    expected_prev_hash = ZERO_EVENT_HASH
    events = db.query(AuditEvent).order_by(AuditEvent.id.asc()).all()

    for event in events:
        event_id = int(event.id)
        stored_prev_hash = _as_bytes(event.prev_event_hash)
        stored_event_hash = _as_bytes(event.event_hash)
        if stored_prev_hash != expected_prev_hash:
            violations.append(
                AuditChainViolation(event_id=event_id, reason="previous hash mismatch")
            )

        hmac_key = hmac_keys.get(event.hmac_key_version)
        if hmac_key is None:
            violations.append(
                AuditChainViolation(event_id=event_id, reason="missing HMAC key")
            )
            expected_prev_hash = stored_event_hash or ZERO_EVENT_HASH
            continue

        expected_event_hash = compute_event_hash(
            prev_event_hash=expected_prev_hash,
            event_payload=_payload_from_row(event),
            hmac_key=hmac_key,
        )
        if stored_event_hash != expected_event_hash:
            violations.append(
                AuditChainViolation(event_id=event_id, reason="event hash mismatch")
            )
        expected_prev_hash = stored_event_hash or ZERO_EVENT_HASH

    return violations
