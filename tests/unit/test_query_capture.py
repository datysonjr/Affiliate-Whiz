"""Unit tests for the OpenClaw AI Query Capture Engine."""

import unittest

from src.domains.seo.query_capture import (
    EmergingQuery,
    EmergingQueryType,
    build_authority_clusters,
    capture_emerging_queries,
    classify_buyer_intent,
    classify_query_type,
    compute_capture_score,
    expand_product_queries,
)


# ---------------------------------------------------------------------------
# Tests — buyer intent classification
# ---------------------------------------------------------------------------


class TestClassifyBuyerIntent(unittest.TestCase):
    def test_best_is_rank_1(self):
        self.assertEqual(classify_buyer_intent("best wireless earbuds"), 1)

    def test_vs_is_rank_2(self):
        self.assertEqual(classify_buyer_intent("AirPods vs Galaxy Buds"), 2)

    def test_comparison_is_rank_2(self):
        self.assertEqual(classify_buyer_intent("AirPods comparison"), 2)

    def test_worth_it_is_rank_3(self):
        self.assertEqual(classify_buyer_intent("is iPhone 16 worth it"), 3)

    def test_should_i_buy_is_rank_3(self):
        self.assertEqual(classify_buyer_intent("should I buy a standing desk"), 3)

    def test_review_is_rank_4(self):
        self.assertEqual(classify_buyer_intent("Sony WF-1000XM5 review"), 4)

    def test_alternatives_is_rank_5(self):
        self.assertEqual(classify_buyer_intent("alternatives to Notion"), 5)

    def test_no_intent_is_rank_6(self):
        self.assertEqual(classify_buyer_intent("what is bluetooth"), 6)


# ---------------------------------------------------------------------------
# Tests — query type classification
# ---------------------------------------------------------------------------


class TestClassifyQueryType(unittest.TestCase):
    def test_new_product_release(self):
        qt = classify_query_type("does iPhone 16 support USB-C")
        self.assertEqual(qt, EmergingQueryType.NEW_PRODUCT_RELEASE)

    def test_model_specific_decision(self):
        qt = classify_query_type("is Lenovo LOQ good for gaming")
        self.assertEqual(qt, EmergingQueryType.MODEL_SPECIFIC_DECISION)

    def test_problem_triggered(self):
        qt = classify_query_type("best mattress for back pain")
        self.assertEqual(qt, EmergingQueryType.PROBLEM_TRIGGERED)

    def test_new_category(self):
        qt = classify_query_type("best AI resume builders")
        self.assertEqual(qt, EmergingQueryType.NEW_CATEGORY)


# ---------------------------------------------------------------------------
# Tests — autocomplete expansion
# ---------------------------------------------------------------------------


class TestExpandProductQueries(unittest.TestCase):
    def test_expansion_count(self):
        queries = expand_product_queries("Sony WF-1000XM5")
        self.assertEqual(len(queries), 10)

    def test_contains_review(self):
        queries = expand_product_queries("iPhone 16")
        self.assertTrue(any("review" in q for q in queries))

    def test_contains_vs(self):
        queries = expand_product_queries("AirPods Pro")
        self.assertTrue(any("vs" in q for q in queries))

    def test_custom_templates(self):
        queries = expand_product_queries("Widget", templates=["{product} rocks"])
        self.assertEqual(queries, ["Widget rocks"])


# ---------------------------------------------------------------------------
# Tests — capture score
# ---------------------------------------------------------------------------


class TestComputeCaptureScore(unittest.TestCase):
    def test_perfect_conditions(self):
        score = compute_capture_score(
            buyer_intent_rank=1,
            content_supply=0,
            days_since_trigger=0,
            is_trending=True,
        )
        self.assertEqual(score, 100.0)

    def test_worst_conditions(self):
        score = compute_capture_score(
            buyer_intent_rank=6,
            content_supply=20,
            days_since_trigger=120,
            is_trending=False,
        )
        self.assertEqual(score, 5.0)

    def test_trending_bonus(self):
        base = compute_capture_score(
            buyer_intent_rank=3,
            content_supply=2,
            days_since_trigger=10,
            is_trending=False,
        )
        with_trend = compute_capture_score(
            buyer_intent_rank=3,
            content_supply=2,
            days_since_trigger=10,
            is_trending=True,
        )
        self.assertEqual(with_trend - base, 15.0)

    def test_score_in_range(self):
        score = compute_capture_score(
            buyer_intent_rank=3,
            content_supply=5,
            days_since_trigger=20,
        )
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)


# ---------------------------------------------------------------------------
# Tests — authority clusters
# ---------------------------------------------------------------------------


class TestBuildAuthorityClusters(unittest.TestCase):
    def test_groups_by_product(self):
        queries = [
            EmergingQuery(query="best Widget", product_name="Widget", capture_score=80),
            EmergingQuery(
                query="Widget review", product_name="Widget", capture_score=70
            ),
            EmergingQuery(query="best Gadget", product_name="Gadget", capture_score=90),
        ]
        clusters = build_authority_clusters(queries)
        self.assertEqual(len(clusters), 2)
        # Gadget should be first (higher score)
        self.assertEqual(clusters[0].product_name, "gadget")
        self.assertEqual(clusters[0].query_count, 1)
        self.assertEqual(clusters[1].product_name, "widget")
        self.assertEqual(clusters[1].query_count, 2)

    def test_empty_input(self):
        clusters = build_authority_clusters([])
        self.assertEqual(len(clusters), 0)


# ---------------------------------------------------------------------------
# Tests — full pipeline
# ---------------------------------------------------------------------------


class TestCaptureEmergingQueries(unittest.TestCase):
    def test_basic_pipeline(self):
        clusters = capture_emerging_queries(["Sony WF-1000XM5"])
        self.assertGreater(len(clusters), 0)
        # Should have 10 queries (from 10 templates)
        total_queries = sum(c.query_count for c in clusters)
        self.assertEqual(total_queries, 10)

    def test_multiple_products(self):
        clusters = capture_emerging_queries(["iPhone 16", "Galaxy S25"])
        total_queries = sum(c.query_count for c in clusters)
        self.assertEqual(total_queries, 20)

    def test_trending_boosts_score(self):
        base_clusters = capture_emerging_queries(["Widget"])
        trending_clusters = capture_emerging_queries(
            ["Widget"], trending_products={"Widget"}
        )
        base_avg = base_clusters[0].cluster_score
        trending_avg = trending_clusters[0].cluster_score
        self.assertGreater(trending_avg, base_avg)

    def test_auto_publish_queries_exist(self):
        clusters = capture_emerging_queries(["New Product 2026"])
        all_queries = [q for c in clusters for q in c.queries]
        auto_pub = [q for q in all_queries if q.should_auto_publish]
        # "best New Product 2026" should auto-publish (rank 1, 0 supply)
        self.assertGreater(len(auto_pub), 0)

    def test_first_page_window(self):
        clusters = capture_emerging_queries(
            ["Fresh Launch"],
            days_since_trigger_map={"fresh launch": 5},
        )
        all_queries = [q for c in clusters for q in c.queries]
        self.assertTrue(all(q.is_within_first_page_window for q in all_queries))

    def test_outside_first_page_window(self):
        clusters = capture_emerging_queries(
            ["Old Product"],
            days_since_trigger_map={"old product": 60},
        )
        all_queries = [q for c in clusters for q in c.queries]
        self.assertTrue(all(not q.is_within_first_page_window for q in all_queries))


if __name__ == "__main__":
    unittest.main()
