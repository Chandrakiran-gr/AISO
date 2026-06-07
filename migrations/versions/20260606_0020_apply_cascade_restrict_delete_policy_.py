"""apply cascade/restrict delete policy across foreign keys

Implements the Phase 1 delete policy: client/scan/user-owned rows CASCADE when
their parent is deleted; optional cross-links use SET NULL so the owning row
survives; and the immutable records (scan_provenance's FKs and every
methodology_version_set reference) are left as NO ACTION so they cannot be
silently deleted.

Existing foreign keys were created without explicit names, so PostgreSQL
auto-names them (e.g. ``actions_client_id_fkey``) while SQLite reflects them
anonymously. To drop them portably we resolve each FK's REAL name from the live
database via the inspector; on SQLite (where reflected FKs have no name) we fall
back to the batch ``naming_convention`` (``fk_<table>_<column>``), which assigns
that name during the table recreate. We then re-create each FK with an explicit
``fk_<table>_<column>`` name and the new ``ondelete`` rule. All affected FKs are
single-column.

Revision ID: 20260606_0020
Revises: 20260605_0019
Create Date: 2026-06-06 12:25:51.850865
"""

from alembic import op
import sqlalchemy as sa


revision = "20260606_0020"
down_revision = "20260605_0019"
branch_labels = None
depends_on = None

NAMING = {"fk": "fk_%(table_name)s_%(column_0_name)s"}

# table -> list of (local_col, ref_table, ref_col, ondelete)
# Only the FKs whose ondelete is changing are listed. The PROTECT FKs
# (scan_provenance.* and every methodology_version_set_id) are intentionally
# absent and are preserved unchanged when their table is recreated.
POLICY: dict[str, list[tuple[str, str, str, str]]] = {
    "actions": [("client_id", "clients", "id", "CASCADE"), ("scan_id", "scans", "id", "CASCADE")],
    "assistant_rate_limit_events": [("user_id", "users", "id", "CASCADE")],
    "avs_computation": [("scan_id", "scan_provenance", "scan_id", "CASCADE")],
    "business_profile": [("client_id", "clients", "id", "CASCADE")],
    "classification": [("sample_id", "sample", "id", "CASCADE")],
    "client_contexts": [("client_id", "clients", "id", "CASCADE")],
    "clients": [("user_id", "users", "id", "CASCADE")],
    "content_drafts": [
        ("client_id", "clients", "id", "CASCADE"),
        ("created_by", "users", "id", "CASCADE"),
        ("reviewed_by", "users", "id", "SET NULL"),
        ("conversation_id", "conversations", "id", "SET NULL"),
        ("source_action_id", "actions", "id", "SET NULL"),
    ],
    "conversations": [("user_id", "users", "id", "CASCADE"), ("client_id", "clients", "id", "CASCADE")],
    "crawl_business_profiles": [
        ("client_id", "clients", "id", "CASCADE"),
        ("job_id", "crawl_jobs", "id", "CASCADE"),
        ("workspace_id", "onboarding_workspaces", "id", "CASCADE"),
        ("approved_by_user_id", "users", "id", "SET NULL"),
    ],
    "crawl_jobs": [("workspace_id", "onboarding_workspaces", "id", "CASCADE")],
    "crawl_pages": [("job_id", "crawl_jobs", "id", "CASCADE")],
    "extraction_evidence": [("job_id", "crawl_jobs", "id", "CASCADE"), ("page_id", "crawl_pages", "id", "CASCADE")],
    "kb_chunks": [("job_id", "crawl_jobs", "id", "CASCADE"), ("page_id", "crawl_pages", "id", "CASCADE")],
    "messages": [("conversation_id", "conversations", "id", "CASCADE")],
    "onboarding_workspaces": [("client_id", "clients", "id", "CASCADE")],
    "question": [("client_id", "clients", "id", "CASCADE")],
    "question_bank_membership": [
        ("bank_version_id", "question_bank_version", "bank_version_id", "CASCADE"),
        ("question_id", "question", "question_id", "CASCADE"),
    ],
    "question_bank_version": [
        ("client_id", "clients", "id", "CASCADE"),
        ("parent_version_id", "question_bank_version", "bank_version_id", "SET NULL"),
    ],
    "question_bridge": [
        ("old_question_id", "question", "question_id", "CASCADE"),
        ("new_question_id", "question", "question_id", "SET NULL"),
    ],
    "question_candidate": [("client_id", "clients", "id", "CASCADE")],
    "question_candidate_score": [("question_id", "question_candidate", "id", "CASCADE")],
    "question_deprecation": [
        ("question_id", "question", "question_id", "CASCADE"),
        ("replaced_by", "question", "question_id", "SET NULL"),
    ],
    "question_score": [("question_id", "question", "question_id", "CASCADE")],
    "scan_action": [("client_id", "clients", "id", "CASCADE")],
    "scan_analysis": [("client_id", "clients", "id", "CASCADE"), ("scan_id", "scans", "id", "CASCADE")],
    "scan_artifacts": [("client_id", "clients", "id", "CASCADE"), ("scan_id", "scans", "id", "CASCADE")],
    "scan_citation": [("client_id", "clients", "id", "CASCADE")],
    "scan_citations": [
        ("client_id", "clients", "id", "CASCADE"),
        ("scan_id", "scans", "id", "CASCADE"),
        ("source_profile_id", "source_profiles", "id", "SET NULL"),
    ],
    "scan_competitor": [("client_id", "clients", "id", "CASCADE")],
    "scan_manifest": [
        ("question_id", "question", "question_id", "CASCADE"),
        ("bank_version_id", "question_bank_version", "bank_version_id", "CASCADE"),
    ],
    "scan_metric": [("client_id", "clients", "id", "CASCADE")],
    "scan_question_result": [("client_id", "clients", "id", "CASCADE")],
    "scan_results": [("client_id", "clients", "id", "CASCADE"), ("scan_id", "scans", "id", "CASCADE")],
    "scan_runs": [("client_id", "clients", "id", "CASCADE")],
    "scans": [("client_id", "clients", "id", "CASCADE")],
    "source_profiles": [("client_id", "clients", "id", "CASCADE")],
}


def _existing_fk_name(inspector, table: str, column: str) -> str | None:
    """Real name of the single-column FK currently constraining (table, column).

    Returns the actual constraint name (PostgreSQL) or None when the dialect
    reflects FKs anonymously (SQLite).
    """
    for fk in inspector.get_foreign_keys(table):
        if fk.get("constrained_columns") == [column]:
            return fk.get("name")
    return None


def _rewrite(ondelete_for) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    # Resolve every FK's real name up front, before any DDL runs. On SQLite the
    # reflected name is None, so fall back to the naming_convention name that
    # batch mode assigns during the recreate.
    drop_names = {
        table: {
            col: (_existing_fk_name(inspector, table, col) or f"fk_{table}_{col}")
            for col, *_ in fks
        }
        for table, fks in POLICY.items()
    }
    for table, fks in POLICY.items():
        with op.batch_alter_table(table, schema=None, naming_convention=NAMING) as batch:
            for col, _ref_t, _ref_c, _od in fks:
                batch.drop_constraint(drop_names[table][col], type_="foreignkey")
            for col, ref_t, ref_c, od in fks:
                batch.create_foreign_key(
                    f"fk_{table}_{col}", ref_t, [col], [ref_c], ondelete=ondelete_for(od)
                )


def upgrade() -> None:
    _rewrite(lambda od: od)


def downgrade() -> None:
    # Restore NO ACTION (no ondelete) everywhere.
    _rewrite(lambda od: None)
