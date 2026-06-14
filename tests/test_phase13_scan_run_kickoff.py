from datetime import datetime, timezone
from decimal import Decimal
import unittest

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from tests._pgharness import make_test_engine, reset_schema
from api.auth import get_current_user_id
from api.database import (
    AuditEvent,
    Base,
    Client,
    IdempotencyKey,
    MethodologyVersionSet,
    QuestionBankQuestion,
    QuestionBankVersion,
    ScanManifest,
    ScanProgress,
    ScanRun,
    ScanStep,
    User,
    get_db,
)
from api.domain.ports import ScanHandle
from api.domain.scan_runs import request_hash
from api.main import app
from api.routes import scan_runs as scan_run_routes


class RecordingScanExecutor:
    def __init__(self):
        self.calls = []

    async def enqueue(
        self,
        *,
        scan_run_id,
        idempotency_key: str,
        client_id,
        methodology_version: str,
        cost_budget_usd: float,
        priority: int = 0,
    ) -> ScanHandle:
        self.calls.append(
            {
                "scan_run_id": str(scan_run_id),
                "idempotency_key": idempotency_key,
                "client_id": str(client_id),
                "methodology_version": methodology_version,
                "cost_budget_usd": cost_budget_usd,
                "priority": priority,
            }
        )
        return ScanHandle(
            scan_run_id=scan_run_id,
            idempotency_key=idempotency_key,
            enqueued_at=datetime.now(timezone.utc),
            methodology_version=methodology_version,
        )


class ConflictingScanExecutor:
    async def enqueue(
        self,
        *,
        scan_run_id,
        idempotency_key: str,
        client_id,
        methodology_version: str,
        cost_budget_usd: float,
        priority: int = 0,
    ) -> ScanHandle:
        from api.adapters.scan_execution import ScanQueueConflict

        raise ScanQueueConflict()


class Phase13ScanRunKickoffTests(unittest.TestCase):
    def setUp(self):
        self.engine = make_test_engine()  # Postgres when TEST_DATABASE_URL set, else SQLite
        reset_schema(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.source_scan_id = "33333333-3333-4333-8333-333333333333"
        self.idempotency_key = "11111111-1111-4111-8111-111111111111"

        seed = self.Session()
        try:
            self._seed_ready_question_manifest(seed)
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
        self.executor = RecordingScanExecutor()
        app.dependency_overrides[scan_run_routes.get_scan_executor] = lambda: self.executor
        self.client = TestClient(app, base_url="http://localhost")

    def tearDown(self):
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user_id, None)
        app.dependency_overrides.pop(scan_run_routes.get_scan_executor, None)
        self.engine.dispose()

    def test_phase_13_4_acceptance_idempotently_creates_queued_scan_run(self):
        response = self.client.post(
            "/api/v1/clients/client-1/scan-runs",
            headers={"Idempotency-Key": self.idempotency_key},
            json={
                "source_scan_id": self.source_scan_id,
                "providers": ["openai", "claude"],
                "cost_budget_usd": "12.34",
            },
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload["scan_run_id"], self.source_scan_id)
        self.assertEqual(payload["client_id"], "client-1")
        self.assertEqual(payload["status"], "queued")
        self.assertEqual(payload["methodology_version_set_id"], "mvs-1")
        self.assertEqual(payload["providers"], ["openai", "claude"])
        self.assertEqual(payload["samples_per_cell"], 5)
        self.assertEqual(payload["question_count"], 50)
        self.assertEqual(payload["total_calls"], 500)
        self.assertEqual(payload["cost_budget_usd"], "12.3400")
        self.assertTrue(payload["scan_manifest_hash"])

        replay = self.client.post(
            "/api/v1/clients/client-1/scan-runs",
            headers={"Idempotency-Key": self.idempotency_key},
            json={
                "source_scan_id": self.source_scan_id,
                "providers": ["openai", "claude"],
                "cost_budget_usd": "12.34",
            },
        )
        self.assertEqual(replay.status_code, 201)
        self.assertEqual(replay.json(), payload)

        conflict = self.client.post(
            "/api/v1/clients/client-1/scan-runs",
            headers={"Idempotency-Key": self.idempotency_key},
            json={
                "source_scan_id": self.source_scan_id,
                "providers": ["openai"],
                "cost_budget_usd": "12.34",
            },
        )
        self.assertEqual(conflict.status_code, 409)

        progress = self.client.get(f"/api/v1/scan-runs/{self.source_scan_id}/progress")
        self.assertEqual(progress.status_code, 200)
        progress_payload = progress.json()
        self.assertEqual(progress_payload["status"], "queued")
        self.assertEqual(progress_payload["stage"], "queued")
        self.assertEqual(progress_payload["total_calls"], 500)
        self.assertEqual(progress_payload["completed_calls"], 0)
        self.assertEqual(progress_payload["methodology_version_set_id"], "mvs-1")

        db = self.Session()
        try:
            self.assertEqual(len(self.executor.calls), 1)
            self.assertEqual(self.executor.calls[0]["scan_run_id"], self.source_scan_id)
            self.assertEqual(self.executor.calls[0]["client_id"], "client-1")
            self.assertEqual(db.query(ScanRun).count(), 1)
            self.assertEqual(db.query(ScanProgress).count(), 1)
            self.assertEqual(db.query(IdempotencyKey).count(), 1)
            self.assertEqual(db.query(ScanStep).filter_by(step_id="create_scan_run").count(), 1)
            self.assertEqual(db.query(ScanStep).filter_by(step_id="enqueue_scan").count(), 1)
            self.assertEqual(db.query(AuditEvent).count(), 3)
            self.assertEqual(
                [event.action for event in db.query(AuditEvent).order_by(AuditEvent.id.asc()).all()],
                ["scan_run.created", "scan_run.enqueued", "scan_run.idempotency_replayed"],
            )
            run = db.query(ScanRun).one()
            self.assertEqual(run.methodology_version_set_id, "mvs-1")
            self.assertEqual(run.providers, ["openai", "claude"])
            idempotency = db.query(IdempotencyKey).one()
            self.assertEqual(idempotency.response_status, 201)
            self.assertIsNotNone(idempotency.completed_at)
        finally:
            db.close()

    def test_scan_run_kickoff_requires_manifest_and_valid_ids(self):
        invalid_key = self.client.post(
            "/api/v1/clients/client-1/scan-runs",
            headers={"Idempotency-Key": "not-a-uuid"},
            json={"source_scan_id": self.source_scan_id},
        )
        self.assertEqual(invalid_key.status_code, 400)

        missing_manifest = self.client.post(
            "/api/v1/clients/client-1/scan-runs",
            headers={"Idempotency-Key": "22222222-2222-4222-8222-222222222222"},
            json={"source_scan_id": "44444444-4444-4444-8444-444444444444"},
        )
        self.assertEqual(missing_manifest.status_code, 409)

        invalid_source_scan_id = self.client.post(
            "/api/v1/clients/client-1/scan-runs",
            headers={"Idempotency-Key": "55555555-5555-4555-8555-555555555555"},
            json={"source_scan_id": "not-a-uuid"},
        )
        self.assertEqual(invalid_source_scan_id.status_code, 400)

    def test_scan_run_kickoff_rejects_manifest_owned_by_another_client(self):
        other_scan_id = "66666666-6666-4666-8666-666666666666"
        db = self.Session()
        try:
            self._seed_foreign_manifest(db, scan_id=other_scan_id)
            db.commit()
        finally:
            db.close()

        response = self.client.post(
            "/api/v1/clients/client-1/scan-runs",
            headers={"Idempotency-Key": "77777777-7777-4777-8777-777777777777"},
            json={"source_scan_id": other_scan_id},
        )

        self.assertEqual(response.status_code, 409)

    def test_scan_run_kickoff_persists_failed_enqueue_event(self):
        app.dependency_overrides[scan_run_routes.get_scan_executor] = lambda: ConflictingScanExecutor()

        response = self.client.post(
            "/api/v1/clients/client-1/scan-runs",
            headers={"Idempotency-Key": self.idempotency_key},
            json={
                "source_scan_id": self.source_scan_id,
                "providers": ["openai", "claude"],
                "cost_budget_usd": "12.34",
            },
        )

        self.assertEqual(response.status_code, 409)
        db = self.Session()
        try:
            self.assertEqual(db.query(ScanRun).count(), 1)
            self.assertEqual(db.query(ScanStep).filter_by(step_id="enqueue_scan", event="succeeded").count(), 0)
            failed_step = db.query(ScanStep).filter_by(step_id="enqueue_scan", event="failed").one()
            self.assertEqual(failed_step.payload["reason"], "Client already has an active queued scan")
            idempotency = db.query(IdempotencyKey).one()
            self.assertIsNone(idempotency.completed_at)
            self.assertIsNone(idempotency.response_status)
            self.assertEqual(
                [event.action for event in db.query(AuditEvent).order_by(AuditEvent.id.asc()).all()],
                ["scan_run.created", "scan_run.enqueue_failed"],
            )
        finally:
            db.close()

    def test_scan_run_kickoff_rejects_in_progress_idempotency_key(self):
        db = self.Session()
        try:
            db.add(
                IdempotencyKey(
                    key="88888888-8888-4888-8888-888888888888",
                    scope="scan_run.create",
                    request_hash=request_hash(
                        {
                            "client_id": "client-1",
                            "source_scan_id": self.source_scan_id,
                            "providers": ["openai", "claude"],
                            "cost_budget_usd": "12.3400",
                            "latency_class": "standard",
                        }
                    ),
                )
            )
            db.commit()
        finally:
            db.close()

        response = self.client.post(
            "/api/v1/clients/client-1/scan-runs",
            headers={"Idempotency-Key": "88888888-8888-4888-8888-888888888888"},
            json={
                "source_scan_id": self.source_scan_id,
                "providers": ["openai", "claude"],
                "cost_budget_usd": "12.34",
            },
        )

        self.assertEqual(response.status_code, 409)

    def _seed_ready_question_manifest(self, session) -> None:
        session.add(User(id="user-1", email="founder@example.com"))
        session.add(
            MethodologyVersionSet(
                id="mvs-1",
                label="phase13-test-current",
                avs_formula_version="AVS-1.0.0",
                bank_version="question-bank-1.0.0",
                stance_classifier_version="classifier-1.0.0",
                source_classifier_version="classifier-1.0.0",
                sampling_config_version="N-sampling-1.0.0",
                provider_model_snapshot_version="providers-1.0.0",
                valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
                sys_period="current",
                spec_document_url="methodology/MANIFEST.txt",
                spec_document_hash=b"0" * 32,
                approved_by="founder",
                approved_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
        )
        session.add(
            Client(
                id="client-1",
                user_id="user-1",
                name="VectorCRM",
                url="https://vector.example",
                cost_budget_default_usd=Decimal("5.00"),
            )
        )
        session.flush()  # client must exist before its question-bank rows FK to it
        bank_version = QuestionBankVersion(
            bank_version_id="bank-1",
            client_id="client-1",
            avs_version="AVS-1.0.0",
            effective_from=datetime.now(timezone.utc),
            n_core=35,
            n_tail=15,
            n_total=50,
            rotation_reason="phase12_initial_import",
        )
        session.add(bank_version)
        for index in range(50):
            question_id = f"question-{index:02d}"
            session.add(
                QuestionBankQuestion(
                    question_id=question_id,
                    client_id="client-1",
                    text=f"What should buyers evaluate for VectorCRM option {index}?",
                    text_hash=f"hash-{index:02d}",
                    journey_stage="J2",
                    brand_frame="U",
                    locality="L0",
                    source="generated",
                )
            )
            session.add(
                ScanManifest(
                    scan_id=self.source_scan_id,
                    question_id=question_id,
                    bank_version_id=bank_version.bank_version_id,
                    weight_at_scan=Decimal("1.0000"),
                    state_at_scan="FROZEN" if index < 35 else "TAIL",
                )
            )

    def _seed_foreign_manifest(self, session, *, scan_id: str) -> None:
        session.add(User(id="user-2", email="other@example.com"))
        session.add(Client(id="client-2", user_id="user-2", name="OtherCo", url="https://other.example"))
        session.flush()  # client must exist before its question-bank rows FK to it
        session.add(
            QuestionBankVersion(
                bank_version_id="bank-2",
                client_id="client-2",
                avs_version="AVS-1.0.0",
                effective_from=datetime.now(timezone.utc),
                n_core=1,
                n_tail=0,
                n_total=1,
                rotation_reason="phase12_initial_import",
            )
        )
        session.add(
            QuestionBankQuestion(
                question_id="foreign-question-1",
                client_id="client-2",
                text="What should buyers evaluate for OtherCo?",
                text_hash="foreign-hash-1",
                journey_stage="J2",
                brand_frame="U",
                locality="L0",
                source="generated",
            )
        )
        session.add(
            ScanManifest(
                scan_id=scan_id,
                question_id="foreign-question-1",
                bank_version_id="bank-2",
                weight_at_scan=Decimal("1.0000"),
                state_at_scan="FROZEN",
            )
        )


if __name__ == "__main__":
    unittest.main()
