"""Materialization adapter: scan data -> projection tables (idempotent)."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from decimal import Decimal

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
    ScanAction,
    ScanCitationP13,
    ScanCompetitor,
    ScanManifest,
    ScanMetric,
    ScanRun,
    User,
)


def _citations(*urls):
    return {"metadata": {"web_search_used": True, "citations": [{"url": u} for u in urls]}}


class MaterializationAdapterTests(unittest.TestCase):
    SCAN_ID = "33333333-3333-4333-8333-333333333333"

    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self._seed()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _seed(self):
        self.db.add(User(id="user-1", email="f@example.com"))
        self.db.add(Client(id="client-1", user_id="user-1", name="Acme CRM", url="https://acme.com",
                           competitor_names=["Salesforce", "HubSpot"], cost_budget_default_usd=Decimal("5.00")))
        self.db.add(ScanRun(id=self.SCAN_ID, client_id="client-1", idempotency_key="idem-1",
                            methodology_version="AVS-1.0.0", methodology_version_set_id=None,
                            status="running", cost_budget_usd=Decimal("5.00"), latency_class="standard",
                            providers=["openai", "claude"]))
        self.db.add(QuestionBankVersion(bank_version_id="bank-1", client_id="client-1", avs_version="AVS-1.0.0",
                                        effective_from=datetime.now(timezone.utc), n_core=2, n_tail=0, n_total=2,
                                        rotation_reason="test"))
        for qid, stage in (("q1", "J1"), ("q2", "J4")):
            self.db.add(QuestionBankQuestion(question_id=qid, client_id="client-1", text=f"text {qid}",
                                             text_hash=f"h-{qid}", journey_stage=stage, brand_frame="U",
                                             locality="L0", source="generated"))
            self.db.add(ScanManifest(scan_id=self.SCAN_ID, question_id=qid, bank_version_id="bank-1",
                                     weight_at_scan=Decimal("1.0"), state_at_scan="FROZEN"))

        samples = [
            ("s1", "q1", "openai", "Acme CRM is a great option.", "R+", ["https://acme.com/x", "https://g2.com/acme"]),
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
            judgments = [
                {"domain": "acme.com", "source_class": "OWNED", "confidence": 0.9},
                {"domain": "g2.com", "source_class": "EARNED-MID", "confidence": 0.8},
                {"domain": "reddit.com", "source_class": "UGC", "confidence": 0.7},
            ]
            self.db.add(Classification(id=f"so-{sid}", sample_id=sid, classifier_type="source",
                                       classifier_version="classifier-1.0.0", classifier_model="judge",
                                       prompt_hash=b"p", consensus_value="EARNED-MID",
                                       individual_judgments=judgments))
        self.db.commit()

    def test_materialization_creates_rows(self):
        result = materialize_dashboard_projection(self.db, scan_run_id=self.SCAN_ID)
        self.db.commit()

        self.assertGreater(result.metric_count, 0)
        self.assertGreater(result.citation_count, 0)

        # overall metric
        overall = self.db.query(ScanMetric).filter_by(scan_id=self.SCAN_ID, scope_type="overall").one()
        self.assertEqual(overall.total_samples, 4)
        self.assertEqual(overall.mention_count, 2)  # s1, s3 mention Acme
        # citation_rate non-zero because acme.com (owned) was cited in s1
        self.assertGreater(float(overall.citation_rate), 0.0)

        # brand citation flagged (acme.com), source class carried through
        brand_cites = self.db.query(ScanCitationP13).filter_by(scan_id=self.SCAN_ID, is_brand_citation=True).all()
        self.assertTrue(brand_cites)
        g2 = self.db.query(ScanCitationP13).filter_by(scan_id=self.SCAN_ID, source_domain="g2.com").first()
        self.assertEqual(g2.source_class, "EARNED-MID")
        self.assertEqual(g2.action_role, "direct_citation_target")

        # competitors present
        comps = self.db.query(ScanCompetitor).filter_by(scan_id=self.SCAN_ID, scope_type="overall").all()
        self.assertEqual({c.competitor_name for c in comps}, {"Salesforce", "HubSpot"})

        # at least one action
        self.assertGreater(self.db.query(ScanAction).filter_by(scan_id=self.SCAN_ID).count(), 0)

    def test_phase13_actions_reader_shape(self):
        from api.adapters.scan_projection_read import latest_phase13_scan_id, phase13_actions

        materialize_dashboard_projection(self.db, scan_run_id=self.SCAN_ID)
        # mark run published so the "latest" resolver finds it
        run = self.db.query(ScanRun).filter_by(id=self.SCAN_ID).one()
        run.status = "succeeded"
        run.finished_at = datetime.now(timezone.utc)
        self.db.commit()

        self.assertEqual(latest_phase13_scan_id(self.db, client_id="client-1"), self.SCAN_ID)

        actions = phase13_actions(self.db, client_id="client-1", scan_id=None, status=None)
        self.assertTrue(actions)
        a = actions[0]
        # legacy ActionResponse shape keys present
        for key in ("id", "client_id", "scan_id", "title", "priority", "impact_pts",
                    "score", "sort_order", "status", "created_at", "target_questions_json"):
            self.assertIn(key, a)
        self.assertEqual(a["scan_id"], self.SCAN_ID)
        # impact_pts is the legacy display string
        self.assertTrue(a["impact_pts"] is None or a["impact_pts"].endswith("pts"))

    def test_phase13_gap_report_and_readers(self):
        from api.adapters.scan_projection_read import (
            phase13_citations,
            phase13_gap_report,
            phase13_sources,
        )

        materialize_dashboard_projection(self.db, scan_run_id=self.SCAN_ID)
        self.db.commit()
        client = self.db.query(Client).filter_by(id="client-1").one()

        report = phase13_gap_report(self.db, client=client, scan_id=self.SCAN_ID)
        # top-level keys the frontend renders
        for key in ("summary", "coverage", "weak_segments", "source_opportunities",
                    "source_intelligence", "competitor_gaps", "priority_fixes", "query_results"):
            self.assertIn(key, report)
        self.assertEqual(report["summary"]["appeared_count"], 2)
        self.assertEqual(report["summary"]["missed_count"], 2)

        # query_results: a missed question carries its cited sources in plain language
        missed = [q for q in report["query_results"] if not q["appeared"]]
        self.assertTrue(missed)
        with_sources = [q for q in missed if q["cited_sources"]]
        self.assertTrue(with_sources)
        self.assertIn("source_label", with_sources[0]["cited_sources"][0])

        # source opportunities surfaced (g2.com cited on a missed question)
        domains = {s["domain"] for s in report["source_opportunities"]}
        self.assertIn("g2.com", domains)

        # citations + sources readers return rows
        self.assertTrue(phase13_citations(self.db, client_id="client-1", scan_id=self.SCAN_ID))
        sources = phase13_sources(self.db, client_id="client-1", scan_id=self.SCAN_ID)
        self.assertTrue(sources)
        self.assertIn("canonical_url", sources[0])  # SourceProfileResponse shape

    def test_materialization_is_idempotent(self):
        first = materialize_dashboard_projection(self.db, scan_run_id=self.SCAN_ID)
        self.db.commit()
        m1 = self.db.query(ScanMetric).filter_by(scan_id=self.SCAN_ID).count()
        c1 = self.db.query(ScanCitationP13).filter_by(scan_id=self.SCAN_ID).count()

        second = materialize_dashboard_projection(self.db, scan_run_id=self.SCAN_ID)
        self.db.commit()
        m2 = self.db.query(ScanMetric).filter_by(scan_id=self.SCAN_ID).count()
        c2 = self.db.query(ScanCitationP13).filter_by(scan_id=self.SCAN_ID).count()

        self.assertEqual(first.metric_count, second.metric_count)
        self.assertEqual(m1, m2)
        self.assertEqual(c1, c2)


if __name__ == "__main__":
    unittest.main()
