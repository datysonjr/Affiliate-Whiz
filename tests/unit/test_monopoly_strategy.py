"""Unit tests for the OpenClaw Monopoly Site Strategy."""

import unittest

from src.domains.seo.monopoly_strategy import (
    BuyerStage,
    ContentFocus,
    InterlinkSafety,
    NicheMonopolyPlan,
    SERPOccupationPlan,
    SiteBlueprint,
    SiteType,
    build_monopoly_plan,
    classify_interlink_safety,
    evaluate_network_coverage,
    plan_serp_occupation,
)


# ---------------------------------------------------------------------------
# Tests — site types and buyer stages
# ---------------------------------------------------------------------------

class TestSiteTypes(unittest.TestCase):

    def test_four_site_types(self):
        self.assertEqual(len(SiteType), 4)

    def test_launch_order(self):
        self.assertLess(SiteType.AUTHORITY, SiteType.REVIEW)
        self.assertLess(SiteType.REVIEW, SiteType.SPECIALIST)
        self.assertLess(SiteType.SPECIALIST, SiteType.TREND)

    def test_four_buyer_stages(self):
        self.assertEqual(len(BuyerStage), 4)


# ---------------------------------------------------------------------------
# Tests — SERP occupation planning
# ---------------------------------------------------------------------------

class TestSERPOccupation(unittest.TestCase):

    def test_plans_all_four_sites(self):
        plan = plan_serp_occupation("best standing desks", "standing desks")
        self.assertEqual(plan.sites_targeting, 4)
        self.assertIn(SiteType.AUTHORITY, plan.site_assignments)
        self.assertIn(SiteType.REVIEW, plan.site_assignments)
        self.assertIn(SiteType.SPECIALIST, plan.site_assignments)
        self.assertIn(SiteType.TREND, plan.site_assignments)

    def test_target_positions(self):
        plan = plan_serp_occupation("best widgets", "widgets")
        self.assertEqual(plan.estimated_positions[SiteType.AUTHORITY], 1)
        self.assertEqual(plan.estimated_positions[SiteType.REVIEW], 3)

    def test_keyword_stored(self):
        plan = plan_serp_occupation("best headphones", "headphones")
        self.assertEqual(plan.keyword, "best headphones")


# ---------------------------------------------------------------------------
# Tests — interlink safety
# ---------------------------------------------------------------------------

class TestInterlinkSafety(unittest.TestCase):

    def test_contextual_is_safe(self):
        self.assertEqual(
            classify_interlink_safety("contextual citation"),
            InterlinkSafety.SAFE,
        )

    def test_data_source_is_safe(self):
        self.assertEqual(
            classify_interlink_safety("data source reference"),
            InterlinkSafety.SAFE,
        )

    def test_footer_is_forbidden(self):
        self.assertEqual(
            classify_interlink_safety("footer link"),
            InterlinkSafety.FORBIDDEN,
        )

    def test_sidebar_is_forbidden(self):
        self.assertEqual(
            classify_interlink_safety("sidebar blogroll"),
            InterlinkSafety.FORBIDDEN,
        )

    def test_unknown_is_caution(self):
        self.assertEqual(
            classify_interlink_safety("random link type"),
            InterlinkSafety.CAUTION,
        )


# ---------------------------------------------------------------------------
# Tests — monopoly plan building
# ---------------------------------------------------------------------------

class TestBuildMonopolyPlan(unittest.TestCase):

    def test_builds_4_sites(self):
        plan = build_monopoly_plan("standing desks")
        self.assertEqual(plan.site_count, 4)
        self.assertTrue(plan.is_full_network)

    def test_staggered_launch_months(self):
        plan = build_monopoly_plan("headphones")
        months = [s.launch_month for s in plan.sites]
        self.assertEqual(months, [0, 3, 6, 9])

    def test_distinct_content_focus(self):
        plan = build_monopoly_plan("widgets")
        focuses = {s.content_focus for s in plan.sites}
        self.assertEqual(len(focuses), 4)  # all different

    def test_distinct_editorial_voices(self):
        plan = build_monopoly_plan("widgets")
        voices = {s.editorial_voice for s in plan.sites}
        self.assertEqual(len(voices), 4)

    def test_serp_plans_generated(self):
        plan = build_monopoly_plan(
            "standing desks",
            target_keywords=["best standing desks", "standing desk reviews"],
        )
        self.assertEqual(len(plan.serp_plans), 2)

    def test_default_keyword_is_niche(self):
        plan = build_monopoly_plan("gaming chairs")
        self.assertEqual(len(plan.serp_plans), 1)
        self.assertEqual(plan.serp_plans[0].keyword, "gaming chairs")

    def test_interlinking_rules_present(self):
        plan = build_monopoly_plan("widgets")
        self.assertGreater(len(plan.interlinking_rules), 0)
        self.assertTrue(any("NEVER" in r for r in plan.interlinking_rules))

    def test_content_segmentation_present(self):
        plan = build_monopoly_plan("widgets")
        self.assertEqual(len(plan.content_segmentation), 4)

    def test_sub_niche_passed_to_specialist(self):
        plan = build_monopoly_plan("fitness gear", sub_niche="rowing machines")
        specialist = [s for s in plan.sites if s.site_type == SiteType.SPECIALIST][0]
        self.assertEqual(specialist.sub_niche, "rowing machines")

    def test_launch_timeline(self):
        plan = build_monopoly_plan("widgets")
        self.assertEqual(plan.launch_timeline_months, 9)

    def test_authority_site_targets_buying_queries(self):
        plan = build_monopoly_plan("standing desks")
        authority = [s for s in plan.sites if s.site_type == SiteType.AUTHORITY][0]
        self.assertTrue(any("Best" in q for q in authority.target_queries))

    def test_review_site_targets_comparison_queries(self):
        plan = build_monopoly_plan("standing desks")
        review = [s for s in plan.sites if s.site_type == SiteType.REVIEW][0]
        self.assertTrue(any("vs" in q or "alternatives" in q.lower() for q in review.target_queries))

    def test_trend_site_targets_emerging_queries(self):
        plan = build_monopoly_plan("standing desks")
        trend = [s for s in plan.sites if s.site_type == SiteType.TREND][0]
        self.assertTrue(any("New" in q or "Upcoming" in q for q in trend.target_queries))


# ---------------------------------------------------------------------------
# Tests — network coverage evaluation
# ---------------------------------------------------------------------------

class TestNetworkCoverage(unittest.TestCase):

    def test_single_niche(self):
        plans = [build_monopoly_plan("widgets")]
        metrics = evaluate_network_coverage(plans)
        self.assertEqual(metrics["niches_covered"], 1)
        self.assertEqual(metrics["total_sites"], 4)
        self.assertEqual(metrics["full_networks"], 1)

    def test_multiple_niches(self):
        plans = [
            build_monopoly_plan("standing desks"),
            build_monopoly_plan("gaming chairs"),
        ]
        metrics = evaluate_network_coverage(plans)
        self.assertEqual(metrics["niches_covered"], 2)
        self.assertEqual(metrics["total_sites"], 8)
        self.assertEqual(metrics["full_networks"], 2)

    def test_empty_portfolio(self):
        metrics = evaluate_network_coverage([])
        self.assertEqual(metrics["niches_covered"], 0)
        self.assertEqual(metrics["total_sites"], 0)


if __name__ == "__main__":
    unittest.main()
