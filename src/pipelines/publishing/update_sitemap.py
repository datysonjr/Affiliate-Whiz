"""
pipelines.publishing.update_sitemap
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Generate and maintain XML sitemaps for affiliate content sites.  Ensures
search engines can discover all published pages efficiently.

Sitemaps are regenerated after each publish cycle when ``auto`` is
enabled in ``config/pipelines.yaml`` (``publishing.steps[2]``).

Design references:
    - config/pipelines.yaml  ``publishing.steps[2]``  (auto)
    - https://www.sitemaps.org/protocol.html
    - ARCHITECTURE.md  Section 3 (Publishing Pipeline)
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from xml.sax.saxutils import escape as xml_escape

from src.core.errors import PublishingError
from src.core.logger import get_logger, log_event

logger = get_logger("pipelines.publishing.update_sitemap")


# ---------------------------------------------------------------------------
# Sitemap protocol constants
# ---------------------------------------------------------------------------

_SITEMAP_XML_HEADER = '<?xml version="1.0" encoding="UTF-8"?>'
_SITEMAP_URLSET_OPEN = (
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"'
    ' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
    ' xsi:schemaLocation="http://www.sitemaps.org/schemas/sitemap/0.9'
    ' http://www.sitemaps.org/schemas/sitemap/0.9/sitemap.xsd">'
)
_SITEMAP_URLSET_CLOSE = "</urlset>"
_MAX_URLS_PER_SITEMAP = 50000
_MAX_SITEMAP_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class SitemapEntry:
    """A single URL entry in the sitemap.

    Attributes
    ----------
    loc:
        Full URL of the page.
    lastmod:
        Last modification date (ISO 8601 format).
    changefreq:
        Expected change frequency: ``"always"``, ``"hourly"``,
        ``"daily"``, ``"weekly"``, ``"monthly"``, ``"yearly"``,
        ``"never"``.
    priority:
        Priority relative to other pages on the site (0.0 - 1.0).
    """

    loc: str
    lastmod: str = ""
    changefreq: str = "weekly"
    priority: float = 0.5


@dataclass
class SitemapResult:
    """Result of a sitemap generation or update operation.

    Attributes
    ----------
    sitemap_url:
        URL where the sitemap is accessible.
    total_urls:
        Number of URLs in the sitemap.
    xml_content:
        The generated XML string.
    size_bytes:
        Size of the XML in bytes.
    checksum:
        MD5 checksum for change detection.
    is_valid:
        Whether the sitemap passes validation.
    errors:
        Validation errors if any.
    generated_at:
        UTC timestamp of generation.
    """

    sitemap_url: str = ""
    total_urls: int = 0
    xml_content: str = ""
    size_bytes: int = 0
    checksum: str = ""
    is_valid: bool = True
    errors: List[str] = field(default_factory=list)
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Sitemap generation
# ---------------------------------------------------------------------------


def generate_sitemap(
    entries: List[SitemapEntry],
    *,
    site_url: str = "",
) -> SitemapResult:
    """Generate a complete XML sitemap from a list of URL entries.

    Produces a standards-compliant sitemap according to the sitemaps.org
    protocol specification.

    Parameters
    ----------
    entries:
        List of :class:`SitemapEntry` objects to include.
    site_url:
        Base URL of the site (used for the sitemap URL).

    Returns
    -------
    SitemapResult
        The generated sitemap with XML content and metadata.

    Raises
    ------
    PublishingError
        If the sitemap exceeds protocol limits.
    """
    log_event(logger, "sitemap.generate.start", entry_count=len(entries))

    if len(entries) > _MAX_URLS_PER_SITEMAP:
        raise PublishingError(
            f"Sitemap contains {len(entries)} URLs, exceeding the "
            f"{_MAX_URLS_PER_SITEMAP} URL limit per sitemap file",
            details={"url_count": len(entries), "limit": _MAX_URLS_PER_SITEMAP},
        )

    xml_lines: List[str] = [
        _SITEMAP_XML_HEADER,
        _SITEMAP_URLSET_OPEN,
    ]

    for entry in entries:
        xml_lines.append("  <url>")
        xml_lines.append(f"    <loc>{xml_escape(entry.loc)}</loc>")
        if entry.lastmod:
            xml_lines.append(f"    <lastmod>{xml_escape(entry.lastmod)}</lastmod>")
        if entry.changefreq:
            xml_lines.append(
                f"    <changefreq>{xml_escape(entry.changefreq)}</changefreq>"
            )
        xml_lines.append(f"    <priority>{entry.priority:.1f}</priority>")
        xml_lines.append("  </url>")

    xml_lines.append(_SITEMAP_URLSET_CLOSE)

    xml_content = "\n".join(xml_lines)
    size_bytes = len(xml_content.encode("utf-8"))

    if size_bytes > _MAX_SITEMAP_SIZE_BYTES:
        raise PublishingError(
            f"Sitemap size ({size_bytes} bytes) exceeds the "
            f"{_MAX_SITEMAP_SIZE_BYTES} byte limit",
            details={"size_bytes": size_bytes, "limit": _MAX_SITEMAP_SIZE_BYTES},
        )

    checksum = hashlib.md5(xml_content.encode("utf-8")).hexdigest()
    sitemap_url = f"{site_url.rstrip('/')}/sitemap.xml" if site_url else "/sitemap.xml"

    result = SitemapResult(
        sitemap_url=sitemap_url,
        total_urls=len(entries),
        xml_content=xml_content,
        size_bytes=size_bytes,
        checksum=checksum,
    )

    log_event(
        logger,
        "sitemap.generate.ok",
        total_urls=len(entries),
        size_bytes=size_bytes,
    )
    return result


# ---------------------------------------------------------------------------
# Sitemap update (incremental)
# ---------------------------------------------------------------------------


def update_sitemap(
    existing_entries: List[SitemapEntry],
    new_entries: List[SitemapEntry],
    *,
    site_url: str = "",
    remove_urls: Optional[List[str]] = None,
) -> SitemapResult:
    """Update an existing sitemap with new, modified, or removed entries.

    Merges new entries into the existing sitemap, updates ``lastmod``
    for entries whose URLs already exist, and removes entries for
    deleted pages.

    Parameters
    ----------
    existing_entries:
        Current sitemap entries.
    new_entries:
        New or updated entries to add/merge.
    site_url:
        Base URL of the site.
    remove_urls:
        List of URLs to remove from the sitemap.

    Returns
    -------
    SitemapResult
        The regenerated sitemap.
    """
    log_event(
        logger,
        "sitemap.update.start",
        existing=len(existing_entries),
        new=len(new_entries),
        removals=len(remove_urls or []),
    )

    # Build a lookup by URL
    entries_by_url: Dict[str, SitemapEntry] = {}
    for entry in existing_entries:
        entries_by_url[entry.loc] = entry

    # Merge new entries
    for entry in new_entries:
        if entry.loc in entries_by_url:
            # Update existing entry's lastmod and other fields
            existing = entries_by_url[entry.loc]
            existing.lastmod = entry.lastmod or datetime.now(timezone.utc).strftime(
                "%Y-%m-%d"
            )
            if entry.changefreq:
                existing.changefreq = entry.changefreq
            if entry.priority != 0.5:
                existing.priority = entry.priority
        else:
            # Add new entry
            if not entry.lastmod:
                entry.lastmod = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            entries_by_url[entry.loc] = entry

    # Remove deleted URLs
    if remove_urls:
        for url in remove_urls:
            entries_by_url.pop(url, None)

    merged_entries = list(entries_by_url.values())

    # Sort by priority (highest first), then alphabetically
    merged_entries.sort(key=lambda e: (-e.priority, e.loc))

    result = generate_sitemap(merged_entries, site_url=site_url)

    log_event(
        logger,
        "sitemap.update.ok",
        total_urls=result.total_urls,
        size_bytes=result.size_bytes,
    )
    return result


# ---------------------------------------------------------------------------
# Sitemap validation
# ---------------------------------------------------------------------------


def validate_sitemap(
    xml_content: str,
    *,
    check_urls: bool = True,
) -> Dict[str, Any]:
    """Validate a sitemap XML string against the protocol specification.

    Checks XML well-formedness, required elements, URL count limits,
    file size, and URL format.

    Parameters
    ----------
    xml_content:
        The sitemap XML to validate.
    check_urls:
        Whether to validate individual URL formats.

    Returns
    -------
    dict[str, Any]
        Validation report with keys: ``valid``, ``errors``, ``warnings``,
        ``url_count``, ``size_bytes``.
    """
    log_event(logger, "sitemap.validate.start")

    errors: List[str] = []
    warnings: List[str] = []
    url_count = 0
    size_bytes = len(xml_content.encode("utf-8"))

    # Check size limit
    if size_bytes > _MAX_SITEMAP_SIZE_BYTES:
        errors.append(
            f"Sitemap size ({size_bytes} bytes) exceeds the "
            f"{_MAX_SITEMAP_SIZE_BYTES} byte protocol limit."
        )

    # Check for required XML header
    if not xml_content.strip().startswith("<?xml"):
        errors.append("Missing XML declaration header.")

    # Check for urlset element
    if "<urlset" not in xml_content:
        errors.append("Missing <urlset> root element.")

    # Count and validate URLs
    url_matches = re.findall(r"<loc>(.*?)</loc>", xml_content)
    url_count = len(url_matches)

    if url_count == 0:
        warnings.append("Sitemap contains no URL entries.")

    if url_count > _MAX_URLS_PER_SITEMAP:
        errors.append(
            f"Sitemap contains {url_count} URLs, exceeding the "
            f"{_MAX_URLS_PER_SITEMAP} limit."
        )

    if check_urls:
        for url in url_matches:
            if not url.startswith("http://") and not url.startswith("https://"):
                errors.append(f"Invalid URL (must be absolute): {url}")

    # Check for valid changefreq values
    valid_changefreqs = {
        "always",
        "hourly",
        "daily",
        "weekly",
        "monthly",
        "yearly",
        "never",
    }
    freq_matches = re.findall(r"<changefreq>(.*?)</changefreq>", xml_content)
    for freq in freq_matches:
        if freq not in valid_changefreqs:
            warnings.append(f"Invalid changefreq value: {freq}")

    # Check priority values
    priority_matches = re.findall(r"<priority>(.*?)</priority>", xml_content)
    for pri_str in priority_matches:
        try:
            pri = float(pri_str)
            if not (0.0 <= pri <= 1.0):
                warnings.append(f"Priority value out of range (0.0-1.0): {pri_str}")
        except ValueError:
            errors.append(f"Invalid priority value: {pri_str}")

    is_valid = len(errors) == 0

    report = {
        "valid": is_valid,
        "errors": errors,
        "warnings": warnings,
        "url_count": url_count,
        "size_bytes": size_bytes,
    }

    log_event(
        logger,
        "sitemap.validate.ok",
        valid=is_valid,
        errors=len(errors),
        warnings=len(warnings),
        url_count=url_count,
    )
    return report
