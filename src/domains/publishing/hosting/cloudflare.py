"""
domains.publishing.hosting.cloudflare
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Cloudflare Pages and CDN integration for the OpenClaw publishing domain.

Provides the :class:`CloudflareHosting` class for managing Cloudflare Pages
deployments, DNS configuration, domain management, and cache purging via
the Cloudflare API v4.

Design references:
    - https://developers.cloudflare.com/api/
    - https://developers.cloudflare.com/pages/
    - ARCHITECTURE.md  Section 4 (Publishing Domain)
    - config/providers.yaml  ``hosting.cloudflare`` section
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.core.constants import DEFAULT_MAX_RETRIES, DEFAULT_REQUEST_TIMEOUT
from src.core.errors import IntegrationError, APIAuthenticationError
from src.core.logger import get_logger, log_event

# ---------------------------------------------------------------------------
# Optional dependency: requests
# ---------------------------------------------------------------------------
try:
    import requests  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    requests = None  # type: ignore[assignment]

logger = get_logger("publishing.hosting.cloudflare")

_BASE_URL = "https://api.cloudflare.com/client/v4"


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------

@dataclass
class CloudflareDeployment:
    """A single Cloudflare Pages deployment record.

    Attributes
    ----------
    deployment_id:
        Cloudflare-assigned deployment identifier.
    project_name:
        Pages project name.
    url:
        Deployment preview URL.
    production_url:
        Production URL (only for production deployments).
    environment:
        Deployment environment (``"production"`` or ``"preview"``).
    status:
        Deployment status (``"active"``, ``"building"``, ``"failure"``).
    created_at:
        UTC creation timestamp.
    modified_at:
        UTC last status change timestamp.
    source_branch:
        Git branch that triggered the deployment.
    commit_hash:
        Git commit hash.
    commit_message:
        Git commit message.
    metadata:
        Additional Cloudflare-specific data.
    """

    deployment_id: str
    project_name: str = ""
    url: str = ""
    production_url: str = ""
    environment: str = "production"
    status: str = "building"
    created_at: Optional[datetime] = None
    modified_at: Optional[datetime] = None
    source_branch: str = ""
    commit_hash: str = ""
    commit_message: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CloudflarePagesProject:
    """Summary of a Cloudflare Pages project.

    Attributes
    ----------
    project_id:
        Project identifier.
    name:
        Project name.
    subdomain:
        Default ``*.pages.dev`` subdomain.
    production_branch:
        Git branch for production deployments.
    domains:
        Custom domains attached to the project.
    latest_deployment_id:
        ID of the most recent deployment.
    latest_deployment_status:
        Status of the most recent deployment.
    created_at:
        UTC creation timestamp.
    """

    project_id: str
    name: str = ""
    subdomain: str = ""
    production_branch: str = "main"
    domains: List[str] = field(default_factory=list)
    latest_deployment_id: str = ""
    latest_deployment_status: str = ""
    created_at: Optional[datetime] = None


@dataclass
class CachePurgeResult:
    """Result of a cache purge operation.

    Attributes
    ----------
    zone_id:
        Zone that was purged.
    purge_type:
        Type of purge (``"everything"``, ``"files"``, ``"tags"``,
        ``"prefixes"``).
    files_purged:
        Number of individual URLs purged (0 for ``"everything"``).
    success:
        Whether the purge was successful.
    """

    zone_id: str
    purge_type: str = "everything"
    files_purged: int = 0
    success: bool = True


# ---------------------------------------------------------------------------
# CloudflareHosting client
# ---------------------------------------------------------------------------

class CloudflareHosting:
    """Client for managing hosting via the Cloudflare API v4.

    Supports Cloudflare Pages deployments, DNS record management, domain
    configuration, and CDN cache purging.  Authenticates with an API
    token (recommended) or API key + email combination.

    Parameters
    ----------
    api_token:
        Cloudflare API token with appropriate permissions.
    account_id:
        Cloudflare account identifier (required for Pages operations).
    zone_id:
        Default Cloudflare zone ID (for DNS and cache operations).
    timeout:
        Per-request HTTP timeout in seconds.
    max_retries:
        Maximum retry attempts for transient failures.

    Raises
    ------
    IntegrationError
        If the ``requests`` library is not installed.
    APIAuthenticationError
        If ``api_token`` is empty.
    """

    def __init__(
        self,
        api_token: str,
        account_id: str = "",
        zone_id: str = "",
        timeout: int = DEFAULT_REQUEST_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> None:
        if requests is None:
            raise IntegrationError(
                "The 'requests' package is required for CloudflareHosting. "
                "Install it with: pip install requests"
            )
        if not api_token:
            raise APIAuthenticationError(
                "Cloudflare hosting integration requires an api_token",
                details={"account_id": account_id},
            )

        self._api_token = api_token
        self._account_id = account_id
        self._zone_id = zone_id
        self._timeout = timeout
        self._max_retries = max_retries
        self._request_count: int = 0
        self.logger: logging.Logger = get_logger("publishing.hosting.cloudflare")

        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
        })

        log_event(
            logger, "cloudflare.init",
            has_account_id=bool(account_id), has_zone_id=bool(zone_id),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _api_request(
        self,
        method: str,
        path: str,
        *,
        json_data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Execute an authenticated request against the Cloudflare API.

        Parameters
        ----------
        method:
            HTTP method.
        path:
            API path relative to the base URL.
        json_data:
            Optional JSON body.
        params:
            Optional query parameters.

        Returns
        -------
        dict
            The ``result`` field from the Cloudflare JSON envelope.

        Raises
        ------
        IntegrationError
            If the request fails or the API returns an error.
        """
        url = f"{_BASE_URL}{path}"

        try:
            response = self._session.request(
                method=method, url=url,
                json=json_data, params=params,
                timeout=self._timeout,
            )
            response.raise_for_status()
            self._request_count += 1
            body = response.json()
        except Exception as exc:
            raise IntegrationError(
                f"Cloudflare API request failed: {method} {path}",
                details={
                    "method": method, "path": path,
                    "status_code": getattr(
                        getattr(exc, "response", None), "status_code", None
                    ),
                },
                cause=exc,
            ) from exc

        if not body.get("success", False):
            errors = body.get("errors", [])
            error_msg = "; ".join(
                e.get("message", "Unknown error") for e in errors
            ) if errors else "Unknown Cloudflare API error"
            raise IntegrationError(
                f"Cloudflare API error: {error_msg}",
                details={"errors": errors, "path": path},
            )

        return body.get("result", {})

    @staticmethod
    def _parse_timestamp(value: Any) -> Optional[datetime]:
        """Parse an ISO 8601 timestamp from the Cloudflare API.

        Parameters
        ----------
        value:
            ISO 8601 string, or ``None``.

        Returns
        -------
        datetime or None
            UTC datetime.
        """
        if not value:
            return None
        try:
            return datetime.fromisoformat(
                str(value).replace("Z", "+00:00")
            ).astimezone(timezone.utc)
        except (ValueError, TypeError):
            return None

    # ------------------------------------------------------------------
    # Pages deployments
    # ------------------------------------------------------------------

    def deploy(
        self,
        project_name: str,
        *,
        branch: str = "main",
    ) -> CloudflareDeployment:
        """Trigger a new Cloudflare Pages deployment.

        For Git-connected projects this triggers a build from the specified
        branch.

        Parameters
        ----------
        project_name:
            Cloudflare Pages project name.
        branch:
            Git branch to deploy.

        Returns
        -------
        CloudflareDeployment
            The initiated deployment record.

        Raises
        ------
        IntegrationError
            If the account_id is not set or the deployment fails.
        """
        if not self._account_id:
            raise IntegrationError(
                "account_id is required for Cloudflare Pages deployments"
            )

        log_event(
            logger, "cloudflare.deploy",
            project=project_name, branch=branch,
        )

        path = (
            f"/accounts/{self._account_id}"
            f"/pages/projects/{project_name}/deployments"
        )
        data = self._api_request("POST", path)

        trigger = data.get("deployment_trigger", {}).get("metadata", {})
        return CloudflareDeployment(
            deployment_id=data.get("id", ""),
            project_name=project_name,
            url=data.get("url", ""),
            production_url=(data.get("aliases", [""])[0] if data.get("aliases") else ""),
            environment=data.get("environment", "production"),
            status=data.get("latest_stage", {}).get("status", "building"),
            created_at=self._parse_timestamp(data.get("created_on")),
            modified_at=self._parse_timestamp(data.get("modified_on")),
            source_branch=trigger.get("branch", branch),
            commit_hash=trigger.get("commit_hash", ""),
            commit_message=trigger.get("commit_message", ""),
            metadata=data,
        )

    def get_pages_projects(self) -> List[CloudflarePagesProject]:
        """List all Cloudflare Pages projects in the account.

        Returns
        -------
        list[CloudflarePagesProject]
            Project summaries.

        Raises
        ------
        IntegrationError
            If the account_id is not set or the request fails.
        """
        if not self._account_id:
            raise IntegrationError(
                "account_id is required to list Cloudflare Pages projects"
            )

        log_event(logger, "cloudflare.get_pages_projects")

        path = f"/accounts/{self._account_id}/pages/projects"
        data = self._api_request("GET", path)

        projects: List[CloudflarePagesProject] = []
        items = data if isinstance(data, list) else [data] if data else []

        for item in items:
            latest = item.get("latest_deployment", {}) or {}
            domains_list = [
                d.get("name", "") for d in (item.get("domains", []) or [])
            ]
            projects.append(CloudflarePagesProject(
                project_id=item.get("id", ""),
                name=item.get("name", ""),
                subdomain=item.get("subdomain", ""),
                production_branch=item.get("production_branch", "main"),
                domains=domains_list,
                latest_deployment_id=latest.get("id", ""),
                latest_deployment_status=latest.get("latest_stage", {}).get("status", ""),
                created_at=self._parse_timestamp(item.get("created_on")),
            ))

        self.logger.debug("Retrieved %d Pages projects", len(projects))
        return projects

    # ------------------------------------------------------------------
    # DNS management
    # ------------------------------------------------------------------

    def configure_dns(
        self,
        name: str,
        content: str,
        *,
        record_type: str = "CNAME",
        ttl: int = 1,
        proxied: bool = True,
        zone_id: str = "",
    ) -> Dict[str, Any]:
        """Create or update a DNS record in a Cloudflare zone.

        Parameters
        ----------
        name:
            DNS record name (e.g. ``"www.example.com"``).
        content:
            Record value (IP address, CNAME target, etc.).
        record_type:
            DNS record type (``"A"``, ``"AAAA"``, ``"CNAME"``, ``"TXT"``).
        ttl:
            Time-to-live (``1`` for Cloudflare automatic).
        proxied:
            Whether to proxy traffic through Cloudflare.
        zone_id:
            Cloudflare zone ID.  Falls back to the instance default.

        Returns
        -------
        dict[str, Any]
            The created or updated DNS record data.

        Raises
        ------
        IntegrationError
            If no zone_id is available or the API call fails.
        """
        effective_zone = zone_id or self._zone_id
        if not effective_zone:
            raise IntegrationError("zone_id is required for DNS operations")

        payload: Dict[str, Any] = {
            "type": record_type,
            "name": name,
            "content": content,
            "ttl": ttl,
            "proxied": proxied,
        }

        log_event(
            logger, "cloudflare.configure_dns",
            name=name, record_type=record_type, proxied=proxied,
        )

        path = f"/zones/{effective_zone}/dns_records"
        data = self._api_request("POST", path, json_data=payload)

        self.logger.info(
            "Created DNS %s record '%s' -> '%s' (proxied=%s)",
            record_type, name, content, proxied,
        )
        return data

    # ------------------------------------------------------------------
    # Cache management
    # ------------------------------------------------------------------

    def purge_cache(
        self,
        *,
        purge_everything: bool = False,
        files: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        prefixes: Optional[List[str]] = None,
        zone_id: str = "",
    ) -> CachePurgeResult:
        """Purge cached content from the Cloudflare CDN.

        Parameters
        ----------
        purge_everything:
            If ``True``, purge all cached files for the zone.
        files:
            List of specific URLs to purge.
        tags:
            List of cache tags to purge (Enterprise only).
        prefixes:
            List of URL prefixes to purge (Enterprise only).
        zone_id:
            Cloudflare zone ID.  Falls back to the instance default.

        Returns
        -------
        CachePurgeResult
            Result of the purge operation.

        Raises
        ------
        IntegrationError
            If no zone_id is available or the purge fails.
        """
        effective_zone = zone_id or self._zone_id
        if not effective_zone:
            raise IntegrationError("zone_id is required for cache purge operations")

        payload: Dict[str, Any] = {}
        purge_type = "everything"

        if purge_everything:
            payload["purge_everything"] = True
        elif files:
            payload["files"] = files
            purge_type = "files"
        elif tags:
            payload["tags"] = tags
            purge_type = "tags"
        elif prefixes:
            payload["prefixes"] = prefixes
            purge_type = "prefixes"
        else:
            payload["purge_everything"] = True

        log_event(
            logger, "cloudflare.purge_cache",
            zone_id=effective_zone, purge_type=purge_type,
            file_count=len(files) if files else 0,
        )

        path = f"/zones/{effective_zone}/purge_cache"
        self._api_request("POST", path, json_data=payload)

        result = CachePurgeResult(
            zone_id=effective_zone,
            purge_type=purge_type,
            files_purged=len(files) if files else 0,
            success=True,
        )

        self.logger.info(
            "Cache purge completed for zone %s (type=%s)",
            effective_zone, purge_type,
        )
        return result

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying HTTP session."""
        self._session.close()
        self.logger.debug("Cloudflare hosting session closed")

    @property
    def request_count(self) -> int:
        """Return the total number of API requests made."""
        return self._request_count

    def __repr__(self) -> str:
        return (
            f"CloudflareHosting(account_id={self._account_id!r}, "
            f"zone_id={self._zone_id!r}, requests={self._request_count})"
        )
