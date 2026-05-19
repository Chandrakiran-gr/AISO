import json
import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from api import database as database_module
from api.database import (
    Action,
    Base,
    Client,
    ClientContext,
    Conversation,
    Message,
    Scan,
    ScanAnalysis,
    ScanArtifact,
    ScanCitation,
    ScanResult,
    SourceProfile,
    User,
)
from api.storage import (
    ArtifactStorageError,
    OneDriveUploadResult,
    build_scan_artifact_path,
    client_artifact_slug,
    describe_configured_artifact,
    describe_local_artifact,
    onedrive_remote_dir,
    safe_storage_part,
)
from full_stack.scan_metrics import persist_collect_csv_results


class DatabaseSchemaTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        self.engine.dispose()

    def test_schema_contains_artifacts_analysis_and_citations(self):
        with self.engine.connect() as connection:
            inspector = inspect(connection)

            self.assertIn("scan_artifacts", inspector.get_table_names())
            self.assertIn("scan_analysis", inspector.get_table_names())
            self.assertIn("scan_citations", inspector.get_table_names())
            self.assertIn("source_profiles", inspector.get_table_names())
            self.assertIn("client_contexts", inspector.get_table_names())
            self.assertIn("conversations", inspector.get_table_names())
            self.assertIn("messages", inspector.get_table_names())
            self.assertIn("content_drafts", inspector.get_table_names())

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

            user_columns = {
                column["name"] for column in inspector.get_columns("users")
            }
            self.assertTrue(
                {
                    "plan_tier",
                    "account_role",
                }.issubset(user_columns)
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
                    "canonical_url",
                    "source_type",
                    "owner_type",
                    "action_role",
                }.issubset(citation_columns)
            )

            source_columns = {
                column["name"] for column in inspector.get_columns("source_profiles")
            }
            self.assertTrue(
                {
                    "canonical_url",
                    "source_domain",
                    "source_type",
                    "owner_type",
                    "action_role",
                    "influence_score",
                    "actionability_score",
                }.issubset(source_columns)
            )

            action_columns = {
                column["name"] for column in inspector.get_columns("actions")
            }
            self.assertTrue(
                {
                    "action_key",
                    "score",
                    "sort_order",
                    "evidence_json",
                }.issubset(action_columns)
            )

            context_columns = {
                column["name"] for column in inspector.get_columns("client_contexts")
            }
            self.assertTrue(
                {
                    "client_id",
                    "status",
                    "profile_json",
                    "evidence_json",
                    "warnings_json",
                }.issubset(context_columns)
            )

            conversation_columns = {
                column["name"] for column in inspector.get_columns("conversations")
            }
            self.assertTrue(
                {
                    "client_id",
                    "user_id",
                    "title",
                    "archived_at",
                }.issubset(conversation_columns)
            )

            message_columns = {
                column["name"] for column in inspector.get_columns("messages")
            }
            self.assertTrue(
                {
                    "conversation_id",
                    "role",
                    "content",
                    "metadata_json",
                }.issubset(message_columns)
            )

            draft_columns = {
                column["name"] for column in inspector.get_columns("content_drafts")
            }
            self.assertTrue(
                {
                    "conversation_id",
                    "client_id",
                    "created_by",
                    "content_type",
                    "title",
                    "content",
                    "status",
                    "reviewed_by",
                    "reviewed_at",
                    "review_notes",
                }.issubset(draft_columns)
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
            session.add(
                ClientContext(
                    client_id="client-1",
                    status="confirmed",
                    profile_json=json.dumps({"business": {"name": "AISO Demo"}}),
                    evidence_json=json.dumps({"pages": []}),
                    warnings_json=json.dumps([]),
                )
            )
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
            self.assertEqual(session.query(ClientContext).count(), 1)
        finally:
            session.close()

    def test_scan_metrics_persistence_registers_collect_csv_artifact(self):
        session = self.Session()
        try:
            session.add(User(id="user-1", email="founder@example.com", provider="google"))
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
                        "url": "https://example.com",
                        "competitors": ["SearchCo"],
                    }
                ),
                encoding="utf-8",
            )
            csv_path = folder / "responses.csv"
            with csv_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["question", "group", "response_openai", "error_openai"],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "question": "best ai visibility tool",
                        "group": "G1",
                        "response_openai": (
                            "AISO Demo is a strong option with proof from "
                            "[Example Source](https://example.com/source?utm_source=test)."
                        ),
                        "error_openai": "",
                    }
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
            self.assertEqual(session.query(ScanCitation).count(), 1)
            self.assertEqual(session.query(SourceProfile).count(), 1)
            self.assertGreaterEqual(session.query(Action).count(), 1)
            citation = session.query(ScanCitation).one()
            self.assertEqual(citation.citation_url, "https://example.com/source")
            self.assertEqual(citation.canonical_url, "https://example.com/source")
            self.assertEqual(citation.citation_title, "Example Source")
            self.assertEqual(citation.source_domain, "example.com")
            self.assertEqual(citation.owner_type, "owned")
            profile = session.query(SourceProfile).one()
            self.assertEqual(profile.canonical_url, "https://example.com/source")
            self.assertEqual(profile.owner_type, "owned")
            self.assertIsNotNone(citation.source_profile_id)
            artifact = session.query(ScanArtifact).one()
            self.assertEqual(artifact.artifact_type, "collect_csv")
            self.assertEqual(artifact.file_format, "csv")
            self.assertEqual(artifact.storage_backend, "local")
            self.assertEqual(len(artifact.sha256), 64)
            self.assertEqual(json.loads(artifact.metadata_json)["source"], "full_stack.collect")
        finally:
            session.close()

    def test_scan_metrics_persistence_registers_source_evidence_artifact(self):
        session = self.Session()
        try:
            session.add(User(id="user-2", email="source@example.com", provider="google"))
            session.add(
                Client(
                    id="client-2",
                    user_id="user-2",
                    name="PemSpa",
                    url="https://pempsa.com",
                )
            )
            session.add(Scan(id="scan-2", client_id="client-2", status="complete"))
            session.commit()
        finally:
            session.close()

        with tempfile.TemporaryDirectory() as tmp:
            client_folder = Path(tmp)
            (client_folder / "client_profile.json").write_text(
                json.dumps(
                    {
                        "display_name": "PemSpa",
                        "url": "https://pempsa.com",
                        "competitors": ["Glowbar Chestnut Hill"],
                    }
                ),
                encoding="utf-8",
            )
            csv_path = client_folder / "pemspa_aisodata_20260502_120000.csv"
            with csv_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["question", "group", "response_perplexity", "error_perplexity"],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "question": "best facial near me",
                        "group": "G1",
                        "response_perplexity": "Glowbar appears first, then other spas.",
                        "error_perplexity": "",
                    }
                )
            evidence_path = client_folder / "pemspa_source_evidence_20260502_120000.jsonl"
            evidence_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "scan_id": "scan-2",
                        "client_id": "client-2",
                        "provider": "perplexity",
                        "model": "sonar",
                        "question": "best facial near me",
                        "group": "G1",
                        "answer_excerpt": "Glowbar appears first, then other spas.",
                        "web_search_used": True,
                        "source": {
                            "url": "https://www.yelp.com/biz/glowbar-chestnut-hill?utm_source=ai",
                            "canonical_url": "https://yelp.com/biz/glowbar-chestnut-hill",
                            "domain": "yelp.com",
                            "title": "Glowbar Chestnut Hill on Yelp",
                            "source_rank": 1,
                            "origin": "native_citation",
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            with patch.object(database_module, "SessionLocal", self.Session):
                persist_collect_csv_results(
                    csv_path,
                    scan_id="scan-2",
                    client_id="client-2",
                    client_folder=client_folder,
                )

        session = self.Session()
        try:
            artifacts = {artifact.artifact_type for artifact in session.query(ScanArtifact).all()}
            self.assertEqual(artifacts, {"collect_csv", "source_evidence_jsonl"})
            citation = session.query(ScanCitation).one()
            self.assertEqual(citation.citation_origin, "native_citation")
            self.assertEqual(citation.web_search_used, True)
            self.assertEqual(citation.source_type, "directory_or_review")
            profile = session.query(SourceProfile).one()
            self.assertEqual(profile.source_domain, "yelp.com")
            self.assertEqual(profile.action_role, "listing_or_profile_target")
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

    def test_onedrive_client_slug_is_deterministic_and_separate_per_client(self):
        first = client_artifact_slug("PemSpa Skincare & Wellness", "client-abcdef123")
        second = client_artifact_slug("PemSpa Skincare & Wellness", "client-999999999")

        self.assertEqual(first, "pemspa-skincare-wellness--6e2864c9")
        self.assertNotEqual(first, second)
        self.assertNotIn("client-abcdef123", first)

    def test_onedrive_remote_dir_uses_client_slug_and_scan_id(self):
        with patch.dict("os.environ", {"AISO_ONEDRIVE_BASE_PATH": "/AISO"}):
            remote_dir = onedrive_remote_dir(
                "PemSpa Skincare & Wellness",
                "client-abcdef123",
                "scan-1",
            )

        self.assertEqual(remote_dir, "/AISO/clients/pemspa-skincare-wellness--6e2864c9/scans/scan-1")

    def test_configured_artifact_uploads_to_onedrive_without_public_link_or_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "responses.csv"
            csv_path.write_text("question,response\nhello,world\n", encoding="utf-8")

            with patch.dict(
                "os.environ",
                {
                    "AISO_STORAGE_BACKEND": "onedrive",
                    "AISO_ONEDRIVE_BASE_PATH": "/AISO",
                    "MICROSOFT_REFRESH_TOKEN": "secret-refresh-token",
                },
            ), patch(
                "api.storage.upload_file_to_onedrive",
                return_value=OneDriveUploadResult(
                    drive_id="drive-1",
                    item_id="item-1",
                    remote_path="/AISO/clients/aiso-demo--client-1/scans/scan-1/responses.csv",
                    web_url="https://onedrive.example/private",
                ),
            ):
                metadata = describe_configured_artifact(
                    csv_path,
                    artifact_type="collect_csv",
                    client_name="AISO Demo",
                    client_id="client-1",
                    scan_id="scan-1",
                    metadata={"source": "test"},
                )

        stored_metadata = json.loads(metadata["metadata_json"])
        self.assertEqual(metadata["storage_backend"], "onedrive")
        self.assertEqual(metadata["storage_path"], "onedrive://drive-1/item-1")
        self.assertEqual(stored_metadata["upload_status"], "uploaded")
        self.assertEqual(stored_metadata["remote_path"], "/AISO/clients/aiso-demo--client-1/scans/scan-1/responses.csv")
        self.assertNotIn("webUrl", stored_metadata)
        self.assertNotIn("secret-refresh-token", json.dumps(stored_metadata))

    def test_onedrive_upload_failure_falls_back_to_local_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "responses.csv"
            csv_path.write_text("question,response\nhello,world\n", encoding="utf-8")

            with patch.dict("os.environ", {"AISO_STORAGE_BACKEND": "onedrive"}), patch(
                "api.storage.upload_file_to_onedrive",
                side_effect=ArtifactStorageError("OneDrive unavailable"),
            ):
                metadata = describe_configured_artifact(
                    csv_path,
                    artifact_type="collect_csv",
                    client_name="AISO Demo",
                    client_id="client-1",
                    scan_id="scan-1",
                )

        stored_metadata = json.loads(metadata["metadata_json"])
        self.assertEqual(metadata["storage_backend"], "local")
        self.assertEqual(stored_metadata["upload_backend"], "onedrive")
        self.assertEqual(stored_metadata["upload_status"], "failed")
        self.assertEqual(stored_metadata["upload_error"], "OneDrive unavailable")


if __name__ == "__main__":
    unittest.main()
