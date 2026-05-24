"""Add canonical question-bank tables and preserve Phase 12 candidate scores.

Revision ID: 20260524_0015
Revises: 20260524_0014
Create Date: 2026-05-24
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260524_0015"
down_revision = "20260524_0014"
branch_labels = None
depends_on = None


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


def upgrade() -> None:
    if (
        _table_exists("question_score")
        and _has_column("question_score", "d1_buyer_plausibility")
        and not _table_exists("question_candidate_score")
    ):
        op.rename_table("question_score", "question_candidate_score")

    if not _table_exists("question_bank_version"):
        op.create_table(
            "question_bank_version",
            sa.Column("bank_version_id", sa.String(), primary_key=True),
            sa.Column("client_id", sa.String(), nullable=False),
            sa.Column("avs_version", sa.Text(), nullable=False),
            sa.Column("effective_from", sa.DateTime(), nullable=False),
            sa.Column("effective_to", sa.DateTime(), nullable=True),
            sa.Column("n_core", sa.Integer(), nullable=False),
            sa.Column("n_tail", sa.Integer(), nullable=False),
            sa.Column("n_total", sa.Integer(), nullable=False),
            sa.Column("rotation_reason", sa.Text(), nullable=True),
            sa.Column("parent_version_id", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["client_id"], ["clients.id"]),
            sa.ForeignKeyConstraint(["parent_version_id"], ["question_bank_version.bank_version_id"]),
        )

    if not _table_exists("question"):
        op.create_table(
            "question",
            sa.Column("question_id", sa.String(), primary_key=True),
            sa.Column("client_id", sa.String(), nullable=False),
            sa.Column("text", sa.Text(), nullable=False),
            sa.Column("text_hash", sa.Text(), nullable=False),
            sa.Column("journey_stage", sa.Text(), nullable=False),
            sa.Column("brand_frame", sa.Text(), nullable=False),
            sa.Column("locality", sa.Text(), nullable=False, server_default="L0"),
            sa.Column("persona_id", sa.String(), nullable=True),
            sa.Column("source", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.CheckConstraint(
                "journey_stage IN ('J1','J2','J3','J4','J5','J6')",
                name="ck_question_journey_stage",
            ),
            sa.CheckConstraint(
                "brand_frame IN ('U','B','C')",
                name="ck_question_brand_frame",
            ),
            sa.CheckConstraint(
                "source IN ('generated','manual','imported')",
                name="ck_question_source",
            ),
            sa.ForeignKeyConstraint(["client_id"], ["clients.id"]),
            sa.UniqueConstraint("client_id", "text_hash", name="uq_question_client_text_hash"),
        )

    if not _table_exists("question_score"):
        op.create_table(
            "question_score",
            sa.Column("question_id", sa.String(), primary_key=True),
            sa.Column("scored_at", sa.DateTime(), primary_key=True),
            sa.Column("journey_match", sa.Numeric(5, 3), nullable=True),
            sa.Column("brand_frame_match", sa.Numeric(5, 3), nullable=True),
            sa.Column("demand_signal", sa.Numeric(5, 3), nullable=True),
            sa.Column("commercial_prox", sa.Numeric(5, 3), nullable=True),
            sa.Column("buyer_plausibility", sa.Numeric(5, 3), nullable=True),
            sa.Column("scope_calibration", sa.Numeric(5, 3), nullable=True),
            sa.Column("objective_alignment", sa.Numeric(5, 3), nullable=True),
            sa.Column("construct_coverage", sa.Numeric(5, 3), nullable=True),
            sa.Column("provider_diff", sa.Numeric(5, 3), nullable=True),
            sa.Column("goodhart_resistance", sa.Numeric(5, 3), nullable=True),
            sa.Column("answer_stability", sa.Numeric(5, 3), nullable=True),
            sa.Column("composite", sa.Numeric(5, 3), nullable=False),
            sa.Column("scorer_version", sa.Text(), nullable=False),
            sa.ForeignKeyConstraint(["question_id"], ["question.question_id"]),
        )

    if not _table_exists("question_bank_membership"):
        op.create_table(
            "question_bank_membership",
            sa.Column("bank_version_id", sa.String(), primary_key=True),
            sa.Column("question_id", sa.String(), primary_key=True),
            sa.Column("state", sa.Text(), nullable=False),
            sa.Column("weight", sa.Numeric(6, 4), nullable=False, server_default="1.0"),
            sa.Column("entered_at", sa.DateTime(), nullable=False),
            sa.CheckConstraint(
                "state IN ('FROZEN','TAIL','BRIDGE_IN','BRIDGE_OUT')",
                name="ck_question_bank_membership_state",
            ),
            sa.ForeignKeyConstraint(["bank_version_id"], ["question_bank_version.bank_version_id"]),
            sa.ForeignKeyConstraint(["question_id"], ["question.question_id"]),
        )

    if not _table_exists("scan_manifest"):
        op.create_table(
            "scan_manifest",
            sa.Column("scan_id", sa.String(), primary_key=True),
            sa.Column("question_id", sa.String(), primary_key=True),
            sa.Column("bank_version_id", sa.String(), nullable=False),
            sa.Column("weight_at_scan", sa.Numeric(6, 4), nullable=False),
            sa.Column("state_at_scan", sa.Text(), nullable=False),
            sa.ForeignKeyConstraint(["question_id"], ["question.question_id"]),
            sa.ForeignKeyConstraint(["bank_version_id"], ["question_bank_version.bank_version_id"]),
        )

    if not _table_exists("question_bridge"):
        op.create_table(
            "question_bridge",
            sa.Column("bridge_id", sa.String(), primary_key=True),
            sa.Column("old_question_id", sa.String(), nullable=False),
            sa.Column("new_question_id", sa.String(), nullable=True),
            sa.Column("bridge_scan_id", sa.String(), nullable=True),
            sa.Column("equivalence_score", sa.Numeric(5, 3), nullable=True),
            sa.Column("bridge_method", sa.Text(), nullable=False),
            sa.Column("avs_version_pre", sa.Text(), nullable=True),
            sa.Column("avs_version_post", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.CheckConstraint(
                "bridge_method IN ('parallel_measurement','rasch_latent','none')",
                name="ck_question_bridge_method",
            ),
            sa.ForeignKeyConstraint(["old_question_id"], ["question.question_id"]),
            sa.ForeignKeyConstraint(["new_question_id"], ["question.question_id"]),
        )

    if not _table_exists("question_deprecation"):
        op.create_table(
            "question_deprecation",
            sa.Column("question_id", sa.String(), primary_key=True),
            sa.Column("deprecated_at", sa.DateTime(), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("replaced_by", sa.String(), nullable=True),
            sa.ForeignKeyConstraint(["question_id"], ["question.question_id"]),
            sa.ForeignKeyConstraint(["replaced_by"], ["question.question_id"]),
        )


def downgrade() -> None:
    for table_name in (
        "question_deprecation",
        "question_bridge",
        "scan_manifest",
        "question_bank_membership",
        "question_score",
        "question",
        "question_bank_version",
    ):
        if _table_exists(table_name):
            op.drop_table(table_name)

    if _table_exists("question_candidate_score") and not _table_exists("question_score"):
        op.rename_table("question_candidate_score", "question_score")
