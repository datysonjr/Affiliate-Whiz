"""Unit tests for the OpenClaw Automated Empire Scaling Plan."""

import unittest

from src.domains.ops.empire_scaling import (
    AUTOMATION_THRESHOLD_SITES,
    CAPACITY_EXPANSION_PCT,
    CAPACITY_EXPERIMENTAL_PCT,
    CAPACITY_REFRESH_PCT,
    EXPANSION_TRIGGER_COUNT,
    KILL_NO_IMPRESSIONS_DAYS,
    KILL_NO_INDEX_DAYS,
    MAX_INFRA_COST_RATIO,
    MIN_WEEKS_BETWEEN_LAUNCHES,
    CapacityAllocation,
    DomainHealthScore,
    ExpansionTriggerCheck,
    ScalingStage,
    SiteMaturity,
    SiteMetrics,
    SiteVerdict,
    build_scaling_plan,
    check_expansion_triggers,
    check_kill_policy,
    check_validation_stage,
    classify_site_maturity,
    compute_capacity_allocation,
    compute_domain_health,
    decide_site_scaling,
    detect_niche_saturation,
    determine_scaling_stage,
    get_safe_publishing_rate,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _healthy_site(**kwargs) -> SiteMetrics:
    """A profitable, healthy site."""
    defaults = dict(
        site_id="site-healthy",
        niche="standing desks",
        age_days=120,
        total_pages=50,
        indexed_pages=45,
        monthly_impressions=5000,
        impressions_trend=0.15,
        monthly_clicks=500,
        converting_pages=5,
        monthly_revenue=800.0,
        monthly_cost=100.0,
        has_manual_penalty=False,
        avg_days_to_rank=25.0,
        ctr_trend=0.05,
        refresh_backlog=0,
        error_rate=1.0,
    )
    defaults.update(kwargs)
    return SiteMetrics(**defaults)


def _new_site(**kwargs) -> SiteMetrics:
    """A brand new site with minimal metrics."""
    defaults = dict(
        site_id="site-new",
        niche="headphones",
        age_days=15,
        total_pages=8,
        indexed_pages=5,
        monthly_impressions=50,
        impressions_trend=0.1,
        monthly_clicks=3,
        converting_pages=0,
        monthly_revenue=0.0,
        monthly_cost=30.0,
        has_manual_penalty=False,
        avg_days_to_rank=45.0,
        ctr_trend=0.0,
        refresh_backlog=0,
        error_rate=0.0,
    )
    defaults.update(kwargs)
    return SiteMetrics(**defaults)


def _dead_site(**kwargs) -> SiteMetrics:
    """A site that should be killed."""
    defaults = dict(
        site_id="site-dead",
        niche="obscure widgets",
        age_days=100,
        total_pages=15,
        indexed_pages=0,
        monthly_impressions=0,
        impressions_trend=0.0,
        monthly_clicks=0,
        converting_pages=0,
        monthly_revenue=0.0,
        monthly_cost=50.0,
        has_manual_penalty=False,
        avg_days_to_rank=999.0,
        ctr_trend=-0.1,
        refresh_backlog=5,
        error_rate=10.0,
    )
    defaults.update(kwargs)
    return SiteMetrics(**defaults)


def _saturated_site(**kwargs) -> SiteMetrics:
    """A site in a saturated niche."""
    defaults = dict(
        site_id="site-saturated",
        niche="phone cases",
        age_days=300,
        total_pages=150,
        indexed_pages=140,
        monthly_impressions=3000,
        impressions_trend=-0.05,
        monthly_clicks=200,
        converting_pages=8,
        monthly_revenue=400.0,
        monthly_cost=80.0,
        has_manual_penalty=False,
        avg_days_to_rank=95.0,
        ctr_trend=-0.1,
        refresh_backlog=0,
        error_rate=2.0,
    )
    defaults.update(kwargs)
    return SiteMetrics(**defaults)


def _validated_site(**kwargs) -> SiteMetrics:
    """A site that passes Stage 1 validation."""
    defaults = dict(
        site_id="site-validated",
        niche="gaming chairs",
        age_days=60,
        total_pages=30,
        indexed_pages=25,
        monthly_impressions=2000,
        impressions_trend=0.2,
        monthly_clicks=200,
        converting_pages=3,
        monthly_revenue=300.0,
        monthly_cost=60.0,
        has_manual_penalty=False,
        avg_days_to_rank=20.0,
        ctr_trend=0.1,
        refresh_backlog=0,
        error_rate=1.0,
    )
    defaults.update(kwargs)
    return SiteMetrics(**defaults)


# ---------------------------------------------------------------------------
# Tests — SiteMetrics properties
# ---------------------------------------------------------------------------

class TestSiteMetrics(unittest.TestCase):

    def test_index_coverage(self):
        site = _healthy_site(total_pages=100, indexed_pages=80)
        self.assertEqual(site.index_coverage, 80.0)

    def test_index_coverage_no_pages(self):
        site = _new_site(total_pages=0)
        self.assertEqual(site.index_coverage, 0.0)

    def test_revenue_per_page(self):
        site = _healthy_site(total_pages=50, monthly_revenue=500.0)
        self.assertEqual(site.revenue_per_page, 10.0)

    def test_roi(self):
        site = _healthy_site(monthly_revenue=800.0, monthly_cost=100.0)
        self.assertEqual(site.roi, 8.0)

    def test_roi_zero_cost(self):
        site = _healthy_site(monthly_cost=0)
        self.assertEqual(site.roi, 0.0)

    def test_is_profitable(self):
        self.assertTrue(_healthy_site().is_profitable)
        self.assertFalse(_dead_site().is_profitable)


# ---------------------------------------------------------------------------
# Tests — scaling stage determination
# ---------------------------------------------------------------------------

class TestScalingStage(unittest.TestCase):

    def test_no_sites_is_validation(self):
        self.assertEqual(determine_scaling_stage([]), ScalingStage.VALIDATION)

    def test_no_profitable_is_validation(self):
        self.assertEqual(
            determine_scaling_stage([_new_site()]),
            ScalingStage.VALIDATION,
        )

    def test_one_profitable_is_replication(self):
        self.assertEqual(
            determine_scaling_stage([_healthy_site()]),
            ScalingStage.REPLICATION,
        )

    def test_two_profitable_is_replication(self):
        self.assertEqual(
            determine_scaling_stage([_healthy_site(), _healthy_site(site_id="s2")]),
            ScalingStage.REPLICATION,
        )

    def test_three_sites_is_portfolio(self):
        sites = [_healthy_site(site_id=f"s{i}") for i in range(3)]
        self.assertEqual(determine_scaling_stage(sites), ScalingStage.PORTFOLIO)

    def test_ten_sites_is_empire(self):
        sites = [_healthy_site(site_id=f"s{i}") for i in range(10)]
        self.assertEqual(determine_scaling_stage(sites), ScalingStage.EMPIRE)


# ---------------------------------------------------------------------------
# Tests — site maturity
# ---------------------------------------------------------------------------

class TestSiteMaturity(unittest.TestCase):

    def test_new_site(self):
        self.assertEqual(classify_site_maturity(_new_site(age_days=15)), SiteMaturity.NEW)

    def test_growing_site(self):
        site = _healthy_site(age_days=90, total_pages=30)
        self.assertEqual(classify_site_maturity(site), SiteMaturity.GROWING)

    def test_authority_site(self):
        site = _healthy_site(age_days=200, total_pages=100, indexed_pages=80)
        self.assertEqual(classify_site_maturity(site), SiteMaturity.AUTHORITY)

    def test_publishing_rate_new(self):
        min_rate, max_rate = get_safe_publishing_rate(SiteMaturity.NEW)
        self.assertEqual(min_rate, 2)
        self.assertEqual(max_rate, 4)

    def test_publishing_rate_growing(self):
        min_rate, max_rate = get_safe_publishing_rate(SiteMaturity.GROWING)
        self.assertEqual(min_rate, 4)
        self.assertEqual(max_rate, 8)

    def test_publishing_rate_authority(self):
        min_rate, max_rate = get_safe_publishing_rate(SiteMaturity.AUTHORITY)
        self.assertEqual(min_rate, 8)
        self.assertEqual(max_rate, 15)


# ---------------------------------------------------------------------------
# Tests — domain health
# ---------------------------------------------------------------------------

class TestDomainHealth(unittest.TestCase):

    def test_healthy_site_perfect_score(self):
        health = compute_domain_health(_healthy_site())
        self.assertEqual(health.score, 100.0)
        self.assertTrue(health.is_healthy)

    def test_dead_site_zero_score(self):
        health = compute_domain_health(_dead_site())
        self.assertEqual(health.score, 0.0)
        self.assertFalse(health.is_healthy)

    def test_partial_health(self):
        site = _healthy_site(impressions_trend=-0.1, refresh_backlog=3)
        health = compute_domain_health(site)
        self.assertEqual(health.score, 50.0)  # index + error ok, impressions + refresh fail
        self.assertFalse(health.is_healthy)

    def test_high_error_rate_fails(self):
        site = _healthy_site(error_rate=10.0)
        health = compute_domain_health(site)
        self.assertFalse(health.error_rate_ok)


# ---------------------------------------------------------------------------
# Tests — niche saturation
# ---------------------------------------------------------------------------

class TestNicheSaturation(unittest.TestCase):

    def test_saturated_site_detected(self):
        self.assertTrue(detect_niche_saturation(_saturated_site()))

    def test_healthy_site_not_saturated(self):
        self.assertFalse(detect_niche_saturation(_healthy_site()))

    def test_needs_two_signals(self):
        # Only slow ranking, but impressions and CTR fine
        site = _healthy_site(avg_days_to_rank=100, impressions_trend=0.1, ctr_trend=0.05)
        self.assertFalse(detect_niche_saturation(site))


# ---------------------------------------------------------------------------
# Tests — kill-fast policy
# ---------------------------------------------------------------------------

class TestKillPolicy(unittest.TestCase):

    def test_zero_indexing_triggers_kill(self):
        site = _new_site(age_days=50, indexed_pages=0)
        self.assertTrue(check_kill_policy(site))

    def test_zero_impressions_triggers_kill(self):
        site = _new_site(age_days=65, indexed_pages=5, monthly_impressions=0)
        self.assertTrue(check_kill_policy(site))

    def test_young_site_not_killed(self):
        site = _new_site(age_days=20, indexed_pages=0)
        self.assertFalse(check_kill_policy(site))

    def test_healthy_site_not_killed(self):
        self.assertFalse(check_kill_policy(_healthy_site()))


# ---------------------------------------------------------------------------
# Tests — per-site scaling decisions
# ---------------------------------------------------------------------------

class TestSiteDecision(unittest.TestCase):

    def test_healthy_site_expands(self):
        decision = decide_site_scaling(_healthy_site())
        self.assertEqual(decision.verdict, SiteVerdict.EXPAND)
        self.assertGreater(decision.max_pages_per_week, 0)

    def test_dead_site_killed(self):
        decision = decide_site_scaling(_dead_site())
        self.assertEqual(decision.verdict, SiteVerdict.KILL)
        self.assertEqual(decision.max_pages_per_week, 0)

    def test_saturated_site_flagged(self):
        decision = decide_site_scaling(_saturated_site())
        self.assertEqual(decision.verdict, SiteVerdict.SATURATED)
        self.assertEqual(decision.max_pages_per_week, 0)

    def test_unhealthy_site_refresh_only(self):
        site = _healthy_site(impressions_trend=-0.1, refresh_backlog=5, error_rate=8.0)
        decision = decide_site_scaling(site)
        self.assertEqual(decision.verdict, SiteVerdict.REFRESH_ONLY)

    def test_penalized_site_held(self):
        site = _healthy_site(has_manual_penalty=True)
        decision = decide_site_scaling(site)
        self.assertEqual(decision.verdict, SiteVerdict.HOLD)

    def test_decision_includes_reasons(self):
        decision = decide_site_scaling(_healthy_site())
        self.assertGreater(len(decision.reasons), 0)


# ---------------------------------------------------------------------------
# Tests — expansion triggers
# ---------------------------------------------------------------------------

class TestExpansionTriggers(unittest.TestCase):

    def test_healthy_portfolio_can_expand(self):
        sites = [_healthy_site(site_id=f"s{i}") for i in range(5)]
        check = check_expansion_triggers(sites)
        self.assertTrue(check.revenue_increasing)
        self.assertTrue(check.indexing_stable)
        self.assertTrue(check.no_penalties)
        self.assertTrue(check.can_expand)
        self.assertGreaterEqual(check.triggers_met, EXPANSION_TRIGGER_COUNT)

    def test_empty_portfolio_cannot_expand(self):
        check = check_expansion_triggers([])
        self.assertFalse(check.can_expand)
        self.assertEqual(check.triggers_met, 0)

    def test_penalty_blocks_trigger(self):
        sites = [_healthy_site(has_manual_penalty=True)]
        check = check_expansion_triggers(sites)
        self.assertFalse(check.no_penalties)

    def test_high_infra_cost_blocks(self):
        # Cost > 20% of revenue
        site = _healthy_site(monthly_revenue=100, monthly_cost=30)
        check = check_expansion_triggers([site])
        self.assertFalse(check.infra_costs_safe)


# ---------------------------------------------------------------------------
# Tests — capacity allocation
# ---------------------------------------------------------------------------

class TestCapacityAllocation(unittest.TestCase):

    def test_default_allocation(self):
        cap = compute_capacity_allocation()
        self.assertEqual(cap.refresh_capacity, 60.0)
        self.assertEqual(cap.expansion_capacity, 30.0)
        self.assertEqual(cap.experimental_capacity, 10.0)

    def test_custom_total(self):
        cap = compute_capacity_allocation(total_capacity=200.0)
        self.assertEqual(cap.refresh_capacity, 120.0)
        self.assertEqual(cap.expansion_capacity, 60.0)
        self.assertEqual(cap.experimental_capacity, 20.0)

    def test_percentages_sum_to_100(self):
        total = CAPACITY_REFRESH_PCT + CAPACITY_EXPANSION_PCT + CAPACITY_EXPERIMENTAL_PCT
        self.assertEqual(total, 100)


# ---------------------------------------------------------------------------
# Tests — validation stage check
# ---------------------------------------------------------------------------

class TestValidationCheck(unittest.TestCase):

    def test_validated_site_passes(self):
        self.assertTrue(check_validation_stage([_validated_site()]))

    def test_new_site_fails(self):
        self.assertFalse(check_validation_stage([_new_site()]))

    def test_empty_fails(self):
        self.assertFalse(check_validation_stage([]))

    def test_needs_all_criteria(self):
        # Missing converting pages
        site = _validated_site(converting_pages=0)
        self.assertFalse(check_validation_stage([site]))


# ---------------------------------------------------------------------------
# Tests — full scaling plan
# ---------------------------------------------------------------------------

class TestBuildScalingPlan(unittest.TestCase):

    def test_single_healthy_site(self):
        plan = build_scaling_plan([_validated_site()])
        self.assertEqual(plan.stage, ScalingStage.REPLICATION)
        self.assertEqual(plan.total_sites, 1)
        self.assertGreater(plan.portfolio_roi, 0)

    def test_empty_portfolio(self):
        plan = build_scaling_plan([])
        self.assertEqual(plan.stage, ScalingStage.VALIDATION)
        self.assertFalse(plan.can_launch_new_site)

    def test_portfolio_stage(self):
        sites = [_healthy_site(site_id=f"s{i}") for i in range(5)]
        plan = build_scaling_plan(sites, weeks_since_last_launch=6)
        self.assertEqual(plan.stage, ScalingStage.PORTFOLIO)
        self.assertTrue(plan.can_launch_new_site)
        self.assertEqual(plan.next_launch_weeks, 0)

    def test_staggered_launch_enforced(self):
        sites = [_healthy_site(site_id=f"s{i}") for i in range(5)]
        plan = build_scaling_plan(sites, weeks_since_last_launch=1)
        self.assertFalse(plan.can_launch_new_site)
        self.assertGreater(plan.next_launch_weeks, 0)

    def test_saturated_niches_detected(self):
        sites = [_healthy_site(), _saturated_site()]
        plan = build_scaling_plan(sites)
        self.assertIn("phone cases", plan.saturated_niches)

    def test_kill_candidates_counted(self):
        sites = [_healthy_site(), _dead_site()]
        plan = build_scaling_plan(sites)
        self.assertEqual(plan.kill_candidates, 1)

    def test_automation_threshold(self):
        sites = [_healthy_site(site_id=f"s{i}") for i in range(50)]
        plan = build_scaling_plan(sites)
        self.assertTrue(plan.needs_automation_upgrade)

    def test_under_automation_threshold(self):
        sites = [_healthy_site(site_id=f"s{i}") for i in range(10)]
        plan = build_scaling_plan(sites)
        self.assertFalse(plan.needs_automation_upgrade)

    def test_capacity_allocation_present(self):
        plan = build_scaling_plan([_healthy_site()], total_capacity=200)
        self.assertEqual(plan.capacity.refresh_capacity, 120.0)

    def test_validation_stage_blocks_launch(self):
        plan = build_scaling_plan([_new_site()])
        self.assertEqual(plan.stage, ScalingStage.VALIDATION)
        self.assertFalse(plan.can_launch_new_site)

    def test_validation_allows_launch_when_validated(self):
        # Validated site is in REPLICATION stage — needs staggered cadence met
        plan = build_scaling_plan([_validated_site()], weeks_since_last_launch=5)
        self.assertTrue(plan.can_launch_new_site)

    def test_empire_stage(self):
        sites = [_healthy_site(site_id=f"s{i}") for i in range(12)]
        plan = build_scaling_plan(sites, weeks_since_last_launch=5)
        self.assertEqual(plan.stage, ScalingStage.EMPIRE)
        self.assertTrue(plan.can_launch_new_site)

    def test_healthy_sites_counted(self):
        sites = [_healthy_site(), _dead_site(), _saturated_site()]
        plan = build_scaling_plan(sites)
        self.assertEqual(plan.healthy_sites, 1)


if __name__ == "__main__":
    unittest.main()
