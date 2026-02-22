"""Unit tests for the OpenClaw Trend Explosion Predictor."""

import unittest

from src.domains.seo.trend_predictor import (
    ACTIVATION_THRESHOLD,
    NichePriority,
    NicheTrendReport,
    SignalLevel,
    SignalSource,
    TrendSignal,
    analyze_niche,
    check_multi_signal_confirmation,
    compute_trend_score,
    generate_explosion_playbook,
    get_signal_level,
    has_purchase_intent,
    predict_explosions,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _supply_signal(niche: str = "ai headphones", strength: float = 0.8) -> TrendSignal:
    return TrendSignal(niche=niche, source=SignalSource.AMAZON_NEW_SKU, strength=strength,
                       description="New SKUs appearing on Amazon")

def _industry_signal(niche: str = "ai headphones", strength: float = 0.7) -> TrendSignal:
    return TrendSignal(niche=niche, source=SignalSource.VC_FUNDING, strength=strength,
                       description="$10M funding round for audio AI startup")

def _creator_signal(niche: str = "ai headphones", strength: float = 0.6) -> TrendSignal:
    return TrendSignal(niche=niche, source=SignalSource.YOUTUBE_COVERAGE, strength=strength,
                       description="Multiple YouTube reviews appearing")

def _consumer_signal(niche: str = "ai headphones", strength: float = 0.5) -> TrendSignal:
    return TrendSignal(niche=niche, source=SignalSource.REDDIT_SPIKE, strength=strength,
                       description="Reddit buying questions spiking")

def _search_signal(niche: str = "ai headphones", strength: float = 0.4) -> TrendSignal:
    return TrendSignal(niche=niche, source=SignalSource.GOOGLE_TRENDS_SPIKE, strength=strength,
                       description="Google Trends showing uptick")


# ---------------------------------------------------------------------------
# Tests — signal level mapping
# ---------------------------------------------------------------------------

class TestSignalLevel(unittest.TestCase):

    def test_amazon_is_supply(self):
        self.assertEqual(get_signal_level(SignalSource.AMAZON_NEW_SKU), SignalLevel.SUPPLY)

    def test_vc_is_industry(self):
        self.assertEqual(get_signal_level(SignalSource.VC_FUNDING), SignalLevel.INDUSTRY)

    def test_youtube_is_creator(self):
        self.assertEqual(get_signal_level(SignalSource.YOUTUBE_COVERAGE), SignalLevel.CREATOR)

    def test_reddit_is_consumer(self):
        self.assertEqual(get_signal_level(SignalSource.REDDIT_SPIKE), SignalLevel.CONSUMER)

    def test_google_trends_is_search(self):
        self.assertEqual(get_signal_level(SignalSource.GOOGLE_TRENDS_SPIKE), SignalLevel.SEARCH_VOLUME)

    def test_signal_level_property(self):
        s = _supply_signal()
        self.assertEqual(s.level, SignalLevel.SUPPLY)
        self.assertEqual(s.level_name, "supply")


# ---------------------------------------------------------------------------
# Tests — multi-signal confirmation
# ---------------------------------------------------------------------------

class TestMultiSignalConfirmation(unittest.TestCase):

    def test_two_levels_confirms(self):
        signals = [_supply_signal(), _creator_signal()]
        confirmed, levels = check_multi_signal_confirmation(signals)
        self.assertTrue(confirmed)
        self.assertEqual(len(levels), 2)

    def test_single_level_does_not_confirm(self):
        signals = [_supply_signal(), _supply_signal()]
        confirmed, _ = check_multi_signal_confirmation(signals)
        self.assertFalse(confirmed)

    def test_search_only_does_not_confirm(self):
        signals = [_search_signal(), _search_signal()]
        confirmed, _ = check_multi_signal_confirmation(signals)
        self.assertFalse(confirmed)

    def test_search_plus_one_does_not_confirm(self):
        # Search is excluded from confirmation — need 2 non-search levels
        signals = [_search_signal(), _consumer_signal()]
        confirmed, _ = check_multi_signal_confirmation(signals)
        self.assertFalse(confirmed)

    def test_three_levels_confirms(self):
        signals = [_supply_signal(), _industry_signal(), _creator_signal()]
        confirmed, levels = check_multi_signal_confirmation(signals)
        self.assertTrue(confirmed)
        self.assertEqual(len(levels), 3)

    def test_empty_signals(self):
        confirmed, levels = check_multi_signal_confirmation([])
        self.assertFalse(confirmed)
        self.assertEqual(len(levels), 0)


# ---------------------------------------------------------------------------
# Tests — trend score
# ---------------------------------------------------------------------------

class TestComputeTrendScore(unittest.TestCase):

    def test_max_score(self):
        # All levels at full strength: 4+3+3+2+1 = 13
        signals = [
            _supply_signal(strength=1.0),
            _industry_signal(strength=1.0),
            _creator_signal(strength=1.0),
            _consumer_signal(strength=1.0),
            _search_signal(strength=1.0),
        ]
        score = compute_trend_score(signals)
        self.assertEqual(score, 13.0)

    def test_supply_only(self):
        signals = [_supply_signal(strength=1.0)]
        score = compute_trend_score(signals)
        self.assertEqual(score, 4.0)

    def test_strength_scales_weight(self):
        signals = [_supply_signal(strength=0.5)]
        score = compute_trend_score(signals)
        self.assertEqual(score, 2.0)  # 4 * 0.5

    def test_best_signal_per_level(self):
        # Two supply signals — only strongest counts
        signals = [_supply_signal(strength=0.3), _supply_signal(strength=0.9)]
        score = compute_trend_score(signals)
        self.assertEqual(score, 3.6)  # 4 * 0.9

    def test_empty_signals(self):
        score = compute_trend_score([])
        self.assertEqual(score, 0.0)


# ---------------------------------------------------------------------------
# Tests — explosion playbook
# ---------------------------------------------------------------------------

class TestExplosionPlaybook(unittest.TestCase):

    def test_generates_6_pages(self):
        playbook = generate_explosion_playbook("AI Headphones")
        self.assertEqual(len(playbook), 6)

    def test_contains_niche_name(self):
        playbook = generate_explosion_playbook("Smart Rings")
        for title in playbook:
            self.assertIn("Smart Rings", title)

    def test_has_buying_guide(self):
        playbook = generate_explosion_playbook("Widgets")
        self.assertTrue(any("Buying Guide" in t for t in playbook))

    def test_has_faq(self):
        playbook = generate_explosion_playbook("Widgets")
        self.assertTrue(any("FAQ" in t for t in playbook))

    def test_has_alternatives(self):
        playbook = generate_explosion_playbook("Widgets")
        self.assertTrue(any("Alternative" in t for t in playbook))


# ---------------------------------------------------------------------------
# Tests — purchase intent detection
# ---------------------------------------------------------------------------

class TestPurchaseIntent(unittest.TestCase):

    def test_supply_signal_implies_intent(self):
        self.assertTrue(has_purchase_intent("widgets", [_supply_signal("widgets")]))

    def test_industry_signal_implies_intent(self):
        self.assertTrue(has_purchase_intent("widgets", [_industry_signal("widgets")]))

    def test_description_with_buy_language(self):
        s = TrendSignal(niche="widgets", source=SignalSource.REDDIT_SPIKE,
                        description="People asking where to buy widgets")
        self.assertTrue(has_purchase_intent("widgets", [s]))

    def test_niche_name_with_review(self):
        self.assertTrue(has_purchase_intent("best widget review", [_consumer_signal()]))

    def test_no_intent_detected(self):
        s = TrendSignal(niche="philosophy", source=SignalSource.REDDIT_SPIKE,
                        description="Discussion about epistemology")
        self.assertFalse(has_purchase_intent("philosophy", [s]))


# ---------------------------------------------------------------------------
# Tests — analyze_niche
# ---------------------------------------------------------------------------

class TestAnalyzeNiche(unittest.TestCase):

    def test_activated_niche(self):
        signals = [
            _supply_signal(strength=1.0),   # 4 pts
            _creator_signal(strength=1.0),   # 3 pts
        ]
        report = analyze_niche("ai headphones", signals)
        self.assertTrue(report.confirmed)
        self.assertEqual(report.trend_score, 7.0)
        self.assertTrue(report.should_activate)
        self.assertEqual(len(report.explosion_playbook), 6)
        self.assertTrue(report.is_early_mover_opportunity)

    def test_below_threshold(self):
        signals = [_consumer_signal(strength=0.5)]  # 1 pt
        report = analyze_niche("novelty socks", signals)
        self.assertFalse(report.should_activate)
        self.assertEqual(len(report.explosion_playbook), 0)

    def test_not_confirmed_despite_high_score(self):
        # High score from single level — doesn't meet multi-signal rule
        signals = [_supply_signal(strength=1.0)]  # 4 pts, but only 1 level
        report = analyze_niche("widgets", signals)
        self.assertFalse(report.confirmed)
        self.assertFalse(report.should_activate)

    def test_earliest_signal_level(self):
        signals = [_creator_signal(), _consumer_signal()]
        report = analyze_niche("gadgets", signals)
        self.assertEqual(report.earliest_signal_level, SignalLevel.CREATOR)


# ---------------------------------------------------------------------------
# Tests — full pipeline
# ---------------------------------------------------------------------------

class TestPredictExplosions(unittest.TestCase):

    def test_basic_pipeline(self):
        signals = [
            _supply_signal("smart rings", 0.9),
            _creator_signal("smart rings", 0.8),
            _consumer_signal("smart rings", 0.7),
        ]
        reports = predict_explosions(signals)
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0].niche, "smart rings")
        self.assertTrue(reports[0].should_activate)

    def test_multiple_niches(self):
        signals = [
            _supply_signal("smart rings", 0.9),
            _industry_signal("smart rings", 0.8),
            _supply_signal("ai glasses", 1.0),
            _creator_signal("ai glasses", 0.9),
        ]
        reports = predict_explosions(signals)
        self.assertEqual(len(reports), 2)
        # AI glasses should rank first (higher score)
        self.assertEqual(reports[0].niche, "ai glasses")

    def test_filters_non_activated(self):
        signals = [_search_signal("fad toys", 0.3)]
        reports = predict_explosions(signals)
        self.assertEqual(len(reports), 0)

    def test_filters_no_purchase_intent(self):
        signals = [
            TrendSignal(niche="philosophy", source=SignalSource.REDDIT_SPIKE,
                        strength=0.8, description="Debate about ethics"),
            TrendSignal(niche="philosophy", source=SignalSource.FORUM_QUESTIONS,
                        strength=0.7, description="Discussion threads"),
        ]
        reports = predict_explosions(signals, require_purchase_intent=True)
        self.assertEqual(len(reports), 0)

    def test_skip_purchase_intent_filter(self):
        # Need 2 distinct non-search levels + score >= 6
        # Supply (4) + Creator (3) = 7, confirmed with 2 levels
        signals = [
            TrendSignal(niche="philosophy", source=SignalSource.CROWDFUNDING_LAUNCH,
                        strength=1.0, description="New crowdfunding campaign"),
            TrendSignal(niche="philosophy", source=SignalSource.YOUTUBE_COVERAGE,
                        strength=1.0, description="Creator videos appearing"),
        ]
        reports = predict_explosions(signals, require_purchase_intent=False)
        self.assertEqual(len(reports), 1)

    def test_niche_priorities(self):
        signals = [
            _supply_signal("vr headsets", 0.9),
            _creator_signal("vr headsets", 0.8),
        ]
        reports = predict_explosions(
            signals,
            niche_priorities={"vr headsets": NichePriority.EVOLVING_TECH},
        )
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0].priority, NichePriority.EVOLVING_TECH)

    def test_empty_signals(self):
        reports = predict_explosions([])
        self.assertEqual(len(reports), 0)


if __name__ == "__main__":
    unittest.main()
