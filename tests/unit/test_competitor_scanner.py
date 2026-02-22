"""Unit tests for the OpenClaw Competitor Weakness Scanner."""

import unittest

from src.domains.seo.competitor_scanner import (
    ATTACKABLE_WEAKNESS_THRESHOLD,
    AttackPriority,
    CompetitorPage,
    PageWeaknessReport,
    SERPWeaknessReport,
    WeaknessType,
    classify_attack_priority,
    detect_bad_ux,
    detect_outdated,
    detect_poor_linking,
    detect_thin_content,
    detect_weak_domain,
    generate_attack_strategy,
    scan_multiple_serps,
    scan_serp_weaknesses,
    score_competitor_page,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strong_page(**kwargs) -> CompetitorPage:
    """A strong competitor page with no weaknesses."""
    defaults = dict(
        url="https://strong.com/best-widgets",
        position=1,
        word_count=3000,
        heading_count=10,
        last_updated_year=2026,
        internal_link_count=15,
        domain_authority=75,
        has_comparison_table=True,
        has_faq_section=True,
        has_excessive_ads=False,
        page_load_score=90,
    )
    defaults.update(kwargs)
    return CompetitorPage(**defaults)


def _weak_page(**kwargs) -> CompetitorPage:
    """A weak competitor page with many weaknesses."""
    defaults = dict(
        url="https://weak-blog.com/widgets",
        position=5,
        word_count=400,
        heading_count=1,
        last_updated_year=2022,
        internal_link_count=0,
        domain_authority=10,
        has_comparison_table=False,
        has_faq_section=False,
        has_excessive_ads=True,
        page_load_score=30,
    )
    defaults.update(kwargs)
    return CompetitorPage(**defaults)


# ---------------------------------------------------------------------------
# Tests — thin content detection
# ---------------------------------------------------------------------------

class TestDetectThinContent(unittest.TestCase):

    def test_short_article_scores_high(self):
        page = _weak_page(word_count=200, heading_count=1)
        signal = detect_thin_content(page)
        self.assertEqual(signal.weakness_type, WeaknessType.THIN_CONTENT)
        self.assertGreater(signal.score, 10)

    def test_long_article_scores_zero(self):
        page = _strong_page(word_count=3000, heading_count=10)
        signal = detect_thin_content(page)
        self.assertEqual(signal.score, 0.0)

    def test_few_headings_adds_score(self):
        page = _weak_page(word_count=1500, heading_count=1)
        signal = detect_thin_content(page)
        self.assertGreater(signal.score, 0)


# ---------------------------------------------------------------------------
# Tests — outdated detection
# ---------------------------------------------------------------------------

class TestDetectOutdated(unittest.TestCase):

    def test_old_year_scores_high(self):
        page = _weak_page(last_updated_year=2022)
        signal = detect_outdated(page)
        self.assertEqual(signal.weakness_type, WeaknessType.OUTDATED)
        self.assertGreater(signal.score, 10)

    def test_current_year_scores_zero(self):
        page = _strong_page(last_updated_year=2026)
        signal = detect_outdated(page)
        self.assertEqual(signal.score, 0.0)

    def test_unknown_year_gets_mild_score(self):
        page = _weak_page(last_updated_year=0)
        signal = detect_outdated(page)
        self.assertEqual(signal.score, 5.0)


# ---------------------------------------------------------------------------
# Tests — poor linking detection
# ---------------------------------------------------------------------------

class TestDetectPoorLinking(unittest.TestCase):

    def test_zero_links_scores_max(self):
        page = _weak_page(internal_link_count=0)
        signal = detect_poor_linking(page)
        self.assertEqual(signal.score, 20.0)

    def test_few_links_scores_moderate(self):
        page = _weak_page(internal_link_count=2)
        signal = detect_poor_linking(page)
        self.assertEqual(signal.score, 14.0)

    def test_many_links_scores_zero(self):
        page = _strong_page(internal_link_count=20)
        signal = detect_poor_linking(page)
        self.assertEqual(signal.score, 0.0)


# ---------------------------------------------------------------------------
# Tests — weak domain detection
# ---------------------------------------------------------------------------

class TestDetectWeakDomain(unittest.TestCase):

    def test_low_da_scores_high(self):
        page = _weak_page(domain_authority=5)
        signal = detect_weak_domain(page)
        self.assertGreater(signal.score, 15)

    def test_high_da_scores_zero(self):
        page = _strong_page(domain_authority=75)
        signal = detect_weak_domain(page)
        self.assertEqual(signal.score, 0.0)


# ---------------------------------------------------------------------------
# Tests — bad UX detection
# ---------------------------------------------------------------------------

class TestDetectBadUX(unittest.TestCase):

    def test_all_ux_problems(self):
        page = _weak_page(
            has_comparison_table=False,
            has_faq_section=False,
            has_excessive_ads=True,
            page_load_score=30,
        )
        signal = detect_bad_ux(page)
        self.assertEqual(signal.score, 20.0)

    def test_no_ux_problems(self):
        page = _strong_page()
        signal = detect_bad_ux(page)
        self.assertEqual(signal.score, 0.0)

    def test_partial_ux_problems(self):
        page = _weak_page(
            has_comparison_table=True,
            has_faq_section=False,
            has_excessive_ads=False,
            page_load_score=80,
        )
        signal = detect_bad_ux(page)
        self.assertEqual(signal.score, 5.0)


# ---------------------------------------------------------------------------
# Tests — page-level scoring
# ---------------------------------------------------------------------------

class TestScoreCompetitorPage(unittest.TestCase):

    def test_weak_page_high_score(self):
        report = score_competitor_page(_weak_page())
        self.assertGreater(report.total_score, 50)
        self.assertGreater(len(report.weaknesses), 3)

    def test_strong_page_low_score(self):
        report = score_competitor_page(_strong_page())
        self.assertEqual(report.total_score, 0.0)
        self.assertEqual(len(report.weaknesses), 0)

    def test_primary_weakness(self):
        report = score_competitor_page(_weak_page())
        self.assertIsNotNone(report.primary_weakness)


# ---------------------------------------------------------------------------
# Tests — attack strategy
# ---------------------------------------------------------------------------

class TestAttackStrategy(unittest.TestCase):

    def test_generates_5_articles(self):
        strategy = generate_attack_strategy("standing desks")
        self.assertEqual(len(strategy), 5)

    def test_contains_keyword(self):
        strategy = generate_attack_strategy("gaming chairs")
        for title in strategy:
            self.assertIn("gaming chairs", title)


# ---------------------------------------------------------------------------
# Tests — attack priority
# ---------------------------------------------------------------------------

class TestAttackPriority(unittest.TestCase):

    def test_immediate(self):
        self.assertEqual(classify_attack_priority(70), AttackPriority.IMMEDIATE)

    def test_high(self):
        self.assertEqual(classify_attack_priority(55), AttackPriority.HIGH)

    def test_moderate(self):
        self.assertEqual(classify_attack_priority(35), AttackPriority.MODERATE)

    def test_low(self):
        self.assertEqual(classify_attack_priority(20), AttackPriority.LOW)


# ---------------------------------------------------------------------------
# Tests — SERP-level scanning
# ---------------------------------------------------------------------------

class TestScanSERPWeaknesses(unittest.TestCase):

    def test_weak_serp_is_attackable(self):
        competitors = [_weak_page(position=i) for i in range(1, 6)]
        report = scan_serp_weaknesses("best widgets", competitors)
        self.assertTrue(report.is_attackable)
        self.assertGreater(report.weakness_total, ATTACKABLE_WEAKNESS_THRESHOLD)
        self.assertEqual(len(report.attack_strategy), 5)

    def test_strong_serp_not_attackable(self):
        competitors = [_strong_page(position=i) for i in range(1, 6)]
        report = scan_serp_weaknesses("best widgets", competitors)
        self.assertFalse(report.is_attackable)
        self.assertEqual(len(report.attack_strategy), 0)

    def test_empty_competitors(self):
        report = scan_serp_weaknesses("obscure query", [])
        self.assertEqual(report.weakness_total, 0.0)
        self.assertFalse(report.is_attackable)

    def test_weakest_page_property(self):
        competitors = [
            _strong_page(position=1),
            _weak_page(position=2),
        ]
        report = scan_serp_weaknesses("test keyword", competitors)
        self.assertIsNotNone(report.weakest_page)
        self.assertEqual(report.weakest_page.page.position, 2)


# ---------------------------------------------------------------------------
# Tests — batch scanning
# ---------------------------------------------------------------------------

class TestScanMultipleSERPs(unittest.TestCase):

    def test_filters_non_attackable(self):
        serp_data = {
            "weak keyword": [_weak_page(position=i) for i in range(1, 4)],
            "strong keyword": [_strong_page(position=i) for i in range(1, 4)],
        }
        reports = scan_multiple_serps(serp_data)
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0].keyword, "weak keyword")

    def test_sorted_by_weakness(self):
        serp_data = {
            "kw1": [_weak_page(position=1, word_count=800)],
            "kw2": [_weak_page(position=1, word_count=100)],
        }
        reports = scan_multiple_serps(serp_data)
        if len(reports) >= 2:
            self.assertGreaterEqual(reports[0].weakness_total, reports[1].weakness_total)

    def test_empty_input(self):
        reports = scan_multiple_serps({})
        self.assertEqual(len(reports), 0)


if __name__ == "__main__":
    unittest.main()
