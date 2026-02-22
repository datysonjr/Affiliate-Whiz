"""
domains.analytics.reporting
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Report generation for the OpenClaw analytics domain.

Provides the :class:`SiteReport` dataclass and functions for generating
daily, weekly, and monthly performance reports across affiliate sites.
Reports aggregate traffic, revenue, content performance, and SEO metrics
into structured summaries for monitoring and decision-making.

Design references:
    - ARCHITECTURE.md  Section 5 (Analytics Domain)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from src.core.logger import get_logger, log_event

logger = get_logger("analytics.reporting")


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class TrafficSummary:
    """Aggregated traffic metrics for a reporting period.

    Attributes
    ----------
    page_views:
        Total page views.
    unique_visitors:
        Approximate unique visitor count.
    sessions:
        Total sessions.
    avg_session_duration:
        Average session duration in seconds.
    bounce_rate:
        Bounce rate as a percentage (0--100).
    top_pages:
        List of dicts with ``"url"``, ``"views"``, and ``"avg_time"`` keys,
        ordered by views descending.
    traffic_by_channel:
        Mapping of channel name to session count.
    """

    page_views: int = 0
    unique_visitors: int = 0
    sessions: int = 0
    avg_session_duration: float = 0.0
    bounce_rate: float = 0.0
    top_pages: List[Dict[str, Any]] = field(default_factory=list)
    traffic_by_channel: Dict[str, int] = field(default_factory=dict)


@dataclass
class RevenueSummary:
    """Aggregated revenue metrics for a reporting period.

    Attributes
    ----------
    total_revenue:
        Total affiliate revenue in USD.
    total_clicks:
        Total affiliate link clicks.
    total_conversions:
        Total conversions (purchases, sign-ups).
    conversion_rate:
        Conversion rate as a percentage.
    avg_order_value:
        Average order value in USD.
    revenue_by_network:
        Mapping of affiliate network name to revenue.
    revenue_by_page:
        Mapping of page URL to revenue attributed.
    top_products:
        List of dicts with ``"product"``, ``"revenue"``, ``"conversions"``
        keys, ordered by revenue descending.
    """

    total_revenue: float = 0.0
    total_clicks: int = 0
    total_conversions: int = 0
    conversion_rate: float = 0.0
    avg_order_value: float = 0.0
    revenue_by_network: Dict[str, float] = field(default_factory=dict)
    revenue_by_page: Dict[str, float] = field(default_factory=dict)
    top_products: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class ContentSummary:
    """Content performance metrics for a reporting period.

    Attributes
    ----------
    articles_published:
        Number of new articles published.
    articles_updated:
        Number of existing articles updated.
    total_word_count:
        Total words published across all new articles.
    avg_quality_score:
        Average content quality score (0--100).
    top_performing:
        List of dicts with ``"title"``, ``"url"``, ``"views"``,
        ``"revenue"`` keys for the best-performing content.
    underperforming:
        List of dicts for content that may need optimisation.
    """

    articles_published: int = 0
    articles_updated: int = 0
    total_word_count: int = 0
    avg_quality_score: float = 0.0
    top_performing: List[Dict[str, Any]] = field(default_factory=list)
    underperforming: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class SEOSummary:
    """SEO performance metrics for a reporting period.

    Attributes
    ----------
    indexed_pages:
        Number of pages indexed by search engines.
    avg_position:
        Average search ranking position.
    impressions:
        Total search impressions.
    clicks:
        Total organic search clicks.
    ctr:
        Click-through rate as a percentage.
    new_keywords_ranked:
        Number of new keywords that gained rankings.
    keywords_improved:
        Number of keywords that improved in position.
    keywords_declined:
        Number of keywords that declined in position.
    """

    indexed_pages: int = 0
    avg_position: float = 0.0
    impressions: int = 0
    clicks: int = 0
    ctr: float = 0.0
    new_keywords_ranked: int = 0
    keywords_improved: int = 0
    keywords_declined: int = 0


@dataclass
class SiteReport:
    """Complete performance report for a single affiliate site.

    Attributes
    ----------
    site_id:
        Site identifier.
    site_name:
        Human-readable site name.
    period:
        Report period label (e.g. ``"daily"``, ``"weekly"``, ``"monthly"``).
    start_date:
        Start of the reporting period (UTC).
    end_date:
        End of the reporting period (UTC).
    generated_at:
        UTC timestamp when the report was generated.
    traffic:
        Traffic metrics summary.
    revenue:
        Revenue metrics summary.
    content:
        Content performance summary.
    seo:
        SEO performance summary.
    alerts:
        List of alert messages (e.g. ``"Revenue dropped 20% vs last period"``).
    metadata:
        Additional report-level data.
    """

    site_id: str
    site_name: str = ""
    period: str = "daily"
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    generated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    traffic: TrafficSummary = field(default_factory=TrafficSummary)
    revenue: RevenueSummary = field(default_factory=RevenueSummary)
    content: ContentSummary = field(default_factory=ContentSummary)
    seo: SEOSummary = field(default_factory=SEOSummary)
    alerts: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Report generation functions
# ---------------------------------------------------------------------------

def generate_daily_report(
    site_id: str,
    *,
    site_name: str = "",
    reference_date: Optional[datetime] = None,
    traffic_data: Optional[Dict[str, Any]] = None,
    revenue_data: Optional[Dict[str, Any]] = None,
    content_data: Optional[Dict[str, Any]] = None,
    seo_data: Optional[Dict[str, Any]] = None,
) -> SiteReport:
    """Generate a daily performance report for a site.

    Aggregates the previous 24-hour period's traffic, revenue, content,
    and SEO metrics into a single :class:`SiteReport`.

    Parameters
    ----------
    site_id:
        Site identifier.
    site_name:
        Human-readable site name.
    reference_date:
        The date the report covers.  Defaults to yesterday (UTC).
    traffic_data:
        Raw traffic data to summarise.  If ``None``, traffic section
        will contain default (zero) values.
    revenue_data:
        Raw revenue data to summarise.
    content_data:
        Raw content performance data.
    seo_data:
        Raw SEO data from Search Console or similar.

    Returns
    -------
    SiteReport
        The generated daily report.
    """
    now = datetime.now(timezone.utc)
    ref = reference_date or (now - timedelta(days=1))
    start = ref.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)

    report = SiteReport(
        site_id=site_id,
        site_name=site_name,
        period="daily",
        start_date=start,
        end_date=end,
        generated_at=now,
    )

    if traffic_data:
        report.traffic = _build_traffic_summary(traffic_data)
    if revenue_data:
        report.revenue = _build_revenue_summary(revenue_data)
    if content_data:
        report.content = _build_content_summary(content_data)
    if seo_data:
        report.seo = _build_seo_summary(seo_data)

    report.alerts = _generate_alerts(report)

    log_event(
        logger, "reporting.daily_generated",
        site_id=site_id, date=start.strftime("%Y-%m-%d"),
        page_views=report.traffic.page_views,
        revenue=report.revenue.total_revenue,
        alerts=len(report.alerts),
    )

    return report


def generate_weekly_report(
    site_id: str,
    *,
    site_name: str = "",
    reference_date: Optional[datetime] = None,
    traffic_data: Optional[Dict[str, Any]] = None,
    revenue_data: Optional[Dict[str, Any]] = None,
    content_data: Optional[Dict[str, Any]] = None,
    seo_data: Optional[Dict[str, Any]] = None,
) -> SiteReport:
    """Generate a weekly performance report for a site.

    Aggregates the previous 7-day period's metrics.

    Parameters
    ----------
    site_id:
        Site identifier.
    site_name:
        Human-readable site name.
    reference_date:
        Any date within the reporting week.  Defaults to last week.
    traffic_data:
        Raw traffic data to summarise.
    revenue_data:
        Raw revenue data to summarise.
    content_data:
        Raw content performance data.
    seo_data:
        Raw SEO data.

    Returns
    -------
    SiteReport
        The generated weekly report.
    """
    now = datetime.now(timezone.utc)
    ref = reference_date or (now - timedelta(days=7))
    # Start from the Monday of the reference week
    start = ref.replace(hour=0, minute=0, second=0, microsecond=0)
    start = start - timedelta(days=start.weekday())
    end = start + timedelta(days=7)

    report = SiteReport(
        site_id=site_id,
        site_name=site_name,
        period="weekly",
        start_date=start,
        end_date=end,
        generated_at=now,
    )

    if traffic_data:
        report.traffic = _build_traffic_summary(traffic_data)
    if revenue_data:
        report.revenue = _build_revenue_summary(revenue_data)
    if content_data:
        report.content = _build_content_summary(content_data)
    if seo_data:
        report.seo = _build_seo_summary(seo_data)

    report.alerts = _generate_alerts(report)

    log_event(
        logger, "reporting.weekly_generated",
        site_id=site_id,
        week_start=start.strftime("%Y-%m-%d"),
        page_views=report.traffic.page_views,
        revenue=report.revenue.total_revenue,
    )

    return report


def generate_monthly_report(
    site_id: str,
    *,
    site_name: str = "",
    year: int = 0,
    month: int = 0,
    traffic_data: Optional[Dict[str, Any]] = None,
    revenue_data: Optional[Dict[str, Any]] = None,
    content_data: Optional[Dict[str, Any]] = None,
    seo_data: Optional[Dict[str, Any]] = None,
) -> SiteReport:
    """Generate a monthly performance report for a site.

    Aggregates a full calendar month's metrics.

    Parameters
    ----------
    site_id:
        Site identifier.
    site_name:
        Human-readable site name.
    year:
        Report year.  Defaults to the previous month.
    month:
        Report month (1--12).  Defaults to the previous month.
    traffic_data:
        Raw traffic data to summarise.
    revenue_data:
        Raw revenue data to summarise.
    content_data:
        Raw content performance data.
    seo_data:
        Raw SEO data.

    Returns
    -------
    SiteReport
        The generated monthly report.
    """
    now = datetime.now(timezone.utc)

    if not year or not month:
        # Default to previous month
        first_of_current = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        last_month_end = first_of_current - timedelta(days=1)
        year = last_month_end.year
        month = last_month_end.month

    start = datetime(year, month, 1, tzinfo=timezone.utc)
    # Calculate end of month
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)

    report = SiteReport(
        site_id=site_id,
        site_name=site_name,
        period="monthly",
        start_date=start,
        end_date=end,
        generated_at=now,
    )

    if traffic_data:
        report.traffic = _build_traffic_summary(traffic_data)
    if revenue_data:
        report.revenue = _build_revenue_summary(revenue_data)
    if content_data:
        report.content = _build_content_summary(content_data)
    if seo_data:
        report.seo = _build_seo_summary(seo_data)

    report.alerts = _generate_alerts(report)

    log_event(
        logger, "reporting.monthly_generated",
        site_id=site_id,
        year=year, month=month,
        page_views=report.traffic.page_views,
        revenue=report.revenue.total_revenue,
    )

    return report


# ---------------------------------------------------------------------------
# Internal builders
# ---------------------------------------------------------------------------

def _build_traffic_summary(data: Dict[str, Any]) -> TrafficSummary:
    """Build a TrafficSummary from raw traffic data.

    Parameters
    ----------
    data:
        Dict with keys such as ``"page_views"``, ``"unique_visitors"``,
        ``"sessions"``, ``"avg_session_duration"``, ``"bounce_rate"``,
        ``"top_pages"``, ``"traffic_by_channel"``.

    Returns
    -------
    TrafficSummary
        Populated traffic summary.
    """
    return TrafficSummary(
        page_views=int(data.get("page_views", 0)),
        unique_visitors=int(data.get("unique_visitors", 0)),
        sessions=int(data.get("sessions", 0)),
        avg_session_duration=float(data.get("avg_session_duration", 0.0)),
        bounce_rate=float(data.get("bounce_rate", 0.0)),
        top_pages=data.get("top_pages", []),
        traffic_by_channel=data.get("traffic_by_channel", {}),
    )


def _build_revenue_summary(data: Dict[str, Any]) -> RevenueSummary:
    """Build a RevenueSummary from raw revenue data.

    Parameters
    ----------
    data:
        Dict with keys such as ``"total_revenue"``, ``"total_clicks"``,
        ``"total_conversions"``, ``"revenue_by_network"``, etc.

    Returns
    -------
    RevenueSummary
        Populated revenue summary.
    """
    total_clicks = int(data.get("total_clicks", 0))
    total_conversions = int(data.get("total_conversions", 0))
    total_revenue = float(data.get("total_revenue", 0.0))

    conversion_rate = 0.0
    if total_clicks > 0:
        conversion_rate = round((total_conversions / total_clicks) * 100, 2)

    avg_order = 0.0
    if total_conversions > 0:
        avg_order = round(total_revenue / total_conversions, 2)

    return RevenueSummary(
        total_revenue=total_revenue,
        total_clicks=total_clicks,
        total_conversions=total_conversions,
        conversion_rate=conversion_rate,
        avg_order_value=avg_order,
        revenue_by_network=data.get("revenue_by_network", {}),
        revenue_by_page=data.get("revenue_by_page", {}),
        top_products=data.get("top_products", []),
    )


def _build_content_summary(data: Dict[str, Any]) -> ContentSummary:
    """Build a ContentSummary from raw content performance data.

    Parameters
    ----------
    data:
        Dict with keys such as ``"articles_published"``,
        ``"articles_updated"``, ``"total_word_count"``, etc.

    Returns
    -------
    ContentSummary
        Populated content summary.
    """
    return ContentSummary(
        articles_published=int(data.get("articles_published", 0)),
        articles_updated=int(data.get("articles_updated", 0)),
        total_word_count=int(data.get("total_word_count", 0)),
        avg_quality_score=float(data.get("avg_quality_score", 0.0)),
        top_performing=data.get("top_performing", []),
        underperforming=data.get("underperforming", []),
    )


def _build_seo_summary(data: Dict[str, Any]) -> SEOSummary:
    """Build an SEOSummary from raw SEO data.

    Parameters
    ----------
    data:
        Dict with keys such as ``"indexed_pages"``, ``"avg_position"``,
        ``"impressions"``, ``"clicks"``, etc.

    Returns
    -------
    SEOSummary
        Populated SEO summary.
    """
    impressions = int(data.get("impressions", 0))
    clicks = int(data.get("clicks", 0))
    ctr = 0.0
    if impressions > 0:
        ctr = round((clicks / impressions) * 100, 2)

    return SEOSummary(
        indexed_pages=int(data.get("indexed_pages", 0)),
        avg_position=float(data.get("avg_position", 0.0)),
        impressions=impressions,
        clicks=clicks,
        ctr=ctr,
        new_keywords_ranked=int(data.get("new_keywords_ranked", 0)),
        keywords_improved=int(data.get("keywords_improved", 0)),
        keywords_declined=int(data.get("keywords_declined", 0)),
    )


def _generate_alerts(report: SiteReport) -> List[str]:
    """Generate alert messages based on report metrics.

    Checks for concerning patterns such as zero traffic, zero revenue,
    high bounce rates, or declining SEO metrics.

    Parameters
    ----------
    report:
        The report to analyse for alerts.

    Returns
    -------
    list[str]
        Human-readable alert messages.
    """
    alerts: List[str] = []

    if report.traffic.page_views == 0:
        alerts.append("Zero page views recorded for this period")

    if report.traffic.bounce_rate > 80:
        alerts.append(
            f"High bounce rate: {report.traffic.bounce_rate:.1f}% "
            "(threshold: 80%)"
        )

    if report.revenue.total_clicks > 0 and report.revenue.conversion_rate < 0.5:
        alerts.append(
            f"Low conversion rate: {report.revenue.conversion_rate:.2f}% "
            "(threshold: 0.5%)"
        )

    if report.seo.keywords_declined > report.seo.keywords_improved:
        decline_net = report.seo.keywords_declined - report.seo.keywords_improved
        alerts.append(
            f"Net keyword ranking decline: {decline_net} more keywords "
            "declined than improved"
        )

    if report.content.avg_quality_score > 0 and report.content.avg_quality_score < 60:
        alerts.append(
            f"Low average content quality score: "
            f"{report.content.avg_quality_score:.1f} (threshold: 60)"
        )

    return alerts
