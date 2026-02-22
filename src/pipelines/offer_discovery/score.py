"""
pipelines.offer_discovery.score
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Score normalized affiliate offers using a weighted multi-factor model.
Each offer receives sub-scores for commission rate, average order value
(as a proxy for revenue potential), cookie duration, and competitive
positioning.  The composite score determines the :class:`OfferTier`
(A/B/C/rejected) which drives content pipeline prioritisation.

Scoring thresholds are loaded from ``config/pipelines.yaml`` under
``offer_discovery.steps[2]`` (min_score, tier_thresholds).

Design references:
    - config/pipelines.yaml  ``offer_discovery.steps[2]``
    - domains/offers/models.py  (OfferScore, OfferTier, Offer)
    - ARCHITECTURE.md  Section 3 (Pipeline Architecture)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.core.constants import (
    DEFAULT_MIN_OFFER_SCORE,
    OFFER_TIER_THRESHOLDS,
)
from src.core.errors import PipelineStepError
from src.core.logger import get_logger, log_event
from src.domains.offers.models import Offer, OfferScore, OfferTier

logger = get_logger("pipelines.offer_discovery.score")


# ---------------------------------------------------------------------------
# Default scoring weights (can be overridden via pipeline config)
# ---------------------------------------------------------------------------

DEFAULT_WEIGHTS: Dict[str, float] = {
    "commission": 0.30,
    "aov": 0.25,
    "cookie": 0.10,
    "conversion": 0.20,
    "competition": 0.15,
}


# ---------------------------------------------------------------------------
# Benchmark ranges for normalising raw values to 0-100
# ---------------------------------------------------------------------------

# Commission rate benchmarks (expressed as decimal fractions)
_COMMISSION_BENCHMARKS = {
    "floor": 0.01,   # 1% -- minimum noteworthy commission
    "good": 0.08,    # 8% -- solid mid-range
    "excellent": 0.20,  # 20% -- top-tier digital/SaaS offers
}

# Average order value benchmarks (USD)
_AOV_BENCHMARKS = {
    "floor": 10.0,
    "good": 75.0,
    "excellent": 300.0,
}

# Cookie duration benchmarks (days)
_COOKIE_BENCHMARKS = {
    "floor": 1,
    "good": 30,
    "excellent": 90,
}


# ---------------------------------------------------------------------------
# Sub-score calculators
# ---------------------------------------------------------------------------

def _normalize_to_score(
    value: float,
    floor: float,
    good: float,
    excellent: float,
) -> float:
    """Map a raw numeric value onto a 0-100 scale using benchmark thresholds.

    Values at or below *floor* score 0.  Values at *good* score 50.
    Values at or above *excellent* score 100.  Intermediate values are
    linearly interpolated.

    Parameters
    ----------
    value:
        The raw metric value.
    floor:
        The minimum meaningful value (maps to 0).
    good:
        A solid mid-range value (maps to 50).
    excellent:
        An outstanding value (maps to 100).

    Returns
    -------
    float
        Score between 0.0 and 100.0.
    """
    if value <= floor:
        return 0.0
    if value >= excellent:
        return 100.0
    if value <= good:
        # Linear interpolation from floor..good -> 0..50
        return 50.0 * (value - floor) / (good - floor)
    # Linear interpolation from good..excellent -> 50..100
    return 50.0 + 50.0 * (value - good) / (excellent - good)


def calculate_commission_score(commission_rate: float) -> float:
    """Score a commission rate on a 0-100 scale.

    Higher commission rates yield higher scores, benchmarked against
    typical affiliate programme rates across niches.

    Parameters
    ----------
    commission_rate:
        Commission as a decimal fraction (e.g. ``0.08`` for 8%).

    Returns
    -------
    float
        Normalised score between 0.0 and 100.0.

    Examples
    --------
    >>> calculate_commission_score(0.08)
    50.0
    >>> calculate_commission_score(0.20)
    100.0
    """
    return round(
        _normalize_to_score(
            commission_rate,
            _COMMISSION_BENCHMARKS["floor"],
            _COMMISSION_BENCHMARKS["good"],
            _COMMISSION_BENCHMARKS["excellent"],
        ),
        2,
    )


def calculate_aov_score(avg_order_value: float) -> float:
    """Score an average order value on a 0-100 scale.

    Higher AOV means more revenue per conversion, making the offer more
    attractive for content investment.

    Parameters
    ----------
    avg_order_value:
        Average order value in USD.

    Returns
    -------
    float
        Normalised score between 0.0 and 100.0.

    Examples
    --------
    >>> calculate_aov_score(75.0)
    50.0
    >>> calculate_aov_score(300.0)
    100.0
    """
    return round(
        _normalize_to_score(
            avg_order_value,
            _AOV_BENCHMARKS["floor"],
            _AOV_BENCHMARKS["good"],
            _AOV_BENCHMARKS["excellent"],
        ),
        2,
    )


def _calculate_cookie_score(cookie_days: int) -> float:
    """Score a cookie duration on a 0-100 scale.

    Longer cookie windows give the affiliate more time to earn a
    commission from referred traffic.

    Parameters
    ----------
    cookie_days:
        Cookie duration in days.

    Returns
    -------
    float
        Normalised score between 0.0 and 100.0.
    """
    return round(
        _normalize_to_score(
            float(cookie_days),
            float(_COOKIE_BENCHMARKS["floor"]),
            float(_COOKIE_BENCHMARKS["good"]),
            float(_COOKIE_BENCHMARKS["excellent"]),
        ),
        2,
    )


def _estimate_conversion_score(offer_data: Dict[str, Any]) -> float:
    """Heuristically estimate a conversion likelihood score.

    In the absence of real conversion data, we use proxy signals:
    - Known merchant brand strength (large merchants convert better)
    - Whether a landing page URL is present and looks clean
    - Category popularity

    Parameters
    ----------
    offer_data:
        Normalized offer dict.

    Returns
    -------
    float
        Estimated conversion score between 0.0 and 100.0.
    """
    score = 40.0  # baseline

    # Boost for having a URL (suggests active programme)
    url = offer_data.get("url", "")
    if url and url.startswith("http"):
        score += 15.0

    # Boost for having alternate sources (validates offer legitimacy)
    alt_sources = offer_data.get("alternate_sources", [])
    score += min(len(alt_sources) * 10.0, 20.0)

    # Boost for popular categories
    popular_categories = {
        "technology", "software", "saas", "finance", "health",
        "home_office", "fitness", "education", "travel",
    }
    category = offer_data.get("category", "").lower()
    if category in popular_categories:
        score += 15.0

    # Boost for well-known merchants
    merchant = offer_data.get("merchant", "").lower()
    if len(merchant) > 3:  # at least a real name
        score += 10.0

    return round(min(score, 100.0), 2)


def _estimate_competition_score(offer_data: Dict[str, Any]) -> float:
    """Heuristically estimate a competition score (higher = less competition).

    Uses the inverse logic: niche categories with fewer alternate sources
    suggest less saturation, which is better for new content.

    Parameters
    ----------
    offer_data:
        Normalized offer dict.

    Returns
    -------
    float
        Competition advantage score between 0.0 and 100.0.
    """
    score = 50.0  # neutral baseline

    # Fewer alternate sources might mean less affiliate competition
    alt_count = len(offer_data.get("alternate_sources", []))
    if alt_count == 0:
        score += 20.0
    elif alt_count == 1:
        score += 10.0
    else:
        score -= min(alt_count * 5.0, 20.0)

    # Niche categories tend to have less competition
    broad_categories = {"technology", "finance", "health", "travel"}
    category = offer_data.get("category", "").lower()
    if category and category not in broad_categories:
        score += 15.0

    return round(min(max(score, 0.0), 100.0), 2)


# ---------------------------------------------------------------------------
# Main scoring functions
# ---------------------------------------------------------------------------

def score_offer(
    offer_data: Dict[str, Any],
    *,
    weights: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """Compute a composite quality score for a normalized offer.

    Calculates sub-scores for commission, AOV, cookie duration,
    estimated conversion, and competition, then produces a weighted
    total.  The offer dict is updated in place with ``score`` and
    ``tier`` keys.

    Parameters
    ----------
    offer_data:
        A normalized offer dict (output of
        :func:`~pipelines.offer_discovery.normalize.normalize_offer`).
    weights:
        Optional custom scoring weights.  Keys: ``commission``, ``aov``,
        ``cookie``, ``conversion``, ``competition``.  Falls back to
        :data:`DEFAULT_WEIGHTS`.

    Returns
    -------
    dict[str, Any]
        The same *offer_data* dict, now augmented with ``score`` (a dict
        of sub-scores and total) and ``tier`` (string tier label).

    Raises
    ------
    PipelineStepError
        If the offer data is missing critical fields.
    """
    w = weights or DEFAULT_WEIGHTS

    commission_rate = offer_data.get("commission_rate", 0.0)
    avg_order_value = offer_data.get("avg_order_value", 0.0)
    cookie_days = offer_data.get("cookie_days", 0)

    # Calculate sub-scores
    comm_score = calculate_commission_score(commission_rate)
    aov_score = calculate_aov_score(avg_order_value)
    cookie_score = _calculate_cookie_score(cookie_days)
    conversion_score = _estimate_conversion_score(offer_data)
    competition_score = _estimate_competition_score(offer_data)

    # Weighted composite
    total = (
        comm_score * w.get("commission", 0.30)
        + aov_score * w.get("aov", 0.25)
        + cookie_score * w.get("cookie", 0.10)
        + conversion_score * w.get("conversion", 0.20)
        + competition_score * w.get("competition", 0.15)
    )
    total = round(min(max(total, 0.0), 100.0), 2)

    offer_data["score"] = {
        "commission_score": comm_score,
        "aov_score": aov_score,
        "cookie_score": cookie_score,
        "conversion_score": conversion_score,
        "competition_score": competition_score,
        "total": total,
    }

    offer_data["tier"] = assign_tier(total)

    log_event(
        logger,
        "score.offer.ok",
        name=offer_data.get("name", "unknown"),
        total=total,
        tier=offer_data["tier"],
    )
    return offer_data


def assign_tier(
    total_score: float,
    *,
    thresholds: Optional[Dict[str, int]] = None,
    min_score: Optional[int] = None,
) -> str:
    """Assign a quality tier based on a total score.

    Tiers follow the thresholds defined in ``config/pipelines.yaml``:
    - A: >= 80 (high-value, dedicated long-form content)
    - B: >= 60 (good, suitable for comparison articles)
    - C: >= 40 (acceptable, supplementary mentions)
    - rejected: < min_score (not worth promoting)

    Parameters
    ----------
    total_score:
        Composite score on a 0-100 scale.
    thresholds:
        Optional custom tier thresholds dict with keys ``A``, ``B``, ``C``.
        Falls back to :data:`OFFER_TIER_THRESHOLDS` from constants.
    min_score:
        Minimum score below which offers are ``"rejected"``.  Falls back
        to :data:`DEFAULT_MIN_OFFER_SCORE`.

    Returns
    -------
    str
        Tier label: ``"A"``, ``"B"``, ``"C"``, or ``"rejected"``.
    """
    t = thresholds or OFFER_TIER_THRESHOLDS
    cutoff = min_score if min_score is not None else DEFAULT_MIN_OFFER_SCORE

    if total_score < cutoff:
        return "rejected"
    if total_score >= t.get("A", 80):
        return "A"
    if total_score >= t.get("B", 60):
        return "B"
    if total_score >= t.get("C", 40):
        return "C"
    return "rejected"


def score_offers_batch(
    offers: List[Dict[str, Any]],
    *,
    weights: Optional[Dict[str, float]] = None,
    min_score: Optional[int] = None,
    include_rejected: bool = False,
) -> List[Dict[str, Any]]:
    """Score a batch of normalized offers and optionally filter rejects.

    Convenience wrapper around :func:`score_offer` that processes a list
    and returns only offers that meet the minimum score threshold.

    Parameters
    ----------
    offers:
        List of normalized offer dicts.
    weights:
        Optional custom scoring weights.
    min_score:
        Minimum total score to include in results.  Falls back to
        :data:`DEFAULT_MIN_OFFER_SCORE`.
    include_rejected:
        If ``True``, include rejected offers in the output (marked with
        ``tier="rejected"``).

    Returns
    -------
    list[dict[str, Any]]
        Scored (and optionally filtered) offers, sorted by total score
        descending.
    """
    cutoff = min_score if min_score is not None else DEFAULT_MIN_OFFER_SCORE
    scored: List[Dict[str, Any]] = []
    rejected_count = 0

    for offer in offers:
        try:
            score_offer(offer, weights=weights)
        except PipelineStepError as exc:
            logger.warning("Skipping unscoreable offer: %s", exc)
            continue

        total = offer.get("score", {}).get("total", 0.0)
        if total < cutoff and not include_rejected:
            rejected_count += 1
            continue

        scored.append(offer)

    # Sort by total score, descending
    scored.sort(key=lambda o: o.get("score", {}).get("total", 0.0), reverse=True)

    log_event(
        logger,
        "score.batch.complete",
        input_count=len(offers),
        scored_count=len(scored),
        rejected_count=rejected_count,
    )
    return scored
