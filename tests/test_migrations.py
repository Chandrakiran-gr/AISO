import tempfile
import re
import unittest
from pathlib import Path
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from api.database import Base

MIGRATIONS_DIR = Path("migrations/versions")
PHASE13_TABLES = (
    "methodology_version_set",
    "scan_runs",
    "scan_progress",
    "samples",
    "scan_steps",
    "idempotency_keys",
    "cost_ledger",
    "scan_provenance",
    "sample",
    "classification",
    "avs_computation",
    "audit_event",
)
QUESTION_BANK_TABLES = (
    "question_candidate_score",
    "question_bank_version",
    "question",
    "question_score",
    "question_bank_membership",
    "scan_manifest",
    "question_bridge",
    "question_deprecation",
)
PHASE13_CLIENT_COLUMNS = {
    "tier",
    "cost_budget_default_usd",
    "byok",
    "byok_keys",
    "owned_domains",
    "competitor_domains",
}


def _alembic_config(db_path: Path) -> Config:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    return config


class AlembicMigrationTests(unittest.TestCase):
    def test_upgrade_head_creates_initial_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "aiso.db"
            with patch.dict("os.environ", {"DATABASE_URL": f"sqlite:///{db_path}"}):
                command.upgrade(_alembic_config(db_path), "head")

            engine = create_engine(f"sqlite:///{db_path}")
            try:
                with engine.connect() as connection:
                    inspector = inspect(connection)

                    self.assertIn("users", inspector.get_table_names())
                    self.assertIn("scan_artifacts", inspector.get_table_names())
                    self.assertIn("scan_analysis", inspector.get_table_names())
                    self.assertIn("scan_citations", inspector.get_table_names())
                    self.assertIn("client_contexts", inspector.get_table_names())
                    self.assertIn("conversations", inspector.get_table_names())
                    self.assertIn("messages", inspector.get_table_names())
                    self.assertIn("content_drafts", inspector.get_table_names())
                    self.assertIn("assistant_rate_limit_events", inspector.get_table_names())
                    self.assertIn("business_profile", inspector.get_table_names())
                    self.assertIn("methodology_prompt_version", inspector.get_table_names())
                    self.assertIn("question_candidate", inspector.get_table_names())
                    for table_name in QUESTION_BANK_TABLES:
                        self.assertIn(table_name, inspector.get_table_names())
                    candidate_score_columns = {
                        column["name"] for column in inspector.get_columns("question_candidate_score")
                    }
                    self.assertIn("d1_buyer_plausibility", candidate_score_columns)
                    bank_score_columns = {
                        column["name"] for column in inspector.get_columns("question_score")
                    }
                    self.assertIn("commercial_prox", bank_score_columns)
                    for table_name in PHASE13_TABLES:
                        self.assertIn(table_name, inspector.get_table_names())
                    self.assertIn("alembic_version", inspector.get_table_names())
                    client_columns = {
                        column["name"] for column in inspector.get_columns("clients")
                    }
                    self.assertTrue(PHASE13_CLIENT_COLUMNS.issubset(client_columns))
                    action_columns = {
                        column["name"] for column in inspector.get_columns("actions")
                    }
                    self.assertIn("evidence_json", action_columns)
                    conversation_columns = {
                        column["name"] for column in inspector.get_columns("conversations")
                    }
                    self.assertIn("summary_json", conversation_columns)
            finally:
                engine.dispose()

    def test_upgrade_head_adopts_existing_create_all_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "aiso.db"
            engine = create_engine(f"sqlite:///{db_path}")
            Base.metadata.create_all(engine)

            with patch.dict("os.environ", {"DATABASE_URL": f"sqlite:///{db_path}"}):
                command.upgrade(_alembic_config(db_path), "head")

            try:
                with engine.connect() as connection:
                    inspector = inspect(connection)
                    self.assertIn("alembic_version", inspector.get_table_names())
                    self.assertIn(
                        "ix_users_email",
                        {index["name"] for index in inspector.get_indexes("users")},
                    )
                    action_columns = {
                        column["name"] for column in inspector.get_columns("actions")
                    }
                    self.assertIn("action_key", action_columns)
                    self.assertIn("client_contexts", inspector.get_table_names())
                    self.assertIn("conversations", inspector.get_table_names())
                    self.assertIn("messages", inspector.get_table_names())
                    self.assertIn("content_drafts", inspector.get_table_names())
                    self.assertIn("assistant_rate_limit_events", inspector.get_table_names())
                    self.assertIn("business_profile", inspector.get_table_names())
                    self.assertIn("methodology_prompt_version", inspector.get_table_names())
                    self.assertIn("question_candidate", inspector.get_table_names())
                    for table_name in QUESTION_BANK_TABLES:
                        self.assertIn(table_name, inspector.get_table_names())
                    candidate_score_columns = {
                        column["name"] for column in inspector.get_columns("question_candidate_score")
                    }
                    self.assertIn("d1_buyer_plausibility", candidate_score_columns)
                    bank_score_columns = {
                        column["name"] for column in inspector.get_columns("question_score")
                    }
                    self.assertIn("commercial_prox", bank_score_columns)
                    for table_name in PHASE13_TABLES:
                        self.assertIn(table_name, inspector.get_table_names())
                    client_columns = {
                        column["name"] for column in inspector.get_columns("clients")
                    }
                    self.assertTrue(PHASE13_CLIENT_COLUMNS.issubset(client_columns))
                    conversation_columns = {
                        column["name"] for column in inspector.get_columns("conversations")
                    }
                    self.assertIn("summary_json", conversation_columns)
            finally:
                engine.dispose()

    def test_boolean_defaults_are_postgres_safe(self):
        unsafe_boolean_default = re.compile(
            r"sa\.Column\([^)]*sa\.Boolean\(\)[^)]*server_default=sa\.text\([\"'][01][\"']\)",
            re.DOTALL,
        )
        offenders: list[str] = []

        for migration_path in MIGRATIONS_DIR.glob("*.py"):
            source = migration_path.read_text(encoding="utf-8")
            if "sa.Boolean" not in source:
                continue
            if unsafe_boolean_default.search(source):
                offenders.append(str(migration_path))

        self.assertEqual(
            [],
            offenders,
            "Boolean server defaults must use sa.false()/sa.true(), not integer text defaults, so PostgreSQL migrations work.",
        )


if __name__ == "__main__":
    unittest.main()
