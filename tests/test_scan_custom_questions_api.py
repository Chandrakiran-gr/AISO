import asyncio
import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.database import Base, Client, Scan, ScanArtifact, ScanCitation, User
from api.routes.pipeline import list_scan_custom_questions


class ScanCustomQuestionsApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        self.engine.dispose()

    def test_custom_question_endpoint_returns_manual_rows_with_provider_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage_root = Path(tmp)
            csv_path = storage_root / "collect.csv"
            with csv_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "question",
                        "group",
                        "response_openai",
                        "error_openai",
                        "response_claude",
                        "error_claude",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "question": "What sources recommend AISO for local businesses?",
                        "group": "MANUAL",
                        "response_openai": "AISO is mentioned by Example Directory.",
                        "error_openai": "",
                        "response_claude": "Competitors are mentioned, but not the client.",
                        "error_claude": "",
                    }
                )
                writer.writerow(
                    {
                        "question": "best AI visibility software",
                        "group": "G1",
                        "response_openai": "Templated row",
                        "error_openai": "",
                        "response_claude": "",
                        "error_claude": "",
                    }
                )

            session = self.Session()
            try:
                session.add(User(id="user-1", email="founder@example.com"))
                session.add(
                    Client(
                        id="client-1",
                        user_id="user-1",
                        name="AISO",
                        url="https://aiso.example",
                    )
                )
                session.add(
                    Scan(
                        id="scan-1",
                        client_id="client-1",
                        status="complete",
                    )
                )
                session.add(
                    ScanArtifact(
                        id="artifact-1",
                        client_id="client-1",
                        scan_id="scan-1",
                        artifact_type="collect_csv",
                        file_format="csv",
                        storage_backend="local",
                        storage_path=str(csv_path),
                    )
                )
                session.add(
                    ScanCitation(
                        id="citation-1",
                        client_id="client-1",
                        scan_id="scan-1",
                        provider="openai",
                        group="MANUAL",
                        question="What sources recommend AISO for local businesses?",
                        answer_excerpt="AISO is mentioned by Example Directory.",
                        citation_url="https://example.com/aiso",
                        citation_title="Example Directory",
                        source_domain="example.com",
                        source_rank=1,
                    )
                )
                session.commit()

                with patch.dict("os.environ", {"AISO_STORAGE_ROOT": str(storage_root)}, clear=False):
                    response = asyncio.run(
                        list_scan_custom_questions(
                            "client-1",
                            "scan-1",
                            db=session,
                            user_id="user-1",
                        )
                    )

                self.assertEqual(response["data_status"], "complete")
                self.assertEqual(len(response["questions"]), 1)
                question = response["questions"][0]
                self.assertEqual(question["question"], "What sources recommend AISO for local businesses?")
                self.assertTrue(question["providers"]["openai"]["mentioned"])
                self.assertFalse(question["providers"]["claude"]["mentioned"])
                self.assertEqual(question["providers"]["openai"]["citations"][0]["domain"], "example.com")
            finally:
                session.close()


if __name__ == "__main__":
    unittest.main()
