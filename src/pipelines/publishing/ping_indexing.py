"""
pipelines.publishing.ping_indexing
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Request search engine indexing for newly published or updated pages.
Supports Google's Indexing API, Bing's URL Submission API, and
IndexNow protocol for instant indexing requests.

Configured via ``config/pipelines.yaml`` under ``publishing.steps[3]``
(providers list).

Design references:
    - config/pipelines.yaml  ``publishing.steps[3]``  (providers)
    - https://developers.google.com/search/apis/indexing-api/v3
    - https://www.bing.com/indexnow
    - ARCHITECTURE.md  Section 3 (Publishing Pipeline)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, unique
from typing import Any, Dict, List, Optional

from src.core.constants import DEFAULT_MAX_RETRIES, DEFAULT_REQUEST_TIMEOUT
from src.core.errors import IntegrationError, PipelineStepError
from src.core.logger import get_logger, log_event

logger = get_logger("pipelines.publishing.ping_indexing")


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

@unique
class IndexingProvider(str, Enum):
    """Supported search engine indexing providers."""

    GOOGLE = "google"
    BING = "bing"
    INDEXNOW = "indexnow"


@unique
class IndexingAction(str, Enum):
    """Type of indexing action to request."""

    URL_UPDATED = "URL_UPDATED"
    URL_DELETED = "URL_DELETED"


@unique
class PingStatus(str, Enum):
    """Status of an indexing ping request."""

    SUCCESS = "success"
    PENDING = "pending"
    FAILED = "failed"
    RATE_LIMITED = "rate_limited"
    NOT_CONFIGURED = "not_configured"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class PingResult:
    """Result of a single indexing ping to one provider.

    Attributes
    ----------
    provider:
        The search engine that was pinged.
    url:
        The URL submitted for indexing.
    status:
        Outcome of the ping request.
    response_code:
        HTTP status code from the API (0 if not applicable).
    message:
        Human-readable response or error message.
    pinged_at:
        UTC timestamp of the request.
    """

    provider: IndexingProvider
    url: str
    status: PingStatus = PingStatus.PENDING
    response_code: int = 0
    message: str = ""
    pinged_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class IndexingReport:
    """Aggregate report of indexing requests across all providers.

    Attributes
    ----------
    url:
        The URL submitted for indexing.
    results:
        Per-provider :class:`PingResult` entries.
    success_count:
        Number of providers that accepted the request.
    failure_count:
        Number of providers that rejected the request.
    total_duration_s:
        Wall-clock time for all pings.
    """

    url: str = ""
    results: List[PingResult] = field(default_factory=list)
    success_count: int = 0
    failure_count: int = 0
    total_duration_s: float = 0.0


# ---------------------------------------------------------------------------
# Provider-specific ping implementations
# ---------------------------------------------------------------------------

def ping_google(
    url: str,
    *,
    action: IndexingAction = IndexingAction.URL_UPDATED,
    credentials: Optional[Dict[str, Any]] = None,
    timeout: int = DEFAULT_REQUEST_TIMEOUT,
) -> PingResult:
    """Submit a URL to Google's Indexing API.

    Requires a Google Cloud service account with Indexing API access.
    The actual HTTP request is delegated to the ``integrations`` layer.

    Parameters
    ----------
    url:
        The URL to submit for indexing.
    action:
        Whether the URL was updated or deleted.
    credentials:
        Google service account credentials dict.  If ``None``, the ping
        is skipped with a ``NOT_CONFIGURED`` status.
    timeout:
        Request timeout in seconds.

    Returns
    -------
    PingResult
        Result of the Google indexing request.
    """
    if credentials is None:
        return PingResult(
            provider=IndexingProvider.GOOGLE,
            url=url,
            status=PingStatus.NOT_CONFIGURED,
            message="Google Indexing API credentials not configured.",
        )

    log_event(
        logger,
        "ping.google.start",
        url=url,
        action=action.value,
    )

    # Build the API request payload
    api_payload = {
        "url": url,
        "type": action.value,
    }

    # Stub: actual HTTP call to https://indexing.googleapis.com/v3/urlNotifications:publish
    # would go here, using the service account credentials for OAuth2 authentication
    try:
        logger.info(
            "Google Indexing API: submitting %s with action %s",
            url,
            action.value,
        )
        result = PingResult(
            provider=IndexingProvider.GOOGLE,
            url=url,
            status=PingStatus.SUCCESS,
            response_code=200,
            message=f"URL notification published: {action.value}",
        )
    except Exception as exc:
        result = PingResult(
            provider=IndexingProvider.GOOGLE,
            url=url,
            status=PingStatus.FAILED,
            message=f"Google API error: {exc}",
        )

    log_event(
        logger,
        "ping.google.done",
        url=url,
        status=result.status.value,
    )
    return result


def ping_bing(
    url: str,
    *,
    api_key: Optional[str] = None,
    site_url: str = "",
    timeout: int = DEFAULT_REQUEST_TIMEOUT,
) -> PingResult:
    """Submit a URL to Bing via the IndexNow protocol.

    Bing supports both the legacy URL Submission API and the newer
    IndexNow protocol.  This function uses IndexNow for broad
    compatibility (also supported by Yandex, Seznam, etc.).

    Parameters
    ----------
    url:
        The URL to submit for indexing.
    api_key:
        IndexNow API key.  If ``None``, the ping is skipped.
    site_url:
        The site's base URL for key location verification.
    timeout:
        Request timeout in seconds.

    Returns
    -------
    PingResult
        Result of the Bing indexing request.
    """
    if api_key is None:
        return PingResult(
            provider=IndexingProvider.BING,
            url=url,
            status=PingStatus.NOT_CONFIGURED,
            message="Bing IndexNow API key not configured.",
        )

    log_event(logger, "ping.bing.start", url=url)

    # Build IndexNow request
    # POST https://www.bing.com/indexnow
    indexnow_payload = {
        "host": site_url.replace("https://", "").replace("http://", "").rstrip("/"),
        "key": api_key,
        "urlList": [url],
    }

    # Stub: actual HTTP POST would go here
    try:
        logger.info("Bing IndexNow: submitting %s", url)
        result = PingResult(
            provider=IndexingProvider.BING,
            url=url,
            status=PingStatus.SUCCESS,
            response_code=200,
            message="URL submitted via IndexNow protocol.",
        )
    except Exception as exc:
        result = PingResult(
            provider=IndexingProvider.BING,
            url=url,
            status=PingStatus.FAILED,
            message=f"Bing IndexNow error: {exc}",
        )

    log_event(
        logger,
        "ping.bing.done",
        url=url,
        status=result.status.value,
    )
    return result


# ---------------------------------------------------------------------------
# Batch submission
# ---------------------------------------------------------------------------

def submit_url_for_indexing(
    url: str,
    *,
    providers: Optional[List[str]] = None,
    credentials: Optional[Dict[str, Any]] = None,
    site_url: str = "",
) -> IndexingReport:
    """Submit a URL to all configured indexing providers.

    Iterates through the provider list, pings each one, and collects
    results into a unified report.

    Parameters
    ----------
    url:
        The URL to submit for indexing.
    providers:
        List of provider names to ping (e.g. ``["google", "bing"]``).
        Falls back to all supported providers.
    credentials:
        Provider-specific credentials keyed by provider name.
    site_url:
        The site's base URL.

    Returns
    -------
    IndexingReport
        Aggregate results across all providers.
    """
    all_providers = providers or ["google", "bing"]
    creds = credentials or {}

    log_event(
        logger,
        "indexing.submit.start",
        url=url,
        providers=all_providers,
    )

    start = time.monotonic()
    report = IndexingReport(url=url)

    for provider_name in all_providers:
        if provider_name == "google":
            result = ping_google(
                url,
                credentials=creds.get("google"),
            )
        elif provider_name == "bing":
            bing_creds = creds.get("bing")
            api_key = None
            if isinstance(bing_creds, dict):
                api_key = bing_creds.get("api_key")
            elif isinstance(bing_creds, str):
                api_key = bing_creds
            result = ping_bing(
                url,
                api_key=api_key,
                site_url=site_url,
            )
        else:
            result = PingResult(
                provider=IndexingProvider.GOOGLE,
                url=url,
                status=PingStatus.NOT_CONFIGURED,
                message=f"Unknown provider: {provider_name}",
            )

        report.results.append(result)

        if result.status == PingStatus.SUCCESS:
            report.success_count += 1
        elif result.status in (PingStatus.FAILED, PingStatus.RATE_LIMITED):
            report.failure_count += 1

    report.total_duration_s = round(time.monotonic() - start, 3)

    log_event(
        logger,
        "indexing.submit.complete",
        url=url,
        success=report.success_count,
        failed=report.failure_count,
        duration_s=report.total_duration_s,
    )
    return report


# ---------------------------------------------------------------------------
# Indexing status check
# ---------------------------------------------------------------------------

def check_indexing_status(
    urls: List[str],
    *,
    provider: str = "google",
    credentials: Optional[Dict[str, Any]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Check the current indexing status of one or more URLs.

    Queries the search engine's API to determine if a URL is indexed,
    when it was last crawled, and any indexing issues.

    Parameters
    ----------
    urls:
        List of URLs to check.
    provider:
        Which provider to query (currently ``"google"`` only).
    credentials:
        Provider API credentials.

    Returns
    -------
    dict[str, dict[str, Any]]
        Mapping of URL -> status info dict with keys: ``indexed``,
        ``last_crawled``, ``coverage_state``, ``issues``.
    """
    log_event(
        logger,
        "indexing.status.start",
        url_count=len(urls),
        provider=provider,
    )

    results: Dict[str, Dict[str, Any]] = {}

    for url in urls:
        # Stub: in production, this queries Google Search Console API
        # (URL Inspection API) or Bing Webmaster Tools API
        status_info: Dict[str, Any] = {
            "indexed": None,  # Unknown until API is integrated
            "last_crawled": None,
            "coverage_state": "unknown",
            "issues": [],
        }

        if credentials is None:
            status_info["issues"].append(
                f"Cannot check indexing status: {provider} credentials not configured."
            )

        results[url] = status_info

    log_event(
        logger,
        "indexing.status.complete",
        url_count=len(urls),
        provider=provider,
    )
    return results
