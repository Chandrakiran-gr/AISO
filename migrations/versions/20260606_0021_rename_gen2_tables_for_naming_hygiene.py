"""rename Gen-2 tables for naming hygiene

Removes the dangerous near-homonyms and adopts plural table names consistent with
``users``/``clients``/``scans``. All renamed tables are empty (Gen-2 is gated and
unused), so these are pure metadata renames. SQLite rewrites the one inbound FK
reference (``classification.sample_id`` → ``samples``) automatically on rename.

  samples (ExecutionSample)        -> execution_samples
  sample  (canonical Sample)       -> samples
  scan_citation                    -> scan_source_citations
  scan_action                      -> scan_actions
  scan_metric                      -> scan_metrics
  scan_competitor                  -> scan_competitors
  scan_question_result             -> scan_question_results

Revision ID: 20260606_0021
Revises: 20260606_0020
Create Date: 2026-06-06 14:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260606_0021"
down_revision = "20260606_0020"
branch_labels = None
depends_on = None

# Ordered so the canonical ``samples`` name is freed (samples -> execution_samples)
# before the canonical Sample table claims it (sample -> samples).
RENAMES = [
    ("samples", "execution_samples"),
    ("sample", "samples"),
    ("scan_citation", "scan_source_citations"),
    ("scan_action", "scan_actions"),
    ("scan_metric", "scan_metrics"),
    ("scan_competitor", "scan_competitors"),
    ("scan_question_result", "scan_question_results"),
]


def _rename_if_needed(old: str, new: str) -> None:
    """Rename only when the source exists and the target doesn't.

    Keeps the migration idempotent for a database first built by ``create_all()``
    (which already has the new names) that later adopts migrations — mirrors the
    ``if not _table_exists`` guards in the earlier Phase 12/13 migrations.
    """
    names = set(sa.inspect(op.get_bind()).get_table_names())
    if old in names and new not in names:
        op.rename_table(old, new)


def upgrade() -> None:
    for old, new in RENAMES:
        _rename_if_needed(old, new)


def downgrade() -> None:
    for old, new in reversed(RENAMES):
        _rename_if_needed(new, old)
