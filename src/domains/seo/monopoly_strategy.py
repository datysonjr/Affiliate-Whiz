"""
domains.seo.monopoly_strategy
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

OpenClaw Monopoly Site Strategy.

Models a multi-site portfolio approach for dominating entire niches by
operating coordinated sites that capture different buyer journey stages
and occupy multiple SERP positions.

Implements the strategy from
``docs/seo/OPENCLAW_MONOPOLY_SITE_STRATEGY.md``.

The strategy:
    1. Defines the 4-site domination model per niche
    2. Assigns content focus areas to each site type
    3. Plans staggered launches (0/3/6/9 months)
    4. Maps the buyer journey stages to site types
    5. Generates a SERP occupation plan
    6. Enforces safe interlinking and content segmentation rules

Design references:
    - docs/seo/OPENCLAW_MONOPOLY_SITE_STRATEGY.md
    - src/domains/seo/authority_snowball.py  (GrowthStage, PublishingPlan)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum, Enum, unique
from typing import Any, Dict, List, Optional, Sequence

from src.core.logger import get_logger, log_event

logger = get_logger("domains.seo.monopoly_strategy")


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

@unique
class SiteType(IntEnum):
    """The 4 site types from the Monopoly domination model.

    Order reflects recommended launch sequence.
    """

    AUTHORITY = 1       # Primary ranking engine
    REVIEW = 2          # High-conversion buyer capture
    SPECIALIST = 3      # Sub-niche authority capture
    TREND = 4           # Early emerging traffic capture


@unique
class BuyerStage(IntEnum):
    """Stages of the buyer journey that sites map to."""

    AWARENESS = 1       # learns about product category
    COMPARISON = 2      # compares options
    RESEARCH = 3        # researches specific model
    DECISION = 4        # decides purchase


@unique
class ContentFocus(str, Enum):
    """Content focus area assigned to each site type."""

    BROAD_BUYING_GUIDES = "broad_buying_guides"
    DEEP_PRODUCT_COMPARISONS = "deep_product_comparisons"
    NARROW_USE_CASE = "narrow_use_case"
    EMERGING_COVERAGE = "emerging_coverage"


@unique
class InterlinkSafety(str, Enum):
    """Safety classification of cross-site links."""

    SAFE = "safe"               # natural contextual citations
    CAUTION = "caution"         # occasional reference links
    FORBIDDEN = "forbidden"     # footer farms, obvious cross-monetization


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Staggered launch timing (months after network start)
LAUNCH_MONTH_AUTHORITY = 0
LAUNCH_MONTH_REVIEW = 3
LAUNCH_MONTH_SPECIALIST = 6
LAUNCH_MONTH_TREND = 9

_SITE_LAUNCH_MONTHS: dict[SiteType, int] = {
    SiteType.AUTHORITY: LAUNCH_MONTH_AUTHORITY,
    SiteType.REVIEW: LAUNCH_MONTH_REVIEW,
    SiteType.SPECIALIST: LAUNCH_MONTH_SPECIALIST,
    SiteType.TREND: LAUNCH_MONTH_TREND,
}

# Buyer journey mapping from spec
_SITE_TO_BUYER_STAGE: dict[SiteType, BuyerStage] = {
    SiteType.AUTHORITY: BuyerStage.AWARENESS,
    SiteType.SPECIALIST: BuyerStage.COMPARISON,
    SiteType.REVIEW: BuyerStage.RESEARCH,
    SiteType.TREND: BuyerStage.AWARENESS,  # feeds traffic to others
}

# Content focus per site type
_SITE_CONTENT_FOCUS: dict[SiteType, ContentFocus] = {
    SiteType.AUTHORITY: ContentFocus.BROAD_BUYING_GUIDES,
    SiteType.REVIEW: ContentFocus.DEEP_PRODUCT_COMPARISONS,
    SiteType.SPECIALIST: ContentFocus.NARROW_USE_CASE,
    SiteType.TREND: ContentFocus.EMERGING_COVERAGE,
}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class SiteBlueprint:
    """Blueprint for a single site in the monopoly network.

    Attributes
    ----------
    site_type:
        Which of the 4 site types this is.
    niche:
        The niche this site targets.
    sub_niche:
        Optional sub-niche focus (for SPECIALIST sites).
    content_focus:
        Primary content focus area.
    buyer_stage:
        Which buyer journey stage this site captures.
    launch_month:
        Recommended launch month (0 = network start).
    target_queries:
        Example query patterns this site should target.
    editorial_voice:
        Description of the distinct editorial voice.
    """

    site_type: SiteType = SiteType.AUTHORITY
    niche: str = ""
    sub_niche: str = ""
    content_focus: ContentFocus = ContentFocus.BROAD_BUYING_GUIDES
    buyer_stage: BuyerStage = BuyerStage.AWARENESS
    launch_month: int = 0
    target_queries: List[str] = field(default_factory=list)
    editorial_voice: str = ""


@dataclass
class SERPOccupationPlan:
    """Plan for occupying multiple SERP positions for a keyword.

    From the spec — own multiple search results for the same query.

    Attributes
    ----------
    keyword:
        The target keyword.
    site_assignments:
        Mapping of SiteType -> target content angle.
    estimated_positions:
        Target positions for each site (aspirational).
    """

    keyword: str = ""
    site_assignments: Dict[SiteType, str] = field(default_factory=dict)
    estimated_positions: Dict[SiteType, int] = field(default_factory=dict)

    @property
    def sites_targeting(self) -> int:
        return len(self.site_assignments)


@dataclass
class NicheMonopolyPlan:
    """Complete monopoly plan for dominating a niche.

    Attributes
    ----------
    niche:
        The target niche.
    sites:
        Blueprints for all sites in the network.
    serp_plans:
        SERP occupation plans for key queries.
    launch_timeline_months:
        Total months for full network deployment.
    interlinking_rules:
        Safe interlinking guidelines.
    content_segmentation:
        How content is divided across sites.
    """

    niche: str = ""
    sites: List[SiteBlueprint] = field(default_factory=list)
    serp_plans: List[SERPOccupationPlan] = field(default_factory=list)
    launch_timeline_months: int = 9
    interlinking_rules: List[str] = field(default_factory=list)
    content_segmentation: Dict[SiteType, str] = field(default_factory=dict)

    @property
    def site_count(self) -> int:
        return len(self.sites)

    @property
    def is_full_network(self) -> bool:
        """True if all 4 site types are planned."""
        types = {s.site_type for s in self.sites}
        return len(types) == 4


# ---------------------------------------------------------------------------
# Site blueprint generation
# ---------------------------------------------------------------------------

_AUTHORITY_QUERIES = [
    "Best {niche}",
    "How to choose {niche}",
    "Top {niche} for {year}",
    "{niche} buying guide",
]

_REVIEW_QUERIES = [
    "Is {niche} worth it",
    "{niche} vs alternatives",
    "Best alternatives to {niche}",
    "{niche} honest review",
]

_SPECIALIST_QUERIES = [
    "Best {niche} for {sub_niche}",
    "{niche} {sub_niche} guide",
    "{sub_niche} {niche} comparison",
]

_TREND_QUERIES = [
    "New {niche} {year}",
    "Upcoming {niche} releases",
    "{niche} trends {year}",
    "Latest {niche} news",
]


def _build_site_blueprint(
    site_type: SiteType,
    niche: str,
    *,
    sub_niche: str = "",
    year: int = 2026,
) -> SiteBlueprint:
    """Build a blueprint for a single site type."""
    focus = _SITE_CONTENT_FOCUS[site_type]
    buyer_stage = _SITE_TO_BUYER_STAGE[site_type]
    launch_month = _SITE_LAUNCH_MONTHS[site_type]

    # Generate target queries
    query_templates = {
        SiteType.AUTHORITY: _AUTHORITY_QUERIES,
        SiteType.REVIEW: _REVIEW_QUERIES,
        SiteType.SPECIALIST: _SPECIALIST_QUERIES,
        SiteType.TREND: _TREND_QUERIES,
    }
    templates = query_templates.get(site_type, [])
    queries = [
        t.format(niche=niche, sub_niche=sub_niche or "specific use", year=year)
        for t in templates
    ]

    # Editorial voice descriptions
    voices = {
        SiteType.AUTHORITY: "Comprehensive, authoritative, educational tone covering the full category",
        SiteType.REVIEW: "Direct, conversion-focused, detailed product analysis",
        SiteType.SPECIALIST: f"Expert-level depth focused narrowly on {sub_niche or 'sub-niche'}",
        SiteType.TREND: "News-style, forward-looking, emerging product coverage",
    }

    return SiteBlueprint(
        site_type=site_type,
        niche=niche,
        sub_niche=sub_niche,
        content_focus=focus,
        buyer_stage=buyer_stage,
        launch_month=launch_month,
        target_queries=queries,
        editorial_voice=voices.get(site_type, ""),
    )


# ---------------------------------------------------------------------------
# SERP occupation planning
# ---------------------------------------------------------------------------

def plan_serp_occupation(
    keyword: str,
    niche: str,
    *,
    sub_niche: str = "",
) -> SERPOccupationPlan:
    """Plan how to occupy multiple SERP positions for a keyword.

    From the spec::

        Result 1 → Authority site "Best X"
        Result 3 → Review site "X vs Y"
        Result 6 → Specialist site "Best X for apartments"

    Parameters
    ----------
    keyword:
        The target keyword.
    niche:
        The niche.
    sub_niche:
        Optional sub-niche for the specialist site angle.
    """
    assignments: Dict[SiteType, str] = {
        SiteType.AUTHORITY: f"Best {niche} — Complete Guide",
        SiteType.REVIEW: f"{niche} Review — Honest Analysis",
        SiteType.SPECIALIST: f"Best {niche} for {sub_niche or 'Specific Use'}",
        SiteType.TREND: f"New {niche} — What's Coming",
    }

    target_positions: Dict[SiteType, int] = {
        SiteType.AUTHORITY: 1,
        SiteType.REVIEW: 3,
        SiteType.SPECIALIST: 6,
        SiteType.TREND: 8,
    }

    return SERPOccupationPlan(
        keyword=keyword,
        site_assignments=assignments,
        estimated_positions=target_positions,
    )


# ---------------------------------------------------------------------------
# Interlinking rules
# ---------------------------------------------------------------------------

_SAFE_INTERLINKING_RULES: list[str] = [
    "Use natural contextual citations only",
    "Occasional reference links are acceptable",
    "Data-source style linking is safe",
    "NEVER use footer link farms",
    "NEVER use obvious cross-site monetization links",
    "NEVER use identical templates across sites",
    "Sites must appear editorially independent",
]

_CONTENT_SEGMENTATION: dict[SiteType, str] = {
    SiteType.AUTHORITY: "Broad buying guides, FAQ clusters, evergreen educational content",
    SiteType.REVIEW: "Deep individual product reviews, direct comparisons, alternatives",
    SiteType.SPECIALIST: "Narrow use-case optimization, specialized depth",
    SiteType.TREND: "New product releases, industry news, trend predictions",
}


def classify_interlink_safety(link_type: str) -> InterlinkSafety:
    """Classify a cross-site link type for safety.

    Parameters
    ----------
    link_type:
        Description of the link type (e.g. "contextual citation",
        "footer link", "data source reference").

    Returns
    -------
    InterlinkSafety
        Safety classification.
    """
    link_lower = link_type.lower()

    forbidden_patterns = ["footer", "sidebar", "blogroll", "network", "farm"]
    for pattern in forbidden_patterns:
        if pattern in link_lower:
            return InterlinkSafety.FORBIDDEN

    safe_patterns = ["contextual", "citation", "data source", "reference", "editorial"]
    for pattern in safe_patterns:
        if pattern in link_lower:
            return InterlinkSafety.SAFE

    return InterlinkSafety.CAUTION


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def build_monopoly_plan(
    niche: str,
    *,
    sub_niche: str = "",
    target_keywords: Optional[Sequence[str]] = None,
    year: int = 2026,
) -> NicheMonopolyPlan:
    """Build a complete monopoly plan for a niche.

    1. Generate site blueprints for all 4 site types
    2. Plan SERP occupation for target keywords
    3. Apply safe interlinking rules
    4. Define content segmentation

    Parameters
    ----------
    niche:
        The target niche to dominate.
    sub_niche:
        Optional sub-niche focus for the specialist site.
    target_keywords:
        Key queries to plan SERP occupation for.
    year:
        Current year for query templates.

    Returns
    -------
    NicheMonopolyPlan
        Complete monopoly strategy.
    """
    keywords = list(target_keywords or [niche])

    # Build blueprints for all 4 site types
    sites = [
        _build_site_blueprint(SiteType.AUTHORITY, niche, sub_niche=sub_niche, year=year),
        _build_site_blueprint(SiteType.REVIEW, niche, sub_niche=sub_niche, year=year),
        _build_site_blueprint(SiteType.SPECIALIST, niche, sub_niche=sub_niche, year=year),
        _build_site_blueprint(SiteType.TREND, niche, sub_niche=sub_niche, year=year),
    ]

    # Plan SERP occupation for each keyword
    serp_plans = [
        plan_serp_occupation(kw, niche, sub_niche=sub_niche)
        for kw in keywords
    ]

    plan = NicheMonopolyPlan(
        niche=niche,
        sites=sites,
        serp_plans=serp_plans,
        launch_timeline_months=LAUNCH_MONTH_TREND,
        interlinking_rules=list(_SAFE_INTERLINKING_RULES),
        content_segmentation=dict(_CONTENT_SEGMENTATION),
    )

    log_event(
        logger,
        "monopoly_strategy.plan.built",
        niche=niche,
        sites=len(sites),
        keywords=len(keywords),
        serp_plans=len(serp_plans),
    )

    return plan


def evaluate_network_coverage(
    plans: Sequence[NicheMonopolyPlan],
) -> Dict[str, Any]:
    """Evaluate coverage across the full multi-niche portfolio.

    Parameters
    ----------
    plans:
        Monopoly plans for all niches in the portfolio.

    Returns
    -------
    dict
        Coverage metrics including total sites, niches covered,
        full networks count, and total SERP occupation plans.
    """
    total_sites = sum(p.site_count for p in plans)
    full_networks = sum(1 for p in plans if p.is_full_network)
    total_serp_plans = sum(len(p.serp_plans) for p in plans)

    metrics = {
        "niches_covered": len(plans),
        "total_sites": total_sites,
        "full_networks": full_networks,
        "total_serp_plans": total_serp_plans,
    }

    log_event(
        logger,
        "monopoly_strategy.network.evaluated",
        **metrics,
    )

    return metrics
