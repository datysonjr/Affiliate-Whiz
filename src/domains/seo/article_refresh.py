"""
domains.seo.article_refresh
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

OpenClaw Article Refresh Engine.

Automatically evaluates existing articles for refresh opportunities and
generates structured refresh plans that boost rankings without requiring
entirely new content.

Implements the strategy from
``docs/seo/ARTICLE_REFRESH_ENGINE.md``.

The engine:
    1. Accepts article status data (age, position, impressions, etc.)
    2. Checks three refresh trigger types (age, ranking plateau, product change)
    3. Determines the refresh cycle based on page category
    4. Generates a prioritised refresh plan with specific actions
    5. Returns a sorted refresh queue for the publishing pipeline

Design references:
    - docs/seo/ARTICLE_REFRESH_ENGINE.md
    - src/domains/seo/validator.py  (SEO quality enforcement)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, IntEnum, unique
from typing import Any, Dict, List, Optional, Sequence

from src.core.logger import get_logger, log_event

logger = get_logger("domains.seo.article_refresh")


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


@unique
class RefreshTrigger(str, Enum):
    """Reasons an article should be refreshed."""

    AGE = "age"  # article_age > refresh cycle
    RANKING_PLATEAU = "ranking_plateau"  # stuck pos 10-30, high impressions
    PRODUCT_CHANGE = "product_change"  # product discontinued / new model


@unique
class PageCategory(str, Enum):
    """Article category that determines refresh frequency."""

    MONEY = "money"  # core buying guides / reviews
    SUPPORT = "support"  # support / comparison articles
    INFORMATIONAL = "informational"  # informational / educational


@unique
class RefreshAction(str, Enum):
    """Specific actions to perform during a refresh."""

    UPDATE_INTRO = "update_intro"
    EXPAND_PRODUCTS = "expand_products"
    EXPAND_FAQ = "expand_faq"
    ADD_INTERNAL_LINKS = "add_internal_links"
    UPDATE_TIMESTAMP = "update_timestamp"


@unique
class RefreshUrgency(IntEnum):
    """Refresh urgency level. Lower = more urgent."""

    CRITICAL = 1  # Product change — immediate
    HIGH = 2  # Ranking plateau — strong opportunity
    NORMAL = 3  # Age-based — routine maintenance
    LOW = 4  # Within cycle but close to threshold


# ---------------------------------------------------------------------------
# Constants — refresh cycles (days) from the spec
# ---------------------------------------------------------------------------

MONEY_PAGE_REFRESH_DAYS = 45
SUPPORT_PAGE_REFRESH_DAYS = 90
INFORMATIONAL_PAGE_REFRESH_DAYS = 120

# Ranking plateau detection
PLATEAU_POSITION_MIN = 10
PLATEAU_POSITION_MAX = 30
PLATEAU_CTR_THRESHOLD = 0.02  # impressions high but CTR < 2%

# Age trigger range from spec: 45-60 days for evaluation
AGE_EVALUATION_DAYS = 45


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class ArticleStatus:
    """Current status of a published article.

    Attributes
    ----------
    url:
        Article URL or slug.
    title:
        Article title.
    page_category:
        Money / support / informational classification.
    published_days_ago:
        Days since original publication.
    last_refreshed_days_ago:
        Days since last refresh (0 if never refreshed).
    current_position:
        Average SERP position (0 if not ranking).
    impressions:
        Monthly search impressions.
    clicks:
        Monthly clicks from search.
    has_product_changes:
        Whether the referenced products have changed
        (discontinued, new model, price change).
    word_count:
        Current article word count.
    internal_link_count:
        Current number of internal links.
    metadata:
        Additional tracking data.
    """

    url: str
    title: str = ""
    page_category: PageCategory = PageCategory.INFORMATIONAL
    published_days_ago: int = 0
    last_refreshed_days_ago: int = 0
    current_position: float = 0.0
    impressions: int = 0
    clicks: int = 0
    has_product_changes: bool = False
    word_count: int = 0
    internal_link_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def ctr(self) -> float:
        """Computed click-through rate."""
        if self.impressions <= 0:
            return 0.0
        return self.clicks / self.impressions

    @property
    def effective_age_days(self) -> int:
        """Days since last refresh, or since publication if never refreshed."""
        if self.last_refreshed_days_ago > 0:
            return self.last_refreshed_days_ago
        return self.published_days_ago


@dataclass
class RefreshPlan:
    """A structured plan for refreshing a single article.

    Attributes
    ----------
    article:
        The article being refreshed.
    triggers:
        Which refresh triggers were activated.
    actions:
        Specific refresh actions to perform.
    urgency:
        How urgently the refresh should happen.
    priority_score:
        Numeric priority (0-100, higher = refresh sooner).
    notes:
        Human-readable notes about the refresh plan.
    """

    article: ArticleStatus
    triggers: List[RefreshTrigger] = field(default_factory=list)
    actions: List[RefreshAction] = field(default_factory=list)
    urgency: RefreshUrgency = RefreshUrgency.NORMAL
    priority_score: float = 0.0
    notes: List[str] = field(default_factory=list)

    @property
    def trigger_count(self) -> int:
        return len(self.triggers)

    @property
    def is_urgent(self) -> bool:
        """True if urgency is CRITICAL or HIGH."""
        return self.urgency <= RefreshUrgency.HIGH


# ---------------------------------------------------------------------------
# Refresh cycle lookup
# ---------------------------------------------------------------------------

_REFRESH_CYCLES: dict[PageCategory, int] = {
    PageCategory.MONEY: MONEY_PAGE_REFRESH_DAYS,
    PageCategory.SUPPORT: SUPPORT_PAGE_REFRESH_DAYS,
    PageCategory.INFORMATIONAL: INFORMATIONAL_PAGE_REFRESH_DAYS,
}


def get_refresh_cycle(category: PageCategory) -> int:
    """Return the refresh cycle in days for a page category.

    From the spec::

        money pages         → every 30-45 days
        support pages       → every 90 days
        informational pages → every 120+ days
    """
    return _REFRESH_CYCLES.get(category, INFORMATIONAL_PAGE_REFRESH_DAYS)


# ---------------------------------------------------------------------------
# Trigger detection
# ---------------------------------------------------------------------------


def check_age_trigger(article: ArticleStatus) -> Optional[RefreshTrigger]:
    """Check if the article exceeds its refresh cycle.

    From the spec — if article_age > 45-60 days, queue for refresh.
    Uses the page-category-specific cycle.
    """
    cycle = get_refresh_cycle(article.page_category)
    if article.effective_age_days >= cycle:
        return RefreshTrigger.AGE
    return None


def check_ranking_plateau(article: ArticleStatus) -> Optional[RefreshTrigger]:
    """Check if the article is stuck in a ranking plateau.

    From the spec — if article is stuck between positions 10-30
    with impressions high but clicks low, Google is testing but
    unconvinced. Perfect refresh candidate.
    """
    if article.current_position <= 0:
        return None

    in_plateau_range = (
        PLATEAU_POSITION_MIN <= article.current_position <= PLATEAU_POSITION_MAX
    )
    has_impressions = article.impressions > 0
    low_ctr = article.ctr < PLATEAU_CTR_THRESHOLD

    if in_plateau_range and has_impressions and low_ctr:
        return RefreshTrigger.RANKING_PLATEAU
    return None


def check_product_change(article: ArticleStatus) -> Optional[RefreshTrigger]:
    """Check if referenced products have changed.

    From the spec — if product discontinued, new model released,
    or price tiers changed, immediate refresh required.
    """
    if article.has_product_changes:
        return RefreshTrigger.PRODUCT_CHANGE
    return None


# ---------------------------------------------------------------------------
# Action determination
# ---------------------------------------------------------------------------


def determine_refresh_actions(
    article: ArticleStatus,
    triggers: Sequence[RefreshTrigger],
) -> List[RefreshAction]:
    """Determine which refresh actions to perform.

    From the spec — refresh must NOT rewrite entire article. Instead:
    update intro, expand product sections, expand FAQ, add internal
    links, update timestamp.
    """
    actions: List[RefreshAction] = []

    # Always update intro and timestamp on any refresh
    actions.append(RefreshAction.UPDATE_INTRO)
    actions.append(RefreshAction.UPDATE_TIMESTAMP)

    # Product changes require expanding product sections
    if RefreshTrigger.PRODUCT_CHANGE in triggers:
        actions.append(RefreshAction.EXPAND_PRODUCTS)

    # Ranking plateau benefits from FAQ expansion and linking
    if RefreshTrigger.RANKING_PLATEAU in triggers:
        actions.append(RefreshAction.EXPAND_FAQ)
        if article.internal_link_count < 5:
            actions.append(RefreshAction.ADD_INTERNAL_LINKS)

    # Age-based refresh should expand FAQ and add links
    if RefreshTrigger.AGE in triggers:
        if RefreshAction.EXPAND_FAQ not in actions:
            actions.append(RefreshAction.EXPAND_FAQ)
        if (
            article.internal_link_count < 5
            and RefreshAction.ADD_INTERNAL_LINKS not in actions
        ):
            actions.append(RefreshAction.ADD_INTERNAL_LINKS)

    return actions


# ---------------------------------------------------------------------------
# Priority scoring
# ---------------------------------------------------------------------------


def compute_refresh_priority(
    article: ArticleStatus,
    triggers: Sequence[RefreshTrigger],
) -> tuple[float, RefreshUrgency]:
    """Compute refresh priority score and urgency.

    Factors:
        - Trigger severity (product change > plateau > age)
        - Page category (money pages > support > informational)
        - How overdue the refresh is
        - Current ranking position opportunity

    Returns
    -------
    tuple[float, RefreshUrgency]
        (priority_score 0-100, urgency level)
    """
    score = 0.0
    urgency = RefreshUrgency.LOW

    # Trigger severity scoring
    if RefreshTrigger.PRODUCT_CHANGE in triggers:
        score += 40
        urgency = RefreshUrgency.CRITICAL
    if RefreshTrigger.RANKING_PLATEAU in triggers:
        score += 30
        if urgency > RefreshUrgency.HIGH:
            urgency = RefreshUrgency.HIGH
    if RefreshTrigger.AGE in triggers:
        score += 15
        if urgency > RefreshUrgency.NORMAL:
            urgency = RefreshUrgency.NORMAL

    # Page category bonus
    category_bonus = {
        PageCategory.MONEY: 20,
        PageCategory.SUPPORT: 10,
        PageCategory.INFORMATIONAL: 5,
    }
    score += category_bonus.get(article.page_category, 5)

    # Overdue factor: how far past the refresh cycle
    cycle = get_refresh_cycle(article.page_category)
    if article.effective_age_days > cycle:
        overdue_ratio = min((article.effective_age_days - cycle) / cycle, 1.0)
        score += overdue_ratio * 15

    # Position opportunity: pages 10-20 have highest potential
    if 10 <= article.current_position <= 20:
        score += 10
    elif 20 < article.current_position <= 30:
        score += 5

    return round(min(score, 100), 1), urgency


# ---------------------------------------------------------------------------
# Single article analysis
# ---------------------------------------------------------------------------


def plan_refresh(article: ArticleStatus) -> Optional[RefreshPlan]:
    """Evaluate a single article and generate a refresh plan if needed.

    Parameters
    ----------
    article:
        Current status of the article.

    Returns
    -------
    RefreshPlan or None
        A refresh plan if any triggers are active, None otherwise.
    """
    triggers: List[RefreshTrigger] = []
    notes: List[str] = []

    age_trigger = check_age_trigger(article)
    if age_trigger:
        triggers.append(age_trigger)
        cycle = get_refresh_cycle(article.page_category)
        notes.append(
            f"Content age ({article.effective_age_days}d) exceeds {cycle}d cycle"
        )

    plateau_trigger = check_ranking_plateau(article)
    if plateau_trigger:
        triggers.append(plateau_trigger)
        notes.append(
            f"Ranking plateau at position {article.current_position} "
            f"with {article.impressions} impressions and {article.ctr:.1%} CTR"
        )

    product_trigger = check_product_change(article)
    if product_trigger:
        triggers.append(product_trigger)
        notes.append("Referenced products have changed — immediate refresh needed")

    if not triggers:
        return None

    actions = determine_refresh_actions(article, triggers)
    priority_score, urgency = compute_refresh_priority(article, triggers)

    plan = RefreshPlan(
        article=article,
        triggers=triggers,
        actions=actions,
        urgency=urgency,
        priority_score=priority_score,
        notes=notes,
    )

    log_event(
        logger,
        "article_refresh.plan.created",
        url=article.url,
        triggers=len(triggers),
        actions=len(actions),
        urgency=urgency.name,
        priority=priority_score,
    )

    return plan


# ---------------------------------------------------------------------------
# Batch pipeline
# ---------------------------------------------------------------------------


def evaluate_refresh_queue(
    articles: Sequence[ArticleStatus],
) -> List[RefreshPlan]:
    """Evaluate all articles and return a prioritised refresh queue.

    1. Check each article for refresh triggers
    2. Generate refresh plans for triggered articles
    3. Sort by priority score (highest first)

    Parameters
    ----------
    articles:
        All published articles to evaluate.

    Returns
    -------
    list[RefreshPlan]
        Refresh plans sorted by priority (highest first).
        Only articles needing refresh are included.
    """
    plans: List[RefreshPlan] = []

    for article in articles:
        plan = plan_refresh(article)
        if plan is not None:
            plans.append(plan)

    plans.sort(key=lambda p: p.priority_score, reverse=True)

    log_event(
        logger,
        "article_refresh.queue.evaluated",
        total_articles=len(articles),
        needs_refresh=len(plans),
        urgent_count=sum(1 for p in plans if p.is_urgent),
    )

    return plans
