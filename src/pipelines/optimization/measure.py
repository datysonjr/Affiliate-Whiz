"""
pipelines.optimization.measure
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Measure the performance of published affiliate content to drive
data-driven optimization decisions.  Collects traffic metrics, revenue
data, click-through rates, and computes ROI for each content piece.

The measurement stage feeds both the ``prune`` stage (underperformers)
and the ``scale`` stage (winners).

Design references:
    - config/pipelines.yaml  ``optimization.steps[0]``  (metrics, lookback_days)
    - ARCHITECTURE.md  Section 3 (Optimization Pipeline)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from src.core.errors import PipelineStepError
from src.core.logger import get_logger, log_event

logger = get_logger("pipelines.optimization.measure")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ContentMetrics:
    """Performance metrics for a single piece of content.

    Attributes
    ----------
    post_id:
        Identifier of the measured post.
    title:
        Post title.
    url:
        Post URL.
    pageviews:
        Total pageviews in the measurement period.
    unique_visitors:
        Unique visitors in the period.
    avg_time_on_page_s:
        Average time on page in seconds.
    bounce_rate:
        Bounce rate as a decimal (0.0-1.0).
    clicks:
        Total affiliate link clicks.
    ctr:
        Click-through rate (clicks / pageviews).
    conversions:
        Number of affiliate conversions.
    revenue:
        Total affiliate revenue in USD.
    epc:
        Earnings per click (revenue / clicks).
    organic_traffic_pct:
        Fraction of traffic from organic search.
    top_keywords:
        Top organic keywords driving traffic.
    measured_at:
        UTC timestamp of measurement.
    period_days:
        Number of days in the measurement window.
    """

    post_id: str
    title: str = ""
    url: str = ""
    pageviews: int = 0
    unique_visitors: int = 0
    avg_time_on_page_s: float = 0.0
    bounce_rate: float = 0.0
    clicks: int = 0
    ctr: float = 0.0
    conversions: int = 0
    revenue: float = 0.0
    epc: float = 0.0
    organic_traffic_pct: float = 0.0
    top_keywords: List[str] = field(default_factory=list)
    measured_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    period_days: int = 30


@dataclass
class SiteMetrics:
    """Aggregate metrics for an entire site.

    Attributes
    ----------
    site_id:
        Identifier of the measured site.
    total_pageviews:
        Aggregate pageviews across all content.
    total_revenue:
        Aggregate affiliate revenue.
    total_clicks:
        Aggregate affiliate link clicks.
    avg_epc:
        Site-wide average earnings per click.
    avg_ctr:
        Site-wide average click-through rate.
    content_count:
        Number of published content pieces.
    top_performers:
        Post IDs of the best-performing content.
    period_days:
        Measurement window in days.
    measured_at:
        UTC timestamp.
    """

    site_id: str
    total_pageviews: int = 0
    total_revenue: float = 0.0
    total_clicks: int = 0
    avg_epc: float = 0.0
    avg_ctr: float = 0.0
    content_count: int = 0
    top_performers: List[str] = field(default_factory=list)
    period_days: int = 30
    measured_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class ROIResult:
    """Return on investment calculation for a content piece.

    Attributes
    ----------
    post_id:
        The content piece identifier.
    revenue:
        Total revenue generated.
    estimated_cost:
        Estimated production and maintenance cost.
    roi:
        Computed ROI ratio ((revenue - cost) / cost).
    profitable:
        Whether the content is profitable (ROI > 0).
    """

    post_id: str
    revenue: float = 0.0
    estimated_cost: float = 0.0
    roi: float = 0.0
    profitable: bool = False


# ---------------------------------------------------------------------------
# Cost estimation
# ---------------------------------------------------------------------------

# Default cost assumptions per content piece (in USD)
_DEFAULT_CONTENT_COSTS = {
    "creation": 25.0,       # LLM API costs for generation
    "seo_optimization": 5.0,  # SEO tools API costs
    "hosting_share": 2.0,   # Monthly hosting cost share per page
    "maintenance": 3.0,     # Monthly refresh/monitoring cost
}


def _estimate_content_cost(
    age_days: int,
    *,
    cost_overrides: Optional[Dict[str, float]] = None,
) -> float:
    """Estimate the total cost of a content piece including ongoing costs.

    Parameters
    ----------
    age_days:
        Number of days since the content was published.
    cost_overrides:
        Optional custom cost assumptions.

    Returns
    -------
    float
        Total estimated cost in USD.
    """
    costs = {**_DEFAULT_CONTENT_COSTS, **(cost_overrides or {})}

    # One-time costs
    upfront = costs.get("creation", 25.0) + costs.get("seo_optimization", 5.0)

    # Recurring monthly costs
    months = max(age_days / 30.0, 1.0)
    recurring = months * (costs.get("hosting_share", 2.0) + costs.get("maintenance", 3.0))

    return round(upfront + recurring, 2)


# ---------------------------------------------------------------------------
# Core measurement functions
# ---------------------------------------------------------------------------

def measure_content_performance(
    post_id: str,
    *,
    title: str = "",
    url: str = "",
    analytics_data: Optional[Dict[str, Any]] = None,
    affiliate_data: Optional[Dict[str, Any]] = None,
    period_days: int = 30,
) -> ContentMetrics:
    """Measure the overall performance of a single content piece.

    Aggregates traffic data from analytics and revenue data from
    affiliate networks into a unified :class:`ContentMetrics` record.

    Parameters
    ----------
    post_id:
        Identifier of the post to measure.
    title:
        Post title (for reporting).
    url:
        Post URL (for reporting).
    analytics_data:
        Pre-fetched analytics dict with keys: ``pageviews``,
        ``unique_visitors``, ``avg_time_on_page``, ``bounce_rate``,
        ``organic_traffic_pct``, ``top_keywords``.  If ``None``, zeros
        are used (analytics integration not yet connected).
    affiliate_data:
        Pre-fetched affiliate dict with keys: ``clicks``,
        ``conversions``, ``revenue``.  If ``None``, zeros are used.
    period_days:
        Number of days in the measurement lookback window.

    Returns
    -------
    ContentMetrics
        Comprehensive performance snapshot.
    """
    log_event(
        logger,
        "measure.content.start",
        post_id=post_id,
        period_days=period_days,
    )

    analytics = analytics_data or {}
    affiliate = affiliate_data or {}

    pageviews = analytics.get("pageviews", 0)
    clicks = affiliate.get("clicks", 0)
    revenue = affiliate.get("revenue", 0.0)

    # Compute derived metrics
    ctr = clicks / pageviews if pageviews > 0 else 0.0
    epc = revenue / clicks if clicks > 0 else 0.0

    metrics = ContentMetrics(
        post_id=post_id,
        title=title,
        url=url,
        pageviews=pageviews,
        unique_visitors=analytics.get("unique_visitors", 0),
        avg_time_on_page_s=analytics.get("avg_time_on_page", 0.0),
        bounce_rate=analytics.get("bounce_rate", 0.0),
        clicks=clicks,
        ctr=round(ctr, 4),
        conversions=affiliate.get("conversions", 0),
        revenue=round(revenue, 2),
        epc=round(epc, 4),
        organic_traffic_pct=analytics.get("organic_traffic_pct", 0.0),
        top_keywords=analytics.get("top_keywords", []),
        period_days=period_days,
    )

    log_event(
        logger,
        "measure.content.ok",
        post_id=post_id,
        pageviews=pageviews,
        clicks=clicks,
        revenue=revenue,
        ctr=round(ctr, 4),
        epc=round(epc, 4),
    )
    return metrics


def calculate_roi(
    post_id: str,
    revenue: float,
    *,
    age_days: int = 30,
    cost_overrides: Optional[Dict[str, float]] = None,
) -> ROIResult:
    """Calculate return on investment for a content piece.

    ROI = (revenue - estimated_cost) / estimated_cost.
    A value of 1.0 means the content doubled its investment; 0.0 means
    break-even; negative values mean a net loss.

    Parameters
    ----------
    post_id:
        Content piece identifier.
    revenue:
        Total revenue generated in USD.
    age_days:
        Number of days since publication (for cost estimation).
    cost_overrides:
        Optional custom cost assumptions.

    Returns
    -------
    ROIResult
        ROI calculation result.
    """
    cost = _estimate_content_cost(age_days, cost_overrides=cost_overrides)

    if cost <= 0:
        roi = 0.0 if revenue == 0 else float("inf")
    else:
        roi = round((revenue - cost) / cost, 4)

    result = ROIResult(
        post_id=post_id,
        revenue=revenue,
        estimated_cost=cost,
        roi=roi,
        profitable=roi > 0,
    )

    log_event(
        logger,
        "measure.roi.ok",
        post_id=post_id,
        revenue=revenue,
        cost=cost,
        roi=roi,
        profitable=result.profitable,
    )
    return result


def get_traffic_metrics(
    site_id: str,
    *,
    period_days: int = 30,
    analytics_data: Optional[Dict[str, Any]] = None,
) -> SiteMetrics:
    """Retrieve aggregate traffic metrics for an entire site.

    Provides a site-wide view of performance to contextualize individual
    content metrics.

    Parameters
    ----------
    site_id:
        Internal identifier of the site.
    period_days:
        Number of days in the lookback window.
    analytics_data:
        Pre-fetched site-level analytics dict.  If ``None``, a stub
        response is returned (analytics integration not yet connected).

    Returns
    -------
    SiteMetrics
        Aggregate site-level metrics.
    """
    log_event(
        logger,
        "measure.traffic.start",
        site_id=site_id,
        period_days=period_days,
    )

    data = analytics_data or {}

    metrics = SiteMetrics(
        site_id=site_id,
        total_pageviews=data.get("total_pageviews", 0),
        total_revenue=data.get("total_revenue", 0.0),
        total_clicks=data.get("total_clicks", 0),
        content_count=data.get("content_count", 0),
        period_days=period_days,
    )

    # Compute averages
    if metrics.total_clicks > 0:
        metrics.avg_epc = round(metrics.total_revenue / metrics.total_clicks, 4)
    if metrics.total_pageviews > 0:
        metrics.avg_ctr = round(metrics.total_clicks / metrics.total_pageviews, 4)

    metrics.top_performers = data.get("top_performers", [])

    log_event(
        logger,
        "measure.traffic.ok",
        site_id=site_id,
        total_pageviews=metrics.total_pageviews,
        total_revenue=metrics.total_revenue,
        content_count=metrics.content_count,
    )
    return metrics


def get_revenue_metrics(
    site_id: str,
    *,
    period_days: int = 30,
    affiliate_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Retrieve revenue metrics for a site across all affiliate networks.

    Breaks down earnings by network, identifies top-performing products,
    and computes trend data.

    Parameters
    ----------
    site_id:
        Internal identifier of the site.
    period_days:
        Number of days in the lookback window.
    affiliate_data:
        Pre-fetched revenue data dict.  If ``None``, a stub response is
        returned.

    Returns
    -------
    dict[str, Any]
        Revenue metrics dict with keys: ``site_id``, ``period_days``,
        ``total_revenue``, ``total_clicks``, ``total_conversions``,
        ``epc``, ``conversion_rate``, ``revenue_by_network``,
        ``top_products``, ``revenue_trend``.
    """
    log_event(
        logger,
        "measure.revenue.start",
        site_id=site_id,
        period_days=period_days,
    )

    data = affiliate_data or {}

    total_revenue = data.get("total_revenue", 0.0)
    total_clicks = data.get("total_clicks", 0)
    total_conversions = data.get("total_conversions", 0)

    epc = total_revenue / total_clicks if total_clicks > 0 else 0.0
    conversion_rate = total_conversions / total_clicks if total_clicks > 0 else 0.0

    result: Dict[str, Any] = {
        "site_id": site_id,
        "period_days": period_days,
        "total_revenue": round(total_revenue, 2),
        "total_clicks": total_clicks,
        "total_conversions": total_conversions,
        "epc": round(epc, 4),
        "conversion_rate": round(conversion_rate, 4),
        "revenue_by_network": data.get("revenue_by_network", {}),
        "top_products": data.get("top_products", []),
        "revenue_trend": data.get("revenue_trend", []),
    }

    log_event(
        logger,
        "measure.revenue.ok",
        site_id=site_id,
        total_revenue=round(total_revenue, 2),
        total_clicks=total_clicks,
        epc=round(epc, 4),
    )
    return result
