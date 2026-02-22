"""
domains.seo.validator
~~~~~~~~~~~~~~~~~~~~~

OpenClaw SEO publishing validator.  Blocks article publishing unless all
mandatory SEO structural blocks are present.

Required blocks (from docs/seo/README_SEO_SYSTEM.md):
    1. TLDR block at top of article
    2. Comparison table
    3. FAQ section
    4. At least 5 internal links
    5. At least 3 product verdict statements

Also computes the **AI Domination Score** (0-10) from
``docs/seo/OPENCLAW_AI_DOMINATION_PROTOCOL.md``.  Articles scoring
below 8 are rejected or flagged for refresh.

If any required block is missing the validator returns a structured failure
report and raises ``ContentValidationError``.

Design references:
    - docs/seo/README_SEO_SYSTEM.md
    - docs/seo/TLDR_BLOCK_STANDARD.md
    - docs/seo/SEO_AGENT_KNOWLEDGE_BASE.md
    - docs/seo/OPENCLAW_AI_DOMINATION_PROTOCOL.md
    - docs/seo/PROMPTS_CLAUDE_CODE_SEO.md
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List

from src.core.errors import ContentValidationError
from src.core.logger import get_logger, log_event

logger = get_logger("domains.seo.validator")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MIN_INTERNAL_LINKS: int = 5
MIN_VERDICT_STATEMENTS: int = 3
TLDR_MUST_APPEAR_WITHIN_WORDS: int = 200

# AI Domination Score thresholds (from OPENCLAW_AI_DOMINATION_PROTOCOL.md)
# +2 TLDR present, +2 comparison table, +2 FAQ structured,
# +2 verdict sentences, +1 internal linking cluster, +1 updated within 60d
AI_DOMINATION_SCORE_MIN: int = 8
AI_DOMINATION_SCORE_MAX: int = 10


# ---------------------------------------------------------------------------
# Verdict detection patterns
# ---------------------------------------------------------------------------

_VERDICT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bbest\s+(?:overall|budget|premium|for)\b", re.IGNORECASE),
    re.compile(r"\btop\s+pick\b", re.IGNORECASE),
    re.compile(r"\bour\s+(?:top\s+)?(?:pick|choice|recommendation)\b", re.IGNORECASE),
    re.compile(r"\bwe\s+recommend\b", re.IGNORECASE),
    re.compile(r"\bhighly\s+recommend(?:ed)?\b", re.IGNORECASE),
    re.compile(r"\bwinner\b", re.IGNORECASE),
    re.compile(r"\bbest\s+[\w\s]+(?:for|in|under|over|around)\b", re.IGNORECASE),
    re.compile(r"\bverdict\s*:", re.IGNORECASE),
    re.compile(r"\bbottom\s+line\s*:", re.IGNORECASE),
    re.compile(r"\bfinal\s+(?:verdict|recommendation|pick)\b", re.IGNORECASE),
    re.compile(r"\beditor'?s?\s+choice\b", re.IGNORECASE),
]


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class SEOValidationResult:
    """Result of the OpenClaw SEO validation pass.

    Attributes
    ----------
    passed:
        ``True`` if article meets all SEO requirements.
    has_tldr:
        Whether a TLDR block was found near the top.
    has_comparison_table:
        Whether a comparison table was detected.
    has_faq:
        Whether an FAQ section was found.
    internal_link_count:
        Number of internal links detected.
    verdict_count:
        Number of product verdict statements found.
    failures:
        Human-readable list of what failed validation.
    """

    passed: bool = False
    has_tldr: bool = False
    has_comparison_table: bool = False
    has_faq: bool = False
    internal_link_count: int = 0
    verdict_count: int = 0
    ai_domination_score: int = 0
    failures: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def _check_tldr(content: str) -> bool:
    """Check that a TLDR / Quick Answer block exists near the top.

    Looks for common TLDR heading patterns within the first
    ``TLDR_MUST_APPEAR_WITHIN_WORDS`` words of the article.
    """
    # Take the first N words worth of text
    words = content.split()
    top_chunk = " ".join(words[:TLDR_MUST_APPEAR_WITHIN_WORDS]).lower()

    tldr_signals = [
        "tldr",
        "tl;dr",
        "quick answer",
        "quick summary",
        "short answer",
        "at a glance",
        "our top picks",
        "top picks",
        "quick verdict",
    ]
    return any(signal in top_chunk for signal in tldr_signals)


def _check_comparison_table(content: str) -> bool:
    """Check that a comparison / markdown table exists.

    Detects markdown pipe-tables (``| col | col |``) or HTML ``<table>``
    elements.
    """
    # Markdown table: at least two rows with pipe delimiters
    md_table = re.search(r"^\|.+\|.*\n\|[-: |]+\|", content, re.MULTILINE)
    if md_table:
        return True

    # HTML table
    if "<table" in content.lower():
        return True

    return False


def _check_faq(content: str) -> bool:
    """Check that an FAQ section exists.

    Looks for a heading containing 'FAQ' or 'Frequently Asked' followed by
    question-style content.
    """
    faq_heading = re.search(
        r"^#{1,4}\s+.*(?:FAQ|Frequently\s+Asked|Common\s+Questions)",
        content,
        re.MULTILINE | re.IGNORECASE,
    )
    return faq_heading is not None


def _count_internal_links(content: str) -> int:
    """Count internal links in the content.

    Counts both markdown links ``[text](url)`` and HTML ``<a>`` tags.
    Self-anchors (``#section``) are excluded — only path-based links count.
    """
    # Markdown links (excluding pure anchors and external http links that
    # point to domains other than the site itself — we can't know the site
    # domain here, so we count all markdown links as potential internal links
    # since external links should use full URLs while internal links use
    # relative paths or the site's own domain)
    md_links = re.findall(r"\[([^\]]+)\]\(([^)]+)\)", content)

    # HTML links
    html_links = re.findall(r'<a\s+[^>]*href="([^"]+)"', content, re.IGNORECASE)

    count = 0
    for _text, url in md_links:
        # Skip pure anchors
        if url.startswith("#"):
            continue
        count += 1

    for url in html_links:
        if url.startswith("#"):
            continue
        count += 1

    return count


def _count_verdict_statements(content: str) -> int:
    """Count product verdict / recommendation statements.

    Uses pattern matching against common verdict language used in
    affiliate content.
    """
    matches: set[int] = set()
    for pattern in _VERDICT_PATTERNS:
        for match in pattern.finditer(content):
            # Deduplicate by position (within 20 chars counts as same)
            pos = match.start()
            is_duplicate = any(abs(pos - existing) < 20 for existing in matches)
            if not is_duplicate:
                matches.add(pos)

    return len(matches)


# ---------------------------------------------------------------------------
# AI Domination Score
# ---------------------------------------------------------------------------

def compute_ai_domination_score(
    *,
    has_tldr: bool,
    has_comparison_table: bool,
    has_faq: bool,
    has_verdicts: bool,
    has_internal_links: bool,
    is_fresh: bool = True,
) -> int:
    """Compute the AI Domination Score (0-10).

    Scoring from ``docs/seo/OPENCLAW_AI_DOMINATION_PROTOCOL.md``::

        +2  TLDR present
        +2  comparison table present
        +2  FAQ structured
        +2  verdict sentences included
        +1  internal linking cluster present
        +1  updated within 60 days

    Parameters
    ----------
    has_tldr:
        TLDR block detected at top.
    has_comparison_table:
        Comparison table detected.
    has_faq:
        FAQ section detected.
    has_verdicts:
        Minimum verdict statements met.
    has_internal_links:
        Minimum internal links met.
    is_fresh:
        Whether the article was updated within the last 60 days.
        Defaults to ``True`` for new articles.

    Returns
    -------
    int
        Score between 0 and 10.
    """
    score = 0
    if has_tldr:
        score += 2
    if has_comparison_table:
        score += 2
    if has_faq:
        score += 2
    if has_verdicts:
        score += 2
    if has_internal_links:
        score += 1
    if is_fresh:
        score += 1
    return score


# ---------------------------------------------------------------------------
# Main validator
# ---------------------------------------------------------------------------

def validate_seo(content: str, *, is_fresh: bool = True) -> SEOValidationResult:
    """Run all OpenClaw SEO validation checks on article content.

    Parameters
    ----------
    content:
        The full article content (Markdown or HTML).
    is_fresh:
        Whether the article was created/updated within the last 60 days.
        Defaults to ``True`` for new content.

    Returns
    -------
    SEOValidationResult
        Structured result with pass/fail and details.
    """
    has_tldr = _check_tldr(content)
    has_table = _check_comparison_table(content)
    has_faq = _check_faq(content)
    link_count = _count_internal_links(content)
    verdict_count = _count_verdict_statements(content)

    has_enough_links = link_count >= MIN_INTERNAL_LINKS
    has_enough_verdicts = verdict_count >= MIN_VERDICT_STATEMENTS

    failures: list[str] = []

    if not has_tldr:
        failures.append(
            "TLDR block missing — must appear within first "
            f"{TLDR_MUST_APPEAR_WITHIN_WORDS} words"
        )

    if not has_table:
        failures.append("Comparison table missing — article needs a product comparison table")

    if not has_faq:
        failures.append("FAQ section missing — article needs an FAQ heading with questions")

    if not has_enough_links:
        failures.append(
            f"Internal links insufficient — found {link_count}, "
            f"minimum is {MIN_INTERNAL_LINKS}"
        )

    if not has_enough_verdicts:
        failures.append(
            f"Verdict statements insufficient — found {verdict_count}, "
            f"minimum is {MIN_VERDICT_STATEMENTS}"
        )

    # Compute AI Domination Score
    ai_score = compute_ai_domination_score(
        has_tldr=has_tldr,
        has_comparison_table=has_table,
        has_faq=has_faq,
        has_verdicts=has_enough_verdicts,
        has_internal_links=has_enough_links,
        is_fresh=is_fresh,
    )

    if ai_score < AI_DOMINATION_SCORE_MIN:
        failures.append(
            f"AI Domination Score too low — scored {ai_score}/{AI_DOMINATION_SCORE_MAX}, "
            f"minimum is {AI_DOMINATION_SCORE_MIN}"
        )

    passed = len(failures) == 0

    result = SEOValidationResult(
        passed=passed,
        has_tldr=has_tldr,
        has_comparison_table=has_table,
        has_faq=has_faq,
        internal_link_count=link_count,
        verdict_count=verdict_count,
        ai_domination_score=ai_score,
        failures=failures,
    )

    log_event(
        logger,
        "seo.validation.complete",
        passed=passed,
        ai_domination_score=ai_score,
        failures=len(failures),
        links=link_count,
        verdicts=verdict_count,
    )

    return result


def enforce_seo(content: str, *, is_fresh: bool = True) -> SEOValidationResult:
    """Validate and raise on failure.

    Convenience wrapper that calls :func:`validate_seo` and raises
    ``ContentValidationError`` if the article does not pass.

    Parameters
    ----------
    content:
        The full article content.
    is_fresh:
        Whether the article was created/updated within the last 60 days.

    Returns
    -------
    SEOValidationResult
        The passing result (only returned if validation succeeds).

    Raises
    ------
    ContentValidationError
        If any required SEO block is missing or AI Domination Score < 8.
    """
    result = validate_seo(content, is_fresh=is_fresh)

    if not result.passed:
        detail_lines = "\n".join(f"  - {f}" for f in result.failures)
        raise ContentValidationError(
            f"ARTICLE FAILED OPENCLAW SEO VALIDATION\n{detail_lines}",
            details={
                "has_tldr": result.has_tldr,
                "has_comparison_table": result.has_comparison_table,
                "has_faq": result.has_faq,
                "internal_link_count": result.internal_link_count,
                "verdict_count": result.verdict_count,
                "ai_domination_score": result.ai_domination_score,
                "failures": result.failures,
            },
        )

    return result
