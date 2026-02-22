"""
domains.seo.authority_snowball
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

OpenClaw Site Authority Snowball Model.

Models the 4-stage growth trajectory of an affiliate site and
determines safe publishing speeds based on real indexing and ranking
signals. Prevents premature scaling that triggers ranking suppression.

Implements the strategy from
``docs/seo/SITE_AUTHORITY_SNOWBALL_MODEL.md``.

The model:
    1. Classifies the site into one of 4 growth stages
    2. Checks snowball signals (indexing speed, impressions, long-tail)
    3. Computes safe publishing speed for the current stage
    4. Returns a publishing plan with page type recommendations

Design references:
    - docs/seo/SITE_AUTHORITY_SNOWBALL_MODEL.md
    - src/domains/seo/query_capture.py  (AuthorityCluster)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum, Enum, unique
from typing import Any, Dict, List, Optional, Sequence

from src.core.logger import get_logger, log_event

logger = get_logger("domains.seo.authority_snowball")


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

@unique
class GrowthStage(IntEnum):
    """The 4 site growth stages from the spec.

    Each stage has different goals, strategies, and safe publishing speeds.
    """

    SEED = 1         # 0-20 pages: prove topical relevance
    TRUST = 2        # 20-80 pages: build topical dominance
    EXPANSION = 3    # 80-200 pages: own the topic ecosystem
    AUTHORITY = 4    # 200-500+ pages: become default reference


@unique
class PageType(str, Enum):
    """Content types appropriate for each growth stage."""

    CORE_BUYER_GUIDE = "core_buyer_guide"
    SUPPORT_GUIDE = "support_guide"
    INFORMATIONAL = "informational"
    SCENARIO_GUIDE = "scenario_guide"
    COMPARISON = "comparison"
    PRICE_TIER_GUIDE = "price_tier_guide"
    USE_CASE_GUIDE = "use_case_guide"
    HUB_PAGE = "hub_page"
    ADJACENT_CLUSTER = "adjacent_cluster"


# ---------------------------------------------------------------------------
# Constants — stage boundaries and publishing speeds
# ---------------------------------------------------------------------------

SEED_MAX_PAGES = 20
TRUST_MAX_PAGES = 80
EXPANSION_MAX_PAGES = 200
# Authority = 200+

# Publishing speed (pages per week) from the spec:
# 3/week → 5/week → 7/week → scale gradually
_STAGE_PUBLISHING_SPEED: dict[GrowthStage, int] = {
    GrowthStage.SEED: 3,
    GrowthStage.TRUST: 5,
    GrowthStage.EXPANSION: 7,
    GrowthStage.AUTHORITY: 10,
}

# Snowball signal thresholds
INDEXING_HOURS_THRESHOLD = 72       # pages should index within 72h
IMPRESSIONS_TREND_THRESHOLD = 0.0   # must be non-negative (rising)
LONG_TAIL_RANKING_THRESHOLD = 5     # need some long-tail rankings


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class SnowballSignals:
    """Real-time signals that indicate whether scaling is safe.

    From the spec — scale ONLY when:
    - pages indexing within 48-72h
    - impressions rising steadily
    - internal pages ranking for long-tail queries

    Attributes
    ----------
    avg_indexing_hours:
        Average hours for new pages to appear in search index.
    impressions_trend:
        Impressions growth rate (-1.0 to +1.0). Positive = rising.
    long_tail_rankings:
        Number of pages ranking for long-tail queries.
    """

    avg_indexing_hours: float = 168.0   # default: 1 week (not fast)
    impressions_trend: float = 0.0      # flat by default
    long_tail_rankings: int = 0


@dataclass
class SiteSnapshot:
    """Current state of the affiliate site.

    Attributes
    ----------
    total_pages:
        Total number of published pages.
    niche:
        Primary niche the site covers.
    signals:
        Current snowball signals.
    current_stage:
        Auto-detected growth stage (computed on creation).
    metadata:
        Additional site-level data.
    """

    total_pages: int = 0
    niche: str = ""
    signals: SnowballSignals = field(default_factory=SnowballSignals)
    current_stage: GrowthStage = GrowthStage.SEED
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.current_stage = determine_growth_stage(self.total_pages)


@dataclass
class PublishingPlan:
    """Recommended publishing plan based on growth stage and signals.

    Attributes
    ----------
    stage:
        Current growth stage.
    recommended_pages_per_week:
        Safe number of pages to publish per week.
    page_types:
        Recommended content types to focus on.
    safe_to_scale:
        Whether all snowball signals support scaling.
    scaling_blockers:
        Reasons why scaling is not safe (if any).
    stage_goal:
        Human-readable description of the current stage's goal.
    next_stage_threshold:
        Number of pages needed to reach the next stage.
    """

    stage: GrowthStage = GrowthStage.SEED
    recommended_pages_per_week: int = 3
    page_types: List[PageType] = field(default_factory=list)
    safe_to_scale: bool = False
    scaling_blockers: List[str] = field(default_factory=list)
    stage_goal: str = ""
    next_stage_threshold: int = 0

    @property
    def is_blocked(self) -> bool:
        """True if there are scaling blockers preventing normal speed."""
        return len(self.scaling_blockers) > 0


# ---------------------------------------------------------------------------
# Stage determination
# ---------------------------------------------------------------------------

_STAGE_GOALS: dict[GrowthStage, str] = {
    GrowthStage.SEED: "Prove topical relevance with depth over volume",
    GrowthStage.TRUST: "Build topical dominance within the same cluster",
    GrowthStage.EXPANSION: "Own the entire topic ecosystem",
    GrowthStage.AUTHORITY: "Become the default reference site",
}

_STAGE_THRESHOLDS: dict[GrowthStage, int] = {
    GrowthStage.SEED: TRUST_MAX_PAGES,
    GrowthStage.TRUST: EXPANSION_MAX_PAGES,
    GrowthStage.EXPANSION: 500,
    GrowthStage.AUTHORITY: 0,  # no next stage
}


def determine_growth_stage(total_pages: int) -> GrowthStage:
    """Classify the site into a growth stage based on total page count.

    From the spec::

        Stage 1 — Seed Phase (0-20 pages)
        Stage 2 — Trust Phase (20-80 pages)
        Stage 3 — Expansion Phase (80-200 pages)
        Stage 4 — Authority Phase (200-500+ pages)
    """
    if total_pages <= SEED_MAX_PAGES:
        return GrowthStage.SEED
    if total_pages <= TRUST_MAX_PAGES:
        return GrowthStage.TRUST
    if total_pages <= EXPANSION_MAX_PAGES:
        return GrowthStage.EXPANSION
    return GrowthStage.AUTHORITY


# ---------------------------------------------------------------------------
# Snowball signal checks
# ---------------------------------------------------------------------------

def check_snowball_signals(signals: SnowballSignals) -> tuple[bool, List[str]]:
    """Check if all snowball signals support safe scaling.

    From the spec — scale ONLY when:
    - pages indexing within 48-72h
    - impressions rising steadily
    - internal pages ranking for long-tail queries

    If none present: do NOT scale content. Fix cluster structure first.

    Returns
    -------
    tuple[bool, list[str]]
        (safe_to_scale, list of blockers). Empty blockers = safe.
    """
    blockers: List[str] = []

    if signals.avg_indexing_hours > INDEXING_HOURS_THRESHOLD:
        blockers.append(
            f"Slow indexing: {signals.avg_indexing_hours:.0f}h avg "
            f"(need <{INDEXING_HOURS_THRESHOLD}h)"
        )

    if signals.impressions_trend <= IMPRESSIONS_TREND_THRESHOLD:
        blockers.append(
            f"Impressions not rising: trend={signals.impressions_trend:+.2f} "
            "(need positive growth)"
        )

    if signals.long_tail_rankings < LONG_TAIL_RANKING_THRESHOLD:
        blockers.append(
            f"Insufficient long-tail rankings: {signals.long_tail_rankings} "
            f"(need >={LONG_TAIL_RANKING_THRESHOLD})"
        )

    return len(blockers) == 0, blockers


# ---------------------------------------------------------------------------
# Page type recommendations per stage
# ---------------------------------------------------------------------------

_STAGE_PAGE_TYPES: dict[GrowthStage, list[PageType]] = {
    GrowthStage.SEED: [
        PageType.CORE_BUYER_GUIDE,
        PageType.SUPPORT_GUIDE,
        PageType.INFORMATIONAL,
    ],
    GrowthStage.TRUST: [
        PageType.SUPPORT_GUIDE,
        PageType.SCENARIO_GUIDE,
        PageType.COMPARISON,
        PageType.INFORMATIONAL,
    ],
    GrowthStage.EXPANSION: [
        PageType.PRICE_TIER_GUIDE,
        PageType.USE_CASE_GUIDE,
        PageType.COMPARISON,
        PageType.INFORMATIONAL,
        PageType.SUPPORT_GUIDE,
    ],
    GrowthStage.AUTHORITY: [
        PageType.ADJACENT_CLUSTER,
        PageType.HUB_PAGE,
        PageType.COMPARISON,
        PageType.PRICE_TIER_GUIDE,
        PageType.USE_CASE_GUIDE,
    ],
}


# ---------------------------------------------------------------------------
# Publishing speed computation
# ---------------------------------------------------------------------------

def compute_publishing_speed(
    stage: GrowthStage,
    safe_to_scale: bool,
) -> int:
    """Compute the recommended publishing speed for the current stage.

    From the spec — never spike to 10 articles day one. Instead:
    3/week → 5/week → 7/week → scale gradually.

    If snowball signals are not present, reduce speed to prevent
    ranking suppression.

    Parameters
    ----------
    stage:
        Current growth stage.
    safe_to_scale:
        Whether snowball signals support normal speed.

    Returns
    -------
    int
        Recommended pages per week.
    """
    base_speed = _STAGE_PUBLISHING_SPEED.get(stage, 3)

    if not safe_to_scale:
        # Reduce to minimum safe speed when signals are missing
        return max(base_speed // 2, 1)

    return base_speed


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def build_publishing_plan(snapshot: SiteSnapshot) -> PublishingPlan:
    """Generate a publishing plan based on the site's current state.

    1. Determine growth stage from total pages
    2. Check snowball signals for scaling safety
    3. Compute safe publishing speed
    4. Recommend page types for the current stage
    5. Identify the next stage threshold

    Parameters
    ----------
    snapshot:
        Current state of the affiliate site.

    Returns
    -------
    PublishingPlan
        Complete publishing recommendation.
    """
    stage = snapshot.current_stage
    safe_to_scale, blockers = check_snowball_signals(snapshot.signals)
    speed = compute_publishing_speed(stage, safe_to_scale)
    page_types = _STAGE_PAGE_TYPES.get(stage, [PageType.INFORMATIONAL])
    goal = _STAGE_GOALS.get(stage, "")
    next_threshold = _STAGE_THRESHOLDS.get(stage, 0)

    plan = PublishingPlan(
        stage=stage,
        recommended_pages_per_week=speed,
        page_types=page_types,
        safe_to_scale=safe_to_scale,
        scaling_blockers=blockers,
        stage_goal=goal,
        next_stage_threshold=next_threshold,
    )

    log_event(
        logger,
        "authority_snowball.plan.built",
        niche=snapshot.niche,
        total_pages=snapshot.total_pages,
        stage=stage.name,
        speed=speed,
        safe_to_scale=safe_to_scale,
        blockers=len(blockers),
    )

    return plan


def evaluate_portfolio(
    snapshots: Sequence[SiteSnapshot],
) -> List[PublishingPlan]:
    """Generate publishing plans for all sites in a portfolio.

    Parameters
    ----------
    snapshots:
        Current state of each site.

    Returns
    -------
    list[PublishingPlan]
        Publishing plans sorted by stage (earliest stage first,
        as they need the most careful attention).
    """
    plans = [build_publishing_plan(snap) for snap in snapshots]
    plans.sort(key=lambda p: p.stage)

    log_event(
        logger,
        "authority_snowball.portfolio.evaluated",
        sites=len(snapshots),
        blocked_count=sum(1 for p in plans if p.is_blocked),
    )

    return plans
