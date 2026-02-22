"""
domains.offers.models
~~~~~~~~~~~~~~~~~~~~~

Data models for affiliate offers, scoring, and tier classification.

An :class:`Offer` represents a single affiliate programme or product that
OpenClaw can promote.  Each offer is scored via :class:`OfferScore` and
assigned an :class:`OfferTier` (A through D) to drive prioritisation in
the content pipeline.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, unique
from typing import Any


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

@unique
class OfferTier(str, Enum):
    """Quality tier assigned to discovered affiliate offers.

    Tiers drive content prioritisation and resource allocation:
    - A: High-value offers that justify dedicated long-form content.
    - B: Good offers suitable for comparison/roundup inclusion.
    - C: Acceptable offers used as supplementary mentions.
    - D: Low-value offers kept in the database but not actively promoted.
    """

    A = "A"
    B = "B"
    C = "C"
    D = "D"

    @classmethod
    def from_score(cls, score: float) -> OfferTier:
        """Derive the tier from a numeric score (0-100 scale).

        Thresholds:
            >= 80 -> A, >= 60 -> B, >= 40 -> C, < 40 -> D

        Parameters
        ----------
        score:
            Numeric offer score between 0 and 100.

        Returns
        -------
        OfferTier
            The computed tier.
        """
        if score >= 80:
            return cls.A
        if score >= 60:
            return cls.B
        if score >= 40:
            return cls.C
        return cls.D


# ---------------------------------------------------------------------------
# OfferScore
# ---------------------------------------------------------------------------

@dataclass
class OfferScore:
    """Composite score capturing multiple dimensions of offer quality.

    Each sub-score is normalised to a 0-100 range.  The final
    :attr:`total` is a weighted average that determines the
    :class:`OfferTier`.

    Attributes
    ----------
    commission_score:
        How competitive the commission rate is relative to the niche average.
    cookie_score:
        Score based on cookie duration (longer = better).
    conversion_score:
        Estimated conversion rate score derived from merchant reputation
        and landing-page quality.
    demand_score:
        Search demand score for the merchant / product keywords.
    competition_score:
        Inverse competition score -- higher means *less* competition.
    total:
        Weighted composite score (auto-computed if not provided).
    """

    commission_score: float = 0.0
    cookie_score: float = 0.0
    conversion_score: float = 0.0
    demand_score: float = 0.0
    competition_score: float = 0.0
    total: float = 0.0

    # Default weights used by ``compute_total``.
    _WEIGHTS: dict[str, float] = field(
        default_factory=lambda: {
            "commission": 0.30,
            "cookie": 0.10,
            "conversion": 0.25,
            "demand": 0.20,
            "competition": 0.15,
        },
        repr=False,
        compare=False,
    )

    def compute_total(self, weights: dict[str, float] | None = None) -> float:
        """Calculate the weighted composite score and store it in :attr:`total`.

        Parameters
        ----------
        weights:
            Optional custom weight dict.  Keys must be ``commission``,
            ``cookie``, ``conversion``, ``demand``, ``competition``.
            Falls back to :attr:`_WEIGHTS` if not provided.

        Returns
        -------
        float
            The computed total score (also stored on the instance).
        """
        w = weights or self._WEIGHTS
        self.total = (
            self.commission_score * w.get("commission", 0.30)
            + self.cookie_score * w.get("cookie", 0.10)
            + self.conversion_score * w.get("conversion", 0.25)
            + self.demand_score * w.get("demand", 0.20)
            + self.competition_score * w.get("competition", 0.15)
        )
        self.total = round(min(max(self.total, 0.0), 100.0), 2)
        return self.total

    def to_dict(self) -> dict[str, float]:
        """Serialise the score to a plain dictionary."""
        return {
            "commission_score": self.commission_score,
            "cookie_score": self.cookie_score,
            "conversion_score": self.conversion_score,
            "demand_score": self.demand_score,
            "competition_score": self.competition_score,
            "total": self.total,
        }


# ---------------------------------------------------------------------------
# Offer
# ---------------------------------------------------------------------------

@dataclass
class Offer:
    """Represents a single affiliate programme or product offer.

    An Offer is the fundamental unit that the research agent discovers and
    the content pipeline turns into revenue-generating articles.

    Attributes
    ----------
    id:
        Unique identifier (auto-generated UUID hex if not provided).
    name:
        Human-readable offer / product name.
    merchant:
        Name of the merchant or brand behind the offer.
    commission_rate:
        Commission percentage expressed as a decimal (e.g. 0.08 for 8 %).
    cookie_days:
        Affiliate cookie duration in days.
    avg_order_value:
        Average order value in USD (used for EPC estimation).
    category:
        Niche or product category label (e.g. ``"home_office"``).
    score:
        Composite :class:`OfferScore` summarising offer quality.
    tier:
        Derived :class:`OfferTier` classification.
    source_network:
        Affiliate network that surfaced this offer (e.g. ``"ShareASale"``).
    url:
        Deep-link or landing-page URL for the offer.
    active:
        Whether the offer is currently accepting affiliates.
    created_at:
        UTC timestamp when the offer was first discovered.
    updated_at:
        UTC timestamp of the most recent data refresh.
    metadata:
        Free-form dict for network-specific fields (sub-IDs, coupons, etc.).
    """

    name: str
    merchant: str
    commission_rate: float = 0.0
    cookie_days: int = 30
    avg_order_value: float = 0.0
    category: str = ""
    score: OfferScore = field(default_factory=OfferScore)
    tier: OfferTier = OfferTier.D
    source_network: str = ""
    url: str = ""
    active: bool = True
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Derived properties
    # ------------------------------------------------------------------

    @property
    def estimated_epc(self) -> float:
        """Estimate earnings-per-click assuming a 2 % base conversion rate.

        Returns
        -------
        float
            Estimated EPC in USD.
        """
        base_conversion = 0.02
        return round(self.avg_order_value * self.commission_rate * base_conversion, 4)

    # ------------------------------------------------------------------
    # Scoring helpers
    # ------------------------------------------------------------------

    def compute_score(self, weights: dict[str, float] | None = None) -> OfferTier:
        """Recompute the composite score and update the tier.

        Parameters
        ----------
        weights:
            Optional custom weight dict passed through to
            :meth:`OfferScore.compute_total`.

        Returns
        -------
        OfferTier
            The newly assigned tier.
        """
        self.score.compute_total(weights)
        self.tier = OfferTier.from_score(self.score.total)
        self.updated_at = datetime.now(timezone.utc)
        return self.tier

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialise the offer to a JSON-friendly dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "merchant": self.merchant,
            "commission_rate": self.commission_rate,
            "cookie_days": self.cookie_days,
            "avg_order_value": self.avg_order_value,
            "category": self.category,
            "score": self.score.to_dict(),
            "tier": self.tier.value,
            "source_network": self.source_network,
            "url": self.url,
            "active": self.active,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "metadata": self.metadata,
        }

    def __repr__(self) -> str:
        return (
            f"Offer(name={self.name!r}, merchant={self.merchant!r}, "
            f"tier={self.tier.value}, score={self.score.total:.1f}, "
            f"active={self.active})"
        )
