"""Add scan-engine methodology, execution, provenance, and audit tables.

Revision ID: 20260524_0014
Revises: 20260522_0013
Create Date: 2026-05-24
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260524_0014"
down_revision = "20260522_0013"
branch_labels = None
depends_on = None


def _json_type():
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def _text_array_type():
    return sa.JSON().with_variant(postgresql.ARRAY(sa.Text()), "postgresql")


def _table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def _has_column(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if table_name not in inspector.get_table_names():
        return False
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def _has_index(table_name: str, index_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if table_name not in inspector.get_table_names():
        return False
    return any(index["name"] == index_name for index in inspector.get_indexes(table_name))


def _create_index(
    index_name: str,
    table_name: str,
    columns: list[str],
    *,
    unique: bool = False,
) -> None:
    if not _has_index(table_name, index_name):
        op.create_index(index_name, table_name, columns, unique=unique)


def _extend_clients() -> None:
    if not _has_column("clients", "tier"):
        op.add_column(
            "clients",
            sa.Column("tier", sa.String(), nullable=False, server_default="free"),
        )
    if not _has_column("clients", "cost_budget_default_usd"):
        op.add_column(
            "clients",
            sa.Column(
                "cost_budget_default_usd",
                sa.Numeric(10, 2),
                nullable=False,
                server_default="5.00",
            ),
        )
    if not _has_column("clients", "byok"):
        op.add_column(
            "clients",
            sa.Column("byok", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    if not _has_column("clients", "byok_keys"):
        op.add_column("clients", sa.Column("byok_keys", _json_type(), nullable=True))
    if not _has_column("clients", "owned_domains"):
        op.add_column("clients", sa.Column("owned_domains", _text_array_type(), nullable=True))
    if not _has_column("clients", "competitor_domains"):
        op.add_column(
            "clients",
            sa.Column("competitor_domains", _text_array_type(), nullable=True),
        )


def upgrade() -> None:
    _extend_clients()

    if not _table_exists("methodology_version_set"):
        op.create_table(
            "methodology_version_set",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("label", sa.Text(), nullable=False, unique=True),
            sa.Column("avs_formula_version", sa.Text(), nullable=False),
            sa.Column("bank_version", sa.Text(), nullable=False),
            sa.Column("stance_classifier_version", sa.Text(), nullable=False),
            sa.Column("source_classifier_version", sa.Text(), nullable=False),
            sa.Column("sampling_config_version", sa.Text(), nullable=False),
            sa.Column("provider_model_snapshot_version", sa.Text(), nullable=False),
            sa.Column("valid_from", sa.DateTime(), nullable=False),
            sa.Column("valid_to", sa.DateTime(), nullable=True),
            sa.Column("sys_period", sa.Text(), nullable=False),
            sa.Column("spec_document_url", sa.Text(), nullable=False),
            sa.Column("spec_document_hash", sa.LargeBinary(), nullable=False),
            sa.Column("change_memo_url", sa.Text(), nullable=True),
            sa.Column("approved_by", sa.Text(), nullable=False),
            sa.Column("approved_at", sa.DateTime(), nullable=False),
            sa.Column("shadow_run_started_at", sa.DateTime(), nullable=True),
            sa.Column("shadow_run_ended_at", sa.DateTime(), nullable=True),
            sa.Column("superseded_by", sa.String(), nullable=True),
            sa.ForeignKeyConstraint(["superseded_by"], ["methodology_version_set.id"]),
        )
    _create_index(
        "ix_methodology_version_set_validity",
        "methodology_version_set",
        ["valid_from", "valid_to"],
    )

    if not _table_exists("scan_runs"):
        op.create_table(
            "scan_runs",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("client_id", sa.String(), nullable=False),
            sa.Column("idempotency_key", sa.Text(), nullable=False),
            sa.Column("methodology_version", sa.Text(), nullable=False),
            sa.Column("methodology_version_set_id", sa.String(), nullable=True),
            sa.Column("status", sa.Text(), nullable=False),
            sa.Column("completeness", sa.Text(), nullable=True),
            sa.Column("cost_budget_usd", sa.Numeric(10, 4), nullable=False),
            sa.Column(
                "cost_spent_usd",
                sa.Numeric(10, 4),
                nullable=False,
                server_default="0",
            ),
            sa.Column("latency_class", sa.Text(), nullable=False),
            sa.Column("enqueued_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.Column("error_summary", _json_type(), nullable=True),
            sa.ForeignKeyConstraint(["client_id"], ["clients.id"]),
            sa.ForeignKeyConstraint(
                ["methodology_version_set_id"],
                ["methodology_version_set.id"],
            ),
            sa.UniqueConstraint(
                "client_id",
                "idempotency_key",
                name="uq_scan_runs_client_idempotency",
            ),
        )
    _create_index("idx_scan_runs_client_status", "scan_runs", ["client_id", "status"])

    if not _table_exists("scan_progress"):
        op.create_table(
            "scan_progress",
            sa.Column("scan_run_id", sa.String(), primary_key=True),
            sa.Column("status", sa.Text(), nullable=False),
            sa.Column("stage", sa.Text(), nullable=False, server_default="queued"),
            sa.Column("total_calls", sa.Integer(), nullable=False),
            sa.Column("completed_calls", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("failed_calls", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("per_provider", _json_type(), nullable=False),
            sa.Column("eta_seconds", sa.Integer(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["scan_run_id"], ["scan_runs.id"], ondelete="CASCADE"),
        )

    if not _table_exists("samples"):
        op.create_table(
            "samples",
            sa.Column("scan_run_id", sa.String(), primary_key=True),
            sa.Column("question_id", sa.Text(), primary_key=True),
            sa.Column("provider", sa.Text(), primary_key=True),
            sa.Column("sample_index", sa.Integer(), primary_key=True),
            sa.Column("seed", sa.BigInteger(), nullable=False),
            sa.Column("raw_response", _json_type(), nullable=True),
            sa.Column("system_fingerprint", sa.Text(), nullable=True),
            sa.Column("cost_usd", sa.Numeric(10, 6), nullable=False, server_default="0"),
            sa.Column("provider_idem_key", sa.Text(), nullable=False),
            sa.Column("classified_stance", sa.Text(), nullable=True),
            sa.Column("classified_source", sa.Text(), nullable=True),
            sa.Column("failure_reason", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["scan_run_id"], ["scan_runs.id"], ondelete="CASCADE"),
        )

    if not _table_exists("scan_steps"):
        op.create_table(
            "scan_steps",
            sa.Column("scan_run_id", sa.String(), primary_key=True),
            sa.Column("step_id", sa.Text(), primary_key=True),
            sa.Column("event", sa.Text(), primary_key=True),
            sa.Column("attempt", sa.Integer(), primary_key=True, server_default="1"),
            sa.Column("payload", _json_type(), nullable=True),
            sa.Column("occurred_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.CheckConstraint(
                "event IN ('started','succeeded','failed','compensated')",
                name="ck_scan_steps_event",
            ),
            sa.ForeignKeyConstraint(["scan_run_id"], ["scan_runs.id"], ondelete="CASCADE"),
        )
    _create_index("idx_scan_steps_at", "scan_steps", ["scan_run_id", "occurred_at"])

    if not _table_exists("idempotency_keys"):
        op.create_table(
            "idempotency_keys",
            sa.Column("key", sa.Text(), primary_key=True),
            sa.Column("scope", sa.Text(), nullable=False),
            sa.Column("request_hash", sa.Text(), nullable=False),
            sa.Column("response_status", sa.Integer(), nullable=True),
            sa.Column("response_body", _json_type(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("locked_at", sa.DateTime(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
        )
    _create_index("idx_idempotency_gc", "idempotency_keys", ["created_at"])

    if not _table_exists("cost_ledger"):
        op.create_table(
            "cost_ledger",
            sa.Column("scan_run_id", sa.String(), primary_key=True),
            sa.Column("provider", sa.Text(), primary_key=True),
            sa.Column("spent_usd", sa.Numeric(10, 6), nullable=False, server_default="0"),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["scan_run_id"], ["scan_runs.id"], ondelete="CASCADE"),
        )

    if not _table_exists("scan_provenance"):
        op.create_table(
            "scan_provenance",
            sa.Column("scan_id", sa.String(), primary_key=True),
            sa.Column("client_id", sa.String(), nullable=False),
            sa.Column("methodology_version_set_id", sa.String(), nullable=False),
            sa.Column("scan_started_at", sa.DateTime(), nullable=False),
            sa.Column("scan_completed_at", sa.DateTime(), nullable=False),
            sa.Column("question_count", sa.Integer(), nullable=False),
            sa.Column("sample_count", sa.Integer(), nullable=False),
            sa.Column("raw_response_archive_url", sa.Text(), nullable=False),
            sa.Column("raw_response_archive_hash", sa.LargeBinary(), nullable=False),
            sa.Column("scan_manifest_hash", sa.LargeBinary(), nullable=False),
            sa.Column("git_sha", sa.Text(), nullable=False),
            sa.Column("computed_by_host", sa.Text(), nullable=False),
            sa.Column("prev_provenance_hash", sa.LargeBinary(), nullable=True),
            sa.Column("this_provenance_hash", sa.LargeBinary(), nullable=False),
            sa.Column("signed_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["scan_id"], ["scan_runs.id"]),
            sa.ForeignKeyConstraint(["client_id"], ["clients.id"]),
            sa.ForeignKeyConstraint(
                ["methodology_version_set_id"],
                ["methodology_version_set.id"],
            ),
        )
    _create_index("ix_scan_provenance_client", "scan_provenance", ["client_id"])

    if not _table_exists("sample"):
        op.create_table(
            "sample",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("scan_id", sa.String(), nullable=False),
            sa.Column("question_id", sa.String(), nullable=False),
            sa.Column("provider", sa.Text(), nullable=False),
            sa.Column("provider_model", sa.Text(), nullable=False),
            sa.Column("system_fingerprint", sa.Text(), nullable=True),
            sa.Column("temperature", sa.Numeric(4, 3), nullable=False),
            sa.Column("seed", sa.BigInteger(), nullable=False),
            sa.Column("sample_index", sa.Integer(), nullable=False),
            sa.Column("request_payload_hash", sa.LargeBinary(), nullable=False),
            sa.Column("raw_response_text", sa.Text(), nullable=False),
            sa.Column("raw_response_hash", sa.LargeBinary(), nullable=False),
            sa.Column("response_received_at", sa.DateTime(), nullable=False),
            sa.Column("latency_ms", sa.Integer(), nullable=True),
            sa.ForeignKeyConstraint(["scan_id"], ["scan_provenance.scan_id"]),
            sa.UniqueConstraint(
                "scan_id",
                "question_id",
                "provider",
                "sample_index",
                name="uq_sample_scan_question_provider_index",
            ),
        )
    _create_index("ix_sample_scan_provider", "sample", ["scan_id", "provider"])

    if not _table_exists("classification"):
        op.create_table(
            "classification",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("sample_id", sa.String(), nullable=False),
            sa.Column("classifier_type", sa.Text(), nullable=False),
            sa.Column("classifier_version", sa.Text(), nullable=False),
            sa.Column("classifier_model", sa.Text(), nullable=False),
            sa.Column("prompt_hash", sa.LargeBinary(), nullable=False),
            sa.Column("self_consistency_n", sa.Integer(), nullable=True),
            sa.Column("individual_judgments", _json_type(), nullable=True),
            sa.Column("consensus_value", sa.Text(), nullable=False),
            sa.Column("consensus_confidence", sa.Numeric(5, 4), nullable=True),
            sa.Column("judged_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["sample_id"], ["sample.id"]),
        )
    _create_index(
        "ix_classification_sample_type",
        "classification",
        ["sample_id", "classifier_type"],
    )

    if not _table_exists("avs_computation"):
        op.create_table(
            "avs_computation",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("scan_id", sa.String(), nullable=False),
            sa.Column("methodology_version_set_id", sa.String(), nullable=False),
            sa.Column("avs_value", sa.Numeric(6, 3), nullable=False),
            sa.Column("presence", sa.Numeric(6, 5), nullable=False),
            sa.Column("prominence", sa.Numeric(6, 5), nullable=False),
            sa.Column("positivity", sa.Numeric(6, 5), nullable=False),
            sa.Column("ci_lower_95", sa.Numeric(6, 3), nullable=False),
            sa.Column("ci_upper_95", sa.Numeric(6, 3), nullable=False),
            sa.Column("ci_method", sa.Text(), nullable=False),
            sa.Column("bootstrap_iterations", sa.Integer(), nullable=True),
            sa.Column("computed_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("computed_by_git_sha", sa.Text(), nullable=False),
            sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.ForeignKeyConstraint(["scan_id"], ["scan_provenance.scan_id"]),
            sa.ForeignKeyConstraint(
                ["methodology_version_set_id"],
                ["methodology_version_set.id"],
            ),
            sa.UniqueConstraint(
                "scan_id",
                "methodology_version_set_id",
                name="uq_avs_computation_scan_methodology",
            ),
        )
    _create_index(
        "ix_avs_computation_scan_primary",
        "avs_computation",
        ["scan_id", "is_primary"],
    )

    if not _table_exists("audit_event"):
        op.create_table(
            "audit_event",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("event_time", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("actor_type", sa.Text(), nullable=False),
            sa.Column("actor_id", sa.Text(), nullable=False),
            sa.Column("actor_session_id", sa.Text(), nullable=True),
            sa.Column("source_ip", sa.String(), nullable=True),
            sa.Column("user_agent", sa.Text(), nullable=True),
            sa.Column("action", sa.Text(), nullable=False),
            sa.Column("resource_type", sa.Text(), nullable=False),
            sa.Column("resource_id", sa.Text(), nullable=False),
            sa.Column("before_state", _json_type(), nullable=True),
            sa.Column("after_state", _json_type(), nullable=True),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("correlation_id", sa.String(), nullable=True),
            sa.Column("txid", sa.BigInteger(), nullable=False, server_default="0"),
            sa.Column("prev_event_hash", sa.LargeBinary(), nullable=True),
            sa.Column("event_hash", sa.LargeBinary(), nullable=False),
            sa.Column("hmac_key_version", sa.Integer(), nullable=False),
        )
    _create_index("idx_audit_event_resource", "audit_event", ["resource_type", "resource_id"])
    _create_index("idx_audit_event_actor", "audit_event", ["actor_type", "actor_id"])
    _create_index("idx_audit_event_correlation", "audit_event", ["correlation_id"])


def downgrade() -> None:
    for table_name in (
        "audit_event",
        "avs_computation",
        "classification",
        "sample",
        "scan_provenance",
        "cost_ledger",
        "idempotency_keys",
        "scan_steps",
        "samples",
        "scan_progress",
        "scan_runs",
        "methodology_version_set",
    ):
        if _table_exists(table_name):
            op.drop_table(table_name)

    for column_name in (
        "competitor_domains",
        "owned_domains",
        "byok_keys",
        "byok",
        "cost_budget_default_usd",
        "tier",
    ):
        if _has_column("clients", column_name):
            op.drop_column("clients", column_name)
