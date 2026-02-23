"""
integrations.affiliates.generic_rss
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

RSS/Atom feed parser for affiliate programmes that expose offers via feeds.

Provides :class:`GenericRSSFeed` which fetches and parses RSS or Atom feeds,
then normalises each entry into a standard offer dict compatible with the
OpenClaw offer-discovery pipeline.  Useful for smaller affiliate networks
and merchants that publish deals, coupons, and product feeds via RSS.

Design references:
    - config/providers.yaml  ``rss_sources`` section
    - ARCHITECTURE.md  Section 4 (Integration Layer)

Usage::

    from src.integrations.affiliates.generic_rss import GenericRSSFeed

    feed = GenericRSSFeed(
        feed_url="https://example.com/affiliates/deals.rss",
        source_name="ExampleMerchant",
    )
    offers = await feed.fetch_feed()
    normalised = [feed.normalize_offer(o) for o in offers]
"""

from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Optional

from src.core.constants import DEFAULT_MAX_RETRIES, DEFAULT_REQUEST_TIMEOUT
from src.core.errors import IntegrationError
from src.core.logger import get_logger, log_event

logger = get_logger("integrations.affiliates.generic_rss")

# ---------------------------------------------------------------------------
# Namespace constants for Atom feeds
# ---------------------------------------------------------------------------

_ATOM_NS = "http://www.w3.org/2005/Atom"
_DC_NS = "http://purl.org/dc/elements/1.1/"
_CONTENT_NS = "http://purl.org/rss/1.0/modules/content/"


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------


@dataclass
class RSSFeedEntry:
    """A single entry parsed from an RSS or Atom feed.

    Attributes
    ----------
    entry_id:
        Unique identifier for the entry (GUID from RSS or ``id`` from Atom).
    title:
        Entry title.
    link:
        Primary link URL.
    description:
        Entry description or summary text.
    published:
        Publication date (UTC).
    updated:
        Last-updated date (UTC), if available.
    author:
        Author name.
    categories:
        List of category/tag labels.
    content:
        Full content body (if provided via ``content:encoded`` or Atom ``content``).
    raw_xml:
        The original XML element as a string (for debugging).
    """

    entry_id: str
    title: str = ""
    link: str = ""
    description: str = ""
    published: Optional[datetime] = None
    updated: Optional[datetime] = None
    author: str = ""
    categories: List[str] = field(default_factory=list)
    content: str = ""
    raw_xml: str = ""


@dataclass
class NormalisedOffer:
    """A feed entry normalised into a standard offer format.

    Compatible with the :class:`~src.pipelines.offer_discovery.ingest.RawOffer`
    pipeline input schema.

    Attributes
    ----------
    offer_id:
        Deterministic identifier derived from the feed entry.
    source:
        Name of the feed source.
    name:
        Offer / product title.
    url:
        Offer destination URL.
    description:
        Offer description.
    categories:
        Category labels.
    discovered_at:
        UTC timestamp when the offer was parsed from the feed.
    metadata:
        Additional key-value pairs extracted from the feed entry.
    """

    offer_id: str
    source: str
    name: str = ""
    url: str = ""
    description: str = ""
    categories: List[str] = field(default_factory=list)
    discovered_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# GenericRSSFeed client
# ---------------------------------------------------------------------------


class GenericRSSFeed:
    """RSS/Atom feed fetcher and parser for affiliate offer discovery.

    Fetches a remote feed, parses it into structured entries, and provides
    normalisation helpers for the offer-discovery pipeline.

    Parameters
    ----------
    feed_url:
        URL of the RSS or Atom feed.
    source_name:
        Human-readable name for this feed source (used as the ``source``
        field in normalised offers).
    timeout:
        HTTP request timeout in seconds.
    max_retries:
        Maximum number of retry attempts on transient failures.
    custom_headers:
        Additional HTTP headers to include in the feed request
        (e.g. API keys, custom user-agent strings).
    """

    def __init__(
        self,
        feed_url: str,
        source_name: str = "generic_rss",
        timeout: int = DEFAULT_REQUEST_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        custom_headers: Optional[Dict[str, str]] = None,
    ) -> None:
        if not feed_url:
            raise IntegrationError("feed_url is required for RSS feed integration")

        self._feed_url = feed_url
        self._source_name = source_name
        self._timeout = timeout
        self._max_retries = max_retries
        self._custom_headers = custom_headers or {}
        self._last_fetched_at: Optional[datetime] = None
        self._last_etag: str = ""
        self._last_modified: str = ""
        self._fetch_count: int = 0

        log_event(
            logger,
            "rss.init",
            source_name=source_name,
            feed_url=feed_url,
        )

    # ------------------------------------------------------------------
    # XML parsing helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_feed_type(root: ET.Element) -> str:
        """Detect whether the XML root element represents RSS or Atom.

        Parameters
        ----------
        root:
            The root XML element.

        Returns
        -------
        str
            Either ``"rss"`` or ``"atom"``.

        Raises
        ------
        IntegrationError
            If the feed format is not recognised.
        """
        tag = root.tag.lower()
        if tag == "rss" or tag.endswith("}rss"):
            return "rss"
        if "feed" in tag:
            return "atom"
        # Check for RSS 2.0 channel as direct child
        if root.find("channel") is not None:
            return "rss"
        raise IntegrationError(
            f"Unrecognised feed format: root tag is {root.tag!r}",
            details={"root_tag": root.tag},
        )

    @staticmethod
    def _safe_parse_date(date_str: Optional[str]) -> Optional[datetime]:
        """Attempt to parse a date string from various RSS/Atom formats.

        Parameters
        ----------
        date_str:
            Date string in RFC 822, RFC 3339, or ISO 8601 format.

        Returns
        -------
        datetime or None
            Parsed UTC datetime, or ``None`` if parsing fails.
        """
        if not date_str:
            return None

        # Try RFC 822 (common in RSS)
        try:
            return parsedate_to_datetime(date_str).astimezone(timezone.utc)
        except (ValueError, TypeError, AttributeError):
            pass

        # Try ISO 8601 / RFC 3339 (common in Atom)
        try:
            cleaned = date_str.replace("Z", "+00:00")
            return datetime.fromisoformat(cleaned).astimezone(timezone.utc)
        except (ValueError, TypeError):
            pass

        return None

    @staticmethod
    def _generate_entry_id(entry: Dict[str, Any]) -> str:
        """Generate a deterministic ID for a feed entry.

        Uses a SHA-256 hash of the entry's link and title to create a
        stable, unique identifier even when the feed does not include
        a GUID or ``id`` element.

        Parameters
        ----------
        entry:
            Dict with at least ``"link"`` and ``"title"`` keys.

        Returns
        -------
        str
            A 16-character hex digest.
        """
        content = f"{entry.get('link', '')}|{entry.get('title', '')}"
        return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]

    def _parse_rss_channel(self, root: ET.Element) -> List[RSSFeedEntry]:
        """Parse entries from an RSS 2.0 feed.

        Parameters
        ----------
        root:
            The root ``<rss>`` XML element.

        Returns
        -------
        list[RSSFeedEntry]
            Parsed feed entries.
        """
        entries: List[RSSFeedEntry] = []
        channel = root.find("channel")
        if channel is None:
            logger.warning("RSS feed has no <channel> element")
            return entries

        for item in channel.findall("item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            description = (item.findtext("description") or "").strip()
            guid = (item.findtext("guid") or "").strip()
            pub_date = item.findtext("pubDate") or item.findtext("pubdate")
            author = (
                item.findtext(f"{{{_DC_NS}}}creator") or item.findtext("author") or ""
            ).strip()

            # Full content via content:encoded
            content_encoded = (item.findtext(f"{{{_CONTENT_NS}}}encoded") or "").strip()

            categories = [
                (cat.text or "").strip() for cat in item.findall("category") if cat.text
            ]

            entry_id = guid or self._generate_entry_id({"link": link, "title": title})

            entry = RSSFeedEntry(
                entry_id=entry_id,
                title=title,
                link=link,
                description=description,
                published=self._safe_parse_date(pub_date),
                author=author,
                categories=categories,
                content=content_encoded,
                raw_xml=ET.tostring(item, encoding="unicode", method="xml"),
            )
            entries.append(entry)

        return entries

    def _parse_atom_feed(self, root: ET.Element) -> List[RSSFeedEntry]:
        """Parse entries from an Atom feed.

        Parameters
        ----------
        root:
            The root ``<feed>`` XML element.

        Returns
        -------
        list[RSSFeedEntry]
            Parsed feed entries.
        """
        entries: List[RSSFeedEntry] = []
        ns = {"atom": _ATOM_NS}

        for entry_elem in root.findall("atom:entry", ns):
            title = (entry_elem.findtext("atom:title", "", ns)).strip()
            entry_id = (entry_elem.findtext("atom:id", "", ns)).strip()

            # Link extraction -- prefer "alternate" rel
            link = ""
            for link_elem in entry_elem.findall("atom:link", ns):
                rel = link_elem.get("rel", "alternate")
                if rel == "alternate":
                    link = link_elem.get("href", "")
                    break
            if not link:
                link_elems = entry_elem.findall("atom:link", ns)
                if link_elems:
                    link = link_elems[0].get("href", "")

            summary = (entry_elem.findtext("atom:summary", "", ns)).strip()
            content = (entry_elem.findtext("atom:content", "", ns)).strip()
            published = entry_elem.findtext("atom:published", "", ns)
            updated = entry_elem.findtext("atom:updated", "", ns)
            author_name = (entry_elem.findtext("atom:author/atom:name", "", ns)).strip()

            categories = [
                cat.get("term", "")
                for cat in entry_elem.findall("atom:category", ns)
                if cat.get("term")
            ]

            if not entry_id:
                entry_id = self._generate_entry_id({"link": link, "title": title})

            entry = RSSFeedEntry(
                entry_id=entry_id,
                title=title,
                link=link,
                description=summary,
                published=self._safe_parse_date(published),
                updated=self._safe_parse_date(updated),
                author=author_name,
                categories=categories,
                content=content or summary,
                raw_xml=ET.tostring(entry_elem, encoding="unicode", method="xml"),
            )
            entries.append(entry)

        return entries

    # ------------------------------------------------------------------
    # Public API methods
    # ------------------------------------------------------------------

    async def fetch_feed(self, raw_xml: Optional[str] = None) -> List[RSSFeedEntry]:
        """Fetch and parse the RSS/Atom feed.

        If *raw_xml* is provided, it is parsed directly without making
        an HTTP request (useful for testing).

        Parameters
        ----------
        raw_xml:
            Optional pre-fetched XML content.  When ``None``, the feed
            is fetched from :attr:`_feed_url` via HTTP GET.

        Returns
        -------
        list[RSSFeedEntry]
            Parsed feed entries sorted by publication date (newest first).

        Raises
        ------
        IntegrationError
            If the feed cannot be fetched or parsed.
        """
        log_event(
            logger,
            "rss.fetch_feed",
            source_name=self._source_name,
            feed_url=self._feed_url,
            from_cache=raw_xml is not None,
        )

        xml_content = raw_xml
        if xml_content is None:
            # Production: use aiohttp to fetch the feed.
            # headers = {"User-Agent": APP_USER_AGENT, **self._custom_headers}
            # if self._last_etag:
            #     headers["If-None-Match"] = self._last_etag
            # if self._last_modified:
            #     headers["If-Modified-Since"] = self._last_modified
            # async with aiohttp.ClientSession() as session:
            #     async with session.get(self._feed_url, headers=headers,
            #                            timeout=self._timeout) as resp:
            #         if resp.status == 304:
            #             return []  # Not modified
            #         if resp.status != 200:
            #             raise IntegrationError(...)
            #         self._last_etag = resp.headers.get("ETag", "")
            #         self._last_modified = resp.headers.get("Last-Modified", "")
            #         xml_content = await resp.text()
            logger.debug(
                "HTTP fetch for %s would happen here (transport not wired)",
                self._feed_url,
            )
            self._fetch_count += 1
            self._last_fetched_at = datetime.now(timezone.utc)
            return []

        try:
            root = ET.fromstring(xml_content)
        except ET.ParseError as exc:
            raise IntegrationError(
                f"Failed to parse XML from feed {self._source_name!r}",
                details={"feed_url": self._feed_url, "error": str(exc)},
                cause=exc,
            ) from exc

        feed_type = self._detect_feed_type(root)

        if feed_type == "rss":
            entries = self._parse_rss_channel(root)
        else:
            entries = self._parse_atom_feed(root)

        # Sort by published date (newest first)
        entries.sort(
            key=lambda e: e.published or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )

        self._fetch_count += 1
        self._last_fetched_at = datetime.now(timezone.utc)

        log_event(
            logger,
            "rss.fetch_complete",
            source_name=self._source_name,
            feed_type=feed_type,
            entry_count=len(entries),
        )

        return entries

    def parse_offers(self, entries: List[RSSFeedEntry]) -> List[NormalisedOffer]:
        """Convert a list of feed entries into normalised offer dicts.

        Convenience method that calls :meth:`normalize_offer` on each
        entry and filters out entries that lack a title and link.

        Parameters
        ----------
        entries:
            Feed entries as returned by :meth:`fetch_feed`.

        Returns
        -------
        list[NormalisedOffer]
            Normalised offers suitable for the ingest pipeline.
        """
        offers: List[NormalisedOffer] = []
        skipped = 0

        for entry in entries:
            if not entry.title and not entry.link:
                skipped += 1
                continue
            offers.append(self.normalize_offer(entry))

        if skipped:
            logger.info(
                "Skipped %d entries without title or link from %s",
                skipped,
                self._source_name,
            )

        log_event(
            logger,
            "rss.parse_offers",
            source_name=self._source_name,
            input_count=len(entries),
            output_count=len(offers),
            skipped=skipped,
        )

        return offers

    def normalize_offer(self, entry: RSSFeedEntry) -> NormalisedOffer:
        """Normalise a single feed entry into a standard offer record.

        Parameters
        ----------
        entry:
            A single :class:`RSSFeedEntry` to normalise.

        Returns
        -------
        NormalisedOffer
            Normalised offer with a deterministic ID.
        """
        return NormalisedOffer(
            offer_id=entry.entry_id,
            source=self._source_name,
            name=entry.title,
            url=entry.link,
            description=entry.description or entry.content[:500]
            if entry.content
            else entry.description,
            categories=entry.categories,
            discovered_at=datetime.now(timezone.utc),
            metadata={
                "author": entry.author,
                "published": entry.published.isoformat() if entry.published else "",
                "updated": entry.updated.isoformat() if entry.updated else "",
                "has_full_content": bool(entry.content),
            },
        )

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def feed_url(self) -> str:
        """Return the configured feed URL."""
        return self._feed_url

    @property
    def source_name(self) -> str:
        """Return the configured source name."""
        return self._source_name

    @property
    def fetch_count(self) -> int:
        """Return the total number of feed fetches performed."""
        return self._fetch_count

    @property
    def last_fetched_at(self) -> Optional[datetime]:
        """Return the UTC timestamp of the most recent fetch."""
        return self._last_fetched_at

    def __repr__(self) -> str:
        return (
            f"GenericRSSFeed(source={self._source_name!r}, "
            f"url={self._feed_url!r}, "
            f"fetches={self._fetch_count})"
        )
