"""
integrations.proxy.proxy_pool
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Managed pool of proxy connections for web scraping and research tasks.

Provides :class:`ProxyPool` which maintains a set of proxy servers,
tracks their health, and distributes requests across healthy proxies
with automatic rotation.  Failed proxies are temporarily quarantined
and retested before being returned to the active pool.

Design references:
    - config/providers.yaml  ``proxies`` section
    - ARCHITECTURE.md  Section 4 (Integration Layer)

Usage::

    from src.integrations.proxy.proxy_pool import ProxyPool

    pool = ProxyPool(proxies=[
        "http://user:pass@proxy1.example.com:8080",
        "http://user:pass@proxy2.example.com:8080",
    ])
    proxy = pool.get_proxy()
    # ... use proxy for HTTP request ...
    pool.release_proxy(proxy)
"""

from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from src.core.errors import IntegrationError
from src.core.logger import get_logger, log_event

logger = get_logger("integrations.proxy.proxy_pool")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_MAX_FAILURES = 3
_DEFAULT_COOLDOWN_SECONDS = 300  # 5 minutes
_DEFAULT_HEALTH_CHECK_TIMEOUT = 10  # seconds


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------

@dataclass
class ProxyInfo:
    """Metadata and health tracking for a single proxy server.

    Attributes
    ----------
    url:
        Proxy URL including scheme, auth, host, and port
        (e.g. ``"http://user:pass@host:port"``).
    is_healthy:
        Whether the proxy is currently considered healthy.
    in_use:
        Whether the proxy is currently checked out for a request.
    total_requests:
        Lifetime request count through this proxy.
    total_failures:
        Lifetime failure count for this proxy.
    consecutive_failures:
        Number of consecutive failures (reset on success).
    last_used_at:
        UTC timestamp of the most recent checkout.
    last_failure_at:
        UTC timestamp of the most recent failure.
    cooldown_until:
        UTC timestamp when the proxy becomes eligible again after
        being quarantined (``None`` if not quarantined).
    response_time_ms:
        Most recent response time in milliseconds (0 if untested).
    tags:
        Arbitrary labels for filtering (e.g. ``"residential"``,
        ``"datacenter"``, ``"us"``).
    """

    url: str
    is_healthy: bool = True
    in_use: bool = False
    total_requests: int = 0
    total_failures: int = 0
    consecutive_failures: int = 0
    last_used_at: Optional[datetime] = None
    last_failure_at: Optional[datetime] = None
    cooldown_until: Optional[datetime] = None
    response_time_ms: float = 0.0
    tags: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# ProxyPool
# ---------------------------------------------------------------------------

class ProxyPool:
    """Managed pool of proxy connections with health tracking and rotation.

    Thread-safe: all mutable state is guarded by an internal lock so the
    pool can be shared across multiple threads or async tasks.

    Parameters
    ----------
    proxies:
        List of proxy URLs to populate the pool.
    max_failures:
        Number of consecutive failures before a proxy is quarantined.
    cooldown_seconds:
        How long (in seconds) a quarantined proxy must wait before
        being retested.
    rotation_strategy:
        How to select the next proxy.  One of ``"round_robin"``,
        ``"random"``, ``"least_used"``.
    """

    def __init__(
        self,
        proxies: Optional[List[str]] = None,
        max_failures: int = _DEFAULT_MAX_FAILURES,
        cooldown_seconds: int = _DEFAULT_COOLDOWN_SECONDS,
        rotation_strategy: str = "round_robin",
    ) -> None:
        self._lock = threading.Lock()
        self._max_failures = max_failures
        self._cooldown_seconds = cooldown_seconds
        self._rotation_strategy = rotation_strategy
        self._round_robin_index: int = 0

        # Build the internal proxy registry
        self._proxies: Dict[str, ProxyInfo] = {}
        for proxy_url in (proxies or []):
            normalised = proxy_url.strip()
            if normalised and normalised not in self._proxies:
                self._proxies[normalised] = ProxyInfo(url=normalised)

        log_event(
            logger,
            "proxy_pool.init",
            pool_size=len(self._proxies),
            strategy=rotation_strategy,
            max_failures=max_failures,
            cooldown_s=cooldown_seconds,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_available_proxies(self) -> List[ProxyInfo]:
        """Return proxies that are healthy, not in use, and not quarantined.

        Must be called with ``self._lock`` held.

        Returns
        -------
        list[ProxyInfo]
            Available proxy entries.
        """
        now = datetime.now(timezone.utc)
        available: List[ProxyInfo] = []

        for proxy in self._proxies.values():
            # Check if cooldown has expired
            if proxy.cooldown_until and now >= proxy.cooldown_until:
                proxy.is_healthy = True
                proxy.cooldown_until = None
                proxy.consecutive_failures = 0
                logger.debug(
                    "Proxy %s cooldown expired, returning to pool",
                    self._mask_url(proxy.url),
                )

            if proxy.is_healthy and not proxy.in_use:
                available.append(proxy)

        return available

    def _select_proxy(self, available: List[ProxyInfo]) -> ProxyInfo:
        """Select a proxy from the available pool using the configured strategy.

        Must be called with ``self._lock`` held.

        Parameters
        ----------
        available:
            List of available proxy entries.

        Returns
        -------
        ProxyInfo
            The selected proxy.
        """
        if self._rotation_strategy == "random":
            return random.choice(available)

        if self._rotation_strategy == "least_used":
            return min(available, key=lambda p: p.total_requests)

        # Default: round_robin
        idx = self._round_robin_index % len(available)
        self._round_robin_index = (self._round_robin_index + 1) % len(available)
        return available[idx]

    @staticmethod
    def _mask_url(url: str) -> str:
        """Mask credentials in a proxy URL for safe logging.

        Parameters
        ----------
        url:
            Proxy URL that may contain ``user:pass@``.

        Returns
        -------
        str
            URL with password masked.
        """
        if "@" in url:
            scheme_and_auth, host_part = url.rsplit("@", 1)
            if ":" in scheme_and_auth:
                # Find the last colon that separates user from password
                parts = scheme_and_auth.split("://", 1)
                if len(parts) == 2:
                    scheme = parts[0]
                    user_pass = parts[1]
                    if ":" in user_pass:
                        user = user_pass.split(":", 1)[0]
                        return f"{scheme}://{user}:***@{host_part}"
            return f"***@{host_part}"
        return url

    # ------------------------------------------------------------------
    # Public API methods
    # ------------------------------------------------------------------

    def get_proxy(self, *, tag: str = "") -> str:
        """Check out a healthy proxy from the pool.

        The proxy is marked as ``in_use`` until :meth:`release_proxy`
        is called.

        Parameters
        ----------
        tag:
            Optional tag filter.  If provided, only proxies with a
            matching tag are considered.

        Returns
        -------
        str
            Proxy URL string.

        Raises
        ------
        IntegrationError
            If no healthy proxies are available.
        """
        with self._lock:
            available = self._get_available_proxies()

            if tag:
                available = [p for p in available if tag in p.tags]

            if not available:
                healthy_count = sum(
                    1 for p in self._proxies.values() if p.is_healthy
                )
                in_use_count = sum(
                    1 for p in self._proxies.values() if p.in_use
                )
                raise IntegrationError(
                    "No healthy proxies available in pool",
                    details={
                        "pool_size": len(self._proxies),
                        "healthy": healthy_count,
                        "in_use": in_use_count,
                        "tag_filter": tag,
                    },
                )

            proxy = self._select_proxy(available)
            proxy.in_use = True
            proxy.total_requests += 1
            proxy.last_used_at = datetime.now(timezone.utc)

        log_event(
            logger,
            "proxy_pool.checkout",
            proxy=self._mask_url(proxy.url),
            total_requests=proxy.total_requests,
        )

        return proxy.url

    def release_proxy(self, proxy_url: str) -> None:
        """Return a proxy to the pool after use.

        Resets the ``in_use`` flag so the proxy becomes available for
        other requests.  If the proxy was used successfully, its
        consecutive failure counter is reset.

        Parameters
        ----------
        proxy_url:
            The proxy URL to release (must match what :meth:`get_proxy` returned).
        """
        with self._lock:
            proxy = self._proxies.get(proxy_url)
            if proxy is None:
                logger.warning(
                    "Attempted to release unknown proxy: %s",
                    self._mask_url(proxy_url),
                )
                return

            proxy.in_use = False
            # A successful release implies the request worked
            proxy.consecutive_failures = 0

        log_event(
            logger,
            "proxy_pool.release",
            proxy=self._mask_url(proxy_url),
        )

    def mark_failed(self, proxy_url: str) -> None:
        """Mark a proxy as having failed a request.

        Increments the failure counter.  If consecutive failures exceed
        ``max_failures``, the proxy is quarantined for ``cooldown_seconds``.

        Parameters
        ----------
        proxy_url:
            The proxy URL that failed.
        """
        with self._lock:
            proxy = self._proxies.get(proxy_url)
            if proxy is None:
                logger.warning(
                    "Attempted to mark unknown proxy as failed: %s",
                    self._mask_url(proxy_url),
                )
                return

            proxy.in_use = False
            proxy.total_failures += 1
            proxy.consecutive_failures += 1
            proxy.last_failure_at = datetime.now(timezone.utc)

            if proxy.consecutive_failures >= self._max_failures:
                proxy.is_healthy = False
                proxy.cooldown_until = datetime.fromtimestamp(
                    time.time() + self._cooldown_seconds, tz=timezone.utc
                )
                log_event(
                    logger,
                    "proxy_pool.quarantined",
                    proxy=self._mask_url(proxy_url),
                    consecutive_failures=proxy.consecutive_failures,
                    cooldown_until=proxy.cooldown_until.isoformat(),
                )
            else:
                log_event(
                    logger,
                    "proxy_pool.failure_recorded",
                    proxy=self._mask_url(proxy_url),
                    consecutive_failures=proxy.consecutive_failures,
                    max_failures=self._max_failures,
                )

    def rotate(self) -> str:
        """Get a fresh proxy, releasing the current one if applicable.

        Convenience method for single-proxy workflows where you just
        want the "next" proxy without tracking checkout/release manually.

        Returns
        -------
        str
            A new proxy URL from the pool.

        Raises
        ------
        IntegrationError
            If no healthy proxies are available.
        """
        with self._lock:
            # Release any proxies that are checked out
            for proxy in self._proxies.values():
                if proxy.in_use:
                    proxy.in_use = False

        # Get a fresh proxy
        return self.get_proxy()

    def get_healthy_count(self) -> int:
        """Return the number of currently healthy proxies.

        A proxy is considered healthy if it has not exceeded the failure
        threshold and is not in its cooldown period.

        Returns
        -------
        int
            Count of healthy proxies (regardless of in-use status).
        """
        with self._lock:
            now = datetime.now(timezone.utc)
            count = 0
            for proxy in self._proxies.values():
                # Check if cooldown has expired
                if proxy.cooldown_until and now >= proxy.cooldown_until:
                    proxy.is_healthy = True
                    proxy.cooldown_until = None
                    proxy.consecutive_failures = 0
                if proxy.is_healthy:
                    count += 1
            return count

    # ------------------------------------------------------------------
    # Pool management
    # ------------------------------------------------------------------

    def add_proxy(self, proxy_url: str, tags: Optional[List[str]] = None) -> None:
        """Add a new proxy to the pool.

        Parameters
        ----------
        proxy_url:
            Proxy URL to add.
        tags:
            Optional labels for the proxy.
        """
        normalised = proxy_url.strip()
        if not normalised:
            return

        with self._lock:
            if normalised not in self._proxies:
                self._proxies[normalised] = ProxyInfo(
                    url=normalised,
                    tags=tags or [],
                )
                log_event(
                    logger,
                    "proxy_pool.added",
                    proxy=self._mask_url(normalised),
                    pool_size=len(self._proxies),
                )

    def remove_proxy(self, proxy_url: str) -> bool:
        """Remove a proxy from the pool entirely.

        Parameters
        ----------
        proxy_url:
            Proxy URL to remove.

        Returns
        -------
        bool
            ``True`` if the proxy was found and removed.
        """
        with self._lock:
            if proxy_url in self._proxies:
                del self._proxies[proxy_url]
                log_event(
                    logger,
                    "proxy_pool.removed",
                    proxy=self._mask_url(proxy_url),
                    pool_size=len(self._proxies),
                )
                return True
            return False

    def get_stats(self) -> Dict[str, Any]:
        """Return a summary of pool health and usage statistics.

        Returns
        -------
        dict[str, Any]
            Pool statistics including total, healthy, in-use, and
            quarantined proxy counts plus aggregate request/failure totals.
        """
        with self._lock:
            total = len(self._proxies)
            healthy = sum(1 for p in self._proxies.values() if p.is_healthy)
            in_use = sum(1 for p in self._proxies.values() if p.in_use)
            quarantined = sum(
                1 for p in self._proxies.values()
                if not p.is_healthy and p.cooldown_until
            )
            total_requests = sum(p.total_requests for p in self._proxies.values())
            total_failures = sum(p.total_failures for p in self._proxies.values())

        return {
            "total_proxies": total,
            "healthy": healthy,
            "in_use": in_use,
            "quarantined": quarantined,
            "total_requests": total_requests,
            "total_failures": total_failures,
            "failure_rate": (
                round(total_failures / total_requests, 4)
                if total_requests > 0
                else 0.0
            ),
        }

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def pool_size(self) -> int:
        """Return the total number of proxies in the pool."""
        return len(self._proxies)

    def __repr__(self) -> str:
        stats = self.get_stats()
        return (
            f"ProxyPool(total={stats['total_proxies']}, "
            f"healthy={stats['healthy']}, "
            f"in_use={stats['in_use']}, "
            f"strategy={self._rotation_strategy!r})"
        )
