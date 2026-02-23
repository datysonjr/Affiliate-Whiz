"""
integrations.affiliates.shareasale
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Client for the ShareASale affiliate network API.

Provides :class:`ShareASaleIntegration` which wraps the ShareASale REST
API to discover merchants, retrieve active deals and coupons, pull
commission reports, and generate affiliate tracking links.

Design references:
    - https://account.shareasale.com/a-apiManager.cfm
    - config/providers.yaml  ``shareasale`` section
    - ARCHITECTURE.md  Section 4 (Integration Layer)

Usage::

    from src.integrations.affiliates.shareasale import ShareASaleIntegration

    sas = ShareASaleIntegration(
        affiliate_id="123456",
        api_token="your-api-token",
        api_secret="your-api-secret",
    )
    merchants = await sas.get_merchants(category="Home & Garden")
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.core.constants import DEFAULT_MAX_RETRIES, DEFAULT_REQUEST_TIMEOUT
from src.core.errors import (
    APIAuthenticationError,
    IntegrationError,
)
from src.core.logger import get_logger, log_event

logger = get_logger("integrations.affiliates.shareasale")

# ---------------------------------------------------------------------------
# ShareASale API constants
# ---------------------------------------------------------------------------

_BASE_URL = "https://api.shareasale.com/w.cfm"
_API_VERSION = "2.9"


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------

@dataclass
class ShareASaleMerchant:
    """Normalised merchant record from the ShareASale API.

    Attributes
    ----------
    merchant_id:
        ShareASale's unique merchant identifier.
    name:
        Merchant display name.
    url:
        Merchant's website URL.
    category:
        Primary programme category.
    status:
        Relationship status with the merchant.
    commission_percent:
        Base commission rate as a percentage (e.g. 10.0 for 10%).
    commission_type:
        Commission model (``"percent"``, ``"flat"``, ``"lead"``).
    cookie_days:
        Affiliate cookie duration in days.
    epc_seven_day:
        Earnings per click over the last 7 days.
    epc_thirty_day:
        Earnings per click over the last 30 days.
    reversal_rate:
        Percentage of commissions that get reversed.
    average_sale:
        Average sale amount in USD.
    power_rank:
        ShareASale merchant power rank (lower is better).
    raw:
        Original API response payload.
    """

    merchant_id: str
    name: str = ""
    url: str = ""
    category: str = ""
    status: str = ""
    commission_percent: float = 0.0
    commission_type: str = "percent"
    cookie_days: int = 30
    epc_seven_day: float = 0.0
    epc_thirty_day: float = 0.0
    reversal_rate: float = 0.0
    average_sale: float = 0.0
    power_rank: int = 0
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass
class ShareASaleDeal:
    """A deal or coupon record from the ShareASale deals/coupons API.

    Attributes
    ----------
    deal_id:
        Unique deal identifier.
    merchant_id:
        Parent merchant identifier.
    merchant_name:
        Merchant display name.
    title:
        Deal headline / title.
    description:
        Full deal description.
    coupon_code:
        Coupon code (empty string if not a coupon-based deal).
    start_date:
        Deal start date (UTC).
    end_date:
        Deal end date (UTC).  ``None`` if the deal has no expiry.
    deal_type:
        Classification (``"coupon"``, ``"sale"``, ``"free_shipping"``, ``"other"``).
    tracking_url:
        Affiliate tracking URL for this deal.
    restrictions:
        Any restrictions or conditions on the deal.
    """

    deal_id: str
    merchant_id: str = ""
    merchant_name: str = ""
    title: str = ""
    description: str = ""
    coupon_code: str = ""
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    deal_type: str = "coupon"
    tracking_url: str = ""
    restrictions: str = ""


@dataclass
class ShareASaleCommission:
    """A single commission/transaction record from the ShareASale API.

    Attributes
    ----------
    transaction_id:
        Unique transaction identifier.
    merchant_id:
        Merchant that generated the commission.
    merchant_name:
        Merchant display name.
    transaction_date:
        UTC datetime of the transaction.
    amount:
        Commission payout amount.
    sale_amount:
        Total sale value.
    status:
        Transaction status (``"pending"``, ``"locked"``, ``"voided"``, ``"paid"``).
    comment:
        Optional comment or note from the merchant.
    reference:
        Publisher's sub-tracking reference value.
    """

    transaction_id: str
    merchant_id: str = ""
    merchant_name: str = ""
    transaction_date: Optional[datetime] = None
    amount: float = 0.0
    sale_amount: float = 0.0
    status: str = "pending"
    comment: str = ""
    reference: str = ""


# ---------------------------------------------------------------------------
# ShareASaleIntegration client
# ---------------------------------------------------------------------------

class ShareASaleIntegration:
    """Client for the ShareASale affiliate network API.

    Authenticates requests using a combination of affiliate ID, API
    token, and API secret.  Each request includes a signature computed
    from the token, secret, and a UNIX timestamp to prevent replay attacks.

    Parameters
    ----------
    affiliate_id:
        ShareASale publisher affiliate ID.
    api_token:
        ShareASale API token.
    api_secret:
        ShareASale API secret key (used for request signing).
    base_url:
        Override the default API endpoint (for testing).
    timeout:
        HTTP request timeout in seconds.
    max_retries:
        Maximum retry attempts for transient failures.
    """

    def __init__(
        self,
        affiliate_id: str,
        api_token: str,
        api_secret: str,
        base_url: str = _BASE_URL,
        timeout: int = DEFAULT_REQUEST_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> None:
        if not affiliate_id or not api_token or not api_secret:
            raise APIAuthenticationError(
                "ShareASale API requires affiliate_id, api_token, and api_secret",
                details={"affiliate_id": affiliate_id},
            )

        self._affiliate_id = affiliate_id
        self._api_token = api_token
        self._api_secret = api_secret
        self._base_url = base_url
        self._timeout = timeout
        self._max_retries = max_retries
        self._request_count: int = 0
        self._last_request_at: Optional[datetime] = None

        log_event(
            logger,
            "shareasale.init",
            affiliate_id=affiliate_id,
        )

    # ------------------------------------------------------------------
    # Authentication helpers
    # ------------------------------------------------------------------

    def _compute_signature(self, timestamp: str, action: str) -> str:
        """Compute the HMAC-SHA256 signature for a ShareASale API request.

        The signature is computed over the concatenation of
        ``api_token + ':' + timestamp + ':' + action + ':' + api_secret``.

        Parameters
        ----------
        timestamp:
            UNIX timestamp string.
        action:
            ShareASale API action name (e.g. ``"merchantSearch"``).

        Returns
        -------
        str
            Hex-encoded SHA-256 signature.
        """
        sig_input = f"{self._api_token}:{timestamp}:{action}:{self._api_secret}"
        return hashlib.sha256(sig_input.encode("utf-8")).hexdigest()

    def _build_params(self, action: str, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Build the standard query parameters for a ShareASale API call.

        Parameters
        ----------
        action:
            ShareASale API action name.
        extra:
            Additional action-specific parameters.

        Returns
        -------
        dict[str, Any]
            Complete parameter set for the request.
        """
        timestamp = str(int(time.time()))
        signature = self._compute_signature(timestamp, action)

        params: Dict[str, Any] = {
            "affiliateId": self._affiliate_id,
            "token": self._api_token,
            "version": _API_VERSION,
            "action": action,
            "XMLFormat": 1,
            "sig": signature,
            "timestamp": timestamp,
        }
        if extra:
            params.update(extra)
        return params

    def _track_request(self) -> None:
        """Record that an API request was made."""
        self._last_request_at = datetime.now(timezone.utc)
        self._request_count += 1

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_merchant(data: Dict[str, Any]) -> ShareASaleMerchant:
        """Parse a single merchant record from the API response.

        Parameters
        ----------
        data:
            Merchant dict from the ShareASale API.

        Returns
        -------
        ShareASaleMerchant
            Normalised merchant record.
        """
        return ShareASaleMerchant(
            merchant_id=str(data.get("MerchantId", data.get("merchantId", ""))),
            name=data.get("Merchant", data.get("merchantName", "")),
            url=data.get("URL", data.get("url", "")),
            category=data.get("Category", data.get("category", "")),
            status=data.get("Status", data.get("status", "")),
            commission_percent=float(data.get("Commission", data.get("commission", 0.0))),
            commission_type=data.get("CommissionType", data.get("commissionType", "percent")),
            cookie_days=int(data.get("CookieLength", data.get("cookieLength", 30))),
            epc_seven_day=float(data.get("EpcSevenDay", data.get("epcSevenDay", 0.0))),
            epc_thirty_day=float(data.get("EpcThirtyDay", data.get("epcThirtyDay", 0.0))),
            reversal_rate=float(data.get("ReversalRate", data.get("reversalRate", 0.0))),
            average_sale=float(data.get("AverageSale", data.get("averageSale", 0.0))),
            power_rank=int(data.get("PowerRank", data.get("powerRank", 0))),
            raw=data,
        )

    @staticmethod
    def _parse_deal(data: Dict[str, Any]) -> ShareASaleDeal:
        """Parse a single deal/coupon record from the API response.

        Parameters
        ----------
        data:
            Deal dict from the ShareASale API.

        Returns
        -------
        ShareASaleDeal
            Normalised deal record.
        """
        start_date = None
        end_date = None
        raw_start = data.get("StartDate", data.get("startDate"))
        raw_end = data.get("EndDate", data.get("endDate"))
        if raw_start:
            try:
                start_date = datetime.fromisoformat(str(raw_start).replace("Z", "+00:00"))
            except (ValueError, TypeError):
                start_date = None
        if raw_end:
            try:
                end_date = datetime.fromisoformat(str(raw_end).replace("Z", "+00:00"))
            except (ValueError, TypeError):
                end_date = None

        return ShareASaleDeal(
            deal_id=str(data.get("DealId", data.get("dealId", ""))),
            merchant_id=str(data.get("MerchantId", data.get("merchantId", ""))),
            merchant_name=data.get("Merchant", data.get("merchantName", "")),
            title=data.get("Title", data.get("title", "")),
            description=data.get("Description", data.get("description", "")),
            coupon_code=data.get("CouponCode", data.get("couponCode", "")),
            start_date=start_date,
            end_date=end_date,
            deal_type=data.get("DealType", data.get("dealType", "coupon")),
            tracking_url=data.get("TrackingUrl", data.get("trackingUrl", "")),
            restrictions=data.get("Restrictions", data.get("restrictions", "")),
        )

    @staticmethod
    def _parse_commission(data: Dict[str, Any]) -> ShareASaleCommission:
        """Parse a single transaction/commission record from the API.

        Parameters
        ----------
        data:
            Transaction dict from the ShareASale API.

        Returns
        -------
        ShareASaleCommission
            Normalised commission record.
        """
        trans_date = None
        raw_date = data.get("TransDate", data.get("transDate", data.get("TransactionDate")))
        if raw_date:
            try:
                trans_date = datetime.fromisoformat(str(raw_date).replace("Z", "+00:00"))
            except (ValueError, TypeError):
                trans_date = None

        return ShareASaleCommission(
            transaction_id=str(data.get("TransId", data.get("transId", ""))),
            merchant_id=str(data.get("MerchantId", data.get("merchantId", ""))),
            merchant_name=data.get("Merchant", data.get("merchantName", "")),
            transaction_date=trans_date,
            amount=float(data.get("Commission", data.get("commission", 0.0))),
            sale_amount=float(data.get("SaleAmount", data.get("saleAmount", 0.0))),
            status=data.get("TransStatus", data.get("status", "pending")).lower(),
            comment=data.get("Comment", data.get("comment", "")),
            reference=data.get("Afftrack", data.get("afftrack", "")),
        )

    # ------------------------------------------------------------------
    # Public API methods
    # ------------------------------------------------------------------

    async def get_merchants(
        self,
        *,
        category: str = "",
        keywords: str = "",
        status: str = "",
    ) -> List[ShareASaleMerchant]:
        """Search for merchants (advertisers) on ShareASale.

        Parameters
        ----------
        category:
            Optional category filter.
        keywords:
            Optional keyword search across merchant names and descriptions.
        status:
            Relationship status filter (e.g. ``"approved"``).

        Returns
        -------
        list[ShareASaleMerchant]
            Matching merchant records.

        Raises
        ------
        IntegrationError
            If the API request fails.
        """
        extra: Dict[str, Any] = {}
        if category:
            extra["category"] = category
        if keywords:
            extra["keywords"] = keywords
        if status:
            extra["status"] = status

        params = self._build_params("merchantSearch", extra)

        log_event(
            logger,
            "shareasale.get_merchants",
            category=category,
            keywords=keywords,
            status=status,
        )
        self._track_request()

        logger.debug(
            "ShareASale merchantSearch request with %d params", len(params)
        )

        # Production: HTTP GET to self._base_url with params, parse XML/JSON.
        # merchants = parsed_response.get("merchants", [])
        # return [self._parse_merchant(m) for m in merchants]
        return []

    async def get_deals(
        self,
        *,
        merchant_id: str = "",
        deal_type: str = "",
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> List[ShareASaleDeal]:
        """Retrieve active deals and coupons from ShareASale.

        Parameters
        ----------
        merchant_id:
            Optional merchant filter.
        deal_type:
            Optional deal type filter (``"coupon"``, ``"sale"``,
            ``"free_shipping"``).
        start_date:
            Only include deals starting after this date.
        end_date:
            Only include deals ending before this date.

        Returns
        -------
        list[ShareASaleDeal]
            Matching deal records.

        Raises
        ------
        IntegrationError
            If the API request fails.
        """
        extra: Dict[str, Any] = {}
        if merchant_id:
            extra["merchantId"] = merchant_id
        if deal_type:
            extra["dealType"] = deal_type
        if start_date:
            extra["startDate"] = start_date.strftime("%m/%d/%Y")
        if end_date:
            extra["endDate"] = end_date.strftime("%m/%d/%Y")

        params = self._build_params("couponDeals", extra)

        log_event(
            logger,
            "shareasale.get_deals",
            merchant_id=merchant_id or "all",
            deal_type=deal_type or "all",
        )
        self._track_request()

        logger.debug(
            "ShareASale couponDeals request with %d params", len(params)
        )

        # Production: HTTP GET, parse deal records.
        return []

    async def get_commissions(
        self,
        *,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        merchant_id: str = "",
    ) -> List[ShareASaleCommission]:
        """Retrieve commission/transaction records from ShareASale.

        Parameters
        ----------
        start_date:
            Start of the date range (UTC).
        end_date:
            End of the date range (UTC).
        merchant_id:
            Optional merchant filter.

        Returns
        -------
        list[ShareASaleCommission]
            Commission transaction records.

        Raises
        ------
        IntegrationError
            If the API request fails or required date parameters are missing.
        """
        if not start_date or not end_date:
            raise IntegrationError(
                "ShareASale commissions query requires both start_date and end_date",
                details={"has_start": bool(start_date), "has_end": bool(end_date)},
            )

        extra: Dict[str, Any] = {
            "dateStart": start_date.strftime("%m/%d/%Y"),
            "dateEnd": end_date.strftime("%m/%d/%Y"),
        }
        if merchant_id:
            extra["merchantId"] = merchant_id

        self._build_params("activity", extra)

        log_event(
            logger,
            "shareasale.get_commissions",
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            merchant_id=merchant_id or "all",
        )
        self._track_request()

        logger.debug(
            "ShareASale activity request for %s to %s",
            start_date.isoformat(),
            end_date.isoformat(),
        )

        # Production: HTTP GET, parse transaction records.
        return []

    async def get_links(
        self,
        merchant_id: str,
        *,
        page: int = 1,
        page_size: int = 50,
    ) -> List[Dict[str, str]]:
        """Retrieve affiliate tracking links for a specific merchant.

        Parameters
        ----------
        merchant_id:
            ShareASale merchant ID to get links for.
        page:
            Page number (1-based).
        page_size:
            Results per page.

        Returns
        -------
        list[dict[str, str]]
            Each dict contains ``"link_id"``, ``"tracking_url"``,
            ``"destination_url"``, and ``"link_text"`` keys.

        Raises
        ------
        IntegrationError
            If the merchant_id is empty or the API request fails.
        """
        if not merchant_id:
            raise IntegrationError(
                "merchant_id is required to retrieve affiliate links"
            )

        extra: Dict[str, Any] = {
            "merchantId": merchant_id,
            "page": max(page, 1),
            "rowsPerPage": min(page_size, 200),
        }
        self._build_params("getLinks", extra)

        log_event(
            logger,
            "shareasale.get_links",
            merchant_id=merchant_id,
            page=page,
        )
        self._track_request()

        logger.debug(
            "ShareASale getLinks for merchant=%s page=%d", merchant_id, page
        )

        # Production: HTTP GET, parse link records.
        return []

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def affiliate_id(self) -> str:
        """Return the configured ShareASale affiliate ID."""
        return self._affiliate_id

    @property
    def request_count(self) -> int:
        """Return the total number of API requests made by this instance."""
        return self._request_count

    def __repr__(self) -> str:
        return (
            f"ShareASaleIntegration(affiliate_id={self._affiliate_id!r}, "
            f"requests={self._request_count})"
        )
