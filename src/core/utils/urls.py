"""
core.utils.urls
~~~~~~~~~~~~~~~

URL utilities for link handling, validation, and affiliate URL construction.

Provides functions used throughout the publishing and content pipelines
to normalize URLs for deduplication, extract domains for site management,
validate links before publishing, and build properly-tagged affiliate URLs
for each supported network.

Usage::

    from src.core.utils.urls import normalize_url, extract_domain, is_valid_url, build_affiliate_url

    canonical = normalize_url("https://Example.com/Page?b=2&a=1&utm_source=x")
    domain = extract_domain("https://shop.example.co.uk/products/widget")
    valid = is_valid_url("https://example.com")
    aff_url = build_affiliate_url("https://amzn.com/dp/B123", "mytag-20", network="amazon")
"""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse


# =====================================================================
# Tracking parameters to strip during normalization
# =====================================================================

_TRACKING_PARAMS = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "fbclid",
        "gclid",
        "msclkid",
        "dclid",
        "twclid",
        "mc_cid",
        "mc_eid",
    }
)


# =====================================================================
# URL normalization
# =====================================================================


def normalize_url(
    url: str,
    *,
    strip_tracking: bool = True,
    strip_fragment: bool = True,
    force_https: bool = False,
) -> str:
    """Normalize a URL for consistent storage and comparison.

    * Lowercases scheme and host.
    * Strips trailing slashes from the path (keeps root ``/``).
    * Sorts query parameters alphabetically.
    * Optionally removes tracking parameters and fragments.

    Parameters
    ----------
    url:
        The raw URL to normalize.
    strip_tracking:
        If ``True``, remove known tracking/UTM query parameters.
    strip_fragment:
        If ``True``, remove the ``#fragment`` portion.
    force_https:
        If ``True``, upgrade ``http://`` to ``https://``.

    Returns
    -------
    str
        The normalized URL string.

    Examples
    --------
    >>> normalize_url("https://Example.com/Page?b=2&a=1")
    'https://example.com/Page?a=1&b=2'
    >>> normalize_url("http://example.com/page?utm_source=google&q=test", strip_tracking=True)
    'http://example.com/page?q=test'
    >>> normalize_url("http://example.com/page", force_https=True)
    'https://example.com/page'
    """
    parsed = urlparse(url)

    scheme = (parsed.scheme or "https").lower()
    if force_https and scheme == "http":
        scheme = "https"

    netloc = (parsed.netloc or "").lower()

    # Preserve path casing (URLs are case-sensitive in the path segment)
    # but normalize trailing slashes
    path = parsed.path.rstrip("/") or "/"

    # Process query parameters
    query_params = parse_qs(parsed.query, keep_blank_values=True)
    if strip_tracking:
        query_params = {
            k: v for k, v in query_params.items() if k.lower() not in _TRACKING_PARAMS
        }

    # Sort for deterministic output
    sorted_query = urlencode(
        sorted(
            ((k, v[0]) for k, v in query_params.items()),
            key=lambda pair: pair[0],
        )
    )

    fragment = "" if strip_fragment else parsed.fragment

    return urlunparse((scheme, netloc, path, "", sorted_query, fragment))


# =====================================================================
# Domain extraction
# =====================================================================


def extract_domain(url: str, *, include_subdomain: bool = True) -> str:
    """Extract the domain from a URL.

    Parameters
    ----------
    url:
        URL to extract the domain from.
    include_subdomain:
        If ``True`` (default), return the full netloc (e.g.
        ``"shop.example.co.uk"``).  If ``False``, attempt to return
        just the registrable domain (e.g. ``"example.co.uk"``).

    Returns
    -------
    str
        Lowercase domain string.

    Examples
    --------
    >>> extract_domain("https://shop.example.co.uk/products/widget")
    'shop.example.co.uk'
    >>> extract_domain("https://shop.example.co.uk/products/widget", include_subdomain=False)
    'example.co.uk'
    >>> extract_domain("https://example.com:8080/path")
    'example.com'
    """
    parsed = urlparse(url)
    domain = parsed.netloc or parsed.path.split("/")[0]

    # Remove port number
    domain = domain.split(":")[0].lower()

    if not include_subdomain:
        # Simple heuristic: keep the last two parts, or three if the
        # second-level is a known ccTLD component (co, com, org, net, etc.)
        parts = domain.split(".")
        if len(parts) > 2:
            # Check for two-part TLDs like .co.uk, .com.au, .org.br
            if parts[-2] in ("co", "com", "org", "net", "gov", "edu", "ac"):
                domain = ".".join(parts[-3:])
            else:
                domain = ".".join(parts[-2:])

    return domain


# =====================================================================
# Validation
# =====================================================================


def is_valid_url(url: str, *, require_https: bool = False) -> bool:
    """Check if a string is a valid HTTP(S) URL.

    Parameters
    ----------
    url:
        String to validate.
    require_https:
        If ``True``, only ``https://`` URLs are considered valid.

    Returns
    -------
    bool
        ``True`` if the string is a well-formed URL with a recognized
        scheme and non-empty host.

    Examples
    --------
    >>> is_valid_url("https://example.com/path")
    True
    >>> is_valid_url("ftp://files.example.com")
    False
    >>> is_valid_url("not a url")
    False
    >>> is_valid_url("http://example.com", require_https=True)
    False
    """
    try:
        parsed = urlparse(url)
    except (ValueError, AttributeError):
        return False

    allowed_schemes = ("https",) if require_https else ("http", "https")

    if parsed.scheme not in allowed_schemes:
        return False
    if not parsed.netloc:
        return False

    # Basic hostname validation: must contain at least one dot and
    # consist of valid characters
    host = parsed.netloc.split(":")[0]
    if "." not in host:
        return False
    if not re.match(r"^[a-zA-Z0-9._-]+$", host):
        return False

    return True


# =====================================================================
# Affiliate URL construction
# =====================================================================

# Maps affiliate network names to their tag/ID parameter name.
_NETWORK_PARAM_MAP: dict[str, str] = {
    "amazon": "tag",
    "impact": "irclickid",
    "cj": "sid",
    "shareasale": "afftrack",
    "rakuten": "mid",
    "awin": "awc",
    "partnerize": "pubref",
}


def build_affiliate_url(
    base_url: str,
    affiliate_tag: str,
    network: str = "amazon",
    *,
    sub_id: Optional[str] = None,
    extra_params: Optional[dict[str, str]] = None,
) -> str:
    """Build an affiliate tracking URL for the specified network.

    Appends (or replaces) the network-specific tracking parameter and
    any additional parameters to the base product/merchant URL.

    Parameters
    ----------
    base_url:
        The original product or merchant URL.
    affiliate_tag:
        Your affiliate tag, tracking ID, or publisher ID.
    network:
        Affiliate network identifier.  Supported values:
        ``"amazon"``, ``"impact"``, ``"cj"``, ``"shareasale"``,
        ``"rakuten"``, ``"awin"``, ``"partnerize"``.
        Falls back to ``"ref"`` for unrecognized networks.
    sub_id:
        Optional sub-tracking ID for internal campaign attribution.
        Appended as ``sub_id=<value>`` for networks that support it.
    extra_params:
        Additional query parameters to append.

    Returns
    -------
    str
        Full URL with affiliate tracking parameters.

    Examples
    --------
    >>> build_affiliate_url("https://amazon.com/dp/B123", "mytag-20")
    'https://amazon.com/dp/B123?tag=mytag-20'
    >>> build_affiliate_url("https://merchant.com/product", "pub123", network="impact", sub_id="review")
    'https://merchant.com/product?irclickid=pub123&sub_id=review'
    """
    parsed = urlparse(base_url)

    # Start with existing query parameters
    existing_params = parse_qs(parsed.query, keep_blank_values=True)
    merged: dict[str, str] = {
        k: v[0] if isinstance(v, list) else v for k, v in existing_params.items()
    }

    # Add the network-specific tracking parameter
    param_name = _NETWORK_PARAM_MAP.get(network.lower(), "ref")
    merged[param_name] = affiliate_tag

    # Add sub-tracking ID if provided
    if sub_id:
        merged["sub_id"] = sub_id

    # Merge extra params
    if extra_params:
        merged.update(extra_params)

    new_query = urlencode(sorted(merged.items()))

    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            new_query,
            "",  # Strip fragment from affiliate URLs
        )
    )


def strip_affiliate_params(url: str) -> str:
    """Remove known affiliate tracking parameters from a URL.

    Useful for comparing URLs ignoring affiliate attribution.

    Parameters
    ----------
    url:
        URL that may contain affiliate parameters.

    Returns
    -------
    str
        Clean URL with affiliate parameters removed.

    Examples
    --------
    >>> strip_affiliate_params("https://amazon.com/dp/B123?tag=foo-20&ref=sr")
    'https://amazon.com/dp/B123'
    """
    all_affiliate_params = set(_NETWORK_PARAM_MAP.values()) | {"ref", "sub_id"}

    parsed = urlparse(url)
    query_params = parse_qs(parsed.query, keep_blank_values=True)
    cleaned = {
        k: v for k, v in query_params.items() if k.lower() not in all_affiliate_params
    }

    new_query = (
        urlencode(sorted(((k, v[0]) for k, v in cleaned.items()), key=lambda p: p[0]))
        if cleaned
        else ""
    )

    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            new_query,
            "",
        )
    )


def join_url(base: str, path: str) -> str:
    """Join a base URL with a relative path.

    A thin wrapper around :func:`urllib.parse.urljoin` for readability.

    Parameters
    ----------
    base:
        Base URL (e.g. ``"https://example.com/blog/"``).
    path:
        Relative path (e.g. ``"best-widgets"``).

    Returns
    -------
    str
        Absolute URL.

    Examples
    --------
    >>> join_url("https://example.com/blog/", "best-widgets")
    'https://example.com/blog/best-widgets'
    """
    return urljoin(base, path)
