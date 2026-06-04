"""Pure builders for the Phase 13 dashboard projection."""

from __future__ import annotations

import unittest

from api.domain.scan_projection import (
    CitationFact,
    ProjectionSample,
    SCOPE_OVERALL,
    SCOPE_PROVIDER,
    action_role_for_source_class,
    build_action_plan,
    build_citation_rows,
    build_competitor_rows,
    build_metric_rows,
    detect_competitor_mentions,
)


def _sample(sid, provider, stage, text, stance="C+", citations=None):
    return ProjectionSample(
        sample_id=sid, question_id=f"q-{sid[:1]}", provider=provider, journey_stage=stage,
        text=text, stance_label=stance, citations=citations or [],
    )


class ScanProjectionTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            _sample("a", "openai", "J1", "Acme CRM is a great option for teams.", "R+",
                    [CitationFact(url="https://acme.com/x", domain="acme.com", source_class="OWNED"),
                     CitationFact(url="https://g2.com/acme", domain="g2.com", source_class="EARNED-MID")]),
            _sample("b", "openai", "J1", "Salesforce and HubSpot dominate the market.", "N",
                    [CitationFact(url="https://g2.com/sf", domain="g2.com", source_class="EARNED-MID")]),
            _sample("c", "claude", "J2", "Acme CRM works well; some prefer HubSpot.", "C+",
                    [CitationFact(url="https://reddit.com/r/crm", domain="reddit.com", source_class="UGC")]),
            _sample("d", "claude", "J2", "Consider Salesforce for enterprise needs.", "C-", []),
        ]

    def test_action_role_mapping(self):
        self.assertEqual(action_role_for_source_class("EARNED-HIGH"), "digital_pr_target")
        self.assertEqual(action_role_for_source_class("UGC"), "community_target")
        self.assertEqual(action_role_for_source_class(None), "review_needed")
        self.assertEqual(action_role_for_source_class("weird"), "review_needed")

    def test_metric_rows_have_scopes_and_wilson_cis(self):
        metrics = build_metric_rows(self.rows, brand_aliases=["Acme CRM", "Acme"], owned_domains=["acme.com"])
        overall = [m for m in metrics if m.scope_type == SCOPE_OVERALL]
        self.assertEqual(len(overall), 1)
        o = overall[0]
        self.assertEqual(o.total_samples, 4)
        self.assertEqual(o.mention_count, 2)  # samples a and c mention Acme
        self.assertAlmostEqual(o.mention_rate, 0.5, places=3)
        # Wilson interval is a proper sub-interval of [0,1] and brackets nothing absurd.
        self.assertLess(o.mention_rate_ci_lower_95, o.mention_rate)
        self.assertGreater(o.mention_rate_ci_upper_95, o.mention_rate)
        self.assertGreaterEqual(o.mention_rate_ci_lower_95, 0.0)
        self.assertLessEqual(o.mention_rate_ci_upper_95, 1.0)
        # citation_count: samples with an owned (acme.com) citation -> only sample a
        self.assertEqual(o.citation_count, 1)
        # per-provider + per-journey + provider_journey scopes present
        providers = {m.provider for m in metrics if m.scope_type == SCOPE_PROVIDER}
        self.assertEqual(providers, {"openai", "claude"})

    def test_citation_rows_flag_brand_and_competitor(self):
        cites = build_citation_rows(self.rows, owned_domains=["acme.com"], competitor_domains=["salesforce.com"])
        brand = [c for c in cites if c.is_brand_citation]
        self.assertTrue(brand)
        self.assertEqual(brand[0].source_domain, "acme.com")
        # action_role derived from source_class
        g2 = [c for c in cites if c.source_domain == "g2.com"][0]
        self.assertEqual(g2.action_role, "direct_citation_target")

    def test_competitor_mentions_and_sov(self):
        competitors = {"Salesforce": ["Salesforce"], "HubSpot": ["HubSpot"]}
        self.assertEqual(
            detect_competitor_mentions("Salesforce and HubSpot dominate.", competitors),
            {"Salesforce", "HubSpot"},
        )
        rows = build_competitor_rows(self.rows, brand_aliases=["Acme CRM", "Acme"], competitors=competitors)
        overall = [r for r in rows if r.scope_type == SCOPE_OVERALL]
        names = {r.competitor_name for r in overall}
        self.assertEqual(names, {"Salesforce", "HubSpot"})
        for r in overall:
            self.assertGreaterEqual(r.share_of_voice, 0.0)
            self.assertLessEqual(r.share_of_voice, 1.0)

    def test_action_plan_is_ranked_and_evidence_backed(self):
        metrics = build_metric_rows(self.rows, brand_aliases=["Acme CRM", "Acme"], owned_domains=["acme.com"])
        cites = build_citation_rows(self.rows, owned_domains=["acme.com"], competitor_domains=["salesforce.com"])
        comps = build_competitor_rows(self.rows, brand_aliases=["Acme"], competitors={"Salesforce": ["Salesforce"]})
        actions = build_action_plan(metrics, cites, comps, brand_name="Acme CRM", limit=20)
        self.assertTrue(actions)
        # sorted by score desc, sort_order assigned
        self.assertEqual([a.sort_order for a in actions], list(range(len(actions))))
        scores = [a.score for a in actions]
        self.assertEqual(scores, sorted(scores, reverse=True))
        # g2.com cited twice (not owned) -> a source opportunity action exists
        source_actions = [a for a in actions if a.category == "source_opportunity"]
        self.assertTrue(any("g2.com" in a.action_key for a in source_actions))


if __name__ == "__main__":
    unittest.main()
