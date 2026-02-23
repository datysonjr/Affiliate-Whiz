"""
domains.offers.sources.affiliate_networks
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Abstract base class for affiliate network data sources.

Each supported network (ShareASale, CJ Affiliate, Impact, etc.) should
subclass :class:`AffiliateNetworkSource` and implement the three
abstract methods to normalise network-specific API responses into
:class:`~domains.offers.models.Offer` instances.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from src.core.logger import get_logger
from src.domains.offers.models import Offer


# ---------------------------------------------------------------------------
# Commission rate detail
# ---------------------------------------------------------------------------

@dataclass
class CommissionRate:
    """Normalised commission rate returned by a network API.

    Attributes
    ----------
    offer_id:
        The network-specific offer or programme identifier.
    rate:
        Commission percentage as a decimal (0.08 = 8 %).
    rate_type:
        One of ``"percentage"``, ``"flat"``, or ``"tiered"``.
    currency:
        ISO 4217 currency code (default ``"USD"``).
    conditions:
        Human-readable conditions or notes from the network.
    """

    offer_id: str
    rate: float
    rate_type: str = "percentage"
    currency: str = "USD"
    conditions: str = ""


# ---------------------------------------------------------------------------
# Offer detail (extended metadata from a network)
# ---------------------------------------------------------------------------

@dataclass
class OfferDetail:
    """Extended metadata for a single offer returned by a network API.

    Attributes
    ----------
    offer_id:
        Network-specific programme / offer identifier.
    name:
        Programme or product name.
    merchant:
        Merchant / advertiser name.
    description:
        Long-form programme description.
    commission:
        Parsed :class:`CommissionRate`.
    cookie_days:
        Affiliate cookie duration in days.
    landing_url:
        Default destination URL.
    categories:
        List of category labels assigned by the network.
    status:
        Network-reported status string (e.g. ``"active"``).
    raw:
        The unmodified API payload for debugging and audit.
    """

    offer_id: str
    name: str = ""
    merchant: str = ""
    description: str = ""
    commission: CommissionRate | None = None
    cookie_days: int = 30
    landing_url: str = ""
    categories: list[str] = field(default_factory=list)
    status: str = "active"
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


# ---------------------------------------------------------------------------
# Abstract base class
# ---------------------------------------------------------------------------

class AffiliateNetworkSource(ABC):
    """Abstract interface for fetching offer data from an affiliate network.

    Subclasses must implement:

    * :meth:`fetch_offers`          -- bulk discovery of available programmes.
    * :meth:`get_commission_rates`  -- commission details for specific offers.
    * :meth:`get_offer_details`     -- full metadata for a single offer.

    The base class provides common helpers for logging, rate-limit
    tracking, and conversion from :class:`OfferDetail` to the domain
    :class:`~domains.offers.models.Offer` model.

    Parameters
    ----------
    network_name:
        Human-readable network identifier (e.g. ``"ShareASale"``).
    api_key:
        Network API key / token.
    api_secret:
        Network API secret (if required -- may be empty).
    base_url:
        Root URL for the network's API.
    """

    def __init__(
        self,
        network_name: str,
        api_key: str,
        api_secret: str = "",
        base_url: str = "",
    ) -> None:
        self.network_name = network_name
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = base_url
        self.logger: logging.Logger = get_logger(f"offers.sources.{network_name}")
        self._last_request_at: datetime | None = None
        self._request_count: int = 0

    # ------------------------------------------------------------------
    # Abstract methods
    # ------------------------------------------------------------------

    @abstractmethod
    async def fetch_offers(
        self,
        *,
        category: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> list[Offer]:
        """Fetch a paginated list of available offers from the network.

        Parameters
        ----------
        category:
            Optional category filter.  Empty string means all categories.
        limit:
            Maximum number of offers to return per page.
        offset:
            Pagination offset.

        Returns
        -------
        list[Offer]
            Normalised offer objects.

        Raises
        ------
        IntegrationError
            If the network API returns an error or is unreachable.
        """

    @abstractmethod
    async def get_commission_rates(
        self,
        offer_ids: list[str],
    ) -> list[CommissionRate]:
        """Retrieve commission rate details for one or more offers.

        Parameters
        ----------
        offer_ids:
            Network-specific offer / programme identifiers.

        Returns
        -------
        list[CommissionRate]
            One entry per requested offer (order may differ).

        Raises
        ------
        IntegrationError
            If the network API returns an error.
        """

    @abstractmethod
    async def get_offer_details(self, offer_id: str) -> OfferDetail:
        """Retrieve full metadata for a single offer.

        Parameters
        ----------
        offer_id:
            Network-specific offer / programme identifier.

        Returns
        -------
        OfferDetail
            Detailed offer information.

        Raises
        ------
        IntegrationError
            If the offer is not found or the API request fails.
        """

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _track_request(self) -> None:
        """Record that an API request was made (for rate-limit awareness)."""
        self._last_request_at = datetime.now(timezone.utc)
        self._request_count += 1
        self.logger.debug(
            "API request #%d to %s at %s",
            self._request_count,
            self.network_name,
            self._last_request_at.isoformat(),
        )

    def _detail_to_offer(self, detail: OfferDetail) -> Offer:
        """Convert an :class:`OfferDetail` into the domain :class:`Offer` model.

        Parameters
        ----------
        detail:
            Network-specific offer detail payload.

        Returns
        -------
        Offer
            A fully initialised domain offer.
        """
        commission_rate = detail.commission.rate if detail.commission else 0.0
        return Offer(
            name=detail.name,
            merchant=detail.merchant,
            commission_rate=commission_rate,
            cookie_days=detail.cookie_days,
            category=detail.categories[0] if detail.categories else "",
            source_network=self.network_name,
            url=detail.landing_url,
            active=detail.status.lower() == "active",
            metadata={"network_offer_id": detail.offer_id, **detail.raw},
        )

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}(network={self.network_name!r}, "
            f"requests={self._request_count})"
        )
