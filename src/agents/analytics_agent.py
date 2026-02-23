"""
agents.analytics_agent
~~~~~~~~~~~~~~~~~~~~~~

The AnalyticsAgent tracks site performance by collecting traffic, revenue,
and engagement metrics from multiple sources (Google Analytics, affiliate
network APIs, CMS stats).  It produces periodic performance summaries that
the scheduler and other agents use to adjust strategy.

Design references:
    - ARCHITECTURE.md  Section 2 (Agent Architecture)
    - config/agents.yaml    (analytics settings)
    - config/providers.yaml (API keys and endpoints for analytics sources)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.agents.base_agent import BaseAgent
from src.core.constants import AgentName
from src.core.logger import log_event

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class TrafficSnapshot:
    """A point-in-time traffic measurement.

    Attributes:
        site:            Site identifier the metrics belong to.
        page_views:      Total page views in the period.
        unique_visitors: Unique visitors in the period.
        sessions:        Number of sessions.
        bounce_rate:     Bounce rate as a fraction (0-1).
        avg_session_duration: Average session duration in seconds.
        top_pages:       Top-performing pages by views.
        period_start:    Start of the measurement period.
        period_end:      End of the measurement period.
    """

    site: str
    page_views: int = 0
    unique_visitors: int = 0
    sessions: int = 0
    bounce_rate: float = 0.0
    avg_session_duration: float = 0.0
    top_pages: List[Dict[str, Any]] = field(default_factory=list)
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None


@dataclass
class RevenueSnapshot:
    """Revenue data from affiliate networks for a given period.

    Attributes:
        network:         Affiliate network name.
        clicks:          Total affiliate link clicks.
        conversions:     Number of conversions (sales/leads).
        revenue:         Total revenue earned (USD).
        epc:             Earnings per click.
        top_offers:      Best-performing offers by revenue.
        period_start:    Start of the measurement period.
        period_end:      End of the measurement period.
    """

    network: str
    clicks: int = 0
    conversions: int = 0
    revenue: float = 0.0
    epc: float = 0.0
    top_offers: List[Dict[str, Any]] = field(default_factory=list)
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None


@dataclass
class AnalyticsPlan:
    """Output of the planning phase -- what metrics to collect.

    Attributes:
        sites:           Site identifiers to collect traffic for.
        networks:        Affiliate networks to query for revenue.
        lookback_hours:  How many hours back to query.
        collect_traffic: Whether to collect traffic metrics.
        collect_revenue: Whether to collect revenue metrics.
        plan_time:       When the plan was generated.
    """

    sites: List[str] = field(default_factory=list)
    networks: List[str] = field(default_factory=list)
    lookback_hours: int = 24
    collect_traffic: bool = True
    collect_revenue: bool = True
    plan_time: Optional[datetime] = None


@dataclass
class AnalyticsExecutionResult:
    """Aggregated analytics data from all collection pipelines.

    Attributes:
        traffic:   Traffic snapshots per site.
        revenue:   Revenue snapshots per network.
        errors:    Errors encountered during collection.
    """

    traffic: Dict[str, TrafficSnapshot] = field(default_factory=dict)
    revenue: Dict[str, RevenueSnapshot] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Agent implementation
# ---------------------------------------------------------------------------


class AnalyticsAgent(BaseAgent):
    """Collects and summarises performance analytics from traffic and revenue sources.

    The analytics agent runs periodically (typically once or twice daily) to
    pull metrics from Google Analytics, affiliate network dashboards, and
    internal CMS statistics.  The summaries it produces are used by the
    scheduler to prioritise niches, content types, and publishing cadence.

    Configuration keys (from ``config/agents.yaml`` under ``analytics``):
        enabled:           bool  -- whether this agent is active.
        sites:             list  -- site identifiers to track.
        networks:          list  -- affiliate networks to query.
        lookback_hours:    int   -- default look-back window.
        ga_property_id:    str   -- Google Analytics property ID.
        revenue_api_keys:  dict  -- per-network API credentials.
    """

    def __init__(self, config: Dict[str, Any]) -> None:
        super().__init__(name=str(AgentName.ANALYTICS), config=config)
        self._sites: List[str] = config.get("sites", [])
        self._networks: List[str] = config.get("networks", [])
        self._lookback_hours: int = config.get("lookback_hours", 24)
        self._ga_property_id: str = config.get("ga_property_id", "")
        self._revenue_api_keys: Dict[str, str] = config.get("revenue_api_keys", {})

    # ------------------------------------------------------------------
    # BaseAgent lifecycle
    # ------------------------------------------------------------------

    def plan(self) -> AnalyticsPlan:
        """Determine which metrics to collect this cycle.

        Reads the configured sites and networks and produces a collection
        plan.  If certain data sources are temporarily unavailable, they
        may be excluded from the plan.

        Returns:
            An :class:`AnalyticsPlan` describing the collection scope.
        """
        log_event(
            self.logger,
            "analytics.plan.start",
            sites=len(self._sites),
            networks=len(self._networks),
        )

        plan = AnalyticsPlan(
            sites=list(self._sites),
            networks=list(self._networks),
            lookback_hours=self._lookback_hours,
            collect_traffic=bool(self._sites),
            collect_revenue=bool(self._networks),
            plan_time=datetime.now(timezone.utc),
        )

        log_event(
            self.logger,
            "analytics.plan.complete",
            traffic=plan.collect_traffic,
            revenue=plan.collect_revenue,
            lookback_hours=plan.lookback_hours,
        )
        return plan

    def execute(self, plan: AnalyticsPlan) -> AnalyticsExecutionResult:
        """Gather analytics data from all configured sources.

        Runs the traffic and revenue collection pipelines in sequence.

        Parameters:
            plan: The :class:`AnalyticsPlan` from planning.

        Returns:
            An :class:`AnalyticsExecutionResult` with collected snapshots.
        """
        result = AnalyticsExecutionResult()

        if plan.collect_traffic:
            for site in plan.sites:
                try:
                    snapshot = self._collect_traffic(site, plan.lookback_hours)
                    result.traffic[site] = snapshot
                    self.logger.info(
                        "Traffic collected for site '%s': %d page views, %d visitors.",
                        site,
                        snapshot.page_views,
                        snapshot.unique_visitors,
                    )
                except Exception as exc:
                    result.errors.append(f"Traffic collection for site '{site}': {exc}")
                    self.logger.error(
                        "Traffic collection failed for site '%s': %s",
                        site,
                        exc,
                    )

        if plan.collect_revenue:
            for network in plan.networks:
                try:
                    snapshot = self._collect_revenue(network, plan.lookback_hours)
                    result.revenue[network] = snapshot
                    self.logger.info(
                        "Revenue collected for network '%s': $%.2f (%d conversions).",
                        network,
                        snapshot.revenue,
                        snapshot.conversions,
                    )
                except Exception as exc:
                    result.errors.append(
                        f"Revenue collection for network '{network}': {exc}"
                    )
                    self.logger.error(
                        "Revenue collection failed for network '%s': %s",
                        network,
                        exc,
                    )

        return result

    def report(
        self, plan: AnalyticsPlan, result: AnalyticsExecutionResult
    ) -> Dict[str, Any]:
        """Generate performance summaries and log key metrics.

        Parameters:
            plan:   The analytics plan.
            result: The execution result.

        Returns:
            A summary dict for the orchestrator's audit log.
        """
        total_page_views = sum(t.page_views for t in result.traffic.values())
        total_visitors = sum(t.unique_visitors for t in result.traffic.values())
        total_revenue = sum(r.revenue for r in result.revenue.values())
        total_conversions = sum(r.conversions for r in result.revenue.values())
        total_clicks = sum(r.clicks for r in result.revenue.values())

        overall_epc = round(total_revenue / max(total_clicks, 1), 4)

        report_data: Dict[str, Any] = {
            "lookback_hours": plan.lookback_hours,
            "sites_queried": len(result.traffic),
            "networks_queried": len(result.revenue),
            "total_page_views": total_page_views,
            "total_unique_visitors": total_visitors,
            "total_revenue_usd": round(total_revenue, 2),
            "total_conversions": total_conversions,
            "total_clicks": total_clicks,
            "overall_epc": overall_epc,
            "per_site_traffic": {
                site: {
                    "page_views": snap.page_views,
                    "unique_visitors": snap.unique_visitors,
                    "bounce_rate": snap.bounce_rate,
                }
                for site, snap in result.traffic.items()
            },
            "per_network_revenue": {
                net: {
                    "revenue": snap.revenue,
                    "conversions": snap.conversions,
                    "epc": snap.epc,
                }
                for net, snap in result.revenue.items()
            },
            "errors": result.errors,
        }

        self._log_metric("analytics.page_views", total_page_views)
        self._log_metric("analytics.unique_visitors", total_visitors)
        self._log_metric("analytics.revenue_usd", round(total_revenue, 2))
        self._log_metric("analytics.conversions", total_conversions)
        self._log_metric("analytics.epc", overall_epc)
        self._log_metric("analytics.errors", len(result.errors))

        log_event(
            self.logger,
            "analytics.report.complete",
            page_views=total_page_views,
            revenue=round(total_revenue, 2),
            conversions=total_conversions,
        )
        return report_data

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _collect_traffic(self, site: str, lookback_hours: int) -> TrafficSnapshot:
        """Collect traffic metrics for a single site.

        In production this calls the Google Analytics Data API (GA4) or
        a similar analytics service.  The scaffold returns a zeroed snapshot.

        Parameters:
            site:           Site identifier to query.
            lookback_hours: Number of hours to look back.

        Returns:
            A :class:`TrafficSnapshot` with the collected metrics.
        """
        if self._check_dry_run(f"traffic collection for site '{site}'"):
            return TrafficSnapshot(site=site)

        now = datetime.now(timezone.utc)
        period_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)

        self.logger.debug(
            "Collecting traffic for site '%s' (lookback=%dh, ga_property=%s).",
            site,
            lookback_hours,
            self._ga_property_id,
        )

        # Placeholder: real implementation calls GA4 API
        return TrafficSnapshot(
            site=site,
            period_start=period_start,
            period_end=now,
        )

    def _collect_revenue(self, network: str, lookback_hours: int) -> RevenueSnapshot:
        """Collect revenue data from an affiliate network.

        In production this calls the affiliate network's reporting API.
        The scaffold returns a zeroed snapshot.

        Parameters:
            network:        Affiliate network name.
            lookback_hours: Number of hours to look back.

        Returns:
            A :class:`RevenueSnapshot` with the collected metrics.
        """
        if self._check_dry_run(f"revenue collection for network '{network}'"):
            return RevenueSnapshot(network=network)

        now = datetime.now(timezone.utc)
        period_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)

        api_key = self._revenue_api_keys.get(network, "")
        self.logger.debug(
            "Collecting revenue for network '%s' (lookback=%dh, key_present=%s).",
            network,
            lookback_hours,
            bool(api_key),
        )

        # Placeholder: real implementation calls the network API
        return RevenueSnapshot(
            network=network,
            period_start=period_start,
            period_end=now,
        )
