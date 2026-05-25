"""Add N-sampling metadata columns to execution sample tables.

Revision ID: 20260524_0016
Revises: 20260524_0015
Create Date: 2026-05-24
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260524_0016"
down_revision = "20260524_0015"
branch_labels = None
depends_on = None


def _json_type():
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def _json_server_default(value: str):
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        return sa.text(f"'{value}'::jsonb")
    return value


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


def _column_nullable(table_name: str, column_name: str) -> bool | None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if table_name not in inspector.get_table_names():
        return None
    for column in inspector.get_columns(table_name):
        if column["name"] == column_name:
            return bool(column["nullable"])
    return None


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    if _table_exists(table_name) and not _has_column(table_name, column.name):
        op.add_column(table_name, column)


def _alter_nullable_if_needed(
    table_name: str,
    column_name: str,
    *,
    existing_type: sa.types.TypeEngine,
    nullable: bool,
) -> None:
    current = _column_nullable(table_name, column_name)
    if current is None or current == nullable:
        return
    with op.batch_alter_table(table_name) as batch_op:
        batch_op.alter_column(column_name, existing_type=existing_type, nullable=nullable)


def upgrade() -> None:
    _add_column_if_missing(
        "scan_runs",
        sa.Column("providers", _json_type(), nullable=False, server_default=_json_server_default("[]")),
    )
    _add_column_if_missing(
        "samples",
        sa.Column("planned_provider_model", sa.Text(), nullable=False, server_default="unknown"),
    )
    _add_column_if_missing(
        "samples",
        sa.Column("provider_model", sa.Text(), nullable=True),
    )
    _add_column_if_missing(
        "samples",
        sa.Column("temperature", sa.Numeric(4, 3), nullable=False, server_default="0.700"),
    )
    _add_column_if_missing(
        "samples",
        sa.Column("top_p", sa.Numeric(4, 3), nullable=False, server_default="1.000"),
    )
    _add_column_if_missing(
        "samples",
        sa.Column("sample_plan_hash", sa.LargeBinary(), nullable=True),
    )
    _add_column_if_missing("samples", sa.Column("request_payload_hash", sa.LargeBinary(), nullable=True))
    _add_column_if_missing("samples", sa.Column("raw_response_text", sa.Text(), nullable=True))
    _add_column_if_missing("samples", sa.Column("raw_response_pointer", sa.Text(), nullable=True))
    _add_column_if_missing("samples", sa.Column("raw_response_hash", sa.LargeBinary(), nullable=True))
    _add_column_if_missing("samples", sa.Column("input_tokens", sa.Integer(), nullable=True))
    _add_column_if_missing("samples", sa.Column("output_tokens", sa.Integer(), nullable=True))
    _add_column_if_missing("samples", sa.Column("total_tokens", sa.Integer(), nullable=True))
    _add_column_if_missing("samples", sa.Column("response_received_at", sa.DateTime(), nullable=True))
    _add_column_if_missing("samples", sa.Column("latency_ms", sa.Integer(), nullable=True))
    _add_column_if_missing(
        "samples",
        sa.Column("methodology_version", sa.Text(), nullable=False, server_default=""),
    )
    _add_column_if_missing(
        "samples",
        sa.Column("cache_bust", _json_type(), nullable=False, server_default=_json_server_default("{}")),
    )
    _alter_nullable_if_needed("samples", "provider_model", existing_type=sa.Text(), nullable=True)
    _alter_nullable_if_needed("samples", "seed", existing_type=sa.BigInteger(), nullable=True)

    _add_column_if_missing(
        "sample",
        sa.Column("top_p", sa.Numeric(4, 3), nullable=False, server_default="1.000"),
    )
    _add_column_if_missing("sample", sa.Column("raw_response_pointer", sa.Text(), nullable=True))
    _add_column_if_missing("sample", sa.Column("input_tokens", sa.Integer(), nullable=True))
    _add_column_if_missing("sample", sa.Column("output_tokens", sa.Integer(), nullable=True))
    _add_column_if_missing("sample", sa.Column("total_tokens", sa.Integer(), nullable=True))
    _add_column_if_missing(
        "sample",
        sa.Column("methodology_version", sa.Text(), nullable=False, server_default=""),
    )
    _alter_nullable_if_needed("sample", "seed", existing_type=sa.BigInteger(), nullable=True)


def downgrade() -> None:
    # Phase 13 migrations are forward-only in local adoption tests; keep the
    # downgrade intentionally empty to avoid destructive column drops.
    pass
