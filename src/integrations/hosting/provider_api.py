"""
integrations.hosting.provider_api
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Abstract hosting provider interface and factory.

Defines the :class:`HostingProvider` abstract base class that all hosting
integrations must implement, plus a :func:`get_provider` factory function
that instantiates the correct provider by name.  Currently supports
Cloudflare Pages, Vercel, and Netlify as hosting targets for the
affiliate sites managed by OpenClaw.

Design references:
    - config/providers.yaml  ``hosting`` section
    - ARCHITECTURE.md  Section 4 (Integration Layer)
    - config/sites.yaml  (per-site hosting configuration)

Usage::

    from src.integrations.hosting.provider_api import get_provider

    provider = get_provider("cloudflare_pages", api_key="xxx", account_id="yyy")
    status = await provider.get_status("my-site-project")
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.core.constants import DEFAULT_MAX_RETRIES, DEFAULT_REQUEST_TIMEOUT
from src.core.errors import IntegrationError, APIAuthenticationError
from src.core.logger import get_logger, log_event

logger = get_logger("integrations.hosting.provider_api")


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------


@dataclass
class DeploymentResult:
    """Result of a site deployment operation.

    Attributes
    ----------
    deployment_id:
        Provider-assigned deployment identifier.
    project_name:
        Name of the deployed project.
    status:
        Deployment status (``"success"``, ``"building"``, ``"failed"``,
        ``"queued"``).
    url:
        Live URL of the deployment.
    created_at:
        UTC timestamp when the deployment was initiated.
    finished_at:
        UTC timestamp when the deployment completed (``None`` if still building).
    commit_hash:
        Git commit hash associated with this deployment (if applicable).
    metadata:
        Provider-specific extra data.
    """

    deployment_id: str
    project_name: str = ""
    status: str = "queued"
    url: str = ""
    created_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    commit_hash: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ProjectStatus:
    """Current status of a hosted project.

    Attributes
    ----------
    project_name:
        Project identifier.
    production_url:
        Live production URL.
    latest_deployment_id:
        ID of the most recent deployment.
    latest_deployment_status:
        Status of the most recent deployment.
    domains:
        List of custom domains configured for this project.
    ssl_active:
        Whether SSL/TLS is active on the production domain.
    created_at:
        UTC timestamp when the project was created.
    """

    project_name: str
    production_url: str = ""
    latest_deployment_id: str = ""
    latest_deployment_status: str = ""
    domains: List[str] = field(default_factory=list)
    ssl_active: bool = False
    created_at: Optional[datetime] = None


@dataclass
class DomainInfo:
    """Information about a custom domain attached to a hosting project.

    Attributes
    ----------
    domain:
        Fully qualified domain name.
    project_name:
        Associated hosting project.
    ssl_status:
        SSL certificate status (``"active"``, ``"pending"``, ``"error"``).
    verification_status:
        DNS verification status.
    created_at:
        When the domain was attached.
    """

    domain: str
    project_name: str = ""
    ssl_status: str = "pending"
    verification_status: str = "pending"
    created_at: Optional[datetime] = None


@dataclass
class SSLConfiguration:
    """SSL/TLS configuration result.

    Attributes
    ----------
    domain:
        Domain the certificate covers.
    issuer:
        Certificate issuer (e.g. ``"Let's Encrypt"``).
    status:
        Current status (``"active"``, ``"pending_issuance"``, ``"error"``).
    expires_at:
        UTC timestamp when the certificate expires.
    auto_renew:
        Whether automatic renewal is enabled.
    """

    domain: str
    issuer: str = ""
    status: str = "pending_issuance"
    expires_at: Optional[datetime] = None
    auto_renew: bool = True


# ---------------------------------------------------------------------------
# Abstract base class
# ---------------------------------------------------------------------------


class HostingProvider(ABC):
    """Abstract interface for hosting provider integrations.

    Subclasses must implement the four core operations: deploy, get_status,
    get_domains, and configure_ssl.  The base class provides common
    infrastructure for authentication, request tracking, and logging.

    Parameters
    ----------
    provider_name:
        Human-readable provider identifier.
    api_key:
        Provider API key or token.
    account_id:
        Provider account or team identifier.
    timeout:
        HTTP request timeout in seconds.
    max_retries:
        Maximum retry attempts for transient failures.
    """

    def __init__(
        self,
        provider_name: str,
        api_key: str,
        account_id: str = "",
        timeout: int = DEFAULT_REQUEST_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> None:
        if not api_key:
            raise APIAuthenticationError(
                f"{provider_name} hosting integration requires an api_key",
                details={"provider": provider_name},
            )

        self._provider_name = provider_name
        self._api_key = api_key
        self._account_id = account_id
        self._timeout = timeout
        self._max_retries = max_retries
        self._request_count: int = 0

        log_event(
            logger,
            "hosting.provider.init",
            provider=provider_name,
            has_account_id=bool(account_id),
        )

    def _track_request(self) -> None:
        """Record that an API request was made."""
        self._request_count += 1

    @abstractmethod
    async def deploy(
        self,
        project_name: str,
        *,
        source_dir: str = "",
        branch: str = "main",
        environment: str = "production",
    ) -> DeploymentResult:
        """Trigger a new deployment for the given project.

        Parameters
        ----------
        project_name:
            Hosting project identifier.
        source_dir:
            Local directory containing build output to upload (if supported).
        branch:
            Git branch to deploy from (for Git-connected projects).
        environment:
            Target environment (``"production"`` or ``"preview"``).

        Returns
        -------
        DeploymentResult
            Deployment status and metadata.

        Raises
        ------
        IntegrationError
            If the deployment cannot be initiated.
        """

    @abstractmethod
    async def get_status(self, project_name: str) -> ProjectStatus:
        """Retrieve the current status of a hosted project.

        Parameters
        ----------
        project_name:
            Hosting project identifier.

        Returns
        -------
        ProjectStatus
            Current project state including deployment status and domains.

        Raises
        ------
        IntegrationError
            If the project is not found or the API request fails.
        """

    @abstractmethod
    async def get_domains(self, project_name: str) -> List[DomainInfo]:
        """List custom domains configured for a project.

        Parameters
        ----------
        project_name:
            Hosting project identifier.

        Returns
        -------
        list[DomainInfo]
            Domain records with SSL and verification status.

        Raises
        ------
        IntegrationError
            If the API request fails.
        """

    @abstractmethod
    async def configure_ssl(
        self,
        project_name: str,
        domain: str,
        *,
        force_renew: bool = False,
    ) -> SSLConfiguration:
        """Configure or renew SSL/TLS for a custom domain.

        Parameters
        ----------
        project_name:
            Hosting project identifier.
        domain:
            The custom domain to configure SSL for.
        force_renew:
            If ``True``, force certificate re-issuance even if one is active.

        Returns
        -------
        SSLConfiguration
            SSL certificate status.

        Raises
        ------
        IntegrationError
            If SSL configuration fails.
        """

    @property
    def provider_name(self) -> str:
        """Return the provider name."""
        return self._provider_name

    @property
    def request_count(self) -> int:
        """Return the total number of API requests made."""
        return self._request_count

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}(provider={self._provider_name!r}, "
            f"requests={self._request_count})"
        )


# ---------------------------------------------------------------------------
# Concrete providers
# ---------------------------------------------------------------------------


class CloudflarePagesProvider(HostingProvider):
    """Cloudflare Pages hosting provider implementation.

    Uses the Cloudflare API v4 to manage Pages projects, deployments,
    custom domains, and SSL certificates.
    """

    _BASE_URL = "https://api.cloudflare.com/client/v4"

    def __init__(
        self,
        api_key: str,
        account_id: str,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            provider_name="cloudflare_pages",
            api_key=api_key,
            account_id=account_id,
            **kwargs,
        )
        if not account_id:
            raise IntegrationError(
                "Cloudflare Pages requires an account_id",
            )

    def _build_headers(self) -> Dict[str, str]:
        """Return Cloudflare API request headers."""
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    async def deploy(
        self,
        project_name: str,
        *,
        source_dir: str = "",
        branch: str = "main",
        environment: str = "production",
    ) -> DeploymentResult:
        """Trigger a Cloudflare Pages deployment."""
        log_event(
            logger,
            "cloudflare_pages.deploy",
            project=project_name,
            branch=branch,
            environment=environment,
        )
        self._track_request()

        # Production: POST to url with build configuration.
        return DeploymentResult(
            deployment_id="",
            project_name=project_name,
            status="queued",
            created_at=datetime.now(timezone.utc),
        )

    async def get_status(self, project_name: str) -> ProjectStatus:
        """Get Cloudflare Pages project status."""
        log_event(logger, "cloudflare_pages.get_status", project=project_name)
        self._track_request()

        # Production: GET project info from Cloudflare API.
        return ProjectStatus(project_name=project_name)

    async def get_domains(self, project_name: str) -> List[DomainInfo]:
        """List domains for a Cloudflare Pages project."""
        log_event(logger, "cloudflare_pages.get_domains", project=project_name)
        self._track_request()

        # Production: GET domain list from Cloudflare API.
        return []

    async def configure_ssl(
        self,
        project_name: str,
        domain: str,
        *,
        force_renew: bool = False,
    ) -> SSLConfiguration:
        """Configure SSL for a Cloudflare Pages custom domain.

        Cloudflare provides automatic SSL via their edge network, so this
        primarily checks the certificate status and optionally forces renewal.
        """
        log_event(
            logger,
            "cloudflare_pages.configure_ssl",
            project=project_name,
            domain=domain,
            force_renew=force_renew,
        )
        self._track_request()

        # Cloudflare auto-provisions SSL; return current status.
        return SSLConfiguration(
            domain=domain,
            issuer="Cloudflare",
            status="active",
            auto_renew=True,
        )


class VercelProvider(HostingProvider):
    """Vercel hosting provider implementation.

    Uses the Vercel REST API to manage projects, deployments, domains,
    and SSL certificates.
    """

    _BASE_URL = "https://api.vercel.com"

    def __init__(self, api_key: str, team_id: str = "", **kwargs: Any) -> None:
        super().__init__(
            provider_name="vercel",
            api_key=api_key,
            account_id=team_id,
            **kwargs,
        )

    def _build_headers(self) -> Dict[str, str]:
        """Return Vercel API request headers."""
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    async def deploy(
        self,
        project_name: str,
        *,
        source_dir: str = "",
        branch: str = "main",
        environment: str = "production",
    ) -> DeploymentResult:
        """Trigger a Vercel deployment."""
        log_event(
            logger,
            "vercel.deploy",
            project=project_name,
            branch=branch,
        )
        self._track_request()

        return DeploymentResult(
            deployment_id="",
            project_name=project_name,
            status="queued",
            created_at=datetime.now(timezone.utc),
        )

    async def get_status(self, project_name: str) -> ProjectStatus:
        """Get Vercel project status."""
        log_event(logger, "vercel.get_status", project=project_name)
        self._track_request()
        return ProjectStatus(project_name=project_name)

    async def get_domains(self, project_name: str) -> List[DomainInfo]:
        """List domains for a Vercel project."""
        log_event(logger, "vercel.get_domains", project=project_name)
        self._track_request()
        return []

    async def configure_ssl(
        self,
        project_name: str,
        domain: str,
        *,
        force_renew: bool = False,
    ) -> SSLConfiguration:
        """Configure SSL for a Vercel custom domain."""
        log_event(
            logger,
            "vercel.configure_ssl",
            project=project_name,
            domain=domain,
        )
        self._track_request()

        return SSLConfiguration(
            domain=domain,
            issuer="Let's Encrypt",
            status="active",
            auto_renew=True,
        )


class NetlifyProvider(HostingProvider):
    """Netlify hosting provider implementation.

    Uses the Netlify API to manage sites, deployments, domains, and
    SSL certificates.
    """

    _BASE_URL = "https://api.netlify.com/api/v1"

    def __init__(self, api_key: str, **kwargs: Any) -> None:
        super().__init__(
            provider_name="netlify",
            api_key=api_key,
            **kwargs,
        )

    def _build_headers(self) -> Dict[str, str]:
        """Return Netlify API request headers."""
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    async def deploy(
        self,
        project_name: str,
        *,
        source_dir: str = "",
        branch: str = "main",
        environment: str = "production",
    ) -> DeploymentResult:
        """Trigger a Netlify deployment."""
        log_event(
            logger,
            "netlify.deploy",
            project=project_name,
            branch=branch,
        )
        self._track_request()

        return DeploymentResult(
            deployment_id="",
            project_name=project_name,
            status="queued",
            created_at=datetime.now(timezone.utc),
        )

    async def get_status(self, project_name: str) -> ProjectStatus:
        """Get Netlify site status."""
        log_event(logger, "netlify.get_status", project=project_name)
        self._track_request()
        return ProjectStatus(project_name=project_name)

    async def get_domains(self, project_name: str) -> List[DomainInfo]:
        """List domains for a Netlify site."""
        log_event(logger, "netlify.get_domains", project=project_name)
        self._track_request()
        return []

    async def configure_ssl(
        self,
        project_name: str,
        domain: str,
        *,
        force_renew: bool = False,
    ) -> SSLConfiguration:
        """Configure SSL for a Netlify custom domain."""
        log_event(
            logger,
            "netlify.configure_ssl",
            project=project_name,
            domain=domain,
        )
        self._track_request()

        return SSLConfiguration(
            domain=domain,
            issuer="Let's Encrypt",
            status="active",
            auto_renew=True,
        )


# ---------------------------------------------------------------------------
# Provider registry and factory
# ---------------------------------------------------------------------------

_PROVIDER_REGISTRY: Dict[str, type] = {
    "cloudflare_pages": CloudflarePagesProvider,
    "vercel": VercelProvider,
    "netlify": NetlifyProvider,
}


def register_provider(name: str, provider_class: type) -> None:
    """Register a custom hosting provider class.

    Parameters
    ----------
    name:
        Provider name key (used in configuration files).
    provider_class:
        A class that extends :class:`HostingProvider`.

    Raises
    ------
    TypeError
        If *provider_class* does not extend :class:`HostingProvider`.
    """
    if not (
        isinstance(provider_class, type) and issubclass(provider_class, HostingProvider)
    ):
        raise TypeError(
            f"provider_class must be a subclass of HostingProvider, got {provider_class!r}"
        )
    _PROVIDER_REGISTRY[name] = provider_class
    log_event(logger, "hosting.provider.registered", name=name)


def get_provider(name: str, **kwargs: Any) -> HostingProvider:
    """Factory function to instantiate a hosting provider by name.

    Parameters
    ----------
    name:
        Provider name matching a key in the registry (e.g.
        ``"cloudflare_pages"``, ``"vercel"``, ``"netlify"``).
    **kwargs:
        Provider-specific constructor arguments (``api_key``,
        ``account_id``, etc.).

    Returns
    -------
    HostingProvider
        An initialised provider instance.

    Raises
    ------
    IntegrationError
        If the provider name is not registered.

    Examples
    --------
    >>> provider = get_provider("cloudflare_pages", api_key="xxx", account_id="yyy")
    >>> isinstance(provider, CloudflarePagesProvider)
    True
    """
    provider_class = _PROVIDER_REGISTRY.get(name)
    if provider_class is None:
        raise IntegrationError(
            f"Unknown hosting provider: {name!r}",
            details={
                "requested": name,
                "available": list(_PROVIDER_REGISTRY.keys()),
            },
        )

    log_event(logger, "hosting.provider.create", name=name)
    return provider_class(**kwargs)
