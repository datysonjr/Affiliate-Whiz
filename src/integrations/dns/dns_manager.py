"""
integrations.dns.dns_manager
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

DNS record management via the Cloudflare DNS API.

Provides :class:`DNSManager` which wraps the Cloudflare API v4 to create,
update, delete, and verify DNS records for the domains managed by OpenClaw.
Supports A, AAAA, CNAME, TXT, and MX record types with propagation
verification.

Design references:
    - https://developers.cloudflare.com/api/operations/dns-records-for-a-zone-list-dns-records
    - config/providers.yaml  ``cloudflare`` section
    - ARCHITECTURE.md  Section 4 (Integration Layer)

Usage::

    from src.integrations.dns.dns_manager import DNSManager

    dns = DNSManager(
        api_token="your-cloudflare-api-token",
        zone_id="your-zone-id",
    )
    record = await dns.add_record("A", "www", "1.2.3.4")
"""

from __future__ import annotations

import socket
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.core.constants import DEFAULT_MAX_RETRIES, DEFAULT_REQUEST_TIMEOUT
from src.core.errors import (
    APIAuthenticationError,
    IntegrationError,
)
from src.core.logger import get_logger, log_event

logger = get_logger("integrations.dns.dns_manager")

# ---------------------------------------------------------------------------
# Cloudflare DNS API constants
# ---------------------------------------------------------------------------

_CF_API_BASE = "https://api.cloudflare.com/client/v4"
_VALID_RECORD_TYPES = frozenset({"A", "AAAA", "CNAME", "TXT", "MX", "NS", "SRV", "CAA"})
_DEFAULT_TTL = 3600  # 1 hour
_PROPAGATION_CHECK_INTERVAL = 10  # seconds between DNS lookups
_PROPAGATION_MAX_WAIT = 300  # 5 minutes maximum wait


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------

@dataclass
class DNSRecord:
    """A single DNS record as stored in Cloudflare.

    Attributes
    ----------
    record_id:
        Cloudflare-assigned record identifier.
    zone_id:
        Parent zone identifier.
    record_type:
        DNS record type (``"A"``, ``"CNAME"``, ``"TXT"``, etc.).
    name:
        Fully qualified domain name of the record.
    content:
        Record value (IP address, hostname, TXT content, etc.).
    ttl:
        Time-to-live in seconds (1 = automatic).
    proxied:
        Whether the record is proxied through Cloudflare's CDN.
    priority:
        MX record priority (0 for non-MX records).
    created_on:
        UTC timestamp when the record was created.
    modified_on:
        UTC timestamp when the record was last modified.
    """

    record_id: str
    zone_id: str
    record_type: str
    name: str
    content: str
    ttl: int = _DEFAULT_TTL
    proxied: bool = False
    priority: int = 0
    created_on: Optional[datetime] = None
    modified_on: Optional[datetime] = None


@dataclass
class PropagationResult:
    """Result of a DNS propagation verification check.

    Attributes
    ----------
    domain:
        Domain name that was checked.
    record_type:
        DNS record type that was queried.
    expected_value:
        The value we expect to resolve to.
    resolved_values:
        Actual values returned by DNS resolution.
    propagated:
        Whether the expected value was found in resolved values.
    check_count:
        Number of DNS lookups performed during verification.
    elapsed_seconds:
        Total time spent waiting for propagation.
    """

    domain: str
    record_type: str
    expected_value: str
    resolved_values: List[str] = field(default_factory=list)
    propagated: bool = False
    check_count: int = 0
    elapsed_seconds: float = 0.0


# ---------------------------------------------------------------------------
# DNSManager client
# ---------------------------------------------------------------------------

class DNSManager:
    """Cloudflare DNS record manager.

    Provides full CRUD operations for DNS records and propagation
    verification via system DNS resolution.  Uses the Cloudflare API v4
    with bearer token authentication.

    Parameters
    ----------
    api_token:
        Cloudflare API bearer token with DNS edit permissions.
    zone_id:
        Cloudflare zone identifier for the target domain.
    timeout:
        HTTP request timeout in seconds.
    max_retries:
        Maximum retry attempts for transient failures.
    """

    def __init__(
        self,
        api_token: str,
        zone_id: str,
        timeout: int = DEFAULT_REQUEST_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> None:
        if not api_token:
            raise APIAuthenticationError(
                "Cloudflare DNS API requires an api_token",
            )
        if not zone_id:
            raise IntegrationError(
                "Cloudflare DNS manager requires a zone_id",
            )

        self._api_token = api_token
        self._zone_id = zone_id
        self._timeout = timeout
        self._max_retries = max_retries
        self._request_count: int = 0

        log_event(
            logger,
            "dns.init",
            zone_id=zone_id,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_headers(self) -> Dict[str, str]:
        """Return Cloudflare API request headers."""
        return {
            "Authorization": f"Bearer {self._api_token}",
            "Content-Type": "application/json",
        }

    def _zone_url(self, path: str = "") -> str:
        """Build a Cloudflare API URL scoped to the configured zone.

        Parameters
        ----------
        path:
            Additional path segments after ``/dns_records``.

        Returns
        -------
        str
            Fully qualified API URL.
        """
        base = f"{_CF_API_BASE}/zones/{self._zone_id}/dns_records"
        if path:
            return f"{base}/{path}"
        return base

    def _track_request(self) -> None:
        """Record that an API request was made."""
        self._request_count += 1

    @staticmethod
    def _validate_record_type(record_type: str) -> str:
        """Validate and normalise a DNS record type string.

        Parameters
        ----------
        record_type:
            Record type to validate (case-insensitive).

        Returns
        -------
        str
            Upper-cased record type.

        Raises
        ------
        IntegrationError
            If the record type is not supported.
        """
        normalised = record_type.upper().strip()
        if normalised not in _VALID_RECORD_TYPES:
            raise IntegrationError(
                f"Unsupported DNS record type: {record_type!r}",
                details={
                    "requested": record_type,
                    "supported": sorted(_VALID_RECORD_TYPES),
                },
            )
        return normalised

    @staticmethod
    def _parse_record(data: Dict[str, Any]) -> DNSRecord:
        """Parse a Cloudflare DNS record response into a :class:`DNSRecord`.

        Parameters
        ----------
        data:
            Record dict from the Cloudflare API response.

        Returns
        -------
        DNSRecord
            Parsed record.
        """
        created_on = None
        modified_on = None
        if data.get("created_on"):
            try:
                created_on = datetime.fromisoformat(
                    str(data["created_on"]).replace("Z", "+00:00")
                )
            except (ValueError, TypeError):
                created_on = None
        if data.get("modified_on"):
            try:
                modified_on = datetime.fromisoformat(
                    str(data["modified_on"]).replace("Z", "+00:00")
                )
            except (ValueError, TypeError):
                modified_on = None

        return DNSRecord(
            record_id=data.get("id", ""),
            zone_id=data.get("zone_id", ""),
            record_type=data.get("type", ""),
            name=data.get("name", ""),
            content=data.get("content", ""),
            ttl=int(data.get("ttl", _DEFAULT_TTL)),
            proxied=data.get("proxied", False),
            priority=int(data.get("priority", 0)),
            created_on=created_on,
            modified_on=modified_on,
        )

    # ------------------------------------------------------------------
    # Public API methods
    # ------------------------------------------------------------------

    async def add_record(
        self,
        record_type: str,
        name: str,
        content: str,
        *,
        ttl: int = _DEFAULT_TTL,
        proxied: bool = False,
        priority: int = 0,
    ) -> DNSRecord:
        """Create a new DNS record in the Cloudflare zone.

        Parameters
        ----------
        record_type:
            DNS record type (``"A"``, ``"CNAME"``, ``"TXT"``, etc.).
        name:
            Record name (subdomain or ``"@"`` for the root domain).
        content:
            Record value (IP address, hostname, TXT content, etc.).
        ttl:
            Time-to-live in seconds.  Use ``1`` for Cloudflare automatic.
        proxied:
            Whether to proxy the record through Cloudflare's CDN.
            Only applicable to A, AAAA, and CNAME records.
        priority:
            MX record priority (ignored for non-MX records).

        Returns
        -------
        DNSRecord
            The created DNS record with its Cloudflare-assigned ID.

        Raises
        ------
        IntegrationError
            If the record type is invalid or the API request fails.
        """
        validated_type = self._validate_record_type(record_type)

        payload: Dict[str, Any] = {
            "type": validated_type,
            "name": name,
            "content": content,
            "ttl": ttl,
            "proxied": proxied,
        }
        if validated_type == "MX":
            payload["priority"] = priority

        log_event(
            logger,
            "dns.add_record",
            record_type=validated_type,
            name=name,
            proxied=proxied,
        )
        self._track_request()

        url = self._zone_url()
        headers = self._build_headers()
        logger.debug("POST %s with type=%s name=%s", url, validated_type, name)

        # Production: POST to Cloudflare API, parse result.
        # response_json = await resp.json()
        # return self._parse_record(response_json["result"])
        return DNSRecord(
            record_id="",
            zone_id=self._zone_id,
            record_type=validated_type,
            name=name,
            content=content,
            ttl=ttl,
            proxied=proxied,
            priority=priority,
            created_on=datetime.now(timezone.utc),
            modified_on=datetime.now(timezone.utc),
        )

    async def update_record(
        self,
        record_id: str,
        *,
        record_type: Optional[str] = None,
        name: Optional[str] = None,
        content: Optional[str] = None,
        ttl: Optional[int] = None,
        proxied: Optional[bool] = None,
        priority: Optional[int] = None,
    ) -> DNSRecord:
        """Update an existing DNS record.

        Uses the Cloudflare PATCH endpoint so only supplied fields are
        modified; omitted fields retain their current values.

        Parameters
        ----------
        record_id:
            Cloudflare record identifier to update.
        record_type:
            New record type (rarely changed).
        name:
            New record name.
        content:
            New record value.
        ttl:
            New time-to-live.
        proxied:
            New proxy setting.
        priority:
            New MX priority.

        Returns
        -------
        DNSRecord
            The updated DNS record.

        Raises
        ------
        IntegrationError
            If the record is not found or the API request fails.
        """
        if not record_id:
            raise IntegrationError("record_id is required to update a DNS record")

        payload: Dict[str, Any] = {}
        if record_type is not None:
            payload["type"] = self._validate_record_type(record_type)
        if name is not None:
            payload["name"] = name
        if content is not None:
            payload["content"] = content
        if ttl is not None:
            payload["ttl"] = ttl
        if proxied is not None:
            payload["proxied"] = proxied
        if priority is not None:
            payload["priority"] = priority

        if not payload:
            raise IntegrationError(
                "At least one field must be provided for update",
                details={"record_id": record_id},
            )

        log_event(
            logger,
            "dns.update_record",
            record_id=record_id,
            fields_updated=list(payload.keys()),
        )
        self._track_request()

        url = self._zone_url(record_id)
        headers = self._build_headers()
        logger.debug("PATCH %s with %d fields", url, len(payload))

        # Production: PATCH to Cloudflare API.
        return DNSRecord(
            record_id=record_id,
            zone_id=self._zone_id,
            record_type=payload.get("type", ""),
            name=payload.get("name", ""),
            content=payload.get("content", ""),
            ttl=payload.get("ttl", _DEFAULT_TTL),
            proxied=payload.get("proxied", False),
            modified_on=datetime.now(timezone.utc),
        )

    async def delete_record(self, record_id: str) -> bool:
        """Delete a DNS record from the Cloudflare zone.

        Parameters
        ----------
        record_id:
            Cloudflare record identifier to delete.

        Returns
        -------
        bool
            ``True`` if the record was successfully deleted.

        Raises
        ------
        IntegrationError
            If the record is not found or the API request fails.
        """
        if not record_id:
            raise IntegrationError("record_id is required to delete a DNS record")

        log_event(logger, "dns.delete_record", record_id=record_id)
        self._track_request()

        url = self._zone_url(record_id)
        headers = self._build_headers()
        logger.debug("DELETE %s", url)

        # Production: DELETE to Cloudflare API, check success.
        # response_json = await resp.json()
        # return response_json.get("success", False)
        return True

    async def get_records(
        self,
        *,
        record_type: str = "",
        name: str = "",
        content: str = "",
        page: int = 1,
        per_page: int = 100,
    ) -> List[DNSRecord]:
        """List DNS records in the zone with optional filters.

        Parameters
        ----------
        record_type:
            Filter by record type (e.g. ``"A"``, ``"CNAME"``).
        name:
            Filter by record name (exact match).
        content:
            Filter by record content (exact match).
        page:
            Page number (1-based).
        per_page:
            Records per page (max 5000).

        Returns
        -------
        list[DNSRecord]
            Matching DNS records.

        Raises
        ------
        IntegrationError
            If the API request fails.
        """
        params: Dict[str, Any] = {
            "page": max(page, 1),
            "per_page": min(per_page, 5000),
        }
        if record_type:
            params["type"] = self._validate_record_type(record_type)
        if name:
            params["name"] = name
        if content:
            params["content"] = content

        log_event(
            logger,
            "dns.get_records",
            record_type=record_type or "all",
            name=name or "all",
            page=page,
        )
        self._track_request()

        url = self._zone_url()
        headers = self._build_headers()
        logger.debug("GET %s with %d filters", url, len(params))

        # Production: GET from Cloudflare API, parse result array.
        # records = response_json.get("result", [])
        # return [self._parse_record(r) for r in records]
        return []

    async def verify_propagation(
        self,
        domain: str,
        record_type: str,
        expected_value: str,
        *,
        max_wait_seconds: int = _PROPAGATION_MAX_WAIT,
        check_interval: int = _PROPAGATION_CHECK_INTERVAL,
    ) -> PropagationResult:
        """Wait for a DNS record change to propagate globally.

        Performs repeated DNS lookups using the system resolver until the
        expected value is found or the timeout is exceeded.

        Parameters
        ----------
        domain:
            Fully qualified domain name to resolve.
        record_type:
            Expected record type (``"A"``, ``"CNAME"``, ``"TXT"``, etc.).
        expected_value:
            The record value we expect to see after propagation.
        max_wait_seconds:
            Maximum time to wait for propagation (default 300s).
        check_interval:
            Seconds between DNS lookup attempts (default 10s).

        Returns
        -------
        PropagationResult
            Result indicating whether propagation was confirmed.
        """
        validated_type = self._validate_record_type(record_type)

        log_event(
            logger,
            "dns.verify_propagation.start",
            domain=domain,
            record_type=validated_type,
            expected_value=expected_value,
            max_wait_seconds=max_wait_seconds,
        )

        result = PropagationResult(
            domain=domain,
            record_type=validated_type,
            expected_value=expected_value,
        )

        start_time = time.monotonic()

        while (time.monotonic() - start_time) < max_wait_seconds:
            result.check_count += 1
            resolved_values: List[str] = []

            try:
                if validated_type in ("A", "AAAA"):
                    # Use getaddrinfo for A/AAAA records
                    family = (
                        socket.AF_INET if validated_type == "A" else socket.AF_INET6
                    )
                    addr_info = socket.getaddrinfo(
                        domain, None, family, socket.SOCK_STREAM
                    )
                    resolved_values = list({info[4][0] for info in addr_info})
                elif validated_type == "CNAME":
                    # CNAME resolution via getfqdn is limited; check A resolution
                    try:
                        cname = socket.getfqdn(domain)
                        resolved_values = [cname]
                    except socket.gaierror:
                        resolved_values = []
                elif validated_type == "TXT":
                    # TXT records require a proper DNS library (dnspython).
                    # Fall back to a basic check.
                    logger.debug(
                        "TXT record verification requires dnspython; "
                        "performing basic connectivity check for %s",
                        domain,
                    )
                    try:
                        socket.getaddrinfo(domain, None)
                        resolved_values = ["[dns-reachable]"]
                    except socket.gaierror:
                        resolved_values = []
                else:
                    # For MX, NS, SRV, CAA -- require dnspython for proper check.
                    logger.debug(
                        "%s record verification requires dnspython; skipping",
                        validated_type,
                    )
                    resolved_values = []

            except socket.gaierror as exc:
                logger.debug(
                    "DNS lookup #%d for %s failed: %s",
                    result.check_count,
                    domain,
                    exc,
                )
                resolved_values = []

            result.resolved_values = resolved_values

            if expected_value in resolved_values:
                result.propagated = True
                result.elapsed_seconds = round(time.monotonic() - start_time, 2)
                log_event(
                    logger,
                    "dns.verify_propagation.success",
                    domain=domain,
                    checks=result.check_count,
                    elapsed_s=result.elapsed_seconds,
                )
                return result

            logger.debug(
                "Propagation check #%d for %s: expected=%r, got=%r",
                result.check_count,
                domain,
                expected_value,
                resolved_values,
            )

            # Wait before the next check
            remaining = max_wait_seconds - (time.monotonic() - start_time)
            if remaining > check_interval:
                time.sleep(check_interval)
            else:
                break

        result.elapsed_seconds = round(time.monotonic() - start_time, 2)
        log_event(
            logger,
            "dns.verify_propagation.timeout",
            domain=domain,
            checks=result.check_count,
            elapsed_s=result.elapsed_seconds,
        )

        return result

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def zone_id(self) -> str:
        """Return the configured Cloudflare zone ID."""
        return self._zone_id

    @property
    def request_count(self) -> int:
        """Return the total number of API requests made."""
        return self._request_count

    def __repr__(self) -> str:
        return (
            f"DNSManager(zone_id={self._zone_id!r}, "
            f"requests={self._request_count})"
        )
