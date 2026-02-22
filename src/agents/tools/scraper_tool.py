"""Web scraping tool for extracting structured data from HTML pages.

Provides methods for fetching pages, extracting links and text,
and parsing structured data (JSON-LD, OpenGraph, microdata) from
raw HTML content.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

logger = logging.getLogger(__name__)


class ScraperTool:
    """Web scraping and HTML data-extraction tool.

    Fetches web pages using ``httpx`` (async HTTP client) and parses
    HTML with ``BeautifulSoup``.  The class is intentionally stateless
    beyond configuration so that it can be shared across agent tasks.

    Attributes:
        config: Dictionary holding scraper configuration such as
            ``user_agent``, ``timeout``, ``max_retries``,
            ``respect_robots_txt``, and ``rate_limit``.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        """Initialise ScraperTool with the given configuration.

        Args:
            config: Configuration dictionary.  Recognised keys:

                * ``user_agent`` (str) -- User-Agent header value.
                  Default ``"Affiliate-Whiz Scraper/1.0"``.
                * ``timeout`` (int) -- request timeout in seconds.
                  Default ``30``.
                * ``max_retries`` (int) -- number of retry attempts on
                  transient errors.  Default ``3``.
                * ``respect_robots_txt`` (bool) -- if ``True``, honour
                  robots.txt directives.  Default ``True``.
                * ``rate_limit`` (float) -- minimum seconds between
                  consecutive requests to the same host.  Default ``1.0``.
                * ``headers`` (dict) -- extra HTTP headers to include.
        """
        self.config = config
        self._user_agent: str = config.get(
            "user_agent", "Affiliate-Whiz Scraper/1.0"
        )
        self._timeout: int = config.get("timeout", 30)
        self._max_retries: int = config.get("max_retries", 3)
        self._respect_robots: bool = config.get("respect_robots_txt", True)
        self._rate_limit: float = config.get("rate_limit", 1.0)
        self._extra_headers: dict[str, str] = config.get("headers", {})

        logger.info(
            "ScraperTool initialised (timeout=%ds, retries=%d)",
            self._timeout,
            self._max_retries,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _fetch(self, url: str) -> str:
        """Perform an HTTP GET request and return the response body.

        Applies retry logic and honours the configured timeout.

        Args:
            url: The URL to fetch.

        Returns:
            Response body as a string.

        Raises:
            RuntimeError: After all retry attempts have been exhausted.
        """
        try:
            import httpx  # type: ignore[import-untyped]
        except ImportError as exc:
            raise RuntimeError(
                "httpx is required for ScraperTool. Install it with: "
                "pip install httpx"
            ) from exc

        headers = {"User-Agent": self._user_agent, **self._extra_headers}

        last_error: Optional[Exception] = None
        for attempt in range(1, self._max_retries + 1):
            try:
                async with httpx.AsyncClient(
                    timeout=self._timeout, headers=headers
                ) as client:
                    response = await client.get(url)
                    response.raise_for_status()
                    logger.debug(
                        "Fetched %s (attempt %d, status %d)",
                        url,
                        attempt,
                        response.status_code,
                    )
                    return response.text
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Fetch attempt %d/%d for %s failed: %s",
                    attempt,
                    self._max_retries,
                    url,
                    exc,
                )

        raise RuntimeError(
            f"Failed to fetch {url} after {self._max_retries} attempts: "
            f"{last_error}"
        )

    @staticmethod
    def _get_soup(html: str) -> Any:
        """Return a BeautifulSoup document from raw HTML.

        Args:
            html: Raw HTML string.

        Returns:
            A ``BeautifulSoup`` object.

        Raises:
            RuntimeError: If ``beautifulsoup4`` is not installed.
        """
        try:
            from bs4 import BeautifulSoup  # type: ignore[import-untyped]
        except ImportError as exc:
            raise RuntimeError(
                "beautifulsoup4 is required for ScraperTool. "
                "Install it with: pip install beautifulsoup4"
            ) from exc

        return BeautifulSoup(html, "html.parser")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def scrape_url(self, url: str) -> dict[str, Any]:
        """Fetch a URL and return a structured representation of the page.

        The returned dictionary contains the page title, meta
        description, all links found, the visible text body, and any
        structured data (JSON-LD / OpenGraph) discovered.

        Args:
            url: Fully-qualified URL to scrape.

        Returns:
            A dict with the following keys:

            * ``url`` (str) -- the canonical URL that was fetched.
            * ``title`` (str) -- contents of the ``<title>`` tag.
            * ``meta_description`` (str) -- meta description content.
            * ``links`` (list[str]) -- all ``href`` URLs found on
              the page.
            * ``text`` (str) -- visible body text, whitespace-normalised.
            * ``structured_data`` (dict) -- output of
              :meth:`parse_structured_data`.

        Raises:
            RuntimeError: If the page cannot be fetched or parsed.
        """
        logger.info("Scraping URL: %s", url)
        html = await self._fetch(url)
        soup = self._get_soup(html)

        title_tag = soup.find("title")
        title: str = title_tag.get_text(strip=True) if title_tag else ""

        meta_tag = soup.find("meta", attrs={"name": "description"})
        meta_description: str = (
            meta_tag.get("content", "") if meta_tag else ""
        )

        links = self.extract_links(html, base_url=url)
        text = self.extract_text(html)
        structured_data = self.parse_structured_data(html)

        result: dict[str, Any] = {
            "url": url,
            "title": title,
            "meta_description": meta_description,
            "links": links,
            "text": text,
            "structured_data": structured_data,
        }

        logger.info(
            "Scraped %s -- title=%r, links=%d, text_len=%d",
            url,
            title,
            len(links),
            len(text),
        )
        return result

    def extract_links(
        self,
        html: str,
        *,
        base_url: Optional[str] = None,
    ) -> list[str]:
        """Extract all hyperlink URLs from HTML content.

        Relative URLs are resolved against *base_url* if provided.
        Duplicate URLs and fragment-only anchors are removed.

        Args:
            html: Raw HTML string to parse.
            base_url: Optional base URL used to resolve relative links.

        Returns:
            Deduplicated list of absolute URL strings found in the HTML.
        """
        logger.debug("Extracting links from HTML (%d chars)", len(html))
        soup = self._get_soup(html)
        seen: set[str] = set()
        result: list[str] = []

        for anchor in soup.find_all("a", href=True):
            href: str = anchor["href"].strip()
            if not href or href.startswith("#"):
                continue

            if base_url and not urlparse(href).netloc:
                href = urljoin(base_url, href)

            if href not in seen:
                seen.add(href)
                result.append(href)

        logger.debug("Found %d unique links.", len(result))
        return result

    def extract_text(self, html: str) -> str:
        """Extract visible body text from HTML, stripping tags and scripts.

        Collapses excessive whitespace and returns a clean text block
        suitable for NLP processing.

        Args:
            html: Raw HTML string to parse.

        Returns:
            Whitespace-normalised visible text content.
        """
        logger.debug("Extracting text from HTML (%d chars)", len(html))
        soup = self._get_soup(html)

        # Remove non-visible elements.
        for tag in soup(["script", "style", "noscript", "iframe", "svg"]):
            tag.decompose()

        raw_text = soup.get_text(separator=" ")
        # Collapse whitespace.
        clean_text = re.sub(r"\s+", " ", raw_text).strip()

        logger.debug("Extracted %d characters of text.", len(clean_text))
        return clean_text

    def parse_structured_data(self, html: str) -> dict[str, Any]:
        """Parse structured data from HTML (JSON-LD, OpenGraph, meta).

        Looks for ``<script type="application/ld+json">`` blocks and
        OpenGraph ``<meta property="og:...">`` tags.

        Args:
            html: Raw HTML string to parse.

        Returns:
            A dict with keys:

            * ``json_ld`` (list[dict]) -- all JSON-LD objects found.
            * ``opengraph`` (dict[str, str]) -- OpenGraph property map.
            * ``meta_tags`` (dict[str, str]) -- other interesting meta
              tags (e.g. ``twitter:*``).
        """
        import json as _json

        logger.debug("Parsing structured data from HTML (%d chars)", len(html))
        soup = self._get_soup(html)

        # --- JSON-LD ---
        json_ld: list[dict[str, Any]] = []
        for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
            try:
                data = _json.loads(script.string or "")
                if isinstance(data, list):
                    json_ld.extend(data)
                else:
                    json_ld.append(data)
            except (_json.JSONDecodeError, TypeError):
                logger.debug("Skipping malformed JSON-LD block.")

        # --- OpenGraph ---
        opengraph: dict[str, str] = {}
        for meta in soup.find_all("meta", attrs={"property": re.compile(r"^og:")}):
            prop = meta.get("property", "")
            content = meta.get("content", "")
            if prop and content:
                opengraph[prop] = content

        # --- Twitter / misc meta ---
        meta_tags: dict[str, str] = {}
        for meta in soup.find_all("meta", attrs={"name": re.compile(r"^twitter:")}):
            name = meta.get("name", "")
            content = meta.get("content", "")
            if name and content:
                meta_tags[name] = content

        result: dict[str, Any] = {
            "json_ld": json_ld,
            "opengraph": opengraph,
            "meta_tags": meta_tags,
        }
        logger.debug(
            "Structured data: %d JSON-LD blocks, %d OG tags, %d meta tags",
            len(json_ld),
            len(opengraph),
            len(meta_tags),
        )
        return result
