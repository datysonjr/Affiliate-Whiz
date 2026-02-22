"""Unit tests for the OpenClaw Article Refresh Engine."""

import unittest

from src.domains.seo.article_refresh import (
    MONEY_PAGE_REFRESH_DAYS,
    SUPPORT_PAGE_REFRESH_DAYS,
    INFORMATIONAL_PAGE_REFRESH_DAYS,
    ArticleStatus,
    PageCategory,
    RefreshAction,
    RefreshTrigger,
    RefreshUrgency,
    check_age_trigger,
    check_product_change,
    check_ranking_plateau,
    compute_refresh_priority,
    determine_refresh_actions,
    evaluate_refresh_queue,
    get_refresh_cycle,
    plan_refresh,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _money_article(**kwargs) -> ArticleStatus:
    """A money page with default attributes."""
    defaults = dict(
        url="/best-standing-desks",
        title="Best Standing Desks 2026",
        page_category=PageCategory.MONEY,
        published_days_ago=60,
        last_refreshed_days_ago=0,
        current_position=15.0,
        impressions=500,
        clicks=5,
        has_product_changes=False,
        word_count=3000,
        internal_link_count=8,
    )
    defaults.update(kwargs)
    return ArticleStatus(**defaults)


def _support_article(**kwargs) -> ArticleStatus:
    defaults = dict(
        url="/standing-desk-setup-guide",
        title="How to Set Up Your Standing Desk",
        page_category=PageCategory.SUPPORT,
        published_days_ago=100,
        last_refreshed_days_ago=0,
        current_position=8.0,
        impressions=200,
        clicks=30,
        has_product_changes=False,
        word_count=2000,
        internal_link_count=5,
    )
    defaults.update(kwargs)
    return ArticleStatus(**defaults)


def _fresh_article(**kwargs) -> ArticleStatus:
    defaults = dict(
        url="/new-article",
        title="Fresh Article",
        page_category=PageCategory.MONEY,
        published_days_ago=10,
        last_refreshed_days_ago=0,
        current_position=5.0,
        impressions=100,
        clicks=20,
        has_product_changes=False,
        word_count=2500,
        internal_link_count=6,
    )
    defaults.update(kwargs)
    return ArticleStatus(**defaults)


# ---------------------------------------------------------------------------
# Tests — refresh cycles
# ---------------------------------------------------------------------------

class TestRefreshCycles(unittest.TestCase):

    def test_money_page_cycle(self):
        self.assertEqual(get_refresh_cycle(PageCategory.MONEY), MONEY_PAGE_REFRESH_DAYS)

    def test_support_page_cycle(self):
        self.assertEqual(get_refresh_cycle(PageCategory.SUPPORT), SUPPORT_PAGE_REFRESH_DAYS)

    def test_informational_page_cycle(self):
        self.assertEqual(
            get_refresh_cycle(PageCategory.INFORMATIONAL),
            INFORMATIONAL_PAGE_REFRESH_DAYS,
        )


# ---------------------------------------------------------------------------
# Tests — age trigger
# ---------------------------------------------------------------------------

class TestAgeTrigger(unittest.TestCase):

    def test_old_money_page_triggers(self):
        article = _money_article(published_days_ago=60)
        trigger = check_age_trigger(article)
        self.assertEqual(trigger, RefreshTrigger.AGE)

    def test_fresh_page_no_trigger(self):
        article = _fresh_article(published_days_ago=10)
        trigger = check_age_trigger(article)
        self.assertIsNone(trigger)

    def test_refreshed_article_uses_refresh_age(self):
        article = _money_article(
            published_days_ago=200,
            last_refreshed_days_ago=10,
        )
        trigger = check_age_trigger(article)
        self.assertIsNone(trigger)  # last refresh was 10 days ago


# ---------------------------------------------------------------------------
# Tests — ranking plateau trigger
# ---------------------------------------------------------------------------

class TestRankingPlateau(unittest.TestCase):

    def test_plateau_detected(self):
        article = _money_article(
            current_position=18,
            impressions=1000,
            clicks=10,  # CTR = 1%
        )
        trigger = check_ranking_plateau(article)
        self.assertEqual(trigger, RefreshTrigger.RANKING_PLATEAU)

    def test_no_plateau_good_ctr(self):
        article = _money_article(
            current_position=15,
            impressions=100,
            clicks=10,  # CTR = 10%
        )
        trigger = check_ranking_plateau(article)
        self.assertIsNone(trigger)

    def test_no_plateau_top_position(self):
        article = _money_article(current_position=3)
        trigger = check_ranking_plateau(article)
        self.assertIsNone(trigger)

    def test_no_plateau_no_impressions(self):
        article = _money_article(current_position=20, impressions=0, clicks=0)
        trigger = check_ranking_plateau(article)
        self.assertIsNone(trigger)


# ---------------------------------------------------------------------------
# Tests — product change trigger
# ---------------------------------------------------------------------------

class TestProductChange(unittest.TestCase):

    def test_product_change_triggers(self):
        article = _money_article(has_product_changes=True)
        trigger = check_product_change(article)
        self.assertEqual(trigger, RefreshTrigger.PRODUCT_CHANGE)

    def test_no_product_change(self):
        article = _money_article(has_product_changes=False)
        trigger = check_product_change(article)
        self.assertIsNone(trigger)


# ---------------------------------------------------------------------------
# Tests — refresh actions
# ---------------------------------------------------------------------------

class TestRefreshActions(unittest.TestCase):

    def test_product_change_includes_expand_products(self):
        article = _money_article()
        actions = determine_refresh_actions(article, [RefreshTrigger.PRODUCT_CHANGE])
        self.assertIn(RefreshAction.EXPAND_PRODUCTS, actions)
        self.assertIn(RefreshAction.UPDATE_INTRO, actions)
        self.assertIn(RefreshAction.UPDATE_TIMESTAMP, actions)

    def test_plateau_includes_faq_and_links(self):
        article = _money_article(internal_link_count=2)
        actions = determine_refresh_actions(article, [RefreshTrigger.RANKING_PLATEAU])
        self.assertIn(RefreshAction.EXPAND_FAQ, actions)
        self.assertIn(RefreshAction.ADD_INTERNAL_LINKS, actions)

    def test_age_refresh_actions(self):
        article = _money_article(internal_link_count=2)
        actions = determine_refresh_actions(article, [RefreshTrigger.AGE])
        self.assertIn(RefreshAction.EXPAND_FAQ, actions)
        self.assertIn(RefreshAction.ADD_INTERNAL_LINKS, actions)

    def test_no_link_action_if_enough_links(self):
        article = _money_article(internal_link_count=10)
        actions = determine_refresh_actions(article, [RefreshTrigger.AGE])
        self.assertNotIn(RefreshAction.ADD_INTERNAL_LINKS, actions)


# ---------------------------------------------------------------------------
# Tests — priority scoring
# ---------------------------------------------------------------------------

class TestRefreshPriority(unittest.TestCase):

    def test_product_change_is_critical(self):
        article = _money_article()
        score, urgency = compute_refresh_priority(article, [RefreshTrigger.PRODUCT_CHANGE])
        self.assertEqual(urgency, RefreshUrgency.CRITICAL)
        self.assertGreater(score, 50)

    def test_plateau_is_high(self):
        article = _money_article()
        score, urgency = compute_refresh_priority(article, [RefreshTrigger.RANKING_PLATEAU])
        self.assertEqual(urgency, RefreshUrgency.HIGH)

    def test_age_only_is_normal(self):
        article = _money_article()
        score, urgency = compute_refresh_priority(article, [RefreshTrigger.AGE])
        self.assertEqual(urgency, RefreshUrgency.NORMAL)

    def test_money_pages_score_higher(self):
        money = _money_article()
        support = _support_article(published_days_ago=60)
        money_score, _ = compute_refresh_priority(money, [RefreshTrigger.AGE])
        support_score, _ = compute_refresh_priority(support, [RefreshTrigger.AGE])
        self.assertGreater(money_score, support_score)

    def test_multiple_triggers_stack(self):
        article = _money_article(has_product_changes=True)
        single_score, _ = compute_refresh_priority(article, [RefreshTrigger.AGE])
        multi_score, _ = compute_refresh_priority(
            article, [RefreshTrigger.AGE, RefreshTrigger.PRODUCT_CHANGE]
        )
        self.assertGreater(multi_score, single_score)


# ---------------------------------------------------------------------------
# Tests — single article plan
# ---------------------------------------------------------------------------

class TestPlanRefresh(unittest.TestCase):

    def test_old_article_gets_plan(self):
        article = _money_article(published_days_ago=60)
        plan = plan_refresh(article)
        self.assertIsNotNone(plan)
        self.assertIn(RefreshTrigger.AGE, plan.triggers)
        self.assertGreater(len(plan.actions), 0)

    def test_fresh_article_no_plan(self):
        article = _fresh_article()
        plan = plan_refresh(article)
        self.assertIsNone(plan)

    def test_product_change_generates_urgent_plan(self):
        article = _money_article(published_days_ago=10, has_product_changes=True)
        plan = plan_refresh(article)
        self.assertIsNotNone(plan)
        self.assertTrue(plan.is_urgent)
        self.assertIn(RefreshTrigger.PRODUCT_CHANGE, plan.triggers)

    def test_ctr_property(self):
        article = _money_article(impressions=1000, clicks=50)
        self.assertAlmostEqual(article.ctr, 0.05)

    def test_effective_age_uses_refresh(self):
        article = _money_article(
            published_days_ago=300,
            last_refreshed_days_ago=20,
        )
        self.assertEqual(article.effective_age_days, 20)


# ---------------------------------------------------------------------------
# Tests — batch evaluation
# ---------------------------------------------------------------------------

class TestEvaluateRefreshQueue(unittest.TestCase):

    def test_basic_queue(self):
        articles = [
            _money_article(published_days_ago=60),
            _fresh_article(published_days_ago=5),
            _support_article(published_days_ago=100),
        ]
        plans = evaluate_refresh_queue(articles)
        # Money (60d > 45d cycle) and support (100d > 90d cycle) need refresh
        self.assertEqual(len(plans), 2)

    def test_sorted_by_priority(self):
        articles = [
            _support_article(published_days_ago=100),
            _money_article(published_days_ago=60, has_product_changes=True),
        ]
        plans = evaluate_refresh_queue(articles)
        self.assertEqual(len(plans), 2)
        # Product change should be highest priority
        self.assertGreater(plans[0].priority_score, plans[1].priority_score)

    def test_empty_input(self):
        plans = evaluate_refresh_queue([])
        self.assertEqual(len(plans), 0)

    def test_no_articles_need_refresh(self):
        articles = [_fresh_article(published_days_ago=5)]
        plans = evaluate_refresh_queue(articles)
        self.assertEqual(len(plans), 0)


if __name__ == "__main__":
    unittest.main()
