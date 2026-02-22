"""
domains.offers.sources.scraping_sources
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Web scraping source for discovering affiliate offer data directly from
merchant websites when API access is unavailable or when enriching
existing offer records with live pricing and product details.

Uses HTTP requests with configurable rate-limiting and rotating user
agents to scrape merchant pages, extract product catalogues, and pull
current pricing information.

Design references:
    - ARCHITECTURE.md  Section 3 (Pipeline Architecture -- Offer Discovery)
    - AI_RULES.md      Ethical scraping guidelines
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

from src.core.constants import DEFAULT_REQUEST_TIMEOUT, DEFAULT_USER_AGENT
from src.core.errors import IntegrationError
from src.core.logger import get_logger

# ---------------------------------------------------------------------------
# Optional dependency: requests / BeautifulSoup
# ---------------------------------------------------------------------------
try:
    import requests  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    requests = None  # type: ignore[assignment]

try:
    from bs4 import BeautifulSoup  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    BeautifulSoup = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------

@dataclass
class ScrapedProduct:
    """Product data extracted from a merchant web page.

    Attributes
    ----------
    name:
        Product or offer name as displayed on the page.
    price:
        Current price in the merchant's default currency.
    original_price:
        Original / list price before discounts (``0.0`` if not on sale).
    currency:
        ISO 4217 currency code (default ``"USD"``).
    description:
        Short product description extracted from the page.
    image_url:
        URL of the primary product image.
    url:
        Canonical URL of the product page.
    category:
        Category or breadcrumb path extracted from page structure.
    in_stock:
        Whether the product appears to be in stock.
    sku:
        SKU or model number if found on the page.
    rating:
        Average customer rating (0.0--5.0 scale), or ``None``.
    review_count:
        Number of customer reviews, or ``None``.
    scraped_at:
        UTC timestamp when the data was collected.
    raw_html_hash:
        SHA-256 hash of the raw HTML for change-detection.
    metadata:
        Additional key-value data extracted from structured markup.
    """

    name: str
    price: float = 0.0
    original_price: float = 0.0
    currency: str = "USD"
    description: str = ""
    image_url: str = ""
    url: str = ""
    category: str = ""
    in_stock: bool = True
    sku: str = ""
    rating: Optional[float] = None
    review_count: Optional[int] = None
    scraped_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    raw_html_hash: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PricingData:
    """Extracted pricing information for a single product.

    Attributes
    ----------
    price:
        Current selling price.
    original_price:
        Pre-discount / list price (``0.0`` if not discounted).
    currency:
        ISO 4217 currency code.
    discount_percent:
        Computed discount percentage (``0.0`` if not on sale).
    price_text:
        Raw price string as it appeared on the page.
    """

    price: float = 0.0
    original_price: float = 0.0
    currency: str = "USD"
    discount_percent: float = 0.0
    price_text: str = ""

    def compute_discount(self) -> float:
        """Calculate and store the discount percentage.

        Returns
        -------
        float
            Discount as a percentage (e.g. ``25.0`` for 25 % off).
        """
        if self.original_price > 0 and self.price < self.original_price:
            self.discount_percent = round(
                ((self.original_price - self.price) / self.original_price) * 100, 2
            )
        else:
            self.discount_percent = 0.0
        return self.discount_percent


# ---------------------------------------------------------------------------
# Scraping source
# ---------------------------------------------------------------------------

class ScrapingSource:
    """Scrape affiliate offer data directly from merchant websites.

    Provides methods to fetch merchant pages, extract product catalogues,
    and parse pricing details.  Designed to complement API-based sources
    when a network does not expose the data OpenClaw needs.

    Rate limiting is enforced via a configurable minimum delay between
    requests to the same domain.  ``robots.txt`` compliance is the
    caller's responsibility.

    Parameters
    ----------
    user_agent:
        HTTP User-Agent header value.  Defaults to the OpenClaw UA string.
    timeout:
        Per-request timeout in seconds.
    min_request_interval:
        Minimum seconds between consecutive requests to the same domain.
    max_retries:
        Number of retry attempts for transient HTTP errors.
    headers:
        Additional HTTP headers merged into every request.
    """

    def __init__(
        self,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout: int = DEFAULT_REQUEST_TIMEOUT,
        min_request_interval: float = 2.0,
        max_retries: int = 2,
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        if requests is None:
            raise IntegrationError(
                "The 'requests' package is required for ScrapingSource. "
                "Install it with: pip install requests"
            )
        if BeautifulSoup is None:
            raise IntegrationError(
                "The 'beautifulsoup4' package is required for ScrapingSource. "
                "Install it with: pip install beautifulsoup4"
            )

        self.user_agent = user_agent
        self.timeout = timeout
        self.min_request_interval = min_request_interval
        self.max_retries = max_retries
        self.logger: logging.Logger = get_logger("offers.sources.scraping")

        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        })
        if headers:
            self._session.headers.update(headers)

        # Per-domain timestamps for rate-limit enforcement
        self._domain_last_request: Dict[str, float] = {}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _enforce_rate_limit(self, url: str) -> None:
        """Sleep if necessary to respect the minimum request interval for a domain.

        Parameters
        ----------
        url:
            The URL about to be fetched.
        """
        domain = urlparse(url).netloc
        last_ts = self._domain_last_request.get(domain, 0.0)
        elapsed = time.monotonic() - last_ts
        if elapsed < self.min_request_interval:
            sleep_time = self.min_request_interval - elapsed
            self.logger.debug(
                "Rate-limiting: sleeping %.2fs before requesting %s", sleep_time, domain
            )
            time.sleep(sleep_time)
        self._domain_last_request[domain] = time.monotonic()

    def _fetch_html(self, url: str) -> str:
        """Fetch the raw HTML content of a URL with retry logic.

        Parameters
        ----------
        url:
            Fully qualified URL to fetch.

        Returns
        -------
        str
            Raw HTML response body.

        Raises
        ------
        IntegrationError
            If the page cannot be fetched after all retry attempts.
        """
        self._enforce_rate_limit(url)
        last_exc: Optional[Exception] = None

        for attempt in range(1, self.max_retries + 2):
            try:
                response = self._session.get(url, timeout=self.timeout)
                response.raise_for_status()
                self.logger.debug(
                    "Fetched %s (status=%d, size=%d bytes)",
                    url,
                    response.status_code,
                    len(response.content),
                )
                return response.text
            except Exception as exc:
                last_exc = exc
                if attempt <= self.max_retries:
                    delay = 2.0 ** attempt
                    self.logger.warning(
                        "Request to %s failed (attempt %d/%d): %s -- retrying in %.1fs",
                        url,
                        attempt,
                        self.max_retries + 1,
                        exc,
                        delay,
                    )
                    time.sleep(delay)

        raise IntegrationError(
            f"Failed to fetch {url} after {self.max_retries + 1} attempts",
            details={"url": url, "last_error": str(last_exc)},
            cause=last_exc if isinstance(last_exc, Exception) else None,
        )

    @staticmethod
    def _html_hash(html: str) -> str:
        """Return a SHA-256 hex digest of the HTML content for change detection."""
        return hashlib.sha256(html.encode("utf-8")).hexdigest()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scrape_merchant_page(
        self,
        url: str,
        *,
        css_selectors: Optional[Dict[str, str]] = None,
    ) -> List[ScrapedProduct]:
        """Scrape product listings from a merchant page.

        Fetches the HTML, parses the DOM, and extracts product data using
        common e-commerce patterns.  Custom CSS selectors can be supplied
        for sites whose markup does not match the built-in heuristics.

        Parameters
        ----------
        url:
            URL of the merchant catalogue or product listing page.
        css_selectors:
            Optional mapping of field names to CSS selectors that override
            the default extraction logic.  Supported keys: ``product_card``,
            ``name``, ``price``, ``original_price``, ``image``, ``link``,
            ``description``.

        Returns
        -------
        list[ScrapedProduct]
            Extracted product records.  May be empty if no products are
            detected on the page.

        Raises
        ------
        IntegrationError
            If the page cannot be fetched.
        """
        html = self._fetch_html(url)
        soup = BeautifulSoup(html, "html.parser")
        html_hash = self._html_hash(html)

        selectors = css_selectors or {}
        card_selector = selectors.get(
            "product_card",
            "[class*='product'], [class*='item'], [data-product-id]",
        )

        products: List[ScrapedProduct] = []
        cards = soup.select(card_selector)

        if not cards:
            self.logger.info("No product cards found on %s with selector '%s'", url, card_selector)
            return products

        for card in cards:
            try:
                product = self._parse_product_card(card, url, selectors, html_hash)
                if product.name:
                    products.append(product)
            except Exception as exc:
                self.logger.debug("Failed to parse product card: %s", exc)
                continue

        self.logger.info("Extracted %d products from %s", len(products), url)
        return products

    def _parse_product_card(
        self,
        card: Any,
        base_url: str,
        selectors: Dict[str, str],
        html_hash: str,
    ) -> ScrapedProduct:
        """Parse a single product card element into a ScrapedProduct.

        Parameters
        ----------
        card:
            BeautifulSoup Tag representing a product card.
        base_url:
            Base URL for resolving relative links.
        selectors:
            Custom CSS selectors for field extraction.
        html_hash:
            Pre-computed hash of the full page HTML.

        Returns
        -------
        ScrapedProduct
            The extracted product data.
        """
        # Name
        name_el = card.select_one(selectors.get("name", "h2, h3, h4, [class*='title'], [class*='name']"))
        name = name_el.get_text(strip=True) if name_el else ""

        # Price
        price_el = card.select_one(selectors.get("price", "[class*='price'], .price, [data-price]"))
        price = self._parse_price_text(price_el.get_text(strip=True)) if price_el else 0.0

        # Original price (for detecting discounts)
        orig_el = card.select_one(selectors.get(
            "original_price",
            "[class*='original'], [class*='was'], [class*='list-price'], s, del",
        ))
        original_price = self._parse_price_text(orig_el.get_text(strip=True)) if orig_el else 0.0

        # Image
        img_el = card.select_one(selectors.get("image", "img"))
        image_url = ""
        if img_el:
            image_url = img_el.get("src", "") or img_el.get("data-src", "") or ""
            if image_url and not image_url.startswith("http"):
                image_url = urljoin(base_url, image_url)

        # Link
        link_el = card.select_one(selectors.get("link", "a[href]"))
        product_url = ""
        if link_el:
            href = link_el.get("href", "")
            product_url = urljoin(base_url, href) if href else ""

        # Description
        desc_el = card.select_one(selectors.get("description", "[class*='desc'], p"))
        description = desc_el.get_text(strip=True) if desc_el else ""

        return ScrapedProduct(
            name=name,
            price=price,
            original_price=original_price,
            description=description,
            image_url=image_url,
            url=product_url,
            raw_html_hash=html_hash,
        )

    def extract_product_data(
        self,
        url: str,
    ) -> ScrapedProduct:
        """Extract detailed product data from a single product page.

        Unlike :meth:`scrape_merchant_page` which handles listing pages,
        this method targets individual product detail pages and extracts
        richer information including ratings, reviews, SKU, and structured
        data (JSON-LD / microdata).

        Parameters
        ----------
        url:
            URL of an individual product page.

        Returns
        -------
        ScrapedProduct
            Fully populated product record.

        Raises
        ------
        IntegrationError
            If the page cannot be fetched.
        """
        html = self._fetch_html(url)
        soup = BeautifulSoup(html, "html.parser")
        html_hash = self._html_hash(html)

        product = ScrapedProduct(name="", url=url, raw_html_hash=html_hash)

        # -- Extract from JSON-LD structured data (most reliable) --
        jsonld_data = self._extract_jsonld_product(soup)
        if jsonld_data:
            product.name = jsonld_data.get("name", "")
            product.description = jsonld_data.get("description", "")
            product.sku = jsonld_data.get("sku", "")
            product.image_url = self._extract_jsonld_image(jsonld_data)

            # Pricing from JSON-LD offers
            offers = jsonld_data.get("offers", {})
            if isinstance(offers, list) and offers:
                offers = offers[0]
            if isinstance(offers, dict):
                product.price = self._safe_float(offers.get("price", 0))
                product.currency = offers.get("priceCurrency", "USD")
                availability = offers.get("availability", "")
                product.in_stock = "InStock" in str(availability)

            # Rating from JSON-LD
            aggregate_rating = jsonld_data.get("aggregateRating", {})
            if isinstance(aggregate_rating, dict):
                product.rating = self._safe_float(aggregate_rating.get("ratingValue"))
                product.review_count = self._safe_int(aggregate_rating.get("reviewCount"))

        # -- Fallback: extract from HTML if JSON-LD was incomplete --
        if not product.name:
            title_el = soup.select_one(
                "h1, [class*='product-title'], [class*='product-name'], [itemprop='name']"
            )
            product.name = title_el.get_text(strip=True) if title_el else ""

        if product.price == 0.0:
            pricing = self.extract_pricing(url, _soup=soup)
            product.price = pricing.price
            product.original_price = pricing.original_price
            product.currency = pricing.currency

        if not product.description:
            desc_el = soup.select_one(
                "[itemprop='description'], [class*='product-description'], "
                "[class*='description'], #product-description"
            )
            if desc_el:
                product.description = desc_el.get_text(strip=True)[:500]

        # -- Category from breadcrumbs --
        breadcrumb = soup.select("[class*='breadcrumb'] a, [itemtype*='BreadcrumbList'] a")
        if breadcrumb:
            crumbs = [a.get_text(strip=True) for a in breadcrumb if a.get_text(strip=True)]
            product.category = " > ".join(crumbs)

        self.logger.info("Extracted product data from %s: %s", url, product.name)
        return product

    def extract_pricing(
        self,
        url: str,
        *,
        _soup: Optional[Any] = None,
    ) -> PricingData:
        """Extract pricing information from a product or offer page.

        Parses the page for price elements using common CSS patterns and
        structured data markup.

        Parameters
        ----------
        url:
            URL of the product page (fetched only if ``_soup`` is not provided).
        _soup:
            Pre-parsed BeautifulSoup object (internal use to avoid re-fetching).

        Returns
        -------
        PricingData
            Extracted pricing details.

        Raises
        ------
        IntegrationError
            If the page cannot be fetched.
        """
        if _soup is None:
            html = self._fetch_html(url)
            _soup = BeautifulSoup(html, "html.parser")

        pricing = PricingData()

        # Strategy 1: JSON-LD structured data
        jsonld = self._extract_jsonld_product(_soup)
        if jsonld:
            offers = jsonld.get("offers", {})
            if isinstance(offers, list) and offers:
                offers = offers[0]
            if isinstance(offers, dict):
                pricing.price = self._safe_float(offers.get("price", 0))
                pricing.currency = offers.get("priceCurrency", "USD")

        # Strategy 2: Microdata / itemprop
        if pricing.price == 0.0:
            price_el = _soup.select_one("[itemprop='price']")
            if price_el:
                content = price_el.get("content", "") or price_el.get_text(strip=True)
                pricing.price = self._parse_price_text(str(content))

        # Strategy 3: CSS class heuristics
        if pricing.price == 0.0:
            price_selectors = [
                "[class*='sale-price']",
                "[class*='current-price']",
                "[class*='price'] [class*='now']",
                "[class*='price']",
                ".price",
                "#price",
            ]
            for selector in price_selectors:
                el = _soup.select_one(selector)
                if el:
                    parsed = self._parse_price_text(el.get_text(strip=True))
                    if parsed > 0:
                        pricing.price = parsed
                        pricing.price_text = el.get_text(strip=True)
                        break

        # Original / list price
        orig_selectors = [
            "[class*='original-price']",
            "[class*='was-price']",
            "[class*='list-price']",
            "[class*='price'] s",
            "[class*='price'] del",
        ]
        for selector in orig_selectors:
            el = _soup.select_one(selector)
            if el:
                parsed = self._parse_price_text(el.get_text(strip=True))
                if parsed > 0:
                    pricing.original_price = parsed
                    break

        pricing.compute_discount()
        self.logger.debug(
            "Pricing from %s: %.2f %s (was %.2f, discount %.1f%%)",
            url,
            pricing.price,
            pricing.currency,
            pricing.original_price,
            pricing.discount_percent,
        )
        return pricing

    # ------------------------------------------------------------------
    # Private extraction helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_jsonld_product(soup: Any) -> Dict[str, Any]:
        """Extract JSON-LD Product structured data from the page.

        Parameters
        ----------
        soup:
            Parsed BeautifulSoup document.

        Returns
        -------
        dict
            The first ``Product`` JSON-LD object found, or an empty dict.
        """
        import json as _json

        for script in soup.select('script[type="application/ld+json"]'):
            try:
                data = _json.loads(script.string or "")
            except (ValueError, TypeError):
                continue

            # Handle @graph arrays
            if isinstance(data, dict) and "@graph" in data:
                data = data["@graph"]

            items = data if isinstance(data, list) else [data]
            for item in items:
                if isinstance(item, dict) and item.get("@type") == "Product":
                    return item

        return {}

    @staticmethod
    def _extract_jsonld_image(jsonld: Dict[str, Any]) -> str:
        """Pull the first image URL from a JSON-LD Product object."""
        image = jsonld.get("image", "")
        if isinstance(image, list) and image:
            image = image[0]
        if isinstance(image, dict):
            image = image.get("url", "")
        return str(image)

    @staticmethod
    def _parse_price_text(text: str) -> float:
        """Parse a price string like ``"$29.99"`` or ``"EUR 1,299.00"`` into a float.

        Parameters
        ----------
        text:
            Raw price text from the page.

        Returns
        -------
        float
            Numeric price value, or ``0.0`` if parsing fails.
        """
        if not text:
            return 0.0
        # Remove currency symbols and whitespace, keep digits/dots/commas
        cleaned = re.sub(r"[^\d.,]", "", text.strip())
        if not cleaned:
            return 0.0

        # Handle European format: 1.299,00 -> 1299.00
        if "," in cleaned and "." in cleaned:
            if cleaned.rfind(",") > cleaned.rfind("."):
                # European: dots are thousands separators, comma is decimal
                cleaned = cleaned.replace(".", "").replace(",", ".")
            else:
                # US: commas are thousands separators
                cleaned = cleaned.replace(",", "")
        elif "," in cleaned:
            # Could be European decimal or US thousands
            parts = cleaned.split(",")
            if len(parts) == 2 and len(parts[1]) == 2:
                # Likely European decimal: 29,99
                cleaned = cleaned.replace(",", ".")
            else:
                # Likely US thousands: 1,299
                cleaned = cleaned.replace(",", "")

        try:
            return round(float(cleaned), 2)
        except ValueError:
            return 0.0

    @staticmethod
    def _safe_float(value: Any) -> float:
        """Safely convert a value to float, returning 0.0 on failure."""
        if value is None:
            return 0.0
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _safe_int(value: Any) -> Optional[int]:
        """Safely convert a value to int, returning None on failure."""
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying HTTP session and release resources."""
        self._session.close()
        self.logger.debug("ScrapingSource session closed")

    def __repr__(self) -> str:
        return (
            f"ScrapingSource(ua={self.user_agent!r}, "
            f"timeout={self.timeout}, "
            f"interval={self.min_request_interval}s)"
        )
