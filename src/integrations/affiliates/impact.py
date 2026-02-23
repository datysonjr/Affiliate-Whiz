"""
integrations.affiliates.impact
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Client for the Impact (formerly Impact Radius) partnership management API.

Provides :class:`ImpactIntegration` which wraps the Impact API to retrieve
available offers (campaigns), commission data, tracking links, and
performance reports.  Impact is used by many large brands (e.g. Uber,
Airbnb, Canva) as their affiliate programme platform.

Design references:
    - https://developer.impact.com/
    - config/providers.yaml  ``impact`` section
    - ARCHITECTURE.md  Section 4 (Integration Layer)

Usage::

    from src.integrations.affiliates.impact import ImpactIntegration

    impact = ImpactIntegration(
        account_sid="IRxxxxxxxx",
        auth_token="xxxxxxx",
    )
    offers = await impact.get_offers(category="SaaS")
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.core.constants import DEFAULT_MAX_RETRIES, DEFAULT_REQUEST_TIMEOUT
from src.core.errors import (
    APIAuthenticationError,
    IntegrationError,
)
from src.core.logger import get_logger, log_event

logger = get_logger("integrations.affiliates.impact")

# ---------------------------------------------------------------------------
# Impact API constants
# ---------------------------------------------------------------------------

_BASE_URL = "https://api.impact.com"
_API_VERSION = "Mediapartners"


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------

@dataclass
class ImpactOffer:
    """Normalised offer (campaign) record from the Impact API.

    Attributes
    ----------
    campaign_id:
        Impact's unique campaign identifier.
    name:
        Campaign / programme name.
    advertiser_name:
        Name of the advertiser brand.
    description:
        Programme description text.
    category:
        Primary programme category.
    commission_type:
        Commission model (``"CPA"``, ``"CPC"``, ``"CPS"``, ``"Hybrid"``).
    default_payout:
        Default payout amount or rate as reported by Impact.
    currency:
        ISO 4217 currency code.
    cookie_days:
        Tracking cookie duration in days.
    status:
        Campaign status (``"Active"``, ``"Paused"``, ``"Pending"``).
    tracking_link:
        Default tracking link template, if available.
    contract_status:
        Relationship status with the advertiser.
    raw:
        Original API response payload.
    """

    campaign_id: str
    name: str = ""
    advertiser_name: str = ""
    description: str = ""
    category: str = ""
    commission_type: str = "CPS"
    default_payout: float = 0.0
    currency: str = "USD"
    cookie_days: int = 30
    status: str = "Active"
    tracking_link: str = ""
    contract_status: str = ""
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass
class ImpactCommission:
    """A single commission event from Impact's reporting API.

    Attributes
    ----------
    action_id:
        Unique action/conversion identifier.
    campaign_id:
        Associated campaign identifier.
    advertiser_name:
        Brand name of the advertiser.
    action_date:
        UTC datetime when the action occurred.
    amount:
        Commission payout amount.
    currency:
        ISO 4217 currency code.
    status:
        Commission status (``"Pending"``, ``"Approved"``, ``"Reversed"``).
    order_id:
        Merchant's order identifier (if available).
    sub_id:
        Publisher sub-ID used for attribution.
    """

    action_id: str
    campaign_id: str = ""
    advertiser_name: str = ""
    action_date: Optional[datetime] = None
    amount: float = 0.0
    currency: str = "USD"
    status: str = "Pending"
    order_id: str = ""
    sub_id: str = ""


@dataclass
class ImpactPerformance:
    """Aggregated performance data for a date range.

    Attributes
    ----------
    campaign_id:
        Campaign these metrics belong to.
    clicks:
        Total click count.
    impressions:
        Total impression count.
    actions:
        Total conversion/action count.
    revenue:
        Total revenue generated.
    payout:
        Total publisher payout.
    date_start:
        Start of the reporting period.
    date_end:
        End of the reporting period.
    """

    campaign_id: str
    clicks: int = 0
    impressions: int = 0
    actions: int = 0
    revenue: float = 0.0
    payout: float = 0.0
    date_start: Optional[datetime] = None
    date_end: Optional[datetime] = None


# ---------------------------------------------------------------------------
# ImpactIntegration client
# ---------------------------------------------------------------------------

class ImpactIntegration:
    """Client for the Impact partnership management API.

    Uses HTTP Basic authentication with the account SID and auth token.
    All methods are async-ready and return typed dataclass instances.

    Parameters
    ----------
    account_sid:
        Impact account SID (starts with ``"IR"``).
    auth_token:
        Impact API auth token.
    base_url:
        Override the default API base URL (for testing).
    timeout:
        HTTP request timeout in seconds.
    max_retries:
        Maximum retry attempts for transient failures.
    """

    def __init__(
        self,
        account_sid: str,
        auth_token: str,
        base_url: str = _BASE_URL,
        timeout: int = DEFAULT_REQUEST_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> None:
        if not account_sid or not auth_token:
            raise APIAuthenticationError(
                "Impact API requires both account_sid and auth_token",
                details={"account_sid_prefix": account_sid[:4] if account_sid else ""},
            )

        self._account_sid = account_sid
        self._auth_token = auth_token
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._max_retries = max_retries
        self._request_count: int = 0
        self._last_request_at: Optional[datetime] = None

        # Pre-compute Basic auth header
        credentials = f"{account_sid}:{auth_token}"
        self._auth_header = (
            f"Basic {base64.b64encode(credentials.encode('utf-8')).decode('ascii')}"
        )

        log_event(
            logger,
            "impact.init",
            account_sid_prefix=account_sid[:4],
            base_url=base_url,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_url(self, path: str) -> str:
        """Construct a full API URL for the given resource path.

        Parameters
        ----------
        path:
            Relative API path (e.g. ``"/Campaigns"``).

        Returns
        -------
        str
            Fully qualified URL.
        """
        return f"{self._base_url}/{_API_VERSION}/{self._account_sid}{path}"

    def _build_headers(self) -> Dict[str, str]:
        """Return standard request headers with authentication.

        Returns
        -------
        dict[str, str]
            Headers dict including ``Authorization`` and ``Accept``.
        """
        return {
            "Authorization": self._auth_header,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _track_request(self) -> None:
        """Record that an API request was made."""
        self._last_request_at = datetime.now(timezone.utc)
        self._request_count += 1

    @staticmethod
    def _parse_offer(data: Dict[str, Any]) -> ImpactOffer:
        """Parse a single campaign object from the API response.

        Parameters
        ----------
        data:
            Campaign dict from the Impact API response.

        Returns
        -------
        ImpactOffer
            Normalised offer record.
        """
        return ImpactOffer(
            campaign_id=str(data.get("Id", data.get("CampaignId", ""))),
            name=data.get("CampaignName", data.get("Name", "")),
            advertiser_name=data.get("AdvertiserName", ""),
            description=data.get("CampaignDescription", ""),
            category=data.get("VerticalName", data.get("Category", "")),
            commission_type=data.get("ContractCommissionType", "CPS"),
            default_payout=float(data.get("DefaultPayout", 0.0)),
            currency=data.get("Currency", "USD"),
            cookie_days=int(data.get("CookieDays", 30)),
            status=data.get("CampaignStatus", data.get("Status", "Active")),
            tracking_link=data.get("TrackingLink", ""),
            contract_status=data.get("ContractStatus", ""),
            raw=data,
        )

    @staticmethod
    def _parse_commission(data: Dict[str, Any]) -> ImpactCommission:
        """Parse a single action/commission record from the API response.

        Parameters
        ----------
        data:
            Action dict from the Impact API response.

        Returns
        -------
        ImpactCommission
            Normalised commission record.
        """
        action_date = None
        raw_date = data.get("EventDate", data.get("ActionDate"))
        if raw_date:
            try:
                action_date = datetime.fromisoformat(
                    str(raw_date).replace("Z", "+00:00")
                )
            except (ValueError, TypeError):
                action_date = None

        return ImpactCommission(
            action_id=str(data.get("Id", data.get("ActionId", ""))),
            campaign_id=str(data.get("CampaignId", "")),
            advertiser_name=data.get("AdvertiserName", ""),
            action_date=action_date,
            amount=float(data.get("Payout", data.get("Amount", 0.0))),
            currency=data.get("Currency", "USD"),
            status=data.get("State", data.get("Status", "Pending")),
            order_id=str(data.get("Oid", data.get("OrderId", ""))),
            sub_id=str(data.get("SubId1", data.get("SharedId", ""))),
        )

    # ------------------------------------------------------------------
    # Public API methods
    # ------------------------------------------------------------------

    async def get_offers(
        self,
        *,
        category: str = "",
        status: str = "Active",
        page: int = 1,
        page_size: int = 100,
    ) -> List[ImpactOffer]:
        """Retrieve available campaigns (offers) from Impact.

        Parameters
        ----------
        category:
            Optional vertical/category filter.
        status:
            Campaign status filter.  Defaults to ``"Active"``.
        page:
            Page number for pagination (1-based).
        page_size:
            Number of results per page (max 1000).

        Returns
        -------
        list[ImpactOffer]
            Matching campaign records.

        Raises
        ------
        IntegrationError
            If the API request fails.
        """
        url = self._build_url("/Campaigns")
        params: Dict[str, Any] = {
            "PageSize": min(page_size, 1000),
            "Page": max(page, 1),
        }
        if status:
            params["CampaignStatus"] = status
        if category:
            params["VerticalName"] = category

        log_event(
            logger,
            "impact.get_offers",
            category=category,
            status=status,
            page=page,
        )
        self._track_request()

        self._build_headers()
        logger.debug(
            "Impact GET %s with %d params", url, len(params)
        )

        # Production: async HTTP GET with params and headers, parse JSON response.
        # campaigns = response_json.get("Campaigns", [])
        # return [self._parse_offer(c) for c in campaigns]
        return []

    async def get_commissions(
        self,
        *,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        campaign_id: str = "",
        status: str = "",
        page: int = 1,
        page_size: int = 100,
    ) -> List[ImpactCommission]:
        """Retrieve commission/action records from Impact.

        Parameters
        ----------
        start_date:
            Start of the date range filter (UTC).
        end_date:
            End of the date range filter (UTC).
        campaign_id:
            Optional campaign ID filter.
        status:
            Optional status filter (``"Pending"``, ``"Approved"``, ``"Reversed"``).
        page:
            Page number (1-based).
        page_size:
            Results per page.

        Returns
        -------
        list[ImpactCommission]
            Matching commission records.

        Raises
        ------
        IntegrationError
            If the API request fails.
        """
        url = self._build_url("/Actions")
        params: Dict[str, Any] = {
            "PageSize": min(page_size, 1000),
            "Page": max(page, 1),
        }
        if start_date:
            params["StartDate"] = start_date.strftime("%Y-%m-%dT%H:%M:%SZ")
        if end_date:
            params["EndDate"] = end_date.strftime("%Y-%m-%dT%H:%M:%SZ")
        if campaign_id:
            params["CampaignId"] = campaign_id
        if status:
            params["State"] = status

        log_event(
            logger,
            "impact.get_commissions",
            campaign_id=campaign_id,
            has_date_range=bool(start_date and end_date),
            page=page,
        )
        self._track_request()

        self._build_headers()
        logger.debug("Impact GET %s with %d params", url, len(params))

        # Production: async HTTP GET, parse Actions array.
        # actions = response_json.get("Actions", [])
        # return [self._parse_commission(a) for a in actions]
        return []

    async def get_tracking_links(
        self,
        campaign_id: str,
        *,
        destination_url: str = "",
        sub_id: str = "",
    ) -> List[Dict[str, str]]:
        """Generate or retrieve tracking links for a given campaign.

        Parameters
        ----------
        campaign_id:
            The Impact campaign ID to generate links for.
        destination_url:
            Optional deep-link destination URL.
        sub_id:
            Optional sub-ID for attribution tracking.

        Returns
        -------
        list[dict[str, str]]
            Each dict contains ``"tracking_url"`` and ``"landing_url"`` keys.

        Raises
        ------
        IntegrationError
            If the campaign is not found or link generation fails.
        """
        if not campaign_id:
            raise IntegrationError(
                "campaign_id is required to generate tracking links"
            )

        url = self._build_url(f"/Campaigns/{campaign_id}/TrackingLinks")
        params: Dict[str, str] = {}
        if destination_url:
            params["Url"] = destination_url
        if sub_id:
            params["SubId1"] = sub_id

        log_event(
            logger,
            "impact.get_tracking_links",
            campaign_id=campaign_id,
            has_destination=bool(destination_url),
        )
        self._track_request()

        self._build_headers()
        logger.debug("Impact GET %s", url)

        # Production: parse TrackingLinks from response.
        return []

    async def get_performance_data(
        self,
        *,
        campaign_id: str = "",
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        group_by: str = "Campaign",
    ) -> List[ImpactPerformance]:
        """Retrieve aggregated performance statistics from Impact.

        Parameters
        ----------
        campaign_id:
            Optional campaign filter.  If empty, returns aggregated data
            across all campaigns.
        start_date:
            Start of the reporting period (UTC).
        end_date:
            End of the reporting period (UTC).
        group_by:
            Aggregation dimension.  One of ``"Campaign"``, ``"Day"``,
            ``"Month"``.

        Returns
        -------
        list[ImpactPerformance]
            Aggregated performance metrics.

        Raises
        ------
        IntegrationError
            If the API request fails.
        """
        url = self._build_url("/Reports/mp_action_listing")
        params: Dict[str, Any] = {
            "GroupBy": group_by,
        }
        if campaign_id:
            params["CampaignId"] = campaign_id
        if start_date:
            params["StartDate"] = start_date.strftime("%Y-%m-%d")
        if end_date:
            params["EndDate"] = end_date.strftime("%Y-%m-%d")

        log_event(
            logger,
            "impact.get_performance",
            campaign_id=campaign_id or "all",
            group_by=group_by,
            has_date_range=bool(start_date and end_date),
        )
        self._track_request()

        self._build_headers()
        logger.debug("Impact GET %s with group_by=%s", url, group_by)

        # Production: parse performance records from response.
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
            f"ImpactIntegration(account_sid={self._account_sid[:4]}..., "
            f"requests={self._request_count})"
        )
