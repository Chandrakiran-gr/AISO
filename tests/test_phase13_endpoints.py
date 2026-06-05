"""Endpoint-level coverage of the AISO_SCAN_ENGINE=phase13 route branches.

The Phase 13 builders/adapter/saga are unit-tested elsewhere; this exercises the
thin `if is_phase13_engine(): return phase13_*(...)` branches in the gap-report,
actions, sources, and citations endpoints end-to-end against materialized data.
"""

from __future__ import annotations

import asyncio
import os
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from unittest import mock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.adapters.scan_projection import materialize_dashboard_projection
from api.database import (
    Base,
    Classification,
    Client,
    ExecutionSample,
    QuestionBankQuestion,
    QuestionBankVersion,
    Sample,
    ScanManifest,
    ScanRun,
    User,
)
from api.routes.actions import list_actions
from api.routes.pipeline import get_client_gap_report, list_client_sources, list_scan_citations

PHASE13 = {"AISO_SCAN_ENGINE": "phase13"}


def _citations(*urls):
    return {"metadata": {"web_search_used": True, "citations": [{"url": u} for u in urls]}}


class Phase13EndpointTests(unittest.TestCase):
    SCAN_ID = "33333333-3333-4333-8333-333333333333"

    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self._seed()
        materialize_dashboard_projection(self.db, scan_run_id=self.SCAN_ID)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _seed(self):
        self.db.add(User(id="user-1", email="f@example.com"))
        self.db.add(Client(id="client-1", user_id="user-1", name="Acme CRM", url="https://acme.com",
                           competitors='["Salesforce"]', cost_budget_default_usd=Decimal("5.00")))
        self.db.add(ScanRun(id=self.SCAN_ID, client_id="client-1", idempotency_key="idem-1",
                            methodology_version="AVS-1.0.0", methodology_version_set_id=None,
                            status="succeeded", finished_at=datetime.now(timezone.utc),
                            cost_budget_usd=Decimal("5.00"), latency_class="standard",
                            providers=["openai", "claude"]))
        self.db.add(QuestionBankVersion(bank_version_id="bank-1", client_id="client-1", avs_version="AVS-1.0.0",
                                        effective_from=datetime.now(timezone.utc), n_core=2, n_tail=0, n_total=2,
                                        rotation_reason="test"))
        for qid, stage in (("q1", "J1"), ("q2", "J4")):
            self.db.add(QuestionBankQuestion(question_id=qid, client_id="client-1", text=f"best crm for {qid}?",
                                             text_hash=f"h-{qid}", journey_stage=stage, brand_frame="U",
                                             locality="L0", source="generated"))
            self.db.add(ScanManifest(scan_id=self.SCAN_ID, question_id=qid, bank_version_id="bank-1",
                                     weight_at_scan=Decimal("1.0"), state_at_scan="FROZEN"))
        samples = [
            ("s1", "q1", "openai", "Acme CRM is a great option.", "R+", ["https://acme.com/x", "https://g2.com/a"]),
            ("s2", "q1", "claude", "Salesforce dominates the market.", "N", ["https://g2.com/sf"]),
            ("s3", "q2", "openai", "Acme CRM and HubSpot are options.", "C+", ["https://reddit.com/r/crm"]),
            ("s4", "q2", "claude", "Use Salesforce for enterprise.", "C-", []),
        ]
        for idx, (sid, qid, provider, text, stance, urls) in enumerate(samples):
            self.db.add(Sample(id=sid, scan_id=self.SCAN_ID, question_id=qid, provider=provider,
                               provider_model="m", temperature=Decimal("0.7"), sample_index=idx,
                               request_payload_hash=b"x", raw_response_text=text, raw_response_hash=b"y",
                               response_received_at=datetime.now(timezone.utc)))
            self.db.add(ExecutionSample(scan_run_id=self.SCAN_ID, question_id=qid, provider=provider,
                                        sample_index=idx, provider_idem_key=f"k-{sid}",
                                        raw_response=_citations(*urls), raw_response_text=text))
            self.db.add(Classification(id=f"st-{sid}", sample_id=sid, classifier_type="stance",
                                       classifier_version="classifier-1.0.0", classifier_model="judge",
                                       prompt_hash=b"p", consensus_value=stance, consensus_confidence=Decimal("0.9")))
            self.db.add(Classification(id=f"so-{sid}", sample_id=sid, classifier_type="source",
                                       classifier_version="classifier-1.0.0", classifier_model="judge",
                                       prompt_hash=b"p", consensus_value="EARNED-MID",
                                       individual_judgments=[
                                           {"domain": "acme.com", "source_class": "OWNED", "confidence": 0.9},
                                           {"domain": "g2.com", "source_class": "EARNED-MID", "confidence": 0.8},
                                           {"domain": "reddit.com", "source_class": "UGC", "confidence": 0.7},
                                       ]))
        self.db.commit()

    def test_gap_report_endpoint_serves_phase13(self):
        with mock.patch.dict(os.environ, PHASE13):
            report = asyncio.run(get_client_gap_report("client-1", scan_id=None, db=self.db, user_id="user-1"))
        self.assertEqual(report["report_source"], "phase13_projection")
        self.assertEqual(report["scan_id"], self.SCAN_ID)
        self.assertEqual(report["summary"]["appeared_count"], 2)
        self.assertTrue(report["query_results"])

    def test_actions_endpoint_serves_phase13(self):
        with mock.patch.dict(os.environ, PHASE13):
            actions = asyncio.run(list_actions("client-1", scan_id=None, status=None, db=self.db, user_id="user-1"))
        self.assertTrue(actions)
        self.assertEqual(actions[0]["scan_id"], self.SCAN_ID)
        self.assertIn("impact_pts", actions[0])

    def test_sources_endpoint_serves_phase13(self):
        with mock.patch.dict(os.environ, PHASE13):
            sources = asyncio.run(list_client_sources(
                "client-1", scan_id=None, owner_type=None, source_type=None, action_role=None,
                min_actionability=None, limit=50, offset=0, db=self.db, user_id="user-1"))
        self.assertTrue(sources)
        self.assertIn("canonical_url", sources[0])

    def test_citations_endpoint_serves_phase13(self):
        with mock.patch.dict(os.environ, PHASE13):
            citations = asyncio.run(list_scan_citations("client-1", self.SCAN_ID, db=self.db, user_id="user-1"))
        self.assertTrue(citations)
        self.assertIn("citation_url", citations[0])

    def test_legacy_default_does_not_hit_phase13(self):
        # With the default engine (legacy) and no legacy rows, gap-report 404s
        # rather than returning phase13 data — proving the branch is flag-gated.
        from fastapi import HTTPException

        with self.assertRaises(HTTPException):
            asyncio.run(get_client_gap_report("client-1", scan_id=None, db=self.db, user_id="user-1"))


if __name__ == "__main__":
    unittest.main()
