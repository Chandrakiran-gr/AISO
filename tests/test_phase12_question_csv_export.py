import csv
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.auth import get_current_user_id
from api.database import Base, BusinessProfile, Client, QuestionCandidate, QuestionScore, Scan, ScanArtifact, User, get_db
from api.domain.ports import ScanEnqueueResult
from api.domain.question_generation import BRAND_FRAMES, INTENT_CLASSES, JOURNEY_STAGES, question_text_hash
from api.main import app
from api.routes.onboarding import get_scan_executor
from api.storage import OneDriveUploadResult, client_artifact_slug, materialize_artifact_file
from api.question_gen.export import QUESTION_CSV_COLUMNS, QUESTION_CSV_METHODOLOGY_VERSION


class RecordingScanExecutor:
    provider = "procrastinate_test"

    def __init__(self):
        self.calls = []

    def enqueue(self, *, scan_id: str, client_id: str) -> ScanEnqueueResult:
        self.calls.append({"scan_id": scan_id, "client_id": client_id})
        return ScanEnqueueResult(
            enqueued=True,
            provider=self.provider,
            job_id=f"test-job-{len(self.calls)}",
        )


class Phase12QuestionCsvExportTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.storage_dir = tempfile.TemporaryDirectory()
        self.uploaded_files: dict[str, bytes] = {}
        self.executor = RecordingScanExecutor()
        self.env_patch = patch.dict(
            "os.environ",
            {
                "AISO_STORAGE_BACKEND": "onedrive",
                "AISO_ONEDRIVE_BASE_PATH": "/AISO",
                "AISO_STORAGE_ROOT": self.storage_dir.name,
            },
        )
        self.upload_patch = patch("api.storage.upload_file_to_onedrive", side_effect=self._fake_onedrive_upload)
        self.download_patch = patch("api.storage.download_onedrive_artifact", side_effect=self._fake_onedrive_download)
        self.env_patch.start()
        self.upload_patch.start()
        self.download_patch.start()

        seed = self.Session()
        try:
            self._seed_question_fixture(seed)
            seed.commit()
        finally:
            seed.close()

        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user_id] = lambda: "user-1"
        app.dependency_overrides[get_scan_executor] = lambda: self.executor
        self.client = TestClient(app, base_url="http://localhost")

    def tearDown(self):
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user_id, None)
        app.dependency_overrides.pop(get_scan_executor, None)
        self.download_patch.stop()
        self.upload_patch.stop()
        self.env_patch.stop()
        self.storage_dir.cleanup()
        self.engine.dispose()

    def test_phase_12_9_acceptance_exports_selected_csv_and_enqueues_scan(self):
        response = self.client.post(
            "/api/v1/onboarding/client-1/select-questions",
            json={"target_n": 50},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()

        self.assertEqual(payload["selected_count"], 50)
        self.assertEqual(payload["scan_status"], "ready")
        self.assertEqual(payload["question_csv_storage_backend"], "onedrive")
        self.assertEqual(payload["question_csv_filename"], f"questions_{payload['scan_id']}.csv")
        self.assertEqual(payload["question_csv_columns"], QUESTION_CSV_COLUMNS)
        self.assertTrue(payload["enqueue_enqueued"])
        self.assertEqual(payload["enqueue_provider"], "procrastinate_test")
        self.assertEqual(len(self.executor.calls), 1)
        self.assertEqual(self.executor.calls[0], {"scan_id": payload["scan_id"], "client_id": "client-1"})

        db = self.Session()
        try:
            scan = db.query(Scan).filter(Scan.id == payload["scan_id"], Scan.client_id == "client-1").one()
            self.assertEqual(scan.status, "ready")

            artifact = (
                db.query(ScanArtifact)
                .filter(
                    ScanArtifact.id == payload["question_csv_artifact_id"],
                    ScanArtifact.scan_id == scan.id,
                    ScanArtifact.client_id == "client-1",
                )
                .one()
            )
            self.assertEqual(artifact.artifact_type, "selected_questions_csv")
            self.assertEqual(artifact.storage_backend, "onedrive")
            self.assertEqual(artifact.storage_path, payload["question_csv_storage_path"])
            metadata = json.loads(artifact.metadata_json)
            self.assertEqual(metadata["upload_status"], "uploaded")
            self.assertEqual(metadata["methodology_version"], QUESTION_CSV_METHODOLOGY_VERSION)
            self.assertEqual(metadata["selected_count"], 50)
            self.assertEqual(
                metadata["remote_path"],
                f"/AISO/clients/{client_artifact_slug('VectorCRM', 'client-1')}/scans/{scan.id}/questions_{scan.id}.csv",
            )

            with materialize_artifact_file(artifact) as csv_path:
                with csv_path.open(newline="", encoding="utf-8") as handle:
                    reader = csv.DictReader(handle)
                    rows = list(reader)

            self.assertEqual(reader.fieldnames, QUESTION_CSV_COLUMNS)
            self.assertEqual(len(rows), 50)
            self.assertEqual({row["scan_id"] for row in rows}, {scan.id})
            self.assertEqual({row["client_id"] for row in rows}, {"client-1"})
            self.assertEqual({row["vertical"] for row in rows}, {"b2b_saas"})
            self.assertEqual({row["objective"] for row in rows}, {"preference"})
            self.assertEqual({row["methodology_version"] for row in rows}, {QUESTION_CSV_METHODOLOGY_VERSION})
            self.assertTrue(all(row["question_text"] for row in rows))
            self.assertTrue(all(row["weighted_score"] for row in rows))
            self.assertTrue(all(row["realism_score"] for row in rows))
        finally:
            db.close()

    def _fake_onedrive_upload(self, local_path, remote_path):
        item_id = f"item-{len(self.uploaded_files) + 1}"
        storage_path = f"onedrive://drive-test/{item_id}"
        self.uploaded_files[storage_path] = local_path.read_bytes()
        return OneDriveUploadResult(
            drive_id="drive-test",
            item_id=item_id,
            remote_path=remote_path,
            web_url="https://onedrive.example/private",
        )

    def _fake_onedrive_download(self, storage_path: str) -> bytes:
        return self.uploaded_files[storage_path]

    def _seed_question_fixture(self, session) -> None:
        session.add(User(id="user-1", email="founder@example.com"))
        session.add(Client(id="client-1", user_id="user-1", name="VectorCRM", url="https://vector.example"))
        session.add(
            BusinessProfile(
                client_id="client-1",
                vertical="b2b_saas",
                objective="preference",
                category="sales CRM",
                icp={"firmographics": {"industry": "B2B SaaS", "employee_band": "51-200"}},
                geographic_scope={"countries": ["US"]},
                competitors=["HubSpot", "Salesforce", "Pipedrive"],
                personas={"primary": "VP Sales", "economic_buyer": "CRO"},
                crawl_artifacts={"auto_extracted": {"brand_name": "VectorCRM"}},
                floor_met=True,
            )
        )
        scored_at = datetime.now(timezone.utc)
        for index in range(150):
            stage = JOURNEY_STAGES[index % len(JOURNEY_STAGES)]
            frame = BRAND_FRAMES[(index // len(JOURNEY_STAGES)) % len(BRAND_FRAMES)]
            intent = INTENT_CLASSES[(index // (len(JOURNEY_STAGES) * len(BRAND_FRAMES))) % len(INTENT_CLASSES)]
            persona = "VP Sales" if index % 2 == 0 else "CRO"
            question = (
                f"what should {persona} evaluate for VectorCRM use case {index} "
                f"at {stage} with {frame} and {intent} intent?"
            )
            session.add(
                QuestionCandidate(
                    id=f"candidate-{index}",
                    client_id="client-1",
                    text=question,
                    text_hash=question_text_hash(question),
                    journey_stage=stage,
                    brand_frame=frame,
                    intent_class=intent,
                    persona=persona,
                    locality="US",
                    rationale="CSV export acceptance fixture.",
                    realism_score=Decimal("8.000"),
                    selected=index < 3,
                    generator_version="question_generation-test",
                    realism_filter_version="realism_filter-test",
                )
            )
            score = Decimal("9.500") - Decimal(index % 40) * Decimal("0.050")
            session.add(
                QuestionScore(
                    question_id=f"candidate-{index}",
                    scored_at=scored_at + timedelta(milliseconds=index),
                    d1_buyer_plausibility=score,
                    d2_commercial_proximity=score,
                    d3_cognitive_answerability=score,
                    d4_diagnostic_power=score,
                    d5_statistical_identifiability=score,
                    weighted_score=score,
                    rationale="Acceptance score.",
                    scorer_version="question_scorer-test",
                )
            )


if __name__ == "__main__":
    unittest.main()
