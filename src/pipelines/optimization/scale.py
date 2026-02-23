"""
pipelines.optimization.scale
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Scale winning affiliate content by identifying top performers, planning
expansion strategies, creating related content, and increasing publishing
cadence in high-ROI niches.

Scaling multipliers are configured via ``config/pipelines.yaml`` under
``optimization.steps[2]`` (top_performers_multiply).

Design references:
    - config/pipelines.yaml  ``optimization.steps[2]``
    - ARCHITECTURE.md  Section 3 (Optimization Pipeline)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.core.constants import (
    DEFAULT_MAX_POSTS_PER_DAY,
    DEFAULT_POSTING_CADENCE_PER_DAY,
    DEFAULT_TARGET_WORD_COUNT,
)
from src.core.errors import PipelineStepError
from src.core.logger import get_logger, log_event
from src.pipelines.optimization.measure import ContentMetrics

logger = get_logger("pipelines.optimization.scale")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class Winner:
    """A high-performing content piece identified for scaling.

    Attributes
    ----------
    post_id:
        Internal identifier.
    title:
        Article title.
    url:
        Live URL.
    roi:
        Return on investment.
    revenue:
        Revenue in the measurement period.
    pageviews:
        Pageviews in the measurement period.
    clicks:
        Affiliate clicks.
    top_keywords:
        Organic keywords driving traffic.
    category:
        Content category / niche.
    expansion_potential:
        Qualitative assessment: ``"high"``, ``"medium"``, ``"low"``.
    """

    post_id: str
    title: str = ""
    url: str = ""
    roi: float = 0.0
    revenue: float = 0.0
    pageviews: int = 0
    clicks: int = 0
    top_keywords: List[str] = field(default_factory=list)
    category: str = ""
    expansion_potential: str = "medium"


@dataclass
class ExpansionPlan:
    """Strategic plan for expanding around a winning piece of content.

    Attributes
    ----------
    post_id:
        The winner this plan is based on.
    title:
        Title of the winning post.
    related_topics:
        Topics for new supporting content.
    keyword_gaps:
        Related keywords the winner does not yet rank for.
    content_briefs:
        Structured briefs for new articles to create.
    internal_link_targets:
        Existing posts that should link to/from the winner.
    refresh_actions:
        Recommended updates to the original post.
    estimated_additional_traffic:
        Projected monthly traffic increase.
    priority:
        Execution priority: ``"high"``, ``"medium"``, ``"low"``.
    """

    post_id: str
    title: str = ""
    related_topics: List[str] = field(default_factory=list)
    keyword_gaps: List[str] = field(default_factory=list)
    content_briefs: List[Dict[str, Any]] = field(default_factory=list)
    internal_link_targets: List[str] = field(default_factory=list)
    refresh_actions: List[str] = field(default_factory=list)
    estimated_additional_traffic: int = 0
    priority: str = "medium"


@dataclass
class CadenceUpdate:
    """Result of a publishing cadence adjustment.

    Attributes
    ----------
    site_id:
        The site whose cadence was updated.
    previous_cadence:
        Previous posts per day.
    new_cadence:
        Updated posts per day.
    factor:
        Multiplication factor applied.
    capped:
        Whether the new cadence was capped at the maximum.
    effective_at:
        When the new cadence takes effect.
    """

    site_id: str
    previous_cadence: int = DEFAULT_POSTING_CADENCE_PER_DAY
    new_cadence: int = DEFAULT_POSTING_CADENCE_PER_DAY
    factor: float = 1.0
    capped: bool = False
    effective_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Winner identification
# ---------------------------------------------------------------------------


def identify_winners(
    content_metrics: List[ContentMetrics],
    *,
    min_roi: float = 1.0,
    min_revenue: float = 10.0,
    min_pageviews: int = 50,
    top_n: Optional[int] = None,
) -> List[Winner]:
    """Identify high-performing content that should be scaled.

    Filters content metrics to find posts exceeding performance
    thresholds, then assesses their expansion potential based on keyword
    coverage and category competition.

    Parameters
    ----------
    content_metrics:
        List of :class:`ContentMetrics` for all published content.
    min_roi:
        Minimum ROI to qualify as a winner (1.0 = 100% return).
    min_revenue:
        Minimum revenue in USD to qualify.
    min_pageviews:
        Minimum pageviews to qualify.
    top_n:
        If set, return only the top N winners by ROI.

    Returns
    -------
    list[Winner]
        Winners sorted by ROI descending.
    """
    log_event(
        logger,
        "scale.identify_winners.start",
        total_content=len(content_metrics),
        min_roi=min_roi,
    )

    winners: List[Winner] = []

    for metrics in content_metrics:
        # Apply threshold filters
        if metrics.roi < min_roi:
            continue
        if metrics.revenue < min_revenue:
            continue
        if metrics.pageviews < min_pageviews:
            continue

        # Assess expansion potential
        expansion = _assess_expansion_potential(metrics)

        winners.append(
            Winner(
                post_id=metrics.post_id,
                title=metrics.title,
                url=metrics.url,
                roi=metrics.roi,
                revenue=metrics.revenue,
                pageviews=metrics.pageviews,
                clicks=metrics.clicks,
                top_keywords=metrics.top_keywords,
                category="",  # populated from post metadata in production
                expansion_potential=expansion,
            )
        )

    # Sort by ROI descending
    winners.sort(key=lambda w: w.roi, reverse=True)

    if top_n is not None:
        winners = winners[:top_n]

    log_event(
        logger,
        "scale.identify_winners.ok",
        winners_found=len(winners),
        top_roi=winners[0].roi if winners else 0,
    )
    return winners


def _assess_expansion_potential(metrics: ContentMetrics) -> str:
    """Assess the expansion potential of a winning content piece.

    Uses heuristics based on keyword diversity, traffic volume, and
    conversion efficiency.

    Parameters
    ----------
    metrics:
        The content's performance metrics.

    Returns
    -------
    str
        Potential rating: ``"high"``, ``"medium"``, or ``"low"``.
    """
    score = 0

    # More keywords = more expansion angles
    if len(metrics.top_keywords) >= 5:
        score += 3
    elif len(metrics.top_keywords) >= 3:
        score += 2
    elif len(metrics.top_keywords) >= 1:
        score += 1

    # High organic traffic suggests ranking potential for related content
    if metrics.organic_traffic_pct > 0.6:
        score += 2
    elif metrics.organic_traffic_pct > 0.3:
        score += 1

    # Strong conversion metrics suggest the niche converts well
    if metrics.epc > 0.50:
        score += 2
    elif metrics.epc > 0.10:
        score += 1

    # Growing content (high recent pageviews relative to age)
    if metrics.age_days > 0:
        daily_pageviews = metrics.pageviews / metrics.age_days
        if daily_pageviews > 10:
            score += 2
        elif daily_pageviews > 3:
            score += 1

    if score >= 7:
        return "high"
    elif score >= 4:
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# Expansion planning
# ---------------------------------------------------------------------------


def plan_expansion(
    winners: List[Winner],
    *,
    multiply_factor: int = 2,
) -> List[ExpansionPlan]:
    """Create strategic expansion plans for winning content.

    For each winner, generates related topic ideas, identifies keyword
    gaps, creates content briefs for supporting articles, and recommends
    updates to the original post.

    Parameters
    ----------
    winners:
        List of :class:`Winner` objects to expand.
    multiply_factor:
        How many related articles to create per winner
        (from ``top_performers_multiply`` in config).

    Returns
    -------
    list[ExpansionPlan]
        Expansion plans sorted by priority.
    """
    log_event(
        logger,
        "scale.plan_expansion.start",
        winners=len(winners),
        multiply=multiply_factor,
    )

    plans: List[ExpansionPlan] = []

    for winner in winners:
        # Generate related topics from top keywords
        related_topics = _generate_related_topics(
            winner.top_keywords, count=multiply_factor
        )

        # Identify keyword gaps
        keyword_gaps = _identify_keyword_gaps(winner.top_keywords)

        # Create content briefs
        briefs = create_related_content(
            winner.title,
            winner.top_keywords,
            count=multiply_factor,
        )

        # Determine refresh actions for the original post
        refresh_actions = _suggest_refresh_actions(winner)

        # Estimate traffic from expansion
        estimated_traffic = _estimate_expansion_traffic(winner, multiply_factor)

        # Set priority based on expansion potential
        priority_map = {"high": "high", "medium": "medium", "low": "low"}
        priority = priority_map.get(winner.expansion_potential, "medium")

        plans.append(
            ExpansionPlan(
                post_id=winner.post_id,
                title=winner.title,
                related_topics=related_topics,
                keyword_gaps=keyword_gaps,
                content_briefs=briefs,
                internal_link_targets=[winner.url] if winner.url else [],
                refresh_actions=refresh_actions,
                estimated_additional_traffic=estimated_traffic,
                priority=priority,
            )
        )

    # Sort by priority
    priority_order = {"high": 0, "medium": 1, "low": 2}
    plans.sort(key=lambda p: priority_order.get(p.priority, 3))

    log_event(
        logger,
        "scale.plan_expansion.ok",
        plans_created=len(plans),
        total_briefs=sum(len(p.content_briefs) for p in plans),
    )
    return plans


def _generate_related_topics(
    keywords: List[str],
    count: int = 2,
) -> List[str]:
    """Generate related topic ideas from a set of keywords.

    Uses keyword modification patterns to suggest content angles that
    complement the original winning post.

    Parameters
    ----------
    keywords:
        Source keywords from the winning content.
    count:
        Number of topics to generate.

    Returns
    -------
    list[str]
        Related topic strings.
    """
    if not keywords:
        return []

    patterns = [
        "best {kw} for beginners",
        "{kw} vs alternatives",
        "{kw} buying guide",
        "how to choose {kw}",
        "{kw} comparison",
        "affordable {kw} options",
        "{kw} tips and tricks",
        "is {kw} worth it",
    ]

    topics: List[str] = []
    for i, kw in enumerate(keywords):
        if len(topics) >= count:
            break
        pattern = patterns[i % len(patterns)]
        topics.append(pattern.format(kw=kw))

    return topics[:count]


def _identify_keyword_gaps(keywords: List[str]) -> List[str]:
    """Identify keyword variations not yet covered.

    In production, this would query a keyword research API.  The stub
    generates common modifier patterns.

    Parameters
    ----------
    keywords:
        Current keywords the content ranks for.

    Returns
    -------
    list[str]
        Potential keyword gaps.
    """
    modifiers = ["best", "top", "review", "cheap", "premium", "comparison"]
    gaps: List[str] = []

    for kw in keywords[:3]:
        for mod in modifiers:
            candidate = f"{mod} {kw}"
            if candidate not in keywords:
                gaps.append(candidate)

    return gaps[:10]


def _suggest_refresh_actions(winner: Winner) -> List[str]:
    """Suggest updates to refresh the winning content.

    Parameters
    ----------
    winner:
        The winning content piece.

    Returns
    -------
    list[str]
        Recommended refresh actions.
    """
    actions: List[str] = []

    actions.append("Update pricing and availability information")
    actions.append("Add or refresh comparison tables")

    if winner.clicks > 0 and winner.revenue / winner.clicks < 0.20:
        actions.append("Optimize CTA placement to improve earnings per click")

    if len(winner.top_keywords) < 3:
        actions.append("Expand content to target additional long-tail keywords")

    actions.append("Update publication date and add 'last reviewed' timestamp")

    return actions


def _estimate_expansion_traffic(
    winner: Winner,
    multiply_factor: int,
) -> int:
    """Estimate additional monthly traffic from the expansion plan.

    Uses a conservative heuristic: each new related article is expected
    to capture 30-50% of the original's traffic.

    Parameters
    ----------
    winner:
        The winning content piece.
    multiply_factor:
        Number of related articles planned.

    Returns
    -------
    int
        Estimated additional monthly pageviews.
    """
    # Conservative: each new article gets ~35% of the winner's traffic
    per_article_estimate = int(winner.pageviews * 0.35)
    return per_article_estimate * multiply_factor


# ---------------------------------------------------------------------------
# Related content creation
# ---------------------------------------------------------------------------


def create_related_content(
    parent_title: str,
    keywords: List[str],
    *,
    count: int = 2,
) -> List[Dict[str, Any]]:
    """Generate content briefs for related supporting articles.

    Creates structured briefs that can be fed into the content pipeline
    (outline -> draft -> optimize -> publish) to build out a topic
    cluster around the winning content.

    Parameters
    ----------
    parent_title:
        Title of the parent winning post.
    keywords:
        Keywords from the winning content to expand on.
    count:
        Number of briefs to generate.

    Returns
    -------
    list[dict[str, Any]]
        Content brief dicts ready for the content pipeline.
    """
    log_event(
        logger,
        "scale.create_briefs.start",
        parent=parent_title,
        count=count,
    )

    content_types = ["comparison", "buying_guide", "how_to", "review", "roundup"]
    briefs: List[Dict[str, Any]] = []

    for i in range(count):
        kw = keywords[i % len(keywords)] if keywords else parent_title
        content_type = content_types[i % len(content_types)]

        title_templates = {
            "comparison": f"{kw} vs Top Alternatives: Which Is Best?",
            "buying_guide": f"Complete {kw} Buying Guide for Beginners",
            "how_to": f"How to Get the Best Results with {kw}",
            "review": f"In-Depth {kw} Review: Pros, Cons, and Verdict",
            "roundup": f"Top 5 {kw} Options Reviewed and Compared",
        }

        brief: Dict[str, Any] = {
            "title": title_templates.get(content_type, f"{kw} - Complete Guide"),
            "target_keyword": kw,
            "secondary_keywords": [k for k in keywords if k != kw][:3],
            "content_type": content_type,
            "estimated_word_count": DEFAULT_TARGET_WORD_COUNT,
            "parent_post": parent_title,
            "internal_link_to": parent_title,
            "priority": "high" if i < count // 2 else "medium",
        }
        briefs.append(brief)

    log_event(
        logger,
        "scale.create_briefs.ok",
        briefs_created=len(briefs),
    )
    return briefs


# ---------------------------------------------------------------------------
# Cadence management
# ---------------------------------------------------------------------------


def increase_posting_cadence(
    site_id: str,
    factor: float,
    *,
    current_cadence: int = DEFAULT_POSTING_CADENCE_PER_DAY,
    max_cadence: int = DEFAULT_MAX_POSTS_PER_DAY,
) -> CadenceUpdate:
    """Increase the content publishing frequency for a site.

    Multiplies the current posting cadence by the given factor, capped
    at the maximum allowed cadence.

    Parameters
    ----------
    site_id:
        Internal site identifier.
    factor:
        Multiplier for the current cadence (e.g. 2.0 doubles output).
        Must be positive.
    current_cadence:
        Current posts per day.
    max_cadence:
        Maximum allowed posts per day (safety cap).

    Returns
    -------
    CadenceUpdate
        Details of the cadence adjustment.

    Raises
    ------
    PipelineStepError
        If *factor* is not positive or *site_id* is empty.
    """
    if not site_id:
        raise PipelineStepError(
            "site_id is required for cadence update",
            step_name="scale",
        )
    if factor <= 0:
        raise PipelineStepError(
            f"factor must be positive, got {factor}",
            step_name="scale",
        )

    new_cadence = int(current_cadence * factor)
    capped = new_cadence > max_cadence
    if capped:
        new_cadence = max_cadence

    log_event(
        logger,
        "scale.cadence.update",
        site_id=site_id,
        previous=current_cadence,
        new=new_cadence,
        factor=factor,
        capped=capped,
    )

    update = CadenceUpdate(
        site_id=site_id,
        previous_cadence=current_cadence,
        new_cadence=new_cadence,
        factor=factor,
        capped=capped,
    )

    # Stub: in production, this persists the schedule change to the database
    logger.info(
        "Publishing cadence for site %s updated: %d -> %d posts/day (factor: %.1f%s)",
        site_id,
        current_cadence,
        new_cadence,
        factor,
        ", capped" if capped else "",
    )

    return update
