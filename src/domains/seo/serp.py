"""
domains.seo.serp
~~~~~~~~~~~~~~~~~

SERP (Search Engine Results Page) analysis utilities for the OpenClaw SEO
domain.

Provides data models and functions for analysing search results, assessing
competition, and identifying content gaps that represent opportunities for
new affiliate content.

Design references:
    - ARCHITECTURE.md  Section 3 (Content Pipeline -- SERP Analysis)
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from enum import Enum, unique
from typing import Any, Dict, List, Optional, Sequence

from src.core.logger import get_logger

logger = get_logger("seo.serp")


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

@unique
class SERPFeature(str, Enum):
    """SERP feature types that may appear alongside organic results."""

    FEATURED_SNIPPET = "featured_snippet"
    PEOPLE_ALSO_ASK = "people_also_ask"
    KNOWLEDGE_PANEL = "knowledge_panel"
    LOCAL_PACK = "local_pack"
    IMAGE_PACK = "image_pack"
    VIDEO_CAROUSEL = "video_carousel"
    SHOPPING = "shopping"
    TOP_STORIES = "top_stories"
    REVIEWS = "reviews"
    SITELINKS = "sitelinks"
    ADS = "ads"


@unique
class CompetitionLevel(str, Enum):
    """Overall competition assessment for a SERP."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    VERY_HIGH = "very_high"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class SERPResult:
    """A single organic result from a SERP analysis.

    Attributes
    ----------
    position:
        Ranking position (1 = top result).
    url:
        URL of the ranking page.
    title:
        Title tag of the ranking page.
    description:
        Meta description or snippet text.
    domain:
        Root domain of the result (e.g. ``"example.com"``).
    domain_authority:
        Estimated domain authority score (0--100).
    page_authority:
        Estimated page authority score (0--100).
    word_count:
        Estimated word count of the ranking page content.
    content_type:
        Detected content type (e.g. ``"listicle"``, ``"review"``,
        ``"guide"``).
    has_affiliate_links:
        Whether affiliate links were detected on the page.
    last_updated:
        Estimated date the content was last updated, if detectable.
    metadata:
        Additional fields from the SERP data source.
    """

    position: int
    url: str
    title: str = ""
    description: str = ""
    domain: str = ""
    domain_authority: int = 0
    page_authority: int = 0
    word_count: int = 0
    content_type: str = ""
    has_affiliate_links: bool = False
    last_updated: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SERPAnalysis:
    """Aggregated analysis of a full SERP for a target keyword.

    Attributes
    ----------
    keyword:
        The keyword that was searched.
    results:
        Ordered list of organic results.
    features:
        SERP features detected on the page.
    total_results:
        Estimated total number of search results.
    competition_level:
        Overall competition assessment.
    avg_domain_authority:
        Mean domain authority of page-one results.
    avg_word_count:
        Mean word count of page-one results.
    content_gaps:
        List of identified content gap descriptions.
    metadata:
        Additional analysis-level data.
    """

    keyword: str
    results: List[SERPResult] = field(default_factory=list)
    features: List[SERPFeature] = field(default_factory=list)
    total_results: int = 0
    competition_level: CompetitionLevel = CompetitionLevel.MEDIUM
    avg_domain_authority: float = 0.0
    avg_word_count: float = 0.0
    content_gaps: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ContentGap:
    """A content gap identified from SERP analysis.

    Attributes
    ----------
    description:
        Human-readable description of the gap.
    gap_type:
        Category of gap: ``"missing_angle"``, ``"outdated_content"``,
        ``"thin_content"``, ``"no_affiliate"``.
    opportunity_score:
        Estimated opportunity score (0--100).
    suggested_content_type:
        Recommended content type to fill this gap.
    keywords:
        Related keywords that could target this gap.
    """

    description: str
    gap_type: str = "missing_angle"
    opportunity_score: float = 0.0
    suggested_content_type: str = ""
    keywords: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Analysis functions
# ---------------------------------------------------------------------------

def analyze_serp(
    keyword: str,
    results: Sequence[SERPResult],
    *,
    features: Optional[List[SERPFeature]] = None,
    total_results: int = 0,
) -> SERPAnalysis:
    """Perform a comprehensive analysis of SERP data for a keyword.

    Computes aggregate statistics, assesses competition level, and
    identifies content gaps among the ranking pages.

    Parameters
    ----------
    keyword:
        The target keyword.
    results:
        Organic results from the SERP (position 1 through N).
    features:
        SERP features detected on the results page.
    total_results:
        Estimated total search results count.

    Returns
    -------
    SERPAnalysis
        Complete analysis including competition assessment and gaps.
    """
    analysis = SERPAnalysis(
        keyword=keyword,
        results=list(results),
        features=features or [],
        total_results=total_results,
    )

    if results:
        das = [r.domain_authority for r in results if r.domain_authority > 0]
        wcs = [r.word_count for r in results if r.word_count > 0]

        analysis.avg_domain_authority = round(statistics.mean(das), 1) if das else 0.0
        analysis.avg_word_count = round(statistics.mean(wcs), 1) if wcs else 0.0

    analysis.competition_level = assess_competition(results)
    analysis.content_gaps = [
        gap.description for gap in find_content_gaps(keyword, results)
    ]

    logger.info(
        "SERP analysis for '%s': competition=%s, avg_da=%.1f, avg_words=%.0f, gaps=%d",
        keyword,
        analysis.competition_level.value,
        analysis.avg_domain_authority,
        analysis.avg_word_count,
        len(analysis.content_gaps),
    )
    return analysis


def get_top_results(
    results: Sequence[SERPResult],
    n: int = 10,
) -> List[SERPResult]:
    """Return the top N organic results sorted by position.

    Parameters
    ----------
    results:
        Full list of SERP results.
    n:
        Number of results to return.

    Returns
    -------
    list[SERPResult]
        The top N results by position.
    """
    sorted_results = sorted(results, key=lambda r: r.position)
    return sorted_results[:n]


def assess_competition(
    results: Sequence[SERPResult],
) -> CompetitionLevel:
    """Assess the competition level of a SERP based on ranking page metrics.

    Factors considered:
    - Average domain authority of top-10 results.
    - Presence of major authority domains.
    - Average word count (higher = more investment by competitors).
    - Proportion of results with affiliate content.

    Parameters
    ----------
    results:
        Organic results from the SERP.

    Returns
    -------
    CompetitionLevel
        Overall competition assessment.
    """
    if not results:
        return CompetitionLevel.LOW

    top_10 = get_top_results(results, 10)
    das = [r.domain_authority for r in top_10 if r.domain_authority > 0]
    avg_da = statistics.mean(das) if das else 0

    # Check for major authority domains (DA > 80)
    high_da_count = sum(1 for r in top_10 if r.domain_authority > 80)

    # Check average word count
    wcs = [r.word_count for r in top_10 if r.word_count > 0]
    avg_wc = statistics.mean(wcs) if wcs else 0

    # Affiliate saturation
    affiliate_count = sum(1 for r in top_10 if r.has_affiliate_links)

    # Scoring heuristic
    score = 0.0
    score += min(avg_da, 100) * 0.4            # DA contributes 40%
    score += high_da_count * 5                   # Major sites penalty
    score += min(avg_wc / 50, 20)               # Content depth (max 20 points)
    score += affiliate_count * 3                 # Affiliate saturation

    if score >= 70:
        return CompetitionLevel.VERY_HIGH
    if score >= 50:
        return CompetitionLevel.HIGH
    if score >= 30:
        return CompetitionLevel.MEDIUM
    return CompetitionLevel.LOW


def find_content_gaps(
    keyword: str,
    results: Sequence[SERPResult],
) -> List[ContentGap]:
    """Identify content gaps in the current SERP that represent opportunities.

    Analyses the ranking pages for weaknesses that a new piece of content
    could exploit: outdated content, thin articles, missing angles, or
    absence of affiliate-focused content.

    Parameters
    ----------
    keyword:
        The target keyword.
    results:
        Organic results from the SERP.

    Returns
    -------
    list[ContentGap]
        Identified gaps sorted by opportunity score (highest first).
    """
    gaps: List[ContentGap] = []
    top_10 = get_top_results(results, 10)

    if not top_10:
        gaps.append(ContentGap(
            description=f"No organic results found for '{keyword}' -- untapped opportunity",
            gap_type="missing_angle",
            opportunity_score=95.0,
            suggested_content_type="blog_post",
            keywords=[keyword],
        ))
        return gaps

    # Gap: outdated content
    year_pattern = re.compile(r"20[12]\d")
    outdated_count = 0
    for r in top_10:
        title_text = f"{r.title} {r.last_updated or ''}"
        years = year_pattern.findall(title_text)
        if years:
            latest_year = max(int(y) for y in years)
            if latest_year < 2025:
                outdated_count += 1

    if outdated_count >= 3:
        gaps.append(ContentGap(
            description=(
                f"{outdated_count} of top 10 results for '{keyword}' appear outdated. "
                "Fresh, updated content could rank quickly."
            ),
            gap_type="outdated_content",
            opportunity_score=80.0,
            suggested_content_type="blog_post",
            keywords=[keyword],
        ))

    # Gap: thin content
    wcs = [r.word_count for r in top_10 if r.word_count > 0]
    if wcs and statistics.mean(wcs) < 1000:
        gaps.append(ContentGap(
            description=(
                f"Average word count for '{keyword}' is only {statistics.mean(wcs):.0f}. "
                "A comprehensive long-form article could outrank existing thin content."
            ),
            gap_type="thin_content",
            opportunity_score=70.0,
            suggested_content_type="blog_post",
            keywords=[keyword],
        ))

    # Gap: no affiliate angle
    affiliate_count = sum(1 for r in top_10 if r.has_affiliate_links)
    if affiliate_count == 0:
        gaps.append(ContentGap(
            description=(
                f"No affiliate content in top 10 for '{keyword}'. "
                "Opportunity to be the first affiliate-focused result."
            ),
            gap_type="no_affiliate",
            opportunity_score=75.0,
            suggested_content_type="product_review",
            keywords=[keyword],
        ))

    # Gap: missing comparison content
    has_comparison = any(
        "vs" in r.title.lower() or "comparison" in r.title.lower()
        for r in top_10
    )
    if not has_comparison and len(keyword.split()) >= 2:
        gaps.append(ContentGap(
            description=(
                f"No comparison content in top 10 for '{keyword}'. "
                "A comparison article could capture commercial intent traffic."
            ),
            gap_type="missing_angle",
            opportunity_score=65.0,
            suggested_content_type="comparison",
            keywords=[keyword],
        ))

    # Gap: weak domain authority
    das = [r.domain_authority for r in top_10 if r.domain_authority > 0]
    if das:
        low_da_count = sum(1 for da in das if da < 30)
        if low_da_count >= 4:
            gaps.append(ContentGap(
                description=(
                    f"{low_da_count} of top 10 results for '{keyword}' have low domain "
                    "authority (<30). Even a newer site can compete here."
                ),
                gap_type="missing_angle",
                opportunity_score=60.0,
                suggested_content_type="roundup",
                keywords=[keyword],
            ))

    gaps.sort(key=lambda g: g.opportunity_score, reverse=True)
    logger.debug("Found %d content gaps for '%s'", len(gaps), keyword)
    return gaps
