"""Create upstream-pipeline profile and question tables.

Revision ID: 20260522_0012
Revises: 20260520_0011
Create Date: 2026-05-22
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260522_0012"
down_revision = "20260520_0011"
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


def upgrade() -> None:
    if not _table_exists("business_profile"):
        op.create_table(
            "business_profile",
            sa.Column("client_id", sa.String(), sa.ForeignKey("clients.id"), primary_key=True),
            sa.Column("vertical", sa.String(), nullable=False),
            sa.Column("objective", sa.String(), nullable=False),
            sa.Column("category", sa.String(), nullable=False),
            sa.Column("icp", _json_type(), nullable=False),
            sa.Column("geographic_scope", _json_type(), nullable=False),
            sa.Column("competitors", _text_array_type(), nullable=False),
            sa.Column("personas", _json_type(), nullable=False),
            sa.Column("crawl_artifacts", _json_type(), nullable=False),
            sa.Column("onboarding_completed_at", sa.DateTime(), nullable=True),
            sa.Column("founder_reviewed_at", sa.DateTime(), nullable=True),
            sa.Column("floor_met", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.CheckConstraint(
                "vertical IN ("
                "'b2b_saas','b2b_services','local_services','ecommerce',"
                "'regulated_healthcare','regulated_legal','regulated_financial',"
                "'consumer_brand','marketplace','agency','enterprise'"
                ")",
                name="ck_business_profile_vertical",
            ),
            sa.CheckConstraint(
                "objective IN ("
                "'awareness','consideration','preference',"
                "'reputation_defense','competitive_intelligence'"
                ")",
                name="ck_business_profile_objective",
            ),
        )

    if not _table_exists("question_candidate"):
        op.create_table(
            "question_candidate",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("client_id", sa.String(), sa.ForeignKey("clients.id"), nullable=False),
            sa.Column("scan_run_id", sa.String(), nullable=True),
            sa.Column("text", sa.Text(), nullable=False),
            sa.Column("text_hash", sa.String(), nullable=False),
            sa.Column("journey_stage", sa.String(), nullable=False),
            sa.Column("brand_frame", sa.String(), nullable=False),
            sa.Column("intent_class", sa.String(), nullable=False),
            sa.Column("persona", sa.String(), nullable=True),
            sa.Column("locality", sa.String(), nullable=True),
            sa.Column("rationale", sa.Text(), nullable=True),
            sa.Column("realism_score", sa.Numeric(5, 3), nullable=True),
            sa.Column("selected", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("generator_version", sa.String(), nullable=False),
            sa.Column("realism_filter_version", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint(
                "client_id",
                "text_hash",
                "generator_version",
                name="uq_question_candidate_client_hash_generator",
            ),
        )
        op.create_index("ix_question_candidate_client", "question_candidate", ["client_id"])
        op.create_index("ix_question_candidate_scan_run", "question_candidate", ["scan_run_id"])

    if not _table_exists("question_score"):
        op.create_table(
            "question_score",
            sa.Column("question_id", sa.String(), sa.ForeignKey("question_candidate.id"), primary_key=True),
            sa.Column("scored_at", sa.DateTime(), primary_key=True),
            sa.Column("d1_buyer_plausibility", sa.Numeric(5, 3), nullable=True),
            sa.Column("d2_commercial_proximity", sa.Numeric(5, 3), nullable=True),
            sa.Column("d3_cognitive_answerability", sa.Numeric(5, 3), nullable=True),
            sa.Column("d4_diagnostic_power", sa.Numeric(5, 3), nullable=True),
            sa.Column("d5_statistical_identifiability", sa.Numeric(5, 3), nullable=True),
            sa.Column("weighted_score", sa.Numeric(5, 3), nullable=False),
            sa.Column("rationale", sa.Text(), nullable=True),
            sa.Column("scorer_version", sa.String(), nullable=False),
        )


def downgrade() -> None:
    for table in ("question_score", "question_candidate", "business_profile"):
        if _table_exists(table):
            op.drop_table(table)
