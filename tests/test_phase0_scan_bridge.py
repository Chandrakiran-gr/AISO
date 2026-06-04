"""Phase 0 bridge: groups/custom-questions → Phase 13 question manifest."""

from __future__ import annotations

import asyncio
import os
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from fastapi import BackgroundTasks
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.domain.ports import ScanHandle

from api.database import (
    Base,
    Client,
    MethodologyVersionSet,
    QuestionBankMembership,
    QuestionBankQuestion,
    QuestionBankVersion,
    ScanManifest,
    ScanRun,
    User,
)
from api.scan_bridge import (
    GROUP_TO_JOURNEY,
    ScanBridgeError,
    build_phase13_manifest_from_groups,
)


class _RecordingExecutor:
    def __init__(self):
        self.calls = []

    async def enqueue(self, *, scan_run_id, idempotency_key, client_id, methodology_version, cost_budget_usd, priority=0):
        self.calls.append({"scan_run_id": str(scan_run_id), "client_id": str(client_id)})
        return ScanHandle(
            scan_run_id=scan_run_id,
            idempotency_key=idempotency_key,
            enqueued_at=datetime.now(timezone.utc),
            methodology_version=methodology_version,
        )


class ScanBridgeTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        self.db.add(User(id="user-1", email="founder@example.com"))
        self.db.add(
            Client(
                id="client-1",
                user_id="user-1",
                name="VectorCRM",
                url="https://vector.example",
                cost_budget_default_usd=Decimal("5.00"),
            )
        )
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_custom_questions_build_manifest_with_journey_mapping(self):
        scan_id = "33333333-3333-4333-8333-333333333333"
        count = build_phase13_manifest_from_groups(
            self.db,
            client_id="client-1",
            scan_id=scan_id,
            groups=[],
            profile={},
            custom_questions=["Is VectorCRM good for startups?", "Does VectorCRM integrate with Slack?"],
        )
        self.db.commit()

        self.assertEqual(count, 2)
        self.assertEqual(self.db.query(QuestionBankVersion).count(), 1)
        self.assertEqual(self.db.query(QuestionBankQuestion).count(), 2)
        self.assertEqual(self.db.query(QuestionBankMembership).count(), 2)
        manifest = self.db.query(ScanManifest).filter(ScanManifest.scan_id == scan_id).all()
        self.assertEqual(len(manifest), 2)

        # Custom questions map to the MANUAL default journey/frame.
        expected_stage, expected_frame = GROUP_TO_JOURNEY["MANUAL"]
        for question in self.db.query(QuestionBankQuestion).all():
            self.assertEqual(question.journey_stage, expected_stage)
            self.assertEqual(question.brand_frame, expected_frame)
            self.assertEqual(question.source, "manual")

    def test_group_questions_get_mapped_journey_stages(self):
        scan_id = "44444444-4444-4444-8444-444444444444"
        profile = {
            "brand_name": "VectorCRM",
            "category": "CRM software",
            "geographic_scope": "US",
            "competitors": ["Salesforce", "HubSpot"],
            "primary_persona": "sales manager",
        }
        build_phase13_manifest_from_groups(
            self.db,
            client_id="client-1",
            scan_id=scan_id,
            groups=["G1", "G2", "G4"],
            profile=profile,
            custom_questions=[],
        )
        self.db.commit()

        questions = self.db.query(QuestionBankQuestion).all()
        self.assertGreater(len(questions), 0)
        valid_stages = {"J1", "J2", "J3", "J4", "J5", "J6"}
        valid_frames = {"U", "B", "C"}
        for question in questions:
            self.assertIn(question.journey_stage, valid_stages)
            self.assertIn(question.brand_frame, valid_frames)

    def test_duplicate_manifest_rejected(self):
        scan_id = "55555555-5555-4555-8555-555555555555"
        build_phase13_manifest_from_groups(
            self.db,
            client_id="client-1",
            scan_id=scan_id,
            groups=[],
            profile={},
            custom_questions=["Only question?"],
        )
        self.db.commit()
        with self.assertRaises(ScanBridgeError):
            build_phase13_manifest_from_groups(
                self.db,
                client_id="client-1",
                scan_id=scan_id,
                groups=[],
                profile={},
                custom_questions=["Only question?"],
            )

    def test_sparse_profile_with_template_groups_raises(self):
        # Template groups requested but no profile signal and no custom questions.
        with self.assertRaises(ScanBridgeError):
            build_phase13_manifest_from_groups(
                self.db,
                client_id="client-1",
                scan_id="88888888-8888-4888-8888-888888888888",
                groups=["G1", "G2"],
                profile={},
                custom_questions=[],
            )

    def test_no_questions_raises(self):
        with self.assertRaises(ScanBridgeError):
            build_phase13_manifest_from_groups(
                self.db,
                client_id="client-1",
                scan_id="66666666-6666-4666-8666-666666666666",
                groups=[],
                profile={},
                custom_questions=[],
            )

    def test_manifest_is_readable_by_scan_run_kickoff(self):
        """The bridge manifest must satisfy create_or_replay_scan_run's reader."""
        from api.adapters.scan_runs import create_or_replay_scan_run

        self.db.add(
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
        self.db.commit()

        scan_id = "77777777-7777-4777-8777-777777777777"
        count = build_phase13_manifest_from_groups(
            self.db,
            client_id="client-1",
            scan_id=scan_id,
            groups=[],
            profile={},
            custom_questions=["Q1?", "Q2?", "Q3?"],
        )
        self.db.commit()

        result = create_or_replay_scan_run(
            self.db,
            client_id="client-1",
            user_id="user-1",
            source_scan_id=scan_id,
            idempotency_key="11111111-1111-4111-8111-111111111111",
            providers=["openai", "claude"],
            complete_idempotency_response=False,
        )
        self.db.commit()

        self.assertEqual(result.body["scan_run_id"], scan_id)
        self.assertEqual(result.body["question_count"], count)
        run = self.db.query(ScanRun).filter(ScanRun.id == scan_id).one()
        self.assertEqual(run.status, "queued")


    def _seed_methodology_version_set(self):
        self.db.add(
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
        self.db.commit()

    def test_start_scan_phase13_routes_to_bridge_and_enqueues(self):
        from api.database import Scan
        from api.routes.pipeline import ScanCreate, start_scan

        self._seed_methodology_version_set()
        executor = _RecordingExecutor()
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(scan_executor=executor)))

        with mock.patch.dict(os.environ, {"AISO_SCAN_ENGINE": "phase13"}):
            response = asyncio.run(
                start_scan(
                    "client-1",
                    ScanCreate(
                        client_id="client-1",
                        providers=["openai", "claude"],
                        groups=[],
                        custom_questions=["Is VectorCRM good?", "Does it integrate with Slack?"],
                    ),
                    BackgroundTasks(),
                    request,
                    db=self.db,
                    user_id="user-1",
                )
            )

        # ScanRun created and enqueued; no legacy Scan row written.
        self.assertEqual(len(executor.calls), 1)
        scan_run_id = response["id"]
        self.assertEqual(executor.calls[0]["scan_run_id"], scan_run_id)
        self.assertEqual(self.db.query(ScanRun).count(), 1)
        self.assertEqual(self.db.query(Scan).count(), 0)
        self.assertEqual(self.db.query(ScanManifest).filter(ScanManifest.scan_id == scan_run_id).count(), 2)


if __name__ == "__main__":
    unittest.main()
