"""
integrations.affiliates.amazon_associates
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Client for the Amazon Product Advertising API (PA-API 5.0).

Provides :class:`AmazonAssociates` which wraps the PA-API to search for
products, retrieve product details, look up commission rate schedules,
and build properly tagged affiliate links that include the associate
tracking tag.

Design references:
    - https://webservices.amazon.com/paapi5/documentation/
    - config/providers.yaml  ``amazon_associates`` section
    - ARCHITECTURE.md  Section 4 (Integration Layer)

Usage::

    from src.integrations.affiliates.amazon_associates import AmazonAssociates

    amazon = AmazonAssociates(
        access_key="AKIAI...",
        secret_key="abc123...",
        partner_tag="mysite-20",
    )
    results = await amazon.search_products("wireless earbuds", category="Electronics")
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

from src.core.constants import DEFAULT_MAX_RETRIES, DEFAULT_REQUEST_TIMEOUT
from src.core.errors import IntegrationError, APIAuthenticationError
from src.core.logger import get_logger, log_event

logger = get_logger("integrations.affiliates.amazon_associates")

# ---------------------------------------------------------------------------
# PA-API constants
# ---------------------------------------------------------------------------

_DEFAULT_REGION = "us-east-1"
_DEFAULT_HOST = "webservices.amazon.com"
_DEFAULT_MARKETPLACE = "www.amazon.com"
_PA_API_SERVICE = "ProductAdvertisingAPI"
_PA_API_VERSION = "v1"
_PA_API_PATH = "/paapi5/"

# Commission rate schedule (approximate, subject to change by Amazon)
_COMMISSION_SCHEDULE: Dict[str, float] = {
    "Luxury Beauty": 0.10,
    "Amazon Coins": 0.10,
    "Digital Music": 0.05,
    "Physical Music": 0.05,
    "Handmade": 0.05,
    "Digital Videos": 0.05,
    "Physical Books": 0.045,
    "Kitchen": 0.045,
    "Automotive": 0.045,
    "Electronics": 0.04,
    "Amazon Fresh": 0.03,
    "Grocery": 0.03,
    "Health & Personal Care": 0.03,
    "Baby Products": 0.03,
    "Sports & Outdoors": 0.03,
    "Home": 0.03,
    "Toys": 0.03,
    "Furniture": 0.03,
    "Apparel": 0.04,
    "Shoes": 0.04,
    "Jewelry": 0.04,
    "Watches": 0.04,
    "Luggage": 0.04,
    "Tools & Home Improvement": 0.03,
    "Computers": 0.025,
    "TV & Video": 0.02,
    "Video Games": 0.02,
    "PC": 0.025,
    "Software": 0.025,
    "Pet Supplies": 0.03,
    "Lawn & Garden": 0.03,
    "default": 0.03,
}


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------

@dataclass
class AmazonProduct:
    """Normalised product record returned by PA-API search or detail calls.

    Attributes
    ----------
    asin:
        Amazon Standard Identification Number (10-character unique ID).
    title:
        Product title.
    url:
        Direct product URL on Amazon (without affiliate tag).
    image_url:
        Primary product image URL.
    price_amount:
        Current price in the marketplace currency (0.0 if unavailable).
    price_currency:
        ISO 4217 currency code (typically ``"USD"``).
    category:
        Primary browse-node category label.
    rating:
        Average customer rating (0.0--5.0).
    review_count:
        Total number of customer reviews.
    is_prime:
        Whether the product is eligible for Prime delivery.
    raw:
        The original PA-API response payload for this item.
    """

    asin: str
    title: str = ""
    url: str = ""
    image_url: str = ""
    price_amount: float = 0.0
    price_currency: str = "USD"
    category: str = ""
    rating: float = 0.0
    review_count: int = 0
    is_prime: bool = False
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass
class CommissionInfo:
    """Commission rate information for a product category.

    Attributes
    ----------
    category:
        Product category name.
    rate:
        Commission rate as a decimal (e.g. 0.04 for 4%).
    is_fixed:
        Whether the rate is a fixed dollar amount rather than a percentage.
    notes:
        Additional context or conditions.
    """

    category: str
    rate: float
    is_fixed: bool = False
    notes: str = ""


# ---------------------------------------------------------------------------
# AmazonAssociates client
# ---------------------------------------------------------------------------

class AmazonAssociates:
    """Integration client for the Amazon Product Advertising API.

    Handles request signing (AWS Signature Version 4), pagination, and
    response normalisation.  All methods are async-ready and return
    strongly-typed dataclass instances.

    Parameters
    ----------
    access_key:
        AWS access key ID authorised for PA-API.
    secret_key:
        Corresponding AWS secret access key.
    partner_tag:
        Amazon Associates tracking tag (e.g. ``"mysite-20"``).
    marketplace:
        Amazon marketplace domain.  Defaults to ``www.amazon.com``.
    region:
        AWS region for the PA-API endpoint.  Defaults to ``us-east-1``.
    timeout:
        HTTP request timeout in seconds.
    max_retries:
        Maximum number of retry attempts for transient failures.
    """

    def __init__(
        self,
        access_key: str,
        secret_key: str,
        partner_tag: str,
        marketplace: str = _DEFAULT_MARKETPLACE,
        region: str = _DEFAULT_REGION,
        timeout: int = DEFAULT_REQUEST_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> None:
        if not access_key or not secret_key:
            raise APIAuthenticationError(
                "Amazon PA-API requires both access_key and secret_key",
                details={"partner_tag": partner_tag},
            )
        if not partner_tag:
            raise IntegrationError(
                "partner_tag is required for Amazon Associates links"
            )

        self._access_key = access_key
        self._secret_key = secret_key
        self._partner_tag = partner_tag
        self._marketplace = marketplace
        self._region = region
        self._host = _DEFAULT_HOST
        self._timeout = timeout
        self._max_retries = max_retries
        self._request_count: int = 0
        self._last_request_at: Optional[datetime] = None

        log_event(
            logger,
            "amazon.init",
            partner_tag=partner_tag,
            marketplace=marketplace,
            region=region,
        )

    # ------------------------------------------------------------------
    # AWS Signature V4 helpers
    # ------------------------------------------------------------------

    def _sign_request(
        self,
        operation: str,
        payload: Dict[str, Any],
        timestamp: datetime,
    ) -> Dict[str, str]:
        """Build AWS Signature Version 4 headers for a PA-API request.

        Parameters
        ----------
        operation:
            PA-API operation name (e.g. ``"SearchItems"``).
        payload:
            JSON-serialisable request body.
        timestamp:
            UTC datetime to use for the signature.

        Returns
        -------
        dict[str, str]
            HTTP headers including ``Authorization``, ``X-Amz-Date``,
            ``X-Amz-Target``, and ``Content-Type``.
        """
        amz_date = timestamp.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = timestamp.strftime("%Y%m%d")
        payload_json = json.dumps(payload, separators=(",", ":"))
        payload_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()

        # Canonical request components
        canonical_uri = f"{_PA_API_PATH}searchitems"
        if operation == "GetItems":
            canonical_uri = f"{_PA_API_PATH}getitems"
        canonical_querystring = ""
        canonical_headers = (
            f"content-type:application/json; charset=utf-8\n"
            f"host:{self._host}\n"
            f"x-amz-date:{amz_date}\n"
            f"x-amz-target:com.amazon.paapi5.v1.ProductAdvertisingAPIv1.{operation}\n"
        )
        signed_headers = "content-type;host;x-amz-date;x-amz-target"

        canonical_request = (
            f"POST\n{canonical_uri}\n{canonical_querystring}\n"
            f"{canonical_headers}\n{signed_headers}\n{payload_hash}"
        )

        # String to sign
        credential_scope = f"{date_stamp}/{self._region}/{_PA_API_SERVICE}/aws4_request"
        string_to_sign = (
            f"AWS4-HMAC-SHA256\n{amz_date}\n{credential_scope}\n"
            f"{hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()}"
        )

        # Signing key derivation
        def _hmac_sha256(key: bytes, msg: str) -> bytes:
            return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

        k_date = _hmac_sha256(f"AWS4{self._secret_key}".encode("utf-8"), date_stamp)
        k_region = _hmac_sha256(k_date, self._region)
        k_service = _hmac_sha256(k_region, _PA_API_SERVICE)
        k_signing = _hmac_sha256(k_service, "aws4_request")

        signature = hmac.new(
            k_signing, string_to_sign.encode("utf-8"), hashlib.sha256
        ).hexdigest()

        authorization = (
            f"AWS4-HMAC-SHA256 Credential={self._access_key}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )

        return {
            "Content-Type": "application/json; charset=utf-8",
            "Host": self._host,
            "X-Amz-Date": amz_date,
            "X-Amz-Target": f"com.amazon.paapi5.v1.ProductAdvertisingAPIv1.{operation}",
            "Authorization": authorization,
        }

    def _track_request(self) -> None:
        """Record that an API request was made for rate-limit awareness."""
        self._last_request_at = datetime.now(timezone.utc)
        self._request_count += 1

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_product(item: Dict[str, Any]) -> AmazonProduct:
        """Parse a single PA-API item result into an :class:`AmazonProduct`.

        Parameters
        ----------
        item:
            A single item dict from the PA-API ``SearchResult.Items``
            or ``ItemsResult.Items`` array.

        Returns
        -------
        AmazonProduct
            Normalised product data.
        """
        asin = item.get("ASIN", "")
        detail_url = item.get("DetailPageURL", "")

        # Item info
        item_info = item.get("ItemInfo", {})
        title = item_info.get("Title", {}).get("DisplayValue", "")
        classifications = item_info.get("Classifications", {})
        category = classifications.get("Binding", {}).get("DisplayValue", "")

        # Images
        images = item.get("Images", {})
        primary_image = images.get("Primary", {})
        image_url = primary_image.get("Large", {}).get("URL", "")
        if not image_url:
            image_url = primary_image.get("Medium", {}).get("URL", "")

        # Offers / pricing
        offers = item.get("Offers", {})
        listings = offers.get("Listings", [])
        price_amount = 0.0
        price_currency = "USD"
        is_prime = False
        if listings:
            first_listing = listings[0]
            price_info = first_listing.get("Price", {})
            price_amount = price_info.get("Amount", 0.0)
            price_currency = price_info.get("Currency", "USD")
            delivery = first_listing.get("DeliveryInfo", {})
            is_prime = delivery.get("IsPrimeEligible", False)

        return AmazonProduct(
            asin=asin,
            title=title,
            url=detail_url,
            image_url=image_url,
            price_amount=price_amount,
            price_currency=price_currency,
            category=category,
            is_prime=is_prime,
            raw=item,
        )

    # ------------------------------------------------------------------
    # Public API methods
    # ------------------------------------------------------------------

    async def search_products(
        self,
        keywords: str,
        *,
        category: str = "",
        min_price: Optional[int] = None,
        max_price: Optional[int] = None,
        sort_by: str = "Relevance",
        item_count: int = 10,
        item_page: int = 1,
    ) -> List[AmazonProduct]:
        """Search for products on Amazon matching the given keywords.

        Calls the PA-API ``SearchItems`` operation and normalises the
        results into :class:`AmazonProduct` instances.

        Parameters
        ----------
        keywords:
            Search query string.
        category:
            Optional Amazon search index (e.g. ``"Electronics"``).
        min_price:
            Minimum price filter in cents (e.g. 1000 = $10.00).
        max_price:
            Maximum price filter in cents.
        sort_by:
            Sort order.  One of ``"Relevance"``, ``"Price:LowToHigh"``,
            ``"Price:HighToLow"``, ``"AvgCustomerReviews"``, ``"NewestArrivals"``.
        item_count:
            Number of results per page (1--10).
        item_page:
            Page number for pagination (1--10).

        Returns
        -------
        list[AmazonProduct]
            Matching products, up to *item_count* entries.

        Raises
        ------
        IntegrationError
            If the PA-API returns an error or the request fails.
        APIRateLimitError
            If the PA-API returns a TooManyRequests response.
        """
        payload: Dict[str, Any] = {
            "PartnerTag": self._partner_tag,
            "PartnerType": "Associates",
            "Marketplace": self._marketplace,
            "Keywords": keywords,
            "Resources": [
                "ItemInfo.Title",
                "ItemInfo.Classifications",
                "Images.Primary.Large",
                "Images.Primary.Medium",
                "Offers.Listings.Price",
                "Offers.Listings.DeliveryInfo.IsPrimeEligible",
            ],
            "SortBy": sort_by,
            "ItemCount": max(1, min(item_count, 10)),
            "ItemPage": max(1, min(item_page, 10)),
        }

        if category:
            payload["SearchIndex"] = category
        if min_price is not None:
            payload["MinPrice"] = min_price
        if max_price is not None:
            payload["MaxPrice"] = max_price

        log_event(
            logger,
            "amazon.search",
            keywords=keywords,
            category=category,
            sort_by=sort_by,
            page=item_page,
        )

        self._track_request()

        # In production, this would use aiohttp to POST to the PA-API endpoint
        # with the signed headers from self._sign_request("SearchItems", payload, ...).
        # For now, we prepare the request structure and return an empty list
        # until the HTTP transport layer is wired in.
        timestamp = datetime.now(timezone.utc)
        self._sign_request("SearchItems", payload, timestamp)
        endpoint = f"https://{self._host}{_PA_API_PATH}searchitems"

        logger.debug(
            "PA-API SearchItems request prepared for endpoint=%s with %d resources",
            endpoint,
            len(payload.get("Resources", [])),
        )

        # Placeholder: return empty until HTTP transport is integrated.
        # Production implementation would be:
        #   async with aiohttp.ClientSession() as session:
        #       async with session.post(endpoint, headers=headers,
        #                               json=payload, timeout=self._timeout) as resp:
        #           data = await resp.json()
        #           items = data.get("SearchResult", {}).get("Items", [])
        #           return [self._parse_product(item) for item in items]
        return []

    async def get_product_details(
        self,
        asins: List[str],
    ) -> List[AmazonProduct]:
        """Retrieve detailed information for one or more products by ASIN.

        Calls the PA-API ``GetItems`` operation.

        Parameters
        ----------
        asins:
            List of Amazon Standard Identification Numbers (max 10 per call).

        Returns
        -------
        list[AmazonProduct]
            Product details for each valid ASIN.

        Raises
        ------
        IntegrationError
            If the PA-API returns an error.
        ValueError
            If more than 10 ASINs are supplied.
        """
        if not asins:
            return []
        if len(asins) > 10:
            raise ValueError(
                f"PA-API GetItems supports at most 10 ASINs per call, got {len(asins)}"
            )

        payload: Dict[str, Any] = {
            "PartnerTag": self._partner_tag,
            "PartnerType": "Associates",
            "Marketplace": self._marketplace,
            "ItemIds": asins,
            "Resources": [
                "ItemInfo.Title",
                "ItemInfo.Classifications",
                "ItemInfo.Features",
                "ItemInfo.ProductInfo",
                "Images.Primary.Large",
                "Images.Primary.Medium",
                "Offers.Listings.Price",
                "Offers.Listings.DeliveryInfo.IsPrimeEligible",
                "CustomerReviews.Count",
                "CustomerReviews.StarRating",
            ],
        }

        log_event(
            logger,
            "amazon.get_details",
            asin_count=len(asins),
            first_asin=asins[0],
        )

        self._track_request()

        timestamp = datetime.now(timezone.utc)
        self._sign_request("GetItems", payload, timestamp)
        endpoint = f"https://{self._host}{_PA_API_PATH}getitems"

        logger.debug(
            "PA-API GetItems request prepared for %d ASINs at endpoint=%s",
            len(asins),
            endpoint,
        )

        # Placeholder: return empty until HTTP transport is integrated.
        return []

    def get_commission_rates(
        self,
        categories: Optional[List[str]] = None,
    ) -> List[CommissionInfo]:
        """Return the current commission rate schedule for product categories.

        Amazon does not expose commission rates via the PA-API, so this
        method uses a locally maintained schedule that mirrors the official
        Amazon Associates commission table.

        Parameters
        ----------
        categories:
            Optional list of category names to filter.  If ``None``,
            all known categories are returned.

        Returns
        -------
        list[CommissionInfo]
            Commission rate information for each requested category.
        """
        results: List[CommissionInfo] = []

        target_categories = categories if categories else list(_COMMISSION_SCHEDULE.keys())

        for category in target_categories:
            rate = _COMMISSION_SCHEDULE.get(
                category, _COMMISSION_SCHEDULE["default"]
            )
            info = CommissionInfo(
                category=category,
                rate=rate,
                is_fixed=False,
                notes=(
                    "Rate sourced from Amazon Associates programme fee schedule. "
                    "Actual rates may vary by product and promotional period."
                ),
            )
            results.append(info)

        log_event(
            logger,
            "amazon.commission_rates",
            categories_requested=len(target_categories),
            categories_resolved=len(results),
        )

        return results

    def build_affiliate_link(
        self,
        url: str,
        *,
        campaign: str = "",
        sub_tag: str = "",
    ) -> str:
        """Append the Associates tracking tag to an Amazon product URL.

        Builds a properly formatted affiliate link that includes the
        partner tag and optional campaign/sub-tag parameters for tracking
        attribution across different content pieces.

        Parameters
        ----------
        url:
            Base Amazon product URL (e.g. ``"https://www.amazon.com/dp/B08N5WRWNW"``).
        campaign:
            Optional campaign identifier appended as ``linkId`` for
            internal attribution tracking.
        sub_tag:
            Optional sub-tag appended as ``ascsubtag`` for granular tracking
            (e.g. article slug, A/B test variant).

        Returns
        -------
        str
            The affiliate-tagged URL.

        Raises
        ------
        IntegrationError
            If the URL is empty or not an Amazon domain.

        Examples
        --------
        >>> amazon.build_affiliate_link("https://www.amazon.com/dp/B08N5WRWNW")
        'https://www.amazon.com/dp/B08N5WRWNW?tag=mysite-20'
        """
        if not url:
            raise IntegrationError("Cannot build affiliate link from empty URL")

        if "amazon." not in url.lower() and "amzn." not in url.lower():
            raise IntegrationError(
                f"URL does not appear to be an Amazon domain: {url}",
                details={"url": url},
            )

        # Determine the separator (? or &)
        separator = "&" if "?" in url else "?"
        tagged_url = f"{url}{separator}tag={quote_plus(self._partner_tag)}"

        if campaign:
            tagged_url += f"&linkId={quote_plus(campaign)}"

        if sub_tag:
            tagged_url += f"&ascsubtag={quote_plus(sub_tag)}"

        log_event(
            logger,
            "amazon.link_built",
            partner_tag=self._partner_tag,
            has_campaign=bool(campaign),
            has_sub_tag=bool(sub_tag),
        )

        return tagged_url

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def partner_tag(self) -> str:
        """Return the configured Associates partner tag."""
        return self._partner_tag

    @property
    def request_count(self) -> int:
        """Return the total number of API requests made by this instance."""
        return self._request_count

    def __repr__(self) -> str:
        return (
            f"AmazonAssociates(tag={self._partner_tag!r}, "
            f"marketplace={self._marketplace!r}, "
            f"requests={self._request_count})"
        )
