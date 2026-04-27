import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from api.database import Base


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
                    self.assertIn("alembic_version", inspector.get_table_names())
                    action_columns = {
                        column["name"] for column in inspector.get_columns("actions")
                    }
                    self.assertIn("evidence_json", action_columns)
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
            finally:
                engine.dispose()


if __name__ == "__main__":
    unittest.main()
