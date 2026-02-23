"""
integrations.proxy.proxy_pool
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Rotating proxy pool for web scraping and research operations.

Provides the :class:`ProxyPool` class for managing a pool of HTTP/SOCKS
proxies with health tracking, automatic rotation, failure detection, and
load balancing.  Used by the research agent to make web requests through
diverse IP addresses, avoiding rate limits and blocks.

Design references:
    - ARCHITECTURE.md  Section 4 (Integration Layer)
    - config/providers.yaml  ``proxy`` section
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, unique
from typing import Any, Dict, List, Optional

from src.core.errors import IntegrationError
from src.core.logger import get_logger, log_event

logger = get_logger("integrations.proxy.proxy_pool")


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


@unique
class ProxyProtocol(str, Enum):
    """Supported proxy protocols."""

    HTTP = "http"
    HTTPS = "https"
    SOCKS4 = "socks4"
    SOCKS5 = "socks5"


@unique
class ProxyStatus(str, Enum):
    """Health status of a proxy."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILED = "failed"
    BANNED = "banned"


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------


@dataclass
class ProxyEntry:
    """A single proxy in the pool.

    Attributes
    ----------
    proxy_id:
        Unique identifier for this proxy entry.
    host:
        Proxy server hostname or IP.
    port:
        Proxy server port.
    protocol:
        Proxy protocol.
    username:
        Authentication username (empty for unauthenticated proxies).
    password:
        Authentication password.
    country:
        ISO 3166-1 alpha-2 country code of the proxy's IP.
    status:
        Current health status.
    success_count:
        Number of successful requests through this proxy.
    failure_count:
        Number of failed requests through this proxy.
    consecutive_failures:
        Number of consecutive failures (resets on success).
    avg_response_time:
        Average response time in seconds.
    last_used_at:
        UTC timestamp of the last request through this proxy.
    last_checked_at:
        UTC timestamp of the last health check.
    in_use:
        Whether the proxy is currently assigned to an active request.
    metadata:
        Additional proxy-level data.
    """

    proxy_id: str
    host: str = ""
    port: int = 8080
    protocol: ProxyProtocol = ProxyProtocol.HTTP
    username: str = ""
    password: str = ""
    country: str = ""
    status: ProxyStatus = ProxyStatus.HEALTHY
    success_count: int = 0
    failure_count: int = 0
    consecutive_failures: int = 0
    avg_response_time: float = 0.0
    last_used_at: Optional[datetime] = None
    last_checked_at: Optional[datetime] = None
    in_use: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def url(self) -> str:
        """Return the proxy URL in ``protocol://host:port`` format."""
        if self.username and self.password:
            return f"{self.protocol.value}://{self.username}:{self.password}@{self.host}:{self.port}"
        return f"{self.protocol.value}://{self.host}:{self.port}"

    @property
    def reliability(self) -> float:
        """Compute a reliability score (0.0--1.0) based on success rate."""
        total = self.success_count + self.failure_count
        if total == 0:
            return 1.0
        return self.success_count / total


# ---------------------------------------------------------------------------
# ProxyPool
# ---------------------------------------------------------------------------


class ProxyPool:
    """Manages a pool of rotating HTTP/SOCKS proxies.

    Provides proxy acquisition, release, failure tracking, and automatic
    rotation.  Proxies with high failure rates are temporarily removed
    from the available pool.

    Parameters
    ----------
    proxies:
        Initial list of proxy entries to populate the pool.
    max_consecutive_failures:
        Number of consecutive failures before a proxy is marked as failed.
    rotation_strategy:
        Strategy for selecting the next proxy: ``"round_robin"``,
        ``"random"``, or ``"least_used"``.

    Usage::

        pool = ProxyPool(proxies=[
            ProxyEntry(proxy_id="p1", host="1.2.3.4", port=8080),
            ProxyEntry(proxy_id="p2", host="5.6.7.8", port=8080),
        ])
        proxy = pool.get_proxy()
        try:
            # Use proxy for HTTP request
            ...
        finally:
            pool.release_proxy(proxy.proxy_id, success=True)
    """

    def __init__(
        self,
        proxies: Optional[List[ProxyEntry]] = None,
        max_consecutive_failures: int = 5,
        rotation_strategy: str = "least_used",
    ) -> None:
        self._proxies: Dict[str, ProxyEntry] = {}
        self._max_consecutive_failures = max_consecutive_failures
        self._rotation_strategy = rotation_strategy
        self._rotation_index: int = 0
        self._total_requests: int = 0

        if proxies:
            for proxy in proxies:
                self._proxies[proxy.proxy_id] = proxy

        log_event(
            logger,
            "proxy_pool.init",
            pool_size=len(self._proxies),
            strategy=rotation_strategy,
        )

    # ------------------------------------------------------------------
    # Proxy acquisition
    # ------------------------------------------------------------------

    def get_proxy(
        self,
        *,
        country: str = "",
        protocol: Optional[ProxyProtocol] = None,
    ) -> ProxyEntry:
        """Acquire a proxy from the pool.

        Selects a healthy, available proxy based on the configured
        rotation strategy and marks it as in-use.

        Parameters
        ----------
        country:
            Optional country filter (ISO 3166-1 alpha-2 code).
        protocol:
            Optional protocol filter.

        Returns
        -------
        ProxyEntry
            The selected proxy.

        Raises
        ------
        IntegrationError
            If no healthy proxies are available.
        """
        candidates = [
            p
            for p in self._proxies.values()
            if p.status in (ProxyStatus.HEALTHY, ProxyStatus.DEGRADED) and not p.in_use
        ]

        if country:
            candidates = [p for p in candidates if p.country == country]
        if protocol:
            candidates = [p for p in candidates if p.protocol == protocol]

        if not candidates:
            raise IntegrationError(
                "No healthy proxies available in the pool",
                details={
                    "pool_size": len(self._proxies),
                    "healthy_count": self.get_healthy_count(),
                    "country_filter": country,
                    "protocol_filter": protocol.value if protocol else "",
                },
            )

        proxy = self._select_proxy(candidates)
        proxy.in_use = True
        proxy.last_used_at = datetime.now(timezone.utc)
        self._total_requests += 1

        logger.debug(
            "Acquired proxy %s (%s:%d, reliability=%.2f)",
            proxy.proxy_id,
            proxy.host,
            proxy.port,
            proxy.reliability,
        )
        return proxy

    def _select_proxy(self, candidates: List[ProxyEntry]) -> ProxyEntry:
        """Select a proxy from the candidate list based on rotation strategy.

        Parameters
        ----------
        candidates:
            Available healthy proxies.

        Returns
        -------
        ProxyEntry
            The selected proxy.
        """
        if self._rotation_strategy == "random":
            return random.choice(candidates)

        if self._rotation_strategy == "round_robin":
            self._rotation_index = self._rotation_index % len(candidates)
            proxy = candidates[self._rotation_index]
            self._rotation_index += 1
            return proxy

        # Default: least_used (select proxy with fewest total requests)
        return min(
            candidates,
            key=lambda p: p.success_count + p.failure_count,
        )

    # ------------------------------------------------------------------
    # Proxy release and failure tracking
    # ------------------------------------------------------------------

    def release_proxy(
        self,
        proxy_id: str,
        *,
        success: bool = True,
        response_time: float = 0.0,
    ) -> None:
        """Release a proxy back to the pool after use.

        Updates the proxy's statistics and marks it as available.

        Parameters
        ----------
        proxy_id:
            Identifier of the proxy to release.
        success:
            Whether the request through this proxy succeeded.
        response_time:
            Request response time in seconds.
        """
        proxy = self._proxies.get(proxy_id)
        if proxy is None:
            logger.warning("Attempted to release unknown proxy: %s", proxy_id)
            return

        proxy.in_use = False

        if success:
            proxy.success_count += 1
            proxy.consecutive_failures = 0
            if proxy.status == ProxyStatus.DEGRADED:
                proxy.status = ProxyStatus.HEALTHY
            # Update rolling average response time
            total = proxy.success_count + proxy.failure_count
            proxy.avg_response_time = (
                ((proxy.avg_response_time * (total - 1) + response_time) / total)
                if total > 0
                else response_time
            )
        else:
            proxy.failure_count += 1
            proxy.consecutive_failures += 1
            if proxy.consecutive_failures >= self._max_consecutive_failures:
                proxy.status = ProxyStatus.FAILED
                logger.warning(
                    "Proxy %s marked as FAILED after %d consecutive failures",
                    proxy_id,
                    proxy.consecutive_failures,
                )

        logger.debug(
            "Released proxy %s (success=%s, reliability=%.2f, status=%s)",
            proxy_id,
            success,
            proxy.reliability,
            proxy.status.value,
        )

    def mark_failed(
        self,
        proxy_id: str,
        *,
        reason: str = "",
    ) -> None:
        """Explicitly mark a proxy as failed.

        Parameters
        ----------
        proxy_id:
            Identifier of the proxy to mark as failed.
        reason:
            Human-readable reason for the failure.
        """
        proxy = self._proxies.get(proxy_id)
        if proxy is None:
            logger.warning("Attempted to mark unknown proxy as failed: %s", proxy_id)
            return

        proxy.status = ProxyStatus.FAILED
        proxy.in_use = False

        log_event(
            logger,
            "proxy_pool.mark_failed",
            proxy_id=proxy_id,
            reason=reason,
        )

    # ------------------------------------------------------------------
    # Rotation and management
    # ------------------------------------------------------------------

    def rotate(self) -> int:
        """Reset failed proxies to healthy status for retry.

        Proxies that were marked as failed are given another chance.
        Their consecutive failure counters are reset to allow them
        back into the available pool.

        Returns
        -------
        int
            Number of proxies that were rotated back to healthy status.
        """
        rotated = 0
        for proxy in self._proxies.values():
            if proxy.status == ProxyStatus.FAILED:
                proxy.status = ProxyStatus.DEGRADED
                proxy.consecutive_failures = 0
                proxy.in_use = False
                rotated += 1

        if rotated:
            log_event(
                logger,
                "proxy_pool.rotate",
                rotated=rotated,
                pool_size=len(self._proxies),
            )

        return rotated

    def add_proxy(self, proxy: ProxyEntry) -> None:
        """Add a new proxy to the pool.

        Parameters
        ----------
        proxy:
            Proxy entry to add.
        """
        self._proxies[proxy.proxy_id] = proxy
        logger.debug(
            "Added proxy %s to pool (%s:%d)", proxy.proxy_id, proxy.host, proxy.port
        )

    def remove_proxy(self, proxy_id: str) -> bool:
        """Remove a proxy from the pool.

        Parameters
        ----------
        proxy_id:
            Identifier of the proxy to remove.

        Returns
        -------
        bool
            ``True`` if the proxy was found and removed.
        """
        if proxy_id in self._proxies:
            del self._proxies[proxy_id]
            logger.debug("Removed proxy %s from pool", proxy_id)
            return True
        return False

    # ------------------------------------------------------------------
    # Pool status
    # ------------------------------------------------------------------

    def get_healthy_count(self) -> int:
        """Return the number of healthy (available) proxies.

        Returns
        -------
        int
            Count of proxies with ``HEALTHY`` or ``DEGRADED`` status
            that are not currently in use.
        """
        return sum(
            1
            for p in self._proxies.values()
            if p.status in (ProxyStatus.HEALTHY, ProxyStatus.DEGRADED) and not p.in_use
        )

    @property
    def total_size(self) -> int:
        """Return the total number of proxies in the pool."""
        return len(self._proxies)

    @property
    def total_requests(self) -> int:
        """Return the total number of proxy acquisitions."""
        return self._total_requests

    def get_stats(self) -> Dict[str, Any]:
        """Return pool statistics.

        Returns
        -------
        dict[str, Any]
            Pool statistics including counts by status.
        """
        status_counts: Dict[str, int] = {}
        for proxy in self._proxies.values():
            key = proxy.status.value
            status_counts[key] = status_counts.get(key, 0) + 1

        return {
            "total_proxies": self.total_size,
            "healthy_available": self.get_healthy_count(),
            "total_requests": self._total_requests,
            "status_breakdown": status_counts,
            "rotation_strategy": self._rotation_strategy,
        }

    def __repr__(self) -> str:
        return (
            f"ProxyPool(total={self.total_size}, "
            f"healthy={self.get_healthy_count()}, "
            f"strategy={self._rotation_strategy!r})"
        )
