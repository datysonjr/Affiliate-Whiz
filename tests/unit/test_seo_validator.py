"""Unit tests for the OpenClaw SEO publishing validator."""

import unittest

from src.core.errors import ContentValidationError
from src.domains.seo.validator import (
    AI_DOMINATION_SCORE_MIN,
    MIN_INTERNAL_LINKS,
    MIN_VERDICT_STATEMENTS,
    SEOValidationResult,
    compute_ai_domination_score,
    enforce_seo,
    validate_seo,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_passing_article() -> str:
    """Return a minimal article that passes all SEO validation checks."""
    return """## Quick Answer — Our Top Picks

Best wireless earbuds for 2026 is:

1. Sony WF-1000XM5 — best overall
2. Samsung Galaxy Buds FE — best budget
3. Apple AirPods Pro 2 — best premium

We recommend the Sony WF-1000XM5 for most people.

| Feature | Sony WF-1000XM5 | Galaxy Buds FE | AirPods Pro 2 |
|---------|-----------------|----------------|---------------|
| Price   | $279            | $99            | $249          |
| ANC     | Yes             | Yes            | Yes           |
| Battery | 8h              | 6h             | 6h            |

## Why We Chose These

Our top pick is the Sony WF-1000XM5 due to its class-leading noise
cancellation and sound quality. The best budget option is the Galaxy
Buds FE which punches well above its price.

Verdict: Sony WF-1000XM5 takes the crown for audiophiles.

## How to Choose Wireless Earbuds

Consider battery life, comfort, and ANC performance.

## Real-World Scenarios

Best for commuters: Sony WF-1000XM5.
Best for gym: Galaxy Buds FE.

[Related: Best Noise Cancelling Headphones](/best-noise-cancelling-headphones)
[Related: Wireless Earbuds Under $50](/wireless-earbuds-under-50)
[See also: How to Clean Earbuds](/how-to-clean-earbuds)
[Guide: Bluetooth Codecs Explained](/bluetooth-codecs-explained)
[More: Best Headphones for Running](/best-headphones-for-running)

## FAQ

**Q: Are wireless earbuds worth it?**
A: Yes, modern wireless earbuds offer excellent sound quality.

**Q: How long do wireless earbuds last?**
A: Most last 4-8 hours on a single charge.

## Final Recommendation

Our final verdict: Sony WF-1000XM5 is the best overall.
"""


# ---------------------------------------------------------------------------
# Tests — validate_seo
# ---------------------------------------------------------------------------

class TestValidateSeo(unittest.TestCase):
    """Tests for validate_seo()."""

    def test_passing_article(self):
        result = validate_seo(_build_passing_article())
        self.assertTrue(result.passed, f"Expected pass, got failures: {result.failures}")
        self.assertTrue(result.has_tldr)
        self.assertTrue(result.has_comparison_table)
        self.assertTrue(result.has_faq)
        self.assertGreaterEqual(result.internal_link_count, MIN_INTERNAL_LINKS)
        self.assertGreaterEqual(result.verdict_count, MIN_VERDICT_STATEMENTS)
        self.assertGreaterEqual(result.ai_domination_score, AI_DOMINATION_SCORE_MIN)

    def test_missing_tldr(self):
        content = _build_passing_article().replace("Quick Answer", "Introduction")
        content = content.replace("Our Top Picks", "Overview")
        result = validate_seo(content)
        self.assertFalse(result.has_tldr)
        self.assertFalse(result.passed)
        self.assertTrue(any("TLDR" in f for f in result.failures))

    def test_missing_table(self):
        lines = _build_passing_article().split("\n")
        filtered = [line for line in lines if not line.startswith("|")]
        content = "\n".join(filtered)
        result = validate_seo(content)
        self.assertFalse(result.has_comparison_table)
        self.assertFalse(result.passed)
        self.assertTrue(any("table" in f.lower() for f in result.failures))

    def test_missing_faq(self):
        content = _build_passing_article().replace("## FAQ", "## Additional Info")
        result = validate_seo(content)
        self.assertFalse(result.has_faq)
        self.assertFalse(result.passed)
        self.assertTrue(any("FAQ" in f for f in result.failures))

    def test_insufficient_internal_links(self):
        import re
        content = _build_passing_article()
        links = list(re.finditer(r"\[([^\]]+)\]\(([^)]+)\)", content))
        for link in links[2:]:
            content = content.replace(link.group(0), link.group(1))
        result = validate_seo(content)
        self.assertLess(result.internal_link_count, MIN_INTERNAL_LINKS)
        self.assertFalse(result.passed)

    def test_insufficient_verdicts(self):
        content = """## Quick Answer

Best widget for home.

| A | B |
|---|---|
| 1 | 2 |

[link1](/a) [link2](/b) [link3](/c) [link4](/d) [link5](/e)

## FAQ

**Q: Is it good?**
A: Yes.
"""
        result = validate_seo(content)
        self.assertLess(result.verdict_count, MIN_VERDICT_STATEMENTS)
        self.assertFalse(result.passed)

    def test_empty_content(self):
        result = validate_seo("")
        self.assertFalse(result.passed)
        # 5 structural failures + 1 AI Domination Score failure
        self.assertEqual(len(result.failures), 6)

    def test_stale_content_lowers_score(self):
        result_fresh = validate_seo(_build_passing_article(), is_fresh=True)
        result_stale = validate_seo(_build_passing_article(), is_fresh=False)
        self.assertGreater(result_fresh.ai_domination_score, result_stale.ai_domination_score)


# ---------------------------------------------------------------------------
# Tests — AI Domination Score
# ---------------------------------------------------------------------------

class TestAIDominationScore(unittest.TestCase):
    """Tests for compute_ai_domination_score()."""

    def test_perfect_score(self):
        score = compute_ai_domination_score(
            has_tldr=True,
            has_comparison_table=True,
            has_faq=True,
            has_verdicts=True,
            has_internal_links=True,
            is_fresh=True,
        )
        self.assertEqual(score, 10)

    def test_zero_score(self):
        score = compute_ai_domination_score(
            has_tldr=False,
            has_comparison_table=False,
            has_faq=False,
            has_verdicts=False,
            has_internal_links=False,
            is_fresh=False,
        )
        self.assertEqual(score, 0)

    def test_missing_freshness_only(self):
        score = compute_ai_domination_score(
            has_tldr=True,
            has_comparison_table=True,
            has_faq=True,
            has_verdicts=True,
            has_internal_links=True,
            is_fresh=False,
        )
        self.assertEqual(score, 9)

    def test_minimum_passing_score(self):
        # All structural blocks present + fresh = 10 (passes)
        # Missing one +2 block drops to 8 only if links+fresh compensate
        score = compute_ai_domination_score(
            has_tldr=True,
            has_comparison_table=True,
            has_faq=True,
            has_verdicts=True,
            has_internal_links=False,
            is_fresh=True,
        )
        self.assertEqual(score, 9)
        self.assertGreaterEqual(score, AI_DOMINATION_SCORE_MIN)


# ---------------------------------------------------------------------------
# Tests — enforce_seo
# ---------------------------------------------------------------------------

class TestEnforceSeo(unittest.TestCase):
    """Tests for enforce_seo() which raises on failure."""

    def test_passing_does_not_raise(self):
        result = enforce_seo(_build_passing_article())
        self.assertTrue(result.passed)
        self.assertGreaterEqual(result.ai_domination_score, AI_DOMINATION_SCORE_MIN)

    def test_failing_raises_content_validation_error(self):
        with self.assertRaises(ContentValidationError) as ctx:
            enforce_seo("This is a bare article with no SEO blocks.")

        self.assertIn("ARTICLE FAILED OPENCLAW SEO VALIDATION", str(ctx.exception))

    def test_error_contains_details_with_score(self):
        with self.assertRaises(ContentValidationError) as ctx:
            enforce_seo("No SEO here.")

        error = ctx.exception
        self.assertIn("failures", error.details)
        self.assertIn("ai_domination_score", error.details)
        self.assertIsInstance(error.details["failures"], list)
        self.assertGreater(len(error.details["failures"]), 0)
        self.assertLess(error.details["ai_domination_score"], AI_DOMINATION_SCORE_MIN)


if __name__ == "__main__":
    unittest.main()
