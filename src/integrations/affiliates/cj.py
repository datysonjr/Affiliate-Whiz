"""
integrations.affiliates.cj
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Client for the Commission Junction (CJ Affiliate) API.

Provides :class:`CJIntegration` which wraps the CJ Affiliate REST API
to discover advertisers, retrieve product links, pull commission reports,
and search the CJ product catalogue.

Design references:
    - https://developers.cj.com/
    - config/providers.yaml  ``cj`` section
    - ARCHITECTURE.md  Section 4 (Integration Layer)

Usage::

    from src.integrations.affiliates.cj import CJIntegration

    cj = CJIntegration(
        api_key="your-cj-api-key",
        website_id="your-cj-website-id",
    )
    advertisers = await cj.get_advertisers(category="Technology")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.core.constants import DEFAULT_MAX_RETRIES, DEFAULT_REQUEST_TIMEOUT
from src.core.errors import (
    APIAuthenticationError,
    IntegrationError,
)
from src.core.logger import get_logger, log_event

logger = get_logger("integrations.affiliates.cj")

# ---------------------------------------------------------------------------
# CJ API constants
# ---------------------------------------------------------------------------

_BASE_URL = "https://commissions.api.cj.com"
_ADVERTISER_API = "https://advertiser-lookup.api.cj.com"
_LINK_API = "https://link-search.api.cj.com"
_PRODUCT_API = "https://product-search.api.cj.com"


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------

@dataclass
class CJAdvertiser:
    """Normalised advertiser record from the CJ API.

    Attributes
    ----------
    advertiser_id:
        CJ's unique advertiser identifier.
    name:
        Advertiser / merchant name.
    category:
        Primary programme category.
    network_rank:
        CJ network rank (1-5 scale, higher is better).
    seven_day_epc:
        Earnings per 100 clicks over the last 7 days.
    three_month_epc:
        Earnings per 100 clicks over the last 3 months.
    commission_terms:
        Human-readable description of commission structure.
    cookie_days:
        Affiliate cookie duration in days.
    status:
        Relationship status (``"Joined"``, ``"Not Joined"``, ``"Extended"``).
    url:
        Advertiser's programme URL.
    raw:
        Original API response payload.
    """

    advertiser_id: str
    name: str = ""
    category: str = ""
    network_rank: int = 0
    seven_day_epc: float = 0.0
    three_month_epc: float = 0.0
    commission_terms: str = ""
    cookie_days: int = 30
    status: str = ""
    url: str = ""
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass
class CJLink:
    """A single affiliate link record from CJ's link search API.

    Attributes
    ----------
    link_id:
        CJ-assigned link identifier.
    advertiser_id:
        Parent advertiser identifier.
    advertiser_name:
        Advertiser display name.
    link_name:
        Descriptive name of the link creative.
    link_type:
        Type of creative (``"Text Link"``, ``"Banner"``, ``"Content"``).
    destination_url:
        Landing page URL.
    click_url:
        CJ click-tracking URL.
    description:
        Link description text.
    promotion_type:
        Promotion classification (``"coupon"``, ``"product"``, ``"general"``).
    promotion_start:
        Start date of the promotion (if applicable).
    promotion_end:
        End date of the promotion (if applicable).
    """

    link_id: str
    advertiser_id: str = ""
    advertiser_name: str = ""
    link_name: str = ""
    link_type: str = "Text Link"
    destination_url: str = ""
    click_url: str = ""
    description: str = ""
    promotion_type: str = ""
    promotion_start: Optional[datetime] = None
    promotion_end: Optional[datetime] = None


@dataclass
class CJCommission:
    """A single commission transaction from CJ's commission detail report.

    Attributes
    ----------
    commission_id:
        Unique commission identifier.
    advertiser_id:
        Advertiser that generated the commission.
    advertiser_name:
        Display name of the advertiser.
    event_date:
        UTC datetime when the action occurred.
    commission_amount:
        Payout amount in the account currency.
    sale_amount:
        Total order/sale value.
    currency:
        ISO 4217 currency code.
    status:
        Commission status (``"received"``, ``"extended"``, ``"locked"``).
    sid:
        Publisher sub-ID for attribution.
    order_id:
        Merchant's order reference number.
    """

    commission_id: str
    advertiser_id: str = ""
    advertiser_name: str = ""
    event_date: Optional[datetime] = None
    commission_amount: float = 0.0
    sale_amount: float = 0.0
    currency: str = "USD"
    status: str = "received"
    sid: str = ""
    order_id: str = ""


@dataclass
class CJProduct:
    """A product record from CJ's product catalogue search.

    Attributes
    ----------
    product_id:
        Catalogue product identifier.
    name:
        Product name / title.
    advertiser_id:
        Owning advertiser identifier.
    advertiser_name:
        Advertiser display name.
    description:
        Product description.
    price:
        Product price in the catalogue currency.
    currency:
        ISO 4217 currency code.
    image_url:
        Product image URL.
    buy_url:
        CJ-tracked purchase URL.
    category:
        Product category label.
    in_stock:
        Whether the product is currently in stock.
    """

    product_id: str
    name: str = ""
    advertiser_id: str = ""
    advertiser_name: str = ""
    description: str = ""
    price: float = 0.0
    currency: str = "USD"
    image_url: str = ""
    buy_url: str = ""
    category: str = ""
    in_stock: bool = True


# ---------------------------------------------------------------------------
# CJIntegration client
# ---------------------------------------------------------------------------

class CJIntegration:
    """Client for the Commission Junction (CJ Affiliate) REST API.

    Authenticates via a personal access token passed in the
    ``Authorization`` header.  All methods are async-ready and return
    typed dataclass instances.

    Parameters
    ----------
    api_key:
        CJ Affiliate personal access token.
    website_id:
        CJ publisher website/property ID.
    cid:
        CJ company ID (publisher ID).
    timeout:
        HTTP request timeout in seconds.
    max_retries:
        Maximum retry attempts for transient failures.
    """

    def __init__(
        self,
        api_key: str,
        website_id: str,
        cid: str = "",
        timeout: int = DEFAULT_REQUEST_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> None:
        if not api_key:
            raise APIAuthenticationError(
                "CJ API requires an api_key (personal access token)",
            )
        if not website_id:
            raise IntegrationError(
                "CJ integration requires a website_id (publisher property ID)",
            )

        self._api_key = api_key
        self._website_id = website_id
        self._cid = cid
        self._timeout = timeout
        self._max_retries = max_retries
        self._request_count: int = 0
        self._last_request_at: Optional[datetime] = None

        log_event(
            logger,
            "cj.init",
            website_id=website_id,
            has_cid=bool(cid),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_headers(self) -> Dict[str, str]:
        """Return standard request headers with CJ authentication.

        Returns
        -------
        dict[str, str]
            Headers including the Bearer token.
        """
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json",
        }

    def _track_request(self) -> None:
        """Record that an API request was made."""
        self._last_request_at = datetime.now(timezone.utc)
        self._request_count += 1

    @staticmethod
    def _parse_advertiser(data: Dict[str, Any]) -> CJAdvertiser:
        """Parse a single advertiser record from the CJ API response.

        Parameters
        ----------
        data:
            Advertiser dict from the API.

        Returns
        -------
        CJAdvertiser
            Normalised advertiser record.
        """
        return CJAdvertiser(
            advertiser_id=str(data.get("advertiser-id", data.get("advertiserId", ""))),
            name=data.get("advertiser-name", data.get("advertiserName", "")),
            category=data.get("primary-category", data.get("primaryCategory", "")),
            network_rank=int(data.get("network-rank", data.get("networkRank", 0))),
            seven_day_epc=float(data.get("seven-day-epc", data.get("sevenDayEpc", 0.0))),
            three_month_epc=float(data.get("three-month-epc", data.get("threeMonthEpc", 0.0))),
            commission_terms=data.get("actions", {}).get("action", {}).get("name", ""),
            cookie_days=int(data.get("cookie-days", data.get("cookieDays", 30))),
            status=data.get("relationship-status", data.get("relationshipStatus", "")),
            url=data.get("program-url", data.get("programUrl", "")),
            raw=data,
        )

    @staticmethod
    def _parse_link(data: Dict[str, Any]) -> CJLink:
        """Parse a single link record from the CJ link search API.

        Parameters
        ----------
        data:
            Link dict from the API.

        Returns
        -------
        CJLink
            Normalised link record.
        """
        promo_start = None
        promo_end = None
        raw_start = data.get("promotion-start-date", data.get("promotionStartDate"))
        raw_end = data.get("promotion-end-date", data.get("promotionEndDate"))
        if raw_start:
            try:
                promo_start = datetime.fromisoformat(str(raw_start).replace("Z", "+00:00"))
            except (ValueError, TypeError):
                promo_start = None
        if raw_end:
            try:
                promo_end = datetime.fromisoformat(str(raw_end).replace("Z", "+00:00"))
            except (ValueError, TypeError):
                promo_end = None

        return CJLink(
            link_id=str(data.get("link-id", data.get("linkId", ""))),
            advertiser_id=str(data.get("advertiser-id", data.get("advertiserId", ""))),
            advertiser_name=data.get("advertiser-name", data.get("advertiserName", "")),
            link_name=data.get("link-name", data.get("linkName", "")),
            link_type=data.get("link-type", data.get("linkType", "Text Link")),
            destination_url=data.get("destination", data.get("destinationUrl", "")),
            click_url=data.get("clickUrl", data.get("click-url", "")),
            description=data.get("description", ""),
            promotion_type=data.get("promotion-type", data.get("promotionType", "")),
            promotion_start=promo_start,
            promotion_end=promo_end,
        )

    @staticmethod
    def _parse_commission(data: Dict[str, Any]) -> CJCommission:
        """Parse a single commission record from the CJ commissions API.

        Parameters
        ----------
        data:
            Commission dict from the API.

        Returns
        -------
        CJCommission
            Normalised commission record.
        """
        event_date = None
        raw_date = data.get("event-date", data.get("eventDate"))
        if raw_date:
            try:
                event_date = datetime.fromisoformat(str(raw_date).replace("Z", "+00:00"))
            except (ValueError, TypeError):
                event_date = None

        return CJCommission(
            commission_id=str(data.get("commission-id", data.get("commissionId", ""))),
            advertiser_id=str(data.get("advertiser-id", data.get("advertiserId", ""))),
            advertiser_name=data.get("advertiser-name", data.get("advertiserName", "")),
            event_date=event_date,
            commission_amount=float(data.get("commission-amount", data.get("commissionAmount", 0.0))),
            sale_amount=float(data.get("sale-amount", data.get("saleAmount", 0.0))),
            currency=data.get("currency", "USD"),
            status=data.get("action-status", data.get("actionStatus", "received")),
            sid=data.get("sid", ""),
            order_id=data.get("order-id", data.get("orderId", "")),
        )

    @staticmethod
    def _parse_product(data: Dict[str, Any]) -> CJProduct:
        """Parse a single product record from the CJ product search API.

        Parameters
        ----------
        data:
            Product dict from the API.

        Returns
        -------
        CJProduct
            Normalised product record.
        """
        return CJProduct(
            product_id=str(data.get("ad-id", data.get("adId", data.get("id", "")))),
            name=data.get("name", data.get("title", "")),
            advertiser_id=str(data.get("advertiser-id", data.get("advertiserId", ""))),
            advertiser_name=data.get("advertiser-name", data.get("advertiserName", "")),
            description=data.get("description", ""),
            price=float(data.get("price", data.get("salePrice", 0.0))),
            currency=data.get("currency", "USD"),
            image_url=data.get("image-url", data.get("imageUrl", "")),
            buy_url=data.get("buy-url", data.get("buyUrl", "")),
            category=data.get("advertiser-category", data.get("advertiserCategory", "")),
            in_stock=data.get("in-stock", data.get("inStock", True)),
        )

    # ------------------------------------------------------------------
    # Public API methods
    # ------------------------------------------------------------------

    async def get_advertisers(
        self,
        *,
        category: str = "",
        advertiser_name: str = "",
        status: str = "joined",
        page: int = 1,
        page_size: int = 100,
    ) -> List[CJAdvertiser]:
        """Retrieve advertisers from the CJ advertiser lookup API.

        Parameters
        ----------
        category:
            Optional category filter.
        advertiser_name:
            Optional advertiser name search filter.
        status:
            Relationship status filter.  Defaults to ``"joined"``
            (only show programmes you have been accepted into).
        page:
            Page number (1-based).
        page_size:
            Results per page (max 100).

        Returns
        -------
        list[CJAdvertiser]
            Matching advertiser records.

        Raises
        ------
        IntegrationError
            If the API request fails.
        """
        url = f"{_ADVERTISER_API}/v3/advertiser-lookup"
        params: Dict[str, Any] = {
            "requestor-type": "publisher",
            "website-id": self._website_id,
            "relationship-status": status,
            "page-number": max(page, 1),
            "records-per-page": min(page_size, 100),
        }
        if category:
            params["advertiser-category"] = category
        if advertiser_name:
            params["keywords"] = advertiser_name

        log_event(
            logger,
            "cj.get_advertisers",
            category=category,
            status=status,
            page=page,
        )
        self._track_request()

        self._build_headers()
        logger.debug("CJ GET %s with %d params", url, len(params))

        # Production: async HTTP GET, parse advertiser records from XML/JSON.
        # advertisers = response_data.get("advertisers", {}).get("advertiser", [])
        # return [self._parse_advertiser(a) for a in advertisers]
        return []

    async def get_links(
        self,
        *,
        advertiser_id: str = "",
        link_type: str = "",
        promotion_type: str = "",
        page: int = 1,
        page_size: int = 100,
    ) -> List[CJLink]:
        """Search for affiliate links from CJ advertisers.

        Parameters
        ----------
        advertiser_id:
            Optional filter to a specific advertiser.
        link_type:
            Optional link type filter (``"Text Link"``, ``"Banner"``).
        promotion_type:
            Optional promotion type filter (``"coupon"``, ``"product"``).
        page:
            Page number (1-based).
        page_size:
            Results per page.

        Returns
        -------
        list[CJLink]
            Matching affiliate link records.

        Raises
        ------
        IntegrationError
            If the API request fails.
        """
        url = f"{_LINK_API}/v2/link-search"
        params: Dict[str, Any] = {
            "website-id": self._website_id,
            "page-number": max(page, 1),
            "records-per-page": min(page_size, 100),
        }
        if advertiser_id:
            params["advertiser-ids"] = advertiser_id
        if link_type:
            params["link-type"] = link_type
        if promotion_type:
            params["promotion-type"] = promotion_type

        log_event(
            logger,
            "cj.get_links",
            advertiser_id=advertiser_id or "all",
            link_type=link_type or "all",
            page=page,
        )
        self._track_request()

        self._build_headers()
        logger.debug("CJ GET %s", url)

        # Production: parse link records from response.
        return []

    async def get_commissions(
        self,
        *,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        advertiser_id: str = "",
        page: int = 1,
        page_size: int = 100,
    ) -> List[CJCommission]:
        """Retrieve commission transaction records from CJ.

        Parameters
        ----------
        start_date:
            Start of the date range (UTC).  Required by CJ API.
        end_date:
            End of the date range (UTC).  Required by CJ API.
        advertiser_id:
            Optional advertiser filter.
        page:
            Page number (1-based).
        page_size:
            Results per page.

        Returns
        -------
        list[CJCommission]
            Commission transaction records.

        Raises
        ------
        IntegrationError
            If required date parameters are missing or the API fails.
        """
        if not start_date or not end_date:
            raise IntegrationError(
                "CJ commissions API requires both start_date and end_date",
                details={"has_start": bool(start_date), "has_end": bool(end_date)},
            )

        url = f"{_BASE_URL}/query"
        params: Dict[str, Any] = {
            "date-type": "event",
            "start-date": start_date.strftime("%Y-%m-%d"),
            "end-date": end_date.strftime("%Y-%m-%d"),
            "page-number": max(page, 1),
            "records-per-page": min(page_size, 1000),
        }
        if advertiser_id:
            params["advertiser-ids"] = advertiser_id
        if self._cid:
            params["cids"] = self._cid

        log_event(
            logger,
            "cj.get_commissions",
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            advertiser_id=advertiser_id or "all",
        )
        self._track_request()

        self._build_headers()
        logger.debug("CJ GET %s with date range %s to %s", url,
                      start_date.isoformat(), end_date.isoformat())

        # Production: parse commission records from response.
        return []

    async def search_products(
        self,
        keywords: str,
        *,
        advertiser_id: str = "",
        category: str = "",
        low_price: Optional[float] = None,
        high_price: Optional[float] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> List[CJProduct]:
        """Search the CJ product catalogue.

        Parameters
        ----------
        keywords:
            Search query string.
        advertiser_id:
            Optional advertiser filter.
        category:
            Optional category filter.
        low_price:
            Minimum price filter.
        high_price:
            Maximum price filter.
        page:
            Page number (1-based).
        page_size:
            Results per page (max 50 for product search).

        Returns
        -------
        list[CJProduct]
            Matching product records.

        Raises
        ------
        IntegrationError
            If the API request fails.
        """
        if not keywords:
            raise IntegrationError(
                "CJ product search requires a non-empty keywords parameter"
            )

        url = f"{_PRODUCT_API}/v2/product-search"
        params: Dict[str, Any] = {
            "website-id": self._website_id,
            "keywords": keywords,
            "page-number": max(page, 1),
            "records-per-page": min(page_size, 50),
        }
        if advertiser_id:
            params["advertiser-ids"] = advertiser_id
        if category:
            params["advertiser-category"] = category
        if low_price is not None:
            params["low-price"] = str(low_price)
        if high_price is not None:
            params["high-price"] = str(high_price)

        log_event(
            logger,
            "cj.search_products",
            keywords=keywords,
            advertiser_id=advertiser_id or "all",
            page=page,
        )
        self._track_request()

        self._build_headers()
        logger.debug("CJ GET %s for keywords=%r", url, keywords)

        # Production: parse product records from response.
        return []

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def request_count(self) -> int:
        """Return the total number of API requests made by this instance."""
        return self._request_count

    def __repr__(self) -> str:
        return (
            f"CJIntegration(website_id={self._website_id!r}, "
            f"requests={self._request_count})"
        )
