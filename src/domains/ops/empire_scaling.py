"""
domains.ops.empire_scaling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

OpenClaw Automated Empire Scaling Plan.

Manages portfolio-level growth decisions: when to add sites, when to
hold, when to rotate capacity, and how to scale without tripping
algorithm or budget traps.

Implements the strategy from
``docs/ops/OPENCLAW_AUTOMATED_EMPIRE_SCALING_PLAN.md``.

The system:
    1. Classifies the portfolio into one of 4 scaling stages
    2. Checks expansion readiness via multi-signal triggers
    3. Detects niche saturation
    4. Computes capacity allocation (60/30/10 rotation)
    5. Enforces safe publishing rates per site maturity
    6. Scores domain health for each site
    7. Applies budget protection and kill-fast policies
    8. Returns scaling decisions and launch schedules

Design references:
    - docs/ops/OPENCLAW_AUTOMATED_EMPIRE_SCALING_PLAN.md
    - src/domains/seo/authority_snowball.py  (GrowthStage)
    - src/domains/seo/monopoly_strategy.py   (NicheMonopolyPlan)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum, Enum, unique
from typing import Any, Dict, List, Sequence

from src.core.logger import get_logger, log_event

logger = get_logger("domains.ops.empire_scaling")


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


@unique
class ScalingStage(IntEnum):
    """The 4 stages of OpenClaw empire scaling."""

    VALIDATION = 1  # 0-1 winning site: prove real revenue
    REPLICATION = 2  # 1→3 sites: confirm pattern is repeatable
    PORTFOLIO = 3  # 3→10 sites: diversify revenue sources
    EMPIRE = 4  # 10+ sites: maximize ROI per compute hour


@unique
class SiteMaturity(str, Enum):
    """Site maturity classification for publishing speed limits."""

    NEW = "new"  # <30 days, 2-4 pages/week
    GROWING = "growing"  # 30-180 days with traction, 4-8 pages/week
    AUTHORITY = "authority"  # 180+ days with strong metrics, 8-15 pages/week


@unique
class SiteVerdict(str, Enum):
    """Operational verdict for a site."""

    EXPAND = "expand"  # healthy — continue publishing
    HOLD = "hold"  # signals mixed — maintain but don't grow
    REFRESH_ONLY = "refresh_only"  # health issues — fix before new content
    KILL = "kill"  # kill-fast policy triggered
    SATURATED = "saturated"  # niche saturated — redirect capacity


@unique
class CapacityBucket(str, Enum):
    """The 3 compute capacity buckets from the 60/30/10 rule."""

    REFRESH = "refresh"  # 60% — refresh + optimization
    EXPANSION = "expansion"  # 30% — validated cluster expansion
    EXPERIMENTAL = "experimental"  # 10% — trend tests / new niches


# ---------------------------------------------------------------------------
# Constants from the spec
# ---------------------------------------------------------------------------

# Validation stage thresholds
VALIDATION_MIN_INDEXED_PAGES = 20
VALIDATION_MIN_IMPRESSION_DAYS = 30
VALIDATION_MIN_CONVERTING_PAGES = 1

# Replication window
REPLICATION_TEST_CLUSTER_PAGES = 20
REPLICATION_VALIDATION_DAYS = 90

# Portfolio expansion — need ANY TWO of these
EXPANSION_TRIGGER_COUNT = 2

# Staggered launch cadence
MIN_WEEKS_BETWEEN_LAUNCHES = 4
MAX_WEEKS_BETWEEN_LAUNCHES = 8

# Safe publishing ranges (pages per week)
PUBLISHING_RATE_NEW: tuple[int, int] = (2, 4)
PUBLISHING_RATE_GROWING: tuple[int, int] = (4, 8)
PUBLISHING_RATE_AUTHORITY: tuple[int, int] = (8, 15)

# Capacity rotation percentages
CAPACITY_REFRESH_PCT = 60
CAPACITY_EXPANSION_PCT = 30
CAPACITY_EXPERIMENTAL_PCT = 10

# Domain health thresholds
HEALTH_INDEX_COVERAGE_MIN = 70  # percent
HEALTH_ERROR_RATE_MAX = 5  # percent

# Kill-fast policy thresholds
KILL_NO_INDEX_DAYS = 45
KILL_NO_IMPRESSIONS_DAYS = 60
KILL_NO_RANKING_DAYS = 90

# Niche saturation thresholds
SATURATION_RANKING_DAYS = 90
SATURATION_PLATEAU_DAYS = 60

# Budget protection
MAX_INFRA_COST_RATIO = 0.20  # infra costs must be < 20% of revenue

# 50-site automation threshold
AUTOMATION_THRESHOLD_SITES = 50


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class SiteMetrics:
    """Operational metrics for a single site.

    Attributes
    ----------
    site_id:
        Unique identifier for the site.
    niche:
        Primary niche the site targets.
    age_days:
        Days since site launch.
    total_pages:
        Total published pages.
    indexed_pages:
        Pages confirmed indexed by search engines.
    monthly_impressions:
        Search impressions in the last 30 days.
    impressions_trend:
        Impressions growth rate (-1.0 to +1.0).
    monthly_clicks:
        Clicks from search in the last 30 days.
    converting_pages:
        Number of pages generating affiliate revenue.
    monthly_revenue:
        Revenue in the last 30 days (USD).
    monthly_cost:
        Infrastructure + content cost for this site (USD).
    has_manual_penalty:
        Whether a manual penalty is active.
    avg_days_to_rank:
        Average days for new pages to enter top 100.
    ctr_trend:
        CTR growth rate (-1.0 to +1.0).
    refresh_backlog:
        Number of pages overdue for refresh.
    error_rate:
        Percentage of pages with errors (404s, broken schema, etc.).
    days_since_last_launch:
        Days since the most recent page was published.
    metadata:
        Additional tracking data.
    """

    site_id: str
    niche: str = ""
    age_days: int = 0
    total_pages: int = 0
    indexed_pages: int = 0
    monthly_impressions: int = 0
    impressions_trend: float = 0.0
    monthly_clicks: int = 0
    converting_pages: int = 0
    monthly_revenue: float = 0.0
    monthly_cost: float = 0.0
    has_manual_penalty: bool = False
    avg_days_to_rank: float = 30.0
    ctr_trend: float = 0.0
    refresh_backlog: int = 0
    error_rate: float = 0.0
    days_since_last_launch: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def index_coverage(self) -> float:
        """Percentage of pages that are indexed."""
        if self.total_pages <= 0:
            return 0.0
        return round((self.indexed_pages / self.total_pages) * 100, 1)

    @property
    def revenue_per_page(self) -> float:
        """Monthly revenue per published page."""
        if self.total_pages <= 0:
            return 0.0
        return round(self.monthly_revenue / self.total_pages, 2)

    @property
    def roi(self) -> float:
        """Return on investment (revenue / cost). 0 if no cost."""
        if self.monthly_cost <= 0:
            return 0.0
        return round(self.monthly_revenue / self.monthly_cost, 2)

    @property
    def is_profitable(self) -> bool:
        return self.monthly_revenue > self.monthly_cost


@dataclass
class DomainHealthScore:
    """Health assessment for a single site.

    From the spec — each site should maintain:
    - index coverage > 70%
    - impressions trending upward
    - refresh cycle on time
    - error rate low
    """

    site_id: str = ""
    index_coverage_ok: bool = False
    impressions_rising: bool = False
    refresh_on_time: bool = False
    error_rate_ok: bool = False
    score: float = 0.0  # 0-100

    @property
    def is_healthy(self) -> bool:
        """True if all 4 health dimensions pass."""
        return (
            self.index_coverage_ok
            and self.impressions_rising
            and self.refresh_on_time
            and self.error_rate_ok
        )


@dataclass
class CapacityAllocation:
    """Compute capacity allocation across the 60/30/10 buckets.

    Attributes
    ----------
    total_capacity:
        Total available compute units (abstract).
    refresh_capacity:
        Units allocated to refresh + optimization (60%).
    expansion_capacity:
        Units allocated to validated cluster expansion (30%).
    experimental_capacity:
        Units allocated to experimental niches / trends (10%).
    """

    total_capacity: float = 100.0
    refresh_capacity: float = 60.0
    expansion_capacity: float = 30.0
    experimental_capacity: float = 10.0


@dataclass
class SiteScalingDecision:
    """Scaling decision for a single site.

    Attributes
    ----------
    site_id:
        Site identifier.
    verdict:
        Operational verdict (expand, hold, refresh_only, kill, saturated).
    maturity:
        Site maturity classification.
    max_pages_per_week:
        Safe publishing rate for this site.
    health:
        Domain health score breakdown.
    reasons:
        Human-readable reasons for the verdict.
    """

    site_id: str = ""
    verdict: SiteVerdict = SiteVerdict.HOLD
    maturity: SiteMaturity = SiteMaturity.NEW
    max_pages_per_week: int = 2
    health: DomainHealthScore = field(default_factory=DomainHealthScore)
    reasons: List[str] = field(default_factory=list)


@dataclass
class ExpansionTriggerCheck:
    """Result of checking the portfolio expansion triggers.

    From the spec — ANY TWO of 5 conditions must be met.
    """

    revenue_increasing: bool = False
    indexing_stable: bool = False
    no_penalties: bool = False
    refresh_under_control: bool = False
    infra_costs_safe: bool = False

    @property
    def triggers_met(self) -> int:
        """Count of satisfied expansion triggers."""
        return sum(
            [
                self.revenue_increasing,
                self.indexing_stable,
                self.no_penalties,
                self.refresh_under_control,
                self.infra_costs_safe,
            ]
        )

    @property
    def can_expand(self) -> bool:
        """True if enough triggers are met."""
        return self.triggers_met >= EXPANSION_TRIGGER_COUNT


@dataclass
class PortfolioScalingPlan:
    """Full scaling plan for the entire portfolio.

    Attributes
    ----------
    stage:
        Current scaling stage.
    site_decisions:
        Per-site scaling decisions.
    expansion_check:
        Expansion trigger assessment.
    can_launch_new_site:
        Whether conditions support a new site launch.
    next_launch_weeks:
        Recommended weeks until next launch (0 = now).
    capacity:
        Compute capacity allocation.
    saturated_niches:
        Niches flagged as saturated.
    needs_automation_upgrade:
        True if portfolio exceeds 50-site threshold.
    portfolio_roi:
        Portfolio-wide ROI.
    """

    stage: ScalingStage = ScalingStage.VALIDATION
    site_decisions: List[SiteScalingDecision] = field(default_factory=list)
    expansion_check: ExpansionTriggerCheck = field(
        default_factory=ExpansionTriggerCheck
    )
    can_launch_new_site: bool = False
    next_launch_weeks: int = 0
    capacity: CapacityAllocation = field(default_factory=CapacityAllocation)
    saturated_niches: List[str] = field(default_factory=list)
    needs_automation_upgrade: bool = False
    portfolio_roi: float = 0.0

    @property
    def total_sites(self) -> int:
        return len(self.site_decisions)

    @property
    def healthy_sites(self) -> int:
        return sum(1 for d in self.site_decisions if d.verdict == SiteVerdict.EXPAND)

    @property
    def kill_candidates(self) -> int:
        return sum(1 for d in self.site_decisions if d.verdict == SiteVerdict.KILL)


# ---------------------------------------------------------------------------
# Scaling stage determination
# ---------------------------------------------------------------------------


def determine_scaling_stage(sites: Sequence[SiteMetrics]) -> ScalingStage:
    """Classify the portfolio into a scaling stage.

    From the spec::

        Stage 1 — Validation (0-1 winning site)
        Stage 2 — Replication (1→3 sites)
        Stage 3 — Portfolio Expansion (3→10 sites)
        Stage 4 — Empire Optimization (10+ sites)
    """
    profitable_count = sum(1 for s in sites if s.is_profitable)
    total = len(sites)

    if total == 0 or profitable_count == 0:
        return ScalingStage.VALIDATION
    if total < 3:
        return ScalingStage.REPLICATION
    if total < 10:
        return ScalingStage.PORTFOLIO
    return ScalingStage.EMPIRE


# ---------------------------------------------------------------------------
# Site maturity classification
# ---------------------------------------------------------------------------


def classify_site_maturity(site: SiteMetrics) -> SiteMaturity:
    """Classify a site's maturity for publishing speed limits.

    From the spec::

        New site: 2-4 pages per week
        Growing site: 4-8 pages per week
        Large authority site: 8-15 pages per week
    """
    if site.age_days < 30:
        return SiteMaturity.NEW
    if site.age_days >= 180 and site.total_pages >= 80 and site.index_coverage >= 70:
        return SiteMaturity.AUTHORITY
    return SiteMaturity.GROWING


def get_safe_publishing_rate(maturity: SiteMaturity) -> tuple[int, int]:
    """Return (min, max) safe pages per week for a maturity level."""
    rates = {
        SiteMaturity.NEW: PUBLISHING_RATE_NEW,
        SiteMaturity.GROWING: PUBLISHING_RATE_GROWING,
        SiteMaturity.AUTHORITY: PUBLISHING_RATE_AUTHORITY,
    }
    return rates.get(maturity, PUBLISHING_RATE_NEW)


# ---------------------------------------------------------------------------
# Domain health scoring
# ---------------------------------------------------------------------------


def compute_domain_health(site: SiteMetrics) -> DomainHealthScore:
    """Score the health of a single site.

    From the spec — each site should maintain:
    - index coverage > 70%
    - average page impressions trending upward
    - refresh cycle completed on time
    - error rate low (404s, broken schema, etc.)

    Sites failing these should not receive new content.
    """
    index_ok = site.index_coverage >= HEALTH_INDEX_COVERAGE_MIN
    impressions_ok = site.impressions_trend > 0
    refresh_ok = site.refresh_backlog == 0
    error_ok = site.error_rate <= HEALTH_ERROR_RATE_MAX

    # Score: 25 points per dimension
    score = 0.0
    if index_ok:
        score += 25
    if impressions_ok:
        score += 25
    if refresh_ok:
        score += 25
    if error_ok:
        score += 25

    return DomainHealthScore(
        site_id=site.site_id,
        index_coverage_ok=index_ok,
        impressions_rising=impressions_ok,
        refresh_on_time=refresh_ok,
        error_rate_ok=error_ok,
        score=score,
    )


# ---------------------------------------------------------------------------
# Niche saturation detection
# ---------------------------------------------------------------------------


def detect_niche_saturation(site: SiteMetrics) -> bool:
    """Check if a site's niche is saturated.

    From the spec — flag as saturated if:
    - new pages take >90 days to rank
    - impressions plateau for 60+ days
    - CTR drops despite refresh attempts

    When saturated: stop publishing, shift capacity elsewhere.
    """
    slow_ranking = site.avg_days_to_rank > SATURATION_RANKING_DAYS
    flat_impressions = (
        site.impressions_trend <= 0 and site.age_days > SATURATION_PLATEAU_DAYS
    )
    declining_ctr = site.ctr_trend < 0

    # Saturated if 2+ signals present
    signals = sum([slow_ranking, flat_impressions, declining_ctr])
    return signals >= 2


# ---------------------------------------------------------------------------
# Kill-fast policy
# ---------------------------------------------------------------------------


def check_kill_policy(site: SiteMetrics) -> bool:
    """Check if a site triggers the kill-fast policy.

    From the spec — pause publishing if:
    - zero indexing after 45 days
    - zero impressions after 60 days
    - no ranking movement after 90 days
    """
    if site.age_days >= KILL_NO_INDEX_DAYS and site.indexed_pages == 0:
        return True
    if site.age_days >= KILL_NO_IMPRESSIONS_DAYS and site.monthly_impressions == 0:
        return True
    if (
        site.age_days >= KILL_NO_RANKING_DAYS
        and site.monthly_clicks == 0
        and site.monthly_impressions == 0
    ):
        return True
    return False


# ---------------------------------------------------------------------------
# Per-site scaling decision
# ---------------------------------------------------------------------------


def decide_site_scaling(site: SiteMetrics) -> SiteScalingDecision:
    """Generate a scaling decision for a single site.

    Evaluates health, saturation, kill policy, and maturity to
    produce a verdict with a safe publishing rate.
    """
    health = compute_domain_health(site)
    maturity = classify_site_maturity(site)
    _, max_rate = get_safe_publishing_rate(maturity)
    reasons: List[str] = []

    # Kill-fast check (highest priority)
    if check_kill_policy(site):
        reasons.append(
            f"Kill-fast triggered: {site.age_days}d old, "
            f"{site.indexed_pages} indexed, {site.monthly_impressions} impressions"
        )
        return SiteScalingDecision(
            site_id=site.site_id,
            verdict=SiteVerdict.KILL,
            maturity=maturity,
            max_pages_per_week=0,
            health=health,
            reasons=reasons,
        )

    # Niche saturation check
    if detect_niche_saturation(site):
        reasons.append(
            f"Niche saturated: avg {site.avg_days_to_rank:.0f}d to rank, "
            f"impressions trend {site.impressions_trend:+.2f}, "
            f"CTR trend {site.ctr_trend:+.2f}"
        )
        return SiteScalingDecision(
            site_id=site.site_id,
            verdict=SiteVerdict.SATURATED,
            maturity=maturity,
            max_pages_per_week=0,
            health=health,
            reasons=reasons,
        )

    # Health check
    if not health.is_healthy:
        issues = []
        if not health.index_coverage_ok:
            issues.append(
                f"index coverage {site.index_coverage:.0f}% (need >{HEALTH_INDEX_COVERAGE_MIN}%)"
            )
        if not health.impressions_rising:
            issues.append("impressions not rising")
        if not health.refresh_on_time:
            issues.append(f"{site.refresh_backlog} pages overdue for refresh")
        if not health.error_rate_ok:
            issues.append(
                f"error rate {site.error_rate:.1f}% (need <{HEALTH_ERROR_RATE_MAX}%)"
            )

        reasons.append(f"Health issues: {'; '.join(issues)}")
        return SiteScalingDecision(
            site_id=site.site_id,
            verdict=SiteVerdict.REFRESH_ONLY,
            maturity=maturity,
            max_pages_per_week=0,
            health=health,
            reasons=reasons,
        )

    # Manual penalty check
    if site.has_manual_penalty:
        reasons.append("Manual penalty active — hold all new content")
        return SiteScalingDecision(
            site_id=site.site_id,
            verdict=SiteVerdict.HOLD,
            maturity=maturity,
            max_pages_per_week=0,
            health=health,
            reasons=reasons,
        )

    # All clear — expand
    reasons.append(
        f"Healthy {maturity.value} site: {site.total_pages} pages, "
        f"${site.monthly_revenue:.0f}/mo revenue, safe rate {max_rate}/week"
    )
    return SiteScalingDecision(
        site_id=site.site_id,
        verdict=SiteVerdict.EXPAND,
        maturity=maturity,
        max_pages_per_week=max_rate,
        health=health,
        reasons=reasons,
    )


# ---------------------------------------------------------------------------
# Expansion trigger check
# ---------------------------------------------------------------------------


def check_expansion_triggers(
    sites: Sequence[SiteMetrics],
) -> ExpansionTriggerCheck:
    """Check the 5 portfolio expansion triggers.

    From the spec — ANY TWO must be met:
    1. Average monthly revenue per site increasing
    2. Stable indexing across last 30 days
    3. No manual penalties
    4. Content refresh backlog under control
    5. Infrastructure costs < 20% of revenue

    Parameters
    ----------
    sites:
        All sites in the portfolio.

    Returns
    -------
    ExpansionTriggerCheck
        Trigger assessment with per-condition status.
    """
    if not sites:
        return ExpansionTriggerCheck()

    total_revenue = sum(s.monthly_revenue for s in sites)
    total_cost = sum(s.monthly_cost for s in sites)
    avg_revenue = total_revenue / len(sites)

    # 1. Revenue increasing: avg revenue > 0 and most sites profitable
    profitable_ratio = sum(1 for s in sites if s.is_profitable) / len(sites)
    revenue_increasing = avg_revenue > 0 and profitable_ratio >= 0.5

    # 2. Stable indexing: average index coverage > 70%
    avg_coverage = sum(s.index_coverage for s in sites) / len(sites)
    indexing_stable = avg_coverage >= HEALTH_INDEX_COVERAGE_MIN

    # 3. No manual penalties
    no_penalties = not any(s.has_manual_penalty for s in sites)

    # 4. Refresh backlog under control: total backlog < total pages * 10%
    total_backlog = sum(s.refresh_backlog for s in sites)
    total_pages = sum(s.total_pages for s in sites)
    refresh_ok = total_backlog <= max(total_pages * 0.10, 1)

    # 5. Infrastructure costs < 20% of revenue
    if total_revenue > 0:
        infra_ratio = total_cost / total_revenue
        infra_safe = infra_ratio < MAX_INFRA_COST_RATIO
    else:
        infra_safe = False

    return ExpansionTriggerCheck(
        revenue_increasing=revenue_increasing,
        indexing_stable=indexing_stable,
        no_penalties=no_penalties,
        refresh_under_control=refresh_ok,
        infra_costs_safe=infra_safe,
    )


# ---------------------------------------------------------------------------
# Capacity allocation
# ---------------------------------------------------------------------------


def compute_capacity_allocation(
    total_capacity: float = 100.0,
) -> CapacityAllocation:
    """Compute the 60/30/10 capacity allocation.

    From the spec::

        60% compute → refresh + optimization of existing winners
        30% compute → expansion of validated clusters
        10% compute → experimental niches / trend tests
    """
    return CapacityAllocation(
        total_capacity=total_capacity,
        refresh_capacity=round(total_capacity * CAPACITY_REFRESH_PCT / 100, 1),
        expansion_capacity=round(total_capacity * CAPACITY_EXPANSION_PCT / 100, 1),
        experimental_capacity=round(
            total_capacity * CAPACITY_EXPERIMENTAL_PCT / 100, 1
        ),
    )


# ---------------------------------------------------------------------------
# Validation stage check
# ---------------------------------------------------------------------------


def check_validation_stage(sites: Sequence[SiteMetrics]) -> bool:
    """Check if any site meets the Stage 1 validation criteria.

    From the spec — required signals:
    - at least 20 indexed pages
    - sustained impressions growth for 30+ days
    - at least 1 converting money page
    - positive earnings trend (even small)
    """
    for site in sites:
        pages_ok = site.indexed_pages >= VALIDATION_MIN_INDEXED_PAGES
        impressions_ok = (
            site.impressions_trend > 0
            and site.age_days >= VALIDATION_MIN_IMPRESSION_DAYS
        )
        converting_ok = site.converting_pages >= VALIDATION_MIN_CONVERTING_PAGES
        revenue_ok = site.monthly_revenue > 0

        if pages_ok and impressions_ok and converting_ok and revenue_ok:
            return True

    return False


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


def build_scaling_plan(
    sites: Sequence[SiteMetrics],
    *,
    total_capacity: float = 100.0,
    weeks_since_last_launch: int = 0,
) -> PortfolioScalingPlan:
    """Build a complete portfolio scaling plan.

    1. Determine current scaling stage
    2. Generate per-site scaling decisions
    3. Check expansion triggers
    4. Detect saturated niches
    5. Compute capacity allocation
    6. Determine if a new site launch is safe

    Parameters
    ----------
    sites:
        All sites in the portfolio.
    total_capacity:
        Total available compute capacity (abstract units).
    weeks_since_last_launch:
        Weeks since the last new site was launched.

    Returns
    -------
    PortfolioScalingPlan
        Complete scaling plan with per-site decisions and portfolio metrics.
    """
    stage = determine_scaling_stage(sites)
    site_decisions = [decide_site_scaling(s) for s in sites]
    expansion_check = check_expansion_triggers(sites)
    capacity = compute_capacity_allocation(total_capacity)

    # Detect saturated niches
    saturated_niches = list(
        {s.niche for s in sites if detect_niche_saturation(s) and s.niche}
    )

    # Determine if new site launch is safe
    can_launch = False
    next_launch_weeks = MAX_WEEKS_BETWEEN_LAUNCHES

    if stage == ScalingStage.VALIDATION:
        # Can't launch more until validation passes
        can_launch = False
        if check_validation_stage(sites):
            can_launch = True
            next_launch_weeks = 0
    elif stage == ScalingStage.REPLICATION:
        # Can launch if first site validated and enough time passed
        can_launch = (
            weeks_since_last_launch >= MIN_WEEKS_BETWEEN_LAUNCHES
            and check_validation_stage(sites)
        )
        if can_launch:
            next_launch_weeks = 0
        else:
            next_launch_weeks = max(
                MIN_WEEKS_BETWEEN_LAUNCHES - weeks_since_last_launch, 0
            )
    elif stage in (ScalingStage.PORTFOLIO, ScalingStage.EMPIRE):
        # Need expansion triggers + staggered cadence
        can_launch = (
            expansion_check.can_expand
            and weeks_since_last_launch >= MIN_WEEKS_BETWEEN_LAUNCHES
        )
        if can_launch:
            next_launch_weeks = 0
        elif expansion_check.can_expand:
            next_launch_weeks = max(
                MIN_WEEKS_BETWEEN_LAUNCHES - weeks_since_last_launch, 0
            )

    # Portfolio-wide ROI
    total_revenue = sum(s.monthly_revenue for s in sites)
    total_cost = sum(s.monthly_cost for s in sites)
    portfolio_roi = round(total_revenue / total_cost, 2) if total_cost > 0 else 0.0

    # 50-site automation threshold
    needs_automation = len(sites) >= AUTOMATION_THRESHOLD_SITES

    plan = PortfolioScalingPlan(
        stage=stage,
        site_decisions=site_decisions,
        expansion_check=expansion_check,
        can_launch_new_site=can_launch,
        next_launch_weeks=next_launch_weeks,
        capacity=capacity,
        saturated_niches=saturated_niches,
        needs_automation_upgrade=needs_automation,
        portfolio_roi=portfolio_roi,
    )

    log_event(
        logger,
        "empire_scaling.plan.built",
        stage=stage.name,
        total_sites=len(sites),
        healthy=plan.healthy_sites,
        kill_candidates=plan.kill_candidates,
        can_launch=can_launch,
        saturated_niches=len(saturated_niches),
        portfolio_roi=portfolio_roi,
    )

    return plan
