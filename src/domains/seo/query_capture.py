"""
domains.seo.query_capture
~~~~~~~~~~~~~~~~~~~~~~~~~~

OpenClaw AI Query Capture Engine.

Detects, scores, and prioritises emerging search queries BEFORE they
become competitive.  Implements the strategy from
``docs/seo/OPENCLAW_AI_QUERY_CAPTURE_ENGINE.md``.

The engine:
    1. Expands seed products into the 4 emerging query types
    2. Scores each query by buyer intent, content supply gap, and timing
    3. Groups queries into authority clusters (5-page bundles)
    4. Returns a prioritised publish queue

Design references:
    - docs/seo/OPENCLAW_AI_QUERY_CAPTURE_ENGINE.md
    - src/domains/seo/keyword.py  (KeywordData, SearchIntent)
    - src/agents/research_agent.py  (KeywordCandidate)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, unique
from typing import Any, Dict, List, Optional, Sequence

from src.core.logger import get_logger, log_event

logger = get_logger("domains.seo.query_capture")


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


@unique
class EmergingQueryType(str, Enum):
    """The 4 emerging query types from the Query Capture Engine spec."""

    NEW_PRODUCT_RELEASE = "new_product_release"
    NEW_CATEGORY = "new_category"
    PROBLEM_TRIGGERED = "problem_triggered"
    MODEL_SPECIFIC_DECISION = "model_specific_decision"


@unique
class SignalSource(str, Enum):
    """Where the emerging query signal was detected."""

    GOOGLE_AUTOCOMPLETE = "google_autocomplete"
    PEOPLE_ALSO_ASK = "people_also_ask"
    REDDIT_DISCUSSION = "reddit_discussion"
    AMAZON_NEW_RELEASE = "amazon_new_release"
    YOUTUBE_REVIEWS = "youtube_reviews"
    TIKTOK_TRENDS = "tiktok_trends"
    AFFILIATE_NETWORK = "affiliate_network"
    AI_QUESTION_HARVEST = "ai_question_harvest"
    AMAZON_REVIEW_MINING = "amazon_review_mining"
    MANUAL = "manual"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class EmergingQuery:
    """A single emerging query detected by the capture engine.

    Attributes
    ----------
    query:
        The search query phrase.
    query_type:
        Which of the 4 emerging query types this matches.
    product_name:
        The product or category this relates to.
    signal_source:
        Where the signal was detected.
    capture_score:
        Priority score (0-100). Higher = publish sooner.
    buyer_intent_rank:
        1-5 based on the buyer intent priority order
        (1=best, 2=vs, 3=worth_it, 4=review, 5=alternatives).
    content_supply:
        Estimated number of existing quality pages for this query.
        Lower = bigger opportunity.
    days_since_trigger:
        Days since the product release or trend spike.
        Lower = more urgent.
    detected_at:
        UTC timestamp when the query was first detected.
    metadata:
        Additional context from the signal source.
    """

    query: str
    query_type: EmergingQueryType = EmergingQueryType.NEW_PRODUCT_RELEASE
    product_name: str = ""
    signal_source: SignalSource = SignalSource.MANUAL
    capture_score: float = 0.0
    buyer_intent_rank: int = 5
    content_supply: int = 0
    days_since_trigger: int = 0
    detected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_within_first_page_window(self) -> bool:
        """True if still within the 30-day first-page advantage window."""
        return self.days_since_trigger <= 30

    @property
    def should_auto_publish(self) -> bool:
        """True if query meets the auto-publish threshold.

        From the spec: commercial product + clear buyer decision + limited
        existing content.
        """
        return self.buyer_intent_rank <= 3 and self.content_supply < 5


@dataclass
class AuthorityCluster:
    """A 5-page authority cluster for a single product/topic.

    From the spec — never publish ONE page. Always publish:
    review + comparison + alternatives + troubleshooting + buying guide.

    Attributes
    ----------
    product_name:
        The seed product or topic.
    queries:
        The grouped emerging queries forming this cluster.
    cluster_score:
        Average capture score of all queries in the cluster.
    page_types:
        The content types to publish for this cluster.
    """

    product_name: str = ""
    queries: List[EmergingQuery] = field(default_factory=list)
    cluster_score: float = 0.0
    page_types: List[str] = field(
        default_factory=lambda: [
            "review",
            "comparison",
            "alternatives",
            "troubleshooting",
            "buying_guide",
        ]
    )

    @property
    def is_complete(self) -> bool:
        """True if the cluster has queries covering all 5 page types."""
        return len(self.queries) >= 5

    @property
    def query_count(self) -> int:
        return len(self.queries)


# ---------------------------------------------------------------------------
# Buyer intent classification
# ---------------------------------------------------------------------------

_BUYER_INTENT_PATTERNS: list[tuple[int, re.Pattern[str]]] = [
    (1, re.compile(r"\bbest\b", re.IGNORECASE)),
    (2, re.compile(r"\bvs\b|\bversus\b|\bcompare\b|\bcomparison\b", re.IGNORECASE)),
    (
        3,
        re.compile(
            r"\bworth\s+it\b|\bshould\s+i\s+buy\b|\bworth\s+buying\b", re.IGNORECASE
        ),
    ),
    (4, re.compile(r"\breview\b|\breviews\b|\brated\b", re.IGNORECASE)),
    (
        5,
        re.compile(r"\balternative\b|\balternatives\b|\binstead\s+of\b", re.IGNORECASE),
    ),
]


def classify_buyer_intent(query: str) -> int:
    """Return buyer intent rank (1-5) for a query.

    Priority order from the spec:
        1. "best"
        2. "vs" / "comparison"
        3. "worth it" / "should I buy"
        4. "review"
        5. "alternatives"

    Returns 6 if no buyer intent signal is detected.
    """
    for rank, pattern in _BUYER_INTENT_PATTERNS:
        if pattern.search(query):
            return rank
    return 6


# ---------------------------------------------------------------------------
# Query type classification
# ---------------------------------------------------------------------------

_QUERY_TYPE_PATTERNS: dict[EmergingQueryType, list[re.Pattern[str]]] = {
    EmergingQueryType.NEW_PRODUCT_RELEASE: [
        re.compile(r"\bis\s+\w+\s+worth\s+it\b", re.IGNORECASE),
        re.compile(r"\bvs\s+(?:previous|old|last)\b", re.IGNORECASE),
        re.compile(r"\bnew\s+\d{4}\b", re.IGNORECASE),
        re.compile(r"\bdoes\s+[\w\s]+\bsupport\b", re.IGNORECASE),
    ],
    EmergingQueryType.MODEL_SPECIFIC_DECISION: [
        re.compile(r"\bis\s+\w[\w\s]+\bgood\s+for\b", re.IGNORECASE),
        re.compile(r"\bshould\s+i\s+(?:buy|get|upgrade)\b", re.IGNORECASE),
        re.compile(r"\bis\s+\w[\w\s]+\bworth\s+(?:buying|it)\b", re.IGNORECASE),
    ],
    EmergingQueryType.PROBLEM_TRIGGERED: [
        re.compile(r"\bbest\s+\w+\s+for\s+\w+\s+\w+", re.IGNORECASE),
        re.compile(
            r"\bfor\s+(?:back\s+pain|bad\s+credit|small\s+spaces?|beginners?)\b",
            re.IGNORECASE,
        ),
    ],
    EmergingQueryType.NEW_CATEGORY: [
        re.compile(
            r"\bbest\s+(?:ai|smart|portable|wireless|electric)\s+\w+", re.IGNORECASE
        ),
    ],
}


def classify_query_type(query: str) -> EmergingQueryType:
    """Classify a query into one of the 4 emerging query types.

    Checks patterns in priority order:
    new product release > model-specific > problem-triggered > new category.
    """
    for qtype, patterns in _QUERY_TYPE_PATTERNS.items():
        for pattern in patterns:
            if pattern.search(query):
                return qtype
    return EmergingQueryType.NEW_CATEGORY


# ---------------------------------------------------------------------------
# Autocomplete expansion
# ---------------------------------------------------------------------------

_AUTOCOMPLETE_TEMPLATES: list[str] = [
    "is {product}",
    "{product} vs",
    "best alternative to {product}",
    "problems with {product}",
    "{product} review",
    "should I buy {product}",
    "best {product}",
    "{product} worth it",
    "{product} comparison",
    "{product} for beginners",
]


def expand_product_queries(
    product_name: str,
    *,
    templates: Optional[List[str]] = None,
) -> List[str]:
    """Expand a product name into the full autocomplete mining set.

    From the spec — for each seed product, extract all common query
    variations. Do not wait for search volume confirmation.

    Parameters
    ----------
    product_name:
        The product or category name.
    templates:
        Custom templates. If ``None``, uses the default set.

    Returns
    -------
    list[str]
        Expanded query list.
    """
    tpls = templates or _AUTOCOMPLETE_TEMPLATES
    queries = [t.format(product=product_name) for t in tpls]

    log_event(
        logger,
        "query_capture.expand.ok",
        product=product_name,
        query_count=len(queries),
    )
    return queries


# ---------------------------------------------------------------------------
# Capture score computation
# ---------------------------------------------------------------------------


def compute_capture_score(
    *,
    buyer_intent_rank: int,
    content_supply: int,
    days_since_trigger: int,
    is_trending: bool = False,
) -> float:
    """Score an emerging query for publish priority (0-100).

    Higher = publish sooner.

    Factors:
        - Buyer intent (rank 1 = highest score contribution)
        - Content supply gap (fewer existing pages = higher score)
        - Timing urgency (fewer days since trigger = higher score)
        - Trending bonus

    Parameters
    ----------
    buyer_intent_rank:
        1-6, where 1 = "best" queries (highest intent).
    content_supply:
        Estimated existing quality pages for this query.
    days_since_trigger:
        Days since product release or trend spike.
    is_trending:
        Whether the query is actively trending up.

    Returns
    -------
    float
        Capture score between 0 and 100.
    """
    # Intent score: rank 1 = 30pts, rank 6 = 5pts
    intent_score = max(35 - (buyer_intent_rank * 5), 5)

    # Supply gap: 0 existing pages = 30pts, 10+ = 0pts
    supply_score = max(30 - (content_supply * 3), 0)

    # Timing: 0 days = 25pts, 60+ days = 0pts
    timing_score = max(25 - (days_since_trigger * 0.42), 0)

    # Trending bonus
    trend_bonus = 15 if is_trending else 0

    score = intent_score + supply_score + timing_score + trend_bonus
    return round(min(max(score, 0), 100), 1)


# ---------------------------------------------------------------------------
# Authority cluster builder
# ---------------------------------------------------------------------------


def build_authority_clusters(
    queries: Sequence[EmergingQuery],
) -> List[AuthorityCluster]:
    """Group emerging queries into authority clusters by product.

    From the spec — never publish ONE page. Group related queries and
    plan the full 5-page bundle (review + comparison + alternatives +
    troubleshooting + buying guide).

    Parameters
    ----------
    queries:
        Flat list of scored emerging queries.

    Returns
    -------
    list[AuthorityCluster]
        Clusters sorted by average capture score (highest first).
    """
    product_groups: Dict[str, List[EmergingQuery]] = {}
    for q in queries:
        key = q.product_name.lower().strip() or q.query.lower().strip()
        if key not in product_groups:
            product_groups[key] = []
        product_groups[key].append(q)

    clusters: List[AuthorityCluster] = []
    for product, group_queries in product_groups.items():
        avg_score = sum(q.capture_score for q in group_queries) / len(group_queries)
        cluster = AuthorityCluster(
            product_name=product,
            queries=sorted(group_queries, key=lambda q: q.capture_score, reverse=True),
            cluster_score=round(avg_score, 1),
        )
        clusters.append(cluster)

    clusters.sort(key=lambda c: c.cluster_score, reverse=True)

    log_event(
        logger,
        "query_capture.clusters.built",
        total_queries=len(queries),
        cluster_count=len(clusters),
    )
    return clusters


# ---------------------------------------------------------------------------
# Main pipeline entry point
# ---------------------------------------------------------------------------


def capture_emerging_queries(
    product_names: Sequence[str],
    *,
    content_supply_map: Optional[Dict[str, int]] = None,
    days_since_trigger_map: Optional[Dict[str, int]] = None,
    trending_products: Optional[set[str]] = None,
) -> List[AuthorityCluster]:
    """Run the full Query Capture Engine pipeline.

    1. Expand each product into autocomplete queries
    2. Classify query type and buyer intent
    3. Score each query
    4. Build authority clusters
    5. Return sorted publish queue

    Parameters
    ----------
    product_names:
        Seed product/category names to scan.
    content_supply_map:
        Optional mapping of query -> estimated existing page count.
    days_since_trigger_map:
        Optional mapping of product -> days since release/trend.
    trending_products:
        Set of product names that are actively trending.

    Returns
    -------
    list[AuthorityCluster]
        Prioritised authority clusters, ready for content generation.
    """
    supply = content_supply_map or {}
    timing = days_since_trigger_map or {}
    trending = trending_products or set()

    all_queries: List[EmergingQuery] = []

    for product in product_names:
        expanded = expand_product_queries(product)
        product_lower = product.lower().strip()
        days = timing.get(product_lower, 0)
        is_trending = product_lower in {p.lower() for p in trending}

        for query_text in expanded:
            intent_rank = classify_buyer_intent(query_text)
            query_type = classify_query_type(query_text)
            existing_pages = supply.get(query_text.lower(), 0)

            score = compute_capture_score(
                buyer_intent_rank=intent_rank,
                content_supply=existing_pages,
                days_since_trigger=days,
                is_trending=is_trending,
            )

            eq = EmergingQuery(
                query=query_text,
                query_type=query_type,
                product_name=product,
                signal_source=SignalSource.MANUAL,
                capture_score=score,
                buyer_intent_rank=intent_rank,
                content_supply=existing_pages,
                days_since_trigger=days,
            )
            all_queries.append(eq)

    clusters = build_authority_clusters(all_queries)

    log_event(
        logger,
        "query_capture.pipeline.complete",
        products=len(product_names),
        total_queries=len(all_queries),
        clusters=len(clusters),
        auto_publish_count=sum(1 for q in all_queries if q.should_auto_publish),
    )

    return clusters
