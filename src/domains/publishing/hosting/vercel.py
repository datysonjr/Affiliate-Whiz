"""
domains.publishing.hosting.vercel
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Vercel hosting integration for the OpenClaw publishing domain.

Provides the :class:`VercelHosting` class for managing deployments, domains,
and project configuration via the Vercel REST API.  Used by the publishing
pipeline to deploy generated static sites for affiliate content.

Design references:
    - https://vercel.com/docs/rest-api
    - ARCHITECTURE.md  Section 4 (Publishing Domain)
    - config/providers.yaml  ``hosting.vercel`` section
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

logger = get_logger("publishing.hosting.vercel")

_BASE_URL = "https://api.vercel.com"


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------


@dataclass
class VercelDeployment:
    """A single Vercel deployment record.

    Attributes
    ----------
    deployment_id:
        Vercel-assigned deployment identifier.
    name:
        Project name.
    url:
        Deployment URL (e.g. ``"my-site-abc123.vercel.app"``).
    state:
        Deployment state (``"READY"``, ``"BUILDING"``, ``"ERROR"``,
        ``"QUEUED"``, ``"CANCELED"``).
    target:
        Deployment target (``"production"`` or ``"preview"``).
    created_at:
        UTC timestamp when the deployment was created.
    ready_at:
        UTC timestamp when the deployment became ready.
    commit_sha:
        Git commit SHA associated with this deployment.
    commit_message:
        Git commit message.
    branch:
        Git branch name.
    metadata:
        Additional Vercel-specific data.
    """

    deployment_id: str
    name: str = ""
    url: str = ""
    state: str = "QUEUED"
    target: str = "production"
    created_at: Optional[datetime] = None
    ready_at: Optional[datetime] = None
    commit_sha: str = ""
    commit_message: str = ""
    branch: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class VercelDomain:
    """A custom domain configured on a Vercel project.

    Attributes
    ----------
    domain:
        Fully qualified domain name.
    project_id:
        Associated Vercel project ID.
    redirect:
        Redirect target domain (empty if this is the primary domain).
    verified:
        Whether DNS verification has passed.
    ssl_configured:
        Whether SSL is active and properly configured.
    created_at:
        UTC timestamp when the domain was added.
    """

    domain: str
    project_id: str = ""
    redirect: str = ""
    verified: bool = False
    ssl_configured: bool = False
    created_at: Optional[datetime] = None


@dataclass
class VercelProject:
    """Summary of a Vercel project.

    Attributes
    ----------
    project_id:
        Vercel project identifier.
    name:
        Project name.
    framework:
        Detected or configured framework (e.g. ``"nextjs"``, ``"astro"``).
    node_version:
        Node.js version used for builds.
    domains:
        List of custom domains attached to the project.
    latest_deployment_url:
        URL of the most recent production deployment.
    created_at:
        UTC timestamp when the project was created.
    """

    project_id: str
    name: str = ""
    framework: str = ""
    node_version: str = ""
    domains: List[str] = field(default_factory=list)
    latest_deployment_url: str = ""
    created_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# VercelHosting client
# ---------------------------------------------------------------------------


class VercelHosting:
    """Client for managing hosting via the Vercel REST API.

    Authenticates with a Vercel access token (personal or team-scoped).
    All methods support an optional ``team_id`` for team-scoped operations.

    Parameters
    ----------
    api_token:
        Vercel personal access token or team token.
    team_id:
        Optional Vercel team ID for team-scoped API calls.
    timeout:
        Per-request HTTP timeout in seconds.
    max_retries:
        Maximum number of retry attempts for transient failures.

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
        team_id: str = "",
        timeout: int = DEFAULT_REQUEST_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> None:
        if requests is None:
            raise IntegrationError(
                "The 'requests' package is required for VercelHosting. "
                "Install it with: pip install requests"
            )
        if not api_token:
            raise APIAuthenticationError(
                "Vercel hosting integration requires an api_token",
                details={"team_id": team_id},
            )

        self._api_token = api_token
        self._team_id = team_id
        self._timeout = timeout
        self._max_retries = max_retries
        self._request_count: int = 0
        self.logger: logging.Logger = get_logger("publishing.hosting.vercel")

        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {api_token}",
                "Content-Type": "application/json",
            }
        )

        log_event(logger, "vercel.init", has_team_id=bool(team_id))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_params(self, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Build query parameters, including team_id if set.

        Parameters
        ----------
        extra:
            Additional query parameters.

        Returns
        -------
        dict[str, Any]
            Merged parameters.
        """
        params: Dict[str, Any] = {}
        if self._team_id:
            params["teamId"] = self._team_id
        if extra:
            params.update(extra)
        return params

    def _api_request(
        self,
        method: str,
        path: str,
        *,
        json_data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Execute an authenticated request against the Vercel API.

        Parameters
        ----------
        method:
            HTTP method.
        path:
            API path (e.g. ``"/v13/deployments"``).
        json_data:
            Optional JSON request body.
        params:
            Optional query parameters.

        Returns
        -------
        Any
            Parsed JSON response body.

        Raises
        ------
        IntegrationError
            If the request fails.
        """
        url = f"{_BASE_URL}{path}"
        merged_params = self._build_params(params)

        try:
            response = self._session.request(
                method=method,
                url=url,
                json=json_data,
                params=merged_params,
                timeout=self._timeout,
            )
            response.raise_for_status()
            self._request_count += 1
            return response.json() if response.content else {}
        except Exception as exc:
            raise IntegrationError(
                f"Vercel API request failed: {method} {path}",
                details={
                    "method": method,
                    "path": path,
                    "status_code": getattr(
                        getattr(exc, "response", None), "status_code", None
                    ),
                },
                cause=exc,
            ) from exc

    @staticmethod
    def _parse_timestamp(value: Any) -> Optional[datetime]:
        """Parse a Vercel millisecond-epoch timestamp.

        Parameters
        ----------
        value:
            Timestamp in milliseconds since epoch, or ``None``.

        Returns
        -------
        datetime or None
            UTC datetime.
        """
        if not value:
            return None
        try:
            return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)
        except (ValueError, TypeError, OSError):
            return None

    # ------------------------------------------------------------------
    # Deployments
    # ------------------------------------------------------------------

    def deploy(
        self,
        project_name: str,
        *,
        target: str = "production",
        git_source: Optional[Dict[str, str]] = None,
        files: Optional[List[Dict[str, str]]] = None,
    ) -> VercelDeployment:
        """Trigger a new deployment on Vercel.

        Either ``git_source`` (for Git-connected projects) or ``files``
        (for direct file uploads) should be provided.

        Parameters
        ----------
        project_name:
            Vercel project name or ID.
        target:
            Deployment target: ``"production"`` or ``"preview"``.
        git_source:
            Git source with ``"repo"``, ``"ref"``, and optional ``"sha"``.
        files:
            File dicts with ``"file"`` (path) and ``"data"`` (base64) keys.

        Returns
        -------
        VercelDeployment
            The initiated deployment record.

        Raises
        ------
        IntegrationError
            If the deployment cannot be created.
        """
        payload: Dict[str, Any] = {"name": project_name, "target": target}
        if git_source:
            payload["gitSource"] = git_source
        if files:
            payload["files"] = files

        log_event(
            logger,
            "vercel.deploy",
            project=project_name,
            target=target,
            has_git=bool(git_source),
            has_files=bool(files),
        )

        data = self._api_request("POST", "/v13/deployments", json_data=payload)

        return VercelDeployment(
            deployment_id=data.get("id", ""),
            name=data.get("name", project_name),
            url=data.get("url", ""),
            state=data.get("readyState", data.get("state", "QUEUED")),
            target=data.get("target", target),
            created_at=self._parse_timestamp(data.get("createdAt")),
            ready_at=self._parse_timestamp(data.get("ready")),
            commit_sha=data.get("meta", {}).get("githubCommitSha", ""),
            commit_message=data.get("meta", {}).get("githubCommitMessage", ""),
            branch=data.get("meta", {}).get("githubCommitRef", ""),
            metadata=data,
        )

    def get_deployments(
        self,
        project_name: str,
        *,
        target: str = "",
        state: str = "",
        limit: int = 20,
    ) -> List[VercelDeployment]:
        """List recent deployments for a project.

        Parameters
        ----------
        project_name:
            Vercel project name or ID.
        target:
            Optional filter by target.
        state:
            Optional filter by state.
        limit:
            Maximum number of deployments to return.

        Returns
        -------
        list[VercelDeployment]
            Deployment records sorted by creation time (newest first).
        """
        params: Dict[str, Any] = {
            "projectId": project_name,
            "limit": min(limit, 100),
        }
        if target:
            params["target"] = target
        if state:
            params["state"] = state

        log_event(
            logger,
            "vercel.get_deployments",
            project=project_name,
            limit=limit,
        )

        data = self._api_request("GET", "/v6/deployments", params=params)
        deployments: List[VercelDeployment] = []

        for item in data.get("deployments", []):
            meta = item.get("meta", {})
            deployments.append(
                VercelDeployment(
                    deployment_id=item.get("uid", ""),
                    name=item.get("name", ""),
                    url=item.get("url", ""),
                    state=item.get("readyState", item.get("state", "")),
                    target=item.get("target", ""),
                    created_at=self._parse_timestamp(item.get("createdAt")),
                    ready_at=self._parse_timestamp(item.get("ready")),
                    commit_sha=meta.get("githubCommitSha", ""),
                    commit_message=meta.get("githubCommitMessage", ""),
                    branch=meta.get("githubCommitRef", ""),
                )
            )

        self.logger.debug(
            "Retrieved %d deployments for project %s", len(deployments), project_name
        )
        return deployments

    # ------------------------------------------------------------------
    # Domains
    # ------------------------------------------------------------------

    def get_domains(self, project_name: str) -> List[VercelDomain]:
        """List custom domains configured for a Vercel project.

        Parameters
        ----------
        project_name:
            Vercel project name or ID.

        Returns
        -------
        list[VercelDomain]
            Domain records with verification and SSL status.
        """
        log_event(logger, "vercel.get_domains", project=project_name)

        data = self._api_request("GET", f"/v9/projects/{project_name}/domains")
        domains: List[VercelDomain] = []

        for item in data.get("domains", []):
            verification = item.get("verification", [])
            domains.append(
                VercelDomain(
                    domain=item.get("name", ""),
                    project_id=item.get("projectId", project_name),
                    redirect=item.get("redirect", ""),
                    verified=item.get("verified", False),
                    ssl_configured=not any(
                        v.get("type") == "pending" for v in verification
                    )
                    if verification
                    else True,
                    created_at=self._parse_timestamp(item.get("createdAt")),
                )
            )

        self.logger.debug(
            "Retrieved %d domains for project %s", len(domains), project_name
        )
        return domains

    def configure_domain(
        self,
        project_name: str,
        domain: str,
        *,
        redirect: str = "",
        git_branch: str = "",
    ) -> VercelDomain:
        """Add or configure a custom domain on a Vercel project.

        Parameters
        ----------
        project_name:
            Vercel project name or ID.
        domain:
            Fully qualified domain name to add.
        redirect:
            Optional redirect target domain.
        git_branch:
            Optional Git branch to associate with this domain.

        Returns
        -------
        VercelDomain
            The configured domain record.

        Raises
        ------
        IntegrationError
            If domain configuration fails.
        """
        if not domain:
            raise IntegrationError("domain is required for configure_domain")

        payload: Dict[str, Any] = {"name": domain}
        if redirect:
            payload["redirect"] = redirect
        if git_branch:
            payload["gitBranch"] = git_branch

        log_event(
            logger,
            "vercel.configure_domain",
            project=project_name,
            domain=domain,
        )

        data = self._api_request(
            "POST",
            f"/v10/projects/{project_name}/domains",
            json_data=payload,
        )

        result = VercelDomain(
            domain=data.get("name", domain),
            project_id=data.get("projectId", project_name),
            redirect=data.get("redirect", redirect),
            verified=data.get("verified", False),
            created_at=self._parse_timestamp(data.get("createdAt")),
        )

        self.logger.info(
            "Configured domain '%s' on project '%s' (verified=%s)",
            result.domain,
            project_name,
            result.verified,
        )
        return result

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying HTTP session."""
        self._session.close()
        self.logger.debug("Vercel hosting session closed")

    @property
    def request_count(self) -> int:
        """Return the total number of API requests made."""
        return self._request_count

    def __repr__(self) -> str:
        return (
            f"VercelHosting(team_id={self._team_id!r}, requests={self._request_count})"
        )
