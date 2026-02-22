"""
core.utils.hashing
~~~~~~~~~~~~~~~~~~

Hashing utilities for content fingerprinting and deduplication.

OpenClaw uses content hashes to detect duplicate articles, URL fingerprints
to avoid re-processing the same pages, and dedup keys to prevent publishing
substantially identical content across sites.

All hashes use SHA-256 by default for consistency and collision resistance.

Usage::

    from src.core.utils.hashing import content_hash, url_fingerprint, dedup_key

    h = content_hash("This is my article body text...")
    fp = url_fingerprint("https://example.com/product?ref=123&utm_source=google")
    dk = dedup_key(title="Best Widgets 2025", niche="widgets", url="https://...")
"""

from __future__ import annotations

import hashlib
import re
from typing import Optional
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse


# =====================================================================
# Constants
# =====================================================================

# Query parameters to strip when computing URL fingerprints (tracking params).
_TRACKING_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "ref", "fbclid", "gclid", "msclkid", "dclid", "twclid",
    "mc_cid", "mc_eid", "affiliate_id", "aff_id", "click_id",
})

# Default hash algorithm.
_DEFAULT_ALGORITHM = "sha256"


# =====================================================================
# Core helpers
# =====================================================================

def _hash_bytes(data: bytes, algorithm: str = _DEFAULT_ALGORITHM) -> str:
    """Return the hex digest of *data* using the specified algorithm.

    Parameters
    ----------
    data:
        Raw bytes to hash.
    algorithm:
        Hashlib algorithm name (default ``"sha256"``).

    Returns
    -------
    str
        Lowercase hexadecimal digest string.
    """
    h = hashlib.new(algorithm)
    h.update(data)
    return h.hexdigest()


def _normalize_text(text: str) -> str:
    """Normalize text for consistent hashing.

    * Lowercase
    * Collapse whitespace to single spaces
    * Strip leading/trailing whitespace

    Parameters
    ----------
    text:
        Raw input text.

    Returns
    -------
    str
        Normalized text.
    """
    text = text.lower().strip()
    text = re.sub(r"\s+", " ", text)
    return text


# =====================================================================
# Public API
# =====================================================================

def content_hash(
    text: str,
    *,
    normalize: bool = True,
    algorithm: str = _DEFAULT_ALGORITHM,
) -> str:
    """Compute a stable hash of article/content text.

    Parameters
    ----------
    text:
        The full body text of the content piece.
    normalize:
        If ``True`` (default), normalize whitespace and case before
        hashing so that trivial formatting differences produce the
        same hash.
    algorithm:
        Hash algorithm (default ``"sha256"``).

    Returns
    -------
    str
        Hex digest string.

    Examples
    --------
    >>> content_hash("Hello   World") == content_hash("hello world")
    True
    >>> content_hash("Hello World", normalize=False) != content_hash("hello world", normalize=False)
    True
    """
    if normalize:
        text = _normalize_text(text)
    return _hash_bytes(text.encode("utf-8"), algorithm)


def url_fingerprint(
    url: str,
    *,
    strip_tracking: bool = True,
    strip_fragment: bool = True,
    algorithm: str = _DEFAULT_ALGORITHM,
) -> str:
    """Compute a stable fingerprint for a URL.

    Strips tracking parameters, normalizes the scheme/host to lowercase,
    removes fragments, and sorts remaining query parameters so that
    equivalent URLs produce the same fingerprint.

    Parameters
    ----------
    url:
        The URL to fingerprint.
    strip_tracking:
        Remove known tracking/affiliate query parameters.
    strip_fragment:
        Remove the ``#fragment`` portion.
    algorithm:
        Hash algorithm (default ``"sha256"``).

    Returns
    -------
    str
        Hex digest string.

    Examples
    --------
    >>> fp1 = url_fingerprint("https://Example.com/page?b=2&a=1")
    >>> fp2 = url_fingerprint("https://example.com/page?a=1&b=2")
    >>> fp1 == fp2
    True
    >>> fp3 = url_fingerprint("https://example.com/page?a=1&utm_source=google")
    >>> fp1 == fp3
    True
    """
    parsed = urlparse(url)

    # Normalize scheme and host
    scheme = (parsed.scheme or "https").lower()
    netloc = (parsed.netloc or "").lower()

    # Strip trailing slash from path for consistency
    path = parsed.path.rstrip("/") or "/"

    # Process query parameters
    query_params = parse_qs(parsed.query, keep_blank_values=True)
    if strip_tracking:
        query_params = {
            k: v for k, v in query_params.items()
            if k.lower() not in _TRACKING_PARAMS
        }

    # Sort query parameters for deterministic ordering
    sorted_query = urlencode(
        sorted(
            ((k, v[0]) for k, v in query_params.items()),
            key=lambda pair: pair[0],
        )
    )

    # Build the canonical URL
    fragment = "" if strip_fragment else parsed.fragment
    canonical = urlunparse((scheme, netloc, path, "", sorted_query, fragment))

    return _hash_bytes(canonical.encode("utf-8"), algorithm)


def dedup_key(
    *,
    title: str,
    niche: str = "",
    url: str = "",
    algorithm: str = _DEFAULT_ALGORITHM,
) -> str:
    """Generate a deduplication key from content metadata.

    Combines normalized title, niche, and URL fingerprint into a single
    hash that can be used to detect near-duplicate content across sites.

    Parameters
    ----------
    title:
        Article or page title.
    niche:
        Niche/category label (e.g. ``"home-office-chairs"``).
    url:
        Optional source or target URL.
    algorithm:
        Hash algorithm (default ``"sha256"``).

    Returns
    -------
    str
        Hex digest dedup key.

    Examples
    --------
    >>> k1 = dedup_key(title="Best Widgets", niche="widgets")
    >>> k2 = dedup_key(title="  Best  WIDGETS ", niche="Widgets")
    >>> k1 == k2
    True
    """
    parts = [
        _normalize_text(title),
        _normalize_text(niche),
    ]
    if url:
        parts.append(url_fingerprint(url, algorithm=algorithm))
    combined = "|".join(parts)
    return _hash_bytes(combined.encode("utf-8"), algorithm)


def short_hash(text: str, length: int = 12) -> str:
    """Return a truncated content hash suitable for use as an ID suffix.

    Parameters
    ----------
    text:
        Input text to hash.
    length:
        Number of hex characters to return (max 64 for SHA-256).

    Returns
    -------
    str
        Truncated hex digest.

    Examples
    --------
    >>> len(short_hash("hello world"))
    12
    """
    full = content_hash(text, normalize=True)
    return full[:length]
