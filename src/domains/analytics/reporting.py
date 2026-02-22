"""
domains.analytics.reporting
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Report generation for the OpenClaw analytics domain.

Provides functions to generate daily, weekly, and monthly performance
reports from event data.  Reports summarise traffic, conversions,
revenue, and content performance metrics across individual sites and
niches.

Design references:
    - ARCHITECTURE.md  Section 5 (Analytics Domain)
    - AI_RULES.md      Operational Rule #5 (audit trail / logging)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from src.core.logger import get_logger
from src.domains.analytics.events import AggregationResult, EventTracker, EventType

logger = get_logger("analytics.reporting")


# ---------------------------------------------------------------------------
# Report data models
# ---------------------------------------------------------------------------

@dataclass
class TrafficMetrics:
    """Traffic-level metrics for a reporting period.

    Attributes
    ----------
    page_views:
        Total page views.
    unique_sessions:
        Unique session count.
    unique_pages:
        Number of distinct pages viewed.
    top_pages:
        Top pages by view count (page -> count).
    top_sources:
        Top traffic sources (source -> count).
    bounce_rate:
        Estimated bounce rate (0.0--1.0).
    """

    page_views: int = 0
    unique_sessions: int = 0
    unique_pages: int = 0
    top_pages: Dict[str, int] = field(default_factory=dict)
    top_sources: Dict[str, int] = field(default_factory=dict)
    bounce_rate: float = 0.0


@dataclass
class ConversionMetrics:
    """Conversion and revenue metrics for a reporting period.

    Attributes
    ----------
    affiliate_clicks:
        Total affiliate link clicks.
    conversions:
        Total conversion events.
    revenue:
        Total revenue from conversions.
    conversion_rate:
        Conversion rate (conversions / affiliate_clicks).
    avg_order_value:
        Average conversion value.
    epc:
        Earnings per click (revenue / affiliate_clicks).
    top_converting_pages:
        Pages with the most conversions (page -> count).
    revenue_by_source:
        Revenue breakdown by traffic source (source -> value).
    """

    affiliate_clicks: int = 0
    conversions: int = 0
    revenue: float = 0.0
    conversion_rate: float = 0.0
    avg_order_value: float = 0.0
    epc: float = 0.0
    top_converting_pages: Dict[str, int] = field(default_factory=dict)
    revenue_by_source: Dict[str, float] = field(default_factory=dict)


@dataclass
class ContentMetrics:
    """Content performance metrics for a reporting period.

    Attributes
    ----------
    articles_published:
        Number of articles published during the period.
    total_word_count:
        Total words published.
    avg_quality_score:
        Average content quality score.
    top_performing_articles:
        Articles with the most page views (title -> views).
    articles_with_conversions:
        Number of articles that generated at least one conversion.
    """

    articles_published: int = 0
    total_word_count: int = 0
    avg_quality_score: float = 0.0
    top_performing_articles: Dict[str, int] = field(default_factory=dict)
    articles_with_conversions: int = 0


@dataclass
class SiteReport:
    """Performance report for a single affiliate site.

    Attributes
    ----------
    site_id:
        Site identifier.
    site_name:
        Human-readable site name.
    period_start:
        Start of the reporting period.
    period_end:
        End of the reporting period.
    period_label:
        Human-readable period label (e.g. ``"2025-01-15 (daily)"``).
    traffic:
        Traffic metrics for the period.
    conversions:
        Conversion and revenue metrics.
    content:
        Content performance metrics.
    generated_at:
        UTC timestamp when the report was generated.
    metadata:
        Additional report data.
    """

    site_id: str
    site_name: str = ""
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None
    period_label: str = ""
    traffic: TrafficMetrics = field(default_factory=TrafficMetrics)
    conversions: ConversionMetrics = field(default_factory=ConversionMetrics)
    content: ContentMetrics = field(default_factory=ContentMetrics)
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the report to a JSON-friendly dictionary."""
        return {
            "site_id": self.site_id,
            "site_name": self.site_name,
            "period_start": self.period_start.isoformat() if self.period_start else None,
            "period_end": self.period_end.isoformat() if self.period_end else None,
            "period_label": self.period_label,
            "traffic": {
                "page_views": self.traffic.page_views,
                "unique_sessions": self.traffic.unique_sessions,
                "unique_pages": self.traffic.unique_pages,
                "top_pages": self.traffic.top_pages,
                "top_sources": self.traffic.top_sources,
                "bounce_rate": self.traffic.bounce_rate,
            },
            "conversions": {
                "affiliate_clicks": self.conversions.affiliate_clicks,
                "conversions": self.conversions.conversions,
                "revenue": self.conversions.revenue,
                "conversion_rate": self.conversions.conversion_rate,
                "avg_order_value": self.conversions.avg_order_value,
                "epc": self.conversions.epc,
                "top_converting_pages": self.conversions.top_converting_pages,
                "revenue_by_source": self.conversions.revenue_by_source,
            },
            "content": {
                "articles_published": self.content.articles_published,
                "total_word_count": self.content.total_word_count,
                "avg_quality_score": self.content.avg_quality_score,
                "articles_with_conversions": self.content.articles_with_conversions,
            },
            "generated_at": self.generated_at.isoformat(),
            "metadata": self.metadata,
        }


@dataclass
class NicheReport:
    """Aggregated performance report across all sites in a niche.

    Attributes
    ----------
    niche:
        Niche identifier (e.g. ``"home_office"``).
    period_start:
        Start of the reporting period.
    period_end:
        End of the reporting period.
    period_label:
        Human-readable period label.
    site_reports:
        Individual site reports within this niche.
    total_revenue:
        Sum of revenue across all sites.
    total_page_views:
        Sum of page views across all sites.
    total_conversions:
        Sum of conversions across all sites.
    overall_conversion_rate:
        Aggregate conversion rate.
    best_performing_site:
        Site ID of the highest-revenue site.
    generated_at:
        UTC timestamp when the report was generated.
    """

    niche: str
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None
    period_label: str = ""
    site_reports: List[SiteReport] = field(default_factory=list)
    total_revenue: float = 0.0
    total_page_views: int = 0
    total_conversions: int = 0
    overall_conversion_rate: float = 0.0
    best_performing_site: str = ""
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def compute_aggregates(self) -> None:
        """Recompute aggregate metrics from the site reports."""
        self.total_revenue = sum(r.conversions.revenue for r in self.site_reports)
        self.total_page_views = sum(r.traffic.page_views for r in self.site_reports)
        self.total_conversions = sum(r.conversions.conversions for r in self.site_reports)

        total_clicks = sum(r.conversions.affiliate_clicks for r in self.site_reports)
        self.overall_conversion_rate = (
            round(self.total_conversions / total_clicks, 4)
            if total_clicks > 0
            else 0.0
        )

        if self.site_reports:
            best = max(self.site_reports, key=lambda r: r.conversions.revenue)
            self.best_performing_site = best.site_id


# ---------------------------------------------------------------------------
# Report generation functions
# ---------------------------------------------------------------------------

def _build_site_report(
    tracker: EventTracker,
    site_id: str,
    start: datetime,
    end: datetime,
    period_label: str,
) -> SiteReport:
    """Build a site report from event tracker data.

    Parameters
    ----------
    tracker:
        Event tracker containing the events.
    site_id:
        Site to report on.
    start:
        Period start (inclusive).
    end:
        Period end (exclusive).
    period_label:
        Human-readable period label.

    Returns
    -------
    SiteReport
        Populated site report.
    """
    report = SiteReport(
        site_id=site_id,
        period_start=start,
        period_end=end,
        period_label=period_label,
    )

    # --- Traffic ---
    pv_agg = tracker.aggregate(
        metric="count",
        event_type=EventType.PAGE_VIEW,
        site_id=site_id,
        start_time=start,
        end_time=end,
    )
    report.traffic.page_views = int(pv_agg.value)

    sessions_agg = tracker.aggregate(
        metric="unique_sessions",
        event_type=EventType.PAGE_VIEW,
        site_id=site_id,
        start_time=start,
        end_time=end,
    )
    report.traffic.unique_sessions = int(sessions_agg.value)

    pages_agg = tracker.aggregate(
        metric="unique_pages",
        event_type=EventType.PAGE_VIEW,
        site_id=site_id,
        start_time=start,
        end_time=end,
    )
    report.traffic.unique_pages = int(pages_agg.value)

    # Top pages by views
    pv_by_page = tracker.aggregate(
        metric="count",
        event_type=EventType.PAGE_VIEW,
        site_id=site_id,
        group_by="page",
        start_time=start,
        end_time=end,
    )
    sorted_pages = sorted(pv_by_page.breakdown.items(), key=lambda x: x[1], reverse=True)
    report.traffic.top_pages = {p: int(v) for p, v in sorted_pages[:10]}

    # Top sources
    pv_by_source = tracker.aggregate(
        metric="count",
        event_type=EventType.PAGE_VIEW,
        site_id=site_id,
        group_by="source",
        start_time=start,
        end_time=end,
    )
    sorted_sources = sorted(pv_by_source.breakdown.items(), key=lambda x: x[1], reverse=True)
    report.traffic.top_sources = {s: int(v) for s, v in sorted_sources[:10]}

    # Bounce rate estimate
    bounces = tracker.aggregate(
        metric="count",
        event_type=EventType.BOUNCE,
        site_id=site_id,
        start_time=start,
        end_time=end,
    )
    if report.traffic.unique_sessions > 0:
        report.traffic.bounce_rate = round(
            bounces.value / report.traffic.unique_sessions, 4
        )

    # --- Conversions ---
    clicks_agg = tracker.aggregate(
        metric="count",
        event_type=EventType.AFFILIATE_CLICK,
        site_id=site_id,
        start_time=start,
        end_time=end,
    )
    report.conversions.affiliate_clicks = int(clicks_agg.value)

    conv_agg = tracker.aggregate(
        metric="count",
        event_type=EventType.CONVERSION,
        site_id=site_id,
        start_time=start,
        end_time=end,
    )
    report.conversions.conversions = int(conv_agg.value)

    revenue_agg = tracker.aggregate(
        metric="sum",
        event_type=EventType.CONVERSION,
        site_id=site_id,
        start_time=start,
        end_time=end,
    )
    report.conversions.revenue = round(revenue_agg.value, 2)

    if report.conversions.affiliate_clicks > 0:
        report.conversions.conversion_rate = round(
            report.conversions.conversions / report.conversions.affiliate_clicks, 4
        )
        report.conversions.epc = round(
            report.conversions.revenue / report.conversions.affiliate_clicks, 4
        )

    if report.conversions.conversions > 0:
        report.conversions.avg_order_value = round(
            report.conversions.revenue / report.conversions.conversions, 2
        )

    # Top converting pages
    conv_by_page = tracker.aggregate(
        metric="count",
        event_type=EventType.CONVERSION,
        site_id=site_id,
        group_by="page",
        start_time=start,
        end_time=end,
    )
    sorted_conv_pages = sorted(conv_by_page.breakdown.items(), key=lambda x: x[1], reverse=True)
    report.conversions.top_converting_pages = {p: int(v) for p, v in sorted_conv_pages[:10]}

    # Revenue by source
    rev_by_source = tracker.aggregate(
        metric="sum",
        event_type=EventType.CONVERSION,
        site_id=site_id,
        group_by="source",
        start_time=start,
        end_time=end,
    )
    report.conversions.revenue_by_source = {
        s: round(v, 2) for s, v in rev_by_source.breakdown.items()
    }

    logger.info(
        "Built %s report for site '%s': %d PVs, %d conversions, $%.2f revenue",
        period_label,
        site_id,
        report.traffic.page_views,
        report.conversions.conversions,
        report.conversions.revenue,
    )
    return report


def generate_daily_report(
    tracker: EventTracker,
    site_id: str,
    *,
    date: Optional[datetime] = None,
) -> SiteReport:
    """Generate a daily performance report for a site.

    Parameters
    ----------
    tracker:
        Event tracker containing the events.
    site_id:
        Site to report on.
    date:
        The date to report on.  Defaults to yesterday (UTC).

    Returns
    -------
    SiteReport
        Daily performance report.
    """
    if date is None:
        date = datetime.now(timezone.utc) - timedelta(days=1)

    start = date.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    label = f"{start.strftime('%Y-%m-%d')} (daily)"

    return _build_site_report(tracker, site_id, start, end, label)


def generate_weekly_report(
    tracker: EventTracker,
    site_id: str,
    *,
    week_ending: Optional[datetime] = None,
) -> SiteReport:
    """Generate a weekly performance report for a site.

    Parameters
    ----------
    tracker:
        Event tracker containing the events.
    site_id:
        Site to report on.
    week_ending:
        The last day of the reporting week.  Defaults to yesterday (UTC).

    Returns
    -------
    SiteReport
        Weekly performance report.
    """
    if week_ending is None:
        week_ending = datetime.now(timezone.utc) - timedelta(days=1)

    end = week_ending.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    start = end - timedelta(days=7)
    label = f"{start.strftime('%Y-%m-%d')} to {(end - timedelta(days=1)).strftime('%Y-%m-%d')} (weekly)"

    return _build_site_report(tracker, site_id, start, end, label)


def generate_monthly_report(
    tracker: EventTracker,
    site_id: str,
    *,
    year: Optional[int] = None,
    month: Optional[int] = None,
) -> SiteReport:
    """Generate a monthly performance report for a site.

    Parameters
    ----------
    tracker:
        Event tracker containing the events.
    site_id:
        Site to report on.
    year:
        Report year.  Defaults to the current year.
    month:
        Report month (1--12).  Defaults to the previous month.

    Returns
    -------
    SiteReport
        Monthly performance report.
    """
    now = datetime.now(timezone.utc)
    if year is None or month is None:
        # Default to previous month
        first_of_current = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        last_month_end = first_of_current
        last_month_start = (first_of_current - timedelta(days=1)).replace(day=1)
        start = last_month_start
        end = last_month_end
    else:
        start = datetime(year, month, 1, tzinfo=timezone.utc)
        if month == 12:
            end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
        else:
            end = datetime(year, month + 1, 1, tzinfo=timezone.utc)

    label = f"{start.strftime('%Y-%m')} (monthly)"

    return _build_site_report(tracker, site_id, start, end, label)
