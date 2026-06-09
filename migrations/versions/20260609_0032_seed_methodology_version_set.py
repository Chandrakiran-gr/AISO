"""Seed the active methodology version set (Phase 13 provenance anchor).

Phase 13 scans require an *active* ``methodology_version_set`` row: the kickoff
stamps its id onto every scan run and all downstream artifacts (scan_metrics,
scan_provenance, AVS computations …), and refuses to run without one. Until now
this table was only ever written by tests, so a fresh/production database had no
active row and every scan failed with HTTP 409 "Active methodology version set
not found".

This seeds the canonical v1.0 set (``AISO-2026.06``). Every component version is
taken from the code's own constants (AVS_FORMULA_VERSION, SAMPLING_CONFIG_VERSION,
CLASSIFIER_VERSION, the question-bank version, …) and the spec hash is the sha256
of the methodology ``MANIFEST.txt``. Idempotent: keyed on a fixed id, so it is a
no-op if the row already exists (e.g. inserted manually to unblock prod first) —
that pre-existing row, including its ``approved_by``, is left untouched.

Revision ID: 20260609_0032
Revises: 20260609_0031
Create Date: 2026-06-09 00:00:00.000000
"""

from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa


revision = "20260609_0032"
down_revision = "20260609_0031"
branch_labels = None
depends_on = None

# Canonical v1.0 methodology version set. The fixed id makes the seed idempotent
# and lets a manual prod bootstrap and this migration converge on one row.
_ID = "a150f3c0-0000-4000-8000-000000000001"
_LABEL = "AISO-2026.06"  # date-anchored label per methodology/versioning-1.0.md
# sha256 of methodology MANIFEST.txt (the checksum manifest of all spec docs).
_SPEC_HASH_HEX = "b5fea3a9b827a97380f4882c96835903fe6b3fccc7cd0121b345be5c8c6091c6"
_ACTIVE_FROM = datetime(2026, 6, 1, tzinfo=timezone.utc)

_VALUES = {
    "id": _ID,
    "label": _LABEL,
    "avs_formula_version": "AVS-1.0.0",
    "bank_version": "question-bank-1.0.0",
    "stance_classifier_version": "classifier-1.0.0",
    "source_classifier_version": "classifier-1.0.0",
    "sampling_config_version": "N-sampling-1.0.0",
    "provider_model_snapshot_version": "provider-snapshot-1.0.0",
    "valid_from": _ACTIVE_FROM,
    "sys_period": "current",
    "spec_document_url": "MANIFEST.txt",
    "spec_document_hash": bytes.fromhex(_SPEC_HASH_HEX),
    # Fresh-DB default. Production's row is bootstrapped separately with the
    # owning account's identity and is preserved by the existence guard below.
    "approved_by": "admin@aisoglobal.com",
    "approved_at": _ACTIVE_FROM,
}


def upgrade() -> None:
    bind = op.get_bind()
    already = bind.execute(
        sa.text("SELECT 1 FROM methodology_version_set WHERE id = :id"),
        {"id": _ID},
    ).first()
    if already:
        return
    bind.execute(
        sa.text(
            """
            INSERT INTO methodology_version_set (
                id, label, avs_formula_version, bank_version,
                stance_classifier_version, source_classifier_version,
                sampling_config_version, provider_model_snapshot_version,
                valid_from, valid_to, sys_period,
                spec_document_url, spec_document_hash,
                approved_by, approved_at
            ) VALUES (
                :id, :label, :avs_formula_version, :bank_version,
                :stance_classifier_version, :source_classifier_version,
                :sampling_config_version, :provider_model_snapshot_version,
                :valid_from, NULL, :sys_period,
                :spec_document_url, :spec_document_hash,
                :approved_by, :approved_at
            )
            """
        ),
        _VALUES,
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text("DELETE FROM methodology_version_set WHERE id = :id"),
        {"id": _ID},
    )
