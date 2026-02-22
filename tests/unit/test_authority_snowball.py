"""Unit tests for the OpenClaw Site Authority Snowball Model."""

import unittest

from src.domains.seo.authority_snowball import (
    EXPANSION_MAX_PAGES,
    SEED_MAX_PAGES,
    TRUST_MAX_PAGES,
    GrowthStage,
    PageType,
    PublishingPlan,
    SiteSnapshot,
    SnowballSignals,
    build_publishing_plan,
    check_snowball_signals,
    compute_publishing_speed,
    determine_growth_stage,
    evaluate_portfolio,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _healthy_signals() -> SnowballSignals:
    """Signals that support scaling."""
    return SnowballSignals(
        avg_indexing_hours=48.0,
        impressions_trend=0.15,
        long_tail_rankings=12,
    )


def _unhealthy_signals() -> SnowballSignals:
    """Signals that block scaling."""
    return SnowballSignals(
        avg_indexing_hours=200.0,
        impressions_trend=-0.1,
        long_tail_rankings=2,
    )


# ---------------------------------------------------------------------------
# Tests — growth stage determination
# ---------------------------------------------------------------------------

class TestDetermineGrowthStage(unittest.TestCase):

    def test_seed_stage(self):
        self.assertEqual(determine_growth_stage(0), GrowthStage.SEED)
        self.assertEqual(determine_growth_stage(15), GrowthStage.SEED)
        self.assertEqual(determine_growth_stage(20), GrowthStage.SEED)

    def test_trust_stage(self):
        self.assertEqual(determine_growth_stage(21), GrowthStage.TRUST)
        self.assertEqual(determine_growth_stage(50), GrowthStage.TRUST)
        self.assertEqual(determine_growth_stage(80), GrowthStage.TRUST)

    def test_expansion_stage(self):
        self.assertEqual(determine_growth_stage(81), GrowthStage.EXPANSION)
        self.assertEqual(determine_growth_stage(150), GrowthStage.EXPANSION)
        self.assertEqual(determine_growth_stage(200), GrowthStage.EXPANSION)

    def test_authority_stage(self):
        self.assertEqual(determine_growth_stage(201), GrowthStage.AUTHORITY)
        self.assertEqual(determine_growth_stage(500), GrowthStage.AUTHORITY)


# ---------------------------------------------------------------------------
# Tests — snowball signal checks
# ---------------------------------------------------------------------------

class TestSnowballSignals(unittest.TestCase):

    def test_healthy_signals_safe(self):
        safe, blockers = check_snowball_signals(_healthy_signals())
        self.assertTrue(safe)
        self.assertEqual(len(blockers), 0)

    def test_unhealthy_signals_blocked(self):
        safe, blockers = check_snowball_signals(_unhealthy_signals())
        self.assertFalse(safe)
        self.assertEqual(len(blockers), 3)

    def test_slow_indexing_blocks(self):
        signals = SnowballSignals(
            avg_indexing_hours=100,
            impressions_trend=0.1,
            long_tail_rankings=10,
        )
        safe, blockers = check_snowball_signals(signals)
        self.assertFalse(safe)
        self.assertEqual(len(blockers), 1)
        self.assertIn("indexing", blockers[0].lower())

    def test_flat_impressions_block(self):
        signals = SnowballSignals(
            avg_indexing_hours=48,
            impressions_trend=0.0,
            long_tail_rankings=10,
        )
        safe, blockers = check_snowball_signals(signals)
        self.assertFalse(safe)
        self.assertEqual(len(blockers), 1)

    def test_low_long_tail_blocks(self):
        signals = SnowballSignals(
            avg_indexing_hours=48,
            impressions_trend=0.1,
            long_tail_rankings=3,
        )
        safe, blockers = check_snowball_signals(signals)
        self.assertFalse(safe)
        self.assertEqual(len(blockers), 1)


# ---------------------------------------------------------------------------
# Tests — publishing speed
# ---------------------------------------------------------------------------

class TestPublishingSpeed(unittest.TestCase):

    def test_seed_speed(self):
        speed = compute_publishing_speed(GrowthStage.SEED, safe_to_scale=True)
        self.assertEqual(speed, 3)

    def test_trust_speed(self):
        speed = compute_publishing_speed(GrowthStage.TRUST, safe_to_scale=True)
        self.assertEqual(speed, 5)

    def test_expansion_speed(self):
        speed = compute_publishing_speed(GrowthStage.EXPANSION, safe_to_scale=True)
        self.assertEqual(speed, 7)

    def test_authority_speed(self):
        speed = compute_publishing_speed(GrowthStage.AUTHORITY, safe_to_scale=True)
        self.assertEqual(speed, 10)

    def test_reduced_speed_when_unsafe(self):
        speed = compute_publishing_speed(GrowthStage.TRUST, safe_to_scale=False)
        self.assertEqual(speed, 2)  # 5 // 2

    def test_minimum_speed_is_one(self):
        speed = compute_publishing_speed(GrowthStage.SEED, safe_to_scale=False)
        self.assertEqual(speed, 1)  # max(3 // 2, 1)


# ---------------------------------------------------------------------------
# Tests — publishing plan
# ---------------------------------------------------------------------------

class TestBuildPublishingPlan(unittest.TestCase):

    def test_seed_plan(self):
        snapshot = SiteSnapshot(total_pages=10, niche="standing desks",
                                signals=_healthy_signals())
        plan = build_publishing_plan(snapshot)
        self.assertEqual(plan.stage, GrowthStage.SEED)
        self.assertEqual(plan.recommended_pages_per_week, 3)
        self.assertTrue(plan.safe_to_scale)
        self.assertIn(PageType.CORE_BUYER_GUIDE, plan.page_types)

    def test_trust_plan(self):
        snapshot = SiteSnapshot(total_pages=50, niche="headphones",
                                signals=_healthy_signals())
        plan = build_publishing_plan(snapshot)
        self.assertEqual(plan.stage, GrowthStage.TRUST)
        self.assertEqual(plan.recommended_pages_per_week, 5)
        self.assertIn(PageType.COMPARISON, plan.page_types)

    def test_blocked_plan_reduces_speed(self):
        snapshot = SiteSnapshot(total_pages=50, niche="headphones",
                                signals=_unhealthy_signals())
        plan = build_publishing_plan(snapshot)
        self.assertFalse(plan.safe_to_scale)
        self.assertTrue(plan.is_blocked)
        self.assertLess(plan.recommended_pages_per_week, 5)

    def test_authority_plan(self):
        snapshot = SiteSnapshot(total_pages=300, niche="fitness gear",
                                signals=_healthy_signals())
        plan = build_publishing_plan(snapshot)
        self.assertEqual(plan.stage, GrowthStage.AUTHORITY)
        self.assertIn(PageType.ADJACENT_CLUSTER, plan.page_types)
        self.assertIn(PageType.HUB_PAGE, plan.page_types)

    def test_stage_goal_populated(self):
        snapshot = SiteSnapshot(total_pages=10, niche="widgets")
        plan = build_publishing_plan(snapshot)
        self.assertIn("relevance", plan.stage_goal.lower())

    def test_next_stage_threshold(self):
        snapshot = SiteSnapshot(total_pages=10, niche="widgets",
                                signals=_healthy_signals())
        plan = build_publishing_plan(snapshot)
        self.assertEqual(plan.next_stage_threshold, TRUST_MAX_PAGES)


# ---------------------------------------------------------------------------
# Tests — site snapshot auto-stage
# ---------------------------------------------------------------------------

class TestSiteSnapshot(unittest.TestCase):

    def test_auto_stage_detection(self):
        snap = SiteSnapshot(total_pages=100)
        self.assertEqual(snap.current_stage, GrowthStage.EXPANSION)


# ---------------------------------------------------------------------------
# Tests — portfolio evaluation
# ---------------------------------------------------------------------------

class TestEvaluatePortfolio(unittest.TestCase):

    def test_multiple_sites(self):
        snapshots = [
            SiteSnapshot(total_pages=10, niche="standing desks",
                         signals=_healthy_signals()),
            SiteSnapshot(total_pages=250, niche="headphones",
                         signals=_healthy_signals()),
        ]
        plans = evaluate_portfolio(snapshots)
        self.assertEqual(len(plans), 2)
        # Seed stage should come first (earliest = most attention needed)
        self.assertEqual(plans[0].stage, GrowthStage.SEED)

    def test_empty_portfolio(self):
        plans = evaluate_portfolio([])
        self.assertEqual(len(plans), 0)


if __name__ == "__main__":
    unittest.main()
