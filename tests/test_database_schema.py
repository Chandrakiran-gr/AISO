import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from api import database as database_module
from api.database import (
    Base,
    Client,
    Scan,
    ScanAnalysis,
    ScanArtifact,
    ScanCitation,
    ScanResult,
    User,
)
from api.storage import (
    build_scan_artifact_path,
    describe_local_artifact,
    safe_storage_part,
)
from full_stack.scan_metrics import persist_collect_csv_results


class DatabaseSchemaTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def test_schema_contains_artifacts_analysis_and_citations(self):
        inspector = inspect(self.engine)

        self.assertIn("scan_artifacts", inspector.get_table_names())
        self.assertIn("scan_analysis", inspector.get_table_names())
        self.assertIn("scan_citations", inspector.get_table_names())

        artifact_columns = {
            column["name"] for column in inspector.get_columns("scan_artifacts")
        }
        self.assertTrue(
            {
                "artifact_type",
                "file_format",
                "storage_backend",
                "storage_path",
                "sha256",
            }.issubset(artifact_columns)
        )

        citation_columns = {
            column["name"] for column in inspector.get_columns("scan_citations")
        }
        self.assertTrue(
            {
                "provider",
                "question",
                "answer_excerpt",
                "citation_url",
                "source_domain",
            }.issubset(citation_columns)
        )

    def test_persists_scan_artifact_analysis_and_citation_rows(self):
        session = self.Session()
        try:
            session.add(
                User(id="user-1", email="founder@example.com", provider="google")
            )
            session.add(
                Client(
                    id="client-1",
                    user_id="user-1",
                    name="AISO Demo",
                    url="https://example.com",
                )
            )
            session.add(Scan(id="scan-1", client_id="client-1", status="complete"))
            session.flush()

            session.add(
                ScanArtifact(
                    id="artifact-1",
                    client_id="client-1",
                    scan_id="scan-1",
                    artifact_type="collect_csv",
                    file_format="csv",
                    storage_backend="local",
                    storage_path="storage/clients/client-1/scans/scan-1/raw/responses.csv",
                    sha256="0" * 64,
                )
            )
            session.add(
                ScanAnalysis(
                    id="analysis-1",
                    client_id="client-1",
                    scan_id="scan-1",
                    analysis_type="visibility_summary",
                    summary="AISO is visible in most direct-brand prompts.",
                    recommendations_json=json.dumps(
                        ["Improve competitor comparison pages."]
                    ),
                )
            )
            session.add(
                ScanCitation(
                    id="citation-1",
                    client_id="client-1",
                    scan_id="scan-1",
                    provider="perplexity",
                    citation_url="https://example.com/source",
                    source_domain="example.com",
                    source_rank=1,
                )
            )
            session.commit()

            self.assertEqual(session.query(ScanArtifact).count(), 1)
            self.assertEqual(session.query(ScanAnalysis).count(), 1)
            self.assertEqual(session.query(ScanCitation).count(), 1)
        finally:
            session.close()

    def test_scan_metrics_persistence_registers_collect_csv_artifact(self):
        session = self.Session()
        try:
            session.add(
                User(id="user-1", email="founder@example.com", provider="google")
            )
            session.add(
                Client(
                    id="client-1",
                    user_id="user-1",
                    name="AISO Demo",
                    url="https://example.com",
                )
            )
            session.add(Scan(id="scan-1", client_id="client-1", status="complete"))
            session.commit()
        finally:
            session.close()

        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            client_folder = folder / "client"
            client_folder.mkdir()
            (client_folder / "client_profile.json").write_text(
                json.dumps(
                    {
                        "display_name": "AISO Demo",
                        "competitors": ["SearchCo"],
                    }
                ),
                encoding="utf-8",
            )
            csv_path = folder / "responses.csv"
            csv_path.write_text(
                "question,group,response_openai,error_openai\n"
                "best ai visibility tool,G1,AISO Demo is a strong option,\n",
                encoding="utf-8",
            )

            with patch.object(database_module, "SessionLocal", self.Session):
                persisted = persist_collect_csv_results(
                    csv_path,
                    scan_id="scan-1",
                    client_id="client-1",
                    client_folder=client_folder,
                )

        session = self.Session()
        try:
            self.assertEqual(len(persisted), 1)
            self.assertEqual(session.query(ScanResult).count(), 1)
            artifact = session.query(ScanArtifact).one()
            self.assertEqual(artifact.artifact_type, "collect_csv")
            self.assertEqual(artifact.file_format, "csv")
            self.assertEqual(artifact.storage_backend, "local")
            self.assertEqual(len(artifact.sha256), 64)
            self.assertEqual(
                json.loads(artifact.metadata_json)["source"],
                "full_stack.collect",
            )
        finally:
            session.close()


class StorageHelperTests(unittest.TestCase):
    def test_builds_safe_scan_artifact_paths(self):
        path = build_scan_artifact_path(
            "../client",
            "scan/123",
            "../responses.csv",
            stage="raw",
        )

        self.assertNotIn("..", path.as_posix())
        self.assertTrue(
            path.as_posix().endswith("/client/scans/scan-123/raw/responses.csv")
        )

    def test_describes_local_artifact_without_storing_file_contents(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "responses.csv"
            csv_path.write_text("question,response\nhello,world\n", encoding="utf-8")

            metadata = describe_local_artifact(
                csv_path,
                artifact_type="collect_csv",
                metadata={"source": "test"},
            )

        self.assertEqual(metadata["artifact_type"], "collect_csv")
        self.assertEqual(metadata["file_format"], "csv")
        self.assertEqual(metadata["storage_backend"], "local")
        self.assertEqual(metadata["size_bytes"], 30)
        self.assertEqual(len(metadata["sha256"]), 64)
        self.assertEqual(json.loads(metadata["metadata_json"]), {"source": "test"})

    def test_rejects_empty_storage_segments(self):
        with self.assertRaises(ValueError):
            safe_storage_part("../")


if __name__ == "__main__":
    unittest.main()
