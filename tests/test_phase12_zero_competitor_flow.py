import csv
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.adapters.question_generation import HeuristicQuestionGenerationAdapter
from api.adapters.question_scorer import HeuristicQuestionScorerAdapter
from api.adapters.realism_filter import HeuristicRealismFilterAdapter
from api.auth import get_current_user_id
from api.database import Base, QuestionCandidate, Scan, ScanArtifact, User, get_db
from api.domain.ports import ScanEnqueueResult
from api.domain.question_generation import COMPETITOR_BRAND_FRAMES, question_uses_competitor_pattern
from api.main import app
from api.question_gen.export import QUESTION_CSV_COLUMNS
from api.routes.onboarding import (
    get_question_generation_provider,
    get_question_scorer_provider,
    get_realism_filter_provider,
    get_scan_executor,
)
from api.storage import OneDriveUploadResult, materialize_artifact_file


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


class Phase12ZeroCompetitorFlowTests(unittest.TestCase):
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
            seed.add(User(id="user-1", email="founder@example.com"))
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
        app.dependency_overrides[get_question_generation_provider] = lambda: HeuristicQuestionGenerationAdapter()
        app.dependency_overrides[get_realism_filter_provider] = lambda: HeuristicRealismFilterAdapter()
        app.dependency_overrides[get_question_scorer_provider] = lambda: HeuristicQuestionScorerAdapter()
        app.dependency_overrides[get_scan_executor] = lambda: self.executor
        self.client = TestClient(app, base_url="http://localhost")

    def tearDown(self):
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user_id, None)
        app.dependency_overrides.pop(get_question_generation_provider, None)
        app.dependency_overrides.pop(get_realism_filter_provider, None)
        app.dependency_overrides.pop(get_question_scorer_provider, None)
        app.dependency_overrides.pop(get_scan_executor, None)
        self.download_patch.stop()
        self.upload_patch.stop()
        self.env_patch.stop()
        self.storage_dir.cleanup()
        self.engine.dispose()

    def test_zero_competitors_generates_selected_csv_and_ready_scan(self):
        start = self.client.post(
            "/api/v1/onboarding/start",
            json={
                "display_name": "Glow Day Spa",
                "url": "https://glow.example",
                "vertical": "local_services",
                "objective": "consideration",
            },
        )
        self.assertEqual(start.status_code, 201)
        onboarding_id = start.json()["onboarding_id"]

        confirmed = self.client.post(
            f"/api/v1/onboarding/{onboarding_id}/confirm-profile",
            json={
                "category": "day spa",
                "nap": "Glow Day Spa | 123 Main St, Boston, MA 02118 | (617) 555-0100",
                "service_radius": "10 miles around Boston",
                "service_taxonomy": ["facials", "massage", "waxing"],
                "hours": "Mon-Fri 9am-7pm, Sat 10am-5pm",
                "geographic_scope": {"description": "Boston, MA"},
            },
        )
        self.assertEqual(confirmed.status_code, 200)
        self.assertTrue(confirmed.json()["floor_met"])

        generated = self.client.post(
            f"/api/v1/onboarding/{onboarding_id}/generate-questions",
            json={"target_n": 50},
        )
        self.assertEqual(generated.status_code, 200)
        self.assertEqual(generated.json()["candidate_count"], 150)
        self.assertEqual(
            {
                frame
                for frame, count in generated.json()["brand_frame_distribution"].items()
                if count > 0
            }.intersection(COMPETITOR_BRAND_FRAMES),
            set(),
        )

        filtered = self.client.post(f"/api/v1/onboarding/{onboarding_id}/filter-realism")
        self.assertEqual(filtered.status_code, 200)
        self.assertGreaterEqual(filtered.json()["passed_count"], 50)

        scored = self.client.post(f"/api/v1/onboarding/{onboarding_id}/score-questions")
        self.assertEqual(scored.status_code, 200)
        self.assertGreaterEqual(scored.json()["scored_count"], 50)

        selected = self.client.post(
            f"/api/v1/onboarding/{onboarding_id}/select-questions",
            json={"target_n": 50},
        )
        self.assertEqual(selected.status_code, 200)
        payload = selected.json()
        self.assertEqual(payload["selected_count"], 50)
        self.assertEqual(payload["scan_status"], "ready")
        self.assertTrue(payload["enqueue_enqueued"])
        self.assertEqual(len(self.executor.calls), 1)
        self.assertEqual(payload["question_csv_columns"], QUESTION_CSV_COLUMNS)
        self.assertEqual(set(payload["frame_distribution"]).intersection(COMPETITOR_BRAND_FRAMES), set())

        db = self.Session()
        try:
            rows = (
                db.query(QuestionCandidate)
                .filter(QuestionCandidate.client_id == onboarding_id, QuestionCandidate.selected.is_(True))
                .all()
            )
            self.assertEqual(len(rows), 50)
            self.assertTrue(all(row.brand_frame not in COMPETITOR_BRAND_FRAMES for row in rows))
            self.assertTrue(all(not question_uses_competitor_pattern(row.text) for row in rows))

            scan = db.query(Scan).filter(Scan.id == payload["scan_id"]).one()
            self.assertEqual(scan.status, "ready")
            artifact = db.query(ScanArtifact).filter(ScanArtifact.id == payload["question_csv_artifact_id"]).one()
            with materialize_artifact_file(artifact) as csv_path:
                with csv_path.open(newline="", encoding="utf-8") as handle:
                    reader = csv.DictReader(handle)
                    csv_rows = list(reader)
            self.assertEqual(reader.fieldnames, QUESTION_CSV_COLUMNS)
            self.assertEqual(len(csv_rows), 50)
            self.assertTrue(all(row["brand_frame"] not in COMPETITOR_BRAND_FRAMES for row in csv_rows))
            self.assertTrue(all(not question_uses_competitor_pattern(row["question_text"]) for row in csv_rows))
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


if __name__ == "__main__":
    unittest.main()
