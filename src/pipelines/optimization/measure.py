"""
pipelines.optimization.measure
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Measure the performance of published affiliate content.  Aggregates
traffic, engagement, conversion, and revenue data to produce actionable
performance snapshots that drive the prune and scale stages.

Metrics and lookback period are configured via ``config/pipelines.yaml``
under ``optimization.steps[0]`` (metrics list, lookback_days).

Design references:
    - config/pipelines.yaml  ``optimization.steps[0]``
    - ARCHITECTURE.md  Section 3 (Optimization Pipeline)
"""

from __future__ import annotations

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
        Internal identifier of the post.
    url:
        Live URL of the post.
    title:
        Article title.
    published_at:
        UTC datetime when the post was published.
    age_days:
        Days since publication.
    clicks:
        Total affiliate link clicks in the measurement period.
    pageviews:
        Total pageviews.
    unique_visitors:
        Unique visitor count.
    ctr:
        Click-through rate (clicks / pageviews).
    epc:
        Earnings per click (revenue / clicks).
    conversions:
        Number of affiliate conversions.
    revenue:
        Total affiliate revenue in USD.
    bounce_rate:
        Bounce rate as a decimal (0.0-1.0).
    avg_time_on_page:
        Average time on page in seconds.
    organic_traffic_pct:
        Fraction of traffic from organic search.
    top_keywords:
        Top organic keywords driving traffic.
    roi:
        Return on investment for this content.
    measured_at:
        UTC timestamp of this measurement.
    """

    post_id: str
    url: str = ""
    title: str = ""
    published_at: Optional[datetime] = None
    age_days: int = 0
    clicks: int = 0
    pageviews: int = 0
    unique_visitors: int = 0
    ctr: float = 0.0
    epc: float = 0.0
    conversions: int = 0
    revenue: float = 0.0
    bounce_rate: float = 0.0
    avg_time_on_page: float = 0.0
    organic_traffic_pct: float = 0.0
    top_keywords: List[str] = field(default_factory=list)
    roi: float = 0.0
    measured_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class SiteMetrics:
    """Aggregate metrics for an entire site.

    Attributes
    ----------
    site_id:
        Internal identifier of the site.
    period:
        Measurement period identifier (e.g. "30d").
    total_pageviews:
        Total pageviews across all content.
    total_clicks:
        Total affiliate link clicks.
    total_revenue:
        Total affiliate revenue in USD.
    total_conversions:
        Total conversions.
    avg_epc:
        Average earnings per click across the site.
    avg_ctr:
        Average click-through rate.
    top_performers:
        List of top-performing content pieces.
    underperformers:
        List of underperforming content pieces.
    measured_at:
        UTC timestamp.
    """

    site_id: str
    period: str = "30d"
    total_pageviews: int = 0
    total_clicks: int = 0
    total_revenue: float = 0.0
    total_conversions: int = 0
    avg_epc: float = 0.0
    avg_ctr: float = 0.0
    top_performers: List[ContentMetrics] = field(default_factory=list)
    underperformers: List[ContentMetrics] = field(default_factory=list)
    measured_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Period parsing
# ---------------------------------------------------------------------------

def _parse_period(period: str) -> tuple[datetime, datetime]:
    """Parse a period string into start and end datetimes.

    Supports shorthand like ``"7d"``, ``"30d"``, ``"90d"``, ``"ytd"``
    and explicit ranges like ``"2025-01-01:2025-01-31"``.

    Parameters
    ----------
    period:
        Period specification.

    Returns
    -------
    tuple[datetime, datetime]
        (start, end) datetimes in UTC.

    Raises
    ------
    PipelineStepError
        If the period format is not recognized.
    """
    now = datetime.now(timezone.utc)

    if period.endswith("d") and period[:-1].isdigit():
        days = int(period[:-1])
        return (now - timedelta(days=days), now)

    if period == "ytd":
        return (datetime(now.year, 1, 1, tzinfo=timezone.utc), now)

    if ":" in period:
        parts = period.split(":")
        if len(parts) == 2:
            try:
                start = datetime.fromisoformat(parts[0]).replace(tzinfo=timezone.utc)
                end = datetime.fromisoformat(parts[1]).replace(tzinfo=timezone.utc)
                return (start, end)
            except ValueError as exc:
                raise PipelineStepError(
                    f"Invalid date range: {period}",
                    step_name="measure",
                    cause=exc,
                ) from exc

    raise PipelineStepError(
        f"Unrecognized period format: {period!r}. "
        f"Use '7d', '30d', '90d', 'ytd', or 'YYYY-MM-DD:YYYY-MM-DD'.",
        step_name="measure",
    )


# ---------------------------------------------------------------------------
# Core measurement functions
# ---------------------------------------------------------------------------

def measure_content_performance(
    post_id: str,
    *,
    post_data: Optional[Dict[str, Any]] = None,
    analytics_data: Optional[Dict[str, Any]] = None,
    revenue_data: Optional[Dict[str, Any]] = None,
    lookback_days: int = 30,
    estimated_cost: float = 50.0,
) -> ContentMetrics:
    """Measure the overall performance of a single piece of content.

    Aggregates traffic, engagement, and revenue data to produce a
    comprehensive :class:`ContentMetrics` snapshot.  When analytics or
    revenue data providers are not available, uses the provided dicts.

    Parameters
    ----------
    post_id:
        Internal identifier of the post to measure.
    post_data:
        Optional dict with post metadata (``url``, ``title``,
        ``published_at``).
    analytics_data:
        Optional dict with traffic metrics (``pageviews``,
        ``unique_visitors``, ``bounce_rate``, ``avg_time_on_page``,
        ``organic_traffic_pct``, ``top_keywords``).
    revenue_data:
        Optional dict with revenue metrics (``clicks``, ``conversions``,
        ``revenue``).
    lookback_days:
        Number of days to look back for metrics.
    estimated_cost:
        Estimated cost of producing this content (for ROI calculation).

    Returns
    -------
    ContentMetrics
        Comprehensive performance snapshot.
    """
    log_event(logger, "measure.content.start", post_id=post_id, lookback_days=lookback_days)

    post = post_data or {}
    analytics = analytics_data or {}
    revenue = revenue_data or {}

    now = datetime.now(timezone.utc)

    # Parse publication date
    published_at = None
    age_days = 0
    pub_str = post.get("published_at")
    if pub_str:
        try:
            if isinstance(pub_str, datetime):
                published_at = pub_str
            else:
                published_at = datetime.fromisoformat(str(pub_str)).replace(tzinfo=timezone.utc)
            age_days = (now - published_at).days
        except (ValueError, TypeError):
            logger.debug("Could not parse published_at for %s: %r", post_id, pub_str)

    # Extract traffic metrics
    pageviews = int(analytics.get("pageviews", 0))
    unique_visitors = int(analytics.get("unique_visitors", 0))
    bounce_rate = float(analytics.get("bounce_rate", 0.0))
    avg_time_on_page = float(analytics.get("avg_time_on_page", 0.0))
    organic_traffic_pct = float(analytics.get("organic_traffic_pct", 0.0))
    top_keywords = list(analytics.get("top_keywords", []))

    # Extract revenue metrics
    clicks = int(revenue.get("clicks", 0))
    conversions = int(revenue.get("conversions", 0))
    total_revenue = float(revenue.get("revenue", 0.0))

    # Calculate derived metrics
    ctr = (clicks / pageviews) if pageviews > 0 else 0.0
    epc = (total_revenue / clicks) if clicks > 0 else 0.0

    # Calculate ROI
    roi = calculate_roi(total_revenue, estimated_cost)

    metrics = ContentMetrics(
        post_id=post_id,
        url=post.get("url", ""),
        title=post.get("title", ""),
        published_at=published_at,
        age_days=age_days,
        clicks=clicks,
        pageviews=pageviews,
        unique_visitors=unique_visitors,
        ctr=round(ctr, 4),
        epc=round(epc, 4),
        conversions=conversions,
        revenue=round(total_revenue, 2),
        bounce_rate=round(bounce_rate, 4),
        avg_time_on_page=round(avg_time_on_page, 1),
        organic_traffic_pct=round(organic_traffic_pct, 4),
        top_keywords=top_keywords,
        roi=round(roi, 4),
    )

    log_event(
        logger,
        "measure.content.ok",
        post_id=post_id,
        pageviews=pageviews,
        clicks=clicks,
        revenue=total_revenue,
        roi=round(roi, 4),
    )
    return metrics


def calculate_roi(
    revenue: float,
    cost: float,
) -> float:
    """Calculate return on investment for a content piece.

    Uses the formula: ``ROI = (revenue - cost) / cost``.

    A value of 1.0 means 100% return (revenue doubled the investment).
    Zero means breakeven.  Negative means net loss.

    Parameters
    ----------
    revenue:
        Total revenue generated by the content (USD).
    cost:
        Total cost of producing the content (USD).

    Returns
    -------
    float
        ROI as a decimal.  Returns ``-1.0`` if cost is zero.
    """
    if cost <= 0:
        logger.debug("Cannot calculate ROI: cost is zero or negative")
        return -1.0 if revenue <= 0 else float("inf")

    roi = (revenue - cost) / cost
    return round(roi, 4)


def get_traffic_metrics(
    site_id: str,
    period: str,
    *,
    analytics_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Retrieve aggregate traffic metrics for a site.

    Fetches or computes pageviews, sessions, users, traffic sources,
    and top pages for the specified period.

    Parameters
    ----------
    site_id:
        Internal site identifier.
    period:
        Time period (e.g. ``"7d"``, ``"30d"``, ``"90d"``).
    analytics_data:
        Optional pre-fetched analytics data dict.

    Returns
    -------
    dict[str, Any]
        Traffic metrics dict with keys: ``site_id``, ``period``,
        ``total_pageviews``, ``total_sessions``, ``total_users``,
        ``pages_per_session``, ``avg_session_duration``, ``bounce_rate``,
        ``traffic_sources``, ``top_pages``.
    """
    log_event(logger, "measure.traffic.start", site_id=site_id, period=period)

    start_dt, end_dt = _parse_period(period)
    data = analytics_data or {}

    total_pageviews = int(data.get("total_pageviews", 0))
    total_sessions = int(data.get("total_sessions", 0))
    total_users = int(data.get("total_users", 0))

    pages_per_session = (
        total_pageviews / total_sessions if total_sessions > 0 else 0.0
    )

    result: Dict[str, Any] = {
        "site_id": site_id,
        "period": period,
        "start_date": start_dt.strftime("%Y-%m-%d"),
        "end_date": end_dt.strftime("%Y-%m-%d"),
        "total_pageviews": total_pageviews,
        "total_sessions": total_sessions,
        "total_users": total_users,
        "pages_per_session": round(pages_per_session, 2),
        "avg_session_duration": float(data.get("avg_session_duration", 0.0)),
        "bounce_rate": float(data.get("bounce_rate", 0.0)),
        "traffic_sources": data.get("traffic_sources", {
            "organic": 0,
            "direct": 0,
            "referral": 0,
            "social": 0,
            "paid": 0,
        }),
        "top_pages": data.get("top_pages", []),
    }

    log_event(
        logger,
        "measure.traffic.ok",
        site_id=site_id,
        period=period,
        pageviews=total_pageviews,
    )
    return result


def get_revenue_metrics(
    site_id: str,
    period: str,
    *,
    revenue_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Retrieve aggregate revenue metrics for a site.

    Fetches affiliate revenue, click counts, conversion rates, and
    per-network breakdowns for the specified period.

    Parameters
    ----------
    site_id:
        Internal site identifier.
    period:
        Time period (e.g. ``"7d"``, ``"30d"``, ``"90d"``).
    revenue_data:
        Optional pre-fetched revenue data dict.

    Returns
    -------
    dict[str, Any]
        Revenue metrics dict with keys: ``site_id``, ``period``,
        ``total_revenue``, ``total_clicks``, ``total_conversions``,
        ``earnings_per_click``, ``conversion_rate``,
        ``revenue_by_network``, ``top_products``, ``revenue_trend``.
    """
    log_event(logger, "measure.revenue.start", site_id=site_id, period=period)

    start_dt, end_dt = _parse_period(period)
    data = revenue_data or {}

    total_revenue = float(data.get("total_revenue", 0.0))
    total_clicks = int(data.get("total_clicks", 0))
    total_conversions = int(data.get("total_conversions", 0))

    epc = total_revenue / total_clicks if total_clicks > 0 else 0.0
    conversion_rate = total_conversions / total_clicks if total_clicks > 0 else 0.0

    result: Dict[str, Any] = {
        "site_id": site_id,
        "period": period,
        "start_date": start_dt.strftime("%Y-%m-%d"),
        "end_date": end_dt.strftime("%Y-%m-%d"),
        "total_revenue": round(total_revenue, 2),
        "total_clicks": total_clicks,
        "total_conversions": total_conversions,
        "earnings_per_click": round(epc, 4),
        "conversion_rate": round(conversion_rate, 4),
        "revenue_by_network": data.get("revenue_by_network", {}),
        "top_products": data.get("top_products", []),
        "revenue_trend": data.get("revenue_trend", []),
    }

    log_event(
        logger,
        "measure.revenue.ok",
        site_id=site_id,
        period=period,
        revenue=total_revenue,
        epc=round(epc, 4),
    )
    return result
